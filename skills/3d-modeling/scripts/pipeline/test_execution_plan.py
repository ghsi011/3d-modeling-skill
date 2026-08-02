#!/usr/bin/env python3
"""Stage 1: one compiled plan, and a runner that cannot disagree with it.

The 796 tests that were here before this file caught none of the four defects
below, and the reason is worth writing down: every fixture exercised a path the
code was built for. A `FITTED` job was always given an external interface, so
`external_geometry` was always true, so the route the runner re-derived happened
to agree with the route the compiler decided. Nothing ever ran a job down a path
a real project could take and the code had not anticipated.

So each test here starts from a project shape a user can actually write, and each
one fails on the code as it stood:

* a `RECONSTRUCT` job whose parameters sit inside a certified domain -- routed
  `FITTED`, executed as `DIRECT`, no metrologist, no verifier, `"DIRECT"` on its
  own receipt, and a claim asking for the verifier that had been supplied;
* a `FULL` job made `FULL` by its component count alone -- no evidence, no
  external interface, so no metrologist was asked for, and the runner refused it
  for the missing metrologist;
* `verification_requested` on a `DIRECT` job, read by nothing;
* a `FITTED` or `FULL` project whose designer had already written `model.py` --
  the run rewrote the same commission every time without ever looking for it.

None of the four was resolvable by any action an agent could take, which is the
property that separates a defect from a stopping condition.
"""
from __future__ import annotations

import dataclasses
import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from . import acceptance as ACC
from . import cli
from . import execution as EX
from . import project as P
from . import route as RT
from . import runner
from . import selftest as ST

CLIP = dict(ST.FROZEN_PARAMETERS["c_clip"])
UTC = "1970-01-01T00:00:00Z"

# A legacy job description, in the shape `run-job` reads and `init
# --from-job-json` adapts. `external_geometry` is what makes it route FITTED, and
# FITTED through the two entry points is where they disagreed.
JOB_JSON = {
    "job_id": "legacy", "template": "c_clip", "parameters": dict(CLIP),
    "updated_utc": UTC, "consequence": "INCONSEQUENTIAL",
    "printer": "Test Printer",
    "material": {"process": "FDM", "material": "PLA"},
    "nozzle": {"diameter_mm": 0.4},
    "orientation": {"model_to_printer_matrix": "identity", "bed_z_mm": 0.0},
    "external_geometry": True,
    "interface_map": {"channel": "bore_d"},
    "reviewer": {"model_snapshot": "test"},
}

# A plain block: one body, no overhangs, every expectation the closed form of a
# rectangle. The geometry is deliberately uninteresting -- what these tests are
# about is which lane builds it and what the receipt is allowed to say.
#
# Two files since stage 2: the proposal says what it must measure and the model
# says how it is built, and the second may not restate the first after a result.
BLOCK = '''
import trimesh

PARAMS = {"w": 40.0, "d": 30.0, "h": 10.0}


def build():
    block = trimesh.creation.box(extents=(40.0, 30.0, 10.0))
    block.apply_translation((20.0, 15.0, 5.0))
    return block
'''

BLOCK_PROPOSAL = {
    "schema_version": 1,
    "job_id": "stage1",
    "design_id": "plain-block",
    "rationale": "a 40x30x10 block; the lane is the subject, not the shape",
    "params": {"w": 40.0, "d": 30.0, "h": 10.0},
    "bbox_mm": {"x": 40.0, "y": 30.0, "z": 10.0},
    "bodies": 1,
    "profile_marks": {"z": []},
    "features": [
        {"feature_id": "block-section", "kind": "section_area",
         "at": {"z": 5.0}, "value_mm2": 40.0 * 30.0},
        {"feature_id": "bed-footprint", "kind": "bed_contact",
         "value_mm2": 40.0 * 30.0},
    ],
}

SPEC_RESPONSE = {
    "measurements": [{"feature": "bundle_across", "nominal_mm": 12.4,
                      "uncertainty_mm": 0.05, "method": "caliper",
                      "datum": "widest section", "confidence": "A"}],
    "interfaces": [{"interface_id": "channel", "measurement": "bundle_across",
                    "fit_class": "slip"}],
    "unresolved": [],
}

PASSED_REVIEW = {"decision": "PASS", "defects": [], "unmet_requirements": [],
                 "missing_evidence": [], "summary": "nothing undeclared visible"}


def _project(**over) -> P.Project:
    base = dict(
        job_id="stage1", updated_utc=UTC, source_mode="NEW",
        consequence="INCONSEQUENTIAL",
        consequence_rationale="a desk clip; failure wastes material",
        printer="Test Printer", material={"process": "FDM", "material": "PLA"},
        nozzle={"diameter_mm": 0.4},
        orientation={"model_to_printer_matrix": "identity", "bed_z_mm": 0.0},
        template="c_clip", parameters=dict(CLIP),
        reviewer={"model_snapshot": "test"},
        requirements=(P.Requirement(name="bore_d", value=12.0, unit="mm",
                                    provenance="STATED", source="user"),),
    )
    base.update(over)
    return P.Project(**base)


def _authored(**over) -> P.Project:
    """The same job with the geometry authored rather than certified."""
    return _project(template=None, parameters={}, model="model.py",
                    envelope_mm={"x": 40.0, "y": 30.0, "z": 10.0}, **over)


def _laid_out(root: Path, project: P.Project, *, model: str | None = None,
              proposal: dict | None = None, name: str = "project",
              source: bool = False) -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "brief.md").write_text("a clip", encoding="utf-8")
    if model is not None:
        (directory / "model.py").write_text(textwrap.dedent(model), encoding="utf-8")
        _propose(directory, proposal or BLOCK_PROPOSAL)
    if source:
        _source_artifact(directory)
    project.save(directory)
    return directory


def _propose(directory: Path, proposal: dict) -> Path:
    path = directory / ACC.PROPOSAL_FILE
    path.write_text(json.dumps(proposal, indent=2, sort_keys=True), encoding="utf-8")
    return path


