#!/usr/bin/env python3
"""F1's predicates measure what they name, and the request carries no answer.

Two claims, and a fixture that lost either would still print a table.

**The predicates discriminate.** Every hard predicate here passes on a
compliant bin and fails on the specific defect it exists to catch. The
compliant bin is `tools/f1_candidate.py`, written by this benchmark; the
defects are source edits to it listed in
`benchmarks/mutations/e2e-f1-gridbin.json`, so each claim below is checked by
running the sweep and not by reading this file. The *second* state is the one
that matters: `benchmarks/heavy/test_e2e_f1_heavy.py` puts the hidden
reference -- geometry nobody here authored -- through the same predicates, and
a predicate that only ever saw geometry written to satisfy it would be a
tautology with a table.

**The request carries no answer.** Asserted at the materialised package rather
than at the manifest, for the reason `tools/test_blind.py` gives about its own:
a rule enforced on the manifest and not on its output is a rule about a file
nobody reads.

Nothing here starts a process or reads the corpus. The meshes are built and
measured in this interpreter, which is L0's rule; the halves that need a child
or the reference live in `benchmarks/heavy/test_e2e_f1_heavy.py`.
"""
from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import e2e
import f1_candidate

SPEC = e2e.fixture()
GEOMETRY = SPEC["geometry"]

# The compliant bin, built and measured once for the whole module. A mutation
# run is a fresh interpreter, so the cache cannot carry an unmutated answer
# into a mutated sweep -- and building it per test would pay the boolean five
# times for an answer that cannot differ.
_BUILT: dict[str, object] = {}


def compliant() -> dict[str, object]:
    if not _BUILT:
        mesh = f1_candidate.build()
        measured = e2e.features(mesh, GEOMETRY)
        _BUILT.update(mesh=mesh, features=measured,
                      rows={row["predicate"]: row
                            for row in e2e.predicates(measured, GEOMETRY)})
    return _BUILT


def verdict(name: str) -> bool | None:
    return compliant()["rows"][name]["passes"]           # type: ignore[index]


def _tripod():
    """A right-handed solid, for the one property the bin cannot test.

    Three arms of *different* lengths along +x, +y and +z. A proper rotation
    has to send each arm to the arm of its own length, so it would have to map
    the right-handed frame (+x, +y, +z) onto the left-handed (-x, +y, +z) that
    the mirror image carries -- which is exactly what a proper rotation cannot
    do. The bin itself is achiral (measured: the mirrored reference registers
    back at p99 = 4.4e-11 mm, recorded in the fixture's calibration block), so
    the reflection guard needs geometry that *is* handed or it is being tested
    against a shape that cannot tell the difference.
    """
    import trimesh

    arms = []
    for extents, shift in (((30.0, 4.0, 4.0), (15.0, 2.0, 2.0)),
                           ((4.0, 20.0, 4.0), (2.0, 10.0, 2.0)),
                           ((4.0, 4.0, 10.0), (2.0, 2.0, 5.0))):
        arm = trimesh.creation.box(extents=extents)
        arm.apply_translation(shift)
        arms.append(arm)
    return trimesh.boolean.union(arms, engine="manifold")


def _mirrored(mesh):
    import numpy as np

    flipped = mesh.copy()
    reflection = np.eye(4)
    reflection[0, 0] = -1.0
    flipped.apply_transform(reflection)
    flipped.fix_normals()
    return flipped


class TheHardPredicateSetIsFrozenTest(unittest.TestCase):
    """Which predicates exist is part of the contract, not an implementation
    detail. A slice that quietly dropped one would still report `CAD_PASS`."""

    FROZEN = ("one_printable_body", "watertight", "footprint_long_mm",
              "footprint_short_mm", "height_mm", "base_plug_profile_mm",
              "outer_corner_radius_mm", "compartment_floor_height_mm",
              "compartment_count", "divider_on_long_axis", "no_bores_in_base",
              "base_feet", "compartment_is_prismatic", "stack_lip_present",
              "stack_lip_depth_mm", "stack_lip_seat_height_mm")

    def test_the_predicate_names_are_the_ones_the_fixture_was_frozen_with(self) -> None:
        self.assertEqual(list(self.FROZEN), list(compliant()["rows"]))

    def test_every_row_says_what_it_measured_and_what_it_required(self) -> None:
        for name, row in compliant()["rows"].items():          # type: ignore[union-attr]
            self.assertIsInstance(row["passes"], bool, name)
            self.assertTrue(str(row["required"]).strip(), name)
            self.assertTrue(row["why"].strip(), name)


class TheCompliantBinPassesEveryHardPredicateTest(unittest.TestCase):

    def test_nothing_fails_on_a_bin_built_to_the_brief(self) -> None:
        failed = [name for name, row in compliant()["rows"].items()  # type: ignore[union-attr]
                  if not row["passes"]]
        self.assertEqual([], failed)


