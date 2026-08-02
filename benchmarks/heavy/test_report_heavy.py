#!/usr/bin/env python3
"""L0-heavy — the half of
`skills/3d-modeling/scripts/designer_toolkit/test_report.py`
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

# The fixtures this half shares with the half that stayed behind,
# imported rather than copied: two spellings of one fixture is how
# two tiers stop testing the same thing.
from designer_toolkit.test_report import (  # noqa: E402
    _SCRIPTS,
    _WHEN,
    _commission,
)


class CliTest(unittest.TestCase):
    def test_it_writes_a_draft_from_a_commission_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            source = work / "commission.json"
            source.write_text(json.dumps(_commission()), encoding="utf-8")
            out = work / "verification_report.md"

            completed = subprocess.run(
                [sys.executable, "-m", "designer_toolkit.report", "--commission", str(source),
                 "--out", str(out), "--job-id", "t", "--updated-utc", _WHEN],
                cwd=_SCRIPTS, capture_output=True, text=True, check=False)

            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertIn("contract: verification-report", out.read_text(encoding="utf-8"))
