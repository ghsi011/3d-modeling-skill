#!/usr/bin/env python3
"""L0-heavy — the half of
`skills/3d-modeling/scripts/designer_toolkit/test_build.py`
that costs a child interpreter.

The repository-root `conftest.py` refuses a child interpreter inside the commit
gate, and these classes start one. Same tests, moved rather than weakened;
`benchmarks/heavy/README.md` records the profile that decided the seam and what
runs this tier. What stayed behind is what answers in the parent process.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from designer_toolkit import build

# The fixtures this half shares with the half that stayed behind,
# imported rather than copied: two spellings of one fixture is how
# two tiers stop testing the same thing.
from designer_toolkit.test_build import (  # noqa: E402
    LAUNCHER,
    _CLIP,
)


class TestBuildCommand(unittest.TestCase):
    def test_bad_parameters_fail_here_not_in_the_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "model.py"
            code = build.main(["--template", "c_clip", "--param", "bore_d=12.0", "--out", str(out)])
            self.assertEqual(1, code)
            self.assertFalse(out.exists(), "a model that cannot build must not be left on disk")

    def test_the_generated_model_passes_the_gate(self) -> None:
        try:
            import trimesh  # noqa: F401
            import manifold3d  # noqa: F401
        except ImportError:
            self.skipTest("needs trimesh + manifold3d")
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp)
            self.assertEqual(0, subprocess.run(
                [sys.executable, str(LAUNCHER), "build", "--template", "c_clip",
                 *_CLIP, "--out", str(job / "model.py")],
                capture_output=True, check=False).returncode)
            self.assertEqual(0, subprocess.run(
                [sys.executable, str(LAUNCHER), "plan", "template", "--bbox", "40", "22", "14",
                 "--job-id", "b", "--updated-utc", "1970-01-01T00:00:00Z",
                 "--out", str(job / "print_plan_checks.json")],
                capture_output=True, check=False).returncode)

            done = subprocess.run(
                [sys.executable, str(LAUNCHER), "commission", "--model", "model.py",
                 "--plan", "print_plan_checks.json", "--out", ".", "--job-id", "b",
                 "--updated-utc", "1970-01-01T00:00:00Z", "--no-render"],
                cwd=job, capture_output=True, text=True, check=False)

            self.assertEqual(0, done.returncode, done.stdout[-3000:] + done.stderr[-2000:])

    def test_a_template_regression_fails_the_generated_model_at_the_gate(self) -> None:
        """End to end, on the defect that actually shipped: the countersink cut
        out of the template while the model file still asks for one. Nothing in
        the generated file changes -- only the geometry it produces -- so this is
        the path a real regression would take."""
        try:
            import trimesh
            import manifold3d  # noqa: F401
        except ImportError:
            self.skipTest("needs trimesh + manifold3d")
        from designer_toolkit import commission, templates

        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp)
            build.main(["--template", "c_clip", *_CLIP, "--out", str(job / "model.py")])
            plan = {"contract": "print-plan", "contract_version": 4, "job_id": "b",
                    "revision": 1, "owner": "print-engineer", "interfaces": [], "edges": [],
                    "expected_bbox_mm": {"x": 40.0, "y": 22.0, "z": 14.0},
                    "bbox_tolerance_mm": 0.5,
                    "support_rules": [{"id": "S-01", "disposition": "SELF_SUPPORT_REQUIRED",
                                       "downward_normal_z_max": -0.73,
                                       "max_out_of_limit_area_mm2": 0.0,
                                       "model_to_printer_matrix": [[1, 0, 0, 0], [0, 1, 0, 0],
                                                                   [0, 0, 1, 0], [0, 0, 0, 1]],
                                       "bed_z_mm": 0.0, "bed_tolerance_mm": 0.05}]}

            healthy = commission.run(model=job / "model.py", stl=None, out_dir=job / "a",
                                     plan=plan, render=False)
            self.assertEqual("PASS", healthy.as_dict()["verdict"], healthy.as_dict()["checks"])

            original = templates._frustum
            try:
                templates._frustum = lambda *a, **k: trimesh.creation.box(
                    extents=(1e-6, 1e-6, 1e-6))
                regressed = commission.run(model=job / "model.py", stl=None,
                                           out_dir=job / "b", plan=plan, render=False)
            finally:
                templates._frustum = original

            failed = [c.id for c in regressed.failed]
            self.assertIn("feature-screw", failed,
                          "a countersink missing from the solid must fail the gate")

    def test_what_it_writes_is_the_file_a_designer_would_edit(self) -> None:
        """Not a pickle, not a blob: a part that later needs a feature no
        template offers has to be able to start from this file."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "model.py"
            build.main(["--template", "c_clip", *_CLIP, "--out", str(out)])
            text = out.read_text(encoding="utf-8")
            self.assertIn("from designer_toolkit.templates import c_clip", text)
            self.assertIn("bore_d=12.0", text)
            compile(text, "model.py", "exec")
