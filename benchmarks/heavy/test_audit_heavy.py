#!/usr/bin/env python3
"""L0-heavy — the half of
`skills/3d-modeling/scripts/designer_toolkit/test_audit.py`
that costs a child interpreter.

The repository-root `conftest.py` refuses a child interpreter inside the commit
gate, and these classes start one. Same tests, moved rather than weakened;
`benchmarks/heavy/README.md` records the profile that decided the seam and what
runs this tier. What stayed behind is what answers in the parent process.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

# The fixtures this half shares with the half that stayed behind,
# imported rather than copied: two spellings of one fixture is how
# two tiers stop testing the same thing.
from designer_toolkit.test_audit import (  # noqa: E402
    _CLIP,
    _audit,
    _built_project,
    _by_id,
    _dt,
    trimesh,
)


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

    def test_a_receipt_claiming_the_wrong_verdict_is_caught(self) -> None:
        """`recompute` is the whole disagreement path, and nothing asserted it
        could fail. Its comparison rules have been changed twice -- once to
        excuse checks a verifying run structurally cannot have, once to stop the
        render row counting as a difference -- and either edit could have made it
        agree with everything. Here the bytes are untouched and the designer's
        own receipt is altered, which is the one thing re-measuring exists to
        notice."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project = _built_project(root)
            receipt = project / "commission.json"
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            flipped = next(c for c in payload["checks"] if c["id"] == "solid")
            flipped["result"] = "FAIL"
            receipt.write_text(json.dumps(payload, indent=2), encoding="utf-8")

            done, audit = _audit(project, root / "verify")

            self.assertEqual(1, done.returncode)
            recompute = next(c for c in audit["checks"] if c["id"] == "recompute")
            self.assertEqual("FAIL", recompute.get("result"), recompute)
            self.assertIn("solid", recompute["detail"])

    def test_a_check_the_designer_never_ran_is_caught(self) -> None:
        """The other direction: a receipt quieter than the recomputation."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project = _built_project(root)
            receipt = project / "commission.json"
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            payload["checks"] = [c for c in payload["checks"] if c["id"] != "envelope"]
            receipt.write_text(json.dumps(payload, indent=2), encoding="utf-8")

            _done, audit = _audit(project, root / "verify")

            recompute = next(c for c in audit["checks"] if c["id"] == "recompute")
            self.assertEqual("FAIL", recompute["result"])
            self.assertIn("envelope", recompute["detail"])

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

    def test_it_never_demands_the_report_it_is_the_input_to(self) -> None:
        """`audit` produces the numbers a verification_report is written from, so
        at audit time that report cannot exist. Requiring it made the first audit
        of every job fail with REQUIRED_CONTRACT_MISSING -- which reads exactly
        like a real defect, and was documented as the normal first pass."""
        from designer_toolkit.audit import _required_contracts

        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw)
            for profile in ("DIRECT", "FULL"):
                with self.subTest(profile=profile):
                    (project / "job_state.md").write_text(
                        "\n".join(["---", f"profile: {profile}", "---", ""]),
                        encoding="utf-8")
                    required = _required_contracts(project)
                    self.assertNotIn("verification_report", required)
                    self.assertIn("candidate_readiness", required)

    def test_a_clean_project_audits_at_exit_zero_first_time(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            done, _payload = _audit(_built_project(root), root / "verify")
            self.assertEqual(0, done.returncode, done.stderr[-600:])

    def test_audit_resolves_plan_relative_assembly_from_project_not_verify_output(self) -> None:
        """A copied plan used for recomputation must retain the project's path base."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project = _built_project(root)
            plan_path = project / "print_plan_checks.json"
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            clear = trimesh.creation.box(extents=(10, 10, 10))
            clear.apply_translation((100, 100, 5))
            clear.export(project / "clear.stl")
            plan["assembly_mesh_paths"] = ["clear.stl"]
            plan["assembly_overlap_budget_mm3"] = 0.0
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            recommission = _dt(
                "commission", "--model", "model.py", "--plan", "print_plan_checks.json",
                "--out", ".", "--job-id", "a", "--updated-utc",
                "1970-01-01T00:00:00Z", "--no-render", cwd=project)
            self.assertEqual(0, recommission.returncode, recommission.stderr[-600:])

            done, payload = _audit(project, root / "verify")

            self.assertEqual(0, done.returncode, done.stderr[-600:])
            self.assertEqual("PASS", _by_id(payload)["recompute"])

    def test_audit_rejects_traversing_reference_before_recompute(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project = _built_project(root)

            done, payload = _audit(project, root / "verify", reference="../outside.stl")

            self.assertEqual(2, done.returncode)
            self.assertIsNone(payload)
            self.assertIn("reference path is unsafe", done.stderr)

    def test_audit_rejects_symlinked_reference_before_recompute(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project = _built_project(root)
            outside = root / "outside-reference.stl"
            outside.write_bytes((project / "candidate-01.stl").read_bytes())
            linked = project / "linked-reference.stl"
            try:
                linked.symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is not permitted in this environment")

            done, payload = _audit(project, root / "verify", reference=linked.name)

            self.assertEqual(2, done.returncode)
            self.assertIsNone(payload)
            self.assertIn("reference path is unsafe", done.stderr)

    def test_audit_rejects_unsafe_manifest_candidate_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project = _built_project(root)
            manifest_path = project / "artifact_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            candidate = next(row for row in manifest["artifacts"]
                             if row["id"] == manifest["candidate_id"])
            candidate["path"] = "../candidate-01.stl"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            done, payload = _audit(project, root / "verify")

            self.assertEqual(2, done.returncode)
            self.assertIsNone(payload)
            self.assertIn("unsafe or unresolved", done.stderr)

    def test_audit_reference_is_project_relative_in_production(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project = _built_project(root)
            reference = project / "reference.stl"
            reference.write_bytes((project / "candidate-01.stl").read_bytes())
            plan_path = project / "print_plan_checks.json"
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["interfaces"] = [{
                "id": "I-01", "fit_type": "interference",
                "min_mm": -100.0, "max_mm": 100.0, "units": "mm",
                "contact_state": "seated", "uncertainty_mm": 0.01,
                "acceptance_method": "commission", "motion_path": "seated",
                "material": "PLA", "coupon_required": False,
            }]
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            recommission = _dt(
                "commission", "--model", "model.py", "--plan", "print_plan_checks.json",
                "--reference", "reference.stl", "--out", ".", "--job-id", "a",
                "--updated-utc", "1970-01-01T00:00:00Z", "--no-render", cwd=project)
            self.assertEqual(0, recommission.returncode, recommission.stderr[-600:])

            done, payload = _audit(project, root / "verify", reference="reference.stl")

            self.assertEqual(0, done.returncode, done.stderr[-600:])
            self.assertEqual("PASS", _by_id(payload)["recompute"])

    def test_audit_missing_safe_reference_fails_fit_measurement(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project = _built_project(root)
            reference = project / "reference.stl"
            reference.write_bytes((project / "candidate-01.stl").read_bytes())
            plan_path = project / "print_plan_checks.json"
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["interfaces"] = [{
                "id": "I-01", "fit_type": "interference",
                "min_mm": -100.0, "max_mm": 100.0, "units": "mm",
                "contact_state": "seated", "uncertainty_mm": 0.01,
                "acceptance_method": "commission", "motion_path": "seated",
                "material": "PLA", "coupon_required": False,
            }]
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            recommission = _dt(
                "commission", "--model", "model.py", "--plan", "print_plan_checks.json",
                "--reference", "reference.stl", "--out", ".", "--job-id", "a",
                "--updated-utc", "1970-01-01T00:00:00Z", "--no-render", cwd=project)
            self.assertEqual(0, recommission.returncode, recommission.stderr[-600:])

            done, payload = _audit(
                project, root / "verify", reference="missing-reference.stl")

            self.assertEqual(1, done.returncode, done.stderr[-600:])
            fit = json.loads(
                (root / "verify" / "commission.json").read_text(encoding="utf-8"))
            fit_check = next(check for check in fit["checks"] if check["id"] == "fit-I-01")
            self.assertEqual("FAIL", fit_check["result"])
            self.assertIn("cannot read", fit_check["detail"])
            self.assertEqual("FAIL", _by_id(payload)["recompute"])

    def test_audit_rejects_symlinked_manifest_candidate_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project = _built_project(root)
            outside = root / "outside.stl"
            outside.write_bytes((project / "candidate-01.stl").read_bytes())
            linked = project / "linked-candidate.stl"
            try:
                linked.symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is not permitted in this environment")
            manifest_path = project / "artifact_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            candidate = next(row for row in manifest["artifacts"]
                             if row["id"] == manifest["candidate_id"])
            candidate["path"] = linked.name
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            done, payload = _audit(project, root / "verify")

            self.assertEqual(2, done.returncode)
            self.assertIsNone(payload)
            self.assertIn("unsafe or unresolved", done.stderr)

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
