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

    uv run --project <skill> --frozen python <skill>/scripts/dt.py intake --job-id clip --template c_clip \
        --param bore_d=12.0 --param wall=3.0 ... \
        --profile DIRECT --consequence INCONSEQUENTIAL \
        --updated-utc <iso8601> --out <project>
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from . import templates as _templates
from .build import parse_param
from .templates import CATALOGUE

REQUIRED = "<!-- REQUIRED -->"
OFF_TEMPLATE = "none"

_CONSEQUENCE = ("INCONSEQUENTIAL", "CONSEQUENTIAL")
_PROFILE = ("DIRECT", "FITTED", "FULL")
_IMPORTED_BACKENDS = {
    ".stl": "trimesh-manifold",
    ".step": "build123d",
    ".stp": "build123d",
}


def _built(template: str, params: dict[str, Any]):
    """`CATALOGUE` documents the templates; it does not hold them.

    Membership is checked against it anyway, so an unknown name is refused by
    the catalogue that lists the real ones rather than by an AttributeError on
    some unrelated module member.
    """
    if template == OFF_TEMPLATE:
        return None
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


def _imported_artifact(path: Path | None, stated_sha256: str | None,
                       out: Path) -> tuple[str, str, str]:
    """Bind a supported imported artifact by path, backend, and SHA-256."""
    if path is None or not stated_sha256:
        raise ValueError("--template none requires --imported-artifact and --imported-sha256")
    artifact = path.resolve()
    if not artifact.is_file():
        raise ValueError(f"imported artifact does not exist: {path}")
    backend = _IMPORTED_BACKENDS.get(artifact.suffix.lower())
    if backend is None:
        supported = ", ".join(sorted(_IMPORTED_BACKENDS))
        raise ValueError(f"unsupported imported artifact type {artifact.suffix or '<none>'!r}; "
                         f"supported types: {supported}")

    digest = stated_sha256.strip().lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("--imported-sha256 must be a 64-character hexadecimal SHA-256")

    from .receipts import sha256_file
    actual = sha256_file(artifact)
    if actual != digest:
        raise ValueError(
            f"imported artifact SHA-256 mismatch: supplied {digest}, actual {actual}")
    relative = Path(os.path.relpath(artifact, out.resolve())).as_posix()
    return relative, actual, backend


