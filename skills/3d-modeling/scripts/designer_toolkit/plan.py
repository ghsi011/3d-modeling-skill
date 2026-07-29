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

    uv run --project <skill> --frozen python <skill>/scripts/dt.py plan template --bbox 40 22 14 --out print_plan_checks.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

from .metrics import DEFAULT_BED_TOLERANCE_MM, DEFAULT_BED_Z_MM
from .metrics import DEFAULT_DOWNWARD_NORMAL_Z_MAX as _SCREEN

# -0.73, not the bare 45 deg value. A self-supporting 45 deg chamfer -- the
# standard fix for an overhang, and the one this template's own failure advice
# recommends -- tessellates to normal_z = -0.70710678118, which is *below* the
# bare value of -0.70710678 and so gets flagged by it. Screening at the bare
# angle therefore rejects correct geometry and sends the designer to add the
# very feature that caused the failure. The margin is what -0.73 exists for.
DEFAULT_DOWNWARD_NORMAL_Z_MAX = _SCREEN

# Zero, and not a small allowance. A `DIRECT` part is simple and its dimensions
# are stated, so "prints without support" is a bar it should clear by
# reorienting or chamfering. A part that cannot is not a `DIRECT` part -- it
# needs a print engineer to declare where support may touch, which is a
# judgment this file must not fake. Escalating is the honest failure.
DEFAULT_MAX_OUT_OF_LIMIT_AREA_MM2 = 0.0

DEFAULT_BBOX_TOLERANCE_MM = 0.5

_CONSEQUENCES = ("INCONSEQUENTIAL", "CONSEQUENTIAL")

# A DIRECT part is modelled in its print orientation -- seated on the bed, so
# its minimum Z is 0 -- which makes model and printer frames coincide. Declaring
# the identity explicitly still matters: the audit reads the matrix rather than
# assuming one. A model centred on the origin instead will read as unsupported
# across its whole underside, correctly: half of it is below the bed.
IDENTITY_TRANSFORM = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]


