#!/usr/bin/env python3
"""Set the formulations of one job beside each other, on the evidence already
on disk.

This module reads receipts. It dispatches nothing, builds nothing, and measures
no geometry it did not find already measured. Everything it reports was written
by a run that had the part in front of it; the only thing added here is the act
of putting two of them side by side, and being explicit about what that does and
does not settle.

**There is no score, no weight and no ordering.** `ARCHITECTURE.md` 8.5 says no
weighted score may hide a mandatory failure, and the cheapest way to guarantee
that is to have no weighted score. Formulations are a JSON *object* keyed by id
and never an array, because an array has an order and an order reads as a
ranking. Choosing is `design-tool branch --disposition`, which records who chose
and on what basis. A comparison that also chose would be a second authority over
one decision, and the one with no person's name on it.

## The defect this file exists for

A naive comparison of the recorded three-formulation knob prints `envelope PASS`
beside `envelope PASS` and a reader concludes the two formulations are equal on
size. They are not being told that. Measured on
`benchmarks/replays/branch-knob-seat-fallback`: the root formulation's proposal
declares `bbox_mm.z = 50.0` and `plate-seated`'s declares `52.0`, and each was
checked against its own declaration, to a band of 0.5. Both PASS. The two
verdicts are answers to different questions.

That is one face of a general defect (`docs/defects.md` D25): **on the authored
lane a formulation's own `design_proposal.json` sets the rubric it will be
graded against.** It has three faces, and all three make a "PASS beside PASS"
comparison false in a different way:

1. **the check set.** Coverage is `covered / declared` where `declared` is that
   formulation's own mandatory features (`commission.py:436`, `docs/defects.md`
   D24). Three-of-three and eight-of-eight both score 1.0. No normalisation
   repairs this, because there is no shared denominator to normalise to.
2. **the expectation.** `expected_bbox_mm` and `expected_bodies` come from the
   proposal (`acceptance.py:358-359`), and they are what the always-present
   `envelope`, `bodies` and `unit_scale` checks measure against. This is the
   face that fires on the recorded case with nothing constructed.
3. **the band.** A feature's tolerance is computed from the magnitude the
   proposal declared -- `contract.area_tolerance` is 0.5% of it, floored at
   1 mm2 -- so a formulation declaring 881.33 mm2 is graded to +/-4.41 and one
   declaring 400.0 mm2 to +/-2.00. Declaring a larger number buys a looser band.

So the mandatory axis carries a three-valued verdict rather than a boolean, and
`INCOMPARABLE_CHECK_SETS` is only the first of them. The comparand is never
`coverage.fraction`: `covered` is not filtered to mandatory features
(`commission.py:437` counts every check with a `feature_id` that ran), so the
fraction is not even bounded by 1.0, and a fraction cannot say *which* check
differs, which is the only part of the answer a reader can act on.

**The verdict scopes to the axis, not to the comparison.** 8.5 requires
comparative results to distinguish mandatory pass-or-failure from preference
criteria from incomplete evidence from subjective choice -- four registers -- and
one verdict standing for all of them is the same collapse the rule forbids, run
backwards. An unusable mandatory axis does not delete its neighbours; in
particular it must not delete the evidence axis, which is where a stale sibling
is reported and which is computable however badly the contracts disagree.

## Two sentences this module keeps apart

*"Each formulation met the contract it froze, and all of them bind the same
requirement digest."* True, and reported.

*"All of them meet the requirement."* Not established, and never claimed. The
shared requirements are bound as a digest (`cli._requirement_hash`) and never
individually checked; the contract's rows are geometric proxies a designer
chose, and no edge in this build links a project requirement to the contract row
that measures it. So `shared.requirement_digest` is reported as a **binding** and
never as a satisfaction.

## What `not_compared` is for

A comparison that silently omits the dimension nobody can measure is worse than
none: it leaves a reader concluding two formulations are equivalent on an axis
nothing looked at. So the output always carries one row per dimension this job
exercises and this build cannot measure, each naming why and which release owns
it. On a single-material one-piece pair that block is short. On a `MODIFY` pair
it is the entire finding -- both formulations report `EXPERIMENTAL_UNAVAILABLE`,
the axis that decides between them is preservation, and preservation cannot be
measured here. That output is correct and complete, not a failure to compare,
and `preference.admissible` is false with preservation named as the reason.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import bindings as B
from . import project as P
from . import schemas as S
from . import screening as SCR
from . import status as STATUS

COMPARISON_SCHEMA = 1
COMPARISON_FILE = "comparison.json"

# How the shared root spells itself here, in `cost.compare` and in the binding
# map. One spelling, because two would be two places as far as a comparison is
# concerned -- which is the class of failure this module is about.
ROOT = B.ROOT_ALTERNATIVE

# The receipts this module reads, and nothing else. Named rather than globbed so
# that reading one more is a decision with a diff: whatever is in this tuple is
# what a comparison is entitled to talk about, and each one's digest is recorded
# in the output so a comparison quoted after the evidence moved is detectable.
#
# `model_contract.json` and not only `acceptance_contract.json`, because the
# model contract is what `commission.report` iterates and therefore what decided
# which checks ran -- and because it is written before the mesh is loaded
# (`runner.py:423`), so a formulation that died during measurement still has a
# full declaration and no report at all.
READS: tuple[str, ...] = (
    "model_contract.json",
    "acceptance_contract.json",
    "commission_report.json",
    "artifact_manifest.json",
    "final_status.json",
)

# The mandatory axis's three verdicts. None of them is about a part; all three
# are about whether two measurements are of the same thing.
COMPARABLE = "COMPARABLE"
INCOMPARABLE_CHECK_SETS = "INCOMPARABLE_CHECK_SETS"
INCOMPARABLE_EXPECTATIONS = "INCOMPARABLE_EXPECTATIONS"

# What a formulation's mandatory block can say. `NOT_RUN` is not a failure: no
# run has concluded in that directory, which is unequal evidence rather than a
# finding about a part.
MANDATORY_PASS = "PASS"
MANDATORY_NOT_RUN = "NOT_RUN"
MANDATORY_UNKNOWN_STALE = "UNKNOWN_STALE"


class CompareError(Exception):
    """A comparison that cannot be attempted, as opposed to one with a finding."""


# ---------------------------------------------------------------------------
# Reading one formulation
# ---------------------------------------------------------------------------

def _payload(path: Path) -> dict[str, Any] | None:
    """One receipt, or None where there is not one to read.

    Tolerant of a file that will not parse, for the reason `cli._final_status`
    is: a comparison has to be able to describe a directory whose receipt
    somebody has broken, and a command that raises instead cannot describe the
    one state a reader most needs described.
    """
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def read(work_dir: Path, *, project_dir: Path, alternative_id: str | None,
         model_name: str | None) -> dict[str, Any]:
    """Everything one formulation's own receipts say, and what they still bind.

    `derived` comes from `status.derive` over `bindings.broken` -- the same pair
    `design-tool status` uses, and deliberately not a second adjudication. A
    comparison that re-decided a formulation's status would be a gate wearing a
    report's clothes, and the third place in this build that could disagree
    about one verdict.
    """
    work_dir = Path(work_dir)
    state = B.current(work_dir, alternative_id=alternative_id,
                      model_name=model_name)
    stale = B.broken(work_dir, evidence_dir=project_dir,
                     alternative_id=alternative_id, model_name=model_name)
    receipts = {name: _payload(work_dir / name) for name in READS}
    return {
        "dir": work_dir,
        "receipts": receipts,
        "derived": STATUS.derive(receipts["final_status.json"], stale),
        "stale": stale,
        # Which run this formulation currently *is*, content-derived. Two
        # byte-identical siblings still have different identities -- the
        # alternative id is in the map -- which is exactly the case a
        # comparison must not collapse into one witness.
        "run_id": B.identity(state),
        "bindings": state,
        "digests": {name: (S.sha256_file(work_dir / name)
                           if (work_dir / name).is_file() else None)
                    for name in READS},
    }


def _checks(reading: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """This formulation's check rows, by check id."""
    report = reading["receipts"]["commission_report.json"]
    if not isinstance(report, dict):
        return {}
    return {str(row.get("check_id")): row
            for row in (report.get("checks") or ())
            if isinstance(row, dict) and row.get("check_id")}


