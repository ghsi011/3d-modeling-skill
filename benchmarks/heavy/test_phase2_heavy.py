#!/usr/bin/env python3
"""L0-heavy — the half of
`skills/3d-modeling/scripts/pipeline/test_phase2.py`
that costs a child interpreter.

The repository-root `conftest.py` refuses a child interpreter inside the commit
gate, and these classes start one. Same tests, moved rather than weakened;
`benchmarks/heavy/README.md` records the profile that decided the seam and what
runs this tier. What stayed behind is what answers in the parent process.
"""
from __future__ import annotations

import ast
import json
import tempfile
import textwrap
import unittest
from pathlib import Path
from pipeline import acceptance as ACC
from pipeline import bindings as B
from pipeline import cli
from pipeline import project as P
from pipeline import route as RT
from pipeline import runner
from pipeline import schemas as S
from pipeline import selftest as ST

# `__file__` is under benchmarks/heavy now; what the moved code reaches through
# it is not. Named from the repository root rather than by a different count of
# `.parent`, because a count is what breaks silently on the next move.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO_ROOT / "skills" / "3d-modeling" / "scripts"
_PACKAGE = _SCRIPTS / "pipeline"

# The fixtures this half shares with the half that stayed behind,
# imported rather than copied: two spellings of one fixture is how
# two tiers stop testing the same thing.
from pipeline.test_phase2 import (  # noqa: E402
    MUSHROOM,
    MUSHROOM_PROPOSAL,
    RISER,
    RISER_PROPOSAL,
    RISER_SMALL_PAD,
    WASHER,
    WASHER_PROPOSAL,
    _laid_out,
    _project,
    _propose,
    _read,
)


