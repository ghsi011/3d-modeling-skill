"""Smoke tests for `python -m designer_toolkit`.

The designer's required reading tells it to run this CLI rather than re-author
the measurement patterns, so broken wiring sends the role back to hand-rolling
the thing the toolkit exists to prevent -- which is exactly what three measured
runs did.

The surface is deliberately two subcommands. These check that `commission`
reaches the gate with its flags intact, that `coupon` still works, and that a
bad invocation is a usage error rather than a traceback.
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


def _plan_for(x: float, y: float, z: float) -> dict:
    from designer_toolkit import plan

    return plan.direct_template((x, y, z), job_id="t")


@pytest.fixture(scope="module")
def box_stl(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("cli") / "box.stl"
    mesh = trimesh.creation.box(extents=(10, 20, 30))
    mesh.apply_translation((0, 0, 15))
    mesh.export(path)
    return path


def test_the_surface_is_the_gate_and_the_coupon() -> None:
    """Offering the checks individually is what taught three runs to assemble
    their own verification script instead of running the gate."""
    result = _run("--help")

    assert result.returncode == 0, result.stderr
    assert "commission" in result.stdout
    assert "coupon" in result.stdout
    # Absence from --help would also hold for a hidden-but-working subcommand,
    # so invoke one and require the parser to reject it outright.
    for retired in ("measure", "overhang", "datums", "sweep", "finalize"):
        assert retired not in result.stdout
        rejected = _run(retired, "anything.stl")
        assert rejected.returncode == 2, retired
        assert "invalid choice" in (rejected.stderr + rejected.stdout), retired


def test_commission_reaches_the_gate_with_its_flags_intact(box_stl: Path, tmp_path: Path) -> None:
    """The wrapper forwards argv verbatim rather than re-declaring the flags, so
    this is what proves it has not drifted from the gate it fronts."""
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(_plan_for(10, 20, 30)), encoding="utf-8")
    out = tmp_path / "out"

    result = _run("commission", "--stl", str(box_stl), "--plan", str(plan_path),
                  "--out", str(out), "--no-render", "--job-id", "t",
                  "--updated-utc", "2026-01-01T00:00:00Z")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["verdict"] == "PASS"
    assert (out / "candidate_readiness.md").is_file()


def test_a_failing_candidate_exits_nonzero_through_the_wrapper(box_stl: Path,
                                                               tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(_plan_for(10, 20, 99)), encoding="utf-8")

    result = _run("commission", "--stl", str(box_stl), "--plan", str(plan_path),
                  "--out", str(tmp_path / "out"), "--no-render", "--job-id", "t",
                  "--updated-utc", "2026-01-01T00:00:00Z")

    assert result.returncode == 1
    assert "FAIL envelope" in result.stderr


def test_missing_file_is_an_error_not_a_silent_zero(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(_plan_for(10, 20, 30)), encoding="utf-8")

    result = _run("commission", "--stl", str(tmp_path / "does_not_exist.stl"),
                  "--plan", str(plan_path), "--out", str(tmp_path / "out"),
                  "--no-render", "--job-id", "t", "--updated-utc", "2026-01-01T00:00:00Z")

    # `returncode != 0` alone would also be satisfied by an unrelated import
    # error, so require the message to name the missing file.
    assert result.returncode != 0
    combined = result.stderr + result.stdout
    assert "does_not_exist" in combined, combined[-2000:]


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
