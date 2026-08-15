#!/usr/bin/env python3
"""The model contract: what the solid must be, written before it exists.

Two properties make this worth a separate artifact rather than a dict beside the
model.

**It is upstream.** Expectations that live in `model.py` disappear with the code
that produced them. This repo has the failure documented: drop `countersink_d`
and the geometry and its expectation vanish together, because one parameter drove
both -- the part is then self-consistently wrong and nothing objects. A contract
written before the build survives the build being wrong.

**It is immutable.** Once a build starts, the contract is frozen and hashed. Every
downstream artifact binds to that hash, so a receipt can be traced to the exact
requirement it was measured against, and a contract edited mid-flight invalidates
its own receipts rather than quietly redefining success.
"""
from __future__ import annotations

import dataclasses
import math

from typing import Any


from . import schemas as S


class ContractError(ValueError):
    """The contract cannot be used as written."""


# --------------------------------------------------------------------------
# System-owned acceptance bands
# --------------------------------------------------------------------------
#
# Here rather than in `commission.py` because a tolerance is a statement about
# what the contract requires, not about how a mesh is measured -- and because
# `acceptance.py` has to compute one while importing no analysis module and no
# backend. Nothing about the numbers moved.


def area_tolerance(expected: float) -> dict[str, Any]:
    """The default band for an area expectation.

    A floor of 1 mm2 and a fraction of 0.5%: tessellation noise on a section is
    about 0.04 mm2, and the smallest defect worth catching moved 67. Anything
    between those two numbers is the whole design.
    """
    return {"abs": max(1.0, 0.005 * abs(float(expected)))}


def diameter_tolerance(expected: float) -> dict[str, Any]:
    return {"abs": max(0.12, 0.01 * abs(float(expected)))}


@dataclasses.dataclass(frozen=True)
class Feature:
    """One thing the solid must have, and how anyone would know.

    All five fields are required by the preflight. The last is the one people
    forget: a check that cannot run has to have said in advance what its silence
    means, or silence becomes a pass.
    """

    feature_id: str
    kind: str
    provenance: str
    expectation: dict[str, Any]
    tolerance: dict[str, Any]
    verified_by: str
    on_unrunnable: str = "ESCALATE"
    mandatory: bool = True

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class Contract:
    job_id: str
    template: str
    template_version: str
    domain_id: str | None
    backend: str
    parameters: dict[str, Any]
    features: tuple[Feature, ...]
    expected_bbox_mm: dict[str, float]
    bbox_tolerance_mm: float
    expected_bodies: int
    orientation: dict[str, Any]
    material: dict[str, Any]
    nozzle: dict[str, Any]
    printer: str
    modifiers: tuple[str, ...]
    minimum_coverage: float
    step_required: bool
    consequence: str
    updated_utc: str
    # Where the geometry comes from when it is not a certified template: the
    # authored module's project-relative path and its hash. Omitted from the
    # payload entirely when absent, so every certified contract keeps the hash
    # it already had -- an added key that is always null is still an added key,
    # and it would have moved every frozen golden in `selftest.py`.
    source: dict[str, Any] | None = None

    def as_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": S.CONTRACT_SCHEMA,
            "job_id": self.job_id,
            "template": self.template,
            "template_version": self.template_version,
            "domain_id": self.domain_id,
            "backend": self.backend,
            "parameters": self.parameters,
            "features": [f.as_dict() for f in self.features],
            "expected_bbox_mm": self.expected_bbox_mm,
            "bbox_tolerance_mm": self.bbox_tolerance_mm,
            "expected_bodies": self.expected_bodies,
            "orientation": self.orientation,
            "material": self.material,
            "nozzle": self.nozzle,
            "printer": self.printer,
            "modifiers": list(self.modifiers),
            "minimum_coverage": self.minimum_coverage,
            "step_required": self.step_required,
            "consequence": self.consequence,
            "updated_utc": self.updated_utc,
        }
        if self.source is not None:
            payload["source"] = self.source
        return payload

    def contract_hash(self) -> str:
        return S.payload_hash(self.as_payload())


# --------------------------------------------------------------------------
# Preflight
# --------------------------------------------------------------------------

_REQUIRED_FIELDS = ("provenance", "expectation", "tolerance", "verified_by", "on_unrunnable")