class AcceptanceIsUpstreamTest(unittest.TestCase):
    """The ordering, asserted over the code rather than over one run.

    ADR 0002's gate for this stage is not "does a check fire". It is "is there
    any ordering of operations in which the built artifact can influence its own
    acceptance criteria". These are the facts about the *code* that answer it.

    Ordering is not the whole answer and these are not the whole proof. An
    import is an execution, so freezing first bought nothing while the candidate
    was imported into this interpreter; `test_isolation.py` is where that half
    lives, and the first test below is this walker's own fixture because these
    guards were passing on the absolute imports alone.
    """

    def _imports(self, relative: str) -> set[str]:
        """Every name one module imports, `from . import x` included.

        The `and node.module` this used to carry made the guard blind to the
        dominant idiom in this package: `from . import analysis` parses as an
        `ImportFrom` with `module=None`, so the branch never ran and *nothing*
        was recorded -- not the module, not the alias. Every sibling import in
        the forbidden lists below was therefore invisible to the check that
        forbade it, and the two tests were passing on the absolute imports alone.
        `test_the_walker_sees_a_relative_import` is this walker's own fixture.
        """
        root = _PACKAGE
        tree = ast.parse((root / relative).read_text(encoding="utf-8"))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module:
                    names.add(node.module)
                names |= {alias.name for alias in node.names}
            elif isinstance(node, ast.Import):
                names |= {alias.name for alias in node.names}
        return names

    def test_the_walker_sees_a_relative_import(self) -> None:
        """A guard that cannot see the import it forbids is a comment."""
        names = self._imports("runner.py")
        for expected in ("analysis", "commission", "screening", "status"):
            self.assertIn(expected, names,
                          f"runner.py imports {expected} with `from . import` and "
                          "this walker cannot see it, so neither can the two tests "
                          "below")

    def test_the_contract_generator_cannot_see_a_mesh(self) -> None:
        names = self._imports("acceptance.py")
        for forbidden in ("analysis", "commission", "screening", "backends",
                          "trimesh", "build123d", "numpy", "runner"):
            self.assertNotIn(forbidden, names,
                             f"acceptance.py imports {forbidden}, so a measurement "
                             "could reach the criteria it is measured against")

    def test_the_generator_takes_no_parameter_a_build_could_arrive_through(self) -> None:
        import inspect

        taken = set(inspect.signature(ACC.generate).parameters)
        for forbidden in ("ctx", "mesh", "artifact", "built", "commission",
                          "report", "measured"):
            self.assertNotIn(forbidden, taken)

    def test_the_module_that_runs_the_builder_cannot_freeze_a_contract(self) -> None:
        """By import graph and by call, not by grep over the prose.

        `runner.py`'s docstrings name the acceptance contract while explaining
        that the runner is not a source of one, so a substring rule would fail on
        the comment that documents the rule.

        "Runs the builder" is now weaker than it was: the runner invokes a
        backend that adopts geometry a child process already produced, and it
        executes no candidate code at all. What it must still not be able to do
        is write the document the geometry is judged against.
        """
        self.assertNotIn("acceptance", self._imports("runner.py"),
                         "runner.py imports the freezer, which is one line away "
                         "from calling it after the build")
        tree = ast.parse((_PACKAGE / "runner.py")
                         .read_text(encoding="utf-8"))
        called = {node.func.attr for node in ast.walk(tree)
                  if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Attribute)}
        self.assertNotIn("freeze", called)

    def test_the_contract_is_on_disk_before_the_model_is_imported(self) -> None:
        """Two facts, observed at the instant the candidate is launched.

        This used to be proved by a model that wrote a marker into the project
        directory carrying the contract it had just read there. The confined
        build boundary makes both halves of that impossible -- the candidate
        cannot write the project directory, and it is not told where it is -- so
        the witness moved to the only party that can still see both sides.

        What is asserted is the same claim and slightly more of it: at the moment
        `isolation.build` is entered, the contract is already on disk *and*
        already hashes to the digest every receipt binds; and the directory the
        candidate is handed contains its own sources and nothing else.
        """
        observed: dict[str, object] = {}
        real = cli.ISO.build

        def watch(model_path, *, dest_dir, step, **kw):
            path = Path(dest_dir) / ACC.ACCEPTANCE_FILE
            observed["present"] = path.is_file()
            observed["payload"] = (json.loads(path.read_text(encoding="utf-8"))
                                   if path.is_file() else None)
            return real(model_path, dest_dir=dest_dir, step=step, **kw)

        self.addCleanup(setattr, cli.ISO, "build", real)
        cli.ISO.build = watch

        witness = textwrap.dedent(RISER) + textwrap.dedent('''
            from pathlib import Path
            PROVENANCE = {"visible_to_the_candidate":
                          sorted(p.name for p in Path(__file__).parent.iterdir())}
            ''')
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), witness, _project())
            cli.run([str(directory), "--no-render"])
            # Out of `candidate_declaration.json` and not out of the contract:
            # `source` no longer carries `provenance` at all, because the
            # contract is handed verbatim to the reviewers who decide the run
            # (D10). This probe still reports through `PROVENANCE` -- that is the
            # only channel a model has -- and the parent still records it. It
            # simply does not forward it.
            visible = _read(directory, cli.ISO.DECLARATION_FILE)["provenance"]

        self.assertTrue(observed["present"],
                        "the candidate was launched before the acceptance contract "
                        "reached disk, so the freeze is not upstream of the build")
        payload = observed["payload"]
        body = {key: value for key, value in payload.items()
                if key != "contract_sha256"}
        self.assertEqual(payload["contract_sha256"], S.payload_hash(body),
                         "the contract on disk when the candidate started is not "
                         "the one that hashes to the digest the receipts bind")

        self.assertNotIn(ACC.ACCEPTANCE_FILE, visible["visible_to_the_candidate"],
                         "the candidate could see the document it is measured "
                         "against in the directory it was handed")

