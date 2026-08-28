#!/usr/bin/env python3
"""The fused job: one invocation, one worker, one mesh load.

Measured, the deterministic work of a routine job is seconds and a real run took
minutes. The gap is round trips -- every separate command pays interpreter start
before a shell is even reached. So intake, routing, contract, preflight, build,
export, commissioning, screening, witnesses and status are one call, because
there is no branch between them a caller could usefully take.

It stops at the first failure and hands back that step's own message. A chain
that continues past a broken link writes receipts describing a part that was
never built.
"""
from __future__ import annotations

import dataclasses
import platform
import time
from pathlib import Path
from typing import Any, Callable

from . import analysis, artifact_names as N, bindings as B, cache as K, commission
from . import contract as C, cost as COST
from . import execution as EX
from . import fitted, intent, review as R
from . import safety
from . import schemas as S
from . import screening, status, templates as T, verification, witness as W
from .backends import get as get_backend


@dataclasses.dataclass
class JobRequest:
    job_id: str
    brief_path: Path
    template: str | None
    parameters: dict[str, Any]
    stated: frozenset[str]
    consequence: str
    out_dir: Path
    updated_utc: str
    # These are job-owned manufacturing inputs. They are required here rather
    # than defaulted: the contract must name the machine, process/material,
    # nozzle and transform that the deterministic checks describe.
    printer: str
    material: dict[str, Any]
    nozzle: dict[str, Any]
    orientation: dict[str, Any]
    modifiers: tuple[str, ...] = ()
    # ADR 0003 decision 6, derived by `project.datum_conflicts` and carried
    # rather than recomputed: the runner takes a flattened request and has no
    # `Project` to ask, and a second derivation here could disagree with the
    # one the project already made.
    datum_conflicts: tuple[dict[str, Any], ...] = ()
    external_geometry: bool = False
    ambiguities: tuple[str, ...] = ()
    step: bool = False
    render: bool = True
    safety_call: Callable[[safety.Packet], dict[str, Any]] | None = None
    reviewer: dict[str, Any] | None = None
    # The one bounded call that recovers externally owned geometry, and the
    # evidence it is given. Required exactly when the plan lists `specification`,
    # and absent on a job that owns everything it needs by definition.
    spec_call: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    # The independent verifier, and the only way any route reaches VERIFIED.
    # Whether it is dispatched is `plan.verification_dispatch`: never on DIRECT,
    # whose route trade is that nobody independent looks.
    verify_call: Callable[[verification.Packet], dict[str, Any]] | None = None
    evidence: tuple[str, ...] = ()
    # Where the declared evidence files are read from. `out_dir` when absent,
    # which is every caller that has no alternative: evidence is *shared* job
    # input -- a photo, a caliper sheet -- and it is declared once against the
    # project, not copied into each formulation's directory. Once `out_dir` moves
    # under `alternatives/<id>`, resolving evidence relative to it would look for
    # the shared file in a place nobody put it.
    evidence_dir: Path | None = None
    interface_map: dict[str, str] = dataclasses.field(default_factory=dict)
    # Where build artifacts are reused from. None disables caching entirely,
    # which is the right default for a test: a cache that is on by default makes
    # every test depend on what a previous one left behind.
    cache_dir: Path | None = None
    # The authored builder: geometry is a module the designer wrote rather than a
    # certified template. Which builder to use is the plan's answer, not a
    # property of the route.
    #
    # Two objects, and the split is the point of stage 2. `acceptance` is the
    # frozen `acceptance_contract.json`, generated from the design proposal and
    # written to disk *before* this runner was called; it is what the contract is
    # built from. `authored_build` is an `isolation.BuiltCandidate`: geometry that
    # a one-shot confined process already produced, that this process re-read and
    # re-hashed, and that carries no callable at all. It used to be the loaded
    # model -- one object supplying both the expectations and the solid, which is
    # how a designer could widen an expectation after seeing it missed, and then
    # a live module in this interpreter, which is how import-time code could
    # replace `status.decide`. Neither the criteria nor any executable candidate
    # code reaches this module now.
    acceptance: Any = None
    authored_build: Any = None
    # The compiled plan: the route, the builder, the reviews this job owes and
    # what it is allowed to claim. Supplied by `design-tool run`, which compiles
    # it from `project.json`. A request without one -- `run-job`, the frozen
    # fixtures -- is compiled by the same module from the request itself, so
    # there is still exactly one place a route is decided. This runner must never
    # decide one; two authorities is one authority and one bug.
    plan: EX.ExecutionPlan | None = None
    # Contract features generated from the print plan -- written before the
    # geometry existed, which is the only reason they are a gate rather than a
    # receipt.
    plan_features: tuple[dict[str, Any], ...] = ()
