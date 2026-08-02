#!/usr/bin/env python3
"""The route authority: one decision, made over the canonical project.

`intent.select` used to answer two different questions with one function --
"does a certified template cover this?" and "what workflow does this job need?"
-- and could only see a parameter dict, so the second answer had to be inferred
from the first. That is why a novel from-scratch part came back `FULL` and then
got refused for having no certified template to recover parameters into.

Here the two are separated. `intent.select` keeps the first question, with its
recorded candidates and named bounds. This module answers the second, over a
project that can actually say whether geometry is being reconstructed, how many
parts there are, whether anything moves, and who owns the other side of each
interface.

**Consequence is not a route.** It never selects a workflow; it adds the
mandatory safety pass and it is one of the triggers that turns an independent
verification on. A `CONSEQUENTIAL` single bracket with stated dimensions is still
`DIRECT` in shape.

**Source mode is not a route either.** `MODIFY` does not force `FITTED`: a
supplied STEP that is trusted and needs no reconciliation is a `CUSTOM` job with
an edit scope. What forces `FITTED` is reconciliation -- two sources that have to
be made to agree -- which is exactly the metrologist's product.
"""
from __future__ import annotations

import dataclasses
from typing import Any

from . import intent
from . import project as P


@dataclasses.dataclass(frozen=True)
class RouteDecision:
    route: str
    template: str | None
    backend: str | None
    condition: str
    source_mode: str
    # Why an independent verification is required on this job. Empty means the
    # route's own policy decides, and on CUSTOM that means it may finish
    # COMMISSIONED.
    escalations: tuple[str, ...]
    requires_verification: bool
    requires_metrology: bool
    # Each route that was not taken, and the reason. Routing was the one decision
    # in the pipeline that left no trace, so it could be neither audited nor
    # regression-tested.
    considered: tuple[dict[str, Any], ...]
    candidates: tuple[intent.Candidate, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "route": self.route, "template": self.template, "backend": self.backend,
            "condition": self.condition, "source_mode": self.source_mode,
            "escalations": list(self.escalations),
            "requires_verification": self.requires_verification,
            "requires_metrology": self.requires_metrology,
            "considered": [dict(row) for row in self.considered],
            "candidates": [c.as_dict() for c in self.candidates],
        }


# What makes a job need the complete workflow. Each is a fact about the job, not
# a judgement about its difficulty, so a router and a reader reach the same
# answer from the same project file.
def _full_reasons(project: P.Project) -> list[str]:
    reasons: list[str] = []
    parts = sum(component.count for component in project.components)
    if parts > 1:
        reasons.append(f"{parts} interacting parts are expected")
    if len(project.external_interfaces) > 1:
        reasons.append(f"{len(project.external_interfaces)} externally owned "
                       "interfaces have to agree at once")
    if project.motion:
        moving = ", ".join(sorted(m.motion_id for m in project.motion))
        reasons.append(f"declared motion ({moving}): a static pose cannot answer a "
                       "question about a path")
    # `candidate_strategy == "PARALLEL"` used to add a fifth reason here, and that
    # sentence was the entire behaviour of the field: no second candidate was
    # produced, isolated or compared, so a project asking for alternatives got one
    # candidate and a longer rationale. Competing formulations are branches now,
    # and a branch is a directory with its own contract rather than a route
    # escalation on the job that did not get one.
    return reasons


def _metrology_reasons(project: P.Project) -> list[str]:
    """When two sources have to be reconciled, which is the metrologist's work."""
    reasons: list[str] = []
    if project.source_mode == "RECONSTRUCT":
        reasons.append("source_mode is RECONSTRUCT: the geometry has to be recovered "
                       "from evidence")
    for artifact in project.source_artifacts:
        if artifact.classification == "RECONSTRUCTION_REQUIRED":
            reasons.append(f"source artifact {artifact.artifact_id!r} is classified "
                           "RECONSTRUCTION_REQUIRED and cannot be built on")
    if project.external_interfaces and project.evidence:
        reasons.append("an externally owned interface is backed by photographic or "
                       "caliper evidence, which has to be reconciled with the brief")
    return reasons


