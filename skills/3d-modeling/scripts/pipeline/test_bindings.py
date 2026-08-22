#!/usr/bin/env python3
"""Release 3 slice B: scoped invalidation, and a status computed rather than read.

Three things were true of this build before the slice, and each of them is a
different way for a receipt to say something that is no longer so:

* **the status was stored.** `status.decide` ran once, mid-run, its answer went
  into `final_status.json`, and every reader afterwards repeated it verbatim.
  `design-tool status` recomputed the project's `problems` and took the verdict
  as given, so a `VERIFIED` receipt beside a candidate somebody had rebuilt, an
  evidence file somebody had corrected, or a plan that had since moved read as
  current -- and nothing on disk could tell;
* **invalidation was all-or-nothing.** A changed acceptance body deleted a fixed
  six-name tuple, whatever had actually moved. It could not express "this
  changed, therefore that is stale", so it could only express "something changed,
  therefore everything is" -- and the other direction, a receipt that is still
  true and must not be thrown away, it could not express at all;
* **`next_action.json` had no identity.** No run id, no sequence, no self-digest.
  Staleness was handled by overwriting or unlinking, so any path that changed the
  project without reaching one of those two calls left an instruction pointing at
  work already done. D17 is the live instance: a successful `route` left the "fix
  the project" instruction it had written while the project was incomplete.

Every test here fails on the code as it stood before the slice. Where a test
shows a protection holding, its neighbour mutates the protection and shows the
loss is reachable -- a test that only shows the current code refusing proves that
the refusal happens, not that anything is holding it up.

The half of this file the commit gate will not carry is in
`benchmarks/heavy/test_bindings_heavy.py`, and runs before merge instead of on
every push: `DerivedStatusTest`, `NextActionIdentityTest`,
`NothingHashedGainedAKeyTest`, `ScopedInvalidationTest`, `SiblingScopeTest`.
Same tests, moved rather than weakened; `conftest.py` carries the rule and
`benchmarks/heavy/README.md` the measurement behind it.
"""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from . import bindings as B
from . import acceptance as ACC
from . import cli
from . import project as P
from . import schemas as S
from . import selftest as ST

UTC = "1970-01-01T00:00:00Z"

MODEL = '''
import trimesh

PARAMS = {{"w": {w}, "d": {d}, "h": {h}}}


def build():
    block = trimesh.creation.box(extents=({w}, {d}, {h}))
    block.apply_translation(({w} / 2, {d} / 2, {h} / 2))
    return block
'''

BLOCK = dict(w=40.0, d=30.0, h=10.0)
OTHER = dict(w=36.0, d=26.0, h=12.0)

# The declared evidence. A caliper sheet is a *shared* job input: it is named
# once against the project, it is hashed into every review envelope that was
# shown it, and it reaches no contract and no artifact. Correcting one after a
# review is therefore the sharpest available case of a change that must unbind
# exactly one thing -- and, before this slice, of a change nothing could see.
EVIDENCE_FILE = "calipers.md"


def _proposal(design_id: str, *, w: float, d: float, h: float) -> dict:
    return {
        "schema_version": 1,
        "job_id": "bindings",
        "design_id": design_id,
        "rationale": f"a {w}x{d}x{h} block",
        "params": {"w": w, "d": d, "h": h},
        "bbox_mm": {"x": w, "y": d, "z": h},
        "bodies": 1,
        "profile_marks": {"z": []},
        "features": [
            {"feature_id": "block-section", "kind": "section_area",
             "at": {"z": h / 2}, "value_mm2": w * d},
            {"feature_id": "bed-footprint", "kind": "bed_contact",
             "value_mm2": w * d},
        ],
    }


def _project(**over) -> P.Project:
    base = dict(
        job_id="bindings", updated_utc=UTC, source_mode="NEW",
        consequence="INCONSEQUENTIAL",
        consequence_rationale="a desk block; failure wastes material",
        printer="Test Printer", material={"process": "FDM", "material": "PLA"},
        nozzle={"diameter_mm": 0.4},
        orientation={"model_to_printer_matrix": "identity", "bed_z_mm": 0.0},
        template=None, parameters={}, model="model.py",
        envelope_mm={"x": 60.0, "y": 50.0, "z": 20.0},
        reviewer={"model_snapshot": "test"},
        evidence=(EVIDENCE_FILE,),
        verification_requested=True,
        requirements=(P.Requirement(name="mount_pitch", value=32.0, unit="mm",
                                    provenance="STATED", source="user"),),
    )
    base.update(over)
    return P.Project(**base)


