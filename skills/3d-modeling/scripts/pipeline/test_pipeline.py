#!/usr/bin/env python3
"""Iteration 1: the DIRECT vertical slice, and the defects it must still catch.

Every mutation below is applied to the *mesh*, after a correct build, so the test
asks the question that matters: does the contract catch a part that is wrong in a
way the builder did not know about? A test that mutates the parameters instead
would only prove the builder is consistent with itself.
"""
from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

import trimesh

from . import analysis, commission, contract as C, intent, runner, safety, screening
from . import status, templates as T

CLIP = {"bore_d": 12.0, "wall": 3.0, "height": 9.0, "mouth_gap": 9.0,
        "flange_w": 40.0, "flange_d": 22.0, "flange_t": 5.0, "screw_d": 4.8}
RING = {"hole_d": 60.0, "lip_w": 5.0, "panel_t": 18.0, "lip_t": 3.0,
        "wall": 2.0, "chamfer": 1.0}


def _request(out: Path, *, template="c_clip", params=None, consequence="INCONSEQUENTIAL",
             **kw) -> runner.JobRequest:
    return runner.JobRequest(
        job_id="t", brief_path=out / "brief.md", template=template,
        parameters=dict(params or CLIP), stated=frozenset({"bore_d"}),
        consequence=consequence, out_dir=out, updated_utc="1970-01-01T00:00:00Z",
        render=False, **kw)


def _run(out: Path, **kw):
    return runner.run(_request(out, **kw))


def _contract(out: Path, template="c_clip", params=None) -> C.Contract:
    return runner._contract_from(T.get(template), _request(out, template=template, params=params))


def _measure(mesh: trimesh.Trimesh, contract: C.Contract, tmp: Path):
    path = tmp / "mutant.stl"
    mesh.export(path)
    ctx = analysis.load(path)
    return ctx, commission.run(ctx, contract), screening.run(ctx, contract)


