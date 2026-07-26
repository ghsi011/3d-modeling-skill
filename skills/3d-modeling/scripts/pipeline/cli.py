#!/usr/bin/env python3
"""`design-tool` — one fused production command.

    uv run design-tool run-job job_dir/

Lower-level verbs exist for debugging and are not the production path. A job is
one invocation because every extra one pays interpreter startup to do work
measured in milliseconds.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import runner, schemas as S

JOB_FILE = "job.json"


def _load_job(job_dir: Path) -> dict[str, Any]:
    path = job_dir / JOB_FILE
    if not path.is_file():
        raise SystemExit(f"design-tool: no {JOB_FILE} in {job_dir}")
    return json.loads(path.read_text(encoding="utf-8"))


def _request(job_dir: Path, spec: dict[str, Any], *, render: bool) -> runner.JobRequest:
    return runner.JobRequest(
        job_id=spec["job_id"],
        brief_path=job_dir / spec.get("brief", "brief.md"),
        template=spec.get("template"),
        parameters=spec["parameters"],
        stated=frozenset(spec.get("stated", ())),
        consequence=S.require_enum(spec.get("consequence", "INCONSEQUENTIAL"),
                                   S.CONSEQUENCE, what="job.consequence"),
        out_dir=job_dir,
        updated_utc=spec["updated_utc"],
        modifiers=tuple(spec.get("modifiers", ())),
        candidate_strategy=spec.get("candidate_strategy", "SINGLE"),
        external_geometry=bool(spec.get("external_geometry", False)),
        ambiguities=tuple(spec.get("ambiguities", ())),
        step=bool(spec.get("step", False)),
        render=render,
    )


def run_job(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="design-tool run-job")
    parser.add_argument("job_dir", type=Path)
    parser.add_argument("--no-render", action="store_true",
                        help="skip the witness images -- and with them the only evidence "
                             "that is not conditioned on a declaration")
    args = parser.parse_args(argv)

    job_dir = args.job_dir.resolve()
    spec = _load_job(job_dir)
    result = runner.run(_request(job_dir, spec, render=not args.no_render))

    for name, path in sorted(result.artifacts.items()):
        sys.stderr.write(f"  {name:28s} {path.name}\n")
    timings = "  ".join(f"{k} {v:.2f}s" for k, v in result.timings.items())
    sys.stderr.write(f"\n  {timings}\n  llm calls: {result.llm_calls}\n")

    if not result.ok:
        sys.stderr.write(f"\ndesign-tool: {result.stage}: {result.message}\n")
        return 1
    sys.stderr.write(f"\n  {result.final_status['final_status']}: {result.message}\n")
    return 0


def doctor(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="design-tool doctor")
    parser.parse_args(argv)
    import importlib.metadata as md

    print(f"python {sys.version.split()[0]}")
    for name in ("trimesh", "manifold3d", "build123d", "numpy", "pillow"):
        try:
            print(f"  [yes] {name:12s} {md.version(name)}")
        except md.PackageNotFoundError:
            print(f"  [NO ] {name:12s} required on the core path")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        print("commands: run-job, doctor")
        return 0
    command, rest = argv[0], argv[1:]
    if command == "run-job":
        return run_job(rest)
    if command == "doctor":
        return doctor(rest)
    sys.stderr.write(f"design-tool: unknown command {command!r}; have run-job, doctor\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
