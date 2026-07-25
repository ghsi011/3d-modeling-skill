"""CLI for designer_toolkit — call the deterministic checks from a shell instead
of authoring Python. Every subcommand prints JSON to stdout.

    python -m designer_toolkit measure body.stl
    python -m designer_toolkit overhang body.stl --threshold -0.73
    python -m designer_toolkit datums body.stl --z 1.0
    python -m designer_toolkit interference body.stl ref.stl
    python -m designer_toolkit sweep body.stl ref.stl --travels 5,15,25,35
    python -m designer_toolkit coupon --plan plan.json --out coupon.stl
    python -m designer_toolkit finalize body.stl --plan plan.json
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from . import bundle, coupon, exporter, fit, metrics


def _floats(csv: str):
    return [float(x) for x in csv.split(",") if x.strip()]


def _cmd_measure(a):
    return asdict(metrics.measure(a.stl))


def _cmd_overhang(a):
    return {"overhang_mm2": metrics.overhang_area(
        a.stl, threshold=a.threshold, bed_tolerance=a.bed_tolerance)}


def _cmd_datums(a):
    normal = _floats(a.normal) if a.normal else (0, 0, 1)
    feats = metrics.datum_features(a.stl, (0, 0, a.z), normal)
    return {"features": [bundle.asdict_feature(f) for f in feats]}


def _cmd_interference(a):
    return {"interference_mm3": fit.interference(a.part, a.ref)}


def _cmd_sweep(a):
    axis = _floats(a.axis) if a.axis else (0, 0, -1)
    steps = fit.insertion_sweep(a.part, a.ref, _floats(a.travels), axis=axis)
    return {"steps": [asdict(s) for s in steps]}


def _cmd_export(a):
    return {k: v for k, v in asdict(exporter.export_and_hash(a.stl, a.out or a.stl)).items()
            if k != "integrity"}


def _cmd_coupon(a):
    plan = json.loads(open(a.plan, encoding="utf-8").read())
    ifaces = plan["interfaces"] if isinstance(plan, dict) else plan
    path, legend = coupon.fit_coupon(ifaces, a.out)
    return {"stl": path, "legend": coupon.legend_to_rows(legend)}


def _cmd_finalize(a):
    plan = json.loads(open(a.plan, encoding="utf-8").read()) if a.plan else {}
    return bundle.finalize(
        a.stl, plan.get("out_stem", a.stl.rsplit(".", 1)[0]),
        datums=plan.get("datums", ()), reference=plan.get("reference"),
        insertion=plan.get("insertion"),
        orientation_transform=plan.get("orientation_transform"),
        # Left as None when the plan is silent, so finalize records the fallback
        # as "toolkit_default" instead of it looking like a declared plan value.
        overhang_threshold=plan.get("overhang_threshold"),
        also_step=False)


def main(argv=None):
    p = argparse.ArgumentParser(prog="designer_toolkit")
    sub = p.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("measure")
    m.add_argument("stl")
    m.set_defaults(fn=_cmd_measure)

    o = sub.add_parser("overhang")
    o.add_argument("stl")
    o.add_argument("--threshold", type=float, default=metrics.DEFAULT_DOWNWARD_NORMAL_Z_MAX)
    o.add_argument("--bed-tolerance", dest="bed_tolerance", type=float,
                   default=metrics.DEFAULT_BED_TOLERANCE_MM)
    o.set_defaults(fn=_cmd_overhang)

    d = sub.add_parser("datums")
    d.add_argument("stl")
    d.add_argument("--z", type=float, required=True)
    d.add_argument("--normal", default="")
    d.set_defaults(fn=_cmd_datums)

    i = sub.add_parser("interference")
    i.add_argument("part")
    i.add_argument("ref")
    i.set_defaults(fn=_cmd_interference)

    s = sub.add_parser("sweep")
    s.add_argument("part")
    s.add_argument("ref")
    s.add_argument("--travels", required=True)
    s.add_argument("--axis", default="")
    s.set_defaults(fn=_cmd_sweep)

    e = sub.add_parser("export")
    e.add_argument("stl")
    e.add_argument("--out", default="")
    e.set_defaults(fn=_cmd_export)

    c = sub.add_parser("coupon")
    c.add_argument("--plan", required=True)
    c.add_argument("--out", required=True)
    c.set_defaults(fn=_cmd_coupon)

    f = sub.add_parser("finalize")
    f.add_argument("stl")
    f.add_argument("--plan", default="")
    f.set_defaults(fn=_cmd_finalize)

    # `commission` owns its own exit code -- a failing candidate must not be
    # handed on -- so it is dispatched before the shared print-and-return path.
    c2 = sub.add_parser(
        "commission",
        help="build, run every deterministic check, write the evidence, and exit "
             "non-zero if anything failed",
    )
    source = c2.add_mutually_exclusive_group(required=True)
    source.add_argument("--model", type=Path, help="module defining `part` or `build()`")
    source.add_argument("--stl", type=Path, help="an already-exported STL")
    c2.add_argument("--plan", type=Path, required=True)
    c2.add_argument("--out", type=Path, required=True)
    c2.add_argument("--reference")
    c2.add_argument("--no-render", action="store_true")
    c2.set_defaults(fn=None, command="commission")

    args = p.parse_args(argv)
    if getattr(args, "command", None) == "commission":
        from .commission import main as commission_main
        argv_out = ["--plan", str(args.plan), "--out", str(args.out)]
        argv_out += ["--model", str(args.model)] if args.model else ["--stl", str(args.stl)]
        if args.reference:
            argv_out += ["--reference", args.reference]
        if args.no_render:
            argv_out.append("--no-render")
        raise SystemExit(commission_main(argv_out))
    print(json.dumps(args.fn(args), indent=2))


if __name__ == "__main__":
    main()