class TheDividerIsCountedAndPlacedTest(unittest.TestCase):
    """Probes 1 and 2: divider removed, and divider on the wrong axis."""

    def test_one_divider_reads_as_two_compartments_at_every_height(self) -> None:
        self.assertTrue(verdict("compartment_count"))
        self.assertEqual({2}, set(compliant()["features"]["compartment_ring_counts"]))

    def test_the_split_is_on_the_long_axis(self) -> None:
        self.assertTrue(verdict("divider_on_long_axis"))
        self.assertEqual("x", compliant()["features"]["split"]["axis"])

    def test_disjointness_and_not_centroids_decides_the_axis(self) -> None:
        """The gap along the split axis is positive and the other is not.

        Pinned because a centroid-difference rule gives the same answer here
        and a different one on two L-shaped cavities, and the two rules are
        indistinguishable on this fixture's own geometry.
        """
        split = compliant()["features"]["split"]
        self.assertGreater(split["gap_x_mm"], 0.0)
        self.assertLess(split["gap_y_mm"], 0.0)


class TheStackLipIsRequiredTest(unittest.TestCase):
    """Probe 3: the lip removed."""

    def test_the_opening_narrows_near_the_rim(self) -> None:
        self.assertTrue(verdict("stack_lip_present"))
        inner = compliant()["features"]["compartment_inner_box_mm"]
        top = compliant()["features"]["lip_inner_box_mm"]
        self.assertLess(min(box[0] for box in top), max(box[0] for box in inner))


class TheForbiddenFeaturesAreRefusedTest(unittest.TestCase):
    """Probes 4, 9 and 10: magnet or screw bores, a finger scoop, a label
    flange. All three are absences, and an absence is the easiest thing for a
    fixture to certify by accident."""

    def test_the_base_section_has_no_holes_in_it(self) -> None:
        self.assertTrue(verdict("no_bores_in_base"))
        self.assertEqual([0], sorted(set(compliant()["features"]["base_ring_counts"])))

    def test_the_compartment_walls_are_straight_from_floor_to_rim(self) -> None:
        self.assertTrue(verdict("compartment_is_prismatic"))
        areas = compliant()["features"]["compartment_cavity_area_mm2"]
        self.assertLessEqual((max(areas) - min(areas)) / max(areas),
                             GEOMETRY["prismatic_tolerance_fraction"])


class TheFootprintMustDropIntoTheGridTest(unittest.TestCase):
    """Probe 5: one axis scaled."""

    def test_both_footprints_are_the_published_figure(self) -> None:
        self.assertTrue(verdict("footprint_long_mm"))
        self.assertTrue(verdict("footprint_short_mm"))

    def test_a_bin_exactly_the_pitch_wide_is_refused(self) -> None:
        """The published footprint leaves a gap in the cell, so equal-to-pitch
        fails.

        Written as a direct call rather than through a mutation because the
        boundary is the whole content of the predicate: a bin the size of its
        cell does not drop into the cell.
        """
        exact = dict(compliant()["features"])                  # type: ignore[arg-type]
        exact["extents_mm"] = [84.0, 42.0, 24.8]
        rows = {row["predicate"]: row for row in e2e.predicates(exact, GEOMETRY)}
        self.assertFalse(rows["footprint_long_mm"]["passes"])
        self.assertFalse(rows["footprint_short_mm"]["passes"])


class TheHeightMustBeThreeUnitsTest(unittest.TestCase):

    def test_the_bin_is_three_height_units_plus_a_lip(self) -> None:
        self.assertTrue(verdict("height_mm"))
        self.assertGreaterEqual(compliant()["features"]["height_mm"],
                                GEOMETRY["height_units"] *
                                GEOMETRY["height_unit_mm"])

    def test_the_band_is_the_published_lip_at_both_ends(self) -> None:
        """Both ends are arithmetic on request-side numbers, and neither is a
        margin around the reference. The publication cannot fix the overall
        height -- it fixes the body and the whole lip, and the truncation
        between them is the designer's -- so the band is exactly that freedom
        and not a tolerance."""
        body = GEOMETRY["height_units"] * GEOMETRY["height_unit_mm"]
        lip = GEOMETRY["lip_profile"]
        self.assertAlmostEqual(body + lip["lower_chamfer_mm"] + lip["land_mm"],
                               GEOMETRY["height_min_mm"], places=9)
        self.assertAlmostEqual(body + lip["height_mm"],
                               GEOMETRY["height_max_mm"], places=9)


