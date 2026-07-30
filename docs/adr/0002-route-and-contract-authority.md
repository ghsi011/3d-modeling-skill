# ADR 0002 — Route authority, acceptance-contract authority, and the CUSTOM rebuild

Status: accepted, 2026-07-30
Amends: [ADR 0001](0001-one-project-one-cli.md) §1 (routing) and §3 (one canonical
project). Supersedes Phases 2 and 3 of [the migration map](../migration-map.md).

## The sentence this whole design serves

> A receipt is worth exactly what the party who could not edit it knows. Route,
> acceptance criteria and expected values must each be owned by something other
> than the artifact being judged, and frozen before that artifact exists.

## What the architecture is in service of

The objective is one skill — reliable, fast, accurate and versatile — that covers
the whole of ordinary 3D work:

* from-scratch design where dimensions are stated or chosen;
* parts that mate with an existing real object;
* modification of a supplied STEP, STL or 3MF;
* combination of two or more existing CAD artifacts;
* multi-part and moving assemblies;
* ordinary FDM preparation for all of the above.

Trust architecture exists so those jobs can be *believed*. It is not an end in
itself, and it earns nothing on its own. A receipt that no one needed is cost; a
route that adds a review a job did not require is cost; a control that makes a
supported job unsupported is a regression, whatever it does for provability.

Read the rest of this document with that ordering in mind. Every decision below
is there because a job in the list above cannot currently be believed, and each
is bounded by the acceptance goals in the section of that name.

### One capability gap, recorded not solved

Combination of two or more existing CAD artifacts is in the objective and is not
representable in the current schema. `edit_scope` names a single `artifact_id`,
validated against one entry in the source-artifact manifest, so merging two
imported assemblies — two source artifacts, two preservation scopes, one
candidate — has nowhere to be declared.

This ADR does not solve it. It is recorded as owed work so that the repair stages
are not designed in a way that makes it harder to add: whatever replaces
`edit_scope` should not assume a single source.

## Context: two reviews, twenty-one defects, three that invalidate the receipts

Two independent code reviews of the Phase 0-3 consolidation found 21 defects.
Most are ordinary: wrong error codes, unbound evidence, missing checks. Three are
not defects in a check — they are defects in who owns the check, and they mean
the receipts the pipeline emits do not carry the meaning they claim.

### A — the declared route is not controlling execution

`runner.run` re-derives the route from `intent.select` on the certified lane
instead of consuming the route the project declared. A project routed `FITTED` or
`FULL` therefore executes as `DIRECT`: no spec call, no verification stage.
`project.json` says one thing and `final_status.json` says another, and nothing
reconciles them.

Today this is a permanent livelock — the job cannot finish, so nothing false
leaves the pipeline. That is luck, not a control. The moment the screening
calibration flag flips true, the same code path produces a completed job whose
verification was silently skipped.

### B — the candidate controls its own acceptance criteria

`EXPECTED`, `BBOX_MM`, `BODIES`, `VOLUME_MM3` and `PROFILE_MARKS` are re-read out
of the mutable `model.py` on every run, and the contract is overwritten with what
was found. The designer can read a failure, widen the expectation, re-run, and
receive a clean commission. Nothing records that the expectation moved.

Demonstrated, not hypothesised: a model declaring a 24x18 pad, building a 10x8
one, with a self-declared 500 mm2 tolerance, was commissioned `PASS` on a
352 mm2 miss.

The sharper edge is what those fields feed. `VOLUME_MM3` and `PROFILE_MARKS` are
the calibration inputs to the broad anomaly screen. On the certified lane they
come from a different party — `pipeline/templates.py`, which the designer does
not write. On `CUSTOM` they come from the file being screened. A screen
calibrated by its own subject is not a screen.

### C — the preservation gate is nondeterministic and misses real modifications

`pipeline/preservation.py` compares source against candidate with unseeded
area-weighted surface sampling. Measured:

* an undeclared 1.2 mm cube outside the edit region reported `PRESERVED` in 2 of
  20 audits;
* a 0.5 mm cube reported `PRESERVED` in 15 of 20;
* `max_deviation_mm` varied 1.13-2.00 mm across six runs of one unchanged pair.

The last of those also breaks byte-identical reruns for every `MODIFY` job, which
is the property Phase 0 exists to protect.

These three are not isolated bugs to be queued behind the other eighteen. They
are the reason the other eighteen cannot be judged: a fix that lands under them
is verified by receipts that do not mean what they say.

## Decision

**Do not patch in severity order.** Settle route authority and acceptance-contract
authority first, then rebuild the `CUSTOM` lane on top of them.

The branch is kept. The unified CLI, the canonical project representation, the
authored backend, the diagnosis tooling, the Phase 0 fixtures and the
preservation *concept* are all worth keeping and are not re-litigated here. What
changes is who owns the decisions those parts consume.

Until the repair lands, `CUSTOM` and `MODIFY` must not produce a successful final
status. Failing closed on a lane whose receipts are meaningless is the honest
state.

### 1. Route authority

