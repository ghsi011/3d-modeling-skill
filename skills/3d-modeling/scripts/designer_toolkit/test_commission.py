"""Tests for the one-call commission gate.

The gate exists because every rejection a fresh verifier ever issued was a
deterministic predicate the designer's own receipt already claimed to have
checked. So these tests are mostly about one property: a candidate that would
have been rejected downstream must fail *here*, with a non-zero exit, before it
can be handed on.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import numpy as np
import trimesh

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from designer_toolkit import commission  # noqa: E402


def _plan(**overrides):
    """A plan the gate can actually be run against.

    This fixture used to omit `model_to_printer_matrix`, `bed_z_mm`,
    `bed_tolerance_mm`, `allowed_contact_class` and `expected_bbox_mm` -- so
    every test built on it was exercising `planned_placement`'s fallback to
    `orient.best` rather than a declared orientation, and the envelope check
    silently skipped. It was exactly the shape of plan `commission` accepted
    without complaint until it started validating what it reads.
    """
    plan = {
        "schema_version": 4,
        "contract": "print-plan", "contract_version": 4, "job_id": "t", "revision": 1,
        "owner": "print-engineer",
        "support_rules": [{
            "id": "S-01", "disposition": "SUPPORT_ALLOWED",
            "allowed_contact_class": "COSMETIC_NON_MATING",
            "downward_normal_z_max": -0.73, "max_out_of_limit_area_mm2": 10000.0,
            "model_to_printer_matrix": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
            "bed_z_mm": 0.0, "bed_tolerance_mm": 0.05,
        }],
        "expected_bbox_mm": {"x": 30.0, "y": 20.0, "z": 10.0},
        "bbox_tolerance_mm": 0.5,
        "interfaces": [], "edges": [],
    }
    plan.update(overrides)
    return plan


def _box_stl(directory: Path, extents=(30, 20, 10)) -> Path:
    """Seated on the bed, which is the convention every template returns.

    This used to export a box centred on the origin -- half of it below z=0 --
    so every test built on it was quietly exercising a part the plan's identity
    transform places underground. Harmless while nothing looked, and the moment
    something did, the whole suite failed at once.
    """
    from designer_toolkit.templates import seated

    path = directory / "box.stl"
    seated(trimesh.creation.box(extents=extents)).export(path)
    return path


class EnvelopeCheckTest(unittest.TestCase):
    """The check whose absence shipped a phone case 31% too thick."""

    def test_a_part_the_wrong_size_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            stl = _box_stl(work, extents=(30, 20, 14))
            plan = _plan(expected_bbox_mm={"x": 30, "y": 20, "z": 10},
                         bbox_tolerance_mm=1.0)

            result = commission.run(model=None, stl=stl, out_dir=work / "out",
                                    plan=plan, render=False)

            envelope = next(c for c in result.checks if c.id == "envelope")
            self.assertEqual(envelope.result, "FAIL")
            self.assertIn("z", envelope.detail)
            self.assertIn("do not widen the tolerance", envelope.action)

    def test_a_part_the_right_size_passes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            stl = _box_stl(work, extents=(30, 20, 10))
            plan = _plan(expected_bbox_mm={"x": 30, "y": 20, "z": 10},
                         bbox_tolerance_mm=0.5)

            result = commission.run(model=None, stl=stl, out_dir=work / "out",
                                    plan=plan, render=False)

            self.assertEqual(next(c for c in result.checks if c.id == "envelope").result, "PASS")

    def test_a_plan_with_no_expected_size_fails_rather_than_skipping(self) -> None:
        """Skipping is how the 31% error passed: three checks reported SKIPPED,
        nothing counted them, and the gate exited zero with status READY."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            plan = _plan()
            del plan["expected_bbox_mm"]
            result = commission.run(model=None, stl=_box_stl(work), out_dir=work / "out",
                                    plan=plan, render=False)

            envelope = next(c for c in result.checks if c.id == "envelope")
            self.assertEqual("FAIL", envelope.result)
            self.assertIn("expected_bbox_mm", envelope.action)
            self.assertTrue(result.failed, "an ungateable plan must not exit zero")

    def test_an_unreadable_expected_bbox_is_not_a_passed_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            result = commission.run(
                model=None, stl=_box_stl(work), out_dir=work / "out",
                plan=_plan(expected_bbox_mm={"X": 30, "Y": 20, "Z": 10}), render=False)

            envelope = next(c for c in result.checks if c.id == "envelope")
            self.assertEqual("FAIL", envelope.result)
            self.assertIn("no readable", envelope.detail)


class ConsequenceCheckTest(unittest.TestCase):
    def test_consequential_commission_emits_an_explicit_safety_gap(self) -> None:
        """The toolkit has no safety reviewer, so a consequential run must not
        look complete merely because its geometry checks pass.
        """
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            result = commission.run(
                model=None, stl=_box_stl(work), out_dir=work / "out",
                plan=_plan(consequence="CONSEQUENTIAL"), render=False)

            safety = next(c for c in result.checks if c.id == "safety-review")
            self.assertEqual("SKIPPED", safety.result)
            message = f"{safety.detail} {safety.action}"
            self.assertIn("no safety reviewer", message)
            self.assertIn("design-tool run-job", message)
            self.assertIn("record", message)


