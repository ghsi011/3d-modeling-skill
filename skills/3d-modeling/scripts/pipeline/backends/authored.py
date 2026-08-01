#!/usr/bin/env python3
"""Adopt the geometry the isolated build boundary already produced.

This module used to import the candidate's builder and call it here, inside the
process that then commissioned the result. It no longer executes anything:
`isolation.build` ran the model in a one-shot child process, re-hashed what came
back and copied the two files it asked for by name into the job directory. What
is left is the part of a backend that was always a receipt -- which kernel made
this, which engine resolved the booleans, how long it took -- and the checks that
the files it names are on disk.

The model module is never rewritten. The certified backends drop a `model.py`
beside the STL as a record of what was built; doing that here would overwrite the
authored source with a summary of itself.
"""
from __future__ import annotations

from pathlib import Path

from . import BuildArtifacts

NAME = "authored"


class AuthoredBackend:
    name = NAME

    def __init__(self, built=None) -> None:
        # An `isolation.BuiltCandidate`, injected by the runner. Never a
        # callable: a backend holding the candidate's builder is a backend that
        # can run it, and this one runs in the interpreter that decides whether
        # the candidate passed.
        self._built = built

    def _adopted(self, output_dir: Path, name: str, what: str) -> Path:
        path = output_dir / name
        if not path.is_file():
            raise ValueError(
                f"{name} is the {what} the build boundary reported and it is not in "
                f"{output_dir}; the artifact manifest would bind to a file that "
                "does not exist")
        return path

    def build(self, contract, output_dir: Path) -> BuildArtifacts:
        built = self._built
        if built is None:
            raise ValueError(
                "the authored backend must be handed the candidate the isolated "
                "build boundary produced; building the model here would execute it "
                "in the process that owns the acceptance contract")
        output_dir = Path(output_dir)

        stl_path = self._adopted(output_dir, built.stl_path.name, "exported mesh")
        step_path = None
        if contract.step_required:
            if built.step_path is None:
                raise ValueError(
                    "the contract requires a STEP export and the build boundary was "
                    "not asked for one")
            step_path = self._adopted(output_dir, built.step_path.name, "STEP export")

        source = contract.source or {}
        source_path = self._adopted(
            output_dir, str(source.get("module") or "model.py"),
            "contract's declared source")

        return BuildArtifacts(
            stl_path=stl_path,
            step_path=step_path,
            source_path=source_path,
            backend=self.name,
            backend_version=built.backend_version,
            tessellation=dict(built.tessellation),
            boolean_ops=(),
            boolean_engine=built.boolean_engine,
            build_seconds=built.build_seconds,
        )
