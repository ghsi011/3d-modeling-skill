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
import importlib.util
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ._bootstrap import as_mesh  # noqa: F401  (also puts scripts/ on sys.path)

from . import edges, fit, orient  # noqa: E402
from .bundle import finalize  # noqa: E402
from .metrics import BARE_45_DEG, measure  # noqa: E402

_PASS, _FAIL, _SKIP = "PASS", "FAIL", "SKIPPED"


@dataclass
class Check:
    """One deterministic verdict, with the action to take when it fails."""

    id: str
    title: str
    result: str
    detail: str
    action: str = ""

    def as_dict(self) -> dict[str, Any]:
        out = {"id": self.id, "title": self.title, "result": self.result, "detail": self.detail}
        if self.action:
            out["next_action"] = self.action
        return out


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


def load_part(model_path: Path) -> Any:
    """Import a model module and take its part.

    The module must expose ``part`` or a zero-argument ``build()``. Anything
    else is a contract the caller has to guess at, and guessing is what the
    hand-written scripts were doing.
    """
    spec = importlib.util.spec_from_file_location(model_path.stem, model_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot import {model_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if hasattr(module, "part"):
        return module.part
    if hasattr(module, "build"):
        return module.build()
    raise ValueError(f"{model_path.name} must define `part` or `build()`")


def _plan_support_rule(plan: dict[str, Any]) -> dict[str, Any] | None:
    rules = plan.get("support_rules") or []
    return rules[0] if rules else None


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
            "envelope", "Overall size vs plan", _SKIP,
            "the plan declares no expected_bbox_mm",
            "Declare expected_bbox_mm {x,y,z} and tolerance_mm in the plan. Without "
            "it nothing checks the part's own size, and a part can pass every other "
            "gate while being wholly the wrong size.",
        ))
        return
    tolerance = float(plan.get("bbox_tolerance_mm", 1.0))
    worst_axis, worst = "", 0.0
    for axis in ("x", "y", "z"):
        if axis in expected:
            delta = report.bbox_mm[axis] - float(expected[axis])
            if abs(delta) > abs(worst):
                worst_axis, worst = axis, delta
    ok = abs(worst) <= tolerance
    commission.add(Check(
        "envelope", "Overall size vs plan",
        _PASS if ok else _FAIL,
        f"worst axis {worst_axis or 'n/a'} off by {worst:+.2f} mm (tolerance {tolerance} mm)",
        "" if ok else f"The part is {worst:+.2f} mm out on {worst_axis}. Either the "
                      "geometry is wrong or the plan's expected_bbox_mm is. Resolve which "
                      "before proceeding -- do not widen the tolerance to fit the part.",
    ))


def _check_support(commission: Commission, mesh, plan: dict[str, Any], placement) -> None:
    rule = _plan_support_rule(plan)
    threshold = float(rule.get("downward_normal_z_max", BARE_45_DEG)) if rule else BARE_45_DEG
    disposition = (rule or {}).get("disposition", "SELF_SUPPORT_REQUIRED")
    ceiling = float((rule or {}).get("max_out_of_limit_area_mm2", 0.0))

    # The contract says SELF_SUPPORT_REQUIRED means zero out-of-limit area, and
    # the gate accepted any non-negative ceiling. Two archived runs declared
    # SELF_SUPPORT_REQUIRED with ceilings of 1850 and 2150 mm2 and passed.
    if disposition == "SELF_SUPPORT_REQUIRED" and ceiling > 0:
        commission.add(Check(
            "support-ceiling", "Support ceiling matches disposition", _FAIL,
            f"SELF_SUPPORT_REQUIRED declared with a ceiling of {ceiling} mm2",
            "SELF_SUPPORT_REQUIRED means zero out-of-limit area. Either reorient until "
            "it is zero, or declare SUPPORT_ALLOWED and say which faces take support.",
        ))
        ceiling = 0.0

    from .metrics import overhang_area
    area = overhang_area(mesh, threshold=threshold, transform=placement.transform)
    ok = area <= ceiling
    commission.add(Check(
        "support", "Downward-facing area within the plan limit",
        _PASS if ok else _FAIL,
        f"{area:.2f} mm2 past {threshold} in the '{placement.name}' placement "
        f"(limit {ceiling} mm2)",
        "" if ok else f"Best of {len(orient._CANDIDATES)} placements still leaves "
                      f"{area:.2f} mm2. Reorient, add a chamfer to the offending face, "
                      "or declare SUPPORT_ALLOWED with a contact class.",
    ))


