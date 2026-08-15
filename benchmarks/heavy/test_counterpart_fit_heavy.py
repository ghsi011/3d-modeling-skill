#!/usr/bin/env python3
"""Two clamps the existing gate cannot tell apart, and one check that can.

This is the regression for the blind spot a real discovery commission found. That
job passed **19 of 19 checks** on a split clamp for a 608 bearing, and every one
of the nineteen was a property of the candidate alone: bodies, watertight,
seated, envelope, four section areas, six hole diameters, two void regions,
support area, unit scale. The counterpart was never loaded and there was no
assembly pose, so nothing anywhere asked whether the bearing fits. A clamp
gripping the *inner* race -- which stops the bearing turning, the one thing the
brief forbids -- passes all nineteen.

**How the two candidates differ, and why the difference is invisible.** Both are
the same block with the same Ø21.8 seat bored through it. `SEIZED` adds one
annular lip inside that bore, reaching from the bore wall inward to r = 5.0,
which is well inside the r = 6.5 cylinder the inner ring and shaft turn in. The
lip is 1 mm thick and sits *between the declared section planes*: the contract
measures area at z = 2 and z = 28, the lip occupies z = 4.1 to 25.9 in a plane
normal to Y, and a Z-plane measurement at either declared height passes straight
over it. That is not a contrived hiding place. It is the ordinary consequence of
gating a solid on planes somebody chose in advance.

The first test is the one that matters, and it is written to fail if the slice is
pointless: it asserts that **without** the new row the two candidates receive the
*same* verdict from the existing gate. If that ever stops being true -- if some
other check grows the ability to see the lip -- this test fails and says so,
rather than leaving a check in the tree that no longer closes anything.

Heavy rather than L0 because every assertion here is a boolean between real
solids through the manifold engine, on meshes built for the test.
"""
from __future__ import annotations

import math
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "3d-modeling" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from pipeline import commission as CM          # noqa: E402
from pipeline import contract as CT            # noqa: E402
from pipeline.analysis import MeshAnalysisContext  # noqa: E402

# A 608 bearing: 22 mm outside, 8 mm bore, 7 mm wide. The clamp seat is bored
# Ø21.8, so the clamp's own material occupies r = 10.9 to 11.0 -- that ring *is*
# the interference the design rests on, and it is what `retained` measures.
BEARING_R = 11.0
SEAT_R = 10.9
BEARING_W = 7.0
# Inside this radius the inner ring and the shaft turn. A real 608's inner ring
# runs out to about r = 6; 6.5 leaves the clamp no excuse and the shaft no doubt.
FREE_R = 6.5
AXIS_Z = 15.0          # the bearing axis height above the bed
BLOCK = (40.0, 20.0, 30.0)


def _clamp(seized: bool):
    """The clamp, with or without the lip that seizes the bearing."""
    import trimesh

    body = trimesh.creation.box(extents=BLOCK)
    body.apply_translation([0.0, 0.0, BLOCK[2] / 2.0])

    def _pin(radius, height, y=0.0):
        pin = trimesh.creation.cylinder(radius=radius, height=height, sections=192)
        pin.apply_transform(trimesh.geometry.align_vectors([0, 0, 1], [0, 1, 0]))
        pin.apply_translation([0.0, y, AXIS_Z])
        return pin

    # The seat: bored right through, so the bearing can be pushed in.
    body = trimesh.boolean.difference(
        [body, _pin(SEAT_R, BLOCK[1] * 2.0)], engine="manifold")
    # Two M3 mounting holes through Z, clear of the seat.
    for x in (-16.0, 16.0):
        bolt = trimesh.creation.cylinder(radius=1.7, height=BLOCK[2] * 2.0,
                                         sections=96)
        bolt.apply_translation([x, 0.0, BLOCK[2] / 2.0])
        body = trimesh.boolean.difference([body, bolt], engine="manifold")

    if seized:
        # One annular lip inside the bore, reaching past the free radius. Union
        # rather than difference: this is material added where none may be.
        lip = trimesh.boolean.difference(
            [_pin(SEAT_R, 1.0, y=2.0), _pin(5.0, 4.0, y=2.0)], engine="manifold")
        body = trimesh.boolean.union([body, lip], engine="manifold")
    return body


def _ctx(mesh, path):
    mesh.export(path)
    return MeshAnalysisContext(path=path, raw=mesh, normalized=mesh,
                               load_count=1, repair_actions=())