class ThePublishedBaseProfileIsHeldTest(unittest.TestCase):
    """Revision 2. The request states the foot; these rows read whether it is
    there, and they are the rows the ruling exists to create."""

    def test_the_compliant_bin_matches_the_published_profile_exactly(self) -> None:
        self.assertTrue(verdict("base_plug_profile_mm"))
        plug = compliant()["features"]["base_profile"]
        self.assertEqual(0, plug["missing_sections"])
        self.assertLessEqual(plug["worst_mm"], 0.01)

    def test_every_published_segment_is_sampled_inside_itself(self) -> None:
        """Nine samples, three per segment, and none of them on a boundary.

        Pinned because a sample taken exactly where two segments meet is a
        sample of an edge, and which side of it a tessellation lands on is a
        property of the exporter rather than of the design. If the sampling ever
        collapses onto the boundaries this passes silently and measures the one
        thing it must not.
        """
        plug = GEOMETRY["base_profile"]
        edges = {0.0, plug["lower_chamfer_mm"],
                 plug["lower_chamfer_mm"] + plug["land_mm"], plug["rise_mm"]}
        heights = [row["z_mm"] for row in
                   compliant()["features"]["base_profile"]["samples"]]
        self.assertEqual(9, len(heights))
        for z in heights:
            self.assertTrue(all(abs(z - edge) >= plug["sample_margin_mm"] - 1e-9
                                for edge in edges), z)

    def test_a_quarter_millimetre_on_the_upper_chamfer_is_refused(self) -> None:
        """The deviation the first real run actually produced, as a number.

        That candidate ran the upper chamfer 2.4 mm where the publication says
        2.15, which revision 1 could not fault because revision 1 did not state
        it. Asserted here directly as well as through the mutation, because it
        is the specific defect this revision exists to be able to see.
        """
        got = dict(compliant()["features"])                    # type: ignore[arg-type]
        got["base_profile"] = {"worst_mm": 0.25, "missing_sections": 0,
                               "samples": []}
        rows = {row["predicate"]: row for row in e2e.predicates(got, GEOMETRY)}
        self.assertFalse(rows["base_plug_profile_mm"]["passes"])

    def test_a_bin_on_one_plinth_is_refused_and_a_bin_on_two_feet_is_not(self) -> None:
        """The one published fact no span can see.

        Two feet on the pitch and one plinth spanning them have identical
        bounding boxes at every height, so `base_plug_profile_mm` and both
        footprint rows accept either. Asserted on both states rather than only
        the failing one, because a row pinned on one side is satisfied by a
        scorer that always answers that way.
        """
        self.assertTrue(verdict("base_feet"))
        self.assertEqual([2], sorted(set(
            compliant()["features"]["base_feet_counts"])))
        plinth = dict(compliant()["features"])                 # type: ignore[arg-type]
        plinth["base_feet_counts"] = [1] * len(plinth["base_feet_counts"])
        rows = {row["predicate"]: row for row in e2e.predicates(plinth, GEOMETRY)}
        self.assertFalse(rows["base_feet"]["passes"])
        self.assertTrue(rows["base_plug_profile_mm"]["passes"])
        self.assertTrue(rows["footprint_long_mm"]["passes"])


class ThePublishedInterfaceRowsCanFailTest(unittest.TestCase):
    """The other three revision-2 rows, each pinned in both states.

    Fed as measurements rather than as built geometry: each of these reads one
    number off the section stack, and the question here is whether the
    comparison against the published figure decides anything. The geometry that
    produces the number is exercised by the mutations.
    """

    def _with(self, **changes) -> dict[str, dict]:
        got = dict(compliant()["features"])                    # type: ignore[arg-type]
        got.update(changes)
        return {row["predicate"]: row for row in e2e.predicates(got, GEOMETRY)}

    def test_the_corner_radius_is_the_published_one(self) -> None:
        self.assertTrue(verdict("outer_corner_radius_mm"))
        self.assertFalse(self._with(outer_corner_radius_mm=4.0)
                         ["outer_corner_radius_mm"]["passes"])
        self.assertFalse(self._with(outer_corner_radius_mm=None)
                         ["outer_corner_radius_mm"]["passes"])

    def test_the_floor_sits_at_the_published_base_height(self) -> None:
        self.assertTrue(verdict("compartment_floor_height_mm"))
        self.assertAlmostEqual(GEOMETRY["base_height_mm"],
                               compliant()["features"]["floor_top_mm"], places=2)
        self.assertFalse(self._with(floor_top_mm=5.0)
                         ["compartment_floor_height_mm"]["passes"])
        self.assertFalse(self._with(floor_top_mm=None)
                         ["compartment_floor_height_mm"]["passes"])

    def test_the_lip_throat_is_at_the_published_depth_and_height(self) -> None:
        self.assertTrue(verdict("stack_lip_depth_mm"))
        self.assertTrue(verdict("stack_lip_seat_height_mm"))
        shallow = {"opening_mm": 79.5, "inset_from_outer_mm": 2.0,
                   "seat_top_mm": 21.0}
        low = {"opening_mm": 78.3, "inset_from_outer_mm": 2.6,
               "seat_top_mm": 19.5}
        self.assertFalse(self._with(lip_throat=shallow)
                         ["stack_lip_depth_mm"]["passes"])
        self.assertTrue(self._with(lip_throat=shallow)
                        ["stack_lip_seat_height_mm"]["passes"])
        self.assertFalse(self._with(lip_throat=low)
                         ["stack_lip_seat_height_mm"]["passes"])
        self.assertTrue(self._with(lip_throat=low)["stack_lip_depth_mm"]["passes"])
        self.assertFalse(self._with(lip_throat=None)
                         ["stack_lip_depth_mm"]["passes"])