class CandidateCannotWidenItsOwnToleranceTest(unittest.TestCase):
    """The demonstrated defect, closed from both directions.

    A model declaring a 24x18 pad, building a 10x8 one, with a self-declared
    `{"abs": 500.0}` band on that row, was commissioned `PASS` on a 352 mm2 miss.
    Two things had to be true for that: the band could be authored by the party
    being measured, and the declaration could be restated after the result.
    """

    def test_a_352_mm2_miss_is_caught_by_the_system_owned_band(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER_SMALL_PAD, _project())
            code = cli.run([str(directory), "--no-render"])

            contract = _read(directory, ACC.ACCEPTANCE_FILE)
            row = next(f for f in contract["features"]
                       if f["feature_id"] == "pad-section")
            self.assertEqual("pipeline", contract["tolerance_owner"])
            self.assertAlmostEqual(2.16, row["tolerance"]["abs"], places=6,
                                   msg="0.5% of 432 mm2, and nothing the designer "
                                       "wrote could have moved it")

            report = _read(directory, "commission_report.json")
            check = next(c for c in report["checks"]
                         if c["check_id"] == "feature-pad-section")
            self.assertEqual("FAIL", check["result"])
            self.assertAlmostEqual(432.0, float(check["expected"]))
            self.assertLess(float(check["measured"]), 100.0)
            self.assertGreater(float(check["expected"]) - float(check["measured"]),
                               350.0, "the 352 mm2 miss, measured")
            self.assertEqual("FAIL", report["verdict"])
            self.assertEqual("FAILED", _read(directory, "final_status.json")
                             ["final_status"])
            self.assertEqual(1, code)

    def test_the_band_it_used_to_widen_cannot_be_written_at_all(self) -> None:
        rows = [dict(row) for row in RISER_PROPOSAL["features"]]
        rows[1]["tolerance"] = {"abs": 500.0}
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER_SMALL_PAD, _project(),
                                  {**RISER_PROPOSAL, "features": rows})
            self.assertEqual(2, cli.run([str(directory), "--no-render"]))
            self.assertFalse((directory / ACC.ACCEPTANCE_FILE).is_file(),
                             "a proposal that names its own band must not reach a "
                             "frozen contract at all")
            action = _read(directory, cli.NEXT_ACTION_FILE)
            self.assertTrue(any("500" in problem for problem in action["unresolved"]),
                            action["unresolved"])

    def test_restating_the_expectation_after_the_result_is_a_visible_revision(self) -> None:
        """The other half: the number can still move, and it cannot move quietly.

        A designer who has read the failure and decided the pad really is 10x8
        may say so. What they cannot do is have the receipt that was issued
        against 24x18 survive them saying it.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER_SMALL_PAD, _project())
            cli.run([str(directory), "--no-render"])
            first = _read(directory, ACC.ACCEPTANCE_FILE)
            self.assertEqual(1, first["revision"])

            widened = [dict(row) for row in RISER_PROPOSAL["features"]]
            widened[1]["value_mm2"] = 10.0 * 8.0
            _propose(directory, {**RISER_PROPOSAL, "features": widened})
            cli.run([str(directory), "--no-render"])

            second = _read(directory, ACC.ACCEPTANCE_FILE)
            self.assertEqual(2, second["revision"])
            self.assertNotEqual(first["contract_sha256"], second["contract_sha256"])

            history = _read(directory, ACC.HISTORY_FILE)
            self.assertEqual([1, 2], [r["revision"] for r in history["revisions"]])
            entry = history["revisions"][1]
            self.assertTrue(any("432" in line and "80" in line
                                for line in entry["changed"]), entry["changed"])
            self.assertEqual(first["contract_sha256"],
                             entry["supersedes"]["contract_sha256"])
            self.assertIn("commission_report.json",
                          entry["supersedes"]["invalidated_receipts"])

    def test_a_proposal_copied_from_another_job_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER, _project(),
                                  {**RISER_PROPOSAL, "job_id": "some-other-job"})
            self.assertEqual(2, cli.run([str(directory), "--no-render"]))
            action = _read(directory, cli.NEXT_ACTION_FILE)
            self.assertTrue(any("some-other-job" in problem
                                for problem in action["unresolved"]), action)
            self.assertFalse((directory / ACC.ACCEPTANCE_FILE).is_file(),
                             "a proposal for another job cut a revision on its way "
                             "to being refused")

    def test_the_model_and_the_proposal_must_agree_about_the_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER, _project(), {
                **RISER_PROPOSAL,
                "params": {**RISER_PROPOSAL["params"], "pad_w": 10.0}})
            self.assertEqual(2, cli.run([str(directory), "--no-render"]))
            action = _read(directory, cli.NEXT_ACTION_FILE)
            self.assertTrue(any("pad_w" in problem
                                for problem in action["unresolved"]), action)

class RevisionTest(unittest.TestCase):
    def test_an_unchanged_proposal_leaves_the_contract_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER, _project())
            cli.run([str(directory), "--no-render"])
            before = (directory / ACC.ACCEPTANCE_FILE).read_bytes()
            cli.run([str(directory), "--no-render"])
            self.assertEqual(before, (directory / ACC.ACCEPTANCE_FILE).read_bytes())
            self.assertEqual(
                1, len(_read(directory, ACC.HISTORY_FILE)["revisions"]),
                "a rerun that changed nothing cut a revision, which makes every "
                "revision that does mean something unreadable")

    def test_reformatting_the_proposal_is_not_a_revision(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER, _project())
            cli.run([str(directory), "--no-render"])
            (directory / ACC.PROPOSAL_FILE).write_text(
                json.dumps(RISER_PROPOSAL), encoding="utf-8")
            cli.run([str(directory), "--no-render"])
            self.assertEqual(1, _read(directory, ACC.ACCEPTANCE_FILE)["revision"])

    def test_a_changed_user_requirement_cuts_a_revision_too(self) -> None:
        """Not only the proposal. The contract binds what the user asked for, and
        a contract that survived a change to that would gate a part against a job
        that no longer exists."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER, _project())
            cli.run([str(directory), "--no-render"])
            (directory / "brief.md").write_text("a taller riser block",
                                                encoding="utf-8")
            cli.run([str(directory), "--no-render"])
            self.assertEqual(2, _read(directory, ACC.ACCEPTANCE_FILE)["revision"])
            entry = _read(directory, ACC.HISTORY_FILE)["revisions"][1]
            self.assertTrue(any("requirement_sha256" in line
                                for line in entry["changed"]), entry["changed"])

    def test_a_new_revision_invalidates_an_independent_verification(self) -> None:
        """Not by deleting the answer -- by making it stop matching.

        The verifier's answer echoes a review envelope that binds the model
        contract's hash, and the model contract carries the acceptance contract's.
        A revision therefore unbinds every answer written against the old one
        without anybody having to remember to go and remove it.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER,
                                  _project(verification_requested=True,
                                           reviewer={"model_snapshot": "test"}))
            self.assertEqual(cli.NEEDS_ACTION, cli.run([str(directory), "--no-render"]))
            packet = _read(directory, "reviews/verification_packet.json")
            (directory / "reviews" / "verification_response.json").write_text(
                json.dumps({"decision": "PASS", "defects": [],
                            "unmet_requirements": [], "missing_evidence": [],
                            "summary": "nothing undeclared visible",
                            "review_envelope": packet["review_envelope"]}),
                encoding="utf-8")
            self.assertEqual(0, cli.run([str(directory), "--no-render"]))
            self.assertEqual("VERIFIED",
                             _read(directory, "final_status.json")["final_status"])

            moved = [dict(row) for row in RISER_PROPOSAL["features"]]
            moved[1]["value_mm2"] = 24.0 * 18.0 - 4.0
            _propose(directory, {**RISER_PROPOSAL, "features": moved})
            self.assertNotEqual(0, cli.run([str(directory), "--no-render"]))
            self.assertNotEqual(
                "VERIFIED",
                (_read(directory, "final_status.json")["final_status"]
                 if (directory / "final_status.json").is_file() else None),
                "an answer written against revision 1 survived into revision 2")

    def test_a_new_revision_removes_the_receipts_it_invalidates(self) -> None:
        """The run that cuts a revision may then fail before it writes anything.

        Driven through a model that raises on import, so the second run stops at
        the build with no fresh receipts of its own. What must not be sitting
        there afterwards is the previous revision's success -- a reader, and
        `design-tool status`, would take it for this one's.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER, _project())
            cli.run([str(directory), "--no-render"])
            for name in ("artifact_manifest.json", "commission_report.json",
                         "final_status.json"):
                self.assertTrue((directory / name).is_file(), name)

            moved = [dict(row) for row in RISER_PROPOSAL["features"]]
            moved[1]["value_mm2"] = 10.0 * 8.0
            _propose(directory, {**RISER_PROPOSAL, "features": moved})
            (directory / "model.py").write_text(
                textwrap.dedent(RISER) + "\nraise RuntimeError('mid-edit')\n",
                encoding="utf-8")
            self.assertEqual(2, cli.run([str(directory), "--no-render"]))

            self.assertEqual(2, _read(directory, ACC.ACCEPTANCE_FILE)["revision"])
            # `bindings.REMOVABLE`, not a tuple restated in `acceptance.py`: what
            # a revision invalidates is derived from what each receipt records
            # about the contract it was issued against, and the set it reaches
            # here is the same six files the hardcoded tuple used to name.
            for name in B.REMOVABLE:
                self.assertFalse((directory / name).is_file(),
                                 f"{name} was issued against revision 1 and is "
                                 "still on disk under revision 2")
            removed = _read(directory, ACC.HISTORY_FILE)["revisions"][1][
                "supersedes"]["invalidated_receipts"]
            self.assertIn("final_status.json", removed)
            self.assertIn("commission_report.json", removed)

