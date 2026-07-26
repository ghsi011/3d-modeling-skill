"""Tests for the feature checks.

Both classes here are reproductions of defects that shipped: a countersink cut
out of the template while every caller still asked for one, and a mouth cutter
tall enough to slot the mounting flange through. Each passed the bounding box,
the watertight test, the component count and the overhang screen -- all four
bit-identical to the good part -- so every test below asserts against a variant
that the rest of the gate cannot tell apart from correct.
"""
from __future__ import annotations

import math
import unittest

try:
    import trimesh
except ImportError:  # pragma: no cover - exercised only on a bare interpreter
    trimesh = None

from . import features as F

_CLIP = dict(bore_d=12.0, wall=3.0, height=9.0, mouth_gap=9.0,
             flange=(40.0, 22.0, 5.0), screw_d=4.5, screw_at=(8.0, 11.0),
             countersink_d=9.0)
_PLATE = 40.0 * 22.0 - math.pi * 2.25 ** 2


def _needs_trimesh(test):
    return unittest.skipIf(trimesh is None, "needs trimesh + manifold3d")(test)


def _clip(**overrides):
    from .templates import c_clip
    return c_clip(**{**_CLIP, **overrides})


def _results(part, rows, **kwargs):
    return {c.id: c.result for c in F.check_features(part, rows, **kwargs)}


class TestTolerances(unittest.TestCase):
    def test_the_area_floor_is_far_below_the_defect_it_catches(self) -> None:
        """The slot removed 67 mm2. Tessellation noise on the same plane is
        0.04. A tolerance between those two is the whole design."""
        self.assertLess(F.area_tolerance(_PLATE), 10.0)
        self.assertGreater(F.area_tolerance(_PLATE), 0.04)


@_needs_trimesh
class TestSolidRegion(unittest.TestCase):
    def test_a_correct_flange_measures_its_own_arithmetic(self) -> None:
        part = _clip().part
        self.assertAlmostEqual(_PLATE, F.solid_area_mm2(part, 2.5), delta=0.1)

    def test_a_slotted_flange_fails(self) -> None:
        """The archived bug: a mouth cutter three times the ring height reached
        below the flange top and cut the mounting plate through, open to the
        short edge. Not a ring, so ring counts and bboxes are blind to it; the
        part stays one component, so connectivity is blind too. Only area sees
        it."""
        good = _clip().part
        slotted = trimesh.boolean.difference(
            [good, trimesh.creation.box(extents=(9.0, 30.0, 60.0))])

        row = {"kind": "solid_region", "id": "flange-mid", "z": 2.5, "area_mm2": _PLATE}
        self.assertEqual({"feature-flange-mid": "FAIL"}, _results(slotted, [row]))
        self.assertEqual({"feature-flange-mid": "PASS"}, _results(good, [row]))

    def test_an_empty_plane_reads_zero_and_fails_loudly(self) -> None:
        part = _clip().part
        row = {"kind": "solid_region", "id": "above", "z": 500.0, "area_mm2": _PLATE}
        self.assertEqual({"feature-above": "FAIL"}, _results(part, [row]))


@_needs_trimesh
class TestHoleProfile(unittest.TestCase):
    def test_the_countersink_profile_matches_the_closed_form(self) -> None:
        part = _clip().part
        self.assertAlmostEqual(8.59, F.bore_diameter_mm(part, 8, 11, 4.8, 6.0), delta=0.05)
        self.assertAlmostEqual(7.00, F.bore_diameter_mm(part, 8, 11, 4.0, 6.0), delta=0.05)
        self.assertAlmostEqual(4.50, F.bore_diameter_mm(part, 8, 11, 2.5, 6.0), delta=0.05)

    def test_a_countersink_deleted_from_the_geometry_fails(self) -> None:
        """The defect that shipped, and that a human then agreed with: the cone
        was removed from the template on the belief that countersinks are
        inherently overhangs, while every caller still passed `countersink_d`.
        Volume moved 0.9% -- under any usable envelope."""
        from . import templates as T

        good = _clip()
        original = T._frustum
        try:
            T._frustum = lambda *a, **k: trimesh.creation.box(extents=(1e-6, 1e-6, 1e-6))
            regressed = _clip()
        finally:
            T._frustum = original

        self.assertLess(abs(regressed.part.volume - good.part.volume) / good.part.volume, 0.01,
                        "the reproduction must be one a volume envelope cannot separate")
        self.assertEqual("PASS", _results(good.part, good.expected,
                                          bed_contact_mm2=_PLATE)["feature-screw"])
        self.assertEqual("FAIL", _results(regressed.part, regressed.expected,
                                          bed_contact_mm2=_PLATE)["feature-screw"])

    def test_a_window_hanging_off_the_part_refuses_to_report(self) -> None:
        """Void area is invariant to window size only while the window is buried
        in material. Without the two-radius cross-check, a window overhanging the
        edge reports a confident diameter computed mostly from fresh air."""
        part = _clip().part          # the clip occupies x in [0, 40], y in [0, 22]
        with self.assertRaises(F.Indeterminate):
            F.bore_diameter_mm(part, 38.0, 11.0, 2.5, 6.0)


