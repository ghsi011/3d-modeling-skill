#!/usr/bin/env python3
"""A mutation corpus, and the rates that decide whether screening is trusted.

The plan makes zero-dispatch `DIRECT` conditional on measured performance rather
than on detector code existing, and a review showed why: a 112 mm3 boss fused
between two declared section heights commissioned CLEAR. Detectors that exist are
not detectors that work.

So this builds defective parts on purpose, in five classes, and reports what the
screens and the contract each catch. Two rates come out:

* **false negative** -- a mutant nothing flagged. Reported per class, because the
  classes are not interchangeable: added material is screening's job and a
  missing feature is the contract's, and averaging them would hide both.
* **false positive** -- a correct part something flagged. This is the rate that
  decides whether anybody will still be reading the output in a month.

Run it: `uv run --project <skill> --frozen python -m pipeline.corpus` (from the skill directory) or `uv run --project <extracted-bundle> --frozen python -m pipeline.corpus` (from any directory)
"""
from __future__ import annotations

import dataclasses
import math
import random
import tempfile
from pathlib import Path
from typing import Any, Callable

import numpy as np
import trimesh

from . import analysis, commission, screening
from .contract import Contract

ADDED = "added-material"
MISSING = "missing-feature"
WRONG_FACE = "wrong-face"
EDGE_OPEN = "edge-open"
DEBRIS = "boolean-debris"

CLASSES = (ADDED, MISSING, WRONG_FACE, EDGE_OPEN, DEBRIS)

# Screening is only claimed to catch material that should not be there. The
# contract owns absence, and saying so here keeps the corpus honest about which
# instrument each class is actually testing.
SCREENING_CLASSES = frozenset({ADDED, DEBRIS})

MAX_FALSE_NEGATIVE = 0.05
MAX_FALSE_POSITIVE = 0.02
# Every certified template, not a sample. A global flag covering a template the
# corpus never saw is the same stale-True problem one level up.
MIN_TEMPLATES = 5


@dataclasses.dataclass
class Mutant:
    name: str
    defect_class: str
    mesh: trimesh.Trimesh
    note: str


@dataclasses.dataclass
class Outcome:
    mutant: Mutant
    commission_verdict: str
    screening_verdict: str
    body_count: int = 1

    @property
    def caught_by_contract(self) -> bool:
        return self.commission_verdict in ("FAIL", "ESCALATE")

    @property
    def caught_by_screening(self) -> bool:
        return self.screening_verdict in ("ANOMALY", "INDETERMINATE")

    @property
    def caught(self) -> bool:
        """Anything at all flagged it. Useful, and NOT the calibration number.

        The gate exists to decide whether the broad screen alone is trustworthy
        enough to drop the visual call. Contract checks are conditioned on
        declared features, which is precisely why they are not broad evidence --
        so a rate computed from `caught` measures the whole pipeline and answers
        a different question. It said 0.0 while screening's own rate on added
        material was 0.467.
        """
        return self.caught_by_contract or self.caught_by_screening

    @property
    def fused(self) -> bool:
        """Whether the defect is continuous with the part.

        A disconnected solid is debris, whatever class it was filed under, and
        the component detector sees it for free. Half the added-material mutants
        were separate bodies, so screening's apparent catches on that class were
        mostly the debris detector wearing another label.
        """
        return self.body_count == 1


def _cyl(radius: float, height: float, at, sections: int = 64) -> trimesh.Trimesh:
    mesh = trimesh.creation.cylinder(radius=radius, height=height, sections=sections)
    mesh.apply_translation(at)
    return mesh


def _box(extents, at) -> trimesh.Trimesh:
    mesh = trimesh.creation.box(extents=extents)
    mesh.apply_translation(at)
    return mesh


def _union(a, b):
    return trimesh.boolean.union([a, b], engine="manifold")


def _diff(a, b):
    return trimesh.boolean.difference([a, b], engine="manifold")


