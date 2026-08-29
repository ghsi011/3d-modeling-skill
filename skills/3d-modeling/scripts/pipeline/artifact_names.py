#!/usr/bin/env python3
"""Which owner holds which filename in the work directory.

D34, D35, D36 and D37 are one shape found four times: two legitimate writers,
one filename, and nothing anywhere that could say the name was taken. D34 was
closed by an existence check inside the writer and D35 and D36 by moving the
pipeline's file -- repairs that remove the collision they were written for and
leave the condition that produced it, a shared directory whose names are string
literals in whichever module happens to write them.

This is the smallest thing that makes the collision impossible rather than
repaired. A registered name has exactly one owner; a second owner claiming it is
refused; and a writer resolves its path *through* the owner that holds the name,
so pointing a write back at somebody else's file raises instead of succeeding.

**What it holds.** The verifier's team contract, every artifact the runner
writes, and the execution plan compiled for it. It is *not* yet everything
written into a work directory: `cli` also writes `route_decision.json` and
`next_action.json` there and neither is registered, the role-authored files --
the designer's module and manifest, the print engineer's plan checks -- are
still named by the modules that write them, and the team-contract validators
still declare their own filename table. Bringing those under this is later
work, and guessing at that shape now would be scaffolding for a change nobody
has made yet.
"""
from __future__ import annotations

from pathlib import Path

# The owners that write into a work directory at the same time. `verifier` is
# spelled as `team_tools.validators._EXPECTED_OWNERS` already spells it, so the
# registry and the contract validator name the same role.
VERIFIER = "verifier"
PIPELINE = "pipeline"
# Whatever built the geometry, and deliberately not `pipeline`. A certified
# backend is handed the work directory itself -- `runner` calls
# `backend.build(model_contract, out)` -- and writes its build record there
# beside the receipts. Under one owner the registry could not tell the builder
# from the process that judges what it built, so no claim by one on the other's
# name would be refusable. On the certified lane this record is also what
# `bindings._source_name` binds as `source`, which on the authored lane is the
# designer's own module -- a third party again, and not this one.
BACKEND = "backend"


class NameConflict(Exception):
    """A filename was claimed or written by an owner that does not hold it."""


_OWNERS: dict[str, str] = {}


def register(name: str, *, owner: str) -> str:
    """Record that `owner` holds `name`, refusing it if somebody else does.

    Registering the same pair twice is a no-op rather than a conflict: this
    source checkout imports some modules both package-relatively and by bare
    name, and an import that raised the second time would be reporting the
    packaging, not a collision.
    """
    held = _OWNERS.setdefault(name, owner)
    if held != owner:
        raise NameConflict(
            f"{name!r} is registered to {held!r}; {owner!r} may not claim it too")
    return name


def path(work_dir: Path | str, name: str, *, owner: str) -> Path:
    """Where `owner` may write `name`, or `NameConflict` if it is not theirs."""
    held = _OWNERS.get(name)
    if held != owner:
        raise NameConflict(
            f"{owner!r} may not write {name!r}: it is registered to {held!r}")
    return Path(work_dir) / name


# The verifier's team contract. `team_tools.validators.CANONICAL_FILENAMES`
# names it, `_EXPECTED_OWNERS` requires `verifier` to have authored it, and
# `team_tools.status` cross-checks four bindings against it.
VERIFICATION_REPORT = register("verification_report.json", owner=VERIFIER)

# The pipeline's own independent-verification report: a decision, an evidence
# packet digest, a review envelope and a reviewer. It carries none of the four
# bindings above and no `contract` marker, so it is a different document that
# was sharing the name -- and it is the one that moves, for D36's reason. The
# team contract's name is externally specified, validator-known and
# charter-facing; this one has no reader outside this package.
PIPELINE_VERIFICATION_REPORT = register("pipeline_verification_report.json",
                                        owner=PIPELINE)

# ---------------------------------------------------------------------------
# Everything the runner writes, and the plan compiled for it
# ---------------------------------------------------------------------------
# Declared here rather than beside each writer, because a name declared beside
# its writer is a name no other module can see -- which is the condition D34 to
# D37 kept reproducing. `runner.py` spelled eight of these as bare literals
# while `bindings.py` separately spelled five of the same eight, and neither
# consulted the other.
#
# Every name below is the name the file already had: this registers, it does
# not rename.

