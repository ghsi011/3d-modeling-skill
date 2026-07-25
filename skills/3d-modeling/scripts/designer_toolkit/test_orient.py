"""Tests for the print-orientation sweep."""

import os
import sys
import unittest

import numpy as np
import trimesh

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from designer_toolkit import orient  # noqa: E402
from designer_toolkit.metrics import BARE_45_DEG, overhang_area  # noqa: E402


def _overhanging_part():
    """A plate on two legs: a large downward face held clear of the bed.

    Flat on the bed the underside is a genuine overhang; stood on end it is a
    vertical wall and screens clean. That asymmetry is what a sweep must find.
    """
    plate = trimesh.creation.box(extents=(40, 40, 3))
    plate.apply_translation((0, 0, 20))
    leg_a = trimesh.creation.box(extents=(4, 4, 20))
    leg_a.apply_translation((-16, 0, 10))
    leg_b = trimesh.creation.box(extents=(4, 4, 20))
    leg_b.apply_translation((16, 0, 10))
    return trimesh.util.concatenate((plate, leg_a, leg_b))


class SweepTest(unittest.TestCase):
    def test_every_candidate_is_seated_on_the_bed(self) -> None:
        """The regression this exists for.

        ``overhang_area`` excludes faces resting on the bed plane so bed contact
        is not counted as overhang. A rotated-but-untranslated part never
        touches that plane, so it is screened in a pose it will never be printed
        in. Every returned transform must therefore land the part on the bed.
        """
        mesh = _overhanging_part()

        for placement in orient.sweep(mesh):
            placed = mesh.copy()
            placed.apply_transform(placement.transform)
            self.assertAlmostEqual(
                float(placed.bounds[0][2]), 0.0, places=6,
                msg=f"{placement.name} is not seated on the bed",
            )

    def test_results_are_ordered_best_first(self) -> None:
        results = orient.sweep(_overhanging_part())

        areas = [round(p.overhang_mm2, 3) for p in results]
        self.assertEqual(areas, sorted(areas))
        self.assertEqual(orient.best(_overhanging_part()).name, results[0].name)

    def test_it_finds_the_orientation_that_removes_the_overhang(self) -> None:
        mesh = _overhanging_part()

        winner = orient.best(mesh)

        # Flat-on-bed leaves the 40x40 underside overhanging; the winner must be
        # decisively better than that, not marginally.
        flat = overhang_area(mesh, threshold=BARE_45_DEG)
        self.assertLess(winner.overhang_mm2, flat / 4)

    def test_ties_break_toward_bed_contact(self) -> None:
        """Two placements that both print clean are not equal if one stands on
        a postage stamp.
        """
        results = orient.sweep(trimesh.creation.box(extents=(30, 20, 10)))

        clean = [p for p in results if p.overhang_mm2 < 1e-6]
        self.assertGreater(len(clean), 1, "a box should print clean several ways")
        contacts = [p.bed_contact_mm2 for p in clean]
        self.assertEqual(contacts, sorted(contacts, reverse=True))

    def test_transform_is_a_rigid_4x4(self) -> None:
        for placement in orient.sweep(_overhanging_part()):
            transform = np.asarray(placement.transform, dtype=float)
            self.assertEqual(transform.shape, (4, 4))
            rotation = transform[:3, :3]
            np.testing.assert_allclose(rotation @ rotation.T, np.eye(3), atol=1e-9)
            self.assertAlmostEqual(float(np.linalg.det(rotation)), 1.0, places=9)

    def test_as_dict_is_json_safe(self) -> None:
        import json

        payload = orient.best(_overhanging_part()).as_dict()

        json.dumps(payload)  # must not raise on numpy scalars
        self.assertEqual(len(payload["transform"]), 4)


if __name__ == "__main__":
    unittest.main()
