"""designer_toolkit — deterministic CAD-evaluation helpers for the 3D pipeline.

Codifies the Phase-4 boilerplate the designer and verifier used to re-author
(and re-debug) every job — export + re-import, measurement, datum extraction,
overhang screening, boolean fit, coupon generation, rendered comparison — so the
agent writes only the parametric geometry and the judgment, and calls tested code
for everything mechanical. Every measurement runs on the EXPORTED mesh, the same
geometry the print will be sliced from.

Design notes:
* Measurement/fit/coupon are mesh-based and need no CAD kernel (CI-safe).
* ``exporter.export_and_hash`` also accepts CadQuery models (lazy import).
* ``render`` needs a pyrender/GL context; its import is deferred to call time.
"""

from __future__ import annotations

from .coupon import CouponLane, fit_coupon, legend_to_rows
from .exporter import ExportReport, export_and_hash
from .fit import interference
from .metrics import (
    DEFAULT_DOWNWARD_NORMAL_Z_MAX,
    Feature,
    MeasureReport,
    datum_features,
    measure,
    overhang_area,
)

__all__ = [
    "DEFAULT_DOWNWARD_NORMAL_Z_MAX",
    "CouponLane",
    "ExportReport",
    "Feature",
    "MeasureReport",
    "datum_features",
    "export_and_hash",
    "fit_coupon",
    "interference",
    "legend_to_rows",
    "measure",
    "overhang_area",
]
