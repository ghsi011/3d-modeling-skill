"""Tests for the CadQuery runner's contract.

The runner spawns a model script in a subprocess and reports a structured JSON
result. Everything asserted here -- the exit codes docs/tooling.md publishes,
the JSON keys agents parse, the timeout path -- is the runner's own logic, not
CadQuery's, so it all runs on the core stack: the script it launches is a plain
Python file. The CAD-specific behaviour stays covered by skipUnless elsewhere.

The timeout and strict-watertight exits had no coverage at all despite being
documented exit codes, which is the class of promise most likely to rot.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "run_cadquery_model.py"


def _run(*args: str, timeout: int = 90) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, check=False, timeout=timeout,
    )


def _model(tmp_path: Path, body: str, name: str = "model.py") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_help_documents_the_exit_codes() -> None:
    result = _run("--help")

    assert result.returncode == 0
    assert "timeout" in result.stdout.lower()


def test_successful_script_reports_success_json(tmp_path: Path) -> None:
    script = _model(tmp_path, "print('built')\n")

    result = _run(str(script))

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["success"] is True
    assert report["returncode"] == 0


def test_failing_script_is_reported_not_raised(tmp_path: Path) -> None:
    """A model script that raises is data for the designer to act on, not a
    crash of the runner: the JSON must still parse and carry the traceback.
    """
    script = _model(tmp_path, "raise ValueError('bad sketch')\n")

    result = _run(str(script))

    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["success"] is False
    assert report["returncode"] != 0
    assert "bad sketch" in json.dumps(report)


def test_timeout_exits_three(tmp_path: Path) -> None:
    script = _model(tmp_path, "import time\ntime.sleep(30)\n")

    result = _run(str(script), "--timeout", "2")

    assert result.returncode == 3, result.stdout
    report = json.loads(result.stdout)
    assert report["success"] is False
    assert "timeout" in json.dumps(report).lower()


def test_missing_script_is_an_error(tmp_path: Path) -> None:
    result = _run(str(tmp_path / "no_such_model.py"))

    assert result.returncode != 0


def test_emitted_json_carries_the_keys_agents_parse(tmp_path: Path) -> None:
    script = _model(tmp_path, "pass\n")

    report = json.loads(_run(str(script)).stdout)

    for key in ("success", "returncode", "stdout", "stderr"):
        assert key in report, f"{key} missing from the runner's JSON contract"
