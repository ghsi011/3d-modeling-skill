#!/usr/bin/env python3
"""What each receipt was issued against, and whether that still holds.

ARCHITECTURE.md 13.4 says every generated artifact and assessment is bound to
the inputs capable of changing it, and 13.5 says that when a binding changes the
results that depend on *that* become stale while unrelated valid results stay
reusable. This module is the second half of that sentence, which the build did
not have.

**What it replaces.** Invalidation was one all-or-nothing form: a changed
acceptance body deleted a fixed six-name tuple, whatever had actually moved and
whatever each of those files was measuring. It could not express "this changed,
therefore that is stale", so it could only express "something changed, therefore
everything is". A tuple also cannot answer the other direction -- a receipt whose
bindings still hold is not stale, and deleting it throws away evidence that is
still true.

**How a binding is read.** Off the receipt itself, not out of a table of what we
believe each receipt depends on. `artifact_manifest.json` carries the digests of
the contract and the three artifacts; a review report carries a whole envelope;
`final_status.json` carries the artifact hashes and the plan digest. Each entry
in `RECEIPTS` says how to read that receipt's own record of what it was issued
against, and `broken()` compares it against what is on disk now.

Two consequences worth stating, because they are what makes this a graph rather
than a list:

* **a receipt may depend on another receipt.** `commission_report.json` records
  the contract it measured against and not the mesh it measured, so on its own it
  cannot tell that the candidate moved. It is issued beside `artifact_manifest.json`,
  which does record it, and it is stale when that one is. Declaring the edge is
  honest about where the digest lives; inventing a digest the file does not carry
  would not be;
* **the acceptance contract reaches the receipts through the model contract.**
  Nothing downstream binds `acceptance_contract.json` directly -- every receipt
  binds `model_contract.json`'s hash, and the model contract carries the
  acceptance contract's. So a new acceptance revision breaks one edge and the
  whole chain below it goes, which is the same set the old tuple named and now
  for a reason that can be read.

**What is not removed.** `model_contract.json` is reported stale and kept. It is
the definition of the `contract` binding's current value, so deleting it would
turn "this receipt was issued against a contract that has since moved" into
"there is no contract here at all", and every other receipt would report the
weaker, less useful thing.

This module reads files and compares digests. It decides nothing about the part:
`status.derive` is what turns a broken binding into a claim a reader is allowed
to make, and it may only ever weaken one.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any, Callable

from . import schemas as S

# The frozen acceptance contract. Defined here rather than in `acceptance.py`
# because this module is what reads it to find the current value of the
# `acceptance` binding, and `acceptance.py` imports it back -- one definition,
# and the import runs one way.
CONTRACT_FILE = "acceptance_contract.json"
# The contract the receipts actually bind: derived from the acceptance contract
# on the authored lane and from the certified template on the other, and hashed
# by `contract.Contract.contract_hash`, which is `payload_hash(as_payload())` --
# so the file on disk re-hashes to the value every receipt carries.
MODEL_CONTRACT_FILE = "model_contract.json"
PLAN_FILE = "execution_plan.json"
WITNESS_DIR = "witness"

CANDIDATE_STL = "candidate.stl"
CANDIDATE_STEP = "candidate.step"
DEFAULT_SOURCE = "model.py"

# How the shared root spells itself. A review taken at the root carries no
# `alternative_id` -- the envelope omits the key rather than writing `null`, so
# that an unbranched job's digests do not move -- and comparing `None` against
# `None` would make the binding unreadable rather than satisfied. The root is a
# real place with its own contract and its own receipts, so it gets a name.
ROOT_ALTERNATIVE = "."

# Every input a receipt in this pipeline can be issued against. A binding a
# receipt does not record is not one it is checked on: `step` is `null` on a job
# that exported no STEP, and a review taken with no plan in hand binds no plan.
BINDING = ("acceptance", "contract", "plan", "stl", "step", "source",
           "alternative")


def _payload(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _digest(path: Path | None) -> str | None:
    return S.sha256_file(path) if path is not None and path.is_file() else None


def _within(base: Path, name: Any) -> Path | None:
    """A declared filename resolved under `base`, or None if it would leave it.

    Every name here comes out of a JSON file -- a frozen contract's
    `expected_artifacts`, a review envelope's witness and evidence lists -- which
    is untrusted text like any other declared path in this pipeline, and goes
    through the one resolver that proves it stays inside.
    """
    try:
        return S.resolve_within(base, name, what="bound file")
    except S.PathEscape:
        return None


def current(work_dir: Path, *, alternative_id: str | None = None,
            model_name: str | None = None) -> dict[str, str | None]:
    """The value each binding has right now, read off this formulation's files.

    `work_dir` is the project root for an unbranched job and `alternatives/<id>`
    for a branched one -- the same scoping every other per-formulation file
    follows, so a sibling's artifacts are never what this one is checked against.

    On the certified lane there is no frozen acceptance contract: the contract is
    derived from the project and the template at run time, so `acceptance` is
    absent and `contract` is whatever the last run wrote down. A certified job
    whose *parameters* moved is therefore caught by re-running, not by reading --
    which is worth saying out loud rather than leaving a reader to assume this
    function sees more than it does.
    """
    work_dir = Path(work_dir)
    frozen = _payload(work_dir / CONTRACT_FILE) or {}
    expected = frozen.get("expected_artifacts")
    expected = expected if isinstance(expected, dict) else {}
    model_contract = _payload(work_dir / MODEL_CONTRACT_FILE)
    plan = _payload(work_dir / PLAN_FILE)
    return {
        "acceptance": frozen.get("contract_sha256"),
        "contract": None if model_contract is None else S.payload_hash(model_contract),
        "plan": None if plan is None else S.payload_hash(plan),
        "stl": _digest(_within(work_dir, expected.get("stl") or CANDIDATE_STL)),
        "step": _digest(_within(work_dir, expected.get("step") or CANDIDATE_STEP)),
        "source": _digest(_within(
            work_dir, expected.get("source") or model_name or DEFAULT_SOURCE)),
        "alternative": alternative_id or ROOT_ALTERNATIVE,
    }


# ---------------------------------------------------------------------------
# What each receipt records about what it was issued against
# ---------------------------------------------------------------------------

def _model_contract(payload: dict[str, Any]) -> dict[str, Any]:
    """The one edge from the frozen acceptance contract into everything else.

    `source` is the authored lane's `AcceptanceSource.as_source()`. A certified
    template has no `as_source`, so `source` is null and this receipt binds no
    acceptance contract -- correctly, because on that lane there is not one.
    """
    source = payload.get("source")
    if not isinstance(source, dict):
        return {}
    return {"acceptance": source.get("acceptance_contract_sha256")}


def _artifact_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    return {"contract": payload.get("contract_sha256"),
            "stl": payload.get("stl_sha256"),
            "step": payload.get("step_sha256"),
            "source": payload.get("source_sha256")}


def _commission(payload: dict[str, Any]) -> dict[str, Any]:
    return {"contract": payload.get("contract_hash")}


def _manufacturing(payload: dict[str, Any]) -> dict[str, Any]:
    return {"contract": payload.get("contract_sha256")}


def _envelope(payload: dict[str, Any]) -> dict[str, Any]:
    env = payload.get("review_envelope")
    return env if isinstance(env, dict) else {}


def _review(payload: dict[str, Any]) -> dict[str, Any]:
    """A review's bindings are its envelope's, which is the point of an envelope.

    An error report -- written when a stored answer would not parse or would not
    bind -- carries no envelope and therefore binds nothing. It is not a claim
    about the part, so there is nothing for it to have gone stale against.
    """
    env = _envelope(payload)
    if not env:
        return {}
    hashes = env.get("artifact_hashes")
    hashes = hashes if isinstance(hashes, dict) else {}
    return {"contract": env.get("contract_sha256"),
            "stl": hashes.get("stl"),
            "step": hashes.get("step"),
            "source": hashes.get("source"),
            "plan": env.get("execution_plan_sha256"),
            "alternative": env.get("alternative_id") or ROOT_ALTERNATIVE}


def _review_files(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The witness images and evidence files the reviewer was shown.

    Bound by the envelope already, and checkable without re-running anything:
    these are files on disk with digests in the answer. A caliper sheet corrected
    after the review is exactly the change that must unbind the review and
    nothing else.
    """
    env = _envelope(payload)
    out: dict[str, dict[str, Any]] = {}
    for key, base in (("witness_hashes", "witness"), ("evidence_hashes", "evidence")):
        entries = env.get(key)
        if isinstance(entries, dict) and entries:
            out[base] = dict(entries)
    return out


