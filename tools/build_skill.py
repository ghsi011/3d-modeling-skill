#!/usr/bin/env python3
"""Build deterministic .skill zip artifacts for the five 3D modeling roles.

Usage:
    python tools/build_skill.py [--out dist/skills]
"""
from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / "skills"
SHARED_DIR = SKILLS_DIR / "3d-modeling"

ROLE_NAMES = [
    "3d-orchestrator",
    "3d-metrologist",
    "3d-designer",
    "3d-verifier",
    "3d-print-engineer",
]

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


def _build_role_skill(role_name: str, out_dir: Path) -> Path:
    role_dir = SKILLS_DIR / role_name
    zip_path = out_dir / f"{role_name}.skill"
    shared_refs = SHARED_DIR / "references"
    shared_scripts = SHARED_DIR / "scripts"

    entries: list[tuple[str, bytes]] = []

    skill_md = role_dir / "SKILL.md"
    if skill_md.exists():
        entries.append(("SKILL.md", skill_md.read_bytes()))

    for f in _collect_files(shared_refs):
        rel = f.relative_to(shared_refs)
        entries.append((f"references/{rel.as_posix()}", f.read_bytes()))

    for f in _collect_files(shared_scripts):
        rel = f.relative_to(shared_scripts)
        entries.append((f"scripts/{rel.as_posix()}", f.read_bytes()))

    _write_zip(zip_path, entries)
    return zip_path


def _build_team_bundle(out_dir: Path) -> Path:
    zip_path = out_dir / "3d-modeling-team.skill"
    entries: list[tuple[str, bytes]] = []

    for role_name in ROLE_NAMES:
        role_dir = SKILLS_DIR / role_name
        skill_md = role_dir / "SKILL.md"
        if skill_md.exists():
            entries.append((f"roles/{role_name}/SKILL.md", skill_md.read_bytes()))

    shared_refs = SHARED_DIR / "references"
    for f in _collect_files(shared_refs):
        rel = f.relative_to(shared_refs)
        entries.append((f"references/{rel.as_posix()}", f.read_bytes()))

    shared_scripts = SHARED_DIR / "scripts"
    for f in _collect_files(shared_scripts):
        rel = f.relative_to(shared_scripts)
        entries.append((f"scripts/{rel.as_posix()}", f.read_bytes()))

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

    built: list[Path] = []
    for role_name in ROLE_NAMES:
        p = _build_role_skill(role_name, out_dir)
        built.append(p)
        print(f"  built {p}")

    bundle = _build_team_bundle(out_dir)
    built.append(bundle)
    print(f"  built {bundle}")

    print(f"Done: {len(built)} artifacts in {out_dir}")


if __name__ == "__main__":
    main()
