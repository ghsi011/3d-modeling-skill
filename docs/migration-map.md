# Migration map

The phase-by-phase plan behind [ADR 0001](adr/0001-one-project-one-cli.md). Each
phase continues to the next while its gates are green. Nothing here deletes or
migrates a user's project data; nothing here adds a dependency beyond the four
the skill already declares.

Legend: **new** = file created, **ext** = existing file extended, **doc** = agent-facing
text changed, **ret** = leaves agent instructions but stays importable.

## Status

| phase | state |
|---|---|
| 0 — freeze behavior | **done** (`bea8d66`) |
| 1 — route and CLI unification | **done** (`43ccd0d`) |
| 2 — custom from-scratch lane | **superseded** — see [Repair stages](#repair-stages-adr-0002) below |
| 3 — modification lane | **superseded** — see [Repair stages](#repair-stages-adr-0002) below |
| 4 — fitted / photo workflow | not started |
| 5 — motion and assemblies | not started; the declaration and its routing consequences exist, the sweep engine does not |
| 6 — packaging and hardening | not started |

Until Phase 5 lands, a job that declares motion routes `FULL` and its
`motion_path` modifier is reported `DEFERRED` by `status.manufacturing` — the
sweep is named as unmeasured rather than implied complete. Until Phase 6 lands,
there is no resource governor and no versioned Bambu adapter; `make_3mf.py` and
`make_bambu_3mf.py` are unchanged from before this work.

## Repair stages (ADR 0002)

Two independent reviews of the Phase 0-3 consolidation found 21 defects, three of
which mean the `CUSTOM` and `MODIFY` receipts do not carry the meaning they
claim: the declared route does not control execution, the candidate re-derives
its own acceptance criteria on every run, and the preservation audit sampled
unseeded, so no two runs of one `MODIFY` job produced the same evidence.

[ADR 0002](adr/0002-route-and-contract-authority.md) records the decision: settle
route authority and acceptance-contract authority first, then rebuild the
`CUSTOM` lane on top of them. Phases 2 and 3 below are therefore **superseded** —
their tables record what was attempted, not what stands. Until the repair lands,
`CUSTOM` and `MODIFY` fail closed rather than reaching a successful final status.

The repair runs in five stages: route authority -> acceptance contract -> state
lifecycle -> gate consolidation -> preservation. No stage after 2 begins until a
built artifact is structurally unable to influence its own acceptance criteria.

One half-stage sits out of that order. Stage 5's determinism was pulled forward
as **1.6** because it is not a preservation improvement so much as a precondition
for measuring anything on the `MODIFY` lane: while the audit sampled unseeded,
every later stage would have been verified against receipts that no rerun could
reproduce. It takes the determinism and nothing else — the sensitivity work stays
in stage 5, and the lane cap stays on.

| stage | state |
|---|---|
| 1 — route authority | **done**: `pipeline/execution.py` compiles `execution_plan.json`; the runner consumes it and no longer selects a route; `final_status.json` carries the plan's route, the plan hash and the lane status. An independent review of the first landing found four defects in it, all repaired: the modification cap keyed on the source mode rather than on the declared edit scope, a matched certified template silently outranking a declared authored model, `verification_dispatch: OPTIONAL` naming a look `design-tool run` could not take, and `route._legacy` dropping `verification_requested` |
| 1.6 — deterministic evidence | **done**: the preservation sample plan is derived from the source and candidate hashes over meshes whose vertex and face order is canonicalised first, floats are serialised through `schemas.canonical_number`, and the plan's digest and the audit's own digest are bound into the review envelope (`review` protocol 2). Identical inputs now produce byte-identical evidence, which is what makes a `MODIFY` review round trip possible: before it, the rerun that read a reviewer's answer had already measured the part differently, the envelope mismatched, and the job could not be resumed. Taken out of stage 5 and landed early because every stage after it that touches a `MODIFY` job is verified by receipts this defect made unreproducible |
| 2 — acceptance contract | **done**: the designer commission returns `design_proposal.json` and `model.py` together; `pipeline/acceptance.py` generates `acceptance_contract.json` from the frozen proposal and the system-owned inputs and writes it before the builder is imported. `AuthoredModel` no longer has an `expectations`, a `bbox` or a `bodies`, so the object the builder came out of cannot reach the function that writes the contract; acceptance bands are computed by the pipeline from each row's own magnitude and are not proposable. A changed proposal or requirement cuts a revision, invalidates the receipts issued against the old one and records both in `acceptance_history.json`. The `CUSTOM` cap is lifted with the reason it named; `MODIFY`'s is not, because what it owes is stage 5's sample density |
| 3 — state lifecycle | not started |
| 4 — gate consolidation | not started |
| 5 — preservation | not started. Stage 1.6 took the determinism only; sensitivity is untouched and still owed here — density derived from a declared minimum detectable defect size, real B-rep comparison, the `PRESERVED_WITHIN_SAMPLED_TOLERANCE` naming, and the STEP decision. A plan that misses a 0.5 mm undeclared cube still misses it, now identically on every run |

Stage 1 marked `CUSTOM` and `MODIFY` `EXPERIMENTAL_UNAVAILABLE`: they build,
screen, gate and write every receipt, and a passing run reports the cap rather
than `COMMISSIONED` or `VERIFIED`. A real `FAILED` or `NEEDS_MORE_EVIDENCE` is
still reported as itself -- withholding a claim must not bury a finding. Stage 2
lifts `CUSTOM`'s, because the reason it named is gone. `MODIFY` stays capped on
what stage 5 owes.

A third lane status arrives with stage 2 and is not a cap at all in the same
sense. `UNSUPPORTED` is a combination this build cannot execute -- a `FITTED` or
`FULL` job on authored geometry owes a bounded recovery that is defined only
against a certified template's bounds -- and no stage on this map lifts it. It
used to be spelled `EXPERIMENTAL_UNAVAILABLE` too, so every reader of such a
receipt was told to wait for something that was never coming.

Phase 2 rows that were planned and never built are unchanged by this and still
owed: `pipeline/commissions.py`, a `design-tool commission` verb, and a
`certified` flag on the starting templates. `dt.py commission` therefore does NOT
leave agent instructions yet.

## Phase 0 — freeze behavior

Establish what "unchanged" means before anything moves.

| what | where |
|---|---|
| **new** golden route decisions for every certified template, in and out of domain | `pipeline/test_frozen.py` |
| **new** golden artifact set + final status for `DIRECT`, `FITTED`, `FULL` | `pipeline/test_frozen.py` |
| **new** `design-tool selftest` — a smoke set that ships inside the bundle | `pipeline/selftest.py` |
| **new** baseline timings, agent-call counts and artifact inventory | `docs/baseline.md` |

Gate: the full suite green, and the frozen fixtures reproduce byte-identical
receipts on a rerun with the same `updated_utc`.

## Phase 1 — route and CLI unification

| what | where |
|---|---|
| **new** canonical project schema, validation, `job.json` adapter | `pipeline/project.py` |
| **new** route authority: `DIRECT`/`CUSTOM`/`FITTED`/`FULL` over a project | `pipeline/route.py` |
| **new** resumable stop signal | written as `next_action.json` by `pipeline/cli.py` |
| **ext** `design-tool` gains `init`, `route`, `run`, `status`; `run-job` becomes a deprecated alias | `pipeline/cli.py` |
| **ext** `intent.select` keeps template-domain matching, loses route authority | `pipeline/intent.py` |
| **doc** `SKILL.md` route table and command surface | `skills/3d-modeling/SKILL.md` |

Gate: Phase 0 fixtures unchanged; `run-job` byte-identical on the frozen jobs.

## Phase 2 — custom from-scratch lane

| what | where |
|---|---|
| **new** one designer commission generated from project state | `pipeline/commissions.py` |
| **ext** pre-build print/fit plan required before candidate measurement | `designer_toolkit/plan.py` |
| **ext** `design-tool commission` drives the authored-geometry gate from the project | `pipeline/cli.py` -> `designer_toolkit/commission.py` |
| **ext** route-specific independent verification triggers | `pipeline/route.py` |
| **ext** starting templates flagged separately from certified ones | `designer_toolkit/templates.py` |

Gate: two unrelated custom parts commissioned end to end.

## Phase 3 — modification lane

| what | where |
|---|---|
| **new** imported-artifact diagnosis and classification | `pipeline/diagnose.py` |
| **new** preservation audit (B-rep, mesh, 3MF scene) | `pipeline/preservation.py` |
| **ext** edit scope and source-artifact manifest in the project | `pipeline/project.py` |
| **ext** exact-vs-mesh fallback recorded as a fidelity change | `pipeline/project.py`, artifact manifest |

Gate: a STEP modification preserving most geometry; a damaged/complex STL
modification; a multi-component 3MF inspection.

## Phase 4 — fitted / photo workflow

| what | where |
|---|---|
| **ext** metrology reads and writes canonical project state | `pipeline/fitted.py`, `pipeline/project.py` |
| **new** conditional early blind-reference acceptance loop | `pipeline/route.py`, `pipeline/commissions.py` |
| **ext** fresh independent visual verification preserved | `verify_visual.py`, `overlay_photo.py` |

Gate: two structurally different external-object fits.

## Phase 5 — motion and assemblies

| what | where |
|---|---|
| **new** declared motion schema and adaptive sweep | `pipeline/motion.py` |
| **new** intended-contact semantics and worst-pose evidence | `pipeline/motion.py` |
| **ext** multi-component manifests | `pipeline/project.py` |

Gate: free linear slide; rotary hinge; intended snap/detent; a narrow jam
between coarse stations.

## Phase 6 — packaging and hardening

| what | where |
|---|---|
| **new** resource governor (child process, wall/memory/output limits) | `pipeline/governor.py` |
| **ext** fail-closed generic 3MF | `make_3mf.py` |
| **ext** versioned Bambu adapter, native-slicer evidence boundary | `make_bambu_3mf.py` |
| **ext** package self-tests | `pipeline/selftest.py` |
| **doc** slim role files; narratives move to ADRs and test names | `skills/3d-modeling/roles/*` |

Gate: the benchmark matrix in `docs/benchmark.md` runs clean.

## What leaves agent instructions, and when

| surface | leaves when | still importable |
|---|---|---|
| `dt.py plan check` | Phase 2 (`design-tool run` gates the plan) | yes |
| `dt.py commission` | Phase 2 (`design-tool commission`) | yes |
| `dt.py intake` / `build` | Phase 2 (`design-tool init` + designer commission) | yes |
| `dt.py screen` / `audit` / `probe` | Phase 3 (`design-tool audit`) | yes |
| `python -m team_tools.contracts` | Phase 4 (`design-tool status`) | yes |
| `team_preflight.py` | Phase 5 (`design-tool motion`) | yes |
