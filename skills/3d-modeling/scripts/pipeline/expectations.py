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

`test_independence.py` asserts the import graph, because a rule this easy to
break quietly is not a rule unless something checks it.
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
         "note": "the annulus, less the straight mouth slot cut through one side"},
        {"feature_id": "bed-footprint", "kind": "bed_contact",
         "value_mm2": flange_area,
         "note": "the flange meets the bed; the screw hole goes through it"},
        {"feature_id": "screw-bore", "kind": "through_hole",
         "at": {"x": flange_w * 0.2, "y": flange_d / 2.0},
         "d_mm": float(p["screw_d"]), "z_from": 0.0, "z_to": flange_t},
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
