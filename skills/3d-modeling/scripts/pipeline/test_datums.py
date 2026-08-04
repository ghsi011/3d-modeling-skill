#!/usr/bin/env python3
"""ADR 0003: a datum is evidence with a provenance and a scope.

The ADR was accepted and nothing implemented it. `ROADMAP.md`'s Release 5 names
two declaration obligations and this is one of them, with the reason stated
plainly: *"a region with no disposition and a datum with no provenance are the
two ways a job can arrive at Release 6 with nothing to judge it by."*

The failure the ADR was written from is worth restating, because every test here
is one of its edges. A job coordinated two edit scopes across two artifacts by
writing the same number into both. The source file was then rewritten mid-job.
Under revision 1 a correct part came out; under revision 2 the same declaration
produced three bosses that must not exist, and nothing detected it -- because
nothing recorded which revision the number had been measured on, and because
there were two copies of one number so the second to be corrected was the one
that shipped.

The ADR takes seven decisions. Four of them are declaration obligations and are
what this file covers:

1. a datum records where it came from (§6.5 provenance classes), and a number
   with no recorded provenance is an assumption -- permitted, labelled, and
   carrying an owner and the check that would settle it;
2. a datum read off geometry names the artifact **and the revision** it was read
   on: required of `INHERITED`, permitted of `MEASURED`, refused of the rest;
3. a datum states the scope it may be used in, and that scope names something
   the job declares;
4. coordinated scopes reference one datum identity rather than each holding a
   copy.

**Decisions 5 and 6 are not implemented, and that is not an omission this file
gets to be quiet about.** Decision 5 -- datums join §13.4's dependency-binding
list, so changing one invalidates the results that rested on it -- is Release 6
by the ADR's own Consequences: *"Release 6 carries the invalidation obligation,
because that is where a `MODIFY` job may claim success."* What exists here is
the near half of it: the acceptance contract binds *which* datum an edit was
placed against, so re-placing an edit invalidates the answer, while changing the
datum's **value** does not. Decision 6 -- that precedence between a datum and
other evidence is a property of the authoritative model and not of the file --
is satisfied by construction today, in that nothing grants a datum authority over
measured evidence, and enforced by nothing. `ROADMAP.md`'s Release 5 section
records both gaps and why the `EXPERIMENTAL_UNAVAILABLE` cap makes them safe;
`TheContractBindsWhichDatumTheEditWasPlacedAgainstTest` asserts that cap rather
than trusting it.

Decision 7 decides nothing to build. What is deliberately *not* here: measuring
anything against a datum. These are declaration obligations, and a declaration
that cannot be checked is the thing this file exists to stop.
"""
from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import tempfile
import unittest
from pathlib import Path

from . import cli
from . import execution as EX
from . import findings as F
from . import project as P
from . import schemas as S
from .test_alternatives import SCREW, _author, _laid_out, _project
from .test_execution_plan import POCKETS, SECOND_ARTIFACT, SOURCE_ARTIFACT

UTC = "1970-01-01T00:00:00Z"


def _datum(**over) -> P.Datum:
    base = dict(datum_id="magnet-pocket-face", value=12.4, unit="mm",
                provenance="MEASURED", derived_from=None,
                valid_for=("src",), note="")
    base.update(over)
    return P.Datum(**base)


def _placed(**over) -> P.Project:
    """A project that declares the rows its datums are scoped to.

    `valid_for` must name an artifact, component or interface the job declares,
    so a fixture scoping a datum to an artifact the job does not declare
    is not a project anyone could write -- it is the malformed declaration the
    check exists to refuse. These two artifacts and one interface are the same
    ones the execution-plan fixtures use, so a reader comparing the two files is
    reading one job.
    """
    base = dict(source_mode="MODIFY", model="model.py",
                source_artifacts=(SOURCE_ARTIFACT, SECOND_ARTIFACT),
                interfaces=(POCKETS,))
    base.update(over)
    return _project(**base)


