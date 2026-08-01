#!/usr/bin/env python3
"""The confined build boundary: the parent half.

The acceptance contract is frozen before the candidate exists. That ordering was
worth nothing while the candidate was *imported into the process that holds the
contract*, and it was still not enough once the candidate merely ran as a peer
process. `0a8e464` gave the candidate a different interpreter; it did not give it
a smaller authority. Same user, same filesystem, no lifetime bound -- and three
attacks walked through, none of which needed an import to do it:

* the candidate rewrote `pipeline/backends/authored.py`, which the parent
  first imports *after* `build` returns, and the parent executed its
  module-level code seconds later in the interpreter holding the frozen
  contract. `VERIFIED`, `expected 432.0 measured 80.002`, contract at revision 1;
* the same, through a `__pycache__` entry stamped to the real file's mtime and
  size, leaving the `.py` byte-identical, so hashing the source saw nothing;
* a `DETACHED_PROCESS` grandchild that outlived `subprocess.run`'s timeout and
  rewrote `final_status.json` 25 s after the run had reported `FAILED`.

So the candidate does not run as a peer. `confine.py` builds a restricted,
low-integrity, privilege-stripped token and a job object it cannot leave, and
this module builds the workspace that token can reach:

1. the parent validates and freezes the proposal and keeps it in memory;
2. **every input is hashed here, before anything is launched** -- the model and
   each sibling module the candidate is allowed to import;
3. those inputs are *copied* into a sandbox `in\\` directory which is then sealed
   read-only. The candidate never holds a handle to the authoritative original;
4. a sandbox `out\\` directory is labelled Low. It is the only object on the
   machine the child can write;
5. the child runs `-m pipeline.build_child` under that token, inside that job,
   with a constructed environment and exactly two inherited handles: a `NUL` and
   one pipe for its transcript;
6. the parent waits for the *job* to report zero live processes -- not for the
   direct child to exit -- and only then looks at `out\\`;
7. every output is validated by name, rejected if it is a reparse point, if it
   carries an alternate data stream, or if its real path leaves the sandbox;
   then hashed by the parent and copied into the project directory;
8. commissioning, screening, review binding and the final status happen in the
   parent, which has imported nothing the candidate wrote.

**Hashing is not the gate.** The parent hashes the inputs before launch and the
outputs after, and both digests go on the receipt, but neither is what stops the
candidate: the `.pyc` attack proved that detection-after-the-fact is a different
thing from not having been given the authority. What stops the candidate is that
the token cannot write the repository, the virtual environment, the project
directory or its own inputs, and the job object means nothing it spawned is still
alive when the parent starts reading. The one integrity check kept here is a
narrow canary over the frozen contract, and it is a finding, not the gate.

**What this module deliberately does not import.** `authored`, which calls
`spec.loader.exec_module`, and `build_child`, which calls `authored`. The
executor is reached through `sys.executable` and by no other route --
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
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from . import confine
from . import schemas as S

CHILD_MODULE = "pipeline.build_child"
CHILD_SCHEMA = 2

INPUT_FILE = "build_input.json"
MANIFEST_FILE = "build_manifest.json"
STL_NAME = "candidate.stl"
STEP_NAME = "candidate.step"

INPUT_DIR = "in"
OUTPUT_DIR = "out"

# Ten minutes. Not a performance target -- the slowest observed authored build is
# under four seconds, of which 3.7 s is a build123d cold import -- but a bound, so
# that a model with a loop in it is a diagnosable failure rather than a hung
# command with no receipt. It bounds the whole job object, not one process.
BUILD_TIMEOUT_S = 600.0

# The frozen contract, by name. Not a list of everything the pipeline owns: the
# candidate has no write access to any of it, and a second list that has to be
# kept in step with `acceptance.INVALIDATED_BY_A_NEW_REVISION` is a maintenance
# obligation whose failure mode is a silent gap. This one file is re-read after
# the job is dead as a canary on the confinement itself -- if it ever moves, the
# boundary did not hold and the run is refused whatever else is true.
CANARY_FILE = "acceptance_contract.json"


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

    `module_sha256` and the artifact digests are computed by the parent. The
    module digest is taken from the authoritative file **before the child is
    launched** -- not after, and never from the manifest. A party that could hash
    its own source could report the digest of something else, and a digest taken
    afterwards is a digest of whatever survived the build.
    """

    name: str
    module_path: Path
    module_sha256: str
    # Every file staged into the sandbox, digested before the copy, by name.
    # The receipt says what the candidate was allowed to import as well as what
    # it declared.
    input_sha256: dict[str, str]
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


