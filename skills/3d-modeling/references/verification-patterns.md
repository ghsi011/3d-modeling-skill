# Verification patterns — backend-neutral

Everything here operates on the **exported STL**, so it applies whatever authored
the geometry: build123d, the trimesh templates, or a hand-written model. That is
the point of the split -- the kernel is an authoring choice and verification is
not.

The deterministic gate runs these for you:

```bash
uv run design-tool run-job job_dir/
```

Read on when you need to understand a result, reproduce one by hand, or work on
the checks themselves. This is an explanation, not a kit to assemble: offering
the individual check functions as a menu is what made three measured runs
hand-write 130-to-280-line verification scripts instead of running the gate, and
one of them widened its own acceptance bands until its wrong numbers passed.

The gate already handles the traps below — the `plane_transform` datum frame, the
-0.73 overhang screen, watertight-on-the-normalized-mesh — and exits non-zero if
any declared measurement fails.

## Verification patterns

```python
# Name the engine at every boolean. Letting trimesh choose is how a run silently
# gets a different engine's answer, or none.
import numpy as np, trimesh
from trimesh.boolean import intersection, difference
ENGINE = "manifold"

body = trimesh.load("body.stl", force="mesh")
ref_part = trimesh.load("ref.stl", force="mesh")

# 1. seated interference (must be ~0)
inter = intersection([body, ref_part], engine=ENGINE)
print("interference", float(inter.volume) if len(inter.faces) else 0.0)

# 2. insertion sweep — ref less deep by t, still no interference
for t in (5, 15, 25, 35, 45, 55, 65):
    r = ref_part.copy()
    r.apply_translation((0, 0, -t))
    s = intersection([body, r], engine=ENGINE)
    v = float(s.volume) if len(s.faces) else 0.0
    assert v < 1e-6, f"insertion blocked at travel {t}: {v}"

# 3. section render: cut half, export, preview
# Place the cutter from the part's own bounds, not from the origin. A fixed
# x >= 0 half-space removes a seated part entirely, and an empty section.stl
# looks like a rendering problem rather than a cut in the wrong place.
mid = float(body.bounds[:, 0].mean())
cutter = trimesh.creation.box((500, 500, 500))
cutter.apply_translation((mid + 250, 0, 0))    # keep the x < mid half
difference([body, cutter], engine=ENGINE).export("section.stl")

# 4. visual side-by-side vs reference model / photos — SAME cameras, one image
import sys; sys.path.insert(0, '<skill>/scripts'); from preview import render_view
from PIL import Image
import trimesh
ref_mesh = trimesh.load('ref.stl')                  # render_view takes trimesh meshes,
cand_mesh = trimesh.load('body.stl')                # the exported mesh, not a B-rep part
views = [(89, -90), (5, -90), (25, -60)]            # top, front, iso
row_r = [render_view(ref_mesh, e, a, 420, 420) for e, a in views]
row_c = [render_view(cand_mesh, e, a, 420, 420) for e, a in views]
canvas = Image.new('RGB', (3*420, 2*420), 'white')
for i, im in enumerate(row_r + row_c):
    canvas.paste(im, ((i % 3)*420, (i // 3)*420))
canvas.save('side_by_side.png')                      # then LOOK at it and compare
# feature-by-feature: silhouette, shapes, counts, positions — before any export

# 5. feature positions from named datums — on the EXPORTED STL
sec = body.section(plane_origin=[0, 0, 1.0], plane_normal=[0, 0, 1])
# ALWAYS pass plane_transform: bare to_2D() re-origins on a path-dependent frame,
# so hole centers silently stop matching model-coordinate datums
p, _ = sec.to_2D(trimesh.geometry.plane_transform([0, 0, 1.0], [0, 0, 1]))
for poly in p.polygons_full:
    for hole in poly.interiors:
        c = np.array(hole.coords)
        ctr, size = (c.min(0) + c.max(0)) / 2, c.max(0) - c.min(0)
        print('hole', np.round(size, 1), 'center', np.round(ctr, 1))
# compare each center to the Phase-2 datum values (e.g. camera window: +5.5 from
# centerline, 36.7 from top edge). Size alone never passes a placement check.
# Handedness: also compare with x negated — mirrored layouts fit the numbers too.

# 7. face audit half of check 7 — bore diameters present in the part
#    (check 6, measurement audit, is a manual diff of prompt numbers vs geometry;
#     printability half of check 7: next section)
# An STL has no analytic faces: a cylinder is facets, and there is no radius to
# ask for. That is the honest cost of verifying the exported mesh instead of the
# kernel's own model of it -- and it is the right trade, because the exported
# mesh is what gets printed. Measure the hole in a section instead.
sec = body.section(plane_origin=[0, 0, 1.0], plane_normal=[0, 0, 1])
flat, _ = sec.to_2D(trimesh.geometry.plane_transform([0, 0, 1.0], [0, 0, 1]))
for poly in flat.polygons_full:
    for hole in poly.interiors:
        c = np.array(hole.coords)
        size = c.max(0) - c.min(0)
        # Round only for display. A bore tessellated at 64 segments measures
        # slightly under nominal across the flats; compare against the tolerance
        # the contract declares, never against the nominal number.
        print("bore", np.round(size, 2))
print("bbox", np.round(body.bounds, 2))
```

