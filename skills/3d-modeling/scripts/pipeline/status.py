#!/usr/bin/env python3
"""Final status, and the claim it permits.

Four statuses, and the rules that separate them are the point of the artifact.
`VERIFIED` is the only one that means somebody independent agreed, so everything
that could have gone unexamined has to block it: a required manufacturing
predicate nobody proved, a screening detector that could not run, a
`CONSEQUENTIAL` job with no safety pass.

`COMMISSIONED` is not a lesser `VERIFIED`. It is a precise claim -- the geometry
was measured against its contract and matched -- and the allowed-claim string
says in words what was *not* established, so a reader who skips the JSON still
cannot mistake one for the other.
"""
from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import bindings as B
from . import cost as COST
from . import findings as F
from . import lifecycle as LC
from . import project as P
from . import review as R
from . import safety as _safety_review
from . import schemas as S
from . import verification as _verification_review
from .contract import Contract

# Two answers `decide` can never produce and a reader can. `decide` runs once,
# mid-run, with the evidence in front of it; `derive` runs whenever somebody
# asks, over what is on disk, and its whole job is to say when the stored answer
# is no longer about the project it is sitting in.
#
# `NOT_RUN` is not "failed" and not "passed": no run has concluded here.
# `STALE` is not a verdict about the part at all -- it says the verdict that was
# reached was reached against evidence that has since moved, so nobody may repeat
# it as current. Neither belongs in `S.FINAL_STATUS`, because neither is a thing
# a run may write down about a candidate it measured.
DERIVED_ONLY = ("NOT_RUN", "STALE")
DERIVED_STATUS = S.FINAL_STATUS + DERIVED_ONLY

# The two a broken binding is allowed to take away. The lane cap in `decide`
# makes the same choice for the same reason: `FAILED` and `NEEDS_MORE_EVIDENCE`
# are findings the run is entitled to report, and replacing one with "stale"
# would hide a real defect behind a bookkeeping caveat.
CLAIMS_SUCCESS = ("COMMISSIONED", "VERIFIED")

# Predicates no mesh can answer. Without a named, versioned slicer adapter these
# are always DEFERRED -- and this toolchain has no slicer, by design. Promising
# otherwise would be promising verification the stack cannot produce.
SLICER_DEPENDENT = {
    "supports": "actual support-contact faces and their toolpaths",
    "multi-material": "the material boundary as the slicer resolves it",
    "multi-colour": "the colour boundary as the slicer resolves it",
    "flexible-filament": "extrusion behaviour of a flexible under this geometry",
}

# Named in the plan, and not yet measured by anything here. They are DEFERRED
# rather than SATISFIED: the earlier version returned SATISFIED with the reason
# "settled from the mesh and the declared orientation" while nothing was
# settling anything, which is a fabricated claim on a receipt.
NOT_YET_MEASURED = {
    "inserts": "insert-pocket reachability and retention",
    "threads": "thread engagement and pitch as printed",
    "captive-hardware": "whether the hardware can be placed and stays captive",
    "split-body": "seam registration and the sealing method the plan owes",
    # A motion path is a claim about clearance through a *sweep* -- the part moving
    # along a trajectory without colliding. Every check in this build reads one
    # static pose, and a single pose cannot answer a question about motion. Named
    # explicitly so it is DEFERRED rather than silently implied complete or
    # falling through to a bare "unknown modifier" that says nothing about why.
    "motion_path": "swept-volume clearance along the declared motion path",
}

KNOWN_MODIFIERS = frozenset(SLICER_DEPENDENT) | frozenset(NOT_YET_MEASURED)


