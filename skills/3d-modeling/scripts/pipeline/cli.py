#!/usr/bin/env python3
"""`design-tool` — the one agent-facing command surface.

    uv run design-tool init <project> --job-id J --source-mode NEW ...
    uv run design-tool route <project>
    uv run design-tool run <project>
    uv run design-tool status <project>
    uv run design-tool branch <project> --from . --id snap-fit --reason "..."
    uv run design-tool diagnose <artifact>
    uv run design-tool doctor
    uv run design-tool selftest

`branch` is the one verb for competing formulations of the same job. It writes a
row in `project.json` and copies nothing: everything unchanged -- requirements,
source artifacts, evidence, the brief -- stays shared, and the alternative's own
directory holds only what differs. Every file that means something about one
formulation moves under `alternatives/<id>`, which is what stops two siblings
deleting each other's receipts through the acceptance revision.

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
import dataclasses
import json
import math
import sys
import textwrap
from pathlib import Path
from typing import Any

from . import acceptance as ACC
from . import artifact_names as N
from . import bindings as B
from . import compare as CMP
from . import cost as COST
from . import execution as EX
from . import findings as F
from . import isolation as ISO
from . import lifecycle as LC
from . import project as P
from . import review as R
from . import route as RT
from . import runner, schemas as S
from . import screening as SCR
from . import status as STATUS

JOB_FILE = "job.json"


REVIEW_DIR = "reviews"
NEEDS_REVIEW = 3

# One exit code for "a person or an agent has to do something before this can
# continue", whether that something is a review response or a whole commission.
# A caller scripting the loop needs one condition to test, not two.
NEEDS_ACTION = NEEDS_REVIEW
# One spelling, in the module that reads the file to say whether the
# instruction is still current. Two would be two places as far as a reader is
# concerned.
NEXT_ACTION_FILE = STATUS.NEXT_ACTION_FILE
NEXT_ACTION_SCHEMA = 1
ROUTE_DECISION_FILE = "route_decision.json"
# The compiled plan's name is `artifact_names.EXECUTION_PLAN`, deliberately not
# re-exported here.


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


def _answer(work_dir: Path, kind: str):
    """A call that reads its answer from disk, or asks for one and stops.

    `work_dir`, not the project directory: a review answers a question about one
    formulation, and `reviews/<kind>_response.json` is treated as answered by its
    mere presence. With one shared `reviews/` a sibling picked up the answer
    written for its neighbour, and the envelope refusal that followed reported
    the wrong diagnosis -- a stale review rather than somebody else's.
    """
    def call(packet: Any) -> dict[str, Any]:
        room = work_dir / REVIEW_DIR
        room.mkdir(parents=True, exist_ok=True)
        # Always write the current request packet first. If a stale response from
        # a previous run is already on disk, the runner will reject it, but the
        # user must be able to answer the current envelope.
        request = room / f"{kind}_packet.json"
        request.write_text(S.canonical_json(_payload_of(packet)), encoding="utf-8")
        response = room / f"{kind}_response.json"
        if response.is_file():
            # Nothing was asked here. The answer was written by an agent between
            # two invocations, and a resumable command surface re-reads it on
            # every run that follows. `cost.Ledger.watch` reads this flag so the
            # ledger charges the job for the question once instead of once per
            # re-run -- which is what summing `llm_calls` over a round trip does.
            call.answered_from_disk = True
            try:
                return json.loads(response.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                # An unreadable answer is a malformed review, not a crash: the
                # runner boundary turns this into a blocked job with a receipt.
                raise R.ReviewError(
                    f"{response.name} is not valid JSON: {exc}") from exc
        raise ReviewNeeded(kind, packet, response)

    call.answered_from_disk = False
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
    if spec.get("candidate_strategy") not in (None, "SINGLE"):
        raise S.SchemaError(
            f"job.candidate_strategy {spec['candidate_strategy']!r} is not a field "
            "this build reads. It never produced a second candidate; competing "
            "formulations are declared with `design-tool branch` on a canonical "
            "project.")

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


def _report_artifacts(result: runner.JobResult, work_dir: Path | None = None) -> None:
    for name, path in sorted(result.artifacts.items()):
        sys.stderr.write(f"  {name:28s} {path.name}\n")
    timings = "  ".join(f"{k} {v:.2f}s" for k, v in result.timings.items())
    sys.stderr.write(f"\n  {timings}\n  llm calls: {result.llm_calls}\n")
    if work_dir is not None:
        # What this formulation has spent in total, not only what this
        # invocation did. `llm calls` above is one run's dispatches; the line
        # below is the job's, and on a job that paused for a review the two are
        # deliberately different numbers.
        sys.stderr.write(f"  cost so far: "
                         f"{COST.one_line(COST.totals_at(work_dir))}\n")


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

    _report_artifacts(result, job_dir)

    if not result.ok:
        sys.stderr.write(f"\ndesign-tool: {result.stage}: {result.message}\n")
        return 1
    sys.stderr.write(f"\n  {result.final_status['final_status']}: {result.message}\n")
    return 0


# ---------------------------------------------------------------------------
# The canonical project surface
# ---------------------------------------------------------------------------

def _work_dir(project_dir: Path, project: P.Project) -> Path:
    """Where this run writes, created before anything tries to write into it.

    One call, at the top of every verb that produces files, so that no code path
    can be the one that still writes to the project root. For an unbranched
    project this is the project root and the `mkdir` is a no-op on a directory
    that already exists, so nothing new appears.

    The verbs that only read do not come through here at all: `status.report`
    resolves the same directory without creating it, because a command that had
    to create a directory to report on a job would be changing what it is
    describing.
    """
    work = STATUS.active_work_dir(project_dir, project)
    work.mkdir(parents=True, exist_ok=True)
    return work


# What this formulation's files say right now, and whether an instruction
# written against them still describes the project. Both live in `status.py`,
# beside the report that reads them; the names here are the ones every call
# site in this module and its tests already use.
_state = STATUS.binding_state


def _write_next_action(work_dir: Path, project: P.Project,
                       payload: dict[str, Any]) -> Path:
    """Write the instruction, stamped with the state it was computed from.

    `next_action.json` carried no identity at all: no run id, no sequence, no
    digest of anything. Staleness was handled entirely by overwriting or
    unlinking it, so any path that changed the project without reaching one of
    those two calls left an instruction that pointed at work already done and
    nothing anywhere could tell. D17 is a live instance -- a successful `route`
    left the "fix the project" instruction it had written when the project was
    incomplete -- and the reader with the least context is the one most likely to
    believe it.

    The state is the binding map: the contract, the plan, the artifacts and which
    formulation this is. That is the same map `status.derive` checks the receipts
    against, deliberately, because an instruction and a receipt go stale for the
    same reasons and two answers to "has this project moved" is one answer and
    one bug.
    """
    state = _state(work_dir, project)
    path = work_dir / NEXT_ACTION_FILE
    path.write_text(S.canonical_json({
        **payload,
        "state": state,
        "state_sha256": S.payload_hash(state),
    }), encoding="utf-8")
    return path


_superseded = STATUS.is_superseded


def _clear_next_action(work_dir: Path) -> None:
    """A finished run must not leave a stale instruction behind.

    `next_action.json` is read as "this is what the job is waiting for". Left on
    disk after the thing was done, it says the opposite of the truth, and the
    reader with the least context is the one most likely to believe it.
    """
    path = work_dir / NEXT_ACTION_FILE
    if path.is_file():
        path.unlink()


# ---------------------------------------------------------------------------
# Resume and restart
# ---------------------------------------------------------------------------
#
# The model until now was "re-run the identical command", and reuse was four
# independent presence and content checks with no central authority: an artifact
# was reused if it was on disk, a review if a response file existed, an
# acceptance contract if its body compared equal, a build if the content cache
# held it. That is resumption, and it works, and there was no way to *say* it --
# so there was also no way to say the other thing.
#
# **Resume** is what the default already does, and `--resume` is not a synonym
# for it. It asserts the precondition the default assumes: that there is
# something here to continue. On a formulation with no receipts, no instruction
# and no answered review, "resume" is a user who believes work exists that does
# not, and the useful answer is to say so rather than to start from nothing under
# a word that promised otherwise.
#
# **Restart** is the question this slice actually had to decide, because
# invalidation is already scoped. "Delete everything and start again" would throw
# away the frozen acceptance contract (cutting a spurious revision on the next
# run), the content cache (re-paying for geometry that is still valid by
# content), the design proposal and model (which are inputs, not conclusions),
# and, if it were scoped to the project rather than the formulation, every
# sibling -- which is exactly what 13.5 forbids. A restart that costs more than
# it corrects is a worse default than no restart at all.
#
# So restart is scoped twice over: to **one formulation**, and to that
# formulation's **conclusions**. It removes what this alternative concluded --
# the receipts, and the review answers that fed them -- and keeps everything it
# concluded *from*. What it buys that resume cannot is the one case scoped
# invalidation is blind to by construction: a conclusion whose bindings all still
# hold and which somebody nonetheless no longer trusts. A review answered PASS
# against evidence that has not moved is reused forever by resume, correctly;
# restart is the only way to ask again.

# The review answers a restart discards. Not the packets: a packet is the
# question, rewritten at the top of every run, and deleting one removes nothing
# that was concluded.
RESPONSE_GLOB = "*_response.json"


def _concluded_files(work_dir: Path) -> list[Path]:
    """Everything in this formulation that records a conclusion, in removal order.

    `bindings.REMOVABLE` is derived from the receipt table rather than restated,
    so a receipt added there is discarded by a restart without anyone
    remembering to add it here. `model_contract.json` is deliberately not in it
    -- it is the definition of the `contract` binding, not a conclusion -- and
    neither is anything a run reads as input.
    """
    found = [work_dir / name for name in B.REMOVABLE]
    room = work_dir / REVIEW_DIR
    if room.is_dir():
        found.extend(sorted(room.glob(RESPONSE_GLOB)))
    found.append(work_dir / NEXT_ACTION_FILE)
    return [path for path in found if path.is_file()]


def _has_progress(work_dir: Path) -> bool:
    """Whether there is anything here to resume."""
    return bool(_concluded_files(work_dir))


def _restart(project_dir: Path, work_dir: Path, project: P.Project) -> None:
    """Discard this formulation's conclusions, recording them before they go.

    The digests are written to `lifecycle.json` and not only to stderr. A
    restart is the one operation here that removes a receipt whose bindings still
    hold, so it is the one where "neither current nor erased" needs somewhere
    durable to live -- ADR 0002's rule, applied to the case that rule did not
    cover.
    """
    stored = _final_status(work_dir) or {}
    doomed = _concluded_files(work_dir)
    discarded: dict[str, str] = {}
    for path in doomed:
        discarded[path.relative_to(work_dir).as_posix()] = S.sha256_file(path)
        path.unlink()
    LC.record(project_dir, {
        "event": "RESTART",
        "alternative": project.active_alternative or B.ROOT_ALTERNATIVE,
        # What the discarded conclusions were issued against. Content-derived,
        # so it is the same value for two restarts of one unchanged formulation
        # -- which is correct: they discarded the same thing.
        "run_id": B.identity(_state(work_dir, project)),
        "discarded_status": stored.get("final_status"),
        "discarded": discarded,
        "updated_utc": project.updated_utc,
    })
    if not discarded:
        sys.stderr.write("design-tool: --restart: nothing had concluded here; "
                         "this run starts from the same state a resume would.\n")
        return
    sys.stderr.write(
        f"design-tool: --restart discarded {len(discarded)} file(s) this "
        "formulation had concluded"
        + (f", including a stored {stored['final_status']}"
           if stored.get("final_status") else "")
        + f". Recorded in {LC.LIFECYCLE_FILE}:\n"
        + "".join(f"    - {name}\n" for name in sorted(discarded)))
    sys.stderr.write(
        "  Kept: the frozen acceptance contract, the design proposal, the model, "
        "the content cache\n  and every sibling formulation. A restart discards "
        "what this alternative concluded,\n  not what it concluded from.\n")


def _resume(project_dir: Path, work_dir: Path, project: P.Project) -> int:
    """Report what an explicit resume is continuing, or refuse if it is nothing."""
    if not _has_progress(work_dir):
        where = work_dir.relative_to(project_dir).as_posix()
        sys.stderr.write(
            "design-tool: --resume: nothing has concluded in "
            f"{'the project root' if where == '.' else where} -- no receipt, no "
            "answered review and no pending instruction. There is nothing to "
            "continue, so the flag is asserting something that is not true. Drop "
            "it to start this formulation.\n")
        return 2
    stale = B.broken(work_dir, evidence_dir=project_dir,
                     alternative_id=project.active_alternative or None,
                     model_name=project.model)
    # The receipts, not the review answers: a receipt is what records a binding
    # and is therefore what `broken` can speak about. Listing an answer here
    # would be reporting it as verified-still-current when what was checked is
    # the report it produced.
    kept = [name for name in B.REMOVABLE
            if (work_dir / name).is_file() and name not in stale]
    sys.stderr.write(
        f"design-tool: --resume: {len(kept)} receipt(s) still bind what they "
        f"were issued against and are being reused: {', '.join(kept) or 'none'}.\n")
    if stale:
        sys.stderr.write(
            f"  {len(stale)} no longer bind and are discarded below.\n")
    return 0


def _relative(work_dir: Path, project_dir: Path, name: str) -> str:
    """A file in the work directory, named the way the project sees it.

    `design_proposal.json` at the root, `alternatives/snap-fit/design_proposal.json`
    on a branch. The commission names paths rather than gaining an alternative
    field: the designer needs to know where to write, and a bare filename plus an
    id somewhere else is two things to get right instead of one. It also keeps an
    unbranched commission byte-identical, because the relative path of a file in
    the project root is its own name.
    """
    return (work_dir / name).relative_to(project_dir).as_posix()


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


def _report_problems(project_dir: Path, work_dir: Path, project: P.Project,
                     problems: list[F.Issue], *, stage: str) -> int:
    """Refuse the run, and say what is wrong in both registers at once.

    `unresolved` stays a list of English sentences, unchanged. It is not
    `validate()`'s field: three other writers fill it from `status.derive`'s
    reasons, from a stage's message, and from the project's blocking questions,
    and a field whose element type depends on which of the four wrote it is a
    field no reader can parse. So the structure goes beside it under `findings`,
    where every element is an `Issue.to_dict()` -- `code`, `where`, `severity`
    and a stable `id` -- and a caller asking "why is this alternative not
    COMMISSIONED" matches on those rather than on a substring of a sentence.
    """
    _write_next_action(work_dir, project, {
        "schema_version": NEXT_ACTION_SCHEMA,
        "job_id": project.job_id,
        "kind": "FIX_PROJECT",
        "stage": stage,
        "reason": "the project does not describe a job that can be routed",
        "unresolved": F.messages(problems),
        "findings": [issue.to_dict() for issue in problems],
        "completion_command": f"design-tool run {project_dir.as_posix()}",
        "updated_utc": project.updated_utc,
    })
    sys.stderr.write(f"design-tool: {P.PROJECT_FILE} is not complete enough to "
                     f"{stage}:\n")
    for problem in problems:
        sys.stderr.write(f"  - {problem.message}\n")
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
            sys.stderr.write(f"  - {problem.message}\n")
    return 0


def _compile(work_dir: Path, project: P.Project,
             decision: RT.RouteDecision) -> EX.ExecutionPlan:
    """Compile the plan and write both receipts.

    Two files, one authority. `route_decision.json` is why this route and not the
    others -- the audit trail of a decision. `execution_plan.json` is what will
    be executed under it, and it is the only one the runner reads.

    Both land in the work directory. A plan compiled for one formulation is not a
    plan for its sibling even when the two happen to compile identically, and a
    single shared `execution_plan.json` would be rewritten by whichever
    alternative ran last.
    """
    plan = EX.compile_plan(project, decision)
    (work_dir / ROUTE_DECISION_FILE).write_text(
        S.canonical_json(decision.as_dict()), encoding="utf-8")
    N.path(work_dir, N.EXECUTION_PLAN, owner=N.PIPELINE).write_text(
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
    work_dir = _work_dir(project_dir, project)
    problems = project.validate(project_dir, require_buildable=False)
    if problems:
        return _report_problems(project_dir, work_dir, project, problems,
                                stage="route")

    decision = RT.decide(project)
    RT.apply(project, decision)
    plan = _compile(work_dir, project, decision)
    project.save(project_dir)
    _route_next_action(project_dir, work_dir, project, plan)

    if plan.alternative_id:
        sys.stderr.write(f"\n  alternative {plan.alternative_id} "
                         f"({_relative(work_dir, project_dir, '')})")
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


def _route_next_action(project_dir: Path, work_dir: Path, project: P.Project,
                       plan: EX.ExecutionPlan) -> None:
    """Replace the pending instruction with the one the routed project is owed.

    D17: `route` used to succeed without touching `next_action.json`, so the
    "this project cannot be routed" instruction it wrote on an incomplete project
    survived the moment the project became routable, and went on telling its
    reader to fix something that was already fixed. Clearing was not enough on
    its own either -- a project that has been routed and never built *is* waiting
    for something, and a command that answers "what next" with silence is the
    same defect facing the other way.

    So the instruction is recomputed against the state after routing -- and only
    when routing has something to say about it. An instruction that still
    describes this project is one routing did not answer: an `AGENT_COMMISSION`
    is more specific than "run it", and replacing a live one with the general
    case would lose what the agent was told to write. A job whose receipts still
    support a current success is waiting for nothing routing knows about and the
    file goes; anything else is waiting to be run, and says so.
    """
    pending = _pending_action(work_dir)
    if pending is not None and not _superseded(pending, _state(work_dir, project)):
        return
    stale = B.broken(work_dir, evidence_dir=project_dir,
                     alternative_id=plan.alternative_id, model_name=project.model)
    derived = STATUS.derive(_final_status(work_dir), stale)
    if derived["derived_status"] in STATUS.CLAIMS_SUCCESS:
        _clear_next_action(work_dir)
        return
    _write_next_action(work_dir, project, {
        "schema_version": NEXT_ACTION_SCHEMA,
        "job_id": project.job_id,
        "kind": "RUN",
        "stage": "run",
        "route": plan.route,
        "reason": ("the route is decided and the plan is compiled; nothing has "
                   "been executed against it"),
        "unresolved": list(derived["reasons"]),
        "completion_command": f"design-tool run {project_dir.as_posix()}",
        "updated_utc": project.updated_utc,
    })


_pending_action = STATUS.pending_action


_alternative_dir = STATUS.alternative_dir
_final_status = STATUS.stored


# The print engineer's plan checks: the machine-readable projection of the print
# plan, and a `team_tools.validators` canonical filename. It was `PLAN_FILE`,
# which is what `bindings` called `execution_plan.json` -- so this module read
# `PLAN_FILE` and `B.PLAN_FILE` and meant two different files. Named for what it
# is now.
PRINT_PLAN_CHECKS_FILE = "print_plan_checks.json"

def _review_calls(work_dir: Path, plan: EX.ExecutionPlan) -> dict[str, Any]:
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
        "safety_call": _answer(work_dir, "safety") if "safety" in required else None,
        "spec_call": (_answer(work_dir, "spec")
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
        "verify_call": (_answer(work_dir, "verification")
                        if plan.verification_dispatch != "NEVER" else None),
    }




def _print_plan(work_dir: Path, project: P.Project) -> tuple[dict[str, Any], list[str]]:
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

    Generated *in the orientation the project declared*, which it was not. The
    template wrote the identity into its support rule whatever the job said, so
    the ceiling a candidate was gated against was measured in one frame while
    the candidate was measured in another. `project.orientation` is the single
    authority: it reaches the acceptance contract already, it reaches the plan
    from here, and `contract.preflight` refuses the run if the two disagree.

    **Absence is the only state in which this function owns the file.** The
    argument above holds exactly where nobody has authored a plan, and nowhere
    else. Where a print engineer has, the generated template used to replace it
    on every run -- destroying the Edge IDs, the declared interfaces, and every
    deliverable and export-fidelity obligation the charter requires, and
    replacing them with a template that has none of them. Two independent reads
    found it: an external post-mortem of the shipped build recorded three
    sessions doing nothing but re-authoring the file the run had just deleted,
    and the same defect reproduces here in one call.

    Presence is the authority boundary, not authorship: `authored_by` is
    optional, so a detector reading it would hand the file back to the generator
    for the plans that happened not to carry it -- which is the same bug for a
    smaller set of jobs.

    An existing plan that cannot be read, or does not validate, is **refused**
    rather than repaired. A run that answers an unbuildable plan by substituting
    one it wrote itself turns the engineer's error into the pipeline's silent
    decision, and a half-written file is exactly what a crashed session leaves.

    **A generated plan whose commission has moved is refused too, and that costs
    something.** Regenerating on every run is what kept the generated plan
    byte-stable; simply not writing left a 60 mm envelope gating a job that has
    since declared 20 mm, silently. The plan carries the generator's own
    `owner`, so this run can tell its own earlier output from an authored plan
    and say so. It still does not overwrite it, because the run drops that
    template at the engineer's deliverable path and *then* commissions them --
    editing it in place is a workflow this program invites, and an overwrite
    would be the same defect again aimed at the people it hurt before.
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
        consequence=project.consequence,
        orientation=project.orientation)

    accepted_path = work_dir / PRINT_PLAN_CHECKS_FILE
    if accepted_path.is_file():
        try:
            accepted = json.loads(accepted_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return {}, [f"{PRINT_PLAN_CHECKS_FILE} is already written and cannot be read: "
                        f"{exc}. It is the print engineer's deliverable, so this "
                        f"run will not replace it; repair or remove the file."]
        if not isinstance(accepted, dict):
            return {}, [f"{PRINT_PLAN_CHECKS_FILE} is already written and is not a JSON "
                        f"object. It is the print engineer's deliverable, so "
                        f"this run will not replace it."]
        if (accepted.get("owner") == plan.get("owner")
                and accepted != plan):
            # This run's own template from a superseded commission. Keeping the
            # generated plan byte-stable across runs was the point of
            # regenerating it, and leaving this one in place silently gates the
            # candidate against a declaration nobody holds any more -- a 60 mm
            # envelope that has since become 20 mm.
            #
            # Refused rather than replaced, even though the pipeline wrote it:
            # the run drops this template at the engineer's own deliverable
            # path and then stops to commission them, so editing it in place is
            # a workflow this program *invites*. An overwrite here would be the
            # same defect again, aimed at exactly the people it hurt before.
            return {}, [
                f"{PRINT_PLAN_CHECKS_FILE} is a generated plan from an earlier commission "
                f"and no longer matches this one -- the project has changed "
                f"since it was written. This run will not replace it, because "
                f"it may have been edited in place. Delete it to regenerate, "
                f"or supersede it with an accepted plan."]
        return accepted, validate_plan(accepted)

    problems = validate_plan(plan)
    if not problems:
        accepted_path.write_text(S.canonical_json(plan), encoding="utf-8")
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
    downward-facing area it inherits is all of theirs.

    **Per source, not all or nothing.** This used to return `None` -- the
    generated zero -- if *any* declared source could not be read, on the argument
    that a partial sum is a ceiling nobody measured. The vent-ball run showed what
    that costs: one source was a STEP the audit could not open, so the allowance
    the candidate was entitled to inherit from the *readable* source went to zero
    too, and the job failed `feature-plan-support-00` on 4,582.055 mm2 of overhang
    it had inherited from the part it was told to preserve. That reads as a design
    defect and was a missing importer.

    The argument was also wrong on its own terms. A zero is no more measured than
    a partial sum is -- it is *less* measured, and it is wrong in the direction
    that fails a correct part. The sum over the sources that read is a real
    measurement of real geometry and is a strict lower bound on what the candidate
    legitimately inherits, so it cannot excuse an overhang the edit added. What it
    cannot cover is the unread source's own share, and the note says so by name so
    that a reader knows which part of the ceiling was measured and which was not.

    `None` still means the generated zero, and now means what it says: not one
    declared source could be measured, so there is no evidence to credit at all.

    **In the frame the candidate is measured in.** This called `overhang_area`
    with no `transform=` while `commission` passes the contract's printer
    transform, so the ceiling and the measurement it caps were two frames of one
    inequality -- the last live half of D15. Each source is now placed the way
    it is actually placed:

        source's own coordinates --alignment_transform--> the job's design frame
                                 --model_to_printer_matrix--> the printer's

    which is one composition, `printer @ alignment`, in that order. The order is
    not a convention to pick: `alignment_transform` maps *out of* the source's
    frame and the printer matrix maps *out of* the design frame, so reversing
    them applies the printer rotation to coordinates that are not in the design
    frame yet. For a translating alignment and a rotating printer the two
    products differ, and a fixture pins that.

    An alignment or a rule matrix this cannot resolve makes that source an
    unmeasured gap by name, never a silent identity. Substituting identity would
    credit the candidate an allowance measured in the wrong place, which is the
    direction that passes a part that should fail.
    """
    if not project.edit_scopes or project.source_mode != "MODIFY":
        return None

    from .contract import as_transform

    printer = as_transform(rule.get("model_to_printer_matrix", "identity"))
    measured: list[tuple[str, float]] = []
    unmeasured: list[tuple[str, str]] = []
    for scope in project.edit_scopes:
        artifact = project.artifact(scope.artifact_id)
        if artifact is None:
            unmeasured.append((scope.artifact_id,
                               "no source artifact carries this id"))
            continue
        if printer is None:
            unmeasured.append((artifact.path,
                               "the print plan rule's model_to_printer_matrix "
                               "is not a usable rigid transform, so there is no "
                               "printer frame to measure this source in"))
            continue
        alignment = as_transform(scope.alignment_transform)
        if alignment is None:
            unmeasured.append((artifact.path,
                               "alignment_transform is not a usable rigid "
                               "transform, so where this source sits in the "
                               "job's frame is unknown"))
            continue
        try:
            source = S.resolve_within(project_dir, artifact.path,
                                      what="edit source")
            if not source.is_file():
                unmeasured.append((artifact.path, "not on disk"))
                continue
            from designer_toolkit import metrics as M
            area = float(M.overhang_area(
                str(source),
                threshold=float(rule.get("downward_normal_z_max", -0.73)),
                bed_z=float(rule.get("bed_z_mm", 0.0)),
                transform=printer @ alignment))
        except Exception as exc:                      # noqa: BLE001 - one source
            unmeasured.append((artifact.path,         # that cannot be read is a
                               f"{type(exc).__name__}: {exc}"))   # named gap, not
            continue                                  # the whole job's allowance
        measured.append((artifact.path, area))

    if not measured:
        return None

    total = sum(area for _, area in measured)
    if len(measured) == 1 and not unmeasured:
        path, area = measured[0]
        return area, (f"inherited from {path}, measured before the edit: "
                      f"{area:.3f} mm2 of the supplied artifact already faces "
                      "downward. The edit may not add to it.")

    detail = ", ".join(f"{path} {area:.3f} mm2" for path, area in measured)
    why = (f"inherited from {len(measured)} of "
           f"{len(measured) + len(unmeasured)} supplied artifacts, measured "
           f"before the edit: {total:.3f} mm2 already faces downward "
           f"({detail}). The edit may not add to it.")
    if unmeasured:
        gaps = ", ".join(f"{path} ({why_not})" for path, why_not in unmeasured)
        why += (f" This ceiling is partial: {len(unmeasured)} declared source(s) "
                f"could not be measured and contribute nothing to it -- {gaps}. "
                "Overhang the candidate inherited from those is charged to the "
                "edit, because nothing here can tell the two apart.")
    return total, why


