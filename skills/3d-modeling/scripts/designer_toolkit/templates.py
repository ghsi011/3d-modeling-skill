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
from dataclasses import dataclass, field
from typing import Any

import trimesh


@dataclass(frozen=True)
class Built:
    """Geometry plus everything a check would otherwise have to be told."""

    part: Any
    params: dict[str, Any]
    reference: Any | None = None
    edge_samples: dict[str, tuple[float, float]] = field(default_factory=dict)
    notes: tuple[str, ...] = ()


def _seated(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Drop a solid onto z=0.

    Templates always return a part resting on the bed, because that is the
    convention the plan's identity model-to-printer transform assumes. A part
    centred on the origin has half of itself below the bed and every downward
    face reads as unsupported.
    """
    mesh.apply_translation((0.0, 0.0, -float(mesh.bounds[0][2])))
    return mesh


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

    return Built(
        part=part,
        params={
            "wall_mm": float(wall),
            "overall_mm": {"x": float(outer[0]), "y": float(outer[1]), "z": float(outer[2])},
        },
        notes=(f"cavity {iw} x {id_} x {ih} mm inside a {wall} mm wall"
               + (f" on a {floor} mm floor" if floor else "")
               + ("" if open_top else f" under a {wall} mm lid"),),
    )


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


def panel(*, width: float, depth: float, thickness: float,
          openings: tuple[dict[str, Any], ...] = ()) -> Built:
    """A flat plate with openings: hive window, screen board, bottom board, lid.

    Each opening is ``{"kind": "rect", "x", "y", "w", "h"}`` or
    ``{"kind": "round", "x", "y", "d"}``, positioned by its centre in panel
    coordinates with the origin at the panel's near corner.
    """
    if min(width, depth, thickness) <= 0:
        raise ValueError(f"panel extents must be positive, got {(width, depth, thickness)}")

    plate = _box((width, depth, thickness), (width / 2, depth / 2, thickness / 2))
    if openings:
        cuts = [_opening_solid(o, thickness) for o in openings]
        for cut in cuts:
            cut.apply_translation((0.0, 0.0, thickness / 2))
        plate = trimesh.boolean.difference([plate, trimesh.util.concatenate(cuts)])
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

    return Built(part=part, params=params, notes=tuple(notes))


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
    return Built(
        part=part,
        params={
            "wall_mm": float(annulus),
            "overall_mm": {"x": float(outer_d), "y": float(outer_d), "z": float(height)},
        },
        notes=tuple(notes),
    )


def stack(*builts: Built, gap: float = 0.0) -> Built:
    """Lay several parts out side by side along X, all seated on the bed.

    A multi-plate job is many parts checked against one plan; laying them out
    here means the envelope and support screens see the arrangement that will
    actually be printed rather than one part at a time.
    """
    if not builts:
        raise ValueError("stack needs at least one part")
    placed, cursor = [], 0.0
    for built in builts:
        mesh = built.part.copy()
        mesh.apply_translation((cursor - float(mesh.bounds[0][0]), 0.0, 0.0))
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
                 notes=tuple(n for b in builts for n in b.notes))


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
    "bolt_boss": (
        "a screw boss or standoff, reporting its annulus wall and aspect ratio",
        "bolt_boss(outer_d=8.0, bore_d=4.2, height=10.0)",
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


def deg_to_normal_z(degrees_from_vertical: float) -> float:
    """The `downward_normal_z_max` a plan would declare for a given overhang angle."""
    return -math.cos(math.radians(degrees_from_vertical))
