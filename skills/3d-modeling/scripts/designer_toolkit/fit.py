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

from typing import Any

import trimesh

from ._bootstrap import as_mesh  # (also puts scripts/ on sys.path; keep first)


def _intersection_volume(a: trimesh.Trimesh, b: trimesh.Trimesh) -> float:
    inter = trimesh.boolean.intersection([a, b])
    if inter is None or inter.is_empty or len(inter.faces) == 0:
        return 0.0
    return float(abs(inter.volume))


def interference(a: Any, b: Any) -> float:
    """Overlap volume (mm^3) of two meshes; 0.0 when disjoint."""
    return _intersection_volume(as_mesh(a), as_mesh(b))
