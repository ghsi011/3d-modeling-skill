"""Parametric fit-coupon generator (mesh primitives — no CAD kernel needed).

The print engineer declares, per interface, a nominal mating size and a fit
band. Before the real part prints, a coupon exercises that band across a few
lanes so the operator measures the ACTUAL printed fit and picks the offset that
works on this machine/material. This builds the coupon STL and a legend from the
plan's interface list, instead of the designer hand-modelling one every job.

Each interface is a dict:
    {"id": str, "nominal_mm": float, "kind": "hole"|"peg", "depth_mm": float (optional)}
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import trimesh

DEFAULT_OFFSETS_MM = (-0.20, -0.10, 0.00, 0.10, 0.20)


@dataclass(frozen=True)
class CouponLane:
    interface_id: str
    kind: str
    offset_mm: float
    feature_diameter_mm: float
    x_mm: float
    y_mm: float


def _cylinder(diameter: float, height: float, at):
    cyl = trimesh.creation.cylinder(radius=diameter / 2.0, height=height, sections=64)
    cyl.apply_translation(at)
    return cyl


def fit_coupon(interfaces, out_path, *, plate_thickness: float = 4.0,
               feature_pitch: float = 12.0, lane_pitch: float = 14.0,
               margin: float = 6.0, peg_height: float = 6.0,
               offsets_mm=DEFAULT_OFFSETS_MM):
    """Build a multi-lane fit coupon STL and return ``(stl_path, legend)``.

    One lane (row along +Y) per interface; one feature per declared offset. Holes
    are bored through the plate; pegs stand proud of it. ``legend`` is a list of
    :class:`CouponLane` mapping every printed feature back to its interface and
    intended offset so the operator can read the coupon.
    """
    interfaces = list(interfaces)
    if not interfaces:
        raise ValueError("fit_coupon needs at least one interface")
    offsets = list(offsets_mm)
    n_lanes = len(interfaces)
    n_feat = len(offsets)

    width = margin * 2 + (n_feat - 1) * feature_pitch
    depth = margin * 2 + (n_lanes - 1) * lane_pitch
    plate = trimesh.creation.box((width, depth, plate_thickness))
    # Bottom of the plate at Z=0 (print orientation), features centred over cells.
    plate.apply_translation((width / 2, depth / 2, plate_thickness / 2))

    holes: list = []
    pegs: list = []
    legend: list = []
    for li, iface in enumerate(interfaces):
        # `nominal_mm` and `kind` are this command's own inputs, not fields of
        # the v4 interface row -- that row carries a per-side clearance range and
        # says nothing about the feature's size or whether it is a hole or a peg,
        # because a band is a band whatever it is measured on. A conformant plan
        # therefore reached here and died on `KeyError: 'nominal_mm'`, which
        # names a key its author had no way to know they owed.
        if "nominal_mm" not in iface:
            raise ValueError(
                f"interface {iface.get('id', li)!r} has no `nominal_mm`. A coupon prints "
                "real features at graded sizes, so it needs the nominal dimension being "
                "toleranced and whether it is a `hole` or a `peg` -- neither is part of the "
                "v4 interface row, which carries only the band. Add `nominal_mm` (and "
                "`kind`) to the interfaces you want lanes for.")
        nominal = float(iface["nominal_mm"])
        kind = iface.get("kind", "hole")
        y = margin + li * lane_pitch
        for fi, off in enumerate(offsets):
            d = max(nominal + float(off), 0.2)
            x = margin + fi * feature_pitch
            if kind == "peg":
                pegs.append(_cylinder(d, peg_height, (x, y, plate_thickness + peg_height / 2)))
            else:
                # over-tall cutter so the bore is clean through the plate
                holes.append(_cylinder(d, plate_thickness * 3, (x, y, plate_thickness / 2)))
            legend.append(CouponLane(str(iface.get("id", f"iface{li}")), kind,
                                     float(off), float(d), float(x), float(y)))

    body = plate
    if holes:
        body = trimesh.boolean.difference([body, *holes])
    parts = [body] + pegs
    coupon = trimesh.util.concatenate(parts) if len(parts) > 1 else body

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    coupon.export(str(out_path))
    return str(out_path), legend


def legend_to_rows(legend) -> list:
    """Flatten a legend to plain dict rows (for JSON / Markdown tables)."""
    return [
        {"interface_id": c.interface_id, "kind": c.kind, "offset_mm": c.offset_mm,
         "feature_diameter_mm": round(c.feature_diameter_mm, 3),
         "x_mm": round(c.x_mm, 2), "y_mm": round(c.y_mm, 2)}
        for c in legend
    ]
