#!/usr/bin/env python3
"""Versioned schemas for every artifact the pipeline writes.

JSON is canonical here. Markdown, where it appears at all, is a generated view
-- which inverts the direction this repo used to run, where four contracts were
Markdown-authoritative and the JSON mirrored them.

Every artifact carries `schema_version` so that a reader can refuse a version it
does not know rather than guess -- a schema change that silently reinterprets an
old field is indistinguishable, from the outside, from a correct read. Nothing
reads an artifact back yet: one run writes them and the next writes them again.
The field is the provision for when something does, not a check running today.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any

INTENT_SCHEMA = 1
CONTRACT_SCHEMA = 2
ARTIFACT_SCHEMA = 1
COMMISSION_SCHEMA = 2
SPECIFICATION_SCHEMA = 1
VERIFICATION_SCHEMA = 2
SAFETY_SCHEMA = 2
MANUFACTURING_SCHEMA = 1
# 2: the final status carries the execution plan it was produced under -- the
# plan's hash and the lane's availability -- so a receipt can be checked against
# the plan that was actually executed rather than against a route somebody
# re-derived while reading it.
STATUS_SCHEMA = 2

CONSEQUENCE = ("INCONSEQUENTIAL", "CONSEQUENTIAL")
CANDIDATE_STRATEGY = ("SINGLE", "PARALLEL")
# `authored` is the CUSTOM lane: geometry a designer wrote, built through
# whichever of the two kernels the model itself calls. It is a third *source of
# geometry*, not a third kernel -- the backend records which kernel actually ran
# and the artifact manifest carries it, because "authored" alone does not say
# whether a boolean engine was involved.
BACKEND = ("trimesh-manifold", "build123d", "authored")

# What happens when a check cannot run. `SKIP` is deliberately absent: a
# candidate once shipped 31% too thick while three checks reported SKIPPED,
# nothing counted them, and the gate exited zero. A feature that cannot say what
# its own silence means does not get built.
ON_UNRUNNABLE = ("ESCALATE", "FAIL")

# Whether a measured value was produced or the instrument could not answer.
# A measured zero is "MEASURED" with value 0.0; "UNAVAILABLE" means the check
# did not run and the value is null.
MEASUREMENT_STATUS = ("MEASURED", "UNAVAILABLE")

SAFETY_DECISION = ("PASS", "BLOCK", "NEEDS_MORE_EVIDENCE")
# `EXPERIMENTAL_UNAVAILABLE` is not a fifth verdict about the geometry. It says
# the lane that produced the receipt is not yet allowed to certify its own
# result: the build, the gates, the screen and the witnesses all ran and are on
# disk, and the one thing withheld is the claim. It is separate from
# NEEDS_MORE_EVIDENCE because no evidence an agent can supply lifts it -- see
# `execution.LANE_STATUS`.
FINAL_STATUS = ("FAILED", "NEEDS_MORE_EVIDENCE", "COMMISSIONED", "VERIFIED",
                "EXPERIMENTAL_UNAVAILABLE")


class SchemaError(ValueError):
    """An artifact does not match the schema it claims."""


class PathEscape(SchemaError):
    """A referenced path is not a safe project-relative name."""


def require_finite_number(value: Any, *, what: str) -> float:
    """A finite real number, or a SchemaError naming the field.

    Rejects `bool` (an `int` subclass that is never a magnitude), `None`,
    numeric-looking strings, and the non-standard JSON tokens `NaN`,
    `Infinity` and `-Infinity`, which Python's `json` module parses into real
    floats by default. A `float(value)` guarded only by `try/except` accepts
    every one of those -- `float(True)` is 1.0, `float("3")` is 3.0,
    `float("nan")` is a NaN -- and each then poisons every arithmetic
    consequence downstream (a NaN nominal sizes a NaN parameter and builds a
    part from nothing). This is the one place the pipeline closes that hole
    before an authoritative number is used.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchemaError(f"{what}: expected a finite number, got {value!r}")
    if not math.isfinite(value):
        raise SchemaError(f"{what}: must be finite (not NaN or Infinity), got {value!r}")
    return float(value)


def resolve_within(base_dir: Path, name: Any, *, what: str = "path") -> Path:
    """Turn a declared filename into a path proven to stay under `base_dir`.

    Every evidence or witness reference the pipeline hashes arrives as a string
    from a job file or a review response -- untrusted text. Joined naively,
    `base_dir / name` will reach an absolute path, a Windows drive (`C:...`), a
    UNC share (`\\\\host\\share`), or climb out with `..`, and `resolve()` will
    follow a symlink planted inside the directory straight out of it. Routing
    every read through this one resolver is what makes "project-relative" a
    property the code enforces rather than a convention it hopes for.
    """
    if not isinstance(name, str) or not name.strip():
        raise PathEscape(f"{what}: must be a non-empty string, got {name!r}")
    normalized = name.replace("\\", "/")
    is_windows_drive = bool(re.match(r"^[A-Za-z]:", normalized))
    is_unc = normalized.startswith("//")
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or is_windows_drive or is_unc:
        raise PathEscape(
            f"{what}: must be project-relative, got absolute path {name!r}")
    if ".." in pure.parts:
        raise PathEscape(
            f"{what}: must not contain '..' traversal segments, got {name!r}")
    if not pure.parts:
        raise PathEscape(f"{what}: must not be empty, got {name!r}")
    base_real = Path(os.path.realpath(base_dir))
    candidate = base_dir / normalized
    # resolve(strict=False) follows existing symlink components even when the
    # final segment does not exist yet -- exactly what catches a symlink planted
    # inside the directory that points outside it.
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(base_real)
    except ValueError:
        raise PathEscape(
            f"{what}: {name!r} resolves outside the project directory "
            "(possible symlink escape)") from None
    # Return the canonical target that was checked, not a second spelling that
    # could be redirected differently before the caller opens it.
    return resolved


def canonical_json(payload: Any) -> str:
    """Deterministic text: sorted keys, stable separators, trailing newline.

    Two runs of the same job must produce byte-identical artifacts, or hashing
    them proves nothing.
    """
    return json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def canonical_number(value: Any, places: int = 4) -> float:
    """A float whose serialization is a function of its value and nothing else.

    `round` on its own is not enough for an artifact whose identity is its hash.
    Any small negative magnitude rounds to `-0.0`, which is the same number as
    `0.0` and different bytes -- so two runs that agree about the geometry can
    still disagree about the receipt, and a deviation of `-1e-9` mm is exactly
    the sort of value a distance query produces. `-0.0 == 0` is true, so the
    comparison below is what collapses the two spellings into the one zero.

    Non-finite values are refused rather than serialized: `NaN` and `Infinity`
    are not JSON, and Python's encoder emits them anyway.
    """
    number = require_finite_number(value, what="canonical number")
    rounded = round(number, places)
    return 0.0 if rounded == 0 else rounded


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def payload_hash(payload: Any) -> str:
    """Hash a structure by its canonical text, so key order cannot change it."""
    return sha256_text(canonical_json(payload))



def require_enum(value: Any, allowed: tuple[str, ...], *, what: str) -> str:
    if value not in allowed:
        raise SchemaError(f"{what}: {value!r} is not one of {list(allowed)}")
    return value
