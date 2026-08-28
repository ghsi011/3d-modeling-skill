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
# The plan's *filename* is not here. It is `artifact_names.EXECUTION_PLAN`, and
# this module compiles the plan rather than writing it -- a constant here was
# the first of the three spellings one file had.

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
# `OPTIONAL` is a look the route did not oblige but that is worth taking when the
# broad screen came back clear; `REQUIRED` is an obligation the run cannot drop
# because a screen was messy.
#
# `OPTIONAL` used to be a name for behaviour `design-tool run` could not produce.
# The compiler returned it exactly when `verification` was *absent* from
# `required_reviews`, and `cli._review_calls` supplied a verifier exactly when it
# was *present*, so the one setting meant to invite a look was the one setting
# that guaranteed no verifier was in the room. `run-job`, which hands the runner
# all three callables unconditionally, did honour it -- so one `job.json` reached
# `VERIFIED` through `run-job` and `NEEDS_MORE_EVIDENCE` through `run`, with the
# legacy adapter quietly dropping a review its predecessor dispatched.
#
# It is now produced only where it is honoured: on the two routes that recover
# geometry the job does not own and have not already been obliged to verify. It
# is deliberately *not* produced on `CUSTOM` -- buying one designer commission a
# second context it never asked for is the escalation the route decision exists
# to make deliberately, and it would put an agent round trip on a route the
# baseline costs at one.
DISPATCH = ("NEVER", "OPTIONAL", "REQUIRED")

# Whether this lane may claim success at all. Neither cap stops the
# deterministic work: the build, the gates, the screen and the witnesses all run
# and all write their receipts, because a designer has to be able to iterate
# against real measurements. What they stop is the claim -- see `status.decide`.
#
# The two caps are different kinds of thing and are named separately, because a
# reader who cannot tell them apart cannot tell which one waiting will lift.
# `EXPERIMENTAL_UNAVAILABLE` is a stage gate: a named stage of ADR 0002 removes
# it. `UNSUPPORTED` is a capability statement about a combination this build
# cannot execute at all, and no stage on the map lifts it -- it was previously
# spelled `EXPERIMENTAL_UNAVAILABLE` too, which told every reader of an authored
# `FITTED` job's receipt to wait for a stage that was never going to arrive.
LANE_STATUS = ("AVAILABLE", "EXPERIMENTAL_UNAVAILABLE", "UNSUPPORTED")

# Why each lane cannot certify its own result -- the specific failure, not a
# general caveat, and stated once here so the receipt and the CLI say the same
# sentence.
#
# `CUSTOM` no longer has one. Its cap said the lane re-read its acceptance
# criteria out of the model file it was judging; stage 2 moved those criteria
# into `design_proposal.json`, froze them into `acceptance_contract.json` before
# the builder runs, and removed the fields from `AuthoredModel` so nothing can
# read them back. A cap whose stated reason is gone is a caveat nobody can act
# on, and leaving it would train its readers to skip the next one.
MODIFY_LANE_NOTE = (
    "the MODIFY lane's preservation audit no longer samples unseeded: the plan is "
    "derived from the source and candidate hashes, so two runs of one unchanged "
    "pair produce byte-identical evidence and a review answer stays bound across "
    "a rerun. What is still owed is sensitivity, not repeatability -- the sample "
    "density is a fixed count rather than one derived from a declared minimum "
    "detectable defect size, so a small undeclared addition outside the edit "
    "region can still be missed, and is now missed identically on every run. "
    "Until that density is derived, this lane may not report a part COMMISSIONED "
    "or VERIFIED")
AUTHORED_METROLOGY_NOTE = (
    "this job owes a bounded metrology recovery, and recovery is defined only "
    "against a certified template's covers and bounds -- nothing in this build "
    "can recover an externally owned dimension into authored geometry, so the "
    "specification this route requires cannot be produced. This is a limit of "
    "what the build can do and not a stage that is coming: name a certified "
    "template to recover into, or drop the obligation by removing the external "
    "interface or the evidence that made the route FITTED or FULL")


