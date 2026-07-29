#!/usr/bin/env python3
"""Measure the exported solid against the contract, and fail closed.

Every check names the contract feature it answers, so coverage is countable
rather than asserted: a feature with no check that ran is not covered, whatever
the other checks said. That is the shape of the failure this replaces -- a
candidate shipped 31% too thick while three checks reported SKIPPED, nothing
counted them, and the gate exited zero.

A check that cannot run does not decide its own consequence. The contract said,
in advance, whether that feature's silence is an `ESCALATE` or a `FAIL`.
"""
from __future__ import annotations

import dataclasses
import math
from typing import Any

from . import schemas as S
from .analysis import MeasurementFailed, MeshAnalysisContext
from .contract import Contract, Feature

# Which check answers which declared kind. The preflight validates a feature's
# `verified_by` against these names, so a contract cannot name a check that does
# not exist and then read its absence as silence.
KNOWN_CHECKS = frozenset({
    "section_area", "bed_contact", "through_hole", "bore_by_displacement",
    "void_region", "envelope", "watertight", "bodies", "unit_scale", "seated",
    "fit_acceptance",
})


@dataclasses.dataclass
class Check:
    check_id: str
    feature_id: str | None
    title: str
    ran: bool
    reason: str
    expected: Any
    measured: Any
    tolerance: Any
    result: str
    status: str = "MEASURED"
    error_code: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if not self.ran and self.measured is None and self.status == "MEASURED":
            self.status = "UNAVAILABLE"
        S.require_enum(self.status, S.MEASUREMENT_STATUS, what="check.status")

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def _tol(tolerance: dict[str, Any], expected: float) -> float:
    if "abs" in tolerance:
        return float(tolerance["abs"])
    if "frac" in tolerance:
        return abs(float(tolerance["frac"]) * float(expected))
    band = tolerance.get("band")
    if band:
        return abs(float(band[1]) - float(band[0])) / 2.0
    raise ValueError("tolerance declares no abs, frac or band")


def _verdict(feature: Feature, ok: bool, ran: bool) -> str:
    if not ran:
        return "ESCALATE" if feature.on_unrunnable == "ESCALATE" else "FAIL"
    return "PASS" if ok else "FAIL"


def _unavailable_check(feature: Feature, title: str, reason: str, code: str,
                       expected: Any, tolerance: Any) -> Check:
    return Check(
        check_id=f"feature-{feature.feature_id}", feature_id=feature.feature_id,
        title=title, ran=False, reason=reason, expected=expected, measured=None,
        tolerance=tolerance, result=_verdict(feature, False, False),
        status="UNAVAILABLE", error_code=code, error_message=reason)


