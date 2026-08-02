#!/usr/bin/env python3
"""L0-heavy — the half of
`skills/3d-modeling/scripts/pipeline/test_phase3.py`
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
import unittest
from pathlib import Path
import numpy as np
import trimesh
from pipeline import cli
from pipeline import commission as CM
from pipeline import preservation as PR
from pipeline import project as P
from pipeline import review as R
from pipeline import schemas as S

# The fixtures this half shares with the half that stayed behind,
# imported rather than copied: two spellings of one fixture is how
# two tiers stop testing the same thing.
from pipeline.test_phase3 import (  # noqa: E402
    BALL_D,
    MODIFIER,
    REDRAWN,
    REDRAWN_PROPOSAL,
    RIGHT_BOX,
    VENT_MOUNT_BOSS,
    _edit_scope,
    _laid_out,
    _modify_project,
    _store_passing_answer,
    _two_scopes_laid_out,
    _vent_mount,
)


class PreservationTest(unittest.TestCase):
    def test_an_edit_inside_its_region_preserves_everything_outside(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source_path = root / "bracket.stl"
            source = _vent_mount()
            source.export(source_path)

            ball = trimesh.creation.icosphere(radius=BALL_D / 2.0, subdivisions=3)
            ball.apply_translation((*VENT_MOUNT_BOSS, 20.0))
            edited = trimesh.boolean.difference([source, ball], engine="manifold")
            candidate_path = root / "candidate.stl"
            edited.export(candidate_path)

            region = PR.Region.from_declaration(_edit_scope().region_box)
            report = PR.audit(source_path=source_path,
                              candidate_path=candidate_path, region=region)
            self.assertEqual("PRESERVED_WITHIN_TOLERANCE", report["verdict"])
            self.assertIn("sampled", report["method"])
            self.assertIn("cannot establish exact preservation",
                          report["claim_note"])

    def test_a_redraw_that_moved_the_plate_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source_path = root / "bracket.stl"
            _vent_mount().export(source_path)

            thicker = trimesh.creation.box(extents=(50.0, 30.0, 8.6))
            thicker.apply_translation((25.0, 15.0, 4.3))
            candidate_path = root / "candidate.stl"
            thicker.export(candidate_path)

            region = PR.Region.from_declaration(_edit_scope().region_box)
            report = PR.audit(source_path=source_path,
                              candidate_path=candidate_path, region=region)
            self.assertEqual("CHANGED", report["verdict"])
            self.assertGreater(report["max_deviation_mm"], 0.05)
            self.assertIsNotNone(report["worst_point_mm"])

    def test_without_a_region_the_audit_says_unmeasurable_rather_than_passing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / "bracket.stl"
            _vent_mount().export(path)
            report = PR.audit(source_path=path, candidate_path=path, region=None)
            self.assertEqual("UNMEASURABLE", report["verdict"])
            self.assertIn("no region box", report["reason"])

    def test_exact_is_a_claim_about_the_inputs_not_about_the_extension(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / "bracket.stl"
            _vent_mount().export(path)
            region = PR.Region.from_declaration(_edit_scope().region_box)
            sampled = PR.audit(source_path=path, candidate_path=path, region=region)
            declared = PR.audit(source_path=path, candidate_path=path,
                                region=region, exact=True)
            self.assertEqual("PRESERVED_WITHIN_TOLERANCE", sampled["verdict"])
            self.assertEqual("PRESERVED_EXACTLY", declared["verdict"])
            self.assertEqual(sampled["method"], declared["method"],
                             "the measurement is the same; what `exact` buys is "
                             "the right to read it as a statement about geometry")

class StepSourceTest(unittest.TestCase):
    """D13. A STEP source produces a preservation verdict, not an import error.

    `preservation.audit` handed every path to `trimesh.load`, which dispatches
    STEP to `cascadio` -- not in this runtime -- so any MODIFY or COMBINE whose
    base was a STEP came back `UNMEASURABLE: ModuleNotFoundError: cascadio`. That
    is most CAD anybody supplies, and it is the repository's only
    `PHYSICALLY_PROVEN` fixture's primary source.

    The build is done here with `build123d` rather than with a checked-in STEP so
    that the test asserts the reading path end to end -- kernel import,
    tessellation, canonical ordering, sampling -- on a file this test wrote.
    """

    def _sound_step(self, root: Path) -> tuple[Path, Path]:
        from build123d import Box, Cylinder, Location, export_step, export_stl

        source_path = root / "plate.step"
        block = Box(40.0, 30.0, 10.0)
        export_step(block, str(source_path))

        candidate_path = root / "candidate.stl"
        pocket = Cylinder(radius=4.0, height=8.0).moved(Location((0.0, 0.0, 3.0)))
        export_stl(block - pocket, str(candidate_path),
                   tolerance=0.01, angular_tolerance=0.1)
        return source_path, candidate_path

    def _region(self) -> PR.Region:
        return PR.Region((-6.0, -6.0, -2.0), (6.0, 6.0, 6.0), 0.5)

    def test_a_step_source_is_measured_rather_than_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source_path, candidate_path = self._sound_step(Path(raw))
            report = PR.audit(source_path=source_path,
                              candidate_path=candidate_path, region=self._region())
            self.assertIn(report["verdict"],
                          ("PRESERVED_WITHIN_TOLERANCE", "CHANGED"),
                          f"a readable STEP must reach a measurement: "
                          f"{report.get('reason')}")
            self.assertGreater(report["samples_outside_region"], 0)
            self.assertNotIn("cascadio", json.dumps(report))

    def test_the_report_says_how_the_brep_was_read(self) -> None:
        """A tessellation is a measurement parameter; a parse is not.

        Two deflections give two different meshes of one solid and therefore two
        different distances, so the deflection travels on the evidence -- and only
        for the side that actually had to be tessellated, because a key that
        appeared on every report to announce that nothing happened would move
        every evidence digest ever taken.
        """
        with tempfile.TemporaryDirectory() as raw:
            source_path, candidate_path = self._sound_step(Path(raw))
            report = PR.audit(source_path=source_path,
                              candidate_path=candidate_path, region=self._region())
            reading = report["tessellation"]["source"]
            self.assertNotIn("candidate", report["tessellation"],
                             "the candidate is an STL; reading it is a parse")
            self.assertEqual(6, reading["faces"])
            self.assertEqual(6, reading["tessellated_faces"])
            self.assertEqual(0, reading["untessellatable_faces"])
            self.assertEqual(0.01, reading["linear_deflection"])

    def test_a_step_no_mesher_can_read_is_named_rather_than_measured(self) -> None:
        """Fail closed on the file `diagnose` now calls `REPAIR_REQUIRED`.

        Dropping the faces OCC cannot triangulate would leave an open surface,
        and `signed_distance` against an open surface reports a distance to
        geometry that is missing rather than to geometry that moved. The audit
        refuses and names the faces.
        """
        import mesh_io

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source_path, candidate_path = self._sound_step(root)
            broken = root / "broken.step"
            broken.write_bytes(source_path.read_bytes())

            def unreadable(path, **kwargs):
                _ = kwargs
                if Path(path).name == "broken.step":
                    return mesh_io.BrepTessellation(
                        faces=329, tessellated=323,
                        failures=("face 93 (GeomType.CONE): null triangulation",),
                        linear_deflection=0.01, angular_deflection=0.1)
                return original(path, **kwargs)

            original = mesh_io.read_step
            mesh_io.read_step = unreadable
            try:
                report = PR.audit(source_path=broken,
                                  candidate_path=candidate_path,
                                  region=self._region())
            finally:
                mesh_io.read_step = original

            self.assertEqual("UNMEASURABLE", report["verdict"])
            self.assertIn("BrepUnreadable", report["reason"])
            self.assertIn("face 93", report["reason"])
            self.assertIn("CONE", report["reason"])

class MemoryCeilingTest(unittest.TestCase):
    """D19. The audit refuses before allocating rather than racing the allocator.

    Measured on the vent-ball pair: 22.4 GB peak working set, 39.74 GB page file,
    free RAM at 0-1.5 GB throughout, and **one of eleven identical invocations**
    died with `MemoryError: Unable to allocate 1.57 GiB for an array with shape
    (210081703,)`. It failed controllably and the retry succeeded, which is
    precisely the problem: the same unchanged job produced two different outcomes,
    and Release 1 exists so that an unchanged job can be rerun and resumed.

    The 210 million is not a mystery. `trimesh.proximity.nearby_faces` uses the
    distance to the nearest *vertex* as its query radius, so a sample 60 mm from a
    20 mm part asks the r-tree for everything inside a 60 mm box: measured on that
    pair, all 7,056 faces came back for all 20,000 points in one direction, and a
    mean of 16,583 of 19,522 in the other.
    """

    def _pair(self, root: Path) -> tuple[Path, Path]:
        source_path = root / "bracket.stl"
        source = _vent_mount()
        source.export(source_path)
        ball = trimesh.creation.icosphere(radius=BALL_D / 2.0, subdivisions=3)
        ball.apply_translation((*VENT_MOUNT_BOSS, 20.0))
        candidate_path = root / "candidate.stl"
        trimesh.boolean.difference([source, ball], engine="manifold").export(
            candidate_path)
        return source_path, candidate_path

    def test_a_ceiling_below_one_query_point_refuses_before_allocating(self) -> None:
        """The property is a refusal, not a survived allocation.

        A ceiling that only ever *bounds* is untestable in the way that matters:
        the assertion would be about a peak nobody can observe from inside the
        process. This declares a ceiling that one point against this target cannot
        fit and asserts the verdict, the arithmetic, and that nothing was
        allocated.
        """
        with tempfile.TemporaryDirectory() as raw:
            source_path, candidate_path = self._pair(Path(raw))
            region = PR.Region.from_declaration(_edit_scope().region_box)
            report = PR.audit(source_path=source_path,
                              candidate_path=candidate_path, region=region,
                              memory_ceiling_bytes=1024)
            self.assertEqual("UNMEASURABLE", report["verdict"])
            self.assertIn("MemoryCeilingExceeded", report["reason"])
            self.assertIn("1024", report["reason"])
            self.assertIn("nothing has been allocated", report["reason"])
            self.assertNotIn("max_deviation_mm", report,
                             "a refusal must not carry half a measurement")
            self.assertNotIn("directions", report)

    def test_the_refusal_is_taken_before_either_direction_runs(self) -> None:
        """Both batch sizes are settled first.

        A ceiling checked per direction would let the first direction run, write
        its numbers, and then refuse -- a partial answer with a verdict attached,
        which is worse than no answer.
        """
        with self.assertRaises(PR.MemoryCeilingExceeded) as caught:
            PR._query_batch(50_000, 1024)
        self.assertIn("50000", str(caught.exception))

    def test_the_ceiling_bounds_the_batch_without_moving_the_evidence(self) -> None:
        """The whole claim: bounded memory, byte-identical answer.

        `closest_point` computes every query point independently -- the candidate
        lookup, the per-row triangle distance and the two-best tie-break are all
        per point -- so splitting the query changes the peak and not one float.
        If this ever fails, the batching has stopped being exact and the fix is
        not to re-pin the evidence.
        """
        with tempfile.TemporaryDirectory() as raw:
            source_path, candidate_path = self._pair(Path(raw))
            region = PR.Region.from_declaration(_edit_scope().region_box)
            unbounded = PR.audit(source_path=source_path,
                                 candidate_path=candidate_path, region=region,
                                 memory_ceiling_bytes=PR.DEFAULT_MEMORY_CEILING_BYTES)
            # Small enough to force many batches on a target of this size, and
            # large enough that one point still fits.
            bounded = PR.audit(source_path=source_path,
                               candidate_path=candidate_path, region=region,
                               memory_ceiling_bytes=8 * 1024 * 1024)
            self.assertEqual("PRESERVED_WITHIN_TOLERANCE", unbounded["verdict"])
            self.assertEqual(S.canonical_json(unbounded), S.canonical_json(bounded))

    def test_the_batch_is_derived_from_the_declared_ceiling(self) -> None:
        """Halve the budget, halve the batch. The ceiling is the input, not a hint."""
        faces = 10_000
        big = PR._query_batch(faces, 64 * 1024 * 1024)
        small = PR._query_batch(faces, 32 * 1024 * 1024)
        # Floor division, so the halved budget gives the halved batch to within
        # the one point the truncation costs.
        self.assertIn(big - 2 * small, (0, 1), f"{big} against 2 x {small}")
        for batch, budget in ((big, 64 * 1024 * 1024), (small, 32 * 1024 * 1024)):
            self.assertLessEqual(
                batch * faces * PR.WORKING_BYTES_PER_CANDIDATE, budget,
                "the worst case a batch can reach has to fit the budget it "
                "came from")

    def test_the_default_ceiling_is_declared_rather_than_discovered(self) -> None:
        """ARCHITECTURE section 12 wants an explicit limit, not the machine's.

        A limit read off whatever happened to be free would reproduce exactly the
        run-to-run variability this exists to remove.
        """
        self.assertEqual(2 * 1024 ** 3, PR.DEFAULT_MEMORY_CEILING_BYTES)
        self.assertGreater(PR.WORKING_BYTES_PER_CANDIDATE, 350,
                           "the declared per-candidate cost must not sit below "
                           "the 350.1-350.3 bytes measured on the vent-ball pair")

class DeterministicEvidenceTest(unittest.TestCase):
    """The audit is a function of the pair it compares, and of nothing else.

    Before this, `sample_surface` drew from the process-wide generator, so
    `samples_outside_region` alone moved by hundreds between two runs of one
    unchanged pair. That is not a cosmetic wobble: the commission report is
    inside the review packet, the packet hash is inside the review envelope, and
    an evidence packet that cannot be reproduced cannot be answered.
    """

    def _pair(self, root: Path) -> tuple[Path, Path]:
        source_path = root / "bracket.stl"
        source = _vent_mount()
        source.export(source_path)
        ball = trimesh.creation.icosphere(radius=BALL_D / 2.0, subdivisions=3)
        ball.apply_translation((*VENT_MOUNT_BOSS, 20.0))
        candidate_path = root / "candidate.stl"
        trimesh.boolean.difference([source, ball], engine="manifold").export(
            candidate_path)
        return source_path, candidate_path

    def test_identical_inputs_produce_byte_identical_evidence(self) -> None:
        from pipeline import schemas as S

        with tempfile.TemporaryDirectory() as raw:
            source_path, candidate_path = self._pair(Path(raw))
            region = PR.Region.from_declaration(_edit_scope().region_box)
            texts = {S.canonical_json(PR.audit(
                source_path=source_path, candidate_path=candidate_path,
                region=region)) for _ in range(3)}
            self.assertEqual(1, len(texts),
                             "three audits of one unchanged pair serialized to "
                             f"{len(texts)} different documents")

    def test_the_plan_is_bound_to_the_exact_pair_it_compared(self) -> None:
        """A plan reused across pairs would be evidence about neither."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source_path, candidate_path = self._pair(root)
            region = PR.Region.from_declaration(_edit_scope().region_box)
            first = PR.audit(source_path=source_path,
                             candidate_path=candidate_path, region=region)

            moved = _vent_mount()
            moved.apply_translation((0.0, 0.0, 0.25))
            other = root / "other.stl"
            moved.export(other)
            second = PR.audit(source_path=source_path, candidate_path=other,
                              region=region)

            self.assertNotEqual(first["sample_plan"]["sha256"],
                                second["sample_plan"]["sha256"])
            self.assertNotEqual(first["evidence_sha256"], second["evidence_sha256"])

    def test_a_changed_input_changes_the_evidence_hash(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source_path, candidate_path = self._pair(root)
            region = PR.Region.from_declaration(_edit_scope().region_box)
            before = PR.audit(source_path=source_path,
                              candidate_path=candidate_path, region=region)

            thicker = trimesh.creation.box(extents=(50.0, 30.0, 8.6))
            thicker.apply_translation((25.0, 15.0, 4.3))
            thicker.export(candidate_path)
            after = PR.audit(source_path=source_path,
                             candidate_path=candidate_path, region=region)

            self.assertNotEqual(before["evidence_sha256"], after["evidence_sha256"])
            self.assertEqual("CHANGED", after["verdict"])

    def test_the_two_directions_are_not_the_same_point_set(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source_path, candidate_path = self._pair(Path(raw))
            region = PR.Region.from_declaration(_edit_scope().region_box)
            report = PR.audit(source_path=source_path,
                              candidate_path=candidate_path, region=region)
            seeds = report["sample_plan"]["direction_seeds"]
            self.assertEqual(set(PR.DIRECTIONS), set(seeds))
            self.assertNotEqual(seeds["source_to_candidate"],
                                seeds["candidate_to_source"])

    def test_the_receipt_does_not_claim_a_sensitivity_it_has_not_earned(self) -> None:
        """Determinism is not accuracy, and the words must not imply it is."""
        with tempfile.TemporaryDirectory() as raw:
            source_path, candidate_path = self._pair(Path(raw))
            region = PR.Region.from_declaration(_edit_scope().region_box)
            note = PR.audit(source_path=source_path,
                            candidate_path=candidate_path,
                            region=region)["claim_note"]
            self.assertIn("cannot establish exact preservation", note)
            self.assertIn("minimum", note)
            self.assertIn("missed identically on every run", note)

    def test_reordering_the_faces_of_one_file_does_not_move_the_measurement(self) -> None:
        """The plan indexes into the faces, so their order has to be the mesh's.

        Two exports of one solid can present the same triangles in a different
        order. Under an ordering that came from the file, that alone would change
        which points the plan lands on and what the audit reports.
        """
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            mesh = _vent_mount()
            plain = root / "plain.stl"
            mesh.export(plain)

            shuffled = trimesh.Trimesh(
                vertices=np.asarray(mesh.vertices),
                faces=np.asarray(mesh.faces)[::-1], process=False)
            reordered = root / "reordered.stl"
            shuffled.export(reordered)

            raw_mesh, record = PR._load(plain)
            self.assertIsNone(record, "a mesh file's read is a parse and has no "
                                      "tessellation to declare")
            first = PR._ordered(raw_mesh)
            second = PR._ordered(PR._load(reordered)[0])
            np.testing.assert_array_equal(first.faces, second.faces)
            np.testing.assert_allclose(first.vertices, second.vertices)
            # Against the mesh as read, not against the other ordered copy: two
            # copies flipped the same way would agree with each other and be
            # inside out. `signed_distance` takes its sign from the winding.
            self.assertAlmostEqual(float(raw_mesh.volume), float(first.volume),
                                   places=6,
                                   msg="canonical ordering must not flip a winding")

class ModifyLaneTest(unittest.TestCase):
    def _checks(self, directory: Path) -> dict:
        report = json.loads(
            (directory / "commission_report.json").read_text(encoding="utf-8"))
        return {c["check_id"]: c for c in report["checks"]} | {"_report": report}

    def test_an_edit_that_stays_in_its_region_passes_the_preservation_gate(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), MODIFIER, _modify_project())
            cli.run([str(directory), "--no-render"])
            checks = self._checks(directory)
            self.assertIn("feature-preservation-bracket", checks,
                          "a MODIFY job with an edit scope must carry the row")
            check = checks["feature-preservation-bracket"]
            self.assertEqual("PASS", check["result"], check)
            self.assertEqual("PRESERVED_WITHIN_TOLERANCE",
                             check["measured"]["verdict"])
            self.assertEqual("PASS", checks["_report"]["verdict"],
                             checks["_report"]["checks"])

    def test_the_support_ceiling_is_inherited_from_the_supplied_artifact(self) -> None:
        """A modification did not choose the geometry it inherited.

        A generated zero-support ceiling fails a supplied part for overhangs
        that were in the file before anybody touched it, and the designer cannot
        chamfer them away without redrawing the part -- which is the one thing a
        modification must not do. So the ceiling is the source artifact's own
        measurement, taken from a file that was fixed before the job started.
        Any overhang the edit *adds* still fails.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), MODIFIER, _modify_project())
            cli.run([str(directory), "--no-render"])
            contract = json.loads(
                (directory / "model_contract.json").read_text(encoding="utf-8"))
            support = next(f for f in contract["features"]
                           if f["feature_id"].startswith("plan-support"))
            self.assertGreater(support["expectation"]["max_area_mm2"], 0.0,
                               "the inherited allowance was not measured")
            self.assertIn("inherited from bracket.stl", support["provenance"])
            self.assertIn("measured before the edit", support["provenance"])

    def test_a_redraw_fails_the_job_even_though_it_looks_right(self) -> None:
        """Every other check passes. This is the one that catches it."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), REDRAWN, _modify_project(
                envelope_mm={"x": 50.0, "y": 30.0, "z": 21.0}),
                REDRAWN_PROPOSAL)
            code = cli.run([str(directory), "--no-render"])
            checks = self._checks(directory)
            self.assertEqual("FAIL", checks["feature-preservation-bracket"]["result"])
            self.assertEqual("CHANGED",
                             checks["feature-preservation-bracket"]["measured"]["verdict"])
            self.assertEqual("FAIL", checks["_report"]["verdict"])
            self.assertEqual(1, code)
            final = json.loads(
                (directory / "final_status.json").read_text(encoding="utf-8"))
            self.assertEqual("FAILED", final["final_status"])

    def test_a_missing_source_artifact_escalates_rather_than_passing(self) -> None:
        """No source, no comparison -- and silence is not a pass.

        Exercised at the check rather than through a run: a model that imports
        the artifact cannot build without it either, so a run would stop earlier
        and never reach the question this check answers.
        """
        from pipeline import analysis
        from pipeline.contract import Feature

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            candidate = root / "candidate.stl"
            _vent_mount().export(candidate)
            ctx = analysis.load(candidate)
            feature = Feature(
                feature_id="preservation", kind="preservation",
                provenance="the edit scope", tolerance={"abs": 0.0},
                verified_by="preservation", on_unrunnable="ESCALATE",
                expectation={"source": "bracket.stl",
                             "region": _edit_scope().region_box,
                             "tolerance_mm": 0.05})
            check = CM._feature_check(ctx, feature, None)
            self.assertEqual("ESCALATE", check.result)
            self.assertEqual("SOURCE_MISSING", check.error_code)
            self.assertEqual("UNAVAILABLE", check.status)

