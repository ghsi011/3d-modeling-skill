#!/usr/bin/env python3
"""`design-tool` — the one agent-facing command surface.

    uv run design-tool init <project> --job-id J --source-mode NEW ...
    uv run design-tool route <project>
    uv run design-tool run <project>
    uv run design-tool status <project>
    uv run design-tool diagnose <artifact>
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

from . import acceptance as ACC
from . import execution as EX
from . import isolation as ISO
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
# The compiled plan, written beside the decision it was compiled from. Nobody
# authors this file: `route` and `run` produce it from `project.json` in the same
# invocation, deterministically and without a dispatch. It is here to be read --
# by the next run, by a reviewer, and by anyone checking that the receipt names
# the plan that was actually executed.
EXECUTION_PLAN_FILE = EX.EXECUTION_PLAN_FILE


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


def _compile(project_dir: Path, project: P.Project,
             decision: RT.RouteDecision) -> EX.ExecutionPlan:
    """Compile the plan and write both receipts.

    Two files, one authority. `route_decision.json` is why this route and not the
    others -- the audit trail of a decision. `execution_plan.json` is what will
    be executed under it, and it is the only one the runner reads.
    """
    plan = EX.compile_plan(project, decision)
    (project_dir / ROUTE_DECISION_FILE).write_text(
        S.canonical_json(decision.as_dict()), encoding="utf-8")
    (project_dir / EXECUTION_PLAN_FILE).write_text(
        S.canonical_json(plan.as_payload()), encoding="utf-8")
    return plan


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
    plan = _compile(project_dir, project, decision)
    project.save(project_dir)

    sys.stderr.write(f"\n  route      {decision.route}\n"
                     f"  because    {decision.condition}\n"
                     f"  source     {decision.source_mode}\n"
                     f"  builder    {plan.builder}"
                     f"{f' ({plan.template})' if plan.template else ''}\n"
                     f"             {plan.builder_rationale}\n")
    if project.required_reviews:
        sys.stderr.write(f"  reviews    {', '.join(project.required_reviews)}\n")
    for reason in decision.escalations:
        sys.stderr.write(f"    - {reason}\n")
    if plan.lane_status != "AVAILABLE":
        sys.stderr.write(f"  lane       {plan.lane_status}: {plan.lane_note}\n")
    return 0


PLAN_FILE = "print_plan_checks.json"

def _review_calls(project_dir: Path, plan: EX.ExecutionPlan) -> dict[str, Any]:
    """Only the reviews the plan actually named.

    Supplying a callback the route did not ask for is not harmless: the runner
    dispatches an independent verification whenever one is available and the
    screen is clear, so an unconditional verifier turned every `CUSTOM` job into
    one that requires a fresh context -- which is exactly the escalation the
    route decision exists to make deliberately.

    Read off the same plan the runner reads. When this list and the runner's
    expectation came from two different derivations, a `FULL` job could be handed
    no spec reviewer by one and refused for the missing spec reviewer by the
    other, with nothing the agent could supply to break the tie.

    The spec reviewer is wired on `dispatches_specification`, not on the bare
    obligation. A job that owes a bounded recovery it cannot run -- authored
    geometry, which has no certified bounds to recover into -- would otherwise be
    handed a reviewer, write a packet asking an agent to answer, and have the
    answer read by nothing.
    """
    required = set(plan.required_reviews)
    return {
        "safety_call": _answer(project_dir, "safety") if "safety" in required else None,
        "spec_call": (_answer(project_dir, "spec")
                      if plan.dispatches_specification else None),
        # `!= "NEVER"`, not `"verification" in required`. Those two conditions
        # were exact complements: the compiler said OPTIONAL precisely when the
        # review was absent from the list this used to read, so the one setting
        # meant to invite an independent look was the one setting that guaranteed
        # nobody was there to take it. `run-job` passes every callable
        # unconditionally and did take it, so the same `job.json` finished
        # VERIFIED through the deprecated entry point and NEEDS_MORE_EVIDENCE
        # through the supported one.
        #
        # This does not hand a verifier to a route that traded one away: OPTIONAL
        # is compiled only for FITTED and FULL, and DIRECT and CUSTOM both reach
        # NEVER.
        "verify_call": (_answer(project_dir, "verification")
                        if plan.verification_dispatch != "NEVER" else None),
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


def _inherited_overhang(project_dir: Path, project: P.Project,
                        rule: dict[str, Any]) -> tuple[float, str] | None:
    """How much unsupported area the supplied artifact already had.

    A `MODIFY` job did not choose the geometry it inherited, so a zero-support
    ceiling generated from the printer would fail it for overhangs that were
    there before anybody touched the file -- and the designer cannot chamfer them
    away without redrawing the part, which is the one thing a modification must
    not do.

    So the ceiling for a modification is the source artifact's own measurement.
    That is not a threshold tuned to the candidate: it is measured on a file that
    was fixed before the job started, and any overhang the *edit* adds still
    fails. Where it cannot be measured, the generated zero stands, because
    widening a limit on a guess is the failure this whole arrangement avoids.

    A job may modify more than one artifact, and then the ceiling is the sum of
    what each of them already had -- the candidate carries all of them, so the
    downward-facing area it inherits is all of theirs. One unmeasurable artifact
    drops the whole allowance back to the generated zero rather than crediting
    the part with only the artifacts that happened to read: a partial sum is a
    ceiling nobody measured.
    """
    if not project.edit_scopes or project.source_mode != "MODIFY":
        return None

    measured: list[tuple[str, float]] = []
    for scope in project.edit_scopes:
        artifact = project.artifact(scope.artifact_id)
        if artifact is None:
            return None
        try:
            source = S.resolve_within(project_dir, artifact.path,
                                      what="edit source")
            if not source.is_file():
                return None
            from designer_toolkit import metrics as M
            area = float(M.overhang_area(
                str(source),
                threshold=float(rule.get("downward_normal_z_max", -0.73)),
                bed_z=float(rule.get("bed_z_mm", 0.0))))
        except Exception:                             # noqa: BLE001 - an
            return None                               # unmeasurable source keeps
                                                      # the generated zero
        measured.append((artifact.path, area))

    total = sum(area for _, area in measured)
    if len(measured) == 1:
        path, area = measured[0]
        return area, (f"inherited from {path}, measured before the edit: "
                      f"{area:.3f} mm2 of the supplied artifact already faces "
                      "downward. The edit may not add to it.")
    detail = ", ".join(f"{path} {area:.3f} mm2" for path, area in measured)
    return total, (f"inherited from {len(measured)} supplied artifacts, measured "
                   f"before the edit: {total:.3f} mm2 already faces downward "
                   f"({detail}). The edit may not add to it.")


def _plan_features(plan: dict[str, Any], *, project_dir: Path | None = None,
                   project: P.Project | None = None) -> tuple[dict[str, Any], ...]:
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
        ceiling = float(rule.get("max_out_of_limit_area_mm2", 0.0))
        note = (f"print plan rule {rule.get('id', index)}: "
                f"{rule.get('disposition')}")
        inherited = (_inherited_overhang(project_dir, project, rule)
                     if project_dir is not None and project is not None else None)
        if inherited is not None:
            ceiling, why = inherited
            note = f"{note}; {why}"
        rows.append({
            "feature_id": f"plan-support-{index:02d}",
            "kind": "overhang",
            "max_area_mm2": ceiling,
            "downward_normal_z_max": float(
                rule.get("downward_normal_z_max", -0.73)),
            "bed_z_mm": float(rule.get("bed_z_mm", 0.0)),
            # Zero allowance on top of the ceiling. The plan's own number is the
            # band; adding a default one here would widen a threshold the plan
            # set deliberately.
            "tolerance": {"abs": 0.0},
            "note": note,
        })
    return tuple(rows)


def _preservation_feature(project: P.Project) -> tuple[dict[str, Any], ...]:
    """One contract row per declared edit scope, measuring outside its region.

    A contract feature rather than a report written afterwards, so it reaches the
    same commissioning verdict and the same status decision as every other
    expectation. A preservation audit that could only be read in its own JSON
    would be a receipt: nothing downstream would refuse a job for failing it.

    Wired into every builder, not just the authored one. It reached the contract
    from `_run_authored` alone, so a project that declared an edit scope over a
    source artifact and matched a certified template built the template, never
    opened the artifact, named neither on any receipt, and finished `VERIFIED`.
    The plan names the artifacts that owe a row now, and `runner.run` refuses a
    contract carrying fewer rows than that, so a builder added later cannot drop
    one by omission.

    Every row names its artifact -- `preservation-<artifact_id>` -- rather than
    the first one taking the bare id. A job may modify two artifacts, the
    preflight refuses a duplicate feature id, and an id whose spelling depended
    on how many scopes there happened to be is one no receipt reader could
    predict.

    The row carries every field of the scope. It used to carry four -- the
    artifact id in the feature id, the region name in the note, `region_box` and
    `preservation_tolerance_mm`, with `mesh_fallback_allowed` folded into `exact`
    -- so a job could change what it promised about the edit (what must survive,
    what may go, what is being added, how many bodies should result, whether the
    source's metadata must, which interface the edit realizes, where the source
    sits in the job's frame) without moving the contract hash, and keep the review
    answer somebody wrote against the previous promise. Everything here reaches
    the frozen acceptance revision and therefore `contract_sha256` in the review
    envelope.
    """
    rows: list[dict[str, Any]] = []
    for scope in project.edit_scopes:
        artifact = project.artifact(scope.artifact_id)
        if artifact is None:
            continue
        exact = (artifact.classification == "USABLE_EXACT"
                 and not scope.mesh_fallback_allowed)
        note = f"everything outside {scope.region!r} must survive the edit"
        if len(project.edit_scopes) > 1:
            # Said on the row rather than left for the reader to discover from a
            # CHANGED verdict. `preservation.audit` compares one source against
            # one candidate in both directions, and the second direction samples
            # the whole candidate: where the candidate carries the other edited
            # artifact too, that artifact's surface is far from this row's source
            # and the comparison reports it as movement. The declaration is
            # right; the instrument is not yet built for it.
            note += (f" ({len(project.edit_scopes)} artifacts are edited together "
                     "and the audit compares one source against the whole "
                     "candidate, so a coordinated multi-artifact edit is declared "
                     "here but not yet measurable by it)")
        rows.append({
            "feature_id": f"preservation-{scope.artifact_id}",
            "kind": "preservation",
            "source": artifact.path,
            "region": scope.region_box,
            "tolerance_mm": scope.preservation_tolerance_mm,
            "exact": exact,
            # The rest of the declared edit intent, not only the fields the
            # measurement happens to consume. Everything here reaches the frozen
            # acceptance contract, so it reaches `contract_sha256`, so it reaches
            # the review envelope: a job that changes what it claims to be doing
            # can no longer keep the answer somebody wrote against the previous
            # claim. Only `alignment_transform` goes on to the sampling seed --
            # see `preservation._seed_material`. The other six say what the edit
            # promised, not where the geometry is, so they must not move the plan
            # digest of a measurement they cannot change.
            "alignment_transform": scope.canonical_alignment_transform(),
            "preserve": list(scope.preserve),
            "may_remove": list(scope.may_remove),
            "add": list(scope.add),
            "expected_body_delta": int(scope.expected_body_delta),
            "preserve_metadata": bool(scope.preserve_metadata),
            "interface_ids": list(scope.interface_ids),
            # `abs: 0.0` on top of the row's own tolerance_mm: the band lives in
            # the comparison, and a second one here would widen it.
            "tolerance": {"abs": 0.0},
            "note": note,
        })
    return tuple(rows)


def _requirement_hash(project: P.Project, brief_hash: str) -> str:
    """What the user asked for, hashed, so the contract binds to it.

    The designer's own `CHOSEN` values are deliberately out: they are the
    proposal, and the proposal is already bound by its own hash. What this pins
    is the half of the job that nobody on the design side owns -- the brief, the
    values somebody stated or measured, the envelope, the interfaces and the
    component list. A contract that survived a change to any of those would be
    gating a part against a job that no longer exists.
    """
    return S.payload_hash({
        "brief_sha256": brief_hash,
        "requirements": [r.as_dict() for r in project.requirements
                         if r.provenance in ("STATED", "INHERITED", "MEASURED")],
        "envelope_mm": project.envelope_mm,
        "interfaces": [i.as_dict() for i in project.interfaces],
        "components": [c.as_dict() for c in project.components],
        "modifiers": list(project.modifiers),
    })


def _source_artifact_hashes(project_dir: Path, project: P.Project) -> dict[str, str]:
    """The supplied artifacts as they stand, hashed before anything is built."""
    hashes: dict[str, str] = {}
    for artifact in project.source_artifacts:
        try:
            path = S.resolve_within(project_dir, artifact.path,
                                    what="source artifact")
        except S.PathEscape:
            continue
        if path.is_file():
            hashes[artifact.artifact_id] = S.sha256_file(path)
        elif artifact.sha256:
            hashes[artifact.artifact_id] = str(artifact.sha256)
    return hashes


PROPOSAL_API = {
    "design_id": "a short stable name for what is being proposed",
    "params": "the numbers the shape is built from; model.py declares the same "
              "PARAMS and must agree with them",
    "bbox_mm": "x/y/z the solid must measure, derived from params by arithmetic "
               "that does not go through the builder",
    "bodies": "how many separate solids the export should contain",
    "profile_marks": "{'z': [...]} -- the heights this shape legitimately steps "
                     "at. They explain a step; they cannot clear the part",
    "features": "rows the gate measures. Geometry only -- position and size. "
                "Proposable kinds: " + ", ".join(sorted(ACC.PROPOSABLE))
                + ". A row may not carry a tolerance: the band is the "
                  "pipeline's and is computed from the row's own magnitude",
}


def _commission_authored(project_dir: Path, project: P.Project,
                         plan: EX.ExecutionPlan, print_plan: dict[str, Any],
                         missing: list[str]) -> int:
    """One designer commission, for the proposal and the model together.

    One, not two. Freeze-proposal-then-build is a deterministic pipeline step and
    must not become a second dispatch: asking the designer to come back and
    confirm a contract generated from their own proposal would buy nothing and
    cost the round trip the `CUSTOM` route exists to avoid.
    """
    _write_next_action(project_dir, {
        "schema_version": NEXT_ACTION_SCHEMA,
        "job_id": project.job_id,
        "kind": "AGENT_COMMISSION",
        "role": "designer",
        "stage": "candidate_build",
        "route": plan.route,
        "reason": plan.route_rationale,
        "authorized_inputs": [project.brief, P.PROJECT_FILE,
                              ROUTE_DECISION_FILE, EXECUTION_PLAN_FILE,
                              PLAN_FILE]
        + [a.path for a in project.source_artifacts],
        "required_outputs": missing,
        "proposal_api": dict(PROPOSAL_API),
        "source_api": {
            "PARAMS": "the numbers the shape is built from",
            "build()": "returns the solid, or a module-level `part`",
            "not here": "EXPECTED, BBOX_MM, BODIES, PROFILE_MARKS, VOLUME_MM3 and "
                        "any acceptance tolerance. They belong to "
                        + ACC.PROPOSAL_FILE + ", which is frozen into "
                        + ACC.ACCEPTANCE_FILE + " before this file is executed",
        },
        "bound": {"project_sha256": project.project_hash(),
                  "execution_plan_sha256": plan.plan_hash(),
                  "print_plan_sha256": S.payload_hash(print_plan),
                  "source_artifacts": {a.artifact_id: a.sha256
                                       for a in project.source_artifacts}},
        "unresolved": list(project.blocking_questions),
        "required_reviews": list(plan.required_reviews),
        "completion_command": f"design-tool run {project_dir.as_posix()}",
        "updated_utc": project.updated_utc,
    })
    sys.stderr.write(
        f"\ndesign-tool: this job routes {plan.route} and is missing "
        f"{', '.join(missing)}.\n"
        f"  the commission is written to  {NEXT_ACTION_FILE}\n"
        f"  the print plan it builds against is  {PLAN_FILE}\n"
        f"  write both files, in one pass, then run the same command again.\n\n"
        f"  {ACC.PROPOSAL_FILE} is what the part must measure; the model is how it\n"
        "  is built. They are separated so that the second cannot restate the\n"
        "  first after seeing a result.\n\n"
        "  This program cannot author geometry, and a deterministic tool that\n"
        "  returned some would be inventing it.\n")
    return NEEDS_ACTION


def _run_authored(project_dir: Path, project: P.Project, plan: EX.ExecutionPlan,
                  *, render: bool) -> int:
    """The authored builder: freeze the acceptance contract, then build elsewhere.

    The ordering is the whole of stage 2. The proposal is validated and frozen,
    the acceptance contract is generated from it and the system-owned inputs and
    written to disk, and only then is `model.py` executed. Nothing downstream of
    the freeze can reach back into it: `acceptance.freeze` takes a proposal, a
    project and a plan and has no parameter a mesh could arrive through, and
    `runner.py` contains no function that writes an acceptance contract at all.

    Ordering was not enough on its own. This function used to import the model
    *here*, which runs its module-level code in the interpreter that holds the
    frozen contract, the commissioning bands and `status.decide` -- and all three
    were reachable and were demonstrably rewritten, to a `VERIFIED` receipt on a
    352 mm2 miss with the on-disk contract still at revision 1. The build now
    happens in a one-shot confined process (`isolation.build`), which is handed a
    sealed directory of copied sources and a scratch directory and nothing about
    acceptance -- not even where the project is; this
    interpreter re-reads and re-hashes what came back and does the assessing.

    Selected by the plan's builder and not by its route. Reaching this lane only
    from `CUSTOM` is what stranded a `FITTED` or `FULL` job whose geometry a
    designer had already written: the run rewrote the same commission every time,
    never looked to see whether the model it had asked for was sitting next to
    the project file, and could not progress by any action the designer took.
    """
    if project.envelope_mm is None:
        return _report_problems(project_dir, project, [
            "envelope_mm is required when the geometry is authored: the print "
            "plan is written before the geometry, and it cannot be written "
            "without the envelope the part is allowed to occupy. Declare it as a "
            "stated or chosen requirement."], stage="run")

    print_plan, plan_problems = _print_plan(project_dir, project)
    if plan_problems:
        return _report_problems(project_dir, project, plan_problems, stage="plan")

    model_path = project_dir / (project.model or "model.py")
    proposal_path = project_dir / ACC.PROPOSAL_FILE
    missing = [name for name, path in ((ACC.PROPOSAL_FILE, proposal_path),
                                       (model_path.name, model_path))
               if not path.is_file()]
    if missing:
        return _commission_authored(project_dir, project, plan, print_plan, missing)

    brief_path = project_dir / project.brief
    brief_hash = S.sha256_text(
        brief_path.read_text(encoding="utf-8") if brief_path.is_file() else "")

    # ---- validate and freeze, before the builder exists --------------------
    try:
        proposal = ACC.load_proposal(proposal_path)
        # Checked before the freeze, not after: a proposal for another job would
        # otherwise cut a revision and invalidate this job's receipts on its way
        # to being refused.
        if proposal.job_id and proposal.job_id != project.job_id:
            raise ACC.ProposalError(
                f"{ACC.PROPOSAL_FILE} names job {proposal.job_id!r} and this "
                f"project is {project.job_id!r}. A proposal copied from another "
                "job describes another part, and every hash on the receipt would "
                "say it was this one.")
        body = ACC.generate(
            proposal=proposal, job_id=project.job_id, route=plan.route,
            requirement_sha256=_requirement_hash(project, brief_hash),
            source_artifact_sha256=_source_artifact_hashes(project_dir, project),
            print_plan_sha256=S.payload_hash(print_plan),
            print_plan_features=_plan_features(print_plan, project_dir=project_dir,
                                               project=project),
            preservation_features=_preservation_feature(project),
            route_gates={
                "required_reviews": list(plan.required_reviews),
                "verification_dispatch": plan.verification_dispatch,
                "requires_preservation": plan.requires_preservation,
                "requires_specification": plan.requires_specification,
                "consequence": project.consequence,
            },
            expected_artifacts={
                "stl": "candidate.stl",
                "step": "candidate.step" if project.step else None,
                "source": model_path.name,
                "declared": list(project.expected_artifacts),
            },
            # ADR 0002 section 3, and the honest answer for novel authored
            # geometry. The five legitimate sources are a certified template, an
            # analytic formula the pipeline generates from the frozen proposal,
            # an immutable source artifact plus a bounded delta, a previously
            # approved revision, and an independent verifier's predeclared bound.
            # This build has none of them for a part somebody just drew, and
            # inventing one -- a second agent's estimate, a heuristic over the
            # proposal text -- would restore the shape of the certified lane's
            # screen without restoring its substance.
            expected_volume_mm3=None,
            expected_volume_basis="NOT_INDEPENDENTLY_SPECIFIED")
        frozen = ACC.freeze(project_dir, body, updated_utc=project.updated_utc)
    except ACC.ProposalError as exc:
        return _report_problems(project_dir, project, [str(exc)], stage="proposal")

    if frozen.disposition == "SUPERSEDED":
        sys.stderr.write(
            f"\ndesign-tool: the acceptance contract moved to revision "
            f"{frozen.revision}.\n"
            + "".join(f"    - {line}\n" for line in frozen.changed[:8])
            + (f"    ... and {len(frozen.changed) - 8} more\n"
               if len(frozen.changed) > 8 else "")
            + f"  {len(frozen.invalidated)} receipt(s) bound to revision "
              f"{frozen.revision - 1} were invalidated and removed;\n"
              f"  {ACC.HISTORY_FILE} records their digests.\n")

    # ---- only now is the model executed, and not in this process ------------
    # One shot: the child imports the model, validates it, calls the builder,
    # exports the geometry into a scratch directory and exits. `built` is what
    # the parent re-read and re-hashed afterwards, and `isolation.build` has
    # already verified that nothing in this directory moved while it ran.
    try:
        built = ISO.build(model_path, dest_dir=project_dir, step=project.step)
    except ISO.BuildRefused as exc:
        return _report_problems(project_dir, project, [str(exc)], stage="build")

    # After the build rather than before it, and unavoidably so: the parameters a
    # model declares are read by importing it, and importing it is the thing that
    # now happens in another process exactly once.
    divergent = sorted(
        key for key in set(built.params) | set(proposal.params)
        if built.params.get(key) != proposal.params.get(key))
    if divergent:
        return _report_problems(project_dir, project, [
            f"{model_path.name} and {ACC.PROPOSAL_FILE} disagree about "
            f"{', '.join(divergent)}. The proposal is what the part is measured "
            "against and PARAMS is what it is built from; when they differ the "
            "job is building one part and gating another."], stage="build")

    fields = P.to_job_request_fields(project)
    fields["template"] = None
    request = runner.JobRequest(
        brief_path=brief_path,
        out_dir=project_dir,
        render=render,
        acceptance=ACC.AcceptanceSource(
            frozen=frozen, module=model_path.name,
            module_sha256=built.module_sha256,
            sources_sha256=built.input_sha256, provenance=built.provenance),
        authored_build=built,
        plan=plan,
        # No `plan_features` here: the print plan's support rows and the
        # preservation row are inside the frozen contract, where they are subject
        # to the same revision discipline as everything else the part is gated
        # against. Passing them again would append a duplicate id and the
        # preflight would refuse the contract.
        cache_dir=(project_dir / project.cache_dir) if project.cache_dir else None,
        **_review_calls(project_dir, plan),
        **fields)
    return _finish(project_dir, project, plan, request)


def _run_project(project_dir: Path, project: P.Project, plan: EX.ExecutionPlan,
                 *, render: bool) -> int:
    """Every deterministic stage this plan can execute right now.

    Dispatched on the builder, never on the route. Which lane builds the geometry
    and which reviews the job owes are two different questions, and answering the
    first with the second is what left a `RECONSTRUCT` job with a certified
    template running as though nothing had to be recovered.
    """
    if plan.builder == "AUTHORED":
        return _run_authored(project_dir, project, plan, render=render)

    fields = P.to_job_request_fields(project)
    request = runner.JobRequest(
        brief_path=project_dir / project.brief,
        out_dir=project_dir,
        render=render,
        plan=plan,
        # The certified builder takes no print plan -- its expectations are the
        # template's own -- but a declared edit scope is an obligation of the job,
        # not of the lane that happens to draw the shape.
        plan_features=_preservation_feature(project),
        cache_dir=(project_dir / project.cache_dir) if project.cache_dir else None,
        **_review_calls(project_dir, plan),
        **fields)
    return _finish(project_dir, project, plan, request)


def _finish(project_dir: Path, project: P.Project, plan: EX.ExecutionPlan,
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
            "route": plan.route,
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
        #
        # A capped lane is a third thing again, and it is not `NEEDS_ACTION`: no
        # answer the agent writes lifts it, so a job parked there waiting for a
        # response nobody can give is the livelock this stage exists to remove.
        # The deterministic work ran and its receipts are on disk to iterate
        # against.
        needs_evidence = final == "NEEDS_MORE_EVIDENCE"
        unavailable = final in ("EXPERIMENTAL_UNAVAILABLE", "UNSUPPORTED")
        _write_next_action(project_dir, {
            "schema_version": NEXT_ACTION_SCHEMA,
            "job_id": project.job_id,
            "kind": ("LANE_UNAVAILABLE" if unavailable
                     else "NEEDS_EVIDENCE" if needs_evidence else "BLOCKED"),
            "stage": result.stage,
            "route": plan.route,
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
    # Compiled here, in the same invocation, from state that is already on disk.
    # No round trip and no hand-written file: `design-tool run` is still the one
    # command for a whole job.
    plan = _compile(project_dir, project, decision)
    project.save(project_dir)

    return _run_project(project_dir, project, plan, render=not args.no_render)


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
        "lane_status": (final_payload or {}).get("lane_status"),
        "execution_plan_sha256": (final_payload or {}).get("execution_plan_sha256"),
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
        if report["lane_status"] and report["lane_status"] != "AVAILABLE":
            print(f"  lane         {report['lane_status']}")
        if next_action:
            print(f"  waiting for  {next_action.get('kind')} "
                  f"({next_action.get('stage')})")
            print(f"               {next_action.get('reason', '')}")
        for problem in report["problems"]:
            print(f"  problem      {problem}")

    if report["final_status"] in ("FAILED", "EXPERIMENTAL_UNAVAILABLE",
                                 "UNSUPPORTED"):
        # Not NEEDS_ACTION: there is no answer an agent can write that lifts
        # either of these, and an exit code that says "waiting" would send a
        # caller round a loop that cannot terminate.
        return 1
    if next_action is not None:
        return NEEDS_ACTION
    return 0


def diagnose(argv: list[str]) -> int:
    from . import diagnose as _diagnose
    return _diagnose.main(argv)


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
    "diagnose": diagnose,
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