# The supplied artifact a modification starts from. Deliberately a plain block:
# what these tests are about is whether anything reads it at all.
SOURCE_ARTIFACT = P.SourceArtifact(artifact_id="src", path="source.stl",
                                   format="STL", classification="USABLE_MESH")
EDIT_SCOPE = P.EditScope(
    artifact_id="src", region="the mounting boss",
    region_box={"min": [5.0, 5.0, 0.0], "max": [15.0, 15.0, 10.0]},
    preserve=("everything but the boss",))


def _source_artifact(directory: Path) -> Path:
    import trimesh

    block = trimesh.creation.box(extents=(40.0, 30.0, 10.0))
    block.apply_translation((20.0, 15.0, 5.0))
    path = directory / "source.stl"
    block.export(path)
    return path


def _answer(directory: Path, kind: str, payload: dict) -> None:
    """Answer the review the run is waiting for, bound to its own envelope."""
    packet = json.loads((directory / "reviews" / f"{kind}_packet.json")
                        .read_text(encoding="utf-8"))
    (directory / "reviews" / f"{kind}_response.json").write_text(
        json.dumps({**payload, "review_envelope": packet["review_envelope"]}),
        encoding="utf-8")


def _final(directory: Path) -> dict:
    return json.loads((directory / "final_status.json").read_text(encoding="utf-8"))


def _plan_file(directory: Path) -> dict:
    return json.loads(
        (directory / cli.EXECUTION_PLAN_FILE).read_text(encoding="utf-8"))


def _next_action(directory: Path) -> dict:
    return json.loads(
        (directory / cli.NEXT_ACTION_FILE).read_text(encoding="utf-8"))


class RouteIsNotABuilderTest(unittest.TestCase):
    """Template matching picks who draws the shape. It never picks the route."""

    def test_a_certified_template_in_a_reconstruct_job_leaves_it_fitted(self) -> None:
        plan = EX.compile_plan(_project(source_mode="RECONSTRUCT"))
        self.assertEqual("FITTED", plan.route)
        self.assertEqual("CERTIFIED_TEMPLATE", plan.builder)
        self.assertEqual("c_clip", plan.template)
        self.assertEqual(("specification", "verification"), plan.required_reviews)

    def test_the_same_template_in_a_full_job_leaves_it_full(self) -> None:
        plan = EX.compile_plan(_project(components=(
            P.Component(component_id="body", role="housing"),
            P.Component(component_id="lid", role="cover"))))
        self.assertEqual("FULL", plan.route)
        self.assertEqual("CERTIFIED_TEMPLATE", plan.builder)
        self.assertEqual("c_clip", plan.template)

    def test_an_authored_model_is_a_builder_on_every_route(self) -> None:
        for over, route in (({}, "CUSTOM"),
                            ({"components": (P.Component(component_id="a", role="x"),
                                             P.Component(component_id="b", role="y"))},
                             "FULL")):
            with self.subTest(route=route):
                plan = EX.compile_plan(_authored(**over))
                self.assertEqual(route, plan.route)
                self.assertEqual("AUTHORED", plan.builder)
                self.assertEqual("authored", plan.backend)

    def test_the_plan_is_compiled_and_never_authored(self) -> None:
        """No hand-written file, no extra command, and byte-stable per run."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), _project())
            self.assertFalse((directory / cli.EXECUTION_PLAN_FILE).is_file())
            cli.run([str(directory), "--no-render"])
            first = (directory / cli.EXECUTION_PLAN_FILE).read_text(encoding="utf-8")
            cli.run([str(directory), "--no-render"])
            self.assertEqual(first, (directory / cli.EXECUTION_PLAN_FILE)
                             .read_text(encoding="utf-8"))
            self.assertEqual("DIRECT", json.loads(first)["route"])


class ReconstructOnACertifiedTemplateTest(unittest.TestCase):
    """The livelock: routed FITTED, executed DIRECT, receipt said DIRECT.

    The job owed a specification and a verification, `reviews/` was never
    created, and the final status parked on NEEDS_MORE_EVIDENCE telling the
    caller to supply a verifier -- which the caller had supplied. No answer
    lifted it, because nothing was ever going to ask the question.
    """

    def _run_to_completion(self, directory: Path) -> None:
        self.assertEqual(cli.NEEDS_ACTION, cli.run([str(directory), "--no-render"]))
        _answer(directory, "spec", SPEC_RESPONSE)
        self.assertEqual(cli.NEEDS_ACTION, cli.run([str(directory), "--no-render"]))
        _answer(directory, "verification", PASSED_REVIEW)
        self.assertEqual(0, cli.run([str(directory), "--no-render"]))

    def test_it_asks_for_the_metrologist_and_the_verifier_it_says_it_needs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), _project(
                source_mode="RECONSTRUCT", interface_map={"channel": "bore_d"}))
            self._run_to_completion(directory)
            for kind in ("spec", "verification"):
                self.assertTrue((directory / "reviews" / f"{kind}_packet.json").is_file(),
                                f"the {kind} review the plan requires was never asked "
                                "for, and nothing on disk said so")

    def test_the_receipt_names_the_route_that_was_compiled(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), _project(
                source_mode="RECONSTRUCT", interface_map={"channel": "bore_d"}))
            self._run_to_completion(directory)
            final = _final(directory)
            self.assertEqual("FITTED", final["route"])
            self.assertEqual("VERIFIED", final["final_status"])
            self.assertEqual("PASS", final["verification"])

    def test_the_receipt_carries_the_hash_of_the_plan_it_executed(self) -> None:
        """A route on a receipt is only worth reading if it names its plan."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), _project(
                source_mode="RECONSTRUCT", interface_map={"channel": "bore_d"}))
            self._run_to_completion(directory)
            written = _plan_file(directory)
            plan = EX.compile_plan(P.load(directory))
            self.assertEqual(plan.as_payload(), written)
            self.assertEqual(plan.plan_hash(), _final(directory)["execution_plan_sha256"])


