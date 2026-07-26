# Hand-writing a part with trimesh

Read this when no template fits **and** `dt.py doctor` reports no CAD kernel. That is the
common case, not the fallback: trimesh and a boolean kernel are the only hard dependencies,
so a part written here needs nothing installed and feeds `commission` unchanged.

The charter used to send you to "the commissioned backend and its patterns" for this. On an
interpreter with no backend that is advice to nowhere, and a measured run spent its single
largest block of time working out these conventions from the template source.

## The shape of a model file

```python
"""What this part is."""
import trimesh

# Every design-driving number, named, at the top. Nothing derived by hand twice.
BORE_D, WALL, HEIGHT = 12.0, 3.0, 9.0

_body = trimesh.creation.box(extents=(40.0, 22.0, 5.0))
_body.apply_translation([20.0, 11.0, 2.5])          # seated: min Z at zero

part = _body
PARAMS = {"wall_mm": WALL,
          "overall_mm": {"x": 40.0, "y": 22.0, "z": 5.0}}
EXPECTED = ({"kind": "solid_region", "id": "plate", "z": 2.5, "area_mm2": 40.0 * 22.0},)
```

`part` is the solid. `PARAMS` is read *before* the build, so the pre-build stage can reject
your numbers without paying for the geometry. `EXPECTED` is what the solid must measure,
derived from the same named constants — never from the mesh you just made, or it agrees with
whatever you built including the mistake.

## Conventions the gate assumes

**Seat the part.** Minimum Z at zero. The plan's identity model-to-printer transform places
the model where it sits, so a part centred on the origin has half of itself under the bed and
its whole underside reads as unsupported. `seated-<rule>` fails on this now; before it did,
one run shipped a bed face 16 mm off the bed.

**Union your cutters before subtracting.** `trimesh.util.concatenate` glues meshes into a
non-manifold soup, and the boolean silently mishandles overlapping pieces — a countersink
cone crossing its own shaft removed nothing at all and read as 18 mm² of phantom overhang.

```python
cut = cuts[0] if len(cuts) == 1 else trimesh.boolean.union(cuts)
part = trimesh.boolean.difference([part, cut])
```

**Overshoot every through-cut.** A cutter whose face lands exactly on the surface it crosses
leaves coplanar artifacts that survive as degenerate faces and fail `repair`. Run it past by
a millimetre; the geometry outside the part costs nothing.

**No cone apexes.** A full cone tessellates to slivers at the tip that pass in memory and fail
watertightness on re-import. Build a truncated cone from two rings — a countersink meets its
shaft at a finite radius, so the apex was never part of the shape.

**Parts that touch weld on export.** Two solids sharing a face merge on STL reimport into one
non-manifold body: in-memory `is_watertight` says yes and the round trip says no. Leave a
bond line between them — which is also what glue needs — and declare the count with
`plan template --bodies N`.

## Measuring your own work

Do not write a sampler. `dt.py commission` measures everything the plan declares, and a
hand-rolled instrument is an uncalibrated one — one archived run's own sampler read 137% high
against known nominals and the run widened its bands until the wrong numbers passed.

If you need a number while designing, the library functions the gate itself uses are
importable:

```python
from designer_toolkit.features import solid_area_mm2, bore_diameter_mm, slice_profile
```

`solid_area_mm2(mesh, z)` is material area on a Z plane, net of holes. It works by
intersecting a thin slab, so it needs no `scipy`/`shapely`.

**The `to_2D()` frame trap.** If you section a mesh yourself, `to_2D()` returns an arbitrary
planar frame, not world XY — a verifier's first pass reported a part's section centred at
x = 2.97 with the bounding box at ±41.75 and nearly filed it as a defect. Pass the plane
transform explicitly, or use `solid_area_mm2`, which already does.

## What to declare in `EXPECTED`

Enough that a wrong number cannot hide. The kinds are `solid_region`, `bed_footprint`,
`through_hole` and `countersink`; see [`designer-toolkit.md`](designer-toolkit.md).

A hole's row is measured **where you declare it**, and its position is checked as well as its
size — a run building to the Gridfinity standard put its magnet pockets 0.25 mm out on both
axes, declared them in the same wrong place, and eight checks agreed before a fresh reader
compared the sheet against the standard.

Two things nothing here covers, so say them in `print_notes.md` rather than leaving them
silent: a blind pocket or a rabbet has no expectation kind, and a feature you added after the
fact may have changed a number some other row asserts.
