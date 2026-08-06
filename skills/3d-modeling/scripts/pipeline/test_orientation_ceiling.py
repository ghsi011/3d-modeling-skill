#!/usr/bin/env python3
"""D15's last half: the ceiling was generated in a frame nobody declared.

`test_orientation_frame.py` closed the screen and `test_commission_frame.py`
closed the three contract checks. Both fixed the side of the inequality that
measures the *candidate*. The review of that slice found the other side still
open, and the defect log carried it until this landed:

* `cli._print_plan` called `designer_toolkit.plan.direct_template` without the
  project's orientation, and `direct_template` wrote `IDENTITY_TRANSFORM` into
  its one support rule whatever the job had declared;
* `cli._plan_features` copied that rule's `downward_normal_z_max` and
  `bed_z_mm` into the contract row and dropped its `model_to_printer_matrix`,
  so the contract's orientation silently stood in for a declaration another
  artifact had made and nothing checked the two agreed;
* `cli._inherited_overhang` called `metrics.overhang_area` with no `transform=`
  while `commission` passes `contract.printer_transform`.

Net effect: on a `MODIFY` job declaring any reorientation, the ceiling was the
source's downward area *as authored* and the candidate's was measured in the
printer frame. Two sides of one inequality, two frames -- and before the
candidate half was fixed they had at least been wrong the same way.

**One authority chain, not a fourth transform reader.** `project.orientation`
is the declaration. It reaches the acceptance contract already; it now reaches
the generated plan from `_print_plan`; the plan rule's copy travels into the
contract feature row; `contract.preflight` refuses the run when the two
disagree; and `contract.as_transform` is the single resolution all of them use,
so `"identity"` and the 4x4 identity are one declaration in two spellings rather
than a refusal.

Every test here fails against at least one of the five mutations D15 named --
removing the orientation from plan generation, the alignment from the
composition, the printer transform from the inherited measurement, the preflight
equality, or the `transform=` argument itself. All five are run in
`CHANGELOG.md`'s entry for this fix.
"""
from __future__ import annotations

import dataclasses
import math
import tempfile
import unittest
from pathlib import Path
from typing import Any

import numpy as np
import trimesh

from designer_toolkit import metrics as M
from designer_toolkit import plan as PL

from . import cli
from . import contract as CT
from . import project as P

UTC = "1970-01-01T00:00:00Z"