def _plan_features(plan: dict[str, Any], *, project_dir: Path | None = None,
                   project: P.Project | None = None) -> tuple[dict[str, Any], ...]:
    """The plan's support rules, as contract features the gate already measures.

    One rule, not the whole plan: the support ceiling is what decides whether a
    novel part prints at all, and it is the rule the archived runs violated. The
    rest of the plan (edges, interfaces, coupons) is measured by
    `designer_toolkit.commission` and is not duplicated here.

    The rule's `model_to_printer_matrix` travels with its threshold and its bed
    height, where it used to be dropped. Dropping it did not make the row
    frameless; it made the contract's orientation silently stand in for a
    declaration another artifact had made, with nothing checking the two agreed.
    Carried here, the frozen contract records which frame each ceiling was
    measured in, and `contract.preflight` has both numbers in one place to
    refuse a disagreement before any geometry is built.
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
            "model_to_printer_matrix": rule.get("model_to_printer_matrix",
                                                "identity"),
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
    source's metadata must, which interface the edit realizes, which datum it is
    placed against, where the source sits in the job's frame) without moving the
    contract hash, and keep the review answer somebody wrote against the previous
    promise. Everything here reaches the frozen acceptance revision and therefore
    `contract_sha256` in the review envelope.
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
        declared_size = scope.minimum_detectable_defect_mm
        rows.append({
            "feature_id": f"preservation-{scope.artifact_id}",
            "kind": "preservation",
            "source": artifact.path,
            # Present only where the job declared one. An added key that is
            # always there -- even as null -- is still an added key, and it would
            # move the frozen contract hash of every job that predates this field
            # and declares nothing new. Same rule `contract.Contract.source`
            # follows for the same reason.
            **({"minimum_detectable_defect_mm": float(declared_size)}
               if declared_size is not None else {}),
            "region": scope.region_box,
            "tolerance_mm": scope.preservation_tolerance_mm,
            "exact": exact,
            # The rest of the declared edit intent, not only the fields the
            # measurement happens to consume. Everything here reaches the frozen
            # acceptance contract, so it reaches `contract_sha256`, so it reaches
            # the review envelope: a job that changes what it claims to be doing
            # can no longer keep the answer somebody wrote against the previous
            # claim. Only `alignment_transform` goes on to the sampling seed --
            # see `preservation._seed_material`. The others say what the edit
            # promised, not where the geometry is, so they must not move the plan
            # digest of a measurement they cannot change.
            "alignment_transform": scope.canonical_alignment_transform(),
            "preserve": list(scope.preserve),
            # Absent where the job declares none, for the reason
            # `minimum_detectable_defect_mm` gives above: the five pinned
            # certified contracts declare no permitted-change region, and an
            # always-present key would move all five for a field they do not use.
            **({"may_change": list(scope.may_change)}
               if scope.may_change else {}),
            "may_remove": list(scope.may_remove),
            "add": list(scope.add),
            # Which declared datum this edit was placed against (ADR 0003), by
            # the same argument as every other field in this block: re-placing an edit against a
            # different reference changes what the job claims to be doing, and
            # an answer written against the previous claim must not survive it.
            # Absent where the job declares none, for the reason
            # `minimum_detectable_defect_mm` gives above -- an always-present key
            # would move the five pinned certified contracts for a field they do
            # not use.
            #
            # Sorted, and only here. This field is a set of references to declared
            # `Datum` identities, not a precedence or an operation sequence, so
            # which order one scope happens to list two independent references in
            # is not a fact about the job -- and a contract that moved when it
            # changed would refuse a review answer over a difference that says
            # nothing. `edit_scopes` order stays authorial (`execution.compile_plan`
            # deliberately does not sort them) because the order of *scopes* can be
            # meaningful; the order inside one scope's reference list cannot.
            #
            # Sorted rather than deduplicated. A repeated id is a declaration this
            # function does not get to silently rewrite -- `Project.validate` owns
            # what a malformed reference list is -- and dropping one here would
            # hide it behind a contract that looks well-formed. The canonical datum
            # block in `_requirement_payload` does collapse duplicates, because
            # ADR 0003 requires one authoritative object per identity; that is a
            # different question from what this row reports the job as having
            # written.
            **({"datum_ids": sorted(scope.datum_ids)} if scope.datum_ids else {}),
            "expected_body_delta": int(scope.expected_body_delta),
            "preserve_metadata": bool(scope.preserve_metadata),
            "interface_ids": list(scope.interface_ids),
            # `abs: 0.0` on top of the row's own tolerance_mm: the band lives in
            # the comparison, and a second one here would widen it.
            "tolerance": {"abs": 0.0},
            "note": note,
        })
    return tuple(rows)


def _referenced_datums(project: P.Project) -> list[dict[str, Any]]:
    """The authoritative contents of exactly the datums some edit is placed against.

    ADR 0003 decision 5 -- a datum is a dependency binding, so changing one
    invalidates the results that rested on it -- and `docs/defects.md` D31, which
    was that only the near half of decision 5 had landed: a scope recorded *which*
    datums it depended on and nothing recorded *what they said*. A datum could
    keep its `datum_id` while its value, unit, provenance or derived revision
    changed, the frozen contract stayed byte-identical, and a review answer
    written against the old number kept binding.

    **Referenced, not every declared datum.** ARCHITECTURE.md 13.4: "a binding
    that a job does not use does not participate in its identity". Hashing every
    row would make correcting an unrelated datum cut a revision on work that
    never read it, which 13.5 forbids in the same breath as it requires the
    opposite for work that did.

    **One entry per identity, sorted by it.** Decision 4 is that coordinated
    scopes naming one reference share one object rather than each holding a copy,
    and the serialization has to say the same thing: two scopes referencing one
    datum produce one entry here, so there is one authoritative copy of the number
    in the contract and not two that can disagree. Sorting by `datum_id` is what
    makes the declaration order of `Project.datums` and the order references
    appear in both irrelevant, because neither is a fact about the job.

    **`as_dict()` verbatim, not a field list.** Reconstructing the payload here
    would be a second representation of the model, and its failure mode is
    specific: it would carry the fields whoever wrote it was thinking about and
    silently drop `owner`, `settled_by`, `note`, or whichever authority-bearing
    field is added next. `test_datums` asserts the bound row *equals*
    `Datum.as_dict()` for exactly that reason.

    **What this does not do.** It does not normalise anything. A datum declared
    with `"unit": null` arrives from the loader carrying the string `"None"`
    (`docs/defects.md` D33) and is bound as `"None"`, because this function's
    subject is whether identity follows the authoritative object the system
    accepted, and D33's is whether the loader built the right object. Binding a
    wrong-but-admitted value still moves the identity when it changes, which is
    the property D31 owes; correcting it here would be a second authority over
    what a unit means.
    """
    declared = {datum.datum_id: datum for datum in project.datums}
    referenced = {
        datum_id
        for scope in project.edit_scopes
        for datum_id in scope.datum_ids
        # An id no row declares is `REF_UNDECLARED` and `Project.validate` refuses
        # the job for it. Skipping it here rather than inventing an entry keeps
        # this function's answer a statement about declared authority; the id
        # itself still reaches the contract through the scope's own row.
        if datum_id in declared
    }
    return [declared[datum_id].as_dict() for datum_id in sorted(referenced)]


def _requirement_payload(project: P.Project, brief_hash: str) -> dict[str, Any]:
    """The structure `_requirement_hash` hashes, separated so it can be read.

    Split out for one reason, and it is a property the hash cannot support: the
    rule that an unused key is *absent* rather than present-and-empty is
    invisible through a digest. Two no-datum jobs both carrying `"datums": []`
    hash equal to each other, so every comparison between two projects passes
    while every recorded contract has silently moved -- the failure would only be
    visible against the goldens, one tier up, and a rule that only the expensive
    suite can check is a rule the commit gate does not hold. `test_datums` reads
    this payload and asserts the key is missing.
    """
    datums = _referenced_datums(project)
    return {
        "brief_sha256": brief_hash,
        "requirements": [r.as_dict() for r in project.requirements
                         if r.provenance in ("STATED", "INHERITED", "MEASURED")],
        # Absent when no edit is placed against a datum, which is every job in the
        # recorded set. Same rule the preservation row's optional fields follow:
        # an always-present key -- even as an empty list -- is still an added key,
        # and it would move the five pinned certified contracts and all four
        # replay goldens for a field they do not use.
        **({"datums": datums} if datums else {}),
        "envelope_mm": project.envelope_mm,
        "interfaces": [i.as_dict() for i in project.interfaces],
        "components": [c.as_dict() for c in project.components],
        "modifiers": list(project.modifiers),
    }


def _requirement_hash(project: P.Project, brief_hash: str) -> str:
    """What the user asked for, hashed, so the contract binds to it.

    The designer's own `CHOSEN` values are deliberately out: they are the
    proposal, and the proposal is already bound by its own hash. What this pins
    is the half of the job that nobody on the design side owns -- the brief, the
    values somebody stated or measured, the geometric references those values are
    placed against, the envelope, the interfaces and the component list. A
    contract that survived a change to any of those would be gating a part
    against a job that no longer exists.
    """
    return S.payload_hash(_requirement_payload(project, brief_hash))


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
    # Each kind with the fields that kind requires, derived from the whitelist
    # rather than described beside it. The kinds were already interpolated here
    # and the *fields* were not, so a designer read "proposable kinds:
    # section_area, ..." and had nowhere to learn that a `section_area` row owes
    # `at` and `value_mm2`. Six of the eight field names appeared nowhere in this
    # packet -- `d_mm`, `enclosing_d_mm`, `size_mm`, `value_mm2`, `z_from`,
    # `z_to` -- and none of them is in any `authorized_inputs` file either, so
    # the two instructions this packet gives could not both be obeyed: read only
    # what is authorized, and satisfy this API exactly. Measured on a real
    # commission, the designer went and read `acceptance.py` to find the schema,
    # which is the honest thing to do and outside what it was permitted.
    #
    # Derived, because a hand-written list is the same defect one release later:
    # `PROPOSABLE` is the authority on what a row may carry, and a second
    # spelling of it here would be a second authority over the same question.
    "features": "rows the gate measures. Geometry only -- position and size. "
                "Proposable kinds, with the fields each one requires: "
                + "; ".join(f"{kind} -> {', '.join(fields)}"
                            for kind, fields in sorted(ACC.PROPOSABLE.items()))
                + ". A row may not carry a tolerance: the band is the "
                  "pipeline's and is computed from the row's own magnitude",
}


def _commission_authored(project_dir: Path, work_dir: Path, project: P.Project,
                         plan: EX.ExecutionPlan, print_plan: dict[str, Any],
                         requirement_sha256: str, missing: list[str]) -> int:
    """One designer commission, for the proposal and the model together.

    One, not two. Freeze-proposal-then-build is a deterministic pipeline step and
    must not become a second dispatch: asking the designer to come back and
    confirm a contract generated from their own proposal would buy nothing and
    cost the round trip the `CUSTOM` route exists to avoid.

    Every path here is project-relative rather than a bare filename, which is how
    a commission for a branch says which branch without carrying an id field. On
    an unbranched job the relative path of a file in the project root *is* its
    name, so the commission is unchanged.

    **This is the dispatch `llm_calls` never counted.** `tools/replay.py` calls
    an `AGENT_COMMISSION` "the live dispatch on the `CUSTOM` lane" and refuses to
    replay a case that provokes one; `runner.py`'s counter cannot see it, because
    this function returns before the runner is reached. `docs/baseline.md` prices
    the `CUSTOM` riser at one call, and that one is this -- counted by a person,
    because nothing in the build counted it. It is a ledger entry now.
    """
    authorized = ([project.brief, P.PROJECT_FILE]
                  + [_relative(work_dir, project_dir, name)
                     for name in (ROUTE_DECISION_FILE, N.EXECUTION_PLAN,
                                  PRINT_PLAN_CHECKS_FILE)]
                  + [a.path for a in project.source_artifacts])
    instruction = _write_next_action(work_dir, project, {
        "schema_version": NEXT_ACTION_SCHEMA,
        "job_id": project.job_id,
        "kind": "AGENT_COMMISSION",
        "role": "designer",
        "stage": "candidate_build",
        "route": plan.route,
        "reason": plan.route_rationale,
        "authorized_inputs": list(authorized),
        "required_outputs": [_relative(work_dir, project_dir, name)
                             for name in missing],
        "proposal_api": dict(PROPOSAL_API),
        "source_api": {
            "PARAMS": "the numbers the shape is built from",
            "build()": "returns the solid, or a module-level `part`",
            "not here": "EXPECTED, BBOX_MM, BODIES, PROFILE_MARKS, VOLUME_MM3 and "
                        "any acceptance tolerance. They belong to "
                        + ACC.PROPOSAL_FILE + ", which is frozen into "
                        + ACC.ACCEPTANCE_FILE + " before this file is executed",
        },
        # `requirement_sha256`, not a digest of the whole project file. This is
        # the half of the job nobody on the design side owns -- the brief, the
        # stated, inherited and measured values, the envelope, the interfaces and
        # the components -- and it is the same digest the frozen acceptance
        # contract carries, so a designer can check that what they were
        # commissioned against is what the part was gated against. The digest
        # that used to be here hashed `status` and `bindings` too, so it moved
        # every time a run finished and bound nothing to anything.
        "bound": {"requirement_sha256": requirement_sha256,
                  "execution_plan_sha256": plan.plan_hash(),
                  "print_plan_sha256": S.payload_hash(print_plan),
                  "source_artifacts": {a.artifact_id: a.sha256
                                       for a in project.source_artifacts}},
        "unresolved": list(project.blocking_questions),
        "required_reviews": list(plan.required_reviews),
        "completion_command": f"design-tool run {project_dir.as_posix()}",
        "updated_utc": project.updated_utc,
    })
    ledger = COST.Ledger(job_id=project.job_id,
                         alternative=plan.alternative_id or COST.ROOT_ALTERNATIVE,
                         route=plan.route, builder=plan.builder,
                         allowed=COST.budget(plan))
    ledger.commissioned(instruction, project_dir=project_dir, named=authorized)
    breaches = COST.overruns(ledger.allowed, ledger.spent())
    COST.append(work_dir, ledger,
                ledger.invocation(ok=False, stage="candidate_build",
                                  overruns=breaches))
    if breaches:
        # A commission written for a plan that does not build authored geometry
        # is a round trip nothing asked for. Unreachable as the compiler stands
        # -- this function is only called from the authored lane -- and refused
        # rather than trusted, because "unreachable" is a property of today's
        # compiler and this is the guard that notices when it stops holding.
        for text in breaches:
            sys.stderr.write(f"design-tool: {text}\n")
        return 1
    sys.stderr.write(
        f"\ndesign-tool: this job routes {plan.route} and is missing "
        f"{', '.join(_relative(work_dir, project_dir, name) for name in missing)}.\n"
        f"  the commission is written to  "
        f"{_relative(work_dir, project_dir, NEXT_ACTION_FILE)}\n"
        f"  the print plan it builds against is  "
        f"{_relative(work_dir, project_dir, PRINT_PLAN_CHECKS_FILE)}\n"
        f"  write both files, in one pass, then run the same command again.\n\n"
        f"  {ACC.PROPOSAL_FILE} is what the part must measure; the model is how it\n"
        "  is built. They are separated so that the second cannot restate the\n"
        "  first after seeing a result.\n\n"
        "  This program cannot author geometry, and a deterministic tool that\n"
        "  returned some would be inventing it.\n")
    return NEEDS_ACTION


def _run_authored(project_dir: Path, work_dir: Path, project: P.Project,
                  plan: EX.ExecutionPlan, *, render: bool) -> int:
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

    The proposal and the model are looked for in the *work* directory. Shared,
    they were the sharpest of the sibling collisions: the commission is skipped
    when both exist, so a second formulation was never commissioned at all -- it
    silently rebuilt the first one's model and filed the receipts under its own
    name, which is a job that produced no evidence that it was a different job.
    """
    if project.envelope_mm is None:
        return _report_problems(project_dir, work_dir, project, [F.problem(
            F.SCHEMA_REQUIRED, "envelope_mm",
            "envelope_mm is required when the geometry is authored: the print "
            "plan is written before the geometry, and it cannot be written "
            "without the envelope the part is allowed to occupy. Declare it as a "
            "stated or chosen requirement.")], stage="run")

    print_plan, plan_problems = _print_plan(work_dir, project)
    if plan_problems:
        # `designer_toolkit.validate_plan` still answers in sentences, so the
        # finding carries the file and the position in that answer rather than a
        # field path inside the plan. It names the file and not a declaration
        # because the plan is a file either way: generated here from the printer
        # and the envelope when nobody authored one, and the print engineer's
        # own deliverable when somebody did. The finding cannot say which of the
        # two is at fault, and the file is what the reader has to open.
        return _report_problems(project_dir, work_dir, project, [
            F.problem(F.ARTIFACT_REFUSED, f"{PRINT_PLAN_CHECKS_FILE}[{index}]", text)
            for index, text in enumerate(plan_problems)], stage="plan")

    brief_path = project_dir / project.brief
    brief_hash = S.sha256_text(
        brief_path.read_text(encoding="utf-8") if brief_path.is_file() else "")
    requirement_sha256 = _requirement_hash(project, brief_hash)

    model_path = work_dir / (project.model or "model.py")
    proposal_path = work_dir / ACC.PROPOSAL_FILE
    missing = [name for name, path in ((ACC.PROPOSAL_FILE, proposal_path),
                                       (model_path.name, model_path))
               if not path.is_file()]
    if missing:
        return _commission_authored(project_dir, work_dir, project, plan,
                                    print_plan, requirement_sha256, missing)

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
            requirement_sha256=requirement_sha256,
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
        # Frozen into the work directory. That single argument is what makes
        # `_invalidate` correct across siblings: it deletes the receipts of the
        # revision it supersedes, and pointed at a shared directory it deleted
        # the *other* formulation's final status, commissioning report, artifact
        # manifest, manufacturing report and both review reports -- which the
        # other formulation then did back, on every alternating run.
        frozen = ACC.freeze(work_dir, body, updated_utc=project.updated_utc,
                            alternative_id=plan.alternative_id,
                            evidence_dir=project_dir)
    except ACC.ProposalError as exc:
        return _report_problems(project_dir, work_dir, project, [F.problem(
            F.ARTIFACT_REFUSED, ACC.PROPOSAL_FILE, str(exc))], stage="proposal")

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
        # `dest_dir` is the work directory: `candidate.stl`, `candidate.step` and
        # `candidate_declaration.json` are fixed literals, so shared they were
        # simply overwritten by whichever sibling ran last. It is also where the
        # boundary's canary lives -- `acceptance_contract.json`, which is now this
        # formulation's own.
        built = ISO.build(model_path, dest_dir=work_dir, step=project.step)
    except ISO.BuildRefused as exc:
        return _report_problems(project_dir, work_dir, project, [F.problem(
            F.ARTIFACT_REFUSED, model_path.name, str(exc))], stage="build")

    # After the build rather than before it, and unavoidably so: the parameters a
    # model declares are read by importing it, and importing it is the thing that
    # now happens in another process exactly once.
    declared = built.declared.params
    divergent = sorted(
        key for key in set(declared) | set(proposal.params)
        if declared.get(key) != proposal.params.get(key))
    if divergent:
        return _report_problems(project_dir, work_dir, project, [F.problem(
            F.INTENT_CONTRADICTION, f"{ACC.PROPOSAL_FILE}.params",
            f"{model_path.name} and {ACC.PROPOSAL_FILE} disagree about "
            f"{', '.join(divergent)}. The proposal is what the part is measured "
            "against and PARAMS is what it is built from; when they differ the "
            "job is building one part and gating another.")], stage="build")

    fields = P.to_job_request_fields(project)
    fields["template"] = None
    request = runner.JobRequest(
        brief_path=brief_path,
        out_dir=work_dir,
        # Evidence stays where it was declared. It is a shared job input -- a
        # photograph, a caliper sheet -- named once against the project, so it is
        # not copied into each formulation's directory and must not be looked for
        # there.
        evidence_dir=project_dir,
        render=render,
        # No `provenance` argument, because `AcceptanceSource` no longer has the
        # field: `as_source()` is handed verbatim to both reviewers, and the
        # candidate's own paragraph was reaching the party whose PASS or REJECT
        # decides the run. `built.declared` holds it, `candidate_declaration.json`
        # records it, and neither is a parameter of anything below (D10).
        acceptance=ACC.AcceptanceSource(
            frozen=frozen, module=model_path.name,
            module_sha256=built.module_sha256,
            sources_sha256=built.input_sha256),
        authored_build=built,
        plan=plan,
        # No `plan_features` here: the print plan's support rows and the
        # preservation row are inside the frozen contract, where they are subject
        # to the same revision discipline as everything else the part is gated
        # against. Passing them again would append a duplicate id and the
        # preflight would refuse the contract.
        # Shared across every formulation, and safely so: a cache slot is named
        # by `key.digest()`, which is a function of the contract and the
        # toolchain, so two alternatives that build different geometry key
        # differently and two that build the same geometry legitimately reuse it.
        cache_dir=(project_dir / project.cache_dir) if project.cache_dir else None,
        **_review_calls(work_dir, plan),
        **fields)
    return _finish(project_dir, work_dir, project, plan, request)


