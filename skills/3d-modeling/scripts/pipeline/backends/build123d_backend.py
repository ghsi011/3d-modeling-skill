#!/usr/bin/env python3
"""Exact B-rep authoring: fillets, chamfers, revolves, and STEP.

**Every build123d import in this file is function-local.** Measured on this
machine `import build123d` costs 10.7 s against 1.5 s for trimesh and manifold3d
together, so a module-level import would tax every trimesh-only job with seven
times its own build time to load a kernel it never calls.

This backend always exports STL, because commissioning measures the mesh whatever
produced it. STEP is exported only when the contract asks.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .. import artifact_names as N
from .. import bindings
from .. import schemas as S
from . import BuildArtifacts
import mesh_io

# STL tessellation, recorded into the artifact manifest. A section area measured
# off a coarser mesh is a different number, so a receipt that does not say which
# deflection produced it cannot be compared against another run.
LINEAR_DEFLECTION = 0.01
ANGULAR_DEFLECTION = 0.1


def build_trim_ring(p: dict[str, Any]):
    """A lined hole: a skirt through the panel, a chamfered lip on top.

    The chamfer is why this template is build123d and not mesh CSG. An exact edge
    treatment is what a B-rep kernel is for; approximating one with boolean
    primitives is how a mesh pipeline ends up shipping a faceted lie.

    Algebra mode rather than builder contexts: the shape is three solids and two
    operations, and a builder context adds scoping rules without adding clarity.
    """
    from build123d import Align, Axis, Cylinder, Location, chamfer

    hole_d, lip_w = float(p["hole_d"]), float(p["lip_w"])
    panel_t, lip_t = float(p["panel_t"]), float(p["lip_t"])
    wall, cham = float(p["wall"]), float(p["chamfer"])
    bore_d, lip_outer = hole_d - 2.0 * wall, hole_d + 2.0 * lip_w
    seated = (Align.CENTER, Align.CENTER, Align.MIN)
    ops: list[str] = []

    solid = Cylinder(radius=hole_d / 2.0, height=panel_t, align=seated)
    ops.append("skirt: cylinder through the panel")

    solid = solid + Cylinder(radius=lip_outer / 2.0, height=lip_t, align=seated) \
        .moved(Location((0, 0, panel_t)))
    ops.append("union: lip on top of the skirt")

    solid = chamfer(solid.edges().group_by(Axis.Z)[-1], length=cham)
    ops.append(f"chamfer: top outer edge, {cham:g} mm")

    # Overshoot both ends. A cutter face landing exactly on the surface it
    # crosses leaves coplanar artifacts, which survive as degenerate faces and
    # fail repair on re-import.
    solid = solid - Cylinder(radius=bore_d / 2.0, height=panel_t + lip_t + 2.0,
                             align=seated).moved(Location((0, 0, -1.0)))
    ops.append("subtract: liner bore, overshot through both ends")

    # Into the +XY quadrant, seated at z=0 -- the convention every downstream
    # check assumes, and the one the plan's identity transform places the part by.
    solid = solid.moved(Location((lip_outer / 2.0, lip_outer / 2.0, 0)))
    ops.append("locate: +XY quadrant, min Z at zero")
    return solid, ops


_BUILDERS = {"trim_ring": build_trim_ring}


class Build123dBackend:
    name = "build123d"

    def build(self, contract, output_dir: Path) -> BuildArtifacts:
        started = time.perf_counter()
        import build123d
        from build123d import export_step, export_stl

        builder = _BUILDERS.get(contract.template)
        if builder is None:
            raise KeyError(f"{self.name}: no builder for template {contract.template!r}")
        part, ops = builder(contract.parameters)

        output_dir.mkdir(parents=True, exist_ok=True)
        stl_path = output_dir / "candidate.stl"
        mesh_io.validate_brep_tessellation(
            part, tolerance=LINEAR_DEFLECTION, angular_tolerance=ANGULAR_DEFLECTION
        )
        export_stl(part, str(stl_path),
                   tolerance=LINEAR_DEFLECTION, angular_tolerance=ANGULAR_DEFLECTION)

        step_path = None
        if contract.step_required:
            step_path = output_dir / "candidate.step"
            export_step(part, str(step_path))

        # `BACKEND_RECORD`, never `model.py` and never any `*.py`: the boundary
        # stages every top-level Python file beside the model as the designer's,
        # so a `.py` record would destroy a helper that happened to share its
        # name. Nothing executes this -- it is provenance -- so it is a receipt.
        #
        # Resolved through the registry under the backend's own owner and not the
        # pipeline's, so a record pointed at one of the runner's receipts is
        # refused here rather than written over it.
        record_path = N.path(output_dir, N.BACKEND_RECORD, owner=N.BACKEND)
        record_path.write_text(S.canonical_json({
            "schema_version": bindings.BACKEND_RECORD_SCHEMA,
            "record": "backend-build",
            "note": "Generated from model_contract.json. The contract is "
                    "authoritative; this records what was built and is not a "
                    "source of expectations.",
            "template": contract.template,
            "backend": self.name,
            "parameters": contract.parameters,
        }), encoding="utf-8")

        return BuildArtifacts(
            stl_path=stl_path, step_path=step_path,
            source_path=record_path, backend=self.name,
            backend_version=f"build123d {getattr(build123d, '__version__', 'unknown')}",
            tessellation={"linear_deflection": LINEAR_DEFLECTION,
                          "angular_deflection": ANGULAR_DEFLECTION},
            boolean_ops=tuple(ops),
            boolean_engine="n/a (B-rep)",
            build_seconds=time.perf_counter() - started,
        )


__all__ = ["Build123dBackend", "build_trim_ring"]
