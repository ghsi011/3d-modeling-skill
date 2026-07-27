#!/usr/bin/env python3
"""The raw-parse integrity read, without writing a script for it.

This is the one acceptance check a verifier cannot delegate to the commission
gate: every shared tool downstream loads the *normalized* mesh, so a genuine
export defect only ever shows on the raw side, and once normalization has run
the evidence of it is gone. Which meant the verifier hand-wrote a snippet to
call `mesh_io.load_mesh_report` -- authoring, in the one step whose whole point
is that it must not be re-authored.

It also prints the reading a verifier is most likely to misread. An STL is a
triangle soup: a raw parse of a perfectly good part reports many components and
`watertight=False`, because the format stores no vertex sharing. That is the
format, not a defect. `degenerate_faces` is the number that would catch a real
one.

    uv run --project <skill> --frozen python <skill>/scripts/dt.py integrity out/candidate-01.stl
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from ._bootstrap import as_mesh  # noqa: F401  (puts scripts/ on sys.path)

import mesh_io  # noqa: E402


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return {k: _plain(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except (ValueError, AttributeError):
            return str(value)
    return value


def report(stl_path: Path) -> dict[str, Any]:
    loaded = mesh_io.load_mesh_report(str(stl_path))
    raw = _plain(loaded.raw_integrity)
    return {
        "path": str(stl_path),
        "raw_integrity": raw,
        "mutation_log": _plain(getattr(loaded, "mutation_log", None)),
        "normalized_sha256": loaded.normalized_sha256,
        "reading_note": (
            "An STL stores no vertex sharing, so a raw parse of a sound part reports "
            "many components and watertight=False. That is the format. "
            "degenerate_faces is the metric that catches a real export defect."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stl", type=Path)
    parser.add_argument("--out", type=Path, help="write the JSON here as well as stdout")
    args = parser.parse_args(argv)

    if not args.stl.is_file():
        sys.stderr.write(f"integrity: no such STL: {args.stl}\n")
        return 2
    payload = report(args.stl)
    text = json.dumps(payload, indent=2, default=str)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
