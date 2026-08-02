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

# 2: the envelope binds `evidence_digests` -- the digests of the deterministic
# measurement plans that produced the evidence in the packet, and of the evidence
# itself. A reviewer's answer to a preservation audit could previously only be
# checked against the packet as a whole, so a reader of a response could see
# *that* it no longer matched and never *what* it had been written against.
# Bumping rather than adding silently: every stored response's digest moves, and
# a build that refuses one by name is telling the truth more usefully than one
# that reports an unexplained mismatch.
#
# 3: the envelope binds `execution_plan_sha256` -- the identity of the plan the
# run was executed under. The plan decides the builder, the source mode, the lane
# status and its note, and which artifacts owe a preservation row; none of that
# reached anything a reviewer answered, because `plan_hash()` was written only
# into `final_status.json`, which is produced *after* the review. A job whose
# lane cap or builder changed underneath a stored answer therefore kept the
# answer. Same reasoning as 2: bumped rather than added silently, so a stored
# protocol-2 response is refused by name rather than by an unexplained digest
# mismatch.
#
# 4: the envelope binds `alternative_id` -- which formulation of the job the
# review was taken on. At the instant a branch is created its sibling is a copy,
# so `contract_sha256`, `artifact_hashes` and `witness_hashes` are all equal and
# `revision` is `request.updated_utc`, a timestamp rather than a graph node. A
# safety PASS written for one sibling was therefore `is_bound` for the other: a
# false pass of exactly the class the authority gate forbids, reachable without
# anybody doing anything wrong. Path isolation does not close it either, because
# `ExecutionPlan.as_payload` carries no parameters, so two alternatives of one
# template with different numbers share an `execution_plan_sha256`. Bumped rather
# than added silently, as 2 and 3 were: a stored protocol-3 response is refused
# by name instead of by an unexplained digest mismatch.
REVIEW_PROTOCOL_VERSION = 4
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
        # Every evidence/witness reference is untrusted text from a job file or a
        # review response. The canonical resolver is the one gate for it: it
        # refuses absolute paths, Windows drives, UNC shares, `..` traversal and
        # symlink escapes, so an envelope cannot bind a hash of a file outside
        # the project directory.
        try:
            path = S.resolve_within(base_dir, name, what="evidence file")
        except S.PathEscape as exc:
            raise ReviewError(str(exc)) from None
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
    # Digests of the deterministic measurement plans behind the evidence, and of
    # the evidence those plans produced. `evidence_hashes` above covers *files*
    # handed to the reviewer; this covers measurements computed during the run,
    # which have no file of their own and used not to be nameable at all.
    evidence_digests: dict[str, str] | None = None
    # The execution plan this run was carried out under. `builder`, `source_mode`,
    # `lane_status`, `lane_note` and `preserved_artifact_ids` all live in the plan
    # and in nothing else the reviewer sees, and the plan's own digest reached
    # only `final_status.json` -- written after the review that it should have
    # bound. All three review boundaries supply it. It stays optional because an
    # envelope is a general structure and a caller with no plan in hand must be
    # able to say so rather than invent one; the runner is not such a caller.
    execution_plan_sha256: str | None = None
    # Which alternative this review was taken on, absent at the shared root.
    #
    # The second and last payload the id joins. Two siblings at the instant of
    # branching agree about every other field here, and `revision` is a
    # timestamp, so without this an answer written for one is bound to the other
    # by construction.
    alternative_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """The envelope as it is handed over, echoed back and hashed.

        `alternative_id` is *omitted* when there is none. That is deliberately
        not what the line below it does: `execution_plan_sha256` is emitted
        unconditionally, including as `null`, and following that precedent would
        move every envelope digest on every unbranched job -- which is the cost
        this slice is required not to impose. The reader accepts absent and null
        as the same answer (`_optional_str_field`), so nothing has to be migrated
        to read it either way.
        """
        payload = {
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
            "evidence_digests": (None if self.evidence_digests is None
                                 else {k: v for k, v in sorted(self.evidence_digests.items())}),
            "execution_plan_sha256": self.execution_plan_sha256,
        }
        if self.alternative_id is not None:
            payload["alternative_id"] = self.alternative_id
        return payload

    def digest(self) -> str:
        return S.payload_hash(self.as_dict())


