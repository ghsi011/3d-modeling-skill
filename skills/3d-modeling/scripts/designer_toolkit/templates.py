#!/usr/bin/env python3
"""Parametric starting points that know their own topology.

The measured cost of a designer dispatch is authoring: one archived phone case
was 531 lines of hand-written Python. But the reason to have templates is not
that they save typing -- it is that a hand-written model cannot be *asked*
anything. The pre-build stage can only check numbers the model declares, and a
model assembled ad hoc declares whatever its author remembered to declare.

A template returns its parameters alongside its geometry, computed from the same
arithmetic that built the solid. So `wall_mm` is the wall that exists,
`overall_mm` is the size the part actually came out, and neither can drift from
the geometry the way a hand-maintained `PARAMS` dict can.

Backend-neutral on purpose: these build with trimesh and manifold booleans, so
they work with no CAD kernel installed and the result feeds `commission`
unchanged. Where a part needs kernel-only features (true fillets, lofts,
threads), write it in the commissioned backend -- and populate `PARAMS`
yourself.

    from designer_toolkit.templates import box_shell
    built = box_shell(inner=(120, 80, 60), wall=3.0, floor=3.0)
    part, PARAMS = built.part, built.params
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import trimesh


@dataclass(frozen=True)
class Built:
    """Geometry plus everything a check would otherwise have to be told."""

    part: Any
    params: dict[str, Any]
    reference: Any | None = None
    notes: tuple[str, ...] = ()
    # What the solid must measure, derived from the caller's numbers rather than
    # from the solid. The independence is the whole value: the mouth-cutter bug
    # changed the boolean result and left `fw * fd - pi * r**2` untouched, so the
    # two disagreed by 67 mm2. An expectation measured off the part it is
    # checking would have agreed with the defect.
    expected: tuple[dict[str, Any], ...] = ()


def _seated(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Drop a solid onto z=0.

    Templates always return a part resting on the bed, because that is the
    convention the plan's identity model-to-printer transform assumes. A part
    centred on the origin has half of itself below the bed and every downward
    face reads as unsupported.
    """
    mesh.apply_translation((0.0, 0.0, -float(mesh.bounds[0][2])))
    return mesh


def _cylinder(radius: float, height: float, centre) -> trimesh.Trimesh:
    mesh = trimesh.creation.cylinder(radius=radius, height=height, sections=48)
    mesh.apply_translation(centre)
    return mesh


def _frustum(r_bottom: float, r_top: float, height: float, centre, sections: int = 64):
    """A truncated cone, built from two rings rather than a tapered cylinder.

    A full cone's apex tessellates into slivers that survive in memory and then
    fail the watertight check on re-import. A countersink meets its own shaft at
    a finite radius, so the apex was never part of the shape anyway.
    """
    angles = np.linspace(0.0, 2.0 * np.pi, sections, endpoint=False)
    cx, cy, cz = centre
    lower = np.column_stack([cx + r_bottom * np.cos(angles), cy + r_bottom * np.sin(angles),
                             np.full(sections, cz)])
    upper = np.column_stack([cx + r_top * np.cos(angles), cy + r_top * np.sin(angles),
                             np.full(sections, cz + height)])
    vertices = np.vstack([lower, upper, [[cx, cy, cz], [cx, cy, cz + height]]])
    low_c, high_c = 2 * sections, 2 * sections + 1
    faces = []
    for i in range(sections):
        j = (i + 1) % sections
        faces.append([i, j, sections + j])
        faces.append([i, sections + j, sections + i])
        faces.append([low_c, j, i])                      # bottom cap, facing down
        faces.append([high_c, sections + i, sections + j])  # top cap, facing up
    return trimesh.Trimesh(vertices=vertices, faces=np.array(faces), process=True)


def _cut_with(part: trimesh.Trimesh, cuts: list[trimesh.Trimesh]) -> trimesh.Trimesh:
    """Subtract several solids, unioning them first.

    `concatenate` glues meshes into one non-manifold soup, which the boolean
    silently mishandles when the pieces overlap -- a countersink cone crossing
    its own shaft removed nothing at all, and read as 18 mm2 of phantom
    downward-facing area. Union them and both problems go away.
    """
    if not cuts:
        return part
    solid = cuts[0] if len(cuts) == 1 else trimesh.boolean.union(cuts)
    return trimesh.boolean.difference([part, solid])


def _box(extents, centre) -> trimesh.Trimesh:
    mesh = trimesh.creation.box(extents=extents)
    mesh.apply_translation(centre)
    return mesh


def box_shell(*, inner: tuple[float, float, float], wall: float, floor: float = 0.0,
              open_top: bool = True) -> Built:
    """A walled box: hive body, enclosure, tray, drawer.

    ``inner`` is the usable cavity. The outer size follows from it and the wall,
    so the two can never disagree.
    """
    if wall <= 0:
        raise ValueError(f"wall must be positive, got {wall}")
    if min(inner) <= 0:
        raise ValueError(f"inner extents must be positive, got {inner}")
    if floor < 0:
        raise ValueError(f"floor must not be negative, got {floor}")

    iw, id_, ih = (float(v) for v in inner)
    # A closed box needs material above the cavity; an open one does not. Sizing
    # both the same way left `open_top=False` with its cavity breaking the top
    # surface -- a lid that was not there, and identical volumes either way.
    lid = 0.0 if open_top else wall
    outer = (iw + 2 * wall, id_ + 2 * wall, floor + ih + lid)
    shell = _box(outer, (outer[0] / 2, outer[1] / 2, outer[2] / 2))
    # The cavity is cut tall enough to break the top surface when the box is
    # open; a closed box keeps its lid.
    cavity_height = ih + (wall if open_top else 0.0)  # overshoot to break the top
    cavity = _box((iw, id_, cavity_height),
                  (outer[0] / 2, outer[1] / 2, floor + cavity_height / 2))
    part = _seated(trimesh.boolean.difference([shell, cavity]))

    # The wall ring, in closed form: the footprint less the cavity it encloses.
    # A cavity cut larger than it should be, or a wall that silently thinned,
    # changes this and changes nothing else the gate measures -- the bounding box
    # is set by the outside, and a box stays watertight and single-bodied either
    # way. Sampled inside the cavity, where the ring is all that is left.
    footprint = float(outer[0]) * float(outer[1])
    ring = footprint - float(iw) * float(id_)
    expected: list[dict[str, Any]] = [
        {"kind": "solid_region", "id": "wall-ring",
         "z": float(floor) + float(ih) / 2.0, "area_mm2": ring},
        # The ring is one scalar for the whole section, so anything that thins a
        # wall pays for something standing inside the box. This reads the cavity
        # alone: `inner` is what the caller asked to be able to put things in,
        # and nothing may be in the way of it.
        {"kind": "void_region", "id": "cavity",
         "z": float(floor) + float(ih) / 2.0,
         "at": (outer[0] / 2.0, outer[1] / 2.0), "size_mm": (float(iw), float(id_))},
        # With a floor the part meets the bed on solid material; without one it
        # meets it on the ring, and confusing the two is how a part gets printed
        # upside down without anything noticing.
        {"kind": "bed_footprint", "area_mm2": footprint if floor > 0 else ring},
    ]

    return Built(
        part=part,
        expected=tuple(expected),
        params={
            "wall_mm": float(wall),
            "overall_mm": {"x": float(outer[0]), "y": float(outer[1]), "z": float(outer[2])},
        },
        notes=(f"cavity {iw} x {id_} x {ih} mm inside a {wall} mm wall"
               + (f" on a {floor} mm floor" if floor else "")
               + ("" if open_top else f" under a {wall} mm lid"),),
    )


