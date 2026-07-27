#!/usr/bin/env python3
"""Final status, and the claim it permits.

Four statuses, and the rules that separate them are the point of the artifact.
`VERIFIED` is the only one that means somebody independent agreed, so everything
that could have gone unexamined has to block it: a required manufacturing
predicate nobody proved, a screening detector that could not run, a
`CONSEQUENTIAL` job with no safety pass.

`COMMISSIONED` is not a lesser `VERIFIED`. It is a precise claim -- the geometry
was measured against its contract and matched -- and the allowed-claim string
says in words what was *not* established, so a reader who skips the JSON still
cannot mistake one for the other.
"""
from __future__ import annotations

from typing import Any

from . import schemas as S
from .contract import Contract

# Predicates no mesh can answer. Without a named, versioned slicer adapter these
# are always DEFERRED -- and this toolchain has no slicer, by design. Promising
# otherwise would be promising verification the stack cannot produce.
SLICER_DEPENDENT = {
    "supports": "actual support-contact faces and their toolpaths",
    "multi-material": "the material boundary as the slicer resolves it",
    "multi-colour": "the colour boundary as the slicer resolves it",
    "flexible-filament": "extrusion behaviour of a flexible under this geometry",
}

# Named in the plan, and not yet measured by anything here. They are DEFERRED
# rather than SATISFIED: the earlier version returned SATISFIED with the reason
# "settled from the mesh and the declared orientation" while nothing was
# settling anything, which is a fabricated claim on a receipt.
NOT_YET_MEASURED = {
    "inserts": "insert-pocket reachability and retention",
    "threads": "thread engagement and pitch as printed",
    "captive-hardware": "whether the hardware can be placed and stays captive",
    "split-body": "seam registration and the sealing method the plan owes",
}

KNOWN_MODIFIERS = frozenset(SLICER_DEPENDENT) | frozenset(NOT_YET_MEASURED)


def manufacturing(contract: Contract, commission_report: dict[str, Any]) -> dict[str, Any] | None:
    """What the modifiers require, and how much of it geometry can settle."""
    if not contract.modifiers:
        return None

    predicates: list[dict[str, Any]] = []
    for modifier in contract.modifiers:
        if modifier in SLICER_DEPENDENT:
            predicates.append({
                "modifier": modifier, "predicate": SLICER_DEPENDENT[modifier],
                "result": "DEFERRED",
                "reason": "no slicer adapter is configured; this stack is uv, build123d, "
                          "trimesh and manifold3d, none of which produces toolpaths"})
        elif modifier in NOT_YET_MEASURED:
            predicates.append({
                "modifier": modifier, "predicate": NOT_YET_MEASURED[modifier],
                "result": "DEFERRED",
                "reason": "no check in this build measures it yet"})
        else:
            predicates.append({
                "modifier": modifier, "predicate": "unknown modifier",
                "result": "BLOCKED",
                "reason": f"{modifier!r} is not one of {sorted(KNOWN_MODIFIERS)}; a "
                          "modifier nobody implements cannot be reported as handled"})

    deferred = [p for p in predicates if p["result"] == "DEFERRED"]
    blocked = [p for p in predicates if p["result"] == "BLOCKED"]
    overall = "BLOCKED" if blocked else ("DEFERRED" if deferred else "SATISFIED")
    return {
        "schema_version": S.MANUFACTURING_SCHEMA,
        "job_id": contract.job_id,
        "contract_sha256": contract.contract_hash(),
        "modifiers": list(contract.modifiers),
        "slicer_adapter": None,
        "overall": overall,
        "predicates": predicates,
        "commission_verdict": commission_report["verdict"],
    }


