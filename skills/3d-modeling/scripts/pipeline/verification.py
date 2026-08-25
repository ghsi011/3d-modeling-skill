#!/usr/bin/env python3
"""Independent verification: the only route to `VERIFIED`.

Every rejection a fresh verifier ever issued on the old pipeline was a
deterministic predicate the designer's own receipt already claimed to have
checked. The gate absorbed those, which is why `COMMISSIONED` is now a real
claim. What a gate still cannot do is ask whether the part is the one the brief
asked for -- every check it runs is conditioned on a contract somebody wrote, and
a contract that misread the brief is satisfied exactly as well by the wrong part.

So this is a second reading of the *requirement*, not of the mesh. It receives
the brief and the artifacts and never the designer's reasoning: a verifier told
what to conclude has stopped being one.

**It cannot re-measure and it is not asked to.** The deterministic numbers are
handed over as measured; disputing them would be a second implementation of
arithmetic that already has one. Its questions are the ones no number answers --
does this match what was asked for, is anything visible that nobody declared, is
a stated requirement missing from the contract entirely.
"""
from __future__ import annotations

import dataclasses
from typing import Any, Callable

from . import review as R
from . import schemas as S

DECISION = ("PASS", "REJECT", "NEEDS_MORE_EVIDENCE")

# Which loop owns a defect. A verifier that cannot say where a fix belongs has
# described a symptom, and the next context has to rediscover the cause.
OWNING_LOOP = ("SPECIFICATION", "CONTRACT", "BUILD")

QUESTIONS = (
    "Does the delivered part do what the brief asked for?",
    "Is any requirement in the brief absent from the contract entirely?",
    "Is anything visible in the witnesses that no contract row declares?",
    "Do the declared features match the brief's intent, not just its wording?",
    "Is the print orientation plausible for how the part is used?",
    "Would this part be usable by the person who asked for it?",
)


@dataclasses.dataclass(frozen=True)
class Packet:
    payload: dict[str, Any]

    def packet_hash(self) -> str:
        # The envelope is meta-data handed to the reviewer and echoed back.
        payload = {k: v for k, v in self.payload.items() if k != "review_envelope"}
        return S.payload_hash(payload)

    def with_envelope(self, envelope: R.ReviewEnvelope) -> "Packet":
        return Packet(payload={**self.payload, "review_envelope": envelope.as_dict()})


def build_packet(*, brief: str, intent: dict[str, Any], contract: dict[str, Any],
                 artifact: dict[str, Any], commission: dict[str, Any],
                 witness: dict[str, Any],
                 specification: dict[str, Any] | None = None) -> Packet:
    """Everything except the designer's reasoning.

    `model.py` is deliberately absent. The source is how the part was made, and a
    verifier reading it starts checking whether the code does what the code says
    -- which is the designer's own question, asked again by someone with less
    context.

    **The numbers here are the claim under audit, not settled fact.** This packet
    used to say "do not recompute them", which is the opposite of what
    `roles/verifier.md` requires of the reader it is handed to: *audit upstream
    measurements*, *independently compare*, *an independent recomputation
    compared check-by-check*, and -- the reason -- *independently of the
    toolkit's, so a silent disagreement between them is the cheapest bug*.

    Two authorities reaching one role with opposite instructions about the single
    thing that role exists to do. The charter is the one that is right: a verdict
    that trusts the numbers it is auditing is not a second opinion, and a
    verifier that had obeyed this packet would have returned a decision fast and
    hollow, having checked nothing the pipeline had not already checked. Nothing
    downstream would have noticed -- the report parses, carries a decision, and
    binds.

    They are still *given*, because a re-derivation nobody can compare against is
    not an audit either. The instruction is to check them, not to work blind.
    """
    return Packet({
        "task": ("Decide whether the delivered part is the one the brief asked "
                 "for. The numbers below are what the pipeline measured and are "
                 "the claim under audit: re-derive them independently and report "
                 "any disagreement, which is a finding in itself."),
        "brief": brief,
        "intent_manifest": intent,
        "model_contract": contract,
        "artifact_manifest": artifact,
        "commission_report": commission,
        "specification": specification,
        "witness": witness,
        "questions": list(QUESTIONS),
        "response_schema": {
            "decision": list(DECISION),
            "defects": [{"summary": "str", "owning_loop": list(OWNING_LOOP),
                         "expected_vs_observed": "str", "evidence": "str",
                         "severity": "str"}],
            "unmet_requirements": ["str -- in the brief, absent from the contract"],
            "missing_evidence": ["str"],
            "summary": "str",
            "review_envelope": "dict -- exact envelope digest required when review is bound",
        },
    })


