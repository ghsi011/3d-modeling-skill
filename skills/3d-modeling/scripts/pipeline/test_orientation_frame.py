#!/usr/bin/env python3
"""D15: the bed screen answered about a frame the job never declared.

`docs/defects.md` filed D15 as "orientation is declared, validated, frozen, and
read by nothing" -- the third instance of a field the schema takes seriously and
no code consumes. Re-measuring it made it something else.

`model_to_printer_matrix` occurs in exactly four places: three shape checks and
a selftest constant. It is **never applied to geometry**. And
`screening._bed_screen` decides whether the part reaches below the bed from
`ctx.bounds[0][2]` -- the lowest Z of the mesh *as authored* -- with a signature
of `(ctx)` that cannot receive the contract, so it could not see the declared
orientation even in principle. Measured before this file was written:

    authored z 0..20, declared printed rotated to z -20..0  ->  bed-plane: CLEAR

That is not an unused field. It is a detector issuing a clean verdict about a
frame the job did not declare it was working in, which `AGENTS.md` requires to
fail closed immediately rather than wait for the capability that would make the
claim true.

**So the fix is a claim about the claim.** Either the screen measures in the
declared printer frame, or it names the frame it measured and may not say
`CLEAR` for the other one. "The lowest point of the authored mesh" is a weaker
statement than "the part does not go below the bed", and a weaker method may not
issue a stronger claim.

**This is not the only such path, and saying so was the first version's own
over-claim.** A review found three more, all in `commission.py`, all reading
`ctx.bounds[0][2]` in the model frame, and all of them *contract checks* that
reach the commissioning verdict rather than screens that only escalate:

* `seated` -- "Part sits on the bed", bed hard-coded to 0.0, naming no frame,
  and it can PASS. On the very case this file tests, `commission` returns PASS
  while `screening` returns ANOMALY, so the receipt now carries two
  contradictory answers and the stronger one is wrong;
* `bed_contact` -- measures contact area at the part's own lowest plane, which
  under a declared rotation is a different face;
* `overhang` -- calls `metrics.overhang_area` with no `transform=`, though that
  function documents the parameter for exactly this, and `cli` drops the plan
  rule's `model_to_printer_matrix` while copying its other two fields. Measured
  on a cone: 0.0 mm2 authored, 1294.4 mm2 in the declared frame.

`docs/defects.md` D15 records them as open. They are a separate slice because
each is a different measurement, not because they are less urgent -- and until
that slice lands, `AGENTS.md`'s "stop dependent work until a regression test
proves the repair" is still live on this claim path.

Bridging and strength direction are orientation-dependent too and nothing
measures them at all.
"""
from __future__ import annotations

import unittest

import numpy as np

from . import screening as SC
from .contract import Contract


def _contract(**over) -> Contract:
    """The smallest contract `_bed_screen` needs to know the frame."""
    base = dict(model_to_printer_matrix="identity", bed_z_mm=0.0)
    base.update(over)
    return Contract(job_id="d15", template="none", template_version="1",
                    domain_id="none", backend="none", parameters={},
                    features=(), expected_bbox_mm=None, bbox_tolerance_mm=0.5,
                    expected_bodies=1, orientation=dict(base),
                    material={"process": "FDM", "material": "PLA"},
                    nozzle={"diameter_mm": 0.4}, printer="none",
                    modifiers=(), minimum_coverage=1.0, step_required=False,
                    consequence="INCONSEQUENTIAL",
                    updated_utc="1970-01-01T00:00:00Z")


class _Ctx:
    """Only what the bed screen touches."""

    def __init__(self, low_z: float, high_z: float) -> None:
        self.bounds = np.array([[0.0, 0.0, low_z], [10.0, 10.0, high_z]])


