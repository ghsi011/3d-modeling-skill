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

Three refusals, each because the failure it prevents reads like success:

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
from pathlib import Path

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
    done = subprocess.run(["git", "status", "--porcelain"], cwd=str(root),
                          capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise MutateError(f"git status failed in {root}: {done.stderr.strip()}")
    return tuple(line[3:].strip() for line in done.stdout.splitlines() if line.strip())


def require_clean(root: Path, files: Iterable[str], *,
                  dirty: Sequence[str]) -> None:
    modified = sorted(set(files) & {d.replace("\\", "/") for d in dirty})
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
    path = Path(root) / mutation.file
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
        path.write_text(text.replace(mutation.anchor, mutation.replacement, 1),
                        encoding="utf-8")
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
    """The real runner: True when the named tests pass, which means SURVIVED."""

    def run(tests: Sequence[str]) -> bool:
        done = subprocess.run([sys.executable, "-m", "pytest", "-q", *tests],
                              cwd=str(root), capture_output=True, text=True,
                              check=False)
        return done.returncode == 0

    return run


def sweep(root: Path, manifest: Manifest, *,
          runner: Callable[[Sequence[str]], bool],
          dirty: Sequence[str] | None = None) -> tuple[Result, ...]:
    root = Path(root)
    require_clean(root, manifest.files,
                  dirty=git_dirty(root) if dirty is None else dirty)
    results = []
    for mutation in manifest.mutations:
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
