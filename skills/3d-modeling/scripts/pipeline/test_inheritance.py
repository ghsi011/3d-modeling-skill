#!/usr/bin/env python3
"""What an output body inherited, and what the job may not quietly drop.

`ROADMAP.md`'s Release 5 asks for "output-component inheritance" and for
imported intent to survive the edit, in unusually blunt terms:

> A job that prints in one material does not thereby erase the two materials its
> donor declared. Discarding imported multi-material intent is a defect, not a
> simplification -- the intent is recorded even when this release cannot act on
> it.

`ARCHITECTURE.md` **6.8 Edit intent** says the same thing: *"Imported intent that
the current job does not use is preserved rather than discarded. A donor assembly
that names two materials still names them after the edit, even when the target
job prints in one."* -- and 6.8's own bullet list is where this slice comes from:
*"material, process, and component roles inherited from the source"* and *"output
components that inherit from the source"*. (An earlier version of this file cited
6.11 four times over. 6.11 is "Manufacturing, assembly, and service operations"
and does not contain the word "inherit".)

**The gap, measured before this was written.** `Component` is "one printed body
the job expects to produce" and carries `component_id`, `role`, `count`,
`material`. Nothing else. So a two-source combination produces output bodies
with no record of which donor each came from, and a donor that declared two
materials is indistinguishable, after the edit, from one that declared none.
The discard is not a decision anybody takes -- there is nowhere to write it
down, so it happens by omission, which is exactly the failure mode the ROADMAP
calls a defect.

**What this slice does and does not claim.** It records. Nothing here *acts* on
an inherited material: a job that prints in one material still prints in one.
The obligation is that what the donor said is still readable afterwards, and
that an inheritance naming a source nothing declares is refused rather than
silently kept -- because an inheritance nobody can resolve is the same as none,
with the appearance of provenance.
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
from .test_alternatives import _laid_out, _project
from .test_execution_plan import SECOND_ARTIFACT, SOURCE_ARTIFACT


def _component(**over) -> P.Component:
    base = dict(component_id="the-combined-mount", role="printed part")
    base.update(over)
    return P.Component(**base)


def _codes(problems) -> set[str]:
    return {row.code for row in problems}


def _at(problems, prefix: str) -> set[str]:
    return {row.code for row in problems if row.where.startswith(prefix)}


def _sourced(**over) -> P.Project:
    base = dict(source_mode="MODIFY", model="model.py",
                source_artifacts=(SOURCE_ARTIFACT, SECOND_ARTIFACT))
    base.update(over)
    return _project(**base)


class AnOutputBodyRecordsWhatItCameFromTest(unittest.TestCase):
    """The declaration itself."""

    def test_a_component_may_name_the_source_it_was_inherited_from(self) -> None:
        self.assertEqual([], _component(inherited_from="src").problems())

    def test_a_component_declaring_no_inheritance_is_unchanged(self) -> None:
        """`ROADMAP.md` 4.4: a job that declares nothing new gains no key in
        `project.json`. A part designed from scratch inherits from nothing, and
        that is the ordinary case rather than an omission."""
        self.assertEqual([], _component().problems())
        self.assertNotIn("inherited_from", _component().as_dict())
        self.assertNotIn("inherited_materials", _component().as_dict())

    def test_the_requirement_hash_does_not_move_for_a_job_inheriting_nothing(
            self) -> None:
        """Here the frozen-hash argument is real, and this computes it.

        `cli._requirement_hash` feeds `Component.as_dict()` straight into
        `S.payload_hash`, so an always-present key -- even empty -- changes the
        requirement hash of **every** job that declares a component, and
        `requirement_sha256` reaches the contract body and therefore
        `contract_sha256`. That is not the situation `SourceArtifact.role` was
        in: an independent review proved that field reaches only `project.json`,
        which is deliberately unhashed, and the comment claiming otherwise was
        wrong. One serializer feeds a hash and the other does not, so the claim
        has to be checked per field.

        The first version of this test asserted
        `sorted(plain.as_dict()) == sorted(P.Component(...).as_dict())` -- the
        same expression twice, which cannot fail -- and two key-presence checks
        already made above. A review severed the link entirely, deleting
        `"components"` from `_requirement_hash`, and the whole gate stayed
        green. So the sentence claiming this was measured was itself the
        unchecked claim it warned about.
        """
        plain = P.Component(component_id="body", role="printed part")
        gained = dataclasses.replace(plain, inherited_from="drawer",
                                     inherited_materials=("TPU95A", "PETG"))
        # The exact key set the pre-slice hash was computed over. Adding one is
        # what would move it, so the set is the thing to pin.
        self.assertEqual({"component_id", "role", "count", "material"},
                         set(plain.as_dict()))
        # And the link itself: severing `components` from the hash must be
        # visible, or the paragraph above is describing a wire that is not there.
        self.assertNotEqual(
            cli._requirement_hash(
                dataclasses.replace(_sourced(), components=(plain,)), "b"),
            cli._requirement_hash(
                dataclasses.replace(_sourced(), components=(gained,)), "b"),
            "a component that gained an inheritance must move the hash the "
            "acceptance contract binds, or nothing was recorded")

    def test_an_inheritance_naming_nothing_declared_is_refused(self) -> None:
        """An inheritance nobody can resolve is no inheritance with the
        appearance of provenance, which is worse than none."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            project = dataclasses.replace(
                _sourced(), components=(_component(inherited_from="no-such"),))
            self.assertIn(
                F.REF_UNDECLARED,
                _at(project.validate(directory, require_buildable=False),
                    "components[0].inherited_from"))

    def test_declaring_no_inheritance_is_not_an_accusation(self) -> None:
        """Silence has to stay silence *through `validate`*, not only through
        `problems()`.

        Drop the `.strip()` guard and `artifact("")` returns None, so every
        component in every project ever recorded -- all of which inherit from
        nothing -- reports `REF_UNDECLARED`. A mutation doing exactly that
        survived, because the fixtures that exercise `validate` all declared an
        inheritance and the one that declared none never reached it.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            project = dataclasses.replace(_sourced(),
                                          components=(_component(),))
            self.assertEqual(
                set(), _at(project.validate(directory,
                                            require_buildable=False),
                           "components[0].inherited_from"),
                "a part designed from scratch inherits from nothing, and that "
                "is the ordinary case rather than an unresolved reference")

    def test_a_whitespace_inheritance_is_not_a_declaration(self) -> None:
        """`as_dict` tested truthiness while `problems` and `validate` tested
        `.strip()`, so `"   "` was emitted into `project.json` **and into the
        requirement hash** while both checks skipped it -- a fail-open in the
        one protection this slice adds, in the gap between two guards that
        disagreed about what empty means."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            dataclasses.replace(_sourced(),
                                components=(_component(),)).save(directory)
            payload = json.loads((directory / P.PROJECT_FILE)
                                 .read_text(encoding="utf-8"))
            payload["components"][0]["inherited_from"] = "   "
            (directory / P.PROJECT_FILE).write_text(json.dumps(payload),
                                                    encoding="utf-8")
            loaded = P.load(directory).components[0]
            self.assertEqual("", loaded.inherited_from)
            self.assertNotIn("inherited_from", loaded.as_dict())
        # And in process, where the loader's strip cannot help: a row built by
        # code rather than read from disk must not hash whitespace either.
        self.assertNotIn("inherited_from",
                         _component(inherited_from="   ").as_dict())

    def test_an_inheritance_naming_a_declared_source_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            project = dataclasses.replace(
                _sourced(), components=(_component(inherited_from="drawer"),))
            self.assertEqual(
                set(), _at(project.validate(directory,
                                            require_buildable=False),
                           "components[0].inherited_from"))


