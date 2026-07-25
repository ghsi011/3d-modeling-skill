# designer_toolkit — one call, not a menu

You write the parametric geometry and make every judgment call. The deterministic
Phase-4 work — export, re-import, measurement, orientation screening, boolean fit,
edge measurement, datum extraction, rendering — is a tested library behind a single
command. Run it and read what it says.

Runs from `skills/3d-modeling/scripts/`.

## The one call

```bash
python -m designer_toolkit commission --model model.py --plan print_plan_checks.json   --out . --job-id <job> --updated-utc <iso8601> [--reference mating.stl] [--no-render]
```

First it checks what needs no geometry. If `model.py` exposes a module-level `PARAMS` dict,
the pre-build stage reads it and stops before the first CAD call when the numbers already
settle the question — a wall under two extrusion widths, a cavity mouth fillet larger than the
clearance it eats (the boundary is exactly `clearance >= radius`; one run bisected four full
build/export/measure cycles toward it), an edge treatment at half the wall or more, or a
declared overall size that disagrees with the plan. A model with no `PARAMS` gets a visible
`SKIPPED`, never a silent pass.

Then it exports, re-imports, and measures the whole set on the mesh that actually ships:

- single watertight solid, and one body rather than phantom shells
- overall size against the plan's `expected_bbox_mm`
- downward-facing area for **every** support rule, each screened in the orientation
  that rule declares via `model_to_printer_matrix` — not in whichever orientation
  happens to look best
- seated per-side clearance against each declared interface band, in millimetres,
  which is the unit the band is written in; over-clearance fails exactly as
  interference does
- every plan-named edge, against both ends of its band

Then it writes `commission.json`, `artifact_manifest.json` and
`candidate_readiness.md`, and exits non-zero if any check failed. Each failure names
the action to take. Iterate until it exits zero.

A verifier runs the same command with `--stl` against the delivered file, into its own
output directory. That is an independent recomputation: the input it distrusts is the
designer's `commission.json`, and this never reads it.

## Do not hand-roll it

Re-implementing these by hand costs about an hour a job and re-introduces the exact
failures the library already solved: stale hashes, phantom shells, the `to_2D()`
datum-frame trap, a measuring routine that reads high against its own nominals, and
evidence describing a mesh you no longer ship. One archived run widened its own
acceptance bands until its hand-written sampler's wrong numbers passed.

The same applies to the receipts. `artifact_manifest.json` and
`candidate_readiness.md` are generated from the measurements above; retyping those
numbers is how a receipt starts describing a different mesh.

Every function is still importable — `export_and_hash`, `measure`, `datum_features`,
`overhang_area`, `interference`, `insertion_sweep`, `fit_coupon`, and
`designer_toolkit.render` — for the rare case that genuinely needs one directly. That
is not the normal path, and reaching for it to rebuild a check the gate already
performs is the mistake this file exists to prevent.

## Starting points that know their own topology

```python
from designer_toolkit.templates import box_shell, panel, bolt_boss, stack

built = box_shell(inner=(120, 80, 60), wall=3.0, floor=3.0)   # body, enclosure, tray
part, PARAMS = built.part, built.params
```

`box_shell`, `panel` (a plate with rectangular or round openings), `bolt_boss`, and `stack`
(several parts laid out for one plate). Each returns geometry *and* the `PARAMS` describing it,
computed from the same arithmetic that built the solid — so `wall_mm` is the wall that exists
and `overall_mm` is the size the part came out, neither able to drift the way a hand-maintained
dict can.

The point is not saved typing, it is that a hand-written model cannot be *asked* anything.
`panel` reports the narrowest material left between its openings and the panel edge, so a plate
whose holes leave a 0.6 mm rib fails the pre-build wall check for free. Nothing downstream
would have caught it: that plate is watertight, exactly the right size, and unprintable.

They build with trimesh and manifold booleans, so they need no CAD kernel and feed `commission`
unchanged, and they return the part seated on the bed. A part needing kernel-only features —
true fillets, lofts, threads — is written in the commissioned backend, and then `PARAMS` is
yours to declare.

## The fit coupon

```bash
python -m designer_toolkit coupon --plan print_plan_checks.json --out coupon.stl
```

A multi-lane coupon from the plan's declared interfaces. Genuinely separate work: a
physical test artifact, not a check on the candidate.

## Verification is backend-neutral

Once the exported mesh exists the CAD kernel is irrelevant, because every
deterministic check reads that mesh. `commission` never trusts the kernel's own
numbers — `.val().Volume()` misreports on periodic splines, and OCC can split one
solid into phantom shells.

## What is still yours

Interpreting photos, choosing datums and geometry, choosing the fit and manufacturing
strategy, and the accept/reject decision. `commission.json` leaves `visual_accept` and
`fit_band_ok` null on purpose, and `candidate_readiness.md` leaves them blank: a green
mechanical bundle is **necessary, not sufficient**. No number in it distinguishes a
correct part from a plausible wrong one — look at the renders before trusting any
single scalar.