def _verification_reasons(project: P.Project, route: str) -> list[str]:
    """Why a `CUSTOM` job cannot finish on deterministic gates alone.

    `FITTED` and `FULL` carry their own required reviews and only need to say so.
    `DIRECT` gets almost none of this: its whole route trade is deterministic
    commissioning of a certified template without an independent look, and a
    `CONSEQUENTIAL` `DIRECT` job gets exactly one bounded safety review rather
    than a geometric verifier on top. Consequence does not add a geometric review
    merely because the job is consequential.

    The one thing `DIRECT` does not get to discard is an explicit ask. Returning
    early for the whole route dropped `verification_requested` on the floor: the
    user turned a verifier on, the project recorded it, and nothing downstream
    ever read it -- a request that vanishes without a receipt is worse than one
    that is refused, because nobody can tell which happened.

    The list is additive by construction: nothing here can remove a review, only
    turn one on.
    """
    if route == "DIRECT":
        return (["independent verification was explicitly requested"]
                if project.verification_requested else [])
    reasons: list[str] = []
    if project.consequence == "CONSEQUENTIAL":
        reasons.append("the job is CONSEQUENTIAL")
    if project.external_interfaces:
        named = ", ".join(sorted(i.interface_id for i in project.external_interfaces))
        reasons.append(f"externally owned interface(s): {named}")
    if project.motion:
        reasons.append("motion is declared")
    for artifact in project.source_artifacts:
        if artifact.classification == "REPAIR_REQUIRED":
            reasons.append(f"source artifact {artifact.artifact_id!r} needs repair "
                           "before it can be built on")
    if project.verification_requested:
        reasons.append("independent verification was explicitly requested")
    if project.blocking_questions:
        reasons.append(f"{len(project.blocking_questions)} unresolved question(s) "
                       "remain")
    if route in ("FITTED", "FULL"):
        reasons.append(f"the {route} route requires it")
    return reasons


def _legacy(project: P.Project) -> RouteDecision:
    """Reproduce `intent.select`'s answers for a project adapted from job.json.

    A legacy job has no source mode, no components, no declared interfaces and no
    motion, so the questions the new model is built on have no answers. Guessing
    at them would silently re-route jobs that were routing correctly, which is
    the one thing a compatibility adapter must not do.

    One thing it does read, because it is on the project in front of it and no
    guess is involved: `verification_requested`. `P.load` deserializes the field
    and this function ignored it, so on any `compat: "job.json@1"` project an
    explicit ask for an independent look vanished with no receipt anywhere. A
    request that disappears in silence is worse than one that is refused, because
    nobody downstream can tell which of the two happened.
    """
    decision = intent.select(
        requested_template=project.template, parameters=project.parameters,
        external_geometry=bool(project.status.get("external_geometry", False)),
        ambiguities=project.blocking_questions)
    escalations = ["the job was adapted from job.json and routes under the legacy "
                   "rules"]
    if project.verification_requested:
        escalations.append("independent verification was explicitly requested")
    return RouteDecision(
        route=decision.route, template=decision.template, backend=decision.backend,
        condition=decision.condition, source_mode=project.source_mode,
        escalations=tuple(escalations),
        requires_verification=(decision.route == "FULL"
                               or project.verification_requested),
        requires_metrology=decision.route in ("FITTED", "FULL"),
        considered=({"route": "CUSTOM", "taken": False,
                     "why": "job.json carries no source mode, so the CUSTOM "
                            "preconditions cannot be checked"},),
        candidates=decision.candidates)


