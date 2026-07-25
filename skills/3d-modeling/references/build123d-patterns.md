# build123d — tested code patterns

**When to pick build123d** (vs CadQuery/FreeCAD): runs headless like CadQuery,
keeps scripts Python-first, and is the right backend when a host or source model
standardizes on build123d's builder contexts and direct exporters. **Costs**:
the user edits a .py, not a GUI document (also ship STEP so any CAD can open it);
OCC kernel pitfalls still apply; every output must be delivered explicitly —
nothing lands on the user's disk by itself.

Run exported meshes through the bundled mesh tools — verification is on the STL,
not the in-memory build123d `Part`:

```bash
cd skills/3d-modeling/scripts     # or scripts/ inside a packaged .skill bundle
python3 preview.py body.stl preview.png --views multi
python3 -m designer_toolkit finalize body.stl --plan plan.json   # full evidence bundle as JSON
```

Failure → read the tool output, fix the script, re-export, and always LOOK at
the preview.

## Script skeleton (one file, parameters first)

```python
from build123d import *

# ==== PARAMETERS (mm; provenance in comments) ====
shaft_d = 12.9       # measured, caliper photo 1
fit_clr_side = 0.15  # per-side, sliding fit — fdm-design §4
bore_depth = 74.0    # rod exposed 72.1 + 1.9 seat offset

# ==== MODEL ====
with BuildPart() as body_builder:
    Cylinder(radius=46 / 2, height=95, align=(Align.CENTER, Align.CENTER, Align.MIN))
    with Locations((0, 0, 95 - bore_depth / 2)):
        Hole(radius=(shaft_d + 2 * fit_clr_side) / 2, depth=bore_depth)
body = body_builder.part

# ==== REFERENCE (mating object, NOT exported) ====
with BuildPart() as ref_builder:
    Cylinder(radius=shaft_d / 2, height=72.1, align=(Align.CENTER, Align.CENTER, Align.MIN))
ref_part = ref_builder.part.moved(Location((0, 0, 1.9)))

# ==== EXPORT ====
export_stl(body, "body.stl", tolerance=0.01, angular_tolerance=0.1)
export_step(body, "body.step")
print("volume", body.volume, "bbox", body.bounding_box())
```

- Bottom of the part at Z=0 in print orientation (`Align.MIN` on Z).
- Booleans: use builder operations (`add`, `subtract`, `intersect`) or explicit
  shape booleans, then export the final `Part`.
- **Fillet/chamfer robustness** (recurring OCC failure: a fillet that will not
  compute at *any* radius — usually on a lip, thin, lofted, or post-boolean edge).
  Work this ladder before giving up, rather than looping on radii:
  1. Fillet on the primitive, before the boolean/union — not on the merged edge
     afterward (largest radius first).
  2. Reduce the radius and select one edge set at a time; one fragile edge can
     sink a batch selector.
  3. Substitute a chamfer. Chamfers are far more OCC-robust than fillets and
     satisfy most exposed-edge comfort requirements.
  4. Last resort: ship the edge sharp but DECLARE it `allowed_sharp` with a
     feature-specific reason in the plan's edge set.
- OCC pitfalls (observed in sibling OCC stacks): fillet/chamfer on scalloped or
  periodic-spline edges can silently corrupt solids. Assert a sane volume delta
  after fragile booleans and trust the exported mesh volume in Phase 4.

## Phase-4 verification patterns

**First reach for the toolkit, not raw backend code.** These checks are packaged
and tested in [`designer-toolkit.md`](designer-toolkit.md) — `export_and_hash`,
`interference`, `insertion_sweep`, `datum_features`, `overhang_area`, and a
one-call `finalize`. Call those on the exported STL; they already handle the
`plane_transform` datum frame, the -0.73 overhang screen, and watertight checks
on the normalized mesh. Raw snippets below are the explanation and fallback.

