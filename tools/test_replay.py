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
from pathlib import Path, PurePosixPath

from tools import replay as RP

UNCHANGED = "0" * 64

# The smallest `project.json` `pipeline.project.load` accepts, and what
# `_FakeSurface` starts a project from. `play` reads the real file now that the
# derived status is obtained by calling `status.report` rather than by parsing
# what a `--json` invocation printed, so a fake that wrote a project no loader
# accepts would fail there instead of at the guard each test is about -- which
# is also what the real `branch` avoids by writing a whole project file.
MINIMAL_PROJECT = json.dumps({"schema_version": 1, "job_id": "synthetic",
                              "updated_utc": "1970-01-01T00:00:00Z",
                              "source_mode": "NEW",
                              "consequence": "INCONSEQUENTIAL"})


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _case(directory: Path, *, reviews=(), judgements=None, substitutions=None,
          inputs=None, revisions=None, formulations=None, dispositions=None,
          concludes="BUILT", case_id="synthetic") -> Path:
    """A case on disk under a temporary CASES_ROOT, sealed and loadable.

    `inputs`, `revisions` and `judgements` take the case-relative path inside
    their own tree, so a nested branch layout is written the same way a real
    case writes one.
    """
    room = directory / case_id
    (room / RP.INPUT_DIR).mkdir(parents=True)
    for name, text in (inputs or {"project.json": "{}"}).items():
        _write(room / RP.INPUT_DIR / name, text)
    for name, text in (revisions or {}).items():
        _write(room / RP.REVISION_DIR / name, text)
    for name, payload in (judgements or {}).items():
        _write(room / RP.JUDGEMENT_DIR / f"{name}.json", json.dumps(payload))
    payload = {
        "schema_version": RP.CASE_SCHEMA, "case_id": case_id,
        "use_case": "MODIFY", "source_mode": "MODIFY",
        "consequence": "INCONSEQUENTIAL",
        "request": "benchmarks/fixtures/berlingo-knob/public/request.md",
        "sources": [], "substitutions": substitutions or {},
        "concludes": concludes, "max_invocations": 3,
        "recorded_at": "synthetic", "provenance": "synthetic", "notes": "",
        "inputs_sha256": {},
    }
    if formulations is None:
        payload["reviews"] = list(reviews)
    else:
        payload["formulations"] = list(formulations)
    if dispositions is not None:
        payload["dispositions"] = list(dispositions)
    (room / RP.CASE_FILE).write_text(json.dumps(payload), encoding="utf-8")
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


class TheStatusReadIsADocumentAndNotATranscriptTest(unittest.TestCase):
    """`_status_report` calls `status.report` instead of parsing stdout.

    **This proves the report is reachable as data, because it fails if the
    function returns anything the renderer could not have printed.** The command
    renders the same value with `json.dumps(..., indent=2, sort_keys=True)`, so
    anything that does not survive that call round trip -- a `Path`, a set, a
    dataclass, a tuple, an integer dict key -- is a value that never reached a
    user through `--json` and must not reach this harness either. Deleting the
    hop is only safe while that stays true, and nothing else here would notice:
    the recording keeps three scalar fields per formulation, so a report that
    grew an unprintable value everywhere else would still replay green.

    Run in the failing direction by returning `work_dir` -- a `Path`, the one
    local `report` already holds -- under a key of its own: `json.dumps` raises
    `TypeError: Object of type WindowsPath is not JSON serializable` and this
    test is the only thing in the repository that fails.
    """

    def test_the_report_is_exactly_what_the_command_could_have_printed(self) -> None:
        from pipeline import project as PROJ
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            PROJ.Project(job_id="synthetic", updated_utc="1970-01-01T00:00:00Z",
                         source_mode="NEW",
                         consequence="INCONSEQUENTIAL").save(directory)
            report = RP._status_report(directory)
        # It is the status document, not an empty dict that would round trip
        # for a reason unrelated to the code.
        self.assertEqual("synthetic", report["job_id"])
        self.assertEqual("NOT_RUN", report["final_status"])
        rendered = json.dumps(report, indent=2, sort_keys=True)
        self.assertEqual(report, json.loads(rendered))


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
        self.assertIn("no such judgement", str(caught.exception))

    def test_a_judgement_is_looked_up_under_the_formulation_it_answers(self) -> None:
        """Two siblings answering one review kind are two recorded answers.

        Under a single `judgements/<kind>.json` the first formulation's decision
        would be replayed as the second's -- which is the same class of mistake
        as one shared `reviews/` directory, one level up.
        """
        _case(self.root,
              formulations=[{"alternative_id": "."},
                            {"alternative_id": "snap-fit", "parent": ".",
                             "reason": "no fasteners", "reviews": ["safety"]}],
              judgements={"snap-fit/safety": {"decision": "BLOCK",
                                              "summary": "the clip shears"}})
        case = self._seal()
        self.assertEqual("BLOCK",
                         case.judgement("safety", "snap-fit")["decision"])
        with self.assertRaises(RP.NoRecordedAnswer) as caught:
            case.judgement("safety")
        self.assertIn("judgements", str(caught.exception).replace("\\", "/"))


