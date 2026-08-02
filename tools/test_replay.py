#!/usr/bin/env python3
"""L0 for the L1 harness: the guards, shown failing, without running a job.

`tools/replay.py` is the only thing standing between "the recorded job still
behaves" and "the recorded job produced *something*". Its own guards therefore
need what `tools/test_check_internal_links.py` says about the link gate: a check
nobody checks reports all clear just as convincingly when it is broken.

Everything here is synthetic and costs milliseconds. The real cases run in
`benchmarks/replays/test_l1_replay.py`, which is outside `testpaths` on purpose
-- see that file. Nothing in this file executes `design-tool`, so the
commit-gating suite pays for the harness and not for the jobs.

Each guard gets the pair: the thing it lets through, and the thing it stops.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools import replay as RP

UNCHANGED = "0" * 64


def _case(directory: Path, *, reviews=(), judgements=None, substitutions=None,
          inputs=None, case_id="synthetic") -> RP.ReplayCase:
    """A case on disk under a temporary CASES_ROOT, sealed and loadable."""
    room = directory / case_id
    (room / RP.INPUT_DIR).mkdir(parents=True)
    for name, text in (inputs or {"project.json": "{}"}).items():
        (room / RP.INPUT_DIR / name).write_text(text, encoding="utf-8")
    if judgements:
        (room / RP.JUDGEMENT_DIR).mkdir()
        for kind, payload in judgements.items():
            (room / RP.JUDGEMENT_DIR / f"{kind}.json").write_text(
                json.dumps(payload), encoding="utf-8")
    (room / RP.CASE_FILE).write_text(json.dumps({
        "schema_version": RP.CASE_SCHEMA, "case_id": case_id,
        "use_case": "MODIFY", "source_mode": "MODIFY",
        "consequence": "INCONSEQUENTIAL",
        "request": "benchmarks/fixtures/berlingo-knob/public/request.md",
        "sources": [], "substitutions": substitutions or {},
        "reviews": list(reviews), "max_invocations": 3,
        "recorded_at": "synthetic", "provenance": "synthetic", "notes": "",
        "inputs_sha256": {},
    }), encoding="utf-8")
    return room


class _Sandboxed(unittest.TestCase):
    """Point the loader at a temporary case tree for the duration of one test."""

    def setUp(self) -> None:
        self.raw = tempfile.TemporaryDirectory()
        self.addCleanup(self.raw.cleanup)
        self.root = Path(self.raw.name)
        original = RP.CASES_ROOT
        RP.CASES_ROOT = self.root
        self.addCleanup(setattr, RP, "CASES_ROOT", original)

    def _seal(self, case_id: str = "synthetic") -> RP.ReplayCase:
        RP.reseal(case_id)
        return RP.load(case_id)


class TheSeamPointsAtTheRealCommandSurfaceTest(unittest.TestCase):
    """`play` takes an injectable runner. That is exactly one hole to close.

    Every guard below is exercised through `invoke=`, which is why it exists. A
    seam that could quietly resolve to something other than `design-tool` would
    turn the whole L1 suite into a test of a stub, so the default binding is
    asserted rather than assumed -- and so is the exit code the loop branches on,
    which is a literal here and a constant there.
    """

    def test_the_default_runner_is_design_tools_own_entry_point(self) -> None:
        from pipeline import cli
        self.assertIs(cli.main, RP.command_surface())

    def test_the_pause_code_the_loop_branches_on_is_the_clis_own(self) -> None:
        from pipeline import cli
        self.assertEqual(cli.NEEDS_ACTION, RP.NEEDS_ACTION)


class TheRecordedInputsAreVerifiedTest(_Sandboxed):
    """`expected.json` is a statement about specific bytes.

    Nothing else in this repository would notice a case whose `model.py` somebody
    reformatted: the replay would run the new model, compare it against the old
    recording, and report whatever came out as the truth about the pipeline.
    """

    def test_a_sealed_case_loads(self) -> None:
        _case(self.root)
        case = self._seal()
        self.assertEqual({"inputs/project.json"}, set(case.inputs_sha256))

    def test_an_edited_input_is_refused_by_name(self) -> None:
        room = _case(self.root)
        self._seal()
        (room / RP.INPUT_DIR / "project.json").write_text("{ }", encoding="utf-8")
        with self.assertRaises(RP.CaseMismatch) as caught:
            RP.load("synthetic")
        self.assertIn("inputs/project.json", str(caught.exception))

    def test_an_input_nobody_digested_is_refused_too(self) -> None:
        """The half a digest check usually forgets.

        Verifying every recorded digest says nothing about a file that has no
        digest, and a case can gain a second module beside `model.py` -- the
        confined build stages every `.py` in the project directory -- without a
        single recorded hash moving.
        """
        room = _case(self.root)
        self._seal()
        (room / RP.INPUT_DIR / "helper.py").write_text("X = 1\n", encoding="utf-8")
        with self.assertRaises(RP.CaseMismatch) as caught:
            RP.load("synthetic")
        self.assertIn("inputs/helper.py", str(caught.exception))

    def test_an_unknown_schema_version_is_refused_rather_than_guessed(self) -> None:
        room = _case(self.root)
        self._seal()
        payload = json.loads((room / RP.CASE_FILE).read_text(encoding="utf-8"))
        payload["schema_version"] = RP.CASE_SCHEMA + 1
        (room / RP.CASE_FILE).write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(RP.ReplayError) as caught:
            RP.load("synthetic")
        self.assertIn("schema_version", str(caught.exception))


class TheRecordedJudgementCarriesNoEnvelopeTest(_Sandboxed):
    """A judgement is an opinion about a part. An envelope is a binding to one run.

    Recording the two together is the mistake that makes a replay useless: the
    envelope would bind the answer to the run that happened at the commit it was
    recorded at, and every replay after the next protocol bump would refuse it.
    """

    def test_a_bare_judgement_is_returned(self) -> None:
        _case(self.root, reviews=("safety",),
              judgements={"safety": {"decision": "PASS", "summary": "fine"}})
        case = self._seal()
        self.assertEqual("PASS", case.judgement("safety")["decision"])

    def test_a_judgement_that_carries_one_is_refused(self) -> None:
        _case(self.root, reviews=("safety",),
              judgements={"safety": {"decision": "PASS", "summary": "fine",
                                     "review_envelope": {"packet_sha256": UNCHANGED}}})
        case = self._seal()
        with self.assertRaises(RP.ReplayError) as caught:
            case.judgement("safety")
        self.assertIn("review_envelope", str(caught.exception))

    def test_a_review_the_case_never_recorded_fails_closed(self) -> None:
        _case(self.root, reviews=("safety",),
              judgements={"safety": {"decision": "PASS", "summary": "fine"}})
        case = self._seal()
        with self.assertRaises(RP.NoRecordedAnswer) as caught:
            case.judgement("verification")
        self.assertIn("no verification judgement", str(caught.exception))


class _FakeSurface:
    """A `design-tool` that does whatever the test needs it to do next."""

    def __init__(self, project_dir: Path, script) -> None:
        self.project_dir, self.script, self.calls = project_dir, list(script), []

    def __call__(self, argv: list[str]) -> int:
        self.calls.append(list(argv))
        if argv[0] == "route":
            return 0
        code, action = self.script.pop(0) if self.script else (0, None)
        pending = self.project_dir / "next_action.json"
        if action is None:
            pending.unlink(missing_ok=True)
        else:
            (self.project_dir / "reviews").mkdir(exist_ok=True)
            if action.get("kind") == "REVIEW":
                (self.project_dir / action["evidence"]).write_text(
                    json.dumps({"review_envelope": {"packet_sha256": UNCHANGED}}),
                    encoding="utf-8")
            pending.write_text(json.dumps(action), encoding="utf-8")
        return code


class ThePlayLoopFailsClosedTest(_Sandboxed):
    """Four ways a replay could quietly stop being one.

    None of these needs a real job to misbehave: what is being tested is the
    harness's response to a state, and the state is cheaper to write than to
    provoke.
    """

    def _play(self, script, **kw):
        room = _case(self.root, **kw)
        case = self._seal()
        project = self.root / "project"
        project.mkdir()
        (room / "unused").mkdir(exist_ok=True)
        return case, project, RP.play(case, project,
                                      invoke=_FakeSurface(project, script))

    REVIEW = {"kind": "REVIEW", "review_kind": "safety",
              "evidence": "reviews/safety_packet.json",
              "respond_with": "reviews/safety_response.json"}

    def test_a_recorded_review_is_answered_with_the_current_envelope(self) -> None:
        case, project, run = self._play(
            [(RP.NEEDS_ACTION, self.REVIEW), (0, None)],
            reviews=("safety",),
            judgements={"safety": {"decision": "PASS", "summary": "fine"}})
        self.assertEqual([0, RP.NEEDS_ACTION, 0], run.exit_codes)
        self.assertEqual(["safety"], run.reviews_answered)
        answer = json.loads((project / "reviews" / "safety_response.json")
                            .read_text(encoding="utf-8"))
        self.assertEqual("PASS", answer["decision"])
        self.assertEqual({"packet_sha256": UNCHANGED}, answer["review_envelope"],
                         "the judgement is recorded and the binding is not; the "
                         "harness stamps the packet the run just wrote")

    def test_an_agent_commission_is_fatal_rather_than_a_pause(self) -> None:
        """The live dispatch, by its real name.

        `AGENT_COMMISSION` is the pipeline asking a designer for a proposal and a
        model. A replay that treated it as an ordinary stopping point would
        report a job that never built anything as a job whose receipts matched.
        """
        with self.assertRaises(RP.LiveDispatchRequired) as caught:
            self._play([(RP.NEEDS_ACTION, {"kind": "AGENT_COMMISSION",
                                           "required_outputs": ["model.py"]})])
        self.assertIn("model.py", str(caught.exception))

    def test_an_answer_the_harness_did_not_write_is_refused(self) -> None:
        """Somebody else's response file sitting in the project directory.

        This is what "zero live dispatches" has to mean concretely: not that no
        call was made, but that every answer consumed came out of the recording.
        """
        room = _case(self.root, reviews=("safety",),
                     judgements={"safety": {"decision": "PASS", "summary": "fine"}})
        case = self._seal()
        project = self.root / "project"
        (project / "reviews").mkdir(parents=True)
        (project / "reviews" / "safety_response.json").write_text(
            json.dumps({"decision": "PASS"}), encoding="utf-8")
        self.assertTrue((room / RP.CASE_FILE).is_file())
        with self.assertRaises(RP.ReplayError) as caught:
            RP.play(case, project, invoke=_FakeSurface(
                project, [(RP.NEEDS_ACTION, self.REVIEW), (0, None)]))
        self.assertIn("already exists", str(caught.exception))

    def test_a_branched_project_is_refused_rather_than_read_from_the_root(self) -> None:
        """The trap this harness is not yet built for, made loud.

        A branch keeps its proposal, its acceptance revision, its receipts and
        its review packets under `alternatives/<id>/`, and every path joined here
        is relative to the project root. Resolving that correctly is work a
        branch case should arrive with; reading the root and calling it the
        branch is a replay that passes for the wrong reason, which is worse than
        not having one.
        """
        room = _case(self.root)
        case = self._seal()
        project = self.root / "project"
        project.mkdir()
        (project / "project.json").write_text(
            json.dumps({"active_alternative": "snap-fit"}), encoding="utf-8")
        self.assertTrue((room / RP.CASE_FILE).is_file())
        with self.assertRaises(RP.ReplayError) as caught:
            RP.play(case, project, invoke=_FakeSurface(project, [(0, None)]))
        self.assertIn("snap-fit", str(caught.exception))
        self.assertIn("alternatives/", str(caught.exception))

    def test_an_unbranched_project_is_not_refused(self) -> None:
        _case(self.root)
        case = self._seal()
        project = self.root / "project"
        project.mkdir()
        (project / "project.json").write_text(
            json.dumps({"active_alternative": None}), encoding="utf-8")
        self.assertEqual([0, 0], RP.play(
            case, project, invoke=_FakeSurface(project, [(0, None)])).exit_codes)

    def test_a_job_that_never_settles_is_reported_rather_than_looped(self) -> None:
        with self.assertRaises(RP.ReplayError) as caught:
            self._play([(RP.NEEDS_ACTION, self.REVIEW)] * 6,
                       reviews=("safety",),
                       judgements={"safety": {"decision": "PASS",
                                              "summary": "fine"}})
        self.assertIn("still asking for something", str(caught.exception))


class TheSubstitutionReachesTheModelTest(_Sandboxed):
    """A recorded model cannot carry a path that does not exist yet.

    The token is expanded on the way into the materialised directory, and the
    materialised directory is not the case directory -- so a substitution that
    silently did nothing would leave `__SOURCE__` in the model and the build
    would fail somewhere much less informative than here.
    """

    def test_the_token_becomes_the_materialised_path(self) -> None:
        _case(self.root, substitutions={"__SOURCE__": "part.stl"},
              inputs={"project.json": "{}",
                      "model.py": 'SOURCE = r"__SOURCE__"\n'})
        case = self._seal()
        destination = RP.materialise(case, self.root / "work")
        text = (destination / "model.py").read_text(encoding="utf-8")
        self.assertNotIn("__SOURCE__", text)
        self.assertIn("part.stl", text)
        self.assertIn(destination.name, text)

    def test_materialising_creates_no_reviews_directory(self) -> None:
        """Why the on-disk answer set is evidence and not bookkeeping."""
        _case(self.root)
        case = self._seal()
        destination = RP.materialise(case, self.root / "work")
        self.assertFalse((destination / "reviews").exists())


class TheComparatorLayersTest(unittest.TestCase):
    """What a replay asserts, and what it deliberately lets through.

    The argument is in `tools/replay.py`'s docstring. These are the cases that
    would make it false.
    """

    BASE = {
        "schema_version": RP.EXPECTED_SCHEMA, "case_id": "x",
        "exit_codes": [0, 3, 3], "reviews_answered": ["safety"],
        "outcome": {"final_status": "NEEDS_MORE_EVIDENCE", "verification": "PASS"},
        "checks": {"seated": {"result": "PASS", "status": "MEASURED", "ran": True}},
        "measured": {"seated": 0.0},
        "tolerances": {"seated": {"abs": 0.05}},
        "coverage": {"covered": 1, "declared": 1, "fraction": 1.0},
        "screening_detail": {"overall": "CLEAR", "calibrated": False,
                             "detectors": {"volume": "NOT_APPLICABLE"}},
        "acceptance": {"revision": 1, "history_entries": 1},
        "receipts": ["final_status.json"],
        "reasons": ["screening reported an anomaly"],
        "allowed_claim": "nobody independent looked",
    }

    def _diff(self, **over):
        observed = {**self.BASE, **over}
        return RP.compare(self.BASE, observed)

    def test_an_unchanged_run_reports_nothing(self) -> None:
        self.assertEqual([], self._diff())

    def test_a_moved_final_status_is_binding(self) -> None:
        rows = RP.binding(self._diff(outcome={**self.BASE["outcome"],
                                              "final_status": "FAILED"}))
        self.assertEqual(1, len(rows), rows)
        self.assertIn("outcome.final_status", rows[0].where)

    def test_a_moved_exit_sequence_is_binding(self) -> None:
        self.assertTrue(RP.binding(self._diff(exit_codes=[0, 0])))

    def test_a_check_that_stops_running_is_binding(self) -> None:
        rows = RP.binding(self._diff(checks={
            "seated": {"result": "ESCALATE", "status": "UNAVAILABLE", "ran": False}}))
        self.assertEqual(3, len(rows), rows)

    def test_a_check_that_disappears_is_binding(self) -> None:
        """Coverage is a fraction and stays 1.0 when both halves shrink."""
        rows = RP.binding(self._diff(checks={}))
        self.assertTrue(any("checks.ids" in row.where for row in rows), rows)

    def test_a_measurement_inside_the_contracts_own_band_passes(self) -> None:
        self.assertEqual([], self._diff(measured={"seated": 0.03}))

    def test_a_measurement_past_it_is_binding(self) -> None:
        rows = RP.binding(self._diff(measured={"seated": 0.2}))
        self.assertEqual(1, len(rows), rows)
        self.assertIn("measured.seated", rows[0].where)

    def test_a_zero_band_falls_back_to_the_pipelines_own_relative_one(self) -> None:
        """A support ceiling declares `abs: 0.0`, and two floats at zero
        tolerance is byte equality with extra steps."""
        recorded = {**self.BASE, "measured": {"seated": 400.0},
                    "tolerances": {"seated": {"abs": 0.0}}}
        near = {**recorded, "measured": {"seated": 400.5}}
        far = {**recorded, "measured": {"seated": 420.0}}
        self.assertEqual([], RP.binding(RP.compare(recorded, near)))
        self.assertTrue(RP.binding(RP.compare(recorded, far)))

    def test_a_plan_digest_inside_a_measured_value_is_never_compared(self) -> None:
        """It moves with a plan-version bump, which is not a regression.

        Determinism is what a plan digest is worth, and determinism is tested by
        running the case twice -- see `determinism_marks` -- not by pinning a
        digest recorded at another commit.
        """
        recorded = {**self.BASE,
                    "measured": {"seated": {"verdict": "PRESERVED_WITHIN_TOLERANCE",
                                            "sample_plan_sha256": "a" * 64,
                                            "evidence_sha256": "b" * 64}},
                    "tolerances": {"seated": None}}
        moved = {**recorded,
                 "measured": {"seated": {"verdict": "PRESERVED_WITHIN_TOLERANCE",
                                         "sample_plan_sha256": "c" * 64,
                                         "evidence_sha256": "d" * 64}}}
        self.assertEqual([], RP.compare(recorded, moved))

        changed = {**recorded,
                   "measured": {"seated": {"verdict": "CHANGED",
                                           "sample_plan_sha256": "c" * 64,
                                           "evidence_sha256": "d" * 64}}}
        self.assertTrue(RP.binding(RP.compare(recorded, changed)),
                        "the verdict inside the same value must still bind")

    def test_a_receipt_that_stops_being_written_is_binding(self) -> None:
        self.assertTrue(RP.binding(self._diff(receipts=[])))

    def test_reworded_prose_is_advisory_and_never_fails_a_build(self) -> None:
        rows = self._diff(reasons=["the broad screen reported an anomaly"],
                          allowed_claim="no independent look was taken")
        self.assertEqual([], RP.binding(rows))
        self.assertEqual({RP.ADVISORY}, {row.severity for row in rows})
        self.assertEqual(2, len(rows))


class TheObservationReadsTheReceiptsTest(unittest.TestCase):
    """`observe` off a directory, so the recording is not a second derivation."""

    def _directory(self, root: Path) -> Path:
        directory = root / "project"
        directory.mkdir()
        (directory / "final_status.json").write_text(json.dumps({
            "final_status": "FAILED", "commission_verdict": "FAIL",
            "reasons": ["a"], "allowed_claim": "no"}), encoding="utf-8")
        (directory / "commission_report.json").write_text(json.dumps({
            "verdict": "FAIL", "coverage": {"fraction": 1.0},
            "checks": [{"check_id": "seated", "result": "FAIL",
                        "status": "MEASURED", "ran": True, "measured": -0.65,
                        "tolerance": {"abs": 0.05}}],
            "screening": {"overall": "ANOMALY", "calibrated": False,
                          "detectors": [{"detector": "profile-z",
                                         "result": "ANOMALY"}]}}),
            encoding="utf-8")
        (directory / "timings.json").write_text("{}", encoding="utf-8")
        (directory / "candidate.stl").write_bytes(b"solid x\nendsolid x\n")
        return directory

    def test_the_receipt_set_excludes_what_the_runner_calls_non_identifying(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = self._directory(Path(raw))
            run = RP.Play(directory, [0], [], [], "")
            observed = RP.observe(
                RP.ReplayCase("x", "MODIFY", "MODIFY", "INCONSEQUENTIAL", "r", (),
                              {}, (), 2, {}, "", "", ""), run)
        self.assertNotIn("timings.json", observed["receipts"])
        self.assertIn("candidate.stl", observed["receipts"])
        self.assertEqual("FAILED", observed["outcome"]["final_status"])
        self.assertEqual({"profile-z": "ANOMALY"},
                         observed["screening_detail"]["detectors"])
        self.assertEqual({"abs": 0.05}, observed["tolerances"]["seated"])

    def test_the_determinism_marks_are_the_digests_two_runs_must_agree_on(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = self._directory(Path(raw))
            marks = RP.determinism_marks(directory)
        self.assertEqual(["candidate.stl"], sorted(marks))


class TheShippedCasesAreWellFormedTest(unittest.TestCase):
    """The committed cases load, seal and declare what they hold -- no job run.

    Cheap enough for the commit-gating suite, and it is the check that says a
    case broke by being edited rather than by the pipeline moving underneath it.
    """

    def test_every_case_loads_with_its_inputs_verified(self) -> None:
        self.assertTrue(RP.case_ids(), "no replay case is committed")
        for case_id in RP.case_ids():
            with self.subTest(case=case_id):
                case = RP.load(case_id)
                self.assertEqual(case_id, case.case_id)
                self.assertTrue(case.inputs_sha256)
                self.assertTrue((RP.REPO_ROOT / case.request).is_file(),
                                "the recorded request must be committed")

    def test_every_case_carries_a_judgement_for_every_review_it_declares(self) -> None:
        for case_id in RP.case_ids():
            case = RP.load(case_id)
            for kind in case.reviews:
                with self.subTest(case=case_id, review=kind):
                    self.assertIn("decision", case.judgement(kind))

    def test_every_case_has_a_recording_taken_at_a_named_commit(self) -> None:
        for case_id in RP.case_ids():
            with self.subTest(case=case_id):
                recorded = RP.expected(case_id)
                self.assertEqual(case_id, recorded["case_id"])
                self.assertRegex(recorded["recorded_at"], r"^[0-9a-f]{40}$")

    def test_a_case_supplies_the_designer_output_so_no_commission_is_provoked(self) -> None:
        """The structural half of "no live dispatch".

        `_run_authored` writes an `AGENT_COMMISSION` exactly when the proposal or
        the model is absent. A case that carries both cannot reach that branch,
        which is a stronger statement than counting calls afterwards.
        """
        for case_id in RP.case_ids():
            with self.subTest(case=case_id):
                names = {Path(name).name for name in RP.recorded_files(case_id)}
                self.assertIn("design_proposal.json", names)
                self.assertIn("model.py", names)
                self.assertIn("project.json", names)


if __name__ == "__main__":
    unittest.main()