def _assumed(**over) -> P.Datum:
    """A datum somebody chose, complete: owner and settling check included."""
    base = dict(provenance="CHOSEN", derived_from=None,
                owner="print engineer",
                settled_by="calipers across the magnet pocket once one exists")
    base.update(over)
    return _datum(**base)


def _codes(problems) -> set[str]:
    return {row.code for row in problems}


def _status(directory: Path) -> dict:
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        cli.status([str(directory), "--json"])
    return json.loads(stream.getvalue())


def _at(problems, prefix: str) -> set[str]:
    """The codes reported *at* a field path.

    By path, not by code alone. A project fixture reports several unrelated
    findings -- an edit scope naming an artifact no source declares raises its
    own `REF_UNDECLARED` -- and a test asserting only that some code appeared
    would be reading a different finding and calling it this one.
    """
    return {row.code for row in problems if row.where.startswith(prefix)}


class ADatumRecordsWhereItCameFromTest(unittest.TestCase):
    """ADR 0003 decision 1, and its deliberate permission."""

    def test_a_datum_carries_one_of_the_projects_provenance_classes(self) -> None:
        self.assertEqual([], _datum().problems())
        self.assertEqual(
            {F.SCHEMA_ENUM},
            _codes(_datum(provenance="ASSUMED_OBVIOUSLY").problems()),
            "the classes are the ones every other design-driving value uses; a "
            "sixth invented here would be a second vocabulary for one idea")

    def test_a_datum_with_no_provenance_is_the_assumption_not_a_refusal(self) -> None:
        """ADR 0003 decision 1 and 6.4, in the same words: *"A datum with no
        recorded provenance is an assumption. It may still be used -- the ADR
        does not forbid it -- but it is recorded as one."*

        The first version of this file refused it, while `cli.py` cited that very
        sentence as the reason assumptions are reported by `status` rather than
        by `validate`. So the code and its own comment disagreed, and `status`
        managed to both refuse the job and hide the one thing the sentence is
        about.

        Refusing it is not a stricter reading of the ADR -- it is a different
        rule. The third option the ADR names is to *label* it, which is neither
        defaulting nor refusing, and it is the one that keeps an unrecorded
        number distinguishable from a measurement.
        """
        blank = _assumed(provenance="")
        self.assertEqual([], blank.problems())
        self.assertTrue(blank.is_assumption)

    def test_the_unrecorded_number_still_owes_an_owner_and_a_check(self) -> None:
        """Permitted is not free. 6.4 attaches both obligations to exactly this
        case, and without them it is a number in a list nobody can act on."""
        self.assertEqual({F.SCHEMA_REQUIRED},
                         _codes(_datum(provenance="").problems()))

    def test_an_assumption_is_reported_where_somebody_would_look(self) -> None:
        """*"It may still be used ... but it is recorded as one"* -- and a
        record nothing surfaces is not one.

        Not through `validate`. Every caller of it here refuses the run on a
        non-empty list, warning severity included, and the ADR says plainly that
        a job whose datum has no provenance is **not refused**. So the place a
        person asks what a job is resting on is where it goes.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            dataclasses.replace(_placed(), datums=(
                _assumed(datum_id="guessed-clearance", owner="print engineer",
                         settled_by="calipers on the printed magnet pocket"),
                _datum(datum_id="magnet-pocket-face", provenance="MEASURED"),
            )).save(directory)
            self.assertEqual(
                [{"datum_id": "guessed-clearance", "owner": "print engineer",
                  "settled_by": "calipers on the printed magnet pocket"}],
                _status(directory)["assumptions"],
                "the chosen number is named and the measured one is not; a "
                "list naming both would say nothing. And it carries who "
                "settles it and how, or it is a list nobody can act on")

    def test_a_job_with_no_assumptions_says_so_by_saying_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            _placed().save(directory)
            self.assertEqual([], _status(directory)["assumptions"])

    def test_an_assumption_is_permitted_and_is_labelled(self) -> None:
        """ADR 0003: *"A datum with no recorded provenance is an assumption. It
        may still be used -- the ADR does not forbid it -- but it is recorded as
        one."*

        So `CHOSEN` loads clean and `is_assumption` says so. A rule that refused
        assumptions outright would be refused by every job that has one, and the
        declaration would move into a note where nothing can read it.
        """
        chosen = _assumed()
        self.assertEqual([], chosen.problems())
        self.assertTrue(chosen.is_assumption)
        self.assertFalse(_datum(provenance="MEASURED").is_assumption)

    def test_an_assumption_names_an_owner_and_the_check_that_settles_it(self) -> None:
        """`ARCHITECTURE.md` 6.4, stated and not implied: *"It may still be
        used, and it is named as an assumption, **with an owner and with the
        check that would settle it**."*

        Without those two an assumption is a number in a list nobody can act
        on, which is what a `note` already was. With them the status report is
        a work item: who resolves it, and what resolving it means.
        """
        for missing in ({"owner": ""}, {"settled_by": ""},
                        {"owner": "", "settled_by": ""}):
            with self.subTest(**missing):
                self.assertEqual(
                    {F.SCHEMA_REQUIRED},
                    _codes(_assumed(**missing).problems()))

    def test_a_measured_datum_owes_neither(self) -> None:
        """The obligation is the assumption's. A number somebody measured is
        already settled, and requiring it to name a settling check would make
        every honest datum invent one."""
        self.assertEqual([], _datum(provenance="MEASURED", owner="",
                                    settled_by="").problems())


class ADerivedDatumNamesTheRevisionTest(unittest.TestCase):
    """ADR 0003 decision 2 -- the edge the original failure turned on."""

    def test_a_derived_datum_must_name_the_artifact_and_the_revision(self) -> None:
        self.assertEqual(
            {F.SCHEMA_REQUIRED},
            _codes(_datum(provenance="INHERITED", derived_from=None).problems()),
            "INHERITED means read out of a supplied artifact, and one that does "
            "not say which artifact at which revision is the assumption that "
            "produced three bosses")
        for missing in ({"artifact_id": "", "revision": 1},
                        {"artifact_id": "src", "revision": None},
                        {"artifact_id": "src", "revision": 0}):
            with self.subTest(derived_from=missing):
                self.assertTrue(_datum(provenance="INHERITED",
                                       derived_from=missing).problems())

    def test_a_complete_derived_datum_loads_clean(self) -> None:
        self.assertEqual([], _datum(
            provenance="INHERITED",
            derived_from={"artifact_id": "src", "revision": 1}).problems())

    def test_a_datum_nobody_derived_may_not_claim_a_revision(self) -> None:
        """A stated number has no artifact revision, and saying it does is a
        provenance claim the value cannot support."""
        for provenance in ("STATED", "CHOSEN"):
            with self.subTest(provenance=provenance):
                self.assertIn(
                    F.INTENT_CONTRADICTION,
                    _codes(_assumed(provenance=provenance,
                                    derived_from={"artifact_id": "src",
                                                  "revision": 1}).problems()))

    def test_a_measured_datum_may_name_the_revision_it_was_measured_on(self) -> None:
        """The one the first version of this file got backwards, and the class
        the ADR was written from.

        `MEASURED` covers 6.5's *"measured from supplied evidence"* and
        *"measured from generated geometry"* -- both taken off geometry, both
        with a revision to be valid against. The incident was exactly that: a
        field *"derived from the drawer before the drawer was modified"*, which
        is a measurement off the job's own geometry.

        It is not *required*, because calipers on a physical part have no
        artifact revision to name. Refusing it, which is what this used to do,
        inverted the incentive on the one class that most needs the field: the
        honest row was refused and the vague one validated clean, so the only
        way to record a revision was to relabel the number `INHERITED` -- a
        provenance the value cannot support, which is the thing being checked
        for.
        """
        self.assertEqual([], _datum(
            provenance="MEASURED",
            derived_from={"artifact_id": "src", "revision": 2}).problems(),
            "the honest declaration must not be the refused one")
        self.assertEqual([], _datum(provenance="MEASURED").problems(),
                         "and it stays optional, or calipers have to invent one")

    def test_a_revision_of_true_is_not_a_revision_of_one(self) -> None:
        """`isinstance(True, int)` is True in Python, so without the explicit
        bool check `revision: true` reads as revision 1 -- a revision number
        nobody wrote, on the field the three bosses turned on."""
        self.assertIn(F.SCHEMA_TYPE, _codes(_datum(
            provenance="INHERITED",
            derived_from={"artifact_id": "src",
                          "revision": True}).problems()))

    def test_a_datum_with_no_id_cannot_be_referenced(self) -> None:
        self.assertIn(F.SCHEMA_REQUIRED, _codes(_datum(datum_id="  ").problems()))

    def test_the_number_the_whole_construct_carries_is_checked(self) -> None:
        """`Requirement` validates exactly this and `Datum` did not -- it checked
        the id, the provenance, the revision and the scope, and never the value.
        A datum whose number is `None` is a reference to nothing.

        Asserted by code and not by truthiness. `True` is an `int` in Python, so
        without its own branch it reaches the finite-number check and is reported
        as *"not a finite real number"* -- true of nothing a reader would call
        `true`, and a mutation that removed the branch survived a test asserting
        only that something fired.
        """
        for value, code in ((None, F.SCHEMA_TYPE), (True, F.SCHEMA_TYPE),
                            ("", F.SCHEMA_TYPE), (float("nan"),
                                                  F.SCHEMA_NON_FINITE)):
            with self.subTest(value=value):
                self.assertIn(code, _codes(_datum(value=value).problems()))
        self.assertEqual([], _datum(value="the moulded face").problems(),
                         "a named reference is a legitimate datum value")

    def test_a_number_with_no_unit_is_refused(self) -> None:
        self.assertIn(F.SCHEMA_REQUIRED,
                      _codes(_datum(value=12.4, unit=" ").problems()))
        self.assertEqual([], _datum(value="the moulded face", unit="").problems(),
                         "a unit on a named reference would be an invented one")


class ADatumStatesItsScopeTest(unittest.TestCase):
    """ADR 0003 decision 3: evidence carries the scope it was taken in."""

    def test_a_datum_valid_for_nothing_is_refused(self) -> None:
        self.assertEqual({F.SCHEMA_REQUIRED},
                         _codes(_datum(valid_for=()).problems()),
                         "a datum that may be used to place anything is a datum "
                         "with no scope, which is what 6.12 forbids")

    def test_the_scope_may_name_an_artifact_a_component_or_an_interface(self) -> None:
        """Named for what it establishes, which is only that these load.

        It used to be named the same and assert `[] == problems()` -- true of
        *any* non-empty tuple, so it established nothing beyond what
        `test_a_datum_valid_for_nothing_is_refused` already did, while its name
        claimed the three kinds were understood. What makes the claim real is
        `TheScopeIsCheckedAgainstWhatTheJobDeclaresTest` below, where an
        interface-scoped datum is actually usable by the scopes that realize it.
        """
        for scope in (("src",), ("src", "drawer"),
                      ("magnet-pockets",)):
            with self.subTest(valid_for=scope):
                self.assertEqual([], _datum(valid_for=scope).problems())

    def test_a_bare_string_of_scopes_names_the_field_not_its_letters(self) -> None:
        """`tuple("src")` is nine scopes. `_ids` exists in this file for
        exactly that and `datum_ids` uses it; `valid_for` bypassed it, so a
        malformed declaration recorded nine bogus scopes as clean -- and a
        non-list crashed `design-tool status` with an unhandled TypeError
        instead of naming the field."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            dataclasses.replace(_placed(), datums=(_datum(),)).save(directory)
            payload = json.loads((directory / P.PROJECT_FILE)
                                 .read_text(encoding="utf-8"))
            for bad in ("src", 7):
                with self.subTest(valid_for=bad):
                    payload["datums"][0]["valid_for"] = bad
                    (directory / P.PROJECT_FILE).write_text(
                        json.dumps(payload), encoding="utf-8")
                    with self.assertRaises(S.SchemaError) as caught:
                        P.load(directory)
                    self.assertIn("datums[0].valid_for", str(caught.exception))


