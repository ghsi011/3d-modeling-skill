"""`status` command: report each contract's revision plus stale/invalidated
downstream bindings (bound revision/hash vs. current revision/hash).

Read-only: a stale or invalidated binding is reported, never rewritten. Agents
own the decision to re-bind after reviewing what changed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from common import sha256_file
from project import load_project

CONTRACT_ORDER = ("job_state", "dimensions", "print_plan", "verification_report", "artifact_manifest")


def _hash_prefix(value: Any) -> str:
    return value[:12] if isinstance(value, str) and value else "<missing>"


def _artifact_by_role(manifest: dict[str, Any] | None, role: str) -> dict[str, Any] | None:
    if not manifest:
        return None
    for artifact in manifest.get("artifacts") or []:
        if isinstance(artifact, dict) and artifact.get("role") == role:
            return artifact
    return None


def _artifact_by_id(manifest: dict[str, Any] | None, artifact_id: Any) -> dict[str, Any] | None:
    if not manifest or not isinstance(artifact_id, str):
        return None
    for artifact in manifest.get("artifacts") or []:
        if isinstance(artifact, dict) and artifact.get("id") == artifact_id:
            return artifact
    return None


def _current_hash_of(artifact: dict[str, Any] | None, project_dir: Path) -> str | None:
    if not artifact:
        return None
    raw_path = artifact.get("path")
    if not isinstance(raw_path, str):
        return None
    full_path = (project_dir / raw_path.replace("\\", "/")).resolve(strict=False)
    if not full_path.is_file():
        return None
    return sha256_file(full_path)


def compute_status(project_dir: Path) -> list[dict[str, Any]]:
    project = load_project(project_dir)
    files = project.files
    rows: list[dict[str, Any]] = []

    for key in CONTRACT_ORDER:
        contract_file = files[key]
        label = key.upper()
        if not contract_file.present:
            rows.append({"contract": label, "status": "MISSING", "detail": f"{contract_file.filename} not found"})
            continue
        if contract_file.data is None:
            rows.append({"contract": label, "status": "UNREADABLE", "detail": contract_file.filename})
            continue
        revision = contract_file.data.get("revision")
        detail = f"revision {revision}" if revision is not None else "no revision field (artifact_manifest is unrevisioned)"
        rows.append({"contract": label, "status": "OK", "detail": detail})

    job_state = files["job_state"].data
    dimensions = files["dimensions"].data
    print_plan = files["print_plan"].data
    verification_report = files["verification_report"].data
    artifact_manifest = files["artifact_manifest"].data

    if print_plan and dimensions:
        bound, current = print_plan.get("dimensions_revision"), dimensions.get("revision")
        if bound != current:
            rows.append(
                {
                    "contract": "PRINT_PLAN",
                    "status": "STALE",
                    "detail": f"bound to dimensions r{bound}, current r{current}",
                }
            )

    reference_artifact = _artifact_by_role(artifact_manifest, "reference")
    current_reference_hash = _current_hash_of(reference_artifact, project_dir)
    if print_plan and current_reference_hash is not None:
        bound = print_plan.get("reference_sha256")
        if bound != current_reference_hash:
            rows.append(
                {
                    "contract": "PRINT_PLAN",
                    "status": "INVALIDATED",
                    "detail": f"reference_sha256 bound {_hash_prefix(bound)}, current {_hash_prefix(current_reference_hash)}",
                }
            )

    if verification_report and dimensions:
        bound, current = verification_report.get("dimensions_revision"), dimensions.get("revision")
        if bound != current:
            rows.append(
                {
                    "contract": "VERIFICATION_REPORT",
                    "status": "STALE",
                    "detail": f"bound to dimensions r{bound}, current r{current}",
                }
            )
    if verification_report and print_plan:
        bound, current = verification_report.get("print_plan_revision"), print_plan.get("revision")
        if bound != current:
            rows.append(
                {
                    "contract": "VERIFICATION_REPORT",
                    "status": "STALE",
                    "detail": f"bound to print_plan r{bound}, current r{current}",
                }
            )
    if verification_report and current_reference_hash is not None:
        bound = verification_report.get("reference_sha256")
        if bound != current_reference_hash:
            rows.append(
                {
                    "contract": "VERIFICATION_REPORT",
                    "status": "INVALIDATED",
                    "detail": f"reference_sha256 bound {_hash_prefix(bound)}, current {_hash_prefix(current_reference_hash)}",
                }
            )
    if verification_report:
        candidate_artifact = _artifact_by_id(artifact_manifest, verification_report.get("candidate_id"))
        current_candidate_hash = _current_hash_of(candidate_artifact, project_dir)
        if current_candidate_hash is not None:
            bound = verification_report.get("candidate_stl_sha256")
            if bound != current_candidate_hash:
                rows.append(
                    {
                        "contract": "VERIFICATION_REPORT",
                        "status": "INVALIDATED",
                        "detail": (
                            f"candidate_stl_sha256 bound {_hash_prefix(bound)}, "
                            f"current {_hash_prefix(current_candidate_hash)}"
                        ),
                    }
                )

    if artifact_manifest:
        revisions_now = {
            "job_state": job_state.get("revision") if job_state else None,
            "dimensions": dimensions.get("revision") if dimensions else None,
            "print_plan": print_plan.get("revision") if print_plan else None,
        }
        for artifact in artifact_manifest.get("artifacts") or []:
            if not isinstance(artifact, dict):
                continue
            source_revisions = artifact.get("source_revisions")
            if not isinstance(source_revisions, dict):
                continue
            for contract_key in sorted(source_revisions):
                bound_rev = source_revisions[contract_key]
                current_rev = revisions_now.get(contract_key)
                if current_rev is not None and bound_rev != current_rev:
                    rows.append(
                        {
                            "contract": "ARTIFACT_MANIFEST",
                            "status": "STALE",
                            "detail": (
                                f"artifact '{artifact.get('id')}' bound to {contract_key} "
                                f"r{bound_rev}, current r{current_rev}"
                            ),
                        }
                    )

    if job_state and artifact_manifest:
        active_candidate = job_state.get("active_candidate")
        if isinstance(active_candidate, str) and active_candidate not in ("none", ""):
            if _artifact_by_id(artifact_manifest, active_candidate) is None:
                rows.append(
                    {
                        "contract": "JOB_STATE",
                        "status": "STALE",
                        "detail": f"active_candidate '{active_candidate}' has no matching artifact_manifest entry",
                    }
                )

    return rows


def format_status_lines(rows: list[dict[str, Any]]) -> list[str]:
    width = max((len(row["contract"]) for row in rows), default=0)
    status_width = max((len(row["status"]) for row in rows), default=0)
    return [
        f"{row['contract']:<{width}}  {row['status']:<{status_width}}  {row['detail']}" for row in rows
    ]
