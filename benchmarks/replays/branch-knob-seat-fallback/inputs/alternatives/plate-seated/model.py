"""The knob sleeve seated on the base plate.

52 mm of body -- the envelope's whole height -- over the same 36 mm bore, so
the extra 2 mm sits below the engagement and lands on the base plate. This
formulation is right if the estimated plate height is right, and it is the
one that makes the knob feel solid rather than hanging on the rails.

Printed crown-down, mouth up. Every face on the part is vertical, on the bed, or
faces up: the bore is a well whose floor faces the ceiling and the rail slots run
out of the open mouth, so nothing here needs support and the support-ceiling row
measures zero. That is deliberate and it is not a design flourish -- a taper or a
skirt would put the overhang check in front of the chain this case exists to
exercise.

The circles are 96-gons, so the mesh measures fractionally under the closed forms
the proposal states, and the two rail slots are declared as rectangles where the
solid removes a slightly curved sliver of them. Both are tessellation
differences, both are under the acceptance band the pipeline owns, and neither
number is read off the mesh being judged.
"""
import trimesh

PARAMS = {
    "grip_d_mm": 38.0,
    "body_h_mm": 52.0,
    "bore_d_mm": 17.4,
    "bore_floor_z_mm": 16.0,
    "rail_w_mm": 5.0,
    "rail_depth_mm": 1.5,
    "facets": 96,
}


def build():
    facets = int(PARAMS["facets"])
    body_h = PARAMS["body_h_mm"]
    body = trimesh.creation.cylinder(radius=PARAMS["grip_d_mm"] / 2.0,
                                     height=body_h, sections=facets)
    body.apply_translation((0.0, 0.0, body_h / 2.0))

    floor = PARAMS["bore_floor_z_mm"]
    bore_h = body_h - floor
    # Two millimetres proud of the mouth so the cut leaves no skin behind it.
    bore = trimesh.creation.cylinder(radius=PARAMS["bore_d_mm"] / 2.0,
                                     height=bore_h + 2.0, sections=facets)
    bore.apply_translation((0.0, 0.0, floor + (bore_h + 2.0) / 2.0))

    cutters = [bore]
    for sign in (-1.0, 1.0):
        rail = trimesh.creation.box(
            extents=(PARAMS["rail_depth_mm"] * 2.0, PARAMS["rail_w_mm"],
                     bore_h + 2.0))
        rail.apply_translation((sign * PARAMS["bore_d_mm"] / 2.0, 0.0,
                                floor + (bore_h + 2.0) / 2.0))
        cutters.append(rail)
    return trimesh.boolean.difference([body, *cutters], engine="manifold")
