#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Snapshot a job mid-pipeline so a change can be tested against one phase.

Measuring a skill change by running a whole job is a 15-to-90 minute loop, and
almost all of it re-derives work the change did not touch. A full Langstroth
hive spent most of its 93 minutes on phases that were already right.

The phases are separated by files, which is the one useful consequence of the
whole pipeline talking through a project directory: a job at any boundary *is*
its directory. Snapshot it there, and a later run can be handed that state and
asked for only the next phase. Changing the verifier's charter no longer costs a
build; changing a template no longer costs a routing decision.

    uv run python tools/bench.py save     --project <dir> --as routed
    uv run python tools/bench.py restore   --snapshot routed --to <fresh-dir>
    uv run python tools/bench.py list
    uv run python tools/bench.py diff     --snapshot routed --project <dir>
    uv run python tools/bench.py preamble               # paste into every benchmark prompt

A snapshot is a plain directory copy under the snapshot root, so it can be read,
diffed and edited by hand. Nothing here is clever, and that is the point: the
thing being measured is the agent, and a harness with its own behaviour would be
one more variable in the measurement.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

# Kept out of the repo: snapshots are measurement scratch, sometimes large, and
# never an input to the skill.
DEFAULT_ROOT = Path(os.environ.get("BENCH_SNAPSHOT_ROOT")
                    or Path.home() / ".cache" / "3d-modeling-bench")

# Everything is carried, including renders: visual acceptance is a phase, and
# a resumed run that has to re-render has paid for a build it was meant to skip.
# Only caches are dropped.
SKIP_DIRS = {"__pycache__", ".git"}

# Handed to every benchmark agent, because a measurement of this skill has to be
# a measurement of *this* skill. A host can have other skills installed whose
# trigger descriptions cover the same ground -- one here fires on "3D print",
# "STL", "enclosure" and "bracket" and opens by telling the reader to
# pip install a CAD kernel, which is the opposite of the design being measured.
# Nothing in a subagent's environment stops both loading, and a run that followed
# the wrong one would look like a result rather than a mistake.
PREAMBLE = """Use only the skill at the path this prompt names. Your host may have other skills
installed whose descriptions cover 3D printing, STL, CAD or parametric modelling;
they are not what is being measured here. Do not load, read or follow any of them.
If one loads on its own, say so in your report and name it -- that is a finding
about the measurement, and I would rather know than have it quietly average in.
"""


def _files(project: Path) -> list[Path]:
    out: list[Path] = []
    for path in sorted(project.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(project).parts):
            continue
        out.append(path)
    return out


def _fingerprint(project: Path) -> dict[str, str]:
    """What is in the directory, by content, so a resumed run can be shown to
    have started from the state it claims."""
    return {
        str(path.relative_to(project)).replace("\\", "/"):
            hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        for path in _files(project)
    }


def save(project: Path, name: str, root: Path, note: str | None) -> int:
    if not project.is_dir():
        sys.stderr.write(f"bench: no such project directory: {project}\n")
        return 2
    target = root / name
    if target.exists():
        sys.stderr.write(f"bench: snapshot {name!r} already exists at {target}. "
                         "Pick another name or delete that one -- overwriting a "
                         "snapshot silently would make an earlier measurement "
                         "unreproducible.\n")
        return 1
    target.mkdir(parents=True)
    shutil.copytree(project, target / "project",
                    ignore=shutil.ignore_patterns(*SKIP_DIRS))
    (target / "manifest.json").write_text(json.dumps({
        "name": name,
        "source": str(project),
        "note": note or "",
        "files": _fingerprint(project),
    }, indent=2), encoding="utf-8")
    sys.stdout.write(f"{target}\n  {len(_fingerprint(project))} files\n")
    return 0


def restore(name: str, destination: Path, root: Path) -> int:
    source = root / name / "project"
    if not source.is_dir():
        sys.stderr.write(f"bench: no snapshot named {name!r} under {root}\n")
        return 2
    if destination.exists() and any(destination.iterdir()):
        sys.stderr.write(f"bench: {destination} is not empty. Restore into a fresh "
                         "directory -- a run that starts on top of another run's "
                         "output is not measuring what it says it is.\n")
        return 1
    shutil.copytree(source, destination, dirs_exist_ok=True)
    sys.stdout.write(f"{destination}\n")
    return 0


def listing(root: Path) -> int:
    if not root.is_dir():
        sys.stdout.write(f"no snapshots yet under {root}\n")
        return 0
    for entry in sorted(root.iterdir()):
        manifest = entry / "manifest.json"
        if not manifest.is_file():
            continue
        data = json.loads(manifest.read_text(encoding="utf-8"))
        sys.stdout.write(f"{data['name']:<24} {len(data['files']):>3} files  "
                         f"{data.get('note', '')}\n")
    return 0


def diff(name: str, project: Path, root: Path) -> int:
    """What a phase actually changed.

    The point of a phase benchmark is to see one phase's output, and a job
    directory holds every phase's. Comparing against the snapshot it started
    from is the only way to say which files this run is responsible for.
    """
    manifest = root / name / "manifest.json"
    if not manifest.is_file():
        sys.stderr.write(f"bench: no snapshot named {name!r} under {root}\n")
        return 2
    before = json.loads(manifest.read_text(encoding="utf-8"))["files"]
    after = _fingerprint(project)
    for key in sorted(set(before) | set(after)):
        if key not in before:
            sys.stdout.write(f"  added    {key}\n")
        elif key not in after:
            sys.stdout.write(f"  removed  {key}\n")
        elif before[key] != after[key]:
            sys.stdout.write(f"  changed  {key}\n")
    unchanged = sum(1 for k in before if after.get(k) == before[k])
    sys.stdout.write(f"  ({unchanged} unchanged)\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    sub = parser.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("save", help="copy a project directory into a named snapshot")
    s.add_argument("--project", type=Path, required=True)
    s.add_argument("--as", dest="name", required=True)
    s.add_argument("--note", help="what phase this is the state after")

    r = sub.add_parser("restore", help="lay a snapshot into a fresh directory")
    r.add_argument("--snapshot", required=True)
    r.add_argument("--to", dest="destination", type=Path, required=True)

    sub.add_parser("list", help="what snapshots exist")
    sub.add_parser("preamble", help="the isolation text every benchmark prompt needs")

    d = sub.add_parser("diff", help="what a project changed since a snapshot")
    d.add_argument("--snapshot", required=True)
    d.add_argument("--project", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.cmd == "save":
        return save(args.project, args.name, args.root, args.note)
    if args.cmd == "restore":
        return restore(args.snapshot, args.destination, args.root)
    if args.cmd == "list":
        return listing(args.root)
    if args.cmd == "preamble":
        sys.stdout.write(PREAMBLE)
        return 0
    return diff(args.snapshot, args.project, args.root)


if __name__ == "__main__":
    raise SystemExit(main())
