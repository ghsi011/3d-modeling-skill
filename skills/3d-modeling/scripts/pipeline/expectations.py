#!/usr/bin/env python3
"""What each certified template's solid must measure, from the parameters alone.

**Nothing here may import a backend, and no backend may import this.** That is
the whole value, and it is easy to lose by accident. If geometry and expectation
share a helper for a critical dimension, a bug in the helper moves both and they
agree while the part is wrong -- the common-mode failure this repo already has on
record: drop `countersink_d` and the geometry and its expectation vanish
together, so the part is self-consistently wrong and nothing objects.

So the arithmetic below is derived independently, from the closed form of what
the shape *should* be, and never from what the builder happened to construct.
The mouth-cutter bug is the model to preserve: it changed the boolean result and
left `fw * fd - pi * r**2` untouched, so the two disagreed by 67 mm2 and the
disagreement is what caught it.

`test_pipeline.py`'s `IndependenceTest` asserts the import graph, because a rule
this easy to break quietly is not a rule unless something checks it.
"""
from __future__ import annotations

import math
from typing import Any


def _strip_of_disk(radius: float, gap: float) -> float:
    """Area of `{|x| <= gap/2, y >= 0}` inside a disk of `radius`.

    The mouth of a C-channel is a straight slot cut on one side, so the material
    it removes from an annulus is this integral evaluated at the outer radius
    less the same at the inner one. Closed form:

        2 * integral(0, g/2) sqrt(r^2 - x^2) dx
          = (g/2) * sqrt(r^2 - g^2/4) + r^2 * asin(g / 2r)
    """
    half = gap / 2.0
    if half >= radius:
        return math.pi * radius * radius / 2.0
    return half * math.sqrt(radius * radius - half * half) + radius * radius * math.asin(half / radius)


# ---------------------------------------------------------------------------
# c_clip
# ---------------------------------------------------------------------------

def c_clip_bbox(p: dict[str, Any]) -> dict[str, float]:
    return {"x": float(p["flange_w"]), "y": float(p["flange_d"]),
            "z": float(p["flange_t"]) + float(p["height"])}


def c_clip_expectations(p: dict[str, Any]) -> list[dict[str, Any]]:
    flange_w, flange_d = float(p["flange_w"]), float(p["flange_d"])
    flange_t, height = float(p["flange_t"]), float(p["height"])
    bore_d, wall, gap = float(p["bore_d"]), float(p["wall"]), float(p["mouth_gap"])
    screw_r = float(p["screw_d"]) / 2.0

    outer_r, inner_r = bore_d / 2.0 + wall, bore_d / 2.0
    annulus = math.pi * (outer_r ** 2 - inner_r ** 2)
    mouth_removed = _strip_of_disk(outer_r, gap) - _strip_of_disk(inner_r, gap)

    flange_area = flange_w * flange_d - math.pi * screw_r ** 2

    return [
        {"feature_id": "flange-section", "kind": "section_area",
         "at": {"z": flange_t / 2.0}, "value_mm2": flange_area,
         "note": "the plate, less the screw shank through it"},
        {"feature_id": "channel-section", "kind": "section_area",
         "at": {"z": flange_t + height / 2.0}, "value_mm2": annulus - mouth_removed,
         "fit_parameter": "bore_d",
         "fit_probe": {"at": {"x": flange_w / 2.0, "y": flange_d / 2.0},
                       "z": flange_t + height / 2.0},
         "note": "the annulus, less the straight mouth slot cut through one side"},
        {"feature_id": "bed-footprint", "kind": "bed_contact",
         "value_mm2": flange_area,
         "note": "the flange meets the bed; the screw hole goes through it"},
        {"feature_id": "screw-bore", "kind": "through_hole",
         "at": {"x": flange_w * 0.2, "y": flange_d / 2.0},
         "d_mm": float(p["screw_d"]), "z_from": 0.0, "z_to": flange_t,
         "fit_parameter": "screw_d"},
        {"feature_id": "channel-void", "kind": "void_region",
         "at": {"x": flange_w / 2.0, "y": flange_d / 2.0},
         "z": flange_t + height / 2.0,
         "size_mm": [bore_d * 0.6, bore_d * 0.6],
         "note": "the bundle has to go somewhere; nothing may stand in the channel"},
    ]


