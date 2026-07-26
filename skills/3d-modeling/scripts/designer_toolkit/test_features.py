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
