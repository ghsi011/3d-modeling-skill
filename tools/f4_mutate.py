#!/usr/bin/env python3
"""Every F4 row has to be independently failed by a mutation.

The ruling is explicit: *mutations must independently make each relevant row
fail*. A row nobody has seen fail is not a gate, it is a sentence. So this
generates a deliberately wrong candidate per row and asserts that the scorer
rejects it **and** names that row — not merely that it rejected something, which
would let one over-broad row cover for a blind one.

Answer-side and deliberately so: it builds wrong geometry, which nothing on the
candidate path may do.

One script, one report, on purpose. An earlier ingest agent ran twenty
measurements as twenty commands; because every turn re-sends the whole
conversation, turn count drives token cost roughly quadratically. Twenty results
from one invocation cost a fraction of the same twenty from twenty.

Usage:
    uv run --with embreex python tools/f4_mutate.py --source <source.step>
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "3d-modeling" / "scripts"))
sys.path.insert(0, str(ROOT / "tools"))

FIXTURE = ROOT / "benchmarks" / "e2e" / "f4-prusa-modify.json"

# The frozen edit, restated here only as the *baseline the mutations perturb*.
BASE = dict(face_x=29.680, w=20.00, h=4.00, r=1.00, cy=0.00, cz=10.50, depth=5.00)

# row it must break -> what to change
MUTATIONS = [
    ("slot_width_mm",   "width 20.00 -> 20.60",                dict(w=20.60)),
    ("slot_height_mm",  "height 4.00 -> 4.60",                 dict(h=4.60)),
    ("corner_radius_mm", "radius 1.00 -> 1.80",                dict(r=1.80)),
    ("centre_y_mm",     "centre y 0.00 -> +0.60",              dict(cy=0.60)),
    ("centre_z_mm",     "centre z 10.50 -> 11.20",             dict(cz=11.20)),
    ("through_the_wall", "blind pocket: depth 5.00 -> 1.20",   dict(depth=1.20)),
    ("source_equivalence_outside_the_mask",
     "correct slot PLUS a 6 mm hole at y=+30 outside the mask", dict(extra_hole=True)),
]


def write_3mf(out: Path, part: Path) -> Path:
    """A real 3MF, written by the pipeline's own writer rather than by this file.

    Through `make_3mf.py` as a subprocess because that is the archive the rest of
    the repository produces and reads. A 3MF hand-assembled here could differ
    from a shipped one in exactly the structural way the gate is meant to notice,
    and then the mutation would be proving something about this file.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    writer = ROOT / "skills" / "3d-modeling" / "scripts" / "make_3mf.py"
    subprocess.run([sys.executable, str(writer), str(out), f"part={part}"],
                   check=True, capture_output=True, text=True)
    return out


