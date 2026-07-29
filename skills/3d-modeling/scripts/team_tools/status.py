"""`status` command: report each contract's revision plus stale/invalidated
downstream bindings (bound revision/hash vs. current revision/hash).

Read-only: a stale or invalidated binding is reported, never rewritten. Agents
own the decision to re-bind after reviewing what changed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from .common import normalize_project_path, sha256_file
    from .project import load_project
except ImportError:  # pragma: no cover - direct script/test compatibility
    from common import normalize_project_path, sha256_file
    from project import load_project

CONTRACT_ORDER = ("job_state", "dimensions", "print_plan", "verification_report", "artifact_manifest")

# A row with one of these statuses means the project may not advance. `MISSING`
# is deliberately absent: an early-phase project is legitimately missing the
# contracts later phases write, and `validate --require` is what names the ones
# a given phase must have.
BLOCKING_STATUSES = frozenset({"STALE", "INVALIDATED", "UNREADABLE", "AMBIGUOUS", "MISMATCH"})


def exit_code(rows: list[dict[str, Any]]) -> int:
    return 1 if any(row["status"] in BLOCKING_STATUSES for row in rows) else 0


def _hash_prefix(value: Any) -> str:
    return value[:12] if isinstance(value, str) and value else "<missing>"


def _artifacts_by_role(manifest: dict[str, Any] | None, role: str) -> list[dict[str, Any]]:
    if not manifest:
        return []
    return [
        artifact
        for artifact in manifest.get("artifacts") or []
        if isinstance(artifact, dict) and artifact.get("role") == role
    ]


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
    _, full_path = normalize_project_path(
        raw_path, field="path", where="artifact_manifest.artifacts", project_dir=project_dir
    )
    if full_path is None or not full_path.is_file():
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

    # Every contract in a project must name the same job. `validate` checks each
    # file alone, so a project assembled from two jobs' contracts passed it
    # cleanly -- four files bound to `final4` under a `job_state` saying
    # `express1`, with every hash and revision internally consistent. Only
    # reading them side by side caught it, which is what this command is for.
    named: dict[str, str] = {}
    for key in CONTRACT_ORDER:
        data = files[key].data
        if data and isinstance(data.get("job_id"), str):
            named[key] = data["job_id"]
    if len(set(named.values())) > 1:
        governing = named.get("job_state")
        odd = sorted(k for k, v in named.items() if v != governing) if governing else []
        rows.append({
            "contract": "JOB_STATE" if governing else "PROJECT",
            "status": "MISMATCH",
            "detail": ("contracts name different jobs: "
                       + ", ".join(f"{k}={v}" for k, v in sorted(named.items()))
                       + (f"; {', '.join(odd)} disagree with job_state" if odd else "")),
        })

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

    # `reference_sha256` is one scalar on the plan and on the report, so it can
    # bind exactly one reference. A multi-part job has several, and picking the
    # first would answer "is the reference current?" from an arbitrary member of
    # the set -- a change to any other reference would read as OK. Report the
    # ambiguity instead of guessing which one the binding meant.
    reference_artifacts = _artifacts_by_role(artifact_manifest, "reference")
    if len(reference_artifacts) > 1:
        rows.append(
            {
                "contract": "ARTIFACT_MANIFEST",
                "status": "AMBIGUOUS",
                "detail": (
                    f"{len(reference_artifacts)} artifacts have role 'reference' "
                    f"({', '.join(str(a.get('id')) for a in reference_artifacts)}); "
                    "reference_sha256 is a single hash and cannot bind them all"
                ),
            }
        )
    current_reference_hash = (
        _current_hash_of(reference_artifacts[0], project_dir) if len(reference_artifacts) == 1 else None
    )
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
