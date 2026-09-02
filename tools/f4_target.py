#!/usr/bin/env python3
"""F4's hidden target: the pinned Prusa MINI display box with one slot cut.

Answer-side. This is the *only* thing that knows what the edited part looks
like, and it never reaches the candidate -- the candidate is handed the
untouched source and the request, and nothing else.

**The edit is expressed from source-visible datums, not from the original CAD
origin.** A candidate cannot know what `y = 0` signified to Prusa's author, so
the request states the slot centre as an offset from the source bounding box
and the generator resolves that offset the same way. On the pinned source the
two agree exactly -- `Y-min + 47.83 = 0.00`, `Z-min + 10.50 = 10.50` -- and the
generator asserts that agreement rather than assuming it, so a source whose
bounding box moved would stop this script instead of quietly producing a target
in the wrong place.

**The cut goes deeper than the wall on purpose.** "Through the complete wall"
is a topological requirement, not a nominal depth. The tool cuts 5.00 mm inward
from the outer face, traversing the 2.4300 mm wall and extending 2.5700 mm into
the measured-clear void, which the ingest survey found to be at least 8 mm deep
across the whole safe window. So it removes exactly the wall and then nothing:
the result is identical to a cut of precisely 2.4300 mm, and it does not depend
on the wall thickness being uniform to the micron.

**The wall thickness is answer-side.** 2.4300 mm is a source-derived ingest
fact, not a candidate-visible design requirement. It lives here and in the
fixture record as a sanity check on the pinned source and target; the request
the candidate reads says only *cut through the complete wall*, and no predicate
scores a candidate on reproducing a nominal 2.4300 mm depth.

**This generator is not byte-deterministic, and the fixture must not claim it
is.** The honest claim is narrower: *the geometric operation is deterministic;
serialization and tessellation bytes are not.* Two equivalent runs differ
because the STEP header embeds a build timestamp and the STL's floats move --
measured at 8 bytes of 831,884. The artifact that gets scored is therefore a
stored, hash-pinned external file, exactly as F1 pins its reference, and
"rerunning this script reproduces that SHA-256" is never asserted anywhere.

Usage:
    uv run python tools/f4_target.py --source <source.step> --out <dir>

Writes `target.step` and `target.stl` and prints the SHA-256 of each, which is
what the fixture freezes.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

# --- the frozen edit -------------------------------------------------------
# Ruled and frozen 2026-08-17 after the ingest survey; every number below is
# either measured from the pinned source or ruled against it.
SOURCE_SHA256 = "0cbce7139089d4feb493b02a0f27a429514f3251af5969f166aed4c6ce705855"
SOURCE_BYTES = 321781

FACE_X_MM = 29.680          # the +X outer wall plane, measured
SLOT_Y_MM = 20.00           # slot length along Y
SLOT_Z_MM = 4.00            # slot height along Z
CORNER_R_MM = 1.00          # rounded rectangle
CENTRE_FROM_YMIN_MM = 47.83  # datum-expressed: offset from the bbox Y-min plane
CENTRE_ABOVE_ZMIN_MM = 10.50  # datum-expressed: height above the Z-min base plane
CUT_DEPTH_MM = 5.00         # inward from the outer face: 2.4300 of wall,
                            # then 2.5700 into void measured at >= 8 mm clear

# What the source must be for those numbers to mean anything.
#
# 2.4300, not the 2.25 the first ingest survey reported. That survey marched
# inward on a 0.25 mm grid and took the first void sample as the far face, which
# quantises thickness down by up to one step -- it read 2.25 for a wall that is
# 2.43. The correction was forced by arithmetic rather than noticed: the cut
# removed 192.317 mm^3 where 2.25 mm predicts 178.07, and 192.317 / 79.1416 is
# 2.4300 exactly. A ray cast at 45 points across the slot footprint then gives
# min = mean = max = 2.4300, so the wall is uniform and the coarse march was the
# only thing that was wrong.
EXPECT_WALL_MM = 2.4300
EXPECT_BBOX = {           # mm, from the ingest survey
    "x": (-34.930, 29.680),
    "y": (-47.830, 65.030),
    "z": (0.000, 30.000),
}
BBOX_TOL_MM = 0.01

STL_TOLERANCE = 0.01
STL_ANGULAR_TOLERANCE = 0.1


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(source: Path, out_dir: Path) -> dict[str, str]:
    from build123d import (Location, Plane, RectangleRounded, export_step,
                           export_stl, extrude, import_step)

    raw = source.read_bytes()
    got = hashlib.sha256(raw).hexdigest()
    if got != SOURCE_SHA256:
        raise SystemExit(
            f"source is not the pinned artifact\n  expected {SOURCE_SHA256}\n"
            f"  got      {got}\n  ({len(raw)} bytes, expected {SOURCE_BYTES})")

    shape = import_step(str(source))
    bb = shape.bounding_box()

    # The datums the request names must actually be where the survey found
    # them. Without this the offsets below would silently address a different
    # part of a different solid.
    for axis, (lo, hi) in EXPECT_BBOX.items():
        got_lo = getattr(bb.min, axis.upper())
        got_hi = getattr(bb.max, axis.upper())
        if abs(got_lo - lo) > BBOX_TOL_MM or abs(got_hi - hi) > BBOX_TOL_MM:
            raise SystemExit(
                f"source bounding box moved on {axis}: expected {lo}..{hi}, "
                f"got {got_lo:.3f}..{got_hi:.3f}")

    # Resolve the datum-expressed centre, then assert it lands where the frozen
    # canonical coordinates say. These are two routes to one number and the
    # fixture quotes both, so they are checked against each other here.
    centre_y = bb.min.Y + CENTRE_FROM_YMIN_MM
    centre_z = bb.min.Z + CENTRE_ABOVE_ZMIN_MM
    if abs(centre_y - 0.00) > 1e-6 or abs(centre_z - 10.50) > 1e-6:
        raise SystemExit(
            f"datum-expressed centre does not resolve to the frozen canonical "
            f"coordinates: got y={centre_y:.6f} z={centre_z:.6f}, "
            f"expected y=0.000000 z=10.500000")

    # A rounded rectangle in the YZ plane, extruded along -X from just outside
    # the wall so the boolean has no coincident-face ambiguity at the surface.
    start_x = FACE_X_MM + 0.50
    profile = Plane.YZ * Location((centre_y, centre_z, 0))
    sketch = profile * RectangleRounded(SLOT_Y_MM, SLOT_Z_MM, CORNER_R_MM)
    tool = extrude(sketch, amount=-(CUT_DEPTH_MM + 0.50))
    tool = tool.moved(Location((start_x, 0, 0)))

    edited = shape - tool

    out_dir.mkdir(parents=True, exist_ok=True)
    step_out = out_dir / "target.step"
    stl_out = out_dir / "target.stl"
    export_step(edited, str(step_out))
    export_stl(edited, str(stl_out),
               tolerance=STL_TOLERANCE, angular_tolerance=STL_ANGULAR_TOLERANCE)

    removed = shape.volume - edited.volume
    nominal = (SLOT_Y_MM * SLOT_Z_MM
               - (4 - 3.141592653589793) * CORNER_R_MM ** 2) * EXPECT_WALL_MM
    return {
        "source_sha256": got,
        "target_step_sha256": sha256(step_out),
        "target_stl_sha256": sha256(stl_out),
        "source_volume_mm3": f"{shape.volume:.4f}",
        "target_volume_mm3": f"{edited.volume:.4f}",
        "removed_mm3": f"{removed:.4f}",
        "removed_nominal_mm3": f"{nominal:.4f}",
        "centre_y_mm": f"{centre_y:.4f}",
        "centre_z_mm": f"{centre_z:.4f}",
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Generate F4's hidden target")
    ap.add_argument("--source", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(argv)
    facts = build(args.source, args.out)
    width = max(len(k) for k in facts)
    for k, v in facts.items():
        print(f"{k:<{width}} : {v}")


if __name__ == "__main__":
    main()