def derive(stored: dict[str, Any] | None,
           stale: dict[str, tuple[str, ...]]) -> dict[str, Any]:
    """The status the evidence on disk currently supports.

    `final_status.json` is the record of what a run concluded and stays exactly
    that. What changes is that a reader no longer takes it verbatim: the receipts
    it was issued against either still bind or they do not, and `bindings.broken`
    is what answers that. Everything before this ran `decide` once, mid-run,
    serialized the answer, and every reader afterwards repeated it -- so a
    `VERIFIED` receipt beside a candidate somebody had since rebuilt read as
    current, and nothing anywhere could tell.

    **This is not a second gate.** It re-adjudicates nothing: no check is re-run,
    no threshold is re-applied, and a job whose bindings all hold derives exactly
    what it stored. The only move it can make is downward -- `STALE` in place of a
    success whose evidence moved -- and it cannot make one upward, because there is
    no input here that could turn a `FAILED` into anything else.

    A `FAILED` or `NEEDS_MORE_EVIDENCE` whose bindings broke keeps its own name
    and carries the breakage in `stale`. That is deliberate, and it is the same
    rule the lane cap follows: those are findings, and a finding replaced by
    "this is out of date" is a defect nobody is looking at any more.
    """
    if not isinstance(stored, dict) or not stored.get("final_status"):
        return {
            "derived_status": "NOT_RUN",
            "stored_status": None,
            "allowed_claim": None,
            "stale": {name: list(rows) for name, rows in sorted(stale.items())},
            "reasons": ["no run has concluded in this directory"],
        }

    was = str(stored.get("final_status"))
    broke = stale.get("final_status.json") or ()
    reasons: list[str] = []
    derived = was
    if broke:
        if was in CLAIMS_SUCCESS:
            derived = "STALE"
            reasons.append(
                f"the run concluded {was} and the evidence it was issued against "
                "has moved, so that claim is not current")
        else:
            reasons.append(
                f"{was} stands -- it is a finding this run was entitled to report "
                "-- but the evidence it was issued against has moved")
        reasons.extend(broke)
    for name, rows in sorted(stale.items()):
        if name == "final_status.json":
            continue
        reasons.append(f"{name} no longer binds: {'; '.join(rows)}")
    S.require_enum(derived, DERIVED_STATUS, what="derived_status")
    return {
        "derived_status": derived,
        "stored_status": was,
        "allowed_claim": stored.get("allowed_claim"),
        "stale": {name: list(rows) for name, rows in sorted(stale.items())},
        "reasons": reasons,
    }


# ---------------------------------------------------------------------------
# The report, and the readers underneath it
# ---------------------------------------------------------------------------
#
# `report` is the assembly `design-tool status` renders and `tools/replay.py`
# reads. It used to exist only as text: the command assembled it, printed it,
# and the harness recovered it by redirecting stdout, invoking the command
# surface with `--json` and parsing what it caught. Two adapters over one
# document, separated by a hop that bought neither of them anything.
#
# The readers below sit here rather than in `cli.py` because `report` needs
# them and `cli` imports this module, so this is the only direction that is not
# a cycle. `cli` keeps its own names as aliases of these, which is why no call
# site there moved.

NEXT_ACTION_FILE = "next_action.json"


class Unreadable(Exception):
    """A file the report has to read is on disk and will not parse.

    Raised rather than exited. `report` has two consumers and a function that
    killed the process would be choosing an exit code for both of them;
    `cli.status` is what turns this into the refusal a user sees.
    """


def _json_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def pending_action(work_dir: Path) -> dict[str, Any] | None:
    """The instruction on disk, or None where there is not a readable one."""
    return _json_object(work_dir / NEXT_ACTION_FILE)


def stored(work_dir: Path) -> dict[str, Any] | None:
    """The stored verdict, or None where there is not one to read.

    Tolerant of a file that will not parse, deliberately: `status` has to be able
    to report on a directory whose receipt somebody has broken, and a command
    that raises instead is a command that cannot describe the one state a reader
    most needs described.
    """
    return _json_object(work_dir / "final_status.json")


def active_work_dir(project_dir: Path, project: P.Project) -> Path:
    """Where this formulation writes, resolved without creating anything.

    The active formulation's own directory, not the root's. Reading the root
    while a branch is active would report the sibling's answer as this one's,
    which is the whole class of failure the work directory exists to remove.

    A hand-written `active_alternative` that would leave the project falls back
    to the project root. `validate` names it -- the regex refuses the id and the
    cross-check refuses one nothing declares -- and falling back is what lets
    that problem be written down instead of tracebacking on the way to reporting
    it.
    """
    try:
        return project.work_dir(project_dir)
    except S.PathEscape:
        return Path(project_dir)


def binding_state(work_dir: Path, project: P.Project) -> dict[str, Any]:
    """What this formulation's files say right now -- the instruction's own state."""
    return B.current(work_dir, alternative_id=project.active_alternative or None,
                     model_name=project.model)


def is_superseded(next_action: Any, state: dict[str, Any]) -> bool:
    """Whether an instruction on disk still describes the project it sits in.

    An instruction written before this field existed carries no digest and cannot
    vouch for itself, which is the condition it was added for; it is reported
    superseded rather than believed.
    """
    if not isinstance(next_action, dict):
        return False
    return next_action.get("state_sha256") != S.payload_hash(state)


