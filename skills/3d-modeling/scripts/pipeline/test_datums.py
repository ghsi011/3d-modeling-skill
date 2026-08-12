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

**Decision 5 has landed; decision 6 has not, and that is not an omission this
file gets to be quiet about.** Decision 5 -- datums join §13.4's
dependency-binding list, so changing one invalidates the results that rested on
it -- is `docs/defects.md` D31 and is covered by
`TheContractBindsTheReferencedDatumsContentsTest` below: the acceptance contract
binds *which* datum an edit was placed against **and** the canonical contents of
exactly the datums referenced, so correcting a value with the id kept moves the
requirement hash. The end-to-end half -- the stored review answer actually
refused and the dependent receipts actually removed -- is
`benchmarks/heavy/test_datums_heavy.py`, because it costs a build. Decision 6 --
that precedence between a datum and other evidence is a property of the
authoritative model and not of the file -- is satisfied by construction today, in
that nothing grants a datum authority over measured evidence, and enforced by
nothing. `ROADMAP.md`'s Release 5 section records that remaining gap and why the
`EXPERIMENTAL_UNAVAILABLE` cap makes it safe; the cap is asserted here rather
than trusted, and D31 lifted none of it.

Decision 7 decides nothing to build. What is deliberately *not* here: measuring
anything against a datum. These are declaration obligations, and a declaration
that cannot be checked is the thing this file exists to stop.
"""
from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import os
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
        """ADR 0003 decision 1 and 6.4, in the ADR's words: *"A datum with no
        recorded provenance is an assumption. It may still be used -- the
        alternative is a job that cannot start -- but it is named as an
        assumption, it carries an owner, and it carries the check that would
        settle it."*

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
        """*"It may still be used ... but it is named as an assumption"* -- and
        a name nothing surfaces is not one.

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
                _assumed(datum_id="never-recorded", provenance="",
                         owner="designer", settled_by="ask who chose it"),
                _datum(datum_id="magnet-pocket-face", provenance="MEASURED"),
            )).save(directory)
            self.assertEqual(
                [{"datum_id": "guessed-clearance", "provenance": "CHOSEN",
                  "owner": "print engineer",
                  "settled_by": "calipers on the printed magnet pocket"},
                 {"datum_id": "never-recorded", "provenance": "",
                  "owner": "designer", "settled_by": "ask who chose it"}],
                _status(directory)["assumptions"],
                "both assumptions are named and the measured one is not; and "
                "each carries its provenance, because a number somebody chose "
                "and a number nobody recorded are the two cases decision 1 "
                "exists to keep apart -- a report calling both 'a chosen "
                "number' asserts the labelled one for the unlabelled case")

    def test_a_job_with_no_assumptions_says_so_by_saying_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            _placed().save(directory)
            self.assertEqual([], _status(directory)["assumptions"])

    def test_an_assumption_is_permitted_and_is_labelled(self) -> None:
        """ADR 0003: *"A datum with no recorded provenance is an assumption. It
        may still be used -- the alternative is a job that cannot start -- but
        it is named as an assumption, it carries an owner, and it carries the
        check that would settle it."*

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

    def test_the_generated_geometry_half_of_MEASURED_still_cannot_say_so(self) -> None:
        """The limit of the fix above, asserted so it is not read as closed.

        6.5's second measuring class is *"measured from generated geometry"*,
        and `Project.validate` requires a named artifact to be a declared
        *source* artifact -- geometry this job produced is not one. So a datum
        measured off the job's own output still cannot record the revision it
        was measured on, which is the same incentive inversion one class over.
        It fails closed rather than quietly, and closing it needs a build result
        to be an addressable artifact with a revision, which is Release 6.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            project = dataclasses.replace(_placed(), datums=(_datum(
                provenance="MEASURED",
                derived_from={"artifact_id": "the candidate", "revision": 2}),))
            self.assertIn(
                F.REF_UNDECLARED,
                _at(project.validate(directory, require_buildable=False),
                    "datums[0].derived_from.artifact_id"),
                "refused, and refused is the honest answer today -- but it is "
                "the honest row being refused, so this is a stated gap")

    def test_a_derived_from_that_is_not_an_object_names_the_field(self) -> None:
        """The same failure `valid_for` had, on the field the ADR calls *"the
        field that failed"*.

        The loader coerced anything that was not a dict to `None`, and
        `problems` inspects it only when it is one. So on a `MEASURED` row --
        where the revision is optional -- `"derived_from": "drawer, revision 1"`,
        a plausible hand-authored spelling, loaded as *no revision at all* and
        validated completely clean. `INHERITED` was safe by accident: the
        coercion trips its `SCHEMA_REQUIRED`.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            dataclasses.replace(_placed(), datums=(_datum(),)).save(directory)
            payload = json.loads((directory / P.PROJECT_FILE)
                                 .read_text(encoding="utf-8"))
            payload["datums"][0]["derived_from"] = "drawer, revision 1"
            (directory / P.PROJECT_FILE).write_text(json.dumps(payload),
                                                    encoding="utf-8")
            with self.assertRaises(S.SchemaError) as caught:
                P.load(directory)
            self.assertIn("datums[0].derived_from", str(caught.exception))

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
        """`tuple("src")` is three scopes. `_ids` exists in this file for
        exactly that and `datum_ids` uses it; `valid_for` bypassed it, so a
        malformed declaration recorded nine bogus scopes as clean -- and a
        non-list crashed `design-tool status` with an unhandled TypeError
        instead of naming the field."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            dataclasses.replace(_placed(), datums=(_datum(),)).save(directory)
            payload = json.loads((directory / P.PROJECT_FILE)
                                 .read_text(encoding="utf-8"))
            # The third case is not the container but an *element*. `_ids`
            # validated the list and never what was in it, so `[["src"]]` reached
            # a set membership test and came out as `TypeError: unhashable type:
            # 'list'` from `design-tool status` -- the same unhandled crash on
            # the command surface, one level in.
            for bad in ("src", 7, [["src"]]):
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

    def test_a_row_that_is_wrong_in_itself_reaches_the_project(self) -> None:
        """The one line that wires `Datum.problems` to a real `project.json`.

        Every rule in that method -- the provenance enum, the three-way revision
        rule, the value, the unit, a non-empty scope, an assumption's owner and
        settling check -- is otherwise only ever asserted by calling
        `_datum(...).problems()` directly. Delete `problems.extend(...)` from
        `Project.validate` and all of those tests stay green while
        `design-tool status` accepts a datum with no provenance, no value, no
        unit, no owner and no scope. A mutation proved exactly that: the whole
        gate stayed at its baseline.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            broken = P.Datum(datum_id="nothing-at-all", value=None, unit="",
                             provenance="", derived_from=None, valid_for=())
            project = self._project_with([broken])
            reported = _at(project.validate(directory, require_buildable=False),
                           "datums[0]")
            self.assertEqual({F.SCHEMA_TYPE, F.SCHEMA_REQUIRED}, reported,
                             "the row's own rules have to arrive here, or they "
                             "are rules about a dataclass and not about a job")

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
                | _at(reported, "edit_scopes[1].datum_ids")
                # And at the declaration too. Asserting only at the reference
                # sites let a refusal *relocate* to `datums[0].valid_for` and
                # stay invisible: a mutation dropping interfaces out of the
                # placeable set left this test green while the job it builds was
                # refused at the other end.
                | _at(reported, "datums["),
                "the datum is scoped to the interface these two scopes realize, "
                "which is the coordinated case the ADR exists for")

    def test_a_datum_may_be_scoped_to_a_declared_component(self) -> None:
        """Declarable, and — say it plainly — not yet referenceable.

        ADR decision 3 names artifacts, components and interfaces, so a
        component id is accepted here. No `EditScope` names a component, so the
        scope match (artifact plus interfaces) can never be inside one: a
        component-scoped datum is a declaration nothing can use yet. The axis
        stays because the ADR names it and because dropping it would make the
        declaration unrepresentable rather than merely unused; what does not
        stay is the impression that it works. Referencing it needs a component
        to be something an edit scope can be inside, which no release has built.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            project = dataclasses.replace(
                self._with([_datum(valid_for=("drawer-body",))], ()),
                components=(P.Component(component_id="drawer-body",
                                        role="printed part"),))
            self.assertEqual(
                set(), _at(project.validate(directory,
                                            require_buildable=False),
                           "datums[0].valid_for"),
                "a component the job declares is a scope the datum may name")

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

    def test_the_row_carries_the_reference_and_not_a_copy_of_the_contents(
            self) -> None:
        """Where the contents live, and where they deliberately do not.

        This assertion used to be named for the D31 gap -- the row does not bind
        the datum's value, so correcting 12.4 to 12.9 left `contract_sha256`
        alone -- and it instructed its own deletion once ADR 0003 decision 5
        landed. Decision 5 has now landed and the assertion survives, which is
        worth being exact about rather than letting a green test carry a claim
        that is no longer true.

        The row still carries no contents, and that is now a design property
        instead of a gap: the authoritative contents are bound once, in
        `_requirement_hash`'s canonical datum block, because decision 4 says
        coordinated scopes reference one object rather than each holding a copy.
        Two scopes naming one datum must not put two copies of its number in one
        contract. So the row keeps the reference, the block keeps the contents,
        and `TheContractBindsTheReferencedDatumsContentsTest` is where the
        binding itself is proved.

        The cap assertion stays, and not as a leftover. A datum is only ever
        reachable through an edit scope, so every job that can rest on one is
        held at `EXPERIMENTAL_UNAVAILABLE`; D31 makes the binding correct and
        does not lift that ceiling. If the cap ever goes away this goes red,
        which is the point of asserting it rather than writing it down.
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
                         "the row reports the reference; a second copy of the "
                         "number here would be the two-authorities failure ADR "
                         "0003 decision 4 exists to stop")
        self.assertEqual("EXPERIMENTAL_UNAVAILABLE",
                         EX.compile_plan(placed).lane_status,
                         "D31 binds the contents correctly and lifts nothing: "
                         "nothing resting on that datum may claim success while "
                         "the cap holds")

    def test_one_scopes_reference_list_is_sorted_but_never_deduplicated(self) -> None:
        """Two different questions about one list, and only one is this row's.

        Sorting is authorised because the field is a set of references to
        declared identities rather than a precedence or an operation order, so
        the order one scope lists two independent references in is not a fact
        about the job. Deduplicating is not: a repeated id is a declaration
        `Project.validate` owns, and collapsing it here would hide it behind a
        contract that looks well-formed.
        """
        plain = self._pair()

        def placed(ids: tuple[str, ...]) -> P.Project:
            return dataclasses.replace(
                plain,
                datums=(_datum(valid_for=("src", "drawer")),
                        _datum(datum_id="drawer-face",
                               valid_for=("src", "drawer"))),
                edit_scopes=(dataclasses.replace(plain.edit_scopes[0],
                                                 datum_ids=ids),
                             plain.edit_scopes[1]))

        forward = self._rows(placed(("drawer-face", "magnet-pocket-face")))
        reversed_ = self._rows(placed(("magnet-pocket-face", "drawer-face")))
        self.assertEqual(forward, reversed_,
                         "the same two references in the other order are the "
                         "same declaration and must not move the contract")
        self.assertEqual(["drawer-face", "magnet-pocket-face"],
                         forward[0]["datum_ids"])

        repeated = self._rows(placed(("magnet-pocket-face", "magnet-pocket-face")))
        self.assertEqual(["magnet-pocket-face", "magnet-pocket-face"],
                         repeated[0]["datum_ids"],
                         "a duplicate reference is reported as written; this "
                         "function does not get to silently repair it")

    def test_a_job_placing_no_edit_against_a_datum_gains_no_key(self) -> None:
        """The five pinned certified contracts declare no datum, and a key that
        is always present -- even as an empty list -- would move all five for a
        field they do not use. Same rule `minimum_detectable_defect_mm` follows,
        stated in the same block."""
        for row in self._rows(self._pair()):
            self.assertNotIn("datum_ids", row)


