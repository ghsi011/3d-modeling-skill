#!/usr/bin/env python3
"""A support area below tessellation noise is not a finding.

`SELF_SUPPORT_REQUIRED` forces the declared ceiling to exactly `0.0`, and that is
correct -- it is a disposition, not a budget, and two archived runs declared it
with ceilings of 1850 and 2150 mm2 and passed. The measured side, though, is a
sum of triangle areas off a tessellated mesh, and comparing a float sum against
exact zero asks the mesh to be perfect rather than the part to be right.

**A measured run paid for that.** A correct 2x1x3U grid bin reported 5.5e-2 mm2
of out-of-limit area, then **8e-6 mm2** after refining to 1.1 million triangles
-- slivers thrown where a foot's inner arc is tangent to the bin's outer face at
a single point. Refining further did not remove them. Neither did reformulating
the boolean, nor `clean()`, nor steepening the flare. **The designer rebuilt the
entire model in a second CAD kernel** to reach a literal `0.0`, and that rebuild
was a large part of a 38.7-minute dispatch.

8e-6 mm2 is eight square micrometres. A 0.4 mm nozzle at 0.2 mm layers lays a
bead of roughly 8e-2 mm2 -- so the geometry that forced a kernel rewrite was
about one ten-thousandth of the smallest thing the printer can deposit.

The floor is a **noise floor, not a budget**: at 1e-3 mm2 nothing a printer can
express fits under it, so the disposition still means what it says.
"""
from __future__ import annotations

import unittest

from .commission import TESSELLATION_NOISE_MM2


class TheNoiseFloorIsBelowAnythingPrintableTest(unittest.TestCase):
    """What stops a noise floor becoming a budget by another name."""

    def test_it_is_far_under_one_extrusion_bead(self) -> None:
        """0.4 mm nozzle, 0.2 mm layer: ~8e-2 mm2 of deposited cross-section.
        The floor must be a small fraction of the smallest depositable feature,
        or it is licensing real unsupported geometry."""
        one_bead_mm2 = 0.4 * 0.2
        self.assertLess(TESSELLATION_NOISE_MM2, one_bead_mm2 / 10.0)

    def test_it_is_above_the_sliver_that_forced_a_kernel_rewrite(self) -> None:
        """The observed tangency sliver, after 1.1M triangles: 8e-6 mm2."""
        self.assertGreater(TESSELLATION_NOISE_MM2, 8e-6 * 10.0)

    def test_it_is_not_large_enough_to_hide_a_real_overhang(self) -> None:
        """A 1 mm x 1 mm unsupported ledge is 1 mm2 -- a thousand times the
        floor, and the kind of thing this gate exists to catch."""
        self.assertLess(TESSELLATION_NOISE_MM2, 1.0 / 100.0)


class TheComparisonUsesTheFloorTest(unittest.TestCase):
    """**Driven through the real `_check_support`.**

    My first version of this class re-implemented the comparison
    (`area <= ceiling + FLOOR`) and asserted against the copy. Every row passed
    while the call site was reverted to exact zero -- the one mutation the whole
    fix exists to prevent. A test that recomputes the expected value the way the
    code does cannot disagree with the code. So these call the function.

    `overhang_mm2` is stubbed rather than modelled: producing a mesh whose
    tessellation slivers land on an exact target is the problem this fix exists
    to avoid, and it would make the row depend on a CAD kernel's rounding.
    """

    @staticmethod
    def _verdict(area: float, ceiling: float = 0.0,
                 disposition: str = "SELF_SUPPORT_REQUIRED") -> str:
        import trimesh
        from unittest import mock
        from . import commission as C

        mesh = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
        mesh.apply_translation((5.0, 5.0, 5.0))
        plan = {"support_rules": [{
            "id": "S-01", "disposition": disposition,
            "max_out_of_limit_area_mm2": ceiling,
            "downward_normal_z_max": -0.73,
            "bed_z_mm": 0.0, "bed_tolerance_mm": 0.05,
            "model_to_printer_matrix": [[1, 0, 0, 0], [0, 1, 0, 0],
                                        [0, 0, 1, 0], [0, 0, 0, 1]],
        }]}

        placement = C.planned_placement(plan["support_rules"][0], mesh, -0.73)
        stub = type(placement)(**{**placement.__dict__, "overhang_mm2": area})
        commission = C.Commission()
        with mock.patch.object(C, "planned_placement", return_value=stub):
            C._check_support(commission, mesh, plan)
        rows = [c for c in commission.checks if c.id.startswith("support")
                and "ceiling" not in c.id]
        return rows[0].result if rows else "NO-ROW"

    def test_the_observed_sliver_now_passes(self) -> None:
        """8e-6 mm2: the sliver that cost a CAD-kernel rewrite."""
        self.assertEqual("PASS", self._verdict(8e-6))

    def test_a_pre_refinement_sliver_still_fails(self) -> None:
        """5.5e-2 mm2 -- what the same part measured before tessellation was
        refined -- stays a finding. The floor forgives numerical dust, not a
        coarse mesh."""
        self.assertEqual("FAIL", self._verdict(5.5e-2))

    def test_a_real_unsupported_face_still_fails(self) -> None:
        self.assertEqual("FAIL", self._verdict(1.0))
        self.assertEqual("FAIL", self._verdict(1850.0))

    def test_a_declared_budget_still_binds_above_the_floor(self) -> None:
        """`SUPPORT_ALLOWED` keeps its ceiling; the floor shifts it by a
        thousandth of a square millimetre and by nothing else."""
        self.assertEqual("PASS", self._verdict(
            10.0, ceiling=10.0, disposition="SUPPORT_ALLOWED"))
        self.assertEqual("FAIL", self._verdict(
            10.1, ceiling=10.0, disposition="SUPPORT_ALLOWED"))


