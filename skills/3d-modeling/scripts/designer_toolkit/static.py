#!/usr/bin/env python3
"""Checks that need no geometry, so they cost no build.

Every measured designer dispatch spent most of its calls in one loop: change
`model.py`, export, measure, read a number, change it again. Some of what that
loop discovered was never geometric. It was arithmetic over numbers the model
already declared, and arithmetic does not need a CAD kernel.

The clearest case is on record. One run bisected its way to a working clearance
across four full build/export/measure cycles -- 0.15, 0.20, 0.25, 0.28, watching
interference fall 0.250, 0.063, 0.0076, 0.00055 mm3 -- against a cavity mouth
filleted at r = 0.30. The boundary it was searching for is closed form. A fillet
of radius r pulls the wall in by

    d(h) = r - sqrt(2rh - h^2),   0 <= h <= r

which is largest at the mouth plane, where d(0) = r. So the fillet's maximum
bite into a per-side clearance c is exactly `r - c`, and it is zero if and only
if `c >= r`. Four dispatches for one subtraction.

These run before the first CAD call and, unlike the rest of the gate, they can
be wrong only in the direction of the declared numbers -- if the model's
`PARAMS` do not describe what `build()` actually makes, that is a defect this
stage cannot see and the post-export checks will.
"""
from __future__ import annotations

import math
from typing import Any

from .verdict import FAIL, PASS, SKIP, Check

# The bare geometric floor: a wall thinner than two extrusion widths cannot be
# printed as two perimeters, and a single-perimeter wall is not a structure
# (fdm-design.md section 2, which sets 1.0 mm as the design rule at 0.4 mm).
MIN_WALL_NOZZLE_MULTIPLE = 2.0

# Two treatments of half the wall, one from each face, exactly meet: the wall is
# fully consumed at that corner. So half is the point of collapse, not a safe
# value -- and it is the exact ratio both archived Pixel runs shipped, 0.6 mm on
# a 1.2 mm wall.
MAX_EDGE_FRACTION_OF_WALL = 0.5


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return None if math.isnan(value) or math.isinf(value) else float(value)


def _nozzle_from_plan(plan: dict[str, Any]) -> float | None:
    for row in plan.get("process") or []:
        text = str(row.get("printer_material_nozzle", ""))
        for token in text.replace(";", " ").replace(",", " ").split():
            if token.endswith("mm"):
                value = _number(_to_float(token[:-2]))
                if value and 0.1 <= value <= 2.0:
                    return value
    return None


