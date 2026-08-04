#!/usr/bin/env python3
"""L0 — the commit gate, enforced rather than described.

`ROADMAP.md` section 5.1 puts L0 on every commit and L1 on pull requests, and
section 4.4 budgets each. The L0/L1 line is structural: `testpaths` in
`pyproject.toml` names `skills/3d-modeling/scripts` and `tools`, and
`benchmarks/replays` is in neither, so a bare `uv run pytest` cannot collect a
job replay. `benchmarks/heavy` is outside `testpaths` for the same reason and by
the same mechanism -- see `benchmarks/heavy/README.md` for what lives there.

Structure alone decides which tier a file is *collected* in. It cannot decide
whether the file deserves to be there, and that is what this module adds.

**Where the 997 s went.** Profiled at `79244ae` with `--durations=0` and an audit
hook counting process creation per test: of 1163 tests and 1020 s, **194 tests
started a child interpreter and held 876 s of it** -- 86% of the gate, in 17% of
the tests. The remaining 969 tests cost 143 s together, and all but a handful of
those were under 0.2 s. The cost is not spread thin; it is one mechanism, priced
at about 1.6 s a go, because a fresh interpreter that reaches `import trimesh`
costs that on the reference machine (`docs/baseline.md`). Nothing else is close.

So the tier boundary is not a taste question, and it is not left to a decorator
somebody remembers to apply. It is measured while the suite runs:

* `_SPAWN_ALLOWED` -- an L0 test may not start a process. The single exception is
  `git`, which two guards genuinely need (`tools/test_replay.py` reads the head
  commit, `tools/test_fixtures.py` asks `git check-attr`) and which measured
  ~45 ms a call, three orders off an interpreter. Anything else -- `python`,
  `uv`, `design-tool`, the confined build child -- fails the test that started
  it, and names `benchmarks/heavy/` in the failure.
* `L0_TEST_CEILING_S` -- a backstop for the cost a spawn count cannot see. The
  screening corpus was 19 s a test without leaving the process. The slowest test
  left in L0 is 1.7 s, so the ceiling has better than four times the headroom a
  loaded CI runner needs, and it still catches anything of that order.
* `L0_COLLECTED_CEILING` -- the aggregate, and the only one of the three that a
  slow machine cannot move.

**Why the aggregate is counted rather than timed.** Section 4.4's budget is wall
clock, and wall clock on this machine is not stable enough to regress against:
the same 867 tests at the same commit measured 43.3 s and then 76.9 s within one
session, and one change measured +7.2 s, +10.5 s and +0.1 s on three honest
attempts. Two normalisers were considered and both were rejected on evidence.
A ratio to collection time inverts the answer -- `--collect-only` went 2.5 s to
2.2 s across the same drift, so it would have reported a 1.78x slowdown as a 0.9x
improvement, because the drift lands on sustained geometry and mesh work and
never touches an import burst. And a count of tests *over a duration threshold*
is not machine-independent either: 40 tests exceed 0.5 s in the slow regime and
fewer do in the fast one, so the threshold counts the machine.

What does not move is how many tests there are. The gate grows by tests being
added, so the ceiling counts tests -- and it is the regression control, while
section 4.4 keeps its wall-clock number as the product statement, because a
person waits seconds and no ratio changes that.

Neither of the first two guards is a correctness limit, and nor is this one. All
three exist because a budget nobody checks reports all clear exactly as
convincingly as one that holds.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

# Mirrors `testpaths` in `pyproject.toml`; `tools/test_tiers.py` fails if the two
# ever disagree, because a guard that has quietly stopped covering a directory is
# indistinguishable from a directory with nothing to guard.
L0_ROOTS: tuple[str, ...] = ("skills/3d-modeling/scripts", "tools")

# Not a root, and deliberately not reachable from one.
HEAVY_ROOT = "benchmarks/heavy"

_SPAWN_ALLOWED = frozenset({"git"})

L0_TEST_CEILING_S = 5.0

# The gate collected 890 when this was first set, and 1050 was about 18%
# headroom -- room for a release's worth of ordinary fixtures without a
# conversation. That headroom is spent: ADR 0003's datum fixtures took the gate
# past it and this guard refused them, which is the guard working.
#
# Raised to 1240 on the same rule -- about 16% over the 1066 the gate now holds.
# What that costs, measured in one session so the machine's own drift is common
# to every reading: 56.0 s at 1066, against 56.4 s at 1033 on the commit before
# this slice. An intermediate state of the same slice measured 55.4 s and 56.4 s
# at 1052 -- one commit, two readings, a full second apart and in the wrong
# direction. Thirty-three added fixtures are not measurable against that, which
# is the argument for counting tests rather than timing them and is exactly why
# this number and not the wall clock is the control.
#
# 174 tests of headroom cannot hide the mechanism that once took the gate to
# 997 s: that was child interpreters at ~1.6 s each, and `_violation` refuses a
# spawn inside the gate outright rather than pricing it. A raise stays deliberate
# -- it is a line in a diff saying the gate got bigger, with what it costs beside
# it.
L0_COLLECTED_CEILING = 1240

# Set by CI (or by hand) to profile without the gate refusing; the value is
# printed in the failure text so a run that was let through says so.
_OFF = os.environ.get("L0_TIER_GUARD") == "off"

_running: dict[str, object] = {"nodeid": None, "spawns": [], "started": 0.0}


def _executable_name(args: tuple) -> str:
    """The program a `subprocess.Popen` audit event is about, as a bare name.

    The event is `(executable, args, cwd, env)`, and both of the first two are
    load-bearing. `executable` is usually `None`. `args` is the argument *list*
    on POSIX and, on Windows, the joined command line `list2cmdline` produced --
    so reading it as a sequence there yields the last thing that looks like a
    path, which is an argument and not the program. That is not a cosmetic bug:
    it made `git check-attr -- some.stl` report as a spawn of `some.stl`, which
    is not on the allow-list, which failed a guard that was behaving correctly.
    """
    candidate: object = ""
    if args:
        candidate = args[0] or ""
    if not candidate and len(args) > 1 and args[1]:
        argv = args[1]
        candidate = argv[0] if isinstance(argv, (list, tuple)) else argv
    if isinstance(candidate, str):
        candidate = _first_word(candidate)
    try:
        name = Path(os.fsdecode(candidate)).name.lower()
    except (TypeError, ValueError):
        return "<unreadable>"
    return name[:-4] if name.endswith(".exe") else name


def _first_word(line: str) -> str:
    """The program out of a Windows command line, quoted or not."""
    line = line.strip()
    if line.startswith('"'):
        close = line.find('"', 1)
        return line[1:close] if close > 0 else line[1:]
    return line.split(" ", 1)[0]


def _audit(event: str, args: tuple) -> None:
    # An audit hook cannot be removed and runs on every audited call in the
    # process, so it does the least possible work and never raises: an exception
    # here would surface as a failure in whatever the interpreter was doing.
    if event != "subprocess.Popen" or _running["nodeid"] is None:
        return
    try:
        name = _executable_name(args)
    except Exception:                                       # pragma: no cover
        name = "<unreadable>"
    if name not in _SPAWN_ALLOWED:
        _running["spawns"].append(name)                     # type: ignore[union-attr]


sys.addaudithook(_audit)


def _is_l0(nodeid: str) -> bool:
    """Which tier a test is in, decided by where its file is. Nothing else."""
    path = nodeid.replace("\\", "/")
    return any(path.startswith(f"{root}/") for root in L0_ROOTS)


def _violation(nodeid: str, spawns: list[str], elapsed: float) -> str | None:
    """The message, as a pure function, so `tools/test_tiers.py` can test it."""
    if spawns:
        seen = ", ".join(sorted(set(spawns)))
        return (
            f"{nodeid} started {len(spawns)} child process(es) ({seen}).\n"
            f"L0 runs on every commit and a child interpreter costs ~1.6 s of it. "
            f"Move this test to {HEAVY_ROOT}/, which runs before merge, or make it "
            f"answer in this process. See conftest.py and {HEAVY_ROOT}/README.md."
        )
    if elapsed > L0_TEST_CEILING_S:
        return (
            f"{nodeid} took {elapsed:.1f}s, over the {L0_TEST_CEILING_S:.0f}s L0 "
            f"ceiling. It starts no process, so it is doing the expensive work "
            f"itself -- a corpus, a B-rep read, or a run repeated. Move it to "
            f"{HEAVY_ROOT}/ or shrink what it measures."
        )
    return None


def pytest_runtest_logstart(nodeid: str, location) -> None:  # noqa: ANN001
    # Reset here rather than in the call wrapper: a module- or class-scoped
    # fixture spawns during setup, and a counter that started at `call` would
    # miss the most expensive fixtures in the repository.
    _running["nodeid"] = nodeid if _is_l0(nodeid) else None
    _running["spawns"] = []
    _running["started"] = time.perf_counter()


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item):
    result = yield
    if _OFF or not _is_l0(item.nodeid):
        return result
    elapsed = time.perf_counter() - float(_running["started"])  # type: ignore[arg-type]
    complaint = _violation(item.nodeid, list(_running["spawns"]), elapsed)  # type: ignore[arg-type]
    if complaint:
        raise AssertionError(complaint)
    return result


def pytest_runtest_logfinish(nodeid: str, location) -> None:  # noqa: ANN001
    _running["nodeid"] = None


def over_ceiling(collected: int) -> str | None:
    """The complaint for a gate that has grown past its ceiling, or None.

    Split out from the hook so `tools/test_tiers.py` can test the decision
    without collecting 890 tests to do it.
    """
    if collected <= L0_COLLECTED_CEILING:
        return None
    return (
        f"the L0 gate collected {collected} tests, over the ceiling of "
        f"{L0_COLLECTED_CEILING}. This is the aggregate guard: a slow machine "
        f"cannot move it and a wall-clock budget cannot hold it. Either move the "
        f"new tests to {HEAVY_ROOT}/, or raise L0_COLLECTED_CEILING in "
        f"conftest.py deliberately and say in the commit what the gate now costs."
    )


def pytest_collection_modifyitems(session, config, items) -> None:  # noqa: ANN001
    """Count what the gate collected, once, after collection settles."""
    if _OFF:
        return
    # Only when the gate itself is being run. A targeted `pytest path::Test` or a
    # heavy/replay invocation collects a subset, and a ceiling applied to a subset
    # would fire on nothing and pass on everything.
    if config.args and set(config.args) != set(L0_ROOTS):
        return
    complaint = over_ceiling(sum(1 for item in items if _is_l0(item.nodeid)))
    if complaint:
        raise pytest.UsageError(complaint)
