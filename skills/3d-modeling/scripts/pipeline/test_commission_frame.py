#!/usr/bin/env python3
"""D15, the half that reaches a verdict: three checks measured the wrong frame.

`screening._bed_screen` was fixed at `fb18e31`. A review of that fix found the
same defect in three *contract checks*, and a check outranks a screen: a screen
escalates, a check decides. All three read `ctx.bounds[0][2]` -- the lowest Z of
the mesh as authored -- while the contract froze a `model_to_printer_matrix`
saying the part prints in some other orientation. `docs/defects.md` records the
measurement under D15:

    commission 'seated'   -> PASS      (expected 0.0, measured 0.0)
    screening 'bed-plane' -> ANOMALY   ("14.00 mm below the bed in the
                                         printer frame")

One receipt, two contradictory answers, and the one that decides the outcome is
wrong. `overhang` is worse than contradictory: `designer_toolkit.metrics.
overhang_area` documents a `transform=` parameter *for exactly this*, and
`commission` did not pass it while `cli` copies the plan support rule's
`downward_normal_z_max` and `bed_z_mm` and drops its `model_to_printer_matrix`.
On this file's cone (`sections=64`) that is 0.0 mm2 authored against
1293.3 mm2 in the declared frame -- a
PASS against a plan ceiling, about a frame the job did not declare.

**One reading of the orientation field, not a third.** The screening fix reached
for `team_preflight.is_finite_rigid` rather than writing a fourth shape check,
after a review found the weakest of four authorities deciding the verdict. Doing
the same thing again one file over would be the same mistake with a different
file name, so `contract.printer_transform` and `contract.declared_bed_z` live
where the field lives, and `screening` and `commission` both call them.
"""
from __future__ import annotations

import unittest

import trimesh

from . import commission as C
from . import contract as CT
from . import screening as SC
from .contract import Contract, Feature


def _contract(**over) -> Contract:
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


def _flip_x_180() -> list[list[float]]:
    """Turns the part over: z -> -z, y -> -y. An ordinary print decision."""
    return [[1.0, 0.0, 0.0, 0.0], [0.0, -1.0, 0.0, 0.0],
            [0.0, 0.0, -1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]


class _Ctx:
    """A real mesh: these checks measure faces, not only bounds."""

    def __init__(self, low_z: float = 0.0) -> None:
        box = trimesh.creation.box(extents=(10.0, 10.0, 20.0))
        box.apply_translation((5.0, 5.0, 10.0 + low_z))
        self.normalized = box

    @property
    def bounds(self):
        return self.normalized.bounds

    @property
    def extents(self):
        return self.normalized.extents


class _ConeCtx:
    """Flat base, conical top. Apex-down it is entirely unsupported."""

    def __init__(self) -> None:
        self.normalized = trimesh.creation.cone(radius=20.0, height=5.0,
                                                sections=64)

    @property
    def bounds(self):
        return self.normalized.bounds

    @property
    def extents(self):
        return self.normalized.extents


class OneReadingOfTheOrientationTest(unittest.TestCase):
    """The field is read where the field lives, and by both callers."""

    def test_the_contract_resolves_its_own_transform(self) -> None:
        self.assertIsNotNone(CT.printer_transform(_contract()))
        self.assertIsNone(
            CT.printer_transform(_contract(model_to_printer_matrix="sideways")))

    def test_a_projective_matrix_is_refused_where_the_field_is_read(self) -> None:
        """The hole the screening fix opened and closed: the eight-corner bound
        is conservative for affine transforms only, and every shape check in
        this repo accepts a projective matrix."""
        projective = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0],
                      [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 1.0, 1.0]]
        self.assertIsNone(
            CT.printer_transform(_contract(model_to_printer_matrix=projective)))

    def test_a_bed_height_must_be_a_finite_number(self) -> None:
        for bed_z in ("the table", None, True, float("nan")):
            with self.subTest(bed_z_mm=bed_z):
                self.assertIsNone(CT.declared_bed_z(_contract(bed_z_mm=bed_z)))
        self.assertEqual(5.0, CT.declared_bed_z(_contract(bed_z_mm=5.0)))

    def test_screening_reads_the_field_through_the_same_function(self) -> None:
        """Two readings of one field is how one receipt came to hold two
        answers. A review found the weakest of four authorities over this
        question deciding the verdict; a fifth in another file is the same
        mistake renamed."""
        import inspect
        source = inspect.getsource(SC)
        self.assertIn("printer_transform", source)
        # By import, not by mention: the docstring explains that this module
        # used to call `is_finite_rigid` directly, and a substring search on
        # source text cannot tell an explanation from a call.
        self.assertNotIn("import is_finite_rigid", source)
        self.assertNotIn("is_finite_rigid(", source,
                         "screening resolves the matrix through the contract, "
                         "not by re-deriving what counts as a usable one")


