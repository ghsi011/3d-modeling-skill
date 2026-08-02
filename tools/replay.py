#!/usr/bin/env python3
"""L1 — a recorded engineering job, replayed through the current command surface.

    uv run pytest benchmarks/replays              # the suite; ~70 s, four cases
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
* *The derived status of each formulation, and which receipts stopped binding.*
  `derived_status`, `stored_status`, and the sorted *names* in `stale`. See the
  next section for why a computed value belongs in this list at all.

**Advisory, reported and never failing on its own.** `reasons` and
`allowed_claim` are prose written for a human. They are recorded verbatim,
because a maintainer reading `expected.json` should be able to see what the run
actually said, and they are compared and printed as advisories -- a reworded
sentence is not a regression and must not be able to stop a build.

**Deliberately not asserted at all.** The bytes of any receipt; any literal
sha256 of a receipt, packet, envelope, contract or artifact; `findings` text;
`lane_note` text; timings; the witness images; the *sentences* under a `stale`
entry, which name two short digests and are prose about them. Every one of them
moves for reasons that have nothing to do with whether the job still behaves.

## Derived status is computed, not a receipt, and it is still binding

Everything else in the binding list is read off a file the run wrote.
`status.derive` is different: it is computed on demand from the bindings on disk,
so `design-tool status` can answer a question `final_status.json` cannot -- is
the verdict this run reached still about the project it is sitting in. Recording
it means recording something no receipt carries.

It goes in the binding list anyway, and the existing rule is what puts it there
rather than an exception made for it. The rule separates *answers the system
gives* from *prose written for a human*: a status, a verdict and a per-check
result bind; `reasons` and `allowed_claim` do not. `STALE` versus `VERIFIED`
versus `NOT_RUN` is an answer, not a sentence -- `design-tool status` returns a
different exit code for each, so a caller scripting the loop branches on it, and
a change that stopped weakening a superseded claim would move it while every
receipt on disk stayed byte-identical. It is also deterministic in the way the
binding layer requires: `derive` re-adjudicates nothing, applies no threshold and
reads no clock, so two replays of one recording produce the same answer or
something is wrong.

The *reasons* underneath it are the same prose `final_status.reasons` is, and are
treated the same way. The `stale` map splits: its keys are the set of receipts
that stopped binding, which is a shape, and shapes bind here -- a receipt that
silently stops being checked is the failure `RECEIPTS` exists to prevent. Its
values name two truncated digests inside an English sentence and are recorded
nowhere.

## Where a branched job writes, and what this harness still refuses

Everything belonging to one formulation -- the proposal, the model, the frozen
acceptance contract, the receipts, `next_action.json`, the review packets --
lives in that formulation's *work directory*: the project root while no
alternative is active, and `alternatives/<id>` once one is. The shared half
never moves: `project.json`, the brief and the supplied artifacts stay at the
root, and the review envelope's evidence digests are taken relative to it.

So `work_dir()` is re-read from `project.json` at every step rather than
computed once. `design-tool branch` changes the answer mid-play, and a resolver
that cached it would read one formulation's receipts as another's -- which is
the whole failure this exists to avoid.

It is a second implementation of `Project.work_dir` on purpose, for the reason
`NEEDS_ACTION` is a literal here: a harness that asked the system under test
where to look could not catch the system looking in the wrong place.
`tools/test_replay.py` asserts the two agree, and asserts the id pattern and the
directory name against `pipeline.project`'s own, so the copy cannot drift
unnoticed.

What it still refuses, loudly, is an `active_alternative` that is not a plain
`[a-z0-9-]+` id, or one whose join would leave the project. `design-tool branch`
cannot write one; a hand-edited `project.json` can, and `Project.validate` names
it as a finding. A replay that quietly resolved it to the project root would
compare the root's receipts and report a pass.

Deliberately still not expressed: nothing here selects a formulation by anything
other than the ordered list a case declares. There is no resume-from-the-middle,
no scoping below job-versus-alternative and no merge with several parents,
because no committed case needs one -- which is the same argument that kept the
resolver itself out until this case arrived.

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
three things guard it. The harness asserts that the envelope on each review
report is the envelope of the packet that asked for it -- if the runner ever
accepted an answer that did not match, the replay fails. And the L1 suite carries
two adversarial fixtures, both of which stamp an envelope the run did not issue
and require it to refuse, write no final status and exit non-zero:

* one moves an *evidence digest*, which is a stale answer -- the case the
  envelope was built for;
* one moves nothing at all. It offers a formulation the envelope its *sibling's*
  review was issued under: live, current, correctly formed, and for a part whose
  contract hash, STL digest and source digest are byte-identical. That is the
  false pass protocol 4 exists for, and it is only reachable at all because a
  branch is a copy of its ancestor at the instant it is created.

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

A case directory holds three trees, and two of them are the project directory::

    case.json      what to play, and the digest of every file below
    expected.json  what it produced, at the commit that recorded it
    inputs/        the project directory as it must be before the play
    revisions/     files written over it *after* a named formulation settles
    judgements/    the reviewers' decisions, by formulation and kind

`inputs/` and `revisions/` mirror the project tree exactly -- `inputs/model.py`
at the root, `inputs/alternatives/as-drawn/model.py` on a branch -- because they
*are* files that land in it, and a second naming scheme over one directory layout
is a mapping to get wrong. `judgements/` does not land in the project at all: it
is indexed by formulation and review kind (`judgements/safety.json` at the root,
`judgements/as-drawn/safety.json` on a branch), which is what the harness looks
one up by.

`revisions/` exists for one property nothing else can reach. A stored verdict
goes stale when an input it was issued against moves *after* the run concluded --
a designer picking a formulation back up and editing its model. That cannot be an
`inputs/` file, because then the run would have been executed against it and
nothing would ever have bound the older one.

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
import re
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
REVISION_DIR = "revisions"
JUDGEMENT_DIR = "judgements"
# 2: a case may declare `formulations` -- the ordered list of alternatives one
# recorded job is played across -- and must declare `concludes`, which says
# whether the job reaches a final status or is refused before it builds. Both
# are read by the loader, so a case written against schema 1 is refused by
# version rather than silently played as an unbranched one that concludes.
CASE_SCHEMA = 2
EXPECTED_SCHEMA = 1

# Where a branched formulation's work directory sits, and how its id may be
# spelled. Both are `pipeline.project`'s, duplicated here for the reason the
# module docstring gives and asserted equal in `tools/test_replay.py`.
ALTERNATIVES_DIR = "alternatives"
ALTERNATIVE_ID = re.compile(r"^[a-z0-9-]+$")
# How the shared root spells itself on the command line and in a case file.
ROOT_ALTERNATIVE = "."

# What a case says its job does. A replay of a job that is *correctly refused*
# is a replay: "failures are actionable and controlled" is a release gate, and
# an actionable refusal is an outcome with receipts. It is declared rather than
# inferred so that a case which silently stopped building would be caught by the
# declaration rather than by nobody noticing the assertions had gone quiet.
CONCLUDES = ("BUILT", "REFUSED")

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
class Formulation:
    """One formulation of the job, and how the play reaches it.

    `alternative_id` is `None` for the shared root, which is a real place with
    its own proposal, its own contract and its own receipts -- not a bookkeeping
    entry for "no branch". Every other formulation is created by
    `design-tool branch --from <parent> --id <id> --reason <reason>` and worked
    on in its own directory.

    A list rather than a graph: a case declares the order its formulations are
    played in, and the ancestry lives in `parent`, which is what `branch` writes
    into `project.json`. Nothing here resumes into the middle of one.
    """

    alternative_id: str | None
    # `.` for the shared root, or the id of a formulation declared before this
    # one. Unused when this row *is* the root.
    parent: str = ROOT_ALTERNATIVE
    reason: str = ""
    # The review kinds this formulation is expected to be asked for, in order.
    reviews: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        """How this formulation is named in a recording and on the command line."""
        return self.alternative_id or ROOT_ALTERNATIVE

    def relative_dir(self) -> PurePosixPath:
        """Its work directory, relative to the project root."""
        return (PurePosixPath() if self.alternative_id is None
                else PurePosixPath(ALTERNATIVES_DIR) / self.alternative_id)


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
    # Every formulation this job is played across, in order. Always at least one:
    # a case that declares none is one unbranched formulation at the root, which
    # is what `load` builds from the case's own `reviews` list.
    formulations: tuple[Formulation, ...]
    # Whether the case declared branching at all. Derived and not stored, so an
    # unbranched case cannot accidentally opt into the branch machinery: `play`
    # issues no `branch` command and `observe` produces exactly the payload it
    # produced before formulations existed, which is why the two cases recorded
    # before this arrived did not have to be re-recorded.
    branched: bool
    # `BUILT` or `REFUSED`. See `CONCLUDES`.
    concludes: str
    max_invocations: int
    inputs_sha256: dict[str, str]
    recorded_at: str
    provenance: str
    notes: str

    @property
    def directory(self) -> Path:
        return CASES_ROOT / self.case_id

    @property
    def reviews(self) -> tuple[str, ...]:
        """Every review this play answers, in order, across all formulations.

        One flat list because that is what "the reviews answered, in order, and
        that every one came from the recording" means for a whole job. Which
        formulation each belongs to is in `formulations`.
        """
        return tuple(kind for row in self.formulations for kind in row.reviews)

    def judgement(self, kind: str,
                  alternative_id: str | None = None) -> dict[str, Any]:
        room = self.directory / JUDGEMENT_DIR
        path = (room / f"{kind}.json" if alternative_id is None
                else room / alternative_id / f"{kind}.json")
        if not path.is_file():
            where = ("" if alternative_id is None
                     else f" for alternative {alternative_id!r}")
            raise NoRecordedAnswer(
                f"{self.case_id}: the run asked for a {kind} review{where} and "
                f"this case records no such judgement at {path}. A replay answers "
                "from a recording or it does not answer; there is no live call "
                "here to fall back on.")
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

    Case-relative, POSIX-spelled, sorted, and walked to the bottom of each tree:
    a branched case's `inputs/` mirrors the project directory, so its files are
    nested, and a digest set that only looked one level down would leave every
    branch's model and proposal unchecked.

    `case.json` is out because it is where the digests live, and `expected.json`
    is out because it is the recording rather than an input to it.
    """
    directory = CASES_ROOT / case_id
    names = []
    for sub in (INPUT_DIR, REVISION_DIR, JUDGEMENT_DIR):
        room = directory / sub
        if not room.is_dir():
            continue
        names += [path.relative_to(directory).as_posix()
                  for path in sorted(room.rglob("*")) if path.is_file()]
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

    declared = payload.get("formulations")
    if declared and payload.get("reviews"):
        raise ReplayError(
            f"{case_id}: case.json declares both `formulations` and a top-level "
            "`reviews`. On a branched job a review belongs to one formulation, "
            "and two places to read the expected order from is two answers and "
            "one bug. Put the reviews on the formulation that is asked for them.")
    formulations = (
        tuple(_formulation(case_id, index, row)
              for index, row in enumerate(declared))
        if declared else
        # The shape every case had before branching arrived: one formulation, at
        # the root, holding whatever reviews the case declared.
        (Formulation(alternative_id=None,
                     reviews=tuple(payload.get("reviews") or ())),))

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
        formulations=formulations,
        branched=bool(declared),
        concludes=payload["concludes"],
        max_invocations=int(payload["max_invocations"]),
        inputs_sha256=dict(payload["inputs_sha256"]),
        recorded_at=payload["recorded_at"],
        provenance=payload["provenance"],
        notes=payload.get("notes", ""))
    if case.concludes not in CONCLUDES:
        raise ReplayError(
            f"{case_id}: concludes {case.concludes!r} is not one of "
            f"{list(CONCLUDES)}")
    _verify_inputs(case)
    return case