def _flip_x_180() -> list[list[float]]:
    """Turns the part over: z -> -z, y -> -y. An ordinary print decision."""
    return [[1.0, 0.0, 0.0, 0.0], [0.0, -1.0, 0.0, 0.0],
            [0.0, 0.0, -1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]


def _printer_rotate_x_90() -> list[list[float]]:
    """A quarter turn about X: the printer half of the non-commuting pair."""
    return [[1.0, 0.0, 0.0, 0.0], [0.0, 0.0, -1.0, 0.0],
            [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 0.0, 1.0]]


def _align_rotate_z_270_and_move() -> list[list[float]]:
    """Three quarter turns about Z **and** a translation, as one alignment.

    Both halves of this are load-bearing and neither was obvious.

    *A different axis from the printer's.* Rotations about one shared axis
    commute, so an alignment and a printer transform that both turn about X
    have the same rotation block in either order and only their translations
    differ -- which the overhang measurement, being a question about face
    normals first, mostly cannot see. Measured on the first attempt at this
    fixture: `printer @ alignment` and `alignment @ printer` both returned
    0.000 mm2 and the test proved nothing.

    *And a translation.* Without it the composition still reads 200.0 mm2
    rather than the 100.0 mm2 the real pair produces, so a mutation that
    dropped the offset and kept the rotation would survive a rotation-only
    fixture.

    Against `_stepped_source` the five numbers are all distinct, which is what
    makes this one fixture answer five separate mutations:

        printer @ alignment   100.0 mm2   <- what the code must do
        alignment @ printer     0.0 mm2   <- multiplication order reversed
        alignment only        300.0 mm2   <- printer transform dropped
        printer only          300.0 mm2   <- source alignment dropped
        no transform at all   300.0 mm2   <- `transform=` dropped
    """
    return [[0.0, 1.0, 0.0, 0.0], [-1.0, 0.0, 0.0, 20.0],
            [0.0, 0.0, 1.0, 5.0], [0.0, 0.0, 0.0, 1.0]]


def _orientation(matrix: Any = "identity", bed_z: float = 0.0) -> dict[str, Any]:
    return {"model_to_printer_matrix": matrix, "bed_z_mm": bed_z}


def _project(**over) -> P.Project:
    base = dict(
        job_id="d15-ceiling", updated_utc=UTC, source_mode="NEW",
        consequence="INCONSEQUENTIAL",
        consequence_rationale="a fixture; failure wastes nothing",
        printer="Test Printer", material={"process": "FDM", "material": "PLA"},
        nozzle={"diameter_mm": 0.4}, orientation=_orientation(),
        envelope_mm={"x": 60.0, "y": 60.0, "z": 60.0},
        reviewer={"model_snapshot": "test"},
    )
    base.update(over)
    return P.Project(**base)


ARTIFACT = P.SourceArtifact(artifact_id="src", path="source.stl",
                            format="STL", classification="USABLE_MESH")


def _scope(alignment: Any = "identity") -> P.EditScope:
    return P.EditScope(
        artifact_id="src", region="the mounting boss",
        region_box={"min": [0.0, 0.0, 0.0], "max": [10.0, 10.0, 10.0]},
        preserve=("everything but the boss",),
        alignment_transform=alignment)


def _modify(alignment: Any = "identity", **over) -> P.Project:
    return _project(source_mode="MODIFY", source_artifacts=(ARTIFACT,),
                    edit_scopes=(_scope(alignment),), **over)


def _asymmetric_source(directory: Path) -> Path:
    """A cone, flat base down, lifted clear of the bed.

    Asymmetric about the XY plane on purpose, and the whole first fixture rests
    on it: a shape symmetric under the flip -- a box, a sphere -- has the same
    downward area either way up, so it cannot tell a measurement that applied
    the orientation from one that ignored it. A cone has a flat base and a
    conical flank, and turning it over swaps which of the two faces down.

    Lifted 5 mm because `overhang_area` excludes faces sitting inside the bed
    band: a base resting at z=0 contributes zero downward area and every
    assertion below would pass for the wrong reason.
    """
    cone = trimesh.creation.cone(radius=20.0, height=10.0, sections=64)
    cone.apply_translation((0.0, 0.0, 5.0))
    path = directory / "source.stl"
    cone.export(path)
    return path


def _stepped_source(directory: Path) -> Path:
    """Two blocks at two heights, offset in X: asymmetric about all three axes.

    The composition fixtures need a shape whose downward area *changes* under
    each of five different transforms, and a cone cannot do it: turn its axis
    off vertical and its flank normals sit near the horizon, well inside the
    -0.73 threshold, so almost every rotation reads 0.000 mm2 and the fixture
    stops discriminating. Two flat undersides at two heights keep a large,
    axis-aligned downward area in play through every one of them.

    Two bodies rather than one solid, and legitimately: an artifact a job is
    handed may be several, and `overhang_area` measures faces rather than
    solids. Nothing here depends on them being joined.
    """
    lower = trimesh.creation.box(extents=(20.0, 10.0, 10.0))
    lower.apply_translation((0.0, 0.0, 15.0))
    upper = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
    upper.apply_translation((15.0, 0.0, 30.0))
    path = directory / "source.stl"
    trimesh.util.concatenate([lower, upper]).export(path)
    return path


def _rule(plan: dict[str, Any]) -> dict[str, Any]:
    return plan["support_rules"][0]


class ThePlanIsGeneratedInTheDeclaredOrientationTest(unittest.TestCase):
    """`project.orientation` reaches the plan, or the ceiling has no frame."""

    def test_the_generated_rule_carries_the_projects_matrix(self) -> None:
        """The mutation this observes is removing `orientation=` from
        `_print_plan`'s `direct_template` call. It looks at the plan actually
        written, not at the argument, so passing the wrong object fails too."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            plan, problems = cli._print_plan(
                work, _project(orientation=_orientation(_flip_x_180(), 0.0)))
            self.assertEqual([], problems)
            self.assertEqual(_flip_x_180(), _rule(plan)["model_to_printer_matrix"])

    def test_the_generated_rule_carries_the_projects_bed_height(self) -> None:
        """`bed_z_mm` decides which faces count as bed contact rather than
        overhang, so a rule at 0.0 under a job printing off a 5 mm raft is
        measuring a different thing from the check it feeds."""
        with tempfile.TemporaryDirectory() as raw:
            plan, problems = cli._print_plan(
                Path(raw), _project(orientation=_orientation("identity", 5.0)))
            self.assertEqual([], problems)
            self.assertEqual(5.0, _rule(plan)["bed_z_mm"])

    def test_identity_leaves_the_common_path_byte_identical(self) -> None:
        """The cost side of this slice, pinned rather than asserted in prose.

        A job that declares no reorientation must emit exactly the plan it
        emitted before, or every recorded `print_plan_sha256` moves for a
        declaration that did not change. `"identity"` and the 4x4 identity are
        both spellings of that, and both have to land on the same bytes.
        """
        from . import schemas as S

        before = PL.direct_template((60.0, 60.0, 60.0), job_id="d15-ceiling")
        for matrix in ("identity", PL.IDENTITY_TRANSFORM):
            with self.subTest(matrix=matrix):
                after = PL.direct_template((60.0, 60.0, 60.0),
                                           job_id="d15-ceiling",
                                           orientation=_orientation(matrix, 0.0))
                self.assertEqual(S.canonical_json(before), S.canonical_json(after))

    def test_a_declared_reorientation_does_move_the_plan(self) -> None:
        """The other direction, or the test above is satisfied by a function
        that ignores its new argument entirely."""
        from . import schemas as S

        flipped = PL.direct_template((60.0, 60.0, 60.0), job_id="d15-ceiling",
                                     orientation=_orientation(_flip_x_180(), 0.0))
        plain = PL.direct_template((60.0, 60.0, 60.0), job_id="d15-ceiling")
        self.assertNotEqual(S.canonical_json(plain), S.canonical_json(flipped))


class ThePlanAndTheContractMayNotDisagreeTest(unittest.TestCase):
    """Refused before geometry, and neither side silently chosen."""

    @staticmethod
    def _contract(orientation: dict[str, Any],
                  rule_matrix: Any, bed_z: float = 0.0) -> CT.Contract:
        feature = CT.Feature(
            feature_id="plan-support-00", kind="overhang",
            provenance="print plan rule S-01",
            expectation={"max_area_mm2": 0.0, "downward_normal_z_max": -0.73,
                         "bed_z_mm": bed_z,
                         "model_to_printer_matrix": rule_matrix},
            tolerance={"abs": 0.0}, verified_by="overhang",
            on_unrunnable="ESCALATE", mandatory=True)
        return CT.Contract(
            job_id="d15", template="none", template_version="1",
            domain_id="none", backend="authored", parameters={},
            features=(feature,), expected_bbox_mm={"x": 1.0, "y": 1.0, "z": 1.0},
            bbox_tolerance_mm=0.5, expected_bodies=1, orientation=orientation,
            material={"process": "FDM", "material": "PLA"},
            nozzle={"diameter_mm": 0.4}, printer="none", modifiers=(),
            minimum_coverage=1.0, step_required=False,
            consequence="INCONSEQUENTIAL", updated_utc=UTC)

    def _preflight(self, contract: CT.Contract) -> list[str]:
        return CT.preflight(contract, known_checks=frozenset({"overhang"}))

    def test_a_rule_that_disagrees_with_the_project_is_refused(self) -> None:
        """The fixture D15 names. The contract prints the part one way up and
        the rule that set its ceiling measured it the other, and a run that
        proceeded would compare two frames and report the difference as the
        edit's fault."""
        problems = self._preflight(self._contract(_orientation("identity"),
                                                  _flip_x_180()))
        self.assertTrue(problems)
        self.assertTrue(any("different print orientation" in text
                            for text in problems), problems)

    def test_a_rule_that_agrees_is_silent(self) -> None:
        """Or the refusal is just a way of failing every job."""
        for orientation, rule in ((_orientation("identity"), PL.IDENTITY_TRANSFORM),
                                  (_orientation(PL.IDENTITY_TRANSFORM), "identity"),
                                  (_orientation(_flip_x_180()), _flip_x_180())):
            with self.subTest(rule=rule):
                self.assertEqual([], self._preflight(
                    self._contract(orientation, rule)))

    def test_two_spellings_of_one_declaration_are_not_a_disagreement(self) -> None:
        """`"identity"` is the contract's spelling and a support rule needs a
        matrix, so the two are never literally equal on the common path.
        Comparing literals here would refuse every job in the repository."""
        self.assertEqual([], self._preflight(
            self._contract(_orientation("identity"), PL.IDENTITY_TRANSFORM)))

    def test_a_disagreeing_bed_height_is_refused_too(self) -> None:
        """Bed contact is what separates a supported face from an overhang, so
        two bed heights are two measurements as surely as two matrices are."""
        problems = self._preflight(
            self._contract(_orientation("identity", 0.0), "identity", bed_z=5.0))
        self.assertTrue(any("bed_z_mm" in text for text in problems), problems)

    def test_an_unusable_rule_matrix_refuses_rather_than_defaulting(self) -> None:
        """A matrix nothing can apply is not permission to measure the authored
        frame -- that is D15 with an extra step."""
        projective = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0],
                      [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 1.0, 1.0]]
        for matrix in (projective, "sideways", None, 7, [[1.0, 0.0], [0.0, 1.0]]):
            with self.subTest(matrix=matrix):
                self.assertTrue(self._preflight(
                    self._contract(_orientation("identity"), matrix)))

    def test_the_generated_contract_row_carries_the_rules_matrix(self) -> None:
        """`_plan_features` dropped it, which is what let the two disagree
        undetected: with no matrix on the row there is nothing for the preflight
        above to compare."""
        with tempfile.TemporaryDirectory() as raw:
            plan, _ = cli._print_plan(
                Path(raw), _project(orientation=_orientation(_flip_x_180())))
            rows = cli._plan_features(plan)
            self.assertEqual(1, len(rows))
            self.assertEqual(_flip_x_180(), rows[0]["model_to_printer_matrix"])

    def test_the_whole_chain_refuses_a_plan_built_for_another_frame(self) -> None:
        """The four steps joined, on generated artifacts rather than literals.

        A plan is generated for a job that prints the part flipped; its support
        row is compiled by `_plan_features` exactly as a run compiles it; the
        row is then placed in a contract that declares the identity -- which is
        what a frozen contract from an earlier revision, or a plan supplied from
        outside this generator, would produce. The run must stop here, before
        any geometry is paid for, and it must not resolve the disagreement by
        preferring either declaration.

        The same two artifacts built for one frame must of course pass, or this
        is a test that the pipeline refuses everything.
        """
        with tempfile.TemporaryDirectory() as raw:
            flipped_plan, problems = cli._print_plan(
                Path(raw), _project(orientation=_orientation(_flip_x_180())))
            self.assertEqual([], problems)
        row = cli._plan_features(flipped_plan)[0]
        expectation = {k: v for k, v in row.items()
                       if k not in ("feature_id", "kind", "note", "tolerance")}
        feature = CT.Feature(
            feature_id=row["feature_id"], kind=row["kind"],
            provenance=row["note"], expectation=expectation,
            tolerance=row["tolerance"], verified_by="overhang",
            on_unrunnable="ESCALATE", mandatory=True)

        def _with(orientation: dict[str, Any]) -> list[str]:
            contract = ThePlanAndTheContractMayNotDisagreeTest._contract(
                orientation, "identity")
            return CT.preflight(
                dataclasses.replace(contract, features=(feature,)),
                known_checks=frozenset({"overhang"}))

        refused = _with(_orientation("identity"))
        self.assertTrue(any("different print orientation" in text
                            for text in refused), refused)
        self.assertEqual([], _with(_orientation(_flip_x_180())))


