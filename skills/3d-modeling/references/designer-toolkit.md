# designer_toolkit — one call, not a menu

You write the parametric geometry and make every judgment call. The deterministic
Phase-4 work — export, re-import, measurement, orientation screening, boolean fit,
edge measurement, datum extraction, rendering — is a tested library behind a single
command. Run it and read what it says.

Runs from `skills/3d-modeling/scripts/`.

## Before anything

```bash
uv run --project <skill> --frozen python <skill>/scripts/dt.py doctor
```

Names the interpreter, which CAD backends it has, what each absent extra costs, and the
launcher's own absolute path — a capability discovered by failure costs a round trip every
time, and so does reconstructing an invocation. Exits non-zero only when `commission`
genuinely cannot run here.

**Invoke `dt.py` by absolute path, from your project directory.** Every measured designer run
hit the same snag — the module form only resolves when the working directory is this
`scripts/` folder, while the job's files live elsewhere — and every one of them wrote the same
workaround: a `verify.py` shim in the job folder that hardcodes this path, patches `sys.path`
and calls the gate itself. Those shims added no checks. `dt.py` exists so nobody writes
another.

## The one call

```bash
uv run --project <skill> --frozen python <skill>/scripts/dt.py commission --model model.py   --plan print_plan_checks.json --out . --job-id <job> --updated-utc <iso8601>   [--reference mating.stl] [--no-render]
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

Point `--out` at the project directory itself. The receipts are contracts, and the contract
gate resolves them by exact path without searching subdirectories, so receipts written below
the project are invisible to it however correct their content.

Then it renders a section and an eight-view exterior sheet, writes `commission.json`,
`artifact_manifest.json` and `candidate_readiness.md` -- the manifest listing the renders it
produced -- and exits non-zero if any check failed. Each failure names
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
`overhang_area`, `interference`, `fit_coupon`, and
`designer_toolkit.render` — for the rare case that genuinely needs one directly. That
is not the normal path, and reaching for it to rebuild a check the gate already
performs is the mistake this file exists to prevent.

## Starting points that know their own topology

```bash
uv run --project <skill> --frozen python <skill>/scripts/dt.py templates      # what they cover, and the call for each
```

```python
from designer_toolkit.templates import box_shell

built = box_shell(inner=(120, 80, 60), wall=3.0, floor=3.0)
part, PARAMS = built.part, built.params
```

That model is four lines, and the whole deterministic path from it — build, export,
re-import, every check, both receipts — measures about one second.

`box_shell`, `panel` (a plate with rectangular or round openings), `device_case`, `c_clip`,
`bolt_boss`, and `stack` (several parts laid out for one plate). Each returns geometry *and*
the `PARAMS` describing it,
computed from the same arithmetic that built the solid — so `wall_mm` is the wall that exists
and `overall_mm` is the size the part came out, neither able to drift the way a hand-maintained
dict can.

`device_case` goes further and returns the **mating reference** built from the same numbers,
seated where the device actually sits, with the clearance uniform on every side including
underneath. Two archived runs hand-wrote a device proxy beside their case; one debugged a
false interference caused by forgetting to round its corners, and another added a relief gap
by hand because a device resting flush on the cavity floor reads zero clearance however
correct its walls are. A reference derived from the cavity's own arithmetic cannot describe a
different device from the cavity.

`c_clip` encodes an orientation decision rather than a shape. A horizontal round bore carries
an unsupported crown that no surrounding geometry removes — four runs each rediscovered that,
one of them across three build cycles — so the channel axis stands along Z and every wall
becomes a vertical extrusion. The part is self-supporting by construction instead of by a
designer choosing the right orientation.

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
uv run --project <skill> --frozen python <skill>/scripts/dt.py coupon --plan print_plan_checks.json --out coupon.stl
```

A multi-lane coupon from the plan's declared interfaces. Genuinely separate work: a
physical test artifact, not a check on the candidate.

## Verification is backend-neutral

Once the exported mesh exists the CAD kernel is irrelevant, because every
deterministic check reads that mesh. `commission` never trusts the kernel's own
numbers — `.val().Volume()` misreports on periodic splines, and OCC can split one
solid into phantom shells.

## Verifying: `dt.py audit`

    uv run --project <skill> --frozen python <skill>/scripts/dt.py audit <project-dir> --out <your-own-dir>         --job-id <job> --updated-utc <iso8601> [--reference mating.stl]

One call for the whole mechanical half: the hash binding between the delivered
STL and the receipt that claims to describe it, the raw un-repaired parse, an
independent recomputation compared check-by-check against the designer's, and
both contract checks. It refuses to write into the project root, because the
receipts it compares against are what a run there would overwrite.

One call, because the pipeline's cost is agent turns rather than arithmetic: a
measured dispatch spent 6 min 25 s running four commands totalling 4.4 seconds
of work.

Its `still_requires_a_look` field is the honest part: nothing in the call reads
`dimensions.md`, and no measurement is taken of a feature nobody declared. Both
defects this pipeline has shipped were invisible to every number and obvious in
a render.

## Everything else the launcher offers

The launcher has fifteen verbs. Every one is listed here, because a charter that
tells a reader to run something this file does not mention is a dead end.

| verb | what it is for |
|---|---|---|
| `intake` | `job_state.md` and `dimensions.md` for a job, judgments left blank |
| `build` | `model.py` for a template-covered part, parameters checked by building once |
| `plan template` / `plan check` | the built-in DIRECT plan, and the gate that rejects an unbuildable one before a build |
| `probe` | ask the delivered solid a question: section area, a hole's size **and position**, the slice profile |
| `screen` | the one question no check can ask: what is here that nobody declared |
| `report` | draft `verification_report.md` from the verifier's own numbers, judgments blank |
| `integrity` | the raw, un-repaired parse of a delivered mesh |
| `crop` | `crop` / `contact-sheet` / `rotations` -- zoom evidence without hand-rolling it |
| `validate` / `status` | the contract checks, reachable from anywhere rather than only from the scripts directory |

Two of those exist because of a defect rather than a feature. `probe` exists because the
charter told a verifier to compare the sheet against geometry *and* not to hand-roll
anything, with no way to do the first without the second -- and a part shipped with its
holes 0.25 mm out of place while every check agreed, because each measured a correct hole at
the position the designer declared. `validate` and `status` route through the launcher
because `python -m team_tools.contracts` only resolves with the scripts directory on
`sys.path`: fine from the repo, broken from an installed bundle.

## What is still yours

Interpreting photos, choosing datums and geometry, choosing the fit and manufacturing
strategy, and the accept/reject decision. `commission.json` leaves `visual_accept` and
`fit_band_ok` null on purpose, and `candidate_readiness.md` leaves them blank: a green
mechanical bundle is **necessary, not sufficient**. No number in it distinguishes a
correct part from a plausible wrong one — look at the renders before trusting any
single scalar.
