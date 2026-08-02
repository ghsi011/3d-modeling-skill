#!/usr/bin/env python3
"""L1 — a recorded engineering job, replayed through the current command surface.

    uv run pytest benchmarks/replays              # the suite; ~35 s, two cases
    uv run python tools/replay.py --list
    uv run python tools/replay.py --run    modify-ball-flange-flat
    uv run python tools/replay.py --reseal modify-ball-flange-flat  # inputs moved
    uv run python tools/replay.py --record modify-ball-flange-flat  # re-freeze

`ROADMAP.md` section 5.1 defines three tiers and this repository shipped three
releases with only two of them. L0 is `tools/test_diagnosis_l0.py` and the unit
suite: fast component fixtures, run on every commit. L2 is blind live
evaluation, deliberately manual. **L1 is a recorded engineering output replayed
through the current system with no live AI call**, and nothing here replayed a
*job*. `test_diagnosis_l0.py` replays five artifacts through `diagnose`, which is
one component; `pipeline/test_frozen.py` runs `runner.run` on parameters a test
made up, which is the runner without the command surface, without a project,
without a proposal, without the confined build and without a review round trip.

So the gap this closes is narrow and specific: **something drives a whole job
from a recording and compares the result against what was recorded.**

---

## What a replay is allowed to assert, and why it is not more

Almost everything in this pipeline is hash-bound on purpose. A naive replay that
diffed receipts byte for byte would go red on a new field, a protocol bump, a
reworded finding and a dependency upgrade -- every one of them a legitimate
change -- and it would be deleted inside a month, which is worse than not having
one. So the assertions are layered, and each layer is here because it fails for
a different reason.

**Binding, in order of how much they are worth.**

* *The exit codes, in sequence.* `design-tool` answers a caller in exit codes,
  and `[3, 3, 3]` -- pause for safety, pause for verification, finish needing
  more evidence -- is a different job from `[3, 0]`. This is the cheapest
  assertion here and the one that catches a resumption regression outright.
* *The final status, and the verdicts under it.* `final_status`,
  `commission_verdict`, `screening`, `screening_calibrated`, `safety`,
  `verification`, `route`, `backend`, `lane_status`. These are the system's
  answers. Any move is a behaviour change and somebody has to look at it.
* *Per-check verdicts.* `check_id -> (result, status, ran)`, exactly. A check
  that stops running, starts escalating, or quietly disappears from the report is
  the failure mode a status assertion alone cannot see: coverage is a fraction,
  and a fraction stays 1.0 when the declared set shrinks with the covered one.
* *Measured values, inside the band the contract itself declares for them.* Not
  equality. A mesher upgrade moves the fourth decimal of a section area and that
  is not a regression; a change that moves a measurement past the band the
  acceptance contract says matters is one. Where a row declares a zero band --
  the support ceiling does -- the band falls back to the same 0.5% the pipeline's
  own `contract.area_tolerance` uses, plus the rounding the receipt already
  carries, because comparing two floats at zero tolerance is byte equality with
  extra steps.
* *The shape of the receipt set.* Which files a run wrote, by name. A route that
  silently stops writing a receipt is exactly what `test_frozen` was built for,
  one level up.
* *The reviews answered, in order, and that every one came from the recording.*
  See the dispatch section below.
* *Four hashes, and only where the hash is the property.* Every one is an
  equality between two values computed in the same replay, never a literal pinned
  in a file, so none of them churns:
  1. the plan digest the reviewer's envelope binds equals the plan digest on
     `final_status.json` -- the plan the reviewer was shown is the plan that ran;
  2. the contract digest on `artifact_manifest.json` equals the one
     `final_status.json` bound -- the receipt describes the contract it was
     judged against;
  3. the envelope echoed on each review report equals the envelope on the packet
     that asked for it -- the answer is bound to the question;
  4. two independent replays of one case produce the same `candidate.stl` digest
     and the same preservation `sample_plan_sha256` -- determinism, which is the
     property that makes a review round trip possible at all, and the one thing
     here that a *literal* hash could never test because it would have to be
     re-pinned on every legitimate geometry change.

**Advisory, reported and never failing on its own.** `reasons` and
`allowed_claim` are prose written for a human. They are recorded verbatim,
because a maintainer reading `expected.json` should be able to see what the run
actually said, and they are compared and printed as advisories -- a reworded
sentence is not a regression and must not be able to stop a build.

**Deliberately not asserted at all.** The bytes of any receipt; any literal
sha256 of a receipt, packet, envelope, contract or artifact; `findings` text;
`lane_note` text; timings; the witness images. Every one of them moves for
reasons that have nothing to do with whether the job still behaves.

## Why the review answer is re-bound rather than replayed verbatim

A stored review response echoes a `review_envelope` that binds the packet, the
contract, the execution plan, the evidence digests, the protocol version and the
alternative. That is the right design: in a real run it is what stops an answer
to question A being promoted as an answer to question B. It also means a stored
response cannot survive *any* legitimate change to the question, which is why the
real vent-ball run has two 164-byte `safety_verification_report.json` files whose
whole content is `review envelope mismatch`.

So a case records the reviewer's **judgement** -- the decision, the summary, the
defects, the concerns -- with no envelope at all, and the harness stamps the
envelope of the packet the current run just wrote. That is exactly what a human
reviewer does; the only thing that is recorded rather than fresh is the
judgement, which is the part a live AI call would have produced.

Re-binding would be a hole if nothing checked that the binding still bites, so
two things guard it. The harness asserts that the envelope on each review report
is the envelope of the packet that asked for it -- if the runner ever accepted an
answer that did not match, the replay fails. And the L1 suite carries an
adversarial case that stamps a *wrong* envelope and requires the run to refuse
it, write no final status, and exit non-zero.

## Zero live dispatches, asserted rather than assumed

Three separate facts, because no one of them is enough:

* `materialise` writes no `reviews/` directory, so every response file on disk at
  the end is one this harness wrote, and it can only write one from a recording.
  The harness re-checks that set at the end of the play.
* A review kind the case holds no judgement for raises `NoRecordedAnswer`. The
  replay fails; it does not quietly leave the job paused.
* `AGENT_COMMISSION` is fatal. That instruction is the pipeline asking an agent
  to author a proposal and a model -- it *is* the live dispatch on the `CUSTOM`
  lane -- and a case that provokes one is a case missing its recorded designer
  output rather than a passing replay of a paused job.

## Where the cases live, and why there

`benchmarks/replays/<case-id>/`, beside `fixtures/` and `references/` and inside
neither.

`tools/fixtures.py` keeps a wall: everything under `benchmarks/fixtures/<id>/` is
material a design agent may read, and the withheld answer lives under
`benchmarks/references/` so that it is not one `cd ..` from the request. A replay
case is entirely on the grader's side of that wall -- it carries the design
proposal, the model and the reviewer's answers -- so putting it under
`fixtures/<id>/` would tear the wall down, and putting it under `references/<id>/`
would mix a live harness in with vendored immutable evidence. A third sibling
leaves both alone.

Source geometry is not copied here. It is named by fixture id and index and
resolved through `tools/fixtures.py`, which verifies size and SHA-256 on the way
past, so a case cannot silently be replayed against different bytes -- and a case
whose source is an `ExternalFile` this machine does not have skips, exactly as
the L0 set does.

## What is frozen, and at which commit

Every `expected.json` here is recorded at the commit that added it, on purpose.

The alternative was available: two completed real runs exist on disk, and the
`vent-ball-combine-r1` exercise is a full recording with two alternatives and a
closed review round trip. It is not the source of these expectations, for four
reasons. It costs about 876 s and 24 GB of RAM per run against a section 4.4
budget of two minutes for the whole L1 suite, and one run in eleven died in the
allocator. It ran at `2721ffe`, before two later slices. Its root
`final_status.json` was deleted by its own revision-2 bump, so the only complete
receipt set it has is an archive copy rather than a resumable project. And two of
the three defects behind its terminal `FAILED` are *instrument* failures -- a
missing STEP reader and an alignment transform that was bound but not applied --
which this repository intends to fix, so pinning that run's expectations would
have built a fixture that goes red on the day the bug is repaired.

What *is* taken from it is what survives a change of scale and is real: the
recorded request, the `MODIFY`-with-an-edit-scope shape, and the source artifact
itself -- `ball_male_17mm.stl`, the same bytes that run consumed, hash-verified
through the fixture register.

An expectation recorded at the current commit catches drift and nothing else,
which is the honest thing for it to do. When a change to the pipeline
legitimately moves one, re-record it with `--record` and put the diff in the
review; that diff is the point.
"""
from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import io
import json
import shutil
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
CASES_ROOT = REPO_ROOT / "benchmarks" / "replays"