def child_input(*, model_name: str, build_dir: Path, input_dir: Path,
                step: bool) -> dict[str, Any]:
    """Everything the child is given, which is everything it needs to build.

    A directory of copied sources, a model *name* within it, somewhere to write,
    and the names to write under. No frozen contract, no proposal, no
    expectations, no tolerances, no parameters: the model declares its own
    `PARAMS` and is measured against a document it is never shown.

    A name rather than a path, and the two directories are the sandbox's. The
    child is never told where the project is, so the candidate is not handed the
    location of the receipts it is not allowed to reach.
    """
    return {
        "schema_version": CHILD_SCHEMA,
        "input_dir": str(input_dir),
        "model_name": model_name,
        "build_dir": str(build_dir),
        "stl_name": STL_NAME,
        "step_name": STEP_NAME if step else None,
        "manifest_name": MANIFEST_FILE,
    }


def child_command(input_path: Path) -> list[str]:
    """The child, as an argument vector.

    A list and a module entry point. `confine.run` passes `argv[0]` to
    `CreateProcessAsUserW` as `lpApplicationName` and the joined form as the
    command line, so the executable is never found by parsing a string and no
    shell is involved at any point.
    """
    return [sys.executable, "-m", CHILD_MODULE, str(input_path)]


HOME_DIR = "home"


def child_environment(build_dir: Path) -> dict[str, str]:
    """The child's environment, constructed rather than inherited.

    The parent's environment names the project directory, the job, the user and
    every path this machine happens to have. None of that is a build input, and
    the candidate that rewrote this package's source found out where to write by
    reading `PYTHONPATH` out of an inherited environment.

    Everything a library reaches for when it wants somewhere to put things --
    `TEMP`, `TMP`, `USERPROFILE`, `APPDATA`, `LOCALAPPDATA`, `HOMEDRIVE` and
    `HOMEPATH` -- points inside the one writable directory. That is not tidiness:
    OCCT's Python bindings call `Path.home()` during import and raise
    `Could not determine home directory` without one, and the alternative to
    giving them a home inside the sandbox is giving them the real one.

    `PYTHONPATH` still has to name this package, because the child is
    `-m pipeline.build_child`. It is a read-only path now: the restricted token
    cannot write anything under it.
    """
    scripts_root = str(Path(__file__).resolve().parents[1])
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    home = build_dir / HOME_DIR
    return {
        "SystemRoot": system_root,
        "SystemDrive": os.environ.get("SystemDrive", "C:"),
        "windir": system_root,
        "PATH": os.pathsep.join((f"{system_root}\\system32", system_root)),
        "PATHEXT": os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD"),
        "NUMBER_OF_PROCESSORS": os.environ.get("NUMBER_OF_PROCESSORS", "1"),
        "PROCESSOR_ARCHITECTURE": os.environ.get("PROCESSOR_ARCHITECTURE", "AMD64"),
        "TEMP": str(home),
        "TMP": str(home),
        "USERPROFILE": str(home),
        "APPDATA": str(home),
        "LOCALAPPDATA": str(home),
        "HOMEDRIVE": home.drive,
        "HOMEPATH": str(home)[len(home.drive):],
        "PYTHONPATH": scripts_root,
        # The candidate's module would otherwise leave a `__pycache__` beside
        # itself. It could not write one into the sealed input directory anyway;
        # this makes the failure not happen rather than not matter.
        "PYTHONDONTWRITEBYTECODE": "1",
        # No `site-packages` out of a user profile this process is not looking at.
        "PYTHONNOUSERSITE": "1",
    }


