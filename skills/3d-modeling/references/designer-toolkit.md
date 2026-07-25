# designer_toolkit — call it, don't re-author it

The deterministic Phase-4 work — export + re-import, measurement, datum
extraction, overhang screening, boolean fit, coupon generation, rendered
comparison — is a tested library. **Call it.** Do not paste the raw trimesh/OCC
patterns into a fresh `verify.py` and re-debug them every job; that re-debugging
(stale hashes, phantom shells, the `to_2D()` datum-frame trap, a self-check that
disagrees with the gate) is exactly what used to make the design step take an hour.
You still write the parametric geometry and make every judgment call — the toolkit
does the mechanical measuring.

Runs from `skills/3d-modeling/scripts/`. Import as a package, or use the CLI.

## One call for the whole readiness bundle

```python
import sys; sys.path.insert(0, '<skill>/scripts')
import cadquery as cq
from designer_toolkit import finalize

body = cq.Workplane("XY").box(40, 30, 20, centered=(True, True, False))  # your model
ev = finalize(
    body, "out/body",                       # writes out/body.stl (+ .step)
    datums=[{"name": "camera_window", "plane_origin": (0, 0, 1.0)}],
    reference="out/ref.stl",                # seated mating mesh (optional)
    insertion={"travels": [5, 15, 25, 35, 45], "axis": (0, 0, -1)},
    orientation_transform=None,             # 4x4 model->printer for the overhang screen
)
# ev["export"]        watertight / components / volume / bbox / file+geometry sha256
# ev["overhang_mm2"]  downward area past the -0.73 screen (SAME threshold as the gate)
# ev["datums"]        hole+outline centres in MODEL coords, per datum plane
# ev["seated_interference_mm3"], ev["insertion_sweep"]
# ev["readiness_skeleton"]  auto_notes + the judgment fields you must fill:
#   visual_accept (LOOK at the render), fit_band_ok (print engineer / your call)
```

`finalize` re-imports the exported STL and measures THAT — never the CAD kernel's
own numbers (`.val().Volume()` misreports on periodic splines; OCC can split one
solid into phantom shells). `is_single_watertight_solid()` and `auto_notes` flag
both automatically.

## Individual helpers (when you don't want the whole bundle)

```python
from designer_toolkit import (
    export_and_hash, measure, datum_features, overhang_area,
    interference, insertion_sweep, fit_coupon,
)
rep  = export_and_hash(body, "out/body")            # ExportReport (re-imported, hashed)
m    = measure("out/body.stl")                      # bbox/volume/watertight/components
feat = datum_features("out/body.stl", (0, 0, 1.0))  # holes/outlines in MODEL coords
over = overhang_area("out/body.stl")                # mm^2 past the -0.73 screen
i    = interference("out/body.stl", "out/ref.stl")  # seated overlap volume (mm^3)
sw   = insertion_sweep("out/body.stl", "out/ref.stl", [5, 15, 25], axis=(0, 0, -1))
stl, legend = fit_coupon(                            # multi-lane coupon from the plan
    [{"id": "bore", "nominal_mm": 12.9, "kind": "hole"}], "out/coupon.stl")
```

`datum_features` already passes `plane_transform`, so hole centres come back in
model X/Y — compare each to its Phase-2 datum. A mirrored layout fits the same
magnitudes, so also compare with the u-coordinate negated when handedness is open.

## Rendered comparison (needs a pyrender/GL context)

```python
from designer_toolkit.render import compare_views, section_render
compare_views("out/ref.stl", "out/body.stl", "out/compare.png")  # ref row over cand row
section_render("out/body.stl", "out/section.png", plane_normal=(1, 0, 0))
```
Then LOOK at the image — silhouette, feature shapes, counts, positions — before
trusting any single number.

## CLI (run checks from a shell, no Python file)

```bash
python -m designer_toolkit measure body.stl
python -m designer_toolkit overhang body.stl --threshold -0.73
python -m designer_toolkit datums body.stl --z 1.0
python -m designer_toolkit interference body.stl ref.stl
python -m designer_toolkit sweep body.stl ref.stl --travels 5,15,25,35
python -m designer_toolkit finalize body.stl --plan plan.json     # full evidence bundle as JSON
```

## What is still yours (the toolkit will not do it)

Interpreting photos, choosing datums and geometry, choosing the fit/manufacturing
strategy, and the accept/reject decision. `finalize` leaves `visual_accept` and
`fit_band_ok` as `None` on purpose — a green mechanical bundle is **necessary, not
sufficient**; the gate (`team_preflight`) and the human still decide acceptance.
