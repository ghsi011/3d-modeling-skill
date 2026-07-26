"""Measure declared features against the solid, not against the model's own words.

Every scalar the gate had was identical across a correct `c_clip`, one with its
countersink deleted, and one whose mouth cutter had sliced a slot through the
flange: same bounding box, same watertight verdict, same component count, same
0.00 mm2 of overhang. Volume separates them by 0.9% and 6.4% -- the first is
under any usable envelope, and a countersink cut into the wrong face changes
volume not at all. Both defects reached a human, and one of them reached a human
who agreed with it and deleted a correct feature.

What separates them is a cut through the part. A section at flange mid-height
reads 864.14 mm2 on the good part against an intent of `40*22 - pi*2.25**2 =
864.10`, and 796.64 on the slotted one. The countersink shows as a mouth opening
from 4.50 to 8.59 mm over the top of the plate; its absence reads 4.50 mm at
every station.

Measured by intersecting the solid with a thin slab and dividing the resulting
volume by the slab thickness. The obvious route is `mesh.section`, but that
needs scipy, networkx, shapely and rtree, and the gate's core path deliberately
needs none of them -- a check that only runs on a full install is a check that
does not run where parts are actually built. The boolean kernel is already a
core dependency, and both routes agree to 0.04 mm2 on the same part.

The expectations may come from the template's own arithmetic or from the plan.
They may never come from a hand-maintained dict beside the model: that is the
party being measured setting its own threshold, and the check is worth something
only because the two derivations are independent. `40*22 - pi*2.25**2` is
untouched by the boolean bug that produced the slot, which is exactly why it
catches it.

The two sources catch different failures, and neither covers the other:

* A **template** expectation is derived from the caller's parameters, so it
  catches geometry that stopped matching them -- the archived case exactly, where
  the countersink was cut out of the template while every caller still asked for
  one. Verified: that regression fails here at 4.50 mm against a predicted 8.78.
* It cannot catch a feature nobody asked for. Drop `countersink_d` and the
  expectation disappears with the geometry, because one parameter drives both;
  the part is then self-consistently wrong and this module says nothing.
* A **plan** expectation is written upstream of the model from the sheet, so it
  survives the model omitting the feature. That is the only thing that catches a
  transcription that quietly lost a hole.
"""
from __future__ import annotations

import math
from typing import Any

from .verdict import FAIL as _FAIL
from .verdict import PASS as _PASS
from .verdict import Check

# Thin enough that a cone's taper across the slab is far below the diameter
# tolerance (a 90-degree countersink changes 0.02 mm across it), thick enough
# that the boolean stays well-conditioned.
SLAB_MM = 0.02
# A 192-gon window deficits 0.013% of its area; the smallest defect this exists
# to catch is 7.8%.
WINDOW_SECTIONS = 192

AREA_TOL_MM2 = 1.0
AREA_TOL_FRAC = 0.005
DIAMETER_TOL_MM = 0.12
DIAMETER_TOL_FRAC = 0.01

KINDS = ("solid_region", "bed_footprint", "through_hole", "countersink")


def area_tolerance(expected: float) -> float:
    return max(AREA_TOL_MM2, AREA_TOL_FRAC * abs(expected))


def diameter_tolerance(expected: float) -> float:
    return max(DIAMETER_TOL_MM, DIAMETER_TOL_FRAC * abs(expected))


class Indeterminate(Exception):
    """The measurement window does not sit where the reading would mean anything."""


def _slab_volume(mesh: Any, window: Any) -> float:
    import trimesh
    solid = trimesh.boolean.intersection([mesh, window])
    if solid is None or solid.is_empty:
        return 0.0
    return float(solid.volume)


def solid_area_mm2(mesh: Any, z: float, *, thickness: float = SLAB_MM) -> float:
    """Material area on a Z plane, net of every hole through it.

    An empty slab returns 0.0 rather than raising, which reads as a loud
    disagreement with the expected area instead of a silent skip.
    """
    import trimesh
    span = float(max(mesh.extents)) * 4.0 + 10.0
    window = trimesh.creation.box(extents=(span, span, thickness))
    window.apply_translation([float(mesh.centroid[0]), float(mesh.centroid[1]), z])
    return _slab_volume(mesh, window) / thickness


def _void_area_mm2(mesh: Any, x: float, y: float, z: float, radius: float,
                   *, thickness: float = SLAB_MM) -> float:
    import trimesh
    window = trimesh.creation.cylinder(radius=radius, height=thickness,
                                       sections=WINDOW_SECTIONS)
    window.apply_translation([x, y, z])
    material = _slab_volume(mesh, window) / thickness
    return math.pi * radius * radius - material


