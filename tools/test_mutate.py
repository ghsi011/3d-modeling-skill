#!/usr/bin/env python3
"""The mutation harness, and the one property it must never get wrong.

`AGENTS.md` says to prove a protection by mutating it, never by watching it pass,
and `ROADMAP.md`'s release rows consume mutation counts as evidence -- "37
mutations attempted, 37 killed". Until now that evidence was prose. There was no
harness for mutating *source*: `pipeline/corpus.py` wears the name and mutates
*geometry*. Of roughly two hundred claimed kills across `ROADMAP.md`,
`CHANGELOG.md` and `docs/defects.md`, one set of five is reconstructible from what
is in the repository. `ROADMAP.md` records three mutations of the datum protections
that survived the whole gate and were found by an independent review of the
evidence rather than by the author's sweep, which is what unreproducible evidence
costs.

**The property this file exists for.** A sweep patches production source and puts
it back. The obvious way to put it back is `git checkout -- <file>`, and that is
how this repository lost an implementation: a sweep reverted each mutation from a
tree whose work was not yet committed, so the first revert restored `HEAD` and
destroyed it, and the twelve mutations after it reported a missing anchor against a
file that no longer held the code -- the sweep stopped measuring anything while
continuing to print results. So the harness holds the original bytes itself and
restores them in a `finally`, and this file's central assertions are that the bytes
come back *exactly*, including when the body raises.

Everything here is pure: the runner is injected, so nothing in this file starts a
process. `conftest.py` allows an L0 test to spawn only `git`, and the half that
really invokes `pytest` lives in `benchmarks/heavy/test_mutate_heavy.py`.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from tools import mutate as MU

ANCHOR = '    return [declared[datum_id].as_dict() for datum_id in sorted(referenced)]'
REPLACEMENT = '    return []'

SOURCE = f"""def _referenced_datums(project):
    declared = {{}}
    referenced = set()
{ANCHOR}
"""


def _write(path: Path, text: str = SOURCE) -> None:
    """LF, explicitly, because these fixtures stand in for repository source.

    `Path.write_text` translates to the platform ending, so on Windows every
    fixture here landed as CRLF -- and then an assertion that the patch changed
    one line and no other cannot tell the harness's doing from the fixture's. The
    repository stores source with LF (`.gitattributes`); writing bytes is what
    makes the subject resemble the thing it stands for.
    """
    path.write_bytes(text.encode("utf-8"))


def _manifest(**over) -> dict:
    base = {
        "target": "the D31 datum-content binding",
        "mutations": [{
            "name": "ids-only",
            "file": "src.py",
            "anchor": ANCHOR,
            "replacement": REPLACEMENT,
            "tests": ["test_datums.py"],
            "why": "the defect restored: references bound, contents not",
        }],
    }
    base.update(over)
    return base


def _mutation(**over) -> MU.Mutation:
    base = dict(name="ids-only", file="src.py", anchor=ANCHOR,
                replacement=REPLACEMENT, tests=(), why="the defect restored")
    base.update(over)
    return MU.Mutation(**base)


class AnchorMustMatchExactlyTest(unittest.TestCase):
    """A patch that did not apply is the worst outcome, not a neutral one.

    A sweep whose replacement silently did nothing reports the mutation as caught
    when nothing was mutated -- a check that cannot fail wearing the costume of one
    that held. Ambiguity is refused for the neighbouring reason: two matches mean
    the manifest does not say which line it is probing, so the record is not
    reproducible even though the sweep ran.

    Subtests rather than separate methods, here and below, because `conftest.py`
    caps what L0 may collect and these are variations on one rule rather than
    different rules.
    """

    def test_an_anchor_that_is_absent_or_ambiguous_stops_the_sweep(self) -> None:
        for label, text, anchor, expected in (
                ("absent", SOURCE, "text that is not there", MU.AnchorMissing),
                ("twice", SOURCE + SOURCE, ANCHOR, MU.AnchorAmbiguous),
        ):
            with self.subTest(anchor=label), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                _write(root / "src.py", text)
                with self.assertRaises(expected):
                    with MU.patched(root, _mutation(anchor=anchor)):
                        pass
                self.assertEqual(text, (root / "src.py").read_text(encoding="utf-8"),
                                 "a refused patch must leave the file alone")


class TheBytesComeBackTest(unittest.TestCase):
    """The property the harness exists to guarantee.

    Three ways out of the block -- returning, raising, and the body destroying the
    file underneath it -- and all three must end with the source as it was found.
    The raising case is what the `finally` is for: a sweep dies mid-run and the
    alternative is production source left patched in a tree somebody else is
    reading.
    """

    def test_the_replacement_applies_and_then_the_original_returns(self) -> None:
        for label, body in (
                ("returns", lambda p: None),
                ("raises", None),
                ("deletes the file", lambda p: p.unlink()),
        ):
            with self.subTest(body=label), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                path = root / "src.py"
                _write(path)
                if body is None:
                    with self.assertRaises(RuntimeError):
                        with MU.patched(root, _mutation()):
                            raise RuntimeError("the runner fell over")
                else:
                    with MU.patched(root, _mutation()) as target:
                        raw_bytes = target.read_bytes()
                        seen = raw_bytes.decode("utf-8")
                        self.assertIn(REPLACEMENT, seen)
                        self.assertNotIn(ANCHOR, seen)
                        # The patch is the anchor swapped for the replacement and
                        # nothing else. Written in text mode this file came back
                        # CRLF throughout on Windows -- every line changed, so a
                        # test failing because of that reported KILLED for a
                        # mutation it never saw. Asserted on bytes because that is
                        # the only place the difference is visible.
                        self.assertNotIn(b"\r\n", raw_bytes)
                        self.assertEqual(
                            SOURCE.replace(ANCHOR, REPLACEMENT).encode("utf-8"),
                            raw_bytes)
                        body(target)
                self.assertEqual(SOURCE, path.read_text(encoding="utf-8"),
                                 "the original bytes must come back exactly")

    def test_a_runner_that_changes_directory_cannot_misdirect_the_restore(self) -> None:
        """The target is decided before the body runs, because the body is not ours.

        `runner` is injected on purpose, so it is somebody else's code, and a
        relative `root` is resolved against the working directory *at the moment
        the restore writes*. A runner that chdirs would send the original bytes to
        a path under wherever it moved to -- where they would read back
        identically, so the digest check would confirm a restore that never
        touched the mutated file. Provoked with a real chdir rather than argued.
        """
        with tempfile.TemporaryDirectory() as raw, \
                tempfile.TemporaryDirectory() as elsewhere:
            root = Path(raw)
            _write(root / "src.py")
            before = Path.cwd()
            os.chdir(root)
            try:
                with MU.patched(Path("."), _mutation()):
                    os.chdir(elsewhere)
            finally:
                os.chdir(before)
            self.assertEqual(SOURCE, (root / "src.py").read_text(encoding="utf-8"))
            self.assertFalse((Path(elsewhere) / "src.py").exists(),
                             "the restore must not land where the runner wandered")

    def test_a_restore_that_cannot_be_written_is_raised_not_swallowed(self) -> None:
        """The guard is reachable, which is the only way to know it is not dead.

        A restore that fails leaves production source mutated, so it has to be
        loud -- and a guard nothing can reach is indistinguishable from one that
        was deleted, so the failure is provoked rather than described.

        The provocation is a **directory** where the file was, and that choice is
        the whole point of this docstring. It was a read-only file first, and CI
        found the flaw: the merge gate runs the heavy tier in a container, which
        means **root**, and root writes to read-only files perfectly happily. So
        `RestoreFailed` was unreachable in the one environment that gates merges,
        and this test was red there -- which the new baseline refusal caught by
        stopping the sweep instead of reporting a false `KILLED`. Nobody can write
        bytes over a directory, root included, and it needs no `chmod` cleanup:
        `IsADirectoryError` on POSIX, `PermissionError` on Windows, both `OSError`,
        which is what the `finally` catches. One provocation, every platform, and
        no privilege level where it silently stops provoking.
        """
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / "src.py"
            _write(path)
            with self.assertRaises(MU.RestoreFailed):
                with MU.patched(root, _mutation()) as target:
                    target.unlink()
                    target.mkdir()


class ADirtyTargetIsRefusedTest(unittest.TestCase):
    """Uncommitted work in a file about to be patched is a stop, not a warning.

    Not because the harness would lose it -- it restores from memory -- but because
    a sweep measures a *known* baseline. Mutating a file that already differs from
    what was reviewed produces a verdict about a state nobody has seen.
    """

    def test_only_a_modified_target_stops_the_sweep(self) -> None:
        MU.require_clean(Path("."), ("src.py",), dirty=())
        MU.require_clean(Path("."), ("src.py",), dirty=("other.py",))
        with self.assertRaises(MU.DirtyTarget):
            MU.require_clean(Path("."), ("src.py",), dirty=("src.py",))
        # One file, two spellings. Compared as raw strings these are different
        # names, so the guard found nothing and patched a dirty target.
        with self.assertRaises(MU.DirtyTarget):
            MU.require_clean(Path("."), ("./src.py",), dirty=("src.py",))

    def test_the_sweep_itself_refuses_and_not_only_the_helper(self) -> None:
        """The seam above this one: `sweep` has to *call* the guard.

        `test_only_a_modified_target_stops_the_sweep` proves `require_clean` says
        no when asked. It says nothing about whether anybody asks -- delete the
        call from `sweep()` and it still passes, which would leave the refusal
        provable and unreachable at the same time. So this goes through `sweep`,
        and it asserts the runner was never reached: a refusal that patched the
        file first is not a refusal.
        """
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write(root / "src.py")
            calls: list[tuple[str, ...]] = []
            with self.assertRaises(MU.DirtyTarget):
                MU.sweep(root, MU.from_payload(_manifest()),
                         runner=lambda tests: calls.append(tuple(tests)) or True,
                         dirty=("src.py",))
            self.assertEqual([], calls, "nothing may run against a dirty target")
            self.assertEqual(SOURCE, (root / "src.py").read_text(encoding="utf-8"))


class TheBaselineIsProvenBeforeAnyVerdictTest(unittest.TestCase):
    """`KILLED` from an already-red test is the harness's own false confidence.

    The verdict means "the named tests failed under the mutation". Tests that were
    failing beforehand fail under it too, so they report `KILLED` for every
    mutation including ones nothing detects -- the sweep prints a clean sheet at
    exactly the moment it is measuring nothing. The heavy fixture asserted its own
    baseline before mutating, but a convention observed in one fixture protects
    that fixture and no manifest anyone else writes, so the refusal belongs here.
    """

    def _project(self, root: Path) -> None:
        _write(root / "src.py")

    def test_tests_that_were_already_failing_produce_no_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._project(root)
            calls: list[tuple[str, ...]] = []

            def always_fails(tests):
                calls.append(tuple(tests))
                return False

            with self.assertRaises(MU.BaselineFailed):
                MU.sweep(root, MU.from_payload(_manifest()),
                         runner=always_fails, dirty=())
            # The distinction that makes this a refusal and not a verdict: the
            # baseline was the only thing run. Had the sweep gone on to patch and
            # judge, this would be two calls and a KILLED.
            self.assertEqual([("test_datums.py",)], calls)
            self.assertEqual(SOURCE, (root / "src.py").read_text(encoding="utf-8"))

    def test_a_passing_baseline_is_proven_once_per_test_set(self) -> None:
        """And the mutation is still judged on its own run, not on the baseline.

        Two mutations naming one selector: three runs, not four. The baseline is a
        fact about the tree that cannot change between two mutations that both
        started from it, and the slowest tier pays for every extra process.
        """
        second = _manifest()["mutations"][0] | {"name": "also-ids-only",
                                                "anchor": "    referenced = set()",
                                                "replacement": "    referenced = ()"}
        payload = _manifest(mutations=[_manifest()["mutations"][0], second])
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._project(root)
            calls: list[tuple[str, ...]] = []
            # Passes clean, fails once patched: the ordinary case, so the verdict
            # below is KILLED and the count is what proves the caching.
            results = MU.sweep(
                root, MU.from_payload(payload),
                runner=lambda tests: calls.append(tuple(tests)) or
                SOURCE == (root / "src.py").read_text(encoding="utf-8"),
                dirty=())
            self.assertEqual([MU.KILLED, MU.KILLED], [r.verdict for r in results])
            self.assertEqual(3, len(calls), f"one baseline, two mutations: {calls}")


class TheVerdictIsWhatTheCheckSaidTest(unittest.TestCase):
    """`KILLED` when the tests fail under the mutation, `SURVIVED` when they pass.

    The runner is injected. A sweep's verdict is a fact about somebody else's
    tests, and a harness that decided it for itself would be the thing it exists to
    prevent. The exit code is asserted in the same breath, because a sweep whose
    failure nobody notices is a sweep that reports every rule as held.
    """

    def test_the_verdict_and_the_exit_code_follow_the_runner(self) -> None:
        for passes, verdict, code in ((False, MU.KILLED, 0),
                                      (True, MU.SURVIVED, 1)):
            with self.subTest(tests_pass=passes), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                path = root / "src.py"
                _write(path)
                # The runner answers `True` on the clean tree and `passes` once the
                # file is patched. It cannot be a constant any more: a runner that
                # always fails now stops the sweep with `BaselineFailed`, because a
                # test failing either way cannot say anything about a mutation. So
                # this reads the file to tell which run it is in -- which is also
                # closer to what a real runner does.
                def runner(tests, path=path, passes=passes):
                    clean = path.read_bytes() == SOURCE.encode("utf-8")
                    return True if clean else passes

                results = MU.sweep(root, MU.from_payload(_manifest()),
                                   runner=runner, dirty=())
                self.assertEqual([verdict], [r.verdict for r in results])
                self.assertEqual(code, MU.report(results))


class TheManifestIsCheckedBeforeItIsTrustedTest(unittest.TestCase):
    """A manifest is evidence, so a malformed one is refused rather than skipped.

    The empty case matters most: it would report "0 attempted, 0 survived" and exit
    0, which reads exactly like a sweep that held.
    """

    def test_a_manifest_that_cannot_be_re_run_is_refused(self) -> None:
        missing_field = _manifest()
        del missing_field["mutations"][0]["anchor"]
        for label, payload in (("no mutations", _manifest(mutations=[])),
                               ("missing anchor", missing_field),
                               ("tests not a list", _manifest(mutations=[
                                   {**_manifest()["mutations"][0], "tests": "t"}])),
                               # An empty list is not "no opinion": it is pytest
                               # with no argument, so the verdict would be about
                               # the whole repository and not this mutation.
                               ("tests empty", _manifest(mutations=[
                                   {**_manifest()["mutations"][0], "tests": []}]))):
            with self.subTest(manifest=label):
                with self.assertRaises(MU.ManifestError):
                    MU.from_payload(payload)

    def test_a_manifest_round_trips_from_disk(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "m.json"
            path.write_text(json.dumps(_manifest()), encoding="utf-8")
            manifest = MU.load(path)
            self.assertEqual(("src.py",), manifest.files)
            self.assertEqual("ids-only", manifest.mutations[0].name)


class TheRestoreIsVerifiedByDigestTest(unittest.TestCase):
    """The half of `RestoreFailed` that a write-failure provocation cannot reach.

    `patched`'s `finally` has two guards and they catch different worlds. The
    `except OSError` half catches a write that *refuses*; this half catches a write
    that *lies* -- one that returns without error and leaves bytes on disk that are
    not the bytes it was handed. A truncating filesystem, a full disk that reports
    success, a sync that never lands.

    It needed its own test because the existing directory provocation exercises only
    the refusing half: replacing the comparison with `if False:` left the whole L0
    file green. The module docstring and a merged pull request both said the restore
    is "verified by digest", which was true of the code and unproven by the suite --
    and an unproven guard is indistinguishable from a deleted one.

    Provoked rather than described: the write is made to land two bytes short, which
    is what a partial write looks like from here.
    """

    def test_a_write_that_lands_wrong_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / "src.py"
            _write(path)
            real = Path.write_bytes

            def truncating(self, data):
                # Succeeds, reports nothing, and leaves the wrong bytes behind.
                return real(self, data[:-2] if self == path else data)

            with self.assertRaises(MU.RestoreFailed) as caught:
                Path.write_bytes = truncating
                try:
                    with MU.patched(root, _mutation()):
                        pass
                finally:
                    Path.write_bytes = real
            message = str(caught.exception)
            self.assertIn("does not match", message)
            self.assertIn("src.py", message)

    def test_the_probe_itself_would_pass_a_faithful_write(self) -> None:
        """The control, without which the test above proves only that patching works."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / "src.py"
            _write(path)
            with MU.patched(root, _mutation()) as target:
                self.assertIn(REPLACEMENT, target.read_text(encoding="utf-8"))
            self.assertEqual(SOURCE, path.read_text(encoding="utf-8"))