def _counterpart(path: Path) -> str:
    """The bearing itself, written out and hashed, because the row names bytes."""
    import trimesh

    from pipeline import schemas as S

    ring = trimesh.boolean.difference(
        [trimesh.creation.cylinder(radius=BEARING_R, height=BEARING_W, sections=192),
         trimesh.creation.cylinder(radius=4.0, height=BEARING_W * 2, sections=192)],
        engine="manifold")
    ring.export(path)
    return S.sha256_file(path)


def _features(counterpart_name: str, digest: str, *, with_fit: bool):
    """The ordinary rows both candidates satisfy, and optionally the new one."""
    rows = [
        CT.Feature(feature_id="flange-section", kind="section_area",
                   provenance="ANALYTIC_FROM_FROZEN_PROPOSAL",
                   expectation={"at": {"z": 2.0}, "value_mm2": 800.0 - 2 * math.pi * 1.7 ** 2},
                   tolerance={"abs": 5.0}, verified_by="section_area",
                   on_unrunnable="FAIL"),
        CT.Feature(feature_id="cap-section", kind="section_area",
                   provenance="ANALYTIC_FROM_FROZEN_PROPOSAL",
                   expectation={"at": {"z": 28.0}, "value_mm2": 800.0 - 2 * math.pi * 1.7 ** 2},
                   tolerance={"abs": 5.0}, verified_by="section_area",
                   on_unrunnable="FAIL"),
    ]
    if with_fit:
        rows.append(CT.Feature(
            feature_id="bearing-fit", kind="counterpart_fit", provenance="MEASURED",
            expectation={
                "counterpart": counterpart_name, "counterpart_sha256": digest,
                # One solid, already where it belongs: this fixture is a single
                # block, so its transform is the identity. The two-half case is
                # the class at the bottom of this file.
                "bodies": [{"locator_mm": [0.0, 0.0, 1.0],
                            "transform": "identity"}],
                "pose": {"centre_mm": [0.0, 0.0, AXIS_Z], "axis": [0.0, 1.0, 0.0]},
                "retain_r_mm": [FREE_R + 1.0, BEARING_R],
                "retain_z_mm": [-BEARING_W / 2.0, BEARING_W / 2.0],
                "clear_r_mm": FREE_R,
                "clear_z_mm": [-BLOCK[1], BLOCK[1]],
                # The seat's own interference ring is pi*(11^2 - 10.9^2)*7 = 48.2
                # mm3. A floor of 30 is met by a real grip and missed by a seat
                # bored to clearance, which is the distinction the row is for.
                "min_retain_mm3": 30.0,
                "max_intrusion_mm3": 0.0,
            },
            # 1 mm3 of slack against a 192-section tessellation, whose own error
            # on these zones is about 0.02%.
            tolerance={"abs": 1.0}, verified_by="counterpart_fit",
            on_unrunnable="FAIL"))
    return tuple(rows)


def _contract(features):
    return CT.Contract(
        job_id="bearing-fit-regression", template="authored", template_version="1",
        domain_id=None, backend="authored", parameters={},
        expected_bbox_mm={"x": BLOCK[0], "y": BLOCK[1], "z": BLOCK[2]},
        bbox_tolerance_mm=0.5, expected_bodies=1,
        orientation={"bed_z_mm": 0.0, "model_to_printer_matrix": "identity"},
        material={"material": "PLA", "process": "FDM"}, nozzle={"diameter_mm": 0.4},
        printer="Bambu Lab A1", modifiers=(), minimum_coverage=1.0,
        step_required=False, consequence="INCONSEQUENTIAL",
        updated_utc="2026-08-15T00:00:00Z", source={"kind": "authored"},
        features=features)


