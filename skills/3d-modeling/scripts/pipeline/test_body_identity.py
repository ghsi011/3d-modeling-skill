#!/usr/bin/env python3
"""A body in a supplied assembly gets a handle a declaration can hold.

`ROADMAP.md`'s Release 5 asks for "selected components within source
assemblies", and the commit before this one recorded why that could not be
built yet: `design-tool diagnose` reported `bodies` as a **count** and nothing
per body. A declaration selecting "the third body" would resolve to whatever
`trimesh.split` or OCC's solid enumeration returned that run -- a reference
meaning different geometry depending on something nobody declared, which is
[ADR 0003](../../../../docs/adr/0003-datum-provenance-and-authority.md)'s failure
moved from datums to bodies.

So identity first. A body's handle is a digest of its own geometry in canonical
form, which makes it a function of the shape and of nothing else: not of load
order, not of vertex order, not of which loader path produced the mesh.

**The canonicaliser is moved, not rewritten.** `preservation._ordered` already
made vertex and face order a function of geometry, for the same reason in a
different job -- a seeded sample plan is only reproducible if the thing it
indexes into is. Writing a second one here would be two authorities over one
question, so it moves to `mesh_io`, which `diagnose` and `preservation` both
already import.

That move has a safety property worth naming: `SAMPLE_PLAN_VERSION` is tied to
the ordering rule, and every review answer is bound to a plan digest, so a move
that changed the ordering by a hair would silently invalidate them. The first
version of this file claimed the L1 replay suite proved the move was pure. It
proves nothing of the kind -- see `TheOrderingRuleIsPinnedTest`, which is the
protection that does. Only one replay case carries a preservation receipt at
all, not four.

**Scope, stated because the ROADMAP names both formats.** `body_identities`
reaches `_diagnose_mesh` only. `_diagnose_step` and `_diagnose_3mf` still report
a bare count, so the two formats that actually carry assembly structure are as
blocked as they were. Selection over a STEP or 3MF assembly needs those two
wired next; this slice unblocks the mesh path and says so rather than implying
the blocker is cleared.
"""
from __future__ import annotations

import unittest

import numpy as np


def _two_boxes():
    """One mesh, two disconnected bodies, deliberately different sizes.

    These extents are chosen so that `split` returns them in an order that is
    NOT their digest order -- verified, not assumed. An arrangement where the
    two coincide makes the ordering rule untestable: a mutation removing the
    sort survived against the first version of this helper for exactly that
    reason.
    """
    import trimesh
    left = trimesh.creation.box(extents=(3.0, 4.0, 5.0))
    right = trimesh.creation.box(extents=(4.0, 5.0, 6.0))
    right.apply_translation((30.0, 0.0, 0.0))
    return trimesh.util.concatenate([left, right])


def _same_corners_different_triangulation():
    """Two bodies with identical vertices and different faces.

    Two exporters can triangulate one quad face either way round, which is a
    real difference in the mesh a job would build from -- and a handle taken
    over vertices alone would call them the same body.
    """
    import trimesh
    corners = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0],
                        [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]])
    return (trimesh.Trimesh(vertices=corners,
                            faces=np.array([[0, 1, 2], [0, 2, 3]]),
                            process=False),
            trimesh.Trimesh(vertices=corners,
                            faces=np.array([[1, 2, 3], [1, 3, 0]]),
                            process=False))


def _shuffled(mesh):
    """The same geometry presented in a different order.

    What a different loader path, a scene rather than a mesh, or a
    concatenation whose order came from a dict would hand over.
    """
    import trimesh
    rng = np.random.default_rng(11)
    vertex_order = rng.permutation(len(mesh.vertices))
    rank = np.empty(len(vertex_order), dtype=np.int64)
    rank[vertex_order] = np.arange(len(vertex_order), dtype=np.int64)
    faces = rank[np.asarray(mesh.faces, dtype=np.int64)]
    face_order = rng.permutation(len(faces))
    return trimesh.Trimesh(vertices=np.asarray(mesh.vertices)[vertex_order],
                           faces=faces[face_order], process=False)


