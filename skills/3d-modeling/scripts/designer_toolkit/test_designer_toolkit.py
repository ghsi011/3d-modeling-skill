"""Tests for designer_toolkit. Mesh-based so they run in lean CI (trimesh +
numpy + manifold3d only); the CadQuery export path is gated with skipUnless, and
the pyrender-backed render module is not exercised here (needs a GL context).
"""

import importlib.util
import os
import sys
import tempfile
import unittest

import numpy as np
import trimesh

# scripts/ on path so `import designer_toolkit` resolves when run directly.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from designer_toolkit import (  # noqa: E402
    bundle,
    coupon,
    exporter,
    fit,
    metrics,
)

_HAS_CADQUERY = importlib.util.find_spec("cadquery") is not None


def _box(size=(10, 10, 10), at=(0, 0, 0)):
    m = trimesh.creation.box(size)
    m.apply_translation(at)
    return m


def _plate_with_hole(hole_center=(3, -2), hole_d=5.0):
    plate = _box((20, 20, 4), (0, 0, 2))
    cutter = trimesh.creation.cylinder(radius=hole_d / 2, height=20)
    cutter.apply_translation((hole_center[0], hole_center[1], 2))
    return trimesh.boolean.difference([plate, cutter])


def _downward_quad(z=1.0, side=10.0):
    v = np.array([[0, 0, z], [side, 0, z], [side, side, z], [0, side, z]], dtype=float)
    m = trimesh.Trimesh(vertices=v, faces=[[0, 1, 2], [0, 2, 3]], process=False)
    if m.face_normals[0, 2] > 0:  # force the normal to point down
        m = trimesh.Trimesh(vertices=v, faces=[[0, 2, 1], [0, 3, 2]], process=False)
    return m


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

    @unittest.skipUnless(_HAS_CADQUERY, "cadquery not installed")
    def test_cadquery_solid_export_writes_step(self):
        import cadquery as cq

        with tempfile.TemporaryDirectory() as d:
            model = cq.Workplane("XY").box(10, 10, 10, centered=(True, True, False))
            rep = exporter.export_and_hash(model, os.path.join(d, "c"))
            self.assertTrue(rep.watertight)
            self.assertIsNotNone(rep.step_path)
            self.assertTrue(os.path.exists(rep.step_path))


class TestMeasure(unittest.TestCase):
    def test_measure_box(self):
        r = metrics.measure(_box((10, 20, 30)))
        self.assertTrue(r.watertight)
        self.assertEqual(r.components, 1)
        self.assertAlmostEqual(r.bbox_mm["y"], 20, delta=0.1)

    def test_datum_features_finds_offset_hole(self):
        feats = metrics.datum_features(_plate_with_hole((3, -2), 5.0), (0, 0, 2))
        outlines = [f for f in feats if f.kind == "outline"]
        holes = [f for f in feats if f.kind == "hole"]
        self.assertEqual(len(outlines), 1)
        self.assertEqual(len(holes), 1)
        # hole bbox ~ diameter
        self.assertAlmostEqual(holes[0].size_mm[0], 5.0, delta=0.4)
        self.assertAlmostEqual(holes[0].size_mm[1], 5.0, delta=0.4)
        # centre aligns with the model offset up to frame sign/swap: {|u|,|v|}={3,2}
        got = sorted(round(abs(c), 1) for c in holes[0].center_mm)
        self.assertEqual(got, [2.0, 3.0])

    def test_overhang_counts_downward_face_above_bed(self):
        self.assertAlmostEqual(metrics.overhang_area(_downward_quad(z=1.0)), 100.0, delta=1.0)

    def test_overhang_excludes_faces_below_min_z(self):
        self.assertAlmostEqual(metrics.overhang_area(_downward_quad(z=0.1)), 0.0, delta=1e-6)

    def test_overhang_excludes_shallow_slopes(self):
        # A plain box: bottom face is downward but at the bed (excluded by min_z),
        # all other faces are not past the -0.73 screen -> zero overhang.
        self.assertAlmostEqual(metrics.overhang_area(_box((10, 10, 10), (0, 0, 5))),
                               0.0, delta=1e-6)