@dataclasses.dataclass(frozen=True)
class ExecutionPlan:
    """What will actually be executed, and what it will be allowed to claim."""

    job_id: str
    route: str
    route_rationale: str
    source_mode: str
    builder: str
    # Why this builder and not the other one. On the receipt because the builder
    # is a choice between two declarations that can both be present, and a choice
    # nobody can read is a choice nobody can dispute.
    builder_rationale: str
    template: str | None
    backend: str | None
    model: str | None
    required_reviews: tuple[str, ...]
    verification_dispatch: str
    # Which supplied artifacts this job must prove survived outside their
    # declared edit regions. Carried on the plan rather than left for whichever
    # CLI path happens to assemble the contract: the audit reached the contract
    # from `_run_authored` only, so an edit scope declared over any other builder
    # was never measured and never mentioned. The runner refuses to build a
    # contract that does not carry a row for each artifact this names.
    #
    # The ids and not a flag. A job may edit two artifacts, and "the contract
    # carries a preservation row" was the same statement as "every declared scope
    # is measured" only while there could be one scope. With two, a contract
    # carrying one row would satisfy a flag and leave the second artifact
    # unmeasured -- which is the defect this obligation was added to stop, one
    # artifact later.
    preserved_artifact_ids: tuple[str, ...]
    lane_status: str
    lane_note: str
    # Audit detail, not identity: the rejected certified templates are recorded
    # in `route_decision.json` and carried here only so the intent manifest can
    # keep naming them. Two plans that execute identically must hash identically
    # even if a sixth certified template is added to the registry.
    candidates: tuple[intent.Candidate, ...] = ()
    # Which formulation of the job this plan executes, or None at the shared root.
    #
    # This is one of exactly two payloads the id joins, and it is here because
    # path isolation alone is provably not sufficient. `as_payload` carries no
    # parameters and deliberately omits `candidates`, so two alternatives of one
    # template with *different numbers* compile to the same plan and therefore to
    # the same `execution_plan_sha256`. A review answered against one would bind
    # against the other on a digest that could not tell them apart. It joins the
    # review envelope for the same reason and no others: it must not reach
    # `contract_sha256`, because two formulations that legitimately require
    # identical geometry share an acceptance contract, and making the contract
    # differ would invent a difference the job does not have.
    alternative_id: str | None = None

    def __post_init__(self) -> None:
        """The two things a plan may not say at once.

        Checked here rather than in a validator a code path can miss. A plan is
        the one authority over what runs, so a plan that states an obligation it
        also declines is not a job that needs a warning -- it is a plan that must
        not exist.

        `UNSUPPORTED` and not merely "anything other than AVAILABLE": this
        combination used to be covered by whichever cap `_lane` happened to
        return first, so it was carried by the `CUSTOM` cap on most jobs and by
        the `MODIFY` cap on the rest. Both of those are stage gates that a later
        commit lifts, and lifting one would silently uncover this. Demanding the
        one status that means "this build cannot execute this combination" makes
        that impossible to do by accident.
        """
        S.require_enum(self.lane_status, LANE_STATUS, what="plan.lane_status")
        if self.requires_specification and not self.dispatches_specification \
                and self.lane_status != "UNSUPPORTED":
            raise ValueError(
                f"plan for {self.job_id!r} requires a specification, builds "
                f"through {self.builder}, and is capped {self.lane_status}: the "
                "bounded recovery is defined only against a certified "
                "template's bounds, so this plan owes a review nothing can run. "
                "That is a capability limit and must be recorded as UNSUPPORTED, "
                "not behind a stage gate somebody is waiting on")

    @property
    def requires_specification(self) -> bool:
        """The obligation, which is not the same as the ability to meet it."""
        return "specification" in self.required_reviews

    @property
    def dispatches_specification(self) -> bool:
        """Whether the bounded recovery this job owes can actually be run.

        One predicate, compiled once and read by the runner and by the CLI's
        review wiring. The runner used to answer this for itself -- `if
        plan.requires_specification and plan.builder == "CERTIFIED_TEMPLATE"` --
        which is the two-authorities shape stage 1 exists to remove: the plan
        stated the obligation, the runner declined it, and only the lane cap kept
        that from becoming a job that claimed success without the review it owed.
        `__post_init__` now makes that combination unrepresentable.
        """
        return self.requires_specification and self.builder == "CERTIFIED_TEMPLATE"

    # There is deliberately no `requires_safety`. The safety gate reads
    # `contract.consequence` instead, and `runner.py` states why: the safety pass
    # is mandatory on a CONSEQUENTIAL job and must not be droppable by a plan
    # that failed to list it. A predicate here would invite exactly the gate that
    # comment forbids, and the property that used to sit at this line was read by
    # nothing.

    @property
    def requires_preservation(self) -> bool:
        """Whether this job owes a preservation audit at all.

        Derived from the artifacts rather than stored beside them. A declared
        edit scope is the obligation, and `MODIFY` is read too so that a project
        which somehow carried the mode without a scope fails closed rather than
        building against nothing.
        """
        return bool(self.preserved_artifact_ids) or self.source_mode == "MODIFY"

    @property
    def requires_verification(self) -> bool:
        return "verification" in self.required_reviews

    def as_payload(self) -> dict[str, Any]:
        """The plan as it is written down and hashed.

        `alternative_id` is omitted when there is none, not spelled `null`. A job
        that has never branched must compile to the plan it compiled to before
        branching existed, byte for byte, or every `execution_plan_sha256` on
        every existing receipt moves for a capability the job does not use.
        """
        payload: dict[str, Any] = {
            "schema_version": EXECUTION_PLAN_SCHEMA,
            "job_id": self.job_id,
            "route": self.route,
            "route_rationale": self.route_rationale,
            "source_mode": self.source_mode,
            "builder": self.builder,
            "builder_rationale": self.builder_rationale,
            "template": self.template,
            "backend": self.backend,
            "model": self.model,
            "required_reviews": list(self.required_reviews),
            "verification_dispatch": self.verification_dispatch,
            "requires_preservation": self.requires_preservation,
            "preserved_artifact_ids": list(self.preserved_artifact_ids),
            "lane_status": self.lane_status,
            "lane_note": self.lane_note,
        }
        if self.alternative_id is not None:
            payload["alternative_id"] = self.alternative_id
        return payload

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
             model: str | None,
             requires_specification: bool) -> tuple[str, str | None, str]:
    """Which geometry provider this job builds through, and never which route.

    Four cases, in order:

    * the project declares an authored model -- that is the geometry, on every
      route. A declaration cannot be outvoted by a match. Preferring a matched
      certified template over a declared `model.py` emitted a plan that
      contradicted itself (`builder: CERTIFIED_TEMPLATE, model: model.py`) and
      then built the template: a `RECONSTRUCT` job declaring both built the
      certified c_clip, reached `VERIFIED`, and named `model.py` in no receipt.
      The asymmetry was the tell -- the same declaration flipped a `NEW` job to
      `CUSTOM` and was dropped in silence on `FITTED` and `FULL`;
    * `CUSTOM` is one designer commission, so it is authored by definition even
      before the model file exists;
    * a certified template covers the parameters as they stand -- build it,
      whatever the route says about evidence;
    * no template covers them *yet*, but a metrologist is recovering the
      dimensions this job does not own into the named template's bounds. The
      recovered parameters are re-checked against the certified domain before
      anything is built, so the domain is still enforced.

    Otherwise the geometry is authored and the commission asks for it.
    """
    if model is not None:
        why = f"the project declares an authored model ({model})"
        if matched is not None:
            why += (f"; the certified template {matched} covers these parameters "
                    "and is not used, because a declared model is a decision and "
                    "a match is only an offer")
        return "AUTHORED", None, why
    if route == "CUSTOM":
        return "AUTHORED", None, ("CUSTOM is one designer commission, so the "
                                  "geometry is authored for this job")
    if matched is not None:
        return "CERTIFIED_TEMPLATE", matched, (
            f"{matched} covers the parameters as they stand")
    # Checked against the registry rather than trusted: a project may name a
    # template that no longer exists, and a plan that carried the name anyway
    # would turn a typo into a KeyError out of the CLI instead of a job that
    # stops and says what it is waiting for.
    if requires_specification and requested in T.registry():
        return "CERTIFIED_TEMPLATE", requested, (
            f"no certified template covers these parameters yet; the bounded "
            f"recovery this route owes measures into {requested}'s bounds")
    return "AUTHORED", None, ("no certified template covers this geometry, so it "
                              "has to be authored")


