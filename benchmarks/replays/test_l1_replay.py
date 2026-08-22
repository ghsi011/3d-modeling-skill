#!/usr/bin/env python3
"""L1 — the replay suite. Deliberately outside `testpaths`.

    uv run pytest benchmarks/replays -q

`pyproject.toml` sets `testpaths = ["skills/3d-modeling/scripts", "tools"]`, and
this directory is in neither, so a bare `uv run pytest` does not collect this
file. That is the separation, and it is structural rather than a marker somebody
has to remember to apply: ROADMAP.md section 4.4 budgets each suite, and those
numbers stop meaning anything the moment one can silently run inside another.

`benchmarks/heavy` is outside `testpaths` by the same mechanism and for the same
reason one rung down -- the commit gate was 994 s when this file was written,
because everything that starts a child interpreter was still in it. It is 43 s
now. See `benchmarks/heavy/README.md`.

CI runs L0 on every push and this suite on pull requests, which is where section
5.1 says L1 belongs; the heavy tier shares this trigger.

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
        blocks = (list((self.recorded.get("formulations") or {}).values())
                  or [self.recorded])
        for block in blocks:
            self.assertIn("reasons", block,
                          "the recording keeps the prose even though nothing "
                          "fails on it, because a maintainer reading "
                          "expected.json should be able to see what the run said")

    # -- zero live dispatches ---------------------------------------------
    def test_every_review_was_answered_from_the_recording(self) -> None:
        self.assertEqual(list(self.case.reviews), self.play.reviews_answered)
        # Project-relative and walked to the bottom: two formulations each
        # answering one `verification` review are two answers, and under the bare
        # filename they were one.
        self.assertEqual(sorted(self.play.responses_written),
                         sorted(path.relative_to(self.project).as_posix()
                                for path in self.project.rglob("*_response.json")
                                if path.parent.name == "reviews"))

    def test_the_case_concluded_the_way_it_says_it_does(self) -> None:
        """`concludes` is a declaration and this is what makes it one.

        A case that stopped building would otherwise go quiet rather than red:
        every assertion about a receipt it no longer writes is an assertion about
        a file that is absent, and absence compares equal to absence.
        """
        for key, directory in self.play.work_dirs.items():
            with self.subTest(formulation=key):
                built = (directory / "final_status.json").is_file()
                self.assertEqual(self.case.concludes == "BUILT", built,
                                 f"case.json says this job {self.case.concludes} "
                                 f"and {directory / 'final_status.json'} "
                                 f"{'exists' if built else 'does not exist'}")

    def test_nothing_is_still_waiting_for_a_judgement_nobody_recorded(self) -> None:
        """A replay that ends paused is a replay that stopped exercising the job.

        `REVIEW` means an unanswered question and `AGENT_COMMISSION` means the
        pipeline is asking a designer to author geometry -- which is the live
        dispatch itself. Either one surviving to the end means this case is
        incomplete, whatever the receipts happen to say.

        Every formulation's own instruction, not the project root's: on a
        branched job the root's is the ancestor's, and a branch left waiting for
        a review nobody answered would be invisible from there.
        """
        for key, directory in self.play.work_dirs.items():
            pending = directory / "next_action.json"
            if not pending.is_file():
                continue
            with self.subTest(formulation=key):
                kind = json.loads(pending.read_text(encoding="utf-8")).get("kind")
                self.assertNotIn(kind, ("REVIEW", "AGENT_COMMISSION"), kind)

    # -- the hashes that are the property ---------------------------------
    #
    # Every one is over each formulation's *own* directory. On an unbranched job
    # that is the project root and nothing about them changed; on a branched one
    # reading the root would be reading whichever sibling happened to write
    # there, which is the failure the work directory exists to remove.
    def test_the_plan_the_reviewer_saw_is_the_plan_that_ran(self) -> None:
        """An equality between two values from this run, never a pinned literal.

        `execution_plan_sha256` reached `final_status.json` alone until protocol
        4 -- written after the review it should have bound -- so a job whose lane
        cap or builder moved underneath a stored answer kept the answer.
        """
        for formulation, work in self._built():
            final = json.loads((work / "final_status.json")
                               .read_text(encoding="utf-8"))
            plan_digest = final.get("execution_plan_sha256")
            self.assertTrue(plan_digest)
            for kind in formulation.reviews:
                with self.subTest(formulation=formulation.key, review=kind):
                    report = json.loads((work / self._report_name(kind))
                                        .read_text(encoding="utf-8"))
                    self.assertEqual(
                        plan_digest,
                        report["review_envelope"]["execution_plan_sha256"])

    def test_the_receipt_describes_the_contract_it_was_judged_against(self) -> None:
        for formulation, work in self._built():
            with self.subTest(formulation=formulation.key):
                final = json.loads((work / "final_status.json")
                                   .read_text(encoding="utf-8"))
                manifest = json.loads((work / "pipeline_artifact_receipt.json")
                                      .read_text(encoding="utf-8"))
                self.assertEqual(manifest["contract_sha256"],
                                 final["artifact_hashes"]["contract"])
                self.assertEqual(manifest["stl_sha256"],
                                 final["artifact_hashes"]["stl"])

    def test_each_answer_is_bound_to_the_question_it_was_asked(self) -> None:
        """What keeps re-binding honest.

        The harness stamps the current packet's envelope onto a recorded
        judgement. If the runner ever accepted an answer whose envelope was not
        the one it had just issued, that is the authority failure the envelope
        exists to prevent, and it would look like a passing replay without this.
        """
        for formulation, work in self._built():
            for kind in formulation.reviews:
                with self.subTest(formulation=formulation.key, review=kind):
                    packet = json.loads(
                        (work / "reviews" / f"{kind}_packet.json")
                        .read_text(encoding="utf-8"))
                    report = json.loads((work / self._report_name(kind))
                                        .read_text(encoding="utf-8"))
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
            replayed = RP.play(self.case, second)
            self.assertEqual(sorted(self.play.work_dirs),
                             sorted(replayed.work_dirs))
            self.assertEqual(
                {key: RP.determinism_marks(work)
                 for key, work in self.play.work_dirs.items()},
                {key: RP.determinism_marks(work)
                 for key, work in replayed.work_dirs.items()})

    def _built(self):
        """Each formulation and its work directory, for a case that builds.

        Empty for a case declared `REFUSED`, and that is not a silent skip:
        `test_the_case_concluded_the_way_it_says_it_does` binds the declaration
        against what is on disk, so a job that stopped producing a final status
        goes red there rather than going quiet here.
        """
        if self.case.concludes != "BUILT":
            return []
        return [(formulation, self.play.work_dirs[formulation.key])
                for formulation in self.case.formulations]

    @staticmethod
    def _report_name(kind: str) -> str:
        # Named, not derived. `f"{kind}_report.json"` happened to spell the
        # verification receipt correctly only while that receipt was sitting
        # on the verifier's contract filename; deriving a path from a review
        # kind encodes a coincidence, and D37 is what it cost.
        return {"safety": "safety_verification_report.json",
                "verification": "pipeline_verification_receipt.json"}[kind]


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

    def test_a_two_review_round_trip_cost_three_builds_of_one_part(self) -> None:
        """What resumption costs, on a real job, measured rather than estimated.

        `design-tool run` is resumable by re-running, and every re-run re-executes
        every deterministic stage before the point it stopped at. This case pauses
        twice, so the candidate is built three times and two of those builds are
        work the job had already done. Nothing in this repository reported that
        number before `pipeline/cost.py`; the exit sequence above shows the three
        invocations and says nothing about what they cost.

        Asserted as an equality against the recorded exit codes rather than as a
        literal, so a case that stops pausing moves both together.
        """
        from pipeline import cost as COST

        totals = COST.totals_at(self.project)
        runs = sum(1 for code in self.play.exit_codes[1:])
        self.assertEqual(runs, totals["invocations"],
                         "one ledger entry per `design-tool run`, including the "
                         "two that concluded nothing")
        self.assertEqual(3, totals["builds"])
        self.assertEqual(2, totals["repeated_builds"])
        self.assertEqual(2, totals["reviews"],
                         "two questions were asked: one safety, one verification")
        self.assertEqual(3, totals["reviews_reused"],
                         "and three stored answers were read back by later "
                         "invocations. Summing `llm_calls` over the three runs "
                         "gives 0 + 1 + 2 = 3 dispatches where two questions "
                         "were ever put to anybody, which is the accounting the "
                         "ledger corrects.")
        self.assertEqual(3, totals["failed_invocations"],
                         "15.6's `failed work`: not one of the three invocations "
                         "produced a claim. Two stopped to ask a question and "
                         "the third finished on a lane that may not certify its "
                         "own result, so the whole 40-odd seconds this case "
                         "costs bought receipts to iterate against and no "
                         "claimable outcome.")

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


class BranchKnobSeatFallbackTest(_CaseChecks, unittest.TestCase):
    """Three formulations of one job: the fork Release 3 shipped, on a real request.

    The shared root is the sleeve as drawn; `plate-seated` trusts the base-plate
    estimate and spends the whole envelope on it; `as-drawn` carries the ancestor
    forward unchanged as the fallback. Everything asserted here failed before
    Release 3's slice A, and for different reasons -- see
    `pipeline/test_alternatives.py`'s docstring, which lists them. What is new
    at this tier is that they are asserted over a whole job driven through the
    command surface a user has, rather than over a project a test constructed.
    """

    CASE_ID = "branch-knob-seat-fallback"

    def _read(self, key: str, name: str) -> dict:
        return json.loads((self.play.work_dirs[key] / name)
                          .read_text(encoding="utf-8"))

    def test_neither_sibling_cut_an_acceptance_revision_from_the_other(self) -> None:
        """The collision that ran in a loop, on a job rather than a fixture.

        With one shared `acceptance_contract.json` the second formulation's
        freeze read the first's as `previous`, bumped the revision, and the
        invalidation deleted the first's final status, commissioning report,
        artifact manifest and review reports. Re-running the first did it back.
        Each of these freezes revision 1 and supersedes nothing.
        """
        for key in self.play.work_dirs:
            with self.subTest(formulation=key):
                history = self._read(key, "acceptance_history.json")
                self.assertEqual(1, len(history["revisions"]))
                entry = history["revisions"][0]
                self.assertEqual(1, entry["revision"])
                self.assertIsNone(entry["supersedes"],
                                  "a branch is not a correction of its sibling")
                # Absent at the shared root rather than null, the way every
                # optional branching key in this pipeline is absent until it
                # means something.
                self.assertEqual(None if key == RP.ROOT_ALTERNATIVE else key,
                                 entry.get("alternative_id"))

    def test_the_shared_half_stays_shared_and_nothing_writes_over_it(self) -> None:
        """One `project.json` for the whole fork, and one brief.

        The project file cannot move: it is where the requirements, the printer
        and the source declarations live for every formulation at once. A branch
        that stamped its own outcome into it would make the job read as whatever
        finished last, in the one file that has to be shared.
        """
        self.assertEqual(
            [self.project / "project.json"],
            sorted(self.project.rglob("project.json")))
        self.assertEqual([self.project / "brief.md"],
                         sorted(self.project.rglob("brief.md")))
        payload = json.loads((self.project / "project.json")
                             .read_text(encoding="utf-8"))
        self.assertNotIn("status", payload)
        self.assertNotIn("bindings", payload)
        self.assertEqual(
            [("plate-seated", []), ("as-drawn", [])],
            [(row["alternative_id"], row["parents"])
             for row in payload["alternatives"]],
            "both are branched from the shared root, which is what `parents: []` "
            "records")

    def test_each_formulation_kept_its_own_artifacts(self) -> None:
        """`candidate.stl` is a fixed literal, so one directory means one part."""
        seated = self.play.work_dirs["plate-seated"] / "candidate.stl"
        root = self.play.work_dirs[RP.ROOT_ALTERNATIVE] / "candidate.stl"
        self.assertNotEqual(RP.digest_of(root), RP.digest_of(seated),
                            "the two concepts are materially different solids")
        self.assertNotEqual(
            self._read(RP.ROOT_ALTERNATIVE, "final_status.json")["artifact_hashes"],
            self._read("plate-seated", "final_status.json")["artifact_hashes"])

    def test_the_fallback_is_the_ancestor_carried_forward_byte_for_byte(self) -> None:
        """Why this case can say anything about the false pass at all.

        A branch that differed from its parent would be refused on the contract
        hash alone, which proves nothing about the instant that matters: the one
        where the two are still the same part and the only thing telling their
        reviews apart is which formulation each was taken on.
        """
        root = self.play.work_dirs[RP.ROOT_ALTERNATIVE]
        fallback = self.play.work_dirs["as-drawn"]
        self.assertEqual(RP.digest_of(root / "candidate.stl"),
                         RP.digest_of(fallback / "candidate.stl"))
        self.assertEqual(
            self._read(RP.ROOT_ALTERNATIVE, "acceptance_contract.json")["contract_sha256"],
            self._read("as-drawn", "acceptance_contract.json")["contract_sha256"],
            "two formulations that require identical geometry are two ways of "
            "getting there, not two parts, so `alternative_id` deliberately does "
            "not join the contract hash")

    def test_the_whole_difference_between_the_two_reviews_is_the_formulation(self) -> None:
        """The protection, and the mutation that removes it, on real envelopes.

        Everything the reviewer of the fallback was shown equals what the
        reviewer of the root was shown -- the contract, the artifacts, the
        witnesses, the evidence, the packet itself. Two fields differ, and both
        are the same slice's doing: `alternative_id`, and the plan digest, which
        differs *because the plan carries the alternative id and nothing else*.

        Strip that one field from both plans and the digests are equal; strip it
        from both envelopes too and the two are the same document, so the PASS
        written for one is `is_bound` for the other. That is the false pass the
        authority gate forbids, reachable with nobody doing anything wrong, and
        it is what protocol 4 exists for.
        """
        from pipeline import schemas as S

        root, fallback = (self.play.work_dirs[RP.ROOT_ALTERNATIVE],
                          self.play.work_dirs["as-drawn"])
        here, there = (json.loads((where / "reviews" /
                                   "verification_packet.json")
                                  .read_text(encoding="utf-8"))["review_envelope"]
                       for where in (root, fallback))
        self.assertEqual({"alternative_id", "execution_plan_sha256"},
                         {key for key in set(here) | set(there)
                          if here.get(key) != there.get(key)})
        self.assertIsNone(here.get("alternative_id"),
                          "a review taken at the shared root omits the key "
                          "rather than writing null, so an unbranched job's "
                          "digests do not move")
        self.assertEqual("as-drawn", there["alternative_id"])

        plans = [json.loads((where / "execution_plan.json")
                            .read_text(encoding="utf-8"))
                 for where in (root, fallback)]
        self.assertEqual({"alternative_id"},
                         {key for key in set(plans[0]) | set(plans[1])
                          if plans[0].get(key) != plans[1].get(key)})
        for plan in plans:
            plan.pop("alternative_id", None)
        self.assertEqual(S.payload_hash(plans[0]), S.payload_hash(plans[1]),
                         "the plan cannot tell two formulations apart on its own")

        without = [{key: value for key, value in envelope.items()
                    if key not in ("alternative_id", "execution_plan_sha256")}
                   for envelope in (here, there)]
        self.assertEqual(without[0], without[1],
                         "with the id taken out -- of the envelope and of the "
                         "plan it binds -- the two reviews are one review, and "
                         "the first answer settles the second")

    def test_each_formulation_paid_in_full_and_nothing_computational_was_shared(self) -> None:
        """ARCHITECTURE.md 15.2's incremental cost per alternative, on a real fork.

        The vent-ball branch exercise produced this number with a stopwatch: a
        sibling costs a full build and a full audit, and nothing is shared. Here
        the pipeline produces it. What *is* shared is intent -- the brief, the
        requirements, the engagement length, the printer, all read from one
        `project.json` no formulation rewrites -- and intent is free. Everything
        that costs anything is paid again, per formulation, and the ledgers say
        so rather than a comment claiming it.

        `as-drawn` is the sharpest case in the repository for this: it builds a
        candidate byte-identical to its parent's, so if anything anywhere reused a
        sibling's work this is where it would show, and it costs exactly what the
        parent cost.
        """
        from pipeline import cost as COST

        costs = {key: COST.totals_at(work)
                 for key, work in self.play.work_dirs.items()}
        for key, totals in sorted(costs.items()):
            with self.subTest(formulation=key):
                self.assertEqual(2, totals["invocations"],
                                 "one run to ask for the verification, one to "
                                 "consume the answer")
                self.assertEqual(2, totals["builds"])
                self.assertEqual(1, totals["repeated_builds"])
                self.assertEqual(1, totals["reviews"],
                                 "one question, asked once and answered once")
                self.assertEqual(1, totals["reviews_reused"],
                                 "and read back once by the run that finished")
                self.assertEqual(0, totals["builds_avoided"])
                self.assertGreater(totals["context_bytes"], 0)

        report = COST.compare(costs)
        self.assertEqual(6, report["project"]["builds"],
                         "three formulations of one job, two builds each: "
                         "branching multiplies the deterministic cost and shares "
                         "the declaration")
        self.assertEqual(3, report["project"]["reviews"])
        self.assertEqual(sorted(["plate-seated", "as-drawn"]),
                         sorted(report["incremental"]),
                         "the shared root is what the others were branched from, "
                         "so it is not an increment over anything")
        for key, added in sorted(report["incremental"].items()):
            with self.subTest(formulation=key):
                self.assertEqual(2, added["builds"])
                self.assertEqual(1, added["reviews"])
                self.assertGreater(added["deterministic_seconds"], 0.0)
                self.assertEqual(
                    {"builds_avoided": 0, "reviews_from_a_sibling": 0},
                    added["shared"],
                    "the first is measured off the ledger and the second is zero "
                    "by construction -- `TheSiblingRefusesTheAnswerWrittenNextDoor"
                    "Test` is the proof that it still bites")

        fallback = costs["as-drawn"]["deterministic_seconds"]
        ancestor = costs[RP.ROOT_ALTERNATIVE]["deterministic_seconds"]
        self.assertGreater(fallback, ancestor / 2,
                           "the fallback builds the same solid as its parent and "
                           "pays for it again; a figure far below the parent's "
                           "would mean something was reusing a sibling's work, "
                           "which nothing here does")

    def test_the_revised_formulation_can_no_longer_claim_what_it_concluded(self) -> None:
        """Slice B, on a job: a verdict read after the evidence under it moved.

        The fallback was picked back up and its model edited after the run that
        verified it. Nothing was re-adjudicated and nothing was deleted --
        `final_status.json` still records `VERIFIED`, because that is what that
        run concluded -- but what a reader is allowed to repeat is derived from
        the bindings, and those no longer hold. Its two siblings are untouched,
        which is the scoping half: staleness follows the binding that broke.
        """
        derived = self.play.derived
        self.assertEqual("STALE", derived["as-drawn"]["derived_status"])
        self.assertEqual("VERIFIED", derived["as-drawn"]["stored_status"])
        self.assertEqual(
            ["commission_report.json", "final_status.json",
             "pipeline_artifact_receipt.json", "pipeline_verification_receipt.json"],
            derived["as-drawn"]["stale"],
            "the receipts that stopped binding, and only those: the frozen "
            "acceptance contract and the model contract still describe the same "
            "contract and are still true")
        for key in (RP.ROOT_ALTERNATIVE, "plate-seated"):
            with self.subTest(formulation=key):
                self.assertEqual("VERIFIED", derived[key]["derived_status"])
                self.assertEqual([], derived[key]["stale"])

        stored = self._read("as-drawn", "final_status.json")
        self.assertEqual("VERIFIED", stored["final_status"],
                         "the record of what that run concluded is not rewritten")
        self.assertNotEqual(
            stored["artifact_hashes"]["source"],
            RP.digest_of(self.play.work_dirs["as-drawn"] / "model.py"),
            "and this is why: the model it was issued against is not the model "
            "on disk")

    # ----------------------------------------------------------------
    # `design-tool compare`, on the job Release 4 says to exercise it on
    # ----------------------------------------------------------------

    def test_the_material_difference_between_the_two_designs_is_a_measurement(self) -> None:
        """The figure that was prose until this recording froze it.

        `docs/release-4-scope.md` rests its whole material argument on two
        volumes. When that document was judged, neither number could be
        reproduced from anything committed: `_observe_dir` recorded the volume
        detector's *result* and threw its measurement away, so the one quantity
        that discriminates the seated knob from the as-drawn one was frozen
        nowhere. It is frozen now, and the figures hold -- which retires the
        finding against that citation, and leaves the other two standing.

        Asserted as a relation and a band, not as a literal: the numbers live in
        `expected.json`, which is where a recording keeps its literals.
        """
        seated = self.observed["formulations"]["plate-seated"]["material"]
        root = self.observed["formulations"][RP.ROOT_ALTERNATIVE]["material"]

        self.assertGreater(seated["volume_mm3"], root["volume_mm3"],
                           "the formulation that spends the whole envelope on "
                           "the body is the one that uses more material")
        self.assertAlmostEqual(2.0, seated["bbox_mm"]["z"] - root["bbox_mm"]["z"],
                               places=3,
                               msg="52 mm against 50 mm: the fork is the "
                                   "base-plate estimate the request records as "
                                   "+/-2 mm, and this is that 2 mm")
        self.assertEqual(
            "NOT_APPLICABLE",
            self.observed["formulations"][RP.ROOT_ALTERNATIVE]
            ["screening_detail"]["detectors"]["volume"],
            "and it is a measurement with no calibrated gate behind it -- no "
            "independently specified expected volume exists, so the screen "
            "refuses to grade the solid against a number its own author wrote. "
            "Read from `screening_detail`, which is where the recording keeps "
            "the detector's verdict; `material` carried a second copy of it "
            "until a review pointed out that recording a value twice does not "
            "protect it twice")

    def test_the_comparison_settles_the_rubric_question_and_nothing_else(self) -> None:
        """What `compare` establishes on a job whose answer a score would destroy.

        Every mandatory check passes on all three. A ranking would therefore
        report a tie, and the tie would be false: the three are measured against
        *different envelope expectations*, because on the authored lane a
        formulation's own proposal sets the `expected_bbox_mm` its always-present
        checks are graded against (`docs/defects.md` D25). So the first thing the
        comparison says is that those verdicts are not comparable -- and the
        thing that actually decides, whether the mouth seats, is a measurement
        nobody has taken.
        """
        marks = self.observed["comparison"]
        self.assertEqual("INCOMPARABLE_EXPECTATIONS", marks["mandatory_verdict"])
        self.assertEqual({"PASS", "UNKNOWN_STALE"},
                         {row["verdict"]
                          for row in marks["mandatory_per_formulation"].values()},
                         "no formulation failed a mandatory check; the fallback's "
                         "verdict is merely no longer supported")
        self.assertTrue(marks["same_requirement_digest"],
                        "none of them weakened a requirement a sibling was held "
                        "to -- which is a binding, not a satisfaction")
        self.assertFalse(marks["preference_admissible"])

    def test_a_comparison_that_started_ranking_would_fail_this_recording(self) -> None:
        """ADR 0005's two forbidden fields, pinned where a change has to pass.

        A guarantee that lives only in a docstring is a convention. `ranking` and
        `score` are recorded as `null`, so acquiring a value is a binding
        difference in a frozen recording rather than a code review somebody may
        or may not do.
        """
        marks = self.observed["comparison"]
        self.assertIsNone(marks["ranking"])
        self.assertIsNone(marks["score"])
        self.assertTrue(marks["built_nothing"])
        self.assertEqual([".", "as-drawn", "plate-seated"], marks["compared"],
                         "all three, including the shared root -- which "
                         "`status` drops, and which is `docs/defects.md` D26")

    def test_two_columns_of_one_design_are_named_as_one(self) -> None:
        """D28 closed, on the only case in the repository that exercises it.

        The root and the fallback were built from a byte-identical `model.py`,
        their receipts prove it, and every measured value they carry agrees.
        `identical_designs` exists to stop a reader taking that agreement for
        two designs independently reaching one answer -- and it used to be
        empty, because it grouped on the source digest *on disk now* and the
        fallback's model was revised after its run concluded.

        This assertion was inverted when the fix landed. The comment it carried
        said so by name: "when D28 is fixed this becomes [['.', 'as-drawn']] and
        this assertion is the one to update".

        What is grouped is what the **receipts** establish -- the same design
        implementation and the same built artifacts. It is not a statement that
        either formulation's evidence is still current, and the test below keeps
        that separate: `as-drawn` is still STALE and its mandatory verdict is
        still `UNKNOWN_STALE`.
        """
        root = self._read(RP.ROOT_ALTERNATIVE, "final_status.json")
        fallback = self._read("as-drawn", "final_status.json")
        self.assertEqual(root["artifact_hashes"]["source"],
                         fallback["artifact_hashes"]["source"],
                         "one design: the receipts were issued against the same "
                         "model")
        self.assertEqual(root["artifact_hashes"]["stl"],
                         fallback["artifact_hashes"]["stl"],
                         "and the same solid came out of it, which is the half "
                         "of the key a source digest alone cannot carry")
        self.assertEqual(
            self.observed["formulations"][RP.ROOT_ALTERNATIVE]["material"],
            self.observed["formulations"]["as-drawn"]["material"],
            "and every number the comparison prints for them agrees")
        self.assertEqual([[RP.ROOT_ALTERNATIVE, "as-drawn"]],
                         self.observed["comparison"]["identical_designs"],
                         "and the block that says so is no longer silent")

    def test_naming_them_as_one_design_did_not_make_the_stale_one_current(self) -> None:
        """The claim D28's mitigation already made, kept separate from the fix.

        "These two columns are one design" and "this formulation's evidence
        still binds" are different sentences. `as-drawn`'s model was revised
        after its run, so its evidence does not bind and its mandatory verdict
        is `UNKNOWN_STALE`; grouping it with the root must not restore or
        strengthen that. A grouping that quietly did would have turned a defect
        about a missing sentence into a defect about a false one.
        """
        marks = self.observed["comparison"]
        self.assertEqual([[RP.ROOT_ALTERNATIVE, "as-drawn"]],
                         marks["identical_designs"])
        self.assertEqual(
            "UNKNOWN_STALE",
            marks["mandatory_per_formulation"]["as-drawn"]["verdict"],
            "still stale, still not a current verdict")
        self.assertFalse(marks["preference_admissible"],
                         "and still no basis for preferring one")

    # ----------------------------------------------------------------
    # Gate 4.5: somebody decides, on a real part
    # ----------------------------------------------------------------

    def test_one_formulation_is_preferred_and_the_other_is_kept(self) -> None:
        """What Release 3 owed and nothing in this repository had done.

        Gate 4.5 asks for derived status used to decide about a real part. Three
        formulations of a real vendored request were built, verified, compared,
        and then decided between -- through `design-tool branch --disposition`,
        the verb a user has, one command per decision.

        Retained, not deleted. 13.1 does not rewrite history and the fallback is
        the whole reason the fork exists: if the plate estimate is wrong, the
        sleeve as drawn is the part that ships.
        """
        rows = self.observed["dispositions"]["by_alternative"]
        self.assertEqual("PREFERRED", rows["plate-seated"]["disposition"])
        self.assertEqual("FALLBACK", rows["as-drawn"]["disposition"])
        self.assertNotIn(RP.ROOT_ALTERNATIVE, rows,
                         "the shared root has no declared row and no "
                         "disposition applies to it -- it is what the "
                         "alternatives were branched from")
        for key in ("plate-seated", "as-drawn"):
            with self.subTest(formulation=key):
                self.assertTrue((self.play.work_dirs[key] / "final_status.json")
                                .is_file(),
                                "deciding deletes nothing; both formulations "
                                "keep every receipt they earned")

    def test_the_decision_does_not_claim_the_support_the_comparison_refused(self) -> None:
        """The half of gate 4.5 that is about honesty rather than about typing.

        The comparison run immediately before these commands reports
        `preference.admissible: false`, and the *reason* is asserted here rather
        than the boolean alone. An earlier version of this test, of the case's
        notes and of ROADMAP all said the reason was the rubric -- the three
        formulations are measured against different envelope expectations, which
        is true -- and all three were wrong about the mechanism: `_preference`
        returns on its first branch and never reaches the rubric. Nor is it the
        third branch: every `not_compared` row on this job is CONTEXT, so the
        build makes no claim that a deciding axis is unmeasurable.

        What actually fires is that `as-drawn` has no current verdict. Its model
        was revised after the run that verified it, so its mandatory verdict
        derives `UNKNOWN_STALE`, and a preference over a formulation that cannot
        presently claim to have passed anything is not admissible.

        A decision is still correct. What it may not do is claim measured
        support that was refused, and the basis is where that shows --
        `USER_SELECTION` for the preference, which says a person chose on no
        measured ground, and not `STRONGER_CONCEPT`, which would say the
        evidence favoured it. Nothing in the build enforces that agreement; the
        recording is what makes it visible.
        """
        comparison = self.observed["comparison"]
        self.assertFalse(comparison["preference_admissible"])
        self.assertEqual("NO_CURRENT_VERDICT", comparison["preference_reason"],
                         "the reason as a code, pinned. Freezing only `false` "
                         "cannot tell three different findings about a job "
                         "apart, and that is how three documents came to name "
                         "the wrong one; freezing the *sentence* instead, which "
                         "is what this asserted first, went red on a reworded "
                         "explanation with no defect behind it")
        self.assertEqual(
            {"geometric-difference": "CONTEXT", "print-time": "CONTEXT",
             "engineering-judgment": "CONTEXT"},
            comparison["not_compared"],
            "no DECIDING row: this job's inadmissible preference is not about "
            "an axis nobody could measure")

        rows = self.observed["dispositions"]["by_alternative"]
        self.assertEqual("USER_SELECTION", rows["plate-seated"]["basis"])
        self.assertEqual("UNRESOLVED_EVIDENCE", rows["as-drawn"]["basis"])

    def test_the_retained_fallback_is_one_whose_verification_no_longer_binds(self) -> None:
        """Recorded beside the decision, because it is a property of the decision.

        The harness takes declared decisions only when every formulation wrote a
        final status -- which `as-drawn` did. Its verdict is nonetheless `STALE`:
        the model under it moved afterwards. Retaining a stale concept as the
        fallback is right, and it is the reason the fallback exists, but a
        recording that showed `FALLBACK` without showing that would let a reader
        believe the part behind it is ready to ship. It would need re-verifying
        first, and `STALE` is the pipeline saying so.
        """
        self.assertEqual("FALLBACK",
                         self.observed["dispositions"]["by_alternative"]
                         ["as-drawn"]["disposition"])
        self.assertEqual("STALE",
                         self.observed["formulations"]["as-drawn"]["derived"]
                         ["derived_status"])
        self.assertEqual("UNKNOWN_STALE",
                         self.observed["comparison"]
                         ["mandatory_per_formulation"]["as-drawn"]["verdict"])

    def test_the_job_ends_parked_on_the_fallback_and_the_recording_says_so(self) -> None:
        """Which formulation `design-tool run` would pick up next.

        It is the fallback, not the preferred one: `_derive_all` leaves the
        project on the last formulation it activated and `FALLBACK` is runnable,
        so `--disposition` has no reason to move off it. Deterministic, fixed by
        the order the case declares. Recorded because it decides what happens
        next and was invisible until a review measured it -- not asserted to be
        *right*. Whether preferring one formulation should also activate it is a
        question for whichever slice touches lifecycle next.
        """
        self.assertEqual("as-drawn",
                         self.observed["dispositions"]["active_alternative"])

    def test_the_decision_is_journalled_as_a_transition_not_only_as_a_state(self) -> None:
        """`project.json` says where the job stands; the journal says what happened.

        Both are needed and they are different claims. A reader arriving later
        finds `PREFERRED` in the project and has no way to tell whether somebody
        chose it or it was always so -- 14.6's requirement that a disposition
        carry its basis is about the decision, and a decision is an event.
        """
        from pipeline import lifecycle as LC
        events = [row for row in LC.read(self.play.project_dir)
                  if row.get("event") == "DISPOSITION"]
        self.assertEqual(
            [("plate-seated", "ACTIVE", "PREFERRED"),
             ("as-drawn", "ACTIVE", "FALLBACK")],
            [(row["alternative"], row["was"], row["now"]) for row in events],
            "in the order they were taken, each naming what it moved from")
        # Per alternative, not "one of these two". The loop already knows which
        # row it is looking at, and a membership check would pass a journal that
        # recorded the preference's basis against the fallback -- in a slice
        # whose whole subject is making the basis mean something.
        expected = {"plate-seated": "USER_SELECTION",
                    "as-drawn": "UNRESOLVED_EVIDENCE"}
        for row in events:
            with self.subTest(alternative=row["alternative"]):
                self.assertEqual(expected[row["alternative"]], row["basis"])


class TheSiblingRefusesTheAnswerWrittenNextDoorTest(unittest.TestCase):
    """The false pass, tried for real, on the pair that makes it reachable.

    `TheBindingStillBitesTest` moves an evidence digest, which is a stale answer.
    This one moves nothing: it takes the envelope the shared root's review was
    issued under -- a live, current, correctly-formed envelope for a part with
    the same contract hash, the same STL digest and the same source digest -- and
    offers it as the answer to the fallback's review. Before protocol 4 that was
    accepted, and both formulations passed on one judgement.

    What is asserted is the whole consequence rather than an exception: the run
    stopped, said why, left no final status behind, and the layered comparison
    against the recording went red.
    """

    CASE_ID = "branch-knob-seat-fallback"

    def test_a_pass_written_for_the_ancestor_does_not_settle_the_fallback(self) -> None:
        case = RP.load(self.CASE_ID)
        with tempfile.TemporaryDirectory() as raw:
            try:
                project = RP.materialise(case, Path(raw) / "project")
            except FX.FixtureUnavailable as exc:
                self.skipTest(str(exc))

            def next_door(kind: str, packet: dict, formulation) -> dict:
                if formulation.alternative_id != "as-drawn":
                    return packet["review_envelope"]
                return json.loads(
                    (project / "reviews" / f"{kind}_packet.json")
                    .read_text(encoding="utf-8"))["review_envelope"]

            run = RP.play(case, project, envelope_for=next_door)

            self.assertEqual(
                [0, RP.NEEDS_ACTION, 0,
                 0, 0, RP.NEEDS_ACTION, 0,
                 0, 0, RP.NEEDS_ACTION, 1],
                run.exit_codes,
                "the first two formulations answer their own reviews and "
                "finish; the third is handed the answer written next door and "
                "stops")

            fallback = project / "alternatives" / "as-drawn"
            # The refusal is a diagnostic, not a review, and since D37 it
            # says so in its filename: the receipt name is now reserved for
            # an object that carries a decision.
            report = json.loads((fallback / "verification_review_error.json")
                                .read_text(encoding="utf-8"))
            self.assertIn("ReviewError", report["error"])
            self.assertIn("review envelope mismatch", report["error"])
            self.assertNotIn("decision", report,
                             "a refused answer must not leave a decision behind")
            self.assertFalse((fallback / "pipeline_verification_receipt.json").is_file(),
                             "a refused answer must not leave a receipt either")
            self.assertFalse((fallback / "final_status.json").is_file())
            for sibling in (project, project / "alternatives" / "plate-seated"):
                self.assertTrue((sibling / "final_status.json").is_file(),
                                "the refusal is the fallback's alone")

            observed = RP.observe(case, run)
            self.assertEqual(
                {"plate-seated": {"disposition": "ACTIVE", "basis": "",
                                  "superseded_by": ""},
                 "as-drawn": {"disposition": "ACTIVE", "basis": "",
                              "superseded_by": ""}},
                observed["dispositions"]["by_alternative"],
                "and nothing was decided: both are still in the state they were "
                "branched into, with no basis. The case declares two decisions "
                "and `design-tool branch --disposition` would have accepted "
                "both -- a formulation need not have concluded to be retained "
                "as a fallback -- so the harness declines to take them when a "
                "declared formulation left no final status. A preference "
                "recorded over a job that stopped is one nobody could have "
                "formed from evidence that is not there.")

            failures = RP.binding(
                RP.compare(RP.expected(self.CASE_ID), RP.observe(case, run)))
            self.assertTrue(failures,
                            "an answer bound to a sibling has to make the replay "
                            "go red. If this passes, the comparison is not "
                            "reading the thing it claims to read.")


class ModifyBallScopeRefusedTest(_CaseChecks, unittest.TestCase):
    """A real job refused before it builds, and the findings it leaves behind.

    Nothing else at this tier covers the refusal path, which is half of the
    functional gate -- "failures are actionable and controlled" -- and it is the
    only path on which Release 3's slice C produces anything: a structured
    finding exists because a validator found something wrong.
    """

    CASE_ID = "modify-ball-scope-refused"

    def _instruction(self) -> dict:
        return json.loads((self.project / "next_action.json")
                          .read_text(encoding="utf-8"))

    def test_the_findings_name_the_position_in_the_file_and_the_rule(self) -> None:
        """Slice C: a `code` to match on and a `where` a caller can go and edit.

        `edit_scopes[0].region_box.y` rather than "edit_scope 'ball-17mm'": the
        sentence names the scope by id and the field path names the position,
        and only one of the two survives a list somebody reorders. The axis is
        part of the path because a box can be empty on two axes at once and
        `CODE@where` has to name one finding -- an id two findings share is one
        nobody can key on.
        """
        from pipeline import findings as F

        instruction = self._instruction()
        self.assertEqual("FIX_PROJECT", instruction["kind"])
        self.assertEqual(
            [("SCHEMA_RANGE", "edit_scopes[0].region_box.y"),
             ("REF_UNDECLARED", "edit_scopes[0].interface_ids[0]")],
            [(row["code"], row["where"]) for row in instruction["findings"]])
        for row in instruction["findings"]:
            with self.subTest(finding=row["id"]):
                self.assertEqual("error", row["severity"])
                self.assertEqual(f"{row['code']}@{row['where']}", row["id"])
                self.assertIn(row["code"], F.CODES)
                self.assertTrue(
                    any(row["code"].startswith(group) for group in F.CODE_GROUPS),
                    "the prefix names what has to change to clear it")

    def test_the_sentence_and_the_structure_are_one_validation_and_not_two(self) -> None:
        """`unresolved` and `findings` come from one `validate()` call.

        Two calls would be two answers to one question and the cheaper of the
        two ways to make them disagree; the English stays a list of sentences
        because four writers fill that field and a reader cannot parse a field
        whose element type depends on which of them wrote it.
        """
        instruction = self._instruction()
        self.assertEqual([row["message"] for row in instruction["findings"]],
                         instruction["unresolved"])

    def test_the_refusal_reached_neither_the_freeze_nor_the_build(self) -> None:
        """No dispatch, and no confined build either -- by never getting there.

        A job refused at validation costs a second and produces no candidate, so
        "zero live dispatches" is true of this case for a stronger reason than
        the harness's accounting: there was nothing to dispatch about.
        """
        for name in ("acceptance_contract.json", "candidate.stl",
                     "final_status.json", "execution_plan.json", "timings.json"):
            with self.subTest(receipt=name):
                self.assertFalse((self.project / name).exists())
        self.assertFalse((self.project / "reviews").exists())
        self.assertTrue((self.project / "ball_male_17mm.stl").is_file(),
                        "the supplied artifact is still there to be modified "
                        "once the declaration is corrected")

    def test_the_supplied_artifact_is_the_one_the_register_records(self) -> None:
        declared = FX.public("vent-ball-combine").sources[1]
        self.assertEqual("ball_male_17mm.stl", declared.name)
        self.assertEqual(declared.sha256,
                         RP.digest_of(self.project / "ball_male_17mm.stl"))


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

            def wrong(kind: str, packet: dict, formulation) -> dict:
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
            # Neither name, not just the receipt: since D37 a verification
            # that was reached and failed to parse leaves a diagnostic
            # instead, so "never reached" has to exclude both or it
            # half-checks itself.
            self.assertFalse((project / "pipeline_verification_receipt.json").is_file(),
                             "the second review must never have been reached")
            self.assertFalse((project / "verification_review_error.json").is_file(),
                             "nor left a diagnostic from a review it never ran")

            failures = RP.binding(
                RP.compare(RP.expected(self.CASE_ID),
                           RP.observe(case, run)))
            self.assertTrue(failures,
                            "a wrongly-bound answer has to make the replay go "
                            "red. If this passes, the comparison is not reading "
                            "the thing it claims to read.")


if __name__ == "__main__":
    unittest.main()
