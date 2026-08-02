#!/usr/bin/env python3
"""L0-heavy — the half of
`skills/3d-modeling/scripts/designer_toolkit/test_static.py`
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
from designer_toolkit import plan  # noqa: E402

# The fixtures this half shares with the half that stayed behind,
# imported rather than copied: two spellings of one fixture is how
# two tiers stop testing the same thing.
from designer_toolkit.test_static import (  # noqa: E402
    _SCRIPTS,
)


class FailsBeforeTheBuildTest(unittest.TestCase):
    def test_a_static_failure_costs_no_export(self) -> None:
        """The whole point. If the export still runs, nothing was saved."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            model = work / "model.py"
            model.write_text(
                "PARAMS = {'wall_mm': 0.6, 'nozzle_mm': 0.4}\n"
                "def build():\n"
                "    raise AssertionError('build() must not run after a static failure')\n",
                encoding="utf-8")
            plan_path = work / "plan.json"
            plan_path.write_text(json.dumps(plan.direct_template((10.0, 10.0, 10.0))),
                                 encoding="utf-8")
            out = work / "out"

            completed = subprocess.run(
                [sys.executable, "-m", "designer_toolkit.commission", "--model", str(model),
                 "--plan", str(plan_path), "--out", str(out), "--no-render",
                 "--job-id", "t", "--updated-utc", "2026-01-01T00:00:00Z"],
                cwd=_SCRIPTS, capture_output=True, text=True, check=False)

            self.assertEqual(1, completed.returncode, completed.stderr)
            self.assertIn("FAIL static-wall", completed.stderr)
            self.assertFalse((out / "candidate_01.stl").exists(),
                             "nothing should have been exported")
            payload = json.loads((out / "commission.json").read_text(encoding="utf-8"))
            self.assertEqual("static", payload["evidence"]["stage_reached"])