class _FakeSurface:
    """A `design-tool` that does whatever the test needs it to do next.

    It writes into the *work* directory the way the real one does, which is what
    lets the branch loop be exercised for milliseconds: `branch` moves
    `active_alternative` in `project.json` and creates the directory, and
    everything after that lands wherever `RP.work_dir` now points.
    """

    def __init__(self, project_dir: Path, script) -> None:
        self.project_dir, self.script, self.calls = project_dir, list(script), []

    def _project(self) -> dict:
        path = self.project_dir / "project.json"
        return json.loads(path.read_text(encoding="utf-8") if path.is_file()
                          else MINIMAL_PROJECT)

    def _save(self, payload: dict) -> None:
        (self.project_dir / "project.json").write_text(json.dumps(payload),
                                                       encoding="utf-8")

    def __call__(self, argv: list[str]) -> int:
        self.calls.append(list(argv))
        if argv[0] == "branch":
            payload = self._project()
            rows = list(payload.get("alternatives") or ())
            if "--disposition" in argv:
                wanted = argv[argv.index("--of") + 1]
                state = argv[argv.index("--disposition") + 1]
                basis = (argv[argv.index("--basis") + 1]
                         if "--basis" in argv else "")
                payload["alternatives"] = [
                    {**row, "disposition": state, "basis": basis}
                    if row.get("alternative_id") == wanted else row
                    for row in rows]
                self._save(payload)
                return 0
            if "--activate" in argv:
                wanted = argv[argv.index("--activate") + 1]
                payload["active_alternative"] = (
                    None if wanted == RP.ROOT_ALTERNATIVE else wanted)
            else:
                wanted = argv[argv.index("--id") + 1]
                # `ACTIVE` because that is what `cli.py` writes for a new
                # alternative. A fake that left the field out would make
                # "nothing was decided" look like `None` rather than like the
                # state a formulation is branched into.
                rows.append({"alternative_id": wanted, "disposition": "ACTIVE",
                             "basis": ""})
                payload["alternatives"] = rows
                payload["active_alternative"] = wanted
            self._save(payload)
            RP.work_dir(self.project_dir).mkdir(parents=True, exist_ok=True)
            return 0
        # No `status` branch: the harness reads the report by calling
        # `status.report`, so a fake that still answered that verb would be
        # answering a question nothing asks.
        if argv[0] == "compare":
            # The smallest report `_comparison_marks` can read. Everything it
            # does not name is absent on purpose: a fake that filled in the
            # whole payload would stop the marks function from having to cope
            # with a report that is missing a block.
            print(json.dumps({"compared": [RP.ROOT_ALTERNATIVE, "snap-fit"],
                              "built_nothing": True,
                              "ranking": None, "score": None,
                              "axes": {"mandatory": {"verdict": "COMPARABLE"}}}))
            return 0
        if argv[0] == "route":
            return 0
        work = RP.work_dir(self.project_dir)
        code, action = self.script.pop(0) if self.script else (0, None)
        pending = work / "next_action.json"
        if action is None:
            pending.unlink(missing_ok=True)
            # A run that stops with nothing pending has concluded, and the real
            # one leaves a final status behind when it does. `_apply_dispositions`
            # reads exactly that to decide whether the job finished, so a fake
            # that skipped it would make every decision test vacuous.
            (work / "final_status.json").write_text(
                json.dumps({"final_status": "VERIFIED"}), encoding="utf-8")
        else:
            (work / "reviews").mkdir(parents=True, exist_ok=True)
            if action.get("kind") == "REVIEW":
                (work / action["evidence"]).write_text(
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

    def test_an_unbranched_project_issues_no_branch_command_at_all(self) -> None:
        """The zero-cost half, in the harness rather than in the pipeline.

        A case that declares no formulations must play the sequence it played
        before formulations existed -- which is why the two cases recorded
        before this arrived did not have to be re-recorded.
        """
        _case(self.root)
        case = self._seal()
        project = self.root / "project"
        project.mkdir()
        (project / "project.json").write_text(
            json.dumps({"active_alternative": None}), encoding="utf-8")
        surface = _FakeSurface(project, [(0, None)])
        run = RP.play(case, project, invoke=surface)
        self.assertEqual([0, 0], run.exit_codes)
        self.assertEqual({RP.ROOT_ALTERNATIVE: project}, run.work_dirs)
        self.assertEqual({}, run.derived)
        self.assertEqual([], [argv for argv in surface.calls
                              if argv[0] in ("branch", "status")])

    def test_each_formulation_is_reached_through_the_branch_verb(self) -> None:
        """The resolver, driven the way a user drives it.

        Every path below the first `branch` has moved: the instruction, the
        review packet and the answer are all in `alternatives/<id>/`, and a
        harness that kept joining against the project root would look for the
        packet where nobody put it.
        """
        _case(self.root,
              formulations=[{"alternative_id": "."},
                            {"alternative_id": "snap-fit", "parent": ".",
                             "reason": "no fasteners", "reviews": ["safety"]}],
              judgements={"snap-fit/safety": {"decision": "PASS",
                                              "summary": "fine"}})
        case = self._seal()
        project = self.root / "project"
        project.mkdir()
        (project / "project.json").write_text(MINIMAL_PROJECT, encoding="utf-8")
        surface = _FakeSurface(project, [(0, None),
                                         (RP.NEEDS_ACTION, self.REVIEW),
                                         (0, None)])
        run = RP.play(case, project, invoke=surface)
        self.assertEqual(["safety"], run.reviews_answered)
        self.assertEqual(
            {RP.ROOT_ALTERNATIVE: project,
             "snap-fit": project / RP.ALTERNATIVES_DIR / "snap-fit"},
            run.work_dirs)
        self.assertEqual(["alternatives/snap-fit/reviews/safety_response.json"],
                         run.responses_written,
                         "the answer is written into the branch's own directory, "
                         "and is named by the path rather than by the filename "
                         "two siblings would share")
        self.assertEqual(
            ["branch", str(project), "--from", ".", "--id", "snap-fit",
             "--reason", "no fasteners"],
            [argv for argv in surface.calls if argv[0] == "branch"][0])

    def test_the_comparison_is_issued_once_and_after_everything_else(self) -> None:
        """A comparison of a job half-finished is a verdict about late evidence.

        Position, not merely presence: `compare` reads the receipts on disk, so
        issuing it between formulations would report `NOT_RUN` for every sibling
        that had not had its turn yet and freeze that as the job's answer. Once,
        because it is over the whole job rather than over a formulation.
        """
        _case(self.root,
              formulations=[{"alternative_id": "."},
                            {"alternative_id": "snap-fit", "parent": ".",
                             "reason": "no fasteners", "reviews": ["safety"]}],
              judgements={"snap-fit/safety": {"decision": "PASS",
                                              "summary": "fine"}})
        case = self._seal()
        project = self.root / "project"
        project.mkdir()
        (project / "project.json").write_text(MINIMAL_PROJECT, encoding="utf-8")
        surface = _FakeSurface(project, [(0, None),
                                         (RP.NEEDS_ACTION, self.REVIEW),
                                         (0, None)])
        run = RP.play(case, project, invoke=surface)

        verbs = [argv[0] for argv in surface.calls]
        self.assertEqual(1, verbs.count("compare"))
        self.assertEqual("compare", verbs[-1])
        self.assertEqual("COMPARABLE", run.comparison["mandatory_verdict"])
        self.assertIsNone(run.comparison["ranking"])

    def test_a_ranking_under_any_name_at_all_moves_the_recording(self) -> None:
        """ADR 0005 pinned by shape, not by two literal field names.

        Measured by a review of the commit that added `_comparison_marks`:
        adding `rank_order` and `overall_score` to the report left the whole
        gate green -- 86 passed -- because `ranking` and `score` were pinned by
        name and the payload's shape was not. A ranking arriving under a name
        nobody thought to forbid is exactly the change this recording exists to
        refuse, so the top-level key set is recorded and compared exactly.
        """
        honest = {"compared": ["."], "ranking": None, "score": None,
                  "built_nothing": True, "axes": {}}
        smuggled = {**honest, "rank_order": [".", "b"], "overall_score": 0.87}

        self.assertEqual(["axes", "built_nothing", "compared", "ranking", "score"],
                         RP._comparison_marks(honest)["payload_keys"])
        differences = RP.compare(
            {"formulations": {}, "comparison": RP._comparison_marks(honest)},
            {"formulations": {}, "comparison": RP._comparison_marks(smuggled)})
        self.assertTrue(
            [row for row in differences
             if row.severity == RP.BINDING and "payload_keys" in row.where],
            "a report that grew a ranking under another name must move the "
            "recording, or the guarantee is two field names rather than a rule")

    def test_an_unbranched_case_issues_no_comparison_at_all(self) -> None:
        """`compare` refuses a job with one formulation, and rightly.

        So a harness that issued it anyway would record an error where the
        branched cases record a report, and the two cases recorded before
        formulations existed would have had to move to say nothing.
        """
        case, project, run = self._play([(0, None)])
        self.assertEqual({}, run.comparison)
        self.assertNotIn("comparison", RP.observe(case, run))

    def _decided(self, dispositions, script=None, **kw):
        """A two-formulation case that concludes, with decisions declared."""
        _case(self.root,
              formulations=[{"alternative_id": "."},
                            {"alternative_id": "snap-fit", "parent": ".",
                             "reason": "no fasteners"}],
              dispositions=dispositions, **kw)
        case = self._seal()
        project = self.root / "project"
        project.mkdir()
        (project / "project.json").write_text(MINIMAL_PROJECT, encoding="utf-8")
        surface = _FakeSurface(project, script or [(0, None), (0, None)])
        return case, project, surface

    def test_a_declared_decision_is_taken_through_the_verb_a_user_has(self) -> None:
        """Gate 4.5's mechanism, at L0 speed.

        One command per decision, after everything else, with the basis on the
        command line -- because a disposition that reached `project.json` by any
        other route would be a state this harness set rather than a decision the
        product recorded.
        """
        case, project, surface = self._decided(
            [{"alternative_id": "snap-fit", "disposition": "PREFERRED",
              "basis": "USER_SELECTION"}])
        run = RP.play(case, project, invoke=surface)

        self.assertEqual(
            ["branch", str(project), "--disposition", "PREFERRED",
             "--of", "snap-fit", "--basis", "USER_SELECTION"],
            surface.calls[-1],
            "last, so the comparison that informs it has already run")
        self.assertEqual(
            {"snap-fit": {"disposition": "PREFERRED",
                          "basis": "USER_SELECTION", "superseded_by": ""}},
            RP.observe(case, run)["dispositions"]["by_alternative"])

    def test_nothing_is_decided_about_a_job_that_did_not_finish(self) -> None:
        """The fail-closed half, and it is not what the product would do.

        `design-tool branch --disposition` accepts a formulation that never
        concluded -- retaining an unfinished alternative as a fallback is a
        legitimate thing to want. But a *recording* that carried a preference
        formed over a formulation with no final status would be evidence of a
        decision nobody could have made, so the harness declines to take the
        declared decisions at all.
        """
        case, project, surface = self._decided(
            [{"alternative_id": "snap-fit", "disposition": "PREFERRED",
              "basis": "USER_SELECTION"}],
            # The second formulation stops with an instruction still pending, so
            # it writes no final status.
            script=[(0, None), (RP.NEEDS_ACTION, {"kind": "OTHER"})])
        run = RP.play(case, project, invoke=surface)

        self.assertNotIn("--disposition", [a for argv in surface.calls for a in argv])
        self.assertEqual(
            {"snap-fit": {"disposition": "ACTIVE", "basis": "",
                          "superseded_by": ""}},
            RP.observe(case, run)["dispositions"]["by_alternative"],
            "still in the state it was branched into, with no basis: the "
            "recording says nobody decided rather than saying nothing")

    def test_a_decision_the_product_refuses_stops_the_play(self) -> None:
        case, project, _ = self._decided(
            [{"alternative_id": "snap-fit", "disposition": "PREFERRED",
              "basis": "USER_SELECTION"}])

        class _Refuses(_FakeSurface):
            def __call__(self, argv):
                if "--disposition" in argv:
                    self.calls.append(list(argv))
                    return 2
                return super().__call__(argv)

        with self.assertRaises(RP.ReplayError) as caught:
            RP.play(case, project, invoke=_Refuses(project, [(0, None), (0, None)]))
        self.assertIn("--disposition", str(caught.exception))

    def test_a_basis_the_pipeline_does_not_know_is_refused_at_load(self) -> None:
        """Against `project.DISPOSITION_BASIS`, not a copy of it.

        A harness holding its own list would let a case declare a basis the
        product refuses, and the play would fail two commands later with a
        message about `project.json` rather than about the case.
        """
        _case(self.root,
              formulations=[{"alternative_id": "."},
                            {"alternative_id": "snap-fit", "parent": ".",
                             "reason": "no fasteners"}],
              dispositions=[{"alternative_id": "snap-fit",
                             "disposition": "PREFERRED",
                             "basis": "IT_LOOKED_BETTER"}])
        with self.assertRaises(RP.ReplayError) as caught:
            self._seal()
        self.assertIn("IT_LOOKED_BETTER", str(caught.exception))

    def test_a_decision_with_no_basis_is_refused_at_load(self) -> None:
        """14.6: a disposition records why, or it records that somebody moved on."""
        _case(self.root,
              formulations=[{"alternative_id": "."},
                            {"alternative_id": "snap-fit", "parent": ".",
                             "reason": "no fasteners"}],
              dispositions=[{"alternative_id": "snap-fit",
                             "disposition": "FALLBACK"}])
        with self.assertRaises(RP.ReplayError) as caught:
            self._seal()
        self.assertIn("basis", str(caught.exception))

    def test_an_unbranched_case_may_not_declare_a_decision(self) -> None:
        """There is nothing to decide between, and the root is not a candidate."""
        _case(self.root, dispositions=[{"alternative_id": "snap-fit",
                                        "disposition": "PREFERRED",
                                        "basis": "USER_SELECTION"}])
        with self.assertRaises(RP.ReplayError) as caught:
            self._seal()
        self.assertIn("no formulations", str(caught.exception))

    def test_a_case_that_does_not_build_may_not_declare_a_decision(self) -> None:
        """Otherwise the skip is permanent and silent.

        `_apply_dispositions` takes nothing when a formulation left no final
        status, and a case declaring `concludes: REFUSED` never leaves one. The
        decisions would then be skipped on every play for ever, and the
        recording would contradict the case that produced it with nothing red to
        say so. Found by a review, which constructed exactly this case and
        watched it load.
        """
        _case(self.root, concludes="REFUSED",
              formulations=[{"alternative_id": "."},
                            {"alternative_id": "snap-fit", "parent": ".",
                             "reason": "no fasteners"}],
              dispositions=[{"alternative_id": "snap-fit",
                             "disposition": "PREFERRED",
                             "basis": "USER_SELECTION"}])
        with self.assertRaises(RP.ReplayError) as caught:
            self._seal()
        self.assertIn("REFUSED", str(caught.exception))

    def test_a_decision_about_a_formulation_the_case_never_declared_is_refused(self) -> None:
        """Checked against the declared set, not only against the id's shape.

        `_disposition` validated that the id *could* be a directory name and
        nothing more, so a typo loaded cleanly and died two verbs later with a
        message about `project.json` -- the failure that function's own docstring
        says it exists to prevent. On a play where the decisions are skipped it
        never failed at all.
        """
        _case(self.root,
              formulations=[{"alternative_id": "."},
                            {"alternative_id": "snap-fit", "parent": ".",
                             "reason": "no fasteners"}],
              dispositions=[{"alternative_id": "snapfit",
                             "disposition": "PREFERRED",
                             "basis": "USER_SELECTION"}])
        with self.assertRaises(RP.ReplayError) as caught:
            self._seal()
        self.assertIn("snapfit", str(caught.exception))
        self.assertIn("snap-fit", str(caught.exception),
                      "and it names what there is")

    def test_a_superseded_formulation_must_say_what_replaced_it(self) -> None:
        """The product's second requirement, mirrored beside its first.

        `BASIS_REQUIRED` was checked here and `SUCCESSOR_REQUIRED` was not, so a
        `SUPERSEDED` row with no successor loaded and failed at the command
        line. `SUPERSEDED` without one asserts that something better exists with
        no way to find it.
        """
        def declare(**over):
            _case(self.root,
                  formulations=[{"alternative_id": "."},
                                {"alternative_id": "snap-fit", "parent": ".",
                                 "reason": "no fasteners"},
                                {"alternative_id": "welded", "parent": ".",
                                 "reason": "the successor"}],
                  dispositions=[{"alternative_id": "snap-fit",
                                 "disposition": "SUPERSEDED",
                                 "basis": "STRONGER_CONCEPT", **over}])

        declare()
        with self.assertRaises(RP.ReplayError) as caught:
            self._seal()
        self.assertIn("successor", str(caught.exception))

        self.raw.cleanup()
        self.raw = tempfile.TemporaryDirectory()
        self.addCleanup(self.raw.cleanup)
        self.root = Path(self.raw.name)
        RP.CASES_ROOT = self.root
        declare(superseded_by="welded")
        self.assertEqual(
            ("welded",),
            tuple(row.superseded_by for row in self._seal().dispositions),
            "and a successor that is named loads, so the check is not a ban")

    def test_a_successor_the_case_never_declared_is_refused(self) -> None:
        """The same rule as the alternative id, one field over.

        The first version of the id check looked at `alternative_id` and not at
        `superseded_by` -- the omission it was written to fix, repeated in the
        code fixing it, and found by a review probing the id rule's siblings.
        """
        _case(self.root,
              formulations=[{"alternative_id": "."},
                            {"alternative_id": "snap-fit", "parent": ".",
                             "reason": "no fasteners"}],
              dispositions=[{"alternative_id": "snap-fit",
                             "disposition": "SUPERSEDED",
                             "basis": "STRONGER_CONCEPT",
                             "superseded_by": "ghost"}])
        with self.assertRaises(RP.ReplayError) as caught:
            self._seal()
        self.assertIn("ghost", str(caught.exception))

    def test_a_formulation_may_not_supersede_itself(self) -> None:
        _case(self.root,
              formulations=[{"alternative_id": "."},
                            {"alternative_id": "snap-fit", "parent": ".",
                             "reason": "no fasteners"}],
              dispositions=[{"alternative_id": "snap-fit",
                             "disposition": "SUPERSEDED",
                             "basis": "STRONGER_CONCEPT",
                             "superseded_by": "snap-fit"}])
        with self.assertRaises(RP.ReplayError) as caught:
            self._seal()
        self.assertIn("supersedes itself", str(caught.exception))

    def test_a_successor_on_a_state_that_takes_none_is_refused(self) -> None:
        _case(self.root,
              formulations=[{"alternative_id": "."},
                            {"alternative_id": "snap-fit", "parent": ".",
                             "reason": "no fasteners"}],
              dispositions=[{"alternative_id": "snap-fit",
                             "disposition": "FALLBACK",
                             "basis": "UNRESOLVED_EVIDENCE",
                             "superseded_by": "welded"}])
        with self.assertRaises(RP.ReplayError) as caught:
            self._seal()
        self.assertIn("successor", str(caught.exception))

    def test_a_comparison_that_fails_stops_the_play_rather_than_recording_it(self) -> None:
        """It dispatches nothing and builds nothing, so it has no way to be busy.

        A non-zero code is the verb broken. Recording it would freeze the
        breakage as the expectation, which is the one thing a recording must
        never do.
        """
        _case(self.root,
              formulations=[{"alternative_id": "."},
                            {"alternative_id": "snap-fit", "parent": ".",
                             "reason": "no fasteners"}])
        case = self._seal()
        project = self.root / "project"
        project.mkdir()
        (project / "project.json").write_text(MINIMAL_PROJECT, encoding="utf-8")

        class _Broken(_FakeSurface):
            def __call__(self, argv):
                if argv[0] == "compare":
                    self.calls.append(list(argv))
                    return 2
                return super().__call__(argv)

        with self.assertRaises(RP.ReplayError) as caught:
            RP.play(case, project,
                    invoke=_Broken(project, [(0, None), (0, None)]))
        self.assertIn("compare", str(caught.exception))

    def test_a_branch_that_will_not_be_created_stops_the_play(self) -> None:
        """A `branch` that fails leaves the project on the wrong formulation.

        Without this the next `route` and `run` would succeed against whatever
        was active, and the recording would be compared against a formulation
        nobody asked for.
        """
        _case(self.root, formulations=[{"alternative_id": "snap-fit",
                                        "parent": ".", "reason": "no fasteners"}])
        case = self._seal()
        project = self.root / "project"
        project.mkdir()
        (project / "project.json").write_text(MINIMAL_PROJECT, encoding="utf-8")

        class _RefusesToBranch(_FakeSurface):
            def __call__(self, argv):
                if argv[0] == "branch":
                    self.calls.append(list(argv))
                    return 2
                return super().__call__(argv)

        with self.assertRaises(RP.ReplayError) as caught:
            RP.play(case, project, invoke=_RefusesToBranch(project, [(0, None)]))
        self.assertIn("exited 2", str(caught.exception))

    def test_a_job_that_never_settles_is_reported_rather_than_looped(self) -> None:
        with self.assertRaises(RP.ReplayError) as caught:
            self._play([(RP.NEEDS_ACTION, self.REVIEW)] * 6,
                       reviews=("safety",),
                       judgements={"safety": {"decision": "PASS",
                                              "summary": "fine"}})
        self.assertIn("still asking for something", str(caught.exception))


class TheWorkDirectoryResolverTest(unittest.TestCase):
    """A second implementation of `Project.work_dir`, kept honest against it.

    A second one on purpose: a harness that asked the system under test where to
    look could not catch the system looking in the wrong place. What that buys
    has to be paid for, and this is the payment -- the two answers are compared
    directly, and the two constants the copy depends on are compared to
    `pipeline.project`'s own rather than eyeballed.
    """

    def _project(self, directory: Path, active) -> Path:
        (directory / "project.json").write_text(
            json.dumps({"active_alternative": active}), encoding="utf-8")
        return directory

    def test_an_unbranched_project_resolves_to_its_own_root(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = self._project(Path(raw), None)
            self.assertEqual(directory, RP.work_dir(directory))

    def test_a_branch_resolves_under_alternatives(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = self._project(Path(raw), "snap-fit")
            self.assertEqual(directory / "alternatives" / "snap-fit",
                             RP.work_dir(directory))

    def test_it_agrees_with_the_pipelines_own_resolver(self) -> None:
        from pipeline import project as P
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            for active in (None, "snap-fit"):
                with self.subTest(active=active):
                    self._project(directory, active)
                    project = P.Project(
                        job_id="j", updated_utc="1970-01-01T00:00:00Z",
                        source_mode="NEW", consequence="INCONSEQUENTIAL",
                        active_alternative=active)
                    self.assertEqual(project.work_dir(directory).resolve(),
                                     RP.work_dir(directory).resolve())

    def test_the_two_constants_the_copy_rests_on_are_the_pipelines(self) -> None:
        from pipeline import bindings as B
        from pipeline import project as P
        self.assertEqual(P.ALTERNATIVES_DIR, RP.ALTERNATIVES_DIR)
        self.assertEqual(P.ALTERNATIVE_ID.pattern, RP.ALTERNATIVE_ID.pattern)
        self.assertEqual(B.ROOT_ALTERNATIVE, RP.ROOT_ALTERNATIVE)

    def test_an_id_this_harness_cannot_resolve_is_refused_not_flattened(self) -> None:
        """The one thing the resolver still will not express.

        `design-tool branch` cannot write any of these and `Project.validate`
        reports one as a finding, so the only way to get here is a hand-edited
        `project.json`. Falling back to the project root would compare the shared
        root's receipts and report them as the branch's -- a replay passing for
        the wrong reason, which is what the refusal it replaced existed to stop.
        """
        for active in ("../escape", "Snap-Fit", "snap fit", "a/b", 7):
            with self.subTest(active=active), \
                    tempfile.TemporaryDirectory() as raw:
                directory = self._project(Path(raw), active)
                with self.assertRaises(RP.ReplayError) as caught:
                    RP.work_dir(directory)
                self.assertIn(repr(active), str(caught.exception))


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

    def test_the_input_tree_is_mirrored_rather_than_flattened(self) -> None:
        """`inputs/` *is* the project directory, nesting included.

        Flattened, a branch's `model.py` would land beside the root's and one of
        the two would overwrite the other -- and the case would still load,
        because the digests are of the case tree and not of what was written.
        """
        _case(self.root, inputs={
            "project.json": "{}", "model.py": "ROOT = 1\n",
            "alternatives/snap-fit/model.py": "BRANCH = 1\n"})
        case = self._seal()
        destination = RP.materialise(case, self.root / "work")
        self.assertEqual("ROOT = 1\n",
                         (destination / "model.py").read_text(encoding="utf-8"))
        self.assertEqual(
            "BRANCH = 1\n",
            (destination / "alternatives" / "snap-fit" / "model.py")
            .read_text(encoding="utf-8"))

    def test_a_revision_is_not_materialised_and_lands_after_the_run(self) -> None:
        """The whole point of the third tree.

        A revised input that was materialised would be the input the run used,
        and the verdict would have been issued against it -- so nothing would
        ever have been bound to the version it superseded, which is the state a
        derived `STALE` exists to report.
        """
        _case(self.root, inputs={"project.json": "{}", "model.py": "V = 1\n"},
              revisions={"model.py": "V = 2\n"})
        case = self._seal()
        destination = RP.materialise(case, self.root / "work")
        self.assertEqual("V = 1\n",
                         (destination / "model.py").read_text(encoding="utf-8"))
        RP._apply_revisions(case, destination, case.formulations[0])
        self.assertEqual("V = 2\n",
                         (destination / "model.py").read_text(encoding="utf-8"))

    def test_a_revision_belongs_to_the_formulation_whose_tree_it_sits_in(self) -> None:
        _case(self.root,
              formulations=[{"alternative_id": "."},
                            {"alternative_id": "snap-fit", "parent": ".",
                             "reason": "no fasteners"}],
              inputs={"project.json": "{}", "model.py": "V = 1\n",
                      "alternatives/snap-fit/model.py": "V = 1\n"},
              revisions={"alternatives/snap-fit/model.py": "V = 2\n"})
        case = self._seal()
        destination = RP.materialise(case, self.root / "work")
        root, branch = case.formulations
        RP._apply_revisions(case, destination, root)
        self.assertEqual("V = 1\n",
                         (destination / "model.py").read_text(encoding="utf-8"),
                         "the root's own model is not touched by a branch's "
                         "revision")
        RP._apply_revisions(case, destination, branch)
        self.assertEqual(
            "V = 2\n",
            (destination / "alternatives" / "snap-fit" / "model.py")
            .read_text(encoding="utf-8"))


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

    # The branched arm of `compare`. `BASE` above has no `formulations` key, so
    # nothing else in this class reaches it -- which is how the `dispositions`
    # guard came to be the one binding comparison in the whole harness with no
    # mutation test behind it. A review deleted the call and measured the
    # result: L0 identical, L1 identical, 121 passed either way. Deleting the
    # sibling `comparison` line goes red at L0 in under a second, so the shape
    # was already known and had been applied one level down and not one up.
    BRANCHED = {
        "schema_version": RP.EXPECTED_SCHEMA, "case_id": "x",
        "exit_codes": [0], "reviews_answered": [],
        "formulations": {},
        "comparison": {"ranking": None, "score": None},
        "dispositions": {
            "active_alternative": "seated",
            "by_alternative": {
                "seated": {"disposition": "PREFERRED",
                           "basis": "USER_SELECTION", "superseded_by": ""},
                "as-drawn": {"disposition": "FALLBACK",
                             "basis": "UNRESOLVED_EVIDENCE",
                             "superseded_by": ""}}},
    }

    def _branched_diff(self, dispositions):
        return RP.binding(RP.compare(
            self.BRANCHED, {**self.BRANCHED, "dispositions": dispositions}))

    def test_a_decision_that_moved_is_binding(self) -> None:
        """The preference switched to the formulation nobody chose."""
        rows = self.BRANCHED["dispositions"]["by_alternative"]
        moved = {**self.BRANCHED["dispositions"], "by_alternative": {
            "seated": {**rows["seated"], "disposition": "FALLBACK"},
            "as-drawn": {**rows["as-drawn"], "disposition": "PREFERRED"}}}
        found = self._branched_diff(moved)
        self.assertTrue(found)
        self.assertTrue(all("dispositions" in row.where for row in found), found)

    def test_a_basis_that_started_overstating_is_binding(self) -> None:
        """`USER_SELECTION` -> `STRONGER_CONCEPT` is the claim this repo refuses.

        Nothing in the product forbids it while a comparison says preference is
        inadmissible, so the recording is the only thing that would notice.
        """
        rows = self.BRANCHED["dispositions"]["by_alternative"]
        louder = {**self.BRANCHED["dispositions"], "by_alternative": {
            **rows, "seated": {**rows["seated"], "basis": "STRONGER_CONCEPT"}}}
        found = self._branched_diff(louder)
        self.assertTrue(found)
        self.assertTrue(any("basis" in row.where for row in found), found)

    def test_decisions_that_stopped_being_taken_are_binding(self) -> None:
        """The regression the skip rule could otherwise hide.

        A formulation that quietly stops concluding makes `_apply_dispositions`
        skip, and every alternative goes back to `ACTIVE`. Without this the
        recording would have to rely on another test noticing the missing final
        status.
        """
        undecided = {"active_alternative": "seated", "by_alternative": {
            key: {"disposition": "ACTIVE", "basis": "", "superseded_by": ""}
            for key in self.BRANCHED["dispositions"]["by_alternative"]}}
        self.assertTrue(self._branched_diff(undecided))

    def test_the_formulation_the_job_ends_on_is_binding(self) -> None:
        """It decides what `design-tool run` picks up next."""
        moved = {**self.BRANCHED["dispositions"], "active_alternative": "as-drawn"}
        found = self._branched_diff(moved)
        self.assertTrue(any("active_alternative" in row.where for row in found),
                        found)

    def test_an_undecided_job_compares_clean(self) -> None:
        """The guard must not fire on a job where nothing was decided."""
        self.assertEqual([], RP.compare(self.BRANCHED, dict(self.BRANCHED)))

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

    def _directory(self, root: Path, name: str = "project") -> Path:
        directory = root / name
        directory.mkdir(parents=True)
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

    @staticmethod
    def _case(**over) -> RP.ReplayCase:
        base = dict(case_id="x", use_case="MODIFY", source_mode="MODIFY",
                    consequence="INCONSEQUENTIAL", request="r", sources=(),
                    substitutions={},
                    formulations=(RP.Formulation(alternative_id=None),),
                    branched=False, concludes="BUILT", max_invocations=2,
                    inputs_sha256={}, recorded_at="", provenance="", notes="")
        return RP.ReplayCase(**{**base, **over})

    def test_the_receipt_set_excludes_what_the_runner_calls_non_identifying(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = self._directory(Path(raw))
            run = RP.Play(directory, [0], [], [], "",
                          work_dirs={RP.ROOT_ALTERNATIVE: directory})
            observed = RP.observe(self._case(), run)
        self.assertNotIn("timings.json", observed["receipts"])
        self.assertIn("candidate.stl", observed["receipts"])
        self.assertEqual("FAILED", observed["outcome"]["final_status"])
        self.assertEqual({"profile-z": "ANOMALY"},
                         observed["screening_detail"]["detectors"])
        self.assertEqual({"abs": 0.05}, observed["tolerances"]["seated"])
        self.assertNotIn("formulations", observed,
                         "an unbranched job carries no trace of the capability, "
                         "which is why the cases recorded before it arrived "
                         "did not move")

    def test_a_branched_observation_nests_the_same_block_per_formulation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            directory = self._directory(root)
            branch = self._directory(directory, "alternatives/snap-fit")
            run = RP.Play(directory, [0], [], [], "",
                          work_dirs={RP.ROOT_ALTERNATIVE: directory,
                                     "snap-fit": branch},
                          derived={"snap-fit": {"derived_status": "STALE",
                                                "stored_status": "VERIFIED",
                                                "stale": ["final_status.json"]}})
            observed = RP.observe(
                self._case(branched=True,
                           formulations=(RP.Formulation(None),
                                         RP.Formulation("snap-fit"))), run)
        self.assertEqual({".", "snap-fit"}, set(observed["formulations"]))
        self.assertEqual("FAILED",
                         observed["formulations"]["."]["outcome"]["final_status"])
        self.assertEqual("STALE",
                         observed["formulations"]["snap-fit"]["derived"]
                         ["derived_status"])
        self.assertNotIn("outcome", observed,
                         "a branched job has no single outcome; every one of "
                         "them belongs to a formulation")

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
            for formulation in case.formulations:
                for kind in formulation.reviews:
                    with self.subTest(case=case_id, formulation=formulation.key,
                                      review=kind):
                        self.assertIn("decision", case.judgement(
                            kind, formulation.alternative_id))

    def test_every_declared_formulation_has_somewhere_to_be_played_from(self) -> None:
        """A parent nothing declares is a `branch` that cannot succeed.

        Caught by loading rather than by playing, which is the difference
        between a case that says what is wrong with it and one that fails eleven
        seconds later inside a command whose output nobody kept.
        """
        for case_id in RP.case_ids():
            case = RP.load(case_id)
            # The shared root is always a legitimate parent and is never itself
            # declared by a `branch`, so it starts in one set and not the other.
            parents = {RP.ROOT_ALTERNATIVE}
            declared: set[str] = set()
            for formulation in case.formulations:
                with self.subTest(case=case_id, formulation=formulation.key):
                    self.assertIn(formulation.parent, parents,
                                  "a formulation is branched from the shared "
                                  "root or from one declared before it")
                    self.assertNotIn(formulation.key, declared,
                                     "two rows for one formulation")
                declared.add(formulation.key)
                parents.add(formulation.key)

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
        which is a stronger statement than counting calls afterwards -- and it
        has to hold for *every* formulation, because a branch that inherited
        nothing is exactly the job that asks a designer to author one.

        A case declared `REFUSED` is refused before the builder is reached and
        carries neither; what it must not do is build, which
        `test_a_refused_case_builds_nothing_at_all` states directly.
        """
        for case_id in RP.case_ids():
            case = RP.load(case_id)
            if case.concludes != "BUILT":
                continue
            names = set(RP.recorded_files(case_id))
            self.assertIn(f"{RP.INPUT_DIR}/project.json", names)
            for formulation in case.formulations:
                where = PurePosixPath(RP.INPUT_DIR) / formulation.relative_dir()
                with self.subTest(case=case_id, formulation=formulation.key):
                    self.assertIn((where / "design_proposal.json").as_posix(),
                                  names)
                    self.assertIn((where / "model.py").as_posix(), names)

    def test_a_refused_case_builds_nothing_at_all(self) -> None:
        """What `REFUSED` has to mean, stated as an absence in the recording.

        A refusal that still reached the confined build would be a case whose
        expectations were about a job nobody meant to run, and the release gate
        it stands for -- "failures are actionable and controlled" -- would be
        met by something that was neither.
        """
        for case_id in RP.case_ids():
            case = RP.load(case_id)
            if case.concludes == "BUILT":
                continue
            with self.subTest(case=case_id):
                recorded = RP.expected(case_id)
                self.assertIsNone(recorded["outcome"]["final_status"])
                self.assertNotIn("candidate.stl", recorded["receipts"])
                self.assertEqual({}, recorded["checks"])


if __name__ == "__main__":
    unittest.main()
