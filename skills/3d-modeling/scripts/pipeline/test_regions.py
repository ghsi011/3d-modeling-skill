#!/usr/bin/env python3
"""A named region carries exactly one disposition.

`ROADMAP.md`'s Release 5 names two declaration obligations. The datum one is
[ADR 0003](../../../docs/adr/0003-datum-provenance-and-authority.md) and landed
in `test_datums.py`; this is the other, in the ROADMAP's own words: *"named
regions, each carrying exactly one declared disposition — must-preserve,
permitted-change, or consumed-by-intent"*, because *"a region with no
disposition and a datum with no provenance are the two ways a job can arrive at
Release 6 with nothing to judge it by."*

**The defect this closes, measured before it was written.** An `EditScope`
carried three lists of region names and nothing compared them, so:

    EditScope(preserve=("the mounting boss",), may_remove=("the mounting boss",),
              add=("the mounting boss",)).problems() == []

One name, three contradictory promises, no finding. That is not a tidiness
complaint. All four lists reach the frozen acceptance contract, so the review
envelope carried a declaration saying the boss must survive *and* that it may go,
and the preservation audit reads `preserve` while a person reads the note. Two
authorities over one region, which is the same shape as ADR 0003's two copies of
one number -- and the second one to be corrected is the one that ships.

**Why `may_change` is new.** The vocabulary is three-way and the fields were
two-way: `preserve` is must-preserve and `may_remove` is consumed-by-intent,
and permitted-change -- the ROADMAP's *"source-specific editable regions"* --
had nowhere to go. A job meaning "this region may be reshaped but must not
disappear" had to say either nothing or something false. `add` is not the third:
it is geometry that does not exist yet, not a disposition on a region that does.
"""
from __future__ import annotations

import dataclasses
import json
import tempfile
import unittest
from pathlib import Path

from . import cli
from . import findings as F
from . import project as P
from .test_datums import _placed
from .test_execution_plan import SECOND_ARTIFACT, SOURCE_ARTIFACT

BOX = {"min": [5.0, 5.0, 0.0], "max": [15.0, 15.0, 10.0]}


def _scope(**over) -> P.EditScope:
    base = dict(artifact_id="src", region="the mounting boss", region_box=BOX)
    base.update(over)
    return P.EditScope(**base)


def _codes(problems) -> set[str]:
    return {row.code for row in problems}


def _at(problems, prefix: str) -> set[str]:
    return {row.code for row in problems if row.where.startswith(prefix)}


class ARegionCarriesOneDispositionTest(unittest.TestCase):
    """The obligation itself, one pair at a time."""

    def test_a_region_that_must_survive_may_not_also_be_removable(self) -> None:
        self.assertEqual(
            {F.INTENT_CONTRADICTION},
            _codes(_scope(preserve=("the boss",),
                          may_remove=("the boss",)).problems()),
            "must-preserve and consumed-by-intent are the two ends of the "
            "vocabulary; a region declaring both has declared nothing")

    def test_a_region_that_must_survive_may_not_also_be_editable(self) -> None:
        self.assertEqual(
            {F.INTENT_CONTRADICTION},
            _codes(_scope(preserve=("the boss",),
                          may_change=("the boss",)).problems()))

    def test_a_region_may_not_be_both_editable_and_consumed(self) -> None:
        self.assertEqual(
            {F.INTENT_CONTRADICTION},
            _codes(_scope(may_change=("the boss",),
                          may_remove=("the boss",)).problems()),
            "reshaping a region and consuming it are different promises about "
            "whether it is there afterwards")

    def test_the_finding_names_the_region_and_both_dispositions(self) -> None:
        """A finding a reader cannot act on is a finding they have to
        investigate. `CODE@where` keys on the field, and the sentence has to
        carry which name collided and which two lists hold it."""
        (row,) = _scope(preserve=("the boss",), may_remove=("the boss",)).problems()
        self.assertIn("the boss", row.message)
        self.assertIn("preserve", row.message)
        self.assertIn("may_remove", row.message)

    def test_three_dispositions_on_one_region_report_every_pair(self) -> None:
        """Not one finding and a `break`. Fixing the pair a run happened to
        report first would leave the job still contradicting itself, and the
        next run would report the next pair -- which reads as a new defect."""
        problems = _scope(preserve=("the boss",), may_change=("the boss",),
                          may_remove=("the boss",)).problems()
        self.assertEqual(3, len(problems), [row.message for row in problems])

    def test_distinct_regions_in_distinct_dispositions_are_fine(self) -> None:
        self.assertEqual([], _scope(preserve=("the flange",),
                                    may_change=("the fillet",),
                                    may_remove=("the boss",)).problems())

    def test_a_scope_declaring_no_disposition_at_all_is_unchanged(self) -> None:
        """`ROADMAP.md` 4.4: a job that declares nothing new gains no key in
        `project.json`. Every scope written before this obligation existed
        declared no `may_change`, and none of them may start failing. (3.4, cited
        here first, is "Preserve the common case" -- AI round trips, not
        serialization.)"""
        self.assertEqual([], _scope().problems())


