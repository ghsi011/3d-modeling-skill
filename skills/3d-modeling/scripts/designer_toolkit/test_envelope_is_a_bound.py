#!/usr/bin/env python3
"""An envelope is a maximum. It was being checked as a target.

`cli._print_plan` generates a plan when nobody authored one, and builds
`expected_bbox_mm` from the printer and the declared envelope -- deliberately,
and its docstring gives the reason: a plan that took its expectation from the
part it gates would not be a gate.

`_check_envelope` then compared it two-sidedly, `abs(delta) <= tolerance`, so a
part *smaller* than the build volume failed exactly as hard as one larger. Which
is every part. A correct 83.5 x 41.5 x 24.4 mm bin reported

    envelope | Overall size vs plan | FAIL | worst axis z off by -231.60 mm (tolerance 0.5 mm)
    status: NOT_READY

while the frozen acceptance contract passed the same part at the same numbers.

**It fired on every job with a generated plan** -- not intermittently, not on odd
data: on any part smaller than the build volume. And a gate that fails on every
correct part is one its readers learn to discount, which is what hides the single
real envelope failure it exists to catch.

The plan already says which kind of expectation it holds: `owner`, one of the two
in `_EXPECTED_OWNERS["print_plan"]`. A generated plan states a bound; a print
engineer's states a size. No new field was needed.
"""
from __future__ import annotations

import unittest

from .commission import Commission, _check_envelope


class _Report:
    def __init__(self, x: float, y: float, z: float) -> None:
        self.bbox_mm = {"x": x, "y": y, "z": z}


def _run(plan: dict, report: _Report) -> tuple[str, str]:
    commission = Commission()
    _check_envelope(commission, report, plan)
    check = [c for c in commission.checks if c.id == "envelope"][0]
    return check.result, check.detail


GENERATED = {"owner": "builtin-direct-template", "bbox_tolerance_mm": 0.5,
             "expected_bbox_mm": {"x": 256.0, "y": 256.0, "z": 256.0}}
AUTHORED = {"owner": "print-engineer", "bbox_tolerance_mm": 0.5,
            "expected_bbox_mm": {"x": 83.5, "y": 41.5, "z": 24.4}}


class AGeneratedPlansEnvelopeIsABoundTest(unittest.TestCase):

    def test_a_part_that_fits_passes(self) -> None:
        """The observed case: a correct bin inside a 256 mm build volume."""
        result, detail = _run(GENERATED, _Report(83.5, 41.5, 24.4))
        self.assertEqual("PASS", result, detail)

    def test_a_part_that_overflows_still_fails(self) -> None:
        """**Control.** The bound must still bind, or this trades a false alarm
        for a missing gate."""
        result, detail = _run(GENERATED, _Report(83.5, 41.5, 300.0))
        self.assertEqual("FAIL", result, detail)
        self.assertIn("z", detail)

    def test_overflow_beyond_tolerance_on_any_axis_fails(self) -> None:
        for axis, dims in (("x", (300.0, 41.5, 24.4)),
                           ("y", (83.5, 300.0, 24.4)),
                           ("z", (83.5, 41.5, 300.0))):
            with self.subTest(axis=axis):
                self.assertEqual("FAIL", _run(GENERATED, _Report(*dims))[0])

    def test_an_unreadable_expectation_is_not_a_pass(self) -> None:
        """**Control.** 'Every axis fitted' must stay distinguishable from 'no
        axis could be read' -- a key the check cannot read is not a looser check,
        it is no check."""
        plan = {**GENERATED, "expected_bbox_mm": {"depth": 10.0}}
        self.assertEqual("FAIL", _run(plan, _Report(83.5, 41.5, 24.4))[0])


class AnAuthoredPlansSizeIsStillATargetTest(unittest.TestCase):
    """**The control that stops this becoming a hole.** Relaxing the generated
    case must not turn a print engineer's stated size into a bound: undershooting
    a declared dimension is the defect the envelope check was added for -- a case
    once shipped 31% too thick while passing every other gate."""

    def test_a_part_matching_the_stated_size_passes(self) -> None:
        self.assertEqual("PASS", _run(AUTHORED, _Report(83.5, 41.5, 24.4))[0])

    def test_a_part_under_the_stated_size_fails(self) -> None:
        result, detail = _run(AUTHORED, _Report(83.5, 41.5, 20.0))
        self.assertEqual("FAIL", result, detail)

    def test_a_part_over_the_stated_size_fails(self) -> None:
        self.assertEqual("FAIL", _run(AUTHORED, _Report(83.5, 41.5, 30.0))[0])


if __name__ == "__main__":
    unittest.main()
