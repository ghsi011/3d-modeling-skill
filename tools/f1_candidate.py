#!/usr/bin/env python3
"""A compliant F1 bin, built by the benchmark, so the predicates can be mutated.

`AGENTS.md`: *prove a protection by mutating it, never by watching it pass.*
F1's protections are geometric -- divider count, divider axis, lip present, no
bores, prismatic compartments -- and the defects they exist to catch are
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

**This is a predicate exerciser, not a printable bin.** It has the footprint,
the height, the wall, the two compartments, the inward lip and the closed base,
because those are what the predicates read. It has no grid base profile, so it
would not seat in a real baseplate. Saying so rather than letting a later reader
assume otherwise: the geometric authority for this fixture is the hidden
reference, which a third-party generator produced and which
`benchmarks/heavy/test_e2e_f1_heavy.py` puts through these same predicates. Two
states, one written here and one nobody here wrote -- a fixture whose two states
are identical distinguishes neither.

Nothing here was measured off the reference. The base allowance is the published
grid family's base-profile height rather than the reference's own, so this bin
is 25.75 mm tall where the reference is 24.8; the wall is 1.0 mm because the
brief asks for 1.0 mm; and the lip inset is 0.9 mm where the reference's is 1.6.
The two independently clear `min_lip_inset_mm` instead of one copying the other.
"""
from __future__ import annotations

from pathlib import Path

# The brief, as numbers.
PITCH_MM = 42.0
CLEARANCE_MM = 0.5
UNITS_LONG = 2
UNITS_SHORT = 1
HEIGHT_UNIT_MM = 7.0
HEIGHT_UNITS = 3
BASE_MM = 4.75
WALL_MM = 1.0
FLOOR_MM = 6.0

# What the brief asks for, and what it forbids. These are the mutation targets:
# `benchmarks/mutations/e2e-f1-gridbin.json` edits one of them per probe.
DIVIDER_COUNT = 1
DIVIDER_MM = 1.2
SPLIT_AXIS = 0                       # 0 = x, the long direction the brief names
LIP_INSET_MM = 0.9                   # 0.0 removes the stacking lip
LIP_HEIGHT_MM = 4.0
MAGNET_BORES = 0                     # magnet pockets / screw holes in the base
SCOOP_MM = 0.0                       # a finger-scoop ramp at the compartment floor
LABEL_MM = 0.0                       # a label flange hanging into the compartment
LONG_AXIS_SCALE = 1.0                # one axis scaled off the grid
EXTRA_BODY = False                   # a second solid in the STL

OUTER_RADIUS_MM = 3.75
LENGTH_MM = UNITS_LONG * PITCH_MM * LONG_AXIS_SCALE - CLEARANCE_MM
WIDTH_MM = UNITS_SHORT * PITCH_MM - CLEARANCE_MM
HEIGHT_MM = HEIGHT_UNITS * HEIGHT_UNIT_MM + BASE_MM
CAVITY_TOP_MM = HEIGHT_MM - LIP_HEIGHT_MM


def _rounded(length: float, width: float, radius: float):
    """A rounded rectangle centred on the origin, as a shapely polygon."""
    from shapely.geometry import box

    return (box(-length / 2.0, -width / 2.0, length / 2.0, width / 2.0)
            .buffer(-radius, join_style=1, quad_segs=16)
            .buffer(radius, join_style=1, quad_segs=16))


def _prism(polygon, low: float, high: float):
    import trimesh

    solid = trimesh.creation.extrude_polygon(polygon, high - low)
    solid.apply_translation((0.0, 0.0, low))
    return solid


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
    inner = (LENGTH_MM if SPLIT_AXIS == 0 else WIDTH_MM) - 2.0 * WALL_MM
    count = DIVIDER_COUNT + 1
    each = (inner - DIVIDER_COUNT * DIVIDER_MM) / count
    first = -inner / 2.0 + each / 2.0
    return [(first + index * (each + DIVIDER_MM), each) for index in range(count)]


def build():
    """The bin, in whatever state the constants above currently describe."""
    import trimesh
    from shapely.geometry import Polygon

    outer = _prism(_rounded(LENGTH_MM, WIDTH_MM, OUTER_RADIUS_MM), 0.0, HEIGHT_MM)
    inner_long = LENGTH_MM - 2.0 * WALL_MM
    inner_short = WIDTH_MM - 2.0 * WALL_MM
    across = inner_short if SPLIT_AXIS == 0 else inner_long

    cutters = []
    for offset, each in _compartments():
        shape = (_rounded(each, across, 1.0) if SPLIT_AXIS == 0
                 else _rounded(across, each, 1.0))
        cavity = _prism(shape, FLOOR_MM, CAVITY_TOP_MM)
        cavity.apply_translation((offset, 0.0, 0.0) if SPLIT_AXIS == 0
                                 else (0.0, offset, 0.0))
        cutters.append(cavity)

    # The lip: the opening above the compartments is narrower, so the base of
    # the next bin lands on the ledge. Overlapped 0.1 mm into the compartment
    # cutters rather than butted against them, because two coplanar boolean
    # faces are where a manifold engine leaves a sliver.
    cutters.append(_prism(
        _rounded(inner_long - 2.0 * LIP_INSET_MM,
                 inner_short - 2.0 * LIP_INSET_MM, 1.0),
        CAVITY_TOP_MM - 0.1, HEIGHT_MM + 1.0))

    for index in range(MAGNET_BORES):
        bore = trimesh.creation.cylinder(radius=3.25, height=4.8, sections=48)
        bore.apply_translation(((index % 4) * 13.0 - 19.5,
                                (index // 4) * 13.0 - 6.5, 0.0))
        cutters.append(bore)

    bin_ = trimesh.boolean.difference([outer, *cutters], engine="manifold")

    additions = []
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