def direct_template(
    bbox_mm: tuple[float, float, float],
    *,
    tolerance_mm: float = DEFAULT_BBOX_TOLERANCE_MM,
    job_id: str = "direct",
    nozzle_mm: float = 0.4,
    material: str = "PETG",
    dimensions_revision: int = 1,
    bodies: int = 1,
    updated_utc: str = "1970-01-01T00:00:00Z",
    consequence: str | None = None,
    assembly_mesh_paths: tuple[str, ...] = (),
    assembly_overlap_budget_mm3: float | None = None,
) -> dict[str, Any]:
    """A bound plan for a job whose dimensions were stated, not measured."""
    x, y, z = (float(v) for v in bbox_mm)
    if min(x, y, z) <= 0:
        raise ValueError(f"bbox must be positive in every axis, got {bbox_mm}")
    plan = {
        "contract": "print-plan",
        "contract_version": 4,
        "job_id": job_id,
        "revision": 1,
        # Not `print-engineer`: nobody engineered this part. Naming the source
        # is what keeps the distinction visible downstream, where a plan that
        # merely *looks* authored is indistinguishable from one that was.
        "owner": "builtin-direct-template",
        "status": "ACCEPTED",
        "dimensions_revision": dimensions_revision,
        "updated_utc": updated_utc,
        "threshold_source": "builtin-default",
        # How many separate solids the delivered STL should contain. One, unless
        # the part is deliberately several -- a box too big for the bed comes as
        # segments, and a slicer separates them. Declared here rather than
        # inferred from the mesh, because "however many came out" is not a check.
        "expected_bodies": int(bodies),
        "process": [{"printer_material_nozzle": f"{material}; {nozzle_mm}mm nozzle"}],
        "expected_bbox_mm": {"x": x, "y": y, "z": z},
        "bbox_tolerance_mm": float(tolerance_mm),
        "support_rules": [
            {
                "id": "S-01",
                "disposition": "SELF_SUPPORT_REQUIRED",
                # `support_audit` requires all three unconditionally and raises
                # before it ever reads the mesh. A template that omits them
                # produces a plan no candidate can satisfy -- which is what one
                # measured run spent 55 minutes discovering.
                "model_to_printer_matrix": IDENTITY_TRANSFORM,
                "bed_z_mm": DEFAULT_BED_Z_MM,
                "bed_tolerance_mm": DEFAULT_BED_TOLERANCE_MM,
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
    if consequence is not None:
        plan["consequence"] = consequence
    if assembly_mesh_paths:
        plan["assembly_mesh_paths"] = [str(path) for path in assembly_mesh_paths]
    if assembly_overlap_budget_mm3 is not None:
        plan["assembly_overlap_budget_mm3"] = float(assembly_overlap_budget_mm3)
    return plan


# `BRIDGED_NO_SUPPORT` is a third thing, and the schema had no room for it. A
# magnet-pocket roof spans a gap with no scaffold under it: the slicer prints no
# support, so `SUPPORT_ALLOWED` is false, and the area is not zero, so
# `SELF_SUPPORT_REQUIRED` is false too. A Gridfinity bin hit this and had to
# declare SUPPORT_ALLOWED and then write an `allowed_contact_class` saying no
# face may take support -- a field used for the exact opposite of its purpose,
# on a feature that is on tens of thousands of published parts.
_DISPOSITIONS = ("SELF_SUPPORT_REQUIRED", "SUPPORT_ALLOWED", "BRIDGED_NO_SUPPORT")


def validate_plan(plan: dict[str, Any]) -> list[str]:
    """Every way a plan can be unbuildable, checked before a designer reads it.

    None of them need geometry, so every one can be settled before a designer
    reads the plan. Leaving them to the finished candidate cost one archived run
    39 minutes: `commission` passed a plan whose single support rule declared
    `SUPPORT_ALLOWED` with no `allowed_contact_class`, and the designer learned
    the plan was incomplete only after building against it.
    None of these depend on the geometry, so none of them need to wait for it.
    """
    problems: list[str] = []
    rules = plan.get("support_rules") or []
    if not rules:
        problems.append("no support_rules: nothing constrains the print orientation")

    seen: set[str] = set()
    for index, rule in enumerate(rules):
        rule_id = str(rule.get("id") or f"support_rules[{index}]")
        if rule_id in seen:
            problems.append(f"{rule_id}: duplicate support rule id")
        seen.add(rule_id)

        disposition = rule.get("disposition")
        if disposition not in _DISPOSITIONS:
            problems.append(f"{rule_id}: disposition must be one of {', '.join(_DISPOSITIONS)}")
        elif disposition == "SELF_SUPPORT_REQUIRED":
            if float(rule.get("max_out_of_limit_area_mm2", 0.0)) > 0:
                problems.append(
                    f"{rule_id}: SELF_SUPPORT_REQUIRED means zero out-of-limit area, "
                    f"but declares {rule['max_out_of_limit_area_mm2']} mm2"
                )
        elif disposition == "BRIDGED_NO_SUPPORT":
            if float(rule.get("max_out_of_limit_area_mm2", 0.0)) <= 0:
                problems.append(
                    f"{rule_id}: BRIDGED_NO_SUPPORT needs a positive "
                    "max_out_of_limit_area_mm2 -- it is the budget for area that bridges, "
                    "and a zero budget is SELF_SUPPORT_REQUIRED under another name")
            if rule.get("allowed_contact_class"):
                problems.append(
                    f"{rule_id}: BRIDGED_NO_SUPPORT must not name an allowed_contact_class. "
                    "Nothing touches these faces -- that is what distinguishes it from "
                    "SUPPORT_ALLOWED, and declaring one asks a print engineer to review "
                    "support contacts that will never exist")
        elif not rule.get("allowed_contact_class"):
            problems.append(
                f"{rule_id}: SUPPORT_ALLOWED needs allowed_contact_class naming which "
                "faces may take support"
            )

        # Required by `team_preflight.support_audit` unconditionally -- it raises
        # on the plan before reading any mesh, so their absence is a plan defect
        # that no geometry can work around.
        for field in ("model_to_printer_matrix", "bed_z_mm", "bed_tolerance_mm"):
            if rule.get(field) is None:
                problems.append(
                    f"{rule_id}: missing {field}, which support_audit requires before it "
                    "reads the candidate at all"
                )
        tolerance = rule.get("bed_tolerance_mm")
        if tolerance is not None and float(tolerance) < 0:
            problems.append(f"{rule_id}: bed_tolerance_mm must be >= 0, got {tolerance}")

        angle = rule.get("downward_normal_z_max")
        if angle is not None and not (-1.0 <= float(angle) <= 0.0):
            problems.append(f"{rule_id}: downward_normal_z_max must lie in [-1, 0], got {angle}")

    bbox = plan.get("expected_bbox_mm")
    if bbox is None:
        problems.append(
            "no expected_bbox_mm: the envelope check silently skips, which is how a "
            "candidate shipped 31% too thick"
        )
    elif any(float(bbox.get(axis, 0.0)) <= 0 for axis in "xyz"):
        problems.append(f"expected_bbox_mm must be positive in every axis, got {bbox}")
    else:
        # A tolerance nobody bounds is a check nobody performs. `--tolerance 1e9`
        # validated clean and then passed a part 100% over its envelope, with the
        # receipt counting `envelope` as having run -- which defeats the one
        # check whose reason for existing is a candidate that shipped 31% too
        # thick. Ten percent of the smallest declared axis is far looser than any
        # real band and still forbids that.
        band = plan.get("bbox_tolerance_mm")
        smallest = min(float(bbox[axis]) for axis in "xyz")
        if band is None or float(band) <= 0:
            problems.append(
                f"bbox_tolerance_mm must be positive, got {band}: a zero or absent band "
                "makes the envelope check unable to fail")
        elif float(band) > 0.1 * smallest:
            problems.append(
                f"bbox_tolerance_mm {band} is more than a tenth of the smallest declared "
                f"axis ({smallest}), so the envelope check cannot reject anything a "
                "reader would call the wrong size")

    bodies = plan.get("expected_bodies")
    if bodies is not None and (not isinstance(bodies, int) or bodies < 1):
        problems.append(
            f"expected_bodies must be a positive whole number, got {bodies!r}: it says how "
            "many solids the part is meant to be, and the `solid` check compares against it")

    consequence = plan.get("consequence")
    if consequence is not None and consequence not in _CONSEQUENCES:
        problems.append(f"consequence must be one of {', '.join(_CONSEQUENCES)}, got {consequence!r}")

    assembly_paths = plan.get("assembly_mesh_paths")
    budget = plan.get("assembly_overlap_budget_mm3")
    if assembly_paths is not None:
        if not isinstance(assembly_paths, (list, tuple)) or not assembly_paths:
            problems.append("assembly_mesh_paths must be a non-empty list of paths")
        elif any(not isinstance(path, str) or not path.strip() for path in assembly_paths):
            problems.append("assembly_mesh_paths must contain non-empty string paths")
        if budget is None:
            problems.append("assembly_overlap_budget_mm3 is required when assembly_mesh_paths "
                            "are declared")
    elif budget is not None:
        problems.append("assembly_overlap_budget_mm3 requires assembly_mesh_paths")
    if budget is not None:
        try:
            numeric_budget = float(budget)
        except (TypeError, ValueError):
            numeric_budget = math.nan
        if not math.isfinite(numeric_budget) or numeric_budget < 0:
            problems.append("assembly_overlap_budget_mm3 must be a finite non-negative number")

    return problems


def _cmd_template(args: argparse.Namespace) -> int:
    plan = direct_template(tuple(args.bbox), tolerance_mm=args.tolerance,
                           job_id=args.job_id, nozzle_mm=args.nozzle,
                           material=args.material,
                           dimensions_revision=args.dimensions_revision,
                           bodies=args.bodies, updated_utc=args.updated_utc,
                           consequence=args.consequence,
                           assembly_mesh_paths=tuple(args.assembly_mesh_paths),
                           assembly_overlap_budget_mm3=args.assembly_overlap_budget_mm3)
    payload = json.dumps(plan, indent=2) + "\n"
    # `--out -` means stdout, portably. Windows has no `/dev/stdout`, and a bare
    # `Path("-").write_text` would create a file literally named `-` in the job
    # folder. Writing the plan to the text stream instead lets a caller pipe it
    # (`... plan template --bbox ... --out - | ...`) on any platform. The plan is
    # ASCII (json.dumps escapes non-ASCII), so no console code page can mangle it.
    if str(args.out) == "-":
        sys.stdout.write(payload)
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(payload, encoding="utf-8")
    sys.stdout.write(f"{args.out}\n")
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    problems = validate_plan(json.loads(args.path.read_text(encoding="utf-8")))
    if not problems:
        sys.stdout.write(f"OK: {args.path} is buildable\n")
        return 0
    sys.stderr.write(f"{args.path} cannot be built against:\n")
    for problem in problems:
        sys.stderr.write(f"  {problem}\n")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    template = sub.add_parser("template", help="write the built-in DIRECT plan")
    template.add_argument("--bbox", type=float, nargs=3, required=True,
                          metavar=("X", "Y", "Z"), help="stated overall size in mm")
    template.add_argument("--tolerance", type=float, default=DEFAULT_BBOX_TOLERANCE_MM)
    template.add_argument("--job-id", default="direct")
    template.add_argument("--nozzle", type=float, default=0.4)
    template.add_argument("--material", default="PETG")
    template.add_argument("--bodies", type=int, default=1,
                          help="separate solids the STL should contain; more than one only "
                               "when the part is deliberately segmented")
    template.add_argument("--dimensions-revision", type=int, default=1)
    template.add_argument("--updated-utc", default="1970-01-01T00:00:00Z",
                          help="injected, never wall-clock, so a rerun is byte-identical")
    template.add_argument("--consequence", choices=_CONSEQUENCES,
                          help="optional consequence class carried into the plan")
    template.add_argument("--assembly-mesh-path", action="append", default=[],
                          dest="assembly_mesh_paths",
                          help="optional assembly mesh path; repeat for each mating mesh")
    template.add_argument("--assembly-overlap-budget-mm3", type=float,
                          help="maximum allowed candidate/assembly overlap volume")
    template.add_argument("--out", type=Path, required=True)
    template.set_defaults(func=_cmd_template)

    check = sub.add_parser("check", help="reject an unbuildable plan before a designer reads it")
    check.add_argument("path", type=Path)
    check.set_defaults(func=_cmd_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
