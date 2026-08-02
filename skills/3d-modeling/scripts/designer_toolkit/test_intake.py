"""Tests for `dt.py intake`.

The point of this command is that a measured no-dispatch run spent much of 13.8
minutes typing 246 lines of contract by hand, almost none of it judgment. So the
tests hold it to both halves of that: the mechanical fields must come out right
without help, and the judgment fields must still be demanded rather than
invented.

The half of this file the commit gate will not carry is in
`benchmarks/heavy/test_intake_heavy.py`, and runs before merge instead of on
every push: `TestIntake`. Same tests, moved rather than weakened; `conftest.py`
carries the rule and `benchmarks/heavy/README.md` the measurement behind it.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from . import intake

SCRIPTS = Path(__file__).resolve().parents[1]

_CLIP = ["--param", "bore_d=12.0", "--param", "wall=3.0", "--param", "height=9.0",
         "--param", "mouth_gap=9.0", "--param", "flange=(40.0, 22.0, 5.0)",
         "--param", "screw_d=4.5", "--param", "screw_at=(8.0, 11.0)",
         "--param", "countersink_d=9.0"]


def _run(out: Path, *extra):
    return intake.main(["--job-id", "clip", "--template", "c_clip", *_CLIP,
                        "--updated-utc", "1970-01-01T00:00:00Z", "--out", str(out), *extra])


if __name__ == "__main__":
    unittest.main()


class ProvenanceTest(unittest.TestCase):
    """Where each number in `dimensions.md` says it came from.

    Every row used to read `stated in the brief / user / B`, on the reasoning
    that user-stated numbers are the condition for the DIRECT route. They are
    not: the condition is that nothing needs measuring. A brief asking for a
    clip over a 12 mm bundle states three numbers and `c_clip` takes eight, so
    five rows claimed the user's authority for values the caller invented -- on
    the one document whose entire purpose is provenance.
    """

    _PARAMS = {"bore_d": 12.0, "wall": 3.0, "screw_d": 4.8}

    def _rows(self, stated: frozenset[str]) -> str:
        return intake._dimension_rows(self._PARAMS, stated)

    def test_unlisted_parameters_are_the_designers_choice(self) -> None:
        rows = self._rows(frozenset({"bore_d"}))
        self.assertIn("| bore_d | 12.0 | stated in the brief | user | B |", rows)
        self.assertIn("| wall | 3.0 | chosen by design | designer | D |", rows)
        self.assertIn("| screw_d | 4.8 | chosen by design | designer | D |", rows)

    def test_the_default_never_claims_the_user_said_anything(self) -> None:
        """The direction of the failure is the point. Forgetting `--stated`
        understates the caller's own confidence, which invites scrutiny;
        the reverse manufactures a statement the user never made, and nothing
        downstream of the sheet can tell."""
        rows = self._rows(frozenset())
        self.assertNotIn("stated in the brief", rows)
        self.assertNotIn("| user |", rows)
        self.assertEqual(3, rows.count("chosen by design"))

    def test_stated_accepts_a_comma_list_and_repeated_flags(self) -> None:
        self.assertEqual(frozenset({"a", "b", "c"}),
                         intake._stated(["a,b", "c"]))
        self.assertEqual(frozenset({"a", "b"}),
                         intake._stated([" a , b "]))
        self.assertEqual(frozenset(), intake._stated([]))