def decide(project: P.Project) -> RouteDecision:
    """The route, the reason, and every route that was not taken."""
    if project.compat == "job.json@1":
        return _legacy(project)

    match = intent.select(requested_template=project.template,
                          parameters=project.parameters,
                          external_geometry=False, ambiguities=())
    template_covers = match.route == "DIRECT"
    considered: list[dict[str, Any]] = []

    full_reasons = _full_reasons(project)
    metrology_reasons = _metrology_reasons(project)
    one_external = len(project.external_interfaces) == 1

    if full_reasons:
        route = "FULL"
        condition = "; ".join(full_reasons)
        considered.extend([
            {"route": "DIRECT", "taken": False,
             "why": "the complete workflow is required: " + condition},
            {"route": "CUSTOM", "taken": False,
             "why": "CUSTOM is one designer commission; this job has more than one "
                    "thing that has to agree"},
            {"route": "FITTED", "taken": False,
             "why": "FITTED is a single candidate against one external object"},
        ])
    elif metrology_reasons or one_external:
        route = "FITTED"
        condition = "; ".join(metrology_reasons) or (
            "acceptance depends on one externally owned object: "
            + project.external_interfaces[0].interface_id)
        considered.extend([
            {"route": "DIRECT", "taken": False,
             "why": "a dimension this job does not get to choose has to be recovered "
                    "first"},
            {"route": "CUSTOM", "taken": False,
             "why": "CUSTOM requires every value stated, cited, inherited or chosen; "
                    "this job has one to reconcile"},
            {"route": "FULL", "taken": False,
             "why": "one external object, one candidate, nothing moving"},
        ])
    elif (template_covers and project.model is None and not project.edit_scopes
            and not project.blocking_questions):
        route = "DIRECT"
        condition = match.condition
        considered.extend([
            {"route": "CUSTOM", "taken": False,
             "why": f"{match.template} covers the geometry inside its certified "
                    "domain, so no designer commission is needed"},
            {"route": "FITTED", "taken": False,
             "why": "nothing has to be recovered from evidence"},
            {"route": "FULL", "taken": False,
             "why": "one part, no motion, no external interfaces"},
        ])
    else:
        route = "CUSTOM"
        if len(project.edit_scopes) == 1:
            condition = (f"an existing artifact is being modified inside "
                         f"{project.edit_scopes[0].region!r}")
        elif project.edit_scopes:
            # Named per artifact rather than collapsed into a count: two edits
            # that have to agree are the reason this route was taken, and a
            # rationale that says only "2 artifacts" cannot be checked against
            # the scopes it came from.
            named = "; ".join(f"{s.artifact_id} inside {s.region!r}"
                              for s in project.edit_scopes)
            condition = (f"{len(project.edit_scopes)} existing artifacts are being "
                         f"modified together -- {named}")
        elif not template_covers:
            condition = ("no certified template covers this geometry inside its "
                         "domain, and nothing has to be recovered from evidence")
        elif project.blocking_questions:
            condition = ("a certified template covers the shape but "
                         f"{len(project.blocking_questions)} question(s) are still "
                         "open")
        else:
            condition = "custom geometry is authored for this job"
        considered.extend([
            {"route": "DIRECT", "taken": False,
             "why": ("DIRECT is certified deterministic templates only; " + condition)},
            {"route": "FITTED", "taken": False,
             "why": "nothing has to be reconciled against an external object"},
            {"route": "FULL", "taken": False,
             "why": "one part, no motion, at most one external interface"},
        ])

    escalations = tuple(_verification_reasons(project, route))
    requires_verification = route in ("FITTED", "FULL") or bool(escalations)
    # FITTED's own review policy already covers this, but recording it keeps the
    # decision readable without knowing the route table by heart.
    requires_metrology = route in ("FITTED", "FULL") and bool(
        metrology_reasons or project.evidence or project.external_interfaces)

    return RouteDecision(
        route=route,
        template=match.template if route in ("DIRECT", "FITTED", "FULL") else None,
        backend=match.backend if route == "DIRECT" else None,
        condition=condition, source_mode=project.source_mode,
        escalations=escalations, requires_verification=requires_verification,
        requires_metrology=requires_metrology,
        considered=tuple(considered), candidates=match.candidates)


def required_reviews(project: P.Project, decision: RouteDecision) -> tuple[str, ...]:
    """The reviews this job needs, derived rather than accumulated.

    Derived, and never unioned with whatever the field already held: a route that
    moves must be able to *drop* a review it no longer requires. Accumulating
    left a `CONSEQUENTIAL` `DIRECT` job claiming it needed an independent
    verification it will never dispatch, which reads as an unmet obligation
    rather than as the route trade it actually is.
    """
    reviews: set[str] = set()
    if project.consequence == "CONSEQUENTIAL":
        reviews.add("safety")
    if decision.requires_verification:
        reviews.add("verification")
    if decision.requires_metrology:
        reviews.add("specification")
    return tuple(sorted(reviews))


def apply(project: P.Project, decision: RouteDecision) -> P.Project:
    """Record the decision on the project, without touching anything else."""
    project.route = decision.route
    project.route_rationale = decision.condition
    project.required_reviews = required_reviews(project, decision)
    return project
