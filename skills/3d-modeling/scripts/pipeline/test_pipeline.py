#!/usr/bin/env python3
"""Iteration 1: the DIRECT vertical slice, and the defects it must still catch.

Every mutation below is applied to the *mesh*, after a correct build, so the test
asks the question that matters: does the contract catch a part that is wrong in a
way the builder did not know about? A test that mutates the parameters instead
would only prove the builder is consistent with itself.

The half of this file the commit gate will not carry is in
`benchmarks/heavy/test_pipeline_heavy.py`, and runs before merge instead of on
every push: `CalibrationTest`, `VerticalSliceTest`. Same tests, moved rather
than weakened; `conftest.py` carries the rule and `benchmarks/heavy/README.md`
the measurement behind it.
"""
from __future__ import annotations

import dataclasses
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

import trimesh

from . import analysis, commission, contract as C, fitted, intent, runner, safety, screening
from . import schemas as S, status, templates as T, verification
from . import witness as W

CLIP = {"bore_d": 12.0, "wall": 3.0, "height": 9.0, "mouth_gap": 9.0,
        "flange_w": 40.0, "flange_d": 22.0, "flange_t": 5.0, "screw_d": 4.8}
RING = {"hole_d": 60.0, "lip_w": 5.0, "panel_t": 18.0, "lip_t": 3.0,
        "wall": 2.0, "chamfer": 1.0}
TEST_PRINTER = "Test Printer"
TEST_MATERIAL = {"process": "FDM", "material": "PLA"}
TEST_NOZZLE = {"diameter_mm": 0.4}
TEST_ORIENTATION = {"model_to_printer_matrix": "identity", "bed_z_mm": 0.0}


def _request(out: Path, *, template="c_clip", params=None, consequence="INCONSEQUENTIAL",
             printer=TEST_PRINTER, material=TEST_MATERIAL, nozzle=TEST_NOZZLE,
             orientation=TEST_ORIENTATION, render=False,
             **kw) -> runner.JobRequest:
    return runner.JobRequest(
        job_id="t", brief_path=out / "brief.md", template=template,
        parameters=dict(params or CLIP), stated=frozenset({"bore_d"}),
        consequence=consequence, out_dir=out, updated_utc="1970-01-01T00:00:00Z",
        render=render, printer=printer, material=dict(material), nozzle=dict(nozzle),
        orientation=dict(orientation), **kw)


def _looked_at(packet):
    """A stand-in for the bounded visual call.

    The screening corpus gate is not currently earned, so a clean job does not
    complete without somebody looking. Tests that want a finished job supply
    this; tests about the gate itself do not.
    """
    response = {"decision": "PASS", "defects": [], "unmet_requirements": [],
                "missing_evidence": [], "summary": "nothing undeclared visible"}
    payload = getattr(packet, "payload", packet)
    if isinstance(payload, dict) and "review_envelope" in payload:
        response["review_envelope"] = payload["review_envelope"]
    return response


def _run(out: Path, **kw):
    return runner.run(_request(out, **kw))


def _run_looked(out: Path, **kw):
    return runner.run(_request(out, verify_call=_looked_at,
                               reviewer={"model_snapshot": "test"}, **kw))


def _full_spec(request):
    response = {
        "measurements": [{"feature": "bundle_across", "nominal_mm": 12.4,
                          "uncertainty_mm": 0.05, "method": "caliper",
                          "datum": "widest section", "confidence": "A"}],
        "interfaces": [{"interface_id": "channel", "measurement": "bundle_across",
                        "fit_class": "slip"}],
        "unresolved": [],
    }
    if "review_envelope" in request:
        response["review_envelope"] = request["review_envelope"]
    return response


def _full_request(out: Path, **kw) -> runner.JobRequest:
    params = dict(kw.pop("params", CLIP))
    params["bore_d"] = 60.0
    kw.setdefault("spec_call", _full_spec)
    kw.setdefault("interface_map", {"channel": "bore_d"})
    return _request(out, params=params, **kw)


