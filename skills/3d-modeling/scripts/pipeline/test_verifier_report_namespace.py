#!/usr/bin/env python3
"""D37: the pipeline's review report was squatting on the verifier's contract.

`verification_report.json` is a team contract:
`team_tools.validators.CANONICAL_FILENAMES` names it, `_EXPECTED_OWNERS`
requires `verifier` to have authored it, and `team_tools.status` cross-checks
`dimensions_revision`, `print_plan_revision`, `reference_sha256` and
`candidate_stl_sha256` against it. The pipeline wrote its own review report --
a decision, a packet digest, a review envelope -- to the same path, and listed
that path among its own removable receipts.

**D36's two mechanisms, one more of its own, and one running the other way.**
The write displaces the contract. `bindings.invalidate` deletes it when it
judges it stale, reached from `cli._finish` rather than from a commission stop.
`cli._restart` deletes it *unconditionally*, because `cli._concluded_files` is
`[work_dir / name for name in B.REMOVABLE]`. And in the other direction the team
lane then cross-checks a document carrying none of the four bindings, so three
of them report the contract stale or invalidated against something it never
claimed and the fourth silently stops comparing at all.

A rename rather than a guard, for D36's reason: both writers are legitimate and
only one is entitled to the name. The team contract's is externally specified,
validator-known and charter-facing; the pipeline's has no reader outside this
package, so the pipeline's is what moves -- and it moves *through the registry*
in `artifact_names`, so the next writer to reach for the name is refused rather
than repaired afterwards.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from . import artifact_names as N
from . import bindings as B
from . import schemas as S
from .test_pipeline import _run_full_looked

# The verifier's own contract, as this repository already ships it. A fixture
# invented here would be a fixture this test agreed with; the committed example
# is the one `dt.py validate` and `dt.py status` are held to.
EXAMPLE_PROJECT = (Path(__file__).resolve().parents[1] / "team_tools"
                   / "examples" / "project_ok")
# From the registry rather than spelled again here, so the two cannot drift --
# and the read below fails loudly if the registry ever names a file the example
# project does not ship.
TEAM_FILE = N.VERIFICATION_REPORT
TEAM_CONTRACT = json.loads((EXAMPLE_PROJECT / TEAM_FILE).read_text(encoding="utf-8"))

# What the pipeline's own review report is: `verification.run`'s return shape.
# It overlaps the contract on `defects` and `fresh_context` and on nothing else.
PIPELINE_REPORT = {
    "schema_version": S.VERIFICATION_SCHEMA,
    "evidence_packet_sha256": "b" * 64,
    "reviewer": {"model_snapshot": "test"},
    "review_envelope": None,
    "fresh_context": None,
    "saw_designer_reasoning": None,
    "reviewed_questions": [],
    "decision": "PASS",
    "defects": [],
    "unmet_requirements": [],
    "missing_evidence": [],
    "summary": "ok",
}


def _seed_contract(work: Path) -> bytes:
    path = work / TEAM_FILE
    path.write_text(json.dumps(TEAM_CONTRACT, indent=2), encoding="utf-8")
    return path.read_bytes()


class ThePipelineReportHasItsOwnNameTest(unittest.TestCase):
    """**The rename itself, asserted where a reader can check it.**"""

    def test_the_report_is_not_the_team_contract(self) -> None:
        self.assertNotEqual(TEAM_FILE, N.PIPELINE_VERIFICATION_REPORT)

    def test_the_report_collides_with_no_role_owned_canonical_name(self) -> None:
        """Against the authoritative set, the standard D35 and D36 were held to:
        a rename that lands on another role's artifact has moved the defect
        rather than closed it."""
        from team_tools import validators as V
        owned = {name for spellings in V.CANONICAL_FILENAMES.values()
                 for name in spellings}
        self.assertTrue(owned, "the canonical set came back empty")
        self.assertNotIn(N.PIPELINE_VERIFICATION_REPORT, owned)

    def test_the_team_contract_is_not_a_pipeline_receipt(self) -> None:
        """**The lifecycle half, and `REMOVABLE` has two consumers.**

        `invalidate` deletes from it when a receipt goes stale, and
        `cli._concluded_files` is `[work_dir / name for name in B.REMOVABLE]`,
        which `cli._restart` unlinks one by one -- so membership alone was
        enough to have `--restart` delete the verifier's contract with no
        staleness involved at all. The name must not appear in the table, which
        is what closes both.
        """
        names = {receipt.name for receipt in B.RECEIPTS}
        self.assertNotIn(TEAM_FILE, names)
        self.assertNotIn(TEAM_FILE, B.REMOVABLE)
        self.assertIn(N.PIPELINE_VERIFICATION_REPORT, names)
        self.assertIn(N.PIPELINE_VERIFICATION_REPORT, B.REMOVABLE)

    def test_no_dependency_edge_names_the_team_contract(self) -> None:
        """A `depends_on` edge is how a file gets judged stale in the first
        place, so an edge left behind would keep deleting it.

        `final_status.json` names the verification report only when it promoted
        one, so the payload has to say it did -- an edge probed with an empty
        dict is an edge this test never reads.
        """
        promoted = {"verification": {"decision": "PASS"},
                    "safety_verification": {"decision": "PASS"}}
        edges: list[str] = []
        for receipt in B.RECEIPTS:
            edges.extend(receipt.depends_on(promoted))
        self.assertIn(N.PIPELINE_VERIFICATION_REPORT, edges,
                      "the edge to the pipeline's own report was lost with the "
                      "rename, so a promoted status now depends on nothing")
        self.assertNotIn(TEAM_FILE, edges)


class TheVerifiersContractSurvivesTest(unittest.TestCase):
    """**This proves the verifier's contract is safe from the pipeline, because
    it fails when the pipeline's write is pointed back at the shared name.**

    `Y` is the pre-D37 implementation: `runner` writing its review report to
    `out / "verification_report.json"` instead of resolving
    `N.PIPELINE_VERIFICATION_REPORT` through `artifact_names.path`. Run that way,
    `test_a_seeded_contract_survives_a_full_run` fails on the byte comparison --
    the contract comes back as the pipeline's object. Driven by
    `benchmarks/mutations/d37-verifier-report.json`.
    """

    def test_a_seeded_contract_survives_a_full_run(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            before = _seed_contract(work)
            result = _run_full_looked(work)
            self.assertEqual("VERIFIED", result.final_status["final_status"],
                             "the run must actually reach the verification "
                             "write, or this proves nothing about it")
            self.assertEqual(before, (work / TEAM_FILE).read_bytes(),
                             "the run overwrote the verifier's contract")
            written = work / N.PIPELINE_VERIFICATION_REPORT
            self.assertTrue(written.is_file(),
                            "the pipeline stopped writing its own report")
            report = json.loads(written.read_text(encoding="utf-8"))
            self.assertEqual("verification", report["review_envelope"]["kind"])
            # Why the collision mattered rather than merely looked untidy, read
            # off what the run actually wrote: the pipeline's report carries
            # none of the four bindings the team lane checks, so while it held
            # that name the lane was cross-checking a document that could not
            # answer.
            self.assertEqual([], [field for field, _, _
                                  in TheTeamLaneCrossChecksTheVerifiersContractTest.BINDINGS
                                  if field in report])

    def test_a_seeded_contract_survives_invalidate(self) -> None:
        """**The mechanism a rename of the write alone would not have closed**,
        and proven against `invalidate` directly: on a run that builds, the
        pipeline's own later write masks the deletion."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            before = _seed_contract(work)
            removed = B.invalidate(work)
            self.assertNotIn(TEAM_FILE, removed)
            self.assertTrue((work / TEAM_FILE).is_file(),
                            "invalidation deleted the verifier's contract")
            self.assertEqual(before, (work / TEAM_FILE).read_bytes())

    def test_the_pipeline_report_is_still_invalidated(self) -> None:
        """**The control**, and it observes the same property through the same
        path as the row above: a fix that simply stopped deleting anything would
        satisfy that one while leaving stale reports standing."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            before = _seed_contract(work)
            report = work / N.PIPELINE_VERIFICATION_REPORT
            report.write_text(json.dumps(PIPELINE_REPORT), encoding="utf-8")
            removed = B.invalidate(work)
            self.assertIn(N.PIPELINE_VERIFICATION_REPORT, removed)
            self.assertFalse(report.is_file())
            self.assertTrue((work / TEAM_FILE).is_file())
            self.assertEqual(before, (work / TEAM_FILE).read_bytes())

    def test_with_no_verifier_contract_the_pipeline_still_manages_its_own(self) -> None:
        """**Preservation.** Nothing here may depend on a team contract being
        present: the great majority of work directories hold none."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            result = _run_full_looked(work)
            report = work / N.PIPELINE_VERIFICATION_REPORT
            self.assertEqual("VERIFIED", result.final_status["final_status"])
            self.assertTrue(report.is_file())
            self.assertFalse((work / TEAM_FILE).exists(),
                             "the pipeline wrote the team contract's name")
            (work / B.MODEL_CONTRACT_FILE).write_text("{}", encoding="utf-8")
            self.assertIn(N.PIPELINE_VERIFICATION_REPORT, B.invalidate(work))
            self.assertFalse(report.is_file())


