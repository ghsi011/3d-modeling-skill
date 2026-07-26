#!/usr/bin/env python3
"""The whole no-dispatch route in one call.

Measured: the deterministic work of a `DIRECT` job is 5.1 seconds, and a real
run of the same job took 13.5 minutes. The gap is not computation and it is not
dispatch -- this route dispatches nobody. It is turns. Every command is a round
trip costing 8 to 47 seconds of inference before the shell is even reached, so
five commands cost minutes to deliver five seconds of work.

So they become one. `intake`, `plan template`, `build`, `commission` and the
`screen` question always run in that order with the same job id, the same clock
and the same parameters; there is no branch between them a caller could usefully
take. What was five decisions is one.

It stops at the first failure and hands back that step's own message, because a
chain that continues past a broken link produces receipts describing a part that
was never built. `plan check` is deliberately absent: `commission` validates the
plan it is handed and refuses an ungateable one, so running it separately buys a
failure one second earlier at the cost of a whole turn.

    python <skill>/scripts/dt.py direct --job-id clip --template c_clip \
        --param bore_d=12.0 ... --bbox 40 22 14 \
        --risk R1_LOW_CONSEQUENCE --updated-utc <iso8601> --out <project>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import build as build_module
from . import commission as commission_module
from . import intake as intake_module
from . import plan as plan_module
from . import screen as screen_module


def _params(raw: list[str]) -> dict[str, Any]:
    return dict(build_module.parse_param(text) for text in raw)


def _instantiate(template: str, params: dict[str, Any]):
    from . import templates as templates_module
    return getattr(templates_module, template)(**params)


def run(*, job_id: str, template: str, raw_params: list[str], bbox: tuple[float, float, float],
        risk: str, updated_utc: str, out: Path, material: str | None,
        rationale: str | None = None, acceptance: str | None = None,
        brief: Path | None = None, bodies: int | None = None,
        render: bool = True) -> tuple[int, list[str]]:
    """Every step, in order, stopping at the first that fails."""
    log: list[str] = []
    out.mkdir(parents=True, exist_ok=True)

    # How many solids the part is meant to be. A segmented box knows -- it is
    # ceil(outer/usable) per axis, the same arithmetic that decided where to cut
    # -- and a caller cannot know it without building first, which is exactly the
    # trap the emergent bounding box already set once. Reading it from the
    # template is not the part certifying itself: it is derived from the inner
    # size, the wall and the bed, and is untouched by whatever the boolean
    # actually produced. An explicit --bodies still wins, and then it is a claim
    # the gate will hold the part to.
    if bodies is None:
        try:
            built = _instantiate(template, _params(raw_params))
            bodies = int(built.params.get("segment_count", 1))
        except Exception:  # noqa: BLE001 - build failures are reported by build itself
            bodies = 1

    intake_argv = [
        "--job-id", job_id, "--template", template, *_flatten(raw_params),
        "--profile", "DIRECT", "--risk", risk,
        "--updated-utc", updated_utc, "--out", str(out)]
    if rationale:
        intake_argv += ["--rationale", rationale]
    if acceptance:
        intake_argv += ["--acceptance", acceptance]
    if brief:
        intake_argv += ["--brief", str(brief)]
    code = intake_module.main(intake_argv)
    if code != 0:
        return code, log + ["intake failed; nothing downstream ran"]
    log.append("intake      job_state.md, dimensions.md")

    plan_path = out / "print_plan_checks.json"
    plan_argv = ["template", "--bbox", *(str(v) for v in bbox), "--job-id", job_id,
                 "--updated-utc", updated_utc, "--out", str(plan_path)]
    if material:
        plan_argv += ["--material", material]
    if bodies and bodies != 1:
        plan_argv += ["--bodies", str(bodies)]
    if plan_module.main(plan_argv) != 0:
        return 1, log + ["plan failed; no candidate was built"]
    log.append(f"plan        {plan_path.name}")

    model = out / "model.py"
    if build_module.main(["--template", template, *_flatten(raw_params),
                          "--out", str(model)]) != 0:
        return 1, log + ["build failed; the template rejected these parameters"]
    log.append("build       model.py")

    gate = ["--model", str(model), "--plan", str(plan_path), "--out", str(out),
            "--job-id", job_id, "--updated-utc", updated_utc]
    if not render:
        gate.append("--no-render")
    code = commission_module.main(gate)
    log.append(f"commission  {'PASS' if code == 0 else 'FAIL'}")

    # The screen question, from artefacts that now exist. It was a separate
    # command and a separate turn, and it takes no decision from the caller: it
    # reads the declared inventory this call just wrote and states the one
    # question no check here can ask. A turn costs 8 to 47 seconds and the
    # question costs milliseconds, so the only thing the separation bought was
    # a chance to skip the look entirely by forgetting the command.
    #
    # Run even when the gate fails. A failing part is exactly the one worth
    # looking at, and the renders are already on disk.
    try:
        result = screen_module.bundle(out, out / "screen")
        log.append(f"screen      {len(result['images'])} renders, "
                   f"{result['declared_features']} declared features")
    except (OSError, ValueError) as exc:
        log.append(f"screen      unavailable: {exc}")
    return code, log


def _flatten(raw_params: list[str]) -> list[str]:
    out: list[str] = []
    for text in raw_params:
        out += ["--param", text]
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--template", required=True)
    parser.add_argument("--param", action="append", default=[], metavar="NAME=VALUE")
    parser.add_argument("--bbox", nargs=3, type=float, required=True, metavar=("X", "Y", "Z"),
                        help="the envelope the part must come out at, from the brief")
    parser.add_argument("--risk", default="R1_LOW_CONSEQUENCE",
                        choices=("R0_DECORATIVE", "R1_LOW_CONSEQUENCE"),
                        help="R2 and above do not take this route: they need a named "
                             "reviewer and independent verification")
    parser.add_argument("--material", help="overrides the plan template's default")
    parser.add_argument("--rationale", help="why this consequence class; yours to decide")
    parser.add_argument("--acceptance", help="what acceptance depends on that you did not "
                                             "get to choose -- 'nothing' is a real answer")
    parser.add_argument("--brief", type=Path, help="hashed into the dimensions sources table")
    parser.add_argument("--bodies", type=int, default=None,
                        help="separate solids the part is meant to be. Omit it: a segmented "
                             "template already knows, from the same arithmetic that decided "
                             "where to cut. Pass it to make a claim the gate holds you to.")
    parser.add_argument("--updated-utc", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--no-render", action="store_true",
                        help="skip the renders -- and with them the only unconditioned "
                             "evidence this route has")
    args = parser.parse_args(argv)

    try:
        _params(args.param)          # fail on a bad literal before anything is written
    except ValueError as exc:
        sys.stderr.write(f"direct: {exc}\n")
        return 2

    code, log = run(job_id=args.job_id, template=args.template, raw_params=args.param,
                    bbox=tuple(args.bbox), risk=args.risk, updated_utc=args.updated_utc,
                    out=args.out, material=args.material, rationale=args.rationale,
                    acceptance=args.acceptance, brief=args.brief, bodies=args.bodies,
                    render=not args.no_render)

    sys.stderr.write("\n".join(f"  {line}" for line in log) + "\n")
    if code != 0:
        sys.stderr.write("direct: the chain stopped above. Fix that step and re-run.\n")
        return code

    receipt = args.out / "commission.json"
    payload = json.loads(receipt.read_text(encoding="utf-8")) if receipt.is_file() else {}
    coverage = payload.get("coverage") or {}
    # Counted, not asserted. A closing line that demands the required fields be
    # answered when there are none left reads as boilerplate, and boilerplate is
    # what gets skimmed past on the run where there really is one.
    outstanding = sum(
        path.read_text(encoding="utf-8").count(intake_module.REQUIRED)
        for path in args.out.glob("*.md") if path.is_file())
    sys.stderr.write(
        f"\n{coverage.get('ran', '?')} of {coverage.get('declared', '?')} checks ran"
        + (f"; {', '.join(coverage['skipped'])} did not" if coverage.get("skipped") else "")
        # ASCII only. This is the last thing a successful run prints, and a
        # Windows console on a legacy code page raises UnicodeEncodeError on an
        # em-dash -- which would turn a finished, passing job into a traceback
        # at the final line.
        + ".\nStill yours, and it is one turn: read the renders and "
        f"{args.out / 'screen' / 'question.md'}\ntogether. Nothing above was measured that "
        "nobody declared, and that file is the\nquestion no check here can ask. Then answer "
        "`visual_accept` and `fit_band_ok`"
        + (f",\nand the {outstanding} remaining <!-- REQUIRED --> field"
           f"{'s' if outstanding != 1 else ''} in the contracts" if outstanding else "")
        + ".\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
