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
import sys
import time
from pathlib import Path
from typing import Any, Callable

from . import analysis, commission, contract as C, intent, safety, schemas as S
from . import screening, status, templates as T, witness as W
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


@dataclasses.dataclass
class JobResult:
    ok: bool
    stage: str
    message: str
    artifacts: dict[str, Path]
    timings: dict[str, float]
    llm_calls: int
    final_status: dict[str, Any] | None


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

    if decision.route != "DIRECT":
        return JobResult(False, "routing",
                         f"route is {decision.route}, not DIRECT: {decision.condition}. "
                         "This runner implements the DIRECT vertical slice.",
                         written, timings, llm_calls, None)

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

    # ---- build ------------------------------------------------------------
    mark = time.perf_counter()
    backend = get_backend(model_contract.backend)
    try:
        built = backend.build(model_contract, out)
    except Exception as exc:                        # noqa: BLE001 - a build failure is a
        return JobResult(False, "build", f"{type(exc).__name__}: {exc}",   # receipt, not a crash
                         written, timings, llm_calls, None)
    timings["build"] = time.perf_counter() - mark

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
        "updated_utc": request.updated_utc,
    }

    # ---- one load, then everything reads it -------------------------------
    mark = time.perf_counter()
    ctx = analysis.load(built.stl_path)
    timings["mesh_load"] = time.perf_counter() - mark
    artifact["bbox_mm"] = {k: round(float(ctx.extents[i]), 4) for i, k in enumerate("xyz")}

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
        safety_report = safety.run(packet, request.reviewer or {}, request.safety_call)
        llm_calls += 1
        timings["safety"] = time.perf_counter() - mark
        written["safety_verification_report"] = _write(
            out / "safety_verification_report.json", safety_report)

    final = status.decide(contract=model_contract, commission_report=report,
                          screening=screen, manufacturing=manufacturing,
                          safety=safety_report, artifact=artifact,
                          verification=None, updated_utc=request.updated_utc)
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


def _unused() -> None:  # pragma: no cover
    _ = sys