class TheContractBindsTheReferencedDatumsContentsTest(unittest.TestCase):
    """D31, and ADR 0003 decision 5: a datum is a dependency binding.

    The sibling class above binds *which* datum an edit was placed against. This
    one is about what the datum said. `_requirement_hash` pins "the values
    somebody stated or measured" and `project.datums` was not among its six keys,
    so correcting a referenced number while keeping its id left the frozen
    contract byte-identical and a review answer written against the old number
    still current.

    That is the ADR's own incident with the blast radius moved once more: there
    the file was rewritten mid-job and nothing was invalidated; here the
    authoritative model is corrected and nothing is invalidated.
    """

    # A stand-in for the brief's digest. The subject is the datum payload, and a
    # real brief hash would only add a constant to every value below.
    BRIEF = "0" * 64

    def _placed(self, **datum_over) -> P.Project:
        from .test_execution_plan import (EDIT_SCOPE, POCKETS, SECOND_ARTIFACT,
                                          SECOND_SCOPE, SOURCE_ARTIFACT)
        plain = _project(
            source_mode="MODIFY", model="model.py",
            envelope_mm={"x": 40.0, "y": 30.0, "z": 10.0},
            interfaces=(POCKETS,),
            source_artifacts=(SOURCE_ARTIFACT, SECOND_ARTIFACT),
            edit_scopes=(dataclasses.replace(EDIT_SCOPE,
                                             interface_ids=("magnet-pockets",)),
                         SECOND_SCOPE))
        # Overrides win, including over `valid_for` -- the validity-scope subtest
        # changes exactly that field.
        fields: dict = dict(valid_for=("src", "drawer"))
        fields.update(datum_over)
        return dataclasses.replace(
            plain,
            datums=(_datum(**fields),),
            edit_scopes=(dataclasses.replace(plain.edit_scopes[0],
                                             datum_ids=("magnet-pocket-face",)),
                         plain.edit_scopes[1]))

    def _hash(self, project: P.Project) -> str:
        return cli._requirement_hash(project, self.BRIEF)

    def test_a_referenced_datums_changed_value_moves_the_requirement_hash(self) -> None:
        """The smallest statement of the defect: same id, corrected number."""
        self.assertNotEqual(
            self._hash(self._placed()),
            self._hash(self._placed(value=12.9)),
            "the scope names this datum and the number it names changed, so a "
            "contract derived from it must not be byte-identical -- otherwise a "
            "review answer written against 12.4 stays current against 12.9")

    def test_an_unchanged_project_rederives_the_same_requirement_hash(self) -> None:
        """The other half, and the one that makes the first meaningful.

        A hash that moved on every call would satisfy the assertion above while
        ending byte-identical reruns, which `bindings.identity` is built on.
        """
        self.assertEqual(self._hash(self._placed()), self._hash(self._placed()))

    def test_every_authority_bearing_field_moves_the_hash(self) -> None:
        """One subtest per field, and each pair differs in *only* that field.

        Written as pairs rather than as variations on one baseline, because the
        first version was not isolating what it named. Two independent reviews
        found the same hole: the `source artifact` and `artifact revision` cases
        each flipped `provenance` *and* set `derived_from`, and the `owner` and
        `settled_by` cases each flipped `provenance` too -- so provenance alone
        moved the hash and all four subtests would have stayed green against an
        implementation that dropped `derived_from`, `owner` and `settled_by`
        entirely. Four assertions named four protections and tested one.

        So each row below is `(label, left, right)` and the two sides differ in
        exactly one key. The `derived_from` cases keep provenance fixed at
        `INHERITED` on *both* sides; the assumption cases keep it at `CHOSEN` on
        both. `test_the_bound_row_is_the_models_own_serialization` is the
        backstop for a field nobody thought to pair here.

        The unit case is `mm -> cm` deliberately: two unquestionably valid units,
        so this proves the D31 property without depending on D33's
        `null`-to-`"None"` coercion or implying that `"None"` is a unit.
        """
        derived = dict(provenance="INHERITED",
                       derived_from={"artifact_id": "src", "revision": 1})
        assumed = dict(provenance="CHOSEN", owner="metrologist",
                       settled_by="calipers")
        for label, left, right in (
                ("value", {}, dict(value=12.9)),
                ("unit", {}, dict(unit="cm")),
                # Provenance alone: `derived_from` stays None on both sides.
                ("provenance", {}, dict(provenance="CHOSEN")),
                ("source artifact", derived,
                 {**derived, "derived_from": {"artifact_id": "drawer",
                                              "revision": 1}}),
                ("artifact revision", derived,
                 {**derived, "derived_from": {"artifact_id": "src",
                                              "revision": 2}}),
                ("validity scope", {}, dict(valid_for=("src",))),
                ("assumption owner", assumed, {**assumed, "owner": "designer"}),
                ("settling check", assumed,
                 {**assumed, "settled_by": "a printed coupon"}),
                ("note", {}, dict(note="measured after the pocket was cut")),
        ):
            with self.subTest(field=label):
                self.assertNotEqual(
                    self._hash(self._placed(**left)),
                    self._hash(self._placed(**right)),
                    f"changing {label} changes what the reference means, so a "
                    "contract derived from it must move")

    def test_the_bound_row_is_the_models_own_serialization(self) -> None:
        """Equality against `as_dict()`, not a list of the fields I thought of.

        This is the assertion that catches the next implementation rather than
        this one: a payload rebuilt field by field would carry whatever its author
        remembered and quietly drop `owner`, `settled_by`, `note`, or whichever
        authority-bearing field is added after this test was written. Comparing
        against the model's own serialization cannot drift from the model.
        """
        project = self._placed()
        self.assertEqual([project.datums[0].as_dict()],
                         cli._referenced_datums(project))

    def test_a_datum_no_scope_references_does_not_participate(self) -> None:
        """ARCHITECTURE.md 13.4: a binding a job does not use is not in its identity.

        The other direction of the same rule as 13.5's "unrelated valid results
        remain reusable" -- correcting a datum nothing was placed against must not
        cut a revision on work that never read it.
        """
        project = self._placed()
        with_spare = dataclasses.replace(
            project,
            datums=project.datums + (_datum(datum_id="unused-face", value=99.0,
                                            valid_for=("src", "drawer")),))
        moved = dataclasses.replace(
            project,
            datums=project.datums + (_datum(datum_id="unused-face", value=1.0,
                                            valid_for=("src", "drawer")),))
        self.assertEqual(self._hash(with_spare), self._hash(moved),
                         "nothing is placed against unused-face, so its value "
                         "cannot be part of this job's identity")
        self.assertEqual([d["datum_id"] for d in cli._referenced_datums(moved)],
                         ["magnet-pocket-face"])

    def test_declaration_order_of_the_datums_list_is_not_a_fact_about_the_job(
            self) -> None:
        """Item 12: reordering unordered datum rows does not change bytes."""
        project = self._placed()
        rows = (project.datums[0],
                _datum(datum_id="drawer-face", valid_for=("src", "drawer")))
        forward = dataclasses.replace(
            project, datums=rows,
            edit_scopes=(dataclasses.replace(
                project.edit_scopes[0],
                datum_ids=("magnet-pocket-face", "drawer-face")),
                project.edit_scopes[1]))
        backward = dataclasses.replace(forward, datums=tuple(reversed(rows)))
        self.assertEqual(self._hash(forward), self._hash(backward))

    def test_reference_order_is_not_a_fact_either_but_which_ids_still_is(
            self) -> None:
        """Item 13 and its converse, together.

        Order-insensitivity is only safe if identity-sensitivity survives it. A
        hash that ignored reference order by ignoring the references would pass
        the first assertion and be useless, so the second one replaces an id and
        requires the hash to move.
        """
        project = self._placed()
        rows = (project.datums[0],
                _datum(datum_id="drawer-face", value=8.0,
                       valid_for=("src", "drawer")))

        def placed(ids: tuple[str, ...]) -> P.Project:
            return dataclasses.replace(
                project, datums=rows,
                edit_scopes=(dataclasses.replace(project.edit_scopes[0],
                                                 datum_ids=ids),
                             project.edit_scopes[1]))

        self.assertEqual(
            self._hash(placed(("magnet-pocket-face", "drawer-face"))),
            self._hash(placed(("drawer-face", "magnet-pocket-face"))),
            "the same two references in the other order are one declaration")
        self.assertNotEqual(
            self._hash(placed(("magnet-pocket-face",))),
            self._hash(placed(("drawer-face",))),
            "replacing the reference re-places the edit, which must move")

    def test_two_scopes_sharing_one_datum_bind_one_authoritative_copy(self) -> None:
        """ADR 0003 decision 4, in the serialization rather than in prose.

        The incident the ADR was written from was two copies of one number where
        the second to be corrected was the one that shipped. A contract that
        wrote the contents once per referencing scope would rebuild exactly that.
        """
        project = self._placed()
        shared = dataclasses.replace(
            project,
            edit_scopes=(dataclasses.replace(project.edit_scopes[0],
                                             datum_ids=("magnet-pocket-face",)),
                         dataclasses.replace(project.edit_scopes[1],
                                             datum_ids=("magnet-pocket-face",))))
        bound = cli._referenced_datums(shared)
        self.assertEqual(1, len(bound),
                         "one identity, one authoritative entry, however many "
                         "scopes name it")
        self.assertNotEqual(self._hash(shared),
                            self._hash(dataclasses.replace(
                                shared,
                                datums=(_datum(value=12.9,
                                               valid_for=("src", "drawer")),))),
                            "and correcting it moves the identity for both")

    def test_a_job_with_no_referenced_datum_gains_no_key(self) -> None:
        """Items 11 and 14, at the level the byte-identity actually depends on.

        Every recorded case -- the five pinned certified contracts and all four
        L1 replay goldens -- declares no datum. An always-present key, even an
        empty list, would move all nine. The two `modify-ball-*` replays are the
        sharp case and are represented here by `plain`: an edit scope, no datum.
        """
        from .test_execution_plan import (EDIT_SCOPE, POCKETS, SECOND_ARTIFACT,
                                          SECOND_SCOPE, SOURCE_ARTIFACT)
        plain = _project(
            source_mode="MODIFY", model="model.py",
            envelope_mm={"x": 40.0, "y": 30.0, "z": 10.0},
            interfaces=(POCKETS,),
            source_artifacts=(SOURCE_ARTIFACT, SECOND_ARTIFACT),
            edit_scopes=(dataclasses.replace(EDIT_SCOPE,
                                             interface_ids=("magnet-pockets",)),
                         SECOND_SCOPE))
        self.assertEqual([], cli._referenced_datums(plain))
        declared_but_unused = dataclasses.replace(
            plain, datums=(_datum(valid_for=("src", "drawer")),))
        self.assertEqual(
            self._hash(plain), self._hash(declared_but_unused),
            "a datum nothing is placed against leaves the contract exactly "
            "where it was, so no recorded golden can move because of it")

        # The key must be ABSENT, not present and empty, and the two hash
        # differently while comparing identical to each other. A digest cannot
        # see the difference -- both projects above would carry `"datums": []`
        # and still match -- so this reads the payload. Without it the only
        # thing standing between an always-present key and nine moved goldens is
        # the replay suite, which is not the commit gate.
        for label, project in (("no datum at all", plain),
                               ("declared but unreferenced", declared_but_unused)):
            with self.subTest(project=label):
                self.assertNotIn(
                    "datums", cli._requirement_payload(project, self.BRIEF),
                    "an unused key is still an added key")
        self.assertIn("datums", cli._requirement_payload(self._placed(), self.BRIEF),
                      "and it is present the moment an edit is placed against one")

    def test_reordering_one_datums_scope_list_changes_nothing(self) -> None:
        """The canonicalization ruling, and the converse that keeps it honest.

        `valid_for` is a membership set to the only code that reads it --
        `Project.validate` intersects `set(datum.valid_for)` against the scope --
        so two declarations differing only in the order of the same scopes are one
        declaration. Before `Datum.as_dict` sorted the field they were two
        contracts: `("src", "drawer")` hashed 50db5e539edbe65c and
        `("drawer", "src")` hashed 0a239014a926045c, which cut a spurious
        acceptance revision and refused a review answer over a difference the model
        does not distinguish. Found by an independent review, not by this suite.

        The converse matters as much: a hash that ignored scope *order* by ignoring
        the scope *set* would pass the first assertion and mean nothing, so the
        second one changes which scopes are named and requires the hash to move.
        """
        project = self._placed(valid_for=("src", "drawer"))
        reordered = self._placed(valid_for=("drawer", "src"))
        self.assertEqual(self._hash(project), self._hash(reordered),
                         "the same two scopes in the other order are the same "
                         "declaration, and must not move the contract")
        narrowed = self._placed(valid_for=("src",))
        self.assertNotEqual(self._hash(project), self._hash(narrowed),
                            "but withdrawing a scope changes where the datum may "
                            "be used, which must move it")

    def test_the_bound_order_is_sorted_and_not_whatever_a_set_yielded(self) -> None:
        """The assertion a surviving mutation asked for.

        Dropping `sorted()` from the content block passed every other test here,
        and the reason is worth stating because it is the trap: the referenced ids
        are collected into a *set*, so the set has already discarded declaration
        order and two projects differing only in that order iterate identically
        within one process. Reordering fixtures therefore cannot see the
        difference.

        What they cannot see is that a set's iteration order is a function of
        `PYTHONHASHSEED`. Unsorted, the same project would serialize differently
        in two interpreters -- ending byte-identical reruns and clean-clone
        reproduction, which are the two properties `bindings.identity` rests on --
        while every comparison inside one run agreed. So this asserts the order
        itself, over enough ids that a set coincidentally yielding sorted order is
        not a thing to rely on. `benchmarks/heavy/test_datums_heavy.py` proves the
        same property the expensive way, across two real interpreters with
        different seeds.
        """
        project = self._placed()
        ids = ("zeta-face", "alpha-face", "mid-face", "beta-face", "yankee-face",
               "delta-face", "kilo-face", "omega-face")
        many = dataclasses.replace(
            project,
            datums=tuple(_datum(datum_id=name, valid_for=("src", "drawer"))
                         for name in ids),
            edit_scopes=(dataclasses.replace(project.edit_scopes[0],
                                             datum_ids=ids),
                         project.edit_scopes[1]))
        self.assertEqual(
            sorted(ids), [row["datum_id"] for row in cli._referenced_datums(many)],
            "the block is ordered by datum_id, not by whatever the set yielded "
            "under this process's hash seed")

    def test_the_binding_does_not_read_the_directory_it_is_run_from(self) -> None:
        """Items 17-19, tested behaviourally after the first attempt was theatre.

        This asserted `list(inspect.signature(cli._referenced_datums).parameters)
        == ["project"]` and nothing else. Both independent reviews called it
        correctly: a one-parameter function can still read a module global, an
        environment variable, or a file in the working directory, so the
        assertion passed for an implementation that did exactly what it claimed
        to forbid -- and it *failed* for an added unused keyword argument, which
        is no regression at all. It tested a shape, not a property.

        What it does now: run the same project from two different working
        directories, one of which contains a plausibly-named override file that a
        careless implementation might read, and require the same answer. That
        catches the `Path.cwd() / "datum_overrides.json"` implementation the
        signature check waved through.

        It remains a floor rather than a proof. A candidate cannot reach this
        function at all -- `acceptance.generate` has no parameter a mesh, digest
        or build result can arrive through, and `_run_authored` freezes before
        `ISO.build` runs, which `test_frozen` asserts. This test covers the
        narrower question of ambient state, which is the half a unit test can
        actually measure.
        """
        project = self._placed()
        expected = cli._referenced_datums(project)
        with tempfile.TemporaryDirectory() as raw:
            here = Path(raw)
            # The bait: a file whose name an implementation reaching for ambient
            # state would plausibly reach for.
            (here / "datum_overrides.json").write_text(
                json.dumps({"magnet-pocket-face": {"value": 999.0}}),
                encoding="utf-8")
            was = Path.cwd()
            try:
                os.chdir(here)
                from_elsewhere = cli._referenced_datums(project)
            finally:
                os.chdir(was)
        self.assertEqual(expected, from_elsewhere,
                         "the bound contents are a function of the project and "
                         "of nothing in the directory the run happens to start in")
        self.assertEqual(12.4, from_elsewhere[0]["value"],
                         "and specifically not of a file sitting next to it")