class TheCanonicalFormIsSharedTest(unittest.TestCase):
    """One canonicaliser, in the module both readers already import."""

    def test_mesh_io_exposes_the_ordering_preservation_uses(self) -> None:
        import mesh_io
        from . import preservation as PR
        self.assertTrue(hasattr(mesh_io, "canonical_order"),
                        "the shared home is mesh_io: diagnose and preservation "
                        "both import it already")
        # And preservation reads it from there rather than keeping a copy. Two
        # implementations of one ordering is the duplicate authority this move
        # exists to avoid, and the one nobody runs is the one that drifts.
        #
        # Identity of *behaviour*, not of object: `_ordered` delegates lazily,
        # because binding the name at module scope pulled `trimesh` in eagerly
        # and took `import pipeline.preservation` from 0.07 s to 0.60 s. An
        # earlier version asserted `assertIs`, which is what made the expensive
        # import look required.
        mine = PR._ordered(_two_boxes())
        theirs = mesh_io.canonical_order(_two_boxes())
        np.testing.assert_array_equal(mine.vertices, theirs.vertices)
        np.testing.assert_array_equal(mine.faces, theirs.faces)

    def test_ordering_is_a_function_of_the_geometry(self) -> None:
        import mesh_io
        one = mesh_io.canonical_order(_two_boxes())
        other = mesh_io.canonical_order(_shuffled(_two_boxes()))
        np.testing.assert_allclose(one.vertices, other.vertices)
        np.testing.assert_array_equal(one.faces, other.faces)