class ReviewNeeded(Exception):
    """A review has no answer on disk yet.

    Raised by the CLI's on-disk review adapter so the runner can stop cleanly
    without its broad safety/spec/verification try/except swallowing the signal.
    """

    def __init__(self, kind: str, packet: Any, path: Path) -> None:
        super().__init__(kind)
        self.kind, self.packet, self.path = kind, packet, path


@dataclasses.dataclass
class JobResult:
    ok: bool
    stage: str
    message: str
    artifacts: dict[str, Path]
    timings: dict[str, float]
    llm_calls: int
    final_status: dict[str, Any] | None


def _repo_root() -> Path:
    """Where to start looking for the toolchain's lockfile.

    A starting point, not an answer: `cache.find_lock` walks up from here for a
    `uv.lock` with a `pyproject.toml` beside it. This used to return
    `parents[4]`, which is this repository's layout and no one else's -- from an
    installed skill it landed two directories above the skill root.
    """
    return Path(__file__).resolve().parent


def _write(out: Path, name: str, payload: dict[str, Any]) -> Path:
    """Write one of the pipeline's own receipts, resolved through the registry.

    The name goes through `artifact_names.path` rather than being joined here,
    so a receipt this process is not the owner of is refused at the write rather
    than discovered afterwards by whoever lost their file. Taking the directory
    and the name instead of a finished path is what makes that unavoidable: the
    thirteen call sites below cannot compose a path that skips the check.
    """
    path = N.path(out, name, owner=N.PIPELINE)
    path.write_text(S.canonical_json(payload), encoding="utf-8")
    return path


def run(request: JobRequest) -> JobResult:
    """One invocation, and the ledger of what it spent.

    A thin wrapper around `_run`, and thin deliberately: the body below returns
    from fifteen places and raises `ReviewNeeded` from three, and an accounting
    line repeated at every one of them is an accounting line that will be
    forgotten at the sixteenth. Everything the ledger needs is filled in as the
    run goes; this is where it is written down, on every exit including the ones
    that produced no claim -- a run that spent two seconds and stopped for a
    review is exactly the failed-and-repeated work ARCHITECTURE.md 15.6 asks to
    be visible, and it is the half a receipt-shaped record cannot hold.

    The budget check is here for the same reason. `budget()` is what the compiled
    plan authorises this invocation to dispatch; a run that went past it did work
    the plan did not name, and the authority gate says runtime execution follows
    the compiled plan. It cannot fire on any path in this build -- the ceiling is
    derived from the same predicates the dispatch sites read -- which is the
    point: it is the guard that makes the next release's accidental round trip
    fail a test instead of quietly costing money.
    """
    ledger = COST.Ledger(job_id=request.job_id)
    try:
        result = _run(request, ledger)
    except ReviewNeeded as need:
        # The invocation that wrote the packet and stopped. Two things are
        # recorded here and neither was recorded anywhere before. Its
        # deterministic work is real and is paid again by the invocation that
        # resumes. And the question it stopped on *is* the dispatch on this
        # path: the packet is on disk, an agent will answer it before the next
        # invocation, and the run that reads that answer back must not be
        # charged for asking it a second time (`cost.Ledger.dispatched`).
        #
        # Guarded, and only on this path. `ReviewNeeded` is a control signal --
        # it is how the CLI is told to write an instruction and stop -- and
        # accounting that could replace it with its own exception would turn
        # "answer this review" into a traceback. On the ordinary return path an
        # accounting failure is allowed to raise, the way `lifecycle.record`
        # does, because there is no signal there for it to destroy.
        try:
            ledger.asked(need.kind)
            COST.append(request.out_dir, ledger,
                        ledger.invocation(ok=False, stage="review-pause"))
        except Exception:                               # noqa: BLE001 - see above
            pass
        raise
    breaches = COST.overruns(ledger.allowed, ledger.spent())
    COST.append(request.out_dir, ledger,
                ledger.invocation(ok=result.ok and not breaches,
                                  stage="cost" if breaches else result.stage,
                                  overruns=breaches))
    if breaches:
        return dataclasses.replace(
            result, ok=False, stage="cost",
            message="\n  - ".join(["this run cost more than its plan budgets:"]
                                  + breaches))
    return result


