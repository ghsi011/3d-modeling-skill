"""Tests for `dt.py direct` — the whole no-dispatch route in one call.

The command exists because measurement said the cost of this route is turns, not
work: 5.1 seconds of computation inside a run that took 13.5 minutes. So the
tests hold it to the two things that makes it worth having — it must produce
everything the four commands produced, and it must not paper over a failure to
do it, because a chain that continues past a broken link writes receipts
describing a part that was never built.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from . import direct

_CLIP = ["bore_d=12.0", "wall=3.0", "height=9.0", "mouth_gap=9.0",
         "flange=(40.0, 22.0, 5.0)", "screw_d=4.5", "screw_at=(8.0, 11.0)",
         "countersink_d=9.0"]


def _needs_kernel(test):
    try:
        import manifold3d  # noqa: F401
        import trimesh  # noqa: F401
    except ImportError:
        return unittest.skip("needs trimesh + manifold3d")(test)
    return test


def _argv(out: Path, params=None, *extra):
    argv = ["--job-id", "one", "--template", "c_clip"]
    for text in (params if params is not None else _CLIP):
        argv += ["--param", text]
    return argv + ["--bbox", "40", "22", "14", "--updated-utc", "1970-01-01T00:00:00Z",
                   "--out", str(out), "--no-render", *extra]


@_needs_kernel
class TestDirect(unittest.TestCase):
    def test_one_call_produces_the_whole_job(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)

            self.assertEqual(0, direct.main(_argv(out)))

            for name in ("job_state.md", "dimensions.md", "print_plan_checks.json",
                         "model.py", "candidate-01.stl", "commission.json",
                         "artifact_manifest.json", "candidate_readiness.md"):
                self.assertTrue((out / name).is_file(), f"missing {name}")

    def test_the_gate_still_decides(self) -> None:
        """Collapsing four commands must not soften the one that can say no."""
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            direct.main(_argv(out))

            payload = json.loads((out / "commission.json").read_text(encoding="utf-8"))
            self.assertEqual("PASS", payload["verdict"])
            self.assertIn("feature-screw", [c["id"] for c in payload["checks"]])

    def test_the_judgments_arrive_as_arguments_or_stay_demanded(self) -> None:
        """Passing them in is not a shortcut past the decision -- it is the same
        decision, delivered without spending edit turns on a file written a
        second earlier. Omit them and they must still be demanded."""
        from . import intake as intake_module

        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            direct.main(_argv(out) + ["--rationale", "a dropped cable is inconvenience",
                                      "--acceptance", "nothing: the mouth gap is chosen"])
            job = (out / "job_state.md").read_text(encoding="utf-8")
            self.assertIn("a dropped cable is inconvenience", job)
            self.assertNotIn(intake_module.REQUIRED, job)

        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            direct.main(_argv(out))
            job = (out / "job_state.md").read_text(encoding="utf-8")
            self.assertIn(intake_module.REQUIRED, job)

    def test_a_bad_parameter_stops_before_anything_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)

            code = direct.main(_argv(out, ["bore_d=12.0"]))

            self.assertNotEqual(0, code)
            self.assertFalse((out / "candidate-01.stl").exists(),
                             "a chain that continues past a broken link writes receipts "
                             "for a part that was never built")

    def test_an_envelope_the_part_misses_fails_the_run(self) -> None:
        """The bbox comes from the brief, not the geometry, so a template whose
        output disagrees with it has to be caught here."""
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            argv = [a if a != "22" else "30" for a in _argv(out)]

            self.assertNotEqual(0, direct.main(argv))

    def test_it_refuses_the_classes_that_need_a_reviewer(self) -> None:
        """R2 and above need a named reviewer and independent verification, and
        this route provides neither."""
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(SystemExit):
                direct.main(_argv(Path(raw)) + ["--risk", "R2_ENGINEERING_REVIEW"])


if __name__ == "__main__":
    unittest.main()