class TheTeamLaneCrossChecksTheVerifiersContractTest(unittest.TestCase):
    """**The other direction, and what this class does and does not observe.**

    That the pipeline no longer displaces the contract is
    `test_a_seeded_contract_survives_a_full_run`'s claim, not this one's. What
    is left to establish is that the document standing at that name is one the
    team lane can actually read, and that is what these rows do.

    A clean status would not establish it: a check that never ran is green too,
    which is the exact failure the pipeline's object produced -- three of these
    four reported the *contract* stale against bindings it never carried, and
    the fourth stopped comparing entirely. So each binding is moved on its own
    and the row it produces is required.
    """

    #: Each binding, what breaking it must be called, and what to break it to.
    BINDINGS = (
        ("dimensions_revision", "STALE", 99),
        ("print_plan_revision", "STALE", 99),
        ("reference_sha256", "INVALIDATED", "0" * 64),
        ("candidate_stl_sha256", "INVALIDATED", "0" * 64),
    )

    def _status(self, payload: dict) -> list[dict]:
        from team_tools.status import compute_status
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw) / "project"
            shutil.copytree(EXAMPLE_PROJECT, project)
            (project / TEAM_FILE).write_text(json.dumps(payload), encoding="utf-8")
            return compute_status(project)

    def test_the_verifiers_contract_reads_clean(self) -> None:
        from team_tools.status import exit_code
        rows = self._status(TEAM_CONTRACT)
        self.assertEqual(0, exit_code(rows),
                         [row for row in rows if row["status"] != "OK"])

    def test_each_of_the_four_bindings_is_actually_compared(self) -> None:
        for field, expected, broken in self.BINDINGS:
            with self.subTest(binding=field):
                rows = self._status({**TEAM_CONTRACT, field: broken})
                reported = [row for row in rows
                            if row["contract"] == "VERIFICATION_REPORT"
                            and row["status"] == expected]
                self.assertTrue(
                    reported,
                    f"moving {field} produced no VERIFICATION_REPORT row, so "
                    f"that binding is not being read off the contract")


