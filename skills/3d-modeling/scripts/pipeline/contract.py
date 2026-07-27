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
from typing import Any

from . import schemas as S


class ContractError(ValueError):
    """The contract cannot be used as written."""


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
    modifiers: tuple[str, ...]
    minimum_coverage: float
    step_required: bool
    consequence: str
    updated_utc: str

    def as_payload(self) -> dict[str, Any]:
        return {
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
            "modifiers": list(self.modifiers),
            "minimum_coverage": self.minimum_coverage,
            "step_required": self.step_required,
            "consequence": self.consequence,
            "updated_utc": self.updated_utc,
        }

    def contract_hash(self) -> str:
        return S.payload_hash(self.as_payload())


# --------------------------------------------------------------------------
# Preflight
# --------------------------------------------------------------------------

_REQUIRED_FIELDS = ("provenance", "expectation", "tolerance", "verified_by", "on_unrunnable")


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

    if not contract.expected_bbox_mm:
        problems.append("no expected_bbox_mm: nothing would check the part's own size, "
                        "and a candidate once shipped 31% too thick that way")
    if contract.bbox_tolerance_mm <= 0:
        problems.append("bbox_tolerance_mm must be positive")
    if contract.expected_bodies < 1:
        problems.append("expected_bodies must be at least 1")
    if not 0.0 < contract.minimum_coverage <= 1.0:
        problems.append("minimum_coverage must be in (0, 1]")
    S.require_enum(contract.consequence, S.CONSEQUENCE, what="contract.consequence")
    S.require_enum(contract.backend, S.BACKEND, what="contract.backend")
    return problems