def _tail(text: str, limit: int = 800) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else "..." + text[-limit:]


def _json_object(path: Path, what: str) -> dict[str, Any]:
    """A JSON object the child wrote, or a finding naming the file.

    Every failure mode of "read what the untrusted party said" lands here: a
    file that is not there, is not readable, is not UTF-8, is not JSON, or is
    JSON that is not an object. Each is a refusal with a message, because the
    caller writes findings down and `None` is not one.
    """
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildRefused(f"{what} is not readable JSON: {exc}") from exc
    if not isinstance(loaded, dict):
        raise BuildRefused(f"{what} is not an object")
    return loaded


def _sections(manifest: dict[str, Any], returncode: int | None,
              output: str = "") -> tuple[dict, dict, dict]:
    """The three parts of a build manifest, or a finding naming what is wrong.

    A function rather than a run of `if`s inside `build`, so that "a manifest
    from a boundary that speaks a different protocol is refused" is a thing a
    test can state in three lines instead of by arranging for a whole child
    process to lie about its schema.

    `output` is the child's transcript and it is appended to every refusal here.
    A model that printed a measurement and then raised has said two useful
    things, and the manifest carries only the second.
    """
    def refuse(message: str) -> BuildRefused:
        return BuildRefused(message + (f"\n{_tail(output)}" if output.strip() else ""))

    if manifest.get("schema_version") != CHILD_SCHEMA:
        raise refuse(f"{MANIFEST_FILE} declares schema_version "
                     f"{manifest.get('schema_version')!r}; this boundary speaks "
                     f"{CHILD_SCHEMA}")
    if not manifest.get("ok"):
        error = manifest.get("error") or {}
        raise refuse(str(error.get("message")
                         or f"the build failed and said nothing (exit "
                            f"{returncode})"))

    model = manifest.get("model")
    artifacts = manifest.get("artifacts")
    built = manifest.get("build")
    if not all(isinstance(section, dict) for section in (model, artifacts, built)):
        raise refuse(f"{MANIFEST_FILE} is missing model, artifacts or build")
    return model, artifacts, built


def _accept_artifact(build_dir: Path, name: Any, dest_dir: Path, *, what: str) -> Path:
    """One file the child was asked for, moved into the project directory.

    Every check here is on the *name the child chose*, and every one of them was
    a way to make the parent adopt a file it did not ask for:

    * checked by exact byte compare against the constant, not by basename, not
      by suffix and not by `Path.name` -- `..\\..\\somewhere\\else.stl`,
      `CANDIDATE.STL`, `candidate.stl.`, `candidate.stl `, `.\\candidate.stl`,
      `CANDID~1.STL` and `candidate.stl:payload` are seven different ways to
      write something that is not `candidate.stl` and that Windows will open
      anyway;
    * rejected if the entry is a reparse point. A directory junction needs no
      privilege to create, and the parent copies with the parent's rights;
    * rejected if its real path is not inside the build directory;
    * rejected if it carries a second data stream, which a digest cannot see.
    """
    wanted = STL_NAME if what == "stl" else STEP_NAME
    if name != wanted:
        raise BuildRefused(
            f"the build manifest names {name!r} as its {what}, and the boundary "
            f"asked for {wanted!r}")

    produced = build_dir / str(name)
    if confine.is_reparse_point(produced):
        raise BuildRefused(
            f"{name} is a reparse point (a symlink, junction or mount point) and "
            "not a file. The boundary copies with the parent's rights and would "
            "have followed it out of the sandbox.")
    if not produced.is_file():
        raise BuildRefused(
            f"the build manifest names {name!r} as its {what} and no such file "
            "was written to the build directory")

    real = Path(os.path.realpath(produced))
    root = Path(os.path.realpath(build_dir))
    if not real.is_relative_to(root):
        raise BuildRefused(
            f"{name} resolves to {real}, which is outside the build directory")

    extra = [stream for stream in confine.data_streams(produced)
             if stream != "::$DATA"]
    if extra:
        raise BuildRefused(
            f"{name} carries the alternate data stream(s) {', '.join(extra)}. "
            "A stream is not visible to a digest of the file and travels with it "
            "when it is copied.")

    destination = dest_dir / str(name)
    try:
        # `copyfile` and not `copy2`: metadata is not wanted, and on Windows a
        # stream-preserving copy would carry across exactly what was just
        # refused.
        shutil.copyfile(produced, destination)
    except OSError as exc:
        raise BuildRefused(
            f"{name} could not be copied out of the build directory: {exc}") from exc
    return destination


