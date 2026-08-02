"""Shared primitives: issues, hashing, finite-number checks, path safety.

Deterministic by construction: no wall-clock reads, stable ordering (callers sort
before emitting), sha256 for all hashing (matches team_preflight.py conventions).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any

# `Issue` moved to `pipeline.findings` so that `Project.validate()` could answer
# in findings instead of English. One type, not two: the second copy is the one
# whose `id` stops matching the first. The dependency points from this package to
# `pipeline` and never back -- `team_tools` is the older layer and `pipeline` is
# the one being built, so a shared module owned here would make everything built
# next depend on what it replaces.
#
# The path insert is the compatibility bootstrap `contracts.py` already carries,
# one level up: the direct-script invocation this package supports puts
# `team_tools/` on `sys.path` and not the `scripts/` directory that holds
# `pipeline/`. Under pytest, `python -m team_tools.contracts`, and the installed
# wheel the entry is already present and the insert is skipped.
_SCRIPTS_DIR = str(Path(__file__).resolve().parent.parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from pipeline.findings import (  # noqa: E402 - import follows the bootstrap above
    Issue, error, has_errors, sort_issues, warning)

__all__ = ["Issue", "error", "warning", "has_errors", "sort_issues"]

TOOL_NAME = "team_tools.contracts"
TOOL_VERSION = "1.0"
# Schema version of receipts/records *emitted by this tool* (independent from the
# per-contract ``contract_version`` field defined by team-contracts-v4.md).
TOOL_SCHEMA_VERSION = 1

DEFAULT_TIMESTAMP = "1970-01-01T00:00:00Z"
TIMESTAMP_ENV_VAR = "TEAM_TOOLS_TIMESTAMP"
INCH_TO_MM = 25.4
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class ContractError(ValueError):
    """Raised for conditions that make a file impossible to process at all
    (unreadable, not JSON, not an object). Field/rule-level problems are collected
    as Issue objects instead of raising, so a single validate call can report every
    problem in a file, not just the first.
    """


# `Issue`, `error`, `warning`, `has_errors` and `sort_issues` are re-exported
# from `pipeline.findings` at the top of this file. They were defined here; every
# call site in this package still imports them from `common`, which is why the
# move is a move and not a rewrite.


# ---------------------------------------------------------------------------
# Hashing (never trust an entered hash -- always recompute from bytes on disk)
# ---------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json(value: Any) -> str:
    """Deterministic JSON text: sorted keys, stable separators, trailing newline."""
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(payload)


def is_hash_format(value: Any) -> bool:
    return isinstance(value, str) and bool(_HASH_RE.match(value))


# ---------------------------------------------------------------------------
# Finite-number validation (reject NaN / +Inf / -Inf, recursively, anywhere)
# ---------------------------------------------------------------------------


def check_finite(value: Any, where: str) -> list[Issue]:
    """Recursively walk a JSON-decoded structure and flag every non-finite number.

    Python's ``json`` module accepts the non-standard ``NaN``/``Infinity``/
    ``-Infinity`` literals by default and turns them into real ``float('nan')`` /
    ``float('inf')`` objects, so a plain recursive walk after ``json.loads`` catches
    every case (literal tokens and any float that is inf/nan for other reasons)
    with an exact field path attached.
    """
    issues: list[Issue] = []
    _check_finite_inner(value, where, issues)
    return issues


def _check_finite_inner(value: Any, where: str, issues: list[Issue]) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            issues.append(error("NON_FINITE", where, f"non-finite number {value!r}"))
        return
    if isinstance(value, dict):
        for key in value:
            _check_finite_inner(value[key], f"{where}.{key}", issues)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _check_finite_inner(item, f"{where}[{index}]", issues)
        return


_FRONTMATTER_TRUE = {"true", "yes"}
_FRONTMATTER_FALSE = {"false", "no"}


def _coerce_scalar(raw: str) -> Any:
    lowered = raw.lower()
    if lowered in _FRONTMATTER_TRUE:
        return True
    if lowered in _FRONTMATTER_FALSE:
        return False
    for cast in (int, float):
        try:
            return cast(raw)
        except ValueError:
            continue
    return raw


def load_markdown_contract(path: Path, *, where: str) -> dict[str, Any]:
    """Load the YAML frontmatter of a Markdown contract as a flat mapping.

    Four of the five v4 contracts are authored as Markdown -- the body is
    provenance, uncertainty and open questions written for the next agent to
    read, which no schema can usefully check. But every field the tooling
    *binds* on already sits in the frontmatter: ``revision``,
    ``dimensions_revision``, ``print_plan_revision``, ``reference_sha256``,
    ``candidate_stl_sha256``. Reading it here is what lets the revision- and
    hash-binding checks run against the files the pipeline actually writes,
    instead of a JSON mirror no role is told to author.

    Flat scalars only, deliberately: no lists, no nesting, no YAML dependency
    (this package stays on stdlib + trimesh + numpy). Anything structured
    belongs either in the body as prose or in one of the JSON contracts.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractError(f"{where}: cannot read {path}: {exc}") from exc
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ContractError(f"{where}: {path} has no frontmatter block (expected '---' on line 1)")
    data: dict[str, Any] = {}
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            return data
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, raw = stripped.partition(":")
        if separator:
            data[key.strip()] = _coerce_scalar(raw.strip())
    raise ContractError(f"{where}: {path} frontmatter block is not terminated by '---'")


