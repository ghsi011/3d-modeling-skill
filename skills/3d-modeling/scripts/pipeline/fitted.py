#!/usr/bin/env python3
"""The `FITTED` route: one bounded call to recover what the job does not own.

`FITTED` exists for exactly one reason -- acceptance depends on geometry somebody
else owns. A phone's width is what it is; a cradle either fits it or does not,
and no template parameter can decide the question. So something has to read the
photographs and the calipers, and that something is a model.

**One call, not a conversation.** The measured cost of a dispatch is four to six
minutes whatever it contains, so the whole specification is recovered in a single
constrained structured call: every input in the initial context, strict output
schema, no shell, no file navigation, no rereading a file it just wrote. What
comes back is data, and every deterministic consequence of that data -- the
contract, the fit bands, the tolerances -- is computed here rather than asked for.

**What the model is not allowed to decide.** It reports measurements and their
uncertainty. It does not choose the fit strategy, set tolerances, or declare the
part acceptable: those are consequences of the measurement plus the printing
process, and deriving them deterministically is what keeps a confident wrong
reading from becoming a confident wrong part.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Callable

from . import review as R
from . import schemas as S

# Per-side clearance by fit class, in millimetres, for FDM at a 0.4 mm nozzle.
# These are the pipeline's, not the model's: a measurement that arrives with its
# own clearance already applied cannot be checked against the object it came
# from, and the number would then be unfalsifiable.
FIT_CLEARANCE = {
    "slip": (0.20, 0.40),        # slides freely, no retention
    "locating": (0.10, 0.20),    # positions without force
    "snug": (0.05, 0.10),        # hand pressure to seat
    "press": (-0.10, -0.05),     # interference; assembly deforms the print
}

# What a caliper on a printed part is actually good for. Applied on top of the
# reading's own spread, because an operator who repeats a measurement three times
# has bounded repeatability and not accuracy.
INSTRUMENT_UNCERTAINTY_MM = 0.05
# A margin smaller than this is below the credibility of the print and
# measurement process.  Treat it as ungateable rather than reporting a rounded
# zero that looks like a successful acceptance decision.
MIN_ACCEPTANCE_MARGIN_MM = 0.01


@dataclasses.dataclass(frozen=True)
class Measurement:
    """One externally owned dimension, and how well it is known."""

    feature: str
    nominal_mm: float
    uncertainty_mm: float
    method: str
    datum: str
    confidence: str          # A measured, B corroborated, C image-derived, D assumed

    def band(self) -> tuple[float, float]:
        total = self.uncertainty_mm + INSTRUMENT_UNCERTAINTY_MM
        return (self.nominal_mm - total, self.nominal_mm + total)


@dataclasses.dataclass(frozen=True)
class Interface:
    """Where the printed part meets the thing it does not own."""

    interface_id: str
    measurement: str         # the Measurement.feature it fits
    fit_class: str
    owner: str = "external"

    def clearance(self) -> tuple[float, float]:
        try:
            return FIT_CLEARANCE[self.fit_class]
        except KeyError:
            raise S.SchemaError(
                f"{self.interface_id}: fit class {self.fit_class!r} is not one of "
                f"{sorted(FIT_CLEARANCE)}. The pipeline owns the clearance, so an "
                "unknown class has no band to apply.") from None


SPEC_SCHEMA = {
    "measurements": [{
        "feature": "str", "nominal_mm": "float", "uncertainty_mm": "float",
        "method": "str -- caliper, photo scale, published spec, ...",
        "datum": "str -- which face or axis it was taken from",
        "confidence": "A | B | C | D",
    }],
    "interfaces": [{
        "interface_id": "str", "measurement": "str -- a feature named above",
        "fit_class": " | ".join(sorted(FIT_CLEARANCE)),
    }],
    "unresolved": ["str -- what could not be recovered, and why"],
    "review_envelope": "dict -- exact envelope digest required when review is bound",
}


def build_request(*, brief: str, evidence: list[str], template: str,
                  template_covers: str, bounds: dict[str, Any]) -> dict[str, Any]:
    """Everything the call needs, in the initial context.

    A dispatch that has to go and find its own inputs spends its budget on
    navigation. Reading a file it just wrote is worse: it costs a round trip to
    learn something it already knew.
    """
    return {
        "task": ("Recover the externally owned dimensions this part must fit, and "
                 "nothing else. Do not choose tolerances, clearances or a fit "
                 "strategy -- report what you measured and how well you know it."),
        "brief": brief,
        "evidence": list(evidence),
        "template": {"name": template, "covers": template_covers,
                     "parameters": {k: dataclasses.asdict(v) if dataclasses.is_dataclass(v)
                                    else {"low": v.low, "high": v.high, "unit": v.unit,
                                          "basis": v.basis}
                                    for k, v in bounds.items()}},
        "rules": [
            "Report a measurement only where you actually have evidence for it.",
            "An envelope dimension on a rounded part is not at a flat face: the "
            "widest section sits part-way through the thickness, so take it at two "
            "or more heights and record the largest.",
            "Uncertainty is the spread you would expect on a repeat, not a guess "
            "at how wrong you might be.",
            "Say what you could not recover. An unresolved dimension escalates the "
            "job; a fabricated one ships a part that does not fit.",
        ],
        "response_schema": SPEC_SCHEMA,
    }


def validate(response: dict[str, Any], *,
             envelope: "R.ReviewEnvelope | None" = None) -> tuple[list[Measurement], list[Interface], list[str]]:
    """Turn the response into data, refusing anything that is not measurable."""
    if not isinstance(response, dict):
        raise S.SchemaError("specification response must be a dict")
    required = {"measurements", "interfaces", "unresolved"}
    missing = required - set(response.keys())
    if missing:
        raise S.SchemaError(f"specification response missing required fields: {sorted(missing)}")
    if envelope is not None and "review_envelope" not in response:
        raise S.SchemaError("specification response: review_envelope is required when bound")

    if not isinstance(response["measurements"], list):
        raise S.SchemaError("specification response: measurements must be a list")
    if not isinstance(response["interfaces"], list):
        raise S.SchemaError("specification response: interfaces must be a list")
    if not isinstance(response["unresolved"], list):
        raise S.SchemaError("specification response: unresolved must be a list")

    measurements: list[Measurement] = []
    seen_features: set[str] = set()
    for row in response["measurements"]:
        if not isinstance(row, dict):
            raise S.SchemaError("specification response: each measurement must be a dict")
        for field in ("feature", "nominal_mm", "uncertainty_mm", "method", "datum", "confidence"):
            if field not in row:
                raise S.SchemaError(f"measurement {row.get('feature')!r}: missing {field}")
        if not isinstance(row["feature"], str):
            raise S.SchemaError(f"measurement {row['feature']!r}: feature must be a string")
        if row["feature"] in seen_features:
            raise S.SchemaError(f"measurement {row['feature']!r}: duplicate feature")
        seen_features.add(row["feature"])
        if not isinstance(row["confidence"], str):
            raise S.SchemaError(
                f"measurement {row['feature']!r}: confidence must be a string")
        confidence = S.require_enum(row["confidence"], ("A", "B", "C", "D"),
                                    what=f"measurement {row['feature']!r} confidence")
        # Strict finite numbers: a bool, a numeric-looking string, or a
        # NaN/Infinity smuggled through `json` would each survive a bare
        # `float(...)` and size a nonsense parameter. This route reads
        # model-produced numbers, so it is exactly where that has to be refused.
        nominal = S.require_finite_number(row["nominal_mm"],
                                          what=f"{row['feature']}: nominal_mm")
        uncertainty = S.require_finite_number(row["uncertainty_mm"],
                                              what=f"{row['feature']}: uncertainty_mm")
        if uncertainty < 0:
            raise S.SchemaError(f"{row['feature']}: uncertainty cannot be negative")
        if nominal <= 0:
            raise S.SchemaError(f"{row['feature']}: a dimension must be positive")
        for field in ("method", "datum"):
            if not isinstance(row[field], str):
                raise S.SchemaError(f"{row['feature']}: {field} must be a string")
        measurements.append(Measurement(
            feature=str(row["feature"]), nominal_mm=nominal, uncertainty_mm=uncertainty,
            method=str(row["method"]), datum=str(row["datum"]),
            confidence=confidence))

    known = {m.feature for m in measurements}
    interfaces: list[Interface] = []
    seen_interfaces: set[str] = set()
    for row in response["interfaces"]:
        if not isinstance(row, dict):
            raise S.SchemaError("specification response: each interface must be a dict")
        for field in ("interface_id", "measurement", "fit_class"):
            if field not in row:
                raise S.SchemaError(f"interface: missing {field}")
        if (not isinstance(row["interface_id"], str)
                or not row["interface_id"].strip()):
            raise S.SchemaError("interface: interface_id must be a non-empty string")
        if not isinstance(row["measurement"], str):
            raise S.SchemaError(
                f"interface {row['interface_id']!r}: measurement must be a string")
        feature = row["measurement"]
        if feature not in known:
            raise S.SchemaError(
                f"interface {row['interface_id']!r} fits {feature!r}, which no "
                "measurement reports. An interface to a dimension nobody measured is "
                "a fit nobody can check.")
        if row["interface_id"] in seen_interfaces:
            raise S.SchemaError(f"interface {row['interface_id']!r}: duplicate interface_id")
        seen_interfaces.add(row["interface_id"])
        if not isinstance(row["fit_class"], str):
            raise S.SchemaError(
                f"interface {row['interface_id']!r}: fit_class must be a string")
        interface = Interface(interface_id=row["interface_id"], measurement=feature,
                              fit_class=row["fit_class"])
        interface.clearance()      # refuse an unknown class now, not at build time
        interfaces.append(interface)

    unresolved = response["unresolved"]
    if not all(isinstance(u, str) for u in unresolved):
        raise S.SchemaError("specification response: unresolved must be a list of strings")

    return measurements, interfaces, [str(u) for u in unresolved]


def acceptance_tolerance(measurement: Measurement, interface: Interface) -> float:
    """The print tolerance left once the measurement's uncertainty is spent.

    A per-side clearance applies to both sides, so the controlled printed
    dimension has a full fit window of `2 * (high - low)`.  The acceptance
    tolerance is the *half* window: `high - low`.  The measured nominal is only
    known to +/- its total uncertainty (the reading's own spread plus the
    instrument's), and that uncertainty consumes the same amount from the
    half-window.  Returning the full window here doubled the credible print
    margin and let a candidate pass outside the uncertainty-aware band.

    If the remaining half-window is tiny or non-positive, the measurement
    cannot decide the fit at the resolution of this process.  A part whose fit
    is a guess is exactly what the FITTED route exists to prevent.
    """
    low, high = interface.clearance()
    half_window = high - low
    total_uncertainty = measurement.uncertainty_mm + INSTRUMENT_UNCERTAINTY_MM
    remaining = half_window - total_uncertainty
    if remaining < MIN_ACCEPTANCE_MARGIN_MM:
        raise S.SchemaError(
            f"{interface.interface_id}: the measurement of {measurement.feature!r} is "
            f"uncertain to +/-{total_uncertainty:.3f} mm, which consumes the entire "
            f"{half_window:.3f} mm half-window of the {interface.fit_class} fit band, "
            f"leaving {remaining:.4f} mm, below the {MIN_ACCEPTANCE_MARGIN_MM:.3f} mm "
            "minimum credible margin. No print tolerance is left, "
            "so whether the part fits cannot be decided from this measurement.")
    return round(remaining, 4)


def fit_acceptance(measurements: list[Measurement],
                   interfaces: list[Interface]) -> dict[str, dict[str, float]]:
    """Per interface, the uncertainty that went in and the tolerance that came out.

    Raises `SchemaError` for any interface whose measurement uncertainty consumes
    its fit band, so the job stops here rather than sizing a part nobody can say
    fits.
    """
    by_feature = {m.feature: m for m in measurements}
    acceptance: dict[str, dict[str, float]] = {}
    for interface in interfaces:
        measurement = by_feature[interface.measurement]
        total_uncertainty = measurement.uncertainty_mm + INSTRUMENT_UNCERTAINTY_MM
        acceptance[interface.interface_id] = {
            "uncertainty_mm": round(total_uncertainty, 4),
            "acceptance_tolerance_mm": acceptance_tolerance(measurement, interface),
        }
    return acceptance


def acceptance_contract(
    measurements: list[Measurement], interfaces: list[Interface],
    mapping: dict[str, str],
) -> tuple[dict[str, Any], ...]:
    """Return the immutable fit-gate rows carried into the model contract.

    The rows deliberately retain the external measurement, pipeline-owned
    clearance band, propagated uncertainty, mapped parameter, and the remaining
    half-window.  ``commission`` uses the row to bind the fit gate to the
    candidate feature checks; it must not reconstruct a tolerance from a
    stripped interface dataclass or from a designer-supplied value.
    """
    acceptance = fit_acceptance(measurements, interfaces)
    by_feature = {m.feature: m for m in measurements}
    rows: list[dict[str, Any]] = []
    for interface in interfaces:
        measurement = by_feature[interface.measurement]
        low, high = interface.clearance()
        details = acceptance[interface.interface_id]
        rows.append({
            "interface_id": interface.interface_id,
            "measurement_feature": measurement.feature,
            "parameter": mapping.get(interface.interface_id),
            "nominal_mm": measurement.nominal_mm,
            "clearance_mm": [low, high],
            "target_mm": round(measurement.nominal_mm + low + high, 4),
            "uncertainty_mm": details["uncertainty_mm"],
            "acceptance_tolerance_mm": details["acceptance_tolerance_mm"],
        })
    return tuple(rows)


def parameters_from(measurements: list[Measurement], interfaces: list[Interface],
                    mapping: dict[str, str]) -> dict[str, float]:
    """Template parameters, derived from the measurements and the pipeline's bands.

    `mapping` says which template parameter each interface drives. The arithmetic
    is here rather than in the model's answer, so the parameter is a function of
    a measurement anyone can re-check against the object.
    """
    # This is the sizing gate as well as a report calculation. Callers that
    # derive parameters directly must not bypass the uncertainty decision by
    # skipping report().
    fit_acceptance(measurements, interfaces)
    by_feature = {m.feature: m for m in measurements}
    params: dict[str, float] = {}
    for interface in interfaces:
        parameter = mapping.get(interface.interface_id)
        if parameter is None:
            continue
        measurement = by_feature[interface.measurement]
        low, high = interface.clearance()
        # Size to the middle of the clearance band, off the measurement's nominal.
        params[parameter] = round(measurement.nominal_mm + (low + high), 4)
    return params


def report(*, measurements: list[Measurement], interfaces: list[Interface],
           unresolved: list[str], reviewer: dict[str, Any]) -> dict[str, Any]:
    # Raises if any interface's measurement uncertainty consumes its fit band;
    # otherwise the propagated acceptance tolerance rides on each interface, so a
    # reader sees the margin the print actually has rather than the clearance
    # band as if the measurement were exact.
    acceptance = fit_acceptance(measurements, interfaces)
    return {
        "schema_version": S.SPECIFICATION_SCHEMA,
        "route": "FITTED",
        "reviewer": reviewer,
        "measurements": [
            {**dataclasses.asdict(m), "band_mm": [round(v, 4) for v in m.band()]}
            for m in measurements],
        "interfaces": [
            {**dataclasses.asdict(i), "clearance_mm": list(i.clearance()),
             "clearance_owner": "pipeline",
             "uncertainty_mm": acceptance[i.interface_id]["uncertainty_mm"],
             "acceptance_tolerance_mm": acceptance[i.interface_id]["acceptance_tolerance_mm"]}
            for i in interfaces],
        "unresolved": list(unresolved),
        "instrument_uncertainty_mm": INSTRUMENT_UNCERTAINTY_MM,
        "note": ("Clearances and tolerances are the pipeline's, applied to the "
                 "measurements above. A specification that arrived with its own "
                 "clearance already folded in could not be checked against the "
                 "object it came from."),
    }


def recover(*, brief: str, evidence: list[str], template: str, template_covers: str,
            bounds: dict[str, Any], call: Callable[[dict[str, Any]], dict[str, Any]],
            reviewer: dict[str, Any], job_id: str, revision: str,
            contract_hash: str, evidence_dir: Path | None = None,
            artifact_hashes: dict[str, str | None] | None = None,
            execution_plan_sha256: str | None = None,
            alternative_id: str | None = None) -> dict[str, Any]:
    """One call, validated, with every deterministic consequence computed here."""
    from . import review as R

    request = build_request(brief=brief, evidence=evidence, template=template,
                            template_covers=template_covers, bounds=bounds)
    packet_hash = S.payload_hash(request)
    envelope = R.build_envelope(
        kind="specification", job_id=job_id, revision=revision,
        packet_hash=packet_hash, reviewer=reviewer, contract_hash=contract_hash,
        artifact_hashes=artifact_hashes, evidence=evidence, evidence_dir=evidence_dir,
        # Bound here as at the other two review boundaries. This review is only
        # asked because the plan routed FITTED, so the plan is one of the things
        # the question is a function of; leaving it out here would be the same
        # gap in miniature. Same argument for the alternative: this recovery is a
        # question about one formulation of the job, and two formulations of one
        # template can share every other field here.
        execution_plan_sha256=execution_plan_sha256,
        alternative_id=alternative_id)
    request["review_envelope"] = envelope.as_dict()
    response = call(request)
    # Validate the payload shape and types first. A malformed but correctly bound
    # response must become a controlled SchemaError, not a TypeError from a set
    # operation or a hash that runs before the schema check.
    measurements, interfaces, unresolved = validate(response, envelope=envelope)
    R.validate_response_envelope(response, envelope)
    R.require_specification_pass_closed(response)
    result = report(measurements=measurements, interfaces=interfaces,
                    unresolved=unresolved, reviewer=reviewer)
    result["review_envelope"] = envelope.as_dict()
    return result
