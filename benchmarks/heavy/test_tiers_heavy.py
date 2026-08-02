#!/usr/bin/env python3
"""L0-heavy — the tier guard, shown red, in a real pytest session.

`tools/test_tiers.py` tests the decision as a function, which is what keeps the
guard's own tests inside the rule the guard enforces. This file tests that the
decision is actually *wired*: that a test which starts an interpreter goes red
when it sits in an L0 root, and green when it sits outside one.

It cannot live in `tools/`. Proving that a child interpreter is refused requires
starting a child interpreter, so by its own rule this file belongs here -- which
is the shortest available demonstration that the rule is real.

Everything happens in a temporary tree that mimics the repository's layout and
carries a copy of the real `conftest.py`. Nothing is written into the checkout.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFTEST = REPO_ROOT / "conftest.py"

_SPAWNS = '''
import subprocess, sys
def test_it_starts_an_interpreter():
    subprocess.run([sys.executable, "-c", "pass"], check=True)
'''

_SLEEPS = '''
import time
def test_it_takes_its_time():
    time.sleep({seconds})
'''

_QUIET = '''
def test_it_answers_in_this_process():
    assert 2 + 2 == 4
'''


class _TierSession(unittest.TestCase):
    """One synthetic checkout, one pytest run, one verdict."""

    def _session(self, where: str, name: str, body: str) -> subprocess.CompletedProcess[str]:
        raw = tempfile.TemporaryDirectory()
        self.addCleanup(raw.cleanup)
        room = Path(raw.name)
        # A pyproject makes this directory pytest's rootdir, so the nodeids the
        # guard reads are relative to it exactly as they are in the real repo.
        (room / "pyproject.toml").write_text(
            '[tool.pytest.ini_options]\npythonpath = ["."]\n', encoding="utf-8")
        shutil.copy2(CONFTEST, room / "conftest.py")
        target = room / where
        target.mkdir(parents=True, exist_ok=True)
        (target / name).write_text(textwrap.dedent(body), encoding="utf-8")
        return subprocess.run(
            [sys.executable, "-m", "pytest", where, "-q", "-p", "no:cacheprovider"],
            cwd=str(room), capture_output=True, text=True, check=False)


class ASpawnInsideTheGateIsRefusedTest(_TierSession):
    def test_a_test_that_starts_an_interpreter_goes_red_under_an_l0_root(self) -> None:
        result = self._session("tools", "test_spawner.py", _SPAWNS)
        self.assertNotEqual(0, result.returncode,
                            "the gate accepted a child interpreter:\n" + result.stdout)
        self.assertIn("child process", result.stdout)
        self.assertIn("benchmarks/heavy", result.stdout)
        self.assertIn("python", result.stdout)

    def test_the_other_l0_root_is_guarded_too(self) -> None:
        result = self._session("skills/3d-modeling/scripts", "test_spawner.py", _SPAWNS)
        self.assertNotEqual(0, result.returncode,
                            "only one of the two declared roots is guarded:\n" + result.stdout)
        self.assertIn("child process", result.stdout)

    def test_the_same_test_outside_the_gate_passes(self) -> None:
        """The pair. Without this the guard could be refusing everything."""
        result = self._session("benchmarks/heavy", "test_spawner.py", _SPAWNS)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_git_is_let_through_because_the_guards_that_need_it_measured_45ms(self) -> None:
        body = '''
        import subprocess
        def test_it_asks_git_something():
            subprocess.run(["git", "--version"], capture_output=True, check=False)
        '''
        result = self._session("tools", "test_gitcaller.py", body)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


class TheCeilingIsWiredTest(_TierSession):
    def test_a_slow_test_that_starts_nothing_is_refused(self) -> None:
        result = self._session("tools", "test_slow.py", _SLEEPS.format(seconds=6.0))
        self.assertNotEqual(0, result.returncode,
                            "the ceiling is not wired:\n" + result.stdout)
        self.assertIn("ceiling", result.stdout)

    def test_a_quick_test_that_starts_nothing_is_not(self) -> None:
        result = self._session("tools", "test_quick.py", _QUIET)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


class TheGuardCanBeTurnedOffOnlyOnPurposeTest(_TierSession):
    def test_nothing_in_the_repository_sets_the_escape_hatch(self) -> None:
        """`L0_TIER_GUARD=off` exists for profiling. CI must not set it."""
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertNotIn("L0_TIER_GUARD", workflow)


if __name__ == "__main__":
    unittest.main()
