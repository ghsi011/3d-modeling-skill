"""Tests for `dt.py intake`.

The point of this command is that a measured no-dispatch run spent much of 13.8
minutes typing 246 lines of contract by hand, almost none of it judgment. So the
tests hold it to both halves of that: the mechanical fields must come out right
without help, and the judgment fields must still be demanded rather than
invented.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from . import intake

SCRIPTS = Path(__file__).resolve().parents[1]

_CLIP = ["--param", "bore_d=12.0", "--param", "wall=3.0", "--param", "height=9.0",
         "--param", "mouth_gap=9.0", "--param", "flange=(40.0, 22.0, 5.0)",
         "--param", "screw_d=4.5", "--param", "screw_at=(8.0, 11.0)",
         "--param", "countersink_d=9.0"]


def _run(out: Path, *extra):
    return intake.main(["--job-id", "clip", "--template", "c_clip", *_CLIP,
                        "--updated-utc", "1970-01-01T00:00:00Z", "--out", str(out), *extra])


class TestIntake(unittest.TestCase):
    def test_what_it_writes_validates(self) -> None:
        """A scaffold the contract checker rejects has saved nobody anything."""
        try:
            import trimesh  # noqa: F401
            import manifold3d  # noqa: F401
        except ImportError:
            self.skipTest("needs trimesh + manifold3d")
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            self.assertEqual(0, _run(out))

            done = subprocess.run(
                [sys.executable, "-m", "team_tools.contracts", "validate", str(out),
                 "--require", "job_state,dimensions"],
                cwd=str(SCRIPTS), capture_output=True, text=True, check=False)

            self.assertEqual(0, done.returncode, done.stdout[-1500:])

    def test_every_judgment_is_demanded_not_invented(self) -> None:
        """The consequence-class rationale is the one thing here a machine cannot
        supply, and a scaffold that filled it in with something plausible would
        be worse than one that left the work undone."""
        try:
            import trimesh  # noqa: F401
        except ImportError:
            self.skipTest("needs trimesh")
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            _run(out)

            job = (out / "job_state.md").read_text(encoding="utf-8")
            self.assertIn(intake.REQUIRED, job)
            self.assertIn(f"Rationale: {intake.REQUIRED}", job)

    def test_the_completeness_table_comes_from_the_template(self) -> None:
        """Not from the geometry and not from the author: the template's own
        declaration of what it built, which is the same list the gate measures."""
        try:
            import trimesh  # noqa: F401
        except ImportError:
            self.skipTest("needs trimesh")
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            _run(out)

            sheet = (out / "dimensions.md").read_text(encoding="utf-8")
            for feature in ("channel-mid", "flange-mid", "screw"):
                self.assertIn(feature, sheet)

    def test_it_emits_every_section_the_contract_declares(self) -> None:
        """`validate` only reads frontmatter, so a scaffold missing half the
        body passes it and still fails the reader who follows the spec."""
        try:
            import trimesh  # noqa: F401
        except ImportError:
            self.skipTest("needs trimesh")
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            _run(out)

            job = (out / "job_state.md").read_text(encoding="utf-8")
            for section in ("## Route", "## Bound inputs", "## Gates",
                            "## Dispatches", "## Open user questions"):
                self.assertIn(section, job)

            sheet = (out / "dimensions.md").read_text(encoding="utf-8")
            for section in ("## Frame", "## Sources", "## Blind-build completeness",
                            "## Dimensions", "## Open questions", "## Reference round trip"):
                self.assertIn(section, sheet)

    def test_the_briefs_hash_is_computed_rather_than_demanded(self) -> None:
        """A reader who types a hash by hand has bound the sheet to whatever
        they typed. With no brief there is nothing honest to write, so the
        field stays demanded."""
        try:
            import trimesh  # noqa: F401
        except ImportError:
            self.skipTest("needs trimesh")
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            brief = out / "brief.md"
            brief.write_text("a clip", encoding="utf-8")
            _run(out, "--brief", str(brief))

            sources = [line for line in
                       (out / "dimensions.md").read_text(encoding="utf-8").splitlines()
                       if line.startswith("| S-01")][0]
            self.assertNotIn(intake.REQUIRED, sources)

        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            _run(out)
            sources = [line for line in
                       (out / "dimensions.md").read_text(encoding="utf-8").splitlines()
                       if line.startswith("| S-01")][0]
            self.assertIn(intake.REQUIRED, sources)

    def test_it_will_not_overwrite_an_edited_contract(self) -> None:
        try:
            import trimesh  # noqa: F401
        except ImportError:
            self.skipTest("needs trimesh")
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            _run(out)
            (out / "job_state.md").write_text("hand-edited", encoding="utf-8")

            self.assertEqual(1, _run(out))
            self.assertEqual("hand-edited",
                             (out / "job_state.md").read_text(encoding="utf-8"))

    def test_it_refuses_to_scaffold_a_prohibited_job(self) -> None:
        """R3 never reaches delivery, so making its paperwork quicker only
        smooths a path that must not be walked."""
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            self.assertEqual(2, _run(out, "--risk", "R3_PROHIBITED_AUTONOMOUS_ACCEPTANCE"))
            self.assertFalse((out / "job_state.md").exists())

    def test_an_unknown_template_lists_the_real_ones(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            code = intake.main(["--job-id", "x", "--template", "sprocket",
                                "--updated-utc", "1970-01-01T00:00:00Z", "--out", raw])
            self.assertEqual(2, code)


if __name__ == "__main__":
    unittest.main()