def decide(*, contract: Contract, commission_report: dict[str, Any],
           screening: dict[str, Any], manufacturing: dict[str, Any] | None,
           safety: dict[str, Any] | None, artifact: dict[str, Any],
           verification: dict[str, Any] | None, updated_utc: str,
           route: str = "DIRECT") -> dict[str, Any]:
    reasons: list[str] = []
    verdict = commission_report["verdict"]
    witness = commission_report.get("witness") or {}
    rendered = bool(witness.get("rendered"))

    if verdict == "FAIL":
        final, claim = "FAILED", "the geometry does not match its contract"
        reasons.append("commissioning failed")
    elif verdict == "ESCALATE":
        final = "NEEDS_MORE_EVIDENCE"
        claim = "a check could not run and the contract said to escalate rather than pass"
        reasons.append("commissioning escalated")
    elif screening["overall"] == "ANOMALY":
        final = "NEEDS_MORE_EVIDENCE"
        claim = "screening found geometry the contract does not explain"
        reasons.append("screening reported an anomaly")
    elif screening["overall"] == "INDETERMINATE":
        final = "NEEDS_MORE_EVIDENCE"
        claim = "a screening detector could not run, so the part was not broadly screened"
        reasons.append("screening was indeterminate")
    else:
        final, claim = "COMMISSIONED", "geometrically commissioned against its contract"
        if not screening.get("calibrated", False) and verification is None:
            # The plan's hard gate, and it has to move the status or it is a
            # string. An uncalibrated screen plus nobody looking means the one
            # question no declared check can ask went unasked -- and the measured
            # miss rate on fused undeclared material is 30% -- measured on a
            # corpus whose mutants are actually fused to the part, which the
            # first one was not.
            final = "NEEDS_MORE_EVIDENCE"
            claim = ("the geometry matches its contract, but the broad screen is "
                     "uncalibrated and nobody independent looked, so undeclared "
                     "geometry cannot be ruled out. Supply a verifier, or say plainly "
                     "that nothing has looked at this part.")
            reasons.append("screening is uncalibrated and no independent look ran")
        elif not screening.get("calibrated", False):
            # Only claim the look covered it if there was something to look at.
            reasons.append(
                "screening is uncalibrated; the independent review is what covers "
                "undeclared geometry here"
                + ("" if rendered else " -- and it saw no images, only numbers"))

    if final in ("COMMISSIONED", "VERIFIED"):
        if manufacturing and manufacturing["overall"] == "DEFERRED":
            unproven = ", ".join(p["predicate"] for p in manufacturing["predicates"]
                                 if p["result"] == "DEFERRED")
            final = "COMMISSIONED"
            claim = f"geometrically commissioned; not verified: {unproven}"
            reasons.append("a required manufacturing predicate is deferred")
        elif manufacturing and manufacturing["overall"] == "BLOCKED":
            final, claim = "FAILED", "a manufacturing predicate is blocked"
            reasons.append("manufacturing blocked")

    if contract.consequence == "CONSEQUENTIAL":
        # A safety review of a part nobody could see is a review of numbers. The
        # renderer is not on the core path, so this is the ordinary case rather
        # than an exotic one, and it used to pass in silence: witness.renderer
        # recorded "unavailable" and no consumer read it.
        if not rendered:
            reasons.append("no renders were produced, so the safety reviewer saw "
                           "numbers and no images")
        if safety is None:
            final = "NEEDS_MORE_EVIDENCE"
            claim = "consequential, and no final safety verification was performed"
            reasons.append("safety verification is mandatory and absent")
        elif safety["decision"] == "BLOCK":
            final = "FAILED"
            claim = f"blocked on safety review: {safety['summary'][:160]}"
            reasons.append("safety review returned BLOCK")
        elif safety["decision"] == "NEEDS_MORE_EVIDENCE":
            final = "NEEDS_MORE_EVIDENCE"
            claim = "the safety reviewer needs evidence this run did not produce"
            reasons.append("safety review needs more evidence")
        elif not rendered and final in ("COMMISSIONED", "VERIFIED"):
            final = "NEEDS_MORE_EVIDENCE"
            claim = ("consequential, and the safety review saw no images -- install the "
                     "render extra and re-run, or say plainly that nobody has looked "
                     "at this part")
        elif final == "COMMISSIONED" and verification is None:
            # A passing safety review is not independent verification of the
            # geometry -- it reviewed hazards, not whether the part matches the
            # brief. VERIFIED still requires a verifier.
            reasons.append("safety review passed; no independent geometric verification ran")

    if verification is not None:
        decision = verification.get("decision")
        if decision == "REJECT":
            # A rejection must move the status. Leaving it at COMMISSIONED read
            # as "geometrically commissioned against its contract" while an
            # independent reader had just said the part is wrong -- the claim was
            # true about the geometry and silent about the finding, which is the
            # worst combination a receipt can have.
            defects = verification.get("defects") or []
            loops = sorted({d.get("owning_loop", "?") for d in defects})
            final = "FAILED"
            claim = (f"rejected by independent verification ({len(defects)} defect(s), "
                     f"owned by {', '.join(loops) or 'an unnamed loop'}): "
                     f"{verification.get('summary', '')[:120]}")
            reasons.append("independent verification returned REJECT")
        elif decision == "NEEDS_MORE_EVIDENCE" and final in ("COMMISSIONED", "VERIFIED"):
            final = "NEEDS_MORE_EVIDENCE"
            claim = ("independent verification could not decide on the evidence this "
                     "run produced")
            reasons.append("independent verification needs more evidence")
        elif decision == "PASS" and final == "COMMISSIONED":
            if manufacturing and manufacturing["overall"] == "DEFERRED":
                reasons.append("verified geometrically; a manufacturing predicate is "
                               "still deferred, so the job stays COMMISSIONED")
            else:
                final = "VERIFIED"
                # Say which kind of verification it was. The verifier is asked
                # "is anything visible in the witnesses that no contract row
                # declares?" -- with no images it can only answer from numbers,
                # and undeclared geometry is exactly what numbers do not cover.
                # The unqualified claim went out on jobs where nothing had been
                # seen, over a reason that read "the independent look is what
                # covers undeclared geometry here". There was no look.
                if rendered:
                    claim = "independently verified against its contract"
                else:
                    claim = ("independently verified against its contract on "
                             "measurements alone -- no images were rendered, so "
                             "nobody has seen this part")
                    reasons.append("verification saw no images; undeclared geometry "
                                   "is not covered by a numeric check")

    S.require_enum(final, S.FINAL_STATUS, what="final_status")
    return {
        "schema_version": S.STATUS_SCHEMA,
        "job_id": contract.job_id,
        "consequence": contract.consequence,
        # Threaded, not assumed. It was the literal "DIRECT" from the days when
        # DIRECT was the only route, so every FITTED job's authoritative receipt
        # said it had cost no dispatches. Nothing read the field, which is how it
        # survived -- a receipt nobody reads is still a receipt somebody may.
        "route": route,
        "backend": contract.backend,
        "template": f"{contract.template}@{contract.template_version}",
        "domain_id": contract.domain_id,
        "commission_verdict": verdict,
        "screening": screening["overall"],
        "screening_calibrated": screening.get("calibrated", False),
        "witnesses_rendered": rendered,
        "manufacturing": manufacturing["overall"] if manufacturing else None,
        "verification": verification["decision"] if verification else None,
        "safety_verification": safety["decision"] if safety else None,
        "final_status": final,
        "allowed_claim": claim,
        "reasons": reasons,
        "artifact_hashes": {"contract": artifact["contract_sha256"],
                            "stl": artifact["stl_sha256"],
                            "step": artifact.get("step_sha256"),
                            "source": artifact["source_sha256"]},
        "updated_utc": updated_utc,
    }
