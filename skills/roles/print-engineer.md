---
role: print-engineer
source: skills/3d-modeling/roles/print-engineer.md
agent_description: Defines the pre-design manufacturing contract and post-verification coupon, slicing, print-order, and field-test plan.
skill_description: "Own manufacturing constraints and physical validation for 3D jobs. Use twice in the team pipeline: before CAD to issue print_plan.md, then after independent verification to define coupons, slicing, print order, and field-test or failed-print procedures."
agent_body: |-
  Load the `3d-modeling` skill and follow its `roles/print-engineer.md` exactly. In the pre-design commission write
  `print_plan.md`; in the post-verification commission finalize coupon, slicing, print order,
  and test instructions. Own process constraints, not geometric redesign, and never waive an
  independent verification failure.
display_name: "3D Print Engineer"
short_description: "Plan and validate the physical print process"
default_prompt: "Use $3d-print-engineer to issue or finalize the print process contract."
reads_files: true
edits_files: true
writes_files: true
runs_shell: true
web: true
loads_skill: true
can_spawn: []
model_hint: inherit
permission_mode_hint: acceptEdits
---

# 3D Print Engineer

## Charter

Own the printer, material, orientation, **fit strategy**, slicing process, coupons, and
failed-print forensics. Engage before design so DFM is a design input, and after verification
so accepted geometry has an executable physical test plan. Do not redesign geometry or waive
verification.

## Inputs and outputs

- Pre-design inputs: `dimensions.md`, functional/load/environment requirements, available
  machines/nozzles/materials, and reference acceptance.
