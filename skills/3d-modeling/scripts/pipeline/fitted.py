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
from typing import Any, Callable

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
            raise ValueError(
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


def validate(response: dict[str, Any]) -> tuple[list[Measurement], list[Interface], list[str]]:
    """Turn the response into data, refusing anything that is not measurable."""
    measurements: list[Measurement] = []
    for row in response.get("measurements", []):
        confidence = S.require_enum(row.get("confidence"), ("A", "B", "C", "D"),
                                    what=f"measurement {row.get('feature')!r} confidence")
        nominal = float(row["nominal_mm"])
        uncertainty = float(row.get("uncertainty_mm", 0.0))
        if uncertainty < 0:
            raise S.SchemaError(f"{row['feature']}: uncertainty cannot be negative")
        if nominal <= 0:
            raise S.SchemaError(f"{row['feature']}: a dimension must be positive")
        measurements.append(Measurement(
            feature=str(row["feature"]), nominal_mm=nominal, uncertainty_mm=uncertainty,
            method=str(row.get("method", "")), datum=str(row.get("datum", "")),
            confidence=confidence))

    known = {m.feature for m in measurements}
    interfaces: list[Interface] = []
    for row in response.get("interfaces", []):
        feature = str(row["measurement"])
        if feature not in known:
            raise S.SchemaError(
                f"interface {row.get('interface_id')!r} fits {feature!r}, which no "
                "measurement reports. An interface to a dimension nobody measured is "
                "a fit nobody can check.")
        interface = Interface(interface_id=str(row["interface_id"]), measurement=feature,
                              fit_class=str(row["fit_class"]))
        interface.clearance()      # refuse an unknown class now, not at build time
        interfaces.append(interface)

    return measurements, interfaces, [str(u) for u in response.get("unresolved", [])]


def parameters_from(measurements: list[Measurement], interfaces: list[Interface],
                    mapping: dict[str, str]) -> dict[str, float]:
    """Template parameters, derived from the measurements and the pipeline's bands.

    `mapping` says which template parameter each interface drives. The arithmetic
    is here rather than in the model's answer, so the parameter is a function of
    a measurement anyone can re-check against the object.
    """
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
    return {
        "schema_version": S.INTENT_SCHEMA,
        "route": "FITTED",
        "reviewer": reviewer,
        "measurements": [
            {**dataclasses.asdict(m), "band_mm": [round(v, 4) for v in m.band()]}
            for m in measurements],
        "interfaces": [
            {**dataclasses.asdict(i), "clearance_mm": list(i.clearance()),
             "clearance_owner": "pipeline"}
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
            reviewer: dict[str, Any]) -> dict[str, Any]:
    """One call, validated, with every deterministic consequence computed here."""
    request = build_request(brief=brief, evidence=evidence, template=template,
                            template_covers=template_covers, bounds=bounds)
    measurements, interfaces, unresolved = validate(call(request))
    return report(measurements=measurements, interfaces=interfaces,
                  unresolved=unresolved, reviewer=reviewer)
