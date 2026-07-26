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
from schemas import NUMBER, check_enum, check_fk, check_object_fields, check_rows

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
MODE = frozenset({"PIPELINE"})
PROFILE = frozenset({"DIRECT", "FITTED", "FULL"})
BACKEND = frozenset({"cadquery", "build123d", "freecad"})
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

# Each contract is looked up in order: the Markdown the roles actually author
# first, then a JSON mirror if one exists. `artifact_manifest` is JSON-only --
# team-contracts-v4 calls it machine-authoritative with no Markdown mirror.
CANONICAL_FILENAMES: dict[str, tuple[str, ...]] = {
    "job_state": ("job_state.md", "job_state.json"),
    "dimensions": ("dimensions.md", "dimensions.json"),
    # `print_plan_checks.json` is the machine-readable projection of the plan and
    # is the *only* plan a DIRECT job has, so omitting it made
    # `validate --require all` unsatisfiable there -- the verifier is told to
    # require exit zero, and exit zero was unreachable.
    "print_plan": ("print_plan.md", "print_plan.json", "print_plan_checks.json"),
    "verification_report": ("verification_report.md", "verification_report.json"),
    "artifact_manifest": ("artifact_manifest.json",),
}

# Contracts with a full structural validator, which only runs on a JSON source.
# A Markdown contract is header-validated instead: its body is prose for an
# agent, and schema-checking prose reports nothing a reader could act on.
DEEP_VALIDATED: frozenset[str] = frozenset({"print_plan", "artifact_manifest"})

CONTRACT_KIND_BY_KEY: dict[str, str] = {
    "job_state": "job-state",
    "dimensions": "dimensions",
    "print_plan": "print-plan",
    "verification_report": "verification-report",
    "artifact_manifest": "artifact-manifest",
}

# Who may author each contract. Sets, not scalars, because two contracts have a
# second legitimate author under the `DIRECT` route: nothing is recovered from
# evidence there, so the orchestrator transcribes the stated dimensions and the
# shipped template supplies the plan. Neither is a metrologist or a print
# engineer, and saying otherwise in the `owner` field would be a lie about
# provenance -- which is the one thing that field exists to record.
_EXPECTED_OWNERS: dict[str, frozenset[str]] = {
    "job_state": frozenset({"orchestrator"}),
    "dimensions": frozenset({"metrologist", "orchestrator"}),
    "print_plan": frozenset({"print-engineer", "builtin-direct-template"}),
    "verification_report": frozenset({"verifier"}),
}


def validate_contract_header(data: dict[str, Any], *, key: str, where: str) -> list[Issue]:
    """Validate the fields every contract carries and the tooling binds on.

    This is the whole check for a Markdown contract. It deliberately says
    nothing about the body: `dimensions.md` states how a number was obtained,
    what it conflicts with, and how confident the metrologist is, and a
    validator that walked those rows would only ever confirm that prose is
    prose. What must hold is that the header identifies the contract and
    carries an integer revision, because that is what staleness and binding
    checks compare.
    """
    issues = _check_contract_header(
        data, contract_key=CONTRACT_KIND_BY_KEY[key], expected_owners=_EXPECTED_OWNERS.get(key), where=where
    )
    job_id = data.get("job_id")
    if not isinstance(job_id, str) or not job_id.strip():
        issues.append(error("MISSING_FIELD", f"{where}.job_id", "required non-empty string field is missing"))
    if key == "job_state" and "risk_class" in data:
        issues += check_enum(data, "risk_class", RISK_CLASS, where)
    if key != "artifact_manifest":
        revision = data.get("revision")
        if not isinstance(revision, int) or isinstance(revision, bool):
            issues.append(
                error(
                    "MISSING_FIELD",
                    f"{where}.revision",
                    "required integer field is missing -- staleness and revision binding compare it",
                )
            )
    return issues


def _check_contract_header(
    data: dict[str, Any], *, contract_key: str, expected_owners: frozenset[str] | None, where: str
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
    if expected_owners is not None and "owner" in data and data.get("owner") not in expected_owners:
        issues.append(
            error(
                "BAD_ENUM",
                f"{where}.owner",
                f"expected owner one of {sorted(expected_owners)}, got {data.get('owner')!r}",
            )
        )
    return issues




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
    issues += _check_contract_header(
        data, contract_key="print-plan", expected_owners=_EXPECTED_OWNERS["print_plan"], where=where
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
            "dimensions_revision": int,
            "updated_utc": str,
        },
        optional={
            # Optional because a job with no recreated mating object has no
            # reference to bind to, and requiring the hash of a thing that does
            # not exist made a DIRECT plan unvalidatable.
            "reference_sha256": str,
            "process": list,
            "transform": dict,
            "geometry_rules": list,
            "edges": list,
            "support_rules": list,
            "coupon": dict,
            "final_prep_notes": str,
            # The envelope the candidate is gated against. `commission` fails
            # rather than skips without it, so the contract has to name it.
            "expected_bbox_mm": dict,
            "bbox_tolerance_mm": (int, float),
            "interfaces": list,
            "threshold_source": str,
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
# artifact_manifest
# =============================================================================


def validate_artifact_manifest(
    data: dict[str, Any],
    *,
    where: str = "artifact_manifest",
    project_dir: Path | None = None,
) -> tuple[list[Issue], dict[str, Any]]:
    issues: list[Issue] = []
    issues += _check_contract_header(data, contract_key="artifact-manifest", expected_owners=None, where=where)
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
