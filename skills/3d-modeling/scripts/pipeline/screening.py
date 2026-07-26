#!/usr/bin/env python3
"""Broad geometry anomaly screening.

**What this is for.** Every check in `commission.py` is conditioned on the
contract naming a feature. Geometry nobody declared is invisible to all of them:
a 4 mm post standing in a bin floor once passed twenty-seven green checks, an
exact bounding box, a watertight verdict and a matching bed-contact area. These
screens are not tied to individual declared features, which is their value.

**What this is not.** They are not unconditioned, and they cannot prove absence.
A deleted countersink leaves a plain bore -- smooth, plausible, and anomalous
only against the curve the part should have had, which is the template that
produced it, so the comparison would be against itself. Missing features are the
contract's job and only the contract's. A screening pass is not coverage for
absence, and reading it that way is how the next defect ships.

**They escalate; they do not fail.** A broad screen has false positives, and a
false positive that fails a correct part teaches its reader to widen the
threshold until nothing fires.
"""
from __future__ import annotations

from typing import Any

from .analysis import MeshAnalysisContext
from .contract import Contract

# Fraction of the local section area. Scale-normalized on purpose: a 12 mm2 post
# in a 2,000 mm2 floor is 0.6%, and an absolute millimetre threshold either
# misses it on a large part or cries wolf on a small one.
STEP_FRACTION = 0.08

# Whether the screens have been measured against a mutation corpus, with
# published false-negative and false-positive rates. They have been:
# `python -m pipeline.corpus` builds 38 defective parts across three templates in
# five classes and reports what each instrument catches. Measured 38/38, with a
# 0.0 false-negative rate on the classes screening is responsible for and 0.0
# false positives on the clean parts.
#
# The flag is not an assertion. `test_pipeline.py::CalibrationTest` runs the
# corpus and fails if the gate stops passing, so screening that degrades takes
# this flag down with it rather than leaving a stale True behind.
#
# What it does NOT license: screening still cannot prove absence, and X and Y are
# still unscreened. A calibrated screen is a measured one, not a complete one.
CALIBRATED = True
CALIBRATION_NOTE = (
    "measured against a 38-mutant corpus across three templates: 0.0 false-negative "
    "rate on added material and boolean debris, 0.0 false positives on clean parts. "
    "Still true regardless: screening cannot prove a feature is absent, and only the "
    "Z axis is profiled.")
SAMPLES = 24
FRAGMENT_FRACTION = 0.02


def _profile_screen(ctx: MeshAnalysisContext, axis: int, envelope: dict[str, Any],
                    label: str) -> dict[str, Any]:
    """One axis of profile screening, against the heights a step is explained at.

    Legitimate parts step abruptly all the time -- ribs, pockets, shoulders,
    mounting bosses -- so a bare delta cannot tell a feature from a defect. The
    envelope is what makes the difference sayable, and `reference_envelope`
    always produces one: the bed and the top of the part are steps on every
    shape, so there is no shape for which the list is empty.
    """
    profile = ctx.axis_profile(axis, SAMPLES, jitter=0.13)
    if len(profile) < 3:
        return {"detector": f"profile-{label}", "result": "INDETERMINATE",
                "reason": "the part is too thin along this axis to profile"}
    steps = []
    for a, b in zip(profile, profile[1:]):
        local = max(a["area_mm2"], b["area_mm2"], 1e-6)
        delta = abs(b["area_mm2"] - a["area_mm2"]) / local
        if delta > STEP_FRACTION:
            steps.append({"from": a["at"], "to": b["at"], "fraction": round(delta, 4)})

    allowed = [float(v) for v in envelope.get(label, ())]
    unexplained = [s for s in steps
                   if not any(min(s["from"], s["to"]) - 1.0 <= at <= max(s["from"], s["to"]) + 1.0
                              for at in allowed)]
    if unexplained:
        return {"detector": f"profile-{label}", "result": "ANOMALY",
                "reason": f"{len(unexplained)} step(s) the contract does not explain",
                "steps": unexplained, "profile": profile}
    return {"detector": f"profile-{label}", "result": "CLEAR",
            "reason": f"{len(steps)} step(s), all at declared feature heights",
            "profile": profile}


