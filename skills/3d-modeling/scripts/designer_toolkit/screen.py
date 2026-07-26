#!/usr/bin/env python3
"""Bundle the one question a measurement cannot ask: what is here that nobody named?

Every check in this toolkit is conditioned on a declaration. `feature-*` rows
measure what the plan names, `envelope` compares a declared size, `fit` a
declared band. Geometry nobody declared is invisible to all of it -- a 4 mm post
standing in a bin floor passed twenty-seven green checks, an exact bounding box,
a watertight verdict and a matching bed-contact area.

A render is conditioned on nothing, which is why the charter has always ended
with "look at it". The trouble was cost: looking meant a dispatch, so it happened
once at the end if at all. Measured, the look itself takes eight seconds -- what
made it expensive was working out what to ask.

So this writes the ask down. It collects the images and states the part's
declared inventory, then poses the question in the direction no check can go:
not "is each declared feature present" but "is anything present that is not
declared". Hand the bundle to whoever, or whatever, is doing the looking.

It renders nothing and decides nothing. The answer is a judgment and stays one.

    python <skill>/scripts/dt.py screen <project-dir> --out <dir>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _declared(project: Path) -> list[str]:
    """What the part is, in words a reader can match against a picture.

    Read from `dimensions.md`'s blind-build completeness table, whose second
    column the contract already requires to be a feature's name, count and
    function -- "base feet, 2, locate the bin in a baseplate".

    The first draft of this listed the measured rows instead: areas at z heights
    and hole coordinates. That is an accurate inventory and a useless
    description, and it measurably degraded the screen -- given the numeric list
    a reader flagged a structural bridge and walked straight past a post standing
    in the middle of the compartment, which the same reader had found in eight
    seconds when told the part was "a plain open box with one empty compartment
    and a flat floor". A picture is matched against a mental image, not a table.
    """
    sheet = project / "dimensions.md"
    try:
        lines = sheet.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    said: list[str] = []
    inside = False
    for line in lines:
        if line.startswith("## "):
            inside = line.strip().lower().startswith("## blind-build")
            continue
        if not inside or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2 or cells[0].startswith("-") or cells[0].lower() == "feature id":
            continue
        said.append(cells[1] if len(cells) < 3 else f"{cells[1]} ({cells[2]})")
    return said


def bundle(project: Path, out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    commission = _read_json(project / "commission.json") or {}
    export = commission.get("evidence", {}).get("export", {})
    bbox = export.get("bbox_mm") or {}

    images = sorted(str(p) for p in (project / "renders").glob("*.png")) \
        if (project / "renders").is_dir() else []

    declared = _declared(project)
    inventory = "\n".join(f"- {line}" for line in declared) or (
        "- (the sheet's blind-build table is empty, so nothing at all was declared by "
        "name -- treat everything you see as unaccounted for)")

    question = f"""# Visual screen

Attached are technical renders of a 3D-printed part. Look at every view.

The part is {bbox.get('x', '?')} x {bbox.get('y', '?')} x {bbox.get('z', '?')} mm.
Everything it is supposed to have was declared in advance, and this is the whole
list:

{inventory}

**Is there anything visible that is not on that list?**

Answer in one short paragraph. If you see something extra, say what it looks
like, roughly where it is, and which view shows it. If you see nothing extra,
say so plainly.

Do not verify the list -- every item on it has already been measured. The only
thing being asked is what is present that nobody named, because no measurement
in this pipeline can ask that: each one checks a feature somebody declared, and
geometry nobody declared is invisible to all of them.
"""
    (out_dir / "question.md").write_text(question, encoding="utf-8")

    return {
        "question": str(out_dir / "question.md"),
        "images": images,
        "declared_features": len(declared),
        "note": ("Hand the question and the images to a fresh reader. Measured, this "
                 "takes seconds; what used to make it expensive was deciding what to "
                 "ask, and that is now written down."),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("project", type=Path)
    parser.add_argument("--out", type=Path, required=True,
                        help="where to write the question; never the project root")
    args = parser.parse_args(argv)

    project = args.project.resolve()
    out = args.out.resolve()
    if out == project:
        sys.stderr.write("screen: --out must not be the project root\n")
        return 2
    if not (project / "commission.json").is_file():
        sys.stderr.write(f"screen: no commission.json in {project}; nothing has been "
                         "gated, so there is no declared inventory to screen against\n")
        return 2

    result = bundle(project, out)
    sys.stdout.write(json.dumps(result, indent=2) + "\n")
    if not result["images"]:
        sys.stderr.write(
            "screen: this project has no renders, so the one piece of evidence that is "
            "conditioned on nothing does not exist. Re-run the gate without --no-render.\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