def _run_project(project_dir: Path, work_dir: Path, project: P.Project,
                 plan: EX.ExecutionPlan, *, render: bool) -> int:
    """Every deterministic stage this plan can execute right now.

    Dispatched on the builder, never on the route. Which lane builds the geometry
    and which reviews the job owes are two different questions, and answering the
    first with the second is what left a `RECONSTRUCT` job with a certified
    template running as though nothing had to be recovered.
    """
    if plan.builder == "AUTHORED":
        return _run_authored(project_dir, work_dir, project, plan, render=render)

    fields = P.to_job_request_fields(project)
    request = runner.JobRequest(
        brief_path=project_dir / project.brief,
        out_dir=work_dir,
        evidence_dir=project_dir,
        render=render,
        plan=plan,
        # The certified builder takes no print plan -- its expectations are the
        # template's own -- but a declared edit scope is an obligation of the job,
        # not of the lane that happens to draw the shape.
        plan_features=_preservation_feature(project),
        cache_dir=(project_dir / project.cache_dir) if project.cache_dir else None,
        **_review_calls(work_dir, plan),
        **fields)
    return _finish(project_dir, work_dir, project, plan, request)


def _finish(project_dir: Path, work_dir: Path, project: P.Project,
            plan: EX.ExecutionPlan, request: runner.JobRequest) -> int:
    """Run, then turn whatever came back into a state the next run can resume.

    The scoped invalidation happens here, immediately before the run, and it is
    the general form of what an acceptance revision has always done to its own
    receipts. `bindings.invalidate` removes exactly the receipts whose bindings no
    longer hold -- so a rebuilt candidate takes the commissioning report and the
    reviews with it, while a corrected evidence file takes only the reviews that
    were shown it and leaves the measurements of the part alone.

    Before the run rather than after, because the point is what happens when the
    run does *not* finish: a job that stops for a review used to leave the
    previous run's `final_status.json` sitting there, and a reader -- or
    `design-tool status` -- read a success that had been issued against evidence
    the job had already moved past (ADR 0002 section 4).
    """
    invalidated = B.invalidate(work_dir, evidence_dir=project_dir,
                               alternative_id=plan.alternative_id,
                               model_name=project.model)
    if invalidated:
        sys.stderr.write(
            f"\ndesign-tool: {len(invalidated)} receipt(s) no longer bind what "
            "they were issued against and were removed:\n"
            + "".join(f"    - {name}: {'; '.join(row['broke'])}\n"
                      for name, row in sorted(invalidated.items())))
    try:
        result = runner.run(request)
    except ReviewNeeded as need:
        # Relative to the work directory, which is where `next_action.json` sits
        # and where the answer has to be written. On an unbranched job the two
        # directories are the same and nothing about the instruction changes.
        rel = need.path.relative_to(work_dir)
        _write_next_action(work_dir, project, {
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
        _review_needed_message(need, work_dir)
        return NEEDS_ACTION

    _report_artifacts(result, work_dir)
    # Nothing is stamped back into `project.json`. `status` and `bindings` were a
    # copy of one run's outcome in the one file that has to be shared, so the
    # project said the job was whatever finished last -- and Slice A had already
    # had to stop a branch writing them, which left a mirror that was true of the
    # root and silently wrong while a branch was active. A formulation's outcome
    # is `final_status.json` in that formulation's own directory, and whether it
    # is still current is derived from the bindings rather than repeated from a
    # copy nothing keeps in step.
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
        _write_next_action(work_dir, project, {
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
    _clear_next_action(work_dir)
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
    continuation = parser.add_mutually_exclusive_group()
    continuation.add_argument(
        "--resume", action="store_true",
        help="continue this formulation, and say what is being reused. This is "
             "what a bare run already does; the flag asserts that there is "
             "something here to continue and refuses when there is not")
    continuation.add_argument(
        "--restart", action="store_true",
        help="discard what this formulation concluded -- its receipts and its "
             "review answers -- and build it again. Keeps the acceptance "
             "contract, the proposal, the model, the content cache and every "
             "sibling; the discarded receipts are recorded in "
             f"{LC.LIFECYCLE_FILE} before they go")
    args = parser.parse_args(argv)

    project_dir = args.project_dir.resolve()
    project = _load_project(project_dir)
    work_dir = _work_dir(project_dir, project)
    problems = project.validate(project_dir, require_buildable=False)
    if problems:
        return _report_problems(project_dir, work_dir, project, problems, stage="run")

    # After validation and before anything is compiled. A restart that ran on a
    # project too broken to route would discard a formulation's conclusions in
    # exchange for a refusal, and a resume that reported on one would be
    # describing a state the run is about to refuse to use.
    if args.restart:
        _restart(project_dir, work_dir, project)
    elif args.resume:
        refused = _resume(project_dir, work_dir, project)
        if refused:
            return refused

    decision = RT.decide(project)
    previous = project.route
    RT.apply(project, decision)
    if previous is not None and previous != decision.route:
        # Said, not stamped. `route_decision.json` is the audit trail of the
        # decision and `execution_plan.json` is what will run under it; a third
        # copy of the same fact in `project.json` was a mirror nobody read and
        # nothing kept in step.
        sys.stderr.write(f"design-tool: the route moved {previous} -> "
                         f"{decision.route}: {decision.condition}\n")
    # Compiled here, in the same invocation, from state that is already on disk.
    # No round trip and no hand-written file: `design-tool run` is still the one
    # command for a whole job.
    plan = _compile(work_dir, project, decision)
    project.save(project_dir)
    if plan.alternative_id:
        sys.stderr.write(f"design-tool: alternative {plan.alternative_id} "
                         f"({_relative(work_dir, project_dir, '')})\n")

    return _run_project(project_dir, work_dir, project, plan,
                        render=not args.no_render)


def status(argv: list[str]) -> int:
    """What the evidence on disk currently supports, not what a run once said.

    The status was *stored*: `status.decide` ran once, mid-run, its answer was
    serialized into `final_status.json`, and every reader from then on repeated
    it verbatim. This command recomputed `problems` and took the verdict as
    given, so a `VERIFIED` receipt beside a candidate somebody had rebuilt, an
    evidence file somebody had corrected or a plan that had since moved read as
    current, and nothing anywhere could tell.

    So `final_status` in this report is derived: the stored verdict, weakened to
    `STALE` when the receipts it was issued against no longer bind. The stored
    one is still reported, under its own name, because it remains the record of
    what that run concluded -- what changes is that a reader no longer trusts it
    without checking. Nothing is re-adjudicated: see `status.derive`.

    The report itself is assembled by `status.report`, which prints nothing and
    returns no exit code. This command is one of its two renderings -- the lines
    a person reads and the JSON `--json` emits -- and the exit code below is
    derived from the same value. `tools/replay.py` is the other consumer and
    calls that function directly, so neither reading of the report goes through
    the other's output.
    """
    parser = argparse.ArgumentParser(
        prog="design-tool status",
        description="Route, bindings, what the job is waiting for, and the claim it "
                    "is currently allowed to make.")
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    project_dir = args.project_dir.resolve()
    project = _load_project(project_dir, adapt=False)
    try:
        report = STATUS.report(project, project_dir)
    except STATUS.Unreadable as exc:
        raise SystemExit(f"design-tool: {exc}")
    next_action = report["waiting_for"]
    superseded = report["waiting_for_superseded"]
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"  job          {report['job_id']}")
        print(f"  source mode  {report['source_mode']}")
        print(f"  consequence  {report['consequence']}")
        # Only a job that branched prints a formulation block. The JSON carries
        # the root as a row -- D26, and a caller reading the set needs it -- but
        # a person running `status` on a job with one formulation should see
        # what they saw before branching existed, which is nothing here.
        # ROADMAP.md 3.4: a job that declares no alternatives costs exactly what
        # it cost before. The first version of the D26 fix printed
        # `alternative . [ACTIVE] NOT_RUN from (the shared root)` on every
        # unbranched job.
        if project.alternatives:
            for row in report["alternatives"]:
                at = (None if row["alternative_id"] == ROOT_ALTERNATIVE
                      else row["alternative_id"])
                mark = "*" if at == report["alternative"] else " "
                # The root has no parents and is not "from" anything; every
                # other row names what it was branched from.
                origin = (", ".join(row["parents"]) or "the shared root"
                          if at is not None else None)
                state_of = row["disposition"]
                if row.get("basis"):
                    state_of += f" on {row['basis']}"
                if row.get("superseded_by"):
                    state_of += f" by {row['superseded_by']}"
                label = (f"alternative {row['alternative_id']}"
                         if at is not None else "the shared root")
                print(f"  {mark} {label} [{state_of}] {row['status']}"
                      + (f" from {origin}" if origin else "")
                      + f": {row['reason']}")
        print(f"  run          {report['run_id'][:12]}")
        print(f"  route        {report['route'] or '(not decided)'}")
        if report["route_rationale"]:
            print(f"  because      {report['route_rationale']}")
        if report["required_reviews"]:
            print(f"  reviews      {', '.join(report['required_reviews'])}")
        # One line per assumption rather than a joined list: the settling check
        # is a sentence, and four of them behind a comma is a paragraph nobody
        # reads. A job with none prints nothing, as it did before ADR 0003.
        for row in report["assumptions"]:
            kind = ("a chosen number" if row["provenance"] == "CHOSEN"
                    else "a number with no recorded provenance")
            print(f"  assuming     {row['datum_id']} is {kind}. "
                  f"{row['owner']} settles it: {row['settled_by']}")
        if report["stored_status"]:
            print(f"  status       {report['final_status']}")
            if report["final_status"] == report["stored_status"]:
                print(f"  claim        {report['allowed_claim']}")
            else:
                print(f"  claim        none is current. The run concluded "
                      f"{report['stored_status']}: {report['allowed_claim']}")
        if report["final_status"] not in STATUS.CLAIMS_SUCCESS:
            for row in report["fallbacks"]:
                standing = ("its claim is current"
                            if row["status"] in STATUS.CLAIMS_SUCCESS
                            else "it has no current claim either")
                print(f"  fallback     {row['alternative_id']} is retained "
                      f"({row['status']}) and {standing}: {row['reason']}")
        for name, rows in sorted(report["stale"].items()):
            print(f"  stale        {name}: {'; '.join(rows)}")
        if report["cost"]["project"]["invocations"]:
            print(f"  cost         {COST.one_line(report['cost']['project'])}")
            for key, row in sorted(report["cost"]["incremental"].items()):
                # What this formulation added, and what it inherited for free.
                # Both, because the second is the claim branching makes and the
                # first is what it costs to make it.
                print(f"  + {key:10s} {COST.one_line(row)}; shared "
                      f"{row['shared']['builds_avoided']} build(s), "
                      f"{row['shared']['reviews_reused']} review(s)")
        if report["lifecycle"]:
            event = report["lifecycle"][-1]
            print(f"  last change  {event.get('event')} on "
                  f"{event.get('alternative')}: "
                  + (f"{event.get('was')} -> {event.get('now')}"
                     if event.get("event") == "DISPOSITION"
                     else f"discarded {len(event.get('discarded') or {})} file(s)"))
        if report["lane_status"] and report["lane_status"] != "AVAILABLE":
            print(f"  lane         {report['lane_status']}")
        if next_action:
            print(f"  waiting for  {next_action.get('kind')} "
                  f"({next_action.get('stage')})"
                  + (" -- superseded" if superseded else ""))
            print(f"               {next_action.get('reason', '')}")
            if superseded:
                print("               it was computed from a state this project "
                      "has left, so it is not what to do next")
        for problem in report["problems"]:
            print(f"  problem      {problem}")

    if report["final_status"] in ("FAILED", "EXPERIMENTAL_UNAVAILABLE",
                                 "UNSUPPORTED"):
        # Not NEEDS_ACTION: there is no answer an agent can write that lifts
        # either of these, and an exit code that says "waiting" would send a
        # caller round a loop that cannot terminate.
        return 1
    if report["final_status"] == "STALE":
        # There is something to do and it is not a review: re-run, and the
        # deterministic stages settle whether the conclusion still holds.
        return NEEDS_ACTION
    if next_action is not None and not superseded:
        return NEEDS_ACTION
    return 0


# How the shared root spells itself, on the command line and in the binding map.
# `bindings.py` needs the same name -- a review taken at the root carries no
# `alternative_id`, and comparing absent against absent would make the binding
# unreadable rather than satisfied -- and two spellings of one place is two
# places as far as a comparison is concerned.
ROOT_ALTERNATIVE = B.ROOT_ALTERNATIVE


def branch(argv: list[str]) -> int:
    """Declare a second formulation of the same job, or switch to one.

    Deterministic and free. It dispatches nothing, builds nothing and copies
    nothing: it appends one row to `project.json`, creates the directory that row
    names, and points `active_alternative` at it. Everything the two formulations
    share -- the brief, the requirements, the source artifacts, the evidence, the
    printer -- is still read from the one project file, which is what
    ARCHITECTURE.md 6.13 means by an alternative inheriting unchanged intent and
    recording only its differences.

    Two modes, because creating a branch and choosing which branch to work on are
    different questions and a system that could only answer the first could never
    return to the first formulation. `--activate .` goes back to the shared root,
    which is a real place: it has its own proposal, its own contract and its own
    receipts, and it is what the siblings were branched from.
    """
    parser = argparse.ArgumentParser(
        prog="design-tool branch",
        description="Declare a competing formulation of this job, or switch to "
                    "one. Nothing is copied: shared intent stays in project.json "
                    "and the alternative's directory holds only what differs.")
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("--from", dest="parent", default=None,
                        help=f"the alternative this one starts from, or "
                             f"{ROOT_ALTERNATIVE!r} for the shared root")
    parser.add_argument("--id", dest="alternative_id", default=None,
                        help="the new alternative's id: lower-case letters, "
                             "digits and hyphens, because it becomes a directory "
                             "name and appears in every review envelope")
    parser.add_argument("--reason", default=None,
                        help="why this formulation exists; two alternatives with "
                             "no stated difference cannot be compared")
    parser.add_argument("--activate", default=None,
                        help=f"switch to an existing alternative, or "
                             f"{ROOT_ALTERNATIVE!r} for the shared root, without "
                             "declaring a new one")
    parser.add_argument("--disposition", default=None,
                        choices=P.ALTERNATIVE_DISPOSITION,
                        help="move an existing alternative to a lifecycle state. "
                             f"{list(P.RUNNABLE_DISPOSITION)} may be worked under; "
                             "PAUSED parks one and keeps its instruction; "
                             f"{list(P.CONCLUDED_DISPOSITION)} finish with it and "
                             "clear it")
    parser.add_argument("--of", dest="of", default=None,
                        help="which alternative --disposition applies to; defaults "
                             "to the active one")
    parser.add_argument("--basis", default=None, choices=P.DISPOSITION_BASIS,
                        help="what the new disposition rests on. Required for every "
                             "state but ACTIVE: a disposition with no basis records "
                             "that somebody decided and not what they decided on")
    parser.add_argument("--superseded-by", dest="superseded_by", default=None,
                        help="the alternative that replaced or absorbed this one. "
                             f"Required by {list(P.SUCCESSOR_REQUIRED)}")
    args = parser.parse_args(argv)

    project_dir = args.project_dir.resolve()
    project = _load_project(project_dir, adapt=False)

    creating = any(value is not None
                   for value in (args.parent, args.alternative_id, args.reason))
    setting = any(value is not None
                  for value in (args.disposition, args.of, args.basis,
                                args.superseded_by))
    if setting and (creating or args.activate is not None):
        sys.stderr.write(
            "design-tool: --disposition moves an alternative that already exists "
            "between lifecycle states. It is not combined with declaring one "
            "(--from/--id/--reason) or with switching to one (--activate): a new "
            "branch starts ACTIVE, and a transition is a decision worth its own "
            "command and its own record.\n")
        return 2
    if setting:
        return _set_disposition(project_dir, project, args)
    if args.activate is not None and creating:
        sys.stderr.write(
            "design-tool: --activate switches to an alternative that already "
            "exists; --from/--id/--reason declare a new one. Creating and "
            "switching in one command is the first mode, which activates what it "
            "creates.\n")
        return 2

    if args.activate is not None:
        return _activate(project_dir, project, args.activate)

    missing = [name for name, value in (("--from", args.parent),
                                        ("--id", args.alternative_id),
                                        ("--reason", args.reason))
               if value is None]
    if missing:
        sys.stderr.write(
            f"design-tool: branch needs {', '.join(missing)}. An alternative with "
            "no recorded parent or no recorded reason is one nothing can be "
            "compared against later.\n")
        return 2

    row = P.Alternative(
        alternative_id=args.alternative_id,
        parents=() if args.parent == ROOT_ALTERNATIVE else (args.parent,),
        reason=args.reason,
        disposition="ACTIVE")
    # The index this row would occupy once appended, so the finding names the
    # position a caller would go and edit rather than a row that does not exist
    # yet.
    at = f"alternatives[{len(project.alternatives)}]"
    problems = list(row.problems(len(project.alternatives)))
    if project.alternative(row.alternative_id) is not None:
        problems.append(F.problem(
            F.REF_DUPLICATE, f"{at}.alternative_id",
            f"alternative {row.alternative_id!r} is already declared. Branching "
            "over it would replace its parents and its reason while its "
            "directory kept the receipts written under the old ones; use "
            f"--activate {row.alternative_id} to work on it."))
    for position, parent in enumerate(row.parents):
        if project.alternative(parent) is None:
            problems.append(F.problem(
                F.REF_UNDECLARED, f"{at}.parents[{position}]",
                f"--from {parent!r} names no declared alternative. Pass "
                f"{ROOT_ALTERNATIVE!r} to branch from the shared root."))
    if not problems:
        try:
            # The one path guard, and the one every other declared name in this
            # pipeline already goes through. The id is validated text by now, so
            # this is belt and braces -- and belt and braces is what a directory
            # name derived from user input gets.
            S.resolve_within(project_dir,
                             f"{P.ALTERNATIVES_DIR}/{row.alternative_id}",
                             what="alternative directory")
        except S.PathEscape as exc:
            problems.append(F.problem(F.ARTIFACT_PATH_UNSAFE,
                                      f"{at}.alternative_id", str(exc)))
    if problems:
        for problem in problems:
            sys.stderr.write(f"design-tool: {problem.message}\n")
        return 2

    project.alternatives = tuple(project.alternatives) + (row,)
    project.active_alternative = row.alternative_id
    work_dir = _work_dir(project_dir, project)
    project.save(project_dir)

    parents = ", ".join(row.parents) or "the shared root"
    sys.stderr.write(
        f"\n  alternative  {row.alternative_id}\n"
        f"  from         {parents}\n"
        f"  because      {row.reason}\n"
        f"  directory    {work_dir.relative_to(project_dir).as_posix()}\n"
        f"  disposition  {row.disposition}\n\n"
        "  Nothing was copied. Shared requirements, source artifacts and\n"
        "  evidence stay in project.json; write this formulation's proposal and\n"
        f"  model into the directory above, then run "
        f"`design-tool run {project_dir.as_posix()}`.\n")
    return 0


def _set_disposition(project_dir: Path, project: P.Project, args: Any) -> int:
    """Move one formulation between lifecycle states, and record the move.

    Four things happen here that a stored field could not do on its own, and they
    are what the seven states now *mean*:

    * **preferring one demotes the other.** ARCHITECTURE.md 13.3 says changing
      the preferred alternative does not erase the previously preferred one, so
      the displaced row goes back to ACTIVE and both halves of the switch are
      journalled. Two PREFERRED rows are refused by `Project.validate`, which is
      what makes "the preferred one" a thing a reader can name;
    * **concluding one clears its instruction.** `next_action.json` is read as
      "this is what the job is waiting for", and a formulation nobody will pick
      up again is waiting for nothing. Its receipts stay: a rejection is
      evidence, and 13.1 does not rewrite history;
    * **parking or concluding the active one moves the project off it.** A
      non-runnable disposition on the active formulation would otherwise leave
      the project in a state its own validation refuses, and the next command a
      user ran would be a refusal they did not ask for;
    * **the whole project is validated before anything is written.** A
      transition that produced an unloadable project would be a lifecycle that
      broke the job it was describing.
    """
    wanted = args.of or project.active_alternative
    if wanted is None:
        sys.stderr.write(
            "design-tool: --disposition needs --of <id>; no alternative is "
            "active, and the shared root is not one of the formulations a "
            "disposition applies to -- it is what they were branched from.\n")
        return 2
    if args.disposition is None:
        sys.stderr.write("design-tool: --of/--basis/--superseded-by move an "
                         "alternative between states; say which with "
                         "--disposition.\n")
        return 2
    row = project.alternative(wanted)
    if row is None:
        sys.stderr.write(
            f"design-tool: {wanted!r} names no declared alternative; have "
            f"{[a.alternative_id for a in project.alternatives]}\n")
        return 2

    basis = args.basis if args.basis is not None else (
        "" if args.disposition == "ACTIVE" else row.basis)
    successor = args.superseded_by if args.superseded_by is not None else (
        row.superseded_by if args.disposition in P.SUCCESSOR_REQUIRED else "")
    moved = dataclasses.replace(row, disposition=args.disposition, basis=basis,
                                superseded_by=successor)

    rows = []
    demoted: str | None = None
    for existing in project.alternatives:
        if existing.alternative_id == wanted:
            rows.append(moved)
        elif (args.disposition == "PREFERRED"
              and existing.disposition == "PREFERRED"):
            demoted = existing.alternative_id
            rows.append(dataclasses.replace(existing, disposition="ACTIVE"))
        else:
            rows.append(existing)

    before = project.alternatives
    was_active = project.active_alternative
    project.alternatives = tuple(rows)
    if (project.active_alternative == wanted
            and args.disposition not in P.RUNNABLE_DISPOSITION):
        project.active_alternative = None

    problems = project.validate(project_dir, require_buildable=False)
    if problems:
        project.alternatives = before
        project.active_alternative = was_active
        for problem in problems:
            sys.stderr.write(f"design-tool: {problem.message}\n")
        return 2

    if args.disposition in P.CONCLUDED_DISPOSITION:
        _clear_next_action(_alternative_dir(project_dir, wanted) or project_dir)
    project.save(project_dir)
    if demoted:
        # First, because it is what the promotion displaced: a reader following
        # the journal in order sees the seat vacated and then taken, and the last
        # event is the decision somebody made rather than its consequence.
        LC.record(project_dir, {
            "event": "DISPOSITION", "alternative": demoted,
            "was": "PREFERRED", "now": "ACTIVE", "basis": "USER_SELECTION",
            "superseded_by": "", "note": f"displaced as preferred by {wanted}",
            "updated_utc": project.updated_utc})
    LC.record(project_dir, {
        "event": "DISPOSITION", "alternative": wanted,
        "was": row.disposition, "now": args.disposition, "basis": basis,
        "superseded_by": successor, "note": "",
        "updated_utc": project.updated_utc})

    sys.stderr.write(f"\n  alternative  {wanted}\n"
                     f"  disposition  {row.disposition} -> {args.disposition}"
                     + (f" on {basis}" if basis else "") + "\n")
    if successor:
        sys.stderr.write(f"  replaced by  {successor}\n")
    if demoted:
        sys.stderr.write(f"  demoted      {demoted} PREFERRED -> ACTIVE "
                         "(nothing was deleted)\n")
    if was_active == wanted and project.active_alternative is None:
        sys.stderr.write(
            f"  active       the shared root -- {args.disposition} may not be "
            "worked under\n")
    if args.disposition in P.CONCLUDED_DISPOSITION:
        sys.stderr.write("  cleared      next_action.json; a formulation this job "
                         "is finished with is waiting for nothing. Its receipts "
                         "are untouched.\n")
    sys.stderr.write(f"  recorded     {LC.LIFECYCLE_FILE}\n\n")
    return 0


def _activate(project_dir: Path, project: P.Project, wanted: str) -> int:
    """Point the project at an existing formulation, or back at the shared root."""
    if wanted != ROOT_ALTERNATIVE:
        row = project.alternative(wanted)
        if row is None:
            sys.stderr.write(
                f"design-tool: {wanted!r} names no declared alternative; have "
                f"{[a.alternative_id for a in project.alternatives]}\n")
            return 2
        if row.disposition not in P.RUNNABLE_DISPOSITION:
            sys.stderr.write(
                f"design-tool: alternative {wanted!r} is {row.disposition}, and "
                f"only {list(P.RUNNABLE_DISPOSITION)} may be worked under. "
                + (f"Resume it first: `design-tool branch {project_dir.as_posix()} "
                   f"--disposition ACTIVE --of {wanted} --basis USER_SELECTION`. "
                   "Activating a paused formulation in silence would be a pause "
                   "that paused nothing.\n"
                   if row.disposition == "PAUSED" else
                   f"{row.disposition} says this job is finished with it. Branch a "
                   "new formulation from it rather than reopening it in place, "
                   "which would rewrite the history it is the record of.\n"))
            return 2
    project.active_alternative = None if wanted == ROOT_ALTERNATIVE else wanted
    work_dir = _work_dir(project_dir, project)
    project.save(project_dir)
    where = work_dir.relative_to(project_dir).as_posix()
    sys.stderr.write(f"\n  active       {project.active_alternative or 'the shared root'}\n"
                     f"  directory    {where}\n")
    return 0


def compare(argv: list[str]) -> int:
    """Set this job's formulations beside each other, on the receipts on disk.

    Deterministic and free. It dispatches nothing, builds nothing and writes
    nothing but its own report: every number in it was measured by a run that
    had the part in front of it, and the only thing added here is the act of
    putting two of them side by side.

    It does not choose. `design-tool branch --disposition` does, and it records
    who chose and on what basis; a comparison that also chose would be a second
    authority over one decision, and the one with no person's name on it. So
    there is no total, no weight and no order in the output -- see
    `pipeline/compare.py` for why that is a structural guarantee rather than a
    convention, and for the three ways a formulation's own proposal can set the
    rubric it will be graded against.
    """
    parser = argparse.ArgumentParser(
        prog="design-tool compare",
        description="What setting this job's formulations beside each other "
                    "establishes, and -- the more important half -- what it does "
                    "not. No score, no ranking, no selection.")
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("--against", default=None,
                        help="a comma-separated list of formulations to compare, "
                             f"{ROOT_ALTERNATIVE!r} for the shared root. The "
                             "default is every formulation that may be worked "
                             f"under ({list(P.RUNNABLE_DISPOSITION)}) plus the "
                             "root, which is a formulation with its own "
                             "proposal, contract and receipts even though it has "
                             "no declared row")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    project_dir = args.project_dir.resolve()
    project = _load_project(project_dir, adapt=False)

    # The root plus every declared alternative. `status` carries the same union
    # now -- it did not when this was written, and a comparison taking its
    # formulation set from `report["alternatives"]` would have silently dropped
    # one of the knob's three. That was `docs/defects.md` D26, fixed; this set
    # is still built here rather than read from a report, because a comparison
    # must not depend on another command's shape.
    declared = {ROOT_ALTERNATIVE: None}
    for row in project.alternatives:
        declared[row.alternative_id] = row

    if args.against is not None:
        wanted = [name.strip() for name in args.against.split(",") if name.strip()]
        unknown = [name for name in wanted if name not in declared]
        if unknown:
            sys.stderr.write(
                f"design-tool: {', '.join(unknown)} names no formulation of this "
                f"job; have {', '.join(declared)}\n")
            return 2
    else:
        # Runnable, because a comparison is a thing you do before deciding, and
        # REJECTED or SUPERSEDED formulations are ones the job has already
        # finished with. They stay on disk and stay nameable with --against --
        # 6.14 requires a rejected alternative to remain available for
        # reconsideration -- they are just not what "compare this job" means.
        wanted = [key for key, row in declared.items()
                  if row is None or row.disposition in P.RUNNABLE_DISPOSITION]

    readings: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for key in wanted:
        alternative_id = None if key == ROOT_ALTERNATIVE else key
        where = _alternative_dir(project_dir, alternative_id)
        if where is None or not where.is_dir():
            missing.append(key)
            continue
        readings[key] = CMP.read(where, project_dir=project_dir,
                                 alternative_id=alternative_id,
                                 model_name=project.model)
    for key in missing:
        sys.stderr.write(f"design-tool: {key} has no directory on disk and is "
                         "not compared\n")

    events = LC.read(project_dir)
    restarts = COST.restarts_by_alternative(events)
    costs = {}
    for key in readings:
        totals = COST.totals_at(readings[key]["dir"])
        costs[key] = {**totals, "restarts": restarts.get(key, 0)}

    try:
        payload = CMP.report(project, readings, costs)
    except (CMP.CompareError, SCR.ScreeningShapeUnexpected) as exc:
        # The second one is `docs/defects.md` D27's guard. It is deliberately
        # loud, but loud is not the same as uncontrolled: `CompareError` is not
        # a `ValueError` and `main` catches nothing, so without this a shape
        # regression reached a user as a bare traceback while every other
        # failure in this program reaches them as one `design-tool:` line. Gate
        # 4.1 asks for controlled failure, not for a stack.
        sys.stderr.write(f"design-tool: {exc}\n")
        return 2

    # Written before it is printed, and at the project root: a comparison is
    # about several formulations, so it belongs to none of their directories,
    # and writing it into one would put a sibling's artifact under another's
    # work directory -- which is the scoping rule the work directory exists for.
    (project_dir / CMP.COMPARISON_FILE).write_text(
        S.canonical_json(payload) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _compare_table(payload)
    # Always zero on a report that ran. A comparison is never *waiting* for
    # anything -- there is no answer a caller could write that changes it -- and
    # a non-zero code would send a script round a loop that cannot terminate.
    # A stale sibling is a finding in the output, not a state to resolve here.
    return 0


def _compare_table(payload: dict[str, Any]) -> None:
    """The same report a person reads, in the shape `status` prints."""
    axes = payload["axes"]
    mandatory = axes["mandatory"]
    print(f"  job          {payload['job_id']}")
    print(f"  compared     {len(payload['compared'])} formulations, from receipts "
          "alone -- nothing was built and nothing re-adjudicated")
    print(f"  rubric       {mandatory['verdict']}")
    for line in _wrapped(mandatory["note"]):
        print(f"               {line}")
    for check_id, row in sorted(mandatory.get("expectations", {}).items()):
        print(f"               {check_id} was measured against")
        for key in sorted(row["expected"]):
            print(f"                 {key:14s} {json.dumps(row['expected'][key])}"
                  f"  band {json.dumps(row['tolerance'][key])}"
                  f"  {row['result'][key]}")
    for key, rows in sorted(mandatory.get("only_in", {}).items()):
        print(f"               only {key} declared {', '.join(rows)}")
    # No marker on any row. `status` marks the active formulation because one of
    # them is where work is happening; here, marking one would be the ordering
    # this command exists not to imply.
    for key in payload["compared"]:
        own = mandatory["per_formulation"][key]
        claim = axes["claim"]["per_formulation"][key]
        print(f"  formulation  {key:14s} {claim['status'] or 'NOT_RUN':10s} "
              f"mandatory {own['verdict']}"
              + (f" ({own['stored_verdict']} when it ran)"
                 if own["verdict"] == CMP.MANDATORY_UNKNOWN_STALE else ""))
    for group in payload["identical_designs"]:
        print(f"  same design  {', '.join(group['members'])} share source "
              f"{str(group['source_sha256'])[:12]}; their agreement corroborates "
              "nothing")
    for key, row in sorted(axes["evidence"]["per_formulation"].items()):
        if row["stale_receipts"]:
            print(f"  stale        {key}: {', '.join(row['stale_receipts'])}")
    print("  requirements bound as one digest"
          + (", identical across all of them" if payload["shared"]["same_requirement_digest"]
             else ", AND THEY DIFFER -- these formulations were frozen against "
                  "different job states")
          + ", and not checked row by row:")
    print("               each formulation met the contract it froze, which is "
          "not 'they meet the requirement'")
    for row in payload["not_compared"]:
        # The deciding ones are marked, because a dimension this build cannot
        # measure and this job turns on is the finding rather than a footnote.
        label = ("not compared!" if row["standing"] == CMP.DECIDING
                 else "not compared")
        print(f"  {label:12s} {row['dimension']} -- {row['owner']}")
    print(f"  preference   {'admissible' if payload['preference']['admissible'] else 'none'}")
    for line in _wrapped(payload["preference"]["because"]):
        print(f"               {line}")
    print("               this command compares and does not select; use "
          "`design-tool branch --disposition`")


def _wrapped(text: str, width: int = 62) -> list[str]:
    """Prose at the width the rest of this surface prints at."""
    return textwrap.wrap(text, width=width) or [""]


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
    "branch": branch,
    "compare": compare,
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
