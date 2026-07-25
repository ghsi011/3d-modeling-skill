"""Smoke tests for `python -m designer_toolkit`.

The designer's required reading tells it to call this CLI rather than
re-author the measurement patterns, so a broken subcommand sends the role
back to hand-rolling the thing the toolkit exists to prevent. These check the
contract each subcommand advertises: that it runs, emits parseable JSON, and
reports a usage error rather than a traceback on bad input.

Deliberately thin. The measurement logic itself is covered against known
geometry in test_designer_toolkit.py; what is unproven without these is the
CLI wiring between them.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import trimesh

SCRIPTS_DIR = Path(__file__).resolve().parent.parent


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "designer_toolkit", *args],
        cwd=str(SCRIPTS_DIR), capture_output=True, text=True, check=False,
    )


@pytest.fixture(scope="module")
def box_stl(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("cli") / "box.stl"
    mesh = trimesh.creation.box(extents=(10, 20, 30))
    mesh.apply_translation((0, 0, 15))
    mesh.export(path)
    return path


def test_help_lists_every_subcommand() -> None:
    result = _run("--help")

    assert result.returncode == 0, result.stderr
    for subcommand in ("measure", "overhang", "datums", "interference", "sweep",
                       "export", "coupon", "finalize"):
        assert subcommand in result.stdout


def test_measure_emits_the_dimensions_it_documents(box_stl: Path) -> None:
    result = _run("measure", str(box_stl))

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["bbox_mm"]["x"] == pytest.approx(10, abs=0.1)
    assert report["bbox_mm"]["z"] == pytest.approx(30, abs=0.1)
    assert report["watertight"] is True
    assert report["components"] == 1


def test_overhang_reports_zero_for_a_box_on_the_bed(box_stl: Path) -> None:
    result = _run("overhang", str(box_stl))

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["overhang_mm2"] == pytest.approx(0.0, abs=1e-6)


def test_interference_of_a_mesh_with_itself_is_its_volume(box_stl: Path) -> None:
    result = _run("interference", str(box_stl), str(box_stl))

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["interference_mm3"] == pytest.approx(10 * 20 * 30, rel=0.01)


def test_export_writes_an_stl_and_hashes_it(box_stl: Path, tmp_path: Path) -> None:
    stem = tmp_path / "out"

    result = _run("export", str(box_stl), "--out", str(stem))

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert Path(report["stl_path"]).is_file()
    assert len(report["file_sha256"]) == 64
    assert len(report["geometry_sha256"]) == 64


def test_missing_file_is_an_error_not_a_silent_zero(tmp_path: Path) -> None:
    result = _run("measure", str(tmp_path / "does_not_exist.stl"))

    assert result.returncode != 0


def test_unknown_subcommand_is_a_usage_error() -> None:
    result = _run("nonsense")

    assert result.returncode == 2
    assert "invalid choice" in (result.stderr + result.stdout)


@pytest.mark.skipif(
    importlib.util.find_spec("pyrender") is not None,
    reason="pyrender is installed, so there is no missing-renderer path to take",
)
def test_render_without_a_gl_context_names_what_is_missing(tmp_path: Path) -> None:
    """The renderer is optional. When it is absent the caller must learn that
    pyrender/GL is what failed, rather than an ImportError from three frames
    down inside preview.py.
    """
    from designer_toolkit import render

    with pytest.raises(RuntimeError, match="pyrender"):
        render._render_view(None, None)
