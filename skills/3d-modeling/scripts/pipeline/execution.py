#!/usr/bin/env python3
"""The execution plan: compiled once, and executed exactly as compiled.

`route.py` was the declared route authority and the runner kept a second copy of
the answer. On the certified lane the runner re-derived the route from
`intent.select` -- which can only ask "does a certified template cover these
parameters?" -- and then every downstream guard read *that* answer: which reviews
were dispatched, and which route the final receipt claimed.

Two routing authorities is one authority and one bug. What it cost, measured on
the shipped code:

* a `RECONSTRUCT` job whose parameters happen to sit inside a certified domain
  routed `FITTED`, owed a specification and a verification, and then executed as
  `DIRECT`: no metrologist, no verifier, `"route": "DIRECT"` on its own final
  status, and a claim asking for a verifier that had already been supplied;
* a `FULL` job with no evidence and no external interface was refused at the
  routing stage for a metrologist the route decision had correctly not asked for.

Neither was resolvable by anything the agent could do, because the two copies
disagreed about the job rather than about the answer.

So: one compiler, one plan, and a runner that consumes it. The plan is
*compiled*, never authored -- there is no hand-written `execution_plan.json` and
no extra command; `design-tool run` compiles it in-process, deterministically,
and pays no dispatch for it.

**The distinction the compiler exists to keep.** A route is a statement about
evidence and review obligations. A builder is a statement about where the
geometry comes from. Template matching answers the second question only: a
certified template used by a `FITTED` job leaves it `FITTED`, and used by a
`FULL` job leaves it `FULL`. Collapsing the two is the defect above.
"""
from __future__ import annotations

import dataclasses
from typing import Any

from . import intent
from . import project as P
from . import route as RT
from . import schemas as S
from . import templates as T

EXECUTION_PLAN_SCHEMA = 1
EXECUTION_PLAN_FILE = "execution_plan.json"

# Where the geometry comes from, which is not what the route decides. Two
# providers, not the four axes ADR 0002 names: imported geometry and
# reconstruction are not separate builders in this build -- a MODIFY edit is an
# authored module that imports the artifact, and a reconstruction is a certified
# template whose dimensions the metrologist recovers. Naming providers that do
# not exist would put a distinction on the receipt that nothing behind it makes.
BUILDER = ("CERTIFIED_TEMPLATE", "AUTHORED")

# Whether an independent verifier may be dispatched at all.
#
# `NEVER` is `DIRECT`'s own route trade written down: its whole bargain is
# deterministic commissioning of a certified template with nobody independent
# looking, and a verifier that happens to be reachable is not a free extra look.
# `OPTIONAL` is a look worth taking when the broad screen came back clear;
# `REQUIRED` is an obligation the run cannot drop because a screen was messy.
DISPATCH = ("NEVER", "OPTIONAL", "REQUIRED")

# Whether this lane may claim success at all. `EXPERIMENTAL_UNAVAILABLE` does not
# stop the deterministic work: the build, the gates, the screen and the witnesses
# all run and all write their receipts, because a designer has to be able to
# iterate against real measurements. What it stops is the claim -- see
# `status.decide`.
LANE_STATUS = ("AVAILABLE", "EXPERIMENTAL_UNAVAILABLE")

# Why each lane cannot yet certify its own result -- the specific failure, not a
# general caveat, and stated once here so the receipt and the CLI say the same
# sentence. Both are lifted by named stages of ADR 0002 and not by anything an
# agent can supply on a run.
CUSTOM_LANE_NOTE = (
    "the CUSTOM lane still re-reads its acceptance criteria out of the model "
    "file it is judging, so a designer can widen an expectation after seeing it "
    "missed and be commissioned on the next run; until the acceptance contract "
    "is frozen before the build, a pass here is self-issued and may not be "
    "reported COMMISSIONED or VERIFIED")
