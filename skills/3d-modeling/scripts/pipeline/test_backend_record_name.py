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

import json
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

    def test_the_certified_lane_binds_the_record(self) -> None:
        """The certified lane is a **current model contract carrying no
        source**, not merely a record lying on disk. A run that has built has
        written that contract, and it is what says which lane this is."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            (work / B.BACKEND_RECORD).write_text('{"template": "c_clip"}\n',
                                                 encoding="utf-8")
            (work / B.DEFAULT_SOURCE).write_text("# the designer's\n",
                                                 encoding="utf-8")
            (work / B.MODEL_CONTRACT_FILE).write_text(
                json.dumps({"template": "c_clip"}), encoding="utf-8")
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
        certified = json.dumps({"template": "c_clip"})
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            (work / B.BACKEND_RECORD).write_text("RECORD\n", encoding="utf-8")
            (work / B.DEFAULT_SOURCE).write_text("DESIGNER\n", encoding="utf-8")
            (work / B.MODEL_CONTRACT_FILE).write_text(certified, encoding="utf-8")
            binding = B.current(work)["source"]
            record_only = Path(raw) / "record_only"
            record_only.mkdir()
            (record_only / B.BACKEND_RECORD).write_text("RECORD\n", encoding="utf-8")
            (record_only / B.MODEL_CONTRACT_FILE).write_text(certified,
                                                             encoding="utf-8")
            expected = B.current(record_only)["source"]
            designer_only = Path(raw) / "designer_only"
            designer_only.mkdir()
            (designer_only / B.DEFAULT_SOURCE).write_text("DESIGNER\n",
                                                          encoding="utf-8")
            designer = B.current(designer_only)["source"]
        self.assertEqual(expected, binding)
        self.assertNotEqual(designer, binding,
                            "the receipt is bound to the designer's file")


class TheCurrentContractDecidesTheSourceTest(unittest.TestCase):
    """**A lane transition must not leave a superseded declaration winning.**

    `_source_name` used to consult the frozen `acceptance_contract.json` first.
    That file is written by the authored lane and never removed by the certified
    one, so a project that ran authored and then ran certified kept an
    `expected_artifacts["source"]` naming `model.py` -- and it outranked the
    record the certified backend had just written. The fresh artifact manifest
    hashed the backend record while `current()["source"]` hashed the obsolete
    authored module, so evidence generated by that very run read as stale the
    moment it was written.

    The authority is now `model_contract.json`: the contract the run actually
    built against, rewritten on every run. An authored contract names its
    module; a certified one carries no source, and its source is the backend's
    record. Only where no contract exists yet does the pre-contract fallback
    still speak.

    **Nothing historical is deleted to achieve this.** The stale acceptance
    contract stays exactly where it is; it simply stops outranking a newer
    statement about what was built.
    """

    def _seed(self, work: Path, *, model_contract: dict | None,
              acceptance_source: str | None) -> None:
        (work / B.BACKEND_RECORD).write_text('{"template": "c_clip"}\n',
                                             encoding="utf-8")
        (work / B.DEFAULT_SOURCE).write_text("# the designer's\n",
                                             encoding="utf-8")
        if acceptance_source is not None:
            (work / B.CONTRACT_FILE).write_text(
                json.dumps({"expected_artifacts": {"source": acceptance_source}}),
                encoding="utf-8")
        if model_contract is not None:
            (work / B.MODEL_CONTRACT_FILE).write_text(
                json.dumps(model_contract), encoding="utf-8")

    def test_a_stale_authored_declaration_does_not_outrank_the_record(self) -> None:
        """The transition itself: authored yesterday, certified today."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            self._seed(work, model_contract={"template": "c_clip"},
                       acceptance_source=B.DEFAULT_SOURCE)
            name = B._source_name(work, {"source": B.DEFAULT_SOURCE}, None)
            digest = B.current(work)["source"]
            record = B._digest(work / B.BACKEND_RECORD)
            designer = B._digest(work / B.DEFAULT_SOURCE)
        self.assertEqual(B.BACKEND_RECORD, name)
        self.assertEqual(record, digest)
        self.assertNotEqual(designer, digest,
                            "the receipt is bound to a superseded declaration")

    def test_a_current_authored_contract_beats_a_leftover_record(self) -> None:
        """**The reverse control.** The rule is "the current contract decides",
        not "the record always wins" -- an authored run whose record was left
        behind by an earlier certified one must still bind its own module."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            self._seed(work,
                       model_contract={"source": {"kind": "authored",
                                                  "module": B.DEFAULT_SOURCE}},
                       acceptance_source=None)
            name = B._source_name(work, {}, None)
            digest = B.current(work)["source"]
            designer = B._digest(work / B.DEFAULT_SOURCE)
        self.assertEqual(B.DEFAULT_SOURCE, name)
        self.assertEqual(designer, digest)

    def test_with_no_current_contract_the_declaration_still_speaks(self) -> None:
        """**The control that keeps the pre-contract case intact.** Before a run
        has written a model contract there is nothing newer to defer to, and the
        frozen declaration is the best statement available."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            self._seed(work, model_contract=None,
                       acceptance_source=B.DEFAULT_SOURCE)
            self.assertEqual(
                B.DEFAULT_SOURCE,
                B._source_name(work, {"source": B.DEFAULT_SOURCE}, None))

    def test_an_authored_contract_that_names_no_module_is_not_certified(self) -> None:
        """**The discriminator is the absent `source` key, not an absent
        module.**

        `Contract.as_payload` omits `source` entirely on the certified lane
        rather than writing a null, so absence is how that lane says what it is.
        An authored contract whose `source` is present but does not name a
        module is a different thing -- incomplete, not certified -- and reading
        it as certified would bind a real authored job to the backend's record.
        A live fixture is exactly that shape, and it caught this.
        """
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            self._seed(work,
                       model_contract={"source": {"acceptance_contract_sha256":
                                                  "a" * 64}},
                       acceptance_source=B.DEFAULT_SOURCE)
            name = B._source_name(work, {"source": B.DEFAULT_SOURCE}, None)
        self.assertEqual(B.DEFAULT_SOURCE, name)

    def test_a_malformed_contract_does_not_promote_the_record(self) -> None:
        """An unreadable contract is not a certified one. It says nothing, so
        the pre-contract fallback answers rather than the branch that reads
        absence of a source as proof of the certified lane."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            self._seed(work, model_contract=None, acceptance_source=None)
            (work / B.MODEL_CONTRACT_FILE).write_text("{ not json",
                                                      encoding="utf-8")
            self.assertEqual(B.DEFAULT_SOURCE, B._source_name(work, {}, None))


if __name__ == "__main__":
    unittest.main()