class AStaleBytecodeThatCannotBeRemovedIsRefusedTest(unittest.TestCase):
    """A verdict decided by a `.pyc` nobody chose is not a verdict about the mutation.

    `_invalidate_bytecode` raises rather than warns, and that refusal had no test:
    swallowing the `MutateError` left the whole L0 file green. The reason it must be
    a refusal is recorded in the harness itself -- a stale entry compiled from the
    mutation outlives the sweep, so a later run in the same checkout can execute code
    no file on disk contains.
    """

    def test_a_pyc_that_will_not_unlink_stops_the_sweep(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / "src.py"
            _write(path)
            cache = root / "__pycache__"
            cache.mkdir()
            stale = cache / "src.cpython-312.pyc"
            stale.write_bytes(b"stale bytecode")
            real = Path.unlink

            def refusing(self, missing_ok=False):
                if self == stale:
                    raise OSError(13, "in use by another process")
                return real(self, missing_ok=missing_ok)

            with self.assertRaises(MU.MutateError) as caught:
                Path.unlink = refusing
                try:
                    MU._invalidate_bytecode(path)
                finally:
                    Path.unlink = real
            message = str(caught.exception)
            self.assertIn("stale", message.lower())
            self.assertIn("src.py", message)

    def test_a_removable_pyc_is_removed_and_does_not_raise(self) -> None:
        """The control: the refusal above must be about the failure, not the path."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / "src.py"
            _write(path)
            cache = root / "__pycache__"
            cache.mkdir()
            for tag in ("cpython-311", "cpython-312"):
                (cache / f"src.{tag}.pyc").write_bytes(b"stale")
            MU._invalidate_bytecode(path)
            self.assertEqual([], sorted(cache.glob("src.*.pyc")),
                             "every interpreter's stale entry must go, not just this one's")


if __name__ == "__main__":
    unittest.main()
