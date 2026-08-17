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
import unittest.mock
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


class BrepTessellationDiagnosticTest(unittest.TestCase):
    def test_null_triangulation_names_the_affected_face(self) -> None:
        class Face:
            geom_type = "BSPLINE"

            def center(self):
                return "(1, 2, 3)"

            def tessellate(self, tolerance, angular_tolerance):
                _ = tolerance, angular_tolerance
                return None, None

        class Shape:
            def faces(self):
                return [Face()]

        with self.assertRaises(ValueError) as caught:
            mesh_io.validate_brep_tessellation(
                Shape(), tolerance=0.01, angular_tolerance=0.1
            )
        message = str(caught.exception)
        self.assertIn("B-rep tessellation failed", message)
        self.assertIn("face 0", message)
        self.assertIn("BSPLINE", message)
        self.assertIn("null triangulation", message)

    def test_a_shape_whose_faces_cannot_be_walked_is_not_reported_complete(self) -> None:
        """docs/defects.md D23: no failures read as success.

        `complete` was `not failures`, and a shape this function cannot walk
        produces no failures -- so the probe added to stop `diagnose` calling an
        untessellatable STEP clean returned clean for the one input it can learn
        least about. Recorded twice by accident: `build123d.Shape.cast` returns
        `None` for a `ShapeFix_Shape` result, and that `None` arrived here.
        """

        class NoFaces:
            """A shape object with no face enumeration at all."""

        for label, shape in (("None", None), ("no faces() method", NoFaces()),
                             ("faces is not callable", type("S", (), {"faces": 3})())):
            with self.subTest(shape=label):
                reading = mesh_io.tessellate_brep(shape, tolerance=0.01,
                                                  angular_tolerance=0.1)
                self.assertFalse(
                    reading.complete,
                    "a shape whose faces cannot be enumerated is unknown, not clean")
                self.assertFalse(reading.enumerated)
                self.assertIn("could not be enumerated", reading.summary())
                # And the gate in front of every B-rep export refuses it.
                with self.assertRaises(ValueError):
                    mesh_io.validate_brep_tessellation(shape, tolerance=0.01,
                                                       angular_tolerance=0.1)

    def test_a_shape_with_no_faces_at_all_is_not_reported_complete(self) -> None:
        """Zero faces tessellated out of zero is not a successful reading.

        The same arithmetic as above one step later: an empty enumeration
        produces an empty failure list, and `not failures` called it clean. A
        B-rep with no faces is not a solid, and exporting one exports nothing.
        """

        class Empty:
            def faces(self):
                return []

        reading = mesh_io.tessellate_brep(Empty(), tolerance=0.01,
                                          angular_tolerance=0.1)
        self.assertTrue(reading.enumerated)
        self.assertEqual(0, reading.faces)
        self.assertFalse(reading.complete)
        self.assertIn("no faces", reading.summary())
        with self.assertRaises(ValueError):
            mesh_io.validate_brep_tessellation(Empty(), tolerance=0.01,
                                               angular_tolerance=0.1)

    def test_a_reading_that_walked_every_face_is_still_complete(self) -> None:
        """The other half of the fix: it must still be able to say yes."""

        class Vertex:
            X = Y = Z = 0.0

        class Face:
            geom_type = "PLANE"

            def tessellate(self, tolerance, angular_tolerance):
                _ = tolerance, angular_tolerance
                return [Vertex(), Vertex(), Vertex()], [(0, 1, 2)]

        class Shape:
            def faces(self):
                return [Face(), Face()]

        reading = mesh_io.tessellate_brep(Shape(), tolerance=0.01,
                                          angular_tolerance=0.1)
        self.assertTrue(reading.enumerated)
        self.assertTrue(reading.complete)
        self.assertEqual((2, 2), (reading.faces, reading.tessellated))
        mesh_io.validate_brep_tessellation(Shape(), tolerance=0.01,
                                           angular_tolerance=0.1)

    def test_the_receipt_says_whether_the_shape_could_be_walked(self) -> None:
        """A reader of the evidence can tell "clean" from "never looked"."""
        reading = mesh_io.tessellate_brep(None, tolerance=0.01,
                                          angular_tolerance=0.1)
        self.assertFalse(reading.as_dict()["enumerated"])
        self.assertEqual(0, reading.as_dict()["faces"])

    def test_unwalkable_is_not_clean_even_with_faces_counted(self) -> None:
        """`enumerated` carries its own weight in `complete`, not the zero count.

        Through `tessellate_brep` the two always coincide -- the one site that
        sets `enumerated=False` also reports zero faces -- so a mutation
        dropping either conjunct survives every other test in this class. They
        are different statements: `enumerated=False` is *nobody looked*, and
        `faces == 0` is *looked, and there was nothing there*. `summary()`
        already tells them apart, and `BrepTessellation` is a public dataclass a
        caller can construct, so the invariant is asserted here against the type
        rather than against the one path that happens to reach it.
        """
        reading = mesh_io.BrepTessellation(
            faces=3, tessellated=3, failures=(), linear_deflection=0.01,
            angular_deflection=0.1, enumerated=False)
        self.assertFalse(reading.complete)
        self.assertIn("could not be enumerated", reading.summary())