class TheSeatedCheckNamesItsFrameTest(unittest.TestCase):
    """`seated` is a PASS/FAIL that reaches the verdict."""

    def test_a_part_on_the_bed_in_both_frames_passes(self) -> None:
        self.assertEqual("PASS", C._seated_check(_Ctx(), _contract()).result)

    def test_a_flip_that_buries_the_part_fails(self) -> None:
        """Authored z 0..20 sits on the bed. Printed upside down it is
        z -20..0, and this returned PASS at measured 0.0."""
        self.assertEqual("FAIL", C._seated_check(
            _Ctx(), _contract(model_to_printer_matrix=_flip_x_180())).result)

    def test_a_flip_that_seats_the_part_passes(self) -> None:
        """The other direction, or the fix is a way of always failing."""
        self.assertEqual("FAIL", C._seated_check(_Ctx(-20.0), _contract()).result)
        self.assertEqual("PASS", C._seated_check(
            _Ctx(-20.0),
            _contract(model_to_printer_matrix=_flip_x_180())).result)

    def test_the_declared_bed_height_is_what_it_measures_against(self) -> None:
        self.assertEqual("FAIL",
                         C._seated_check(_Ctx(), _contract(bed_z_mm=5.0)).result)

    def test_it_agrees_with_the_screen_on_the_same_job(self) -> None:
        """The defect was two answers in one receipt. This is the assertion
        that they are one answer, on the case that separated them."""
        contract = _contract(model_to_printer_matrix=_flip_x_180())
        self.assertEqual("FAIL", C._seated_check(_Ctx(), contract).result)
        self.assertEqual("ANOMALY",
                         SC._bed_screen(_Ctx(), contract)["result"])

    def test_an_unusable_declaration_fails_rather_than_measuring_the_model(self) -> None:
        """A check may not fall back to the authored frame and PASS -- that is
        the defect with an extra step, in the half that decides."""
        for over in ({"model_to_printer_matrix": "sideways"},
                     {"model_to_printer_matrix": [[1.0, 0.0], [0.0, 1.0]]},
                     {"model_to_printer_matrix": None},
                     {"bed_z_mm": float("nan")}):
            with self.subTest(**over):
                row = C._seated_check(_Ctx(), _contract(**over))
                self.assertEqual("FAIL", row.result)
                self.assertEqual("ORIENTATION_UNUSABLE", row.error_code)


class TheBedContactIsMeasuredWhereThePartLandsTest(unittest.TestCase):
    """Contact area at the part's own lowest plane is a different face."""

    def test_contact_area_follows_the_declared_orientation(self) -> None:
        upright = C._bed_contact(_Ctx(), _contract())
        flipped = C._bed_contact(
            _Ctx(), _contract(model_to_printer_matrix=_flip_x_180()))
        self.assertGreater(upright, 0.0)
        self.assertGreater(flipped, 0.0,
                           "the flipped part lands on its other face; measuring "
                           "the authored plane would find nothing on the bed")

    def test_an_unusable_matrix_measures_nothing_rather_than_zero(self) -> None:
        """`0.0` **is** the guess, and the first version of this test asserted
        it under a name saying it wasn't.

        Zero contact area is a legitimate measurement -- it is what a part
        touching the bed nowhere returns -- so a refusal spelled `0.0` is
        indistinguishable from one, and `_feature_check` published it as
        `ran: true, status: MEASURED, reason: "measured"`. A review measured the
        consequence: the fabricated row kept `coverage.fraction` at 1.0, so the
        gate that exists because three SKIPPED checks went uncounted was
        defeated by a row claiming to have been measured.
        """
        self.assertIsNone(C._bed_contact(
            _Ctx(), _contract(model_to_printer_matrix="sideways")))

    def test_a_refused_contact_area_is_not_counted_as_covered(self) -> None:
        """The consequence, asserted where it bites rather than inferred."""
        feature = Feature(feature_id="bed-footprint", kind="bed_contact",
                          provenance="STATED",
                          expectation={"value_mm2": 0.4},
                          tolerance={"abs": 1.0},
                          verified_by="the bed-contact measurement")
        row = C._feature_check(_Ctx(), feature, None, None,
                               _contract(model_to_printer_matrix="sideways"))
        self.assertFalse(row.ran, "an unmeasured check may not count as covered")
        self.assertEqual("UNAVAILABLE", row.status)
        self.assertNotEqual("PASS", row.result,
                            "with a small enough declared area, a fabricated "
                            "0.0 passed this outright")