def c_clip_mutants(params: dict[str, Any], clean: trimesh.Trimesh) -> list[Mutant]:
    """Defects a c_clip can actually have, at several sizes and positions.

    Sizes matter more than count. One large boss proves nothing about the
    threshold; the interesting question is where a screen stops seeing, so the
    same defect appears at 2, 4 and 8 mm and the report says which survived.
    """
    fw, fd, ft = params["flange_w"], params["flange_d"], params["flange_t"]
    height, bore_d = params["height"], params["bore_d"]
    cx, cy = fw / 2.0, fd / 2.0
    outer_r = bore_d / 2.0 + params["wall"]
    ring_z = ft + height / 2.0
    out: list[Mutant] = []

    # Added material, fused, at three scales and two heights.
    for r in (1.0, 2.0, 4.0):
        post = _cyl(r, height + 1.0, (cx, cy, ft - 1.0 + (height + 1.0) / 2.0))
        out.append(Mutant(f"post-r{r:g}-in-channel", ADDED, _union(clean, post),
                          f"{math.pi * r * r:.1f} mm2 standing in the declared void"))
    for r in (1.5, 3.0):
        boss = _cyl(r, height * 0.3, (cx + outer_r + r * 0.6, cy, ring_z))
        out.append(Mutant(f"boss-r{r:g}-outside-ring", ADDED, _union(clean, boss),
                          "material on the outside of the ring, between declared sections"))
    rib = _box((fw * 0.5, 2.0, height * 0.5), (cx, cy - outer_r - 1.0, ring_z))
    out.append(Mutant("rib-on-flange", ADDED, _union(clean, rib),
                      "a rib nobody declared, above the flange"))

    # Missing features. The contract's job, not screening's.
    plug = _cyl(params["screw_d"] / 2.0 - 0.01, ft, (fw * 0.2, cy, ft / 2.0))
    out.append(Mutant("screw-bore-filled", MISSING, _union(clean, plug),
                      "the fastener hole gone; smooth and plausible"))
    mouth_fill = _box((params["mouth_gap"], outer_r, height),
                      (cx, cy + outer_r / 2.0, ring_z))
    out.append(Mutant("mouth-closed", MISSING, _union(clean, mouth_fill),
                      "the C closed into an O -- no bundle can enter"))

    # Wrong face: the bore drilled through the flange from the side.
    sideways = _cyl(params["screw_d"] / 2.0, fw, (cx, cy, ft / 2.0))
    sideways.apply_transform(trimesh.transformations.rotation_matrix(
        math.pi / 2, [0, 1, 0], [cx, cy, ft / 2.0]))
    filled = _union(clean, _cyl(params["screw_d"] / 2.0 - 0.01, ft, (fw * 0.2, cy, ft / 2.0)))
    out.append(Mutant("bore-on-the-wrong-face", WRONG_FACE, _diff(filled, sideways),
                      "right hole, wrong face -- volume barely moves"))

    # Edge-open cut through the flange.
    for width in (3.0, 6.0):
        slot = _box((width, fd * 1.5, ft * 3), (cx, fd, ft / 2.0))
        out.append(Mutant(f"flange-slotted-{width:g}mm", EDGE_OPEN, _diff(clean, slot),
                          "a cut reaching the flange edge; not a ring, so counts are blind"))

    # Boolean debris, at sizes a fragment realistically takes.
    for side in (0.6, 1.2, 3.0):
        speck = _box((side, side, side), (2.0, 2.0, side / 2.0))
        out.append(Mutant(f"debris-{side:g}mm", DEBRIS,
                          trimesh.util.concatenate([clean, speck]),
                          "a solid nobody asked for, disconnected from the part"))
    return out


def _bed_point(clean: trimesh.Trimesh) -> tuple[float, float]:
    """A point in XY that is guaranteed to have material under it.

    The centre of the bounding box is not: it is the mouth of a C-channel, the
    empty quadrant of an L, and the cavity of every shell. The largest face lying
    on the bed plane is real material by construction, so its centroid is
    somewhere a mutant can stand.
    """
    z0 = float(clean.bounds[0][2])
    centers = clean.triangles_center
    on_bed = np.abs(centers[:, 2] - z0) < 1e-6
    if not on_bed.any():                       # not seated: fall back to the centre
        lo, hi = clean.bounds
        return float((lo[0] + hi[0]) / 2.0), float((lo[1] + hi[1]) / 2.0)
    areas = clean.area_faces[on_bed]
    biggest = centers[on_bed][int(np.argmax(areas))]
    return float(biggest[0]), float(biggest[1])


