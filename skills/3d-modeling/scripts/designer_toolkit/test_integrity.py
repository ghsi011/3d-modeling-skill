"""Tests for the raw-parse integrity read.

This is the one acceptance check a verifier cannot delegate to the gate -- every
shared tool downstream loads the normalized mesh, so an export defect only shows
on the raw side. It existed only as a snippet each verifier wrote by hand, in
the one step whose whole point is that it must not be re-authored.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import trimesh

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from designer_toolkit import integrity  # noqa: E402


def _stl(path: Path) -> Path:
    box = trimesh.creation.box(extents=(20.0, 15.0, 10.0))
    box.apply_translation((0.0, 0.0, 5.0))
    box.export(path)
    return path


class ReportTest(unittest.TestCase):
    def test_it_reports_the_raw_parse_not_the_repaired_one(self) -> None:
        """The raw side is authoritative: a repaired copy can convert a genuine
        export defect into a pass."""
        with tempfile.TemporaryDirectory() as raw:
            data = integrity.report(_stl(Path(raw) / "box.stl"))

            self.assertIn("raw_integrity", data)
            self.assertIn("degenerate_face_count", data["raw_integrity"])
            self.assertIn("mutation_log", data)

    def test_a_sound_part_still_reads_as_many_components(self) -> None:
        """The reading most likely to be mistaken for a defect. An STL stores no
        vertex sharing, so this is the format talking."""
        with tempfile.TemporaryDirectory() as raw:
            data = integrity.report(_stl(Path(raw) / "box.stl"))

            self.assertGreater(data["raw_integrity"]["components"], 1)
            self.assertEqual(0, data["raw_integrity"]["degenerate_face_count"])
            self.assertIn("That is the format", data["reading_note"])

    def test_the_normalized_hash_is_present(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            data = integrity.report(_stl(Path(raw) / "box.stl"))

            self.assertEqual(64, len(data["normalized_sha256"]))


class CliTest(unittest.TestCase):
    def test_it_emits_parseable_json(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            completed = subprocess.run(
                [sys.executable, "-m", "designer_toolkit", "integrity",
                 str(_stl(work / "box.stl"))],
                cwd=_SCRIPTS, capture_output=True, text=True, check=False)

            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertIn("raw_integrity", json.loads(completed.stdout))

    def test_a_missing_file_is_named_not_tracebacked(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            completed = subprocess.run(
                [sys.executable, "-m", "designer_toolkit", "integrity",
                 str(Path(raw) / "absent.stl")],
                cwd=_SCRIPTS, capture_output=True, text=True, check=False)

            self.assertEqual(2, completed.returncode)
            self.assertIn("absent.stl", completed.stderr)


if __name__ == "__main__":
    unittest.main()
