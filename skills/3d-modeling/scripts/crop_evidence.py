#!/usr/bin/env python3
"""Prepare evidence photographs for reading.

Photographs dominate a metrology dispatch: measured across two real runs they
were ~69% of peak context, at 2,568-21,785 tokens each -- one phone photo can
cost as much as the entire runtime contract. Two habits made that worse:

* Crops were saved as 3x-upscaled PNG. One 1.74 MB source became a 35 MB crop.
  The upscale buys nothing: images are downsampled before a model sees them, so
  the extra pixels are discarded on arrival and only the tokens survive.
* Rotation was resolved by trial: read, rotate, read again, rotate again. Two
  photographs in one run were read four times and still yielded no number.

So: `crop` caps the long edge and writes JPEG, and `contact-sheet` puts many
images on one page so triage costs one read instead of seventeen.

    uv run --project <skill> --frozen python <skill>/scripts/crop_evidence.py contact-sheet evidence/*.jpg --out sheet.jpg
    uv run --project <skill> --frozen python <skill>/scripts/crop_evidence.py crop photo.jpg --box 0.30 0.40 0.62 0.58 --out c.jpg
    uv run --project <skill> --frozen python <skill>/scripts/crop_evidence.py rotations photo.jpg --out r.jpg
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

# Images are downsampled to roughly this long edge before a model sees them.
# Anything larger is paid for in bytes and discarded on arrival.
MAX_LONG_EDGE = 1568
JPEG_QUALITY = 85


def _load(path: Path) -> Image.Image:
    """Open, honouring the EXIF orientation tag.

    Doing this first is what removes most of the guess-and-retry: a phone photo
    is usually already labelled with which way is up.
    """
    return ImageOps.exif_transpose(Image.open(path)).convert("RGB")


def _fit(image: Image.Image, max_edge: int = MAX_LONG_EDGE) -> Image.Image:
    scale = max_edge / max(image.size)
    if scale >= 1.0:
        return image
    return image.resize((round(image.width * scale), round(image.height * scale)),
                        Image.LANCZOS)


def crop(source: Path, out: Path, box: tuple[float, float, float, float],
         rotate: int = 0, max_edge: int = MAX_LONG_EDGE) -> Path:
    """Crop by fractional box (left, top, right, bottom), then cap and save."""
    image = _load(source)
    left, top, right, bottom = box
    region = image.crop((round(left * image.width), round(top * image.height),
                         round(right * image.width), round(bottom * image.height)))
    if rotate:
        region = region.rotate(rotate, expand=True)
    region = _fit(region, max_edge)
    out.parent.mkdir(parents=True, exist_ok=True)
    region.save(out, "JPEG", quality=JPEG_QUALITY)
    return out


def contact_sheet(sources: list[Path], out: Path, columns: int = 0,
                  max_edge: int = MAX_LONG_EDGE) -> Path:
    """Tile every image onto one page, numbered.

    Triage is a whole-set question -- which photographs carry a readable
    dimension -- and answering it one file at a time costs one read per file.
    """
    if not sources:
        raise ValueError("no images given")
    images = [_load(path) for path in sources]
    columns = columns or math.ceil(math.sqrt(len(images)))
    rows = math.ceil(len(images) / columns)
    cell = max(1, max_edge // columns)

    sheet = Image.new("RGB", (columns * cell, rows * cell), "white")
    draw = ImageDraw.Draw(sheet)
    for index, image in enumerate(images):
        thumb = image.copy()
        thumb.thumbnail((cell, cell), Image.LANCZOS)
        x = (index % columns) * cell
        y = (index // columns) * cell
        sheet.paste(thumb, (x + (cell - thumb.width) // 2, y + (cell - thumb.height) // 2))
        draw.rectangle([x, y, x + cell - 1, y + cell - 1], outline="black")
        draw.text((x + 4, y + 4), str(index + 1), fill="red")
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, "JPEG", quality=JPEG_QUALITY)
    return out


def rotations(source: Path, out: Path, max_edge: int = MAX_LONG_EDGE) -> Path:
    """All four rotations of one image on a single page.

    When a caliper display is ambiguous, this answers "which way is up" in one
    read instead of four.
    """
    image = _load(source)
    cell = max(1, max_edge // 2)
    sheet = Image.new("RGB", (cell * 2, cell * 2), "white")
    draw = ImageDraw.Draw(sheet)
    for index, angle in enumerate((0, 90, 180, 270)):
        turned = image.rotate(angle, expand=True)
        turned.thumbnail((cell, cell), Image.LANCZOS)
        x, y = (index % 2) * cell, (index // 2) * cell
        sheet.paste(turned, (x + (cell - turned.width) // 2, y + (cell - turned.height) // 2))
        draw.rectangle([x, y, x + cell - 1, y + cell - 1], outline="black")
        draw.text((x + 4, y + 4), f"{angle} deg", fill="red")
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, "JPEG", quality=JPEG_QUALITY)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    c = sub.add_parser("crop", help="fractional crop, capped and saved as JPEG")
    c.add_argument("source", type=Path)
    c.add_argument("--box", type=float, nargs=4, required=True,
                   metavar=("LEFT", "TOP", "RIGHT", "BOTTOM"), help="fractions of the image")
    c.add_argument("--rotate", type=int, default=0)
    c.add_argument("--out", type=Path, required=True)

    s = sub.add_parser("contact-sheet", help="tile many images onto one page for triage")
    s.add_argument("sources", type=Path, nargs="+")
    s.add_argument("--columns", type=int, default=0)
    s.add_argument("--out", type=Path, required=True)

    r = sub.add_parser("rotations", help="all four rotations on one page")
    r.add_argument("source", type=Path)
    r.add_argument("--out", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.command == "crop":
        written = crop(args.source, args.out, tuple(args.box), args.rotate)
    elif args.command == "contact-sheet":
        written = contact_sheet(args.sources, args.out, args.columns)
    else:
        written = rotations(args.source, args.out)
    size_kb = written.stat().st_size // 1024
    sys.stdout.write(f"{written} ({size_kb} KB)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
