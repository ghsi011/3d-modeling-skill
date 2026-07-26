#!/usr/bin/env python3
"""Write the contracts a no-dispatch job needs, so nobody types them out.

A measured `DIRECT` run took 13.8 minutes with no dispatches at all -- the whole
job in one context -- and spent a large part of it hand-authoring 164 lines of
`job_state.md` and 82 of `dimensions.md`. Almost none of that was judgment. The
frontmatter is fully determined by the route, the job id and the clock; the
tables are the parameters that were already chosen; the completeness inventory
is what the template already declares it built.

So the same trade `dt.py report` makes on the other end of the pipeline: the
tool fills every mechanical field, and leaves each judgment as an explicit
`<!-- REQUIRED -->` that the file is not finished while it still contains. What
remains for the agent is the consequence-class rationale and anything the brief
left open -- which is the part a machine genuinely cannot supply.

`dimensions.md` written this way is a transcription, and says so in its own
body. That is honest for this route and only this route: `METROLOGY` is skipped
precisely when there is one source and nothing to reconcile. The moment a
photograph or a caliper reading enters the job, a metrologist writes this file
and this command has no business producing it.

    python <skill>/scripts/dt.py intake --job-id clip --template c_clip \
        --param bore_d=12.0 --param wall=3.0 ... \
        --profile DIRECT --risk R1_LOW_CONSEQUENCE \
        --updated-utc <iso8601> --out <project>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from . import templates as _templates
from .build import parse_param
from .templates import CATALOGUE

REQUIRED = "<!-- REQUIRED -->"

_RISK = ("R0_DECORATIVE", "R1_LOW_CONSEQUENCE", "R2_ENGINEERING_REVIEW",
         "R3_PROHIBITED_AUTONOMOUS_ACCEPTANCE")
_PROFILE = ("DIRECT", "FITTED", "FULL")


def _built(template: str, params: dict[str, Any]):
    """`CATALOGUE` documents the templates; it does not hold them.

    Membership is checked against it anyway, so an unknown name is refused by
    the catalogue that lists the real ones rather than by an AttributeError on
    some unrelated module member.
    """
    if template not in CATALOGUE:
        raise ValueError(f"no template named {template!r}; have {', '.join(sorted(CATALOGUE))}")
    return getattr(_templates, template)(**params)


def _brief_hash(brief: Path | None) -> str:
    """The brief's hash, because it is arithmetic rather than judgment.

    The sources table asked a reader to supply it, and a reader who types a
    hash by hand has bound the sheet to whatever they typed. Absent a brief
    path there is nothing honest to write, so the field stays demanded.
    """
    if brief is None or not brief.is_file():
        return REQUIRED
    from .receipts import sha256_file
    return f"`{sha256_file(brief)[:16]}`"


def _dimension_rows(params: dict[str, Any], stated: frozenset[str]) -> str:
    """Every parameter, as a row that says where the number came from.

    This used to write `stated in the brief / user / B` on every row, on the
    reasoning that user-stated numbers are the condition for this route. They
    are not: the condition is that nothing needs *measuring*. A brief asking for
    a clip over a 12 mm bundle states three numbers and a `c_clip` takes eight,
    so five rows claimed the user's authority for values the caller invented --
    at grade `B`, on a sheet whose whole purpose is provenance. One measured run
    caught it, and had to correct eight rows by hand.

    Unlisted means chosen, not stated, because that is the direction whose
    failure is safe. A caller who forgets `--stated` understates its own
    confidence and prompts scrutiny; the reverse manufactures a user statement
    that was never made, and nothing downstream can tell.

    `B` rather than `A` even when stated: nothing here was measured, and calling
    a transcription high-confidence would be the document flattering itself.
    """
    rows = []
    for index, (name, value) in enumerate(sorted(params.items()), start=1):
        if name in stated:
            rows.append(f"| D-{index:02d} | {name} | {value} | stated in the brief | "
                        f"user | B | as stated |")
        else:
            rows.append(f"| D-{index:02d} | {name} | {value} | chosen by design | "
                        f"designer | D | free to change |")
    return "\n".join(rows) or "| — | — | — | — | — | — | — |"


def _stated(raw: list[str]) -> frozenset[str]:
    """Accept `--stated a,b` and repeated `--stated a --stated b` alike."""
    return frozenset(name.strip() for text in raw for name in text.split(",") if name.strip())


def _completeness_rows(built) -> str:
    """One row per feature the template says it built.

    Not a summary of the geometry -- the template's own declaration of what it
    put there, which is the same list the gate measures. A feature that appears
    here and nowhere in `expected` is one nothing checks, and that is worth
    seeing in a table rather than discovering later.
    """
    rows = []
    for index, row in enumerate(built.expected, start=1):
        kind = row.get("kind", "?")
        value = (f"{row['area_mm2']:.2f} mm2" if "area_mm2" in row
                 else f"{row.get('head_d', row.get('d_mm', '?'))} mm")
        rows.append(f"| F-{index:02d} | {row.get('id', kind)} ({kind}) | {value} | "
                    f"template arithmetic | B | measured by the gate | yes |")
    for note in built.notes:
        rows.append(f"| F-{len(rows) + 1:02d} | {note[:88]} | see the brief | "
                    f"template note | B | {REQUIRED} | {REQUIRED} |")
    return "\n".join(rows) or f"| F-01 | {REQUIRED} | {REQUIRED} | | | | |"


def job_state(*, job_id: str, profile: str, risk: str, updated_utc: str,
              template: str, rationale: str | None = None,
              acceptance: str | None = None) -> str:
    """The judgments arrive as arguments, or not at all.

    They are still the caller's -- nothing here invents one. What changes is
    delivery: an agent that has already decided the consequence class pays two
    or three edit turns to type it into a file it just generated, and turns are
    what this route spends. Passing it in costs nothing and the field is filled
    by the same reasoning that would have filled it by hand.
    """
    dispatches = ("| — | none | — | — | — | not dispatched: this route runs no specialists |"
                  if profile == "DIRECT" else f"| D01 | {REQUIRED} | | | | queued |")
    return f"""---
