#!/usr/bin/env python3
"""An accepted print plan is the print engineer's, and a run may not replace it.

`_print_plan` generates a template from the printer and the declared envelope and
writes it to `work_dir / print_plan_checks.json` whenever that template validates.
For an unbranched project `Project.work_dir` returns the project root, which is
the path the print engineer's accepted plan occupies: `dt.py audit` defaults to
`<project>/print_plan_checks.json`, `dt.py commission --plan` is pointed at it,
and the role charter names it as the engineer's deliverable. So on any job where
an engineer had already authored a plan, `design-tool run` silently replaced it
with a template carrying no Edge IDs, no declared interfaces, and none of the
deliverable or export-fidelity obligations the charter requires.

Found independently, twice: an external post-mortem of the shipped 0.2.0 build
recorded three separate print-engineer sessions doing nothing but restoring the
plan the run had just overwritten -- 19.0 active minutes and 1.72M tokens spent
re-authoring a file the pipeline deleted -- and the same read of `cli.py`
reproduced it here on a temporary directory in one call.

**The generated template is not wrong; generating it over an author is.** The
template exists because four archived runs with no plan bound let every designer
set its own support ceiling after reading its own measurement, which is a receipt
rather than a gate. That argument holds exactly where nobody has authored a plan,
and nowhere else.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from . import cli
from . import project as P
from . import schemas as S

_IDENTITY = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]

# The template writes -0.73. An author is entitled to a different number, and
# this is the one the fixtures below assert travels.
_AUTHORED_NORMAL_Z_MAX = -0.90
_TEMPLATE_NORMAL_Z_MAX = -0.73

# The 11 keys a project needs to reach `_print_plan` through the real `run`
# endpoint. Dropping any one of `printer`, `material`, `nozzle`, `orientation`,
# `consequence_rationale`, `job_id`, `updated_utc` or `envelope_mm` refuses the
# run at exit 2 *before* the plan is touched; `schema_version` raises. No
# `brief.md`, no `model.py`, no `design_proposal.json` and no `reviewer` are
# needed, because the plan is written before the run looks for any of them --
# which is exactly why the destruction reached jobs that never got as far as a
# build.
_PROJECT = {
    "schema_version": 1,
    "job_id": "plan-authority",
    "updated_utc": "1970-01-01T00:00:00Z",
    "source_mode": "NEW",
    "consequence": "INCONSEQUENTIAL",
    "consequence_rationale": "a fixture; failure wastes nothing",
    "printer": "Test Printer",
    "material": {"process": "FDM", "material": "PLA"},
    "nozzle": {"diameter_mm": 0.4},
    "orientation": {"model_to_printer_matrix": _IDENTITY, "bed_z_mm": 0.0},
    "envelope_mm": {"x": 60.0, "y": 60.0, "z": 60.0},
}

UTC = "1970-01-01T00:00:00Z"


def _project(**over) -> P.Project:
    base = dict(
        job_id="plan-authority", updated_utc=UTC, source_mode="NEW",
        consequence="INCONSEQUENTIAL",
        consequence_rationale="a fixture; failure wastes nothing",
        printer="Test Printer", material={"process": "FDM", "material": "PLA"},
        nozzle={"diameter_mm": 0.4},
        orientation={"model_to_printer": "identity", "bed_z_mm": 0.0},
        envelope_mm={"x": 60.0, "y": 60.0, "z": 60.0},
        reviewer={"model_snapshot": "test"},
    )
    base.update(over)
    return P.Project(**base)


def _accepted_plan() -> dict:
    """A plan an engineer could actually have written, and that validates.

    Deliberately valid: a plan the generator would be entitled to reject is a
    different question, and answering it here would let this row pass for the
    wrong reason.
    """
    return {
        "contract": "print-plan",
        "contract_version": 4,
        "schema_version": 4,
        "candidate_predicate_revision": 1,
        "authored_by": "3d-print-engineer",
        "revision": 3,
        "expected_bbox_mm": {"x": 40.0, "y": 22.0, "z": 14.0},
        "bbox_tolerance_mm": 0.5,
        "edges": [{"id": "E-01", "min_radius_mm": 0.4,
                   "max_radius_mm": None, "samples_required": 3}],
        "support_rules": [{
            "id": "S-01",
            "disposition": "SELF_SUPPORT_REQUIRED",
            "model_to_printer_matrix": _IDENTITY,
            "bed_z_mm": 0,
            "bed_tolerance_mm": 0.05,
            # **The one number the whole slice turns on.** It is the only
            # support-rule field an author may legitimately set differently
            # from the template -- `validate_plan` permits any finite value in
            # [-1, 0] -- it is the only one preflight does not pin to a value
            # the contract already carries, and it is passed straight into the
            # measurement that decides the verdict. The template writes -0.73.
            # On one measured candidate the two answers are 402.206 mm2 FAIL
            # and 0.000 mm2 PASS, with ceiling and tolerance identical: the
            # overwrite is not a cosmetic loss of authorship, it changes the
            # verdict.
            "downward_normal_z_max": _AUTHORED_NORMAL_Z_MAX,
            "max_out_of_limit_area_mm2": 0,
        }],
        # Rule 10 and rule 11, the obligations the charter hardening added.
        # They live in this file, so the overwrite erased them too -- a plan
        # could satisfy both rules perfectly and be replaced before the
        # candidate was judged.
        "deliverables": [{
            "format": "3mf",
            "purpose": "the archive that goes to the slicer",
            "source_geometry": "the accepted candidate solid",
            "units": "millimetre",
            "frame": "installed frame, identity transform",
            "export_path": "make_3mf.py from the exported STL",
            "acceptance": "one printable body, matches the accepted STL",
        }],
        "export_fidelity": {
            "applies_because": "the STL is what the preservation comparison measures",
            "basis": "four-point convergence ladder on this part",
            "worst_error_mm": 0.004,
            "tolerance_it_must_not_consume_mm": 0.1,
        },
    }


class AnAcceptedPlanSurvivesTheRunTest(unittest.TestCase):
    """**These fail on a build that generates over an author, and only then.**"""

    def test_an_accepted_plan_on_disk_is_not_replaced(self) -> None:
        """The defect itself: the file the engineer wrote is still there."""
        accepted = _accepted_plan()
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            path = work / cli.PLAN_FILE
            path.write_text(json.dumps(accepted), encoding="utf-8")
            cli._print_plan(work, _project())
            after = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(accepted, after,
                         "the run replaced a plan it did not author")

    def test_the_plan_the_run_gates_against_is_the_accepted_one(self) -> None:
        """Not only the file. The caller gates the candidate against the value
        this returns, so leaving the file alone and returning the template would
        repair the artifact and leave the gate measuring the template."""
        accepted = _accepted_plan()
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            (work / cli.PLAN_FILE).write_text(json.dumps(accepted),
                                              encoding="utf-8")
            plan, problems = cli._print_plan(work, _project())
        self.assertEqual([], problems, problems)
        self.assertEqual("3d-print-engineer", plan.get("authored_by"))
        self.assertEqual([{"id": "E-01", "min_radius_mm": 0.4,
                           "max_radius_mm": None, "samples_required": 3}],
                         plan.get("edges"),
                         "the gate is reading the generated template")

    def test_an_accepted_plan_that_does_not_validate_is_reported(self) -> None:
        """Refused, not repaired. A run that answers an unbuildable plan by
        substituting a template it wrote itself turns the engineer's error into
        the pipeline's silent decision, which is the same defect wearing the
        opposite sign."""
        broken = _accepted_plan()
        del broken["support_rules"]
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            path = work / cli.PLAN_FILE
            path.write_text(json.dumps(broken), encoding="utf-8")
            _plan, problems = cli._print_plan(work, _project())
            after = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(problems, "an unbuildable accepted plan reported nothing")
        self.assertEqual(broken, after, "the run rewrote the plan it refused")

    def test_a_plan_that_is_not_json_is_reported_rather_than_overwritten(self) -> None:
        """The file exists and cannot be read. Overwriting is the one answer that
        loses whatever it held, and a half-written plan is exactly the state a
        crashed session leaves behind."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            path = work / cli.PLAN_FILE
            path.write_text("{ not json", encoding="utf-8")
            _plan, problems = cli._print_plan(work, _project())
            after = path.read_text(encoding="utf-8")
        self.assertTrue(problems, "an unreadable plan reported nothing")
        self.assertEqual("{ not json", after)