class FullWithNothingToMeasureTest(unittest.TestCase):
    """The other deadlock: refused for a reviewer the route had not asked for."""

    def _moving(self) -> P.Project:
        """FULL for a reason that owes no measurement.

        Declared motion, which used to be one of four such triggers.
        `candidate_strategy: PARALLEL` was another until it was retired: it
        produced no second candidate, isolated nothing and compared nothing, and
        its whole effect was this extra line of route rationale. Competing
        formulations are `design-tool branch` now.
        """
        return _project(motion=(P.Motion(motion_id="hinge", kind="ROTARY",
                                         static=("body",), moving=("lid",)),))

    def test_a_full_job_with_no_evidence_asks_for_no_metrologist(self) -> None:
        for name, project in (("declared motion", self._moving()),
                              ("two components", _project(components=(
                                  P.Component(component_id="a", role="x"),
                                  P.Component(component_id="b", role="y"))))):
            with self.subTest(trigger=name):
                plan = EX.compile_plan(project)
                self.assertEqual("FULL", plan.route)
                self.assertEqual(("verification",), plan.required_reviews)
                self.assertFalse(plan.requires_specification)

    def test_it_runs_to_a_receipt_instead_of_refusing_at_the_routing_stage(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), self._moving())
            code = cli.run([str(directory), "--no-render"])
            self.assertEqual(cli.NEEDS_ACTION, code)
            action = _next_action(directory)
            self.assertEqual("REVIEW", action["kind"], action)
            self.assertEqual("verification", action["review_kind"])

            _answer(directory, "verification", PASSED_REVIEW)
            self.assertEqual(0, cli.run([str(directory), "--no-render"]))
            self.assertEqual("FULL", _final(directory)["route"])

    def test_the_compiler_and_the_runner_ask_for_the_same_reviews(self) -> None:
        """The deadlock was structural: two derivations of one obligation.

        Whatever the plan requires is exactly what the CLI supplies, so there is
        no shape of job for which one side asks for a reviewer the other did not
        provide. Asserted over the review wiring itself rather than over one
        example, because the failing example was the one nobody had written.
        """
        cases = {
            "direct": _project(),
            "consequential direct": _project(
                consequence="CONSEQUENTIAL",
                consequence_rationale="carries a load over a walkway"),
            "reconstruct": _project(source_mode="RECONSTRUCT"),
            "full by components": _project(components=(
                P.Component(component_id="a", role="x"),
                P.Component(component_id="b", role="y"))),
            "full by declared motion": self._moving(),
            "explicit verification": _project(verification_requested=True),
        }
        cases["authored metrology"] = _authored(source_mode="RECONSTRUCT")
        cases["legacy fitted"] = P.from_job_json(dict(JOB_JSON))
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            for name, project in cases.items():
                with self.subTest(job=name):
                    plan = EX.compile_plan(project)
                    calls = cli._review_calls(directory, plan)
                    # Each reviewer is wired on the predicate the runner reads,
                    # not on a second reading of the review list. A job that owes
                    # a recovery nothing can run must not be handed a reviewer
                    # whose answer nothing would read, and a job the plan invites
                    # an optional look on must have somebody there to take it.
                    self.assertEqual("safety" in plan.required_reviews,
                                     calls["safety_call"] is not None)
                    self.assertEqual(plan.dispatches_specification,
                                     calls["spec_call"] is not None,
                                     "spec_call and the plan disagree")
                    self.assertEqual(plan.verification_dispatch != "NEVER",
                                     calls["verify_call"] is not None,
                                     "verify_call and the plan disagree")


class ExplicitVerificationRequestTest(unittest.TestCase):
    def test_direct_takes_no_free_extra_look(self) -> None:
        """The route trade, unchanged: a reachable verifier is not a decision."""
        plan = EX.compile_plan(_project())
        self.assertEqual("NEVER", plan.verification_dispatch)
        self.assertEqual((), plan.required_reviews)

    def test_but_an_explicit_request_is_not_silently_discarded(self) -> None:
        project = _project(verification_requested=True)
        decision = RT.decide(project)
        self.assertEqual("DIRECT", decision.route)
        self.assertIn("independent verification was explicitly requested",
                      decision.escalations)
        plan = EX.compile_plan(project, decision)
        self.assertEqual(("verification",), plan.required_reviews)
        self.assertEqual("REQUIRED", plan.verification_dispatch)

    def test_and_the_verifier_it_asked_for_actually_runs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), _project(verification_requested=True))
            self.assertEqual(cli.NEEDS_ACTION, cli.run([str(directory), "--no-render"]))
            _answer(directory, "verification", PASSED_REVIEW)
            self.assertEqual(0, cli.run([str(directory), "--no-render"]))
            final = _final(directory)
            self.assertEqual("DIRECT", final["route"])
            self.assertEqual("VERIFIED", final["final_status"])


