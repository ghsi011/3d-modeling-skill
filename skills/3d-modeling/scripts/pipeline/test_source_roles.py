#!/usr/bin/env python3
"""What a supplied file is *for*, and what that forbids.

`ROADMAP.md`'s Release 5 asks for "source-specific roles" and names five;
`ARCHITECTURE.md` 6.2 names eight and calls them typical. Neither was
implemented, so every supplied artifact was the same kind of thing: geometry
this job may do as it likes with.

**The fail-open, measured before this was written.** Take a constructed case --
no fixture in this repository supplies a third-party mating object yet -- of a
vent mount that clips into a car's air vent. The vent is supplied as geometry so
the mount can be fitted to it, and it is emphatically not ours to change:

    project.validate(...)  # a MODIFY job, one artifact, one edit scope over it
    # -> nothing at edit_scopes[0].artifact_id

Nothing detected it, because nothing recorded what the vent was for. Note *where*
that is measured: `EditScope.problems()` never looks at artifacts and still
returns `[]` for this scope after the fix, because a scope alone cannot know what
it is editing. An earlier version of this paragraph quoted that call instead, and
would have been describing a surface the fix does not touch -- the same
wrong-surface error `ROADMAP.md` records against the datum slice's mutation
sweep, repeated in the next slice written.

None of this is a tidy-declaration complaint: an edit scope compiles a
preservation row,
so the pipeline would have gone on to measure *whether the car's vent survived
our edit* -- a real measurement, deterministic and reproducible, about an
object the job does not own and cannot change. A receipt like that is worse
than no receipt, because it reads as evidence.

**Why the role is optional.** Every project recorded before this field existed
declares none, and a required role would refuse all of them for a field they do
not use. Absent means undeclared and nothing fires. (It would *not* move a frozen
contract hash either way -- `SourceArtifact.as_dict` reaches only
`project.json`, which is deliberately unhashed. An earlier version of this
paragraph said otherwise, unchecked.) What the obligation buys is that a role *declared* is a role
*kept*: say a file is the thing you are fitting to, and you may not then edit
it.
"""
from __future__ import annotations

import dataclasses
import json
import tempfile
import unittest
from pathlib import Path

from . import findings as F
from . import project as P
from .test_alternatives import _laid_out, _project

BOX = {"min": [5.0, 5.0, 0.0], "max": [15.0, 15.0, 10.0]}

ARCHITECTURE = (Path(__file__).resolve().parents[4]
                / "ARCHITECTURE.md").read_text(encoding="utf-8")

# 6.2 writes the roles as English -- "authoritative base geometry", "prior
# revision". The code needs identifiers, so the mapping is stated once, here,
# where a reader comparing the two lists can see it.
_SLUGS = {"authoritative base geometry": "BASE", "donor geometry": "DONOR",
          "mating object": "MATING_OBJECT",
          "measurement reference": "MEASUREMENT_REFERENCE",
          "visual envelope": "VISUAL_ENVELOPE", "prior revision": "PRIOR_REVISION",
          "alternative candidate": "ALTERNATIVE_CANDIDATE",
          "production export": "PRODUCTION_EXPORT"}


def _slug(name: str) -> str:
    return _SLUGS.get(name, name.upper().replace(" ", "_"))


def _artifact(**over) -> P.SourceArtifact:
    base = dict(artifact_id="src", path="source.stl", format="STL",
                classification="USABLE_MESH")
    base.update(over)
    return P.SourceArtifact(**base)


def _scope(**over) -> P.EditScope:
    base = dict(artifact_id="src", region="the mounting boss", region_box=BOX)
    base.update(over)
    return P.EditScope(**base)


def _codes(problems) -> set[str]:
    return {row.code for row in problems}


def _at(problems, prefix: str) -> set[str]:
    return {row.code for row in problems if row.where.startswith(prefix)}