class TheInheritedCeilingIsMeasuredWhereThePartPrintsTest(unittest.TestCase):
    """The ceiling and the candidate in one frame, or the inequality is noise."""

    def test_a_flip_changes_the_inherited_allowance(self) -> None:
        """The first fixture D15 requires: an asymmetric source whose overhang
        differs between the identity and a 180 degree rotation.

        Measured on this cone -- flat base down, lifted 5 mm -- the base is
        1256.6 mm2 of downward area as authored, and turned over it is the
        conical flank instead. The two numbers must not be equal, or nothing
        here observes that the transform was applied.
        """
        rule = {"downward_normal_z_max": -0.73, "bed_z_mm": 0.0}
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            _asymmetric_source(directory)
            upright = cli._inherited_overhang(
                directory, _modify(),
                {**rule, "model_to_printer_matrix": "identity"})
            flipped = cli._inherited_overhang(
                directory, _modify(),
                {**rule, "model_to_printer_matrix": _flip_x_180()})
            self.assertIsNotNone(upright)
            self.assertIsNotNone(flipped)
            self.assertGreater(upright[0], 0.0)
            self.assertNotAlmostEqual(
                upright[0], flipped[0], places=3,
                msg="the printer transform reached the measurement or it did "
                    "not; equal areas mean it did not")

    def _composed(self, directory: Path):
        """The one measurement the non-commuting fixture is built around."""
        return cli._inherited_overhang(
            directory, _modify(_align_rotate_z_270_and_move()),
            {"downward_normal_z_max": -0.73, "bed_z_mm": 0.0,
             "model_to_printer_matrix": _printer_rotate_x_90()})

    def test_the_measurement_matches_the_composed_transform_exactly(self) -> None:
        """Not merely 'different', but the specific number.

        `assertNotAlmostEqual` elsewhere in this class survives a mutation that
        applies *some* transform. This pins the arithmetic against
        `overhang_area` called directly with `printer @ alignment`, which is the
        same composition the candidate is measured under.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            source = _stepped_source(directory)
            got = self._composed(directory)
            expected = M.overhang_area(
                str(source), threshold=-0.73, bed_z=0.0,
                transform=(np.array(_printer_rotate_x_90())
                           @ np.array(_align_rotate_z_270_and_move())))
            self.assertIsNotNone(got)
            self.assertAlmostEqual(expected, got[0], places=6)
            self.assertAlmostEqual(100.0, got[0], places=6,
                                   msg="the measured value this fixture was "
                                       "chosen for; see the four it is not")

    def test_reversing_the_composition_order_is_a_different_answer(self) -> None:
        """The second fixture D15 requires, and the reason it specifies a
        *non-commuting* pair.

        The alignment turns about Z and translates; the printer turns about X.
        Different axes, so the rotation blocks themselves do not commute, and
        `printer @ alignment` is a different transform from `alignment @
        printer` rather than the same rotation with a different offset. The
        order is not a convention: `alignment_transform` maps out of the
        source's own frame and the printer matrix maps out of the job's, so the
        reverse product rotates coordinates that are not in the job's frame yet.
        """
        alignment = np.array(_align_rotate_z_270_and_move())
        printer = np.array(_printer_rotate_x_90())
        self.assertFalse(np.allclose(printer[:3, :3] @ alignment[:3, :3],
                                     alignment[:3, :3] @ printer[:3, :3]),
                         "this fixture is only evidence if the rotations "
                         "themselves do not commute")
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            source = _stepped_source(directory)
            got = self._composed(directory)
            reversed_order = M.overhang_area(
                str(source), threshold=-0.73, bed_z=0.0,
                transform=alignment @ printer)
            self.assertIsNotNone(got)
            self.assertNotAlmostEqual(
                reversed_order, got[0], places=3,
                msg="source alignment then printer, in that order")

    def test_dropping_either_half_of_the_composition_is_visible(self) -> None:
        """The two mutations a single composed number could still hide.

        Measuring under the printer transform alone, or the alignment alone,
        both read 300.0 mm2 on this fixture against the composition's 100.0 --
        so neither half can be removed without one of these failing. Asserted
        against freshly measured values rather than the constants, so the test
        stays true if the mesh library's tessellation moves.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            source = _stepped_source(directory)
            got = self._composed(directory)
            self.assertIsNotNone(got)
            for name, transform in (
                    ("printer only, source alignment dropped",
                     np.array(_printer_rotate_x_90())),
                    ("alignment only, printer transform dropped",
                     np.array(_align_rotate_z_270_and_move()))):
                with self.subTest(dropped=name):
                    self.assertNotAlmostEqual(
                        M.overhang_area(str(source), threshold=-0.73, bed_z=0.0,
                                        transform=transform),
                        got[0], places=3, msg=name)

    def test_the_alignment_translation_is_not_decorative(self) -> None:
        """A rotation-only alignment reads 200.0 mm2 here against the real
        pair's 100.0, so an implementation that composed the rotation blocks and
        discarded the offset would be caught."""
        rotation_only = [row[:] for row in _align_rotate_z_270_and_move()]
        for row in rotation_only[:3]:
            row[3] = 0.0
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            source = _stepped_source(directory)
            got = self._composed(directory)
            self.assertIsNotNone(got)
            self.assertNotAlmostEqual(
                M.overhang_area(str(source), threshold=-0.73, bed_z=0.0,
                                transform=(np.array(_printer_rotate_x_90())
                                           @ np.array(rotation_only))),
                got[0], places=3,
                msg="the alignment's translation reached the composition")

    def test_the_source_alignment_alone_changes_the_answer(self) -> None:
        """Isolates the alignment from the printer transform.

        With the printer at identity the scope's alignment is the only thing
        moving the geometry, so a composition that dropped
        `alignment_transform` reports the authored area here.

        The alignment is the flip and the source is the cone, deliberately: the
        Z-rotation alignment the composition fixtures use leaves every face
        normal's Z component alone, so on its own -- with no printer rotation
        after it -- it is invisible to an overhang measurement and would make
        this test pass whatever the code did.
        """
        rule = {"downward_normal_z_max": -0.73, "bed_z_mm": 0.0,
                "model_to_printer_matrix": "identity"}
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            _asymmetric_source(directory)
            plain = cli._inherited_overhang(directory, _modify(), rule)
            aligned = cli._inherited_overhang(
                directory, _modify(_flip_x_180()), rule)
            self.assertIsNotNone(plain)
            self.assertIsNotNone(aligned)
            self.assertNotAlmostEqual(
                plain[0], aligned[0], places=3,
                msg="the edit scope's alignment_transform reached the "
                    "composition or it did not")

    def test_identity_everywhere_measures_the_authored_frame(self) -> None:
        """The common path, unchanged and cheap.

        A job declaring no reorientation and a scope declaring no alignment must
        get exactly the number this returned before the composition existed, or
        every `MODIFY` ceiling in the repository moved for a declaration nobody
        made.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            source = _asymmetric_source(directory)
            got = cli._inherited_overhang(
                directory, _modify(),
                {"downward_normal_z_max": -0.73, "bed_z_mm": 0.0,
                 "model_to_printer_matrix": PL.IDENTITY_TRANSFORM})
            self.assertIsNotNone(got)
            self.assertAlmostEqual(
                M.overhang_area(str(source), threshold=-0.73, bed_z=0.0),
                got[0], places=6)


class ItFailsClosedPerSourceRatherThanGuessingTest(unittest.TestCase):
    """A frame it cannot resolve is a named gap, never a silent identity."""

    def test_an_unreadable_source_still_yields_a_named_partial_ceiling(self) -> None:
        """The fifth fixture D15 requires: D18's controlled partial behaviour
        survives the composition.

        Two declared scopes, one file on disk. The allowance the readable source
        is entitled to must still be credited -- a zero is not more measured
        than a partial sum, and it is wrong in the direction that fails a
        correct part -- and the gap must still be named.
        """
        second = P.SourceArtifact(artifact_id="drawer", path="drawer.stl",
                                  format="STL", classification="USABLE_MESH")
        pair = _project(source_mode="MODIFY",
                        source_artifacts=(ARTIFACT, second),
                        edit_scopes=(_scope(), P.EditScope(
                            artifact_id="drawer", region="the pocket",
                            region_box={"min": [0.0, 0.0, 0.0],
                                        "max": [5.0, 5.0, 5.0]})))
        rule = {"downward_normal_z_max": -0.73, "bed_z_mm": 0.0,
                "model_to_printer_matrix": _flip_x_180()}
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            _asymmetric_source(directory)
            partial = cli._inherited_overhang(directory, pair, rule)
            self.assertIsNotNone(partial, "one unreadable source must not zero "
                                          "the allowance measured on the other")
            self.assertGreater(partial[0], 0.0)
            self.assertIn("1 of 2 supplied artifacts", partial[1])
            self.assertIn("This ceiling is partial", partial[1])
            self.assertIn("drawer.stl", partial[1])

    def test_an_unusable_alignment_names_the_gap_and_credits_nothing(self) -> None:
        """Falling back to identity would credit the candidate an allowance
        measured somewhere the source does not sit, which passes a part that
        should fail."""
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            _asymmetric_source(directory)
            got = cli._inherited_overhang(
                directory, _modify([[1.0, 0.0], [0.0, 1.0]]),
                {"downward_normal_z_max": -0.73, "bed_z_mm": 0.0,
                 "model_to_printer_matrix": "identity"})
            self.assertIsNone(got, "the only declared source could not be "
                                   "placed, so there is nothing to credit")

    def test_an_unusable_rule_matrix_credits_nothing(self) -> None:
        """The preflight refuses this contract, so this is the belt to that
        brace. What it may not do is measure the authored frame and call the
        result an allowance."""
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            _asymmetric_source(directory)
            mirror = [[-1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0],
                      [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]
            self.assertIsNone(cli._inherited_overhang(
                directory, _modify(),
                {"downward_normal_z_max": -0.73, "bed_z_mm": 0.0,
                 "model_to_printer_matrix": mirror}))


class OneTransformConventionTest(unittest.TestCase):
    """Three declarations of a placement, one predicate deciding all three."""

    def test_the_contract_reads_its_orientation_through_the_shared_resolver(self) -> None:
        contract = ThePlanAndTheContractMayNotDisagreeTest._contract(
            _orientation(_flip_x_180()), _flip_x_180())
        self.assertTrue(np.array_equal(CT.as_transform(_flip_x_180()),
                                       CT.printer_transform(contract)))

    def test_identity_resolves_rather_than_refusing(self) -> None:
        self.assertTrue(np.array_equal(np.eye(4), CT.as_transform("identity")))
        self.assertTrue(np.array_equal(np.eye(4),
                                       CT.as_transform(PL.IDENTITY_TRANSFORM)))

    def test_anything_weaker_than_a_rigid_transform_is_none(self) -> None:
        """A mesh may not be moved by a scale, a shear, a mirror or a
        projection, and `screening` bounds a part by its transformed corners --
        which is conservative for an affine map and wrong in the unsafe
        direction for a projective one."""
        mirror = [[-1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0],
                  [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]
        scale = [[2.0, 0.0, 0.0, 0.0], [0.0, 2.0, 0.0, 0.0],
                 [0.0, 0.0, 2.0, 0.0], [0.0, 0.0, 0.0, 1.0]]
        projective = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0],
                      [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 1.0, 1.0]]
        nan = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0],
               [0.0, 0.0, float("nan"), 0.0], [0.0, 0.0, 0.0, 1.0]]
        for matrix in (mirror, scale, projective, nan, "sideways", None, 7):
            with self.subTest(matrix=matrix):
                self.assertIsNone(CT.as_transform(matrix))

    def test_a_rotation_survives_the_round_trip_it_is_hashed_through(self) -> None:
        """`EditScope.canonical_alignment_transform` rounds to six places for
        hashing, and an orthonormality check at `atol=1e-6` is close enough to
        that to be worth pinning: a declared rotation that validated must not
        become unresolvable once it has been through the canonical spelling."""
        angle = math.radians(37.0)
        rotation = [[1.0, 0.0, 0.0, 0.0],
                    [0.0, math.cos(angle), -math.sin(angle), 3.5],
                    [0.0, math.sin(angle), math.cos(angle), 0.0],
                    [0.0, 0.0, 0.0, 1.0]]
        scope = _scope(rotation)  # noqa: F841 - read through both spellings below
        self.assertIsNotNone(CT.as_transform(scope.alignment_transform))
        self.assertIsNotNone(
            CT.as_transform(scope.canonical_alignment_transform()))


if __name__ == "__main__":
    unittest.main()