def _dimension_rows(params: dict[str, Any], stated: frozenset[str],
                    *, imported: bool = False,
                    inherited: frozenset[str] = frozenset(),
                    inherited_methods: dict[str, str] | None = None) -> str:
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

    `B` rather than `A` on the built-in route: nothing there was measured, and
    calling a transcription high-confidence would be the document flattering
    itself. Imported rows retain `B` because this command records the supplied
    method but does not independently verify it.
    """
    methods = inherited_methods or {}
    rows = []
    for index, (name, value) in enumerate(sorted(params.items()), start=1):
        if imported and name in inherited:
            method = methods.get(name)
            if not method:
                raise ValueError(f"every inherited dimension requires a method: {name}")
            rows.append(f"| D-{index:02d} | {name} | {value} | "
                        f"inherited from imported solid; {method} | "
                        f"imported artifact | B | inherited value |")
        elif imported:
            rows.append(f"| D-{index:02d} | {name} | {value} | chosen by design | "
                        f"designer | D | free to change |")
        elif name in stated:
            rows.append(f"| D-{index:02d} | {name} | {value} | stated in the brief | "
                        f"user | B | as stated |")
        else:
            rows.append(f"| D-{index:02d} | {name} | {value} | chosen by design | "
                        f"designer | D | free to change |")
    return "\n".join(rows) or "| — | — | — | — | — | — | — |"


def _stated(raw: list[str]) -> frozenset[str]:
    """Accept `--stated a,b` and repeated `--stated a --stated b` alike."""
    return frozenset(name.strip() for text in raw for name in text.split(",") if name.strip())


def _inherited_methods(raw: list[str]) -> dict[str, str]:
    """Parse one explicit derivation or measurement method per dimension."""
    methods = {}
    for text in raw:
        name, separator, method = text.partition("=")
        name = name.strip()
        method = method.strip()
        if not separator or not name or not method:
            raise ValueError("--inherited-method values must be non-empty NAME=METHOD pairs")
        if name in methods:
            raise ValueError(f"duplicate or ambiguous inherited method for dimension {name!r}")
        methods[name] = method
    return methods


def _completeness_rows(built) -> str:
    """One row per feature the template says it built.

    Not a summary of the geometry -- the template's own declaration of what it
    put there, which is the same list the gate measures. A feature that appears
    here and nowhere in `expected` is one nothing checks, and that is worth
    seeing in a table rather than discovering later.
    """
    if built is None:
        return (f"| F-01 | imported/off-template geometry | see the supplied input | "
                f"inherited from imported solid | B | {REQUIRED} | {REQUIRED} |")

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


def job_state(*, job_id: str, profile: str, consequence: str, updated_utc: str,
              template: str, rationale: str | None = None,
              acceptance: str | None = None, artifact_path: str | None = None,
              artifact_sha256: str | None = None,
              backend: str | None = None) -> str:
    """The judgments arrive as arguments, or not at all.

    They are still the caller's -- nothing here invents one. What changes is
    delivery: an agent that has already decided the consequence class pays two
    or three edit turns to type it into a file it just generated, and turns are
    what this route spends. Passing it in costs nothing and the field is filled
    by the same reasoning that would have filled it by hand.
    """
    dispatches = ("| — | none | — | — | — | not dispatched: this route runs no specialists |"
                  if profile == "DIRECT" else f"| D01 | {REQUIRED} | | | | queued |")
    if template == OFF_TEMPLATE:
        route_basis = ("this is an imported/off-template input; no built-in template covers "
                       "the shape")
    else:
        route_basis = ("nothing here needs measuring and the "
                       f"`{template}` template covers the shape")
    backend_value = backend or ("trimesh-template"
                                if template != OFF_TEMPLATE else "trimesh-manifold")
    artifact_binding = (f"| imported artifact | {artifact_sha256} | inherited from imported "
                        f"solid: {artifact_path} |"
                        if artifact_path else "")
    bound_inputs = (f"| brief.md | as supplied | read |\n{artifact_binding}"
                    if artifact_binding else "| brief.md | as supplied | read |")
    return f"""---
contract: job-state
contract_version: 4
job_id: {job_id}
revision: 1
owner: orchestrator
mode: PIPELINE
profile: {profile}
consequence: {consequence}
state: INTAKE
backend: {backend_value}
active_candidate: none
updated_utc: {updated_utc}
---

# Job state

## Route

**Consequence class: `{consequence}`.** Rationale: {rationale or REQUIRED}

