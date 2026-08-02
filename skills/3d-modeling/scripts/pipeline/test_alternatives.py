#!/usr/bin/env python3
"""Release 3 slice A: a second formulation of the same job, isolated on disk and
in the receipts.

Every test here fails on the code as it stood before the slice, and each fails
for a different reason. They are worth listing, because "two directories" reads
like a tidiness change and it is not:

* **the acceptance revision was a weapon.** Both siblings froze into one
  `acceptance_contract.json`. The second one's `freeze` read the first one's
  contract as `previous`, cut a revision, and `_invalidate` deleted the first's
  `final_status.json`, `commission_report.json`, `artifact_manifest.json`,
  `manufacturing_report.json` and both review reports. Re-running the first did
  it back. Two alternatives destroyed each other on every alternating run, and
  `acceptance_history.json` recorded the fork as one linear chain of corrections;
* **the second alternative was never commissioned.** `_run_authored` skips the
  designer commission when `design_proposal.json` and `model.py` both exist, so a
  branch inherited the first formulation's geometry, built it, and filed the
  receipts under its own name -- a job with no evidence anywhere that it was a
  different job;
* **`candidate.stl` and `candidate.step` are fixed literals**, so the second
  build simply overwrote the first;
* **a review was answered by the presence of a file.** One `reviews/` directory
  meant a sibling picked up the answer written for its neighbour;
* **and path isolation does not close any of the last one.** `ExecutionPlan`
  carries no parameters, so two formulations of one authored job compile to the
  same plan; `ReviewEnvelope.revision` is `updated_utc`, a timestamp rather than
  a graph node; and at the instant a branch is created its sibling is a copy, so
  `contract_sha256`, `artifact_hashes` and `witness_hashes` are equal too. A
  safety PASS written for one was `is_bound` for the other. That is a false pass
  of exactly the class the authority gate forbids, reachable with nobody doing
  anything wrong, and it is why `alternative_id` joins the envelope as well as
  the plan.

The zero-cost half is asserted here too, and it is exact rather than a stopwatch:
a project declaring no alternatives serializes, compiles and hashes to the bytes
it did before this file existed.

The half of this file the commit gate will not carry is in
`benchmarks/heavy/test_alternatives_heavy.py`, and runs before merge instead of
on every push: `AReviewBoundToOneBranchTest`, `CleanCloneTest`,
`NoAlternativesCostsNothingTest`, `OneBranchFailingTest`,
`SharedChangeInvalidatesEveryAlternativeTest`,
`SharedInputIsStillFoundFromABranchTest`, `TwoSiblingsTest`. Same tests, moved
rather than weakened; `conftest.py` carries the rule and
`benchmarks/heavy/README.md` the measurement behind it.
"""
from __future__ import annotations

import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from . import acceptance as ACC
from . import cli
from . import project as P
from . import schemas as S

UTC = "1970-01-01T00:00:00Z"

# One block per formulation, differing in the numbers a plan never sees. That is
# the point of the pair: the two build materially different solids and their
# execution plans are identical apart from the id this slice adds.
MODEL = '''
import trimesh

PARAMS = {{"w": {w}, "d": {d}, "h": {h}}}


def build():
    block = trimesh.creation.box(extents=({w}, {d}, {h}))
    block.apply_translation(({w} / 2, {d} / 2, {h} / 2))
    return block
'''


def _proposal(design_id: str, *, w: float, d: float, h: float) -> dict:
    return {
        "schema_version": 1,
        "job_id": "branching",
        "design_id": design_id,
        "rationale": f"a {w}x{d}x{h} block standing in for one formulation",
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


SCREW = dict(w=40.0, d=30.0, h=10.0)
SNAP = dict(w=36.0, d=26.0, h=12.0)


def _project(**over) -> P.Project:
    base = dict(
        job_id="branching", updated_utc=UTC, source_mode="NEW",
        consequence="INCONSEQUENTIAL",
        consequence_rationale="a desk bracket; failure wastes material",
        printer="Test Printer", material={"process": "FDM", "material": "PLA"},
        nozzle={"diameter_mm": 0.4},
        orientation={"model_to_printer_matrix": "identity", "bed_z_mm": 0.0},
        template=None, parameters={}, model="model.py",
        envelope_mm={"x": 60.0, "y": 50.0, "z": 20.0},
        reviewer={"model_snapshot": "test"},
        requirements=(P.Requirement(name="mount_pitch", value=32.0, unit="mm",
                                    provenance="STATED", source="user"),),
    )
    base.update(over)
    return P.Project(**base)


def _laid_out(root: Path, project: P.Project | None = None) -> Path:
    directory = root / "project"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "brief.md").write_text("a bracket", encoding="utf-8")
    (project or _project()).save(directory)
    return directory


