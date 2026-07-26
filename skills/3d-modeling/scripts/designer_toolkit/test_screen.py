"""Tests for `dt.py screen`.

The command exists because every other check here is conditioned on a
declaration, so geometry nobody declared is invisible to all of them -- a 4 mm
post standing in a bin floor passed twenty-seven green checks. Looking is the
only unconditioned evidence, and measured it takes about ten seconds; what made
it expensive was deciding what to ask.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from . import screen

_SHEET = """---
contract: dimensions
---

# Dimensions

## Blind-build completeness
| Feature ID | Name/count/function | Datum value or bounded envelope | Source | Confidence | Candidate response | Ready |
|---|---|---|---|---|---|---|
| BF-01 | Base feet, 2, locate the bin in a baseplate | tops 41.5 sq at (+/-21, 0) | S-1 | B | loft | yes |
| BF-02 | Magnet pockets, 8 | dia 6.5, 2.4 deep | S-1 | B | bore | yes |

## Dimensions
| ID | Feature |
|---|---|
| D-01 | not part of the inventory |
"""


def _project(root: Path, *, sheet: bool = True, renders: bool = True) -> Path:
    project = root / "job"
    project.mkdir()
    (project / "commission.json").write_text(json.dumps({
        "verdict": "PASS",
        "evidence": {"export": {"bbox_mm": {"x": 83.5, "y": 41.5, "z": 25.4}}},
    }), encoding="utf-8")
    if sheet:
        (project / "dimensions.md").write_text(_SHEET, encoding="utf-8")
    if renders:
        (project / "renders").mkdir()
        (project / "renders" / "multi.png").write_bytes(b"\x89PNG")
    return project


class TestScreen(unittest.TestCase):
    def test_the_inventory_is_the_human_readable_one(self) -> None:
        """The first draft listed the measured rows -- areas at z heights, hole
        coordinates. That is an accurate inventory and a useless description, and
        it measurably degraded the screen: given the numeric list a reader
        flagged a structural bridge and walked past a post standing in the middle
        of the compartment, which the same reader found in eight seconds when
        told the part was a plain open box with a flat floor."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            screen.bundle(_project(root), root / "out")

            question = (root / "out" / "question.md").read_text(encoding="utf-8")

            self.assertIn("Base feet, 2, locate the bin in a baseplate", question)
            self.assertIn("Magnet pockets, 8", question)
            self.assertNotIn("not part of the inventory", question,
                             "only the completeness table describes the object")

    def test_it_asks_the_question_no_check_can_ask(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            screen.bundle(_project(root), root / "out")
            question = (root / "out" / "question.md").read_text(encoding="utf-8")

            self.assertIn("not on that list", question)
            self.assertIn("Do not verify the list", question,
                          "re-checking declared features is what the gate already did")

    def test_it_names_the_images(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            result = screen.bundle(_project(root), root / "out")
            self.assertEqual(1, len(result["images"]))

    def test_no_renders_is_an_error_not_a_bundle(self) -> None:
        """With no image the one piece of evidence conditioned on nothing does
        not exist, so there is nothing to screen."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project = _project(root, renders=False)
            code = screen.main([str(project), "--out", str(root / "out")])
            self.assertEqual(1, code)

    def test_an_ungated_project_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "bare").mkdir()
            self.assertEqual(2, screen.main([str(root / "bare"), "--out", str(root / "o")]))

    def test_a_sheet_with_no_inventory_says_so(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            screen.bundle(_project(root, sheet=False), root / "out")
            question = (root / "out" / "question.md").read_text(encoding="utf-8")
            self.assertIn("nothing at all was declared by name", question)


if __name__ == "__main__":
    unittest.main()