# ---------------------------------------------------------------------------
# trim_ring
# ---------------------------------------------------------------------------

def trim_ring_bbox(p: dict[str, Any]) -> dict[str, float]:
    across = float(p["hole_d"]) + 2.0 * float(p["lip_w"])
    return {"x": across, "y": across, "z": float(p["panel_t"]) + float(p["lip_t"])}


def trim_ring_expectations(p: dict[str, Any]) -> list[dict[str, Any]]:
    hole_d, lip_w = float(p["hole_d"]), float(p["lip_w"])
    panel_t, lip_t = float(p["panel_t"]), float(p["lip_t"])
    wall, chamfer = float(p["wall"]), float(p["chamfer"])

    bore_d = hole_d - 2.0 * wall
    skirt = math.pi / 4.0 * (hole_d ** 2 - bore_d ** 2)
    lip_outer = hole_d + 2.0 * lip_w
    lip = math.pi / 4.0 * (lip_outer ** 2 - bore_d ** 2)
    centre = lip_outer / 2.0

    # Sampled below the chamfer on purpose: the chamfer is a real feature and
    # its taper would make a mid-lip section a function of where exactly the
    # plane fell, which is a tolerance argument rather than a measurement.
    lip_probe = panel_t + min(lip_t * 0.25, max(lip_t - chamfer, 0.1) * 0.5)

    return [
        {"feature_id": "skirt-section", "kind": "section_area",
         "at": {"z": panel_t / 2.0}, "value_mm2": skirt,
         "note": "the tube passing through the panel"},
        {"feature_id": "lip-section", "kind": "section_area",
         "at": {"z": lip_probe}, "value_mm2": lip,
         "note": "the flange resting on the panel, sampled below the chamfer"},
        {"feature_id": "bed-footprint", "kind": "bed_contact",
         "value_mm2": skirt,
         "note": "printed lip-down would need support; skirt-down it does not"},
        # By displacement, not by the two-radius cross-check: this bore is wide
        # and its wall is thin, so no window radius exists with both r and 0.8r
        # buried in material. Measured as the material missing from a disc the
        # size of the skirt, which needs no such window.
        {"feature_id": "liner-bore", "kind": "bore_by_displacement",
         "at": {"x": centre, "y": centre}, "d_mm": bore_d,
         "enclosing_d_mm": hole_d, "z": panel_t / 2.0},
    ]


# ---------------------------------------------------------------------------
# Where each template's own geometry legitimately steps
# ---------------------------------------------------------------------------

def c_clip_profile_marks(p: dict[str, Any]) -> dict[str, list[float]]:
    """The flange top is a real step: the section drops from the plate to the ring."""
    flange_t = float(p["flange_t"])
    return {"z": [0.0, flange_t, flange_t + float(p["height"])]}


def trim_ring_profile_marks(p: dict[str, Any]) -> dict[str, list[float]]:
    """The lip underside steps out; the chamfer tapers in over its own length."""
    panel_t, lip_t, cham = float(p["panel_t"]), float(p["lip_t"]), float(p["chamfer"])
    return {"z": [0.0, panel_t, panel_t + lip_t - cham, panel_t + lip_t]}


# ---------------------------------------------------------------------------
# box_shell -- a walled box: enclosure, tray, drawer, bin
# ---------------------------------------------------------------------------

def box_shell_bbox(p: dict[str, Any]) -> dict[str, float]:
    wall = float(p["wall"])
    return {"x": float(p["inner_w"]) + 2.0 * wall,
            "y": float(p["inner_d"]) + 2.0 * wall,
            "z": float(p["floor"]) + float(p["inner_h"])}