def as_transform(matrix: Any):
    """One declared matrix resolved to one usable transform, or None.

    The convention, in one function, so that nothing in this repository grows a
    second one. `printer_transform` reads the contract's orientation through it,
    `preflight` reads a print plan rule's own matrix through it to check the two
    agree, and `cli._inherited_overhang` reads an edit scope's
    `alignment_transform` through it before composing. Three declarations of a
    placement, one predicate deciding whether a mesh may be moved by them.

    `team_preflight.is_finite_rigid` is the predicate: finite, last row exactly
    [0,0,0,1], the rotation block orthonormal, determinant +1. Weaker than that
    is not a transform a mesh may be moved by -- and the affine requirement is
    load-bearing rather than fastidious, because `screening` bounds a part by
    its transformed box corners, which is conservative for an affine map and
    *wrong in the unsafe direction* for a projective one. Measured on a matrix
    every shape check in this repository accepts: corner bound +0.5 mm against a
    true minimum near -49999 mm, reported CLEAR.

    `"identity"` resolves to the identity matrix rather than to None: a job that
    declares no reorientation has declared one and is entitled to an answer. It
    is the spelling both `orientation.model_to_printer_matrix` and
    `edit_scopes[].alignment_transform` already use for that.
    """
    from team_preflight import is_finite_rigid
    import numpy as np

    if isinstance(matrix, str):
        return np.eye(4) if matrix == "identity" else None
    if not is_finite_rigid(matrix):
        return None
    return np.array(matrix, dtype=np.float64)


def printer_transform(contract: Contract):
    """The declared model-to-printer transform, or None if it cannot be applied.

    One reading of `orientation.model_to_printer_matrix`, here because this is
    where the field lives. `screening` and `commission` both call it, and that
    is the point rather than a convenience: D15 (`CHANGELOG.md`) is a receipt
    holding two answers about one part, produced by two readings of one
    declaration, and a review of the first half of the fix found the weakest of
    four shape checks over this question deciding the verdict.
    """
    orientation = contract.orientation if isinstance(contract.orientation, dict) else {}
    return as_transform(orientation.get("model_to_printer_matrix"))


def declared_bed_z(contract: Contract) -> float | None:
    """The bed height the job declared, or None where it did not declare one.

    Not defaulted to zero. Defaulting answers a question the job did not ask,
    which is the substitution D15 was made of -- and `NaN` is a `float` for
    which every comparison is False, so a NaN bed height would pass a type check
    and then quietly decide a verdict.
    """
    orientation = contract.orientation if isinstance(contract.orientation, dict) else {}
    bed_z = orientation.get("bed_z_mm")
    if isinstance(bed_z, bool) or not isinstance(bed_z, (int, float)):
        return None
    return float(bed_z) if math.isfinite(float(bed_z)) else None


def _number(expectation: dict[str, Any], field: str) -> float | None:
    value = expectation.get(field)
    if (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value)):
        return float(value)
    return None


def _span(expectation: dict[str, Any], field: str) -> tuple[float, float] | None:
    value = expectation.get(field)
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    out = []
    for item in value:
        if (not isinstance(item, (int, float)) or isinstance(item, bool)
                or not math.isfinite(item)):
            return None
        out.append(float(item))
    return (out[0], out[1])