class VerticalSliceTest(unittest.TestCase):
    def test_a_clean_trimesh_job_runs_end_to_end_with_no_llm_calls(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result = _run(out)

            self.assertTrue(result.ok, result.message)
            self.assertEqual(0, result.llm_calls)
            self.assertEqual("COMMISSIONED", result.final_status["final_status"])
            for name in ("intent_manifest", "model_contract", "artifact_manifest",
                         "commission_report", "final_status"):
                self.assertIn(name, result.artifacts, f"missing {name}")

    def test_the_stl_is_loaded_exactly_once(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result = _run(out)
            report = json.loads((out / "commission_report.json").read_text(encoding="utf-8"))
            self.assertEqual(1, report["mesh_loads"])
            _ = result

    def test_a_trimesh_job_never_imports_build123d(self) -> None:
        """10.7 s against 1.5 s measured. A trimesh-only job that loaded the CAD
        kernel would spend seven times its own build time on an import it never
        calls."""
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            (out / "brief.md").write_text("clip\n", encoding="utf-8")
            (out / "job.json").write_text(json.dumps({
                "job_id": "t", "template": "c_clip", "consequence": "INCONSEQUENTIAL",
                "parameters": CLIP, "updated_utc": "1970-01-01T00:00:00Z"}), encoding="utf-8")
            probe = (
                "import sys, runpy;"
                "sys.argv=['design-tool','run-job',%r,'--no-render'];"
                "import pipeline.cli as c;"
                "code=c.main(sys.argv[1:]);"
                "print('BUILD123D_LOADED', 'build123d' in sys.modules)" % str(out))
            done = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                                  text=True, cwd=str(Path(__file__).resolve().parents[1]))
            self.assertIn("BUILD123D_LOADED False", done.stdout, done.stdout + done.stderr)

    def test_step_is_written_only_when_the_contract_asks(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            _run(out, template="trim_ring", params=RING)
            self.assertFalse((out / "candidate.step").exists(),
                             "STEP must not appear unrequested")

        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result = _run(out, template="trim_ring", params=RING, step=True)
            self.assertTrue((out / "candidate.step").is_file())
            self.assertTrue(result.ok, result.message)

    def test_a_trimesh_template_refuses_a_step_it_cannot_produce(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result = _run(Path(raw), step=True)
            self.assertFalse(result.ok)
            self.assertEqual("build", result.stage)
            self.assertIn("STL only", result.message)


class PreflightTest(unittest.TestCase):
    """Five properties, checked before geometry is paid for."""

    def _one(self, **overrides) -> C.Feature:
        base = {"feature_id": "f", "kind": "section_area", "provenance": "brief",
                "expectation": {"at": {"z": 1.0}, "value_mm2": 10.0},
                "tolerance": {"abs": 1.0}, "verified_by": "section_area",
                "on_unrunnable": "ESCALATE"}
        base.update(overrides)
        return C.Feature(**base)

    def _contract_with(self, feature: C.Feature) -> C.Contract:
        return C.Contract(
            job_id="t", template="c_clip", template_version="1.0.0", domain_id="d",
            backend="trimesh-manifold", parameters={}, features=(feature,),
            expected_bbox_mm={"x": 1, "y": 1, "z": 1}, bbox_tolerance_mm=0.5,
            expected_bodies=1, orientation={}, material={}, modifiers=(),
            minimum_coverage=1.0, step_required=False,
            consequence="INCONSEQUENTIAL", updated_utc="1970-01-01T00:00:00Z")

    def test_each_missing_property_is_rejected(self) -> None:
        for field, empty in (("provenance", ""), ("expectation", {}),
                             ("tolerance", {}), ("verified_by", "")):
            with self.subTest(missing=field):
                problems = C.preflight(self._contract_with(self._one(**{field: empty})),
                                       known_checks=commission.KNOWN_CHECKS)
                self.assertTrue(any(field in p for p in problems), problems)

    def test_skip_is_not_a_legal_answer_to_a_check_that_cannot_run(self) -> None:
        """A candidate shipped 31% too thick while three checks reported SKIPPED,
        nothing counted them, and the gate exited zero."""
        problems = C.preflight(self._contract_with(self._one(on_unrunnable="skip")),
                               known_checks=commission.KNOWN_CHECKS)
        self.assertTrue(any("on_unrunnable" in p for p in problems), problems)

    def test_a_check_that_does_not_exist_is_rejected(self) -> None:
        problems = C.preflight(self._contract_with(self._one(verified_by="vibes")),
                               known_checks=commission.KNOWN_CHECKS)
        self.assertTrue(any("names no check" in p for p in problems), problems)

    def test_a_bare_tolerance_is_rejected(self) -> None:
        problems = C.preflight(self._contract_with(self._one(tolerance={"value": 1.0})),
                               known_checks=commission.KNOWN_CHECKS)
        self.assertTrue(any("abs" in p for p in problems), problems)

    def test_preflight_runs_before_any_geometry_exists(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            request = _request(out)
            template = T.get("c_clip")
            broken = runner._contract_from(template, request)
            broken = C.Contract(**{**broken.__dict__,
                                   "features": (self._one(verified_by="vibes"),)})
            self.assertTrue(C.preflight(broken, known_checks=commission.KNOWN_CHECKS))
            self.assertFalse((out / "candidate.stl").exists(),
                             "no build may have started")


class RoutingTest(unittest.TestCase):
    def test_out_of_domain_is_not_direct_and_names_the_bound(self) -> None:
        decision = intent.select(requested_template="c_clip",
                                 parameters={**CLIP, "bore_d": 60.0},
                                 external_geometry=False, ambiguities=())
        self.assertNotEqual("DIRECT", decision.route)
        reason = " ".join(r for c in decision.candidates for r in c.reasons)
        self.assertIn("bore_d=60", reason)
        self.assertIn("[4, 40]", reason)

    def test_out_of_domain_does_not_default_to_fitted(self) -> None:
        """A novel shape outside every certified domain often has no external
        object to measure, so calling it 'fitted' would be wrong about the work."""
        decision = intent.select(requested_template="c_clip",
                                 parameters={**CLIP, "bore_d": 60.0},
                                 external_geometry=False, ambiguities=())
        self.assertEqual("FULL", decision.route)

    def test_external_geometry_routes_to_fitted(self) -> None:
        decision = intent.select(requested_template="c_clip", parameters=CLIP,
                                 external_geometry=True, ambiguities=())
        self.assertEqual("FITTED", decision.route)

    def test_a_violated_constraint_is_recorded_by_name(self) -> None:
        decision = intent.select(requested_template="c_clip",
                                 parameters={**CLIP, "mouth_gap": 13.0},
                                 external_geometry=False, ambiguities=())
        reason = " ".join(r for c in decision.candidates for r in c.reasons)
        self.assertIn("mouth_gap < bore_d", reason)

    def test_every_candidate_and_its_reason_reaches_the_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            _run(out)
            manifest = json.loads((out / "intent_manifest.json").read_text(encoding="utf-8"))
            decision = manifest["route_decision"]
            self.assertEqual("DIRECT", decision["route"])
            self.assertTrue(decision["condition"])
            self.assertEqual({"c_clip", "trim_ring"},
                             {c["template"] for c in decision["candidates"]})
            for candidate in decision["candidates"]:
                self.assertTrue(candidate["reasons"], candidate)

    def test_chosen_parameters_are_not_attributed_to_the_user(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            _run(out)
            manifest = json.loads((out / "intent_manifest.json").read_text(encoding="utf-8"))
            rows = {r["name"]: r for r in manifest["requirements"]}
            self.assertEqual("user", rows["bore_d"]["source"])
            self.assertEqual("designer", rows["wall"]["source"],
                             "an unstated parameter must never claim the user's authority")


class RegressionCorpusTest(unittest.TestCase):
    """The archived defects, and the synthetic ones screening is meant to catch."""

    def _clean(self, tmp: Path):
        from .backends.trimesh_manifold import build_c_clip
        part, _ = build_c_clip(CLIP)
        return part

    def test_a_feature_deleted_from_the_geometry_still_fails(self) -> None:
        """The countersink lesson, generalized and made mutation-proof.

        The historical defect removed a feature from the template while every
        caller still asked for it; the expectation vanished with the geometry
        because one parameter drove both. Here the contract is upstream, so
        filling the screw bore leaves the expectation standing and the check
        fails -- which is the property the whole redesign is for.

        Screening is *not* asserted to catch this. A filled bore is smooth and
        plausible; absence is the contract's job.
        """
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            contract = _contract(tmp)
            part = self._clean(tmp)
            plug = trimesh.creation.cylinder(radius=CLIP["screw_d"] / 2.0 - 0.01,
                                             height=CLIP["flange_t"], sections=96)
            plug.apply_translation([CLIP["flange_w"] * 0.2, CLIP["flange_d"] / 2.0,
                                    CLIP["flange_t"] / 2.0])
            filled = trimesh.boolean.union([part, plug], engine="manifold")

            _, report, _ = _measure(filled, contract, tmp)

            bore = next(c for c in report["checks"] if c["check_id"] == "feature-screw-bore")
            self.assertIn(bore["result"], ("FAIL", "ESCALATE"), bore)
            self.assertEqual("FAIL", report["verdict"])

    def test_an_edge_open_cut_through_the_flange_fails(self) -> None:
        """The archived slotted-flange defect: a cutter tall enough to reach the
        mounting plate and open to its edge. Not a ring, so counts and bounding
        boxes are blind; the part stays one component, so connectivity is blind
        too. Only the section area sees it."""
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            contract = _contract(tmp)
            slot = trimesh.creation.box(extents=(6.0, 30.0, CLIP["flange_t"] * 3))
            slot.apply_translation([CLIP["flange_w"] / 2.0, CLIP["flange_d"],
                                    CLIP["flange_t"] / 2.0])
            slotted = trimesh.boolean.difference([self._clean(tmp), slot], engine="manifold")

            _, report, _ = _measure(slotted, contract, tmp)

            flange = next(c for c in report["checks"] if c["check_id"] == "feature-flange-section")
            self.assertEqual("FAIL", flange["result"], flange)

    def test_an_undeclared_post_in_the_channel_is_caught(self) -> None:
        """The 4 mm post that passed twenty-seven green checks, an exact bounding
        box, a watertight verdict and a matching bed-contact area."""
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            contract = _contract(tmp)
            # Rooted 1 mm into the flange so it genuinely fuses. A post merely
            # resting on the floor stays a separate body and the component screen
            # catches it -- the harder case, and the one that actually shipped, is
            # material continuous with the part, where only a declared void sees it.
            post = trimesh.creation.cylinder(radius=2.0, height=CLIP["height"] + 1.0,
                                             sections=64)
            post.apply_translation([CLIP["flange_w"] / 2.0, CLIP["flange_d"] / 2.0,
                                    CLIP["flange_t"] - 1.0 + (CLIP["height"] + 1.0) / 2.0])
            posted = trimesh.boolean.union([self._clean(tmp), post], engine="manifold")

            ctx, report, screen = _measure(posted, contract, tmp)

            self.assertEqual(1, len(ctx.components),
                             "fused: the component screen cannot see this one")
            void = next(c for c in report["checks"] if c["check_id"] == "feature-channel-void")
            self.assertEqual("FAIL", void["result"],
                             "material standing in a declared-empty channel")
            _ = screen

    def test_a_stray_fragment_is_caught_by_screening_alone(self) -> None:
        """Boolean debris: a solid nobody asked for, too small to be the part and
        too disconnected to disturb any declared measurement. No contract row
        names it, which is the whole reason screening exists."""
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            contract = _contract(tmp)
            speck = trimesh.creation.box(extents=(1.2, 1.2, 1.2))
            speck.apply_translation([2.0, 2.0, 0.6])
            debris = trimesh.util.concatenate([self._clean(tmp), speck])

            ctx, report, screen = _measure(debris, contract, tmp)

            self.assertEqual("ANOMALY", screen["overall"], screen)
            components = next(d for d in screen["detectors"] if d["detector"] == "components")
            self.assertEqual("ANOMALY", components["result"], components)
            _ = ctx, report

    def test_screening_says_plainly_that_it_cannot_prove_absence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            _, _, screen = _measure(self._clean(tmp), _contract(tmp), tmp)
            self.assertIn("cannot prove", screen["note"])
            self.assertEqual(["z"], screen["axes_screened"])
            self.assertEqual({"x", "y"}, set(screen["axes_not_screened"]))


class RepairTest(unittest.TestCase):
    def test_vertex_merging_alone_is_not_an_escalation(self) -> None:
        """An STL stores three unshared vertices per triangle, so the merge ratio
        is about 6:1 on every file ever exported. Escalating on it would fire on
        every job, and an escalation that always fires is one nobody reads."""
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            _run(out)
            report = json.loads((out / "commission_report.json").read_text(encoding="utf-8"))
            repair = next(c for c in report["checks"] if c["check_id"] == "repair")
            self.assertEqual("PASS", repair["result"])
            self.assertIn("STL format", repair["reason"])
            self.assertEqual([], report["repair_actions"])


class SafetyTest(unittest.TestCase):
    REVIEWER = {"model_snapshot": "m", "prompt_hash": "p", "policy_version": "1",
                "reasoning_settings": "none", "inference_config": "{}",
                "image_preprocessing": "none"}

    def _job(self, out: Path, response):
        seen = []

        def call(packet):
            seen.append(packet)
            return response
        result = runner.run(_request(out, consequence="CONSEQUENTIAL",
                                     safety_call=call, reviewer=self.REVIEWER))
        return result, seen

    def test_exactly_one_bounded_call_and_it_gates_the_status(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result, seen = self._job(Path(raw), {
                "decision": "PASS", "failure_modes": [], "safety_concerns": [],
                "missing_evidence": [], "required_actions": [], "summary": "ok"})
            self.assertEqual(1, len(seen))
            self.assertEqual(1, result.llm_calls)
            self.assertEqual("PASS", result.final_status["safety_verification"])

    def test_block_prevents_completion(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result, _ = self._job(Path(raw), {
                "decision": "BLOCK", "failure_modes": ["fracture"], "safety_concerns": [],
                "missing_evidence": [], "required_actions": [], "summary": "no"})
            self.assertEqual("FAILED", result.final_status["final_status"])

    def test_needs_more_evidence_stops_the_job(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result, _ = self._job(Path(raw), {
                "decision": "NEEDS_MORE_EVIDENCE", "failure_modes": [],
                "safety_concerns": [], "missing_evidence": ["load direction"],
                "required_actions": [], "summary": "unclear"})
            self.assertEqual("NEEDS_MORE_EVIDENCE", result.final_status["final_status"])

    def test_a_consequential_job_cannot_complete_without_a_reviewer(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result = runner.run(_request(Path(raw), consequence="CONSEQUENTIAL"))
            self.assertFalse(result.ok)
            self.assertEqual("safety", result.stage)

    def test_stage_one_does_not_see_the_normal_verifier(self) -> None:
        """Showing a second opinion the first one is anchoring by construction."""
        with tempfile.TemporaryDirectory() as raw:
            _, seen = self._job(Path(raw), {
                "decision": "PASS", "failure_modes": [], "safety_concerns": [],
                "missing_evidence": [], "required_actions": [], "summary": "ok"})
            self.assertNotIn("verification_report", seen[0].payload)
            self.assertEqual(1, seen[0].payload["stage"])

    def test_an_inconsequential_job_never_calls_the_reviewer(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            called = []
            result = runner.run(_request(Path(raw), safety_call=lambda p: called.append(p)))
            self.assertEqual([], called)
            self.assertEqual(0, result.llm_calls)

    def test_cache_identity_separates_reviewers_that_differ_anywhere(self) -> None:
        packet = safety.Packet(stage=1, payload={"a": 1})
        base = safety.cache_identity(packet, reviewer=self.REVIEWER)
        for key in ("model_snapshot", "prompt_hash", "policy_version",
                    "reasoning_settings", "inference_config", "image_preprocessing"):
            with self.subTest(differs=key):
                other = {**self.REVIEWER, key: "changed"}
                self.assertNotEqual(base, safety.cache_identity(packet, reviewer=other))


class ManufacturingTest(unittest.TestCase):
    def test_a_deferred_predicate_blocks_verified_and_says_so(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result = runner.run(_request(out, modifiers=("supports",)))
            report = json.loads((out / "manufacturing_report.json").read_text(encoding="utf-8"))

            self.assertEqual("DEFERRED", report["overall"])
            self.assertIsNone(report["slicer_adapter"])
            self.assertEqual("COMMISSIONED", result.final_status["final_status"])
            self.assertIn("not verified", result.final_status["allowed_claim"])

    def test_no_modifiers_writes_no_manufacturing_report(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            _run(out)
            self.assertFalse((out / "manufacturing_report.json").exists())


class IndependenceTest(unittest.TestCase):
    def test_expectations_and_backends_share_no_module(self) -> None:
        """If geometry and expectation share a helper for a critical dimension, a
        bug moves both and they agree while the part is wrong."""
        import ast

        root = Path(__file__).resolve().parent
        tree = ast.parse((root / "expectations.py").read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
        self.assertEqual(set(), {m for m in imported if "backend" in m or "template" in m},
                         f"expectations.py must not import geometry: {imported}")

        for name in ("trimesh_manifold.py", "build123d_backend.py"):
            # By import graph, not by substring: the backends' own docstrings say
            # the word "expectations" while explaining that they are not a source
            # of them, and a grep-based rule would fail on the comment that
            # documents the rule.
            backend_tree = ast.parse((root / "backends" / name).read_text(encoding="utf-8"))
            names = set()
            for node in ast.walk(backend_tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    names.add(node.module)
                    names |= {a.name for a in node.names}
                elif isinstance(node, ast.Import):
                    names |= {a.name for a in node.names}
            self.assertNotIn("expectations", names,
                             f"{name} must not import the expectations it is measured against")

    def test_the_closed_forms_agree_with_the_built_solid(self) -> None:
        """Both sides derived independently; they must still land on the same
        number, or one of them is wrong."""
        from .backends.trimesh_manifold import build_c_clip
        from . import expectations as X

        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            part, _ = build_c_clip(CLIP)
            path = tmp / "clip.stl"
            part.export(path)
            ctx = analysis.load(path)

            for row in X.c_clip_expectations(CLIP):
                if row["kind"] != "section_area":
                    continue
                with self.subTest(feature=row["feature_id"]):
                    measured = ctx.section_area(float(row["at"]["z"]))
                    self.assertAlmostEqual(float(row["value_mm2"]), measured,
                                           delta=max(1.0, 0.005 * row["value_mm2"]))
            _ = math


class StatusTest(unittest.TestCase):
    def test_a_passing_safety_review_is_not_independent_verification(self) -> None:
        """It reviewed hazards, not whether the part matches the brief."""
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result = runner.run(_request(
                out, consequence="CONSEQUENTIAL",
                reviewer=SafetyTest.REVIEWER,
                safety_call=lambda p: {"decision": "PASS", "failure_modes": [],
                                       "safety_concerns": [], "missing_evidence": [],
                                       "required_actions": [], "summary": "ok"}))
            self.assertEqual("COMMISSIONED", result.final_status["final_status"])
            self.assertNotEqual("VERIFIED", result.final_status["final_status"])

    def test_screening_anomaly_stops_short_of_commissioned(self) -> None:
        clean = {"overall": "CLEAR"}
        anomaly = {"overall": "ANOMALY"}
        with tempfile.TemporaryDirectory() as raw:
            contract = _contract(Path(raw))
        report = {"verdict": "PASS"}
        artifact = {"contract_sha256": "a", "stl_sha256": "b", "source_sha256": "c"}
        ok = status.decide(contract=contract, commission_report=report, screening=clean,
                           manufacturing=None, safety=None, artifact=artifact,
                           verification=None, updated_utc="t")
        flagged = status.decide(contract=contract, commission_report=report, screening=anomaly,
                                manufacturing=None, safety=None, artifact=artifact,
                                verification=None, updated_utc="t")
        self.assertEqual("COMMISSIONED", ok["final_status"])
        self.assertEqual("NEEDS_MORE_EVIDENCE", flagged["final_status"])


if __name__ == "__main__":
    unittest.main()