def _formulation(case_id: str, index: int, row: dict[str, Any]) -> Formulation:
    """One declared formulation, with the id checked before it becomes a path.

    Checked here and not only where it is joined: the id reaches the command
    line as `--id`, the filesystem as a directory name and `expected.json` as a
    key, and a case that had to be played before anybody found out it was
    unspellable is a case that fails somewhere unhelpful.
    """
    raw = row.get("alternative_id")
    alternative_id = None if raw in (None, ROOT_ALTERNATIVE) else str(raw)
    if alternative_id is not None and not ALTERNATIVE_ID.match(alternative_id):
        raise ReplayError(
            f"{case_id}: formulations[{index}].alternative_id {raw!r} must match "
            f"{ALTERNATIVE_ID.pattern} or be {ROOT_ALTERNATIVE!r} for the shared "
            "root -- it becomes a directory name, a command-line argument and a "
            "key in the recording.")
    if alternative_id is not None and not str(row.get("reason") or "").strip():
        raise ReplayError(
            f"{case_id}: formulations[{index}] declares no reason. "
            "`design-tool branch` refuses one without it, so a case that carried "
            "none could never be played.")
    return Formulation(alternative_id=alternative_id,
                       parent=str(row.get("parent") or ROOT_ALTERNATIVE),
                       reason=str(row.get("reason") or ""),
                       reviews=tuple(row.get("reviews") or ()))


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
        if not name.startswith(f"{INPUT_DIR}/"):
            continue
        _write_input(case, name, destination)
    return destination


