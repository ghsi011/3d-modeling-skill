# Release 4 — scope

> **Status: judged and acted on, 2026-08-03. Superseded in three places — read
> this header before the argument below.**
>
> This document was written by one agent in one pass and was never reviewed. Its
> citations have since been checked one by one. Most held. What did not:
>
> * ~~**§4(C)'s material-use table is unsourced.**~~ **Withdrawn 2026-08-04, and
>   the table was right.** The finding was correct when written: `_observe_dir`
>   recorded the volume detector's *result* and discarded its `measured_mm3`, so
>   nothing committed could reproduce 47,526.263 mm³ against 49,792.874 mm³. It
>   said they should be treated as unverified "until a recording freezes the
>   number". Release 4 slice 2 freezes it, and a replay of
>   `branch-knob-seat-fallback` produces both figures to the digit, along with
>   the 38×38×50 and 38×38×52 envelopes. The document was accurate and the
>   repository was not; §5's second argument stands. The two findings below are
>   unaffected.
> * **§1's "`cli.py:1754` builds a table over *every* formulation" is false.**
>   The loop is over `project.alternatives`, and `branch` writes no row for the
>   shared root — so `status` reports two formulations where `cost.compare` in
>   the same report reports three. That is now `docs/defects.md` D26, and it
>   means §1's argument that a comparison is already reachable from
>   `design-tool status --json` is weaker than it reads.
> * **§6's "`docs/adr/0001` lists the unbuilt verbs … and does not name
>   `compare`" understates it.** That list is a code block rather than a table,
>   and it had already drifted: `branch` and `selftest` shipped in Release 3
>   without reaching it. Fixed, with a test that refuses the drift in future.
>
> And two of its judgements were **overruled** on evidence, in
> [ADR 0005](adr/0005-a-comparison-refuses-rather-than-scores.md):
>
> * **§4(F) proposed deferring `MODIFY` pairs.** They are in. Settling nothing
>   is the correct output when the deciding axis cannot be measured, provided
>   the comparison names that axis and refuses preference on those grounds.
>   Deferring the case that is hard to answer is what "Release 4 waiting on
>   Release 6 in disguise" would actually look like.
> * **§1 and §6 make `INCOMPARABLE_CHECK_SETS` the whole of the structural
>   answer.** It is one of three faces. The check *set* is one way a formulation
>   grades itself; the frozen *expectation* and the *band* are the other two,
>   and the expectation face is live on the recorded knob with nothing
>   constructed — the root declares `bbox_mm.z = 50.0`, `plate-seated` declares
>   `52.0`, and both are recorded `PASS` on `envelope`. See `docs/defects.md`
>   D25.
>
> Its four re-scoping recommendations in §6 were **accepted**, three as written
> and one enlarged, and are recorded at the bullets they change in
> `ROADMAP.md`. What shipped is in `ROADMAP.md` Release 4, slice 1.

What Release 4 should build first, what it should not build at all, and what it
may honestly compare with the instruments that exist.

Written at `08cdc4a`, tree clean. Every claim below about existing behaviour
cites a file and a line, or a number measured by replaying
`branch-knob-seat-fallback` through `tools/replay.py` at that commit.

`ROADMAP.md` owns sequencing. This document is an argument for what the next
slice should be; nothing here is a roadmap change until `ROADMAP.md` says so.
Section 6 lists what it recommends changing there and in `docs/adr/0001`.

---

## 1. What already exists that Release 4 would otherwise rebuild

This project has twice found a release item already built under another name.
Release 4's declared scope contains four more.

**The alternative record is complete.** `pipeline/project.py:515` `Alternative`
carries id, a **list** of parents, a required `reason`, a disposition, a `basis`
from a closed vocabulary and a `superseded_by`. All seven dispositions
(`project.py:62`) are honoured and each changes behaviour rather than labelling:
one `PREFERRED` per project and switching demotes the previous holder
(`project.py:1099`, `cli.py:2085`), `FALLBACK` is runnable
(`project.py:76`), `MERGED` is refused unless the named successor's `parents`
actually record the merge (`project.py:97`). Release 4's *Alternative
disposition* section — "support explicit reasons for preferred, paused,
rejected, superseded, retained as fallback" — is **shipped**. Nothing is owed
there.

**Branching already shares intent and duplicates nothing.** `cli.py:1930`
appends one row and creates one directory; the brief, requirements, source
artifacts, envelope and printer are read from the one `project.json`. Release
4's "which intent remains shared" is a property of the file layout, not a field
to add.