def _final_status(payload: dict[str, Any]) -> dict[str, Any]:
    hashes = payload.get("artifact_hashes")
    hashes = hashes if isinstance(hashes, dict) else {}
    return {"contract": hashes.get("contract"),
            "stl": hashes.get("stl"),
            "step": hashes.get("step"),
            "source": hashes.get("source"),
            "plan": payload.get("execution_plan_sha256")}


def _status_depends(payload: dict[str, Any]) -> tuple[str, ...]:
    """Which reviews this status promoted, and therefore depends on.

    Read off the receipt rather than assumed: a status that recorded no
    verification decision did not rest on one, and making every status depend on
    a file most jobs never write would report a missing review as staleness.
    """
    owed = ["commission_report.json"]
    if payload.get("verification") is not None:
        owed.append("verification_report.json")
    if payload.get("safety_verification") is not None:
        owed.append("safety_verification_report.json")
    return tuple(owed)


@dataclasses.dataclass(frozen=True)
class Receipt:
    """One file the pipeline writes, and how to read what it was issued against."""

    name: str
    binds: Callable[[dict[str, Any]], dict[str, Any]]
    # Other receipts this one was issued beside. An edge, not a digest: it is
    # here exactly where the receipt does not carry a digest of its own for
    # something it plainly depends on, and saying so is more honest than
    # pretending the file records more than it does.
    depends_on: Callable[[dict[str, Any]], tuple[str, ...]] = lambda payload: ()
    # Named files with digests inside the receipt, keyed by which directory they
    # are relative to: `witness` under the work directory, `evidence` under the
    # project root.
    files: Callable[[dict[str, Any]], dict[str, dict[str, Any]]] = \
        lambda payload: {}
    removable: bool = True


