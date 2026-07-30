#!/usr/bin/env python3
"""Phase 1: the canonical project, the four routes, and a resumable `run`.

The three things this phase has to get right, and what each test here is for:

* **The project refuses rather than defaults.** Every field a contract will be
  built from is required, and a project missing one names it. The failure
  direction that is safe is refusing to build.
* **Routing is a decision over the job, not over a parameter dict.** `CUSTOM`
  exists so that "novel" and "fitted" stop being the same answer, and the legacy
  `job.json` adapter must keep giving the answers it always gave.
* **`run` stops cleanly and continues.** The runner never performs an agent
  review; it writes what it is waiting for, exits, and consumes the answer on the
  next identical invocation.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from . import cli
from . import project as P
from . import route as RT
from . import schemas as S
from . import selftest as ST

CLIP = dict(ST.FROZEN_PARAMETERS["c_clip"])
UTC = "1970-01-01T00:00:00Z"


def _complete(**over) -> P.Project:
    """A project with every required field supplied, so a test can remove one."""
    base = dict(
        job_id="p", updated_utc=UTC, source_mode="NEW",
        consequence="INCONSEQUENTIAL",
        consequence_rationale="a desk clip; failure wastes material",
        printer="Test Printer", material={"process": "FDM", "material": "PLA"},
        nozzle={"diameter_mm": 0.4},
        orientation={"model_to_printer_matrix": "identity", "bed_z_mm": 0.0},
        template="c_clip", parameters=dict(CLIP),
        requirements=(P.Requirement(name="bore_d", value=12.0, unit="mm",
                                    provenance="STATED", source="user"),),
    )
    base.update(over)
    return P.Project(**base)


def _project_dir(root: Path, project: P.Project, *, brief: str = "a clip") -> Path:
    directory = root / "project"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "brief.md").write_text(brief, encoding="utf-8")
    project.save(directory)
    return directory


class ProjectSchemaTest(unittest.TestCase):
    def test_a_complete_project_validates(self) -> None:
        self.assertEqual([], _complete().validate())

    def test_every_manufacturing_input_is_required_not_defaulted(self) -> None:
        for field in ("printer", "material", "nozzle", "orientation"):
            with self.subTest(missing=field):
                problems = _complete(**{field: None}).validate()
                self.assertTrue(any(field.split(".")[0] in p for p in problems),
                                f"{field} was accepted as missing: {problems}")

    def test_a_consequence_without_a_rationale_is_refused(self) -> None:
        problems = _complete(consequence_rationale="").validate()
        self.assertTrue(any("consequence_rationale" in p for p in problems))

    def test_a_nan_parameter_is_refused_before_it_can_size_anything(self) -> None:
        problems = _complete(parameters={**CLIP, "bore_d": float("nan")}).validate()
        self.assertTrue(any("finite" in p for p in problems), problems)

    def test_an_inherited_value_must_name_the_artifact_it_came_from(self) -> None:
        """Otherwise it is indistinguishable from a value somebody chose."""
        project = _complete(requirements=(
            P.Requirement(name="bore_d", value=12.0, unit="mm",
                          provenance="INHERITED", source="supplied STEP"),))
        self.assertTrue(any("artifact_id" in p for p in project.validate()))

    def test_a_requirement_cannot_cite_an_artifact_that_is_not_declared(self) -> None:
        project = _complete(requirements=(
            P.Requirement(name="bore_d", value=12.0, unit="mm",
                          provenance="INHERITED", source="a STEP",
                          artifact_id="ghost"),))
        self.assertTrue(any("names no source artifact" in p
                            for p in project.validate()))

    def test_modify_without_an_edit_scope_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "source.step").write_text("not really a step", encoding="utf-8")
            project = _complete(
                source_mode="MODIFY",
                source_artifacts=(P.SourceArtifact(artifact_id="src",
                                                   path="source.step",
                                                   format="STEP"),))
            problems = project.validate(root)
            self.assertTrue(any("edit_scope" in p for p in problems), problems)

    def test_new_with_a_source_artifact_is_refused_as_a_category_error(self) -> None:
        project = _complete(source_artifacts=(
            P.SourceArtifact(artifact_id="src", path="source.step"),))
        self.assertTrue(any("MODIFY" in p for p in project.validate()))

    def test_a_source_artifact_path_cannot_escape_the_project(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = _complete(
                source_mode="MODIFY",
                edit_scope=P.EditScope(artifact_id="src", region="the boss face"),
                source_artifacts=(P.SourceArtifact(artifact_id="src",
                                                   path="../../secrets.step"),))
            problems = project.validate(Path(raw))
            self.assertTrue(any("traversal" in p or "project-relative" in p
                                for p in problems), problems)

    def test_a_motion_cannot_declare_one_component_both_static_and_moving(self) -> None:
        project = _complete(motion=(P.Motion(motion_id="slide", kind="LINEAR",
                                             static=("rail",), moving=("rail",)),))
        self.assertTrue(any("both static and moving" in p
                            for p in project.validate()))

    def test_an_unknown_schema_version_is_refused_rather_than_guessed(self) -> None:
        payload = _complete().as_payload()
        payload["schema_version"] = 99
        with self.assertRaises(S.SchemaError):
            P.from_payload(payload)

    def test_a_project_round_trips_through_its_own_payload(self) -> None:
        original = _complete(
            source_mode="MODIFY",
            source_artifacts=(P.SourceArtifact(artifact_id="src", path="s.step",
                                               format="STEP", units="mm",
                                               classification="USABLE_EXACT"),),
            edit_scope=P.EditScope(artifact_id="src", region="the mount boss",
                                   preserve=("everything else",)),
            motion=(P.Motion(motion_id="hinge", kind="ROTARY", static=("body",),
                             moving=("lid",)),),
            interfaces=(P.Interface(interface_id="ball", kind="socket",
                                    external=True, owner="the vent clip",
                                    motion_id="hinge"),),
            components=(P.Component(component_id="body", role="housing"),))
        again = P.from_payload(original.as_payload())
        self.assertEqual(S.canonical_json(original.as_payload()),
                         S.canonical_json(again.as_payload()))
        self.assertEqual(original.project_hash(), again.project_hash())


class RouteTest(unittest.TestCase):
    def test_a_certified_template_in_domain_routes_direct(self) -> None:
        decision = RT.decide(_complete())
        self.assertEqual("DIRECT", decision.route)
        self.assertEqual("c_clip", decision.template)
        self.assertFalse(decision.requires_verification)

    def test_novel_geometry_routes_custom_and_not_full(self) -> None:
        """The whole reason CUSTOM exists: novel is not the same as fitted, and a
        single novel part is not the same as a coupled assembly."""
        decision = RT.decide(_complete(template=None, parameters={},
                                       model="model.py"))
        self.assertEqual("CUSTOM", decision.route)
        self.assertIn("no certified template", decision.condition)

    def test_out_of_domain_parameters_route_custom(self) -> None:
        decision = RT.decide(_complete(parameters={**CLIP, "bore_d": 60.0}))
        self.assertEqual("CUSTOM", decision.route)

    def test_modifying_a_trusted_artifact_is_custom_not_fitted(self) -> None:
        """MODIFY does not force FITTED. What forces FITTED is reconciliation."""
        decision = RT.decide(_complete(
            source_mode="MODIFY", template=None, parameters={},
            source_artifacts=(P.SourceArtifact(artifact_id="src", path="s.step",
                                               format="STEP",
                                               classification="USABLE_EXACT"),),
            edit_scope=P.EditScope(artifact_id="src", region="the boss face")))
        self.assertEqual("CUSTOM", decision.route)

    def test_reconstruct_routes_fitted(self) -> None:
        decision = RT.decide(_complete(source_mode="RECONSTRUCT"))
        self.assertEqual("FITTED", decision.route)
        self.assertTrue(decision.requires_metrology)
        self.assertTrue(decision.requires_verification)

    def test_one_external_interface_routes_fitted(self) -> None:
        decision = RT.decide(_complete(interfaces=(
            P.Interface(interface_id="socket", kind="socket", external=True,
                        owner="the car's vent blade"),)))
        self.assertEqual("FITTED", decision.route)

    def test_two_external_interfaces_route_full(self) -> None:
        decision = RT.decide(_complete(interfaces=(
            P.Interface(interface_id="a", kind="socket", external=True, owner="x"),
            P.Interface(interface_id="b", kind="post", external=True, owner="y"))))
        self.assertEqual("FULL", decision.route)

    def test_declared_motion_routes_full(self) -> None:
        decision = RT.decide(_complete(motion=(
            P.Motion(motion_id="slide", kind="LINEAR", static=("rail",),
                     moving=("carriage",)),)))
        self.assertEqual("FULL", decision.route)
        self.assertIn("static pose cannot answer", decision.condition)

    def test_multiple_parts_route_full(self) -> None:
        decision = RT.decide(_complete(components=(
            P.Component(component_id="body", role="housing"),
            P.Component(component_id="lid", role="cover"))))
        self.assertEqual("FULL", decision.route)

    def test_consequence_never_selects_a_route(self) -> None:
        direct = RT.decide(_complete(consequence="CONSEQUENTIAL"))
        self.assertEqual("DIRECT", direct.route)
        custom = RT.decide(_complete(consequence="CONSEQUENTIAL", template=None,
                                     parameters={}, model="model.py"))
        self.assertEqual("CUSTOM", custom.route)

    def test_a_consequential_direct_job_gets_safety_and_no_geometric_verifier(self) -> None:
        """The route trade, stated in the charter and now enforced by the router.

        Consequence adds one bounded safety pass. It does not add a geometric
        review merely because the job is consequential -- and a project claiming
        it needs a verification it will never dispatch reads as an unmet
        obligation rather than as the trade it is.
        """
        project = _complete(consequence="CONSEQUENTIAL")
        decision = RT.decide(project)
        RT.apply(project, decision)
        self.assertEqual(("safety",), project.required_reviews)
        self.assertFalse(decision.requires_verification)

    def test_a_consequential_custom_job_does_get_one(self) -> None:
        project = _complete(consequence="CONSEQUENTIAL", template=None,
                            parameters={}, model="model.py")
        decision = RT.decide(project)
        RT.apply(project, decision)
        self.assertEqual(("safety", "verification"), project.required_reviews)
        self.assertIn("the job is CONSEQUENTIAL", decision.escalations)

    def test_an_uncomplicated_custom_job_may_finish_without_a_verifier(self) -> None:
        project = _complete(template=None, parameters={}, model="model.py")
        decision = RT.decide(project)
        RT.apply(project, decision)
        self.assertEqual((), decision.escalations)
        self.assertEqual((), project.required_reviews)

    def test_each_custom_escalation_trigger_turns_verification_on(self) -> None:
        base = dict(template=None, parameters={}, model="model.py")
        cases = {
            "consequence": dict(consequence="CONSEQUENTIAL"),
            "external interface": dict(interfaces=(
                P.Interface(interface_id="a", kind="socket", external=True,
                            owner="x"),)),
            "repair": dict(
                source_mode="MODIFY",
                source_artifacts=(P.SourceArtifact(
                    artifact_id="src", path="s.stl", format="STL",
                    classification="REPAIR_REQUIRED"),),
                edit_scope=P.EditScope(artifact_id="src", region="the cracked rib")),
            "explicit request": dict(verification_requested=True),
            "open question": dict(open_questions=(
                P.OpenQuestion("is that radius or diameter?"),)),
        }
        for name, over in cases.items():
            with self.subTest(trigger=name):
                decision = RT.decide(_complete(**{**base, **over}))
                self.assertTrue(decision.requires_verification,
                                f"{name} did not escalate: {decision.escalations}")

    def test_the_routes_not_taken_are_recorded_with_reasons(self) -> None:
        decision = RT.decide(_complete())
        self.assertEqual(3, len(decision.considered))
        for row in decision.considered:
            self.assertFalse(row["taken"])
            self.assertTrue(row["why"].strip())

    def test_a_legacy_job_json_keeps_routing_the_way_it_always_did(self) -> None:
        """The compatibility adapter's one job: not to silently re-route.

        A legacy job carries no source mode, no components, no declared
        interfaces and no motion, so the questions the new model is built on have
        no answers. Guessing at them would move jobs that were routing correctly.
        """
        spec = {"job_id": "legacy", "template": "c_clip", "updated_utc": UTC,
                "consequence": "INCONSEQUENTIAL", "parameters": dict(CLIP),
                "printer": "Test Printer",
                "material": {"process": "FDM", "material": "PLA"},
                "nozzle": {"diameter_mm": 0.4},
                "orientation": {"model_to_printer_matrix": "identity",
                                "bed_z_mm": 0.0}}
        self.assertEqual("DIRECT", RT.decide(P.from_job_json(spec)).route)

        out_of_domain = {**spec, "parameters": {**CLIP, "bore_d": 60.0}}
        legacy = RT.decide(P.from_job_json(out_of_domain))
        self.assertEqual("FULL", legacy.route,
                         "a legacy out-of-domain job routed FULL before this phase "
                         "and must keep routing FULL")

        external = {**spec, "external_geometry": True}
        self.assertEqual("FITTED", RT.decide(P.from_job_json(external)).route)

        ambiguous = {**spec, "ambiguities": ["radius or diameter?"]}
        self.assertEqual("FITTED", RT.decide(P.from_job_json(ambiguous)).route)

    def test_the_adapter_marks_stated_parameters_and_invents_no_others(self) -> None:
        spec = {"job_id": "legacy", "template": "c_clip", "updated_utc": UTC,
                "consequence": "INCONSEQUENTIAL", "parameters": dict(CLIP),
                "stated": ["bore_d"], "printer": "P",
                "material": {"process": "FDM", "material": "PLA"},
                "nozzle": {"diameter_mm": 0.4},
                "orientation": {"model_to_printer_matrix": "identity",
                                "bed_z_mm": 0.0}}
        project = P.from_job_json(spec)
        provenance = {r.name: r.provenance for r in project.requirements}
        self.assertEqual("STATED", provenance["bore_d"])
        self.assertEqual({"CHOSEN"}, set(v for k, v in provenance.items()
                                         if k != "bore_d"))


class CliRunTest(unittest.TestCase):
    """`design-tool run`: stop cleanly, then continue from the same command."""

    def test_a_direct_job_runs_and_records_its_route(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _project_dir(Path(raw), _complete())
            code = cli.run([str(directory), "--no-render"])
            self.assertEqual(cli.NEEDS_ACTION, code,
                             "a clean DIRECT job stops at NEEDS_MORE_EVIDENCE "
                             "today -- see docs/baseline.md")
            decision = json.loads(
                (directory / cli.ROUTE_DECISION_FILE).read_text(encoding="utf-8"))
            self.assertEqual("DIRECT", decision["route"])
            final = json.loads(
                (directory / "final_status.json").read_text(encoding="utf-8"))
            self.assertEqual("PASS", final["commission_verdict"])

    def test_a_custom_job_stops_with_a_designer_commission(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _project_dir(
                Path(raw), _complete(template=None, parameters={}))
            code = cli.run([str(directory), "--no-render"])
            self.assertEqual(cli.NEEDS_ACTION, code)
            action = json.loads(
                (directory / cli.NEXT_ACTION_FILE).read_text(encoding="utf-8"))
            self.assertEqual("AGENT_COMMISSION", action["kind"])
            self.assertEqual("designer", action["role"])
            self.assertEqual("CUSTOM", action["route"])
            self.assertIn("model.py", action["required_outputs"])
            self.assertTrue(action["bound"]["project_sha256"])

    def test_the_commission_carries_no_expected_answer(self) -> None:
        """A commission that says what to conclude has stopped commissioning."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _project_dir(
                Path(raw), _complete(template=None, parameters={}))
            cli.run([str(directory), "--no-render"])
            action = json.loads(
                (directory / cli.NEXT_ACTION_FILE).read_text(encoding="utf-8"))
            self.assertEqual(
                {"schema_version", "job_id", "kind", "role", "stage", "route",
                 "reason", "authorized_inputs", "required_outputs", "bound",
                 "unresolved", "required_reviews", "completion_command",
                 "updated_utc"},
                set(action))

    def test_a_consequential_job_asks_for_its_safety_review_then_continues(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _project_dir(Path(raw), _complete(
                consequence="CONSEQUENTIAL",
                consequence_rationale="mounted on a bicycle brake cable run",
                reviewer={"model_snapshot": "test"}))

            first = cli.run([str(directory), "--no-render"])
            self.assertEqual(cli.NEEDS_ACTION, first)
            action = json.loads(
                (directory / cli.NEXT_ACTION_FILE).read_text(encoding="utf-8"))
            self.assertEqual("REVIEW", action["kind"])
            self.assertEqual("safety", action["review_kind"])
            self.assertEqual("reviews/safety_response.json", action["respond_with"])

            packet = json.loads((directory / "reviews" / "safety_packet.json")
                                .read_text(encoding="utf-8"))
            (directory / "reviews" / "safety_response.json").write_text(json.dumps({
                "decision": "PASS", "safety_concerns": [], "required_actions": [],
                "failure_modes": [], "missing_evidence": [],
                "summary": "low load, thick flange, no mandatory concern applies",
                "review_envelope": packet["review_envelope"],
            }), encoding="utf-8")

            second = cli.run([str(directory), "--no-render"])
            report = json.loads((directory / "safety_verification_report.json")
                                .read_text(encoding="utf-8"))
            self.assertEqual("PASS", report["decision"])
            # Still NEEDS_MORE_EVIDENCE, for the frozen reason: uncalibrated
            # screening and no independent look. The point of this test is the
            # resumption, and that the review was consumed rather than re-asked.
            self.assertEqual(cli.NEEDS_ACTION, second)
            action = json.loads(
                (directory / cli.NEXT_ACTION_FILE).read_text(encoding="utf-8"))
            self.assertEqual("NEEDS_EVIDENCE", action["kind"],
                             "the answered review must not still be what the job "
                             "is waiting for")

    def test_a_failed_run_says_what_blocked_it_rather_than_what_it_asked_before(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _project_dir(Path(raw), _complete(
                consequence="CONSEQUENTIAL",
                consequence_rationale="on a brake cable run",
                reviewer={"model_snapshot": "test"}))
            cli.run([str(directory), "--no-render"])
            (directory / "reviews" / "safety_response.json").write_text(
                "{ not json", encoding="utf-8")
            code = cli.run([str(directory), "--no-render"])
            self.assertEqual(1, code)
            action = json.loads(
                (directory / cli.NEXT_ACTION_FILE).read_text(encoding="utf-8"))
            self.assertEqual("BLOCKED", action["kind"])
            self.assertEqual("safety", action["stage"])

    def test_an_incomplete_project_names_every_missing_field_at_once(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _project_dir(Path(raw), P.skeleton(
                job_id="skeleton", source_mode="NEW",
                consequence="INCONSEQUENTIAL", updated_utc=UTC))
            code = cli.run([str(directory), "--no-render"])
            self.assertEqual(2, code)
            action = json.loads(
                (directory / cli.NEXT_ACTION_FILE).read_text(encoding="utf-8"))
            self.assertEqual("FIX_PROJECT", action["kind"])
            self.assertTrue(len(action["unresolved"]) >= 4, action["unresolved"])

    def test_run_adapts_a_bare_job_json_and_marks_it(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw) / "legacy"
            directory.mkdir()
            (directory / "brief.md").write_text("a clip", encoding="utf-8")
            (directory / "job.json").write_text(json.dumps({
                "job_id": "legacy", "template": "c_clip", "updated_utc": UTC,
                "consequence": "INCONSEQUENTIAL", "parameters": dict(CLIP),
                "stated": ["bore_d"], "printer": "Test Printer",
                "material": {"process": "FDM", "material": "PLA"},
                "nozzle": {"diameter_mm": 0.4},
                "orientation": {"model_to_printer_matrix": "identity",
                                "bed_z_mm": 0.0}}), encoding="utf-8")
            cli.run([str(directory), "--no-render"])
            project = P.load(directory)
            self.assertEqual("job.json@1", project.compat)
            self.assertEqual("DIRECT", project.route)

    def test_a_finished_run_leaves_no_stale_instruction(self) -> None:
        """A `next_action.json` left behind says the opposite of the truth."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _project_dir(Path(raw), _complete(
                source_mode="RECONSTRUCT", reviewer={"model_snapshot": "test"},
                interface_map={"channel": "bore_d"},
                interfaces=(P.Interface(interface_id="channel", kind="fit",
                                        external=True, owner="the bundle"),)))
            def answer(kind: str, payload: dict) -> None:
                packet = json.loads((directory / "reviews" / f"{kind}_packet.json")
                                    .read_text(encoding="utf-8"))
                (directory / "reviews" / f"{kind}_response.json").write_text(
                    json.dumps({**payload,
                                "review_envelope": packet["review_envelope"]}),
                    encoding="utf-8")

            # One round trip per review, and the same command every time.
            self.assertEqual(cli.NEEDS_ACTION,
                             cli.run([str(directory), "--no-render"]))
            answer("spec", {
                "measurements": [{"feature": "bundle_across", "nominal_mm": 12.4,
                                  "uncertainty_mm": 0.05, "method": "caliper",
                                  "datum": "widest section", "confidence": "A"}],
                "interfaces": [{"interface_id": "channel",
                                "measurement": "bundle_across",
                                "fit_class": "slip"}],
                "unresolved": []})
            self.assertEqual(cli.NEEDS_ACTION,
                             cli.run([str(directory), "--no-render"]))
            answer("verification", {
                "decision": "PASS", "defects": [], "unmet_requirements": [],
                "missing_evidence": [], "summary": "nothing undeclared visible"})
            self.assertEqual(0, cli.run([str(directory), "--no-render"]))

            final = json.loads(
                (directory / "final_status.json").read_text(encoding="utf-8"))
            self.assertEqual("VERIFIED", final["final_status"])
            self.assertEqual("FITTED", final["route"])
            self.assertFalse((directory / cli.NEXT_ACTION_FILE).is_file())

    def test_status_reports_what_the_job_is_waiting_for(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _project_dir(
                Path(raw), _complete(template=None, parameters={}))
            cli.run([str(directory), "--no-render"])
            self.assertEqual(cli.NEEDS_ACTION, cli.status([str(directory)]))


if __name__ == "__main__":
    unittest.main()
