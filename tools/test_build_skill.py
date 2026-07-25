"""Tests for tools/build_skill.py — the deterministic .skill artifact.

The load-bearing one is `test_every_internal_link_resolves_inside_the_archive`.
Its absence shipped an archive in which every required-reading link pointed one
directory above the installed skill: the files were all present, the build was
green, and an agent following its own charter found nothing.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = ROOT / "tools" / "build_skill.py"

ARTIFACT = "3d-modeling.skill"
ROLE_FILES = ["roles/designer.md", "roles/metrologist.md",
              "roles/print-engineer.md", "roles/verifier.md"]

LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")


def _run_build(out_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(BUILD_SCRIPT), "--out", str(out_dir)],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        check=True,
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def build_dir():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "skills"
        _run_build(out)
        yield out


class TestBuildSkill:
    def test_one_artifact_is_built(self, build_dir: Path):
        emitted = {p.name for p in build_dir.glob("*.skill")}
        assert emitted == {ARTIFACT}

    def test_reproducible_builds(self):
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            out1, out2 = Path(tmp1) / "skills", Path(tmp2) / "skills"
            _run_build(out1)
            _run_build(out2)
            assert _sha256(out1 / ARTIFACT) == _sha256(out2 / ARTIFACT)

    def test_archive_shape(self, build_dir: Path):
        with zipfile.ZipFile(build_dir / ARTIFACT) as zf:
            names = zf.namelist()
        assert "SKILL.md" in names, "the orchestrator must be the skill entry point"
        for role in ROLE_FILES:
            assert role in names, f"missing {role}"
        assert any(n.startswith("references/") for n in names)
        assert any(n.startswith("scripts/") for n in names)

    def test_every_internal_link_resolves_inside_the_archive(self, build_dir: Path):
        """No link may escape the archive or point at a missing member.

        This is what the five-bundle layout got wrong: SKILL.md kept the repo's
        `../3d-modeling/references/...` paths while the bundle carried those
        assets at its own root, so all 36 links resolved above the install root.
        """
        with zipfile.ZipFile(build_dir / ARTIFACT) as zf:
            members = set(zf.namelist())
            broken: list[str] = []
            for name in (n for n in members if n.endswith(".md")):
                text = zf.read(name).decode("utf-8", errors="replace")
                for _label, target in LINK_RE.findall(text):
                    if target.startswith(("http://", "https://", "mailto:", "#")):
                        continue
                    path_part = target.split("#", 1)[0]
                    if not path_part:
                        continue
                    resolved = (Path(name).parent / path_part).as_posix()
                    resolved = str(Path(resolved).as_posix()).replace("\\", "/")
                    normalized = Path(resolved)
                    parts: list[str] = []
                    for part in normalized.parts:
                        if part == "..":
                            if not parts:
                                broken.append(f"{name} -> {target} (escapes the archive)")
                                break
                            parts.pop()
                        elif part != ".":
                            parts.append(part)
                    else:
                        candidate = "/".join(parts)
                        if candidate not in members and f"{candidate}/" not in members:
                            if not any(m.startswith(f"{candidate}/") for m in members):
                                broken.append(f"{name} -> {target} (no member {candidate})")
        assert not broken, "links break inside the shipped skill:\n  " + "\n  ".join(broken)

    def test_zips_ship_no_test_suite(self, build_dir: Path):
        with zipfile.ZipFile(build_dir / ARTIFACT) as zf:
            offenders = [
                e for e in zf.namelist()
                if Path(e).name.startswith("test_") or "/examples/" in e
            ]
        assert not offenders, f"ships test payload: {offenders}"

    def test_no_pycache_in_zip(self, build_dir: Path):
        with zipfile.ZipFile(build_dir / ARTIFACT) as zf:
            assert not [e for e in zf.namelist() if "__pycache__" in e]

    def test_fixed_timestamps_and_permissions(self, build_dir: Path):
        with zipfile.ZipFile(build_dir / ARTIFACT) as zf:
            for info in zf.infolist():
                assert info.date_time == (1980, 1, 1, 0, 0, 0), info.filename
                assert info.external_attr >> 16 == 0o644, info.filename

    def test_entries_are_sorted(self, build_dir: Path):
        with zipfile.ZipFile(build_dir / ARTIFACT) as zf:
            names = zf.namelist()
        assert names == sorted(names)
