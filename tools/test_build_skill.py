"""Tests for tools/build_skill.py — deterministic .skill artifact builds."""
from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = ROOT / "tools" / "build_skill.py"

ROLE_NAMES = [
    "3d-orchestrator",
    "3d-metrologist",
    "3d-designer",
    "3d-verifier",
    "3d-print-engineer",
]

ALL_ARTIFACTS = [f"{n}.skill" for n in ROLE_NAMES] + ["3d-modeling-team.skill"]


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
    def test_all_artifacts_created(self, build_dir: Path):
        for name in ALL_ARTIFACTS:
            assert (build_dir / name).exists(), f"Missing artifact: {name}"

    def test_reproducible_builds(self):
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            out1 = Path(tmp1) / "skills"
            out2 = Path(tmp2) / "skills"
            _run_build(out1)
            _run_build(out2)
            for name in ALL_ARTIFACTS:
                h1 = _sha256(out1 / name)
                h2 = _sha256(out2 / name)
                assert h1 == h2, f"Non-reproducible: {name}"

    def test_skill_md_at_root(self, build_dir: Path):
        for name in ALL_ARTIFACTS:
            with zipfile.ZipFile(build_dir / name) as zf:
                names = zf.namelist()
                if name == "3d-modeling-team.skill":
                    for role in ROLE_NAMES:
                        assert f"roles/{role}/SKILL.md" in names, (
                            f"Missing roles/{role}/SKILL.md in {name}"
                        )
                else:
                    assert "SKILL.md" in names, f"Missing SKILL.md at root of {name}"

    def test_no_monolith_primary(self, build_dir: Path):
        standalone = [n for n in ALL_ARTIFACTS if n != "3d-modeling-team.skill"]
        assert "3d-modeling.skill" not in standalone

    def test_no_pycache_in_zips(self, build_dir: Path):
        for name in ALL_ARTIFACTS:
            with zipfile.ZipFile(build_dir / name) as zf:
                for entry in zf.namelist():
                    assert "__pycache__" not in entry, f"__pycache__ in {name}: {entry}"
                    assert not entry.endswith(".pyc"), f".pyc in {name}: {entry}"

    def test_fixed_timestamp(self, build_dir: Path):
        expected = (1980, 1, 1, 0, 0, 0)
        for name in ALL_ARTIFACTS:
            with zipfile.ZipFile(build_dir / name) as zf:
                for info in zf.infolist():
                    assert info.date_time == expected, (
                        f"Bad timestamp in {name}/{info.filename}: {info.date_time}"
                    )

    def test_sorted_entries(self, build_dir: Path):
        for name in ALL_ARTIFACTS:
            with zipfile.ZipFile(build_dir / name) as zf:
                names = zf.namelist()
                assert names == sorted(names), f"Unsorted entries in {name}"

    def test_role_skills_include_shared_assets(self, build_dir: Path):
        for name in [f"{n}.skill" for n in ROLE_NAMES]:
            with zipfile.ZipFile(build_dir / name) as zf:
                entries = zf.namelist()
                ref_entries = [e for e in entries if e.startswith("references/")]
                script_entries = [e for e in entries if e.startswith("scripts/")]
                assert len(ref_entries) > 0, f"No references/ in {name}"
                assert len(script_entries) > 0, f"No scripts/ in {name}"
