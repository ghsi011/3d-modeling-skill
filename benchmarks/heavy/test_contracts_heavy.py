#!/usr/bin/env python3
"""L0-heavy — the half of
`skills/3d-modeling/scripts/team_tools/test_contracts.py`
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

# `__file__` is under benchmarks/heavy now; what the moved code reaches through
# it is not. Named from the repository root rather than by a different count of
# `.parent`, because a count is what breaks silently on the next move.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO_ROOT / "skills" / "3d-modeling" / "scripts"

# The fixtures this half shares with the half that stayed behind,
# imported rather than copied: two spellings of one fixture is how
# two tiers stop testing the same thing.
from team_tools.test_contracts import (  # noqa: E402
    _DIMENSIONS,
    _PRINT_PLAN,
    _write_project,
    clone,
)
# ProjectValidateReceiptTest is a test class as well as a fixture; reached
# through the module so this tier does not collect and re-run it.
from team_tools import test_contracts as _l0_half  # noqa: E402


class CliTest(unittest.TestCase):
    SCRIPTS_DIR = _SCRIPTS

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "team_tools.contracts", *args],
            cwd=str(self.SCRIPTS_DIR),
            capture_output=True,
            text=True,
            check=False,
        )

    def test_help_works(self) -> None:
        completed = self._run("--help")
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("validate", completed.stdout)
        self.assertIn("status", completed.stdout)

    def test_validate_cli_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            helper = _l0_half.ProjectValidateReceiptTest()
            helper._build_full_project(project_dir)
            completed = self._run("validate", str(project_dir), "--timestamp", "FIXED")
            self.assertEqual(0, completed.returncode, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual("PASS", payload["results"]["overall"])
            self.assertEqual("FIXED", payload["timestamp"])

    def test_status_cli_exit_code_reflects_staleness(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            dimensions = clone(_DIMENSIONS)
            dimensions["revision"] = 9
            print_plan = clone(_PRINT_PLAN)
            print_plan["dimensions_revision"] = 1
            _write_project(project_dir, dimensions=dimensions, print_plan=print_plan)
            completed = self._run("status", str(project_dir))
            self.assertEqual(1, completed.returncode)
            self.assertIn("STALE", completed.stdout)
