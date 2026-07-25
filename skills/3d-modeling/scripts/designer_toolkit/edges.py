"""Measure fillet radii and chamfer legs on the exported mesh.

The v4 contract requires a measured radius per plan-named exposed edge, and the
toolkit did not provide one, so every designer run wrote its own. One then found
its instrument read high against known nominals and *widened its acceptance
bands to fit the instrument*. A measuring tool that ships with the gate is worth
more than a better tool the caller has to write.

Method: cut a section perpendicular to the edge and walk the outline through the
corner, accumulating the turn angle at each vertex. The three treatments are
distinguishable by how a corner's total turn is distributed, which is a property
of the shape rather than of a fitting heuristic:

    sharp    all of the turn at a single vertex
    chamfer  the turn split across two vertices with a straight run between
    fillet   the turn spread evenly across many vertices, all at one radius

Fitting a circle to everything inside a window does not work: the window also
contains the two straight walls, whose points outnumber the corner's and drag
the fitted radius to roughly twice nominal. The corner run must be isolated
first, and that is what the turn angles do.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import trimesh

from ._bootstrap import as_mesh  # noqa: F401  (also puts scripts/ on sys.path)

# A vertex turning less than this is on a straight run, not a corner. Section
# outlines carry tessellation jitter; this is comfortably above it.
_STRAIGHT_TURN_DEG = 1.5
# A single vertex taking this much of the turn is a hard corner, not an arc.
_HARD_CORNER_DEG = 20.0


@dataclass(frozen=True)
class EdgeMeasurement:
    """What was actually found where an edge was expected."""

    kind: Literal["fillet", "chamfer", "sharp", "indeterminate"]
    value_mm: float | None          # fillet radius, or chamfer leg length
    residual_mm: float | None       # RMS deviation from the fitted circle
    sample_count: int
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "value_mm": None if self.value_mm is None else round(self.value_mm, 4),
            "residual_mm": None if self.residual_mm is None else round(self.residual_mm, 5),
            "sample_count": self.sample_count,
            "detail": self.detail,
        }


def fit_circle(points: np.ndarray) -> tuple[float, float, float, float]:
    """Least-squares circle through 2-D points -> (cx, cy, radius, rms).

    Algebraic (Kasa) fit: linear, no starting guess, nothing to tune. The RMS is
    returned rather than discarded because it is the evidence that the points
    really were an arc.
    """
    points = np.asarray(points, dtype=float)
    x, y = points[:, 0], points[:, 1]
    design = np.column_stack([x, y, np.ones(len(points))])
    solution, *_ = np.linalg.lstsq(design, x**2 + y**2, rcond=None)
    cx, cy = solution[0] / 2.0, solution[1] / 2.0
    radius = float(np.sqrt(solution[2] + cx**2 + cy**2))
    rms = float(np.sqrt(np.mean((np.hypot(x - cx, y - cy) - radius) ** 2)))
    return float(cx), float(cy), radius, rms


def _densify(loop: np.ndarray, spacing: float) -> np.ndarray:
    """Resample a closed polyline at even spacing.

    A straight run carries no intermediate vertices, so a chamfer's face is two
    points and the turn walk has nothing to measure. Added points turn 0 deg, so
    this cannot dilute a hard corner: the whole turn stays on the one vertex
    that owns it, while the straight run in between becomes measurable.
    """
    out: list[np.ndarray] = []
    for start, end in zip(loop, np.roll(loop, -1, axis=0)):
        span = float(np.linalg.norm(end - start))
        for step in range(max(1, int(np.ceil(span / spacing)))):
            out.append(start + (end - start) * (step / max(1, int(np.ceil(span / spacing)))))
    return np.asarray(out)


def _outline_near(mesh: trimesh.Trimesh, origin, normal, corner, window: float):
    """The contiguous run of section-outline vertices around ``corner``."""
    section = mesh.section(plane_origin=np.asarray(origin, dtype=float),
                           plane_normal=np.asarray(normal, dtype=float))
    if section is None:
        return None
    planar, _ = section.to_2D(trimesh.geometry.plane_transform(origin, normal))
    best: np.ndarray | None = None
    best_distance = np.inf
    for entity in planar.entities:
        loop = np.asarray(entity.discrete(planar.vertices), dtype=float)
        distances = np.linalg.norm(loop - np.asarray(corner, dtype=float), axis=1)
        if distances.min() < best_distance:
            best_distance, best = float(distances.min()), loop
    if best is None or best_distance > window:
        return None
    # Roll the loop so the vertex nearest the corner is centred, then keep the
    # neighbourhood: a corner run is contiguous, and windowing on raw distance
    # would also pick up the far side of a thin wall.
    if np.allclose(best[0], best[-1]):
        best = best[:-1]
    best = _densify(best, spacing=window / 40.0)
    nearest = int(np.argmin(np.linalg.norm(best - np.asarray(corner, dtype=float), axis=1)))
    rolled = np.roll(best, -nearest, axis=0)
    keep = np.linalg.norm(rolled - rolled[0], axis=1) <= window
    forward = int(np.argmax(~keep)) if (~keep).any() else len(rolled)
    backward = int(np.argmax(~keep[::-1])) if (~keep).any() else 0
    return np.vstack([rolled[len(rolled) - backward:], rolled[:forward]])


def _turn_angles_deg(run: np.ndarray) -> np.ndarray:
    """Exterior turn angle at each interior vertex of a polyline."""
    incoming = run[1:-1] - run[:-2]
    outgoing = run[2:] - run[1:-1]
    incoming_angle = np.arctan2(incoming[:, 1], incoming[:, 0])
    outgoing_angle = np.arctan2(outgoing[:, 1], outgoing[:, 0])
    delta = np.degrees(outgoing_angle - incoming_angle)
    return np.abs((delta + 180.0) % 360.0 - 180.0)


def measure_edge(
    mesh_or_path: Any,
    corner_xy: tuple[float, float],
    *,
    section_origin=(0, 0, 0),
    section_normal=(0, 0, 1),
    window_mm: float = 4.0,
) -> EdgeMeasurement:
    """Measure the edge treatment nearest ``corner_xy`` on one section plane.

    ``corner_xy`` is where the edge would be if it were left sharp.
    ``window_mm`` must exceed the expected radius or leg and stay clear of
    neighbouring features.
    """
    mesh = as_mesh(mesh_or_path)
    run = _outline_near(mesh, section_origin, section_normal, corner_xy, window_mm)
    if run is None or len(run) < 3:
        return EdgeMeasurement("indeterminate", None, None, 0 if run is None else len(run),
                               "no section outline within the window at this plane")

    turns = _turn_angles_deg(run)
    turning = np.flatnonzero(turns > _STRAIGHT_TURN_DEG)
    if turning.size == 0:
        return EdgeMeasurement("indeterminate", None, None, len(run),
                               "outline is straight through the window: the corner is elsewhere")

    hard = np.flatnonzero(turns > _HARD_CORNER_DEG)
    if hard.size == 1:
        return EdgeMeasurement("sharp", 0.0, None, len(run),
                               f"a single vertex turns {turns[hard[0]]:.1f} deg: no material removed")
    if hard.size == 2:
        first, second = run[hard[0] + 1], run[hard[1] + 1]
        return EdgeMeasurement(
            "chamfer", float(np.linalg.norm(second - first)), None, len(run),
            f"two corners of {turns[hard[0]]:.1f} and {turns[hard[1]]:.1f} deg with a "
            "straight run between them",
        )

    arc = run[turning[0]: turning[-1] + 3]
    if len(arc) < 4:
        return EdgeMeasurement("indeterminate", None, None, len(run),
                               "too few points on the corner run to fit an arc")
    _cx, _cy, radius, rms = fit_circle(arc)
    return EdgeMeasurement(
        "fillet", radius, rms, len(arc),
        f"{len(arc)} points turning {turns[turning].sum():.0f} deg in total, "
        f"circle fit residual {rms:.4f} mm",
    )
