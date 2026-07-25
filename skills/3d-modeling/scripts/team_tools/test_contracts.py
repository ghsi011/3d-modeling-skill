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

import numpy as np
import trimesh

_PACKAGE_DIR = str(Path(__file__).resolve().parent)
if _PACKAGE_DIR not in sys.path:
    sys.path.insert(0, _PACKAGE_DIR)

import common as C  # noqa: E402  (import after sys.path bootstrap above)
import contracts as CLI  # noqa: E402
import manifest_checks as MC  # noqa: E402
import receipts as R  # noqa: E402
import status as S  # noqa: E402
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
# Project fixtures
# ---------------------------------------------------------------------------


def _write_project(project_dir: Path, *, as_markdown: bool = False, **contracts) -> None:
    """Write contract fixtures as the JSON mirror, or (``as_markdown``) as the
    Markdown the roles actually author, with the fixture's scalars as
    frontmatter. Both are legal sources; the tests exercise each.
    """
    project_dir.mkdir(parents=True, exist_ok=True)
    for key, filenames in V.CANONICAL_FILENAMES.items():
        if key not in contracts or contracts[key] is None:
            continue
        data = contracts[key]
        markdown_name = next((n for n in filenames if n.endswith(".md")), None)
        if as_markdown and markdown_name:
            scalars = "\n".join(
                f"{k}: {'true' if v is True else 'false' if v is False else v}"
                for k, v in data.items()
                if isinstance(v, (str, int, float, bool))
            )
            body = f"---\n{scalars}\n---\n\n# {key}\n\nBody prose is not schema-checked.\n"
            (project_dir / markdown_name).write_text(body, encoding="utf-8")
        else:
            json_name = next(n for n in filenames if n.endswith(".json"))
            (project_dir / json_name).write_text(
                json.dumps(data, sort_keys=True, indent=2) + "\n", encoding="utf-8"
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

    def test_scale_flag_on_one_axis_does_not_hide_bbox_mismatch_on_another(self) -> None:
        # Regression: the bbox check used to be an `elif` on the scale flag, so a
        # near-25.4x ratio on axis 0 suppressed BBOX_MISMATCH on EVERY axis --
        # axis 1 here is declared 5x too large and shipped as a warning only.
        issues = MC._compare_extents(
            declared_extent=np.array([25.9, 50.0, 10.0]),
            actual_extent=np.array([1.0, 10.0, 10.0]),
            where="w.bbox",
        )
        ids = issue_ids(issues)
        self.assertIn("POSSIBLE_UNIT_SCALE_MISMATCH@w.bbox", ids)
        self.assertIn("BBOX_MISMATCH@w.bbox", ids)
        bbox_issue = next(i for i in issues if i.code == "BBOX_MISMATCH")
        self.assertIn("[0, 1]", bbox_issue.message)  # axis 1 is the one that used to vanish

    def test_loose_scale_flag_is_not_promoted_by_an_unrelated_axis(self) -> None:
        # The other direction: promotion to a hard UNIT_SCALE_MISMATCH must come
        # from the flagged axis's own ratio. Axis 0 is 1.97% off 25.4x (warning
        # band, outside the 0.5% block band); no axis may raise it to an error.
        issues = MC._compare_extents(
            declared_extent=np.array([25.9, 50.0, 10.0]),
            actual_extent=np.array([1.0, 10.0, 10.0]),
            where="w.bbox",
        )
        scale_issues = [i for i in issues if i.code.endswith("UNIT_SCALE_MISMATCH")]
        self.assertEqual(["warning"], [i.severity for i in scale_issues])

    def test_exact_25_4x_still_blocks_and_still_reports_the_bbox(self) -> None:
        # An exact 25.4x ratio stays a hard error, and now also emits the bbox
        # finding it previously swallowed -- both facts are true of this mesh.
        issues = MC._compare_extents(
            declared_extent=np.array([25.4, 50.8, 76.2]),
            actual_extent=np.array([1.0, 2.0, 3.0]),
            where="w.bbox",
        )
        ids = issue_ids(issues)
        self.assertIn("UNIT_SCALE_MISMATCH@w.bbox", ids)
        self.assertIn("BBOX_MISMATCH@w.bbox", ids)

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

    def test_absent_contract_is_silent_and_recorded_in_validated_paths(self) -> None:
        """An early-phase project holds only what its phase produced, so absence
        is not a finding. It used to raise four warnings on every correct run --
        on the same channel that carries POSSIBLE_UNIT_SCALE_MISMATCH, which the
        verifier must actually read. What was read is recorded instead.
        """
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            _write_project(project_dir, job_state=clone(_JOB_STATE))
            receipt, _project = R.build_validate_receipt(project_dir, timestamp="fixed", argv=[])
            self.assertEqual([], receipt["warning_ids"])
            self.assertEqual([], receipt["error_ids"])
            self.assertEqual(["job_state.json"], receipt["validated_paths"])
            self.assertEqual("fixed", receipt["timestamp"])

    def test_markdown_contract_is_read_from_frontmatter(self) -> None:
        """The roles author Markdown. Its frontmatter carries identity, revision
        and the binding hashes, so it validates like the JSON mirror does.
        """
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            _write_project(project_dir, as_markdown=True, job_state=clone(_JOB_STATE),
                           dimensions=clone(_DIMENSIONS))
            receipt, project = R.build_validate_receipt(project_dir, timestamp="fixed", argv=[])
            self.assertEqual("PASS", receipt["results"]["overall"], receipt["issues"])
            self.assertEqual([], receipt["error_ids"])
            self.assertEqual(["dimensions.md", "job_state.md"], receipt["validated_paths"])
            self.assertEqual("markdown", project.files["dimensions"].source_format)
            # The binding field the staleness checks compare survived the parse.
            self.assertEqual(1, project.files["dimensions"].data["revision"])

    def test_markdown_contract_with_a_bad_header_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            broken = clone(_DIMENSIONS)
            del broken["revision"]
            _write_project(project_dir, as_markdown=True, dimensions=broken)
            receipt, _project = R.build_validate_receipt(project_dir, timestamp="fixed", argv=[])
            self.assertIn("MISSING_FIELD@dimensions.revision", receipt["error_ids"])
            self.assertEqual("FAIL", receipt["results"]["overall"])

    def test_required_contract_absence_is_an_error_not_a_warning(self) -> None:
        """A caller gating on validate must be able to say which contracts its
        phase requires; everything it did not name stays silent, so an
        early-phase project still validates.
        """
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            _write_project(project_dir, job_state=clone(_JOB_STATE))
            receipt, _project = R.build_validate_receipt(
                project_dir, timestamp="fixed", argv=[], required=["dimensions"]
            )
            self.assertIn("REQUIRED_CONTRACT_MISSING@dimensions", receipt["error_ids"])
            self.assertEqual("FAIL", receipt["results"]["dimensions"])
            self.assertEqual("FAIL", receipt["results"]["overall"])
            self.assertEqual(["dimensions"], receipt["required_contracts"])
            # A contract the caller did not name is simply absent: no issue at
            # all, and its own result stays PASS.
            self.assertEqual("PASS", receipt["results"]["print_plan"])
            self.assertEqual([], receipt["warning_ids"])

    def test_required_contract_present_validates_clean(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            self._build_full_project(project_dir)
            receipt, _project = R.build_validate_receipt(
                project_dir, timestamp="fixed", argv=[], required=list(V.CANONICAL_FILENAMES)
            )
            self.assertEqual("PASS", receipt["results"]["overall"], receipt["issues"])
            self.assertEqual([], receipt["error_ids"])
            self.assertEqual(sorted(V.CANONICAL_FILENAMES), receipt["required_contracts"])

    def test_nonexistent_project_dir_raises_instead_of_validating_green(self) -> None:
        """A typo'd path must not be indistinguishable from a clean early-phase
        project. Every canonical file is absent either way, so the directory
        check is the only thing separating them.
        """
        with tempfile.TemporaryDirectory() as raw_dir:
            missing = Path(raw_dir) / "no-such-project"
            with self.assertRaises(C.ContractError):
                R.build_validate_receipt(missing, timestamp="fixed", argv=[])
            # And it is a usage/filesystem failure (exit 2), never a gate pass.
            self.assertEqual(2, CLI.main(["validate", str(missing)]))

    def test_require_flag_parsing(self) -> None:
        self.assertEqual([], CLI._parse_required(None))
        self.assertEqual(["job_state", "dimensions"], CLI._parse_required(["job_state,dimensions"]))
        self.assertEqual(["job_state", "dimensions"], CLI._parse_required(["job_state", "dimensions"]))
        self.assertEqual(list(V.CANONICAL_FILENAMES), CLI._parse_required(["all"]))
        # An unknown name must fail loudly: silently dropping it would disarm
        # the gate the caller asked for.
        with self.assertRaises(C.ContractError):
            CLI._parse_required(["dimensionz"])

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
        self.assertIn("status", completed.stdout)

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
