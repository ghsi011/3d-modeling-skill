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
`verification_report.json`, so it cannot anchor on it. A second opinion that read
the first one is not a second opinion.

This module builds the packet and validates the response. It does not call a
model: the runner hands the packet to whatever the host provides, so the pipeline
stays testable without one.
"""
from __future__ import annotations

import dataclasses
from typing import Any, Callable

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
        return S.payload_hash(self.payload)


def build_packet(*, brief: str, intent: dict[str, Any], contract: dict[str, Any],
                 artifact: dict[str, Any], commission: dict[str, Any],
                 manufacturing: dict[str, Any] | None,
                 witness: dict[str, Any]) -> Packet:
    """Deliberately omits `verification_report.json` -- see the module docstring."""
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
        },
    })


def validate(response: dict[str, Any]) -> dict[str, Any]:
    decision = S.require_enum(response.get("decision"), S.SAFETY_DECISION,
                              what="safety response decision")
    for key in ("failure_modes", "safety_concerns", "missing_evidence", "required_actions"):
        if not isinstance(response.get(key, []), list):
            raise S.SchemaError(f"safety response: {key} must be a list")
    if not isinstance(response.get("summary", ""), str):
        raise S.SchemaError("safety response: summary must be a string")
    return {"decision": decision,
            "failure_modes": list(response.get("failure_modes", [])),
            "safety_concerns": list(response.get("safety_concerns", [])),
            "missing_evidence": list(response.get("missing_evidence", [])),
            "required_actions": list(response.get("required_actions", [])),
            "summary": str(response.get("summary", ""))}


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
        call: Callable[[Packet], dict[str, Any]]) -> dict[str, Any]:
    """One bounded call, validated, with its cache identity recorded."""
    response = validate(call(packet))
    return {
        "schema_version": S.SAFETY_SCHEMA,
        "evidence_packet_sha256": packet.packet_hash(),
        "cache_identity": cache_identity(packet, reviewer=reviewer),
        "reviewer": reviewer,
        # See verification.py: answered, not asserted.
        "fresh_context": reviewer.get("fresh_context"),
        "stage": packet.stage,
        "reviewed_questions": list(QUESTIONS),
        **response,
    }