`project.json` owns route intent. A single route compiler emits
`execution_plan.json`. The runner consumes that plan verbatim and never reroutes.
`intent.select` keeps template-domain matching and gains no authority back.

Template matching selects a *geometry provider*, not a route. The two axes are
recorded separately and named separately:

| axis | what it decides | values |
|---|---|---|
| route | the evidence required and the review obligations | `DIRECT`, `CUSTOM`, `FITTED`, `FULL` |
| builder | where the geometry comes from | certified template, authored model, imported geometry, reconstruction |

A certified template used inside a `FITTED` job stays `FITTED` — the template
makes the build cheap, not the evidence obligation smaller. `verification_requested`
adds the review stage regardless of route.

`final_status.json` records the plan's route and the plan hash, so a status can
be checked against the plan that produced it rather than against a route
re-derived at read time.

### 2. Acceptance-contract authority

The acceptance contract must be frozen **before the candidate is built**, not
derived and consumed within the same build. Two artifacts replace the current
structure:

* a **design proposal** — what the designer proposes to build, in the designer's
  own words and numbers;
* **`acceptance_contract.json`** — generated and frozen by the pipeline, before
  the builder executes.

The acceptance contract carries: the proposal hash; the user requirement hash;
source artifact hashes; system-owned tolerances; print-plan constraints; required
feature checks; route-specific gates; expected artifact identities; and its own
revision number and hash.

The candidate and every receipt bind that exact hash. Any change to the contract
creates a new revision, invalidates the candidate artifact, the commissioning and
the verification, and is visible in history. There is no silent overwrite.

One-agent `CUSTOM` stays possible, and the ordering is what makes it safe. A
single designer commission produces both the proposal and the model. The runner
then:

1. validates and freezes the proposal;
2. generates `acceptance_contract.json` from the frozen proposal and the
   system-owned inputs;
3. only then executes the model;
4. commissions the exported artifact against the frozen contract.

What is prohibited is narrow and precise: deriving acceptance criteria from the
built mesh, and re-reading acceptance criteria from a mutable model on every run.
The designer may still state every number. The designer may not restate them
after seeing the result.

### 3. No invented second-party expectations

There is no universal second-party source for `VOLUME_MM3` or `PROFILE_MARKS` in
novel `CUSTOM` work, and one must not be invented to make the certified lane's
screen appear to apply.

Expected volume is an acceptance input only when it is independently available:

* a certified template;
* an analytic formula generated from the frozen proposal;
* an immutable source artifact plus a bounded addition or removal;
* a previously approved revision;
* an independent verifier's predeclared bound.

Otherwise it is recorded as `NOT_INDEPENDENTLY_SPECIFIED`. The measured volume
may still appear in the receipt as a measurement — it simply cannot clear an
anomaly detector by comparing against itself.

Screening policy is therefore per lane:

| lane | what drives the screen | an uncalibrated volume/profile screen |
|---|---|---|
| `DIRECT` | certified expectations from `templates.py` | may drive the calibrated screen |
| `CUSTOM` | explicit frozen feature and dimensional checks | `WARNING` or `NOT_APPLICABLE` |
| `MODIFY` | immutable-source deltas and preservation checks | `WARNING` or `NOT_APPLICABLE` |
| `FITTED` / `FULL` | explicit checks plus independent verification | `WARNING` or `NOT_APPLICABLE` |

An uncalibrated screen never issues itself a `CLEAR`.

This is not weakening the gate. It is removing a gate that was never valid on
these lanes, and relying instead on evidence that is more direct: named features,
stated dimensions, source deltas, and — where the consequence warrants it — a
second party.

### 4. Execution state and invalidation authority

Status becomes a computation over current bindings rather than a file that is
displayed.

* Every run carries a run id, and status is binding-aware.
* A previous `final_status.json` is stale unless every binding still matches.
* A stale successful status is never displayed as current.
* `next_action.json` is superseded or removed when the action it names is done or
  no longer applies.
* An incomplete prior commission is explicitly resumed or explicitly invalidated;
  it is never inherited by silence.

`design-tool status` computes status from current bindings rather than displaying
the last status file it finds.

### 5. One gate matrix

Required checks are declared per lane, in one place, rather than per code path.
The present bypass exists because `CUSTOM` reaches the exported artifact through
a different function than `DIRECT` does, and that function simply does not call
some of the checks. Declaring the matrix once makes a missing check a data
difference that can be read, not a control-flow difference that has to be found.

### 6. Preservation

Asserted exactness is removed. `exact=True` must be an *output* of a specific
comparison method, never an input assertion that grants acceptance.

Sampling becomes deterministic: seeded from the source and candidate hashes, with
density derived from a declared minimum detectable defect size rather than a
fixed sample count. The verdict is named for what it establishes —
`PRESERVED_WITHIN_SAMPLED_TOLERANCE`, not "exactly".

If exact STEP preservation requires the `cascadio` dependency, then either
package and test that dependency, or declare exact STEP preservation unsupported
and fail closed. The one behaviour that is not allowed is the present one:
falling back from exact comparison to mesh sampling while retaining the exact
claim.

## The staged sequence

