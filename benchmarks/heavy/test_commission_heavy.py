#!/usr/bin/env python3
"""L0-heavy — the half of
`skills/3d-modeling/scripts/designer_toolkit/test_commission.py`
that costs a child interpreter.

The repository-root `conftest.py` refuses a child interpreter inside the commit
gate, and these classes start one. Same tests, moved rather than weakened;
`benchmarks/heavy/README.md` records the profile that decided the seam and what
runs this tier. What stayed behind is what answers in the parent process.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from designer_toolkit import commission  # noqa: E402

# The fixtures this half shares with the half that stayed behind,
# imported rather than copied: two spellings of one fixture is how
# two tiers stop testing the same thing.
from designer_toolkit.test_commission import (  # noqa: E402
    _SCRIPTS,
    _box_stl,
    _plan,
)


class CliTest(unittest.TestCase):
    def test_a_failing_candidate_exits_nonzero(self) -> None:
        """The whole point: a failing candidate cannot reach a verifier."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            stl = _box_stl(work, extents=(30, 20, 14))
            plan_path = work / "plan.json"
            plan_path.write_text(json.dumps(
                _plan(expected_bbox_mm={"x": 30, "y": 20, "z": 10}, bbox_tolerance_mm=0.5)),
                encoding="utf-8")

            completed = subprocess.run(
                [sys.executable, "-m", "designer_toolkit.commission",
                 "--stl", str(stl), "--plan", str(plan_path),
                 "--out", str(work / "out"), "--no-render",
                 "--updated-utc", "2026-01-01T00:00:00Z"],
                cwd=_SCRIPTS, capture_output=True, text=True, check=False,
            )

            self.assertEqual(completed.returncode, 1)
            self.assertIn("FAIL envelope", completed.stderr)
            self.assertEqual(json.loads(completed.stdout)["verdict"], "FAIL")

    def test_an_ungateable_plan_is_refused_before_any_geometry_is_built(self) -> None:
        """`plan check` was a separate command somebody had to remember to run.
        Skipped, a rule with no `model_to_printer_matrix` still reached
        `planned_placement`, which falls back to `orient.best` and renames the
        placement -- so the gate screened the orientation the part prints best
        in, reported PASS, and said nothing about the one the plan asked for."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            plan = _plan()
            del plan["support_rules"][0]["model_to_printer_matrix"]
            plan_path = work / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")

            completed = subprocess.run(
                [sys.executable, "-m", "designer_toolkit.commission",
                 "--stl", str(_box_stl(work)), "--plan", str(plan_path),
                 "--out", str(work / "out"), "--no-render",
                 "--updated-utc", "2026-01-01T00:00:00Z"],
                cwd=_SCRIPTS, capture_output=True, text=True, check=False,
            )

            self.assertEqual(2, completed.returncode)
            self.assertIn("model_to_printer_matrix", completed.stderr)
            self.assertFalse((work / "out").exists(), "nothing should have been built")

    def test_the_receipt_says_how_much_of_the_gate_ran(self) -> None:
        """PASS says nothing failed; it does not say much ran, and a reader
        takes `status: READY` to mean both."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            result = commission.run(model=None, stl=_box_stl(work), out_dir=work / "out",
                                    plan=_plan(), render=False)

            coverage = result.as_dict()["coverage"]
            self.assertEqual(coverage["declared"], coverage["ran"] + len(coverage["skipped"]))
            self.assertIn("fit", coverage["skipped"],
                          "a plan declaring no interfaces measures no fit")

            from designer_toolkit import receipts
            text = receipts.build_readiness(result.as_dict(), job_id="t",
                                            updated_utc="2026-01-01T00:00:00Z")
            self.assertIn(f"{coverage['ran']} of {coverage['declared']} checks ran", text)
            self.assertIn("`fit`", text)

    def test_it_writes_the_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            commission.run(model=None, stl=_box_stl(work), out_dir=work / "out",
                           plan=_plan(expected_bbox_mm={"x": 30, "y": 20, "z": 10}),
                           render=False)

            payload = json.loads((work / "out" / "commission.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["verdict"], "PASS")
            self.assertIsNone(payload["judgment_required"]["visual_accept"])
