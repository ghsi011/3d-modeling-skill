#!/usr/bin/env python3
"""D35's cheap half: the record has a name of its own, and the receipt finds it.

The building half is `benchmarks/heavy/test_model_source_authority_heavy.py` --
it executes manifold3d and build123d, and a real build does not belong in the
commit gate. What is here needs no geometry and would otherwise regress in
silence.

**The silent one is the binding.** `bindings.current()` does not read
`BuildArtifacts`; it re-derives the `source` binding from a *filename*, taking
the acceptance contract's declaration, then the project's `model`, then a
fallback. On the certified lane the first two are absent -- that lane freezes no
acceptance contract and declares no model -- so the fallback is the only thing
naming its source. Move the backend's record without moving that fallback and
the binding resolves to a file nothing writes any more: `source` becomes `None`,
`artifact_manifest.json` and every receipt that depends on it read as stale on
every certified job, and no test goes red.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from . import bindings as B


class TheRecordIsNotTheDesignersFileTest(unittest.TestCase):
    """The whole repair in one assertion, stated separately because a rename
    that collided with `model.py` again would satisfy every behavioural row."""

    def test_the_two_names_are_different(self) -> None:
        self.assertNotEqual(B.DEFAULT_SOURCE, B.BACKEND_RECORD)

    def test_the_record_collides_with_no_role_owned_canonical_name(self) -> None:
        """Against the **authoritative** set, not a local list.

        The first repair checked a handful of `bindings` constants, which is the
        weaker question: those are the pipeline's own names. What decides whether
        D35 has merely moved to a new victim is `team_tools.validators`'
        `CANONICAL_FILENAMES` -- every spelling of every contract artifact a role
        is responsible for authoring.
        """
        from team_tools import validators as V
        owned = {name for spellings in V.CANONICAL_FILENAMES.values()
                 for name in spellings}
        owned |= {B.CONTRACT_FILE, B.MODEL_CONTRACT_FILE, B.PLAN_FILE,
                  B.CANDIDATE_STL, B.CANDIDATE_STEP, B.DEFAULT_SOURCE}
        self.assertTrue(owned, "the canonical set came back empty")
        self.assertNotIn(B.BACKEND_RECORD, owned)

    def test_the_record_is_not_python(self) -> None:
        """**The extension is the repair, so it gets its own row.**

        `isolation._stage` stages every top-level `*.py` beside the model as the
        designer's, on the stated ground that "the pipeline writes no Python into
        a project directory". A record named `backend_build_record.py` broke that
        invariant and would have destroyed a designer helper of that name -- the
        same defect, one filename over. Nothing executes this record; it is
        provenance, and a `.py` extension claims an ownership it does not have.
        """
        self.assertFalse(B.BACKEND_RECORD.endswith(".py"), B.BACKEND_RECORD)

    def test_the_pipeline_writes_no_python_into_a_project(self) -> None:
        """The invariant itself, asserted where it can be read: no name this
        module hands the pipeline to write is Python."""
        written = {B.BACKEND_RECORD, B.CONTRACT_FILE, B.MODEL_CONTRACT_FILE,
                   B.PLAN_FILE}
        self.assertEqual([], [n for n in written if n.endswith(".py")])


class TheSourceBindingFollowsTheRecordTest(unittest.TestCase):
    """**These fail if the fallback still names `model.py`.**"""

    def test_the_certified_fallback_is_the_record(self) -> None:
        """The certified lane: nothing declared, and a record on disk."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            (work / B.BACKEND_RECORD).write_text('{"template": "c_clip"}\n',
                                                 encoding="utf-8")
            (work / B.DEFAULT_SOURCE).write_text("# the designer's\n",
                                                 encoding="utf-8")
            name = B._source_name(work, {}, None)
        self.assertEqual(B.BACKEND_RECORD, name)

    def test_a_declared_source_still_wins(self) -> None:
        """The authored lane's acceptance contract declares its source, and a
        record sitting beside it must not displace that declaration."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            (work / B.BACKEND_RECORD).write_text('{"template": "c_clip"}\n',
                                                 encoding="utf-8")
            declared = B._source_name(work, {"source": "part.py"}, None)
            by_project = B._source_name(work, {}, "part.py")
        self.assertEqual("part.py", declared)
        self.assertEqual("part.py", by_project)

    def test_with_no_record_the_fallback_is_unchanged(self) -> None:
        """**The control.** An authored job whose contract is not frozen yet and
        whose project declares no model still binds `model.py` -- so this change
        cannot silently unbind a lane it was not about."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            (work / B.DEFAULT_SOURCE).write_text("# the designer's\n",
                                                 encoding="utf-8")
            self.assertEqual(B.DEFAULT_SOURCE, B._source_name(work, {}, None))

    def test_the_binding_reads_the_record_and_not_the_designers_file(self) -> None:
        """End to end through `current()`, which is what receipts actually call.
        Distinct contents, so the digest says *which* file was read."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            (work / B.BACKEND_RECORD).write_text("RECORD\n", encoding="utf-8")
            (work / B.DEFAULT_SOURCE).write_text("DESIGNER\n", encoding="utf-8")
            binding = B.current(work)["source"]
            record_only = Path(raw) / "record_only"
            record_only.mkdir()
            (record_only / B.BACKEND_RECORD).write_text("RECORD\n", encoding="utf-8")
            expected = B.current(record_only)["source"]
            designer_only = Path(raw) / "designer_only"
            designer_only.mkdir()
            (designer_only / B.DEFAULT_SOURCE).write_text("DESIGNER\n",
                                                          encoding="utf-8")
            designer = B.current(designer_only)["source"]
        self.assertEqual(expected, binding)
        self.assertNotEqual(designer, binding,
                            "the receipt is bound to the designer's file")


if __name__ == "__main__":
    unittest.main()