def _counterpart_fit_problems(expectation: dict[str, Any], where: str) -> list[str]:
    """Every reason an assembled-interface row could not decide anything.

    All of it runs before a mesh is loaded, and all of it is about the *zones*
    rather than about the candidate -- which is the point of the row. The two
    zones are frozen from the counterpart and the assembly pose, so a candidate
    cannot move the question it is asked, and neither can a designer: this kind
    is in no `PROPOSABLE` whitelist.
    """
    problems: list[str] = []
    for field in ("counterpart", "counterpart_sha256"):
        value = expectation.get(field)
        if not isinstance(value, str) or not value.strip():
            problems.append(
                f"{where}: counterpart fit must name {field}. A zone placed against "
                "a mating object nobody identified is a zone about nothing.")

    pose = expectation.get("pose")
    if not isinstance(pose, dict):
        problems.append(f"{where}: counterpart fit must declare a pose")
        pose = {}
    centre = pose.get("centre_mm")
    if (not isinstance(centre, (list, tuple)) or len(centre) != 3
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                       and math.isfinite(v) for v in centre)):
        problems.append(
            f"{where}: pose.centre_mm must be three finite numbers -- where the "
            "counterpart sits in the candidate's frame. The halves export in their "
            "printed pose, so an assembled question needs the assembled placement "
            "stated rather than assumed.")
    axis = pose.get("axis")
    if (not isinstance(axis, (list, tuple)) or len(axis) != 3
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                       and math.isfinite(v) for v in axis)):
        problems.append(f"{where}: pose.axis must be three finite numbers")
    elif not any(float(v) != 0.0 for v in axis):
        problems.append(
            f"{where}: pose.axis is all zeros, so the zones have no orientation")

    bodies = expectation.get("bodies")
    if not isinstance(bodies, list) or not bodies:
        problems.append(
            f"{where}: counterpart fit must declare at least one body and where it "
            "goes. The halves of a split part export in their printed pose -- side "
            "by side, not assembled -- so an assembled question asked of the file "
            "as exported is asked at the wrong place.")
        bodies = []
    seen_locators: set[tuple[float, ...]] = set()
    for index, row in enumerate(bodies):
        at = f"{where}: bodies[{index}]"
        if not isinstance(row, dict):
            problems.append(f"{at} must be a mapping")
            continue
        locator = row.get("locator_mm")
        if (not isinstance(locator, (list, tuple)) or len(locator) != 3
                or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                           and math.isfinite(v) for v in locator)):
            problems.append(
                f"{at}.locator_mm must be three finite numbers. A body is named by "
                "a point the contract puts inside it, because split order is not "
                "an identity and anything the candidate writes about itself is not "
                "independent of the candidate.")
        else:
            key = tuple(round(float(v), 6) for v in locator)
            if key in seen_locators:
                problems.append(
                    f"{at}.locator_mm {list(key)} is already used by another body, "
                    "so the two rows name the same solid")
            seen_locators.add(key)
        if as_transform(row.get("transform")) is None:
            problems.append(
                f"{at}.transform is not a finite rigid transform. Translation and a "
                "proper rotation only: a reflection would assemble a mirror image "
                "of the part that was printed, and a scale would fit a bearing to a "
                "part no printer made.")

    retain_r = _span(expectation, "retain_r_mm")
    if retain_r is None:
        problems.append(
            f"{where}: retain_r_mm must be [inner, outer] finite radii -- the band "
            "the candidate is required to grip")
    elif not 0.0 <= retain_r[0] < retain_r[1]:
        problems.append(
            f"{where}: retain_r_mm {list(retain_r)} is not an annulus with "
            "0 <= inner < outer")

    clear_r = _number(expectation, "clear_r_mm")
    if clear_r is None or clear_r <= 0.0:
        problems.append(
            f"{where}: clear_r_mm must be a positive radius -- the cylinder the "
            "candidate must stay out of")
    elif retain_r is not None and clear_r > retain_r[0]:
        problems.append(
            f"{where}: clear_r_mm {clear_r:g} reaches past the retained band's "
            f"inner radius {retain_r[0]:g}, so the two zones overlap and one piece "
            "of material would answer both questions at once -- required here and "
            "forbidden there.")

    for field in ("retain_z_mm", "clear_z_mm"):
        span = _span(expectation, field)
        if span is None:
            problems.append(f"{where}: {field} must be [low, high] finite numbers")
        elif span[1] <= span[0]:
            problems.append(
                f"{where}: {field} {list(span)} has no height, so the zone it names "
                "encloses nothing")

    floor = _number(expectation, "min_retain_mm3")
    if floor is None or floor <= 0.0:
        problems.append(
            f"{where}: min_retain_mm3 must be positive. A retention floor of zero "
            "is satisfied by a part that touches the counterpart nowhere, and a "
            "gate that cannot fail is not one.")
    ceiling = _number(expectation, "max_intrusion_mm3")
    if ceiling is None or ceiling < 0.0:
        problems.append(
            f"{where}: max_intrusion_mm3 must be zero or positive -- how much "
            "material is tolerated inside the forbidden cylinder")
    return problems