**A mandatory requirement already cannot be loosened by a formulation.** Two
independent mechanisms, and both are stronger than the check Release 4's proof
list asks for:

* a proposal **may not declare a tolerance at all** (`acceptance.py:246`).
  Bands are computed by the pipeline from each row's own magnitude and every
  frozen contract records `tolerance_owner: "pipeline"` (`acceptance.py:364`).
  Measured: both knob formulations carry `feature-bore-wall-section` tolerance
  `4.406638999978519`, byte-identical, from two separately authored proposals;
* `_requirement_hash` (`cli.py:1159`) is taken over the **shared**
  `project.json` — brief, `STATED`/`INHERITED`/`MEASURED` requirements,
  envelope, interfaces, components, modifiers — so every formulation's frozen
  contract binds the identical requirement digest. A formulation cannot weaken a
  shared requirement without editing the file all its siblings read, which
  invalidates all of them.

**Per-formulation status, evidence staleness and cost are already derived and
already reported side by side.** `cli.py:1754` builds a table over *every*
formulation, not only the active one: disposition, basis, successor, derived
status and stored status, via `status.derive` (`status.py:74`) over
`bindings.broken` (`bindings.py:347`). `cli.py:1774` adds `cost.compare`
(`cost.py:504`) — per-formulation dispatches, context bytes, deterministic
seconds, builds, repeated builds, restarts, and a `shared` block. Release 4's
"comparison reports unequal evidence" and "paused alternative incurs no ongoing
execution cost" are answerable from `design-tool status --json` today.

**A three-formulation job is recorded and replayed.**
`benchmarks/replays/branch-knob-seat-fallback/` drives the real `berlingo-knob`
request through `branch`, `route`, `run` and `status` with no live call, and
`tools/replay.py:1074` already writes a per-formulation block holding checks,
measured values, tolerances, coverage, screening detail, derived status and
receipts. That block **is** a comparison table; nothing reads it as one.

**What is genuinely absent.** No module compares formulations. `cost.compare` is
the only `compare` in the pipeline, and it compares spend, not designs. There is
no `comparison.json`, no verb, no output. And there is no link from a project
requirement to the contract row that measures it: the contract's features are
geometric proxies a designer chose, and coverage is computed against *that
formulation's own* declared features (`commission.py:436`), so a sibling
declaring three rows instead of four scores coverage 1.0 against its own
smaller contract. **That gap, not the alternative model, is what Release 4 has
to close.**

---

## 2. The first vertical slice

**Compare the formulations that exist, on the evidence already on disk.**
One new verb, `design-tool compare <project>`, that dispatches nothing, builds
nothing, and asserts nothing about geometry that a receipt does not already
carry.

Against rule 3.1's eight parts:

* **Input representation** — none new. Inputs are `project.json`'s alternative
  rows plus each formulation's own `acceptance_contract.json`,
  `commission_report.json`, `artifact_manifest.json`, `final_status.json` and
  `cost.json`. (D36 later renamed the pipeline's receipt to
  `pipeline_artifact_receipt.json`; this scope note is left as it was written,
  and the file it names here is that one, not the team contract of the same
  former name.) Optional `--against` selects formulations; the default is every
  runnable one. No new project field, no new schema. Rule 3.1 forbids an
  abstraction one fixture justifies, and this fixture justifies none.
* **Execution** — deterministic, zero dispatch, zero build, one pass over
  receipts. `cost.budget` is untouched, so 3.4's "no release may add an AI round
  trip to an existing path" holds by construction and is provable against the
  frozen table at `cost.py:114`.
* **Output** — `comparison.json` at the project root (it is about several
  formulations, so it belongs to none of their directories), plus a table on
  stderr. Four blocks per formulation — `mandatory`, `claim`, `evidence`,
  `measured` — and one project-level `not_compared` block, §4. No total, no
  weight vector, no ordering.
* **State and resumption** — nothing to resume: the comparison is recomputable
  from disk at any moment. It records each formulation's `bindings.identity`
  (`bindings.py:152`) and the digest of each receipt it read, so a comparison
  issued against evidence that has since moved is detectable by the mechanism
  already shipped rather than by a new one.
* **Relevant assessment** — the comparison *is* the assessment, and it
  re-adjudicates nothing, the same rule `status.derive` follows. Its one
  structural verdict is `INCOMPARABLE_CHECK_SETS`: two formulations measured
  against different declared feature sets are reported as incomparable on those
  checks rather than as equal. That is the gap §1 names.
