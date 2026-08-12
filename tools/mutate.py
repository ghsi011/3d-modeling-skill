#!/usr/bin/env python3
"""Mutate source text by exact anchor, run a check against it, put the bytes back.

`AGENTS.md`: *prove a protection by mutating it, never by watching it pass.* This is
the harness for doing that to **source text**. `pipeline/corpus.py` wears the word
"mutation" and means something else -- it mutates *geometry*, to measure what the
screening detectors catch -- and nothing in this repository mutated code until now.

The gap that makes this worth its lines is not that sweeps were hard to run. It is
that their results were unreproducible. `ROADMAP.md`'s release rows consume mutation
counts as release-gate evidence ("37 mutations attempted, 37 killed") and
`CHANGELOG.md` claims eight in one entry and then names seven. Of roughly two
hundred claimed kills across those files and `docs/defects.md`, one set of five can
be reconstructed from what is in the tree. `ROADMAP.md` also records three mutations
of the datum protections that **survived the whole gate** and were found by an
independent review of the evidence rather than by the author's sweep -- which is
what a number with no artifact behind it is worth.

So a sweep here is a file: `benchmarks/mutations/<slice>.json`, listing each
mutation with the exact anchor it replaces, the tests that are supposed to notice,
and why. A later reader re-runs it.

**Restoration never goes through git, and that is the whole safety design.** The
obvious way to undo a patch is `git checkout -- <file>`, and it is how this
repository lost an implementation: a sweep reverted each mutation that way from a
tree whose work was not yet committed, so the first revert restored `HEAD` over it,
and the twelve mutations afterwards reported a missing anchor against a file that no
longer held the code -- printing results the whole time while measuring nothing.
`patched()` therefore holds the original bytes in memory, writes them back in a
`finally`, and **verifies the restore by digest**. If the bytes cannot be put back it
raises `RestoreFailed` rather than continuing, because the alternative is production
source left mutated in a tree somebody else may be reading.

Five refusals, each because the failure it prevents reads like success:

* tests that **already fail** on the unmutated tree are `BaselineFailed`. `KILLED`
  means "the named tests failed under the mutation", so a test that fails either
  way reports `KILLED` for every mutation including the ones nothing detects. The
  harness proves the baseline itself; a convention in one fixture protects only
  that fixture;
* a check that **neither passed nor failed** is `RunnerAmbiguous`. `pytest` exits
  non-zero for interruption, internal error, a node id matching nothing, and an
  empty collection, and reading any of those as `KILLED` lets a stale selector
  certify itself;

* an anchor that matches **nothing** is `AnchorMissing`, not a silent no-op -- a
  replacement that did nothing reports the mutation as caught while nothing was
  mutated;
* an anchor that matches **twice** is `AnchorAmbiguous` -- two matches mean the
  manifest does not say which line it is probing, so the record is not reproducible
  even though the sweep ran;
* a target file with **uncommitted changes** is `DirtyTarget`. Not because the work
  would be lost, since nothing here reverts through git, but because a sweep
  measures a known baseline, and mutating a file that already differs from what was
  reviewed yields a verdict about a state nobody has seen.

The verdict is somebody else's tests' answer, never this module's: `runner` is
injected. `sweep()` takes it as a parameter so the pure half is testable without
starting a process -- `conftest.py` allows an L0 test to spawn only `git` -- and
`benchmarks/heavy/test_mutate_heavy.py` exercises the real `pytest` runner.

Usage:

    uv run python tools/mutate.py benchmarks/mutations/<slice>.json

Exit code is 0 only when every mutation was killed. A survivor exits 1, because a
sweep whose failure nobody notices is a sweep that reports every rule as held.

**What the restore does not survive.** The guarantee is a `finally` in one process,
so it holds for a body that returns, raises, or deletes the file, and it does not
hold against `SIGKILL`, a machine losing power, or `os._exit`. Nor is it safe to run
two sweeps over one file at once, or to edit the target while a sweep is running:
the second reader would capture the first one's mutation as its "original", and the
restore would faithfully put back bytes that were never yours. The `DirtyTarget`
refusal is what makes the last of those unlikely rather than impossible. If a sweep
is killed mid-run, `git diff` shows exactly what is still patched -- which is the
recovery path, and the reason the harness insists the tree was clean beforehand.

**What this does not do.** It does not write manifests for mutation claims already
recorded in prose. Those were run against trees that no longer exist and cannot be
reconstructed exactly; inventing entries for them would manufacture the very
evidence this file exists to make real. This is the forward authority from the point
it lands, and the historical numbers stay what they are: prose.
"""
from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable, Iterable, Iterator, Sequence
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parent.parent