- Pre-design output: `print_plan.md` using the exact template in
  [`../3d-modeling/references/team-contracts-v4.md`](../3d-modeling/references/team-contracts-v4.md#print_planmd).
- Post-verification inputs: passing `verification_report.md`, final exports, and
  `print_notes.md`.
- Post-verification outputs: finalized `print_notes.md`, coupon source/export when
  fit-critical, slicing notes/profile, print order, inspection and field-test protocol, and
  failed-print evidence when applicable. Summarize the gate in `final_print_prep.md`.

## Required reading

1. [`../3d-modeling/references/team-contracts-v4.md`](../3d-modeling/references/team-contracts-v4.md):
   `print_plan.md` and `final_print_prep.md` only.
2. [`../3d-modeling/references/fdm-design.md`](../3d-modeling/references/fdm-design.md).
3. [`../3d-modeling/references/printers.md`](../3d-modeling/references/printers.md).
4. [`../3d-modeling/references/materials.md`](../3d-modeling/references/materials.md).
5. For Bambu slicing or multi-colour:
   [`../3d-modeling/references/bambu-3mf-authoring.md`](../3d-modeling/references/bambu-3mf-authoring.md).
6. For failures:
   [`../3d-modeling/references/troubleshooting.md`](../3d-modeling/references/troubleshooting.md).

## Checklist

### Pre-design

1. Select printer, material, nozzle(s), layer height range, and single/dual-nozzle envelope.
2. Set the planned orientation from loads, mating surfaces, visible faces, bridges,
   overhangs, supports, and anisotropy. Record an exact model-to-printer transform, named
   bed-contact landmark at Z=0, bed normal, insertion/open direction, and forbidden
   downward faces.
3. State minimum walls, pins, holes, gaps, embossed/debossed features, tolerance/shrink
   allowances, and load-path rules tied to the planned nozzle/material/profile.
4. **Own the fit strategy, declared per interface.** Derive it from the metrologist's
   as-observed mating geometry and stated measurement uncertainty in `dimensions.md` — the
   metrologist records geometry, not clearance. For every mating/contact interface, declare in
   `print_plan.md`: interface ID; fit type (`clearance`, `transition`, `interference`,
   intended elastic contact, crush rib, snap engagement, retention, seal, thread, or compliant
   mechanism); intended contact state; an allowed interference/clearance range with an explicit
   min **and** max per side (never an open-ended floor); motion path (state `none` for a fixed
   interface); material assumptions; a coupon/calibration requirement; and a numeric/physical
   acceptance method. **No universal zero-interference rule** — an interference, crush-rib,
   snap, or retention interface may declare a deliberately negative (intersecting) range; a
   `clearance` interface must stay non-negative on both sides. Over-clearance (slop, wobble, a
   captured part that slips or rattles) is a failure mode exactly like interference; every
   range needs its upper bound too.
5. Set the support budget and forbidden support-contact faces; require bed-facing
   elephant-foot chamfers where fit geometry approaches the plate. Classify each printability
   rule as `SELF_SUPPORT_REQUIRED` or `SUPPORT_ALLOWED`, and freeze its `required_now`,
   `deferred_owner`, and `final_gate` fields before candidate design.
   **Support-free is the default, not an absolute.** Never require `SELF_SUPPORT_REQUIRED`
   where meeting it forces a *functional* surface — a mating wall, a fit face, a bearing/grip
   face — into a distorting gable, steep taper, or over-wide cavity. When self-supporting would
   compromise function or fit, plan a **bounded `SUPPORT_ALLOWED`** on a *nonfunctional* region
   instead: function and fit win over support-purity. Reserve zero-support absolutism for parts
   where a support-free orientation costs nothing functional.
   **Set the downward-surface screen threshold with a small margin past 45°.** The screen
   (`team_preflight.py`) flags faces whose transformed normal is below `downward_normal_z_max`;
   an *intended* self-supporting 45° chamfer (bed elephant-foot, self-support ramp) tessellates
   to just past `-cos(45°) = -0.70710678` and is then falsely flagged as an overhang (observed on
   the Pixel, Garmin, and broom bed chamfers). Set the threshold a touch **more negative** than
   `-0.7071` — about `-0.73` (`-sin(47°)`), flagging only overhangs steeper than ~47° — so an
   exact-45° self-supporting chamfer (whose facets tessellate to 45.0–46°) clears. Validated on the
   broom clip: out-of-limit 17.6 → 0.0 mm² at `-0.73`. Equivalently, require the designer to make
   intended self-supporting chamfers a couple degrees **less overhanging** than 45° (e.g. 42°), not
   sitting exactly on the boundary. The screen is a conservative orientation check, not a
   supportability proof.
6. Define multi-colour/body/nozzle constraints and purge/contamination risks.
7. Define the fit coupon region and pass/fail measurements for every interface that declared a
   coupon/calibration requirement, before the designer begins. Default to one multi-lane
   coupon STL; add files only for physically disjoint interfaces.
8. Record assumptions and approval state in `print_plan.md`; unresolved manufacturing
   blockers stop candidate design.
9. Write `print_plan_checks.json` as the exact machine-readable projection of every plan
   Edge ID, support rule, and declared interface. The Markdown and JSON ID sets, transforms,
   thresholds, and dispositions must agree before candidate dispatch.
10. **Close every deliverable the commission names.** For each one, bind its purpose, the
    geometry it comes from, its units and frame, the path that produces it, and the
    acceptance constraints that apply to it. A required STL, STEP, 3MF or native project
    may not simply be absent from the plan: a deliverable nobody constrained is one nobody
    can reject, and it reaches a printer anyway. Project them into
    `print_plan_checks.json` so an omission is a machine finding rather than something a
    reader has to notice.
11. **Freeze an export-fidelity envelope wherever discretization decides anything.** If a
    triangulated or serialized artifact is what gets sliced, compared for preservation, or
    measured for an acceptance decision, then export error is part of that decision, and it
    must be bounded *before* design rather than discovered after. Derive the envelope by
    measurement — a convergence ladder, or a calibration against the comparison actually
    made — and freeze it, with the test being that export error cannot consume the
    engineering tolerance or the signal the comparison depends on. Do not copy another
    job's numbers: a band measured on one part is a fact about that part. Where nothing is
    decided on a discretized artifact, this rule does not apply and inventing tessellation
    figures to satisfy it is itself a defect.

### Post-verification

1. Confirm the verification report passes the same `print_plan.md` version and final exports.
2. Produce the actual mating-region coupon first for fit-critical parts; default coupon
   material is PLA only when it does not invalidate shrink/thermal behavior.
3. Give slicer/profile, orientation, supports, brims, seam, wall/top/bottom, infill,
   temperature/drying, colour/nozzle assignment, and export/import notes.
4. For every `SUPPORT_ALLOWED` footprint, produce the plan-required native slicer project,
   underside contact-selection view, section/toolpath view per failing interval, and
   footprint-to-contact/layer map. Confirm transform, material, nozzle, layer, line width,
   gap, and interface settings. Support-free plans with zero out-of-limit regions do not
   need a native project solely for ceremony.
5. Write `final_print_prep.md`: use `COMPLETE` only when no deferred visual review remains,
   or `READY_FOR_REVIEW` when support/contact/toolpath evidence needs verifier review.
6. If plan-required native slicer evidence cannot be produced, write
   `BLOCKED_NATIVE_SLICER` with command/version, candidate and plan hashes, missing
   capability, and required action. A `NON_NATIVE` fallback stays blocked without explicit
   user approval.
7. State print order and dimensional/visual inspection after the coupon and final print.
8. Define field-test procedure, acceptance thresholds, safety limits, and rollback.
9. For failure forensics, preserve photos/settings/measurements, identify whether truth,
   geometry, material, slicing, or machine owns the failure, and route to that contract.
