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

**A screen calibrated by its own subject is not a screen.** The volume and
profile detectors need an expectation to compare against. On the certified lane
that expectation comes from `templates.py`, which the designer does not write. On
the authored lanes it comes from the party whose work is being screened, so
neither detector may issue a `CLEAR` there: the volume detector reports
`NOT_APPLICABLE` and records the measurement, and the profile detector reports
`NOT_APPLICABLE` when every step sits at a declared height and `ANOMALY` when one
does not. The asymmetry is deliberate and it is not a weakened threshold -- a
step the designer's own declarations fail to explain is evidence against the part
whoever wrote the declarations, while a step they *do* explain is evidence of
nothing at all. ADR 0002 section 3 has the reasoning; `expected_volume_basis`
carries which of the legitimate sources, if any, the expectation came from.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from .analysis import MeasurementFailed, MeshAnalysisContext
from .contract import Contract

# Fraction of the local section area. Scale-normalized on purpose: a 12 mm2 post
# in a 2,000 mm2 floor is 0.6%, and an absolute millimetre threshold either
# misses it on a large part or cries wolf on a small one.
STEP_FRACTION = 0.08

# Whether the broad screen is trustworthy enough to stand in for a look.
# Measured, and the measurement is the point -- an earlier version of this flag
# said True on a number that turned out to be measuring something else.
#
# `uv run --project <skill> --frozen python -m pipeline.corpus` measures it, over every certified template and
# every defect class. **It currently fails**: screening's own false-negative rate
# on defects fused to the part is 0.30. Fifteen mutants pass every check here and
# every contract check -- among them a Ø4 x 8 mm post standing on the floor of a
# box_shell, one body, watertight, inside the envelope, +0.234% of the volume.
# That is verbatim the defect the first paragraph of this file exists to prevent.
#
# It read 0.0 until the corpus was fixed. Three construction errors, each of
# which flattered the screen:
#
#   * The rate was computed from `caught_by_contract or caught_by_screening`, so
#     it reported the pipeline's number while the screen itself missed 46.7%.
#   * Added material was placed at the centre of the bounding box at mid-height,
#     which inside a shell is air. Those mutants were separate solids, caught
#     free by the component detector, and excluded from the fused rate -- so the
#     0.0 was measured on `c_clip` alone, 11 mutants out of 30. `_require_fused`
#     now raises rather than letting one through, and there are 50.
#   * The profile compares neighbouring samples, so material that lifts the level
#     across a whole region shows no step. The volume detector closes part of
#     that, but its 0.25% band is above a real defect: the post costs 0.234%.
#
# The corpus size is deliberately not written down here. It was, twice, and both
# times a template was added and the number in this file became a false
# provenance claim stamped into every receipt.
#
# Also true and not something this flag could license even at 0.0: screening
# cannot prove a feature is *absent*, and only the Z axis is profiled.
CALIBRATED = False
CALIBRATION_NOTE = (
    "NOT CALIBRATED. `uv run --project <skill> --frozen python -m pipeline.corpus` measures a 0.30 false-negative "
    "rate on defects fused to the part -- a small boss standing on the floor "
    "passes every check here. Screening is evidence, not a substitute for a "
    "look, and this job needs one. It also cannot prove a feature is absent -- a "
    "deleted countersink leaves a plain bore -- and only the Z axis is profiled.")
SAMPLES = 24
FRAGMENT_FRACTION = 0.02

# How far the solid's own volume may sit from the closed form before it is worth
# a look. Measured tessellation error at the nominal points, worst first:
# trim_ring -0.0414%, c_clip -0.0144%, vented_enclosure -0.0066%, l_bracket
# +0.0008%, box_shell 0.0000%. So the band sits **6x** above the noise floor,
# and it catches a 1.1 mm post that moves the total 0.38%. Set at 1% it missed
# exactly that post.
#
# This comment claimed 0.01% and 25x, which was true of the three templates it
# was written against and false as soon as trim_ring's thin annulus arrived --
# `(R^2+r^2)/(R^2-r^2)` reaches 10.5x there, so faceting error is amplified by
# an order of magnitude. 6x is thinner headroom than 25x and the honest number
# to design the next change against.
VOLUME_FRACTION = 0.0025


def _independent(contract: Contract) -> bool:
    """Whether the expectations this screen calibrates against are second-party.

    One predicate, read by both calibrated detectors. `source` is absent on a
    certified contract and present on every authored one, which is exactly the
    line: a certified template's closed forms are written in `templates.py` by
    somebody who is not the designer, and an authored contract's come from the
    proposal the designer wrote.
    """
    return (contract.source or {}).get("kind") != "authored"