## Render-over-photo overlay loop (recreating a part from photos)

Side-by-side comparison catches gross mismatch; an OVERLAY catches millimeters. When a
near-orthographic photo exists (top/front view), draw the model's slice boundaries ON
the photo and iterate parameters until they hug the features:

```python
# 1. segment the part's bbox in the photo (non-white profile rows/cols, or threshold)
# 2. map model mm -> photo px: fit model slice bbox to photo bbox, y flipped
# 3. slice the exported STL (plane_transform! see item 5) at feature depths,
#    draw every exterior+interior ring on the photo in red, save, LOOK
# 4. adjust the named parameters the misfit points at; re-export; repeat
```

Rules learned running this: iterate against the PHOTO only (never against a scoring
reference — that's tuning to the answer key); a mean-distance-to-nearest-edge residual
is a useful trend number but too forgiving to decide with (any line lands near SOME
edge in a busy photo) — the overlay image decides; apply the same trick to iso/side
photos to catch vertical architecture (raised rims, ramps, dips) that top views hide —
render your model from the photo's viewpoint and compare silhouettes. Measured result:
one overlay iteration took a photo recreation from layout-IoU 0.59 to 0.70 vs ground
truth; the loop also exposed pocket-mouth chamfers and a raised-end architecture that
side-by-side viewing had missed.

## Printability audit helpers (trimesh, on the exported STL)

```python
import trimesh, numpy as np
m = trimesh.load("body.stl")
print("watertight", m.is_watertight, "volume", m.volume)
down = m.face_normals[:, 2] < -0.7071                # faces steeper than 45° down
overhang_area = m.area_faces[down & (m.triangles_center[:, 2] > 0.3)].sum()
print("unsupported overhang area mm2", overhang_area)  # ~0 for a support-free print
```

## Extracting a chunk from a NON-watertight source mesh (scans, marching cubes)

Do **not** chain `trimesh.slice_plane(cap=True)` to whittle a region out of a dirty mesh:
capping a face with sub-micron float noise on nominally-flat faces, or with sliver
triangles, leaves thousands of unshared edges — the result isn't a volume and the next
boolean dies with `Not all meshes are volumes!`. Instead feed the raw face soup straight to
`manifold3d` and take the region as ONE boolean intersection against a box:

```python
import trimesh
src = trimesh.load("scan.stl", process=False)          # keep the raw faces as-is
box = trimesh.creation.box(extents=(bx, by, bz))
box.apply_translation((cx, cy, cz))                    # the chunk you want to keep
chunk = trimesh.boolean.intersection([src, box], engine="manifold")
```

- **Dodge a noisy flat face**: cut a hair (~0.01 mm) ABOVE it, then translate the chunk back
  down to z=0 — you get a genuinely planar face instead of inheriting the float noise.
- **Self-touching marching-cubes surfaces**: fine in memory (the two sheets have distinct
  vertex indices), but go non-manifold the instant a binary STL merges coincident vertices
  on export. Nudge such vertices ~2 µm apart before writing the STL.