def _check_opening(opening: dict[str, Any], index: int, width: float, depth: float) -> None:
    """Refuse an opening that cannot mean what it says.

    Every case here was reproduced returning a wrong answer rather than an
    error: a negative diameter cut a hole of its absolute size *and* computed an
    expectation from the square of it, so the two agreed and the gate passed; an
    opening hanging off the edge produced `wall_mm = -15.0` and surfaced three
    steps later as "wall -15.0 mm against a 0.80 mm floor", which describes a
    placement mistake as a thickness one; and an opening larger than the panel
    removed the whole plate, leaving a boolean result whose bounds are None and
    a TypeError from deep inside the seating helper.
    """
    kind = opening.get("kind", "rect")
    x, y = float(opening["x"]), float(opening["y"])
    if kind == "round":
        diameter = float(opening["d"])
        if diameter <= 0:
            raise ValueError(f"opening {index}: diameter must be positive, got {diameter}")
        half_w = half_h = diameter / 2.0
    else:
        w, h = float(opening["w"]), float(opening["h"])
        if min(w, h) <= 0:
            raise ValueError(f"opening {index}: width and height must be positive, got {w} x {h}")
        half_w, half_h = w / 2.0, h / 2.0
    if not (0.0 <= x - half_w and x + half_w <= width
            and 0.0 <= y - half_h and y + half_h <= depth):
        raise ValueError(
            f"opening {index} at ({x}, {y}) reaches outside the {width} x {depth} mm panel; "
            "an opening that is not contained by the plate is a placement error, and the "
            "wall report downstream will describe it as a negative thickness")


def _opening_solid(opening: dict[str, Any], thickness: float) -> trimesh.Trimesh:
    kind = opening.get("kind", "rect")
    x, y = float(opening["x"]), float(opening["y"])
    tall = thickness * 3.0
    if kind == "round":
        diameter = float(opening["d"])
        cut = trimesh.creation.cylinder(radius=diameter / 2.0, height=tall, sections=64)
        cut.apply_translation((x, y, 0.0))
        return cut
    return _box((float(opening["w"]), float(opening["h"]), tall), (x, y, 0.0))


def _half_extents(opening: dict[str, Any]) -> tuple[float, float]:
    if opening.get("kind") == "round":
        radius = float(opening["d"]) / 2.0
        return radius, radius
    return float(opening["w"]) / 2.0, float(opening["h"]) / 2.0


def _min_ligament(openings, width: float, depth: float) -> float | None:
    """The narrowest material left anywhere in the panel.

    Openings placed close together leave a rib too thin to print, and nothing
    downstream measures it: the mesh is watertight, the envelope is right, and
    the part is a sieve with no ribs between the holes. Computed here because
    the template knows where every opening is; a hand-written panel would have
    to be asked, and could not answer.

    Axis-aligned bounding boxes, so a round opening is treated as its square --
    the number this returns is a lower bound on the true ligament, which is the
    safe direction for a check.
    """
    if not openings:
        return None
    gaps: list[float] = []
    boxes = []
    for opening in openings:
        hx, hy = _half_extents(opening)
        x, y = float(opening["x"]), float(opening["y"])
        boxes.append((x - hx, x + hx, y - hy, y + hy))
        gaps.extend([x - hx, width - (x + hx), y - hy, depth - (y + hy)])

    for index, (ax0, ax1, ay0, ay1) in enumerate(boxes):
        for bx0, bx1, by0, by1 in boxes[index + 1:]:
            dx = max(bx0 - ax1, ax0 - bx1)
            dy = max(by0 - ay1, ay0 - by1)
            if dx >= 0 or dy >= 0:
                # Separated on at least one axis; the gap is the larger
                # separation, since overlapping on the other axis means the
                # material between them is exactly that distance.
                gaps.append(max(dx, dy))
            else:
                gaps.append(0.0)  # they overlap: no material between them at all
    return min(gaps) if gaps else None


def area_tolerance_for(total: float, features: list[float]) -> float:
    """A band the whole plate can move within, that one feature cannot hide in.

    The default area tolerance is a fraction of what is being measured, which is
    right for a single region and wrong for a plate full of holes: half a percent
    of 60,000 mm2 is 300, and four M5 holes come to 78. Whichever is smaller
    wins, with a floor so tessellation noise still passes.
    """
    band = max(1.0, 0.005 * abs(total))
    if features:
        band = min(band, max(1.0, 0.25 * min(features)))
    return band