def _feature_check(ctx: MeshAnalysisContext, feature: Feature,
                   bed_contact_mm2: float | None) -> Check:
    exp = feature.expectation
    kind = feature.kind

    if kind == "section_area":
        z = float(exp["at"]["z"])
        want = float(exp["value_mm2"])
        tol = _tol(feature.tolerance, want)
        try:
            got = ctx.section_area(z)
        except MeasurementFailed as exc:
            return _unavailable_check(
                feature, f"Section area at z={z:.2f}", str(exc), exc.code, want, tol)
        measured: Any = round(got, 3)
        probe = exp.get("fit_probe")
        if isinstance(probe, dict):
            at = probe.get("at")
            z_probe = probe.get("z")
            fit_value = None
            if (isinstance(at, dict) and isinstance(z_probe, (int, float))
                    and not isinstance(z_probe, bool)
                    and isinstance(at.get("x"), (int, float))
                    and isinstance(at.get("y"), (int, float))):
                try:
                    fit_value = round(ctx.section_bore_diameter_mm(
                        z=float(z_probe), at=(float(at["x"]), float(at["y"]))), 4)
                except MeasurementFailed:
                    fit_value = None
            measured = {"area_mm2": round(got, 3), "fit_value_mm": fit_value}
        return Check(f"feature-{feature.feature_id}", feature.feature_id,
                     f"Section area at z={z:.2f}", True, "measured", want, measured, tol,
                     _verdict(feature, abs(got - want) <= tol, True))

    if kind == "bed_contact":
        want = float(exp["value_mm2"])
        tol = _tol(feature.tolerance, want)
        if bed_contact_mm2 is None:
            return _unavailable_check(
                feature, "Bed contact area",
                "no placement was computed, so there is no contact area",
                "NO_PLACEMENT", want, tol)
        return Check(f"feature-{feature.feature_id}", feature.feature_id,
                     "Bed contact area", True, "measured", want, round(bed_contact_mm2, 3), tol,
                     _verdict(feature, abs(bed_contact_mm2 - want) <= tol, True))

    if kind == "through_hole":
        from designer_toolkit import features as F
        at, want = exp["at"], float(exp["d_mm"])
        z0, z1 = float(exp["z_from"]), float(exp["z_to"])
        tol = _tol(feature.tolerance, want)
        radius = want * 0.7
        worst, detail = 0.0, []
        for frac in (0.2, 0.5, 0.8):
            z = z0 + frac * (z1 - z0)
            try:
                got = F.bore_diameter_mm(ctx.normalized, float(at["x"]), float(at["y"]), z, radius)
            except F.Indeterminate as exc:
                return _unavailable_check(
                    feature, f"Bore {want:.2f} mm", str(exc),
                    "BORE_INDETERMINATE", want, tol)
            except Exception as exc:
                # This instrument is the one feature check that does not go
                # through `analysis._intersect`, so an engine refusal here used
                # to escape commission.run entirely -- no report, no verdict.
                # An absent engine answer is not a measured zero: it is an
                # UNAVAILABLE observation, exactly like every other check's.
                return _unavailable_check(
                    feature, f"Bore {want:.2f} mm",
                    f"the boolean engine could not measure the bore at z={z:.2f}: "
                    f"{exc}. An absent engine answer is not an empty bore.",
                    "BOOLEAN_ENGINE_REFUSED", want, tol)
            detail.append(round(got, 3))
            worst = max(worst, abs(got - want))
        return Check(f"feature-{feature.feature_id}", feature.feature_id,
                     f"Bore {want:.2f} mm", True, "three stations along the axis",
                     want, detail, tol, _verdict(feature, worst <= tol, True))

    if kind == "bore_by_displacement":
        # A large bore in a thin wall cannot be measured by the two-radius
        # cross-check: that needs r and 0.8r both buried in material, and a
        # 56 mm bore behind a 2 mm wall leaves no radius where both are. The
        # check correctly refused rather than reporting a number computed
        # mostly from fresh air -- so this measures the same bore a different
        # way, by how much material is missing from a disc of known size.
        at, want = exp["at"], float(exp["d_mm"])
        outer_d, z = float(exp["enclosing_d_mm"]), float(exp["z"])
        tol = _tol(feature.tolerance, want)
        outer_area = math.pi / 4.0 * outer_d * outer_d
        try:
            material = ctx.disc_area(z=z, at=(float(at["x"]), float(at["y"])), diameter=outer_d)
        except MeasurementFailed as exc:
            return _unavailable_check(
                feature, f"Bore {want:.2f} mm", str(exc), exc.code, want, tol)
        void = outer_area - material
        if void <= 0.0:
            return _unavailable_check(
                feature, f"Bore {want:.2f} mm",
                "the enclosing disc is entirely solid, so no bore is present to "
                "measure at this height",
                "BORE_NOT_PRESENT", want, tol)
        got = 2.0 * math.sqrt(void / math.pi)
        return Check(f"feature-{feature.feature_id}", feature.feature_id,
                     f"Bore {want:.2f} mm", True,
                     f"material missing from a {outer_d:.2f} mm disc at z={z:.2f}",
                     want, round(got, 3), tol, _verdict(feature, abs(got - want) <= tol, True))

    if kind == "void_region":
        at, size, z = exp["at"], exp["size_mm"], float(exp["z"])
        allowed = float(exp.get("max_area_mm2", 0.0))
        tol = _tol(feature.tolerance, allowed or 1.0)
        lo, hi = ctx.bounds[0], ctx.bounds[1]
        half_x, half_y = float(size[0]) / 2.0, float(size[1]) / 2.0
        cx, cy = float(at["x"]), float(at["y"])
        if (cx - half_x < lo[0] - 0.02 or cx + half_x > hi[0] + 0.02
                or cy - half_y < lo[1] - 0.02 or cy + half_y > hi[1] + 0.02):
            return _unavailable_check(
                feature, "Void region",
                "the window reaches outside the part's own footprint, so an "
                "empty reading would be fresh air rather than a clear cavity",
                "WINDOW_OUTSIDE_FOOTPRINT", allowed, tol)
        try:
            got = ctx.window_area(z=z, at=(cx, cy), size=(float(size[0]), float(size[1])))
        except MeasurementFailed as exc:
            return _unavailable_check(
                feature, "Void region", str(exc), exc.code, allowed, tol)
        return Check(f"feature-{feature.feature_id}", feature.feature_id,
                     "Void region", True, "material inside a declared-empty window",
                     allowed, round(got, 3), tol,
                     _verdict(feature, got - allowed <= tol, True))

    return _unavailable_check(
        feature, f"Feature kind {kind!r}",
        f"no check implements kind {kind!r}",
        "UNKNOWN_CHECK_KIND", None, None)