class ImportedIntentSurvivesTheEditTest(unittest.TestCase):
    """The obligation the ROADMAP calls a defect to break.

    Recording only. This release does not *act* on an inherited material -- a
    job printing in one material still prints in one -- and a test that implied
    otherwise would be claiming a capability the build does not have.
    """

    def test_a_donor_material_the_job_does_not_use_is_still_readable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            component = _component(inherited_from="drawer", material="PETG",
                                   inherited_materials=("TPU95A", "PETG"))
            dataclasses.replace(_sourced(),
                                components=(component,)).save(directory)
            payload = json.loads((directory / P.PROJECT_FILE)
                                 .read_text(encoding="utf-8"))
            self.assertEqual(["TPU95A", "PETG"],
                             payload["components"][0]["inherited_materials"],
                             "the donor named two materials and the job prints "
                             "one; the two are still named afterwards")
            self.assertEqual("PETG", payload["components"][0]["material"],
                             "and what this job actually prints is unchanged")
            self.assertEqual((component,), P.load(directory).components)

    def test_recording_two_materials_is_not_a_claim_to_print_two(self) -> None:
        """A weaker method may not issue a stronger claim. The inherited list is
        evidence about the donor, and the job's own `material` is what it will
        build -- so a component may honestly carry both without the receipt
        reading as a multi-material capability."""
        component = _component(inherited_from="drawer", material="PETG",
                               inherited_materials=("TPU95A", "PETG"))
        self.assertEqual([], component.problems())
        self.assertEqual("PETG", component.material)

    def test_inherited_materials_without_a_source_is_refused(self) -> None:
        """Inherited *from what*? A material list with no donor is a claim about
        an import that the row does not say happened."""
        self.assertIn(
            F.INTENT_CONTRADICTION,
            _codes(_component(inherited_materials=("TPU95A",)).problems()))

    def test_a_bare_string_of_materials_names_the_field(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            dataclasses.replace(
                _sourced(),
                components=(_component(inherited_from="drawer"),)).save(directory)
            payload = json.loads((directory / P.PROJECT_FILE)
                                 .read_text(encoding="utf-8"))
            payload["components"][0]["inherited_materials"] = "TPU95A"
            (directory / P.PROJECT_FILE).write_text(json.dumps(payload),
                                                    encoding="utf-8")
            with self.assertRaises(P.S.SchemaError) as caught:
                P.load(directory)
            self.assertIn("components[0].inherited_materials",
                          str(caught.exception))


if __name__ == "__main__":
    unittest.main()
