"""Tests for the verification-report draft.

The property under test is what the draft REFUSES to fill in. Transcribing a
measurement is safe; pre-filling a verdict, a visual observation or an upstream
audit would turn the draft into the finding, which is the one thing a
verification cannot borrow.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from designer_toolkit import report  # noqa: E402

_WHEN = "2026-01-01T00:00:00Z"


def _commission(**overrides):
    payload = {
        "verdict": "PASS",
        "checks": [
            {"id": "solid", "title": "s", "result": "PASS", "detail": "watertight=True"},
            {"id": "envelope", "title": "e", "result": "PASS", "detail": "off by +0.00 mm"},
            {"id": "support-S-01", "title": "p", "result": "PASS", "detail": "0.00 mm2 past -0.73"},
            {"id": "fit", "title": "f", "result": "SKIPPED", "detail": "no interfaces"},
        ],
        "evidence": {"export": {"file_sha256": "a" * 64}},
    }
    payload.update(overrides)
    return payload


def _draft(**overrides):
    return report.build(_commission(**overrides), job_id="t", candidate_id="candidate-01",
                        revision=1, updated_utc=_WHEN)


class TranscriptionTest(unittest.TestCase):
    def test_measured_numbers_reach_the_row_that_needs_them(self) -> None:
        text = _draft()

        self.assertIn("0.00 mm2 past -0.73", text)
        self.assertIn("off by +0.00 mm", text)

    def test_the_hash_binds_the_report_to_the_artifact(self) -> None:
        self.assertIn("candidate_stl_sha256: " + "a" * 64, _draft())

    def test_a_failing_check_is_carried_as_failing(self) -> None:
        text = _draft(checks=[{"id": "envelope", "title": "e", "result": "FAIL",
                               "detail": "off by +4.00 mm"}])

        self.assertIn("off by +4.00 mm", text)
        self.assertIn("| FAIL |", text)


class RefusalTest(unittest.TestCase):
    """What the draft must never decide."""

    def test_the_verdict_is_not_prefilled(self) -> None:
        text = _draft()

        self.assertNotIn("## Verdict\nPASS", text)
        self.assertIn("<!-- REQUIRED -->", text.split("## Verdict")[1])

    def test_the_status_field_is_not_prefilled(self) -> None:
        """Even on an all-PASS recomputation. The numbers are necessary and
        never sufficient."""
        self.assertIn("status: <!-- REQUIRED -->", _draft())

    def test_every_visual_observation_is_left_empty(self) -> None:
        text = _draft()
        seven = text.split("## Seven checks")[1].split("## Defects")[0]

        for line in [ln for ln in seven.splitlines() if ln.startswith("| ")][2:]:
            with self.subTest(row=line[:34]):
                self.assertIn("<!-- REQUIRED -->", line)

    def test_the_checks_no_tool_computes_are_marked_verifier_owned(self) -> None:
        text = _draft()

        for row in ("2 full insertion/travel sweep",
                    "4 same-view/photo overlay look",
                    "5 named-datum feature positions/handedness"):
            with self.subTest(row=row):
                line = next(ln for ln in text.splitlines() if ln.startswith(f"| {row}"))
                self.assertIn("VERIFIER-OWNED", line)

    def test_the_upstream_audit_is_not_answered(self) -> None:
        audit = _draft().split("## Input/upstream audit")[1].split("## Seven checks")[0]

        self.assertIn("<!-- REQUIRED -->", audit)


class DefectScaffoldTest(unittest.TestCase):
    """The rejection half of the report, which had none.

    The charter requires a REJECT to identify defect, evidence, expected versus
    observed, severity and owning loop. The table carried no severity column, so
    the requirement was unsatisfiable in the document the tool produces, and it
    arrived empty besides -- meaning the verifier retyped numbers already sitting
    in `commission.json` two sections above.
    """

    def _defects(self, checks) -> str:
        drafted = report.build({"checks": checks, "evidence": {"export": {}}},
                               job_id="j", candidate_id="candidate-01",
                               revision=1, updated_utc="t")
        return drafted.split("## Defects")[1].split("## Verdict")[0]

    def test_the_column_the_charter_requires_exists(self) -> None:
        self.assertIn("| Severity |", self._defects([]))

    def test_a_failing_check_arrives_as_a_row_with_its_numbers_transcribed(self) -> None:
        table = self._defects([
            {"id": "envelope", "result": "FAIL", "detail": "z is +4.20 mm from the plan"},
            {"id": "watertight", "result": "PASS", "detail": "closed"}])

        self.assertIn("| envelope |", table)
        self.assertIn("z is +4.20 mm from the plan", table)
        self.assertNotIn("watertight", table, "a passing check is not a defect")

    def test_the_judgments_are_demanded_not_guessed(self) -> None:
        """Which loop owns a defect, how severe it is, and what would make it
        acceptable are not derivable from a failing check: a 0.3 mm envelope
        miss can be a rounding artefact or a wrong datum."""
        row = [line for line in self._defects(
            [{"id": "envelope", "result": "FAIL", "detail": "off by 0.3"}]).splitlines()
            if line.startswith("| D-01")][0]

        self.assertEqual(3, row.count("<!-- REQUIRED -->"))

    def test_a_passing_run_gets_no_rows(self) -> None:
        """A table of "none" entries reads as a filled-in form, and a reader who
        skims it once will skim the one that matters."""
        table = self._defects([{"id": "watertight", "result": "PASS", "detail": "closed"}])

        self.assertEqual([], [ln for ln in table.splitlines() if ln.startswith("| D-")])


class CliTest(unittest.TestCase):
    def test_it_writes_a_draft_from_a_commission_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            source = work / "commission.json"
            source.write_text(json.dumps(_commission()), encoding="utf-8")
            out = work / "verification_report.md"

            completed = subprocess.run(
                [sys.executable, "-m", "designer_toolkit.report", "--commission", str(source),
                 "--out", str(out), "--job-id", "t", "--updated-utc", _WHEN],
                cwd=_SCRIPTS, capture_output=True, text=True, check=False)

            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertIn("contract: verification-report", out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()


class PlaceholderInProseTest(unittest.TestCase):
    def test_the_marker_appears_only_in_fields_never_in_the_instructions(self) -> None:
        """"Is anything still unanswered?" is a grep for the marker, and the
        instructional sentence used to contain one -- so the answer was always
        yes, however complete the report. A verifier had to delete the sentence
        to satisfy its own completion check."""
        drafted = report.build({"checks": [], "evidence": {"export": {}}},
                               job_id="j", candidate_id="c", revision=1,
                               updated_utc="t", fresh_context="no")

        for line in drafted.splitlines():
            if report._UNSET not in line:
                continue
            before = line.split(report._UNSET)[0]
            with self.subTest(line=line[:60]):
                self.assertTrue(
                    line.startswith("|")            # a table cell to fill
                    or line.startswith(report._UNSET)  # the answer slot itself
                    or before.rstrip().endswith(":"),  # a frontmatter field
                    "a marker must be a slot to answer, never part of a sentence "
                    "explaining what the markers mean -- that sentence made "
                    "'is anything unanswered?' always true")
