#!/usr/bin/env python3
"""What a job cost, and what it was allowed to cost.

`MISSION.md` makes efficiency a first-class objective and `ARCHITECTURE.md` 15.6
lists what has to be visible before any of it can be held to: AI dispatch count,
context size, deterministic runtime, import cost, cache reuse, repeated work,
failed work, per-alternative incremental cost. Until this module existed the
build measured one of the eight -- `JobResult.llm_calls`, printed to stderr and
written down nowhere -- and `docs/baseline.md` held wall-clock figures a person
had taken by hand on four jobs. A budget nobody measures reports all clear
exactly as convincingly as one that holds.

**Two documents, and the split is the point.** `timings.json` is one run's
per-stage durations and is rewritten every invocation. `cost.json` is the
*ledger*: one entry per invocation of one formulation, oldest first, plus the
totals over them. It is the only way the number that matters here can exist at
all -- a review round trip is three invocations of `design-tool run`, each of
which rebuilds the geometry from scratch, and a file that only ever describes the
last one reports a third of what the job spent.

**Bound by nothing, deliberately, and for `lifecycle.json`'s reason.** No receipt
carries this file's digest, `bindings.RECEIPTS` does not name it, and appending to
it cannot make anything stale. That is what lets it be a journal in a system whose
every other artifact is ordered by what it contains rather than by when it
happened. It also means a rerun on unchanged inputs still moves no receipt and no
run identity -- what it moves is this file, which is the honest record that the
rerun happened and cost something.

**What is measured here and what is honestly not.**

* *AI dispatch count* -- the existing counter, not a second one. Every entry
  appended by `Ledger.dispatched` sits beside the runner's own `llm_calls += 1`,
  and `pipeline/test_cost.py` asserts the two agree on every route. What it adds
  is the **commission**: `next_action.json` kind `AGENT_COMMISSION` asks an agent
  to author a proposal and a model, `tools/replay.py` already calls that "the
  live dispatch on the `CUSTOM` lane", and `llm_calls` never counted it because it
  happens in `cli.py` before the runner is reached. `docs/baseline.md` records
  the `CUSTOM` riser at "1 llm call" -- that 1 is this commission, counted by a
  person because nothing in the build counted it.
* *Context size* -- the bytes of the payload actually handed to each call, taken
  at the moment it is handed over. For a commission it is the instruction plus
  every file the instruction authorises the agent to read, because those are the
  context: `authorized_inputs` is a list the pipeline writes and an agent obeys.
  Bytes and not tokens: there is no tokenizer here and a fabricated token count
  would be a worse number than an honest byte count.
* *Deterministic runtime* -- wall time inside `runner.run`, plus the confined
  build boundary, which happens before `runner.run` is called and is the dominant
  term on the authored lane.
* *Cache reuse* -- the status `runner.run` already computes, per invocation, and
  the count of builds it actually avoided. That second number is the one worth
  having and it is **zero on every path in this build**, measured rather than
  assumed: the cache is consulted *after* `backend.build` returns, so a hit
  confirms the bytes and saves nothing.
* *Repeated work* -- builds beyond the first for one formulation, which is what a
  review round trip costs, and the restarts recorded in `lifecycle.json`.
* *Failed work* -- every invocation records whether it concluded and at which
  stage, so the seconds spent by runs that produced no claim are in the totals
  rather than absent from them.
* *Per-alternative incremental cost* -- `compare` below.
* *Import cost* is **not** decomposed, and saying so is the honest answer. The
  ~1.6 s an authored build pays is a fresh interpreter reaching `import trimesh`,
  and separating it from the build inside that interpreter needs an import hook in
  the child -- new machinery, for a number `docs/baseline.md` already decomposes
  by hand. What is recorded instead is which regime the seconds were measured in:
  `warm_kernel` says whether the geometry kernel was already imported in this
  process, which is the cold/warm distinction section 4.4 asks to be kept
  separate, and it costs a `sys.modules` lookup.

**The budget.** `budget(plan)` is what one invocation of a compiled plan may
dispatch, derived from the plan and from nothing else. `overruns` compares it
against what the invocation actually spent, and `runner.run` refuses a run that
went over -- a run that dispatched a review its plan did not name has not
followed the compiled plan, which is the authority gate, not a cost footnote.
The frozen table below pins the forecast itself, in the shipped module, the way
`selftest.FROZEN_CONTRACTS` pins a certified contract: `pipeline/test_cost.py`
imports it. Two copies of a golden is two goldens and the one nobody runs drifts.
Between them they make ROADMAP.md 3.4's "no release may add an AI round trip to
an existing path as an accidental side effect" a thing that fails a test rather
than a thing somebody notices.
"""
from __future__ import annotations

