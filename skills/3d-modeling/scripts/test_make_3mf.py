"""Tests for make_3mf.py, which writes a deliverable.

A 3MF is the file the user actually loads into a slicer, so a malformed one is
not a caught error -- it is a broken hand-off discovered at the printer. These
assert the archive shape (OPC requires the content types and rels members), the
per-part component structure multi-colour printing depends on, and that the
result loads back with the geometry that went in.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import trimesh

SCRIPT = Path(__file__).resolve().parent / "make_3mf.py"


def _stl(path: Path, extents=(10, 10, 10), translate=(0, 0, 0)) -> trimesh.Trimesh:
    mesh = trimesh.creation.box(extents=extents)
    mesh.apply_translation(translate)
    mesh.export(path)
    return mesh


def _run(out: Path, *specs: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(out), *specs],
        capture_output=True, text=True, check=False,
    )


def test_two_parts_become_one_object_with_two_components(tmp_path: Path) -> None:
    body, pattern = tmp_path / "body.stl", tmp_path / "pattern.stl"
    _stl(body)
    _stl(pattern, translate=(20, 0, 0))
    out = tmp_path / "combined.3mf"

    result = _run(out, f"Body={body}", f"Pattern={pattern}")

    assert result.returncode == 0, result.stderr
    assert out.is_file()
    with zipfile.ZipFile(out) as archive:
        names = archive.namelist()
        # OPC packaging: without these two a slicer rejects the file outright.
        assert "[Content_Types].xml" in names
        assert "_rels/.rels" in names
        model = next(n for n in names if n.endswith("3dmodel.model"))
        xml = archive.read(model).decode("utf-8")
    # One object per part, plus the build object that references them.
    assert xml.count("<component objectid=") == 2
    assert 'name="Body"' in xml and 'name="Pattern"' in xml


def test_written_geometry_matches_the_source_mesh(tmp_path: Path) -> None:
    """Asserted from the emitted XML, so this runs on the core stack: reading a
    3MF back needs lxml and networkx, which writing one does not.
    """
    source = _stl(tmp_path / "cube.stl", extents=(12, 8, 4))
    welded = trimesh.load(tmp_path / "cube.stl", process=True)
    out = tmp_path / "single.3mf"

    assert _run(out, f"Cube={tmp_path / 'cube.stl'}").returncode == 0

    with zipfile.ZipFile(out) as archive:
        xml = archive.read(next(n for n in archive.namelist() if n.endswith("3dmodel.model"))).decode("utf-8")
    assert xml.count("<vertex ") == len(welded.vertices)
    assert xml.count("<triangle ") == len(welded.faces) == len(source.faces)
    # Every extreme of the source box survives into the written vertices.
    for axis, low, high in zip("xyz", source.bounds[0], source.bounds[1]):
        assert f'{axis}="{low:.6g}"' in xml and f'{axis}="{high:.6g}"' in xml


@pytest.mark.skipif(
    any(importlib.util.find_spec(m) is None for m in ("lxml", "networkx")),
    reason="reading a 3MF back needs lxml + networkx; writing one does not",
)
def test_result_reloads_with_the_geometry_that_went_in(tmp_path: Path) -> None:
    source = _stl(tmp_path / "cube.stl", extents=(12, 8, 4))
    out = tmp_path / "single.3mf"

    assert _run(out, f"Cube={tmp_path / 'cube.stl'}").returncode == 0

    loaded = trimesh.load(out)
    geometry = max(loaded.geometry.values(), key=lambda g: len(g.faces)) if hasattr(loaded, "geometry") else loaded
    assert geometry.bounding_box.extents.tolist() == source.bounding_box.extents.tolist()


def test_non_watertight_part_is_warned_about_not_silently_accepted(tmp_path: Path) -> None:
    open_mesh = trimesh.Trimesh(
        vertices=[[0, 0, 0], [10, 0, 0], [10, 10, 0]], faces=[[0, 1, 2]], process=False
    )
    path = tmp_path / "open.stl"
    open_mesh.export(path)
    out = tmp_path / "open.3mf"

    result = _run(out, f"Open={path}")

    assert result.returncode == 0  # still written -- the caller may want it
    assert "not watertight" in result.stdout.lower()


def test_usage_error_when_a_spec_has_no_equals(tmp_path: Path) -> None:
    result = _run(tmp_path / "x.3mf", "no_equals_sign.stl")

    assert result.returncode != 0
    assert "Usage" in (result.stdout + result.stderr)
