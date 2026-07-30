#!/usr/bin/env python3
"""`design-tool` — the one agent-facing command surface.

    uv run design-tool init <project> --job-id J --source-mode NEW ...
    uv run design-tool route <project>
    uv run design-tool run <project>
    uv run design-tool status <project>
    uv run design-tool doctor
    uv run design-tool selftest

`run` is resumable on every route. It validates the project, executes every
deterministic stage it can, and when agent judgement is genuinely required it
writes `next_action.json`, stops cleanly, and continues from that state the next
time the identical command is invoked. A finished run deletes the file, because
a stale instruction left on disk says the opposite of the truth to the reader
with the least context.

`run-job` is the deprecated predecessor: it reads `job.json` directly, skips the
canonical project, and is kept so existing job directories keep working.

A job is one invocation because every extra one pays interpreter startup to do
work measured in milliseconds.

**Reviews are answered by re-running, not by this program.** A `CONSEQUENTIAL`
job needs a bounded safety call, a `FITTED` job needs a spec call, and `VERIFIED`
needs independent verification. Those are model calls, and this is a
deterministic program: it cannot make them and must not pretend to. So when the
runner needs one, the CLI writes the evidence packet to `reviews/<kind>_packet.json`
and exits 3 naming the file to answer. Write the response next to it as
`reviews/<kind>_response.json` and run the same command again; the response is
validated against the same schema an in-process caller would be held to.

Until this existed the CLI wired none of the hooks, so `run-job` could complete
exactly one kind of job -- INCONSEQUENTIAL, DIRECT, unverified -- while the
front page advertised the pipeline.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

from . import project as P
from . import review as R
from . import route as RT
from . import runner, schemas as S

JOB_FILE = "job.json"


REVIEW_DIR = "reviews"
NEEDS_REVIEW = 3

# One exit code for "a person or an agent has to do something before this can
# continue", whether that something is a review response or a whole commission.
# A caller scripting the loop needs one condition to test, not two.
NEEDS_ACTION = NEEDS_REVIEW
NEXT_ACTION_FILE = "next_action.json"
NEXT_ACTION_SCHEMA = 1
ROUTE_DECISION_FILE = "route_decision.json"


ReviewNeeded = runner.ReviewNeeded


def _payload_of(packet: Any) -> Any:
    """Packets are dataclasses; a spec call is handed a plain dict."""
    return getattr(packet, "payload", packet)


def _reviewer_of(spec: dict[str, Any]) -> dict[str, Any]:
    """Who answered, by their own account.

    Not defaulted to something flattering: `fresh_context` is a claim only the
    caller can make, and this program has no way to check it. Absent means
    absent, and the receipt records that rather than `true`.
    """
    return dict(spec.get("reviewer") or {})


def _answer(job_dir: Path, kind: str):
    """A call that reads its answer from disk, or asks for one and stops."""
    def call(packet: Any) -> dict[str, Any]:
        room = job_dir / REVIEW_DIR
        room.mkdir(parents=True, exist_ok=True)
        # Always write the current request packet first. If a stale response from
        # a previous run is already on disk, the runner will reject it, but the
        # user must be able to answer the current envelope.
        request = room / f"{kind}_packet.json"
        request.write_text(S.canonical_json(_payload_of(packet)), encoding="utf-8")
        response = room / f"{kind}_response.json"
        if response.is_file():
            try:
                return json.loads(response.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                # An unreadable answer is a malformed review, not a crash: the
                # runner boundary turns this into a blocked job with a receipt.
                raise R.ReviewError(
                    f"{response.name} is not valid JSON: {exc}") from exc
        raise ReviewNeeded(kind, packet, response)
    return call


def _load_job(job_dir: Path) -> dict[str, Any]:
    path = job_dir / JOB_FILE
    if not path.is_file():
        raise SystemExit(f"design-tool: no {JOB_FILE} in {job_dir}")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise SystemExit(
            f"design-tool: {JOB_FILE} in {job_dir} is not valid UTF-8: {exc}") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        # A malformed job.json is the contract's own parse failure, not a bug in
        # the tool. Surface the decoder's line and column instead of letting a
        # JSONDecodeError traceback out of the CLI -- a traceback reads as a crash
        # and hides the one thing the author needs: where the JSON is broken.
        raise SystemExit(
            f"design-tool: {JOB_FILE} in {job_dir} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(
            f"design-tool: {JOB_FILE} in {job_dir} must contain a JSON object, "
            f"not {type(payload).__name__}")
    return payload


def _required(spec: dict[str, Any], key: str) -> Any:
    if key not in spec:
        raise SystemExit(
            f"design-tool: {JOB_FILE} is missing {key!r}; the pipeline does not invent it")
    return spec[key]


def _string(value: Any, path: str, *, non_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise S.SchemaError(f"{path} must be a string")
    if non_empty and not value.strip():
        raise S.SchemaError(f"{path} must be a non-empty string")
    return value


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise S.SchemaError(f"{path} must be an object")
    return value


def _number(value: Any, path: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise S.SchemaError(f"{path} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        suffix = " positive" if positive else " finite"
        raise S.SchemaError(f"{path} must be a{suffix} number")
    return result


def _strings(value: Any, path: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise S.SchemaError(f"{path} must be a list of strings")
    return tuple(value)


def _validate_orientation(value: Any) -> dict[str, Any]:
    orientation = _object(value, "orientation")
    if "model_to_printer_matrix" not in orientation:
        raise S.SchemaError("orientation.model_to_printer_matrix is required")
    matrix = orientation["model_to_printer_matrix"]
    if matrix != "identity":
        if (not isinstance(matrix, list) or len(matrix) != 4
                or any(not isinstance(row, list) or len(row) != 4 for row in matrix)):
            raise S.SchemaError(
                "orientation.model_to_printer_matrix must be 'identity' or a 4x4 numeric matrix")
        for row_index, row in enumerate(matrix):
            for column_index, item in enumerate(row):
                _number(item, f"orientation.model_to_printer_matrix[{row_index}][{column_index}]")
    if "bed_z_mm" not in orientation:
        raise S.SchemaError("orientation.bed_z_mm is required")
    _number(orientation["bed_z_mm"], "orientation.bed_z_mm")
    return orientation


def _validate_job_contract(spec: dict[str, Any]) -> None:
    """Validate JSON shapes before any runner code can turn them into a traceback."""
    _string(_required(spec, "job_id"), "job_id", non_empty=True)
    parameters = _object(_required(spec, "parameters"), "parameters")
    for key, value in parameters.items():
        if not isinstance(key, str):
            raise S.SchemaError("parameters keys must be strings")
        _number(value, f"parameters.{key}")
    _string(_required(spec, "updated_utc"), "updated_utc", non_empty=True)
    S.require_enum(_required(spec, "consequence"), S.CONSEQUENCE, what="job.consequence")
    S.require_enum(spec.get("candidate_strategy", "SINGLE"), S.CANDIDATE_STRATEGY,
                   what="job.candidate_strategy")

    _string(_required(spec, "printer"), "printer", non_empty=True)
    material = _object(_required(spec, "material"), "material")
    _string(material.get("process"), "material.process", non_empty=True)
    _string(material.get("material"), "material.material", non_empty=True)
    nozzle = _object(_required(spec, "nozzle"), "nozzle")
    if "diameter_mm" not in nozzle:
        raise S.SchemaError("nozzle.diameter_mm is required")
    _number(nozzle["diameter_mm"], "nozzle.diameter_mm", positive=True)
    _validate_orientation(_required(spec, "orientation"))

    optional_strings = ("brief", "template", "cache_dir")
    for key in optional_strings:
        if key in spec and spec[key] is not None:
            _string(spec[key], key, non_empty=True)
    for key in ("stated", "modifiers", "ambiguities", "evidence"):
        if key in spec:
            _strings(spec[key], key)
    for key in ("external_geometry", "step"):
        if key in spec and not isinstance(spec[key], bool):
            raise S.SchemaError(f"{key} must be a boolean")
    if "reviewer" in spec and spec["reviewer"] is not None:
        _object(spec["reviewer"], "reviewer")
    if "interface_map" in spec and spec["interface_map"] is not None:
        interface_map = _object(spec["interface_map"], "interface_map")
        if any(not isinstance(key, str) or not isinstance(value, str)
               for key, value in interface_map.items()):
            raise S.SchemaError("interface_map must map strings to strings")


def _request(job_dir: Path, spec: dict[str, Any], *, render: bool) -> runner.JobRequest:
    _validate_job_contract(spec)
    return runner.JobRequest(
        job_id=_required(spec, "job_id"),
        brief_path=job_dir / spec.get("brief", "brief.md"),
        template=spec.get("template"),
        parameters=_required(spec, "parameters"),
        stated=frozenset(spec.get("stated", ())),
        consequence=S.require_enum(_required(spec, "consequence"),
                                   S.CONSEQUENCE, what="job.consequence"),
        out_dir=job_dir,
        updated_utc=_required(spec, "updated_utc"),
        modifiers=tuple(spec.get("modifiers", ())),
        candidate_strategy=spec.get("candidate_strategy", "SINGLE"),
        external_geometry=bool(spec.get("external_geometry", False)),
        ambiguities=tuple(spec.get("ambiguities", ())),
        step=bool(spec.get("step", False)),
        render=render,
        safety_call=_answer(job_dir, "safety"),
        spec_call=_answer(job_dir, "spec"),
        verify_call=_answer(job_dir, "verification"),
        reviewer=_reviewer_of(spec),
        evidence=tuple(spec.get("evidence", ())),
        interface_map=dict(spec.get("interface_map") or {}),
        cache_dir=(job_dir / spec["cache_dir"]) if spec.get("cache_dir") else None,
        printer=_required(spec, "printer"),
        material=_required(spec, "material"),
        nozzle=_required(spec, "nozzle"),
        orientation=_required(spec, "orientation"),
    )


def _review_needed_message(need: ReviewNeeded, job_dir: Path) -> None:
    rel = need.path.relative_to(job_dir)
    packet = rel.with_name(need.kind + "_packet.json")
    sys.stderr.write(
        f"\ndesign-tool: this job needs a {need.kind} review before it can finish.\n"
        f"  the evidence is written to  {packet}\n"
        f"  write the answer to         {rel}\n"
        "  then run the same command again.\n\n"
        "  This program cannot answer it. A review is a judgement about a part,\n"
        "  and a deterministic tool that returned one would be inventing it.\n")


def _report_artifacts(result: runner.JobResult) -> None:
    for name, path in sorted(result.artifacts.items()):
        sys.stderr.write(f"  {name:28s} {path.name}\n")
    timings = "  ".join(f"{k} {v:.2f}s" for k, v in result.timings.items())
    sys.stderr.write(f"\n  {timings}\n  llm calls: {result.llm_calls}\n")


def run_job(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="design-tool run-job")
    parser.add_argument("job_dir", type=Path)
    parser.add_argument("--no-render", action="store_true",
                        help="skip the witness images -- and with them the only evidence "
                             "that is not conditioned on a declaration")
    args = parser.parse_args(argv)

    job_dir = args.job_dir.resolve()
    spec = _load_job(job_dir)
    try:
        request = _request(job_dir, spec, render=not args.no_render)
    except (S.SchemaError, KeyError, TypeError, ValueError) as exc:
        # Contract-shaped inputs (the consequence class, and anything else parsed
        # through the schema helpers) are validated as the job is turned into a
        # request. A bad value is the contract failing to parse: name the field
        # and the value it rejected rather than tracebacking out of the CLI.
        raise SystemExit(
            f"design-tool: {JOB_FILE} in {job_dir} is not a valid contract: {exc}") from exc
    try:
        result = runner.run(request)
    except ReviewNeeded as need:
        _review_needed_message(need, job_dir)
        return NEEDS_REVIEW

    _report_artifacts(result)

    if not result.ok:
        sys.stderr.write(f"\ndesign-tool: {result.stage}: {result.message}\n")
        return 1
    sys.stderr.write(f"\n  {result.final_status['final_status']}: {result.message}\n")
    return 0


# ---------------------------------------------------------------------------
# The canonical project surface
# ---------------------------------------------------------------------------

def _write_next_action(project_dir: Path, payload: dict[str, Any]) -> Path:
    path = project_dir / NEXT_ACTION_FILE
    path.write_text(S.canonical_json(payload), encoding="utf-8")
    return path


def _clear_next_action(project_dir: Path) -> None:
    """A finished run must not leave a stale instruction behind.

    `next_action.json` is read as "this is what the job is waiting for". Left on
    disk after the thing was done, it says the opposite of the truth, and the
    reader with the least context is the one most likely to believe it.
    """
    path = project_dir / NEXT_ACTION_FILE
    if path.is_file():
        path.unlink()


def _load_project(project_dir: Path, *, adapt: bool = True) -> P.Project:
    """The project, adapting a legacy `job.json` in place when that is all there is."""
    try:
        return P.load(project_dir)
    except FileNotFoundError:
        pass
    if not adapt:
        raise SystemExit(
            f"design-tool: no {P.PROJECT_FILE} in {project_dir}. "
            f"Run `design-tool init {project_dir}` to write one.")
    job = project_dir / JOB_FILE
    if not job.is_file():
        raise SystemExit(
            f"design-tool: no {P.PROJECT_FILE} and no {JOB_FILE} in {project_dir}. "
            f"Run `design-tool init {project_dir}` to write one.")
    project = P.from_job_json(_load_job(project_dir))
    project.save(project_dir)
    sys.stderr.write(
        f"design-tool: adapted {JOB_FILE} into {P.PROJECT_FILE} "
        "(compat: job.json@1 -- it keeps routing under the legacy rules)\n")
    return project


def _report_problems(project_dir: Path, project: P.Project,
                     problems: list[str], *, stage: str) -> int:
    _write_next_action(project_dir, {
        "schema_version": NEXT_ACTION_SCHEMA,
        "job_id": project.job_id,
        "kind": "FIX_PROJECT",
        "stage": stage,
        "reason": "the project does not describe a job that can be routed",
        "unresolved": list(problems),
        "completion_command": f"design-tool run {project_dir.as_posix()}",
        "updated_utc": project.updated_utc,
    })
    sys.stderr.write(f"design-tool: {P.PROJECT_FILE} is not complete enough to "
                     f"{stage}:\n")
    for problem in problems:
        sys.stderr.write(f"  - {problem}\n")
    return 2


def init(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="design-tool init",
        description="Write a project.json skeleton. Nothing is invented: every "
                    "field you must supply is present and empty, and the command "
                    "prints them as a to-do list.")
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--source-mode", required=True, choices=P.SOURCE_MODE,
                        help="NEW creates geometry from requirements; MODIFY starts "
                             "from a supplied artifact; RECONSTRUCT recovers it from "
                             "evidence")
    parser.add_argument("--consequence", required=True, choices=S.CONSEQUENCE)
    parser.add_argument("--updated-utc", required=True,
                        help="ISO-8601, passed in and never wall-clock, so a rerun "
                             "on unchanged inputs is byte-identical")
    parser.add_argument("--from-job-json", action="store_true",
                        help="derive the project from an existing job.json in the "
                             "same directory")
    parser.add_argument("--force", action="store_true",
                        help="overwrite an existing project.json")
    args = parser.parse_args(argv)

    project_dir = args.project_dir.resolve()
    project_dir.mkdir(parents=True, exist_ok=True)
    existing = project_dir / P.PROJECT_FILE
    if existing.is_file() and not args.force:
        sys.stderr.write(f"design-tool: {existing} already exists; pass --force to "
                         "overwrite it\n")
        return 2

    if args.from_job_json:
        project = P.from_job_json(_load_job(project_dir))
        project.job_id = args.job_id
        project.updated_utc = args.updated_utc
    else:
        project = P.skeleton(job_id=args.job_id, source_mode=args.source_mode,
                             consequence=args.consequence,
                             updated_utc=args.updated_utc)
    path = project.save(project_dir)
    problems = project.validate(project_dir, require_buildable=False)
    sys.stderr.write(f"  wrote {path.name}\n")
    if problems:
        sys.stderr.write("\n  still to supply:\n")
        for problem in problems:
            sys.stderr.write(f"  - {problem}\n")
    return 0


def route(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="design-tool route",
        description="Decide the route, record it and the rationale, and say which "
                    "routes were not taken and why.")
    parser.add_argument("project_dir", type=Path)
    args = parser.parse_args(argv)

    project_dir = args.project_dir.resolve()
    project = _load_project(project_dir)
    problems = project.validate(project_dir, require_buildable=False)
    if problems:
        return _report_problems(project_dir, project, problems, stage="route")

    decision = RT.decide(project)
    RT.apply(project, decision)
    project.save(project_dir)
    (project_dir / ROUTE_DECISION_FILE).write_text(
        S.canonical_json(decision.as_dict()), encoding="utf-8")

    sys.stderr.write(f"\n  route      {decision.route}\n"
                     f"  because    {decision.condition}\n"
                     f"  source     {decision.source_mode}\n")
    if project.required_reviews:
        sys.stderr.write(f"  reviews    {', '.join(project.required_reviews)}\n")
    for reason in decision.escalations:
        sys.stderr.write(f"    - {reason}\n")
    return 0


PLAN_FILE = "print_plan_checks.json"

def _review_calls(project_dir: Path, project: P.Project) -> dict[str, Any]:
    """Only the reviews the route decision actually named.

    Supplying a callback the route did not ask for is not harmless: the runner
    dispatches an independent verification whenever one is available and the
    screen is clear, so an unconditional verifier turned every `CUSTOM` job into
    one that requires a fresh context -- which is exactly the escalation the
    route decision exists to make deliberately.
    """
    required = set(project.required_reviews)
    return {
        "safety_call": _answer(project_dir, "safety") if "safety" in required else None,
        "spec_call": (_answer(project_dir, "spec")
                      if "specification" in required else None),
        "verify_call": (_answer(project_dir, "verification")
                        if "verification" in required else None),
    }




def _print_plan(project_dir: Path, project: P.Project) -> tuple[dict[str, Any], list[str]]:
    """The plan a `CUSTOM` candidate is gated against, written before it exists.

    Generated rather than dispatched, and generated *here* rather than by the
    designer. Across four archived runs with no plan bound, every designer set
    its own support ceiling after reading its own measurement -- which is a
    receipt, not a gate. This template is a legitimate plan for exactly the
    reason a shipped one is: it depends on the printer and the declared envelope
    and on nothing about the geometry being judged.

    Regenerated on every run from the same inputs, so it is byte-stable, and
    refused if it does not validate -- an unbuildable plan discovered after a
    build is 39 archived minutes of nothing.
    """
    from designer_toolkit.plan import direct_template, validate_plan

    envelope = project.envelope_mm
    plan = direct_template(
        (envelope["x"], envelope["y"], envelope["z"]),
        job_id=project.job_id,
        nozzle_mm=float(project.nozzle["diameter_mm"]),
        material=str(project.material["material"]),
        bodies=max(1, sum(c.count for c in project.components) or 1),
        updated_utc=project.updated_utc,
        consequence=project.consequence)
    problems = validate_plan(plan)
    if not problems:
        (project_dir / PLAN_FILE).write_text(S.canonical_json(plan), encoding="utf-8")
    return plan, problems


def _plan_features(plan: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """The plan's support rules, as contract features the gate already measures.

    One rule, not the whole plan: the support ceiling is what decides whether a
    novel part prints at all, and it is the rule the archived runs violated. The
    rest of the plan (edges, interfaces, coupons) is measured by
    `designer_toolkit.commission` and is not duplicated here.
    """
    rows: list[dict[str, Any]] = []
    for index, rule in enumerate(plan.get("support_rules") or []):
        if rule.get("disposition") != "SELF_SUPPORT_REQUIRED":
            # SUPPORT_ALLOWED rules name where support may touch, which is a
            # contact-class question this check does not answer. Skipped rather
            # than approximated: a rule measured by the wrong instrument reports
            # a number about something else.
            continue
        rows.append({
            "feature_id": f"plan-support-{index:02d}",
            "kind": "overhang",
            "max_area_mm2": float(rule.get("max_out_of_limit_area_mm2", 0.0)),
            "downward_normal_z_max": float(
                rule.get("downward_normal_z_max", -0.73)),
            "bed_z_mm": float(rule.get("bed_z_mm", 0.0)),
            # Zero allowance on top of a zero ceiling. The plan's own number is
            # the band; adding a default one here would widen a threshold the
            # plan set deliberately.
            "tolerance": {"abs": 0.0},
            "note": f"print plan rule {rule.get('id', index)}: "
                    f"{rule.get('disposition')}",
        })
    return tuple(rows)


def _run_custom(project_dir: Path, project: P.Project, decision: RT.RouteDecision,
                *, render: bool) -> int:
    """The `CUSTOM` lane: a print plan, then the authored model, then the gate."""
    from . import authored as A
    from . import commission as CM

    if project.envelope_mm is None:
        return _report_problems(project_dir, project, [
            "envelope_mm is required on a CUSTOM job: the print plan is written "
            "before the geometry, and it cannot be written without the envelope "
            "the part is allowed to occupy. Declare it as a stated or chosen "
            "requirement."], stage="run")

    plan, plan_problems = _print_plan(project_dir, project)
    if plan_problems:
        return _report_problems(project_dir, project, plan_problems, stage="plan")

    model_path = project_dir / (project.model or "model.py")
    if not model_path.is_file():
        _write_next_action(project_dir, {
            "schema_version": NEXT_ACTION_SCHEMA,
            "job_id": project.job_id,
            "kind": "AGENT_COMMISSION",
            "role": "designer",
            "stage": "candidate_build",
            "route": decision.route,
            "reason": decision.condition,
            "authorized_inputs": [project.brief, P.PROJECT_FILE,
                                  ROUTE_DECISION_FILE, PLAN_FILE]
            + [a.path for a in project.source_artifacts],
            "required_outputs": [model_path.name],
            "source_api": {
                "PARAMS": "the numbers the shape is built from",
                "BBOX_MM": "x/y/z the solid must measure, derived from PARAMS "
                           "without going through the builder",
                "BODIES": "how many separate solids the export should contain",
                "EXPECTED": "feature rows the gate measures; kinds: "
                            + ", ".join(sorted(CM.KNOWN_CHECKS)),
                "build()": "returns the solid, or a module-level `part`",
            },
            "bound": {"project_sha256": project.project_hash(),
                      "print_plan_sha256": S.payload_hash(plan),
                      "source_artifacts": {a.artifact_id: a.sha256
                                           for a in project.source_artifacts}},
            "unresolved": list(project.blocking_questions),
            "required_reviews": list(project.required_reviews),
            "completion_command": f"design-tool run {project_dir.as_posix()}",
            "updated_utc": project.updated_utc,
        })
        sys.stderr.write(
            f"\ndesign-tool: this job routes {decision.route} and has no model yet.\n"
            f"  the commission is written to  {NEXT_ACTION_FILE}\n"
            f"  the print plan it builds against is  {PLAN_FILE}\n"
            f"  write the model to            {model_path.name}\n"
            "  then run the same command again.\n\n"
            "  This program cannot author geometry, and a deterministic tool that\n"
            "  returned some would be inventing it.\n")
        return NEEDS_ACTION

    try:
        model, builder = A.load(model_path, known_kinds=CM.KNOWN_CHECKS)
    except A.ModelError as exc:
        return _report_problems(project_dir, project, [str(exc)], stage="build")

    fields = P.to_job_request_fields(project)
    fields["template"] = None
    request = runner.JobRequest(
        brief_path=project_dir / project.brief,
        out_dir=project_dir,
        render=render,
        authored=model,
        authored_builder=builder,
        route=decision.route,
        route_condition=decision.condition,
        require_verification=decision.requires_verification,
        plan_features=_plan_features(plan),
        cache_dir=(project_dir / project.cache_dir) if project.cache_dir else None,
        **_review_calls(project_dir, project),
        **fields)
    return _finish(project_dir, project, decision, request)


def _run_project(project_dir: Path, project: P.Project, decision: RT.RouteDecision,
                 *, render: bool) -> int:
    """Every deterministic stage this route can execute right now."""
    if decision.route == "CUSTOM":
        return _run_custom(project_dir, project, decision, render=render)
    if project.template is None:
        # The certified-template runner is the only build lane wired today; the
        # authored-geometry lane arrives in Phase 2. Stopping here with a written
        # commission is the honest state: the job is routed, its reviews are
        # known, and what it is waiting for is a designer.
        _write_next_action(project_dir, {
            "schema_version": NEXT_ACTION_SCHEMA,
            "job_id": project.job_id,
            "kind": "AGENT_COMMISSION",
            "role": "designer",
            "stage": "candidate_build",
            "route": decision.route,
            "reason": decision.condition,
            "authorized_inputs": [project.brief, P.PROJECT_FILE, ROUTE_DECISION_FILE]
            + [a.path for a in project.source_artifacts],
            "required_outputs": ["model.py"],
            "bound": {"project_sha256": project.project_hash(),
                      "source_artifacts": {a.artifact_id: a.sha256
                                           for a in project.source_artifacts}},
            "unresolved": list(project.blocking_questions),
            "required_reviews": list(project.required_reviews),
            "completion_command": f"design-tool run {project_dir.as_posix()}",
            "updated_utc": project.updated_utc,
        })
        sys.stderr.write(
            f"\ndesign-tool: this job routes {decision.route} and has no model yet.\n"
            f"  the commission is written to  {NEXT_ACTION_FILE}\n"
            f"  write the model to            model.py\n"
            "  then run the same command again.\n\n"
            "  This program cannot author geometry, and a deterministic tool that\n"
            "  returned some would be inventing it.\n")
        return NEEDS_ACTION

    fields = P.to_job_request_fields(project)
    request = runner.JobRequest(
        brief_path=project_dir / project.brief,
        out_dir=project_dir,
        render=render,
        route=decision.route,
        route_condition=decision.condition,
        require_verification=decision.requires_verification,
        cache_dir=(project_dir / project.cache_dir) if project.cache_dir else None,
        **_review_calls(project_dir, project),
        **fields)
    return _finish(project_dir, project, decision, request)


def _finish(project_dir: Path, project: P.Project, decision: RT.RouteDecision,
            request: runner.JobRequest) -> int:
    """Run, then turn whatever came back into a state the next run can resume."""
    try:
        result = runner.run(request)
    except ReviewNeeded as need:
        rel = need.path.relative_to(project_dir)
        _write_next_action(project_dir, {
            "schema_version": NEXT_ACTION_SCHEMA,
            "job_id": project.job_id,
            "kind": "REVIEW",
            "review_kind": need.kind,
            "stage": f"review:{need.kind}",
            "route": decision.route,
            "reason": f"this job needs a {need.kind} review before it can finish",
            "evidence": str(rel.with_name(need.kind + "_packet.json")).replace("\\", "/"),
            "respond_with": str(rel).replace("\\", "/"),
            "completion_command": f"design-tool run {project_dir.as_posix()}",
            "updated_utc": project.updated_utc,
        })
        _review_needed_message(need, project_dir)
        return NEEDS_ACTION

    _report_artifacts(result)
    project.status = {**project.status,
                      "stage": result.stage,
                      "final_status": (result.final_status or {}).get("final_status"),
                      "allowed_claim": (result.final_status or {}).get("allowed_claim")}
    project.bindings = {**project.bindings,
                        **(result.final_status or {}).get("artifact_hashes", {})}
    project.save(project_dir)
    final = (result.final_status or {}).get("final_status")
    if not result.ok:
        # Rewrite rather than leave: the previous instruction may have been
        # "answer the safety review", and it has been answered. Left on disk
        # after the answer was refused, it points the next reader at work already
        # done instead of at the reason it was refused.
        #
        # `NEEDS_MORE_EVIDENCE` is separated from `FAILED` deliberately. One says
        # the part does not match its contract; the other says a question went
        # unasked. They call for different work, and collapsing both into exit 1
        # made the second read as a rejection of the geometry.
        needs_evidence = final == "NEEDS_MORE_EVIDENCE"
        _write_next_action(project_dir, {
            "schema_version": NEXT_ACTION_SCHEMA,
            "job_id": project.job_id,
            "kind": "NEEDS_EVIDENCE" if needs_evidence else "BLOCKED",
            "stage": result.stage,
            "route": decision.route,
            "reason": result.message,
            "unresolved": list((result.final_status or {}).get("reasons")
                               or [result.message]),
            "completion_command": f"design-tool run {project_dir.as_posix()}",
            "updated_utc": project.updated_utc,
        })
        sys.stderr.write(f"\ndesign-tool: {result.stage}: {result.message}\n")
        return NEEDS_ACTION if needs_evidence else 1
    _clear_next_action(project_dir)
    sys.stderr.write(f"\n  {final}: {result.message}\n")
    return 0


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="design-tool run",
        description="Validate, route, execute every deterministic stage available, "
                    "and stop cleanly with next_action.json when agent judgement is "
                    "required. Re-run the identical command to continue.")
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("--no-render", action="store_true",
                        help="skip the witness images -- and with them the only "
                             "evidence that is not conditioned on a declaration")
    args = parser.parse_args(argv)

    project_dir = args.project_dir.resolve()
    project = _load_project(project_dir)
    problems = project.validate(project_dir, require_buildable=False)
    if problems:
        return _report_problems(project_dir, project, problems, stage="run")

    decision = RT.decide(project)
    previous = project.route
    RT.apply(project, decision)
    if previous is not None and previous != decision.route:
        project.status = {**project.status, "route_changed_from": previous}
        sys.stderr.write(f"design-tool: the route moved {previous} -> "
                         f"{decision.route}: {decision.condition}\n")
    project.save(project_dir)
    (project_dir / ROUTE_DECISION_FILE).write_text(
        S.canonical_json(decision.as_dict()), encoding="utf-8")

    return _run_project(project_dir, project, decision, render=not args.no_render)


def status(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="design-tool status",
        description="Route, bindings, what the job is waiting for, and the claim it "
                    "is currently allowed to make.")
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    project_dir = args.project_dir.resolve()
    project = _load_project(project_dir, adapt=False)
    pending = project_dir / NEXT_ACTION_FILE
    next_action = None
    if pending.is_file():
        try:
            next_action = json.loads(pending.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"design-tool: {NEXT_ACTION_FILE} is not valid JSON: {exc}")

    final = project_dir / "final_status.json"
    final_payload = (json.loads(final.read_text(encoding="utf-8"))
                     if final.is_file() else None)
    report = {
        "job_id": project.job_id,
        "source_mode": project.source_mode,
        "consequence": project.consequence,
        "route": project.route,
        "route_rationale": project.route_rationale,
        "required_reviews": list(project.required_reviews),
        "problems": project.validate(project_dir, require_buildable=False),
        "waiting_for": next_action,
        "final_status": (final_payload or {}).get("final_status"),
        "allowed_claim": (final_payload or {}).get("allowed_claim"),
        "bindings": project.bindings,
    }
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"  job          {report['job_id']}")
        print(f"  source mode  {report['source_mode']}")
        print(f"  consequence  {report['consequence']}")
        print(f"  route        {report['route'] or '(not decided)'}")
        if report["route_rationale"]:
            print(f"  because      {report['route_rationale']}")
        if report["required_reviews"]:
            print(f"  reviews      {', '.join(report['required_reviews'])}")
        if report["final_status"]:
            print(f"  status       {report['final_status']}")
            print(f"  claim        {report['allowed_claim']}")
        if next_action:
            print(f"  waiting for  {next_action.get('kind')} "
                  f"({next_action.get('stage')})")
            print(f"               {next_action.get('reason', '')}")
        for problem in report["problems"]:
            print(f"  problem      {problem}")

    if report["final_status"] == "FAILED":
        return 1
    if next_action is not None:
        return NEEDS_ACTION
    return 0


def doctor(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="design-tool doctor")
    parser.parse_args(argv)
    import importlib.metadata as md

    print(f"uv run --project <skill> --frozen python {sys.version.split()[0]}")
    for name in ("trimesh", "manifold3d", "build123d", "numpy", "pillow"):
        try:
            print(f"  [yes] {name:12s} {md.version(name)}")
        except md.PackageNotFoundError:
            print(f"  [NO ] {name:12s} required on the core path")
    return 0


def selftest(argv: list[str]) -> int:
    from . import selftest as _selftest
    return _selftest.main(argv)


# The single documented interface. `run-job` is kept as a deprecated alias so
# existing job directories keep working; everything else routes through the
# canonical project.
COMMANDS = {
    "doctor": doctor,
    "selftest": selftest,
    "init": init,
    "route": route,
    "run": run,
    "status": status,
    "run-job": run_job,
}

DEPRECATED = {
    "run-job": "design-tool run <project> (run-job still works; it reads job.json "
               "directly and skips the canonical project)",
}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        print("commands: " + ", ".join(COMMANDS))
        return 0
    command, rest = argv[0], argv[1:]
    handler = COMMANDS.get(command)
    if handler is None:
        sys.stderr.write(
            f"design-tool: unknown command {command!r}; have {', '.join(COMMANDS)}\n")
        return 2
    if command in DEPRECATED:
        sys.stderr.write(f"design-tool: {command} is deprecated -- use "
                         f"{DEPRECATED[command]}\n")
    return handler(rest)


if __name__ == "__main__":
    raise SystemExit(main())