* **Regression fixtures** — L0: (a) different feature sets report incomparable,
  not a winner; (b) a formulation whose commissioning FAILED can never be
  reported preferable to one that passed, whatever its material or cost numbers
  say; (c) a single-material one-piece pair emits **no** material-count,
  sequence, assembly or tooling rows at all — absent, not zero (6.14, 8.5); (d)
  a stale formulation is reported stale rather than by its stored verdict.
  Mutation: flip one formulation's commission verdict in the fixture and assert
  the `mandatory` row moves. L1: one `compare` step appended to
  `branch-knob-seat-fallback`, its output frozen in `expected.json`. It costs
  approximately nothing — the case is already 31 s of the 62 s suite and the new
  command builds nothing.
* **One authentic use case** — `branch-knob-seat-fallback`, argued in §5, plus
  recording one real disposition decision on it.
* **Documentation** — one section in `docs/tooling.md`, whose more important
  half is the list of dimensions the comparison does not measure and why.

---

## 3. What is deliberately out of the first slice

**Forbidden by Release 4's own text, and excluded on those grounds.**

* *Generating alternatives for every job.* Nothing in this build generates one.
  `design-tool branch` requires `--from`, `--id` and `--reason` and is refused
  without them (`cli.py:2015`). Slice 1 adds no generator, so the common case is
  preserved by construction.
* *Treating cosmetic variants as concepts.* Excluded, and note **why**: with no
  generator there is nothing to stop. A cosmetic-variant classifier would be a
  guard on a mechanism that does not exist, judging a decision a person makes by
  typing `--reason`. 3.1 forbids the abstraction. See finding 4.
* *One opaque score.* Excluded permanently, not merely from slice 1. The output
  has no total and no ordering. 8.5's "no weighted score may hide a mandatory
  failure" is enforced by there being no weighted score.
* *Claiming merged features work without reassessment.* Excluded because merge
  itself is out, below.
* *Unlimited active alternatives.* Not capped, and see finding 3: a numeric cap
  over a build where nothing generates branches limits a person's typing.

**Excluded merely for size, and still Release 4's.**

* *Reuse and merge planning.* The `MERGED` disposition and the multi-parent
  `parents` list exist and are validated, and nothing in this build ever *writes*
  a two-parent row (`ROADMAP.md:125`). Merge needs a proposal that declares
  provenance per element and a rule for which assessments survive. Its own
  slice, after comparison, because a merge you cannot compare against its
  sources is a merge nobody can accept.
* *Alternative-specific requirement scoping* below job-versus-alternative
  (component, interface, manufacturing configuration). Scoped by Release 3, not
  built, and nothing in slice 1 needs it.
* *A ceiling on exploration cost.* Measurement exists (`cost.compare`); a
  per-project exploration budget does not. Not needed to compare.
* *Context packages.* Decided out.

---

## 4. The hard question: what can be compared today

Comparison needs measured values from two formulations. Here is my judgement on
which of Release 4's thirteen dimensions have an instrument in this build.

### Available now, measured

**(A) Mandatory-requirement status.** `commission_report.verdict`, each check's
`ran` / `result` / `status` / `measured` / `tolerance`, and
`coverage.fraction` against `coverage.minimum` (`commission.py:436`). On the
knob: 4 of 4 declared features covered, every check PASS, both formulations.

One caveat that must be **printed rather than omitted**: the shared requirements
(`engagement_length_mm = 36.0`) are bound as a *digest* and are not individually
checked. The contract's rows are geometric proxies a designer chose. So the
honest sentence is "each formulation met the contract it froze, and both
contracts bind the same requirement digest" — not "both formulations meet the
requirement". A comparison that blurs those two is a false comparison, and the
distinction costs one line of output.

**(B) Evidence completeness and inequality.** Derived status per formulation,
the stale receipt set, `screening_calibrated`, `witnesses_rendered`, the
verification decision, `lane_status`, `unavailable_checks`. The recorded case
produces two VERIFIED and one STALE without anyone constructing it. This is
14.7's third bullet, it is the single most valuable thing available today, and
it is the one thing a person cannot see by looking at the parts.

**(C) Four manufacturing facts, measured.**