def bore_diameter_mm(mesh: Any, x: float, y: float, z: float, radius: float) -> float:
    """Diameter of the void at (x, y), from the material missing around it.

    Measured at two radii and cross-checked. The void inside a window is
    invariant to the window's size only while the window is wholly buried in
    material; if it overhangs the part's edge, the two readings diverge and the
    number means nothing. Without that check a window hanging off the side of a
    flange reports a confident diameter computed mostly from fresh air.
    """
    wide = _void_area_mm2(mesh, x, y, z, radius)
    narrow = _void_area_mm2(mesh, x, y, z, radius * 0.8)
    if abs(wide - narrow) > max(0.5, 0.02 * math.pi * radius * radius):
        raise Indeterminate(
            f"window at ({x:.2f}, {y:.2f}, {z:.2f}) is not buried in material: "
            f"r={radius:.2f} implies {wide:.2f} mm2 of void, r={radius * 0.8:.2f} "
            f"implies {narrow:.2f}")
    return 2.0 * math.sqrt(max(wide, 0.0) / math.pi)


def _countersink_stations(row: dict) -> list[tuple[float, float]]:
    """Predicted (z, diameter) down a countersunk hole.

    Closed form, not a curve fit: a cone of included angle `t` opening from the
    shaft to the head spans (head - shaft) / (2 tan(t/2)), and the mouth is the
    head diameter at the face. Predicted 8.6 at z=4.8 and 7.0 at z=4.0 for the
    catalogue clip; measured 8.59 and 7.00.
    """
    shaft, head = float(row["shaft_d"]), float(row["head_d"])
    face_z, angle = float(row["face_z"]), float(row.get("included_angle", 90.0))
    if head <= shaft:
        raise ValueError(f"head_d {head} must exceed shaft_d {shaft}")
    half = math.tan(math.radians(angle) / 2.0)
    depth = (head - shaft) / (2.0 * half)
    sign = -1.0 if str(row.get("from_face", "+z")) == "+z" else 1.0
    stations = [(face_z + sign * f * depth, head - 2.0 * f * depth * half)
                for f in (0.05, 0.35, 0.65)]
    stations.append((face_z + sign * depth * 1.6, shaft))
    return stations


def _check_solid_region(mesh: Any, row: dict) -> Check:
    ident = row.get("id", "solid_region")
    expected = float(row["area_mm2"])
    tolerance = float(row.get("tol_mm2") or area_tolerance(expected))
    z = float(row["z"])
    measured = solid_area_mm2(mesh, z)
    delta = measured - expected
    detail = f"{measured:.2f} mm2 at z={z:.2f}, expected {expected:.2f} +/- {tolerance:.2f}"
    if abs(delta) <= tolerance:
        return Check(f"feature-{ident}", "Section area", _PASS, detail)
    return Check(
        f"feature-{ident}", "Section area", _FAIL, f"{detail} (off by {delta:+.2f})",
        "Material is missing from this plane, or there is more of it than the part "
        "is meant to have. A cutter larger than the feature it was cutting is the "
        "usual cause. Do not widen the tolerance to admit the measurement.",
    )


def _check_bed_footprint(row: dict, bed_contact_mm2: float | None) -> Check:
    ident = row.get("id", "bed_footprint")
    expected = float(row["area_mm2"])
    tolerance = float(row.get("tol_mm2") or area_tolerance(expected))
    if bed_contact_mm2 is None:
        return Check(f"feature-{ident}", "Bed contact area", _FAIL,
                     "no placement was computed, so there is no contact area to check",
                     "The plan declares a bed footprint; the gate must reach a placement "
                     "before it can be measured.")
    delta = bed_contact_mm2 - expected
    detail = f"{bed_contact_mm2:.2f} mm2, expected {expected:.2f} +/- {tolerance:.2f}"
    if abs(delta) <= tolerance:
        return Check(f"feature-{ident}", "Bed contact area", _PASS, detail)
    return Check(
        f"feature-{ident}", "Bed contact area", _FAIL, f"{detail} (off by {delta:+.2f})",
        "The face meeting the bed is not the size the part says it is: either it is "
        "the wrong face, or material is missing from it.",
    )