def _fit_acceptance_check(feature: Feature, checks: list[Check]) -> Check:
    """Bind an uncertainty-aware fit row to measurements of this candidate.

    The fit row is not allowed to pass merely because its metadata is present.
    ``candidate_feature_id`` names the one ordinary geometry check that measured
    the mapped parameter on the exported candidate. A fit acceptance row passes
    only when that measurement ran and lies inside the fitted band; a mutated
    candidate therefore fails the fit gate even when the external measurement
    and tolerance metadata are unchanged.
    """
    expectation = feature.expectation
    candidate_id = expectation.get("candidate_feature_id")
    if not isinstance(candidate_id, str) or not candidate_id:
        return _unavailable_check(
            feature, f"Fit acceptance {expectation.get('interface_id', '?')}",
            "no candidate geometry check is bound to this fit acceptance row",
            "FIT_CANDIDATE_UNBOUND", expectation, feature.tolerance)

    by_id = {check.feature_id: check for check in checks if check.feature_id}
    candidate = by_id.get(candidate_id)
    if candidate is None:
        return _unavailable_check(
            feature, f"Fit acceptance {expectation.get('interface_id', '?')}",
            f"candidate geometry check is missing: {candidate_id}",
            "FIT_CANDIDATE_CHECK_MISSING", expectation, feature.tolerance)

    measured = candidate.measured
    values: list[float]
    if isinstance(measured, dict):
        raw_value = measured.get("fit_value_mm")
        if raw_value is None:
            return _unavailable_check(
                feature, f"Fit acceptance {expectation.get('interface_id', '?')}",
                f"candidate measurement {candidate_id} could not produce the fit dimension",
                "FIT_MEASUREMENT_UNAVAILABLE", expectation, feature.tolerance)
        values = [float(raw_value)] if isinstance(raw_value, (int, float)) else []
    elif isinstance(measured, (int, float)) and not isinstance(measured, bool):
        values = [float(measured)]
    elif isinstance(measured, list):
        values = [float(value) for value in measured
                  if isinstance(value, (int, float)) and not isinstance(value, bool)]
    else:
        values = []
    raw_target = expectation.get("target_mm")
    raw_tolerance = expectation.get("acceptance_tolerance_mm")
    target = (float(raw_target)
              if isinstance(raw_target, (int, float)) and not isinstance(raw_target, bool)
              and math.isfinite(raw_target) else None)
    tolerance = (float(raw_tolerance)
                 if isinstance(raw_tolerance, (int, float)) and not isinstance(raw_tolerance, bool)
                 and math.isfinite(raw_tolerance) else None)
    numeric = target is not None and tolerance is not None
    target_value = target if target is not None else 0.0
    tolerance_value = tolerance if tolerance is not None else 0.0
    ok = (candidate.ran and candidate.result == "PASS" and numeric and bool(values)
          and all(abs(value - target_value) <= tolerance_value for value in values))
    results = {candidate_id: candidate.result}
    return Check(
        check_id=f"feature-{feature.feature_id}", feature_id=feature.feature_id,
        title=f"Fit acceptance {expectation.get('interface_id', '?')}",
        ran=True,
        reason="candidate measurement is inside the fitted target band" if ok else
               "candidate measurement is outside the fitted target band",
        expected={key: expectation.get(key) for key in (
            "nominal_mm", "clearance_mm", "target_mm", "uncertainty_mm",
            "acceptance_tolerance_mm")},
        measured={"candidate_check": results, "candidate_value_mm": values},
        tolerance=feature.tolerance,
        result="PASS" if ok else "FAIL")