def _write_input(case: ReplayCase, name: str, destination: Path) -> Path:
    """One recorded file into the place the project tree wants it.

    `inputs/` mirrors the project directory, so the path after the prefix is the
    path inside it -- no mapping, and a branch's model lands under
    `alternatives/<id>/` because that is where the case put it.
    """
    relative = PurePosixPath(name).relative_to(PurePosixPath(name).parts[0])
    target = destination / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    text = (case.directory / name).read_text(encoding="utf-8")
    for token, where in sorted(case.substitutions.items()):
        text = text.replace(token, str(destination / where).replace("\\", "\\\\"))
    target.write_text(text, encoding="utf-8")
    return target


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
    # Formulation key -> its work directory. One entry for an unbranched job,
    # one per formulation otherwise, in play order.
    work_dirs: dict[str, Path] = dataclasses.field(default_factory=dict)
    # Formulation key -> what `design-tool status` derives for it at the end of
    # the play. Empty unless the case declared formulations; see `observe`.
    derived: dict[str, dict[str, Any]] = dataclasses.field(default_factory=dict)


def work_dir(project_dir: Path) -> Path:
    """Where the *currently active* formulation writes, read off `project.json`.

    The project root while no alternative is active -- which is every job that
    has never branched -- and `alternatives/<id>` once one is. Re-read on every
    use rather than computed once, because `design-tool branch` moves it
    mid-play.

    Refused rather than resolved, loudly, for an id that is not a plain
    `[a-z0-9-]+` or whose join would leave the project. `branch` cannot write
    one and `Project.validate` reports one as a finding, so the only way to get
    here is a hand-edited `project.json` -- and falling back to the project root
    would compare the root's receipts and call them the branch's, which is a
    replay passing for the wrong reason.
    """
    project_dir = Path(project_dir)
    active = (_read(project_dir, "project.json") or {}).get("active_alternative")
    if active in (None, "", ROOT_ALTERNATIVE):
        return project_dir
    if not isinstance(active, str) or not ALTERNATIVE_ID.match(active):
        raise ReplayError(
            f"project.json makes {active!r} the active alternative, and an id "
            f"this harness can resolve matches {ALTERNATIVE_ID.pattern}. "
            "Resolving it to the project root instead would read the shared "
            "root's receipts and report them as this formulation's.")
    resolved = (project_dir / ALTERNATIVES_DIR / active).resolve()
    if not resolved.is_relative_to(project_dir.resolve()):
        raise ReplayError(                          # pragma: no cover - see above
            f"the work directory for alternative {active!r} resolves to "
            f"{resolved}, which is outside the project.")
    return resolved


