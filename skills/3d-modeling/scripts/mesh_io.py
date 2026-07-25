"""Trimesh mesh loading with validation guards, plus a raw-vs-normalized
integrity report.

Kept separate from preview.py so consumers that only need mesh loading
(run_cadquery_model.py's --strict watertight check) don't
pay the pyrender + PyOpenGL import cost. Only depends on trimesh + numpy.

Two views of the same file are available:

- ``load_mesh_raw`` / the ``raw`` + ``raw_integrity`` fields of
  ``load_mesh_report``: exactly as parsed, with **no** topology-changing
  repair -- no vertex merge, no degenerate-face removal. Integrity metrics
  (``MeshIntegrity``) are computed on this unrepaired geometry, so a genuine
  defect (e.g. a degenerate export) can never be silently dropped before an
  acceptance check ever sees it. A hard failure (unparseable file, no
  vertices, no faces, non-finite coordinates) is raised here, before any
  normalization is attempted, so normalization can never turn a raw hard
  failure into a pass.
- ``load_mesh`` (existing, backward-compatible) / the ``normalized`` field of
  ``load_mesh_report``: a repaired copy (degenerate faces dropped, coincident
  vertices merged) suitable for rendering and further modelling -- never for
  a raw acceptance decision.

Caveat: the STL format stores every triangle as three independent (x, y, z)
triples -- it has no shared-vertex indices at all. So for an STL source,
``MeshIntegrity.duplicate_vertex_count`` will be close to the full vertex
count, and ``watertight``/``components``/``non_manifold_edge_count`` reflect
that raw triangle-soup structure rather than a real defect -- that is simply
the honest raw truth of what an unwelded STL contains before any repair.
Formats that store shared vertex indices (OBJ, PLY, glTF, ...) report
meaningful connectivity numbers directly on the raw parse.
``degenerate_face_count`` is a pure per-triangle area check and is
meaningful for every format, welded or not.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import numpy as np
import trimesh


@dataclass(frozen=True)
class MeshIntegrity:
    """Mutation-free integrity metrics measured on a mesh exactly as parsed
    (no vertex merge, no degenerate-face removal, no other repair applied).
    """

    vertex_count: int
    face_count: int
    watertight: bool
    components: int
    degenerate_face_count: int
    duplicate_vertex_count: int
    non_manifold_edge_count: int | None  # None only if the cheap check could not run


@dataclass(frozen=True)
class MeshMutationLog:
    """Pre/post counts recorded while producing the normalized copy from the
    raw parse. Every count is measured directly (never assumed), so this log
    is an honest record of exactly what normalization changed.
    """

    vertices_before: int
    vertices_after: int
    faces_before: int
    faces_after: int
    degenerate_faces_removed: int
    vertices_merged: int


@dataclass(frozen=True)
class MeshReport:
    """Both views of one mesh file: the raw, un-repaired parse with its
    integrity metrics, and a separately normalized copy with a mutation log
    and a hash of the normalized geometry. The raw side is authoritative for
    acceptance checks; the normalized side is for rendering/visuals only.
    """

    raw: trimesh.Trimesh
    raw_integrity: MeshIntegrity
    normalized: trimesh.Trimesh
    mutation_log: MeshMutationLog
    normalized_sha256: str


def _require_parsed_mesh(tm: Any, *, label: str = "mesh file") -> None:
    """Raise ValueError for the hard-failure conditions shared by the raw and
    normalized loaders: unparseable, empty, or non-finite geometry. Runs
    before any repair is attempted, so a raw hard failure can never be
    hidden by later normalization.
    """
    if not hasattr(tm, "vertices") or len(tm.vertices) == 0:
        raise ValueError(f"{label} contains no vertices")
    if not hasattr(tm, "faces") or len(tm.faces) == 0:
        raise ValueError(f"{label} contains no triangles")
    if not np.isfinite(tm.vertices).all():
        raise ValueError(f"{label} has non-finite vertex coordinates (NaN or inf)")


def _degenerate_face_count(mesh: trimesh.Trimesh) -> int:
    # nondegenerate_faces() only computes a boolean mask; it does not mutate
    # the mesh (that only happens if a caller feeds the mask to update_faces).
    mask = mesh.nondegenerate_faces()
    return int((~mask).sum())


def _duplicate_vertex_count(vertices: np.ndarray) -> int:
    if vertices.shape[0] == 0:
        return 0
    _, counts = np.unique(vertices, axis=0, return_counts=True)
    duplicated_groups = counts[counts > 1]
    if duplicated_groups.size == 0:
        return 0
    return int((duplicated_groups - 1).sum())


def _components(mesh: trimesh.Trimesh) -> int:
    try:
        return len(mesh.split(only_watertight=False))
    except Exception:  # noqa: BLE001 - best-effort, never blocks a read
        return 1


def _non_manifold_edge_count(mesh: trimesh.Trimesh) -> int | None:
    try:
        edges = mesh.edges_sorted
        if edges.shape[0] == 0:
            return 0
        _, counts = np.unique(edges, axis=0, return_counts=True)
        return int((counts > 2).sum())
    except Exception:  # noqa: BLE001 - "if cheap": skip rather than block a read
        return None


def compute_integrity(mesh: trimesh.Trimesh) -> MeshIntegrity:
    """Compute ``MeshIntegrity`` for ``mesh`` exactly as it stands -- every
    check here is read-only and does not call ``update_faces``,
    ``merge_vertices``, or any other topology-changing method.
    """
    return MeshIntegrity(
        vertex_count=int(mesh.vertices.shape[0]),
        face_count=int(mesh.faces.shape[0]),
        watertight=bool(mesh.is_watertight),
        components=_components(mesh),
        degenerate_face_count=_degenerate_face_count(mesh),
        duplicate_vertex_count=_duplicate_vertex_count(mesh.vertices),
        non_manifold_edge_count=_non_manifold_edge_count(mesh),
    )


def load_mesh_raw(path) -> tuple[trimesh.Trimesh, MeshIntegrity]:
    """Parse ``path`` with NO topology-changing repair (no vertex merge, no
    degenerate-face removal, no normal fixing) and return
    ``(raw_mesh, integrity)``.

    Raises ValueError for the same hard-failure conditions as ``load_mesh``
    (unparseable file, no vertices, no faces, non-finite coordinates),
    checked here before any normalization is attempted -- a raw hard
    failure can never be converted into a pass by later repair.
    """
    try:
        tm = trimesh.load(path, force="mesh", process=False)
    except Exception as e:
        raise ValueError(f"Failed to load STL: {e}") from e
    _require_parsed_mesh(tm, label="STL file")
    integrity = compute_integrity(tm)
    return tm, integrity


def load_mesh(path):
    """Load a mesh file via trimesh, repaired for rendering/modelling use.

    Raises ValueError if the file cannot be parsed, contains no geometry,
    has zero faces, or has non-finite vertex coordinates. Callers handle
    the failure in-process instead of being killed by sys.exit, and silent
    garbage (zero-face or NaN meshes) is stopped before it reaches pyrender.

    Backward-compatible: unchanged behavior and return value (a single
    repaired ``trimesh.Trimesh``). For a raw, un-repaired read plus
    integrity metrics and a mutation log, use ``load_mesh_report`` instead --
    acceptance/verification checks should read the raw side, never this one.
    """
    try:
        tm = trimesh.load(path, force="mesh")
    except Exception as e:
        raise ValueError(f"Failed to load STL: {e}") from e
    _require_parsed_mesh(tm, label="STL file")
    # OCC's tessellator emits zero-area triangles at the poles of
    # spherical faces (and similar degenerate spots). They carry no
    # surface, but their zero-length open edges make an otherwise
    # closed mesh read as non-watertight. Drop them before any checks.
    tm.update_faces(tm.nondegenerate_faces())
    tm.merge_vertices()
    return tm


def normalize_mesh(raw: trimesh.Trimesh) -> tuple[trimesh.Trimesh, MeshMutationLog]:
    """Produce a repaired copy of ``raw`` (degenerate faces dropped,
    coincident vertices merged) for rendering/modelling, plus a mutation log
    of what changed. Never mutates ``raw`` itself.
    """
    normalized = raw.copy()
    vertices_before = int(normalized.vertices.shape[0])
    faces_before = int(normalized.faces.shape[0])
    degenerate_removed = _degenerate_face_count(normalized)
    normalized.update_faces(normalized.nondegenerate_faces())
    normalized.merge_vertices()
    vertices_after = int(normalized.vertices.shape[0])
    faces_after = int(normalized.faces.shape[0])
    mutation_log = MeshMutationLog(
        vertices_before=vertices_before,
        vertices_after=vertices_after,
        faces_before=faces_before,
        faces_after=faces_after,
        degenerate_faces_removed=degenerate_removed,
        vertices_merged=vertices_before - vertices_after,
    )
    return normalized, mutation_log


def _mesh_sha256(mesh: trimesh.Trimesh) -> str:
    digest = hashlib.sha256()
    digest.update(np.ascontiguousarray(mesh.vertices, dtype=np.float64).tobytes())
    digest.update(np.ascontiguousarray(mesh.faces, dtype=np.int64).tobytes())
    return digest.hexdigest()


def load_mesh_report(path) -> MeshReport:
    """Load ``path`` and return BOTH a raw, mutation-free integrity read and
    a separately normalized copy for rendering, with a mutation log and the
    normalized geometry's hash.

    The raw hard-failure guards run first (see ``load_mesh_raw``): a raw
    parse failure always raises before normalization is attempted, so a
    repaired copy can never convert a raw hard failure into a pass.
    """
    raw, raw_integrity = load_mesh_raw(path)
    normalized, mutation_log = normalize_mesh(raw)
    return MeshReport(
        raw=raw,
        raw_integrity=raw_integrity,
        normalized=normalized,
        mutation_log=mutation_log,
        normalized_sha256=_mesh_sha256(normalized),
    )
