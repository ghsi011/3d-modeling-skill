"""One call that turns a finished solid into the Phase-4 evidence bundle.

Runs the toolkit-native checks the designer would otherwise stitch together by
hand — export + re-import, measure, overhang screen, datum placement, and (when
a seated reference is supplied) interference + insertion sweep — and returns a
JSON-serialisable evidence dict plus a readiness skeleton to drop into the
candidate's readiness section. The AUTHORITATIVE gate (``team_preflight``) and
the artifact manifest (``team_tools``) stay separate CLIs by design; this does
not re-implement or replace them — it collects the measurements they and the
human reviewer need, in one place, deterministically.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import exporter, fit, metrics


def asdict_feature(f) -> dict:
    return {"kind": f.kind, "center_mm": list(f.center_mm),
            "size_mm": list(f.size_mm), "area_mm2": round(f.area_mm2, 4)}


def _datum_block(stl_path: str, datum: dict) -> dict:
    origin = datum["plane_origin"]
    normal = datum.get("plane_normal", (0, 0, 1))
    feats = metrics.datum_features(stl_path, origin, normal)
    return {
        "name": datum.get("name", "datum"),
        "plane_origin": list(origin),
        "plane_normal": list(normal),
        "features": [asdict_feature(f) for f in feats],
    }


def finalize(model: Any, out_stem: str | Path, *, datums=(), reference: Any = None,
             insertion=None, orientation_transform=None,
             overhang_threshold: float = metrics.DEFAULT_DOWNWARD_NORMAL_Z_MAX,
             also_step: bool = True) -> dict:
    """Export ``model``, measure it, and assemble a Phase-4 evidence bundle.

    ``datums``: iterable of ``{"name", "plane_origin", "plane_normal"?}``.
    ``reference``: seated mating mesh/STL for interference (optional).
    ``insertion``: ``{"travels": [...], "axis": (..)}`` for a sweep (optional).
    ``orientation_transform``: 4x4 model-to-printer transform for the overhang
    screen (optional; identity if omitted).
    """
    report = exporter.export_and_hash(model, out_stem, also_step=also_step)
    stl_path = report.stl_path

    overhang = metrics.overhang_area(
        stl_path, threshold=overhang_threshold, transform=orientation_transform)

    evidence: dict = {
        "export": {
            "stl_path": report.stl_path,
            "step_path": report.step_path,
            "file_sha256": report.file_sha256,
            "geometry_sha256": report.geometry_sha256,
            "watertight": report.watertight,
            "components": report.components,
            "triangle_count": report.triangle_count,
            "volume_mm3": round(report.volume_mm3, 4),
            "bbox_mm": {k: round(v, 4) for k, v in report.bbox_mm.items()},
        },
        "overhang_mm2": round(overhang, 4),
        "overhang_threshold": overhang_threshold,
        "datums": [_datum_block(stl_path, d) for d in datums],
    }

    if reference is not None:
        evidence["seated_interference_mm3"] = round(fit.interference(stl_path, reference), 6)
        if insertion is not None:
            steps = fit.insertion_sweep(
                stl_path, reference, insertion["travels"],
                axis=insertion.get("axis", (0, 0, -1)))
            evidence["insertion_sweep"] = [
                {"travel_mm": s.travel_mm, "interference_mm3": round(s.interference_mm3, 6),
                 "blocked": s.blocked} for s in steps]

    # Readiness skeleton — deterministic parts filled; the judgment fields
    # (visual accept, fit-band call) stay for the agent to complete.
    notes: list = []
    if not report.is_single_watertight_solid():
        notes.append(
            f"NOT a single watertight solid (watertight={report.watertight}, "
            f"components={report.components}) — investigate before delivery.")
    if overhang > 1.0:
        notes.append(
            f"{overhang:.1f} mm2 of downward-facing area past the support screen "
            "in the given orientation — reorient or declare SUPPORT_ALLOWED.")
    if evidence.get("seated_interference_mm3", 0.0) > 1e-3:
        notes.append(
            f"seated interference {evidence['seated_interference_mm3']} mm3 — "
            "confirm this is an intended interference/crush/snap fit, else re-clear.")

    evidence["readiness_skeleton"] = {
        "single_watertight_solid": report.is_single_watertight_solid(),
        "overhang_mm2": round(overhang, 4),
        "auto_notes": notes,
        "visual_accept": None,      # agent must LOOK (render.compare_views) and decide
        "fit_band_ok": None,        # print engineer / agent judgment
    }
    return evidence
