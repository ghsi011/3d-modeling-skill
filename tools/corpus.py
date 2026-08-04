#!/usr/bin/env python3
"""Fetch and verify the external reference corpus, and never write into the repo.

`benchmarks/corpus.json` names reference geometry by stable identity and hash.
The bytes themselves are third-party and stay outside this repository --
`AGENTS.md` forbids licensed third-party artifacts in it, and `ARCHITECTURE.md`
16.6 says a large or non-redistributable corpus stays external and is referenced
by identity and hash. This module is the loader that makes that referencing real
rather than aspirational.

**Why a manifest and not a directory.** A benchmark whose reference is "whatever
is in that folder" measures whatever happened to be in that folder. Every entry
here carries the digest of the exact bytes it means, so a corpus that has drifted
is a loud failure rather than a quietly different answer. The one property a
blind benchmark cannot do without is that the reference is the reference.

**What this module deliberately does not do.** It does not read geometry, does
not measure anything, and does not grade. The reference *answer* is the bytes on
disk, and the only door to them is `resolve`, which a grader calls and a design
agent has no reason to have written -- the same shape `tools/fixtures.py` keeps
for its own answers, for the reason its docstring gives at length.

**What it does do, and what took three attempts to get right.** A blind
benchmark also has a *question*, and the question is written from this manifest,
so the manifest can leak the answer without anybody touching an STL.

The first two defences were rules about *digits*. A regular expression matching a
number next to a unit; then, after a review broke that a dozen ways in one pass,
a flat "no digit in any string" with an exemption list, which a second review
broke in nineteen. Both were hardened, and both were answering the wrong
question. A real request is **full of measurements** -- somebody takes calipers
to the extrusion slot, the panel, the rail, and writes the numbers down -- and a
request stripped of them is not a hard benchmark, it is an unanswerable one.

The question is not whether a number appears. It is **what the number measures**:

* *the counterpart* -- the slot the part sits in, the panel it retains, the rail
  it aligns, the bolt through it. Allowed, and required: that is the caliper
  work, and `provenance: MEASURED` is what a requester actually produces.
* *the part itself* -- its envelope, its volume, its wall thickness, its body
  count. Withheld, because that is what a blind reconstruction has to produce
  and what the scorer compares it on.

So `request_view` is the only door to question material, `purpose` is prose that
may carry digits but may not name the part's own geometry, and `requirements`
are `project.Requirement` rows -- the same shape `project.json` consumes, so a
generator writes them through rather than translating them.

The claim this supports, exactly: *no requirement names the reference part's own
geometry, and every requirement carries a provenance a requester could have.*
Not "no measurement of the part can leak" -- an author can write
`extrusion_slot_width: 20.0` when 20.0 is the part's own x-extent, and no rule
here can tell. A weaker method may not issue a stronger claim.

**Absence is not failure.** A checkout with none of this fetched is a normal
checkout: `resolve` raises `CorpusUnavailable`, and a fixture that names an entry
reports it as unavailable rather than skipping in silence. What is *not*
tolerated is a file that is present and wrong.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "benchmarks" / "corpus.json"

# Where fetched geometry lands. The manifest names a default; the environment
# overrides it, so a machine that keeps its corpus elsewhere does not have to
# edit a committed file to say so.
ROOT_ENV = "DESIGN_TOOL_CORPUS_ROOT"


class CorpusUnavailable(FileNotFoundError):
    """A named entry is not on this machine. Fetch it, or accept the gap."""


class CorpusCorrupt(ValueError):
    """A named entry is on this machine and is not the bytes it claims to be.

    Separate from `CorpusUnavailable` and never softened into it. Missing is a
    machine that has not fetched; wrong is a reference that has drifted, and a
    benchmark scored against a drifted reference produces a number that looks
    exactly like a real one.
    """


class CorpusLeak(ValueError):
    """Question material carries something only the reference can answer.

    A hard failure and never a warning. The whole value of a blind benchmark is
    that the candidate did not have the answer, and a benchmark that leaked it
    reports a number indistinguishable from one that did not -- the same
    argument `CorpusCorrupt` makes about a drifted reference, one layer up.
    """


def manifest() -> dict[str, Any]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# The wall between the question and the answer
# --------------------------------------------------------------------------

# The keys a request generator may be handed. Adding one is an edit here and an
# edit to the test that pins this tuple. The design before this had an
# *exemption* list instead, and an exemption list grows silently every time an
# ordinary field needs a digit in it -- a sparse-checkout path, a second corpus
# root -- and each growth reopened the hole invisibly.
REQUEST_KEYS = ("purpose", "requirements")

# Every field of one requirement, and they are `project.Requirement`'s fields
# rather than a shape invented here. A generator writes these straight into
# `project.json`, so a second vocabulary would be a translation layer and a
# place for the two to disagree.
REQUIREMENT_KEYS = ("name", "value", "unit", "provenance", "source", "note")

# `project.PROVENANCE`, restated as the subset a *request* can honestly carry.
# `INHERITED` means "read out of a supplied artifact", which is a MODIFY job's
# answer and not a requester's measurement; `CHOSEN` is a decision the pipeline
# makes downstream. What a person with calipers produces is `MEASURED`, and what
# a datasheet or a standard gives them is `STATED`.
REQUEST_PROVENANCE = ("MEASURED", "STATED")

# THE RULE, and it took three designs plus a fourth correction to find.
#
# A request may carry measurements -- that is the whole point, somebody takes
# calipers to the extrusion slot and writes the number down. What it may not
# carry is a measurement of the *reference part itself*. Two mechanisms, because
# one of them cannot be done with words at all.
#
# **Names are allowlisted.** A requirement must measure a declared counterpart:
# its name's leading token must be one of the entry's own `counterparts`. This
# replaced a denylist of twenty words that an independent review walked through
# about eighty times -- `girth`, `ht`, `part_thickness`, `overall`, `span`,
# fullwidth `ｅｎｖｅｌｏｐｅ` -- and four of whose own entries could never match,
# because the tokenizer split on underscores and `bounding_box` has one. A
# denylist grows when somebody thinks of a synonym, which is never, and fails
# silently. An allowlist grows when an entry is added, which is a line in a diff.
# `REQUEST_KEYS`, `REQUIREMENT_KEYS` and `REQUEST_PROVENANCE` are the same shape,
# and they are the three things nothing got through.
#
# **Numbers are checked against the reference.** No wording rule can catch
# `extrusion_series: "2020"` on a part whose x-extent is exactly 20.0 mm --
# which is not hypothetical, it is what this manifest shipped. So when the
# corpus is on this machine, every number anywhere in the question is compared
# against the reference's own extents and volume, and a coincidence is refused.
# That check operates on the thing the claim is about; everything else operates
# on how somebody spelled it.

# How close a stated number may come to one of the reference's own measurements
# before it stops being a coincidence. Relative, because a 0.1 mm agreement on a
# 5 mm wall means something different from 0.1 mm on a 30 mm span.
COINCIDENCE_FRACTION = 0.02

_TOKEN = re.compile(r"[^\W\d_]+", re.UNICODE)
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def counterpart_of(name: str, counterparts: tuple[str, ...]) -> str | None:
    """Which declared counterpart this requirement measures, or None.

    The leading token, so `extrusion_slot_opening` measures the `extrusion` and
    `panel_stock` measures the `panel`. A name that leads with nothing declared
    is refused rather than guessed at -- `girth` names no counterpart, and the
    whole failure of the previous design was that it named nothing the rule
    happened to know about either.
    """
    tokens = _TOKEN.findall(name.lower())
    if not tokens:
        return None
    return tokens[0] if tokens[0] in counterparts else None


def numbers_in(node: Any) -> tuple[float, ...]:
    """Every number anywhere in a question, whatever field or type it sits in.

    Values, prose, units, sources and notes alike, and inside nested containers.
    A review found the previous design scanned `name` and `note` only, so a
    measurement in `source` -- "calipers; the part measures 20.0 x 14.5 x 5.8"
    -- was copied into the request untouched.
    """
    out: list[float] = []
    if isinstance(node, bool):
        return ()
    if isinstance(node, (int, float)):
        return (float(node),)
    if isinstance(node, str):
        return tuple(float(m) for m in _NUMBER.findall(node))
    if isinstance(node, dict):
        for key, value in node.items():
            out += list(numbers_in(key)) + list(numbers_in(value))
    elif isinstance(node, (list, tuple)):
        for value in node:
            out += list(numbers_in(value))
    return tuple(out)


def reference_measurements(entry_id: str,
                           payload: dict[str, Any] | None = None
                           ) -> dict[str, float]:
    """What the reference actually is: its extents and its volume.

    The answer, read off the bytes `resolve` vouches for. Only a grader and this
    module's own coincidence check may call it, and it raises rather than
    guessing when the corpus is not on this machine -- `request_view` catches
    that and says what it could not check.
    """
    import trimesh                                   # local: heavy, and a grader-only path

    mesh = trimesh.load(str(resolve(entry_id, payload)), force="mesh")
    extents = [float(v) for v in mesh.bounding_box.extents]
    return {"extent_x": extents[0], "extent_y": extents[1], "extent_z": extents[2],
            "volume_mm3": float(mesh.volume)}


def coincidences(stated: tuple[float, ...],
                 measured: dict[str, float]) -> tuple[tuple[float, str], ...]:
    """Numbers in the question that are also measurements of the part.

    A number is a coincidence when it lands within `COINCIDENCE_FRACTION` of one
    of the reference's own measurements, or of a plain multiple of an extent --
    "2020 extrusion" states 20 as part of 2020, and a part 20.0 mm across is
    then described by its own answer.
    """
    found: list[tuple[float, str]] = []
    for value in stated:
        if value <= 0:
            continue
        for name, truth in measured.items():
            if truth <= 0:
                continue
            for candidate in {value, value / 100.0, value / 10.0}:
                if abs(candidate - truth) <= truth * COINCIDENCE_FRACTION:
                    found.append((value, name))
                    break
            else:
                continue
            break
    return tuple(dict.fromkeys(found))


def _requirement(entry_id: str, index: int, row: Any,
                 counterparts: tuple[str, ...]) -> dict[str, Any]:
    """One measured fact about what the part must fit, checked before it ships."""
    if not isinstance(row, dict):
        raise CorpusLeak(
            f"{entry_id}: requirements[{index}] is {type(row).__name__}, not a "
            "requirement")
    unknown = sorted(set(row) - set(REQUIREMENT_KEYS))
    if unknown:
        raise CorpusLeak(
            f"{entry_id}: requirements[{index}] carries {', '.join(unknown)}, "
            f"and a requirement is {', '.join(REQUIREMENT_KEYS)}.")
    # Every string field, not two of them. A review put the part's bounding box
    # in `source` -- "calipers; the part measures 20.0 x 14.5 x 5.8" -- and in
    # `unit`, and watched both reach the request untouched.
    for field in ("name", "provenance", "source", "unit", "note"):
        if field in row and not isinstance(row[field], str):
            raise CorpusLeak(
                f"{entry_id}: requirements[{index}].{field} must be a string, "
                f"not {type(row[field]).__name__}. A list or a dict is a place "
                "to hide three numbers where a rule looks for one.")
    for field in ("name", "provenance", "source"):
        if not str(row.get(field, "")).strip():
            raise CorpusLeak(
                f"{entry_id}: requirements[{index}] has no {field}. A "
                "measurement with no source is one nobody can go back and check")
    if row["provenance"] not in REQUEST_PROVENANCE:
        raise CorpusLeak(
            f"{entry_id}: requirements[{index}].provenance is "
            f"{row['provenance']!r}; a request carries "
            f"{list(REQUEST_PROVENANCE)}. INHERITED is read out of a supplied "
            "artifact and CHOSEN is decided downstream -- neither is something "
            "a requester measured.")

    value = row.get("value")
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise CorpusLeak(
            f"{entry_id}: requirements[{index}].value must be a number or a "
            f"catalogue name, not {type(value).__name__}. A list or a dict is "
            "a bounding box with the brackets left on.")
    numeric = isinstance(value, (int, float))
    unit = str(row.get("unit", ""))
    if numeric and not unit.strip():
        raise CorpusLeak(
            f"{entry_id}: requirements[{index}] measures {value} and names no "
            "unit. A bare number is not a measurement.")
    if not numeric:
        if unit.strip():
            raise CorpusLeak(
                f"{entry_id}: requirements[{index}] has value {value!r} and "
                f"unit {unit!r}. A catalogue name takes no unit.")
        if not value.strip():
            raise CorpusLeak(f"{entry_id}: requirements[{index}] has no value")

    # The allowlist. A requirement measures a declared counterpart or it does
    # not ship -- which is the whole of what replaced twenty denied words.
    if counterpart_of(row["name"], counterparts) is None:
        raise CorpusLeak(
            f"{entry_id}: requirements[{index}] is named {row['name']!r}, which "
            f"leads with no declared counterpart. This entry declares "
            f"{list(counterparts)}; a requirement measures one of them -- "
            "`extrusion_slot_opening`, `panel_stock`, `rail_across_flats` -- or "
            "it is measuring the part, which is the answer.")
    return {key: row[key] for key in REQUIREMENT_KEYS if key in row}


def request_view(entry_id: str,
                 payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """One entry's question material, and nothing else about it.

    Carries no id, no path, no digest and no source: an identifier is a place a
    measurement hides -- the first version of this manifest called an entry
    `voron-deck-support-3mm` -- and a path is one `ls` away from the answer.

    **What this guarantees.** Two keys, six requirement fields, each typed.
    Every requirement names a counterpart this entry declares, carries a
    provenance a requester could have, and pairs a number with a unit or a
    catalogue name with none. And -- when the corpus is on this machine -- no
    number anywhere in the question coincides with one of the reference's own
    extents or its volume.

    **What it does not.** With the corpus absent that last check cannot run, and
    the view says `checked_against_reference: False` rather than implying a
    check nobody performed. A purpose can still describe a shape in words that
    carry no number at all. A weaker method may not issue a stronger claim, so
    the guarantee is the paragraph above and not "the answer cannot leak".
    """
    payload = payload if payload is not None else manifest()
    row = entries(payload).get(entry_id)
    if row is None:
        raise KeyError(f"{entry_id!r} names no corpus entry; have "
                       f"{sorted(entries(payload))}")

    counterparts = tuple(row.get("counterparts") or ())
    if not counterparts or not all(isinstance(c, str) and c.strip()
                                   for c in counterparts):
        raise CorpusLeak(
            f"{entry_id} declares no counterparts. A blind request measures the "
            "things the part has to fit, so the entry has to say what those "
            "are -- and an entry declaring none would admit any requirement "
            "name at all, which is the denylist this replaced.")

    block = row.get("request")
    if not isinstance(block, dict):
        raise CorpusLeak(
            f"{entry_id} declares no request block. An entry with no question "
            "material is not usable blind, and falling back to its other fields "
            "is how the id and the path got read out loud.")
    unknown = sorted(set(block) - set(REQUEST_KEYS))
    if unknown:
        raise CorpusLeak(
            f"{entry_id}: request carries {', '.join(unknown)}, and only "
            f"{', '.join(REQUEST_KEYS)} may be handed to a generator.")
    missing = sorted(set(REQUEST_KEYS) - set(block))
    if missing:
        raise CorpusLeak(f"{entry_id}: request is missing {', '.join(missing)}")

    purpose = block["purpose"]
    if not isinstance(purpose, str) or not purpose.strip():
        raise CorpusLeak(f"{entry_id}: purpose must be prose saying what the "
                         "part is for")

    rows = block["requirements"]
    if not isinstance(rows, list) or not rows:
        raise CorpusLeak(
            f"{entry_id}: requirements must be a non-empty list. A request with "
            "no measured interface is not answerable -- that is the blind "
            "benchmark being impossible rather than hard.")
    view = {"purpose": purpose,
            "requirements": [_requirement(entry_id, index, item, counterparts)
                             for index, item in enumerate(rows)]}

    # The check that operates on the answer rather than on the wording. Skipped
    # -- and said to be skipped -- when the reference is not on this machine.
    try:
        measured = reference_measurements(entry_id, payload)
    except (CorpusUnavailable, ImportError):
        return {**view, "checked_against_reference": False}
    found = coincidences(numbers_in(view), measured)
    if found:
        detail = "; ".join(f"{value:g} is this part's {name}"
                           for value, name in found)
        raise CorpusLeak(
            f"{entry_id}: the question states a number that is a measurement of "
            f"the reference itself -- {detail}. No wording rule catches this: "
            "an `extrusion_series` of 2020 on a part exactly 20 mm across is a "
            "correctly named counterpart handing over an answer, and it is what "
            "this manifest shipped until this check existed.")
    return {**view, "checked_against_reference": True}


def corpus_root(payload: dict[str, Any] | None = None) -> Path:
    payload = payload if payload is not None else manifest()
    override = os.environ.get(ROOT_ENV)
    if override:
        return Path(override).expanduser()
    return Path(payload["roots"]["default"]).expanduser()


def entries(payload: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    payload = payload if payload is not None else manifest()
    return {row["id"]: row for row in payload["entries"]}


def _digest(path: Path) -> str:
    reader = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            reader.update(block)
    return reader.hexdigest()


def location(entry_id: str, payload: dict[str, Any] | None = None) -> Path:
    payload = payload if payload is not None else manifest()
    row = entries(payload).get(entry_id)
    if row is None:
        raise KeyError(f"{entry_id!r} names no corpus entry; have "
                       f"{sorted(entries(payload))}")
    source = payload["sources"][row["source"]]
    return corpus_root(payload) / source["into"] / row["path"]


def resolve(entry_id: str, payload: dict[str, Any] | None = None) -> Path:
    """The path to one entry's bytes, proven to be the bytes it claims.

    Verified on every call rather than once at fetch time. A digest checked when
    the file arrived says nothing about the file a benchmark is about to read,
    and the cost here is a hash of a file already in the page cache.
    """
    payload = payload if payload is not None else manifest()
    path = location(entry_id, payload)
    if not path.is_file():
        raise CorpusUnavailable(
            f"{entry_id} is not on this machine at {path}. Fetch the corpus: "
            f"`uv run python tools/corpus.py --fetch`")
    want = entries(payload)[entry_id]["sha256"]
    found = _digest(path)
    if found != want:
        raise CorpusCorrupt(
            f"{entry_id} at {path} hashes {found[:12]} and the manifest names "
            f"{want[:12]}. This is a reference that has drifted, which is worse "
            "than one that is missing: a benchmark scored against it would "
            "produce a number indistinguishable from a real one.")
    return path


def fetch(payload: dict[str, Any] | None = None, *,
          which: str | None = None) -> list[str]:
    """Clone each declared source at its pinned ref. Idempotent.

    Pinned to a commit rather than a branch, because a branch is a moving
    reference and the digests below are not. A source already present at the
    right commit is left alone.
    """
    payload = payload if payload is not None else manifest()
    root = corpus_root(payload)
    root.mkdir(parents=True, exist_ok=True)
    done: list[str] = []
    for name, source in sorted(payload["sources"].items()):
        if which and name != which:
            continue
        if source["kind"] != "git":
            raise ValueError(f"{name}: unsupported source kind "
                             f"{source['kind']!r}")
        into = root / source["into"]
        if (into / ".git").is_dir():
            head = subprocess.run(["git", "-C", str(into), "rev-parse", "HEAD"],
                                  capture_output=True, text=True).stdout.strip()
            if head == source["ref"]:
                done.append(f"{name}: already at {head[:12]}")
                continue
            shutil.rmtree(into)
        subprocess.run(
            ["git", "clone", "--filter=blob:none", "--sparse", "--no-checkout",
             source["url"], str(into)], check=True)
        subprocess.run(["git", "-C", str(into), "sparse-checkout", "set",
                        *source["sparse"]], check=True)
        subprocess.run(["git", "-C", str(into), "checkout", source["ref"]],
                       check=True)
        done.append(f"{name}: fetched {source['ref'][:12]}")
    return done


def verify(payload: dict[str, Any] | None = None) -> dict[str, str]:
    """Every entry's state, as a mapping a caller can act on."""
    payload = payload if payload is not None else manifest()
    out: dict[str, str] = {}
    for entry_id in sorted(entries(payload)):
        try:
            resolve(entry_id, payload)
            out[entry_id] = "OK"
        except CorpusUnavailable:
            out[entry_id] = "MISSING"
        except CorpusCorrupt:
            out[entry_id] = "CORRUPT"
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tools/corpus.py",
        description="Fetch and verify external reference geometry. Nothing this "
                    "writes goes inside the repository.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--fetch", action="store_true")
    group.add_argument("--verify", action="store_true")
    group.add_argument("--where", metavar="ENTRY")
    parser.add_argument("--source", default=None)
    args = parser.parse_args(argv)

    payload = manifest()
    if args.fetch:
        for line in fetch(payload, which=args.source):
            print(f"  {line}")
        args.verify = True

    if args.verify:
        state = verify(payload)
        for entry_id, how in state.items():
            print(f"  {how:8s} {entry_id}")
        bad = [k for k, v in state.items() if v == "CORRUPT"]
        print(f"\n{sum(1 for v in state.values() if v == 'OK')}/{len(state)} "
              f"verified, root {corpus_root(payload)}")
        return 1 if bad else 0

    print(resolve(args.where, payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
