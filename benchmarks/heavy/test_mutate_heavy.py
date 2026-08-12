#!/usr/bin/env python3
"""The mutation harness's real runner, which costs a process per mutation.

`tools/test_mutate.py` covers everything about the harness that can be decided
without starting anything: anchors, the restore, the refusals, the verdict logic
with an injected runner. What it deliberately cannot cover is
`mutate.pytest_runner`, because `conftest.py` allows an L0 test to spawn only
`git`, and the whole point of that runner is that it starts `pytest`.

So this is the seam test. It builds a throwaway project -- one source file, one
test that asserts something about it -- and sweeps a real mutation through the real
runner, in both directions: a test that notices the mutation kills it, and a test
that does not notice lets it survive. A harness whose runner reported the same
verdict either way would pass every fixture in the L0 file, since those inject
their own.

Two children per case, so it is heavy rather than L0 -- and cheap as heavy tests
go: no CAD kernel, no build, no confinement.
"""
from __future__ import annotations

import importlib.util
import os
import py_compile
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools import mutate as MU  # noqa: E402

# The subject: a function with a guard, and the guard is what gets mutated out.
SOURCE = '''def clamp(value):
    if value < 0:
        return 0
    return value
'''

ANCHOR = "    if value < 0:\n        return 0\n"

# One test that would notice the guard going away, and one that would not.
WATCHFUL = '''from subject import clamp


def test_negatives_are_clamped():
    assert clamp(-5) == 0
'''

OBLIVIOUS = '''from subject import clamp


def test_positives_pass_through():
    assert clamp(7) == 7
'''


def _write(path: Path, text: str) -> None:
    """LF, explicitly.

    `Path.write_text` translates newlines to the platform's ending, so on Windows
    this fixture would land as CRLF while `ANCHOR` above is LF -- and the harness
    matches byte for byte on purpose, so the mutation would simply not apply. The
    repository stores source with LF (`.gitattributes`), so writing LF here is what
    makes the fixture resemble the thing it stands for. Hitting this while writing
    the test is also why `AnchorMissing` now says so when the only difference is the
    line ending: it is the first thing to suspect and the last thing anyone checks.
    """
    path.write_bytes(text.encode("utf-8"))


def _project(root: Path, test_body: str) -> None:
    _write(root / "subject.py", SOURCE)
    _write(root / "test_subject.py", test_body)


def _mutation() -> MU.Mutation:
    return MU.Mutation(
        name="drop-the-negative-guard", file="subject.py", anchor=ANCHOR,
        replacement="", tests=("test_subject.py",),
        why="the clamp stops clamping, which a test that only tries positive "
            "numbers cannot see")


def _sweep(root: Path) -> tuple[MU.Result, ...]:
    # `dirty=()` rather than asking git: the throwaway directory is not a
    # repository, and what is under test here is the runner, not the guard.
    return MU.sweep(root, MU.Manifest(target="clamp", mutations=(_mutation(),)),
                    runner=MU.pytest_runner(root), dirty=())


def test_the_real_runner_kills_a_mutation_a_test_notices() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        _project(root, WATCHFUL)
        # The baseline matters: a test that was already failing would report
        # KILLED for every mutation, including ones nothing detects.
        before = subprocess.run([sys.executable, "-m", "pytest", "-q"],
                                cwd=str(root), capture_output=True, text=True,
                                check=False)
        assert before.returncode == 0, (
            "the fixture's own test must pass before anything is mutated, or "
            f"every verdict below is meaningless: {before.stdout[-400:]}")

        results = _sweep(root)
        assert [r.verdict for r in results] == [MU.KILLED], results
        assert SOURCE == (root / "subject.py").read_text(encoding="utf-8"), (
            "and the source is back exactly as it was found")


def test_the_real_runner_lets_a_mutation_no_test_notices_survive() -> None:
    """The direction that makes the other one mean something.

    If both cases reported `KILLED` the runner would be ignoring `pytest` and
    answering from something else -- which is precisely what an injected runner in
    the L0 file cannot detect.
    """
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        _project(root, OBLIVIOUS)
        results = _sweep(root)
        assert [r.verdict for r in results] == [MU.SURVIVED], results
        assert MU.report(results) == 1, "a survivor has to fail the command"
        assert SOURCE == (root / "subject.py").read_text(encoding="utf-8")