```python
# 1. export first; Phase 4 measures the mesh artifact, not body_builder.part
export_stl(body, "body.stl", tolerance=0.01, angular_tolerance=0.1)
export_step(body, "body.step")

# 2. use designer_toolkit on the exported mesh
import sys
sys.path.insert(0, "<skill>/scripts")
from designer_toolkit import finalize, overhang_area

finalize("body.stl", strict=True)
print("unsupported overhang area mm2", overhang_area("body.stl"))

# 3. visual side-by-side vs reference model / photos — SAME cameras, one image
from preview import render_view
from PIL import Image
import trimesh

ref_mesh = trimesh.load("ref.stl")
cand_mesh = trimesh.load("body.stl")
views = [(89, -90), (5, -90), (25, -60)]
row_r = [render_view(ref_mesh, e, a, 420, 420) for e, a in views]
row_c = [render_view(cand_mesh, e, a, 420, 420) for e, a in views]
canvas = Image.new("RGB", (3 * 420, 2 * 420), "white")
for i, im in enumerate(row_r + row_c):
    canvas.paste(im, ((i % 3) * 420, (i // 3) * 420))
canvas.save("side_by_side.png")

# 4. feature positions from named datums — on the EXPORTED STL
import numpy as np

m = trimesh.load("body.stl")
sec = m.section(plane_origin=[0, 0, 1.0], plane_normal=[0, 0, 1])
p, _ = sec.to_2D(trimesh.geometry.plane_transform([0, 0, 1.0], [0, 0, 1]))
for poly in p.polygons_full:
    for hole in poly.interiors:
        c = np.array(hole.coords)
        ctr, size = (c.min(0) + c.max(0)) / 2, c.max(0) - c.min(0)
        print("hole", np.round(size, 1), "center", np.round(ctr, 1))
```

## Render-over-photo overlay loop (recreating a part from photos)

Side-by-side comparison catches gross mismatch; an OVERLAY catches millimeters.
For near-orthographic top/front photos:

```python
# 1. segment the part's bbox in the photo (non-white profile rows/cols, or threshold)
# 2. map model mm -> photo px: fit exported mesh slice bbox to photo bbox, y flipped
# 3. slice body.stl with plane_transform and draw exterior+interior rings on the photo
# 4. adjust named parameters; re-export with export_stl/export_step; repeat
```

Iterate against the PHOTO only, not against a scoring reference; the overlay
image decides whether silhouettes, pockets, and raised features line up.

## Printability audit helpers (trimesh, on the exported STL)

```python
import numpy as np
import trimesh

m = trimesh.load("body.stl")
print("watertight", m.is_watertight, "volume", m.volume)
down = m.face_normals[:, 2] < -0.7071
overhang_area = m.area_faces[down & (m.triangles_center[:, 2] > 0.3)].sum()
print("unsupported overhang area mm2", overhang_area)
```

## Extracting a chunk from a NON-watertight source mesh (scans, marching cubes)

Do **not** chain `trimesh.slice_plane(cap=True)` to whittle a region out of a
dirty mesh. Feed raw face soup to `manifold3d` and take the region as one
boolean intersection against a box:

```python
import trimesh

src = trimesh.load("scan.stl", process=False)
box = trimesh.creation.box(extents=(bx, by, bz))
box.apply_translation((cx, cy, cz))
chunk = trimesh.boolean.intersection([src, box], engine="manifold")
```

## Common shapes

```python
from build123d import *

# revolve a profile (knobs, bulbs)
with BuildPart() as knob:
    with BuildSketch(Plane.XZ):
        Polyline((0, 0), (15, 0), (23, 40), (8, 95), (0, 95), close=True)
        make_face()
    revolve(axis=Axis.Z)

# bolt circle locations
with BuildPart() as flange:
    Cylinder(radius=20, height=4, align=(Align.CENTER, Align.CENTER, Align.MIN))
    with PolarLocations(radius=16, count=6):
        Hole(radius=1.6)

# enclosure shell (open top)
with BuildPart() as enclosure:
    Box(60, 40, 25, align=(Align.CENTER, Align.CENTER, Align.MIN))
    shell(openings=enclosure.faces().sort_by(Axis.Z).last, amount=2)
```

## Multi-color

Export each color as its own STL from the same script (shared coordinates), then run
this from `skills/3d-modeling/scripts/` (`scripts/` inside a packaged .skill bundle):
`python3 make_3mf.py out.3mf "Body=body.stl" "Inlay=inlay.stl"` — one
3MF, one build object, one component per part; Bambu/Orca import it as a single
object with parts individually assignable to filaments. Inlay geometry rules
(flush recess, zero clearance, stroke ≥0.8 mm) live in `fdm-design.md`.
