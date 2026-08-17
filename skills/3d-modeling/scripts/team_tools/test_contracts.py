"""Tests for team_tools.contracts.

Runnable as:
    uv run --project <skill> --frozen python -m team_tools.test_contracts     (from the repo root or skill directory)
    uv run --project <skill> --frozen python <skill>/scripts/team_tools/test_contracts.py      (from any directory)

For every validator: a normal-pass fixture, a malformed-input fixture, an
adversarial numeric (NaN/Inf) fixture, a stale-dependency fixture where
relevant, and a second structurally-different fixture. Non-finite numbers,
paths, duplicate IDs, enums, and hashes/mutation are covered with hand-rolled
property-based loops that walk every applicable field rather than one
hardcoded case. Every assertion below checks that the failure message names
the exact contract field/id/rule, not just that *something* failed.

The half of this file the commit gate will not carry is in
`benchmarks/heavy/test_contracts_heavy.py`, and runs before merge instead of on
every push: `CliTest`. Same tests, moved rather than weakened; `conftest.py`
carries the rule and `benchmarks/heavy/README.md` the measurement behind it.
"""

from __future__ import annotations

import copy
import json
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
    "profile": "FITTED",
    "consequence": "INCONSEQUENTIAL",
    "state": "CANDIDATE_BUILD",
    "backend": "build123d",
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
    "schema_version": 4,
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
_DELIVERABLE = {
    "format": "3mf",
    "purpose": "the archive that goes to the slicer",
    "source_geometry": "the accepted candidate solid",
    "units": "millimetre",
    "frame": "installed frame, identity transform",
    "export_path": "make_3mf.py from the exported STL",
    "acceptance": "unit is millimetre, one printable body, matches the accepted STL",
}

_EXPORT_FIDELITY = {
    "applies_because": "the STL is what the preservation comparison measures",
    "basis": "four-point convergence ladder on this part",
    "chord_tolerance_mm": [0.005, 0.010],
    "angular_tolerance_deg": [0.05, 0.10],
    "worst_error_mm": 0.004,
    "tolerance_it_must_not_consume_mm": 0.1,
}


class PrintPlanDeliverableClosureTest(unittest.TestCase):
    """**This proves a deliverable the commission names cannot vanish from the
    plan, because it fails when that deliverable's entry is removed.**

    Not hypothetical. On a real MODIFY commission whose brief listed both an STL
    and a 3MF, a plan was authored that never mentioned the 3MF at all -- zero
    occurrences -- and passed every structural check there was, because nothing
    checked that a named deliverable had been closed. A deliverable nobody
    constrained is one nobody can reject, and it reaches a printer anyway.
    """

    def _plan(self) -> dict:
        plan = clone(_PRINT_PLAN)
        plan["deliverables"] = [clone(_DELIVERABLE)]
        return plan

    def test_a_named_deliverable_that_is_closed_passes(self) -> None:
        """The control. Without it, a check that refuses everything would pass."""
        issues = V.validate_print_plan(
            self._plan(), feature_ids={"F01": {}}, required_deliverables=["3mf"])
        self.assertEqual([], [i for i in issues if i.severity == "error"], issues)

    def test_a_named_deliverable_the_plan_omits_is_an_error(self) -> None:
        plan = clone(_PRINT_PLAN)          # no `deliverables` at all
        issues = V.validate_print_plan(
            plan, feature_ids={"F01": {}}, required_deliverables=["stl", "3mf"])
        ids = issue_ids(issues)
        self.assertIn("MISSING_DELIVERABLE@print_plan.deliverables[stl]", ids)
        self.assertIn("MISSING_DELIVERABLE@print_plan.deliverables[3mf]", ids)

    def test_one_of_two_named_deliverables_is_still_an_error(self) -> None:
        """The case that actually happened: the STL closed, the 3MF forgotten."""
        issues = V.validate_print_plan(
            self._plan(), feature_ids={"F01": {}},
            required_deliverables=["stl", "3mf"])
        ids = issue_ids(issues)
        self.assertIn("MISSING_DELIVERABLE@print_plan.deliverables[stl]", ids)
        self.assertNotIn("MISSING_DELIVERABLE@print_plan.deliverables[3mf]", ids)

    def test_a_deliverable_present_but_unbound_is_an_error(self) -> None:
        """Naming a format is not closing it: the plan has to say what the thing
        is for, where it comes from, in what units and frame, how it is produced
        and what would reject it."""
        thin = self._plan()
        del thin["deliverables"][0]["units"]
        del thin["deliverables"][0]["acceptance"]
        ids = issue_ids(V.validate_print_plan(
            thin, feature_ids={"F01": {}}, required_deliverables=["3mf"]))
        self.assertIn("MISSING_FIELD@print_plan.deliverables[3mf].units", ids)
        self.assertIn("MISSING_FIELD@print_plan.deliverables[3mf].acceptance", ids)

    def test_nothing_is_required_when_the_commission_names_nothing(self) -> None:
        """The second control, and it is what keeps this from becoming a tax on
        every existing plan: absent a stated deliverable list, this check is
        silent."""
        issues = V.validate_print_plan(clone(_PRINT_PLAN), feature_ids={"F01": {}})
        self.assertEqual([], [i for i in issues if i.severity == "error"], issues)