def _laid_out(root: Path, project: P.Project | None = None) -> Path:
    directory = root / "project"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "brief.md").write_text("a block", encoding="utf-8")
    (directory / EVIDENCE_FILE).write_text(
        "mount pitch 32.00 mm, digital calipers, 2026-08-02\n", encoding="utf-8")
    (project or _project()).save(directory)
    return directory


def _author(where: Path, design_id: str, **params) -> None:
    where.mkdir(parents=True, exist_ok=True)
    (where / "model.py").write_text(textwrap.dedent(MODEL.format(**params)),
                                    encoding="utf-8")
    (where / ACC.PROPOSAL_FILE).write_text(
        S.canonical_json(_proposal(design_id, **params)), encoding="utf-8")


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _digests(directory: Path) -> dict[str, str]:
    return {p.relative_to(directory).as_posix(): S.sha256_file(p)
            for p in sorted(directory.rglob("*")) if p.is_file()}


def _answer(work_dir: Path) -> None:
    """Echo the packet's own envelope back with a closed PASS."""
    packet = _read(work_dir / cli.REVIEW_DIR / "verification_packet.json")
    (work_dir / cli.REVIEW_DIR / "verification_response.json").write_text(
        S.canonical_json({
            "decision": "PASS", "defects": [], "unmet_requirements": [],
            "missing_evidence": [], "summary": "nothing undeclared visible",
            "review_envelope": packet["review_envelope"]}), encoding="utf-8")


def _verified(root: Path) -> Path:
    """An ordinary authored job carried all the way to a stored VERIFIED."""
    directory = _laid_out(root)
    _author(directory, "block", **BLOCK)
    assert cli.run([str(directory), "--no-render"]) == cli.NEEDS_ACTION
    _answer(directory)
    assert cli.run([str(directory), "--no-render"]) == 0
    assert _read(directory / "final_status.json")["final_status"] == "VERIFIED"
    return directory


def _status(directory: Path) -> dict:
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        cli.status([str(directory), "--json"])
    return json.loads(stream.getvalue())


def _corrupt_the_evidence(directory: Path) -> None:
    """The caliper sheet is corrected after the review that was shown it."""
    (directory / EVIDENCE_FILE).write_text(
        "mount pitch 32.05 mm, digital calipers, re-measured\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# A status derived from what is on disk
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Invalidation, scoped to what depended on the change
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Two formulations, one invalidation
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# An instruction that can say it is out of date
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# The certified lane, which has no frozen acceptance contract at all
# ---------------------------------------------------------------------------

class CertifiedLaneTest(unittest.TestCase):
    """Derivation is not an authored-lane feature bolted onto one code path.

    A certified job has no `acceptance_contract.json`: its contract is derived
    from the project and the template at run time. So the `acceptance` binding is
    absent and the receipts are checked against `model_contract.json`, which is
    what they all carry the hash of either way.
    """

    def _certified(self, root: Path) -> Path:
        directory = root / "project"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "brief.md").write_text("a clip", encoding="utf-8")
        _project(template="c_clip", model=None, envelope_mm=None, evidence=(),
                 verification_requested=False,
                 parameters=dict(ST.FROZEN_PARAMETERS["c_clip"])).save(directory)
        cli.run([str(directory), "--no-render"])
        return directory

    def test_an_untouched_certified_job_derives_what_it_stored(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = self._certified(Path(raw))
            report = _status(directory)
            self.assertEqual("DIRECT", report["route"])
            self.assertEqual("NEEDS_MORE_EVIDENCE", report["stored_status"])
            self.assertEqual("NEEDS_MORE_EVIDENCE", report["final_status"])
            self.assertEqual({}, report["stale"])
            self.assertIsNone(report["state"]["acceptance"],
                              "a certified lane has no frozen acceptance contract")
            self.assertIsNotNone(report["state"]["contract"])

    def test_a_finding_survives_its_bindings_breaking(self) -> None:
        """End to end, on the rule that a broken binding may not hide a defect."""
        with tempfile.TemporaryDirectory() as raw:
            directory = self._certified(Path(raw))
            stl = directory / "candidate.stl"
            stl.write_bytes(stl.read_bytes() + b"\n")

            report = _status(directory)
            self.assertEqual("NEEDS_MORE_EVIDENCE", report["final_status"])
            self.assertIn("final_status.json", report["stale"])
            self.assertIn(B.PIPELINE_RECEIPT, report["stale"])


# ---------------------------------------------------------------------------
# The zero-cost proof
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    unittest.main()
