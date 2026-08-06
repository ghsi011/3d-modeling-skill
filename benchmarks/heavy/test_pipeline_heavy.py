#!/usr/bin/env python3
"""L0-heavy — the half of
`skills/3d-modeling/scripts/pipeline/test_pipeline.py`
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

# `__file__` is under benchmarks/heavy now; what the moved code reaches through
# it is not. Named from the repository root rather than by a different count of
# `.parent`, because a count is what breaks silently on the next move.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO_ROOT / "skills" / "3d-modeling" / "scripts"

# The fixtures this half shares with the half that stayed behind,
# imported rather than copied: two spellings of one fixture is how
# two tiers stop testing the same thing.
from pipeline import runner  # noqa: E402
from pipeline.test_pipeline import (  # noqa: E402
    CLIP,
    RING,
    TEST_MATERIAL,
    TEST_NOZZLE,
    TEST_ORIENTATION,
    TEST_PRINTER,
    _clean_clip,
    _contract,
    _full_request,
    _good_verification_response,
    _looked_at,
    _measure,
    _run,
    _run_looked,
)


class VerticalSliceTest(unittest.TestCase):
    def test_a_clean_trimesh_job_runs_end_to_end_with_no_llm_calls(self) -> None:
        """Zero dispatches, and it finishes -- because the broad screen is
        calibrated. If it were not, the same job would stop at
        NEEDS_MORE_EVIDENCE and say nobody had looked; that behaviour has its own
        test in CalibrationTest."""
        from pipeline import screening as S

        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result = _run(out)

            self.assertEqual(0, result.llm_calls)
            self.assertEqual("PASS", json.loads(
                (out / "commission_report.json").read_text(encoding="utf-8"))["verdict"])
            if S.CALIBRATED:
                self.assertTrue(result.ok, result.message)
                self.assertEqual("COMMISSIONED", result.final_status["final_status"])
            else:
                self.assertEqual("NEEDS_MORE_EVIDENCE",
                                 result.final_status["final_status"])
            for name in ("intent_manifest", "model_contract", "artifact_manifest",
                         "commission_report", "final_status"):
                self.assertIn(name, result.artifacts, f"missing {name}")
            for name in ("intent_manifest", "model_contract", "artifact_manifest",
                         "commission_report", "final_status"):
                self.assertIn(name, result.artifacts, f"missing {name}")

    def test_the_stl_is_loaded_exactly_once(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result = _run(out)
            report = json.loads((out / "commission_report.json").read_text(encoding="utf-8"))
            self.assertEqual(1, report["mesh_loads"])
            _ = result

    def test_a_trimesh_job_never_imports_build123d(self) -> None:
        """10.7 s against 1.5 s measured. A trimesh-only job that loaded the CAD
        kernel would spend seven times its own build time on an import it never
        calls."""
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            (out / "brief.md").write_text("clip\n", encoding="utf-8")
            (out / "job.json").write_text(json.dumps({
                "job_id": "t", "template": "c_clip", "consequence": "INCONSEQUENTIAL",
                "parameters": CLIP, "updated_utc": "1970-01-01T00:00:00Z",
                "printer": TEST_PRINTER, "material": TEST_MATERIAL,
                "nozzle": TEST_NOZZLE, "orientation": TEST_ORIENTATION}),
                                       encoding="utf-8")
            probe = (
                "import sys, runpy;"
                "sys.argv=['design-tool','run-job',%r,'--no-render'];"
                "import pipeline.cli as c;"
                "code=c.main(sys.argv[1:]);"
                "print('BUILD123D_LOADED', 'build123d' in sys.modules)" % str(out))
            done = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                                  text=True, cwd=str(_SCRIPTS))
            self.assertIn("BUILD123D_LOADED False", done.stdout, done.stdout + done.stderr)

    def test_step_is_written_only_when_the_contract_asks(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            _run(out, template="trim_ring", params=RING)
            self.assertFalse((out / "candidate.step").exists(),
                             "STEP must not appear unrequested")

        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result = _run_looked(out, template="trim_ring", params=RING, step=True)
            self.assertTrue((out / "candidate.step").is_file())
            self.assertEqual("NEEDS_MORE_EVIDENCE", result.final_status["final_status"])

    def test_a_trimesh_template_refuses_a_step_it_cannot_produce(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result = _run(Path(raw), step=True)
            self.assertFalse(result.ok)
            self.assertEqual("build", result.stage)
            self.assertIn("STL only", result.message)

class CalibrationTest(unittest.TestCase):
    """The gate the plan calls hard, kept honest by re-measuring it.

    `screening.CALIBRATED` is a claim about measured performance. A boolean that
    somebody set by hand decays the moment a detector changes, so the flag is
    only allowed to be True while this test can still reproduce the numbers
    behind it.
    """

    def test_the_corpus_measures_screening_and_not_the_pipeline(self) -> None:
        """The rate that decides the gate must be screening's own.

        It was computed from `caught_by_contract or caught_by_screening`, so it
        reported 0.0 while the screen itself missed 46.7% of added material --
        and contract checks are conditioned on declared features, which is
        exactly why they are not the broad evidence this gate is about.
        """
        from pipeline import corpus

        report = corpus.run(corpus._default_templates())
        added = report["per_class"]["added-material"]

        # Separately computed, not separately named. The screen's rate is scored
        # on fused mutants only; the pipeline's counts every mutant and every
        # instrument. They may agree when both are clean -- what must hold is
        # that the gate reads the screen's.
        self.assertIn("pipeline_false_negative_rate", added)
        self.assertIn("screening_false_negative_rate", added)
        self.assertEqual(report["screening_false_negative_rate"],
                         added["screening_false_negative_rate"])
        self.assertLessEqual(added["fused_mutants"], added["mutants"])

    def test_screening_is_scored_only_on_defects_it_could_see(self) -> None:
        """A disconnected solid is debris whatever class it was filed under, and
        the component detector sees it for free."""
        from pipeline import corpus

        report = corpus.run(corpus._default_templates())
        added = report["per_class"]["added-material"]
        self.assertLess(added["fused_mutants"], added["mutants"],
                        "the corpus should contain both fused and separate defects")

    def test_the_flag_matches_the_measurement(self) -> None:
        """A stale True is worse than a False: it licenses dropping the look on a
        screen nobody has checked."""
        from pipeline import corpus, screening as S

        gate = corpus.run(corpus._default_templates())["gate"]
        self.assertEqual(S.CALIBRATED, gate == "PASS",
                         f"CALIBRATED={S.CALIBRATED} while the corpus gate is {gate}")

    def test_an_uncalibrated_screen_stops_a_job_nobody_looked_at(self) -> None:
        """The plan calls this a hard gate. It has to move the status, or it is a
        string: an earlier version only edited the claim text, so flipping the
        flag changed nothing about what shipped."""
        from pipeline import screening as S

        if S.CALIBRATED:
            self.skipTest("screening is calibrated; the gate does not apply")
        with tempfile.TemporaryDirectory() as raw:
            result = _run(Path(raw))
            self.assertEqual("NEEDS_MORE_EVIDENCE",
                             result.final_status["final_status"])
        with tempfile.TemporaryDirectory() as raw:
            looked = _run(Path(raw), verify_call=_looked_at,
                          reviewer={"model_snapshot": "test"})
            self.assertEqual("NEEDS_MORE_EVIDENCE", looked.final_status["final_status"])

    def test_the_status_reports_the_calibration_state(self) -> None:
        from pipeline import screening as S

        with tempfile.TemporaryDirectory() as raw:
            final = _run(Path(raw)).final_status
            self.assertEqual(S.CALIBRATED, final["screening_calibrated"])

    def test_screening_never_claims_to_prove_absence(self) -> None:
        """Calibration measures what the screens catch. It does not widen what
        they are for -- a missing feature stays the contract's job, and the
        calibration note must not read as though passing changed that."""
        from pipeline import screening as S

        self.assertIn("cannot prove", S.__doc__)
        self.assertIn("cannot prove", S.CALIBRATION_NOTE)
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            _, _, screen = _measure(_clean_clip(), _contract(tmp), tmp)
            self.assertIn("cannot prove", screen["note"])


class ReviewEnvelopeRenderTest(unittest.TestCase):
    """The one `ReviewEnvelopeTest` case that asks the renderer for images.

    It is here for the tier's own reason and not because it is slow. The render
    path answers in the parent process on Windows, and never does on Linux:
    `preview` selects the EGL platform there, PyOpenGL resolves the library
    through `ctypes.util.find_library`, and that shells out to `ldconfig` --
    whether or not the library is present, so no machine escapes it by having
    EGL installed. The rest of the class stayed in the commit gate.

    What the case still proves where the renderer is missing: `witness` records
    a failed import as `renderer="unavailable: ..."` with no images, which is a
    different witness record from the `"none"` of a job that never asked. The
    envelope binds that record either way, so the stale answer is refused for
    the reason the test names rather than by accident.
    """

    def test_stale_verification_response_after_render_change_is_rejected(self) -> None:
        """Changing whether images are rendered changes the witness record, so
        an answer from the other setting must not be accepted."""
        response = _good_verification_response()
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            seen = []
            def capture(packet):
                seen.append(packet)
                return {**response, "review_envelope": packet.payload["review_envelope"]}
            runner.run(_full_request(out, verify_call=capture,
                                     reviewer={"model_snapshot": "test"}))
            stale = seen[0].payload["review_envelope"]
            result = runner.run(_full_request(
                out, render=True,
                verify_call=lambda p: {**response, "review_envelope": stale},
                reviewer={"model_snapshot": "test"}))
            self.assertFalse(result.ok)
            self.assertEqual("verification", result.stage)
