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
        return S.payload_hash(self.payload)


def build_packet(*, brief: str, intent: dict[str, Any], contract: dict[str, Any],
                 artifact: dict[str, Any], commission: dict[str, Any],
                 witness: dict[str, Any],
                 specification: dict[str, Any] | None = None) -> Packet:
    """Everything except the designer's reasoning.

    `model.py` is deliberately absent. The source is how the part was made, and a
    verifier reading it starts checking whether the code does what the code says
    -- which is the designer's own question, asked again by someone with less
    context.
    """
    return Packet({
        "task": ("Decide whether the delivered part is the one the brief asked for. "
                 "The numbers below were measured deterministically and are not in "
                 "dispute -- do not recompute them."),
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
        },
    })


def validate(response: dict[str, Any]) -> dict[str, Any]:
    decision = S.require_enum(response.get("decision"), DECISION,
                              what="verification decision")
    defects = []
    for row in response.get("defects", []):
        loop = S.require_enum(row.get("owning_loop"), OWNING_LOOP,
                              what=f"defect {row.get('summary')!r} owning_loop")
        for field in ("summary", "expected_vs_observed", "evidence", "severity"):
            if not str(row.get(field, "")).strip():
                raise S.SchemaError(
                    f"defect {row.get('summary')!r}: {field} is empty. A rejection "
                    "that does not say what was expected, what was observed, and "
                    "where to look sends the next context back to rediscover it.")
        defects.append({**row, "owning_loop": loop})

    if decision == "REJECT" and not defects:
        raise S.SchemaError(
            "REJECT with no defects: a rejection has to name what is wrong, or "
            "nobody can act on it and the next build is a guess.")
    if decision == "PASS" and defects:
        raise S.SchemaError(
            "PASS with defects listed: decide. A pass carrying known defects is "
            "how a defect ships with a paper trail saying somebody saw it.")

    return {"decision": decision, "defects": defects,
            "unmet_requirements": [str(r) for r in response.get("unmet_requirements", [])],
            "missing_evidence": [str(e) for e in response.get("missing_evidence", [])],
            "summary": str(response.get("summary", ""))}


def run(packet: Packet, reviewer: dict[str, Any],
        call: Callable[[Packet], dict[str, Any]]) -> dict[str, Any]:
    result = validate(call(packet))
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
        "fresh_context": True,
        "saw_designer_reasoning": False,
        "reviewed_questions": list(QUESTIONS),
        **result,
    }