def _check_interfaces(commission: Commission, stl: Path, plan: dict[str, Any], reference) -> None:
    interfaces = plan.get("interfaces") or []
    if not interfaces or reference is None:
        commission.add(Check("fit", "Declared interface fit", _SKIP,
                             "no interfaces declared, or no mating reference supplied"))
        return
    volume = fit.interference(str(stl), reference)
    bands = [(float(i.get("min_mm", 0.0)), float(i.get("max_mm", 0.0))) for i in interfaces]
    low = min(b[0] for b in bands)
    high = max(b[1] for b in bands)
    ok = low <= volume <= high or (high <= 0 and volume <= 1e-2)
    commission.add(Check(
        "fit", "Declared interface fit",
        _PASS if ok else _FAIL,
        f"seated interference {volume:.4f} mm3 against a declared band [{low}, {high}]",
        "" if ok else "Seated interference is outside every declared band. Interference "
                      "below ~0.01 mm3 is tessellation noise and is already zero -- do not "
                      "tune clearance against it; find the feature that actually overlaps.",
    ))


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
    if model is not None:
        source = load_part(model)

    # Export first: every measurement below is on the re-imported mesh, never on
    # the in-memory model, because that is what actually ships.
    from .exporter import export_and_hash
    report = export_and_hash(source, str(out_dir / "candidate_01"), also_step=True)
    exported = Path(report.stl_path)
    mesh = as_mesh(str(exported))

    _check_solid(commission, report)
    _check_envelope(commission, report, plan)

    placement = orient.best(mesh)
    _check_support(commission, mesh, plan, placement)
    _check_interfaces(commission, exported, plan, reference)

    measured_edges = {}
    for edge in plan.get("edges") or []:
        corner = edge.get("corner_xy")
        if corner is None:
            continue
        result = edges.measure_edge(
            mesh, tuple(corner),
            section_origin=tuple(edge.get("section_origin", (0, 0, 0))),
            window_mm=float(edge.get("window_mm", 4.0)),
        )
        measured_edges[edge["id"]] = result.as_dict()
        nominal = edge.get("min_radius_mm")
        if nominal is not None and result.value_mm is not None:
            ok = result.value_mm + 1e-9 >= float(nominal)
            commission.add(Check(
                f"edge-{edge['id']}", f"Edge {edge['id']} treatment",
                _PASS if ok else _FAIL,
                f"measured {result.kind} {result.value_mm:.3f} mm against a "
                f"{nominal} mm minimum",
                "" if ok else "Increase the radius or declare the edge sharp with a reason. "
                              "Do not widen the band to fit the measurement.",
            ))

    bundle = finalize(
        str(exported), str(out_dir / "candidate_01"),
        reference=reference,
        orientation_transform=placement.transform,
        overhang_threshold=float((_plan_support_rule(plan) or {}).get(
            "downward_normal_z_max", BARE_45_DEG)),
        also_step=False,
    )

    commission.evidence = {
        "export": bundle["export"],
        "placement": placement.as_dict(),
        "placements_considered": [p.as_dict() for p in orient.sweep(mesh)],
        "edges": measured_edges,
        "measure": measure(mesh).__dict__,
    }

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
    args = parser.parse_args(argv)

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    commission = run(model=args.model, stl=args.stl, out_dir=args.out, plan=plan,
                     reference=args.reference, render=not args.no_render)

    payload = commission.as_dict()
    sys.stdout.write(json.dumps(payload, indent=2, default=str) + "\n")
    for check in commission.failed:
        sys.stderr.write(f"FAIL {check.id}: {check.detail}\n      -> {check.action}\n")
    return 1 if commission.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
