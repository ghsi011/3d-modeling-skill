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
    # Expected solid volume from the parameters. The one screen that does not
    # need to know where a defect is.
    volume: Callable[[dict[str, Any]], float] | None = None
    bodies: int = 1

    def rejects(self, params: dict[str, Any]) -> list[str]:
        """Why these parameters are outside the certified domain, if they are.

        Iterating the *parameters*, not the bounds. Iterating the bounds meant a
        parameter nobody had bounded was never checked: a c_clip with a
        900 x 400 mm flange routed DIRECT and commissioned, while `bore_d`'s own
        basis says "above 40 the flange leaves the bed". A domain with a hole in
        it certifies nothing, so an unbounded parameter is a certification defect
        rather than a permissive default.
        """
        reasons: list[str] = []
        for name in sorted(params):
            if name not in self.bounds:
                reasons.append(
                    f"{name} has no certified range in {self.domain_id}; a domain that "
                    "does not bound every parameter cannot say a job is inside it")
        if reasons:
            return reasons
        for name, bound in self.bounds.items():
            if name not in params:
                reasons.append(f"{name} is required by {self.name} and was not given")
                continue
            # A count is a number of discrete things -- vent columns, vent rows.
            # 3.5 of them is not a smaller grid, it is a nonsense one: the builder
            # rounds it with `int(...)` and then the geometry, the constraints and
            # the volume screen each see a different integer. The domain is the
            # one place that can refuse the fraction before any of them guesses.
            raw_value = params[name]
            if (bound.unit == "count"
                    and (isinstance(raw_value, bool)
                         or not isinstance(raw_value, (int, float)))):
                reasons.append(f"{name}={raw_value!r} is not a number")
                continue
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                reasons.append(f"{name}={raw_value!r} is not a number")
                continue
            if bound.unit == "count" and not value.is_integer():
                reasons.append(
                    f"{name}={raw_value!r} is a count and must be a whole number "
                    f"in [{bound.low:g}, {bound.high:g}]")
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


def _box_build(params: dict[str, Any]):
    from .backends.trimesh_manifold import build_box_shell
    return build_box_shell(params)


def _bracket_build(params: dict[str, Any]):
    from .backends.trimesh_manifold import build_l_bracket
    return build_l_bracket(params)


