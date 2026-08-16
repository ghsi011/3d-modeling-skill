#!/usr/bin/env python3
"""A compliant F1 bin, built by the benchmark, so the predicates can be mutated.

`AGENTS.md`: *prove a protection by mutating it, never by watching it pass.*
F1's protections are geometric -- the published base profile, the corner radius,
the floor height, the lip's depth and seat height, divider count, divider axis,
no bores, prismatic compartments -- and the defects they exist to catch are
geometric too. `tools/mutate.py` patches **source text**, so the probes the
brief requires are expressed here: each is a one-line edit to a constant below,
and the mutation is killed when the predicate that names it stops passing in
`tools/test_e2e.py`. That is the honest shape of the requirement. Mutating a
predicate would prove a test notices the *test* changing; mutating the
candidate proves the predicate notices the *defect*.

Every defect is a module constant and never an argument to `build`. An argument
a test passes is a second code path, and a sweep over it would be probing the
path rather than the geometry -- the compliant state and the defective state
have to be the same code with one number different.

**What changed at fixture revision 2.** This used to be a plain rounded box with
a flat bottom, and it said so: *it has no grid base profile, so it would not
seat in a real baseplate*. It could get away with that because revision 1's
predicates did not look at the base. They do now -- the request states the
published profile and five new rows measure it -- so this file builds the
profile: a lofted foot, a floor at the published base height, and a lip socket
whose determined segments are the published ones.

**It is still a predicate exerciser and not a design.** It is built from the
same published figures the request states, which is exactly what makes it the
first of the two states this fixture needs. The second is
`benchmarks/heavy/test_e2e_f1_heavy.py`, which puts the hidden reference --
geometry nobody in this repository authored -- through the same predicates. A
fixture whose two states are identical distinguishes neither, so the two are
kept apart where the publication leaves room: this bin runs the lip's final
chamfer 1.0 mm and stands 24.5 mm tall where the reference runs 1.3 and stands
24.8, and it meets its floor and its divider in sharp junctions where the
reference fillets them at 1.1 mm. Both readings are legal, which is why the
distance predicate masks the regions they differ in.

Nothing here was measured off the reference. Every figure is either in the
request or is one of the two choices named above.
"""
from __future__ import annotations

from pathlib import Path

# The published interface, as the request states it.
PITCH_MM = 42.0
GAP_MM = 0.5
UNITS_LONG = 2
UNITS_SHORT = 1
HEIGHT_UNIT_MM = 7.0
HEIGHT_UNITS = 3
OUTER_RADIUS_MM = 3.75             # the published radius at the widest section
BASE_LOWER_CHAMFER_MM = 0.8
BASE_LAND_MM = 1.8
BASE_UPPER_CHAMFER_MM = 2.15
FLOOR_MM = 7.0                     # the published base height; its top is the floor
LIP_DEPTH_MM = 2.6                 # published, from the outer surface, wall included
LIP_LOWER_CHAMFER_MM = 0.7
LIP_LAND_MM = 1.8
LIP_SUPPORT_MM = 1.2
WALL_MM = 1.0
DIVIDER_MM = 1.2

# The two things the publication leaves open, chosen here and chosen
# differently from the reference on purpose -- see the module docstring.
LIP_TOP_CHAMFER_MM = 1.0           # the published 1.9 truncated; 0.9 mm of rim left
LIP_TIP_OFFSET_MM = 0.0            # the tip sits at the nominal height, so: none

# What the brief asks for, and what it forbids. These are the mutation targets:
# `benchmarks/mutations/e2e-f1-gridbin.json` edits one of them per probe.
DIVIDER_COUNT = 1
SPLIT_AXIS = 0                       # 0 = x, the long direction the brief names
LIP_INSET_MM = LIP_DEPTH_MM - WALL_MM  # how far the ledge hangs past the wall
MAGNET_BORES = 0                     # magnet pockets / screw holes in the base
SCOOP_MM = 0.0                       # a finger-scoop ramp at the compartment floor
LABEL_MM = 0.0                       # a label flange hanging into the compartment
LONG_AXIS_SCALE = 1.0                # one axis scaled off the grid
EXTRA_BODY = False                   # a second solid in the STL
SEPARATE_FEET = True                 # one published foot per grid unit, not one long one

