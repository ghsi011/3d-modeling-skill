#!/usr/bin/env python3
"""D37: the pipeline's review record was squatting on the verifier's report.

`verification_report.json` is a team contract owned by the verifier alone --
`CANONICAL_FILENAMES` names it, `CONTRACT_KIND_BY_KEY` gives it
`contract: verification-report`, and `_EXPECTED_OWNERS` lists `{verifier}` and
nothing else. The pipeline wrote two entirely different objects to that path.

**The two are different in kind, and only one of them merely loses work.**

The success path writes the pipeline's own normalized review receipt --
`evidence_packet_sha256`, `review_envelope`, `reviewed_questions`, `decision`.
That is a genuine review record wearing someone else's name.

The exception path writes `{schema_version, error}` when the adapter's answer
will not parse. Sent to the canonical pathname it replaces a verifier's REJECT
with a note that parsing failed -- which does not lose a verdict so much as
**invert** one, turning "a person found a defect" into "something went wrong".
Of this whole defect class that is the worst member.

So: two renames rather than one. The receipt gets `PIPELINE_VERIFICATION_RECEIPT`
because two schemas were sharing a filename; the diagnostic gets
`VERIFICATION_ERROR` because it is neither a report nor a receipt, and declaring
the pipeline a co-owner of the verifier's contract would have formalised the
collision instead of repairing it.

`_EXPECTED_OWNERS["verification_report"]` is unchanged and must stay `{verifier}`.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from . import bindings as B

# A verifier's real team report, trimmed to the fields that decide identity.
# `contract` is the marker the compatibility predicate keys on; the REJECT and
# the defect are what a destructive write would silently throw away.
TEAM_REPORT = {
    "contract": "verification-report",
    "contract_version": 4,
    "job_id": "the-verifier-wrote-this",
    "revision": 1,
    "owner": "verifier",
    "status": "REJECT",
    "candidate_id": "candidate-01",
    "fresh_context": True,
    "updated_utc": "1970-01-01T00:00:00Z",
    "defects": [{"summary": "wall 0.6 mm below the declared minimum"}],
}
TEAM_FILE = "verification_report.json"

# The pipeline's former receipt, as `verification.run` actually returned it.
LEGACY_RECEIPT = {
    "schema_version": 3,
    "evidence_packet_sha256": "a" * 64,
    "reviewer": {"fresh_context": True},
    "review_envelope": {"contract_sha256": "b" * 64},
    "reviewed_questions": ["q1", "q2"],
    "decision": "PASS",
    "defects": [],
}

# The malformed-response diagnostic, exactly as the runner writes it.
ERROR_STUB = {"schema_version": 3, "error": "SchemaError: unparseable"}

# Named here so the disguised-contract row can assert its own fixture is strong
# enough, rather than trusting that it happens to carry the right keys.
_VERIFICATION_SHAPE_KEYS = frozenset({
    "schema_version", "evidence_packet_sha256", "reviewed_questions",
})


def _seed(work: Path, name: str, payload: dict) -> bytes:
    path = work / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path.read_bytes()


class TheReceiptAndTheDiagnosticHaveTheirOwnNamesTest(unittest.TestCase):
    """**The renames themselves, asserted where a reader can check them.**"""

    def test_neither_new_name_is_the_team_contract(self) -> None:
        self.assertNotEqual(TEAM_FILE, B.PIPELINE_VERIFICATION_RECEIPT)
        self.assertNotEqual(TEAM_FILE, B.VERIFICATION_ERROR)

    def test_the_receipt_and_the_diagnostic_are_not_each_other(self) -> None:
        """The diagnostic cannot support a verification claim, so it cannot
        share a name with the object that does."""
        self.assertNotEqual(B.PIPELINE_VERIFICATION_RECEIPT, B.VERIFICATION_ERROR)

    def test_neither_new_name_collides_with_any_role_owned_canonical_name(self) -> None:
        from team_tools import validators as V
        canonical = {name for names in V.CANONICAL_FILENAMES.values() for name in names}
        self.assertNotIn(B.PIPELINE_VERIFICATION_RECEIPT, canonical)
        self.assertNotIn(B.VERIFICATION_ERROR, canonical)

    def test_the_team_contract_is_no_longer_a_pipeline_receipt(self) -> None:
        self.assertNotIn(TEAM_FILE, [r.name for r in B.RECEIPTS])
        self.assertNotIn(TEAM_FILE, B.REMOVABLE)

    def test_the_receipt_is_a_receipt_and_the_diagnostic_is_not(self) -> None:
        """Requirement 10. The diagnostic must never enter a binding role: its
        existence is not evidence that a verification happened."""
        names = [r.name for r in B.RECEIPTS]
        self.assertIn(B.PIPELINE_VERIFICATION_RECEIPT, names)
        self.assertNotIn(B.VERIFICATION_ERROR, names)
        self.assertNotIn(B.VERIFICATION_ERROR, B.REMOVABLE)

    def test_the_verifier_remains_the_sole_declared_owner(self) -> None:
        """Requirement 9. (b) was chosen over co-ownership precisely so this
        stays true; adding `pipeline` here would formalise the collision."""
        from team_tools import validators as V
        self.assertEqual(frozenset({"verifier"}),
                         V._EXPECTED_OWNERS["verification_report"])


class TheLegacyReceiptIsStillReadableTest(unittest.TestCase):
    """**Compatibility, built in from the first version rather than after a
    second project goes stale.** A project completed before D37 has its receipt
    under the old name, and must not read as stale merely because the software
    was upgraded."""

    def test_a_legacy_pipeline_receipt_is_recognised(self) -> None:
        """Requirement 5."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            _seed(work, TEAM_FILE, LEGACY_RECEIPT)
            self.assertEqual(
                work / TEAM_FILE,
                B._receipt_path(work, B.PIPELINE_VERIFICATION_RECEIPT))

    def test_a_genuine_team_report_cannot_masquerade_as_the_receipt(self) -> None:
        """Requirement 6, and the half that matters. A verifier's report sits at
        that path *by right*; a fallback keyed on the filename -- or on the
        pipeline keys alone -- would let it stand in for a receipt the pipeline
        never wrote."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            _seed(work, TEAM_FILE, TEAM_REPORT)
            self.assertEqual(
                work / B.PIPELINE_VERIFICATION_RECEIPT,
                B._receipt_path(work, B.PIPELINE_VERIFICATION_RECEIPT))

    def test_the_contract_marker_alone_disqualifies_a_team_report(self) -> None:
        """Requirement 6, tested so that it can actually fail.

        The obvious negative control -- a plain team report -- is rejected by the
        *shape* half all on its own, because a verifier's contract carries none
        of the pipeline's keys. So it never exercises the `contract` marker, and
        a mutation deleting that half leaves every other row green. This one
        gives the payload the full pipeline shape **and** the marker, so the
        marker is the only thing standing between it and the fallback.

        That is the guard that matters if a future contract revision ever grows a
        `schema_version`: the file says what it is, and what it says wins.
        """
        disguised = {**TEAM_REPORT, **LEGACY_RECEIPT, "contract": "verification-report"}
        self.assertTrue(_VERIFICATION_SHAPE_KEYS <= set(disguised),
                        "the fixture must carry the pipeline shape, or this row "
                        "is the weaker one it exists to replace")
        self.assertFalse(B._is_legacy_verification_receipt(disguised))
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            _seed(work, TEAM_FILE, disguised)
            self.assertEqual(
                work / B.PIPELINE_VERIFICATION_RECEIPT,
                B._receipt_path(work, B.PIPELINE_VERIFICATION_RECEIPT))

    def test_the_error_stub_cannot_masquerade_as_the_receipt(self) -> None:
        """Requirement 8, the verdict-inversion guard. `{schema_version, error}`
        carries neither `evidence_packet_sha256` nor `reviewed_questions`, so it
        fails the predicate by construction -- which is the design, not luck."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            _seed(work, TEAM_FILE, ERROR_STUB)
            self.assertEqual(
                work / B.PIPELINE_VERIFICATION_RECEIPT,
                B._receipt_path(work, B.PIPELINE_VERIFICATION_RECEIPT))

    def test_the_new_receipt_wins_wherever_both_exist(self) -> None:
        """Requirement 7. Compatibility can never override present authority."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            _seed(work, TEAM_FILE, LEGACY_RECEIPT)
            _seed(work, B.PIPELINE_VERIFICATION_RECEIPT,
                  {**LEGACY_RECEIPT, "decision": "REJECT"})
            self.assertEqual(
                work / B.PIPELINE_VERIFICATION_RECEIPT,
                B._receipt_path(work, B.PIPELINE_VERIFICATION_RECEIPT))
            self.assertEqual(
                "REJECT",
                B._receipt_payload(work, B.PIPELINE_VERIFICATION_RECEIPT)["decision"])

    def test_compatibility_is_read_only(self) -> None:
        """Requirement 3. `invalidate` resolves through `receipt.name`, never
        through `_receipt_path`, so the compatibility reader cannot acquire
        deletion authority over a file the verifier owns."""
        self.assertNotIn(TEAM_FILE, B.REMOVABLE)
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            before = _seed(work, TEAM_FILE, LEGACY_RECEIPT)
            # Nothing else on disk, so every receipt's bindings are broken and
            # `invalidate` sweeps everything it is entitled to sweep. It deletes
            # `work_dir / receipt.name` (bindings.py:620) rather than resolving
            # through `_receipt_path`, which is the whole reason the legacy file
            # is safe -- and this row fails if that ever changes.
            B.invalidate(work)
            self.assertTrue((work / TEAM_FILE).is_file(),
                            "a legacy receipt is read, never swept")
            self.assertEqual(before, (work / TEAM_FILE).read_bytes())

    def test_the_predicate_reads_the_two_real_schemas(self) -> None:
        """The discriminator frozen against what each object actually contains,
        so a re-shaped schema breaks this row rather than silently widening the
        fallback."""
        self.assertTrue(B._is_legacy_verification_receipt(LEGACY_RECEIPT))
        self.assertFalse(B._is_legacy_verification_receipt(TEAM_REPORT))
        self.assertFalse(B._is_legacy_verification_receipt(ERROR_STUB))


class TheLifecycleStillOwnsThePipelinesOwnReceiptTest(unittest.TestCase):
    """**The rename must not cost the lifecycle its grip.** Protecting the team
    contract is only half the fix; a receipt nothing may invalidate is a receipt
    that can go quietly stale."""

    def test_the_pipeline_receipt_is_removable(self) -> None:
        """Requirement 4."""
        self.assertIn(B.PIPELINE_VERIFICATION_RECEIPT, B.REMOVABLE)

    def test_it_still_depends_on_the_commission_report(self) -> None:
        row = next(r for r in B.RECEIPTS
                   if r.name == B.PIPELINE_VERIFICATION_RECEIPT)
        self.assertIn("commission_report.json", row.depends_on({}))

    def test_a_status_that_recorded_a_verification_depends_on_the_receipt(self) -> None:
        """`_status_depends` reads the decision off the status rather than
        assuming one, so the edge must name the new file."""
        self.assertIn(B.PIPELINE_VERIFICATION_RECEIPT,
                      B._status_depends({"verification": {"decision": "PASS"}}))
        self.assertNotIn(B.PIPELINE_VERIFICATION_RECEIPT,
                         B._status_depends({}))


if __name__ == "__main__":
    unittest.main()
