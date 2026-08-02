#!/usr/bin/env python3
"""L0-heavy — the half of
`skills/3d-modeling/scripts/designer_toolkit/test_doctor.py`
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
import unittest

# The fixtures this half shares with the half that stayed behind,
# imported rather than copied: two spellings of one fixture is how
# two tiers stop testing the same thing.
from designer_toolkit.test_doctor import (  # noqa: E402
    _SCRIPTS,
)


class CliTest(unittest.TestCase):
    def test_json_output_is_parseable(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "designer_toolkit", "doctor", "--json"],
            cwd=_SCRIPTS, capture_output=True, text=True, check=False)

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("capabilities", json.loads(completed.stdout))

    def test_the_text_form_names_the_backends_it_found(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "designer_toolkit", "doctor"],
            cwd=_SCRIPTS, capture_output=True, text=True, check=False)

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("commission can run", completed.stdout)