def _rotate_x_180() -> list[list[float]]:
    """Turns the part over: z -> -z, y -> -y. A real print decision."""
    return [[1.0, 0.0, 0.0, 0.0], [0.0, -1.0, 0.0, 0.0],
            [0.0, 0.0, -1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]


class TheBedScreenKnowsWhichFrameItMeasuredTest(unittest.TestCase):
    """The false-clean-verdict path, closed."""

    def test_a_part_on_the_bed_as_authored_and_printed_is_clear(self) -> None:
        row = SC._bed_screen(_Ctx(0.0, 20.0), _contract())
        self.assertEqual("CLEAR", row["result"])

    def test_a_part_below_the_bed_as_authored_is_still_an_anomaly(self) -> None:
        row = SC._bed_screen(_Ctx(-5.0, 15.0), _contract())
        self.assertEqual("ANOMALY", row["result"])

    def test_a_rotation_that_puts_the_part_under_the_bed_is_caught(self) -> None:
        """The defect. Authored z 0..20 is clear; printed upside down it is
        z -20..0, and the screen used to report CLEAR because it never looked
        at the matrix the contract froze."""
        row = SC._bed_screen(
            _Ctx(0.0, 20.0),
            _contract(model_to_printer_matrix=_rotate_x_180()))
        self.assertEqual("ANOMALY", row["result"])
        self.assertIn("printer frame", row["reason"])

    def test_a_rotation_that_lifts_the_part_onto_the_bed_is_clear(self) -> None:
        """The other direction, or the fix would just be a way of always
        refusing. Authored z -20..0 reads as an anomaly; turned over it sits on
        the bed and is clear."""
        self.assertEqual("ANOMALY", SC._bed_screen(_Ctx(-20.0, 0.0),
                                                   _contract())["result"])
        row = SC._bed_screen(
            _Ctx(-20.0, 0.0),
            _contract(model_to_printer_matrix=_rotate_x_180()))
        self.assertEqual("CLEAR", row["result"])

    def test_the_declared_bed_height_is_the_one_it_measures_against(self) -> None:
        """`bed_z_mm` was validated and ignored the same way. A bed at 5 mm
        means a part whose lowest point is 2 mm is below it."""
        self.assertEqual("ANOMALY",
                         SC._bed_screen(_Ctx(2.0, 20.0),
                                        _contract(bed_z_mm=5.0))["result"])
        self.assertEqual("CLEAR",
                         SC._bed_screen(_Ctx(5.0, 20.0),
                                        _contract(bed_z_mm=5.0))["result"])

    def test_the_reason_names_the_frame_it_measured_in(self) -> None:
        """A receipt that says "lowest point 0.000 mm" without saying in which
        frame is the ambiguity this defect was made of."""
        for matrix in ("identity", _rotate_x_180()):
            with self.subTest(matrix=matrix):
                row = SC._bed_screen(_Ctx(0.0, 20.0),
                                     _contract(model_to_printer_matrix=matrix))
                self.assertIn("frame", row["reason"])


class ItFailsClosedRatherThanGuessingTest(unittest.TestCase):
    """A matrix it cannot apply may not become a clean verdict."""

    def test_an_unusable_matrix_refuses_rather_than_measuring_the_model(self) -> None:
        """`contract.preflight` refuses a malformed matrix before a run reaches
        here, so this is the belt to that braces. What it may not do is fall
        back to the authored frame and report CLEAR, which is the defect with an
        extra step."""
        wrong_shape = [[1.0, 0.0], [0.0, 1.0]]
        # A 4x4 whose *entries* are wrong is the case a shape check alone
        # misses, and the first version of this test had four malformed
        # matrices and not one of them among them.
        bad_entry = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0],
                     [0.0, 0.0, "sideways", 0.0], [0.0, 0.0, 0.0, 1.0]]
        not_finite = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0],
                      [0.0, 0.0, float("nan"), 0.0], [0.0, 0.0, 0.0, 1.0]]
        degenerate = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0],
                      [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 0.0]]
        for matrix in (wrong_shape, bad_entry, not_finite, degenerate,
                       "sideways", None, 7):
            with self.subTest(matrix=matrix):
                row = SC._bed_screen(
                    _Ctx(0.0, 20.0),
                    _contract(model_to_printer_matrix=matrix))
                self.assertEqual("ANOMALY", row["result"])

    def test_a_bed_height_that_is_not_a_number_refuses(self) -> None:
        """`bed_z_mm` decides what "below" means. Without a number there is no
        bed to be above, and defaulting it to zero would answer a question the
        job did not ask -- the same substitution the frame defect was made of."""
        for bed_z in ("the table", None, True, float("nan")):
            with self.subTest(bed_z_mm=bed_z):
                row = SC._bed_screen(_Ctx(0.0, 20.0), _contract(bed_z_mm=bed_z))
                self.assertEqual("ANOMALY", row["result"])

    def test_a_projective_matrix_cannot_be_bounded_by_its_corners(self) -> None:
        """The hole this fix opened while closing another one.

        The eight-corner minimum bounds the transformed mesh only for an
        *affine* transform. With a bottom row that is not [0,0,0,1], `w` is
        affine in the coordinates and can vanish *inside* the box while all
        eight corners sit far from zero -- so the corner bound reads **higher**
        than the part goes, and this returned CLEAR while naming the printer
        frame. Measured: corner bound +0.5 mm, true transformed minimum about
        -49999 mm.

        Every shape check in this repository accepts that matrix -- `preflight`,
        `cli._validate_orientation` and `project.validate` all check 4x4 of
        finite numbers and no more.
        """
        projective = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0],
                      [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 1.0, 1.0]]
        row = SC._bed_screen(_Ctx(-3.0, 1.0),
                             _contract(model_to_printer_matrix=projective))
        self.assertEqual("ANOMALY", row["result"])

    def test_a_mirror_is_not_a_print_orientation(self) -> None:
        """A determinant of -1 is a reflection. No printer can do it, and the
        corner bound would be measuring a part that cannot exist."""
        mirror = [[-1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0],
                  [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]
        self.assertEqual("ANOMALY",
                         SC._bed_screen(_Ctx(0.0, 20.0),
                                        _contract(model_to_printer_matrix=mirror)
                                        )["result"])

    def test_an_oblique_rotation_needs_all_eight_corners(self) -> None:
        """The slice's central geometric claim, which no fixture pinned.

        Every matrix in the first version of this file was diagonal or a pure
        translation, and for those the two bound corners give the same minimum
        as all eight -- a mutation replacing the enumeration with `[low, high]`
        survived the entire suite. A 45 degree rotation separates them: eight
        corners give -7.07 mm and two give 0.0, which is ANOMALY against CLEAR.
        """
        half = 2.0 ** -0.5
        tilt = [[1.0, 0.0, 0.0, 0.0], [0.0, half, half, 0.0],
                [0.0, -half, half, 0.0], [0.0, 0.0, 0.0, 1.0]]
        row = SC._bed_screen(_Ctx(0.0, 20.0),
                             _contract(model_to_printer_matrix=tilt))
        self.assertEqual("ANOMALY", row["result"])

    def test_bounds_that_are_not_finite_refuse_in_either_branch(self) -> None:
        """`NaN > 0.05` is False, so a NaN low point fell through to CLEAR on
        the identity path -- the same fail-open fixed for `bed_z_mm`, one
        operand over, and the two branches disagreed about one geometry."""
        for matrix in ("identity",
                       [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0],
                        [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]):
            with self.subTest(matrix=matrix):
                row = SC._bed_screen(_Ctx(float("nan"), 20.0),
                                     _contract(model_to_printer_matrix=matrix))
                self.assertEqual("ANOMALY", row["result"])

    def test_a_missing_bed_height_is_not_zero(self) -> None:
        """This file already argues that defaulting it "would answer a question
        the job did not ask -- the same substitution the frame defect was made
        of", and then the code defaulted it to 0.0."""
        contract = _contract()
        del contract.orientation["bed_z_mm"]
        # A part that WOULD be clear under a silent 0.0, or the two states are
        # indistinguishable: the first version used a part 50 mm below the
        # origin, which is an anomaly either way, and a mutation restoring the
        # default survived it.
        self.assertEqual("ANOMALY",
                         SC._bed_screen(_Ctx(0.0, 20.0), contract)["result"],
                         "no declared bed height is not a bed height of zero")
        self.assertEqual("CLEAR",
                         SC._bed_screen(_Ctx(0.0, 20.0), _contract())["result"],
                         "and the same part with 0.0 declared is clear, so the "
                         "refusal above is about the absence and not the part")

    def test_a_matrix_of_an_unexpected_type_does_not_raise(self) -> None:
        """`matrix == "identity"` raised `ValueError` on a numpy array, where
        `_printer_frame_low_z` promises `None` for anything it cannot apply.

        The expectation here is *not* a refusal: a numpy identity is a perfectly
        good rigid transform, and the repo's own predicate says so. Refusing it
        would be the mirror of the defect this file exists to close -- answering
        with the wrong verdict because of how the input was spelled.
        """
        row = SC._bed_screen(_Ctx(0.0, 20.0),
                             _contract(model_to_printer_matrix=np.eye(4)))
        self.assertEqual("CLEAR", row["result"])
        self.assertEqual("ANOMALY",
                         SC._bed_screen(_Ctx(0.0, 20.0),
                                        _contract(model_to_printer_matrix=np.zeros((2, 2)))
                                        )["result"])

    def test_a_translation_only_matrix_is_applied_too(self) -> None:
        """Not every print decision is a rotation; lifting a part off the bed
        is a translation, and the screen has to see that as well."""
        lifted = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0],
                  [0.0, 0.0, 1.0, -30.0], [0.0, 0.0, 0.0, 1.0]]
        self.assertEqual("ANOMALY",
                         SC._bed_screen(_Ctx(0.0, 20.0),
                                        _contract(model_to_printer_matrix=lifted)
                                        )["result"])


if __name__ == "__main__":
    unittest.main()
