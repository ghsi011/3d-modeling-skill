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


class DeviceCaseTest(unittest.TestCase):
    """The shape two archived runs each hand-wrote, at 26 and 39 minutes."""

    def _case(self, **kw):
        args = dict(device=(73.56, 155.61, 8.5), wall=1.5, clearance=0.25,
                    corner_radius=9.0)
        args.update(kw)
        return templates.device_case(**args)

    def test_the_reference_is_the_device_it_was_given(self) -> None:
        """Two runs hand-wrote a device proxy beside their case, and one debugged
        a false interference caused by forgetting to round its corners."""
        built = self._case()

        measured = built.reference.bounds[1] - built.reference.bounds[0]
        for expected, actual in zip((73.56, 155.61, 8.5), measured):
            self.assertAlmostEqual(expected, actual, places=3)

    def test_the_clearance_is_uniform_on_every_side_including_under(self) -> None:
        """A device resting flush on the cavity floor touches it, so the
        assembly's tightest point reads zero however correct the walls are."""
        built = self._case(clearance=0.25)

        case_low, case_high = built.part.bounds
        ref_low, ref_high = built.reference.bounds
        self.assertAlmostEqual(0.25, float(ref_low[2] - (case_low[2] + 1.5)), places=3)
        self.assertAlmostEqual(1.75, float(ref_low[0] - case_low[0]), places=2)

    def test_the_reported_size_is_the_size_it_built(self) -> None:
        built = self._case()

        measured = built.part.bounds[1] - built.part.bounds[0]
        for axis, index in (("x", 0), ("y", 1), ("z", 2)):
            # places=4, not 6: the rounded corners are tessellated, so the
            # measured extent carries single-precision STL noise the arithmetic
            # does not. Tighter than the gate's own tolerance either way.
            self.assertAlmostEqual(built.params["overall_mm"][axis], measured[index], places=4)

    def test_it_is_a_single_watertight_solid_seated_on_the_bed(self) -> None:
        built = self._case()

        self.assertTrue(built.part.is_watertight)
        self.assertEqual(1, mesh_io.connected_component_count(built.part))
        self.assertAlmostEqual(0.0, float(built.part.bounds[0][2]), places=9)

    def test_an_opening_removes_material(self) -> None:
        plain = self._case()
        holed = self._case(openings=({"x": 0.0, "y": 50.0, "w": 30.0, "h": 25.0},))

        self.assertLess(holed.part.volume, plain.part.volume)

    def test_the_declared_clearance_reaches_the_pre_build_stage(self) -> None:
        checks = {c.id: c for c in static.check(
            {**self._case().params, "nozzle_mm": 0.4,
             "cavity_mouth_fillet_mm": 0.5}, {})}

        self.assertEqual("FAIL", checks["static-cavity-fillet"].result,
                         "a 0.5 mm mouth fillet eats a 0.25 mm clearance")

    def test_a_negative_clearance_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._case(clearance=-0.1)


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