def panel(*, width: float, depth: float, thickness: float,
          openings: tuple[dict[str, Any], ...] = ()) -> Built:
    """A flat plate with openings: hive window, screen board, bottom board, lid.

    Each opening is ``{"kind": "rect", "x", "y", "w", "h"}`` or
    ``{"kind": "round", "x", "y", "d"}``, positioned by its centre in panel
    coordinates with the origin at the panel's near corner.
    """
    if min(width, depth, thickness) <= 0:
        raise ValueError(f"panel extents must be positive, got {(width, depth, thickness)}")
    for index, opening in enumerate(openings, start=1):
        _check_opening(opening, index, float(width), float(depth))

    plate = _box((width, depth, thickness), (width / 2, depth / 2, thickness / 2))
    if openings:
        cuts = [_opening_solid(o, thickness) for o in openings]
        for cut in cuts:
            cut.apply_translation((0.0, 0.0, thickness / 2))
        plate = _cut_with(plate, cuts)
    part = _seated(plate)

    ligament = _min_ligament(openings, width, depth)
    params: dict[str, Any] = {
        "overall_mm": {"x": float(width), "y": float(depth), "z": float(thickness)},
    }
    notes: list[str] = []
    if ligament is not None:
        # The thinnest remaining material *is* the panel's wall, and calling it
        # that is what puts it in front of the pre-build wall check.
        params["wall_mm"] = float(min(ligament, thickness))
        notes.append(f"narrowest material between openings/edges is {ligament:.2f} mm")
    else:
        params["wall_mm"] = float(thickness)

    # Plate area less every hole cut in it. This is the number that catches an
    # opening at the wrong size, a duplicate opening, or a cutter that took more
    # than its own footprint -- none of which move the bounding box.
    areas = [math.pi * (float(o["d"]) / 2.0) ** 2 if o.get("kind") == "round"
             else float(o["w"]) * float(o["h"]) for o in openings]
    plate = float(width) * float(depth) - sum(areas)

    # A tolerance scaled off the plate is no tolerance at all for one opening.
    # The default is half a percent of the *total*, which on a 300 x 200 panel is
    # 299 mm2 -- so four M5 holes, 78 mm2 of material between them, could be
    # missing entirely and land inside it. Bound it by a quarter of the smallest
    # feature declared, so no single opening can hide in the whole-plate number.
    tol = area_tolerance_for(plate, areas)
    plate_rows: list[dict[str, Any]] = [
        {"kind": "solid_region", "id": "plate-mid", "z": float(thickness) / 2.0,
         "area_mm2": plate, "tol_mm2": tol},
        {"kind": "bed_footprint", "area_mm2": plate, "tol_mm2": tol},
    ]
    # Round openings get measured individually as well: an area can be right in
    # total while a hole is in the wrong place or the wrong size, and a bolt does
    # not care about the total.
    for index, opening in enumerate(openings, start=1):
        if opening.get("kind") == "round":
            plate_rows.append({
                "kind": "through_hole", "id": f"hole-{index:02d}",
                "at": (float(opening["x"]), float(opening["y"])),
                "d_mm": float(opening["d"]), "z_from": 0.0, "z_to": float(thickness)})
    return Built(part=part, params=params, notes=tuple(notes),
                 expected=tuple(plate_rows))


def _rounded_slab(width: float, depth: float, height: float, radius: float,
                  centre=(0.0, 0.0, 0.0)) -> trimesh.Trimesh:
    """A rectangular prism with rounded vertical corners.

    Two crossed boxes unioned with four corner cylinders -- not a convex hull,
    which would need scipy, and not a fillet, which would need a CAD kernel.
    These templates run on a lean install by design.
    """
    radius = max(1e-6, min(radius, width / 2 - 1e-6, depth / 2 - 1e-6))
    pieces = [
        _box((width - 2 * radius, depth, height), (0.0, 0.0, 0.0)),
        _box((width, depth - 2 * radius, height), (0.0, 0.0, 0.0)),
    ]
    for sx in (-1, 1):
        for sy in (-1, 1):
            post = trimesh.creation.cylinder(radius=radius, height=height, sections=48)
            post.apply_translation((sx * (width / 2 - radius), sy * (depth / 2 - radius), 0.0))
            pieces.append(post)
    slab = trimesh.boolean.union(pieces)
    slab.apply_translation(centre)
    return slab


def _rounded_area(width: float, length: float, radius: float) -> float:
    """Plan area of a rounded rectangle, clamped the same way the solid is.

    `_rounded_slab` silently caps the radius at half the shorter side, so an
    expectation computed from the requested radius would disagree with the part
    over a value the geometry never used.
    """
    r = min(float(radius), float(width) / 2.0, float(length) / 2.0)
    return float(width) * float(length) - (4.0 - math.pi) * r * r


def device_case(*, device: tuple[float, float, float], wall: float, clearance: float,
                corner_radius: float = 8.0,
                openings: tuple[dict[str, Any], ...] = ()) -> Built:
    """A shelled wrap around a slab device: phone case, remote sleeve, boot.

    The mating reference comes back with it, built from the same numbers -- which
    is the whole point. Two archived runs each hand-wrote a thirty-to-sixty line
    device proxy beside their case, and one of them debugged a false interference
    caused by forgetting to round the proxy's corners. A proxy derived from the
    same arithmetic cannot describe a different device from the cavity.

    ``openings`` cut through the back, positioned by centre in case coordinates
    with the origin at the case's centre: ``{"x", "y", "w", "h"}``.
    """
    if wall <= 0 or clearance < 0:
        raise ValueError(f"wall must be positive and clearance non-negative, "
                         f"got {wall} and {clearance}")
    dw, dl, dt = (float(v) for v in device)
    if min(dw, dl, dt) <= 0:
        raise ValueError(f"device extents must be positive, got {device}")
    if corner_radius < 0:
        raise ValueError(f"corner_radius must not be negative, got {corner_radius}")
    if clearance < 0:
        raise ValueError(f"clearance must not be negative, got {clearance}")

    outer_w = dw + 2 * (clearance + wall)
    outer_l = dl + 2 * (clearance + wall)
    outer_t = dt + 2 * clearance + wall
    outer = _rounded_slab(outer_w, outer_l, outer_t, corner_radius + clearance + wall,
                          centre=(0.0, 0.0, outer_t / 2))

    # The cavity breaks the top face, so the device drops in from +Z.
    cavity_t = dt + 2 * clearance + wall
    cavity = _rounded_slab(dw + 2 * clearance, dl + 2 * clearance, cavity_t,
                           corner_radius + clearance,
                           centre=(0.0, 0.0, wall + cavity_t / 2))
    part = trimesh.boolean.difference([outer, cavity])

    if openings:
        part = _cut_with(part, [
            _box((float(o["w"]), float(o["h"]), outer_t * 3),
                 (float(o["x"]), float(o["y"]), 0.0)) for o in openings])
    part = _seated(part)

    # `clearance` is per-side and that includes underneath. A device resting
    # flush on the cavity floor touches it, so the assembly's tightest point is
    # zero however correct the walls are -- an archived run met the same wall and
    # hand-added a relief gap to get past it. Holding the clearance uniform in
    # every direction is the honest version of that fix, and it is what "per-side
    # clearance" already means.
    reference = _rounded_slab(dw, dl, dt, corner_radius,
                              centre=(0.0, 0.0, wall + clearance + dt / 2))
    # The cavity is the part. Everything else -- bounding box, watertightness,
    # body count, bed contact, overhang -- is identical whether the device drops
    # in or jams, so a case cut 0.75 mm per side undersize passed every check
    # this gate had. Both areas are closed form from the caller's numbers: the
    # outer slab, and the wall ring left once the cavity is taken out of it.
    outer_area = _rounded_area(outer_w, outer_l, corner_radius + clearance + wall)
    cavity_area = _rounded_area(dw + 2 * clearance, dl + 2 * clearance,
                                corner_radius + clearance)
    # Openings are cut right through, so they come off the ring as well.
    cut_area = sum(float(o["w"]) * float(o["h"]) for o in openings or ())
    # The largest axis-aligned rectangle inside the rounded cavity: a corner arc
    # of radius r admits a square corner inset by r*(1 - 1/sqrt2). Declared this
    # way the window never clips the fillets, so the row means "the pocket is
    # clear" and not "the corners are round", which is not in dispute.
    cavity_r = float(corner_radius) + float(clearance)
    inset = cavity_r * (1.0 - 2.0 ** -0.5)
    case_expected = (
        {"kind": "solid_region", "id": "wall-ring",
         "z": float(wall) + float(dt) / 2.0,
         "area_mm2": outer_area - cavity_area - cut_area},
        {"kind": "void_region", "id": "cavity",
         "z": float(wall) + float(dt) / 2.0, "at": (0.0, 0.0),
         "size_mm": (dw + 2 * clearance - 2 * inset, dl + 2 * clearance - 2 * inset)},
        {"kind": "bed_footprint", "area_mm2": outer_area},
    )
    return Built(
        part=part,
        params={
            "wall_mm": float(wall),
            "cavity_clearance_mm": float(clearance),
            "overall_mm": {"x": float(outer_w), "y": float(outer_l), "z": float(outer_t)},
        },
        reference=reference,
        expected=case_expected,
        notes=(f"cavity {dw + 2 * clearance:.2f} x {dl + 2 * clearance:.2f} mm around a "
               f"{dw} x {dl} x {dt} mm device at {clearance} mm per side, {wall} mm wall",),
    )


