"""Tests for `dt.py audit` — the verifier's mechanical half, in one call.

The charter used to ask for six commands and justified the expensive one by
saying it "has never once disagreed". That is an argument for collapsing the
chain, not for trusting it, so these tests hold the collapsed version to what
the six were actually for: noticing that the delivered bytes are not the ones
the receipt describes, and noticing it whichever way the substitution happened.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import trimesh
except ImportError:  # pragma: no cover
    trimesh = None

SCRIPTS = Path(__file__).resolve().parents[1]
LAUNCHER = SCRIPTS / "dt.py"

_CLIP = [
    "--param", "bore_d=12.0", "--param", "wall=3.0", "--param", "height=9.0",
    "--param", "mouth_gap=9.0", "--param", "flange=(40.0, 22.0, 5.0)",
    "--param", "screw_d=4.5", "--param", "screw_at=(8.0, 11.0)",
    "--param", "countersink_d=9.0",
]


def _dt(*args, cwd=None):
    return subprocess.run([sys.executable, str(LAUNCHER), *args], cwd=cwd,
                          capture_output=True, text=True, check=False)


def _built_project(root: Path) -> Path:
    """A real gated candidate: the thing a verifier is handed."""
    project = root / "job"
    project.mkdir()
    _dt("build", "--template", "c_clip", *_CLIP, "--out", str(project / "model.py"))
    _dt("plan", "template", "--bbox", "40", "22", "14", "--job-id", "a",
        "--updated-utc", "1970-01-01T00:00:00Z",
        "--out", str(project / "print_plan_checks.json"))
    _dt("commission", "--model", "model.py", "--plan", "print_plan_checks.json",
        "--out", ".", "--job-id", "a", "--updated-utc", "1970-01-01T00:00:00Z",
        "--no-render", cwd=project)
    return project


def _audit(project: Path, out: Path):
    done = _dt("audit", str(project), "--out", str(out), "--job-id", "a",
               "--updated-utc", "1970-01-01T00:00:00Z")
    payload = json.loads(done.stdout) if done.stdout.strip().startswith("{") else None
    return done, payload


def _by_id(payload):
    return {c["id"]: c["result"] for c in payload["checks"]}


@unittest.skipIf(trimesh is None, "needs trimesh + manifold3d")
class TestAudit(unittest.TestCase):
    def test_a_clean_candidate_agrees_with_its_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project = _built_project(root)

            _done, payload = _audit(project, root / "verify")

            results = _by_id(payload)
            self.assertEqual("PASS", results["binding"])
            self.assertEqual("PASS", results["recompute"],
                             next(c["detail"] for c in payload["checks"]
                                  if c["id"] == "recompute"))

    def test_degenerate_geometry_fails_through_the_recomputation(self) -> None:
        """There is deliberately no separate raw-parse check. `normalize_mesh`
        counts degenerate faces on an unmutated copy before removing any, so the
        number is identical to the one the recomputation's `repair` check already
        fails on -- and two paths to one number are how the overhang area came to
        disagree with itself by 2x."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project = _built_project(root)
            mesh = trimesh.load(project / "candidate-01.stl")
            import numpy as np
            broken = trimesh.Trimesh(vertices=mesh.vertices,
                                     faces=np.vstack([mesh.faces, [0, 0, 0]]),
                                     process=False)
            broken.export(project / "candidate-01.stl")

            done, payload = _audit(project, root / "verify")

            self.assertEqual(1, done.returncode)
            mine = json.loads((root / "verify" / "commission.json").read_text(encoding="utf-8"))
            repair = next(c for c in mine["checks"] if c["id"] == "repair")
            self.assertEqual("FAIL", repair["result"], repair["detail"])
            self.assertIn("raw_integrity", payload["evidence"])

    def test_a_swapped_stl_fails_the_binding(self) -> None:
        """The one thing re-measuring was actually for. A part 2% taller is the
        same shape, passes every check on its own terms, and is not the part the
        receipt describes."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project = _built_project(root)
            mesh = trimesh.load(project / "candidate-01.stl")
            mesh.apply_scale([1.0, 1.0, 1.02])
            mesh.export(project / "candidate-01.stl")

            done, payload = _audit(project, root / "verify")

            self.assertEqual(1, done.returncode)
            self.assertEqual("FAIL", _by_id(payload)["binding"])

    def test_the_recomputation_sees_the_templates_own_expectations(self) -> None:
        """A verifier holds the STL and the plan, never model.py. Without the
        rows carried through the designer's evidence, its recomputation came back
        missing exactly the checks that catch a geometry regression -- quieter
        than the run it was checking, and reporting agreement."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project = _built_project(root)

            _done, payload = _audit(project, root / "verify")

            mine = json.loads((root / "verify" / "commission.json").read_text(encoding="utf-8"))
            ids = {c["id"] for c in mine["checks"]}
            self.assertIn("feature-screw", ids)
            self.assertIn("feature-flange-mid", ids)

    def test_writing_over_the_project_is_refused(self) -> None:
        """The comparison is against the designer's receipts. A run that writes
        into the project root destroys what it came to check -- and one did."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project = _built_project(root)

            done = _dt("audit", str(project), "--out", str(project), "--job-id", "a",
                       "--updated-utc", "1970-01-01T00:00:00Z")

            self.assertEqual(2, done.returncode)
            self.assertIn("must not be the project root", done.stderr)

    def test_it_names_the_images_rather_than_leaving_them_to_be_found(self) -> None:
        """A verifier that has to discover which renders exist spends turns on
        directory listings before it has looked at anything, and turns are the
        cost here."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project = root / "job"
            project.mkdir()
            _dt("build", "--template", "c_clip", *_CLIP, "--out", str(project / "model.py"))
            _dt("plan", "template", "--bbox", "40", "22", "14", "--job-id", "a",
                "--updated-utc", "1970-01-01T00:00:00Z",
                "--out", str(project / "print_plan_checks.json"))
            _dt("commission", "--model", "model.py", "--plan", "print_plan_checks.json",
                "--out", ".", "--job-id", "a", "--updated-utc", "1970-01-01T00:00:00Z",
                cwd=project)
            if not (project / "renders").is_dir():
                self.skipTest("this interpreter has no renderer")

            _done, payload = _audit(project, root / "verify")

            self.assertTrue(payload["evidence"]["look_at"],
                            "renders exist and the audit did not name them")

    def test_no_renders_names_no_images_rather_than_inventing_them(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _done, payload = _audit(_built_project(root), root / "verify")
            self.assertEqual([], payload["evidence"]["look_at"])

    def test_it_says_what_no_tool_settled(self) -> None:
        """Collapsing the chain must not read as "verification is done". Every
        defect this role ever found came from looking at renders."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _done, payload = _audit(_built_project(root), root / "verify")

            remaining = " ".join(payload["still_requires_a_look"]).lower()
            self.assertIn("image", remaining)
            self.assertIn("sheet", remaining)


class TestStructuralAbsence(unittest.TestCase):
    def test_only_named_checks_may_go_missing(self) -> None:
        """Treating "absent" as "fine" in general is how a recomputation comes
        back quietly emptier than the run it is checking."""
        from .audit import _structurally_absent

        for check_id in ("step", "render", "static-wall", "static-envelope"):
            self.assertTrue(_structurally_absent(check_id), check_id)
        for check_id in ("solid", "envelope", "fit", "repair", "feature-screw",
                         "support-S-01", "edge-E-01"):
            self.assertFalse(_structurally_absent(check_id), check_id)


if __name__ == "__main__":
    unittest.main()
