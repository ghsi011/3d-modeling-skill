#!/usr/bin/env python3
"""L0-heavy — what an authored job costs, measured through the real boundary.

The commit-gate half of this slice
(`skills/3d-modeling/scripts/pipeline/test_cost.py`) measures the certified lane,
which builds in this process, and the *commission* on the authored lane, which
stops before any geometry exists. Neither can reach the two numbers that only the
authored lane has:

* the **confined build boundary**, which is a fresh interpreter reaching `import
  trimesh` and is the dominant term on this lane -- ~1.6 s against a whole
  certified run's 0.2 s. `docs/baseline.md` decomposes it by hand; the ledger is
  what records it per invocation;
* the **review round trip**, which is what `repeated_builds` was added for. A job
  with one bounded review is two invocations of `design-tool run` and two confined
  builds of identical geometry, and the second one exists solely because the first
  had to stop and ask.

Both need a child interpreter, which the root `conftest.py` refuses inside the
gate, so they run here.
"""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from pipeline import cli
from pipeline import cost as COST

# The authored fixture the bindings slice already built: a project laid out, a
# model and proposal authored, a verification round trip answered from the
# packet's own envelope, and a stored VERIFIED at the end. Imported rather than
# copied -- two spellings of one fixture is how two tiers stop testing the same
# thing.
from pipeline.test_bindings import (  # noqa: E402
    _answer,
    _author,
    _laid_out,
    BLOCK,
    _verified,
)


class AnAuthoredJobPaysForTheBoundaryAndPaysAgainToResumeTest(unittest.TestCase):
    """The two costs only this lane has, and the ledger that now reports them."""

    def test_the_round_trip_cost_two_confined_builds_of_the_same_geometry(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _verified(Path(raw))
            totals = COST.totals_at(directory)

            self.assertEqual(2, totals["invocations"],
                             "one run to ask for the verification and one to "
                             "consume the answer")
            self.assertEqual(2, totals["builds"])
            self.assertEqual(1, totals["repeated_builds"],
                             "the resumed run rebuilt the candidate the paused "
                             "run had already built. That is what a bounded "
                             "review costs on this lane and nothing measured it "
                             "before.")
            self.assertEqual(1, totals["reviews"])
            self.assertEqual(0, totals["commissions"],
                             "the designer output was authored by the fixture, so "
                             "no commission was dispatched -- the number a real "
                             "job would also pay")
            self.assertEqual(1, totals["failed_invocations"],
                             "the invocation that stopped for the review produced "
                             "no claim, and its seconds are in the totals rather "
                             "than absent from them")

    def test_the_confined_boundary_is_the_dominant_term_and_is_recorded(self) -> None:
        """The cost that happens outside `runner.run` and is charged to it anyway."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _verified(Path(raw))
            totals = COST.totals_at(directory)
            self.assertGreater(totals["build_boundary_seconds"], 0.0,
                               "a run that reported no boundary cost would be "
                               "reporting a 1.7 s job as a 0.05 s one")
            self.assertGreater(totals["deterministic_seconds"],
                               totals["build_boundary_seconds"],
                               "the boundary is part of the total, not the whole "
                               "of it")
            for entry in COST.invocations(directory):
                with self.subTest(stage=entry["stage"]):
                    self.assertEqual("AUTHORED", entry["builder"])
                    self.assertGreater(entry["seconds"]["build_boundary"], 0.0)

    def test_the_pause_is_recorded_as_an_invocation_that_concluded_nothing(self) -> None:
        """A run that stops to ask has still spent everything up to the question."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            _author(directory, "block", **BLOCK)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cli.NEEDS_ACTION,
                                 cli.run([str(directory), "--no-render"]))

            entries = COST.invocations(directory)
            self.assertEqual(1, len(entries))
            self.assertEqual("review-pause", entries[0]["stage"])
            self.assertFalse(entries[0]["ok"])
            self.assertEqual(1, entries[0]["builds"],
                             "the candidate was built, exported, re-imported and "
                             "commissioned before anybody was asked anything")
            self.assertEqual(
                [{"kind": "verification", "context_bytes": COST.context_bytes(
                    json.loads(
                        (directory / cli.REVIEW_DIR / "verification_packet.json")
                        .read_text(encoding="utf-8"))),
                  "reused": False}],
                entries[0]["dispatches"],
                "the question is the dispatch on this path: the packet is on "
                "disk, an agent will answer it, and this is the invocation that "
                "asked. `llm_calls` is 0 here and 1 on the run that reads the "
                "answer back, which is why the ledger counts the pause instead")

            _answer(directory)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(0, cli.run([str(directory), "--no-render"]))
            totals = COST.totals_at(directory)
            self.assertEqual(1, totals["reviews"], "one question, asked once")
            self.assertEqual(1, totals["reviews_reused"],
                             "and one stored answer read back, which `llm_calls` "
                             "counts as a second dispatch and this does not")

    def test_a_restart_is_two_more_builds_and_the_ledger_keeps_them(self) -> None:
        """`--restart` discards conclusions; it does not discard what they cost.

        The receipts go and are journalled in `lifecycle.json`; the ledger is the
        record that the job paid for them and is about to pay again. A cost
        record a restart could erase would report the cheapest history rather
        than the real one.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _verified(Path(raw))
            before = COST.totals_at(directory)
            with contextlib.redirect_stderr(io.StringIO()):
                cli.run([str(directory), "--restart", "--no-render"])
            after = COST.totals_at(directory)
            self.assertEqual(before["builds"] + 1, after["builds"])
            self.assertGreater(after["deterministic_seconds"],
                               before["deterministic_seconds"])


if __name__ == "__main__":
    unittest.main()
