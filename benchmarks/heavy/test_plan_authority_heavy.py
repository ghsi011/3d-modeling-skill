#!/usr/bin/env python3
"""L0-heavy — D34 through the build, where the plan becomes a gate.

`skills/3d-modeling/scripts/pipeline/test_plan_authority.py` drives the real
`run` endpoint and stops at the agent commission, which is where most of the
destruction happened and costs 0.02 s. What it cannot show is the last step:
that the *authored* support ceiling ends up in the frozen acceptance contract
and is therefore the number the candidate is measured against. That needs a
model, a proposal and a child interpreter, so it lives here.

The distinction matters because the two halves fail differently. A run could
leave the file alone and still gate the candidate against a template it
generated in memory; a run could bind the authored plan's hash and still
project the template's ceiling into the contract. Only the contract row
settles which ceiling the verdict rests on.

`downward_normal_z_max` is the number under test for a measured reason: it is
the only support-rule field an author may legitimately set differently from the
template, `validate_plan` permits any finite value in [-1, 0], and preflight
does not pin it to a value the contract already carries. On one measured
candidate the template's -0.73 and an author's -0.90 give 402.206 mm2 FAIL and
0.000 mm2 PASS with ceiling and tolerance identical -- so this is not a
cosmetic loss of authorship, it is the verdict.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pipeline import cli

# The fixtures the endpoint half already uses, imported rather than copied.
from pipeline.test_execution_plan import (  # noqa: E402
    BLOCK,
    _authored,
    _laid_out,
)
from pipeline.test_plan_authority import (  # noqa: E402
    _AUTHORED_NORMAL_Z_MAX,
    _TEMPLATE_NORMAL_Z_MAX,
    _accepted_plan,
)


def _support_rows(directory: Path) -> list[dict]:
    contract = json.loads(
        (directory / "acceptance_contract.json").read_text(encoding="utf-8"))
    features = contract.get("features") or contract.get("expectations") or []
    return [row for row in features
            if str(row.get("feature_id", "")).startswith("plan-support-")]


class TheContractIsFrozenAgainstTheAuthoredCeilingTest(unittest.TestCase):
    """**This fails on a build that regenerates the plan, and only then.**"""

    def _accepted_for(self, directory: Path) -> dict:
        plan = _accepted_plan()
        (directory / cli.PRINT_PLAN_CHECKS_FILE).write_text(json.dumps(plan), encoding="utf-8")
        return plan

    def test_the_frozen_contract_carries_the_authors_ceiling(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), _authored(), model=BLOCK)
            self._accepted_for(directory)
            cli.run([str(directory), "--no-render"])
            rows = _support_rows(directory)
        self.assertEqual(1, len(rows), rows)
        self.assertEqual(_AUTHORED_NORMAL_Z_MAX, rows[0]["downward_normal_z_max"],
                         "the candidate is being measured against the template")

    def test_the_plan_file_survives_a_full_build(self) -> None:
        """The build path writes far more than the commission path does, and a
        guard that held only where the run stopped early would leave every job
        that actually builds still losing its plan."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), _authored(), model=BLOCK)
            self._accepted_for(directory)
            before = (directory / cli.PRINT_PLAN_CHECKS_FILE).read_bytes()
            cli.run([str(directory), "--no-render"])
            after = (directory / cli.PRINT_PLAN_CHECKS_FILE).read_bytes()
        self.assertEqual(before, after, "the build rewrote the accepted plan")


class TheGeneratedTemplateStillReachesTheContractTest(unittest.TestCase):
    """**The control, and it passes in both builds.**

    A fix that stopped projecting support rules at all would satisfy the rows
    above. This one requires that a job with no authored plan still gets a
    contract row, and that the row carries the template's own ceiling -- so the
    guard is proved to be about *whose* plan it is, not about whether there is
    one.
    """

    def test_a_job_with_no_authored_plan_is_gated_on_the_template(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), _authored(), model=BLOCK)
            cli.run([str(directory), "--no-render"])
            rows = _support_rows(directory)
        self.assertEqual(1, len(rows), rows)
        self.assertEqual(_TEMPLATE_NORMAL_Z_MAX, rows[0]["downward_normal_z_max"])


if __name__ == "__main__":
    unittest.main()
