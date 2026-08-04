#!/usr/bin/env python3
"""Release 3 slice A: a second formulation of the same job, isolated on disk and
in the receipts.

Every test here fails on the code as it stood before the slice, and each fails
for a different reason. They are worth listing, because "two directories" reads
like a tidiness change and it is not:

* **the acceptance revision was a weapon.** Both siblings froze into one
  `acceptance_contract.json`. The second one's `freeze` read the first one's
  contract as `previous`, cut a revision, and `_invalidate` deleted the first's
  `final_status.json`, `commission_report.json`, `artifact_manifest.json`,
  `manufacturing_report.json` and both review reports. Re-running the first did
  it back. Two alternatives destroyed each other on every alternating run, and
  `acceptance_history.json` recorded the fork as one linear chain of corrections;
* **the second alternative was never commissioned.** `_run_authored` skips the
  designer commission when `design_proposal.json` and `model.py` both exist, so a
  branch inherited the first formulation's geometry, built it, and filed the
  receipts under its own name -- a job with no evidence anywhere that it was a
  different job;
* **`candidate.stl` and `candidate.step` are fixed literals**, so the second
  build simply overwrote the first;
* **a review was answered by the presence of a file.** One `reviews/` directory
  meant a sibling picked up the answer written for its neighbour;
* **and path isolation does not close any of the last one.** `ExecutionPlan`
  carries no parameters, so two formulations of one authored job compile to the
  same plan; `ReviewEnvelope.revision` is `updated_utc`, a timestamp rather than
  a graph node; and at the instant a branch is created its sibling is a copy, so
  `contract_sha256`, `artifact_hashes` and `witness_hashes` are equal too. A
  safety PASS written for one was `is_bound` for the other. That is a false pass
  of exactly the class the authority gate forbids, reachable with nobody doing
  anything wrong, and it is why `alternative_id` joins the envelope as well as
  the plan.

The zero-cost half is asserted here too, and it is exact rather than a stopwatch:
a project declaring no alternatives serializes, compiles and hashes to the bytes
it did before this file existed.

The half of this file the commit gate will not carry is in
`benchmarks/heavy/test_alternatives_heavy.py`, and runs before merge instead of
on every push: `AReviewBoundToOneBranchTest`, `CleanCloneTest`,
`NoAlternativesCostsNothingTest`, `OneBranchFailingTest`,
`SharedChangeInvalidatesEveryAlternativeTest`,
`SharedInputIsStillFoundFromABranchTest`, `TwoSiblingsTest`. Same tests, moved
rather than weakened; `conftest.py` carries the rule and
`benchmarks/heavy/README.md` the measurement behind it.
"""
from __future__ import annotations

import dataclasses
import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from . import acceptance as ACC
from . import cli
from . import project as P
from . import schemas as S

UTC = "1970-01-01T00:00:00Z"

# One block per formulation, differing in the numbers a plan never sees. That is
# the point of the pair: the two build materially different solids and their
# execution plans are identical apart from the id this slice adds.
MODEL = '''
import trimesh

PARAMS = {{"w": {w}, "d": {d}, "h": {h}}}


def build():
    block = trimesh.creation.box(extents=({w}, {d}, {h}))
    block.apply_translation(({w} / 2, {d} / 2, {h} / 2))
    return block
'''


def _proposal(design_id: str, *, w: float, d: float, h: float) -> dict:
    return {
        "schema_version": 1,
        "job_id": "branching",
        "design_id": design_id,
        "rationale": f"a {w}x{d}x{h} block standing in for one formulation",
        "params": {"w": w, "d": d, "h": h},
        "bbox_mm": {"x": w, "y": d, "z": h},
        "bodies": 1,
        "profile_marks": {"z": []},
        "features": [
            {"feature_id": "block-section", "kind": "section_area",
             "at": {"z": h / 2}, "value_mm2": w * d},
            {"feature_id": "bed-footprint", "kind": "bed_contact",
             "value_mm2": w * d},
        ],
    }


SCREW = dict(w=40.0, d=30.0, h=10.0)
SNAP = dict(w=36.0, d=26.0, h=12.0)