ARC_SEGMENTS = 24                    # per corner; see `_ring`

LENGTH_MM = UNITS_LONG * PITCH_MM * LONG_AXIS_SCALE - GAP_MM
WIDTH_MM = UNITS_SHORT * PITCH_MM - GAP_MM
BASE_RISE_MM = BASE_LOWER_CHAMFER_MM + BASE_LAND_MM + BASE_UPPER_CHAMFER_MM
BASE_RUN_MM = BASE_LOWER_CHAMFER_MM + BASE_UPPER_CHAMFER_MM
FOOT_PITCH_X_MM = (LENGTH_MM + GAP_MM) / UNITS_LONG
FOOT_PITCH_Y_MM = (WIDTH_MM + GAP_MM) / UNITS_SHORT
FOOT_SPAN_X_MM = FOOT_PITCH_X_MM - GAP_MM
FOOT_SPAN_Y_MM = FOOT_PITCH_Y_MM - GAP_MM
LIP_TIP_Z_MM = HEIGHT_UNITS * HEIGHT_UNIT_MM + LIP_TIP_OFFSET_MM
HEIGHT_MM = (LIP_TIP_Z_MM + LIP_LOWER_CHAMFER_MM + LIP_LAND_MM
             + LIP_TOP_CHAMFER_MM)
CAVITY_TOP_MM = LIP_TIP_Z_MM         # where the compartments end and the lip starts


def _ring(length: float, width: float, radius: float) -> list[tuple[float, float]]:
    """A rounded rectangle centred on the origin, as an ordered point ring.

    Written out rather than taken from `shapely.buffer` because the loft below
    needs two rings with *corresponding* vertices, and a buffer returns whatever
    point count it likes. Parametrised the same way at every size, so ring `i`
    of one profile pairs with ring `i` of the next.

    The first sample of each corner arc is at 0 degrees and the last at 90, so
    the extreme points in x and y are vertices: the ring's bounding box is
    exactly `length` x `width` whatever `ARC_SEGMENTS` is, which is what lets
    the base-profile predicate read spans off a tessellated section without
    paying for the discretisation. The area is not exact -- an inscribed
    polygon is smaller than its arc -- and at 24 segments that costs the
    corner-radius measurement about 0.011 mm against a 0.2 mm tolerance.
    """
    import math

    half_l = length / 2.0 - radius
    half_w = width / 2.0 - radius
    out: list[tuple[float, float]] = []
    for cx, cy, start in ((half_l, half_w, 0.0), (-half_l, half_w, 90.0),
                          (-half_l, -half_w, 180.0), (half_l, -half_w, 270.0)):
        for step in range(ARC_SEGMENTS + 1):
            angle = math.radians(start + 90.0 * step / ARC_SEGMENTS)
            out.append((cx + radius * math.cos(angle),
                        cy + radius * math.sin(angle)))
    return out


