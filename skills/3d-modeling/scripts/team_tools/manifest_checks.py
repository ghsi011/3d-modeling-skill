"""Filesystem/mesh-backed checks for artifact_manifest artifacts.

These checks require touching disk (existence, hashing, mesh bounds) and are
therefore kept separate from the pure structural validators in validators.py,
which only look at the parsed JSON. Uses trimesh/numpy only, per the
dependency constraint (no OCP dependency for STEP; STEP loading is
attempted opportunistically and skipped, not failed, when unavailable).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
import trimesh

from common import INCH_TO_MM, Issue, error, is_hash_format, normalize_project_path, sha256_file, warning

# Tolerances for the "obvious 25.4x mismatch" heuristic.
_SCALE_BLOCK_TOL = 0.005  # within 0.5% of an exact 25.4x ratio -> hard error
_SCALE_WARN_TOL = 0.03  # within 3% -> warning
_BBOX_ABS_TOL_MM = 0.05
_BBOX_REL_TOL = 0.01


def _connected_component_count(mesh: trimesh.Trimesh) -> int:
    """Connected components of ``mesh`` counted on face adjacency (two faces are
    connected when they share an edge) -- the same number
    ``trimesh.Trimesh.split(only_watertight=False)`` reports.

    Not routed through ``mesh.split``: that path builds a submesh per component
    and needs scipy (``csgraph``), plus networkx for any component with a hole.
    Where either is missing trimesh raises and the count degrades to "no
    observation", so a two-body STL declared as one body would sail through this
    check. Pure numpy keeps the answer identical on every install.

    Intentionally duplicated from ``mesh_io.connected_component_count`` rather
    than imported: this package is self-contained on stdlib + trimesh + numpy
    and must import cleanly with only ``team_tools/`` on sys.path (see the
    bootstrap note in ``contracts.py``). Keep the two in step.
    """
    face_count = int(np.asarray(mesh.faces).shape[0])
    if face_count == 0:
        return 0
    adjacency = np.asarray(mesh.face_adjacency, dtype=np.int64).reshape((-1, 2))
    if adjacency.shape[0] == 0:
        return face_count  # no shared edges: every face is its own component
    left = adjacency[:, 0]
    right = adjacency[:, 1]
    labels = np.arange(face_count, dtype=np.int64)
    while True:
        previous = labels
        hooked = labels.copy()
        np.minimum.at(hooked, left, labels[right])
        np.minimum.at(hooked, right, labels[left])
        while True:  # pointer jumping: labels[i] <= i, so this terminates
            jumped = hooked[hooked]
            if np.array_equal(jumped, hooked):
                break
            hooked = jumped
        labels = hooked
        if np.array_equal(labels, previous):
            return int(np.unique(labels).size)


def _load_mesh_bounds(path: Path) -> trimesh.Trimesh | None:
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
    path_issues, full_path = normalize_project_path(
        raw_path, field="path", where=where, project_dir=project_dir
    )
    if path_issues or full_path is None:
        return issues

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
            observed_components = _connected_component_count(mesh)
        except Exception:  # noqa: BLE001 - defensive; odd meshes must not crash the check
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
    tight_scale = False
    mismatched_axes: list[int] = []
    for axis in range(3):
        declared = float(declared_extent[axis])
        actual = float(actual_extent[axis])
        if actual <= 0:
            continue
        ratio = declared / actual
        for candidate_ratio, direction in ((INCH_TO_MM, "declared looks like inches, actual mesh is mm"), (1.0 / INCH_TO_MM, "declared looks like mm, actual mesh is inches")):
            relative_error = abs(ratio - candidate_ratio) / candidate_ratio
            if relative_error <= _SCALE_WARN_TOL:
                scale_flags.append(f"axis {axis}: {direction} (ratio {ratio:.4f})")
                # Promotion to a hard error is decided from the ratio of the SAME
                # axis that raised the flag. Deciding it from a separate sweep over
                # all three axes lets an unrelated axis that happens to sit near
                # 25.4x turn another axis's loose warning into a block.
                tight_scale = tight_scale or relative_error <= _SCALE_BLOCK_TOL
        absolute_diff = abs(declared - actual)
        if absolute_diff > max(_BBOX_ABS_TOL_MM, _BBOX_REL_TOL * actual):
            mismatched_axes.append(axis)

    if scale_flags:
        detail = "; ".join(scale_flags)
        if tight_scale:
            issues.append(error("UNIT_SCALE_MISMATCH", where, f"obvious inch/mm (25.4x) mismatch: {detail}"))
        else:
            issues.append(warning("POSSIBLE_UNIT_SCALE_MISMATCH", where, f"possible inch/mm (25.4x) mismatch: {detail}"))
    # Unconditional, NOT an elif on the scale flag: a near-25.4x ratio on one axis
    # used to suppress the bbox error on every other axis, so a declared extent
    # that was 5x wrong on axis 1 shipped with nothing but a scale warning. The
    # two findings are independent -- a mesh can be both mis-scaled and wrong.
    if mismatched_axes:
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
    silently skipped (informational), matching the "trimesh only if
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

        _, stl_path = normalize_project_path(
            stl_row.get("path"), field="path", where=f"{where}.artifacts[{stl_row.get('id')}]",
            project_dir=project_dir
        )
        _, step_path = normalize_project_path(
            step_row.get("path"), field="path", where=f"{where}.artifacts[{step_row.get('id')}]",
            project_dir=project_dir
        )
        if stl_path is None or step_path is None:
            continue
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


def _current_candidate_stl(manifest: dict[str, Any] | None, *, project_dir: Path) -> Path | None:
    """The project-relative path of the candidate STL the final-prep bindings
    must match, or None when it cannot be resolved unambiguously.

    The artifact_manifest is the authoritative record of the current candidate:
    Its top-level ``candidate_id`` must name one real ``role: candidate`` STL
    row. A missing, mismatched, ambiguous, traversal-escaping or symlinked row
    is unresolved; the binding check fails closed rather than guessing which
    candidate a sign-off meant. The path is run through
    ``normalize_project_path`` before it is opened.
    """
    if not isinstance(manifest, dict):
        return None
    artifacts = [row for row in (manifest.get("artifacts") or []) if isinstance(row, dict)]
    row: dict[str, Any] | None = None
    candidate_id = manifest.get("candidate_id")
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        return None
    row = next((a for a in artifacts if a.get("id") == candidate_id), None)
    if (row is None or row.get("role") != "candidate"
            or row.get("type") != "stl"):
        return None
    _, safe_path = normalize_project_path(
        row.get("path"), field="path", where="artifact_manifest", project_dir=project_dir
    )
    return safe_path


def _recompute_hash_binding(
    *, declared: Any, field: str, where: str, target: Path | None, artifact_label: str
) -> list[Issue]:
    """Compare one declared binding hash against the recomputed sha256 of the
    artifact it names, and flag a mismatch. This is the manifest's HASH_MISMATCH
    philosophy one contract layer up: the entered hash is never trusted.

    Two cases degrade to a silent skip rather than a finding. A hash that is not
    well-formed is left to validators.py, which already emits BAD_HASH /
    MISSING_FIELD on that exact field -- a second finding would only add noise.
    An artifact that cannot be resolved or whose file is absent is also skipped:
    when a manifest row names a missing file the manifest's own ARTIFACT_MISSING
    already reports it, so recomputing here would only duplicate that error.
    """
    if not is_hash_format(declared):
        return []
    if target is None:
        return [error(
            "BINDING_UNRESOLVED", f"{where}.{field}",
            f"cannot resolve the {artifact_label}; binding fails closed",
        )]
    if not target.is_file():
        return [error(
            "BINDING_UNRESOLVED", f"{where}.{field}",
            f"the {artifact_label} is absent at {target}; binding fails closed",
        )]
    computed = sha256_file(target)
    if declared == computed:
        return []
    return [
        error(
            "BINDING_STALE",
            f"{where}.{field}",
            f"declared {declared} != current {computed} for the {artifact_label} "
            "(binding is to a stale or wrong artifact; never trust an entered hash)",
        )
    ]


def check_final_prep_bindings(
    *,
    final_print_prep: dict[str, Any] | None,
    final_prep_review: dict[str, Any] | None,
    final_print_prep_path: Path | None,
    manifest: dict[str, Any] | None,
    project_dir: Path,
) -> dict[str, list[Issue]]:
    """Recompute the final-prep bound hashes against the CURRENT artifacts.

    The final-prep contracts are Markdown, so validators.py can only check their
    bound hashes for *format*: a well-formed hash that no longer matches the
    bytes it names still passes. That is the whole failure this closes -- a
    ``final_prep_review`` can declare a ``candidate_stl_sha256`` /
    ``final_print_prep_sha256`` that looks like a hash but points at a stale or
    wrong artifact, so the sign-off reads as a binding that holds when it binds
    to nothing current. Recompute each from the bytes on disk and compare, the
    same way check_artifact_files recomputes a manifest row's sha256.

    Both artifact kinds are hashed by their file bytes (``sha256_file``): the
    candidate STL, and the ``final_print_prep.md`` contract -- which is how the
    validate receipt and the review author hash that contract elsewhere. Returns
    issues keyed by contract so each attaches to the file that declared the bad
    binding.
    """
    out: dict[str, list[Issue]] = {"final_print_prep": [], "final_prep_review": []}
    candidate_stl = _current_candidate_stl(manifest, project_dir=project_dir)
    final_prep_target = final_print_prep_path
    if final_prep_target is not None:
        try:
            relative = os.path.relpath(final_prep_target, project_dir)
        except ValueError:
            relative = ".."
        _, final_prep_target = normalize_project_path(
            relative, field="final_print_prep", where="final_print_prep",
            project_dir=project_dir
        )

    if isinstance(final_print_prep, dict):
        out["final_print_prep"] += _recompute_hash_binding(
            declared=final_print_prep.get("candidate_stl_sha256"),
            field="candidate_stl_sha256",
            where="final_print_prep",
            target=candidate_stl,
            artifact_label="current candidate STL",
        )

    if isinstance(final_prep_review, dict):
        out["final_prep_review"] += _recompute_hash_binding(
            declared=final_prep_review.get("candidate_stl_sha256"),
            field="candidate_stl_sha256",
            where="final_prep_review",
            target=candidate_stl,
            artifact_label="current candidate STL",
        )
        out["final_prep_review"] += _recompute_hash_binding(
            declared=final_prep_review.get("final_print_prep_sha256"),
            field="final_print_prep_sha256",
            where="final_prep_review",
            target=final_prep_target,
            artifact_label="current final_print_prep.md",
        )
    return out
