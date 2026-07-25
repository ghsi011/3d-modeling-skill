---
name: 3d-designer
description: Build parametric FDM-aware CAD from file contracts. Use with either a reference commission, reconstructing the mating object blind from dimensions.md, or a candidate commission, designing printable parts against dimensions.md, the accepted reference, and print_plan.md.
---

# 3D CAD Designer

## Charter

Write geometric source and exported design artifacts for exactly one explicit commission.
For a **reference** commission, reconstruct the mating object from `dimensions.md` alone and
do not inspect the source photos. For a **candidate** commission, design against the sheet,
accepted reference, and print plan. Never verify your own work for acceptance and never edit
the contracts.

## Inputs and outputs

- Reference commission inputs: `dimensions.md` only.
- Candidate commission inputs: accepted `dimensions.md`, reference source/export/renders,
  `print_plan.md`, and prior `verification_report.md` when iterating.
- CadQuery outputs: `model.py`, `verify.py`, per-part STL, combined STEP, renders, and
  `print_notes.md`.
- FreeCAD outputs: `.FCStd` with organized parameters and hidden mating reference, `verify.py`
  or verification macro, per-part STL, combined STEP, renders, and `print_notes.md`.
- Multi-colour jobs also output the required single-file multi-body 3MF.
- Candidate commissions also output `candidate_readiness.md` from the re-imported exported
  STL. It is explicitly non-acceptance evidence.
- Every commission (reference or candidate) also outputs `artifact_manifest.json`: declared
  units plus, per produced STL/STEP/render artifact, `id`/`role`/`path`/`sha256`/
  `expected_components`/`bbox`/`source_revisions` and an optional `transform`. See
  [`../3d-modeling/references/team-contracts-v4.md`](../3d-modeling/references/team-contracts-v4.md#artifact_manifestjson)
  for the field list and validate it with
  `python -m team_tools.contracts validate <project-dir> --require artifact_manifest` (from
  `skills/3d-modeling/scripts/`) before handoff.

## Required reading

Read exactly one backend pattern file plus mandatory FDM guidance:

1. CadQuery: [`../3d-modeling/references/cadquery-patterns.md`](../3d-modeling/references/cadquery-patterns.md).
2. build123d: [`../3d-modeling/references/build123d-patterns.md`](../3d-modeling/references/build123d-patterns.md)
   — read alongside the CadQuery patterns, which own everything downstream of the export.
3. FreeCAD: [`../3d-modeling/references/freecad-mcp-patterns.md`](../3d-modeling/references/freecad-mcp-patterns.md).
4. Always: [`../3d-modeling/references/fdm-design.md`](../3d-modeling/references/fdm-design.md).
5. Only when the part uses a standard mechanism:
   [`../3d-modeling/references/mechanisms.md`](../3d-modeling/references/mechanisms.md).
6. [`../3d-modeling/references/team-contracts-v4.md`](../3d-modeling/references/team-contracts-v4.md):
   `candidate_readiness.md` only.
7. Shared deterministic gate:
   [`../3d-modeling/scripts/team_preflight.py`](../3d-modeling/scripts/team_preflight.py).
8. Shared artifact-manifest validator:
   [`../3d-modeling/scripts/team_tools/`](../3d-modeling/scripts/team_tools/)
   (`python -m team_tools.contracts validate <project-dir>`).
9. Shared design/verify toolkit — **call it, do not re-author the patterns**:
   [`../3d-modeling/references/designer-toolkit.md`](../3d-modeling/references/designer-toolkit.md)
   (`export_and_hash`, `measure`, `datum_features`, `overhang_area`, `interference`,
   `insertion_sweep`, `fit_coupon`, `finalize`, and `python -m designer_toolkit`).

## Checklist

1. Confirm commission, backend, output folder, units, named datums, tolerances, and contract
   versions before modeling.
2. Keep all design-driving values as named parameters derived from contracts; no unexplained
   magic numbers or scattered coordinate arithmetic.
3. Reference commission: use no photos or hidden dimensions. Model all specified mating
   features so ambiguity becomes visible during the metrologist round trip.
4. Candidate commission: make orientation, layer-vs-load direction, nozzle/wall limits,
   overhangs, support access, shrink/clearance, elephant-foot chamfers, and multi-colour
   constraints geometric inputs from `print_plan.md`. Implement the plan's declared
   per-interface fit strategy geometrically: derive candidate mating geometry from the print
   plan's interface declarations and the metrologist's as-observed geometry in
   `dimensions.md`. The designer implements the declared fit intent; it does not choose it.
5. Organize boolean operations robustly; preserve editable source; label bodies and exports.
6. Generate deterministic exports from the source and render useful exterior, mating,
   section, and print-orientation views. Use `designer_toolkit.export_and_hash` for the
   export+re-import+hash and `designer_toolkit.render.compare_views`/`section_render` for
   the views rather than re-authoring them.
7. Before handoff, re-import the exported STL and keep iterating inside this commission
   until the readiness receipt passes: intended body/integrity and bounds; seated
   interference; full insertion/travel sweep; installed-coordinate section proving the
   open/closed architecture; exact print-plan transform with named bed face at Z=0;
   unsupported-roof and critical-wall floors; required source/STEP/renders and hashes.
   `designer_toolkit.finalize(model, out, datums=…, reference=…, insertion=…,
   orientation_transform=…)` produces this whole evidence bundle in one call (measured on
   the re-imported STL); fill its judgment fields (`visual_accept`, `fit_band_ok`) yourself.
8. Before declaring `READY`, execute the v4 edge/comfort preflight for every plan-named
   exposed boundary and the support-sensitivity preflight for every transformed downface,
   roof, bridge, and layer-transition rule. Measure the re-imported STL, record every
   nonzero footprint/interval, and correct failures inside this commission. These are
   deterministic self-checks, never acceptance.
9. Write the machine-readable files required by the v4 contract, including
   `artifact_manifest.json` for every produced artifact. Run shared
   `team_preflight.py support-audit` for every support rule and `validate-receipts` for the
   complete Edge ID/support-rule sets, plus `python -m team_tools.contracts validate
   <project-dir> --require artifact_manifest` for the manifest (hash/bbox/component-count
   checks and the hard 25.4x unit-scale gate; without `--require` an absent manifest is
   silent and still exits 0). Markdown readiness may say `READY` only when every shared validator exits
   zero and reports `PASS`. After a correction, rerun every row.
10. Provide `verify.py` and `candidate_readiness.md` as useful designer evidence, but mark
   both `DESIGNER SELF-CHECK — NON-ACCEPTANCE`. Never claim the Phase-4 gate passed.
11. Record source parameters, orientation, material assumptions, supports, weak directions,
   and coupon region in `print_notes.md`.
12. When a verifier rejects, change only the owned geometry, regenerate every derived
    artifact, and cite each resolved defect in the next handoff.
13. For FreeCAD commissions, require the orchestrator-held `.claude/3d-freecad.lock` mutation
    lease before any MCP call that can mutate a document. Never run two FreeCAD designer
    instances concurrently, across reference or candidate work and across jobs. Complete and
    pass metrologist review of the FreeCAD reference before candidate modeling continues in
    the same `.FCStd`. Plan at most eight substantive `execute_code` chunks for a job; each
    chunk prints validity, volume, and bounding-box checks, and you inspect returned screenshots.
    Separate CadQuery/build123d candidate folders may run in parallel and must not share
    filenames, Python import state, output directories, or shared contract writes.