class TheProjectRefusesADatumNobodyCanUseTest(unittest.TestCase):
    """The rows have to reach `Project.validate`, or none of the above runs."""

    def _project_with(self, datums, **over) -> P.Project:
        return dataclasses.replace(_placed(**over), datums=tuple(datums))

    def test_two_datums_may_not_claim_one_id(self) -> None:
        """Decision 4's precondition: an identity two rows answer to is not one."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            project = self._project_with([_datum(), _datum(value=12.9)])
            self.assertIn(F.REF_DUPLICATE,
                          _codes(project.validate(directory,
                                                  require_buildable=False)))

    def test_a_scope_referencing_no_declared_datum_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            scope = P.EditScope(artifact_id="src", region="pocket",
                                datum_ids=("no-such-datum",))
            project = dataclasses.replace(
                self._project_with([_datum()]), edit_scopes=(scope,))
            self.assertIn(F.REF_UNDECLARED,
                          _at(project.validate(directory,
                                               require_buildable=False),
                              "edit_scopes[0].datum_ids"))

    def test_a_scope_may_reference_a_declared_datum(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            scope = P.EditScope(artifact_id="src", region="pocket",
                                datum_ids=("magnet-pocket-face",))
            project = dataclasses.replace(
                self._project_with([_datum()]), edit_scopes=(scope,))
            self.assertEqual(set(),
                             _at(project.validate(directory,
                                                  require_buildable=False),
                                 "edit_scopes[0].datum_ids"),
                             "the datum is declared, so nothing is reported "
                             "against the reference itself")


class TheScopeIsCheckedAgainstWhatTheJobDeclaresTest(unittest.TestCase):
    """Decision 3 says artifacts, components *and* interfaces. Only one worked.

    The scope check compared `valid_for` against `scope.artifact_id` alone, so a
    datum scoped to the interface both coordinated scopes realize -- the exact
    shape decision 4 is about -- was refused by both of them. And nothing
    checked `valid_for`'s contents at all, so a datum valid for `"nobody"` was a
    clean declaration that no scope could ever use.
    """

    def _with(self, datums, scopes) -> P.Project:
        return dataclasses.replace(_placed(), datums=tuple(datums),
                                   edit_scopes=tuple(scopes))

    def test_a_datum_scoped_to_an_interface_is_usable_by_the_scopes_realizing_it(
            self) -> None:
        from .test_execution_plan import POCKETS
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            scopes = tuple(
                P.EditScope(artifact_id=artifact, region="magnet pocket",
                            interface_ids=("magnet-pockets",),
                            datum_ids=("magnet-pocket-face",))
                for artifact in ("src", "drawer"))
            project = dataclasses.replace(
                self._with([_datum(valid_for=("magnet-pockets",))], scopes),
                interfaces=(POCKETS,))
            reported = project.validate(directory, require_buildable=False)
            self.assertEqual(
                set(), _at(reported, "edit_scopes[0].datum_ids")
                | _at(reported, "edit_scopes[1].datum_ids"),
                "the datum is scoped to the interface these two scopes realize, "
                "which is the coordinated case the ADR exists for")

    def test_a_scope_naming_nothing_the_job_declares_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            project = self._with([_datum(valid_for=("nobody",))], ())
            self.assertIn(F.REF_UNDECLARED,
                          _at(project.validate(directory,
                                               require_buildable=False),
                              "datums[0].valid_for"))

    def test_the_artifact_a_datum_was_derived_from_must_be_declared(self) -> None:
        """*"the field that failed"*, in the ADR's own words, and the one field
        in this slice's neighbourhood with no referential check: every other id
        reference here is checked against the rows that declare it."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            project = self._with([_datum(
                provenance="INHERITED",
                derived_from={"artifact_id": "no-such-file", "revision": 99},
                valid_for=("src",))], ())
            self.assertIn(
                F.REF_UNDECLARED,
                _at(project.validate(directory, require_buildable=False),
                    "datums[0].derived_from.artifact_id"))


