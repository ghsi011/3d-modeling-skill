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
"""
from __future__ import annotations

import json
import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path

from . import acceptance as ACC
from . import cli
from . import execution as EX
from . import project as P
from . import review as R
from . import schemas as S
from . import selftest as ST

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

    def test_only_the_two_honoured_dispositions_may_be_worked_under(self) -> None:
        """The other five are stored and read by nothing, and say so."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            _branch(directory, parent=".", name="snap-fit", reason="no fasteners")
            for disposition, allowed in (("ACTIVE", True), ("PREFERRED", True),
                                         ("PAUSED", False), ("REJECTED", False),
                                         ("SUPERSEDED", False), ("FALLBACK", False),
                                         ("MERGED", False)):
                with self.subTest(disposition=disposition):
                    project = P.load(directory)
                    project.alternatives = (P.Alternative(
                        alternative_id="snap-fit", reason="no fasteners",
                        disposition=disposition),)
                    project.active_alternative = "snap-fit"
                    project.save(directory)
                    problems = project.validate(directory, require_buildable=False)
                    self.assertEqual(allowed, not any("honoured" in p for p in problems),
                                     problems)
                    self.assertEqual(0 if allowed else 2,
                                     cli.branch([str(directory), "--activate",
                                                 "snap-fit"]))

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
                self.assertTrue(any("ancestry order" in p for p in problems),
                                problems)


# ---------------------------------------------------------------------------
# The zero-cost proof
# ---------------------------------------------------------------------------