| dimension | instrument | knob, root / `as-drawn` | knob, `plate-seated` |
|---|---|---|---|
| material use | solid volume, on the receipt even where the detector is `NOT_APPLICABLE` (`screening.py:189`) | 47,526.263 mm³ | 49,792.874 mm³ (+2,266.611, +4.77%) |
| support burden | downward-facing area against a printer-derived ceiling (`cli.py:1034`, `metrics.py:164`) | 0.0 mm² of 0.0 | 0.0 mm² of 0.0 |
| component count | `bodies` check + the components screen | 1 | 1 |
| envelope | `bbox_mm` (`runner.py:521`) | 38 × 38 × 50 | 38 × 38 × 52, against a 40 × 40 × 52 declared envelope |

6.14's rule is that criteria a job does not exercise are **absent** from its
comparison rather than scored zero, so a single-material one-piece pair
legitimately reports these four rows and no others.

**(D) Exploration cost**, per formulation (`cost.compare`). Each knob sibling: 1
dispatch, 23.8 kB of context, ~3.44 s, 2 builds of which 1 repeated, 1 stored
answer reused, 0 builds shared. It is a fact about the process, not about the
part, and must be labelled that way or it becomes a tie-breaker for the wrong
reason.

### Must wait for Release 6

**(E) Anything measuring one formulation against another** — surface distance,
interference, region correspondence. Release 6 owns the comparison core.

**(F) Preservation, and this is the vent-ball answer.** It fails twice, for two
different reasons, and both are decisive:

* on the only `PHYSICALLY_PROVEN` source it cannot run at all. D22: five cone
  faces of `vent_mount.step` do not tessellate, the row reports `UNAVAILABLE` /
  `PRESERVATION_UNMEASURABLE`, and the fix is Release 6's *bounded repair* slice;
* on the source it *can* read, `ball_male_17mm.stl`, it runs and reports
  `PRESERVED_WITHIN_TOLERANCE`, `max_deviation_mm 0.0`, 38,014 samples outside
  the region — **and the lane still refuses a success claim**, in its own
  recorded words: sample density is a fixed count rather than one derived from a
  declared minimum detectable defect size, "so a small undeclared addition
  outside the edit region can still be missed, and is now missed identically on
  every run. Until that density is derived, this lane may not report a part
  COMMISSIONED or VERIFIED."

So two `MODIFY` formulations compared today both report
`EXPERIMENTAL_UNAVAILABLE` and neither may claim anything. The comparison would
be correct and would discriminate nothing on the axis that matters. **That is
the argument for slice 1 comparing from-scratch formulations and reporting a
`MODIFY` pair as un-rankable rather than ranking it.**

**(G) Print time, support toolpaths, multi-material and colour boundaries.**
`status.py:47` — no slicer adapter, and this stack has none by design. These are
permanently absent, not pending. An estimate here would be fabricated.

**(H) Strength, assembly effort, adjustability, serviceability, hardware count,
irreversibility.** No instrument anywhere in this build. They may appear only as
a **stated** row attributed to whoever stated it, never as a measurement and
never with a number this pipeline invented. Release 4's own scope already
requires comparison to distinguish objective measurements from policy-derived
estimates from engineering judgment; this is where that rule earns its keep.

### The rule that makes the difference

A comparison that silently omits the dimension nobody can measure is worse than
none. So the output carries an explicit `not_compared` block: one row per
dimension the job would exercise and this build cannot measure, each naming the
reason and the release that owns it. On the knob that block is short. On a
`MODIFY` pair it is the entire finding, and it is what stops a reader concluding
that two `EXPERIMENTAL_UNAVAILABLE` formulations are equivalent.

---

## 5. The authentic job

**`branch-knob-seat-fallback` is the right driver.** The argument is not that it
exists.

1. **The fork is the request's own recorded uncertainty.** The base-plate height
   is a photo estimate the source notes give as ±2 mm; the project records it as
   a non-blocking open question and models both answers rather than guessing.
   That is 3.5's "uncertainty makes early commitment expensive" met by evidence
   rather than by a designer's taste for options — the harder and more honest
   trigger than a snap-fit-versus-screws preference.
2. **Its comparison has a non-obvious answer.** Both formulations pass every
   mandatory check and both derive VERIFIED. They differ in one dimension that
   is measured — 2,266.611 mm³ of material, and an envelope that goes from 50 mm
   to exactly the declared 52 mm ceiling — and one that is not: whether the
   mouth actually seats, which needs a measurement nobody has taken. "Equal on
   everything I can measure, 4.77% apart in material, and the thing that decides
   between them is unmeasured" is precisely the output Release 4 should produce
   and precisely what a score would destroy.
