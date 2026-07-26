"""Tests for `dt.py probe`.

The charter tells a verifier to compare the sheet against built geometry, and
separately not to hand-roll anything. Those collided until this existed, and the
collision is not hypothetical: a Gridfinity bin shipped its magnet pockets
0.25 mm off on both axes, eight green checks agreed because each measured at the
position the designer declared, and the verifier that caught it had to write its
own sections to do so.
"""
from __future__ import annotations

import io
import json
import contextlib
import tempfile
import unittest
from pathlib import Path

try:
    import trimesh
except ImportError:  # pragma: no cover
    trimesh = None

from . import probe


def _part(root: Path, hole_at=(10.0, 0.0)) -> Path:
    plate = trimesh.creation.box(extents=(60.0, 60.0, 6.0))
    plate.apply_translation([0, 0, 3])
    bore = trimesh.creation.cylinder(radius=3.25, height=20.0, sections=96)
    bore.apply_translation([hole_at[0], hole_at[1], 3])
    path = root / "part.stl"
    trimesh.boolean.difference([plate, bore]).export(path)
    return path


def _run(*argv) -> dict:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = probe.main([str(a) for a in argv])
    assert code == 0, code
    return json.loads(buf.getvalue())


@unittest.skipIf(trimesh is None, "needs trimesh + manifold3d")
class TestMeasure(unittest.TestCase):
    def test_a_hole_measured_where_it_is_reads_no_offset(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            out = _run(_part(root), "--hole", "10,0", "--z", "3", "--nominal", "6.5")
            self.assertAlmostEqual(6.5, out["hole"]["diameter_mm"], delta=0.05)
            for component in out["hole"]["centre_offset_mm"]:
                self.assertAlmostEqual(0.0, component, delta=0.02)

    def test_a_hole_measured_where_it_should_be_reports_the_drift(self) -> None:
        """The whole point. The part has its hole at 10.0; the sheet says 10.25;
        asking at the sheet's position must say so, per axis."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            out = _run(_part(root, hole_at=(10.0, 0.0)),
                       "--hole", "10.25,0", "--z", "3", "--nominal", "6.5")
            self.assertAlmostEqual(-0.25, out["hole"]["centre_offset_mm"][0], delta=0.03)

    def test_sections_and_profile_are_available(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            out = _run(_part(root), "--section", "3", "--profile", "--slices", "8")
            self.assertAlmostEqual(60 * 60 - 3.14159 * 3.25 ** 2,
                                   out["sections"][0]["area_mm2"], delta=1.0)
            self.assertEqual(8, len(out["profile"]))

    def test_asking_nothing_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            self.assertEqual(2, probe.main([str(_part(Path(raw)))]))

    def test_a_hole_without_a_height_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            self.assertEqual(2, probe.main([str(_part(Path(raw))), "--hole", "10,0"]))

    def test_it_says_when_it_guessed_the_window(self) -> None:
        """A window sized from a guess can sit outside the material, and a
        confident number computed partly from fresh air is the failure mode this
        whole module exists to avoid."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            out = _run(_part(root), "--hole", "10,0", "--z", "3")
            self.assertTrue(out["hole"]["nominal_assumed"])


if __name__ == "__main__":
    unittest.main()