def _vented_build(params: dict[str, Any]):
    from .backends.trimesh_manifold import build_vented_enclosure
    return build_vented_enclosure(params)


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
            "flange_w": Bound(15.0, 200.0, "mm", "narrower will not take a screw beside "
                                                 "the channel; wider leaves a 256 mm bed"),
            "flange_d": Bound(10.0, 200.0, "mm", "same bed limit, across"),
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
            # The bbox expectation takes the flange as the bounding box. A ring
            # wider than its own flange makes that false, and the envelope check
            # then fails a correct part: bore_d 40 + 2x8 wall is a 56 mm ring on
            # a 20 mm flange, extents [56.0, 55.9, 15.0] against a declared
            # [40, 20, 15]. That was inside the certified domain, so a clean job
            # was flagged for being outside a box the contract derived wrong.
            Constraint("bore_d + 2 * wall <= min(flange_w, flange_d)",
                       lambda p: float(p["bore_d"]) + 2.0 * float(p["wall"])
                       <= min(float(p["flange_w"]), float(p["flange_d"])),
                       "the ring would stand proud of the flange, and the flange "
                       "is what the bounding box is derived from"),
            Constraint("screw_d < flange_d / 3",
                       lambda p: float(p["screw_d"]) < float(p["flange_d"]) / 3.0,
                       "the screw would break out across the flange's short side"),
        ),
        build=_clip_build, expectations=X.c_clip_expectations, bbox=X.c_clip_bbox,
        profile_marks=X.c_clip_profile_marks, volume=X.c_clip_volume,
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
            "lip_t": Bound(1.2, 20.0, "mm", "three layers at 0.2 mm minimum; thicker is "
                                            "a spacer, not a trim ring"),
        },
        constraints=(
            # A chamfer larger than the material it is cut into makes the kernel
            # raise `Failed creating a chamfer`, which reached the caller as a
            # build crash on parameters the domain said were fine.
            Constraint("chamfer < lip_t",
                       lambda p: float(p["chamfer"]) < float(p["lip_t"]),
                       "the chamfer would consume the whole lip"),
            Constraint("chamfer < wall",
                       lambda p: float(p["chamfer"]) < float(p["wall"]),
                       "the chamfer would cut through the wall it sits on"),
            Constraint("chamfer < lip_w / 2",
                       lambda p: float(p["chamfer"]) < float(p["lip_w"]) / 2.0,
                       "the chamfer would consume the whole lip"),
            Constraint("wall < hole_d / 4",
                       lambda p: float(p["wall"]) < float(p["hole_d"]) / 4.0,
                       "the skirt would close the hole it lines"),
        ),
        build=_ring_build, expectations=X.trim_ring_expectations, bbox=X.trim_ring_bbox,
        profile_marks=X.trim_ring_profile_marks, volume=X.trim_ring_volume,
    )
    box_shell = CertifiedTemplate(
        name="box_shell", version="1.0.0", domain_id="box_shell@1.0.0/d1",
        backend="trimesh-manifold",
        covers="a walled box with a floor and an open top: enclosure, tray, drawer, bin",
        bounds={
            "inner_w": Bound(10.0, 230.0, "mm", "usable width; above 230 the outside "
                                                "leaves a 256 mm bed"),
            "inner_d": Bound(10.0, 230.0, "mm", "same bed limit, across"),
            "inner_h": Bound(5.0, 240.0, "mm", "taller than 240 exceeds common Z travel"),
            "wall": Bound(1.2, 10.0, "mm", "three perimeters at a 0.4 mm nozzle"),
            "floor": Bound(1.2, 20.0, "mm", "three layers at 0.2 mm minimum"),
        },
        constraints=(
            Constraint("wall < inner_w / 4",
                       lambda p: float(p["wall"]) < float(p["inner_w"]) / 4.0,
                       "the walls would consume the cavity"),
            Constraint("wall < inner_d / 4",
                       lambda p: float(p["wall"]) < float(p["inner_d"]) / 4.0,
                       "the walls would consume the cavity across"),
        ),
        build=_box_build, expectations=X.box_shell_expectations, bbox=X.box_shell_bbox,
        profile_marks=X.box_shell_profile_marks, volume=X.box_shell_volume,
    )

    l_bracket = CertifiedTemplate(
        name="l_bracket", version="1.0.0", domain_id="l_bracket@1.0.0/d1",
        backend="trimesh-manifold",
        covers="two plates at a right angle with a fastener hole through each: "
               "shelf bracket, mount, corner brace",
        bounds={
            "width": Bound(12.0, 200.0, "mm", "narrower will not take a fastener; "
                                              "wider leaves the bed"),
            "leg_a": Bound(15.0, 200.0, "mm", "the upright"),
            "leg_b": Bound(15.0, 200.0, "mm", "the leg on the bed"),
            "thickness": Bound(2.0, 20.0, "mm", "five perimeters at 0.4 mm; thinner "
                                                "peels at the corner under load"),
            "hole_d": Bound(2.0, 12.0, "mm", "common fastener shanks"),
            "hole_inset": Bound(5.0, 60.0, "mm", "edge distance: closer than 5 mm and "
                                                 "the hole breaks out"),
        },
        constraints=(
            Constraint("hole_d < width / 3",
                       lambda p: float(p["hole_d"]) < float(p["width"]) / 3.0,
                       "the fastener would break out of the plate"),
            Constraint("hole_inset > hole_d",
                       lambda p: float(p["hole_inset"]) > float(p["hole_d"]),
                       "less than one diameter of edge distance tears out"),
            # Clears the hole's *edge* from the corner, not its centre. Clearing
            # only the centre let a hole overlap the upright (leaving 1.07 mm of
            # material against a 2.90 mm wall) and let another reach below the
            # bed -- both inside the certified domain, both flagged on a part
            # built exactly as asked.
            Constraint("hole_inset + hole_d / 2 < min(leg_a, leg_b) - thickness",
                       lambda p: float(p["hole_inset"]) + float(p["hole_d"]) / 2.0
                       < min(float(p["leg_a"]), float(p["leg_b"])) - float(p["thickness"]),
                       "the hole would run into the corner or off the plate"),
            Constraint("thickness < min(leg_a, leg_b) / 3",
                       lambda p: float(p["thickness"]) < min(float(p["leg_a"]),
                                                             float(p["leg_b"])) / 3.0,
                       "a leg barely longer than it is thick is a block, not a bracket"),
        ),
        build=_bracket_build, expectations=X.l_bracket_expectations, bbox=X.l_bracket_bbox,
        profile_marks=X.l_bracket_profile_marks, volume=X.l_bracket_volume,
    )

    vented_enclosure = CertifiedTemplate(
        name="vented_enclosure", version="1.0.0", domain_id="vented_enclosure@1.0.0/d1",
        backend="trimesh-manifold",
        covers="a walled enclosure with a vent grid through one wall and four "
               "corner mounting bosses: electronics case, fan shroud, driver box",
        bounds={
            "inner_w": Bound(40.0, 230.0, "mm", "narrower will not take a vent grid; "
                                                "wider leaves a 256 mm bed"),
            "inner_d": Bound(30.0, 230.0, "mm", "same bed limit, across"),
            "inner_h": Bound(20.0, 240.0, "mm", "shorter has no room for vent rows"),
            "wall": Bound(1.6, 10.0, "mm", "four perimeters at 0.4; the vents cut "
                                           "through it and a thinner wall tears"),
            "floor": Bound(1.6, 20.0, "mm", "four layers at 0.2 mm minimum"),
            "vent_cols": Bound(1, 40, "count", "one column is a slot; past 40 the "
                                               "webs between vents drop under a nozzle"),
            "vent_rows": Bound(1, 20, "count", "same web limit vertically"),
            "vent_w": Bound(2.0, 40.0, "mm", "narrower than 2 will not print open"),
            "vent_h": Bound(1.0, 40.0, "mm", "shorter than 1 closes up in the slicer"),
            "boss_d": Bound(5.0, 30.0, "mm", "smaller cannot hold a fastener"),
            "boss_bore": Bound(1.5, 20.0, "mm", "common self-tapping pilots"),
        },
        constraints=(
            Constraint("boss_bore < boss_d - 2",
                       lambda p: float(p["boss_bore"]) < float(p["boss_d"]) - 2.0,
                       "less than a millimetre of boss wall each side splits"),
            Constraint("4 * boss_d < min(inner_w, inner_d)",
                       lambda p: 4.0 * float(p["boss_d"]) < min(float(p["inner_w"]),
                                                                float(p["inner_d"])),
                       "the bosses would meet in the middle and there would be no cavity"),
            # Written against the builder's own pitch, `inner_w / (cols + 1)`.
            # These divided by `cols` and added `2 * wall`, which admitted a grid
            # whose vents overlapped: five 33.2 mm vents on a 28.6 mm pitch. The
            # closed form counts N separate cuts and overlapping cuts remove less
            # material than N of them, so the volume screen called a part built
            # exactly as asked an ANOMALY.
            Constraint("vent_w + 2 < inner_w / (vent_cols + 1)",
                       lambda p: float(p["vent_w"]) + 2.0
                       < float(p["inner_w"]) / (int(p["vent_cols"]) + 1),
                       "the vents would run into each other with no web between"),
            Constraint("vent_h + 2 < inner_h / (vent_rows + 1)",
                       lambda p: float(p["vent_h"]) + 2.0
                       < float(p["inner_h"]) / (int(p["vent_rows"]) + 1),
                       "the vent rows would merge into one opening"),
            Constraint("wall < min(inner_w, inner_d) / 4",
                       lambda p: float(p["wall"]) < min(float(p["inner_w"]),
                                                        float(p["inner_d"])) / 4.0,
                       "the walls would consume the cavity"),
        ),
        build=_vented_build, expectations=X.vented_enclosure_expectations,
        bbox=X.vented_enclosure_bbox, profile_marks=X.vented_enclosure_profile_marks,
        volume=X.vented_enclosure_volume,
    )

    return {t.name: t for t in (c_clip, box_shell, l_bracket, vented_enclosure, trim_ring)}


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
