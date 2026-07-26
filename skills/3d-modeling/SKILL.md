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
(Written as paths rather than links on purpose: this text also renders into the generated
agent definitions under `.claude/agents/`, where a relative link would resolve to nothing.)
A dispatch spawns a subagent and gives it three things, in this order:

1. **Its role.** "Read `roles/verifier.md` and follow it exactly." The file is the whole
   charter — do not paraphrase it into the prompt, and do not send a specialist a role it
   did not ask for.
2. **Its commission.** The dispatch row id from `job_state.md`, and the project directory.
   The specialist reads its own inputs from disk, which is what makes a fresh context able to
   disagree with you. A named template is the one thing worth adding: it says which starting
   point exists, not what to conclude, and it is the largest measured difference in dispatch
   cost.
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

## Route profiles

A phase whose input does not exist cannot check anything, and every dispatch costs minutes.
So the profile is decided by one question — **what has to be recovered from evidence?** —
and it decides which phases run, not how verbose the record is.

- **`DIRECT`** — every design-driving dimension is stated by the user or a cited spec, and no
  real-world object is being recreated. Single part, `R0`/`R1`.
  `INTAKE -> PRINT_PLAN -> CANDIDATE_BUILD -> INDEPENDENT_VERIFICATION -> DELIVERY`,
  and `PRINT_PLAN` is you instantiating the shipped template, not a dispatch. Two dispatches.
  `REFERENCE_BUILD` reconstructs the mating object from `dimensions.md`; with no mating
  object it has nothing to build, and `REFERENCE_ACCEPTANCE` has nothing to overlay.
  `METROLOGY`'s own load-bearing check is reconciling disagreeing sources, and a stated
  dimension has one source. Write the sheet yourself from the user's numbers, and ask the
  disambiguating question (units, ID vs OD, radius vs diameter) at `INTAKE` where it is cheap.

  **The express variant, only if the user asks for it by name.** Both dispatches together are
  about fifteen minutes, and roughly four of those are the build. A user who wants the part
  faster can have `DIRECT_EXPRESS`: you run the verification steps yourself instead of
  dispatching a fresh verifier —

  ```bash
  V=<your-own-dir>
  python <skill>/scripts/dt.py integrity <candidate>.stl --out $V/integrity.json
  python <skill>/scripts/dt.py commission --stl <candidate>.stl         --plan print_plan_checks.json --out $V --job-id <job>         --updated-utc <iso8601> --no-receipts
  python -m team_tools.contracts validate <project-dir> --require all
  python -m team_tools.contracts status <project-dir>
  ```

  — then look at `$V/renders/`, zooming with `dt.py crop` where a view is too small to settle
  a question. That chain measures 4.4 seconds of computation, so what it costs is your own
  turns, not the tooling. You did not author the
  geometry, so this is not the designer marking its own work; but you *have* read the brief
  and the dispatch, so it is not fresh eyes either.

  What that costs is specific, not hypothetical. Fresh-context verification has caught two
  candidates that passed every deterministic check and were still wrong: one missing the
  countersink its own sheet required, one whose mounting flange had a slot cut clean through
  it. Both were found by a reader with no stake in the geometry looking at a render. Neither
  was a number, so running the same commands yourself would not have caught them.

  So never choose this silently. `job_state.md`'s `## Route` records `DIRECT_EXPRESS` and the
  sentence "no independent fresh-context verification was performed", and the delivered summary
  repeats it. An `R2`/`R3` job may never take it, and neither may a job whose part carries load,
  mates to anything, or would be expensive to reprint.
- **`FITTED`** — one real object is measured or photographed and the part must fit it.
  Single candidate.
  `INTAKE -> METROLOGY -> PRINT_PLAN -> CANDIDATE_BUILD -> INDEPENDENT_VERIFICATION ->
  DELIVERY`. Four dispatches. The blind rebuild still happens — the candidate designer builds
  the mating object from the sheet alone and exports it as a `mating_reference` manifest row —
  but the fresh verifier is who overlays it on the photos, so the round trip costs no dispatch
  of its own. The cost of folding it in is lateness, not blindness: a sheet defect now surfaces
  against a built candidate, so budget the rework as a candidate rebuild.
- **`FULL`** — multiple parts, moving or mating interfaces between printed parts, `R2`/`R3`,
  multi-colour alignment, or parallel candidates. Every phase, plus `FINAL_PREP_REVIEW` when
  required. Buy the time back with parallel candidate builds, not by skipping gates.

Classify toward the more complete profile when genuinely torn, and re-classify upward the
moment new evidence changes the answer. The consequence class is independent: an `R2` single
bracket with fully stated dimensions is still `DIRECT` in shape, but `R2` adds the named
reviewer and physical proof before any "ready for use" claim, and an `R3` job never reaches
`DELIVERY` at all.

Two rules survive every profile, because the benchmark runs show what happens without them.
**The print plan is never authored by whoever builds the geometry** — across four archived
runs with no plan bound, every designer set its own support ceiling *after* reading its own
measurement (2034 mm² observed, 2150 declared), which is a receipt, not a gate. A shipped
template is a legitimate plan precisely because it was written before any measurement existed.
**Verification is never folded into the build** — a designer self-waived one of the seven
checks as "n/a for this interface type", and only a fresh context catches that.

## Checklist

1. Run the Consequence and escalation gate above and record the resulting class, rationale,
   reviewer requirement, and prohibited claims in `job_state.md` before any routing decision.
2. Pick the profile with the Route profiles section above, record it and the deciding fact in
   `job_state.md`, then create the project folder and `job_state.md`; create/update any
   optional host print queue note when the host provides one.