def _check_hole(mesh: Any, row: dict) -> Check:
    """One predicate for a plain bore and for a countersunk one.

    A through hole is a countersink whose stations all read the same diameter, so
    the only difference is which profile gets predicted -- and reading 4.50 mm
    where 9.00 was declared is precisely how a deleted countersink announces
    itself.
    """
    ident = row.get("id", row["kind"])
    x, y = float(row["at"][0]), float(row["at"][1])
    if row["kind"] == "countersink":
        stations = _countersink_stations(row)
        largest = float(row["head_d"])
        label = f"Countersink {float(row['shaft_d']):.2f} -> {largest:.2f} mm"
    else:
        diameter = float(row["d_mm"])
        z0, z1 = float(row["z_from"]), float(row["z_to"])
        stations = [(z0 + f * (z1 - z0), diameter) for f in (0.1, 0.5, 0.9)]
        largest = diameter
        label = f"Bore {diameter:.2f} mm"
    # The window has to enclose the hole at *both* radii the cross-check uses, or
    # it reports indeterminate on a perfectly good part. The old default added a
    # flat 1.5 mm, which holds for an M5 and fails from about 12 mm up: the
    # narrow window, at 0.8 of the wide one, lands inside the hole itself. Scaled
    # instead, so the margin grows with the feature.
    radius = float(row.get("window_r") or largest * 0.7)

    problems = []
    for z, expected in stations:
        try:
            measured = bore_diameter_mm(mesh, x, y, z, radius)
        except Indeterminate as exc:
            return Check(
                f"feature-{ident}", label, _FAIL, str(exc),
                "Declare a smaller `window_r` that stays inside the material, or "
                "correct the position: a reading taken partly outside the part is "
                "not a measurement of the hole.")
        tolerance = diameter_tolerance(expected)
        if abs(measured - expected) > tolerance:
            problems.append(f"z={z:.2f}: {measured:.2f} mm, expected {expected:.2f} "
                            f"+/- {tolerance:.2f}")

    if not problems:
        return Check(f"feature-{ident}", label, _PASS,
                     f"{len(stations)} stations along the axis all within tolerance")
    return Check(
        f"feature-{ident}", label, _FAIL, "; ".join(problems),
        "The hole is not the shape it was declared to be. A cylindrical mouth where "
        "a countersink was declared means the countersink is not in the solid, "
        "whatever the model file says.",
    )


def slice_profile(mesh: Any, *, slices: int = 28) -> list[dict[str, float]]:
    """Material area at evenly spaced heights, declared by nobody.

    Every check in this module is conditioned on somebody having named a feature.
    This is not: it walks the whole part at a fixed pitch and reports what is
    there. On the two defects this pipeline has shipped it is unmissable -- the
    deleted countersink moves four consecutive slices by up to 40.8 mm2, the
    slotted flange moves ten by up to 67.5 -- and neither defect had to be
    anticipated for that to happen.

    It is **evidence, not a verdict**, and the distinction is not modesty. To
    turn a curve into a pass/fail you need the curve the part should have had,
    and the only thing that can produce it is the template that produced the
    part -- so the comparison would be against itself. What it is good for is
    the thing a scalar cannot do: showing a reader the whole part at once, so a
    step or a flat where the shape should have been smooth is visible without
    anyone having predicted it. Put it in front of whoever is doing the looking.

    28 slices on a 1500-face part costs 0.14 s.
    """
    low, high = float(mesh.bounds[0][2]), float(mesh.bounds[1][2])
    if high <= low:
        return []
    step = (high - low) / slices
    return [{"z": round(low + (i + 0.5) * step, 4),
             "area_mm2": round(solid_area_mm2(mesh, low + (i + 0.5) * step), 3)}
            for i in range(slices)]


def check_features(mesh: Any, rows, *, bed_contact_mm2: float | None = None) -> list[Check]:
    """Every declared feature measured, with an unknown kind a failure.

    Not a skip: a plan naming a feature this module cannot measure is a plan whose
    author believed something was being checked. Saying so is the whole point of
    the row.
    """
    checks: list[Check] = []
    for row in rows or ():
        kind = row.get("kind")
        ident = row.get("id", kind or "feature")
        try:
            if kind == "solid_region":
                checks.append(_check_solid_region(mesh, row))
            elif kind == "bed_footprint":
                checks.append(_check_bed_footprint(row, bed_contact_mm2))
            elif kind in ("through_hole", "countersink"):
                checks.append(_check_hole(mesh, row))
            else:
                checks.append(Check(
                    f"feature-{ident}", f"Feature kind {kind!r}", _FAIL,
                    f"unknown feature kind {kind!r}",
                    f"Measurable kinds are: {', '.join(KINDS)}. A kind nobody measures "
                    "is a declaration that reads as a check and is not one."))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            checks.append(Check(
                f"feature-{ident}", f"Feature {ident}", _FAIL,
                f"malformed feature row: {exc}",
                "Fix the declaration; a row the gate cannot read checks nothing."))
    return checks