class NoAlternativesCostsNothingTest(unittest.TestCase):
    """A project declaring no alternatives is byte-identical to one that could not.

    Exact rather than a stopwatch. Every new field follows one rule -- absent when
    there is nothing to say, never `null` -- because a `null` in a hashed payload
    moves every digest on every job in the corpus in exchange for information the
    reader already had.
    """

    def test_the_project_payload_gains_no_key(self) -> None:
        payload = _project().as_payload()
        self.assertNotIn("alternatives", payload)
        self.assertNotIn("active_alternative", payload)

    def test_the_execution_plan_payload_gains_no_key(self) -> None:
        plan = EX.compile_plan(_project())
        self.assertIsNone(plan.alternative_id)
        self.assertNotIn("alternative_id", plan.as_payload())

    def test_the_review_envelope_gains_no_key_and_no_digest_moves(self) -> None:
        """And it deliberately does not follow `execution_plan_sha256`'s precedent.

        That field is emitted unconditionally, `null` included. Copying it here
        would move every stored envelope digest on every unbranched job.
        """
        envelope = R.build_envelope(
            kind="safety", job_id="j", revision=UTC, packet_hash="p" * 64,
            reviewer={}, contract_hash="c" * 64)
        self.assertNotIn("alternative_id", envelope.as_dict())
        self.assertIn("execution_plan_sha256", envelope.as_dict())
        self.assertEqual(S.payload_hash(envelope.as_dict()), envelope.digest())

    def test_an_absent_alternative_and_a_null_one_read_the_same(self) -> None:
        """So nothing has to be migrated to read an envelope either way."""
        envelope = R.build_envelope(
            kind="safety", job_id="j", revision=UTC, packet_hash="p" * 64,
            reviewer={}, contract_hash="c" * 64)
        spelled = {**envelope.as_dict(), "alternative_id": None}
        self.assertIsNone(
            R._envelope_from_dict(spelled).alternative_id)

    def test_the_acceptance_history_of_an_unbranched_job_gains_no_key(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            _author(directory, "ancestor", **SCREW)
            cli.run([str(directory), "--no-render"])
            history = _read(directory / ACC.HISTORY_FILE)
            self.assertEqual(1, len(history["revisions"]))
            self.assertNotIn("alternative_id", history["revisions"][0])

    def test_an_ordinary_project_grows_no_subdirectory(self) -> None:
        """Nothing that names candidate.stl at the project root changes."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            _author(directory, "ancestor", **SCREW)
            cli.run([str(directory), "--no-render"])
            self.assertFalse((directory / P.ALTERNATIVES_DIR).exists())
            self.assertTrue((directory / "candidate.stl").is_file())
            self.assertTrue((directory / ACC.ACCEPTANCE_FILE).is_file())
            self.assertTrue((directory / cli.EXECUTION_PLAN_FILE).is_file())

    def test_the_shipped_goldens_are_untouched(self) -> None:
        """The five pinned certified contracts, from the one copy of the golden.

        Called rather than restated: two copies of a golden is two goldens, and
        the one nobody runs is the one that drifts. If this slice had put
        `alternative_id` anywhere near `contract_sha256` -- which it must not,
        because two formulations requiring identical geometry legitimately share
        an acceptance contract -- these are what would move.
        """
        report = ST.run(quick=True)
        self.assertTrue(report["ok"], [c for c in report["cases"] if not c["ok"]])


# ---------------------------------------------------------------------------
# Two siblings from one ancestor
# ---------------------------------------------------------------------------

class TwoSiblingsTest(unittest.TestCase):
    """The fork, end to end, through the command surface a user has."""

    def _forked(self, root: Path) -> Path:
        """An ancestor formulation at the root, and two siblings branched from it."""
        directory = _laid_out(root)
        _author(directory, "ancestor", **SCREW)
        cli.run([str(directory), "--no-render"])

        _branch(directory, parent=".", name="screw-fastened",
                reason="the fallback everybody can service")
        _author(_alt(directory, "screw-fastened"), "screw-fastened", **SCREW)
        cli.run([str(directory), "--no-render"])

        cli.branch([str(directory), "--activate", "."])
        _branch(directory, parent=".", name="snap-fit",
                reason="no fasteners to lose in the field")
        _author(_alt(directory, "snap-fit"), "snap-fit", **SNAP)
        cli.run([str(directory), "--no-render"])
        return directory

    def test_each_sibling_is_commissioned_as_itself(self) -> None:
        """The defect: a branch was never commissioned and rebuilt its parent.

        `_run_authored` skips the designer commission when the proposal and the
        model both exist, so with one shared directory the second alternative
        found the first's files, built the first's geometry and wrote the
        receipts under its own name. Nothing on disk said the two were different
        jobs, because they were not.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = self._forked(Path(raw))
            for name, params in (("screw-fastened", SCREW), ("snap-fit", SNAP)):
                with self.subTest(alternative=name):
                    contract = _read(_alt(directory, name) / ACC.ACCEPTANCE_FILE)
                    self.assertEqual(name, contract["design_id"])
                    self.assertEqual(params["w"], contract["expected_bbox_mm"]["x"])
                    self.assertEqual(1, contract["revision"])

    def test_a_branch_is_commissioned_by_path_rather_than_by_a_bare_filename(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            _branch(directory, parent=".", name="snap-fit", reason="no fasteners")
            self.assertEqual(cli.NEEDS_ACTION, cli.run([str(directory), "--no-render"]))
            action = _read(_alt(directory, "snap-fit") / cli.NEXT_ACTION_FILE)
            self.assertEqual("AGENT_COMMISSION", action["kind"])
            self.assertIn("alternatives/snap-fit/model.py", action["required_outputs"])
            self.assertIn("alternatives/snap-fit/design_proposal.json",
                          action["required_outputs"])
            self.assertIn(P.PROJECT_FILE, action["authorized_inputs"],
                          "shared intent is still read from the one project file")
            self.assertFalse((directory / cli.NEXT_ACTION_FILE).exists(),
                             "the root's own instruction is not overwritten by a "
                             "branch's")

    def test_no_artifact_is_overwritten_between_siblings(self) -> None:
        """`candidate.stl` and `candidate.step` are fixed literals."""
        with tempfile.TemporaryDirectory() as raw:
            directory = self._forked(Path(raw))
            screw = _alt(directory, "screw-fastened") / "candidate.stl"
            snap = _alt(directory, "snap-fit") / "candidate.stl"
            self.assertTrue(screw.is_file())
            self.assertTrue(snap.is_file())
            self.assertNotEqual(S.sha256_file(screw), S.sha256_file(snap))
            for name in ("candidate_declaration.json", "artifact_manifest.json",
                         "commission_report.json", "final_status.json",
                         ACC.ACCEPTANCE_FILE, ACC.HISTORY_FILE,
                         cli.EXECUTION_PLAN_FILE, cli.ROUTE_DECISION_FILE,
                         cli.PLAN_FILE):
                with self.subTest(artifact=name):
                    left = _alt(directory, "screw-fastened") / name
                    right = _alt(directory, "snap-fit") / name
                    self.assertTrue(left.is_file() and right.is_file())

    def test_neither_sibling_cuts_a_revision_from_the_other(self) -> None:
        """The worst of the collisions, and the one that ran in a loop.

        A shared `acceptance_contract.json` made the second freeze read the
        first's contract as `previous`. It bumped the revision, `_invalidate`
        deleted the first's receipts, and the history recorded a fork as a linear
        supersession chain. Each alternative now freezes revision 1 and
        supersedes nothing.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = self._forked(Path(raw))
            for name in ("screw-fastened", "snap-fit"):
                with self.subTest(alternative=name):
                    history = _read(_alt(directory, name) / ACC.HISTORY_FILE)
                    self.assertEqual(1, len(history["revisions"]))
                    entry = history["revisions"][0]
                    self.assertEqual(1, entry["revision"])
                    self.assertIsNone(entry["supersedes"],
                                      "a branch is not a correction of its sibling")
                    self.assertEqual(name, entry["alternative_id"])

    def test_rerunning_one_sibling_leaves_the_other_byte_for_byte(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = self._forked(Path(raw))
            untouched = _digests(_alt(directory, "screw-fastened"))
            cli.branch([str(directory), "--activate", "snap-fit"])
            cli.run([str(directory), "--no-render"])
            cli.run([str(directory), "--no-render"])
            self.assertEqual(untouched, _digests(_alt(directory, "screw-fastened")))

    def test_the_shared_project_file_never_speaks_for_one_formulation(self) -> None:
        """`status` and `bindings` were one run's outcome, and are gone.

        The project file cannot move, so a branch must not stamp it: otherwise
        `project.json` says the job is whatever the last sibling to finish was --
        the same collision as a shared `final_status.json`, in the one file that
        has to stay shared. Slice A stopped the branch stamping it, which left
        the mirror true of the root and silently wrong for as long as a branch
        was active; slice B removes it. Every formulation's outcome, the root's
        included, is `final_status.json` in that formulation's own directory.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = self._forked(Path(raw))
            payload = _read(directory / P.PROJECT_FILE)
            self.assertNotIn("status", payload)
            self.assertNotIn("bindings", payload)

            root = _read(directory / "final_status.json")["artifact_hashes"]
            for name in ("screw-fastened", "snap-fit"):
                with self.subTest(alternative=name):
                    branch = _read(_alt(directory, name) / "final_status.json")
                    self.assertNotEqual(branch["artifact_hashes"], root)

    def test_status_reports_the_active_formulation_and_its_own_bindings(self) -> None:
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as raw:
            directory = self._forked(Path(raw))
            for name in ("screw-fastened", "snap-fit"):
                with self.subTest(alternative=name):
                    cli.branch([str(directory), "--activate", name])
                    stream = io.StringIO()
                    with contextlib.redirect_stdout(stream):
                        cli.status([str(directory), "--json"])
                    report = json.loads(stream.getvalue())
                    self.assertEqual(name, report["alternative"])
                    self.assertEqual(
                        {"screw-fastened", "snap-fit"},
                        {row["alternative_id"] for row in report["alternatives"]})
                    final = _read(_alt(directory, name) / "final_status.json")
                    self.assertEqual(final["artifact_hashes"], report["bindings"])

    def test_two_formulations_may_share_one_acceptance_contract(self) -> None:
        """`alternative_id` deliberately does not join `contract_sha256`.

        Two formulations that require identical geometry are two ways of getting
        there, not two parts. Making their contracts differ would invent a
        difference the job does not have, and would move the five pinned certified
        goldens on the way.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            for name in ("printed-in-one", "printed-in-two"):
                _branch(directory, parent=".", name=name, reason=f"{name} route")
                _author(_alt(directory, name), "same-shape", **SCREW)
                cli.run([str(directory), "--no-render"])
                cli.branch([str(directory), "--activate", "."])
            left = _read(_alt(directory, "printed-in-one") / ACC.ACCEPTANCE_FILE)
            right = _read(_alt(directory, "printed-in-two") / ACC.ACCEPTANCE_FILE)
            self.assertEqual(left["contract_sha256"], right["contract_sha256"])


# ---------------------------------------------------------------------------
# Failure and invalidation
# ---------------------------------------------------------------------------

class OneBranchFailingTest(unittest.TestCase):
    """A branch that cannot build must not take its sibling's evidence with it."""

    def test_a_failed_branch_leaves_the_sibling_s_receipts_intact(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            _branch(directory, parent=".", name="screw-fastened",
                    reason="the fallback everybody can service")
            _author(_alt(directory, "screw-fastened"), "screw-fastened", **SCREW)
            cli.run([str(directory), "--no-render"])
            good = _digests(_alt(directory, "screw-fastened"))
            self.assertIn("final_status.json", good)

            cli.branch([str(directory), "--activate", "."])
            _branch(directory, parent=".", name="snap-fit", reason="no fasteners")
            broken = _alt(directory, "snap-fit")
            _author(broken, "snap-fit", **SNAP)
            # A model whose declared PARAMS contradict its own proposal: the run
            # is refused after the freeze and before any receipt is written.
            (broken / "model.py").write_text(textwrap.dedent(MODEL.format(
                w=99.0, d=99.0, h=99.0)), encoding="utf-8")

            self.assertNotEqual(0, cli.run([str(directory), "--no-render"]))
            self.assertFalse((broken / "final_status.json").exists())
            self.assertTrue((broken / cli.NEXT_ACTION_FILE).is_file())
            self.assertEqual(good, _digests(_alt(directory, "screw-fastened")))


class SharedChangeInvalidatesEveryAlternativeTest(unittest.TestCase):
    """One rule: the shared half invalidates everything, a branch invalidates itself."""

    def _two(self, root: Path) -> Path:
        directory = _laid_out(root)
        for name, params in (("screw-fastened", SCREW), ("snap-fit", SNAP)):
            _branch(directory, parent=".", name=name, reason=f"the {name} concept")
            _author(_alt(directory, name), name, **params)
            cli.run([str(directory), "--no-render"])
            cli.branch([str(directory), "--activate", "."])
        return directory

    def test_a_changed_shared_requirement_invalidates_both(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = self._two(Path(raw))
            project = P.load(directory)
            project.requirements = (P.Requirement(
                name="mount_pitch", value=48.0, unit="mm",
                provenance="STATED", source="user"),)
            project.save(directory)

            for name in ("screw-fastened", "snap-fit"):
                with self.subTest(alternative=name):
                    where = _alt(directory, name)
                    before = _read(where / ACC.ACCEPTANCE_FILE)["contract_sha256"]
                    cli.branch([str(directory), "--activate", name])
                    cli.run([str(directory), "--no-render"])
                    contract = _read(where / ACC.ACCEPTANCE_FILE)
                    self.assertEqual(2, contract["revision"])
                    self.assertNotEqual(before, contract["contract_sha256"])

                    entry = _read(where / ACC.HISTORY_FILE)["revisions"][1]
                    self.assertEqual(name, entry["alternative_id"])
                    self.assertEqual(name, entry["supersedes"]["alternative_id"],
                                     "a revision that superseded a *different* "
                                     "formulation would be a fork recorded as a "
                                     "correction")
                    self.assertIn("requirement_sha256",
                                  " ".join(entry["changed"]))

    def test_a_change_inside_one_alternative_invalidates_that_one_only(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = self._two(Path(raw))
            untouched = _digests(_alt(directory, "screw-fastened"))

            _author(_alt(directory, "snap-fit"), "snap-fit",
                    w=34.0, d=24.0, h=14.0)
            cli.branch([str(directory), "--activate", "snap-fit"])
            cli.run([str(directory), "--no-render"])

            self.assertEqual(
                2, _read(_alt(directory, "snap-fit") / ACC.ACCEPTANCE_FILE)["revision"])
            self.assertEqual(untouched, _digests(_alt(directory, "screw-fastened")))

    def test_the_superseded_receipts_are_recorded_before_they_are_removed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = self._two(Path(raw))
            _author(_alt(directory, "snap-fit"), "snap-fit", w=34.0, d=24.0, h=14.0)
            cli.branch([str(directory), "--activate", "snap-fit"])
            cli.run([str(directory), "--no-render"])
            entry = _read(_alt(directory, "snap-fit") / ACC.HISTORY_FILE)["revisions"][1]
            self.assertIn("final_status.json",
                          entry["supersedes"]["invalidated_receipts"])


class SharedInputIsStillFoundFromABranchTest(unittest.TestCase):
    """Branching copies nothing, so shared inputs must still resolve."""

    def test_a_branch_measures_preservation_against_the_shared_source(self) -> None:
        """The declared source artifact is a project input, not a branch's file.

        `commission` looked beside the candidate, which stopped being beside the
        project the moment the candidate moved under `alternatives/<id>`. The
        symptom would have been `SOURCE_MISSING` on a file sitting exactly where
        the project declared it -- a preservation audit that fails closed for the
        wrong reason and tells the reader to go and find a file that is already
        there.
        """
        import trimesh

        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), _project(
                source_mode="MODIFY",
                source_artifacts=(P.SourceArtifact(
                    artifact_id="src", path="source.stl", format="STL",
                    classification="USABLE_MESH"),),
                edit_scopes=(P.EditScope(
                    artifact_id="src", region="the mounting boss",
                    region_box={"min": [5.0, 5.0, 0.0], "max": [15.0, 15.0, 10.0]},
                    preserve=("everything but the boss",)),)))
            block = trimesh.creation.box(extents=(40.0, 30.0, 10.0))
            block.apply_translation((20.0, 15.0, 5.0))
            block.export(directory / "source.stl")

            _branch(directory, parent=".", name="snap-fit", reason="no fasteners")
            _author(_alt(directory, "snap-fit"), "snap-fit", **SCREW)
            cli.run([str(directory), "--no-render"])

            report = _read(_alt(directory, "snap-fit") / "commission_report.json")
            rows = [c for c in report["checks"]
                    if c.get("feature_id") == "preservation-src"]
            self.assertEqual(1, len(rows), report["checks"])
            self.assertNotIn("SOURCE_MISSING", json.dumps(rows[0]))
            self.assertTrue(rows[0]["ran"], rows[0])


# ---------------------------------------------------------------------------
# The false pass
# ---------------------------------------------------------------------------

class AReviewBoundToOneBranchTest(unittest.TestCase):
    """Path isolation is necessary and provably not sufficient."""

    ENVELOPE = dict(kind="safety", job_id="branching", revision=UTC,
                    packet_hash="p" * 64, reviewer={"model_snapshot": "test"},
                    contract_hash="c" * 64,
                    artifact_hashes={"stl": "s" * 64, "source": "m" * 64},
                    execution_plan_sha256="e" * 64)

    def _pass(self, envelope: R.ReviewEnvelope) -> dict:
        return {"decision": "PASS", "failure_modes": [], "safety_concerns": [],
                "missing_evidence": [], "required_actions": [],
                "summary": "nothing undeclared visible",
                "review_envelope": envelope.as_dict()}

    def test_a_pass_written_for_one_sibling_cannot_bind_the_other(self) -> None:
        """The false pass, asserted directly rather than through a verdict.

        At the instant a branch is created its sibling is a copy: the contract,
        the artifacts, the witnesses and the reviewer are the same objects, and
        `revision` is `updated_utc` -- a timestamp, not a graph node. Every field
        below is deliberately identical, so this test is the whole of the
        difference.
        """
        screw = R.build_envelope(**self.ENVELOPE, alternative_id="screw-fastened")
        snap = R.build_envelope(**self.ENVELOPE, alternative_id="snap-fit")

        self.assertEqual(
            {k: v for k, v in screw.as_dict().items() if k != "alternative_id"},
            {k: v for k, v in snap.as_dict().items() if k != "alternative_id"},
            "everything a reviewer is shown is equal between two fresh siblings")

        answer = self._pass(screw)
        self.assertFalse(R.is_bound(answer, "safety", snap.digest()))
        with self.assertRaises(R.ReviewError):
            R.validate_response_envelope(answer, snap)

    def test_without_the_field_the_same_pass_binds_both(self) -> None:
        """The mutation: remove the protection and the false pass is reachable.

        A test that only shows the current code refusing proves the refusal
        happens, not that anything is holding it up. This one shows what is.
        """
        neither = R.build_envelope(**self.ENVELOPE)
        answer = self._pass(neither)
        self.assertTrue(R.is_bound(answer, "safety", neither.digest()),
                        "with no alternative on either envelope the two siblings "
                        "are one review, and the first PASS answers the second")

    def test_the_plan_alone_cannot_tell_two_formulations_apart(self) -> None:
        """Which is why the envelope binds the id and not only the plan digest.

        `ExecutionPlan.as_payload` carries no parameters and deliberately omits
        `candidates`, so two authored formulations of one job -- different
        numbers, different geometry, different acceptance contracts -- compile to
        the same plan.
        """
        rows = (P.Alternative(alternative_id="screw-fastened", reason="serviceable"),
                P.Alternative(alternative_id="snap-fit", reason="no fasteners"))
        project = _project(alternatives=rows)
        project.active_alternative = "screw-fastened"
        first = EX.compile_plan(project)
        project.active_alternative = "snap-fit"
        second = EX.compile_plan(project)
        self.assertEqual(
            {k: v for k, v in first.as_payload().items() if k != "alternative_id"},
            {k: v for k, v in second.as_payload().items() if k != "alternative_id"})
        self.assertNotEqual(first.plan_hash(), second.plan_hash())

    def test_a_sibling_refuses_the_answer_written_next_door(self) -> None:
        """End to end: the answer is moved across, and the run does not take it."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), _project(
                consequence="CONSEQUENTIAL",
                consequence_rationale="it carries a load over a walkway"))
            # Deliberately identical formulations. A branch that differed would be
            # refused on the contract hash alone, which proves nothing about the
            # instant that matters -- the one where the sibling is still a copy.
            for name in ("screw-fastened", "snap-fit"):
                _branch(directory, parent=".", name=name, reason=f"the {name} concept")
                _author(_alt(directory, name), "same-shape", **SCREW)
                self.assertEqual(cli.NEEDS_ACTION,
                                 cli.run([str(directory), "--no-render"]))
                cli.branch([str(directory), "--activate", "."])

            screw, snap = (_alt(directory, "screw-fastened"),
                           _alt(directory, "snap-fit"))
            packet = _read(screw / cli.REVIEW_DIR / "safety_packet.json")
            answer = self._pass(
                R._envelope_from_dict(packet["review_envelope"]))

            # The one sibling's own answer finishes its own run.
            (screw / cli.REVIEW_DIR / "safety_response.json").write_text(
                S.canonical_json(answer), encoding="utf-8")
            cli.branch([str(directory), "--activate", "screw-fastened"])
            cli.run([str(directory), "--no-render"])
            self.assertEqual("PASS",
                             _read(screw / "safety_verification_report.json")["decision"])

            # Copied next door, it is refused -- and the neighbour writes no
            # passing safety report and no final status.
            shutil.copyfile(screw / cli.REVIEW_DIR / "safety_response.json",
                            snap / cli.REVIEW_DIR / "safety_response.json")
            cli.branch([str(directory), "--activate", "snap-fit"])
            self.assertNotEqual(0, cli.run([str(directory), "--no-render"]))
            report = _read(snap / "safety_verification_report.json")
            self.assertNotEqual("PASS", report.get("decision"))
            self.assertIn("envelope", report["error"])
            self.assertFalse((snap / "final_status.json").exists())


# ---------------------------------------------------------------------------
# Reconstruction
# ---------------------------------------------------------------------------

class CleanCloneTest(unittest.TestCase):
    """Nothing about the fork lives outside the project directory."""

    def test_a_clean_copy_reconstructs_the_graph_and_every_branch_s_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            directory = _laid_out(root)
            _branch(directory, parent=".", name="base", reason="the shared start")
            _author(_alt(directory, "base"), "base", **SCREW)
            cli.run([str(directory), "--no-render"])
            for name, params in (("screw-fastened", SCREW), ("snap-fit", SNAP)):
                _branch(directory, parent="base", name=name, reason=f"the {name} concept")
                _author(_alt(directory, name), name, **params)
                cli.run([str(directory), "--no-render"])
                cli.branch([str(directory), "--activate", "base"])

            clone = root / "clone"
            shutil.copytree(directory, clone)

            original, copied = P.load(directory), P.load(clone)
            self.assertEqual(original.as_payload(), copied.as_payload())
            self.assertEqual(
                [("base", ()), ("screw-fastened", ("base",)), ("snap-fit", ("base",))],
                [(a.alternative_id, a.parents) for a in copied.alternatives])
            self.assertEqual([], copied.validate(clone, require_buildable=False))
            self.assertEqual(_digests(directory), _digests(clone))

            # And the clone reports the same fork through the command surface.
            self.assertEqual(cli.NEEDS_ACTION, cli.status([str(clone), "--json"]))


if __name__ == "__main__":
    unittest.main()