KILLED = "KILLED"
SURVIVED = "SURVIVED"

_REQUIRED = ("name", "file", "anchor", "replacement", "tests", "why")


class MutateError(RuntimeError):
    """Anything that stops a sweep. Every subclass is a refusal, not a verdict."""


class ManifestError(MutateError):
    pass


class AnchorMissing(MutateError):
    pass


class AnchorAmbiguous(MutateError):
    pass


class DirtyTarget(MutateError):
    pass


class RestoreFailed(MutateError):
    pass


class BaselineFailed(MutateError):
    """The named tests were already failing before anything was mutated.

    Every verdict below such a test is meaningless: `KILLED` means "the tests
    failed under the mutation", and tests that fail regardless report `KILLED`
    for every mutation, including ones nothing detects. That is the harness
    reporting a protection as proven at exactly the moment it has none, so it is
    a refusal and no verdict is produced.
    """


class RunnerAmbiguous(MutateError):
    """The check neither passed nor failed -- it could not say.

    `pytest` exits non-zero for reasons that are not "a test failed": 2
    interrupted, 3 internal error, 4 usage error, 5 nothing collected. Reading
    any of those as `KILLED` is how a stale selector certifies itself: rename a
    test class, leave the manifest pointing at the old name, and every mutation
    reports as caught while nothing ran. Measured, not supposed -- a typo'd node
    id exits 4 on this repository's pytest.
    """


@dataclasses.dataclass(frozen=True)
class Mutation:
    """One patch, and what is supposed to notice it.

    `why` is not decoration. A survivor has to be actionable by whoever reads the
    report, and "the anchor at line 1311 changed" does not say which protection was
    being probed.
    """

    name: str
    file: str
    anchor: str
    replacement: str
    tests: tuple[str, ...]
    why: str


@dataclasses.dataclass(frozen=True)
class Manifest:
    target: str
    mutations: tuple[Mutation, ...]

    @property
    def files(self) -> tuple[str, ...]:
        return tuple(sorted({m.file for m in self.mutations}))


@dataclasses.dataclass(frozen=True)
class Result:
    mutation: Mutation
    verdict: str


def from_payload(payload: dict) -> Manifest:
    """A manifest is evidence, so a malformed one is refused rather than skipped."""
    if not isinstance(payload, dict):
        raise ManifestError("a manifest is a JSON object")
    rows = payload.get("mutations")
    if not isinstance(rows, list) or not rows:
        # An empty set would report "0 attempted, 0 survived" and exit 0, which
        # reads exactly like a sweep that held.
        raise ManifestError("a manifest with no mutations would report a clean "
                            "sweep having attempted nothing")
    mutations = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ManifestError(f"mutations[{index}] is not an object")
        missing = [key for key in _REQUIRED if key not in row]
        if missing:
            raise ManifestError(
                f"mutations[{index}] ({row.get('name', 'unnamed')}) is missing "
                f"{missing}; every field is required because a mutation without "
                "one of them cannot be re-run or read")
        tests = row["tests"]
        if not isinstance(tests, list):
            raise ManifestError(f"mutations[{index}].tests must be a list")
        if not tests:
            # An empty list is not "no opinion", it is `pytest` with no argument:
            # the whole suite. Then any unrelated failure anywhere reports this
            # mutation as caught, and a suite that passes reports it as survived
            # without the named protection ever being exercised. Neither answer is
            # about the mutation.
            raise ManifestError(
                f"mutations[{index}] ({row.get('name', 'unnamed')}) names no "
                "tests. An empty list runs the entire suite, so the verdict would "
                "be about the repository rather than about this mutation.")
        mutations.append(Mutation(
            name=str(row["name"]), file=str(row["file"]),
            anchor=str(row["anchor"]), replacement=str(row["replacement"]),
            tests=tuple(str(t) for t in tests), why=str(row["why"])))
    return Manifest(target=str(payload.get("target", "")),
                    mutations=tuple(mutations))