import dataclasses
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

from . import schemas as S
from .bindings import ROOT_ALTERNATIVE

COST_FILE = "cost.json"
COST_SCHEMA = 1

# Every way this pipeline spends a model context. `commission` is the designer
# round trip on the authored lane; the other three are the bounded reviews.
DISPATCH = ("commission", "spec", "safety", "verification")
REVIEW = ("spec", "safety", "verification")

# ---------------------------------------------------------------------------
# The frozen budget
# ---------------------------------------------------------------------------
#
# Per route, for an INCONSEQUENTIAL job on the builder that route is defined
# for, and these are the four numbers `docs/baseline.md` has always carried:
# DIRECT 0, CUSTOM 1 (its commission), FITTED 2, FULL 2. Consequence and the
# authored builder are separate terms below rather than a second table, because
# they are separate facts: consequence adds a safety review on *every* route,
# and authored geometry costs one commission whatever route asked for it.
#
# A change that moves one of these has to move it here, in a shipped module, in
# a diff a reviewer reads. That is the whole mechanism.
FROZEN_REVIEW_DISPATCH: dict[str, int] = {
    "DIRECT": 0, "CUSTOM": 0, "FITTED": 2, "FULL": 2,
}
FROZEN_COMMISSION_DISPATCH = 1
FROZEN_SAFETY_DISPATCH = 1


def budget(plan) -> dict[str, int]:
    """What one invocation of this plan may dispatch. A ceiling, not a forecast.

    Read off the compiled plan and nothing else, so it is the plan's own
    statement about its cost rather than a second opinion about the job. Every
    term is a ceiling because two of them are conditional at run time and the
    conditions are not knowable here: `OPTIONAL` verification is dispatched only
    when the broad screen came back clear, and a commission is written only while
    the proposal and the model are still missing. Under-spending a ceiling is a
    job that needed less; over-spending one is a run that did something its plan
    did not authorise.
    """
    reviews = 0
    # Keyed off `required_reviews`, which is where `route.required_reviews` puts
    # safety for exactly the CONSEQUENTIAL class the runner gates on.
    if "safety" in plan.required_reviews:
        reviews += 1
    # The obligation is not the ability: a job that owes a bounded recovery it
    # cannot run (authored geometry, which has no certified bounds to recover
    # into) dispatches nothing and is capped UNSUPPORTED instead.
    if plan.dispatches_specification:
        reviews += 1
    if plan.verification_dispatch != "NEVER":
        reviews += 1
    commissions = 1 if plan.builder == "AUTHORED" else 0
    return {"reviews": reviews, "commissions": commissions,
            "dispatches": reviews + commissions}


def overruns(allowed: dict[str, int] | None, spent: dict[str, int]) -> list[str]:
    """Every way this invocation spent past its plan's ceiling.

    `None` means no plan was compiled -- which cannot happen through either
    entry point, and is treated as "nothing to check" rather than as a failure,
    because a cost check that can refuse a job for a reason unrelated to cost is
    worse than the accounting it is protecting.
    """
    if not allowed:
        return []
    problems: list[str] = []
    for key, what in (("reviews", "bounded review"),
                      ("commissions", "designer commission")):
        if spent.get(key, 0) > allowed.get(key, 0):
            problems.append(
                f"this invocation dispatched {spent.get(key, 0)} {what}(s) and the "
                f"compiled plan budgets {allowed.get(key, 0)}. A dispatch the plan "
                "did not name is work done outside the plan, which is the "
                "authority gate rather than a cost footnote.")
    return problems


