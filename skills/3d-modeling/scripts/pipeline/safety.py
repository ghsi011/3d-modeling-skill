#!/usr/bin/env python3
"""The one bounded safety call a CONSEQUENTIAL job must make.

Mandatory, and not skippable because the route is `DIRECT`, the template is
certified, the part looks simple, deterministic checks passed, the artifact came
from cache, or somebody wants it faster.

Bounded on purpose. This is one call with a compact packet and a strict output
schema -- not an autonomous agent with a shell. A full autonomous reviewer runs
only after this one names a specific unresolved issue.

**Stage 1 only, and it says so.** The plan's second stage -- show the normal
verifier's conclusion, purely so disagreement can be reported -- is not built.
What is built is the part that matters most: this call never sees
`pipeline_verification_report.json`, so it cannot anchor on it. A second opinion
that read the first one is not a second opinion.

This module builds the packet and validates the response. It does not call a
model: the runner hands the packet to whatever the host provides, so the pipeline
stays testable without one.
"""
from __future__ import annotations

import dataclasses
from typing import Any, Callable

from . import review as R
from . import schemas as S

QUESTIONS = (
    "What are the plausible failure modes?",
    "Could the part detach, fracture, deform, slip, jam, short, overheat, or "
    "interfere with nearby equipment?",
    "Are the expected load direction and magnitude represented?",
    "Are stress concentrations visible or implied?",
    "Does the print orientation create weak inter-layer loading?",
    "Are wall thicknesses, attachment points and transitions plausible for the use?",
    "Are flexible or snap-fit assumptions supported?",
    "Could tolerance or material variation produce unsafe behaviour?",
    "Could a missing, extra or misplaced feature create a hazard?",
    "Are the important external interfaces represented accurately?",
    "Is physical testing required before use?",
    "Is the available evidence sufficient to allow this to pass at all?",
)

# Applications the reviewer must address explicitly and say what physical
# evidence would be needed. Not an automatic block: that would be a third
# consequence level wearing a different hat, and this pipeline has two.
MANDATORY_CONCERNS = (
    "life-safety", "load-bearing for a person", "braking or steering",
    "pressure vessel", "mains-electrical barrier", "fire containment",
    "regulated structural or medical use",
)


@dataclasses.dataclass(frozen=True)
class Packet:
    stage: int
    payload: dict[str, Any]

    def packet_hash(self) -> str:
        # The envelope is meta-data handed to the reviewer and echoed back.
        # Including it in the packet hash would create a circular dependency,
        # because the envelope binds the packet hash.
        payload = {k: v for k, v in self.payload.items() if k != "review_envelope"}
        return S.payload_hash(payload)

    def with_envelope(self, envelope: R.ReviewEnvelope) -> "Packet":
        return Packet(stage=self.stage,
                      payload={**self.payload, "review_envelope": envelope.as_dict()})


def build_packet(*, brief: str, intent: dict[str, Any], contract: dict[str, Any],
                 artifact: dict[str, Any], commission: dict[str, Any],
                 manufacturing: dict[str, Any] | None,
                 witness: dict[str, Any]) -> Packet:
    """Deliberately omits `pipeline_verification_report.json` -- see the module
    docstring."""
    return Packet(stage=1, payload={
        "stage": 1,
        "brief": brief,
        "consequence": intent["consequence"],
        "intent_manifest": intent,
        "model_contract": contract,
        "artifact_manifest": artifact,
        "commission_report": commission,
        "manufacturing_report": manufacturing,
        "witness": witness,
        "questions": list(QUESTIONS),
        "mandatory_concerns": list(MANDATORY_CONCERNS),
        "response_schema": {
            "decision": list(S.SAFETY_DECISION),
            "failure_modes": "list[str]", "safety_concerns": "list[str]",
            "missing_evidence": "list[str]", "required_actions": "list[str]",
            "summary": "str",
            "review_envelope": "dict -- exact envelope digest required when review is bound",
        },
    })


def validate(response: dict[str, Any], *,
             envelope: R.ReviewEnvelope | None = None) -> dict[str, Any]:
    if not isinstance(response, dict):
        raise S.SchemaError("safety response must be a dict")
    required = {"decision", "failure_modes", "safety_concerns", "missing_evidence",
                "required_actions", "summary"}
    missing = required - set(response.keys())
    if missing:
        raise S.SchemaError(f"safety response missing required fields: {sorted(missing)}")
    if envelope is not None and "review_envelope" not in response:
        raise S.SchemaError("safety response: review_envelope is required when bound")

    decision = S.require_enum(response["decision"], S.SAFETY_DECISION,
                              what="safety response decision")
    for key in ("failure_modes", "safety_concerns", "missing_evidence", "required_actions"):
        value = response[key]
        if not isinstance(value, list):
            raise S.SchemaError(f"safety response: {key} must be a list")
        if not all(isinstance(item, str) for item in value):
            raise S.SchemaError(f"safety response: {key} must be a list of strings")
    if not isinstance(response["summary"], str):
        raise S.SchemaError("safety response: summary must be a string")
    return {"decision": decision,
            "failure_modes": list(response["failure_modes"]),
            "safety_concerns": list(response["safety_concerns"]),
            "missing_evidence": list(response["missing_evidence"]),
            "required_actions": list(response["required_actions"]),
            "summary": response["summary"]}


def cache_identity(packet: Packet, *, reviewer: dict[str, Any]) -> str:
    """What makes two safety reviews the same review.

    Not "same verifier version". The same version under different reasoning
    settings is a different reviewer, and a different image preprocessing is the
    same reviewer looking at a different picture.
    """
    return S.payload_hash({
        "evidence_packet": packet.packet_hash(),
        "prompt": reviewer.get("prompt_hash"),
        "model_snapshot": reviewer.get("model_snapshot"),
        "reasoning": reviewer.get("reasoning_settings"),
        "policy_version": reviewer.get("policy_version"),
        "response_schema_version": S.SAFETY_SCHEMA,
        "inference": reviewer.get("inference_config"),
        "image_preprocessing": reviewer.get("image_preprocessing"),
    })


def run(packet: Packet, reviewer: dict[str, Any],
        call: Callable[[Packet], dict[str, Any]], *,
        envelope: R.ReviewEnvelope | None = None) -> dict[str, Any]:
    """One bounded call, validated, with its cache identity and review envelope recorded."""
    if envelope is not None:
        packet = packet.with_envelope(envelope)
    response = call(packet)
    if envelope is not None:
        R.validate_response_envelope(response, envelope)
        R.require_safety_pass_closed(response)
    response = validate(response, envelope=envelope)
    return {
        "schema_version": S.SAFETY_SCHEMA,
        "evidence_packet_sha256": packet.packet_hash(),
        "cache_identity": cache_identity(packet, reviewer=reviewer),
        "reviewer": reviewer,
        "review_envelope": envelope.as_dict() if envelope is not None else None,
        # See verification.py: answered, not asserted.
        "fresh_context": reviewer.get("fresh_context"),
        "stage": packet.stage,
        "reviewed_questions": list(QUESTIONS),
        **response,
    }