def _profile_screen(ctx: MeshAnalysisContext, axis: int, envelope: dict[str, Any],
                    label: str, *, independent: bool) -> dict[str, Any]:
    """One axis of profile screening, against the heights a step is explained at.

    Legitimate parts step abruptly all the time -- ribs, pockets, shoulders,
    mounting bosses -- so a bare delta cannot tell a feature from a defect. The
    envelope is what makes the difference sayable, and `reference_envelope`
    always produces one: the bed and the top of the part are steps on every
    shape, so there is no shape for which the list is empty.

    When the heights were declared by the party being screened, a clean result
    means only that the declarations and the geometry agree -- which they were
    written to. That is `NOT_APPLICABLE`, not `CLEAR`.
    """
    try:
        profile = ctx.axis_profile(axis, SAMPLES, jitter=0.13)
    except MeasurementFailed as exc:
        return {"detector": f"profile-{label}", "result": "INDETERMINATE",
                "reason": f"the boolean engine could not profile this axis: {exc}"}
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
    if not independent:
        return {"detector": f"profile-{label}", "result": "NOT_APPLICABLE",
                "reason": (f"{len(steps)} step(s), all at heights the frozen proposal "
                           "declares -- and the proposal is the designer's own, so "
                           "agreement here is not independent evidence and this "
                           "detector may not clear the part"),
                "calibration": "NOT_INDEPENDENTLY_SPECIFIED", "profile": profile}
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


def _volume_screen(ctx: MeshAnalysisContext, contract: Contract) -> dict[str, Any]:
    """Total solid volume against the closed form, from the parameters.

    The only screen here that does not need to know where a defect is, and the
    reason it exists: a profile compares neighbouring samples, so material that
    lifts the level across a whole region shows no step. Measured, a ledge adding
    24.9% and a rib adding 45.8% both screened CLEAR on the profile and were
    invisible to every declared check.

    Weak where volume has always been weak -- a deleted countersink moves it 0.9%,
    under any usable band -- and strong exactly where the profile is blind.
    """
    from . import templates as T

    source = contract.source or {}
    got = float(ctx.normalized.volume)
    if source.get("kind") == "authored":
        # ADR 0002 section 3: expected volume is an acceptance input only when it
        # is independently available. It was not, here, in the shape that mattered
        # -- the number came out of the same `model.py` the screen was screening,
        # so the detector was calibrated by its own subject and could be made
        # tautologically CLEAR by editing one line.
        #
        # No second-party source is invented to fill the gap. The measurement is
        # still on the receipt; what it may not do is clear a detector by
        # comparing against itself.
        basis = source.get("expected_volume_basis")
        declared = source.get("expected_volume_mm3")
        if (basis == "NOT_INDEPENDENTLY_SPECIFIED"
                or not isinstance(declared, (int, float))
                or isinstance(declared, bool)):
            return {"detector": "volume", "result": "NOT_APPLICABLE",
                    "reason": ("no independently specified expected volume exists for "
                               "this part, so there is nothing to compare the solid "
                               "against that the solid's own author did not write"),
                    "calibration": "NOT_INDEPENDENTLY_SPECIFIED",
                    "expected_mm3": None, "measured_mm3": round(got, 3)}
        want = float(declared)
    else:
        try:
            template = T.get(contract.template)
        except KeyError:
            return {"detector": "volume", "result": "INDETERMINATE",
                    "reason": f"no certified template named {contract.template!r}"}
        if template.volume is None:
            return {"detector": "volume", "result": "INDETERMINATE",
                    "reason": f"{contract.template} declares no closed-form volume, so "
                              "there is nothing to compare the solid against"}
        want = float(template.volume(contract.parameters))
    delta = (got - want) / want if want else 0.0
    if abs(delta) > VOLUME_FRACTION:
        return {"detector": "volume", "result": "ANOMALY",
                "reason": f"solid is {delta:+.1%} against the closed form "
                          f"({got:.1f} mm3 vs {want:.1f})",
                "expected_mm3": round(want, 3), "measured_mm3": round(got, 3)}
    return {"detector": "volume", "result": "CLEAR",
            "reason": f"{delta:+.2%} of the closed form",
            "expected_mm3": round(want, 3), "measured_mm3": round(got, 3)}


