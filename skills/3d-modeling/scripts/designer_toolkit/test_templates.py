"""Tests for the parametric starting points.

The property under test is not that geometry comes out. It is that the numbers a
template reports are the numbers the geometry actually has -- because the whole
reason to have templates is that a hand-written model cannot be asked anything,
and a template that reports a wall it did not build is worse than no template.
"""

import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import mesh_io  # noqa: E402
from designer_toolkit import static, templates  # noqa: E402


def _extents(built):
    return built.part.bounds[1] - built.part.bounds[0]


class BoxShellTest(unittest.TestCase):
    def test_the_reported_size_is_the_size_it_built(self) -> None:
        built = templates.box_shell(inner=(120.0, 80.0, 60.0), wall=3.0, floor=3.0)

        measured = _extents(built)
        for axis, index in (("x", 0), ("y", 1), ("z", 2)):
            self.assertAlmostEqual(built.params["overall_mm"][axis], measured[index], places=6)

    def test_the_outer_size_follows_from_the_cavity_and_the_wall(self) -> None:
        built = templates.box_shell(inner=(120.0, 80.0, 60.0), wall=3.0, floor=3.0)

        self.assertAlmostEqual(126.0, built.params["overall_mm"]["x"], places=6)
        self.assertAlmostEqual(86.0, built.params["overall_mm"]["y"], places=6)
        self.assertAlmostEqual(63.0, built.params["overall_mm"]["z"], places=6)

    def test_it_is_a_single_watertight_solid(self) -> None:
        built = templates.box_shell(inner=(40.0, 30.0, 20.0), wall=2.0, floor=2.0)

        self.assertTrue(built.part.is_watertight)
        # The repo's own scipy-free counter: `body_count` pulls in the section
        # extra, which a lean install does not have.
        self.assertEqual(1, mesh_io.connected_component_count(built.part))

    def test_a_closed_box_actually_gets_a_lid(self) -> None:
        """`open_top=False` once produced an identical solid, because the outer
        height left no material above the cavity."""
        opened = templates.box_shell(inner=(40.0, 30.0, 20.0), wall=2.0, floor=2.0)
        closed = templates.box_shell(inner=(40.0, 30.0, 20.0), wall=2.0, floor=2.0,
                                     open_top=False)

        self.assertAlmostEqual(22.0, opened.params["overall_mm"]["z"], places=6)
        self.assertAlmostEqual(24.0, closed.params["overall_mm"]["z"], places=6)
        # The lid is 44 x 34 x 2 mm of extra material.
        self.assertAlmostEqual(44.0 * 34.0 * 2.0,
                               closed.part.volume - opened.part.volume, delta=1.0)

    def test_it_is_seated_on_the_bed(self) -> None:
        built = templates.box_shell(inner=(40.0, 30.0, 20.0), wall=2.0)

        self.assertAlmostEqual(0.0, float(built.part.bounds[0][2]), places=9)

    def test_a_nonsense_wall_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            templates.box_shell(inner=(40.0, 30.0, 20.0), wall=0.0)


