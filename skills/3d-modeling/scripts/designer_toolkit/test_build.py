"""Tests for `dt.py build` -- the template instantiator.

The load-bearing one is `test_the_generated_model_passes_the_gate`: this command
exists to remove a dispatch, so what it writes has to satisfy the gate with no
human in between. A generator whose output needs hand-repair has saved nothing.

The half of this file the commit gate will not carry is in
`benchmarks/heavy/test_build_heavy.py`, and runs before merge instead of on
every push: `TestBuildCommand`. Same tests, moved rather than weakened;
`conftest.py` carries the rule and `benchmarks/heavy/README.md` the measurement
behind it.
"""
from __future__ import annotations

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

    def test_expectations_come_from_the_template_not_the_caller(self) -> None:
        """`EXPECTED` is the one thing in a model file nobody may hand-tune: an
        expectation the author adjusted until it passed measures nothing. It has
        to be the template's arithmetic, reached by reference."""
        source = build.render_model("c_clip", {"wall": 3.0})
        self.assertIn("EXPECTED = _built.expected", source)
        self.assertNotIn("EXPECTED = [", source)
        self.assertNotIn("EXPECTED = (", source)

    def test_params_come_from_the_template_not_the_caller(self) -> None:
        """A hand-written model.py could declare `PARAMS` that disagreed with the
        solid it shipped beside; every static check then ran against fiction."""
        source = build.render_model("c_clip", {"wall": 3.0})
        self.assertIn("PARAMS = _built.params", source)
        self.assertNotIn("PARAMS = {", source)


if __name__ == "__main__":
    unittest.main()