class TheTemplateStillCoversAJobWithNoPlanTest(unittest.TestCase):
    """**The control, and it passes in both builds because it asserts what must
    not change.** Without it, refusing to write anything at all would satisfy
    every row above -- and that would strand exactly the runs the template was
    added for, where no engineer authored a plan and every designer set its own
    ceiling from its own measurement."""

    def test_no_plan_on_disk_still_gets_the_generated_template(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            plan, problems = cli._print_plan(work, _project())
            self.assertEqual([], problems, problems)
            self.assertTrue((work / cli.PLAN_FILE).is_file(),
                            "a job with no authored plan was left without one")
        self.assertEqual("print-plan", plan.get("contract"))
        self.assertTrue(plan.get("support_rules"),
                        "the generated plan must still bind the orientation")


def _seeded(directory: Path, plan: dict | None) -> Path:
    """An unbranched project, optionally with a plan already accepted in it."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "project.json").write_text(json.dumps(_PROJECT), encoding="utf-8")
    if plan is not None:
        (directory / cli.PLAN_FILE).write_text(json.dumps(plan), encoding="utf-8")
    return directory


def _plan_digest(plan: dict) -> str:
    """The hash the commission packet binds: canonical JSON, not file bytes."""
    return hashlib.sha256(S.canonical_json(plan).encode("utf-8")).hexdigest()


class TheRealRunEndpointLeavesTheAcceptedPlanAloneTest(unittest.TestCase):
    """**The load-bearing rows: these drive `design-tool run` itself.**

    The rows above prove the helper behaves; only these prove the *command*
    does, and the difference is the whole defect -- the helper was never the
    thing that ran on a real job. `cli.run([dir, "--no-render"])` is the
    in-process idiom a dozen existing test modules already use, and it reaches
    `_run_authored` through `_run_project`, dispatched on the compiled plan's
    builder.

    They stop at the agent commission rather than building. That is not a
    shortcut around the endpoint: `_print_plan` runs *before* the run looks for
    `model.py` or `design_proposal.json`, so the plan was destroyed on jobs that
    never reached a build at all -- which is most of the jobs this happened to.
    It also costs 13 ms once imports are warm and starts no child process, so
    the real endpoint is affordable in the commit gate. The build path is
    covered in `benchmarks/heavy/`, where it belongs.
    """

    def test_an_accepted_plan_survives_the_real_run_byte_for_byte(self) -> None:
        accepted = _accepted_plan()
        with tempfile.TemporaryDirectory() as raw:
            directory = _seeded(Path(raw) / "job", accepted)
            path = directory / cli.PLAN_FILE
            before = path.read_bytes()
            code = cli.run([str(directory), "--no-render"])
            after = path.read_bytes()
        self.assertEqual(3, code, "the run should stop at the agent commission")
        self.assertEqual(before, after, "the run rewrote the accepted plan")

    def test_the_designer_is_commissioned_against_the_authored_plan(self) -> None:
        """Survival of the file is not enough on its own.

        The commission packet binds `print_plan_sha256`, and that hash is what
        tells the designer which plan it is building against. A build that left
        the file alone and bound the template's hash would be gating the
        candidate against a plan nobody wrote while the authored one sat
        untouched beside it -- the same defect, harder to see.
        """
        accepted = _accepted_plan()
        with tempfile.TemporaryDirectory() as raw:
            directory = _seeded(Path(raw) / "job", accepted)
            cli.run([str(directory), "--no-render"])
            packet = json.loads(
                (directory / "next_action.json").read_text(encoding="utf-8"))
        bound = packet["bound"]["print_plan_sha256"]
        self.assertEqual(_plan_digest(accepted), bound,
                         "the commission binds a plan the engineer did not write")

    def test_the_authored_ceiling_is_what_the_run_leaves_behind(self) -> None:
        """Named separately from the hash, because a hash says *different* and
        not *which*. This says which: the ceiling a candidate will be measured
        against is the author's -0.90 and not the template's -0.73, and the two
        are not interchangeable -- on one measured candidate they are 402.206
        mm2 FAIL and 0.000 mm2 PASS."""
        accepted = _accepted_plan()
        with tempfile.TemporaryDirectory() as raw:
            directory = _seeded(Path(raw) / "job", accepted)
            cli.run([str(directory), "--no-render"])
            after = json.loads(
                (directory / cli.PLAN_FILE).read_text(encoding="utf-8"))
            packet = json.loads(
                (directory / "next_action.json").read_text(encoding="utf-8"))
        self.assertEqual(_AUTHORED_NORMAL_Z_MAX,
                         after["support_rules"][0]["downward_normal_z_max"])
        self.assertNotEqual(_TEMPLATE_NORMAL_Z_MAX,
                            after["support_rules"][0]["downward_normal_z_max"])
        self.assertEqual(_plan_digest(accepted),
                         packet["bound"]["print_plan_sha256"])

    def test_the_charter_obligations_in_the_plan_survive(self) -> None:
        """The specific reason this defect matters now. Rule 10 and rule 11 live
        in this file, so a run that replaces it deletes every deliverable the
        commission named and the export envelope the acceptance decision rests
        on -- while the validator that enforces them stays green, because it is
        handed the template."""
        accepted = _accepted_plan()
        with tempfile.TemporaryDirectory() as raw:
            directory = _seeded(Path(raw) / "job", accepted)
            cli.run([str(directory), "--no-render"])
            after = json.loads(
                (directory / cli.PLAN_FILE).read_text(encoding="utf-8"))
        self.assertEqual(accepted["deliverables"], after.get("deliverables"))
        self.assertEqual(accepted["export_fidelity"], after.get("export_fidelity"))

    def test_argv_reaches_the_same_place(self) -> None:
        """`main` is what the console script calls. A guard that held only for
        the in-process call would leave the shipped command still destroying
        plans."""
        accepted = _accepted_plan()
        with tempfile.TemporaryDirectory() as raw:
            directory = _seeded(Path(raw) / "job", accepted)
            path = directory / cli.PLAN_FILE
            before = path.read_bytes()
            cli.main(["run", str(directory), "--no-render"])
            self.assertEqual(before, path.read_bytes())


class TheRunStillWritesAPlanForAJobThatHasNoneTest(unittest.TestCase):
    """**The endpoint control, and it passes in both builds.**

    Refusing to write at all would satisfy every row above and strand exactly
    the runs the template exists for. This row is what stops the fix from being
    "stop generating plans".
    """

    def test_a_project_with_no_plan_gets_the_generated_template(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _seeded(Path(raw) / "job", None)
            code = cli.run([str(directory), "--no-render"])
            self.assertEqual(3, code)
            written = json.loads(
                (directory / cli.PLAN_FILE).read_text(encoding="utf-8"))
            packet = json.loads(
                (directory / "next_action.json").read_text(encoding="utf-8"))
        self.assertEqual(_TEMPLATE_NORMAL_Z_MAX,
                         written["support_rules"][0]["downward_normal_z_max"])
        self.assertEqual(_plan_digest(written),
                         packet["bound"]["print_plan_sha256"])


if __name__ == "__main__":
    unittest.main()