def _backend(builder: str, template: str | None) -> str | None:
    if builder == "AUTHORED":
        return "authored"
    return T.get(template).backend if template in T.registry() else None


def _dispatch(route: str, required_reviews: tuple[str, ...]) -> str:
    if "verification" in required_reviews:
        return "REQUIRED"
    # Note the order: an explicitly requested verification reaches
    # `required_reviews` above and is honoured on every route, because a trade the
    # pipeline makes on the job's behalf is not a reason to discard something the
    # user asked for out loud.
    #
    # Below it, only the two routes that recover geometry the job does not own
    # invite the optional look -- see `DISPATCH`. `DIRECT` trades it away and
    # `CUSTOM` is one commission that must not grow a second one by side effect.
    return "OPTIONAL" if route in ("FITTED", "FULL") else "NEVER"


def _lane(*, edit_scopes: int, source_mode: str, builder: str,
          requires_specification: bool) -> tuple[str, str]:
    """Which cap this job runs under, keyed on what it declared.

    The modification cap is checked before the `CUSTOM` one, and on the *edit
    scopes* rather than on the literal source mode. Both were defects:

    * keyed on `source_mode == "MODIFY"`, a project that declared an edit scope
      over a source artifact and called itself `RECONSTRUCT` compiled
      `lane_status: AVAILABLE`, took the certified builder and reached
      `VERIFIED` -- with the edit scope and the source artifact read by nothing
      at all. A declared edit scope is the obligation; the source mode is a
      label beside it;
    * `MODIFY_LANE_NOTE` names the preservation audit's own unsettled sampling
      and the `CUSTOM` note did not, so an edit job that also routed `CUSTOM`
      -- which is most of them -- got the note that omits the caveat closest to
      the work.

    `CUSTOM` no longer appears here at all. Its cap existed because the lane read
    its acceptance criteria out of the model file it was judging; the criteria
    now come from a proposal frozen into `acceptance_contract.json` before the
    builder runs, and `AuthoredModel` has no field they could be read back
    through.

    `edit_scopes` is a count and not a flag because a job may declare several --
    a case body and its drawer, edited together. Any one of them carries the
    obligation, so the cap is on the count being non-zero; a cap keyed on the
    first scope would let a second one go unmeasured.
    """
    if requires_specification and builder != "CERTIFIED_TEMPLATE":
        return "UNSUPPORTED", AUTHORED_METROLOGY_NOTE
    if edit_scopes or source_mode == "MODIFY":
        return "EXPERIMENTAL_UNAVAILABLE", MODIFY_LANE_NOTE
    return "AVAILABLE", ""