@_needs_trimesh
class TestSliceProfile(unittest.TestCase):
    """The one measurement here that nobody has to anticipate."""

    def test_it_walks_the_whole_part(self) -> None:
        profile = F.slice_profile(_clip().part, slices=28)
        self.assertEqual(28, len(profile))
        self.assertTrue(all(row["area_mm2"] > 0 for row in profile))

    def test_both_shipped_defects_move_it_with_nothing_declared(self) -> None:
        """Neither defect had to be predicted. That is the whole point: every
        other check in this module reports only on features somebody named."""
        from . import templates as T

        good = _clip().part
        original = T._frustum
        try:
            T._frustum = lambda *a, **k: trimesh.creation.box(extents=(1e-6, 1e-6, 1e-6))
            no_countersink = _clip().part
        finally:
            T._frustum = original
        slotted = trimesh.boolean.difference(
            [good, trimesh.creation.box(extents=(9.0, 30.0, 60.0))])

        baseline = [row["area_mm2"] for row in F.slice_profile(good)]
        for name, part, least in (("countersink deleted", no_countersink, 20.0),
                                  ("flange slotted", slotted, 40.0)):
            with self.subTest(defect=name):
                curve = [row["area_mm2"] for row in F.slice_profile(part)]
                worst = max(abs(a - b) for a, b in zip(curve, baseline))
                self.assertGreater(worst, least,
                                   f"{name} barely moved the curve: {worst:.2f} mm2")

    def test_a_degenerate_part_returns_nothing_rather_than_dividing_by_zero(self) -> None:
        flat = trimesh.Trimesh(vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0]], faces=[[0, 1, 2]])
        self.assertEqual([], F.slice_profile(flat))


@_needs_trimesh
class TestDeclarationHandling(unittest.TestCase):
    def test_an_unmeasurable_kind_fails_rather_than_skips(self) -> None:
        part = _clip().part
        rows = [{"kind": "thread", "id": "m4"}]
        self.assertEqual({"feature-m4": "FAIL"}, _results(part, rows))

    def test_a_malformed_row_fails_rather_than_crashing_the_gate(self) -> None:
        part = _clip().part
        self.assertEqual({"feature-x": "FAIL"},
                         _results(part, [{"kind": "solid_region", "id": "x"}]))

    def test_no_rows_is_no_checks(self) -> None:
        self.assertEqual([], F.check_features(None, []))


@_needs_trimesh
class TestTemplateExpectations(unittest.TestCase):
    def test_the_clip_declares_what_it_built(self) -> None:
        kinds = {row["kind"] for row in _clip().expected}
        self.assertEqual({"solid_region", "bed_footprint", "countersink"}, kinds)

    def test_a_feature_nobody_asked_for_is_not_covered(self) -> None:
        """Stated as a test because it is the honest limit: one parameter drives
        both the geometry and its expectation, so dropping it removes the check
        along with the feature. Only a plan-side declaration, written from the
        sheet upstream of the model, catches that."""
        built = _clip(countersink_d=4.5)
        self.assertNotIn("countersink", {row["kind"] for row in built.expected})


if __name__ == "__main__":
    unittest.main()


