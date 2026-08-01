#!/usr/bin/env python3
"""The isolated build boundary: the parent half.

The acceptance contract is frozen before the candidate exists. That ordering is
worth nothing while the candidate is then *imported into the process that holds
the contract*, because an import runs code: `runner.status is pipeline.status`,
`status.decide` is resolved at call time, `commission._tol` and
`contract.area_tolerance` are module globals, `AcceptanceSource.expectations` is
one assignment away, and the live `Frozen` object sat in the calling frame. All
four were reachable from `model.py`'s first line, and the demonstrated result was
a `VERIFIED` final status on a 352 mm2 miss with the on-disk contract still at
revision 1 and an empty `changed` list.

So the candidate runs somewhere else:

1. the parent validates and freezes the proposal, and keeps the frozen contract
   in memory;
2. this module snapshots every file the pipeline owns in the project directory;
3. a one-shot child process -- `sys.executable -m pipeline.build_child`, never a
   shell string -- executes the candidate;
4. the child is handed a model path, a scratch directory and whether a STEP is
   wanted. Nothing about acceptance crosses;
5. the child writes geometry and a small JSON manifest into that scratch
   directory and exits;
6. the parent re-reads the manifest, hashes the geometry *itself*, and copies
   only the two files it asked for into the project directory. Everything else
   the child wrote is in a temporary directory that is then deleted;
7. the parent verifies the snapshot. A pipeline-owned file that moved while the
   candidate was running is restored and the run is refused;
8. commissioning, screening, review binding and the final status happen in the
   parent, which has imported nothing the candidate wrote.

**What this module deliberately does not import.** `authored`, which calls
`spec.loader.exec_module`, and `build_child`, which calls `authored`. The
executor is reached through `sys.executable` and by no other route, so no
ordering of the parent's code can execute a model file --
`test_isolation.TheParentNeverImportsTheExecutorTest` asserts it over the import
graph rather than over one run.

**`DIRECT` does not come here.** A certified template is geometry the pipeline
wrote; there is no untrusted code to isolate, and the route's dispatch count and
runtime are a release gate. `runner.py` does not import this module at all.
"""
from __future__ import annotations

import dataclasses
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from . import schemas as S

CHILD_MODULE = "pipeline.build_child"
CHILD_SCHEMA = 1

INPUT_FILE = "build_input.json"
MANIFEST_FILE = "build_manifest.json"
STL_NAME = "candidate.stl"
STEP_NAME = "candidate.step"

# Ten minutes. Not a performance target -- the slowest observed authored build is
# under four seconds, of which 3.7 s is a build123d cold import -- but a bound, so
# that a model with a loop in it is a diagnosable failure rather than a hung
# command with no receipt.
BUILD_TIMEOUT_S = 600.0

# Every file in the project directory that the pipeline writes and the candidate
# may not. Snapshotted before the child starts and verified after it exits: a
# receipt is written by the party that measured the part, and the frozen contract
# is what every receipt binds by hash.
#
# `test_isolation` asserts this covers `acceptance.INVALIDATED_BY_A_NEW_REVISION`
# entirely; two lists that can drift apart is one list and one forged receipt.
PARENT_OWNED = (
    "acceptance_contract.json",
    "acceptance_history.json",
    "design_proposal.json",
    "project.json",
    "job.json",
    "execution_plan.json",
    "route_decision.json",
    "intent_manifest.json",
    "model_contract.json",
    "artifact_manifest.json",
    "commission_report.json",
    "manufacturing_report.json",
    "safety_verification_report.json",
    "verification_report.json",
    "specification.json",
    "final_status.json",
    "next_action.json",
    "timings.json",
)

# Directories where *every* file is the pipeline's, including ones that do not
# exist yet. `reviews/` holds the answers a second party gave -- a forged
# `verification_response.json` is a candidate declaring itself independently
# verified -- and `witness/` holds the evidence those answers are hashed against.
# Neither has a fixed file list, so they are guarded whole.
PARENT_OWNED_DIRS = ("reviews", "witness")


class BuildRefused(S.SchemaError):
    """The candidate could not be built, or was not allowed to have been."""


@dataclasses.dataclass(frozen=True)
class BuiltCandidate:
    """What came back across the boundary, after the parent re-checked it.

    Identity and geometry, and nothing the gate reads. `params` is the
    candidate's own declaration and is compared against the frozen proposal by
    the caller; `provenance` is the only candidate-supplied value that reaches
    the contract, and it reaches it as recorded provenance rather than as an
    expectation.

    `module_sha256` and the artifact digests are computed by the parent from the
    files on disk. The child reports neither -- a party that could hash its own
    output could report a digest of something else.
    """

    name: str
    module_path: Path
    module_sha256: str
    params: dict[str, Any]
    provenance: dict[str, Any]
    stl_path: Path
    step_path: Path | None
    kernel: str
    backend_version: str
    tessellation: dict[str, Any]
    boolean_engine: str
    # What the child measured of itself: importing the model and building it,
    # which in a fresh process are one cost.
    build_seconds: float
    # What the parent measured of the child: the above plus interpreter start,
    # this package's imports and the copy out. `timings.json` records both,
    # because a receipt whose total excludes the dominant term is a receipt that
    # says a 1.7 s job took 0.05 s.
    boundary_seconds: float


