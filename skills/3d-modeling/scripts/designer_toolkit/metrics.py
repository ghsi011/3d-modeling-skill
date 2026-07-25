"""Measurement helpers on the EXPORTED mesh — the numbers Phase-4 must judge on.

Consolidates three things the designer and verifier re-derive by hand every run:

* ``measure()`` — bbox / volume / watertight / component count.
* ``datum_features()`` — hole and outline positions from a section, taken with the
  ``plane_transform`` that keeps them in model coordinates. A bare ``to_2D()``
  re-origins on a path-dependent frame, so hole centres silently stop matching
  the Phase-2 datums — the single most common false "placement OK". This is the
  one helper here that needs the ``section`` extra (scipy + shapely).
* ``overhang_area()`` — downward-facing area past the support screen, using the
  SAME threshold as the preflight gate so the designer self-check and the gate
  can never disagree.

STL is a vertex soup with no connectivity, so watertightness and component count
are only meaningful after coincident vertices are merged. These helpers load via
``mesh_io.load_mesh`` (degenerate faces dropped, vertices merged) — the geometry
that prints. When a suspicious amount of merging matters, read the raw side and
mutation log through ``mesh_io.load_mesh_report`` directly.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import trimesh

from . import _bootstrap  # noqa: F401  (puts scripts/ on sys.path; keep first)

import mesh_io

# Matches the validated preflight support-screen margin (-sin(47deg)): an
# intended self-supporting 45deg chamfer tessellates to ~-0.7071 and must NOT be
# flagged; only overhangs steeper than ~47deg are counted. Keep in lockstep with
# team_preflight's downward_normal_z_max default.
DEFAULT_DOWNWARD_NORMAL_Z_MAX = -0.73


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


def _as_mesh(mesh_or_path: Any) -> trimesh.Trimesh:
    if isinstance(mesh_or_path, (str, Path)):
        return mesh_io.load_mesh(mesh_or_path)
    return mesh_or_path


def measure(mesh_or_path: Any) -> MeasureReport:
    m = _as_mesh(mesh_or_path)
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
            f"(mesh cross-section + ring extraction): pip install -e \".[section]\""
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
    m = _as_mesh(mesh_or_path)
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


def overhang_area(mesh_or_path: Any, *, threshold: float = DEFAULT_DOWNWARD_NORMAL_Z_MAX,
                  min_z: float = 0.3, transform=None) -> float:
    """Total downward-facing face area (mm^2) whose transformed normal Z is below
    ``threshold`` and which sits above ``min_z`` (bed-contact faces excluded).
    Pass the model-to-printer ``transform`` to screen in print orientation.
    ~0 for a support-free print.
    """
    m = _as_mesh(mesh_or_path)
    normals = m.face_normals
    centers = m.triangles_center
    if transform is not None:
        transform = np.asarray(transform, dtype=float)
        normals = normals @ transform[:3, :3].T
        centers = trimesh.transformations.transform_points(centers, transform)
    mask = (normals[:, 2] < threshold) & (centers[:, 2] > min_z)
    return float(m.area_faces[mask].sum())
