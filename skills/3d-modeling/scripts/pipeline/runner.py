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

from . import analysis, cache as K, commission, contract as C, fitted, intent, safety
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
    modifiers: tuple[str, ...] = ()
    candidate_strategy: str = "SINGLE"
    external_geometry: bool = False
    ambiguities: tuple[str, ...] = ()
    step: bool = False
    render: bool = True
    safety_call: Callable[[safety.Packet], dict[str, Any]] | None = None
    reviewer: dict[str, Any] | None = None
    # FITTED only: the one bounded call that recovers externally owned geometry,
    # and the evidence it is given. Absent on a DIRECT job, which owns everything
    # it needs by definition.
    spec_call: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    # The independent verifier. Optional on DIRECT -- the route's whole trade is
    # that nobody independent looks, and its status says so. Required for FULL,
    # and the only way any route reaches VERIFIED.
    verify_call: Callable[[verification.Packet], dict[str, Any]] | None = None
    evidence: tuple[str, ...] = ()
    interface_map: dict[str, str] = dataclasses.field(default_factory=dict)
    # Where build artifacts are reused from. None disables caching entirely,
    # which is the right default for a test: a cache that is on by default makes
    # every test depend on what a previous one left behind.
    cache_dir: Path | None = None


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
    """Where `uv.lock` lives, for the toolchain half of the cache key."""
    return Path(__file__).resolve().parents[4]


def _write(path: Path, payload: dict[str, Any]) -> Path:
    path.write_text(S.canonical_json(payload), encoding="utf-8")
    return path


def run(request: JobRequest) -> JobResult:
    started = time.perf_counter()
    timings: dict[str, float] = {}
    out = request.out_dir
    out.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    llm_calls = 0
    specification: dict[str, Any] | None = None

    brief_text = request.brief_path.read_text(encoding="utf-8") if request.brief_path.is_file() else ""
    brief_hash = S.sha256_text(brief_text)

    # ---- intent + routing -------------------------------------------------
    mark = time.perf_counter()
    decision = intent.select(requested_template=request.template,
                             parameters=request.parameters,
                             external_geometry=request.external_geometry,
                             ambiguities=request.ambiguities)
    manifest = intent.manifest(
        job_id=request.job_id, brief_text=brief_text, brief_hash=brief_hash,
        parameters=request.parameters, stated=request.stated,
        consequence=request.consequence, modifiers=request.modifiers,
        candidate_strategy=request.candidate_strategy, ambiguities=request.ambiguities,
        decision=decision, updated_utc=request.updated_utc)
    written["intent_manifest"] = _write(out / "intent_manifest.json", manifest)
    timings["intent"] = time.perf_counter() - mark

    if decision.route == "FULL" and request.verify_call is None:
        return JobResult(False, "routing",
                         f"route is FULL: {decision.condition}. FULL requires independent "
                         "verification and no verifier was supplied.",
                         written, timings, llm_calls, None)

    if decision.route in ("FITTED", "FULL"):
        if request.spec_call is None and decision.route == "FITTED":
            return JobResult(False, "routing",
                             f"route is FITTED: {decision.condition}. This job needs one "
                             "bounded call to recover geometry it does not own, and no "
                             "spec reviewer was supplied.",
                             written, timings, llm_calls, None)
        mark = time.perf_counter()
        template = T.get(decision.template or request.template)
        spec = fitted.recover(
            brief=brief_text, evidence=list(request.evidence), template=template.name,
            template_covers=template.covers, bounds=template.bounds,
            call=request.spec_call, reviewer=request.reviewer or {})
        llm_calls += 1
        timings["specification"] = time.perf_counter() - mark
        specification = spec
        written["specification"] = _write(out / "specification.json", spec)

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
                                          if k not in ("clearance_mm", "clearance_owner")})
                      for row in spec["interfaces"]]
        derived = fitted.parameters_from(measurements, interfaces, request.interface_map)
        request = dataclasses.replace(
            request, parameters={**request.parameters, **derived},
            external_geometry=False)

        recovered = decision.route
        decision = intent.select(requested_template=request.template,
                                 parameters=request.parameters,
                                 external_geometry=False, ambiguities=())
        if decision.route != "DIRECT":
            return JobResult(False, "routing",
                             "after recovering the specification the derived parameters "
                             f"still do not route DIRECT: {decision.condition}",
                             written, timings, llm_calls, None)
        manifest["route_decision"] = {**decision.as_dict(), "recovered_via": recovered}
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
        written["intent_manifest"] = _write(out / "intent_manifest.json", manifest)

    template = T.get(decision.template)

    # ---- contract ---------------------------------------------------------
    mark = time.perf_counter()
    model_contract = _contract_from(template, request)
    written["model_contract"] = _write(out / "model_contract.json", model_contract.as_payload())
    problems = C.preflight(model_contract, known_checks=commission.KNOWN_CHECKS)
    timings["contract"] = time.perf_counter() - mark
    if problems:
        return JobResult(False, "preflight",
                         "the contract is not complete enough to build against:\n  - "
                         + "\n  - ".join(problems), written, timings, llm_calls, None)

    # ---- build, or the same bytes from a previous one ---------------------
    mark = time.perf_counter()
    backend = get_backend(model_contract.backend)
    cache_status, cache_key = "disabled", None
    try:
        built = backend.build(model_contract, out)
    except Exception as exc:                        # noqa: BLE001 - a build failure is a
        return JobResult(False, "build", f"{type(exc).__name__}: {exc}",   # receipt, not a crash
                         written, timings, llm_calls, None)
    timings["build"] = time.perf_counter() - mark

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
        "boolean_engine": "manifold3d" if built.backend == "trimesh-manifold" else "n/a (B-rep)",
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
        report = commission.run(ctx, model_contract)
        timings["commission"] = time.perf_counter() - mark

        mark = time.perf_counter()
        screen = screening.run(ctx, model_contract)
        report["screening"] = screen
        timings["screening"] = time.perf_counter() - mark

        mark = time.perf_counter()
        witness = W.generate(ctx, model_contract, out / "witness", render=request.render)
        report["witness"] = witness.as_dict()
        timings["witness"] = time.perf_counter() - mark
    except Exception as exc:                        # noqa: BLE001 - see above
        written["artifact_manifest"] = _write(out / "artifact_manifest.json", artifact)
        return JobResult(False, "measurement", f"{type(exc).__name__}: {exc}",
                         written, timings, llm_calls, None)

    # Durations live in their own file, deliberately unhashed. Serializing them
    # into the manifest made every artifact byte-unstable, which broke the one
    # property hashing exists for: `evidence_packet_sha256` and the safety
    # cache identity became functions of elapsed time, so no two runs could ever
    # match and the cache could never hit.
    written["artifact_manifest"] = _write(out / "artifact_manifest.json", artifact)
    written["commission_report"] = _write(out / "commission_report.json", report)

    # ---- manufacturing evidence -------------------------------------------
    manufacturing = status.manufacturing(model_contract, report)
    if manufacturing is not None:
        written["manufacturing_report"] = _write(out / "manufacturing_report.json", manufacturing)

    # ---- the one bounded safety call, when required ------------------------
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
        safety_report = safety.run(packet, request.reviewer or {}, request.safety_call)
        llm_calls += 1
        timings["safety"] = time.perf_counter() - mark
        written["safety_verification_report"] = _write(
            out / "safety_verification_report.json", safety_report)

    verification_report = None
    if request.verify_call is not None:
        mark = time.perf_counter()
        packet = verification.build_packet(
            brief=brief_text, intent=manifest, contract=model_contract.as_payload(),
            artifact=artifact, commission=report, witness=witness.as_dict(),
            specification=specification)
        verification_report = verification.run(packet, request.reviewer or {},
                                               request.verify_call)
        llm_calls += 1
        timings["verification"] = time.perf_counter() - mark
        written["verification_report"] = _write(
            out / "verification_report.json", verification_report)

    final = status.decide(contract=model_contract, commission_report=report,
                          screening=screen, manufacturing=manufacturing,
                          safety=safety_report, artifact=artifact,
                          verification=verification_report,
                          updated_utc=request.updated_utc,
                          route=manifest["route_decision"]["route"])
    written["final_status"] = _write(out / "final_status.json", final)

    timings["build"] = round(built.build_seconds, 4)
    timings["total"] = time.perf_counter() - started
    _write(out / "timings.json", {"job_id": request.job_id,
                                  "seconds": {k: round(v, 4) for k, v in timings.items()},
                                  "note": "not hashed: durations are not part of any "
                                          "artifact's identity"})
    ok = final["final_status"] in ("COMMISSIONED", "VERIFIED")
    return JobResult(ok, "complete", final["allowed_claim"], written, timings,
                     llm_calls, final)