def _next_action(work: Path) -> dict[str, Any] | None:
    path = work / "next_action.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


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
    """Every declared formulation in turn: branch, `route`, then `run` until it
    stops, answering from the record.

    On an unbranched case there is one formulation, no `branch` command is
    issued, and this is exactly the loop it always was.

    `envelope_for` exists for the adversarial fixtures, which stamp an envelope
    the run did not ask for -- one belonging to another question, and one
    belonging to a *sibling* -- so that the binding can be shown to still fail
    closed. It is given the formulation as well as the kind, because on a
    branched job "the answer written next door" is the whole point. Every other
    caller takes the default, which echoes the packet.

    `invoke` exists so the guards below -- an unrecorded review, an
    `AGENT_COMMISSION`, an answer this harness did not write, a job that will not
    settle -- can be shown to fail on demand without paying for a real job to
    misbehave first. The L1 suite never passes it, and `tools/test_replay.py`
    asserts the default is `pipeline.cli.main` so the seam cannot quietly point
    somewhere else.
    """
    invoke_surface = invoke or command_surface()
    project_dir = Path(project_dir)
    exit_codes: list[str | int] = []
    answered: list[str] = []
    written: list[str] = []
    work_dirs: dict[str, Path] = {}
    transcript = io.StringIO()

    def step(argv: list[str]) -> int:
        with contextlib.redirect_stdout(transcript), \
                contextlib.redirect_stderr(transcript):
            return invoke_surface(argv)

    for formulation in case.formulations:
        exit_codes += _select(case, project_dir, formulation, step)
        exit_codes.append(step(["route", str(project_dir)]))
        _play_one(case, project_dir, formulation, step,
                  exit_codes=exit_codes, answered=answered, written=written,
                  envelope_for=envelope_for)
        work_dirs[formulation.key] = work_dir(project_dir)
        _apply_revisions(case, project_dir, formulation)

    on_disk = sorted(
        path.relative_to(project_dir).as_posix()
        for path in project_dir.rglob("*_response.json")
        if path.parent.name == "reviews")
    if on_disk != sorted(written):
        raise ReplayError(
            f"{case.case_id}: the review answers on disk are {on_disk} and this "
            f"harness wrote {sorted(written)}. An answer nobody recorded reached "
            "the run.")
    derived = _derive_all(case, project_dir, step, invoke_surface, transcript)
    return Play(project_dir=project_dir, exit_codes=exit_codes,
                reviews_answered=answered, responses_written=written,
                transcript=transcript.getvalue(), work_dirs=work_dirs,
                derived=derived)


