#!/usr/bin/env python3
"""L0 for the tier boundary: the guard, shown refusing, without a subprocess.

`conftest.py` is the only thing standing between "the commit gate is five
seconds" and "the commit gate is whatever anybody last added to it". It is
therefore the same shape as `tools/test_check_internal_links.py` and
`tools/test_replay.py`: a check nobody checks reports all clear exactly as
convincingly when it is broken.

Everything here is a pure function call or a file read, so the guard's own tests
obey the guard. The end-to-end proof -- a real pytest session, over a real test
that starts a real interpreter, going red -- costs a child interpreter and
therefore lives where the rule says it must, in
`benchmarks/heavy/test_tiers_heavy.py`.

Each guard gets the pair: the thing it lets through, and the thing it stops.
"""
from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

import conftest as GATE

ROOT = Path(__file__).resolve().parents[1]


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


class TheTierIsDecidedByThePathTest(unittest.TestCase):
    """Which tier a test is in is a fact about where its file is, and nothing else."""

    def test_a_test_under_a_declared_root_is_l0(self) -> None:
        self.assertTrue(GATE._is_l0("tools/test_tiers.py::T::test_x"))
        self.assertTrue(GATE._is_l0(
            "skills/3d-modeling/scripts/pipeline/test_pipeline.py::T::test_x"))

    def test_a_test_outside_them_is_not(self) -> None:
        self.assertFalse(GATE._is_l0("benchmarks/heavy/test_phase3_heavy.py::T::test_x"))
        self.assertFalse(GATE._is_l0("benchmarks/replays/test_l1_replay.py::T::test_x"))

    def test_a_windows_nodeid_reaches_the_same_answer(self) -> None:
        """pytest reports posix separators; a caller assembling one may not."""
        self.assertTrue(GATE._is_l0(r"tools\test_tiers.py::T::test_x"))

    def test_a_root_is_a_directory_prefix_and_not_a_string_prefix(self) -> None:
        """`toolsomething/` is not `tools/`, and neither is a file called `tools`."""
        self.assertFalse(GATE._is_l0("toolsmith/test_x.py::T::test_y"))


class TheDeclaredRootsAreTheCollectedOnesTest(unittest.TestCase):
    """The guard's idea of L0 and pytest's must be the same set.

    They are stated twice because pytest reads one of them and Python reads the
    other, and there is no way to have only one. So the drift is what gets
    tested: a root added to `testpaths` and not to `conftest.py` would be
    collected on every commit with no guard on it at all, and nothing about the
    run would look different.
    """

    def test_the_guard_covers_exactly_what_pytest_collects(self) -> None:
        testpaths = _pyproject()["tool"]["pytest"]["ini_options"]["testpaths"]
        self.assertEqual(sorted(testpaths), sorted(GATE.L0_ROOTS))

    def test_neither_heavy_nor_replays_is_collected_by_a_bare_run(self) -> None:
        testpaths = _pyproject()["tool"]["pytest"]["ini_options"]["testpaths"]
        for outside in (GATE.HEAVY_ROOT, "benchmarks/replays"):
            self.assertNotIn(outside, testpaths)
            for root in GATE.L0_ROOTS:
                self.assertFalse(outside.startswith(f"{root}/"),
                                 f"{outside} is inside {root}, so a bare run collects it")


class TheSpawnGuardTest(unittest.TestCase):
    """What the audit hook is looking at, and what it decides about it."""

    def test_the_executable_is_read_off_the_event_either_way_it_is_given(self) -> None:
        # `subprocess.Popen` audits as (executable, args, cwd, env); either of
        # the first two carries the program, depending on how it was called.
        self.assertEqual("python", GATE._executable_name((r"C:\venv\Scripts\python.exe", None)))
        self.assertEqual("git", GATE._executable_name((None, ["git", "rev-parse", "HEAD"])))
        self.assertEqual("uv", GATE._executable_name(("/usr/bin/uv", None)))

    def test_a_windows_command_line_is_not_read_as_a_list_of_paths(self) -> None:
        """On Windows `args` is the joined command line, not the argv list.

        Reading it as a sequence takes the *last* thing that looks like a path,
        which is an argument. `git check-attr -- some.stl` reported as a spawn of
        `some.stl`, and a guard that was working correctly went red on it.
        """
        self.assertEqual("git", GATE._executable_name(
            (None, "git check-attr -a -- tesla-vent-mount-17mm-ball.stl")))
        self.assertEqual("python", GATE._executable_name(
            (None, r'"C:\Program Files\Py\python.exe" -m pytest')))

    def test_an_unreadable_event_is_a_name_and_never_an_exception(self) -> None:
        """An audit hook that raises fails whatever the interpreter was doing."""
        self.assertEqual("<unreadable>", GATE._executable_name((object(), None)))

    def test_git_is_the_one_program_l0_may_start(self) -> None:
        self.assertEqual(frozenset({"git"}), GATE._SPAWN_ALLOWED)

    def test_a_spawn_fails_the_test_that_made_it_and_says_where_to_put_it(self) -> None:
        message = GATE._violation("tools/test_x.py::T::test_y", ["python"], 0.1)
        self.assertIsNotNone(message)
        self.assertIn("python", message)
        self.assertIn(GATE.HEAVY_ROOT, message)

    def test_a_test_that_starts_nothing_and_is_quick_is_not_complained_about(self) -> None:
        self.assertIsNone(GATE._violation("tools/test_x.py::T::test_y", [], 0.1))