**Profile `{profile}`,** because {route_basis}. {acceptance or REQUIRED} — say here what acceptance
depends on that you did not get to choose, and if the answer is nothing, say that.
{"" if profile != "DIRECT" else '''
Built and checked by the orchestrator; no independent fresh-context verification. That is
what this route is: nobody who did not build the part will look at it. The delivery repeats
this, and the receipt leaves `visual_accept` for a human who has actually seen a render.
'''}
## Bound inputs
| Contract/evidence | Revision/hash | Status |
|---|---|---|
{bound_inputs}
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
               built=None, brief: Path | None = None,
               stated: frozenset[str] = frozenset(), artifact_path: str | None = None,
               artifact_sha256: str | None = None,
               inherited: frozenset[str] = frozenset(),
               inherited_methods: dict[str, str] | None = None) -> str:
    imported = template == OFF_TEMPLATE
    inherited_methods = inherited_methods or {}
    provenance = ("Written by the orchestrator for an imported/off-template input. No built-in "
                  "template declares the geometry or its feature list; the supplied values "
                  "remain the source of record."
                  if imported else
                  "Written by the orchestrator, not a metrologist, because this job carries no "
                  "photograph, no caliper reading and no real object. A metrologist reconciles "
                  "sources; given one source it can only transcribe.")
    frame_source = "imported artifact" if imported else "template"
    if imported:
        source_rows = (f"| S-01 | {artifact_path} | imported solid | {artifact_sha256} | "
                       "inherited from imported solid; source artifact is bound read-only |")
        if brief is not None:
            source_rows += (f"\n| S-02 | {brief.name} | as supplied | {_brief_hash(brief)} | "
                            "the user's statement is the only authority here |")
    else:
        source_rows = (f"| S-01 | {brief.name if brief else 'brief.md'} | as supplied | "
                       f"{_brief_hash(brief)} | the user's statement is the only authority here |")
    closing = ("Every visible feature must be recorded in blind-build completeness above. "
               "This row marks the geometry as imported/off-template; its feature inventory "
               "was not supplied by a built-in template."
               if imported else
               f"Every visible feature must appear in blind-build completeness above. The rows "
               f"come from `{template}`'s own declaration of what it built — if the brief names "
               "a feature that is not in that list, the template does not build it, and nothing "
               "downstream will measure it.")
    row_provenance = ("Every row below is stated by the user, chosen by the design, or explicitly "
                      "imported/off-template; inherited rows include their explicit "
                      "derivation/measurement method, and none is image-derived."
                      if imported else
                      "Every row below is stated by the user or chosen by the design, none is "
                      "image-derived or measured, and none is graded `A`.")
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

{provenance} {row_provenance}

## Frame
| Axis/datum | Definition | Source | Confidence |
|---|---|---|---|
| origin | the part is seated on the bed at z=0, the convention every template returns | {frame_source} | A |
| +Z | build direction | print plan | A |

## Sources
| ID | Evidence path/URL | Variant | SHA-256 or access date | Authority/limits |
|---|---|---|---|---|
{source_rows}

## Blind-build completeness
| Feature ID | Name/count/function | Datum value or bounded envelope | Source | Confidence | Candidate response | Ready |
|---|---|---|---|---|---|---|
{_completeness_rows(built)}

## Dimensions
| ID | Feature | Value/range | Datum/method | Source | Confidence | Tolerance/design response |
|---|---|---:|---|---|---|---|
{_dimension_rows(params, stated, imported=imported, inherited=inherited,
                 inherited_methods=inherited_methods)}

## Open questions
| ID | Unknown | Risk | Approved bound/question | Blocks |
|---|---|---|---|---|
| — | none | — | — | — |

## Reference round trip
| Build ID/hash | Views/overlay | Verdict | Sheet revision required |
|---|---|---|---|
| — | no reference is built on this route: nothing is being recreated | — | no |

