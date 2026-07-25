#!/usr/bin/env python3
"""The plan a `DIRECT` job is gated against.

A `DIRECT` job states every design-driving dimension and recreates nothing from
evidence, so it runs no print-engineer dispatch. That leaves a hole the archived
runs walked straight into: with no plan bound, the designer wrote its own. Four
runs did, and every one of them set the support ceiling *after* reading its own
measurement -- 1799.73 observed against a declared 1850.0, 2034.33 against 2150.
One of them labelled the file `owner: cad-designer -- SELF-AUTHORED, NOT a
print-engineer artifact` and shipped it anyway. A threshold authored after the
measurement is a receipt, not a gate.

These numbers are a gate for exactly one reason: they were written here, ahead
of any part. That is also the whole constraint on what may live in this file --
a default may depend on the printer and the stated envelope, never on the
geometry being judged.

    python -m designer_toolkit plan-template --bbox 40 22 14 --out print_plan_checks.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .metrics import BARE_45_DEG

# 45 deg from vertical is the angle that always prints clean on a tuned 0.4 mm
# nozzle (fdm-design.md section 1). The toolkit's other constant, -0.73, is
# *steeper*, so it flags fewer faces; the more permissive angle is the wrong
# default for a gate nobody reviewed.
DEFAULT_DOWNWARD_NORMAL_Z_MAX = BARE_45_DEG

# Zero, and not a small allowance. A `DIRECT` part is simple and its dimensions
# are stated, so "prints without support" is a bar it should clear by
# reorienting or chamfering. A part that cannot is not a `DIRECT` part -- it
# needs a print engineer to declare where support may touch, which is a
# judgment this file must not fake. Escalating is the honest failure.
DEFAULT_MAX_OUT_OF_LIMIT_AREA_MM2 = 0.0

DEFAULT_BBOX_TOLERANCE_MM = 0.5


def direct_template(
    bbox_mm: tuple[float, float, float],
    *,
    tolerance_mm: float = DEFAULT_BBOX_TOLERANCE_MM,
    job_id: str = "direct",
    nozzle_mm: float = 0.4,
    material: str = "PETG",
) -> dict[str, Any]:
    """A bound plan for a job whose dimensions were stated, not measured."""
    x, y, z = (float(v) for v in bbox_mm)
    if min(x, y, z) <= 0:
        raise ValueError(f"bbox must be positive in every axis, got {bbox_mm}")
    return {
        "contract": "print-plan",
        "contract_version": 4,
        "job_id": job_id,
        "revision": 1,
        # Not `print-engineer`: nobody engineered this part. Naming the source
        # is what keeps the distinction visible downstream, where a plan that
        # merely *looks* authored is indistinguishable from one that was.
        "owner": "builtin-direct-template",
        "threshold_source": "builtin-default",
        "process": [{"printer_material_nozzle": f"{material}; {nozzle_mm}mm nozzle"}],
        "expected_bbox_mm": {"x": x, "y": y, "z": z},
        "bbox_tolerance_mm": float(tolerance_mm),
        "support_rules": [
            {
                "id": "S-01",
                "disposition": "SELF_SUPPORT_REQUIRED",
                "downward_normal_z_max": DEFAULT_DOWNWARD_NORMAL_Z_MAX,
                "max_out_of_limit_area_mm2": DEFAULT_MAX_OUT_OF_LIMIT_AREA_MM2,
            }
        ],
        # Empty on purpose, and not a stub to fill in. An interface or an edge
        # band is a fit decision about a specific part; inventing one here would
        # be this file doing the very thing it exists to prevent.
        "interfaces": [],
        "edges": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bbox", type=float, nargs=3, required=True,
                        metavar=("X", "Y", "Z"), help="stated overall size in mm")
    parser.add_argument("--tolerance", type=float, default=DEFAULT_BBOX_TOLERANCE_MM)
    parser.add_argument("--job-id", default="direct")
    parser.add_argument("--nozzle", type=float, default=0.4)
    parser.add_argument("--material", default="PETG")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    plan = direct_template(tuple(args.bbox), tolerance_mm=args.tolerance,
                           job_id=args.job_id, nozzle_mm=args.nozzle,
                           material=args.material)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(f"{args.out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
