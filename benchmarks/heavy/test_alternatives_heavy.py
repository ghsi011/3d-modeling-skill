#!/usr/bin/env python3
"""L0-heavy — the half of
`skills/3d-modeling/scripts/pipeline/test_alternatives.py`
that costs a child interpreter.

The repository-root `conftest.py` refuses a child interpreter inside the commit
gate, and these classes start one. Same tests, moved rather than weakened;
`benchmarks/heavy/README.md` records the profile that decided the seam and what
runs this tier. What stayed behind is what answers in the parent process.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path
from pipeline import acceptance as ACC
from pipeline import artifact_names as N
from pipeline import cli
from pipeline import execution as EX
from pipeline import project as P
from pipeline import review as R
from pipeline import schemas as S
from pipeline import selftest as ST

# The fixtures this half shares with the half that stayed behind,
# imported rather than copied: two spellings of one fixture is how
# two tiers stop testing the same thing.
from pipeline.test_alternatives import (  # noqa: E402
    MODEL,
    SCREW,
    SNAP,
    UTC,
    _alt,
    _author,
    _branch,
    _digests,
    _laid_out,
    _project,
    _read,
)


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
            self.assertTrue((directory / N.EXECUTION_PLAN).is_file())

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
            for name in ("candidate_declaration.json", "pipeline_artifact_receipt.json",
                         "commission_report.json", "final_status.json",
                         ACC.ACCEPTANCE_FILE, ACC.HISTORY_FILE,
                         N.EXECUTION_PLAN, cli.ROUTE_DECISION_FILE,
                         cli.PRINT_PLAN_CHECKS_FILE):
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

    def test_status_reports_every_formulation_and_the_active_ones_bindings(self) -> None:
        """The set is the union: the shared root and every declared alternative.

        This asserted `{"screw-fastened", "snap-fit"}` until `docs/defects.md`
        D26 -- which is the defect written down as the expectation, so it had to
        move, and it is moved deliberately rather than relaxed. The root is a
        formulation: it has a directory, a proposal, a contract and its own
        receipts, and a caller taking its formulation set from this block was
        silently dropping one of the two designs on the recorded knob.

        `bindings` is unchanged and still scoped to whichever formulation is
        active, which is the other half of what this test is for.
        """
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
                        {cli.ROOT_ALTERNATIVE, "screw-fastened", "snap-fit"},
                        {row["alternative_id"] for row in report["alternatives"]},
                        "the union -- D26. The root has no declared row in "
                        "project.json and is a formulation nonetheless")
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