class ADatumSurvivesTheRoundTripTest(unittest.TestCase):
    """A declaration that does not serialize is a declaration for one process."""

    def test_a_project_with_no_datums_gains_no_key(self) -> None:
        """`ROADMAP.md` 4.4: a job that declares no alternative "gains no key in
        `project.json`, the execution plan or the review envelope". 3.4, which an
        earlier version of this cited, is about AI round trips."""
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

            # Canonical rather than literal, and only in `valid_for`. `as_dict`
            # writes that field sorted, because `Project.validate` reads it as a
            # membership set and identity must not distinguish two spellings of one
            # set. So the trip returns the same *set* of scopes, not the same tuple
            # order -- asserted here as the set, because asserting the tuple would
            # be asserting an order the model does not have.
            loaded = P.load(directory).datums
            self.assertEqual(len(rows), len(loaded))
            for before, after in zip(rows, loaded):
                self.assertEqual(set(before.valid_for), set(after.valid_for))
                self.assertEqual(dataclasses.replace(before, valid_for=()),
                                 dataclasses.replace(after, valid_for=()),
                                 "every field except the scope order survives the "
                                 "trip unchanged")
            self.assertEqual([sorted(r.valid_for) for r in rows],
                             [list(d.valid_for) for d in loaded],
                             "and what comes back is the canonical order, so a "
                             "saved project reloads to one spelling rather than "
                             "whichever the author happened to type")