class CustomLaneTest(unittest.TestCase):
    def test_a_custom_part_reaches_the_same_receipts_as_a_certified_one(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER, _project())
            code = cli.run([str(directory), "--no-render"])

            report = _read(directory, "commission_report.json")
            self.assertEqual("PASS", report["verdict"], report["checks"])
            final = _read(directory, "final_status.json")
            self.assertEqual("CUSTOM", final["route"])
            self.assertEqual("PASS", final["commission_verdict"])
            self.assertEqual("AVAILABLE", final["lane_status"],
                             "the CUSTOM cap named acceptance criteria read out of "
                             "the model file; there are none left to read")
            for name in ST.FROZEN_ARTIFACTS["CUSTOM"]:
                self.assertTrue((directory / f"{name}.json").is_file(), name)
            # Same frozen reason DIRECT stops here: the broad screen is
            # uncalibrated and this job did not require an independent look.
            self.assertEqual(cli.NEEDS_ACTION, code)
            self.assertEqual("NEEDS_MORE_EVIDENCE", final["final_status"])

    def test_every_receipt_binds_the_frozen_contract(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER, _project())
            cli.run([str(directory), "--no-render"])
            frozen = _read(directory, ACC.ACCEPTANCE_FILE)
            contract = _read(directory, "model_contract.json")
            self.assertEqual(frozen["contract_sha256"],
                             contract["source"]["acceptance_contract_sha256"])
            self.assertEqual(frozen["proposal_sha256"],
                             contract["source"]["proposal_sha256"])
            self.assertEqual(1, contract["source"]["acceptance_revision"])
            self.assertEqual("two-tier-riser", contract["template"])
            self.assertEqual("authored-r1", contract["template_version"],
                             "the revision is on the receipt's face, not only in "
                             "the hash")
            self.assertEqual(_read(directory, "artifact_manifest.json")
                             ["contract_sha256"],
                             _read(directory, "commission_report.json")
                             ["contract_hash"])

    def test_an_unrelated_custom_part_on_the_other_kernel_works_too(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), WASHER, _project(
                job_id="washer", envelope_mm={"x": 30.0, "y": 30.0, "z": 4.0},
                consequence_rationale="a spacer washer under a desk foot"),
                WASHER_PROPOSAL)
            cli.run([str(directory), "--no-render"])
            report = _read(directory, "commission_report.json")
            self.assertEqual("PASS", report["verdict"], report["checks"])
            artifact = _read(directory, "artifact_manifest.json")
            self.assertEqual("authored", artifact["backend"])
            self.assertIn("build123d", artifact["backend_version"])
            self.assertEqual("n/a (B-rep)", artifact["boolean_engine"])

    def test_the_contract_binds_the_module_that_was_built(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER, _project())
            cli.run([str(directory), "--no-render"])
            first = _read(directory, "model_contract.json")
            self.assertEqual("authored", first["source"]["kind"])
            self.assertEqual("model.py", first["source"]["module"])

            (directory / "model.py").write_text(
                textwrap.dedent(RISER) + "\n# a comment the designer added\n",
                encoding="utf-8")
            cli.run([str(directory), "--no-render"])
            second = _read(directory, "model_contract.json")
            self.assertNotEqual(first["source"]["module_sha256"],
                                second["source"]["module_sha256"])
            self.assertEqual(1, _read(directory, ACC.ACCEPTANCE_FILE)["revision"],
                             "editing the model must not move the contract it is "
                             "judged against; iterating against a fixed expectation "
                             "is the whole point")

    def test_a_mesh_model_does_not_claim_an_engine_nobody_observed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER, _project())
            cli.run([str(directory), "--no-render"])
            self.assertIn("unrecorded", _read(directory, "artifact_manifest.json")
                          ["boolean_engine"])

