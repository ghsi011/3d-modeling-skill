#!/usr/bin/env python3
"""`disc_area` measured against its closed form, because nothing measured it at all.

`commission.py:247` calls `disc_area` on a real job to check the material inside a
bolt-hole boss. The only test that named it, `test_pipeline.py:3126`, **replaces it
with a stub** -- so across the whole commit gate the function's body executed zero
times. That was found by tracing every deferred-import function while proving the
lazy-import slice, and it is the reason a mutation removing that function's own
`import trimesh` had to be proven in the heavy tier: L0 could not see it.

A stub is the right call in `test_pipeline`, which is testing the caller. What was
missing is anything testing the function.

**Why the expectations are closed form.** A disc of diameter d cut from solid
material has area pi*d^2/4, from geometry, not from this repository and not from
trimesh -- so the assertion can disagree with the code. Comparing `disc_area`
against whatever trimesh returned would be a snapshot: green forever, including on
the day the slab thickness cancels wrong or the radius is passed as a diameter.

The cylinder is tessellated at 192 sections, so an inscribed polygon sits slightly
inside the true circle. The band below is that discretisation error and nothing
more: for a regular n-gon inscribed in a circle the area ratio is
(n/2pi)*sin(2pi/n), which at n=192 is 0.99982 -- so 0.05% is the floor, and 0.5%
leaves an order of magnitude over it while still catching a radius-for-diameter
mistake, which would be wrong by a factor of four.
"""
from __future__ import annotations

import math
import unittest

from . import analysis as A

SLAB = 30.0          # a plate thick enough that a thin slab sits well inside it
PLATE = 60.0         # and wide enough that no disc reaches its edge


def _plate():
    """A solid rectangular plate, centred on the origin."""
    import trimesh

    return trimesh.creation.box(extents=(PLATE, PLATE, SLAB))


def _context(mesh):
    return A.MeshAnalysisContext(path=None, raw=mesh, normalized=mesh,
                                 load_count=1, repair_actions=())


class TheDiscProbeMeasuresARealDiscTest(unittest.TestCase):

    def test_a_disc_in_solid_material_is_its_closed_form_area(self) -> None:
        ctx = _context(_plate())
        for diameter in (4.0, 10.0, 25.0):
            with self.subTest(diameter=diameter):
                want = math.pi * diameter * diameter / 4.0
                got = ctx.disc_area(z=0.0, at=(0.0, 0.0), diameter=diameter)
                self.assertAlmostEqual(
                    want, got, delta=want * 0.005,
                    msg="a disc cut from solid material is pi*d^2/4; a mismatch of "
                        "roughly four times means a radius was passed where a "
                        "diameter was expected")

    def test_a_disc_over_a_through_hole_measures_the_material_that_is_left(self) -> None:
        """The measurement the production caller actually wants.

        `commission` probes a bolt-hole boss: the answer that matters is how much
        material remains inside the probe, not how big the probe is.
        """
        import trimesh

        bore = 6.0
        probe = 20.0
        pin = trimesh.creation.cylinder(radius=bore / 2.0, height=SLAB * 2.0,
                                        sections=192)
        holed = trimesh.boolean.difference([_plate(), pin], engine="manifold")
        ctx = _context(holed)
        want = math.pi * (probe * probe - bore * bore) / 4.0
        got = ctx.disc_area(z=0.0, at=(0.0, 0.0), diameter=probe)
        self.assertAlmostEqual(
            want, got, delta=want * 0.005,
            msg="the probe must report the material left inside it, so a bore "
                "through the middle has to come off the answer")

    def test_a_disc_clear_of_the_part_measures_a_genuine_zero(self) -> None:
        """Zero because nothing is there, which is not the same as unavailable."""
        ctx = _context(_plate())
        self.assertEqual(0.0, ctx.disc_area(z=0.0, at=(PLATE, PLATE), diameter=4.0))

    def test_a_repeated_probe_does_not_run_the_boolean_again(self) -> None:
        """The docstring says "cached like the rest", and nothing checked it.

        Counting keys is not enough and that is the point: a cache that recomputes
        and then overwrites the same key leaves the dictionary exactly one entry
        long, so a key-count assertion passes while every probe pays a boolean.
        What the cache is *for* is not doing the work twice, so the work is what is
        counted -- a mutation that always recomputes survived the key-count version
        of this test and dies against this one.
        """
        ctx = _context(_plate())
        calls = []
        real = ctx._intersect

        def counting(window, *, where):
            calls.append(where)
            return real(window, where=where)

        ctx._intersect = counting
        first = ctx.disc_area(z=0.0, at=(0.0, 0.0), diameter=8.0)
        self.assertEqual(1, len(calls), "the first probe has to do the work")
        again = ctx.disc_area(z=0.0, at=(0.0, 0.0), diameter=8.0)
        self.assertEqual(first, again)
        self.assertEqual(1, len(calls),
                         "a repeated probe must be served from the cache, not "
                         "recomputed and written over the same key")
        ctx.disc_area(z=0.0, at=(0.0, 0.0), diameter=9.0)
        self.assertEqual(2, len(calls), "a different probe is genuinely new work")


if __name__ == "__main__":
    unittest.main()