def _run(request: JobRequest, ledger: COST.Ledger) -> JobResult:
    started = time.perf_counter()
    timings: dict[str, float] = {}
    # By reference: an invocation that stops for a review still reports the
    # stages it did reach, and it reaches them by filling in this dict.
    ledger.seconds = timings
    # The confined child ran before this function was called, so none of its cost
    # is inside `started`. Recorded at the top rather than at the bottom, because
    # an authored job that stops for a review has already paid it and an
    # invocation that reported zero would be the one hiding the biggest number on
    # the lane.
    ledger.boundary_seconds = float(
        getattr(request.authored_build, "boundary_seconds", 0.0) or 0.0)
    out = request.out_dir
    out.mkdir(parents=True, exist_ok=True)
    evidence_root = request.evidence_dir or out
    written: dict[str, Path] = {}
    llm_calls = 0
    specification: dict[str, Any] | None = None
    fit_rows: tuple[dict[str, Any], ...] = ()
    safety_envelope: R.ReviewEnvelope | None = None
    verification_envelope: R.ReviewEnvelope | None = None

    brief_text = request.brief_path.read_text(encoding="utf-8") if request.brief_path.is_file() else ""
    brief_hash = S.sha256_text(brief_text)

    # ---- the compiled plan, consumed verbatim -----------------------------
    mark = time.perf_counter()
    # Compiled upstream over the canonical project, or -- for `run-job` and the
    # frozen fixtures, which hand over a job description and no project -- by the
    # same compiler over this request. Either way the route is decided once and
    # read here. The runner re-deriving it from `intent.select` is what let a
    # FITTED job execute as DIRECT: no metrologist, no verifier, and "DIRECT" on
    # its own final status.
    plan = request.plan or EX.from_job_request(
        job_id=request.job_id, template=request.template,
        parameters=request.parameters, external_geometry=request.external_geometry,
        ambiguities=request.ambiguities, consequence=request.consequence,
        authored=request.acceptance is not None)
    # The plan is the cost authority as well as the route authority: what this
    # invocation may dispatch is derived from it here, once, and checked against
    # what was spent when the run ends.
    ledger.route, ledger.builder = plan.route, plan.builder
    ledger.alternative = plan.alternative_id or COST.ROOT_ALTERNATIVE
    ledger.allowed = COST.budget(plan)
    decision = plan.as_intent_decision()
    manifest = intent.manifest(
        job_id=request.job_id, brief_text=brief_text, brief_hash=brief_hash,
        parameters=request.parameters, stated=request.stated,
        consequence=request.consequence, modifiers=request.modifiers,
        ambiguities=request.ambiguities,
        decision=decision, updated_utc=request.updated_utc)
    written["intent_manifest"] = _write(out, N.INTENT_MANIFEST, manifest)
    timings["intent"] = time.perf_counter() - mark

    if plan.requires_verification and request.verify_call is None:
        return JobResult(False, "routing",
                         f"route is {plan.route}: {plan.route_rationale}. This job "
                         "requires independent verification and no verifier was "
                         "supplied.",
                         written, timings, llm_calls, None)

    if plan.builder == "AUTHORED" and request.acceptance is None:
        return JobResult(False, "routing",
                         f"route is {plan.route}: {plan.route_rationale}. The plan "
                         "builds this job from authored geometry and no frozen "
                         "acceptance contract was supplied, so there is nothing to "
                         "build against.",
                         written, timings, llm_calls, None)
    if request.acceptance is not None:
        # Recorded as a receipt of this run even though this run did not write it.
        # The freeze happened upstream, before the builder existed; naming the
        # file here is what puts it in `JobResult.artifacts` beside the receipts
        # that bind its hash.
        written["acceptance_contract"] = request.acceptance.frozen.path

    # Which certified template the contract is built from, when the plan names
    # one. `request.template` is the fallback for a job that named a template the
    # matcher could not confirm -- an out-of-domain FULL job whose parameters the
    # metrologist is about to recover into that template's bounds.
    built_from = plan.template or request.template

    # The bounded recovery of geometry this job does not own. Gated on one
    # predicate the plan compiled rather than on a route table repeated here: the
    # runner demanding a spec call the compiler had not asked for is what
    # deadlocked a FULL job with two components, no evidence and no external
    # interface -- unresolvable, because no reviewer the agent supplied was ever
    # going to be the one the runner wanted.
    #
    # `dispatches_specification` and not `requires_specification`: the recovery
    # is defined only against a certified template's covers and bounds, so a job
    # that owes one and builds authored geometry has nothing to run it into. That
    # used to be the runner's own judgement -- it read the obligation off the plan
    # and declined it unilaterally, which is the two-authorities shape this stage
    # exists to remove. The compiler owns it now, and a plan that declines a
    # review it owes while claiming an available lane cannot be constructed
    # (`ExecutionPlan.__post_init__`). Stage 2 does not need to revisit this line;
    # it needs to revisit the compiler, in one place.
    if plan.dispatches_specification:
        if request.spec_call is None:
            return JobResult(False, "routing",
                             f"route is {plan.route}: {plan.route_rationale}. This job "
                             "needs one bounded call to recover geometry it does not own, "
                             "and no spec reviewer was supplied.",
                             written, timings, llm_calls, None)
        if built_from is None:
            return JobResult(False, "routing",
                             f"route is {plan.route}: {plan.route_rationale}. No certified "
                             "template was named, so there is nothing to recover "
                             "parameters into.",
                             written, timings, llm_calls, None)
        mark = time.perf_counter()
        template = T.get(built_from)
        # The contract that would be built from the current parameters, before the
        # spec reviewer recovers anything. The spec envelope binds this hash so a
        # response cannot be replayed against a different starting contract.
        pre_contract = _contract_from(template, request)
        try:
            spec = fitted.recover(
                brief=brief_text, evidence=list(request.evidence), template=template.name,
                template_covers=template.covers, bounds=template.bounds,
                call=ledger.watch("spec", request.spec_call),
                reviewer=request.reviewer or {},
                job_id=request.job_id, revision=request.updated_utc,
                contract_hash=pre_contract.contract_hash(),
                evidence_dir=evidence_root,
                artifact_hashes=None, execution_plan_sha256=plan.plan_hash(),
                alternative_id=plan.alternative_id)
        except ReviewNeeded:
            raise
        except (S.SchemaError, R.ReviewError, ValueError) as exc:
            written["specification"] = _write(out, N.SPECIFICATION, {
                "schema_version": S.SPECIFICATION_SCHEMA,
                "route": "FITTED",
                "error": f"{type(exc).__name__}: {exc}",
                "measurements": [], "interfaces": [],
                "unresolved": [str(exc)],
            })
            return JobResult(False, "specification",
                             f"{type(exc).__name__}: {exc}",
                             written, timings, llm_calls, None)
        llm_calls += 1
        ledger.dispatched("spec")
        timings["specification"] = time.perf_counter() - mark
        specification = spec
        written["specification"] = _write(out, N.SPECIFICATION, spec)

        if spec["unresolved"]:
            unresolved = "\n  - ".join(spec["unresolved"])
            return JobResult(False, "specification",
                             f"the specification could not be completed:\n  - {unresolved}\n"
                             "An unrecovered dimension stops the job; a fabricated one "
                             "ships a part that does not fit.",
                             written, timings, llm_calls, None)

        # Every deterministic consequence of the measurement is computed here, so
        # a parameter is a function of a reading anyone can re-check against the
        # object rather than a number that arrived already decided.
        measurements = [fitted.Measurement(**{k: v for k, v in row.items() if k != "band_mm"})
                        for row in spec["measurements"]]
        interfaces = [fitted.Interface(**{k: v for k, v in row.items()
                                          if k not in ("clearance_mm", "clearance_owner",
                                                       "uncertainty_mm", "acceptance_tolerance_mm")})
                      for row in spec["interfaces"]]
        fit_rows = fitted.acceptance_contract(
            measurements, interfaces, request.interface_map
        )
        derived = fitted.parameters_from(measurements, interfaces, request.interface_map)
        request = dataclasses.replace(
            request, parameters={**request.parameters, **derived},
            external_geometry=False)

        # A domain check on the recovered parameters, and nothing else. It asks
        # whether the certified template still covers the job now that the
        # metrologist has supplied the dimensions it does not own -- a question
        # about the builder. It may not touch the route: a FITTED or FULL job is
        # still that route even when the recovered parameters happen to sit
        # inside a certified domain and build through the same code DIRECT does.
        covered = intent.select(requested_template=request.template,
                                parameters=request.parameters,
                                external_geometry=False, ambiguities=())
        if covered.route != "DIRECT":
            return JobResult(False, "routing",
                             "after recovering the specification the derived parameters "
                             f"are outside every certified domain: {covered.condition}",
                             written, timings, llm_calls, None)
        built_from = covered.template or plan.template
        manifest["route_decision"] = {
            **manifest["route_decision"], "recovered_via": plan.route,
        }
        # Rebuilt from the full parameter set, not patched over the old one: a
        # recovered dimension is new, so a comprehension that only updates
        # existing rows drops exactly the values this route exists to produce.
        manifest["requirements"] = [
            {"name": name, "value": value, "unit": "mm",
             "provenance": ("recovered by measurement" if name in derived
                            else ("stated in the brief" if name in request.stated
                                  else "chosen by design")),
             "source": ("metrologist" if name in derived
                        else ("user" if name in request.stated else "designer"))}
            for name, value in sorted(request.parameters.items())]
        manifest["specification"] = {
            "measurements": spec["measurements"], "interfaces": spec["interfaces"]}
        written["intent_manifest"] = _write(out, N.INTENT_MANIFEST, manifest)

    if plan.builder == "AUTHORED":
        template = request.acceptance
    elif built_from is None:
        return JobResult(False, "routing",
                         f"route is {plan.route}: {plan.route_rationale}. The plan "
                         "names a certified builder and no certified template covers "
                         "this geometry, so there is nothing to build.",
                         written, timings, llm_calls, None)
    else:
        template = T.get(built_from)

    # ---- contract ---------------------------------------------------------
    mark = time.perf_counter()
    model_contract = _contract_from(
        template, request,
        fit_acceptance=fit_rows,
    )
    written["model_contract"] = _write(out, N.MODEL_CONTRACT_FILE, model_contract.as_payload())
    problems = C.preflight(model_contract, known_checks=commission.KNOWN_CHECKS)
    # The obligation the plan carries, checked against the contract that will
    # actually be gated. The preservation row reached the contract from one CLI
    # path only, so a project that declared an edit scope over any other builder
    # was measured against nothing, mentioned nothing on its receipts, and could
    # still finish VERIFIED. Refusing here rather than warning: an audit that is
    # absent from the contract cannot reach the commissioning verdict, so there
    # is no later place this could be caught.
    if plan.requires_preservation:
        rows = [feature for feature in model_contract.features
                if feature.kind == "preservation"]
        # One row per declared scope, and at least one either way. Counted rather
        # than matched by id so the runner does not have to know how the CLI
        # spells a feature id -- the preflight already refuses duplicates, so a
        # shortfall is the only way a declared scope can go unmeasured.
        owed = max(1, len(plan.preserved_artifact_ids))
        if len(rows) < owed:
            problems = problems + [
                f"this job declares {owed} edit scope(s) over supplied artifacts, "
                f"so the contract must carry {owed} preservation row(s) measuring "
                f"everything outside each edit region. It carries {len(rows)}, and "
                "a modification whose preservation is unmeasured cannot be "
                "commissioned."]
    timings["contract"] = time.perf_counter() - mark
    if problems:
        return JobResult(False, "preflight",
                         "the contract is not complete enough to build against:\n  - "
                         + "\n  - ".join(problems), written, timings, llm_calls, None)

    # ---- build, or the same bytes from a previous one ---------------------
    mark = time.perf_counter()
    backend = get_backend(model_contract.backend, request.authored_build)
    cache_status, cache_key = "disabled", None
    try:
        built = backend.build(model_contract, out)
    except Exception as exc:                        # noqa: BLE001 - a build failure is a
        return JobResult(False, "build", f"{type(exc).__name__}: {exc}",   # receipt, not a crash
                         written, timings, llm_calls, None)
    timings["build"] = time.perf_counter() - mark
    # Counted here and not at the cache block below, and the order is the whole
    # finding: the geometry has already been built by the time anything looks in
    # the cache, so a hit confirms the bytes rather than saving the work. The
    # ledger records both numbers so that "cache reuse" is a measurement and not
    # a status string a reader has to interpret.
    ledger.builds += 1

    if request.cache_dir is not None:
        cache_key = K.key_for(model_contract, backend_version=built.backend_version,
                              tessellation=built.tessellation, root=_repo_root())
        store = K.Cache(request.cache_dir)
        hit = store.lookup(cache_key)
        if hit is not None:
            # The build already ran -- this is a rebuild whose result matched, and
            # the useful part is the confirmation, not the saving. Caching the
            # build *before* running it would mean trusting the key to be complete;
            # comparing after means a key that misses something shows up as a
            # mismatch here rather than as a stale artifact downstream.
            cached_stl = store._slot(cache_key) / built.stl_path.name
            cache_status = ("hit" if S.sha256_file(cached_stl) == S.sha256_file(built.stl_path)
                            else "hit-mismatch")
        else:
            files = {built.stl_path.name: built.stl_path,
                     built.source_path.name: built.source_path}
            if built.step_path:
                files[built.step_path.name] = built.step_path
            store.store(cache_key, files=files,
                        payloads={"contract": model_contract.as_payload()})
            cache_status = "stored"
    ledger.cache = cache_status

    artifact = {
        "schema_version": S.ARTIFACT_SCHEMA,
        "job_id": request.job_id,
        "contract_sha256": model_contract.contract_hash(),
        "source_sha256": S.sha256_file(built.source_path),
        "stl_sha256": S.sha256_file(built.stl_path),
        "step_sha256": S.sha256_file(built.step_path) if built.step_path else None,
        "backend": built.backend, "backend_version": built.backend_version,
        "python": platform.python_version(),
        "tessellation": built.tessellation,
        "boolean_ops": list(built.boolean_ops),
        "boolean_engine": built.boolean_engine,
        "units": "mm",
        "cache": {"status": cache_status,
                  "key": cache_key.as_dict() if cache_key else None},
        "updated_utc": request.updated_utc,
    }

    # ---- one load, then everything reads it -------------------------------
    # Wrapped as a whole. Only the build used to be, so a mesh the boolean engine
    # refuses -- "Not all meshes are volumes!" -- ended the run in a traceback out
    # of the CLI: no receipt, no final status, and a half-written directory. A
    # part that cannot be measured is a finding, and findings get written down.
    try:
        mark = time.perf_counter()
        ctx = analysis.load(built.stl_path)
        timings["mesh_load"] = time.perf_counter() - mark
        artifact["bbox_mm"] = {k: round(float(ctx.extents[i]), 4)
                               for i, k in enumerate("xyz")}

        mark = time.perf_counter()
        # `evidence_root` and not `out`: a declared source artifact is shared job
        # input, named once against the project. Once the candidate is written
        # under `alternatives/<id>` the two directories differ, and looking for
        # the source beside the candidate would report a file that is exactly
        # where it was declared as missing.
        report = commission.run(ctx, model_contract, evidence_root)
        timings["commission"] = time.perf_counter() - mark

        mark = time.perf_counter()
        screen = screening.run(ctx, model_contract)
        report["screening"] = screen
        timings["screening"] = time.perf_counter() - mark

        mark = time.perf_counter()
        witness = W.generate(ctx, model_contract, out / B.WITNESS_DIR, render=request.render)
        report["witness"] = witness.as_dict()
        timings["witness"] = time.perf_counter() - mark
    except Exception as exc:                        # noqa: BLE001 - see above
        written["artifact_manifest"] = _write(out, N.PIPELINE_RECEIPT, artifact)
        return JobResult(False, "measurement", f"{type(exc).__name__}: {exc}",
                         written, timings, llm_calls, None)

    # Durations live in their own file, deliberately unhashed. Serializing them
    # into the manifest made every artifact byte-unstable, which broke the one
    # property hashing exists for: `evidence_packet_sha256` and the safety
    # cache identity became functions of elapsed time, so no two runs could ever
    # match and the cache could never hit.
    written["artifact_manifest"] = _write(out, N.PIPELINE_RECEIPT, artifact)
    written["commission_report"] = _write(out, N.COMMISSION_REPORT, report)

    # ---- manufacturing evidence -------------------------------------------
    manufacturing = status.manufacturing(model_contract, report)
    if manufacturing is not None:
        written["manufacturing_report"] = _write(out, N.MANUFACTURING_REPORT, manufacturing)

    # ---- the one bounded safety call, when required ------------------------
    # Keyed off the immutable contract rather than off the plan, and deliberately
    # so. Everything else here reads the plan, because the plan is the single
    # route authority; this one review is mandatory on a CONSEQUENTIAL job and
    # must not be droppable by a plan that failed to list it. The compiler cannot
    # disagree -- `route.required_reviews` adds `safety` for exactly this
    # consequence class -- so the two agree, and the one that cannot be edited by
    # a routing change is the one that gates.
    safety_report = None
    if model_contract.consequence == "CONSEQUENTIAL":
        if request.safety_call is None:
            return JobResult(False, "safety",
                             "this job is CONSEQUENTIAL and no safety reviewer was supplied. "
                             "The final safety pass is mandatory; it is not skipped because "
                             "the route is DIRECT or the checks were green.",
                             written, timings, llm_calls, None)
        mark = time.perf_counter()
        packet = safety.build_packet(
            brief=brief_text, intent=manifest, contract=model_contract.as_payload(),
            artifact=artifact, commission=report, manufacturing=manufacturing,
            witness=witness.as_dict())
        # Stage 1 only: `verification_report` is deliberately not in the packet.
        # Showing a second opinion the first one is anchoring by construction.
        # The envelope hashes the evidence and witness files, so it is built
        # inside the boundary: a missing file is a controlled failure with a
        # receipt, not an exception out of the runner.
        try:
            safety_envelope = R.build_envelope(
                kind="safety", job_id=request.job_id, revision=request.updated_utc,
                packet_hash=packet.packet_hash(), reviewer=request.reviewer or {},
                contract_hash=model_contract.contract_hash(),
                artifact_hashes={
                    "contract": artifact["contract_sha256"],
                    "stl": artifact["stl_sha256"],
                    "source": artifact["source_sha256"],
                    "step": artifact.get("step_sha256"),
                },
                witness=witness.as_dict(), witness_dir=out / B.WITNESS_DIR,
                evidence=request.evidence, evidence_dir=evidence_root,
                # The deterministic measurement plans behind the packet's
                # evidence, named rather than only hashed into it. A MODIFY job's
                # preservation audit is the reason this exists: its plan is now a
                # function of the artifact pair, and an answer written against
                # one plan must not survive a run that used another.
                evidence_digests=report.get("evidence_digests"),
                # The plan the run was executed under. `builder`, `source_mode`,
                # `lane_status`, `lane_note` and `preserved_artifact_ids` are
                # decided there and nowhere else the reviewer is shown, and the
                # plan's digest used to reach `final_status.json` alone -- written
                # after this call, so it bound nothing anybody answered.
                execution_plan_sha256=plan.plan_hash(),
                # Which formulation was reviewed. Two siblings agree about every
                # other field in this envelope at the instant one is branched
                # from the other, so without this a PASS written for one is
                # `is_bound` for the other.
                alternative_id=plan.alternative_id)
            safety_report = safety.run(packet, request.reviewer or {},
                                       ledger.watch("safety", request.safety_call),
                                       envelope=safety_envelope)
        except ReviewNeeded:
            raise
        except (S.SchemaError, R.ReviewError, ValueError) as exc:
            # ValueError too, as at the specification boundary: review adapters
            # parse JSON, and a parse failure is a malformed review -- a receipt,
            # not a traceback.
            written["safety_verification_report"] = _write(
                out, N.SAFETY_VERIFICATION_REPORT, {
                    "schema_version": S.SAFETY_SCHEMA,
                    "error": f"{type(exc).__name__}: {exc}",
                })
            return JobResult(False, "safety",
                             f"{type(exc).__name__}: {exc}",
                             written, timings, llm_calls, None)
        llm_calls += 1
        ledger.dispatched("safety")
        timings["safety"] = time.perf_counter() - mark
        written["safety_verification_report"] = _write(
            out, N.SAFETY_VERIFICATION_REPORT, safety_report)

    verification_report = None
    # Whether an independent look happens at all is the plan's answer: NEVER on
    # DIRECT, whose route trade is exactly that nobody independent looks;
    # OPTIONAL, which is worth taking only when the broad screen came back clear;
    # REQUIRED, which survives a screen that could not clear the part.
    #
    # OPTIONAL only ever fired here for `run-job`, which hands over every callable
    # unconditionally. `design-tool run` supplied a verifier exactly when the
    # route *required* one, so the middle value could not be acted on and one
    # `job.json` finished VERIFIED through the old entry point and
    # NEEDS_MORE_EVIDENCE through the new one. `cli._review_calls` now supplies
    # the verifier on OPTIONAL too, which is what closes that gap.
    if request.verify_call is not None and plan.verification_dispatch != "NEVER" and \
            (screen["overall"] == "CLEAR"
             or plan.verification_dispatch == "REQUIRED"):
        mark = time.perf_counter()
        packet = verification.build_packet(
            brief=brief_text, intent=manifest, contract=model_contract.as_payload(),
            artifact=artifact, commission=report, witness=witness.as_dict(),
            specification=specification)
        try:
            # Built inside the boundary for the same reason as the safety
            # envelope above: hashing the evidence can fail, and that failure
            # is a receipt, not a traceback.
            verification_envelope = R.build_envelope(
                kind="verification", job_id=request.job_id, revision=request.updated_utc,
                packet_hash=packet.packet_hash(), reviewer=request.reviewer or {},
                contract_hash=model_contract.contract_hash(),
                artifact_hashes={
                    "contract": artifact["contract_sha256"],
                    "stl": artifact["stl_sha256"],
                    "source": artifact["source_sha256"],
                    "step": artifact.get("step_sha256"),
                },
                witness=witness.as_dict(), witness_dir=out / B.WITNESS_DIR,
                evidence=request.evidence, evidence_dir=evidence_root,
                evidence_digests=report.get("evidence_digests"),
                execution_plan_sha256=plan.plan_hash(),
                alternative_id=plan.alternative_id)
            verification_report = verification.run(
                packet, request.reviewer or {},
                ledger.watch("verification", request.verify_call),
                envelope=verification_envelope)
        except ReviewNeeded:
            raise
        except (S.SchemaError, R.ReviewError, ValueError) as exc:
            # See the safety boundary above: a JSON parse failure from the
            # adapter is a malformed review, written down rather than raised.
            written["verification_report"] = _write(
                out, N.PIPELINE_VERIFICATION_REPORT, {
                    "schema_version": S.VERIFICATION_SCHEMA,
                    "error": f"{type(exc).__name__}: {exc}",
                })
            return JobResult(False, "verification",
                             f"{type(exc).__name__}: {exc}",
                             written, timings, llm_calls, None)
        llm_calls += 1
        ledger.dispatched("verification")
        timings["verification"] = time.perf_counter() - mark
        written["verification_report"] = _write(
            out, N.PIPELINE_VERIFICATION_REPORT, verification_report)

    final = status.decide(contract=model_contract, commission_report=report,
                          screening=screen, manufacturing=manufacturing,
                          safety=safety_report, artifact=artifact,
                          verification=verification_report,
                          updated_utc=request.updated_utc,
                          route=plan.route,
                          execution_plan_sha256=plan.plan_hash(),
                          lane_status=plan.lane_status, lane_note=plan.lane_note,
                          safety_envelope=safety_envelope if model_contract.consequence == "CONSEQUENTIAL" else None,
                          verification_envelope=verification_envelope if request.verify_call is not None else None,
                          datum_conflicts=request.datum_conflicts)
    written["final_status"] = _write(out, N.FINAL_STATUS, final)

    timings["build"] = round(built.build_seconds, 4)
    timings["total"] = time.perf_counter() - started
    if request.authored_build is not None:
        # The candidate was built by a process that ran before this function was
        # called, so none of its cost is inside `started`. Recorded and added
        # rather than left out: it is the dominant term on this lane, and a total
        # that omits it reports a 1.7 s job as a 0.05 s one.
        boundary = float(request.authored_build.boundary_seconds)
        timings["build_boundary"] = round(boundary, 4)
        timings["total"] += boundary
    _write(out, N.TIMINGS,
           {"job_id": request.job_id,
            "seconds": {k: round(v, 4) for k, v in timings.items()},
            "note": "not hashed: durations are not part of any "
                    "artifact's identity"})
    ok = final["final_status"] in ("COMMISSIONED", "VERIFIED")
    return JobResult(ok, "complete", final["allowed_claim"], written, timings,
                     llm_calls, final)


