#!/usr/bin/env python3
"""L0-heavy — the half of
`skills/3d-modeling/scripts/pipeline/test_execution_plan.py`
that costs a child interpreter.

The repository-root `conftest.py` refuses a child interpreter inside the commit
gate, and these classes start one. Same tests, moved rather than weakened;
`benchmarks/heavy/README.md` records the profile that decided the seam and what
runs this tier. What stayed behind is what answers in the parent process.
"""
from __future__ import annotations

import dataclasses
import json
import tempfile
import textwrap
import unittest
from pathlib import Path
from pipeline import acceptance as ACC
from pipeline import cli
from pipeline import execution as EX
from pipeline import project as P

# The fixtures this half shares with the half that stayed behind,
# imported rather than copied: two spellings of one fixture is how
# two tiers stop testing the same thing.
from pipeline.test_execution_plan import (  # noqa: E402
    BLOCK,
    BLOCK_PROPOSAL,
    EDIT_SCOPE,
    PASSED_REVIEW,
    SOURCE_ARTIFACT,
    _answer,
    _authored,
    _final,
    _laid_out,
    _next_action,
    _project,
    _propose,
)


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
