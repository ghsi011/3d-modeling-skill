#!/usr/bin/env python3
"""L0-heavy -- the half of
`skills/3d-modeling/scripts/pipeline/test_verifier_report_namespace.py`
that had to leave the commit gate for room.

**Structure, not behaviour, put these here, and the distinction matters.** These
fixtures start no child process and none of them is slow: the two that drive a
full run measure about 0.25 s each in the parent process, and the rest are a
`copytree` of one small example project. On the rule `docs/agents/review-workflow.md`
section 5 states -- tier by behaviour, not by available headroom -- most of this
file belongs in L0 and is here anyway.

What actually happened is that the commit gate reached its ceiling.
`conftest.py`'s `L0_COLLECTED_CEILING` is 1440, `main` collects 1427, and this
slice adds 14 tests. The user ruled that a slice moves its new fixtures to this
tier rather than raising the gate, because raising a gate to make work fit is
the thing `AGENTS.md` forbids.

**The consequence, stated rather than glossed:** these rows no longer run on
every commit. They still run before merge, because the `pull_request` pre-merge
job runs this tier, so coverage is preserved and the *commit* gate is what got
smaller. A developer who breaks the verifier's contract now learns it at
pre-merge instead of at commit.

Two of the classes here are the closest thing this slice has to end-to-end, and
for those the placement is also defensible on behaviour:
`test_a_seeded_contract_survives_a_full_run` and
`test_with_no_verifier_contract_the_pipeline_still_manages_its_own` execute a
whole job through `runner.run`. The two `invalidate` rows are not heavy-shaped
at all -- they are a `bindings.invalidate` call over a temporary directory --
and they travel with the class because an arm and its control must observe the
same property through the same path at the same tier.

The fixtures are imported from the half that stayed behind rather than copied:
two spellings of one fixture is how two tiers stop testing the same thing.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from pipeline import artifact_names as N
from pipeline import bindings as B
from pipeline.test_pipeline import _run_full_looked

from pipeline.test_verifier_report_namespace import (  # noqa: E402
    EXAMPLE_PROJECT,
    PIPELINE_REPORT,
    TEAM_CONTRACT,
    TEAM_FILE,
    _seed_contract,
)


class TheVerifiersContractSurvivesTest(unittest.TestCase):
    """**This proves the verifier's contract is safe from the pipeline, because
    it fails when the pipeline's write is pointed back at the shared name.**

    `Y` is the pre-D38 implementation: `runner` writing its review report to
    `out / "verification_report.json"` instead of resolving
    `N.PIPELINE_VERIFICATION_REPORT` through `artifact_names.path`. Run that way,
    `test_a_seeded_contract_survives_a_full_run` fails on the byte comparison --
    the contract comes back as the pipeline's object. Driven by
    `benchmarks/mutations/d38-verifier-report.json`.
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

if __name__ == "__main__":
    unittest.main()
