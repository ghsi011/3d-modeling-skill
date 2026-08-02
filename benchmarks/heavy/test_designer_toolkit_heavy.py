#!/usr/bin/env python3
"""L0-heavy — the half of
`skills/3d-modeling/scripts/designer_toolkit/test_designer_toolkit.py`
that costs a child interpreter.

The repository-root `conftest.py` refuses a child interpreter inside the commit
gate, and these classes start one. Same tests, moved rather than weakened;
`benchmarks/heavy/README.md` records the profile that decided the seam and what
runs this tier. What stayed behind is what answers in the parent process.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from designer_toolkit import (  # noqa: E402
    exporter,
)

# The fixtures this half shares with the half that stayed behind,
# imported rather than copied: two spellings of one fixture is how
# two tiers stop testing the same thing.
from designer_toolkit.test_designer_toolkit import (  # noqa: E402
    _box,
)


class TestExport(unittest.TestCase):
    def test_box_mesh_export_report(self):
        with tempfile.TemporaryDirectory() as d:
            rep = exporter.export_and_hash(_box((10, 20, 30)), os.path.join(d, "b"))
            self.assertTrue(os.path.exists(rep.stl_path))
            self.assertTrue(rep.watertight)
            self.assertEqual(rep.components, 1)
            self.assertTrue(rep.is_single_watertight_solid())
            self.assertAlmostEqual(rep.volume_mm3, 10 * 20 * 30, delta=5)
            self.assertAlmostEqual(rep.bbox_mm["x"], 10, delta=0.1)
            self.assertAlmostEqual(rep.bbox_mm["z"], 30, delta=0.1)
            self.assertEqual(len(rep.file_sha256), 64)
            self.assertEqual(len(rep.geometry_sha256), 64)
            self.assertIsNone(rep.step_path)  # no STEP from a trimesh source

    def test_geometry_hash_stable_across_reimport(self):
        with tempfile.TemporaryDirectory() as d:
            stl = os.path.join(d, "a.stl")
            _box((8, 8, 8)).export(stl)
            r1 = exporter.export_and_hash(stl, os.path.join(d, "a"), also_step=False)
            r2 = exporter.export_and_hash(stl, os.path.join(d, "a"), also_step=False)
            self.assertEqual(r1.geometry_sha256, r2.geometry_sha256)

    def test_a_brep_part_export_writes_step(self):
        """The STEP branch of the exporter, on the kernel that is actually here.

        build123d is a core dependency now, so this no longer needs a skip: a
        test that only runs where an optional package happens to be installed is
        a test that does not run.
        """
        from build123d import Align, Box

        with tempfile.TemporaryDirectory() as d:
            model = Box(10, 10, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
            rep = exporter.export_and_hash(model, os.path.join(d, "c"))
            self.assertTrue(rep.watertight)
            self.assertIsNotNone(rep.step_path)
            self.assertTrue(os.path.exists(rep.step_path))