def _stage(model_path: Path, input_dir: Path) -> dict[str, str]:
    """Copy the candidate's sources into the sandbox and digest each one.

    The model, and every other top-level `*.py` beside it -- a designer may ship
    a helper module next to `model.py`, and the pipeline writes no Python into a
    project directory, so every `.py` there is the designer's. Nothing else goes:
    the project directory's other files are receipts.

    Digested from the authoritative original *before* the copy, and the copy is
    digested again and compared. That is not a security check -- both files are
    the parent's -- it is the difference between "the receipt names the source
    that was built" and "the receipt names a source".
    """
    digests: dict[str, str] = {}
    sources = sorted({model_path} | {path for path in model_path.parent.glob("*.py")
                                     if path.is_file()})
    for source in sources:
        if confine.is_reparse_point(source):
            raise BuildRefused(
                f"{source.name} in the project directory is a reparse point, not a "
                "file; the boundary will not stage what it cannot read straight.")
        digest = S.sha256_file(source)
        staged = input_dir / source.name
        shutil.copyfile(source, staged)
        if S.sha256_file(staged) != digest:       # pragma: no cover - raced copy
            raise BuildRefused(
                f"{source.name} changed while it was being staged into the build "
                "sandbox; the run is refused rather than built from a file the "
                "receipt would misname.")
        digests[source.name] = digest
    return digests


def _sweep(build_dir: Path) -> None:
    """Refuse a build directory containing anything the parent cannot walk.

    Called before any output is read. `shutil.rmtree` follows nothing, but the
    parent's own validation walks, and a junction planted in the output
    directory is a directory whose contents are somewhere else entirely.
    """
    for root, directories, files in os.walk(build_dir):
        for name in list(directories) + list(files):
            if confine.is_reparse_point(Path(root) / name):
                raise BuildRefused(
                    f"the build directory contains a reparse point ({name}); "
                    "nothing is read out of a directory that is partly somewhere "
                    "else.")


def _remove(path: Path) -> None:
    """Delete the sandbox without following anything the child left in it."""
    for root, directories, files in os.walk(path, topdown=False):
        for name in files:
            try:
                os.remove(Path(root) / name)
            except OSError:
                pass
        for name in directories:
            entry = Path(root) / name
            try:
                os.rmdir(entry)                   # junctions included: rmdir, never
            except OSError:                       # a recursive delete through one
                pass
    try:
        os.rmdir(path)
    except OSError:
        pass