def _loft(profile: list[tuple[float, float, float, float]]):
    """A closed solid through rings given as `(z, length, width, radius)`.

    Each 45 degree segment of the published profiles is a straight taper
    between two rounded rectangles, and a taper is what neither
    `extrude_polygon` nor a stack of thin prisms gives: the first cannot do it
    at all and the second turns a flat ramp into a staircase whose treads are
    the measurement. So the rings are lofted directly -- quads down the sides,
    a fan cap at each end -- and the surface is the real plane.

    Winding is stated rather than fixed up afterwards: rings run
    counter-clockwise seen from +z, side quads are wound so their normals point
    away from the axis, and the two caps are wound outward. `process=False`
    keeps trimesh from merging vertices before the caller has looked at it.
    """
    import numpy as np
    import trimesh

    rings = [(z, _ring(length, width, radius))
             for z, length, width, radius in profile]
    count = len(rings[0][1])
    vertices: list[tuple[float, float, float]] = []
    for z, points in rings:
        vertices += [(x, y, z) for x, y in points]

    faces: list[tuple[int, int, int]] = []
    for level in range(len(rings) - 1):
        low, high = level * count, (level + 1) * count
        for i in range(count):
            j = (i + 1) % count
            faces.append((low + i, low + j, high + j))
            faces.append((low + i, high + j, high + i))

    bottom_centre = len(vertices)
    vertices.append((0.0, 0.0, rings[0][0]))
    top_centre = len(vertices)
    vertices.append((0.0, 0.0, rings[-1][0]))
    last = (len(rings) - 1) * count
    for i in range(count):
        j = (i + 1) % count
        faces.append((bottom_centre, j, i))
        faces.append((top_centre, last + i, last + j))

    return trimesh.Trimesh(vertices=np.asarray(vertices, dtype=float),
                           faces=np.asarray(faces, dtype=np.int64),
                           process=False)


def _foot_profile(span_x: float, span_y: float
                  ) -> list[tuple[float, float, float, float]]:
    """One published foot, from the bottom of the plug up into the body.

    The profile is stated *per grid unit*, which is the whole reason this is a
    separate function: a two-by-one bin stands on two feet on the pitch with the
    published gap between them, not on one long plinth with the same outline. A
    single plinth has exactly the same bounding box at every height, so the
    profile predicate cannot tell them apart -- and it is `base_feet` that does,
    because a plinth does not sit on a baseplate's grid.

    The last ring repeats the one below it half a millimetre into the body: the
    two are unioned, and a foot whose top face is coplanar with the body's
    bottom face is a boolean asking for a sliver.
    """
    top_r = OUTER_RADIUS_MM
    mid_r = top_r - BASE_UPPER_CHAMFER_MM
    low_r = mid_r - BASE_LOWER_CHAMFER_MM
    return [
        (0.0, span_x - 2 * BASE_RUN_MM, span_y - 2 * BASE_RUN_MM, low_r),
        (BASE_LOWER_CHAMFER_MM, span_x - 2 * BASE_UPPER_CHAMFER_MM,
         span_y - 2 * BASE_UPPER_CHAMFER_MM, mid_r),
        (BASE_LOWER_CHAMFER_MM + BASE_LAND_MM,
         span_x - 2 * BASE_UPPER_CHAMFER_MM,
         span_y - 2 * BASE_UPPER_CHAMFER_MM, mid_r),
        (BASE_RISE_MM, span_x, span_y, top_r),
        (BASE_RISE_MM + 0.5, span_x, span_y, top_r),
    ]


def _feet():
    """Every foot, placed on the grid -- or one plinth when that is mutated."""
    if not SEPARATE_FEET:
        return [((0.0, 0.0), _foot_profile(LENGTH_MM, WIDTH_MM))]
    out = []
    for ix in range(UNITS_LONG):
        for iy in range(UNITS_SHORT):
            at = ((ix - (UNITS_LONG - 1) / 2.0) * FOOT_PITCH_X_MM,
                  (iy - (UNITS_SHORT - 1) / 2.0) * FOOT_PITCH_Y_MM)
            out.append((at, _foot_profile(FOOT_SPAN_X_MM, FOOT_SPAN_Y_MM)))
    return out


def _body_profile() -> list[tuple[float, float, float, float]]:
    """The bin above its feet: one prism from the top of the plug to the rim.

    It starts at the top of the base profile, so the first `BASE_HEIGHT -
    BASE_RISE` millimetres of it are the published structure that ties the feet
    together.
    """
    return [
        (BASE_RISE_MM, LENGTH_MM, WIDTH_MM, OUTER_RADIUS_MM),
        (HEIGHT_MM, LENGTH_MM, WIDTH_MM, OUTER_RADIUS_MM),
    ]


