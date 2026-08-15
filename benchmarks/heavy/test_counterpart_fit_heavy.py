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


if __name__ == "__main__":
    unittest.main()