def _contract_from(
    template: T.CertifiedTemplate, request: JobRequest,
    *, fit_acceptance: tuple[dict[str, Any], ...] = (),
) -> C.Contract:
    """Build the immutable contract from the template's own declarations.

    `template` is a certified template or the frozen acceptance contract, which
    present the same surface. What it can never be is the loaded `model.py`:
    `authored.AuthoredModel` has no `expectations`, no `bbox` and no `bodies`, so
    the object the builder came out of does not fit this signature.
    """
    parameters = (request.acceptance.parameters if request.acceptance is not None
                  else dict(request.parameters))
    rows = list(template.expectations(request.parameters))
    # Appended, never merged: a plan row and a model row can name the same
    # feature and mean different things, and the preflight refuses a duplicate id
    # rather than letting one silently win.
    rows += [dict(row) for row in request.plan_features]
    features: list[C.Feature] = []
    for row in rows:
        kind = row["kind"]
        expectation = {k: v for k, v in row.items()
                       if k not in ("feature_id", "kind", "note", "tolerance")}
        if isinstance(row.get("tolerance"), dict):
            # A row that states its own band keeps it. A support ceiling of zero
            # under a defaulted 1 mm2 allowance is not a zero ceiling, and the
            # default was reached by every row that did not name a kind above.
            tolerance = dict(row["tolerance"])
        elif kind in ("section_area", "bed_contact"):
            tolerance = C.area_tolerance(float(row["value_mm2"]))
        elif kind == "through_hole":
            tolerance = C.diameter_tolerance(float(row["d_mm"]))
        else:
            tolerance = {"abs": 1.0}
        features.append(C.Feature(
            feature_id=row["feature_id"], kind=kind,
            provenance=row.get("note", "derived from the certified template's parameters"),
            expectation=expectation, tolerance=tolerance, verified_by=kind,
            on_unrunnable="ESCALATE", mandatory=True))

    if fit_acceptance:
        for row in fit_acceptance:
            interface_id = row.get("interface_id")
            parameter = row.get("parameter")
            matches = [
                feature.feature_id for feature in features
                if feature.expectation.get("fit_parameter") == parameter
            ]
            expectation = {
                **row,
                # The acceptance row is only valid if it is checked against one
                # measurement taken from this built candidate. Never broaden
                # this to every template feature: an unrelated passing feature
                # cannot prove the mapped fit parameter.
                "candidate_feature_id": matches[0] if len(matches) == 1 else None,
            }
            features.append(C.Feature(
                feature_id=f"fit-{interface_id}",
                kind="fit_acceptance",
                provenance="derived from the bounded external measurement and fit band",
                expectation=expectation,
                tolerance={"abs": float(row["acceptance_tolerance_mm"])},
                verified_by="fit_acceptance",
                on_unrunnable="FAIL", mandatory=True))

    return C.Contract(
        job_id=request.job_id, template=template.name,
        template_version=template.version, domain_id=template.domain_id,
        backend=template.backend, parameters=parameters,
        features=tuple(features), expected_bbox_mm=template.bbox(request.parameters),
        bbox_tolerance_mm=0.5, expected_bodies=template.bodies,
        orientation=request.orientation,
        material=request.material,
        nozzle=request.nozzle,
        printer=request.printer,
        modifiers=request.modifiers, minimum_coverage=1.0,
        step_required=bool(request.step), consequence=request.consequence,
        updated_utc=request.updated_utc,
        source=(template.as_source() if hasattr(template, "as_source") else None))

