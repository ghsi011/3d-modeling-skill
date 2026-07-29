"""Deterministic receipt builders for the `validate` and `hash` CLI commands.

Every receipt carries tool+schema version, job id, validated paths, observed
revisions, computed sha256s, per-file results, warning/error ids, an injected
(never wall-clock) timestamp, and the invocation. The validate receipt is
explicit that it does not prove geometric/manufacturing correctness.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

try:
    from .common import TOOL_NAME, TOOL_SCHEMA_VERSION, TOOL_VERSION, has_errors, resolve_timestamp, sha256_file, sort_issues
    from .project import ProjectValidation, load_project, run_manifest_checks
except ImportError:  # pragma: no cover - direct script/test compatibility
    from common import TOOL_NAME, TOOL_SCHEMA_VERSION, TOOL_VERSION, has_errors, resolve_timestamp, sha256_file, sort_issues
    from project import ProjectValidation, load_project, run_manifest_checks

DISCLAIMER = (
    "This receipt confirms contract structure, identifiers, cross-references, "
    "declared-vs-computed hashes, and revision bindings only. It does NOT prove "
    "geometric or manufacturing correctness -- passing this gate is necessary "
    "evidence, not proof. Agents retain engineering judgment."
)

CONTRACT_ORDER = ("job_state", "dimensions", "print_plan", "verification_report", "artifact_manifest")


def build_validate_receipt(
    project_dir: Path, *, timestamp: str | None, argv: list[str], required: Sequence[str] = ()
) -> tuple[dict[str, Any], ProjectValidation]:
    project = load_project(project_dir, required=required)
    run_manifest_checks(project)

    all_issues = sort_issues(project.all_issues())

    job_state_file = project.files["job_state"]
    job_id = job_state_file.data.get("job_id") if isinstance(job_state_file.data, dict) else None

    validated_paths = sorted(
        contract_file.filename for contract_file in project.files.values() if contract_file.present
    )
    observed_revisions = {
        key: contract_file.data.get("revision")
        for key, contract_file in project.files.items()
        if isinstance(contract_file.data, dict) and "revision" in contract_file.data
    }

    computed_sha256: dict[str, str] = {}
    for contract_file in project.files.values():
        if contract_file.present and contract_file.path.is_file():
            computed_sha256[contract_file.filename] = sha256_file(contract_file.path)
    manifest_file = project.files["artifact_manifest"]
    artifact_ids: dict[str, Any] = manifest_file.index.get("artifact_ids", {}) if manifest_file.data else {}
    for artifact_id, row in sorted(artifact_ids.items()):
        raw_path = row.get("path")
        if isinstance(raw_path, str):
            full_path = (project_dir / raw_path.replace("\\", "/")).resolve(strict=False)
            if full_path.is_file():
                computed_sha256[raw_path] = sha256_file(full_path)

    results = {
        key: ("FAIL" if has_errors(contract_file.issues) else "PASS")
        for key, contract_file in project.files.items()
    }
    results["overall"] = "PASS" if all(value == "PASS" for value in results.values()) else "FAIL"

    receipt = {
        "tool": TOOL_NAME,
        "tool_version": TOOL_VERSION,
        "schema_version": TOOL_SCHEMA_VERSION,
        "kind": "validate-receipt",
        "job_id": job_id,
        "project_dir": _display_path(project_dir),
        # What the caller demanded be present, recorded next to what was
        # actually read: a reviewer can tell a deliberately narrow validate
        # from one that gated on nothing at all.
        "required_contracts": sorted(set(required)),
        "validated_paths": validated_paths,
        "observed_revisions": {key: observed_revisions.get(key) for key in CONTRACT_ORDER if key in observed_revisions},
        "computed_sha256": dict(sorted(computed_sha256.items())),
        "results": results,
        "warning_ids": sorted(issue.id for issue in all_issues if issue.severity == "warning"),
        "error_ids": sorted(issue.id for issue in all_issues if issue.severity == "error"),
        "issues": [issue.to_dict() for issue in all_issues],
        "timestamp": resolve_timestamp(timestamp),
        "invocation": {"command": "validate", "argv": list(argv)},
        "disclaimer": DISCLAIMER,
    }
    return receipt, project


def build_hash_receipt(project_dir: Path, *, timestamp: str | None, argv: list[str]) -> dict[str, Any]:
    project = load_project(project_dir)

    contract_sha256: dict[str, str] = {}
    for contract_file in project.files.values():
        if contract_file.present and contract_file.path.is_file():
            contract_sha256[contract_file.filename] = sha256_file(contract_file.path)

    artifact_sha256: dict[str, str | None] = {}
    hash_mismatches: list[str] = []
    manifest_file = project.files["artifact_manifest"]
    artifact_ids: dict[str, Any] = manifest_file.index.get("artifact_ids", {}) if manifest_file.data else {}
    for artifact_id, row in sorted(artifact_ids.items()):
        raw_path = row.get("path")
        if not isinstance(raw_path, str):
            continue
        full_path = (project_dir / raw_path.replace("\\", "/")).resolve(strict=False)
        if not full_path.is_file():
            artifact_sha256[artifact_id] = None
            continue
        computed = sha256_file(full_path)
        artifact_sha256[artifact_id] = computed
        declared = row.get("sha256")
        if isinstance(declared, str) and declared != computed:
            hash_mismatches.append(artifact_id)

    receipt = {
        "tool": TOOL_NAME,
        "tool_version": TOOL_VERSION,
        "schema_version": TOOL_SCHEMA_VERSION,
        "kind": "hash-receipt",
        "project_dir": _display_path(project_dir),
        "contract_sha256": dict(sorted(contract_sha256.items())),
        "artifact_sha256": dict(sorted(artifact_sha256.items())),
        "hash_mismatches": sorted(hash_mismatches),
        "timestamp": resolve_timestamp(timestamp),
        "invocation": {"command": "hash", "argv": list(argv)},
        "note": "Hashes are always recomputed from bytes on disk; declared hashes are never trusted.",
    }
    return receipt


def _display_path(path: Path) -> str:
    return str(path)
