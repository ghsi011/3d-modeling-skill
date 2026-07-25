"""Contract-specific validators for the five team-pipeline contracts.

Each ``validate_<contract>`` function takes the parsed JSON object (already
loaded with ``common.load_json_object``) and returns ``(issues, index)`` where
``index`` exposes the row-id maps other contracts need for cross-file
foreign-key checks (feature ids, dimension ids, edge ids, support-rule ids,
artifact ids, ...).

Field shapes follow skills/3d-modeling/references/team-contracts-v4.md --
this module defines the *structured JSON* mirror of those Markdown contracts
(added in the Sprint 1A contract-automation work; see CHANGELOG.md).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from common import Issue, error, is_hash_format, normalize_project_path
from schemas import CONFIDENCE, NUMBER, check_enum, check_fk, check_object_fields, check_rows

NULLABLE_NUMBER = (int, float, type(None))
STRLIST = list

# --- shared enumerations -----------------------------------------------------

JOB_STATE_STATES = frozenset(
    {
        "INTAKE",
        "METROLOGY",
        "REFERENCE_BUILD",
        "REFERENCE_ACCEPTANCE",
        "PRINT_PLAN",
        "CANDIDATE_BUILD",
        "INDEPENDENT_VERIFICATION",
        "PRINT_PREP",
        "FINAL_PREP_REVIEW",
        "DELIVERY",
        "BLOCKED",
    }
)
MODE = frozenset({"SOLO", "PIPELINE"})
PROFILE = frozenset({"COMPACT", "FULL"})
BACKEND = frozenset({"cadquery", "freecad"})
GATE_RESULT = frozenset({"PASS", "PENDING", "FAIL", "BLOCKED"})
DISPATCH_STATUS = frozenset({"queued", "dispatched", "complete", "blocked"})

# Consequence/escalation classification (3d-orchestrator/SKILL.md's "Consequence and
# escalation gate", P-03). Optional on job_state for backward compatibility: existing
# job_state.json files with no risk_class remain valid; when present it must be one of
# these four values.
RISK_CLASS = frozenset(
    {
        "R0_DECORATIVE",
        "R1_LOW_CONSEQUENCE",
        "R2_ENGINEERING_REVIEW",
        "R3_PROHIBITED_AUTONOMOUS_ACCEPTANCE",
    }
)

DIMENSIONS_STATUS = frozenset({"DRAFT", "REFERENCE_REVIEW", "ACCEPTED", "BLOCKED"})
REF_VERDICT = frozenset({"ACCEPTED", "REJECTED"})

PRINT_PLAN_STATUS = frozenset({"DRAFT", "ACCEPTED", "BLOCKED"})
SUPPORT_DISPOSITION = frozenset({"SELF_SUPPORT_REQUIRED", "SUPPORT_ALLOWED"})
EXPOSURE_CLASS = frozenset(
    {"EXPOSED_FUNCTIONAL", "EXPOSED_COMFORT", "HIDDEN", "BED_CONTACT", "PERMITTED_SUPPORT_CONTACT"}
)

VERIFICATION_STATUS = frozenset({"PASS", "REJECT"})
CHECK_IDS = frozenset({"1", "2", "3", "4", "5", "6", "7"})
CHECK_RESULT = frozenset({"PASS", "FAIL", "NA"})

ARTIFACT_ROLE = frozenset(
    {"reference", "candidate", "coupon", "render", "source", "mating_reference", "other"}
)
ARTIFACT_TYPE = frozenset({"stl", "step", "svg", "png", "md", "json", "py", "3mf"})
UNITS = frozenset({"mm"})

# Accepted contract_version values per contract. job_state/dimensions/print_plan/
# verification_report mirror team-contracts-v4.md's contract_version: 4.
# artifact_manifest is new (not part of v4 Markdown) and starts at 1.
ACCEPTED_CONTRACT_VERSIONS: dict[str, frozenset[int]] = {
    "job-state": frozenset({4}),
    "dimensions": frozenset({4}),
    "print-plan": frozenset({4}),
    "verification-report": frozenset({4}),
    "artifact-manifest": frozenset({1}),
}

CANONICAL_FILENAMES: dict[str, str] = {
    "job_state": "job_state.json",
    "dimensions": "dimensions.json",
    "print_plan": "print_plan.json",
    "verification_report": "verification_report.json",
    "artifact_manifest": "artifact_manifest.json",
}


def _check_contract_header(
    data: dict[str, Any], *, contract_key: str, expected_owner: str | None, where: str
) -> list[Issue]:
    issues: list[Issue] = []
    if data.get("contract") != contract_key:
        issues.append(
            error(
                "BAD_CONTRACT_KIND",
                f"{where}.contract",
                f"expected '{contract_key}', got {data.get('contract')!r}",
            )
        )
    version = data.get("contract_version")
    accepted = ACCEPTED_CONTRACT_VERSIONS[contract_key]
    if not isinstance(version, int) or isinstance(version, bool):
        issues.append(error("MISSING_FIELD", f"{where}.contract_version", "required integer field is missing"))
    elif version not in accepted:
        issues.append(
            error(
                "UNSUPPORTED_CONTRACT_VERSION",
                f"{where}.contract_version",
                f"{version} is not a supported version {sorted(accepted)}",
            )
        )
    if expected_owner is not None and "owner" in data and data.get("owner") != expected_owner:
        issues.append(
            error(
                "BAD_ENUM",
                f"{where}.owner",
                f"expected owner '{expected_owner}', got {data.get('owner')!r}",
            )
        )
    return issues


# =============================================================================
# job_state
# =============================================================================


def validate_job_state(data: dict[str, Any], *, where: str = "job_state") -> tuple[list[Issue], dict[str, Any]]:
    issues: list[Issue] = []
    issues += _check_contract_header(data, contract_key="job-state", expected_owner="orchestrator", where=where)
    issues += check_object_fields(
        data,
        required={
            "contract": str,
            "contract_version": int,
            "job_id": str,
            "revision": int,
            "owner": str,
            "mode": str,
            "profile": str,
            "state": str,
            "backend": str,
            "active_candidate": str,
            "updated_utc": str,
        },
        optional={
            "route": str,
            "risk_class": str,
            "risk_class_rationale": str,
            "bound_inputs": list,
            "gates": list,
            "dispatches": list,
            "open_questions": list,
        },
        where=where,
    )
    if isinstance(data.get("revision"), int) and not isinstance(data.get("revision"), bool):
        if data["revision"] < 1:
            issues.append(error("BAD_REVISION", f"{where}.revision", "revision must be >= 1"))
    issues += check_enum(data, "mode", MODE, where)
    issues += check_enum(data, "profile", PROFILE, where)
    issues += check_enum(data, "state", JOB_STATE_STATES, where)
    issues += check_enum(data, "backend", BACKEND, where)
    issues += check_enum(data, "risk_class", RISK_CLASS, where)

    def bound_input_row(row: dict[str, Any], row_where: str) -> list[Issue]:
        return check_object_fields(
            row,
            required={"id": str, "label": str, "reference": str, "status": str},
            optional={},
            where=row_where,
        )

    def gate_row(row: dict[str, Any], row_where: str) -> list[Issue]:
        found = check_object_fields(
            row,
            required={"id": str, "required_receipt": str, "result": str, "evidence": str},
            optional={},
            where=row_where,
        )
        found += check_enum(row, "result", GATE_RESULT, row_where)
        return found

    def dispatch_row(row: dict[str, Any], row_where: str) -> list[Issue]:
        found = check_object_fields(
            row,
            required={
                "id": str,
                "role": str,
                "authorized_inputs": str,
                "required_output": str,
                "budget_min": NUMBER,
                "status": str,
            },
            optional={},
            where=row_where,
        )
        found += check_enum(row, "status", DISPATCH_STATUS, row_where)
        return found

    def question_row(row: dict[str, Any], row_where: str) -> list[Issue]:
        return check_object_fields(
            row,
            required={"id": str, "question": str, "blocks": str},
            optional={},
            where=row_where,
        )

    gate_ids: dict[str, Any] = {}
    dispatch_ids: dict[str, Any] = {}
    if "bound_inputs" in data:
        found, _ = check_rows(data["bound_inputs"], where=f"{where}.bound_inputs", row_validator=bound_input_row)
        issues += found
    if "gates" in data:
        found, gate_ids = check_rows(data["gates"], where=f"{where}.gates", row_validator=gate_row)
        issues += found
    if "dispatches" in data:
        found, dispatch_ids = check_rows(data["dispatches"], where=f"{where}.dispatches", row_validator=dispatch_row)
        issues += found
    if "open_questions" in data:
        found, _ = check_rows(data["open_questions"], where=f"{where}.open_questions", row_validator=question_row)
        issues += found

    index = {"gate_ids": gate_ids, "dispatch_ids": dispatch_ids}
    return issues, index


# =============================================================================
# dimensions
# =============================================================================


def validate_dimensions(
    data: dict[str, Any], *, where: str = "dimensions", project_dir: Path | None = None
) -> tuple[list[Issue], dict[str, Any]]:
    issues: list[Issue] = []
    issues += _check_contract_header(data, contract_key="dimensions", expected_owner="metrologist", where=where)
    issues += check_object_fields(
        data,
        required={
            "contract": str,
            "contract_version": int,
            "job_id": str,
            "revision": int,
            "owner": str,
            "status": str,
            "updated_utc": str,
        },
        optional={
            "frame": list,
            "sources": list,
            "features": list,
            "dimensions": list,
            "open_questions": list,
            "reference_round_trip": list,
        },
        where=where,
    )
    issues += check_enum(data, "status", DIMENSIONS_STATUS, where)

    def frame_row(row: dict[str, Any], row_where: str) -> list[Issue]:
        found = check_object_fields(
            row,
            required={"id": str, "definition": str, "source": str, "confidence": str},
            optional={},
            where=row_where,
        )
        found += check_enum(row, "confidence", CONFIDENCE, row_where)
        return found

    def source_row(row: dict[str, Any], row_where: str) -> list[Issue]:
        found = check_object_fields(
            row,
            required={"id": str, "evidence_path": str, "variant": str, "authority": str},
            optional={"sha256": str, "access_date": str},
            where=row_where,
        )
        if "sha256" in row and row["sha256"] is not None and not is_hash_format(row["sha256"]):
            found.append(error("BAD_HASH", f"{row_where}.sha256", "must be 64 lowercase hex characters"))
        if "sha256" not in row and "access_date" not in row:
            found.append(
                error(
                    "MISSING_FIELD",
                    f"{row_where}.sha256",
                    "a source needs either 'sha256' or 'access_date'",
                )
            )
        if project_dir is not None and "evidence_path" in row:
            path_issues, _ = normalize_project_path(
                row.get("evidence_path"), field="evidence_path", where=row_where, project_dir=project_dir
            )
            found += path_issues
        return found

    def feature_row(row: dict[str, Any], row_where: str) -> list[Issue]:
        found = check_object_fields(
            row,
            required={
                "id": str,
                "name": str,
                "datum_value": str,
                "source": str,
                "confidence": str,
                "candidate_response": str,
                "ready": bool,
            },
            optional={},
            where=row_where,
        )
        found += check_enum(row, "confidence", CONFIDENCE, row_where)
        return found

    def dimension_row(row: dict[str, Any], row_where: str) -> list[Issue]:
        found = check_object_fields(
            row,
            required={
                "id": str,
                "feature_id": str,
                "value": str,
                "datum_method": str,
                "source": str,
                "confidence": str,
                "tolerance_response": str,
            },
            optional={},
            where=row_where,
        )
        found += check_enum(row, "confidence", CONFIDENCE, row_where)
        return found

    def question_row(row: dict[str, Any], row_where: str) -> list[Issue]:
        return check_object_fields(
            row,
            required={"id": str, "unknown": str, "risk": str, "bound": str, "blocks": str},
            optional={},
            where=row_where,
        )

    def round_trip_row(row: dict[str, Any], row_where: str) -> list[Issue]:
        found = check_object_fields(
            row,
            required={"id": str, "views_overlay": str, "verdict": str, "sheet_revision_required": bool},
            optional={},
            where=row_where,
        )
        found += check_enum(row, "verdict", REF_VERDICT, row_where)
        return found

    feature_ids: dict[str, Any] = {}
    dimension_ids: dict[str, Any] = {}
    datum_ids: dict[str, Any] = {}
    source_ids: dict[str, Any] = {}
    if "frame" in data:
        found, datum_ids = check_rows(data["frame"], where=f"{where}.frame", row_validator=frame_row)
        issues += found
    if "sources" in data:
        found, source_ids = check_rows(data["sources"], where=f"{where}.sources", row_validator=source_row)
        issues += found
    if "features" in data:
        found, feature_ids = check_rows(data["features"], where=f"{where}.features", row_validator=feature_row)
        issues += found
    if "dimensions" in data:
        found, dimension_ids = check_rows(data["dimensions"], where=f"{where}.dimensions", row_validator=dimension_row)
        issues += found
        for dimension_id, row in dimension_ids.items():
            issues += check_fk(
                [row.get("feature_id")] if isinstance(row.get("feature_id"), str) else None,
                field="feature_id",
                where=f"{where}.dimensions[{dimension_id}]",
                known=feature_ids,
                known_label="feature",
            )
    if "open_questions" in data:
        found, _ = check_rows(data["open_questions"], where=f"{where}.open_questions", row_validator=question_row)
        issues += found
    if "reference_round_trip" in data:
        found, _ = check_rows(
            data["reference_round_trip"], where=f"{where}.reference_round_trip", row_validator=round_trip_row
        )
        issues += found

    index = {
        "feature_ids": feature_ids,
        "dimension_ids": dimension_ids,
        "datum_ids": datum_ids,
        "source_ids": source_ids,
    }
    return issues, index


# =============================================================================
# print_plan
# =============================================================================


def _matrix_shape_issues(matrix: Any, *, where: str) -> list[Issue]:
    issues: list[Issue] = []
    if not isinstance(matrix, list) or len(matrix) != 4:
        issues.append(error("BAD_MATRIX", where, "model_to_printer_matrix must have 4 rows"))
        return issues
    for row_index, row in enumerate(matrix):
        if not isinstance(row, list) or len(row) != 4:
            issues.append(error("BAD_MATRIX", f"{where}[{row_index}]", "each matrix row must have 4 numbers"))
            continue
        for col_index, value in enumerate(row):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                issues.append(
                    error("BAD_MATRIX", f"{where}[{row_index}][{col_index}]", "matrix entries must be numbers")
                )
    return issues


def validate_print_plan(
    data: dict[str, Any],
    *,
    where: str = "print_plan",
    feature_ids: dict[str, Any] | None = None,
) -> tuple[list[Issue], dict[str, Any]]:
    issues: list[Issue] = []
    issues += _check_contract_header(data, contract_key="print-plan", expected_owner="print-engineer", where=where)
    issues += check_object_fields(
        data,
        required={
            "contract": str,
            "contract_version": int,
            "job_id": str,
            "revision": int,
            "owner": str,
            "status": str,
            "dimensions_revision": int,
            "reference_sha256": str,
            "updated_utc": str,
        },
        optional={
            "process": list,
            "transform": dict,
            "geometry_rules": list,
            "edges": list,
            "support_rules": list,
            "coupon": dict,
            "final_prep_notes": str,
        },
        where=where,
    )
    issues += check_enum(data, "status", PRINT_PLAN_STATUS, where)
    if "reference_sha256" in data and isinstance(data["reference_sha256"], str):
        if not is_hash_format(data["reference_sha256"]):
            issues.append(error("BAD_HASH", f"{where}.reference_sha256", "must be 64 lowercase hex characters"))

    if "process" in data and isinstance(data["process"], list):
        for position, row in enumerate(data["process"]):
            if not isinstance(row, dict):
                issues.append(error("BAD_TYPE", f"{where}.process[{position}]", "expected an object"))

    fk_known = feature_ids if feature_ids is not None else {}
    check_fks = feature_ids is not None

    def geometry_rule_row(row: dict[str, Any], row_where: str) -> list[Issue]:
        found = check_object_fields(
            row,
            required={
                "id": str,
                "rule": str,
                "verification_predicate": str,
                "required_now": str,
                "deferred_owner": str,
                "final_gate": str,
            },
            optional={"numeric_limit_mm": NULLABLE_NUMBER, "related_feature_ids": list},
            where=row_where,
        )
        if check_fks:
            found += check_fk(
                row.get("related_feature_ids"),
                field="related_feature_ids",
                where=row_where,
                known=fk_known,
                known_label="feature",
            )
        return found

    def edge_row(row: dict[str, Any], row_where: str) -> list[Issue]:
        found = check_object_fields(
            row,
            required={
                "id": str,
                "min_radius_mm": NULLABLE_NUMBER,
                "samples_required": int,
                "exposure_class": str,
            },
            optional={
                "max_radius_mm": NULLABLE_NUMBER,
                "allowed_sharp": bool,
                "allowed_sharp_reason": str,
                "related_feature_ids": list,
            },
            where=row_where,
        )
        found += check_enum(row, "exposure_class", EXPOSURE_CLASS, row_where)
        if row.get("allowed_sharp") is True and not row.get("allowed_sharp_reason"):
            found.append(
                error(
                    "ALLOWED_SHARP_NEEDS_REASON",
                    f"{row_where}.allowed_sharp_reason",
                    "allowed_sharp: true requires a non-empty allowed_sharp_reason",
                )
            )
        if check_fks:
            found += check_fk(
                row.get("related_feature_ids"),
                field="related_feature_ids",
                where=row_where,
                known=fk_known,
                known_label="feature",
            )
        return found

    def support_rule_row(row: dict[str, Any], row_where: str) -> list[Issue]:
        found = check_object_fields(
            row,
            required={
                "id": str,
                "disposition": str,
                "model_to_printer_matrix": list,
                "bed_z_mm": NUMBER,
                "bed_tolerance_mm": NUMBER,
                "downward_normal_z_max": NUMBER,
                "max_out_of_limit_area_mm2": NUMBER,
            },
            optional={
                "allowed_contact_class": str,
                "forbidden_faces": list,
                "related_feature_ids": list,
            },
            where=row_where,
        )
        found += check_enum(row, "disposition", SUPPORT_DISPOSITION, row_where)
        if "model_to_printer_matrix" in row:
            found += _matrix_shape_issues(row["model_to_printer_matrix"], where=f"{row_where}.model_to_printer_matrix")
        if isinstance(row.get("bed_tolerance_mm"), (int, float)) and not isinstance(row.get("bed_tolerance_mm"), bool):
            if row["bed_tolerance_mm"] < 0:
                found.append(error("BAD_RANGE", f"{row_where}.bed_tolerance_mm", "must be >= 0"))
        if isinstance(row.get("max_out_of_limit_area_mm2"), (int, float)) and not isinstance(
            row.get("max_out_of_limit_area_mm2"), bool
        ):
            if row["max_out_of_limit_area_mm2"] < 0:
                found.append(error("BAD_RANGE", f"{row_where}.max_out_of_limit_area_mm2", "must be >= 0"))
        if row.get("disposition") == "SUPPORT_ALLOWED" and not row.get("allowed_contact_class"):
            found.append(
                error(
                    "SUPPORT_ALLOWED_NEEDS_CONTACT_CLASS",
                    f"{row_where}.allowed_contact_class",
                    "SUPPORT_ALLOWED requires a non-empty allowed_contact_class",
                )
            )
        if check_fks:
            found += check_fk(
                row.get("related_feature_ids"),
                field="related_feature_ids",
                where=row_where,
                known=fk_known,
                known_label="feature",
            )
        return found

    geometry_rule_ids: dict[str, Any] = {}
    edge_ids: dict[str, Any] = {}
    support_rule_ids: dict[str, Any] = {}
    if "geometry_rules" in data:
        found, geometry_rule_ids = check_rows(
            data["geometry_rules"], where=f"{where}.geometry_rules", row_validator=geometry_rule_row
        )
        issues += found
    if "edges" in data:
        found, edge_ids = check_rows(data["edges"], where=f"{where}.edges", row_validator=edge_row)
        issues += found
    if "support_rules" in data:
        found, support_rule_ids = check_rows(
            data["support_rules"], where=f"{where}.support_rules", row_validator=support_rule_row
        )
        issues += found
    if "transform" in data and isinstance(data["transform"], dict):
        transform = data["transform"]
        issues += check_object_fields(
            transform,
            required={
                "coordinate_convention": str,
                "bed_contact_landmark": str,
                "bed_normal": str,
                "open_direction": str,
                "forbidden_downward_faces": list,
            },
            optional={"matrix": list},
            where=f"{where}.transform",
        )
        if "matrix" in transform:
            issues += _matrix_shape_issues(transform["matrix"], where=f"{where}.transform.matrix")

    index = {
        "geometry_rule_ids": geometry_rule_ids,
        "edge_ids": edge_ids,
        "support_rule_ids": support_rule_ids,
    }
    return issues, index


# =============================================================================
# verification_report
# =============================================================================


def validate_verification_report(
    data: dict[str, Any],
    *,
    where: str = "verification_report",
    feature_ids: dict[str, Any] | None = None,
) -> tuple[list[Issue], dict[str, Any]]:
    issues: list[Issue] = []
    issues += _check_contract_header(
        data, contract_key="verification-report", expected_owner="verifier", where=where
    )
    issues += check_object_fields(
        data,
        required={
            "contract": str,
            "contract_version": int,
            "job_id": str,
            "revision": int,
            "owner": str,
            "status": str,
            "candidate_id": str,
            "candidate_stl_sha256": str,
            "dimensions_revision": int,
            "print_plan_revision": int,
            "reference_sha256": str,
            "fresh_context": bool,
            "updated_utc": str,
        },
        optional={"checks": list, "defects": list, "verdict": str},
        where=where,
    )
    issues += check_enum(data, "status", VERIFICATION_STATUS, where)
    if data.get("fresh_context") is False:
        issues.append(
            error(
                "STALE_VERIFIER_CONTEXT",
                f"{where}.fresh_context",
                "fresh_context must be true: a verifier must not reuse a prior context",
            )
        )
    for hash_field in ("candidate_stl_sha256", "reference_sha256"):
        if isinstance(data.get(hash_field), str) and not is_hash_format(data[hash_field]):
            issues.append(error("BAD_HASH", f"{where}.{hash_field}", "must be 64 lowercase hex characters"))

    def check_row(row: dict[str, Any], row_where: str) -> list[Issue]:
        found = check_object_fields(
            row,
            required={"id": str, "method": str, "result": str},
            optional={"numeric_result": NULLABLE_NUMBER, "visual_observation": str, "evidence": str},
            where=row_where,
        )
        if row.get("id") is not None and row.get("id") not in CHECK_IDS:
            found.append(error("BAD_ENUM", f"{row_where}.id", f"must be one of {sorted(CHECK_IDS)}"))
        found += check_enum(row, "result", CHECK_RESULT, row_where)
        return found

    def defect_row(row: dict[str, Any], row_where: str) -> list[Issue]:
        found = check_object_fields(
            row,
            required={
                "id": str,
                "owning_loop": str,
                "expected_vs_observed": str,
                "evidence": str,
                "required_acceptance_condition": str,
            },
            optional={"feature_ids": list, "check_ids": list},
            where=row_where,
        )
        if feature_ids is not None:
            found += check_fk(
                row.get("feature_ids"), field="feature_ids", where=row_where, known=feature_ids, known_label="feature"
            )
        check_ids_dict = {check_id: None for check_id in CHECK_IDS}
        found += check_fk(
            row.get("check_ids"), field="check_ids", where=row_where, known=check_ids_dict, known_label="check"
        )
        return found

    checks_ids: dict[str, Any] = {}
    defect_ids: dict[str, Any] = {}
    if "checks" in data:
        found, checks_ids = check_rows(data["checks"], where=f"{where}.checks", row_validator=check_row)
        issues += found
    if "defects" in data:
        found, defect_ids = check_rows(data["defects"], where=f"{where}.defects", row_validator=defect_row)
        issues += found

    if data.get("status") == "PASS" and "checks" in data:
        present = {check.get("id") for check in data["checks"] if isinstance(check, dict)}
        missing = sorted(CHECK_IDS - present)
        if missing:
            issues.append(
                error(
                    "INCOMPLETE_SEVEN_CHECKS",
                    f"{where}.checks",
                    f"status is PASS but checks {missing} are missing",
                )
            )
        failing = sorted(
            check.get("id")
            for check in data["checks"]
            if isinstance(check, dict) and check.get("result") == "FAIL"
        )
        if failing:
            issues.append(
                error(
                    "INCOMPLETE_SEVEN_CHECKS",
                    f"{where}.checks",
                    f"status is PASS but checks {failing} recorded FAIL",
                )
            )
    if data.get("status") == "REJECT" and not data.get("defects"):
        issues.append(
            error("REJECT_NEEDS_DEFECTS", f"{where}.defects", "status is REJECT but no defects were recorded")
        )

    index = {"check_ids": checks_ids, "defect_ids": defect_ids}
    return issues, index


# =============================================================================
# artifact_manifest
# =============================================================================


def validate_artifact_manifest(
    data: dict[str, Any],
    *,
    where: str = "artifact_manifest",
    project_dir: Path | None = None,
) -> tuple[list[Issue], dict[str, Any]]:
    issues: list[Issue] = []
    issues += _check_contract_header(data, contract_key="artifact-manifest", expected_owner=None, where=where)
    issues += check_object_fields(
        data,
        required={
            "contract": str,
            "contract_version": int,
            "job_id": str,
            "candidate_id": str,
            "units": str,
            "updated_utc": str,
        },
        optional={"artifacts": list},
        where=where,
    )
    issues += check_enum(data, "units", UNITS, where)

    def bbox_issues(bbox: Any, row_where: str) -> list[Issue]:
        found: list[Issue] = []
        if not isinstance(bbox, dict):
            found.append(error("BAD_TYPE", f"{row_where}.bbox", "expected an object with 'min'/'max'"))
            return found
        found += check_object_fields(bbox, required={"min": list, "max": list}, optional={}, where=f"{row_where}.bbox")
        mn, mx = bbox.get("min"), bbox.get("max")
        if isinstance(mn, list) and isinstance(mx, list):
            if len(mn) != 3 or len(mx) != 3:
                found.append(error("BAD_BBOX", f"{row_where}.bbox", "min/max must each have 3 coordinates"))
            else:
                for axis, (lo, hi) in enumerate(zip(mn, mx)):
                    if not isinstance(lo, (int, float)) or isinstance(lo, bool) or not isinstance(hi, (int, float)) or isinstance(hi, bool):
                        found.append(error("BAD_BBOX", f"{row_where}.bbox", f"axis {axis} min/max must be numbers"))
                        continue
                    if hi <= lo:
                        found.append(
                            error(
                                "BBOX_NOT_POSITIVE",
                                f"{row_where}.bbox",
                                f"axis {axis} extent must be positive (min={lo}, max={hi})",
                            )
                        )
        return found

    def artifact_row(row: dict[str, Any], row_where: str) -> list[Issue]:
        found = check_object_fields(
            row,
            required={
                "id": str,
                "role": str,
                "path": str,
                "type": str,
                "sha256": str,
            },
            optional={
                "expected_components": int,
                "bbox": dict,
                "source_revisions": dict,
                "transform": list,
                "printable_deliverable": bool,
                "paired_artifact_id": str,
            },
            where=row_where,
        )
        found += check_enum(row, "role", ARTIFACT_ROLE, row_where)
        found += check_enum(row, "type", ARTIFACT_TYPE, row_where)
        if isinstance(row.get("sha256"), str) and not is_hash_format(row["sha256"]):
            found.append(error("BAD_HASH", f"{row_where}.sha256", "must be 64 lowercase hex characters"))
        if "expected_components" in row and isinstance(row["expected_components"], int):
            if row["expected_components"] < 1:
                found.append(error("BAD_RANGE", f"{row_where}.expected_components", "must be >= 1"))
        if "bbox" in row:
            found += bbox_issues(row["bbox"], row_where)
        if "transform" in row:
            found += _matrix_shape_issues(row["transform"], where=f"{row_where}.transform")
        if project_dir is not None and "path" in row:
            path_issues, _ = normalize_project_path(
                row.get("path"), field="path", where=row_where, project_dir=project_dir
            )
            found += path_issues
        if row.get("role") == "mating_reference" and row.get("printable_deliverable") is True:
            found.append(
                error(
                    "MATING_REFERENCE_NOT_PRINTABLE",
                    f"{row_where}.printable_deliverable",
                    "a mating reference must never be marked as a printable deliverable",
                )
            )
        return found

    artifact_ids: dict[str, Any] = {}
    if "artifacts" in data:
        found, artifact_ids = check_rows(data["artifacts"], where=f"{where}.artifacts", row_validator=artifact_row)
        issues += found
        for artifact_id, row in artifact_ids.items():
            paired = row.get("paired_artifact_id")
            if isinstance(paired, str):
                issues += check_fk(
                    [paired],
                    field="paired_artifact_id",
                    where=f"{where}.artifacts[{artifact_id}]",
                    known=artifact_ids,
                    known_label="artifact",
                )

    index = {"artifact_ids": artifact_ids}
    return issues, index
