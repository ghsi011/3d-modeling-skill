"""The knob sleeve, built mouth-up so nothing it needs is unsupported.

Printed crown-down: the bore becomes a well whose floor faces up, the rail slots
run out of the open mouth, and the only downward-facing face on the part is the
one on the bed. That is a print-engineering decision and it is why the taper
runs the way it does -- a flange stepping outward at the mouth would have put a
few hundred square millimetres of unsupported area under the seat.

The circles are 96-gons, so the mesh measures fractionally under every closed
form the proposal states. That is a tessellation difference and not a design
one; the acceptance bands are the pipeline's own 0.5% and absorb it.
"""
import math

import trimesh

PARAMS = {
    "crown_d_mm": 30.0,
    "grip_d_mm": 38.0,
    "crown_h_mm": 8.0,
    "body_h_mm": 50.0,
    "bore_d_mm": 17.4,
    "bore_floor_z_mm": 14.0,
    "rail_w_mm": 5.0,
    "rail_depth_mm": 1.5,
    "rail_from_z_mm": 20.0,
    "facets": 96,
}


def _ring(radius, z, facets):
    step = 2.0 * math.pi / facets
    return [(radius * math.cos(index * step), radius * math.sin(index * step), z)
            for index in range(facets)]


def build():
    facets = int(PARAMS["facets"])
    crown_r = PARAMS["crown_d_mm"] / 2.0
    grip_r = PARAMS["grip_d_mm"] / 2.0
    crown_h = PARAMS["crown_h_mm"]
    body_h = PARAMS["body_h_mm"]

    # A frustum is convex, so its hull is exactly itself and no boolean is needed
    # to make one.
    frustum = trimesh.convex.convex_hull(
        _ring(crown_r, 0.0, facets) + _ring(grip_r, crown_h, facets))
    grip = trimesh.creation.cylinder(radius=grip_r, height=body_h - crown_h,
                                     sections=facets)
    grip.apply_translation((0.0, 0.0, crown_h + (body_h - crown_h) / 2.0))
    body = trimesh.boolean.union([frustum, grip], engine="manifold")

    floor = PARAMS["bore_floor_z_mm"]
    bore_h = body_h - floor
    bore = trimesh.creation.cylinder(radius=PARAMS["bore_d_mm"] / 2.0,
                                     height=bore_h + 2.0, sections=facets)
    bore.apply_translation((0.0, 0.0, floor + (bore_h + 2.0) / 2.0))

    rail_from = PARAMS["rail_from_z_mm"]
    rail_h = body_h - rail_from + 2.0
    cutters = [bore]
    for sign in (-1.0, 1.0):
        rail = trimesh.creation.box(
            extents=(PARAMS["rail_depth_mm"] * 2.0, PARAMS["rail_w_mm"], rail_h))
        rail.apply_translation((sign * PARAMS["bore_d_mm"] / 2.0, 0.0,
                                rail_from + rail_h / 2.0))
        cutters.append(rail)
    return trimesh.boolean.difference([body, *cutters], engine="manifold")
