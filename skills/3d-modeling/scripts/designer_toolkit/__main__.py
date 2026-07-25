"""CLI for designer_toolkit.

    python -m designer_toolkit commission --model model.py --plan plan.json --out .              --job-id <job> --updated-utc <iso8601>
    python -m designer_toolkit coupon --plan plan.json --out coupon.stl

Two subcommands, and that is deliberate. There used to be seven more --
`measure`, `overhang`, `datums`, `interference`, `sweep`, `export`, `finalize`
-- one per deterministic check, each a separate process paying ~3 s of
interpreter and CAD-library startup, each re-parsing the same STL, and each
costing an agent round trip that had to be repeated after every edit.

They also taught the wrong thing. Three measured runs read the toolkit docs,
found a menu of individual verbs plus a `finalize` that takes its datums,
orientation and thresholds from the caller, and did what the menu implied:
hand-wrote a 130-280 line verification script. Not one of the three ran the
gate. A tool surface that offers the pieces will get the pieces assembled by
hand, and a hand-assembled instrument is how one run widened its acceptance
bands to fit its own sampler.

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

    parser = argparse.ArgumentParser(
        prog="designer_toolkit",
        epilog="commission (--model M | --stl S) --plan P --out D --job-id J "
               "--updated-utc T : the deterministic gate; run `... commission --help`.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("commission", add_help=False,
                   help="build, run every deterministic check, write the receipts, "
                        "and exit non-zero if anything failed")

    c = sub.add_parser("coupon", help="multi-lane fit coupon from the plan's interfaces")
    c.add_argument("--plan", required=True)
    c.add_argument("--out", required=True)
    c.set_defaults(fn=_cmd_coupon)

    args = parser.parse_args(argv)
    print(json.dumps(args.fn(args), indent=2))


if __name__ == "__main__":
    main()