class TheGateCannotSeeASeizedBearingTest(unittest.TestCase):
    """The blind spot itself, asserted rather than described.

    If this test fails, the new check has stopped being necessary -- which is
    worth knowing and is not the same as the check being wrong.
    """

    def test_both_clamps_pass_the_same_gate_without_the_new_row(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            digest = _counterpart(root / "bearing.stl")
            contract = _contract(_features("bearing.stl", digest, with_fit=False))
            verdicts = {}
            for name, seized in (("good", False), ("seized", True)):
                ctx = _ctx(_clamp(seized), root / f"{name}.stl")
                report = CM.run(ctx, contract, source_dir=root)
                verdicts[name] = report["verdict"]
            self.assertEqual("PASS", verdicts["good"])
            self.assertEqual(
                "PASS", verdicts["seized"],
                "a clamp whose lip reaches r=5.0 into the r=6.5 cylinder the "
                "bearing turns in passed every candidate-only check; if it no "
                "longer does, some other check has grown the ability to see it")


class TheAssembledInterfaceDecidesTest(unittest.TestCase):

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name)
        self.digest = _counterpart(self.root / "bearing.stl")
        self.contract = _contract(
            _features("bearing.stl", self.digest, with_fit=True))
        self.addCleanup(self._dir.cleanup)

    def _report(self, seized: bool, **over):
        name = "seized" if seized else "good"
        ctx = _ctx(_clamp(seized), self.root / f"{name}.stl")
        contract = self.contract
        if over:
            import dataclasses
            row = contract.features[-1]
            contract = dataclasses.replace(contract, features=(
                *contract.features[:-1],
                dataclasses.replace(row, expectation={**row.expectation, **over})))
        return CM.run(ctx, contract, source_dir=self.root)

    def _fit(self, report):
        return next(c for c in report["checks"] if c["feature_id"] == "bearing-fit")

    def test_a_clamp_that_seizes_the_bearing_fails(self) -> None:
        report = self._report(seized=True)
        row = self._fit(report)
        self.assertEqual("FAIL", row["result"], row["reason"])
        self.assertEqual("FAIL", report["verdict"])
        # pi*(6.5^2 - 5^2)*1.0 = 54.2 mm3 of the lip lies inside the free
        # cylinder. Checked against the closed form, not against what the code
        # returned, so the assertion can disagree with the implementation.
        want = math.pi * (FREE_R ** 2 - 5.0 ** 2) * 1.0
        self.assertAlmostEqual(want, row["measured"]["intruded_mm3"],
                               delta=want * 0.01)

    def test_the_same_clamp_without_the_lip_passes(self) -> None:
        report = self._report(seized=False)
        row = self._fit(report)
        self.assertEqual("PASS", row["result"], row["reason"])
        self.assertEqual("PASS", report["verdict"])
        self.assertEqual(0.0, row["measured"]["intruded_mm3"],
                         "an empty free cylinder is a measured zero")
        want = math.pi * (BEARING_R ** 2 - SEAT_R ** 2) * BEARING_W
        self.assertAlmostEqual(want, row["measured"]["retained_mm3"],
                               delta=want * 0.02)

    def test_a_clamp_that_grips_nothing_fails_the_other_way(self) -> None:
        """The retention half, which the seized clamp does not exercise.

        Raising the floor above what the seat can possibly provide stands in for
        a seat bored to clearance: the same geometry, asked for a grip it does
        not have. Without this the floor could be zero and both tests above
        would still pass.
        """
        row = self._fit(self._report(seized=False, min_retain_mm3=5000.0))
        self.assertEqual("FAIL", row["result"])
        self.assertIn("gripping", row["reason"])

    def test_a_counterpart_that_is_not_there_is_unavailable_not_a_pass(self) -> None:
        row = self._fit(self._report(seized=False, counterpart="absent.stl"))
        self.assertFalse(row["ran"])
        self.assertEqual("COUNTERPART_MISSING", row["error_code"])
        self.assertEqual("FAIL", row["result"],
                         "on_unrunnable is FAIL, and silence must not be a pass")

    def test_a_counterpart_whose_bytes_moved_is_refused(self) -> None:
        """The zones were frozen against one object; these are different bytes."""
        row = self._fit(self._report(seized=False, counterpart_sha256="f" * 64))
        self.assertFalse(row["ran"])
        self.assertEqual("COUNTERPART_CHANGED", row["error_code"])
        self.assertEqual("FAIL", row["result"])

    def test_the_pose_is_used_rather_than_assumed(self) -> None:
        """Moved to where the bearing is not, the same good clamp fails.

        This is what makes the row a question about an *assembly*: if the pose
        were ignored, or defaulted to the origin, this would still pass.
        """
        row = self._fit(self._report(
            seized=False, pose={"centre_mm": [0.0, 0.0, AXIS_Z + 40.0],
                                "axis": [0.0, 1.0, 0.0]}))
        self.assertEqual("FAIL", row["result"])
        self.assertEqual(0.0, row["measured"]["retained_mm3"])


