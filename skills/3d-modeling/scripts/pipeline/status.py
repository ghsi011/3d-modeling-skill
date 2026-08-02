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

from . import review as R
from . import safety as _safety_review
from . import schemas as S
from . import verification as _verification_review
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
    # A motion path is a claim about clearance through a *sweep* -- the part moving
    # along a trajectory without colliding. Every check in this build reads one
    # static pose, and a single pose cannot answer a question about motion. Named
    # explicitly so it is DEFERRED rather than silently implied complete or
    # falling through to a bare "unknown modifier" that says nothing about why.
    "motion_path": "swept-volume clearance along the declared motion path",
}

KNOWN_MODIFIERS = frozenset(SLICER_DEPENDENT) | frozenset(NOT_YET_MEASURED)


def _promotable(report: dict[str, Any] | None, kind: str,
                envelope: R.ReviewEnvelope | None) -> bool:
    """Bound to the current request, and itself a complete, closed answer.

    Envelope equality says the report answers this request. It says nothing
    about what the answer is: a partial report, or a PASS that carries its own
    contradictions -- defects, failure modes, missing evidence, an empty
    summary -- was refused when it was first validated, and it is refused
    again here. The status layer is the last place a malformed pass can be
    caught, so it re-runs the checks rather than trusting that somebody else
    did.
    """
    if envelope is None or not isinstance(report, dict):
        return False
    if not R.is_bound(report, kind, envelope.digest()):
        return False
    try:
        if kind == "safety":
            _safety_review.validate(report)
            R.require_safety_pass_closed(report)
        else:
            _verification_review.validate(report)
            R.require_verification_pass_closed(report)
    except (S.SchemaError, R.ReviewError):
        return False
    return True


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


# How much of a check's own error message the claim string carries. Long enough
# for a module name and a path, short enough that a summary line stays a summary.
_REASON_CHARS = 160


def _unavailable(commission_report: dict[str, Any]) -> list[dict[str, Any]]:
    """The declared checks that never ran, with the code that says why.

    `commission_report` keeps the distinction perfectly already -- `ran: false`,
    `status: UNAVAILABLE`, `measured: null`, `error_code`, and the exception as
    the reason -- and nothing carried it any further. `final_status.json` said
    only "rejected by independent verification" and the CLI summary said the
    same, so a user who did not open `commission_report.json` learned that a
    reviewer rejected their part rather than that the tool could not read their
    primary source. Those demand different actions, and only one of them is the
    user's fault.
    """
    rows: list[dict[str, Any]] = []
    for check in commission_report.get("checks") or []:
        if not isinstance(check, dict) or check.get("status") != "UNAVAILABLE":
            continue
        rows.append({"check_id": check.get("check_id"),
                     "feature_id": check.get("feature_id"),
                     "error_code": check.get("error_code"),
                     "reason": (check.get("error_message") or check.get("reason")
                                or "")[:_REASON_CHARS],
                     "result": check.get("result")})
    return rows


def _names(rows: list[dict[str, Any]]) -> str:
    return "; ".join(f"{r['check_id']} ({r['error_code']}): {r['reason']}"
                     for r in rows)


