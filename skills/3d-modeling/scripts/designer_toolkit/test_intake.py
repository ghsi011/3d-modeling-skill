"""Tests for `dt.py intake`.

The point of this command is that a measured no-dispatch run spent much of 13.8
minutes typing 246 lines of contract by hand, almost none of it judgment. So the
tests hold it to both halves of that: the mechanical fields must come out right
without help, and the judgment fields must still be demanded rather than
invented.
"""
from __future__ import annotations

import hashlib
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
    def test_off_template_input_writes_valid_contracts_with_visible_provenance(self) -> None:
        """Imported geometry is a supported starting point, not an accidental
        template name that should be rejected or silently treated as one.
        """
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            artifact = out / "imported.stl"
            artifact.write_bytes(b"imported mesh bytes")
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
            code = intake.main([
                "--job-id", "imported", "--template", "none",
                "--param", "overall_mm=(30.0, 20.0, 10.0)",
                "--param", "clearance=0.25",
                "--imported-artifact", str(artifact), "--imported-sha256", digest,
                "--inherited", "overall_mm", "--chosen", "clearance",
                "--inherited-method", "overall_mm=CAD bounding-box measurement",
                "--updated-utc", "1970-01-01T00:00:00Z", "--out", str(out),
            ])

            self.assertEqual(0, code)
            for name in ("job_state.md", "dimensions.md"):
                self.assertTrue((out / name).is_file())
            job = (out / "job_state.md").read_text(encoding="utf-8")
            dimensions = (out / "dimensions.md").read_text(encoding="utf-8")
            self.assertIn("off-template", job)
            self.assertIn("profile: FULL", job)
            self.assertNotIn("profile: DIRECT", job)
            self.assertIn("backend: trimesh-manifold", job)
            for text in (job, dimensions):
                self.assertIn("imported.stl", text)
                self.assertIn(digest, text)
            self.assertIn("inherited from imported solid", dimensions)
            self.assertIn("inherited from imported solid; CAD bounding-box measurement", dimensions)
            self.assertNotIn("none is image-derived or measured", dimensions)
            self.assertIn("| overall_mm |", dimensions)
            self.assertIn("| clearance | 0.25 | chosen by design |", dimensions)
            self.assertNotIn("| clearance | 0.25 | inherited from imported solid |", dimensions)

    def test_inherited_dimensions_require_explicit_methods(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            artifact = out / "imported.stl"
            artifact.write_bytes(b"mesh")
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()

            code = intake.main([
                "--job-id", "missing-method", "--template", "none",
                "--param", "width=10.0", "--imported-artifact", str(artifact),
                "--imported-sha256", digest, "--inherited", "width",
                "--updated-utc", "1970-01-01T00:00:00Z", "--out", str(out),
            ])

            self.assertEqual(2, code)
            self.assertFalse((out / "job_state.md").exists())

    def test_inherited_methods_reject_unknown_keys(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            artifact = out / "imported.stl"
            artifact.write_bytes(b"mesh")
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()

            code = intake.main([
                "--job-id", "unknown-method", "--template", "none",
                "--param", "width=10.0", "--imported-artifact", str(artifact),
                "--imported-sha256", digest, "--inherited", "width",
                "--inherited-method", "depth=CAD measurement",
                "--updated-utc", "1970-01-01T00:00:00Z", "--out", str(out),
            ])

            self.assertEqual(2, code)
            self.assertFalse((out / "job_state.md").exists())

    def test_inherited_methods_reject_duplicate_or_ambiguous_keys(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            artifact = out / "imported.stl"
            artifact.write_bytes(b"mesh")
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()

            code = intake.main([
                "--job-id", "duplicate-method", "--template", "none",
                "--param", "width=10.0", "--imported-artifact", str(artifact),
                "--imported-sha256", digest, "--inherited", "width",
                "--inherited-method", "width=CAD measurement",
                "--inherited-method", "width=mesh measurement",
                "--updated-utc", "1970-01-01T00:00:00Z", "--out", str(out),
            ])

            self.assertEqual(2, code)
            self.assertFalse((out / "job_state.md").exists())

    def test_inherited_methods_reject_chosen_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            artifact = out / "imported.stl"
            artifact.write_bytes(b"mesh")
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()

            code = intake.main([
                "--job-id", "chosen-method", "--template", "none",
                "--param", "width=10.0", "--imported-artifact", str(artifact),
                "--imported-sha256", digest, "--chosen", "width",
                "--inherited-method", "width=CAD measurement",
                "--updated-utc", "1970-01-01T00:00:00Z", "--out", str(out),
            ])

            self.assertEqual(2, code)
            self.assertFalse((out / "job_state.md").exists())

    def test_step_import_maps_to_the_existing_brep_backend(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            artifact = out / "imported.step"
            artifact.write_bytes(b"step source")
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
            code = intake.main([
                "--job-id", "step-import", "--template", "none",
                "--imported-artifact", str(artifact), "--imported-sha256", digest,
                "--updated-utc", "1970-01-01T00:00:00Z", "--out", str(out),
            ])

            self.assertEqual(0, code)
            job = (out / "job_state.md").read_text(encoding="utf-8")
            self.assertIn("profile: FULL", job)
            self.assertIn("backend: build123d", job)

            done = subprocess.run(
                [sys.executable, "-m", "team_tools.contracts", "validate", str(out),
                 "--require", "job_state,dimensions"],
                cwd=str(SCRIPTS), capture_output=True, text=True, check=False)
            self.assertEqual(0, done.returncode, done.stdout[-1500:])

    def test_off_template_requires_an_existing_imported_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw) / "project"
            code = intake.main([
                "--job-id", "missing", "--template", "none",
                "--imported-artifact", str(out / "missing.stl"),
                "--imported-sha256", "0" * 64,
                "--updated-utc", "1970-01-01T00:00:00Z", "--out", str(out),
            ])

            self.assertEqual(2, code)
            self.assertFalse(out.exists())

    def test_off_template_rejects_a_hash_that_does_not_match_the_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            artifact = out / "imported.stl"
            artifact.write_bytes(b"mesh")

            code = intake.main([
                "--job-id", "wrong-hash", "--template", "none",
                "--imported-artifact", str(artifact), "--imported-sha256", "0" * 64,
                "--updated-utc", "1970-01-01T00:00:00Z", "--out", str(out),
            ])

            self.assertEqual(2, code)
            self.assertFalse((out / "job_state.md").exists())

    def test_off_template_cannot_be_marked_direct(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            artifact = out / "imported.stl"
            artifact.write_bytes(b"mesh")
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()

            code = intake.main([
                "--job-id", "direct-import", "--template", "none", "--profile", "DIRECT",
                "--imported-artifact", str(artifact), "--imported-sha256", digest,
                "--updated-utc", "1970-01-01T00:00:00Z", "--out", str(out),
            ])

            self.assertEqual(2, code)
            self.assertFalse((out / "job_state.md").exists())

    def test_off_template_rejects_unsupported_artifact_types(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            artifact = out / "imported.txt"
            artifact.write_bytes(b"not a supported geometry artifact")
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()

            code = intake.main([
                "--job-id", "unsupported", "--template", "none",
                "--imported-artifact", str(artifact), "--imported-sha256", digest,
                "--updated-utc", "1970-01-01T00:00:00Z", "--out", str(out),
            ])

            self.assertEqual(2, code)
            self.assertFalse((out / "job_state.md").exists())

    def test_off_template_rejects_ambiguous_dimension_classification(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            artifact = out / "imported.stl"
            artifact.write_bytes(b"mesh")
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()

            code = intake.main([
                "--job-id", "ambiguous", "--template", "none",
                "--param", "width=10.0", "--imported-artifact", str(artifact),
                "--imported-sha256", digest, "--inherited", "width", "--chosen", "width",
                "--updated-utc", "1970-01-01T00:00:00Z", "--out", str(out),
            ])

            self.assertEqual(2, code)
            self.assertFalse((out / "job_state.md").exists())

    def test_off_template_rejects_unclassified_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            artifact = out / "imported.stl"
            artifact.write_bytes(b"mesh")
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()

            code = intake.main([
                "--job-id", "unclassified", "--template", "none",
                "--param", "width=10.0", "--imported-artifact", str(artifact),
                "--imported-sha256", digest, "--inherited", "other",
                "--updated-utc", "1970-01-01T00:00:00Z", "--out", str(out),
            ])

            self.assertEqual(2, code)
            self.assertFalse((out / "job_state.md").exists())

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

    def test_consequential_jobs_are_scaffolded(self) -> None:
        """CONSEQUENTIAL jobs need independent verification, but intake still
        scaffolds their contracts — the prohibition is on acceptance, not on
        writing the job_state."""
        try:
            import trimesh  # noqa: F401
            import manifold3d  # noqa: F401
        except ImportError:
            self.skipTest("needs trimesh + manifold3d")
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            self.assertEqual(0, _run(out, "--consequence", "CONSEQUENTIAL"))
            self.assertTrue((out / "job_state.md").exists())

    def test_legacy_risk_option_is_not_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(SystemExit) as raised:
                _run(Path(raw), "--risk", "INCONSEQUENTIAL")
            self.assertEqual(2, raised.exception.code)

    def test_an_unknown_template_lists_the_real_ones(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            code = intake.main(["--job-id", "x", "--template", "sprocket",
                                "--updated-utc", "1970-01-01T00:00:00Z", "--out", raw])
            self.assertEqual(2, code)


if __name__ == "__main__":
    unittest.main()


class ProvenanceTest(unittest.TestCase):
    """Where each number in `dimensions.md` says it came from.

    Every row used to read `stated in the brief / user / B`, on the reasoning
    that user-stated numbers are the condition for the DIRECT route. They are
    not: the condition is that nothing needs measuring. A brief asking for a
    clip over a 12 mm bundle states three numbers and `c_clip` takes eight, so
    five rows claimed the user's authority for values the caller invented -- on
    the one document whose entire purpose is provenance.
    """

    _PARAMS = {"bore_d": 12.0, "wall": 3.0, "screw_d": 4.8}

    def _rows(self, stated: frozenset[str]) -> str:
        return intake._dimension_rows(self._PARAMS, stated)

    def test_unlisted_parameters_are_the_designers_choice(self) -> None:
        rows = self._rows(frozenset({"bore_d"}))
        self.assertIn("| bore_d | 12.0 | stated in the brief | user | B |", rows)
        self.assertIn("| wall | 3.0 | chosen by design | designer | D |", rows)
        self.assertIn("| screw_d | 4.8 | chosen by design | designer | D |", rows)

    def test_the_default_never_claims_the_user_said_anything(self) -> None:
        """The direction of the failure is the point. Forgetting `--stated`
        understates the caller's own confidence, which invites scrutiny;
        the reverse manufactures a statement the user never made, and nothing
        downstream of the sheet can tell."""
        rows = self._rows(frozenset())
        self.assertNotIn("stated in the brief", rows)
        self.assertNotIn("| user |", rows)
        self.assertEqual(3, rows.count("chosen by design"))

    def test_stated_accepts_a_comma_list_and_repeated_flags(self) -> None:
        self.assertEqual(frozenset({"a", "b", "c"}),
                         intake._stated(["a,b", "c"]))
        self.assertEqual(frozenset({"a", "b"}),
                         intake._stated([" a , b "]))
        self.assertEqual(frozenset(), intake._stated([]))
