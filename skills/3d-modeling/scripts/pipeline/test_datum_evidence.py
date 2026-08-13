#!/usr/bin/env python3
"""A datum and a measurement of it disagree, and neither one wins.

ADR 0003 decision 6, and §6.5 before it: *"Conflicting values remain separate until
they are deliberately resolved"*, and *"a measured candidate value must not replace
the requirement it is being measured against"*.

**What was missing, and why this needed a new field at all.** Nothing in the pipeline
read `Datum.value`. Production code touched four fields on a datum -- `datum_id`,
`derived_from`, `problems`, `valid_for` -- and the number itself was serialised into
the payload `requirement_sha256` covers and then never consulted. Observed rather
than grepped: a real MODIFY job with its datum set to a distinctive value put that
value in exactly one file, the author's own `project.json`, and in no receipt. So the
conflict this decision describes had no *site* -- no computation for a disagreement to
occur in -- and a fixture asserting one would have compared a number in a hash payload
against a number in a receipt with no code path joining them.

`Requirement.observes_datum_id` is that join, and deliberately the narrowest one that
works: *this MEASURED row is an observation of that datum's value*. Not "this
dimension was measured from this datum", which is a different relationship. Never
inferred from matching names, units or artifacts, because guessing it would
manufacture an authority claim the job never made.

Entirely L0 by ruling: no CAD, no child process, no heavy tier. `decide` is called
directly with synthetic reports, the way the existing status tests do it.

Subtests rather than a method per case, throughout: `conftest.py` capped what L0 may
collect at 1240 when this file was written, and the first draft put collection at
1246. The cap has since been raised, but the reason to prefer a subtest has not: the
cases inside each method are variations on one rule, which is exactly what a subtest is for.
"""
from __future__ import annotations

import unittest

from . import project as P
from . import schemas as S
from . import status as ST
from .contract import Contract

UTC = "2026-01-01T00:00:00Z"


def _datum(**over) -> P.Datum:
    base = dict(datum_id="pocket-face", value=13.7311, unit="mm",
                provenance="MEASURED", derived_from=None, valid_for=("src",),
                note="")
    base.update(over)
    return P.Datum(**base)


def _requirement(**over) -> P.Requirement:
    base = dict(name="pocket-depth", value=11.4, unit="mm", provenance="MEASURED",
                source="calipers, second pass", observes_datum_id="pocket-face")
    base.update(over)
    return P.Requirement(**base)


def _project(*, datums=None, requirements=None, datum_ids=("pocket-face",)) -> P.Project:
    """A MODIFY job whose one edit scope references the datum under test.

    MODIFY because a datum is reachable only through `EditScope.datum_ids`, which is
    also what makes "referenced by a scope" a meaningful distinction below.
    """
    return P.Project(
        job_id="d6", updated_utc=UTC, source_mode="MODIFY",
        consequence="INCONSEQUENTIAL",
        consequence_rationale="a desk block; failure wastes material",
        printer="Test Printer", material={"process": "FDM", "material": "PLA"},
        nozzle={"diameter_mm": 0.4},
        orientation={"model_to_printer_matrix": "identity", "bed_z_mm": 0.0},
        template=None, parameters={}, model="model.py",
        envelope_mm={"x": 60.0, "y": 50.0, "z": 20.0},
        reviewer={"model_snapshot": "test"},
        requirements=(_requirement(),) if requirements is None else requirements,
        source_artifacts=(P.SourceArtifact(
            artifact_id="src", path="source.stl", format="STL",
            classification="USABLE_MESH"),),
        datums=(_datum(),) if datums is None else datums,
        edit_scopes=(P.EditScope(
            artifact_id="src", region="the pocket face",
            region_box={"min": [0.0, 0.0, 0.0], "max": [5.0, 5.0, 5.0]},
            datum_ids=datum_ids, mesh_fallback_allowed=True,
            preserve=("everything outside the pocket",)),),
    )


def _contract() -> Contract:
    """The smallest contract `decide` will accept, built field by field.

    Not `runner._contract_from(...)` like the older status tests: that pulls in a
    template and a request, and the ruling put this fixture at L0 with no CAD and no
    child process. Nothing here is measured against the contract -- `decide` reads its
    identity and `consequence` -- so hand-building one is honest rather than a stub
    pretending to be a real job.
    """
    return Contract(
        job_id="d6", template="none", template_version="1", domain_id="test",
        backend="authored", parameters={}, features=(),
        expected_bbox_mm={"x": 60.0, "y": 50.0, "z": 20.0},
        bbox_tolerance_mm=0.5, expected_bodies=1,
        orientation={"model_to_printer_matrix": "identity", "bed_z_mm": 0.0},
        material={"process": "FDM", "material": "PLA"},
        nozzle={"diameter_mm": 0.4}, printer="Test Printer", modifiers=(),
        minimum_coverage=0.0, step_required=False,
        consequence="INCONSEQUENTIAL", updated_utc=UTC)


