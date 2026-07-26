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