def _component_screen(ctx: MeshAnalysisContext, contract: Contract) -> dict[str, Any]:
    """Count, and the shape a stray boolean fragment takes.

    The least conditioned of the set: a component nobody asked for is a defect
    whatever the contract says, and a fragment is recognisable by being tiny
    beside the body it broke off.
    """
    parts = ctx.components
    if not parts:
        return {"detector": "components", "result": "INDETERMINATE",
                "reason": "the mesh split into nothing"}
    volumes = sorted((abs(float(p.volume)) for p in parts), reverse=True)
    fragments = [v for v in volumes[1:] if v < volumes[0] * FRAGMENT_FRACTION]
    if len(parts) != contract.expected_bodies:
        return {"detector": "components", "result": "ANOMALY",
                "reason": f"{len(parts)} solids, contract declares {contract.expected_bodies}",
                "volumes_mm3": [round(v, 3) for v in volumes]}
    if fragments:
        return {"detector": "components", "result": "ANOMALY",
                "reason": f"{len(fragments)} solid(s) under {FRAGMENT_FRACTION:.0%} of the "
                          "largest -- the shape boolean debris takes",
                "volumes_mm3": [round(v, 3) for v in volumes]}
    return {"detector": "components", "result": "CLEAR",
            "reason": f"{len(parts)} solid(s) as declared, none vestigial"}


def _bed_screen(ctx: MeshAnalysisContext) -> dict[str, Any]:
    lowest = float(ctx.bounds[0][2])
    if lowest < -0.05:
        return {"detector": "bed-plane", "result": "ANOMALY",
                "reason": f"the part reaches {abs(lowest):.2f} mm below the bed, so no "
                          "downward measurement on it means what it says"}
    return {"detector": "bed-plane", "result": "CLEAR", "reason": f"lowest point {lowest:.3f} mm"}


def reference_envelope(contract: Contract) -> dict[str, Any]:
    """Heights along Z where a step is explained, from the contract and template.

    Derived from declarations, never from the mesh. A step at a declared feature
    is the feature; a step anywhere else is worth a look. Without this the
    detector cannot tell a rib from a defect, which is why an absent envelope
    reports INDETERMINATE rather than CLEAR.
    """
    from . import templates as T

    marks: list[float] = [0.0, float(contract.expected_bbox_mm.get("z", 0.0))]
    try:
        marks += [float(v) for v in T.get(contract.template).profile_marks(
            contract.parameters).get("z", ())]
    except KeyError:
        pass
    for feature in contract.features:
        exp = feature.expectation
        at = exp.get("at") or {}
        if "z" in at:
            marks.append(float(at["z"]))
        if "z" in exp:
            marks.append(float(exp["z"]))
        for key in ("z_from", "z_to"):
            if key in exp:
                marks.append(float(exp[key]))
    return {"z": sorted(set(round(v, 3) for v in marks))}


def run(ctx: MeshAnalysisContext, contract: Contract) -> dict[str, Any]:
    envelope = reference_envelope(contract)
    detectors = [
        _profile_screen(ctx, 2, envelope, "z"),
        _component_screen(ctx, contract),
        _bed_screen(ctx),
    ]
    results = {d["result"] for d in detectors}
    overall = "ANOMALY" if "ANOMALY" in results else (
        "INDETERMINATE" if "INDETERMINATE" in results else "CLEAR")
    return {
        "overall": overall,
        "escalates": overall != "CLEAR",
        "calibrated": CALIBRATED,
        "calibration_note": CALIBRATION_NOTE,
        "axes_screened": ["z"],
        # Stated rather than faked. An X/Y profile needs its own reference
        # envelope and its own calibrated threshold -- a round channel's area
        # changes fast near the tangent without anything being wrong, so an
        # uncalibrated cross-axis screen would cry wolf until somebody widened
        # it to silence. Emitting a permanent INDETERMINATE instead would be
        # worse: screening could never be CLEAR and the escalation would mean
        # nothing. Owned by the calibration phase.
        "axes_not_screened": {
            "x": "no calibrated threshold or reference envelope yet",
            "y": "no calibrated threshold or reference envelope yet",
        },
        "note": ("screening catches material that should not be there; it cannot prove "
                 "a feature is absent -- that is the contract's job"),
        "detectors": detectors,
    }
