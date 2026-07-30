"""Tesla Model 3 air-vent mount with a 17 mm male ball joint in place of its phone cradle.

Both source shapes are the user's own printed-and-verified parts and neither is
redrawn here:

  source/vent_mount.step        - the vent mount, three solids in the assembled pose
                                  [0] top phone hook on a height ratchet   (dropped)
                                  [1] pivoting vent-fin arm                (untouched)
                                  [2] main body: backplate + vent claws     (edited)
  source/ball_male_17mm.stl     - the 17 mm male ball, imported as a B-rep solid
                                  and moved, never rebuilt

What this module authors is only the joint between them:

  * a half-space cut at the phone-rest plane, which removes the lower phone lip
    and leaves that face flush,
  * a slab that fills the now-purposeless ratchet channel so the backplate is a
    uniform 6 mm behind the ball instead of 2.5 mm,
  * a tapered collar that fillets the ball's base plate into that backplate.

Design frame (the plate's own frame, which is what every number below is in):
    x  across the plate, 50 mm wide, 0 at the centre
    y  up the plate,     60 mm tall, 0 at the centre
    z  out of the phone-rest face -- the ball axis, 90 deg to that face
The face itself is the plane z = 0.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import trimesh

from build123d import (
    Box,
    BuildPart,
    BuildSketch,
    Cone,
    Cylinder,
    Location,
    Mesher,
    Plane,
    Pos,
    RectangleRounded,
    Vector,
    export_stl,
    import_step,
    loft,
)

TESS_TOL = 0.008           # chord deviation of the exported mesh, mm
TESS_ANG = 0.10            # angular deviation, radians

HERE = Path(__file__).resolve().parent

# --- the phone-rest face, read off the imported B-rep, not assumed ------------
# The 3000 mm^2 planar face of solid[2]: centre and normal in STEP coordinates.
FACE_CENTRE = Vector(7.98, 11.9, 33.04)
FACE_X = Vector(1, 0, 0)            # across the plate
FACE_Z = Vector(0, -0.934, 0.358)   # out of the face; 21 deg recline from vertical

# --- ball, measured from the source STL --------------------------------------
# Robust sphere fit (iterated on vertices 7.8-9.0 mm from the centre and more
# than 7 mm off the axis, which excludes a 44-vertex internal artifact sitting
# at r 2.8 on the equator): every one of 1155 vertices lands on the same sphere,
# residual max 0.0000. A naive fit over z > 15 is pulled 0.1 mm by that artifact
# and reads 16.90.
BALL_D = 17.140           # through the mesh vertices; facet chords sit inside it
BALL_BASE_X = 20.3        # base plate footprint
BALL_BASE_Y = 28.3
BALL_BASE_R = 4.0         # base plate corner radius, from its section area
BALL_AXIS_XY = (10.150, 14.150)   # ball axis in the STL's own frame, min-corner at origin
BALL_CENTRE_Z = 20.480    # sphere centre above the STL's own z = 0
BALL_Z0 = 1.6             # where the STL's own z = 0 lands in the design frame

# --- the joint this module authors -------------------------------------------
FILL_HALF_X = 14.0        # ratchet channel is 20 mm wide plus 3 mm rails each side
FILL_Y_LO = -12.0
# The fill stops at y = 18, well short of the backplate's own top edge at 30.01,
# and the channel stays open above it exactly as the source has it. The vent
# arm's pivot hub is a cylinder of radius ~5.01 about the bore axis at
# (y 25.0, z -10.77), so its crown stands at z = -5.76 in every pose, and it
# swings within y >= 19.99. Filling to the plate's own 6 mm over the whole
# channel put 0.24 mm of new material inside that hub -- the arm would not have
# seated. Nothing above y = 18 carries the ball: the ball's base plate ends at
# y = 14.15.
FILL_Y_HI = 18.0
PLATE_T = 6.0             # the backplate's thickness outboard of the channel

# The plinth. Its base is buried 2 mm inside the backplate and its top is 1 mm
# proud of the ball's base plate all round, so neither end of it has to resolve
# a face coplanar or tangent with anything: a plinth that died exactly on the
# plate face and exactly on the base outline produced 0.05 mm slivers at both
# ends and an invalid solid.
PLINTH_Z_LO = -2.0
PLINTH_Z_HI = 2.9         # inside the base plate's straight wall (2.55 .. 3.90)
PLINTH_LEDGE = 1.0        # how far the plinth stands proud of the base at its top
PLINTH_FLARE = 5.0        # extra half-width at the buried bottom

PARAMS = {
    "ball_diameter_mm": BALL_D,
    "ball_axis_to_face_deg": 90.0,
    "ball_centre_standoff_mm": BALL_Z0 + BALL_CENTRE_Z,
    "plate_thickness_mm": PLATE_T,
    "plinth_height_above_face_mm": PLINTH_Z_HI,
    "plinth_ledge_mm": PLINTH_LEDGE,
    "wall_mm": PLATE_T,
    "removed": ["top phone hook (solid 0)", "lower phone lip", "ratchet channel"],
    "preserved": ["17 mm ball and neck", "vent claws", "vent-arm snap bores"],
}


# --- the two vent-arm snap bores, remeasured off the STEP's own cone surfaces --
# Each leg carries a barrel-shaped through bore that the pivoting arm's peg snaps
# into: d 4.000 at the mouth, swelling to d 5.200 over the middle 0.836 mm, back
# to d 4.000. Its four cone faces are the STEP's only broken geometry -- OCCT
# cannot triangulate them at any deflection, and clean()/ShapeFix do not help, so
# every export drops them and leaves eight open circles in the mesh. They are
# refilled and re-cut from these numbers, which came from the cone surfaces
# themselves (semi-angle 16.0751 deg, ref radius 2.3) and not from the mesh.
BORE_AXIS_YZ = (30.8914, 52.5270)   # STEP coordinates
BORE_R_MOUTH = 2.000
BORE_R_BULGE = 2.600
BORE_R_RELIEF = 2.020
BORE_TAPER_L = 2.082
BORE_BULGE_L = 0.836
BORE_X_STARTS = (-7.018, 17.982)    # low-X mouth of the leg-A and leg-B bores
BORE_LEN = 2 * BORE_TAPER_L + BORE_BULGE_L    # 5.000


def _plate_plane() -> Plane:
    """The design frame: origin on the phone-rest face, z out of it."""
    return Plane(origin=FACE_CENTRE, x_dir=FACE_X, z_dir=FACE_Z)


def _bore_tool(x0: float):
    """The barrel bore as a clean solid, its axis on STEP +X, starting at x0.

    The stubs that run past each mouth are BORE_R_RELIEF rather than
    BORE_R_MOUTH and start 0.2 mm inside the tab. A stub at exactly the mouth
    radius is tangent to the cone it continues, and the cut then leaves a
    0.0005 mm^2 annular sliver at the mouth that OCCT cannot triangulate
    either -- trading one unmeshable face for another. The relief opens each
    mouth by 0.02 mm per side, which is under a tenth of FDM placement noise.
    """
    yz = Plane(origin=(x0, BORE_AXIS_YZ[0], BORE_AXIS_YZ[1]),
               x_dir=(0, 1, 0), z_dir=(1, 0, 0))
    segments = [
        (Cylinder(BORE_R_RELIEF, 0.7, align=None), -0.5),
        (Cone(BORE_R_MOUTH, BORE_R_BULGE, BORE_TAPER_L, align=None), 0.0),
        (Cylinder(BORE_R_BULGE, BORE_BULGE_L, align=None), BORE_TAPER_L),
        (Cone(BORE_R_BULGE, BORE_R_MOUTH, BORE_TAPER_L, align=None),
         BORE_TAPER_L + BORE_BULGE_L),
        (Cylinder(BORE_R_RELIEF, 0.7, align=None), BORE_LEN - 0.2),
    ]
    tool = None
    for shape, offset in segments:
        placed = yz * Pos(0, 0, offset) * shape
        tool = placed if tool is None else tool + placed
    return tool


def _repair_bores(body):
    """Plug each broken barrel bore solid, then re-cut it from clean primitives."""
    for x0 in BORE_X_STARTS:
        yz = Plane(origin=(x0, BORE_AXIS_YZ[0], BORE_AXIS_YZ[1]),
                   x_dir=(0, 1, 0), z_dir=(1, 0, 0))
        plug = yz * Cylinder(BORE_R_BULGE + 0.01, BORE_LEN, align=None)
        body = (body + plug) - _bore_tool(x0)
    return body


def _body_in_plate_frame():
    """solid[2] of the STEP, bores repaired, expressed in the plate frame."""
    compound = import_step(str(HERE / "source" / "vent_mount.step"))
    body = _repair_bores(compound.solids()[2])
    return _plate_plane().to_local_coords(body)


def _ball_mesh():
    """The ball STL as a mesh, its axis on the design z, seated on the plinth.

    The ball stays a mesh rather than becoming a B-rep because its 0.46 mm neck
    fin feathers tangentially into the stem flare near the base. OCCT reads that
    as an invalid solid the moment it is fused to anything -- the union came back
    `is_valid False` with two stray two-triangle shells on the fin's flank -- while
    the mesh itself is watertight and a single component. So the last union is
    manifold3d's, which is the boolean engine this toolchain names anyway.
    """
    m = trimesh.load(HERE / "source" / "ball_male_17mm.stl", process=True, force="mesh")
    m.apply_translation(-m.bounds[0])
    m.apply_translation([-BALL_AXIS_XY[0], -BALL_AXIS_XY[1], BALL_Z0])
    return m


def _plinth():
    """A tapered pad from inside the backplate up past the ball's base plate."""
    with BuildPart() as plinth:
        with BuildSketch(Plane.XY.offset(PLINTH_Z_LO)):
            RectangleRounded(
                BALL_BASE_X + 2 * PLINTH_FLARE,
                BALL_BASE_Y + 2 * PLINTH_FLARE,
                BALL_BASE_R + PLINTH_FLARE,
            )
        with BuildSketch(Plane.XY.offset(PLINTH_Z_HI)):
            RectangleRounded(
                BALL_BASE_X + 2 * PLINTH_LEDGE,
                BALL_BASE_Y + 2 * PLINTH_LEDGE,
                BALL_BASE_R + PLINTH_LEDGE,
            )
        loft()
    return plinth.part