class TheHardDistanceJudgesOnlyWhatTheRequestDeterminesTest(unittest.TestCase):
    """Revision 2's mask, and the two ways a mask goes wrong.

    A mask that removes too little judges a surface the request does not fix,
    which is the defect the ruling names. A mask that removes too much leaves a
    row that cannot fail, which reads exactly like a row that holds. Both are
    asserted.
    """

    def test_the_masked_ranges_are_arithmetic_on_request_side_numbers(self) -> None:
        mask = e2e.distance_mask(GEOMETRY)
        lip = GEOMETRY["lip_profile"]
        self.assertEqual(GEOMETRY["base_height_mm"], mask["floor_low_mm"])
        self.assertEqual(GEOMETRY["base_height_mm"] +
                         GEOMETRY["internal_fillet_allowance_mm"],
                         mask["floor_high_mm"])
        self.assertEqual(GEOMETRY["height_units"] * GEOMETRY["height_unit_mm"] +
                         lip["lower_chamfer_mm"] + lip["land_mm"],
                         mask["lip_land_top_mm"])

    def test_only_the_two_declared_ranges_are_dropped(self) -> None:
        import numpy as np

        mask = e2e.distance_mask(GEOMETRY)
        heights = np.array([0.0, 3.0, 6.9, 7.0, 8.4, 9.8, 9.9, 23.5, 23.6, 30.0])
        points = np.stack([np.zeros_like(heights), np.zeros_like(heights),
                           heights], axis=1)
        dropped = e2e.undetermined(points, mask).tolist()
        self.assertEqual([False, False, False, True, True, True, False,
                          False, True, True], dropped)

    def test_no_mask_drops_nothing(self) -> None:
        import numpy as np

        points = np.zeros((5, 3))
        self.assertFalse(e2e.undetermined(points, None).any())

    def test_a_mask_that_removes_everything_is_a_refusal_not_a_pass(self) -> None:
        import numpy as np

        points = np.stack([np.zeros(4), np.zeros(4),
                           np.array([8.0, 8.5, 9.0, 9.5])], axis=1)
        with self.assertRaises(e2e.E2EError):
            e2e.summarise(points, np.array([9.0, 9.0, 9.0, 9.0]), band_mm=0.3,
                          mask=e2e.distance_mask(GEOMETRY))

    def test_the_mask_hides_the_undetermined_range_and_nothing_else(self) -> None:
        """Two prisms that differ only above the lip's land, and again only
        below it. The first must pass and the second must fail, or the mask is
        either not applied or applied everywhere."""
        import trimesh

        mask = e2e.distance_mask(GEOMETRY)
        base = trimesh.creation.box(extents=(40.0, 20.0, 24.0))
        base.apply_translation((0.0, 0.0, 12.0))
        above = trimesh.creation.box(extents=(40.0, 20.0, 26.0))
        above.apply_translation((0.0, 0.0, 13.0))
        below = trimesh.creation.box(extents=(43.0, 20.0, 24.0))
        below.apply_translation((0.0, 0.0, 12.0))
        tall = e2e.register(above, base, samples=4000, seed=7, band_mm=0.3,
                            probe_samples=300, mask=mask)
        wide = e2e.register(below, base, samples=4000, seed=7, band_mm=0.3,
                            probe_samples=300, mask=mask)
        self.assertLess(tall["distance"]["p99_mm"], 0.3)
        self.assertGreater(tall["distance_unmasked"]["p99_mm"], 0.3)
        self.assertGreater(wide["distance"]["p99_mm"], 0.3)

    def test_the_unmasked_diagnostic_is_the_same_measurement(self) -> None:
        """One sampling pass, two summaries. Two passes would let the row and
        the diagnostic beside it disagree about the same pair of solids."""
        import trimesh

        solid = trimesh.creation.box(extents=(30.0, 20.0, 24.0))
        solid.apply_translation((0.0, 0.0, 12.0))
        found = e2e.register(solid.copy(), solid, samples=2000, seed=7,
                             band_mm=0.3, probe_samples=200,
                             mask=e2e.distance_mask(GEOMETRY))
        self.assertGreater(found["distance"]["masked_out"], 0)
        self.assertEqual(0, found["distance_unmasked"]["masked_out"])
        self.assertEqual(found["distance"]["samples"] +
                         found["distance"]["masked_out"],
                         found["distance_unmasked"]["samples"])


class TheRegistrationSeatsBothSolidsOnTheirBaseTest(unittest.TestCase):
    """The named datum, and why it is not a bounding-box centroid.

    Measured rather than argued: two solids that differ only in overall height
    are compared, and a centroid fit smears half the difference over every
    surface while the datum leaves it where it is.
    """

    def test_a_seated_solid_stands_on_z_zero_and_is_centred_on_its_footprint(self) -> None:
        import trimesh

        solid = trimesh.creation.box(extents=(10.0, 6.0, 4.0))
        solid.apply_translation((17.0, -3.0, 9.0))
        seated = e2e._seat(solid)
        self.assertAlmostEqual(0.0, float(seated.bounds[0][2]), places=9)
        self.assertAlmostEqual(0.0, float(seated.bounds[0][0] +
                                          seated.bounds[1][0]), places=9)
        self.assertAlmostEqual(0.0, float(seated.bounds[0][1] +
                                          seated.bounds[1][1]), places=9)

    def test_a_taller_solid_does_not_shift_the_surfaces_it_shares(self) -> None:
        import trimesh

        short = trimesh.creation.box(extents=(40.0, 20.0, 24.0))
        short.apply_translation((0.0, 0.0, 12.0))
        tall = trimesh.creation.box(extents=(40.0, 20.0, 25.0))
        tall.apply_translation((0.0, 0.0, 12.5))
        def centred(mesh):
            out = mesh.copy()
            out.apply_translation(-mesh.bounding_box.centroid)
            return out

        # The plane the two solids share. Under the datum it is the same plane
        # for both; under a centroid fit the taller one's is half the height
        # difference away, and every surface below it inherits that offset.
        self.assertAlmostEqual(float(e2e._seat(tall).bounds[0][2]),
                               float(e2e._seat(short).bounds[0][2]), places=9)
        self.assertAlmostEqual(0.5, abs(float(centred(tall).bounds[0][2]) -
                                        float(centred(short).bounds[0][2])),
                               places=9)


