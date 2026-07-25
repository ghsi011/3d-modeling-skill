"""Tests for the environment preflight.

An archived run spent turns discovering by trial which interpreter had a CAD
kernel; another skipped a datum check after learning mid-run that its
environment lacked the `section` extra. The property under test is that one call
answers both, and that it distinguishes "cannot run" from "runs with less".
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from designer_toolkit import doctor  # noqa: E402


class ReportTest(unittest.TestCase):
    def test_it_reports_the_interpreter_running_it(self) -> None:
        """The whole question one run could not answer: *which* python is this."""
        data = doctor.report()

        self.assertEqual(sys.executable, data["executable"])

    def test_the_core_of_the_gate_is_present_wherever_the_tests_run(self) -> None:
        data = doctor.report()

        self.assertTrue(data["can_run_commission"], data["missing_required"])
        self.assertEqual([], data["missing_required"])

    def test_every_capability_says_what_is_lost_without_it(self) -> None:
        """A preflight that lists absent modules without consequences just moves
        the guessing."""
        for name, entry in doctor.report()["capabilities"].items():
            with self.subTest(module=name):
                self.assertTrue(entry["enables"].strip(), name)
                self.assertTrue(entry["without_it"].strip(), name)

    def test_a_missing_optional_extra_does_not_block_the_gate(self) -> None:
        data = doctor.report()

        optional_absent = [n for n, e in data["capabilities"].items()
                           if not e["present"] and n not in doctor._REQUIRED]
        if optional_absent:
            self.assertTrue(data["can_run_commission"])


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


if __name__ == "__main__":
    unittest.main()
