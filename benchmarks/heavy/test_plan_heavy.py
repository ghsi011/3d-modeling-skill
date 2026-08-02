#!/usr/bin/env python3
"""L0-heavy — the half of
`skills/3d-modeling/scripts/designer_toolkit/test_plan.py`
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
from designer_toolkit.test_plan import (  # noqa: E402
    _SCRIPTS,
)


class CliTest(unittest.TestCase):
    def test_it_writes_a_plan_commission_can_read(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw) / "print_plan_checks.json"

            completed = subprocess.run(
                [sys.executable, "-m", "designer_toolkit.plan", "template",
                 "--bbox", "40", "22", "14", "--out", str(out)],
                cwd=_SCRIPTS, capture_output=True, text=True, check=False,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual("print-plan", payload["contract"])
            self.assertEqual(14.0, payload["expected_bbox_mm"]["z"])

    def test_out_dash_prints_the_plan_to_stdout_portably(self) -> None:
        """`--out -` means stdout on every platform.

        Windows has no `/dev/stdout`, and a bare `Path("-")` would create a file
        literally named `-` in the working directory instead of printing. The
        plan must arrive on stdout as parseable JSON, with no stray path line and
        no `-` file left behind."""
        with tempfile.TemporaryDirectory() as raw:
            completed = subprocess.run(
                [sys.executable, "-m", "designer_toolkit.plan", "template",
                 "--bbox", "40", "22", "14", "--out", "-"],
                cwd=raw, capture_output=True, text=True, check=False,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertFalse((Path(raw) / "-").exists(),
                             "`--out -` must not create a file named '-'")
            payload = json.loads(completed.stdout)
            self.assertEqual("print-plan", payload["contract"])
            self.assertEqual(14.0, payload["expected_bbox_mm"]["z"])

class ValidatePlanTest(unittest.TestCase):
    """Each case is a way an archived run lost time to a plan, not to geometry."""

    def test_the_builtin_template_is_buildable(self) -> None:
        self.assertEqual([], plan.validate_plan(plan.direct_template((40.0, 22.0, 14.0))))

    def test_support_allowed_without_a_contact_class_is_rejected(self) -> None:
        """The exact defect that cost one run 39 minutes: commission passed this
        plan, and nothing rejected it until after the build."""
        broken = plan.direct_template((40.0, 22.0, 14.0))
        broken["support_rules"][0]["disposition"] = "SUPPORT_ALLOWED"

        problems = plan.validate_plan(broken)

        self.assertEqual(1, len(problems), problems)
        self.assertIn("allowed_contact_class", problems[0])

    def test_self_support_with_a_nonzero_ceiling_is_rejected(self) -> None:
        broken = plan.direct_template((40.0, 22.0, 14.0))
        broken["support_rules"][0]["max_out_of_limit_area_mm2"] = 2150.0

        self.assertIn("zero out-of-limit area", " ".join(plan.validate_plan(broken)))

    def test_a_missing_envelope_is_rejected(self) -> None:
        broken = plan.direct_template((40.0, 22.0, 14.0))
        del broken["expected_bbox_mm"]

        self.assertIn("expected_bbox_mm", " ".join(plan.validate_plan(broken)))

    def test_duplicate_rule_ids_are_rejected(self) -> None:
        broken = plan.direct_template((40.0, 22.0, 14.0))
        broken["support_rules"].append(dict(broken["support_rules"][0]))

        self.assertIn("duplicate", " ".join(plan.validate_plan(broken)))

    def test_assembly_meshes_without_a_budget_are_rejected(self) -> None:
        broken = plan.direct_template((40.0, 22.0, 14.0),
                                      assembly_mesh_paths=("other.stl",))

        self.assertIn("assembly_overlap_budget_mm3", " ".join(plan.validate_plan(broken)))

    def test_an_out_of_range_angle_is_rejected(self) -> None:
        broken = plan.direct_template((40.0, 22.0, 14.0))
        broken["support_rules"][0]["downward_normal_z_max"] = -45.0

        self.assertIn("[-1, 0]", " ".join(plan.validate_plan(broken)))

    def test_plan_schema_version_is_required(self) -> None:
        built = plan.direct_template((40.0, 22.0, 14.0))
        del built["schema_version"]
        self.assertTrue(any("schema_version" in problem
                            for problem in plan.validate_plan(built)))

    def test_normative_interface_fields_are_required(self) -> None:
        built = plan.direct_template((40.0, 22.0, 14.0))
        built["interfaces"] = [{
            "id": "I-01", "fit_type": "clearance", "min_mm": 0.1,
            "max_mm": 0.2, "units": "mm", "contact_state": "sliding",
            "uncertainty_mm": 0.02, "acceptance_method": "gauge",
        }]
        for field in ("motion_path", "material", "coupon_required"):
            with self.subTest(field=field):
                row = dict(built["interfaces"][0])
                if field == "coupon_required":
                    row[field] = True
                else:
                    row[field] = "declared"
                built["interfaces"] = [row]
                # The fields are normative and all three must be present in a
                # passing row; remove each one in turn.
                del built["interfaces"][0][field]
                self.assertTrue(any(field in problem
                                    for problem in plan.validate_plan(built)))

    def test_an_interface_without_explicit_bounds_is_rejected(self) -> None:
        built = plan.direct_template((40.0, 22.0, 14.0))
        built["interfaces"] = [{
            "id": "I-01", "fit_type": "clearance", "units": "mm",
            "contact_state": "sliding", "uncertainty_mm": 0.05,
            "acceptance_method": "gauge",
        }]
        problems = plan.validate_plan(built)
        self.assertTrue(any("min_mm" in problem for problem in problems), problems)
        self.assertTrue(any("max_mm" in problem for problem in problems), problems)

    def test_interface_uncertainty_and_units_are_checked(self) -> None:
        built = plan.direct_template((40.0, 22.0, 14.0))
        built["interfaces"] = [{
            "id": "I-01", "fit_type": "clearance", "min_mm": 0.1,
            "max_mm": 0.2, "units": "inch", "contact_state": "sliding",
            "uncertainty_mm": -0.1, "acceptance_method": "gauge",
        }]
        problems = plan.validate_plan(built)
        self.assertTrue(any("units" in problem for problem in problems), problems)
        self.assertTrue(any("uncertainty_mm" in problem for problem in problems), problems)

    def test_check_exits_nonzero_on_an_unbuildable_plan(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "plan.json"
            broken = plan.direct_template((40.0, 22.0, 14.0))
            broken["support_rules"][0]["disposition"] = "SUPPORT_ALLOWED"
            path.write_text(json.dumps(broken), encoding="utf-8")

            completed = subprocess.run(
                [sys.executable, "-m", "designer_toolkit.plan", "check", str(path)],
                cwd=_SCRIPTS, capture_output=True, text=True, check=False,
            )

            self.assertEqual(1, completed.returncode)
            self.assertIn("allowed_contact_class", completed.stderr)