class TheRegistryRefusesASecondOwnerTest(unittest.TestCase):
    """**This proves a registered name has exactly one owner, because it fails
    when `register` and `path` stop comparing the holder.**

    `Y` for the first row is a `register` that overwrites the holder instead of
    refusing; for the second, a `path` that returns the join without checking.
    Both are in `benchmarks/mutations/d37-verifier-report.json` and both were
    run.
    """

    def test_a_second_owner_claiming_a_registered_name_is_refused(self) -> None:
        with self.assertRaises(N.NameConflict) as caught:
            N.register(TEAM_FILE, owner=N.PIPELINE)
        self.assertIn(N.VERIFIER, str(caught.exception))
        self.assertEqual(N.VERIFIER, N._OWNERS[TEAM_FILE],
                         "the refused claim moved the owner anyway")

    def test_re_registering_the_same_pair_is_not_a_conflict(self) -> None:
        """This checkout imports some modules twice under two names; an import
        that raised the second time would be reporting the packaging."""
        self.assertEqual(TEAM_FILE, N.register(TEAM_FILE, owner=N.VERIFIER))

    def test_an_owner_resolves_its_own_artifact_to_a_path(self) -> None:
        work = Path("work")
        self.assertEqual(work / N.PIPELINE_VERIFICATION_REPORT,
                         N.path(work, N.PIPELINE_VERIFICATION_REPORT,
                                owner=N.PIPELINE))

    def test_a_writer_that_does_not_own_the_name_is_refused(self) -> None:
        for owner, name in ((N.PIPELINE, TEAM_FILE),
                            (N.VERIFIER, N.PIPELINE_VERIFICATION_REPORT),
                            (N.PIPELINE, "not_registered_at_all.json")):
            with self.subTest(owner=owner, name=name):
                with self.assertRaises(N.NameConflict):
                    N.path(Path("work"), name, owner=owner)


if __name__ == "__main__":
    unittest.main()
