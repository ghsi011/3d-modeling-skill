#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import trimesh

SCHEMA_VERSION = 4
TOOL_VERSION = "1.0"

# H-03: fit strategy is print-engineer-owned and declared per interface in
# `print_plan_checks.json`. Every entry must name a fit type from this closed set --
# spanning clearance through interference/retention/compliant-mechanism intent, with no
# universal zero-interference rule.
INTERFACE_FIT_TYPES = frozenset(
    {
        "clearance",
        "transition",
        "interference",
        "elastic_contact",
        "crush_rib",
        "snap",
        "retention",
        "seal",
        "thread",
        "compliant",
    }
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def load_single_mesh(path: Path) -> trimesh.Trimesh:
    loaded = trimesh.load(path, force="mesh", process=True)
    if not isinstance(loaded, trimesh.Trimesh):
        raise ValueError(f"{path}: did not load as one mesh")
    return loaded


def _finite(x: Any) -> bool:
    """True only for a real, finite (non-NaN/Inf) int or float.

    Rejects bool (a `bool` is an `int` subclass but is never a magnitude),
    None/null, and any non-numeric type such as a numeric-looking string.
    Python's ``json`` module parses the non-standard tokens ``NaN``,
    ``Infinity``, and ``-Infinity`` into real floats by default, so a
    hand-authored or corrupted contract file can smuggle a non-finite value
    straight through a naive ``isinstance(x, float)`` check; this helper is
    the one place that closes that hole.
    """
    if isinstance(x, bool):
        return False
    if not isinstance(x, (int, float)):
        return False
    return math.isfinite(x)


def require_finite(value: Any, *, label: str) -> float:
    """Return `value` as a float, or raise ValueError naming `label`.

    Use for fields that must fail loudly (contract-structure problems), as
    opposed to the per-field messages the validators here collect into an
    `errors` list instead of raising.
    """
    if not _finite(value):
        raise ValueError(f"{label} must be a finite number, got {value!r}")
    return float(value)


def is_finite_rigid(matrix: Any) -> bool:
    """True iff `matrix` is a finite rigid-body 4x4 homogeneous transform.

    Requires: convertible to a 4x4 float array; every entry finite (no
    NaN/Inf/None/non-numeric); last row exactly ``[0, 0, 0, 1]``; the upper
    3x3 rotation block orthonormal (``R @ R.T == I``); and its determinant
    ``+1`` (a determinant of ``-1`` is a reflection, and anything else
    signals scale or shear). Never raises -- unusable input simply yields
    False so callers can attach their own field-naming error message.
    """
    try:
        arr = np.array(matrix, dtype=float)
    except (TypeError, ValueError):
        return False
    if arr.shape != (4, 4):
        return False
    if not np.all(np.isfinite(arr)):
        return False
    if not np.allclose(arr[3], (0.0, 0.0, 0.0, 1.0), atol=1e-9):
        return False
    rotation = arr[:3, :3]
    if not np.allclose(rotation @ rotation.T, np.eye(3), atol=1e-6):
        return False
    determinant = float(np.linalg.det(rotation))
    if not math.isclose(determinant, 1.0, abs_tol=1e-6):
        return False
    return True


def indexed_rows(
    rows: Any,
    *,
    label: str,
) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list):
        raise ValueError(f"{label}: expected a list")
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise ValueError(f"{label}: every row needs a string id")
        row_id = row["id"]
        if row_id in indexed:
            raise ValueError(f"{label}: duplicate id {row_id}")
        indexed[row_id] = row
    return indexed