sys.path.insert(0, str(REPO_ROOT / "tools"))
sys.path.insert(0, str(REPO_ROOT / "skills" / "3d-modeling" / "scripts"))

import fixtures as FX                                                # noqa: E402

CASE_FILE = "case.json"
EXPECTED_FILE = "expected.json"
INPUT_DIR = "inputs"
JUDGEMENT_DIR = "judgements"
CASE_SCHEMA = 1
EXPECTED_SCHEMA = 1

# The band a replay allows two *measurements* of one quantity to differ by when
# the contract row itself declares none. 0.5% is not invented here: it is the
# relative band `pipeline.contract.area_tolerance` already computes for a section
# area, so a replay is asking the same question the gate asks. The floor is the
# rounding `commission_report.json` already applies to every measured value, so
# a difference smaller than the receipt can express is not a difference.
REPLAY_RELATIVE_BAND = 0.005
REPLAY_ABSOLUTE_FLOOR = 1e-3

# Digests of deterministic *plans*, carried inside a measured value. They are
# compared by the determinism test -- two replays of one case must produce the
# same plan -- and never against a value recorded at another commit, because a
# plan-version bump legitimately moves every one of them.
VOLATILE_KEYS = frozenset({"evidence_sha256", "sample_plan_sha256"})

BINDING = "BINDING"
ADVISORY = "ADVISORY"


