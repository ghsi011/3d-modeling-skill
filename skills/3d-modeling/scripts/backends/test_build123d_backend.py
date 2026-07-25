"""Tests for the build123d CAD backend adapter."""

from __future__ import annotations

import builtins
import importlib
import sys
from pathlib import Path
from types import ModuleType

import pytest


def test_build123d_backend_import_is_lazy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Given no build123d dep, When importing adapter, Then import still succeeds."""
    real_import = builtins.__import__

    def guarded_import(
        name: str,
        globals_: dict[str, ModuleType] | None = None,
        locals_: dict[str, ModuleType] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> ModuleType:
        root_name = name.split(".", maxsplit=1)[0]
        if root_name == "build123d":
            pytest.fail("build123d_backend import tried to load build123d")
        return real_import(name, globals_, locals_, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.delitem(sys.modules, "backends.build123d_backend", raising=False)

    imported = importlib.import_module("backends.build123d_backend")

    assert imported.Build123dBackend.__name__ == "Build123dBackend"


def test_build123d_backend_uses_build123d_exporters(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Given fake build123d, When exporting, Then STL and STEP exporters run."""
    from backends import FakeBuildParams, FakeSolid
    from backends.build123d_backend import Build123dBackend

    exporter_calls: list[tuple[str, str, Path, float | None, float | None]] = []
    fake_build123d = ModuleType("build123d")

    def export_stl(
        solid: FakeSolid,
        file_path: Path,
        *,
        tolerance: float,
        angular_tolerance: float,
    ) -> bool:
        exporter_calls.append(("stl", solid.label, Path(file_path), tolerance, angular_tolerance))
        return True

    def export_step(solid: FakeSolid, file_path: Path) -> bool:
        exporter_calls.append(("step", solid.label, Path(file_path), None, None))
        return True

    setattr(fake_build123d, "export_stl", export_stl)
    setattr(fake_build123d, "export_step", export_step)
    monkeypatch.setitem(sys.modules, "build123d", fake_build123d)

    backend = Build123dBackend[FakeBuildParams, FakeSolid](
        builder=lambda params: FakeSolid(label=params.label),
    )
    solid = backend.build(FakeBuildParams(label="hinge"))

    exports = backend.export(solid, tmp_path / "hinge")

    assert exports == {"stl": tmp_path / "hinge.stl", "step": tmp_path / "hinge.step"}
    assert exporter_calls == [
        ("stl", "hinge", tmp_path / "hinge.stl", 0.01, 0.1),
        ("step", "hinge", tmp_path / "hinge.step", None, None),
    ]


def test_build123d_backend_exports_real_box_when_build123d_is_installed(
    tmp_path: Path,
) -> None:
    """Given build123d installed, When exporting a box, Then artifacts are written."""
    build123d = pytest.importorskip("build123d")
    from backends.build123d_backend import Build123dBackend

    def build_box(_label: str):
        with build123d.BuildPart() as box_builder:
            build123d.Box(1, 1, 1)
        return box_builder.part

    backend = Build123dBackend[str, build123d.Part](builder=build_box)
    solid = backend.build("box")

    exports = backend.export(solid, tmp_path / "box")

    assert exports["stl"].exists()
    assert exports["step"].exists()
