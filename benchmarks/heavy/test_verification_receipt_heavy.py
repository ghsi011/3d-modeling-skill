#!/usr/bin/env python3
"""D37, the half that needs a real run: a verifier's REJECT must survive.

The L0 rows next to `bindings.py` prove the namespace and the compatibility
predicate. These two prove the thing the defect actually destroyed, and they can
only be proved by running the pipeline: seed the verifier's own
`verification_report.json`, run a job through verification, and require the file
to come back **byte-identical**.

Both halves are here because they fail differently. The success path overwrote a
verifier's report with the pipeline's own review record -- bad, but both objects
are reviews. The exception path overwrote it with `{schema_version, error}`,
which converts "a person found a defect" into "something went wrong". That one
does not lose a verdict, it inverts one, and it is the reason this file exists.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parents[2] / "skills" / "3d-modeling" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from pipeline import bindings as B  # noqa: E402
from pipeline import cli  # noqa: E402
from pipeline import project as P  # noqa: E402
from pipeline import schemas as S  # noqa: E402
# `_laid_out` is aliased: `test_phase3`'s builds the MODIFY fixture used above,
# and `test_bindings`' builds the authored job that reaches a stored VERIFIED.
# Two different fixtures, one name, and only one of them can be it.
from pipeline.test_bindings import (  # noqa: E402
    BLOCK,
    _answer,
    _author,
    _status,
    _verified,
)
from pipeline.test_bindings import _laid_out as _laid_out_authored  # noqa: E402
from pipeline.test_phase3 import (  # noqa: E402
    MODIFIER,
    _laid_out,
    _modify_project,
    _store_passing_answer,
)

# A verifier's report, with a verdict a destructive write would erase and a
# defect a reader would act on. `contract` is what makes it the team object.
VERIFIER_REJECT = {
    "contract": "verification-report",
    "contract_version": 4,
    "job_id": "d37-preservation",
    "revision": 1,
    "owner": "verifier",
    "status": "REJECT",
    "candidate_id": "candidate-01",
    "fresh_context": True,
    "updated_utc": "1970-01-01T00:00:00Z",
    "defects": [{"summary": "seat wall 0.6 mm, below the 1.2 mm minimum"}],
}


class AVerifiersRejectSurvivesThePipelineTest(unittest.TestCase):
    """Requirements 1 and 2 of the ruled minimum proof."""

    INTERFACE = P.Interface(
        interface_id="boss-seat", kind="ball seat", external=False,
        owner="this job", note="the seat this edit cuts")

    def _laid_out(self, root: Path) -> Path:
        return _laid_out(root, MODIFIER, _modify_project(
            verification_requested=True,
            reviewer={"model_snapshot": "test", "fresh_context": True},
            interfaces=(self.INTERFACE,)))

    @staticmethod
    def _seed_verifier_report(directory: Path) -> bytes:
        path = directory / "verification_report.json"
        path.write_text(json.dumps(VERIFIER_REJECT, indent=2), encoding="utf-8")
        return path.read_bytes()

    def test_a_successful_verification_leaves_the_verifier_report_untouched(self) -> None:
        """Requirement 1: the success path writes its receipt somewhere else."""
        with tempfile.TemporaryDirectory() as raw:
            directory = self._laid_out(Path(raw))
            self.assertEqual(
                cli.NEEDS_ACTION, cli.run([str(directory), "--no-render"]),
                "the first run must stop and ask for the verification review")
            before = self._seed_verifier_report(directory)
            _store_passing_answer(directory)

            # Not asserting exit 0: this MODIFY lane declines to claim the part
            # on its own grounds -- the preservation audit's sample density is
            # not yet derived from a declared minimum defect size -- and that
            # verdict is nothing to do with this slice. What matters here is
            # that verification *ran*, which the receipt below establishes.
            cli.run([str(directory), "--no-render"])

            self.assertEqual(
                before, (directory / "verification_report.json").read_bytes(),
                "the pipeline wrote over a verifier's REJECT")

            receipt = directory / B.PIPELINE_VERIFICATION_RECEIPT
            self.assertTrue(receipt.is_file(),
                            "the pipeline's own receipt has to be written, or "
                            "this row would pass on a pipeline that simply "
                            "stopped recording its review")
            self.assertEqual(
                "PASS",
                json.loads(receipt.read_text(encoding="utf-8"))["decision"])

    def test_a_malformed_answer_cannot_invert_a_verifiers_reject(self) -> None:
        """Requirement 2, and the worst member of the class.

        A response the adapter cannot parse used to be written down as
        `{schema_version, error}` **at the verifier's pathname**. A reader who
        went looking for the REJECT found a note that something had gone wrong.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = self._laid_out(Path(raw))
            self.assertEqual(
                cli.NEEDS_ACTION, cli.run([str(directory), "--no-render"]),
                "the first run must stop and ask for the verification review")
            before = self._seed_verifier_report(directory)

            # An answer missing every required key: the adapter raises, and the
            # runner writes the failure down rather than losing it.
            (directory / "reviews" / "verification_response.json").write_text(
                json.dumps({"note": "not a review at all"}), encoding="utf-8")

            self.assertNotEqual(0, cli.run([str(directory), "--no-render"]),
                                "a malformed review must not report success")

            self.assertEqual(
                before, (directory / "verification_report.json").read_bytes(),
                "a parse failure replaced a verifier's REJECT with an error "
                "stub -- the verdict inversion this slice exists to close")

            diagnostic = directory / B.VERIFICATION_ERROR
            self.assertTrue(diagnostic.is_file(),
                            "the failure still has to be written down; a run "
                            "that leaves no diagnostic leaves no reason")
            parsed = json.loads(diagnostic.read_text(encoding="utf-8"))
            self.assertIn("error", parsed)
            self.assertNotIn("decision", parsed,
                             "a diagnostic must not carry a verdict")

            self.assertFalse(
                (directory / B.PIPELINE_VERIFICATION_RECEIPT).is_file(),
                "a review that never parsed must not leave a receipt either")
            self.assertFalse(
                (directory / "final_status.json").is_file(),
                "a malformed review must not produce a final status")