class PrintPlanExportFidelityTest(unittest.TestCase):
    """**This proves an export-fidelity envelope is required wherever
    discretization decides something, because it fails when that block is removed
    from a job that declares such a decision -- and passes when the job declares
    none.**

    The measured case: one plan froze a chord band on a convergence ladder that
    excluded both the deflection where the mesh reads non-watertight and the
    coarse one where volume error reached 10% of the material the edit removes;
    its cheaper sibling left the export unconstrained entirely, which makes a
    mass-based preservation comparison meaningless without any rule appearing to
    fail.
    """

    def _plan(self) -> dict:
        plan = clone(_PRINT_PLAN)
        plan["export_fidelity"] = clone(_EXPORT_FIDELITY)
        return plan

    def test_a_declared_envelope_passes(self) -> None:
        issues = V.validate_print_plan(
            self._plan(), feature_ids={"F01": {}}, discretized_decision=True)
        self.assertEqual([], [i for i in issues if i.severity == "error"], issues)

    def test_no_envelope_where_discretization_decides_is_an_error(self) -> None:
        issues = V.validate_print_plan(
            clone(_PRINT_PLAN), feature_ids={"F01": {}}, discretized_decision=True)
        self.assertIn("MISSING_EXPORT_FIDELITY@print_plan.export_fidelity",
                      issue_ids(issues))

    def test_an_envelope_without_a_measured_basis_is_an_error(self) -> None:
        """A band with no measurement behind it is a number somebody chose, which
        is the thing the charter forbids -- and copying another part's band is the
        specific way that happens."""
        guessed = self._plan()
        del guessed["export_fidelity"]["basis"]
        self.assertIn("MISSING_FIELD@print_plan.export_fidelity.basis",
                      issue_ids(V.validate_print_plan(
                          guessed, feature_ids={"F01": {}},
                          discretized_decision=True)))

    def test_a_job_that_decides_nothing_on_a_mesh_is_not_forced_to_invent_one(self) -> None:
        """The control, and it owes the same proof as the regression: a job where
        discretization is irrelevant must not be pushed into inventing
        tessellation figures, because a fabricated envelope is itself a defect."""
        issues = V.validate_print_plan(
            clone(_PRINT_PLAN), feature_ids={"F01": {}}, discretized_decision=False)
        self.assertEqual([], [i for i in issues if i.severity == "error"], issues)
        issues = V.validate_print_plan(clone(_PRINT_PLAN), feature_ids={"F01": {}})
        self.assertEqual([], [i for i in issues if i.severity == "error"], issues)


