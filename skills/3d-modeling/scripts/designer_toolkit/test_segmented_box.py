"""Tests for `segmented_box`, against a real published standard.

The dimensions here are not invented. A 10-frame Langstroth hive body is
374.7 x 466.7 mm inside and 406.4 x 504.8 mm outside because every frame and
every other beekeeper's box says so, and no common printer bed is over 256 mm.
That combination is the whole reason this template exists, and it is also what
caught two defects in the first draft: cells sized to fill the bed exactly
produced pieces that overhung it once the joint was added, and a scalar wall
could not reproduce a standard whose two axes imply 15.85 and 19.05 mm.
"""
from __future__ import annotations

import unittest
from pathlib import Path

try:
    import trimesh
except ImportError:  # pragma: no cover
    trimesh = None

from . import templates as T

# The standard, in millimetres.
LANGSTROTH_INNER = (374.7, 466.7, 244.5)
LANGSTROTH_WALL = ((406.4 - 374.7) / 2.0, (504.8 - 466.7) / 2.0)
BED = 256.0


@unittest.skipIf(trimesh is None, "needs trimesh + manifold3d")
class TestSegmentedBox(unittest.TestCase):
    def _hive(self, **overrides):
        kwargs = dict(inner=LANGSTROTH_INNER, wall=LANGSTROTH_WALL, bed=BED)
        kwargs.update(overrides)
        return T.segmented_box(**kwargs)

    def test_it_reproduces_the_standard_it_was_given(self) -> None:
        """Both the arithmetic and the solid. They came apart once: tongues were
        allowed to push past the outer wall, so the assembled hive measured
        417 x 515 where the standard says 406.4 x 504.8 -- and every commercial
        box it has to stack with disagrees by 10 mm."""
        built = self._hive()
        for key, standard in (("x", 406.4), ("y", 504.8), ("z", 244.5)):
            with self.subTest(axis=key):
                self.assertAlmostEqual(standard, built.params["assembled_mm"][key], places=3)
                self.assertAlmostEqual(standard, built.params["overall_mm"][key], places=3,
                                       msg="the exported solid must be the box it claims")

    def test_every_segment_fits_the_bed(self) -> None:
        """The one promise. A first draft sized cells to fill the bed exactly and
        then grew each piece by the joint, handing back 259.8 mm segments for a
        256 mm bed -- discovered at the slicer, which is too late."""
        built = self._hive()
        for index, piece in enumerate(built.part.split(only_watertight=False)):
            with self.subTest(segment=index):
                reach = piece.bounds[1] - piece.bounds[0]
                self.assertLessEqual(float(reach[0]), BED)
                self.assertLessEqual(float(reach[1]), BED)

    def test_the_cavity_is_actually_hollow(self) -> None:
        """The defect that made this template useless for its own documented
        example. Each seam tongue was a slab spanning the cell, so every internal
        seam left a solid rib straight across the brood cavity -- 6,575 mm2 of
        excess at mid-height, the middle of the cavity reporting as solid, and no
        frame able to go in. Every other check was green."""
        built = self._hive()

        inside = built.part.contains([[203.2, 250.0, 122.0], [100.0, 400.0, 60.0]])

        self.assertFalse(any(inside),
                         "a point inside the brood cavity must not be solid")

    def test_the_cavity_plane_is_declared_and_catches_a_rib(self) -> None:
        """The first draft declared nothing at this plane, on the argument that a
        jointed section has no exact closed form. It has one to within the joint
        clearance, and while nothing measured it the rib above went unnoticed.

        Two rows now stand there and they fail differently: the ring is the whole
        section against a budget that scales with the seam count, the void is the
        chamber alone against nothing. A rib big enough to matter trips both; one
        small enough to fit the joint budget trips only the second.
        """
        built = self._hive()
        ring = next(r for r in built.expected if r["id"] == "wall-ring")
        self.assertAlmostEqual(406.4 * 504.8 - 374.7 * 466.7, ring["area_mm2"], places=3)

        from . import features as F

        def results(mesh):
            return {c.id: c.result for c in F.check_features(mesh, built.expected)}

        self.assertEqual({"feature-wall-ring": "PASS", "feature-cavity": "PASS"},
                         results(built.part))

        ribbed = trimesh.boolean.union([
            built.part,
            trimesh.creation.box(extents=(5.3, 466.7, 244.5)).apply_translation(
                [203.2, 252.4, 122.25])])
        self.assertEqual({"feature-wall-ring": "FAIL", "feature-cavity": "FAIL"},
                         results(ribbed))

    def test_every_segment_is_a_watertight_solid(self) -> None:
        for index, piece in enumerate(self._hive().part.split(only_watertight=False)):
            with self.subTest(segment=index):
                self.assertTrue(piece.is_watertight)

    def test_it_survives_the_stl_round_trip_as_separate_solids(self) -> None:
        """In-memory watertightness is not the test. Neighbours that touch
        exactly weld on reimport -- coincident faces merge -- and six watertight
        pieces came back as one non-manifold body, which the gate rejected and
        no in-memory assertion saw. They stand a bond line apart now, which is
        also what a glued joint physically needs."""
        import tempfile

        built = self._hive()
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "hive.stl"
            built.part.export(path)
            reloaded = trimesh.load(path, process=True)

        self.assertTrue(reloaded.is_watertight)
        self.assertEqual(built.params["segment_count"], reloaded.body_count)

    def test_it_refuses_rather_than_returning_an_unprintable_piece(self) -> None:
        """A tongue wide enough to swallow the bed has no valid decomposition,
        and saying so beats handing back something that cannot be printed."""
        with self.assertRaises(ValueError):
            self._hive(bed=40.0, tongue=18.0)

    def test_a_box_that_already_fits_is_sent_back_to_box_shell(self) -> None:
        with self.assertRaises(ValueError) as caught:
            T.segmented_box(inner=(100.0, 80.0, 60.0), wall=3.0, bed=256.0)
        self.assertIn("box_shell", str(caught.exception))

    def test_a_scalar_wall_still_works(self) -> None:
        """Per-axis walls exist for standards that need them; the ordinary case
        must not have to know that."""
        built = T.segmented_box(inner=(400.0, 400.0, 100.0), wall=5.0, bed=256.0)
        self.assertAlmostEqual(410.0, built.params["assembled_mm"]["x"], places=3)
        self.assertAlmostEqual(410.0, built.params["assembled_mm"]["y"], places=3)

    def test_the_tongue_must_be_thinner_than_the_wall_it_sits_in(self) -> None:
        with self.assertRaises(ValueError):
            self._hive(tongue=25.0)

    def test_the_seams_are_declared_as_an_open_question(self) -> None:
        """A joint is a light and weather path in a beehive, and nothing here
        measures whether it was sealed. Saying so in the notes is the only
        honest option."""
        notes = " ".join(self._hive().notes).lower()
        self.assertIn("seam", notes)
        self.assertIn("nothing here checks", notes)


