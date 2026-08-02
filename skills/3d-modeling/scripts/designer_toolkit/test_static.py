"""Tests for the pre-build stage.

Each case is a defect an archived run paid a full build/export/measure cycle to
discover -- or, in the fillet case, four of them. The property under test is
that the same finding now costs no geometry at all.

The half of this file the commit gate will not carry is in
`benchmarks/heavy/test_static_heavy.py`, and runs before merge instead of on
every push: `FailsBeforeTheBuildTest`. Same tests, moved rather than weakened;
`conftest.py` carries the rule and `benchmarks/heavy/README.md` the measurement
behind it.
"""

import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from designer_toolkit import plan, static  # noqa: E402


def _ids(checks):
    return {c.id: c for c in checks}


class WallTest(unittest.TestCase):
    def test_a_wall_under_two_extrusions_fails(self) -> None:
        checks = _ids(static.check({"wall_mm": 0.6, "nozzle_mm": 0.4}, {}))

        self.assertEqual("FAIL", checks["static-wall"].result)
        self.assertIn("0.80 mm floor", checks["static-wall"].detail)

    def test_a_one_millimetre_wall_passes_at_a_point_four_nozzle(self) -> None:
        checks = _ids(static.check({"wall_mm": 1.0, "nozzle_mm": 0.4}, {}))

        self.assertEqual("PASS", checks["static-wall"].result)

    def test_the_nozzle_is_read_from_the_plan_when_the_model_is_silent(self) -> None:
        job = {"process": [{"printer_material_nozzle": "X2D; PETG; 0.8mm"}]}

        checks = _ids(static.check({"wall_mm": 1.0}, job))

        self.assertEqual("FAIL", checks["static-wall"].result)
        self.assertIn("1.60 mm floor", checks["static-wall"].detail)


class CavityFilletTest(unittest.TestCase):
    """The four-dispatch bisection.

    One run searched 0.15 -> 0.20 -> 0.25 -> 0.28 for a cavity filleted at
    r = 0.30, watching interference fall 0.250 -> 0.063 -> 0.0076 -> 0.00055.
    The boundary is exactly c >= r, because a fillet's inward pull is largest
    at the mouth plane where it equals its own radius.
    """

    def test_a_fillet_larger_than_the_clearance_fails(self) -> None:
        checks = _ids(static.check(
            {"cavity_mouth_fillet_mm": 0.30, "cavity_clearance_mm": 0.20}, {}))

        check = checks["static-cavity-fillet"]
        self.assertEqual("FAIL", check.result)
        self.assertIn("0.1000 mm", check.detail)
        self.assertIn("do not bisect", check.action.lower())

    def test_clearance_equal_to_the_radius_passes(self) -> None:
        checks = _ids(static.check(
            {"cavity_mouth_fillet_mm": 0.30, "cavity_clearance_mm": 0.30}, {}))

        self.assertEqual("PASS", checks["static-cavity-fillet"].result)

    def test_every_step_of_the_archived_bisection_is_settled_without_geometry(self) -> None:
        for clearance, expected in ((0.15, "FAIL"), (0.20, "FAIL"),
                                    (0.25, "FAIL"), (0.28, "FAIL"), (0.30, "PASS")):
            with self.subTest(clearance=clearance):
                checks = _ids(static.check(
                    {"cavity_mouth_fillet_mm": 0.30, "cavity_clearance_mm": clearance}, {}))
                self.assertEqual(expected, checks["static-cavity-fillet"].result)


class EdgeBudgetTest(unittest.TestCase):
    def test_a_treatment_over_half_the_wall_fails(self) -> None:
        """Both archived Pixel runs put 0.6 mm on a 1.2 mm wall and shipped it."""
        checks = _ids(static.check(
            {"wall_mm": 1.2, "edge_treatments": {"E-01": 0.6}}, {}))

        check = checks["static-edge-E-01"]
        self.assertEqual("FAIL", check.result)
        self.assertIn("50% of a 1.2 mm wall", check.action)
        self.assertIn("would meet and leave nothing", check.action)

    def test_a_modest_treatment_passes(self) -> None:
        checks = _ids(static.check(
            {"wall_mm": 3.0, "edge_treatments": {"E-01": 0.4, "E-02": 0.5}}, {}))

        self.assertEqual("PASS", checks["static-edge-E-01"].result)
        self.assertEqual("PASS", checks["static-edge-E-02"].result)