def _require_fused(mesh: trimesh.Trimesh, name: str) -> trimesh.Trimesh:
    """A mutant that did not fuse is a corpus bug, not a caught defect.

    Silently counting it flatters the screen twice over: the component detector
    catches it for free, and it is excluded from the fused rate the gate reads --
    so the corpus shrinks toward whichever template happens to place material
    where there is material, and reports a rate measured on that one.
    """
    if mesh.body_count != 1:
        raise AssertionError(
            f"corpus: added-material mutant {name!r} left {mesh.body_count} bodies. "
            "It floats -- place it on the part, or the component detector catches "
            "it for free and it never scores against screening.")
    return mesh


def generic_mutants(clean: trimesh.Trimesh) -> list[Mutant]:
    """Defects any part can have, built to be hard rather than convenient.

    The first version of this corpus reported a 0.0 miss rate and a review broke
    it in minutes. Three construction errors made the mutants easy, and all three
    are corrected here:

    * **Fused, not floating.** Bosses were placed at `hi[0] - r*0.5`, which on
      two of three templates landed in empty space -- so they were separate
      solids and the component detector caught them for free.

      This paragraph used to end "and asserted to leave one body". There was no
      assertion, and the property was false on four of five templates: added
      material was placed at mid-height in the middle of the part, which inside a
      shell is air. 19 of 30 added-material mutants were separate solids and the
      fused rate the calibration gate reads came from `c_clip` alone. Both are
      fixed here -- material is seated on the part rather than floated in its
      bounding box, and `_require_fused` raises if a mutant does not fuse, so the
      corpus fails loudly instead of quietly measuring the wrong thing.
    * **Inside the envelope.** They protruded past the bounding box and tripped
      the envelope check, which is a contract check, not a screen. These stay
      within it.
    * **Off the declared marks.** They sat exactly on a declared section plane,
      so a `feature-*` row caught them. These are placed deliberately *between*
      declared heights, where only a profile can see them.

    A corpus whose defects are visible to the checks you are not measuring tells
    you nothing about the check you are.
    """
    lo, hi = clean.bounds[0], clean.bounds[1]
    span = hi - lo
    cx, cy = (lo[0] + hi[0]) / 2.0, (lo[1] + hi[1]) / 2.0
    scale = float(min(span[0], span[1]))
    bx, by = _bed_point(clean)
    out: list[Mutant] = []

    # Added material: a ledge grown inward from a wall, and a post standing in
    # the middle. Both inside the bbox, both spanning a band between marks.
    for frac in (0.03, 0.06, 0.12):
        thickness = max(float(span[2]) * frac, 0.8)
        # Seated on the bed and against a wall. Centred in the bounding box at
        # mid-height -- where this used to sit -- is air on every shell, and on
        # an L it is the empty quadrant. The bed plane is the one height at which
        # a seated part is guaranteed to have material under the mutant.
        depth = float(span[0]) * 0.25
        ledge = _box((depth, float(span[1]) * 0.5, thickness),
                     (float(lo[0]) + depth / 2.0, cy, float(lo[2]) + thickness / 2.0))
        out.append(Mutant("ledge-%.0f%%-mid-height" % (frac * 100), ADDED,
                          _require_fused(_union(clean, ledge),
                                         "ledge-%.0f%%" % (frac * 100)),
                          "a ledge between declared heights, wholly inside the envelope"))

    # Seated on the part, not floated at mid-height. A post centred in a shell's
    # bounding box stands in the cavity touching nothing; seating its base on the
    # bed plane guarantees it meets material, because every part here is seated.
    for frac in (0.05, 0.10, 0.20):
        r = max(scale * frac, 0.6)
        h = float(span[2]) * 0.5
        post = _cyl(r, h, (bx, by, float(lo[2]) + h / 2.0))
        out.append(Mutant("post-%.0f%%-standing-on-the-part" % (frac * 100), ADDED,
                          _require_fused(_union(clean, post),
                                         "post-%.0f%%" % (frac * 100)),
                          "a post rising from the part, inside the envelope"))

    # The one the review broke this corpus with: small, seated on the interior
    # floor, between declared marks. 0.234% of the volume of a box_shell.
    for frac in (0.02, 0.04, 0.08):
        r = max(scale * frac, 0.6)
        h = float(span[2]) * 0.25
        # Base on the bed plane: every part here is seated, so that is the one
        # height at which material is guaranteed to be present.
        boss = _cyl(r, h, (bx, by, float(lo[2]) + h / 2.0))
        out.append(Mutant("floor-boss-%.0f%%" % (frac * 100), ADDED,
                          _require_fused(_union(clean, boss),
                                         "floor-boss-%.0f%%" % (frac * 100)),
                          "a small boss low on the part, off every declared mark"))

    # Debris stays disconnected -- that is what makes it debris.
    for frac in (0.01, 0.03, 0.08):
        side = max(scale * frac, 0.4)
        speck = _box((side, side, side),
                     (float(lo[0]) - side, float(lo[1]) - side, float(lo[2]) + side / 2.0))
        out.append(Mutant("debris-%.0f%%" % (frac * 100), DEBRIS,
                          trimesh.util.concatenate([clean, speck]),
                          "%.2f mm solid, disconnected" % side))

    for frac in (0.06, 0.12):
        width = max(scale * frac, 1.0)
        slot = _box((width, float(span[1]) * 1.5, float(span[2]) * 0.4),
                    (cx, float(hi[1]), float(lo[2]) + float(span[2]) * 0.15))
        out.append(Mutant("edge-slot-%.0f%%" % (frac * 100), EDGE_OPEN,
                          _diff(clean, slot),
                          "a cut open to the edge, low on the part"))
    return out