class AddedGeometryIsNotADispositionTest(unittest.TestCase):
    """`add` is the fourth list and the third disposition is not in it."""

    def test_a_region_being_added_may_not_also_be_preserved(self) -> None:
        self.assertEqual(
            {F.INTENT_CONTRADICTION},
            _codes(_scope(preserve=("the boss",), add=("the boss",)).problems()),
            "a region that must survive the edit already exists, and one being "
            "added does not; the job cannot mean both")

    def test_a_region_being_added_may_not_also_be_consumed(self) -> None:
        self.assertEqual(
            {F.INTENT_CONTRADICTION},
            _codes(_scope(add=("the boss",), may_remove=("the boss",)).problems()))


class TheDispositionSurvivesTheRoundTripTest(unittest.TestCase):
    """A declaration that does not serialize is a declaration for one process."""

    def test_may_change_round_trips_through_project_json(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            directory.mkdir(exist_ok=True)
            scope = _scope(may_change=("the fillet", "the draft face"))
            dataclasses.replace(_placed(), edit_scopes=(scope,)).save(directory)
            payload = json.loads((directory / P.PROJECT_FILE)
                                 .read_text(encoding="utf-8"))
            self.assertEqual(["the fillet", "the draft face"],
                             payload["edit_scopes"][0]["may_change"])
            self.assertEqual((scope,), P.load(directory).edit_scopes)

    def test_the_disposition_serializes_as_a_list(self) -> None:
        """Every sibling on this row is normalized in `as_dict` and the line is
        invisible through JSON, where a tuple and a list are one thing. It is
        visible here, which is cheaper than diverging from the siblings."""
        self.assertIsInstance(
            _scope(may_change=("the fillet",)).as_dict()["may_change"], list)

    def test_a_bare_string_names_the_field_not_its_letters(self) -> None:
        """`tuple("the fillet")` is ten regions. Every other id list on this row
        goes through `_ids` for that reason."""
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            dataclasses.replace(_placed(),
                                edit_scopes=(_scope(),)).save(directory)
            payload = json.loads((directory / P.PROJECT_FILE)
                                 .read_text(encoding="utf-8"))
            payload["edit_scopes"][0]["may_change"] = "the fillet"
            (directory / P.PROJECT_FILE).write_text(json.dumps(payload),
                                                    encoding="utf-8")
            with self.assertRaises(P.S.SchemaError) as caught:
                P.load(directory)
            self.assertIn("edit_scopes[0].may_change", str(caught.exception))


class TheContractBindsTheDispositionTest(unittest.TestCase):
    """A promise about the edit belongs in what a review answer is bound to.

    `cli._preservation_feature` carries the declared edit intent into the
    acceptance contract so that *"a job that changes what it claims to be doing
    can no longer keep the review answer somebody wrote against the previous
    claim."* A region moving from permitted-change to must-preserve is exactly
    such a change.
    """

    def _project(self, **over) -> P.Project:
        base = dict(source_mode="MODIFY", model="model.py",
                    envelope_mm={"x": 40.0, "y": 30.0, "z": 10.0},
                    source_artifacts=(SOURCE_ARTIFACT, SECOND_ARTIFACT))
        base.update(over)
        return _placed(**base)

    def test_a_permitted_change_reaches_the_contract(self) -> None:
        scope = _scope(may_change=("the fillet",))
        (row,) = cli._preservation_feature(self._project(edit_scopes=(scope,)))
        self.assertEqual(["the fillet"], row["may_change"])

    def test_a_scope_declaring_none_gains_no_key(self) -> None:
        """The five pinned certified contracts declare no `may_change`, and an
        always-present key would move all five for a field they do not use."""
        (row,) = cli._preservation_feature(
            self._project(edit_scopes=(_scope(),)))
        self.assertNotIn("may_change", row)


class TheProjectReportsIt(unittest.TestCase):
    """The rows have to reach `Project.validate`, or none of the above runs."""

    def test_a_contradicting_scope_is_reported_by_the_project(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            project = dataclasses.replace(
                _placed(), edit_scopes=(_scope(preserve=("the boss",),
                                               may_remove=("the boss",)),))
            self.assertIn(F.INTENT_CONTRADICTION,
                          _at(project.validate(directory,
                                               require_buildable=False),
                              "edit_scopes[0]"))


if __name__ == "__main__":
    unittest.main()