{closing}
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--template", required=True,
                        help="a built-in template name, or `none` for imported/off-template "
                             "geometry")
    parser.add_argument("--param", action="append", default=[], metavar="NAME=VALUE")
    parser.add_argument("--stated", action="append", default=[], metavar="NAME[,NAME]",
                        help="comma-separated parameter names the brief actually "
                             "states. Everything else is recorded as chosen by the "
                             "design at confidence D. That is the safe direction: "
                             "forgetting it understates your own confidence, while "
                             "the reverse claims the user said something they did not.")
    parser.add_argument("--profile", choices=_PROFILE,
                        help="route profile; imported/off-template input defaults to FULL")
    parser.add_argument("--consequence", default="INCONSEQUENTIAL", choices=_CONSEQUENCE)
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
    parser.add_argument("--imported-artifact", "--artifact", "--imported-artifact-path",
                        dest="imported_artifact", type=Path,
                        help="off-template source artifact to bind by project-relative path")
    parser.add_argument("--imported-sha256", "--artifact-sha256", "--sha256",
                        dest="imported_sha256",
                        help="SHA-256 of the imported artifact")
    parser.add_argument("--inherited", "--inherited-dimension", action="append", default=[],
                        metavar="NAME[,NAME]",
                        help="imported dimension names inherited from the source artifact")
    parser.add_argument("--inherited-method", action="append", default=[],
                        metavar="NAME=METHOD",
                        help="derivation or measurement method for each --inherited dimension; "
                             "repeat once per dimension")
    parser.add_argument("--chosen", "--chosen-by-design", action="append", default=[],
                        metavar="NAME[,NAME]",
                        help="imported dimension names chosen by design")
    args = parser.parse_args(argv)

    try:
        params = dict(parse_param(text) for text in args.param)
        built = _built(args.template, params)
        inherited_methods = _inherited_methods(args.inherited_method)
    except (ValueError, TypeError) as exc:
        sys.stderr.write(f"intake: {exc}\n")
        return 2

    inherited = _stated(args.inherited)
    chosen = _stated(args.chosen)
    artifact_path = artifact_sha256 = artifact_backend = None
    if args.template == OFF_TEMPLATE:
        if args.profile not in (None, "FULL"):
            sys.stderr.write(
                "intake: imported/off-template input must use the FULL profile; "
                "FITTED and DIRECT are unsupported\n")
            return 2
        if args.stated:
            sys.stderr.write(
                "intake: --stated is unsupported for imported dimensions; use "
                "--inherited and --chosen\n")
            return 2
        overlap = inherited & chosen
        unknown = (inherited | chosen) - params.keys()
        unknown_methods = inherited_methods.keys() - params.keys()
        methods_for_chosen = inherited_methods.keys() & chosen
        missing_methods = inherited - inherited_methods.keys()
        unclassified = params.keys() - inherited - chosen
        if overlap:
            sys.stderr.write(
                f"intake: dimensions cannot be both inherited and chosen: "
                f"{', '.join(sorted(overlap))}\n")
            return 2
        if unknown:
            sys.stderr.write(
                f"intake: imported dimension classification names unknown parameters: "
                f"{', '.join(sorted(unknown))}\n")
            return 2
        if unknown_methods:
            sys.stderr.write(
                f"intake: inherited method names unknown parameters: "
                f"{', '.join(sorted(unknown_methods))}\n")
            return 2
        if methods_for_chosen:
            sys.stderr.write(
                f"intake: inherited methods cannot be supplied for chosen dimensions: "
                f"{', '.join(sorted(methods_for_chosen))}\n")
            return 2
        if missing_methods:
            sys.stderr.write(
                f"intake: every inherited dimension requires --inherited-method: "
                f"{', '.join(sorted(missing_methods))}\n")
            return 2
        if unclassified:
            sys.stderr.write(
                f"intake: classify every imported parameter with --inherited or --chosen: "
                f"{', '.join(sorted(unclassified))}\n")
            return 2
        profile = "FULL"
        try:
            artifact_path, artifact_sha256, artifact_backend = _imported_artifact(
                args.imported_artifact, args.imported_sha256, args.out)
        except ValueError as exc:
            sys.stderr.write(f"intake: {exc}\n")
            return 2
    else:
        profile = args.profile or "DIRECT"
        if (args.imported_artifact is not None or args.imported_sha256 is not None
                or args.inherited or args.inherited_method or args.chosen):
            sys.stderr.write(
                "intake: imported artifact and dimension classification options require "
                "--template none\n")
            return 2

    args.out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, text in (
        ("job_state.md", job_state(
            job_id=args.job_id, profile=profile, consequence=args.consequence,
            updated_utc=args.updated_utc, template=args.template,
            rationale=args.rationale, acceptance=args.acceptance,
            artifact_path=artifact_path, artifact_sha256=artifact_sha256,
            backend=artifact_backend)),
        ("dimensions.md", dimensions(
            job_id=args.job_id, updated_utc=args.updated_utc, template=args.template,
            params=params, built=built, brief=args.brief, stated=_stated(args.stated),
            artifact_path=artifact_path, artifact_sha256=artifact_sha256,
            inherited=inherited, inherited_methods=inherited_methods)),
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