def load(path: Path) -> Manifest:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"{path}: {exc}") from exc
    return from_payload(payload)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_dirty(root: Path) -> tuple[str, ...]:
    """Paths with uncommitted changes, as git sees them.

    `git` is the one process an L0 test may start (`conftest.py`), which is why this
    is separate from `require_clean`: the check takes the answer as an argument so
    it can be tested without a repository at all.
    """
    # `-c safe.directory=*`, for one read-only command, because a hosted container
    # checks the repository out as a different uid than the job runs as and git then
    # refuses to say anything at all: *fatal: detected dubious ownership*. Without
    # this the harness cannot learn whether the tree is clean inside CI, and the two
    # tempting ways round that are both worse -- passing `dirty=()` disables the one
    # guard this function exists for, and skipping the sweep turns an environmental
    # quirk into a green tick. Scoped to this invocation rather than written into
    # global config, and `status` reads.
    done = subprocess.run(
        ["git", "-c", "safe.directory=*", "status", "--porcelain"],
        cwd=str(root), capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise MutateError(
            f"git status failed in {root}: {done.stderr.strip()}. A sweep needs a "
            "known baseline, so an unanswerable question is a stop rather than an "
            "assumption that the tree is clean.")
    return tuple(line[3:].strip() for line in done.stdout.splitlines() if line.strip())


def _as_repo_path(raw: str) -> str:
    """One spelling for one file, so the dirty check cannot be spelled around.

    `git status --porcelain` says `tools/mutate.py`; a manifest may say
    `./tools/mutate.py`, and a plain string intersection treats those as two
    different files -- so the guard would find nothing and patch a dirty target.
    `PurePosixPath` collapses `.` segments without touching the filesystem, which
    matters because these paths are compared, not opened.
    """
    return PurePosixPath(raw.replace("\\", "/")).as_posix()


def require_clean(root: Path, files: Iterable[str], *,
                  dirty: Sequence[str]) -> None:
    modified = sorted({_as_repo_path(f) for f in files}
                      & {_as_repo_path(d) for d in dirty})
    if modified:
        raise DirtyTarget(
            f"{modified} have uncommitted changes. A sweep measures a known "
            "baseline; mutating a file that already differs from what was "
            "reviewed produces a verdict about a state nobody has seen. Commit "
            "first -- nothing here reverts through git, so committing is for the "
            "reader's benefit, not the harness's.")


@contextlib.contextmanager
def patched(root: Path, mutation: Mutation) -> Iterator[Path]:
    """Apply one mutation, yield, and put the original bytes back.

    The bytes are held here, in memory, for the reason the module docstring gives.
    The `finally` runs for a body that raised as well as one that returned, and the
    restore is verified rather than assumed.
    """
    # Resolved once, before the body runs. A relative `root` is resolved against
    # the current working directory *at use time*, so a runner that changes
    # directory -- and a runner is somebody else's code -- would send the restore
    # to a path under wherever it moved to, leaving the real file mutated while
    # the digest check passed against the file it accidentally wrote.
    path = (Path(root) / mutation.file).resolve()
    original = path.read_bytes()
    text = original.decode("utf-8")
    found = text.count(mutation.anchor)
    if found == 0:
        # Line endings are the first thing to suspect and the last thing anyone
        # checks, so the message says it rather than leaving a reader to diff two
        # strings that look identical. Diagnosed, deliberately not repaired: this
        # function's contract is that the bytes it writes are the bytes the
        # manifest asked for, and a harness that quietly normalised newlines in
        # source it is about to patch would be editing more than the anchor names.
        if mutation.anchor.replace("\n", "\r\n") in text:
            raise AnchorMissing(
                f"{mutation.name}: the anchor is not in {mutation.file} as written, "
                "but it is there with CRLF line endings. The manifest is stored "
                "with LF and this working copy has CRLF. Anchors are matched byte "
                "for byte on purpose; normalise the checkout (see .gitattributes) "
                "rather than the anchor.")
        raise AnchorMissing(
            f"{mutation.name}: the anchor is not in {mutation.file}. A patch that "
            "did not apply would report this mutation as caught while nothing was "
            "mutated, so it stops the sweep.")
    if found > 1:
        raise AnchorAmbiguous(
            f"{mutation.name}: the anchor appears {found} times in "
            f"{mutation.file}. Two matches mean the manifest does not say which "
            "one it is probing.")
    try:
        # `write_bytes`, not `write_text`: text mode translates `\n` to the
        # platform ending, so on Windows the mutated file came back as CRLF
        # throughout -- every line changed, not the one the manifest named. The
        # restore put the original bytes back, so this was invisible afterwards,
        # but the tests ran against a file whose every line differed from the one
        # under review, and a failure caused by that reports as `KILLED`. The
        # patch has to be exactly the anchor swapped for the replacement and
        # nothing else, which is the same byte-for-byte contract that makes
        # `AnchorMissing` refuse rather than normalise.
        mutated = text.replace(mutation.anchor, mutation.replacement, 1)
        path.write_bytes(mutated.encode("utf-8"))
        yield path
    finally:
        try:
            path.write_bytes(original)
            back = path.read_bytes()
        except OSError as exc:
            raise RestoreFailed(
                f"{mutation.name}: {mutation.file} could not be restored ({exc}). "
                "The source is left mutated; fix that before running anything "
                "else.") from exc
        if _digest(back) != _digest(original):
            raise RestoreFailed(
                f"{mutation.name}: {mutation.file} was restored and does not match "
                f"what was read ({_digest(back)[:12]} against "
                f"{_digest(original)[:12]}).")


def pytest_runner(root: Path) -> Callable[[Sequence[str]], bool]:
    """The real runner: True when the named tests pass, which means SURVIVED.

    Only two exit codes are answers. 0 is "they passed" and 1 is "a test failed";
    everything else means `pytest` never got as far as deciding, and calling that
    `KILLED` is a lie in the safe-sounding direction. Verified rather than
    assumed: a node id with a typo in it exits **4** on this repository's pytest,
    so before this distinction existed a manifest pointing at a renamed test
    reported every mutation as caught while running nothing at all.
    """

    def run(tests: Sequence[str]) -> bool:
        done = subprocess.run([sys.executable, "-m", "pytest", "-q", *tests],
                              cwd=str(root), capture_output=True, text=True,
                              check=False)
        if done.returncode == 0:
            return True
        if done.returncode == 1:
            return False
        raise RunnerAmbiguous(
            f"pytest exited {done.returncode} for {list(tests)}, which is not "
            "'passed' (0) or 'a test failed' (1) but interrupted (2), an "
            "internal error (3), a usage error such as a node id that matches "
            "nothing (4), or nothing collected (5). No verdict: the check did "
            f"not run.\n{done.stdout[-600:]}\n{done.stderr[-300:]}")

    return run


def sweep(root: Path, manifest: Manifest, *,
          runner: Callable[[Sequence[str]], bool],
          dirty: Sequence[str] | None = None) -> tuple[Result, ...]:
    root = Path(root)
    require_clean(root, manifest.files,
                  dirty=git_dirty(root) if dirty is None else dirty)
    # Which test sets have been shown to pass on the unmutated tree. Keyed by the
    # `tests` tuple, so a manifest whose entries share a selector pays for the
    # baseline once -- the sweeps here name the same class repeatedly, and a
    # baseline run per mutation would double the cost of the slowest tier for an
    # answer that cannot have changed.
    proven: dict[tuple[str, ...], bool] = {}
    results = []
    for mutation in manifest.mutations:
        # `tuple(...)` because `Mutation` is a plain dataclass: the annotation says
        # tuple and `from_payload` builds one, but nothing stops a caller
        # constructing a `Mutation` directly with a list -- and a test fixture
        # promptly did, turning the cache lookup into an unhashable-type crash deep
        # inside the sweep. Cheaper to accept both than to raise from here about a
        # type the module never enforced.
        key = tuple(mutation.tests)
        if key not in proven:
            proven[key] = runner(mutation.tests)
        if not proven[key]:
            raise BaselineFailed(
                f"{mutation.name}: {list(mutation.tests)} do not pass before "
                "anything is mutated, so no verdict about them means anything -- "
                "a test that fails either way reports KILLED for every mutation, "
                "including the ones nothing detects. Fix the tests, then sweep.")
        with patched(root, mutation):
            passed = runner(mutation.tests)
        results.append(Result(mutation=mutation,
                              verdict=SURVIVED if passed else KILLED))
    return tuple(results)


def report(results: Iterable[Result]) -> int:
    rows = tuple(results)
    survivors = [r for r in rows if r.verdict == SURVIVED]
    for result in rows:
        print(f"  {result.verdict:9} {result.mutation.name}")
        if result.verdict == SURVIVED:
            print(f"            probing: {result.mutation.why}")
            print(f"            tests that did not notice: "
                  f"{list(result.mutation.tests)}")
    print(f"\n{len(rows)} attempted, {len(rows) - len(survivors)} killed, "
          f"{len(survivors)} survived")
    if survivors:
        # A surviving mutation is a fixture gap or a redundant implementation, and
        # `AGENTS.md` says it must lead to one of those rather than to an
        # explanation. Non-zero so nobody has to read the output to find out.
        print("\na survivor is a fixture that does not measure what it names: "
              "strengthen it, or remove the implementation it fails to protect")
        return 1
    return 0


def main(argv: Sequence[str] | None = None, root: Path = REPO_ROOT) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: python tools/mutate.py <manifest.json>")
        return 2
    try:
        manifest = load(root / args[0] if not Path(args[0]).is_absolute()
                        else Path(args[0]))
        print(f"sweeping: {manifest.target}")
        results = sweep(root, manifest, runner=pytest_runner(root))
    except MutateError as exc:
        print(f"refused: {exc}")
        return 2
    return report(results)


if __name__ == "__main__":
    sys.exit(main())