# In dependency order. `broken()` walks it once and reads the staleness of a
# receipt's dependencies out of what it has already decided, so an entry must
# never come before something it depends on.
RECEIPTS: tuple[Receipt, ...] = (
    # Not removable: this is the contract every other receipt binds, and deleting
    # it would turn "issued against a contract that has moved" into "there is no
    # contract", which says less and is no more true.
    Receipt(MODEL_CONTRACT_FILE, _model_contract, removable=False),
    Receipt("artifact_manifest.json", _artifact_manifest,
            depends_on=lambda payload: (MODEL_CONTRACT_FILE,)),
    # The commissioning report records the contract it measured against and not
    # the mesh it measured; the manifest is where that digest lives.
    Receipt("commission_report.json", _commission,
            depends_on=lambda payload: (MODEL_CONTRACT_FILE,
                                        "artifact_manifest.json")),
    # The manufacturing report carries the commissioning verdict.
    Receipt("manufacturing_report.json", _manufacturing,
            depends_on=lambda payload: ("commission_report.json",)),
    # Both reviews were shown the commissioning report inside their packet.
    Receipt("safety_verification_report.json", _review, files=_review_files,
            depends_on=lambda payload: ("commission_report.json",)),
    Receipt("verification_report.json", _review, files=_review_files,
            depends_on=lambda payload: ("commission_report.json",)),
    Receipt("final_status.json", _final_status, depends_on=_status_depends),
)