def build(model_path: Path, *, dest_dir: Path, step: bool,
          timeout: float = BUILD_TIMEOUT_S) -> BuiltCandidate:
    """Execute the candidate confined, and adopt what it made.

    Raises `BuildRefused` for every way this can go wrong -- a model that will not
    import, a builder that raises, a child that dies, a build that runs past its
    bound, a manifest that does not describe what was asked for, an output that
    is not a plain file inside the sandbox, and a confinement that could not be
    established at all. All of them are findings, and a finding is a message the
    caller writes down.
    """
    unavailable = confine.unavailable_reason()
    if unavailable:
        raise BuildRefused(
            "the confined build boundary could not be established, so the "
            f"candidate was not executed: {unavailable}")

    model_path = Path(model_path).resolve()
    dest_dir = Path(dest_dir).resolve()
    if not model_path.is_file():
        raise BuildRefused(f"no such model module: {model_path}")

    started = time.perf_counter()
    canary_path = dest_dir / CANARY_FILE
    canary_before = S.sha256_file(canary_path) if canary_path.is_file() else None

    sandbox = Path(tempfile.mkdtemp(prefix="design-tool-sandbox-"))
    input_dir = sandbox / INPUT_DIR
    build_dir = sandbox / OUTPUT_DIR
    try:
        input_dir.mkdir()
        build_dir.mkdir()
        # Created by the parent, inside the writable directory, before it is
        # sealed: `child_environment` points every "where do I put things"
        # variable at it, and a library that finds it missing makes it itself.
        (build_dir / HOME_DIR).mkdir()

        # Hashed and copied first, sealed second: the seal is what makes the
        # inputs read-only, and nothing can be written into a sealed directory,
        # this process included.
        input_sha256 = _stage(model_path, input_dir)
        module_sha256 = input_sha256[model_path.name]

        input_path = input_dir / INPUT_FILE
        input_path.write_text(
            S.canonical_json(child_input(model_name=model_path.name,
                                         build_dir=build_dir, input_dir=input_dir,
                                         step=step)),
            encoding="utf-8")

        confine.seal_read_only(input_dir)
        confine.seal_writable(build_dir)

        try:
            result = confine.run(child_command(input_path), cwd=build_dir,
                                 env=child_environment(build_dir), timeout=timeout)
        except confine.ConfinementUnavailable as exc:
            raise BuildRefused(
                f"the candidate was not executed: {exc}") from exc

        # The canary, before a single byte the child produced is looked at. The
        # confinement is what stops the write; this is what says so if it ever
        # did not, and it is deliberately one file rather than a list that has to
        # be kept in step with another one.
        canary_after = S.sha256_file(canary_path) if canary_path.is_file() else None
        if canary_after != canary_before:
            raise BuildRefused(
                f"{CANARY_FILE} changed while the candidate was building. The "
                "confinement grants the candidate no write access to the project "
                "directory, so this is a failure of the boundary itself and not a "
                "finding about the model. The run is refused.")

        if result.timed_out:
            raise BuildRefused(
                f"{model_path.name} did not finish building within {timeout:.0f}s "
                "and the whole build job was terminated."
                + (f" Its last output was:\n{_tail(result.output)}"
                   if result.output.strip() else ""))

        if result.survivors:
            raise BuildRefused(
                f"{model_path.name} left {result.survivors} process(es) running "
                "when its build exited. They were inside the build job object and "
                "have been terminated, and nothing was read out of the build "
                "directory until the job reported none left. A build that spawns "
                "something to outlive it is refused."
                + (f" Its output was:\n{_tail(result.output)}"
                   if result.output.strip() else ""))

        _sweep(build_dir)

        manifest_path = build_dir / MANIFEST_FILE
        if not manifest_path.is_file():
            raise BuildRefused(
                f"the build process exited with code {result.returncode} and wrote "
                f"no {MANIFEST_FILE}, so nothing is known about what it did."
                + (f" Its output was:\n{_tail(result.output)}"
                   if result.output.strip() else ""))

        manifest = _json_object(manifest_path, MANIFEST_FILE)
        model, artifacts, built = _sections(manifest, result.returncode,
                                            result.output)

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
            # Taken from the authoritative file before the child existed, and
            # never from the manifest.
            module_sha256=module_sha256,
            input_sha256=dict(input_sha256),
            params=dict(params),
            provenance=dict(provenance),
            stl_path=stl_path,
            step_path=step_path,
            kernel=str(built.get("kernel") or "unrecorded"),
            backend_version=str(built.get("backend_version") or "unrecorded"),
            tessellation=dict(built.get("tessellation") or {}),
            boolean_engine=str(built.get("boolean_engine") or "unrecorded"),
            build_seconds=float(built.get("build_seconds") or 0.0),
            boundary_seconds=time.perf_counter() - started)
    finally:
        # The input directory was sealed against its own creator, so write access
        # is taken back before the sandbox is removed. Everything the child wrote
        # that the parent did not ask for by name goes with it: there is no path
        # by which an unexpected file becomes an input to anything.
        for directory in (input_dir, build_dir, sandbox):
            if directory.is_dir():
                try:
                    confine.unseal(directory)
                except confine.ConfinementUnavailable:   # pragma: no cover
                    pass
        _remove(sandbox)