class TheCeilingTest(unittest.TestCase):
    """The cost a spawn count cannot see."""

    def test_a_long_test_that_started_no_process_is_still_refused(self) -> None:
        message = GATE._violation("tools/test_x.py::T::test_y", [],
                                  GATE.L0_TEST_CEILING_S + 0.1)
        self.assertIsNotNone(message)
        self.assertIn(GATE.HEAVY_ROOT, message)

    def test_the_ceiling_leaves_room_for_a_slower_machine(self) -> None:
        """1.7 s is the slowest L0 test measured at `79244ae`; CI is not this box."""
        self.assertGreaterEqual(GATE.L0_TEST_CEILING_S, 4 * 1.7 / 2)
        self.assertIsNone(GATE._violation("tools/test_x.py::T::test_y", [], 3.4))


class TheHeavyTierIsRunBySomebodyTest(unittest.TestCase):
    """A tier nobody runs is worse than no tier: it reports all clear."""

    def test_the_heavy_tier_exists_and_holds_tests(self) -> None:
        heavy = ROOT / GATE.HEAVY_ROOT
        self.assertTrue(heavy.is_dir(), f"{GATE.HEAVY_ROOT} is missing")
        self.assertTrue(sorted(heavy.glob("test_*.py")),
                        "the heavy tier collects nothing, so it gates nothing")

    def test_ci_runs_it(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn(GATE.HEAVY_ROOT, workflow,
                      "nothing in CI runs the heavy tier; a suite nobody runs "
                      "reports all clear")

    def test_ci_runs_the_commit_gate_and_the_replays_too(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("benchmarks/replays", workflow)
        self.assertIn("uv run pytest\n", workflow)

    def test_the_heavy_tier_documents_itself(self) -> None:
        self.assertTrue((ROOT / GATE.HEAVY_ROOT / "README.md").is_file())


if __name__ == "__main__":
    unittest.main()


class TheAggregateCeilingTest(unittest.TestCase):
    """The one tier guard a slow machine cannot move.

    Wall clock cannot carry section 4.4's budget as a regression control: the
    same 867 tests at one commit measured 43.3 s and 76.9 s in a single session.
    Neither can a ratio to collection time -- collection went 2.5 s to 2.2 s
    across that same drift, so it would have called a 1.78x slowdown a 0.9x
    improvement. Nor a count of tests over a duration threshold, which counts
    the machine: 40 tests exceed 0.5 s slow and fewer do fast. What is left is
    how many tests there are.
    """

    def test_a_gate_inside_its_ceiling_is_not_complained_about(self) -> None:
        self.assertIsNone(GATE.over_ceiling(GATE.L0_COLLECTED_CEILING))
        self.assertIsNone(GATE.over_ceiling(1))

    def test_a_gate_over_its_ceiling_says_what_to_do(self) -> None:
        complaint = GATE.over_ceiling(GATE.L0_COLLECTED_CEILING + 1)
        self.assertIsNotNone(complaint)
        assert complaint is not None
        self.assertIn(str(GATE.L0_COLLECTED_CEILING), complaint)
        self.assertIn(GATE.HEAVY_ROOT, complaint)
        self.assertIn("L0_COLLECTED_CEILING", complaint)

    def test_the_ceiling_leaves_room_and_is_not_a_blank_cheque(self) -> None:
        # Guards the number itself. Too tight and an ordinary release trips it;
        # too loose and the mechanism that took the gate to 997 s returns unseen.
        collected = 890  # what the gate held when the ceiling was set
        headroom = GATE.L0_COLLECTED_CEILING - collected
        self.assertGreater(headroom, 100, "no room for a release of fixtures")
        self.assertLess(headroom, collected // 2, "that is not a ceiling")
