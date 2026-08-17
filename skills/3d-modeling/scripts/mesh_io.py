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

    ``enumerated`` is the second thing this type has to be able to say, and it
    was missing (`docs/defects.md` D23). ``complete`` was ``not failures``, and a
    shape that cannot be walked at all produces an empty failure list -- so the
    probe added to stop `diagnose` calling an untessellatable STEP clean
    returned clean for the one input it can learn least about. There are three
    answers here, not two: every face read, some face failed, and *nobody
    looked*. The third is not a weaker version of the first.
    """

    faces: int
    tessellated: int
    failures: tuple[str, ...]
    linear_deflection: float
    angular_deflection: float
    vertices: Any = None
    triangles: Any = None
    # False where the shape exposed no face enumeration this function could
    # call. Defaulted True so that every construction site that *did* walk the
    # shape keeps its meaning without restating it.
    enumerated: bool = True

    @property
    def complete(self) -> bool:
        """Every face of a shape that had faces was read.

        Three conjuncts, and each one is a false clean that reached a caller.
        A shape nobody could walk is unknown. A shape with zero faces is not a
        solid, and tessellating none of none is not a success. Only then does
        the absence of failures mean what it says.
        """
        return self.enumerated and self.faces > 0 and not self.failures

    def as_dict(self) -> dict[str, Any]:
        """Receipt-shaped: what was read and how, never the arrays."""
        return {
            "method": "OCC per-face triangulation through build123d",
            "linear_deflection": self.linear_deflection,
            "angular_deflection": self.angular_deflection,
            # On the receipt rather than inferred from `faces == 0`, so that a
            # reader of the evidence can tell "this shape has no faces" from
            # "this shape was never walked" without knowing which of the two
            # produces a zero here.
            "enumerated": self.enumerated,
            "faces": self.faces,
            "tessellated_faces": self.tessellated,
            "untessellatable_faces": len(self.failures),
            "failures": list(self.failures),
        }

    def summary(self) -> str:
        if not self.enumerated:
            return ("B-rep faces could not be enumerated: the shape exposes no "
                    "callable faces(), so nothing here has looked at it. This is "
                    "not a clean reading -- it is no reading. A null shape from "
                    "an OCC repair step arrives exactly like this.")
        if self.faces == 0:
            return ("B-rep tessellation found no faces to read. A shape with no "
                    "faces is not a solid, and tessellating none of none is not "
                    "a successful export.")
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
        # Not a clean reading. `enumerated=False` is what stops the empty
        # failure list below reading as success -- see `BrepTessellation` and
        # `docs/defects.md` D23. Returned rather than raised because the shape
        # -- including `None`, which is what an OCC repair step hands back when
        # it could not produce one -- is the caller's to explain.
        return BrepTessellation(0, 0, (), tolerance, angular_tolerance,
                                enumerated=False)

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


def canonical_order(mesh):
    """The same geometry, with vertex and face order made a function of it.

    A seeded plan is only reproducible if the thing it indexes into is. Face
    order decides which face each sample lands on, and nothing guarantees that
    two reads of one file -- through a different loader path, a scene rather than
    a mesh, a concatenation whose order came from a dict -- present the faces in
    the same order. Sorting them here removes the question rather than assuming
    the answer.

    Winding is preserved: each triangle is rolled so its lowest vertex index
    leads, which is a cyclic shift, and `signed_distance` reads winding for its
    sign. This is defined up to exactly coincident vertices, which the merge in
    `_load` is what removes.
    """
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    if len(vertices) == 0 or len(faces) == 0:
        return mesh

    vertex_order = np.lexsort((vertices[:, 2], vertices[:, 1], vertices[:, 0]))
    rank = np.empty(len(vertex_order), dtype=np.int64)
    rank[vertex_order] = np.arange(len(vertex_order), dtype=np.int64)
    faces = rank[faces]

    roll = np.argmin(faces, axis=1)
    columns = (np.arange(3, dtype=np.int64)[None, :] + roll[:, None]) % 3
    faces = np.take_along_axis(faces, columns, axis=1)
    face_order = np.lexsort((faces[:, 2], faces[:, 1], faces[:, 0]))

    return trimesh.Trimesh(vertices=vertices[vertex_order],
                           faces=faces[face_order], process=False)


def body_identities(mesh: trimesh.Trimesh, *,
                    bodies: Any = None) -> list[dict[str, Any]]:
    """Every disconnected body, with a handle that is a function of its shape.

    `diagnose` reported `bodies` as a count, and a count cannot be referenced:
    a declaration selecting "the third body" resolves to whatever `split`
    returned that run. The handle here is a digest over the body's own geometry
    in canonical form, so it does not move when load order, vertex order or the
    loader path does -- which is the property that lets a receipt name a body
    and mean the same one next time.

    Rows are ordered by handle rather than by split order, for the same reason:
    two reads of one file must present the bodies in one order, or "the first"
    is not a thing anybody can say. `bbox_mm` and `volume_mm3` ride along
    because a list of digests is unreadable, and a person choosing which body
    to keep would have to re-open the file to make the choice.
    """
    # No empty-mesh guard: `split` returns nothing for a mesh with no faces, so
    # a guard here would be a second copy of that rule, and a mutation removing
    # it survived because it could not change an answer.
    # `bodies` lets a caller that has already split hand the result over:
    # `diagnose` computes exactly this split one line above, and splitting
    # twice was over half the cost this function added to an intake step.
    rows: list[dict[str, Any]] = []
    for body in (mesh.split(only_watertight=False)
                 if bodies is None else bodies):
        # Rounded and sign-normalised BEFORE canonicalising, which is the whole
        # of the fix and not a detail. Rounding only the hash input left the
        # sort reading unrounded coordinates, so noise of 1e-9 could flip a
        # near-tie and permute the entire array before the rounding happened --
        # and near-ties are the normal case, since every axis-aligned box has
        # four vertices sharing an x. `+ 0.0` maps -0.0 to 0.0: the two are
        # equal by every numeric test and differ in `tobytes`, and exporters
        # really do write `v -0.0 -0.0 -0.0`.
        #
        # 6 places is a nanometre on a part measured in millimetres, far below
        # anything this pipeline claims to resolve. It is applied here and never
        # inside `canonical_order`, because that function's ordering is what
        # every frozen sample plan was built on.
        settled = np.round(np.asarray(body.vertices, dtype=np.float64), 6) + 0.0
        ordered = canonical_order(trimesh.Trimesh(
            vertices=settled, faces=body.faces, process=False))
        digest = hashlib.sha256()
        digest.update(np.asarray(ordered.vertices, dtype=np.float64).tobytes())
        digest.update(np.asarray(ordered.faces, dtype=np.int64).tobytes())
        low, high = ordered.bounds
        rows.append({
            "body_sha256": digest.hexdigest(),
            "bbox_mm": [round(float(high[axis] - low[axis]), 4)
                        for axis in range(3)],
            "volume_mm3": (round(float(ordered.volume), 4)
                           if ordered.is_watertight else None),
            "faces": int(len(ordered.faces)),
        })
    return sorted(rows, key=lambda row: row["body_sha256"])


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
    # STEP goes through this runtime's own kernel, never through `trimesh.load`.
    #
    # `trimesh.load` dispatches STEP to `cascadio`, which this repository
    # deliberately does not carry: `read_step` below records why, measured on
    # `vent_mount.step` -- cascadio returns the part in METRES where the kernel
    # path returns millimetres, the silent unit substitution ARCHITECTURE.md
    # section 12 forbids. So the dispatch could only ever fail here, and it did,
    # with `Failed to load STL: No module named 'cascadio'`.
    #
    # That failure was not loud. `cli._inherited_overhang` swallowed it into
    # `unmeasured` and returned None, leaving a MODIFY job's inherited-overhang
    # ceiling at the generated 0.0 -- so a candidate was charged for the
    # 54.79 mm2 of downward area it inherited from the very part it was told to
    # preserve. And `commission._preservation_samples` raised through it, which
    # disables the preservation audit entirely whenever
    # `minimum_detectable_defect_mm` is declared on a STEP source: coverage drops
    # and the job fails a gate for a reason that has nothing to do with the
    # candidate. On the MODIFY lane, whose whole subject is preservation, that is
    # the one gate that had to work.
    if str(path).lower().endswith((".step", ".stp")):
        brep = read_step(path)
        tm = trimesh.Trimesh(vertices=brep.vertices, faces=brep.triangles,
                             process=False)
    else:
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
    # STEP through the kernel, for the reason `load_mesh_raw` records at
    # length. Routed here as well and not only there, because `as_mesh` in
    # `designer_toolkit/_bootstrap.py` sends every toolkit entry point through
    # THIS function -- so `overhang_area` on a STEP path died on cascadio even
    # after the raw loader was fixed. Two entry points, one substitution: the
    # branch has to exist at both or the toolkit and the analysis path disagree
    # about which files are readable, which is exactly the drift `as_mesh`'s own
    # docstring says it exists to prevent.
    if str(path).lower().endswith((".step", ".stp")):
        brep = read_step(path)
        tm = trimesh.Trimesh(vertices=brep.vertices, faces=brep.triangles)
    else:
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