class ReplayError(RuntimeError):
    """The case cannot be replayed as it stands. Never a comparison failure."""


class CaseMismatch(ReplayError):
    """A recorded input is present and is not the input the case recorded.

    A failure and not a skip, for the reason `fixtures.FixtureMismatch` gives:
    every expectation in `expected.json` was recorded against the recorded bytes,
    so a case whose inputs moved is a case whose expectations describe something
    else.
    """


class NoRecordedAnswer(ReplayError):
    """The run asked for a review this case holds no judgement for.

    Fails closed and loudly. The alternative -- leaving the job paused and
    reporting whatever partial state it reached -- is a replay that quietly stops
    exercising the thing it was built for.
    """


class LiveDispatchRequired(ReplayError):
    """The run asked an agent to author something. A replay cannot answer that."""


@dataclasses.dataclass(frozen=True)
class SourceRef:
    """A supplied artifact, named through the fixture register rather than copied.

    `fixture_id` and `index` address `tools/fixtures.py`, which verifies size and
    SHA-256 before handing back a path. `as_name` is what the recorded
    `project.json` calls the file, so the two cannot drift.
    """
    fixture_id: str
    index: int
    as_name: str


@dataclasses.dataclass(frozen=True)
class ReplayCase:
    case_id: str
    use_case: str
    source_mode: str
    consequence: str
    # Repo-relative. The recorded request the job was authored against, read from
    # where it already lives: a second copy of one record is two records.
    request: str
    sources: tuple[SourceRef, ...]
    # Token -> project-relative filename. Expanded to the materialised absolute
    # path inside `model.py`, because a recorded model cannot carry the path of a
    # temporary directory that does not exist yet.
    substitutions: dict[str, str]
    # The review kinds this case holds a recorded judgement for, in the order the
    # run is expected to ask for them.
    reviews: tuple[str, ...]
    max_invocations: int
    inputs_sha256: dict[str, str]
    recorded_at: str
    provenance: str
    notes: str

    @property
    def directory(self) -> Path:
        return CASES_ROOT / self.case_id

    def judgement(self, kind: str) -> dict[str, Any]:
        path = self.directory / JUDGEMENT_DIR / f"{kind}.json"
        if not path.is_file():
            raise NoRecordedAnswer(
                f"{self.case_id}: the run asked for a {kind} review and this case "
                f"records no {kind} judgement at {path}. A replay answers from a "
                "recording or it does not answer; there is no live call here to "
                "fall back on.")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if "review_envelope" in payload:
            raise ReplayError(
                f"{self.case_id}: the recorded {kind} judgement carries a "
                "review_envelope. It must not: the envelope binds the judgement "
                "to one packet, and a recorded one would bind it to a run that "
                "happened at another commit. The harness stamps the current "
                "packet's envelope; see this module's docstring.")
        return payload


# --------------------------------------------------------------------------
# Reading a case
# --------------------------------------------------------------------------

def case_ids() -> tuple[str, ...]:
    if not CASES_ROOT.is_dir():
        return ()
    return tuple(sorted(entry.name for entry in CASES_ROOT.iterdir()
                        if (entry / CASE_FILE).is_file()))