def bolt_boss(*, outer_d: float, bore_d: float, height: float,
              centre: tuple[float, float] = (0.0, 0.0)) -> Built:
    """A screw boss. Small, and it encodes the two things routinely got wrong.

    The annulus must be thick enough to print as walls rather than as a single
    bead, and a tall thin boss is a lever with a layer line at its base -- both
    surface as ordinary `PARAMS` the pre-build stage already knows how to judge.
    """
    if bore_d <= 0 or outer_d <= bore_d:
        raise ValueError(f"outer_d must exceed bore_d, got {outer_d} and {bore_d}")
    if height <= 0:
        raise ValueError(f"height must be positive, got {height}")

    x, y = centre
    post = trimesh.creation.cylinder(radius=outer_d / 2.0, height=height, sections=64)
    post.apply_translation((x, y, height / 2.0))
    bore = trimesh.creation.cylinder(radius=bore_d / 2.0, height=height * 3.0, sections=64)
    bore.apply_translation((x, y, height / 2.0))
    part = _seated(trimesh.boolean.difference([post, bore]))

    annulus = (outer_d - bore_d) / 2.0
    aspect = height / outer_d
    notes = [f"annulus wall {annulus:.2f} mm, aspect {aspect:.1f}"]
    if aspect > 4.0:
        notes.append("aspect over 4: add a gusset or ribs, the base layer line is the hinge")
    # The annulus, in closed form. A bore drilled oversize thins the wall that
    # carries the whole load of a standoff, and moves neither the bounding box
    # nor the component count -- the two numbers a boss otherwise offers.
    ring = math.pi * ((outer_d / 2.0) ** 2 - (bore_d / 2.0) ** 2)
    boss_expected: list[dict[str, Any]] = [
        {"kind": "solid_region", "id": "annulus", "z": float(height) / 2.0,
         "area_mm2": float(ring)},
        {"kind": "bed_footprint", "area_mm2": float(ring)},
    ]
    # A bore diameter is read from the material missing inside a window, and the
    # reading is only meaningful while two windows of different radius both
    # enclose the whole bore and both stay inside the post. On a thin annulus no
    # such pair exists -- the narrower window falls entirely inside the bore, the
    # two disagree, and the check reports indeterminate forever. Declaring it
    # anyway would be a permanent FAIL on a correct part, which is worse than not
    # declaring it: the annulus above already catches an oversize bore, at 30 mm2
    # on a boss whose bounding box does not move at all.
    if outer_d >= bore_d * 1.8:
        boss_expected.append(
            {"kind": "through_hole", "id": "bore", "at": (float(x), float(y)),
             "d_mm": float(bore_d), "z_from": 0.0, "z_to": float(height)})
    return Built(
        part=part,
        expected=tuple(boss_expected),
        params={
            "wall_mm": float(annulus),
            "overall_mm": {"x": float(outer_d), "y": float(outer_d), "z": float(height)},
        },
        notes=tuple(notes),
    )


