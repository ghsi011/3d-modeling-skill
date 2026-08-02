"""Trimesh mesh loading with validation guards, plus a raw-vs-normalized
integrity report.

Kept separate from preview.py so consumers that only need mesh loading
(the runner's --strict watertight check) don't
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
count, and ``watertight``/``components`` reflect
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


# How coarsely a *supplied* B-rep is read when a tool downstream needs a mesh of
# it. Deliberately not shared with the export deflection in
# `pipeline/backends/build123d_backend.py`: that one decides how fine the part we
# ship is, this one decides how fine our reading of somebody else's part is. The
# two happen to agree today and are free to diverge, and a single constant would
# make one of those decisions silently by making the other.
#
# It is a declared constant rather than an argument with a default because a
# preservation audit's evidence depends on it, and a deflection nobody wrote down
# is a measurement nobody can reproduce. Callers that record evidence put the
# values on the receipt.
BREP_READ_LINEAR_DEFLECTION = 0.01
BREP_READ_ANGULAR_DEFLECTION = 0.1


@dataclass(frozen=True)
class BrepTessellation:
    """One reading of a B-rep as triangles, with what it could not read.

    ``failures`` is the point of the type. A B-rep with a face OCC cannot
    triangulate still yields triangles for every other face, and a caller that
    took those and said nothing would be measuring a part with holes in it while
    reporting on the part. So the incomplete reading is *returned* rather than
    thrown away, and every caller has to decide in the open what to do with a
    partial one.
    """

    faces: int
    tessellated: int
    failures: tuple[str, ...]
    linear_deflection: float
    angular_deflection: float
    vertices: Any = None
    triangles: Any = None

    @property
    def complete(self) -> bool:
        return not self.failures

    def as_dict(self) -> dict[str, Any]:
        """Receipt-shaped: what was read and how, never the arrays."""
        return {
            "method": "OCC per-face triangulation through build123d",
            "linear_deflection": self.linear_deflection,
            "angular_deflection": self.angular_deflection,
            "faces": self.faces,
            "tessellated_faces": self.tessellated,
            "untessellatable_faces": len(self.failures),
            "failures": list(self.failures),
        }

    def summary(self) -> str:
        return ("B-rep tessellation failed for affected face(s): "
                + "; ".join(self.failures)
                + ". Repair or remove the named face(s) before export.")

    def mesh(self) -> trimesh.Trimesh:
        """The triangles as a mesh, coincident vertices merged.

        Per-face tessellation emits its own vertex block per face, so the seams
        are duplicated points at identical coordinates until they are merged.
        The merge is the parse, exactly as it is for an STL.
        """
        if self.vertices is None or self.triangles is None:
            raise ValueError("this tessellation kept no geometry")
        return trimesh.Trimesh(vertices=np.asarray(self.vertices, dtype=np.float64),
                               faces=np.asarray(self.triangles, dtype=np.int64),
                               process=True)


def tessellate_brep(shape: Any, *, tolerance: float, angular_tolerance: float,
                    keep_geometry: bool = False) -> BrepTessellation:
    """Probe every face of a B-rep through the public tessellation API.

    OCC represents a face with no usable triangulation as a null polygon, and
    ``Shape.tessellate`` over the whole shape dies on the first one with
    ``NoneType has no attribute NbNodes`` -- which names no face. Going face by
    face keeps the index, the surface type and the centre of each one that fails,
    so the defective surface can be found.

    The whole shape is meshed first where the object supports it, because OCC
    discretizes a shared edge once per shape: meshing each face in isolation
    gives neighbouring faces different edge polygons and a mesh full of cracks.
    ``Shape.mesh`` is a no-op when a triangulation of adequate deflection already
    exists, so the per-face calls below reuse that one pass.
    """
    faces_method = getattr(shape, "faces", None)
    if not callable(faces_method):
        return BrepTessellation(0, 0, (), tolerance, angular_tolerance)

    mesh_method = getattr(shape, "mesh", None)
    if callable(mesh_method):
        try:
            mesh_method(tolerance, angular_tolerance)
        except Exception:  # noqa: BLE001 - a shape-wide pass that fails is not the
            pass          # finding; the per-face probe below is, and it still runs

    try:
        faces = list(faces_method())
    except Exception as exc:  # noqa: BLE001 - converted to actionable geometry error
        raise ValueError(f"B-rep tessellation could not enumerate faces: {exc}") from exc

    failures: list[str] = []
    points: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    tessellated = 0
    for index, face in enumerate(faces):
        label = f"face {index}"
        geom_type = getattr(face, "geom_type", None)
        if geom_type is not None:
            label += f" ({geom_type})"
        try:
            centre = getattr(face, "center", lambda: None)()
            if centre is not None:
                label += f" at {centre}"
        except Exception:  # noqa: BLE001 - label enrichment must not mask the probe
            pass
        tessellate = getattr(face, "tessellate", None)
        try:
            if not callable(tessellate):
                raise ValueError("face has no tessellate() method")
            vertices, faceted = tessellate(tolerance, angular_tolerance)
            if vertices is None or faceted is None:
                raise ValueError("null triangulation")
            if len(vertices) == 0 or len(faceted) == 0:
                raise ValueError("empty triangulation")
        except Exception as exc:  # noqa: BLE001 - one report names all bad faces
            failures.append(f"{label}: {exc}")
            continue
        tessellated += 1
        if keep_geometry:
            offset = len(points)
            points.extend((float(v.X), float(v.Y), float(v.Z)) for v in vertices)
            triangles.extend((a + offset, b + offset, c + offset)
                             for a, b, c in faceted)

    return BrepTessellation(
        faces=len(faces), tessellated=tessellated, failures=tuple(failures),
        linear_deflection=tolerance, angular_deflection=angular_tolerance,
        vertices=(np.asarray(points, dtype=np.float64).reshape(-1, 3)
                  if keep_geometry else None),
        triangles=(np.asarray(triangles, dtype=np.int64).reshape(-1, 3)
                   if keep_geometry else None))


def read_step(path, *, tolerance: float = BREP_READ_LINEAR_DEFLECTION,
              angular_tolerance: float = BREP_READ_ANGULAR_DEFLECTION,
              keep_geometry: bool = True) -> BrepTessellation:
    """Import a STEP through the kernel this runtime already carries.

    `build123d` is a core dependency and already reads STEP for diagnosis, so
    this adds no packaging surface. The alternative -- letting `trimesh.load`
    dispatch to `cascadio` -- would put a second OCC build in the process with
    its own unit convention: measured on `vent_mount.step`, cascadio returns the
    part in **metres** where this path returns millimetres, which is precisely
    the silent unit substitution `ARCHITECTURE.md` section 12 forbids.

    The import is function-local: `import build123d` costs about 10 s on this
    machine, and a job that never touches a STEP must not pay it.
    """
    from build123d import import_step
    return tessellate_brep(import_step(str(path)), tolerance=tolerance,
                           angular_tolerance=angular_tolerance,
                           keep_geometry=keep_geometry)


def validate_brep_tessellation(shape: Any, *, tolerance: float,
                               angular_tolerance: float) -> None:
    """Fail with face-level diagnostics before a B-rep is exported."""
    reading = tessellate_brep(shape, tolerance=tolerance,
                              angular_tolerance=angular_tolerance)
    if not reading.complete:
        raise ValueError(reading.summary())


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


def connected_component_count(mesh: trimesh.Trimesh) -> int:
    """Number of connected components of ``mesh``, counted on face adjacency
    (two faces are connected when they share an edge), matching what
    ``trimesh.Trimesh.split(only_watertight=False)`` reports.

    Deliberately NOT implemented via ``mesh.split``: that path builds a
    submesh per component and needs scipy (``csgraph``) and, for any
    component with a hole, networkx (``repair.fill_holes``). When either is
    absent trimesh raises, and a caller swallowing that exception silently
    reports "1 component" -- exactly the multi-body export the readiness gate
    exists to catch. This is pure numpy: same answer on every install.

    Label propagation with pointer jumping (Shiloach-Vishkin): each round
    pulls both ends of every adjacency toward the smaller label, then squashes
    label chains to their root, so it converges in O(log n) rounds rather than
    walking the mesh diameter one face at a time.
    """
    face_count = int(np.asarray(mesh.faces).shape[0])
    if face_count == 0:
        return 0
    adjacency = np.asarray(mesh.face_adjacency, dtype=np.int64).reshape((-1, 2))
    if adjacency.shape[0] == 0:
        return face_count  # no shared edges: every face is its own component
    left = adjacency[:, 0]
    right = adjacency[:, 1]
    labels = np.arange(face_count, dtype=np.int64)
    while True:
        previous = labels
        hooked = labels.copy()
        np.minimum.at(hooked, left, labels[right])
        np.minimum.at(hooked, right, labels[left])
        while True:  # pointer jumping: labels[i] <= i, so this terminates
            jumped = hooked[hooked]
            if np.array_equal(jumped, hooked):
                break
            hooked = jumped
        labels = hooked
        if np.array_equal(labels, previous):
            return int(np.unique(labels).size)


def compute_integrity(mesh: trimesh.Trimesh) -> MeshIntegrity:
    """Compute ``MeshIntegrity`` for ``mesh`` exactly as it stands -- every
    check here is read-only and does not call ``update_faces``,
    ``merge_vertices``, or any other topology-changing method.

    Raises ValueError when the component count cannot be established. A
    swallowed failure here would report "1 component" for a mesh nobody
    counted -- precisely the multi-body export the readiness gate exists to
    catch -- so the failure is re-raised with the mesh's shape attached
    instead. Callers that already handle a bad mesh (the job runner,
    preview) catch ValueError and surface the message.
    """
    try:
        components = connected_component_count(mesh)
    except Exception as exc:  # noqa: BLE001 - re-raised with context, never swallowed
        raise ValueError(
            f"connected-component count failed on this mesh "
            f"({int(mesh.vertices.shape[0])} vertices, {int(mesh.faces.shape[0])} faces): {exc}"
        ) from exc
    return MeshIntegrity(
        vertex_count=int(mesh.vertices.shape[0]),
        face_count=int(mesh.faces.shape[0]),
        watertight=bool(mesh.is_watertight),
        components=components,
        degenerate_face_count=_degenerate_face_count(mesh),
        duplicate_vertex_count=_duplicate_vertex_count(mesh.vertices),
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