class TheStlCarriesOnePrintableBodyTest(unittest.TestCase):
    """Probe 7: an extra body inserted into the STL."""

    def test_the_compliant_bin_is_one_closed_solid(self) -> None:
        self.assertTrue(verdict("one_printable_body"))
        self.assertTrue(verdict("watertight"))

    def test_an_unclosed_surface_fails_the_watertight_row(self) -> None:
        """Fed as a measurement rather than as a mesh with a face deleted.

        `features` sections the solid, and sectioning an open surface answers
        something other than "this is not closed" -- so the row is exercised
        where it is decided, on the measurement it reads.
        """
        open_surface = dict(compliant()["features"])           # type: ignore[arg-type]
        open_surface["watertight"] = False
        rows = {row["predicate"]: row
                for row in e2e.predicates(open_surface, GEOMETRY)}
        self.assertFalse(rows["watertight"]["passes"])


class TheRegistrationCannotFitAReflectionTest(unittest.TestCase):
    """Probe 6, standing in for a handed feature this fixture does not have.

    Brief section 4: *a mirrored part must not become a PASS because a fitter
    found a reflection*, and section 12: *registration -> scale or reflect and
    prove it is rejected*. The bin is achiral, so the property that would
    matter on a handed fixture is tested on handed geometry.
    """

    def test_the_pose_set_is_the_twenty_four_proper_rotations(self) -> None:
        import numpy as np

        poses = e2e._proper_rotations()
        self.assertEqual(24, len(poses))
        for pose in poses:
            self.assertAlmostEqual(1.0, float(np.linalg.det(pose)), places=9)

    def test_a_mirrored_handed_solid_is_not_registered_into_agreement(self) -> None:
        solid = _tripod()
        found = e2e.register(_mirrored(solid), solid, samples=600, seed=7,
                             band_mm=0.3, probe_samples=200)
        self.assertEqual(1.0, found["determinant"])
        self.assertGreater(found["distance"]["p99_mm"], 1.0)

    def test_the_same_solid_unmirrored_registers_onto_itself(self) -> None:
        """The other half of the two states, so the case above is a discovery
        about handedness rather than about the tripod being hard to fit."""
        solid = _tripod()
        found = e2e.register(solid.copy(), solid, samples=600, seed=7,
                             band_mm=0.3, probe_samples=200)
        self.assertLess(found["distance"]["p99_mm"], 1e-6)


class TheSurfaceDistanceIsBidirectionalTest(unittest.TestCase):

    def test_a_protrusion_is_found_from_the_side_that_has_it(self) -> None:
        """One-way nearest neighbour is blind here and both ways are not.

        Every point of the plain box has a near neighbour on the box with a
        spike, so A->B stays at zero however wrong B is. Measured on this pair
        rather than argued: that is why `surface_distance` concatenates.
        """
        import trimesh

        box = trimesh.creation.box(extents=(20.0, 20.0, 20.0))
        spike = trimesh.creation.box(extents=(3.0, 3.0, 12.0))
        spike.apply_translation((0.0, 0.0, 14.0))
        lumpy = trimesh.boolean.union([box, spike], engine="manifold")
        found = e2e.surface_distance(box, lumpy, samples=1200, seed=7,
                                     band_mm=0.3)
        self.assertGreater(found["max_mm"], 3.0)


class TheReferenceComparisonCanFailTest(unittest.TestCase):

    def test_geometry_that_does_not_match_fails_the_distance_row(self) -> None:
        solid = _tripod()
        found = e2e.register(_mirrored(solid), solid, samples=600, seed=7,
                             band_mm=0.3, probe_samples=200)
        rows = {row["predicate"]: row
                for row in e2e.comparison_rows(found, GEOMETRY)}
        self.assertTrue(rows["registration_is_a_proper_rotation"]["passes"])
        self.assertFalse(rows["reference_surface_distance_p99_mm"]["passes"])

    def test_geometry_that_matches_passes_it(self) -> None:
        solid = _tripod()
        found = e2e.register(solid.copy(), solid, samples=600, seed=7,
                             band_mm=0.3, probe_samples=200)
        rows = {row["predicate"]: row
                for row in e2e.comparison_rows(found, GEOMETRY)}
        self.assertTrue(rows["reference_surface_distance_p99_mm"]["passes"])