def validate(response: dict[str, Any], *,
             envelope: R.ReviewEnvelope | None = None) -> dict[str, Any]:
    if not isinstance(response, dict):
        raise S.SchemaError("verification response must be a dict")
    required = {"decision", "defects", "unmet_requirements", "missing_evidence", "summary"}
    missing = required - set(response.keys())
    if missing:
        raise S.SchemaError(f"verification response missing required fields: {sorted(missing)}")
    if envelope is not None and "review_envelope" not in response:
        raise S.SchemaError("verification response: review_envelope is required when bound")

    decision = S.require_enum(response["decision"], DECISION,
                              what="verification decision")
    if not isinstance(response["defects"], list):
        raise S.SchemaError("verification response: defects must be a list")
    if not isinstance(response["unmet_requirements"], list):
        raise S.SchemaError("verification response: unmet_requirements must be a list")
    if not isinstance(response["missing_evidence"], list):
        raise S.SchemaError("verification response: missing_evidence must be a list")
    if not isinstance(response["summary"], str):
        raise S.SchemaError("verification response: summary must be a string")

    defects = []
    for row in response["defects"]:
        if not isinstance(row, dict):
            raise S.SchemaError("verification response: each defect must be a dict")
        for field in ("summary", "owning_loop", "expected_vs_observed", "evidence", "severity"):
            if field not in row or not str(row[field]).strip():
                raise S.SchemaError(
                    f"defect {row.get('summary')!r}: {field} is empty or missing. A rejection "
                    "that does not say what was expected, what was observed, and "
                    "where to look sends the next context back to rediscover it.")
        for field in ("summary", "expected_vs_observed", "evidence", "severity"):
            if not isinstance(row[field], str):
                raise S.SchemaError(f"defect {row['summary']!r}: {field} must be a string")
        loop = S.require_enum(row["owning_loop"], OWNING_LOOP,
                              what=f"defect {row['summary']!r} owning_loop")
        defects.append({**row, "owning_loop": loop})

    if decision == "REJECT" and not defects:
        raise S.SchemaError(
            "REJECT with no defects: a rejection has to name what is wrong, or "
            "nobody can act on it and the next build is a guess.")
    if decision == "PASS" and defects:
        raise S.SchemaError(
            "PASS with defects listed: decide. A pass carrying known defects is "
            "how a defect ships with a paper trail saying somebody saw it.")

    if not all(isinstance(r, str) for r in response["unmet_requirements"]):
        raise S.SchemaError("verification response: unmet_requirements must be a list of strings")
    if not all(isinstance(e, str) for e in response["missing_evidence"]):
        raise S.SchemaError("verification response: missing_evidence must be a list of strings")

    return {"decision": decision, "defects": defects,
            "unmet_requirements": list(response["unmet_requirements"]),
            "missing_evidence": list(response["missing_evidence"]),
            "summary": response["summary"]}


def run(packet: Packet, reviewer: dict[str, Any],
        call: Callable[[Packet], dict[str, Any]], *,
        envelope: R.ReviewEnvelope | None = None) -> dict[str, Any]:
    if envelope is not None:
        packet = packet.with_envelope(envelope)
    response = call(packet)
    if envelope is not None:
        R.validate_response_envelope(response, envelope)
        R.require_verification_pass_closed(response)
    result = validate(response, envelope=envelope)
    if result["decision"] == "PASS" and result["unmet_requirements"]:
        # Not a schema error -- a coherent answer to a question nobody asked
        # clearly enough. Downgraded rather than rejected, because "the brief
        # wants something the contract never mentioned" is exactly the finding
        # this pass exists for.
        result["decision"] = "NEEDS_MORE_EVIDENCE"
        result["summary"] = (result["summary"] + " [downgraded: passed while listing "
                             "requirements the contract does not cover]").strip()
    return {
        "schema_version": S.VERIFICATION_SCHEMA,
        "evidence_packet_sha256": packet.packet_hash(),
        "reviewer": reviewer,
        "review_envelope": envelope.as_dict() if envelope is not None else None,
        # Answered by whoever knows, never asserted here. These were the literals
        # `True` and `False`, written by this function on every report and
        # established by nothing -- on a single-context run that is a plain
        # falsehood in a contract, produced by the pipeline itself. No code can
        # know whether the context that invoked it has read the designer's
        # reasoning, and the whole charter rests on a fresh context being able to
        # disagree with the designer.
        "fresh_context": reviewer.get("fresh_context"),
        "saw_designer_reasoning": reviewer.get("saw_designer_reasoning"),
        "reviewed_questions": list(QUESTIONS),
        **result,
    }