def _cavity_profile() -> list[tuple[float, float, float, float]]:
    """Everything removed from the inside, in one loft.

    The compartments and the stacking-lip socket are the same cut: a straight
    cavity from the floor up, the lip's published support ramping in, the
    throat, and then the socket the next bin's foot drops into. One loft rather
    than two solids because the throat is where they meet, and two coplanar
    boolean faces at exactly the seat is the one place a sliver would matter.

    The last ring repeats the one below it a millimetre above the rim: the cut
    has to leave the solid cleanly, and continuing the 45 degree chamfer would
    have opened the socket wider than the bin.
    """
    wall_l, wall_w = LENGTH_MM - 2 * WALL_MM, WIDTH_MM - 2 * WALL_MM
    wall_r = OUTER_RADIUS_MM - WALL_MM
    tip_l, tip_w = LENGTH_MM - 2 * LIP_DEPTH_MM, WIDTH_MM - 2 * LIP_DEPTH_MM
    tip_r = OUTER_RADIUS_MM - LIP_DEPTH_MM
    ramp = LIP_INSET_MM                      # 45 degrees, so rise equals run
    land_z = LIP_TIP_Z_MM + LIP_LOWER_CHAMFER_MM
    land_l = tip_l + 2 * LIP_LOWER_CHAMFER_MM
    land_w = tip_w + 2 * LIP_LOWER_CHAMFER_MM
    land_r = tip_r + LIP_LOWER_CHAMFER_MM
    return [
        (FLOOR_MM, wall_l, wall_w, wall_r),
        (LIP_TIP_Z_MM - LIP_SUPPORT_MM - ramp, wall_l, wall_w, wall_r),
        (LIP_TIP_Z_MM - LIP_SUPPORT_MM, tip_l, tip_w, tip_r),
        (LIP_TIP_Z_MM, tip_l, tip_w, tip_r),
        (land_z, land_l, land_w, land_r),
        (land_z + LIP_LAND_MM, land_l, land_w, land_r),
        (HEIGHT_MM, land_l + 2 * LIP_TOP_CHAMFER_MM,
         land_w + 2 * LIP_TOP_CHAMFER_MM, land_r + LIP_TOP_CHAMFER_MM),
        (HEIGHT_MM + 1.0, land_l + 2 * LIP_TOP_CHAMFER_MM,
         land_w + 2 * LIP_TOP_CHAMFER_MM, land_r + LIP_TOP_CHAMFER_MM),
    ]


def _lying_prism(polygon, span: float):
    """A prism extruded along +Y instead of +Z, centred on y = 0.

    `extrude_polygon` only runs along +Z, and a scoop and a label tab both run
    across the compartment. Rotating +90 about X sends (u, v, w) to (u, -w, v),
    so the polygon's own second coordinate becomes the height -- which is what
    lets the triangle below be written in the (x, z) the feature is drawn in.
    """
    import numpy as np
    import trimesh

    solid = trimesh.creation.extrude_polygon(polygon, span)
    solid.apply_transform(trimesh.transformations.rotation_matrix(
        np.pi / 2.0, [1, 0, 0]))
    solid.apply_translation((0.0, span / 2.0, 0.0))
    return solid


def _compartments() -> list[tuple[float, float]]:
    """Each compartment's centre offset and length along the split axis."""
    inner = ((LENGTH_MM if SPLIT_AXIS == 0 else WIDTH_MM) - 2.0 * WALL_MM)
    count = DIVIDER_COUNT + 1
    each = (inner - DIVIDER_COUNT * DIVIDER_MM) / count
    first = -inner / 2.0 + each / 2.0
    return [(first + index * (each + DIVIDER_MM), each) for index in range(count)]


