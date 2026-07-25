# CadQuery — tested code patterns

**When to pick CadQuery** (vs FreeCAD): runs anywhere Python does — no desktop, no GUI
dependency; iteration is cheap and fast; verification is scriptable; previews render
headless. Best cost/quality ratio in our benchmark. **Costs**: the user edits a .py, not
a GUI document (also ship STEP so any CAD can open it); OCC kernel pitfalls below
(fillet corruption on scalloped solids, volume misreport on periodic splines); every
output must be delivered explicitly — nothing lands on the user's disk by itself.

Run everything through the bundled runner — it executes the script, finds the STL,
renders a multi-view preview, and returns JSON (`success`, `stderr`, `stl`, `preview`,
`watertight`):

```bash
python3 scripts/run_cadquery_model.py model.py --preview --strict   # strict: non-watertight = fail
python3 scripts/preview.py model.stl preview.png --views multi      # render-only
```

`success: false` → read `stderr`, fix the script, re-run. Always LOOK at the preview.

## Script skeleton (one file, parameters first)

```python
import cadquery as cq

# ==== PARAMETERS (mm; provenance in comments) ====
shaft_d       = 12.9   # measured, caliper photo 1
fit_clr_side  = 0.15   # per-side, sliding fit — fdm-design §4
bore_depth    = 74.0   # rod exposed 72.1 + 1.9 seat offset
# ==== MODEL ====
body = (cq.Workplane("XY")
        .circle(46/2).extrude(95)                      # never centered in Z: bed at Z=0
        .faces("<Z").workplane()
        .hole(shaft_d + 2*fit_clr_side, bore_depth))
# ==== REFERENCE (mating object, NOT exported) ====
ref_part = (cq.Workplane("XY").circle(shaft_d/2).extrude(72.1)
            .translate((0, 0, 1.9)))                   # seated position
# ==== EXPORT ====
cq.exporters.export(body, "body.stl", tolerance=0.01, angularTolerance=0.1)
cq.exporters.export(body, "body.step")
print("volume", body.val().Volume(), "bbox", body.val().BoundingBox().xlen)
```

- Bottom of the part at Z=0 in print orientation (`centered=(True, True, False)`).
- Booleans: `.cut()`, `.union()`, `.intersect()`.
- **Fillet/chamfer robustness** (recurring OCC failure: a fillet that will not compute at *any*
  radius — usually on a lip, thin, lofted, or post-boolean edge). Work this ladder before giving
  up, rather than looping on radii:
  1. Fillet on the **primitive, before** the boolean/union — not on the merged edge afterward
     (largest radius first). Most "won't-compute" fillets succeed when applied earlier in the tree.
  2. Reduce the radius (a fillet ≥ local wall/feature always fails) and select **one edge at a
     time** — a batch `edges(...)` selector fails the whole operation if any single edge is fragile.
  3. **Substitute a chamfer.** Chamfers are far more OCC-robust than fillets and satisfy an
     exposed-edge comfort requirement just as well (a 0.6 mm chamfer breaks an edge for hand-feel
     as well as a 0.6 mm fillet). Prefer this over shipping the edge sharp, and over distorting
     the part to route around the fillet.
  4. Last resort: ship the edge **sharp but DECLARE it `allowed_sharp` with a feature-specific
     reason** in the plan's edge set — never leave an *undeclared* sharp edge, which silently
     fails the gate (that is a NOT_READY, not a delivery).
- OCC pitfalls (observed): fillet/chamfer on scalloped/periodic-spline edges can silently
  corrupt the solid — assert `isValid()` AND a sane volume delta after every
  fillet/chamfer/boolean; if one corrupts, replace it with a revolved or wedge cut.
  `.val().Volume()` can misreport on periodic-spline solids — trust the exported mesh
  (trimesh volume), which is also what Phase 4 must measure.