def _to_float(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def _check_wall(params: dict[str, Any], nozzle: float | None) -> Check | None:
    wall = _number(params.get("wall_mm"))
    if wall is None or nozzle is None:
        return None
    floor = MIN_WALL_NOZZLE_MULTIPLE * nozzle
    ok = wall + 1e-9 >= floor
    return Check(
        "static-wall", "Wall is printable at the planned nozzle",
        PASS if ok else FAIL,
        f"wall {wall} mm against a {floor:.2f} mm floor ({MIN_WALL_NOZZLE_MULTIPLE:g}x "
        f"the {nozzle} mm nozzle)",
        "" if ok else f"Thicken the wall to at least {floor:.2f} mm, or plan a smaller "
                      "nozzle. Below two extrusion widths there are no perimeters to bond.",
    )


def _check_cavity_fillet(params: dict[str, Any]) -> Check | None:
    """The four-dispatch bisection, as one subtraction."""
    radius = _number(params.get("cavity_mouth_fillet_mm"))
    clearance = _number(params.get("cavity_clearance_mm"))
    if radius is None or clearance is None:
        return None
    bite = radius - clearance
    ok = bite <= 1e-9
    return Check(
        "static-cavity-fillet", "Mouth fillet does not eat the cavity clearance",
        PASS if ok else FAIL,
        f"fillet r={radius} mm against a per-side clearance of {clearance} mm "
        f"(maximum bite {max(0.0, bite):.4f} mm at the mouth plane)",
        "" if ok else (
            f"A fillet pulls the wall in by its own radius at the mouth, so the clearance "
            f"must be at least {radius} mm -- raise the clearance to {radius} mm or drop the "
            f"fillet to {clearance} mm. Do not bisect toward it: the boundary is exact."
        ),
    )


def _check_edge_budget(params: dict[str, Any]) -> list[Check]:
    wall = _number(params.get("wall_mm"))
    treatments = params.get("edge_treatments")
    if wall is None or not isinstance(treatments, dict):
        return []
    budget = wall * MAX_EDGE_FRACTION_OF_WALL
    checks: list[Check] = []
    for edge_id, raw in sorted(treatments.items()):
        size = _number(raw)
        if size is None:
            continue
        ok = size < budget - 1e-9
        checks.append(Check(
            f"static-edge-{edge_id}", f"Edge {edge_id} leaves the wall standing",
            PASS if ok else FAIL,
            f"{size} mm treatment on a {wall} mm wall (must stay under {budget:g} mm)",
            "" if ok else f"A {size} mm treatment removes "
                          f"{100 * size / wall:.0f}% of a {wall} mm wall; two of them, one "
                          f"per face, would meet and leave nothing. Shrink it below "
                          f"{budget:g} mm or thicken the wall.",
        ))
    return checks


# A downward face is unsupported whatever the screen threshold, so any feature
# that necessarily has one cannot reach a ceiling of zero. Measured on a plain
# horizontal bore: 207 mm2 at the bare 45 deg screen, still 39 mm2 at -0.99.
_ROOFS_THAT_OVERHANG = {
    "round": "a round roof's crown faces straight down",
    "flat": "a flat roof faces straight down along its whole span",
}


def _check_unsupportable_features(params: dict[str, Any], plan: dict[str, Any]) -> list[Check]:
    """Features that cannot clear a zero ceiling, whatever the geometry around them.

    One measured run spent three full build/export/measure cycles learning that
    its horizontal bore had a crown -- 293 mm2, then 218 mm2, then a teardrop and
    zero. The bore's roof shape was known before the first build; only the
    consequence was not.
    """
    bores = params.get("horizontal_bores")
    if not isinstance(bores, list) or not bores:
        return []
    ceilings = [float(r.get("max_out_of_limit_area_mm2", 0.0))
                for r in (plan.get("support_rules") or [])]
    if not ceilings or min(ceilings) > 0:
        return []  # support is budgeted; a crown is affordable

    checks: list[Check] = []
    for index, bore in enumerate(bores):
        if not isinstance(bore, dict):
            continue
        bore_id = str(bore.get("id") or f"bore[{index}]")
        roof = str(bore.get("roof", "round")).lower()
        why = _ROOFS_THAT_OVERHANG.get(roof)
        if why is None:
            checks.append(Check(
                f"static-bore-{bore_id}", f"Bore {bore_id} can meet a zero support ceiling",
                PASS, f"roof '{roof}' is self-supporting"))
            continue
        checks.append(Check(
            f"static-bore-{bore_id}", f"Bore {bore_id} can meet a zero support ceiling",
            FAIL,
            f"a '{roof}' roof on a horizontal bore: {why}, so its area is above zero at "
            "every screen threshold and no surrounding geometry changes that",
            "The plan allows no unsupported area, so this bore cannot pass as drawn. Give "
            "it a teardrop or diamond roof, or -- if it has to stay round because something "
            "round passes through it -- say so in your handoff and let the print engineer "
            "budget support on a nonfunctional region. Do not iterate on the surrounding "
            "geometry: the crown belongs to the bore.",
        ))
    return checks


def _check_envelope_arithmetic(params: dict[str, Any], plan: dict[str, Any]) -> Check | None:
    """The declared size against the planned size, before anything is built.

    The post-export envelope check catches this too -- but only after a build,
    an export and a re-import. When the model already states its own overall
    size, the disagreement is visible for free.
    """
    stated = params.get("overall_mm")
    expected = plan.get("expected_bbox_mm")
    if not isinstance(stated, dict) or not isinstance(expected, dict):
        return None
    tolerance = _number(plan.get("bbox_tolerance_mm")) or 1.0
    worst_axis, worst = "", None
    for axis in ("x", "y", "z"):
        a, b = _number(stated.get(axis)), _number(expected.get(axis))
        if a is None or b is None:
            continue
        # `is None` rather than a zero start: an exact match is a comparison
        # that happened and passed, not one that never ran.
        if worst is None or abs(a - b) > abs(worst):
            worst_axis, worst = axis, a - b
    if worst is None:
        return None
    ok = abs(worst) <= tolerance
    return Check(
        "static-envelope", "Declared size matches the planned envelope",
        PASS if ok else FAIL,
        f"declared {worst_axis} is {worst:+.2f} mm from the plan (tolerance {tolerance} mm)",
        "" if ok else "The model's own parameters already disagree with the plan's "
                      "expected_bbox_mm. Settle which is right before building -- a build "
                      "cannot resolve it and will only cost an export to say the same thing.",
    )


def check(params: dict[str, Any] | None, plan: dict[str, Any]) -> list[Check]:
    """Everything decidable from declared numbers alone."""
    if not params:
        return [Check(
            "static", "Pre-build checks on declared parameters", SKIP,
            "the model declares no PARAMS",
            "Give model.py a PARAMS dict (wall_mm, cavity_clearance_mm, "
            "cavity_mouth_fillet_mm, edge_treatments, overall_mm, horizontal_bores) and "
            "these run before the first CAD call instead of after an export.",
        )]

    nozzle = _number(params.get("nozzle_mm")) or _nozzle_from_plan(plan)
    found = [
        _check_wall(params, nozzle),
        _check_cavity_fillet(params),
        _check_envelope_arithmetic(params, plan),
    ]
    checks = [c for c in found if c is not None]
    checks.extend(_check_edge_budget(params))
    checks.extend(_check_unsupportable_features(params, plan))
    if not checks:
        return [Check(
            "static", "Pre-build checks on declared parameters", SKIP,
            "PARAMS declares nothing these checks read",
            "Declare wall_mm, cavity_clearance_mm/cavity_mouth_fillet_mm, edge_treatments "
            "or overall_mm to have them checked before the build.",
        )]
    return checks