class ScreeningPolicyTest(unittest.TestCase):
    """A screen calibrated by its own subject is not a screen."""

    def test_neither_calibrated_detector_clears_an_authored_part(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER, _project())
            cli.run([str(directory), "--no-render"])
            screen = _read(directory, "commission_report.json")["screening"]
            self.assertEqual("SELF_DECLARED", screen["expectation_source"])
            by_name = {d["detector"]: d for d in screen["detectors"]}
            self.assertEqual("NOT_APPLICABLE", by_name["volume"]["result"])
            self.assertEqual("NOT_INDEPENDENTLY_SPECIFIED",
                             by_name["volume"]["calibration"])
            self.assertIsNotNone(by_name["volume"]["measured_mm3"],
                                 "the measurement may still appear on the receipt")
            self.assertIsNone(by_name["volume"]["expected_mm3"])
            self.assertEqual("NOT_APPLICABLE", by_name["profile-z"]["result"])

    def test_an_undeclared_step_is_still_an_anomaly(self) -> None:
        """Removing the invalid clearance does not remove the finding.

        A step the designer's own declarations fail to explain is evidence
        against the part whoever wrote the declarations.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER, _project(),
                                  {**RISER_PROPOSAL, "profile_marks": {"z": []}})
            cli.run([str(directory), "--no-render"])
            report = _read(directory, "commission_report.json")
            self.assertEqual("ANOMALY", report["screening"]["overall"])

    def _with_volume(self, directory: Path, volume: float):
        """The same job's contract, with an independently specified volume on it."""
        frozen = ACC.Frozen(
            path=directory / ACC.ACCEPTANCE_FILE,
            payload={**_read(directory, ACC.ACCEPTANCE_FILE),
                     "expected_volume_mm3": volume,
                     "expected_volume_basis": "ANALYTIC_FROM_FROZEN_PROPOSAL"},
            revision=1, contract_sha256="", disposition="UNCHANGED")
        source = ACC.AcceptanceSource(frozen=frozen, module="model.py",
                                      module_sha256="")
        fields = P.to_job_request_fields(_project())
        fields["template"] = None
        return runner._contract_from(source, runner.JobRequest(
            brief_path=directory / "brief.md", out_dir=directory, render=False,
            acceptance=source, **fields))

    def test_an_independently_specified_volume_does_drive_the_screen(self) -> None:
        """The policy is about where the number came from, not about the lane.

        Nothing in this build has an independent expected volume for novel
        authored geometry, so `NOT_INDEPENDENTLY_SPECIFIED` is what a `CUSTOM`
        run records. The detector is still wired to honour one, because otherwise
        `expected_volume_basis` would be a field nothing reads and the first
        legitimate source to arrive -- a bounded source delta, a previously
        approved revision -- would need the screen rebuilt as well as the
        contract.
        """
        from pipeline import analysis, screening

        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER, _project())
            cli.run([str(directory), "--no-render"])
            ctx = analysis.load(directory / "candidate.stl")
            truth = 40.0 * 30.0 * 6.0 + 24.0 * 18.0 * 8.0
            for volume, result in ((truth, "CLEAR"), (truth * 1.2, "ANOMALY")):
                with self.subTest(result=result):
                    screen = screening.run(ctx, self._with_volume(directory, volume))
                    self.assertEqual(result, {d["detector"]: d["result"]
                                              for d in screen["detectors"]}["volume"])

    def test_a_certified_part_still_gets_a_second_party_screen(self) -> None:
        """The policy is per owner, not a blanket downgrade: `templates.py` is
        written by somebody who is not the designer, so DIRECT keeps its screen."""
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            (out / "brief.md").write_text("a clip", encoding="utf-8")
            result = runner.run(ST._request(out, "c_clip"))
            screen = result.final_status and json.loads(
                (out / "commission_report.json").read_text(encoding="utf-8"))["screening"]
            self.assertEqual("SECOND_PARTY", screen["expectation_source"])
            by_name = {d["detector"]: d for d in screen["detectors"]}
            self.assertEqual("CLEAR", by_name["volume"]["result"])
            self.assertEqual("CLEAR", by_name["profile-z"]["result"])

