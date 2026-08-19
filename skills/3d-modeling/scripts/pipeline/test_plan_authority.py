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

import json
import tempfile
import unittest
from pathlib import Path

from . import cli
from . import project as P

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
            "model_to_printer_matrix": [[1, 0, 0, 0], [0, 1, 0, 0],
                                        [0, 0, 1, 0], [0, 0, 0, 1]],
            "bed_z_mm": 0,
            "bed_tolerance_mm": 0.05,
            "downward_normal_z_max": -0.70710678,
            "max_out_of_limit_area_mm2": 0,
        }],
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


if __name__ == "__main__":
    unittest.main()