def c_clip(*, bore_d: float, wall: float, height: float, mouth_gap: float,
           flange: tuple[float, float, float] | None = None,
           screw_d: float = 0.0, screw_at: tuple[float, float] | None = None,
           countersink_d: float = 0.0) -> Built:
    """A C-shaped channel that snaps over a round thing, on an optional flange.

    Cable clip, hose clamp, rail retainer, pen holder. `countersink_d` sinks the
    screw head from the flange's top face; the cone opens upward, away from the
    bed, so its own wall faces up and the zero-overhang guarantee survives it.

    The channel axis stands along Z on purpose, which is the whole reason this template is worth having:
    a horizontal round bore carries an unsupported crown that no surrounding
    geometry can remove, and four archived runs each rediscovered that. Standing
    it up makes every wall a vertical extrusion, so the part is self-supporting
    by construction rather than by a designer getting the orientation right.
    """
    if bore_d <= 0 or wall <= 0 or height <= 0:
        raise ValueError(f"bore, wall and height must be positive, got "
                         f"{bore_d}, {wall}, {height}")
    if not 0 < mouth_gap < bore_d + 2 * wall:
        raise ValueError(f"mouth_gap must open the channel without severing it, got {mouth_gap}")

    outer_d = bore_d + 2 * wall
    base_h = 0.0
    pieces = []
    if flange is not None:
        fw, fd, fh = (float(v) for v in flange)
        if min(fw, fd, fh) <= 0:
            raise ValueError(f"flange extents must be positive, got {flange}")
        base_h = fh
        pieces.append(_box((fw, fd, fh), (fw / 2, fd / 2, fh / 2)))
        centre = (fw - outer_d / 2 - wall, fd / 2)
    else:
        centre = (outer_d / 2, outer_d / 2)

    ring = trimesh.creation.annulus(r_min=bore_d / 2, r_max=outer_d / 2, height=height,
                                    sections=96)
    ring.apply_translation((centre[0], centre[1], base_h + height / 2))
    pieces.append(ring)
    part = trimesh.boolean.union(pieces) if len(pieces) > 1 else pieces[0]

    # The mouth is a straight-walled slot, not a radial wedge: a pie-slice cut
    # leaves cheek faces a few degrees past the overhang screen, which one run
    # measured at 293 mm2 and spent a build cycle removing.
    # Only as tall as the ring, and starting at its base. A cutter centred on
    # the ring and three times its height reached below the flange top and slotted
    # the mounting plate clean through -- 108 mm2 of it, open to the short edge,
    # while every scalar check still passed. A verification caught it by
    # sectioning the flange and comparing areas.
    mouth_h = height + 1.0
    mouth = _box((outer_d, mouth_gap, mouth_h),
                 (centre[0] + outer_d / 2, centre[1], base_h + mouth_h / 2))
    part = _seated(trimesh.boolean.difference([part, mouth]))

    if screw_d > 0 and flange is None:
        # Silently identical geometry either way, which is the worst kind of
        # accepted argument: the caller asked for a fastening and got none, and
        # nothing anywhere said so.
        raise ValueError(
            f"screw_d={screw_d} was given with no flange to put a screw through; "
            "either add a flange or drop the screw")
    if screw_d > 0 and flange is not None:
        # Positioned by the caller. A fixed position is what makes a template
        # half-fit: a run reached for this one, found the hole in the wrong
        # place, and hand-built its own -- paying for the template and the
        # authoring both.
        sx, sy = screw_at if screw_at is not None else (outer_d / 2, flange[1] / 2)
        cuts = [_cylinder(screw_d / 2, base_h * 3, (sx, sy, base_h / 2))]
        if countersink_d > screw_d:
            # Overshoot above the face: a cone whose wide end lands exactly on
            # the top plane leaves coplanar boolean artifacts that read as
            # downward-facing area.
            over = 1.0
            depth = (countersink_d - screw_d) / 2.0
            widest = countersink_d / 2 + over
            cuts.append(_frustum(screw_d / 2, widest, depth + over,
                                 (sx, sy, base_h - depth)))
        part = _cut_with(part, cuts)

    extents = part.bounds[1] - part.bounds[0]
    expected: list[dict[str, Any]] = []

    # The channel's own cross-section, in closed form. One number pins the bore,
    # the wall and the mouth together, because all three set it: an annulus of
    # pi*(Ro^2 - Ri^2) less the slab the mouth cutter takes out of it, and the
    # slab's bite on a circle of radius R is the standard chord integral
    # (g/2)*sqrt(R^2 - (g/2)^2) + R^2*asin(g/2R).
    #
    # Written down because a measured run reached this part with a gate that
    # declared nothing about the channel, correctly distrusted that, and
    # hand-wrote a thirteen-check sectioning script to cover it -- arriving at
    # 112.275 mm2, which is what this returns. The instinct was right and the
    # hand-rolling is exactly what the toolkit exists to stop: a bespoke
    # instrument is an uncalibrated one, and one run's own sampler read 137%
    # high against known nominals before it widened its bands to suit.
    r_in, r_out = bore_d / 2.0, outer_d / 2.0
    if 0.0 < mouth_gap <= bore_d:
        def _chord_area(radius: float) -> float:
            half = mouth_gap / 2.0
            return half * math.sqrt(radius ** 2 - half ** 2) + radius ** 2 * math.asin(half / radius)

        channel = math.pi * (r_out ** 2 - r_in ** 2) - (_chord_area(r_out) - _chord_area(r_in))
        expected.append({"kind": "solid_region", "id": "channel-mid",
                         "z": float(base_h) + float(height) / 2.0,
                         "area_mm2": float(channel)})

    if flange is not None:
        # Arithmetic, not measurement: the plate is its own rectangle less the
        # screw shaft. This is the number that caught the mouth cutter slotting
        # the flange -- 796.64 against 864.10 -- while bbox, watertightness,
        # component count and overhang area were all identical to the good part.
        plate = float(flange[0]) * float(flange[1]) - math.pi * (screw_d / 2.0) ** 2
        expected.append({"kind": "solid_region", "id": "flange-mid",
                         "z": float(base_h) / 2.0, "area_mm2": plate})
        expected.append({"kind": "bed_footprint", "area_mm2": plate})
        if screw_d > 0 and countersink_d > screw_d:
            sx, sy = screw_at if screw_at is not None else (outer_d / 2, flange[1] / 2)
            expected.append({"kind": "countersink", "id": "screw",
                             "at": (float(sx), float(sy)),
                             "shaft_d": float(screw_d), "head_d": float(countersink_d),
                             "face_z": float(base_h)})
    return Built(
        part=part,
        expected=tuple(expected),
        params={
            "wall_mm": float(wall),
            "overall_mm": {"x": float(extents[0]), "y": float(extents[1]),
                           "z": float(extents[2])},
            # Declared so the pre-build stage can see it is already resolved:
            # the channel stands along the print axis, so there is no crown.
            "horizontal_bores": [],
        },
        notes=tuple(
            [f"channel bore {bore_d} mm, {wall} mm wall, {mouth_gap} mm mouth, axis along "
             "Z so every wall is a vertical extrusion"]
            # Both of these drop an expectation, and a check that quietly does
            # not exist is not listed in `coverage.skipped` either -- so without
            # saying so here, nothing at all would tell a reader that the
            # feature went unmeasured.
            + ([f"countersink_d {countersink_d} is not larger than screw_d {screw_d}, so no "
                "countersink was cut and none is checked: the hole is a plain bore"]
               if screw_d > 0 and flange is not None and countersink_d <= screw_d else [])
            + ([f"the {mouth_gap} mm mouth is not narrower than the {bore_d} mm bore, so the "
                "channel cross-section has no closed form here and is not measured"]
               if mouth_gap > bore_d else [])
            + ([f"the {mouth_gap} mm mouth is narrower than the {bore_d} mm bore, so this "
                "retains by elastic snap: it is a fit interface, and a plan declaring none "
                "leaves it with no band, no coupon and no acceptance method. Say so in your "
                "handoff."]
               if mouth_gap < bore_d else [])),
    )


