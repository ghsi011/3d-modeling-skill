"""CadQuery adapter for the backend-neutral CAD contract."""

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
class CadQueryBackend(ModelBackend[ParamsT, SolidT], Generic[ParamsT, SolidT]):
    """CadQuery backend using a caller-supplied typed build function."""

    builder: Callable[[ParamsT], SolidT]
    stl_tolerance: float = 0.01
    angular_tolerance: float = 0.1

    def build(self, params: ParamsT) -> SolidT:
        """Build a CadQuery solid through the configured builder."""
        import_module("cadquery")
        return self.builder(params)

    def export(self, solid: SolidT, stem: Path) -> ExportPaths:
        """Export the CadQuery solid to STL and STEP artifacts."""
        stl_path = stem.with_suffix(".stl")
        step_path = stem.with_suffix(".step")
        stl_path.parent.mkdir(parents=True, exist_ok=True)
        cadquery = import_module("cadquery")
        export = getattr(getattr(cadquery, "exporters"), "export")
        export(solid, str(stl_path), tolerance=self.stl_tolerance, angularTolerance=self.angular_tolerance)
        export(solid, str(step_path))
        return {"stl": stl_path, "step": step_path}


__all__ = ["CadQueryBackend"]
