"""One call that builds a candidate and blocks until it is defensible.

Why this exists, from the measured record of real runs:

* Every rejection a fresh verifier ever issued was a *deterministic* predicate
  the designer's own readiness receipt already claimed to have checked -- a bed
  face 16 mm off the bed, a 9,032 mm2 unsupported roof, a sweep blocked by
  12,709 mm3, a sharp junction where a radius was declared. One archived job
  spent four full verifier dispatches rediscovering them. A deterministic check
  that can fail after handoff is a check in the wrong place.
* Designers hand-wrote 130-280 line verify scripts per job because ``finalize``
  takes its datums, sweep, orientation and threshold as caller-supplied. That
  authored code is also where the worst evidence defect came from: one run's
  evidence described a mesh that was no longer the one being shipped.
* Thresholds were authored by the party being measured, after measuring. One
  observed 1799.73 mm2 and declared a 1850.0 ceiling; another widened an edge
  band twentyfold to fit its own sampler.

So: one entry point, everything derived, every deterministic verdict computed
here, and a non-zero exit if any of them fails. What remains for the agent is
what a machine cannot do -- look at the render, and judge whether the thing
solves the problem.
"""
from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ._bootstrap import as_mesh  # noqa: F401  (also puts scripts/ on sys.path)

from . import edges, fit, orient, static  # noqa: E402
from .bundle import finalize  # noqa: E402
from .metrics import BARE_45_DEG, measure  # noqa: E402
from .verdict import FAIL as _FAIL  # noqa: E402
from .verdict import PASS as _PASS  # noqa: E402
from .verdict import SKIP as _SKIP  # noqa: E402
from .verdict import Check  # noqa: E402


@dataclass
class Commission:
    checks: list[Check] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    def add(self, check: Check) -> None:
        self.checks.append(check)

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if c.result == _FAIL]

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": _FAIL if self.failed else _PASS,
            "checks": [c.as_dict() for c in self.checks],
            "evidence": self.evidence,
            "judgment_required": {
                "visual_accept": None,
                "fit_band_ok": None,
                "note": "A machine cannot supply these. Look at the renders and decide.",
            },
        }