def segmented_box(*, inner: tuple[float, float, float], wall: Any, bed: float,
                  floor: float = 0.0, tongue: float = 0.0,
                  clearance: float = 0.25) -> Built:
    """A walled box too big for the bed, split into corner pieces that fit it.

    Some sizes are not chosen. A Langstroth hive body is 406.4 x 504.8 mm because
    every frame and every other beekeeper's box says so, and no common printer
    bed is over 256 -- so the box is printed in pieces or it is not printed. The
    decomposition is arithmetic, not taste: ceil(outer / bed) cells per axis, cut
    on plane boundaries, which for a Langstroth deep is exactly four quadrant
    corners of 203.2 x 252.4.

    Segments meet on a vertical tongue and groove. Vertical because it is the
    whole reason `c_clip` stands its channel on end: a horizontal alignment pin
    has a crown no surrounding geometry can support, and six separate runs
    rediscovered that before it was written down. A tongue running the full
    height is a vertical extrusion and prints with no support, and it registers
    the joint in both directions across the wall.

    Returns the segments in their assembled positions, so the exported solid is
    the box itself and its bounding box is the standard that was asked for.

    It declares the wall ring, and the first draft did not. The argument for
    silence was that a jointed section has no exact closed form and a nearly-right
    formula would pass a defect while reading like a check. That was wrong in the
    way that matters: the assembled section is the plain ring to within the joint
    clearance, and while nothing measured it a tongue slab spanning each cell left
    a solid rib straight across the brood cavity -- 6,575 mm2 of excess, no frame
    able to go in, and every other check green. The band below covers the
    clearance and nothing structural.
    """
    # A scalar wall cannot describe a real Langstroth box: the standard fixes
    # both the inside (frames must drop in) and the outside (boxes must stack on
    # each other's rims), and 406.4/374.7 implies 15.85 mm across while
    # 504.8/466.7 implies 19.05 along. Timber gets there with rabbet joints. A
    # caller reproducing an existing standard needs to say both.
    wall_x, wall_y = (float(wall), float(wall)) if isinstance(wall, (int, float))         else (float(wall[0]), float(wall[1]))
    if min(wall_x, wall_y) <= 0:
        raise ValueError(f"wall must be positive, got {wall}")
    if bed <= 0:
        raise ValueError(f"bed must be positive, got {bed}")
    # The same guards `box_shell` has. Without them a negative inner size reached
    # the cell arithmetic and came back as "already fits a 200 mm bed", which is
    # true only by a sign accident, and a negative floor shrank the box while
    # `assembled_mm` reported the shrunken height as if it were asked for.
    if min(float(v) for v in inner) <= 0:
        raise ValueError(f"inner extents must be positive, got {inner}")
    if floor < 0:
        raise ValueError(f"floor must not be negative, got {floor}")
    if tongue < 0:
        raise ValueError(f"tongue must not be negative, got {tongue}")
    if clearance < 0:
        raise ValueError(f"clearance must not be negative, got {clearance}")
    iw, id_, ih = (float(v) for v in inner)
    outer_x, outer_y = iw + 2 * wall_x, id_ + 2 * wall_y
    height = floor + ih
    tongue = float(tongue) if tongue > 0 else max(min(wall_x, wall_y) / 3.0, 1.2)
    if tongue >= min(wall_x, wall_y):
        raise ValueError(f"tongue {tongue} must be thinner than the "
                         f"{min(wall_x, wall_y)} mm wall")

    # Sized against what a segment may actually reach, not against the cell it
    # started as. A tongue is added outside the cut plane, so cells laid out to
    # exactly fill the bed produce pieces that overhang it -- 259.8 mm on a
    # 256 mm bed, which is the one failure this template exists to prevent.
    usable = bed - 2.0 * (tongue + clearance)
    if usable <= 0:
        raise ValueError(f"a {tongue} mm tongue leaves no usable width on a {bed} mm bed")
    nx, ny = math.ceil(outer_x / usable), math.ceil(outer_y / usable)
    if nx * ny == 1:
        raise ValueError(f"{outer_x:.1f} x {outer_y:.1f} mm already fits a {bed} mm bed; "
                         "use box_shell")
    cell_x, cell_y = outer_x / nx, outer_y / ny

    shell = _box((outer_x, outer_y, height), (outer_x / 2, outer_y / 2, height / 2))
    lid = max(wall_x, wall_y)
    cavity = _box((iw, id_, ih + lid), (outer_x / 2, outer_y / 2, floor + (ih + lid) / 2))
    ring = trimesh.boolean.difference([shell, cavity])

    # The core band: the wall with a third of its thickness taken off each face,
    # so anything living in it has material on both sides of it.
    band = min(wall_x, wall_y) / 3.0
    core = trimesh.boolean.difference([
        _box((outer_x - 2 * band, outer_y - 2 * band, height * 3),
             (outer_x / 2, outer_y / 2, height / 2)),
        _box((iw + 2 * band, id_ + 2 * band, height * 3),
             (outer_x / 2, outer_y / 2, height / 2))])
    core_grown = trimesh.boolean.difference([
        _box((outer_x - 2 * band + 2 * clearance, outer_y - 2 * band + 2 * clearance,
              height * 3), (outer_x / 2, outer_y / 2, height / 2)),
        _box((iw + 2 * band - 2 * clearance, id_ + 2 * band - 2 * clearance, height * 3),
             (outer_x / 2, outer_y / 2, height / 2))])

    segments: list[Built] = []
    for j in range(ny):
        for i in range(nx):
            x0, y0 = i * cell_x, j * cell_y
            # Inset by half the clearance at every internal seam, so neighbours
            # stand a bond line apart instead of touching exactly. Physically
            # that gap is the glue; topologically it is what stops the export
            # welding six solids into one non-manifold body -- in memory each
            # piece was watertight and the STL round trip was not, because
            # coincident faces merge on reimport. Outer faces are untouched, so
            # the assembled box is still the size the standard asks for.
            inset_x0 = clearance / 2.0 if i > 0 else 0.0
            inset_x1 = clearance / 2.0 if i < nx - 1 else 0.0
            inset_y0 = clearance / 2.0 if j > 0 else 0.0
            inset_y1 = clearance / 2.0 if j < ny - 1 else 0.0
            cell = _box((cell_x - inset_x0 - inset_x1, cell_y - inset_y0 - inset_y1,
                         height * 3),
                        (x0 + inset_x0 + (cell_x - inset_x0 - inset_x1) / 2,
                         y0 + inset_y0 + (cell_y - inset_y0 - inset_y1) / 2,
                         height / 2))
            piece = trimesh.boolean.intersection([ring, cell])
            if piece.is_empty:
                continue
            # One side of every internal seam grows a tongue, the other loses a
            # groove, so each seam is registered exactly once.
            adds, cuts = [], []
            for axis, index, count, span, extent in (
                    (0, i, nx, cell_x, outer_y), (1, j, ny, cell_y, outer_x)):
                for edge, sign in ((index > 0, -1.0), (index < count - 1, 1.0)):
                    if not edge:
                        continue
                    at = (x0 + (0.0 if sign < 0 else cell_x)) if axis == 0 else                          (y0 + (0.0 if sign < 0 else cell_y))
                    size = ((tongue, extent * 3, height) if axis == 0
                            else (extent * 3, tongue, height))
                    grown = tuple(v + 2 * clearance if k < 2 else v for k, v in enumerate(size))
                    centre = ((at, outer_y / 2, height / 2) if axis == 0
                              else (outer_x / 2, at, height / 2))
                    (adds if sign > 0 else cuts).append(
                        (_box(size, centre), _box(grown, centre)))
            # Both clipped to the core band, and that is the whole joint.
            # Unclipped, a tongue is a slab spanning the cell, so every internal
            # seam left a solid rib straight across the brood cavity: 6,575 mm2
            # of excess at mid-height, the middle of the cavity reporting as
            # solid, and no frame able to go in. Clipped only to the wall it
            # would span the full thickness, which is a butt joint offset by half
            # a tongue and registers nothing. In the core band it is a tongue in
            # a groove, with material either side of it.
            piece = _cut_with(piece, [trimesh.boolean.intersection([g, core_grown])
                                      for _, g in cuts])
            if adds:
                tongues = [trimesh.boolean.intersection([s, core]) for s, _ in adds]
                tongues = [s for s in tongues if s is not None and not s.is_empty]
                if tongues:
                    piece = trimesh.boolean.union([piece] + tongues)
            # Clamped twice, and the second clamp is the one that matters. A
            # tongue may cross the seam into its neighbour's cell -- that is what
            # registers the joint -- but it may not push past the outside of the
            # box, or the assembled hive comes out 417 x 515 where the standard
            # says 406.4 x 504.8 and every commercial box it must stack with
            # disagrees.
            piece = trimesh.boolean.intersection([piece, _box(
                (cell_x + 2 * tongue, cell_y + 2 * tongue, height * 3),
                (x0 + cell_x / 2, y0 + cell_y / 2, height / 2))])
            piece = trimesh.boolean.intersection([piece, _box(
                (outer_x, outer_y, height * 3), (outer_x / 2, outer_y / 2, height / 2))])
            # Refuse rather than hand back something unprintable. The whole
            # promise of this template is that every piece fits, and a caller who
            # discovers otherwise at the slicer has been told a comfortable lie.
            reach = piece.bounds[1] - piece.bounds[0]
            if max(float(reach[0]), float(reach[1])) > bed:
                raise ValueError(
                    f"segment {i},{j} reaches {float(reach[0]):.1f} x {float(reach[1]):.1f} mm, "
                    f"over the {bed} mm bed; reduce the tongue or pass a smaller bed")
            segments.append(piece)

    # Left where they belong, not spread along X. Laying them out was the
    # obvious move and it was wrong twice over: six hive segments come to
    # 1291 mm side by side, which fits no bed either, and it made the exported
    # bounding box an artifact of tongue arithmetic that no brief ever stated.
    # In place, the STL *is* the hive body -- in pieces -- and its bounding box
    # is the standard the caller asked for and can check. A slicer separates the
    # objects and arranges them; that is its job, not this one's.
    assembly = trimesh.util.concatenate(segments)
    extents = assembly.bounds[1] - assembly.bounds[0]

    # The assembled section is the plain wall ring, less the clearance in each
    # joint. Seams are (nx-1)*ny + nx*(ny-1), each crossing two walls, each
    # crossing losing about 2*clearance across the core band -- so the band is
    # four times that budget, which is generous for a gap and nowhere near a rib.
    seams = (nx - 1) * ny + nx * (ny - 1)
    ring_area = outer_x * outer_y - iw * id_
    joint_budget = max(1.0, 4.0 * max(seams, 1) * 2.0 * 2.0 * clearance * band)
    return Built(
        part=assembly,
        params={
            "wall_mm": float(min(wall_x, wall_y)),
            "overall_mm": {"x": float(extents[0]), "y": float(extents[1]),
                           "z": float(extents[2])},
            "segment_count": len(segments),
            "assembled_mm": {"x": outer_x, "y": outer_y, "z": height},
        },
        expected=(
            {"kind": "solid_region", "id": "wall-ring",
             "z": float(floor) + float(ih) / 2.0,
             "area_mm2": ring_area, "tol_mm2": joint_budget},
            # This template is why the kind exists: its tongue slabs once ran the
            # full height of the wall and straight across the cavity, 6575 mm2 of
            # material where a frame was meant to hang, and nothing was declared
            # at this plane at all. The ring above was the answer to that, and it
            # does catch a rib that size. What it cannot catch is one paid for
            # from elsewhere in the same section -- and its budget is not small,
            # since it scales with the seam count. The row below is local to the
            # cavity, so no allowance outside it applies.
            {"kind": "void_region", "id": "cavity",
             "z": float(floor) + float(ih) / 2.0,
             "at": (outer_x / 2.0, outer_y / 2.0),
             "size_mm": (float(iw), float(id_))},
        ),
        notes=(
            f"{outer_x:.1f} x {outer_y:.1f} mm box on a {bed:.0f} mm bed, so {nx} x {ny} "
            f"corner segments of {cell_x:.1f} x {cell_y:.1f}",
            f"segments register on a {tongue:.2f} mm vertical tongue and groove with "
            f"{clearance} mm per-side clearance; both are vertical extrusions and need no "
            "support",
            "the seams are a light and weather path: the plan owes them a sealing method, "
            "and nothing here checks that one exists",
        ),
    )


