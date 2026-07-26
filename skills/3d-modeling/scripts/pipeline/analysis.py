#!/usr/bin/env python3
"""One mesh load per job, and every derived quantity computed once.

The old gate loaded the exported STL four times in a single commission and
recomputed bounds, normals and components on each pass. Nothing was wrong with
the answers; it just paid for them repeatedly, and a second load is also a second
chance for raw and normalized to diverge without anyone noticing which one a
given check used.

So both meshes are loaded here, once, and every check takes this object. `raw` is
parsed with no topology repair; `normalized` is the merged/repaired copy. Checks
that care about what was *exported* read `raw`; checks that need well-formed
topology read `normalized`; and the difference between them is itself reported,
because a repair that changed the geometry is a finding rather than a convenience.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import numpy as np
import trimesh

SLAB_MM = 0.02


@dataclasses.dataclass
class MeshAnalysisContext:
    path: Path
    raw: trimesh.Trimesh
    normalized: trimesh.Trimesh
    load_count: int
    repair_actions: tuple[str, ...]
    # Recorded, never escalated: see `load` for why the ratio is meaningless.
    vertex_merge: tuple[int, int] = (0, 0)
    _sections: dict[tuple, float] = dataclasses.field(default_factory=dict)
    _windows: dict[tuple, float] = dataclasses.field(default_factory=dict)

    @property
    def bounds(self) -> np.ndarray:
        return self.normalized.bounds

    @property
    def extents(self) -> np.ndarray:
        return self.normalized.extents

    @property
    def components(self) -> list[trimesh.Trimesh]:
        if not hasattr(self, "_components"):
            self._components = self.normalized.split(only_watertight=False)
        return self._components

    @property
    def face_normals(self) -> np.ndarray:
        return self.normalized.face_normals

    def section_area(self, z: float) -> float:
        """Material area on a Z plane, net of every hole, cached per height.

        Measured by intersecting a thin slab and dividing by its thickness. The
        obvious route is `mesh.section`, but that needs scipy, networkx, shapely
        and rtree, and the core path deliberately needs none of them -- a check
        that only runs on a full install is a check that does not run where parts
        are built.
        """
        key = ("z", round(float(z), 6))
        if key not in self._sections:
            self._sections[key] = self._slab_area(z)
        return self._sections[key]

    def _slab_area(self, z: float) -> float:
        span = float(max(self.extents)) * 4.0 + 10.0
        window = trimesh.creation.box(extents=(span, span, SLAB_MM))
        centre = self.normalized.centroid
        window.apply_translation([float(centre[0]), float(centre[1]), float(z)])
        solid = trimesh.boolean.intersection([self.normalized, window], engine="manifold")
        if solid is None or solid.is_empty:
            return 0.0
        return float(solid.volume) / SLAB_MM

    def window_area(self, *, z: float, at: tuple[float, float],
                    size: tuple[float, float]) -> float:
        """Material area inside one axis-aligned rectangle on a Z plane."""
        key = (round(z, 6), round(at[0], 6), round(at[1], 6), round(size[0], 6), round(size[1], 6))
        if key not in self._windows:
            window = trimesh.creation.box(extents=(float(size[0]), float(size[1]), SLAB_MM))
            window.apply_translation([float(at[0]), float(at[1]), float(z)])
            solid = trimesh.boolean.intersection([self.normalized, window], engine="manifold")
            self._windows[key] = 0.0 if solid is None or solid.is_empty else float(solid.volume) / SLAB_MM
        return self._windows[key]

    def disc_area(self, *, z: float, at: tuple[float, float], diameter: float) -> float:
        """Material area inside a disc on a Z plane, cached like the rest."""
        key = ("disc", round(z, 6), round(at[0], 6), round(at[1], 6), round(diameter, 6))
        if key not in self._windows:
            window = trimesh.creation.cylinder(radius=float(diameter) / 2.0,
                                               height=SLAB_MM, sections=192)
            window.apply_translation([float(at[0]), float(at[1]), float(z)])
            solid = trimesh.boolean.intersection([self.normalized, window], engine="manifold")
            self._windows[key] = (0.0 if solid is None or solid.is_empty
                                  else float(solid.volume) / SLAB_MM)
        return self._windows[key]

    def axis_profile(self, axis: int, samples: int, *, jitter: float = 0.0) -> list[dict[str, Any]]:
        """Material area along one axis, for the screening detectors.

        Jitter exists because a fixed grid is easy to be unlucky with: a small
        local defect can sit entirely between two evenly spaced planes and never
        appear. The offset is deterministic per job so a rerun samples the same
        places -- reproducibility matters more here than independence.
        """
        low, high = float(self.bounds[0][axis]), float(self.bounds[1][axis])
        if high <= low:
            return []
        step = (high - low) / samples
        rows = []
        for i in range(samples):
            at = low + (i + 0.5 + jitter) * step
            at = min(max(at, low + step * 0.05), high - step * 0.05)
            rows.append({"at": round(at, 4), "area_mm2": round(self._axis_area(axis, at), 3)})
        return rows

    def _axis_area(self, axis: int, at: float) -> float:
        if axis == 2:
            return self.section_area(at)
        span = float(max(self.extents)) * 4.0 + 10.0
        extents = [span, span, span]
        extents[axis] = SLAB_MM
        window = trimesh.creation.box(extents=tuple(extents))
        centre = list(self.normalized.centroid)
        centre[axis] = at
        window.apply_translation([float(v) for v in centre])
        solid = trimesh.boolean.intersection([self.normalized, window], engine="manifold")
        if solid is None or solid.is_empty:
            return 0.0
        return float(solid.volume) / SLAB_MM


def load(path: Path) -> MeshAnalysisContext:
    """Parse once, repair once, and report what the repair changed."""
    import mesh_io

    raw, integrity = mesh_io.load_mesh_raw(path)
    normalized = mesh_io.load_mesh(path)

    # Vertex merging is not a repair -- it is the STL format. Every file stores
    # three unshared vertices per triangle, so the merge ratio is about 6:1 on
    # every mesh ever exported (measured here: 3048 -> 508, faces and volume
    # unchanged, volume delta exactly 0). Escalating on it would fire on every
    # job, and an escalation that always fires is one nobody reads.
    #
    # What is worth escalating is geometry that changed: faces dropped as
    # degenerate, or a volume that moved.
    actions: list[str] = []
    if len(raw.faces) != len(normalized.faces):
        actions.append(f"dropped {len(raw.faces) - len(normalized.faces)} degenerate "
                       f"face(s): {len(raw.faces)} -> {len(normalized.faces)}")
    volume_delta = abs(float(raw.volume) - float(normalized.volume))
    if volume_delta > max(1e-6, 1e-9 * abs(float(raw.volume))):
        actions.append(f"volume moved by {volume_delta:.6g} mm3 during normalization")
    _ = integrity
    return MeshAnalysisContext(
        path=path, raw=raw, normalized=normalized, load_count=1,
        repair_actions=tuple(actions),
        vertex_merge=(len(raw.vertices), len(normalized.vertices)))