@_needs_trimesh
class TestDefectsFoundByAdversarialReview(unittest.TestCase):
    """Each of these shipped a defective part at exit 0 with `verdict: PASS`,
    and each was reproduced before it was fixed."""

    def test_a_missing_mounting_hole_cannot_hide_in_the_plate_area(self) -> None:
        """The area tolerance was half a percent of the whole plate -- 299 mm2 on
        a 300 x 200 panel -- and four M5 holes come to 78. All four could be
        deleted and the panel still passed."""
        from .templates import panel

        holes = tuple({"kind": "round", "x": x, "y": y, "d": 5.0}
                      for x, y in ((20.0, 20.0), (280.0, 20.0), (20.0, 180.0), (280.0, 180.0)))
        asked = panel(width=300.0, depth=200.0, thickness=3.0, openings=holes)
        without = panel(width=300.0, depth=200.0, thickness=3.0, openings=())

        results = _results(without.part, asked.expected,
                           bed_contact_mm2=asked.expected[1]["area_mm2"])

        self.assertEqual("FAIL", results["feature-plate-mid"])
        for index in range(1, 5):
            self.assertEqual("FAIL", results[f"feature-hole-{index:02d}"],
                             "every declared hole must be measured on its own")

    def test_an_oversize_hole_is_caught_at_the_hole_not_the_plate(self) -> None:
        """A round opening survived to 23% oversize inside the plate tolerance."""
        from .templates import panel

        asked = panel(width=300.0, depth=200.0, thickness=3.0,
                      openings=({"kind": "round", "x": 150.0, "y": 100.0, "d": 8.0},))
        wider = panel(width=300.0, depth=200.0, thickness=3.0,
                      openings=({"kind": "round", "x": 150.0, "y": 100.0, "d": 9.0},))

        results = _results(wider.part, asked.expected,
                           bed_contact_mm2=asked.expected[1]["area_mm2"])

        self.assertEqual("FAIL", results["feature-hole-01"])

    def test_a_hole_in_the_wrong_place_is_caught(self) -> None:
        """The pipeline's canonical blind spot, in literal form. Every other
        check samples *at the declared position*, so a hole the designer put in
        the wrong place and then declared in the wrong place confirms itself --
        right diameter, right roundness, right section area, and the bolt still
        misses.

        The numbers are the real ones. A run building to the Gridfinity standard
        shipped its magnet pockets at 12.75 mm from each unit centre where the
        reference gives 13.0 two independent ways, because the 8 mm inset was
        taken off the 41.5 mm footprint instead of the 42 mm grid cell. Eight
        green checks agreed with it, and a fresh verifier caught it by hand."""
        plate = trimesh.creation.box(extents=(60.0, 60.0, 4.0))
        plate.apply_translation([0, 0, 2])
        row = {"kind": "through_hole", "id": "H", "at": (0.0, 0.0), "d_mm": 6.5,
               "z_from": 0.0, "z_to": 4.0}

        for offset, expected in ((0.0, "PASS"), (0.10, "PASS"), (0.25, "FAIL")):
            with self.subTest(offset=offset):
                bore = trimesh.creation.cylinder(radius=3.25, height=20.0, sections=128)
                bore.apply_translation([offset, 0, 2])
                part = trimesh.boolean.difference([plate, bore])

                check = F.check_features(part, [row])[0]

                self.assertEqual(expected, check.result, check.detail)
                if expected == "FAIL":
                    self.assertIn("from where it was declared", check.detail)

    def test_a_dropped_feature_says_so_or_refuses(self) -> None:
        """Three parameters were accepted and then ignored. A check that quietly
        does not exist is not listed in `coverage.skipped` either, so without a
        word here nothing at all tells a reader the feature went unmeasured."""
        from .templates import c_clip

        base = dict(bore_d=12.0, wall=3.0, height=9.0, mouth_gap=9.0)
        with self.assertRaises(ValueError):
            c_clip(screw_d=4.5, countersink_d=9.0, **base)

        plain = c_clip(flange=(40.0, 22.0, 5.0), screw_d=4.5, screw_at=(8.0, 11.0),
                       countersink_d=4.5, **base)
        self.assertNotIn("countersink", {row["kind"] for row in plain.expected})
        self.assertTrue(any("no countersink was cut" in note for note in plain.notes))

        wide = c_clip(bore_d=12.0, wall=3.0, height=9.0, mouth_gap=14.0)
        self.assertNotIn("channel-mid", {row.get("id") for row in wide.expected})
        self.assertTrue(any("not measured" in note for note in wide.notes))

    def test_a_case_cavity_cut_undersize_fails(self) -> None:
        """`device_case` declared nothing at all, so a cavity 0.75 mm per side
        undersize -- the phone physically will not go in -- left the bounding
        box, watertightness, body count, bed contact and overhang identical."""
        from .templates import _rounded_slab, _seated, device_case

        device, wall, clearance, radius = (73.6, 155.6, 8.5), 1.5, 0.25, 9.0
        good = device_case(device=device, wall=wall, clearance=clearance,
                           corner_radius=radius)
        dw, dl, dt = device
        outer_t = dt + 2 * clearance + wall
        outer = _rounded_slab(dw + 2 * (clearance + wall), dl + 2 * (clearance + wall),
                              outer_t, radius + clearance + wall, centre=(0, 0, outer_t / 2))
        tight = _rounded_slab(dw + 2 * clearance - 1.5, dl + 2 * clearance - 1.5, outer_t,
                              radius + clearance, centre=(0, 0, wall + outer_t / 2))
        undersize = _seated(trimesh.boolean.difference([outer, tight]))

        self.assertEqual([round(float(v), 3) for v in good.part.extents],
                         [round(float(v), 3) for v in undersize.extents],
                         "the reproduction must be one a bounding box cannot separate")
        footprint = next(r for r in good.expected if r["kind"] == "bed_footprint")
        results = _results(undersize, good.expected,
                           bed_contact_mm2=footprint["area_mm2"])

        self.assertEqual("FAIL", results["feature-wall-ring"])


