"""Check that all relative markdown links resolve to existing files."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
EXCLUDE_DIRS = {".omo", ".git", ".pytest_cache", "__pycache__", "node_modules", ".ruff_cache"}


def iter_markdown() -> list[Path]:
    paths: list[Path] = []
    for p in REPO_ROOT.rglob("*.md"):
        if any(part in EXCLUDE_DIRS for part in p.relative_to(REPO_ROOT).parts):
            continue
        paths.append(p)
    return paths


def find_broken() -> list[tuple[Path, str, str]]:
    broken: list[tuple[Path, str, str]] = []
    for md in iter_markdown():
        text = md.read_text(encoding="utf-8", errors="replace")
        for _text, target in LINK_RE.findall(text):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            path_part = target.split("#", 1)[0]
            if not path_part:
                continue
            resolved = (md.parent / path_part).resolve()
            if not resolved.exists():
                broken.append((md, target, str(resolved)))
    return broken


def main() -> int:
    broken = find_broken()
    if not broken:
        print("All internal markdown links resolved.")
        return 0
    for src, target, resolved in broken:
        rel = src.relative_to(REPO_ROOT)
        print(f"BROKEN: {rel}: [{target}] -> {resolved}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