3. Advance only through the phase sequence that profile names. A phase the profile omits is
   not skipped work you owe later — its input does not exist for this job.
4. `DIRECT` only: write `dimensions.md` yourself from the stated numbers, and generate the
   bound plan from the stated overall size (run from `skills/3d-modeling/scripts/`):

   ```bash
   python <skill>/scripts/dt.py plan template --bbox 40 22 14 --out <project-dir>/print_plan_checks.json
   ```

   It emits `threshold_source: builtin-default`, requires self-support, declares an identity
   model-to-printer transform, and invents no interface or edge band. Tell the designer the
   part must therefore be modelled **seated on the bed**, minimum Z at zero — a model centred
   on the origin has half of itself under the bed and reads as unsupported across its whole
   underside. A part that cannot clear a zero support ceiling by reorienting or
   chamfering is not a `DIRECT` part: re-route it to `FITTED`/`FULL` and dispatch a print
   engineer rather than relaxing the number. Ask every disambiguating question at `INTAKE`; a
   unit or radius-vs-diameter ambiguity resolved here costs one question, and resolved after
   the build costs a rebuild.

   Then run `dt.py templates` yourself and, if one covers the shape you are commissioning,
   name it in the dispatch. This is routing, not an answer: you are saying which starting
   point exists, never what the designer should conclude. It is also the single largest
   measured difference in cost — dispatches told which template fit finished a fitted phone
   case in 11.9 minutes and five beehive parts in 15.3, while one left to discover the
   catalogue on its own hand-wrote a part `c_clip` already covered and took twice as long for
   the same result.
5. `FITTED`/`FULL` only: dispatch the metrologist to create `dimensions.md`; gate on complete
   datum/provenance, confidence grades, resolved blockers, and one blind-build-completeness row
   for every visible feature. That table is what stops a sealed brick: a sheet declaring "all
   fit-critical dimensions resolved" while silently omitting every port produced exactly that
   in four archived runs.
6. `FULL` only: dispatch one designer with the **reference** commission, then dispatch the
   metrologist again to overlay-accept it. A failure returns to `METROLOGY`: fix the sheet,
   not the reference model. Under `FITTED` this loop still runs, but inside the candidate
   build and the verification — see the profile description.
7. `FITTED`/`FULL`: dispatch the print engineer for the pre-design `print_plan.md`; gate on
   orientation, material, nozzle-linked limits, support budget, chamfers, colour constraints, a
   complete per-interface fit-strategy declaration, and a frozen `required_now` /
   `deferred_owner` / `final_gate` scope for every geometry rule. Under `DIRECT` the shipped
   template stands in, and it is a real plan for the same reason: written before any
   measurement existed. Never let the designer supply its own.

   Whatever wrote it, gate the plan before dispatching anyone against it:

   ```bash
   python <skill>/scripts/dt.py plan check <project-dir>/print_plan_checks.json
   ```

   Require exit zero. It applies the conditions `validate-receipts` will apply to the finished
   candidate, none of which depend on geometry. One archived run spent 39 minutes building
   against a plan whose only support rule declared `SUPPORT_ALLOWED` with no
   `allowed_contact_class`, passed `commission`, and was rejected for the plan afterwards.
8. Dispatch candidate designer(s) against the sheet, accepted reference, and print plan.
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
9. Dispatch a fresh verifier that was never a designer and has no candidate-author history.
    Treat designer readiness as untrusted and require all seven checks. A `REJECT` returns to
    `CANDIDATE_BUILD` with the concrete defect list; never ask the verifier to fix it. For an
    `R2` job, a `PASS` is not itself the "ready for use" claim — that still needs the named
    reviewer's sign-off and physical proof. For an `R3` job, the verifier must never issue
    `PASS`/accepted at all.
10. `PRINT_PREP` is conditional, and `commission.json` decides it, not the profile: when the
    verified candidate needs support contacts, toolpaths, or another slicer-dependent visual
    predicate, dispatch the print engineer for coupon, slicing, print order, and field-test
    details in `final_print_prep.md`, require `READY_FOR_REVIEW`, and dispatch the verifier to
    write `final_prep_review.md` before delivery. A support-free candidate with no deferred
    visual predicate finishes on the plan's own final-prep placeholders -- do not spend a
    dispatch producing a native project for ceremony.
11. Enforce the plan-revision rule in
    [`references/team-contracts-v4.md`](references/team-contracts-v4.md#plan-revision-rule).
    Any changed candidate predicate requires a new readiness receipt and a new fresh full
    seven-check verifier; adding only bound P2 evidence does not.
12. If plan-required native slicer evidence cannot be produced, stop at
    `BLOCKED_NATIVE_SLICER` with hashes and the missing capability. Never label it Ready to
    Print. A non-native exception requires explicit user approval.
13. Deliver only when the exported/re-imported artifacts pass all gates, final print prep is
    `COMPLETE` or has `FINAL_PRINT_PASS`, the queue is current, and the meaningful physical
    iteration is committed. For `R2`, deliver only after the named reviewer's sign-off and
    physical proof are recorded. For `R3`, this pipeline never reaches `DELIVERY`.
14. Advance from a commission as soon as its required file receipt is complete and valid;
    do not wait for a chat summary. Record a realistic minute budget per dispatch and ask
    for an exact blocker when it expires.
15. Keep evidence differential. Never copy a canonical STL into a verifier folder. Preserve
    hashes, reports, metrics, and the decisive defect visual; do not fan out unchanged exports
    or full render sets per rejection.

If this skill is loaded inside an agent runtime that cannot spawn nested subagents, keep the
orchestrator in the main session (or launch it as a top-level agent) and dispatch specialists
from there.