def child_input(*, model_path: Path, build_dir: Path, step: bool) -> dict[str, Any]:
    """Everything the child is given, which is everything it needs to build.

    A model path, somewhere to write, and the names to write under. No frozen
    contract, no proposal, no expectations, no tolerances, no parameters: the
    model declares its own `PARAMS` and is measured against a document it is
    never shown.
    """
    return {
        "schema_version": CHILD_SCHEMA,
        "model_path": str(model_path),
        "build_dir": str(build_dir),
        "stl_name": STL_NAME,
        "step_name": STEP_NAME if step else None,
        "manifest_name": MANIFEST_FILE,
    }


def child_command(input_path: Path) -> list[str]:
    """The child, as an argument vector.

    A list and a module entry point, never a shell string: this has to work on
    Windows without `fork`, and a project path with a space in it must survive
    being one argument.
    """
    return [sys.executable, "-m", CHILD_MODULE, str(input_path)]


def _child_env() -> dict[str, str]:
    """The child's environment: this package importable, and no bytecode written.

    `PYTHONPATH` rather than a `cwd` trick, because an environment variable
    carries a path with spaces in it without anything having to quote it. The
    child's working directory is its scratch build directory, so a model that
    writes to a relative path writes there.
    """
    scripts_root = str(Path(__file__).resolve().parents[1])
    existing = os.environ.get("PYTHONPATH", "")
    env = dict(os.environ)
    env["PYTHONPATH"] = (scripts_root + os.pathsep + existing) if existing else scripts_root
    # The candidate's module would otherwise leave a `__pycache__` beside itself
    # in the project directory -- an artifact of the build, in the directory whose
    # every other file is evidence.
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _guarded(dest_dir: Path, model_path: Path) -> list[Path]:
    """Every path in the project directory the candidate may not touch."""
    paths = [dest_dir / name for name in PARENT_OWNED]
    paths.append(model_path)
    for name in PARENT_OWNED_DIRS:
        directory = dest_dir / name
        if directory.is_dir():
            paths.extend(path for path in directory.rglob("*") if path.is_file())
    return paths


def _snapshot(paths: list[Path]) -> dict[Path, bytes | None]:
    return {path: (path.read_bytes() if path.is_file() else None) for path in paths}


def _restore(snapshot: dict[Path, bytes | None], dest_dir: Path) -> list[str]:
    """Put back everything that moved, and say what did.

    Restoring rather than only reporting: the parent holds the bytes, the files
    are small, and a run that is refused should leave the directory in the state
    the refusal describes. A deleted acceptance contract that stays deleted turns
    one refused run into a superseded revision on the next one.

    The guarded directories are re-walked rather than only re-read, because the
    interesting file in `reviews/` is the one that was not there before.
    """
    seen = dict(snapshot)
    for name in PARENT_OWNED_DIRS:
        directory = dest_dir / name
        if directory.is_dir():
            seen.update({path: None for path in directory.rglob("*")
                         if path.is_file() and path not in seen})

    moved: list[str] = []
    for path, before in seen.items():
        after = path.read_bytes() if path.is_file() else None
        if after == before:
            continue
        moved.append(path.name)
        if before is None:
            path.unlink()
        else:
            path.write_bytes(before)
    return sorted(moved)


def _tail(text: str, limit: int = 800) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else "..." + text[-limit:]


def _json_object(path: Path, what: str) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildRefused(f"{what} is not readable JSON: {exc}") from exc
    if not isinstance(loaded, dict):
        raise BuildRefused(f"{what} is not an object")
    return loaded


def _accept_artifact(build_dir: Path, name: Any, dest_dir: Path, *, what: str) -> Path:
    """One file the child was asked for, moved into the project directory.

    Checked by name rather than by pattern: the child names its outputs in the
    manifest, and a manifest naming `../../somewhere/else.stl` is the obvious way
    to make the parent copy a file it did not ask for.
    """
    wanted = STL_NAME if what == "stl" else STEP_NAME
    if name != wanted:
        raise BuildRefused(
            f"the build manifest names {name!r} as its {what}, and the boundary "
            f"asked for {wanted!r}")
    produced = build_dir / str(name)
    if not produced.is_file():
        raise BuildRefused(
            f"the build manifest names {name!r} as its {what} and no such file "
            "was written to the build directory")
    destination = dest_dir / str(name)
    try:
        shutil.copyfile(produced, destination)
    except OSError as exc:
        raise BuildRefused(
            f"{name} could not be copied out of the build directory: {exc}") from exc
    return destination


