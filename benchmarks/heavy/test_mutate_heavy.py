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
        replacement="", tests=["test_subject.py"],
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