@_needs_trimesh
class VoidRegionTest(unittest.TestCase):
    """A rib standing in a cavity nobody declared as a cavity.

    Reproduced from the segmented hive body, whose tongue slab ran the full
    height of the wall and straight across the brood chamber. In-memory
    watertight, one body, exact bounding box, correct bed contact, no overhang
    above the rule -- and no frame could have been hung in it. Every kind that
    existed asserted material was *present* somewhere; the defect was material
    present where the part was supposed to be air.
    """

    def _box(self, *, rib: bool):
        outer = trimesh.creation.box(extents=(60.0, 40.0, 30.0))
        outer.apply_translation([30.0, 20.0, 15.0])
        cavity = trimesh.creation.box(extents=(54.0, 34.0, 28.0))
        cavity.apply_translation([30.0, 20.0, 16.0])
        part = trimesh.boolean.difference([outer, cavity])
        if not rib:
            return part
        slab = trimesh.creation.box(extents=(54.0, 4.0, 27.0))
        slab.apply_translation([30.0, 20.0, 15.5])
        return trimesh.boolean.union([part, slab])

    _CAVITY = {"kind": "void_region", "id": "chamber", "z": 15.0,
               "at": (30.0, 20.0), "size_mm": (54.0, 34.0)}

    def test_clear_cavity_passes_and_a_rib_in_it_fails(self) -> None:
        clean, ribbed = self._box(rib=False), self._box(rib=True)
        self.assertEqual([round(float(v), 3) for v in clean.extents],
                         [round(float(v), 3) for v in ribbed.extents],
                         "the reproduction must be one a bounding box cannot separate")
        self.assertTrue(ribbed.is_watertight)
        self.assertEqual(1, ribbed.body_count)

        self.assertEqual("PASS", _results(clean, [self._CAVITY])["feature-chamber"])
        self.assertEqual("FAIL", _results(ribbed, [self._CAVITY])["feature-chamber"])

    def test_a_plane_area_that_admits_the_rib_still_fails_the_void(self) -> None:
        """Why the kind had to exist rather than a tighter `solid_region`.

        A plane's total area is one scalar for the whole section, so anything
        that costs 216 mm2 elsewhere on it -- thinner walls, a pocket, one more
        chamfer -- buys the rib a place to hide. Here the expectation is simply
        sized to admit it, and the scalar agrees with a part whose chamber is
        blocked end to end. The void row reads the chamber and nothing else, so
        no error outside it can pay for one inside.
        """
        ring = 60.0 * 40.0 - 54.0 * 34.0
        rib = 54.0 * 4.0
        blocked = self._box(rib=True)
        admits = {"kind": "solid_region", "id": "ring", "z": 15.0, "area_mm2": ring + rib}
        self.assertEqual("PASS", _results(blocked, [admits])["feature-ring"])
        self.assertEqual("FAIL", _results(blocked, [self._CAVITY])["feature-chamber"])

    def test_a_window_off_the_part_is_refused_not_passed(self) -> None:
        clean = self._box(rib=False)
        for row in ({**self._CAVITY, "z": 90.0},
                    {**self._CAVITY, "at": (200.0, 20.0)},
                    {**self._CAVITY, "size_mm": (400.0, 34.0)}):
            with self.subTest(row=row):
                self.assertEqual("FAIL", _results(clean, [row])["feature-chamber"],
                                 "an empty window outside the material is not a cavity")