def build(model_path: Path, *, dest_dir: Path, step: bool,
          timeout: float = BUILD_TIMEOUT_S) -> BuiltCandidate:
    """Execute the candidate in a one-shot child process and adopt what it made.

    Raises `BuildRefused` for every way this can go wrong -- a model that will not
    import, a builder that raises, a child that dies, a build that runs past its
    bound, a manifest that does not describe what was asked for, and a candidate
    that wrote to a file the pipeline owns. All of them are findings, and a
    finding is a message the caller writes down.
    """
    model_path = Path(model_path).resolve()
    dest_dir = Path(dest_dir).resolve()
    if not model_path.is_file():
        raise BuildRefused(f"no such model module: {model_path}")

    started = time.perf_counter()
    snapshot = _snapshot(_guarded(dest_dir, model_path))

    build_dir = Path(tempfile.mkdtemp(prefix="design-tool-build-"))
    try:
        input_path = build_dir / INPUT_FILE
        input_path.write_text(
            S.canonical_json(child_input(model_path=model_path,
                                         build_dir=build_dir, step=step)),
            encoding="utf-8")

        timed_out = False
        try:
            # The two streams are merged so a designer's `print()` and the
            # traceback that followed it are one transcript in the right order.
            # Captured rather than inherited: this program's own stdout is the
            # run's report, and the candidate does not get to write on it.
            completed = subprocess.run(          # an argv, never a shell string
                child_command(input_path), cwd=str(build_dir), env=_child_env(),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, timeout=timeout, check=False)
            returncode, output = completed.returncode, completed.stdout
        except subprocess.TimeoutExpired as expired:
            timed_out, returncode = True, None
            partial = expired.output
            output = (partial.decode("utf-8", "replace")
                      if isinstance(partial, bytes) else (partial or ""))

        # First, and before anything the child produced is looked at: what the
        # candidate did to the directory it was running next to.
        moved = _restore(snapshot, dest_dir)
        if moved:
            raise BuildRefused(
                f"{model_path.name} wrote to {len(moved)} file(s) the pipeline owns "
                f"while it was building: {', '.join(moved)}. They have been restored "
                "and the run is refused. A receipt is written by the party that "
                "measured the part, never by the part; and the acceptance contract "
                "on disk is the document every receipt binds by hash.")

        if timed_out:
            raise BuildRefused(
                f"{model_path.name} did not finish building within {timeout:.0f}s "
                "and the build process was killed."
                + (f" Its last output was:\n{_tail(output)}" if output.strip() else ""))

        manifest_path = build_dir / MANIFEST_FILE
        if not manifest_path.is_file():
            raise BuildRefused(
                f"the build process exited with code {returncode} and wrote no "
                f"{MANIFEST_FILE}, so nothing is known about what it did."
                + (f" Its output was:\n{_tail(output)}" if output.strip() else ""))

        manifest = _json_object(manifest_path, MANIFEST_FILE)
        if manifest.get("schema_version") != CHILD_SCHEMA:
            raise BuildRefused(
                f"{MANIFEST_FILE} declares schema_version "
                f"{manifest.get('schema_version')!r}; this boundary speaks "
                f"{CHILD_SCHEMA}")
        if not manifest.get("ok"):
            error = manifest.get("error") or {}
            raise BuildRefused(str(error.get("message")
                                   or f"the build failed and said nothing (exit "
                                      f"{returncode})"))

        model = manifest.get("model")
        artifacts = manifest.get("artifacts")
        built = manifest.get("build")
        if not all(isinstance(section, dict) for section in (model, artifacts, built)):
            raise BuildRefused(f"{MANIFEST_FILE} is missing model, artifacts or build")

        stl_path = _accept_artifact(build_dir, artifacts.get("stl"), dest_dir, what="stl")
        step_path = None
        if step:
            step_path = _accept_artifact(build_dir, artifacts.get("step"), dest_dir,
                                         what="step")

        params = model.get("params")
        provenance = model.get("provenance") or {}
        if not isinstance(params, dict) or not isinstance(provenance, dict):
            raise BuildRefused(f"{MANIFEST_FILE} does not describe the model's "
                               "declared parameters")

        return BuiltCandidate(
            name=str(model.get("name") or model_path.stem),
            module_path=model_path,
            # Hashed here, from the file the parent can see, after the child has
            # exited and after the snapshot proved the file did not move.
            module_sha256=S.sha256_file(model_path),
            params=dict(params),
            provenance=dict(provenance),
            stl_path=stl_path,
            step_path=step_path,
            kernel=str(built.get("kernel") or "unrecorded"),
            backend_version=str(built.get("backend_version") or "unrecorded"),
            tessellation=dict(built.get("tessellation") or {}),
            boolean_engine=str(built.get("boolean_engine") or "unrecorded"),
            build_seconds=float(built.get("build_seconds") or 0.0),
            boundary_seconds=time.perf_counter() - started,
        )
    finally:
        # Everything the child wrote that the parent did not ask for by name goes
        # with the directory. There is no path by which an unexpected file
        # becomes an input to anything.
        shutil.rmtree(build_dir, ignore_errors=True)
