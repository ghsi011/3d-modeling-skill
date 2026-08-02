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

Neither guard is a correctness limit. Both exist because a budget nobody checks
reports all clear exactly as convincingly as one that holds.
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