# ---------------------------------------------------------------------------
# One invocation's ledger
# ---------------------------------------------------------------------------

def context_bytes(payload: Any) -> int:
    """The size of a context, canonically serialized.

    The same canonical form every hash in this pipeline is taken over, so the
    number is a function of the payload and not of how a caller happened to
    format it.
    """
    return len(S.canonical_json(payload).encode("utf-8"))


def _payload_of(packet: Any) -> Any:
    """Packets are dataclasses; a spec call is handed a plain dict."""
    return getattr(packet, "payload", packet)


def _kernel_is_warm() -> bool:
    """Whether the geometry kernel was already imported in this process.

    Not a price for the import -- see the module docstring -- but the regime the
    seconds below were measured in, which section 4.4 asks to be kept separate
    and which nothing else in the build records.
    """
    return "trimesh" in sys.modules


@dataclasses.dataclass
class Ledger:
    """What one invocation spent, accumulated while it runs.

    Created by the caller that is about to spend something -- `runner.run` for a
    build, `cli._commission_authored` for a designer round trip -- and appended
    to `cost.json` when that invocation ends, however it ends.
    """

    job_id: str
    alternative: str = ROOT_ALTERNATIVE
    route: str | None = None
    builder: str | None = None
    allowed: dict[str, int] | None = None
    dispatches: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    builds: int = 0
    cache: str = "disabled"
    boundary_seconds: float = 0.0
    warm_kernel: bool = dataclasses.field(default_factory=_kernel_is_warm)
    # The runner's own timings dict, held by reference so that an invocation
    # which stops for a review still reports the stages it did reach.
    seconds: dict[str, float] = dataclasses.field(default_factory=dict)
    started: float = dataclasses.field(default_factory=time.perf_counter)
    _handed: dict[str, int] = dataclasses.field(default_factory=dict, repr=False)
    _from_disk: dict[str, bool] = dataclasses.field(default_factory=dict, repr=False)

    # -- recording -------------------------------------------------------

    def watch(self, kind: str, call: Callable | None) -> Callable | None:
        """Wrap a model call so the context it is handed is measured on the way past.

        It also reads the one thing `llm_calls` cannot see: whether the answer
        was already on disk. `cli._answer` marks itself when it returns a stored
        response, because a resumed run reading an answer an agent wrote two
        invocations ago has not asked anybody anything.
        """
        if call is None:
            return None

        def watched(packet: Any) -> Any:
            self._handed[kind] = context_bytes(_payload_of(packet))
            answer = call(packet)
            self._from_disk[kind] = bool(getattr(call, "answered_from_disk", False))
            return answer

        return watched

    def dispatched(self, kind: str) -> None:
        """One review call, counted where the runner counts `llm_calls`.

        **This is where the existing counter is wrong, and the ledger says so.**
        `llm_calls` counts a call that *returned an answer*, which is right in
        process and wrong through the command surface: `design-tool run` is
        resumable by re-running, so the invocation that finishes a job re-reads
        every answer written for it and increments the counter again. Summed over
        a real `MODIFY` round trip -- three invocations, `llm_calls` 0, 1, 2 -- it
        reports three model dispatches where two questions were ever asked.

        So a call answered from disk is recorded as `reused` and does not count as
        a question. What counts as one is `asked` below: the moment a packet was
        written and the run stopped for somebody to answer it. In process, where
        no file mediates, a returning call is the question and the answer at once
        and is counted here -- which is the case `llm_calls` was written for and
        the case where the two agree exactly.
        """
        S.require_enum(kind, DISPATCH, what="cost dispatch")
        self.dispatches.append({"kind": kind,
                                "context_bytes": self._handed.get(kind, 0),
                                "reused": self._from_disk.get(kind, False)})

    def asked(self, kind: str) -> None:
        """A question written to disk that this invocation stopped on.

        The dispatch, on the command surface: the packet exists, the run has
        stopped, and an agent will answer it before the next invocation. Counted
        here rather than when the answer is read, so that re-running a resumable
        job does not re-charge it for a question nobody asked twice.
        """
        S.require_enum(kind, DISPATCH, what="cost dispatch")
        self.dispatches.append({"kind": kind,
                                "context_bytes": self._handed.get(kind, 0),
                                "reused": False})

    def commissioned(self, instruction: Path, *, project_dir: Path,
                     named: tuple[str, ...] | list[str]) -> None:
        """The designer round trip, and the context it authorises.

        The instruction is what the pipeline writes; `authorized_inputs` is what
        it tells the agent to read. Counting only the first would price a
        commission at a few kilobytes of JSON while the brief, the project file,
        the route decision, the execution plan and the print plan go unmeasured,
        and those are the context -- `authorized_inputs` is a list this pipeline
        writes and an agent obeys, so it is the closest thing to a measurement of
        an agent's context that a deterministic program can honestly take. A
        named input that is not on disk contributes nothing rather than an
        estimate.

        Measured off the file rather than off the payload, because
        `_write_next_action` adds the state digest after the caller hands the
        body over and the bytes an agent reads are the ones on disk.
        """
        inputs: dict[str, int] = {}
        for name in named:
            try:
                target = S.resolve_within(Path(project_dir), name,
                                          what="commissioned input")
            except S.PathEscape:
                continue
            if target.is_file():
                inputs[name] = target.stat().st_size
        written = Path(instruction).stat().st_size if Path(instruction).is_file() else 0
        self.dispatches.append({
            "kind": "commission",
            "context_bytes": written + sum(inputs.values()),
            "instruction_bytes": written,
            "named_input_bytes": inputs,
        })

    # -- reading back ----------------------------------------------------

    def spent(self) -> dict[str, int]:
        """What this invocation has actually asked anybody. Reuse is not a question."""
        asked = [row for row in self.dispatches if not row.get("reused")]
        reviews = sum(1 for row in asked if row["kind"] in REVIEW)
        commissions = sum(1 for row in asked if row["kind"] == "commission")
        return {"reviews": reviews, "commissions": commissions,
                "dispatches": reviews + commissions,
                "context_bytes": sum(int(row["context_bytes"]) for row in asked)}

    def invocation(self, *, ok: bool, stage: str,
                   overruns: list[str] | None = None) -> dict[str, Any]:
        """This invocation as the ledger records it.

        `in_process` is wall time inside `runner.run`; `build_boundary` is the
        confined child, which ran before `runner.run` was called and whose cost
        is therefore outside it. `deterministic` is their sum, which is what the
        job actually spent and what `runner.py` already writes into
        `timings.json` for the same reason.
        """
        in_process = time.perf_counter() - self.started
        boundary = float(self.boundary_seconds)
        return {
            "ok": bool(ok),
            "stage": stage,
            "route": self.route,
            "builder": self.builder,
            "alternative": self.alternative,
            "seconds": {"deterministic": round(in_process + boundary, 4),
                        "in_process": round(in_process, 4),
                        "build_boundary": round(boundary, 4)},
            "dispatches": [dict(row) for row in self.dispatches],
            "builds": int(self.builds),
            "cache": self.cache,
            "warm_kernel": bool(self.warm_kernel),
            "budget": dict(self.allowed) if self.allowed else None,
            "overruns": list(overruns or ()),
        }