def stack(*builts: Built, gap: float = 0.0) -> Built:
    """Lay several parts out side by side along X, all seated on the bed.

    A multi-plate job is many parts checked against one plan; laying them out
    here means the envelope and support screens see the arrangement that will
    actually be printed rather than one part at a time.
    """
    if not builts:
        raise ValueError("stack needs at least one part")
    placed, cursor, offsets = [], 0.0, []
    for built in builts:
        mesh = built.part.copy()
        shift = cursor - float(mesh.bounds[0][0])
        offsets.append(shift)
        mesh.apply_translation((shift, 0.0, 0.0))
        placed.append(mesh)
        cursor = float(mesh.bounds[1][0]) + gap
    combined = trimesh.util.concatenate(placed)
    extents = combined.bounds[1] - combined.bounds[0]
    walls = [b.params["wall_mm"] for b in builts if "wall_mm" in b.params]
    params: dict[str, Any] = {
        "overall_mm": {"x": float(extents[0]), "y": float(extents[1]), "z": float(extents[2])},
    }
    if walls:
        # The thinnest wall in the set governs: a plate is only as printable as
        # its worst part.
        params["wall_mm"] = float(min(walls))
    return Built(part=combined, params=params,
                 expected=_stacked_expectations(builts, offsets),
                 notes=tuple(n for b in builts for n in b.notes))


