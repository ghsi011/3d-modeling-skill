"""FreeCAD staging helpers for backend-neutral CAD artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from shutil import copy2
from typing import Protocol


class FreeCadMcpProbe(Protocol):
    """Minimal probe contract for a FreeCAD MCP connection."""

    def list_documents(self) -> tuple[str, ...]:
        """Return the open FreeCAD document names."""
        ...


@dataclass(frozen=True, slots=True)
class FreeCadExportPaths:
    """Paths exported by a FreeCAD document or MCP workflow."""

    stl: Path
    step: Path


@dataclass(frozen=True, slots=True)
class FreeCadStageError(RuntimeError):
    """Raised when a FreeCAD artifact cannot be staged."""

    path: Path

    def __str__(self) -> str:
        """Return the missing artifact path."""
        return f"missing FreeCAD export artifact: {self.path}"


def freecad_mcp_available(probe: FreeCadMcpProbe | None = None) -> bool:
    """Return whether a FreeCAD MCP probe can answer a document request."""
    if probe is None:
        return False
    try:
        probe.list_documents()
    except ConnectionError:
        return False
    return True


def stage_freecad_exports(exports: FreeCadExportPaths, staging_dir: Path) -> FreeCadExportPaths:
    """Copy FreeCAD-exported STL and STEP artifacts into a staging directory."""
    if not exports.stl.exists():
        raise FreeCadStageError(path=exports.stl)
    if not exports.step.exists():
        raise FreeCadStageError(path=exports.step)

    staging_dir.mkdir(parents=True, exist_ok=True)
    staged = FreeCadExportPaths(
        stl=staging_dir / exports.stl.name,
        step=staging_dir / exports.step.name,
    )
    copy2(exports.stl, staged.stl)
    copy2(exports.step, staged.step)
    return staged


__all__ = [
    "FreeCadExportPaths",
    "FreeCadMcpProbe",
    "FreeCadStageError",
    "freecad_mcp_available",
    "stage_freecad_exports",
]