def _select(case: ReplayCase, project_dir: Path, formulation: Formulation,
            step: Callable[[list[str]], int]) -> list[str | int]:
    """Put the project on this formulation, through `design-tool branch`.

    Declared for the first time it is created; declared already it is switched
    to. Both are the one verb a user has, and both are recorded in the exit
    sequence -- a branch that started failing would otherwise show up two
    commands later as a job writing into the wrong directory.

    An unbranched case issues nothing at all, so its play is byte-for-byte the
    sequence it was before this existed.
    """
    if not case.branched:
        return []
    payload = _read(project_dir, "project.json") or {}
    declared = {row.get("alternative_id")
                for row in payload.get("alternatives") or ()}
    active = payload.get("active_alternative") or None
    wanted = formulation.alternative_id
    if wanted is None:
        argv = ([] if active is None
                else ["branch", str(project_dir), "--activate", ROOT_ALTERNATIVE])
    elif wanted not in declared:
        argv = ["branch", str(project_dir), "--from", formulation.parent,
                "--id", wanted, "--reason", formulation.reason]
    elif active != wanted:
        argv = ["branch", str(project_dir), "--activate", wanted]
    else:
        argv = []
    if not argv:
        return []
    code = step(argv)
    if code != 0:
        raise ReplayError(
            f"{case.case_id}: `design-tool {' '.join(argv[:1] + argv[2:])}` "
            f"exited {code}. The formulation this case declares could not be "
            "reached, so nothing below it is a replay of anything.")
    return [code]


