"""Calibration for the edge measuring instrument.

This module exists because a hand-rolled sampler "read high against its own
nominals and the run widened its acceptance bands to fit". It then shipped with
no tests of its own, which is the same mistake one layer down: an instrument
nobody calibrated is not evidence.

So these assert against *known* radii, and against the two ways a circle fit
returns a confident wrong number.
"""

import math
import sys
import unittest
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from designer_toolkit import edges  # noqa: E402


def _arc(cx: float, cy: float, r: float, a0: float, a1: float, points: int) -> np.ndarray:
    angles = np.linspace(math.radians(a0), math.radians(a1), points)
    return np.column_stack([cx + r * np.cos(angles), cy + r * np.sin(angles)])


class FitCircleTest(unittest.TestCase):
    def test_it_recovers_known_radii_at_every_tessellation(self) -> None:
        for nominal in (0.3, 0.4, 1.0, 3.0):
            for segments in (4, 8, 24, 64):
                with self.subTest(radius=nominal, segments=segments):
                    _cx, _cy, radius, rms = edges.fit_circle(
                        _arc(nominal, nominal, nominal, 180, 270, segments + 1))
                    self.assertAlmostEqual(nominal, radius, places=6)
                    self.assertLess(rms, 1e-6)

    def test_the_residual_is_small_only_when_the_points_really_are_an_arc(self) -> None:
        _cx, _cy, _r, clean = edges.fit_circle(_arc(0.0, 0.0, 0.5, 0, 90, 20))
        straight = np.column_stack([np.linspace(0, 1, 20), np.zeros(20)])
        _cx, _cy, _r, flat = edges.fit_circle(straight)

        self.assertLess(clean, 1e-6)
        self.assertGreaterEqual(flat, clean)


class GuardTest(unittest.TestCase):
    """Two ways to get a confident wrong number out of a good fit."""

    def test_a_window_spanning_two_fillets_is_refused(self) -> None:
        """A 1.2 mm rib carrying two 0.4 mm fillets inside one window fitted a
        radius 63% high with a residual well inside tolerance. The fit is fine;
        it is a circle through the wrong points, and the giveaway is that the
        run turns 180 deg when one corner can only turn about 90.
        """
        both = np.vstack([_arc(0.4, 0.4, 0.4, 180, 270, 12),
                          _arc(0.8, 0.4, 0.4, 270, 360, 12)])
        _cx, _cy, radius, _rms = edges.fit_circle(both)

        self.assertGreater(radius, 0.6, "the fixture must reproduce the inflated fit")
        self.assertGreater(180.0, edges._MAX_ARC_TURN_DEG,
                           "a two-corner run must exceed the turn gate")

    def test_the_turn_gate_leaves_a_single_corner_alone(self) -> None:
        self.assertLess(90.0, edges._MAX_ARC_TURN_DEG,
                        "one 90 deg corner must stay measurable")

    def test_the_residual_tolerance_scales_with_the_radius(self) -> None:
        """A fixed absolute tolerance would be far too loose on a 3 mm fillet
        and far too tight on a 0.3 mm one."""
        small = max(edges._MAX_RESIDUAL_FLOOR_MM, edges._MAX_RESIDUAL_FRACTION * 0.3)
        large = max(edges._MAX_RESIDUAL_FLOOR_MM, edges._MAX_RESIDUAL_FRACTION * 3.0)

        self.assertLess(small, large)
        self.assertGreaterEqual(small, edges._MAX_RESIDUAL_FLOOR_MM)


class ClassifierTest(unittest.TestCase):
    def test_a_finely_tessellated_arc_is_not_called_straight(self) -> None:
        """At 64 segments per quadrant every vertex turns about 1.4 deg, under
        the straight-run threshold, so the strict pass finds nothing and the
        outline used to read as straight through the window."""
        per_vertex = 90.0 / 64.0

        self.assertLess(per_vertex, edges._STRAIGHT_TURN_DEG,
                        "the fixture must reproduce the sub-threshold case")
        self.assertLess(edges._FINE_TURN_DEG, per_vertex,
                        "the retry threshold must admit those vertices")
        self.assertLess(edges._ARC_TOTAL_TURN_DEG, 90.0,
                        "a quadrant must trip the retry")


if __name__ == "__main__":
    unittest.main()
