"""Backend-neutral CAD contract for the 3D modeling pipeline.

designer_toolkit verification is backend-neutral because it operates on the
exported mesh artifact, not on an in-memory CadQuery/build123d/FreeCAD solid.
Concrete backend adapters must keep heavyweight CAD imports lazy so light CI can
import this package with only the core mesh stack installed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar, TypedDict

ParamsT = TypeVar("ParamsT")
SolidT = TypeVar("SolidT")


class ExportPaths(TypedDict):
    """Paths emitted by a CAD backend export operation."""

    stl: Path
    step: Path


class ModelBackend(ABC, Generic[ParamsT, SolidT]):
    """Common interface for CAD backend adapters."""

    @abstractmethod
    def build(self, params: ParamsT) -> SolidT:
        """Build an opaque backend-native solid from typed parameters."""

    @abstractmethod
    def export(self, solid: SolidT, stem: Path) -> ExportPaths:
        """Export the solid to mesh and CAD-exchange artifacts using stem."""


@dataclass(frozen=True, slots=True)
class FakeBuildParams:
    """Typed parameters for the dependency-free test backend."""

    label: str


@dataclass(frozen=True, slots=True)
class FakeSolid:
    """Opaque solid used by FakeBackend tests without CAD dependencies."""

    label: str


class FakeBackend(ModelBackend[FakeBuildParams, FakeSolid]):
    """Dependency-free backend for unit tests of backend-agnostic callers."""

    def build(self, params: FakeBuildParams) -> FakeSolid:
        """Return an opaque fake solid carrying the build label."""
        return FakeSolid(label=params.label)

    def export(self, solid: FakeSolid, stem: Path) -> ExportPaths:
        """Write placeholder STL and STEP files and return their paths."""
        stl_path = stem.with_suffix(".stl")
        step_path = stem.with_suffix(".step")
        stl_path.write_text(f"solid {solid.label}\nendsolid {solid.label}\n", encoding="utf-8")
        step_path.write_text(f"ISO-10303-21; /* {solid.label} */\n", encoding="utf-8")
        return {"stl": stl_path, "step": step_path}


__all__ = [
    "ExportPaths",
    "FakeBackend",
    "FakeBuildParams",
    "FakeSolid",
    "ModelBackend",
]
