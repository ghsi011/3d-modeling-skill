#!/usr/bin/env python3
"""Shared deterministic review envelope for all bounded review calls.

Every review that crosses the human/model boundary is a claim about a specific
request at a specific moment. The envelope binds the response to that request so
that a stale answer, an answer for a different kind of review, or an answer for
different evidence cannot be promoted to a passing status.

The envelope is meta-data: it is handed to the reviewer in the request and must
be echoed back unchanged. It is not part of the packet hash, because the packet
hash is one of the things the envelope binds.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from . import schemas as S

REVIEW_PROTOCOL_VERSION = 1
REVIEW_KIND = ("specification", "safety", "verification")

SCHEMA_VERSION_BY_KIND = {
    "specification": S.SPECIFICATION_SCHEMA,
    "safety": S.SAFETY_SCHEMA,
    "verification": S.VERIFICATION_SCHEMA,
}


class ReviewError(ValueError):
    """A review response is not bound to the current request or is contradictory."""


class MissingEvidenceError(ReviewError):
    """Evidence referenced by the envelope cannot be found on disk."""


def _file_hashes(filenames, base_dir: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in filenames:
        if not isinstance(name, str):
            # Refused before the join: `base_dir / 42` is a TypeError, and this
            # boundary only ever raises ReviewError.
            raise ReviewError(
                f"evidence entries must be strings, got {type(name).__name__}: {name!r}")
        path = base_dir / name
        if not path.is_file():
            raise MissingEvidenceError(
                f"evidence file not found: {name} (looked in {base_dir})")
        result[name] = S.sha256_file(path)
    return result


def _hash_witness(witness: dict[str, Any] | None, witness_dir: Path | None) -> dict[str, str] | None:
    if witness is None:
        return None
    images = witness.get("images") or []
    if not images:
        return {}
    if witness_dir is None:
        raise ReviewError("witness images present but no witness directory provided")
    return _file_hashes(images, witness_dir)


def _hash_evidence(evidence: tuple[str, ...] | list[str],
                   evidence_dir: Path | None) -> dict[str, str] | None:
    if evidence is None or not evidence:
        return None
    if evidence_dir is None:
        raise ReviewError("evidence files listed but no evidence directory provided")
    return _file_hashes(evidence, evidence_dir)


@dataclasses.dataclass(frozen=True)
class ReviewEnvelope:
    protocol_version: int
    answer_schema_version: int
    kind: str
    job_id: str
    revision: str
    packet_sha256: str
    reviewer: dict[str, Any]
    contract_sha256: str
    artifact_hashes: dict[str, str | None] | None
    witness_hashes: dict[str, str] | None
    evidence_hashes: dict[str, str] | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "answer_schema_version": self.answer_schema_version,
            "kind": self.kind,
            "job_id": self.job_id,
            "revision": self.revision,
            "packet_sha256": self.packet_sha256,
            "reviewer": dict(self.reviewer),
            "contract_sha256": self.contract_sha256,
            "artifact_hashes": (None if self.artifact_hashes is None
                                else {k: v for k, v in sorted(self.artifact_hashes.items())}),
            "witness_hashes": (None if self.witness_hashes is None
                               else {k: v for k, v in sorted(self.witness_hashes.items())}),
            "evidence_hashes": (None if self.evidence_hashes is None
                                else {k: v for k, v in sorted(self.evidence_hashes.items())}),
        }

    def digest(self) -> str:
        return S.payload_hash(self.as_dict())


def build_envelope(*, kind: str, job_id: str, revision: str, packet_hash: str,
                   reviewer: dict[str, Any], contract_hash: str,
                   artifact_hashes: dict[str, str | None] | None = None,
                   witness: dict[str, Any] | None = None,
                   witness_dir: Path | None = None,
                   evidence: tuple[str, ...] | list[str] = (),
                   evidence_dir: Path | None = None) -> ReviewEnvelope:
    S.require_enum(kind, REVIEW_KIND, what="review kind")
    return ReviewEnvelope(
        protocol_version=REVIEW_PROTOCOL_VERSION,
        answer_schema_version=SCHEMA_VERSION_BY_KIND[kind],
        kind=kind,
        job_id=job_id,
        revision=revision,
        packet_sha256=packet_hash,
        reviewer=dict(reviewer),
        contract_sha256=contract_hash,
        artifact_hashes=artifact_hashes,
        witness_hashes=_hash_witness(witness, witness_dir),
        evidence_hashes=_hash_evidence(evidence, evidence_dir),
    )


def _int_field(env: dict[str, Any], key: str) -> int:
    value = env[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise ReviewError(f"review_envelope: {key} must be an integer")
    return value


def _str_field(env: dict[str, Any], key: str) -> str:
    value = env[key]
    if not isinstance(value, str):
        raise ReviewError(f"review_envelope: {key} must be a string")
    return value


def _dict_field(env: dict[str, Any], key: str) -> dict[str, Any]:
    value = env[key]
    if not isinstance(value, dict):
        raise ReviewError(f"review_envelope: {key} must be a dict")
    return dict(value)


def _hash_map_field(env: dict[str, Any], key: str, *,
                    nullable_values: bool) -> dict[str, Any] | None:
    value = env.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ReviewError(f"review_envelope: {key} must be a dict")
    for name, digest in value.items():
        if not isinstance(name, str):
            raise ReviewError(f"review_envelope: {key} keys must be strings")
        if digest is None and nullable_values:
            continue
        if not isinstance(digest, str):
            raise ReviewError(f"review_envelope: {key}[{name!r}] must be a string")
    return dict(value)


def _envelope_from_dict(env: dict[str, Any]) -> ReviewEnvelope:
    """Parse a mapping into an envelope, refusing wrong-typed fields.

    The dataclass constructor accepts anything, so a malformed nested value
    used to survive parsing and detonate later -- `dict()` on a list raising
    ValueError, `sorted(...items())` on a list raising AttributeError -- at a
    call site that only guards against ReviewError. Every field the digest
    will serialize is checked here, where the controlled error lives.
    """
    try:
        return ReviewEnvelope(
            protocol_version=_int_field(env, "protocol_version"),
            answer_schema_version=_int_field(env, "answer_schema_version"),
            kind=_str_field(env, "kind"),
            job_id=_str_field(env, "job_id"),
            revision=_str_field(env, "revision"),
            packet_sha256=_str_field(env, "packet_sha256"),
            reviewer=_dict_field(env, "reviewer"),
            contract_sha256=_str_field(env, "contract_sha256"),
            artifact_hashes=_hash_map_field(env, "artifact_hashes", nullable_values=True),
            witness_hashes=_hash_map_field(env, "witness_hashes", nullable_values=False),
            evidence_hashes=_hash_map_field(env, "evidence_hashes", nullable_values=False),
        )
    except KeyError as exc:
        raise ReviewError(f"review_envelope is malformed: missing {exc}") from None


def envelope_from_response(response: dict[str, Any]) -> ReviewEnvelope:
    if not isinstance(response, dict):
        raise ReviewError("response must be a dict")
    env = response.get("review_envelope")
    if env is None:
        raise ReviewError("response has no review_envelope")
    if not isinstance(env, dict):
        raise ReviewError("review_envelope must be a dict")
    try:
        return _envelope_from_dict(env)
    except (KeyError, TypeError) as exc:
        raise ReviewError(f"review_envelope is malformed: {exc}") from None


def validate_response_envelope(response: dict[str, Any], current: ReviewEnvelope) -> None:
    bound = envelope_from_response(response)
    try:
        bound_digest = bound.digest()
    except TypeError as exc:
        # The digest hashes the echoed envelope as JSON. A hand-assembled
        # envelope can carry a value no JSON document can hold, and that is a
        # malformed answer -- a ReviewError here, not a TypeError out of the
        # runner with no receipt.
        raise ReviewError(f"review_envelope cannot be hashed: {exc}") from None
    if bound_digest != current.digest():
        raise ReviewError(
            f"review envelope mismatch: response bound to {bound_digest[:16]}... "
            f"but current request is {current.digest()[:16]}...")


def require_safety_pass_closed(response: dict[str, Any]) -> None:
    if response.get("decision") != "PASS":
        return
    if not str(response.get("summary", "")).strip():
        raise ReviewError("safety PASS has no summary")
    for key in ("failure_modes", "safety_concerns", "missing_evidence", "required_actions"):
        if response.get(key):
            raise ReviewError(f"safety PASS has nonempty {key}: {response[key]}")


def require_verification_pass_closed(response: dict[str, Any]) -> None:
    if response.get("decision") != "PASS":
        return
    if not str(response.get("summary", "")).strip():
        raise ReviewError("verification PASS has no summary")
    for key in ("defects", "missing_evidence", "unmet_requirements"):
        if response.get(key):
            raise ReviewError(f"verification PASS has nonempty {key}: {response[key]}")


def require_specification_pass_closed(response: dict[str, Any]) -> None:
    unresolved = response.get("unresolved") or []
    if unresolved:
        raise ReviewError(f"specification has unresolved items: {unresolved}")


def is_bound(report: dict[str, Any] | None, kind: str,
             expected_digest: str) -> bool:
    """Surface check for status.py: a report that exists and carries the right envelope.

    The bound envelope must match the complete current request -- packet,
    contract, artifacts, witnesses, reviewer configuration and revision. A
    partial or stale report, or a call that omits the expected envelope, is not
    promoted.
    """
    if not isinstance(report, dict):
        return False
    envelope = report.get("review_envelope")
    if not isinstance(envelope, dict):
        return False
    if envelope.get("kind") != kind:
        return False
    if envelope.get("protocol_version") != REVIEW_PROTOCOL_VERSION:
        return False
    try:
        bound = envelope_from_response({"review_envelope": envelope})
        bound_digest = bound.digest()
    except (ReviewError, TypeError):
        # A surface check cannot raise: status.py has no try/except around it,
        # and a report that cannot be hashed is simply not bound.
        return False
    if bound_digest != expected_digest:
        return False
    return True