def _printer_frame_low_z(bounds, matrix) -> float | None:
    """The lowest Z the part reaches once the declared orientation is applied.

    All eight corners of the model-frame box, transformed, then the minimum -- a
    rotation does not keep the lowest corner lowest, so putting `bounds[0]`
    through the matrix would answer about a corner rather than about the part.

    Conservative, and only because the matrix is checked to be **rigid** first.
    A transformed box bounds the transformed mesh under an affine map, so this
    can read lower than the part goes and never higher, which turns an unlucky
    rotation into a look-again rather than a clean verdict. Under a *projective*
    matrix that is false: `w` is affine in the coordinates and can vanish inside
    the box while all eight corners sit far from zero, and the corner minimum
    then reads **higher** than the part goes. A review built one -- corner bound
    +0.5 mm against a true minimum near -49999 mm -- and it returned CLEAR while
    naming the printer frame. It passes `contract.preflight`,
    `cli._validate_orientation` and `project.validate`, all three of which check
    4x4-of-finite-numbers and no more.

    `is_finite_rigid` is the repo's existing answer and is strictly stronger
    than the shape check this used to carry: finite, last row exactly
    [0,0,0,1], the rotation block orthonormal, determinant +1. Reusing it rather
    than writing a fourth shape check is also the point -- the weaker of two
    authorities over one question was the one deciding the verdict.

    `None` where the matrix cannot be applied. The caller must refuse, not fall
    back to the model frame; falling back is the defect with an extra step.
    """
    from team_preflight import is_finite_rigid

    low, high = np.asarray(bounds, dtype=np.float64)
    if not np.all(np.isfinite([low, high])):
        return None
    if isinstance(matrix, str):
        return float(low[2]) if matrix == "identity" else None
    if not is_finite_rigid(matrix):
        return None
    transform = np.array(matrix, dtype=np.float64)
    corners = np.array([[x, y, z] for x in (low[0], high[0])
                        for y in (low[1], high[1])
                        for z in (low[2], high[2])], dtype=np.float64)
    moved = corners @ transform[:3, :3].T + transform[:3, 3]
    return float(np.min(moved[:, 2]))


def _bed_screen(ctx: MeshAnalysisContext, contract: Contract) -> dict[str, Any]:
    """Does the part reach below the bed -- in the frame it will be printed in?

    This used to read `ctx.bounds[0][2]`, the lowest Z of the mesh *as
    authored*, and its signature took no contract, so it could not see the
    declared orientation even in principle. `docs/defects.md` D15 filed that as
    an unused field; it is worse than that. A job could declare a rotation
    putting the part below the bed, have the rotation validated and hashed into
    the acceptance contract, and receive `bed-plane: CLEAR` -- a clean verdict
    about a frame the job never said it was working in.

    So the frame is named in every reason string, and a matrix that cannot be
    applied is an anomaly rather than a fallback.
    """
    orientation = contract.orientation if isinstance(contract.orientation, dict) else {}
    matrix = orientation.get("model_to_printer_matrix")
    # No default. This slice's own fixture argues that defaulting it "would
    # answer a question the job did not ask -- the same substitution the frame
    # defect was made of", and then the code defaulted it to 0.0.
    bed_z = orientation.get("bed_z_mm")
    # Finite, not merely a float: NaN is a float, `NaN > 0.05` is False, and a
    # NaN bed height therefore fell straight through to CLEAR. Caught by the
    # fixture rather than by review, which is the only reason it is not shipping.
    if (isinstance(bed_z, bool) or not isinstance(bed_z, (int, float))
            or not math.isfinite(float(bed_z))):
        return {"detector": "bed-plane", "result": "ANOMALY",
                "reason": "orientation.bed_z_mm is not a finite number, so there "
                          "is no bed height to measure against and no downward "
                          "measurement means what it says"}
    lowest = _printer_frame_low_z(ctx.bounds, matrix)
    if lowest is None:
        return {"detector": "bed-plane", "result": "ANOMALY",
                "reason": "orientation.model_to_printer_matrix cannot be applied, "
                          "so this part's height above the bed is unknown. "
                          "Measuring the model frame instead would report a "
                          "clean result about a frame the job did not declare"}
    # `isinstance` first: `matrix == "identity"` on a numpy array raises
    # `ValueError: the truth value of an array ... is ambiguous`, and this is
    # the second place that comparison appears.
    identity = isinstance(matrix, str) and matrix == "identity"
    frame = ("model frame (orientation is identity)" if identity
             else "printer frame (the declared orientation is applied)")
    below = float(bed_z) - lowest
    if below > 0.05:
        return {"detector": "bed-plane", "result": "ANOMALY",
                "reason": f"the part reaches {below:.2f} mm below the bed in the "
                          f"{frame}, so no downward measurement on it means what "
                          "it says"}
    return {"detector": "bed-plane", "result": "CLEAR",
            "reason": f"lowest point {lowest:.3f} mm against a bed at "
                      f"{float(bed_z):.3f} mm, measured in the {frame}"}


