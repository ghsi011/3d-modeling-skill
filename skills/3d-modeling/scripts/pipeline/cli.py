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
import math
import sys
from pathlib import Path
from typing import Any

from . import review as R
from . import runner, schemas as S

JOB_FILE = "job.json"


REVIEW_DIR = "reviews"
NEEDS_REVIEW = 3


ReviewNeeded = runner.ReviewNeeded


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
        room.mkdir(parents=True, exist_ok=True)
        # Always write the current request packet first. If a stale response from
        # a previous run is already on disk, the runner will reject it, but the
        # user must be able to answer the current envelope.
        request = room / f"{kind}_packet.json"
        request.write_text(S.canonical_json(_payload_of(packet)), encoding="utf-8")
        response = room / f"{kind}_response.json"
        if response.is_file():
            try:
                return json.loads(response.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                # An unreadable answer is a malformed review, not a crash: the
                # runner boundary turns this into a blocked job with a receipt.
                raise R.ReviewError(
                    f"{response.name} is not valid JSON: {exc}") from exc
        raise ReviewNeeded(kind, packet, response)
    return call


def _load_job(job_dir: Path) -> dict[str, Any]:
    path = job_dir / JOB_FILE
    if not path.is_file():
        raise SystemExit(f"design-tool: no {JOB_FILE} in {job_dir}")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise SystemExit(
            f"design-tool: {JOB_FILE} in {job_dir} is not valid UTF-8: {exc}") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        # A malformed job.json is the contract's own parse failure, not a bug in
        # the tool. Surface the decoder's line and column instead of letting a
        # JSONDecodeError traceback out of the CLI -- a traceback reads as a crash
        # and hides the one thing the author needs: where the JSON is broken.
        raise SystemExit(
            f"design-tool: {JOB_FILE} in {job_dir} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(
            f"design-tool: {JOB_FILE} in {job_dir} must contain a JSON object, "
            f"not {type(payload).__name__}")
    return payload


def _required(spec: dict[str, Any], key: str) -> Any:
    if key not in spec:
        raise SystemExit(
            f"design-tool: {JOB_FILE} is missing {key!r}; the pipeline does not invent it")
    return spec[key]


def _string(value: Any, path: str, *, non_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise S.SchemaError(f"{path} must be a string")
    if non_empty and not value.strip():
        raise S.SchemaError(f"{path} must be a non-empty string")
    return value


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise S.SchemaError(f"{path} must be an object")
    return value


def _number(value: Any, path: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise S.SchemaError(f"{path} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        suffix = " positive" if positive else " finite"
        raise S.SchemaError(f"{path} must be a{suffix} number")
    return result


def _strings(value: Any, path: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise S.SchemaError(f"{path} must be a list of strings")
    return tuple(value)


def _validate_orientation(value: Any) -> dict[str, Any]:
    orientation = _object(value, "orientation")
    if "model_to_printer_matrix" not in orientation:
        raise S.SchemaError("orientation.model_to_printer_matrix is required")
    matrix = orientation["model_to_printer_matrix"]
    if matrix != "identity":
        if (not isinstance(matrix, list) or len(matrix) != 4
                or any(not isinstance(row, list) or len(row) != 4 for row in matrix)):
            raise S.SchemaError(
                "orientation.model_to_printer_matrix must be 'identity' or a 4x4 numeric matrix")
        for row_index, row in enumerate(matrix):
            for column_index, item in enumerate(row):
                _number(item, f"orientation.model_to_printer_matrix[{row_index}][{column_index}]")
    if "bed_z_mm" not in orientation:
        raise S.SchemaError("orientation.bed_z_mm is required")
    _number(orientation["bed_z_mm"], "orientation.bed_z_mm")
    return orientation


def _validate_job_contract(spec: dict[str, Any]) -> None:
    """Validate JSON shapes before any runner code can turn them into a traceback."""
    _string(_required(spec, "job_id"), "job_id", non_empty=True)
    parameters = _object(_required(spec, "parameters"), "parameters")
    for key, value in parameters.items():
        if not isinstance(key, str):
            raise S.SchemaError("parameters keys must be strings")
        _number(value, f"parameters.{key}")
    _string(_required(spec, "updated_utc"), "updated_utc", non_empty=True)
    S.require_enum(_required(spec, "consequence"), S.CONSEQUENCE, what="job.consequence")
    S.require_enum(spec.get("candidate_strategy", "SINGLE"), S.CANDIDATE_STRATEGY,
                   what="job.candidate_strategy")

    _string(_required(spec, "printer"), "printer", non_empty=True)
    material = _object(_required(spec, "material"), "material")
    _string(material.get("process"), "material.process", non_empty=True)
    _string(material.get("material"), "material.material", non_empty=True)
    nozzle = _object(_required(spec, "nozzle"), "nozzle")
    if "diameter_mm" not in nozzle:
        raise S.SchemaError("nozzle.diameter_mm is required")
    _number(nozzle["diameter_mm"], "nozzle.diameter_mm", positive=True)
    _validate_orientation(_required(spec, "orientation"))

    optional_strings = ("brief", "template", "cache_dir")
    for key in optional_strings:
        if key in spec and spec[key] is not None:
            _string(spec[key], key, non_empty=True)
    for key in ("stated", "modifiers", "ambiguities", "evidence"):
        if key in spec:
            _strings(spec[key], key)
    for key in ("external_geometry", "step"):
        if key in spec and not isinstance(spec[key], bool):
            raise S.SchemaError(f"{key} must be a boolean")
    if "reviewer" in spec and spec["reviewer"] is not None:
        _object(spec["reviewer"], "reviewer")
    if "interface_map" in spec and spec["interface_map"] is not None:
        interface_map = _object(spec["interface_map"], "interface_map")
        if any(not isinstance(key, str) or not isinstance(value, str)
               for key, value in interface_map.items()):
            raise S.SchemaError("interface_map must map strings to strings")


def _request(job_dir: Path, spec: dict[str, Any], *, render: bool) -> runner.JobRequest:
    _validate_job_contract(spec)
    return runner.JobRequest(
        job_id=_required(spec, "job_id"),
        brief_path=job_dir / spec.get("brief", "brief.md"),
        template=spec.get("template"),
        parameters=_required(spec, "parameters"),
        stated=frozenset(spec.get("stated", ())),
        consequence=S.require_enum(_required(spec, "consequence"),
                                   S.CONSEQUENCE, what="job.consequence"),
        out_dir=job_dir,
        updated_utc=_required(spec, "updated_utc"),
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
        printer=_required(spec, "printer"),
        material=_required(spec, "material"),
        nozzle=_required(spec, "nozzle"),
        orientation=_required(spec, "orientation"),
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
        request = _request(job_dir, spec, render=not args.no_render)
    except (S.SchemaError, KeyError, TypeError, ValueError) as exc:
        # Contract-shaped inputs (the consequence class, and anything else parsed
        # through the schema helpers) are validated as the job is turned into a
        # request. A bad value is the contract failing to parse: name the field
        # and the value it rejected rather than tracebacking out of the CLI.
        raise SystemExit(
            f"design-tool: {JOB_FILE} in {job_dir} is not a valid contract: {exc}") from exc
    try:
        result = runner.run(request)
    except ReviewNeeded as need:
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

    print(f"uv run --project <skill> --frozen python {sys.version.split()[0]}")
    for name in ("trimesh", "manifold3d", "build123d", "numpy", "pillow"):
        try:
            print(f"  [yes] {name:12s} {md.version(name)}")
        except md.PackageNotFoundError:
            print(f"  [NO ] {name:12s} required on the core path")
    return 0


def selftest(argv: list[str]) -> int:
    from . import selftest as _selftest
    return _selftest.main(argv)


COMMANDS = ("run-job", "doctor", "selftest")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        print("commands: " + ", ".join(COMMANDS))
        return 0
    command, rest = argv[0], argv[1:]
    if command == "run-job":
        return run_job(rest)
    if command == "doctor":
        return doctor(rest)
    if command == "selftest":
        return selftest(rest)
    sys.stderr.write(
        f"design-tool: unknown command {command!r}; have {', '.join(COMMANDS)}\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