MODIFY_LANE_NOTE = (
    "the MODIFY lane carries the same self-issued acceptance criteria as CUSTOM, "
    "and its preservation audit samples unseeded -- two runs of one unchanged "
    "pair disagree, and a small undeclared addition outside the edit region was "
    "reported preserved in most of twenty audits; until both are settled this "
    "lane may not report a part COMMISSIONED or VERIFIED")
AUTHORED_METROLOGY_NOTE = (
    "this job owes a bounded metrology recovery, and recovery is defined only "
    "against a certified template's covers and bounds -- nothing in this build "
    "can recover an externally owned dimension into authored geometry, so the "
    "specification this route requires cannot be produced")


@dataclasses.dataclass(frozen=True)
class ExecutionPlan:
    """What will actually be executed, and what it will be allowed to claim."""

    job_id: str
    route: str
    route_rationale: str
    source_mode: str
    builder: str
    template: str | None
    backend: str | None
    model: str | None
    required_reviews: tuple[str, ...]
    verification_dispatch: str
    lane_status: str
    lane_note: str
    # Audit detail, not identity: the rejected certified templates are recorded
    # in `route_decision.json` and carried here only so the intent manifest can
    # keep naming them. Two plans that execute identically must hash identically
    # even if a sixth certified template is added to the registry.
    candidates: tuple[intent.Candidate, ...] = ()

    @property
    def requires_specification(self) -> bool:
        return "specification" in self.required_reviews

    @property
    def requires_safety(self) -> bool:
        return "safety" in self.required_reviews

    @property
    def requires_verification(self) -> bool:
        return "verification" in self.required_reviews

    def as_payload(self) -> dict[str, Any]:
        return {
            "schema_version": EXECUTION_PLAN_SCHEMA,
            "job_id": self.job_id,
            "route": self.route,
            "route_rationale": self.route_rationale,
            "source_mode": self.source_mode,
            "builder": self.builder,
            "template": self.template,
            "backend": self.backend,
            "model": self.model,
            "required_reviews": list(self.required_reviews),
            "verification_dispatch": self.verification_dispatch,
            "lane_status": self.lane_status,
            "lane_note": self.lane_note,
        }

    def plan_hash(self) -> str:
        return S.payload_hash(self.as_payload())

    def as_intent_decision(self) -> intent.RouteDecision:
        """The plan as the intent manifest records it.

        A view of the plan rather than a second decision. The runner used to
        build this by calling `intent.select` itself, which is where the second
        route came from.
        """
        return intent.RouteDecision(
            route=self.route, template=self.template, backend=self.backend,
            condition=self.route_rationale, candidates=self.candidates)


def _builder(*, route: str, matched: str | None, requested: str | None,
             requires_specification: bool) -> tuple[str, str | None]:
    """Which geometry provider this job builds through, and never which route.

    Three cases, in order:

    * a certified template covers the parameters as they stand -- build it,
      whatever the route says about evidence;
    * no template covers them *yet*, but a metrologist is recovering the
      dimensions this job does not own into the named template's bounds. The
      recovered parameters are re-checked against the certified domain before
      anything is built, so the domain is still enforced;
    * otherwise the geometry is authored, which includes every `CUSTOM` job by
      definition.
    """
    if route == "CUSTOM":
        return "AUTHORED", None
    if matched is not None:
        return "CERTIFIED_TEMPLATE", matched
    # Checked against the registry rather than trusted: a project may name a
    # template that no longer exists, and a plan that carried the name anyway
    # would turn a typo into a KeyError out of the CLI instead of a job that
    # stops and says what it is waiting for.
    if requires_specification and requested in T.registry():
        return "CERTIFIED_TEMPLATE", requested
    return "AUTHORED", None


def _backend(builder: str, template: str | None) -> str | None:
    if builder == "AUTHORED":
        return "authored"
    return T.get(template).backend if template in T.registry() else None