def box_shell_expectations(p: dict[str, Any]) -> list[dict[str, Any]]:
    iw, id_, ih = float(p["inner_w"]), float(p["inner_d"]), float(p["inner_h"])
    wall, floor = float(p["wall"]), float(p["floor"])
    ow, od = iw + 2.0 * wall, id_ + 2.0 * wall
    footprint = ow * od
    ring = footprint - iw * id_

    return [
        {"feature_id": "floor-section", "kind": "section_area",
         "at": {"z": floor / 2.0}, "value_mm2": footprint,
         "note": "solid floor below the cavity"},
        {"feature_id": "wall-ring", "kind": "section_area",
         "at": {"z": floor + ih / 2.0}, "value_mm2": ring,
         "note": "the four walls, with the cavity taken out of the footprint"},
        {"feature_id": "bed-footprint", "kind": "bed_contact", "value_mm2": footprint,
         "note": "a floored box meets the bed on solid material"},
        # The cavity is what the caller asked to be able to put things in. The
        # ring above is one scalar for the whole section, so a thinned wall buys
        # room for something standing inside; this reads the cavity alone.
        {"feature_id": "cavity", "kind": "void_region",
         "at": {"x": ow / 2.0, "y": od / 2.0}, "z": floor + ih / 2.0,
         "size_mm": [iw, id_],
         "note": "nothing may stand in the usable volume"},
    ]


def box_shell_profile_marks(p: dict[str, Any]) -> dict[str, list[float]]:
    floor = float(p["floor"])
    return {"z": [0.0, floor, floor + float(p["inner_h"])]}


# ---------------------------------------------------------------------------
# l_bracket -- two plates at a right angle, with fastener holes in each
# ---------------------------------------------------------------------------

def l_bracket_bbox(p: dict[str, Any]) -> dict[str, float]:
    return {"x": float(p["width"]), "y": float(p["leg_b"]), "z": float(p["leg_a"])}


def l_bracket_expectations(p: dict[str, Any]) -> list[dict[str, Any]]:
    width = float(p["width"])
    leg_a, leg_b, t = float(p["leg_a"]), float(p["leg_b"]), float(p["thickness"])
    hole_d = float(p["hole_d"])
    hole_r = hole_d / 2.0

    # The horizontal leg lies flat on the bed; the vertical leg stands from it.
    #
    # The flat section is the whole footprint less its hole -- a circle there,
    # because that hole's axis is vertical.
    #
    # The standing section is sampled *at the upright hole's own height*, where
    # the check is worth something. That hole's axis lies along Y, so a plane
    # through its centreline cuts it as a full rectangle `hole_d x t`, not a
    # circle. Sampling at the mid-leg instead measured a plane with no hole in it
    # at all, and the expectation subtracted one anyway.
    flat = width * leg_b - math.pi * hole_r ** 2
    standing = t * (width - hole_d)

    return [
        {"feature_id": "flat-leg", "kind": "section_area",
         "at": {"z": t / 2.0}, "value_mm2": flat,
         "note": "the leg on the bed, less its fastener hole"},
        {"feature_id": "standing-leg", "kind": "section_area",
         "at": {"z": leg_a - float(p["hole_inset"])}, "value_mm2": standing,
         "note": "the upright at its fastener hole, which the plane cuts as a slot"},
        {"feature_id": "bed-footprint", "kind": "bed_contact",
         "value_mm2": width * leg_b - math.pi * hole_r ** 2,
         "note": "the flat leg meets the bed; its hole goes through"},
        {"feature_id": "flat-hole", "kind": "through_hole",
         "at": {"x": width / 2.0, "y": leg_b - float(p["hole_inset"])},
         "d_mm": hole_d, "z_from": 0.0, "z_to": t},
    ]


def l_bracket_profile_marks(p: dict[str, Any]) -> dict[str, list[float]]:
    """Where the section legitimately jumps: the flat leg ends, and the upright's
    fastener hole opens and closes."""
    t, leg_a = float(p["thickness"]), float(p["leg_a"])
    hole_r = float(p["hole_d"]) / 2.0
    centre = leg_a - float(p["hole_inset"])
    return {"z": [0.0, t, centre - hole_r, centre, centre + hole_r, leg_a]}


