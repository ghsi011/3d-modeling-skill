#!/usr/bin/env python3
"""L0-heavy — the half of
`skills/3d-modeling/scripts/pipeline/test_frozen.py`
that costs a child interpreter.

The repository-root `conftest.py` refuses a child interpreter inside the commit
gate, and these classes start one. Same tests, moved rather than weakened;
`benchmarks/heavy/README.md` records the profile that decided the seam and what
runs this tier. What stayed behind is what answers in the parent process.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from pipeline import runner, selftest

# The fixtures this half shares with the half that stayed behind,
# imported rather than copied: two spellings of one fixture is how
# two tiers stop testing the same thing.
from pipeline.test_frozen import (  # noqa: E402
    FROZEN_ARTIFACTS,
    FROZEN_CONTRACTS,
    FROZEN_PARAMETERS,
    _passing_review,
    _request,
    _spec,
)


class FrozenRunTest(unittest.TestCase):
    """End-to-end receipts, per route, as they stand before the consolidation."""

    def _run_direct(self, out: Path, template: str = "c_clip"):
        return runner.run(_request(out, template, verify_call=_passing_review,
                                   reviewer={"model_snapshot": "frozen"}))

    def test_direct_writes_its_frozen_receipt_set_and_claim(self) -> None:
        """A clean certified DIRECT job stops at NEEDS_MORE_EVIDENCE today.

        This is the shipped behaviour, and it is not what `SKILL.md` and the
        orchestrator charter describe -- both present `COMMISSIONED` as the
        ordinary DIRECT outcome. The gap is `screening.calibrated`, which the
        corpus flipped back to `False` when it was re-measured on mutants that
        were actually fused to the part. `status.decide` then refuses to call a
        part commissioned when the broad screen is uncalibrated *and* nobody
        independent looked -- and DIRECT, by its own route trade, has no
        independent look.

        Frozen rather than fixed: the two ways to make this say COMMISSIONED are
        to earn the calibration or to weaken the threshold, and weakening a
        threshold after observing the candidate is exactly what the scope
        controls forbid. The consolidation must not change this by accident.
        """
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result = self._run_direct(out)
            self.assertEqual(FROZEN_ARTIFACTS["DIRECT"], set(result.artifacts))
            final = result.final_status
            self.assertEqual("DIRECT", final["route"])
            self.assertEqual("PASS", final["commission_verdict"])
            self.assertEqual("CLEAR", final["screening"])
            self.assertFalse(final["screening_calibrated"])
            self.assertEqual("NEEDS_MORE_EVIDENCE", final["final_status"])
            self.assertIsNone(final["verification"],
                              "DIRECT has no independent verification dispatch; a "
                              "verifier supplied to a DIRECT job must stay unused")
            self.assertEqual(0, result.llm_calls)

    def test_direct_on_the_build123d_path_is_the_same_shape(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result = self._run_direct(out, "trim_ring")
            self.assertEqual(FROZEN_ARTIFACTS["DIRECT"], set(result.artifacts))
            self.assertEqual("PASS", result.final_status["commission_verdict"])
            self.assertEqual("build123d", result.final_status["backend"])

    def test_two_direct_runs_write_byte_identical_receipts(self) -> None:
        """Same job, same timestamp, same bytes -- or the hashes mean nothing.

        `timings.json` is excluded on purpose: durations are not part of any
        artifact's identity and the runner says so in the file itself.
        """
        hashed = ("intent_manifest.json", "model_contract.json",
                  "artifact_manifest.json", "commission_report.json",
                  "final_status.json")
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            first, second = Path(a), Path(b)
            self._run_direct(first)
            self._run_direct(second)
            for name in hashed:
                with self.subTest(artifact=name):
                    self.assertEqual((first / name).read_text(encoding="utf-8"),
                                     (second / name).read_text(encoding="utf-8"))

    def test_fitted_costs_one_spec_call_and_records_the_route(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result = runner.run(_request(
                out, "c_clip", external_geometry=True, spec_call=_spec,
                verify_call=_passing_review, reviewer={"model_snapshot": "frozen"},
                interface_map={"channel": "bore_d"}))
            self.assertTrue(result.ok, result.message)
            self.assertEqual(FROZEN_ARTIFACTS["FITTED"], set(result.artifacts))
            self.assertEqual("FITTED", result.final_status["route"])
            self.assertEqual(2, result.llm_calls)

    def test_full_costs_a_spec_and_a_verification_call(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            params = {**FROZEN_PARAMETERS["c_clip"], "bore_d": 60.0}
            result = runner.run(_request(
                out, "c_clip", params=params, spec_call=_spec,
                verify_call=_passing_review, reviewer={"model_snapshot": "frozen"},
                interface_map={"channel": "bore_d"}))
            self.assertTrue(result.ok, result.message)
            self.assertEqual(FROZEN_ARTIFACTS["FULL"], set(result.artifacts))
            self.assertEqual("FULL", result.final_status["route"])
            self.assertEqual("VERIFIED", result.final_status["final_status"])
            self.assertEqual(2, result.llm_calls)

    def test_a_consequential_direct_job_still_needs_its_safety_pass(self) -> None:
        """The one review DIRECT cannot route around."""
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result = runner.run(_request(out, "c_clip", consequence="CONSEQUENTIAL"))
            self.assertFalse(result.ok)
            self.assertEqual("safety", result.stage)

    def test_the_final_status_claim_never_outruns_the_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            self._run_direct(out)
            final = json.loads((out / "final_status.json").read_text(encoding="utf-8"))
            self.assertEqual("NEEDS_MORE_EVIDENCE", final["final_status"])
            self.assertIn("nobody independent looked", final["allowed_claim"])
            self.assertNotIn("independently verified", final["allowed_claim"])

class ShippedSelftestTest(unittest.TestCase):
    """The smoke set an installed bundle can run, run here too.

    A self-test that only ever executes on somebody else's machine is a
    self-test nobody has seen fail.
    """

    def test_the_shipped_smoke_set_passes_on_this_installation(self) -> None:
        report = selftest.run()
        failures = [c for c in report["cases"] if not c["ok"]]
        self.assertTrue(report["ok"], failures)
        self.assertEqual(report["ran"], len(FROZEN_CONTRACTS) * 2 + 1)

    def test_quick_mode_builds_no_geometry(self) -> None:
        report = selftest.run(quick=True)
        self.assertTrue(report["ok"], [c for c in report["cases"] if not c["ok"]])
        self.assertFalse([c for c in report["cases"] if c["check"].startswith("build:")])

    def test_a_moved_contract_hash_is_reported_rather_than_absorbed(self) -> None:
        original = dict(selftest.FROZEN_CONTRACTS["c_clip"])
        selftest.FROZEN_CONTRACTS["c_clip"] = {**original, "contract_sha256": "0" * 64}
        try:
            report = selftest.run(quick=True)
        finally:
            selftest.FROZEN_CONTRACTS["c_clip"] = original
        self.assertFalse(report["ok"])
        self.assertEqual(1, report["failed"])
