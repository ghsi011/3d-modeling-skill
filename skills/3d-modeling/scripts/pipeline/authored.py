#!/usr/bin/env python3
"""The `CUSTOM` lane's source API: a model module the pipeline can commission.

A certified template declares its geometry, its validity domain and its
expectations separately, and `DIRECT` is gated on all three. An authored model
cannot have a certified domain -- nobody has certified it -- but it can and must
have the other two, because the property that makes commissioning worth anything
is that the expectation was not derived from the geometry.

So a model module declares:

    PARAMS      = {...}                 # the numbers the shape is built from
    BBOX_MM     = {"x": .., "y": .., "z": ..}
    BODIES      = 1
    EXPECTED    = [ {feature rows} ]    # what the solid must measure
    def build(): ...                    # or a module-level `part`

and optionally `COMPONENTS`, `INTERFACES` and `PROVENANCE`.

`BBOX_MM` and `EXPECTED` are declarations, not measurements. Writing them by
running the build and copying what came out is the failure this whole
arrangement exists to prevent -- a threshold authored by the party being
measured, after measuring, is a receipt rather than a gate. Derive them from
`PARAMS` by arithmetic that does not go through the builder.

What is deliberately *not* here: a validity domain. An authored model is not
certified and never routes `DIRECT`, so there is no bound to check a parameter
against and pretending otherwise would sell an assurance nobody produced.
"""
from __future__ import annotations

import dataclasses
import importlib.util
import sys
from pathlib import Path
from typing import Any

from . import schemas as S

# Every declaration a model must carry before anything is built from it.
REQUIRED = ("PARAMS", "BBOX_MM", "EXPECTED")

AUTHORED_VERSION = "authored"


class ModelError(S.SchemaError):
    """The model module does not declare what the pipeline has to be given."""