@unittest.skipIf(trimesh is None, "needs trimesh + manifold3d")
class TestStackedExpectations(unittest.TestCase):
    """Laying parts out for a plate used to discard every check they declared,
    so the multi-part job -- the one with the most to get wrong -- reached the
    gate with the least to gate."""

    def _legs(self, bores=(12.0, 12.0, 12.0, 12.0)):
        return T.stack(*[T.bolt_boss(outer_d=40.0, bore_d=b, height=60.0) for b in bores],
                       gap=8.0)

    def test_holes_carry_over_and_move_with_their_part(self) -> None:
        plate = self._legs()
        bores = [row for row in plate.expected if row["kind"] == "through_hole"]
        self.assertEqual(4, len(bores))
        xs = [row["at"][0] for row in bores]
        self.assertEqual(xs, sorted(xs), "each hole must sit where its part was laid")
        self.assertEqual(4, len({row["id"] for row in bores}), "ids must stay distinct")

    def test_bed_contact_is_summed(self) -> None:
        import math
        ring = math.pi * (20.0 ** 2 - 6.0 ** 2)
        footprint = next(r for r in self._legs().expected if r["kind"] == "bed_footprint")
        self.assertAlmostEqual(4 * ring, footprint["area_mm2"], places=3)

    def test_one_bad_part_among_four_is_named(self) -> None:
        from . import features as F

        good, bad = self._legs(), self._legs(bores=(12.0, 12.0, 15.0, 12.0))
        self.assertEqual(list(good.part.extents), list(bad.part.extents),
                         "the reproduction must be one a bounding box cannot separate")

        failed = [c.id for c in F.check_features(bad.part, good.expected) if c.result == "FAIL"]

        self.assertIn("feature-bore-2", failed, "the failing part must be identified")
        self.assertNotIn("feature-bore-0", failed)
        self.assertNotIn("feature-bore-1", failed)
        self.assertNotIn("feature-bore-3", failed)

    def test_a_section_is_dropped_unless_every_part_declares_one_there(self) -> None:
        """A plane through the plate cuts everything on it, so summing only the
        parts that happened to declare a region at that height measures a number
        nothing has."""
        mixed = T.stack(T.bolt_boss(outer_d=40.0, bore_d=12.0, height=60.0),
                        T.box_shell(inner=(40.0, 40.0, 40.0), wall=3.0), gap=8.0)
        regions = [row for row in mixed.expected if row["kind"] == "solid_region"]
        self.assertEqual([], regions,
                         "the two parts declare regions at different heights")


