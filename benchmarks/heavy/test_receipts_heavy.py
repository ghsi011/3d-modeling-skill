#!/usr/bin/env python3
"""L0-heavy — the half of
`skills/3d-modeling/scripts/designer_toolkit/test_receipts.py`
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
from designer_toolkit import plan, receipts  # noqa: E402

# The fixtures this half shares with the half that stayed behind,
# imported rather than copied: two spellings of one fixture is how
# two tiers stop testing the same thing.
from designer_toolkit.test_receipts import (  # noqa: E402
    _SCRIPTS,
    _WHEN,
    _run,
    _seated_box,
)


class CliTest(unittest.TestCase):
    def test_the_command_emits_both_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            stl = _seated_box(work / "box.stl", (30.0, 20.0, 10.0))
            plan_path = work / "plan.json"
            plan_path.write_text(json.dumps(plan.direct_template((30.0, 20.0, 10.0))),
                                 encoding="utf-8")

            completed = subprocess.run(
                [sys.executable, "-m", "designer_toolkit.commission", "--stl", str(stl),
                 "--plan", str(plan_path), "--out", str(work), "--no-render",
                 "--job-id", "t", "--updated-utc", _WHEN],
                cwd=_SCRIPTS, capture_output=True, text=True, check=False,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertTrue((work / "artifact_manifest.json").is_file())
            self.assertTrue((work / "candidate_readiness.md").is_file())

    def test_the_timestamp_is_injected_so_a_rerun_is_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            first = receipts.build_readiness(_run(work), job_id="t", updated_utc=_WHEN)
            second = receipts.build_readiness(_run(work), job_id="t", updated_utc=_WHEN)

            self.assertEqual(first, second)
