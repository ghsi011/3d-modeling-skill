"""Tests for `dt.py build` -- the template instantiator.

The load-bearing one is `test_the_generated_model_passes_the_gate`: this command
exists to remove a dispatch, so what it writes has to satisfy the gate with no
human in between. A generator whose output needs hand-repair has saved nothing.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from . import build

SCRIPTS = Path(__file__).resolve().parents[1]
LAUNCHER = SCRIPTS / "dt.py"

_CLIP = [
    "--param", "bore_d=12.0", "--param", "wall=3.0", "--param", "height=9.0",
    "--param", "mouth_gap=9.0", "--param", "flange=(40.0, 22.0, 5.0)",
    "--param", "screw_d=4.5", "--param", "screw_at=(8.0, 11.0)",
    "--param", "countersink_d=9.0",
]


class TestParseParam(unittest.TestCase):
    def test_tuples_survive(self) -> None:
        """Floats-only would have covered `wall=3.0` and nothing else -- the
        templates that matter take tuples for envelopes and hole positions."""
        self.assertEqual(("flange", (40.0, 22.0, 5.0)), build.parse_param("flange=(40.0, 22.0, 5.0)"))

    def test_nothing_executable_is_accepted(self) -> None:
        with self.assertRaises(ValueError):
            build.parse_param("wall=__import__('os').getcwd()")

    def test_a_missing_equals_is_named(self) -> None:
        with self.assertRaises(ValueError):
            build.parse_param("wall 3.0")


class TestRenderModel(unittest.TestCase):
    def test_an_unknown_template_lists_the_real_ones(self) -> None:
        with self.assertRaises(ValueError) as caught:
            build.render_model("sprocket", {})
        self.assertIn("c_clip", str(caught.exception))

    def test_params_come_from_the_template_not_the_caller(self) -> None:
        """A hand-written model.py could declare `PARAMS` that disagreed with the
        solid it shipped beside; every static check then ran against fiction."""
        source = build.render_model("c_clip", {"wall": 3.0})
        self.assertIn("PARAMS = _built.params", source)
        self.assertNotIn("PARAMS = {", source)


class TestBuildCommand(unittest.TestCase):
    def test_bad_parameters_fail_here_not_in_the_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "model.py"
            code = build.main(["--template", "c_clip", "--param", "bore_d=12.0", "--out", str(out)])
            self.assertEqual(1, code)
            self.assertFalse(out.exists(), "a model that cannot build must not be left on disk")

    def test_the_generated_model_passes_the_gate(self) -> None:
        try:
            import trimesh  # noqa: F401
            import manifold3d  # noqa: F401
        except ImportError:
            self.skipTest("needs trimesh + manifold3d")
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp)
            self.assertEqual(0, subprocess.run(
                [sys.executable, str(LAUNCHER), "build", "--template", "c_clip",
                 *_CLIP, "--out", str(job / "model.py")],
                capture_output=True, check=False).returncode)
            self.assertEqual(0, subprocess.run(
                [sys.executable, str(LAUNCHER), "plan", "template", "--bbox", "40", "22", "14",
                 "--job-id", "b", "--updated-utc", "1970-01-01T00:00:00Z",
                 "--out", str(job / "print_plan_checks.json")],
                capture_output=True, check=False).returncode)

            done = subprocess.run(
                [sys.executable, str(LAUNCHER), "commission", "--model", "model.py",
                 "--plan", "print_plan_checks.json", "--out", ".", "--job-id", "b",
                 "--updated-utc", "1970-01-01T00:00:00Z", "--no-render"],
                cwd=job, capture_output=True, text=True, check=False)

            self.assertEqual(0, done.returncode, done.stdout[-3000:] + done.stderr[-2000:])

    def test_what_it_writes_is_the_file_a_designer_would_edit(self) -> None:
        """Not a pickle, not a blob: a part that later needs a feature no
        template offers has to be able to start from this file."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "model.py"
            build.main(["--template", "c_clip", *_CLIP, "--out", str(out)])
            text = out.read_text(encoding="utf-8")
            self.assertIn("from designer_toolkit.templates import c_clip", text)
            self.assertIn("bore_d=12.0", text)
            compile(text, "model.py", "exec")


if __name__ == "__main__":
    unittest.main()