def _run_full_looked(out: Path, **kw):
    return runner.run(_full_request(
        out, verify_call=_looked_at, reviewer={"model_snapshot": "test"}, **kw))


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
            expected_bodies=1, orientation={}, material={}, nozzle={}, printer="",
            modifiers=(),
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

    def test_printer_material_nozzle_and_orientation_are_validated(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = _contract(Path(raw))

        cases = {
            "printer": {"printer": ""},
            "material process": {"material": {"material": "PLA"}},
            "material name": {"material": {"process": "FDM"}},
            "nozzle shape": {"nozzle": {"diameter_mm": 0}},
            "nozzle value": {"nozzle": {"diameter_mm": "0.4"}},
            "orientation matrix": {"orientation": {"bed_z_mm": 0.0}},
            "orientation bed": {"orientation": {"model_to_printer_matrix": "identity"}},
            "orientation matrix shape": {
                "orientation": {"model_to_printer_matrix": "rotated", "bed_z_mm": 0.0}},
        }
        for name, overrides in cases.items():
            with self.subTest(input=name):
                broken = C.Contract(**{**base.__dict__, **overrides})
                self.assertTrue(C.preflight(broken, known_checks=commission.KNOWN_CHECKS))

        numeric_orientation = C.Contract(
            **{**base.__dict__, "orientation": {
                "model_to_printer_matrix": [[1, 0, 0, 0], [0, 1, 0, 0],
                                             [0, 0, 1, 0], [0, 0, 0, 1]],
                "bed_z_mm": 0.0}})
        self.assertEqual([], C.preflight(numeric_orientation,
                                         known_checks=commission.KNOWN_CHECKS))

    def test_missing_machine_input_blocks_before_build(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result = _run(Path(raw), printer="")
            self.assertFalse(result.ok)
            self.assertEqual("preflight", result.stage)
            self.assertIn("printer", result.message)


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
            if hasattr(packet, "payload") and "review_envelope" in packet.payload:
                return {**response, "review_envelope": packet.payload["review_envelope"]}
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


class CanonicalPipelineTest(unittest.TestCase):
    """Dispatch counts and escalation behavior from the approved model."""

    def test_consequence_does_not_change_route_selection(self) -> None:
        import inspect

        self.assertNotIn("consequence", inspect.signature(intent.select).parameters)
        for consequence in S.CONSEQUENCE:
            with self.subTest(consequence=consequence):
                direct = intent.select(requested_template="c_clip", parameters=dict(CLIP),
                                       external_geometry=False, ambiguities=())
                self.assertEqual("DIRECT", direct.route)
        self.assertEqual(("INCONSEQUENTIAL", "CONSEQUENTIAL"), S.CONSEQUENCE)

    def test_clean_inconsequential_direct_needs_no_review_dispatch(self) -> None:
        calls = []

        def spec_call(request):
            calls.append("spec")
            return _full_spec(request)

        def safety_call(packet):
            calls.append("safety")
            return {}

        def verify_call(packet):
            calls.append("verification")
            return _looked_at(packet)

        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result = _run(out, spec_call=spec_call, safety_call=safety_call,
                          verify_call=verify_call)
            self.assertEqual([], calls)
            self.assertEqual(0, result.llm_calls)
            self.assertEqual("NEEDS_MORE_EVIDENCE", result.final_status["final_status"])
            self.assertFalse((out / "safety_verification_report.json").exists())
            self.assertFalse((out / "verification_report.json").exists())

    def test_clean_consequential_direct_dispatches_exactly_one_safety_review(self) -> None:
        calls = []

        def spec_call(request):
            calls.append("spec")
            return _full_spec(request)

        def safety_call(packet):
            calls.append("safety")
            return {"decision": "PASS", "failure_modes": [], "safety_concerns": [],
                    "missing_evidence": [], "required_actions": [], "summary": "ok",
                    "review_envelope": packet.payload["review_envelope"]}

        def verify_call(packet):
            calls.append("verification")
            return _looked_at(packet)

        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result = _run(out, consequence="CONSEQUENTIAL", safety_call=safety_call,
                          spec_call=spec_call, verify_call=verify_call)
            self.assertEqual(["safety"], calls)
            self.assertEqual(1, result.llm_calls)
            self.assertEqual("NEEDS_MORE_EVIDENCE", result.final_status["final_status"])
            self.assertTrue((out / "safety_verification_report.json").exists())
            self.assertFalse((out / "verification_report.json").exists())

    def test_full_retains_specification_and_independent_review_dispatches(self) -> None:
        calls = []

        def spec_call(request):
            calls.append("spec")
            return _full_spec(request)

        def verify_call(packet):
            calls.append("verification")
            return _looked_at(packet)

        with tempfile.TemporaryDirectory() as raw:
            result = runner.run(_full_request(
                Path(raw), spec_call=spec_call, verify_call=verify_call,
                reviewer={"model_snapshot": "test"}))
            self.assertEqual(["spec", "verification"], calls)
            self.assertEqual(2, result.llm_calls)
            self.assertEqual("VERIFIED", result.final_status["final_status"])

    def test_recovery_does_not_rewrite_the_full_route_in_final_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result = runner.run(_full_request(
                out, verify_call=_looked_at, reviewer={"model_snapshot": "test"}))
            intent_manifest = json.loads(
                (out / "intent_manifest.json").read_text(encoding="utf-8"))
            final_status = json.loads(
                (out / "final_status.json").read_text(encoding="utf-8"))

            self.assertEqual("FULL", intent_manifest["route_decision"]["route"])
            self.assertEqual("FULL", final_status["route"])
            self.assertEqual("FULL", result.final_status["route"])
            self.assertNotEqual("DIRECT", intent_manifest["route_decision"]["route"])
            self.assertNotEqual("DIRECT", final_status["route"])

    def _screening_case(self, overall: str, *, consequence: str = "INCONSEQUENTIAL",
                        safety_call=None, verify_call=None):
        original = screening.run
        screening.run = lambda ctx, contract: {"overall": overall, "calibrated": True}
        try:
            with tempfile.TemporaryDirectory() as raw:
                result = _run(Path(raw), consequence=consequence,
                              safety_call=safety_call, verify_call=verify_call)
                return result
        finally:
            screening.run = original

    def test_anomaly_screening_adds_no_optional_dispatch_and_escalates(self) -> None:
        calls = []

        def verify_call(packet):
            calls.append("verification")
            return _looked_at(packet)

        result = self._screening_case("ANOMALY", verify_call=verify_call)
        self.assertEqual([], calls)
        self.assertEqual(0, result.llm_calls)
        self.assertEqual("NEEDS_MORE_EVIDENCE", result.final_status["final_status"])

    def test_indeterminate_screening_adds_no_optional_dispatch_and_escalates(self) -> None:
        calls = []

        def verify_call(packet):
            calls.append("verification")
            return _looked_at(packet)

        result = self._screening_case("INDETERMINATE", verify_call=verify_call)
        self.assertEqual([], calls)
        self.assertEqual(0, result.llm_calls)
        self.assertEqual("NEEDS_MORE_EVIDENCE", result.final_status["final_status"])

    def test_consequential_anomaly_keeps_only_its_safety_review(self) -> None:
        calls = []

        def safety_call(packet):
            calls.append("safety")
            return {"decision": "PASS", "failure_modes": [], "safety_concerns": [],
                    "missing_evidence": [], "required_actions": [], "summary": "ok",
                    "review_envelope": packet.payload["review_envelope"]}

        def verify_call(packet):
            calls.append("verification")
            return _looked_at(packet)

        result = self._screening_case("ANOMALY", consequence="CONSEQUENTIAL",
                                      safety_call=safety_call, verify_call=verify_call)
        self.assertEqual(["safety"], calls)
        self.assertEqual(1, result.llm_calls)
        self.assertEqual("NEEDS_MORE_EVIDENCE", result.final_status["final_status"])


class ManufacturingTest(unittest.TestCase):
    def test_a_deferred_predicate_blocks_verified_and_says_so(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result = _run_full_looked(out, modifiers=("supports",))
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

    def _bound_safety(self, contract: C.Contract) -> dict[str, Any]:
        from . import review as R
        return {**self._decide(), "safety_envelope": R.build_envelope(
            kind="safety", job_id=contract.job_id, revision="t",
            packet_hash="p", reviewer={},
            contract_hash=contract.contract_hash())}

    def test_a_passing_safety_review_is_not_independent_verification(self) -> None:
        """It reviewed hazards, not whether the part matches the brief.

        Decided at the status layer with a rendered witness, so the assertion is
        about safety-versus-verification rather than about whether a renderer
        happened to be installed."""
        with tempfile.TemporaryDirectory() as raw:
            base = _contract(Path(raw))
        consequential = C.Contract(**{**base.__dict__, "consequence": "CONSEQUENTIAL"})
        envelope = self._bound_safety(consequential)["safety_envelope"]
        final = status.decide(
            contract=consequential,
            commission_report={"verdict": "PASS", "witness": {"rendered": True}},
            screening={"overall": "CLEAR", "calibrated": True},
            manufacturing=None, artifact={"contract_sha256": consequential.contract_hash(),
                                          "stl_sha256": "b", "source_sha256": "c"},
            safety={"decision": "PASS", "failure_modes": [], "safety_concerns": [],
                    "missing_evidence": [], "required_actions": [], "summary": "ok",
                    "review_envelope": envelope.as_dict()},
            verification=None, updated_utc="t",
            safety_envelope=envelope)
        self.assertEqual("COMMISSIONED", final["final_status"])
        self.assertNotEqual("VERIFIED", final["final_status"])

    def test_a_consequential_job_nobody_could_see_does_not_complete(self) -> None:
        """The renderer is not on the core path, so this is the ordinary case.
        It used to pass in silence: the witness recorded 'unavailable' and no
        consumer read it."""
        with tempfile.TemporaryDirectory() as raw:
            base = _contract(Path(raw))
        consequential = C.Contract(**{**base.__dict__, "consequence": "CONSEQUENTIAL"})
        envelope = self._bound_safety(consequential)["safety_envelope"]
        final = status.decide(
            contract=consequential,
            commission_report={"verdict": "PASS", "witness": {"rendered": False}},
            screening={"overall": "CLEAR", "calibrated": True},
            manufacturing=None, artifact={"contract_sha256": consequential.contract_hash(),
                                          "stl_sha256": "b", "source_sha256": "c"},
            safety={"decision": "PASS", "failure_modes": [], "safety_concerns": [],
                    "missing_evidence": [], "required_actions": [], "summary": "ok",
                    "review_envelope": envelope.as_dict()},
            verification=None, updated_utc="t",
            safety_envelope=envelope)
        self.assertEqual("NEEDS_MORE_EVIDENCE", final["final_status"])
        self.assertIn("saw no images", final["allowed_claim"])
        self.assertFalse(final["witnesses_rendered"])

    def _verification_envelope(self, contract: C.Contract):
        from . import review as R
        return R.build_envelope(
            kind="verification", job_id=contract.job_id, revision="t",
            packet_hash="p", reviewer={}, contract_hash=contract.contract_hash())

    def _status_kwargs(self, contract: C.Contract) -> dict[str, Any]:
        return {"contract": contract,
                "commission_report": {"verdict": "PASS",
                                      "witness": {"rendered": True, "sections": []}},
                "screening": {"overall": "CLEAR", "calibrated": True},
                "manufacturing": None, "safety": None, "verification": None,
                "artifact": {"contract_sha256": contract.contract_hash(),
                             "stl_sha256": "b", "source_sha256": "c"},
                "updated_utc": "t"}

    def test_a_bound_safety_pass_with_failure_modes_is_not_promoted(self) -> None:
        """Envelope equality says who answered; it says nothing about what they
        answered. A PASS carrying its own failure modes is contradictory, and
        must fail closed at promotion exactly as it did at first validation."""
        from . import review as R

        with tempfile.TemporaryDirectory() as raw:
            base = _contract(Path(raw))
        consequential = C.Contract(**{**base.__dict__, "consequence": "CONSEQUENTIAL"})
        envelope = R.build_envelope(
            kind="safety", job_id=consequential.job_id, revision="t",
            packet_hash="p", reviewer={}, contract_hash=consequential.contract_hash())
        final = status.decide(
            **{**self._status_kwargs(consequential),
               "safety": {"decision": "PASS", "failure_modes": ["fracture"],
                          "safety_concerns": [], "missing_evidence": [],
                          "required_actions": [], "summary": "ok",
                          "review_envelope": envelope.as_dict()}},
            safety_envelope=envelope)
        self.assertNotIn(final["final_status"], ("COMMISSIONED", "VERIFIED"))

    def test_a_bound_safety_pass_missing_a_field_is_not_promoted(self) -> None:
        """A partial report bound to the current envelope is still partial:
        completeness is re-checked at promotion, not only when first parsed."""
        from . import review as R

        with tempfile.TemporaryDirectory() as raw:
            base = _contract(Path(raw))
        consequential = C.Contract(**{**base.__dict__, "consequence": "CONSEQUENTIAL"})
        envelope = R.build_envelope(
            kind="safety", job_id=consequential.job_id, revision="t",
            packet_hash="p", reviewer={}, contract_hash=consequential.contract_hash())
        partial = {"decision": "PASS", "failure_modes": [], "safety_concerns": [],
                   "missing_evidence": [], "summary": "ok",
                   "review_envelope": envelope.as_dict()}  # no required_actions
        final = status.decide(
            **{**self._status_kwargs(consequential), "safety": partial},
            safety_envelope=envelope)
        self.assertNotIn(final["final_status"], ("COMMISSIONED", "VERIFIED"))

    def test_a_bound_verification_pass_with_defects_is_not_promoted(self) -> None:
        """A PASS carrying known defects is how a defect ships with a paper
        trail saying somebody saw it -- even when the envelope is current."""
        with tempfile.TemporaryDirectory() as raw:
            contract = _contract(Path(raw))
        envelope = self._verification_envelope(contract)
        defect = {"summary": "x", "owning_loop": "CONTRACT",
                  "expected_vs_observed": "x", "evidence": "x", "severity": "x"}
        final = status.decide(
            **{**self._status_kwargs(contract),
               "verification": {"decision": "PASS", "defects": [defect],
                                "unmet_requirements": [], "missing_evidence": [],
                                "summary": "ok",
                                "review_envelope": envelope.as_dict()}},
            verification_envelope=envelope)
        self.assertNotIn(final["final_status"], ("COMMISSIONED", "VERIFIED"))

    def test_a_bound_verification_pass_missing_a_field_is_not_promoted(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            contract = _contract(Path(raw))
        envelope = self._verification_envelope(contract)
        partial = {"decision": "PASS", "defects": [], "unmet_requirements": [],
                   "missing_evidence": [],  # no summary
                   "review_envelope": envelope.as_dict()}
        final = status.decide(
            **{**self._status_kwargs(contract), "verification": partial},
            verification_envelope=envelope)
        self.assertNotIn(final["final_status"], ("COMMISSIONED", "VERIFIED"))

    def test_a_bound_reject_without_defects_fails_closed(self) -> None:
        """A rejection that names nothing is malformed. It cannot be read as a
        valid finding, and it cannot crash the status layer either."""
        with tempfile.TemporaryDirectory() as raw:
            contract = _contract(Path(raw))
        envelope = self._verification_envelope(contract)
        final = status.decide(
            **{**self._status_kwargs(contract),
               "verification": {"decision": "REJECT", "defects": [],
                                "unmet_requirements": [], "missing_evidence": [],
                                "summary": "no",
                                "review_envelope": envelope.as_dict()}},
            verification_envelope=envelope)
        self.assertEqual("NEEDS_MORE_EVIDENCE", final["final_status"])

    def test_a_decisionless_safety_report_fails_closed_not_a_keyerror(self) -> None:
        """Completeness is re-checked at promotion, and the receipt's own
        serialization must not KeyError on a report carrying no decision."""
        from . import review as R

        with tempfile.TemporaryDirectory() as raw:
            base = _contract(Path(raw))
        consequential = C.Contract(**{**base.__dict__, "consequence": "CONSEQUENTIAL"})
        envelope = R.build_envelope(
            kind="safety", job_id=consequential.job_id, revision="t",
            packet_hash="p", reviewer={}, contract_hash=consequential.contract_hash())
        final = status.decide(
            **{**self._status_kwargs(consequential),
               "safety": {"failure_modes": [], "safety_concerns": [],
                          "missing_evidence": [], "required_actions": [],
                          "summary": "ok",  # no decision at all
                          "review_envelope": envelope.as_dict()}},
            safety_envelope=envelope)
        self.assertEqual("NEEDS_MORE_EVIDENCE", final["final_status"])
        self.assertIsNone(final["safety_verification"])

    def test_a_decisionless_verification_report_fails_closed_not_a_keyerror(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            contract = _contract(Path(raw))
        envelope = self._verification_envelope(contract)
        final = status.decide(
            **{**self._status_kwargs(contract),
               "verification": {"defects": [], "unmet_requirements": [],
                                "missing_evidence": [], "summary": "ok",
                                "review_envelope": envelope.as_dict()}},
            verification_envelope=envelope)
        self.assertEqual("NEEDS_MORE_EVIDENCE", final["final_status"])
        self.assertIsNone(final["verification"])

    def test_an_unavailable_witness_section_blocks_commissioned(self) -> None:
        """No verifier is needed for the block: a section the instrument could
        not measure demotes a clean, calibrated job before any promotion is
        considered. PASS-equivalent requires every section MEASURED."""
        with tempfile.TemporaryDirectory() as raw:
            contract = _contract(Path(raw))
        witness = {"rendered": True,
                   "sections": [{"z": 2.0, "area_mm2": None, "status": "UNAVAILABLE",
                                 "error_code": "X", "error_message": "x"}]}
        final = status.decide(
            contract=contract,
            commission_report={"verdict": "PASS", "witness": witness},
            screening={"overall": "CLEAR", "calibrated": True},
            manufacturing=None, artifact={"contract_sha256": contract.contract_hash(),
                                          "stl_sha256": "b", "source_sha256": "c"},
            safety=None, verification=None, updated_utc="t")
        self.assertEqual("NEEDS_MORE_EVIDENCE", final["final_status"])
        self.assertIn("could not be measured", final["allowed_claim"].lower())
        self.assertTrue(any("witness sections unavailable" in r
                            for r in final["reasons"]))

    def test_screening_anomaly_stops_short_of_commissioned(self) -> None:
        # Both carry `calibrated`, which production always sets. Without it the
        # uncalibrated branch answered first and this test passed with the
        # ANOMALY branch deleted -- it was asserting the wrong reason.
        clean = {"overall": "CLEAR", "calibrated": True}
        anomaly = {"overall": "ANOMALY", "calibrated": True}
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

    def test_a_through_hole_with_no_boolean_answer_is_unavailable(self) -> None:
        """The engine returning nothing is an absent measurement, never a
        measured zero: the bore check must record UNAVAILABLE and not pass."""
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            contract = _contract(tmp)
            from .backends.trimesh_manifold import build_c_clip
            part, _ = build_c_clip(CLIP)
            path = tmp / "a.stl"
            part.export(path)
            ctx = analysis.load(path)
            hole = next(f for f in contract.features if f.kind == "through_hole")

            original = trimesh.boolean.intersection
            try:
                trimesh.boolean.intersection = lambda *a, **k: None
                check = commission._feature_check(ctx, hole, 100.0)
            finally:
                trimesh.boolean.intersection = original

            self.assertFalse(check.ran)
            self.assertEqual("UNAVAILABLE", check.status)
            self.assertIsNone(check.measured)
            self.assertNotEqual("PASS", check.result)
            self.assertIsNotNone(check.error_code)

    def test_a_through_hole_boolean_failure_is_unavailable_not_a_crash(self) -> None:
        """An engine refusal must become an UNAVAILABLE observation on the
        report -- the same treatment every other feature check gets -- not an
        exception that ends commissioning with no commission report at all."""
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
                def refused(*a, **k):
                    raise RuntimeError("Not all meshes are volumes!")
                trimesh.boolean.intersection = refused
                report = commission.run(ctx, contract)
            finally:
                trimesh.boolean.intersection = original

            hole = next(c for c in report["checks"]
                        if c["check_id"].startswith("feature-") and "Bore" in c["title"])
            self.assertFalse(hole["ran"])
            self.assertEqual("UNAVAILABLE", hole["status"])
            self.assertIsNone(hole["measured"])
            self.assertNotEqual("PASS", hole["result"])
            self.assertIsNotNone(hole["error_code"])
            self.assertNotEqual("PASS", report["verdict"])

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

    def test_count_parameters_reject_fractional_vent_grid(self) -> None:
        template = T.get("vented_enclosure")
        params = {name: (bound.low + bound.high) / 2
                  for name, bound in template.bounds.items()}
        params.update({"inner_w": 100.0, "inner_d": 100.0, "inner_h": 100.0,
                       "wall": 2.0, "floor": 2.0, "vent_cols": 3.5,
                       "vent_rows": 3.0, "vent_w": 5.0, "vent_h": 5.0,
                       "boss_d": 8.0, "boss_bore": 3.0})
        reasons = template.rejects(params)
        self.assertTrue(any("vent_cols" in reason and "whole number" in reason
                            for reason in reasons), reasons)

    def test_count_parameters_reject_bool_and_numeric_string(self) -> None:
        template = T.get("vented_enclosure")
        params = {name: (bound.low + bound.high) / 2
                  for name, bound in template.bounds.items()}
        for bad in (True, "3"):
            with self.subTest(value=bad):
                params["vent_cols"] = bad
                reasons = template.rejects(params)
                self.assertTrue(any("vent_cols" in reason and "not a number" in reason
                                    for reason in reasons), reasons)


class ModifierTest(unittest.TestCase):
    def test_a_modifier_nobody_measures_is_deferred_not_satisfied(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            runner.run(_request(out, modifiers=("inserts", "threads")))
            report = json.loads((out / "manufacturing_report.json").read_text(encoding="utf-8"))
            self.assertEqual("DEFERRED", report["overall"])
            for row in report["predicates"]:
                self.assertNotEqual("SATISFIED", row["result"], row)

    def test_motion_path_without_a_sweep_is_explicitly_deferred(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            _run_full_looked(out, modifiers=("motion_path",))
            report = json.loads((out / "manufacturing_report.json").read_text(encoding="utf-8"))
            self.assertEqual("DEFERRED", report["overall"])
            self.assertEqual("DEFERRED", report["predicates"][0]["result"])
            self.assertIn("swept-volume", report["predicates"][0]["predicate"])

    def test_an_unknown_modifier_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result = _run_full_looked(out, modifiers=("banana",))
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


class FittedRouteTest(unittest.TestCase):
    """One bounded call recovers what the job does not own; everything else is
    computed from it deterministically."""

    SPEC = {"measurements": [{"feature": "bundle_across", "nominal_mm": 12.4,
                              "uncertainty_mm": 0.05, "method": "caliper, three reads",
                              "datum": "widest section", "confidence": "A"}],
            "interfaces": [{"interface_id": "channel", "measurement": "bundle_across",
                            "fit_class": "slip"}],
            "unresolved": []}

    BASE = {"bore_d": 12.0, "wall": 3.0, "height": 9.0, "mouth_gap": 9.0,
            "flange_w": 40.0, "flange_d": 22.0, "flange_t": 5.0, "screw_d": 4.8}

    def _job(self, out: Path, response, **kw):
        seen = []
        # Evidence must exist to be hashed into the request identity.
        (out / "photo1.jpg").write_bytes(b"dummy evidence")

        def call(request):
            seen.append(request)
            if isinstance(request, dict) and "review_envelope" in request:
                return {**response, "review_envelope": request["review_envelope"]}
            return response

        result = runner.run(runner.JobRequest(
            job_id="fit", brief_path=out / "b.md", template="c_clip",
            parameters=dict(self.BASE), stated=frozenset({"flange_w"}),
            consequence="INCONSEQUENTIAL", out_dir=out,
            updated_utc="1970-01-01T00:00:00Z", render=False,
            external_geometry=True, evidence=("photo1.jpg",), spec_call=call,
            interface_map={"channel": "bore_d"},
            reviewer={"model_snapshot": "test"},
            printer="Test Printer",
            material={"process": "FDM", "material": "PLA"},
            nozzle={"diameter_mm": 0.4},
            orientation={"model_to_printer_matrix": "identity", "bed_z_mm": 0.0},
            **kw))
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

    def test_recovery_does_not_rewrite_the_fitted_route_in_final_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result, _ = self._job(out, self.SPEC)
            intent_manifest = json.loads(
                (out / "intent_manifest.json").read_text(encoding="utf-8"))
            final_status = json.loads(
                (out / "final_status.json").read_text(encoding="utf-8"))

            self.assertEqual("FITTED", intent_manifest["route_decision"]["route"])
            self.assertEqual("FITTED", final_status["route"])
            self.assertEqual("FITTED", result.final_status["route"])
            self.assertNotEqual("DIRECT", intent_manifest["route_decision"]["route"])
            self.assertNotEqual("DIRECT", final_status["route"])

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
                external_geometry=True,
                printer="Test Printer",
                material={"process": "FDM", "material": "PLA"},
                nozzle={"diameter_mm": 0.4},
                orientation={"model_to_printer_matrix": "identity", "bed_z_mm": 0.0}))

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
                                 "uncertainty_mm": 0.1, "method": "caliper",
                                 "datum": "x", "confidence": "A"}],
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

    def test_non_finite_boolean_and_numeric_string_measurements_are_refused(self) -> None:
        good = {"feature": "a", "nominal_mm": 10.0, "uncertainty_mm": 0.1,
                "method": "caliper", "datum": "x", "confidence": "A"}
        for field, bad in (("nominal_mm", True), ("nominal_mm", "10.0"),
                           ("nominal_mm", float("nan")), ("uncertainty_mm", float("inf"))):
            with self.subTest(field=field, value=bad):
                with self.assertRaises(S.SchemaError):
                    fitted.validate({"measurements": [{**good, field: bad}],
                                     "interfaces": [], "unresolved": []})

    def test_fitted_acceptance_reports_propagated_uncertainty(self) -> None:
        measurements, interfaces, unresolved = fitted.validate(self.SPEC)
        report = fitted.report(measurements=measurements, interfaces=interfaces,
                               unresolved=unresolved, reviewer={})
        interface = report["interfaces"][0]
        self.assertEqual(0.1, interface["uncertainty_mm"])
        # slip is a 0.20 mm per-side band; its half-window is 0.20 mm and
        # +/-0.10 mm propagated uncertainty consumes 0.10 mm of that margin.
        self.assertEqual(0.1, interface["acceptance_tolerance_mm"])

    def test_fitted_acceptance_contract_is_carried_into_commission(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result, _ = self._job(out, self.SPEC)
            contract = json.loads(
                (out / "model_contract.json").read_text(encoding="utf-8"))
            fit = next(feature for feature in contract["features"]
                       if feature["kind"] == "fit_acceptance")
            self.assertEqual("channel", fit["expectation"]["interface_id"])
            self.assertEqual(0.1, fit["expectation"]["acceptance_tolerance_mm"])
            self.assertEqual(0.1, fit["tolerance"]["abs"])
            self.assertEqual("channel-section",
                             fit["expectation"]["candidate_feature_id"])
            report = json.loads(
                (out / "commission_report.json").read_text(encoding="utf-8"))
            check = next(item for item in report["checks"]
                         if item["check_id"] == "feature-fit-channel")
            self.assertEqual("PASS", check["result"])
            self.assertIn("candidate_check", check["measured"])

    def test_fitted_acceptance_fails_when_built_candidate_measurement_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            contract = runner._contract_from(
                T.get("c_clip"),
                _request(out, template="c_clip", params=self.BASE),
                fit_acceptance=fitted.acceptance_contract(
                    *fitted.validate(self.SPEC)[:2], {"channel": "bore_d"}
                ),
            )
            # Exercise the existing contract/check path with a real candidate
            # whose declared feature measurement is wrong. The fit row must not
            # pass just because its external metadata remains well formed.
            mesh = _clean_clip()
            mesh.apply_translation((0.0, 0.0, 1.0))
            _ctx, report, _screen = _measure(mesh, contract, out)
            fit_check = next(item for item in report["checks"]
                             if item["check_id"] == "feature-fit-channel")
            self.assertEqual("FAIL", fit_check["result"])
            self.assertEqual("FAIL", report["verdict"])

    def test_fitted_acceptance_rejects_candidate_inside_generic_but_outside_fit_band(self) -> None:
        """10.09 is inside a generic +/-0.12 check, but not target 10.00 +/-0.01."""
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            params = dict(self.BASE)
            params["bore_d"] = 10.09
            params["wall"] = 2.977512
            request = _request(out, template="c_clip", params=params)
            fit_rows = ({
                "interface_id": "channel",
                "measurement_feature": "bundle_across",
                "parameter": "bore_d",
                "nominal_mm": 10.0,
                "clearance_mm": [0.0, 0.0],
                "target_mm": 10.0,
                "uncertainty_mm": 0.0,
                "acceptance_tolerance_mm": 0.01,
            },)
            contract = runner._contract_from(
                T.get("c_clip"), request, fit_acceptance=fit_rows)
            from .backends.trimesh_manifold import build_c_clip
            mesh, _ = build_c_clip(params)
            _ctx, report, _screen = _measure(mesh, contract, out)
            generic = next(item for item in report["checks"]
                           if item["check_id"] == "feature-channel-section")
            fitted_check = next(item for item in report["checks"]
                                if item["check_id"] == "feature-fit-channel")
            self.assertEqual("PASS", generic["result"], generic)
            self.assertEqual("FAIL", fitted_check["result"], fitted_check)
            self.assertEqual(["channel-section"],
                             list(fitted_check["measured"]["candidate_check"]))

    def test_unsupported_fit_parameter_is_unavailable_not_inferred(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            measurements, interfaces, _ = fitted.validate(self.SPEC)
            rows = fitted.acceptance_contract(
                measurements, interfaces, {"channel": "unsupported_parameter"})
            contract = runner._contract_from(
                T.get("c_clip"), _request(out, template="c_clip", params=self.BASE),
                fit_acceptance=rows)
            _ctx, report, _screen = _measure(_clean_clip(), contract, out)
            fitted_check = next(item for item in report["checks"]
                                if item["check_id"] == "feature-fit-channel")
            self.assertEqual("FAIL", fitted_check["result"])
            self.assertEqual("UNAVAILABLE", fitted_check["status"])
            self.assertEqual("FIT_CANDIDATE_UNBOUND", fitted_check["error_code"])

    def test_fitted_acceptance_refuses_uncertainty_that_consumes_fit_band(self) -> None:
        response = {**self.SPEC,
                    "measurements": [{**self.SPEC["measurements"][0],
                                       "uncertainty_mm": 0.15}]}
        measurements, interfaces, unresolved = fitted.validate(response)
        with self.assertRaises(S.SchemaError) as caught:
            fitted.report(measurements=measurements, interfaces=interfaces,
                          unresolved=unresolved, reviewer={})
        self.assertIn("consumes the entire", str(caught.exception))

    def test_fitted_acceptance_refuses_a_tiny_remaining_margin(self) -> None:
        response = {**self.SPEC,
                    "measurements": [{**self.SPEC["measurements"][0],
                                       "uncertainty_mm": 0.145}]}
        measurements, interfaces, _ = fitted.validate(response)
        with self.assertRaises(S.SchemaError) as caught:
            fitted.fit_acceptance(measurements, interfaces)
        self.assertIn("minimum credible margin", str(caught.exception))

    def test_fitted_sizing_gate_rejects_uncertainty_before_deriving_parameters(self) -> None:
        response = {**self.SPEC,
                    "measurements": [{**self.SPEC["measurements"][0],
                                       "uncertainty_mm": 0.15}]}
        measurements, interfaces, _ = fitted.validate(response)
        with self.assertRaises(S.SchemaError):
            fitted.parameters_from(measurements, interfaces, {"channel": "bore_d"})

    def test_malformed_field_types_raise_schema_error_never_type_error(self) -> None:
        """Every one of these shapes reaches a set operation, a hash or float()
        in unchecked code, and each escapes as a TypeError. The schema check
        has to fire first, so the failure is a controlled SchemaError."""
        from . import schemas as S

        good = {"feature": "a", "nominal_mm": 10.0, "uncertainty_mm": 0.1,
                "method": "caliper", "datum": "x", "confidence": "A"}
        shapes = {
            "response not a dict": ["not", "a", "dict"],
            "measurement row not a dict": {"measurements": ["nope"],
                                           "interfaces": [], "unresolved": []},
            "feature not a string": {"measurements": [{**good, "feature": ["a"]}],
                                     "interfaces": [], "unresolved": []},
            "nominal not a number": {"measurements": [{**good, "nominal_mm": {"x": 1}}],
                                     "interfaces": [], "unresolved": []},
            "uncertainty not a number": {"measurements": [{**good, "uncertainty_mm": None}],
                                         "interfaces": [], "unresolved": []},
            "confidence not a string": {"measurements": [{**good, "confidence": ["A"]}],
                                        "interfaces": [], "unresolved": []},
            "unresolved not strings": {"measurements": [], "interfaces": [],
                                       "unresolved": [42]},
            "interface row not a dict": {"measurements": [good], "interfaces": [7],
                                         "unresolved": []},
            "interface id not a string": {
                "measurements": [good],
                "interfaces": [{"interface_id": 1, "measurement": "a",
                                "fit_class": "slip"}],
                "unresolved": []},
            "interface measurement not a string": {
                "measurements": [good],
                "interfaces": [{"interface_id": "i", "measurement": ["a"],
                                "fit_class": "slip"}],
                "unresolved": []},
        }
        for name, payload in shapes.items():
            with self.subTest(shape=name):
                with self.assertRaises(S.SchemaError):
                    fitted.validate(payload)

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
            if hasattr(packet, "payload") and "review_envelope" in packet.payload:
                return {**response, "review_envelope": packet.payload["review_envelope"]}
            return response

        result = runner.run(_full_request(out, verify_call=call,
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
            payload = seen[0].payload

            # An allow-list, not a search for a filename. This asserted
            # `"model.py" not in json.dumps(payload)`, which a mutation defeats
            # by putting the source under the key `model_py` -- the substring
            # disappears and the designer's reasoning is still in the packet.
            allowed = {"brief", "task", "intent_manifest", "model_contract",
                       "artifact_manifest", "commission_report",
                       "manufacturing_report", "witness", "specification",
                       "questions", "response_schema", "review_envelope"}
            self.assertEqual(set(), set(payload) - allowed,
                             "the verifier's packet grew a key nobody vetted; if it "
                             "belongs there, add it to `allowed` deliberately")
            self.assertIn("brief", payload)
            self.assertIn("commission_report", payload)

            # And nothing anywhere in it may carry Python source. The verifier
            # exists to disagree with the designer, and it cannot do that having
            # read how the designer got there.
            # Markers of Python source, not library names: `trimesh` is in there
            # legitimately as the backend identifier, and asserting on it would
            # be asserting the packet does not say which engine built the part.
            blob = json.dumps(payload)
            for tell in ("import ", "def ", "model.py", "lambda ", "return "):
                with self.subTest(tell=tell):
                    self.assertNotIn(tell, blob)

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
                updated_utc="1970-01-01T00:00:00Z", render=False,
                printer="Test Printer",
                material={"process": "FDM", "material": "PLA"},
                nozzle={"diameter_mm": 0.4},
                orientation={"model_to_printer_matrix": "identity", "bed_z_mm": 0.0}))
            self.assertFalse(result.ok)
            self.assertIn("requires independent verification", result.message)


class CacheTest(unittest.TestCase):
    """A cache is a claim that two runs would agree. The key has to name every
    input that could make them differ, or it is a way of serving a stale answer
    with a fresh-looking receipt."""

    def _job(self, out: Path, cache: Path, **kw):
        return runner.run(_request(out, cache_dir=cache, **kw))

    def _status(self, out: Path) -> str:
        return json.loads(
            (out / "artifact_manifest.json").read_text(encoding="utf-8"))["cache"]["status"]

    def test_a_second_identical_run_hits(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            cache = Path(raw) / "cache"
            first, second = Path(raw) / "a", Path(raw) / "b"
            self._job(first, cache)
            self._job(second, cache)
            self.assertEqual("stored", self._status(first))
            self.assertEqual("hit", self._status(second))

    def test_a_changed_parameter_misses(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            cache = Path(raw) / "cache"
            self._job(Path(raw) / "a", cache)
            other = Path(raw) / "b"
            self._job(other, cache, params={**CLIP, "wall": 3.5})
            self.assertEqual("stored", self._status(other))

    def test_the_key_names_everything_that_could_change_the_answer(self) -> None:
        """Each of these has produced a different mesh or a different measurement
        at some point; a key blind to any of them serves the wrong bytes."""
        from . import cache as K

        with tempfile.TemporaryDirectory() as raw:
            contract = _contract(Path(raw))
            base = K.key_for(contract, backend_version="v1",
                             tessellation={"sections": 96}, root=Path(raw))
            for field, value in (("backend_version", "v2"),
                                 ("tessellation", {"sections": 32}),
                                 ("schema_version", 99),
                                 ("generation", 2),
                                 ("domain_id", "other"),
                                 ("step_required", True),
                                 ("lock_sha256", "moved")):
                with self.subTest(differs=field):
                    other = dataclasses.replace(base, **{field: value})
                    self.assertNotEqual(base.digest(), other.digest())

    def test_a_corrupt_entry_is_a_miss_not_a_failure(self) -> None:
        """A cache that raises on a bad byte turns a stale file into a failed job.
        A miss costs one rebuild and cannot be worse than not caching."""
        from . import cache as K

        with tempfile.TemporaryDirectory() as raw:
            cache = Path(raw) / "cache"
            out = Path(raw) / "a"
            self._job(out, cache)

            contract = _contract(out)
            key = K.key_for(contract, backend_version="x", tessellation={}, root=Path(raw))
            store = K.Cache(cache)
            slot = next(p for p in cache.iterdir() if p.is_dir())
            (slot / "cache_receipt.json").write_text("{ not json", encoding="utf-8")
            self.assertIsNone(store.lookup(key))

    def test_a_cache_receipt_with_an_unknown_schema_is_a_miss(self) -> None:
        from . import cache as K

        with tempfile.TemporaryDirectory() as raw:
            cache = Path(raw) / "cache"
            out = Path(raw) / "a"
            self._job(out, cache)
            contract = _contract(out)
            key = K.key_for(contract, backend_version="x", tessellation={}, root=Path(raw))
            store = K.Cache(cache)
            slot = next(p for p in cache.iterdir() if p.is_dir())
            payload = json.loads((slot / "cache_receipt.json").read_text(encoding="utf-8"))
            payload["schema_version"] = K.CACHE_RECEIPT_SCHEMA + 1
            (slot / "cache_receipt.json").write_text(json.dumps(payload), encoding="utf-8")
            self.assertIsNone(store.lookup(key))

    def test_a_tampered_artifact_is_a_miss(self) -> None:
        """Hashes are recomputed from the bytes. This pipeline exists because an
        entered hash is not a hash."""
        with tempfile.TemporaryDirectory() as raw:
            cache = Path(raw) / "cache"
            first = Path(raw) / "a"
            self._job(first, cache)
            slot = next(p for p in cache.iterdir() if p.is_dir())
            stl = next(p for p in slot.iterdir() if p.suffix == ".stl")
            stl.write_bytes(stl.read_bytes() + b"\n")

            second = Path(raw) / "b"
            self._job(second, cache)
            self.assertEqual("stored", self._status(second),
                             "tampered bytes must not be served as a hit")

    def test_caching_is_off_unless_asked_for(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            _run(out)
            self.assertEqual("disabled", self._status(out))

    def test_a_safety_review_is_not_reused_because_the_geometry_matched(self) -> None:
        """The identity has to move when the reviewer does, not only when the
        part does. Comparing it against the geometry key proves nothing -- two
        digests over two unrelated payloads differ by construction."""
        from . import safety as SF

        packet = SF.Packet(stage=1, payload={"a": 1})
        base = {"model_snapshot": "m", "prompt_hash": "p", "policy_version": "1",
                "reasoning_settings": "none", "inference_config": "{}",
                "image_preprocessing": "none"}
        first = SF.cache_identity(packet, reviewer=base)
        for field in base:
            with self.subTest(reviewer_differs=field):
                self.assertNotEqual(
                    first, SF.cache_identity(packet, reviewer={**base, field: "moved"}),
                    f"a reviewer differing only in {field} is a different reviewer")
        self.assertNotEqual(first, SF.cache_identity(
            SF.Packet(stage=1, payload={"a": 2}), reviewer=base))


class CliReviewTest(unittest.TestCase):
    """`design-tool run-job` has to be able to finish the jobs the pipeline
    supports. It wired none of the review hooks, so a CONSEQUENTIAL job could
    not complete through the documented production path at all."""

    CLIP_JOB = {
        "job_id": "cli", "template": "c_clip", "consequence": "CONSEQUENTIAL",
        "updated_utc": "1970-01-01T00:00:00Z", "stated": [],
        "reviewer": {"model_snapshot": "test"},
        "parameters": CLIP,
        "printer": TEST_PRINTER, "material": TEST_MATERIAL,
        "nozzle": TEST_NOZZLE, "orientation": TEST_ORIENTATION,
    }

    def _job_dir(self, root: Path, **over) -> Path:
        job = root / "job"
        job.mkdir(parents=True, exist_ok=True)
        (job / "brief.md").write_text("a clip", encoding="utf-8")
        (job / "job.json").write_text(json.dumps({**self.CLIP_JOB, **over}), encoding="utf-8")
        return job

    def _run(self, job: Path) -> int:
        from . import cli
        return cli.run_job([str(job), "--no-render"])

    def test_a_consequential_job_asks_for_the_review_it_needs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            job = self._job_dir(Path(raw))
            code = self._run(job)

            self.assertEqual(cli_module().NEEDS_REVIEW, code,
                             "a job needing a review is neither a pass nor a crash")
            packet = job / "reviews" / "safety_packet.json"
            self.assertTrue(packet.is_file(), "the evidence has to be written down")
            payload = json.loads(packet.read_text(encoding="utf-8"))
            self.assertEqual("CONSEQUENTIAL", payload["consequence"])
            self.assertNotIn("verification", payload,
                             "stage 1 must not see the verifier's conclusion")

    def test_missing_explicit_job_inputs_are_refused_not_defaulted(self) -> None:
        for field in ("consequence", "printer", "material", "nozzle", "orientation"):
            with self.subTest(missing=field), tempfile.TemporaryDirectory() as raw:
                job = self._job_dir(Path(raw))
                spec = json.loads((job / "job.json").read_text(encoding="utf-8"))
                del spec[field]
                (job / "job.json").write_text(json.dumps(spec), encoding="utf-8")
                with self.assertRaises(SystemExit) as caught:
                    self._run(job)
                self.assertIn(field, str(caught.exception))

    def test_malformed_job_json_reports_a_detailed_parse_error(self) -> None:
        """A broken job.json must name where the JSON is broken, not traceback.

        job.json is the contract's own source. When it does not parse, the CLI
        has to hand back the decoder's position so the author can fix it, rather
        than dumping a JSONDecodeError that reads as a crash in the tool."""
        with tempfile.TemporaryDirectory() as raw:
            job = self._job_dir(Path(raw))
            (job / "job.json").write_text('{ "job_id": "x", ', encoding="utf-8")
            with self.assertRaises(SystemExit) as caught:
                self._run(job)
            message = str(caught.exception)
            self.assertIn("job.json", message)
            self.assertIn("not valid JSON", message)
            self.assertRegex(message, r"line \d+ column \d+")

    def test_an_invalid_contract_value_reports_the_field_and_value(self) -> None:
        """A bad consequence class is the contract failing to parse. The CLI must
        surface the offending field and value, not a bare SchemaError traceback."""
        with tempfile.TemporaryDirectory() as raw:
            job = self._job_dir(Path(raw), consequence="MAYBE")
            with self.assertRaises(SystemExit) as caught:
                self._run(job)
            message = str(caught.exception)
            self.assertIn("MAYBE", message)
            self.assertIn("consequence", message)
            self.assertIn("not a valid contract", message)

    def test_non_object_job_json_reports_the_contract_shape(self) -> None:
        """A valid JSON scalar is still not a job contract."""
        with tempfile.TemporaryDirectory() as raw:
            job = self._job_dir(Path(raw))
            (job / "job.json").write_text("[]", encoding="utf-8")
            with self.assertRaises(SystemExit) as caught:
                self._run(job)
            message = str(caught.exception)
            self.assertIn("job.json", message)
            self.assertIn("JSON object", message)
            self.assertIn("list", message)

    def test_invalid_nested_job_shapes_are_reported_without_traceback(self) -> None:
        """Nested manufacturing fields are contract input, not unchecked kwargs."""
        cases = (
            ("material", ["FDM", "PLA"], "material must be an object"),
            ("material", {"process": "FDM", "material": 7}, "material.material must be a string"),
            ("nozzle", {"diameter_mm": "0.4"}, "nozzle.diameter_mm must be a finite number"),
            ("orientation", {"model_to_printer_matrix": "identity", "bed_z_mm": "0"},
             "orientation.bed_z_mm must be a finite number"),
            ("stated", ["bore_d", 7], "stated must be a list of strings"),
            ("parameters", [1, 2], "parameters must be an object"),
            ("parameters", {"bore_d": "12"}, "parameters.bore_d must be a finite number"),
            ("interface_map", ["channel"], "interface_map must be an object"),
            ("candidate_strategy", "MANY", "job.candidate_strategy"),
            ("candidate_strategy", True, "job.candidate_strategy"),
            ("external_geometry", "false", "external_geometry must be a boolean"),
        )
        for field, value, expected in cases:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as raw:
                job = self._job_dir(Path(raw), **{field: value})
                with self.assertRaises(SystemExit) as caught:
                    self._run(job)
                message = str(caught.exception)
                self.assertIn(expected, message)
                self.assertNotIn("Traceback", message)

    def test_invalid_utf8_job_json_reports_a_contract_error(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            job = self._job_dir(Path(raw))
            (job / "job.json").write_bytes(b'{"job_id": "x", "bad": "\xff"}')
            with self.assertRaises(SystemExit) as caught:
                self._run(job)
            message = str(caught.exception)
            self.assertIn("job.json", message)
            self.assertIn("not valid UTF-8", message)
            self.assertNotIn("Traceback", message)

    def test_answering_the_packet_completes_the_job(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            job = self._job_dir(Path(raw))
            self._run(job)
            room = job / "reviews"
            safety_envelope = json.loads(
                (room / "safety_packet.json").read_text(encoding="utf-8")).get("review_envelope")
            (room / "safety_response.json").write_text(json.dumps({
                "decision": "PASS", "failure_modes": [], "safety_concerns": [],
                "missing_evidence": [], "required_actions": [],
                "summary": "a cable clip", "review_envelope": safety_envelope}), encoding="utf-8")
            self._run(job)

            final = json.loads((job / "final_status.json").read_text(encoding="utf-8"))
            self.assertEqual("CONSEQUENTIAL", final["consequence"])
            self.assertEqual("NEEDS_MORE_EVIDENCE", final["final_status"])
            self.assertNotEqual("FAILED", final["final_status"])
            self.assertFalse((room / "verification_packet.json").exists(),
                             "DIRECT consequential jobs do not dispatch the normal verifier")

    def test_the_cli_never_answers_a_review_itself(self) -> None:
        """The one thing this program must not do. A deterministic tool that
        returned a safety verdict would be inventing it."""
        with tempfile.TemporaryDirectory() as raw:
            job = self._job_dir(Path(raw))
            self._run(job)
            self.assertFalse((job / "reviews" / "safety_response.json").exists())
            self.assertFalse((job / "final_status.json").exists(),
                             "no receipt may exist for a job that never got its review")

    def test_stale_response_is_rejected_but_current_packet_is_written(self) -> None:
        """If an old response is already on disk, the CLI must still write the
        current request packet so the user can answer the current envelope."""
        with tempfile.TemporaryDirectory() as raw:
            job = self._job_dir(Path(raw))
            self._run(job)
            room = job / "reviews"
            first_envelope = json.loads(
                (room / "safety_packet.json").read_text(encoding="utf-8")).get("review_envelope")
            # Write a stale response for the first envelope.
            (room / "safety_response.json").write_text(json.dumps({
                "decision": "PASS", "failure_modes": [], "safety_concerns": [],
                "missing_evidence": [], "required_actions": [],
                "summary": "stale", "review_envelope": first_envelope}), encoding="utf-8")

            # Change a parameter so the second run has a different envelope.
            (job / "job.json").write_text(json.dumps({
                **self.CLIP_JOB, "parameters": {**CLIP, "wall": 4.0}}), encoding="utf-8")
            code = self._run(job)
            self.assertEqual(1, code, "a stale response must not be promoted")
            self.assertTrue((room / "safety_packet.json").is_file(),
                            "the current packet must be written before reporting stale")
            packet = json.loads((room / "safety_packet.json").read_text(encoding="utf-8"))
            self.assertNotEqual(first_envelope["packet_sha256"],
                                packet["review_envelope"]["packet_sha256"])

    def test_malformed_safety_response_json_is_a_controlled_failure(self) -> None:
        """An answer file that is not JSON must come back as a blocked job with
        an error receipt -- the same as any other malformed review -- never a
        JSONDecodeError traceback out of the CLI."""
        with tempfile.TemporaryDirectory() as raw:
            job = self._job_dir(Path(raw))
            self.assertEqual(cli_module().NEEDS_REVIEW, self._run(job))
            (job / "reviews" / "safety_response.json").write_text(
                "this is not json {", encoding="utf-8")
            code = self._run(job)
            self.assertEqual(1, code)
            receipt = json.loads(
                (job / "safety_verification_report.json").read_text(encoding="utf-8"))
            self.assertIn("not valid JSON", receipt["error"])

    def test_malformed_verification_response_json_is_a_controlled_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            job = self._job_dir(Path(raw), consequence="INCONSEQUENTIAL")
            self.assertEqual(1, self._run(job))
            self.assertFalse((job / "reviews").exists())
            code = self._run(job)
            self.assertEqual(1, code)
            self.assertFalse((job / "verification_report.json").exists(),
                             "DIRECT does not read or dispatch a normal verification response")


def cli_module():
    from . import cli
    return cli


class ReviewEnvelopeTest(unittest.TestCase):
    """A review response is only as good as the request it answers.

    The envelope binds the response to the exact packet, artifact, witness and
    evidence it reviewed. A stale or cross-kind answer must not be promoted to a
    passing status, and a PASS that carries contradictions must fail closed.
    """

    SAFETY_REVIEWER = {"model_snapshot": "m", "prompt_hash": "p",
                       "policy_version": "1", "reasoning_settings": "none",
                       "inference_config": "{}", "image_preprocessing": "none"}

    def _safety_call(self, response):
        def call(packet):
            if hasattr(packet, "payload") and "review_envelope" in packet.payload:
                return {**response, "review_envelope": packet.payload["review_envelope"]}
            return response
        return call

    def _verify_call(self, response):
        def call(packet):
            if hasattr(packet, "payload") and "review_envelope" in packet.payload:
                return {**response, "review_envelope": packet.payload["review_envelope"]}
            return response
        return call

    def _good_safety(self):
        return {"decision": "PASS", "failure_modes": [], "safety_concerns": [],
                "missing_evidence": [], "required_actions": [], "summary": "ok"}

    def _good_verification(self):
        return {"decision": "PASS", "defects": [], "unmet_requirements": [],
                "missing_evidence": [], "summary": "ok"}

    def test_evidence_paths_must_stay_project_relative(self) -> None:
        from . import review as R

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "inside.jpg").write_bytes(b"evidence")
            for name in ("../outside.jpg", "/outside.jpg", "C:/outside.jpg",
                         "\\\\server\\share\\outside.jpg"):
                with self.subTest(path=name):
                    with self.assertRaises(R.ReviewError):
                        R.build_envelope(
                            kind="safety", job_id="t", revision="r", packet_hash="p",
                            reviewer={}, contract_hash="c", evidence=(name,),
                            evidence_dir=root,
                        )

    def test_safety_response_is_bound_to_its_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            runner.run(_request(
                Path(raw), consequence="CONSEQUENTIAL",
                safety_call=self._safety_call(self._good_safety()),
                verify_call=_looked_at,
                reviewer=self.SAFETY_REVIEWER))
            report = json.loads((Path(raw) / "safety_verification_report.json").read_text(
                encoding="utf-8"))
            self.assertEqual("safety", report["review_envelope"]["kind"])
            self.assertEqual(report["evidence_packet_sha256"],
                             report["review_envelope"]["packet_sha256"])

    def test_verification_response_is_bound_to_its_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result = runner.run(_full_request(
                Path(raw), verify_call=self._verify_call(self._good_verification()),
                reviewer={"model_snapshot": "test"}))
            self.assertEqual("VERIFIED", result.final_status["final_status"])
            report = json.loads((Path(raw) / "verification_report.json").read_text(
                encoding="utf-8"))
            self.assertEqual("verification", report["review_envelope"]["kind"])

    def test_stale_safety_response_after_parameter_change_is_rejected(self) -> None:
        """Changing a parameter changes the contract and the packet; an old
        answer must not be stampable onto the new job."""
        response = self._good_safety()
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            seen = []
            def capture(packet):
                seen.append(packet)
                return {**response, "review_envelope": packet.payload["review_envelope"]}
            runner.run(_request(out, consequence="CONSEQUENTIAL",
                                safety_call=capture, reviewer=self.SAFETY_REVIEWER))
            stale = seen[0].payload["review_envelope"]

            result = runner.run(_request(
                out, consequence="CONSEQUENTIAL",
                params={**CLIP, "wall": 4.0},
                safety_call=lambda p: {**response, "review_envelope": stale},
                reviewer=self.SAFETY_REVIEWER))
            self.assertFalse(result.ok)
            self.assertEqual("safety", result.stage)

    def test_stale_safety_response_after_revision_change_is_rejected(self) -> None:
        response = self._good_safety()
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            seen = []
            def capture(packet):
                seen.append(packet)
                return {**response, "review_envelope": packet.payload["review_envelope"]}
            runner.run(_request(out, consequence="CONSEQUENTIAL",
                                safety_call=capture, reviewer=self.SAFETY_REVIEWER))
            stale = seen[0].payload["review_envelope"]
            result = runner.run(runner.JobRequest(
                job_id="t", brief_path=out / "brief.md", template="c_clip",
                parameters=dict(CLIP), stated=frozenset({"bore_d"}),
                consequence="CONSEQUENTIAL", out_dir=out,
                updated_utc="2026-01-01T00:00:00Z", render=False,
                safety_call=lambda p: {**response, "review_envelope": stale},
                reviewer=self.SAFETY_REVIEWER,
                printer="Test Printer",
                material={"process": "FDM", "material": "PLA"},
                nozzle={"diameter_mm": 0.4},
                orientation={"model_to_printer_matrix": "identity", "bed_z_mm": 0.0}))
            self.assertFalse(result.ok)
            self.assertEqual("safety", result.stage)

    def test_safety_response_for_wrong_kind_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            seen = []
            def capture(packet):
                seen.append(packet)
                return {**self._good_verification(),
                        "review_envelope": packet.payload["review_envelope"]}
            runner.run(_full_request(out, verify_call=capture,
                                     reviewer={"model_snapshot": "test"}))
            wrong_envelope = seen[0].payload["review_envelope"]
            result = runner.run(_request(
                out, consequence="CONSEQUENTIAL",
                safety_call=lambda p: {**self._good_safety(),
                                       "review_envelope": wrong_envelope},
                reviewer=self.SAFETY_REVIEWER))
            self.assertFalse(result.ok)
            self.assertEqual("safety", result.stage)

    def test_safety_pass_with_failure_modes_fails_closed(self) -> None:
        response = {**self._good_safety(), "failure_modes": ["fracture"]}
        with tempfile.TemporaryDirectory() as raw:
            result = runner.run(_request(
                Path(raw), consequence="CONSEQUENTIAL",
                safety_call=self._safety_call(response),
                reviewer=self.SAFETY_REVIEWER))
            self.assertFalse(result.ok)
            self.assertEqual("safety", result.stage)

    def test_safety_pass_with_missing_evidence_fails_closed(self) -> None:
        response = {**self._good_safety(), "missing_evidence": ["load direction"]}
        with tempfile.TemporaryDirectory() as raw:
            result = runner.run(_request(
                Path(raw), consequence="CONSEQUENTIAL",
                safety_call=self._safety_call(response),
                reviewer=self.SAFETY_REVIEWER))
            self.assertFalse(result.ok)
            self.assertEqual("safety", result.stage)

    def test_safety_pass_with_empty_summary_fails_closed(self) -> None:
        response = {**self._good_safety(), "summary": "   "}
        with tempfile.TemporaryDirectory() as raw:
            result = runner.run(_request(
                Path(raw), consequence="CONSEQUENTIAL",
                safety_call=self._safety_call(response),
                reviewer=self.SAFETY_REVIEWER))
            self.assertFalse(result.ok)
            self.assertEqual("safety", result.stage)

    def test_verification_pass_with_defects_fails_closed(self) -> None:
        response = {**self._good_verification(),
                    "defects": [{"summary": "x", "owning_loop": "CONTRACT",
                                 "expected_vs_observed": "x", "evidence": "x",
                                 "severity": "x"}]}
        with tempfile.TemporaryDirectory() as raw:
            result = runner.run(_full_request(
                Path(raw), verify_call=self._verify_call(response),
                reviewer={"model_snapshot": "test"}))
            self.assertFalse(result.ok)
            self.assertEqual("verification", result.stage)

    def test_verification_pass_with_unmet_requirements_fails_closed(self) -> None:
        response = {**self._good_verification(),
                    "unmet_requirements": ["strain relief not modelled"]}
        with tempfile.TemporaryDirectory() as raw:
            result = runner.run(_full_request(
                Path(raw), verify_call=self._verify_call(response),
                reviewer={"model_snapshot": "test"}))
            self.assertFalse(result.ok)
            self.assertEqual("verification", result.stage)

    def test_verification_pass_with_empty_summary_fails_closed(self) -> None:
        response = {**self._good_verification(), "summary": ""}
        with tempfile.TemporaryDirectory() as raw:
            result = runner.run(_full_request(
                Path(raw), verify_call=self._verify_call(response),
                reviewer={"model_snapshot": "test"}))
            self.assertFalse(result.ok)
            self.assertEqual("verification", result.stage)

    def test_malformed_safety_response_produces_controlled_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result = runner.run(_request(
                Path(raw), consequence="CONSEQUENTIAL",
                safety_call=lambda p: {"decision": "BANANA", "summary": "?"},
                reviewer=self.SAFETY_REVIEWER))
            self.assertFalse(result.ok)
            self.assertEqual("safety", result.stage)
            self.assertIn("safety_verification_report.json",
                          [p.name for p in Path(raw).iterdir()])

    def test_malformed_verification_response_produces_controlled_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result = runner.run(_full_request(
                Path(raw), verify_call=lambda p: {"decision": "PASS", "summary": ""},
                reviewer={"model_snapshot": "test"}))
            self.assertFalse(result.ok)
            self.assertEqual("verification", result.stage)

    def test_changed_fitted_evidence_byte_rejects_spec_response(self) -> None:
        """A FITTED response bound to one set of evidence bytes cannot be
        reused after the evidence file is touched."""
        spec = {"measurements": [{"feature": "bundle_across", "nominal_mm": 12.4,
                                  "uncertainty_mm": 0.15, "method": "caliper",
                                  "datum": "widest", "confidence": "A"}],
                "interfaces": [{"interface_id": "channel", "measurement": "bundle_across",
                                "fit_class": "slip"}],
                "unresolved": []}
        base = {"bore_d": 12.0, "wall": 3.0, "height": 9.0, "mouth_gap": 9.0,
                "flange_w": 40.0, "flange_d": 22.0, "flange_t": 5.0, "screw_d": 4.8}
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            (out / "photo1.jpg").write_bytes(b"first")
            seen = []
            def capture(request):
                seen.append(request)
                return {**spec, "review_envelope": request["review_envelope"]}
            runner.run(runner.JobRequest(
                job_id="fit", brief_path=out / "b.md", template="c_clip",
                parameters=dict(base), stated=frozenset({"flange_w"}),
                consequence="INCONSEQUENTIAL", out_dir=out,
                updated_utc="1970-01-01T00:00:00Z", render=False,
                external_geometry=True, evidence=("photo1.jpg",), spec_call=capture,
                interface_map={"channel": "bore_d"},
                reviewer={"model_snapshot": "test"},
                printer="Test Printer",
                material={"process": "FDM", "material": "PLA"},
                nozzle={"diameter_mm": 0.4},
                orientation={"model_to_printer_matrix": "identity", "bed_z_mm": 0.0}))
            stale = seen[0]["review_envelope"]

            (out / "photo1.jpg").write_bytes(b"second")
            result = runner.run(runner.JobRequest(
                job_id="fit", brief_path=out / "b.md", template="c_clip",
                parameters=dict(base), stated=frozenset({"flange_w"}),
                consequence="INCONSEQUENTIAL", out_dir=out,
                updated_utc="1970-01-01T00:00:00Z", render=False,
                external_geometry=True, evidence=("photo1.jpg",),
                spec_call=lambda r: {**spec, "review_envelope": stale},
                interface_map={"channel": "bore_d"},
                reviewer={"model_snapshot": "test"},
                printer="Test Printer",
                material={"process": "FDM", "material": "PLA"},
                nozzle={"diameter_mm": 0.4},
                orientation={"model_to_printer_matrix": "identity", "bed_z_mm": 0.0}))
            self.assertFalse(result.ok)
            self.assertEqual("specification", result.stage)

    def test_malformed_specification_response_produces_controlled_failure(self) -> None:
        base = {"bore_d": 12.0, "wall": 3.0, "height": 9.0, "mouth_gap": 9.0,
                "flange_w": 40.0, "flange_d": 22.0, "flange_t": 5.0, "screw_d": 4.8}
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            (out / "photo1.jpg").write_bytes(b"evidence")
            result = runner.run(runner.JobRequest(
                job_id="fit", brief_path=out / "b.md", template="c_clip",
                parameters=dict(base), stated=frozenset({"flange_w"}),
                consequence="INCONSEQUENTIAL", out_dir=out,
                updated_utc="1970-01-01T00:00:00Z", render=False,
                external_geometry=True, evidence=("photo1.jpg",),
                spec_call=lambda r: {"measurements": [], "interfaces": [],
                                     "unresolved": []},
                interface_map={"channel": "bore_d"},
                reviewer={"model_snapshot": "test"},
                printer="Test Printer",
                material={"process": "FDM", "material": "PLA"},
                nozzle={"diameter_mm": 0.4},
                orientation={"model_to_printer_matrix": "identity", "bed_z_mm": 0.0}))
            self.assertFalse(result.ok)
            self.assertEqual("specification", result.stage)

    def test_stale_verification_response_after_render_change_is_rejected(self) -> None:
        """Changing whether images are rendered changes the witness record, so
        an answer from the other setting must not be accepted."""
        response = self._good_verification()
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            seen = []
            def capture(packet):
                seen.append(packet)
                return {**response, "review_envelope": packet.payload["review_envelope"]}
            runner.run(_full_request(out, verify_call=capture,
                                     reviewer={"model_snapshot": "test"}))
            stale = seen[0].payload["review_envelope"]
            result = runner.run(_full_request(
                out, render=True,
                verify_call=lambda p: {**response, "review_envelope": stale},
                reviewer={"model_snapshot": "test"}))
            self.assertFalse(result.ok)
            self.assertEqual("verification", result.stage)

    def test_status_does_not_promote_unbound_safety_pass(self) -> None:
        """Even if a safety report somehow lacks the envelope, status must not
        treat it as a valid pass."""
        with tempfile.TemporaryDirectory() as raw:
            contract = _contract(Path(raw))
        final = status.decide(
            contract=C.Contract(**{**contract.__dict__, "consequence": "CONSEQUENTIAL"}),
            commission_report={"verdict": "PASS", "witness": {"rendered": True}},
            screening={"overall": "CLEAR", "calibrated": True},
            manufacturing=None, artifact={"contract_sha256": "a", "stl_sha256": "b",
                                          "source_sha256": "c"},
            safety={"decision": "PASS", "summary": "ok"},
            verification=None, updated_utc="t")
        self.assertNotIn(final["final_status"], ("COMMISSIONED", "VERIFIED"))

    def test_status_does_not_promote_a_stale_safety_envelope(self) -> None:
        """A safety report bound to a different request must not let the status
        reach COMMISSIONED or VERIFIED, even if every field looks like a pass."""
        from . import review as R

        with tempfile.TemporaryDirectory() as raw:
            contract = _contract(Path(raw))
        consequential = C.Contract(**{**contract.__dict__, "consequence": "CONSEQUENTIAL"})
        stale_envelope = R.build_envelope(
            kind="safety", job_id="t", revision="old",
            packet_hash="stale-packet", reviewer={},
            contract_hash="stale-contract").as_dict()
        safety_report = {**self._good_safety(), "review_envelope": stale_envelope}
        current = R.build_envelope(
            kind="safety", job_id="t", revision="new",
            packet_hash="current-packet", reviewer={},
            contract_hash=consequential.contract_hash())
        final = status.decide(
            contract=consequential,
            commission_report={"verdict": "PASS", "witness": {"rendered": True}},
            screening={"overall": "CLEAR", "calibrated": True},
            manufacturing=None, artifact={"contract_sha256": consequential.contract_hash(),
                                          "stl_sha256": "b", "source_sha256": "c"},
            safety=safety_report, verification=None, updated_utc="t",
            safety_envelope=current)
        self.assertNotIn(final["final_status"], ("COMMISSIONED", "VERIFIED"))

    def test_status_does_not_promote_a_stale_verification_envelope(self) -> None:
        """An independent verification report bound to a different request must
        not be promoted to VERIFIED."""
        from . import review as R

        with tempfile.TemporaryDirectory() as raw:
            contract = _contract(Path(raw))
        stale_envelope = R.build_envelope(
            kind="verification", job_id="t", revision="old",
            packet_hash="stale-packet", reviewer={},
            contract_hash="stale-contract").as_dict()
        verification_report = {**self._good_verification(),
                               "review_envelope": stale_envelope}
        current = R.build_envelope(
            kind="verification", job_id="t", revision="new",
            packet_hash="current-packet", reviewer={},
            contract_hash=contract.contract_hash())
        final = status.decide(
            contract=contract,
            commission_report={"verdict": "PASS", "witness": {"rendered": True}},
            screening={"overall": "CLEAR", "calibrated": True},
            manufacturing=None, artifact={"contract_sha256": contract.contract_hash(),
                                          "stl_sha256": "b", "source_sha256": "c"},
            safety=None, verification=verification_report, updated_utc="t",
            verification_envelope=current)
        self.assertNotIn(final["final_status"], ("COMMISSIONED", "VERIFIED"))

    def test_partial_safety_envelope_with_expected_envelope_fails_closed(self) -> None:
        """A fragment of an envelope is not a binding. Missing digest fields
        must fail closed even when the expected envelope is supplied -- a
        partial envelope cannot yield a PASS-equivalent status."""
        from . import review as R

        with tempfile.TemporaryDirectory() as raw:
            contract = _contract(Path(raw))
        consequential = C.Contract(**{**contract.__dict__, "consequence": "CONSEQUENTIAL"})
        expected = R.build_envelope(
            kind="safety", job_id=consequential.job_id, revision="t",
            packet_hash="p", reviewer={}, contract_hash=consequential.contract_hash())
        final = status.decide(
            contract=consequential,
            commission_report={"verdict": "PASS", "witness": {"rendered": True}},
            screening={"overall": "CLEAR", "calibrated": True},
            manufacturing=None, artifact={"contract_sha256": consequential.contract_hash(),
                                          "stl_sha256": "b", "source_sha256": "c"},
            safety={"decision": "PASS", "summary": "ok",
                    "review_envelope": {"kind": "safety", "protocol_version": 1}},
            verification=None, updated_utc="t",
            safety_envelope=expected)
        self.assertNotIn(final["final_status"], ("COMMISSIONED", "VERIFIED"))

    def test_a_bound_report_still_needs_the_expected_envelope(self) -> None:
        """The expected envelope is mandatory, not optional. A report carrying
        the full current envelope must still fail closed when the caller
        supplies nothing to bind it against."""
        from . import review as R

        with tempfile.TemporaryDirectory() as raw:
            contract = _contract(Path(raw))
        envelope = R.build_envelope(
            kind="verification", job_id=contract.job_id, revision="t",
            packet_hash="p", reviewer={}, contract_hash=contract.contract_hash())
        final = status.decide(
            contract=contract,
            commission_report={"verdict": "PASS",
                               "witness": {"rendered": True, "sections": []}},
            screening={"overall": "CLEAR", "calibrated": True},
            manufacturing=None, artifact={"contract_sha256": contract.contract_hash(),
                                          "stl_sha256": "b", "source_sha256": "c"},
            safety=None,
            verification={"decision": "PASS", "summary": "ok",
                          "review_envelope": envelope.as_dict()},
            updated_utc="t")
        self.assertNotIn(final["final_status"], ("COMMISSIONED", "VERIFIED"))
        self.assertIn("unbound", final["allowed_claim"])

    def test_a_non_dict_safety_response_is_a_controlled_failure(self) -> None:
        """The binding check runs before the schema check on this path, so a
        response that is not a dict at all must still fail closed."""
        with tempfile.TemporaryDirectory() as raw:
            result = runner.run(_request(
                Path(raw), consequence="CONSEQUENTIAL",
                safety_call=lambda p: ["not", "a", "dict"],
                reviewer=self.SAFETY_REVIEWER))
            self.assertFalse(result.ok)
            self.assertEqual("safety", result.stage)

    def test_a_non_dict_verification_response_is_a_controlled_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result = runner.run(_full_request(
                Path(raw), verify_call=lambda p: 42,
                reviewer={"model_snapshot": "test"}))
            self.assertFalse(result.ok)
            self.assertEqual("verification", result.stage)

    def test_a_safety_call_that_raises_valueerror_is_a_controlled_failure(self) -> None:
        """Adapters parse JSON; a parse failure surfaces as ValueError, and the
        runner boundary must turn it into a blocked JobResult, not a traceback."""
        def bad_json(packet):
            raise ValueError("Expecting value: line 1 column 1 (char 0)")

        with tempfile.TemporaryDirectory() as raw:
            result = runner.run(_request(
                Path(raw), consequence="CONSEQUENTIAL",
                safety_call=bad_json, reviewer=self.SAFETY_REVIEWER))
            self.assertFalse(result.ok)
            self.assertEqual("safety", result.stage)
            self.assertIn("ValueError", result.message)

    def test_a_verification_call_that_raises_valueerror_is_a_controlled_failure(self) -> None:
        def bad_json(packet):
            raise ValueError("Expecting value: line 1 column 1 (char 0)")

        with tempfile.TemporaryDirectory() as raw:
            result = runner.run(_full_request(
                Path(raw), verify_call=bad_json,
                reviewer={"model_snapshot": "test"}))
            self.assertFalse(result.ok)
            self.assertEqual("verification", result.stage)
            self.assertIn("ValueError", result.message)

    def test_malformed_fitted_types_fail_closed_with_valid_envelope(self) -> None:
        """A correctly bound FITTED response with a malformed measurement type
        must become a controlled SchemaError/JobResult, never a TypeError."""
        base = {"bore_d": 12.0, "wall": 3.0, "height": 9.0, "mouth_gap": 9.0,
                "flange_w": 40.0, "flange_d": 22.0, "flange_t": 5.0, "screw_d": 4.8}
        bad_spec = {"measurements": [{"feature": ["not", "string"], "nominal_mm": 12.4,
                                      "uncertainty_mm": 0.15, "method": "caliper",
                                      "datum": "widest", "confidence": "A"}],
                    "interfaces": [], "unresolved": []}
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            (out / "photo1.jpg").write_bytes(b"evidence")
            result = runner.run(runner.JobRequest(
                job_id="fit", brief_path=out / "b.md", template="c_clip",
                parameters=dict(base), stated=frozenset({"flange_w"}),
                consequence="INCONSEQUENTIAL", out_dir=out,
                updated_utc="1970-01-01T00:00:00Z", render=False,
                external_geometry=True, evidence=("photo1.jpg",),
                spec_call=lambda r: {**bad_spec,
                                     "review_envelope": r["review_envelope"]},
                interface_map={"channel": "bore_d"},
                reviewer={"model_snapshot": "test"},
                printer="Test Printer",
                material={"process": "FDM", "material": "PLA"},
                nozzle={"diameter_mm": 0.4},
                orientation={"model_to_printer_matrix": "identity", "bed_z_mm": 0.0}))
            self.assertFalse(result.ok)
            self.assertEqual("specification", result.stage)
            self.assertIn("specification.json",
                          [p.name for p in Path(raw).iterdir()])

    def test_malformed_bound_spec_shapes_fail_closed_without_type_errors(self) -> None:
        """Every malformed but correctly bound specification shape must come
        back as a controlled JobResult. A TypeError would escape the runner
        entirely: no receipt, no final status, a traceback out of the CLI."""
        base = {"bore_d": 12.0, "wall": 3.0, "height": 9.0, "mouth_gap": 9.0,
                "flange_w": 40.0, "flange_d": 22.0, "flange_t": 5.0, "screw_d": 4.8}
        good = {"feature": "a", "nominal_mm": 10.0, "uncertainty_mm": 0.1,
                "method": "caliper", "datum": "x", "confidence": "A"}
        shapes = {
            "measurement row not a dict": {"measurements": ["nope"],
                                           "interfaces": [], "unresolved": []},
            "nominal not a number": {"measurements": [{**good, "nominal_mm": {"x": 1}}],
                                     "interfaces": [], "unresolved": []},
            "unresolved not strings": {"measurements": [], "interfaces": [],
                                       "unresolved": [42]},
            "interface row not a dict": {"measurements": [good], "interfaces": [7],
                                         "unresolved": []},
        }
        for name, bad_spec in shapes.items():
            with self.subTest(shape=name), tempfile.TemporaryDirectory() as raw:
                out = Path(raw)
                (out / "photo1.jpg").write_bytes(b"evidence")
                result = runner.run(runner.JobRequest(
                    job_id="fit", brief_path=out / "b.md", template="c_clip",
                    parameters=dict(base), stated=frozenset({"flange_w"}),
                    consequence="INCONSEQUENTIAL", out_dir=out,
                    updated_utc="1970-01-01T00:00:00Z", render=False,
                    external_geometry=True, evidence=("photo1.jpg",),
                    spec_call=lambda r: {**bad_spec,
                                         "review_envelope": r["review_envelope"]},
                    interface_map={"channel": "bore_d"},
                    reviewer={"model_snapshot": "test"},
                    printer="Test Printer",
                    material={"process": "FDM", "material": "PLA"},
                    nozzle={"diameter_mm": 0.4},
                    orientation={"model_to_printer_matrix": "identity", "bed_z_mm": 0.0}))
                self.assertFalse(result.ok)
                self.assertEqual("specification", result.stage)
                self.assertNotIn("TypeError", result.message)

    def test_an_unhashable_echoed_envelope_is_a_controlled_failure(self) -> None:
        """The digest hashes the echoed envelope. A reviewer that hand-assembles
        one can put a value in it that no JSON document can hold; that must be
        a ReviewError inside the runner, never a TypeError out of it."""
        base = {"bore_d": 12.0, "wall": 3.0, "height": 9.0, "mouth_gap": 9.0,
                "flange_w": 40.0, "flange_d": 22.0, "flange_t": 5.0, "screw_d": 4.8}
        spec = {"measurements": [], "interfaces": [], "unresolved": []}
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            (out / "photo1.jpg").write_bytes(b"evidence")

            def call(request):
                corrupt = dict(request["review_envelope"])
                corrupt["reviewer"] = {"snapshot": object()}
                return {**spec, "review_envelope": corrupt}

            result = runner.run(runner.JobRequest(
                job_id="fit", brief_path=out / "b.md", template="c_clip",
                parameters=dict(base), stated=frozenset({"flange_w"}),
                consequence="INCONSEQUENTIAL", out_dir=out,
                updated_utc="1970-01-01T00:00:00Z", render=False,
                external_geometry=True, evidence=("photo1.jpg",),
                spec_call=call, interface_map={"channel": "bore_d"},
                reviewer={"model_snapshot": "test"},
                printer="Test Printer",
                material={"process": "FDM", "material": "PLA"},
                nozzle={"diameter_mm": 0.4},
                orientation={"model_to_printer_matrix": "identity", "bed_z_mm": 0.0}))
            self.assertFalse(result.ok)
            self.assertEqual("specification", result.stage)
            self.assertIn("ReviewError", result.message)

    def test_malformed_envelope_mapping_fields_are_controlled(self) -> None:
        """Wrong-type nested envelope fields must parse into a controlled
        ReviewError -- or a plain False at the status surface check -- never a
        ValueError out of dict() or an AttributeError out of sorted()."""
        from . import review as R

        good = R.build_envelope(kind="safety", job_id="t", revision="r",
                                packet_hash="p", reviewer={}, contract_hash="c")
        env = good.as_dict()
        broken = {
            "reviewer a list": {**env, "reviewer": ["not-a-dict"]},
            "reviewer not a dict": {**env, "reviewer": 5},
            "artifact_hashes a list": {**env, "artifact_hashes": ["a"]},
            "witness_hashes a list": {**env, "witness_hashes": ["a"]},
            "evidence_hashes a list": {**env, "evidence_hashes": ["a"]},
            "evidence_digests a list": {**env, "evidence_digests": ["a"]},
            "evidence digest not a string": {**env,
                                             "evidence_digests": {"plan": 5}},
            "artifact hash not a string": {**env, "artifact_hashes": {"stl": 5}},
            "witness hash not a string": {**env, "witness_hashes": {"a.png": 5}},
            "evidence hash is null": {**env, "evidence_hashes": {"p.jpg": None}},
            "hash-map key not a string": {**env, "witness_hashes": {1: "x"}},
            "packet_sha256 not a string": {**env, "packet_sha256": 5},
            "protocol_version not an int": {**env, "protocol_version": "1"},
        }
        for name, payload in broken.items():
            with self.subTest(case=name):
                with self.assertRaises(R.ReviewError):
                    R.validate_response_envelope({"review_envelope": payload}, good)
                self.assertFalse(R.is_bound({"review_envelope": payload}, "safety",
                                            good.digest()))

    def test_a_non_string_evidence_entry_is_a_controlled_review_error(self) -> None:
        """Hashing joins each entry onto the evidence dir; a non-string entry
        must be refused before the join, not detonate as a TypeError there."""
        from . import review as R

        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            for name, kwargs in (
                    ("evidence entry", {"evidence": (42,), "evidence_dir": out}),
                    ("witness image", {"witness": {"images": [3]}, "witness_dir": out})):
                with self.subTest(case=name):
                    with self.assertRaises(R.ReviewError):
                        R.build_envelope(kind="safety", job_id="t", revision="r",
                                         packet_hash="p", reviewer={},
                                         contract_hash="c", **kwargs)

    def test_a_non_string_evidence_entry_is_a_controlled_safety_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result = runner.run(_request(
                out, consequence="CONSEQUENTIAL",
                safety_call=self._safety_call(self._good_safety()),
                reviewer=self.SAFETY_REVIEWER, evidence=(42,)))
            self.assertFalse(result.ok)
            self.assertEqual("safety", result.stage)
            self.assertNotIn("TypeError", result.message)

    def test_a_non_string_evidence_entry_is_a_controlled_verification_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result = runner.run(_full_request(
                out, verify_call=self._verify_call(self._good_verification()),
                reviewer={"model_snapshot": "test"}, evidence=(42,)))
            self.assertFalse(result.ok)
            self.assertEqual("specification", result.stage)
            self.assertNotIn("TypeError", result.message)

    def test_a_non_string_evidence_entry_is_a_controlled_specification_failure(self) -> None:
        base = {"bore_d": 12.0, "wall": 3.0, "height": 9.0, "mouth_gap": 9.0,
                "flange_w": 40.0, "flange_d": 22.0, "flange_t": 5.0, "screw_d": 4.8}
        spec = {"measurements": [], "interfaces": [], "unresolved": []}
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result = runner.run(runner.JobRequest(
                job_id="fit", brief_path=out / "b.md", template="c_clip",
                parameters=dict(base), stated=frozenset({"flange_w"}),
                consequence="INCONSEQUENTIAL", out_dir=out,
                updated_utc="1970-01-01T00:00:00Z", render=False,
                external_geometry=True, evidence=(42,),
                spec_call=lambda r: {**spec, "review_envelope": r["review_envelope"]},
                interface_map={"channel": "bore_d"},
                reviewer={"model_snapshot": "test"},
                printer="Test Printer",
                material={"process": "FDM", "material": "PLA"},
                nozzle={"diameter_mm": 0.4},
                orientation={"model_to_printer_matrix": "identity", "bed_z_mm": 0.0}))
            self.assertFalse(result.ok)
            self.assertEqual("specification", result.stage)
            self.assertNotIn("TypeError", result.message)

    def test_missing_evidence_file_is_a_controlled_safety_failure(self) -> None:
        """Evidence hashing happens inside the review boundary: a file that is
        not there is a controlled blocked JobResult with a receipt, never an
        uncaught MissingEvidenceError out of the runner."""
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result = runner.run(_request(
                out, consequence="CONSEQUENTIAL",
                safety_call=self._safety_call(self._good_safety()),
                reviewer=self.SAFETY_REVIEWER, evidence=("ghost.jpg",)))
            self.assertFalse(result.ok)
            self.assertEqual("safety", result.stage)
            self.assertIn("MissingEvidenceError", result.message)
            self.assertIn("safety_verification_report.json",
                          [p.name for p in out.iterdir()])

    def test_missing_evidence_file_is_a_controlled_verification_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result = runner.run(_full_request(
                out, verify_call=self._verify_call(self._good_verification()),
                reviewer={"model_snapshot": "test"}, evidence=("ghost.jpg",)))
            self.assertFalse(result.ok)
            self.assertEqual("specification", result.stage)
            self.assertIn("MissingEvidenceError", result.message)
            self.assertIn("specification.json",
                          [p.name for p in out.iterdir()])

    def test_missing_evidence_file_is_a_controlled_specification_failure(self) -> None:
        base = {"bore_d": 12.0, "wall": 3.0, "height": 9.0, "mouth_gap": 9.0,
                "flange_w": 40.0, "flange_d": 22.0, "flange_t": 5.0, "screw_d": 4.8}
        spec = {"measurements": [{"feature": "bundle_across", "nominal_mm": 12.4,
                                  "uncertainty_mm": 0.15, "method": "caliper",
                                  "datum": "widest", "confidence": "A"}],
                "interfaces": [{"interface_id": "channel", "measurement": "bundle_across",
                                "fit_class": "slip"}],
                "unresolved": []}
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result = runner.run(runner.JobRequest(
                job_id="fit", brief_path=out / "b.md", template="c_clip",
                parameters=dict(base), stated=frozenset({"flange_w"}),
                consequence="INCONSEQUENTIAL", out_dir=out,
                updated_utc="1970-01-01T00:00:00Z", render=False,
                external_geometry=True, evidence=("ghost.jpg",),
                spec_call=lambda r: {**spec, "review_envelope": r["review_envelope"]},
                interface_map={"channel": "bore_d"},
                reviewer={"model_snapshot": "test"},
                printer="Test Printer",
                material={"process": "FDM", "material": "PLA"},
                nozzle={"diameter_mm": 0.4},
                orientation={"model_to_printer_matrix": "identity", "bed_z_mm": 0.0}))
            self.assertFalse(result.ok)
            self.assertEqual("specification", result.stage)
            self.assertIn("MissingEvidenceError", result.message)

    def test_an_unhashable_envelope_fails_closed_at_every_surface(self) -> None:
        """The same malformed envelope must be a ReviewError at the binding
        check and a plain False at the status surface check -- is_bound runs
        inside status.decide, which has no try/except to catch anything."""
        from . import review as R

        envelope = R.build_envelope(kind="verification", job_id="t", revision="t",
                                    packet_hash="p", reviewer={}, contract_hash="c")
        corrupt = envelope.as_dict()
        corrupt["reviewer"] = {"snapshot": object()}
        with self.assertRaises(R.ReviewError):
            R.validate_response_envelope({"review_envelope": corrupt}, envelope)
        self.assertFalse(R.is_bound({"review_envelope": corrupt}, "verification",
                                    envelope.digest()))
        self.assertFalse(R.is_bound(["not", "a", "dict"], "verification",
                                    envelope.digest()))

    def test_verification_report_without_expected_envelope_is_not_promoted(self) -> None:
        """Status must require the full current verification envelope; omitting
        it must fail closed even if the report looks like a pass."""
        with tempfile.TemporaryDirectory() as raw:
            contract = _contract(Path(raw))
        final = status.decide(
            contract=contract,
            commission_report={"verdict": "PASS",
                               "witness": {"rendered": True, "sections": []}},
            screening={"overall": "CLEAR", "calibrated": True},
            manufacturing=None, artifact={"contract_sha256": contract.contract_hash(),
                                          "stl_sha256": "b", "source_sha256": "c"},
            safety=None,
            verification={"decision": "PASS", "summary": "ok",
                          "review_envelope": {"kind": "verification",
                                              "protocol_version": 1}},
            updated_utc="t")
        self.assertNotIn(final["final_status"], ("COMMISSIONED", "VERIFIED"))
        self.assertIn("unbound", final["allowed_claim"])

    def test_unavailable_witness_section_blocks_verified(self) -> None:
        """A witness section the pipeline could not measure must block
        PASS-equivalent status while keeping the unavailable evidence visible."""
        from . import review as R

        with tempfile.TemporaryDirectory() as raw:
            contract = _contract(Path(raw))
        witness = {"rendered": True,
                   "sections": [{"z": 1.0, "area_mm2": None, "status": "UNAVAILABLE",
                                 "error_code": "X", "error_message": "x"}]}
        envelope = R.build_envelope(
            kind="verification", job_id=contract.job_id, revision="t",
            packet_hash="p", reviewer={}, contract_hash=contract.contract_hash())
        verification_report = {**self._good_verification(),
                               "review_envelope": envelope.as_dict()}
        final = status.decide(
            contract=contract,
            commission_report={"verdict": "PASS", "witness": witness},
            screening={"overall": "CLEAR", "calibrated": True},
            manufacturing=None, artifact={"contract_sha256": contract.contract_hash(),
                                          "stl_sha256": "b", "source_sha256": "c"},
            safety=None, verification=verification_report, updated_utc="t",
            verification_envelope=envelope)
        self.assertEqual("NEEDS_MORE_EVIDENCE", final["final_status"])
        self.assertIn("could not be measured", final["allowed_claim"].lower())
        self.assertTrue(any("witness sections unavailable" in r for r in final["reasons"]))

    def test_stale_safety_response_after_reviewer_config_change_is_rejected(self) -> None:
        """The reviewer configuration is part of the binding; a response from a
        different reviewer is a different review."""
        response = self._good_safety()
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            seen = []
            def capture(packet):
                seen.append(packet)
                return {**response, "review_envelope": packet.payload["review_envelope"]}
            runner.run(_request(out, consequence="CONSEQUENTIAL",
                                safety_call=capture, reviewer=self.SAFETY_REVIEWER))
            stale = seen[0].payload["review_envelope"]
            result = runner.run(_request(
                out, consequence="CONSEQUENTIAL",
                safety_call=lambda p: {**response, "review_envelope": stale},
                reviewer={**self.SAFETY_REVIEWER, "model_snapshot": "other"}))
            self.assertFalse(result.ok)
            self.assertEqual("safety", result.stage)

    def test_stale_safety_response_after_schema_version_change_is_rejected(self) -> None:
        """A response that advertises an old answer schema version cannot match
        the current envelope, even if every other field is identical."""
        from . import schemas as S

        response = self._good_safety()
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            seen = []
            def capture(packet):
                seen.append(packet)
                return {**response, "review_envelope": packet.payload["review_envelope"]}
            runner.run(_request(out, consequence="CONSEQUENTIAL",
                                safety_call=capture, reviewer=self.SAFETY_REVIEWER))
            stale = seen[0].payload["review_envelope"]
            stale["answer_schema_version"] = S.SAFETY_SCHEMA - 1
            result = runner.run(_request(
                out, consequence="CONSEQUENTIAL",
                safety_call=lambda p: {**response, "review_envelope": stale},
                reviewer=self.SAFETY_REVIEWER))
            self.assertFalse(result.ok)
            self.assertEqual("safety", result.stage)

    def test_stale_verification_response_after_artifact_change_is_rejected(self) -> None:
        """Changing the built artifact changes the artifact hashes in the
        envelope; an old answer must not be accepted."""
        response = self._good_verification()
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            seen = []
            def capture(packet):
                seen.append(packet)
                return {**response, "review_envelope": packet.payload["review_envelope"]}
            runner.run(_full_request(out, verify_call=capture,
                                     reviewer={"model_snapshot": "test"}))
            stale = seen[0].payload["review_envelope"]
            result = runner.run(_full_request(
                out, verify_call=lambda p: {**response, "review_envelope": stale},
                params={**CLIP, "wall": 4.0},
                reviewer={"model_snapshot": "test"}))
            self.assertFalse(result.ok)
            self.assertEqual("verification", result.stage)

    def test_stale_safety_response_after_contract_change_is_rejected(self) -> None:
        """A response bound to one contract hash must not be promoted after the
        contract changes."""
        response = self._good_safety()
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            seen = []
            def capture(packet):
                seen.append(packet)
                return {**response, "review_envelope": packet.payload["review_envelope"]}
            runner.run(_request(out, consequence="CONSEQUENTIAL",
                                safety_call=capture, reviewer=self.SAFETY_REVIEWER))
            stale = seen[0].payload["review_envelope"]
            result = runner.run(_request(
                out, consequence="CONSEQUENTIAL",
                params={**CLIP, "wall": 4.0},
                safety_call=lambda p: {**response, "review_envelope": stale},
                reviewer=self.SAFETY_REVIEWER))
            self.assertFalse(result.ok)
            self.assertEqual("safety", result.stage)

    def test_safety_response_with_valid_envelope_but_missing_field_fails_closed(self) -> None:
        """A correctly bound payload with a missing required field must become a
        SchemaError, not a TypeError or a pass."""
        response = {"decision": "PASS", "safety_concerns": [],
                    "missing_evidence": [], "required_actions": [], "summary": "ok"}
        with tempfile.TemporaryDirectory() as raw:
            result = runner.run(_request(
                Path(raw), consequence="CONSEQUENTIAL",
                safety_call=self._safety_call(response),
                reviewer=self.SAFETY_REVIEWER))
            self.assertFalse(result.ok)
            self.assertEqual("safety", result.stage)

    def test_verification_response_with_valid_envelope_but_missing_defect_field_fails_closed(self) -> None:
        """A bound REJECT carrying a defect that omits a required field must be
        refused as a schema error."""
        response = {"decision": "REJECT",
                    "defects": [{"summary": "x", "owning_loop": "CONTRACT",
                                 "expected_vs_observed": "x", "severity": "x"}],
                    "unmet_requirements": [], "missing_evidence": [], "summary": "x"}
        with tempfile.TemporaryDirectory() as raw:
            result = runner.run(_full_request(
                Path(raw), verify_call=self._verify_call(response),
                reviewer={"model_snapshot": "test"}))
            self.assertFalse(result.ok)
            self.assertEqual("verification", result.stage)

    def test_safety_response_with_non_string_list_item_fails_closed(self) -> None:
        """Exact top-level types: a list containing a non-string is malformed."""
        response = {**self._good_safety(), "failure_modes": ["fracture", 123]}
        with tempfile.TemporaryDirectory() as raw:
            result = runner.run(_request(
                Path(raw), consequence="CONSEQUENTIAL",
                safety_call=self._safety_call(response),
                reviewer=self.SAFETY_REVIEWER))
            self.assertFalse(result.ok)
            self.assertEqual("safety", result.stage)


class NumericOnlyVerificationTest(unittest.TestCase):
    def test_verified_without_images_says_so(self) -> None:
        """The verifier is asked what is *visible* in the witnesses. With no
        images it answers from numbers, and undeclared geometry is exactly what
        numbers do not cover -- so the claim has to name which one it was."""
        with tempfile.TemporaryDirectory() as raw:
            result = _run_full_looked(Path(raw))
            final = result.final_status

            self.assertFalse(final["witnesses_rendered"])
            if final["final_status"] == "VERIFIED":
                self.assertIn("no images were rendered", final["allowed_claim"])
                self.assertTrue(any("saw no images" in r for r in final["reasons"]))


class ToolchainIdentityTest(unittest.TestCase):
    """The cache key's toolchain half. It was the literal string "no-lockfile"
    whenever a lockfile could not be found, so every machine without one shared
    a key no matter what was installed -- and the configuration that could not
    find one was the installed bundle."""

    def test_no_lockfile_is_never_a_constant(self) -> None:
        from . import cache as K

        with tempfile.TemporaryDirectory() as raw:
            empty = Path(raw)
            self.assertIsNone(K.find_lock(empty), "nothing should be found here")
            digest = K.lock_hash(empty)

        self.assertNotIn("no-lockfile", digest)
        self.assertTrue(digest.startswith(("lock:", "versions:")), digest)

    def test_a_lockfile_needs_a_project_beside_it(self) -> None:
        """A lockfile with no project beside it belongs to somebody else. The
        old code took one by fixed depth and, from an installed skill, read two
        directories above the skill root."""
        from . import cache as K

        with tempfile.TemporaryDirectory() as raw:
            stray = Path(raw) / "someone-elses"
            stray.mkdir()
            (stray / "uv.lock").write_text("not ours", encoding="utf-8")
            self.assertIsNone(K.find_lock(stray))

            (stray / "pyproject.toml").write_text("[project]", encoding="utf-8")
            self.assertEqual(stray / "uv.lock", K.find_lock(stray))

    def test_the_versions_fallback_distinguishes_toolchains(self) -> None:
        from . import cache as K

        versions = K.installed_versions()
        self.assertEqual(sorted(K.TOOLCHAIN_PACKAGES), sorted(versions))
        for name, value in versions.items():
            with self.subTest(package=name):
                self.assertTrue(value, name)

        # An absent package and an installed one are different toolchains.
        base = dict(versions)
        from . import schemas as SC
        self.assertNotEqual(SC.payload_hash(base),
                            SC.payload_hash({**base, "build123d": "absent"}))

    def test_the_key_moves_when_the_toolchain_does(self) -> None:
        from . import cache as K

        with tempfile.TemporaryDirectory() as raw:
            contract = _contract(Path(raw))
            key = K.key_for(contract, backend_version="v", tessellation={},
                            root=Path(raw))
            self.assertNotEqual("no-lockfile", key.lock_sha256)
            moved = dataclasses.replace(key, lock_sha256="versions:something-else")
            self.assertNotEqual(key.digest(), moved.digest())


class UnavailableRunnerTest(unittest.TestCase):
    """Unavailable measurements on the production path must become explicit
    non-success evidence rather than aborting before a receipt is written."""

    def test_unavailable_witness_section_is_non_success_evidence(self) -> None:
        """A witness section the instrument could not measure must be recorded
        as UNAVAILABLE and the runner must still finish and write receipts."""
        from . import witness as W

        original_sections = W._sections
        def sections_with_unavailable(ctx, contract, limit):
            real = list(original_sections(ctx, contract, limit))
            return (*real, {"z": 999.0, "area_mm2": None, "status": "UNAVAILABLE",
                            "error_code": "TEST_INJECTED",
                            "error_message": "injected unavailable section"})
        try:
            W._sections = sections_with_unavailable
            with tempfile.TemporaryDirectory() as raw:
                out = Path(raw)
                result = _run(out)
                self.assertIn("commission_report", result.artifacts)
                report = json.loads(
                    (out / "commission_report.json").read_text(encoding="utf-8"))
                sections = report["witness"]["sections"]
                unavailable = [s for s in sections if s.get("status") == "UNAVAILABLE"]
                self.assertEqual(1, len(unavailable), sections)
                self.assertIsNone(unavailable[0]["area_mm2"])
                self.assertEqual("TEST_INJECTED", unavailable[0]["error_code"])
                # The runner must still produce a final status receipt.
                self.assertIn("final_status", result.artifacts)
        finally:
            W._sections = original_sections

    def test_an_unavailable_section_blocks_verified_with_a_bound_pass(self) -> None:
        """End to end through the real envelope flow: the verifier echoes the
        current envelope and returns a bound PASS, and the UNAVAILABLE section
        still keeps the job off VERIFIED."""
        from . import witness as W

        original_sections = W._sections
        def sections_with_unavailable(ctx, contract, limit):
            real = list(original_sections(ctx, contract, limit))
            return (*real, {"z": 999.0, "area_mm2": None, "status": "UNAVAILABLE",
                            "error_code": "TEST_INJECTED",
                            "error_message": "injected unavailable section"})
        try:
            W._sections = sections_with_unavailable
            with tempfile.TemporaryDirectory() as raw:
                result = _run_full_looked(Path(raw))
                self.assertEqual("NEEDS_MORE_EVIDENCE",
                                 result.final_status["final_status"])
                self.assertTrue(any("witness sections unavailable" in r
                                    for r in result.final_status["reasons"]))
        finally:
            W._sections = original_sections


class CommissionInvariantTest(unittest.TestCase):
    """Every ran=False, measured=None observation must be UNAVAILABLE with
    error metadata. A missing instrument answer is not a measured zero."""

    def test_bore_by_displacement_with_no_bore_is_unavailable(self) -> None:
        """The enclosing disc is solid, so the instrument could not answer. The
        check must record UNAVAILABLE, not a fabricated PASS or a traceback."""
        import math

        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            base = _contract(tmp)
            bore = C.Feature(
                feature_id="liner-bore", kind="bore_by_displacement", provenance="test",
                expectation={"at": {"x": 20.0, "y": 11.0}, "d_mm": 30.0,
                             "enclosing_d_mm": 5.0, "z": 2.0},
                tolerance={"abs": 0.5}, verified_by="bore_by_displacement",
                on_unrunnable="FAIL", mandatory=True)
            contract = C.Contract(**{**base.__dict__, "features": (bore,)})
            from .backends.trimesh_manifold import build_c_clip
            part, _ = build_c_clip(CLIP)
            path = tmp / "part.stl"
            part.export(path)
            ctx = analysis.load(path)
            # Force the instrument to see a completely solid disc so the only
            # honest reading is "no bore is present to measure".
            def solid_disc(*, z, at, diameter):
                return math.pi / 4.0 * diameter * diameter
            ctx.disc_area = solid_disc
            report = commission.run(ctx, contract)
            check = next(c for c in report["checks"]
                         if c["check_id"] == "feature-liner-bore")
            self.assertFalse(check["ran"])
            self.assertIsNone(check["measured"])
            self.assertEqual("UNAVAILABLE", check["status"])
            self.assertIsNotNone(check["error_code"])
            self.assertIsNotNone(check["error_message"])
            self.assertNotEqual("PASS", check["result"])


class ManufacturingInputTest(unittest.TestCase):
    """Explicit, validated printer, material, nozzle, and orientation."""

    def test_contract_carries_explicit_printer_material_nozzle_orientation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            _run(out)
            contract = json.loads(
                (out / "model_contract.json").read_text(encoding="utf-8"))
            self.assertEqual("Test Printer", contract.get("printer", ""))
            self.assertEqual({"process": "FDM", "material": "PLA"},
                             contract.get("material"))
            self.assertEqual({"diameter_mm": 0.4}, contract.get("nozzle"))
            self.assertEqual({"model_to_printer_matrix": "identity", "bed_z_mm": 0.0},
                             contract.get("orientation"))

    def test_empty_orientation_is_rejected_by_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            contract = _contract(out)
            broken = C.Contract(**{**contract.__dict__, "orientation": {}})
            problems = C.preflight(broken, known_checks=commission.KNOWN_CHECKS)
            self.assertTrue(any("orientation" in p for p in problems), problems)

    def test_empty_material_is_rejected_by_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            contract = _contract(out)
            broken = C.Contract(**{**contract.__dict__, "material": {}})
            problems = C.preflight(broken, known_checks=commission.KNOWN_CHECKS)
            self.assertTrue(any("material" in p for p in problems), problems)

    def test_empty_nozzle_is_rejected_by_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            contract = _contract(out)
            broken = C.Contract(**{**contract.__dict__, "nozzle": {}})
            problems = C.preflight(broken, known_checks=commission.KNOWN_CHECKS)
            self.assertTrue(any("nozzle" in p for p in problems), problems)

    def test_empty_printer_is_rejected_by_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            contract = _contract(out)
            broken = C.Contract(**{**contract.__dict__, "printer": ""})
            problems = C.preflight(broken, known_checks=commission.KNOWN_CHECKS)
            self.assertTrue(any("printer" in p for p in problems), problems)