contract: job-state
contract_version: 4
job_id: {job_id}
revision: 1
owner: orchestrator
mode: PIPELINE
profile: {profile}
risk_class: {risk}
state: INTAKE
backend: trimesh-template
active_candidate: none
freecad_owner: none
updated_utc: {updated_utc}
---

# Job state

## Route

**Consequence class: `{risk}`.** Rationale: {rationale or REQUIRED}

**Profile `{profile}`,** because nothing here needs measuring and the
`{template}` template covers the shape. {acceptance or REQUIRED} — say here what acceptance
depends on that you did not get to choose, and if the answer is nothing, say that.
{"" if profile != "DIRECT" else '''
Built and checked by the orchestrator; no independent fresh-context verification. That is
what this route is: nobody who did not build the part will look at it. The delivery repeats
this, and the receipt leaves `visual_accept` for a human who has actually seen a render.
'''}
## Bound inputs
| Contract/evidence | Revision/hash | Status |
|---|---|---|
| brief.md | as supplied | read |
| dimensions.md | r1 | written here, not by a metrologist |

## Gates
| Gate | Required receipt | Result | Evidence |
|---|---|---|---|
| consequence class | this section | PASS | the rationale above |
| route | this section | PASS | the profile above |
| plan | `dt.py plan check` | NOT RUN | — |
| candidate | `dt.py commission` exit 0 | NOT RUN | — |
| contracts | `contracts validate` exit 0 | NOT RUN | — |
| visual | a human looked at the renders | NOT RUN | — |

## Dispatches
| ID | Role/commission | Authorized inputs | Required output | Budget min | Status |
|---|---|---|---|---:|---|
{dispatches}

## Open user questions
| ID | Question | Blocks |
|---|---|---|
| — | none recorded | — |
"""


def dimensions(*, job_id: str, updated_utc: str, template: str, params: dict[str, Any],
               built, brief: Path | None = None,
               stated: frozenset[str] = frozenset()) -> str:
    return f"""---
contract: dimensions
contract_version: 4
job_id: {job_id}
revision: 1
owner: orchestrator
status: ACCEPTED
updated_utc: {updated_utc}
---

# Dimensions

Written by the orchestrator, not a metrologist, because this job carries no photograph, no
caliper reading and no real object. A metrologist reconciles sources; given one source it
can only transcribe. Every row below is stated by the user or chosen by the design, none is
image-derived or measured, and none is graded `A`.