def build_envelope(*, kind: str, job_id: str, revision: str, packet_hash: str,
                   reviewer: dict[str, Any], contract_hash: str,
                   artifact_hashes: dict[str, str | None] | None = None,
                   witness: dict[str, Any] | None = None,
                   witness_dir: Path | None = None,
                   evidence: tuple[str, ...] | list[str] = (),
                   evidence_dir: Path | None = None,
                   evidence_digests: dict[str, Any] | None = None,
                   execution_plan_sha256: str | None = None,
                   alternative_id: str | None = None) -> ReviewEnvelope:
    S.require_enum(kind, REVIEW_KIND, what="review kind")
    if evidence_digests is not None:
        for name, digest in sorted(evidence_digests.items()):
            if not isinstance(name, str) or not isinstance(digest, str):
                raise ReviewError(
                    "evidence_digests must map strings to strings, got "
                    f"{name!r}: {digest!r}")
    if execution_plan_sha256 is not None and not isinstance(execution_plan_sha256, str):
        raise ReviewError(
            "execution_plan_sha256 must be a string or absent, got "
            f"{execution_plan_sha256!r}")
    if alternative_id is not None and not isinstance(alternative_id, str):
        raise ReviewError(
            f"alternative_id must be a string or absent, got {alternative_id!r}")
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
        evidence_digests=(None if evidence_digests is None
                          else dict(evidence_digests)),
        execution_plan_sha256=execution_plan_sha256,
        alternative_id=alternative_id,
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


def _optional_str_field(env: dict[str, Any], key: str) -> str | None:
    """A string the envelope may legitimately not carry.

    Absent and null are one answer here: a review taken with no execution plan in
    hand binds no plan, and an envelope that omits the key means the same thing as
    one that spells it `null`. Anything else that is not a string is malformed.
    """
    value = env.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ReviewError(f"review_envelope: {key} must be a string or null")
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
        protocol_version = _int_field(env, "protocol_version")
        answer_schema_version = _int_field(env, "answer_schema_version")
        kind = _str_field(env, "kind")
        # Version and kind are validated before anything trusts the rest. An
        # envelope from a protocol or answer schema this build does not know is
        # not a stale answer to compare digests against -- it is one whose
        # meaning this reader cannot vouch for, and guessing is exactly the
        # silent reinterpretation `schema_version` exists to forbid. The refusal
        # is explicit here rather than an opaque digest mismatch two calls later.
        if protocol_version != REVIEW_PROTOCOL_VERSION:
            raise ReviewError(
                f"review_envelope: unknown protocol_version {protocol_version} "
                f"(this build speaks {REVIEW_PROTOCOL_VERSION})")
        if kind not in REVIEW_KIND:
            raise ReviewError(
                f"review_envelope: kind {kind!r} is not one of {list(REVIEW_KIND)}")
        expected_schema = SCHEMA_VERSION_BY_KIND[kind]
        if answer_schema_version != expected_schema:
            raise ReviewError(
                f"review_envelope: answer_schema_version {answer_schema_version} does "
                f"not match schema {expected_schema} for a {kind} review")
        return ReviewEnvelope(
            protocol_version=protocol_version,
            answer_schema_version=answer_schema_version,
            kind=kind,
            job_id=_str_field(env, "job_id"),
            revision=_str_field(env, "revision"),
            packet_sha256=_str_field(env, "packet_sha256"),
            reviewer=_dict_field(env, "reviewer"),
            contract_sha256=_str_field(env, "contract_sha256"),
            artifact_hashes=_hash_map_field(env, "artifact_hashes", nullable_values=True),
            witness_hashes=_hash_map_field(env, "witness_hashes", nullable_values=False),
            evidence_hashes=_hash_map_field(env, "evidence_hashes", nullable_values=False),
            evidence_digests=_hash_map_field(env, "evidence_digests",
                                             nullable_values=False),
            execution_plan_sha256=_optional_str_field(env, "execution_plan_sha256"),
            alternative_id=_optional_str_field(env, "alternative_id"),
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