class TheRequestPackageCarriesNoAnswerTest(unittest.TestCase):
    """The requester-side prohibition, enforced on the bytes a designer gets.

    It covers derived measurements and not only the reference mesh, which is
    the lesson the bee fixture paid for: there, the designer voluntarily
    avoided the measurement scripts, and a harness that depends on that is
    measuring the designer's manners.
    """

    MEASURED = {"extent_x": 83.5, "extent_y": 41.5, "extent_z": 24.8,
                "volume_mm3": 27927.366}

    def _written(self, root: Path) -> Path:
        return e2e.write_request(SPEC, root)

    def test_the_written_request_states_nothing_undeclared(self) -> None:
        """Two axes cross now and both are declared; the third does not cross.

        Revision 2 states the published footprint, so the request necessarily
        states two of the reference's three extents -- which is the ruling
        carried out rather than a hole in the wall. The overall height is the
        one extent the publication does not fix, and it is the one that has to
        stay out.
        """
        with tempfile.TemporaryDirectory() as raw:
            where = self._written(Path(raw))
            audit = e2e.audit_request(SPEC, where, self.MEASURED)
        self.assertEqual(["extent_x", "extent_y"], audit["declared"])
        self.assertEqual([["42", "extent_y"], ["41.5", "extent_y"],
                          ["83.5", "extent_x"]],
                         [[f"{value:g}", name]
                          for value, name in audit["coincidences"]])

    def test_a_planted_measurement_is_a_hard_failure(self) -> None:
        """Planted on the axis revision 2 does NOT disclose.

        It used to plant the overall length, which revision 2 legitimately
        states. Moving the plant to the height keeps this measuring the guard
        rather than the disclosure: the overall height is a design decision
        inside a published band, so a request that stated it would be handing
        over the answer.
        """
        with tempfile.TemporaryDirectory() as raw:
            where = self._written(Path(raw))
            brief = where / "brief.md"
            brief.write_text(brief.read_text(encoding="utf-8") +
                             "\n* overall height: 24.8 mm\n", encoding="utf-8")
            with self.assertRaises(e2e.RequestLeak) as caught:
                e2e.audit_request(SPEC, where, self.MEASURED)
        self.assertIn("extent_z", str(caught.exception))

    def test_the_written_request_is_a_project_design_tool_can_be_run_from(self) -> None:
        from pipeline import project as P

        with tempfile.TemporaryDirectory() as raw:
            where = self._written(Path(raw))
            loaded = P.load(where)
            self.assertEqual([], [issue for issue in loaded.validate()])
            self.assertEqual({"x", "y", "z"}, set(loaded.envelope_mm))
            self.assertTrue((where / "brief.md").is_file())