def compile_plan(project: P.Project,
                 decision: RT.RouteDecision | None = None) -> ExecutionPlan:
    """The one compilation from canonical project state to executable plan."""
    decision = RT.decide(project) if decision is None else decision
    reviews = RT.required_reviews(project, decision)
    builder, template, builder_rationale = _builder(
        route=decision.route, matched=decision.template,
        requested=project.template, model=project.model,
        requires_specification="specification" in reviews)
    # Declaration order, not sorted: the scopes are what the author wrote, and a
    # plan that reordered them would stop matching the project it was compiled
    # from. `Project.validate` refuses a duplicate artifact_id, so these are
    # distinct.
    preserved = tuple(scope.artifact_id for scope in project.edit_scopes)
    lane_status, lane_note = _lane(
        edit_scopes=len(preserved),
        source_mode=project.source_mode, builder=builder,
        requires_specification="specification" in reviews)
    return ExecutionPlan(
        job_id=project.job_id, route=decision.route,
        route_rationale=decision.condition, source_mode=project.source_mode,
        builder=builder, builder_rationale=builder_rationale, template=template,
        backend=_backend(builder, template),
        model=project.model, required_reviews=reviews,
        verification_dispatch=_dispatch(decision.route, reviews),
        preserved_artifact_ids=preserved,
        lane_status=lane_status, lane_note=lane_note,
        candidates=decision.candidates,
        alternative_id=project.active_alternative or None)


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
        builder_rationale = "the caller supplied authored geometry with the request"
    else:
        builder, name, builder_rationale = _builder(
            route=match.route, matched=match.template, requested=template,
            model=None, requires_specification="specification" in required)
    lane_status, lane_note = _lane(edit_scopes=0,
                                   source_mode="NEW", builder=builder,
                                   requires_specification="specification" in required)
    return ExecutionPlan(
        job_id=job_id, route=match.route, route_rationale=match.condition,
        source_mode="NEW", builder=builder, builder_rationale=builder_rationale,
        template=name,
        # The matched template's backend, kept rather than re-derived: the intent
        # manifest has always recorded it and a legacy job's receipt must not
        # change shape because the plan moved.
        backend="authored" if authored else match.backend,
        model=None, required_reviews=required,
        verification_dispatch=_dispatch(match.route, required),
        preserved_artifact_ids=(),
        lane_status=lane_status, lane_note=lane_note, candidates=match.candidates)
