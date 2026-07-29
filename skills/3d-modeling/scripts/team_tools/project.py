"""Load a project directory's five canonical contracts and validate them.

Each contract is Markdown-first (frontmatter carries identity, revision and the
binding hashes) with a JSON mirror accepted where one exists; only a JSON
source gets a deep structural validator.

Kept separate from manifest_checks.py's filesystem/mesh checks so that cheap
callers (status, hash) are not forced to pay for mesh loads they do not need.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

try:
    from . import manifest_checks as MC
    from . import validators as V
    from .common import ContractError, Issue, check_finite, error, load_json_object, load_markdown_contract
except ImportError:  # pragma: no cover - direct script/test compatibility
    import manifest_checks as MC
    import validators as V
    from common import ContractError, Issue, check_finite, error, load_json_object, load_markdown_contract


@dataclass
class ContractFile:
    key: str
    filename: str
    path: Path
    present: bool
    data: dict[str, Any] | None
    source_format: str = "json"  # "markdown" (frontmatter) or "json"
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


def _load_one(project_dir: Path, key: str, filenames: tuple[str, ...], *, required: bool) -> ContractFile:
    """Load the first of ``filenames`` that exists.

    Markdown first, then a JSON mirror. Which one was found decides how much
    can be checked: a Markdown contract yields its frontmatter, so the header
    and every binding field are available while the prose body is left alone;
    a JSON contract additionally gets its full structural validator.
    """
    path = next((project_dir / name for name in filenames if (project_dir / name).is_file()), None)
    if path is None:
        filename = filenames[0]
        path = project_dir / filename
        # Absence is silent unless the caller declared the contract required.
        # Mid-pipeline a project legitimately holds only the contracts its phase
        # has produced, so a warning here fires on every correct run -- and the
        # same warning channel carries POSSIBLE_UNIT_SCALE_MISMATCH, which the
        # verifier must actually read. Teaching an agent to skim this channel
        # costs more than the notice is worth; `validated_paths` already records
        # exactly what was read.
        return ContractFile(
            key=key,
            filename=filename,
            path=path,
            present=False,
            data=None,
            issues=(
                [error("REQUIRED_CONTRACT_MISSING", key,
                       f"{filename} was not found in the project directory (declared required by --require)")]
                if required else []
            ),
        )
    source_format = "markdown" if path.suffix.lower() == ".md" else "json"
    loader = load_markdown_contract if source_format == "markdown" else load_json_object
    try:
        data = loader(path, where=key)
    except ContractError as exc:
        return ContractFile(
            key=key,
            filename=path.name,
            path=path,
            present=True,
            data=None,
            source_format=source_format,
            issues=[error("UNREADABLE_CONTRACT", key, str(exc))],
        )
    return ContractFile(
        key=key,
        filename=path.name,
        path=path,
        present=True,
        data=data,
        source_format=source_format,
        issues=check_finite(data, key),
    )


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
    for key, filenames in V.CANONICAL_FILENAMES.items():
        files[key] = _load_one(project_dir, key, filenames, required=key in required_keys)

    # Every contract that loaded gets its header checked -- that is where the
    # identity and the revision the binding checks compare actually live.
    for key, contract_file in files.items():
        if contract_file.data is not None:
            contract_file.issues += V.validate_contract_header(
                contract_file.data,
                key=key,
                where=key,
                source_format=contract_file.source_format,
            )

    # The deep structural validators only apply to a JSON source. A Markdown
    # contract's body is provenance and open questions written for the next
    # agent; there is no schema to hold it to.
    print_plan_file = files["print_plan"]
    if print_plan_file.data is not None and print_plan_file.source_format == "json":
        print_plan_file.issues += V.validate_print_plan(
            print_plan_file.data, where="print_plan", feature_ids=None
        )

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
