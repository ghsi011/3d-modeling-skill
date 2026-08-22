#!/usr/bin/env python3
"""D36: the pipeline's build receipt was squatting on the designer's manifest.

`artifact_manifest.json` is a team contract: `CANONICAL_FILENAMES` names it,
`designer_toolkit/receipts.py` writes it with `contract: artifact-manifest`, and
the charters point readers at it. The pipeline wrote an entirely different object
to the same path -- `backend`, `boolean_engine`, `cache`, `contract_sha256` --
and then treated that path as one of *its own* receipts.

**Two mechanisms, and they were both reproduced before this fix.** The write is
the obvious one, on the normal path and the measurement-exception path alike.
The subtler one is the lifecycle: the name was in `REMOVABLE` and carried a
`depends_on` edge, so `bindings.invalidate` deleted the designer's file outright
when it judged the pipeline's receipt stale -- recording the sha of a file the
pipeline had never written, and naming a reason about a dependency the designer
had never declared.

A rename rather than an existence check, because both writers are legitimate and
only one of them is entitled to that name. The team contract's is externally
specified, validator-known and charter-facing; the pipeline's is internal, so the
pipeline's is what moves.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from . import bindings as B

# What a designer's commission actually writes: `designer_toolkit.receipts`
# builds this shape, and `team_tools` validates it. Nothing here overlaps the
# pipeline's object except `job_id`, `units` and `updated_utc`.
TEAM_MANIFEST = {
    "contract": "artifact-manifest",
    "contract_version": 1,
    "job_id": "the-designer-wrote-this",
    "candidate_id": "cand-7",
    "units": "mm",
    "updated_utc": "1970-01-01T00:00:00Z",
    "artifacts": [{"path": "candidate.stl", "sha256": "0" * 64}],
}
TEAM_FILE = "artifact_manifest.json"


def _seed_team_manifest(work: Path) -> bytes:
    path = work / TEAM_FILE
    path.write_text(json.dumps(TEAM_MANIFEST), encoding="utf-8")
    return path.read_bytes()


class ThePipelineReceiptHasItsOwnNameTest(unittest.TestCase):
    """**The rename itself, asserted where a reader can check it.**"""

    def test_the_receipt_is_not_the_team_contract(self) -> None:
        self.assertNotEqual(TEAM_FILE, B.PIPELINE_RECEIPT)

    def test_the_receipt_collides_with_no_role_owned_canonical_name(self) -> None:
        """Against the authoritative set, the same standard D35 was held to: a
        rename that lands on another role's artifact has moved the defect rather
        than closed it."""
        from team_tools import validators as V
        owned = {name for spellings in V.CANONICAL_FILENAMES.values()
                 for name in spellings}
        self.assertTrue(owned, "the canonical set came back empty")
        self.assertNotIn(B.PIPELINE_RECEIPT, owned)

    def test_the_team_contract_is_not_a_pipeline_receipt(self) -> None:
        """**The lifecycle half.** The pipeline's receipt list is what decides
        which files it may delete, so the designer's name must not appear in it
        at all -- not in `REMOVABLE`, not as a `Receipt`, and not as anything's
        declared dependency."""
        names = {receipt.name for receipt in B.RECEIPTS}
        self.assertNotIn(TEAM_FILE, names)
        self.assertNotIn(TEAM_FILE, B.REMOVABLE)
        self.assertIn(B.PIPELINE_RECEIPT, names)
        self.assertIn(B.PIPELINE_RECEIPT, B.REMOVABLE)

    def test_no_dependency_edge_names_the_team_contract(self) -> None:
        """A `depends_on` edge is how the designer's file was judged stale in the
        first place, so an edge left behind would keep deleting it."""
        edges: list[str] = []
        for receipt in B.RECEIPTS:
            if receipt.depends_on is None:
                continue
            edges.extend(receipt.depends_on({}))
        self.assertNotIn(TEAM_FILE, edges)


class InvalidationLeavesTheDesignersManifestAloneTest(unittest.TestCase):
    """**The mechanism a rename of the write alone would not have closed.**

    Proven against `invalidate` directly rather than through a run, because a
    run that builds writes its own receipt afterwards and the write masks the
    deletion. In isolation the deletion is visible on its own terms.
    """

    def test_a_seeded_team_manifest_is_not_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            before = _seed_team_manifest(work)
            B.invalidate(work)
            path = work / TEAM_FILE
            self.assertTrue(path.is_file(),
                            "invalidation deleted the designer's manifest")
            self.assertEqual(before, path.read_bytes())

    def test_the_pipeline_receipt_is_still_invalidated(self) -> None:
        """**The control.** The lifecycle must keep working on the pipeline's own
        file -- a fix that simply stopped deleting anything would satisfy the row
        above while leaving stale receipts standing."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            receipt = work / B.PIPELINE_RECEIPT
            receipt.write_text(json.dumps({"contract_sha256": "a" * 64}),
                               encoding="utf-8")
            removed = B.invalidate(work)
            self.assertIn(B.PIPELINE_RECEIPT, removed)
            self.assertFalse(receipt.is_file())

    def test_the_team_manifest_survives_beside_a_stale_receipt(self) -> None:
        """Both at once, which is the state a real project is in: the pipeline's
        receipt goes and the designer's stays, in the same call."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            before = _seed_team_manifest(work)
            (work / B.PIPELINE_RECEIPT).write_text(
                json.dumps({"contract_sha256": "a" * 64}), encoding="utf-8")
            removed = B.invalidate(work)
            self.assertIn(B.PIPELINE_RECEIPT, removed)
            self.assertNotIn(TEAM_FILE, removed)
            self.assertTrue((work / TEAM_FILE).is_file())
            self.assertEqual(before, (work / TEAM_FILE).read_bytes())


if __name__ == "__main__":
    unittest.main()
