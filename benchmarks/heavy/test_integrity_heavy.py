#!/usr/bin/env python3
"""L0-heavy — the half of
`skills/3d-modeling/scripts/designer_toolkit/test_integrity.py`
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
from designer_toolkit.test_integrity import (  # noqa: E402
    _SCRIPTS,
    _stl,
)


class CliTest(unittest.TestCase):
    def test_it_emits_parseable_json(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            completed = subprocess.run(
                [sys.executable, "-m", "designer_toolkit", "integrity",
                 str(_stl(work / "box.stl"))],
                cwd=_SCRIPTS, capture_output=True, text=True, check=False)

            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertIn("raw_integrity", json.loads(completed.stdout))

    def test_a_missing_file_is_named_not_tracebacked(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            completed = subprocess.run(
                [sys.executable, "-m", "designer_toolkit", "integrity",
                 str(Path(raw) / "absent.stl")],
                cwd=_SCRIPTS, capture_output=True, text=True, check=False)

            self.assertEqual(2, completed.returncode)
            self.assertIn("absent.stl", completed.stderr)