SPLIT_Z = 14.0          # the split plane, and the bearing axis, in the printed pose
HALF = (40.0, 7.0, SPLIT_Z)
CAP_Y = 13.0            # where the cap prints, beside the body


def _half(y_centre: float):
    """One printed half: a block with the seat's lower arch taken out of its top.

    Both halves print this way -- split face up, arch below it, no support -- so
    both are *lower* halves as exported. Assembly flips one of them, which is
    exactly the transform the contract has to carry.
    """
    import trimesh

    block = trimesh.creation.box(extents=HALF)
    block.apply_translation([0.0, y_centre, HALF[2] / 2.0])
    arch = trimesh.creation.cylinder(radius=SEAT_R, height=HALF[1] * 3.0,
                                     sections=192)
    arch.apply_transform(trimesh.geometry.align_vectors([0, 0, 1], [0, 1, 0]))
    arch.apply_translation([0.0, y_centre, SPLIT_Z])
    return trimesh.boolean.difference([block, arch], engine="manifold")


# Rotate 180 degrees about X and set the cap down on the body: (x, y, z) maps to
# (x, CAP_Y - y, 2*SPLIT_Z - z). The rotation block is diag(1, -1, -1), whose
# determinant is +1 -- a proper rotation, not a reflection, which is what
# `contract.as_transform` requires and what a printed part can actually do.
CAP_TRANSFORM = [[1.0, 0.0, 0.0, 0.0],
                 [0.0, -1.0, 0.0, CAP_Y],
                 [0.0, 0.0, -1.0, 2 * SPLIT_Z],
                 [0.0, 0.0, 0.0, 1.0]]


def _split_clamp(with_cap: bool = True):
    import trimesh

    halves = [_half(0.0)] + ([_half(CAP_Y)] if with_cap else [])
    return trimesh.util.concatenate(halves)


def _split_fit_row(counterpart_name: str, digest: str, *, bodies, min_retain):
    return CT.Feature(
        feature_id="bearing-fit", kind="counterpart_fit", provenance="MEASURED",
        expectation={
            "counterpart": counterpart_name, "counterpart_sha256": digest,
            "bodies": bodies,
            "pose": {"centre_mm": [0.0, 0.0, SPLIT_Z], "axis": [0.0, 1.0, 0.0]},
            "retain_r_mm": [FREE_R + 1.0, BEARING_R],
            "retain_z_mm": [-BEARING_W / 2.0, BEARING_W / 2.0],
            "clear_r_mm": FREE_R, "clear_z_mm": [-40.0, 40.0],
            "min_retain_mm3": min_retain, "max_intrusion_mm3": 0.0,
        },
        tolerance={"abs": 1.0}, verified_by="counterpart_fit",
        on_unrunnable="FAIL")


BODY_ROW = {"locator_mm": [0.0, 0.0, 1.0], "transform": "identity"}
CAP_ROW = {"locator_mm": [0.0, CAP_Y, 1.0], "transform": CAP_TRANSFORM}
# The whole ring, so a single half cannot reach it. pi*(11^2-10.9^2)*7 = 48.16.
FULL_RING = math.pi * (BEARING_R ** 2 - SEAT_R ** 2) * BEARING_W


