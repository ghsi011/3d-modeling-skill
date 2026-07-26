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

    def test_a_correct_45_degree_chamfer_is_not_flagged(self) -> None:
        """The bare 45 deg value rejects the standard fix for an overhang. A
        self-supporting chamfer tessellates to -0.70710678118, below the bare
        -0.70710678, so screening there fails correct geometry and the advice
        tells the designer to add the feature that caused the failure."""
        import math

        rule = plan.direct_template((10.0, 10.0, 10.0))["support_rules"][0]
        chamfer_normal_z = -math.cos(math.radians(45.0))

        self.assertGreater(chamfer_normal_z, rule["downward_normal_z_max"],
                           "a 45 deg chamfer must sit above the screen, not on it")
        self.assertAlmostEqual(-0.73, rule["downward_normal_z_max"], places=6)

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
                [sys.executable, "-m", "designer_toolkit.plan", "template",
                 "--bbox", "40", "22", "14", "--out", str(out)],
                cwd=_SCRIPTS, capture_output=True, text=True, check=False,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual("print-plan", payload["contract"])
            self.assertEqual(14.0, payload["expected_bbox_mm"]["z"])


class AgainstTheRealAuditTest(unittest.TestCase):
    """Checked against the tool itself, not against a list I wrote from memory.

    The first version of this template enumerated the fields I believed
    `support_audit` needed and shipped without three of them. It raises on the
    plan before reading any mesh, so the plan was unsatisfiable by any geometry
    -- and a measured run spent 55 minutes finding that out.
    """

    def test_the_template_survives_team_preflight_support_audit(self) -> None:
        import trimesh

        sys.path.insert(0, str(_SCRIPTS))
        import team_preflight  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            stl = work / "box.stl"
            trimesh.creation.box(extents=(40.0, 22.0, 14.0)).export(stl)
            plan_path = work / "print_plan_checks.json"
            plan_path.write_text(json.dumps(plan.direct_template((40.0, 22.0, 14.0))),
                                 encoding="utf-8")

            # The assertion is simply that this does not raise.
            audit, _ = team_preflight.support_audit(
                stl_path=stl, plan_path=plan_path, rule_id="S-01")

            self.assertIn("out_of_limit_area_mm2", audit)

    def test_validate_plan_rejects_what_the_audit_would_reject(self) -> None:
        for field in ("model_to_printer_matrix", "bed_z_mm", "bed_tolerance_mm"):
            with self.subTest(field=field):
                broken = plan.direct_template((40.0, 22.0, 14.0))
                del broken["support_rules"][0][field]

                self.assertIn(field, " ".join(plan.validate_plan(broken)))


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

    def test_an_out_of_range_angle_is_rejected(self) -> None:
        broken = plan.direct_template((40.0, 22.0, 14.0))
        broken["support_rules"][0]["downward_normal_z_max"] = -45.0

        self.assertIn("[-1, 0]", " ".join(plan.validate_plan(broken)))

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


if __name__ == "__main__":
    unittest.main()


class UnboundedThresholdTest(unittest.TestCase):
    """A threshold nobody bounds is a check nobody performs."""

    def test_a_vast_tolerance_is_refused(self) -> None:
        """`--tolerance 1e9` validated clean and then passed a part 100% over its
        envelope, with the receipt counting `envelope` as having run -- which
        defeats the one check whose reason for existing is a candidate that
        shipped 31% too thick."""
        built = plan.direct_template((30.0, 30.0, 10.0), tolerance_mm=1e9, job_id="t")

        problems = plan.validate_plan(built)

        self.assertTrue(any("bbox_tolerance_mm" in p for p in problems), problems)

    def test_a_zero_tolerance_is_refused(self) -> None:
        built = plan.direct_template((30.0, 30.0, 10.0), tolerance_mm=0.0, job_id="t")
        self.assertTrue(any("bbox_tolerance_mm" in p for p in plan.validate_plan(built)))

    def test_an_ordinary_tolerance_passes(self) -> None:
        built = plan.direct_template((30.0, 30.0, 10.0), tolerance_mm=0.5, job_id="t")
        self.assertEqual([], [p for p in plan.validate_plan(built) if "tolerance" in p])

    def test_a_body_count_that_is_not_a_positive_whole_number_is_refused(self) -> None:
        for bad in (0, -2, 1.5, "six"):
            with self.subTest(bodies=bad):
                built = plan.direct_template((30.0, 30.0, 10.0), job_id="t")
                built["expected_bodies"] = bad
                self.assertTrue(any("expected_bodies" in p
                                    for p in plan.validate_plan(built)))

    def test_a_real_body_count_passes(self) -> None:
        built = plan.direct_template((30.0, 30.0, 10.0), job_id="t", bodies=6)
        self.assertEqual([], [p for p in plan.validate_plan(built) if "expected_bodies" in p])


class BridgeDispositionTest(unittest.TestCase):
    """A magnet-pocket roof spans a gap with no scaffold under it. The slicer
    prints no support, so `SUPPORT_ALLOWED` is false; the area is not zero, so
    `SELF_SUPPORT_REQUIRED` is false. A Gridfinity bin had to declare
    SUPPORT_ALLOWED and then write a contact class saying no face may take
    support -- a field used for the opposite of its purpose."""

    def _rule(self, **patch):
        built = plan.direct_template((84.0, 42.0, 28.0), job_id="bin")
        built["support_rules"][0].update(patch)
        return built

    def test_a_bridge_with_a_budget_is_accepted(self) -> None:
        built = self._rule(disposition="BRIDGED_NO_SUPPORT",
                           max_out_of_limit_area_mm2=320.0)
        self.assertEqual([], [p for p in plan.validate_plan(built) if "S-01" in p])

    def test_a_bridge_with_no_budget_is_refused(self) -> None:
        """Zero budget is SELF_SUPPORT_REQUIRED under another name."""
        built = self._rule(disposition="BRIDGED_NO_SUPPORT",
                           max_out_of_limit_area_mm2=0.0)
        self.assertTrue(any("max_out_of_limit_area_mm2" in p
                            for p in plan.validate_plan(built)))

    def test_a_bridge_may_not_name_a_contact_class(self) -> None:
        """Nothing touches these faces, which is what separates it from
        SUPPORT_ALLOWED -- and naming one asks a print engineer to review
        contacts that will never exist."""
        built = self._rule(disposition="BRIDGED_NO_SUPPORT",
                           max_out_of_limit_area_mm2=320.0,
                           allowed_contact_class="COSMETIC_NON_MATING")
        self.assertTrue(any("allowed_contact_class" in p
                            for p in plan.validate_plan(built)))

    def test_the_other_two_still_behave(self) -> None:
        self.assertTrue(any("SELF_SUPPORT_REQUIRED" in p for p in plan.validate_plan(
            self._rule(disposition="SELF_SUPPORT_REQUIRED",
                       max_out_of_limit_area_mm2=50.0))))
        self.assertTrue(any("allowed_contact_class" in p for p in plan.validate_plan(
            self._rule(disposition="SUPPORT_ALLOWED",
                       max_out_of_limit_area_mm2=50.0))))