class UnreadableSourceIsNamedInTheVerdictTest(unittest.TestCase):
    """D20. "Rejected" and "we could not read your file" are different sentences.

    `commission_report.json` kept the distinction perfectly -- `ran: false`,
    `status: UNAVAILABLE`, `measured: null`, `result: ESCALATE`,
    `error_code: PRESERVATION_UNMEASURABLE`, the exception as its reason, beside a
    sibling row reading `ran: true / MEASURED`. Nothing collapsed them in that
    JSON, and nothing carried them out of it: `final_status.json` and the CLI
    summary line each said only what the verdict was. A user who did not open the
    commission report learned that their part had been refused, not that the tool
    had never read their primary source. Only one of those is their fault, and
    they call for different actions.

    A second declared source that is on disk and is not geometry is the whole
    setup. `_load` raises, the audit reports `UNMEASURABLE`, and the row escalates
    exactly as an unreadable STEP did.
    """

    def _project(self) -> P.Project:
        return _modify_project(
            source_artifacts=(
                P.SourceArtifact(artifact_id="bracket", path="bracket.stl",
                                 format="STL", classification="USABLE_MESH"),
                P.SourceArtifact(artifact_id="rail", path="rail.stl",
                                 format="STL", classification="USABLE_MESH")),
            edit_scopes=(
                _edit_scope(),
                P.EditScope(artifact_id="rail", region="the rail seat",
                            region_box={"min": [0.0, 0.0, 0.0],
                                        "max": [4.0, 4.0, 4.0]},
                            preserve=("the rail",))))

    def _run(self, root: Path) -> tuple[Path, dict]:
        directory = _laid_out(root, MODIFIER, self._project())
        # On disk, declared, and not geometry. The audit finds the file where the
        # scope said it would be and then cannot make a surface out of it, which
        # is the shape an unreadable STEP had.
        (directory / "rail.stl").write_bytes(b"this is not a mesh\n" * 8)
        cli.run([str(directory), "--no-render"])
        return directory, json.loads(
            (directory / "final_status.json").read_text(encoding="utf-8"))

    def test_the_check_row_still_records_it_precisely(self) -> None:
        """The half that already worked, asserted so the fix cannot cost it."""
        with tempfile.TemporaryDirectory() as raw:
            directory, _ = self._run(Path(raw))
            checks = {c["check_id"]: c for c in json.loads(
                (directory / "commission_report.json").read_text(encoding="utf-8")
            )["checks"]}
            unreadable = checks["feature-preservation-rail"]
            self.assertFalse(unreadable["ran"])
            self.assertEqual("UNAVAILABLE", unreadable["status"])
            self.assertIsNone(unreadable["measured"])
            self.assertEqual("PRESERVATION_UNMEASURABLE", unreadable["error_code"])
            self.assertEqual("ESCALATE", unreadable["result"])
            self.assertTrue(checks["feature-preservation-bracket"]["ran"],
                            "the readable source must still be measured; one "
                            "unreadable sibling is not a reason to stop")

    def test_the_final_status_names_the_check_that_never_ran(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            _, final = self._run(Path(raw))
            self.assertIn("feature-preservation-rail", final["allowed_claim"])
            self.assertIn("PRESERVATION_UNMEASURABLE", final["allowed_claim"])
            self.assertIn("not a finding about the part", final["allowed_claim"],
                          "the claim has to separate an instrument that failed "
                          "from a part that did")

    def test_the_structured_field_is_there_for_a_caller_that_reads_json(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            _, final = self._run(Path(raw))
            rows = {row["check_id"]: row for row in final["unavailable_checks"]}
            self.assertIn("feature-preservation-rail", rows)
            self.assertEqual("PRESERVATION_UNMEASURABLE",
                             rows["feature-preservation-rail"]["error_code"])
            self.assertEqual("rail", rows["feature-preservation-rail"]["feature_id"]
                             .removeprefix("preservation-"))

    def test_the_summary_line_a_user_reads_carries_it_too(self) -> None:
        """`design-tool` prints `allowed_claim`, so the two cannot drift apart."""
        import io
        import contextlib

        with tempfile.TemporaryDirectory() as raw:
            directory, final = self._run(Path(raw))
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                cli.status([str(directory)])
            printed = captured.getvalue()
            self.assertIn("feature-preservation-rail", printed)
            self.assertIn(final["allowed_claim"], printed)

    def test_a_run_with_nothing_unavailable_says_nothing_extra(self) -> None:
        """The sentence appears because a check failed, not on every receipt."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), MODIFIER, _modify_project())
            cli.run([str(directory), "--no-render"])
            final = json.loads(
                (directory / "final_status.json").read_text(encoding="utf-8"))
            self.assertEqual([], final["unavailable_checks"])
            self.assertNotIn("never ran", final["allowed_claim"])

class ModifyReviewRoundTripTest(unittest.TestCase):
    """Run, answer the review, run again, reach a final status.

    The thing no `MODIFY` job with an edit scope could do. The first run wrote a
    review packet and stopped; the second run re-measured preservation with a
    fresh random draw, produced a different `commission_report.json`, and the
    answer written against the first packet no longer matched the envelope the
    second one built. There was no answer that could be written, because the
    question changed every time it was asked.

    The verification review is turned on by an explicit request rather than by
    raising the consequence class: `verification_requested` adds a review on any
    route by design, and it leaves the `CUSTOM` lane's one designer commission
    where it is instead of also pulling in the mandatory safety pass.
    """

    def _project(self) -> P.Project:
        return _modify_project(verification_requested=True,
                               reviewer={"model_snapshot": "test", "fresh_context": True})

    def _answer(self, directory: Path) -> dict:
        packet = json.loads((directory / "reviews" / "verification_packet.json")
                            .read_text(encoding="utf-8"))
        (directory / "reviews" / "verification_response.json").write_text(
            json.dumps({
                "decision": "PASS", "defects": [], "unmet_requirements": [],
                "missing_evidence": [],
                "summary": "the plate, its outline and both screw holes are as supplied",
                "review_envelope": packet["review_envelope"],
            }, indent=2), encoding="utf-8")
        return packet

    def test_a_modify_job_completes_the_review_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), MODIFIER, self._project())

            first = cli.run([str(directory), "--no-render"])
            self.assertEqual(cli.NEEDS_ACTION, first,
                             "the first run must stop and ask for the review")
            waiting = json.loads(
                (directory / "next_action.json").read_text(encoding="utf-8"))
            self.assertEqual("REVIEW", waiting["kind"])
            self.assertEqual("verification", waiting["review_kind"])
            after_first = (directory / "commission_report.json").read_bytes()

            packet = self._answer(directory)
            cli.run([str(directory), "--no-render"])

            after_second = (directory / "commission_report.json").read_bytes()
            self.assertEqual(after_first, after_second,
                             "the rerun measured the part differently, so the "
                             "answer was written against evidence that no longer "
                             "exists")

            report = json.loads(
                (directory / "verification_report.json").read_text(encoding="utf-8"))
            self.assertNotIn("error", report,
                             "the answer was refused; the round trip did not close")
            self.assertEqual("PASS", report["decision"])
            self.assertEqual(packet["review_envelope"], report["review_envelope"])

            final = json.loads(
                (directory / "final_status.json").read_text(encoding="utf-8"))
            self.assertIn(final["final_status"], S.FINAL_STATUS)
            self.assertEqual("PASS", final["verification"],
                             "the independent look was accepted and recorded")
            self.assertNotIn("unbound", final["allowed_claim"])
            # The lane cap is what this stage does not lift. Preservation is
            # deterministic; the acceptance criteria are still self-issued and
            # the sample density is still not derived from a defect size.
            self.assertEqual("EXPERIMENTAL_UNAVAILABLE", final["lane_status"])

    def test_the_review_envelope_names_the_preservation_evidence(self) -> None:
        """An answer must be checkable against the audit it actually read.

        Binding the packet hash alone says only *that* something moved. The
        envelope carries the sample plan's digest and the audit's own digest, so
        a reader of a stale answer can see which measurement it was written
        against rather than only that it no longer matches.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), MODIFIER, self._project())
            cli.run([str(directory), "--no-render"])

            packet = json.loads((directory / "reviews" / "verification_packet.json")
                                .read_text(encoding="utf-8"))
            digests = packet["review_envelope"]["evidence_digests"]
            self.assertEqual(
                {"feature-preservation-bracket.sample_plan_sha256",
                 "feature-preservation-bracket.evidence_sha256"}, set(digests))

            measured = next(c for c in packet["commission_report"]["checks"]
                            if c["check_id"] == "feature-preservation-bracket")["measured"]
            self.assertEqual(measured["sample_plan_sha256"],
                             digests["feature-preservation-bracket.sample_plan_sha256"])
            self.assertEqual(measured["evidence_sha256"],
                             digests["feature-preservation-bracket.evidence_sha256"])

    def test_an_answer_to_a_different_audit_is_refused(self) -> None:
        """The binding has to fail closed when the evidence really did move.

        Determinism is what stops the mismatch happening by accident. It must not
        also stop it happening on purpose: an answer naming a sample plan this run
        did not use is still an answer to a different question.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), MODIFIER, self._project())
            cli.run([str(directory), "--no-render"])
            packet = self._answer(directory)

            response = directory / "reviews" / "verification_response.json"
            stale = json.loads(response.read_text(encoding="utf-8"))
            stale["review_envelope"] = {
                **packet["review_envelope"],
                "evidence_digests": {
                    "feature-preservation-bracket.sample_plan_sha256": "0" * 64,
                    "feature-preservation-bracket.evidence_sha256": "0" * 64,
                },
            }
            response.write_text(json.dumps(stale, indent=2), encoding="utf-8")

            code = cli.run([str(directory), "--no-render"])
            self.assertNotEqual(0, code)
            report = json.loads(
                (directory / "verification_report.json").read_text(encoding="utf-8"))
            self.assertIn("ReviewError", report["error"])
            self.assertNotIn("decision", report,
                             "a refused answer must not leave a decision behind")
            self.assertFalse((directory / "final_status.json").is_file(),
                             "an unbound answer must not produce a final status")

class ModifyRerunRejectionTest(unittest.TestCase):
    """Store the answer, change one bound input, rerun: the answer must be refused.

    `ROADMAP.md` Release 1 asks for five of these -- changed source, changed
    candidate, changed edit intent, changed transform, changed algorithm version --
    and the nearest tests in this file are not them. Two of them compare two
    digests computed in-process without ever running a job;
    `test_an_answer_to_a_different_audit_is_refused` fabricates a digest rather
    than changing an input. None of the three offers a review a stored response
    written against a real run, and none looks at whether a final status was
    written anyway. This does the whole loop: run to the review pause, store the
    answer the run asked for, change exactly one thing, run the same command
    again, and require both a `ReviewError` and no `final_status.json`.

    "Edit intent" is not one field. `region_box`, the region name and
    `preservation_tolerance_mm` reached the acceptance contract already;
    `preserve`, `may_remove`, `add`, `expected_body_delta`, `preserve_metadata`,
    `interface_ids` and `alignment_transform` were declared, validated and
    serialised into `project.json`, and read by nothing -- so a job could change
    what it promised about the edit, or where its source sits in the job's frame,
    and keep the answer somebody wrote against the previous promise. The property
    worth having is that the set is closed, so every member of it is a case here
    rather than the three that happened to work.

    The stored response is deliberately *not* cleaned up between the two runs. A
    new acceptance revision deletes the receipts of the superseded one; it does
    not delete `reviews/`, so the second run really does read an answer a person
    wrote and really does have to refuse it.
    """

    # Declared on the project so a scope may cite it: `Project.validate` refuses
    # an `interface_id` naming an interface nothing declares, so the field cannot
    # be exercised at all on a project with no interfaces.
    INTERFACE = P.Interface(
        interface_id="boss-seat", kind="ball seat", external=False,
        owner="this job", note="the seat this edit cuts")

    def _laid_out(self, root: Path) -> Path:
        return _laid_out(root, MODIFIER, _modify_project(
            verification_requested=True,
            reviewer={"model_snapshot": "test", "fresh_context": True},
            interfaces=(self.INTERFACE,)))

    def _rescope(self, directory: Path, **fields) -> None:
        """Rewrite the one edit scope on disk with one field changed."""
        project = P.load(directory)
        project.edit_scopes = (
            dataclasses.replace(project.edit_scopes[0], **fields),)
        project.save(directory)

    # -- the changed inputs, one per case ---------------------------------
    def _changed_source(self, directory: Path) -> None:
        """The supplied artifact itself: a plate 0.2 mm taller than the one given."""
        plate = trimesh.creation.box(extents=(50.0, 30.0, 8.2))
        plate.apply_translation((25.0, 15.0, 4.1))
        plate.export(directory / "bracket.stl")

    def _changed_candidate(self, directory: Path) -> None:
        """The model: a 16 mm seat instead of 17, with `PARAMS` left alone.

        The declared parameters still agree with the proposal, so nothing but the
        geometry has moved -- which is exactly the change a hash of the parameter
        dict would miss.
        """
        path = directory / "model.py"
        text = path.read_text(encoding="utf-8")
        edited = text.replace("radius=17.0 / 2.0", "radius=16.0 / 2.0")
        self.assertNotEqual(text, edited,
                            "the fixture no longer spells the seat radius the way "
                            "this mutation looks for")
        path.write_text(edited, encoding="utf-8")

    def _changed_region_box(self, directory: Path) -> None:
        scope = P.load(directory).edit_scopes[0]
        box = dict(scope.region_box)
        box["max"] = [box["max"][0] + 1.0, box["max"][1], box["max"][2]]
        self._rescope(directory, region_box=box)

    def _changed_transform(self, directory: Path) -> None:
        """Where the source sits in the job's frame: 5 mm along x."""
        self._rescope(directory, alignment_transform=[
            [1.0, 0.0, 0.0, 5.0], [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]])

    def _changed_plan_version(self, directory: Path) -> None:
        """The algorithm version, which lives in no file the job can edit."""
        PR.SAMPLE_PLAN_VERSION = PR.SAMPLE_PLAN_VERSION + 1

    def _changed_preserve(self, directory: Path) -> None:
        self._rescope(directory, preserve=(
            "the plate, its outline and both screw holes",
            "and the boss cylinder it stands on"))

    def _changed_may_remove(self, directory: Path) -> None:
        self._rescope(directory, may_remove=("the boss face material the seat takes",))

    def _changed_add(self, directory: Path) -> None:
        self._rescope(directory, add=("a 17 mm ball socket and a retaining lip",))

    def _changed_body_delta(self, directory: Path) -> None:
        self._rescope(directory, expected_body_delta=1)

    def _changed_preserve_metadata(self, directory: Path) -> None:
        """Named by no audit entry, and unbound for the same reason as the rest."""
        self._rescope(directory, preserve_metadata=False)

    def _changed_interface_ids(self, directory: Path) -> None:
        self._rescope(directory, interface_ids=(self.INTERFACE.interface_id,))

    def _refuses(self, mutate) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = self._laid_out(Path(raw))
            self.assertEqual(
                cli.NEEDS_ACTION, cli.run([str(directory), "--no-render"]),
                "the first run must stop and ask for the verification review")
            _store_passing_answer(directory)

            mutate(directory)

            code = cli.run([str(directory), "--no-render"])
            self.assertNotEqual(0, code,
                               "a job whose bound input changed under a stored "
                               "answer must not report success")
            report = directory / "verification_report.json"
            self.assertTrue(report.is_file(),
                            "the refusal has to be written down; a run that "
                            "leaves no report leaves no reason")
            parsed = json.loads(report.read_text(encoding="utf-8"))
            self.assertIn("ReviewError", parsed.get("error", ""),
                          "the stored answer was not refused as unbound")
            self.assertNotIn("decision", parsed,
                             "a refused answer must not leave a decision behind")
            self.assertFalse(
                (directory / "final_status.json").is_file(),
                "an answer written against different inputs must not produce a "
                "final status")

    def test_changing_one_bound_input_refuses_the_stored_answer(self) -> None:
        cases = (
            # ROADMAP Release 1's five, in its own words.
            ("changed source", self._changed_source),
            ("changed candidate", self._changed_candidate),
            ("changed edit intent: region_box", self._changed_region_box),
            ("changed transform", self._changed_transform),
            ("changed algorithm version", self._changed_plan_version),
            # The rest of the declared edit intent, which is the same proof.
            ("changed edit intent: preserve", self._changed_preserve),
            ("changed edit intent: may_remove", self._changed_may_remove),
            ("changed edit intent: add", self._changed_add),
            ("changed edit intent: expected_body_delta", self._changed_body_delta),
            ("changed edit intent: preserve_metadata", self._changed_preserve_metadata),
            ("changed edit intent: interface_ids", self._changed_interface_ids),
        )
        for name, mutate in cases:
            with self.subTest(changed=name):
                # Restored for every case, not only the one that moves it: a
                # module global left bumped would silently change what every
                # later case measures.
                version = PR.SAMPLE_PLAN_VERSION
                try:
                    self._refuses(mutate)
                finally:
                    PR.SAMPLE_PLAN_VERSION = version

    def test_an_answer_from_the_previous_protocol_is_refused_by_name(self) -> None:
        """The bump has to refuse a stored answer, not reinterpret it.

        The envelope gained `execution_plan_sha256`, so an answer written against
        the previous shape is an answer to a question with one fewer binding in
        it. `review.py` prescribes the bump for exactly this, and what makes the
        bump worth more than a silent added field is the refusal naming the
        version: "unknown protocol_version 2" tells whoever has to fix it what
        happened, and a digest mismatch does not.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = self._laid_out(Path(raw))
            self.assertEqual(cli.NEEDS_ACTION, cli.run([str(directory), "--no-render"]))
            packet = _store_passing_answer(directory)

            response = directory / "reviews" / "verification_response.json"
            stale = json.loads(response.read_text(encoding="utf-8"))
            # Spelled 2 rather than `VERSION - 1`: this is the one specific
            # stored answer this bump invalidates, and it must stay refused
            # however many versions are added after it.
            envelope = {k: v for k, v in packet["review_envelope"].items()
                        if k != "execution_plan_sha256"}
            stale["review_envelope"] = {**envelope, "protocol_version": 2}
            response.write_text(json.dumps(stale, indent=2), encoding="utf-8")

            code = cli.run([str(directory), "--no-render"])
            self.assertNotEqual(0, code,
                                "an answer bound to the previous envelope shape "
                                "was accepted and the job finished")
            report = json.loads((directory / "verification_report.json")
                                .read_text(encoding="utf-8"))
            self.assertIn("unknown protocol_version 2", report.get("error", ""))
            self.assertIn(f"this build speaks {R.REVIEW_PROTOCOL_VERSION}",
                          report["error"],
                          "the refusal must say which protocol this build does "
                          "speak, or nobody can act on it")
            self.assertFalse((directory / "final_status.json").is_file())

class ModifyCleanCloneTest(unittest.TestCase):
    """One MODIFY project laid out at two paths has one identity.

    `ROADMAP.md` Release 1's ninth proof. Two tests already compare two
    directories byte for byte -- `test_frozen`'s
    `test_two_direct_runs_write_byte_identical_receipts` and `test_pipeline`'s
    `DeterminismTest` -- and both are certified-template `DIRECT` jobs with no
    edit scope, no preservation audit and no sample plan. Neither exercises the
    identity this release is about, which is the identity of a *measurement* and
    of the plan that produced it.

    `module_sha256` is deliberately not asserted equal, and the inequality is
    asserted instead so the exclusion is a recorded fact rather than a silence.
    The confined build stages `model.py` into a sandbox and runs it with its
    working directory inside that sandbox, staging nothing else; a MODIFY model
    therefore has to name its source artifact by absolute path, and this fixture's
    `model.py` differs between two directories by exactly that string and nothing
    else. Making it relative would mean staging source artifacts into the build
    sandbox -- a change to the build boundary, not to a test.
    """

    def _run_to_the_review(self, root: Path) -> Path:
        directory = _laid_out(root, MODIFIER, _modify_project(
            verification_requested=True,
            reviewer={"model_snapshot": "test", "fresh_context": True}))
        self.assertEqual(cli.NEEDS_ACTION, cli.run([str(directory), "--no-render"]))
        return directory

    def test_the_same_project_at_two_paths_measures_one_thing(self) -> None:
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            first = self._run_to_the_review(Path(a))
            second = self._run_to_the_review(Path(b))
            self.assertNotEqual(first, second)

            for name in ("acceptance_contract.json", "execution_plan.json"):
                with self.subTest(artifact=name):
                    self.assertEqual((first / name).read_text(encoding="utf-8"),
                                     (second / name).read_text(encoding="utf-8"))

            reports = [json.loads((d / "commission_report.json").read_text(encoding="utf-8"))
                       for d in (first, second)]
            self.assertEqual(reports[0]["evidence_digests"],
                             reports[1]["evidence_digests"],
                             "the preservation audit measured two different things "
                             "at two paths, so the evidence is a function of where "
                             "the project happens to sit")
            self.assertTrue(reports[0]["evidence_digests"],
                            "a MODIFY job with an edit scope owes evidence digests; "
                            "comparing two empty dicts proves nothing")

            manifests = [json.loads((d / "artifact_manifest.json").read_text(encoding="utf-8"))
                         for d in (first, second)]
            self.assertEqual(manifests[0]["stl_sha256"], manifests[1]["stl_sha256"])

            envelopes = [json.loads((d / "reviews" / "verification_packet.json")
                                    .read_text(encoding="utf-8"))["review_envelope"]
                         for d in (first, second)]
            self.assertEqual(envelopes[0]["execution_plan_sha256"],
                             envelopes[1]["execution_plan_sha256"])
            # Hashed from the text rather than from the file: `write_text`
            # translates the canonical `\n` to `\r\n` on this platform, so the
            # bytes on disk are not the bytes the canonical hash covers.
            self.assertEqual(
                S.sha256_text((first / "execution_plan.json").read_text(encoding="utf-8")),
                envelopes[0]["execution_plan_sha256"],
                "the plan digest the reviewer is bound to must be the digest of "
                "the plan file the run was carried out under")

            # The one thing that legitimately differs, and why. See the class
            # docstring: it is the fixture's absolute path, not the pipeline's.
            self.assertNotEqual(manifests[0]["source_sha256"],
                                manifests[1]["source_sha256"])
            elided = [(d / "model.py").read_text(encoding="utf-8")
                      .replace(str(d).replace("\\", "\\\\"), "<project>")
                      for d in (first, second)]
            self.assertEqual(elided[0], elided[1],
                             "the two models differ by more than the project path, "
                             "so the excluded difference is no longer the declared one")

class TwoScopeModifyTest(unittest.TestCase):
    """Two edit scopes, one job, and one of them changed under a stored answer.

    Every multi-scope test in `test_phase1.py` is schema or validation only: two
    scopes are declared, `Project.validate` is asked what it thinks, and no job is
    ever run. So the property that matters -- that each scope's row carries its
    own bindings, and that changing one does not silently re-measure or silently
    keep the other -- had never been observed.

    The three cases below are the same rerun-rejection proof, with the extra
    question of *which* row moved. They also separate the two places a binding can
    live: `region_box` and `alignment_transform` are in the sampling seed, so
    changing one moves that row's plan digest and leaves the other row's bytes
    alone; `preserve` is in the contract only, so changing it moves no evidence
    digest at all and the answer is still refused -- through `contract_sha256`,
    which is the honest binding for a field that changed no measurement.
    """

    def _digests(self, directory: Path) -> dict:
        return json.loads((directory / "commission_report.json")
                          .read_text(encoding="utf-8"))["evidence_digests"]

    def _only(self, digests: dict, artifact: str) -> dict:
        return {k: v for k, v in digests.items()
                if k.startswith(f"feature-preservation-{artifact}.")}

    def _one_scope_moves(self, mutate, *, evidence_moves: bool) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _two_scopes_laid_out(Path(raw))
            self.assertEqual(cli.NEEDS_ACTION, cli.run([str(directory), "--no-render"]))

            contract = json.loads((directory / "acceptance_contract.json")
                                  .read_text(encoding="utf-8"))
            rows = [f for f in contract["features"] if f["kind"] == "preservation"]
            self.assertEqual(["preservation-left", "preservation-right"],
                             sorted(row["feature_id"] for row in rows),
                             "two declared scopes owe two rows, each naming its "
                             "own artifact")

            before = self._digests(directory)
            self.assertEqual(2, len(self._only(before, "left")))
            self.assertEqual(2, len(self._only(before, "right")))
            _store_passing_answer(directory)

            project = P.load(directory)
            project.edit_scopes = (project.edit_scopes[0],
                                   mutate(project.edit_scopes[1]))
            project.save(directory)

            code = cli.run([str(directory), "--no-render"])
            after = self._digests(directory)
            self.assertEqual(self._only(before, "left"), self._only(after, "left"),
                             "only the right scope changed, so the left artifact's "
                             "evidence must be byte-identical")
            if evidence_moves:
                self.assertNotEqual(self._only(before, "right"),
                                    self._only(after, "right"),
                                    "the changed scope's sampling plan did not move")
            else:
                self.assertEqual(self._only(before, "right"),
                                 self._only(after, "right"),
                                 "a field that changes nothing about what is "
                                 "sampled must not move a sample plan digest")

            self.assertNotEqual(0, code)
            report = json.loads((directory / "verification_report.json")
                                .read_text(encoding="utf-8"))
            self.assertIn("ReviewError", report.get("error", ""))
            self.assertFalse((directory / "final_status.json").is_file())

    def test_changing_one_scope_binds_only_that_scope(self) -> None:
        cases = (
            ("region_box",
             lambda scope: dataclasses.replace(scope, region_box={
                 **RIGHT_BOX, "max": [57.0, 16.0, 14.0]}),
             True),
            ("alignment_transform",
             lambda scope: dataclasses.replace(scope, alignment_transform=[
                 [1.0, 0.0, 0.0, 5.0], [0.0, 1.0, 0.0, 0.0],
                 [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]),
             True),
            # In the contract and not in the seed, and the assertion says so:
            # the answer is still refused, and no sample plan pretends to have
            # been recomputed.
            ("preserve",
             lambda scope: dataclasses.replace(
                 scope, preserve=("the plate rim and both mounting faces",)),
             False),
        )
        for name, mutate, evidence_moves in cases:
            with self.subTest(changed=name):
                self._one_scope_moves(mutate, evidence_moves=evidence_moves)