def _decide(conflicts, *, verdict="PASS"):
    contract = _contract()
    return ST.decide(
        contract=contract,
        commission_report={"verdict": verdict, "witness": {"rendered": True}},
        screening={"overall": "CLEAR", "calibrated": True},
        manufacturing=None, safety=None,
        artifact={"contract_sha256": contract.contract_hash(),
                  "stl_sha256": "b", "source_sha256": "c"},
        verification=None, updated_utc=UTC,
        datum_conflicts=conflicts)


class BothDeclarationsSurviveTest(unittest.TestCase):
    """The conflict is derived and reported, and resolved by nobody here."""

    def test_a_disagreement_is_retained_whole_and_nothing_picks_a_side(self) -> None:
        project = _project()
        # The project itself is well-formed. Neither declaration is a mistake, which
        # is why this cannot be an `Issue`: a validation error means the project is
        # malformed, and this one is not.
        self.assertEqual([], [p for p in project.validate(None) if p.severity == "error"],
                         "both sides are valid declarations")

        rows = P.datum_conflicts(project)
        self.assertEqual(1, len(rows), rows)
        row = rows[0]
        self.assertEqual(
            {"datum_id": "pocket-face", "measurement_requirement": "pocket-depth",
             "datum_value": 13.7311, "datum_unit": "mm",
             "measurement_value": 11.4, "measurement_unit": "mm",
             "datum_provenance": "MEASURED",
             "measurement_source": "calipers, second pass",
             "state": "UNRESOLVED"},
            row, "both declarations, named, with no verdict between them")
        # Neither value is overwritten in the model it came from, and no field here
        # resolves anything -- asserted on the whole row above, so a later winner
        # field cannot be added without this failing.
        self.assertEqual(13.7311, project.datums[0].value)
        self.assertEqual(11.4, project.requirements[0].value)

        for label, datums, requirements, ids, expected in (
                # Exact `(value, unit)` equality, and nothing is converted: `10 mm`
                # against `1 cm` stays a conflict. Conservative on purpose --
                # converting would choose between two authorities by arithmetic and
                # drag this slice into the tolerance work §7 explicitly left open.
                ("identical", (_datum(value=11.4),), (_requirement(value=11.4),),
                 ("pocket-face",), 0),
                ("same length, other unit", (_datum(value=10.0, unit="mm"),),
                 (_requirement(value=1.0, unit="cm"),), ("pocket-face",), 1),
                ("equal number, other unit", (_datum(value=10.0, unit="mm"),),
                 (_requirement(value=10.0, unit="cm"),), ("pocket-face",), 1),
                # §13.4 binds the datums a scope references, and those are the ones
                # this job's identity rests on. Withholding this job's claim over a
                # datum it does not edit against would let an unrelated correction
                # cut a revision here.
                ("datum no scope references", None, None, (), 0),
                # The relationship is declared or it does not exist. This row is
                # MEASURED, in the same unit, against a referenced datum, and
                # disagrees by 2.3 mm -- every circumstantial sign of being an
                # observation of it -- and it still yields nothing, because it does
                # not say so. Inferring the link from matching names, units or
                # artifacts would invent an authority claim the job never made, and
                # would then withhold a claim on the strength of the invention.
                ("measured, disagreeing, but never declared as an observation",
                 None, (_requirement(observes_datum_id=None),), ("pocket-face",), 0),
        ):
            with self.subTest(case=label):
                self.assertEqual(expected, len(P.datum_conflicts(_project(
                    datums=datums, requirements=requirements, datum_ids=ids))))


