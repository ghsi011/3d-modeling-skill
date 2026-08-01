#!/usr/bin/env python3
"""One interface, so backend choice never spreads into conditionals.

A backend takes a contract and an output directory and returns the artifacts it
wrote. Everything downstream -- commissioning, screening, witnesses, status --
reads the exported STL and never asks which kernel produced it.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Protocol


@dataclasses.dataclass(frozen=True)
class BuildArtifacts:
    stl_path: Path
    step_path: Path | None
    source_path: Path
    backend: str
    backend_version: str
    tessellation: dict[str, Any]
    boolean_ops: tuple[str, ...]
    build_seconds: float
    # Which engine resolved the booleans, by the backend's own account. Derived
    # in the runner until an authored model could reach it: "trimesh-manifold
    # implies manifold3d" is true of the certified backends and false of a model
    # that selects its own, and the manifest must not assert what nobody saw.
    boolean_engine: str = "unrecorded"


class GeometryBackend(Protocol):
    name: str

    def build(self, contract, output_dir: Path) -> BuildArtifacts: ...


def get(name: str, built=None) -> GeometryBackend:
    """Resolve a backend by name, importing only the one asked for.

    The lazy import is not tidiness. `import build123d` costs 10.7 s measured on
    this machine, against 1.5 s for trimesh and manifold3d together -- so a
    trimesh-only job that imported both would spend seven times its own build
    time loading a kernel it never calls.

    `built` is an `isolation.BuiltCandidate` and belongs to the authored backend
    alone: geometry a one-shot confined process already produced. The certified
    backends ignore it, which is why `DIRECT` pays nothing for the boundary.
    """
    if name == "trimesh-manifold":
        from .trimesh_manifold import TrimeshManifoldBackend
        return TrimeshManifoldBackend()
    if name == "build123d":
        from .build123d_backend import Build123dBackend
        return Build123dBackend()
    if name == "authored":
        from .authored import AuthoredBackend
        return AuthoredBackend(built)
    raise KeyError(f"no backend named {name!r}; have 'trimesh-manifold', "
                   "'build123d', 'authored'")
