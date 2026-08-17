#!/usr/bin/env python3
"""Write F4's candidate-visible request package, and nothing more.

The candidate gets the untouched source under a neutral name plus a brief. It
must not get the edited target, the mask, the calibration, the source's measured
geometry, or the wall thickness -- that last one is a source-derived ingest fact
the ruling classified as answer-side, because a nominal depth would hand over
part of the answer and throughness is topological anyway.

Every dimension in the brief is expressed from datums a candidate can find in
the file it was given: offsets from the source bounding box, not coordinates in
the original CAD frame, because nobody outside Prusa knows what `y = 0` meant to
the part's author.

Usage:
    uv run python tools/f4_request.py --source <pinned.step> --into <dir>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "benchmarks" / "e2e" / "f4-prusa-modify.json"

FORBIDDEN_IN_BRIEF = ("2.43", "2.4300", "24951", "24758", "192.31", "27.05", "10.3000")

BRIEF = """# One vent slot in a display box

## What this is

You are given an existing part as `source.step`. It is a real production
enclosure. I need one change to it and nothing else.

## The change

Cut a single **rounded rectangular slot** through the large flat outer wall that
faces the **+X** direction -- the wall whose outer surface is the highest X in
the part's bounding box.

* **Size**: {w:.2f} mm along Y by {h:.2f} mm along Z.
* **Corner radius**: {r:.2f} mm on all four corners.
* **Position**: centre the slot **{from_ymin:.2f} mm from the bounding box's
  Y-minimum plane** and **{above_zmin:.2f} mm above the bounding box's
  Z-minimum plane**. Take both datums from the file you were given.
* **Direction**: cut inward, toward -X.
* **Depth**: all the way **through that wall**. Not a pocket. The slot must open
  into the space behind the wall. Do not treat any particular depth as the
  target -- what matters is that the wall is fully penetrated.

Hold every dimension above to **+/- {tol:.2f} mm**, including the centre position.

## What must not change

**Everything else.** This is a modification of a working part, not a redesign.
No other face, hole, boss, rib, fillet or wall may move, grow, shrink or
disappear. If your process rebuilds the part rather than editing it, the
unchanged regions must still come out identical to the source within
measurement noise.

## Manufacturing

FDM, 0.4 mm nozzle, PLA. The slot is a vent, so it does not mate with anything
and needs no special tolerance beyond the figure above. Do not add draft,
chamfers or fillets that were not asked for.

## Deliverables

* the modified solid as **STL**
* the same solid as **3MF**

Report what you changed and what you measured.
"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, type=Path)
    ap.add_argument("--into", required=True, type=Path)
    a = ap.parse_args(argv)

    spec = json.loads(FIXTURE.read_text(encoding="utf-8"))
    edit, src = spec["edit"], spec["source"]

    raw = a.source.read_bytes()
    got = hashlib.sha256(raw).hexdigest()
    if got != src["sha256"]:
        raise SystemExit(f"source is not the pinned artifact\n  want {src['sha256']}\n  got  {got}")

    req = a.into / "request"
    req.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(a.source, req / "source.step")   # neutral name, identical bytes

    from_ymin = float(str(edit["centre_from_datums"]).split("mm")[0].strip())
    text = BRIEF.format(w=edit["slot_y_mm"], h=edit["slot_z_mm"],
                        r=edit["corner_radius_mm"], from_ymin=from_ymin,
                        above_zmin=edit["centre_canonical"]["z"],
                        tol=edit["cad_tolerance_mm"])

    # A leak here is not a typo, it is a broken benchmark, so it stops the write.
    leaked = [t for t in FORBIDDEN_IN_BRIEF if t in text]
    if leaked:
        raise SystemExit(f"brief would leak answer-side figures: {leaked}")

    (req / "brief.md").write_text(text, encoding="utf-8")
    print(f"wrote {req}")
    print(f"  source.step  {len(raw)} bytes, sha256 {got[:16]}...")
    print(f"  brief.md     {len(text)} chars, leak check clean")
    print(f"  candidate sees exactly: {sorted(p.name for p in req.iterdir())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
