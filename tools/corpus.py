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

**What it does do, and what took two attempts to get right.** A blind benchmark
also has a *question*, and the question is written from this manifest. So the
manifest can leak the answer without anybody touching an STL: a note reading
"supports a three-millimetre panel, twenty by fourteen point five by five point
eight" hands over the reconstruction. The first defence was a regular expression
in a test, matching a number next to a unit. An independent review broke it in a
dozen ways in one pass, and a second review broke its replacement in nineteen --
by putting the measurement in a JSON number, in a dict *key*, in an exempt field,
in a fullwidth digit, in a Roman numeral, and in the entry id.

Both failures have one shape: a rule that lives in a test can only ever describe
the committed text, and the leak happens in the *data path* -- whatever a request
generator is handed. So the rule lives here now, `request_view` is the only
sanctioned door to question material, and it is a whitelist twice over. Two keys
are permitted and their types are pinned, so a number, a nested dict, a dict key
and an unknown field have nowhere to be. `purpose` is free prose and may carry no
numeric character, numeral or number-word at all. `interfaces` may carry
measurements -- "3 mm flat panel" is what makes the task answerable -- but only
terms on the manifest's own `request_vocabulary`, which is a **declared
disclosure**: the list of dimensions the benchmark gives away, written down where
a reader can see the whole of it, rather than an exemption nobody can enumerate.

The claim this supports, exactly: *no numeric character, numeral or number-word
reaches question material except through a term on a committed list.* Not "no
measurement can leak" -- a purpose could still describe a shape in words. A
weaker method may not issue a stronger claim.

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
import unicodedata
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

# The only keys a request generator may be handed. Adding one is an edit here
# and an edit to the test that pins this tuple -- which is the point. The
# previous design had an *exemption* list instead, and an exemption list grows
# silently every time an ordinary field needs a digit in it: a sparse-checkout
# path, a second corpus root, a licence name. Each such growth reopened the hole,
# and nobody reviewing the one-line diff could see that it had.
REQUEST_KEYS = ("purpose", "interfaces")

# `Nd` is what `\d` means and it is not enough on its own: superscripts and
# vulgar fractions are `No`, and Roman-numeral letters are `Nl` only when they
# are the dedicated Unicode codepoints rather than ASCII `X`. So all three
# categories, plus the two things Unicode does not classify as numeric at all.
_NUMERIC_CATEGORIES = frozenset({"Nd", "Nl", "No"})

# ASCII Roman numerals of two characters or more. `I` alone is excluded: it is
# the English pronoun, and a rule that refuses it refuses ordinary prose.
_ROMAN = re.compile(
    r"^(?=[IVXLCDM]{2,}$)M{0,4}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})"
    r"(?:IX|IV|V?I{0,3})$")

# Spelled-out numbers, which every digit-scanning rule misses. `Twenty by
# fourteen` defeated the previous guard and is the reason this set exists.
# Count words are here too -- "single body" states the `bodies` check's result,
# which is a measurement the run makes and therefore an answer.
_NUMBER_WORDS = frozenset("""
    zero one two three four five six seven eight nine ten eleven twelve
    thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty
    thirty forty fifty sixty seventy eighty ninety hundred thousand million
    first second third fourth fifth sixth seventh eighth ninth tenth
    half quarter third dozen pair single double triple twice thrice once
    """.split())


def leaks(text: str) -> tuple[str, ...]:
    """Every token in `text` that states a quantity. Empty means it states none.

    One function, called by `request_view` at runtime and by the tests that
    claim it bites. The previous version had the rule written out twice -- once
    in the enforcing test and once in the test that proved it enforced -- so the
    proof was a tautology over its own literals, and the enforcing rule could be
    deleted outright with the suite green. Mutating this function now fails both.
    """
    found: list[str] = []
    found += [ch for ch in text
              if unicodedata.category(ch) in _NUMERIC_CATEGORIES]
    for token in re.findall(r"[A-Za-z]+", text):
        if _ROMAN.match(token) or token.casefold() in _NUMBER_WORDS:
            found.append(token)
    return tuple(dict.fromkeys(found))


def request_view(entry_id: str,
                 payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """One entry's question material, and nothing else about it.

    Carries no id, no path, no digest and no source: an identifier is a place a
    measurement hides -- the first version of this manifest called an entry
    `voron-deck-support-3mm` -- and a path is one `ls` away from the answer,
    which is the failure `tools/fixtures.py` records at its line 30.
    """
    payload = payload if payload is not None else manifest()
    row = entries(payload).get(entry_id)
    if row is None:
        raise KeyError(f"{entry_id!r} names no corpus entry; have "
                       f"{sorted(entries(payload))}")

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
            f"{', '.join(REQUEST_KEYS)} may be handed to a generator. A key "
            "nobody vetted is a key nobody scanned.")
    missing = sorted(set(REQUEST_KEYS) - set(block))
    if missing:
        raise CorpusLeak(f"{entry_id}: request is missing {', '.join(missing)}")

    purpose = block["purpose"]
    if not isinstance(purpose, str):
        raise CorpusLeak(
            f"{entry_id}: purpose is {type(purpose).__name__}, not prose. A "
            "number needs no digit character to be a number.")
    stated = leaks(purpose)
    if stated:
        raise CorpusLeak(
            f"{entry_id}: purpose states {', '.join(map(repr, stated))}. A "
            "purpose names what a part is for; what size it is, is the answer. "
            f"A measurement belongs in interfaces, on the declared disclosure.")

    interfaces = block["interfaces"]
    if not isinstance(interfaces, list) or \
            not all(isinstance(term, str) for term in interfaces):
        raise CorpusLeak(f"{entry_id}: interfaces must be a list of strings")
    vocabulary = payload.get("request_vocabulary") or ()
    outside = [term for term in interfaces if term not in vocabulary]
    if outside:
        raise CorpusLeak(
            f"{entry_id}: {', '.join(map(repr, outside))} is not on this "
            "manifest's request_vocabulary. Interfaces may carry measurements "
            "-- that is what makes the task answerable -- but only ones the "
            "manifest declares it is giving away, so the disclosure can be read "
            "in one place instead of inferred from every entry.")

    return {"purpose": purpose, "interfaces": list(interfaces)}


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