class PanelTest(unittest.TestCase):
    def test_openings_actually_remove_material(self) -> None:
        solid = templates.panel(width=100.0, depth=60.0, thickness=3.0)
        holed = templates.panel(width=100.0, depth=60.0, thickness=3.0, openings=(
            {"kind": "rect", "x": 50.0, "y": 30.0, "w": 40.0, "h": 20.0},))

        self.assertAlmostEqual(40.0 * 20.0 * 3.0, solid.part.volume - holed.part.volume,
                               delta=1.0)

    def test_the_narrowest_material_between_openings_becomes_the_wall(self) -> None:
        """Nothing downstream measures this: a sieve with no ribs between its
        holes is watertight, the right size, and unprintable."""
        built = templates.panel(width=100.0, depth=60.0, thickness=3.0, openings=(
            {"kind": "rect", "x": 30.0, "y": 30.0, "w": 20.0, "h": 20.0},
            {"kind": "rect", "x": 50.6, "y": 30.0, "w": 20.0, "h": 20.0},
        ))

        # Openings span 20..40 and 40.6..60.6, so 0.6 mm of material remains.
        self.assertAlmostEqual(0.6, built.params["wall_mm"], places=6)

    def test_that_thin_rib_then_fails_the_pre_build_wall_check(self) -> None:
        """The point of reporting it: the existing gate rejects it for free."""
        built = templates.panel(width=100.0, depth=60.0, thickness=3.0, openings=(
            {"kind": "rect", "x": 30.0, "y": 30.0, "w": 20.0, "h": 20.0},
            {"kind": "rect", "x": 50.6, "y": 30.0, "w": 20.0, "h": 20.0},
        ))

        checks = {c.id: c for c in static.check({**built.params, "nozzle_mm": 0.4}, {})}

        self.assertEqual("FAIL", checks["static-wall"].result)

    def test_a_well_spaced_panel_passes(self) -> None:
        built = templates.panel(width=100.0, depth=60.0, thickness=3.0, openings=(
            {"kind": "rect", "x": 25.0, "y": 30.0, "w": 20.0, "h": 20.0},
            {"kind": "rect", "x": 75.0, "y": 30.0, "w": 20.0, "h": 20.0},
        ))

        checks = {c.id: c for c in static.check({**built.params, "nozzle_mm": 0.4}, {})}
        self.assertEqual("PASS", checks["static-wall"].result)

    def test_an_opening_too_near_the_edge_counts_as_a_thin_rib(self) -> None:
        built = templates.panel(width=100.0, depth=60.0, thickness=3.0, openings=(
            {"kind": "rect", "x": 10.3, "y": 30.0, "w": 20.0, "h": 20.0},))

        self.assertAlmostEqual(0.3, built.params["wall_mm"], places=6)

    def test_round_openings_are_measured_conservatively(self) -> None:
        """A round hole is treated as its bounding square, so the reported
        ligament is a lower bound -- the safe direction for a gate."""
        built = templates.panel(width=100.0, depth=60.0, thickness=3.0, openings=(
            {"kind": "round", "x": 20.0, "y": 30.0, "d": 10.0},
            {"kind": "round", "x": 32.0, "y": 30.0, "d": 10.0},
        ))

        self.assertAlmostEqual(2.0, built.params["wall_mm"], places=6)

    def test_overlapping_openings_report_no_material_at_all(self) -> None:
        built = templates.panel(width=100.0, depth=60.0, thickness=3.0, openings=(
            {"kind": "rect", "x": 30.0, "y": 30.0, "w": 20.0, "h": 20.0},
            {"kind": "rect", "x": 35.0, "y": 30.0, "w": 20.0, "h": 20.0},
        ))

        self.assertEqual(0.0, built.params["wall_mm"])


class BoltBossTest(unittest.TestCase):
    def test_the_annulus_is_reported_as_the_wall(self) -> None:
        built = templates.bolt_boss(outer_d=8.0, bore_d=4.2, height=10.0)

        self.assertAlmostEqual(1.9, built.params["wall_mm"], places=6)

    def test_a_tall_thin_boss_says_so(self) -> None:
        built = templates.bolt_boss(outer_d=6.0, bore_d=3.2, height=30.0)

        self.assertTrue(any("aspect over 4" in n for n in built.notes), built.notes)

    def test_a_bore_wider_than_the_boss_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            templates.bolt_boss(outer_d=4.0, bore_d=4.0, height=10.0)


class StackTest(unittest.TestCase):
    def test_parts_are_laid_out_without_overlapping(self) -> None:
        a = templates.panel(width=40.0, depth=30.0, thickness=3.0)
        b = templates.box_shell(inner=(20.0, 20.0, 10.0), wall=2.0)

        built = templates.stack(a, b, gap=5.0)

        expected_x = 40.0 + 5.0 + 24.0
        self.assertAlmostEqual(expected_x, built.params["overall_mm"]["x"], places=6)
        self.assertAlmostEqual(expected_x, float(_extents(built)[0]), places=6)

    def test_the_thinnest_wall_in_the_set_governs(self) -> None:
        thick = templates.box_shell(inner=(20.0, 20.0, 10.0), wall=3.0)
        thin = templates.box_shell(inner=(20.0, 20.0, 10.0), wall=0.9)

        built = templates.stack(thick, thin)

        self.assertAlmostEqual(0.9, built.params["wall_mm"], places=6)

    def test_an_empty_stack_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            templates.stack()


class AngleTest(unittest.TestCase):
    def test_forty_five_degrees_is_the_bare_screen_value(self) -> None:
        self.assertAlmostEqual(-0.70710678, templates.deg_to_normal_z(45.0), places=7)


if __name__ == "__main__":
    unittest.main()
