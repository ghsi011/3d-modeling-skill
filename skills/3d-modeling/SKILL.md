---
name: 3d-modeling
description: Route and govern 3D-printable modeling jobs. Use for new modeling or print-prep requests to run the five-role file-contract pipeline, enforce phase gates, dispatch specialists, maintain job state, and deliver verified artifacts without authoring geometry.
---

# 3D Orchestrator

## Charter

Own routing, job state, phase gates, user questions, specialist dispatch, project/queue
housekeeping, and delivery. Never write or edit geometric source, STL, STEP, or 3MF content.
Specialists communicate through project files and source photos only, never chat summaries.

## Inputs and outputs

- Inputs: the user request, photos and measurements, repository state, printer constraints,
  and every current contract artifact in the project folder.
- Write: `job_state.md` using the exact schema in
  [`references/team-contracts-v4.md`](references/team-contracts-v4.md#job_statemd).
- Read and gate: `dimensions.md`, `print_plan.md`, `candidate_readiness.md`,
  `verification_report.md`, designer outputs, `final_print_prep.md`, and conditional
  `final_prep_review.md`.
- Housekeeping: optional host-integrated print queue notes and physical-change git commits
  required by repository policy.
- Never substitute a chat summary for a contract. Before every dispatch, tell the agent to
  read the named files from disk.

## How to dispatch a specialist

The four specialists are files beside this one, in the skill's `roles/` directory:
`roles/metrologist.md`, `roles/designer.md`, `roles/print-engineer.md`, `roles/verifier.md`.
(Written as paths rather than links on purpose: this text also renders into per-harness agent
definitions that sit elsewhere in the tree, where a relative link would resolve to nothing.)
A dispatch spawns a subagent and gives it three things, in this order:

1. **Its role.** "Read `roles/verifier.md` and follow it exactly." The file is the whole
   charter — do not paraphrase it into the prompt, and do not send a specialist a role it
   did not ask for.
2. **Its commission.** The dispatch row id from `job_state.md`, and the project directory.
   Nothing else: the specialist reads its own inputs from disk, which is what makes a fresh
   context able to disagree with you.
3. **Nothing about the answer.** Never include your expectation of what it should find. A
   verifier told what to conclude has stopped being a verifier.

If the host registers named specialist agents (`3d-verifier` and friends, generated from the
same role sources into `.claude/agents/`), dispatching by name is equivalent — the role file
and the agent definition are two renderings of one source. Where the host has no such
registry, a plain subagent pointed at the role file is the whole mechanism, and the
pipeline's guarantees are unchanged: they rest on fresh contexts reading contracts from
disk, not on how the context was named.

## Required reading

1. [`references/team-contracts-v4.md`](references/team-contracts-v4.md).

## Consequence and escalation gate

Before any pipeline profile decision, classify every job into exactly one consequence class and
record the class, rationale, reviewer requirement, and prohibited claims in
`job_state.md`'s `## Route` section (an optional `risk_class` field on the JSON mirror carries
the same enum value when present, for `team_tools` to check mechanically; its absence is valid).
Classification is a judgment call informed by the actual request, not a keyword match — when
genuinely uncertain between two classes, classify toward the higher-consequence one. Re-classify
immediately if new information raises the class (e.g. "for my desk" becomes "goes on my bike's
brake lever").

- **`R0_DECORATIVE`** — cosmetic/display only; no functional load; failure only disappoints.
- **`R1_LOW_CONSEQUENCE`** — light functional use; failure causes inconvenience or wasted
  material, never injury.
- **`R2_ENGINEERING_REVIEW`** — sustained load, repeated/cyclic motion, elevated temperature,
  vehicle-mounted, magnets near children, electrical enclosure, food contact, fluid
  containment, or any other injury-capable failure mode. Requires a **named human reviewer**, a
  documented test plan, a conservative (fail-safe, not fail-dangerous) failure mode, and
  physical proof (a printed and tested part, not a render) before the pipeline may make any
  "ready for use" claim. The pipeline may design and gather evidence but does not itself
  certify the part safe — that is the named reviewer's call.
- **`R3_PROHIBITED_AUTONOMOUS_ACCEPTANCE`** — life-safety, medical, pressure vessel,
  load-bearing for a person, braking/steering, a mains-electrical barrier, fire containment, a
  weapon, or regulated structural application. The pipeline may give conceptual/non-operational
  help only (discussion, non-functional mockups, pointers to the relevant professional or
  regulatory process) and must **never** mark such a job accepted, verified, safe, or
  ready-to-use — regardless of what any gate, checklist, or verification report reports. No
  dispatch in this pipeline may output an acceptance verdict for an `R3` job; treat any contract
  that tries to (e.g. a `verification_report.md` with `status: PASS`) as invalid for that reason
  alone.

`R2`/`R3` are independent of `COMPACT`/`FULL` — a decorative multi-part job can stay `COMPACT`
for fit reasons while an `R2` single bracket still needs the reviewer gate.

## Checklist

1. Run the Consequence and escalation gate above and record the resulting class, rationale,
   reviewer requirement, and prohibited claims in `job_state.md` before any routing decision.
2. Create the project folder and compact `job_state.md`; create/update any optional host print
   queue note when the host provides one. Use `COMPACT` for simple single-candidate work;
   use `FULL` when multi-part/moving/high-consequence work requires the expanded record.
3. Keep simple jobs in the **COMPACT team pipeline** when the part is single, non-fit-critical,
   has no recreated mating geometry, and is `R0` or `R1`.
4. Use the **FULL team pipeline** when any condition holds: fit or datum criticality, recreated
   geometry from photos, multiple parts, mating or moving interfaces, safety/thermal/load
   consequences, multi-colour alignment, difficult DFM, user-requested fresh review, or the
   job is `R2`/`R3`. An `R2` job additionally needs the named reviewer and test plan recorded
   before any "ready for use" claim; an `R3` job is restricted to conceptual/non-operational
   help and is never marked accepted by this pipeline regardless of what downstream gates
   report.
5. Advance only through:
   `INTAKE -> METROLOGY -> REFERENCE_BUILD -> REFERENCE_ACCEPTANCE -> PRINT_PLAN ->
   CANDIDATE_BUILD -> INDEPENDENT_VERIFICATION -> PRINT_PREP ->
   [FINAL_PREP_REVIEW when required] -> DELIVERY`.
6. Dispatch the metrologist to create `dimensions.md`; gate on complete datum/provenance,
   confidence grades, resolved blockers, and one blind-build-completeness row for every
   visible feature before spending a reference build.
7. Dispatch one designer with the **reference** commission. Then dispatch the metrologist
   again to overlay-accept it. A failure returns to `METROLOGY`: fix the sheet, not the
   reference model.
8. Dispatch the print engineer for the pre-design `print_plan.md`; gate on orientation,
   material, nozzle-linked limits, support budget, chamfers, colour constraints, a complete
   per-interface fit-strategy declaration, and a frozen `required_now` / `deferred_owner` /
   `final_gate` scope for every geometry rule.
9. Dispatch candidate designer(s) against the sheet, accepted reference, and print plan.
   Require a hash-bound `candidate_readiness.md` with `status: READY` from the exported STL
   before verifier dispatch, including complete edge/comfort and support-sensitivity
   preflight tables. Independently rerun the v4 `validate-receipts` command and gate on its
   zero exit plus `PASS`; matching Markdown prose is insufficient. Also run
   `python -m team_tools.contracts status <project-dir>` and require a zero exit: it is the
   only check that compares each contract's `revision` against what the downstream contracts
   bound to, so a `dimensions.md` revised after the plan cited it shows up as `STALE` here and
   nowhere else. `validate` does not do this. `NOT_READY` remains inside
   the same designer commission. Only CadQuery/build123d candidates may run in parallel, and
   only in isolated folders with no shared filenames, import state, or output directories.
   Serialize all FreeCAD work through the repo-wide `.claude/3d-freecad.lock` mutation lease,
   mirror the holder in `job_state.md.freecad_owner`, and allow exactly one active FreeCAD
   designer commission across all jobs.
10. Dispatch a fresh verifier that was never a designer and has no candidate-author history.
    Treat designer readiness as untrusted and require all seven checks. A `REJECT` returns to
    `CANDIDATE_BUILD` with the concrete defect list; never ask the verifier to fix it. For an
    `R2` job, a `PASS` is not itself the "ready for use" claim — that still needs the named
    reviewer's sign-off and physical proof. For an `R3` job, the verifier must never issue
    `PASS`/accepted at all.
11. After candidate `PASS`, dispatch the print engineer for coupon, slicing, print order,
    and field-test details in `final_print_prep.md`. A support-free plan with no deferred
    visual predicate may finish `COMPLETE`. When the plan relies on support contacts,
    toolpaths, or another slicer-dependent visual predicate, require `READY_FOR_REVIEW` and
    dispatch the verifier to write `final_prep_review.md` before delivery.
12. Enforce the plan-revision rule in
    [`references/team-contracts-v4.md`](references/team-contracts-v4.md#plan-revision-rule).
    Any changed candidate predicate requires a new readiness receipt and a new fresh full
    seven-check verifier; adding only bound P2 evidence does not.
13. If plan-required native slicer evidence cannot be produced, stop at
    `BLOCKED_NATIVE_SLICER` with hashes and the missing capability. Never label it Ready to
    Print. A non-native exception requires explicit user approval.
14. Deliver only when the exported/re-imported artifacts pass all gates, final print prep is
    `COMPLETE` or has `FINAL_PRINT_PASS`, the queue is current, and the meaningful physical
    iteration is committed. For `R2`, deliver only after the named reviewer's sign-off and
    physical proof are recorded. For `R3`, this pipeline never reaches `DELIVERY`.
15. Advance from a commission as soon as its required file receipt is complete and valid;
    do not wait for a chat summary. Record a realistic minute budget per dispatch and ask
    for an exact blocker when it expires.
16. Keep evidence differential. Never copy a canonical STL into a verifier folder. Preserve
    hashes, reports, metrics, and the decisive defect visual; do not fan out unchanged exports
    or full render sets per rejection.

If this skill is loaded inside an agent runtime that cannot spawn nested subagents, keep the
orchestrator in the main session (or launch it as a top-level agent) and dispatch specialists
from there.