def build_body():
    """Everything but the ball, exactly, as a B-rep solid in the plate frame."""
    body = _body_in_plate_frame()

    # 1. everything forward of the phone-rest face is the lower phone lip, and
    #    nothing else -- checked: the only solid[2] geometry at z > 0.05 lies at
    #    y in [-35.6, -25.0]. Cutting the half-space leaves that face flush.
    ahead = Box(140, 180, 120, align=None).locate(Location((-70, -90, 0)))
    body = body - ahead

    # 2. fill the ratchet channel the dropped top hook used to ride in, so the
    #    ball roots into 6 mm of plate rather than the channel floor's 2.5 mm.
    fill = Box(2 * FILL_HALF_X, FILL_Y_HI - FILL_Y_LO, PLATE_T, align=None).locate(
        Location((-FILL_HALF_X, FILL_Y_LO, -PLATE_T)))
    body = body + fill

    return body + _plinth()


def build():
    """The finished part, seated on the bed in its print orientation."""
    with tempfile.TemporaryDirectory() as tmp:
        stl = Path(tmp) / "body.stl"
        export_stl(build_body(), str(stl), tolerance=TESS_TOL, angular_tolerance=TESS_ANG)
        body = trimesh.load(stl, process=True, force="mesh")
    fused = trimesh.boolean.union([body, _ball_mesh()], engine="manifold")
    return to_printer(fused)


def to_printer(mesh):
    """Design frame -> print frame: ball axis up, part seated at z = 0."""
    out = mesh.copy()
    out.apply_transform(PRINT_ROTATION)
    out.apply_translation([0, 0, -out.bounds[0][2]])
    return out


# Print orientation: 90 deg about the design y, so the build direction runs
# across the plate and one leg's outer face lands on the bed. `orient_scan.py`
# scored this against 46 candidates. It is the only orientation under
# 2200 mm2 of overhang that has any real bed contact at all (1233 mm2), and it
# is the one that matters for function: the leg profiles -- every vent claw and
# every snap hook -- become pure extrusions perpendicular to the build
# direction, so the fit-critical features print with no support under them.
#
# The ball axis and the claw profiles want orthogonal build directions, so no
# orientation gets both. What this one costs is named in print_plan.md: a
# support tower under the upper leg's flat inner face, and support on the
# sphere's lower cap.
PRINT_ROTATION = [[0.0, 0.0, 1.0, 0.0],
                  [0.0, 1.0, 0.0, 0.0],
                  [-1.0, 0.0, 0.0, 0.0],
                  [0.0, 0.0, 0.0, 1.0]]

part = build()