def load_model(model_path: Path):
    """Import a model module and return its parameters and its part.

    The module must expose ``part`` or a zero-argument ``build()``. Anything
    else is a contract the caller has to guess at, and guessing is what the
    hand-written scripts were doing.

    ``PARAMS`` is read *before* ``build()`` runs, because the pre-build stage
    has to be able to reject the numbers without paying for the geometry they
    describe.
    """
    spec = importlib.util.spec_from_file_location(model_path.stem, model_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot import {model_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    params = getattr(module, "PARAMS", None)
    if not isinstance(params, dict):
        params = None
    if hasattr(module, "part"):
        return params, module.part
    if hasattr(module, "build"):
        return params, module.build
    raise ValueError(f"{model_path.name} must define `part` or `build()`")


def load_part(model_path: Path) -> Any:
    """Back-compat shim for direct callers: just the part."""
    _, part = load_model(model_path)
    return part() if callable(part) else part


def _plan_support_rules(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Every rule, not the first.

    Returning `rules[0]` left rules 2..n unchecked, so a plan could forbid
    support on a face nobody ever screened and still exit zero.
    """
    return list(plan.get("support_rules") or [])


def planned_placement(rule: dict[str, Any], mesh, threshold: float) -> orient.Placement:
    """The orientation the rule declares, or the best available if it declares none.

    The contract check is *planned*-orientation printability. Screening in
    `orient.best` instead answers a different question -- whether some
    orientation exists that prints cleanly -- so a candidate could pass in an
    orientation nobody intended to print, while the face that actually lands
    downward went unscreened.
    """
    matrix = rule.get("model_to_printer_matrix")
    if matrix is None:
        best = orient.best(mesh, threshold=threshold)
        return dataclasses.replace(
            best, name=f"{best.name} (plan declared no model_to_printer_matrix)")
    return orient.score(mesh, "plan model_to_printer_matrix", matrix, threshold=threshold)


def _check_solid(commission: Commission, report) -> None:
    ok = report.watertight and report.components == 1
    commission.add(Check(
        "solid", "Single watertight solid",
        _PASS if ok else _FAIL,
        f"watertight={report.watertight}, components={report.components}",
        "" if ok else "A non-watertight or multi-body export cannot be printed or "
                      "measured. Fix the boolean/shell before anything else here matters.",
    ))


def _check_envelope(commission: Commission, report, plan: dict[str, Any]) -> None:
    """The check whose absence shipped a case 31% too thick.

    Nothing in the pipeline compared the candidate's own size against an
    intended size, because no contract declared one. Every scalar gate passed.
    """
    expected = plan.get("expected_bbox_mm")
    if not expected:
        commission.add(Check(
            "envelope", "Overall size vs plan", _FAIL,
            "the plan declares no expected_bbox_mm",
            "Declare expected_bbox_mm {x,y,z} and bbox_tolerance_mm in the plan. This "
            "is a FAIL and not a skip on purpose: without it nothing checks the part's "
            "own size, and a candidate once shipped 31% too thick while passing every "
            "other gate. Generate a plan with `designer_toolkit.plan template` if none "
            "was bound.",
        ))
        return
    tolerance = float(plan.get("bbox_tolerance_mm", 1.0))
    # `None` rather than 0.0: a zero start is indistinguishable from "no
    # comparison ran", so an expected_bbox_mm with unreadable keys used to
    # report `worst axis n/a off by +0.00 mm` and PASS whatever the part's size.
    worst_axis, worst = "", None
    for axis in ("x", "y", "z"):
        if axis in expected:
            delta = report.bbox_mm[axis] - float(expected[axis])
            if worst is None or abs(delta) > abs(worst):
                worst_axis, worst = axis, delta
    if worst is None:
        commission.add(Check(
            "envelope", "Overall size vs plan", _FAIL,
            f"expected_bbox_mm declares no readable x/y/z axis: {expected!r}",
            "Give expected_bbox_mm numeric `x`, `y` and `z` in millimetres. A key the "
            "check cannot read is not a looser check, it is no check.",
        ))
        return
    ok = abs(worst) <= tolerance
    commission.add(Check(
        "envelope", "Overall size vs plan",
        _PASS if ok else _FAIL,
        f"worst axis {worst_axis or 'n/a'} off by {worst:+.2f} mm (tolerance {tolerance} mm)",
        "" if ok else f"The part is {worst:+.2f} mm out on {worst_axis}. Either the "
                      "geometry is wrong or the plan's expected_bbox_mm is. Resolve which "
                      "before proceeding -- do not widen the tolerance to fit the part.",
    ))


def _check_support(commission: Commission, mesh, plan: dict[str, Any]) -> list[Any]:
    """Screen every support rule, each in the orientation it declares."""
    rules = _plan_support_rules(plan)
    if not rules:
        commission.add(Check("support", "Downward-facing area within the plan limit", _FAIL,
                             "the plan declares no support rules",
                             "Nothing constrains the print orientation, so this cannot "
                             "pass. Add a support rule, or generate a plan with "
                             "`python -m designer_toolkit.plan template`."))
        return []

    placements = []
    for rule in rules:
        rule_id = rule.get("id", "S-01")
        threshold = float(rule.get("downward_normal_z_max", BARE_45_DEG))
        disposition = rule.get("disposition", "SELF_SUPPORT_REQUIRED")
        ceiling = float(rule.get("max_out_of_limit_area_mm2", 0.0))

        # The contract says SELF_SUPPORT_REQUIRED means zero out-of-limit area, and
        # the gate accepted any non-negative ceiling. Two archived runs declared
        # SELF_SUPPORT_REQUIRED with ceilings of 1850 and 2150 mm2 and passed.
        if disposition == "SELF_SUPPORT_REQUIRED" and ceiling > 0:
            commission.add(Check(
                f"support-ceiling-{rule_id}", f"{rule_id} ceiling matches disposition", _FAIL,
                f"SELF_SUPPORT_REQUIRED declared with a ceiling of {ceiling} mm2",
                "SELF_SUPPORT_REQUIRED means zero out-of-limit area. Either reorient until "
                "it is zero, or declare SUPPORT_ALLOWED and say which faces take support.",
            ))
            ceiling = 0.0

        placement = planned_placement(rule, mesh, threshold)
        placements.append(placement)
        area = placement.overhang_mm2
        ok = area <= ceiling
        best = orient.best(mesh, threshold=threshold)
        # Name the remedies rather than leaving them to be rediscovered. One
        # measured run spent three full build/export/measure cycles arriving at
        # two of these -- a vertical-walled slot and a teardrop bore roof --
        # both of which fdm-design.md already documents.
        advice = (
            f"The best of {len(orient._CANDIDATES)} screened placements is "
            f"'{best.name}' at {best.overhang_mm2:.2f} mm2"
            + (" -- no orientation clears this, so the fix is geometric. "
               if best.overhang_mm2 > ceiling else ", so reorienting may be enough. ")
            + "For the usual causes: a horizontal round bore has an unsupported crown -- "
              "give it a teardrop or flat/diamond roof (fdm-design section 3). A radial or "
              "pie-slice cut leaves a cheek face just past the screen -- make the slot "
              "vertical-walled instead. A flat roof or ledge wants a 45 deg chamfer under "
              "it. If meeting zero would distort a functional surface -- a mating wall, a "
              "bore that has to stay round, the cavity itself -- do not contort the "
              "geometry: say so in your handoff and let the print engineer plan a bounded "
              "SUPPORT_ALLOWED on a nonfunctional region. Support-free is the default, not "
              "a hard constraint."
        )
        commission.add(Check(
            f"support-{rule_id}", f"{rule_id} downward-facing area within its limit",
            _PASS if ok else _FAIL,
            f"{area:.2f} mm2 past {threshold} in the '{placement.name}' placement "
            f"(limit {ceiling} mm2)",
            "" if ok else advice,
        ))
    return placements


def seated_clearance_mm(candidate, reference) -> float:
    """Tightest per-side gap between the seated pair, in mm.

    Positive is a gap, negative is overlap depth. The plan declares `min_mm` and
    `max_mm` as per-side *linear* clearances, so a linear measurement is the only
    thing comparable to them. This gate used to test a boolean-intersection
    *volume* against those millimetres, which meant a correctly clearing part --
    0.0 mm3 of overlap -- failed a declared `[0.15, 0.30]` band, because
    `0.15 <= 0.0` is false.

    Signed distance is positive inside the solid, so a reference point sitting
    in the cavity void reports minus its distance to the nearest wall; the
    tightest point of the assembly is the largest such value.

    `rtree` gives the fast path when it is installed, but it lives in the
    `section` extra and this is a core fit gate -- a check that quietly stops
    running on a lean install is the failure mode this whole module exists to
    remove. So the fallback is exact too, just slower: nearest point by brute
    force, and the sign from the winning face's own normal rather than a
    ray-cast containment test.
    """
    points = np.asarray(reference.vertices, dtype=float)
    try:
        from trimesh.proximity import ProximityQuery

        return -float(np.max(ProximityQuery(candidate).signed_distance(points)))
    except ImportError:
        from trimesh.proximity import closest_point_naive

        closest, distance, face_ids = closest_point_naive(candidate, points)
        outward = np.einsum("ij,ij->i", points - closest, candidate.face_normals[face_ids])
        signed = np.where(outward >= 0, -distance, distance)
        return -float(np.max(signed))


def _check_interfaces(commission: Commission, mesh, plan: dict[str, Any], reference) -> None:
    interfaces = plan.get("interfaces") or []
    if not interfaces:
        commission.add(Check("fit", "Declared interface fit", _SKIP,
                             "the plan declares no mating interfaces, so there is no "
                             "fit to measure"))
        return
    if reference is None:
        commission.add(Check(
            "fit", "Declared interface fit", _FAIL,
            f"{len(interfaces)} interface(s) declared but no mating reference was supplied",
            "Pass --reference <mating.stl>. Forgetting it used to read as a skip, so a "
            "part with declared fit bands could pass without any of them being measured.",
        ))
        return

    reference_mesh = as_mesh(reference) if isinstance(reference, str) else reference
    clearance = seated_clearance_mm(mesh, reference_mesh)
    bands = [(float(i.get("min_mm", 0.0)), float(i.get("max_mm", 0.0))) for i in interfaces]
    # Intersection, not union. One reference yields one measurement -- the
    # tightest point of the assembly -- and it has to satisfy every declared
    # band, so the admissible window is [max(mins), min(maxes)]. Taking the
    # union instead admitted 0.30 mm against an interface capped at 0.10.
    low, high = max(b[0] for b in bands), min(b[1] for b in bands)
    ok = low - 1e-6 <= clearance <= high + 1e-6

    # One reference carries no per-interface regions, so the measurement is the
    # tightest point of the whole assembly and cannot say which interface owns
    # it. Say so rather than implying a per-ID verdict the geometry cannot give.
    scope = (f"tightest of {len(interfaces)} declared interfaces"
             if len(interfaces) > 1 else interfaces[0].get("id", "I-01"))
    if clearance < low:
        action = ("Too tight: the seated pair overlaps or clears by less than the declared "
                  "minimum. Open the mating geometry -- never widen the band.")
    else:
        action = ("Too loose: over-clearance fails the fit exactly as interference does, and "
                  "is what makes a part rattle. Close the mating geometry.")
    commission.add(Check(
        "fit", "Declared interface fit",
        _PASS if ok else _FAIL,
        f"seated clearance {clearance:.4f} mm ({scope}) against a declared band "
        f"[{low}, {high}] mm",
        "" if ok else action,
    ))
    commission.evidence["seated_clearance_mm"] = clearance
    commission.evidence["seated_interference_mm3"] = fit.interference(mesh, reference_mesh)


def run(
    *,
    model: Path | None,
    stl: Path | None,
    out_dir: Path,
    plan: dict[str, Any],
    reference: str | None = None,
    render: bool = True,
) -> Commission:
    """Build (if given a model), verify everything deterministic, write evidence."""
    out_dir.mkdir(parents=True, exist_ok=True)
    commission = Commission()

    source: Any = stl
    params: dict[str, Any] | None = None
    if stl is not None and not Path(stl).is_file():
        # Without this the path falls through to the exporter's CAD-kernel
        # branch and the caller is told "No module named 'cadquery'" -- which
        # sends them installing a kernel to fix a typo.
        raise FileNotFoundError(f"no such STL: {stl}")
    if model is not None:
        if not Path(model).is_file():
            raise FileNotFoundError(f"no such model module: {model}")
        params, source = load_model(model)

        # Pre-build stage. These read declared numbers only, so they cost
        # microseconds and, when they fail, they save the whole
        # build/export/measure cycle that would have found the same thing.
        # A wall thinner than two extrusions and a fillet that eats its own
        # clearance are arithmetic, not geometry.
        for check in static.check(params, plan):
            commission.add(check)
        if commission.failed:
            commission.evidence["stage_reached"] = "static"
            (out_dir / "commission.json").write_text(
                json.dumps(commission.as_dict(), indent=2, default=str), encoding="utf-8")
            return commission

        if callable(source):
            source = source()

    # Export: every measurement below is on the re-imported mesh, never on
    # the in-memory model, because that is what actually ships.
    from .exporter import export_and_hash
    report = export_and_hash(source, str(out_dir / "candidate_01"), also_step=True)
    exported = Path(report.stl_path)
    mesh = as_mesh(str(exported))

    _check_solid(commission, report)
    _check_envelope(commission, report, plan)

    placements = _check_support(commission, mesh, plan)
    placement = placements[0] if placements else orient.best(mesh)
    _check_interfaces(commission, mesh, plan, reference)

    measured_edges = {}
    for edge in plan.get("edges") or []:
        edge_id = edge.get("id", "E-??")
        corner = edge.get("corner_xy")
        if corner is None:
            # Never `continue`. The contract's edge row is {id, min_radius_mm,
            # max_radius_mm, samples_required} and says nothing about
            # `corner_xy`, so on a conformant plan this used to skip every edge
            # in silence and still exit zero -- a declared radius nobody
            # measured, which is exactly the defect a fresh verifier caught by
            # hand once already.
            commission.add(Check(
                f"edge-{edge_id}", f"Edge {edge_id} treatment", _FAIL,
                "the plan declares no corner_xy for this edge, so nothing was measured",
                f"Add `corner_xy` (and optionally `section_origin`, `window_mm`) to edge "
                f"{edge_id} so the section has somewhere to cut. A declared radius that "
                "nothing measured is not a met radius.",
            ))
            continue
        try:
            result = edges.measure_edge(
                mesh, tuple(corner),
                section_origin=tuple(edge.get("section_origin", (0, 0, 0))),
                window_mm=float(edge.get("window_mm", 4.0)),
            )
        except ImportError as exc:
            # Sectioning needs the `section` extra. Letting this propagate took
            # the whole gate down over one optional dependency; reporting it
            # keeps every other check's verdict, and keeps the gap visible.
            commission.add(Check(
                f"edge-{edge_id}", f"Edge {edge_id} treatment", _SKIP,
                f"cannot section without the `section` extra: {exc}",
                "Install the `section` extra (scipy, networkx, shapely, rtree). Until then "
                f"edge {edge_id}'s declared band is unverified -- do not treat it as met.",
            ))
            continue
        measured_edges[edge_id] = result.as_dict()
        if result.value_mm is None:
            commission.add(Check(
                f"edge-{edge_id}", f"Edge {edge_id} treatment", _FAIL,
                f"no {result.kind or 'treatment'} could be measured at {tuple(corner)}",
                "The section found nothing to measure there. Check corner_xy against the "
                "part's own frame -- a band that passes because its sampler returned null "
                "is not a passing band.",
            ))
            continue

        low = edge.get("min_radius_mm")
        high = edge.get("max_radius_mm")
        too_small = low is not None and result.value_mm + 1e-9 < float(low)
        too_large = high is not None and result.value_mm - 1e-9 > float(high)
        band = f"[{low if low is not None else '-'}, {high if high is not None else '-'}]"
        commission.add(Check(
            f"edge-{edge_id}", f"Edge {edge_id} treatment",
            _FAIL if (too_small or too_large) else _PASS,
            f"measured {result.kind} {result.value_mm:.3f} mm against band {band} mm",
            "" if not (too_small or too_large) else (
                "Increase the radius or declare the edge sharp with a reason. "
                if too_small else
                "The treatment is larger than the plan allows; an oversized fillet on a thin "
                "wall eats the wall. "
            ) + "Do not widen the band to fit the measurement.",
        ))

    bundle = finalize(
        str(exported), str(out_dir / "candidate_01"),
        reference=reference,
        orientation_transform=placement.transform,
        overhang_threshold=float((_plan_support_rules(plan) or [{}])[0].get(
            "downward_normal_z_max", BARE_45_DEG)),
        also_step=False,
    )

    commission.evidence.update({
        "export": bundle["export"],
        "placement": placement.as_dict(),
        "placements_considered": [p.as_dict() for p in orient.sweep(mesh)],
        "edges": measured_edges,
        "measure": measure(mesh).__dict__,
        "stage_reached": "complete",
        "planned_placements": [p.as_dict() for p in placements],
    })

    if render:
        try:
            from .render import section_render
            renders = out_dir / "renders"
            renders.mkdir(exist_ok=True)
            section_render(str(exported), str(renders / "section_x.png"),
                           plane_origin=(0, 0, 0), plane_normal=(1, 0, 0))
            commission.evidence["renders"] = ["renders/section_x.png"]
        except Exception as exc:  # noqa: BLE001 - a missing GL stack is not a design failure
            commission.add(Check(
                "render", "Section render for visual acceptance", _SKIP,
                f"renderer unavailable: {exc}",
                "Install the `visual` extra or run where a GL context exists. Visual "
                "acceptance cannot be signed off without looking at something.",
            ))

    (out_dir / "commission.json").write_text(
        json.dumps(commission.as_dict(), indent=2, default=str), encoding="utf-8")
    return commission


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m designer_toolkit commission",
        description="Build a candidate and run every deterministic check, in one call. "
                    "Exits non-zero if any check fails, so a failing candidate cannot "
                    "reach a verifier.",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--model", type=Path, help="Python module defining `part` or `build()`")
    source.add_argument("--stl", type=Path, help="an already-exported STL to check")
    parser.add_argument("--plan", type=Path, required=True, help="print_plan_checks.json")
    parser.add_argument("--out", type=Path, required=True, help="output directory")
    parser.add_argument("--reference", help="mating reference mesh for the fit check")
    parser.add_argument("--no-render", action="store_true")
    parser.add_argument("--job-id", default="job",
                        help="job_id stamped into the emitted receipts")
    parser.add_argument("--candidate-id", default="candidate-01")
    parser.add_argument("--dimensions-revision", type=int,
                        help="the dimensions.md revision this candidate was built against; "
                             "recorded in the receipts so `contracts status` can see it go "
                             "stale. Omitted, the receipts say UNBOUND rather than guessing.")
    parser.add_argument("--updated-utc", required=True,
                        help="ISO-8601 timestamp for the receipts; passed in, never "
                             "wall-clock, so a rerun on unchanged inputs is byte-identical")
    parser.add_argument("--no-receipts", action="store_true",
                        help="skip artifact_manifest.json / candidate_readiness.md")
    args = parser.parse_args(argv)

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    try:
        commission = run(model=args.model, stl=args.stl, out_dir=args.out, plan=plan,
                         reference=args.reference, render=not args.no_render)
    except (FileNotFoundError, ValueError) as exc:
        sys.stderr.write("commission: " + str(exc) + "\n")
        return 2

    payload = commission.as_dict()
    if not args.no_receipts:
        from . import receipts
        source_revisions = {}
        if args.dimensions_revision is not None:
            source_revisions["dimensions"] = args.dimensions_revision
        # The plan states its own revision, so that binding needs no flag.
        if isinstance(plan.get("revision"), int):
            source_revisions["print_plan"] = plan["revision"]
        receipts.write(payload, args.out, job_id=args.job_id,
                       candidate_id=args.candidate_id,
                       source_revisions=source_revisions or None,
                       updated_utc=args.updated_utc)
    sys.stdout.write(json.dumps(payload, indent=2, default=str) + "\n")
    for check in commission.failed:
        sys.stderr.write(f"FAIL {check.id}: {check.detail}\n      -> {check.action}\n")
    return 1 if commission.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