def alternative_dir(project_dir: Path, alternative_id: str | None) -> Path | None:
    """Where one formulation's own files live, or None if the id would escape.

    The same join `Project.work_dir` makes, through the same resolver, for an
    alternative that is not the active one. `report` needs it because a status is
    derived *per alternative* -- a report that could only answer for whichever
    branch happens to be checked out is a report that cannot compare two.
    """
    if alternative_id is None:
        return Path(project_dir)
    try:
        return S.resolve_within(Path(project_dir),
                                f"{P.ALTERNATIVES_DIR}/{alternative_id}",
                                what="alternative directory")
    except S.PathEscape:
        return None


def derived_at(project_dir: Path, project: P.Project,
               alternative_id: str | None) -> dict[str, Any]:
    """The status one formulation's own receipts currently support."""
    where = alternative_dir(project_dir, alternative_id)
    if where is None or not where.is_dir():
        return derive(None, {})
    return derive(
        stored(where),
        B.broken(where, evidence_dir=project_dir,
                 alternative_id=alternative_id, model_name=project.model))


def report(project: P.Project, project_dir: Path) -> dict[str, Any]:
    """What the evidence on disk currently supports, as a document.

    Nothing here prints and nothing here chooses an exit code: the return value
    is the whole answer, and the two things that render it -- the terminal
    output of `design-tool status` and the JSON its `--json` flag emits -- are
    both in `cli.status`, beside the exit code it derives from the same value.

    Every value is JSON-representable, because one of the renderings is
    `json.dumps` and the other is what a reader sees. A field that could not
    survive that call would be a field the command could never have printed.
    """
    work_dir = active_work_dir(project_dir, project)
    pending = work_dir / NEXT_ACTION_FILE
    next_action = None
    if pending.is_file():
        try:
            next_action = json.loads(pending.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise Unreadable(f"{NEXT_ACTION_FILE} is not valid JSON: {exc}") from exc

    # Read, never written. `status` reporting on a job it had invalidated on the
    # way past would be a command that changes what it is describing, and the
    # honest report of a broken binding is that it is broken -- not that the
    # receipt carrying it has been tidied away.
    state = binding_state(work_dir, project)
    stale = B.broken(work_dir, evidence_dir=project_dir,
                     alternative_id=project.active_alternative or None,
                     model_name=project.model)
    final_payload = stored(work_dir)
    derived = derive(final_payload, stale)
    superseded = is_superseded(next_action, state)
    # Per alternative, and not only for whichever one is active. Each
    # formulation's receipts sit in its own directory and are checked against
    # that directory's own bindings, so switching branches is not the price of
    # finding out where the other one stands.
    alternatives = []
    # The union: the shared root plus every declared alternative. `branch` writes
    # no row for the root -- it is a formulation by having a directory, a
    # proposal, a contract and its own receipts, not by being declared -- and
    # iterating `project.alternatives` alone reported two formulations of the
    # recorded knob while the `cost` block below reported three. One report, two
    # answers to "what is this job". `docs/defects.md` D26.
    #
    # Synthesised here and not in `project.json`: a declared row for the root
    # would make it a thing a user could reject or supersede, and would move
    # what every existing project deserialises to.
    root_row = P.Alternative(alternative_id=B.ROOT_ALTERNATIVE,
                             reason="what the alternatives were branched from")
    for row in (root_row, *project.alternatives):
        at = None if row.alternative_id == B.ROOT_ALTERNATIVE else row.alternative_id
        other = (derived if at == project.active_alternative
                 else derived_at(project_dir, project, at))
        # All five, not two. `derived_at` computes `allowed_claim`, `stale` and
        # `reasons` as well, and dropping them made per-formulation staleness
        # unreadable from the report -- `tools/replay.py` had to issue `branch
        # --activate` and `status` once per formulation to recover what one call
        # already knew.
        alternatives.append({**row.as_dict(),
                             "status": other["derived_status"],
                             "stored_status": other["stored_status"],
                             "allowed_claim": other.get("allowed_claim"),
                             "stale": sorted(other.get("stale") or {}),
                             "reasons": list(other.get("reasons") or ())})
    # What FALLBACK means to a reader, which is the only thing that separates it
    # from ACTIVE. A retained formulation is the answer to "and if this one does
    # not work out", so it is named exactly when that question is live: the
    # current formulation has no claim it may make. Naming it is not comparison
    # and not selection -- Release 4 owns both -- it is reading a status this
    # report already derives and honouring a disposition the user declared.
    fallbacks = [{"alternative_id": row["alternative_id"], "status": row["status"],
                  "reason": row["reason"]}
                 for row in alternatives if row["disposition"] == "FALLBACK"]
    # What each formulation has spent, and what each one beyond the root added.
    # Per alternative for the same reason the status is: a cost read only for
    # whichever branch happens to be active is a number that cannot answer "what
    # did exploring the second concept cost", which is the question
    # ARCHITECTURE.md 15.2 asks and the one the vent-ball exercise had to answer
    # with a stopwatch.
    events = LC.read(project_dir)
    costs = {}
    for key in [B.ROOT_ALTERNATIVE] + [row.alternative_id
                                       for row in project.alternatives]:
        where = alternative_dir(project_dir,
                                None if key == B.ROOT_ALTERNATIVE else key)
        if where is not None and where.is_dir():
            costs[key] = COST.totals_at(where)
    cost_report = COST.compare(costs,
                               restarts=COST.restarts_by_alternative(events))
    # One validate() call, read in two registers: `problems` keeps its shape as
    # the sentences a person reads, `findings` carries the code, field path and
    # severity a caller matches on. Calling validate twice would be two answers
    # to one question and the cheaper of the two ways to make them disagree.
    problems = project.validate(project_dir, require_buildable=False)
    return {
        "job_id": project.job_id,
        "source_mode": project.source_mode,
        "consequence": project.consequence,
        "alternative": project.active_alternative,
        "alternatives": alternatives,
        "fallbacks": fallbacks,
        # Which run this formulation currently *is*, content-derived, so that a
        # caller can carry one value instead of re-deriving the binding map --
        # and so that two byte-identical siblings are still two runs. See
        # `bindings.identity` for why it is not an invocation counter.
        "run_id": B.identity(state),
        # What was deliberately done to this job's formulations, oldest first.
        # Bound by nothing: appending to it cannot make a receipt stale, which
        # is what lets it record the one thing scoped invalidation cannot.
        "lifecycle": events,
        # What the job spent, per formulation and in total, and what each
        # formulation beyond the root added. Bound by nothing, for the same
        # reason `lifecycle` is: see `pipeline/cost.py`.
        "cost": cost_report,
        "route": project.route,
        "route_rationale": project.route_rationale,
        "required_reviews": list(project.required_reviews),
        # ADR 0003 decision 1: an assumption is permitted and is *findable*.
        # A datum somebody chose is not a defect, so `validate` says nothing
        # about it -- every caller of it here refuses the run on a non-empty
        # list, warning severity included, and the ADR says plainly that a job
        # whose datum has no provenance is not refused. It belongs where a
        # person asks what the job is resting on instead. Release 6 is where an
        # assessment has to name the ones its conclusion rested on.
        # Each row carries who settles it and what settling it means, because a
        # list of bare ids is the `note` this replaced -- and its provenance,
        # because the two kinds of assumption are not the same thing. A `CHOSEN`
        # number was picked deliberately; a blank one was never recorded at all,
        # and ADR 0003 decision 1 is about telling those apart. A row without it
        # left no consumer able to.
        "assumptions": [{"datum_id": row.datum_id,
                         "provenance": row.provenance,
                         "owner": row.owner, "settled_by": row.settled_by}
                        for row in project.datums if row.is_assumption],
        "problems": F.messages(problems),
        "findings": [issue.to_dict() for issue in problems],
        "waiting_for": next_action,
        # Whether that instruction still describes this project. An instruction
        # is as stale-able as a receipt and used to be the only one of the two
        # that could not say so.
        "waiting_for_superseded": superseded,
        "final_status": derived["derived_status"],
        "stored_status": derived["stored_status"],
        "stale": derived["stale"],
        "allowed_claim": derived["allowed_claim"],
        "lane_status": (final_payload or {}).get("lane_status"),
        "execution_plan_sha256": (final_payload or {}).get("execution_plan_sha256"),
        # This formulation's own, from its own final status. The shared project
        # file no longer carries a copy for the root to be read out of.
        "bindings": (final_payload or {}).get("artifact_hashes") or {},
        # And what those hashes are being checked against right now.
        "state": state,
    }


def _promotable(report: dict[str, Any] | None, kind: str,
                envelope: R.ReviewEnvelope | None) -> bool:
    """Bound to the current request, and itself a complete, closed answer.

    Envelope equality says the report answers this request. It says nothing
    about what the answer is: a partial report, or a PASS that carries its own
    contradictions -- defects, failure modes, missing evidence, an empty
    summary -- was refused when it was first validated, and it is refused
    again here. The status layer is the last place a malformed pass can be
    caught, so it re-runs the checks rather than trusting that somebody else
    did.
    """
    if envelope is None or not isinstance(report, dict):
        return False
    if not R.is_bound(report, kind, envelope.digest()):
        return False
    try:
        if kind == "safety":
            _safety_review.validate(report)
            R.require_safety_pass_closed(report)
        else:
            _verification_review.validate(report)
            R.require_verification_pass_closed(report)
    except (S.SchemaError, R.ReviewError):
        return False
    return True


def manufacturing(contract: Contract, commission_report: dict[str, Any]) -> dict[str, Any] | None:
    """What the modifiers require, and how much of it geometry can settle."""
    if not contract.modifiers:
        return None

    predicates: list[dict[str, Any]] = []
    for modifier in contract.modifiers:
        if modifier in SLICER_DEPENDENT:
            predicates.append({
                "modifier": modifier, "predicate": SLICER_DEPENDENT[modifier],
                "result": "DEFERRED",
                "reason": "no slicer adapter is configured; this stack is uv, build123d, "
                          "trimesh and manifold3d, none of which produces toolpaths"})
        elif modifier in NOT_YET_MEASURED:
            predicates.append({
                "modifier": modifier, "predicate": NOT_YET_MEASURED[modifier],
                "result": "DEFERRED",
                "reason": "no check in this build measures it yet"})
        else:
            predicates.append({
                "modifier": modifier, "predicate": "unknown modifier",
                "result": "BLOCKED",
                "reason": f"{modifier!r} is not one of {sorted(KNOWN_MODIFIERS)}; a "
                          "modifier nobody implements cannot be reported as handled"})

    deferred = [p for p in predicates if p["result"] == "DEFERRED"]
    blocked = [p for p in predicates if p["result"] == "BLOCKED"]
    overall = "BLOCKED" if blocked else ("DEFERRED" if deferred else "SATISFIED")
    return {
        "schema_version": S.MANUFACTURING_SCHEMA,
        "job_id": contract.job_id,
        "contract_sha256": contract.contract_hash(),
        "modifiers": list(contract.modifiers),
        "slicer_adapter": None,
        "overall": overall,
        "predicates": predicates,
        "commission_verdict": commission_report["verdict"],
    }


# How much of a check's own error message the claim string carries. Long enough
# for a module name and a path, short enough that a summary line stays a summary.
_REASON_CHARS = 160


def _unavailable(commission_report: dict[str, Any]) -> list[dict[str, Any]]:
    """The declared checks that never ran, with the code that says why.

    `commission_report` keeps the distinction perfectly already -- `ran: false`,
    `status: UNAVAILABLE`, `measured: null`, `error_code`, and the exception as
    the reason -- and nothing carried it any further. `final_status.json` said
    only "rejected by independent verification" and the CLI summary said the
    same, so a user who did not open `commission_report.json` learned that a
    reviewer rejected their part rather than that the tool could not read their
    primary source. Those demand different actions, and only one of them is the
    user's fault.
    """
    rows: list[dict[str, Any]] = []
    for check in commission_report.get("checks") or []:
        if not isinstance(check, dict) or check.get("status") != "UNAVAILABLE":
            continue
        rows.append({"check_id": check.get("check_id"),
                     "feature_id": check.get("feature_id"),
                     "error_code": check.get("error_code"),
                     "reason": (check.get("error_message") or check.get("reason")
                                or "")[:_REASON_CHARS],
                     "result": check.get("result")})
    return rows


def _names(rows: list[dict[str, Any]]) -> str:
    return "; ".join(f"{r['check_id']} ({r['error_code']}): {r['reason']}"
                     for r in rows)


def decide(*, contract: Contract, commission_report: dict[str, Any],
           screening: dict[str, Any], manufacturing: dict[str, Any] | None,
           safety: dict[str, Any] | None, artifact: dict[str, Any],
           verification: dict[str, Any] | None, updated_utc: str,
           route: str = "DIRECT",
           execution_plan_sha256: str | None = None,
           lane_status: str = "AVAILABLE", lane_note: str = "",
           safety_envelope: R.ReviewEnvelope | None = None,
           verification_envelope: R.ReviewEnvelope | None = None,
           datum_conflicts: Sequence[dict[str, Any]] = ()) -> dict[str, Any]:
    reasons: list[str] = []
    verdict = commission_report["verdict"]
    witness = commission_report.get("witness") or {}
    rendered = bool(witness.get("rendered"))

    if verdict == "FAIL":
        final, claim = "FAILED", "the geometry does not match its contract"
        reasons.append("commissioning failed")
    elif verdict == "ESCALATE":
        final = "NEEDS_MORE_EVIDENCE"
        claim = "a check could not run and the contract said to escalate rather than pass"
        reasons.append("commissioning escalated")
    elif screening["overall"] == "ANOMALY":
        final = "NEEDS_MORE_EVIDENCE"
        claim = "screening found geometry the contract does not explain"
        reasons.append("screening reported an anomaly")
    elif screening["overall"] == "INDETERMINATE":
        final = "NEEDS_MORE_EVIDENCE"
        claim = "a screening detector could not run, so the part was not broadly screened"
        reasons.append("screening was indeterminate")
    else:
        final, claim = "COMMISSIONED", "geometrically commissioned against its contract"
        if not screening.get("calibrated", False) and verification is None:
            # The plan's hard gate, and it has to move the status or it is a
            # string. An uncalibrated screen plus nobody looking means the one
            # question no declared check can ask went unasked -- and the measured
            # miss rate on fused undeclared material is 30% -- measured on a
            # corpus whose mutants are actually fused to the part, which the
            # first one was not.
            final = "NEEDS_MORE_EVIDENCE"
            claim = ("the geometry matches its contract, but the broad screen is "
                     "uncalibrated and nobody independent looked, so undeclared "
                     "geometry cannot be ruled out. Supply a verifier, or say plainly "
                     "that nothing has looked at this part.")
            reasons.append("screening is uncalibrated and no independent look ran")
        elif not screening.get("calibrated", False):
            # Only claim the look covered it if there was something to look at.
            reasons.append(
                "screening is uncalibrated; the independent review is what covers "
                "undeclared geometry here"
                + ("" if rendered else " -- and it saw no images, only numbers"))

    if final in ("COMMISSIONED", "VERIFIED"):
        unavailable_sections = [s for s in witness.get("sections", [])
                                if s.get("status") == "UNAVAILABLE"]
        if unavailable_sections:
            final = "NEEDS_MORE_EVIDENCE"
            claim = ("witness section(s) could not be measured; the part was not "
                     "fully verified")
            reasons.append(
                f"witness sections unavailable: {len(unavailable_sections)} section(s) "
                f"at z={[s.get('z') for s in unavailable_sections]}")
        elif manufacturing and manufacturing["overall"] == "DEFERRED":
            unproven = ", ".join(p["predicate"] for p in manufacturing["predicates"]
                                 if p["result"] == "DEFERRED")
            final = "COMMISSIONED"
            claim = f"geometrically commissioned; not verified: {unproven}"
            reasons.append("a required manufacturing predicate is deferred")
        elif manufacturing and manufacturing["overall"] == "BLOCKED":
            final, claim = "FAILED", "a manufacturing predicate is blocked"
            reasons.append("manufacturing blocked")

    if contract.consequence == "CONSEQUENTIAL":
        # A safety review of a part nobody could see is a review of numbers. The
        # renderer is not on the core path, so this is the ordinary case rather
        # than an exotic one, and it used to pass in silence: witness.renderer
        # recorded "unavailable" and no consumer read it.
        if not rendered:
            reasons.append("no renders were produced, so the safety reviewer saw "
                           "numbers and no images")
        if safety is None or not _promotable(safety, "safety", safety_envelope):
            final = "NEEDS_MORE_EVIDENCE"
            claim = "consequential, and no final safety verification was performed"
            reasons.append("safety verification is mandatory and absent, unbound "
                           "or invalid")
        elif safety["decision"] == "BLOCK":
            final = "FAILED"
            claim = f"blocked on safety review: {safety['summary'][:160]}"
            reasons.append("safety review returned BLOCK")
        elif safety["decision"] == "NEEDS_MORE_EVIDENCE":
            final = "NEEDS_MORE_EVIDENCE"
            claim = "the safety reviewer needs evidence this run did not produce"
            reasons.append("safety review needs more evidence")
        elif not rendered and final in ("COMMISSIONED", "VERIFIED"):
            final = "NEEDS_MORE_EVIDENCE"
            claim = ("consequential, and the safety review saw no images -- install the "
                     "render extra and re-run, or say plainly that nobody has looked "
                     "at this part")
        elif final == "COMMISSIONED" and verification is None:
            # A passing safety review is not independent verification of the
            # geometry -- it reviewed hazards, not whether the part matches the
            # brief. VERIFIED still requires a verifier.
            reasons.append("safety review passed; no independent geometric verification ran")

    if verification is not None:
        if not _promotable(verification, "verification", verification_envelope):
            final = "NEEDS_MORE_EVIDENCE"
            claim = "independent verification is unbound or invalid and cannot be trusted"
            reasons.append("verification report is unbound or invalid")
        else:
            decision = verification.get("decision")
            if decision == "REJECT":
                # A rejection must move the status. Leaving it at COMMISSIONED read
                # as "geometrically commissioned against its contract" while an
                # independent reader had just said the part is wrong -- the claim was
                # true about the geometry and silent about the finding, which is the
                # worst combination a receipt can have.
                defects = verification.get("defects") or []
                loops = sorted({d.get("owning_loop", "?") for d in defects})
                final = "FAILED"
                claim = (f"rejected by independent verification ({len(defects)} defect(s), "
                         f"owned by {', '.join(loops) or 'an unnamed loop'}): "
                         f"{verification.get('summary', '')[:120]}")
                reasons.append("independent verification returned REJECT")
            elif decision == "NEEDS_MORE_EVIDENCE" and final in ("COMMISSIONED", "VERIFIED"):
                final = "NEEDS_MORE_EVIDENCE"
                claim = ("independent verification could not decide on the evidence this "
                         "run produced")
                reasons.append("independent verification needs more evidence")
            elif decision == "PASS" and final == "COMMISSIONED":
                if manufacturing and manufacturing["overall"] == "DEFERRED":
                    reasons.append("verified geometrically; a manufacturing predicate is "
                                   "still deferred, so the job stays COMMISSIONED")
                else:
                    final = "VERIFIED"
                    # Say which kind of verification it was. The verifier is asked
                    # "is anything visible in the witnesses that no contract row
                    # declares?" -- with no images it can only answer from numbers,
                    # and undeclared geometry is exactly what numbers do not cover.
                    # The unqualified claim went out on jobs where nothing had been
                    # seen, over a reason that read "the independent look is what
                    # covers undeclared geometry here". There was no look.
                    if rendered:
                        claim = "independently verified against its contract"
                    else:
                        claim = ("independently verified against its contract on "
                                 "measurements alone -- no images were rendered, so "
                                 "nobody has seen this part")
                        reasons.append("verification saw no images; undeclared geometry "
                                       "is not covered by a numeric check")

    if datum_conflicts:
        # ADR 0003 decision 6. A datum and a measurement of it disagree, and §6.5
        # says that stays a conflict until somebody resolves it deliberately. So
        # the claim is withheld rather than picked: neither value is preferred,
        # neither is overwritten, and both travel in the payload below.
        #
        # Shaped exactly like the lane cap underneath, and for the same reason. The
        # reason is appended on every verdict, so a FAILED receipt still says the
        # conflict is there -- a reader who only learns of it when the job would
        # otherwise have succeeded learns it at the worst possible moment. But only
        # a *successful* verdict is downgraded: FAILED and NEEDS_MORE_EVIDENCE are
        # findings this run is entitled to report, and replacing them with a
        # conflict notice would hide a real defect behind a bookkeeping one.
        named = ", ".join(f"{row['datum_id']} vs {row['measurement_requirement']}"
                          for row in datum_conflicts)
        reasons.append(
            f"{len(datum_conflicts)} datum/evidence conflict(s) unresolved: {named}")
        if final in CLAIMS_SUCCESS:
            final = "NEEDS_MORE_EVIDENCE"
            claim = (
                f"{len(datum_conflicts)} datum(s) disagree with a measurement of "
                "the same quantity, and nothing has resolved which is right. What "
                f"ran is on disk: {claim.rstrip('. ')}. Both values are recorded "
                "under datum_conflicts; correct one of them, or say which is "
                "authoritative, and re-run.")

    if lane_status != "AVAILABLE":
        # Recorded on every run of an experimental lane, whatever the verdict, so
        # the limitation is legible on a FAILED receipt too -- a reader who only
        # sees it when the job would otherwise have succeeded learns it at the
        # worst possible moment.
        reasons.append(lane_note)
        if final in ("COMMISSIONED", "VERIFIED"):
            # The deterministic work is done and on disk; what is withheld is the
            # claim. Downgrading only a successful verdict is deliberate: FAILED
            # and NEEDS_MORE_EVIDENCE are findings this lane *is* entitled to
            # report, and overwriting them would hide a real defect behind an
            # architectural caveat.
            #
            # The cap's own name carries through rather than collapsing to one
            # value: `UNSUPPORTED` means no stage is coming and
            # `EXPERIMENTAL_UNAVAILABLE` means one is, and a caller that cannot
            # tell them apart either waits forever or gives up too early.
            final = lane_status
            # "yet" only where a stage is actually coming. On `UNSUPPORTED` it
            # would be the same false promise the shared status name used to make.
            when = "yet" if lane_status == "EXPERIMENTAL_UNAVAILABLE" else "at all"
            claim = (f"not claimable on this lane {when} -- {lane_note}. What did "
                     f"run is on disk: {claim}.")

    # Last, and after the lane cap, because this is true of every verdict above
    # and none of them owns it. A rejection, a failure and a capped success can
    # each sit beside a check that never ran, and the sentence a user reads has to
    # carry both -- the reason the part was refused, and the fact that one of the
    # instruments never measured.
    unavailable = _unavailable(commission_report)
    if unavailable:
        named = _names(unavailable)
        reasons.append(f"{len(unavailable)} declared check(s) could not run: {named}")
        claim = (f"{claim.rstrip('. ')}. Separately, {len(unavailable)} declared "
                 f"check(s) never ran and measured nothing: {named}. That is this "
                 f"tool failing to measure, not a finding about the part.")

    S.require_enum(final, S.FINAL_STATUS, what="final_status")
    return {
        "schema_version": S.STATUS_SCHEMA,
        "job_id": contract.job_id,
        "consequence": contract.consequence,
        # Threaded, not assumed. It was the literal "DIRECT" from the days when
        # DIRECT was the only route, so every FITTED job's authoritative receipt
        # said it had cost no dispatches. Nothing read the field, which is how it
        # survived -- a receipt nobody reads is still a receipt somebody may.
        "route": route,
        # Which plan produced this receipt. The route above is only trustworthy
        # if it is the one that was compiled: the runner used to re-derive its
        # own and write that instead, so a FITTED job's status said "DIRECT"
        # while `route_decision.json` beside it said FITTED.
        "execution_plan_sha256": execution_plan_sha256,
        "lane_status": lane_status,
        "backend": contract.backend,
        "template": f"{contract.template}@{contract.template_version}",
        "domain_id": contract.domain_id,
        "commission_verdict": verdict,
        "screening": screening["overall"],
        "screening_calibrated": screening.get("calibrated", False),
        "witnesses_rendered": rendered,
        "manufacturing": manufacturing["overall"] if manufacturing else None,
        # `.get`, not subscript: a report that reached this layer without a
        # decision was refused above, and the receipt's own serialization must
        # not KeyError on the way out.
        "verification": verification.get("decision") if verification else None,
        "safety_verification": safety.get("decision") if safety else None,
        "final_status": final,
        "allowed_claim": claim,
        # Structured beside the sentence, so a caller that reads JSON does not
        # have to parse prose to find out which instrument failed.
        "unavailable_checks": unavailable,
        # Both declarations, with no winner picked. ADR 0003 decision 6: a caller
        # asking "why is this not COMMISSIONED" gets the two numbers and the two
        # provenances rather than a sentence it would have to parse -- and, because
        # the row carries `state: UNRESOLVED`, cannot mistake the report for a
        # resolution.
        "datum_conflicts": [dict(row) for row in datum_conflicts],
        "reasons": reasons,
        "artifact_hashes": {"contract": artifact["contract_sha256"],
                            "stl": artifact["stl_sha256"],
                            "step": artifact.get("step_sha256"),
                            "source": artifact["source_sha256"]},
        "updated_utc": updated_utc,
    }