def _as_mesh(solid, tmp: Path) -> trimesh.Trimesh:
    """A trimesh, whichever backend produced the solid.

    A build123d template hands back a B-rep `Part`, which has no `.export`
    trimesh understands. Mutating one means mutating its tessellation, which is
    also what the pipeline actually measures -- so the corpus works on the
    exported mesh for every backend, exactly as commissioning does.
    """
    if isinstance(solid, trimesh.Trimesh):
        return solid
    from build123d import export_stl
    path = tmp / "brep.stl"
    export_stl(solid, str(path), tolerance=0.01, angular_tolerance=0.1)
    return trimesh.load(path, force="mesh")


def _evaluate(mesh: trimesh.Trimesh, contract: Contract,
              tmp: Path) -> tuple[str, str, int]:
    path = tmp / "m.stl"
    mesh.export(path)
    ctx = analysis.load(path)
    return (commission.run(ctx, contract)["verdict"],
            screening.run(ctx, contract)["overall"],
            len(ctx.components))


def _contract_at(name: str, params: dict[str, Any]) -> Contract:
    """A contract for arbitrary in-domain parameters, not just the nominal point."""
    from . import runner as R
    from . import templates as T

    request = R.JobRequest(job_id="corpus", brief_path=Path("none"), template=name,
                           parameters=params, stated=frozenset(),
                           consequence="INCONSEQUENTIAL", out_dir=Path("."),
                           updated_utc="1970-01-01T00:00:00Z", render=False,
                           printer="corpus", material={"process": "FDM", "material": "PLA"},
                           nozzle={"diameter_mm": 0.4},
                           orientation={"model_to_printer_matrix": "identity", "bed_z_mm": 0.0})
    return R._contract_from(T.get(name), request)


# How many in-domain parameter sets each template is checked at for false
# positives, beyond its nominal point.
#
# One point per template is not a rate. Measured on five nominal points the false
# positive rate read 0.0 while `c_clip` flagged 36% of its own certified domain:
# nothing constrained the ring to fit inside the flange the bounding box is
# derived from, so a correct part failed the envelope check for being outside a
# box the contract had computed wrong. A threshold of 2% against a denominator of
# five cannot express 2%.
DOMAIN_SAMPLES = 12
DOMAIN_SEED = 20260727