class CClipTest(unittest.TestCase):
    """The part four runs each spent 18-29 minutes on, and one spent 47."""

    def _clip(self, **kw):
        args = dict(bore_d=12.0, wall=3.0, height=9.0, mouth_gap=9.0,
                    flange=(40.0, 22.0, 5.0), screw_d=4.5)
        args.update(kw)
        return templates.c_clip(**args)

    def test_it_is_self_supporting_by_construction(self) -> None:
        """The whole reason the template exists. A horizontal round bore carries
        a crown no surrounding geometry removes; standing the channel along the
        print axis makes every wall a vertical extrusion."""
        from designer_toolkit import metrics

        built = self._clip()

        self.assertAlmostEqual(0.0, metrics.overhang_area(built.part, threshold=-0.73),
                               places=6)
        self.assertAlmostEqual(0.0, metrics.overhang_area(built.part,
                                                          threshold=templates.deg_to_normal_z(45)),
                               places=6)

    def test_the_reported_size_is_the_size_it_built(self) -> None:
        built = self._clip()

        measured = built.part.bounds[1] - built.part.bounds[0]
        for axis, index in (("x", 0), ("y", 1), ("z", 2)):
            self.assertAlmostEqual(built.params["overall_mm"][axis], measured[index], places=4)

    def test_it_is_a_single_watertight_solid_on_the_bed(self) -> None:
        built = self._clip()

        self.assertTrue(built.part.is_watertight)
        self.assertEqual(1, mesh_io.connected_component_count(built.part))
        self.assertAlmostEqual(0.0, float(built.part.bounds[0][2]), places=9)

    def test_the_mouth_actually_opens_the_channel(self) -> None:
        closed = self._clip(mouth_gap=0.5)
        open_wide = self._clip(mouth_gap=9.0)

        self.assertLess(open_wide.part.volume, closed.part.volume)

    def test_the_mouth_does_not_slot_the_flange(self) -> None:
        """A verification caught this by sectioning the flange: a cutter centred
        on the ring and three times its height reached below the flange top and
        cut 108 mm2 clean through the mounting plate, open to the short edge,
        while every scalar check still passed.
        """
        import math

        built = self._clip(flange=(40.0, 22.0, 5.0))
        flange_solid = 40.0 * 22.0 * 5.0
        screw_hole = math.pi * (4.5 / 2) ** 2 * 5.0

        # The part is the flange plus a ring, so its volume must exceed what the
        # flange alone contributes. A slotted flange falls below this.
        self.assertGreater(built.part.volume, flange_solid - screw_hole,
                           "the mouth cut into the flange")

    def test_a_snap_retaining_mouth_says_it_is_a_fit_interface(self) -> None:
        """A verification noticed the mouth is narrower than the bore, making the
        clip retain by elastic snap -- while the plan declared no interfaces, so
        nothing governed it with a band, a coupon or an acceptance method. The
        template knows both numbers and can say so."""
        snapping = self._clip(bore_d=12.0, mouth_gap=9.0)
        open_mouth = self._clip(bore_d=12.0, mouth_gap=13.0)

        self.assertTrue(any("elastic snap" in n for n in snapping.notes), snapping.notes)
        self.assertFalse(any("elastic snap" in n for n in open_mouth.notes), open_mouth.notes)

    def test_a_mouth_that_would_sever_the_part_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._clip(mouth_gap=30.0)

    def test_the_screw_hole_goes_where_the_caller_says(self) -> None:
        """A fixed position is what makes a template half-fit: a run reached for
        this one, found the hole in the wrong place, and hand-built its own --
        paying for the template and the authoring both."""
        from designer_toolkit import metrics

        here = self._clip(screw_at=(8.0, 11.0))
        there = self._clip(screw_at=(30.0, 11.0))

        self.assertNotAlmostEqual(here.part.volume, there.part.volume, places=6)
        for built in (here, there):
            self.assertAlmostEqual(0.0, metrics.overhang_area(built.part, threshold=-0.73),
                                   places=6, msg="a repositioned hole must stay self-supporting")

    def test_a_countersink_is_cut_and_stays_self_supporting(self) -> None:
        """A verification rejected a candidate for a countersink the sheet asked
        for and the template could not make. It opens upward, so its own wall
        faces up."""
        from designer_toolkit import metrics

        plain = self._clip(countersink_d=0.0)
        sunk = self._clip(countersink_d=9.0)

        self.assertLess(sunk.part.volume, plain.part.volume, "nothing was cut")
        for threshold in (-0.73, templates.deg_to_normal_z(45)):
            with self.subTest(threshold=threshold):
                self.assertAlmostEqual(
                    0.0, metrics.overhang_area(sunk.part, threshold=threshold), places=6)

    def test_overlapping_cuts_are_unioned_before_subtraction(self) -> None:
        """`concatenate` glues meshes into a non-manifold soup the boolean
        mishandles when they overlap: the countersink cone crossing its own
        shaft removed nothing, and read as 18 mm2 of phantom downward area."""
        sunk = self._clip(countersink_d=9.0)

        self.assertTrue(sunk.part.is_watertight)
        self.assertEqual(1, mesh_io.connected_component_count(sunk.part))

    def test_it_works_without_a_flange(self) -> None:
        built = self._clip(flange=None, screw_d=0.0)

        self.assertTrue(built.part.is_watertight)
        self.assertAlmostEqual(9.0, built.params["overall_mm"]["z"], places=4)


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
