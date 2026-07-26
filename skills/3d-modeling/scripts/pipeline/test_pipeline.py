#!/usr/bin/env python3
"""Iteration 1: the DIRECT vertical slice, and the defects it must still catch.

Every mutation below is applied to the *mesh*, after a correct build, so the test
asks the question that matters: does the contract catch a part that is wrong in a
way the builder did not know about? A test that mutates the parameters instead
would only prove the builder is consistent with itself.
"""
from __future__ import annotations

import dataclasses
import json
import math
import tempfile
import unittest
from pathlib import Path

import trimesh

from . import analysis, commission, contract as C, fitted, intent, runner, safety, screening
from . import status, templates as T, verification
from . import witness as W

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


def _looked_at(packet):
    """A stand-in for the bounded visual call.

    Screening is uncalibrated (87.5% miss on fused undeclared material), so a
    clean job does not complete without somebody looking. Tests that want a
    finished job supply this; tests about the gate itself do not.
    """
    _ = packet
    return {"decision": "PASS", "defects": [], "unmet_requirements": [],
            "missing_evidence": [], "summary": "nothing undeclared visible"}


def _run(out: Path, **kw):
    return runner.run(_request(out, **kw))


def _run_looked(out: Path, **kw):
    return runner.run(_request(out, verify_call=_looked_at,
                               reviewer={"model_snapshot": "test"}, **kw))


def _contract(out: Path, template="c_clip", params=None) -> C.Contract:
    return runner._contract_from(T.get(template), _request(out, template=template, params=params))


def _clean_clip() -> trimesh.Trimesh:
    from .backends.trimesh_manifold import build_c_clip
    part, _ = build_c_clip(CLIP)
    return part


def _measure(mesh: trimesh.Trimesh, contract: C.Contract, tmp: Path):
    path = tmp / "mutant.stl"
    mesh.export(path)
    ctx = analysis.load(path)
    return ctx, commission.run(ctx, contract), screening.run(ctx, contract)


class VerticalSliceTest(unittest.TestCase):
    def test_a_clean_trimesh_job_runs_end_to_end_with_no_llm_calls(self) -> None:
        """Zero dispatches, and it finishes -- because the broad screen is
        calibrated. If it were not, the same job would stop at
        NEEDS_MORE_EVIDENCE and say nobody had looked; that behaviour has its own
        test in CalibrationTest."""
        from . import screening as S

        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result = _run(out)

            self.assertEqual(0, result.llm_calls)
            self.assertEqual("PASS", json.loads(
                (out / "commission_report.json").read_text(encoding="utf-8"))["verdict"])
            if S.CALIBRATED:
                self.assertTrue(result.ok, result.message)
                self.assertEqual("COMMISSIONED", result.final_status["final_status"])
            else:
                self.assertEqual("NEEDS_MORE_EVIDENCE",
                                 result.final_status["final_status"])
            for name in ("intent_manifest", "model_contract", "artifact_manifest",
                         "commission_report", "final_status"):
                self.assertIn(name, result.artifacts, f"missing {name}")
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
            result = _run_looked(out, template="trim_ring", params=RING, step=True)
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
            from . import templates as _T
            self.assertEqual(set(_T.registry()),
                             {c["template"] for c in decision["candidates"]},
                             "every certified template must appear as a candidate with a "
                             "reason, or the rationale is silent about what was not tried")
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
            result = _run_looked(out, modifiers=("supports",))
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
    def _decide(self, **kw):
        with tempfile.TemporaryDirectory() as raw:
            contract = _contract(Path(raw))
        base = {"contract": contract,
                "commission_report": {"verdict": "PASS",
                                      "witness": {"rendered": True}},
                "screening": {"overall": "CLEAR", "calibrated": True},
                "manufacturing": None, "safety": None, "verification": None,
                "artifact": {"contract_sha256": "a", "stl_sha256": "b",
                             "source_sha256": "c"},
                "updated_utc": "t"}
        return status.decide(**{**base, **kw})

    def test_a_passing_safety_review_is_not_independent_verification(self) -> None:
        """It reviewed hazards, not whether the part matches the brief.

        Decided at the status layer with a rendered witness, so the assertion is
        about safety-versus-verification rather than about whether a renderer
        happened to be installed."""
        with tempfile.TemporaryDirectory() as raw:
            base = _contract(Path(raw))
        consequential = C.Contract(**{**base.__dict__, "consequence": "CONSEQUENTIAL"})
        final = self._decide(contract=consequential,
                             safety={"decision": "PASS", "summary": "ok"})
        self.assertEqual("COMMISSIONED", final["final_status"])
        self.assertNotEqual("VERIFIED", final["final_status"])

    def test_a_consequential_job_nobody_could_see_does_not_complete(self) -> None:
        """The renderer is not on the core path, so this is the ordinary case.
        It used to pass in silence: the witness recorded 'unavailable' and no
        consumer read it."""
        with tempfile.TemporaryDirectory() as raw:
            base = _contract(Path(raw))
        consequential = C.Contract(**{**base.__dict__, "consequence": "CONSEQUENTIAL"})
        final = self._decide(contract=consequential,
                             commission_report={"verdict": "PASS",
                                                "witness": {"rendered": False}},
                             safety={"decision": "PASS", "summary": "ok"})
        self.assertEqual("NEEDS_MORE_EVIDENCE", final["final_status"])
        self.assertIn("saw no images", final["allowed_claim"])
        self.assertFalse(final["witnesses_rendered"])

    def test_screening_anomaly_stops_short_of_commissioned(self) -> None:
        clean = {"overall": "CLEAR"}
        anomaly = {"overall": "ANOMALY"}
        with tempfile.TemporaryDirectory() as raw:
            contract = _contract(Path(raw))
        report = {"verdict": "PASS"}
        artifact = {"contract_sha256": "a", "stl_sha256": "b", "source_sha256": "c"}
        ok = status.decide(contract=contract, commission_report=report,
                           screening={**clean, "calibrated": True},
                           manufacturing=None, safety=None, artifact=artifact,
                           verification=None, updated_utc="t")
        flagged = status.decide(contract=contract, commission_report=report, screening=anomaly,
                                manufacturing=None, safety=None, artifact=artifact,
                                verification=None, updated_utc="t")
        self.assertEqual("COMMISSIONED", ok["final_status"])
        self.assertEqual("NEEDS_MORE_EVIDENCE", flagged["final_status"])



