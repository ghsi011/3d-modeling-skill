#!/usr/bin/env python3
"""L0-heavy — the half of
`tools/test_diagnosis_l0.py`
that costs a child interpreter.

The repository-root `conftest.py` refuses a child interpreter inside the commit
gate, and these classes start one. Same tests, moved rather than weakened;
`benchmarks/heavy/README.md` records the profile that decided the seam and what
runs this tier. What stayed behind is what answers in the parent process.
"""
from __future__ import annotations

import unittest

# The fixtures this half shares with the half that stayed behind,
# imported rather than copied: two spellings of one fixture is how
# two tiers stop testing the same thing.
from tools.test_diagnosis_l0 import (  # noqa: E402
    _report,
)


class L0UntessellatableStep(unittest.TestCase):
    """6 — the vent mount: an exact B-rep nothing can turn into triangles.

    D14. `vent_mount.step` was reported `USABLE_EXACT` with no findings, and then
    every operation that needed geometry died on
    ``'NoneType' object has no attribute 'NbNodes'`` -- OCC's way of saying a face
    has a null triangulation. That is the exact failure diagnosis exists to
    prevent: the file passed the stage whose job is to say whether it can be
    worked with, and the error surfaced at a stage with less context to explain
    it.

    Face area is what the old check measured, and area is not tessellability.
    Every one of this file's 329 faces has a finite positive area -- one of them
    is 1.75e-14 mm2, which is small and is not zero -- so `invalid_faces` was 0
    and stayed 0 whatever the mesher could do.

    The facts are asserted, not the verdict, as everywhere else in this file: the
    count of untessellatable faces, the surface type OCC named, and that the
    finding says what a reader has to do about it. A test asserting only
    `REPAIR_REQUIRED` would pass on any wrong reason at all.
    """

    FIXTURE = "vent-ball-combine"

    def _report(self) -> dict:
        return _report(self, self.FIXTURE)

    def test_the_faces_that_cannot_be_tessellated_are_counted(self) -> None:
        report = self._report()
        self.assertEqual("STEP", report["format"])
        self.assertEqual(329, report["faces"])
        self.assertGreater(report["untessellatable_faces"], 0,
                           "a file whose cone faces defeat every mesher this "
                           "runtime has must not be reported clean")
        self.assertEqual(report["untessellatable_faces"],
                         len(report["tessellation"]["failures"]))
        self.assertEqual(report["faces"],
                         report["tessellation"]["faces"])
        self.assertEqual(report["faces"] - report["untessellatable_faces"],
                         report["tessellation"]["tessellated_faces"])

    def test_the_area_test_alone_would_still_call_this_file_clean(self) -> None:
        """Why the new probe had to be added rather than the old one tightened."""
        report = self._report()
        self.assertEqual(0, report["invalid_faces"],
                         "every face has a finite positive area; if this ever "
                         "becomes non-zero the area test has started catching "
                         "this file and this fixture is measuring something else")

    def test_the_finding_names_the_faces_and_the_deflection(self) -> None:
        report = self._report()
        finding = next((f for f in report["findings"]
                        if "cannot be tessellated" in f), None)
        self.assertIsNotNone(finding, report["findings"])
        self.assertIn("CONE", finding,
                      "the surface type is what tells a repairer where to look")
        self.assertIn(str(report["tessellation"]["linear_deflection"]), finding,
                      "a tessellation failure is only a fact against a deflection")

    def test_it_is_not_usable_as_it_stands(self) -> None:
        self.assertEqual("REPAIR_REQUIRED", self._report()["classification"])