def _project(**over) -> P.Project:
    base = dict(
        job_id="branching", updated_utc=UTC, source_mode="NEW",
        consequence="INCONSEQUENTIAL",
        consequence_rationale="a desk bracket; failure wastes material",
        printer="Test Printer", material={"process": "FDM", "material": "PLA"},
        nozzle={"diameter_mm": 0.4},
        orientation={"model_to_printer_matrix": "identity", "bed_z_mm": 0.0},
        template=None, parameters={}, model="model.py",
        envelope_mm={"x": 60.0, "y": 50.0, "z": 20.0},
        reviewer={"model_snapshot": "test"},
        requirements=(P.Requirement(name="mount_pitch", value=32.0, unit="mm",
                                    provenance="STATED", source="user"),),
    )
    base.update(over)
    return P.Project(**base)


def _laid_out(root: Path, project: P.Project | None = None) -> Path:
    directory = root / "project"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "brief.md").write_text("a bracket", encoding="utf-8")
    (project or _project()).save(directory)
    return directory


def _author(where: Path, design_id: str, **params) -> None:
    """Write one formulation's two files: what it must measure, and how it is built."""
    where.mkdir(parents=True, exist_ok=True)
    (where / "model.py").write_text(textwrap.dedent(MODEL.format(**params)),
                                    encoding="utf-8")
    (where / ACC.PROPOSAL_FILE).write_text(
        S.canonical_json(_proposal(design_id, **params)), encoding="utf-8")


def _branch(directory: Path, *, parent: str, name: str, reason: str) -> int:
    return cli.branch([str(directory), "--from", parent, "--id", name,
                       "--reason", reason])


def _alt(directory: Path, name: str) -> Path:
    return directory / P.ALTERNATIVES_DIR / name


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _lifecycle_rows(disposition: str) -> tuple[P.Alternative, ...]:
    """`snap-fit` in one lifecycle state, with everything that state demands.

    The successor exists and names `snap-fit` as a parent, so a `MERGED` row here
    is describing a graph that records the merge rather than asserting one -- and
    the only finding the caller can be left with is the runnability rule.
    """
    rows = [P.Alternative(
        alternative_id="snap-fit", reason="no fasteners",
        disposition=disposition,
        basis="" if disposition == "ACTIVE" else "USER_SELECTION",
        superseded_by="successor" if disposition in P.SUCCESSOR_REQUIRED else "")]
    if disposition in P.SUCCESSOR_REQUIRED:
        rows.append(P.Alternative(alternative_id="successor", parents=("snap-fit",),
                                  reason="what replaced it"))
    return tuple(rows)


def _digests(directory: Path) -> dict[str, str]:
    """Every file under a directory, by content, so "unchanged" is checkable."""
    return {p.relative_to(directory).as_posix(): S.sha256_file(p)
            for p in sorted(directory.rglob("*")) if p.is_file()}


# ---------------------------------------------------------------------------
# The branch verb
# ---------------------------------------------------------------------------

