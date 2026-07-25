"""Tests for the backend-neutral CAD interface."""

from __future__ import annotations

import builtins
import importlib
import sys
from pathlib import Path
from types import ModuleType
from typing import Final

import pytest

BLOCKED_OPTIONAL_CAD_MODULES: Final[frozenset[str]] = frozenset(
    {"cadquery", "build123d", "FreeCAD"},
)


def test_import_backends_when_optional_cad_modules_are_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Given no CAD deps, When importing backends, Then the common contract loads."""
    real_import = builtins.__import__

    def guarded_import(
        name: str,
        globals_: dict[str, ModuleType] | None = None,
        locals_: dict[str, ModuleType] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> ModuleType:
        root_name = name.split(".", maxsplit=1)[0]
        if root_name in BLOCKED_OPTIONAL_CAD_MODULES:
            pytest.fail(f"backends import tried to load optional CAD module {root_name}")
        return real_import(name, globals_, locals_, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.delitem(sys.modules, "backends", raising=False)

    imported = importlib.import_module("backends")

    assert imported.ModelBackend.__name__ == "ModelBackend"


def test_import_cadquery_backend_when_cadquery_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Given no CadQuery dep, When importing adapter, Then no CAD import happens."""
    real_import = builtins.__import__

    def guarded_import(
        name: str,
        globals_: dict[str, ModuleType] | None = None,
        locals_: dict[str, ModuleType] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> ModuleType:
        root_name = name.split(".", maxsplit=1)[0]
        if root_name == "cadquery":
            pytest.fail("cadquery_backend import tried to load cadquery")
        return real_import(name, globals_, locals_, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.delitem(sys.modules, "backends.cadquery_backend", raising=False)

    imported = importlib.import_module("backends.cadquery_backend")

    assert imported.CadQueryBackend.__name__ == "CadQueryBackend"


def test_cadquery_backend_exports_stl_and_step_when_cadquery_installed(
    tmp_path: Path,
) -> None:
    """Given CadQuery, When build+export runs, Then STL and STEP are written."""
    cq = pytest.importorskip("cadquery")
    from backends.cadquery_backend import CadQueryBackend

    def build_box(edge_mm: float):
        return cq.Workplane("XY").box(edge_mm, edge_mm, edge_mm)

    backend = CadQueryBackend(builder=build_box)

    solid = backend.build(10.0)
    exports = backend.export(solid, tmp_path / "box")

    assert exports["stl"] == tmp_path / "box.stl"
    assert exports["step"] == tmp_path / "box.step"
    assert exports["stl"].exists()
    assert exports["step"].exists()


def test_fake_backend_exports_stl_and_step_paths(tmp_path: Path) -> None:
    """Given a fake backend, When build+export runs, Then STL and STEP keys exist."""
    from backends import FakeBackend, FakeBuildParams

    backend = FakeBackend()
    solid = backend.build(FakeBuildParams(label="bracket"))

    exports = backend.export(solid, tmp_path / "bracket")

    assert exports["stl"] == tmp_path / "bracket.stl"
    assert exports["step"] == tmp_path / "bracket.step"
    assert exports["stl"].exists()
    assert exports["step"].exists()


def test_incomplete_backend_raises_type_error() -> None:
    """Given a backend missing export, When instantiated, Then ABC rejects it."""
    from backends import FakeBuildParams, FakeSolid, ModelBackend

    class MissingExportBackend(ModelBackend[FakeBuildParams, FakeSolid]):
        def build(self, params: FakeBuildParams) -> FakeSolid:
            return FakeSolid(label=params.label)

    with pytest.raises(TypeError):
        type.__call__(MissingExportBackend)


def test_freecad_mcp_available_returns_false_without_probe() -> None:
    """Given no FreeCAD MCP probe, When availability is checked, Then CI-safe False returns."""
    from backends.freecad_backend import freecad_mcp_available

    assert freecad_mcp_available() is False


def test_freecad_mcp_available_returns_false_when_probe_errors() -> None:
    """Given an unavailable probe, When availability is checked, Then False returns."""
    from backends.freecad_backend import freecad_mcp_available

    class UnavailableProbe:
        def list_documents(self) -> tuple[str, ...]:
            raise ConnectionError

    assert freecad_mcp_available(UnavailableProbe()) is False


def test_stage_freecad_exports_copies_artifacts_without_freecad(tmp_path: Path) -> None:
    """Given exported files, When staging runs, Then artifact paths are copied into staging."""
    from backends.freecad_backend import FreeCadExportPaths, stage_freecad_exports

    exported_stl = tmp_path / "freecad-output.stl"
    exported_step = tmp_path / "freecad-output.step"
    exported_stl.write_text("solid freecad\nendsolid freecad\n", encoding="utf-8")
    exported_step.write_text("ISO-10303-21;\n", encoding="utf-8")

    staged = stage_freecad_exports(
        FreeCadExportPaths(stl=exported_stl, step=exported_step),
        tmp_path / "staged",
    )

    assert staged.stl == tmp_path / "staged" / "freecad-output.stl"
    assert staged.step == tmp_path / "staged" / "freecad-output.step"
    assert staged.stl.read_text(encoding="utf-8") == exported_stl.read_text(encoding="utf-8")
    assert staged.step.read_text(encoding="utf-8") == exported_step.read_text(encoding="utf-8")


def test_stage_freecad_exports_reports_missing_artifact(tmp_path: Path) -> None:
    """Given a missing exported file, When staging runs, Then a typed staging error is raised."""
    from backends.freecad_backend import FreeCadExportPaths, FreeCadStageError, stage_freecad_exports

    exported_step = tmp_path / "freecad-output.step"
    exported_step.write_text("ISO-10303-21;\n", encoding="utf-8")

    with pytest.raises(FreeCadStageError) as error:
        stage_freecad_exports(
            FreeCadExportPaths(stl=tmp_path / "missing.stl", step=exported_step),
            tmp_path / "staged",
        )

    assert error.value.path == tmp_path / "missing.stl"