INTENT_MANIFEST = register("intent_manifest.json", owner=PIPELINE)
SPECIFICATION = register("specification.json", owner=PIPELINE)
# The compiled plan: the route authority. Nobody authors it -- `route` and
# `run` compile it from `project.json` in the same invocation, and the runner
# consumes it verbatim. **One name, and this is it.** It used to be spelled
# by `execution.EXECUTION_PLAN_FILE`, re-exported as `cli.EXECUTION_PLAN_FILE`,
# and named a third time as `bindings.PLAN_FILE` -- and that third spelling
# collided with `cli.PLAN_FILE`, which meant the print engineer's
# `print_plan_checks.json`. Since `cli` imports `bindings`, `PLAN_FILE` and
# `B.PLAN_FILE` sat a few lines apart in one module meaning two different files.
EXECUTION_PLAN = register("execution_plan.json", owner=PIPELINE)
# The contract the receipts actually bind: derived from the acceptance contract
# on the authored lane and from the certified template on the other, and hashed
# by `contract.Contract.contract_hash`, which is `payload_hash(as_payload())` --
# so the file on disk re-hashes to the value every receipt carries.
MODEL_CONTRACT_FILE = register("model_contract.json", owner=PIPELINE)

# The pipeline's own record of a build: backend, engine, cache, and the digests
# of the contract and the three artifacts. **Not `artifact_manifest.json`.**
#
# That name is a team contract -- `team_tools.validators.CANONICAL_FILENAMES`
# holds it, `designer_toolkit/receipts.py` writes it with
# `contract: artifact-manifest`, and the charters point readers at it. The
# pipeline wrote a wholly different object to the same path and then treated
# that path as one of its own receipts, so a designer's manifest was both
# overwritten by the runner and *deleted* by `invalidate`, which judged a file
# the pipeline had never written stale against a dependency the designer had
# never declared.
#
# The pipeline's is the one that moves, because the other is externally
# specified: renaming that would turn a local collision into a contract
# migration, while this name has no reader outside this package.
PIPELINE_RECEIPT = register("pipeline_artifact_receipt.json", owner=PIPELINE)
COMMISSION_REPORT = register("commission_report.json", owner=PIPELINE)
MANUFACTURING_REPORT = register("manufacturing_report.json", owner=PIPELINE)
SAFETY_VERIFICATION_REPORT = register("safety_verification_report.json",
                                      owner=PIPELINE)
# What a run concluded, and the one file `design-tool status` and a reader treat
# as the job's answer -- `invalidate` says as much where it explains why a stale
# one is removed. Nobody but the pipeline may issue it, least of all whatever
# built the part, which is why `BACKEND` is a separate owner and why the
# refusal is worth a test of its own.
FINAL_STATUS = register("final_status.json", owner=PIPELINE)
# Durations, deliberately unhashed and bound by nothing. Registered anyway: an
# unregistered name is a name the next writer may take, which is the whole
# condition this module exists to end.
TIMINGS = register("timings.json", owner=PIPELINE)

# What a certified backend executed, by its own account: the template, the
# backend and the frozen parameters. **Not `model.py`.** Both certified backends
# used to write this record straight over that name, which for an unbranched
# project is the project root -- and the designer charter tells a designer on a
# certified `DIRECT` job to produce `model.py` there and edit it. So a run
# destroyed the designer's whole deliverable and reported success.
#
# A name of its own rather than an existence check, because the two files are
# not the same kind of thing. The record is what the backend ran; `model.py` is
# what a person wrote. Keeping the designer's file while still calling it the
# source would make `source_sha256` attest that their module produced this STL,
# which is a worse claim than the one it replaces.
#
# **JSON, and the extension is the point.** The first repair gave the record its
# own name and kept `.py`, which moved the collision rather than ending it:
# `isolation._stage` treats *every* top-level `*.py` beside the model as the
# designer's, on the stated ground that "the pipeline writes no Python into a
# project directory". A designer shipping a helper under this exact name would
# have had it destroyed by the same write. Nothing executes this record -- it is
# provenance data -- and a `.py` extension claims an ownership this file does not
# have.
BACKEND_RECORD = register("backend_build_record.json", owner=BACKEND)