def _contract_from(template: T.CertifiedTemplate, request: JobRequest) -> C.Contract:
    """Build the immutable contract from the template's own declarations."""
    rows = template.expectations(request.parameters)
    features: list[C.Feature] = []
    for row in rows:
        kind = row["kind"]
        expectation = {k: v for k, v in row.items()
                       if k not in ("feature_id", "kind", "note")}
        if kind in ("section_area", "bed_contact"):
            tolerance = commission.area_tolerance(float(row["value_mm2"]))
        elif kind == "through_hole":
            tolerance = commission.diameter_tolerance(float(row["d_mm"]))
        else:
            tolerance = {"abs": 1.0}
        features.append(C.Feature(
            feature_id=row["feature_id"], kind=kind,
            provenance=row.get("note", "derived from the certified template's parameters"),
            expectation=expectation, tolerance=tolerance, verified_by=kind,
            on_unrunnable="ESCALATE", mandatory=True))

    return C.Contract(
        job_id=request.job_id, template=template.name,
        template_version=template.version, domain_id=template.domain_id,
        backend=template.backend, parameters=dict(request.parameters),
        features=tuple(features), expected_bbox_mm=template.bbox(request.parameters),
        bbox_tolerance_mm=0.5, expected_bodies=template.bodies,
        orientation={"model_to_printer_matrix": "identity", "bed_z_mm": 0.0},
        material={"process": "FDM", "material": "PLA"},
        modifiers=request.modifiers, minimum_coverage=1.0,
        step_required=bool(request.step), consequence=request.consequence,
        updated_utc=request.updated_utc)