@dataclasses.dataclass(frozen=True)
class AuthoredModel:
    """A loaded model module, reduced to what the contract needs.

    Shaped so that `runner._contract_from` can take it wherever it takes a
    `CertifiedTemplate`: same attribute names, same call signatures. That is the
    whole reason the `CUSTOM` lane costs a backend and not a second runner --
    contract, preflight, commissioning, screening, witnesses and status are
    reached unchanged, and there is one definition of each.
    """

    name: str
    module_path: Path
    module_sha256: str
    params: dict[str, Any]
    expected: tuple[dict[str, Any], ...]
    bbox_mm: dict[str, float]
    bodies: int
    components: tuple[dict[str, Any], ...]
    interfaces: tuple[dict[str, Any], ...]
    provenance: dict[str, Any]
    # What broad screening needs in order to tell a rib from a defect: where this
    # shape legitimately steps along Z, and what it should displace. Optional,
    # and their absence is reported as an uncalibrated screen rather than
    # silently treated as a clean one.
    profile_marks: dict[str, list[float]] = dataclasses.field(default_factory=dict)
    volume_mm3: float | None = None

    # -- the CertifiedTemplate surface --------------------------------------
    version: str = AUTHORED_VERSION
    domain_id: str | None = None
    backend: str = "authored"
    covers: str = "geometry authored for this job"

    def expectations(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        return [dict(row) for row in self.expected]

    def bbox(self, params: dict[str, Any]) -> dict[str, float]:
        return dict(self.bbox_mm)

    def as_source(self) -> dict[str, Any]:
        return {"kind": "authored", "module": self.module_path.name,
                "module_sha256": self.module_sha256,
                "provenance": dict(self.provenance),
                "profile_marks": {"z": list(self.profile_marks.get("z", ()))},
                "volume_mm3": self.volume_mm3}


def _finite(value: Any, what: str) -> float:
    """A finite number, or a `ModelError` naming the declaration.

    Re-raised rather than passed through: `require_finite_number` raises the
    generic schema error, and a caller catching `ModelError` to report "this
    model cannot be commissioned" would let a NaN escape as something else.
    """
    try:
        return S.require_finite_number(value, what=what)
    except S.SchemaError as exc:
        raise ModelError(str(exc)) from None


def _numbers(value: Any, what: str) -> dict[str, float]:
    if not isinstance(value, dict):
        raise ModelError(f"{what} must be an object of finite numbers")
    return {str(key): _finite(item, f"{what}.{key}") for key, item in value.items()}


def load(module_path: Path, *, known_kinds: frozenset[str] | None = None) -> tuple[AuthoredModel, Any]:
    """Import a model module and return its declarations and its builder.

    Returns the declarations *and* the buildable object separately, so the
    contract can be written and preflighted before any geometry is paid for --
    the same ordering the certified lane uses, and for the same reason: an
    incomplete contract should cost nothing to discover.
    """
    module_path = Path(module_path)
    if not module_path.is_file():
        raise ModelError(f"no such model module: {module_path}")

    spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
    if spec is None or spec.loader is None:
        raise ModelError(f"cannot import {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:                          # noqa: BLE001 - a model that
        raise ModelError(                             # cannot import is a finding
            f"{module_path.name} raised on import: {type(exc).__name__}: {exc}") from exc

    missing = [name for name in REQUIRED if not hasattr(module, name)]
    if missing:
        raise ModelError(
            f"{module_path.name} does not declare {', '.join(missing)}. A model the "
            "pipeline can commission declares PARAMS, BBOX_MM and EXPECTED, and "
            "derives the last two from the first without going through the builder.")

    builder = getattr(module, "part", None)
    if builder is None:
        builder = getattr(module, "build", None)
    if builder is None:
        raise ModelError(f"{module_path.name} must define `part` or `build()`")

    params = getattr(module, "PARAMS")
    if not isinstance(params, dict):
        raise ModelError(f"{module_path.name}: PARAMS must be an object")
    for key, value in params.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            _finite(value, f"PARAMS.{key}")

    bbox = _numbers(getattr(module, "BBOX_MM"), "BBOX_MM")
    if sorted(bbox) != ["x", "y", "z"] or any(v <= 0 for v in bbox.values()):
        raise ModelError("BBOX_MM must be positive in x, y and z")

    expected = getattr(module, "EXPECTED")
    if not isinstance(expected, (list, tuple)) or not expected:
        raise ModelError(
            f"{module_path.name}: EXPECTED must be a non-empty list. A contract that "
            "requires nothing of the solid cannot fail, and a gate that cannot fail "
            "is not one.")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(expected):
        if not isinstance(row, dict):
            raise ModelError(f"EXPECTED[{index}] must be an object")
        feature_id = row.get("feature_id")
        kind = row.get("kind")
        if not isinstance(feature_id, str) or not feature_id.strip():
            raise ModelError(f"EXPECTED[{index}] must carry a non-empty feature_id")
        if feature_id in seen:
            raise ModelError(f"EXPECTED: duplicate feature_id {feature_id!r} -- "
                             "receipts could not name which one")
        seen.add(feature_id)
        if not isinstance(kind, str) or (known_kinds is not None
                                         and kind not in known_kinds):
            raise ModelError(
                f"EXPECTED[{index}] kind {kind!r} names no check this build "
                f"implements. Known: {sorted(known_kinds or ())}")
        rows.append(dict(row))

    bodies = getattr(module, "BODIES", 1)
    if isinstance(bodies, bool) or not isinstance(bodies, int) or bodies < 1:
        raise ModelError("BODIES must be a whole number of at least 1")

    marks = getattr(module, "PROFILE_MARKS", {}) or {}
    if not isinstance(marks, dict):
        raise ModelError("PROFILE_MARKS must be an object like {'z': [6.0]}")
    profile_marks = {"z": [_finite(v, "PROFILE_MARKS.z")
                           for v in (marks.get("z") or ())]}

    volume = getattr(module, "VOLUME_MM3", None)
    if volume is not None:
        volume = _finite(volume, "VOLUME_MM3")
        if volume <= 0:
            raise ModelError("VOLUME_MM3 must be positive")

    return AuthoredModel(
        name=module_path.stem,
        module_path=module_path,
        module_sha256=S.sha256_file(module_path),
        params=dict(params), expected=tuple(rows), bbox_mm=bbox, bodies=bodies,
        components=tuple(getattr(module, "COMPONENTS", ()) or ()),
        interfaces=tuple(getattr(module, "INTERFACES", ()) or ()),
        provenance=dict(getattr(module, "PROVENANCE", {}) or {}),
        profile_marks=profile_marks, volume_mm3=volume,
    ), builder