def build_variant(source: Path, out: Path, *, face_x, w, h, r, cy, cz, depth,
                  extra_hole=False):
    from build123d import (Cylinder, Location, Plane, RectangleRounded,
                           export_stl, extrude, import_step)
    shape = import_step(str(source))
    prof = Plane.YZ * Location((cy, cz, 0))
    tool = extrude(prof * RectangleRounded(w, h, r), amount=-(depth + 0.50))
    tool = tool.moved(Location((face_x + 0.50, 0, 0)))
    edited = shape - tool
    if extra_hole:
        # A through hole on the same wall, far outside the mask in Y.
        cyl = Cylinder(radius=3.0, height=12.0, rotation=(0, 90, 0))
        cyl = cyl.moved(Location((face_x - 2.0, 30.0, 12.0)))
        edited = edited - cyl
    out.parent.mkdir(parents=True, exist_ok=True)
    export_stl(edited, str(out), tolerance=0.01, angular_tolerance=0.1)
    return edited


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, type=Path)
    ap.add_argument("--work", type=Path,
                    default=Path(r"C:\Users\ghsi0\AppData\Local\Temp\claude"
                                 r"\C--github-3d-modeling-skill"
                                 r"\93be6d63-fa50-4d7d-9e38-03f31bd5ebd4\scratchpad\f4-mutations"))
    ap.add_argument("--pitch", type=float, default=0.05)
    a = ap.parse_args(argv)

    import trimesh
    import f4_score

    spec = json.loads(FIXTURE.read_text(encoding="utf-8"))
    src_mesh = f4_score._load(a.source)

    # The control: the honest edit must pass every row. Without it, a mutation
    # that fails could be failing because the harness is broken.
    honest = a.work / "honest" / "target.stl"
    build_variant(a.source, honest, **BASE)
    honest_rows = f4_score.score(src_mesh, trimesh.load(str(honest)), spec, a.pitch)
    honest_ok = all(r["ok"] for r in honest_rows)
    print(f"CONTROL  honest edit: {'ALL ROWS PASS' if honest_ok else 'FAILED — harness suspect'}")
    if not honest_ok:
        for r in honest_rows:
            if not r["ok"]:
                print(f"    unexpected FAIL {r['row']}: got {r['got']}")
        return 2
    print()

    width = max(len(t) for t, _, _ in MUTATIONS)
    caught = 0
    for target_row, why, over in MUTATIONS:
        params = dict(BASE)
        extra = over.pop("extra_hole", False) if "extra_hole" in over else False
        params.update(over)
        path = a.work / target_row / "target.stl"
        build_variant(a.source, path, extra_hole=extra, **params)
        rows = f4_score.score(src_mesh, trimesh.load(str(path)), spec, a.pitch)
        failed = [r["row"] for r in rows if not r["ok"]]
        hit = target_row in failed
        caught += hit
        mark = "KILLED" if hit else "SURVIVED"
        print(f"[{mark:8}] {target_row:<{width}}  {why}")
        print(f"{'':11}rows that failed: {failed or 'NONE'}")
        if not hit:
            got = next((r["got"] for r in rows if r["row"] == target_row), "?")
            print(f"{'':11}!! {target_row} still passed, got {got}")
    print()

    # --- the stale pre-edit 3MF -------------------------------------------
    #
    # Structurally unlike the rows above: nothing is wrong with the geometry the
    # scorer is handed. The candidate STL is the honest edit and passes every
    # geometric row. What is wrong is the artifact that would actually be
    # printed. This is the mutation the fixture explicitly owes, and before the
    # 3MF gate existed the scorer could not see it at all -- it took only
    # --source and --candidate, so a pre-edit archive sitting beside a correct
    # STL was invisible and the run reported success.
    honest_mesh = trimesh.load(str(honest))
    honest_3mf = write_3mf(a.work / "honest" / "candidate.3mf", honest)
    control = f4_score.three_mf_rows(honest_3mf, src_mesh, honest_mesh, spec, a.pitch)
    control_failed = [r["row"] for r in control if not r["ok"]]
    print(f"CONTROL  honest 3MF: "
          f"{'ALL ROWS PASS' if not control_failed else 'FAILED — gate suspect'}")
    if control_failed:
        # A gate that refuses the correct archive would "kill" the mutation
        # below for a reason that has nothing to do with staleness, which is the
        # shape of a control that was never taken.
        for r in control:
            if not r["ok"]:
                print(f"    unexpected FAIL {r['row']}: got {r['got']}")
        return 2

    stale_stl = a.work / "stale_3mf" / "pre_edit.stl"
    stale_stl.parent.mkdir(parents=True, exist_ok=True)
    src_mesh.export(str(stale_stl))
    stale_3mf = write_3mf(a.work / "stale_3mf" / "candidate.3mf", stale_stl)
    # The candidate STL is the honest edit; only the archive is pre-edit. So the
    # gate is asked whether the archive matches the candidate it shipped with.
    stale_rows = f4_score.three_mf_rows(stale_3mf, src_mesh, honest_mesh, spec, a.pitch)
    stale_failed = [r["row"] for r in stale_rows if not r["ok"]]
    # The row that OWNS this property, which is not the common
    # `three_mf_matches_the_accepted_stl`. That one bands the p99 surface
    # distance, and the slot is 79.14 mm2 of a 19,656.7 mm2 surface -- 0.403% --
    # so 99% of samples land on shared geometry and p99 reads 0.000042 mm for a
    # stale archive whose max is 1.997931 mm. Measured, not assumed: a wider
    # band would not help, because the band is not what is blind.
    target = "three_mf_carries_the_requested_edit"
    stale_hit = target in stale_failed
    caught += stale_hit
    print(f"[{'KILLED' if stale_hit else 'SURVIVED':8}] {target:<{width}}  "
          "correct candidate STL paired with a pre-edit 3MF")
    print(f"{'':11}rows that failed: {stale_failed or 'NONE'}")
    if not stale_hit:
        print(f"{'':11}!! the printed artifact was the unmodified part and the "
              "gate passed it")
    print()

    total = len(MUTATIONS) + 1
    print(f"{caught} of {total} mutations killed by their own row")
    return 0 if caught == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
