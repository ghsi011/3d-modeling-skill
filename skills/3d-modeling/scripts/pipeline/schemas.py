#!/usr/bin/env python3
"""Versioned schemas for every artifact the pipeline writes.

JSON is canonical here. Markdown, where it appears at all, is a generated view
-- which inverts the direction this repo used to run, where four contracts were
Markdown-authoritative and the JSON mirrored them.

Every artifact carries `schema_version`. A reader that finds a version it does
not know refuses rather than guessing: a schema change that silently reinterprets
an old field is indistinguishable, from the outside, from a correct read.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

INTENT_SCHEMA = 1
CONTRACT_SCHEMA = 1
ARTIFACT_SCHEMA = 1
COMMISSION_SCHEMA = 1
VERIFICATION_SCHEMA = 1
SAFETY_SCHEMA = 1
MANUFACTURING_SCHEMA = 1
STATUS_SCHEMA = 1

CONSEQUENCE = ("INCONSEQUENTIAL", "CONSEQUENTIAL")
ROUTE = ("DIRECT", "FITTED", "FULL")
CANDIDATE_STRATEGY = ("SINGLE", "PARALLEL")
BACKEND = ("trimesh-manifold", "build123d")

# What happens when a check cannot run. `SKIP` is deliberately absent: a
# candidate once shipped 31% too thick while three checks reported SKIPPED,
# nothing counted them, and the gate exited zero. A feature that cannot say what
# its own silence means does not get built.
ON_UNRUNNABLE = ("ESCALATE", "FAIL")

CHECK_RESULT = ("PASS", "FAIL", "ESCALATE")
SCREEN_RESULT = ("CLEAR", "ANOMALY", "INDETERMINATE")
MANUFACTURING_RESULT = ("SATISFIED", "DEFERRED", "BLOCKED")
SAFETY_DECISION = ("PASS", "BLOCK", "NEEDS_MORE_EVIDENCE")
FINAL_STATUS = ("FAILED", "NEEDS_MORE_EVIDENCE", "COMMISSIONED", "VERIFIED")


class SchemaError(ValueError):
    """An artifact does not match the schema it claims."""


def canonical_json(payload: Any) -> str:
    """Deterministic text: sorted keys, stable separators, trailing newline.

    Two runs of the same job must produce byte-identical artifacts, or hashing
    them proves nothing.
    """
    return json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


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


def require_version(payload: dict[str, Any], expected: int, *, what: str) -> None:
    found = payload.get("schema_version")
    if found != expected:
        raise SchemaError(
            f"{what}: schema_version {found!r}, this build reads {expected}. "
            "Migrate the artifact or use the build that wrote it -- reading it "
            "anyway would be a guess about what its fields meant.")


def require_enum(value: Any, allowed: tuple[str, ...], *, what: str) -> str:
    if value not in allowed:
        raise SchemaError(f"{what}: {value!r} is not one of {list(allowed)}")
    return value
