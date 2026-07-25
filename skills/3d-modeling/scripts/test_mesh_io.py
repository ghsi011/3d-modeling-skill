"""Tests for mesh_io's raw-vs-normalized reporting (P-14).

The point of the split is that a genuine defect in the exported file must be
visible on the RAW read before any repair runs -- normalization must never
convert a raw hard failure (or a raw integrity defect) into a silent pass.

Fixtures use OBJ, not STL, for the degenerate/duplicate-vertex cases: the STL
format has no shared-vertex indices at all (every triangle carries its own
three independent (x, y, z) triples), so a raw STL parse always reports
"every vertex duplicated" and "not watertight" regardless of whether the
underlying shape is actually clean -- that is a format artifact, documented
in mesh_io's module docstring, not something these tests should assert
around. OBJ preserves whatever vertex-sharing the fixture is built with, so
it isolates the specific defect each test is checking for. A plain STL round
trip is covered separately to confirm load_mesh/load_mesh_report still work
against the format the rest of the pipeline actually exports.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import trimesh

import mesh_io


def _box() -> trimesh.Trimesh:
    return trimesh.creation.box(extents=(2, 2, 2))


def _duplicate_vertex_mesh() -> trimesh.Trimesh:
    """A box where one face's three vertices are cloned into fresh indices
    instead of sharing the other faces' vertices -- three genuine extra
    duplicate-position vertices, and the mesh reads as two components on the
    raw (unwelded-there) parse because that one face is topologically
    disconnected from its neighbours until vertices are merged.
    """
    box = _box()
    verts = box.vertices.copy()
    faces = box.faces.copy()
    face0 = faces[0].copy()
    clone_index = len(verts) + np.arange(3)
    verts = np.vstack([verts, verts[face0]])
    faces[0] = clone_index
    return trimesh.Trimesh(vertices=verts, faces=faces, process=False)


def _degenerate_face_mesh() -> trimesh.Trimesh:
    """A box plus one extra zero-area triangle (all three corners the same
    vertex) appended after it -- a genuine per-triangle geometry defect,
    independent of vertex sharing/welding.
    """
    box = _box()
    verts = box.vertices.copy()
    faces = box.faces.copy()
    degenerate_face = np.array([[0, 0, 0]])
    faces = np.vstack([faces, degenerate_face])
    return trimesh.Trimesh(vertices=verts, faces=faces, process=False)


class MeshIoRawVsNormalizedTest(unittest.TestCase):
    def test_clean_mesh_raw_metrics_are_defect_free(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "clean.obj"
            _box().export(path)

            report = mesh_io.load_mesh_report(path)

            self.assertEqual(report.raw_integrity.vertex_count, 8)
            self.assertEqual(report.raw_integrity.face_count, 12)
            self.assertTrue(report.raw_integrity.watertight)
            self.assertEqual(report.raw_integrity.components, 1)
            self.assertEqual(report.raw_integrity.degenerate_face_count, 0)
            self.assertEqual(report.raw_integrity.duplicate_vertex_count, 0)
            # Normalization on an already-clean mesh changes nothing.
            self.assertEqual(report.mutation_log.vertices_before, 8)
            self.assertEqual(report.mutation_log.vertices_after, 8)
            self.assertEqual(report.mutation_log.faces_before, 12)
            self.assertEqual(report.mutation_log.faces_after, 12)
            self.assertEqual(report.mutation_log.degenerate_faces_removed, 0)
            self.assertEqual(report.mutation_log.vertices_merged, 0)
            self.assertTrue(report.normalized.is_watertight)

    def test_degenerate_face_mesh_reports_raw_defect_unrepaired(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "degenerate.obj"
            _degenerate_face_mesh().export(path)

            report = mesh_io.load_mesh_report(path)

            # The raw read must show the injected defect -- it must NOT have
            # been silently dropped before the caller can see it.
            self.assertEqual(report.raw_integrity.face_count, 13)
            self.assertEqual(report.raw_integrity.degenerate_face_count, 1)
            self.assertFalse(report.raw_integrity.watertight)
            # A raw hard-failure surface must never disappear because a
            # normalized copy happens to look fine.
            self.assertGreater(report.raw_integrity.degenerate_face_count, 0)

            # Normalization repairs it, and the mutation log says so honestly.
            self.assertEqual(report.mutation_log.faces_before, 13)
            self.assertEqual(report.mutation_log.faces_after, 12)
            self.assertEqual(report.mutation_log.degenerate_faces_removed, 1)
            self.assertTrue(report.normalized.is_watertight)

            # The repaired copy converges to the same clean geometry as a
            # mesh that never had the defect (regression pin for the hash).
            clean_path = Path(raw_dir) / "clean.obj"
            _box().export(clean_path)
            clean_report = mesh_io.load_mesh_report(clean_path)
            self.assertEqual(report.normalized_sha256, clean_report.normalized_sha256)

    def test_duplicate_vertex_mesh_reports_raw_defect_unrepaired(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "duplicate.obj"
            _duplicate_vertex_mesh().export(path)

            report = mesh_io.load_mesh_report(path)

            self.assertEqual(report.raw_integrity.vertex_count, 11)
            self.assertEqual(report.raw_integrity.duplicate_vertex_count, 3)
            self.assertFalse(report.raw_integrity.watertight)
            self.assertEqual(report.raw_integrity.components, 2)
            self.assertEqual(report.raw_integrity.degenerate_face_count, 0)

            self.assertEqual(report.mutation_log.vertices_before, 11)
            self.assertEqual(report.mutation_log.vertices_after, 8)
            self.assertEqual(report.mutation_log.vertices_merged, 3)
            self.assertTrue(report.normalized.is_watertight)

    def test_normalized_copy_never_hides_a_raw_hard_failure(self) -> None:
        """An empty/degenerate-only mesh is a raw hard failure: load_mesh_raw
        (and therefore load_mesh_report) must raise, never silently repair
        its way to a pass.
        """
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "empty.obj"
            path.write_text("# no geometry\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                mesh_io.load_mesh_raw(path)
            with self.assertRaises(ValueError):
                mesh_io.load_mesh_report(path)
            with self.assertRaises(ValueError):
                mesh_io.load_mesh(path)

    def test_stl_round_trip_still_works_and_normalized_matches_load_mesh(self) -> None:
        """Integration check against the format the rest of the pipeline
        actually exports. STL has no shared vertex indices, so the raw read
        legitimately shows every vertex "duplicated" and not watertight
        (documented format caveat) -- this test asserts that honestly rather
        than asserting a misleadingly clean raw STL result.
        """
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "box.stl"
            _box().export(path)

            report = mesh_io.load_mesh_report(path)
            direct = mesh_io.load_mesh(path)

            self.assertEqual(report.raw_integrity.vertex_count, 36)  # 3 per face x 12 faces
            self.assertEqual(report.raw_integrity.duplicate_vertex_count, 28)
            self.assertFalse(report.raw_integrity.watertight)

            # load_mesh (existing, backward-compatible entry point) and the
            # report's normalized copy converge on the same repaired mesh.
            self.assertEqual(direct.vertices.shape, report.normalized.vertices.shape)
            self.assertEqual(direct.faces.shape, report.normalized.faces.shape)
            self.assertTrue(report.normalized.is_watertight)
            self.assertEqual(report.mutation_log.vertices_after, 8)


if __name__ == "__main__":
    unittest.main()