class OneDatumIsOneObjectTest(unittest.TestCase):
    """ADR 0003 decision 4, which is the whole of why this is not a `note`.

    *"Two copies of a number are two authorities over one declaration, and the
    second one to be corrected is the one that ships."* That is not a style
    preference -- it is the mechanism of the original failure.
    """

    def test_two_scopes_agreeing_on_a_reference_name_one_identity(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            scopes = tuple(
                P.EditScope(artifact_id=artifact, region="magnet pocket",
                            datum_ids=("magnet-pocket-face",))
                for artifact in ("src", "drawer"))
            project = dataclasses.replace(
                _placed(), datums=(_datum(valid_for=("src", "drawer")),),
                edit_scopes=scopes)
            reported = project.validate(directory, require_buildable=False)
            self.assertEqual(
                set(), _at(reported, "edit_scopes[0].datum_ids")
                | _at(reported, "edit_scopes[1].datum_ids")
                | _at(reported, "datums["),
                "both scopes name one declared identity, so nothing is "
                "reported against the datum or either reference")
            # And the number lives in exactly one place.
            self.assertEqual(
                1, sum(1 for row in project.datums
                       if row.datum_id == "magnet-pocket-face"))

    def test_a_datum_used_outside_its_scope_is_reported(self) -> None:
        """The scope is enforced where it is referenced, or it is decoration."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            scope = P.EditScope(artifact_id="drawer", region="pocket",
                                datum_ids=("magnet-pocket-face",))
            project = dataclasses.replace(
                _placed(), datums=(_datum(valid_for=("src",)),),
                edit_scopes=(scope,))
            self.assertIn(
                F.INTENT_CONTRADICTION,
                _at(project.validate(directory, require_buildable=False),
                    "edit_scopes[0].datum_ids"),
                "the datum says it is valid for src and the drawer's "
                "scope used it anyway -- which is the stale-reference failure "
                "one artifact over")


class TheContractBindsWhichDatumTheEditWasPlacedAgainstTest(unittest.TestCase):
    """A promise about the edit belongs in the thing a review answer is bound to.

    `cli._preservation_feature` already carries seven fields of declared edit
    intent into the acceptance contract, and says why in a comment beside them:
    *"a job that changes what it claims to be doing can no longer keep the review
    answer somebody wrote against the previous claim."* `datum_ids` is that kind
    of field and was not among them, so an edit could be re-placed against a
    different reference and `contract_sha256` would not move.

    Which is this ADR's own failure with the blast radius moved: there, the
    number changed under a declaration nobody re-checked; here, the *declaration*
    changes under an answer nobody re-checks.
    """

    def _pair(self, **over) -> P.Project:
        from .test_execution_plan import (EDIT_SCOPE, POCKETS, SECOND_ARTIFACT,
                                          SECOND_SCOPE, SOURCE_ARTIFACT)
        base = dict(
            source_mode="MODIFY", model="model.py",
            envelope_mm={"x": 40.0, "y": 30.0, "z": 10.0},
            interfaces=(POCKETS,),
            source_artifacts=(SOURCE_ARTIFACT, SECOND_ARTIFACT),
            edit_scopes=(dataclasses.replace(EDIT_SCOPE,
                                             interface_ids=("magnet-pockets",)),
                         SECOND_SCOPE))
        base.update(over)
        return _project(**base)

    def _rows(self, project: P.Project) -> list[dict]:
        return cli._preservation_feature(project)

    def test_the_datum_an_edit_is_placed_against_reaches_the_contract(self) -> None:
        plain = self._pair()
        placed = dataclasses.replace(
            plain,
            datums=(_datum(valid_for=("src", "drawer")),),
            edit_scopes=(dataclasses.replace(plain.edit_scopes[0],
                                             datum_ids=("magnet-pocket-face",)),
                         plain.edit_scopes[1]))
        self.assertEqual(["magnet-pocket-face"],
                         self._rows(placed)[0]["datum_ids"])
        self.assertNotEqual(self._rows(plain)[0], self._rows(placed)[0],
                            "re-placing the edit against a datum has to move the "
                            "row, or the frozen answer survives the change")

    def test_the_datums_own_value_is_not_bound_and_the_cap_is_why_that_is_safe(
            self) -> None:
        """The honest limit of this slice, asserted rather than admitted in prose.

        The row binds *which* datum the edit was placed against. It does not
        bind the datum's value, so correcting 12.4 to 12.9 leaves
        `contract_sha256` where it was and a review answer written against the
        old number stays current. That is ADR 0003 decision 5 -- datums join the
        13.4 binding list -- and the ADR assigns it to Release 6: *"Release 6
        carries the invalidation obligation, because that is where a `MODIFY`
        job may claim success."*

        What makes the gap safe today is not that it is small. It is that a job
        with an edit scope is capped at `EXPERIMENTAL_UNAVAILABLE` and cannot
        claim success at all -- the ADR's own reason nothing has to stop. A
        datum is only ever referenced from an edit scope, so every job that can
        rest on one is capped. If that ever stops being true this test goes red,
        which is the point of asserting it here rather than writing it down.
        """
        plain = self._pair()
        placed = dataclasses.replace(
            plain,
            datums=(_datum(valid_for=("src", "drawer")),),
            edit_scopes=(dataclasses.replace(plain.edit_scopes[0],
                                             datum_ids=("magnet-pocket-face",)),
                         plain.edit_scopes[1]))
        corrected = dataclasses.replace(
            placed, datums=(_datum(value=12.9, valid_for=("src", "drawer")),))
        self.assertEqual(self._rows(placed), self._rows(corrected),
                         "if this ever differs, decision 5 landed and this "
                         "test is the one that should have been deleted")
        self.assertEqual("EXPERIMENTAL_UNAVAILABLE",
                         EX.compile_plan(placed).lane_status,
                         "and this is the only reason the line above is not a "
                         "defect: nothing resting on that datum may claim "
                         "success while the cap holds")

    def test_a_job_placing_no_edit_against_a_datum_gains_no_key(self) -> None:
        """The five pinned certified contracts declare no datum, and a key that
        is always present -- even as an empty list -- would move all five for a
        field they do not use. Same rule `minimum_detectable_defect_mm` follows,
        stated in the same block."""
        for row in self._rows(self._pair()):
            self.assertNotIn("datum_ids", row)


class ADatumSurvivesTheRoundTripTest(unittest.TestCase):
    """A declaration that does not serialize is a declaration for one process."""

    def test_a_project_with_no_datums_gains_no_key(self) -> None:
        """`ROADMAP.md` 3.4: a job declaring none costs what it cost before."""
        self.assertNotIn("datums", _placed().as_payload())

    def test_the_scope_list_serializes_as_a_list(self) -> None:
        """Every sibling `as_dict` normalizes its tuples and this one's line was
        unobservable through JSON, where a tuple and a list are one thing. It is
        observable here, which is cheaper than diverging from the siblings."""
        self.assertIsInstance(_datum().as_dict()["valid_for"], list)

    def test_datums_round_trip_through_project_json(self) -> None:
        """Both rows, because they exercise different fields.

        The derived one is the revision. The assumption is `owner` and
        `settled_by` -- and a fixture carrying only the derived row passed while
        the loader silently dropped both of those, because a datum nobody
        assumed leaves them empty on either side of the trip.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            _author(directory, "ancestor", **SCREW)
            rows = (
                _datum(provenance="INHERITED",
                       derived_from={"artifact_id": "src", "revision": 2},
                       valid_for=("src", "drawer"),
                       note="the pocket face"),
                _assumed(datum_id="guessed-clearance", owner="print engineer",
                         settled_by="calipers on the printed pocket"),
            )
            dataclasses.replace(_placed(), datums=rows).save(directory)

            payload = json.loads((directory / P.PROJECT_FILE)
                                 .read_text(encoding="utf-8"))
            self.assertEqual(2, payload["datums"][0]["derived_from"]["revision"])
            self.assertEqual("print engineer", payload["datums"][1]["owner"])
            self.assertEqual(rows, P.load(directory).datums)


if __name__ == "__main__":
    unittest.main()
