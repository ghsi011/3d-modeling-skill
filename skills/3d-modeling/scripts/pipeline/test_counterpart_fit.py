#!/usr/bin/env python3
"""The zones an assembled-interface row declares, refused before geometry is paid for.

The heavy tier proves the *measurement* -- that a clamp gripping the inner race
fails while an equivalent clamp that does not passes. What is proved here is
everything that can be decided without loading a mesh: that a row which could not
decide anything is refused at preflight rather than at the end of a build.

Every case below is a way the row would have run, produced a number, and been
believed:

* a **retention floor of zero** passes for a candidate that touches the
  counterpart nowhere -- the check reports `retained_mm3 = 0.0 >= 0.0` and calls
  it a grip;
* **overlapping zones** make one piece of material simultaneously required and
  forbidden, so the row's verdict depends on which radius is larger rather than
  on the part;
* a **zero-height or inside-out zone** encloses nothing, and an empty region
  reports 0.0 mm3, which reads exactly like a part that stays clear;
* a **missing pose** would silently default the counterpart to the origin, and
  the two halves of a split clamp export in their *printed* pose -- side by side,
  not assembled -- so the origin is precisely where the bearing is not.

None of these is hypothetical shape-checking. Each is a value that yields a
plausible number rather than an error, which is the only kind of bad input worth
a preflight.
"""
from __future__ import annotations

import unittest

from . import contract as CT

# A row that is accepted, so each case below differs from a working one by
# exactly the thing it names. Numbers are a 608 bearing: 22 mm outside, 8 mm
# bore, 7 mm wide, with the inner ring free to turn inside r = 6.5.
GOOD = {
    "counterpart": "bearing.stl",
    "counterpart_sha256": "0" * 64,
    "pose": {"centre_mm": [0.0, 0.0, 12.0], "axis": [0.0, 1.0, 0.0]},
    "retain_r_mm": [9.5, 11.0],
    "retain_z_mm": [-3.5, 3.5],
    "clear_r_mm": 6.5,
    "clear_z_mm": [-20.0, 20.0],
    "min_retain_mm3": 150.0,
    "max_intrusion_mm3": 0.0,
}


def _problems(**over):
    row = dict(GOOD)
    for key, value in over.items():
        if value is _ABSENT:
            row.pop(key, None)
        else:
            row[key] = value
    return CT._counterpart_fit_problems(row, "feature 'bearing-fit'")


_ABSENT = object()


class TheZonesMustBeAbleToDecideSomethingTest(unittest.TestCase):

    def test_the_accepted_row_is_accepted(self) -> None:
        """Without this the rest prove only that the helper returns strings."""
        self.assertEqual([], _problems())

    def test_a_retention_floor_of_zero_is_refused(self) -> None:
        for floor in (0.0, -1.0):
            with self.subTest(floor=floor):
                problems = _problems(min_retain_mm3=floor)
                self.assertTrue(any("cannot fail" in p for p in problems),
                                f"a floor of {floor} is met by a part that grips "
                                f"nothing: {problems}")

    def test_zones_that_overlap_are_refused(self) -> None:
        """`clear_r_mm` past the retained band's inner radius.

        The candidate's material in the shared ring would be counted as gripping
        the outer race and as fouling the inner one at the same time.
        """
        problems = _problems(clear_r_mm=10.0)
        self.assertTrue(any("overlap" in p for p in problems), problems)

    def test_a_zone_that_encloses_nothing_is_refused(self) -> None:
        cases = {
            "retain_z_mm": [3.5, 3.5],        # no height
            "clear_z_mm": [20.0, -20.0],      # inside out
            "retain_r_mm": [11.0, 9.5],       # inner radius outside the outer
        }
        for field, value in cases.items():
            with self.subTest(field=field):
                self.assertNotEqual([], _problems(**{field: value}),
                                    f"{field}={value} names an empty region, and "
                                    "an empty region measures 0.0 mm3 -- which "
                                    "reads as a part that stays clear")

    def test_a_missing_pose_is_refused_rather_than_defaulted(self) -> None:
        for pose in (_ABSENT, {}, {"centre_mm": [0.0, 0.0, 12.0]},
                     {"centre_mm": [0.0, 0.0, 12.0], "axis": [0.0, 0.0, 0.0]}):
            with self.subTest(pose=pose):
                problems = _problems(pose=pose)
                self.assertNotEqual([], problems,
                                    "the halves export in their printed pose, so "
                                    "an assembled question with no assembled "
                                    "placement is asked at the wrong place")

    def test_the_counterpart_must_be_identified_and_pinned(self) -> None:
        for field in ("counterpart", "counterpart_sha256"):
            with self.subTest(field=field):
                self.assertNotEqual([], _problems(**{field: _ABSENT}))
                self.assertNotEqual([], _problems(**{field: "  "}))

    def test_a_non_numeric_bound_is_refused(self) -> None:
        """`float("nan")` compares false against everything, so a NaN ceiling
        would make `intruded - ceiling <= tol` false forever and a NaN floor
        would make `retained >= floor` false forever -- a row that always fails
        is as uninformative as one that cannot."""
        for field in ("min_retain_mm3", "max_intrusion_mm3", "clear_r_mm"):
            for value in (float("nan"), float("inf"), "6.5", True, None):
                with self.subTest(field=field, value=value):
                    self.assertNotEqual([], _problems(**{field: value}))