def _play_one(case: ReplayCase, project_dir: Path, formulation: Formulation,
              step: Callable[[list[str]], int], *,
              exit_codes: list[str | int], answered: list[str],
              written: list[str],
              envelope_for: Callable[..., Any] | None) -> None:
    """`run` one formulation until it stops, answering from the record."""
    for _ in range(case.max_invocations):
        code = step(["run", str(project_dir), "--no-render"])
        exit_codes.append(code)
        if code != NEEDS_ACTION:
            break
        # Re-read: the run that just paused wrote its instruction into *this*
        # formulation's directory, which the last `branch` moved.
        work = work_dir(project_dir)
        action = _next_action(work)
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
        # Both are relative to the work directory, which is where the pipeline
        # wrote them and where it will look for the answer.
        packet_path = work / action["evidence"]
        response_path = work / action["respond_with"]
        # Project-relative, so two formulations answering one review kind are two
        # entries rather than one. Under the bare filename a sibling's answer
        # would have counted as this one's own earlier attempt.
        relative = response_path.relative_to(project_dir).as_posix()
        if response_path.exists() and relative not in written:
            # Not "exists": this play may legitimately be looking at its own
            # earlier answer, and a run that asks twice for one kind is a job
            # that is not consuming what it was given -- which the invocation
            # budget below catches and names correctly. What is refused here is
            # an answer that was on disk before this harness wrote anything,
            # because that is an answer nobody recorded.
            raise ReplayError(
                f"{case.case_id}: {relative} already exists and this harness did "
                "not write it. Every answer a replay consumes must come from the "
                "recording.")
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        stamp = (envelope_for(review_kind, packet, formulation)
                 if envelope_for is not None else packet["review_envelope"])
        response_path.write_text(
            json.dumps({**case.judgement(review_kind, formulation.alternative_id),
                        "review_envelope": stamp},
                       indent=2, sort_keys=True) + "\n", encoding="utf-8")
        answered.append(review_kind)
        if relative not in written:
            written.append(relative)
    else:
        raise ReplayError(
            f"{case.case_id}: formulation {formulation.key!r} is still asking for "
            f"something after {case.max_invocations} invocations of "
            "`design-tool run`. A replay that loops is a replay that never "
            "finishes.")


def _apply_revisions(case: ReplayCase, project_dir: Path,
                     formulation: Formulation) -> None:
    """Write this formulation's recorded revisions over what it just produced.

    After it settles, never before: the point is a verdict that was reached
    against one version of an input and is read afterwards against another. An
    input revised before the run would simply be the input the run used, and
    nothing would ever have bound the older one.
    """
    prefix = PurePosixPath(REVISION_DIR) / formulation.relative_dir()
    for name in recorded_files(case.case_id):
        path = PurePosixPath(name)
        if path.parent != prefix:
            continue
        _write_input(case, name, project_dir)


def _derive_all(case: ReplayCase, project_dir: Path,
                step: Callable[[list[str]], int],
                invoke_surface: Callable[[list[str]], int],
                transcript: io.StringIO) -> dict[str, dict[str, Any]]:
    """What `design-tool status` currently derives for each formulation.

    Read through the command surface, one formulation at a time, because that is
    the only place derived status exists: it is computed from the bindings on
    disk and no receipt carries it. See the module docstring for why a computed
    value is nonetheless binding.

    Only for a branched case. An unbranched one would gain a key in every
    recording for a value that is `stored_status` by construction the moment the
    run finishes, and the two cases recorded before this arrived would have had
    to be re-recorded to say nothing new.
    """
    if not case.branched:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for formulation in case.formulations:
        _select(case, project_dir, formulation, step)
        report = _status_report(project_dir, invoke_surface, transcript)
        out[formulation.key] = {
            "derived_status": report.get("final_status"),
            "stored_status": report.get("stored_status"),
            # The names only. Which receipts stopped binding is a shape; the
            # sentence under each names two truncated digests and is prose.
            "stale": sorted(report.get("stale") or {}),
        }
    return out


def _status_report(project_dir: Path,
                   invoke_surface: Callable[[list[str]], int],
                   transcript: io.StringIO) -> dict[str, Any]:
    """`design-tool status --json`, parsed.

    Its own stdout buffer: the transcript is a human record of the whole play and
    this is a document the harness reads, and interleaving the two would make the
    parse depend on what every earlier command happened to print. Through the
    same injected surface as everything else, so the seam stays one seam.
    """
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured), \
            contextlib.redirect_stderr(transcript):
        code = invoke_surface(["status", str(project_dir), "--json"])
    transcript.write(captured.getvalue())
    try:
        return json.loads(captured.getvalue())
    except json.JSONDecodeError as exc:
        raise ReplayError(
            f"`design-tool status --json` exited {code} and did not print a JSON "
            f"report: {exc}") from exc


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
    """Everything a replay compares, read off the finished job.

    Two shapes, and the second is the first repeated. An unbranched case
    produces exactly the payload it produced before formulations existed --
    which is why the two cases recorded before this arrived did not move. A
    branched one nests the same block under `formulations`, keyed by alternative
    id with `.` for the shared root, and adds what `design-tool status` derives
    for each.

    Absent rather than null on an unbranched job, following the rule
    `Project.as_payload` already follows for `alternatives`: a key that says
    nothing a reader did not already know is a key that moves every recording in
    the set to say it.
    """
    payload: dict[str, Any] = {
        "schema_version": EXPECTED_SCHEMA,
        "case_id": case.case_id,
        "exit_codes": list(run.exit_codes),
        "reviews_answered": list(run.reviews_answered),
    }
    if not case.branched:
        payload.update(_observe_dir(run.project_dir))
        return payload
    payload["formulations"] = {
        key: {**_observe_dir(directory), "derived": run.derived.get(key)}
        for key, directory in run.work_dirs.items()}
    return payload