# What an invalidation may remove. Derived from the table rather than restated,
# so a receipt added above is covered by construction; it happens to be the same
# six files the hardcoded tuple named, which is the point -- the set did not need
# to change, the reason for it did.
REMOVABLE = tuple(receipt.name for receipt in RECEIPTS if receipt.removable)


def _short(digest: Any) -> str:
    if not isinstance(digest, str):
        return "absent"
    return digest[:12] if len(digest) > 12 else digest


def broken(work_dir: Path, *, evidence_dir: Path | None = None,
           alternative_id: str | None = None,
           model_name: str | None = None) -> dict[str, tuple[str, ...]]:
    """Every receipt whose bindings no longer hold, and which ones broke.

    A receipt that is absent is absent, not stale -- there is nothing to have
    gone stale. A receipt that cannot be parsed is stale by that fact alone: a
    record of what something was issued against that cannot be read cannot be
    checked, and a reader who is told nothing is wrong has been told something
    false.
    """
    work_dir = Path(work_dir)
    evidence_dir = Path(evidence_dir) if evidence_dir is not None else work_dir
    now = current(work_dir, alternative_id=alternative_id, model_name=model_name)
    stale: dict[str, tuple[str, ...]] = {}

    for receipt in RECEIPTS:
        path = work_dir / receipt.name
        if not path.is_file():
            continue
        payload = _payload(path)
        if payload is None:
            stale[receipt.name] = (
                "it is not readable JSON, so what it was issued against cannot "
                "be compared with what is on disk",)
            continue

        reasons: list[str] = []
        for name, was in sorted(receipt.binds(payload).items()):
            if was is None:
                # Recorded as absent means it was never bound: no STEP was
                # exported, no plan was in hand. A binding a receipt does not
                # claim is not one it can fail.
                continue
            if was != now.get(name):
                reasons.append(f"{name}: issued against {_short(was)}, "
                               f"now {_short(now.get(name))}")
        for base, entries in sorted(receipt.files(payload).items()):
            root = work_dir / WITNESS_DIR if base == "witness" else evidence_dir
            for relative, was in sorted(entries.items()):
                target = _within(root, relative)
                if target is None:
                    reasons.append(f"{base} {relative}: not a name that stays "
                                   "inside the directory it was hashed in")
                    continue
                found = _digest(target)
                if was != found:
                    reasons.append(f"{base} {relative}: issued against "
                                   f"{_short(was)}, now {_short(found)}")
        for other in receipt.depends_on(payload):
            if other in stale:
                reasons.append(f"{other}, which it was issued beside, is stale")
            elif not (work_dir / other).is_file():
                reasons.append(f"{other}, which it was issued beside, is no "
                               "longer on disk")
        if reasons:
            stale[receipt.name] = tuple(reasons)
    return stale


def invalidate(work_dir: Path, *, evidence_dir: Path | None = None,
               alternative_id: str | None = None,
               model_name: str | None = None) -> dict[str, Any]:
    """Remove the receipts whose bindings no longer hold, recording them first.

    Deleting rather than leaving them, for the reason the acceptance revision
    already gave: `final_status.json` is what a reader and `design-tool status`
    treat as the job's answer, and an answer issued against evidence that has
    since moved is worse than no answer. What is new is the *scope* -- a receipt
    whose bindings still hold is still true and stays on disk, so a changed
    review evidence file no longer takes the commissioning measurements with it.

    The digest of everything removed comes back so the caller can record it: a
    superseded pass must be neither current nor erased.
    """
    stale = broken(work_dir, evidence_dir=evidence_dir,
                   alternative_id=alternative_id, model_name=model_name)
    removed: dict[str, Any] = {}
    for receipt in RECEIPTS:
        if not receipt.removable or receipt.name not in stale:
            continue
        path = Path(work_dir) / receipt.name
        if not path.is_file():
            continue
        removed[receipt.name] = {"sha256": S.sha256_file(path),
                                 "broke": list(stale[receipt.name])}
        path.unlink()
    return removed