def preflight(contract: Contract, *, known_checks: frozenset[str]) -> list[str]:
    """Every reason this contract cannot be built against, or an empty list.

    Runs after the contract is written and before any geometry is paid for. None
    of what it checks needs a mesh, which is the whole point: an archived run
    spent 39 minutes building against a plan whose single support rule was
    incomplete, then had the plan rejected afterwards.
    """
    problems: list[str] = []

    if not contract.features:
        problems.append(
            "no features declared: a contract that requires nothing of the solid "
            "cannot fail, and a gate that cannot fail is not one")

    seen: set[str] = set()
    for feature in contract.features:
        where = f"feature {feature.feature_id!r}"
        if feature.feature_id in seen:
            problems.append(f"{where}: duplicate id -- receipts could not name which one")
        seen.add(feature.feature_id)

        for field in _REQUIRED_FIELDS:
            value = getattr(feature, field, None)
            if value is None or value == "" or value == {}:
                problems.append(
                    f"{where}: missing {field}. A mandatory feature needs all of "
                    f"{', '.join(_REQUIRED_FIELDS)} before anything is built.")

        if feature.on_unrunnable not in S.ON_UNRUNNABLE:
            problems.append(
                f"{where}: on_unrunnable={feature.on_unrunnable!r}. Legal values are "
                f"{list(S.ON_UNRUNNABLE)}. 'skip' is not among them: a candidate "
                "shipped 31% too thick while three checks reported SKIPPED and the "
                "gate exited zero.")

        if feature.verified_by and feature.verified_by not in known_checks:
            problems.append(
                f"{where}: verified_by={feature.verified_by!r} names no check this "
                f"build implements. Known: {sorted(known_checks)}")

        if feature.tolerance and not any(
                k in feature.tolerance for k in ("abs", "frac", "band")):
            problems.append(
                f"{where}: tolerance declares no 'abs', 'frac' or 'band'. A bare "
                "number is either untestable or secretly exact.")

        if feature.kind == "fit_acceptance":
            expectation = feature.expectation
            required = (
                "interface_id", "nominal_mm", "clearance_mm", "target_mm",
                "uncertainty_mm", "acceptance_tolerance_mm",
                "candidate_feature_id", "parameter",
            )
            for field in required:
                if field not in expectation:
                    problems.append(
                        f"{where}: fit acceptance is missing {field}; the fit gate must "
                        "carry its complete uncertainty-aware contract")
            for field in ("nominal_mm", "target_mm", "uncertainty_mm",
                          "acceptance_tolerance_mm"):
                value = expectation.get(field)
                if (not isinstance(value, (int, float)) or isinstance(value, bool)
                        or not math.isfinite(value)):
                    problems.append(
                        f"{where}: fit acceptance {field} must be finite numeric")
            margin = expectation.get("acceptance_tolerance_mm")
            if isinstance(margin, (int, float)) and not isinstance(margin, bool):
                if margin < 0.01:
                    problems.append(
                        f"{where}: fit acceptance margin {margin!r} is below the "
                        "minimum credible 0.01 mm")
            # A mapped parameter with no supported candidate instrument is a
            # validly recorded UNAVAILABLE outcome, not permission to bind an
            # unrelated template feature. Commission reports that outcome.
            parameter = expectation.get("parameter")
            if not isinstance(parameter, str) or not parameter.strip():
                problems.append(
                    f"{where}: fit acceptance parameter must name the mapped built "
                    "parameter")

        if feature.kind == "counterpart_fit":
            problems.extend(_counterpart_fit_problems(feature.expectation, where))

    if not contract.expected_bbox_mm:
        problems.append("no expected_bbox_mm: nothing would check the part's own size, "
                        "and a candidate once shipped 31% too thick that way")
    if contract.bbox_tolerance_mm <= 0:
        problems.append("bbox_tolerance_mm must be positive")
    if (not isinstance(contract.expected_bodies, int)
            or isinstance(contract.expected_bodies, bool)
            or contract.expected_bodies < 1):
        problems.append("expected_bodies must be at least 1")
    if not 0.0 < contract.minimum_coverage <= 1.0:
        problems.append("minimum_coverage must be in (0, 1]")
    S.require_enum(contract.consequence, S.CONSEQUENCE, what="contract.consequence")
    S.require_enum(contract.backend, S.BACKEND, what="contract.backend")

    if not isinstance(contract.printer, str) or not contract.printer.strip():
        problems.append("printer is required and must be a non-empty string")

    material = contract.material
    if (not isinstance(material, dict)
            or not isinstance(material.get("process"), str)
            or not material["process"].strip()
            or not isinstance(material.get("material"), str)
            or not material["material"].strip()):
        problems.append("material must name non-empty process and material strings")

    nozzle = contract.nozzle
    diameter = nozzle.get("diameter_mm") if isinstance(nozzle, dict) else None
    if (not isinstance(diameter, (int, float)) or isinstance(diameter, bool)
            or diameter <= 0):
        problems.append("nozzle.diameter_mm must be a positive number")

    orientation = contract.orientation
    matrix = (orientation.get("model_to_printer_matrix")
              if isinstance(orientation, dict) else None)
    matrix_ok = matrix == "identity" or (
        isinstance(matrix, list) and len(matrix) == 4
        and all(isinstance(row, list) and len(row) == 4
                and all(isinstance(value, (int, float)) and not isinstance(value, bool)
                        for value in row)
                for row in matrix))
    bed_z = orientation.get("bed_z_mm") if isinstance(orientation, dict) else None
    if not matrix_ok:
        problems.append("orientation.model_to_printer_matrix must be 'identity' or a 4x4 matrix")
    if not isinstance(bed_z, (int, float)) or isinstance(bed_z, bool):
        problems.append("orientation.bed_z_mm must be a number")
    # The two functions the checks actually use. `preflight` exists so a job is
    # refused "before any geometry is paid for", and it accepted a mirror, a
    # projective matrix, a uniform scale and a NaN bed height that
    # `printer_transform` and `declared_bed_z` all refuse -- so those four paid
    # for the whole build and then landed on "the geometry does not match its
    # contract", which is a claim about a comparison that never happened.
    if printer_transform(contract) is None:
        problems.append(
            "orientation.model_to_printer_matrix is not a usable rigid "
            "transform (finite, last row [0,0,0,1], orthonormal rotation, "
            "determinant +1), so no check that places this part can run")
    if declared_bed_z(contract) is None:
        problems.append(
            "orientation.bed_z_mm is not a finite number, so there is no bed "
            "height for a placement check to measure against")
    problems += _frame_disagreements(contract)
    return problems