class AuthoredGeometryOffTheCustomRouteTest(unittest.TestCase):
    """A designer's model has to be reachable from the route that commissioned it."""

    def _full(self, **over) -> P.Project:
        return _authored(components=(P.Component(component_id="a", role="body"),
                                     P.Component(component_id="b", role="lid")),
                         **over)

    def test_the_commission_is_written_only_while_the_model_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), self._full())
            self.assertEqual(cli.NEEDS_ACTION, cli.run([str(directory), "--no-render"]))
            action = _next_action(directory)
            self.assertEqual("AGENT_COMMISSION", action["kind"])
            self.assertEqual("FULL", action["route"])

            self.assertEqual([ACC.PROPOSAL_FILE, "model.py"],
                             action["required_outputs"],
                             "one commission, for both files: freezing the proposal "
                             "is a pipeline step and must not become a dispatch")

            (directory / "model.py").write_text(textwrap.dedent(BLOCK),
                                                encoding="utf-8")
            _propose(directory, BLOCK_PROPOSAL)
            cli.run([str(directory), "--no-render"])
            self.assertNotEqual("AGENT_COMMISSION", _next_action(directory)["kind"],
                                "the model the run asked for was sitting beside the "
                                "project file and the run asked for it again")

    def test_a_full_job_on_authored_geometry_reaches_a_final_status(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), self._full(), model=BLOCK)
            self.assertEqual(cli.NEEDS_ACTION, cli.run([str(directory), "--no-render"]))
            self.assertEqual("verification", _next_action(directory)["review_kind"])
            _answer(directory, "verification", PASSED_REVIEW)
            self.assertEqual(0, cli.run([str(directory), "--no-render"]))

            final = _final(directory)
            self.assertEqual("FULL", final["route"])
            self.assertEqual("authored", final["backend"])
            self.assertEqual("VERIFIED", final["final_status"])

    def test_metrology_on_authored_geometry_is_named_rather_than_skipped(self) -> None:
        """The one combination the pipeline genuinely cannot execute.

        Recovery is defined against a certified template's covers and bounds;
        there is nothing to recover an externally owned dimension into when the
        geometry is authored. The honest states are to say so on the receipt or
        to pretend the metrologist ran. It says so -- and it still builds, so a
        designer can keep iterating against real measurements.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), _authored(source_mode="RECONSTRUCT"),
                                  model=BLOCK)
            plan = EX.compile_plan(P.load(directory))
            self.assertTrue(plan.requires_specification)
            self.assertEqual("UNSUPPORTED", plan.lane_status,
                             "not EXPERIMENTAL_UNAVAILABLE: no stage on the map "
                             "lifts this, and a reader told to wait for one waits "
                             "forever")
            self.assertIn("certified template's covers and bounds", plan.lane_note)
            self.assertIn("not a stage that is coming", plan.lane_note)

            # The verification this route also requires is dispatched normally;
            # it is only the recovery that has nothing to run.
            self.assertEqual(cli.NEEDS_ACTION, cli.run([str(directory), "--no-render"]))
            self.assertFalse((directory / "reviews" / "spec_packet.json").is_file(),
                             "a review nothing can run must not be presented as "
                             "one an agent could answer")
            _answer(directory, "verification", PASSED_REVIEW)
            cli.run([str(directory), "--no-render"])
            final = _final(directory)
            self.assertEqual("UNSUPPORTED", final["lane_status"])
            self.assertEqual("UNSUPPORTED", final["final_status"])
            self.assertIn(plan.lane_note, final["reasons"])
            self.assertEqual("PASS", json.loads(
                (directory / "commission_report.json").read_text(encoding="utf-8")
            )["verdict"], "the deterministic work must still run")

    def test_the_cap_that_carried_this_combination_can_no_longer_carry_it(self) -> None:
        """Which cap holds it is the whole point of naming it separately.

        `_lane` used to answer this shape with whichever cap it reached first, so
        on most jobs it was the `CUSTOM` cap doing the work. Stage 2 removes that
        cap. If the combination had still been leaning on a stage gate, lifting
        one would have uncovered it in silence.
        """
        for status in ("AVAILABLE", "EXPERIMENTAL_UNAVAILABLE"):
            with self.subTest(lane_status=status):
                plan = EX.compile_plan(_authored(source_mode="RECONSTRUCT"))
                with self.assertRaises(ValueError) as caught:
                    dataclasses.replace(plan, lane_status=status)
                self.assertIn("must be recorded as UNSUPPORTED",
                              str(caught.exception))


class TheCustomLaneMayNowClaimTest(unittest.TestCase):
    """The cap said the criteria came out of the file being judged. They do not.

    `CUSTOM_LANE_NOTE` read: "the CUSTOM lane still re-reads its acceptance
    criteria out of the model file it is judging, so a designer can widen an
    expectation after seeing it missed and be commissioned on the next run". Stage
    2 moved those criteria into `design_proposal.json`, froze them into
    `acceptance_contract.json` before the builder runs, and removed the fields
    from `AuthoredModel` so nothing can read them back. What is asserted here is
    that the cap went with the reason, and that `MODIFY`'s -- which owes a
    different thing entirely -- did not.
    """

    def test_a_custom_part_is_built_measured_and_claimable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), _authored(), model=BLOCK)
            cli.run([str(directory), "--no-render"])
            report = json.loads(
                (directory / "commission_report.json").read_text(encoding="utf-8"))
            self.assertEqual("PASS", report["verdict"], report["checks"])
            self.assertEqual("AVAILABLE", _final(directory)["lane_status"])
            for receipt in ("acceptance_contract.json", "model_contract.json",
                            "artifact_manifest.json", "final_status.json"):
                self.assertTrue((directory / receipt).is_file(), receipt)

    def test_a_verified_custom_part_reaches_verified(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), _authored(verification_requested=True),
                                  model=BLOCK)
            self.assertEqual(cli.NEEDS_ACTION, cli.run([str(directory), "--no-render"]))
            _answer(directory, "verification", PASSED_REVIEW)
            code = cli.run([str(directory), "--no-render"])

            final = _final(directory)
            self.assertEqual("CUSTOM", final["route"])
            self.assertEqual("PASS", final["verification"])
            self.assertEqual("VERIFIED", final["final_status"])
            self.assertEqual(0, code)

    def test_the_modify_cap_is_not_lifted_with_it(self) -> None:
        """A different lane owes a different thing: the preservation audit's
        sample density is still a fixed count rather than one derived from a
        declared minimum detectable defect size."""
        plan = EX.compile_plan(_project(
            source_mode="MODIFY", source_artifacts=(SOURCE_ARTIFACT,),
            edit_scopes=(EDIT_SCOPE,)))
        self.assertEqual("EXPERIMENTAL_UNAVAILABLE", plan.lane_status)
        self.assertIn("minimum detectable defect size", plan.lane_note)
        self.assertNotIn("acceptance criteria", plan.lane_note,
                         "the half of this note that stage 2 settled is still in "
                         "it, so a reader cannot tell what is actually owed")

    def test_a_real_failure_is_still_reported_as_a_failure(self) -> None:
        """A part that does not match its contract fails, on any lane."""
        widened = [dict(row) for row in BLOCK_PROPOSAL["features"]]
        widened[0]["value_mm2"] = 40.0 * 30.0 * 2
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), _authored(), model=BLOCK,
                                  proposal={**BLOCK_PROPOSAL, "features": widened})
            code = cli.run([str(directory), "--no-render"])
            final = _final(directory)
            self.assertEqual("FAILED", final["final_status"])
            self.assertEqual("AVAILABLE", final["lane_status"])
            self.assertEqual(1, code)


class EditScopeIsTheObligationTest(unittest.TestCase):
    """A declared edit scope carries the modification obligations.

    Stage 1 capped the lane on the literal `source_mode == "MODIFY"` and wired
    the preservation audit into the authored builder alone. Between them, a
    project that declared an edit scope over a supplied artifact and wrote
    `RECONSTRUCT` beside it validated cleanly, compiled `lane_status: AVAILABLE`,
    built a certified template, reached `VERIFIED` -- and never opened the source
    artifact or mentioned it on any receipt. A sweep of project shapes put 960 in
    that class. The same project one commit earlier could not claim success, so
    this was the commit that made the claim reachable.
    """

    def _edit(self, **over) -> P.Project:
        return _project(source_mode="RECONSTRUCT", interface_map={"channel": "bore_d"},
                        source_artifacts=(SOURCE_ARTIFACT,),
                        edit_scopes=(EDIT_SCOPE,),
                        **over)

    def test_the_cap_follows_the_edit_scope_and_not_the_source_mode(self) -> None:
        plan = EX.compile_plan(self._edit())
        self.assertEqual("FITTED", plan.route)
        self.assertEqual("CERTIFIED_TEMPLATE", plan.builder)
        self.assertEqual("EXPERIMENTAL_UNAVAILABLE", plan.lane_status,
                         "a declared modification may not claim success on any "
                         "builder while the preservation audit is unsettled")
        self.assertEqual(EX.MODIFY_LANE_NOTE, plan.lane_note)
        self.assertTrue(plan.requires_preservation)

    def test_no_shape_declares_an_edit_scope_and_keeps_an_available_lane(self) -> None:
        """Asserted over the shapes rather than over the one example.

        The failing example was the one nobody had written, so the property is
        checked across every source mode and every route an edit scope can be
        declared under.
        """
        for source_mode in P.SOURCE_MODE:
            for label, over in (("certified template", {}),
                                ("authored model", {"model": "model.py"}),
                                ("two components", {"components": (
                                    P.Component(component_id="a", role="x"),
                                    P.Component(component_id="b", role="y"))})):
                with self.subTest(source_mode=source_mode, builder=label):
                    plan = EX.compile_plan(_project(
                        source_mode=source_mode, source_artifacts=(SOURCE_ARTIFACT,),
                        edit_scopes=(EDIT_SCOPE,),
                        envelope_mm={"x": 40.0, "y": 30.0, "z": 10.0}, **over))
                    # Which cap, not merely that there is one: a `RECONSTRUCT`
                    # job on an authored model is `UNSUPPORTED` for a reason that
                    # has nothing to do with the edit scope, and asserting the
                    # weaker property would let the preservation obligation go
                    # missing behind it.
                    self.assertNotEqual("AVAILABLE", plan.lane_status)
                    self.assertTrue(plan.requires_preservation)

    def test_the_preservation_row_reaches_the_contract_on_a_certified_builder(self) -> None:
        """Driven through the CLI, because the wiring is where it went missing.

        The run stops at the verification review rather than finishing, and the
        assertions are on the receipts that exist by then. That is not a
        convenience: the preservation audit still samples unseeded, so two runs
        of one unchanged pair disagree and the second run's evidence packet no
        longer matches the answer written against the first. It is the defect
        `MODIFY_LANE_NOTE` names and stage 5 settles -- and it is exactly why this
        lane may not claim success, which is the other half of what is asserted
        here.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), self._edit(), source=True)
            self.assertEqual(cli.NEEDS_ACTION, cli.run([str(directory), "--no-render"]))
            _answer(directory, "spec", SPEC_RESPONSE)
            self.assertEqual(cli.NEEDS_ACTION, cli.run([str(directory), "--no-render"]))

            contract = json.loads(
                (directory / "model_contract.json").read_text(encoding="utf-8"))
            rows = [f for f in contract["features"] if f["kind"] == "preservation"]
            self.assertEqual(1, len(rows),
                             "the edit scope was declared and the contract that "
                             "gates the candidate carries no row measuring it")
            self.assertEqual("source.stl", rows[0]["expectation"]["source"],
                             "the supplied artifact is named nowhere the gate reads")

            report = json.loads(
                (directory / "commission_report.json").read_text(encoding="utf-8"))
            self.assertIn("feature-preservation-src",
                          [c["check_id"] for c in report["checks"]])

            self.assertEqual("EXPERIMENTAL_UNAVAILABLE",
                             _plan_file(directory)["lane_status"])
            self.assertFalse((directory / "final_status.json").is_file(),
                             "this shape reached a successful final status with "
                             "the source artifact read by nothing")

    def test_a_contract_that_drops_the_row_is_refused_before_the_build_counts(self) -> None:
        """The obligation is on the plan, so no builder can drop it by omission.

        Wiring the audit into one CLI path is exactly how it went missing. The
        plan now states the obligation and the runner refuses a contract that
        does not carry it, which makes a future builder's silence a stop rather
        than a receipt nobody wrote.
        """
        with tempfile.TemporaryDirectory() as raw:
            project = _project()
            directory = _laid_out(Path(raw), project)
            plan = dataclasses.replace(EX.compile_plan(project),
                                       preserved_artifact_ids=("src",))
            result = runner.run(runner.JobRequest(
                brief_path=directory / "brief.md", out_dir=directory,
                render=False, plan=plan, **P.to_job_request_fields(project)))
            self.assertFalse(result.ok)
            self.assertEqual("preflight", result.stage)
            self.assertIn("preservation row", result.message)

    def test_the_mode_alone_still_refuses_a_contract_with_no_row(self) -> None:
        """The fail-closed path, kept covered now that the obligation is a list.

        A project that carried `MODIFY` without a scope is refused by
        `Project.validate` before this is reached, so the plan should never name
        zero artifacts and still owe an audit. It is checked anyway: a plan that
        owed nothing measurable would let the one shape nobody validated build
        against nothing at all.
        """
        with tempfile.TemporaryDirectory() as raw:
            project = _project()
            directory = _laid_out(Path(raw), project)
            plan = dataclasses.replace(EX.compile_plan(project),
                                       source_mode="MODIFY",
                                       preserved_artifact_ids=())
            self.assertTrue(plan.requires_preservation)
            result = runner.run(runner.JobRequest(
                brief_path=directory / "brief.md", out_dir=directory,
                render=False, plan=plan, **P.to_job_request_fields(project)))
            self.assertFalse(result.ok)
            self.assertEqual("preflight", result.stage)
            self.assertIn("It carries 0", result.message)