class AMalformedAnswerCannotLeaveAnOlderPassStandingTest(unittest.TestCase):
    """**The hole that separating the files opened, and the review caught.**

    The old code wrote the error stub over the receipt. That destroyed a
    verifier's report, which is why it had to stop -- but it also, incidentally,
    destroyed the stale `PASS`. Writing the diagnostic to its own name fixed the
    first and lost the second: nothing had moved, so nothing was stale, and an
    unchanged `PASS` went on supporting `VERIFIED` after an answer that could not
    be read. A fail-open, and worse than the destruction it replaced, because a
    job that quietly stays `VERIFIED` is one nobody re-examines.

    The repair shadows rather than deletes. `bindings.broken` holds the receipt
    stale while the diagnostic exists, and staleness already cascades through
    `depends_on`, so `final_status.json` stops being current without a second
    mechanism. Nothing is removed, which is what lets the legacy pathname -- read
    only, never deleted -- be covered by the same rule.
    """

    @staticmethod
    def _malformed(directory: Path) -> None:
        (directory / "reviews" / "verification_response.json").write_text(
            json.dumps({"note": "not a review at all"}), encoding="utf-8")

    def test_a_current_pass_stops_being_current(self) -> None:
        """Requirement: current PASS -> malformed must stop reporting VERIFIED."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _verified(Path(raw))
            self.assertEqual("VERIFIED", _status(directory)["final_status"])

            self._malformed(directory)
            self.assertNotEqual(0, cli.run([str(directory), "--no-render"]))

            self.assertNotEqual(
                "VERIFIED", _status(directory)["final_status"],
                "an answer that could not be read left the job claiming it was "
                "verified")

    def test_the_receipt_and_the_status_are_both_reported_stale(self) -> None:
        """The cascade, named: the receipt is shadowed and the status that rests
        on it goes with it."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _verified(Path(raw))
            self._malformed(directory)
            cli.run([str(directory), "--no-render"])

            stale = B.broken(directory)
            self.assertIn(B.PIPELINE_VERIFICATION_RECEIPT, stale)
            self.assertIn("final_status.json", stale)

    def test_a_legacy_pass_stops_being_current_and_survives_on_disk(self) -> None:
        """Requirement: legacy PASS -> malformed, without deleting the legacy
        pathname. Compatibility is read-only, so the shadow has to do the work."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _verified(Path(raw))
            receipt = directory / B.PIPELINE_VERIFICATION_RECEIPT
            legacy = directory / "verification_report.json"
            legacy.write_bytes(receipt.read_bytes())
            receipt.unlink()
            before = legacy.read_bytes()
            self.assertIn(B.PIPELINE_VERIFICATION_RECEIPT,
                          [r.name for r in B.RECEIPTS])

            self._malformed(directory)
            cli.run([str(directory), "--no-render"])

            self.assertIn(B.PIPELINE_VERIFICATION_RECEIPT, B.broken(directory),
                          "the legacy receipt was not shadowed")
            self.assertTrue(legacy.is_file(), "the legacy pathname was deleted")
            self.assertEqual(before, legacy.read_bytes())

    def test_the_diagnostic_records_what_it_superseded(self) -> None:
        """A superseded pass must be neither current nor erased."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _verified(Path(raw))
            was = S.sha256_file(directory / B.PIPELINE_VERIFICATION_RECEIPT)
            self._malformed(directory)
            cli.run([str(directory), "--no-render"])

            diagnostic = json.loads(
                (directory / B.VERIFICATION_ERROR).read_text(encoding="utf-8"))
            self.assertEqual(
                was, diagnostic["superseded"][B.PIPELINE_VERIFICATION_RECEIPT])

    def test_a_first_ever_malformed_answer_supersedes_nothing(self) -> None:
        """**The control.** With no prior pass there is nothing to shadow, and
        the row above must not be passing merely because the diagnostic always
        claims to supersede something."""
        with tempfile.TemporaryDirectory() as raw:
            directory = self._laid_out_awaiting_review(Path(raw))
            self._malformed(directory)
            cli.run([str(directory), "--no-render"])

            diagnostic = json.loads(
                (directory / B.VERIFICATION_ERROR).read_text(encoding="utf-8"))
            self.assertNotIn(B.PIPELINE_VERIFICATION_RECEIPT,
                             diagnostic["superseded"])

    def test_a_later_valid_answer_clears_the_diagnostic(self) -> None:
        """Otherwise a verification that just succeeded would report as
        superseded by the failure it replaced."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _verified(Path(raw))
            self._malformed(directory)
            cli.run([str(directory), "--no-render"])
            self.assertTrue((directory / B.VERIFICATION_ERROR).is_file())

            _answer(directory)
            self.assertEqual(0, cli.run([str(directory), "--no-render"]))

            self.assertFalse((directory / B.VERIFICATION_ERROR).is_file())
            self.assertNotIn(B.PIPELINE_VERIFICATION_RECEIPT, B.broken(directory))
            self.assertEqual("VERIFIED", _status(directory)["final_status"])

    @staticmethod
    def _laid_out_awaiting_review(root: Path) -> Path:
        directory = _laid_out_authored(root)
        _author(directory, "block", **BLOCK)
        assert cli.run([str(directory), "--no-render"]) == cli.NEEDS_ACTION
        return directory


if __name__ == "__main__":
    unittest.main()
