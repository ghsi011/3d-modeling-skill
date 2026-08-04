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
not measure anything, and does not know what any entry is *for*. The wall
between benchmark request material and reference answers lives in
`tools/fixtures.py`, which keeps its answers in a private mapping a design agent
has no reason to have called. Putting a fetcher on the same object would put the
answer one attribute away from the request, which is the failure that module's
docstring already describes at length.

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
import shutil
import subprocess
import sys
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


def manifest() -> dict[str, Any]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


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