# ---------------------------------------------------------------------------
# Expected solid volume, per template, from the parameters alone
# ---------------------------------------------------------------------------
#
# One scalar for the whole part, and the only screen here that does not need to
# know *where* a defect is. A profile compares neighbouring samples, so a ledge
# that lifts the level across twenty millimetres shows no step at all and walks
# past it -- that is measured: a 24.9% ledge and a 45.8% rib both screened CLEAR.
#
# Volume is weak where the repo already knew it was weak: a deleted countersink
# moves it 0.9%, under any usable band. It is strong exactly where the profile is
# blind, which is why both exist.

def c_clip_volume(p: dict[str, Any]) -> float:
    flange_w, flange_d = float(p["flange_w"]), float(p["flange_d"])
    flange_t, height = float(p["flange_t"]), float(p["height"])
    bore_d, wall, gap = float(p["bore_d"]), float(p["wall"]), float(p["mouth_gap"])
    screw_r = float(p["screw_d"]) / 2.0

    outer_r, inner_r = bore_d / 2.0 + wall, bore_d / 2.0
    annulus = math.pi * (outer_r ** 2 - inner_r ** 2)
    mouth = _strip_of_disk(outer_r, gap) - _strip_of_disk(inner_r, gap)
    flange = flange_w * flange_d - math.pi * screw_r ** 2
    return flange * flange_t + (annulus - mouth) * height


def box_shell_volume(p: dict[str, Any]) -> float:
    iw, id_, ih = float(p["inner_w"]), float(p["inner_d"]), float(p["inner_h"])
    wall, floor = float(p["wall"]), float(p["floor"])
    ow, od = iw + 2.0 * wall, id_ + 2.0 * wall
    return ow * od * floor + (ow * od - iw * id_) * ih


def l_bracket_volume(p: dict[str, Any]) -> float:
    width = float(p["width"])
    leg_a, leg_b, t = float(p["leg_a"]), float(p["leg_b"]), float(p["thickness"])
    hole_r = float(p["hole_d"]) / 2.0
    # The two legs share the corner block, so the upright is counted above the
    # flat leg only. Each loses one fastener hole: the flat one a cylinder through
    # its thickness, the upright one a cylinder across its own.
    flat = width * leg_b * t
    upright = width * t * (leg_a - t)
    holes = math.pi * hole_r ** 2 * t + math.pi * hole_r ** 2 * t
    return flat + upright - holes


def trim_ring_volume(p: dict[str, Any]) -> float:
    hole_d, lip_w = float(p["hole_d"]), float(p["lip_w"])
    panel_t, lip_t = float(p["panel_t"]), float(p["lip_t"])
    wall, cham = float(p["wall"]), float(p["chamfer"])
    bore_d, lip_outer = hole_d - 2.0 * wall, hole_d + 2.0 * lip_w

    skirt = math.pi / 4.0 * (hole_d ** 2 - bore_d ** 2) * panel_t
    lip = math.pi / 4.0 * (lip_outer ** 2 - bore_d ** 2) * lip_t
    # A chamfer of side c around a circle of radius r removes the solid of
    # revolution of a right triangle: Pappus gives area * 2*pi*centroid_radius.
    outer_r = lip_outer / 2.0
    chamfer_area = cham * cham / 2.0
    centroid_r = outer_r - cham / 3.0
    return skirt + lip - chamfer_area * 2.0 * math.pi * centroid_r


# ---------------------------------------------------------------------------
# vented_enclosure -- the complex one
# ---------------------------------------------------------------------------
#
# Written the same way as every other closed form here: from the parameters,
# never from the solid. The vents and bosses make the arithmetic longer, not
# different -- and a template with 72 cuts is exactly where an expectation
# derived from the mesh would start agreeing with whatever the boolean produced.

# The bore overshoots the boss by this much at each end so its faces never land
# coplanar with the floor. Written here independently of the builder's own
# overshoot: if the two ever disagree the volume check says so, which is the
# entire point of not sharing the constant.
_BORE_OVERSHOOT_MM = 1.0


def vented_enclosure_bbox(p: dict[str, Any]) -> dict[str, float]:
    wall = float(p["wall"])
    return {"x": float(p["inner_w"]) + 2.0 * wall,
            "y": float(p["inner_d"]) + 2.0 * wall,
            "z": float(p["floor"]) + float(p["inner_h"])}


