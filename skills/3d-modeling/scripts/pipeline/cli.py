#!/usr/bin/env python3
"""`design-tool` — one fused production command.

    uv run design-tool run-job job_dir/

Lower-level verbs exist for debugging and are not the production path. A job is
one invocation because every extra one pays interpreter startup to do work
measured in milliseconds.

**Reviews are answered by re-running, not by this program.** A `CONSEQUENTIAL`
job needs a bounded safety call, a `FITTED` job needs a spec call, and `VERIFIED`
needs independent verification. Those are model calls, and this is a
deterministic program: it cannot make them and must not pretend to. So when the
runner needs one, the CLI writes the evidence packet to `reviews/<kind>_packet.json`
and exits 3 naming the file to answer. Write the response next to it as
`reviews/<kind>_response.json` and run the same command again; the response is
validated against the same schema an in-process caller would be held to.

Until this existed the CLI wired none of the hooks, so `run-job` could complete
exactly one kind of job -- INCONSEQUENTIAL, DIRECT, unverified -- while the
front page advertised the pipeline.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import runner, schemas as S

JOB_FILE = "job.json"


REVIEW_DIR = "reviews"
NEEDS_REVIEW = 3


class _ReviewNeeded(Exception):
    """A review has no answer on disk yet. Carries what to write and where."""

    def __init__(self, kind: str, packet: Any, path: Path) -> None:
        super().__init__(kind)
        self.kind, self.packet, self.path = kind, packet, path


def _payload_of(packet: Any) -> Any:
    """Packets are dataclasses; a spec call is handed a plain dict."""
    return getattr(packet, "payload", packet)


def _reviewer_of(spec: dict[str, Any]) -> dict[str, Any]:
    """Who answered, by their own account.

    Not defaulted to something flattering: `fresh_context` is a claim only the
    caller can make, and this program has no way to check it. Absent means
    absent, and the receipt records that rather than `true`.
    """
    return dict(spec.get("reviewer") or {})


def _answer(job_dir: Path, kind: str):
    """A call that reads its answer from disk, or asks for one and stops."""
    def call(packet: Any) -> dict[str, Any]:
        room = job_dir / REVIEW_DIR
        response = room / f"{kind}_response.json"
        if response.is_file():
            return json.loads(response.read_text(encoding="utf-8"))
        room.mkdir(parents=True, exist_ok=True)
        request = room / f"{kind}_packet.json"
        request.write_text(S.canonical_json(_payload_of(packet)), encoding="utf-8")
        raise _ReviewNeeded(kind, packet, response)
    return call


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
        safety_call=_answer(job_dir, "safety"),
        spec_call=_answer(job_dir, "spec"),
        verify_call=_answer(job_dir, "verification"),
        reviewer=_reviewer_of(spec),
        evidence=tuple(spec.get("evidence", ())),
        interface_map=dict(spec.get("interface_map") or {}),
        cache_dir=(job_dir / spec["cache_dir"]) if spec.get("cache_dir") else None,
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
    try:
        result = runner.run(_request(job_dir, spec, render=not args.no_render))
    except _ReviewNeeded as need:
        rel = need.path.relative_to(job_dir)
        packet = rel.with_name(need.kind + "_packet.json")
        sys.stderr.write(
            f"\ndesign-tool: this job needs a {need.kind} review before it can finish.\n"
            f"  the evidence is written to  {packet}\n"
            f"  write the answer to         {rel}\n"
            "  then run the same command again.\n\n"
            "  This program cannot answer it. A review is a judgement about a part,\n"
            "  and a deterministic tool that returned one would be inventing it.\n")
        return NEEDS_REVIEW

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
