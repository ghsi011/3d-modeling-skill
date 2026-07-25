"""Load a project directory's five canonical contract JSON files and run the
structural + cross-file foreign-key validators from validators.py.

Kept separate from manifest_checks.py's filesystem/mesh checks so that cheap
callers (status, hash) are not forced to pay for mesh loads they do not need.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import manifest_checks as MC
import validators as V
from common import ContractError, Issue, check_finite, error, load_json_object, warning


@dataclass
class ContractFile:
    key: str
    filename: str
    path: Path
    present: bool
    data: dict[str, Any] | None
    issues: list[Issue] = field(default_factory=list)
    index: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProjectValidation:
    project_dir: Path
    files: dict[str, ContractFile]

    def all_issues(self) -> list[Issue]:
        out: list[Issue] = []
        for contract_file in self.files.values():
            out.extend(contract_file.issues)
        return out


def _load_one(project_dir: Path, key: str, filename: str, *, required: bool) -> ContractFile:
    path = project_dir / filename
    if not path.is_file():
        # Absence is a warning by default and an error only when the caller
        # declared the contract required: mid-pipeline a project legitimately
        # holds only the contracts its phase has produced so far, so a blanket
        # error would make `validate` unusable before Phase 4.
        detail = f"{filename} was not found in the project directory"
        issue = (
            error("REQUIRED_CONTRACT_MISSING", key, f"{detail} (declared required by --require)")
            if required
            else warning("MISSING_CONTRACT_FILE", key, detail)
        )
        return ContractFile(
            key=key,
            filename=filename,
            path=path,
            present=False,
            data=None,
            issues=[issue],
        )
    try:
        data = load_json_object(path, where=key)
    except ContractError as exc:
        return ContractFile(
            key=key,
            filename=filename,
            path=path,
            present=True,
            data=None,
            issues=[error("UNREADABLE_CONTRACT", key, str(exc))],
        )
    finite_issues = check_finite(data, key)
    return ContractFile(key=key, filename=filename, path=path, present=True, data=data, issues=finite_issues)


def load_project(project_dir: Path, *, required: Iterable[str] = ()) -> ProjectValidation:
    """Structural + FK validation only. No filesystem/mesh checks on artifact
    bodies -- see manifest_checks.py / run_manifest_checks() for that.

    ``required`` names contract keys whose absence is an error rather than a
    warning (see ``_load_one``).

    A project directory that does not exist is a ContractError, not a project
    with five missing contracts: every canonical file is "absent" either way,
    so a typo'd path would otherwise be indistinguishable from a clean early-
    phase project and would validate green.
    """
    if not project_dir.is_dir():
        raise ContractError(f"project directory not found: {project_dir}")
    required_keys = set(required)
    files: dict[str, ContractFile] = {}
    for key, filename in V.CANONICAL_FILENAMES.items():
        files[key] = _load_one(project_dir, key, filename, required=key in required_keys)

    feature_ids: dict[str, Any] | None = None
    dimensions_file = files["dimensions"]
    if dimensions_file.data is not None:
        issues, index = V.validate_dimensions(dimensions_file.data, where="dimensions", project_dir=project_dir)
        dimensions_file.issues += issues
        dimensions_file.index = index
        feature_ids = index.get("feature_ids", {})

    job_state_file = files["job_state"]
    if job_state_file.data is not None:
        issues, index = V.validate_job_state(job_state_file.data, where="job_state")
        job_state_file.issues += issues
        job_state_file.index = index

    print_plan_file = files["print_plan"]
    if print_plan_file.data is not None:
        issues, index = V.validate_print_plan(
            print_plan_file.data, where="print_plan", feature_ids=feature_ids
        )
        print_plan_file.issues += issues
        print_plan_file.index = index

    verification_file = files["verification_report"]
    if verification_file.data is not None:
        issues, index = V.validate_verification_report(
            verification_file.data, where="verification_report", feature_ids=feature_ids
        )
        verification_file.issues += issues
        verification_file.index = index

    manifest_file = files["artifact_manifest"]
    if manifest_file.data is not None:
        issues, index = V.validate_artifact_manifest(
            manifest_file.data, where="artifact_manifest", project_dir=project_dir
        )
        manifest_file.issues += issues
        manifest_file.index = index

    return ProjectValidation(project_dir=project_dir, files=files)


def run_manifest_checks(project: ProjectValidation) -> None:
    """Mutates project.files['artifact_manifest'].issues in place with the
    filesystem/mesh-backed checks (exists, hash match, bbox, unit-scale,
    component count, paired STL/STEP compare). Call only when those checks are
    actually wanted (validate command) -- status/hash callers that only need
    revisions or raw hashes should not pay for mesh loads.
    """
    manifest_file = project.files["artifact_manifest"]
    if manifest_file.data is None:
        return
    artifact_ids: dict[str, Any] = manifest_file.index.get("artifact_ids", {})
    for artifact_id, row in artifact_ids.items():
        manifest_file.issues += MC.check_artifact_files(
            artifact=row,
            artifact_id=artifact_id,
            project_dir=project.project_dir,
            where=f"artifact_manifest.artifacts[{artifact_id}]",
        )
    manifest_file.issues += MC.compare_paired_stl_step(
        artifacts=artifact_ids, project_dir=project.project_dir, where="artifact_manifest"
    )