class TheInstrumentRefusesAnEmptyRegionTest(unittest.TestCase):
    """The same refusal at the other end, where the zone is actually built.

    Preflight is not the only way a degenerate zone can arrive: `annulus_volume`
    is a public method and the heavy tier calls it directly. It refuses without a
    mesh and without importing the CAD stack, because the fault is in the
    declaration rather than in the part -- and because a measurement that returns
    0.0 mm3 from an empty region reads on a receipt exactly like a candidate that
    stays clear of the bearing.

    No mesh is constructed here: the guard runs before `raw` and `normalized` are
    ever touched, which is itself the thing being asserted.
    """

    def _context(self):
        from .analysis import MeshAnalysisContext

        return MeshAnalysisContext(path=None, raw=None, normalized=None,
                                   load_count=0, repair_actions=())

    def test_a_zone_with_no_volume_is_a_failure_not_a_zero(self) -> None:
        from .analysis import MeasurementFailed

        cases = {
            "inside-out radii": {"r_mm": (11.0, 9.5), "z_mm": (-3.5, 3.5)},
            "equal radii": {"r_mm": (11.0, 11.0), "z_mm": (-3.5, 3.5)},
            "no height": {"r_mm": (0.0, 11.0), "z_mm": (3.5, 3.5)},
            "inside-out height": {"r_mm": (0.0, 11.0), "z_mm": (3.5, -3.5)},
            "no axis": {"r_mm": (0.0, 11.0), "z_mm": (-3.5, 3.5),
                        "axis": (0.0, 0.0, 0.0)},
        }
        for name, kwargs in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(MeasurementFailed) as caught:
                    self._context().annulus_volume(
                        centre=(0.0, 0.0, 0.0), axis=kwargs.pop("axis", (0, 0, 1)),
                        **kwargs)
                self.assertIn("ZONE_", caught.exception.code)


class ThePreflightReachesThisRowTest(unittest.TestCase):
    """The wiring, because a validator nothing calls validates nothing.

    Asserted through `preflight` rather than by reading the source: a `kind ==`
    branch that was never added, or added under a misspelled kind, leaves every
    test above green while no contract is ever checked.
    """

    def _contract(self, expectation):
        return CT.Contract(
            job_id="j", template="authored", template_version="1",
            domain_id=None, backend="authored", parameters={},
            expected_bbox_mm={"x": 60.0, "y": 60.0, "z": 40.0},
            bbox_tolerance_mm=0.5, expected_bodies=1,
            orientation={"bed_z_mm": 0.0, "model_to_printer_matrix": "identity"},
            material={"material": "PLA", "process": "FDM"},
            nozzle={"diameter_mm": 0.4}, printer="Bambu Lab A1", modifiers=(),
            minimum_coverage=1.0, step_required=False,
            consequence="INCONSEQUENTIAL", updated_utc="2026-08-15T00:00:00Z",
            source={"kind": "authored"},
            features=(CT.Feature(
                feature_id="bearing-fit", kind="counterpart_fit",
                provenance="MEASURED", expectation=expectation,
                tolerance={"abs": 1.0}, verified_by="counterpart_fit",
                on_unrunnable="FAIL"),))

    def test_a_row_that_cannot_decide_stops_the_job_at_preflight(self) -> None:
        broken = dict(GOOD, min_retain_mm3=0.0)
        problems = CT.preflight(self._contract(broken),
                                known_checks=frozenset({"counterpart_fit"}))
        self.assertTrue(any("cannot fail" in p for p in problems),
                        f"preflight never reached the counterpart row: {problems}")

    def test_a_sound_row_passes_preflight(self) -> None:
        self.assertEqual([], CT.preflight(
            self._contract(dict(GOOD)),
            known_checks=frozenset({"counterpart_fit"})))


if __name__ == "__main__":
    unittest.main()