def _unit_payload(*, datum_unit="mm", requirement_unit="mm",
                  omit_datum_unit=False, omit_requirement_unit=False) -> dict:
    """The smallest `project.json` payload carrying one datum and one requirement.

    Built as a payload and loaded through `from_payload`, never by constructing the
    rows, because D33 lives in the loader: the coercion that defeats the unit check
    is `str(row.get("unit", ...))`, and a test that hands `Datum(...)` a string has
    already done by hand the one thing the loader gets wrong.
    """
    datum = {"datum_id": "pocket-face", "value": 12.5, "provenance": "MEASURED",
             "valid_for": ["src"]}
    if not omit_datum_unit:
        datum["unit"] = datum_unit
    requirement = {"name": "pocket-depth", "value": 11.4, "provenance": "STATED",
                   "source": "the brief"}
    if not omit_requirement_unit:
        requirement["unit"] = requirement_unit
    return {
        "schema_version": 1, "job_id": "d33", "updated_utc": UTC,
        "source_mode": "MODIFY", "consequence": "INCONSEQUENTIAL",
        "consequence_rationale": "a desk block; failure wastes material",
        "printer": "Test Printer",
        "material": {"process": "FDM", "material": "PLA"},
        "nozzle": {"diameter_mm": 0.4},
        "orientation": {"model_to_printer_matrix": "identity", "bed_z_mm": 0.0},
        "model": "model.py", "parameters": {},
        "envelope_mm": {"x": 60.0, "y": 50.0, "z": 20.0},
        "reviewer": {"model_snapshot": "test"},
        "requirements": [requirement],
        "source_artifacts": [{"artifact_id": "src", "path": "source.stl",
                              "format": "STL", "classification": "USABLE_MESH"}],
        "datums": [datum],
        "edit_scopes": [{"artifact_id": "src", "region": "the pocket face",
                         "region_box": {"min": [0.0, 0.0, 0.0],
                                        "max": [5.0, 5.0, 5.0]},
                         "datum_ids": ["pocket-face"],
                         "preserve": ["everything outside the pocket"]}],
    }