def _stacked_expectations(builts: tuple[Built, ...], offsets: list[float]) -> tuple[dict, ...]:
    """Carry each part's checks onto the plate, or drop them and say so.

    Laying parts out used to discard every expectation its members declared, so
    a plate of five gated parts arrived at the gate with nothing to gate -- the
    multi-part job, which has the most to get wrong, had the emptiest checks.

    Three kinds behave differently and the difference is not cosmetic:

    * A hole keeps its size and moves with its part, so it carries over with the
      layout offset applied.
    * Bed contact is additive: the plate touches the bed on the sum of what its
      parts touch it with.
    * A section area is **not** additive unless every part declares one at that
      exact height. A plane through the plate cuts everything on it, so summing
      the two parts that declared a region at z and ignoring the third measures a
      number nothing has. Where that holds the areas sum; where it does not the
      row is dropped rather than approximated, because a section expectation
      that is nearly right would pass a defect while reading like a check.
    """
    carried: list[dict[str, Any]] = []
    # Bed contact is additive, and that is exactly why it needs the same
    # all-or-nothing rule as a section: the plate touches the bed on the sum of
    # everything on it, so summing only the parts that happened to declare a
    # footprint measures a number nothing has. A plate of one boss and one case
    # declared 36 mm2 against an actual 2848 and failed a correct part.
    footprints = [float(row["area_mm2"]) for b in builts for row in b.expected
                  if row.get("kind") == "bed_footprint"]
    has_footprint = len(footprints) == len(builts)
    footprint = sum(footprints) if has_footprint else 0.0
    for built, shift in zip(builts, offsets):
        for row in built.expected:
            kind = row.get("kind")
            if kind in ("through_hole", "countersink"):
                moved = dict(row)
                moved["at"] = (float(row["at"][0]) + shift, float(row["at"][1]))
                moved["id"] = f"{row.get('id', kind)}-{builts.index(built)}"
                carried.append(moved)

    heights: dict[float, list[float]] = {}
    for built in builts:
        for row in built.expected:
            if row.get("kind") == "solid_region":
                heights.setdefault(round(float(row["z"]), 6), []).append(float(row["area_mm2"]))
    for z, areas in sorted(heights.items()):
        if len(areas) == len(builts):
            carried.append({"kind": "solid_region", "id": f"plate-z{z:g}",
                            "z": z, "area_mm2": sum(areas)})

    if has_footprint:
        carried.append({"kind": "bed_footprint", "area_mm2": footprint})
    return tuple(carried)


# name -> (what shapes it covers, the call)
CATALOGUE: dict[str, tuple[str, str]] = {
    "box_shell": (
        "any walled box: enclosure, hive body, tray, drawer, planter, open or lidded",
        "box_shell(inner=(120, 80, 60), wall=3.0, floor=3.0, open_top=True)",
    ),
    "panel": (
        "a flat plate with openings: window, screen board, bottom board, lid, vent grille",
        'panel(width=100, depth=60, thickness=3.0, openings=('
        '{"kind": "rect", "x": 50, "y": 30, "w": 40, "h": 20},))',
    ),
    "device_case": (
        "a shelled wrap around a slab device: phone case, remote sleeve, "
        "instrument boot -- and it returns the mating reference with it",
        "device_case(device=(73.6, 155.6, 8.5), wall=1.5, clearance=0.25, corner_radius=9.0)",
    ),
    "c_clip": (
        "a C-channel that snaps over a round thing, on an optional flange: cable "
        "clip, hose clamp, rail retainer -- axis along Z, so self-supporting",
        "c_clip(bore_d=12.0, wall=3.0, height=9.0, mouth_gap=9.0, "
        "flange=(40, 22, 5), screw_d=4.5, screw_at=(8, 11), countersink_d=9.0)",
    ),
    "bolt_boss": (
        "a screw boss or standoff, reporting its annulus wall and aspect ratio",
        "bolt_boss(outer_d=8.0, bore_d=4.2, height=10.0)",
    ),
    "segmented_box": (
        "a walled box too big for the bed, split into corner pieces that fit it: "
        "hive body, large enclosure, planter -- per-axis walls, so it can reproduce "
        "a standard that fixes both the inside and the outside",
        "segmented_box(inner=(374.7, 466.7, 244.5), wall=(15.85, 19.05), bed=256.0)",
    ),
    "stack": (
        "several parts laid out side by side for one plate, thinnest wall governing",
        "stack(part_a, part_b, gap=5.0)",
    ),
}


def catalogue_lines() -> list[str]:
    """What a template would save, before deciding to hand-write one.

    A template is worth reaching for only if the part is one of these shapes.
    Knowing that costs one call; discovering it after authoring 130 lines costs
    the authoring.
    """
    lines = ["Parametric starting points. Each returns .part and .params together,",
             "computed from the same arithmetic, so the two cannot drift.", ""]
    for name, (covers, call) in CATALOGUE.items():
        lines.append(f"  {name}")
        lines.append(f"    covers: {covers}")
        lines.append(f"    call:   {call}")
    lines.extend(["",
                  "Use one where the shape fits; hand-write the backend model where it does",
                  "not, and declare PARAMS yourself. Everything else about the commission is",
                  "the same either way."])
    return lines