class TheFindingSaysWhereTest(unittest.TestCase):
    """How much, without where, is a number the reader cannot act on.

    A measured run was told `0.008 mm2 past normal_z <= -0.73` three separate
    times, and each time loaded the STL in trimesh itself to print the offending
    triangles' centroids -- because a real unsupported face and a lofted surface
    tessellating steeper than its nominal angle report the same number and need
    opposite responses.
    """

    @staticmethod
    def _part():
        import trimesh
        box = trimesh.creation.box(extents=(20, 20, 10))
        box.apply_translation((10, 10, 5))
        shelf = trimesh.creation.box(extents=(10, 20, 2))
        shelf.apply_translation((25, 10, 9))
        return trimesh.boolean.union([box, shelf], engine="manifold")

    def test_it_points_at_the_overhanging_face(self) -> None:
        """The shelf's underside is at z=8, x from 20 to 30. That is the answer."""
        from .metrics import overhang_locations
        found = overhang_locations(self._part(), bed_z=0.0)
        self.assertTrue(found)
        for facet in found:
            with self.subTest(facet=facet):
                self.assertAlmostEqual(8.0, facet["centroid_mm"]["z"], places=2)
                self.assertGreater(facet["centroid_mm"]["x"], 20.0)

    def test_a_clean_part_reports_no_locations(self) -> None:
        """**Control.** No overhang, nothing to point at -- an empty list, not a
        misleading nearest-facet."""
        import trimesh
        box = trimesh.creation.box(extents=(20, 20, 10))
        box.apply_translation((10, 10, 5))
        self.assertEqual([], overhang_locations_of(box))

    def test_the_biggest_contributor_comes_first(self) -> None:
        from .metrics import overhang_locations
        found = overhang_locations(self._part(), bed_z=0.0, limit=3)
        areas = [f["area_mm2"] for f in found]
        self.assertEqual(sorted(areas, reverse=True), areas)


class ItSaysWhenThereIsNobodyToHandOffToTest(unittest.TestCase):
    """The advice recommends escalating to a print engineer. On a generated plan
    there is not one -- that is *why* the plan was generated -- so the reader is
    being pointed at a route that does not exist.

    Not a change to the bar: whether a CUSTOM job should be held to a DIRECT
    part's support standard is a contract decision. This only stops the reader
    hunting for a handoff that is not there, and makes the compromise visible
    instead of silent. Two measured runs took it silently: one rebuilt in a
    second CAD kernel, one roofed at 55 degrees instead of 45.
    """

    def test_a_generated_plan_says_the_escalation_is_unavailable(self) -> None:
        from .commission import _no_engineer_note
        note = _no_engineer_note({"owner": "builtin-direct-template"})
        self.assertIn("no print engineer", note)
        self.assertIn("not available", note)

    def test_an_authored_plan_says_nothing_extra(self) -> None:
        """**Control.** Where a print engineer *did* author the plan, the
        escalation is real and the note would be false."""
        from .commission import _no_engineer_note
        self.assertEqual("", _no_engineer_note({"owner": "print-engineer"}))

    def test_it_does_not_invite_a_silent_compromise(self) -> None:
        """Saying 'you have no escalation' without saying 'record it' would read
        as permission to distort the part quietly, which is worse than the
        confusion it replaces."""
        from .commission import _no_engineer_note
        note = _no_engineer_note({"owner": "builtin-direct-template"})
        self.assertIn("do not quietly distort", note)
        self.assertIn("visible", note)


def overhang_locations_of(mesh):
    from .metrics import overhang_locations
    return overhang_locations(mesh, bed_z=0.0)


if __name__ == "__main__":
    unittest.main()