def _domain_points(tpl, count: int, seed: int) -> list[dict[str, Any]]:
    """Deterministic parameter sets drawn from inside a template's own domain.

    Seeded, because a corpus that samples differently each run reports a rate
    that moves on its own and cannot be regressed against.
    """
    rng = random.Random(f"{seed}:{tpl.name}")
    points: list[dict[str, Any]] = []
    for _ in range(count * 400):
        if len(points) >= count:
            break
        candidate = {k: rng.uniform(b.low, b.high) for k, b in tpl.bounds.items()}
        if not tpl.rejects(candidate):
            points.append(candidate)
    return points


def run(templates: list[tuple[str, dict[str, Any], Callable[[], Contract]]]) -> dict[str, Any]:
    """Measure every template against its mutants, plus the clean part."""
    rows: list[Outcome] = []
    false_positives: list[str] = []

    clean_parts = 0
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        for name, params, contract_of in templates:
            from . import templates as T
            contract = contract_of()
            built, _ = T.get(name).build(params)
            clean = _as_mesh(built, tmp)

            clean_parts += 1
            verdict, screen, _ = _evaluate(clean, contract, tmp)
            if verdict != "PASS" or screen != "CLEAR":
                false_positives.append(f"{name}: clean part flagged "
                                       f"(commission {verdict}, screening {screen})")

            # And across the domain, not only at the nominal point. A template
            # certified for a range is a claim about the whole range.
            from . import templates as T
            tpl = T.get(name)
            for point in _domain_points(tpl, DOMAIN_SAMPLES, DOMAIN_SEED):
                clean_parts += 1
                try:
                    sampled = _as_mesh(tpl.build(point)[0], tmp)
                    v, s, _ = _evaluate(sampled, _contract_at(name, point), tmp)
                except Exception as exc:                        # noqa: BLE001
                    # A build that raises on parameters the domain accepts is a
                    # false positive of the worst kind: no receipt at all.
                    false_positives.append(f"{name}: in-domain build raised "
                                           f"{type(exc).__name__}: {exc} at {point}")
                    continue
                if v != "PASS" or s != "CLEAR":
                    false_positives.append(f"{name}: in-domain part flagged "
                                           f"(commission {v}, screening {s}) at {point}")

            mutants = generic_mutants(clean)
            if name == "c_clip":
                mutants += c_clip_mutants(params, clean)
            for mutant in mutants:
                v, s, bodies = _evaluate(mutant.mesh, contract, tmp)
                rows.append(Outcome(Mutant(name + "/" + mutant.name, mutant.defect_class,
                                           mutant.mesh, mutant.note), v, s, bodies))

    per_class: dict[str, Any] = {}
    for defect in CLASSES:
        subset = [r for r in rows if r.mutant.defect_class == defect]
        if not subset:
            continue
        # Fused only, for screening's own rate. A disconnected solid is debris
        # whatever class it was filed under, and the component detector sees it
        # for free -- counting those as profile catches flattered the screen.
        fused = [r for r in subset if r.fused]
        screening_missed = [r for r in fused if not r.caught_by_screening]
        per_class[defect] = {
            "mutants": len(subset),
            "fused_mutants": len(fused),
            "caught_by_anything": len([r for r in subset if r.caught]),
            "pipeline_false_negative_rate": round(
                len([r for r in subset if not r.caught]) / len(subset), 4),
            "screening_false_negative_rate": (
                round(len(screening_missed) / len(fused), 4) if fused else None),
            # Read this next to `screening_false_negative_rate`, which is None for
            # any class with no fused mutants. Debris is disconnected by
            # construction -- that is what makes it debris -- so it has no fused
            # rate and the gate below cannot score it. It is still caught, every
            # one, for free by the component detector; without this count the
            # class reads as unmeasured rather than trivial.
            "caught_by_screening": len([r for r in subset if r.caught_by_screening]),
            "caught_by_contract_only": len([r for r in subset
                                            if r.caught_by_contract and not r.caught_by_screening]),
            "survivors_of_everything": [r.mutant.name for r in subset if not r.caught],
            "survivors_of_screening": [r.mutant.name for r in screening_missed],
            "screening_is_responsible": defect in SCREENING_CLASSES,
        }

    screening_classes = [c for c in SCREENING_CLASSES if c in per_class
                         and per_class[c]["screening_false_negative_rate"] is not None]
    worst_screening_fn = max(
        (per_class[c]["screening_false_negative_rate"] for c in screening_classes),
        default=1.0)
    fp_rate = len(false_positives) / max(clean_parts, 1)

    return {
        "templates": [t[0] for t in templates],
        "mutants": len(rows),
        "per_class": per_class,
        "screening_false_negative_rate": worst_screening_fn,
        "false_positive_rate": round(fp_rate, 4),
        # The denominator, because the rate is meaningless without it: this read
        # 0.0 over five clean parts while one template flagged 36% of its domain.
        "clean_parts_checked": clean_parts,
        "false_positives": false_positives,
        "thresholds": {"max_false_negative": MAX_FALSE_NEGATIVE,
                       "max_false_positive": MAX_FALSE_POSITIVE},
        "templates_measured": len(templates),
        # Every certified template, not a sample: see MIN_TEMPLATES. Two
        # templates that both happen to be boxes would agree with each other and
        # prove nothing about the third shape somebody actually asks for.
        "gate": ("PASS" if worst_screening_fn <= MAX_FALSE_NEGATIVE
                 and fp_rate <= MAX_FALSE_POSITIVE
                 and len(templates) >= MIN_TEMPLATES else "FAIL"),
        "note": ("The gate covers the classes screening is responsible for. Missing "
                 "features and wrong-face features are the contract's job; their rates "
                 "are reported so a regression there is visible, not so screening can "
                 "take credit for them."),
    }


