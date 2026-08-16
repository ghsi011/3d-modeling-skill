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
              "footprint_short_mm", "height_mm", "compartment_count",
              "divider_on_long_axis", "no_bores_in_base",
              "compartment_is_prismatic", "stack_lip_present")

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

    def test_both_footprints_are_undersize_by_a_working_amount(self) -> None:
        self.assertTrue(verdict("footprint_long_mm"))
        self.assertTrue(verdict("footprint_short_mm"))

    def test_a_bin_exactly_the_pitch_wide_is_refused(self) -> None:
        """The band is on the *undersize*, so equal-to-pitch fails.

        Written as a direct call rather than through a mutation because the
        boundary is the whole content of the predicate: a bin the size of its
        cell does not drop into the cell.
        """
        exact = dict(compliant()["features"])                  # type: ignore[arg-type]
        exact["extents_mm"] = [84.0, 41.5, 24.8]
        rows = {row["predicate"]: row for row in e2e.predicates(exact, GEOMETRY)}
        self.assertFalse(rows["footprint_long_mm"]["passes"])


class TheHeightMustBeThreeUnitsTest(unittest.TestCase):

    def test_the_bin_is_three_height_units_plus_a_base_allowance(self) -> None:
        self.assertTrue(verdict("height_mm"))
        self.assertGreaterEqual(compliant()["features"]["height_mm"],
                                GEOMETRY["height_units"] *
                                GEOMETRY["height_unit_mm"])


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
        with tempfile.TemporaryDirectory() as raw:
            where = self._written(Path(raw))
            audit = e2e.audit_request(SPEC, where, self.MEASURED)
        self.assertEqual(["extent_y"], audit["declared"])
        self.assertEqual([["42", "extent_y"]],
                         [[f"{value:g}", name]
                          for value, name in audit["coincidences"]])

    def test_a_planted_measurement_is_a_hard_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            where = self._written(Path(raw))
            brief = where / "brief.md"
            brief.write_text(brief.read_text(encoding="utf-8") +
                             "\n* overall length: 83.5 mm\n", encoding="utf-8")
            with self.assertRaises(e2e.RequestLeak) as caught:
                e2e.audit_request(SPEC, where, self.MEASURED)
        self.assertIn("extent_x", str(caught.exception))

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