class TheOrderingRuleIsPinnedTest(unittest.TestCase):
    """The golden this slice first declined to record, and was wrong to.

    The claim was that L1 replay proves the canonicaliser move was pure, because
    `SAMPLE_PLAN_VERSION` is tied to the ordering and every review answer is
    bound to a plan digest. A review reversed the face ordering outright --
    `np.lexsort(...)[::-1]` -- and L0, L0-heavy and L1 replay all stayed green.
    Three reasons, each sufficient:

    * `_seed_material` carries the *sentence* "vertices and faces
      lexicographically ordered before sampling", not the ordering. The plan
      digest is unmoved by an ordering change, so it cannot detect one.
    * `tools/replay.py`'s `VOLATILE_KEYS` excludes `sample_plan_sha256` and
      `evidence_sha256` from the recorded comparison by design -- they are never
      checked against a value recorded at another commit.
    * the one ordering-sensitive recorded number, `samples_outside_region`, has
      a band of `|recorded| * 0.005`, about 190 counts. Reversing the order
      moved it by 2.

    So the hazard was real, the protection was imaginary, and three places
    asserted it. This is that protection: the ordering rule, pinned to a value.

    Recording it is not re-recording a golden to make something pass -- there
    was no golden. A *deliberate* change to the ordering must bump
    `SAMPLE_PLAN_VERSION`, because every review answer bound to a plan digest is
    invalidated by it, and then this value is re-derived in the same commit that
    says why.
    """

    # Literal geometry, not `trimesh.creation.box`. A library that changed which
    # diagonal it triangulates a cube face on would move this digest, and the
    # failure would be about a dependency rather than about the ordering rule --
    # a guard that cries wolf is one somebody deletes. Written out, the only
    # things that can move it are these numbers and the ordering itself.
    CUBE_VERTICES = ((0.0, 0.0, 0.0), (3.0, 0.0, 0.0), (3.0, 4.0, 0.0),
                     (0.0, 4.0, 0.0), (0.0, 0.0, 5.0), (3.0, 0.0, 5.0),
                     (3.0, 4.0, 5.0), (0.0, 4.0, 5.0))
    CUBE_FACES = ((0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
                  (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5),
                  (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7))
    # Little-endian `tobytes`, which is every machine this runs on. A big-endian
    # host would fail this and the message says so rather than reading as an
    # ordering change.
    ORDERING = "120d99b61abd020932c9975b7276485f25c43c1318a29caaf80439696ee7fcdd"

    def test_the_canonical_ordering_is_the_one_the_plans_were_built_on(self) -> None:
        import hashlib
        import sys

        import trimesh

        import mesh_io
        if sys.byteorder != "little":                     # pragma: no cover
            self.skipTest("the pinned digest is over little-endian float bytes")
        ordered = mesh_io.canonical_order(trimesh.Trimesh(
            vertices=np.array(self.CUBE_VERTICES),
            faces=np.array(self.CUBE_FACES), process=False))
        digest = hashlib.sha256()
        digest.update(np.asarray(ordered.vertices, dtype=np.float64).tobytes())
        digest.update(np.asarray(ordered.faces, dtype=np.int64).tobytes())
        self.assertEqual(
            self.ORDERING, digest.hexdigest(),
            "the vertex or face ordering moved. Every review answer is bound to "
            "a sample plan digest computed under the old one, and neither the "
            "plan digest nor the replay band can see this -- so if the change "
            "was deliberate, bump SAMPLE_PLAN_VERSION and re-derive this value "
            "in the same commit")


class ABodyHasAHandleTest(unittest.TestCase):
    """The identity itself, and what it must not depend on."""

    def test_each_body_gets_a_digest_of_its_own_geometry(self) -> None:
        import mesh_io
        rows = mesh_io.body_identities(_two_boxes())
        self.assertEqual(2, len(rows))
        self.assertEqual(2, len({row["body_sha256"] for row in rows}),
                         "two different shapes are two different handles")
        for row in rows:
            self.assertEqual(64, len(row["body_sha256"]))

    def test_the_handle_does_not_move_when_the_order_does(self) -> None:
        """The whole point. A handle that changed with load order would be the
        unstable reference this slice exists to avoid."""
        import mesh_io
        first = [row["body_sha256"] for row in
                 mesh_io.body_identities(_two_boxes())]
        again = [row["body_sha256"] for row in
                 mesh_io.body_identities(_shuffled(_two_boxes()))]
        self.assertEqual(first, again)

    def test_the_rows_are_ordered_by_handle_and_not_by_split_order(self) -> None:
        """So two reads of one file present the bodies in one order, and a
        receipt naming "the first" means the same body twice."""
        import mesh_io
        rows = mesh_io.body_identities(_two_boxes())
        self.assertEqual([row["body_sha256"] for row in rows],
                         sorted(row["body_sha256"] for row in rows))

    def test_the_handle_covers_the_topology_and_not_only_the_points(self) -> None:
        """Same corners, different triangulation, different body.

        A handle taken over vertices alone would call two differently
        triangulated meshes one body, and a mutation dropping the faces from the
        digest survived until this existed -- because two boxes differ in their
        points as well, so the points alone were enough to tell them apart.
        """
        import mesh_io
        one, other = _same_corners_different_triangulation()
        np.testing.assert_allclose(one.vertices, other.vertices)
        self.assertNotEqual(mesh_io.body_identities(one)[0]["body_sha256"],
                            mesh_io.body_identities(other)[0]["body_sha256"])

    def test_negative_zero_is_zero(self) -> None:
        """`-0.0 == 0.0` is True and their bytes differ, so a digest over
        `tobytes()` split one shape into two handles. Real exporters write
        `v -0.0 -0.0 -0.0`, so this is reachable from an ordinary file rather
        than constructed spite."""
        import trimesh
        import mesh_io
        faces = np.array([[0, 1, 2]])
        positive = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
        signed = np.array([[-0.0, -0.0, -0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
        self.assertTrue(np.array_equal(positive, signed))
        self.assertEqual(
            mesh_io.body_identities(trimesh.Trimesh(vertices=positive,
                                                    faces=faces,
                                                    process=False)),
            mesh_io.body_identities(trimesh.Trimesh(vertices=signed,
                                                    faces=faces,
                                                    process=False)))

    def test_noise_below_the_rounding_does_not_permute_the_whole_body(self) -> None:
        """The rounding was applied to the hash input and not to the sort key.

        `canonical_order` lexsorts *unrounded* vertices, so a difference of 1e-9
        could flip a near-tie and permute the entire array before the rounding
        ever happened -- and near-ties are the normal case here, since every
        axis-aligned box has four vertices sharing an x. The comment claiming
        "rounded before hashing, so a handle survives the float noise two
        loaders can disagree by" was therefore describing something the code
        did not do.
        """
        import trimesh
        import mesh_io
        base = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0],
                         [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]])
        faces = np.array([[0, 1, 2], [0, 2, 3]])
        nudged = base.copy()
        nudged[1, 0] += 1e-9
        self.assertEqual(
            mesh_io.body_identities(trimesh.Trimesh(vertices=base, faces=faces,
                                                    process=False)),
            mesh_io.body_identities(trimesh.Trimesh(vertices=nudged,
                                                    faces=faces,
                                                    process=False)))

    def test_a_caller_that_already_split_is_believed(self) -> None:
        """`diagnose` splits the mesh one line above and splitting twice was
        over half the cost this added to an intake step. A parameter nothing
        checks is a parameter that quietly stops being used, so this passes a
        list the mesh alone would never produce."""
        import mesh_io
        mesh = _two_boxes()
        one_body = list(mesh.split(only_watertight=False))[:1]
        self.assertEqual(1, len(mesh_io.body_identities(mesh, bodies=one_body)),
                         "the caller's list decides, not a second split")
        self.assertEqual(2, len(mesh_io.body_identities(mesh)),
                         "and omitting it still splits for itself")

    def test_a_row_carries_enough_to_tell_the_bodies_apart(self) -> None:
        """A digest alone is unreadable. A person choosing which body to keep
        needs the size of each, and a receipt that only carried hashes would
        make the choice unmakeable without re-reading the file."""
        import mesh_io
        for row in mesh_io.body_identities(_two_boxes()):
            self.assertEqual({"body_sha256", "bbox_mm", "volume_mm3", "faces"},
                             set(row))
            self.assertEqual(3, len(row["bbox_mm"]))
            self.assertGreater(row["volume_mm3"], 0.0)

    def test_one_body_is_one_row_and_not_a_special_case(self) -> None:
        import trimesh
        import mesh_io
        (row,) = mesh_io.body_identities(
            trimesh.creation.box(extents=(10.0, 10.0, 10.0)))
        self.assertAlmostEqual(1000.0, row["volume_mm3"], places=3)

    def test_an_empty_mesh_has_no_bodies_rather_than_one_empty_one(self) -> None:
        """Held by `split` returning nothing, not by a guard of our own -- see
        the note in `body_identities`."""
        import trimesh
        import mesh_io
        self.assertEqual([], mesh_io.body_identities(
            trimesh.Trimesh(vertices=np.zeros((0, 3)),
                            faces=np.zeros((0, 3), dtype=np.int64))))


class DiagnoseReportsThemTest(unittest.TestCase):
    """The count was the whole answer, and a count cannot be referenced."""

    def test_the_report_names_every_body_it_counted(self) -> None:
        import tempfile
        from pathlib import Path

        import mesh_io
        from . import diagnose as D

        mesh = _two_boxes()
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "two-boxes.stl"
            mesh.export(path)
            report = D._diagnose_mesh(path)
        self.assertEqual(report["bodies"], len(report["body_identities"]),
                         "a count and a list that disagree are two answers to "
                         "how many bodies this file has")
        self.assertEqual([row["body_sha256"]
                          for row in mesh_io.body_identities(mesh)],
                         [row["body_sha256"]
                          for row in report["body_identities"]],
                         "and the handles are the ones a declaration will hold")


if __name__ == "__main__":
    unittest.main()
