#!/usr/bin/env python3
"""Write a blind modelling request from the corpus, and score what comes back.

Two verbs and a wall between them.

    uv run python tools/blind.py --ask voron-deck-support --into /tmp/job
    uv run python tools/blind.py --score /tmp/job/candidate.stl \\
                                 --against voron-deck-support

`--ask` builds a `project.json` and a brief from `corpus.request_view`, which
carries the purpose and the measured counterparts and nothing that locates the
reference. `--score` measures the candidate against the reference's own bytes.
Nothing in this file lets the first reach what the second reads: it calls
`corpus.question_ids` and `corpus.request_view` and never `corpus._entries`,
so a path or a digest cannot arrive on the asking side even by accident.

**What a score is, exactly.** Four dimensional measurements and one shape
descriptor, and the claim stops there:

* the three bounding-box extents, **sorted** -- so a part modelled lying down
  and the same part standing up compare equal, and no registration or fitting
  is needed to say so. Orientation drops out; nothing else does;
* the solid volume;
* the body count;
* whether the solid is closed;
* the three principal moments of inertia about the solid's own centre of mass
  at unit density, sorted and each divided by `V^(5/3)`. Dimensionless, so it
  says something the four above cannot: how the material is distributed rather
  than how much of it there is.

The first four are **dimensional agreement, not shape equivalence.** Two quite
different parts can share a bounding box and a volume -- a hollow shell and a
lattice will, and so will a plate with the holes in the wrong places. Measured
here rather than argued: a plain slab sized to the deck-support reference's
bounding box and volume passes all four while being incapable of the job.
Normalised inertia is what rejects that slab, which is why it is the fifth row
and why it is the only one of the three descriptors proposed with it that
shipped -- the per-body Euler tuple matched the impostor exactly and normalised
area sat within 1.7% of it.

Inertia narrows the claim; it does not close it. Three numbers cannot certify a
shape, and distinct solids can share all three. `ROADMAP.md`'s Release 6 still
owns the comparison that would settle it: deterministic geometric difference,
which needs the registration this deliberately avoids.

**Why the envelope is not taken from the reference.** `design-tool run` requires
`envelope_mm` whenever geometry is authored -- it refuses rather than guessing.
Deriving it from the reference would hand over the answer to within the slack,
so it comes from the entry's own declared `build_envelope_mm`: a constraint the
requester states, generous, and checked by the same coincidence rule as every
other number in the question.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
# `tools` last, so it ends up *first*: `pipeline/corpus.py` already exists, and
# a future `scripts/corpus.py` ahead of this one would silently shadow the wall
# with a module that has no idea what it is guarding.
sys.path.insert(0, str(ROOT / "skills" / "3d-modeling" / "scripts"))
sys.path.insert(0, str(ROOT / "tools"))

import corpus                                                    # noqa: E402

# What a score compares, and the band each is compared inside. Relative, because
# 0.2 mm on a 5 mm thickness is a different statement from 0.2 mm on a 30 mm
# span, and a single absolute band would be lenient at one end and impossible at
# the other.
AGREEMENT_FRACTION = corpus.COINCIDENCE_FRACTION

# The shape descriptor gets its own band, calibrated rather than inherited. Borrowing
# `COINCIDENCE_FRACTION` would have been borrowing a *leak-detection policy* -- how near
# a stated number may come to an answer before it is suspicious -- to answer a different
# question: how much this descriptor moves for geometry that has not changed.
#
# Measured, on this machine, in one session. A cylinder tessellated at 24, 48, 96 and
# 192 sections drifts 0.00%, 0.30%, 0.37% and 0.39% from the coarsest -- converging, as
# a discretisation error should, on well under half a percent. A solid box exported to
# STL and reloaded, which is the float32 round trip every candidate here makes, drifts
# 0.0000%. So same-geometry noise is under 0.4%, and 1% leaves better than twice that in
# hand while staying half the size of the 2% it replaces.
#
# It is deliberately the tighter number. The looser one would have let the impostor
# through: a plain slab matching a reference's box and volume sits 33% to 63% out on
# these moments, so the band is nowhere near the difference that matters -- but a band
# chosen for the wrong reason stops being evidence the moment somebody asks where it
# came from.
INERTIA_AGREEMENT_FRACTION = 0.01


class BlindError(RuntimeError):
    """The benchmark cannot be run as asked. Never a low score."""


# --------------------------------------------------------------------------
# Asking
# --------------------------------------------------------------------------

def request(entry_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """The question, as a project a `design-tool` job can be run from.

    Every value here came through `corpus.request_view`, which is the only
    function this module calls that touches the manifest's entry rows.
    """
    # No guard here for a missing envelope: it is a required request key, so
    # `request_view` refuses an entry without one before this function sees it,
    # and a second check would be unreachable. An unreachable check reads to the
    # next maintainer as a thing that can happen.
    view = corpus.request_view(entry_id, payload)
    envelope = view.pop("build_envelope_mm")
    return {
        "checked_against_reference": view["checked_against_reference"],
        "project": _project(entry_id, view, envelope),
        "brief": _brief(view),
    }


def handle(entry_id: str) -> str:
    """What the job calls itself: a digest of the entry, not its name.

    The first version wrote `blind-voron-deck-support` into `project.json`, and
    a review measured what that is worth. Ranked against the 150 STLs already in
    the corpus root, by fuzzy string match alone, that name puts the true
    reference **first or second**. `corpus.request_view` refuses to emit the id
    for exactly this reason and says so in its docstring; this file put it
    straight back, in the one artifact a designer is handed.

    A digest keeps a job identifiable across runs -- the same entry always
    produces the same handle -- and names nothing.
    """
    return "blind-" + hashlib.sha256(entry_id.encode("utf-8")).hexdigest()[:8]


def _project(entry_id: str, view: dict[str, Any],
             envelope: dict[str, float]) -> dict[str, Any]:
    """A `project.json` payload, with the requirements carried through verbatim.

    Verbatim because `corpus.REQUIREMENT_KEYS` is `project.Requirement`'s own
    field list: a translation layer here would be a second vocabulary and a
    place for the two to disagree.
    """
    return {
        "schema_version": 1,
        "job_id": handle(entry_id),
        "updated_utc": "1970-01-01T00:00:00Z",
        "source_mode": "NEW",
        "consequence": "INCONSEQUENTIAL",
        "consequence_rationale": (
            "a benchmark reconstruction; a failure costs the material and "
            "tells us the reconstruction was wrong, which is the point"),
        "brief": "brief.md",
        "printer": "Blind Benchmark",
        "material": {"process": "FDM", "material": "PLA"},
        "nozzle": {"diameter_mm": 0.4},
        "orientation": {"model_to_printer_matrix": "identity", "bed_z_mm": 0.0},
        "envelope_mm": dict(envelope),
        "model": "model.py",
        "requirements": [dict(row) for row in view["requirements"]],
        "reviewer": {"model_snapshot": "blind-benchmark"},
        "verification_requested": True,
    }


def _brief(view: dict[str, Any]) -> str:
    """What a person would have written, from the same material.

    The requirements are restated here as prose *and* carried as structure. Not
    duplication for its own sake: a designer reads the brief and the pipeline
    reads `requirements`, and a brief that omitted them would be a request whose
    human half and machine half disagree about what was asked.
    """
    lines = ["# What this part has to do", "", view["purpose"], "",
             "# What it has to fit", ""]
    for row in view["requirements"]:
        value = row["value"]
        unit = (" " + row["unit"]) if row.get("unit") else ""
        note = f" — {row['note']}" if row.get("note") else ""
        lines.append(f"* **{row['name']}**: {value}{unit} "
                     f"({row['provenance'].lower()}, {row['source']}){note}")
    lines += ["", "# What nobody has told you", "",
              "The size and shape of the part itself. That is what this "
              "exercise is for: build it from what it has to fit, and the "
              "score is how close the result lands.", ""]
    return "\n".join(lines)


def write_request(entry_id: str, into: Path,
                  payload: dict[str, Any] | None = None) -> Path:
    """Lay the question down as a directory `design-tool run` can be pointed at."""
    built = request(entry_id, payload)
    into = Path(into)
    into.mkdir(parents=True, exist_ok=True)
    (into / "project.json").write_text(
        json.dumps(built["project"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    (into / "brief.md").write_text(built["brief"], encoding="utf-8", newline="\n")
    # Nothing else is written. A third file held `entry_id` and a flag the
    # caller already has in hand, and it was the other place the reference's
    # name reached the designer.
    return into


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------

def measure(path: Path) -> dict[str, Any]:
    """The facts a score is made of, off one solid and one load.

    Four of them are dimensional -- the sorted extents, the volume, the body count and
    whether the solid is closed -- and between them they cannot see shape. The report
    says so in its own words, and it is demonstrable rather than cautious: a plain slab
    with one rectangular pocket, sized to a reference's bounding box and volume, agrees
    on every one of those rows while being incapable of the job the reference does.

    `inertia_normalised` is the fifth and it is the one that notices. It is the three
    principal moments of the solid about its own centre of mass at unit density,
    sorted, each divided by `V**(5/3)`.
    """
    import numpy as np
    import trimesh

    mesh = trimesh.load(str(path), force="mesh")
    extents = sorted(float(v) for v in mesh.bounding_box.extents)
    raw = [float(v) for v in mesh.bounding_box.extents]
    volume = float(mesh.volume)
    return {
        "sorted_extents_mm": extents,
        "extent_x": raw[0], "extent_y": raw[1], "extent_z": raw[2],
        "volume_mm3": volume,
        "bodies": int(mesh.body_count),
        "watertight": bool(mesh.is_watertight),
        "inertia_normalised": _normalised_inertia(mesh, volume, np=np),
    }


def _normalised_inertia(mesh, volume: float, *, np) -> list[float] | None:
    """Sorted principal moments over `V**(5/3)`, or nothing at all.

    **Why the exponent.** At unit density inertia scales as length to the fifth, so
    `I/V` still scales as length squared -- a second size check wearing a shape
    descriptor's name, when the extents and the volume already own size. `V**(5/3)`
    cancels the units exactly, which is what lets this say something the other rows
    cannot.

    **Why sorted.** The same part modelled lying down and standing up must compare
    equal, and sorting the triple drops orientation without needing the registration
    ROADMAP.md's Release 6 owns.

    **Why `None` rather than a number.** An open surface still has *a* volume -- a
    defined float, merely meaningless -- so `measure` reports it and `score` withholds
    it. Dividing by it gives NaN or infinity, and that is not a value being withheld
    but no value at all. A NaN formatted into a report reads exactly like a
    measurement, which is the failure this whole file exists to avoid.
    """
    if not mesh.is_watertight or not (volume > 0.0):
        return None
    moments = np.asarray(mesh.principal_inertia_components, dtype=float)
    if not np.all(np.isfinite(moments)):
        return None
    scale = volume ** (5.0 / 3.0)
    return sorted(float(m) / scale for m in moments)


def _given_positions(disclosed: set[str], want: dict[str, Any]) -> set[int]:
    """Where a disclosed extent lands once the extents are sorted.

    The manifest names an axis of the reference -- `extent_x` -- and the score
    compares a *sorted* triple, so the disclosure has to be mapped through the
    same sort. Done by value rather than by index: `extent_x` is whichever
    position the reference's x measurement occupies after sorting, and on a part
    with two equal extents it marks both, which is the safe direction.
    """
    order = want["sorted_extents_mm"]
    positions: set[int] = set()
    for name in disclosed:
        value = want[name]
        positions |= {index for index, extent in enumerate(order)
                      if abs(extent - value) <= 1e-6}
    return positions


def _inertia_row(got: list[float] | None,
                 want: list[float] | None) -> dict[str, Any]:
    """Three sorted dimensionless moments, compared one at a time.

    Per eigenvalue rather than as a single distance, for the reason `score` refuses a
    total: a part that is right about two of its principal axes and wrong about the
    third has a specific defect, and one rolled-up number hides which.
    """
    if got is None or want is None:
        return {"candidate": got, "reference": want, "agrees": None,
                "why": "at least one side has no closed solid to take moments of"}
    deltas = [g - w for g, w in zip(got, want)]
    bands = [abs(w) * INERTIA_AGREEMENT_FRACTION for w in want]
    return {
        "candidate": [round(v, 6) for v in got],
        "reference": [round(v, 6) for v in want],
        "delta": [round(v, 6) for v in deltas],
        "band": [round(v, 6) for v in bands],
        "agrees": all(abs(d) <= b for d, b in zip(deltas, bands)),
    }


def score(candidate: Path, entry_id: str,
          payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """How close a blind reconstruction landed, on four measurements and one descriptor.

    Never a single number. `ARCHITECTURE.md` 8.5's argument against a weighted
    total applies here as much as in `compare`: rolling "the right size" and
    "closed solid" into one figure hides which of them failed, and the answer a
    reader acts on is which one. The inertia row extends that rather than
    breaking it -- three moments compared one at a time, not one distance.
    """
    candidate = Path(candidate)
    if not candidate.is_file():
        raise BlindError(f"no candidate at {candidate}")
    got = measure(candidate)
    want = measure(corpus.resolve(entry_id, payload))

    # Which of the reference's own measurements the question gave away. A
    # disclosed axis is compared and reported like any other, and marked
    # `given` -- a benchmark cannot claim to have measured a reconstruction of
    # a number it handed over. `docs/defects.md` D30 is why any of them are.
    disclosed = {row["measurement"] for row
                 in corpus.request_view(entry_id, payload).get("discloses", ())}
    # Extents and volume counted apart. Mixing them made the summary say "2 of 3
    # extents were given away (extent_x, volume_mm3), so 2 were reconstructed"
    # -- four axes out of three -- and left a disclosed volume marked by
    # nothing at all, on a number the question handed over.
    given_extents = sorted(disclosed & {"extent_x", "extent_y", "extent_z"})
    volume_given = "volume_mm3" in disclosed
    given = _given_positions(set(given_extents), want)

    axes = []
    for index, (a, b) in enumerate(zip(got["sorted_extents_mm"],
                                       want["sorted_extents_mm"])):
        band = b * AGREEMENT_FRACTION
        axes.append({"axis": "smallest middle largest".split()[index],
                     "candidate_mm": round(a, 4), "reference_mm": round(b, 4),
                     "delta_mm": round(a - b, 4), "band_mm": round(band, 4),
                     "agrees": abs(a - b) <= band,
                     "given": index in given})
    # A volume read off a surface that is not closed is a divergence sum over
    # an open boundary, not a volume. Reporting it as a measurement with a
    # verdict put three `ok` rows on something that is not a solid, and a reader
    # took away "right size, right material, needs mesh repair". Fail closed:
    # the measurement could not be made, and the row says so.
    volume_band = want["volume_mm3"] * AGREEMENT_FRACTION
    closed = got["watertight"]
    volume_row = {
        "candidate_mm3": round(got["volume_mm3"], 3) if closed else None,
        "reference_mm3": round(want["volume_mm3"], 3),
        "band_mm3": round(volume_band, 3),
        "agrees": (abs(got["volume_mm3"] - want["volume_mm3"]) <= volume_band
                   if closed else None),
        "given": volume_given,
        "why": None if closed else (
            "the candidate is not a closed solid, so it has no volume to "
            "compare -- what trimesh returns for an open surface is a sum over "
            "a boundary that does not close"),
    }
    return {
        "schema_version": 1,
        "entry_id": entry_id,
        "extents": axes,
        "volume": volume_row,
        "bodies": {"candidate": got["bodies"], "reference": want["bodies"],
                   "agrees": got["bodies"] == want["bodies"]},
        "watertight": {"candidate": got["watertight"],
                       "reference": want["watertight"],
                       "agrees": got["watertight"] == want["watertight"]},
        # The only row that can see shape. Absent on either side means no verdict
        # rather than a failed one: an open surface has no defensible moments, and
        # reporting `agrees: False` for it would blame the candidate's shape for
        # something the watertight row already says plainly.
        "inertia": _inertia_row(got["inertia_normalised"],
                                want["inertia_normalised"]),
        "score": None,
        "reconstructed_axes": sum(1 for row in axes if not row["given"]),
        "given_extents": given_extents,
        "given_volume": volume_given,
        "what_this_is_not": (
            "dimensional agreement on four measurements, plus one "
            "orientation-free shape descriptor -- and still not shape "
            "equivalence. Measured rather than asserted: a plain slab with one "
            "rectangular pocket, sized to this reference's bounding box and "
            "volume, agrees on every dimensional row -- and so does the same "
            "slab with x and y swapped, which would not fit the extrusion the "
            "brief specifies. Sorting the extents drops orientation and also "
            "drops which axis is which. Normalised principal inertia is what "
            "rejects that slab, by 33 to 63 percent, and it is the only row "
            "here that can see shape at all. It still cannot certify one: it is "
            "three numbers, and distinct solids can share all three, so "
            "agreement is evidence rather than proof. In the other direction "
            "the band is tight: two "
            "percent of this part's volume is about one small through-hole, so "
            "whether a correct reconstruction passes the volume row can turn on "
            "a feature the brief never dimensioned. Deterministic geometric "
            "difference is ROADMAP.md's Release 6 and needs the registration "
            "this deliberately avoids. And where `given_extents` is non-empty "
            "the question handed those axes over: they are compared and "
            "reported, and they are not evidence of a reconstruction. Two "
            "blind runs found the rest of the envelope is mostly free "
            "parameters the brief never constrains, so a low score here is "
            "substantially a fact about the question -- docs/defects.md D30."),
    }


def _table(report: dict[str, Any]) -> None:
    print(f"\n  blind score  {report['entry_id']}\n")
    for row in report["extents"]:
        mark = ("giv" if row["given"] else "ok ") if row["agrees"] else \
               ("GIV" if row["given"] else "OFF")
        print(f"  {mark} {row['axis']:8s} {row['candidate_mm']:9.3f} against "
              f"{row['reference_mm']:9.3f}  ({row['delta_mm']:+.3f}, band "
              f"{row['band_mm']:.3f})")
    for name in ("volume", "bodies", "watertight"):
        row = report[name]
        mark = {True: "ok ", False: "OFF", None: "-- "}[row["agrees"]]
        if row.get("given"):
            mark = "giv" if row["agrees"] else "GIV"
        keys = [k for k in row if k.startswith("candidate")]
        ref = [k for k in row if k.startswith("reference")]
        print(f"  {mark} {name:8s} {row[keys[0]]!s:>9} against {row[ref[0]]!s:>9}")
    # Printed per moment rather than as one verdict, for the reason `_inertia_row`
    # compares them one at a time: a part right about two of its principal axes and
    # wrong about the third has a specific defect, and a single mark hides which.
    # This row is what a reader gets that the four above cannot give them, so it is
    # printed by default -- `--json` is the exception, not the interface.
    inertia = report["inertia"]
    print("\n  inertia  I/V^(5/3), sorted -- orientation-free and dimensionless")
    if inertia["agrees"] is None:
        print(f"  --  {inertia['why']}")
    else:
        for label, cand, ref_v, delta, band in zip(
                "smallest middle largest".split(), inertia["candidate"],
                inertia["reference"], inertia["delta"], inertia["band"]):
            print(f"  {'ok ' if abs(delta) <= band else 'OFF'} {label:8s} "
                  f"{cand:9.6f} against {ref_v:9.6f}  "
                  f"({delta:+.6f}, band {band:.6f})")
    if report["given_extents"] or report["given_volume"]:
        parts = []
        if report["given_extents"]:
            parts.append(f"{len(report['given_extents'])} of 3 extents "
                         f"({', '.join(report['given_extents'])})")
        if report["given_volume"]:
            parts.append("the volume")
        print(f"\n  The question gave away {' and '.join(parts)}, so "
              f"{report['reconstructed_axes']} of 3 extents were "
              "reconstructed. Rows marked giv/GIV were not earned.")
    print(f"\n  {report['what_this_is_not']}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tools/blind.py",
        description="Write a blind modelling request from the reference "
                    "corpus, and score a candidate against the reference it "
                    "was never shown.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true")
    group.add_argument("--ask", metavar="ENTRY")
    group.add_argument("--score", metavar="CANDIDATE", type=Path)
    parser.add_argument("--into", type=Path, default=None)  # --ask only
    parser.add_argument("--against", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.list:
        for entry_id in corpus.question_ids():
            print(f"  {entry_id}")
        return 0

    if args.ask:
        if args.into is None:
            parser.error("--ask needs --into <directory>")
        if args.against:
            parser.error("--against belongs to --score")
        try:
            built = request(args.ask)
            where = write_request(args.ask, args.into)
        except (BlindError, KeyError, corpus.CorpusLeak) as exc:
            sys.stderr.write(f"blind: {exc}\n")
            return 2
        print(f"\n  wrote {where}")
        print(f"  checked against the reference: "
              f"{built['checked_against_reference']}")
        print(f"\n  design-tool run {where} --no-render\n")
        return 0

    if not args.against:
        parser.error("--score needs --against <entry>")
    try:
        report = score(args.score, args.against)
    except (BlindError, KeyError, corpus.CorpusLeak, corpus.CorpusUnavailable,
            corpus.CorpusCorrupt) as exc:
        sys.stderr.write(f"blind: {exc}\n")
        return 2
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _table(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