SECOND_ARTIFACT = P.SourceArtifact(artifact_id="drawer", path="drawer.stl",
                                   format="STL", classification="USABLE_MESH")
SECOND_SCOPE = P.EditScope(
    artifact_id="drawer", region="the drawer magnet pocket",
    region_box={"min": [25.0, 5.0, 0.0], "max": [35.0, 15.0, 10.0]},
    interface_ids=("magnet-pockets",))
POCKETS = P.Interface(interface_id="magnet-pockets", kind="magnet pocket",
                      external=False, owner="this job",
                      note="both pockets are one feature cut in two places")


class TwoEditScopesAreTwoObligationsTest(unittest.TestCase):
    """A job may modify two artifacts, and both of them are owed an audit.

    The obligation used to be a flag, because there could only be one scope:
    "the contract carries a preservation row" and "every declared scope is
    measured" were the same sentence. With two scopes they are not, and a
    contract carrying one row would satisfy the flag while leaving the second
    artifact unmeasured -- the same defect the flag was added to stop, one
    artifact later.
    """

    def _pair(self, **over) -> P.Project:
        base = dict(
            source_mode="MODIFY", model="model.py",
            envelope_mm={"x": 40.0, "y": 30.0, "z": 10.0},
            interfaces=(POCKETS,),
            source_artifacts=(SOURCE_ARTIFACT, SECOND_ARTIFACT),
            edit_scopes=(
                dataclasses.replace(EDIT_SCOPE,
                                    interface_ids=("magnet-pockets",)),
                SECOND_SCOPE))
        base.update(over)
        return _project(**base)

    def test_the_plan_names_every_artifact_that_owes_an_audit(self) -> None:
        plan = EX.compile_plan(self._pair())
        self.assertEqual(("src", "drawer"), plan.preserved_artifact_ids)
        self.assertTrue(plan.requires_preservation)

    def test_the_cap_follows_the_scopes_however_many_there_are(self) -> None:
        """Asserted where `source_mode` cannot supply the answer by itself.

        `_lane` caps on `edit_scopes or source_mode == "MODIFY"`, so a `MODIFY`
        project would return `EXPERIMENTAL_UNAVAILABLE` even if the scopes were
        read by nothing -- which is the shape of the defect this cap exists to
        stop. `RECONSTRUCT` over a certified builder leaves the scopes as the
        only thing that can produce the cap.
        """
        plan = EX.compile_plan(self._pair(
            source_mode="RECONSTRUCT", model=None,
            interface_map={"channel": "bore_d"}))
        self.assertEqual("CERTIFIED_TEMPLATE", plan.builder)
        self.assertEqual("EXPERIMENTAL_UNAVAILABLE", plan.lane_status)
        self.assertEqual(EX.MODIFY_LANE_NOTE, plan.lane_note)
        self.assertEqual(("src", "drawer"), plan.preserved_artifact_ids)

    def test_each_scope_gets_its_own_row_naming_its_own_artifact(self) -> None:
        rows = cli._preservation_feature(self._pair())
        self.assertEqual(["preservation-src", "preservation-drawer"],
                         [row["feature_id"] for row in rows])
        self.assertEqual(["source.stl", "drawer.stl"],
                         [row["source"] for row in rows])

    def test_a_multi_artifact_row_says_what_the_audit_cannot_yet_do(self) -> None:
        """The declaration is ahead of the instrument, and the row admits it.

        `preservation.audit` compares one source against one candidate in both
        directions, and the candidate-to-source direction samples the whole
        candidate. Where the candidate carries the other edited artifact too,
        that artifact's surface reads as movement against this row's source. A
        row that stated the obligation without stating that would be read as a
        measurement it is not.
        """
        for row in cli._preservation_feature(self._pair()):
            self.assertIn("not yet measurable", row["note"], row)
        one = cli._preservation_feature(_project(
            source_mode="MODIFY", source_artifacts=(SOURCE_ARTIFACT,),
            edit_scopes=(EDIT_SCOPE,)))
        self.assertNotIn("not yet measurable", one[0]["note"],
                         "a single-artifact edit is measured exactly as before "
                         "and must not carry a caveat that does not apply to it")

    def test_the_inherited_overhang_ceiling_is_the_sum_of_the_artifacts(self) -> None:
        """The candidate carries both bodies, so it inherits both their overhangs.

        And one unmeasurable artifact drops the whole allowance back to the
        generated zero: a partial sum is a ceiling nobody measured, and widening
        a limit on a guess is what this arrangement exists to avoid.
        """
        import trimesh

        rule = {"downward_normal_z_max": -0.73, "bed_z_mm": 0.0}
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            for name, extents in (("source.stl", (40.0, 30.0, 10.0)),
                                  ("drawer.stl", (20.0, 10.0, 10.0))):
                block = trimesh.creation.box(extents=extents)
                block.apply_translation([e / 2 for e in extents])
                block.export(directory / name)

            both = cli._inherited_overhang(directory, self._pair(), rule)
            self.assertIsNotNone(both)
            each = [cli._inherited_overhang(
                directory,
                _project(source_mode="MODIFY", source_artifacts=(artifact,),
                         edit_scopes=(scope,)), rule)
                for artifact, scope in ((SOURCE_ARTIFACT, EDIT_SCOPE),
                                        (SECOND_ARTIFACT, SECOND_SCOPE))]
            self.assertAlmostEqual(sum(area for area, _ in each), both[0], places=6)
            self.assertIn("2 supplied artifacts", both[1])

            (directory / "drawer.stl").unlink()
            self.assertIsNone(cli._inherited_overhang(directory, self._pair(), rule),
                              "one unreadable artifact must not leave a ceiling "
                              "credited with only the ones that happened to read")

    def test_a_contract_that_carries_one_row_for_two_scopes_is_refused(self) -> None:
        """The shortfall, not merely the absence.

        A flag could only ask whether any row was present. Two scopes and one row
        is a job that measured half of what it declared, and it has to stop for
        the same reason zero rows does: there is no later place a missing audit
        can be caught.
        """
        with tempfile.TemporaryDirectory() as raw:
            project = _project()
            directory = _laid_out(Path(raw), project)
            plan = dataclasses.replace(
                EX.compile_plan(project),
                preserved_artifact_ids=("src", "drawer"))
            one_row = ({"feature_id": "preservation-src", "kind": "preservation",
                        "source": "source.stl",
                        "region": EDIT_SCOPE.region_box,
                        "tolerance_mm": 0.05, "exact": False,
                        "tolerance": {"abs": 0.0},
                        "note": "only one of the two declared scopes"},)
            result = runner.run(runner.JobRequest(
                brief_path=directory / "brief.md", out_dir=directory,
                render=False, plan=plan, plan_features=one_row,
                **P.to_job_request_fields(project)))
            self.assertFalse(result.ok)
            self.assertEqual("preflight", result.stage)
            self.assertIn("carries 1", result.message)


