"""Deterministic export + re-import for candidate/reference geometry.

The recurring designer boilerplate this replaces: export an STL (and a STEP),
then re-load it to discover the REAL delivered geometry — is it watertight? how
many shells? what volume? — rather than trusting the CAD kernel's own numbers.
``.val().Volume()`` misreports on periodic-spline solids, and OCC tessellation
can silently split one solid into several shells; both have caused NOT_READY
candidates. Every candidate must be judged on the exported mesh, so this always
re-imports and reports what actually landed on disk, returning BOTH the
artifact (file-byte) hash used for revision binding and a geometry hash that is
stable across re-exports of the same shape.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import trimesh

from . import _bootstrap  # noqa: F401  (puts scripts/ on sys.path; keep first)

import mesh_io


@dataclass(frozen=True)
class ExportReport:
    """What actually landed on disk, measured on the re-imported raw mesh."""

    stl_path: str
    step_path: str | None
    file_sha256: str        # hash of the STL bytes — matches team_tools revision binding
    geometry_sha256: str    # hash of the raw mesh geometry — stable across re-export
    watertight: bool
    components: int
    triangle_count: int
    volume_mm3: float
    bbox_mm: dict           # {"x": .., "y": .., "z": ..}
    integrity: mesh_io.MeshIntegrity

    def is_single_watertight_solid(self) -> bool:
        return self.watertight and self.components == 1


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_solid(model: Any, stl_path: Path, step_path: Path | None,
                 tolerance: float, angular_tolerance: float) -> str | None:
    """Write an STL (+ optional STEP) from a CadQuery model, a trimesh mesh, or
    an existing STL path. Returns the STEP path actually written, or ``None``.
    """
    # Case 1: an existing STL path — copy it in if needed, nothing to tessellate.
    if isinstance(model, (str, Path)) and Path(model).exists():
        src = Path(model)
        if src.resolve() != stl_path.resolve():
            stl_path.write_bytes(src.read_bytes())
        return None
    # Case 2: a trimesh mesh. Use isinstance, NOT duck-typing — a CadQuery
    # Workplane also has `.export` and a `.vertices` selector, so hasattr would
    # misroute it here and silently skip the STEP export.
    if isinstance(model, trimesh.Trimesh):
        model.export(str(stl_path))
        return None
    # Case 3: assume a CadQuery Workplane/Shape (lazy import keeps CI cadquery-free).
    import cadquery as cq

    cq.exporters.export(model, str(stl_path),
                        tolerance=tolerance, angularTolerance=angular_tolerance)
    if step_path is not None:
        cq.exporters.export(model, str(step_path))
        return str(step_path)
    return None


def export_and_hash(model: Any, out_stem: str | Path, *, tolerance: float = 0.01,
                    angular_tolerance: float = 0.1,
                    also_step: bool = True) -> ExportReport:
    """Export ``model`` to ``<out_stem>.stl`` (+ ``.step`` for CadQuery models),
    re-import the STL with the authoritative raw loader, and return an
    :class:`ExportReport`.

    ``model`` may be a CadQuery ``Workplane``/``Shape``, a ``trimesh.Trimesh``,
    or a path to an already-exported STL (re-hashed and re-measured as-is).
    """
    out_stem = Path(out_stem)
    stl_path = out_stem.with_suffix(".stl")
    step_path = out_stem.with_suffix(".step") if also_step else None
    stl_path.parent.mkdir(parents=True, exist_ok=True)

    step_written = _write_solid(model, stl_path, step_path, tolerance, angular_tolerance)

    # STL is a vertex soup: watertightness and component count are only
    # meaningful after coincident vertices are merged, so measure them on the
    # normalized mesh (mutation log is available via load_mesh_report if the
    # amount of merging is itself suspicious). The geometry hash is the
    # normalized hash — stable across re-exports of the same shape.
    report = mesh_io.load_mesh_report(stl_path)
    norm = report.normalized
    integrity = mesh_io.compute_integrity(norm)
    ext = norm.bounding_box.extents
    return ExportReport(
        stl_path=str(stl_path),
        step_path=step_written,
        file_sha256=_file_sha256(stl_path),
        geometry_sha256=report.normalized_sha256,
        watertight=bool(integrity.watertight),
        components=int(integrity.components),
        triangle_count=int(integrity.face_count),
        volume_mm3=float(abs(norm.volume)),
        bbox_mm={"x": float(ext[0]), "y": float(ext[1]), "z": float(ext[2])},
        integrity=integrity,
    )