class UnsupportableFeatureTest(unittest.TestCase):
    """The 47-minute run, as three checks that cost no build.

    It converged on zero unsupported area across three full build/export/measure
    cycles: a pie-slice mouth at 293.82 mm2, then the bore's own crown at 218.98,
    then a teardrop roof. The bore's roof shape was declared before the first
    build; only the consequence was not.
    """

    def _bore(self, roof: str, job=None):
        job = job or plan.direct_template((40.0, 22.0, 14.0))
        checks = static.check({"horizontal_bores": [{"id": "B1", "roof": roof}]}, job)
        return next(c for c in checks if c.id == "static-bore-B1")

    def test_a_round_bore_cannot_meet_a_zero_ceiling(self) -> None:
        """Measured on a real bore: 207 mm2 at the 45 deg screen, still 39 mm2 at
        -0.99. A downward face is unsupported at every threshold."""
        check = self._bore("round")

        self.assertEqual("FAIL", check.result)
        self.assertIn("every screen threshold", check.detail)
        self.assertIn("teardrop", check.action)

    def test_a_flat_roof_cannot_either(self) -> None:
        self.assertEqual("FAIL", self._bore("flat").result)

    def test_a_teardrop_or_diamond_roof_is_fine(self) -> None:
        for roof in ("teardrop", "diamond"):
            with self.subTest(roof=roof):
                self.assertEqual("PASS", self._bore(roof).result)

    def test_a_budgeted_ceiling_makes_the_crown_affordable(self) -> None:
        """This is a conflict between a feature and a zero ceiling, not a claim
        that round bores are bad. Given a support budget there is nothing to say."""
        job = plan.direct_template((40.0, 22.0, 14.0))
        job["support_rules"][0].update(disposition="SUPPORT_ALLOWED",
                                       allowed_contact_class="nonfunctional underside",
                                       max_out_of_limit_area_mm2=600.0)

        checks = static.check({"horizontal_bores": [{"id": "B1", "roof": "round"}]}, job)

        self.assertEqual([], [c for c in checks if c.id.startswith("static-bore")])

    def test_it_says_not_to_iterate_on_the_surrounding_geometry(self) -> None:
        """What the 47-minute run actually did: two cycles reshaping everything
        around a crown that was never going away."""
        self.assertIn("crown belongs to the bore", self._bore("round").action)


class EnvelopeArithmeticTest(unittest.TestCase):
    def test_declared_size_disagreeing_with_the_plan_fails_before_any_build(self) -> None:
        job = plan.direct_template((40.0, 22.0, 14.0))

        checks = _ids(static.check({"overall_mm": {"x": 40.0, "y": 22.0, "z": 18.0}}, job))

        self.assertEqual("FAIL", checks["static-envelope"].result)
        self.assertIn("+4.00 mm", checks["static-envelope"].detail)

    def test_matching_size_passes(self) -> None:
        job = plan.direct_template((40.0, 22.0, 14.0))

        checks = _ids(static.check({"overall_mm": {"x": 40.0, "y": 22.0, "z": 14.0}}, job))

        self.assertEqual("PASS", checks["static-envelope"].result)


class SilenceTest(unittest.TestCase):
    def test_a_model_with_no_params_says_so_rather_than_passing_quietly(self) -> None:
        checks = static.check(None, {})

        self.assertEqual(1, len(checks))
        self.assertEqual("SKIPPED", checks[0].result)
        self.assertIn("PARAMS", checks[0].action)

    def test_params_the_checks_cannot_read_are_also_reported(self) -> None:
        checks = static.check({"unrelated": 3}, {})

        self.assertEqual("SKIPPED", checks[0].result)

    def test_a_nonfinite_number_is_ignored_rather_than_crashing(self) -> None:
        checks = static.check({"wall_mm": float("nan"), "nozzle_mm": 0.4}, {})

        self.assertEqual("SKIPPED", checks[0].result)


if __name__ == "__main__":
    unittest.main()
