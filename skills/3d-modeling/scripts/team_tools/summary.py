"""Agent-facing summary: a compact, informational-only status block that points
back to the authoritative structured contracts + receipts. It never becomes an
authority layer of its own -- it repeats only what validate/status already
computed, to cut re-reading/token use, not to add a new source of truth.
"""

from __future__ import annotations

from pathlib import Path

from project import load_project
from status import compute_status

CONTRACT_ORDER = ("job_state", "dimensions", "print_plan", "verification_report", "artifact_manifest")


def build_agent_summary(project_dir: Path) -> str:
    project = load_project(project_dir)
    status_rows = compute_status(project_dir)

    job_state = project.files["job_state"].data
    mode = job_state.get("mode") if job_state else None
    state = job_state.get("state") if job_state else None

    revisions = []
    for key in CONTRACT_ORDER:
        contract_file = project.files[key]
        if contract_file.data is not None and "revision" in contract_file.data:
            revisions.append(f"{key}=r{contract_file.data['revision']}")
    artifact_manifest = project.files["artifact_manifest"].data
    artifact_count = len(artifact_manifest.get("artifacts") or []) if artifact_manifest else 0
    printable_count = 0
    if artifact_manifest:
        for artifact in artifact_manifest.get("artifacts") or []:
            if (
                isinstance(artifact, dict)
                and artifact.get("role") != "mating_reference"
                and artifact.get("printable_deliverable") is True
            ):
                printable_count += 1

    stale_rows = [row for row in status_rows if row["status"] in ("STALE", "INVALIDATED")]
    blocking_errors = []
    warnings = []
    for key in CONTRACT_ORDER:
        contract_file = project.files[key]
        for issue in contract_file.issues:
            if issue.severity == "error":
                blocking_errors.append(issue.id)
            else:
                warnings.append(issue.id)

    lines = [
        f"mode={mode or '<unset>'} state={state or '<unset>'}",
        f"contract revisions: {', '.join(revisions) if revisions else '<none present>'}",
        f"artifacts: {artifact_count} declared, {printable_count} printable-deliverable",
        f"stale/invalidated bindings: {len(stale_rows)}"
        + ("" if not stale_rows else " (" + "; ".join(f"{row['contract']} {row['detail']}" for row in stale_rows) + ")"),
        f"blocking errors: {len(blocking_errors)}"
        + ("" if not blocking_errors else " (" + ", ".join(sorted(blocking_errors)) + ")"),
        f"warnings: {len(warnings)}",
        "authoritative source: the structured JSON contracts in this project directory "
        "and the receipt from `python -m team_tools.contracts validate <project>`. "
        "This summary is informational only and proves nothing about geometric or "
        "manufacturing correctness.",
    ]
    return "\n".join(lines)