@unittest.skipIf(trimesh is None, "needs trimesh + manifold3d")
class TestDegenerateParameters(unittest.TestCase):
    """Each of these was reproduced returning a wrong answer rather than an
    error. A template that builds a silently different part is worse than one
    that refuses, because nothing downstream knows to look."""

    CASES = (
        ("an opening larger than the panel",
         lambda: T.panel(width=100.0, depth=60.0, thickness=3.0,
                         openings=({"kind": "rect", "x": 50.0, "y": 30.0,
                                    "w": 200.0, "h": 200.0},))),
        ("a negative diameter, which cut its absolute size and agreed with itself",
         lambda: T.panel(width=100.0, depth=60.0, thickness=3.0,
                         openings=({"kind": "round", "x": 50.0, "y": 30.0, "d": -5.0},))),
        ("an opening hanging off the edge, reported as a negative wall",
         lambda: T.panel(width=100.0, depth=60.0, thickness=3.0,
                         openings=({"kind": "rect", "x": 95.0, "y": 30.0,
                                    "w": 40.0, "h": 10.0},))),
        ("a zero-width opening",
         lambda: T.panel(width=100.0, depth=60.0, thickness=3.0,
                         openings=({"kind": "rect", "x": 50.0, "y": 30.0,
                                    "w": 0.0, "h": 10.0},))),
        ("a negative corner radius",
         lambda: T.device_case(device=(70.0, 150.0, 8.0), wall=2.0, clearance=0.25,
                               corner_radius=-50.0)),
        ("a negative floor, which shrank the box and reported the shrunken height",
         lambda: T.segmented_box(inner=(374.7, 466.7, 100.0), wall=5.0, bed=256.0,
                                 floor=-10.0)),
        ("a negative inner size, which 'fitted the bed' by a sign accident",
         lambda: T.segmented_box(inner=(-300.0, -300.0, 100.0), wall=5.0, bed=200.0)),
        ("a negative tongue, silently replaced by the default",
         lambda: T.segmented_box(inner=(374.7, 466.7, 100.0), wall=5.0, bed=256.0,
                                 tongue=-3.0)),
    )

    def test_each_is_refused_with_a_message_naming_the_mistake(self) -> None:
        for label, build in self.CASES:
            with self.subTest(case=label):
                with self.assertRaises(ValueError):
                    build()

if __name__ == "__main__":
    unittest.main()

    def test_a_void_carries_over_where_a_section_cannot(self) -> None:
        """The same plate the section rule has to give up on.

        Two boxes of different heights declare their wall rings at different
        planes, so no section survives the layout and the plate is left with one
        bed-contact number for the whole thing. A void is local -- it reads its
        own rectangle and nothing else on the plate can reach it -- so it moves
        with its part exactly like a hole, and both cavities stay measured.
        """
        from . import features as F

        plate = T.stack(T.box_shell(inner=(40.0, 30.0, 20.0), wall=2.0, floor=2.0),
                        T.box_shell(inner=(30.0, 30.0, 15.0), wall=2.0, floor=2.0), gap=5.0)
        self.assertEqual([], [r for r in plate.expected if r["kind"] == "solid_region"])

        voids = [r for r in plate.expected if r["kind"] == "void_region"]
        self.assertEqual(["cavity-0", "cavity-1"], sorted(r["id"] for r in voids))
        xs = [r["at"][0] for r in voids]
        self.assertEqual(xs, sorted(xs), "each cavity must sit where its part was laid")

        footprint = next(r for r in plate.expected if r["kind"] == "bed_footprint")
        results = {c.id: c.result for c in F.check_features(
            plate.part, plate.expected, bed_contact_mm2=footprint["area_mm2"])}
        self.assertEqual({"feature-cavity-0": "PASS", "feature-cavity-1": "PASS",
                          "feature-bed_footprint": "PASS"}, results)

        blocked = trimesh.boolean.union([
            plate.part,
            trimesh.creation.box(extents=(3.0, 30.0, 20.0)).apply_translation(
                [66.0, 17.0, 10.0])])
        self.assertEqual(
            "FAIL",
            {c.id: c.result for c in F.check_features(blocked, plate.expected)}
            ["feature-cavity-1"],
            "an obstruction in the second box must name the second box")