class ConnectedComponentCountTest(unittest.TestCase):
    """The count must be right on a core-only install. ``mesh.split`` is not
    usable for this: it needs scipy for the component labelling and networkx
    to close any component with a hole, and where either is missing it raises
    -- which historically degraded to a silent "1 component", exactly the
    multi-body export the readiness gate exists to catch.
    """

    def test_single_solid(self) -> None:
        self.assertEqual(mesh_io.connected_component_count(_box()), 1)

    def test_disjoint_bodies_counted_separately(self) -> None:
        second = _box()
        second.apply_translation((10, 0, 0))
        third = _box()
        third.apply_translation((0, 20, 0))
        self.assertEqual(
            mesh_io.connected_component_count(trimesh.util.concatenate((_box(), second, third))),
            3,
        )

    def test_bodies_touching_at_one_corner_stay_separate(self) -> None:
        """Adjacency is by shared EDGE. Two cubes meeting at a single vertex
        share no edge, so they are two components -- matching trimesh.
        """
        second = _box()
        second.apply_translation((2, 2, 2))
        touching = trimesh.util.concatenate((_box(), second))
        touching.merge_vertices()
        self.assertEqual(mesh_io.connected_component_count(touching), 2)

    def test_unwelded_triangle_soup_is_one_component_per_face(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "box.stl"
            _box().export(path)
            raw, _ = mesh_io.load_mesh_raw(path)
        # No shared vertex indices -> no shared edges -> 12 isolated faces.
        self.assertEqual(mesh_io.connected_component_count(raw), 12)

    def test_long_thin_mesh_converges(self) -> None:
        """Label propagation must not need one round per face: a subdivided
        strip has a large graph diameter and is still a single component.
        """
        strip = trimesh.creation.box(extents=(1000, 0.2, 0.2))
        for _ in range(4):
            strip = strip.subdivide()
        self.assertEqual(mesh_io.connected_component_count(strip), 1)


class APartiallyTessellatedStepIsRefusedRatherThanMeasuredTest(unittest.TestCase):
    """**This proves an incomplete B-rep read cannot become an authoritative
    measurement, because it fails when the loaders take `brep.triangles` without
    consulting `brep.complete`.**

    That was the state routing STEP through the kernel first shipped in. OCC
    triangulates per face, and a face it cannot triangulate still leaves every
    other face's triangles in the result -- `BrepTessellation`'s own docstring
    says the partial reading is returned precisely so a caller has to decide in
    the open what to do with it. Both loaders decided nothing. A STEP with one
    failed face therefore became a mesh with a hole in it, and then acquired an
    area, an overhang figure and a preservation sample count that all describe a
    part nobody supplied.

    `validate_brep_tessellation` in the same module already had the correct
    shape -- read, check `complete`, raise `summary()` -- so this is that rule
    applied at the two entry points that skipped it, not a new policy.

    The reading is injected rather than provoked from a real file: making OCC
    fail on one face of a genuine STEP is not reproducible across kernel
    versions, and the property under test is what the *loader* does with a
    partial reading, not whether this month's OCC can be made to stumble. It
    also keeps the row in the commit gate, where a B-rep read costs seconds.
    """

    @staticmethod
    def _reading(*, failures: tuple[str, ...]) -> mesh_io.BrepTessellation:
        box = _box()
        return mesh_io.BrepTessellation(
            faces=12, tessellated=12 - len(failures), failures=failures,
            linear_deflection=0.01, angular_deflection=0.1,
            vertices=np.asarray(box.vertices, dtype=np.float64),
            triangles=np.asarray(box.faces, dtype=np.int64))

    def _step(self, tmp: str) -> Path:
        path = Path(tmp) / "probe.step"
        path.write_text("ISO-10303-21;\n", encoding="utf-8")
        return path

    def test_load_mesh_raw_refuses_a_partial_reading(self) -> None:
        partial = self._reading(failures=("face 7 (BSplineSurface): null triangulation",))
        with tempfile.TemporaryDirectory() as tmp:
            step = self._step(tmp)
            with unittest.mock.patch.object(mesh_io, "read_step",
                                            return_value=partial):
                with self.assertRaises(ValueError) as caught:
                    mesh_io.load_mesh_raw(step)
        self.assertIn("face 7", str(caught.exception),
                      "the refusal has to name the face that failed; a bare "
                      "'could not read' sends the reader back to OCC with "
                      "nothing to go on")

    def test_load_mesh_refuses_a_partial_reading(self) -> None:
        """The second entry point, which is the one the toolkit goes through."""
        partial = self._reading(failures=("face 3 (Cone): empty triangulation",))
        with tempfile.TemporaryDirectory() as tmp:
            step = self._step(tmp)
            with unittest.mock.patch.object(mesh_io, "read_step",
                                            return_value=partial):
                with self.assertRaises(ValueError):
                    mesh_io.load_mesh(step)

    def test_a_complete_reading_is_still_accepted_by_both_loaders(self) -> None:
        """The control. Without it a guard that refuses everything passes."""
        whole = self._reading(failures=())
        with tempfile.TemporaryDirectory() as tmp:
            step = self._step(tmp)
            with unittest.mock.patch.object(mesh_io, "read_step",
                                            return_value=whole):
                raw, _ = mesh_io.load_mesh_raw(step)
                normalized = mesh_io.load_mesh(step)
        self.assertGreater(len(raw.faces), 0)
        self.assertGreater(len(normalized.faces), 0)

    def test_a_shape_nobody_could_walk_is_refused_too(self) -> None:
        """`enumerated=False` is the third answer `complete` exists to keep
        separate: not 'every face read' and not 'a face failed', but nobody
        looked. It produces an empty failure list, so a guard written as
        `not failures` would pass it."""
        unwalkable = mesh_io.BrepTessellation(
            faces=0, tessellated=0, failures=(), linear_deflection=0.01,
            angular_deflection=0.1, vertices=np.zeros((0, 3)),
            triangles=np.zeros((0, 3), dtype=np.int64), enumerated=False)
        with tempfile.TemporaryDirectory() as tmp:
            step = self._step(tmp)
            with unittest.mock.patch.object(mesh_io, "read_step",
                                            return_value=unwalkable):
                with self.assertRaises(ValueError):
                    mesh_io.load_mesh_raw(step)


class APerFaceStepIsWeldedBeforeIntegrityIsReportedTest(unittest.TestCase):
    """**This proves a sound multi-face STEP is not reported as broken, because
    it fails when the loader builds the mesh without merging seam vertices.**

    OCC emits its own vertex block per face and offsets that block's triangle
    indices, so every seam is duplicated points at identical coordinates.
    `BrepTessellation.mesh()` is the authority on what to do about it -- "The
    merge is the parse, exactly as it is for an STL" -- and the first version of
    the STEP routing did not use it. It built the raw mesh with `process=False`
    instead, so adjacent faces shared no indexed edges and `load_mesh_raw`
    reported an ordinary six-face box as twelve components and not watertight.

    That number is worse than useless on the raw path specifically, because the
    raw path exists to state integrity *authoritatively before any repair*. A
    caller reading twelve components sees a finding about the supplied part when
    what it really describes is how this loader assembled it -- the same defect
    as measuring a partial read, wearing different clothes.

    The STL caveat in this module's own docstring does not transfer. For an STL
    the merge would hide a genuine defect in the file; for a per-face B-rep the
    merge is what turns the representation into a mesh at all.
    """

    @staticmethod
    def _unwelded(mesh) -> tuple[np.ndarray, np.ndarray]:
        """The same geometry with a private vertex per triangle corner.

        Maximally unwelded, which is the shape of what OCC hands over: no
        triangle shares an index with any neighbour.
        """
        corners = np.asarray(mesh.vertices, dtype=np.float64)[
            np.asarray(mesh.faces, dtype=np.int64).ravel()]
        return corners, np.arange(len(corners), dtype=np.int64).reshape(-1, 3)

    def _reading(self) -> mesh_io.BrepTessellation:
        verts, tris = self._unwelded(_box())
        return mesh_io.BrepTessellation(
            faces=6, tessellated=6, failures=(), linear_deflection=0.01,
            angular_deflection=0.1, vertices=verts, triangles=tris)

    def _step(self, tmp: str) -> Path:
        path = Path(tmp) / "box.step"
        path.write_text("ISO-10303-21;\n", encoding="utf-8")
        return path

    def test_the_fixture_really_is_unwelded(self) -> None:
        """The control for the control. If this box arrived already welded, every
        assertion below would pass without the loader doing anything."""
        verts, tris = self._unwelded(_box())
        soup = trimesh.Trimesh(vertices=verts, faces=tris, process=False)
        self.assertEqual(12, mesh_io.connected_component_count(soup))
        self.assertFalse(soup.is_watertight)

    def test_the_raw_step_read_is_watertight_and_one_component(self) -> None:
        reading = self._reading()
        with tempfile.TemporaryDirectory() as tmp:
            step = self._step(tmp)
            with unittest.mock.patch.object(mesh_io, "read_step",
                                            return_value=reading):
                raw, integrity = mesh_io.load_mesh_raw(step)
        self.assertEqual(1, mesh_io.connected_component_count(raw),
                         "a sound six-face solid read as more than one component, "
                         "which is a fact about the loader and not about the part")
        self.assertTrue(raw.is_watertight)
        self.assertEqual(1, integrity.components)
        self.assertTrue(integrity.watertight,
                        "raw_integrity is the authoritative pre-repair statement, "
                        "so a seam artefact here is reported as a defect in the "
                        "supplied STEP")

    def test_the_normalized_step_read_is_also_one_solid(self) -> None:
        reading = self._reading()
        with tempfile.TemporaryDirectory() as tmp:
            step = self._step(tmp)
            with unittest.mock.patch.object(mesh_io, "read_step",
                                            return_value=reading):
                normalized = mesh_io.load_mesh(step)
        self.assertEqual(1, mesh_io.connected_component_count(normalized))
        self.assertTrue(normalized.is_watertight)

    def test_an_incomplete_reading_still_refuses_before_any_of_this(self) -> None:
        """Welding must not have moved the completeness refusal downstream of a
        mesh: an incomplete read has to fail before there is anything to weld."""
        verts, tris = self._unwelded(_box())
        partial = mesh_io.BrepTessellation(
            faces=6, tessellated=5, failures=("face 2 (Plane): null triangulation",),
            linear_deflection=0.01, angular_deflection=0.1,
            vertices=verts, triangles=tris)
        with tempfile.TemporaryDirectory() as tmp:
            step = self._step(tmp)
            with unittest.mock.patch.object(mesh_io, "read_step",
                                            return_value=partial):
                with self.assertRaises(ValueError):
                    mesh_io.load_mesh_raw(step)

    def test_a_non_step_raw_read_is_still_unwelded(self) -> None:
        """The STL path must keep its raw semantics. Welding every format would
        hide the genuine defects `raw_integrity` exists to surface, and this
        module's docstring promises an unwelded STL reads as triangle soup."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "box.stl"
            _box().export(path)
            raw, _ = mesh_io.load_mesh_raw(path)
        self.assertEqual(12, mesh_io.connected_component_count(raw))


if __name__ == "__main__":
    unittest.main()