- Selectors: `faces(">Z")`, `edges("|Z")`, `edges("<Z")` (bed chamfer: `.chamfer(0.5)`).

## Phase-4 verification patterns

```python
# 1. seated interference (must be ~0)
inter = body.intersect(ref_part)
print("interference", inter.val().Volume() if inter.val().Solids() else 0.0)

# 2. insertion sweep — ref less deep by t, still no interference
for t in (5, 15, 25, 35, 45, 55, 65):
    r = ref_part.translate((0, 0, -t))
    s = body.intersect(r)
    v = s.val().Volume() if s.val().Solids() else 0.0
    assert v < 1e-6, f"insertion blocked at travel {t}: {v}"

# 3. section render: cut half, export, preview
half = body.cut(cq.Workplane("XY").box(500, 500, 500, centered=(False, True, True)))
cq.exporters.export(half, "section.stl", tolerance=0.01, angularTolerance=0.1)

# 4. visual side-by-side vs reference model / photos — SAME cameras, one image
import sys; sys.path.insert(0, '<skill>/scripts'); from preview import render_view
from PIL import Image
import trimesh
ref_mesh = trimesh.load('ref.stl')                  # render_view takes trimesh meshes,
cand_mesh = trimesh.load('body.stl')                # not CadQuery Workplanes
views = [(89, -90), (5, -90), (25, -60)]            # top, front, iso
row_r = [render_view(ref_mesh, e, a, 420, 420) for e, a in views]
row_c = [render_view(cand_mesh, e, a, 420, 420) for e, a in views]
canvas = Image.new('RGB', (3*420, 2*420), 'white')
for i, im in enumerate(row_r + row_c):
    canvas.paste(im, ((i % 3)*420, (i // 3)*420))
canvas.save('side_by_side.png')                      # then LOOK at it and compare
# feature-by-feature: silhouette, shapes, counts, positions — before any export

# 5. feature positions from named datums — on the EXPORTED STL
import trimesh, numpy as np
m = trimesh.load('body.stl')
sec = m.section(plane_origin=[0, 0, 1.0], plane_normal=[0, 0, 1])
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

# 7. face audit half of check 7 — cylindrical radii present in the part
#    (check 6, measurement audit, is a manual diff of prompt numbers vs geometry;
#     printability half of check 7: next section)
import re
radii = sorted({round(f.radius(), 2) for f in body.val().Faces()
                if f.geomType() == "CYLINDER"})
print("cyl radii", radii, "bbox", body.val().BoundingBox())
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

## Common shapes

```python
# revolve a profile (knobs, bulbs)
profile = cq.Workplane("XZ").polyline([(0,0),(15,0),(23,40),(8,95),(0,95)]).close()
solid = profile.revolve(360, (0,0,0), (0,0,1))
# polar pattern (bolt circles, fins)
r = 20  # bolt-circle radius
wp = (cq.Workplane("XY").pushPoints(
      [(r*__import__('math').cos(a), r*__import__('math').sin(a))
       for a in [i*2*3.14159/6 for i in range(6)]]).circle(1.6).cutThruAll())
# text (engrave 0.6 deep)
body = body.faces(">Z").workplane().text("R", 8, -0.6, font="DejaVu Sans", kind="bold")
# shell an enclosure (open top)
box = cq.Workplane("XY").box(60, 40, 25, centered=(True, True, False)).faces(">Z").shell(-2)
```

## Multi-color

Export each color as its own STL from the same script (shared coordinates), then:
`python3 scripts/make_3mf.py out.3mf "Body=body.stl" "Inlay=inlay.stl"` — one 3MF,
one build object, one component per part; Bambu/Orca import it as a single object with
parts individually assignable to filaments. Inlay geometry rules (flush recess, zero
clearance, stroke ≥0.8 mm): fdm-design §6.

Slicer-facing design decisions (orientation, prime tower, materials, clearances) live in
`fdm-design.md` — consult it, not memory.
