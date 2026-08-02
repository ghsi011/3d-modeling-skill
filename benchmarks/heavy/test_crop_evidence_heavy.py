#!/usr/bin/env python3
"""L0-heavy — the half of
`skills/3d-modeling/scripts/test_crop_evidence.py`
that costs a child interpreter.

The repository-root `conftest.py` refuses a child interpreter inside the commit
gate, and these classes start one. Same tests, moved rather than weakened;
`benchmarks/heavy/README.md` records the profile that decided the seam and what
runs this tier. What stayed behind is what answers in the parent process.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from PIL import Image
import crop_evidence  # noqa: E402

# The fixtures this half shares with the half that stayed behind,
# imported rather than copied: two spellings of one fixture is how
# two tiers stop testing the same thing.
from test_crop_evidence import (  # noqa: E402
    _photo,
)


class ContactSheetTest(unittest.TestCase):
    def test_many_photos_become_one_small_page(self) -> None:
        """Triage is a whole-set question; answering it per file costs a read
        per file."""
        with TemporaryDirectory() as raw:
            work = Path(raw)
            sources = [_photo(work / f"p{i}.jpg", colour=(i * 12 % 255, 80, 140))
                       for i in range(17)]
            total = sum(p.stat().st_size for p in sources)

            sheet = crop_evidence.contact_sheet(sources, work / "sheet.jpg")

            self.assertLess(sheet.stat().st_size, total / 10)
            with Image.open(sheet) as image:
                self.assertLessEqual(max(image.size), crop_evidence.MAX_LONG_EDGE + 8)

    def test_an_empty_set_is_an_error_not_a_blank_page(self) -> None:
        with TemporaryDirectory() as raw:
            with self.assertRaises(ValueError):
                crop_evidence.contact_sheet([], Path(raw) / "sheet.jpg")