class FailClosedTest(unittest.TestCase):
    """The property everything else rests on, which nothing was testing.

    A mutation run found six survivors: fail-open verdicts, dropped repair
    escalation, a removed coverage gate, an unpinned boolean engine, unenforced
    witness budgets and a disabled unit check all left the suite green. A
    property with no test is a comment.
    """

    def _feature(self, on_unrunnable: str) -> C.Feature:
        return C.Feature(feature_id="f", kind="section_area", provenance="p",
                         expectation={"at": {"z": 1.0}, "value_mm2": 1.0},
                         tolerance={"abs": 1.0}, verified_by="section_area",
                         on_unrunnable=on_unrunnable)

    def test_an_unrunnable_check_never_reports_pass(self) -> None:
        for mode, expected in (("ESCALATE", "ESCALATE"), ("FAIL", "FAIL")):
            with self.subTest(on_unrunnable=mode):
                self.assertEqual(expected,
                                 commission._verdict(self._feature(mode), ok=True, ran=False),
                                 "a check that did not run cannot pass, whatever ok says")

    def test_a_runnable_check_still_decides_on_the_measurement(self) -> None:
        self.assertEqual("PASS", commission._verdict(self._feature("ESCALATE"), ok=True, ran=True))
        self.assertEqual("FAIL", commission._verdict(self._feature("ESCALATE"), ok=False, ran=True))

    def test_a_measurement_that_did_not_happen_is_not_an_empty_cavity(self) -> None:
        """The one check whose failure has the same numeric signature as success:
        an engine that returned nothing reads as a perfectly clear void."""
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            contract = _contract(tmp)
            from .backends.trimesh_manifold import build_c_clip
            part, _ = build_c_clip(CLIP)
            path = tmp / "a.stl"
            part.export(path)
            ctx = analysis.load(path)

            original = trimesh.boolean.intersection
            try:
                trimesh.boolean.intersection = lambda *a, **k: None
                void = next(f for f in contract.features if f.kind == "void_region")
                check = commission._feature_check(ctx, void, 100.0)
            finally:
                trimesh.boolean.intersection = original

            self.assertFalse(check.ran)
            self.assertNotEqual("PASS", check.result)
            self.assertIn("returned nothing", check.reason)

    def test_every_boolean_names_manifold3d(self) -> None:
        """Automatic engine selection lets whichever engine happens to be
        importable decide the result, and a receipt that does not name the
        engine cannot be reproduced."""
        import re

        root = Path(__file__).resolve().parent
        pattern = re.compile(r"trimesh\.boolean\.\w+\(")
        for path in (root / "analysis.py", root / "backends" / "trimesh_manifold.py"):
            source = path.read_text(encoding="utf-8")
            for call in pattern.finditer(source):
                tail = source[call.end():call.end() + 220]
                with self.subTest(file=path.name, at=call.start()):
                    self.assertIn('engine="manifold"', tail,
                                  "every boolean must name its engine explicitly")

    def test_a_witness_over_budget_fails_the_build(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            contract = _contract(tmp)
            from .backends.trimesh_manifold import build_c_clip
            part, _ = build_c_clip(CLIP)
            path = tmp / "a.stl"
            part.export(path)
            ctx = analysis.load(path)

            original = W.MAX_SECONDS
            try:
                W.MAX_SECONDS = 0.0
                with self.assertRaises(W.BudgetExceeded):
                    W.generate(ctx, contract, tmp / "w", render=False)
            finally:
                W.MAX_SECONDS = original

    def test_coverage_below_the_minimum_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            base = _contract(tmp)
            ghost = C.Feature(
                feature_id="ghost", kind="section_area", provenance="p",
                expectation={"at": {"z": 999.0}, "value_mm2": 500.0},
                tolerance={"abs": 1.0}, verified_by="section_area", on_unrunnable="FAIL")
            contract = C.Contract(**{**base.__dict__, "features": base.features + (ghost,)})
            from .backends.trimesh_manifold import build_c_clip
            part, _ = build_c_clip(CLIP)
            _, report, _ = _measure(part, contract, tmp)
            self.assertEqual("FAIL", report["verdict"])

    def test_a_part_scaled_to_inches_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            contract = _contract(tmp)
            from .backends.trimesh_manifold import build_c_clip
            part, _ = build_c_clip(CLIP)
            part.apply_scale(1.0 / 25.4)
            _, report, _ = _measure(part, contract, tmp)
            units = next(c for c in report["checks"] if c["check_id"] == "unit_scale")
            self.assertEqual("FAIL", units["result"], units)


class DeterminismTest(unittest.TestCase):
    def test_two_runs_of_one_job_produce_identical_artifacts(self) -> None:
        """Durations used to be serialized into the manifest and the commission
        report, which made every artifact byte-unstable -- so the safety cache
        identity was a function of elapsed time and could never hit."""
        runs = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as raw:
                out = Path(raw)
                _run(out)
                runs.append({name: (out / (name + ".json")).read_text(encoding="utf-8")
                             for name in ("intent_manifest", "model_contract",
                                          "artifact_manifest", "commission_report",
                                          "final_status")})
        for name in runs[0]:
            with self.subTest(artifact=name):
                self.assertEqual(runs[0][name], runs[1][name])

    def test_the_safety_packet_hash_is_stable_across_runs(self) -> None:
        packets = []
        response = {"decision": "PASS", "failure_modes": [], "safety_concerns": [],
                    "missing_evidence": [], "required_actions": [], "summary": "ok"}

        def call(packet):
            packets.append(packet)
            return response

        for _ in range(2):
            with tempfile.TemporaryDirectory() as raw:
                runner.run(_request(Path(raw), consequence="CONSEQUENTIAL",
                                    reviewer=SafetyTest.REVIEWER, safety_call=call))
        self.assertEqual(packets[0].packet_hash(), packets[1].packet_hash())


class DomainCompletenessTest(unittest.TestCase):
    def test_every_parameter_a_template_takes_is_bounded(self) -> None:
        """A domain with a hole in it certifies nothing: a c_clip with a
        900 x 400 mm flange routed DIRECT and commissioned, while bore_d's own
        basis says 'above 40 the flange leaves the bed'."""
        for name, params in (("c_clip", CLIP), ("trim_ring", RING)):
            with self.subTest(template=name):
                template = T.get(name)
                self.assertEqual(set(), set(params) - set(template.bounds),
                                 name + " takes parameters it does not bound")

    def test_an_unbounded_parameter_is_refused_rather_than_admitted(self) -> None:
        template = T.get("c_clip")
        stripped = dataclasses.replace(
            template, bounds={k: v for k, v in template.bounds.items() if k != "flange_w"})
        reasons = stripped.rejects(CLIP)
        self.assertTrue(any("no certified range" in r for r in reasons), reasons)

    def test_an_oversized_flange_no_longer_routes_direct(self) -> None:
        decision = intent.select(requested_template="c_clip",
                                 parameters={**CLIP, "flange_w": 900.0, "flange_d": 400.0},
                                 external_geometry=False, ambiguities=())
        self.assertNotEqual("DIRECT", decision.route)


class ModifierTest(unittest.TestCase):
    def test_a_modifier_nobody_measures_is_deferred_not_satisfied(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            runner.run(_request(out, modifiers=("inserts", "threads")))
            report = json.loads((out / "manufacturing_report.json").read_text(encoding="utf-8"))
            self.assertEqual("DEFERRED", report["overall"])
            for row in report["predicates"]:
                self.assertNotEqual("SATISFIED", row["result"], row)

    def test_an_unknown_modifier_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result = _run_looked(out, modifiers=("banana",))
            report = json.loads((out / "manufacturing_report.json").read_text(encoding="utf-8"))
            self.assertEqual("BLOCKED", report["overall"])
            self.assertEqual("FAILED", result.final_status["final_status"])

    def test_the_manufacturing_report_binds_to_its_contract(self) -> None:
        from . import schemas as S

        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            runner.run(_request(out, modifiers=("supports",)))
            report = json.loads((out / "manufacturing_report.json").read_text(encoding="utf-8"))
            contract = json.loads((out / "model_contract.json").read_text(encoding="utf-8"))
            self.assertEqual(S.payload_hash(contract), report["contract_sha256"])


class CalibrationTest(unittest.TestCase):
    """The gate the plan calls hard, kept honest by re-measuring it.

    `screening.CALIBRATED` is a claim about measured performance. A boolean that
    somebody set by hand decays the moment a detector changes, so the flag is
    only allowed to be True while this test can still reproduce the numbers
    behind it.
    """

    def test_the_corpus_measures_screening_and_not_the_pipeline(self) -> None:
        """The rate that decides the gate must be screening's own.

        It was computed from `caught_by_contract or caught_by_screening`, so it
        reported 0.0 while the screen itself missed 46.7% of added material --
        and contract checks are conditioned on declared features, which is
        exactly why they are not the broad evidence this gate is about.
        """
        from . import corpus

        report = corpus.run(corpus._default_templates())
        added = report["per_class"]["added-material"]

        # Separately computed, not separately named. The screen's rate is scored
        # on fused mutants only; the pipeline's counts every mutant and every
        # instrument. They may agree when both are clean -- what must hold is
        # that the gate reads the screen's.
        self.assertIn("pipeline_false_negative_rate", added)
        self.assertIn("screening_false_negative_rate", added)
        self.assertEqual(report["screening_false_negative_rate"],
                         added["screening_false_negative_rate"])
        self.assertLessEqual(added["fused_mutants"], added["mutants"])

    def test_screening_is_scored_only_on_defects_it_could_see(self) -> None:
        """A disconnected solid is debris whatever class it was filed under, and
        the component detector sees it for free."""
        from . import corpus

        report = corpus.run(corpus._default_templates())
        added = report["per_class"]["added-material"]
        self.assertLess(added["fused_mutants"], added["mutants"],
                        "the corpus should contain both fused and separate defects")

    def test_the_flag_matches_the_measurement(self) -> None:
        """A stale True is worse than a False: it licenses dropping the look on a
        screen nobody has checked."""
        from . import corpus, screening as S

        gate = corpus.run(corpus._default_templates())["gate"]
        self.assertEqual(S.CALIBRATED, gate == "PASS",
                         f"CALIBRATED={S.CALIBRATED} while the corpus gate is {gate}")

    def test_an_uncalibrated_screen_stops_a_job_nobody_looked_at(self) -> None:
        """The plan calls this a hard gate. It has to move the status, or it is a
        string: an earlier version only edited the claim text, so flipping the
        flag changed nothing about what shipped."""
        from . import screening as S

        if S.CALIBRATED:
            self.skipTest("screening is calibrated; the gate does not apply")
        with tempfile.TemporaryDirectory() as raw:
            result = _run(Path(raw))
            self.assertEqual("NEEDS_MORE_EVIDENCE",
                             result.final_status["final_status"])
        with tempfile.TemporaryDirectory() as raw:
            looked = _run_looked(Path(raw))
            self.assertEqual("VERIFIED", looked.final_status["final_status"])

    def test_the_status_reports_the_calibration_state(self) -> None:
        from . import screening as S

        with tempfile.TemporaryDirectory() as raw:
            final = _run(Path(raw)).final_status
            self.assertEqual(S.CALIBRATED, final["screening_calibrated"])

    def test_screening_never_claims_to_prove_absence(self) -> None:
        """Calibration measures what the screens catch. It does not widen what
        they are for -- a missing feature stays the contract's job, and the
        calibration note must not read as though passing changed that."""
        from . import screening as S

        self.assertIn("cannot prove", S.__doc__)
        self.assertIn("cannot prove", S.CALIBRATION_NOTE)
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            _, _, screen = _measure(_clean_clip(), _contract(tmp), tmp)
            self.assertIn("cannot prove", screen["note"])



class FittedRouteTest(unittest.TestCase):
    """One bounded call recovers what the job does not own; everything else is
    computed from it deterministically."""

    SPEC = {"measurements": [{"feature": "bundle_across", "nominal_mm": 12.4,
                              "uncertainty_mm": 0.15, "method": "caliper, three reads",
                              "datum": "widest section", "confidence": "A"}],
            "interfaces": [{"interface_id": "channel", "measurement": "bundle_across",
                            "fit_class": "slip"}],
            "unresolved": []}

    BASE = {"wall": 3.0, "height": 9.0, "mouth_gap": 9.0, "flange_w": 40.0,
            "flange_d": 22.0, "flange_t": 5.0, "screw_d": 4.8}

    def _job(self, out: Path, response, **kw):
        seen = []

        def call(request):
            seen.append(request)
            return response

        result = runner.run(runner.JobRequest(
            job_id="fit", brief_path=out / "b.md", template="c_clip",
            parameters=dict(self.BASE), stated=frozenset({"flange_w"}),
            consequence="INCONSEQUENTIAL", out_dir=out,
            updated_utc="1970-01-01T00:00:00Z", render=False,
            external_geometry=True, evidence=("photo1.jpg",), spec_call=call,
            interface_map={"channel": "bore_d"},
            reviewer={"model_snapshot": "test"}, **kw))
        return result, seen

    def test_one_dispatch_recovers_the_spec_and_the_job_completes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result, seen = self._job(out, self.SPEC)

            self.assertEqual(1, len(seen), "FITTED costs exactly one dispatch")
            self.assertEqual(1, result.llm_calls)
            self.assertEqual("PASS", json.loads(
                (out / "commission_report.json").read_text(encoding="utf-8"))["verdict"])
            self.assertTrue((out / "specification.json").is_file())

    def test_the_recovered_dimension_reaches_the_manifest_with_its_provenance(self) -> None:
        """A recovered parameter is new, so a manifest patched over the old one
        drops exactly the value this route exists to produce."""
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            self._job(out, self.SPEC)
            rows = {r["name"]: r for r in json.loads(
                (out / "intent_manifest.json").read_text(encoding="utf-8"))["requirements"]}

            self.assertEqual(13.0, rows["bore_d"]["value"])
            self.assertEqual("metrologist", rows["bore_d"]["source"])
            self.assertEqual("user", rows["flange_w"]["source"])
            self.assertEqual("designer", rows["wall"]["source"])

    def test_the_clearance_is_the_pipelines_not_the_models(self) -> None:
        """A specification that arrived with its own clearance folded in could
        not be checked against the object it came from."""
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            self._job(out, self.SPEC)
            spec = json.loads((out / "specification.json").read_text(encoding="utf-8"))

            interface = spec["interfaces"][0]
            self.assertEqual("pipeline", interface["clearance_owner"])
            self.assertEqual(list(fitted.FIT_CLEARANCE["slip"]), interface["clearance_mm"])
            self.assertEqual(12.4, spec["measurements"][0]["nominal_mm"],
                             "the measurement is reported as taken, not as adjusted")

    def test_an_unresolved_dimension_stops_the_job(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result, _ = self._job(out, {**self.SPEC,
                                        "unresolved": ["bundle is obscured in every photo"]})

            self.assertFalse(result.ok)
            self.assertEqual("specification", result.stage)
            self.assertIn("obscured", result.message)

    def test_a_fitted_job_without_a_reviewer_refuses_rather_than_guessing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result = runner.run(runner.JobRequest(
                job_id="fit", brief_path=out / "b.md", template="c_clip",
                parameters=dict(self.BASE), stated=frozenset(),
                consequence="INCONSEQUENTIAL", out_dir=out,
                updated_utc="1970-01-01T00:00:00Z", render=False,
                external_geometry=True))

            self.assertFalse(result.ok)
            self.assertIn("no spec reviewer was supplied", result.message)

    def test_an_interface_to_an_unmeasured_feature_is_refused(self) -> None:
        bad = {"measurements": [], "unresolved": [],
               "interfaces": [{"interface_id": "x", "measurement": "ghost",
                               "fit_class": "slip"}]}
        with self.assertRaises(Exception) as caught:
            fitted.validate(bad)
        self.assertIn("no measurement reports", str(caught.exception))

    def test_an_unknown_fit_class_is_refused_before_the_build(self) -> None:
        bad = {"unresolved": [],
               "measurements": [{"feature": "a", "nominal_mm": 10.0,
                                 "uncertainty_mm": 0.1, "confidence": "A"}],
               "interfaces": [{"interface_id": "x", "measurement": "a",
                               "fit_class": "magic"}]}
        with self.assertRaises(ValueError) as caught:
            fitted.validate(bad)
        self.assertIn("magic", str(caught.exception))

    def test_an_impossible_measurement_is_refused(self) -> None:
        for row, why in (({"feature": "a", "nominal_mm": -1.0, "uncertainty_mm": 0.1,
                           "confidence": "A"}, "negative dimension"),
                         ({"feature": "a", "nominal_mm": 10.0, "uncertainty_mm": -0.1,
                           "confidence": "A"}, "negative uncertainty"),
                         ({"feature": "a", "nominal_mm": 10.0, "uncertainty_mm": 0.1,
                           "confidence": "Z"}, "confidence outside the grades")):
            with self.subTest(case=why):
                with self.assertRaises(Exception):
                    fitted.validate({"measurements": [row], "interfaces": [],
                                     "unresolved": []})

    def test_the_band_carries_instrument_uncertainty_on_top_of_the_spread(self) -> None:
        """A repeat spread bounds repeatability, not accuracy."""
        m = fitted.Measurement(feature="a", nominal_mm=12.4, uncertainty_mm=0.15,
                               method="caliper", datum="widest", confidence="A")
        low, high = m.band()
        self.assertAlmostEqual(12.4 - 0.15 - fitted.INSTRUMENT_UNCERTAINTY_MM, low)
        self.assertAlmostEqual(12.4 + 0.15 + fitted.INSTRUMENT_UNCERTAINTY_MM, high)

    def test_a_direct_job_never_calls_the_spec_reviewer(self) -> None:
        called = []
        with tempfile.TemporaryDirectory() as raw:
            result = runner.run(_request(Path(raw), spec_call=lambda r: called.append(r)))
            self.assertEqual([], called)
            self.assertEqual(0, result.llm_calls)



class IndependentVerificationTest(unittest.TestCase):
    """The only route to VERIFIED, and the one reading a gate cannot do.

    A gate checks the part against its contract. It cannot ask whether the
    contract was the right contract -- every check it runs is conditioned on one
    somebody wrote, and a contract that misread the brief is satisfied exactly as
    well by the wrong part.
    """

    DEFECT = {"summary": "mouth faces away from the desk", "owning_loop": "CONTRACT",
              "expected_vs_observed": "opens outward; the brief says toward the run",
              "evidence": "witness/multi.png", "severity": "blocks use"}

    def _verify(self, out: Path, response, **kw):
        seen = []

        def call(packet):
            seen.append(packet)
            return response

        result = runner.run(_request(out, verify_call=call,
                                     reviewer={"model_snapshot": "test"}, **kw))
        return result, seen

    def _reply(self, decision, defects=(), unmet=()):
        return {"decision": decision, "defects": list(defects),
                "unmet_requirements": list(unmet), "missing_evidence": [],
                "summary": "ok"}

    def test_a_pass_is_the_only_way_to_reach_verified(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result, seen = self._verify(out, self._reply("PASS"))
            self.assertEqual("VERIFIED", result.final_status["final_status"])
            self.assertEqual(1, len(seen))
            self.assertTrue((out / "verification_report.json").is_file())

    def test_without_a_verifier_no_job_reaches_verified(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result = _run(Path(raw))
            self.assertNotEqual("VERIFIED", result.final_status["final_status"])
            self.assertIsNone(result.final_status["verification"])

    def test_a_rejection_moves_the_status_and_names_the_loop(self) -> None:
        """Leaving a rejection at COMMISSIONED read as 'geometrically commissioned
        against its contract' while an independent reader had just said the part
        was wrong: true about the geometry, silent about the finding."""
        with tempfile.TemporaryDirectory() as raw:
            result, _ = self._verify(Path(raw), self._reply("REJECT", [self.DEFECT]))
            final = result.final_status
            self.assertEqual("FAILED", final["final_status"])
            self.assertIn("CONTRACT", final["allowed_claim"])
            self.assertIn("rejected by independent verification", final["allowed_claim"])

    def test_needs_more_evidence_does_not_round_up(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result, _ = self._verify(Path(raw), self._reply("NEEDS_MORE_EVIDENCE"))
            self.assertEqual("NEEDS_MORE_EVIDENCE", result.final_status["final_status"])

    def test_a_deferred_manufacturing_predicate_still_blocks_verified(self) -> None:
        """Verification agreed about the geometry. It did not print the part."""
        with tempfile.TemporaryDirectory() as raw:
            result, _ = self._verify(Path(raw), self._reply("PASS"),
                                     modifiers=("supports",))
            self.assertEqual("COMMISSIONED", result.final_status["final_status"])
            self.assertIn("not verified", result.final_status["allowed_claim"])

    def test_the_verifier_never_receives_the_designers_source(self) -> None:
        """Reading model.py turns the second opinion into the designer's own
        question asked again by someone with less context."""
        with tempfile.TemporaryDirectory() as raw:
            _, seen = self._verify(Path(raw), self._reply("PASS"))
            payload = json.dumps(seen[0].payload)
            self.assertNotIn("model.py", payload)
            self.assertIn("brief", seen[0].payload)
            self.assertIn("commission_report", seen[0].payload)

    def test_a_rejection_with_no_defects_is_refused(self) -> None:
        with self.assertRaises(Exception) as caught:
            verification.validate(self._reply("REJECT"))
        self.assertIn("name what is wrong", str(caught.exception))

    def test_a_pass_carrying_defects_is_refused(self) -> None:
        with self.assertRaises(Exception) as caught:
            verification.validate(self._reply("PASS", [self.DEFECT]))
        self.assertIn("decide", str(caught.exception))

    def test_a_defect_missing_its_evidence_is_refused(self) -> None:
        for field in ("summary", "expected_vs_observed", "evidence", "severity"):
            with self.subTest(missing=field):
                defect = {**self.DEFECT, field: ""}
                with self.assertRaises(Exception):
                    verification.validate(self._reply("REJECT", [defect]))

    def test_an_unknown_owning_loop_is_refused(self) -> None:
        defect = {**self.DEFECT, "owning_loop": "somebody else"}
        with self.assertRaises(Exception):
            verification.validate(self._reply("REJECT", [defect]))

    def test_passing_while_listing_unmet_requirements_is_downgraded(self) -> None:
        """The finding this pass exists for: the brief wants something the
        contract never mentioned. A PASS alongside it is incoherent."""
        result = verification.run(
            verification.Packet({"a": 1}), {},
            lambda p: self._reply("PASS", (), ["a strain relief nobody modelled"]))
        self.assertEqual("NEEDS_MORE_EVIDENCE", result["decision"])
        self.assertIn("downgraded", result["summary"])

    def test_full_route_refuses_without_a_verifier(self) -> None:
        decision = intent.select(requested_template=None,
                                 parameters={"nothing": 1.0},
                                 external_geometry=False, ambiguities=())
        self.assertEqual("FULL", decision.route)
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result = runner.run(runner.JobRequest(
                job_id="f", brief_path=out / "b.md", template=None,
                parameters={"nothing": 1.0}, stated=frozenset(),
                consequence="INCONSEQUENTIAL", out_dir=out,
                updated_utc="1970-01-01T00:00:00Z", render=False))
            self.assertFalse(result.ok)
            self.assertIn("requires independent verification", result.message)


if __name__ == "__main__":
    unittest.main()
