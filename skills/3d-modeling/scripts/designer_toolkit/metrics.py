"""Measurement helpers on the EXPORTED mesh — the numbers Phase-4 must judge on.

Consolidates three things the designer and verifier re-derive by hand every run:

* ``measure()`` — bbox / volume / watertight / component count.
* ``datum_features()`` — hole and outline positions from a section, taken with the
  ``plane_transform`` that keeps them in model coordinates. A bare ``to_2D()``
  re-origins on a path-dependent frame, so hole centres silently stop matching
  the Phase-2 datums — the single most common false "placement OK". This is the
  one helper here that needs the ``section`` extra (scipy + shapely).
* ``overhang_area()`` — downward-facing area past the support screen. The
  threshold is a caller argument, defaulting to this module's constant; it agrees
  with the preflight gate only when the caller passes the plan's own
  ``downward_normal_z_max`` (see ``DEFAULT_DOWNWARD_NORMAL_Z_MAX`` below).

STL is a vertex soup with no connectivity, so watertightness and component count
are only meaningful after coincident vertices are merged. These helpers load via
``mesh_io.load_mesh`` (degenerate faces dropped, vertices merged) — the geometry
that prints. When a suspicious amount of merging matters, read the raw side and
mutation log through ``mesh_io.load_mesh_report`` directly.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Any

import numpy as np
import trimesh

from ._bootstrap import as_mesh  # (also puts scripts/ on sys.path; keep first)

import mesh_io  # noqa: E402  (needs the sys.path insert the line above performs)

# Support-screen margin (-sin(47deg)): an intended self-supporting 45deg chamfer
# tessellates to ~-0.7071 and must NOT be flagged, so only overhangs steeper than
# ~47deg are counted.
#
# This is a TOOLKIT default only. ``team_preflight`` has no default at all: every
# support rule in the print plan must carry its own ``downward_normal_z_max``,
# which the authoritative gate reads per-rule. A plan shipping the bare 45deg
# value (-0.7071) therefore screens strictly MORE area than this constant does,
# so a self-check run at this default can read clean where the gate FAILs. Pass
# the plan's value explicitly (``overhang_area(..., threshold=...)``) whenever
# the plan is known -- which is what `commission` does, per support rule.
DEFAULT_DOWNWARD_NORMAL_Z_MAX = -0.73

# -sin(45deg): the bare self-supporting chamfer, and the tightest value a print
# plan can sensibly declare. A 45deg chamfer tessellates to just past it and is
# then falsely flagged, which is why the default above carries a ~47deg margin
# and why the contract's plan schema recommends the same -0.73. Kept named
# because a plan MAY declare this stricter value, and a self-check left on the
# default would then screen less area than the gate.
BARE_45_DEG = -0.70710678


@dataclass(frozen=True)
class MeasureReport:
    bbox_mm: dict
    volume_mm3: float
    watertight: bool
    components: int
    triangle_count: int
    center_mm: dict


@dataclass(frozen=True)
class Feature:
    kind: str            # "outline" | "hole"
    center_mm: tuple     # (u, v) in the section's in-plane frame (model X,Y for a Z-cut)
    size_mm: tuple       # (width, height) of the ring's bbox
    area_mm2: float


def measure(mesh_or_path: Any) -> MeasureReport:
    m = as_mesh(mesh_or_path)
    ext = m.bounding_box.extents
    ctr = m.bounding_box.centroid
    integ = mesh_io.compute_integrity(m)
    return MeasureReport(
        bbox_mm={"x": float(ext[0]), "y": float(ext[1]), "z": float(ext[2])},
        volume_mm3=float(abs(m.volume)),
        watertight=bool(integ.watertight),
        components=int(integ.components),
        triangle_count=int(integ.face_count),
        center_mm={"x": float(ctr[0]), "y": float(ctr[1]), "z": float(ctr[2])},
    )


def _ring_bbox_center_size(coords: np.ndarray) -> tuple:
    lo = coords.min(0)
    hi = coords.max(0)
    ctr = (lo + hi) / 2
    size = hi - lo
    return (float(ctr[0]), float(ctr[1])), (float(size[0]), float(size[1]))


def _ring_area(coords: np.ndarray) -> float:
    x, y = coords[:, 0], coords[:, 1]
    return float(0.5 * abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1))))


# trimesh soft dependencies the section path reaches in turn: scipy (csgraph,
# walking the cut edges), networkx (vertex graph -> closed paths), shapely (the
# rings), rtree (the enclosure tree that decides which ring is a hole). Declared
# together as the `section` extra in pyproject.toml.
_SECTION_STACK = ("scipy", "networkx", "shapely", "rtree")


def _require_section_stack() -> None:
    """Fail fast, and legibly, when the cross-section extra is not installed.

    None of these are core dependencies, and trimesh defers each ImportError
    into an exception wrapper that only fires deep inside its own call stack --
    as a bare ``ModuleNotFoundError: No module named 'scipy'`` several frames
    below this function, with nothing to say which install fixes it. Checking
    the whole set up front also means the caller learns about all four at once
    instead of rediscovering one per run.
    """
    missing = [name for name in _SECTION_STACK if importlib.util.find_spec(name) is None]
    if missing:
        raise ImportError(
            f"datum_features() needs {', '.join(missing)} "
            f"(mesh cross-section + ring extraction): uv sync --frozen --no-dev --extra section"
        )


def datum_features(mesh_or_path: Any, plane_origin, plane_normal=(0, 0, 1)) -> list:
    """Return the outline and hole rings on a section plane, in model
    coordinates. For a Z-normal cut the returned ``center_mm`` (u, v) aligns
    with model (x, y); compare each hole centre to its Phase-2 datum. Mirrored
    layouts fit the same magnitudes, so also compare with u negated when
    handedness is in question.

    Needs the ``section`` extra (scipy + shapely); every other helper in this
    module runs on the core trimesh + numpy stack.
    """
    _require_section_stack()
    m = as_mesh(mesh_or_path)
    origin = np.asarray(plane_origin, dtype=float)
    normal = np.asarray(plane_normal, dtype=float)
    section = m.section(plane_origin=origin, plane_normal=normal)
    if section is None:
        return []
    # ALWAYS pass plane_transform — a bare to_2D() picks a path-dependent frame.
    planar, _ = section.to_2D(trimesh.geometry.plane_transform(origin, normal))
    features: list = []
    for poly in planar.polygons_full:
        oc = np.asarray(poly.exterior.coords)
        o_ctr, o_size = _ring_bbox_center_size(oc)
        features.append(Feature("outline", o_ctr, o_size, float(poly.area)))
        for hole in poly.interiors:
            hc = np.asarray(hole.coords)
            h_ctr, h_size = _ring_bbox_center_size(hc)
            features.append(Feature("hole", h_ctr, h_size, _ring_area(hc)))
    return features


DEFAULT_BED_Z_MM = 0.0
DEFAULT_BED_TOLERANCE_MM = 0.05


def overhang_area(mesh_or_path: Any, *, threshold: float = DEFAULT_DOWNWARD_NORMAL_Z_MAX,
                  bed_z: float = DEFAULT_BED_Z_MM,
                  bed_tolerance: float = DEFAULT_BED_TOLERANCE_MM, transform=None) -> float:
    """Downward-facing area (mm^2) not in contact with the bed.

    This is the authoritative gate's arithmetic, and it used to be a second,
    divergent one. The gate calls a face bed-contact when **all three vertices**
    sit within ``bed_tolerance`` of the bed plane; this function instead
    excluded faces whose *centroid* fell below an arbitrary ``min_z`` of 0.3 mm,
    a height with no relation to the bed tolerance. On a real archived candidate
    the two answered 9,888 mm2 and 10,507 mm2 for the same mesh in the same
    frame -- and at the default ``min_z`` this function returned 0.0 mm2 for a
    part the gate scored at 10,507, because a flat underside sits below 0.3 mm
    everywhere. A screen that reports zero for an unsupported part is worse than
    no screen.

    Pass the model-to-printer ``transform`` to screen in print orientation.
    """
    m = as_mesh(mesh_or_path)
    normals = m.face_normals
    triangles = m.vertices[m.faces]
    if transform is not None:
        transform = np.asarray(transform, dtype=float)
        normals = normals @ transform[:3, :3].T
        triangles = trimesh.transformations.transform_points(
            triangles.reshape(-1, 3), transform).reshape(triangles.shape)
    downward = normals[:, 2] <= threshold
    bed_contact = np.max(np.abs(triangles[:, :, 2] - bed_z), axis=1) <= bed_tolerance
    return float(m.area_faces[downward & ~bed_contact].sum())