## Frame
| Axis/datum | Definition | Source | Confidence |
|---|---|---|---|
| origin | the part is seated on the bed at z=0, the convention every template returns | template | A |
| +Z | build direction | print plan | A |

## Sources
| ID | Evidence path/URL | Variant | SHA-256 or access date | Authority/limits |
|---|---|---|---|---|
| S-01 | {brief.name if brief else "brief.md"} | as supplied | {_brief_hash(brief)} | the user's statement is the only authority here |

## Blind-build completeness
| Feature ID | Name/count/function | Datum value or bounded envelope | Source | Confidence | Candidate response | Ready |
|---|---|---|---|---|---|---|
{_completeness_rows(built)}

## Dimensions
| ID | Feature | Value/range | Datum/method | Source | Confidence | Tolerance/design response |
|---|---|---:|---|---|---|---|
{_dimension_rows(params, stated)}

## Open questions
| ID | Unknown | Risk | Approved bound/question | Blocks |
|---|---|---|---|---|
| — | none | — | — | — |

## Reference round trip
| Build ID/hash | Views/overlay | Verdict | Sheet revision required |
|---|---|---|---|
| — | no reference is built on this route: nothing is being recreated | — | no |

Every visible feature must appear in blind-build completeness above. The rows come from
`{template}`'s own declaration of what it built — if the brief names a feature that is not
in that list, the template does not build it, and nothing downstream will measure it.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--template", required=True)
    parser.add_argument("--param", action="append", default=[], metavar="NAME=VALUE")
    parser.add_argument("--stated", action="append", default=[], metavar="NAME[,NAME]",
                        help="comma-separated parameter names the brief actually "
                             "states. Everything else is recorded as chosen by the "
                             "design at confidence D. That is the safe direction: "
                             "forgetting it understates your own confidence, while "
                             "the reverse claims the user said something they did not.")
    parser.add_argument("--profile", default="DIRECT", choices=_PROFILE)
    parser.add_argument("--risk", default="R1_LOW_CONSEQUENCE", choices=_RISK)
    parser.add_argument("--updated-utc", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--rationale", help="why this consequence class; yours to decide, "
                                            "passed in so you do not spend turns typing it "
                                            "into a file this just wrote")
    parser.add_argument("--acceptance", help="what acceptance depends on that you did not "
                                             "get to choose -- 'nothing' is a real answer")
    parser.add_argument("--brief", type=Path,
                        help="the brief this job was written from; hashed into the sources "
                             "table, which otherwise asks a reader to type a hash by hand")
    args = parser.parse_args(argv)

    if args.risk == "R3_PROHIBITED_AUTONOMOUS_ACCEPTANCE":
        sys.stderr.write(
            "intake: an R3 job never reaches delivery, so scaffolding its contracts would "
            "only make the prohibited path smoother. Handle it by the escalation gate.\n")
        return 2

    try:
        params = dict(parse_param(text) for text in args.param)
        built = _built(args.template, params)
    except (ValueError, TypeError) as exc:
        sys.stderr.write(f"intake: {exc}\n")
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, text in (
        ("job_state.md", job_state(job_id=args.job_id, profile=args.profile,
                                   risk=args.risk, updated_utc=args.updated_utc,
                                   template=args.template, rationale=args.rationale,
                                   acceptance=args.acceptance)),
        ("dimensions.md", dimensions(job_id=args.job_id, updated_utc=args.updated_utc,
                                     template=args.template, params=params, built=built,
                                     brief=args.brief, stated=_stated(args.stated))),
    ):
        path = args.out / name
        if path.exists():
            sys.stderr.write(f"intake: {path} already exists; refusing to overwrite a "
                             f"contract somebody may have edited\n")
            return 1
        path.write_text(text, encoding="utf-8")
        written.append(path)

    for path in written:
        remaining = path.read_text(encoding="utf-8").count(REQUIRED)
        sys.stdout.write(f"{path}  ({remaining} judgment fields to answer)\n")
    sys.stdout.write("Neither file is finished while it still contains "
                     f"{REQUIRED} -- those are the parts no tool can supply.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
