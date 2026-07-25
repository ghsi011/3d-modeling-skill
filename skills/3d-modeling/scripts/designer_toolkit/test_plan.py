"""Tests for the built-in DIRECT plan.

The property under test is provenance, not arithmetic. This file is a legitimate
gate only because nothing in it can depend on the part being judged -- the
moment a default is derived from a measurement, it stops being a gate and
becomes the receipt four archived runs wrote.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from designer_toolkit import plan  # noqa: E402


class DirectTemplateTest(unittest.TestCase):
    def test_the_envelope_is_the_stated_size(self) -> None:
        built = plan.direct_template((40.0, 22.0, 14.0))

        self.assertEqual({"x": 40.0, "y": 22.0, "z": 14.0}, built["expected_bbox_mm"])

    def test_it_declares_where_its_numbers_came_from(self) -> None:
        """A plan that merely looks authored is indistinguishable from one that
        was, which is how a self-authored ceiling passed review."""
        built = plan.direct_template((10.0, 10.0, 10.0))

        self.assertEqual("builtin-default", built["threshold_source"])
        self.assertNotEqual("print-engineer", built["owner"])

    def test_the_support_ceiling_is_zero_and_self_support_is_required(self) -> None:
        rule = plan.direct_template((10.0, 10.0, 10.0))["support_rules"][0]

        self.assertEqual("SELF_SUPPORT_REQUIRED", rule["disposition"])
        self.assertEqual(0.0, rule["max_out_of_limit_area_mm2"])

    def test_the_overhang_angle_is_the_conservative_one(self) -> None:
        """-0.73 is steeper than 45 deg, so it flags fewer faces. An unreviewed
        default must not be the more permissive of the two constants."""
        rule = plan.direct_template((10.0, 10.0, 10.0))["support_rules"][0]

        self.assertAlmostEqual(-0.70710678, rule["downward_normal_z_max"], places=6)
        self.assertGreater(rule["downward_normal_z_max"], -0.73)

    def test_no_interfaces_or_edges_are_invented(self) -> None:
        built = plan.direct_template((10.0, 10.0, 10.0))

        self.assertEqual([], built["interfaces"])
        self.assertEqual([], built["edges"])

    def test_a_degenerate_envelope_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            plan.direct_template((10.0, 0.0, 10.0))

    def test_two_calls_with_the_same_input_agree(self) -> None:
        self.assertEqual(plan.direct_template((5.0, 6.0, 7.0)),
                         plan.direct_template((5.0, 6.0, 7.0)))


class CliTest(unittest.TestCase):
    def test_it_writes_a_plan_commission_can_read(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw) / "print_plan_checks.json"

            completed = subprocess.run(
                [sys.executable, "-m", "designer_toolkit.plan",
                 "--bbox", "40", "22", "14", "--out", str(out)],
                cwd=_SCRIPTS, capture_output=True, text=True, check=False,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual("print-plan", payload["contract"])
            self.assertEqual(14.0, payload["expected_bbox_mm"]["z"])


if __name__ == "__main__":
    unittest.main()
