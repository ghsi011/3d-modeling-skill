"""Print-orientation search on the exported mesh.

Every designer run so far rediscovered the same answer by hand -- one wrote a
throwaway sweep script, two did it inline -- and all three arrived at the same
numbers, because it is a deterministic function of the mesh. It belongs here.

The screen is the same downward-normal test the preflight gate applies, so a
sweep result and a gate result cannot disagree about the same orientation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
import trimesh

from ._bootstrap import as_mesh  # noqa: F401  (also puts scripts/ on sys.path)

from .metrics import BARE_45_DEG, overhang_area  # noqa: E402

# The six axis-aligned placements plus the four 45-degree rolls about X. A part
# is almost always printed on a face or a natural diagonal; arbitrary angles
# trade a little overhang for a lot of bed-adhesion risk.
_CANDIDATES: tuple[tuple[str, tuple[float, float, float], float], ...] = (
    ("as-modelled", (1, 0, 0), 0.0),
    ("rot-x-90", (1, 0, 0), 90.0),
    ("rot-x-180", (1, 0, 0), 180.0),
    ("rot-x-270", (1, 0, 0), 270.0),
    ("rot-y-90", (0, 1, 0), 90.0),
    ("rot-y-270", (0, 1, 0), 270.0),
    ("rot-x-45", (1, 0, 0), 45.0),
    ("rot-y-45", (0, 1, 0), 45.0),
)


@dataclass(frozen=True)
class Placement:
    """One candidate orientation and what it costs."""

    name: str
    transform: np.ndarray
    overhang_mm2: float
    bed_contact_mm2: float
    height_mm: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "overhang_mm2": round(self.overhang_mm2, 3),
            "bed_contact_mm2": round(self.bed_contact_mm2, 3),
            "height_mm": round(self.height_mm, 3),
            "transform": [[round(float(v), 12) for v in row] for row in self.transform],
        }


def _seat_on_bed(mesh: trimesh.Trimesh, rotation: np.ndarray) -> np.ndarray:
    """Rotation, then the translation that drops the part onto z=0.

    Seating is not cosmetic. ``overhang_area`` ignores faces below ``min_z`` so
    that bed-contact faces are not counted as overhangs; a rotated-but-unseated
    part can sit below the bed plane entirely, and then every downward face is
    excluded and the placement scores a spurious near-zero. Rotation without
    translation is the wrong transform to screen with.
    """
    rotated = mesh.copy()
    rotated.apply_transform(rotation)
    drop = trimesh.transformations.translation_matrix((0, 0, -float(rotated.bounds[0][2])))
    return drop @ rotation


def _bed_contact_area(mesh: trimesh.Trimesh, transform: np.ndarray, tol: float = 0.05) -> float:
    """Face area sitting on the bed plane, i.e. what holds the print down."""
    placed = mesh.copy()
    placed.apply_transform(transform)
    z_min = float(placed.bounds[0][2])
    centres = placed.triangles_center
    normals = placed.face_normals
    on_bed = (centres[:, 2] <= z_min + tol) & (normals[:, 2] < -0.99)
    return float(placed.area_faces[on_bed].sum())


def sweep(
    mesh_or_path: Any,
    *,
    threshold: float = BARE_45_DEG,
    candidates: Iterable[tuple[str, tuple[float, float, float], float]] = _CANDIDATES,
) -> list[Placement]:
    """Score every candidate placement, best (least overhang) first.

    Ties on overhang break toward more bed contact: two orientations that both
    print support-free are not equal if one is standing on a postage stamp.
    """
    mesh = as_mesh(mesh_or_path)
    results: list[Placement] = []
    for name, axis, degrees in candidates:
        rotation = trimesh.transformations.rotation_matrix(np.radians(degrees), axis)
        transform = _seat_on_bed(mesh, rotation)
        placed = mesh.copy()
        placed.apply_transform(transform)
        results.append(
            Placement(
                name=name,
                transform=transform,
                overhang_mm2=overhang_area(mesh, threshold=threshold, transform=transform),
                bed_contact_mm2=_bed_contact_area(mesh, transform),
                height_mm=float(placed.extents[2]),
            )
        )
    return sorted(results, key=lambda p: (round(p.overhang_mm2, 3), -p.bed_contact_mm2))


def best(mesh_or_path: Any, *, threshold: float = BARE_45_DEG) -> Placement:
    return sweep(mesh_or_path, threshold=threshold)[0]