def decide(*, contract: Contract, commission_report: dict[str, Any],
           screening: dict[str, Any], manufacturing: dict[str, Any] | None,
           safety: dict[str, Any] | None, artifact: dict[str, Any],
           verification: dict[str, Any] | None, updated_utc: str,
           route: str = "DIRECT",
           execution_plan_sha256: str | None = None,
           lane_status: str = "AVAILABLE", lane_note: str = "",
           safety_envelope: R.ReviewEnvelope | None = None,
           verification_envelope: R.ReviewEnvelope | None = None) -> dict[str, Any]:
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
        unavailable_sections = [s for s in witness.get("sections", [])
                                if s.get("status") == "UNAVAILABLE"]
        if unavailable_sections:
            final = "NEEDS_MORE_EVIDENCE"
            claim = ("witness section(s) could not be measured; the part was not "
                     "fully verified")
            reasons.append(
                f"witness sections unavailable: {len(unavailable_sections)} section(s) "
                f"at z={[s.get('z') for s in unavailable_sections]}")
        elif manufacturing and manufacturing["overall"] == "DEFERRED":
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
        if safety is None or not _promotable(safety, "safety", safety_envelope):
            final = "NEEDS_MORE_EVIDENCE"
            claim = "consequential, and no final safety verification was performed"
            reasons.append("safety verification is mandatory and absent, unbound "
                           "or invalid")
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
        if not _promotable(verification, "verification", verification_envelope):
            final = "NEEDS_MORE_EVIDENCE"
            claim = "independent verification is unbound or invalid and cannot be trusted"
            reasons.append("verification report is unbound or invalid")
        else:
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

    if lane_status != "AVAILABLE":
        # Recorded on every run of an experimental lane, whatever the verdict, so
        # the limitation is legible on a FAILED receipt too -- a reader who only
        # sees it when the job would otherwise have succeeded learns it at the
        # worst possible moment.
        reasons.append(lane_note)
        if final in ("COMMISSIONED", "VERIFIED"):
            # The deterministic work is done and on disk; what is withheld is the
            # claim. Downgrading only a successful verdict is deliberate: FAILED
            # and NEEDS_MORE_EVIDENCE are findings this lane *is* entitled to
            # report, and overwriting them would hide a real defect behind an
            # architectural caveat.
            #
            # The cap's own name carries through rather than collapsing to one
            # value: `UNSUPPORTED` means no stage is coming and
            # `EXPERIMENTAL_UNAVAILABLE` means one is, and a caller that cannot
            # tell them apart either waits forever or gives up too early.
            final = lane_status
            # "yet" only where a stage is actually coming. On `UNSUPPORTED` it
            # would be the same false promise the shared status name used to make.
            when = "yet" if lane_status == "EXPERIMENTAL_UNAVAILABLE" else "at all"
            claim = (f"not claimable on this lane {when} -- {lane_note}. What did "
                     f"run is on disk: {claim}.")

    # Last, and after the lane cap, because this is true of every verdict above
    # and none of them owns it. A rejection, a failure and a capped success can
    # each sit beside a check that never ran, and the sentence a user reads has to
    # carry both -- the reason the part was refused, and the fact that one of the
    # instruments never measured.
    unavailable = _unavailable(commission_report)
    if unavailable:
        named = _names(unavailable)
        reasons.append(f"{len(unavailable)} declared check(s) could not run: {named}")
        claim = (f"{claim.rstrip('. ')}. Separately, {len(unavailable)} declared "
                 f"check(s) never ran and measured nothing: {named}. That is this "
                 f"tool failing to measure, not a finding about the part.")

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
        # Which plan produced this receipt. The route above is only trustworthy
        # if it is the one that was compiled: the runner used to re-derive its
        # own and write that instead, so a FITTED job's status said "DIRECT"
        # while `route_decision.json` beside it said FITTED.
        "execution_plan_sha256": execution_plan_sha256,
        "lane_status": lane_status,
        "backend": contract.backend,
        "template": f"{contract.template}@{contract.template_version}",
        "domain_id": contract.domain_id,
        "commission_verdict": verdict,
        "screening": screening["overall"],
        "screening_calibrated": screening.get("calibrated", False),
        "witnesses_rendered": rendered,
        "manufacturing": manufacturing["overall"] if manufacturing else None,
        # `.get`, not subscript: a report that reached this layer without a
        # decision was refused above, and the receipt's own serialization must
        # not KeyError on the way out.
        "verification": verification.get("decision") if verification else None,
        "safety_verification": safety.get("decision") if safety else None,
        "final_status": final,
        "allowed_claim": claim,
        # Structured beside the sentence, so a caller that reads JSON does not
        # have to parse prose to find out which instrument failed.
        "unavailable_checks": unavailable,
        "reasons": reasons,
        "artifact_hashes": {"contract": artifact["contract_sha256"],
                            "stl": artifact["stl_sha256"],
                            "step": artifact.get("step_sha256"),
                            "source": artifact["source_sha256"]},
        "updated_utc": updated_utc,
    }
