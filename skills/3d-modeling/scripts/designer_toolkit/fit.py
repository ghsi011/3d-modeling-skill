"""Interference and insertion-sweep on the exported meshes.

The boolean fit check the designer and verifier both run: does the seated
reference intersect the part (must be ~0 for a clearance interface), and does it
stay clear all the way in along the insertion axis? Runs on meshes — the
delivered geometry — not the CAD kernel, so the answer matches what prints.
Boolean overlap volume is the shared currency; the print engineer owns whether a
given interface is ALLOWED to interfere (interference/crush-rib/snap fits declare
a deliberately negative band).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import trimesh

from . import _bootstrap  # noqa: F401  (puts scripts/ on sys.path; keep first)

import mesh_io


def _as_mesh(m: Any) -> trimesh.Trimesh:
    # Boolean fit wants the merged/repaired mesh (a raw STL parse is a vertex
    # soup that booleans unreliably); this is the geometry that prints.
    if isinstance(m, (str, Path)):
        return mesh_io.load_mesh(m)
    return m


def _intersection_volume(a: trimesh.Trimesh, b: trimesh.Trimesh, engine=None) -> float:
    kw = {} if engine is None else {"engine": engine}
    inter = trimesh.boolean.intersection([a, b], **kw)
    if inter is None or inter.is_empty or len(inter.faces) == 0:
        return 0.0
    return float(abs(inter.volume))


def interference(a: Any, b: Any, *, engine=None) -> float:
    """Overlap volume (mm^3) of two meshes; 0.0 when disjoint."""
    return _intersection_volume(_as_mesh(a), _as_mesh(b), engine)


@dataclass(frozen=True)
class SweepStep:
    travel_mm: float
    interference_mm3: float
    blocked: bool


def insertion_sweep(part: Any, ref: Any, travels, *, axis=(0, 0, -1),
                    tol_mm3: float = 1e-3, engine=None) -> list:
    """Translate ``ref`` along ``axis`` by each value in ``travels`` and report
    the overlap volume with ``part`` at each step. ``blocked`` is True when the
    overlap exceeds ``tol_mm3`` — a clearance interface must stay unblocked the
    whole way in.
    """
    part_m = _as_mesh(part)
    ref_m = _as_mesh(ref)
    axis = np.asarray(axis, dtype=float)
    out: list = []
    for t in travels:
        moved = ref_m.copy()
        moved.apply_translation(axis * float(t))
        v = _intersection_volume(part_m, moved, engine)
        out.append(SweepStep(float(t), v, v > tol_mm3))
    return out
