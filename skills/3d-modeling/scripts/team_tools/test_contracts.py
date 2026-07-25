"""Tests for team_tools.contracts.

Runnable as:
    python -m team_tools.test_contracts     (from skills/3d-modeling/scripts/)
    python team_tools/test_contracts.py      (from skills/3d-modeling/scripts/)

For every validator: a normal-pass fixture, a malformed-input fixture, an
adversarial numeric (NaN/Inf) fixture, a stale-dependency fixture where
relevant, and a second structurally-different fixture. Non-finite numbers,
paths, duplicate IDs, enums, and hashes/mutation are covered with hand-rolled
property-based loops that walk every applicable field rather than one
hardcoded case. Every assertion below checks that the failure message names
the exact contract field/id/rule, not just that *something* failed.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import trimesh

_PACKAGE_DIR = str(Path(__file__).resolve().parent)
if _PACKAGE_DIR not in sys.path:
    sys.path.insert(0, _PACKAGE_DIR)

import common as C  # noqa: E402  (import after sys.path bootstrap above)
import manifest_checks as MC  # noqa: E402
import receipts as R  # noqa: E402
import render as RD  # noqa: E402
import status as S  # noqa: E402
import summary as SUM  # noqa: E402
import validators as V  # noqa: E402

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64


# ---------------------------------------------------------------------------
# Minimal valid fixtures (deep-copied per use so tests can mutate freely)
# ---------------------------------------------------------------------------

_JOB_STATE = {
    "contract": "job-state",
    "contract_version": 4,
    "job_id": "unit-test-job",
    "revision": 1,
    "owner": "orchestrator",
    "mode": "PIPELINE",
    "profile": "COMPACT",
    "state": "CANDIDATE_BUILD",
    "backend": "cadquery",
    "active_candidate": "none",
    "updated_utc": "2026-01-01T00:00:00Z",
    "route": "unit test route",
    "bound_inputs": [{"id": "BI-01", "label": "brief", "reference": f"SHA-256 {HASH_A}", "status": "bound"}],
    "gates": [{"id": "M1", "required_receipt": "dimensions", "result": "PASS", "evidence": "dimensions.json"}],
    "dispatches": [
        {
            "id": "D1",
            "role": "metrologist",
            "authorized_inputs": "brief",
            "required_output": "dimensions.md",
            "budget_min": 3,
            "status": "complete",
        }
    ],
    "open_questions": [],
}

_DIMENSIONS = {
    "contract": "dimensions",
    "contract_version": 4,
    "job_id": "unit-test-job",
    "revision": 1,
    "owner": "metrologist",
    "status": "ACCEPTED",
    "updated_utc": "2026-01-01T00:00:00Z",
    "frame": [{"id": "D0", "definition": "cap face Z=0", "source": "schematic", "confidence": "B"}],
    "sources": [
        {
            "id": "S1",
            "evidence_path": "evidence/brief.md",
            "variant": "brief",
            "sha256": HASH_A,
            "authority": "declares dimensions",
        }
    ],
    "features": [
        {
            "id": "F01",
            "name": "cross-bar",
            "datum_value": "62.0 x 11.7 x 24.0",
            "source": "S1",
            "confidence": "B",
            "candidate_response": "open channel",
            "ready": True,
        }
    ],
    "dimensions": [
        {
            "id": "M01",
            "feature_id": "F01",
            "value": "62.0 mm",
            "datum_method": "D0/X",
            "source": "S1",
            "confidence": "B",
            "tolerance_response": "clearance >= 0.5 mm",
        }
    ],
    "open_questions": [],
    "reference_round_trip": [
        {"id": "RT-01", "views_overlay": "aligned", "verdict": "ACCEPTED", "sheet_revision_required": False}
    ],
}

_MATRIX = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]

_PRINT_PLAN = {
    "contract": "print-plan",
    "contract_version": 4,
    "job_id": "unit-test-job",
    "revision": 1,
    "owner": "print-engineer",
    "status": "ACCEPTED",
    "dimensions_revision": 1,
    "reference_sha256": HASH_B,
    "updated_utc": "2026-01-01T00:00:00Z",
    "process": [
        {
            "printer_material_nozzle": "X2D; PETG; 0.4mm",
            "layer_mm": 0.2,
            "environment_load": "hand tool",
            "rationale": "PETG required",
        }
    ],
    "transform": {
        "coordinate_convention": "installed frame in mm",
        "bed_contact_landmark": "P_BED",
        "bed_normal": "+Y",
        "open_direction": "-Z",
        "forbidden_downward_faces": ["F01"],
        "matrix": _MATRIX,
    },
    "geometry_rules": [
        {
            "id": "G-01",
            "rule": "wall thickness",
            "numeric_limit_mm": 1.2,
            "verification_predicate": "thickness samples >= 1.2mm",
            "required_now": "candidate readiness",
            "deferred_owner": "none",
            "final_gate": "none",
            "related_feature_ids": ["F01"],
        }
    ],
    "edges": [
        {
            "id": "E-01",
            "min_radius_mm": 0.8,
            "max_radius_mm": None,
            "samples_required": 3,
            "exposure_class": "EXPOSED_FUNCTIONAL",
            "related_feature_ids": ["F01"],
        }
    ],
    "support_rules": [
        {
            "id": "S-01",
            "disposition": "SELF_SUPPORT_REQUIRED",
            "model_to_printer_matrix": _MATRIX,
            "bed_z_mm": 0.0,
            "bed_tolerance_mm": 0.05,
            "downward_normal_z_max": -0.7071,
            "max_out_of_limit_area_mm2": 0.0,
            "related_feature_ids": ["F01"],
        }
    ],
    "coupon": {"interfaces_represented": "F01", "clearance_lanes": "one lane", "material": "PETG", "pass_fail_measurements": "hand fit"},
    "final_prep_notes": "P2 after PASS verifier report.",
}

_VERIFICATION_REPORT = {
    "contract": "verification-report",
    "contract_version": 4,
    "job_id": "unit-test-job",
    "revision": 1,
    "owner": "verifier",
    "status": "PASS",
    "candidate_id": "candidate-01",
    "candidate_stl_sha256": HASH_C,
    "dimensions_revision": 1,
    "print_plan_revision": 1,
    "reference_sha256": HASH_B,
    "fresh_context": True,
    "updated_utc": "2026-01-01T00:00:00Z",
    "checks": [
        {"id": str(n), "method": "re-imported STL", "result": "PASS", "numeric_result": None, "visual_observation": "ok", "evidence": "e.png"}
        for n in range(1, 8)
    ],
    "defects": [],
    "verdict": "PASS",
}

_ARTIFACT_MANIFEST = {
    "contract": "artifact-manifest",
    "contract_version": 1,
    "job_id": "unit-test-job",
    "candidate_id": "candidate-01",
    "units": "mm",
    "updated_utc": "2026-01-01T00:00:00Z",
    "artifacts": [
        {
            "id": "reference-bar",
            "role": "reference",
            "path": "reference_bar.stl",
            "type": "stl",
            "sha256": HASH_B,
            "expected_components": 1,
            "bbox": {"min": [-31.0, -5.85, 0.0], "max": [31.0, 5.85, 24.0]},
            "source_revisions": {"dimensions": 1},
            "printable_deliverable": False,
        },
        {
            "id": "candidate-01",
            "role": "candidate",
            "path": "candidate_01.stl",
            "type": "stl",
            "sha256": HASH_C,
            "expected_components": 1,
            "bbox": {"min": [-31.5, -6.15, 0.0], "max": [31.5, 6.15, 24.6]},
            "source_revisions": {"dimensions": 1, "print_plan": 1},
            "printable_deliverable": True,
        },
    ],
}


def clone(value):
    return copy.deepcopy(value)


def issue_ids(issues):
    return {issue.id for issue in issues}


def codes(issues):
    return {issue.code for issue in issues}


# ---------------------------------------------------------------------------
# common.py
# ---------------------------------------------------------------------------


class FiniteNumberTest(unittest.TestCase):
    """Property-based: walk a realistic nested structure and, for every numeric
    leaf, confirm NaN/+Inf/-Inf at that exact path is caught with a matching
    field path -- not just "some" non-finite error.
    """

    def _numeric_paths(self, value, prefix):
        if isinstance(value, bool):
            return
        if isinstance(value, (int, float)):
            yield prefix
        elif isinstance(value, dict):
            for key, sub in value.items():
                yield from self._numeric_paths(sub, f"{prefix}.{key}")
        elif isinstance(value, list):
            for index, sub in enumerate(value):
                yield from self._numeric_paths(sub, f"{prefix}[{index}]")

    def _set_path(self, root, path, new_value):
        # path looks like ".a.b[0].c" -- walk it against dicts/lists.
        tokens = []
        buf = ""
        i = 0
        while i < len(path):
            ch = path[i]
            if ch == ".":
                if buf:
                    tokens.append(("key", buf))
                    buf = ""
                i += 1
            elif ch == "[":
                if buf:
                    tokens.append(("key", buf))
                    buf = ""
                end = path.index("]", i)
                tokens.append(("index", int(path[i + 1 : end])))
                i = end + 1
            else:
                buf += ch
                i += 1
        if buf:
            tokens.append(("key", buf))
        node = root
        for kind, token in tokens[:-1]:
            node = node[token]
        last_kind, last_token = tokens[-1]
        node[last_token] = new_value

    def test_every_numeric_field_rejects_non_finite(self) -> None:
        fixtures = {
            "job_state": _JOB_STATE,
            "print_plan": _PRINT_PLAN,
            "verification_report": _VERIFICATION_REPORT,
            "artifact_manifest": _ARTIFACT_MANIFEST,
        }
        checked_any = False
        for name, fixture in fixtures.items():
            for path in self._numeric_paths(fixture, ""):
                for bad in (float("nan"), float("inf"), float("-inf")):
                    working = clone(fixture)
                    self._set_path(working, path, bad)
                    issues = C.check_finite(working, name)
                    self.assertTrue(
                        any(issue.code == "NON_FINITE" and issue.where == f"{name}{path}" for issue in issues),
                        f"expected NON_FINITE at {name}{path} for {bad!r}, got {[i.id for i in issues]}",
                    )
                    checked_any = True
        self.assertTrue(checked_any, "fixtures produced no numeric leaves to test")

    def test_finite_fixture_has_no_non_finite_issues(self) -> None:
        for name, fixture in (("job_state", _JOB_STATE), ("print_plan", _PRINT_PLAN)):
            issues = C.check_finite(fixture, name)
            self.assertEqual([], issues)


class PathSafetyTest(unittest.TestCase):
    """Property-based: every one of a list of adversarial path strings must be
    rejected by name; one legitimate relative path must be accepted.
    """

    def test_rejects_traversal_absolute_and_unc_paths(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            bad_paths = [
                "../escape.stl",
                "sub/../../escape.stl",
                "/etc/passwd",
                "C:/Windows/system.ini",
                "c:\\windows\\system.ini",
                "//server/share/file.stl",
                "\\\\server\\share\\file.stl",
                "",
            ]
            for raw in bad_paths:
                issues, resolved = C.normalize_project_path(
                    raw, field="path", where="artifact_manifest.artifacts[X]", project_dir=project_dir
                )
                self.assertTrue(issues, f"expected rejection for {raw!r}")
                self.assertTrue(
                    all(issue.code == "BAD_PATH" for issue in issues),
                    f"{raw!r} -> {[issue.code for issue in issues]}",
                )
                self.assertTrue(
                    any("artifact_manifest.artifacts[X].path" == issue.where for issue in issues),
                    f"{raw!r}: {[issue.where for issue in issues]}",
                )
                self.assertIsNone(resolved)

    def test_accepts_project_relative_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            issues, resolved = C.normalize_project_path(
                "sub/model.stl", field="path", where="artifact_manifest.artifacts[X]", project_dir=project_dir
            )
            self.assertEqual([], issues)
            self.assertEqual(resolved, project_dir / "sub" / "model.stl")

    def test_rejects_symlink_escape_when_platform_supports_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            project_dir = root / "project"
            outside_dir = root / "outside"
            project_dir.mkdir()
            outside_dir.mkdir()
            (outside_dir / "secret.stl").write_bytes(b"not project data")
            link_path = project_dir / "linked.stl"
            try:
                link_path.symlink_to(outside_dir / "secret.stl")
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is not permitted in this environment")
                return
            issues, resolved = C.normalize_project_path(
                "linked.stl", field="path", where="artifact_manifest.artifacts[X]", project_dir=project_dir
            )
            self.assertTrue(issues, "expected the symlink escape to be rejected")
            self.assertEqual({"BAD_PATH"}, codes(issues))
            self.assertIsNone(resolved)


class HashFormatTest(unittest.TestCase):
    def test_is_hash_format_property(self) -> None:
        good = ["0" * 64, "a" * 64, "0123456789abcdef" * 4]
        bad = ["", "A" * 64, "g" * 64, "a" * 63, "a" * 65, "not-a-hash", 12345, None]
        for value in good:
            self.assertTrue(C.is_hash_format(value), value)
        for value in bad:
            self.assertFalse(C.is_hash_format(value), value)


# ---------------------------------------------------------------------------
# validators.py: job_state
# ---------------------------------------------------------------------------


class JobStateValidatorTest(unittest.TestCase):
    def test_normal_pass(self) -> None:
        issues, index = V.validate_job_state(clone(_JOB_STATE))
        self.assertEqual([], [i for i in issues if i.severity == "error"], issues)
        self.assertIn("M1", index["gate_ids"])

    def test_second_structurally_different_fixture_passes(self) -> None:
        alt = clone(_JOB_STATE)
        alt.update({"mode": "SOLO", "profile": "FULL", "state": "BLOCKED", "backend": "freecad"})
        alt["dispatches"] = []
        alt["gates"] = []
        issues, _ = V.validate_job_state(alt)
        self.assertEqual([], [i for i in issues if i.severity == "error"], issues)

    def test_malformed_missing_required_field(self) -> None:
        broken = clone(_JOB_STATE)
        del broken["backend"]
        issues, _ = V.validate_job_state(broken)
        self.assertIn("MISSING_FIELD@job_state.backend", issue_ids(issues))

    def test_malformed_wrong_type(self) -> None:
        broken = clone(_JOB_STATE)
        broken["revision"] = "five"
        issues, _ = V.validate_job_state(broken)
        self.assertIn("BAD_TYPE@job_state.revision", issue_ids(issues))

    def test_bad_enum_named_exactly(self) -> None:
        broken = clone(_JOB_STATE)
        broken["state"] = "NOT_A_REAL_STATE"
        issues, _ = V.validate_job_state(broken)
        self.assertIn("BAD_ENUM@job_state.state", issue_ids(issues))

    def test_duplicate_gate_ids_rejected(self) -> None:
        broken = clone(_JOB_STATE)
        broken["gates"].append(clone(broken["gates"][0]))
        issues, _ = V.validate_job_state(broken)
        self.assertIn("DUPLICATE_ID@job_state.gates", issue_ids(issues))

    def test_unknown_field_warns_not_errors(self) -> None:
        broken = clone(_JOB_STATE)
        broken["totally_unrecognized_field"] = "surprise"
        issues, _ = V.validate_job_state(broken)
        matching = [i for i in issues if i.id == "UNKNOWN_FIELD@job_state.totally_unrecognized_field"]
        self.assertEqual(1, len(matching))
        self.assertEqual("warning", matching[0].severity)

    def test_unsupported_contract_version_rejected(self) -> None:
        broken = clone(_JOB_STATE)
        broken["contract_version"] = 99
        issues, _ = V.validate_job_state(broken)
        self.assertIn("UNSUPPORTED_CONTRACT_VERSION@job_state.contract_version", issue_ids(issues))

    def test_risk_class_is_optional_absence_passes(self) -> None:
        # Backward compatibility: existing job_state.json files with no risk_class
        # (as in _JOB_STATE) must still pass.
        self.assertNotIn("risk_class", _JOB_STATE)
        issues, _ = V.validate_job_state(clone(_JOB_STATE))
        self.assertEqual([], [i for i in issues if i.severity == "error"], issues)

    def test_risk_class_valid_value_passes(self) -> None:
        for value in sorted(V.RISK_CLASS):
            with_class = clone(_JOB_STATE)
            with_class["risk_class"] = value
            with_class["risk_class_rationale"] = "sustained load on a printed bracket"
            issues, _ = V.validate_job_state(with_class)
            self.assertEqual([], [i for i in issues if i.severity == "error"], (value, issues))

    def test_risk_class_bad_value_rejected(self) -> None:
        broken = clone(_JOB_STATE)
        broken["risk_class"] = "R4_MADE_UP"
        issues, _ = V.validate_job_state(broken)
        self.assertIn("BAD_ENUM@job_state.risk_class", issue_ids(issues))


# ---------------------------------------------------------------------------
# validators.py: dimensions
# ---------------------------------------------------------------------------


class DimensionsValidatorTest(unittest.TestCase):
    def test_normal_pass(self) -> None:
        issues, index = V.validate_dimensions(clone(_DIMENSIONS))
        self.assertEqual([], [i for i in issues if i.severity == "error"], issues)
        self.assertIn("F01", index["feature_ids"])

    def test_second_structurally_different_fixture_passes(self) -> None:
        alt = clone(_DIMENSIONS)
        alt["status"] = "DRAFT"
        alt["features"][0]["confidence"] = "D"
        alt["reference_round_trip"] = []
        issues, _ = V.validate_dimensions(alt)
        self.assertEqual([], [i for i in issues if i.severity == "error"], issues)

    def test_malformed_missing_tolerance_response(self) -> None:
        broken = clone(_DIMENSIONS)
        del broken["dimensions"][0]["tolerance_response"]
        issues, _ = V.validate_dimensions(broken)
        self.assertIn("MISSING_FIELD@dimensions.dimensions[M01].tolerance_response", issue_ids(issues))

    def test_fk_missing_feature_named_exactly(self) -> None:
        broken = clone(_DIMENSIONS)
        broken["dimensions"][0]["feature_id"] = "F99-does-not-exist"
        issues, _ = V.validate_dimensions(broken)
        self.assertIn("FK_MISSING@dimensions.dimensions[M01].feature_id[0]", issue_ids(issues))
        matching = [i for i in issues if i.code == "FK_MISSING"][0]
        self.assertIn("F99-does-not-exist", matching.message)

    def test_source_needs_sha256_or_access_date(self) -> None:
        broken = clone(_DIMENSIONS)
        del broken["sources"][0]["sha256"]
        issues, _ = V.validate_dimensions(broken)
        self.assertIn("MISSING_FIELD@dimensions.sources[S1].sha256", issue_ids(issues))

    def test_bad_hash_format_named_exactly(self) -> None:
        broken = clone(_DIMENSIONS)
        broken["sources"][0]["sha256"] = "not-64-hex-chars"
        issues, _ = V.validate_dimensions(broken)
        self.assertIn("BAD_HASH@dimensions.sources[S1].sha256", issue_ids(issues))

    def test_evidence_path_traversal_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            broken = clone(_DIMENSIONS)
            broken["sources"][0]["evidence_path"] = "../outside.md"
            issues, _ = V.validate_dimensions(broken, project_dir=project_dir)
            self.assertIn("BAD_PATH@dimensions.sources[S1].evidence_path", issue_ids(issues))

    def test_duplicate_feature_ids_rejected(self) -> None:
        broken = clone(_DIMENSIONS)
        broken["features"].append(clone(broken["features"][0]))
        issues, _ = V.validate_dimensions(broken)
        self.assertIn("DUPLICATE_ID@dimensions.features", issue_ids(issues))

    def test_bad_confidence_enum(self) -> None:
        broken = clone(_DIMENSIONS)
        broken["features"][0]["confidence"] = "Z"
        issues, _ = V.validate_dimensions(broken)
        self.assertIn("BAD_ENUM@dimensions.features[F01].confidence", issue_ids(issues))


# ---------------------------------------------------------------------------
# validators.py: print_plan
# ---------------------------------------------------------------------------


class PrintPlanValidatorTest(unittest.TestCase):
    def test_normal_pass(self) -> None:
        issues, index = V.validate_print_plan(clone(_PRINT_PLAN), feature_ids={"F01": {}})
        self.assertEqual([], [i for i in issues if i.severity == "error"], issues)
        self.assertIn("S-01", index["support_rule_ids"])

    def test_second_structurally_different_fixture_support_allowed(self) -> None:
        alt = clone(_PRINT_PLAN)
        alt["support_rules"][0]["disposition"] = "SUPPORT_ALLOWED"
        alt["support_rules"][0]["allowed_contact_class"] = "nonfunctional plate land"
        alt["edges"][0]["exposure_class"] = "PERMITTED_SUPPORT_CONTACT"
        issues, _ = V.validate_print_plan(alt, feature_ids={"F01": {}})
        self.assertEqual([], [i for i in issues if i.severity == "error"], issues)

    def test_malformed_missing_support_rule_field(self) -> None:
        broken = clone(_PRINT_PLAN)
        del broken["support_rules"][0]["bed_z_mm"]
        issues, _ = V.validate_print_plan(broken)
        self.assertIn("MISSING_FIELD@print_plan.support_rules[S-01].bed_z_mm", issue_ids(issues))

    def test_adversarial_non_finite_matrix_entry(self) -> None:
        broken = clone(_PRINT_PLAN)
        broken["support_rules"][0]["model_to_printer_matrix"][2][2] = float("inf")
        finite_issues = C.check_finite(broken, "print_plan")
        self.assertIn(
            "NON_FINITE@print_plan.support_rules[0].model_to_printer_matrix[2][2]", issue_ids(finite_issues)
        )

    def test_bad_matrix_shape_named_exactly(self) -> None:
        broken = clone(_PRINT_PLAN)
        broken["support_rules"][0]["model_to_printer_matrix"] = [[1, 0, 0], [0, 1, 0, 0]]
        issues, _ = V.validate_print_plan(broken)
        self.assertTrue(
            any(i.code == "BAD_MATRIX" and "model_to_printer_matrix" in i.where for i in issues), issues
        )

    def test_allowed_sharp_without_reason_rejected(self) -> None:
        broken = clone(_PRINT_PLAN)
        broken["edges"][0]["allowed_sharp"] = True
        issues, _ = V.validate_print_plan(broken)
        self.assertIn("ALLOWED_SHARP_NEEDS_REASON@print_plan.edges[E-01].allowed_sharp_reason", issue_ids(issues))

    def test_support_allowed_without_contact_class_rejected(self) -> None:
        broken = clone(_PRINT_PLAN)
        broken["support_rules"][0]["disposition"] = "SUPPORT_ALLOWED"
        issues, _ = V.validate_print_plan(broken)
        self.assertIn(
            "SUPPORT_ALLOWED_NEEDS_CONTACT_CLASS@print_plan.support_rules[S-01].allowed_contact_class",
            issue_ids(issues),
        )

    def test_fk_related_feature_id_missing(self) -> None:
        broken = clone(_PRINT_PLAN)
        broken["geometry_rules"][0]["related_feature_ids"] = ["F-GHOST"]
        issues, _ = V.validate_print_plan(broken, feature_ids={"F01": {}})
        self.assertIn("FK_MISSING@print_plan.geometry_rules[G-01].related_feature_ids[0]", issue_ids(issues))

    def test_duplicate_edge_ids_rejected(self) -> None:
        broken = clone(_PRINT_PLAN)
        broken["edges"].append(clone(broken["edges"][0]))
        issues, _ = V.validate_print_plan(broken)
        self.assertIn("DUPLICATE_ID@print_plan.edges", issue_ids(issues))

    def test_stale_dimensions_revision_binding_reported_by_status(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            dimensions = clone(_DIMENSIONS)
            dimensions["revision"] = 7
            print_plan = clone(_PRINT_PLAN)
            print_plan["dimensions_revision"] = 2  # stale: bound to an old revision
            _write_project(project_dir, dimensions=dimensions, print_plan=print_plan)
            rows = S.compute_status(project_dir)
            stale = [r for r in rows if r["contract"] == "PRINT_PLAN" and r["status"] == "STALE"]
            self.assertEqual(1, len(stale), rows)
            self.assertIn("bound to dimensions r2, current r7", stale[0]["detail"])


# ---------------------------------------------------------------------------
# validators.py: verification_report
# ---------------------------------------------------------------------------


class VerificationReportValidatorTest(unittest.TestCase):
    def test_normal_pass(self) -> None:
        issues, index = V.validate_verification_report(clone(_VERIFICATION_REPORT), feature_ids={"F01": {}})
        self.assertEqual([], [i for i in issues if i.severity == "error"], issues)
        self.assertEqual(7, len(index["check_ids"]))

    def test_second_structurally_different_fixture_reject_with_defect(self) -> None:
        alt = clone(_VERIFICATION_REPORT)
        alt["status"] = "REJECT"
        alt["verdict"] = "REJECT to CANDIDATE_BUILD"
        alt["checks"][6]["result"] = "FAIL"
        alt["defects"] = [
            {
                "id": "DEF-01",
                "owning_loop": "CANDIDATE_BUILD",
                "feature_ids": ["F01"],
                "check_ids": ["7"],
                "expected_vs_observed": "expected zero out-of-limit area; observed 4.2mm2",
                "evidence": "support_audit.json",
                "required_acceptance_condition": "zero out-of-limit area on rerun",
            }
        ]
        issues, _ = V.validate_verification_report(alt, feature_ids={"F01": {}})
        self.assertEqual([], [i for i in issues if i.severity == "error"], issues)

    def test_malformed_missing_fresh_context(self) -> None:
        broken = clone(_VERIFICATION_REPORT)
        del broken["fresh_context"]
        issues, _ = V.validate_verification_report(broken)
        self.assertIn("MISSING_FIELD@verification_report.fresh_context", issue_ids(issues))

    def test_stale_verifier_context_rejected(self) -> None:
        broken = clone(_VERIFICATION_REPORT)
        broken["fresh_context"] = False
        issues, _ = V.validate_verification_report(broken)
        self.assertIn("STALE_VERIFIER_CONTEXT@verification_report.fresh_context", issue_ids(issues))

    def test_adversarial_non_finite_numeric_result(self) -> None:
        broken = clone(_VERIFICATION_REPORT)
        broken["checks"][0]["numeric_result"] = float("nan")
        finite_issues = C.check_finite(broken, "verification_report")
        self.assertIn(
            "NON_FINITE@verification_report.checks[0].numeric_result", issue_ids(finite_issues)
        )

    def test_pass_status_requires_all_seven_checks(self) -> None:
        broken = clone(_VERIFICATION_REPORT)
        broken["checks"] = broken["checks"][:6]  # drop check 7
        issues, _ = V.validate_verification_report(broken)
        self.assertIn("INCOMPLETE_SEVEN_CHECKS@verification_report.checks", issue_ids(issues))

    def test_reject_status_requires_defects(self) -> None:
        broken = clone(_VERIFICATION_REPORT)
        broken["status"] = "REJECT"
        issues, _ = V.validate_verification_report(broken)
        self.assertIn("REJECT_NEEDS_DEFECTS@verification_report.defects", issue_ids(issues))

    def test_defect_fk_missing_feature_and_check(self) -> None:
        broken = clone(_VERIFICATION_REPORT)
        broken["status"] = "REJECT"
        broken["defects"] = [
            {
                "id": "DEF-01",
                "owning_loop": "x",
                "feature_ids": ["F-GHOST"],
                "check_ids": ["9"],
                "expected_vs_observed": "x",
                "evidence": "x",
                "required_acceptance_condition": "x",
            }
        ]
        issues, _ = V.validate_verification_report(broken, feature_ids={"F01": {}})
        self.assertIn("FK_MISSING@verification_report.defects[DEF-01].feature_ids[0]", issue_ids(issues))
        self.assertIn("FK_MISSING@verification_report.defects[DEF-01].check_ids[0]", issue_ids(issues))


# ---------------------------------------------------------------------------
# validators.py + manifest_checks.py: artifact_manifest
# ---------------------------------------------------------------------------


def _write_project(project_dir: Path, **contracts) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    for key, filename in V.CANONICAL_FILENAMES.items():
        if key in contracts and contracts[key] is not None:
            (project_dir / filename).write_text(
                json.dumps(contracts[key], sort_keys=True, indent=2) + "\n", encoding="utf-8"
            )


def _write_box_stl(path: Path, extents, translate=(0.0, 0.0, 0.0)) -> tuple[str, list, list]:
    mesh = trimesh.creation.box(extents=extents)
    mesh.apply_translation(translate)
    path.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(path)
    return C.sha256_file(path), mesh.bounds[0].tolist(), mesh.bounds[1].tolist()


class ArtifactManifestValidatorTest(unittest.TestCase):
    def test_normal_pass(self) -> None:
        issues, index = V.validate_artifact_manifest(clone(_ARTIFACT_MANIFEST))
        self.assertEqual([], [i for i in issues if i.severity == "error"], issues)
        self.assertIn("candidate-01", index["artifact_ids"])

    def test_second_structurally_different_fixture_with_paired_step(self) -> None:
        alt = clone(_ARTIFACT_MANIFEST)
        alt["artifacts"].append(
            {
                "id": "reference-bar-step",
                "role": "source",
                "path": "reference_bar.step",
                "type": "step",
                "sha256": HASH_D,
                "paired_artifact_id": "reference-bar",
            }
        )
        issues, _ = V.validate_artifact_manifest(alt)
        self.assertEqual([], [i for i in issues if i.severity == "error"], issues)

    def test_malformed_missing_sha256(self) -> None:
        broken = clone(_ARTIFACT_MANIFEST)
        del broken["artifacts"][0]["sha256"]
        issues, _ = V.validate_artifact_manifest(broken)
        self.assertIn("MISSING_FIELD@artifact_manifest.artifacts[reference-bar].sha256", issue_ids(issues))

    def test_adversarial_non_finite_bbox(self) -> None:
        broken = clone(_ARTIFACT_MANIFEST)
        broken["artifacts"][0]["bbox"]["max"][1] = float("nan")
        finite_issues = C.check_finite(broken, "artifact_manifest")
        self.assertIn(
            "NON_FINITE@artifact_manifest.artifacts[0].bbox.max[1]", issue_ids(finite_issues)
        )

    def test_bbox_must_be_positive_named_exactly(self) -> None:
        broken = clone(_ARTIFACT_MANIFEST)
        broken["artifacts"][0]["bbox"]["max"][0] = broken["artifacts"][0]["bbox"]["min"][0]  # zero extent
        issues, _ = V.validate_artifact_manifest(broken)
        self.assertIn("BBOX_NOT_POSITIVE@artifact_manifest.artifacts[reference-bar].bbox", issue_ids(issues))

    def test_duplicate_artifact_ids_rejected(self) -> None:
        broken = clone(_ARTIFACT_MANIFEST)
        dup = clone(broken["artifacts"][0])
        broken["artifacts"].append(dup)
        issues, _ = V.validate_artifact_manifest(broken)
        self.assertIn("DUPLICATE_ID@artifact_manifest.artifacts", issue_ids(issues))

    def test_bad_role_enum_named_exactly(self) -> None:
        broken = clone(_ARTIFACT_MANIFEST)
        broken["artifacts"][0]["role"] = "not-a-real-role"
        issues, _ = V.validate_artifact_manifest(broken)
        self.assertIn("BAD_ENUM@artifact_manifest.artifacts[reference-bar].role", issue_ids(issues))

    def test_mating_reference_cannot_be_printable(self) -> None:
        broken = clone(_ARTIFACT_MANIFEST)
        broken["artifacts"][0]["role"] = "mating_reference"
        broken["artifacts"][0]["printable_deliverable"] = True
        issues, _ = V.validate_artifact_manifest(broken)
        self.assertIn(
            "MATING_REFERENCE_NOT_PRINTABLE@artifact_manifest.artifacts[reference-bar].printable_deliverable",
            issue_ids(issues),
        )

    def test_path_traversal_rejected_in_context(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            broken = clone(_ARTIFACT_MANIFEST)
            broken["artifacts"][0]["path"] = "../outside.stl"
            issues, _ = V.validate_artifact_manifest(broken, project_dir=project_dir)
            self.assertIn("BAD_PATH@artifact_manifest.artifacts[reference-bar].path", issue_ids(issues))

    def test_paired_artifact_fk_missing(self) -> None:
        broken = clone(_ARTIFACT_MANIFEST)
        broken["artifacts"][0]["paired_artifact_id"] = "does-not-exist"
        issues, _ = V.validate_artifact_manifest(broken)
        self.assertIn(
            "FK_MISSING@artifact_manifest.artifacts[reference-bar].paired_artifact_id[0]", issue_ids(issues)
        )


class ArtifactManifestFileChecksTest(unittest.TestCase):
    """Filesystem/mesh checks: exists, hash-matches (never trust an entered
    hash), finite bbox, obvious 25.4x unit-scale mismatch, component count.
    """

    def test_missing_artifact_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            artifact = {"id": "A1", "role": "reference", "path": "nowhere.stl", "type": "stl", "sha256": HASH_A}
            issues = MC.check_artifact_files(artifact=artifact, artifact_id="A1", project_dir=project_dir, where="w")
            self.assertIn("ARTIFACT_MISSING@w.path", issue_ids(issues))

    def test_hash_mismatch_never_trusts_declared_hash(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            stl_hash, bmin, bmax = _write_box_stl(project_dir / "box.stl", (2, 2, 2))
            artifact = {
                "id": "A1",
                "role": "reference",
                "path": "box.stl",
                "type": "stl",
                "sha256": "0" * 64,  # deliberately wrong
                "bbox": {"min": bmin, "max": bmax},
            }
            issues = MC.check_artifact_files(artifact=artifact, artifact_id="A1", project_dir=project_dir, where="w")
            self.assertIn("HASH_MISMATCH@w.sha256", issue_ids(issues))

    def test_correct_hash_and_bbox_pass(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            stl_hash, bmin, bmax = _write_box_stl(project_dir / "box.stl", (2, 2, 2))
            artifact = {
                "id": "A1",
                "role": "reference",
                "path": "box.stl",
                "type": "stl",
                "sha256": stl_hash,
                "expected_components": 1,
                "bbox": {"min": bmin, "max": bmax},
            }
            issues = MC.check_artifact_files(artifact=artifact, artifact_id="A1", project_dir=project_dir, where="w")
            self.assertEqual([], issues)

    def test_obvious_inch_mm_scale_mismatch_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            stl_hash, bmin, bmax = _write_box_stl(project_dir / "box.stl", (2.0, 2.0, 2.0))
            declared_min = [v * C.INCH_TO_MM for v in bmin]
            declared_max = [v * C.INCH_TO_MM for v in bmax]
            artifact = {
                "id": "A1",
                "role": "reference",
                "path": "box.stl",
                "type": "stl",
                "sha256": stl_hash,
                "bbox": {"min": declared_min, "max": declared_max},
            }
            issues = MC.check_artifact_files(artifact=artifact, artifact_id="A1", project_dir=project_dir, where="w")
            self.assertIn("UNIT_SCALE_MISMATCH@w.bbox", issue_ids(issues))

    def test_generic_bbox_mismatch_not_near_25_4x(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            stl_hash, bmin, bmax = _write_box_stl(project_dir / "box.stl", (2.0, 2.0, 2.0))
            declared_max = [v * 3.0 for v in bmax]  # 3x -- not an inch/mm ratio
            artifact = {
                "id": "A1",
                "role": "reference",
                "path": "box.stl",
                "type": "stl",
                "sha256": stl_hash,
                "bbox": {"min": bmin, "max": declared_max},
            }
            issues = MC.check_artifact_files(artifact=artifact, artifact_id="A1", project_dir=project_dir, where="w")
            self.assertIn("BBOX_MISMATCH@w.bbox", issue_ids(issues))

    def test_component_count_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            first = trimesh.creation.box(extents=(1, 1, 1))
            second = trimesh.creation.box(extents=(1, 1, 1))
            second.apply_translation((10, 10, 10))
            combined = trimesh.util.concatenate((first, second))
            path = project_dir / "two_parts.stl"
            combined.export(path)
            artifact = {
                "id": "A1",
                "role": "reference",
                "path": "two_parts.stl",
                "type": "stl",
                "sha256": C.sha256_file(path),
                "expected_components": 1,
            }
            issues = MC.check_artifact_files(artifact=artifact, artifact_id="A1", project_dir=project_dir, where="w")
            self.assertIn("COMPONENT_COUNT_MISMATCH@w.expected_components", issue_ids(issues))

    def test_paired_step_compare_skips_gracefully_without_step_backend(self) -> None:
        # STEP loading needs an optional OCC backend (e.g. cascadio) that is
        # not part of this project's dependency set; the pairing check must
        # skip, not crash or falsely report a mismatch, per the "trimesh/
        # cadquery only if trivially available" instruction.
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            _write_box_stl(project_dir / "ref.stl", (2, 2, 2))
            (project_dir / "ref.step").write_text("not a real STEP file", encoding="utf-8")
            artifacts = {
                "A1": {"id": "A1", "type": "stl", "path": "ref.stl", "paired_artifact_id": "A2"},
                "A2": {"id": "A2", "type": "step", "path": "ref.step", "paired_artifact_id": "A1"},
            }
            issues = MC.compare_paired_stl_step(artifacts=artifacts, project_dir=project_dir, where="artifact_manifest")
            self.assertEqual([], issues)


# ---------------------------------------------------------------------------
# project.py / receipts.py / status.py: whole-project behavior
# ---------------------------------------------------------------------------


class ProjectValidateReceiptTest(unittest.TestCase):
    def _build_full_project(self, project_dir: Path) -> dict:
        reference_hash, ref_min, ref_max = _write_box_stl(project_dir / "reference_bar.stl", (62.0, 11.7, 24.0), (0, 0, 12.0))
        candidate_hash, cand_min, cand_max = _write_box_stl(project_dir / "candidate_01.stl", (63.0, 12.3, 24.6), (0, 0, 12.3))
        (project_dir / "evidence").mkdir(exist_ok=True)
        (project_dir / "evidence" / "brief.md").write_text("brief\n", encoding="utf-8")
        brief_hash = C.sha256_file(project_dir / "evidence" / "brief.md")

        dimensions = clone(_DIMENSIONS)
        dimensions["sources"][0]["sha256"] = brief_hash
        print_plan = clone(_PRINT_PLAN)
        print_plan["reference_sha256"] = reference_hash
        verification_report = clone(_VERIFICATION_REPORT)
        verification_report["reference_sha256"] = reference_hash
        verification_report["candidate_stl_sha256"] = candidate_hash
        manifest = clone(_ARTIFACT_MANIFEST)
        manifest["artifacts"][0]["sha256"] = reference_hash
        manifest["artifacts"][0]["bbox"] = {"min": ref_min, "max": ref_max}
        manifest["artifacts"][1]["sha256"] = candidate_hash
        manifest["artifacts"][1]["bbox"] = {"min": cand_min, "max": cand_max}

        _write_project(
            project_dir,
            job_state=clone(_JOB_STATE),
            dimensions=dimensions,
            print_plan=print_plan,
            verification_report=verification_report,
            artifact_manifest=manifest,
        )
        return {"reference_hash": reference_hash, "candidate_hash": candidate_hash}

    def test_full_project_validates_clean(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            self._build_full_project(project_dir)
            receipt, project = R.build_validate_receipt(project_dir, timestamp=None, argv=["validate", str(project_dir)])
            self.assertEqual("PASS", receipt["results"]["overall"], receipt["issues"])
            self.assertEqual([], receipt["error_ids"])
            self.assertIn("does NOT prove geometric or manufacturing correctness", receipt["disclaimer"])
            self.assertEqual(C.DEFAULT_TIMESTAMP, receipt["timestamp"])

    def test_missing_contract_file_is_a_warning_not_a_crash(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            _write_project(project_dir, job_state=clone(_JOB_STATE))
            receipt, _project = R.build_validate_receipt(project_dir, timestamp="fixed", argv=[])
            self.assertIn("MISSING_CONTRACT_FILE@dimensions", receipt["warning_ids"])
            self.assertEqual("fixed", receipt["timestamp"])

    def test_receipt_is_deterministic_across_runs(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            self._build_full_project(project_dir)
            first, _ = R.build_validate_receipt(project_dir, timestamp="T", argv=["validate", "x"])
            second, _ = R.build_validate_receipt(project_dir, timestamp="T", argv=["validate", "x"])
            self.assertEqual(C.canonical_json(first), C.canonical_json(second))

    def test_mutating_artifact_bytes_invalidates_hash_binding(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            hashes = self._build_full_project(project_dir)
            # Mutate the on-disk reference STL after the manifest/plan were
            # bound to its original hash -- "never silently update a binding".
            with (project_dir / "reference_bar.stl").open("ab") as handle:
                handle.write(b"\x00")

            hash_receipt = R.build_hash_receipt(project_dir, timestamp="T", argv=[])
            self.assertIn("reference-bar", hash_receipt["hash_mismatches"])
            self.assertNotEqual(hashes["reference_hash"], hash_receipt["artifact_sha256"]["reference-bar"])

            status_rows = S.compute_status(project_dir)
            invalidated = [r for r in status_rows if r["status"] == "INVALIDATED"]
            self.assertTrue(invalidated, status_rows)
            self.assertTrue(any("reference_sha256 bound" in r["detail"] for r in invalidated), status_rows)

            # And the binding itself must NOT have been silently rewritten.
            plan_after = json.loads((project_dir / "print_plan.json").read_text())
            self.assertEqual(hashes["reference_hash"], plan_after["reference_sha256"])

    def test_agent_summary_mentions_key_facts(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            self._build_full_project(project_dir)
            text = SUM.build_agent_summary(project_dir)
            self.assertIn("mode=PIPELINE", text)
            self.assertIn("job_state=r1", text)
            self.assertIn("informational only", text)


# ---------------------------------------------------------------------------
# render.py
# ---------------------------------------------------------------------------


class RenderTest(unittest.TestCase):
    def test_render_each_contract_type_is_deterministic_and_bannered(self) -> None:
        fixtures = {
            V.CANONICAL_FILENAMES["job_state"]: _JOB_STATE,
            V.CANONICAL_FILENAMES["dimensions"]: _DIMENSIONS,
            V.CANONICAL_FILENAMES["print_plan"]: _PRINT_PLAN,
            V.CANONICAL_FILENAMES["verification_report"]: _VERIFICATION_REPORT,
            V.CANONICAL_FILENAMES["artifact_manifest"]: _ARTIFACT_MANIFEST,
        }
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            for filename, data in fixtures.items():
                path = project_dir / filename
                path.write_text(json.dumps(data, sort_keys=True, indent=2), encoding="utf-8")
                first = RD.render_contract_file(path)
                second = RD.render_contract_file(path)
                self.assertEqual(first, second, filename)
                self.assertTrue(first.startswith(RD.BANNER), filename)
                self.assertIn(str(data["job_id"]) if "job_id" in data else data.get("candidate_id", ""), first)

    def test_render_unknown_contract_kind_raises_named_error(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "weird.json"
            path.write_text(json.dumps({"contract": "not-a-real-contract"}), encoding="utf-8")
            with self.assertRaises(C.ContractError) as ctx:
                RD.render_contract_file(path)
            self.assertIn("not-a-real-contract", str(ctx.exception))


# ---------------------------------------------------------------------------
# CLI subprocess tests (matches the invocation style in the implementation
# plan: `python -m team_tools.contracts <cmd> <path>` run from scripts/).
# ---------------------------------------------------------------------------


class CliTest(unittest.TestCase):
    SCRIPTS_DIR = Path(__file__).resolve().parent.parent

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "team_tools.contracts", *args],
            cwd=str(self.SCRIPTS_DIR),
            capture_output=True,
            text=True,
            check=False,
        )

    def test_help_works(self) -> None:
        completed = self._run("--help")
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("validate", completed.stdout)
        self.assertIn("agent-summary", completed.stdout)

    def test_validate_cli_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            helper = ProjectValidateReceiptTest()
            helper._build_full_project(project_dir)
            completed = self._run("validate", str(project_dir), "--timestamp", "FIXED")
            self.assertEqual(0, completed.returncode, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual("PASS", payload["results"]["overall"])
            self.assertEqual("FIXED", payload["timestamp"])

    def test_status_cli_exit_code_reflects_staleness(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            dimensions = clone(_DIMENSIONS)
            dimensions["revision"] = 9
            print_plan = clone(_PRINT_PLAN)
            print_plan["dimensions_revision"] = 1
            _write_project(project_dir, dimensions=dimensions, print_plan=print_plan)
            completed = self._run("status", str(project_dir))
            self.assertEqual(1, completed.returncode)
            self.assertIn("STALE", completed.stdout)


if __name__ == "__main__":
    unittest.main()
