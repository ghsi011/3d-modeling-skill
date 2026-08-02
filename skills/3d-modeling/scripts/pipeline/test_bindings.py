#!/usr/bin/env python3
"""Release 3 slice B: scoped invalidation, and a status computed rather than read.

Three things were true of this build before the slice, and each of them is a
different way for a receipt to say something that is no longer so:

* **the status was stored.** `status.decide` ran once, mid-run, its answer went
  into `final_status.json`, and every reader afterwards repeated it verbatim.
  `design-tool status` recomputed the project's `problems` and took the verdict
  as given, so a `VERIFIED` receipt beside a candidate somebody had rebuilt, an
  evidence file somebody had corrected, or a plan that had since moved read as
  current -- and nothing on disk could tell;
* **invalidation was all-or-nothing.** A changed acceptance body deleted a fixed
  six-name tuple, whatever had actually moved. It could not express "this
  changed, therefore that is stale", so it could only express "something changed,
  therefore everything is" -- and the other direction, a receipt that is still
  true and must not be thrown away, it could not express at all;
* **`next_action.json` had no identity.** No run id, no sequence, no self-digest.
  Staleness was handled by overwriting or unlinking, so any path that changed the
  project without reaching one of those two calls left an instruction pointing at
  work already done. D17 is the live instance: a successful `route` left the "fix
  the project" instruction it had written while the project was incomplete.

Every test here fails on the code as it stood before the slice. Where a test
shows a protection holding, its neighbour mutates the protection and shows the
loss is reachable -- a test that only shows the current code refusing proves that
the refusal happens, not that anything is holding it up.
"""
from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from . import acceptance as ACC
from . import bindings as B
from . import cli
from . import project as P
from . import schemas as S
from . import selftest as ST
from . import status as STATUS

UTC = "1970-01-01T00:00:00Z"

MODEL = '''
import trimesh

PARAMS = {{"w": {w}, "d": {d}, "h": {h}}}


def build():
    block = trimesh.creation.box(extents=({w}, {d}, {h}))
    block.apply_translation(({w} / 2, {d} / 2, {h} / 2))
    return block
'''

BLOCK = dict(w=40.0, d=30.0, h=10.0)
OTHER = dict(w=36.0, d=26.0, h=12.0)

# The declared evidence. A caliper sheet is a *shared* job input: it is named
# once against the project, it is hashed into every review envelope that was
# shown it, and it reaches no contract and no artifact. Correcting one after a
# review is therefore the sharpest available case of a change that must unbind
# exactly one thing -- and, before this slice, of a change nothing could see.
EVIDENCE_FILE = "calipers.md"


def _proposal(design_id: str, *, w: float, d: float, h: float) -> dict:
    return {
        "schema_version": 1,
        "job_id": "bindings",
        "design_id": design_id,
        "rationale": f"a {w}x{d}x{h} block",
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


def _project(**over) -> P.Project:
    base = dict(
        job_id="bindings", updated_utc=UTC, source_mode="NEW",
        consequence="INCONSEQUENTIAL",
        consequence_rationale="a desk block; failure wastes material",
        printer="Test Printer", material={"process": "FDM", "material": "PLA"},
        nozzle={"diameter_mm": 0.4},
        orientation={"model_to_printer_matrix": "identity", "bed_z_mm": 0.0},
        template=None, parameters={}, model="model.py",
        envelope_mm={"x": 60.0, "y": 50.0, "z": 20.0},
        reviewer={"model_snapshot": "test"},
        evidence=(EVIDENCE_FILE,),
        verification_requested=True,
        requirements=(P.Requirement(name="mount_pitch", value=32.0, unit="mm",
                                    provenance="STATED", source="user"),),
    )
    base.update(over)
    return P.Project(**base)


def _laid_out(root: Path, project: P.Project | None = None) -> Path:
    directory = root / "project"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "brief.md").write_text("a block", encoding="utf-8")
    (directory / EVIDENCE_FILE).write_text(
        "mount pitch 32.00 mm, digital calipers, 2026-08-02\n", encoding="utf-8")
    (project or _project()).save(directory)
    return directory


def _author(where: Path, design_id: str, **params) -> None:
    where.mkdir(parents=True, exist_ok=True)
    (where / "model.py").write_text(textwrap.dedent(MODEL.format(**params)),
                                    encoding="utf-8")
    (where / ACC.PROPOSAL_FILE).write_text(
        S.canonical_json(_proposal(design_id, **params)), encoding="utf-8")


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _digests(directory: Path) -> dict[str, str]:
    return {p.relative_to(directory).as_posix(): S.sha256_file(p)
            for p in sorted(directory.rglob("*")) if p.is_file()}


def _answer(work_dir: Path) -> None:
    """Echo the packet's own envelope back with a closed PASS."""
    packet = _read(work_dir / cli.REVIEW_DIR / "verification_packet.json")
    (work_dir / cli.REVIEW_DIR / "verification_response.json").write_text(
        S.canonical_json({
            "decision": "PASS", "defects": [], "unmet_requirements": [],
            "missing_evidence": [], "summary": "nothing undeclared visible",
            "review_envelope": packet["review_envelope"]}), encoding="utf-8")


def _verified(root: Path) -> Path:
    """An ordinary authored job carried all the way to a stored VERIFIED."""
    directory = _laid_out(root)
    _author(directory, "block", **BLOCK)
    assert cli.run([str(directory), "--no-render"]) == cli.NEEDS_ACTION
    _answer(directory)
    assert cli.run([str(directory), "--no-render"]) == 0
    assert _read(directory / "final_status.json")["final_status"] == "VERIFIED"
    return directory