class TestFit(unittest.TestCase):
    def test_interference_overlap_and_disjoint(self):
        a = _box((10, 10, 10))
        b = _box((10, 10, 10), (5, 0, 0))       # overlap 5x10x10 = 500
        self.assertAlmostEqual(fit.interference(a, b), 500.0, delta=5)
        far = _box((10, 10, 10), (100, 0, 0))
        self.assertEqual(fit.interference(a, far), 0.0)

    def test_insertion_sweep_clearance_vs_block(self):
        plate = _plate_with_hole((0, 0), 5.0)              # Ø5 bore
        peg_ok = trimesh.creation.cylinder(radius=2.0, height=20)   # Ø4 fits
        peg_ok.apply_translation((0, 0, 10))
        steps_ok = fit.insertion_sweep(plate, peg_ok, [0, 4, 8, 12], axis=(0, 0, -1))
        self.assertTrue(all(not s.blocked for s in steps_ok))
        peg_big = trimesh.creation.cylinder(radius=3.0, height=20)  # Ø6 jams
        peg_big.apply_translation((0, 0, 10))
        steps_big = fit.insertion_sweep(plate, peg_big, [0, 4, 8, 12], axis=(0, 0, -1))
        self.assertTrue(any(s.blocked for s in steps_big))


class TestCoupon(unittest.TestCase):
    def test_coupon_builds_and_legend_matches(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "coupon.stl")
            ifaces = [{"id": "bore", "nominal_mm": 5.0, "kind": "hole"},
                      {"id": "post", "nominal_mm": 4.0, "kind": "peg"}]
            path, legend = coupon.fit_coupon(ifaces, out,
                                             offsets_mm=(-0.1, 0.0, 0.1))
            self.assertTrue(os.path.exists(path))
            self.assertEqual(len(legend), 2 * 3)
            rows = coupon.legend_to_rows(legend)
            self.assertEqual({r["interface_id"] for r in rows}, {"bore", "post"})
            self.assertTrue(trimesh.load(path).is_watertight
                            or len(trimesh.load(path).faces) > 0)

    def test_coupon_requires_an_interface(self):
        with self.assertRaises(ValueError):
            coupon.fit_coupon([], "x.stl")


class TestFinalize(unittest.TestCase):
    def test_finalize_clean_solid(self):
        with tempfile.TemporaryDirectory() as d:
            stl = os.path.join(d, "body.stl")
            _box((10, 10, 10), (0, 0, 5)).export(stl)
            ev = bundle.finalize(
                stl, os.path.join(d, "body"),
                datums=[{"name": "mid", "plane_origin": (0, 0, 5)}],
                also_step=False)
            self.assertTrue(ev["readiness_skeleton"]["single_watertight_solid"])
            self.assertAlmostEqual(ev["overhang_mm2"], 0.0, delta=1e-6)
            self.assertEqual(len(ev["datums"]), 1)
            self.assertIsNone(ev["readiness_skeleton"]["visual_accept"])
            self.assertEqual(ev["readiness_skeleton"]["auto_notes"], [])

    def test_finalize_flags_seated_interference(self):
        with tempfile.TemporaryDirectory() as d:
            stl = os.path.join(d, "body.stl")
            _box((10, 10, 10)).export(stl)
            ref = _box((10, 10, 10), (5, 0, 0))
            ev = bundle.finalize(stl, os.path.join(d, "body"), reference=ref,
                                   also_step=False)
            self.assertGreater(ev["seated_interference_mm3"], 1.0)
            self.assertTrue(any("interference" in n
                                for n in ev["readiness_skeleton"]["auto_notes"]))


if __name__ == "__main__":
    unittest.main()