def support_audit(
    *,
    stl_path: Path,
    plan_path: Path,
    rule_id: str,
) -> tuple[dict[str, Any], float]:
    plan = load_json(plan_path)
    rules = indexed_rows(plan.get("support_rules"), label="support_rules")
    if rule_id not in rules:
        raise ValueError(f"support_rules: missing id {rule_id}")
    rule = rules[rule_id]

    matrix_value = rule.get("model_to_printer_matrix")
    if not is_finite_rigid(matrix_value):
        raise ValueError(
            f"{rule_id}: model_to_printer_matrix must be a finite rigid 4x4 transform "
            "(all entries finite, last row [0, 0, 0, 1], orthonormal rotation, "
            "determinant +1 -- no scale/shear/reflection)"
        )
    matrix = np.array(matrix_value, dtype=float)
    bed_z = require_finite(rule.get("bed_z_mm"), label=f"{rule_id}: bed_z_mm")
    bed_tolerance = require_finite(rule.get("bed_tolerance_mm"), label=f"{rule_id}: bed_tolerance_mm")
    if bed_tolerance < 0:
        raise ValueError(f"{rule_id}: bed_tolerance_mm must be >= 0, got {bed_tolerance!r}")
    downward_normal_z_max = require_finite(
        rule.get("downward_normal_z_max"), label=f"{rule_id}: downward_normal_z_max"
    )
    maximum_area = require_finite(
        rule.get("max_out_of_limit_area_mm2"), label=f"{rule_id}: max_out_of_limit_area_mm2"
    )
    if maximum_area < 0:
        raise ValueError(f"{rule_id}: max_out_of_limit_area_mm2 must be >= 0, got {maximum_area!r}")

    mesh = load_single_mesh(stl_path)
    vertices = trimesh.transform_points(mesh.vertices, matrix)
    triangles = vertices[mesh.faces]
    edges_a = triangles[:, 1] - triangles[:, 0]
    edges_b = triangles[:, 2] - triangles[:, 0]
    crosses = np.cross(edges_a, edges_b)
    double_areas = np.linalg.norm(crosses, axis=1)
    valid = double_areas > 1e-12
    normals = np.zeros_like(crosses)
    normals[valid] = crosses[valid] / double_areas[valid, None]
    areas = double_areas * 0.5

    bed_contact = (
        np.max(np.abs(triangles[:, :, 2] - bed_z), axis=1) <= bed_tolerance
    )
    downward = normals[:, 2] <= downward_normal_z_max
    out_of_limit = valid & downward & ~bed_contact
    out_of_limit_area = float(areas[out_of_limit].sum())

    result = {
        "schema_version": SCHEMA_VERSION,
        "tool": "team_preflight.py",
        "tool_version": TOOL_VERSION,
        "kind": "downward-facing-surface-screen",
        "note": (
            "Conservative downward-facing-surface orientation screen; does NOT prove "
            "slicer supportability, bridgeability, or print success."
        ),
        "stl_path": stl_path.name,
        "stl_sha256": sha256_file(stl_path),
        "plan_checks_sha256": sha256_file(plan_path),
        "rule_id": rule_id,
        "matrix_sha256": canonical_sha256(rule["model_to_printer_matrix"]),
        "disposition": rule.get("disposition"),
        "bed_z_mm": bed_z,
        "bed_tolerance_mm": bed_tolerance,
        "downward_normal_z_max": downward_normal_z_max,
        "bed_contact_area_mm2": float(areas[valid & bed_contact].sum()),
        "out_of_limit_faces": int(np.count_nonzero(out_of_limit)),
        "out_of_limit_area_mm2": out_of_limit_area,
        "max_out_of_limit_area_mm2": maximum_area,
        "result": "PASS" if out_of_limit_area <= maximum_area + 1e-9 else "FAIL",
    }
    return result, maximum_area


