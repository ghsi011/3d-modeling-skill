# build123d — tested code patterns

**When to pick build123d**: exact B-rep authoring — fillets, chamfers, revolves,
lofts, sweeps, exact face and edge operations — and editable STEP output. It is
the only CAD kernel on this stack. For primitive boolean geometry prefer the
trimesh + manifold3d backend: `import build123d` costs 10.7 s measured, against
1.5 s for trimesh and manifold3d together.

**Costs.** The user edits a `.py`, not a GUI document, so ship STEP when they
need to edit the shape itself. And the OCC pitfalls are real: fillets corrupt on
scalloped solids, and volume misreports on periodic splines. Both present as a
solid that looks right and measures wrong, which is what the gate is for —
commission the export, never the kernel's own numbers.

Everything after `export_stl` is backend-neutral — Phase-4 verification, the
render-over-photo overlay loop, printability screening, non-watertight-source
extraction, and multi-color 3MF packing all operate on the exported STL and are
documented once in [`verification-patterns.md`](verification-patterns.md) and
[`designer-toolkit.md`](designer-toolkit.md). Use those as written; only the
modelling below is build123d-specific.

Run your script, then gate the STL it wrote:

```bash
uv run --project <skill> --frozen python <skill>/scripts/dt.py commission --stl body.stl \
  --plan print_plan_checks.json --out . --job-id <job> \
  --updated-utc <iso8601>          # the deterministic gate, from any directory
```

**`--stl`, not `--model`.** `--model` imports the file and expects a module-level
`part` that is a trimesh, alongside `PARAMS` and `EXPECTED` — the contract in
[`trimesh-patterns.md`](trimesh-patterns.md). A build123d `Part` is neither, and the
skeleton below names it `body`, so `--model` fails here with ``model.py must define
`part` or `build()` ``. The exported STL is the handoff, which is what "backend-neutral"
above means.

`--stl` carries no `EXPECTED`, so **the plan has to declare the features** — `features`
rows in `print_plan_checks.json`, in the kinds listed under
[what to declare](trimesh-patterns.md#what-to-declare-in-expected). Skip that and the gate
checks the envelope and the printability and nothing at all about the shape.

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
- When a fillet will not compute, take the radius down in steps rather than
  fighting it: OCC fails on scalloped solids well before the radius is
  geometrically impossible. If it still fails, fillet *earlier* — before the
  booleans that produced the scallop.

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
