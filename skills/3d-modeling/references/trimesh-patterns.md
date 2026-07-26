# Hand-writing a part with trimesh

Read this when no template fits **and** `dt.py doctor` reports no CAD kernel. That is the
common case, not the fallback: trimesh and a boolean kernel are the only hard dependencies,
so a part written here needs nothing installed and feeds `commission` unchanged.

Written down because a measured run spent its single largest block of time working these
conventions out from the template source, having been sent to a backend that was not
installed.

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

Enough that a wrong number cannot hide.

| kind | asserts | keys |
|---|---|---|
| `solid_region` | material area on a Z plane, net of holes | `z`, `area_mm2`, opt. `tol_mm2` |
| `void_region` | a rectangle on a Z plane is **empty** | `z`, `at`, `size_mm`, opt. `max_area_mm2`, `tol_mm2` |
| `bed_footprint` | the area meeting the bed | `area_mm2`, opt. `tol_mm2` |
| `through_hole` | bore diameter and centre, at three depths | `at`, `d_mm`, `z_from`, `z_to`, opt. `window_r` |
| `countersink` | the mouth opening out, plus the shaft below it | `at`, `shaft_d`, `head_d`, `face_z`, opt. `included_angle` (90), `from_face` (`+z`), `window_r` |

An unknown kind is a FAIL, not a skip: a row nobody measures reads as a check and is not one.

A hole's row is measured **where you declare it**, and its position is checked as well as its
size — a run building to the Gridfinity standard put its magnet pockets 0.25 mm out on both
axes, declared them in the same wrong place, and eight checks agreed before a fresh reader
compared the sheet against the standard.

**Declare your cavities, not just your walls.** `solid_region` is one number for a whole
section, so anything that thins a wall buys room for something standing inside the box.
`void_region` reads the named rectangle alone. Use it for a pocket, a rabbet, a compartment —
anywhere the point of the feature is that something else has to fit in it. It refuses rather
than passes when the window is not inside the material's own footprint at that height, because
an empty window off the side of the part is not evidence of anything.

One thing nothing here covers, so say it in `print_notes.md` rather than leaving it silent: a
feature you added after the fact may have changed a number some other row asserts.