class AssemblyOverlapCheckTest(unittest.TestCase):
    def test_each_declared_assembly_mesh_is_checked_against_the_candidate(self) -> None:
        """An undisclosed collision must fail the real gate, not just appear in
        an optional diagnostic.
        """
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            candidate = _box_stl(work)
            overlap = work / "overlap.stl"
            trimesh.creation.box(extents=(10, 10, 10)).apply_translation(
                (5, 0, 5)).export(overlap)
            clear = trimesh.creation.box(extents=(10, 10, 10))
            clear.apply_translation((30, 0, 5))
            clear_path = work / "clear.stl"
            clear.export(clear_path)
            result = commission.run(
                model=None, stl=candidate, out_dir=work / "out",
                plan=_plan(assembly_mesh_paths=[str(overlap), str(clear_path)],
                           assembly_overlap_budget_mm3=0.0), render=False)

            checks = {c.id: c for c in result.checks if c.id.startswith("assembly-overlap-")}
            self.assertEqual({"assembly-overlap-01", "assembly-overlap-02"}, set(checks))
            self.assertEqual("FAIL", checks["assembly-overlap-01"].result)
            self.assertEqual("PASS", checks["assembly-overlap-02"].result)
            self.assertIn("budget", checks["assembly-overlap-01"].detail)
            self.assertTrue(result.failed)

    def test_overlap_away_from_named_interface_fails_even_under_total_budget(self) -> None:
        """The budget may cover an intended mating overlap, not an unrelated crash.

        The old scalar check saw the sum below the budget and passed, even though
        half of that overlap was at a second, unnamed collision.
        """
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            candidate = _box_stl(work)

            contact = trimesh.creation.box(extents=(2, 20, 10))
            contact.apply_translation((15, 0, 5))
            contact_path = work / "contact.stl"
            contact.export(contact_path)

            stray = trimesh.creation.box(extents=(2, 20, 10))
            stray.apply_translation((-14, 0, 5))
            assembly_path = work / "assembly.stl"
            trimesh.util.concatenate((contact, stray)).export(assembly_path)

            result = commission.run(
                model=None, stl=candidate, out_dir=work / "out",
                plan=_plan(
                    interfaces=[{"id": "I-01", "reference": str(contact_path),
                                "min_mm": 0.0, "max_mm": 1.0}],
                    assembly_mesh_paths=[str(assembly_path)],
                    assembly_overlap_budget_mm3=400.0,
                ),
                render=False,
            )

            check = next(c for c in result.checks if c.id == "assembly-overlap-01")
            self.assertEqual("FAIL", check.result, check.detail)
            self.assertIn("away from named interfaces", check.detail)

    def test_boolean_residue_within_explicit_epsilon_does_not_fail(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            candidate = _box_stl(work)
            plan = _plan(assembly_mesh_paths=["assembly.stl"],
                         assembly_overlap_budget_mm3=0.0)
            with mock.patch.object(commission.fit, "interference", return_value=0.0005):
                result = commission.run(
                    model=None, stl=candidate, out_dir=work / "out", plan=plan,
                    render=False,
                )
            check = next(c for c in result.checks if c.id == "assembly-overlap-01")
            self.assertEqual("PASS", check.result, check.detail)


class ProductionPlanPathResolverTest(unittest.TestCase):
    def test_plan_relative_interface_and_assembly_paths_are_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            candidate = _box_stl(work)
            clear = trimesh.creation.box(extents=(10, 10, 10))
            clear.apply_translation((30, 0, 5))
            clear.export(work / "clear.stl")
            plan = _plan(
                interfaces=[{"id": "I-01", "reference": "clear.stl",
                             "min_mm": 0.0, "max_mm": 100.0}],
                assembly_mesh_paths=["clear.stl"],
                         assembly_overlap_budget_mm3=0.0)
            plan_path = work / "print_plan_checks.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")

            result = commission.run(
                model=None, stl=candidate, out_dir=work / "out", plan=plan,
                plan_path=plan_path, render=False,
            )
            check = next(c for c in result.checks if c.id == "assembly-overlap-01")
            self.assertEqual("PASS", check.result, check.detail)
            fit_check = next(c for c in result.checks if c.id == "fit-I-01")
            self.assertNotIn("cannot read", fit_check.detail)

    def test_plan_absolute_or_traversing_assembly_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            candidate = _box_stl(work)
            outside = work.parent / "outside-assembly.stl"
            trimesh.creation.box(extents=(10, 10, 10)).apply_translation(
                (30, 0, 5)).export(outside)
            plan = _plan(assembly_mesh_paths=[str(outside)],
                         assembly_overlap_budget_mm3=0.0)
            plan_path = work / "print_plan_checks.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")

            result = commission.run(
                model=None, stl=candidate, out_dir=work / "out", plan=plan,
                plan_path=plan_path, render=False,
            )
            check = next(c for c in result.checks if c.id == "assembly-overlap-01")
            self.assertEqual("FAIL", check.result)
            self.assertIn("project-relative", check.detail)


