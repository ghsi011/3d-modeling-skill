"""`render` command: stable, git-diff-friendly Markdown generated from a
structured JSON contract. Field order is fixed by contract type (not by JSON
key-insertion order), so re-rendering the same content always produces the
same bytes and unrelated field reordering upstream cannot cause diff noise.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from common import ContractError, load_json_object

BANNER = "<!-- GENERATED -- do not edit; regenerate: python -m team_tools.contracts render <file> -->"


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ", ".join(_cell(item) for item in value)
    if isinstance(value, dict):
        return "; ".join(f"{key}={_cell(value[key])}" for key in sorted(value))
    return str(value)


def _table(headers: list[str], fields: list[str], rows: Any) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            lines.append("| " + " | ".join(_cell(row.get(field)) for field in fields) + " |")
    return "\n".join(lines)


def _frontmatter(pairs: list[tuple[str, Any]]) -> str:
    lines = ["---"]
    for key, value in pairs:
        lines.append(f"{key}: {_cell(value)}")
    lines.append("---")
    return "\n".join(lines)


def _finish(parts: list[str]) -> str:
    return "\n".join(parts).rstrip() + "\n"


def render_job_state(data: dict[str, Any]) -> str:
    fm = _frontmatter(
        [
            ("contract", data.get("contract")),
            ("contract_version", data.get("contract_version")),
            ("job_id", data.get("job_id")),
            ("revision", data.get("revision")),
            ("owner", data.get("owner")),
            ("mode", data.get("mode")),
            ("profile", data.get("profile")),
            ("state", data.get("state")),
            ("backend", data.get("backend")),
            ("active_candidate", data.get("active_candidate")),
            ("updated_utc", data.get("updated_utc")),
        ]
    )
    parts = [BANNER, "", fm, "", "# Job state", ""]
    if data.get("route"):
        parts += ["## Route", "", str(data["route"]), ""]
    parts += [
        "## Bound inputs",
        "",
        _table(["ID", "Label", "Reference", "Status"], ["id", "label", "reference", "status"], data.get("bound_inputs")),
        "",
        "## Gates",
        "",
        _table(
            ["ID", "Required receipt", "Result", "Evidence"],
            ["id", "required_receipt", "result", "evidence"],
            data.get("gates"),
        ),
        "",
        "## Dispatches",
        "",
        _table(
            ["ID", "Role", "Authorized inputs", "Required output", "Budget min", "Status"],
            ["id", "role", "authorized_inputs", "required_output", "budget_min", "status"],
            data.get("dispatches"),
        ),
        "",
        "## Open user questions",
        "",
        _table(["ID", "Question", "Blocks"], ["id", "question", "blocks"], data.get("open_questions")),
        "",
    ]
    return _finish(parts)


def render_dimensions(data: dict[str, Any]) -> str:
    fm = _frontmatter(
        [
            ("contract", data.get("contract")),
            ("contract_version", data.get("contract_version")),
            ("job_id", data.get("job_id")),
            ("revision", data.get("revision")),
            ("owner", data.get("owner")),
            ("status", data.get("status")),
            ("updated_utc", data.get("updated_utc")),
        ]
    )
    parts = [
        BANNER,
        "",
        fm,
        "",
        "# Dimensions",
        "",
        "## Frame",
        "",
        _table(
            ["Axis/datum", "Definition", "Source", "Confidence"],
            ["id", "definition", "source", "confidence"],
            data.get("frame"),
        ),
        "",
        "## Sources",
        "",
        _table(
            ["ID", "Evidence path", "Variant", "SHA-256", "Access date", "Authority/limits"],
            ["id", "evidence_path", "variant", "sha256", "access_date", "authority"],
            data.get("sources"),
        ),
        "",
        "## Blind-build completeness",
        "",
        _table(
            ["Feature ID", "Name", "Datum value/envelope", "Source", "Confidence", "Candidate response", "Ready"],
            ["id", "name", "datum_value", "source", "confidence", "candidate_response", "ready"],
            data.get("features"),
        ),
        "",
        "## Dimensions",
        "",
        _table(
            ["ID", "Feature", "Value/range", "Datum/method", "Source", "Confidence", "Tolerance/design response"],
            ["id", "feature_id", "value", "datum_method", "source", "confidence", "tolerance_response"],
            data.get("dimensions"),
        ),
        "",
        "## Open questions",
        "",
        _table(
            ["ID", "Unknown", "Risk", "Approved bound/question", "Blocks"],
            ["id", "unknown", "risk", "bound", "blocks"],
            data.get("open_questions"),
        ),
        "",
        "## Reference round trip",
        "",
        _table(
            ["Build ID", "Views/overlay", "Verdict", "Sheet revision required"],
            ["id", "views_overlay", "verdict", "sheet_revision_required"],
            data.get("reference_round_trip"),
        ),
        "",
    ]
    return _finish(parts)


def render_print_plan(data: dict[str, Any]) -> str:
    fm = _frontmatter(
        [
            ("contract", data.get("contract")),
            ("contract_version", data.get("contract_version")),
            ("job_id", data.get("job_id")),
            ("revision", data.get("revision")),
            ("owner", data.get("owner")),
            ("status", data.get("status")),
            ("dimensions_revision", data.get("dimensions_revision")),
            ("reference_sha256", data.get("reference_sha256")),
            ("updated_utc", data.get("updated_utc")),
        ]
    )
    parts = [
        BANNER,
        "",
        fm,
        "",
        "# Print plan",
        "",
        "## Process",
        "",
        _table(
            ["Printer/material/nozzle", "Layer", "Environment/load", "Rationale"],
            ["printer_material_nozzle", "layer_mm", "environment_load", "rationale"],
            data.get("process"),
        ),
        "",
        "## Model-to-printer transform",
        "",
    ]
    transform = data.get("transform")
    if isinstance(transform, dict):
        parts.append("| Item | Exact value |")
        parts.append("|---|---|")
        for label, key in (
            ("Coordinate convention", "coordinate_convention"),
            ("Bed-contact landmark", "bed_contact_landmark"),
            ("Bed normal", "bed_normal"),
            ("Open/insertion direction", "open_direction"),
            ("Forbidden downward faces", "forbidden_downward_faces"),
            ("Matrix", "matrix"),
        ):
            if key in transform:
                parts.append(f"| {label} | {_cell(transform[key])} |")
    parts += [
        "",
        "## Geometry rules and phase scope",
        "",
        _table(
            ["ID", "Rule", "Numeric limit", "Verification predicate", "required_now", "deferred_owner", "final_gate"],
            [
                "id",
                "rule",
                "numeric_limit_mm",
                "verification_predicate",
                "required_now",
                "deferred_owner",
                "final_gate",
            ],
            data.get("geometry_rules"),
        ),
        "",
        "## Edge ID set",
        "",
        _table(
            ["ID", "Min radius mm", "Max radius mm", "Samples required", "Exposure class", "Allowed sharp", "Allowed sharp reason"],
            [
                "id",
                "min_radius_mm",
                "max_radius_mm",
                "samples_required",
                "exposure_class",
                "allowed_sharp",
                "allowed_sharp_reason",
            ],
            data.get("edges"),
        ),
        "",
        "## Support rules",
        "",
        _table(
            [
                "ID",
                "Disposition",
                "Bed Z mm",
                "Bed tolerance mm",
                "Downward normal z max",
                "Max out-of-limit area mm2",
                "Allowed contact class",
            ],
            [
                "id",
                "disposition",
                "bed_z_mm",
                "bed_tolerance_mm",
                "downward_normal_z_max",
                "max_out_of_limit_area_mm2",
                "allowed_contact_class",
            ],
            data.get("support_rules"),
        ),
        "",
    ]
    coupon = data.get("coupon")
    if isinstance(coupon, dict):
        parts += ["## Coupon", ""]
        for key in sorted(coupon):
            parts.append(f"- **{key}**: {_cell(coupon[key])}")
        parts.append("")
    if data.get("final_prep_notes"):
        parts += ["## Final-prep placeholders", "", str(data["final_prep_notes"]), ""]
    return _finish(parts)


def render_verification_report(data: dict[str, Any]) -> str:
    fm = _frontmatter(
        [
            ("contract", data.get("contract")),
            ("contract_version", data.get("contract_version")),
            ("job_id", data.get("job_id")),
            ("revision", data.get("revision")),
            ("owner", data.get("owner")),
            ("status", data.get("status")),
            ("candidate_id", data.get("candidate_id")),
            ("candidate_stl_sha256", data.get("candidate_stl_sha256")),
            ("dimensions_revision", data.get("dimensions_revision")),
            ("print_plan_revision", data.get("print_plan_revision")),
            ("reference_sha256", data.get("reference_sha256")),
            ("fresh_context", data.get("fresh_context")),
            ("updated_utc", data.get("updated_utc")),
        ]
    )
    parts = [
        BANNER,
        "",
        fm,
        "",
        "# Independent verification",
        "",
        "## Seven checks on re-imported exported STL",
        "",
        _table(
            ["Check", "Method", "Numeric result", "Visual observation", "Result", "Evidence"],
            ["id", "method", "numeric_result", "visual_observation", "result", "evidence"],
            data.get("checks"),
        ),
        "",
        "## Defects",
        "",
        _table(
            ["ID", "Owning loop", "Feature IDs", "Check IDs", "Expected vs observed", "Evidence", "Required acceptance condition"],
            [
                "id",
                "owning_loop",
                "feature_ids",
                "check_ids",
                "expected_vs_observed",
                "evidence",
                "required_acceptance_condition",
            ],
            data.get("defects"),
        ),
        "",
        "## Verdict",
        "",
        str(data.get("verdict", "")),
        "",
    ]
    return _finish(parts)


def render_artifact_manifest(data: dict[str, Any]) -> str:
    fm = _frontmatter(
        [
            ("contract", data.get("contract")),
            ("contract_version", data.get("contract_version")),
            ("job_id", data.get("job_id")),
            ("candidate_id", data.get("candidate_id")),
            ("units", data.get("units")),
            ("updated_utc", data.get("updated_utc")),
        ]
    )
    parts = [BANNER, "", fm, "", "# Artifact manifest", "", "## Artifacts", ""]
    headers = ["ID", "Role", "Path", "Type", "SHA-256", "Expected components", "BBox min", "BBox max", "Printable deliverable"]
    parts.append("| " + " | ".join(headers) + " |")
    parts.append("|" + "|".join("---" for _ in headers) + "|")
    for row in data.get("artifacts") or []:
        if not isinstance(row, dict):
            continue
        bbox = row.get("bbox") if isinstance(row.get("bbox"), dict) else {}
        cells = [
            _cell(row.get("id")),
            _cell(row.get("role")),
            _cell(row.get("path")),
            _cell(row.get("type")),
            _cell(row.get("sha256")),
            _cell(row.get("expected_components")),
            _cell(bbox.get("min")),
            _cell(bbox.get("max")),
            _cell(row.get("printable_deliverable")),
        ]
        parts.append("| " + " | ".join(cells) + " |")
    parts.append("")
    return _finish(parts)


_RENDERERS = {
    "job-state": render_job_state,
    "dimensions": render_dimensions,
    "print-plan": render_print_plan,
    "verification-report": render_verification_report,
    "artifact-manifest": render_artifact_manifest,
}


def render_contract_file(path: Path) -> str:
    data = load_json_object(path, where=str(path))
    contract_key = data.get("contract")
    renderer = _RENDERERS.get(contract_key)
    if renderer is None:
        raise ContractError(
            f"{path}: unknown or missing 'contract' field {contract_key!r}; "
            f"expected one of {sorted(_RENDERERS)}"
        )
    return renderer(data)