class PrintPlanValidatorTest(unittest.TestCase):
    def test_normal_pass(self) -> None:
        issues = V.validate_print_plan(clone(_PRINT_PLAN), feature_ids={"F01": {}})
        self.assertEqual([], [i for i in issues if i.severity == "error"], issues)

    def test_schema_version_is_required_and_supported(self) -> None:
        missing = clone(_PRINT_PLAN)
        del missing["schema_version"]
        self.assertIn("MISSING_FIELD@print_plan.schema_version",
                      issue_ids(V.validate_print_plan(missing)))

        unknown = clone(_PRINT_PLAN)
        unknown["schema_version"] = 99
        self.assertIn("BAD_SCHEMA_VERSION@print_plan.schema_version",
                      issue_ids(V.validate_print_plan(unknown)))

    def test_second_structurally_different_fixture_support_allowed(self) -> None:
        alt = clone(_PRINT_PLAN)
        alt["support_rules"][0]["disposition"] = "SUPPORT_ALLOWED"
        alt["support_rules"][0]["allowed_contact_class"] = "nonfunctional plate land"
        alt["edges"][0]["exposure_class"] = "PERMITTED_SUPPORT_CONTACT"
        issues = V.validate_print_plan(alt, feature_ids={"F01": {}})
        self.assertEqual([], [i for i in issues if i.severity == "error"], issues)

    def test_malformed_missing_support_rule_field(self) -> None:
        broken = clone(_PRINT_PLAN)
        del broken["support_rules"][0]["bed_z_mm"]
        issues = V.validate_print_plan(broken)
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
        issues = V.validate_print_plan(broken)
        self.assertTrue(
            any(i.code == "BAD_MATRIX" and "model_to_printer_matrix" in i.where for i in issues), issues
        )

    def test_allowed_sharp_without_reason_rejected(self) -> None:
        broken = clone(_PRINT_PLAN)
        broken["edges"][0]["allowed_sharp"] = True
        issues = V.validate_print_plan(broken)
        self.assertIn("ALLOWED_SHARP_NEEDS_REASON@print_plan.edges[E-01].allowed_sharp_reason", issue_ids(issues))

    def test_support_allowed_without_contact_class_rejected(self) -> None:
        broken = clone(_PRINT_PLAN)
        broken["support_rules"][0]["disposition"] = "SUPPORT_ALLOWED"
        issues = V.validate_print_plan(broken)
        self.assertIn(
            "SUPPORT_ALLOWED_NEEDS_CONTACT_CLASS@print_plan.support_rules[S-01].allowed_contact_class",
            issue_ids(issues),
        )

    def test_fk_related_feature_id_missing(self) -> None:
        broken = clone(_PRINT_PLAN)
        broken["geometry_rules"][0]["related_feature_ids"] = ["F-GHOST"]
        issues = V.validate_print_plan(broken, feature_ids={"F01": {}})
        self.assertIn("FK_MISSING@print_plan.geometry_rules[G-01].related_feature_ids[0]", issue_ids(issues))

    def test_duplicate_edge_ids_rejected(self) -> None:
        broken = clone(_PRINT_PLAN)
        broken["edges"].append(clone(broken["edges"][0]))
        issues = V.validate_print_plan(broken)
        self.assertIn("DUPLICATE_ID@print_plan.edges", issue_ids(issues))

    def test_contracts_naming_different_jobs_are_reported(self) -> None:
        """A project assembled from two jobs' contracts passed `validate`
        cleanly: four files bound to one job under a job_state naming another,
        every hash and revision internally consistent. Only reading them side by
        side catches it, which is what `status` is for.
        """
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            job_state = clone(_JOB_STATE)
            job_state["job_id"] = "this-job"
            dimensions = clone(_DIMENSIONS)
            dimensions["job_id"] = "some-other-job"
            _write_project(project_dir, job_state=job_state, dimensions=dimensions)

            rows = S.compute_status(project_dir)

            mismatch = [r for r in rows if r["status"] == "MISMATCH"]
            self.assertEqual(1, len(mismatch), rows)
            self.assertIn("some-other-job", mismatch[0]["detail"])
            self.assertEqual(1, S.exit_code(rows), "a split-brain project must not pass")

    def test_one_job_across_every_contract_is_silent(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            _write_project(project_dir, job_state=clone(_JOB_STATE),
                           dimensions=clone(_DIMENSIONS))

            rows = S.compute_status(project_dir)

            self.assertEqual([], [r for r in rows if r["status"] == "MISMATCH"], rows)

    def test_a_route_that_does_not_exist_is_rejected(self) -> None:
        """`PROFILE` was defined and never checked. An orchestrator wrote
        `COMPACT` -- retired long before -- and `validate` passed it. The profile
        decides which phases run, so an unknown one means nobody knows what the
        job is meant to do."""
        job = clone(_JOB_STATE)
        job["profile"] = "COMPACT"

        issues = V.validate_contract_header(job, key="job_state", where="job_state")

        self.assertIn("BAD_ENUM@job_state.profile", issue_ids(issues))

    def test_each_real_route_validates(self) -> None:
        for profile in sorted(V.PROFILE):
            with self.subTest(profile=profile):
                job = clone(_JOB_STATE)
                job["profile"] = profile
                issues = V.validate_contract_header(job, key="job_state", where="job_state")
                self.assertEqual([], [i for i in issues if i.severity == "error"], issues)

    def test_a_direct_jobs_plan_filename_is_recognised(self) -> None:
        """A DIRECT job has only `print_plan_checks.json`. While that was not a
        canonical name, `validate --require all` could never exit zero there --
        and the verifier is instructed to require exit zero."""
        self.assertIn("print_plan_checks.json", V.CANONICAL_FILENAMES["print_plan"])

    def test_the_orchestrator_may_own_a_direct_jobs_dimensions(self) -> None:
        """Under DIRECT nothing is recovered from evidence, so the orchestrator
        transcribes the stated numbers. Forcing `owner: metrologist` there would
        make the provenance field lie, which is the one thing it records."""
        sheet = clone(_DIMENSIONS)
        sheet["owner"] = "orchestrator"

        issues = V.validate_contract_header(sheet, key="dimensions", where="dimensions")

        self.assertEqual([], [i for i in issues if i.severity == "error"], issues)

    def test_an_unrelated_owner_is_still_rejected(self) -> None:
        sheet = clone(_DIMENSIONS)
        sheet["owner"] = "cad-designer"

        issues = V.validate_contract_header(sheet, key="dimensions", where="dimensions")

        self.assertIn("BAD_ENUM@dimensions.owner", issue_ids(issues))

    def test_the_shipped_template_may_own_a_direct_jobs_plan(self) -> None:
        built = clone(_PRINT_PLAN)
        built["owner"] = "builtin-direct-template"

        issues = V.validate_print_plan(built)

        self.assertEqual([], [i for i in issues if i.severity == "error"], issues)

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

    def test_two_references_report_ambiguity_instead_of_binding_the_first(self) -> None:
        """A multi-part job has several references; `reference_sha256` is one
        hash. Answering the freshness question from whichever happened to be
        first would pass a job whose *other* reference changed.
        """
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            # The first reference still matches what the plan bound. The second
            # does not -- so scanning for the first match reports a clean pass.
            body_hash, _, _ = _write_box_stl(project_dir / "reference_bar.stl", (62.0, 11.7, 24.0))
            _write_box_stl(project_dir / "reference_lid.stl", (62.0, 11.7, 3.0))

            manifest = clone(_ARTIFACT_MANIFEST)
            lid = clone(manifest["artifacts"][0])
            lid["id"] = "reference-lid"
            lid["path"] = "reference_lid.stl"
            manifest["artifacts"].append(lid)
            print_plan = clone(_PRINT_PLAN)
            print_plan["reference_sha256"] = body_hash
            _write_project(project_dir, print_plan=print_plan, artifact_manifest=manifest)

            rows = S.compute_status(project_dir)

            ambiguous = [r for r in rows if r["status"] == "AMBIGUOUS"]
            self.assertEqual(1, len(ambiguous), rows)
            self.assertIn("reference-lid", ambiguous[0]["detail"])
            self.assertEqual(
                1,
                S.exit_code(rows),
                "an unbindable reference must stop the pipeline, not read as OK",
            )
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
            allowed_header = (
                V.JOB_STATE_HEADER_FIELDS if key == "job_state" else None
            )
            scalars = "\n".join(
                f"{k}: {'true' if v is True else 'false' if v is False else v}"
                for k, v in data.items()
                if isinstance(v, (str, int, float, bool))
                and (allowed_header is None or k in allowed_header)
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
        # only if trivially available" instruction.
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
        # The designer's self-check. A project that reached verification has one,
        # and `--require` can name it now, so a "full project" fixture without it
        # is not full -- it is the shape that made the verifier's own checklist
        # step unable to confirm the evidence it distrusts was even present.
        (project_dir / "candidate_readiness.md").write_text(
            "\n".join([
                "---",
                "contract: candidate-readiness",
                "contract_version: 4",
                "job_id: demo",
                "revision: 1",
                "owner: cad-designer",
                "updated_utc: 1970-01-01T00:00:00Z",
                "---",
                "",
                "# Candidate readiness",
                "",
            ]), encoding="utf-8")
        # The PRINT_PREP pair, and the same argument: a project that has been
        # handed over has both, and they are the last gate before it is. The
        # print engineer states the manufacturing evidence is complete and the
        # verifier reads that file to decide. Neither could be checked at all
        # until they were registered, so a fixture without them is not full.
        (project_dir / "final_print_prep.md").write_text("\n".join([
            "---",
            "contract: final-print-prep",
            "contract_version: 4",
            "job_id: demo",
            "owner: print-engineer",
            "status: READY_FOR_REVIEW",
            f"candidate_stl_sha256: {candidate_hash}",
            "print_plan_revision: 1",
            "verification_report_revision: 1",
            "updated_utc: 1970-01-01T00:00:00Z",
            "---",
            "",
            "# Final print preparation",
            "",
        ]), encoding="utf-8")
        (project_dir / "final_prep_review.md").write_text("\n".join([
            "---",
            "contract: final-prep-review",
            "contract_version: 4",
            "job_id: demo",
            "owner: verifier",
            "status: FINAL_PRINT_PASS",
            f"candidate_stl_sha256: {candidate_hash}",
            "print_plan_revision: 1",
            "final_print_prep_sha256: "
            f"{C.sha256_file(project_dir / 'final_print_prep.md')}",
            "updated_utc: 1970-01-01T00:00:00Z",
            "---",
            "",
            "# Final prep review",
            "",
        ]), encoding="utf-8")
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

    def _corrupt_final_prep(self, project_dir: Path, field: str, value: str) -> list[str]:
        """Rewrite one header field of `final_prep_review.md` and revalidate."""
        self._build_full_project(project_dir)
        path = project_dir / "final_prep_review.md"
        lines = [f"{field}: {value}" if line.startswith(f"{field}:") else line
                 for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertIn(f"{field}: {value}", lines, "the field to corrupt must exist")
        path.write_text("\n".join(lines), encoding="utf-8")
        receipt, _ = R.build_validate_receipt(project_dir, timestamp=None, argv=[])
        return receipt["error_ids"]

    def test_a_final_prep_verdict_outside_the_enum_is_rejected(self) -> None:
        """`status` is the whole contract: it decides whether a part is handed
        over. Until these two were registered, a review could say anything at
        all -- `PASS`, `ok`, a typo for a reject -- and validate clean, because
        no validator had ever heard of the file."""
        with tempfile.TemporaryDirectory() as raw_dir:
            errors = self._corrupt_final_prep(Path(raw_dir), "status", "PASS")
            self.assertIn("BAD_ENUM@final_prep_review.status", errors)

    def test_a_final_prep_binding_hash_must_be_a_hash(self) -> None:
        """The review binds to the prep file it reviewed. A placeholder there
        binds to nothing, and reads exactly like a binding that holds."""
        with tempfile.TemporaryDirectory() as raw_dir:
            errors = self._corrupt_final_prep(Path(raw_dir), "final_print_prep_sha256", "TBD")
            self.assertIn("BAD_HASH@final_prep_review.final_print_prep_sha256", errors)

    def test_a_final_prep_bound_revision_must_be_an_integer(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            errors = self._corrupt_final_prep(Path(raw_dir), "print_plan_revision", "latest")
            self.assertIn("MISSING_FIELD@final_prep_review.print_plan_revision", errors)

    def test_the_final_prep_pair_may_not_swap_owners(self) -> None:
        """The verifier writing the print engineer's evidence, or the reverse, is
        the one thing this phase exists to prevent: the review is worth something
        only because a second party wrote it."""
        with tempfile.TemporaryDirectory() as raw_dir:
            errors = self._corrupt_final_prep(Path(raw_dir), "owner", "print-engineer")
            self.assertIn("BAD_ENUM@final_prep_review.owner", errors)

    def test_correct_final_prep_bindings_recompute_clean(self) -> None:
        """A binding whose declared hash matches the current artifact passes: the
        review's candidate_stl_sha256 and final_print_prep_sha256, recomputed
        from the bytes on disk, equal what it declared -- so no BINDING_STALE.
        """
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            self._build_full_project(project_dir)
            receipt, _ = R.build_validate_receipt(project_dir, timestamp=None, argv=[])
            self.assertEqual([], [e for e in receipt["error_ids"] if e.startswith("BINDING_STALE")])
            self.assertEqual("PASS", receipt["results"]["overall"], receipt["issues"])

    def test_a_final_prep_review_bound_to_a_stale_candidate_stl_is_rejected(self) -> None:
        """The review signs off a specific candidate STL. A well-formed hash that
        no longer matches the current candidate binds the sign-off to a stale or
        wrong STL and passes every format check -- so it is recomputed from the
        bytes on disk, the way the manifest's HASH_MISMATCH is.
        """
        with tempfile.TemporaryDirectory() as raw_dir:
            errors = self._corrupt_final_prep(Path(raw_dir), "candidate_stl_sha256", HASH_A)
            self.assertIn("BINDING_STALE@final_prep_review.candidate_stl_sha256", errors)

    def test_a_final_prep_review_bound_to_a_stale_prep_file_is_rejected(self) -> None:
        """The review binds final_print_prep_sha256 to the prep contract it
        reviewed. A well-formed hash that does not match the current
        final_print_prep.md bytes reviews a version that is no longer there.
        """
        with tempfile.TemporaryDirectory() as raw_dir:
            errors = self._corrupt_final_prep(Path(raw_dir), "final_print_prep_sha256", HASH_B)
            self.assertIn("BINDING_STALE@final_prep_review.final_print_prep_sha256", errors)

    def test_a_well_formed_binding_hash_still_gets_the_format_check_not_the_recompute(self) -> None:
        """A malformed hash is BAD_HASH (format), never BINDING_STALE: the
        recompute is skipped for it so a single field carries one clear finding,
        not two.
        """
        with tempfile.TemporaryDirectory() as raw_dir:
            errors = self._corrupt_final_prep(Path(raw_dir), "candidate_stl_sha256", "TBD")
            self.assertIn("BAD_HASH@final_prep_review.candidate_stl_sha256", errors)
            self.assertNotIn("BINDING_STALE@final_prep_review.candidate_stl_sha256", errors)

    def test_final_print_prep_bound_to_a_stale_candidate_stl_is_rejected(self) -> None:
        """The print engineer's own contract also binds the candidate STL; the
        recompute holds it to the current candidate exactly as it does the review.
        """
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            self._build_full_project(project_dir)
            path = project_dir / "final_print_prep.md"
            lines = [
                f"candidate_stl_sha256: {HASH_A}"
                if line.startswith("candidate_stl_sha256:") else line
                for line in path.read_text(encoding="utf-8").splitlines()
            ]
            path.write_text("\n".join(lines), encoding="utf-8")
            receipt, _ = R.build_validate_receipt(project_dir, timestamp=None, argv=[])
            self.assertIn(
                "BINDING_STALE@final_print_prep.candidate_stl_sha256", receipt["error_ids"]
            )

    def test_final_prep_binding_fails_closed_when_candidate_row_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            self._build_full_project(project_dir)
            manifest_path = project_dir / "artifact_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["artifacts"] = [
                row for row in manifest["artifacts"] if row["role"] != "candidate"
            ]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            receipt, _ = R.build_validate_receipt(project_dir, timestamp=None, argv=[])
            self.assertTrue(any(error.startswith("BINDING_UNRESOLVED@")
                                for error in receipt["error_ids"]), receipt["error_ids"])

    def test_final_prep_binding_fails_closed_when_candidate_file_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            self._build_full_project(project_dir)
            (project_dir / "candidate_01.stl").unlink()
            receipt, _ = R.build_validate_receipt(project_dir, timestamp=None, argv=[])
            self.assertTrue(any(error.startswith("BINDING_UNRESOLVED@")
                                for error in receipt["error_ids"]), receipt["error_ids"])

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

    def test_consequential_job_with_a_pass_report_validates_cleanly(self) -> None:
        """Consequence adds the bounded safety review; it does not ban verifier PASS."""
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            job_state = clone(_JOB_STATE)
            job_state["consequence"] = "CONSEQUENTIAL"
            _write_project(project_dir, as_markdown=True, job_state=job_state,
                           verification_report=clone(_VERIFICATION_REPORT))
            receipt, _project = R.build_validate_receipt(project_dir, timestamp="fixed", argv=[])
            self.assertEqual([], receipt["error_ids"], receipt["issues"])
            self.assertEqual("PASS", receipt["results"]["overall"])

    def test_inconsequential_jobs_may_pass(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            job_state = clone(_JOB_STATE)
            job_state["consequence"] = "INCONSEQUENTIAL"
            _write_project(project_dir, as_markdown=True, job_state=job_state,
                           verification_report=clone(_VERIFICATION_REPORT))
            receipt, _project = R.build_validate_receipt(project_dir, timestamp="fixed", argv=[])
            self.assertEqual([], receipt["error_ids"])

    def test_unknown_consequence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            job_state = clone(_JOB_STATE)
            job_state["consequence"] = "UNSAFE"
            _write_project(project_dir, as_markdown=True, job_state=job_state)
            receipt, _project = R.build_validate_receipt(project_dir, timestamp="fixed", argv=[])
            self.assertIn("BAD_ENUM@job_state.consequence", receipt["error_ids"])

    def test_job_state_requires_consequence(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            job_state = clone(_JOB_STATE)
            del job_state["consequence"]
            _write_project(project_dir, as_markdown=True, job_state=job_state)
            receipt, _project = R.build_validate_receipt(project_dir, timestamp="fixed", argv=[])
            self.assertIn("MISSING_FIELD@job_state.consequence", receipt["error_ids"])

    def test_job_state_rejects_legacy_risk_and_unknown_frontmatter_fields(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            project_dir = Path(raw_dir)
            job_state = clone(_JOB_STATE)
            _write_project(project_dir, as_markdown=True, job_state=job_state)
            path = project_dir / "job_state.md"
            text = path.read_text(encoding="utf-8")
            path.write_text(
                text.replace(
                    "---\n\n# job_state",
                    "risk_class: R2_ENGINEERING_REVIEW\nlegacy_reviewer: old-agent\n---\n\n# job_state",
                ),
                encoding="utf-8",
            )
            receipt, _project = R.build_validate_receipt(project_dir, timestamp="fixed", argv=[])
            self.assertIn("UNKNOWN_FIELD@job_state.risk_class", receipt["error_ids"])
            self.assertIn("UNKNOWN_FIELD@job_state.legacy_reviewer", receipt["error_ids"])
            self.assertEqual("FAIL", receipt["results"]["job_state"])

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
# plan: `uv run --project <skill> --frozen python -m team_tools.contracts <cmd> <path>`).
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    unittest.main()