def run(ctx: MeshAnalysisContext, contract: Contract) -> dict[str, Any]:
    checks: list[Check] = []

    watertight = bool(ctx.normalized.is_watertight)
    checks.append(Check("watertight", None, "Closed solid", True, "measured",
                        True, watertight, None, "PASS" if watertight else "FAIL"))

    bodies = len(ctx.components)
    checks.append(Check("bodies", None, "Separate solids", True, "measured",
                        contract.expected_bodies, bodies, None,
                        "PASS" if bodies == contract.expected_bodies else "FAIL"))

    lowest = float(ctx.bounds[0][2])
    checks.append(Check("seated", None, "Part sits on the bed", True, "measured",
                        0.0, round(lowest, 4), 0.05,
                        "PASS" if abs(lowest) <= 0.05 else "FAIL"))

    extents = [float(v) for v in ctx.extents]
    want = contract.expected_bbox_mm
    tol = contract.bbox_tolerance_mm
    worst = max(abs(extents[i] - float(want[k])) for i, k in enumerate("xyz"))
    checks.append(Check("envelope", None, "Overall size vs contract", True, "measured",
                        want, {k: round(extents[i], 3) for i, k in enumerate("xyz")}, tol,
                        "PASS" if worst <= tol else "FAIL"))

    # A part exported in inches reads as a plausible small part in millimetres.
    # 25.4x is the only mismatch worth naming, because it is the only one that
    # happens by accident.
    ratio = max(extents) / max(float(v) for v in want.values()) if max(want.values()) else 1.0
    suspicious = any(abs(ratio - f) < 0.02 for f in (25.4, 1 / 25.4))
    checks.append(Check("unit_scale", None, "Units are millimetres", True,
                        f"extent ratio {ratio:.3f} against the contract",
                        "mm", "mm", None, "FAIL" if suspicious else "PASS"))

    bed_contact = _bed_contact(ctx)
    for feature in contract.features:
        if feature.kind == "fit_acceptance":
            continue
        checks.append(_feature_check(ctx, feature, bed_contact))

    for feature in contract.features:
        if feature.kind == "fit_acceptance":
            checks.append(_fit_acceptance_check(feature, checks))

    declared = [f for f in contract.features if f.mandatory]
    covered = [c for c in checks if c.feature_id and c.ran]
    coverage = len(covered) / len(declared) if declared else 1.0

    failed = [c for c in checks if c.result == "FAIL"]
    escalated = [c for c in checks if c.result == "ESCALATE"]
    if coverage < contract.minimum_coverage:
        failed.append(Check("coverage", None, "Mandatory feature coverage", True,
                            "counted", contract.minimum_coverage, round(coverage, 3), None, "FAIL"))
        checks.append(failed[-1])

    if ctx.repair_actions:
        checks.append(Check("repair", None, "Raw vs normalized", True,
                            "; ".join(ctx.repair_actions), "no geometric change",
                            list(ctx.repair_actions), None, "ESCALATE"))
        escalated.append(checks[-1])
    else:
        checks.append(Check("repair", None, "Raw vs normalized", True,
                            f"vertex merge {ctx.vertex_merge[0]} -> {ctx.vertex_merge[1]} "
                            "is the STL format, not a repair; faces and volume unchanged",
                            "no geometric change", "none", None, "PASS"))

    verdict = "FAIL" if failed else ("ESCALATE" if escalated else "PASS")
    return {
        "schema_version": S.COMMISSION_SCHEMA,
        "contract_hash": contract.contract_hash(),
        "verdict": verdict,
        "coverage": {"covered": len(covered), "declared": len(declared),
                     "fraction": round(coverage, 4),
                     "minimum": contract.minimum_coverage},
        "mesh_loads": ctx.load_count,
        "repair_actions": list(ctx.repair_actions),
        "raw_parse_integrity": ctx.integrity,
        "normalization_log": ctx.mutations,
        "checks": [c.as_dict() for c in checks],
    }


def _bed_contact(ctx: MeshAnalysisContext) -> float:
    """Area of faces lying on the bed plane, in the part's own placement."""
    mesh = ctx.normalized
    z0 = float(ctx.bounds[0][2])
    triangles = mesh.triangles
    on_bed = (abs(triangles[:, :, 2] - z0).max(axis=1) <= 0.02)
    down = mesh.face_normals[:, 2] <= -0.999
    keep = on_bed & down
    if not keep.any():
        return 0.0
    return float(mesh.area_faces[keep].sum())


def area_tolerance(expected: float) -> dict[str, Any]:
    """The default band for an area expectation.

    A floor of 1 mm2 and a fraction of 0.5%: tessellation noise on a section is
    about 0.04 mm2, and the smallest defect worth catching moved 67. Anything
    between those two numbers is the whole design.
    """
    return {"abs": max(1.0, 0.005 * abs(float(expected)))}


def diameter_tolerance(expected: float) -> dict[str, Any]:
    return {"abs": max(0.12, 0.01 * abs(float(expected)))}