class PrintPlanTest(unittest.TestCase):
    def test_one_commission_asks_for_the_proposal_and_the_model_together(self) -> None:
        """One dispatch, not two. Freezing is a pipeline step."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), None, _project(), None)
            code = cli.run([str(directory), "--no-render"])
            self.assertEqual(cli.NEEDS_ACTION, code)
            self.assertFalse((directory / "model.py").is_file())
            plan = _read(directory, cli.PLAN_FILE)
            self.assertEqual("builtin-direct-template", plan["owner"])

            action = _read(directory, cli.NEXT_ACTION_FILE)
            self.assertEqual("designer", action["role"])
            self.assertEqual("AGENT_COMMISSION", action["kind"])
            self.assertEqual([ACC.PROPOSAL_FILE, "model.py"],
                             action["required_outputs"])
            self.assertIn(cli.PLAN_FILE, action["authorized_inputs"])
            self.assertIn("features", action["proposal_api"])
            self.assertIn("PARAMS", action["source_api"])
            self.assertTrue(action["bound"]["print_plan_sha256"])

    def test_the_support_ceiling_is_a_frozen_contract_feature_and_it_bites(self) -> None:
        """The rule four archived runs set after reading their own measurement.

        The mushroom is a 40x30 cap on an 8 mm post: most of the cap's underside
        faces the bed with nothing beneath it. Every declared expectation passes
        -- the sections and the footprint are exactly the closed form -- so this
        is the plan catching what the proposal's own arithmetic cannot.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), MUSHROOM, _project(job_id="mushroom"),
                                  MUSHROOM_PROPOSAL)
            code = cli.run([str(directory), "--no-render"])
            frozen = _read(directory, ACC.ACCEPTANCE_FILE)
            self.assertTrue([f for f in frozen["features"]
                             if f["kind"] == "overhang"],
                            "the print plan's rule must be inside the frozen "
                            "contract, under the same revision discipline as "
                            "everything else the part is gated against")
            report = _read(directory, "commission_report.json")
            overhang = [c for c in report["checks"]
                        if c["check_id"].startswith("feature-plan-support")]
            self.assertTrue(overhang, "the plan's support rule reached no check")
            self.assertEqual("FAIL", overhang[0]["result"], overhang)
            self.assertGreater(overhang[0]["measured"], 900.0)
            self.assertEqual("FAIL", report["verdict"])
            self.assertEqual(1, code)

    def test_a_custom_job_without_an_envelope_is_refused_not_guessed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER, _project(envelope_mm=None))
            self.assertEqual(2, cli.run([str(directory), "--no-render"]))
            action = _read(directory, cli.NEXT_ACTION_FILE)
            self.assertTrue(any("envelope_mm" in p for p in action["unresolved"]))

class ReviewPolicyTest(unittest.TestCase):
    def test_an_uncomplicated_custom_job_dispatches_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER, _project())
            cli.run([str(directory), "--no-render"])
            self.assertFalse((directory / "reviews").exists(),
                             "a verifier the route did not ask for is not a free "
                             "extra look; it is an escalation nobody decided on")

    def test_a_consequential_custom_job_asks_for_safety_and_verification(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER, _project(
                consequence="CONSEQUENTIAL",
                consequence_rationale="carries a monitor arm over a desk",
                reviewer={"model_snapshot": "test"}))
            project = P.load(directory)
            decision = RT.decide(project)
            RT.apply(project, decision)
            self.assertEqual(("safety", "verification"), project.required_reviews)

            self.assertEqual(cli.NEEDS_ACTION, cli.run([str(directory), "--no-render"]))
            action = _read(directory, cli.NEXT_ACTION_FILE)
            self.assertEqual("safety", action["review_kind"])
