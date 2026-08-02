"""Tests for `dt.py audit` — the verifier's mechanical half, in one call.

The charter used to ask for six commands and justified the expensive one by
saying it "has never once disagreed". That is an argument for collapsing the
chain, not for trusting it, so these tests hold the collapsed version to what
the six were actually for: noticing that the delivered bytes are not the ones
the receipt describes, and noticing it whichever way the substitution happened.

The half of this file the commit gate will not carry is in
`benchmarks/heavy/test_audit_heavy.py`, and runs before merge instead of on
every push: `TestAudit`. Same tests, moved rather than weakened; `conftest.py`
carries the rule and `benchmarks/heavy/README.md` the measurement behind it.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

try:
    import trimesh
except ImportError:  # pragma: no cover
    trimesh = None

SCRIPTS = Path(__file__).resolve().parents[1]
LAUNCHER = SCRIPTS / "dt.py"

_CLIP = [
    "--param", "bore_d=12.0", "--param", "wall=3.0", "--param", "height=9.0",
    "--param", "mouth_gap=9.0", "--param", "flange=(40.0, 22.0, 5.0)",
    "--param", "screw_d=4.5", "--param", "screw_at=(8.0, 11.0)",
    "--param", "countersink_d=9.0",
]


def _dt(*args, cwd=None):
    return subprocess.run([sys.executable, str(LAUNCHER), *args], cwd=cwd,
                          capture_output=True, text=True, check=False)


def _built_project(root: Path) -> Path:
    """A real gated candidate: the whole thing a verifier is handed.

    The intake, plan, build and commission utilities leave the same complete
    project that the verifier audits, without a second orchestration route.
    """
    project = root / "job"
    timestamp = "1970-01-01T00:00:00Z"
    _dt("intake", "--job-id", "a", "--template", "c_clip", *_CLIP,
        "--updated-utc", timestamp, "--out", str(project),
        "--rationale", "a benchmark fixture", "--acceptance", "nothing")
    _dt("plan", "template", "--bbox", "40", "22", "14", "--job-id", "a",
        "--updated-utc", timestamp, "--out", str(project / "print_plan_checks.json"))
    _dt("build", "--template", "c_clip", *_CLIP, "--out", str(project / "model.py"))
    _dt("commission", "--model", "model.py", "--plan", "print_plan_checks.json",
        "--out", ".", "--job-id", "a", "--updated-utc", timestamp, "--no-render",
        cwd=project)
    return project


def _audit(project: Path, out: Path, reference: str | None = None):
    args = ["audit", str(project), "--out", str(out), "--job-id", "a",
            "--updated-utc", "1970-01-01T00:00:00Z"]
    if reference is not None:
        args += ["--reference", reference]
    done = _dt(*args)
    payload = json.loads(done.stdout) if done.stdout.strip().startswith("{") else None
    return done, payload


def _by_id(payload):
    return {c["id"]: c["result"] for c in payload["checks"]}


class TestStructuralAbsence(unittest.TestCase):
    def test_the_render_row_is_ignored_in_both_directions(self) -> None:
        """A successful render adds no check at all; this recomputation passes
        --no-render and always reports one. Comparing them manufactures a
        disagreement out of the verifier not being the one drawing pictures."""
        from .audit import _compare

        designer = {"checks": [{"id": "solid", "result": "PASS"}]}
        mine = {"checks": [{"id": "solid", "result": "PASS"},
                           {"id": "render", "result": "SKIPPED"}]}

        self.assertEqual([], _compare(designer, mine))
        self.assertEqual([], _compare(mine, designer))

    def test_only_named_checks_may_go_missing(self) -> None:
        """Treating "absent" as "fine" in general is how a recomputation comes
        back quietly emptier than the run it is checking."""
        from .audit import _structurally_absent

        for check_id in ("step", "render", "static-wall", "static-envelope"):
            self.assertTrue(_structurally_absent(check_id), check_id)
        for check_id in ("solid", "envelope", "fit", "repair", "feature-screw",
                         "support-S-01", "edge-E-01"):
            self.assertFalse(_structurally_absent(check_id), check_id)


if __name__ == "__main__":
    unittest.main()
