"""build123d adapter for the backend-neutral CAD contract."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Generic, TypeVar

from . import ExportPaths, ModelBackend

ParamsT = TypeVar("ParamsT")
SolidT = TypeVar("SolidT")


@dataclass(frozen=True, slots=True)
class Build123dExportError(RuntimeError):
    """Raised when build123d reports an export failure."""

    exporter: str
    path: Path

    def __str__(self) -> str:
        """Return a stable error message for failed build123d exporters."""
        return f"{self.exporter} failed for {self.path}"


@dataclass(frozen=True, slots=True)
class Build123dBackend(ModelBackend[ParamsT, SolidT], Generic[ParamsT, SolidT]):
    """build123d backend using a caller-supplied typed build function."""

    builder: Callable[[ParamsT], SolidT]
    stl_tolerance: float = 0.01
    angular_tolerance: float = 0.1

    def build(self, params: ParamsT) -> SolidT:
        """Build a build123d solid through the configured builder."""
        return self.builder(params)

    def export(self, solid: SolidT, stem: Path) -> ExportPaths:
        """Export the build123d solid to STL and STEP artifacts."""
        stl_path = stem.with_suffix(".stl")
        step_path = stem.with_suffix(".step")
        build123d = import_module("build123d")
        export_stl = getattr(build123d, "export_stl")
        export_step = getattr(build123d, "export_step")

        stl_exported = export_stl(
            solid,
            stl_path,
            tolerance=self.stl_tolerance,
            angular_tolerance=self.angular_tolerance,
        )
        if stl_exported is False:
            raise Build123dExportError(exporter="export_stl", path=stl_path)
        step_exported = export_step(solid, step_path)
        if step_exported is False:
            raise Build123dExportError(exporter="export_step", path=step_path)
        return {"stl": stl_path, "step": step_path}


__all__ = ["Build123dBackend", "Build123dExportError"]