def test_a_stale_pyc_cannot_decide_the_verdict() -> None:
    """The verdict must come from the mutated source, not from a cached compile.

    The restore is verified in bytes, but a child interpreter executes *bytecode*,
    and CPython reuses a `__pycache__` entry when two fields match: the source mtime
    truncated to whole **seconds**, and its size. A mutation whose replacement is
    the same byte length as its anchor, written inside the same second the `.pyc`
    recorded, satisfies both -- so the child runs the old code and the harness
    reports a verdict about a timestamp.

    Two of the twelve rows in `benchmarks/mutations/mutate-harness.json` preserve
    byte length, and this was measured, not feared: the self-sweep reported a false
    survivor on two of six consecutive runs from one clean tree.

    The collision is **forced** here with `os.utime` rather than raced, because a
    test that waits for a sub-second window is a test that passes for timing
    reasons. Both directions are asserted: with the cache invalidated the mutation
    is seen and the row is `KILLED`; and the fixture proves the stale entry really
    was loadable, so the assertion cannot pass because the trap failed to arm.
    """
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        _project(root, WATCHFUL)
        subject = root / "subject.py"

        # `<` becomes `>`, so the clamp stops clamping negatives and the file size
        # does not move by a single byte -- which is the only condition the stale
        # cache needs, and the reason this fixture is written this way.
        same_length = MU.Mutation(
            name="equal-length", file="subject.py", anchor="if value < 0:",
            replacement="if value > 0:", tests=("test_subject.py",),
            why="the clamp stops clamping negatives, at identical file size")
        assert len(same_length.anchor) == len(same_length.replacement), (
            "this fixture is worthless unless the edit preserves length: that is "
            "what makes the .pyc size field keep matching")

        # Compile the ORIGINAL, and note the second its `.pyc` recorded.
        py_compile.compile(str(subject), doraise=True)
        cached = Path(importlib.util.cache_from_source(str(subject)))
        assert cached.is_file(), "the trap has to be armed or this proves nothing"
        recorded = struct.unpack("<4sIII", cached.read_bytes()[:16])[2]

        # `patched` is driven directly rather than through `sweep`, because the trap
        # has to be armed *after* the mutating write: that write sets mtime to now,
        # which is what usually saves this by accident. Stamping the source back into
        # the second the cache recorded is the same state a fast sweep reaches on its
        # own -- forced, so the test does not depend on winning a sub-second race.
        # An earlier version of this test stamped before entering the block and
        # passed with the invalidation deleted, which is to say it tested nothing.
        with MU.patched(root, same_length) as target:
            os.utime(target, (recorded, recorded))
            assert int(target.stat().st_mtime) == recorded, "the trap is armed"
            passed = MU.pytest_runner(root)(["test_subject.py"])

        assert passed is False, (
            "the child ran a cached compile of the unmutated source: the clamp still "
            "clamped, the watchful test passed, and this mutation would have been "
            "recorded SURVIVED on the strength of a .pyc timestamp")
        assert SOURCE == subject.read_text(encoding="utf-8")


def test_a_sweep_leaves_no_compiled_copy_of_the_mutation_behind() -> None:
    """The other half, and the one that poisoned this repository's own test runs.

    A stale entry compiled from the mutation outlives the sweep. Nothing in the
    working tree contains that code -- `git status` is clean and the source hash
    matches -- and yet a later interpreter can still execute it. That is what made
    two tests fail exactly once and then pass seven times, which cost more to
    diagnose than everything else in this file put together.

    Simulated by compiling the mutation deliberately inside the block, standing in
    for any process that imported the file while it was patched. The assertion is
    about what is left on disk afterwards.
    """
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        _project(root, WATCHFUL)
        subject = root / "subject.py"
        cached = Path(importlib.util.cache_from_source(str(subject)))

        with MU.patched(root, MU.Mutation(
                name="equal-length", file="subject.py", anchor="if value < 0:",
                replacement="if value > 0:", tests=("test_subject.py",),
                why="the clamp stops clamping negatives")) as target:
            py_compile.compile(str(target), doraise=True)
            assert cached.is_file(), "the fixture must actually leave one behind"

        assert not cached.is_file(), (
            "a compiled copy of the mutation survived the restore, so every later "
            "run in this checkout can execute code that no file contains")


def test_the_child_is_told_not_to_write_bytecode() -> None:
    """Asserted through the child's own eyes, the way `isolation.py` is.

    `test_isolation_heavy.py:869` asserts the same variable on the env dict it
    builds. `pytest_runner` builds its env internally, so the fixture's own test
    reads `os.environ` and the runner's verdict carries the answer: a child that was
    not told would fail this, and the runner would report `False`.
    """
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        _write(root / "test_env.py",
               'import os\n\n\ndef test_bytecode_writing_is_off():\n'
               '    assert os.environ.get("PYTHONDONTWRITEBYTECODE") == "1"\n')
        assert MU.pytest_runner(root)(["test_env.py"]) is True, (
            "the child was not told to stop writing bytecode, so it can leave a "
            "compiled copy of a mutated file behind for the next process")


def test_a_selector_that_matches_nothing_is_refused_not_counted_as_killed() -> None:
    """The failure that lets a manifest rot into a clean sheet.

    Rename a test class, leave the manifest naming the old one, and `pytest` exits
    non-zero -- 4, a usage error, measured on this repository. Read as a boolean
    that is what "a test failed" looks like, so every mutation reports `KILLED`
    while nothing ran. Only 0 and 1 are answers; this asserts the real runner
    refuses the rest, and it needs a real process because the exit code *is* the
    subject.
    """
    import pytest
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        _project(root, WATCHFUL)
        runner = MU.pytest_runner(root)
        assert runner(["test_subject.py"]) is True, "the fixture itself passes"
        with pytest.raises(MU.RunnerAmbiguous) as caught:
            runner(["test_subject.py::test_this_name_does_not_exist"])
        assert "did not run" in str(caught.value)


def test_the_harness_kills_every_mutation_of_itself() -> None:
    """The repository's own manifest, run for real.

    `benchmarks/mutations/mutate-harness.json` mutates the harness including the
    `finally` that restores the bytes. This runs it against the working tree, which
    is the only way the manifest is evidence rather than a description -- and it is
    also a check that the manifest's anchors still match the code they name, which
    is how a mutation set silently stops testing anything.

    Skipped rather than failed when the tree is dirty: the harness refuses a
    modified target by design, and that refusal is a correct answer, not a defect
    in this test.
    """
    manifest = REPO_ROOT / "benchmarks" / "mutations" / "mutate-harness.json"
    loaded = MU.load(manifest)
    try:
        results = MU.sweep(REPO_ROOT, loaded, runner=MU.pytest_runner(REPO_ROOT))
    except MU.DirtyTarget as exc:
        import pytest
        pytest.skip(f"the harness refuses a modified target, correctly: {exc}")
    survivors = [r.mutation.name for r in results if r.verdict == MU.SURVIVED]
    assert not survivors, (
        f"{survivors} survived: the fixtures named in the manifest do not measure "
        "what they claim")
    assert len(results) == len(loaded.mutations)
