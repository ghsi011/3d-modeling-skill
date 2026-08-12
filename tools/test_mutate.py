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
import stat
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
                (root / "src.py").write_text(text, encoding="utf-8")
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
                path.write_text(SOURCE, encoding="utf-8")
                if body is None:
                    with self.assertRaises(RuntimeError):
                        with MU.patched(root, _mutation()):
                            raise RuntimeError("the runner fell over")
                else:
                    with MU.patched(root, _mutation()) as target:
                        seen = target.read_text(encoding="utf-8")
                        self.assertIn(REPLACEMENT, seen)
                        self.assertNotIn(ANCHOR, seen)
                        body(target)
                self.assertEqual(SOURCE, path.read_text(encoding="utf-8"),
                                 "the original bytes must come back exactly")

    def test_a_restore_that_cannot_be_written_is_raised_not_swallowed(self) -> None:
        """The guard is reachable, which is the only way to know it is not dead.

        A restore that fails leaves production source mutated, so it has to be
        loud. Provoked with a read-only file rather than described: the patch has
        already been written when the body makes the target unwritable, so the
        `finally` hits a real `PermissionError`.
        """
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / "src.py"
            path.write_text(SOURCE, encoding="utf-8")
            try:
                with self.assertRaises(MU.RestoreFailed):
                    with MU.patched(root, _mutation()) as target:
                        target.chmod(stat.S_IREAD)
            finally:
                path.chmod(stat.S_IWRITE | stat.S_IREAD)


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
                (root / "src.py").write_text(SOURCE, encoding="utf-8")
                results = MU.sweep(root, MU.from_payload(_manifest()),
                                   runner=lambda tests: passes, dirty=())
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
                                   {**_manifest()["mutations"][0], "tests": "t"}]))):
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


if __name__ == "__main__":
    unittest.main()