def digest_of(path: Path) -> str:
    """SHA-256 of one file. Public: the suite compares a materialised source
    against the digest the fixture register records for it."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def recorded_files(case_id: str) -> tuple[str, ...]:
    """Every file whose bytes a case's expectations were recorded against.

    Repo-relative, POSIX-spelled, sorted. `case.json` is out because it is where
    the digests live, and `expected.json` is out because it is the recording
    rather than an input to it.
    """
    directory = CASES_ROOT / case_id
    names = []
    for sub in (INPUT_DIR, JUDGEMENT_DIR):
        room = directory / sub
        if not room.is_dir():
            continue
        names += [f"{sub}/{path.name}" for path in sorted(room.iterdir())
                  if path.is_file()]
    return tuple(sorted(names))


def load(case_id: str) -> ReplayCase:
    """The case, with every recorded input verified against its digest.

    Verified here rather than trusted, and the argument is the one
    `tools/fixtures.py` makes about its own manifest: `expected.json` is a
    statement about what these bytes produce, so a case whose `model.py` somebody
    tidied is a case whose recording is no longer true of it.
    """
    path = CASES_ROOT / case_id / CASE_FILE
    if not path.is_file():
        raise ReplayError(f"no replay case named {case_id!r}; known: "
                          f"{', '.join(case_ids()) or '(none)'}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    version = payload.get("schema_version")
    if version != CASE_SCHEMA:
        raise ReplayError(
            f"{case_id}: case.json schema_version {version!r} is not "
            f"{CASE_SCHEMA}; a reader that guesses at an unknown version is "
            "indistinguishable from one that read it correctly")

    case = ReplayCase(
        case_id=case_id,
        use_case=payload["use_case"],
        source_mode=payload["source_mode"],
        consequence=payload["consequence"],
        request=payload["request"],
        sources=tuple(SourceRef(fixture_id=row["fixture_id"], index=int(row["index"]),
                                as_name=row["as"])
                      for row in payload.get("sources", ())),
        substitutions=dict(payload.get("substitutions") or {}),
        reviews=tuple(payload.get("reviews") or ()),
        max_invocations=int(payload["max_invocations"]),
        inputs_sha256=dict(payload["inputs_sha256"]),
        recorded_at=payload["recorded_at"],
        provenance=payload["provenance"],
        notes=payload.get("notes", ""))
    _verify_inputs(case)
    return case


def _verify_inputs(case: ReplayCase) -> None:
    present = set(recorded_files(case.case_id))
    declared = set(case.inputs_sha256)
    if present != declared:
        raise CaseMismatch(
            f"{case.case_id}: the case directory holds "
            f"{sorted(present - declared) or '[]'} that case.json does not record "
            f"and records {sorted(declared - present) or '[]'} that is not there. "
            "Every recorded input is digested, so an undigested one is a file "
            "expected.json was measured against and nobody is checking.")
    for name, expected in sorted(case.inputs_sha256.items()):
        found = digest_of(case.directory / name)
        if found != expected:
            raise CaseMismatch(
                f"{case.case_id}: {name} hashes {found} and case.json records "
                f"{expected}. Every expectation in {EXPECTED_FILE} was recorded "
                "against the recorded bytes. Re-record the case if the change was "
                "meant.")


def expected(case_id: str) -> dict[str, Any]:
    path = CASES_ROOT / case_id / EXPECTED_FILE
    if not path.is_file():
        raise ReplayError(
            f"{case_id}: no {EXPECTED_FILE}. Record one with "
            f"`uv run python tools/replay.py --record {case_id}`.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != EXPECTED_SCHEMA:
        raise ReplayError(
            f"{case_id}: {EXPECTED_FILE} schema_version "
            f"{payload.get('schema_version')!r} is not {EXPECTED_SCHEMA}")
    return payload


# --------------------------------------------------------------------------
# Laying the job out
# --------------------------------------------------------------------------

def materialise(case: ReplayCase, destination: Path) -> Path:
    """Write the recorded job into a fresh directory, ready to run.

    No `reviews/` directory is created, deliberately. Everything under it at the
    end of a play is something `play` wrote, and `play` can only write a recorded
    judgement -- which is how "no live dispatch" becomes a fact about the
    filesystem rather than an assurance.
    """
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)

    request = REPO_ROOT / PurePosixPath(case.request)
    if not request.is_file():
        raise ReplayError(
            f"{case.case_id}: the recorded request is committed at {case.request} "
            "and is not on disk.")
    shutil.copyfile(request, destination / "brief.md")

    for source in case.sources:
        # Through the register, so size and SHA-256 are checked on the way past
        # and a fixture this machine does not have raises `FixtureUnavailable`,
        # which the suite skips on.
        shutil.copyfile(FX.source_path(source.fixture_id, source.index),
                        destination / source.as_name)

    for name in recorded_files(case.case_id):
        target = destination / PurePosixPath(name).name
        if not name.startswith(f"{INPUT_DIR}/"):
            continue
        text = (case.directory / name).read_text(encoding="utf-8")
        for token, relative in sorted(case.substitutions.items()):
            text = text.replace(token,
                                str(destination / relative).replace("\\", "\\\\"))
        target.write_text(text, encoding="utf-8")
    return destination


# --------------------------------------------------------------------------
# Playing it
# --------------------------------------------------------------------------

@dataclasses.dataclass
class Play:
    project_dir: Path
    exit_codes: list[str | int]
    reviews_answered: list[str]
    responses_written: list[str]
    transcript: str


def _next_action(project_dir: Path) -> dict[str, Any] | None:
    path = project_dir / "next_action.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _refuse_a_branch(case: ReplayCase, project_dir: Path) -> None:
    """A case with an active alternative is refused, loudly, rather than misread.

    Everything belonging to one formulation lives under `alternatives/<id>/` --
    the proposal, the acceptance revision, the reviews, `next_action.json` -- and
    every path this harness joins is relative to the project root. On a branched
    job those two are different directories, so the loop would look for the
    review packet where nobody put it and read the root's receipts as the
    branch's.

    Refused rather than resolved. Building a work-directory resolver that no
    committed case exercises is the broad unfinished framework ROADMAP.md 3.1
    forbids; a branch replay is a case that needs recording, and when one is, the
    resolver comes with it and has something to fail on. What must not happen in
    the meantime is a replay that quietly compares the wrong directory and
    reports it as a pass.
    """
    payload = _read(project_dir, "project.json") or {}
    active = payload.get("active_alternative")
    if active:
        raise ReplayError(
            f"{case.case_id}: project.json makes {active!r} the active "
            "alternative, and this harness joins every path against the project "
            "root. A branched formulation keeps its receipts, its acceptance "
            "revision and its review packets under alternatives/<id>/, so a "
            "replay of one would read the root's and call them the branch's. "
            "Record a branch case and give this a work-directory resolver "
            "together; do not do either on its own.")


def command_surface() -> Callable[[list[str]], int]:
    """`design-tool`'s own entry point, resolved late.

    A replay that called `cli.run` would be testing a handler; the surface a user
    and a CI job actually reach is `main`, argv dispatch included. Late so that
    importing this module -- to read a case, to compare two recordings -- costs
    nothing of the pipeline's import time.
    """
    from pipeline import cli
    return cli.main


# `cli.NEEDS_ACTION`. Duplicated as a literal rather than imported at module
# scope for the reason above, and `tools/test_replay.py` asserts the two are
# equal, because a constant copied and not checked is a constant that drifts.
NEEDS_ACTION = 3


def play(case: ReplayCase, project_dir: Path,
         *, envelope_for: Callable[[str, dict], Any] | None = None,
         invoke: Callable[[list[str]], int] | None = None) -> Play:
    """`design-tool route`, then `run` until it stops, answering from the record.

    `envelope_for` exists for one caller: the adversarial fixture, which stamps an
    envelope the run did not ask for so that the binding can be shown to still
    fail closed. Every other caller takes the default, which echoes the packet.

    `invoke` exists so the guards below -- an unrecorded review, an
    `AGENT_COMMISSION`, an answer this harness did not write, a job that will not
    settle -- can be shown to fail on demand without paying for a real job to
    misbehave first. The L1 suite never passes it, and `tools/test_replay.py`
    asserts the default is `pipeline.cli.main` so the seam cannot quietly point
    somewhere else.
    """
    invoke_surface = invoke or command_surface()
    project_dir = Path(project_dir)
    _refuse_a_branch(case, project_dir)
    exit_codes: list[str | int] = []
    answered: list[str] = []
    written: list[str] = []
    transcript = io.StringIO()

    def step(argv: list[str]) -> int:
        with contextlib.redirect_stdout(transcript), \
                contextlib.redirect_stderr(transcript):
            return invoke_surface(argv)

    exit_codes.append(step(["route", str(project_dir)]))

    for _ in range(case.max_invocations):
        code = step(["run", str(project_dir), "--no-render"])
        exit_codes.append(code)
        if code != NEEDS_ACTION:
            break
        action = _next_action(project_dir)
        kind = (action or {}).get("kind")
        if kind == "AGENT_COMMISSION":
            raise LiveDispatchRequired(
                f"{case.case_id}: the run wrote an AGENT_COMMISSION asking a "
                f"designer for {(action or {}).get('required_outputs')}. That is "
                "the live dispatch a replay exists to avoid, so this case is "
                "missing a recorded designer output rather than passing.")
        if kind != "REVIEW":
            break
        review_kind = action["review_kind"]
        packet_path = project_dir / action["evidence"]
        response_path = project_dir / action["respond_with"]
        if response_path.exists() and response_path.name not in written:
            # Not "exists": this play may legitimately be looking at its own
            # earlier answer, and a run that asks twice for one kind is a job
            # that is not consuming what it was given -- which the invocation
            # budget below catches and names correctly. What is refused here is
            # an answer that was on disk before this harness wrote anything,
            # because that is an answer nobody recorded.
            raise ReplayError(
                f"{case.case_id}: {response_path.name} already exists and this "
                "harness did not write it. Every answer a replay consumes must "
                "come from the recording.")
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        stamp = (envelope_for(review_kind, packet) if envelope_for is not None
                 else packet["review_envelope"])
        response_path.write_text(
            json.dumps({**case.judgement(review_kind), "review_envelope": stamp},
                       indent=2, sort_keys=True) + "\n", encoding="utf-8")
        answered.append(review_kind)
        if response_path.name not in written:
            written.append(response_path.name)
    else:
        raise ReplayError(
            f"{case.case_id}: still asking for something after "
            f"{case.max_invocations} invocations of `design-tool run`. A replay "
            "that loops is a replay that never finishes.")

    on_disk = sorted(path.name for path in (project_dir / "reviews").glob("*_response.json")) \
        if (project_dir / "reviews").is_dir() else []
    if on_disk != sorted(written):
        raise ReplayError(
            f"{case.case_id}: the review answers on disk are {on_disk} and this "
            f"harness wrote {sorted(written)}. An answer nobody recorded reached "
            "the run.")
    return Play(project_dir=project_dir, exit_codes=exit_codes,
                reviews_answered=answered, responses_written=written,
                transcript=transcript.getvalue())


# --------------------------------------------------------------------------
# Reading what happened
# --------------------------------------------------------------------------

RECEIPT_SUFFIXES = (".json", ".stl", ".step", ".py", ".md")
# Written by the runner and excluded from the receipt set by name, because it
# says so itself: "not hashed: durations are not part of any artifact's
# identity". A receipt set that contained it would still be stable, but listing a
# file the pipeline declares non-identifying alongside the ones that are is how a
# reader stops trusting the list.
NOT_A_RECEIPT = frozenset({"timings.json"})


def _read(project_dir: Path, name: str) -> dict[str, Any] | None:
    path = project_dir / name
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def observe(case: ReplayCase, run: Play) -> dict[str, Any]:
    """Everything a replay compares, read off the finished job directory."""
    directory = run.project_dir
    final = _read(directory, "final_status.json") or {}
    report = _read(directory, "commission_report.json") or {}
    frozen = _read(directory, "acceptance_contract.json") or {}
    history = _read(directory, "acceptance_history.json") or {}
    screening = report.get("screening") or {}

    checks = {row["check_id"]: {"result": row.get("result"),
                                "status": row.get("status"),
                                "ran": row.get("ran")}
              for row in report.get("checks", ())}
    measured = {row["check_id"]: row.get("measured")
                for row in report.get("checks", ())}
    tolerances = {row["check_id"]: row.get("tolerance")
                  for row in report.get("checks", ())}

    receipts = sorted(
        path.name for path in directory.iterdir()
        if path.is_file() and path.suffix in RECEIPT_SUFFIXES
        and path.name not in NOT_A_RECEIPT)

    return {
        "schema_version": EXPECTED_SCHEMA,
        "case_id": case.case_id,
        "exit_codes": list(run.exit_codes),
        "reviews_answered": list(run.reviews_answered),
        "outcome": {
            "final_status": final.get("final_status"),
            "commission_verdict": final.get("commission_verdict"),
            "screening": final.get("screening"),
            "screening_calibrated": final.get("screening_calibrated"),
            "safety_verification": final.get("safety_verification"),
            "verification": final.get("verification"),
            "route": final.get("route"),
            "backend": final.get("backend"),
            "lane_status": final.get("lane_status"),
            "consequence": final.get("consequence"),
        },
        "checks": checks,
        "measured": measured,
        "tolerances": tolerances,
        "coverage": report.get("coverage"),
        "screening_detail": {
            "overall": screening.get("overall"),
            "calibrated": screening.get("calibrated"),
            # Per detector, not only the roll-up. `overall` is the maximum of
            # four answers, so a detector that stopped running and one that
            # started clearing everything both leave it exactly where it was.
            "detectors": {row.get("detector"): row.get("result")
                          for row in screening.get("detectors", ())},
        },
        "acceptance": {
            "revision": frozen.get("revision"),
            "history_entries": len(history.get("revisions") or ()),
            "tolerance_owner": frozen.get("tolerance_owner"),
            "expected_volume_basis": frozen.get("expected_volume_basis"),
            "features": sorted(row.get("feature_id")
                               for row in frozen.get("features", ())),
        },
        "receipts": receipts,
        # Advisory. Recorded so a maintainer can read what the run said; compared
        # and printed, never binding. See the module docstring.
        "reasons": list(final.get("reasons") or ()),
        "allowed_claim": final.get("allowed_claim"),
    }


def determinism_marks(project_dir: Path) -> dict[str, Any]:
    """The digests two replays of one case must agree on.

    Not compared against anything recorded at another commit -- that is the whole
    point. A candidate digest moves with the tessellator and a sample-plan digest
    moves with the plan version, and neither move is a defect; two runs of one
    unchanged pair disagreeing is.
    """
    marks: dict[str, Any] = {}
    candidate = project_dir / "candidate.stl"
    if candidate.is_file():
        marks["candidate.stl"] = digest_of(candidate)
    report = _read(project_dir, "commission_report.json") or {}
    for row in report.get("checks", ()):
        value = row.get("measured")
        if isinstance(value, dict):
            for key in sorted(VOLATILE_KEYS & set(value)):
                marks[f"{row['check_id']}.{key}"] = value[key]
    return marks


# --------------------------------------------------------------------------
# Comparing
# --------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class Difference:
    severity: str
    where: str
    recorded: Any
    observed: Any

    def __str__(self) -> str:
        return (f"[{self.severity}] {self.where}: recorded {self.recorded!r}, "
                f"observed {self.observed!r}")


def _band_for(tolerance: Any, recorded: Any) -> float:
    declared = 0.0
    if isinstance(tolerance, dict):
        try:
            declared = abs(float(tolerance.get("abs") or 0.0))
        except (TypeError, ValueError):
            declared = 0.0
    if declared > 0.0:
        return declared
    magnitude = abs(float(recorded)) if isinstance(recorded, (int, float)) else 0.0
    return magnitude * REPLAY_RELATIVE_BAND + REPLAY_ABSOLUTE_FLOOR


def _compare_value(where: str, recorded: Any, observed: Any, tolerance: Any,
                   out: list[Difference]) -> None:
    """One measured value, or one branch of a nested one, inside its own band."""
    if isinstance(recorded, bool) or isinstance(observed, bool):
        if recorded != observed:
            out.append(Difference(BINDING, where, recorded, observed))
        return
    if isinstance(recorded, (int, float)) and isinstance(observed, (int, float)):
        band = _band_for(tolerance, recorded)
        if abs(float(recorded) - float(observed)) > band:
            out.append(Difference(
                BINDING, f"{where} (band {band:g})", recorded, observed))
        return
    if isinstance(recorded, dict) and isinstance(observed, dict):
        for key in sorted(set(recorded) | set(observed)):
            if key in VOLATILE_KEYS:
                continue
            if key not in recorded or key not in observed:
                out.append(Difference(BINDING, f"{where}.{key}",
                                      recorded.get(key, "(absent)"),
                                      observed.get(key, "(absent)")))
                continue
            _compare_value(f"{where}.{key}", recorded[key], observed[key],
                           tolerance, out)
        return
    if isinstance(recorded, list) and isinstance(observed, list):
        if len(recorded) != len(observed):
            out.append(Difference(BINDING, f"{where}.length",
                                  len(recorded), len(observed)))
            return
        for index, (a, b) in enumerate(zip(recorded, observed)):
            _compare_value(f"{where}[{index}]", a, b, tolerance, out)
        return
    if recorded != observed:
        out.append(Difference(BINDING, where, recorded, observed))


def _compare_exact(where: str, recorded: Any, observed: Any,
                   out: list[Difference], severity: str = BINDING) -> None:
    if isinstance(recorded, dict) and isinstance(observed, dict):
        for key in sorted(set(recorded) | set(observed)):
            _compare_exact(f"{where}.{key}", recorded.get(key, "(absent)"),
                           observed.get(key, "(absent)"), out, severity)
        return
    if recorded != observed:
        out.append(Difference(severity, where, recorded, observed))


def compare(recorded: dict[str, Any], observed: dict[str, Any]) -> list[Difference]:
    """Every layer, each by its own rule. See the module docstring for the argument."""
    out: list[Difference] = []

    for field in ("exit_codes", "reviews_answered", "receipts"):
        _compare_exact(field, recorded.get(field), observed.get(field), out)
    for field in ("outcome", "coverage", "screening_detail", "acceptance"):
        _compare_exact(field, recorded.get(field), observed.get(field), out)

    recorded_checks = recorded.get("checks") or {}
    observed_checks = observed.get("checks") or {}
    if set(recorded_checks) != set(observed_checks):
        out.append(Difference(BINDING, "checks.ids",
                              sorted(recorded_checks), sorted(observed_checks)))
    for check_id in sorted(set(recorded_checks) & set(observed_checks)):
        _compare_exact(f"checks.{check_id}", recorded_checks[check_id],
                       observed_checks[check_id], out)

    recorded_measured = recorded.get("measured") or {}
    observed_measured = observed.get("measured") or {}
    tolerances = recorded.get("tolerances") or {}
    for check_id in sorted(set(recorded_measured) & set(observed_measured)):
        _compare_value(f"measured.{check_id}", recorded_measured[check_id],
                       observed_measured[check_id], tolerances.get(check_id), out)

    for field in ("reasons", "allowed_claim"):
        _compare_exact(field, recorded.get(field), observed.get(field), out,
                       severity=ADVISORY)
    return out


def binding(differences: list[Difference]) -> list[Difference]:
    return [row for row in differences if row.severity == BINDING]


# --------------------------------------------------------------------------
# Running one case
# --------------------------------------------------------------------------

def run_case(case_id: str, destination: Path) -> tuple[ReplayCase, Play, dict[str, Any]]:
    case = load(case_id)
    project_dir = materialise(case, Path(destination) / "project")
    performed = play(case, project_dir)
    return case, performed, observe(case, performed)


def record(case_id: str, destination: Path) -> dict[str, Any]:
    """Run the case and write what it produced as the new recording.

    Deliberately a separate verb with its own command line. A harness that
    re-recorded on failure would agree with whatever the pipeline does today and
    would never report anything.
    """
    _, _, observed = run_case(case_id, destination)
    payload = {**observed, "recorded_at": _head()}
    (CASES_ROOT / case_id / EXPECTED_FILE).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def reseal(case_id: str) -> dict[str, str]:
    """Re-digest a case's recorded inputs into `case.json`.

    The other half of `--record`, and the one that must be used with it: an input
    resealed without re-recording is a case whose expectations describe bytes
    that are no longer there. `load` refuses that combination on the next run,
    which is the point of digesting them at all.
    """
    path = CASES_ROOT / case_id / CASE_FILE
    payload = json.loads(path.read_text(encoding="utf-8"))
    digests = {name: digest_of(CASES_ROOT / case_id / name)
               for name in recorded_files(case_id)}
    payload["inputs_sha256"] = digests
    payload["recorded_at"] = _head()
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n",
                    encoding="utf-8")
    return digests


def _head() -> str:
    import subprocess
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                              capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:                                  # noqa: BLE001 - a recording
        return "unknown"                               # outside a checkout still records


def main(argv: list[str] | None = None) -> int:
    import argparse
    import tempfile

    parser = argparse.ArgumentParser(
        prog="tools/replay.py",
        description="Replay a recorded engineering job through the current "
                    "pipeline with no live AI call.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true")
    group.add_argument("--run", metavar="CASE")
    group.add_argument("--record", metavar="CASE")
    group.add_argument("--reseal", metavar="CASE",
                       help="re-digest a case's recorded inputs after editing "
                            "them; always followed by --record")
    args = parser.parse_args(argv)

    if args.reseal:
        digests = reseal(args.reseal)
        print(f"resealed {args.reseal}: {len(digests)} input(s). Re-record it: "
              f"`uv run python tools/replay.py --record {args.reseal}`")
        return 0

    if args.list:
        for case_id in case_ids():
            case = load(case_id)
            print(f"  {case_id:28s} {case.use_case:9s} {case.source_mode:10s} "
                  f"{len(case.reviews)} recorded review(s), frozen at "
                  f"{case.recorded_at[:12]}")
        return 0

    if args.record:
        with tempfile.TemporaryDirectory() as raw:
            payload = record(args.record, Path(raw))
        print(f"recorded {args.record} at {payload['recorded_at'][:12]}: "
              f"{payload['outcome']['final_status']}, "
              f"exit {payload['exit_codes']}")
        return 0

    with tempfile.TemporaryDirectory() as raw:
        case, _, observed = run_case(args.run, Path(raw))
    differences = compare(expected(case.case_id), observed)
    for row in differences:
        print(f"  {row}")
    failures = binding(differences)
    print(f"\n{case.case_id}: {len(failures)} binding, "
          f"{len(differences) - len(failures)} advisory")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
