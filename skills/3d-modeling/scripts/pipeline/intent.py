#!/usr/bin/env python3
"""Normalized intent, and the routing decision written down.

Two things live here that used to live nowhere.

**Stated versus inferred, per value.** Defaulting an unmarked number to "the user
said this" fabricates authority. A brief asking for a clip over a 12 mm bundle
states three numbers and the template takes eight; the other five were chosen by
whoever ran the job. The default is `inferred`, which understates and invites
scrutiny -- the failure direction that is safe.

**Why this route, and why not the others.** Routing was the one decision in the
pipeline that left no trace, so it could be neither audited nor regression-tested.
Recorded as candidates with specific rejection reasons, "this brief must reject
c_clip because bore_d=60 exceeds the certified 40 mm bound" becomes an assertion.
"""
from __future__ import annotations

import dataclasses
from typing import Any

from . import schemas as S
from . import templates as T


@dataclasses.dataclass(frozen=True)
class Candidate:
    template: str
    version: str
    domain_id: str
    matched: bool
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"template": self.template, "version": self.version,
                "domain_id": self.domain_id, "matched": self.matched,
                "reasons": list(self.reasons)}


@dataclasses.dataclass(frozen=True)
class RouteDecision:
    route: str
    template: str | None
    backend: str | None
    condition: str
    candidates: tuple[Candidate, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"route": self.route, "template": self.template, "backend": self.backend,
                "condition": self.condition,
                "candidates": [c.as_dict() for c in self.candidates]}


def select(*, requested_template: str | None, parameters: dict[str, Any],
           external_geometry: bool, ambiguities: tuple[str, ...]) -> RouteDecision:
    """Deterministic route selection, with every rejection recorded.

    The question is not whether the part touches something -- almost everything
    does, and reading contact as mating sends every job to `FITTED`. It is whether
    acceptance depends on something a trusted input and a certified template
    cannot represent.
    """
    candidates: list[Candidate] = []
    match: T.CertifiedTemplate | None = None

    for name, template in sorted(T.registry().items()):
        if requested_template and name != requested_template:
            candidates.append(Candidate(name, template.version, template.domain_id, False,
                                        (f"not the requested template ({requested_template})",)))
            continue
        reasons = template.rejects(parameters)
        matched = not reasons
        candidates.append(Candidate(name, template.version, template.domain_id, matched,
                                    tuple(reasons) or ("covers the requested geometry",)))
        if matched and match is None:
            match = template

    if external_geometry:
        return RouteDecision("FITTED", match.name if match else None,
                             match.backend if match else None,
                             "acceptance depends on externally owned geometry, which no "
                             "trusted input represents", tuple(candidates))
    if ambiguities:
        return RouteDecision("FITTED", match.name if match else None,
                             match.backend if match else None,
                             f"unresolved ambiguity: {'; '.join(ambiguities)}",
                             tuple(candidates))
    if match is None:
        # Not DIRECT -- and deliberately not FITTED by default. A novel shape
        # outside every certified domain often has no external object to measure,
        # and calling that "fitted" would be wrong about what the work is.
        return RouteDecision("FULL", None, None,
                             "no certified template covers this geometry inside its domain",
                             tuple(candidates))
    return RouteDecision("DIRECT", match.name, match.backend,
                         f"{match.name} covers the geometry and every parameter is inside "
                         f"{match.domain_id}", tuple(candidates))


def manifest(*, job_id: str, brief_text: str, brief_hash: str, parameters: dict[str, Any],
             stated: frozenset[str], consequence: str, modifiers: tuple[str, ...],
             candidate_strategy: str, ambiguities: tuple[str, ...],
             decision: RouteDecision, updated_utc: str) -> dict[str, Any]:
    S.require_enum(consequence, S.CONSEQUENCE, what="consequence")
    S.require_enum(candidate_strategy, S.CANDIDATE_STRATEGY, what="candidate_strategy")
    return {
        "schema_version": S.INTENT_SCHEMA,
        "job_id": job_id,
        "brief_sha256": brief_hash,
        "brief_chars": len(brief_text),
        "consequence": consequence,
        "modifiers": list(modifiers),
        "candidate_strategy": candidate_strategy,
        "unresolved_ambiguities": list(ambiguities),
        "requirements": [
            {"name": name, "value": value, "unit": "mm",
             "provenance": "stated in the brief" if name in stated else "chosen by design",
             "source": "user" if name in stated else "designer"}
            for name, value in sorted(parameters.items())
        ],
        "route_decision": decision.as_dict(),
        "updated_utc": updated_utc,
    }