def _frame_disagreements(contract: Contract) -> list[str]:
    """Where a feature row and the contract declare two different print frames.

    The half of D15 that survived the first two fixes. `commission` measures the
    candidate's overhang in `printer_transform(contract)`; the ceiling it is
    measured against comes off a print plan support rule which carries its
    *own* `model_to_printer_matrix` and `bed_z_mm`. Nothing compared them, so the
    two sides of one inequality could be two frames -- and `cli._plan_features`
    dropped the rule's matrix on the way here, which meant the contract's
    orientation was silently substituted for a declaration another artifact had
    made and nobody had checked.

    Refused rather than reconciled, and refused *here* rather than at the
    measurement, for the reason the rest of this function exists: a frame
    disagreement needs no mesh to find, and choosing either side of it would be
    this file deciding which of two declarations the job meant. A rule that
    agrees is silent; a rule that does not stops the run before geometry is paid
    for.

    Compared as resolved transforms and not as literals: `"identity"` and the
    4x4 identity are one declaration in two spellings, and refusing that pair
    would fail every job that spells them differently for no geometric reason.
    """
    import numpy as np

    declared = printer_transform(contract)
    bed = declared_bed_z(contract)
    problems: list[str] = []
    for feature in contract.features:
        expectation = feature.expectation if isinstance(feature.expectation, dict) else {}
        if "model_to_printer_matrix" not in expectation:
            continue
        where = f"feature {feature.feature_id!r}"
        rule = as_transform(expectation["model_to_printer_matrix"])
        if rule is None:
            problems.append(
                f"{where}: model_to_printer_matrix is not a usable rigid "
                "transform, so the frame its ceiling was measured in is unknown")
        elif declared is not None and not np.array_equal(rule, declared):
            problems.append(
                f"{where}: the print plan rule declares a different print "
                "orientation from orientation.model_to_printer_matrix. The "
                "candidate is measured in the contract's frame and this row's "
                "ceiling was measured in the rule's, so the two sides of one "
                "inequality would be two frames. Neither is chosen here.")
        rule_bed = expectation.get("bed_z_mm")
        if isinstance(rule_bed, bool) or not isinstance(rule_bed, (int, float)):
            continue
        if bed is not None and float(rule_bed) != bed:
            problems.append(
                f"{where}: the print plan rule's bed_z_mm is {float(rule_bed)!r} "
                f"and orientation.bed_z_mm is {bed!r}. Bed contact is what "
                "separates a supported face from an overhang, so two bed "
                "heights are two different measurements.")
    return problems

