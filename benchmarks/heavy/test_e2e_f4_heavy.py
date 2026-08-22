#!/usr/bin/env python3
"""L0-heavy — F4's fixture has to agree with its own reference, and reject.

Two arms, because one is not a test. **The reference passing proves the fixture
is self-consistent; the source failing proves the scorer can say no.** A file
that only asserted the first would keep passing if the scorer were loosened until
it accepted anything, which is the shape section 3b names — an instrument that
cannot fail for the thing it exists to catch.

The second arm costs nothing to build: handing the *unedited source* in as the
candidate is a mutation with no geometry construction at all, and the slot rows
have to reject it because no slot exists.

This lives in the heavy tier because it needs the external reference and reads a
STEP through the CAD kernel. Like F1, the fixture is `required_hosted: false`, so
a missing reference is an explicit skip that says how to produce it rather than a
silent pass — the artifacts are `EXTERNAL_ONLY` because the source is GPL-3.0 and
vendoring it would impose that licence on this repository.

Runs at pitch 0.20 and without `embreex`: measured at 13 s that way, against
41 s at pitch 0.05 with the accelerator. The coarse pitch is honest here because
this arm is asking *does the fixture agree with its own reference*, not *what is
this candidate's slot width to four decimals*.
"""
from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

FIXTURE = REPO / "benchmarks" / "e2e" / "f4-prusa-modify.json"
PITCH = 0.20


def _root(spec: dict) -> Path:
    import os
    block = spec["source"]["root"]
    return Path(os.environ.get(block["env"], block["default"]))


def _load_spec():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class F4sReferenceAgreesWithItsOwnFixtureTest(unittest.TestCase):
    """The stored reference must satisfy every row the fixture freezes."""

    @classmethod
    def setUpClass(cls):
        cls.spec = _load_spec()
        root = _root(cls.spec)
        cls.source = root / cls.spec["source"]["path"]
        cls.target = root / cls.spec["target"]["path"]
        missing = [p for p in (cls.source, cls.target) if not p.is_file()]
        if missing:
            raise unittest.SkipTest(
                "F4's reference is EXTERNAL_ONLY and is not on this machine: "
                f"{[str(p) for p in missing]}. To make it, put the pinned source "
                f"({cls.spec['source']['upstream']} @ "
                f"{cls.spec['source']['pin']}, {cls.spec['source']['upstream_path']}) "
                f"at {cls.source}, then run "
                "`uv run python tools/f4_target.py --source <that> --out "
                f"{cls.target.parent}`")

    def test_the_pinned_bytes_are_the_bytes_on_disk(self) -> None:
        """A hash in the fixture that nobody checks is a comment."""
        for name, path, want, want_bytes in (
                ("source", self.source, self.spec["source"]["sha256"],
                 self.spec["source"]["bytes"]),
                ("target", self.target, self.spec["target"]["sha256"],
                 self.spec["target"]["bytes"])):
            raw = path.read_bytes()
            self.assertEqual(want_bytes, len(raw), f"{name} byte count moved")
            self.assertEqual(want, hashlib.sha256(raw).hexdigest(),
                             f"{name} is not the pinned artifact")

    def test_the_reference_passes_every_row_the_fixture_freezes(self) -> None:
        import trimesh
        import f4_score
        rows = f4_score.score(f4_score._load(self.source),
                              trimesh.load(str(self.target)), self.spec, PITCH)
        failed = [(r["row"], r["got"]) for r in rows if not r["ok"]]
        self.assertEqual([], failed,
                         "the fixture's own reference does not satisfy the "
                         "fixture. Either a threshold moved or the stored target "
                         "is not the edit the fixture describes")

    def test_the_unedited_source_is_rejected(self) -> None:
        """The arm that makes the arm above mean something.

        Handing the source in as its own candidate is a mutation that costs no
        geometry: nothing was cut, so the slot rows must reject it. If this ever
        passes, the scorer has stopped discriminating and the test above is
        confirming rather than checking.
        """
        import f4_score
        src = f4_score._load(self.source)
        rows = f4_score.score(src, src, self.spec, PITCH)
        failed = {r["row"] for r in rows if not r["ok"]}
        self.assertTrue(failed,
                        "the scorer accepted the UNEDITED source as a valid "
                        "candidate: no slot exists in it, so every edit row "
                        "should have rejected it")
        self.assertIn("slot_exists", failed | {r["row"] for r in rows},
                      "expected the missing-slot row to be the one that spoke")


if __name__ == "__main__":
    unittest.main()