class AUnitThatIsPresentAndNotAStringIsRefusedTest(unittest.TestCase):
    """D33: `str(None)` is `"None"`, and `"None"` satisfies the check that exists to
    stop a unitless number.

    The rule requiring a unit tests `if not str(self.unit).strip()`. An explicit JSON
    `null` arrives through `str(row.get("unit", ...))` as the four-character string
    `None`, which is not empty -- so the check whose own message says *"a number with
    no unit is a number two readers can read differently"* passes it.

    The distinction the loader was missing is between two different rows: a key that
    is **absent**, meaning "use the default", and a key that is **present and not a
    string**, meaning somebody wrote a unit and it is not one. Only the second is
    refused. That is why the defaults are asserted in the same test -- a fix that
    refused the absent case too would satisfy the first subtests and break every
    project that never mentioned a unit.

    Deliberately not in scope, per the ruling: no unit vocabulary, no conversion, no
    normalisation, and the literal string `"None"` somebody could still type is left
    alone rather than made a second issue in this slice.
    """

    def test_only_a_present_non_string_unit_is_refused(self) -> None:
        for label, kwargs in (
                ("datum unit is JSON null", {"datum_unit": None}),
                ("requirement unit is JSON null", {"requirement_unit": None}),
                ("datum unit is a number", {"datum_unit": 4}),
                ("requirement unit is a number", {"requirement_unit": 4}),
                ("datum unit is a list", {"datum_unit": ["mm"]}),
        ):
            with self.subTest(case=label):
                with self.assertRaises(S.SchemaError) as caught:
                    P.from_payload(_unit_payload(**kwargs))
                self.assertIn("unit", str(caught.exception).lower(),
                              "the refusal has to name the field it is about")

        # The other half of the rule, without which the five above would be
        # satisfied by a loader that refused every unit it was not handed.
        with self.subTest(case="an omitted requirement unit still defaults to mm"):
            project = P.from_payload(_unit_payload(omit_requirement_unit=True))
            self.assertEqual("mm", project.requirements[0].unit)

        with self.subTest(case="an omitted datum unit keeps its existing behaviour"):
            # Empty, not defaulted, and then caught by `problems()` as before: this
            # slice does not redesign required-field handling.
            project = P.from_payload(_unit_payload(omit_datum_unit=True))
            self.assertEqual("", project.datums[0].unit)
            self.assertTrue(any("unit" in p.where
                                for p in project.datums[0].problems(0)),
                            "the missing-unit finding must still be raised")

        with self.subTest(case="a valid string unit survives verbatim"):
            project = P.from_payload(_unit_payload(datum_unit="cm",
                                                   requirement_unit="in"))
            self.assertEqual("cm", project.datums[0].unit)
            self.assertEqual("in", project.requirements[0].unit)


if __name__ == "__main__":
    unittest.main()