# ---------------------------------------------------------------------------
# The ledger on disk
# ---------------------------------------------------------------------------

def path(work_dir: Path) -> Path:
    """In the formulation's own directory, beside its receipts.

    Per formulation and not per project, because that is the scope the number is
    about: `alternatives/<id>/cost.json` is what that formulation cost, and a
    single shared file would be rewritten by whichever sibling ran last -- the
    same collision every other per-formulation file already avoids this way.
    """
    return Path(work_dir) / COST_FILE


def read(work_dir: Path) -> dict[str, Any]:
    """The ledger, or an empty one. An unreadable ledger reads as empty.

    Not an error: nothing depends on this file, and a corrupt cost record must
    not be able to stop a job whose geometry is fine. `append` refuses to write
    over something that is not a ledger, so a damaged file is preserved rather
    than replaced by one holding a single entry.
    """
    target = path(work_dir)
    if not target.is_file():
        return {}
    try:
        loaded = json.loads(target.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def invocations(work_dir: Path) -> list[dict[str, Any]]:
    rows = read(work_dir).get("invocations")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _is_a_ledger(target: Path) -> bool:
    """Whether the file on disk is this document and not something else."""
    try:
        loaded = json.loads(target.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, OSError):
        return False
    return isinstance(loaded, dict) and isinstance(loaded.get("invocations"), list)


def append(work_dir: Path, ledger: Ledger, entry: dict[str, Any]) -> Path:
    """Add one invocation and recompute the totals over all of them."""
    target = path(work_dir)
    if target.is_file() and not _is_a_ledger(target):
        # Something is there and it is not a ledger this module wrote. Refused
        # rather than overwritten, for `lifecycle.record`'s reason: an empty
        # ledger and an unreadable one both read as no invocations, and appending
        # to the second would delete a record of what a job spent.
        raise S.SchemaError(
            f"{COST_FILE} in {work_dir} is not a readable cost ledger; it is the "
            "record of what this formulation spent, so it is not overwritten")
    rows = invocations(work_dir) + [entry]
    payload = {
        "schema_version": COST_SCHEMA,
        "job_id": ledger.job_id,
        "alternative": ledger.alternative,
        "invocations": rows,
        "totals": totals(rows),
    }
    target.write_text(S.canonical_json(payload), encoding="utf-8")
    return target


def totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The sum over one formulation's invocations, with the repeats named.

    `repeated_builds` is builds beyond the first, and it is the number this whole
    module exists to make visible: a job with two bounded reviews is three
    invocations of `design-tool run`, each of which rebuilds the geometry, so two
    of the three builds are work the job had already done. Nothing in the build
    reported that before.

    `builds_avoided` is the other half and is currently always zero: an
    invocation that got a cache hit and still ran a build did not avoid one.
    Measured rather than declared, so that a cache which starts short-circuiting
    the build moves the number without anybody editing this comment.
    """
    every = [row for entry in rows for row in entry.get("dispatches") or ()]
    dispatches = [row for row in every if not row.get("reused")]
    reused = [row for row in every if row.get("reused")]
    builds = sum(int(entry.get("builds") or 0) for entry in rows)
    cache: dict[str, int] = {}
    for entry in rows:
        status = str(entry.get("cache") or "disabled")
        cache[status] = cache.get(status, 0) + 1
    return {
        "invocations": len(rows),
        # 15.6's `failed work`, and the name is broader than "a crash": an
        # invocation that stopped to ask a question, one that was refused, and
        # one that finished on a lane which may not certify its own result all
        # spent their seconds and produced no claim.
        "failed_invocations": sum(1 for entry in rows if not entry.get("ok")),
        "dispatches": len(dispatches),
        "reviews": sum(1 for row in dispatches if row.get("kind") in REVIEW),
        "commissions": sum(1 for row in dispatches
                           if row.get("kind") == "commission"),
        # A stored answer consumed by a resumed run. 15.6's `cache reuse`, for
        # the one thing in this pipeline that is genuinely expensive to produce
        # twice: `llm_calls` counts each of these as a fresh dispatch and this is
        # the number that says how many of them were not.
        "reviews_reused": len(reused),
        "context_bytes": sum(int(row.get("context_bytes") or 0)
                             for row in dispatches),
        "deterministic_seconds": round(sum(
            float((entry.get("seconds") or {}).get("deterministic") or 0.0)
            for entry in rows), 4),
        "build_boundary_seconds": round(sum(
            float((entry.get("seconds") or {}).get("build_boundary") or 0.0)
            for entry in rows), 4),
        "builds": builds,
        "repeated_builds": max(0, builds - 1),
        "builds_avoided": sum(1 for entry in rows
                              if entry.get("cache") == "hit"
                              and not entry.get("builds")),
        "cache": cache,
        "overruns": [text for entry in rows for text in entry.get("overruns") or ()],
    }


EMPTY_TOTALS: dict[str, Any] = totals([])


def totals_at(work_dir: Path) -> dict[str, Any]:
    """One formulation's totals, zeros where nothing has run there."""
    stored = read(work_dir).get("totals")
    return dict(stored) if isinstance(stored, dict) else dict(EMPTY_TOTALS)


# ---------------------------------------------------------------------------
# What one alternative added to the job
# ---------------------------------------------------------------------------

_INCREMENTAL_KEYS = ("dispatches", "reviews", "reviews_reused", "commissions",
                     "context_bytes", "deterministic_seconds", "builds",
                     "invocations")


def compare(costs: dict[str, dict[str, Any]], *,
            restarts: dict[str, int] | None = None) -> dict[str, Any]:
    """The job's cost, and what each formulation beyond the root added to it.

    ARCHITECTURE.md 15.2 requires the incremental cost per alternative to be
    recorded, and the vent-ball branch exercise is the case that made it
    concrete: a sibling cost a full build and a full audit, with nothing shared,
    and the only way anybody knew was that a person timed it.

    The incremental cost of a formulation is its own totals, and that is not a
    simplification -- it is the measurement. `design-tool branch` copies nothing
    and shares *intent*: the brief, the requirements, the source artifacts and
    the printer are read from one `project.json` by every formulation, and all of
    them are free. Everything that costs anything -- the commission, the build,
    the audit, the reviews -- is paid again per formulation. `shared` reports the
    two mechanisms that could make that untrue, and both are zero here for
    different reasons worth keeping apart: `builds_avoided` is *measured* off the
    ledgers and is zero because the cache is consulted after the build runs, and
    `reviews_from_a_sibling` is zero *by construction*, because the review
    envelope carries `alternative_id` precisely so that a sibling's answer cannot
    settle this formulation's question -- `benchmarks/replays` carries the
    adversarial case that proves it still bites.

    `reviews_reused` inside a formulation's own totals is a different number and
    is not sharing: it is this formulation re-reading its own stored answer on a
    resumed run.
    """
    restarts = dict(restarts or {})
    project = {key: 0 for key in _INCREMENTAL_KEYS}
    for row in costs.values():
        for key in _INCREMENTAL_KEYS:
            project[key] += row.get(key) or 0
    project["deterministic_seconds"] = round(project["deterministic_seconds"], 4)
    project["repeated_builds"] = sum(row.get("repeated_builds") or 0
                                     for row in costs.values())
    project["restarts"] = sum(restarts.values())
    project["formulations"] = len(costs)

    incremental = {
        key: {**{name: row.get(name) or 0 for name in _INCREMENTAL_KEYS},
              "repeated_builds": row.get("repeated_builds") or 0,
              "restarts": restarts.get(key, 0),
              "shared": {"builds_avoided": row.get("builds_avoided") or 0,
                         "reviews_from_a_sibling": 0}}
        for key, row in costs.items() if key != ROOT_ALTERNATIVE
    }
    return {"by_alternative": costs, "project": project,
            "incremental": incremental}


def restarts_by_alternative(events: list[dict[str, Any]]) -> dict[str, int]:
    """How many times each formulation's conclusions were deliberately discarded.

    Read off `lifecycle.json` rather than recorded here. A restart is repeated
    work by definition -- it throws away receipts whose bindings still hold so
    that the job can be done again -- and it is already journalled, so counting
    it a second time would be two records of one event.
    """
    counted: dict[str, int] = {}
    for event in events:
        if event.get("event") != "RESTART":
            continue
        key = str(event.get("alternative") or ROOT_ALTERNATIVE)
        counted[key] = counted.get(key, 0) + 1
    return counted


def one_line(row: dict[str, Any]) -> str:
    """The totals as a person reads them, for stderr and for `status`."""
    kilobytes = (row.get("context_bytes") or 0) / 1000.0
    text = (f"{row.get('dispatches') or 0} dispatch(es), "
            f"{kilobytes:.1f} kB context, "
            f"{row.get('deterministic_seconds') or 0.0:.2f}s, "
            f"{row.get('builds') or 0} build(s)")
    if row.get("repeated_builds"):
        text += f" of which {row['repeated_builds']} repeated"
    if row.get("reviews_reused"):
        text += f", {row['reviews_reused']} stored answer(s) reused"
    if row.get("restarts"):
        text += f", {row['restarts']} restart(s)"
    return text