class TheLinkIsDeclaredAndCheckedTest(unittest.TestCase):
    """An observation is claimed explicitly, or it is not claimed at all."""

    def test_a_link_that_cannot_mean_what_it_says_is_refused(self) -> None:
        for label, requirement, needle in (
                # `MEASURED` only. A `STATED` or `CHOSEN` row pointing at a datum is
                # a second copy of the number, not evidence about it -- and two
                # authorities for one value is what §6.5 exists to prevent.
                ("stated", _requirement(provenance="STATED"), "observes_datum_id"),
                ("chosen", _requirement(provenance="CHOSEN"), "observes_datum_id"),
                ("blank", _requirement(observes_datum_id="   "), "names no datum"),
        ):
            with self.subTest(case=label):
                problems = requirement.problems(0)
                self.assertTrue(any(needle in p.where or needle in p.message
                                    for p in problems), problems)

        # A reference resolving to nothing would read as agreement: the derivation
        # finds no partner and emits no row, which is indistinguishable from the two
        # values matching. So the refusal belongs in validation, where a dangling
        # reference already is one.
        with self.subTest(case="undeclared datum"):
            problems = _project(
                requirements=(_requirement(observes_datum_id="no-such"),)
            ).validate(None)
            self.assertTrue(any("observes_datum_id" in p.where for p in problems),
                            [p.message for p in problems])

        # Absent, not null. Every requirement is serialised into the payload
        # `requirement_sha256` covers, so `asdict`'s `observes_datum_id: null` on
        # rows that never heard of this slice would move every stored contract hash
        # in the repository -- and a digest cannot tell a key that is missing from
        # one that was never meant.
        with self.subTest(case="the key is absent when nothing is observed"):
            plain = P.Requirement(name="w", value=1.0, unit="mm",
                                  provenance="STATED", source="the brief")
            self.assertNotIn("observes_datum_id", plain.as_dict())
            self.assertEqual("pocket-face",
                             _requirement().as_dict()["observes_datum_id"])

        # And it has to survive being written down, which is where this slice was
        # actually broken. `as_dict` emitted the link and `from_payload` dropped it,
        # so a saved project reloaded without an observation: no link, no conflict,
        # agreement reported, and a real CLI run free to claim success over the
        # disagreement every assertion above catches. Nothing here saw it, because
        # every fixture built `Requirement` objects in memory and never crossed
        # serialisation. So the round trip is asserted on the *conflict*, not just on
        # the field -- the field surviving is only interesting because the behaviour
        # depends on it.
        with self.subTest(case="the link and the conflict survive a round trip"):
            before = _project()
            reloaded = P.from_payload(before.as_payload())
            self.assertEqual("pocket-face",
                             reloaded.requirements[0].observes_datum_id)
            self.assertEqual(P.datum_conflicts(before),
                             P.datum_conflicts(reloaded),
                             "a reloaded project must reach the same verdict")
            self.assertEqual(1, len(P.datum_conflicts(reloaded)))

        with self.subTest(case="an absent link stays absent across a round trip"):
            plain_project = _project(requirements=(
                _requirement(observes_datum_id=None),))
            reloaded = P.from_payload(plain_project.as_payload())
            self.assertIsNone(reloaded.requirements[0].observes_datum_id)
            self.assertNotIn("observes_datum_id",
                             reloaded.requirements[0].as_dict())

        # Refused, not coerced. `str(4)` would make "4" a datum id that names
        # nothing, and `validate` would then blame the reference rather than the file
        # that carried it -- a misdirected error being worse than a clear refusal.
        with self.subTest(case="a non-string id is refused rather than coerced"):
            payload = _project().as_payload()
            payload["requirements"][0]["observes_datum_id"] = 4
            with self.assertRaises(S.SchemaError):
                P.from_payload(payload)


class AnUnresolvedConflictWithholdsTheClaimTest(unittest.TestCase):
    """Withheld through the path that already exists for exactly this.

    Shaped like the experimental lane cap: the reason is appended on every verdict,
    but only a *successful* verdict is downgraded. `FAILED` is a finding the run is
    entitled to report, and replacing it with a conflict notice would hide a real
    defect behind a bookkeeping one.
    """

    def test_a_success_is_withheld_and_a_finding_is_not_overwritten(self) -> None:
        conflicts = P.datum_conflicts(_project())
        self.assertEqual(1, len(conflicts), "the fixture must actually conflict")

        for label, verdict, expected in (
                ("a success cannot be claimed", "PASS", "NEEDS_MORE_EVIDENCE"),
                # The stronger finding survives, which is the half that stops this
                # guard from hiding defects.
                ("a failure stays failed", "FAIL", "FAILED"),
        ):
            with self.subTest(case=label):
                final = _decide(conflicts, verdict=verdict)
                self.assertEqual(expected, final["final_status"])
                self.assertNotIn(final["final_status"], ST.CLAIMS_SUCCESS)
                self.assertEqual(list(conflicts), final["datum_conflicts"],
                                 "both declarations travel with the receipt")
                self.assertTrue(
                    any("datum/evidence conflict" in r for r in final["reasons"]),
                    f"visible on a {expected} receipt too: {final['reasons']}")

        # The converse, without which none of the above proves anything: a test that
        # only ever passed conflicts could not tell a withholding guard from a status
        # layer that always says NEEDS_MORE_EVIDENCE.
        with self.subTest(case="agreement leaves the claim alone"):
            final = _decide(())
            self.assertEqual("COMMISSIONED", final["final_status"])
            self.assertEqual([], final["datum_conflicts"])
            self.assertFalse(
                any("datum/evidence conflict" in r for r in final["reasons"]),
                final["reasons"])

        # Resolution is deliberate: somebody corrects a declaration and it clears.
        # That is the whole shape of §6.5 -- the conflict persists until a human
        # decides, and nothing in the pipeline decides for them.
        with self.subTest(case="correcting the measurement clears it"):
            agreed = _project(requirements=(_requirement(value=13.7311),))
            self.assertEqual((), P.datum_conflicts(agreed))
            self.assertEqual("COMMISSIONED",
                             _decide(P.datum_conflicts(agreed))["final_status"])


if __name__ == "__main__":
    unittest.main()