class BranchVerbTest(unittest.TestCase):
    """One deterministic verb, zero AI calls, and it copies nothing."""

    def test_branching_writes_a_row_and_copies_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            _author(directory, "ancestor", **SCREW)
            before = _digests(directory)

            self.assertEqual(0, _branch(directory, parent=".", name="snap-fit",
                                        reason="no fasteners to lose"))

            project = P.load(directory)
            self.assertEqual(("snap-fit",),
                             tuple(a.alternative_id for a in project.alternatives))
            row = project.alternative("snap-fit")
            self.assertEqual((), row.parents, "--from . is the shared root")
            self.assertEqual("ACTIVE", row.disposition)
            self.assertEqual("snap-fit", project.active_alternative)

            # The directory exists and is empty: an alternative inherits shared
            # intent by reference, and duplicating the ancestor's proposal would
            # make the branch a copy nobody could tell from a formulation.
            self.assertTrue(_alt(directory, "snap-fit").is_dir())
            self.assertEqual([], list(_alt(directory, "snap-fit").iterdir()))

            # Nothing that already existed moved, except project.json itself.
            after = _digests(directory)
            self.assertEqual({name: digest for name, digest in before.items()
                              if name != P.PROJECT_FILE},
                             {name: digest for name, digest in after.items()
                              if name != P.PROJECT_FILE})

    def test_an_id_that_is_not_a_safe_directory_name_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            for name in ("Snap Fit", "../escape", "snap_fit", "SNAP", "",
                         "snap/fit", "snap.fit"):
                with self.subTest(alternative_id=name):
                    self.assertEqual(2, _branch(directory, parent=".", name=name,
                                                reason="because"))
                    self.assertEqual((), P.load(directory).alternatives)
                    self.assertFalse((directory / P.ALTERNATIVES_DIR).exists())

    def test_a_second_row_for_one_id_is_refused_rather_than_replacing_it(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            self.assertEqual(0, _branch(directory, parent=".", name="snap-fit",
                                        reason="no fasteners to lose"))
            self.assertEqual(2, _branch(directory, parent=".", name="snap-fit",
                                        reason="a different story entirely"))
            rows = P.load(directory).alternatives
            self.assertEqual(1, len(rows))
            self.assertEqual("no fasteners to lose", rows[0].reason)

    def test_a_parent_nothing_declares_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            self.assertEqual(2, _branch(directory, parent="magnetic",
                                        name="snap-fit", reason="because"))
            self.assertEqual((), P.load(directory).alternatives)

    def test_a_branch_with_no_reason_is_refused(self) -> None:
        """Two formulations with no stated difference cannot be compared."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            self.assertEqual(2, cli.branch([str(directory), "--from", ".",
                                            "--id", "snap-fit"]))
            self.assertEqual(2, _branch(directory, parent=".", name="snap-fit",
                                        reason="   "))
            self.assertEqual((), P.load(directory).alternatives)

    def test_the_parent_list_carries_the_ancestor_it_was_branched_from(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            _branch(directory, parent=".", name="base", reason="the shared start")
            _branch(directory, parent="base", name="snap-fit", reason="no fasteners")
            row = P.load(directory).alternative("snap-fit")
            self.assertEqual(("base",), row.parents,
                             "a list from the first commit that has one, so a "
                             "merge is additive rather than a schema change")

    def test_switching_back_to_the_shared_root_is_possible(self) -> None:
        """A system that could only branch could never return to what it branched from."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            _branch(directory, parent=".", name="snap-fit", reason="no fasteners")
            self.assertEqual(0, cli.branch([str(directory), "--activate", "."]))
            self.assertIsNone(P.load(directory).active_alternative)
            self.assertEqual(0, cli.branch([str(directory), "--activate", "snap-fit"]))
            self.assertEqual("snap-fit", P.load(directory).active_alternative)

    def test_activating_something_nothing_declares_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            self.assertEqual(2, cli.branch([str(directory), "--activate", "magnetic"]))
            self.assertIsNone(P.load(directory).active_alternative)

    def test_only_a_runnable_disposition_may_be_worked_under(self) -> None:
        """Three may be worked under; the other four refuse, for two reasons.

        `FALLBACK` is on the runnable side and that is the whole point of it: a
        retained formulation you may not keep current is a rejection with a
        kinder word, which is why the vent-ball job had to record one as ACTIVE.
        `PAUSED` refuses and says to resume; the three concluded states refuse
        and say to branch, because reopening one in place would rewrite the
        history it is the record of.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            _branch(directory, parent=".", name="snap-fit", reason="no fasteners")
            for disposition, runnable in (("ACTIVE", True), ("PREFERRED", True),
                                          ("FALLBACK", True), ("PAUSED", False),
                                          ("REJECTED", False), ("SUPERSEDED", False),
                                          ("MERGED", False)):
                with self.subTest(disposition=disposition):
                    project = P.load(directory)
                    project.alternatives = _lifecycle_rows(disposition)
                    project.active_alternative = "snap-fit"
                    project.save(directory)
                    problems = project.validate(directory, require_buildable=False)
                    # Nothing but the runnability rule is under test here: every
                    # row carries the basis and the successor its state demands.
                    self.assertEqual(
                        [] if runnable else ["INTENT_UNSUPPORTED@active_alternative"],
                        [p.id for p in problems], problems)
                    self.assertEqual(0 if runnable else 2,
                                     cli.branch([str(directory), "--activate",
                                                 "snap-fit"]))

    def test_a_disposition_that_only_labels_is_refused(self) -> None:
        """ARCHITECTURE.md 14.6 says a disposition includes its basis. It does."""
        for disposition in P.BASIS_REQUIRED:
            with self.subTest(disposition=disposition):
                rows = (P.Alternative(alternative_id="snap-fit", reason="no fasteners",
                                      disposition=disposition,
                                      superseded_by=("screw" if disposition
                                                     in P.SUCCESSOR_REQUIRED else "")),
                        P.Alternative(alternative_id="screw", reason="fasteners",
                                      parents=("snap-fit",)))
                problems = _project(alternatives=rows).validate(require_buildable=False)
                self.assertIn("SCHEMA_REQUIRED@alternatives[0].basis",
                              [p.id for p in problems], problems)
        self.assertEqual(
            [], _project(alternatives=(P.Alternative(
                alternative_id="snap-fit", reason="no fasteners"),)).validate(
                    require_buildable=False),
            "ACTIVE is the state a formulation starts in; demanding a reason for "
            "nothing having happened yet would be demanding a reason for nothing")

    def test_two_preferred_formulations_are_two_answers_to_one_question(self) -> None:
        rows = (P.Alternative(alternative_id="a", reason="one",
                              disposition="PREFERRED", basis="USER_SELECTION"),
                P.Alternative(alternative_id="b", reason="two",
                              disposition="PREFERRED", basis="USER_SELECTION"))
        problems = _project(alternatives=rows).validate(require_buildable=False)
        self.assertEqual(["REF_DUPLICATE@alternatives[1].disposition"],
                         [p.id for p in problems], problems)

    def test_merged_is_refused_until_the_graph_records_the_merge(self) -> None:
        """The one state this build cannot produce, and will not accept on trust.

        `parents` has been a list since the commit that introduced it, for
        exactly this: a merge is a revision with *several* contributing parents
        (ARCHITECTURE.md 13.2), and nothing in this build writes more than one
        entry. So a merge record is hand-written, and what this slice adds is
        that `MERGED` is checked against it rather than believed.
        """
        first = P.Alternative(alternative_id="screwed", reason="serviceable",
                              disposition="MERGED", basis="STRONGER_CONCEPT",
                              superseded_by="hybrid")
        second = P.Alternative(alternative_id="snap-fit", reason="no fasteners")
        detached = P.Alternative(alternative_id="hybrid",
                                 reason="a screw boss inside a snapping shell")
        self.assertEqual(
            ["REF_UNDECLARED@alternatives[0].superseded_by"],
            [p.id for p in _project(
                alternatives=(first, second, detached)).validate(
                    require_buildable=False)])
        joined = dataclasses.replace(detached, parents=("screwed", "snap-fit"))
        self.assertEqual(
            [], _project(alternatives=(first, second, joined)).validate(
                require_buildable=False),
            "two contributing parents is what a merge record looks like; once "
            "one exists, MERGED is describing the graph rather than asserting it")

    def test_a_successor_is_refused_where_it_cannot_mean_anything(self) -> None:
        for row, expected in (
            (P.Alternative(alternative_id="a", reason="x", disposition="PAUSED",
                           basis="USER_SELECTION", superseded_by="b"),
             "INTENT_CONTRADICTION@alternatives[0].superseded_by"),
            (P.Alternative(alternative_id="a", reason="x", disposition="SUPERSEDED",
                           basis="STRONGER_CONCEPT", superseded_by="a"),
             "REF_ORDER@alternatives[0].superseded_by"),
            (P.Alternative(alternative_id="a", reason="x", disposition="SUPERSEDED",
                           basis="STRONGER_CONCEPT", superseded_by="nobody"),
             "REF_UNDECLARED@alternatives[0].superseded_by"),
        ):
            with self.subTest(expected=expected):
                other = P.Alternative(alternative_id="b", reason="y")
                problems = _project(alternatives=(row, other)).validate(
                    require_buildable=False)
                self.assertIn(expected, [p.id for p in problems], problems)

    def test_creating_and_switching_are_not_mixed_in_one_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            _branch(directory, parent=".", name="snap-fit", reason="no fasteners")
            self.assertEqual(2, cli.branch([str(directory), "--activate", "snap-fit",
                                            "--id", "screw-fastened"]))

    def test_a_hand_written_cycle_is_refused(self) -> None:
        """Ancestry order is the acyclicity rule, and it refuses a self-parent too."""
        for rows in (
            (P.Alternative(alternative_id="a", parents=("b",), reason="x"),
             P.Alternative(alternative_id="b", parents=("a",), reason="y")),
            (P.Alternative(alternative_id="a", parents=("a",), reason="x"),),
        ):
            with self.subTest(rows=[r.alternative_id for r in rows]):
                problems = _project(alternatives=rows).validate(
                    require_buildable=False)
                self.assertTrue(any("ancestry order" in p.message for p in problems),
                                problems)


# ---------------------------------------------------------------------------
# The zero-cost proof
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Two siblings from one ancestor
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Failure and invalidation
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# The false pass
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Reconstruction
# ---------------------------------------------------------------------------


class OneJobHasOneFormulationCountTest(unittest.TestCase):
    """`docs/defects.md` D26: `status` counted the job two different ways.

    `design-tool branch` writes no `alternatives` row for the shared root -- the
    root is a formulation by having a directory, a proposal, a contract and its
    own receipts, not by being declared. So the `alternatives` block iterated
    `project.alternatives` and saw two formulations of the recorded knob while
    the `cost` block in the same report iterated the union and saw three. One
    report, two answers to "what is this job".

    The quieter half is here too. `_derived_at` returns five fields --
    `derived_status`, `stored_status`, `allowed_claim`, `stale` and `reasons` --
    and the loop kept two, so per-formulation staleness was unreadable from the
    report. `tools/replay.py` is the proof it was missed: to record what each
    formulation currently supports the harness had to issue `branch --activate`
    and `status` once per formulation, because one `status` call could not say.
    """

    def _status(self, directory: Path) -> dict:
        import contextlib
        import io
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(0, cli.status([str(directory), "--json"]))
        return json.loads(stream.getvalue())

    def _job(self, root: Path) -> Path:
        directory = _laid_out(root)
        _author(directory, "ancestor", **SCREW)
        for name in ("snap-fit", "magnetic"):
            self.assertEqual(0, _branch(directory, parent=".", name=name,
                                        reason=f"the {name} concept"))
        return directory

    def test_the_two_blocks_of_one_report_count_the_same_formulations(self) -> None:
        """The defect, as the arithmetic that exposed it.

        Fails before the fix with 3 against 4: `cost.by_alternative` carries the
        root and `alternatives` does not.
        """
        with tempfile.TemporaryDirectory() as raw:
            report = self._status(self._job(Path(raw)))

            named = {row["alternative_id"] for row in report["alternatives"]}
            costed = set(report["cost"]["by_alternative"])
            self.assertEqual(
                costed, named,
                "one job, one set of formulations. A caller taking its set from "
                "`alternatives` silently drops the shared root, which on the "
                "recorded knob is one of the two designs")
            self.assertIn(cli.ROOT_ALTERNATIVE, named,
                          "the root is a formulation: it has a directory, a "
                          "proposal, a contract and its own receipts")

    def test_the_root_is_named_as_a_formulation_and_not_as_a_row_branch_wrote(self) -> None:
        """It has no declared row, and `branch` must not start writing one.

        The fix is to iterate the union in the report, not to invent an
        `alternatives` entry in `project.json` -- that would make the root a
        thing a user could reject or supersede, and change what every existing
        project deserialises to.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = self._job(Path(raw))
            report = self._status(directory)

            self.assertEqual(
                ("snap-fit", "magnetic"),
                tuple(a.alternative_id for a in P.load(directory).alternatives),
                "project.json still declares exactly the two branches")
            root = next(row for row in report["alternatives"]
                        if row["alternative_id"] == cli.ROOT_ALTERNATIVE)
            self.assertEqual("ACTIVE", root["disposition"])
            # Absent rather than empty, because that is what `Alternative.as_dict`
            # does with a basis nobody set -- the rule that keeps a project from
            # moving for a field it never carried. The root goes through the same
            # serialisation as any other row rather than a second one written for
            # it, which is the point: it is a formulation, not a special case.
            self.assertNotIn("basis", root)

    def test_each_formulation_reports_what_stopped_binding_and_not_only_its_status(self) -> None:
        """The half `tools/replay.py` had to work around one command at a time."""
        with tempfile.TemporaryDirectory() as raw:
            report = self._status(self._job(Path(raw)))
            for row in report["alternatives"]:
                with self.subTest(formulation=row["alternative_id"]):
                    for field in ("status", "stored_status", "stale",
                                  "allowed_claim"):
                        self.assertIn(field, row)
                    self.assertIsInstance(row["stale"], list)


if __name__ == "__main__":
    unittest.main()
