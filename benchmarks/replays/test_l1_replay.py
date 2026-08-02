#!/usr/bin/env python3
"""L1 — the replay suite. Deliberately outside `testpaths`.

    uv run pytest benchmarks/replays -q

`pyproject.toml` sets `testpaths = ["skills/3d-modeling/scripts", "tools"]`, and
this directory is in neither, so a bare `uv run pytest` does not collect this
file. That is the separation, and it is structural rather than a marker somebody
has to remember to apply: ROADMAP.md section 4.4 budgets the commit-gating L0
suite at about five seconds and the L1 replay suite at about two minutes, and
those two numbers stop meaning anything the moment one suite can silently run
inside the other. The unit suite is 992 s wall clock on the reference machine
today; hiding a job replay in it would make a slow suite slower and an L1 budget
unmeasurable at the same time.

CI runs them as two steps for the same reason: `uv run pytest` on every push, and
`uv run pytest benchmarks/replays` on pull requests, which is where section 5.1
says L1 belongs.

The guards on the harness itself are L0 and live in `tools/test_replay.py`, so
the commit-gating suite still pays for the thing that decides whether a replay
passed -- just not for the jobs.

What each case is, what it was recorded against, and the argument for what a
replay asserts and what it deliberately does not, are in `tools/replay.py`'s
module docstring and in each case's `case.json`. This file is the suite; that
file is the reasoning.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

# `replay` first: it is the module that puts `tools/` and the scripts directory
# on the path, and it is the one authority for where they are. Importing the
# fixture register above it would work only from a checkout whose `pythonpath`
# already happened to cover it.
from tools import replay as RP
import fixtures as FX


class _CaseChecks:
    """One recorded job, played once for the whole class.

    Once, because the point of the budget is that a replay costs what the job
    costs; running it per test method would multiply that by the number of
    questions being asked of one run, which is the wrong shape entirely.

    Deliberately not a `TestCase`. A shared base that was one would be collected
    on its own, and eight tests skipping under a name nobody recognises reads
    exactly like eight tests that stopped working.
    """

    CASE_ID: str = ""

    @classmethod
    def setUpClass(cls) -> None:
        cls.case = RP.load(cls.CASE_ID)
        cls._raw = tempfile.TemporaryDirectory()
        try:
            cls.project = RP.materialise(cls.case, Path(cls._raw.name) / "project")
        except FX.FixtureUnavailable as exc:
            cls._raw.cleanup()
            raise unittest.SkipTest(str(exc))
        cls.play = RP.play(cls.case, cls.project)
        cls.observed = RP.observe(cls.case, cls.play)
        cls.recorded = RP.expected(cls.CASE_ID)

    @classmethod
    def tearDownClass(cls) -> None:
        if getattr(cls, "_raw", None) is not None:
            cls._raw.cleanup()

    # -- the layered comparison -------------------------------------------
    def test_the_replay_matches_what_was_recorded(self) -> None:
        differences = RP.compare(self.recorded, self.observed)
        failures = RP.binding(differences)
        self.assertEqual([], failures, "\n".join(
            [f"{self.CASE_ID}: the replay no longer matches its recording.",
             "If the change was meant, re-record it and put the diff in the "
             f"review: uv run python tools/replay.py --record {self.CASE_ID}", ""]
            + [str(row) for row in failures]
            + ["", "transcript:", self.play.transcript[-2000:]]))

    def test_reworded_prose_is_reported_and_does_not_fail_the_build(self) -> None:
        """The advisory layer, asserted as advisory.

        Not decoration. If `reasons` were binding, every reworded sentence in
        `status.decide` would go red here, somebody would delete the assertion,
        and the layer above it would go with it.
        """
        for row in RP.compare(self.recorded, self.observed):
            if row.severity == RP.ADVISORY:
                print(f"  advisory: {row}")
        self.assertIn("reasons", self.recorded,
                      "the recording keeps the prose even though nothing "
                      "fails on it, because a maintainer reading expected.json "
                      "should be able to see what the run said")

    # -- zero live dispatches ---------------------------------------------
    def test_every_review_was_answered_from_the_recording(self) -> None:
        self.assertEqual(list(self.case.reviews), self.play.reviews_answered)
        self.assertEqual(sorted(self.play.responses_written),
                         sorted(path.name for path in
                                (self.project / "reviews").glob("*_response.json"))
                         if (self.project / "reviews").is_dir() else [])

    def test_nothing_is_still_waiting_for_a_judgement_nobody_recorded(self) -> None:
        """A replay that ends paused is a replay that stopped exercising the job.

        `REVIEW` means an unanswered question and `AGENT_COMMISSION` means the
        pipeline is asking a designer to author geometry -- which is the live
        dispatch itself. Either one surviving to the end means this case is
        incomplete, whatever the receipts happen to say.
        """
        pending = self.project / "next_action.json"
        if not pending.is_file():
            return
        kind = json.loads(pending.read_text(encoding="utf-8")).get("kind")
        self.assertNotIn(kind, ("REVIEW", "AGENT_COMMISSION"), kind)

    # -- the hashes that are the property ---------------------------------
    def test_the_plan_the_reviewer_saw_is_the_plan_that_ran(self) -> None:
        """An equality between two values from this run, never a pinned literal.

        `execution_plan_sha256` reached `final_status.json` alone until protocol
        4 -- written after the review it should have bound -- so a job whose lane
        cap or builder moved underneath a stored answer kept the answer.
        """
        final = json.loads((self.project / "final_status.json")
                           .read_text(encoding="utf-8"))
        plan_digest = final.get("execution_plan_sha256")
        self.assertTrue(plan_digest)
        for kind in self.case.reviews:
            with self.subTest(review=kind):
                report = json.loads(
                    (self.project / self._report_name(kind)).read_text(encoding="utf-8"))
                self.assertEqual(plan_digest,
                                 report["review_envelope"]["execution_plan_sha256"])

    def test_the_receipt_describes_the_contract_it_was_judged_against(self) -> None:
        final = json.loads((self.project / "final_status.json")
                           .read_text(encoding="utf-8"))
        manifest = json.loads((self.project / "artifact_manifest.json")
                              .read_text(encoding="utf-8"))
        self.assertEqual(manifest["contract_sha256"],
                         final["artifact_hashes"]["contract"])
        self.assertEqual(manifest["stl_sha256"], final["artifact_hashes"]["stl"])

    def test_each_answer_is_bound_to_the_question_it_was_asked(self) -> None:
        """What keeps re-binding honest.

        The harness stamps the current packet's envelope onto a recorded
        judgement. If the runner ever accepted an answer whose envelope was not
        the one it had just issued, that is the authority failure the envelope
        exists to prevent, and it would look like a passing replay without this.
        """
        for kind in self.case.reviews:
            with self.subTest(review=kind):
                packet = json.loads(
                    (self.project / "reviews" / f"{kind}_packet.json")
                    .read_text(encoding="utf-8"))
                report = json.loads(
                    (self.project / self._report_name(kind)).read_text(encoding="utf-8"))
                self.assertNotIn("error", report,
                                 "the recorded judgement was refused")
                self.assertEqual(packet["review_envelope"],
                                 report["review_envelope"])

    def test_two_replays_of_one_case_produce_the_same_geometry_and_plan(self) -> None:
        """Determinism, and the one hash a literal could never test.

        A candidate digest moves with the tessellator and a sample-plan digest
        moves with the plan version; neither move is a defect and pinning either
        would mean re-pinning it on every legitimate change. Two runs of one
        unchanged pair disagreeing *is* a defect, and it is the one that made a
        `MODIFY` review round trip impossible before the sampling was seeded.
        """
        with tempfile.TemporaryDirectory() as raw:
            second = RP.materialise(self.case, Path(raw) / "project")
            RP.play(self.case, second)
            self.assertEqual(RP.determinism_marks(self.project),
                             RP.determinism_marks(second))

    @staticmethod
    def _report_name(kind: str) -> str:
        return ("safety_verification_report.json" if kind == "safety"
                else f"{kind}_report.json")


class CustomKnobSleeveTest(_CaseChecks, unittest.TestCase):
    """A `CUSTOM` job from a recorded request: proposal, freeze, confined build.

    The smallest thing that goes all the way through the authored lane. No
    review at all, so its dispatch count is zero by construction rather than by
    accounting, and the whole case costs about two seconds.
    """

    CASE_ID = "custom-knob-sleeve"

    def test_the_acceptance_contract_was_frozen_before_the_build(self) -> None:
        frozen = json.loads((self.project / "acceptance_contract.json")
                            .read_text(encoding="utf-8"))
        self.assertEqual(1, frozen["revision"])
        self.assertEqual("pipeline", frozen["tolerance_owner"],
                         "a threshold authored by the party being measured is a "
                         "receipt rather than a gate")
        self.assertEqual("NOT_INDEPENDENTLY_SPECIFIED",
                         frozen["expected_volume_basis"],
                         "there is no independent volume for a part somebody "
                         "just drew, and the contract has to say so")

    def test_the_candidate_was_built_somewhere_else(self) -> None:
        """The confined boundary, seen from the receipt.

        `AUTHORED` is the one builder that executes code this pipeline did not
        write, and `build_boundary` is the cost of the process that is not this
        one. A run that started importing the model again would still produce
        every receipt here and would lose this line.
        """
        timings = json.loads((self.project / "timings.json")
                             .read_text(encoding="utf-8"))["seconds"]
        self.assertIn("build_boundary", timings)
        plan = json.loads((self.project / "execution_plan.json")
                          .read_text(encoding="utf-8"))
        self.assertEqual("AUTHORED", plan["builder"])

    def test_no_review_packet_was_ever_written(self) -> None:
        self.assertFalse((self.project / "reviews").exists())


class ModifyBallFlangeFlatTest(_CaseChecks, unittest.TestCase):
    """A `MODIFY` job over a real supplied artifact, with two recorded reviews.

    The edit scope, the preservation row inside the frozen contract, and a review
    round trip that pauses twice and finishes -- the three places a regression has
    actually landed.
    """

    CASE_ID = "modify-ball-flange-flat"

    def test_the_preservation_row_is_inside_the_frozen_contract(self) -> None:
        """A contract feature, not a report written afterwards.

        A preservation audit that could only be read in its own JSON would be a
        receipt: nothing downstream would refuse a job for failing it.
        """
        frozen = json.loads((self.project / "acceptance_contract.json")
                            .read_text(encoding="utf-8"))
        row = next(feature for feature in frozen["features"]
                   if feature["feature_id"] == "preservation-ball-17mm")
        self.assertEqual("preservation", row["kind"])
        self.assertEqual(0.1, row["tolerance_mm"])
        self.assertEqual("ball_male_17mm.stl", row["source"])

    def test_the_audit_measured_the_supplied_bytes(self) -> None:
        """Through the fixture register, so the bytes are the recorded ones."""
        declared = FX.public("vent-ball-combine").sources[1]
        self.assertEqual("ball_male_17mm.stl", declared.name)
        self.assertEqual(declared.sha256,
                         RP.digest_of(self.project / "ball_male_17mm.stl"),
                         "the job was given the bytes the fixture register "
                         "records, which are the bytes the real run consumed")
        row = next(check for check in json.loads(
            (self.project / "commission_report.json").read_text(encoding="utf-8")
        )["checks"] if check["check_id"] == "feature-preservation-ball-17mm")
        self.assertEqual("sampled bidirectional surface distance",
                         row["measured"]["method"],
                         "a mesh pair can only be compared by sampling, and the "
                         "claim may not outrun the instrument")
        self.assertEqual("PRESERVED_WITHIN_TOLERANCE", row["measured"]["verdict"])

    def test_the_round_trip_paused_twice_and_finished(self) -> None:
        self.assertEqual(["safety", "verification"], self.play.reviews_answered)
        self.assertEqual([0, RP.NEEDS_ACTION, RP.NEEDS_ACTION, RP.NEEDS_ACTION],
                         self.play.exit_codes)

    def test_the_rerun_did_not_move_the_evidence_under_the_answer(self) -> None:
        """Why a `MODIFY` round trip is possible at all.

        Before the sampling was seeded, the second run re-measured preservation
        with a fresh random draw, produced a different commissioning report, and
        the answer written against the first packet no longer matched the second
        envelope. There was no answer anybody could write. That the two reviews
        here are both bound is the standing proof that it stayed fixed.
        """
        for kind in ("safety", "verification"):
            with self.subTest(review=kind):
                envelope = json.loads(
                    (self.project / "reviews" / f"{kind}_packet.json")
                    .read_text(encoding="utf-8"))["review_envelope"]
                digests = envelope["evidence_digests"]
                self.assertEqual(
                    {"feature-preservation-ball-17mm.sample_plan_sha256",
                     "feature-preservation-ball-17mm.evidence_sha256"},
                    set(digests))


class TheBindingStillBitesTest(unittest.TestCase):
    """The adversarial half, and the reason re-binding is not a hole.

    ROADMAP.md section 4.3 asks for a test that shows the principal protection
    can fail. The principal protection of *this* harness is the review envelope:
    the harness deliberately re-binds a recorded judgement, so the whole
    arrangement is only sound while an answer bound to something else is still
    refused. Here one is, on a real run, and the run has to stop.

    Note what it does *not* assert: that the harness raises. The refusal is the
    pipeline's, not the harness's -- `design-tool` writes an error receipt and
    exits 1 -- and a replay that could only detect a refusal by crashing would be
    one that never noticed a job failing quietly. What is asserted is the whole
    consequence: the run stopped, said why, left no decision and no final status,
    and the layered comparison against the recording went red.
    """

    CASE_ID = "modify-ball-flange-flat"

    def test_a_judgement_bound_to_another_question_is_refused(self) -> None:
        case = RP.load(self.CASE_ID)
        with tempfile.TemporaryDirectory() as raw:
            try:
                project = RP.materialise(case, Path(raw) / "project")
            except FX.FixtureUnavailable as exc:
                self.skipTest(str(exc))

            def wrong(kind: str, packet: dict) -> dict:
                # Every field the run issued, with one digest replaced. Not a
                # fabricated envelope: an envelope for a job whose preservation
                # evidence moved, which is the case the binding exists for.
                return {**packet["review_envelope"],
                        "evidence_digests": {key: "0" * 64 for key in
                                             (packet["review_envelope"]
                                              ["evidence_digests"] or {})}}

            run = RP.play(case, project, envelope_for=wrong)

            self.assertEqual([0, RP.NEEDS_ACTION, 1], run.exit_codes,
                             "the run must pause for safety, be handed an answer "
                             "bound to something else, and stop")
            self.assertEqual(["safety"], run.reviews_answered)

            report = json.loads((project / "safety_verification_report.json")
                                .read_text(encoding="utf-8"))
            self.assertIn("ReviewError", report["error"])
            self.assertIn("review envelope mismatch", report["error"])
            self.assertNotIn("decision", report,
                             "a refused answer must not leave a decision behind")
            self.assertFalse((project / "final_status.json").is_file(),
                             "an unbound answer must not produce a final status")
            self.assertFalse((project / "verification_report.json").is_file(),
                             "the second review must never have been reached")

            failures = RP.binding(
                RP.compare(RP.expected(self.CASE_ID),
                           RP.observe(case, run)))
            self.assertTrue(failures,
                            "a wrongly-bound answer has to make the replay go "
                            "red. If this passes, the comparison is not reading "
                            "the thing it claims to read.")


if __name__ == "__main__":
    unittest.main()