class ADeclaredModelIsNeverDiscardedTest(unittest.TestCase):
    """Either the authored model is the builder, or the plan says why not.

    `_builder` preferred a matched certified template over `project.model` on
    every non-`CUSTOM` route, and nothing reconciled the plan it emitted:
    `builder: CERTIFIED_TEMPLATE, template: c_clip, model: model.py`. A
    `RECONSTRUCT` project declaring both built the c_clip -- 40x22x14 -- rather
    than the model's 40x30x10 block, reached `VERIFIED`, and named `model.py`
    nowhere in the receipts. The asymmetry was the tell: the same declaration
    flipped a `NEW` job to `CUSTOM` and capped its lane, and was dropped in
    silence on `FITTED` and `FULL`.
    """

    def test_the_declared_model_wins_the_builder_on_a_fitted_job(self) -> None:
        plan = EX.compile_plan(_project(
            source_mode="RECONSTRUCT", model="model.py",
            envelope_mm={"x": 40.0, "y": 30.0, "z": 10.0}))
        self.assertEqual("FITTED", plan.route, "the route is unchanged by this")
        self.assertEqual("AUTHORED", plan.builder)
        self.assertIsNone(plan.template)
        self.assertEqual("model.py", plan.model)
        self.assertIn("c_clip", plan.builder_rationale,
                      "the template that was not used has to be named, or it was "
                      "discarded in silence after all")

    def test_no_plan_names_a_certified_builder_and_a_model_at_once(self) -> None:
        cases = {
            "reconstruct": {"source_mode": "RECONSTRUCT"},
            "one external interface": {"interfaces": (P.Interface(
                interface_id="channel", kind="fit", external=True,
                owner="the bundle"),)},
            "two components": {"components": (
                P.Component(component_id="a", role="x"),
                P.Component(component_id="b", role="y"))},
            "declared motion": {"motion": (P.Motion(
                motion_id="hinge", kind="ROTARY", static=("body",),
                moving=("lid",)),)},
            "new": {},
        }
        for name, over in cases.items():
            with self.subTest(job=name):
                plan = EX.compile_plan(_project(
                    model="model.py",
                    envelope_mm={"x": 40.0, "y": 30.0, "z": 10.0}, **over))
                self.assertEqual("AUTHORED", plan.builder)
                self.assertIsNone(plan.template,
                                  "the plan names a certified template it will "
                                  "not build and a model it will not build "
                                  "either")

    def test_the_geometry_that_gets_built_is_the_model_s(self) -> None:
        """The receipt has to be about the file the designer wrote."""
        project = _project(
            model="model.py", envelope_mm={"x": 40.0, "y": 30.0, "z": 10.0},
            components=(P.Component(component_id="a", role="body"),
                        P.Component(component_id="b", role="lid")))
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), project, model=BLOCK)
            self.assertEqual(cli.NEEDS_ACTION, cli.run([str(directory), "--no-render"]))
            _answer(directory, "verification", PASSED_REVIEW)
            self.assertEqual(0, cli.run([str(directory), "--no-render"]))

            artifact = json.loads(
                (directory / "artifact_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual({"x": 40.0, "y": 30.0, "z": 10.0}, artifact["bbox_mm"],
                             "the certified template was built instead of the "
                             "model the project declared")
            self.assertEqual("authored", _final(directory)["backend"])


class OneJobOneAnswerThroughEitherEntryPointTest(unittest.TestCase):
    """`run-job` and `run` on one identical `job.json`.

    `verification_dispatch: OPTIONAL` named a look no `design-tool run` job could
    take: the compiler returned it exactly when `verification` was absent from
    `required_reviews`, and `_review_calls` supplied a verifier exactly when it
    was present. `run-job` hands the runner every callable unconditionally and
    duly took the look, so the same file finished `VERIFIED` through the
    deprecated entry point and `NEEDS_MORE_EVIDENCE` through the supported one --
    the legacy adapter dropping a review its predecessor dispatched, under a name
    that read like deliberate policy.
    """

    def _job_dir(self, root: Path, name: str) -> Path:
        directory = root / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "brief.md").write_text("a clip over a bundle", encoding="utf-8")
        (directory / "job.json").write_text(json.dumps(JOB_JSON), encoding="utf-8")
        return directory

    def _drive(self, directory: Path, entry, argv: list[str]) -> int:
        """Run, answer whatever it asks for, run again -- up to a fixed bound."""
        for _ in range(5):
            code = entry(argv)
            if code != cli.NEEDS_ACTION:
                return code
            for kind, payload in (("spec", SPEC_RESPONSE),
                                  ("verification", PASSED_REVIEW)):
                packet = directory / "reviews" / f"{kind}_packet.json"
                response = directory / "reviews" / f"{kind}_response.json"
                if packet.is_file() and not response.is_file():
                    _answer(directory, kind, payload)
                    break
            else:
                return code
        self.fail("the job never settled")

    def test_both_entry_points_reach_the_same_status(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            legacy = self._job_dir(root, "legacy")
            canonical = self._job_dir(root, "canonical")

            legacy_code = self._drive(legacy, cli.run_job,
                                      [str(legacy), "--no-render"])
            self.assertEqual(0, cli.init([
                str(canonical), "--job-id", "legacy", "--source-mode", "RECONSTRUCT",
                "--consequence", "INCONSEQUENTIAL", "--updated-utc", UTC,
                "--from-job-json"]))
            canonical_code = self._drive(canonical, cli.run,
                                         [str(canonical), "--no-render"])

            self.assertEqual(legacy_code, canonical_code)
            self.assertEqual(_final(legacy)["final_status"],
                             _final(canonical)["final_status"],
                             "one job.json, two entry points, two answers")
            self.assertEqual("VERIFIED", _final(canonical)["final_status"])
            self.assertEqual("PASS", _final(canonical)["verification"])

    def test_the_optional_look_is_compiled_and_a_verifier_is_supplied_for_it(self) -> None:
        plan = EX.compile_plan(P.from_job_json(dict(JOB_JSON)))
        self.assertEqual("FITTED", plan.route)
        self.assertNotIn("verification", plan.required_reviews)
        self.assertEqual("OPTIONAL", plan.verification_dispatch)
        with tempfile.TemporaryDirectory() as raw:
            calls = cli._review_calls(Path(raw), plan)
            self.assertIsNotNone(calls["verify_call"],
                                 "the plan invites an independent look and the "
                                 "run path puts nobody in the room to take it")

    def test_no_dispatch_value_names_behaviour_no_job_can_produce(self) -> None:
        """Every value in the enum is compiled by some project a user can write."""
        produced = {
            EX.compile_plan(_project()).verification_dispatch,
            EX.compile_plan(_project(verification_requested=True)).verification_dispatch,
            EX.compile_plan(P.from_job_json(dict(JOB_JSON))).verification_dispatch,
        }
        self.assertEqual(set(EX.DISPATCH), produced)

    def test_custom_is_not_bought_an_independent_look_it_did_not_ask_for(self) -> None:
        """The optional look must not become a round trip on the CUSTOM baseline."""
        plan = EX.compile_plan(_authored())
        self.assertEqual("CUSTOM", plan.route)
        self.assertEqual("NEVER", plan.verification_dispatch)
        with tempfile.TemporaryDirectory() as raw:
            self.assertIsNone(cli._review_calls(Path(raw), plan)["verify_call"])


class LegacyProjectReadsItsOwnRequestTest(unittest.TestCase):
    """`route._legacy` never read `verification_requested`.

    `P.load` deserializes the field, so on any `compat: "job.json@1"` project an
    explicit ask for an independent look reached the router and vanished with no
    receipt. A request that disappears in silence is worse than one that is
    refused: nothing downstream can tell which of the two happened.
    """

    def _adapted(self, root: Path) -> Path:
        directory = root / "adapted"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "brief.md").write_text("a clip", encoding="utf-8")
        # No external geometry: this routes DIRECT, which is the route that
        # trades the independent look away unless somebody asks for it.
        (directory / "job.json").write_text(
            json.dumps({**JOB_JSON, "external_geometry": False,
                        "interface_map": {}}), encoding="utf-8")
        self.assertEqual(0, cli.init([
            str(directory), "--job-id", "legacy", "--source-mode", "NEW",
            "--consequence", "INCONSEQUENTIAL", "--updated-utc", UTC,
            "--from-job-json"]))
        project = P.load(directory)
        project.verification_requested = True
        project.save(directory)
        return directory

    def test_the_request_reaches_the_route_decision_and_the_plan(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = P.load(self._adapted(Path(raw)))
            self.assertEqual("job.json@1", project.compat)
            decision = RT.decide(project)
            self.assertEqual("DIRECT", decision.route)
            self.assertTrue(decision.requires_verification)
            self.assertIn("independent verification was explicitly requested",
                          decision.escalations)
            plan = EX.compile_plan(project, decision)
            self.assertEqual(("verification",), plan.required_reviews)
            self.assertEqual("REQUIRED", plan.verification_dispatch)

    def test_the_verifier_it_asked_for_actually_runs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = self._adapted(Path(raw))
            self.assertEqual(cli.NEEDS_ACTION, cli.run([str(directory), "--no-render"]))
            _answer(directory, "verification", PASSED_REVIEW)
            self.assertEqual(0, cli.run([str(directory), "--no-render"]))
            final = _final(directory)
            self.assertEqual("DIRECT", final["route"])
            self.assertEqual("VERIFIED", final["final_status"])


class APlanCannotOweWhatItDeclinesTest(unittest.TestCase):
    """The runner used to decline a review the plan required, on its own say-so.

    `if plan.requires_specification and plan.builder == "CERTIFIED_TEMPLATE"`
    meant a FITTED or FULL job on authored geometry carried `specification` in
    its required reviews, had a reviewer wired for it, and never had it invoked.
    Every such shape is capped today, so nothing false escaped -- but the cap was
    the only thing holding it, and a plan stating an obligation the runner
    unilaterally drops is the two-authorities shape this stage exists to remove.
    """

    def test_the_compiler_owns_whether_the_recovery_can_run(self) -> None:
        plan = EX.compile_plan(_authored(source_mode="RECONSTRUCT"))
        self.assertTrue(plan.requires_specification)
        self.assertFalse(plan.dispatches_specification)
        self.assertEqual("UNSUPPORTED", plan.lane_status)

    def test_owing_a_review_nothing_can_run_and_claiming_success_is_unrepresentable(self) -> None:
        available = EX.compile_plan(_project(source_mode="RECONSTRUCT"))
        self.assertEqual("AVAILABLE", available.lane_status)
        self.assertTrue(available.dispatches_specification)
        with self.assertRaises(ValueError) as caught:
            dataclasses.replace(available, builder="AUTHORED", template=None)
        self.assertIn("owes a review nothing can run", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
