"""Check that all relative markdown links resolve to existing files."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
# Anything not authored by this repo. `.venv` matters as much as `.git`: a local
# virtualenv carries thousands of package README files whose relative links are
# none of our business, and scanning them can fail a run that CI (which has no
# venv directory) passes.
EXCLUDE_DIRS = {
    ".omo", ".git", ".pytest_cache", "__pycache__", "node_modules", ".ruff_cache",
    ".venv", "venv", "env", "dist", "temp", ".mypy_cache",
}


def iter_markdown(root: Path = REPO_ROOT) -> list[Path]:
    return [
        p
        for p in sorted(root.rglob("*.md"))
        if not any(part in EXCLUDE_DIRS for part in p.relative_to(root).parts)
    ]


def find_broken(root: Path = REPO_ROOT) -> list[tuple[Path, str, str]]:
    broken: list[tuple[Path, str, str]] = []
    for md in iter_markdown(root):
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


def main(root: Path = REPO_ROOT) -> int:
    broken = find_broken(root)
    if not broken:
        print("All internal markdown links resolved.")
        return 0
    for src, target, resolved in broken:
        print(f"BROKEN: {src.relative_to(root)}: [{target}] -> {resolved}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