def _status(directory: Path) -> dict:
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        cli.status([str(directory), "--json"])
    return json.loads(stream.getvalue())


def _corrupt_the_evidence(directory: Path) -> None:
    """The caliper sheet is corrected after the review that was shown it."""
    (directory / EVIDENCE_FILE).write_text(
        "mount pitch 32.05 mm, digital calipers, re-measured\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# A status derived from what is on disk
# ---------------------------------------------------------------------------

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
            self.assertIn("verification_report.json", report["stale"])
            self.assertTrue(
                any(EVIDENCE_FILE in row
                    for row in report["stale"]["verification_report.json"]),
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
            self.assertTrue((directory / "verification_report.json").is_file())
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
            self.assertIn("stale        verification_report.json", printed)

    def test_without_the_envelope_s_evidence_digests_the_change_is_invisible(self) -> None:
        """The mutation: stop reading what the review bound and the claim survives.

        `verification_report.json` records the digest of every file the reviewer
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


# ---------------------------------------------------------------------------
# Invalidation, scoped to what depended on the change
# ---------------------------------------------------------------------------

class ScopedInvalidationTest(unittest.TestCase):
    """What is removed is what depended on the thing that changed, and no more."""

    def test_a_receipt_whose_bindings_still_hold_is_not_deleted(self) -> None:
        """The corrected caliper sheet takes the review and the status, and stops.

        `commission_report.json` and `artifact_manifest.json` are measurements of
        a candidate that has not moved, against a contract that has not moved.
        They are still true, and the old rule deleted them anyway because they
        were in the tuple.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _verified(Path(raw))
            _corrupt_the_evidence(directory)

            removed = B.invalidate(directory, evidence_dir=directory,
                                   model_name="model.py")

            self.assertEqual({"verification_report.json", "final_status.json"},
                             set(removed))
            for name in ("artifact_manifest.json", "commission_report.json",
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
                _read(directory / "verification_report.json").get("decision"),
                "the answer written against the old caliper sheet was promoted")
            self.assertTrue((directory / "commission_report.json").is_file(),
                            "the measurements of an unchanged candidate went "
                            "with the review that was shown a changed file")

    def test_a_rebuilt_candidate_takes_the_measurements_of_it_with_it(self) -> None:
        """The other direction, so the scoping is not just "delete less".

        `commission_report.json` records the contract it measured against and
        not the mesh it measured. It is stale here because it was issued beside
        `artifact_manifest.json`, which does record it -- the edge is declared
        precisely where the receipt does not carry the digest itself.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _verified(Path(raw))
            stl = directory / "candidate.stl"
            stl.write_bytes(stl.read_bytes() + b"\n")

            stale = B.broken(directory, evidence_dir=directory)
            self.assertIn("artifact_manifest.json", stale)
            self.assertIn("commission_report.json", stale)
            self.assertTrue(
                any("artifact_manifest.json" in row
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


# ---------------------------------------------------------------------------
# Two formulations, one invalidation
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# An instruction that can say it is out of date
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# The certified lane, which has no frozen acceptance contract at all
# ---------------------------------------------------------------------------

class CertifiedLaneTest(unittest.TestCase):
    """Derivation is not an authored-lane feature bolted onto one code path.

    A certified job has no `acceptance_contract.json`: its contract is derived
    from the project and the template at run time. So the `acceptance` binding is
    absent and the receipts are checked against `model_contract.json`, which is
    what they all carry the hash of either way.
    """

    def _certified(self, root: Path) -> Path:
        directory = root / "project"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "brief.md").write_text("a clip", encoding="utf-8")
        _project(template="c_clip", model=None, envelope_mm=None, evidence=(),
                 verification_requested=False,
                 parameters=dict(ST.FROZEN_PARAMETERS["c_clip"])).save(directory)
        cli.run([str(directory), "--no-render"])
        return directory

    def test_an_untouched_certified_job_derives_what_it_stored(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = self._certified(Path(raw))
            report = _status(directory)
            self.assertEqual("DIRECT", report["route"])
            self.assertEqual("NEEDS_MORE_EVIDENCE", report["stored_status"])
            self.assertEqual("NEEDS_MORE_EVIDENCE", report["final_status"])
            self.assertEqual({}, report["stale"])
            self.assertIsNone(report["state"]["acceptance"],
                              "a certified lane has no frozen acceptance contract")
            self.assertIsNotNone(report["state"]["contract"])

    def test_a_finding_survives_its_bindings_breaking(self) -> None:
        """End to end, on the rule that a broken binding may not hide a defect."""
        with tempfile.TemporaryDirectory() as raw:
            directory = self._certified(Path(raw))
            stl = directory / "candidate.stl"
            stl.write_bytes(stl.read_bytes() + b"\n")

            report = _status(directory)
            self.assertEqual("NEEDS_MORE_EVIDENCE", report["final_status"])
            self.assertIn("final_status.json", report["stale"])
            self.assertIn("artifact_manifest.json", report["stale"])


# ---------------------------------------------------------------------------
# The zero-cost proof
# ---------------------------------------------------------------------------

class NothingHashedGainedAKeyTest(unittest.TestCase):
    """The five pinned contracts, and every payload whose digest anything binds.

    The state digest is on `next_action.json`, which is an instruction and is
    hashed into nothing. The identity payloads -- the acceptance contract, the
    execution plan, the model contract, the artifact manifest and the final
    status -- gain no key, which is what keeps the goldens where they are.
    """

    HASHED = ("acceptance_contract.json", "execution_plan.json",
              "model_contract.json", "artifact_manifest.json",
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


if __name__ == "__main__":
    unittest.main()
