#!/usr/bin/env python3
"""Build the deterministic .skill zip artifact for the 3D modeling pipeline.

One archive, not five. The orchestrator is the skill; the four specialists are
files it hands to subagents. They were never independently useful -- a designer
with no commission refuses to start, by design -- and five sibling skills that
reach each other by relative path break the moment a host installs one alone.

Usage:
    python tools/build_skill.py [--out dist/skills]
"""
from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / "skills"
SKILL_DIR = SKILLS_DIR / "3d-modeling"
ARTIFACT_NAME = "3d-modeling.skill"

# A bundle is a runtime surface, not a dev checkout. The suites and their
# fixtures are a third of the packed bytes, no shipped skill runs them, and no
# role or reference tells an agent to. They stay in the repo, where CI runs them.
EXCLUDE_DIRS = {"__pycache__", ".ruff_cache", ".pytest_cache", "examples"}
EXCLUDE_EXTS = {".pyc"}
EXCLUDE_PREFIXES = ("test_",)
FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def _should_include(path: Path) -> bool:
    if path.suffix in EXCLUDE_EXTS or path.name.startswith(EXCLUDE_PREFIXES):
        return False
    for part in path.parts:
        if part in EXCLUDE_DIRS:
            return False
    return True


def _collect_files(base: Path) -> list[Path]:
    if not base.exists():
        return []
    return [p for p in sorted(base.rglob("*")) if p.is_file() and _should_include(p)]


def _write_zip(zip_path: Path, entries: list[tuple[str, bytes]]) -> None:
    entries_sorted = sorted(entries, key=lambda e: e[0])
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for arcname, data in entries_sorted:
            info = zipfile.ZipInfo(arcname, date_time=FIXED_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, data)


def _build_skill(out_dir: Path) -> Path:
    """Pack `skills/3d-modeling/` verbatim.

    The tree on disk is already the shipped shape -- SKILL.md at the root,
    roles/ beside it, references/ and scripts/ beside those -- so every relative
    link inside the archive is the same link that resolves in the repo. That is
    the property `test_build_skill` asserts, and the one whose absence shipped
    an archive whose every required-reading link pointed one directory above
    the installed skill.
    """
    zip_path = out_dir / ARTIFACT_NAME
    entries = [
        (f.relative_to(SKILL_DIR).as_posix(), f.read_bytes())
        for f in _collect_files(SKILL_DIR)
    ]
    _write_zip(zip_path, entries)
    return zip_path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build .skill zip artifacts")
    parser.add_argument(
        "--out",
        default="dist/skills",
        help="Output directory (default: dist/skills)",
    )
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    built = _build_skill(out_dir)
    print(f"  built {built}")
    print(f"Done: 1 artifact in {out_dir}")


if __name__ == "__main__":
    main()