def _declared(reading: dict[str, Any]) -> tuple[str, ...] | None:
    """The mandatory check set: the feature ids the contract obliged.

    From `model_contract.json`, the contract commissioning measured against.
    None -- not an empty tuple -- where no contract is on disk: a formulation
    nobody ran declared nothing, and reporting that as "declared no mandatory
    checks" would make it look like the least demanding contract in the set
    rather than like a formulation nobody ran.
    """
    contract = reading["receipts"]["model_contract.json"]
    if not isinstance(contract, dict) or not isinstance(contract.get("features"), list):
        return None
    return tuple(sorted(
        str(row["feature_id"]) for row in contract["features"]
        if isinstance(row, dict) and row.get("feature_id")
        # Read rather than assumed. Nothing in this build sets it False today
        # (`runner.py:770`, `:795` both pass True), so the filter is decorative
        # -- but the day an optional row becomes reachable, a comparison that
        # had hard-coded the assumption would silently start counting it as an
        # obligation.
        and row.get("mandatory", True)))


# ---------------------------------------------------------------------------
# The mandatory axis
# ---------------------------------------------------------------------------

def _yardstick(readings: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Were these formulations graded against the same rubric?

    Three faces of `docs/defects.md` D25, checked in the order that makes the
    report readable: a differing check *set* is a larger disagreement than a
    differing expectation for a check both declared, so it is named first and
    the verdict takes its name.
    """
    declared = {key: _declared(reading) for key, reading in readings.items()}
    absent = sorted(key for key, rows in declared.items() if rows is None)
    present = {key: frozenset(rows) for key, rows in declared.items()
               if rows is not None}

    if len(present) < 2:
        return {
            "verdict": COMPARABLE,
            "comparand": "the mandatory feature-id set of each model_contract.json",
            "declared_sets": {key: sorted(rows) for key, rows in sorted(present.items())},
            "shared": sorted(next(iter(present.values()))) if present else [],
            "only_in": {}, "expectations": {}, "no_contract_on_disk": absent,
            "note": "fewer than two formulations have a contract on disk, so no "
                    "pair of rubrics can disagree. That is unequal evidence, not "
                    "agreement.",
        }

    shared = frozenset.intersection(*present.values())
    only_in = {key: sorted(rows - shared) for key, rows in present.items()}
    sets_differ = any(only_in.values())

    # Same obligation, different rubric. Compared over the *contract's* feature
    # rows and contract-level expectations rather than over the check rows the
    # report projects from them, because the projection loses the half that
    # decides what was measured.
    #
    # Found by review, on the fixture this module was built around. A
    # `section_area` check publishes `expected = value_mm2` and puts the probe
    # height in its *title* (`commission.py`, "Section area at z=7.00"), so the
    # recorded knob -- whose root declares `grip-section` at z 7.0 and whose
    # `plate-seated` declares it at z 8.0, with the same area -- compared
    # **equal** on both feature rows. Two different sections of two different
    # parts, reported as one rubric. The same loss applies to `through_hole`
    # (`at`, `z_from`, `z_to`), `void_region`, `overhang`, `bore_by_displacement`
    # and `preservation`, whose whole region box is outside `expected`.
    #
    # The contract's `expectation` dict is the rubric itself, so comparing it
    # cannot lose a field by construction.
    expectations: dict[str, Any] = {}
    features = {key: _feature_rubrics(readings[key]) for key in present}
    for feature_id in sorted(shared):
        rows = {key: features[key].get(feature_id) for key in present}
        if any(row is None for row in rows.values()):
            continue
        spelled = {key: S.canonical_json(row) for key, row in rows.items()}
        if len(set(spelled.values())) > 1:
            check_id = f"feature-{feature_id}"
            expectations[check_id] = {
                "equal": False,
                "expected": {key: rows[key]["expectation"] for key in sorted(rows)},
                "tolerance": {key: rows[key]["tolerance"] for key in sorted(rows)},
                # What each formulation concluded against its own rubric. The
                # point of the row is that these verdicts are not comparable, so
                # they are shown together rather than left for a reader to find
                # in another block and assume they meet.
                "result": {key: (_checks(readings[key]).get(check_id) or {}).get("result")
                           for key in sorted(rows)},
            }
    # And the contract-level expectations the always-present structural checks
    # measure against, which belong to no feature row.
    for name, field in (("envelope", "expected_bbox_mm"),
                        ("bodies", "expected_bodies"),
                        ("envelope-band", "bbox_tolerance_mm")):
        stated = {key: (readings[key]["receipts"]["model_contract.json"] or {}).get(field)
                  for key in present}
        if any(value is None for value in stated.values()):
            continue
        if len({S.canonical_json(value) for value in stated.values()}) > 1:
            band = {key: (readings[key]["receipts"]["model_contract.json"] or {}
                          ).get("bbox_tolerance_mm") for key in present}
            expectations[name] = {
                "equal": False,
                "expected": dict(sorted(stated.items())),
                "tolerance": dict(sorted(band.items())),
                "result": {key: (_checks(readings[key]).get(name) or {}).get("result")
                           for key in sorted(present)},
            }

    if sets_differ:
        verdict, note = INCOMPARABLE_CHECK_SETS, (
            "these formulations declared different mandatory checks, so their "
            "coverage figures are ratios to different denominators and may not "
            "be read beside each other. What is comparable is the shared set; "
            "what is not is named per formulation.")
    elif expectations:
        verdict, note = INCOMPARABLE_EXPECTATIONS, (
            "these formulations declared the same mandatory checks and were "
            "measured against different expectations for some of them. Each "
            "PASS is a pass against a value that formulation declared for "
            "itself, so 'both passed' does not mean they passed the same thing.")
    else:
        verdict, note = COMPARABLE, (
            "every formulation declared the same mandatory checks and was "
            "measured against the same expectations and the same bands, so "
            "these verdicts may be read beside each other.")

    return {
        "verdict": verdict,
        "comparand": "the mandatory feature-id set of each model_contract.json, "
                     "then the frozen expectation and band of every check they "
                     "both reported",
        "why_not_coverage": (
            "coverage.fraction is covered/declared against a denominator each "
            "formulation chose for itself (commission.py:436, defect D24), and "
            "covered is not filtered to mandatory features (commission.py:437) "
            "so it is not bounded by 1.0 either. It is reported inside each "
            "formulation's own block and is never compared across them."),
        "declared_sets": {key: sorted(rows) for key, rows in sorted(present.items())},
        "shared": sorted(shared),
        "only_in": {key: rows for key, rows in sorted(only_in.items()) if rows},
        "expectations": expectations,
        "no_contract_on_disk": absent,
        "note": note,
    }


def _feature_rubrics(reading: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Each declared feature's rubric: what it expects and the band around it.

    Straight off `model_contract.json`, which is the contract commissioning
    measured against -- so this is the thing two formulations either agree on or
    do not, with no field lost to a projection on the way.
    """
    contract = reading["receipts"]["model_contract.json"]
    if not isinstance(contract, dict) or not isinstance(contract.get("features"), list):
        return {}
    return {str(row["feature_id"]): {"expectation": row.get("expectation"),
                                     "tolerance": row.get("tolerance")}
            for row in contract["features"]
            if isinstance(row, dict) and row.get("feature_id")}


def _mandatory(reading: dict[str, Any]) -> dict[str, Any]:
    """What one formulation promised to measure, and what happened when it did.

    The verdict is the commission verdict verbatim, weakened to
    `UNKNOWN_STALE` when the receipt carrying it no longer binds. Never
    recomputed and never softened otherwise: `commission.report` had the mesh in
    front of it and this does not.
    """
    report = reading["receipts"]["commission_report.json"]
    declared = _declared(reading)
    if not isinstance(report, dict):
        return {"verdict": MANDATORY_NOT_RUN, "stored_verdict": None,
                "declared_checks": declared, "self_coverage": None,
                "failed": [], "did_not_run": [],
                "note": "no commission report in this directory"}
    rows = list(_checks(reading).values())
    stored = report.get("verdict") or MANDATORY_NOT_RUN
    stale = "commission_report.json" in reading["stale"]
    return {
        "verdict": MANDATORY_UNKNOWN_STALE if stale else stored,
        "stored_verdict": stored,
        "declared_checks": declared,
        # Named `self_coverage` rather than `coverage` at the point of use, so
        # that a reader who scans the JSON cannot take two of these for
        # comparable numbers. It is a ratio to this formulation's own contract.
        "self_coverage": report.get("coverage"),
        "failed": sorted(str(row.get("check_id")) for row in rows
                         if row.get("result") == "FAIL"),
        # A declared check that did not run is not a check that passed, and it
        # is a different thing from a check nobody declared. Both matter to a
        # reader deciding whether two formulations were measured equally, and
        # the receipts distinguish them: a declared feature always gets a row
        # (`commission.py:427`), so `ran: false` is declared-and-unmeasured
        # while an absent row is never-declared.
        "did_not_run": sorted(str(row.get("check_id")) for row in rows
                              if not row.get("ran")),
        "note": ("the receipt carrying this verdict no longer binds, so what it "
                 "concluded is not what the files on disk support"
                 if stale else ""),
    }


# ---------------------------------------------------------------------------
# The other axes
# ---------------------------------------------------------------------------

def _claim(reading: dict[str, Any]) -> dict[str, Any]:
    """What one formulation is currently allowed to say about itself."""
    final = reading["receipts"]["final_status.json"] or {}
    derived = reading["derived"]
    current = derived["derived_status"] == derived["stored_status"]
    return {
        "status": derived["derived_status"],
        "stored_status": derived["stored_status"],
        # The claim only where it is still current. A claim string printed
        # beside a STALE status is the exact sentence a reader quotes and the
        # exact one that is no longer true; the stored one stays, under its own
        # name, as the record of what that run concluded.
        "allowed_claim": derived["allowed_claim"] if current else None,
        "stored_claim": None if current else derived["allowed_claim"],
        "lane_status": final.get("lane_status"),
    }


def _evidence(reading: dict[str, Any]) -> dict[str, Any]:
    """How much was actually looked at, and by what.

    14.7's third bullet, and the most valuable thing this build can compare
    today: it is the one difference between two formulations that a person
    cannot see by looking at the parts.
    """
    final = reading["receipts"]["final_status.json"] or {}
    return {
        "screening": final.get("screening"),
        "screening_calibrated": final.get("screening_calibrated"),
        "witnesses_rendered": final.get("witnesses_rendered"),
        "verification": final.get("verification"),
        "safety_verification": final.get("safety_verification"),
        "unavailable_checks": final.get("unavailable_checks") or [],
        # The names only. Which receipts stopped binding is the shape a reader
        # compares; the sentence under each names two truncated digests and is
        # prose, which two formulations cannot be set beside each other in.
        "stale_receipts": sorted(reading["stale"]),
    }


def _measured(reading: dict[str, Any]) -> dict[str, Any]:
    """The facts about the part that a run actually measured.

    Everything here was written by a run with the mesh in front of it. Nothing
    is estimated, policy-derived or invented: 8.5 requires objective
    measurements to be distinguishable from the other two kinds, and the way
    that rule is kept here is that this block contains only the first kind.

    `volume_mm3` comes off the volume screen, which on a job with no
    independently specified expected volume reports `NOT_APPLICABLE` and records
    the measurement anyway. So the number is a measurement with no calibrated
    gate behind it, and it carries the detector's own result rather than being
    presented as a check that passed.

    Read through `screening.detector` rather than by subscripting the receipt.
    This function used to do the latter, treating `screening.detectors` as a
    mapping keyed by detector name -- which no run has ever written. Every
    fixture that exercised this line had been authored to match the reader, so
    the error survived twenty-two of them and surfaced the first time the verb
    was pointed at a job the pipeline had actually run. See `docs/defects.md`
    D27.
    """
    report = reading["receipts"]["commission_report.json"] or {}
    manifest = reading["receipts"]["artifact_manifest.json"] or {}
    volume = SCR.detector(report, "volume") or {}
    return {
        "bbox_mm": manifest.get("bbox_mm"),
        "volume_mm3": volume.get("measured_mm3"),
        "volume_detector": volume.get("result"),
        "checks": {check_id: {"measured": row.get("measured"),
                              "expected": row.get("expected"),
                              "tolerance": row.get("tolerance"),
                              "result": row.get("result")}
                   for check_id, row in sorted(_checks(reading).items())},
    }


def _identical_designs(readings: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Formulations whose source is identical *right now*, grouped and named.

    Where two formulations are one design under two ids, their every measured
    value agrees, and without this block a reader takes that agreement for two
    independent designs reaching the same answer. It is one design counted
    twice, and it corroborates nothing.

    **This does not fire on the recorded knob, and this docstring used to claim
    it did.** `docs/defects.md` D28: the root and `as-drawn` were built from a
    byte-identical `model.py` and their receipts prove it -- both record
    `artifact_hashes.source = 1e9b9ea…` and the same candidate digest -- but
    `as-drawn`'s model was revised after its run concluded, and the grouping key
    is `bindings.current`, which reads the digest off disk *now*. So the two
    columns whose numbers are identical are the two this block stays silent
    about. Grouping on the digest the receipts were produced from is the fix,
    and it is not made here: it changes what a frozen recording says, so it
    gets its own slice and its own fixture.
    """
    groups: dict[str, list[str]] = {}
    for key, reading in readings.items():
        source = reading["bindings"].get("source")
        if source:
            groups.setdefault(str(source), []).append(key)
    return [{"members": sorted(members),
             "source_sha256": source,
             "note": "these formulations were built from the same source file. "
                     "They are one design under several ids, and their agreement "
                     "is not corroboration."}
            for source, members in sorted(groups.items()) if len(members) > 1]


def _preference(mandatory: dict[str, dict[str, Any]], yardstick: dict[str, Any],
                blocked: list[str]) -> dict[str, Any]:
    """Whether the measured differences may be read as a reason to prefer one.

    8.5 separates mandatory pass-or-failure from preference criteria and forbids
    a weighted total hiding the first behind the second. There is no total here,
    so the rule is kept a second way as well: where a formulation did not pass
    its own mandatory checks, or where the rubrics disagree, or where the axis
    that would decide cannot be measured at all, the measured block is still
    printed in full -- withholding a measurement somebody took would be its own
    dishonesty -- and it is marked as not a basis for preference, with the
    reason.
    """
    unfit = sorted(key for key, row in mandatory.items()
                   if row["verdict"] != MANDATORY_PASS)
    if unfit:
        return {"admissible": False, "because": (
            f"{', '.join(unfit)} did not pass its own mandatory checks, or has "
            "no current verdict. A formulation that uses less material or costs "
            "less to explore is not thereby preferable to one that passed: a "
            "preference criterion may not be weighed against a mandatory "
            "failure.")}
    if yardstick["verdict"] != COMPARABLE:
        return {"admissible": False, "because": (
            f"{yardstick['verdict']}: {yardstick['note']} Until the rubrics "
            "agree, or a person decides the difference does not matter, the "
            "measured differences below are real and are not a basis for "
            "preferring one.")}
    if blocked:
        return {"admissible": False, "because": (
            "the dimension that would decide between these formulations cannot "
            f"be measured by this build: {'; '.join(blocked)}. Every other axis "
            "may be equal and the comparison still settles nothing.")}
    return {"admissible": True, "because": (
        "every formulation passed the same mandatory checks against the same "
        "expectations, so what remains is preference. These are measurements, "
        "not a ranking: no weight is applied and no order is implied.")}


# ---------------------------------------------------------------------------
# What could not be compared at all
# ---------------------------------------------------------------------------

# A dimension is `DECIDING` when it is the axis a comparison of these
# formulations turns on. A comparison that cannot measure a deciding dimension
# settles nothing however much else it measures, and says so rather than
# reporting the axes it could reach as though they were the question.
DECIDING = "DECIDING"
CONTEXT = "CONTEXT"


def not_compared(project: P.Project,
                 measured: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    """One row per dimension this job exercises and this build cannot measure.

    6.14's rule is that a criterion a job does not exercise is *absent* from its
    comparison rather than scored zero, so every row here is guarded by a
    predicate over what the job actually declares. A single-material one-piece
    pair emits no material-count, sequence, assembly or tooling row at all --
    absent, not zero, and not "1 vs 1".
    """
    rows: list[dict[str, str]] = [
        {"dimension": "geometric difference between formulations",
         "standing": CONTEXT,
         "reason": "nothing in this build measures one formulation against "
                   "another. Surface distance, interference and region "
                   "correspondence have no instrument here: each formulation "
                   "was measured against its own contract and never against a "
                   "sibling.",
         "owner": "Release 6"},
        {"dimension": "print time and support toolpaths",
         "standing": CONTEXT,
         "reason": "there is no slicer adapter in this stack and there is not "
                   "going to be one (status.SLICER_DEPENDENT). A number here "
                   "would be fabricated rather than deferred.",
         "owner": "permanently absent"},
        {"dimension": "strength, serviceability, adjustability, irreversibility",
         "standing": CONTEXT,
         "reason": "no instrument anywhere in this build. 8.5 requires a "
                   "comparison to distinguish objective measurements from "
                   "policy-derived estimates from engineering judgment; these "
                   "are the third kind, they may appear only as a stated row "
                   "attributed to whoever stated it, and nothing states one on "
                   "this job.",
         "owner": "Release 9"},
    ]

    for modifier in sorted(frozenset(project.modifiers or ())
                           & frozenset(STATUS.SLICER_DEPENDENT)):
        if modifier == "supports":
            continue                        # already carried by the row above
        rows.append({
            "dimension": f"{modifier} boundary",
            "standing": DECIDING,
            "reason": f"this job declares the {modifier!r} modifier, and "
                      f"{STATUS.SLICER_DEPENDENT[modifier]} is resolved by a "
                      "slicer this stack does not have.",
            "owner": "permanently absent"})

    if project.source_mode == "MODIFY" or project.edit_scopes:
        rows.append({
            "dimension": "preservation of supplied geometry",
            "standing": DECIDING,
            "reason": "this job modifies supplied geometry, so preservation is "
                      "the axis a comparison of these formulations turns on -- "
                      "and it fails twice. On the only PHYSICALLY_PROVEN source "
                      "in this repository the audit cannot run at all "
                      "(docs/defects.md D22: legal cone faces OCC cannot "
                      "mesh). Where it can run, its sample density is a fixed "
                      "count rather than one derived from a declared minimum "
                      "detectable defect size, so the lane refuses a success "
                      "claim and both formulations report "
                      "EXPERIMENTAL_UNAVAILABLE. Comparing them is correct and "
                      "discriminates nothing.",
            "owner": "Release 6"})

    bodies = [(row["checks"].get("bodies") or {}).get("measured")
              for row in measured.values()]
    if any(isinstance(n, (int, float)) and n > 1 for n in bodies) \
            or len(project.components or ()) > 1:
        rows.append({
            "dimension": "assembly sequence, effort, tooling and hardware count",
            "standing": DECIDING,
            "reason": "this job has more than one body or component, so these "
                      "are dimensions it exercises -- and nothing in this build "
                      "measures any of them. They may appear only as a stated "
                      "row attributed to whoever stated it, never as a number "
                      "this pipeline invented.",
            "owner": "Release 8"})
    return rows


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def report(project: P.Project, readings: dict[str, dict[str, Any]],
           costs: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """`comparison.json`: five axes, each with its own verdict.

    Recomputable from disk at any moment, so there is nothing here to resume and
    nothing to invalidate. What it does record is each formulation's whole
    binding map, its `bindings.identity` and the digest of every receipt it read
    -- the identity covers inputs only, so a corrected `commission_report.json`
    would move the comparison with no binding broken, and the receipt digests
    are what catch that.
    """
    if len(readings) < 2:
        raise CompareError(
            "a comparison needs at least two formulations. This project has "
            f"{len(readings)}: {', '.join(sorted(readings)) or 'none'}. Declare "
            "a second with `design-tool branch --from . --id <id> --reason "
            "<why>`.")
    costs = dict(costs or {})
    mandatory = {key: _mandatory(reading) for key, reading in readings.items()}
    measured = {key: _measured(reading) for key, reading in readings.items()}
    yardstick = _yardstick(readings)
    rows = not_compared(project, measured)
    blocked = [row["dimension"] for row in rows if row["standing"] == DECIDING]

    contracts = {key: (reading["receipts"]["acceptance_contract.json"] or {})
                 for key, reading in readings.items()}
    digests = {key: payload.get("requirement_sha256")
               for key, payload in contracts.items()}
    bound = {digest for digest in digests.values() if digest}

    return {
        "schema_version": COMPARISON_SCHEMA,
        "job_id": project.job_id,
        "source_mode": project.source_mode,
        # Sorted, and sorted is not ranked. Said here because a reader looking
        # at a list is entitled to ask what its order means, and the answer has
        # to be in the file rather than in somebody's memory of it.
        "compared": sorted(readings),
        "built_nothing": True,
        "ranking": None,
        "score": None,
        "not_ranked": (
            "there is no total, no weight and no order in this file. Two "
            "formulations that differ are reported as differing; choosing "
            "between them is `design-tool branch --disposition`, which records "
            "who chose and on what basis."),
        "identical_designs": _identical_designs(readings),
        "shared": {
            "requirement_digest": sorted(bound)[0] if len(bound) == 1 else None,
            "same_requirement_digest": len(bound) == 1,
            "per_formulation": dict(sorted(digests.items())),
            "what_that_means": (
                "every formulation froze a contract binding the same digest of "
                "the shared requirements, so none of them weakened a "
                "requirement a sibling was held to. It does NOT mean the "
                "requirements were checked: they are bound as a digest and "
                "never individually measured, and the contract's rows are "
                "geometric proxies a designer chose. The honest sentence is "
                "'each formulation met the contract it froze, and all of them "
                "bind the same requirement digest' -- not 'all of them meet the "
                "requirement'."),
        },
        "axes": {
            "mandatory": {**yardstick,
                          "per_formulation": {key: _serialisable(row)
                                              for key, row in sorted(mandatory.items())}},
            "claim": {"per_formulation": {key: _claim(readings[key])
                                          for key in sorted(readings)}},
            "evidence": {"per_formulation": {key: _evidence(readings[key])
                                             for key in sorted(readings)}},
            "measured": {"per_formulation": dict(sorted(measured.items()))},
            "cost": {
                "verdict": "REPORTED_NOT_COMPARED",
                "note": "what a formulation cost to explore is a fact about the "
                        "process and not about the part. It is reported so that "
                        "exploration can be accounted for, and it is never a "
                        "tie-breaker: a cost column read as one is a weighted "
                        "total with a single weight.",
                "per_formulation": {key: costs.get(key) for key in sorted(readings)},
            },
        },
        "preference": _preference(mandatory, yardstick, blocked),
        "not_compared": rows,
        "issued_against": {
            key: {"run_id": reading["run_id"],
                  "bindings": dict(sorted(reading["bindings"].items())),
                  "receipts": dict(sorted(reading["digests"].items())),
                  "stale": {name: list(why)
                            for name, why in sorted(reading["stale"].items())}}
            for key, reading in sorted(readings.items())},
    }


def _serialisable(row: dict[str, Any]) -> dict[str, Any]:
    """Tuples to lists, so the payload round-trips through JSON unchanged."""
    return {key: (list(value) if isinstance(value, tuple) else value)
            for key, value in row.items()}