PARAMS = {
    "c_clip": {"bore_d": 12.0, "wall": 3.0, "height": 9.0, "mouth_gap": 9.0,
               "flange_w": 40.0, "flange_d": 22.0, "flange_t": 5.0, "screw_d": 4.8},
    "box_shell": {"inner_w": 80.0, "inner_d": 60.0, "inner_h": 40.0,
                  "wall": 2.5, "floor": 2.5},
    "l_bracket": {"width": 40.0, "leg_a": 50.0, "leg_b": 45.0, "thickness": 4.0,
                  "hole_d": 5.0, "hole_inset": 10.0},
    # The build123d template. Certified and DIRECT-routable, so leaving it out
    # meant a global CALIBRATED covering a template nobody had measured.
    "trim_ring": {"hole_d": 60.0, "lip_w": 5.0, "panel_t": 18.0, "lip_t": 3.0,
                  "wall": 2.0, "chamfer": 1.0},
    # The complex one: 72 vent cuts and four bosses, ~4,500 faces. A screen
    # calibrated only on simple shapes says nothing about the parts that are
    # actually hard to get right.
    "vented_enclosure": {"inner_w": 180.0, "inner_d": 120.0, "inner_h": 90.0,
                         "wall": 3.0, "floor": 3.0, "vent_cols": 12, "vent_rows": 6,
                         "vent_w": 8.0, "vent_h": 4.0, "boss_d": 10.0,
                         "boss_bore": 4.2},
}


def _default_templates():
    from . import runner as R
    from . import templates as T

    def make(name, params):
        def contract_of():
            request = R.JobRequest(job_id="corpus", brief_path=Path("none"), template=name,
                                   parameters=params, stated=frozenset(),
                                   consequence="INCONSEQUENTIAL", out_dir=Path("."),
                                   updated_utc="1970-01-01T00:00:00Z", render=False,
                                   printer="corpus", material={"process": "FDM", "material": "PLA"},
                                   nozzle={"diameter_mm": 0.4},
                                   orientation={"model_to_printer_matrix": "identity", "bed_z_mm": 0.0})
            return R._contract_from(T.get(name), request)
        return (name, params, contract_of)

    return [make(name, params) for name, params in sorted(PARAMS.items())]


def main() -> int:
    import json
    import sys

    report = run(_default_templates())
    sys.stdout.write(json.dumps(report, indent=2) + "\n")
    return 0 if report["gate"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