| stage | what lands | what it unblocks |
|---|---|---|
| 1 — route authority | route compiler, `execution_plan.json`, runner consumes verbatim, route/builder split recorded | every later stage, because until now no receipt names the lane it actually ran |
| 2 — acceptance contract | proposal freeze, `acceptance_contract.json`, revisioned invalidation, builder executed after the freeze | the `CUSTOM` lane can mean something |
| 3 — state lifecycle | run ids, binding-aware status, staleness, resume-or-invalidate | reruns and resumption stop inheriting stale success |
| 4 — gate consolidation | one declared per-lane gate matrix | `CUSTOM` stops bypassing checks other lanes perform |
| 5 — preservation | seeded sampling, defect-size-derived density, honest verdict name, STEP decided | `MODIFY` reruns become byte-identical again |

The gating rule: no stage after 2 begins, and no `CUSTOM` or `MODIFY` job reaches
a successful final status, until finding B is **structurally impossible** rather
than merely caught by a validator. A validator that rejects a moved expectation
is a check that can be removed, mis-ordered or skipped on one code path — which
is exactly how the current defect exists. The test for stage 2 is not "does a
check fire", it is "is there any ordering of operations in which the built
artifact can influence its own acceptance criteria".

## Acceptance goals for the repair

These are constraints on the repair, not aspirations for it. Each is testable,
and a stage that meets its own gate while breaking one of these has not landed.

**`DIRECT` does not become slower or more expensive.** Zero design-agent calls,
and no regression against the per-route timings in [`docs/baseline.md`](../baseline.md)
— 0.20 s for a trimesh certified template, 3.90 s for the build123d one, of which
3.69 s is a cold import. Route authority is a plan the runner reads; reading a
plan is cheaper than re-deriving a route.

**`CUSTOM` stays one designer commission.** Freeze-proposal-then-build is a
deterministic pipeline step, not a second dispatch. If the repair ends up asking
the designer to come back and confirm the contract it generated from their own
proposal, the repair is wrong.

**No route gains an agent round trip as a side effect.** The `llm calls` column
of the baseline table is a fixture, not a report. `DIRECT` 0, `FITTED` 2,
`FULL` 2, `CUSTOM` 1.

**The deterministic lanes keep running while `CUSTOM`/`MODIFY` are barred from
claiming success.** Barred from *claiming*, not barred from *executing*: the
build, the export, the commissioning measurements, the preservation audit and the
witnesses all still run and still write receipts. A designer must be able to
iterate against real measurements throughout the repair. What they cannot get is
a final status that says the result was accepted.

**Versatility is not traded for provability.** Where a control cannot be met for
a use case, the honest answer is a named limitation recorded in the receipt — not
the removal of the use case. `NOT_INDEPENDENTLY_SPECIFIED` in §3 and
`PRESERVED_WITHIN_SAMPLED_TOLERANCE` in §6 are both instances of this rule, and
it is the rule that governs when the two conflict.

## Consequences

* Phases 2 and 3 are substantially reworked, not extended. The migration map's
  "done" markers on those phases are withdrawn.
* The Phase 3 headline result — 27,000 samples moving 0.00 mm — was a true
  measurement of a test that could not reliably fail. It is not evidence of
  preservation and is not carried forward as such.
* `CUSTOM` and `MODIFY` fail closed until stage 2 lands, so work that "ran" on
  this branch stops running. That is the cost of having shipped a lane whose
  receipts were self-issued.
* Two artifacts appear where designers previously wrote one file, and a designer
  can no longer adjust an expectation after seeing a result. This is the point,
  and it will be felt as friction on exactly the jobs where it matters.
* `DIRECT` is untouched again. The Phase 0 fixtures remain the definition of
  unchanged, and every stage above is gated on them.
* Route and builder become separately reportable, which makes "a certified
  template was used" stop implying "the cheap route was taken".

## Rejected alternatives

**Patching the 21 findings in severity order.** The severity ranking assumes the
findings are independent. They are not: fixes to the other eighteen would be
verified by commissioning receipts that finding B makes meaningless and by
preservation audits that finding C makes nondeterministic. Ordering by severity
would produce a branch that is green and untrustworthy — the state it is in now,
with more code in it.

**Reverting the branch to `f7082e5`.** The defects are in authority, not in the
consolidation. Reverting would discard a working unified CLI, the canonical
project representation, the authored backend, the diagnosis tooling and the Phase
0 fixtures in order to re-derive them, and the same authority questions would
have to be answered on the second attempt anyway.

**Inventing a second-party expectation source for `CUSTOM`.** Having a second
agent estimate the expected volume, or deriving it from a heuristic over the
proposal text, would restore the shape of the certified lane's screen without
restoring its substance. A guess that the designer's own numbers informed is not
an independent expectation; it is finding B with an extra hop. Recording
`NOT_INDEPENDENTLY_SPECIFIED` is worse-looking and more honest.

**Keeping `exact=True` as an input assertion with a louder warning.** An
assertion that grants acceptance is a control transferred to whoever writes the
assertion. The caller who sets `exact=True` is the caller who wants the pass.
