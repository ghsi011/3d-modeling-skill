"""Tests for the phase-snapshot harness.

Its whole job is to make a measurement reproducible, so the things worth
asserting are the two ways it could quietly stop doing that: overwriting a
snapshot an earlier measurement cited, and restoring on top of output from
another run.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bench  # noqa: E402


def _project(root: Path) -> Path:
    project = root / "job"
    (project / "renders").mkdir(parents=True)
    (project / "job_state.md").write_text("profile: DIRECT\n", encoding="utf-8")
    (project / "model.py").write_text("part = None\n", encoding="utf-8")
    (project / "renders" / "multi.png").write_bytes(b"\x89PNG")
    (project / "__pycache__").mkdir()
    (project / "__pycache__" / "x.pyc").write_bytes(b"junk")
    return project


class TestSnapshot(unittest.TestCase):
    def test_a_round_trip_carries_every_file_including_renders(self) -> None:
        """A resumed run that has to re-render has paid for the build it was
        meant to skip."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, snapshots = _project(root), root / "snaps"

            self.assertEqual(0, bench.save(project, "gated", snapshots, "after direct"))
            self.assertEqual(0, bench.restore("gated", root / "again", snapshots))

            self.assertTrue((root / "again" / "renders" / "multi.png").is_file())
            self.assertEqual("part = None\n",
                             (root / "again" / "model.py").read_text(encoding="utf-8"))

    def test_caches_are_left_behind(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            bench.save(_project(root), "gated", root / "snaps", None)
            bench.restore("gated", root / "again", root / "snaps")
            self.assertFalse((root / "again" / "__pycache__").exists())

    def test_it_will_not_overwrite_a_snapshot(self) -> None:
        """An earlier measurement may cite it by name."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, snapshots = _project(root), root / "snaps"
            bench.save(project, "gated", snapshots, None)

            (project / "model.py").write_text("changed\n", encoding="utf-8")
            self.assertEqual(1, bench.save(project, "gated", snapshots, None))

            kept = snapshots / "gated" / "project" / "model.py"
            self.assertEqual("part = None\n", kept.read_text(encoding="utf-8"))

    def test_it_will_not_restore_onto_another_run(self) -> None:
        """A run that starts on top of someone else's output is not measuring
        what it says it is."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            bench.save(_project(root), "gated", root / "snaps", None)
            occupied = root / "occupied"
            occupied.mkdir()
            (occupied / "leftover.md").write_text("from an earlier run", encoding="utf-8")

            self.assertEqual(1, bench.restore("gated", occupied, root / "snaps"))

    def test_the_manifest_records_what_the_state_was(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            bench.save(_project(root), "gated", root / "snaps", "after direct")

            data = json.loads((root / "snaps" / "gated" / "manifest.json")
                              .read_text(encoding="utf-8"))

            self.assertEqual("after direct", data["note"])
            self.assertIn("job_state.md", data["files"])
            self.assertNotIn("__pycache__/x.pyc", data["files"])

    def test_diff_names_only_what_the_phase_touched(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, snapshots = _project(root), root / "snaps"
            bench.save(project, "gated", snapshots, None)
            (project / "model.py").write_text("edited\n", encoding="utf-8")
            (project / "verification_report.md").write_text("new\n", encoding="utf-8")

            self.assertEqual(0, bench.diff("gated", project, snapshots))

    def test_the_preamble_names_the_confound_it_exists_for(self) -> None:
        """A measurement of this skill has to be a measurement of *this* skill.
        A host can have another installed whose triggers cover the same ground --
        one does, and it opens by telling the reader to pip install a CAD kernel,
        which is the opposite of the design being measured."""
        self.assertIn("only the skill at the path this prompt names", bench.PREAMBLE)
        self.assertIn("say so in your report", bench.PREAMBLE,
                      "a contaminated run must be reportable, not silently averaged in")

    def test_an_unknown_snapshot_is_an_error_not_an_empty_restore(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.assertEqual(2, bench.restore("nope", root / "out", root / "snaps"))
            self.assertFalse((root / "out").exists())


if __name__ == "__main__":
    unittest.main()
