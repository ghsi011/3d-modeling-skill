#!/usr/bin/env python3
"""Certified templates: geometry, a validity domain, and expectations.

A template is certified when it declares a closed parameter domain, the
cross-parameter relations its geometry actually requires, and generators for the
contract expectations. `DIRECT` is gated on all three; an uncertified template is
usable, but only on a route where somebody is looking.

**The expectation generators live in `expectations.py`, not here.** That
separation is the point of the whole arrangement: geometry and expectation must
not be able to fail together. A shared helper for a critical dimension recreates
exactly the common-mode failure the split exists to prevent -- one parameter
drives both, a bug moves both, and the two agree while the part is wrong.
"""
from __future__ import annotations

import dataclasses
from typing import Any, Callable


@dataclasses.dataclass(frozen=True)
class Bound:
    """A closed range, with the reason it stops where it does.

    The basis is not decoration. A bare number invites widening under pressure;
    "four perimeters at a 0.4 mm nozzle" tells the next person what they would be
    giving up, and that is the difference between a limit and a suggestion.
    """

    low: float
    high: float
    unit: str
    basis: str

    def contains(self, value: float) -> bool:
        return self.low <= float(value) <= self.high


@dataclasses.dataclass(frozen=True)
class Constraint:
    """A relation over parameters that the geometry requires to be true."""

    expression: str
    test: Callable[[dict[str, Any]], bool]
    why: str


@dataclasses.dataclass(frozen=True)
class CertifiedTemplate:
    name: str
    version: str
    domain_id: str
    backend: str
    covers: str
    bounds: dict[str, Bound]
    constraints: tuple[Constraint, ...]
    build: Callable[[dict[str, Any]], Any]
    expectations: Callable[[dict[str, Any]], list[dict[str, Any]]]
    bbox: Callable[[dict[str, Any]], dict[str, float]]
    # Where this template's own geometry legitimately steps, per axis, from the
    # parameters. Template-authored because only the template knows that a
    # c_clip's area jumps at the top of its flange; the screening detector would
    # otherwise have to guess, and guessing is how a broad screen becomes either
    # toothless or a nuisance.
    profile_marks: Callable[[dict[str, Any]], dict[str, list[float]]] = lambda p: {"z": []}
    bodies: int = 1
    step_capable: bool = False

    def rejects(self, params: dict[str, Any]) -> list[str]:
        """Why these parameters are outside the certified domain, if they are."""
        reasons: list[str] = []
        for name, bound in self.bounds.items():
            if name not in params:
                reasons.append(f"{name} is required by {self.name} and was not given")
                continue
            try:
                value = float(params[name])
            except (TypeError, ValueError):
                reasons.append(f"{name}={params[name]!r} is not a number")
                continue
            if not bound.contains(value):
                reasons.append(
                    f"{name}={value:g} {bound.unit} is outside the certified range "
                    f"[{bound.low:g}, {bound.high:g}] ({bound.basis})")
        if reasons:
            return reasons
        for constraint in self.constraints:
            try:
                ok = constraint.test(params)
            except Exception:               # noqa: BLE001 - a relation that cannot be
                ok = False                  # evaluated has not been satisfied
            if not ok:
                reasons.append(f"constraint {constraint.expression} is violated: {constraint.why}")
        return reasons


# ---------------------------------------------------------------------------
# The certified set
# ---------------------------------------------------------------------------

def _clip_build(params: dict[str, Any]):
    from .backends.trimesh_manifold import build_c_clip
    return build_c_clip(params)


def _ring_build(params: dict[str, Any]):
    from .backends.build123d_backend import build_trim_ring
    return build_trim_ring(params)


def _registry() -> dict[str, CertifiedTemplate]:
    from . import expectations as X

    c_clip = CertifiedTemplate(
        name="c_clip", version="1.0.0", domain_id="c_clip@1.0.0/d1",
        backend="trimesh-manifold",
        covers="a C-channel that snaps over a round bundle, on a mounting flange",
        bounds={
            "bore_d": Bound(4.0, 40.0, "mm",
                            "below 4 the boolean degenerates; above 40 the flange leaves the bed"),
            "wall": Bound(2.0, 8.0, "mm", "four perimeters at a 0.4 mm nozzle"),
            "height": Bound(4.0, 40.0, "mm", "shorter does not retain; taller buckles in PLA"),
            "mouth_gap": Bound(2.0, 40.0, "mm", "narrower than 2 will not admit a bundle"),
            "flange_t": Bound(2.0, 10.0, "mm", "screw head bearing"),
            "screw_d": Bound(2.0, 8.0, "mm", "common wood-screw shanks"),
        },
        constraints=(
            Constraint("mouth_gap < bore_d",
                       lambda p: float(p["mouth_gap"]) < float(p["bore_d"]),
                       "a mouth at or wider than the bore retains nothing"),
            Constraint("wall <= bore_d / 2",
                       lambda p: float(p["wall"]) <= float(p["bore_d"]) / 2.0,
                       "a wall thicker than the radius leaves no channel"),
            Constraint("screw_d < flange_w / 3",
                       lambda p: float(p["screw_d"]) < float(p["flange_w"]) / 3.0,
                       "the screw would break out of the flange"),
        ),
        build=_clip_build, expectations=X.c_clip_expectations, bbox=X.c_clip_bbox,
        profile_marks=X.c_clip_profile_marks,
    )

    trim_ring = CertifiedTemplate(
        name="trim_ring", version="1.0.0", domain_id="trim_ring@1.0.0/d1",
        backend="build123d",
        covers="a chamfered trim ring that drops into a round hole in a panel",
        bounds={
            "hole_d": Bound(10.0, 200.0, "mm", "smaller is a grommet; larger leaves the bed"),
            "lip_w": Bound(2.0, 25.0, "mm", "narrower than 2 chips off the chamfer"),
            "panel_t": Bound(3.0, 60.0, "mm", "panel thicknesses this reaches through"),
            "wall": Bound(1.2, 8.0, "mm", "three perimeters at a 0.4 mm nozzle"),
            "chamfer": Bound(0.4, 4.0, "mm", "below 0.4 the kernel drops the feature"),
        },
        constraints=(
            Constraint("chamfer < lip_w / 2",
                       lambda p: float(p["chamfer"]) < float(p["lip_w"]) / 2.0,
                       "the chamfer would consume the whole lip"),
            Constraint("wall < hole_d / 4",
                       lambda p: float(p["wall"]) < float(p["hole_d"]) / 4.0,
                       "the skirt would close the hole it lines"),
        ),
        build=_ring_build, expectations=X.trim_ring_expectations, bbox=X.trim_ring_bbox,
        profile_marks=X.trim_ring_profile_marks, step_capable=True,
    )
    return {t.name: t for t in (c_clip, trim_ring)}


_CACHE: dict[str, CertifiedTemplate] | None = None


def registry() -> dict[str, CertifiedTemplate]:
    global _CACHE
    if _CACHE is None:
        _CACHE = _registry()
    return _CACHE


def get(name: str) -> CertifiedTemplate:
    try:
        return registry()[name]
    except KeyError:
        raise KeyError(f"no certified template named {name!r}; "
                       f"have {sorted(registry())}") from None