def _dispatch(route: str, required_reviews: tuple[str, ...]) -> str:
    if "verification" in required_reviews:
        return "REQUIRED"
    # DIRECT's route trade. Note the order: an explicitly requested verification
    # reaches `required_reviews` above and is honoured on every route, because a
    # trade the pipeline makes on the job's behalf is not a reason to discard
    # something the user asked for out loud.
    return "NEVER" if route == "DIRECT" else "OPTIONAL"


def _lane(*, route: str, source_mode: str, builder: str,
          requires_specification: bool) -> tuple[str, str]:
    if requires_specification and builder != "CERTIFIED_TEMPLATE":
        return "EXPERIMENTAL_UNAVAILABLE", AUTHORED_METROLOGY_NOTE
    if route == "CUSTOM":
        return "EXPERIMENTAL_UNAVAILABLE", CUSTOM_LANE_NOTE
    if source_mode == "MODIFY":
        return "EXPERIMENTAL_UNAVAILABLE", MODIFY_LANE_NOTE
    return "AVAILABLE", ""


def compile_plan(project: P.Project,
                 decision: RT.RouteDecision | None = None) -> ExecutionPlan:
    """The one compilation from canonical project state to executable plan."""
    decision = RT.decide(project) if decision is None else decision
    reviews = RT.required_reviews(project, decision)
    builder, template = _builder(
        route=decision.route, matched=decision.template,
        requested=project.template, requires_specification="specification" in reviews)
    lane_status, lane_note = _lane(
        route=decision.route, source_mode=project.source_mode, builder=builder,
        requires_specification="specification" in reviews)
    return ExecutionPlan(
        job_id=project.job_id, route=decision.route,
        route_rationale=decision.condition, source_mode=project.source_mode,
        builder=builder, template=template, backend=_backend(builder, template),
        model=project.model, required_reviews=reviews,
        verification_dispatch=_dispatch(decision.route, reviews),
        lane_status=lane_status, lane_note=lane_note,
        candidates=decision.candidates)


def from_job_request(*, job_id: str, template: str | None,
                     parameters: dict[str, Any], external_geometry: bool,
                     ambiguities: tuple[str, ...], consequence: str,
                     authored: bool = False) -> ExecutionPlan:
    """The plan for a caller that has a job description and no project.

    `run-job` reads `job.json` directly and the frozen fixtures build a
    `JobRequest` by hand, so neither has canonical project state to compile from.
    They still go through a compiler rather than through a second router: the
    obligations below are the legacy runner's own rules, in one place, where they
    can be compared against the project compiler above instead of drifting from
    it.
    """
    match = intent.select(requested_template=template, parameters=parameters,
                          external_geometry=external_geometry,
                          ambiguities=ambiguities)
    reviews: set[str] = set()
    if consequence == "CONSEQUENTIAL":
        reviews.add("safety")
    if match.route in ("FITTED", "FULL"):
        # Both routes recover geometry the job does not own.
        reviews.add("specification")
    if match.route == "FULL":
        reviews.add("verification")
    required = tuple(sorted(reviews))
    if authored:
        builder, name = "AUTHORED", None
    else:
        builder, name = _builder(route=match.route, matched=match.template,
                                 requested=template,
                                 requires_specification="specification" in required)
    lane_status, lane_note = _lane(route=match.route, source_mode="NEW",
                                   builder=builder,
                                   requires_specification="specification" in required)
    return ExecutionPlan(
        job_id=job_id, route=match.route, route_rationale=match.condition,
        source_mode="NEW", builder=builder, template=name,
        # The matched template's backend, kept rather than re-derived: the intent
        # manifest has always recorded it and a legacy job's receipt must not
        # change shape because the plan moved.
        backend="authored" if authored else match.backend,
        model=None, required_reviews=required,
        verification_dispatch=_dispatch(match.route, required),
        lane_status=lane_status, lane_note=lane_note, candidates=match.candidates)
