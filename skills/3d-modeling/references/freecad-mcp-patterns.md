# FreeCAD MCP — tested code patterns

**When to pick FreeCAD** (vs CadQuery): the user gets a parametric FCStd they can open
and edit; Params spreadsheet makes every fit fix a one-cell change; renders come from the
real GUI; outputs save directly to the user's disk. Benchmark winner on design quality.
**Costs**: needs the desktop + FreeCAD + MCP addon running; every execute_code returns a
~10k-token screenshot, making it the most expensive backend (plan ≤8 chunks per job);
single instance — parallel jobs serialize. No desktop connected → use CadQuery.

These patterns were proven working on the user's machine through the FreeCAD MCP. Tools
are named here by their bare names (`list_documents`, `create_document`, `execute_code`,
…); the prefix your host exposes them under is host-dependent, so match on the bare name
rather than a literal string. Every `execute_code` call returns stdout plus a
viewport screenshot — always print check values and look at the screenshot.
Screenshots make each call expensive (~10k tokens): plan the job into FEW large
execute_code chunks (aim ≤8 per job), print all check numbers in each, and never make
a call just to peek.

## Session setup

- First call `list_documents`. If the freecad tools are missing or error, the user's
  desktop/FreeCAD isn't connected — ask them to open FreeCAD with the MCP addon; never
  fall back to guessing geometry offline.
- `list_documents` → `create_document` with a project name (snake_case).
- Files save directly to the user's disk from inside FreeCAD (`doc.saveAs`, `Mesh`/`Part`
  export, `saveImage`) — no staging round-trip for outputs FreeCAD itself writes.
  Anything built outside FreeCAD (the 3MF, print_notes.md) lands wherever the agent
  runs, which is not necessarily the user's disk — deliver those into the project
  folder explicitly, by whatever file-transfer path the host provides.
- Keep each `execute_code` chunk small enough to verify: build → print `Shape.isValid()`,
  `Volume`, `BoundBox` → next chunk.
- Hide the reference part before final renders/exports:
  `doc.RefPart.ViewObject.Visibility = False`.

## Params spreadsheet driving geometry

All clearance cells store **per-side** values (the convention of fdm-design §4).

```python
sheet = doc.addObject('Spreadsheet::Sheet', 'Params')
rows = [('shaft_d', 12.9,      'measured rod shaft diameter'),
        ('fit_clr_side', 0.15, 'per-side clearance — pick from fdm-design §4')]
for i, (name, val, note) in enumerate(rows, start=1):
    sheet.set(f'A{i}', name); sheet.set(f'B{i}', str(val)); sheet.set(f'C{i}', note)
    sheet.setAlias(f'B{i}', name)
doc.recompute()

bore = doc.addObject('Part::Cylinder', 'MainBore')
bore.setExpression('Radius', 'Params.shaft_d / 2 + Params.fit_clr_side')
bore.setExpression('Height', 'Params.bore_depth')
```

Read back with `sheet.get('alias')`. Update with `sheet.set('B6', '74')` + `recompute()`.

## Sculpted solids (revolves) + parametric cut chain

```python
import Part
from FreeCAD import Vector as V
bs = Part.BSplineCurve(); bs.interpolate([V(r,0,z) for r,z in profile_pts])
wire = Part.Wire([Part.makeLine(V(0,0,0), V(r0,0,0)), bs.toShape(), ...])
solid = Part.Face(wire).revolve(V(0,0,0), V(0,0,1), 360)
fo = doc.addObject('Part::Feature', 'OuterBody'); fo.Shape = solid   # static sculpt
cut1 = doc.addObject('Part::Cut', 'Cut1'); cut1.Base = fo; cut1.Tool = bore  # parametric
```

Static base + parametric cutters keeps recompute working when Params change.

## Text / logos (two-color inlays)

```python
import Draft, os
CANDIDATES = ['C:/Windows/Fonts/arialbd.ttf',                       # Windows
              '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',  # Linux
              '/System/Library/Fonts/Supplemental/Arial Bold.ttf']  # macOS
FONT = next((f for f in CANDIDATES if os.path.exists(f)), None)  # none → ask user for a .ttf
ss = Draft.make_shapestring(String='5', FontFile=FONT, Size=5.0)
doc.recompute(); sh = ss.Shape.copy(); doc.removeObject(ss.Name)
if not sh.Faces: sh = Part.makeFace(sh.Wires, 'Part::FaceMakerBullseye')  # holes in R, 4...
# center via sh.BoundBox, translate, extrude 0.6, fuse with gate bars
```

Make the inlay a separate solid that exactly fills a recess cut from the body: export both,
they print flush. Keep inlay strokes ≥ 0.8 mm wide (multi-color floor; single-color
engrave/emboss floors are lower — fdm-design §1).

## Fit verification (Phase 4)

```python
inter = part.Shape.common(rod.Shape)           # rod at final inserted Placement
print('interference volume:', inter.Volume)     # must be ~0
halfbox = Part.makeBox(200,100,300, V(-100,0,-50))
section = doc.KnobBody.Shape.cut(halfbox)       # half-section for render
radii = sorted({round(f.Surface.Radius,2) for f in part.Shape.Faces
                if isinstance(f.Surface, Part.Cylinder)})
print('cylindrical radii:', radii, 'bbox:', part.Shape.BoundBox)
```

Visual side-by-side (Phase 4 check): render the part and RefPart from the SAME saved
camera views as the user's photos (set the view, `saveImage`, repeat per model with the
other hidden), stage the PNGs back, compose one side-by-side image, and look at it
feature-by-feature before export. Feature positions: verify on the **exported STL** in
the cloud container — `device_stage_files` the STL back first — (trimesh slice → hole
centers vs named datums — snippet in cadquery-patterns.md §Phase-4 item 5); the in-memory shape is not the artifact, and
check handedness — a mirrored layout fits the numbers too.

## Renders

```python
import FreeCADGui as Gui
doc.KnobBody.ViewObject.ShapeColor = (0.13,0.13,0.13)
Gui.runCommand('Std_ViewIsometric'); Gui.SendMsgToActiveView('ViewFit')
Gui.activeDocument().activeView().saveImage(path, 1200, 900, 'White')
```

Note: a section cut parallel to the view plane renders as the intact silhouette — cut the
half that faces the camera away, or orbit so the section face is visible before saving.
`saveImage` writes to the user's disk, not to the conversation — surface the saved PNGs
through whatever file-attachment path the host provides so the user actually sees them.

## Exports

```python
import MeshPart, Part
m = MeshPart.meshFromShape(Shape=doc.KnobBody.Shape,
                           LinearDeflection=0.05, AngularDeflection=0.3, Relative=False)
m.write(out_stl)
Part.export([doc.KnobBody, doc.PatternInlay], out_step)   # multi-solid STEP
```

For the single-file multi-color 3MF, run `make_3mf.py` from `skills/3d-modeling/scripts/`
(`scripts/` inside a packaged .skill bundle) on the staged STLs (trimesh welds vertices;
output is a core-spec 3MF with one build object containing one component per part — Bambu
Studio imports it as one object, parts individually assignable to filaments). FreeCAD does
not write this one, so it lands wherever the agent runs — deliver it into the project
folder explicitly (see Session setup).

Slicer-facing design decisions (orientation, prime tower, materials, clearances) live in
`fdm-design.md` — consult it, not memory.
