---
name: 3d-modeling
description: Design 3D-printable parts with an FDM-aware workflow, using FreeCAD (via the FreeCAD MCP, on the user's machine) or CadQuery (code-first, runs anywhere Python does) — new designs, replacement parts, adapters, enclosures, brackets, knobs, print-in-place mechanisms, multi-color prints. Use whenever the user wants to design or modify anything for 3D printing, fit a part to an existing object or commercial product (phone, battery, SBC, appliance), fix a print that failed or doesn't fit, pick materials or orientation, or export STL/STEP/3MF — even if they only say "model this" or "make me a replacement". Printing mistakes cost hours and filament; this workflow front-loads the checks that prevent them.
---

# 3D modeling for FDM printing

Printed parts fail for two reasons: real-world geometry you never noticed, and designs that
ignore how FDM deposits plastic. The phases below close both. Track the phases with your
task/todo tool so the user sees progress.

Read before acting (only what the task needs):
- [references/freecad-mcp-patterns.md](references/freecad-mcp-patterns.md) — FreeCAD backend: when to pick it + tested code patterns
- [references/cadquery-patterns.md](references/cadquery-patterns.md) — CadQuery backend: when to pick it + tested code patterns
- [references/fdm-design.md](references/fdm-design.md) — before design decisions (indexed: printability, orientation, supports, fits, colors, materials, production rules)
- [references/mechanisms.md](references/mechanisms.md) — hinges, printed springs, flexures, magnets, pins
- [references/materials.md](references/materials.md) — filament picks, drying temps, support-interface pairings
- [references/troubleshooting.md](references/troubleshooting.md) — print-quality symptom → cause → fix, calibration order
- [references/printers.md](references/printers.md) — the user's machine, before slicing advice
- [references/bambu-3mf-authoring.md](references/bambu-3mf-authoring.md) — Phase 5 only: authoring a print-ready Bambu *project* 3MF (settings baked in, per-part filament), not bare geometry

## Phase 0 — Choose the backend

Two backends, one workflow. Pick once per part; never mix mid-part.

| | **FreeCAD** (MCP, user's desktop) | **CadQuery** (pip, this environment) |
|---|---|---|
| Pros | Parametric FCStd the user can open and edit; Params spreadsheet = one-cell fit fixes; GUI renders; outputs save directly to the user's disk | Runs anywhere Python does — no desktop dependency; cheap fast iteration; scriptable verification; headless previews |
| Cons | Needs desktop + FreeCAD + MCP addon running; every execute_code returns a ~10k-token screenshot (plan ≤8 chunks/job); one instance — jobs serialize | User edits a .py, not a GUI document; OCC pitfalls (fillet corruption, volume misreport — see patterns); every output must be delivered explicitly |
| Pick when | User wants an editable document, works in FreeCAD, or the job is an iterate-on-physical-fit project on their machine | No desktop connected, batch/cloud work, quick parts, or cost matters |

Availability check first: FreeCAD → `list_documents` succeeds (else ask the user to open
FreeCAD with the MCP addon). CadQuery → `python3 -c "import cadquery"` (else
`pip install cadquery trimesh pyrender Pillow`). Neither available → say so; never guess
geometry offline.

## Phase 1 — Understand the job

Ask what's missing, in one round of pointed questions:

- **Function & loads**: what it does, forces and their directions.
- **Environment**: heat (car? dishwasher? outdoors?), UV, moisture → dictates material.
- **Fit**: mates with a real object? Then Phase 2 is mandatory.
- **Known product?** If the mating object is a commercial product (phone, battery,
  Raspberry Pi/SBC, power tool, appliance part — anything with a model number):
  **web-search its official specs/drawings now**, cross-check two sources, record every
  dimension with its source next to the parameter. Also search MakerWorld / Printables /
  GrabCAD for existing 3D models of the product or of parts that mate with it — a
  published model is documentation AND a candidate reference fixture (import as ref).
  Specs cover the product family; photos + calipers still confirm the user's actual unit
  and variant.
- **Printer**: exact model. If it's not in printers.md, research its specs, strengths, and
  quirks now and persist a profile (procedure in printers.md). Nozzle count and chamber
  change the design strategy, not just the slicing.
- **Filaments on hand; visible faces; text/logos; color count.**
- **Project folder on their disk? Print queue to update?** (needed in Phase 5 — ask now,
  or reuse what they've already mentioned).

Gate: every fit-critical dimension is measured, sourced, or an assumption the user approved.

## Phase 2 — Master the mating object (fit jobs)

- Photos arrive as chat uploads or in a connected folder; inspect by re-reading cropped
  regions. No photos of the mating object → ask before proceeding.
- Inventory **every** feature from photos at max zoom: steps, collars, rails, ribs, clips,
  buttons, windows, tapers, D-flats, threads. Molded parts are never bare cylinders.
- Pin each measurement to a named feature; calipers read a solid collar and two rails
  identically. Ambiguous number → ask, citing the photo. Request missing dims concretely:
  what to clamp, from where to where.
- **Every cutout and pocket needs a position, not just a size** — record each feature's
  center from a named datum (e.g. "camera window: 5.5 right of centerline, 36.7 below top
  edge"). A correctly-sized window in the wrong place is a failed part.
- Commercial counterparts are documentation — every window/slot/tab mates with something.
- **Model the mating object first** (ref part, same document/script). Render beside the
  photos, compare silhouettes, get user confirmation before designing. It becomes the
  Phase 4 test fixture.
- **Recreating a part from photos?** Use the render-over-photo overlay loop
  (cadquery-patterns.md §overlay): draw the model's boundaries on the photo and iterate
  until they hug the features — overlays resolve millimeters where side-by-side viewing
  only catches gross mismatch. Do the same against iso/side photos for heights and ramps.

## Phase 3 — Design and build

- Choose **print orientation before modeling** (checklist in fdm-design.md); it drives
  chamfers, support avoidance, layer-vs-load direction, and where color layers land.
- **Design slicer-agnostic**: function lives in CAD, never in slicer settings. Prefer
  compliant fits (flex walls, grip fins, chamfered mates) over precision fits.
- Every measured dimension and clearance is a named parameter with unit + provenance
  (FreeCAD: aliased Params spreadsheet cells; CadQuery: PARAMETERS section) — a failed
  fit must be a one-line fix. Clearances from fdm-design.md §4 (per-side); tight fits get
  a printed test coupon before the full part.
- Build in small verified steps; after each boolean print validity, volume, bbox, and
  look at a render/preview.

## Phase 4 — Verify before export (all seven)

Any check fails → fix the model (parameter first), then re-run all seven.
Run the dimensional checks on the **exported STL re-imported** (trimesh), not only the CAD
solid — export paths and late chamfer/repair steps can silently change geometry (a slot
once grew 3 mm between model and export).

1. **Interference**: part ∩ ref-part volume ≈ 0 at seated position.
2. **Insertion path**: seated-clear ≠ insertable — intersect at stepped travel offsets.
3. **Section render**: cut the assembly in half, render, show the user.
4. **Visual side-by-side**: render the part from the SAME viewpoints as the user's photos
   (or reference model) and compose them into one image — then actually look: same
   silhouette? same feature shapes? same counts? Numbers pass parts that look nothing
   like the target; this check exists because that happened. (Patterns files have
   same-camera render + side-by-side compose snippets.)
5. **Feature positions**: every cutout/pocket center re-measured from its named datum on
   the exported STL and compared to Phase 2's recorded value. Size alone never passes a
   placement check — and check handedness: a mirrored layout fits the numbers too.
6. **Measurement audit**: every measured number appears in geometry; unused number =
   erased feature — stop and ask.
7. **Printability + face audit**: overhangs, bridges, thin walls, missing chamfers —
   against the chosen orientation; cylindrical radii + bbox vs expected.

## Phase 5 — Deliver

**Where files live**: FreeCAD writes to the user's disk directly (confirm the project
folder in Phase 1). Anything built in this environment — CadQuery outputs, the 3MF,
notes — must be delivered explicitly: SendUserFile every output, and if the user has a
connected project folder, also commit there (`device_commit_files`). A file left here
never reaches the user.

Deliverables: parametric source (FCStd with RefPart hidden / model.py with ref_part not
exported), per-part STLs (CadQuery: tolerance=0.01, angularTolerance=0.1), combined STEP,
renders/previews, `print_notes.md` (geometry summary, which parameter fixes which fit,
orientation + why, material + why, slicer settings, honest risks). Multi-color: run
[scripts/make_3mf.py](scripts/make_3mf.py) → one 3MF, per-part filament assignment.
For a **print-ready Bambu project 3MF** (settings baked in, not just geometry), use
[scripts/make_bambu_3mf.py](scripts/make_bambu_3mf.py) and follow
[references/bambu-3mf-authoring.md](references/bambu-3mf-authoring.md): round-trip the slicer
for the machine's keys, verify structurally, ship an after-import checklist (you can't
confirm the slicer accepts it without launching it).
If the user keeps a print queue (ask once in Phase 1, or reuse what they've mentioned),
update it now and on every design change; otherwise skip.

Propose a cheap PLA fit test before the final material — an hour vs an evening.

**Failed print = data**: photo where it stopped, measure the travel, diff against the
model — the stopping point names the missed feature. Fix the ref part first, re-verify,
re-export, record the lesson in print_notes.md. Quality defects (adhesion, stringing,
shifts, banding) → diagnose with troubleshooting.md, not guesswork.