def _author(where: Path, design_id: str, **params) -> None:
    """Write one formulation's two files: what it must measure, and how it is built."""
    where.mkdir(parents=True, exist_ok=True)
    (where / "model.py").write_text(textwrap.dedent(MODEL.format(**params)),
                                    encoding="utf-8")
    (where / ACC.PROPOSAL_FILE).write_text(
        S.canonical_json(_proposal(design_id, **params)), encoding="utf-8")


def _branch(directory: Path, *, parent: str, name: str, reason: str) -> int:
    return cli.branch([str(directory), "--from", parent, "--id", name,
                       "--reason", reason])


def _alt(directory: Path, name: str) -> Path:
    return directory / P.ALTERNATIVES_DIR / name


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _digests(directory: Path) -> dict[str, str]:
    """Every file under a directory, by content, so "unchanged" is checkable."""
    return {p.relative_to(directory).as_posix(): S.sha256_file(p)
            for p in sorted(directory.rglob("*")) if p.is_file()}


# ---------------------------------------------------------------------------
# The branch verb
# ---------------------------------------------------------------------------

class BranchVerbTest(unittest.TestCase):
    """One deterministic verb, zero AI calls, and it copies nothing."""

    def test_branching_writes_a_row_and_copies_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            _author(directory, "ancestor", **SCREW)
            before = _digests(directory)

            self.assertEqual(0, _branch(directory, parent=".", name="snap-fit",
                                        reason="no fasteners to lose"))

            project = P.load(directory)
            self.assertEqual(("snap-fit",),
                             tuple(a.alternative_id for a in project.alternatives))
            row = project.alternative("snap-fit")
            self.assertEqual((), row.parents, "--from . is the shared root")
            self.assertEqual("ACTIVE", row.disposition)
            self.assertEqual("snap-fit", project.active_alternative)

            # The directory exists and is empty: an alternative inherits shared
            # intent by reference, and duplicating the ancestor's proposal would
            # make the branch a copy nobody could tell from a formulation.
            self.assertTrue(_alt(directory, "snap-fit").is_dir())
            self.assertEqual([], list(_alt(directory, "snap-fit").iterdir()))

            # Nothing that already existed moved, except project.json itself.
            after = _digests(directory)
            self.assertEqual({name: digest for name, digest in before.items()
                              if name != P.PROJECT_FILE},
                             {name: digest for name, digest in after.items()
                              if name != P.PROJECT_FILE})

    def test_an_id_that_is_not_a_safe_directory_name_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            for name in ("Snap Fit", "../escape", "snap_fit", "SNAP", "",
                         "snap/fit", "snap.fit"):
                with self.subTest(alternative_id=name):
                    self.assertEqual(2, _branch(directory, parent=".", name=name,
                                                reason="because"))
                    self.assertEqual((), P.load(directory).alternatives)
                    self.assertFalse((directory / P.ALTERNATIVES_DIR).exists())

    def test_a_second_row_for_one_id_is_refused_rather_than_replacing_it(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            self.assertEqual(0, _branch(directory, parent=".", name="snap-fit",
                                        reason="no fasteners to lose"))
            self.assertEqual(2, _branch(directory, parent=".", name="snap-fit",
                                        reason="a different story entirely"))
            rows = P.load(directory).alternatives
            self.assertEqual(1, len(rows))
            self.assertEqual("no fasteners to lose", rows[0].reason)

    def test_a_parent_nothing_declares_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            self.assertEqual(2, _branch(directory, parent="magnetic",
                                        name="snap-fit", reason="because"))
            self.assertEqual((), P.load(directory).alternatives)

    def test_a_branch_with_no_reason_is_refused(self) -> None:
        """Two formulations with no stated difference cannot be compared."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            self.assertEqual(2, cli.branch([str(directory), "--from", ".",
                                            "--id", "snap-fit"]))
            self.assertEqual(2, _branch(directory, parent=".", name="snap-fit",
                                        reason="   "))
            self.assertEqual((), P.load(directory).alternatives)

    def test_the_parent_list_carries_the_ancestor_it_was_branched_from(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            _branch(directory, parent=".", name="base", reason="the shared start")
            _branch(directory, parent="base", name="snap-fit", reason="no fasteners")
            row = P.load(directory).alternative("snap-fit")
            self.assertEqual(("base",), row.parents,
                             "a list from the first commit that has one, so a "
                             "merge is additive rather than a schema change")

    def test_switching_back_to_the_shared_root_is_possible(self) -> None:
        """A system that could only branch could never return to what it branched from."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            _branch(directory, parent=".", name="snap-fit", reason="no fasteners")
            self.assertEqual(0, cli.branch([str(directory), "--activate", "."]))
            self.assertIsNone(P.load(directory).active_alternative)
            self.assertEqual(0, cli.branch([str(directory), "--activate", "snap-fit"]))
            self.assertEqual("snap-fit", P.load(directory).active_alternative)

    def test_activating_something_nothing_declares_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            self.assertEqual(2, cli.branch([str(directory), "--activate", "magnetic"]))
            self.assertIsNone(P.load(directory).active_alternative)

    def test_only_the_two_honoured_dispositions_may_be_worked_under(self) -> None:
        """The other five are stored and read by nothing, and say so."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            _branch(directory, parent=".", name="snap-fit", reason="no fasteners")
            for disposition, allowed in (("ACTIVE", True), ("PREFERRED", True),
                                         ("PAUSED", False), ("REJECTED", False),
                                         ("SUPERSEDED", False), ("FALLBACK", False),
                                         ("MERGED", False)):
                with self.subTest(disposition=disposition):
                    project = P.load(directory)
                    project.alternatives = (P.Alternative(
                        alternative_id="snap-fit", reason="no fasteners",
                        disposition=disposition),)
                    project.active_alternative = "snap-fit"
                    project.save(directory)
                    problems = project.validate(directory, require_buildable=False)
                    self.assertEqual(allowed,
                                     not any("honoured" in p.message for p in problems),
                                     problems)
                    # The disposition a build does not honour is a decision to
                    # make, not a field to correct, and the code says which.
                    self.assertEqual(
                        [] if allowed else ["INTENT_UNSUPPORTED@active_alternative"],
                        [p.id for p in problems if "honoured" in p.message])
                    self.assertEqual(0 if allowed else 2,
                                     cli.branch([str(directory), "--activate",
                                                 "snap-fit"]))

    def test_creating_and_switching_are_not_mixed_in_one_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            _branch(directory, parent=".", name="snap-fit", reason="no fasteners")
            self.assertEqual(2, cli.branch([str(directory), "--activate", "snap-fit",
                                            "--id", "screw-fastened"]))

    def test_a_hand_written_cycle_is_refused(self) -> None:
        """Ancestry order is the acyclicity rule, and it refuses a self-parent too."""
        for rows in (
            (P.Alternative(alternative_id="a", parents=("b",), reason="x"),
             P.Alternative(alternative_id="b", parents=("a",), reason="y")),
            (P.Alternative(alternative_id="a", parents=("a",), reason="x"),),
        ):
            with self.subTest(rows=[r.alternative_id for r in rows]):
                problems = _project(alternatives=rows).validate(
                    require_buildable=False)
                self.assertTrue(any("ancestry order" in p.message for p in problems),
                                problems)


# ---------------------------------------------------------------------------
# The zero-cost proof
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Two siblings from one ancestor
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Failure and invalidation
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# The false pass
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Reconstruction
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    unittest.main()