def load_json_object(path: Path, *, where: str) -> Any:
    """Load a JSON file. Raises ContractError for anything that is not readable,
    parseable JSON, or is not a JSON object at the top level. Individual field
    problems (including non-finite numbers) are reported later as Issues by the
    contract-specific validators, not raised here.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractError(f"{where}: cannot read {path}: {exc}") from exc
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ContractError(f"{where}: invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{where}: {path} must contain a JSON object at the top level")
    return value


# ---------------------------------------------------------------------------
# Project-relative path safety: no absolute paths, no ``..``, no symlink escape.
# ---------------------------------------------------------------------------


def normalize_project_path(
    raw: Any, *, field: str, where: str, project_dir: Path
) -> tuple[list[Issue], Path | None]:
    issues: list[Issue] = []
    if not isinstance(raw, str) or not raw.strip():
        issues.append(error("BAD_PATH", f"{where}.{field}", "path must be a non-empty string"))
        return issues, None

    normalized = raw.replace("\\", "/")
    is_windows_drive = bool(re.match(r"^[A-Za-z]:", normalized))
    is_unc = normalized.startswith("//")
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or is_windows_drive or is_unc:
        issues.append(
            error(
                "BAD_PATH",
                f"{where}.{field}",
                f"path must be project-relative, got absolute-looking path '{raw}'",
            )
        )
        return issues, None
    if ".." in pure.parts:
        issues.append(
            error(
                "BAD_PATH",
                f"{where}.{field}",
                f"path must not contain '..' traversal segments: '{raw}'",
            )
        )
        return issues, None
    if not pure.parts:
        issues.append(error("BAD_PATH", f"{where}.{field}", "path must not be empty"))
        return issues, None

    candidate = project_dir / normalized
    try:
        base_real = Path(os.path.realpath(project_dir))
        # resolve(strict=False) follows any existing symlink components even when
        # the final path segment does not exist yet; that is exactly what is
        # needed to catch a symlink planted inside the project that escapes it.
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(base_real)
    except ValueError:
        issues.append(
            error(
                "BAD_PATH",
                f"{where}.{field}",
                f"path resolves outside the project directory (possible symlink escape): '{raw}'",
            )
        )
        return issues, None
    # Return the canonical target that was checked. Callers must not re-join
    # the untrusted spelling after this point.
    return issues, resolved


def resolve_timestamp(explicit: str | None) -> str:
    """Never call datetime.now() in logic that must be reproducible: accept an
    explicit timestamp, fall back to an env var, else a fixed placeholder.
    """
    if explicit:
        return explicit
    from_env = os.environ.get(TIMESTAMP_ENV_VAR)
    if from_env:
        return from_env
    return DEFAULT_TIMESTAMP
