"""Filesystem/mesh-backed checks for artifact_manifest artifacts.

These checks require touching disk (existence, hashing, mesh bounds) and are
therefore kept separate from the pure structural validators in validators.py,
which only look at the parsed JSON. Uses trimesh/numpy only, per the
dependency constraint (no cadquery/OCP dependency for STEP; STEP loading is
attempted opportunistically and skipped, not failed, when unavailable).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import trimesh

from common import INCH_TO_MM, Issue, error, sha256_file, warning

# Tolerances for the "obvious 25.4x mismatch" heuristic.
_SCALE_BLOCK_TOL = 0.005  # within 0.5% of an exact 25.4x ratio -> hard error
_SCALE_WARN_TOL = 0.03  # within 3% -> warning
_BBOX_ABS_TOL_MM = 0.05
_BBOX_REL_TOL = 0.01


def _load_mesh_bounds(path: Path) -> tuple[float, float, float] | None:
    """Best-effort mesh load returning (min, max) triples, or None if this file
    type/toolchain cannot be loaded (e.g. STEP without an OCC/cascadio backend).
    Never raises: a failed opportunistic load is reported as informational only.
    """
    try:
        # process=True (matches team_preflight.py's load_single_mesh): welds
        # coincident vertices so face-adjacency-based connected-component
        # analysis is meaningful. Without it every triangle looks isolated.
        loaded = trimesh.load(path, force="mesh", process=True)
    except Exception:  # noqa: BLE001 - opportunistic; any failure means "skip"
        return None
    if not isinstance(loaded, trimesh.Trimesh) or loaded.vertices.shape[0] == 0:
        return None
    return loaded


def check_artifact_files(
    *, artifact: dict[str, Any], artifact_id: str, project_dir: Path, where: str
) -> list[Issue]:
    """Exists / hash-matches / mesh-bbox / component-count / unit-scale checks
    for one artifact row that already passed structural validation.
    """
    issues: list[Issue] = []
    raw_path = artifact.get("path")
    if not isinstance(raw_path, str):
        return issues  # already flagged by validators.py
    full_path = (project_dir / raw_path.replace("\\", "/")).resolve(strict=False)

    if not full_path.is_file():
        issues.append(error("ARTIFACT_MISSING", f"{where}.path", f"declared artifact file not found: {raw_path}"))
        return issues

    computed_hash = sha256_file(full_path)
    declared_hash = artifact.get("sha256")
    if isinstance(declared_hash, str) and declared_hash != computed_hash:
        issues.append(
            error(
                "HASH_MISMATCH",
                f"{where}.sha256",
                f"declared {declared_hash} != computed {computed_hash} (never trust an entered hash)",
            )
        )

    artifact_type = artifact.get("type")
    mesh = None
    if artifact_type == "stl":
        mesh = _load_mesh_bounds(full_path)
        if mesh is None:
            issues.append(error("ARTIFACT_UNREADABLE", f"{where}.path", f"could not load {raw_path} as one mesh"))
        else:
            issues += _check_mesh_against_declared(
                mesh=mesh, artifact=artifact, where=where
            )
    elif artifact_type == "step":
        # Opportunistic only: never block on a missing STEP backend.
        mesh = _load_mesh_bounds(full_path)

    return issues


def _check_mesh_against_declared(*, mesh: trimesh.Trimesh, artifact: dict[str, Any], where: str) -> list[Issue]:
    issues: list[Issue] = []
    actual_min = mesh.bounds[0]
    actual_max = mesh.bounds[1]
    actual_extent = actual_max - actual_min

    bbox = artifact.get("bbox")
    if isinstance(bbox, dict) and isinstance(bbox.get("min"), list) and isinstance(bbox.get("max"), list):
        declared_min = np.asarray(bbox["min"], dtype=float)
        declared_max = np.asarray(bbox["max"], dtype=float)
        if declared_min.shape == (3,) and declared_max.shape == (3,):
            declared_extent = declared_max - declared_min
            issues += _compare_extents(
                declared_extent=declared_extent, actual_extent=actual_extent, where=f"{where}.bbox"
            )

    expected_components = artifact.get("expected_components")
    if isinstance(expected_components, int) and not isinstance(expected_components, bool):
        try:
            observed_components = len(mesh.split(only_watertight=False))
        except Exception:  # noqa: BLE001 - defensive; trimesh split can raise on odd meshes
            observed_components = None
        if observed_components is not None and observed_components != expected_components:
            issues.append(
                error(
                    "COMPONENT_COUNT_MISMATCH",
                    f"{where}.expected_components",
                    f"declared {expected_components}, observed {observed_components} connected component(s)",
                )
            )
    return issues


def _compare_extents(*, declared_extent: np.ndarray, actual_extent: np.ndarray, where: str) -> list[Issue]:
    issues: list[Issue] = []
    scale_flags: list[str] = []
    mismatched_axes: list[int] = []
    for axis in range(3):
        declared = float(declared_extent[axis])
        actual = float(actual_extent[axis])
        if actual <= 0:
            continue
        ratio = declared / actual if actual != 0 else float("inf")
        for candidate_ratio, direction in ((INCH_TO_MM, "declared looks like inches, actual mesh is mm"), (1.0 / INCH_TO_MM, "declared looks like mm, actual mesh is inches")):
            relative_error = abs(ratio - candidate_ratio) / candidate_ratio
            if relative_error <= _SCALE_WARN_TOL:
                scale_flags.append(f"axis {axis}: {direction} (ratio {ratio:.4f})")
        absolute_diff = abs(declared - actual)
        if absolute_diff > max(_BBOX_ABS_TOL_MM, _BBOX_REL_TOL * actual):
            mismatched_axes.append(axis)

    if scale_flags:
        tight = any(
            abs(float(declared_extent[axis]) / float(actual_extent[axis]) - candidate) / candidate <= _SCALE_BLOCK_TOL
            for axis in range(3)
            if float(actual_extent[axis]) > 0
            for candidate in (INCH_TO_MM, 1.0 / INCH_TO_MM)
        )
        detail = "; ".join(scale_flags)
        if tight:
            issues.append(error("UNIT_SCALE_MISMATCH", where, f"obvious inch/mm (25.4x) mismatch: {detail}"))
        else:
            issues.append(warning("POSSIBLE_UNIT_SCALE_MISMATCH", where, f"possible inch/mm (25.4x) mismatch: {detail}"))
    elif mismatched_axes:
        issues.append(
            error(
                "BBOX_MISMATCH",
                where,
                f"declared bbox extent does not match the re-imported mesh on axis/axes {mismatched_axes}: "
                f"declared={declared_extent.tolist()}, actual={actual_extent.tolist()}",
            )
        )
    return issues


def compare_paired_stl_step(
    *,
    artifacts: dict[str, dict[str, Any]],
    project_dir: Path,
    where: str,
) -> list[Issue]:
    """When an STL artifact declares paired_artifact_id pointing at a STEP
    artifact (or vice versa) and both bounding boxes can be established, flag a
    mismatch. STEP loading commonly requires an optional OCC backend
    (e.g. cascadio) that may not be installed; when it cannot be loaded this is
    silently skipped (informational), matching the "trimesh/cadquery only if
    trivially available, else STL bbox + declared" instruction -- it never
    blocks on a missing optional backend.
    """
    issues: list[Issue] = []
    seen_pairs: set[frozenset[str]] = set()
    for artifact_id, artifact in artifacts.items():
        paired_id = artifact.get("paired_artifact_id")
        if not isinstance(paired_id, str) or paired_id not in artifacts:
            continue
        pair_key = frozenset({artifact_id, paired_id})
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)
        other = artifacts[paired_id]
        types = {artifact.get("type"), other.get("type")}
        if types != {"stl", "step"}:
            continue
        stl_row = artifact if artifact.get("type") == "stl" else other
        step_row = other if artifact.get("type") == "stl" else artifact

        stl_path = project_dir / str(stl_row.get("path", "")).replace("\\", "/")
        step_path = project_dir / str(step_row.get("path", "")).replace("\\", "/")
        if not stl_path.is_file() or not step_path.is_file():
            continue
        stl_mesh = _load_mesh_bounds(stl_path)
        step_mesh = _load_mesh_bounds(step_path)
        if stl_mesh is None or step_mesh is None:
            continue  # opportunistic only
        stl_extent = stl_mesh.bounds[1] - stl_mesh.bounds[0]
        step_extent = step_mesh.bounds[1] - step_mesh.bounds[0]
        pair_where = f"{where}.artifacts[{stl_row.get('id')}<->{step_row.get('id')}]"
        for axis in range(3):
            diff = abs(float(stl_extent[axis]) - float(step_extent[axis]))
            if diff > max(_BBOX_ABS_TOL_MM, _BBOX_REL_TOL * float(step_extent[axis] or 1.0)):
                issues.append(
                    error(
                        "STL_STEP_BBOX_MISMATCH",
                        pair_where,
                        f"axis {axis} STL extent {stl_extent[axis]:.4f} mm vs STEP extent "
                        f"{step_extent[axis]:.4f} mm",
                    )
                )
    return issues