class TheReferenceIsProvenOnEveryCallTest(unittest.TestCase):

    def _spec(self, root: Path, digest: str) -> dict:
        spec = json.loads(json.dumps(SPEC))
        spec["reference"] = {**spec["reference"], "sha256": digest,
                             "path": "ref.stl",
                             "root": {"env": "E2E_TEST_ROOT_UNSET",
                                      "default": str(root)}}
        return spec

    def test_a_drifted_reference_is_refused_and_not_scored(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "ref.stl").write_bytes(b"solid x\nendsolid x\n")
            with self.assertRaises(e2e.ReferenceCorrupt):
                e2e.reference_path(self._spec(root, "0" * 64))

    def test_a_missing_reference_says_how_it_is_made(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(e2e.ReferenceUnavailable) as caught:
                e2e.reference_path(self._spec(Path(raw), "0" * 64))
        self.assertIn("cqgridfinity", str(caught.exception))


class TheThreeMfGateCountsPlacedBodiesTest(unittest.TestCase):
    """Probe 8: an extra body inserted into the 3MF while the STL stays right.

    The archive is written here rather than by `make_3mf.py`, because an L0
    test may not start a child interpreter. The real writer's output goes
    through the same reader in `benchmarks/heavy/test_e2e_f1_heavy.py`, so the
    format this test assumes is checked against the one the repository emits.
    """

    NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"

    def _archive(self, path: Path, meshes, components,
                 unit: str = "millimeter") -> Path:
        objects = []
        for index, mesh in enumerate(meshes, start=1):
            vertices = "".join(f'<vertex x="{x:.6g}" y="{y:.6g}" z="{z:.6g}"/>'
                               for x, y, z in mesh.vertices)
            faces = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>'
                            for a, b, c in mesh.faces)
            objects.append(f'<object id="{index}" type="model"><mesh>'
                           f'<vertices>{vertices}</vertices>'
                           f'<triangles>{faces}</triangles></mesh></object>')
        assembly = len(meshes) + 1
        parts = "".join(f'<component objectid="{i}"/>' for i in components)
        model = (f'<?xml version="1.0" encoding="UTF-8"?>'
                 f'<model unit="{unit}" xmlns="{self.NS}"><resources>'
                 f'{"".join(objects)}<object id="{assembly}" type="model">'
                 f'<components>{parts}</components></object></resources>'
                 f'<build><item objectid="{assembly}"/></build></model>')
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("3D/3dmodel.model", model)
        return path

    def test_one_placed_body_passes_and_two_do_not(self) -> None:
        import trimesh

        body = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
        stray = trimesh.creation.box(extents=(2.0, 2.0, 2.0))
        stray.apply_translation((0.0, 0.0, 30.0))
        with tempfile.TemporaryDirectory() as raw:
            good = self._archive(Path(raw) / "one.3mf", [body], [1])
            bad = self._archive(Path(raw) / "two.3mf", [body, stray], [1, 2])
            ok = {row["predicate"]: row
                  for row in e2e.three_mf_rows(good, body, GEOMETRY)}
            extra = {row["predicate"]: row
                     for row in e2e.three_mf_rows(bad, body, GEOMETRY)}
        self.assertTrue(ok["three_mf_printable_body_count"]["passes"])
        self.assertTrue(ok["three_mf_unit_is_millimetre"]["passes"])
        self.assertTrue(ok["three_mf_matches_the_accepted_stl"]["passes"])
        self.assertFalse(extra["three_mf_printable_body_count"]["passes"])

    def test_a_stale_body_fails_the_geometry_row(self) -> None:
        import trimesh

        body = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
        stale = trimesh.creation.box(extents=(10.0, 10.0, 12.0))
        with tempfile.TemporaryDirectory() as raw:
            path = self._archive(Path(raw) / "stale.3mf", [stale], [1])
            rows = {row["predicate"]: row
                    for row in e2e.three_mf_rows(path, body, GEOMETRY)}
        self.assertTrue(rows["three_mf_printable_body_count"]["passes"])
        self.assertFalse(rows["three_mf_matches_the_accepted_stl"]["passes"])

    def test_a_micron_unit_is_refused(self) -> None:
        """3MF's default unit is the micron, so a wrong one is a thousandfold
        scale error that every geometry row would report as a shape error."""
        import trimesh

        body = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
        with tempfile.TemporaryDirectory() as raw:
            path = self._archive(Path(raw) / "micron.3mf", [body], [1],
                                 unit="micron")
            rows = {row["predicate"]: row
                    for row in e2e.three_mf_rows(path, body, GEOMETRY)}
        self.assertFalse(rows["three_mf_unit_is_millimetre"]["passes"])

    def test_a_file_that_is_not_an_archive_is_reported_unreadable(self) -> None:
        """A refusal, not a traceback: an unreadable deliverable is a finding
        the report has to carry, and an exception out of the gate is a run with
        no report at all."""
        import trimesh

        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "broken.3mf"
            path.write_bytes(b"this is not a zip archive")
            rows = {row["predicate"]: row for row in e2e.three_mf_rows(
                path, trimesh.creation.box(extents=(1.0, 1.0, 1.0)), GEOMETRY)}
        self.assertFalse(rows["three_mf_readable"]["passes"])

    def test_a_missing_three_mf_is_a_named_failure_and_not_a_skip(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            rows = e2e.three_mf_rows(Path(raw) / "absent.3mf", None, GEOMETRY)
        self.assertFalse(rows[0]["passes"])
        self.assertEqual("three_mf_present", rows[0]["predicate"])

    def test_the_reason_this_reader_exists_is_still_true(self) -> None:
        """`docs/defects.md` D3, asserted against `pyproject.toml`.

        `trimesh`'s 3MF loader needs `lxml`, which this project declares only in
        the `bambu` extra -- so a runtime-only install cannot read back the 3MF
        `make_3mf.py` just wrote, and the writer's own round-trip check prints
        *round-trip verification skipped* and exits 0.

        Asserted against the **declared dependency set** and not by trying to
        import `lxml`. The first version of this did import it, and it was a
        trap: CI installs core plus every extra, so `lxml` is present there
        without being core, and the test would have failed for a reason it does
        not name. Provenance is not sufficiency -- an importable module answers
        *is it here on this machine*, and the claim is *is it here on a default
        install*.

        When `lxml` becomes a core dependency this fails, and the signal is to
        delete the reader's justification -- not the reader, whose stricter walk
        through build items and components is worth keeping either way.
        """
        import tomllib

        payload = tomllib.loads(
            (Path(e2e.ROOT) / "pyproject.toml").read_text(encoding="utf-8"))
        core = " ".join(payload["project"]["dependencies"])
        extras = payload["project"]["optional-dependencies"]
        self.assertNotIn("lxml", core)
        self.assertIn("lxml", " ".join(extras["bambu"]))


class TheReportBindsTheScorerItWasProducedByTest(unittest.TestCase):
    """Brief section 10: the report binds the scorer's version.

    Not covered by a mutation, because the property that matters is a refusal
    and refusals are what the two states below check directly: a clean tree
    yields a commit, and a dirty one yields `None` rather than a commit id that
    would claim to name code which is not what ran.
    """

    def test_a_dirty_tree_yields_no_commit_rather_than_the_wrong_one(self) -> None:
        from unittest import mock

        class Done:
            def __init__(self, out: str) -> None:
                self.returncode, self.stdout = 0, out

        with mock.patch("subprocess.run",
                        side_effect=[Done("abc123\n"), Done(" M tools/e2e.py\n")]):
            self.assertIsNone(e2e.scorer_commit())

    def test_a_clean_tree_yields_the_head_commit(self) -> None:
        from unittest import mock

        class Done:
            def __init__(self, out: str) -> None:
                self.returncode, self.stdout = 0, out

        with mock.patch("subprocess.run",
                        side_effect=[Done("abc123\n"), Done("\n")]):
            self.assertEqual("abc123", e2e.scorer_commit())


class TheFixtureHalvesAgreeTest(unittest.TestCase):
    """The brief and the predicates state the same request in two languages.

    `AGENTS.md`'s synchronisation rule reaches inside one file: a corrected
    interface was once updated in the table that declared it while the
    acceptance criterion testing that interface still named the superseded one.
    Here the brief is prose and `geometry` is numbers, and nothing else stops
    them drifting apart.
    """

    def test_the_brief_states_the_pitch_the_predicates_apply(self) -> None:
        brief = "\n".join(SPEC["request"]["brief"])
        self.assertIn(f"{GEOMETRY['grid_pitch_mm']:g} mm in both X and Y", brief)
        self.assertIn(f"{GEOMETRY['height_unit_mm']:g} mm", brief)

    def test_the_requirements_state_the_same_footprint_and_height(self) -> None:
        rows = {row["name"]: row["value"]
                for row in SPEC["request"]["project"]["requirements"]}
        self.assertEqual(GEOMETRY["footprint_units"],
                         [rows["grid_units_long"], rows["grid_units_short"]])
        self.assertEqual(GEOMETRY["height_units"], rows["height_units"])
        self.assertEqual(GEOMETRY["grid_pitch_mm"], rows["grid_pitch_mm"])

    def test_every_published_figure_a_predicate_applies_is_in_the_brief(self) -> None:
        """The revision-2 condition, enforced instead of promised.

        The ruling allows a hard reference-distance predicate only where
        request-side facts determine the surface, and the same goes for the
        named rows: `base_plug_profile_mm` against a figure the brief does not
        state would be revision 1 again under a new name. So every number the
        predicates read out of `geometry` has to be findable in the prose a
        designer is handed, and the halves cannot drift apart quietly.
        """
        brief = "\n".join(SPEC["request"]["brief"])
        plug, lip = GEOMETRY["base_profile"], GEOMETRY["lip_profile"]
        for label, value in (
                ("grid pitch", GEOMETRY["grid_pitch_mm"]),
                ("widest section per unit", GEOMETRY["unit_widest_mm"]),
                ("gap between units", GEOMETRY["grid_gap_mm"]),
                ("height unit", GEOMETRY["height_unit_mm"]),
                ("corner radius", GEOMETRY["outer_corner_radius_mm"]),
                ("base lower chamfer", plug["lower_chamfer_mm"]),
                ("base land", plug["land_mm"]),
                ("base upper chamfer", plug["upper_chamfer_mm"]),
                ("base rise", plug["rise_mm"]),
                ("base run", plug["run_mm"]),
                ("base height", GEOMETRY["base_height_mm"]),
                ("lip lower chamfer", lip["lower_chamfer_mm"]),
                ("lip land", lip["land_mm"]),
                ("lip upper chamfer", lip["upper_chamfer_mm"]),
                ("lip depth", lip["depth_mm"]),
                ("lip height", lip["height_mm"]),
                ("lip support", lip["support_height_mm"]),
                ("stated tolerance", GEOMETRY["published_tolerance_mm"])):
            self.assertIn(f"{value:g} mm", brief, label)

    def test_the_brief_cites_the_sources_the_fixture_records(self) -> None:
        """Provenance on the request side, which is what the ruling asked for.

        A figure stated without a source is an assertion a designer has to take
        on trust and a reviewer cannot check, and this repository's most common
        defect is a citation nobody opened.
        """
        brief = "\n".join(SPEC["request"]["brief"])
        published = SPEC["published_interface"]
        for block in ("primary", "corroborating"):
            url = published[block]["url"]
            self.assertIn(url.split("/blob/")[0], brief, block)
        self.assertIn(published["primary_source_checked_and_insufficient"]["url"],
                      brief)

    def test_the_declared_disclosure_names_a_requirement_that_exists(self) -> None:
        names = {row["name"] for row in SPEC["request"]["project"]["requirements"]}
        for row in SPEC["request"]["discloses"]:
            self.assertIn(row["requirement"], names)
            self.assertTrue(row["why"].strip())

    def test_the_calibration_band_is_the_one_the_geometry_block_applies(self) -> None:
        """A band recorded in one place and applied from another is two bands."""
        selected = SPEC["calibration"]["selected"]
        self.assertEqual(GEOMETRY["reference_comparison"]["band_mm"],
                         selected["reference_band_mm"])
        self.assertEqual(GEOMETRY["three_mf"]["band_mm"],
                         selected["three_mf_band_mm"])

    def test_the_band_is_above_the_measured_same_geometry_noise(self) -> None:
        """The calibration rule, enforced rather than described.

        Brief section 5: select a threshold with an explicit safety margin
        above measured transport noise. If someone tightens the band below what
        the same geometry already moves, every correct candidate fails and the
        fixture reports the reference as wrong.
        """
        measured = SPEC["calibration"]["measurements"]
        self.assertGreater(GEOMETRY["reference_comparison"]["band_mm"],
                           measured["scored_vs_coarse_p99_mm"])
        self.assertGreater(GEOMETRY["three_mf"]["band_mm"],
                           measured["three_mf_roundtrip_p99_mm"])


if __name__ == "__main__":
    unittest.main()