def _observe_dir(directory: Path) -> dict[str, Any]:
    """One formulation's receipts, as a block a recording can hold."""
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

    for field in ("exit_codes", "reviews_answered"):
        _compare_exact(field, recorded.get(field), observed.get(field), out)

    if "formulations" in recorded or "formulations" in observed:
        rows = recorded.get("formulations") or {}
        seen = observed.get("formulations") or {}
        if set(rows) != set(seen):
            out.append(Difference(BINDING, "formulations.ids",
                                  sorted(rows), sorted(seen)))
        for key in sorted(set(rows) & set(seen)):
            _compare_block(f"formulations.{key}.", rows[key], seen[key], out)
    else:
        _compare_block("", recorded, observed, out)
    return out


def _compare_block(prefix: str, recorded: dict[str, Any],
                   observed: dict[str, Any], out: list[Difference]) -> None:
    """One formulation's receipts, or a whole unbranched job's.

    `prefix` is empty for an unbranched case, so every `where` a maintainer has
    ever read out of a failure message is unchanged.
    """
    for field in ("receipts", "outcome", "coverage", "screening_detail",
                  "acceptance", "derived"):
        if field == "derived" and recorded.get(field) is None \
                and observed.get(field) is None:
            continue
        _compare_exact(f"{prefix}{field}", recorded.get(field),
                       observed.get(field), out)

    recorded_checks = recorded.get("checks") or {}
    observed_checks = observed.get("checks") or {}
    if set(recorded_checks) != set(observed_checks):
        out.append(Difference(BINDING, f"{prefix}checks.ids",
                              sorted(recorded_checks), sorted(observed_checks)))
    for check_id in sorted(set(recorded_checks) & set(observed_checks)):
        _compare_exact(f"{prefix}checks.{check_id}", recorded_checks[check_id],
                       observed_checks[check_id], out)

    recorded_measured = recorded.get("measured") or {}
    observed_measured = observed.get("measured") or {}
    tolerances = recorded.get("tolerances") or {}
    for check_id in sorted(set(recorded_measured) & set(observed_measured)):
        _compare_value(f"{prefix}measured.{check_id}", recorded_measured[check_id],
                       observed_measured[check_id], tolerances.get(check_id), out)

    for field in ("reasons", "allowed_claim"):
        _compare_exact(f"{prefix}{field}", recorded.get(field),
                       observed.get(field), out, severity=ADVISORY)


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


def _statuses(payload: dict[str, Any]) -> dict[str, str]:
    """What each formulation in a recording concluded, for the command line."""
    if "formulations" not in payload:
        stored = (payload.get("outcome") or {}).get("final_status")
        return {ROOT_ALTERNATIVE: str(stored)}
    out = {}
    for key, block in (payload["formulations"] or {}).items():
        derived = (block.get("derived") or {}).get("derived_status")
        stored = (block.get("outcome") or {}).get("final_status")
        out[key] = (str(stored) if derived in (None, stored)
                    else f"{derived} (the run concluded {stored})")
    return out


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
                  f"{case.concludes:8s} "
                  f"{len(case.formulations)} formulation(s), "
                  f"{len(case.reviews)} recorded review(s), frozen at "
                  f"{case.recorded_at[:12]}")
        return 0

    if args.record:
        with tempfile.TemporaryDirectory() as raw:
            payload = record(args.record, Path(raw))
        print(f"recorded {args.record} at {payload['recorded_at'][:12]}: "
              f"exit {payload['exit_codes']}")
        for key, status in sorted(_statuses(payload).items()):
            print(f"  {key:18s} {status}")
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
