"""Tests for evidence-photo preparation.

The property under test is cost. Photographs were ~69% of a metrology
dispatch's peak context, and the habit that made it worse was saving 3x-upscaled
PNG crops -- one 1.74 MB source became a 35 MB crop, whose extra pixels are
discarded before a model sees them. So these assert the caps hold and the
output is small, not merely that an image comes out.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import crop_evidence  # noqa: E402


def _photo(path: Path, size=(4032, 3024), colour=(90, 120, 160)) -> Path:
    Image.new("RGB", size, colour).save(path, "JPEG", quality=92)
    return path


class CropTest(unittest.TestCase):
    def test_a_crop_is_capped_to_the_readable_edge(self) -> None:
        with TemporaryDirectory() as raw:
            work = Path(raw)
            out = crop_evidence.crop(_photo(work / "src.jpg"), work / "out.jpg",
                                     (0.0, 0.0, 1.0, 1.0))

            with Image.open(out) as image:
                self.assertLessEqual(max(image.size), crop_evidence.MAX_LONG_EDGE)

    def test_it_never_upscales(self) -> None:
        """The specific waste this replaces: a 3x upscale that is discarded."""
        with TemporaryDirectory() as raw:
            work = Path(raw)
            small = _photo(work / "small.jpg", size=(300, 200))

            out = crop_evidence.crop(small, work / "out.jpg", (0.0, 0.0, 1.0, 1.0))

            with Image.open(out) as image:
                self.assertEqual(image.size, (300, 200))

    def test_a_crop_of_a_large_photo_is_far_smaller_than_the_source(self) -> None:
        with TemporaryDirectory() as raw:
            work = Path(raw)
            source = _photo(work / "src.jpg")
            out = crop_evidence.crop(source, work / "out.jpg", (0.25, 0.25, 0.75, 0.75))

            self.assertLess(out.stat().st_size, source.stat().st_size)

    def test_the_fractional_box_selects_the_region_asked_for(self) -> None:
        with TemporaryDirectory() as raw:
            work = Path(raw)
            image = Image.new("RGB", (1000, 1000), "white")
            for x in range(500, 1000):
                for y in range(500, 1000):
                    image.putpixel((x, y), (255, 0, 0))
            source = work / "quad.jpg"
            image.save(source, "JPEG", quality=95)

            out = crop_evidence.crop(source, work / "out.jpg", (0.5, 0.5, 1.0, 1.0))

            with Image.open(out) as cropped:
                centre = cropped.getpixel((cropped.width // 2, cropped.height // 2))
            self.assertGreater(centre[0], 200)
            self.assertLess(centre[1], 60)


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


class RotationsTest(unittest.TestCase):
    def test_all_four_turns_land_on_one_page(self) -> None:
        with TemporaryDirectory() as raw:
            work = Path(raw)
            out = crop_evidence.rotations(_photo(work / "src.jpg", size=(800, 400)),
                                          work / "turns.jpg")

            with Image.open(out) as image:
                self.assertEqual(image.width, image.height)  # 2x2
                self.assertLessEqual(max(image.size), crop_evidence.MAX_LONG_EDGE + 8)


class CliTest(unittest.TestCase):
    def test_contact_sheet_from_the_command_line(self) -> None:
        with TemporaryDirectory() as raw:
            work = Path(raw)
            sources = [str(_photo(work / f"p{i}.jpg")) for i in range(3)]
            out = work / "sheet.jpg"

            code = crop_evidence.main(["contact-sheet", *sources, "--out", str(out)])

            self.assertEqual(code, 0)
            self.assertTrue(out.is_file())


if __name__ == "__main__":
    unittest.main()