3. **It is one command away from Release 4's declared exercise.** `as-drawn`'s
   recorded reason is that it is retained unchanged as the fallback if the
   estimate is wrong, and it is recorded `ACTIVE` because the recording predates
   `FALLBACK` being runnable. Release 4's exercise ends "select one as preferred
   while retaining the other as fallback" — two `design-tool branch
   --disposition` calls. That closes the gap `ROADMAP.md:122` states in its own
   words: nobody has used derived status to decide about a real part, and no
   alternative has been preferred or rejected on evidence.
4. **It costs nothing.** Already frozen, already three formulations, already
   through the real command surface with no live call.

**What it is not**, and must be said on the receipt: it is
`AUTHORED_AGAINST_A_RECORDED_REQUEST` — the request is real and vendored, the
proposals and models were authored for the replay. It ran `--no-render`, so no
witness image exists and nobody has looked at either part. It proves the
mechanism on real intent; it is not physical evidence.

**Why not the alternatives.** The *bracket* the roadmap names does not exist —
finding 1. `vent-ball-combine` is the other real branched job and is the wrong
driver for slice 1 for §4(F)'s reason: it is a `MODIFY` pair, so the comparison
discriminates nothing; it is the right driver for the *second* exercise, and the
roadmap already places it in Release 6. A new live commission is what 4.5
ultimately wants and should follow rather than gate — the mechanism has to exist
before a live job can exercise it.

---

## 6. Recommended re-scoping

**Finding 1 — strike the bracket.** `ROADMAP.md:1068` says "use the bracket
alternatives from Release 3". No bracket project exists: `benchmarks/fixtures/`
holds `berlingo-knob`, `component-cycle`, `oneplus-case-x2d-asa`,
`oneplus-drawer-dropin`, `pixel9-card-case`, `vent-ball-combine`. The bracket is
a *proposed* exercise at `:665` and `:904` that was never built; Release 3's
branching was actually exercised on `vent-ball-combine` and recorded on
`berlingo-knob` (`ROADMAP.md:122`). The comparison list under it names four
dimensions this build has no instrument for (hardware requirements, assembly,
adjustability, strength uncertainty). Repoint both at
`branch-knob-seat-fallback` and at §4's measurable set.

**Finding 2 — one proof is already true; replace it with the one that is not.**
"An alternative cannot loosen a shared mandatory tolerance to pass" is
structurally guaranteed by `acceptance.py:246` and `cli.py:1159` (§1). What is
*not* guaranteed is that two formulations were measured against the same checks:
coverage is computed against each formulation's own declared features
(`commission.py:436`), so a sibling declaring fewer rows scores 1.0 against its
own smaller contract. Restate the proof as "two formulations measured against
different check sets are reported incomparable on those checks, not equal", and
make it slice 1's first fixture.

**Finding 3 — the exploration-limit bullet is three-quarters shipped and
one-quarter mis-scoped.** AI calls per alternative and context duplication are
measured per formulation and *capped per invocation* by a ceiling the compiled
plan declares (`cost.py:121`, frozen at `cost.py:114`); repeated deterministic
work is measured. A cap on the *number* of active alternatives is not built, and
should not be built here: nothing generates one. Move the count cap to whichever
release builds a generator, and restate the bullet as what shipped —
"exploration cost is measured per formulation and bounded per invocation".

**Finding 4 — mark one proof vacuous rather than implementing it.**
"Cosmetic-only variants are not automatically treated as concept branches" is
satisfied by construction while nothing is automatic (`cli.py:2015`). Keep the
proof, record that it is vacuous today, and note that it becomes real work in
the same release that builds a generator.

**Finding 5 — the rest of the scope is sound.** Alternative formulation,
disposition, comparison dimensions "when present rather than mandatory
categories", and "mandatory failures cannot be hidden by weighted totals" are
all right and all worth keeping as written. No manufactured finding.

**Two consequential edits this slice implies elsewhere**, recorded rather than
made:

* `docs/adr/0001` lists the unbuilt verbs `commission`, `audit`, `motion`,
  `coupon`, `package` and does not name `compare`. If slice 1 adds a verb, that
  table gains it in the same commit, or the command surface has two authorities.
* `ROADMAP.md` 4.4's "shared work is reused across alternatives — **this clause
  now fails, measured**" is untouched by this slice. Comparison shares nothing
  because it builds nothing; `builds_avoided` stays 0. Recorded so the clause is
  not read as improved.
