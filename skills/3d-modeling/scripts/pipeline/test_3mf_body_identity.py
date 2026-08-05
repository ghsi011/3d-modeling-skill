#!/usr/bin/env python3
"""A body inside a 3MF object gets the same handle a loose mesh does.

`f9b7c61` gave a body a handle and wired it into `_diagnose_mesh` only. Its
review said so plainly, and `ROADMAP.md` records it: `_diagnose_step` and
`_diagnose_3mf` still reported a bare count, *"so the two formats that actually
carry assembly structure are as blocked as they were."*

3MF is the one that matters most for Release 5's "selected components within
source assemblies" -- it is the format with objects, components and build items,
so a job selecting a component in a supplied assembly is selecting inside a 3MF.
And the mesh is already in hand: `_mesh_facts` runs per object and computes
`mesh.split(only_watertight=False)` for its count, so the handles cost the split
that was already paid.

**STEP is deliberately not here, and not because it is harder.** A B-rep solid
has no triangles until something tessellates it, so a handle over its
tessellation is a handle over `BREP_READ_LINEAR_DEFLECTION` as much as over the
shape -- a different kind of identity wearing the same name, which is the class
of claim this repository keeps having to retract. It needs its own slice that
says what the handle is *of*, and `docs/defects.md` carries that rather than this
file implying the format is covered.
"""
from __future__ import annotations

import unittest

import numpy as np
import trimesh

from . import diagnose as D


def _two_boxes():
    """Two disconnected bodies whose split order is not their digest order."""
    left = trimesh.creation.box(extents=(3.0, 4.0, 5.0))
    right = trimesh.creation.box(extents=(4.0, 5.0, 6.0))
    right.apply_translation((30.0, 0.0, 0.0))
    return trimesh.util.concatenate([left, right])


class AnObjectNamesEveryBodyItCountedTest(unittest.TestCase):
    """The count was the whole answer, and a count cannot be referenced."""

    def test_the_facts_carry_one_handle_per_body(self) -> None:
        import mesh_io
        facts = D._mesh_facts(_two_boxes())
        self.assertEqual(facts["bodies"], len(facts["body_identities"]),
                         "a count and a list that disagree are two answers to "
                         "how many bodies this object has")
        self.assertEqual(
            [row["body_sha256"] for row in mesh_io.body_identities(_two_boxes())],
            [row["body_sha256"] for row in facts["body_identities"]],
            "and they are the same handles a loose mesh of this geometry gets, "
            "or a body would have two identities depending on its container")

    def test_a_single_body_object_gets_one_row(self) -> None:
        facts = D._mesh_facts(trimesh.creation.box(extents=(10.0, 10.0, 10.0)))
        self.assertEqual(1, len(facts["body_identities"]))
        self.assertAlmostEqual(1000.0, facts["body_identities"][0]["volume_mm3"],
                               places=3)

    def test_an_empty_object_names_no_bodies(self) -> None:
        facts = D._mesh_facts(trimesh.Trimesh(
            vertices=np.zeros((0, 3)), faces=np.zeros((0, 3), dtype=np.int64)))
        self.assertEqual(0, facts["bodies"])
        self.assertEqual([], facts["body_identities"])

    def test_the_split_is_paid_for_once(self) -> None:
        """`_mesh_facts` already splits to count. Splitting again for the
        handles would double the cost of the most expensive thing it does.

        Observed at the call, not counted in the source. The first version of
        this grepped `_mesh_facts` for `split(only_watertight=False)` and
        asserted it appeared once -- which a mutation dropping `bodies=bodies`
        survived, because the second split happens *inside* `body_identities`
        and leaves no mark in this function's text. Counting occurrences of a
        call cannot see a call made somewhere else.
        """
        import mesh_io
        seen = {}
        real = mesh_io.body_identities

        def recording(mesh, *, bodies=None):
            seen["bodies"] = bodies
            return real(mesh, bodies=bodies)

        mesh_io.body_identities = recording
        try:
            D._mesh_facts(_two_boxes())
        finally:
            mesh_io.body_identities = real
        self.assertIsNotNone(seen.get("bodies"),
                             "the split `_mesh_facts` already computed is handed "
                             "over; without it `body_identities` splits again")
        self.assertEqual(2, len(seen["bodies"]))


class TheHandleIsTheSameOneEverywhereTest(unittest.TestCase):
    """A body's identity may not depend on which reader found it."""

    def test_a_loose_mesh_and_a_3mf_object_agree(self) -> None:
        import mesh_io
        mesh = _two_boxes()
        loose = [row["body_sha256"] for row in mesh_io.body_identities(mesh)]
        inside = [row["body_sha256"]
                  for row in D._mesh_facts(mesh)["body_identities"]]
        self.assertEqual(loose, inside)


if __name__ == "__main__":
    unittest.main()
