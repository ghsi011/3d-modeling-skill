"""CLI for designer_toolkit.

    uv run --project <skill> --frozen python <skill>/scripts/dt.py doctor        # works from any directory
    uv run --project <skill> --frozen python <skill>/scripts/dt.py commission --model model.py --plan plan.json \
      --out . --job-id <job> --updated-utc <iso8601>
    uv run --project <skill> --frozen python <skill>/scripts/dt.py coupon --plan plan.json --out coupon.stl

No verb here is a measurement you assemble yourself. `commission` is the gate:
it takes a model and a plan and returns every deterministic verdict at once.
The rest set a job up, read one back,
or answer a question the gate cannot -- they do not decompose the gate.

That is the shape because the opposite was tried. Seven verbs -- `measure`,
`overhang`, `datums`, `interference`, `sweep`, `export`, `finalize` -- offered
one deterministic check each, and three measured runs read that menu, did what
it implied, and hand-wrote a 130-280 line verification script. Not one of the
three ran the gate. A surface that offers the pieces gets them assembled by
hand, and a hand-assembled instrument is how one run widened its acceptance
bands until its own sampler agreed with it.

The library functions are all still importable for the rare case that needs
one. What is gone is the invitation.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import coupon


def _cmd_coupon(a):
    plan = json.loads(open(a.plan, encoding="utf-8").read())
    ifaces = plan["interfaces"] if isinstance(plan, dict) else plan
    path, legend = coupon.fit_coupon(ifaces, a.out)
    return {"stl": path, "legend": coupon.legend_to_rows(legend)}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    # `commission` owns its own flags and its own exit code -- a failing
    # candidate must not be handed on. Dispatch before argparse sees anything,
    # so its arguments are forwarded verbatim rather than re-declared here.
    # There is then one definition of them, and this wrapper cannot drift out of
    # step with the gate it fronts.
    if argv and argv[0] == "commission":
        from .commission import main as commission_main
        raise SystemExit(commission_main(argv[1:]))
    if argv and argv[0] == "doctor":
        from .doctor import main as doctor_main
        raise SystemExit(doctor_main(argv[1:]))
    if argv and argv[0] == "templates":
        from .templates import catalogue_lines
        for line in catalogue_lines():
            print(line)
        raise SystemExit(0)
    if argv and argv[0] == "probe":
        from .probe import main as probe_main
        raise SystemExit(probe_main(argv[1:]))
    if argv and argv[0] == "validate":
        # `uv run --project <skill> --frozen python -m team_tools.contracts` resolves with the skill project selected
        # directory on sys.path. From the repo you are already there; from an
        # installed bundle you are not, and the charter's command failed until a
        # reader worked out it needed PYTHONPATH. `dt.py` puts its own directory
        # on the path, so routing through it works from anywhere -- which is the
        # whole reason the launcher exists.
        from team_tools.contracts import main as contracts_main
        raise SystemExit(contracts_main(["validate", *argv[1:]]))
    if argv and argv[0] == "status":
        from team_tools.contracts import main as contracts_main
        raise SystemExit(contracts_main(["status", *argv[1:]]))
    if argv and argv[0] == "screen":
        from .screen import main as screen_main
        raise SystemExit(screen_main(argv[1:]))
    if argv and argv[0] == "audit":
        from .audit import main as audit_main
        raise SystemExit(audit_main(argv[1:]))
    if argv and argv[0] == "intake":
        from .intake import main as intake_main
        raise SystemExit(intake_main(argv[1:]))
    if argv and argv[0] == "build":
        from .build import main as build_main
        raise SystemExit(build_main(argv[1:]))
    if argv and argv[0] == "crop":
        import crop_evidence
        raise SystemExit(crop_evidence.main(argv[1:]))
    if argv and argv[0] == "integrity":
        from .integrity import main as integrity_main
        raise SystemExit(integrity_main(argv[1:]))
    if argv and argv[0] == "report":
        from .report import main as report_main
        raise SystemExit(report_main(argv[1:]))
    if argv and argv[0] == "plan":
        from .plan import main as plan_main
        raise SystemExit(plan_main(argv[1:]))

    parser = argparse.ArgumentParser(
        prog="designer_toolkit",
        epilog="commission (--model M | --stl S) --plan P --out D --job-id J "
               "--updated-utc T : the deterministic gate; run `... commission --help`.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("commission", add_help=False,
                   help="build, run every deterministic check, write the receipts, "
                        "and exit non-zero if anything failed")
    sub.add_parser("doctor", add_help=False,
                   help="what this interpreter can do: backends, extras, and what "
                        "each missing one costs")
    sub.add_parser("crop", add_help=False,
                   help="crop | contact-sheet | rotations -- zoom a render or a photo "
                        "without hand-rolling it, capped so the pixels are not wasted")
    sub.add_parser("integrity", add_help=False,
                   help="raw-parse integrity of a delivered STL: the one acceptance "
                        "read the gate cannot do for you")
    sub.add_parser("report", add_help=False,
                   help="draft verification_report.md from the verifier's own "
                        "recomputation, leaving every judgment blank")
    sub.add_parser("templates", add_help=False,
                   help="the parametric starting points and the shapes they cover")
    sub.add_parser("probe", add_help=False,
                   help="ask the delivered solid a question -- section area, a hole's "
                        "size and position, the whole slice profile")
    sub.add_parser("validate", add_help=False,
                   help="contract validation, reachable from anywhere: "
                        "validate <project> --require all")
    sub.add_parser("status", add_help=False,
                   help="stale and invalidated bindings across a project's contracts")
    sub.add_parser("screen", add_help=False,
                   help="the one question no check can ask: what is here that "
                        "nobody declared")
    sub.add_parser("audit", add_help=False,
                   help="everything a verifier can settle mechanically, in one call: "
                        "binding, raw parse, recomputation, contracts")
    sub.add_parser("intake", add_help=False,
                   help="job_state.md and dimensions.md for a no-dispatch job, with "
                        "every judgment left blank")
    sub.add_parser("build", add_help=False,
                   help="write model.py for a template-covered part, with the "
                        "parameters checked by building it once")
    sub.add_parser("plan", add_help=False,
                   help="template | check -- the built-in DIRECT plan, and the "
                        "gate that rejects an unbuildable one before a build")

    c = sub.add_parser("coupon", help="multi-lane fit coupon from the plan's interfaces")
    c.add_argument("--plan", required=True)
    c.add_argument("--out", required=True)
    c.set_defaults(fn=_cmd_coupon)

    args = parser.parse_args(argv)
    print(json.dumps(args.fn(args), indent=2))


if __name__ == "__main__":
    main()