def reference_envelope(contract: Contract) -> dict[str, Any]:
    """Heights along Z where a step is explained, from the contract and template.

    Derived from declarations, never from the mesh. A step at a declared feature
    is the feature; a step anywhere else is worth a look. Without this the
    detector cannot tell a rib from a defect, which is why it is derived from the
    contract rather than passed in and allowed to be missing.
    """
    from . import templates as T

    marks: list[float] = [0.0, float(contract.expected_bbox_mm.get("z", 0.0))]
    source = contract.source or {}
    if source.get("kind") == "authored":
        marks += [float(v) for v in (source.get("profile_marks") or {}).get("z", ())]
    else:
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


class ScreeningShapeUnexpected(ValueError):
    """A commission report's screening block is not the shape `run` writes.

    Loud rather than absent, and the reason is what happened without it.
    `compare._measured` read `screening.detectors` as a mapping keyed by
    detector name; `run` returns a *list*, and every L0 fixture that exercised
    the comparison had been written to agree with the reader instead of with
    this module. Twenty-two fixtures agreed with each other, the code passed,
    and the first time the verb met a receipt an actual run had written it
    raised `AttributeError` inside a dict comprehension.

    A reader that shrugged and returned nothing would have been worse: the
    comparison's material axis would have reported "no volume measured" on every
    job forever, which is a sentence nobody would think to doubt.
    """


def detectors(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Every detector row a commission report carries, in the order `run` wrote them.

    The single reader, and it is this one rather than `detector` below: a review
    of the commit that added `detector` pointed out that `tools/replay.py` still
    reached into `screening["detectors"]` by hand -- inside the very function
    `docs/defects.md` D27 claimed went through the pipeline's own reader. One
    caller fixed and one caller left is not "one reader", it is one reader and
    one place the next shape change surfaces as a bare `AttributeError`.

    Empty for a report with no screening block, which is a job that did not get
    that far. Raising for a report whose block is the wrong *type*, which is a
    caller reading a shape no run has ever produced.
    """
    screening = report.get("screening") or {}
    rows = screening.get("detectors")
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise ScreeningShapeUnexpected(
            f"screening.detectors is {type(rows).__name__} and `screening.run` "
            f"writes a list of rows, each carrying its own 'detector' key. A "
            f"caller reading it as a {type(rows).__name__} is reading a shape "
            "no run has ever produced.")
    return [row for row in rows if isinstance(row, dict)]


def detector(report: dict[str, Any], name: str) -> dict[str, Any] | None:
    """One detector's row, looked up by name, or `None` if it did not run."""
    for row in detectors(report):
        if row.get("detector") == name:
            return row
    return None


def run(ctx: MeshAnalysisContext, contract: Contract) -> dict[str, Any]:
    envelope = reference_envelope(contract)
    independent = _independent(contract)
    detectors = [
        _profile_screen(ctx, 2, envelope, "z", independent=independent),
        _volume_screen(ctx, contract),
        _component_screen(ctx, contract),
        _bed_screen(ctx, contract),
    ]
    results = {d["result"] for d in detectors}
    # `NOT_APPLICABLE` is deliberately not in this ladder. It says a detector had
    # nothing valid to compare against, which is neither a finding nor a
    # clearance, and promoting it to either would be the same mistake in a
    # different direction -- `INDETERMINATE` would park every authored job on
    # NEEDS_MORE_EVIDENCE for a detector that was never going to apply, and
    # counting it towards `CLEAR` is the self-issued pass this stage removes.
    # What stops a part being claimed on the strength of a screen full of them is
    # `CALIBRATED`, which is False and which `status.decide` reads: an
    # uncalibrated screen with nobody independent looking cannot reach
    # COMMISSIONED at all.
    overall = "ANOMALY" if "ANOMALY" in results else (
        "INDETERMINATE" if "INDETERMINATE" in results else "CLEAR")
    return {
        "overall": overall,
        "escalates": overall != "CLEAR",
        "calibrated": CALIBRATED,
        "calibration_note": CALIBRATION_NOTE,
        # Which lane's policy the two calibrated detectors ran under, and whether
        # the expectations they compare against came from anyone other than the
        # party being screened.
        "expectation_source": "SECOND_PARTY" if independent else "SELF_DECLARED",
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
