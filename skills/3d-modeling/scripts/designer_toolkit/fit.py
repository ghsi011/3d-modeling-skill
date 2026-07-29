"""Static seated overlap/clearance on the exported meshes.

The primitive the designer and verifier can run at the seated position returns
boolean overlap volume on the delivered meshes, not the CAD kernel. It does not
perform an insertion/travel sweep and it does not decide whether overlap is
acceptable. Use this volume only with an explicit volumetric threshold such as
`assembly_overlap_budget_mm3`. Per-side clearance/transition/interference,
crush-rib, snap, or retention bands use `commission.seated_clearance_mm` instead.
Motion fit remains verifier-owned and is deferred/blocked when no motion check is
available.
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