def validate_interfaces(plan: dict[str, Any]) -> dict[str, Any]:
    """Validate the optional `print_plan_checks.json` `"interfaces"` array (H-03).

    `interfaces` is the machine-enforced per-interface fit-strategy declaration the print
    engineer owns (see team-contracts-v4.md `print_plan.md`): clearance, transition,
    interference, intended elastic contact, crush ribs, snap engagement, retention, seals,
    threads, and compliant mechanisms all share one schema -- there is no universal
    zero-interference rule.

    Backward-compatible: a plan with no `interfaces` key (or `null`) PASSes with an empty
    `interface_ids` list -- older plans are unaffected. When the key is present, every entry
    is fully validated and any malformed entry FAILs with a field/ID-named error. Reuses
    `_finite` for numeric fields so NaN/Inf/bool/None/non-numeric handling matches the rest
    of this module exactly.
    """
    errors: list[str] = []
    interface_ids: list[str] = []
    raw = plan.get("interfaces")

    if raw is not None:
        if not isinstance(raw, list):
            errors.append("interfaces: expected a list")
        else:
            seen_ids: set[str] = set()
            for index, row in enumerate(raw):
                if not isinstance(row, dict):
                    errors.append(f"interfaces[{index}]: expected an object")
                    continue
                interface_id = row.get("id")
                if not isinstance(interface_id, str) or not interface_id:
                    errors.append(f"interfaces[{index}]: id must be a non-empty string")
                    continue
                if interface_id in seen_ids:
                    errors.append(f"{interface_id}: duplicate interface id")
                    continue
                seen_ids.add(interface_id)
                interface_ids.append(interface_id)

                fit_type = row.get("fit_type")
                if fit_type not in INTERFACE_FIT_TYPES:
                    errors.append(
                        f"{interface_id}: fit_type must be one of "
                        f"{sorted(INTERFACE_FIT_TYPES)}, got {fit_type!r}"
                    )

                if not isinstance(row.get("contact_state"), str) or not row.get("contact_state"):
                    errors.append(f"{interface_id}: contact_state must be a non-empty string")

                min_ok = _finite(row.get("min_mm"))
                max_ok = _finite(row.get("max_mm"))
                if not min_ok:
                    errors.append(f"{interface_id}: min_mm must be a finite number")
                if not max_ok:
                    errors.append(f"{interface_id}: max_mm must be a finite number")
                if min_ok and max_ok:
                    min_mm = float(row["min_mm"])
                    max_mm = float(row["max_mm"])
                    if max_mm < min_mm:
                        errors.append(f"{interface_id}: max_mm must be >= min_mm")
                    # Only `clearance` is a pure gap that can never be negative. Every other
                    # fit type (interference, crush_rib, snap, retention, ...) may declare a
                    # deliberately negative, intersecting range -- that is the point of H-03's
                    # "no universal zero-interference rule".
                    if fit_type == "clearance" and (min_mm < 0 or max_mm < 0):
                        errors.append(
                            f"{interface_id}: clearance fit_type requires min_mm and "
                            "max_mm >= 0 (a clearance fit cannot be negative)"
                        )

                for field in ("motion_path", "material", "acceptance_method"):
                    if not isinstance(row.get(field), str) or not row.get(field):
                        errors.append(f"{interface_id}: {field} must be a non-empty string")

                if not isinstance(row.get("coupon_required"), bool):
                    errors.append(f"{interface_id}: coupon_required must be a boolean")

    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "team_preflight.py",
        "tool_version": TOOL_VERSION,
        "kind": "interfaces-validation",
        "interface_ids": sorted(interface_ids),
        "errors": errors,
        "result": "PASS" if not errors else "FAIL",
    }


def write_result(result: dict[str, Any], output: Path | None) -> None:
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if output is None:
        sys.stdout.write(payload)
    else:
        output.write_text(payload, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run deterministic team-pipeline non-acceptance gates."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    support = subparsers.add_parser(
        "support-audit",
        help=(
            "Downward-facing-surface orientation screen: measure transformed non-bed "
            "downward area on a re-imported STL. Subcommand name is kept for backward "
            "compatibility; the result's `kind` is `downward-facing-surface-screen`. "
            "This is a conservative geometric screen, not proof of slicer "
            "supportability, bridgeability, or print success."
        ),
    )
    support.add_argument("--stl", required=True, type=Path)
    support.add_argument("--plan", required=True, type=Path)
    support.add_argument("--rule-id", required=True)
    support.add_argument("--output", type=Path)

    interfaces = subparsers.add_parser(
        "validate-interfaces",
        help=(
            "Validate the optional print_plan_checks.json `interfaces` array (H-03 "
            "per-interface fit-strategy declaration). Absent `interfaces` PASSes "
            "(backward-compatible); a present array is fully validated."
        ),
    )
    interfaces.add_argument("--plan", required=True, type=Path)
    interfaces.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "support-audit":
            result, _ = support_audit(
                stl_path=args.stl.resolve(),
                plan_path=args.plan.resolve(),
                rule_id=args.rule_id,
            )
        else:
            result = validate_interfaces(load_json(args.plan.resolve()))
        write_result(result, args.output.resolve() if args.output else None)
        return 0 if result["result"] == "PASS" else 1
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        sys.stderr.write(f"team_preflight: {error}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