class SupportCheckTest(unittest.TestCase):
    def test_self_support_required_with_a_nonzero_ceiling_is_rejected(self) -> None:
        """The contract says that combination means zero. Two archived runs
        declared SELF_SUPPORT_REQUIRED with ceilings of 1850 and 2150 and passed.
        """
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            plan = _plan(support_rules=[{
                "id": "S-01", "disposition": "SELF_SUPPORT_REQUIRED",
                "downward_normal_z_max": -0.73, "max_out_of_limit_area_mm2": 1850.0,
                "model_to_printer_matrix": [[1, 0, 0, 0], [0, 1, 0, 0],
                                             [0, 0, 1, 0], [0, 0, 0, 1]],
                "bed_z_mm": 0.0, "bed_tolerance_mm": 0.05,
            }])

            result = commission.run(model=None, stl=_box_stl(work), out_dir=work / "out",
                                    plan=plan, render=False)

            ceiling = next(c for c in result.checks if c.id == "support-ceiling-S-01")
            self.assertEqual(ceiling.result, "FAIL")

    def test_it_screens_the_orientation_the_plan_declares(self) -> None:
        """Not the best one it can find. A candidate that prints cleanly in some
        other pose tells you nothing about the pose it will actually print in.
        """
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            # Stand the box on its short end: a declared transform the sweep
            # would never pick, so the two answers are distinguishable.
            on_end = [[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [0, 0, 0, 1]]
            plan = _plan(support_rules=[{
                "id": "S-01", "disposition": "SUPPORT_ALLOWED",
                "model_to_printer_matrix": on_end,
                "downward_normal_z_max": -0.73, "max_out_of_limit_area_mm2": 10000.0,
                "bed_z_mm": 0.0, "bed_tolerance_mm": 0.05,
            }])

            result = commission.run(model=None, stl=_box_stl(work), out_dir=work / "out",
                                    plan=plan, render=False)

            support = next(c for c in result.checks if c.id == "support-S-01")
            self.assertEqual(support.result, "FAIL",
                             "a declared orientation without bed contact cannot pass")
            self.assertIn("plan model_to_printer_matrix", support.detail)
            self.assertEqual(on_end, result.evidence["planned_placements"][0]["transform"])

    def test_every_support_rule_is_screened_not_just_the_first(self) -> None:
        """`rules[0]` left the rest unchecked, so a plan could forbid support on
        a face nobody ever screened and still exit zero."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            plan = _plan(support_rules=[
                {"id": "S-01", "disposition": "SUPPORT_ALLOWED",
                 "downward_normal_z_max": -0.73, "max_out_of_limit_area_mm2": 10000.0,
                 "model_to_printer_matrix": [[1, 0, 0, 0], [0, 1, 0, 0],
                                              [0, 0, 1, 0], [0, 0, 0, 1]],
                 "bed_z_mm": 0.0, "bed_tolerance_mm": 0.05},
                {"id": "S-02", "disposition": "SELF_SUPPORT_REQUIRED",
                 "downward_normal_z_max": -0.73, "max_out_of_limit_area_mm2": 2150.0,
                 "model_to_printer_matrix": [[1, 0, 0, 0], [0, 1, 0, 0],
                                              [0, 0, 1, 0], [0, 0, 0, 1]],
                 "bed_z_mm": 0.0, "bed_tolerance_mm": 0.05},
            ])

            result = commission.run(model=None, stl=_box_stl(work), out_dir=work / "out",
                                    plan=plan, render=False)

            ids = {c.id for c in result.checks}
            self.assertIn("support-S-01", ids)
            self.assertIn("support-S-02", ids)
            # The second rule's contradiction must be caught, not skipped.
            self.assertEqual("FAIL",
                             next(c for c in result.checks
                                  if c.id == "support-ceiling-S-02").result)


class InterfaceCheckTest(unittest.TestCase):
    """The check that had no coverage at all: every other fixture here sets
    `interfaces: []`, so nothing ever exercised it and it shipped comparing a
    mm3 volume against the plan's millimetres.
    """

    @staticmethod
    def _shell_and_core(work: Path, gap: float):
        """A cavity with a known per-side gap, and the block that seats in it."""
        outer = trimesh.creation.box(extents=(30, 30, 30))
        cavity = trimesh.creation.box(extents=(20 + 2 * gap, 20 + 2 * gap, 40))
        shell = trimesh.boolean.difference([outer, cavity])
        shell_path = work / "shell.stl"
        shell.export(shell_path)
        core_path = work / "core.stl"
        trimesh.creation.box(extents=(20, 20, 20)).export(core_path)
        return shell_path, str(core_path)

    def _plan_with_band(self, low: float, high: float):
        return _plan(interfaces=[{"id": "I-01", "fit_type": "clearance",
                                  "min_mm": low, "max_mm": high}])

    def test_a_correctly_clearing_part_passes(self) -> None:
        """The regression. A 0.2 mm per-side gap against a declared [0.15, 0.30]
        band is exactly right, and used to FAIL because its overlap volume of
        0.0 mm3 is not >= 0.15."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            stl, core = self._shell_and_core(work, gap=0.2)

            result = commission.run(model=None, stl=stl, out_dir=work / "out",
                                    plan=self._plan_with_band(0.15, 0.30),
                                    reference=core, render=False)

            fit_check = next(c for c in result.checks if c.id.startswith("fit"))
            self.assertEqual("PASS", fit_check.result, fit_check.detail)
            self.assertAlmostEqual(0.2, result.evidence["seated_clearance_mm"], delta=0.02)

    def test_an_over_clearanced_part_fails(self) -> None:
        """Over-clearance fails the fit exactly as interference does -- it is
        what makes a captured part rattle."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            stl, core = self._shell_and_core(work, gap=1.0)

            result = commission.run(model=None, stl=stl, out_dir=work / "out",
                                    plan=self._plan_with_band(0.15, 0.30),
                                    reference=core, render=False)

            fit_check = next(c for c in result.checks if c.id.startswith("fit"))
            self.assertEqual("FAIL", fit_check.result)
            self.assertIn("Too loose", fit_check.action)

    def test_an_interfering_part_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            stl, core = self._shell_and_core(work, gap=-0.5)

            result = commission.run(model=None, stl=stl, out_dir=work / "out",
                                    plan=self._plan_with_band(0.15, 0.30),
                                    reference=core, render=False)

            fit_check = next(c for c in result.checks if c.id.startswith("fit"))
            self.assertEqual("FAIL", fit_check.result)
            self.assertIn("Too tight", fit_check.action)

    def test_a_deliberate_interference_band_accepts_overlap(self) -> None:
        """The contract has no universal zero-interference rule: a press or
        crush-rib interface declares a negative band on purpose."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            stl, core = self._shell_and_core(work, gap=-0.2)

            result = commission.run(model=None, stl=stl, out_dir=work / "out",
                                    plan=self._plan_with_band(-0.30, -0.10),
                                    reference=core, render=False)

            self.assertEqual("PASS", next(c for c in result.checks if c.id.startswith("fit")).result)


class EdgeCheckTest(unittest.TestCase):
    def test_an_edge_the_plan_cannot_locate_is_reported_not_skipped(self) -> None:
        """The contract's edge row has no `corner_xy`, so on a conformant plan
        every edge used to be skipped in silence and the gate still exited zero.
        """
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            plan = _plan(edges=[{"id": "E-01", "min_radius_mm": 0.4, "samples_required": 3}])

            result = commission.run(model=None, stl=_box_stl(work), out_dir=work / "out",
                                    plan=plan, render=False)

            edge = next(c for c in result.checks if c.id == "edge-E-01")
            self.assertEqual("FAIL", edge.result)
            self.assertIn("corner_xy", edge.action)
            self.assertIn("not a met radius", edge.action)

    def test_a_missing_section_extra_reports_instead_of_taking_the_gate_down(self) -> None:
        """One optional dependency used to raise straight out of `run`, losing
        every other check's verdict along with it."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            # The band has to be one a sharp corner genuinely violates, or the
            # assertion below asserts nothing: a plain box corner measures
            # exactly 0.0 mm, which sits inside [0.0, 0.1]. This test passed for
            # a while on an accident -- the fixture plan declared no
            # `model_to_printer_matrix`, so the gate fell back to `orient.best`,
            # rotated the box, and looked for a corner that was no longer there.
            plan = _plan(edges=[{"id": "E-01", "corner_xy": [15.0, 10.0],
                                 "min_radius_mm": 0.5, "max_radius_mm": 1.0}])

            result = commission.run(model=None, stl=_box_stl(work), out_dir=work / "out",
                                    plan=plan, render=False)

            edge = next(c for c in result.checks if c.id == "edge-E-01")
            # Not `assertIn(result, (PASS, FAIL, SKIPPED))` -- those are the only
            # three values the field can hold, so that assertion cannot fail.
            if edge.result == "SKIPPED":
                self.assertIn("section", edge.action)
                self.assertIn("do not treat it as met", edge.action)
            else:
                self.assertEqual("FAIL", edge.result,
                                 "a sharp corner is outside the declared [0.0, 0.1] band "
                                 "only if measured; a PASS here would mean nothing ran")
            # Whatever happened to the edge, the rest of the gate still ran.
            self.assertTrue(any(c.id == "solid" for c in result.checks))


class ReceiptLocationTest(unittest.TestCase):
    def test_receipts_written_below_the_project_are_refused(self) -> None:
        """A run used `--out out`, produced a flawless candidate, and was
        rejected for a missing manifest that existed one directory down.
        `contracts validate` resolves <project-dir>/<name> and does not search."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            plan_path = work / "print_plan_checks.json"
            plan_path.write_text(json.dumps(_plan(expected_bbox_mm={"x": 30, "y": 20, "z": 10})),
                                 encoding="utf-8")

            result = commission.run(
                model=None, stl=_box_stl(work), out_dir=work / "out", render=False,
                plan=_plan(expected_bbox_mm={"x": 30, "y": 20, "z": 10}),
                plan_path=plan_path)

            check = next(c for c in result.checks if c.id == "receipt-location")
            self.assertEqual("FAIL", check.result)
            self.assertIn("does not search subdirectories", check.action)

    def test_a_verifier_writing_no_receipts_is_not_constrained(self) -> None:
        """It passes --no-receipts and writes none. Forcing its --out to the
        project directory made one overwrite the designer's commission.json --
        the very file its own recomputation exists to be compared against."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            plan_path = work / "print_plan_checks.json"
            plan_path.write_text(json.dumps(_plan(expected_bbox_mm={"x": 30, "y": 20, "z": 10})),
                                 encoding="utf-8")

            result = commission.run(
                model=None, stl=_box_stl(work), out_dir=work / "verify", render=False,
                plan=_plan(expected_bbox_mm={"x": 30, "y": 20, "z": 10}),
                plan_path=plan_path, writes_receipts=False)

            self.assertEqual([], [c for c in result.checks if c.id == "receipt-location"])

    def test_receipts_beside_the_plan_are_fine(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            plan_path = work / "print_plan_checks.json"
            plan_path.write_text(json.dumps(_plan(expected_bbox_mm={"x": 30, "y": 20, "z": 10})),
                                 encoding="utf-8")

            result = commission.run(
                model=None, stl=_box_stl(work), out_dir=work, render=False,
                plan=_plan(expected_bbox_mm={"x": 30, "y": 20, "z": 10}),
                plan_path=plan_path)

            self.assertEqual([], [c for c in result.checks if c.id == "receipt-location"])


class StepCheckTest(unittest.TestCase):
    def test_a_mesh_built_part_says_it_has_no_step(self) -> None:
        """A five-part run wrote the same note by hand five times. A gap the
        receipt does not mention is a gap somebody has to find."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            model = work / "model.py"
            model.write_text(
                "from designer_toolkit.templates import box_shell\n"
                "_b = box_shell(inner=(24.0, 14.0, 7.0), wall=3.0, floor=3.0)\n"
                "PARAMS, part = _b.params, _b.part\n",
                encoding="utf-8")

            result = commission.run(
                model=model, stl=None, out_dir=work / "out", render=False,
                plan=_plan(expected_bbox_mm={"x": 30, "y": 20, "z": 10}))

            step = next(c for c in result.checks if c.id == "step")
            self.assertIn(step.result, ("SKIPPED", "PASS"))
            if step.result == "SKIPPED":
                self.assertIn("STL only", step.detail)
                self.assertIn("Nothing is wrong with the geometry", step.action)

    def test_a_verifier_is_not_asked_for_a_step_it_never_exports(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            result = commission.run(
                model=None, stl=_box_stl(work), out_dir=work / "out", render=False,
                plan=_plan(expected_bbox_mm={"x": 30, "y": 20, "z": 10}))

            self.assertEqual([], [c for c in result.checks if c.id == "step"])


class SolidCheckTest(unittest.TestCase):
    def test_a_two_body_export_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            first = trimesh.creation.box(extents=(10, 10, 10))
            second = trimesh.creation.box(extents=(10, 10, 10))
            second.apply_translation((40, 0, 0))
            path = work / "two.stl"
            trimesh.util.concatenate((first, second)).export(path)

            result = commission.run(model=None, stl=path, out_dir=work / "out",
                                    plan=_plan(), render=False)

            self.assertEqual(next(c for c in result.checks if c.id == "solid").result, "FAIL")


class ClearanceSamplingTest(unittest.TestCase):
    """The gap is measured wherever the mating part is sampled, and it used to be
    sampled only at its vertices -- a box has eight. Anything between them was
    invisible, so the number came back plausible and wrong rather than as an
    error, which is the worst shape a measurement can have."""

    def _pair(self, local_gap: float | None):
        floor, gap = 8.0, 0.50
        plate = trimesh.creation.box(extents=(40.0, 40.0, 4.0))
        plate.apply_translation([0, 0, floor + gap + 2.0])
        body = trimesh.creation.box(extents=(70.0, 70.0, floor))
        body.apply_translation([0, 0, floor / 2])
        wall = trimesh.boolean.difference([
            trimesh.creation.box(extents=(70.0, 70.0, 20.0)).apply_translation([0, 0, 10.0]),
            trimesh.creation.box(extents=(41.0, 41.0, 20.0)).apply_translation([0, 0, 10.0])])
        if local_gap is None:            # an unobstructed seat: no boss at all
            return trimesh.boolean.union([body, wall]), plate
        height = gap - local_gap
        boss = trimesh.creation.cylinder(radius=3.0, height=height, sections=64)
        boss.apply_translation([0, 0, floor + height / 2])
        return trimesh.boolean.union([body, wall, boss]), plate

    def test_a_local_interference_between_vertices_is_found(self) -> None:
        """A boss under the middle of the plate leaves 0.05 mm where the rest of
        the seat has 0.50. None of the plate's eight vertices sits over it, so
        vertex sampling reported 0.50 -- ten times too loose, in the direction
        that lets an interference pass."""
        cavity, plate = self._pair(local_gap=0.05)

        measured = commission.seated_clearance_mm(cavity, plate)

        self.assertAlmostEqual(0.05, measured, delta=0.01)

    def test_an_unobstructed_seat_still_reads_its_own_gap(self) -> None:
        """Denser sampling must not invent tightness that is not there."""
        cavity, plate = self._pair(local_gap=None)
        self.assertAlmostEqual(0.50, commission.seated_clearance_mm(cavity, plate), delta=0.01)

    def test_the_samples_are_deterministic(self) -> None:
        """Reruns on unchanged inputs are meant to be byte-identical, so the
        sampler may not be random."""
        _cavity, plate = self._pair(local_gap=0.05)
        first = commission._clearance_samples(plate)
        second = commission._clearance_samples(plate)
        self.assertEqual(first.shape, second.shape)
        self.assertTrue((first == second).all())


class MultipleInterfaceTest(unittest.TestCase):
    """Both benchmark runs hit this and both responded the same way.

    One reference yields one number -- the tightest point of the assembly -- and
    the gate used to intersect every declared band into `[max(mins), min(maxes)]`
    and compare that. For one interface that is right. For six it gave `[0.30,
    0.25]`, an empty window no geometry can enter, so each run deleted
    interfaces from its plan until one remained. That silently guts the contract
    the plan is supposed to be.
    """

    def _pair(self, work: Path, clearance: float):
        inner = trimesh.creation.box(extents=(20.0, 20.0, 10.0))
        inner.apply_translation([0, 0, 5.0])
        outer = trimesh.creation.box(extents=(20.0 + 2 * clearance, 20.0 + 2 * clearance, 10.0))
        outer.apply_translation([0, 0, 5.0])
        shell = trimesh.boolean.difference([
            trimesh.creation.box(extents=(40.0, 40.0, 12.0)).apply_translation([0, 0, 6.0]),
            outer])
        path = work / "ref.stl"
        inner.export(path)
        stl = work / "part.stl"
        shell.export(stl)
        return stl, path

    def test_several_unreferenced_interfaces_are_refused_not_intersected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            stl, ref = self._pair(work, 0.25)
            plan = _plan(interfaces=[
                {"id": "I-01", "min_mm": 0.15, "max_mm": 0.30},
                {"id": "I-02", "min_mm": 0.30, "max_mm": 0.60},
            ], expected_bbox_mm={"x": 40.0, "y": 40.0, "z": 12.0})

            result = commission.run(model=None, stl=stl, out_dir=work / "out", plan=plan,
                                    reference=str(ref), render=False)

            fit = next(c for c in result.checks if c.id.startswith("fit"))
            self.assertEqual("FAIL", fit.result)
            self.assertIn("name no reference of their own", fit.detail)
            self.assertIn("Do not delete interfaces to fit the tool", fit.action)

    def test_each_interface_with_its_own_reference_is_measured_separately(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            stl, ref = self._pair(work, 0.25)
            plan = _plan(interfaces=[
                # The pair seats flush -- per-side clearance includes underneath --
                # so one band admits that and one does not. The point is that each
                # is judged on its own, not folded into a shared window.
                {"id": "I-01", "min_mm": -0.05, "max_mm": 0.05, "reference": str(ref)},
                {"id": "I-02", "min_mm": 0.90, "max_mm": 1.20, "reference": str(ref)},
            ], expected_bbox_mm={"x": 40.0, "y": 40.0, "z": 12.0})

            result = commission.run(model=None, stl=stl, out_dir=work / "out", plan=plan,
                                    render=False)

            results = {c.id: c.result for c in result.checks if c.id.startswith("fit-")}
            self.assertEqual({"fit-I-01": "PASS", "fit-I-02": "FAIL"}, results,
                             "each band is judged against its own measurement")


class SharpEdgeTest(unittest.TestCase):
    """The contract has a row for an edge left sharp on purpose, and
    `validators` refuses one without a stated reason. Demanding `corner_xy` of
    it made a conformant plan ungateable: there is no radius to measure."""

    def test_a_declared_sharp_edge_carries_its_reason(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            plan = _plan(edges=[{"id": "E-01", "min_radius_mm": 0.0, "max_radius_mm": 0.0,
                                 "allowed_sharp": True,
                                 "allowed_sharp_reason": "mates flush to the bottom board"}])

            result = commission.run(model=None, stl=_box_stl(work), out_dir=work / "out",
                                    plan=plan, render=False)

            edge = next(c for c in result.checks if c.id == "edge-E-01")
            self.assertEqual("PASS", edge.result)
            self.assertIn("bottom board", edge.detail)

    def test_a_declared_radius_with_nowhere_to_measure_still_fails(self) -> None:
        """The sharp-edge path must not become a way to skip a real radius."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            plan = _plan(edges=[{"id": "E-02", "min_radius_mm": 0.5, "max_radius_mm": 1.0}])

            result = commission.run(model=None, stl=_box_stl(work), out_dir=work / "out",
                                    plan=plan, render=False)

            self.assertEqual("FAIL", next(c for c in result.checks if c.id == "edge-E-02").result)


class SeatingTest(unittest.TestCase):
    """`bed_z_mm` and `bed_tolerance_mm` were required of every support rule and
    read by nothing. Bed contact is measured against the part's own lowest
    plane, so a part floating above the bed reported its full footprint as
    touching -- true of that plane, and not of the bed."""

    def _lifted(self, work: Path, lift: float) -> Path:
        mesh = trimesh.creation.box(extents=(30, 20, 10))
        mesh.apply_translation([0, 0, -float(mesh.bounds[0][2]) + lift])
        path = work / f"lift{lift}.stl"
        mesh.export(path)
        return path

    def test_a_seated_part_passes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            result = commission.run(model=None, stl=self._lifted(work, 0.0),
                                    out_dir=work / "out", plan=_plan(), render=False)
            seated = next(c for c in result.checks if c.id.startswith("seated-"))
            self.assertEqual("PASS", seated.result)

    def test_a_part_off_the_bed_fails(self) -> None:
        """Sixteen millimetres, because that is the number from the archived run
        this file's own docstring cites."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            result = commission.run(model=None, stl=self._lifted(work, 16.0),
                                    out_dir=work / "out", plan=_plan(), render=False)

            seated = next(c for c in result.checks if c.id.startswith("seated-"))
            self.assertEqual("FAIL", seated.result)
            self.assertIn("16.0", seated.detail)
            self.assertIn("seated-S-01", [c.id for c in result.failed])


class BodyCountTest(unittest.TestCase):
    """One body, almost always: a second means a boolean split the part. But a
    box too big for the bed is delivered as segments a slicer separates, and
    hard-coding one made the gate reject a correct six-piece hive body for being
    six pieces."""

    def _two_bodies(self, work: Path) -> Path:
        pair = trimesh.util.concatenate([
            trimesh.creation.box(extents=(30, 20, 10)),
            trimesh.creation.box(extents=(30, 20, 10)).apply_translation([60, 0, 0])])
        path = work / "pair.stl"
        pair.export(path)
        return path

    def test_an_undeclared_second_body_still_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            result = commission.run(model=None, stl=self._two_bodies(work),
                                    out_dir=work / "out",
                                    plan=_plan(expected_bbox_mm={"x": 90.0, "y": 20.0,
                                                                 "z": 10.0}),
                                    render=False)

            solid = next(c for c in result.checks if c.id == "solid")
            self.assertEqual("FAIL", solid.result)
            self.assertIn("plan expects 1", solid.detail)

    def test_a_declared_second_body_passes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            result = commission.run(model=None, stl=self._two_bodies(work),
                                    out_dir=work / "out",
                                    plan=_plan(expected_bodies=2,
                                               expected_bbox_mm={"x": 90.0, "y": 20.0,
                                                                 "z": 10.0}),
                                    render=False)

            self.assertEqual("PASS", next(c for c in result.checks if c.id == "solid").result)

    def test_a_single_part_declared_as_many_fails(self) -> None:
        """The count is a claim about the part, not a way to silence the check."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            result = commission.run(model=None, stl=_box_stl(work), out_dir=work / "out",
                                    plan=_plan(expected_bodies=4), render=False)

            self.assertEqual("FAIL", next(c for c in result.checks if c.id == "solid").result)


class SliceProfileEvidenceTest(unittest.TestCase):
    def test_the_gate_emits_the_unconditioned_curve(self) -> None:
        """The charter sends readers to `evidence.slice_profile`, and DIRECT has
        no verifier -- so it has to be in the designer's own receipt, not only in
        the audit path. A measured run found the field missing and reached into
        the library itself to get it."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            result = commission.run(model=None, stl=_box_stl(work), out_dir=work / "out",
                                    plan=_plan(), render=False)

            profile = result.evidence["slice_profile"]
            self.assertEqual(28, len(profile))
            self.assertTrue(all(row["area_mm2"] > 0 for row in profile))
            heights = [row["z"] for row in profile]
            self.assertEqual(heights, sorted(heights))


class VisualEvidenceTest(unittest.TestCase):
    def test_not_rendering_blocks_the_visual_verdict(self) -> None:
        """`--no-render` leaves exactly as little to look at as a renderer that
        crashed, and the receipt has to say so either way. Keyed off the SKIPPED
        check alone it did not: no render was attempted, so no check was added,
        so the receipt invited a verdict on images that did not exist -- which is
        the defect the block was written to prevent, arriving by another door."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            result = commission.run(model=None, stl=_box_stl(work), out_dir=work / "out",
                                    plan=_plan(), render=False)

            render = next(c for c in result.checks if c.id == "render")
            self.assertEqual("SKIPPED", render.result)

            from . import receipts
            text = receipts.build_readiness(result.as_dict(), job_id="t",
                                            updated_utc="2026-01-01T00:00:00Z")
            self.assertIn("CANNOT BE ANSWERED HERE", text)
            self.assertNotIn("- `visual_accept`: <!-- REQUIRED", text)


class RepairCheckTest(unittest.TestCase):
    """The gate measures watertightness on the *normalized* mesh, which is right
    -- an STL is a vertex soup and the raw parse calls every correct solid open.
    But it makes the headline verdict a statement about a repaired mesh, and a
    candidate needing structural repair read identically to one needing none.
    Only the verifier's `dt.py integrity` ever saw the raw parse, and the DIRECT
    route has no verifier.
    """

    def test_a_clean_export_says_it_needed_no_repair(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            result = commission.run(model=None, stl=_box_stl(work), out_dir=work / "out",
                                    plan=_plan(), render=False)

            repair = next(c for c in result.checks if c.id == "repair")
            self.assertEqual("PASS", repair.result)
            self.assertIn("no faces dropped", repair.detail)

    def test_degenerate_faces_fail_rather_than_being_repaired_silently(self) -> None:
        """Merging coincident vertices is what the format requires. Dropping
        faces is geometry that was not exportable, and every check above this
        one then describes a solid that is not the one exported."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            mesh = trimesh.creation.box(extents=(30, 20, 10))
            # A zero-area triangle: three references to one corner. It survives
            # the STL round trip and is removed during normalization.
            faces = np.vstack([mesh.faces, [0, 0, 0]])
            degenerate = trimesh.Trimesh(vertices=mesh.vertices, faces=faces,
                                         process=False)
            path = work / "degenerate.stl"
            degenerate.export(path)

            result = commission.run(model=None, stl=path, out_dir=work / "out",
                                    plan=_plan(), render=False)

            repair = next(c for c in result.checks if c.id == "repair")
            self.assertEqual("FAIL", repair.result, repair.detail)
            self.assertIn("degenerate", repair.detail)
            self.assertIn("repair", [c.id for c in result.failed])


class PlanDeclaredFeatureTest(unittest.TestCase):
    """The plan-side half of feature checking.

    A template expectation is derived from the caller's parameters, so it cannot
    catch a feature nobody asked for -- drop the parameter and the check leaves
    with the geometry. A plan row is written from the sheet, upstream of the
    model, so it survives the model omitting the feature entirely. That is the
    only thing standing between a transcription that quietly lost a hole and a
    part that measures self-consistently wrong.
    """

    def test_a_feature_the_model_never_built_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            plan = _plan(features=[{"kind": "through_hole", "id": "H-01",
                                    "at": [0.0, 0.0], "d_mm": 5.0,
                                    "z_from": -4.0, "z_to": 4.0}])

            result = commission.run(model=None, stl=_box_stl(work), out_dir=work / "out",
                                    plan=plan, render=False)

            self.assertIn("feature-H-01", [c.id for c in result.failed],
                          "a solid box has no 5 mm bore, and the plan says it must")

    def test_the_receipt_records_where_the_expectations_came_from(self) -> None:
        """Auditable on purpose: an expectation from the plan and one from the
        template carry different weight, and a reader cannot tell them apart
        from the check result alone."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            plan = _plan(features=[{"kind": "solid_region", "id": "mid",
                                    "z": 0.0, "area_mm2": 600.0}])

            result = commission.run(model=None, stl=_box_stl(work), out_dir=work / "out",
                                    plan=plan, render=False)

            self.assertEqual("plan", result.evidence["expected_features_source"])

    def test_no_declared_features_records_no_source(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            result = commission.run(model=None, stl=_box_stl(work), out_dir=work / "out",
                                    plan=_plan(), render=False)
            self.assertNotIn("expected_features_source", result.evidence)


class CliTest(unittest.TestCase):
    def test_a_failing_candidate_exits_nonzero(self) -> None:
        """The whole point: a failing candidate cannot reach a verifier."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            stl = _box_stl(work, extents=(30, 20, 14))
            plan_path = work / "plan.json"
            plan_path.write_text(json.dumps(
                _plan(expected_bbox_mm={"x": 30, "y": 20, "z": 10}, bbox_tolerance_mm=0.5)),
                encoding="utf-8")

            completed = subprocess.run(
                [sys.executable, "-m", "designer_toolkit.commission",
                 "--stl", str(stl), "--plan", str(plan_path),
                 "--out", str(work / "out"), "--no-render",
                 "--updated-utc", "2026-01-01T00:00:00Z"],
                cwd=_SCRIPTS, capture_output=True, text=True, check=False,
            )

            self.assertEqual(completed.returncode, 1)
            self.assertIn("FAIL envelope", completed.stderr)
            self.assertEqual(json.loads(completed.stdout)["verdict"], "FAIL")

    def test_an_ungateable_plan_is_refused_before_any_geometry_is_built(self) -> None:
        """`plan check` was a separate command somebody had to remember to run.
        Skipped, a rule with no `model_to_printer_matrix` still reached
        `planned_placement`, which falls back to `orient.best` and renames the
        placement -- so the gate screened the orientation the part prints best
        in, reported PASS, and said nothing about the one the plan asked for."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            plan = _plan()
            del plan["support_rules"][0]["model_to_printer_matrix"]
            plan_path = work / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")

            completed = subprocess.run(
                [sys.executable, "-m", "designer_toolkit.commission",
                 "--stl", str(_box_stl(work)), "--plan", str(plan_path),
                 "--out", str(work / "out"), "--no-render",
                 "--updated-utc", "2026-01-01T00:00:00Z"],
                cwd=_SCRIPTS, capture_output=True, text=True, check=False,
            )

            self.assertEqual(2, completed.returncode)
            self.assertIn("model_to_printer_matrix", completed.stderr)
            self.assertFalse((work / "out").exists(), "nothing should have been built")

    def test_the_receipt_says_how_much_of_the_gate_ran(self) -> None:
        """PASS says nothing failed; it does not say much ran, and a reader
        takes `status: READY` to mean both."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            result = commission.run(model=None, stl=_box_stl(work), out_dir=work / "out",
                                    plan=_plan(), render=False)

            coverage = result.as_dict()["coverage"]
            self.assertEqual(coverage["declared"], coverage["ran"] + len(coverage["skipped"]))
            self.assertIn("fit", coverage["skipped"],
                          "a plan declaring no interfaces measures no fit")

            from . import receipts
            text = receipts.build_readiness(result.as_dict(), job_id="t",
                                            updated_utc="2026-01-01T00:00:00Z")
            self.assertIn(f"{coverage['ran']} of {coverage['declared']} checks ran", text)
            self.assertIn("`fit`", text)

    def test_it_writes_the_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            commission.run(model=None, stl=_box_stl(work), out_dir=work / "out",
                           plan=_plan(expected_bbox_mm={"x": 30, "y": 20, "z": 10}),
                           render=False)

            payload = json.loads((work / "out" / "commission.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["verdict"], "PASS")
            self.assertIsNone(payload["judgment_required"]["visual_accept"])


class LoadPartTest(unittest.TestCase):
    def test_a_module_without_part_or_build_says_what_it_needs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            module = Path(raw) / "model.py"
            module.write_text("x = 1\n", encoding="utf-8")

            with self.assertRaises(ValueError) as caught:
                commission.load_model(module)

            self.assertIn("build()", str(caught.exception))

    def test_the_build123d_skeleton_is_not_a_model_the_gate_can_import(self) -> None:
        """The backend docs and `--model` are one contract, and it was broken.

        `build123d-patterns.md` printed a `commission --model model.py` command
        above a skeleton whose solid is named `body`, so following the file
        exactly produced a script the gate refuses -- two paragraphs under its
        own prose saying the exported STL is the handoff. Nothing had ever run
        that path: it is the one backend with no runner and no test.

        This pins both halves. The loader's contract is `part`/`build()` and a
        build123d `Part` is not a trimesh either way, so the doc must send a
        reader to `--stl`.
        """
        references = Path(__file__).resolve().parents[2] / "references"
        doc = (references / "build123d-patterns.md").read_text(encoding="utf-8")
        self.assertIn("commission --stl body.stl", doc)
        self.assertNotIn("commission --model", doc)

        with tempfile.TemporaryDirectory() as raw:
            module = Path(raw) / "model.py"
            module.write_text("body = object()\nref_part = object()\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                commission.load_model(module)


if __name__ == "__main__":
    unittest.main()
