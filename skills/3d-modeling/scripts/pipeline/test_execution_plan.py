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

import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from . import cli
from . import execution as EX
from . import project as P
from . import route as RT
from . import selftest as ST

CLIP = dict(ST.FROZEN_PARAMETERS["c_clip"])
UTC = "1970-01-01T00:00:00Z"

# A plain block: one body, no overhangs, every expectation the closed form of a
# rectangle. The geometry is deliberately uninteresting -- what these tests are
# about is which lane builds it and what the receipt is allowed to say.
BLOCK = '''
import trimesh

PARAMS = {"w": 40.0, "d": 30.0, "h": 10.0}
BBOX_MM = {"x": 40.0, "y": 30.0, "z": 10.0}
BODIES = 1
PROFILE_MARKS = {"z": []}
VOLUME_MM3 = 40.0 * 30.0 * 10.0
EXPECTED = [
    {"feature_id": "block-section", "kind": "section_area",
     "at": {"z": 5.0}, "value_mm2": 40.0 * 30.0},
    {"feature_id": "bed-footprint", "kind": "bed_contact", "value_mm2": 40.0 * 30.0},
]


def build():
    block = trimesh.creation.box(extents=(40.0, 30.0, 10.0))
    block.apply_translation((20.0, 15.0, 5.0))
    return block
'''

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


def _laid_out(root: Path, project: P.Project, *, model: str | None = None) -> Path:
    directory = root / "project"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "brief.md").write_text("a clip", encoding="utf-8")
    if model is not None:
        (directory / "model.py").write_text(textwrap.dedent(model), encoding="utf-8")
    project.save(directory)
    return directory


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

    def _parallel(self) -> P.Project:
        return _project(candidate_strategy="PARALLEL")

    def test_a_full_job_with_no_evidence_asks_for_no_metrologist(self) -> None:
        for name, project in (("parallel candidates", self._parallel()),
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
            directory = _laid_out(Path(raw), self._parallel())
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
            "full by parallel candidates": self._parallel(),
            "explicit verification": _project(verification_requested=True),
        }
        supplied = {"safety": "safety_call", "specification": "spec_call",
                    "verification": "verify_call"}
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            for name, project in cases.items():
                with self.subTest(job=name):
                    plan = EX.compile_plan(project)
                    calls = cli._review_calls(directory, plan)
                    for review, field in supplied.items():
                        self.assertEqual(review in plan.required_reviews,
                                         calls[field] is not None,
                                         f"{field} and the plan disagree about "
                                         f"{review}")


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

            (directory / "model.py").write_text(textwrap.dedent(BLOCK),
                                                encoding="utf-8")
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
            self.assertEqual("EXPERIMENTAL_UNAVAILABLE", plan.lane_status)
            self.assertIn("certified template's covers and bounds", plan.lane_note)

            # The verification this route also requires is dispatched normally;
            # it is only the recovery that has nothing to run.
            self.assertEqual(cli.NEEDS_ACTION, cli.run([str(directory), "--no-render"]))
            self.assertFalse((directory / "reviews" / "spec_packet.json").is_file(),
                             "a review nothing can run must not be presented as "
                             "one an agent could answer")
            _answer(directory, "verification", PASSED_REVIEW)
            cli.run([str(directory), "--no-render"])
            final = _final(directory)
            self.assertEqual("EXPERIMENTAL_UNAVAILABLE", final["lane_status"])
            self.assertIn(plan.lane_note, final["reasons"])
            self.assertEqual("PASS", json.loads(
                (directory / "commission_report.json").read_text(encoding="utf-8")
            )["verdict"], "the deterministic work must still run")


class ExperimentalLaneTest(unittest.TestCase):
    """CUSTOM and MODIFY build, measure and report -- and may not claim success."""

    def test_a_custom_part_is_built_and_measured(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), _authored(), model=BLOCK)
            cli.run([str(directory), "--no-render"])
            report = json.loads(
                (directory / "commission_report.json").read_text(encoding="utf-8"))
            self.assertEqual("PASS", report["verdict"], report["checks"])
            self.assertEqual("CLEAR", report["screening"]["overall"])
            for receipt in ("model_contract.json", "artifact_manifest.json",
                            "final_status.json"):
                self.assertTrue((directory / receipt).is_file(), receipt)

    def test_but_it_cannot_claim_success_while_the_lane_is_experimental(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), _authored(verification_requested=True),
                                  model=BLOCK)
            self.assertEqual(cli.NEEDS_ACTION, cli.run([str(directory), "--no-render"]))
            _answer(directory, "verification", PASSED_REVIEW)
            code = cli.run([str(directory), "--no-render"])

            final = _final(directory)
            self.assertEqual("CUSTOM", final["route"])
            self.assertEqual("PASS", final["verification"],
                             "the independent look ran and passed")
            self.assertEqual("EXPERIMENTAL_UNAVAILABLE", final["final_status"],
                             "a passing verification on an experimental lane is "
                             "still not a claim this lane may make")
            self.assertIn(EX.CUSTOM_LANE_NOTE, final["allowed_claim"])
            self.assertEqual(1, code)
            self.assertEqual("LANE_UNAVAILABLE", _next_action(directory)["kind"],
                             "no answer an agent writes lifts this, so it must not "
                             "read as a job waiting for one")

    def test_a_real_failure_is_still_reported_as_a_failure(self) -> None:
        """The cap withholds a claim; it must not hide a finding.

        Overwriting FAILED with the architectural caveat would bury a part that
        does not match its contract behind a note about the roadmap.
        """
        source = textwrap.dedent(BLOCK).replace(
            '"value_mm2": 40.0 * 30.0}', '"value_mm2": 40.0 * 30.0 * 2}')
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), _authored(), model=source)
            code = cli.run([str(directory), "--no-render"])
            final = _final(directory)
            self.assertEqual("FAILED", final["final_status"])
            self.assertEqual("EXPERIMENTAL_UNAVAILABLE", final["lane_status"])
            self.assertIn(EX.CUSTOM_LANE_NOTE, final["reasons"])
            self.assertEqual(1, code)


if __name__ == "__main__":
    unittest.main()
