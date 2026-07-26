#!/usr/bin/env python3
"""Ask the delivered solid a question, with the instrument the gate uses.

The charter tells a verifier to compare the sheet against built geometry, and
separately not to hand-roll anything. Those collided: there was no way to ask
"how much material is at this height" or "where is that hole", so the only route
was writing a sectioning script -- which is exactly what three paragraphs warn
against, and for good reason. One archived run's own sampler read 137% high
against known nominals and the run widened its bands until the wrong numbers
passed.

It is also the gap that let a real defect through. A Gridfinity bin shipped its
magnet pockets 0.25 mm off on both axes; the reference gives 13.0 mm two
independent ways and the part was built at 12.75. Eight green checks agreed,
because each measured the pocket *at the position the designer declared*. The
verifier that caught it had to write its own sections to do so.

Nothing here decides anything. It reports numbers, using the same code the gate
uses, so a verifier and a designer cannot disagree by instrument.

`probe`, not `measure`: the package already exports a `measure` function from
`metrics`, and `measure` is one of seven per-check verbs retired for teaching
three runs to assemble their own gate. This is a read-only instrument for a
reader who already has a gated part, which is a different thing.

    dt.py probe part.stl --section 12.5
    dt.py probe part.stl --hole 8,11 --z 2.5 --nominal 4.5
    dt.py probe part.stl --hole=-8,13 --z 1.2 --nominal 6.5   (negatives need =)
    dt.py probe part.stl --profile
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ._bootstrap import as_mesh


def _pair(text: str) -> tuple[float, float]:
    parts = [p for p in text.replace(",", " ").split() if p]
    if len(parts) != 2:
        raise ValueError(f"expected 'x,y', got {text!r}")
    return float(parts[0]), float(parts[1])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stl", type=Path)
    parser.add_argument("--section", type=float, action="append", metavar="Z",
                        help="material area on this Z plane, net of holes; repeatable")
    parser.add_argument("--hole", type=_pair, metavar="X,Y",
                        help="measure the void at this position. Write a negative "
                             "coordinate as --hole=-8,13: argparse reads a leading minus "
                             "as another option, and parts centred on the origin have "
                             "negative coordinates constantly")
    parser.add_argument("--z", type=float, help="height for --hole")
    parser.add_argument("--nominal", type=float,
                        help="the diameter --hole is supposed to be, for the window size")
    parser.add_argument("--profile", action="store_true",
                        help="material area at evenly spaced heights, declared by nobody")
    parser.add_argument("--slices", type=int, default=28)
    args = parser.parse_args(argv)

    if not args.stl.is_file():
        sys.stderr.write(f"probe: no such file: {args.stl}\n")
        return 2
    if not (args.section or args.hole or args.profile):
        sys.stderr.write("probe: ask for something -- --section, --hole or --profile\n")
        return 2
    if args.hole and args.z is None:
        sys.stderr.write("probe: --hole needs --z, the height to measure it at\n")
        return 2

    from . import features

    mesh = as_mesh(str(args.stl))
    out: dict[str, Any] = {"stl": str(args.stl)}

    if args.section:
        out["sections"] = [{"z": z, "area_mm2": round(features.solid_area_mm2(mesh, z), 4)}
                           for z in args.section]
    if args.hole:
        x, y = args.hole
        # Default window from the nominal, the same rule the feature check uses;
        # without a nominal, guess from the part and say so, because a window
        # that is not buried in material reports a confident number computed
        # partly from fresh air.
        nominal = args.nominal or float(min(mesh.extents)) / 8.0
        radius = nominal * 0.7
        try:
            diameter = features.bore_diameter_mm(mesh, x, y, args.z, radius)
            off_x, off_y = features.bore_offset_mm(mesh, x, y, args.z, radius)
            out["hole"] = {
                "at": [x, y], "z": args.z, "window_r": round(radius, 4),
                "diameter_mm": round(diameter, 4),
                "centre_offset_mm": [round(off_x, 4), round(off_y, 4)],
                "nominal_assumed": args.nominal is None,
            }
        except features.Indeterminate as exc:
            out["hole"] = {"at": [x, y], "z": args.z, "indeterminate": str(exc)}
    if args.profile:
        out["profile"] = features.slice_profile(mesh, slices=args.slices)

    sys.stdout.write(json.dumps(out, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
