#!/usr/bin/env python3
"""L0-heavy — the half of
`skills/3d-modeling/scripts/pipeline/test_bindings.py`
that costs a child interpreter.

The repository-root `conftest.py` refuses a child interpreter inside the commit
gate, and these classes start one. Same tests, moved rather than weakened;
`benchmarks/heavy/README.md` records the profile that decided the seam and what
runs this tier. What stayed behind is what answers in the parent process.
"""
from __future__ import annotations

import contextlib
import dataclasses
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from pipeline import acceptance as ACC
from pipeline import bindings as B
from pipeline import cli
from pipeline import project as P
from pipeline import schemas as S
from pipeline import selftest as ST
from pipeline import status as STATUS

# The fixtures this half shares with the half that stayed behind,
# imported rather than copied: two spellings of one fixture is how
# two tiers stop testing the same thing.
from pipeline.test_bindings import (  # noqa: E402
    BLOCK,
    EVIDENCE_FILE,
    OTHER,
    UTC,
    _answer,
    _author,
    _corrupt_the_evidence,
    _digests,
    _laid_out,
    _project,
    _read,
    _status,
    _verified,
)


class DerivedStatusTest(unittest.TestCase):
    """`design-tool status` reports what the evidence supports, not what was said."""

    def test_a_stored_verified_whose_evidence_no_longer_binds_derives_weaker(self) -> None:
        """The one that matters, asserted on the receipt rather than on a verdict.

        Nothing about the part changed: the same candidate, the same contract,
        the same commissioning measurements. What moved is a file the verifier
        was shown, which the review envelope binds and which the stored status
        rests on -- so the run's conclusion is still the record of what that run
        concluded, and it is no longer a claim anybody may repeat.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _verified(Path(raw))
            self.assertEqual("VERIFIED", _status(directory)["final_status"],
                             "an untouched job derives exactly what it stored")

            _corrupt_the_evidence(directory)
            report = _status(directory)
            self.assertEqual("STALE", report["final_status"])
            self.assertEqual("VERIFIED", report["stored_status"])
            self.assertIn("final_status.json", report["stale"])
            self.assertIn("pipeline_verification_report.json", report["stale"])
            self.assertTrue(
                any(EVIDENCE_FILE in row
                    for row in report["stale"]["pipeline_verification_report.json"]),
                report["stale"])

    def test_the_derived_status_never_outruns_the_stored_one(self) -> None:
        """It may take a claim away. There is no input here that can add one."""
        for stored, expected in (("VERIFIED", "STALE"), ("COMMISSIONED", "STALE"),
                                 ("FAILED", "FAILED"),
                                 ("NEEDS_MORE_EVIDENCE", "NEEDS_MORE_EVIDENCE"),
                                 ("EXPERIMENTAL_UNAVAILABLE",
                                  "EXPERIMENTAL_UNAVAILABLE")):
            with self.subTest(stored=stored):
                derived = STATUS.derive(
                    {"final_status": stored, "allowed_claim": "..."},
                    {"final_status.json": ("stl: issued against a, now b",)})
                self.assertEqual(expected, derived["derived_status"])
                self.assertEqual(stored, derived["stored_status"])

    def test_a_finding_is_not_replaced_by_a_bookkeeping_caveat(self) -> None:
        """`FAILED` stands and carries the breakage; it does not become STALE.

        The lane cap in `status.decide` makes the same choice for the same
        reason: a defect replaced by "this is out of date" is a defect nobody is
        looking at any more.
        """
        derived = STATUS.derive(
            {"final_status": "FAILED", "allowed_claim": "the geometry is wrong"},
            {"final_status.json": ("stl: issued against a, now b",)})
        self.assertEqual("FAILED", derived["derived_status"])
        self.assertTrue(any("stands" in reason for reason in derived["reasons"]),
                        derived["reasons"])

    def test_a_directory_with_no_concluded_run_says_so(self) -> None:
        self.assertEqual("NOT_RUN", STATUS.derive(None, {})["derived_status"])
        self.assertEqual("NOT_RUN", STATUS.derive({}, {})["derived_status"])

    def test_status_reports_a_broken_binding_without_deleting_the_receipt(self) -> None:
        """Reporting is not invalidating, and this command must never be both.

        A superseded receipt is neither current nor erased. `status` is a reader:
        a command that tidied away the evidence it was describing would leave a
        user unable to see what had been claimed, and would change the thing it
        was asked about on the way past.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _verified(Path(raw))
            _corrupt_the_evidence(directory)
            before = _digests(directory)

            self.assertEqual(cli.NEEDS_ACTION, cli.status([str(directory)]))
            self.assertTrue((directory / "pipeline_verification_report.json").is_file())
            self.assertTrue((directory / "final_status.json").is_file())
            self.assertEqual(before, _digests(directory),
                             "status wrote to the directory it was describing")

    def test_the_printed_summary_does_not_repeat_a_stale_claim_as_current(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _verified(Path(raw))
            _corrupt_the_evidence(directory)
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                cli.status([str(directory)])
            printed = captured.getvalue()
            self.assertIn("STALE", printed)
            self.assertIn("none is current", printed)
            self.assertIn("stale        pipeline_verification_report.json", printed)

    def test_without_the_envelope_s_evidence_digests_the_change_is_invisible(self) -> None:
        """The mutation: stop reading what the review bound and the claim survives.

        `pipeline_verification_report.json` records the digest of every file the reviewer
        was shown. Reading it is the whole of the protection above -- with that
        one reader neutered, a corrected caliper sheet moves nothing anybody
        checks and the stored VERIFIED reads as current.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _verified(Path(raw))
            _corrupt_the_evidence(directory)
            blind = tuple(
                dataclasses.replace(receipt, files=lambda payload: {})
                for receipt in B.RECEIPTS)
            with mock.patch.object(B, "RECEIPTS", blind):
                report = _status(directory)
            self.assertEqual("VERIFIED", report["final_status"])
            self.assertEqual({}, report["stale"])

class ScopedInvalidationTest(unittest.TestCase):
    """What is removed is what depended on the thing that changed, and no more."""

    def test_a_receipt_whose_bindings_still_hold_is_not_deleted(self) -> None:
        """The corrected caliper sheet takes the review and the status, and stops.

        `commission_report.json` and `pipeline_artifact_receipt.json` are measurements of
        a candidate that has not moved, against a contract that has not moved.
        They are still true, and the old rule deleted them anyway because they
        were in the tuple.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _verified(Path(raw))
            _corrupt_the_evidence(directory)

            removed = B.invalidate(directory, evidence_dir=directory,
                                   model_name="model.py")

            self.assertEqual({"pipeline_verification_report.json", "final_status.json"},
                             set(removed))
            for name in ("pipeline_artifact_receipt.json", "commission_report.json",
                         "model_contract.json"):
                with self.subTest(receipt=name):
                    self.assertTrue((directory / name).is_file(),
                                    f"{name} still binds what it was issued "
                                    "against and was deleted anyway")

    def test_the_blanket_rule_would_have_taken_all_six(self) -> None:
        """The mutation: restore "something changed, therefore everything is".

        This is the old behaviour exactly -- every removable receipt named stale
        on any invalidation event -- and it shows that the deletion path does
        reach the commissioning report. What keeps it is the scoping, not luck.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _verified(Path(raw))
            _corrupt_the_evidence(directory)
            blanket = {name: ("the hardcoded tuple named it",)
                       for name in B.REMOVABLE}
            with mock.patch.object(B, "broken", lambda *a, **k: blanket):
                removed = B.invalidate(directory, evidence_dir=directory)
            self.assertIn("commission_report.json", removed)
            self.assertFalse((directory / "commission_report.json").is_file())

    def test_the_run_removes_the_stale_receipts_before_it_can_leave_them(self) -> None:
        """A run that cannot finish must not leave the previous success behind.

        ADR 0002 section 4: a stale successful status is never displayed as
        current. The corrected evidence unbinds the stored answer, so the rerun
        refuses it -- and while nobody has answered the question again there is
        no `final_status.json` saying the job is verified.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _verified(Path(raw))
            _corrupt_the_evidence(directory)

            self.assertNotEqual(0, cli.run([str(directory), "--no-render"]))
            self.assertFalse((directory / "final_status.json").is_file())
            self.assertEqual("NOT_RUN", _status(directory)["final_status"])
            self.assertNotEqual(
                "PASS",
                _read(directory / "pipeline_verification_report.json").get("decision"),
                "the answer written against the old caliper sheet was promoted")
            self.assertTrue((directory / "commission_report.json").is_file(),
                            "the measurements of an unchanged candidate went "
                            "with the review that was shown a changed file")

    def test_a_rebuilt_candidate_takes_the_measurements_of_it_with_it(self) -> None:
        """The other direction, so the scoping is not just "delete less".

        `commission_report.json` records the contract it measured against and
        not the mesh it measured. It is stale here because it was issued beside
        `pipeline_artifact_receipt.json`, which does record it -- the edge is declared
        precisely where the receipt does not carry the digest itself.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _verified(Path(raw))
            stl = directory / "candidate.stl"
            stl.write_bytes(stl.read_bytes() + b"\n")

            stale = B.broken(directory, evidence_dir=directory)
            self.assertIn("pipeline_artifact_receipt.json", stale)
            self.assertIn("commission_report.json", stale)
            self.assertTrue(
                any("pipeline_artifact_receipt.json" in row
                    for row in stale["commission_report.json"]),
                stale["commission_report.json"])
            self.assertNotIn("model_contract.json", stale,
                             "the contract did not move because the mesh did")

    def test_the_contract_the_receipts_bind_is_never_removed(self) -> None:
        """`model_contract.json` is what the others are checked against.

        Deleting it would turn "issued against a contract that has moved" into
        "there is no contract here", which says less and is no more true.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _verified(Path(raw))
            contract = _read(directory / ACC.ACCEPTANCE_FILE)
            (directory / ACC.ACCEPTANCE_FILE).write_text(
                S.canonical_json({**contract, "contract_sha256": "0" * 64}),
                encoding="utf-8")

            stale = B.broken(directory, evidence_dir=directory)
            self.assertIn("model_contract.json", stale)
            B.invalidate(directory, evidence_dir=directory)
            self.assertTrue((directory / "model_contract.json").is_file())
            self.assertNotIn("model_contract.json", B.REMOVABLE)

    def test_an_acceptance_revision_still_reaches_every_receipt(self) -> None:
        """The set the tuple named, now for a reason instead of by name.

        Every receipt binds the model contract's hash and the model contract
        binds the acceptance contract's, so one broken edge takes the chain. The
        scoping did not make invalidation weaker where it was right.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _verified(Path(raw))
            contract = _read(directory / ACC.ACCEPTANCE_FILE)
            (directory / ACC.ACCEPTANCE_FILE).write_text(
                S.canonical_json({**contract, "contract_sha256": "0" * 64}),
                encoding="utf-8")

            stale = B.broken(directory, evidence_dir=directory)
            for name in B.REMOVABLE:
                if (directory / name).is_file():
                    with self.subTest(receipt=name):
                        self.assertIn(name, stale)

class SiblingScopeTest(unittest.TestCase):
    """An invalidation is scoped to one formulation's directory and its own files."""

    def _two(self, root: Path) -> Path:
        directory = _laid_out(root)
        for name, params in (("screw-fastened", BLOCK), ("snap-fit", OTHER)):
            cli.branch([str(directory), "--from", ".", "--id", name,
                        "--reason", f"the {name} concept"])
            where = directory / P.ALTERNATIVES_DIR / name
            _author(where, name, **params)
            self.assertEqual(cli.NEEDS_ACTION,
                             cli.run([str(directory), "--no-render"]))
            _answer(where)
            self.assertEqual(0, cli.run([str(directory), "--no-render"]))
            cli.branch([str(directory), "--activate", "."])
        return directory

    def test_one_alternative_s_invalidation_leaves_the_other_s_receipts_intact(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = self._two(Path(raw))
            untouched = _digests(directory / P.ALTERNATIVES_DIR / "screw-fastened")

            # A new revision of one formulation, which invalidates its own
            # receipts and must reach nothing in its sibling's directory.
            _author(directory / P.ALTERNATIVES_DIR / "snap-fit", "snap-fit",
                    w=34.0, d=24.0, h=14.0)
            cli.branch([str(directory), "--activate", "snap-fit"])
            cli.run([str(directory), "--no-render"])

            self.assertEqual(
                2, _read(directory / P.ALTERNATIVES_DIR / "snap-fit"
                         / ACC.ACCEPTANCE_FILE)["revision"])
            self.assertEqual(
                untouched,
                _digests(directory / P.ALTERNATIVES_DIR / "screw-fastened"))

            cli.branch([str(directory), "--activate", "screw-fastened"])
            report = _status(directory)
            self.assertEqual("screw-fastened", report["alternative"])
            self.assertEqual("VERIFIED", report["final_status"])
            self.assertEqual({}, report["stale"])

    def test_status_derives_one_answer_per_alternative(self) -> None:
        """Not only for whichever branch happens to be active.

        Each formulation's receipts sit in its own directory and are checked
        against that directory's own bindings, so a reader can see where both
        stand without switching branches -- and one branch going stale says
        nothing about the other.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = self._two(Path(raw))
            snap = directory / P.ALTERNATIVES_DIR / "snap-fit" / "candidate.stl"
            snap.write_bytes(snap.read_bytes() + b"\n")

            report = _status(directory)
            self.assertIsNone(report["alternative"], "reported from the root")
            by_id = {row["alternative_id"]: row for row in report["alternatives"]}
            self.assertEqual("VERIFIED", by_id["screw-fastened"]["status"])
            self.assertEqual("STALE", by_id["snap-fit"]["status"])
            self.assertEqual("VERIFIED", by_id["snap-fit"]["stored_status"])

    def test_a_shared_evidence_change_unbinds_both(self) -> None:
        """The shared half is shared, and scoping is not isolation from the job."""
        with tempfile.TemporaryDirectory() as raw:
            directory = self._two(Path(raw))
            _corrupt_the_evidence(directory)
            for name in ("screw-fastened", "snap-fit"):
                with self.subTest(alternative=name):
                    cli.branch([str(directory), "--activate", name])
                    report = _status(directory)
                    self.assertEqual("STALE", report["final_status"])
                    self.assertEqual("VERIFIED", report["stored_status"])

class NextActionIdentityTest(unittest.TestCase):
    """D17, and the identity that makes it detectable rather than only fixed."""

    def _incomplete(self, root: Path) -> Path:
        directory = root / "project"
        self.assertEqual(0, cli.init([
            str(directory), "--job-id", "bindings", "--source-mode", "NEW",
            "--consequence", "INCONSEQUENTIAL", "--updated-utc", UTC]))
        return directory

    def test_route_replaces_the_instruction_the_project_has_left(self) -> None:
        """D17: `init`, `route`, complete the project, `route` again.

        The first `route` refuses and writes "the project does not describe a job
        that can be routed". The second succeeds -- and used to leave that
        sentence sitting there, telling its next reader to go and fix something
        that had already been fixed.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = self._incomplete(Path(raw))
            self.assertEqual(2, cli.route([str(directory)]))
            stale = _read(directory / cli.NEXT_ACTION_FILE)
            self.assertEqual("FIX_PROJECT", stale["kind"])

            (directory / "brief.md").write_text("a block", encoding="utf-8")
            (directory / EVIDENCE_FILE).write_text("32.00 mm\n", encoding="utf-8")
            _project().save(directory)
            _author(directory, "block", **BLOCK)

            self.assertEqual(0, cli.route([str(directory)]))
            action = _read(directory / cli.NEXT_ACTION_FILE)
            self.assertEqual("RUN", action["kind"])
            self.assertEqual("CUSTOM", action["route"])
            self.assertEqual(
                S.payload_hash(B.current(directory, model_name="model.py")),
                action["state_sha256"],
                "the instruction after routing describes the state after routing")
            self.assertFalse(_status(directory)["waiting_for_superseded"])

    def test_the_superseded_instruction_could_say_so_for_itself(self) -> None:
        """And it is the digest that says it, not the verb that overwrote it.

        The fix above is one command remembering to rewrite one file. The point
        of the state digest is that the next one that forgets is caught: the
        instruction written against the incomplete project no longer matches the
        project, and any reader can see that without knowing which command wrote
        it.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = self._incomplete(Path(raw))
            cli.route([str(directory)])
            stale = _read(directory / cli.NEXT_ACTION_FILE)

            (directory / "brief.md").write_text("a block", encoding="utf-8")
            (directory / EVIDENCE_FILE).write_text("32.00 mm\n", encoding="utf-8")
            _project().save(directory)
            _author(directory, "block", **BLOCK)
            cli.route([str(directory)])

            project = P.load(directory)
            state = cli._state(directory, project)
            self.assertTrue(cli._superseded(stale, state))
            self.assertFalse(
                cli._superseded(_read(directory / cli.NEXT_ACTION_FILE), state))

    def test_without_the_state_digest_a_stale_instruction_reads_as_current(self) -> None:
        """The mutation: strip the identity and the staleness is undetectable.

        This is exactly the shape of the file before the slice -- kind, stage,
        reason, a completion command, and nothing that ties it to a project
        state. Every field a reader can see says the instruction is live.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = self._incomplete(Path(raw))
            cli.route([str(directory)])
            stale = _read(directory / cli.NEXT_ACTION_FILE)
            without = {key: value for key, value in stale.items()
                       if key not in ("state", "state_sha256")}

            (directory / "brief.md").write_text("a block", encoding="utf-8")
            (directory / EVIDENCE_FILE).write_text("32.00 mm\n", encoding="utf-8")
            _project().save(directory)
            _author(directory, "block", **BLOCK)
            cli.route([str(directory)])
            state = cli._state(directory, P.load(directory))

            self.assertTrue(cli._superseded(stale, state))
            self.assertTrue(cli._superseded(without, state),
                            "an instruction that carries no state cannot vouch "
                            "for itself and must not be believed")
            # ...and with the digest stripped *and* the reader trusting absence,
            # which is the pre-slice behaviour, nothing is left to notice.
            self.assertEqual(without.get("state_sha256"), None)

    def test_route_leaves_a_live_instruction_alone(self) -> None:
        """Routing answers "which route", and not "what was the designer asked for".

        An `AGENT_COMMISSION` that still describes this project is an instruction
        routing did not answer, and replacing it with the general "run it" would
        lose what the agent was told to write. The guard is the same digest: it
        is replaced when it is superseded and kept when it is not.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            self.assertEqual(cli.NEEDS_ACTION,
                             cli.run([str(directory), "--no-render"]))
            commission = _read(directory / cli.NEXT_ACTION_FILE)
            self.assertEqual("AGENT_COMMISSION", commission["kind"])

            self.assertEqual(0, cli.route([str(directory)]))
            self.assertEqual(commission,
                             _read(directory / cli.NEXT_ACTION_FILE))

    def test_route_on_a_current_success_leaves_no_instruction_at_all(self) -> None:
        """A job whose receipts still support a success is waiting for nothing."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _verified(Path(raw))
            self.assertFalse((directory / cli.NEXT_ACTION_FILE).is_file())
            self.assertEqual(0, cli.route([str(directory)]))
            self.assertFalse((directory / cli.NEXT_ACTION_FILE).is_file())

    def test_route_on_a_success_whose_evidence_moved_says_run_it_again(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _verified(Path(raw))
            _corrupt_the_evidence(directory)
            self.assertEqual(0, cli.route([str(directory)]))
            action = _read(directory / cli.NEXT_ACTION_FILE)
            self.assertEqual("RUN", action["kind"])
            self.assertTrue(any(EVIDENCE_FILE in row
                                for row in action["unresolved"]), action)

class NothingHashedGainedAKeyTest(unittest.TestCase):
    """The five pinned contracts, and every payload whose digest anything binds.

    The state digest is on `next_action.json`, which is an instruction and is
    hashed into nothing. The identity payloads -- the acceptance contract, the
    execution plan, the model contract, the artifact manifest and the final
    status -- gain no key, which is what keeps the goldens where they are.
    """

    HASHED = ("acceptance_contract.json", "execution_plan.json",
              "model_contract.json", "pipeline_artifact_receipt.json",
              "commission_report.json", "final_status.json")

    def test_the_shipped_goldens_are_untouched(self) -> None:
        report = ST.run(quick=True)
        self.assertTrue(report["ok"], [c for c in report["cases"] if not c["ok"]])

    def test_no_hashed_payload_carries_the_new_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _verified(Path(raw))
            for name in self.HASHED:
                with self.subTest(artifact=name):
                    payload = _read(directory / name)
                    for key in ("state", "state_sha256", "bindings", "stale"):
                        self.assertNotIn(key, payload)

    def test_the_project_payload_loses_the_mirror_and_gains_nothing(self) -> None:
        """`status` and `bindings` are gone; `external_geometry` is absent unless said.

        The mirror was two authorities over one fact -- a run's outcome, copied
        into the file that has to stay shared -- and the same argument that
        deleted `project_hash()` applies to the values it was hashing. What was
        *not* an outcome is `external_geometry`, which the legacy adapter had
        been keeping in there, and it has its own field now rather than being
        dropped with the rest.
        """
        payload = _project().as_payload()
        for key in ("status", "bindings", "external_geometry"):
            self.assertNotIn(key, payload)

        legacy = P.from_job_json({"job_id": "j", "updated_utc": UTC,
                                  "consequence": "INCONSEQUENTIAL",
                                  "external_geometry": True, "parameters": {}})
        self.assertTrue(legacy.external_geometry)
        self.assertTrue(legacy.as_payload()["external_geometry"])
        self.assertTrue(
            P.from_payload(legacy.as_payload()).external_geometry,
            "a legacy job's externally owned geometry survived the mirror")

    def test_a_project_written_under_the_old_mirror_still_loads(self) -> None:
        """Read, not refused. What is dropped is a copy of something on disk.

        `edit_scope` and `candidate_strategy` are refused by name because they
        were declarations, and dropping a declaration in silence loses what
        somebody wrote. `status` and `bindings` were a run stamping its own
        outcome back into the shared file, so refusing them would make every
        project this build has ever written unloadable in order to remove a
        mirror. The one value in there that was not an outcome is carried across.
        """
        payload = {**_project().as_payload(),
                   "status": {"external_geometry": True,
                              "final_status": "VERIFIED"},
                   "bindings": {"stl": "0" * 64}}
        loaded = P.from_payload(payload)
        self.assertTrue(loaded.external_geometry)
        self.assertNotIn("status", loaded.as_payload())
        self.assertNotIn("bindings", loaded.as_payload())