class TheHalvesAreAssembledBeforeTheyAreJudgedTest(unittest.TestCase):
    """The repair the reviewer sent this slice back for.

    Measured on the real commission before the repair: each half of the clamp
    retains 24.38 mm3 of the 48.16 mm3 ring, and one zone over the file as
    exported saw 24.38 -- because the cap sits 13 mm away in Y, outside a zone
    7 mm wide. A threshold set for the whole ring failed a correct part; one set
    for a half passed a part with no cap at all. Both candidates below are
    scored against a **full-ring** floor, which is only reachable once the cap
    has been put where it goes.
    """

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name)
        self.digest = _counterpart(self.root / "bearing.stl")
        self.addCleanup(self._dir.cleanup)

    def _run(self, *, with_cap=True, bodies=(BODY_ROW, CAP_ROW),
             min_retain=FULL_RING * 0.85):
        mesh = _split_clamp(with_cap=with_cap)
        ctx = _ctx(mesh, self.root / f"clamp-{with_cap}-{len(bodies)}.stl")
        contract = CT.Contract(
            job_id="split-clamp", template="authored", template_version="1",
            domain_id=None, backend="authored", parameters={},
            expected_bbox_mm={"x": HALF[0], "y": CAP_Y + HALF[1],
                              "z": HALF[2]},
            bbox_tolerance_mm=0.5, expected_bodies=2 if with_cap else 1,
            orientation={"bed_z_mm": 0.0, "model_to_printer_matrix": "identity"},
            material={"material": "PLA", "process": "FDM"},
            nozzle={"diameter_mm": 0.4}, printer="Bambu Lab A1", modifiers=(),
            minimum_coverage=1.0, step_required=False,
            consequence="INCONSEQUENTIAL", updated_utc="2026-08-15T00:00:00Z",
            source={"kind": "authored"},
            features=(_split_fit_row("bearing.stl", self.digest,
                                     bodies=list(bodies), min_retain=min_retain),))
        report = CM.run(ctx, contract, source_dir=self.root)
        return next(c for c in report["checks"] if c["feature_id"] == "bearing-fit")

    def test_the_assembled_pair_reaches_the_whole_ring(self) -> None:
        row = self._run()
        self.assertEqual("PASS", row["result"], row["reason"])
        self.assertAlmostEqual(FULL_RING, row["measured"]["retained_mm3"],
                               delta=FULL_RING * 0.03)
        self.assertEqual(0.0, row["measured"]["intruded_mm3"])

    def test_one_half_alone_falls_short_of_the_whole_ring(self) -> None:
        """The false-pass the reviewer named, shown not to happen.

        The body alone is a legitimate solid that grips half a ring. Scored
        against a whole-ring floor it fails, which is the point: the floor can
        now be set to what the assembly must achieve rather than to what one
        half can reach.
        """
        row = self._run(with_cap=False, bodies=(BODY_ROW,))
        self.assertEqual("FAIL", row["result"])
        self.assertAlmostEqual(FULL_RING / 2.0, row["measured"]["retained_mm3"],
                               delta=FULL_RING * 0.03)

    def test_a_missing_half_is_named_rather_than_measured_around(self) -> None:
        """Cap declared, cap absent: the row refuses instead of scoring the rest."""
        row = self._run(with_cap=False)
        self.assertFalse(row["ran"])
        self.assertEqual("BODY_LOCATOR_UNMATCHED", row["error_code"])
        self.assertEqual("FAIL", row["result"])

    def test_a_locator_inside_two_solids_is_refused(self) -> None:
        """A nested solid, which is what makes a locator genuinely ambiguous.

        Two rows sharing one locator is a different fault -- the contract naming
        one body twice -- and preflight catches that. This is the other one: a
        loose pin sitting inside the block's bore, so its bounding box lies
        wholly inside the block's, and a point in the pin is a point in both.
        The contract cannot say which solid it meant, so the row refuses rather
        than taking the first.
        """
        import trimesh

        block = trimesh.boolean.difference(
            [trimesh.creation.box(extents=(40.0, 20.0, 20.0)),
             trimesh.creation.cylinder(radius=8.0, height=60.0, sections=96)],
            engine="manifold")
        pin = trimesh.creation.cylinder(radius=2.0, height=6.0, sections=96)
        both = trimesh.util.concatenate([block, pin])
        ctx = MeshAnalysisContext(path=None, raw=both, normalized=both,
                                  load_count=1, repair_actions=())
        with self.assertRaises(CM._CannotAssemble) as caught:
            CM._assemble(ctx, [{"locator_mm": [0.0, 0.0, 0.0],
                                "transform": "identity"}])
        self.assertEqual("BODY_LOCATOR_AMBIGUOUS", caught.exception.code)

    def test_a_reflection_may_not_assemble_the_part(self) -> None:
        """A mirrored cap would fit a part no printer made.

        Determinant -1: `contract.as_transform` refuses it, and it is refused
        here rather than silently producing a plausible retained volume.
        """
        mirror = [row[:] for row in CAP_TRANSFORM]
        mirror[0][0] = -1.0
        row = self._run(bodies=(BODY_ROW, {"locator_mm": [0.0, CAP_Y, 1.0],
                                           "transform": mirror}))
        self.assertFalse(row["ran"])
        self.assertEqual("BODY_TRANSFORM_UNUSABLE", row["error_code"])


if __name__ == "__main__":
    unittest.main()