def build():
    """The bin, in whatever state the constants above currently describe."""
    import trimesh
    from shapely.geometry import Polygon

    body = _loft(_body_profile())
    body.fix_normals()
    parts = [body]
    for (dx, dy), profile in _feet():
        foot = _loft(profile)
        foot.fix_normals()
        foot.apply_translation((dx, dy, 0.0))
        parts.append(foot)
    outer = (parts[0] if len(parts) == 1
             else trimesh.boolean.union(parts, engine="manifold"))
    cavity = _loft(_cavity_profile())
    cavity.fix_normals()

    cutters = [cavity]
    for index in range(MAGNET_BORES):
        bore = trimesh.creation.cylinder(radius=3.25, height=4.8, sections=48)
        bore.apply_translation(((index % 4) * 13.0 - 19.5,
                                (index // 4) * 13.0 - 6.5, 0.0))
        cutters.append(bore)
    bin_ = trimesh.boolean.difference([outer, *cutters], engine="manifold")

    # The dividers, put back into the hollow. Each one starts a millimetre below
    # the floor and ends half a millimetre inside the wall at either end, so no
    # face of the addition is coplanar with a face of the body: coplanar union
    # faces are where a manifold engine leaves a sliver, and a sliver here would
    # cost the watertight row for a reason that has nothing to do with the
    # design. Half a millimetre is inside a 1.0 mm wall, so the union cannot
    # grow the bin's footprint either.
    additions = []
    across = (WIDTH_MM if SPLIT_AXIS == 0 else LENGTH_MM) - 2.0 * WALL_MM
    buried = across + WALL_MM
    cells = _compartments()
    for index in range(DIVIDER_COUNT):
        offset = cells[index][0] + cells[index][1] / 2.0 + DIVIDER_MM / 2.0
        extents = ((DIVIDER_MM, buried, CAVITY_TOP_MM - FLOOR_MM + 1.0)
                   if SPLIT_AXIS == 0
                   else (buried, DIVIDER_MM, CAVITY_TOP_MM - FLOOR_MM + 1.0))
        wall = trimesh.creation.box(extents=extents)
        wall.apply_translation(
            ((offset, 0.0, (CAVITY_TOP_MM + FLOOR_MM - 1.0) / 2.0)
             if SPLIT_AXIS == 0
             else (0.0, offset, (CAVITY_TOP_MM + FLOOR_MM - 1.0) / 2.0)))
        additions.append(wall)

    if SCOOP_MM > 0.0:
        # The ramp a finger scoop leaves at the front-bottom of a compartment.
        for offset, each in _compartments():
            corner = offset - each / 2.0
            triangle = Polygon([(corner, FLOOR_MM),
                                (corner + SCOOP_MM, FLOOR_MM),
                                (corner, FLOOR_MM + SCOOP_MM)])
            additions.append(_lying_prism(triangle, across))
    if LABEL_MM > 0.0:
        # A label flange: a tab hanging into the compartment under the rim. It
        # is drawn deep enough to reach inside `compartment_band`, because a tab
        # confined above that band is outside what the prismatic predicate can
        # see -- recorded in the fixture's `what_this_band_cannot_catch`.
        for offset, each in _compartments():
            corner = offset - each / 2.0
            tab = Polygon([(corner, CAVITY_TOP_MM - 6.0),
                           (corner + LABEL_MM, CAVITY_TOP_MM - 6.0),
                           (corner + LABEL_MM, CAVITY_TOP_MM),
                           (corner, CAVITY_TOP_MM)])
            additions.append(_lying_prism(tab, across))
    if additions:
        bin_ = trimesh.boolean.union([bin_, *additions], engine="manifold")

    if not EXTRA_BODY:
        return bin_
    stray = trimesh.creation.box(extents=(4.0, 4.0, 4.0))
    stray.apply_translation((0.0, 0.0, HEIGHT_MM + 10.0))
    return trimesh.util.concatenate([bin_, stray])


def write(into: Path) -> Path:
    into = Path(into)
    into.parent.mkdir(parents=True, exist_ok=True)
    build().export(str(into))
    return into


if __name__ == "__main__":
    import sys

    print(write(Path(sys.argv[1])))
