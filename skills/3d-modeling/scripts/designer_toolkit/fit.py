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


def overlap_away_from(a: Any, b: Any, contacts: list[Any]) -> float:
    """Overlap volume (mm^3) of ``a`` and ``b`` that does *not* sit at any of the
    declared contact regions.

    A single total-overlap budget cannot tell an intended press/mating contact
    apart from a genuine collision somewhere else on the part: a crash hidden
    anywhere under the budget reads identically to the contact the budget was
    written to tolerate. Localising the overlap against the contact geometry --
    the meshes of the named interfaces the plan actually declares -- is what lets
    an away-from-interface collision be measured, and failed, on its own account.

    Returns the whole overlap when no contact regions are given (there is nothing
    to excuse it), and never a negative number.
    """
    inter = trimesh.boolean.intersection([as_mesh(a), as_mesh(b)])
    if inter is None or inter.is_empty or len(inter.faces) == 0:
        return 0.0
    total = float(abs(inter.volume))
    regions = [as_mesh(c) for c in contacts]
    if not regions:
        return total
    # Union first, then one intersection: summing per-region overlaps would
    # double-count anywhere two declared interfaces meet and so *under*-report
    # the stray overlap -- the one direction that could let a collision pass.
    contact = regions[0] if len(regions) == 1 else trimesh.boolean.union(regions)
    at_contact = _intersection_volume(inter, contact)
    return max(0.0, total - at_contact)
