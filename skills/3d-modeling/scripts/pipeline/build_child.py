#!/usr/bin/env python3
"""The confined build boundary: the child half. Run as `-m pipeline.build_child`.

This is the only module in the package that both imports the candidate's code and
is *not* imported by the parent. It is reached through `sys.executable` and by no
other route, so nothing here can be called from the process that freezes the
acceptance contract, commissions the artifact and decides the final status.

It runs under a restricted, low-integrity token inside a job object it cannot
leave (`confine.py`), so the authority it holds is: read the sealed input
directory, write the one output directory, and nothing else on the machine.

What it does, in one shot and then exits:

1. read the input document the parent staged into the sealed input directory;
2. put that input directory on `sys.path`, so a model that imports a helper the
   designer shipped beside it resolves the same way every time. It is a
   directory of *copies*; the authoritative sources are not reachable from here;
3. import and validate the model -- `authored.load`, which is where
   `spec.loader.exec_module` lives;
4. call the builder and export the geometry into the build directory;
5. write `build_manifest.json` beside it.

Everything it knows is in that input document: a directory of copied sources, a
model file name within it, a build directory, and whether a STEP was asked for.
It is not told where the project is. It is handed no acceptance contract, no
proposal, no expectations and no tolerances, so there is nothing here for
candidate code to rewrite. Anything it patches, mutates or monkeypatches dies
with the process, and the process dies inside the job.

**It reports, it does not assert.** The parent hashed the model before this
process existed, hashes every artifact itself, copies out only the two files it
asked for by name, and reads none of it until the job object reports no live
processes. The manifest is a description of a build, not a receipt about a part.

**Nothing written here is trusted to be written by this file.** `authored.load`
runs the model's module-level code in *this* interpreter, so a candidate can
rewrite this module, `schemas`, or anything else in this process before `main`
serialises anything. Every field of `build_manifest.json` is therefore
candidate-authored text, whatever the code above it intends, and the parent
treats it that way: it reads a `kernel` *token* out of a closed vocabulary it
owns (`isolation.KERNELS`) rather than the engine strings this file used to
supply, and it quarantines `PARAMS` and `PROVENANCE` in an
`isolation.CandidateDeclaration` that no reviewer packet has a parameter to
receive. That is D10, and the manifest is why it could not be fixed on this side
of the boundary.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from . import authored as A
from . import confine as C
from . import lazy_build123d as L
from . import schemas as S

# 3: the manifest reports a `kernel` *token* and no engine prose. It used to
# carry `backend_version`, `tessellation` and `boolean_engine` as strings the
# parent copied verbatim onto `artifact_manifest.json`, which the safety and
# verification reviewers both read -- three of D10's four channels. The parent
# owns those words now (`isolation.KERNELS`); this side says only which of two
# kernels exported the geometry. `model.name` went with them: nothing read it.
SCHEMA = 3


def _export(part: Any, stl_path: Path, step_path: Path | None) -> str:
    """Export whatever the model returned, and name the kernel that did it.

    The certified backends know their kernel because they *are* the kernel. An
    authored model calls whichever one it wants, so this detects what came back.
    What it returns is a token out of `isolation.KERNELS` and not a sentence: the
    parent looks the token up and writes its own words, so a candidate that lies
    here can pick between two answers rather than compose one.
    """
    # A trimesh mesh, or something that quacks like one.
    if hasattr(part, "export") and hasattr(part, "faces"):
        part.export(stl_path)
        return "trimesh"

    # A build123d / OCCT solid.
    from build123d import export_step, export_stl   # noqa: PLC0415 - kernel is lazy

    shape = getattr(part, "part", part)
    export_stl(shape, str(stl_path))
    if step_path is not None:
        export_step(shape, str(step_path))
    return "build123d"


def _serialisable(value: Any, what: str) -> Any:
    """A value that survives the boundary, or a finding naming the declaration.

    `PARAMS` and `PROVENANCE` used to be read out of a live module object in the
    same interpreter, so anything at all could sit in them. They now cross a
    process as JSON. That is a real constraint on a model and it is stated as one:
    a parameter the parent cannot read is a parameter the frozen proposal cannot
    be compared against.
    """
    try:
        json.dumps(value)
    except (TypeError, ValueError) as exc:
        raise A.ModelError(
            f"{what} does not survive the build boundary ({exc}). An authored "
            "model is built in its own process and reports what it declared as "
            "JSON, so a declaration must be made of numbers, strings, booleans, "
            "lists and objects.") from None
    return value


def _build(spec: dict[str, Any]) -> dict[str, Any]:
    input_dir = Path(str(spec["input_dir"]))
    model_path = input_dir / str(spec["model_name"])
    build_dir = Path(str(spec["build_dir"]))
    stl_path = build_dir / str(spec["stl_name"])
    step_name = spec.get("step_name")
    step_path = (build_dir / str(step_name)) if step_name else None

    # The sealed input directory, so `import a_helper_beside_me` resolves against
    # the copies the parent staged. Placed after this module's own imports are
    # already resolved: the candidate chooses what it imports, not what the
    # boundary does.
    sys.path.insert(0, str(input_dir))

    # The last act of the boundary, and the last line before any candidate byte
    # is imported. On Windows the process already cannot spawn -- the child
    # policy was set before it started -- and this is a no-op. On Linux the
    # parent's last act was an `execve`, so the filter could not exist until
    # now; installing it here means it covers exactly the code the boundary is
    # about. It is irrevocable: seccomp filters compose by intersection, so a
    # candidate may add one and can never remove one.
    C.seal_syscalls()

    started = time.perf_counter()
    # Inside the stopwatch deliberately, and after the seal: the facade is build
    # work, not boundary setup, and `build_seconds` must keep measuring the same
    # phase it always measured (`docs/baseline.md`, "the lazy build123d facade").
    # It defers the three `build123d` submodules that carry `sklearn` and `ezdxf`
    # -- measured on the bearing candidate, `docs/baseline.md` -- and it serves
    # nothing lazily on a build123d release whose public surface has not been
    # swept, so an unknown one builds exactly as it did before.
    #
    # `input_dir` is passed because this is the side that knows it: the directory
    # inserted above is the candidate's own, and a `build123d` resolved out of it
    # is one the designer supplied deliberately. The facade declines those on
    # origin, which is the only question that separates a complete, well-formed
    # candidate package from the installed one.
    L.install(input_dir)
    model, builder = A.load(model_path)
    part = builder() if callable(builder) else builder
    kernel = _export(part, stl_path, step_path)
    build_seconds = time.perf_counter() - started

    return {
        "schema_version": SCHEMA,
        "ok": True,
        "error": None,
        # The two declarations the parent quarantines. `params` it compares
        # against the frozen proposal and forwards to nothing; `provenance` it
        # records in `candidate_declaration.json` and forwards to nothing.
        "model": {
            "params": _serialisable(dict(model.params), "PARAMS"),
            "provenance": _serialisable(dict(model.provenance), "PROVENANCE"),
        },
        "artifacts": {
            "stl": stl_path.name,
            "step": step_path.name if step_path is not None else None,
        },
        "build": {"kernel": kernel, "build_seconds": round(build_seconds, 6)},
        "python": sys.version.split()[0],
    }


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        sys.stderr.write("usage: python -m pipeline.build_child <input.json>\n")
        return 2
    spec = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    manifest_path = Path(str(spec["build_dir"])) / str(spec["manifest_name"])

    try:
        payload = _build(spec)
    except SystemExit as exc:                     # a model calling sys.exit() is a
        payload = _failed("SystemExit",           # finding, not a silent success
                          f"the model ended the build process with exit "
                          f"{exc.code!r} before anything was exported")
    except Exception as exc:                      # noqa: BLE001 - every build
        payload = _failed(type(exc).__name__, str(exc))     # failure is a receipt

    try:
        text = S.canonical_json(payload)
    except (TypeError, ValueError) as exc:
        text = S.canonical_json(_failed(
            "UnreportableBuild",
            f"the build produced a result that cannot be reported as JSON: {exc}"))
    manifest_path.write_text(text, encoding="utf-8")
    return 0 if payload["ok"] else 1


def _failed(kind: str, message: str) -> dict[str, Any]:
    return {"schema_version": SCHEMA, "ok": False,
            "error": {"kind": kind, "message": message},
            "model": None, "artifacts": None, "build": None,
            "python": sys.version.split()[0]}


if __name__ == "__main__":                        # pragma: no cover - the boundary
    sys.exit(main(sys.argv[1:]))