class ARoleIsOneOfAClosedSetTest(unittest.TestCase):
    """One vocabulary, from `ARCHITECTURE.md` 6.2, or the field means nothing."""

    def test_the_set_is_the_one_the_architecture_names(self) -> None:
        """Read out of `ARCHITECTURE.md` 6.2, not hand-copied beside it.

        The first version of this iterated `P.SOURCE_ROLE` and asserted each
        member loads clean, which cannot fail: shrink the constant to three and
        the loop checks three. A mutation dropping five roles survived it. Two
        hand-written lists are two authorities over one vocabulary, and the one
        nobody runs is the one that drifts -- the argument
        `test_documentation.py` makes about ADR 0001's verb block. This is
        stricter than that precedent: it asserts equality *and order*, where the
        verb test asserts a subset and says explicitly that documented-but-not-
        built verbs are the roadmap rather than a failure. A role in 6.2 that
        the code cannot express is a gap a reader should be told about, so here
        both directions are errors.
        """
        section = ARCHITECTURE.split("Typical artifact roles include:", 1)
        self.assertEqual(2, len(section),
                         "ARCHITECTURE.md 6.2 no longer lists artifact roles")
        listed = []
        for line in section[1].splitlines():
            line = line.strip()
            if line.startswith("* "):
                listed.append(line[2:].rstrip(";.").strip())
            elif listed and not line:
                break
        self.assertEqual(
            [_slug(name) for name in listed], list(P.SOURCE_ROLE),
            f"6.2 names {listed}; SOURCE_ROLE must be that list, in that order")

    def test_every_named_role_loads_clean(self) -> None:
        for role in P.SOURCE_ROLE:
            with self.subTest(role=role):
                self.assertEqual([], _artifact(role=role).problems(None))

    def test_an_invented_role_is_refused(self) -> None:
        self.assertEqual(
            {F.SCHEMA_ENUM},
            _codes(_artifact(role="SORT_OF_A_REFERENCE").problems(None)),
            "a role nothing can check is a note, and 6.2's list is the "
            "vocabulary every other reader of this field will use")

    def test_a_null_role_is_undeclared_like_every_other_optional_here(self) -> None:
        """`"role": null` is how this file's own recordings spell "not stated".

        `modify-ball-flange-flat/inputs/project.json` writes `"sha256": null`
        and `"units": null`, and `sha256`, `format`, `units` and
        `classification` all read `null` as undeclared. `role` did not: it went
        through `str(...)` with a `""` default, so `null` became the *string*
        `"None"` and was refused as a role nobody wrote -- a message naming a
        value that appears nowhere in the file.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            dataclasses.replace(_project(), source_mode="MODIFY",
                                model="model.py",
                                source_artifacts=(_artifact(),)).save(directory)
            payload = json.loads((directory / P.PROJECT_FILE)
                                 .read_text(encoding="utf-8"))
            payload["source_artifacts"][0]["role"] = None
            (directory / P.PROJECT_FILE).write_text(json.dumps(payload),
                                                    encoding="utf-8")
            loaded = P.load(directory).source_artifacts[0]
            self.assertEqual("", loaded.role)
            self.assertEqual([], loaded.problems(None))

    def test_no_role_is_the_declared_absence_and_not_a_defect(self) -> None:
        """`ROADMAP.md` 4.4: a job that declares nothing new gains no key in
        `project.json`. Every project written before this field existed declares no
        role, and none of them may start failing."""
        self.assertEqual([], _artifact().problems(None))
        self.assertEqual([], _artifact(role="").problems(None))


class ARoleDeclaredIsARoleKeptTest(unittest.TestCase):
    """The obligation, and the whole reason the field is worth having."""

    def _project_with(self, artifact, scope) -> P.Project:
        return dataclasses.replace(_project(), source_mode="MODIFY",
                                   model="model.py",
                                   source_artifacts=(artifact,),
                                   edit_scopes=(scope,))

    def test_an_edit_may_not_target_what_the_job_is_only_fitting_to(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            project = self._project_with(_artifact(role="MATING_OBJECT"),
                                         _scope())
            self.assertIn(
                F.INTENT_CONTRADICTION,
                _at(project.validate(directory, require_buildable=False),
                    "edit_scopes[0].artifact_id"),
                "the mount is fitted to the vent; editing the vent is a "
                "measurement about somebody else's object")

    def test_every_non_owned_role_is_refused_as_an_edit_target(self) -> None:
        """Each of these exists to be read, not written: what the part mates
        with, what it was measured against, the space it must fit inside, and a
        file already handed downstream."""
        for role in ("MATING_OBJECT", "MEASUREMENT_REFERENCE",
                     "VISUAL_ENVELOPE", "PRODUCTION_EXPORT"):
            with self.subTest(role=role), tempfile.TemporaryDirectory() as raw:
                directory = _laid_out(Path(raw))
                project = self._project_with(_artifact(role=role), _scope())
                self.assertIn(
                    F.INTENT_CONTRADICTION,
                    _at(project.validate(directory, require_buildable=False),
                        "edit_scopes[0].artifact_id"))

    def test_the_roles_whose_geometry_the_job_owns_may_be_edited(self) -> None:
        """Four, and "editable" does not mean written to.

        6.2 settles what it does mean: *"A repaired artifact is a distinct
        artifact with its own identity ... It never replaces the supplied
        file."* So the question is not whether the job writes the file -- it
        never does -- but whether the job may derive from it and deviate from
        it, which is what a preservation row measures.

        Base geometry and a donor are 6.8's own model of combination. A prior
        revision is the canonical MODIFY case, and measuring the new candidate
        against it is exactly the right measurement; 13.1 keeps that honest by
        requiring the correction to be a new revision rather than a rewrite. An
        alternative candidate is 6.15 verbatim -- reusing a tested phone cradle
        with a new vent attachment. The other four are read-only for the reason
        6.7 gives: *"External real objects are represented independently from
        the candidate design whenever possible."*
        """
        for role in ("BASE", "DONOR", "PRIOR_REVISION", "ALTERNATIVE_CANDIDATE"):
            with self.subTest(role=role), tempfile.TemporaryDirectory() as raw:
                directory = _laid_out(Path(raw))
                project = self._project_with(_artifact(role=role), _scope())
                self.assertEqual(
                    set(),
                    _at(project.validate(directory, require_buildable=False),
                        "edit_scopes[0].artifact_id"))

    def test_two_artifacts_may_not_claim_one_id(self) -> None:
        """This protection rests on identity, and identity was unchecked.

        `Project.artifact()` returns the first row matching an id, and
        `source_artifacts` had no duplicate check where requirements, datums and
        edit scopes all have one. So declaring the same file twice -- first
        `BASE`, then `MATING_OBJECT` -- let an edit scope over it validate
        clean, and swapping the two rows refused it. Whether the vent could be
        edited depended on declaration order.

        "One file is both my base and the thing I mate to" is exactly what a
        confused author writes, so this is the shape the new rule most needed
        closing. 6.2: *"Every imported or generated artifact has a stable
        identity."*
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            project = dataclasses.replace(
                _project(), source_mode="MODIFY", model="model.py",
                source_artifacts=(_artifact(role="BASE"),
                                  _artifact(role="MATING_OBJECT")),
                edit_scopes=(_scope(),))
            reported = project.validate(directory, require_buildable=False)
            self.assertIn(F.REF_DUPLICATE,
                          _at(reported, "source_artifacts[1].artifact_id"),
                          "two rows under one id are two answers to what that "
                          "file is for, and the first one wins by accident")

    def test_an_undeclared_role_is_not_an_accusation(self) -> None:
        """Silence is not permission granted, it is a question not asked. Every
        recorded project is in this state and none of them is wrong."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            project = self._project_with(_artifact(), _scope())
            self.assertEqual(
                set(), _at(project.validate(directory, require_buildable=False),
                           "edit_scopes[0].artifact_id"))

    def test_the_finding_names_the_role_and_what_it_forbids(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            project = self._project_with(_artifact(role="MATING_OBJECT"),
                                         _scope())
            (row,) = [r for r in project.validate(directory,
                                                  require_buildable=False)
                      if r.where == "edit_scopes[0].artifact_id"]
            self.assertIn("MATING_OBJECT", row.message)
            self.assertIn("src", row.message)


class TheRoleSurvivesTheRoundTripTest(unittest.TestCase):
    """A declaration that does not serialize is a declaration for one process."""

    def test_a_declared_role_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            artifact = _artifact(role="DONOR")
            dataclasses.replace(_project(), source_mode="MODIFY",
                                model="model.py",
                                source_artifacts=(artifact,)).save(directory)
            payload = json.loads((directory / P.PROJECT_FILE)
                                 .read_text(encoding="utf-8"))
            self.assertEqual("DONOR", payload["source_artifacts"][0]["role"])
            self.assertEqual((artifact,), P.load(directory).source_artifacts)

    def test_an_artifact_declaring_no_role_gains_no_key(self) -> None:
        """The five pinned certified contracts and every recorded project
        declare no role. An always-present key -- even empty -- is still an
        added key, and it would move all of them for a field they do not use."""
        self.assertNotIn("role", _artifact().as_dict())
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            dataclasses.replace(_project(), source_mode="MODIFY",
                                model="model.py",
                                source_artifacts=(_artifact(),)).save(directory)
            payload = json.loads((directory / P.PROJECT_FILE)
                                 .read_text(encoding="utf-8"))
            self.assertNotIn("role", payload["source_artifacts"][0])


if __name__ == "__main__":
    unittest.main()
