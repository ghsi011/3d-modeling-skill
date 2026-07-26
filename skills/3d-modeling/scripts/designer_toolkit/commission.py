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

    @property
    def coverage(self) -> dict[str, Any]:
        """How much of the gate actually ran.

        `PASS` and "every check ran and passed" are not the same statement, and
        the receipt has only ever carried the first. A run whose STEP export,
        interface fit and every edge treatment all SKIPPED still reported
        `verdict: PASS` and `status: READY` -- true, and read by a human as far
        more assurance than four executed checks can carry. On the `DIRECT`
        route, where the built-in plan declares no interfaces and no edges and
        no fresh verifier ever re-derives any of it, that is most of the gate.
        """
        skipped = [c.id for c in self.checks if c.result == _SKIP]
        return {
            "declared": len(self.checks),
            "ran": len(self.checks) - len(skipped),
            "skipped": skipped,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": _FAIL if self.failed else _PASS,
            "coverage": self.coverage,
            "checks": [c.as_dict() for c in self.checks],
            "evidence": self.evidence,
            "judgment_required": {
                "visual_accept": None,
                "fit_band_ok": None,
                "note": "A machine cannot supply these. Look at the renders and decide.",
            },
        }


def load_model(model_path: Path):
    """Import a model module and return its parameters, its part and what it
    expects to measure.

    The module must expose ``part`` or a zero-argument ``build()``. Anything
    else is a contract the caller has to guess at, and guessing is what the
    hand-written scripts were doing.

    ``PARAMS`` is read *before* ``build()`` runs, because the pre-build stage
    has to be able to reject the numbers without paying for the geometry they
    describe.

    ``EXPECTED`` carries the template's own arithmetic for what the solid must
    measure. It is the one thing here a hand-written model may not invent: an
    expectation the author tuned until it passed measures nothing.
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
    expected = getattr(module, "EXPECTED", ())
    expected = tuple(expected) if isinstance(expected, (list, tuple)) else ()
    if hasattr(module, "part"):
        return params, module.part, expected
    if hasattr(module, "build"):
        return params, module.build, expected
    raise ValueError(f"{model_path.name} must define `part` or `build()`")


def load_part(model_path: Path) -> Any:
    """Back-compat shim for direct callers: just the part."""
    _, part, _ = load_model(model_path)
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


def _check_step(commission: Commission, report, verifying: bool) -> None:
    """Say when no STEP was written, rather than leaving it to be noticed.

    The trimesh path -- which every template uses -- exports STL only; STEP
    needs a CAD kernel. A multi-part run spotted that and wrote the same note
    into five `print_notes.md` by hand. A gap the receipt does not mention is a
    gap somebody has to find.
    """
    if verifying:
        return  # a verifier measures what was delivered; it exports nothing
    if report.step_path:
        commission.add(Check("step", "STEP exported alongside the STL", _PASS,
                             Path(report.step_path).name))
        return
    commission.add(Check(
        "step", "STEP exported alongside the STL", _SKIP,
        "no STEP was written: this part was built through the mesh path, which "
        "exports STL only",
        "Nothing is wrong with the geometry. But a downstream consumer wanting "
        "editable CAD will not find it, so either rebuild the part in the "
        "commissioned kernel backend or record in your handoff that this part "
        "ships as mesh only.",
    ))


def _check_receipt_location(commission: Commission, out_dir: Path, plan_path: Path | None) -> None:
    """The receipts are contracts, and contracts are found by exact path.

    Only when receipts are actually being written. A verifier passes
    `--no-receipts` and writes none, and forcing its `--out` to the project
    directory made it overwrite the designer's `commission.json` -- destroying
    the very file its own recomputation exists to be compared against.

    `team_tools/project.py` resolves each contract as `project_dir / name` with
    no recursive search, so receipts written to a subdirectory are invisible to
    `contracts validate` however correct their content. A run used `--out out`,
    produced a flawless candidate, and was rejected for a missing manifest that
    existed one directory down.
    """
    if plan_path is None:
        return
    project = plan_path.resolve().parent
    if out_dir.resolve() == project:
        return
    commission.add(Check(
        "receipt-location", "Receipts land where the contract gate looks", _FAIL,
        f"writing receipts to {out_dir} while the bound plan lives in {project}",
        "`contracts validate` resolves contracts as <project-dir>/<name> and does not "
        "search subdirectories, so artifact_manifest.json and candidate_readiness.md "
        "would be invisible there. Re-run with `--out` set to the project directory "
        "that holds the plan.",
    ))


def _check_solid(commission: Commission, report, plan: dict[str, Any]) -> None:
    """Watertight, and as many bodies as the plan says it should be.

    One, almost always: a second body means a boolean split the solid. But a box
    too big for the bed is delivered as segments a slicer separates, and hard-
    coding one made the gate reject a correct six-piece hive body for being six
    pieces. The count comes from the plan rather than from the mesh, because
    "however many came out" is not a check.
    """
    expected = plan.get("expected_bodies", 1)
    expected = int(expected) if isinstance(expected, int) and expected > 0 else 1
    ok = report.watertight and report.components == expected
    commission.add(Check(
        "solid", f"Watertight, {expected} bod{'y' if expected == 1 else 'ies'}",
        _PASS if ok else _FAIL,
        f"watertight={report.watertight}, components={report.components}, "
        f"plan expects {expected}",
        "" if ok else (
            "A non-watertight export cannot be printed or measured."
            if not report.watertight else
            f"The plan declares {expected} solid{'' if expected == 1 else 's'} and the export "
            f"has {report.components}. Either a boolean split the part, or the plan's "
            "`expected_bodies` does not describe what is being built."),
    ))


def _check_repair(commission: Commission, report) -> None:
    """How much repair the watertight verdict rested on.

    Measuring watertightness on the normalized mesh is correct: an STL is a
    vertex soup, and the raw parse calls every correctly-exported solid open.
    But it makes the gate's headline number a verdict about a repaired mesh, and
    a candidate that needed structural repair to reach it read identically to
    one that needed none. Merging coincident vertices is what the format
    requires; dropping faces is geometry that was not exportable, and it is the
    difference between a clean solid and one that only looks clean afterwards.

    The exporter's own comment said the log mattered "if the amount of merging is
    itself suspicious". Nothing had ever looked at it, and only the verifier's
    `dt.py integrity` read the raw parse at all -- which the DIRECT route, having
    no verifier, never runs.
    """
    mutation = report.mutation
    dropped = int(mutation.degenerate_faces_removed)
    if dropped == 0:
        commission.add(Check(
            "repair", "Export needed no structural repair", _PASS,
            f"{mutation.vertices_merged} coincident vertices merged, no faces dropped"))
        return
    commission.add(Check(
        "repair", "Export needed no structural repair", _FAIL,
        f"{dropped} degenerate faces removed to make the mesh measurable "
        f"({mutation.faces_before} faces exported, {mutation.faces_after} kept)",
        "Every check above ran on the repaired mesh, so its verdicts describe a "
        "solid that is not the one exported. Degenerate faces come from booleans "
        "on coincident surfaces -- offset the cutter past the face it crosses "
        "rather than landing exactly on it.",
    ))


def _check_seated(commission: Commission, mesh, plan: dict[str, Any],
                  rule: dict[str, Any], placement) -> None:
    """Does the part actually sit on the bed the plan declares?

    `bed_z_mm` and `bed_tolerance_mm` were required of every support rule and
    read by nothing. Bed contact is measured against the part's own lowest
    plane, so a part floating fifty millimetres up reports its full footprint as
    touching -- true of that plane, and not of the bed. The overhang screen
    catches it sideways, because the whole underside becomes unsupported, but
    the check named for the bed could not see it. This is the defect a verifier
    once found by hand and the docstring at the top of this file still cites.
    """
    bed_z = rule.get("bed_z_mm")
    tolerance = rule.get("bed_tolerance_mm")
    if bed_z is None or tolerance is None:
        return          # validate_plan refuses this before a build; nothing to add
    placed = mesh.copy()
    placed.apply_transform(placement.transform)
    lowest = float(placed.bounds[0][2])
    off = lowest - float(bed_z)
    rule_id = rule.get("id", "S-01")
    detail = (f"lowest point sits at z={lowest:.3f} against a declared bed at "
              f"{float(bed_z):.3f} (tolerance {float(tolerance)})")
    if abs(off) <= float(tolerance):
        commission.add(Check(f"seated-{rule_id}", "Part sits on the declared bed",
                             _PASS, detail))
        return
    commission.add(Check(
        f"seated-{rule_id}", "Part sits on the declared bed", _FAIL,
        f"{detail}: off by {off:+.3f} mm",
        "A part modelled off the bed prints with its whole underside unsupported, and "
        "every bed-contact number describes the plane it happens to start at rather than "
        "the bed. Seat the model at the plan's bed_z -- templates return parts already "
        "seated, so a hand-written model is the usual cause."
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
                             "`dt.py plan template`."))
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
        _check_seated(commission, mesh, plan, rule, placement)
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
    commission.evidence["reference_path"] = str(reference) if isinstance(reference, str) else None
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
    candidate_id: str = "candidate_01",
    plan_path: Path | None = None,
    writes_receipts: bool = True,
) -> Commission:
    """Build (if given a model), verify everything deterministic, write evidence."""
    out_dir.mkdir(parents=True, exist_ok=True)
    commission = Commission()

    source: Any = stl
    params: dict[str, Any] | None = None
    expected_features: tuple[dict[str, Any], ...] = ()
    if stl is not None and not Path(stl).is_file():
        # Without this the path falls through to the exporter's CAD-kernel
        # branch and the caller is told "No module named 'cadquery'" -- which
        # sends them installing a kernel to fix a typo.
        raise FileNotFoundError(f"no such STL: {stl}")
    if model is not None:
        if not Path(model).is_file():
            raise FileNotFoundError(f"no such model module: {model}")
        params, source, expected_features = load_model(model)

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
    #
    # Given an already-exported STL, hash and measure it *where it lies*. Writing
    # it to `out_dir` produced a byte-identical duplicate, which for a verifier
    # is a rule violation it then has to clean up -- the charter says never copy
    # a canonical STL into a verifier folder, and this was the thing copying it.
    from .exporter import export_and_hash
    # Named for the candidate, not a fixed `candidate_01`. A multi-part job
    # commissioning five parts into one directory had them overwrite each other.
    stem = Path(stl).with_suffix("") if stl is not None else out_dir / candidate_id
    report = export_and_hash(source, str(stem), also_step=stl is None)
    exported = Path(report.stl_path)
    mesh = as_mesh(str(exported))

    if writes_receipts:
        _check_receipt_location(commission, out_dir, plan_path)
    _check_step(commission, report, stl is not None)
    _check_solid(commission, report, plan)
    _check_repair(commission, report)
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

    # Declared features, measured against the solid. Everything above this point
    # is a scalar summary of the whole part -- bounding box, watertightness,
    # component count, downward-facing area -- and all four were bit-identical
    # across a correct clip, one missing its countersink, and one whose flange
    # had been slotted through. A part is not the numbers that summarise it.
    #
    # The plan's rows come first so a print engineer can add expectations the
    # template does not carry; neither source may be a dict the model author
    # maintains by hand beside the geometry it checks.
    feature_rows = list(expected_features) + list(plan.get("features") or [])
    if feature_rows:
        from . import features as _features
        for check in _features.check_features(
                mesh, feature_rows, bed_contact_mm2=placement.bed_contact_mm2):
            commission.add(check)
        commission.evidence["expected_features_source"] = (
            "template+plan" if expected_features and plan.get("features")
            else "template" if expected_features else "plan")
        # Recorded because a verifier has the STL and the plan, never model.py --
        # so a template's own expectations, which live in the model module, were
        # invisible to it and its recomputation came back missing exactly the
        # checks that catch a geometry regression. Writing the rows down does not
        # make them the designer's word against the verifier's: the rows are
        # inputs, the measurement is redone against the delivered bytes, and a
        # row edited to fit a defective part reads as an edited row.
        commission.evidence["features_checked"] = feature_rows

    # Unconditioned, unlike every check above it: nobody declared these heights
    # and no verdict is drawn from them. It belongs in the designer's own receipt
    # and not only the verifier's, because DIRECT has no verifier -- the charter
    # sent readers to a field that only the audit path produced, and a measured
    # run had to reach into the library itself to get it.
    try:
        from . import features as _features
        commission.evidence["slice_profile"] = _features.slice_profile(mesh)
    except Exception:  # noqa: BLE001 - evidence, never a gate
        commission.evidence["slice_profile"] = []

    commission.evidence.update({
        "export": {
            "stl_path": report.stl_path,
            "step_path": report.step_path,
            "file_sha256": report.file_sha256,
            "geometry_sha256": report.geometry_sha256,
            "watertight": report.watertight,
            "components": report.components,
            "triangle_count": report.triangle_count,
            "volume_mm3": round(report.volume_mm3, 4),
            "bbox_mm": {k: round(v, 4) for k, v in report.bbox_mm.items()},
        },
        # The placement's own figure. This used to come from a second call that
        # re-parsed the STL, re-ran `metrics.overhang_area` with the same
        # threshold and transform, and -- given a `--reference` -- repeated the
        # boolean intersection, the most expensive operation in the gate, then
        # discarded it. The two agreed to every decimal place either printed,
        # because they were the same arithmetic on the same inputs. Beside it
        # travelled a `datums` list that was empty on every run ever made: the
        # call never passed any.
        "overhang_mm2": round(placement.overhang_mm2, 4),
        "placement": placement.as_dict(),
        "placements_considered": [p.as_dict() for p in orient.sweep(mesh)],
        "edges": measured_edges,
        "measure": measure(mesh).__dict__,
        "stage_reached": "complete",
        "planned_placements": [p.as_dict() for p in placements],
    })

    if render:
        try:
            # Both views, because `visual_accept` is a question about the whole
            # part and a single X-section cannot answer it. Runs that produced
            # their own exterior sheet then had to hand-add a manifest row for
            # it; the gate produces it and lists it.
            import preview

            from .render import section_render
            renders = out_dir / "renders"
            renders.mkdir(exist_ok=True)
            # Through the middle of the part. The plane was pinned at the
            # origin, and a part seated on the bed by convention starts at
            # x=0 -- so the cut grazed its outermost face and the section
            # showed no internal structure at all, on every job.
            centre = mesh.bounds.mean(axis=0)
            section_render(str(exported), str(renders / "section_x.png"),
                           plane_origin=tuple(float(v) for v in centre),
                           plane_normal=(1, 0, 0))
            preview.render_multi_view(as_mesh(str(exported)), str(renders / "multi.png"),
                                      title="candidate")
            commission.evidence["renders"] = ["renders/section_x.png", "renders/multi.png"]
        except Exception as exc:  # noqa: BLE001 - a missing GL stack is not a design failure
            commission.add(Check(
                "render", "Renders for visual acceptance", _SKIP,
                f"renderer unavailable: {exc}",
                "Install the `visual` extra or run where a GL context exists. Visual "
                "acceptance cannot be signed off without looking at something.",
            ))
    else:
        # Not rendering at all leaves exactly as little to look at as a renderer
        # that failed, and the receipt has to say so either way. Keyed off the
        # SKIPPED check alone, `--no-render` produced no check, so the receipt
        # invited a visual verdict with no image in existence -- which is the
        # defect that made this block exist, arriving by a different door.
        commission.add(Check(
            "render", "Renders for visual acceptance", _SKIP,
            "not rendered: --no-render was passed",
            "Nothing was drawn, so there is nothing to accept visually. Re-run without "
            "--no-render before anyone signs off on the look.",
        ))

    (out_dir / "commission.json").write_text(
        json.dumps(commission.as_dict(), indent=2, default=str), encoding="utf-8")
    return commission


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dt.py commission",
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

    # The gate reads this plan and never checked it, so `plan check` was a
    # separate command somebody had to remember. Skip it and a rule missing
    # `model_to_printer_matrix` still reached `planned_placement`, which falls
    # back to `orient.best` and renames the placement -- so the run screened the
    # orientation the part would print best in, reported PASS, and said nothing
    # about the orientation the plan actually asked for. Answering a different
    # question quietly is worse than refusing.
    from .plan import validate_plan
    plan_problems = validate_plan(plan)
    if plan_problems:
        sys.stderr.write("commission: the plan cannot be gated against:\n")
        for problem in plan_problems:
            sys.stderr.write(f"  {problem}\n")
        sys.stderr.write("Fix the plan, or regenerate it with `dt.py plan template`.\n")
        return 2

    try:
        commission = run(model=args.model, stl=args.stl, out_dir=args.out, plan=plan,
                         reference=args.reference, render=not args.no_render,
                         candidate_id=args.candidate_id, plan_path=args.plan,
                         writes_receipts=not args.no_receipts)
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
