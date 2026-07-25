from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import trimesh

import team_preflight


class TeamPreflightTest(unittest.TestCase):
    def write_plan(self, directory: Path) -> Path:
        plan = {
            "schema_version": 4,
            "candidate_predicate_revision": 1,
            "edges": [
                {
                    "id": "E-01",
                    "min_radius_mm": 0.4,
                    "max_radius_mm": 0.8,
                    "samples_required": 3,
                },
                {
                    "id": "E-02",
                    "allowed_sharp": True,
                    "allowed_sharp_reason": "hidden datum edge",
                    "samples_required": 3,
                },
            ],
            "support_rules": [
                {
                    "id": "S-01",
                    "disposition": "SELF_SUPPORT_REQUIRED",
                    "model_to_printer_matrix": [
                        [1, 0, 0, 0],
                        [0, 1, 0, 0],
                        [0, 0, 1, 1],
                        [0, 0, 0, 1],
                    ],
                    "bed_z_mm": 0,
                    "bed_tolerance_mm": 0.001,
                    "downward_normal_z_max": -0.7,
                    "max_out_of_limit_area_mm2": 0.0,
                }
            ],
        }
        path = directory / "print_plan_checks.json"
        path.write_text(json.dumps(plan), encoding="utf-8")
        return path

    def test_box_on_bed_has_zero_out_of_limit_area(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            stl_path = directory / "box.stl"
            trimesh.creation.box(extents=(2, 2, 2)).export(stl_path)
            plan_path = self.write_plan(directory)

            result, _ = team_preflight.support_audit(
                stl_path=stl_path,
                plan_path=plan_path,
                rule_id="S-01",
            )
            self.assertEqual(result["result"], "PASS")
            self.assertAlmostEqual(result["out_of_limit_area_mm2"], 0.0, places=6)

    def test_elevated_plate_fails_support_audit(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            stl_path = directory / "overhang.stl"
            base = trimesh.creation.box(extents=(1, 1, 2))
            plate = trimesh.creation.box(extents=(4, 4, 0.2))
            plate.apply_translation((0, 0, 2))
            trimesh.util.concatenate((base, plate)).export(stl_path)
            plan_path = self.write_plan(directory)

            result, _ = team_preflight.support_audit(
                stl_path=stl_path,
                plan_path=plan_path,
                rule_id="S-01",
            )
            self.assertEqual(result["result"], "FAIL")
            self.assertGreater(result["out_of_limit_area_mm2"], 10.0)

    def test_receipt_validator_rejects_missing_edge(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            stl_path = directory / "box.stl"
            trimesh.creation.box(extents=(2, 2, 2)).export(stl_path)
            plan_path = self.write_plan(directory)
            audit, _ = team_preflight.support_audit(
                stl_path=stl_path,
                plan_path=plan_path,
                rule_id="S-01",
            )
            audit_path = directory / "support_audit.json"
            audit_path.write_text(json.dumps(audit), encoding="utf-8")
            readiness = {
                "schema_version": 4,
                "candidate_stl_sha256": team_preflight.sha256_file(stl_path),
                "print_plan_checks_sha256": team_preflight.sha256_file(plan_path),
                "edges": [
                    {
                        "id": "E-01",
                        "samples_mm": [0.5, 0.5, 0.5],
                        "method": "section fit",
                        "evidence": "edge.png",
                    }
                ],
                "support_rules": [
                    {
                        "id": "S-01",
                        "audit_path": audit_path.name,
                        "forbidden_faces_checked": True,
                    }
                ],
            }
            readiness_path = directory / "candidate_preflight.json"
            readiness_path.write_text(json.dumps(readiness), encoding="utf-8")

            result = team_preflight.validate_receipts(
                stl_path=stl_path,
                plan_path=plan_path,
                readiness_path=readiness_path,
            )
            self.assertEqual(result["result"], "FAIL")
            self.assertTrue(
                any("edge ID set mismatch" in error for error in result["errors"])
            )

    def test_receipt_validator_accepts_complete_rows(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            stl_path = directory / "box.stl"
            trimesh.creation.box(extents=(2, 2, 2)).export(stl_path)
            plan_path = self.write_plan(directory)
            audit, _ = team_preflight.support_audit(
                stl_path=stl_path,
                plan_path=plan_path,
                rule_id="S-01",
            )
            audit_path = directory / "support_audit.json"
            audit_path.write_text(json.dumps(audit), encoding="utf-8")
            readiness = {
                "schema_version": 4,
                "candidate_stl_sha256": team_preflight.sha256_file(stl_path),
                "print_plan_checks_sha256": team_preflight.sha256_file(plan_path),
                "edges": [
                    {
                        "id": "E-01",
                        "samples_mm": [0.5, 0.6, 0.7],
                        "method": "section fit",
                        "evidence": "edge.png",
                    },
                    {
                        "id": "E-02",
                        "samples_mm": [0.0, 0.0, 0.0],
                        "method": "declared sharp",
                        "evidence": "hidden edge",
                    },
                ],
                "support_rules": [
                    {
                        "id": "S-01",
                        "audit_path": audit_path.name,
                        "forbidden_faces_checked": True,
                    }
                ],
            }
            readiness_path = directory / "candidate_preflight.json"
            readiness_path.write_text(json.dumps(readiness), encoding="utf-8")

            result = team_preflight.validate_receipts(
                stl_path=stl_path,
                plan_path=plan_path,
                readiness_path=readiness_path,
            )
            self.assertEqual(result["result"], "PASS", result["errors"])

    def test_support_audit_cli(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            stl_path = directory / "box.stl"
            trimesh.creation.box(extents=(2, 2, 2)).export(stl_path)
            plan_path = self.write_plan(directory)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(Path(team_preflight.__file__)),
                    "support-audit",
                    "--stl",
                    str(stl_path),
                    "--plan",
                    str(plan_path),
                    "--rule-id",
                    "S-01",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(completed.stdout)["result"], "PASS")


def _matrix(rotation: list[list[float]], translation: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> list[list[float]]:
    return [
        [rotation[0][0], rotation[0][1], rotation[0][2], translation[0]],
        [rotation[1][0], rotation[1][1], rotation[1][2], translation[1]],
        [rotation[2][0], rotation[2][1], rotation[2][2], translation[2]],
        [0, 0, 0, 1],
    ]


IDENTITY_MATRIX = _matrix([[1, 0, 0], [0, 1, 0], [0, 0, 1]])
SINGULAR_MATRIX = _matrix([[0, 0, 0], [0, 1, 0], [0, 0, 1]])  # det = 0
REFLECTED_MATRIX = _matrix([[1, 0, 0], [0, 1, 0], [0, 0, -1]])  # det = -1
SCALED_MATRIX = _matrix([[2, 0, 0], [0, 2, 0], [0, 0, 2]])  # det = 8, R @ R.T != I
SHEARED_MATRIX = _matrix([[1, 1, 0], [0, 1, 0], [0, 0, 1]])  # R @ R.T != I


class TeamPreflightAdversarialTest(unittest.TestCase):
    """Bugs A (non-finite radius samples silently PASS) and B (float(None)
    crash on a JSON-null max_out_of_limit_area_mm2), plus the hardening the
    Sprint 1 gate work added: finite/negative validation of every numeric
    threshold, is_finite_rigid transform validation, and evidence-path
    containment for audit_path.
    """

    def write_json(self, directory: Path, name: str, payload: object) -> Path:
        path = directory / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def base_plan(self, **edge_overrides: object) -> dict:
        edge = {
            "id": "E-01",
            "min_radius_mm": 0.4,
            "max_radius_mm": 0.8,
            "samples_required": 3,
        }
        edge.update(edge_overrides)
        return {
            "schema_version": 4,
            "edges": [edge],
            "support_rules": [
                {
                    "id": "S-01",
                    "disposition": "SELF_SUPPORT_REQUIRED",
                    "model_to_printer_matrix": IDENTITY_MATRIX,
                    "bed_z_mm": 0,
                    "bed_tolerance_mm": 0.05,
                    "downward_normal_z_max": -0.7,
                    "max_out_of_limit_area_mm2": 0.0,
                }
            ],
        }

    def base_readiness(self, stl_path: Path, plan_path: Path, **edge_overrides: object) -> dict:
        edge = {
            "id": "E-01",
            "samples_mm": [0.5, 0.6, 0.7],
            "method": "section fit",
            "evidence": "edge.png",
        }
        edge.update(edge_overrides)
        return {
            "schema_version": 4,
            "candidate_stl_sha256": team_preflight.sha256_file(stl_path),
            "print_plan_checks_sha256": team_preflight.sha256_file(plan_path),
            "edges": [edge],
            "support_rules": [],
        }

    def write_box_and_plan(self, directory: Path, **edge_overrides: object) -> tuple[Path, Path]:
        stl_path = directory / "box.stl"
        trimesh.creation.box(extents=(2, 2, 2)).export(stl_path)
        plan_path = self.write_json(directory, "print_plan_checks.json", self.base_plan(**edge_overrides))
        return stl_path, plan_path

    # -- Bug A: non-finite / malformed samples_mm must FAIL, not PASS -------

    def test_validate_receipts_rejects_malformed_samples(self) -> None:
        # Every way a samples_mm list can be unusable, each asserting the error
        # names the edge AND says which rule it broke -- a FAIL alone would also
        # be produced by an unrelated defect, so the substring is the real check.
        cases = (
            ([0.5, float("nan"), 0.6], "finite"),
            ([0.5, float("inf"), 0.6], "finite"),
            ([0.5, float("-inf"), 0.6], "finite"),
            (["oops", 0.5, 0.6], "finite"),
            # bool is an int subclass in Python: True must not pass as 1.0.
            ([0.5, True, 0.6], "finite"),
            ([], "non-empty"),
            ([-0.1, 0.5, 0.6], "non-negative"),
        )
        for samples, expected in cases:
            with self.subTest(samples=samples):
                with tempfile.TemporaryDirectory() as raw:
                    directory = Path(raw)
                    stl_path, plan_path = self.write_box_and_plan(directory)
                    # Empty the plan's support rules BEFORE hashing it into the
                    # readiness receipt, so only the edge under test can fail.
                    plan = json.loads(plan_path.read_text(encoding="utf-8"))
                    plan["support_rules"] = []
                    plan_path.write_text(json.dumps(plan), encoding="utf-8")
                    readiness = self.base_readiness(stl_path, plan_path, samples_mm=samples)
                    readiness_path = self.write_json(
                        directory, "candidate_preflight.json", readiness
                    )

                    result = team_preflight.validate_receipts(
                        stl_path=stl_path, plan_path=plan_path, readiness_path=readiness_path
                    )
                    self.assertEqual(result["result"], "FAIL")
                    self.assertTrue(
                        any("E-01" in e and expected in e for e in result["errors"]),
                        result["errors"],
                    )

    def test_validate_receipts_rejects_max_radius_below_min_radius(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            stl_path, plan_path = self.write_box_and_plan(
                directory, min_radius_mm=0.8, max_radius_mm=0.4
            )
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["support_rules"] = []
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            readiness = self.base_readiness(stl_path, plan_path, samples_mm=[0.5, 0.6, 0.7])
            readiness_path = self.write_json(directory, "candidate_preflight.json", readiness)

            result = team_preflight.validate_receipts(
                stl_path=stl_path, plan_path=plan_path, readiness_path=readiness_path
            )
            self.assertEqual(result["result"], "FAIL")
            self.assertTrue(
                any("E-01" in e and "max_radius_mm" in e for e in result["errors"]), result["errors"]
            )

    # -- Bug B: JSON-null max_out_of_limit_area_mm2 must not crash ----------

    def test_support_audit_rejects_null_max_out_of_limit_area(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            stl_path = directory / "box.stl"
            trimesh.creation.box(extents=(2, 2, 2)).export(stl_path)
            plan = {
                "schema_version": 4,
                "edges": [],
                "support_rules": [
                    {
                        "id": "S-03",
                        "disposition": "SELF_SUPPORT_REQUIRED",
                        "model_to_printer_matrix": IDENTITY_MATRIX,
                        "bed_z_mm": 0,
                        "bed_tolerance_mm": 0.05,
                        "downward_normal_z_max": -0.7,
                        "max_out_of_limit_area_mm2": None,
                    }
                ],
            }
            plan_path = self.write_json(directory, "print_plan_checks.json", plan)

            with self.assertRaises(ValueError) as ctx:
                team_preflight.support_audit(stl_path=stl_path, plan_path=plan_path, rule_id="S-03")
            message = str(ctx.exception)
            self.assertIn("S-03", message)
            self.assertIn("max_out_of_limit_area_mm2", message)

    def test_validate_receipts_null_max_out_of_limit_area_is_clean_fail(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            stl_path = directory / "box.stl"
            trimesh.creation.box(extents=(2, 2, 2)).export(stl_path)
            plan = {
                "schema_version": 4,
                "edges": [],
                "support_rules": [
                    {
                        "id": "S-03",
                        "disposition": "SELF_SUPPORT_REQUIRED",
                        "model_to_printer_matrix": IDENTITY_MATRIX,
                        "bed_z_mm": 0,
                        "bed_tolerance_mm": 0.05,
                        "downward_normal_z_max": -0.7,
                        "max_out_of_limit_area_mm2": None,
                    }
                ],
            }
            plan_path = self.write_json(directory, "print_plan_checks.json", plan)
            # A hand-built audit JSON stands in for one produced against a rule that
            # *does* have a finite cap; only the plan's declared cap is null here.
            audit = {
                "tool": "team_preflight.py",
                "stl_sha256": team_preflight.sha256_file(stl_path),
                "plan_checks_sha256": team_preflight.sha256_file(plan_path),
                "rule_id": "S-03",
                "matrix_sha256": team_preflight.canonical_sha256(IDENTITY_MATRIX),
                "out_of_limit_area_mm2": 0.0,
            }
            audit_path = self.write_json(directory, "S-03-support-audit.json", audit)
            readiness = {
                "schema_version": 4,
                "candidate_stl_sha256": team_preflight.sha256_file(stl_path),
                "print_plan_checks_sha256": team_preflight.sha256_file(plan_path),
                "edges": [],
                "support_rules": [
                    {"id": "S-03", "audit_path": audit_path.name, "forbidden_faces_checked": True}
                ],
            }
            readiness_path = self.write_json(directory, "candidate_preflight.json", readiness)

            # Must not raise (this is exactly the S-03 float(None) crash from bug B).
            result = team_preflight.validate_receipts(
                stl_path=stl_path, plan_path=plan_path, readiness_path=readiness_path
            )
            self.assertEqual(result["result"], "FAIL")
            self.assertTrue(
                any("S-03" in e and "max_out_of_limit_area_mm2" in e for e in result["errors"]),
                result["errors"],
            )

    def test_validate_receipts_accepts_null_max_out_of_limit_area_for_support_allowed(self) -> None:
        # SUPPORT_ALLOWED legitimately leaves max_out_of_limit_area_mm2 JSON-null
        # (bounded by a named footprint instead) -- this must NOT be flagged.
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            stl_path = directory / "box.stl"
            trimesh.creation.box(extents=(2, 2, 2)).export(stl_path)
            plan = {
                "schema_version": 4,
                "edges": [],
                "support_rules": [
                    {
                        "id": "S-03",
                        "disposition": "SUPPORT_ALLOWED",
                        "allowed_contact_class": "nonfunctional-window-roof",
                        "model_to_printer_matrix": IDENTITY_MATRIX,
                        "bed_z_mm": 0,
                        "bed_tolerance_mm": 0.05,
                        "downward_normal_z_max": -0.7,
                        "max_out_of_limit_area_mm2": None,
                    }
                ],
            }
            plan_path = self.write_json(directory, "print_plan_checks.json", plan)
            audit = {
                "tool": "team_preflight.py",
                "stl_sha256": team_preflight.sha256_file(stl_path),
                "plan_checks_sha256": team_preflight.sha256_file(plan_path),
                "rule_id": "S-03",
                "matrix_sha256": team_preflight.canonical_sha256(IDENTITY_MATRIX),
                "out_of_limit_area_mm2": 12.3,
            }
            audit_path = self.write_json(directory, "S-03-support-audit.json", audit)
            readiness = {
                "schema_version": 4,
                "candidate_stl_sha256": team_preflight.sha256_file(stl_path),
                "print_plan_checks_sha256": team_preflight.sha256_file(plan_path),
                "edges": [],
                "support_rules": [
                    {"id": "S-03", "audit_path": audit_path.name, "forbidden_faces_checked": True}
                ],
            }
            readiness_path = self.write_json(directory, "candidate_preflight.json", readiness)

            result = team_preflight.validate_receipts(
                stl_path=stl_path, plan_path=plan_path, readiness_path=readiness_path
            )
            self.assertEqual(result["result"], "PASS", result["errors"])

    # -- Transform rigidity ---------------------------------------------------

    def test_is_finite_rigid_accepts_identity(self) -> None:
        self.assertTrue(team_preflight.is_finite_rigid(IDENTITY_MATRIX))

    def test_is_finite_rigid_rejects_non_rigid_and_malformed(self) -> None:
        # Anything that is not a finite rotation+translation: a rigid transform
        # is what makes the printer-frame normals comparable to the model's.
        for label, bad in (
            ("singular", SINGULAR_MATRIX),
            ("reflection", REFLECTED_MATRIX),
            ("scale", SCALED_MATRIX),
            ("shear", SHEARED_MATRIX),
            ("nan entry", _matrix([[1, 0, 0], [0, 1, 0], [0, 0, 1]], (float("nan"), 0, 0))),
            ("none", None),
            ("string", "not a matrix"),
            ("wrong shape", [[1, 0], [0, 1]]),
        ):
            with self.subTest(matrix=label):
                self.assertFalse(team_preflight.is_finite_rigid(bad))

    def test_support_audit_rejects_singular_transform(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            stl_path = directory / "box.stl"
            trimesh.creation.box(extents=(2, 2, 2)).export(stl_path)
            plan = {
                "schema_version": 4,
                "edges": [],
                "support_rules": [
                    {
                        "id": "S-01",
                        "disposition": "SELF_SUPPORT_REQUIRED",
                        "model_to_printer_matrix": SINGULAR_MATRIX,
                        "bed_z_mm": 0,
                        "bed_tolerance_mm": 0.05,
                        "downward_normal_z_max": -0.7,
                        "max_out_of_limit_area_mm2": 0.0,
                    }
                ],
            }
            plan_path = self.write_json(directory, "print_plan_checks.json", plan)

            with self.assertRaises(ValueError) as ctx:
                team_preflight.support_audit(stl_path=stl_path, plan_path=plan_path, rule_id="S-01")
            message = str(ctx.exception)
            self.assertIn("S-01", message)
            self.assertIn("model_to_printer_matrix", message)

    def test_support_audit_rejects_non_rigid_transform(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            stl_path = directory / "box.stl"
            trimesh.creation.box(extents=(2, 2, 2)).export(stl_path)
            for label, matrix in (
                ("reflected", REFLECTED_MATRIX),
                ("scaled", SCALED_MATRIX),
                ("sheared", SHEARED_MATRIX),
            ):
                plan = {
                    "schema_version": 4,
                    "edges": [],
                    "support_rules": [
                        {
                            "id": "S-01",
                            "disposition": "SELF_SUPPORT_REQUIRED",
                            "model_to_printer_matrix": matrix,
                            "bed_z_mm": 0,
                            "bed_tolerance_mm": 0.05,
                            "downward_normal_z_max": -0.7,
                            "max_out_of_limit_area_mm2": 0.0,
                        }
                    ],
                }
                plan_path = self.write_json(directory, f"plan-{label}.json", plan)
                with self.assertRaises(ValueError, msg=label) as ctx:
                    team_preflight.support_audit(
                        stl_path=stl_path, plan_path=plan_path, rule_id="S-01"
                    )
                self.assertIn("model_to_printer_matrix", str(ctx.exception), label)

    def test_validate_receipts_rejects_non_rigid_transform_in_plan(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            stl_path = directory / "box.stl"
            trimesh.creation.box(extents=(2, 2, 2)).export(stl_path)
            plan = {
                "schema_version": 4,
                "edges": [],
                "support_rules": [
                    {
                        "id": "S-01",
                        "disposition": "SELF_SUPPORT_REQUIRED",
                        "model_to_printer_matrix": REFLECTED_MATRIX,
                        "bed_z_mm": 0,
                        "bed_tolerance_mm": 0.05,
                        "downward_normal_z_max": -0.7,
                        "max_out_of_limit_area_mm2": 0.0,
                    }
                ],
            }
            plan_path = self.write_json(directory, "print_plan_checks.json", plan)
            audit = {
                "tool": "team_preflight.py",
                "stl_sha256": team_preflight.sha256_file(stl_path),
                "plan_checks_sha256": team_preflight.sha256_file(plan_path),
                "rule_id": "S-01",
                "matrix_sha256": team_preflight.canonical_sha256(REFLECTED_MATRIX),
                "out_of_limit_area_mm2": 0.0,
            }
            audit_path = self.write_json(directory, "S-01-support-audit.json", audit)
            readiness = {
                "schema_version": 4,
                "candidate_stl_sha256": team_preflight.sha256_file(stl_path),
                "print_plan_checks_sha256": team_preflight.sha256_file(plan_path),
                "edges": [],
                "support_rules": [
                    {"id": "S-01", "audit_path": audit_path.name, "forbidden_faces_checked": True}
                ],
            }
            readiness_path = self.write_json(directory, "candidate_preflight.json", readiness)

            result = team_preflight.validate_receipts(
                stl_path=stl_path, plan_path=plan_path, readiness_path=readiness_path
            )
            self.assertEqual(result["result"], "FAIL")
            self.assertTrue(
                any("S-01" in e and "model_to_printer_matrix" in e for e in result["errors"]),
                result["errors"],
            )

    # -- Evidence-path containment --------------------------------------------

    def _readiness_with_audit_path(self, directory: Path, stl_path: Path, plan_path: Path, audit_value: str) -> Path:
        readiness = {
            "schema_version": 4,
            "candidate_stl_sha256": team_preflight.sha256_file(stl_path),
            "print_plan_checks_sha256": team_preflight.sha256_file(plan_path),
            "edges": [],
            "support_rules": [
                {"id": "S-01", "audit_path": audit_value, "forbidden_faces_checked": True}
            ],
        }
        return self.write_json(directory, "candidate_preflight.json", readiness)

    def test_validate_receipts_rejects_path_traversal_audit_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            (directory / "project").mkdir()
            plan = self.base_plan()
            plan["edges"] = []
            stl_path = directory / "project" / "box.stl"
            trimesh.creation.box(extents=(2, 2, 2)).export(stl_path)
            plan_path = self.write_json(directory / "project", "print_plan_checks.json", plan)
            # A secret file that lives just outside the project's evidence root.
            self.write_json(directory, "secret.json", {"tool": "not-team-preflight"})
            readiness_path = self._readiness_with_audit_path(
                directory / "project", stl_path, plan_path, "../secret.json"
            )

            result = team_preflight.validate_receipts(
                stl_path=stl_path, plan_path=plan_path, readiness_path=readiness_path
            )
            self.assertEqual(result["result"], "FAIL")
            self.assertTrue(
                any("S-01" in e and "audit_path" in e and "escapes" in e for e in result["errors"]),
                result["errors"],
            )

    def test_validate_receipts_rejects_absolute_audit_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            plan = self.base_plan()
            plan["edges"] = []
            stl_path, plan_path = self.write_box_and_plan(directory)
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["edges"] = []
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            absolute_evil = str((directory / "elsewhere.json").resolve())
            readiness_path = self._readiness_with_audit_path(directory, stl_path, plan_path, absolute_evil)

            result = team_preflight.validate_receipts(
                stl_path=stl_path, plan_path=plan_path, readiness_path=readiness_path
            )
            self.assertEqual(result["result"], "FAIL")
            self.assertTrue(
                any("S-01" in e and "audit_path" in e and "absolute" in e for e in result["errors"]),
                result["errors"],
            )

    def test_validate_receipts_rejects_missing_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            stl_path, plan_path = self.write_box_and_plan(directory)
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["edges"] = []
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            readiness_path = self._readiness_with_audit_path(
                directory, stl_path, plan_path, "does-not-exist.json"
            )

            result = team_preflight.validate_receipts(
                stl_path=stl_path, plan_path=plan_path, readiness_path=readiness_path
            )
            self.assertEqual(result["result"], "FAIL")
            self.assertTrue(
                any("S-01" in e and "missing audit file" in e for e in result["errors"]),
                result["errors"],
            )

    # -- Contract/version/hash/ID hardening (pre-existing behavior, now covered) -

    def test_validate_receipts_rejects_unsupported_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            stl_path, plan_path = self.write_box_and_plan(directory)
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["schema_version"] = 3
            plan["edges"] = []
            plan["support_rules"] = []
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            readiness = {
                "schema_version": 4,
                "candidate_stl_sha256": team_preflight.sha256_file(stl_path),
                "print_plan_checks_sha256": team_preflight.sha256_file(plan_path),
                "edges": [],
                "support_rules": [],
            }
            readiness_path = self.write_json(directory, "candidate_preflight.json", readiness)

            result = team_preflight.validate_receipts(
                stl_path=stl_path, plan_path=plan_path, readiness_path=readiness_path
            )
            self.assertEqual(result["result"], "FAIL")
            self.assertTrue(
                any("schema_version" in e for e in result["errors"]), result["errors"]
            )

    def test_validate_receipts_accepts_contract_version_as_an_alias(self) -> None:
        """One JSON file must be able to serve both gates.

        print_plan_checks.json (this tool) and print_plan.json (team_tools)
        carry field-for-field identical edges and support_rules and differed
        only in the name of the version key -- two hand-maintained copies whose
        agreement nothing checked, which is the exact failure the contract
        exists to prevent.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            stl_path, plan_path = self.write_box_and_plan(directory)
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan.pop("schema_version")
            plan["contract_version"] = 4  # what team_tools' copy calls it
            plan["edges"] = []
            plan["support_rules"] = []
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            readiness_path = self.write_json(
                directory,
                "candidate_preflight.json",
                {
                    "schema_version": 4,
                    "candidate_stl_sha256": team_preflight.sha256_file(stl_path),
                    "print_plan_checks_sha256": team_preflight.sha256_file(plan_path),
                    "edges": [],
                    "support_rules": [],
                },
            )

            result = team_preflight.validate_receipts(
                stl_path=stl_path, plan_path=plan_path, readiness_path=readiness_path
            )

            self.assertEqual(result["result"], "PASS", result["errors"])
            self.assertFalse([e for e in result["errors"] if "schema_version" in e], result["errors"])

    def test_validate_receipts_rejects_stale_stl_hash(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            stl_path, plan_path = self.write_box_and_plan(directory)
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["edges"] = []
            plan["support_rules"] = []
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            readiness = {
                "schema_version": 4,
                "candidate_stl_sha256": "0" * 64,  # stale/wrong hash
                "print_plan_checks_sha256": team_preflight.sha256_file(plan_path),
                "edges": [],
                "support_rules": [],
            }
            readiness_path = self.write_json(directory, "candidate_preflight.json", readiness)

            result = team_preflight.validate_receipts(
                stl_path=stl_path, plan_path=plan_path, readiness_path=readiness_path
            )
            self.assertEqual(result["result"], "FAIL")
            self.assertTrue(
                any("candidate_stl_sha256" in e for e in result["errors"]), result["errors"]
            )

    def test_validate_receipts_rejects_duplicate_edge_ids(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            stl_path, plan_path = self.write_box_and_plan(directory)
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["edges"] = [
                {"id": "E-01", "min_radius_mm": 0.4, "max_radius_mm": 0.8, "samples_required": 3},
                {"id": "E-01", "min_radius_mm": 0.2, "max_radius_mm": 0.6, "samples_required": 3},
            ]
            plan["support_rules"] = []
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            readiness = {
                "schema_version": 4,
                "candidate_stl_sha256": team_preflight.sha256_file(stl_path),
                "print_plan_checks_sha256": team_preflight.sha256_file(plan_path),
                "edges": [],
                "support_rules": [],
            }
            readiness_path = self.write_json(directory, "candidate_preflight.json", readiness)

            with self.assertRaises(ValueError) as ctx:
                team_preflight.validate_receipts(
                    stl_path=stl_path, plan_path=plan_path, readiness_path=readiness_path
                )
            self.assertIn("duplicate id E-01", str(ctx.exception))

    def test_validate_receipts_rejects_duplicate_support_rule_ids(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            stl_path, plan_path = self.write_box_and_plan(directory)
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["edges"] = []
            plan["support_rules"] = [
                {"id": "S-01", "disposition": "SELF_SUPPORT_REQUIRED"},
                {"id": "S-01", "disposition": "SELF_SUPPORT_REQUIRED"},
            ]
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            readiness = {
                "schema_version": 4,
                "candidate_stl_sha256": team_preflight.sha256_file(stl_path),
                "print_plan_checks_sha256": team_preflight.sha256_file(plan_path),
                "edges": [],
                "support_rules": [],
            }
            readiness_path = self.write_json(directory, "candidate_preflight.json", readiness)

            with self.assertRaises(ValueError) as ctx:
                team_preflight.validate_receipts(
                    stl_path=stl_path, plan_path=plan_path, readiness_path=readiness_path
                )
            self.assertIn("duplicate id S-01", str(ctx.exception))


class InterfacesValidationTest(unittest.TestCase):
    """H-03: fit strategy moved from the metrologist to the print engineer and is now
    machine-enforced via the optional `print_plan_checks.json` `"interfaces"` array. These
    tests cover backward-compat (absent key), the happy path for a structurally-different
    clearance fit and an interference fit, and one adversarial case per required field.
    """

    def clearance_interface(self, **overrides: object) -> dict:
        # A rigid sliding/seated clearance fit -- e.g. a Pixel-case wall or a seated dock.
        interface = {
            "id": "I-CLR-01",
            "fit_type": "clearance",
            "contact_state": "sliding, user-operated insertion",
            "min_mm": 0.15,
            "max_mm": 0.30,
            "motion_path": "insert along -Z, 12 mm travel to seated stop",
            "material": "PETG on PETG",
            "coupon_required": True,
            "acceptance_method": "gauge-pin pass/fail per lane",
        }
        interface.update(overrides)
        return interface

    def interference_interface(self, **overrides: object) -> dict:
        # An interference/grip/retention fit -- e.g. the broom-holder 30 mm grip fins.
        interface = {
            "id": "I-GRIP-01",
            "fit_type": "retention",
            "contact_state": "elastic grip, deflect-to-insert",
            "min_mm": -0.30,
            "max_mm": -0.10,
            "motion_path": "snap over 30 mm handle, radial deflection",
            "material": "PETG fin on painted-steel handle",
            "coupon_required": True,
            "acceptance_method": "hold a 2 kg static load for 60 s without slip",
        }
        interface.update(overrides)
        return interface

    def test_absent_interfaces_passes_backward_compatibly(self) -> None:
        result = team_preflight.validate_interfaces({"schema_version": 4})
        self.assertEqual(result["result"], "PASS")
        self.assertEqual(result["interface_ids"], [])
        self.assertEqual(result["errors"], [])

    def test_null_interfaces_passes_backward_compatibly(self) -> None:
        result = team_preflight.validate_interfaces({"schema_version": 4, "interfaces": None})
        self.assertEqual(result["result"], "PASS")
        self.assertEqual(result["errors"], [])

    def test_clearance_interface_passes(self) -> None:
        plan = {"interfaces": [self.clearance_interface()]}
        result = team_preflight.validate_interfaces(plan)
        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["interface_ids"], ["I-CLR-01"])

    def test_interference_interface_passes(self) -> None:
        plan = {"interfaces": [self.interference_interface()]}
        result = team_preflight.validate_interfaces(plan)
        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(result["interface_ids"], ["I-GRIP-01"])

    def test_both_fit_types_together_pass(self) -> None:
        plan = {"interfaces": [self.clearance_interface(), self.interference_interface()]}
        result = team_preflight.validate_interfaces(plan)
        self.assertEqual(result["result"], "PASS", result["errors"])
        self.assertEqual(sorted(result["interface_ids"]), ["I-CLR-01", "I-GRIP-01"])

    def test_interfaces_not_a_list_fails(self) -> None:
        result = team_preflight.validate_interfaces({"interfaces": {"id": "I-01"}})
        self.assertEqual(result["result"], "FAIL")
        self.assertTrue(any("interfaces" in e and "list" in e for e in result["errors"]))

    def test_missing_required_field_fails(self) -> None:
        interface = self.clearance_interface()
        del interface["material"]
        result = team_preflight.validate_interfaces({"interfaces": [interface]})
        self.assertEqual(result["result"], "FAIL")
        self.assertTrue(
            any("I-CLR-01" in e and "material" in e for e in result["errors"]), result["errors"]
        )

    def test_bad_fit_type_enum_fails(self) -> None:
        interface = self.clearance_interface(fit_type="press_fit_but_not_a_real_enum_value")
        result = team_preflight.validate_interfaces({"interfaces": [interface]})
        self.assertEqual(result["result"], "FAIL")
        self.assertTrue(
            any("I-CLR-01" in e and "fit_type" in e for e in result["errors"]), result["errors"]
        )

    def test_non_finite_range_fails(self) -> None:
        for bad in (float("nan"), float("inf"), float("-inf"), None, True, "0.2"):
            with self.subTest(bad=bad):
                interface = self.clearance_interface(min_mm=bad)
                result = team_preflight.validate_interfaces({"interfaces": [interface]})
                self.assertEqual(result["result"], "FAIL")
                self.assertTrue(
                    any("I-CLR-01" in e and "min_mm" in e for e in result["errors"]),
                    result["errors"],
                )

    def test_max_below_min_fails(self) -> None:
        interface = self.clearance_interface(min_mm=0.30, max_mm=0.15)
        result = team_preflight.validate_interfaces({"interfaces": [interface]})
        self.assertEqual(result["result"], "FAIL")
        self.assertTrue(
            any("I-CLR-01" in e and "max_mm" in e for e in result["errors"]), result["errors"]
        )

    def test_negative_clearance_range_fails(self) -> None:
        interface = self.clearance_interface(min_mm=-0.10, max_mm=0.10)
        result = team_preflight.validate_interfaces({"interfaces": [interface]})
        self.assertEqual(result["result"], "FAIL")
        self.assertTrue(
            any("I-CLR-01" in e and "clearance" in e for e in result["errors"]), result["errors"]
        )

    def test_negative_interference_range_passes(self) -> None:
        # The whole point of "no universal zero-interference rule": a non-clearance fit type
        # may be fully negative (intersecting) on both sides.
        interface = self.interference_interface(min_mm=-0.30, max_mm=-0.10)
        result = team_preflight.validate_interfaces({"interfaces": [interface]})
        self.assertEqual(result["result"], "PASS", result["errors"])

    def test_duplicate_interface_id_fails(self) -> None:
        plan = {
            "interfaces": [
                self.clearance_interface(),
                self.clearance_interface(min_mm=0.1, max_mm=0.2),
            ]
        }
        result = team_preflight.validate_interfaces(plan)
        self.assertEqual(result["result"], "FAIL")
        self.assertTrue(
            any("I-CLR-01" in e and "duplicate" in e for e in result["errors"]), result["errors"]
        )

    def test_coupon_required_not_bool_fails(self) -> None:
        interface = self.clearance_interface(coupon_required="yes")
        result = team_preflight.validate_interfaces({"interfaces": [interface]})
        self.assertEqual(result["result"], "FAIL")
        self.assertTrue(
            any("I-CLR-01" in e and "coupon_required" in e for e in result["errors"]),
            result["errors"],
        )

    def test_validate_interfaces_cli(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            plan = {
                "schema_version": 4,
                "interfaces": [self.clearance_interface(), self.interference_interface()],
            }
            plan_path = directory / "print_plan_checks.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(Path(team_preflight.__file__)),
                    "validate-interfaces",
                    "--plan",
                    str(plan_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["result"], "PASS")
            self.assertEqual(sorted(payload["interface_ids"]), ["I-CLR-01", "I-GRIP-01"])

    def test_validate_interfaces_cli_fails_on_bad_enum(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            plan = {
                "schema_version": 4,
                "interfaces": [self.clearance_interface(fit_type="not-a-fit-type")],
            }
            plan_path = directory / "print_plan_checks.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(Path(team_preflight.__file__)),
                    "validate-interfaces",
                    "--plan",
                    str(plan_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 1, completed.stderr)
            self.assertEqual(json.loads(completed.stdout)["result"], "FAIL")


if __name__ == "__main__":
    unittest.main()