def _boss_annulus(p: dict[str, Any]) -> float:
    """One boss's cross-section: its disc less its bore.

    The bosses stand clear of the walls, so each contributes a whole annulus
    rather than a lens overlapping one. That clearance is load-bearing in two
    senses: it keeps this arithmetic exact, and it avoids tangency -- a boss
    whose surface exactly touches a wall's makes an edge shared by three faces,
    which is not a volume even though nothing about it is open.
    """
    return math.pi / 4.0 * (float(p["boss_d"]) ** 2 - float(p["boss_bore"]) ** 2)


def vented_enclosure_expectations(p: dict[str, Any]) -> list[dict[str, Any]]:
    iw, id_, ih = float(p["inner_w"]), float(p["inner_d"]), float(p["inner_h"])
    wall, floor = float(p["wall"]), float(p["floor"])
    boss_d = float(p["boss_d"])
    ow, od = iw + 2.0 * wall, id_ + 2.0 * wall

    footprint = ow * od
    ring = footprint - iw * id_
    # Sampled just above the floor, below the lowest vent: the first vent sits at
    # `floor + ih/(rows+1)` and is `vent_h` tall, so half a millimetre up is clear
    # of it by construction and the reading is the walls plus four bosses.
    probe = floor + min(0.5, ih * 0.02)

    return [
        {"feature_id": "floor-section", "kind": "section_area",
         "at": {"z": floor / 2.0}, "value_mm2": footprint,
         "note": "solid floor below the cavity"},
        {"feature_id": "wall-and-bosses", "kind": "section_area",
         "at": {"z": probe}, "value_mm2": ring + 4.0 * _boss_annulus(p),
         "note": "the four walls plus four boss annuli, below the lowest vent"},
        {"feature_id": "bed-footprint", "kind": "bed_contact", "value_mm2": footprint,
         "note": "the enclosure meets the bed on its whole floor"},
        # Clear of the bosses on purpose: this asks whether the usable volume is
        # usable, and a window overlapping a declared boss would answer a
        # different question.
        {"feature_id": "cavity", "kind": "void_region",
         "at": {"x": ow / 2.0, "y": od / 2.0}, "z": floor + ih / 2.0,
         "size_mm": [iw - 2.0 * boss_d, id_ - 2.0 * boss_d],
         "note": "nothing may stand in the middle of the usable volume"},
    ]


def vented_enclosure_profile_marks(p: dict[str, Any]) -> dict[str, list[float]]:
    """Every height the section legitimately jumps: the floor, each vent's top
    and bottom, and the top of the walls."""
    ih, floor = float(p["inner_h"]), float(p["floor"])
    rows, vh = int(p["vent_rows"]), float(p["vent_h"])
    pitch = ih / (rows + 1)
    marks = [0.0, floor, floor + ih]
    for j in range(rows):
        centre = floor + pitch * (j + 1)
        marks += [centre - vh / 2.0, centre, centre + vh / 2.0]
    return {"z": sorted(marks)}


def vented_enclosure_volume(p: dict[str, Any]) -> float:
    iw, id_, ih = float(p["inner_w"]), float(p["inner_d"]), float(p["inner_h"])
    wall, floor = float(p["wall"]), float(p["floor"])
    cols, rows = int(p["vent_cols"]), int(p["vent_rows"])
    vw, vh = float(p["vent_w"]), float(p["vent_h"])
    boss_d, boss_bore = float(p["boss_d"]), float(p["boss_bore"])
    ow, od = iw + 2.0 * wall, id_ + 2.0 * wall

    shell = ow * od * (floor + ih) - iw * id_ * ih
    vents = cols * rows * vw * vh * wall
    bosses = 4.0 * math.pi / 4.0 * boss_d ** 2 * ih
    # Each bore runs the boss height plus one overshoot into the floor; the other
    # overshoot leaves the solid entirely and removes nothing.
    bores = 4.0 * math.pi / 4.0 * boss_bore ** 2 * (ih + _BORE_OVERSHOOT_MM)
    return shell - vents + bosses - bores