class ThePreflightRefusesWhatTheChecksRefuseTest(unittest.TestCase):
    """`preflight` exists so a job is refused before geometry is paid for.

    It accepted a mirror, a projective matrix, a uniform scale and a NaN bed
    height that every placement check refuses -- so those four paid for the
    whole build and then landed on *"the geometry does not match its
    contract"*, which is a claim about a comparison that never happened.
    """

    def _problems(self, **over) -> list[str]:
        """`preflight` validates the whole contract, so the fixture has to be a
        contract it would otherwise accept -- `backend="none"` raises before
        orientation is ever reached, and a test failing there would be testing
        its own helper."""
        import dataclasses
        contract = dataclasses.replace(_contract(**over), backend="authored",
                                       template="authored",
                                       source={"kind": "authored"})
        return CT.preflight(contract, known_checks=frozenset())

    def test_an_unusable_matrix_is_refused_before_the_build(self) -> None:
        projective = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0],
                      [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 1.0, 1.0]]
        mirror = [[-1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0],
                  [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]
        for matrix in (projective, mirror, "sideways"):
            with self.subTest(matrix=matrix):
                self.assertTrue(
                    [p for p in self._problems(model_to_printer_matrix=matrix)
                     if "model_to_printer_matrix" in p])

    def test_an_unusable_bed_height_is_refused_before_the_build(self) -> None:
        for bed_z in (float("nan"), "the table", None):
            with self.subTest(bed_z_mm=bed_z):
                self.assertTrue([p for p in self._problems(bed_z_mm=bed_z)
                                 if "bed_z_mm" in p])

    def test_a_usable_declaration_is_not_complained_about(self) -> None:
        """Or the clause is a way of refusing every job."""
        self.assertEqual([], [p for p in self._problems()
                              if "orientation" in p or "bed_z" in p])


class TheOverhangIsScreenedInPrintOrientationTest(unittest.TestCase):
    """`overhang_area` documents `transform=` for exactly this."""

    def _feature(self) -> Feature:
        return Feature(feature_id="unsupported", kind="overhang",
                       provenance="STATED",
                       expectation={"max_area_mm2": 50.0,
                                    "downward_normal_z_max": -0.5,
                                    "bed_z_mm": 0.0},
                       tolerance={"abs": 0.0},
                       verified_by="the overhang screen")

    def test_commission_passes_the_declared_transform(self) -> None:
        """Exercised through the check rather than around it: the arithmetic was
        never the problem, the parameter was, and a test of the endpoints cannot
        see a missing wire."""
        cone = _ConeCtx()
        upright = C._feature_check(cone, self._feature(), None, None, _contract())
        flipped = C._feature_check(
            cone, self._feature(), None, None,
            _contract(model_to_printer_matrix=_flip_x_180()))
        self.assertEqual("PASS", upright.result)
        self.assertEqual("FAIL", flipped.result,
                         "apex-down the cone is unsupported, against the same "
                         "ceiling either way")
        self.assertGreater(flipped.measured, upright.measured)

    def test_omitting_the_contract_does_not_measure_the_authored_frame(self) -> None:
        """The refusal used to be guarded by `contract is not None`, so a caller
        that forgot the argument skipped it and measured the model frame: PASS
        at 0.0 mm2 where supplying the contract gives FAIL at 1293 mm2, with a
        reason naming no frame. That is D15 reachable by forgetting an optional
        argument."""
        row = C._feature_check(_ConeCtx(), self._feature(), None, None)
        self.assertNotEqual("PASS", row.result,
                            "no contract means no known frame, and a screen "
                            "that does not know its frame may not clear a part")

    def test_an_unusable_matrix_makes_the_overhang_unavailable(self) -> None:
        row = C._feature_check(_ConeCtx(), self._feature(), None, None,
                               _contract(model_to_printer_matrix="sideways"))
        self.assertNotEqual("PASS", row.result)


class TheCommissionPacketCarriesTheRowSchemaTest(unittest.TestCase):
    """A designer may read only `authorized_inputs` and must satisfy
    `proposal_api` exactly. Both are possible only if the API says what a row owes.

    **This proves the packet states which fields each kind requires, because it
    fails whenever the rendered association differs from `PROPOSABLE` in any
    direction** -- a kind dropped, a kind invented, or a field attached to the
    wrong kind. That is not a hypothetical `Y`. Six of the eight field names
    (`d_mm`, `enclosing_d_mm`, `size_mm`, `value_mm2`, `z_from`, `z_to`)
    appeared nowhere in the packet, while the *kinds* were already interpolated
    from the same whitelist. So the packet named five proposable kinds and never
    said that a `section_area` row owes `at` and `value_mm2`.

    None of those names is in an authorized file either. Measured on a real
    commission: the designer read `acceptance.py` to find the row schema, which
    is the only way to obey one instruction and a breach of the other.

    **The association is the claim, so the association is what is asserted.** An
    earlier form of this test joined every value of `PROPOSAL_API` into one
    string and asked whether each field name appeared *somewhere* in it. That
    instrument passes while asking a different question: `section_area` could
    lose `value_mm2` and stay green for as long as `bed_contact` still listed
    it, and the packet would once again fail to tell a designer what a
    *particular* row owes. Presence in the packet was never the property; the
    binding of a field to its kind is. The discriminating mutation is exactly
    that: move a field off its owning kind while leaving it present elsewhere in
    the rendered text. The old form passes that mutation and this one fails it,
    which is the whole difference between the two.

    Only `PROPOSAL_API["features"]` is read, because that is the entry that
    carries the schema; scanning the whole packet is what let an unrelated
    sentence satisfy the assertion.

    Compared against `PROPOSABLE` itself rather than a list written here, because
    a list written here is the same defect one release later: `PROPOSABLE` is the
    authority on what a row may carry, and a second spelling of it in a test is a
    second authority over the same question. Asserting the whole mapping at once
    also subsumes the separate "every kind is named" check this class used to
    carry: two dicts are equal only if their key sets are.
    """

    @staticmethod
    def _rendered_associations(features: str) -> dict[str, list[str]]:
        """The `kind -> field, field` clauses the packet actually renders.

        Deliberately strict. If the rendering changes shape this returns
        something that does not match `PROPOSABLE` and the test fails, which is
        the right outcome: a designer parses this text by eye, and a shape the
        test cannot read is a shape a reader cannot either.
        """
        body = features.partition("requires: ")[2]
        body = body.partition(". A row may not carry")[0]
        out: dict[str, list[str]] = {}
        for clause in body.split(";"):
            kind, arrow, fields = clause.partition(" -> ")
            if not arrow:
                continue
            out[kind.strip()] = [f.strip() for f in fields.split(",") if f.strip()]
        return out

    def test_the_packet_states_which_fields_each_kind_requires(self) -> None:
        from . import acceptance as ACC
        from .cli import PROPOSAL_API

        rendered = self._rendered_associations(PROPOSAL_API["features"])
        self.assertEqual(
            {kind: sorted(fields) for kind, fields in ACC.PROPOSABLE.items()},
            {kind: sorted(fields) for kind, fields in rendered.items()},
            "the commission packet does not say which fields each proposable "
            "kind requires, so a designer told to read only its authorized "
            "inputs cannot learn what a *particular* row owes. It either "
            "guesses or reads acceptance.py, and acceptance.py is not "
            "authorized")


if __name__ == "__main__":
    unittest.main()
