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
        assembled = self._hive().params["assembled_mm"]
        self.assertAlmostEqual(406.4, assembled["x"], places=6)
        self.assertAlmostEqual(504.8, assembled["y"], places=6)
        self.assertAlmostEqual(244.5, assembled["z"], places=6)

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

    def test_every_segment_is_a_watertight_solid(self) -> None:
        for index, piece in enumerate(self._hive().part.split(only_watertight=False)):
            with self.subTest(segment=index):
                self.assertTrue(piece.is_watertight)

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
        self.assertAlmostEqual(410.0, built.params["assembled_mm"]["x"], places=6)
        self.assertAlmostEqual(410.0, built.params["assembled_mm"]["y"], places=6)

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


if __name__ == "__main__":
    unittest.main()
