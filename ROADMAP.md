# Roadmap

## 1. Purpose

This roadmap describes how to evolve the current repository into the system defined by `ARCHITECTURE.md`.

The roadmap is incremental by design.

Every release increment must:

* improve a capability that a user can exercise;
* preserve useful existing behavior;
* remain small enough to review and benchmark independently;
* add regression protection before or with invasive changes;
* be exercised on authentic modeling work;
* produce lessons that may revise later increments;
* avoid unnecessary runtime, context, process, and AI cost.

This document defines the current best path, not an immutable sequence.

The architecture defines the intended destination. This roadmap may change whenever implementation evidence or real projects reveal a better route to that destination.

## 2. Current position

The current baseline on `main` provides these foundations:

* one command surface for running a job;
* a canonical project representation;
* a compiled execution plan;
* one route authority consumed by the runner;
* unchanged dispatch counts across existing routes;
* fast certified deterministic generation;
* authored custom geometry support;
* divergent design alternatives, isolated on disk and in the review bindings, at no cost to a job that declares none;
* a current status computed from the bindings the receipts carry, and invalidation scoped to what depended on the change;
* every reason a project cannot be routed reported as a finding — a grouped code, an exact field path, a severity and a stable id — beside the sentence a person reads;
* what a job cost, recorded per formulation as it is spent and checked against a ceiling the compiled plan declares;
* STEP, STL, and modern production-extension 3MF diagnosis;
* correct 3MF root, unit, component, and build-transform handling;
* controlled failure for malformed or unsupported geometry;
* deterministic L0 benchmark infrastructure;
* an L1 replay harness, and four recorded jobs — one authored, one modification, one branched three ways, one correctly refused — replayed through the command surface with no live AI call;
* structurally separated public and private fixture material;
* selected real benchmark artifacts;
* reproducible packaging and toolchain identity;
* a comparison of a job's formulations that refuses to rank them, and says which of their verdicts are not comparable and why.

### Where this can be developed

**The confined build boundary now has two implementations, and neither degrades.**
`AGENTS.md` requires candidate code to be executed only through a boundary that
reduces its authority *by the operating system* and bounds its lifetime. That
was implemented for Windows only, so on any other platform the pipeline refused
to execute a candidate at all — correctly, but it meant a Linux checkout could
not run a single replay, could not record one, and could not touch the cache
slice or anything else on the build path.

`pipeline/confine_posix.py` is the second implementation. Four properties, each
re-measured by `benchmarks/heavy/test_confine_posix_heavy.py` rather than
asserted:

| property | Windows | Linux |
|---|---|---|
| filesystem authority | restricted token + Low integrity label | mount namespace, `mount_setattr(AT_RECURSIVE, RDONLY)` over `/`, one read-write bind for the build directory |
| network | **open** — `docs/defects.md` D11 | **closed** — network namespace with no interfaces; `ENETUNREACH` |
| bounded lifetime | job object, `KILL_ON_JOB_CLOSE` | PID namespace; init exits and the kernel kills the rest, with no breakaway flag to attempt |
| no child processes | `CHILD_PROCESS_RESTRICTED` before the process starts | seccomp-BPF refusing `execve`, installed by the child immediately before the first candidate import |
| authority reduction | restricted token, same user | empty capability bounding set, same user |

**Availability is decided from effective `CAP_SYS_ADMIN`, not from uid.** The
probe used to ask `geteuid() == 0`, which is a different question and was wrong
in both directions: a root process in a container whose bounding set omits the
capability was told the boundary was available and then failed with a bare
`EPERM` from `unshare`, and a process holding the capability at a nonzero uid was
refused while holding exactly what the construction needs. The capability is now
read from the kernel. Effective is what counts — permitted-but-not-effective is
refused and named as such, and never raised into the effective set, because
raising it would be an escalation performed unasked.

Three states stay distinct and must not be collapsed into each other:

* **unavailable and refused by name** — the boundary cannot be built here, the
  reason says which mechanism is missing, and it is produced before a candidate
  is staged. No candidate byte runs.
* **available and re-measured** — the boundary was built and its four properties
  were re-measured against the kernel rather than asserted from this table.
* **candidate execution** — a candidate actually ran inside it.

The pre-merge job is where the second and third are established rather than
assumed. It runs in a digest-pinned container with `--cap-add=SYS_ADMIN` and a
preflight that prints the capability masks, fails with the exact
`unavailable_reason()` if there is one, and then builds a real confined child.
Nothing there is skipped: a tier that cannot construct the boundary reports on
nothing, and skipping the cases that need it would turn that into a green tick.

The strongest evidence that the Linux boundary is not the weaker one is not any
of those rows: it is that **the L1 replay suite reproduces every value the
Windows recordings froze**. A boundary that leaked would not reproduce a digest.

The exact shape of that evidence changed when Release 4's slice 2 landed, and
saying so matters more than keeping the older, simpler sentence. This paragraph
used to read "against recordings frozen on Windows and not re-recorded" — which
was true until that slice re-recorded all four cases on Linux to add the compare
step. The claim available now is different and stronger: the Linux re-record was
diffed key by key against the Windows-frozen recordings and **changed no value
any of them held** — 0 keys removed and 0 values changed across four cases,
every difference an addition. Reproducing a recording is evidence; reproducing
one you then rewrite and finding you rewrote nothing is the same evidence with
the digests checked one at a time.

The suite runs on a bare checkout, well inside its two-minute budget, and a
case whose supplied artifact is not on the machine skips rather than passing
quietly. Exact counts are reported in each commit and in the pull request that
lands the slice, not pinned here: this line has said 61 and then 66 and then 67
while nothing about what L1 covers changed, and a number that goes stale without
going wrong is worse than no number.

**Path and executable parsing is cross-platform, and the commit gate has no
platform allowance left.** It used to have one: thirteen L0 tests failed on
Linux and were filed as Windows assumptions rather than defects. They were
defects, and one defect wearing two hats — `Path` was the authority in two
places and `Path` is whichever host is reading. A path recorded on another
machine is now parsed in the flavour it was written in, by a rule stated once in
`tools/fixtures.py`, and a spawn event's executable is read the same way by a
rule stated once in `conftest.py`: Windows for a drive letter, a UNC name or any
backslash, POSIX otherwise, with the host never consulted. Windows and POSIX
paths give the same basename on either machine, so a fixture manifest means one
thing in two checkouts. Both rules are covered on Linux and Windows and both are
mutation-proven. The gate is green on Linux with no expected-failure list, and
counts are reported per commit rather than pinned here, where they go stale
silently.

The following work is already complete and is treated as the protected baseline.

**Route authority**

The project route is compiled once and the runner consumes the resulting execution plan without re-deriving it.

**Diagnosis hardening**

Modern 3MF structure, external model parts, component transforms, root relationships, geometry condition, and cyclic component graphs are handled explicitly.

**Benchmark foundation**

The repository has:

* fast component fixtures;
* real source artifacts;
* public/private answer separation;
* fixture licensing rules;
* immutable artifact checks;
* an L1 replay harness (`tools/replay.py`) and four recorded cases under `benchmarks/replays/`, run separately from the commit-gating suite;
* a commit gate that is one, rather than the whole suite under a different name: `benchmarks/heavy/` holds the component fixtures that cost a child interpreter, and the root `conftest.py` refuses one inside the gate.

The replay harness answers the question section 4.3 asks and section 5.1 defines,
and its own docstring carries the argument for what a replay asserts — the exit
sequence, the status and the verdicts under it, the per-check verdicts, the
measured values inside the bands the contract declares for them, the receipt set,
and four hashes that are equalities between two values from the same run — and
what it deliberately does not: receipt bytes, any pinned digest, and the prose,
which is recorded and reported as advisory so that a reworded sentence cannot
stop a build. A branched case adds one binding layer to that list — the status
each formulation currently *derives*, which is computed rather than written down
and is the only place `STALE` exists. Every case is frozen at the commit that
added it, because an expectation lifted from a run at an older commit encodes
that commit's defects along with its behaviour.

The immediate unresolved blockers are:

1. **closed.** Unchanged modification jobs complete review resumption. Preservation evidence is derived rather than drawn: identical inputs produce byte-identical evidence, the review envelope binds the packet, the sample plan, the audit digest, the execution plan and the acceptance revision, and a stored answer is refused when any one of them moves. Release 1's nine proofs are listed in the ledger below and were re-run from a clean pinned checkout. What is *not* closed is the strength of the preservation method itself — sample density is still not derived from a declared minimum detectable defect size — so a job with an edit scope still reports `EXPERIMENTAL_UNAVAILABLE` and still cannot claim success. That is the fifth blocker below, and it is a different sentence from this one;
2. **closed.** Candidate code cannot reach the criteria that judge it. The acceptance contract is generated from the frozen proposal and system-owned inputs and written to disk before `model.py` is executed at all; `acceptance.generate` has no parameter a mesh could arrive through; and the build happens in a one-shot confined process handed a sealed source directory and nothing about acceptance, so the interpreter holding the contract, the bands and `status.decide` never runs candidate code. Section 4.2 records this as a pass. What remains open is narrower and is tracked as its own defect rather than as a blocker: an authored proposal still chooses the *rubric* it will be graded against, which is why `compare` refuses to call two formulations' verdicts comparable when their expectations differ;
3. divergent design alternatives are now declarable and isolated, and the graph is not yet complete. `design-tool branch` records an alternative with an id, a **list** of parents, a reason and a disposition, and writes everything belonging to one formulation under `alternatives/<id>/` — proposal, model, artifacts, acceptance revision, reviews, receipts. Sibling isolation is structural rather than checked: each alternative freezes its own acceptance contract, so neither can cut a revision from the other's, and `alternative_id` joins the execution plan and the review envelope so a review answered for one branch is refused by the other even at the instant the two are still byte-identical copies. `candidate_strategy: PARALLEL` is retired in its favour. Status is no longer stored and repeated: `design-tool status` derives what the evidence on disk currently supports from the bindings each receipt records, weakening a stored success to `STALE` when they no longer hold and never re-adjudicating anything; invalidation removes what depended on the change rather than a fixed six-name tuple; `project.json` no longer mirrors either a run's outcome or its bindings; and `next_action.json` carries the state it was computed from, so a superseded instruction can say so. A project problem is data rather than prose: `Project.validate()` returns `Issue` values — the type `team_tools` already had, moved to `pipeline/findings.py` so both packages report through one — each carrying a code from a declared group, a field path that names a position (`edit_scopes[1].region_box`) rather than a name, a severity, and a stable `CODE@where` id no other finding in the report shares. The grouping rule is the prefix: `SCHEMA_` means correct a field, `REF_` means add or rename a row, `ARTIFACT_` means fix a file, `INTENT_` means make a decision. The English is unchanged and `next_action.unresolved` is still a list of sentences; the structure arrives beside it under `findings`, in the refusal instruction and in `design-tool status --json` alike. The lifecycle group is closed. All seven dispositions are honoured and each changes something rather than labelling: `PREFERRED` is at most one per project and switching it demotes the previous holder to `ACTIVE` rather than erasing it; `FALLBACK` is runnable — the vent-ball job had to record a genuinely retained fallback as `ACTIVE` because a build that would not run one gives "retained" and "abandoned" the same behaviour — and `design-tool status` names it as the option to fall back on exactly when the current formulation has no claim; `PAUSED` is not runnable and keeps its instruction, and resuming it is a recorded transition rather than a silent activation; `REJECTED`, `SUPERSEDED` and `MERGED` are concluded, clear the instruction in their directory and keep every receipt, and the last two must name the formulation that replaced them — `MERGED` refused unless that formulation's `parents` actually record the merge, so the state cannot be claimed ahead of the capability. Every state but `ACTIVE` must carry its basis from a closed vocabulary, which is what ARCHITECTURE.md 14.6 always required. `design-tool run` gained `--resume` and `--restart`: resume is what a bare run already did, said out loud and refusing when there is nothing to continue; restart discards *what this formulation concluded* — its receipts and its review answers — and keeps what it concluded from, which is the frozen contract, the proposal, the model, the content cache and every sibling. Its whole point is the case scoped invalidation is blind to by construction: a conclusion whose bindings still hold and that somebody no longer trusts. Run identity is decided rather than deferred and is content-derived — the digest of the whole binding map, so two formulations byte-identical at the instant one was branched from the other are still two runs, and a rerun on unchanged inputs is still byte-identical ([ADR 0004](docs/adr/0004-run-identity-is-content-derived.md)). `lifecycle.json` is the one file here ordered by when things happened rather than by what they contain, bound by nothing, holding the restarts and the transitions. What a job costs is now recorded rather than estimated. `pipeline/cost.py` writes `cost.json` in each formulation's own directory — one entry per invocation of `design-tool run`, bound by nothing, for the reason `lifecycle.json` is — holding the dispatches actually made, the canonical byte size of each context handed over, the deterministic seconds and the confined boundary's share of them, the builds and the builds beyond the first, the cache status and the builds a hit actually avoided, and every invocation that concluded nothing. `design-tool status --json` reports it per formulation under `cost`, with `incremental` naming what each formulation beyond the shared root added: on the recorded three-formulation `berlingo-knob` replay each sibling costs one dispatch, 23.8 kB of context, ~2.9 s and two builds, and `shared` is zero builds and zero reviews — the number the vent-ball exercise had to take with a stopwatch. Two things the counter it reuses had wrong are now visible: `llm_calls` never counted the designer commission, because `AGENT_COMMISSION` is written by `cli.py` before the runner is reached and is the live dispatch on the authored lane; and summed across a resumable job it counts a stored answer re-read by a later invocation as a fresh dispatch, so a `MODIFY` round trip reports three dispatches where two questions were asked. The ledger counts the question at the pause that wrote the packet and records the re-reads as `reviews_reused`. The budget is the compiled plan's: `cost.budget(plan)` is what one invocation may dispatch, a run that spends past it is refused with stage `cost`, and the per-route numbers are frozen in the shipped module the way `selftest.FROZEN_CONTRACTS` freezes a certified contract — which is what turns 3.4's "no release may add an AI round trip to an existing path as an accidental side effect" into a failing test. What is still owed: merge (several contributing parents), alternative comparison and scoring (Release 4 owns both), scoping below job-versus-alternative, capability-based execution, the lazy assessment registry, the context *packages* — task-specific assembly, which is the other half of the context-budget item and is untouched — and the dormant tolerance, material and operation fields;
4. Multi-artifact edit intent is now declarable: `edit_scopes` supports several source artifacts, coordinated scopes may share existing interfaces through `interface_ids`, and the plan and gate preserve one obligation per scope. Multi-source candidate production and preservation measurement remain unavailable.
5. preservation is not yet strong enough to support successful modification claims;
6. fitted authored designs and moving assemblies are not yet complete end-to-end capabilities;
7. physical outcomes and alternative comparisons are not yet part of a systematic learning loop.

Several narrower gaps are carried forward from the completed consolidation work. They are not blockers in the same sense, but they are owed and are easy to mistake for finished work:

* the command surface described by ADR 0001 is only partly built. `doctor`, `selftest`, `init`, `route`, `run`, `status`, `branch`, `diagnose`, and the deprecated `run-job` exist; `commission`, `audit`, `motion`, `coupon`, and `package` do not. Until they do, the older `dt.py` verbs stay in agent instructions.
* designer commissions are not yet generated from canonical project state, and the template registry does not yet distinguish a certified template from a starting one.
* a job that declares motion routes `FULL`, and its motion modifier is reported `DEFERRED` rather than measured. The sweep engine does not exist. Naming it unmeasured is deliberate and is not a substitute for Release 8.
* there is no resource governor, and the 3MF writers are not versioned adapters.
  One stage is bounded and the rest are not: the preservation audit now declares a
  memory ceiling, derives its query batch from it, and refuses before allocating
  past it — which took the vent-ball pair from 23.24 GiB peak and a `MemoryError`
  to 2.16 GiB and a completed run. That is one limit on one instrument, reached
  because a real job hit it. A governor is the thing that would bound every
  geometry stage under one policy, account for what a job is allowed to spend, and
  be declarable per job rather than compiled into a constant; none of that exists.
* preservation sampling is deterministic but its density is not derived from a declared minimum detectable defect size, and exact STEP comparison is undecided. A real modification job put a number on what that costs: the entire defect the audit had to find was 85 faces of a 93,530-face part, under a tenth of a percent of its surface. Every job that declares an edit scope therefore reports `EXPERIMENTAL_UNAVAILABLE` rather than a successful status.
* preservation also has one verdict for one box. The same job needed three dispositions over named regions — geometry that must not move, geometry permitted to change, and geometry the edit deliberately consumed — because the deviation its audit reported, an unfiltered global maximum of 1.797 mm, *was* the requested change: material consumed where the two parts now interpenetrate, in a band opened to 2.88 mm by design. One box and one band cannot tell that apart from a defect, so the checker fails a correct part.
* there is no repair path at all. `design-tool diagnose` classifies an artifact `REPAIR_REQUIRED` and stops, so a supplied file with non-manifold or open geometry cannot be modified through this skill even though `MISSION.md` names repair as a required capability and `ARCHITECTURE.md` §11.4 specifies it.
* nothing certifies what an export writer wrote. A clean float64 solid became 429 zero-area faces and 367 non-manifold edges when written as binary STL, and two halves of one job independently hand-wrote the same float32-weld and file-versus-memory checks. Preservation and commissioning measure a file, and no tool currently proves the file carries what the geometry in memory did.
* datum precedence is enforced, and the sampling density it waits on is not. Datums carry provenance and are dependency bindings now — the declaration obligation landed in Release 5 below, so a datum records where its number came from, the artifact revision it was read on, and the scope it is valid in, and coordinated scopes reference one identity instead of each holding a copy; and ADR 0003 decision 5 closed with `docs/defects.md` D31, so the acceptance contract binds the canonical contents of exactly the datums an edit is placed against, and **correcting a referenced datum's value cuts a new acceptance revision, refuses the review answer written against the old number, and invalidates the receipts that rested on it**. **Decision 6 has since landed.** Precedence between a datum and other evidence is a property of the authoritative model rather than of the file that introduced it, and that is now enforced rather than merely true by omission: `project.datum_conflicts` reports where a declared datum and an observation of it disagree *with neither winning*, `status` carries the conflict into the receipt and withholds the success claim that rested on it, and `observes_datum_id` is what ties an observation to the datum it observes. Six mutations of those protections were attempted and six killed (`benchmarks/mutations/adr0003-decision6.json`). The `EXPERIMENTAL_UNAVAILABLE` cap does **not** lift on this alone — the sampling-density reason it exists for is untouched. [ADR 0003](docs/adr/0003-datum-provenance-and-authority.md) records the case: a hand-authored shared datum, one of whose fields described a part before that part was modified, was given blanket precedence by an agent brief, and the compliant action was to build three features that must not exist. Nothing has to stop today only because a job with an edit scope is capped at `EXPERIMENTAL_UNAVAILABLE` and cannot claim success — which is the ADR's own reason, and the cap may not lift before decision 6 closes.
* a `FITTED` or `FULL` job built from authored geometry reports `UNSUPPORTED`. That is a limit of what this build can do, not a stage that is pending.

Tolerances today are single numeric bands owned by the pipeline. There is no tolerance profile, no datum model beyond what a dimension names, no per-body material assignment, and no operation model. Those are introduced by the releases below, at the point where a real job needs them.

### Release ledger

One row per release, so that "what shipped" is readable without reading the
release sections. `COMPLETE` means every applicable section 4 gate is met and
the release's own proof list has evidence; `PARTIAL` means the capability works
and a named gate does not; `BLOCKED` means a proof or gate fails. A release is
not complete because its scope list is ticked — Release 1 is why that sentence
is here — and a limitation in the last column is a real limit on what may be
claimed, not a to-do.

| Release | Status | Applicable section 4 gates | Supporting fixture or authentic job | Remaining limitation | Next permitted work |
| --- | --- | --- | --- | --- | --- |
| **1** — stable evidence and resumable review | `COMPLETE` | 4.1 pass · 4.2 pass · 4.3 pass · 4.4 pass · 4.5 pass · 4.6 pass | `benchmarks/heavy/test_phase3_heavy.py` (`DeterministicEvidenceTest`, `ModifyReviewRoundTripTest`, `ModifyRerunRejectionTest`, `ModifyCleanCloneTest`); L1 `modify-ball-flange-flat` over the real vendored `ball_male_17mm.stl` | The evidence is repeatable; the preservation **method** is still not sufficient for a successful modification claim, which the release scoped out explicitly. Sample density is not derived from a declared minimum detectable defect size, so every job with an edit scope is capped `EXPERIMENTAL_UNAVAILABLE`. D22 — OCC cannot mesh six legal cone faces in `vent_mount.step` — stays open and reaches the receipt as `UNAVAILABLE / PRESERVATION_UNMEASURABLE` by name. Release 1 promised neither STEP repair nor successful preservation. | Release 6 owns STEP repair (D22). Sample density derived from a declared defect size, and the lifting of the `EXPERIMENTAL_UNAVAILABLE` cap, remain owed and are not scheduled here. |
| **2** — trustworthy ordinary custom design | `PARTIAL` | 4.1 pass · **4.2 pass** · 4.3 partial · 4.4 pass · 4.5 partial · 4.6 pass | L1 `custom-knob-sleeve`; `pipeline/test_acceptance.py`; the confined build boundary's own fixtures | 4.3: the release shipped with no replay of its own and the two cases that cover it were recorded afterwards, so its regression evidence is retrospective. 4.5: no candidate from this lane has been printed or physically fitted. An authored proposal still chooses the rubric it is graded against — `compare` refuses to call two formulations' verdicts comparable when their expectations differ, which contains the problem rather than solving it. | A live authored job printed and fitted would close 4.5. The rubric question is Release 4's `INCOMPARABLE_EXPECTATIONS` verdict and is not a defect to fix here. |
| **3** — revision graph, branching, lifecycle, context budgets | `PARTIAL` | 4.1 partial · 4.2 pass · 4.3 partial · 4.4 **fail, measured** · 4.5 partial · 4.6 pass | L1 `branch-knob-seat-fallback` (three formulations, one preferred, one retained); `pipeline/test_lifecycle.py`; `benchmarks/heavy/test_lifecycle_heavy.py` | Merge with several contributing parents, capability-based execution, the lazy assessment registry and the context *package* half are unbuilt. 4.4 fails on one clause with a number: shared work is not reused across alternatives — `runner.run` calls `backend.build` before consulting the cache, so a hit confirms the bytes and saves nothing, and `builds_avoided` is zero on every path. Two of thirteen declared proofs have nothing behind them. | The cache-before-build inversion is **not** a self-contained fix, and a slice that investigated it is how that was learned: certified backends have precomputable build identity while the authored lane has only post-execution confirmation, so 4.4 cannot be moved by reordering two calls — see the 4.4 clause below. Merge needs the graph work the release scoped and did not start. |
| **4** — alternative formulation and comparative assessment | `PARTIAL` | 4.1 pass · 4.2 pass · 4.3 pass · 4.4 pass · 4.5 partial · 4.6 pass | L1 `branch-knob-seat-fallback`; `pipeline/test_compare.py` | Preference is admissible only when every formulation has a current verdict and the rubrics agree; on the one real job they do not, so the recorded reason is `USER_SELECTION` — a person chose, on no measured ground. The release proves the mechanism and the claim it carries is small. D24, D25, D26 and D27 remain open against it. | A job where the merits are measurable — every formulation current, rubric shared, deciding axis instrumented — is what 4.5 is reaching for. |
| **5** — datum provenance and authority | `PARTIAL` | 4.1 pass · 4.2 pass · 4.3 pass · 4.4 pass · 4.5 not yet applicable · 4.6 pass | `pipeline/test_datums.py` (49 fixtures; 37 mutations attempted and killed for the declaration obligation, 14 more for D31's binding) · `benchmarks/heavy/test_datums_heavy.py` (the end-to-end refusal and the cross-process digest) | [ADR 0003](docs/adr/0003-datum-provenance-and-authority.md) decision 5 **landed** with `docs/defects.md` D31: a datum is in the §13.4 binding list, the acceptance contract binds the canonical contents of exactly the referenced datums, and correcting one cuts a revision, refuses the stored review answer and invalidates the receipts that rested on it — driven end to end rather than composed. Decision 6, precedence between a datum and other evidence, **has since landed**: `project.datum_conflicts` surfaces a datum-versus-observation disagreement with neither value winning, `status` carries it into the receipt and withholds the claim resting on it, and six mutations of that were attempted and killed. Still capped `EXPERIMENTAL_UNAVAILABLE` for every job that can rest on a datum, asserted by a fixture so the day the cap lifts the test goes red. | Decision 6 has closed; the `EXPERIMENTAL_UNAVAILABLE` cap still may **not** lift, because the sampling-density reason it exists for is the remaining blocker and is untouched. No authentic job has exercised a datum yet. |

### Release 3 measured against section 4

Four slices of Release 3 are implemented — branching and sibling isolation, derived status with superseded instructions, structured project findings, and the lifecycle group (run identity, explicit resume versus restart, the seven dispositions). That is not the same as the release being complete, and Release 1 is why this is written down: a release is not finished because its scope list is ticked. Measured against the six gates:

* **4.1 functional — partial, and one clause of it now passes outright.** `branch`, `run` and `status` work through the normal command surface, refuse actionably, keep producing receipts when the claim is limited, and cannot let one alternative overwrite a sibling's artifacts. "Supported interrupted work resumes correctly" was previously met only by re-running the identical command; `--resume` now asserts that precondition and refuses when nothing has concluded, `--restart` discards this formulation's conclusions and keeps what they were concluded from, and run identity is decided and content-derived ([ADR 0004](docs/adr/0004-run-identity-is-content-derived.md)). What keeps this gate partial is the rest of the release, not the lifecycle: capability-based execution, the lazy assessment registry, the context budget and merge are all still absent.
* **4.2 authority — pass.** The runner consumes the compiled plan, candidate code cannot reach the criteria that judge it, a review is bound to the evidence *and* the formulation it was answered for, derived status can only ever weaken a claim, and branching copies nothing — so a shared mandatory requirement is shared by construction rather than by a check that could be forgotten.
* **4.3 regression — met for Release 3's own work, and still not for Releases 1 and 2.** The suite is green, the new behaviour has component-level coverage, and each slice's principal protection has been shown to fail under mutation. `tools/replay.py` drives a recorded job through `design-tool branch`, `route` and `run`, answering every review from a recorded judgement and never from a live call, and reads the derived status by calling `status.report` — the same assembly `design-tool status` renders — rather than by parsing what a `--json` invocation printed, and `benchmarks/replays/` holds four cases: an authored `CUSTOM` job; a `MODIFY` job over the real vendored `ball_male_17mm.stl` with a declared edit scope, a preservation row inside the frozen contract and a two-review round trip; a three-formulation branched job on the `berlingo-knob` request; and the same `MODIFY` job with its edit scope as somebody first mis-wrote it, refused before it builds. The branched case is the one this clause turned on: two siblings from one ancestor, each freezing revision 1 and superseding nothing, one building a materially different solid and one byte-identical to its parent — so a verification PASS written for the ancestor is refused by the fallback, and the suite shows the two envelopes differ in nothing but `alternative_id`, carried directly and through the execution plan, which is the false pass 4.2 forbids. The fallback's model is then revised after its run concluded and its stored `VERIFIED` derives `STALE` while both siblings stay current. The refused case carries slice C: `next_action.json` kind `FIX_PROJECT` with `SCHEMA_RANGE@edit_scopes[0].region_box.y` and `REF_UNDECLARED@edit_scopes[0].interface_ids[0]`. All four run on a bare checkout; the suite is 62 s against a two-minute budget. Read the clause as a claim about Releases 1 and 2 and it is still false, and cannot be made true: those releases shipped with no replay and nothing written now changes that. Read it slice by slice for Release 3 and one piece is still missing: slice C is *superseded instructions and structured findings*, and only the findings half has a replay. `waiting_for_superseded` does not, because no case here reaches the state it describes — a job either finishes, which clears the instruction, or is refused, which leaves one that is still true. Manufacturing a state change that made a true instruction report as superseded would be recording the mechanism firing on a case it was not built for, which is worse evidence than none. Everything else Release 3 shipped through those three slices has a replay. The lifecycle group deliberately has none, and the reason is the same one that keeps `waiting_for_superseded` out: a replay drives a recorded *job*, and a disposition transition is a recorded *decision a person makes*. No committed case pauses, prefers or rejects a formulation, and inventing one so that the mechanism fires would be recording it on a case it was not built for. What the group has instead is 31 component fixtures, every protection of which was shown to fail under mutation — 18 mutations, 18 caught — plus three end-to-end cases in `benchmarks/heavy/test_lifecycle_heavy.py` where the discard has to survive the confined build boundary and a real review round trip. What still has no evidence of any kind is what Release 3 scoped and did not build — merge, capability-based execution, the lazy assessment registry — where a replay of an absent capability is not a thing that can be owed.
* **4.4 performance — partial, and less vacuous than it was.** A job that declares no alternative gains no key in `project.json`, the execution plan or the review envelope, and the five pinned contract goldens are unmoved. Dispatch counts are unchanged, and they are now *checked* rather than reported: the compiled plan declares a per-invocation ceiling, the run is refused for exceeding it, and the per-route numbers are frozen in `pipeline/cost.py`. The clause about a job declaring no tolerance profile, no per-body material and no operation plan passes only because those fields were never built — it is vacuous rather than satisfied. "Cache behaviour is measured rather than assumed" now passes and the measurement is unflattering: the content cache is consulted *after* `backend.build` returns, so a hit confirms the bytes and saves nothing, and `builds_avoided` is zero on every path. "Shared work is reused across alternatives" **fails, measured**: three formulations of one job pay six builds and three dispatches between them, the fallback that builds a candidate byte-identical to its parent's costs 98% of what its parent cost, and nothing computational is shared. Shared *intent* is still reused, and intent is free. Every suite budget can now be read off a run. The ladder is structural at both joints — `testpaths` names `skills/3d-modeling/scripts` and `tools`, and neither `benchmarks/heavy` nor `benchmarks/replays` is in either, so a bare `uv run pytest` collects only the commit gate — and CI runs them as separate jobs, L0 on every push and the other two on pull requests. Measured on the reference machine: the L1 replay suite is **62 s** against a two-minute budget — 35 s of that is the two cases recorded first, 31 s the branched job and its adversarial replay, 2 s the refusal. The lifecycle group added nothing to it, correctly: a paused or preferred formulation is a decision a person makes, and no committed case makes one. The commit-gating suite was **994 s** against a five-second budget, and the split that measurement made possible is now done: profiling it per test showed 194 of 1163 tests starting a child interpreter and holding 876 s of 1020 s, so the seam was cut there. The gate is **45 s** over 869 of those tests — 43 s over 838 before the lifecycle group added 31 — the 350 that moved plus three written since run before merge as **L0-heavy**, 353 tests in **889 s**, and the budget is amended to a minute in section 4.4 with the argument for why five was not reachable. Structure decides which tier collects a file; `conftest.py` decides whether it belongs there, by refusing a child process inside the gate rather than by trusting a decorator. The branched case is also where the zero-cost claim stops being an assertion about serialization: a case that declares no formulations issues no `branch` command, produces the recording it produced before formulations existed, and the two cases frozen at `4442921d` did not move when the harness gained the capability.
* **4.5 real job — partial, and less partial than it was.** The vent-ball combine exercise at `2721ffe` drove the branch half on real geometry and recorded it properly: two formulations, per-alternative acceptance revisions, a review answer accepted by one sibling and refused by the other at the instant the two were still byte-identical, and a materially different solid from each. It is honest evidence and it counts for the branching slice. It does not count for slices B and C: it was run before derived status existed, so nothing in it exercises a stale binding, a `waiting_for_superseded` instruction or a structured finding, and its own `next_action.json` carries no `state_sha256` at all. What has changed is that both now have evidence of a different kind — two recorded jobs, on the real `berlingo-knob` and `vent-ball-combine` requests and the real vendored `ball_male_17mm.stl`, driven end to end through the command surface with no live call. That is a weaker instrument than a live commission and it is not nothing: a stale binding and a structured finding are now produced by a whole job rather than by a unit fixture, which is the gap this clause named. What is still owed on this gate, honestly, is a live exercise: nobody has *used* derived status to make a decision about a real part, no alternative has been paused, preferred or rejected on evidence, and neither replayed job was printed, fitted or physically tested. For the lifecycle group that gap is now exercise rather than absence — the transitions exist and refuse a disposition with no basis — but "the vent-ball fallback was recorded as `ACTIVE` because there was no way to say `FALLBACK`" is a defect this closes prospectively: that recording is frozen at the commit that produced it and is not being rewritten to use a capability it did not have. `--no-render` means no witness image exists in either, so nobody has looked at either part. Read 4.5 as "the release has been exercised on an authentic project" and branching passes and B and C do not; read it as "every slice has been driven on real inputs outside its own unit tests" and all three now have.
* **4.6 documentation — pass.** `docs/tooling.md` describes the command surface as it behaves, and this section names what is missing rather than implying it is present. The Release 3 section further down is still a statement of intended scope and is not a claim about what shipped; the list below is what closes the gap between the two.

Still unbuilt from Release 3's own scope: merge with several contributing parents; scoping below job-versus-alternative (component, interface, manufacturing configuration); the dormant tolerance-profile, per-body material and operation fields and the scoped invalidation that would depend on them; capability-based execution; the lazy assessment registry; and the *context-package* half of the context-budget item — task-specific assembly, which nothing has asked for and which 3.1 would call a broad unfinished framework today. The *measurement and budget* half of that item is built: `pipeline/cost.py`, `cost.json` per formulation, the per-alternative incremental figure in `design-tool status --json`, and a per-invocation dispatch ceiling the compiled plan declares and the run is refused for exceeding. Of section 15.6's eight, seven are recorded — AI dispatch count, context size, deterministic runtime, cache reuse, repeated work, failed work, per-alternative incremental cost — and one, **import cost**, is deliberately not decomposed: separating a fresh interpreter's `import trimesh` from the build inside it needs an import hook in the confined child, which is machinery nothing has asked for, and `docs/baseline.md` already decomposes it by hand. What is recorded instead is `warm_kernel`, which says which regime a measurement was taken in. **Two** of the release's thirteen declared proofs now have nothing behind them, down from four: an explicit merge record with multiple parents, and a changed material assignment invalidating only what depended on it. The merge proof moved but did not close, and the distinction is worth keeping: a two-contributing-parent row is now *validated* — a `MERGED` disposition is refused unless the formulation it names lists it among its parents — and nothing in this build ever *writes* one, so the record exists only where a hand wrote it. A proof met by a fixture asserting a hand-written row is not the proof the list asks for. The two that closed are the lifecycle transitions — a paused-and-resumed alternative, which `PAUSED` could previously reach and never leave, and a switched *preferred* alternative as a transition rather than a switched active one, which now demotes the previous holder and journals both halves. Both are component fixtures in `pipeline/test_lifecycle.py` rather than replays, which is what the proof list asks for; a replay of either would be recording a decision a person makes, and no committed case makes one.

## 3. Roadmap operating rules

### 3.1 Deliver vertical slices

Prefer a narrow complete capability over a broad unfinished framework.

A release increment should normally include:

* input representation;
* execution;
* output;
* state and resumption;
* relevant assessment;
* regression fixtures;
* one authentic use case;
* user-facing documentation.

Do not build a general abstraction unless the current vertical slice requires it or multiple real cases already justify it.

### 3.2 Keep work usable during repairs

When a capability cannot honestly claim success, it should still perform useful deterministic work where possible.

It should continue to:

* diagnose inputs;
* generate geometry;
* export artifacts;
* measure results;
* write evidence;
* support iteration;
* preserve alternative branches and their artifacts.

It must clearly limit its final claim.

### 3.3 Correctness wins explicitly

Performance and cost constraints are real product requirements, but correctness takes priority.

When correctness requires a measurable cost increase:

1. measure the increase;
2. explain which failure it prevents;
3. confirm that the cost applies only where necessary;
4. record the accepted trade-off.

No trade-off may be taken silently.

### 3.4 Preserve the common case

The intended common behavior remains:

* deterministic reusable work: zero AI design calls;
* ordinary custom work: one coherent design context;
* optional alternative exploration: explicitly requested or justified;
* additional AI calls: only when ambiguity, independence, consequence, or user preference justifies them.

No release may add an AI round trip to an existing path as an accidental side effect.

### 3.5 Treat alternative exploration as optional work

The architecture supports branching, but the system must not generate multiple concepts for every job.

Alternative exploration is justified when:

* the user asks for options;
* materially different mechanisms are plausible;
* early commitment would be costly;
* the consequences justify comparison;
* a preferred concept fails;
* a benchmark explicitly tests design exploration.

Cosmetic variants do not justify full branches unless styling is itself the task.

### 3.6 Use real jobs as design evidence

Each release increment must be exercised on at least one authentic project.

Synthetic fixtures prove mechanisms. Real jobs reveal missing concepts, bad assumptions, and unusable workflows.

### 3.7 Add engineering semantics only where they earn their cost

Tolerance profiles, multi-material assignment, compensation, and operation sequencing are added the same way every other capability is: as narrow vertical slices, driven by a real job.

There is no "implement GD&T" release and no "implement multi-material" release. The foundations appear when something needs them, and they deepen only where use demonstrates they are insufficient.

For all such work:

* begin with a narrow vertical slice, not an ontology;
* add L0 deterministic tests for the new semantics;
* add at least one L1 replay that exercises them end to end;
* use an authentic project before generalizing;
* measure runtime, context, and dispatch cost before and after;
* preserve the zero-call and one-call common paths;
* do not implement a complete ASME or ISO ontology speculatively;
* do not generalize a compensation value from one print;
* do not add operation sequencing to jobs with only one meaningful operation;
* keep required final geometry separate from manufacturing compensation in every release that touches either;
* revise later roadmap scope based on what the slice actually showed.

A job that declares none of these things must cost exactly what it cost before the capability existed. That is a measurable claim, and the performance gate measures it.

The same rule decides when an assessment gets a trigger, and it is written here because the alternative was tried and struck. Assessment today is 62–64% of a certified run and the confined build boundary is ten to twenty times that, so a registry that defers assessments would be optimising the wrong term; and the assessments worth deferring are *already* deferred, by the contract declaring the feature that requires them. So: the first release that introduces an assessment costing more than the build boundary builds its trigger then — and builds it **as** the contract, by declaring the feature that requires the assessment, rather than beside it as a second table of what to run. A separate registry is a second planning authority, which is the thing Release 10 exists to remove.

### 3.8 Separate architectural learning from project peculiarities

After each release, classify discoveries as follows.

Classification determines whether the code, roadmap, or architecture must change. It does not determine whether dependent work may continue. Any defect that violates an authority invariant, defeats a release gate, or can produce a false successful claim fails closed until repaired and regression-tested. Work that does not depend on the violated boundary may continue with its claims explicitly limited.

**Implementation defect**

The design is adequate; the implementation is wrong.

Action:

Fix the code and add a regression fixture. If the defect violates an authority or claim-strength invariant, stop the dependent success-claim path until the fixture proves the repair.

**Missing roadmap capability**

The architecture already allows the behavior, but no release currently implements it.

Action:

* add, split, or reorder a roadmap item.

**Missing domain concept**

The authoritative model cannot express a recurring real requirement cleanly.

Action:

* amend `ARCHITECTURE.md`;
* record an ADR;
* revise dependent roadmap items.

**Invalid architectural assumption**

A trust boundary, authority rule, or major decomposition is shown to be wrong.

Action:

* stop dependent work;
* revise the architecture before continuing.

**Project-specific exception**

The issue is real but does not justify a general mechanism.

Action:

* record it in the project or fixture;
* do not enlarge the core architecture without further evidence.

A severe authority or correctness defect may justify an architecture change after one demonstrated case. Convenience features should normally require broader evidence.

## 4. Release gate

Every release increment must pass the following applicable gates.

### 4.1 Functional gate

* The user-visible capability works through the normal command surface.
* Failures are actionable and controlled.
* The capability produces useful artifacts even when its final claim is limited.
* Supported interrupted work resumes correctly.
* Alternative-specific work cannot overwrite sibling artifacts.

### 4.2 Authority gate

* Runtime execution follows the compiled plan.
* Candidate output cannot redefine the criteria used to judge it.
* Reviews are bound to the evidence reviewed.
* Claims state only what the evidence supports.
* Alternative creation cannot silently weaken shared mandatory requirements.

### 4.3 Regression gate

* Existing tests remain green.
* Important new behavior receives L0 coverage.
* At least one relevant L1 replay exists.
* A mutation or adversarial test demonstrates that the principal protection can fail.

A test that only confirms a nominal verdict is insufficient when the underlying evidence chain can be asserted directly.

### 4.4 Performance gate

* Certified deterministic paths show no meaningful regression outside measurement noise.
* Dispatch counts do not increase accidentally.
* New expensive checks are capability-triggered.
* A job that declares no tolerance profile, no per-body material, and no operation plan shows no measured cost change.
* Cold and warm costs are measured separately where imports dominate.
* Cache behavior is measured rather than assumed.
* Shared work is reused across alternatives. **This clause now fails, measured.**
  On the recorded three-formulation `berlingo-knob` job, the fallback formulation
  builds a candidate **byte-identical to its parent's** and costs 2.91 s against
  the parent's 2.96 s — 98% of a solo job for the same bytes, with
  `builds_avoided` zero. The cause is not the branching: `cache.key_for` is
  content-addressed and the slot is `key.digest()`, so siblings collide on
  nothing and share correctly *in principle*. It is that `runner.run` calls
  `backend.build` **before** it looks the key up and never returns early, so a
  hit confirms the bytes and saves nothing.

  **This is not repairable by reordering those two calls, and a slice that tried
  established why.** The two lanes differ in whether build identity can be known
  before the work:

  * **certified backends have precomputable identity.** `build123d_backend`
    reports `backend_version` from the library version string and `tessellation`
    from module constants; `trimesh_manifold` reports a version string and a
    literal tessellation. Neither is a product of building, so on that lane the
    key is computable before the build.
  * **the authored lane has only post-execution confirmation.** `Cache.Key` binds
    eight fields and two of them — `backend_version` and `tessellation` — are
    derived in `isolation.py` from `_engine(built.get("kernel"))`, where `built` is
    the child's *post-run* manifest. That token is candidate-authored, and nothing
    the parent owns declares the kernel; absent a valid token `_engine` returns
    `UNRECORDED_KERNEL`. `AuthoredBackend.build` does not build at all — it adopts
    files the confined child already produced.

  Substituting `module_sha256` and `input_sha256`, which the parent does compute
  before the child exists, was considered and **refused**. They are additional
  identity, not a proof that executing those bytes again yields the same geometry:
  the authored lane runs arbitrary candidate code rather than a declarative recipe,
  in a run-specific sandbox with a generated working directory, and the same source
  may branch on runtime state, platform, time or randomness. The present cache is
  safe *because* it is post-build confirmation — an incomplete predictive identity
  cannot silently serve stale geometry when the candidate is rebuilt and its bytes
  compared. Moving the hit ahead of execution would change what the cache claims
  from "these newly produced bytes agree with stored bytes" to "these inputs
  guarantee these output bytes", and this repository certifies no such determinism
  for authored code. Having the child announce its kernel before building fails the
  same test twice: it trusts candidate-controlled information earlier and still
  does not show that two executions on one kernel produce identical geometry.

  So **4.4 stays `fail, measured`** and the clause is now understood rather than
  merely unmet: reuse across authored alternatives waits on a deterministic-build
  guarantee that does not exist yet, not on a scheduling slot. A certified-lane-only
  inversion was also refused, because it would leave the measured authored branch
  untouched while reading as a fix.

Provisional suite budgets on the reference machine:

* commit-gating L0 suite: approximately one minute or less;
* pre-merge L0-heavy suite: approximately twenty minutes or less;
* normal warm L1 replay suite: approximately two minutes or less;
* live L2 suite: on demand, limited to a small number of jobs.

These are budgets, not correctness limits. A necessary exception must be documented.

**The L0 budget was five seconds and is amended here.** It was written before the
suite existed, and the suite that exists cannot hold it. Measured at `79244ae`
with `--durations=0` and an audit hook counting process creation per test, the
997 s commit gate decomposed into 194 tests that started a child interpreter and
held 876 s — 86% of the wall clock in 17% of the tests — and 969 tests that
started nothing and cost 143 s together. Cutting at that seam leaves 830 tests in
the gate, and they measure **43 s**. Five is not reachable from there by any
route that keeps the coverage:

* the floor is not zero. `uv run pytest --collect-only` is 2.5 s on this machine,
  because collection imports trimesh, numpy and PIL across thirty modules, and
  `import trimesh` alone is 1.8 s;
* the cheapest unit of behaviour this system has to test is a job run, and the
  cheapest *confined* one is one child interpreter at ~1.6 s — so a single L0 test
  of the build boundary would be a third of a five-second budget;
* what is left is already the cheap half. 43 s over 838 tests is 50 ms each and
  the median is under 5 ms. Reaching five seconds means removing about 95% of
  them, and section 5.1's own list of what L0 must protect — branching and
  alternative isolation, preservation comparison, state invalidation — is largely
  in the part that would go.

A minute is a number a commit gate can hold and a person will wait for; five was
a number this work could only have met by protecting nothing. What the heavy half
costs is not thereby forgiven — it is 16 minutes, it runs before merge, and
bringing it down is real work this does not do.

**Read every wall-clock number here as a band, because this machine drifts.**
Within a single session the same 867 tests at the same commit measured **43.3 s
and then 76.9 s**, a factor of 1.78, and one change measured **+7.2 s, +10.5 s
and +0.1 s** on three honest attempts minutes apart. The drift lands on sustained
geometry and mesh computation and never touches import-bound work, which is
consistent with clock throttling under vectorised load. So the gate figure is
"about 45 s fast, about 90 s slow", and a timing that disagrees with a published
one is not by itself evidence of a regression.

Publish `design-tool selftest` beside any timing that matters, as a calibration
figure: it moved 4.11 s → 5.80 s (1.41×) across the same drift that moved the
suite 1.78×. It is already shipped, already run, already 11/11, so it costs
nothing to record — but it **under-reports rather than cancels**, and a reader
must not treat it as a correction factor.

Two normalisers were tried and rejected on evidence, which is worth keeping so
they are not tried again. A ratio to collection time **inverts** the answer:
`--collect-only` went 2.5 s → 2.2 s across the same drift, so it would have
reported a 1.78× slowdown as a 0.9× improvement. And a count of tests over a
duration threshold measures the machine, not the suite: 40 tests exceed 0.5 s in
the slow regime and fewer do in the fast one.

**So the enforceable half of this budget is not wall clock at all.** It is
`L0_COLLECTED_CEILING` in `conftest.py`, currently 1440 against the 1238 the gate
collects — the aggregate a slow machine cannot move, beside the two guards that
already bound the mechanisms which take a gate from 43 s to 997 s. The minute
above stays as the *product* statement, because a person waits seconds and no
ratio changes that.

### 4.5 Real-job gate

The release is used on at least one authentic project.

The outcome records:

* what worked;
* what failed;
* what required manual intervention;
* what was physically tested;
* what remains unresolved;
* which alternatives were explored;
* why an alternative was preferred, paused, or rejected;
* whether the roadmap or architecture should change.

**Where this stands as of Release 4 slice 3, stated as two clauses because they
are in different states.** Release 3 shipped branching and nobody had used it to
settle anything; `benchmarks/replays/branch-knob-seat-fallback` now does, on a
real vendored request — three formulations explored, one preferred and one
retained as a fallback through the verb a user has, each carrying a basis from
the closed set, with the decision, the state it left and the formulation the job
ends parked on all frozen in the recording.

* **"which alternatives were explored" — met.** Three formulations, each with
  its own proposal, contract, receipts and recorded reason for existing.
* **"why an alternative was preferred, paused, or rejected" — met in the weak
  sense only, and it should not be read as more.** The reason recorded for the
  preference is `USER_SELECTION`: a person chose, on no measured ground. That is
  a true answer to "why", and it is the honest one for this job, because the
  comparison declined to make preference admissible at all — one of the two
  formulations has no current verdict. What the gate is *reaching for* is a
  preference somebody can defend from evidence, and this job cannot supply one.

A release that wants to say alternatives were preferred **on their merits**
still owes a job where the merits were measurable: every formulation current,
the rubric shared, and the deciding axis one this build has an instrument for.
Until then the mechanism is proven and the claim it carries is small.

And the clause names three verbs. Only *preferred* has been exercised on a real
job: `PAUSED`, `REJECTED`, `SUPERSEDED` and `MERGED` appear in no committed
case, so two of the seven lifecycle states carry all the evidence there is.
`SUPERSEDED` and `MERGED` are refused at load by the replay harness unless they
name a successor that exists, which is a guard and not an exercise.

### 4.6 Documentation gate

Current documentation must describe what the released skill actually supports.

Future architecture must not be presented as current behavior.

## Release 1 — Stable evidence and resumable review

**Outcome**

An unchanged job can produce evidence, receive a review response, and resume without the evidence changing underneath that response.

**Why this comes first**

This is a capability-liveness defect.

A modification job that cannot complete a review round trip is not merely weakly verified; it is unusable through the intended command flow.

**Scope**

Make evidence generation deterministic where resumption depends on it.

Bind preservation sampling and evidence generation to:

* source hashes;
* candidate hashes;
* edit intent;
* source-to-design transforms;
* algorithm version;
* sampling parameters.

Canonicalize:

* mesh traversal where relevant;
* evidence ordering;
* numeric serialization;
* receipt serialization.

Bind each review response to:

* the evidence packet identity;
* the relevant execution-plan identity;
* the relevant acceptance revision;
* the sampling-plan identity where applicable.

Re-derive evidence for unchanged inputs rather than caching it, and get the same
bytes back.

This line used to read "reuse valid evidence for unchanged inputs", and the code
has never done that: the preservation audit is recomputed on every run, in about
two seconds, and only the build has a cache at all. The line was amended rather
than implemented, for the reason `pipeline/cache.py` already gives about the
layers it declines to cache — a cache key has to name every input that could
change the answer, and the key for a preservation audit is exactly the sampling
seed and the acceptance revision this release spent its effort binding. Getting
that key wrong serves a stale audit to a reviewer under a fresh-looking receipt,
which is the precise failure this release exists to make impossible. Two seconds
is not worth buying with it.

What the user needs from the line is that a rerun does not invalidate the answer
they just wrote, and determinism delivers that without a cache: identical inputs
produce byte-identical evidence, so the second run's envelope matches the first
run's. That is idempotence rather than reuse, and this release claims the former.

**Explicit exclusions**

Do not implement yet:

* adaptive high-density preservation;
* minimum detectable defect guarantees;
* multi-source preservation;
* exact B-rep comparison;
* complete inherited-overhang analysis;
* divergent alternative histories.

This release makes the evidence repeatable. It does not make the existing preservation method sufficient for a successful modification claim.

**User-visible improvement**

A user can run a modification job, answer its requested review, rerun the same command, and progress without an evidence-envelope mismatch caused solely by nondeterminism.

**Proof**

Required tests include:

* repeated unchanged runs produce byte-stable evidence;
* a response to one unchanged run is accepted by the next;
* changed source rejects the old response;
* changed candidate rejects the old response;
* changed edit intent rejects the old response;
* changed transform rejects the old response;
* changed algorithm version rejects the old response;
* interrupted and resumed runs retain one evidence identity;
* clean-clone reproduction yields the same identity.

**Authentic exercise**

Use the vent-mount and 17 mm ball project to complete an evidence and review round trip.

The final result remains limited by the current preservation capability.

### Release 1: COMPLETE

Ruled after D15 closed, from a clean worktree pinned at `f327687` and detached,
with no writer touching that checkout during the run — `git status --short` was
empty before and after. The authentic exercise is the vent-mount and 17 mm ball
project: `benchmarks/replays/modify-ball-flange-flat`, driven end to end through
`design-tool run` over the real vendored `ball_male_17mm.stl`, resolved and
hash-verified through `tools/fixtures.py` before the job sees it, with both
reviews answered from the recording and no live dispatch.

The nine proofs the release names, each against the fixture that observes it:

| # | Proof | Where it is observed | Result |
| --- | --- | --- | --- |
| 1 | repeated unchanged evidence | `DeterministicEvidenceTest::test_identical_inputs_produce_byte_identical_evidence`, with `test_a_changed_input_changes_the_evidence_hash` as its converse | PASS |
| 2 | response accepted on unchanged rerun | `ModifyReviewRoundTripTest::test_a_modify_job_completes_the_review_round_trip` — packet answered, rerun accepts it, `verification_report.json` carries the same envelope | PASS |
| 3 | changed source rejection | `ModifyRerunRejectionTest`, subtest `changed source` — the supplied plate 0.2 mm taller | PASS |
| 4 | changed candidate rejection | same test, subtest `changed candidate` — a 16 mm seat with the declared parameters left alone, which a hash of the parameter dict would miss | PASS |
| 5 | changed edit intent rejection | same test, seven subtests: `region_box`, `preserve`, `may_remove`, `add`, `expected_body_delta`, `preserve_metadata`, `interface_ids`. Edit intent is not one field, and the set is closed | PASS |
| 6 | changed transform rejection | same test, subtest `changed transform` — `alignment_transform` moved 5 mm in x | PASS |
| 7 | changed algorithm-version rejection | same test, subtest `changed algorithm version` (the sample-plan version, which lives in no file the job can edit), plus `test_an_answer_from_the_previous_protocol_is_refused_by_name` for the envelope-shape bump | PASS |
| 8 | interrupted/resumed identity | L1 `ModifyBallFlangeFlatTest::test_the_round_trip_paused_twice_and_finished` and `::test_the_rerun_did_not_move_the_evidence_under_the_answer`; the heavy round trip asserts `commission_report.json` is byte-identical across the pause | PASS |
| 9 | clean-clone identity | `ModifyCleanCloneTest::test_the_same_project_at_two_paths_measures_one_thing`, and L1 `::test_two_replays_of_one_case_produce_the_same_geometry_and_plan` | PASS |

Every applicable section 4 gate is met.

* **4.1 functional — pass.** The round trip runs through `design-tool run`,
  pauses with an actionable `next_action.json`, resumes on the same command, and
  reaches a final status. It produces receipts throughout, including on the run
  that concludes `NEEDS_MORE_EVIDENCE`. Formulation directories cannot collide.
* **4.2 authority — pass.** The review envelope binds the packet, the sample
  plan, the audit digest, the execution plan and the acceptance revision, so an
  answer is refused the moment any bound input moves; a refused answer leaves no
  decision and no `final_status.json`. The claim the receipt carries is the
  capped one.
* **4.3 regression — pass.** L0 covers the mechanisms, `benchmarks/heavy`
  carries the end-to-end proofs above, `modify-ball-flange-flat` is the L1
  replay, and the eleven rejection subtests are themselves the adversarial
  demonstration that the principal protection can fail — each changes exactly
  one bound input and requires both a `ReviewError` and no final status.
* **4.4 performance — pass.** Evidence is re-derived rather than cached, at
  about two seconds, and `pipeline/cache.py` records why: the key for a
  preservation audit is the sampling seed and acceptance revision this release
  spent its effort binding, and getting it wrong serves a stale audit under a
  fresh-looking receipt. The memory ceiling took the vent-ball pair from
  23.24 GiB and a `MemoryError` to 2.16 GiB and a completed run.
* **4.5 real job — pass.** The vent-ball combine exercise, on a real request and
  a real supplied artifact that had been printed and fitted. What worked, what
  failed, what could not be measured and what remains unresolved are all on the
  receipt rather than in prose.
* **4.6 documentation — pass.** `docs/tooling.md` describes the surface as it
  behaves, and the limitation below is stated rather than implied.

**D22 is named as a Release 6 limitation and does not block this ruling.**
`vent_mount.step` has six legal cone faces OCC cannot mesh, so a preservation
audit over it reports `UNAVAILABLE / PRESERVATION_UNMEASURABLE` — by name, in
the check row, in `unavailable_checks`, and in the sentence a user reads.
Release 1 promised neither STEP repair nor successful preservation; it promised
that the evidence and review round trip is stable, and that an instrument which
cannot measure says so instead of passing. Both hold. Repair is Release 6's.

**What COMPLETE does not mean here.** The release's own explicit exclusions
stand: preservation sample density is still not derived from a declared minimum
detectable defect size, so every job declaring an edit scope is capped at
`EXPERIMENTAL_UNAVAILABLE` and cannot claim a successful modification. That is
the limit Release 1 wrote down in advance and deliberately did not undertake.

## Release 2 — Trustworthy ordinary custom design

**Outcome**

A user can request an original or ordinary custom part and receive a meaningful result from one design context, while candidate geometry is structurally unable to rewrite its own acceptance criteria.

**Scope**

Separate:

* design intent;
* design proposal;
* geometry implementation;
* observed geometry;
* acceptance specification.

The ordinary flow becomes:

1. one design context produces a proposal and editable model source;
2. the proposal is validated and frozen;
3. the system compiles the acceptance specification;
4. the model executes;
5. the exported artifact is measured against that specification.

Acceptance information may come from:

* explicit user requirements;
* immutable source artifacts;
* accepted proposal values;
* manufacturing policy;
* system-owned tolerance policy.

It may not be re-read from mutable model code after evaluation.

Proposal changes remain allowed, but create a visible new design revision and invalidate dependent results.

*OS-enforced confined execution*

Execute authored candidate code through an OS-enforced confinement, not merely in a separate interpreter. A separate interpreter is a different namespace; the claim this release needs is a smaller *privilege*. The first attempt built the former and was broken three ways by an adversarial review — a candidate that rewrote a pipeline module the parent imports after the build and had it executed in the process holding the frozen contract; the same through a bytecode cache entry that left the source byte-identical; and a detached grandchild that outlived the run's timeout and rewrote the final status afterwards. None of those needed an import, a race, or persistence.

The confinement must have these properties:

* read-only candidate inputs;
* read-only runtime dependencies;
* exactly one writable output directory;
* no write access to the repository;
* no write access to the project or its authority files;
* no write access to the virtual environment, package installation, user profile, startup locations, or parent temp directories;
* no network capability for an ordinary geometry build;
* no inherited writable handles;
* no access capable of modifying the parent process;
* rejection of symlinks, junctions, reparse points, alternate data streams, path aliases, and outputs outside the sandbox;
* parent-side hashing of all inputs before launch;
* parent-side re-reading, validation, hashing and promotion of outputs only after the entire confinement is dead;
* parent-only creation of receipts, assessment, status, and authoritative project state.

The candidate receives copies or read-only views of its source and build inputs. It never receives writable access to their authoritative originals.

The ruled design shape is:

1. the parent validates and freezes the proposal;
2. the parent constructs and retains the authoritative acceptance object;
3. the parent hashes every build input and stages copies of them into a sandbox;
4. a one-shot confined child process executes the candidate code;
5. the child receives only the build inputs it needs, as copies, and is not told where the project is;
6. the child writes geometry and a small build manifest into the one writable directory;
7. the parent waits for the confinement to report no live processes, then validates, hashes and promotes the produced artifacts;
8. the parent performs commissioning, screening, review binding, and final status in its clean interpreter.

The protocol is JSON and files, not pickle or shared Python objects. The child must not write authoritative receipts. `DIRECT` does not need a subprocess; the cost applies only to authored candidate execution.

Source-integrity hashing does not count toward this gate. It detects a compromise after the authority has already been exercised, and the bytecode-cache attack is the demonstration: the source stayed byte-identical. A narrow canary is worth keeping; the privilege claim must not depend on one.

Where a property cannot be reached by the ruled mechanism, it is recorded as a named limitation with the next-strongest mechanism identified, and the boundary is not weakened to make it pass. A boundary with one honestly-named gap is worth more than one with a quiet gap.

*Minimum common tolerance foundation*

The acceptance specification stops carrying bare numbers with an implied band.

Add, and no more than this:

* a lightweight explicit tolerance representation — nominal value with a unilateral, bilateral, or limit tolerance;
* the datum or measurement reference a value is taken from, where the value would otherwise be ambiguous;
* the measurement method, where interpretation would otherwise be ambiguous;
* provenance on the tolerance as well as on the value;
* a recorded separation between required finished-part geometry and any process compensation, so that compensation has somewhere to go later without rewriting a requirement.

The system continues to own the band. A designer states what the part must measure; the pipeline decides what band that magnitude is judged in. That property is the point of this release and the tolerance representation must not weaken it.

Compensation is separated in this release but not yet computed. A job with no compensation records none, and nothing about it changes.

**Explicit exclusions**

Do not yet attempt:

* full fitted authored work;
* full multi-source modification;
* strong preservation claims;
* universal anomaly screening for novel custom designs;
* divergent branch storage;
* automatic A/B concept generation;
* a second AI confirmation of the proposal;
* formal GD&T support of any kind — no profiles, no editions, no feature-control frames, no datum reference frames;
* material compensation values;
* per-body material assignment.

Proposal freezing is deterministic continuation of one design commission, not another dispatch.

**User-visible improvement**

A user can obtain:

* editable source;
* production geometry;
* measured requirements;
* a clear commissioned result;
* explicit remaining physical-test requirements;

for ordinary novel work using one design call.

**Proof**

Adversarial tests include:

* proposal declares 24 × 18 while implementation builds 10 × 8;
* implementation supplies an excessive tolerance;
* expectation changes after a failed result;
* model changes while an old proposal remains;
* proposal changes and correctly invalidates prior artifacts;
* candidate-measured volume is reused as expected volume;
* candidate profile data attempts to clear its own anomaly screen;
* a proposal supplies its own tolerance band and the pipeline's band still governs;
* a compensated dimension is measured against the compensated value rather than against the requirement;
* candidate code monkeypatches `AcceptanceSource.expectations`;
* candidate code monkeypatches commissioning tolerance functions;
* candidate code monkeypatches final-status logic;
* candidate code modifies its local copy of the acceptance object;
* none changes the parent's frozen contract, assessment behavior, or final result;
* unexpected child-written receipts are ignored or rejected;
* candidate code rewrites a pipeline module the parent imports after the build returns;
* candidate code poisons that module's bytecode cache, leaving the source byte-identical;
* candidate code rewrites this package's source for the next run;
* candidate code writes a `.pth` or `sitecustomize` into the virtual environment;
* candidate code spawns a detached process intended to outlive the run, and one that asks the kernel to leave the job outright;
* candidate code attempts a write out of the sandbox through a junction;
* candidate code rewrites its own source while it builds;
* every confinement property above is asserted by measurement rather than by inspection, and each named limitation is asserted still open, so that closing one is a visible change;
* `DIRECT` creates no process at all, proven with an audit hook rather than by replacing a module attribute, and its dispatch count and runtime remain unchanged.

The release passes only when candidate-controlled acceptance is structurally impossible, not merely rejected by one validator.

**Authentic exercise**

Use an open-ended FDM bracket request with:

* mounting requirements expressed as lightweight explicit tolerances;
* a keep-out;
* a build envelope;
* material and nozzle constraints;
* freedom over ribs, walls, and styling.

The bracket's fastener holes and mounting pitch are the test of whether the lightweight profile is expressive enough. If it is not, that is a finding for Release 7, not a reason to add formal tolerancing here.

Produce at least two geometrically different valid outputs in separate jobs to confirm that the system rewards requirements rather than resemblance. First-class shared branching arrives in the next release.

## Release 3 — Revision graph, branching, lifecycle, and context budgets

**Outcome**

The project can safely preserve divergent design alternatives, resume the correct branch, and reuse shared work without losing authority or increasing ordinary-job cost.

**Why this comes early**

Fitting, modification, combination, and motion all benefit from exploring competing concepts.

Adding branching after those capabilities would require retrofitting:

* artifact identity;
* invalidation;
* review bindings;
* acceptance revisions;
* physical outcomes;
* benchmark records.

**Scope**

*Revision graph*

Generalize the state model from an effectively linear history into a directed acyclic revision graph.

Support:

* ordinary single-parent revisions;
* sibling alternatives sharing a common ancestor;
* explicit alternative identity;
* stable parent relationships;
* alternative-specific proposals;
* alternative-specific implementations;
* alternative-specific artifacts;
* alternative-specific assessments;
* later explicit merges.

The user-facing system does not need to expose Git terminology.

*Alternative lifecycle*

Support alternative states such as:

* active;
* preferred;
* paused;
* rejected;
* superseded;
* retained as fallback;
* merged.

Changing the preferred alternative must not delete or overwrite previous alternatives.

*Binding-aware lifecycle*

Introduce or complete:

* run identities;
* job and alternative revisions;
* computed current status;
* stale-result invalidation;
* explicit resume versus restart;
* superseded next actions;
* structured malformed-project errors.

*Scoped decisions*

Allow decisions to apply to:

* the whole job;
* one alternative;
* one component;
* one interface;
* one manufacturing configuration.

An alternative-specific choice must not silently become a job-wide requirement.

*Dormant optional intent*

The authoritative model and its bindings must be able to carry, without any of it being required:

* tolerance-profile identity and edition;
* per-body and per-interface material identity;
* operation identities and their dependencies;
* alternative-specific manufacturing intent.

Nothing in this release populates these fields. Later releases do. Adding the capacity now is cheap; retrofitting it into artifact identity, invalidation, and review binding afterwards is not, which is the same argument that puts the revision graph here.

An absent field is absent, not defaulted. A job that names no tolerance profile is not silently assigned one, and its bindings do not include a profile identity.

*Scoped invalidation*

A change to any of the following invalidates its dependent results and nothing else:

* tolerance profile;
* material assignment;
* compensation assumptions;
* operation sequence.

Reassigning one body's material must not invalidate an assessment of an interface whose two sides are unchanged.

*Capability-based execution — moved to Release 10*

Compiling required work from declared capabilities rather than from a route name
now belongs to Release 10, whose outcome already names "route-specific
implementations replaced by capability composition" and "one planning authority".

The reason it moved is that the duplicate it was scoped to remove is not there.
`route.py` answers what evidence and review obligations a job carries;
`execution.py` answers what will be executed and what it may claim. That split
was *created* by [ADR 0002](docs/adr/0002-route-and-contract-authority.md) to
remove a real duplicate — the runner re-deriving the route, which once cost a
`RECONSTRUCT` job routing `FITTED` and executing `DIRECT` with no metrologist and
no verifier. After slices A–C there is one compiler and one consumer,
`ExecutionPlan.__post_init__` makes a self-contradicting plan unrepresentable,
and `dispatches_specification` is one compiled predicate that both the runner and
the CLI's review wiring read. This is one authority in two stages, and it works.

The cost of moving it is churn rather than seconds: planning is inside
`timings["intent"]` at roughly 1–2% of a certified run, while
`execution_plan_sha256` appears in 26 non-test lines across 8 production modules,
is bound into every review envelope and into run identity
([ADR 0004](docs/adr/0004-run-identity-is-content-derived.md)), 97 test
assertions name a route literal, and all four replay cases pin `route` and
`backend`. Release 1's proof list requires responses bound to "the relevant
execution-plan identity"; Release 2's requires `DIRECT`'s dispatch count and
runtime unchanged, which is a claim about a route by name.

Release 3 needs nothing from it: its exclusions already say route labels stay.

*Lazy assessment — struck, and not rescheduled*

There is no capability-triggered assessment registry in this roadmap any more,
and deliberately no release owns one.

The conditional half is **already deferred, through the right authority — the
contract.** Of eleven checks, six are unconditional and five exist only because a
feature was declared: a preservation row only with a declared edit scope, an
overhang row only with a self-support rule, `fit_acceptance` only with a mapped
interface — and `runner.run` refuses a contract carrying fewer preservation rows
than the plan names. The one genuinely expensive conditional assessment, the
preservation audit at about two seconds, is already triggered exactly that way.

The largest unconditional item is the broad anomaly screen, whose entire purpose
is to ask what no declared check asks. Putting it behind a trigger would defer
the one assessment that is *not* conditioned on a declaration, which is backwards.

And the seconds are somewhere else. Assessment is 62–64% of a certified run —
0.12 s of 0.19 s. The confined build boundary is 1.37–2.73 s per authored
invocation, and repeated builds are 2 of 3 on the `MODIFY` round trip and 3 of 6
on the branched job. Neither is an assessment, and a registry would not touch
either. That boundary figure is a *trimesh*-lane one and stands as measured; the
authored **build123d** lane has since moved, and the argument is unaffected
because it moved the right way. The lazy `build123d` facade cut a real bearing
candidate's confined build from a median 5.931 s to 4.299 s of wall
(`build_seconds` 4.910 s → 3.404 s), ranges not overlapping — so the term this
clause calls "somewhere else" is about 3.4 s rather than about 4.9 s and is still
an order above the assessment it is being compared with. The change point and the
arm-by-arm attribution are in [`docs/baseline.md`](docs/baseline.md) under
"Re-measured after the lazy `build123d` facade". `build_seconds` was **not**
redefined, so a figure recorded before that heading and one recorded after it are
both honest and are not comparable.

Building one now would **create** the duplicate planning authority Release 10 is
scoped to remove, over a set of assessments that mostly do not exist, to save a
fraction of 0.12 s. Section 3.7's rule covers what happens instead: the first
release that introduces an assessment costing more than the build boundary —
realistically Release 8's sweep engine or Release 4's comparative assessment —
builds the trigger then, and builds it *as* the contract rather than beside it.

*Context budget foundation*

Record and constrain:

* AI dispatch count;
* input context size;
* deterministic runtime;
* expensive imports;
* cache reuse;
* repeated work;
* incremental alternative cost.

Prepare task-specific context packages rather than loading all roles and project history by default.

A context working on one alternative receives:

* shared job intent;
* relevant ancestry;
* that alternative's differences;
* relevant evidence;
* sibling summaries only when comparison is needed.

**Explicit exclusions**

Do not yet:

* generate multiple concepts automatically;
* implement sophisticated alternative scoring;
* merge arbitrary geometry automatically;
* redesign every role or prompt;
* remove route labels;
* build a general distributed scheduler.

This release establishes safe branching and isolation. Rich alternative formulation and comparison follow in Release 4.

**User-visible improvement**

The user can:

* preserve a screw-fastened concept;
* branch into a snap-fit concept;
* continue developing either;
* switch the preferred concept;
* resume the correct branch;
* retain shared source analysis and requirements;
* avoid repeating unchanged work.

**Proof**

Fixtures include:

* two sibling alternatives sharing one proposal ancestor;
* alternative-specific proposal changes;
* one branch failure that does not invalidate its sibling;
* shared requirement change that invalidates both;
* branch-specific manufacturing change;
* paused and resumed alternative;
* switched preferred alternative;
* no artifact overwrite between siblings;
* review response bound to one branch only;
* explicit merge record with multiple parents;
* clean-clone reconstruction of the revision graph;
* a project declaring no tolerance profile, no per-body material, and no operations produces bindings identical to today's;
* a changed material assignment on one body invalidates only what depended on it.

**Authentic exercise**

Branch the bracket project into:

* a snap-fit formulation;
* an M3 screw formulation.

Confirm that:

* mandatory mounting requirements remain shared;
* fastening decisions remain branch-specific;
* source and printer context are reused;
* artifacts and assessments remain isolated;
* selecting one concept does not delete the other.

## Release 4 — Alternative formulation and comparative assessment

**Outcome**

The skill can intentionally generate, develop, compare, select, pause, and revisit materially different design concepts.

### Slice 1 — shipped, and what it changed about the release

`design-tool compare <project>` reads the receipts each formulation already
writes, emits `comparison.json` at the project root and a table, dispatches
nothing, builds nothing, and adds no project field. [ADR 0005](docs/adr/0005-a-comparison-refuses-rather-than-scores.md)
carries the decision and its reasoning; what follows is what the work *found*,
because two of the three findings were not in anybody's plan.

**The scoping document was judged, not adopted.** `docs/release-4-scope.md` was
written by one agent in one pass and never reviewed. Its citations were checked
one by one. Most held. Three did not survive as written, and they are recorded
because a reader of that document needs them:

* ~~its §4(C) material-use table — 47,526.263 mm³ against 49,792.874, the
  single most load-bearing number in the document and the whole of its §5
  argument — **exists nowhere in the repository.**~~ **Retired by slice 2, and
  the numbers were right.** The finding was accurate when written: `expected.json`
  recorded the volume detector's *result* and discarded its measurement, so
  nothing committed could reproduce the figure. Slice 2 freezes it, and a replay
  now produces 47526.263 against 49792.874 — the document's numbers to the
  digit. What was wrong was the repository, not the citation. The other two
  findings below stand;
* its claim that `cli.py:1754` "builds a table over *every* formulation" is
  false in a way that matters: the loop is over `project.alternatives` and
  `branch` never writes a row for the shared root, so `status` reports two
  formulations where `cost.compare` in the same report reports three. That is
  now `docs/defects.md` D26;
* it treats `docs/adr/0001`'s command list as an authority on the built surface.
  It is a code block, and it had already drifted: `branch` and `selftest`
  shipped in Release 3 without reaching it. Fixed, with a test that refuses the
  drift in future.

Its four re-scoping recommendations were **accepted**, three as written and one
enlarged; each is recorded inline above, at the bullet it changes.

**The measured case for building nothing was taken seriously and overruled.** An
independent reading found that 44 of about 46 frozen per-formulation fields are
identical across all three formulations of the recorded knob, that
`INCOMPARABLE_CHECK_SETS` cannot fire on any committed fixture, and that eleven
of the facts a comparison would print are already side by side in `status
--json`. Its conclusion — thirty lines in an existing loop, no verb — is right
about every fact and wrong about what they mean.

The 44-of-46 is not evidence that the formulations are equivalent. It is the
signature of self-grading. `docs/defects.md` **D25**: on the authored lane a
formulation's own proposal sets its declared feature set, the `expected_bbox_mm`
and `expected_bodies` its always-present checks are measured against, and —
through the declared magnitude — each feature's tolerance band. On the recorded
knob the root declares `bbox_mm.z = 50.0`, `plate-seated` declares `52.0`, and
**both are recorded `PASS` on `envelope`**. Printing those two verdicts adjacent
asserts an equality nobody measured, and the difference it conceals is the
entire point of the fork. So the first thing `compare` reports is
`INCOMPARABLE_EXPECTATIONS` — which, unlike `INCOMPARABLE_CHECK_SETS`, fires on
the authentic case with nothing constructed.

**`MODIFY` pairs are in, overruling the scoping.** It proposed comparing only
from-scratch formulations because two modifications both report
`EXPERIMENTAL_UNAVAILABLE` and discriminate nothing. Deferring the case that is
hard to answer is Release 6 in disguise. Settling nothing *is* the correct
output when the deciding axis cannot be measured, provided the comparison names
that axis and refuses preference on those grounds — so `not_compared` rows carry
`DECIDING` or `CONTEXT`, a `DECIDING` row makes `preference.admissible` false,
and a fixture asserts it. That turns a paragraph into a mechanism.

**Evidence.** 22 fixtures, all L0, none of which builds geometry — every
formulation is laid down as the receipts a run would have written, so the set
gates on a platform where the confined build boundary cannot run. 15 mutations
of the protections were attempted and 15 were caught. The gate is 894 passing at
`5c6ef9e` + this slice, up from 872, against a ceiling of 1050.

**Still owed by slice 1, and blocked rather than skipped.** Both needed a
Windows host, for the reason in §2. `pipeline/confine_posix.py` removed that
constraint; the first is done, the second is not:

* ~~the `compare` step appended to `benchmarks/replays/branch-knob-seat-fallback`
  and its output frozen in `expected.json`~~ — **shipped as slice 2, below**;
* ~~the two `design-tool branch --disposition` calls that prefer one formulation
  and retain the other as `FALLBACK`~~ — **shipped as slice 3, below.** Release 4
  owes nothing further.

### Slice 2 — the comparison meets a receipt a run actually wrote

`design-tool compare` now runs inside the L1 recording of
`branch-knob-seat-fallback`, after every formulation has settled, and what it
claims is frozen. So is the material measurement it is computed from.

**It did not survive first contact, and that is the finding.** The verb shipped
in slice 1 with twenty-two green L0 fixtures. Pointed at the recorded knob for
the first time it raised `AttributeError`: `screening.detectors` is a *list* and
`compare._measured` read it as a mapping keyed by detector name, so the material
axis could never have produced a number on any real job. Every fixture that
exercised the line had been authored against the reader rather than the writer,
so twenty-two of them agreed with each other and with nothing the pipeline
produces (`docs/defects.md` **D27**). Reverting the reader with the fixtures left
correct fails 21 of 25 — the measure of how much the fixtures were holding up
alone. The fix is one reader, `screening.detector`, beside the one writer, and
it raises rather than returning `None`, because a reader that shrugged would have
reported "no volume measured" forever.

The general lesson, and the reason this slice was worth its cost: **a fixture
written from a reader tests the reader against itself.** The tier that catches
this class is one that runs the verb against receipts a real pipeline wrote.

**What the recording now protects.** `material.volume_mm3` per formulation,
compared inside a band because it comes off a tessellator, plus `bbox_mm` —
which `measured.envelope` also carries, from a different writer, so the two
agreeing is itself worth freezing. And the comparison's *claims*: the mandatory
verdict, both verdicts per formulation, the compared set, `identical_designs`,
`same_requirement_digest`, `preference.admissible`, the standing of each
`not_compared` dimension the recorded job exercises, `ranking` and `score`
pinned as `null`, and the payload's whole top-level key set. The report's prose
is recorded by no key: a reworded explanation is not a regression.

Three of those came from the independent review of this slice, and each closed
something the slice had claimed and not delivered:

* **ADR 0005 was pinned by name, not by shape.** Adding `rank_order` and
  `overall_score` to the report left the entire gate green — 86 passed — so the
  guarantee covered two literal field names rather than the rule. `payload_keys`
  records `sorted(payload)` and is compared exactly, which is the anti-drift
  shape already built for ADR 0001's verb list. Re-measured after the fix: the
  same smuggled ranking now fails the recording.
* **`not_compared` was keyed on its own English.** Rewording a dimension's
  sentence turned the recording red — pinning the prose the harness had just
  said it does not pin. Each row now carries a `dimension_id`.
* **"the single reader" was false.** `tools/replay.py` still subscripted
  `screening["detectors"]` by hand, inside the very function `docs/defects.md`
  D27 said had been routed through the pipeline's reader. `screening.detectors`
  is that reader and `detector` is a lookup on top of it.

Two claims the review shortened. `material.volume_result` was deleted: it
duplicated `screening_detail.detectors.volume`, and recording a value twice does
not protect it twice. And of the five golden mutations reported, one — "the
2 mm envelope fork erased" — was exercising `measured.envelope`, which was
already frozen before this slice, so it demonstrated nothing new. The band it
was measured against is 0.5% + 1e-3, which for this part is 237.63 mm³ against a
2266.6 mm³ signal.

**A second defect, found by the same first contact and fixed since.**
`identical_designs` was empty on the knob, where the root and `as-drawn` are one
design under two ids — their receipts carry the same `artifact_hashes.source`
and every measured value agrees. It grouped on the digest *on disk now*, and the
fallback's model was revised after its run. **D28**, closed: the key is what the
completed receipts establish — source, candidate and STEP digests from
`final_status.json` — and not the working tree. The L1 assertion that pinned the
silence is inverted and the knob's recording moved by exactly that one field.
See `CHANGELOG.md` for why the defect's own proposal, grouping on the source
digest alone, was refused.

**Evidence.** Re-recording all four cases moved no value any of them held: 0
removed and 0 changed across the three unbranched cases, and on the branched one
38 additions and a single change — the root formulation's receipt list gained
`comparison.json`, which the verb writes at the project root, which is the root
formulation's work directory. It joins `project.json` and `brief.md`, already
listed there on the same footing. (`recorded_at` moves on every recording by
construction; it is provenance and nothing compares it.)

Mutations of the new golden, each caught: the frozen volume nudged 1%, a ranking
introduced, the rubric verdict softened to `COMPARABLE`, the shared root dropped
from the compared set. Then, after the review, a ranking smuggled in under names
ADR 0005 does not spell — also caught, which it was not before.

L1: 61 passed, 43 subtests, ~52 s. Heavy tier: 356 passed, 9 skipped, 183
subtests, 11 min 40 s.

`docs/defects.md` D26 is deliberately **not** fixed here for the same reason:
`status --json` is read by the replay harness, and changing a golden-feeding
command on a platform that cannot run the goldens is how a recording breaks.

**Not touched by this slice**, and recorded so it is not read as improved: 4.4's
"shared work is reused across alternatives — this clause now fails, measured".
Comparison shares nothing because it builds nothing, and `builds_avoided` stays
zero.

**Scope**

*Alternative formulation*

Allow the planner or user to request alternatives that differ in meaningful engineering choices, such as:

* snap-fit versus screws;
* magnetic versus mechanical retention;
* one-piece compliant versus multi-part pinned construction;
* rigid mount versus articulated mount;
* top-loading versus sliding enclosure;
* a single rigid part with a separate gasket versus one multi-material part;
* a part assembled from printed pieces versus one printed with an embedded insert.

Alternatives may therefore differ in tolerance strategy where the difference is legitimate, in materials, in inter-material interface strategy, in manufacturing sequence, in assembly sequence, and in serviceability — as well as in geometry.

An alternative may not differ in a mandatory requirement. A looser tolerance is a different alternative only when the requirement genuinely permits it; it is never a way to make a failing concept pass.

Each alternative records:

* why it exists;
* which assumptions differ;
* which intent remains shared;
* its proposal;
* its implementation;
* its artifacts;
* its assessments;
* its manufacturing implications.

*Bounded exploration policy*

Alternative generation is triggered only when:

* explicitly requested;
* materially different concepts are plausible;
* uncertainty makes comparison valuable;
* consequence justifies redundancy;
* the preferred concept fails.

The planner limits:

* AI calls per alternative;
* context duplication;
* repeated deterministic work.

**Re-scoped 2026-08-03, and three-quarters of it already shipped.** AI calls per
alternative and context duplication are measured per formulation and *capped per
invocation* by a ceiling the compiled plan declares (`cost.py:121`, frozen at
`cost.py:114`); repeated deterministic work is measured (`repeated_builds`). So
the honest statement of what this bullet asks for is **"exploration cost is
measured per formulation and bounded per invocation"**, and it is done. A cap on
the *number* of active alternatives is struck from Release 4 and moves to
whichever release builds a generator: nothing in this build generates a branch —
`design-tool branch` requires `--from`, `--id` and `--reason` and is refused
without them (`cli.py:2015`) — so a numeric cap here would limit how much a
person may type.

*Comparative assessment*

Compare alternatives across:

* mandatory requirement satisfaction;
* interface performance;
* manufacturing complexity;
* material use;
* expected print time;
* support burden;
* component count;
* assembly effort;
* adjustability;
* maintainability;
* uncertainty;
* physical evidence;
* user preference.

Where the alternatives differ in them, comparison also covers:

* tolerance strategy;
* materials and material count;
* inter-material interface strategy;
* manufacturing sequence complexity;
* assembly sequence complexity and required tooling;
* irreversible operations and what they foreclose;
* serviceability.

These are comparison dimensions when present, not mandatory scoring categories for every job. A single-material one-piece print is compared on the criteria it actually exercises.

Mandatory failures remain visible and cannot be hidden by weighted totals.

Comparison distinguishes:

* objective measurements;
* policy-derived estimates;
* engineering judgment;
* missing evidence;
* user preference.

*Alternative disposition*

Support explicit reasons for:

* preferred;
* paused;
* rejected;
* superseded;
* retained as fallback.

*Reuse and merge planning*

Allow a new alternative to declare that it reuses elements from earlier alternatives.

The system identifies:

* potentially reusable artifacts or subcomponents;
* assessments that remain valid;
* assessments invalidated by interaction changes;
* required reassessment after merging.

This release does not require automatic geometric merging.

**Explicit exclusions**

Do not:

* generate several alternatives for every job;
* treat cosmetic variants as independent engineering concepts by default;
* collapse comparison into one opaque score;
* automatically claim that merged successful features form a successful whole;
* keep unlimited active alternatives.

**User-visible improvement**

A user can request:

> Explore snap-fit and M3 screw versions, compare them, and retain both while we test the preferred one.

The system can execute that without flattening the work into one linear sequence.

**Proof**

Required tests include:

* materially different alternatives inherit the same mandatory intent;
* cosmetic-only variants are not automatically treated as concept branches
  — **vacuous today, kept and marked rather than implemented.** Nothing in this
  build generates a branch (`cli.py:2015`), so a cosmetic-variant classifier
  would guard a mechanism that does not exist and would second-guess a decision
  a person makes by typing `--reason`. It becomes real work in the same release
  that builds a generator, and not before;
* alternative-specific requirements remain scoped;
* ~~an alternative cannot loosen a shared mandatory tolerance to pass~~
  — **already structurally true; replaced by the proof that is not.** A proposal
  may not declare a tolerance *at all* (`acceptance.py:246`); every band is
  computed by the pipeline from the row's own magnitude and every frozen
  contract records `tolerance_owner: "pipeline"` (`acceptance.py:364`). The
  proof that was *not* true, and is now the first fixture of slice 1: **two
  formulations measured against different mandatory check sets are reported
  incomparable on those checks, not equal** (`docs/defects.md` D24). And its
  larger sibling, found while building the slice and live on the recorded knob:
  **two formulations measured against different expectations or bands for the
  same check are reported incomparable, not equal** (`docs/defects.md` D25);
* a comparison over single-material alternatives reports no material or sequence dimensions;
* mandatory failure cannot be outweighed by preference scoring;
* comparison reports unequal evidence;
* paused alternative incurs no ongoing execution cost;
* switching preference does not delete prior results;
* merged proposal preserves source-alternative provenance;
* affected assessments become stale after a merge.

**Authentic exercise**

~~Use the bracket alternatives from Release 3.~~ **Struck 2026-08-03: it names a
project that does not exist.** `benchmarks/fixtures/` holds `berlingo-knob`,
`component-cycle`, `oneplus-case-x2d-asa`, `oneplus-drawer-dropin`,
`pixel9-card-case` and `vent-ball-combine`. The bracket is a *proposed* exercise
at `:665` and `:904` that was never built; Release 3's branching was actually
exercised on `vent-ball-combine` and recorded on `berlingo-knob`. Its comparison
list also named four dimensions this build has no instrument for — hardware
requirements, assembly, adjustability, strength uncertainty — which
`ARCHITECTURE.md` 8.5 says must be distinguishable from measurements and which
this build can only ever carry as a stated row.

Use `benchmarks/replays/branch-knob-seat-fallback` instead. It is three
formulations of one job on a real vendored request, its fork is the request's
own recorded uncertainty rather than an invented preference — the base-plate
height is a photo estimate its notes give as ±2 mm — and its comparison has a
non-obvious answer that a score would destroy: every mandatory check passes on
all three, they are measured against *different envelope expectations*, and the
thing that actually decides is whether the mouth seats, which nobody has
measured.

Compare them on the dimensions this build has an instrument for:

**What the L1 tier does and does not cover, since the list below reads as
though it covers all of it.** `branch-knob-seat-fallback` is the only branched
replay case and its `source_mode` is `NEW`, so the only `not_compared` rows it
exercises are the three unconditional `CONTEXT` ones. The two `DECIDING` rows —
preservation of supplied geometry, and the assembly row — have L0 coverage only.
Gate 4.3 is met; the recorded evidence is narrower than the dimension list.

* mandatory check-set and expectation agreement (the rubric question);
* evidence completeness and inequality — derived status, staleness, screening
  calibration, whether anybody looked at an image;
* material use, as solid volume;
* support burden, against the print plan's own ceiling;
* component count and envelope;
* exploration cost per formulation, labelled as a fact about the process.

Everything else the old list named goes in `not_compared` with its owner.

Select one as preferred while retaining the other as fallback. **Still owed:**
the two `design-tool branch --disposition` calls that do it, and the `compare`
step in the replay recording. Both were blocked on a Windows host when this was
written; `pipeline/confine_posix.py` unblocked them, and §2 now records that the
L1 suite runs on Linux and reproduces its goldens. What is left is the work
itself.

### Slice 3 — somebody decides, and does not claim more than the comparison gave

Gate 4.5 asked for a real part whose alternatives somebody actually decided
between, and until now nothing in this repository had done it. The recorded knob
now ends the way a job ends: three formulations built and verified, `status`
deriving what each is still entitled to claim, `compare` saying what that
establishes, and then two `design-tool branch --disposition` calls —
`plate-seated` preferred on `USER_SELECTION`, `as-drawn` retained as `FALLBACK`
on `UNRESOLVED_EVIDENCE`.

**The basis is the slice.** Typing two commands is not the work; choosing a
basis that does not overstate is.

**And the first version of this paragraph got the mechanism wrong, which is the
more useful thing to record.** It said preference was inadmissible because the
three formulations are measured against different envelope expectations (D25),
and because the axis that would actually decide — whether the mouth seats on a
plate whose height is a photo estimate — cannot be measured. Both sentences
describe real properties of this job, and neither is why `compare` refuses.
`_preference` has three branches and returns on the first: **`as-drawn` has no
current verdict**, because its model is revised after the run that verified it,
so its mandatory verdict derives `UNKNOWN_STALE`. The rubric branch is never
reached. The third branch is gated on a `DECIDING` row, and this job has none —
all three `not_compared` rows are `CONTEXT`, so the build makes no claim that a
deciding axis is unmeasurable. Preference is inadmissible because one of the two
formulations being decided between cannot presently claim to have passed
anything.

The same wrong mechanism was asserted in the case's own notes and in an L1 test
docstring: three documents, one unchecked claim, and no recording that could
contradict any of them — because `_comparison_marks` froze `admissible: false`
and not the reason. It freezes `preference_because` now, so the three branches
are distinguishable and a change of reason moves a test.

**The two bases differ, because the two decisions do.** `plate-seated` is
preferred on `USER_SELECTION` — a person chose, on no measured ground, which is
exactly what happened. `as-drawn` is retained on `UNRESOLVED_EVIDENCE` — the
plate estimate may be wrong, and that is what a fallback is for. One basis on
both rows, which is what shipped first, answers "why keep a fallback" and
answers "why *this* one" not at all. What may not happen either way is a
decision claiming support the comparison refused to give, and
`STRONGER_CONCEPT` would have claimed exactly that.

Nothing in the build *enforces* that agreement. A refusal — `--basis
STRONGER_CONCEPT` rejected while `comparison.json` says preference is
inadmissible — is a real mechanism and is deliberately not built here, because
Release 4 asked for the decision and not for a new gate over it. It is a
candidate for whichever release next touches lifecycle.

**Fail-closed, against what the product allows.** `design-tool branch
--disposition` accepts a formulation that never concluded, and retaining an
unfinished alternative as a fallback is a legitimate thing to want. But the
adversarial fixture plays this same case with a sibling's review answer offered
to the fallback, and there the run stops and leaves no final status — so the
harness declines to take the declared decisions at all when any declared
formulation left none. A recorded preference formed over a job that stopped is
evidence of a decision nobody could have made. The recording says `ACTIVE` with
no basis, which is "nobody decided" rather than silence.

That check asks whether a run *concluded*, not whether its conclusion still
holds, and the distinction matters here: the retained fallback is `STALE` — its
model was revised after the run that verified it, which is what this case
exercises. Gating on `derived == stored` was the obvious repair and is the wrong
one, because retaining a stale concept as the fallback is what a fallback is
for. What was wrong was a docstring saying "concluded" where the code said "left
a file behind". The staleness is now recorded beside the decision and asserted
at L1, rather than left for a reader to discover.

**Two things the review found that the harness had not enforced**, both now
refused at load: a case that declares decisions and `concludes: REFUSED`, where
the decisions would be skipped on every play for ever while the recording
contradicted the case; and a decision naming a formulation the case never
declared, which used to load cleanly and die two verbs later with a message
about `project.json`. `SUCCESSOR_REQUIRED` is mirrored beside `BASIS_REQUIRED`
too — only one of the product's two requirements had been.

**Evidence.** Re-record: 0 removed and 0 changed on the three unbranched cases;
on the knob, additions plus the restructure named above, and no value moved that
was not meant to. (`recorded_at` moves on every recording by construction; it is
provenance and nothing compares it.) Mutations of the recorded decisions, all
caught: the preference switched to the other formulation, the basis upgraded to
`STRONGER_CONCEPT`, decisions that stopped being taken, the formulation the job
ends parked on. Mutations of the guards, all caught: the unfinished-job rule
removed (red at L0 *and* in the L1 adversarial fixture), and the basis dropped
from the command line.

The `dispositions` comparison itself had **no** mutation test when it shipped —
deleting it left L0 and L1 entirely green. It now has four, and deleting the
guard goes red in under a second.

**That closed a key and not the class, and a second review said so by
exploiting it**: adding a new uncompared top-level key to `observe` — an ordered
list of formulations, on every branched recording — left the whole suite green,
132 passed. `compare` walks a hand-maintained whitelist, so a key nobody adds to
it is a key nobody looks at. `observed_keys` freezes `sorted(payload)` and is
compared exactly, which is `payload_keys` one level up and the same argument: a
ranking must not be able to arrive under a name nobody thought to forbid. The
first version of that fix set it on the branched arm only, leaving three of the
four recordings uncovered by the guard written to close exactly that gap; it is
on both arms now.

**And the fix for the wrong-mechanism finding was itself wrong, in the way the
file warns about four lines above it.** Freezing `preference.because` froze a
230-character English sentence as a BINDING value — so improving that sentence's
grammar, with no behaviour change, turned the golden red with no defect behind
it. That is the pressure that trains somebody to re-record, and it is the
regression `_comparison_marks`' own docstring says it avoids, sitting directly
under the comment explaining that `not_compared` had already been fixed for it.
`compare._preference` carries a stable `reason` code now —
`NO_CURRENT_VERDICT` / `RUBRICS_DISAGREE` / `DECIDING_DIMENSION_UNMEASURED` —
and the recording freezes that. Measured after: the reworded sentence passes,
and a reason that changes branch still goes red.

Case schema 2 → 3, because a case declaring decisions and played by a reader
that did not know the key would look exactly like a case that declared none.

L0 970 passed, 557 subtests, 13 failed (the Windows-assumption set). L1 66
passed, 47 subtests. Heavy 357 passed, 183 subtests. Measured after the work,
not before it — the first version of this slice published the pre-slice L0 count
as its own evidence, which a review caught by subtracting the tests the slice
adds.

## Release 5 — Multi-source edit and combination model

**Outcome**

The skill can represent and execute genuine modification and combination jobs involving multiple source artifacts and alternative source strategies.

Delivered early slice: Multi-artifact edit declaration, validation, shared-interface references, planning, and preservation-row gating landed in response to the OnePlus case-and-drawer job. The remaining Release 5 work includes source-role generalization, selected assembly components, inheritance semantics, and candidate production suitable for per-artifact preservation assessment.

**Delivered slice: the datum declaration obligation ([ADR 0003](docs/adr/0003-datum-provenance-and-authority.md)).** A `Datum` is a declared row with an identity, a value, a unit, a provenance from the same closed set every other design-driving value uses, the artifact revision it was read on where it was read off geometry, and the scope it is valid in. `EditScope.datum_ids` references it, so two coordinated scopes name one identity instead of each holding a copy — which is decision 4, and the mechanism of the original failure rather than a style preference. A scope naming an undeclared datum is `REF_UNDECLARED`; two rows claiming one id is `REF_DUPLICATE`; a `valid_for` or a `derived_from.artifact_id` naming nothing the job declares is `REF_UNDECLARED`; a scope using a datum outside the scope it declares itself valid for is `INTENT_CONTRADICTION`, which is the stale reference moved one artifact sideways.

**The revision rule is three rules, and the first version collapsed them into one and got it backwards.** Required of `INHERITED`, which means read out of a supplied artifact and therefore always has a revision to name. *Permitted* of `MEASURED`, which covers both of §6.5's measuring classes — off supplied evidence, and off generated geometry — where the second has a revision and the first may not, because calipers on a physical part have none to invent. Refused of the rest, where claiming one is a provenance the value cannot support. Refusing it on `MEASURED`, which is what shipped first, inverted the incentive on precisely the class the ADR was written from: the incident's bad field was measured off the job's own drawer, so the honest row recording the revision was rejected while the vague one validated clean, and the only way to record the revision at all was to relabel the number `INHERITED`.

Assumptions are permitted and priced, per `ARCHITECTURE.md` 6.4. A number with **no recorded provenance** is the assumption the ADR names outright, and `CHOSEN` is the same thing with a label on it; neither is refused, both must name an owner and the check that would settle it, and `design-tool status` reports them. Not through `validate` — every caller there refuses the run on a non-empty findings list, warning severity included, and the ADR says plainly that a job whose datum has no provenance is not refused. The first version of this slice refused exactly that job while `cli.py` cited that sentence as its justification, so the code and its own comment disagreed and `status` managed to both refuse the job and hide the one thing the sentence is about. A measured or inherited number owes neither; it is already settled.

The scope is checked against what the job declares, and against everything the edit is inside — the artifact it edits and the interfaces it realizes. Comparing against the artifact alone, which is what shipped first, refused the coordinated case the ADR exists for: a datum scoped to the interface that two scopes both realize was out of scope for both of them.

**What this slice did not do, stated because the gap was load-bearing.** Decision 5 — datums join the 13.4 dependency-binding list — did not land *in this slice*. The acceptance contract bound *which* datum an edit was placed against, so re-placing an edit moved `contract_sha256` and the review answer written against the previous claim stopped being current. It did not bind the datum's **value**, so correcting 12.4 mm to 12.9 mm left the hash where it was. What made that safe was not that it was a small gap: it was that a job with an edit scope is capped at `EXPERIMENTAL_UNAVAILABLE` and cannot claim success at all, which is the ADR's own reason nothing had to stop. A datum is only ever referenced from an edit scope, so every job that can rest on one is capped — and that is asserted by a fixture rather than written down here, so the day the cap lifts the test goes red.

**Decision 5 has since closed**, as `docs/defects.md` D31: `_requirement_hash` now binds the canonical `Datum.as_dict()` of exactly the referenced datums, so correcting 12.4 mm to 12.9 mm cuts a new acceptance revision, refuses the stored review answer and invalidates the receipts that rested on it — measured end to end, not composed. The cap is unchanged and still asserted. **Decision 6 has since closed too**: nothing in the code grants a datum authority over measured evidence, which is the state decision 6 asks for, and that state is now *enforced* rather than merely held — `project.datum_conflicts` reports the disagreement with neither value winning and `status` withholds the claim that rested on it, mutation-proven six of six.

**Evidence.** 37 L0 fixtures, none of which builds geometry. 37 mutations of the protections were attempted and 37 were killed, including the `EXPERIMENTAL_UNAVAILABLE` cap the paragraph above rests on. One mutation survived the first sweep — `is_assumption` carried a `not self.derived_from` clause no test could distinguish from its absence, because a `CHOSEN` datum naming a revision is already refused elsewhere — and the redundant clause was deleted rather than given a fixture, on the grounds that a second copy of a rule is a second authority over one question. The gate is 1066 passing at this slice, up from 1014, against the 13 pre-existing Linux platform failures which are unmoved: HEAD was run in a separate worktree in the same session and fails the identical 13. L0-heavy is 357 passed and 9 skipped in 680 s, which is where `test_the_shipped_goldens_are_untouched` proves the five pinned certified contracts did not move for the new contract key — the absent-when-empty rule holding, measured rather than argued. L1 replay is 66 passed and 47 subtests in 55 s, unchanged.

**Delivered slice: D15 closed — the bed screen answered about a frame the job never declared.** Filed as "orientation is declared, validated, frozen, and read by nothing", the third instance of a field the schema takes seriously and no code consumes. Re-measuring made it something else: `model_to_printer_matrix` occurs in exactly four places, three shape checks and a selftest constant, and is applied to geometry nowhere — while `screening._bed_screen` decided whether the part reached below the bed from the lowest Z of the mesh *as authored*, with a signature of `(ctx)` that could not receive the contract even in principle. Measured before the fixture was written: a part authored at z 0..20, declared printed rotated to z −20..0, returned `bed-plane: CLEAR`.

That is not an unused field. It is a detector issuing a clean verdict about a frame the job did not declare it was working in, which `AGENTS.md` requires to fail closed immediately rather than wait for the capability that would make the claim true.

So the fix is a claim about the claim. `_bed_screen(ctx, contract)` transforms all eight corners of the model-frame box — a rotation does not keep the lowest corner lowest, so putting `bounds[0]` through the matrix would answer about a corner rather than a part — takes the minimum Z, and compares it against the declared `bed_z_mm`, which was ignored the same way. Every reason string names the frame it measured in. A matrix that cannot be applied is an anomaly, because falling back to the model frame is the defect with an extra step. The bound is conservative by construction: a transformed box bounds the transformed mesh, so it can read lower than the part goes and never higher, which turns an unlucky rotation into a look-again rather than a clean verdict.

15 L0 fixtures; 11 mutations attempted and 11 killed. Two survived the first sweep and one of them found a fail-open **in the fix itself**: `NaN` is a `float`, so a NaN `bed_z_mm` passed the type check, and `NaN > 0.05` is `False` — straight through to `CLEAR`. A type check standing in for a validity check, which is structurally the same error as the defect being closed, and it is not shipping only because the sweep forced a case nobody had thought of. The other was that four "unusable matrix" cases contained no well-shaped 4×4 with a bad *entry*, which is the one case a shape check alone misses.

**An independent review returned UNSAFE TO SHIP, and the sharper finding is that the fix opened a false-clean-verdict path of its own.** The eight-corner bound is conservative for an *affine* transform only. Under a projective matrix `w` is affine in the coordinates and can vanish inside the box while all eight corners sit far from zero, so the corner minimum reads **higher** than the part goes: measured, a corner bound of +0.5 mm against a true minimum near −49999 mm, returning `CLEAR` while naming the printer frame. That matrix passes `contract.preflight`, `cli._validate_orientation` and `project.validate`, all three of which check 4×4-of-finite-numbers and no more.

The fix was not a fourth shape check. `team_preflight.is_finite_rigid` already exists and is strictly stronger — finite, last row exactly `[0,0,0,1]`, orthonormal rotation, determinant +1 — so reusing it closes the hole and resolves the proportionality objection at the same time: what had been written here was the weakest of four authorities over one question, and it was the one deciding the verdict. The `weights` block it needed became dead code and went.

**What this did not close, and what closed it.** Three checks in `commission.py` read `ctx.bounds[0][2]` in the model frame — `seated`, `bed_contact` and `overhang` — and all three are *contract checks* that reach the commissioning verdict rather than screens that only escalate. On the case this slice's fixture tests, `commission` returned PASS while `screening` returned ANOMALY: one receipt, two contradictory answers, the stronger one wrong. `overhang` measured 0.0 mm² authored against 1293.3 mm² in the declared frame, on the `sections=64` cone the fixture actually builds — an earlier version of this line said 1294.4, which is the `sections=96` value and is the recurring citation defect at its smallest. Fixed at `5ac852e` and the follow-up its review demanded. What that review found still open was the overhang *ceiling*: `cli` computed it in the model frame while the candidate was measured in the declared one, so the two sides of one inequality sat in two frames. **That is closed too, and D15 with it** — the project's orientation now reaches the generated print plan, the plan rule's matrix travels into the contract feature row, `contract.preflight` refuses a run whose rule and orientation disagree, and inherited overhang is measured under `printer @ alignment`; five mutations, five caught, and `CHANGELOG.md` carries the account. Bridging and strength direction are orientation-dependent too and nothing measures them at all.

`screening`'s own siblings check out: `_profile_screen` compares model-frame Z against marks that are model-frame on both sides, so it is self-consistent and issues no verdict about an undeclared frame, and `_volume_screen` and `_component_screen` are invariant under any rigid transform.

**One citation corrected.** "It is never applied to geometry" dropped `docs/defects.md`'s *"anywhere in the pipeline"* qualifier, and the unqualified sentence is false: it is applied three times outside `pipeline/`, including a `_check_seated` that already takes exact transformed bounds against the declared bed height. That matters beyond pedantry — the correct implementation exists twice already, and the fix for the three checks above is to reach for it rather than write a third.

**Delivered slice: a body has a handle.** The commit before this recorded why "selected components within source assemblies" could not be built: `diagnose` reported `bodies` as a count and nothing per body, so a declaration selecting "the third body" would resolve to whatever `split` returned that run. Identity first, selection after.

`mesh_io.body_identities` returns one row per disconnected body — a `body_sha256` over the body's own geometry in canonical form, plus `bbox_mm`, `volume_mm3` and `faces` so a person choosing which body to keep does not have to re-open the file. Rows are ordered by handle rather than by split order, because two reads of one file must present the bodies in one order or "the first" is not a thing anybody can say. `_diagnose_mesh` reports them beside the count it already had, and `_diagnose_3mf` does too — per object, off the split it had already paid for to produce the count, so a body in a supplied assembly gets the same handle a loose mesh of that geometry gets. 3MF is the format Release 5's *"selected components within source assemblies"* is actually about, since it is the one carrying objects, components and build items.

**STEP is still a bare count, and the reason is measured rather than assumed.** `read_step` on the one STEP fixture in this repository takes **7.4 s**, so any fixture exercising a per-solid handle is heavy-tier by construction, not L0. And a B-rep solid has no triangles until something tessellates it: a digest over its tessellation is a handle over `BREP_READ_LINEAR_DEFLECTION` as much as over the shape — a different kind of identity wearing the same name, which is the class of claim this release keeps having to retract. It needs a slice that says what the handle is *of*.

**The canonicaliser moved rather than being rewritten.** `preservation._ordered` already made vertex and face order a function of geometry, for the same reason in a different job, so it is now `mesh_io.canonical_order` and preservation binds its old name to it. A second ordering rule would be two authorities over one question. The move carries a real hazard — `SAMPLE_PLAN_VERSION` is tied to the ordering and every review answer is bound to a plan digest — and the first version of this slice claimed L1 replay proved the move was pure. **It proves nothing of the kind.** A review reversed the face ordering outright and L0, L0-heavy and L1 replay all stayed green: `_seed_material` carries a *sentence* describing the ordering rather than the ordering, `tools/replay.py`'s `VOLATILE_KEYS` excludes the plan digest from comparison by design, and the one ordering-sensitive recorded number has a band of ±190 counts that an ordering change moves by 2. Only one replay case carries a preservation receipt at all, not four. So the hazard was real and the protection imaginary; the ordering is now pinned to a value in `test_body_identity.py`, which is the first golden that rule has ever had.

Two more findings from the same review, both on the handle itself: it was not a function of the shape. `-0.0` and `0.0` are equal by every numeric test and differ in `tobytes`, so one shape got two handles — reachable from an ordinary OBJ, since exporters write `v -0.0 -0.0 -0.0`. And the rounding was applied to the hash input but not to the sort key, so `canonical_order` lexsorted *unrounded* coordinates and noise of 1e-9 could flip a near-tie and permute the whole array before the rounding happened — with near-ties the normal case, since every axis-aligned box has four vertices sharing an x. Both are fixed by rounding and sign-normalising before canonicalising, inside `body_identities` only, so the ordering every frozen sample plan was built on is untouched.

14 L0 fixtures; 11 mutations attempted and 11 killed, including the ordering reversal that had survived every tier. Two further findings were cheap and worth naming: binding the moved function at module scope pulled `trimesh` in eagerly and took `import pipeline.preservation` from 0.075 s to 0.60 s — `commission` imports it to read one integer — so it delegates lazily and the test asserts identity of behaviour rather than of object, which is what had made the expensive import look required; and `diagnose` had already split the mesh one line above, so `body_identities` takes the split it was handed instead of repeating it. Three mutations survived the first sweep and each taught something different. The ordering mutation survived because the fixture's two boxes happened to split *in* digest order, making the rule untestable — the extents are now chosen so split order and digest order provably differ, verified rather than assumed. The topology mutation survived because two boxes differ in their points as well, so dropping faces from the digest changed nothing; the fixture is now two bodies with identical corners and different triangulation, which is what two exporters really produce. And the empty-mesh guard was deleted rather than fixtured: `split` already returns nothing for a mesh with no faces, so the guard was a second copy of a rule enforced elsewhere.

**Delivered slice: output-component inheritance.** This section asks for "output-component inheritance" and for imported intent to survive the edit, in unusually blunt terms: *"A job that prints in one material does not thereby erase the two materials its donor declared. Discarding imported multi-material intent is a defect, not a simplification — the intent is recorded even when this release cannot act on it."* `ARCHITECTURE.md` 6.8 says the same, and its own bullet list names *"output components that inherit from the source"*.

`Component` carried `component_id`, `role`, `count`, `material` and nothing else, so a two-source combination produced output bodies with no record of which donor each came from, and a donor that declared two materials was indistinguishable afterwards from one that declared none. The discard was not a decision anybody took — there was nowhere to write it down, so it happened by omission, which is precisely why the ROADMAP calls it a defect rather than a simplification.

A component now names `inherited_from` (a declared source artifact; one naming nothing declared is `REF_UNDECLARED`, because an inheritance nobody can resolve is none wearing the appearance of provenance) and `inherited_materials` (what the donor said, still readable after an edit that does not use it; a material list with no donor is `INTENT_CONTRADICTION` — inherited from *what?*). **This records and does not act**: `material` is still what the job will print, and a fixture asserts that carrying two inherited materials is not a claim to print two, because a weaker method may not issue a stronger claim.

The absent-when-empty rule is load-bearing here in a way it was not one slice earlier, and the difference is worth stating because the same sentence was wrong last time. `cli._requirement_hash` feeds `Component.as_dict()` straight into `S.payload_hash`, so an always-present key — even null — moves the requirement hash of every job declaring a component, and that hash is what the acceptance contract binds. `SourceArtifact.as_dict` reaches only `project.json`, which is deliberately unhashed. One serializer feeds a hash and the other does not, so the claim has to be checked per field rather than assumed from the shape — and here it is a fixture rather than a comment.

**An independent review returned UNSAFE TO SHIP, and the findings landed on the sentence above.** Three blocking, all of them the citation defect: `ARCHITECTURE.md` 6.11 was cited four times for a sentence that lives in 6.8 — 6.11 is "Manufacturing, assembly, and service operations" and does not contain the word "inherit", while 6.8's own bullets say *"output components that inherit from the source"*, so the right citation was also the better one. `cli._request_hash` was cited three times and does not exist; the function is `_requirement_hash`, and `project.py` names it correctly 330 lines further down in the same file. And the paragraph claiming *"here it is a fixture rather than a comment"* pointed at a fixture whose first assertion compared `sorted(plain.as_dict())` to the same expression again — a tautology — with its other two assertions duplicating the test above it. The review severed the link entirely, deleting `"components"` from `_requirement_hash`, and the whole gate stayed green: nothing guarded the claim. The claim itself is true, measured both ways, which is exactly why it needed a test that computes a hash rather than a sentence asserting one.

A fourth, non-blocking: `as_dict` tested truthiness where `problems` and `validate` tested `.strip()`, so `"   "` was emitted into `project.json` and into the requirement hash while both checks skipped it — a fail-open in the gap between two guards that disagreed about what empty means. `SourceArtifact.role` had inherited the same shape one slice earlier and is fixed with it.

`tools/test_documentation.py` now resolves `ARCHITECTURE.md <n>.<m>` citations against the document's own headings. It is a floor, not a ceiling — it cannot check that a section says what a comment claims, only that the section exists — and it was itself wrong first: the pattern required the literal `ARCHITECTURE.md` while most comments here write `ARCHITECTURE 6.8`, so a deliberately broken citation passed. It is verified by mutation now, which is the point.

11 L0 fixtures; 10 mutations attempted and 10 killed. One survived first: dropping the `.strip()` guard makes `artifact("")` return None, so every component in every recorded project — all of which inherit from nothing — would report `REF_UNDECLARED`. Every fixture that reached `validate` declared an inheritance, and the one that declared none never got there, which is the same gap shape the role slice's silence-stays-silence test closed.

**Delivered slice: source-artifact roles.** This section asks for "source-specific roles" and names five; `ARCHITECTURE.md` 6.2 names eight and calls them typical. Neither was implemented, so every supplied file was the same kind of thing: geometry this job may do as it likes with.

The fail-open, measured before the fixture was written, on a constructed case — no fixture here yet supplies a third-party mating object. A vent mount clips into a car's air vent; the vent is supplied so the mount can be fitted to it, and it is not ours to change. `Project.validate` on that job reported nothing at `edit_scopes[0].artifact_id`. That is not a tidy-declaration complaint — an edit scope compiles a preservation row, so the run would have gone on to measure *whether the car's vent survived our edit*: deterministic, reproducible, and about an object the job does not own. A receipt like that is worse than no receipt, because it reads as evidence.

Where that is measured matters, and the first version of this paragraph got it wrong: it quoted `EditScope(...).problems()`, which returns empty for this scope **after** the fix too, because a scope alone cannot know what it is editing. The defect was real and the sentence described a surface the fix does not touch — the same wrong-surface error recorded two slices above, repeated in the next slice written.

`SOURCE_ROLE` is 6.2's eight as a closed set, and `EDITABLE_ROLE` is the four whose geometry the job owns — base, donor, prior revision, alternative candidate. The other four exist to be read: what the part mates with, what it was measured against, the space it must fit inside, and a file already handed downstream. The role is **optional**, because every project recorded before the field existed declares none and requiring it would refuse all of them for a field they do not use; it is absent from `as_dict` when empty for the same reason. Silence stays silence — an artifact that declared no role is a question nobody asked, not permission granted. What the obligation buys is that a role *declared* is a role *kept*.

A second finding closed here is older than this slice: `source_artifacts` had no duplicate-id check where requirements, datums and edit scopes all have one, and `Project.artifact()` returns the first row matching an id. So declaring one file twice — first `BASE`, then `MATING_OBJECT` — let an edit scope over it validate clean, and swapping the two rows refused it. Whether the vent could be edited depended on declaration order. The new rule rests entirely on identity, so the identity check is part of it.

13 L0 fixtures; 8 mutations attempted and 8 killed. One survived first and the fix is worth recording: `test_every_architecture_role_is_accepted` iterated `SOURCE_ROLE` and asserted each member loads clean, which cannot fail — shrink the constant to three and the loop checks three, so a mutation dropping five roles survived. It now reads 6.2's bullet list out of `ARCHITECTURE.md` and asserts the constant equals it, in order: the anti-drift shape `test_documentation.py` already uses for ADR 0001's verb block, and the answer to two hand-written lists being two authorities over one vocabulary.

**Delivered slice: the region disposition obligation.** The other half of the pair above, and the same shape of defect. An `EditScope` carried three lists of region names and nothing compared them, so one name could be declared must-preserve, removable and added at once and `problems()` returned empty — measured before the fixture was written. All of those lists reach the frozen acceptance contract, so the review envelope carried a declaration saying a region must survive *and* that it may go, while the preservation audit read one list and a person read the note. Two authorities over one region, which is ADR 0003's two copies of one number with a different noun.

Every pair is now reported rather than the first, because fixing whichever collision a run happened to name would leave the job still contradicting itself and the next run would report the next pair — which reads as a new defect rather than the rest of the old one. `add` takes part in the comparison and is not one of the three dispositions: it says the geometry does not exist yet, so a name it shares with any disposition is a job claiming a region both does and does not exist.

`may_change` is a new field because the vocabulary is three-way and the fields were two-way: `preserve` is must-preserve and `may_remove` is consumed-by-intent, and permitted-change — this section's *"source-specific editable regions"* — had nowhere to go, so a job meaning "this may be reshaped but must not disappear" had to say either nothing or something false. It reaches the acceptance contract like its siblings and is absent when empty, so the five pinned certified contracts do not move. It goes through `_ids` where its two siblings do not, and that asymmetry is scope rather than risk: the two recorded MODIFY replays both write `preserve` and `may_remove` as proper lists, so tightening those would not break a recording — it would be a second change riding along in a slice about dispositions. A field being added now starts right; the other two are a one-line slice of their own. 15 L0 fixtures; 9 mutations attempted and 9 killed, one of which — the `as_dict` normalisation — first survived because a tuple and a list serialize identically, and was fixtured by asserting the type directly rather than deleted, since every sibling on the row normalises the same way.

**A second independent review, of the corrections themselves, returned SAFE TO SHIP with eight findings — and the most useful of them was about the evidence rather than the code.** Three mutations of the new datum protections survived the *whole gate*, the worst being deletion of `problems.extend(datum.problems(index))` — the single line wiring every row-level rule to a real `project.json`. Delete it and the gate stays green while `design-tool status` accepts a datum with no provenance, no value, no unit, no owner and no scope, because every one of those rules was only ever asserted by calling `Datum.problems()` directly. So "31 mutations, all killed" was a true sentence that measured the wrong surface; the sweep is 37 now and runs the invalid row through `Project.validate`. Two smaller ones: a test asserting only at `edit_scopes[N].datum_ids` stayed green while the refusal it should have caught *relocated* to `datums[0].valid_for`, and the component axis of the scope set had no fixture at all.

Also closed: a malformed `derived_from` was coerced to `None` and, on a `MEASURED` row where the revision is optional, validated clean — the same read-as-clean failure `_ids` exists to stop, on the field the ADR calls *"the field that failed"*. `_ids` itself validated the container and never its elements, so a nested list reached a set membership test and came out of `design-tool status` as an unhandled `TypeError`. `status` called an unrecorded number "a chosen number", collapsing the two cases decision 1 exists to keep apart. And one docstring presented a sentence as a verbatim ADR quotation that the ADR does not contain — the same failure to check a citation as the two blocking findings below, this time inventing the source rather than misreading it.

**One limit is now stated rather than implied.** `MEASURED` may name the revision it was read on, but `Project.validate` requires that artifact to be a declared *source* artifact, so a datum measured off geometry this job generated still cannot record its revision. That is the same incentive inversion one class over. It fails closed and a fixture asserts it, and closing it needs a build result to be an addressable artifact with a revision — Release 6.

**An independent review returned UNSAFE TO SHIP on the first version of the datum slice, and three of its eleven findings were blocking.** They are worth recording because two of them are the same class of error: *a comment that justified a rule the code did not implement.* The `MEASURED` revision rule cited a convention `Requirement` sets, and `Requirement` sets only half of it — it requires `artifact_id` on `INHERITED` and never refuses it elsewhere, so the harmful half of the rule had no precedent at all. `cli.py` cited the ADR's *"a job whose datum has no provenance is not refused"* as its reason for reporting assumptions through `status`, while `project.py` refused exactly that job. The third was a guard this file wrote and then bypassed: `valid_for` did not go through `_ids`, so a bare string became one scope per letter and a non-list crashed `design-tool status` with an unhandled `TypeError`, one line away from two fields that fail closed on the same input. Also found and fixed: an interface-scoped datum was out of scope for both of the scopes realizing it; the value and unit the construct exists to carry were unvalidated; `derived_from.artifact_id` — *"the field that failed"* — had no referential check while every neighbouring id reference had one; four protections survived mutation; and the duplicate-datum message claimed to detect two copies of one number when what it detects is an id collision.

**The commit-gate ceiling moved, deliberately.** `L0_COLLECTED_CEILING` refused this slice mid-way, at 1052 against 1050, which is the guard working. Raised to 1240 on the rule that set it originally — about 16% headroom over the 1066 the gate now holds — with the cost measured in one session so the machine's drift is common to every reading: 56.0 s at 1066 against 56.4 s at 1033 on the commit before this slice. The intermediate state measured 55.4 s and 56.4 s at 1052 — one commit, two readings, a full second apart and in the wrong direction. Thirty-three added fixtures are not measurable against that, which is the argument for counting tests rather than timing them.

**Scope**

Generalize the authoritative job model to support:

* zero, one, or many sources;
* source-specific roles;
* source-specific transforms;
* selected components within source assemblies — **blocked on identity, and the order matters.** `design-tool diagnose` reports `bodies` as a *count* and nothing per body: no name, no bbox, no volume, no stable handle. So a declaration selecting "the third body" would resolve to whatever trimesh's `split` or OCC's solid enumeration happened to return that run, which is a reference that means different geometry depending on something nobody declared — the failure [ADR 0003](docs/adr/0003-datum-provenance-and-authority.md) exists to stop, moved from datums to bodies. Selection must therefore follow a slice that gives a body an identity a receipt can carry, not precede it. Measured at `pipeline/diagnose.py` (`"bodies": int(len(components))` for meshes, `"bodies": len(solids)` for B-reps);
* source-specific preserved regions;
* source-specific removable regions;
* source-specific editable regions;
* added geometry;
* output-component inheritance;
* named regions, each carrying exactly one declared disposition — must-preserve, permitted-change, or consumed-by-intent;
* shared datums carrying provenance, the artifact revision they were derived from, and their validity scope.

The last two are declaration obligations, not measurement ones; Release 6 measures against them. A region with no disposition and a datum with no provenance are the two ways a job can arrive at Release 6 with nothing to judge it by. The datum requirement is [ADR 0003](docs/adr/0003-datum-provenance-and-authority.md): coordinated scopes name one datum identity rather than each holding a copy of the number, and a datum derived from an artifact before that artifact was edited is valid against the revision it was measured on and no later one.

Imported intent survives the edit. Multi-source edit intent preserves:

* per-source material identity;
* material assignments carried by an imported assembly;
* the donor's material role, where the donor contributes a distinct material;
* sequence obligations attached to inserts or embedded components in a source.

A job that prints in one material does not thereby erase the two materials its donor declared. Discarding imported multi-material intent is a defect, not a simplification — the intent is recorded even when this release cannot act on it.

Typical roles include:

* base;
* donor;
* external mating object;
* reference-only;
* previous revision.

Combination uses the same edit model as modification. It is not implemented as a second parallel concept.

The acceptance specification records every source obligation, even where the final comparison method is not yet strong enough to authorize success.

Alternatives may differ in:

* selected donor artifact;
* donor component;
* alignment;
* fastening strategy;
* retained geometry;
* output component structure.

**Explicit exclusions**

Do not yet promise:

* complete preservation verification;
* exact STEP preservation;
* all possible assembly-selection semantics;
* automatic inference of every edit region;
* automatic resolution of competing donor strategies.

The job may execute fully while reporting that preservation acceptance remains unavailable.

**User-visible improvement**

The user can formally express and run:

* retain the vent attachment from one source;
* retain the 17 mm ball from another;
* remove unwanted regions;
* align the sources;
* generate one combined result;
* preserve an alternative using a different donor or attachment strategy.

**Proof**

Fixtures cover:

* single-source modification;
* two-source combination;
* transformed donor;
* selected component from a source assembly;
* changed source hash;
* missing source;
* role mismatch;
* one preserved source and one intentionally consumed donor;
* a donor carrying two material assignments, both still readable after the edit;
* a source declaring an embedded insert, whose sequence obligation survives import;
* two alternatives using different donors;
* branch-local source change that does not invalidate the sibling;
* shared base-source change that invalidates both;
* two coordinated scopes referencing one shared datum, where changing that datum invalidates both and neither holds a private copy;
* a datum derived from a source revision the job then edits, which is refused against the later revision rather than silently reused.

No schema, acceptance compiler, or runtime API may assume exactly one source.

**Authentic exercise**

Run the real vent-mount plus ball combination through the ordinary command surface.

Optionally branch into:

* direct ball graft;
* reinforced intermediate neck.

Compare:

* source identities;
* source transforms;
* retained regions;
* removed regions;
* output component count;
* output gross dimensions;
* donor alignment;
* manufacturing implications.

## Release 6 — Deterministic geometric comparison and production modification

**Outcome**

Supported modification and combination jobs can reach honest successful outcomes based on reproducible source-specific evidence.

**Scope**

Three of the parts below — bounded repair, certified export, and per-region preservation — are separable slices with their own tests, their own replay, and their own authentic exercise. They are in one release because one real job needed all three at once, not because any of them has to wait for the others. Take them in the order real jobs need them, and do not hold the comparison core hostage to the slowest.

Build one shared deterministic comparison capability for:

* preservation;
* mating interfaces;
* alternative comparison;
* later motion contact;
* benchmark scoring.

The comparison core supports:

* canonical traversal;
* spatial indexing;
* transform-aware comparison;
* changed-cell detection;
* deterministic surface samples;
* bidirectional distance;
* region filtering;
* component correspondence;
* percentile and maximum deviations;
* cached source indices;
* stable serialization;
* surface-to-surface distance between two parts placed in their assembled transforms, filtered by region, reporting an interference count as well as a distance;
* residual material between geometry an edit added or removed and the nearest surface that edit must not break through;
* a declared resource bound on every query above, with a controlled failure instead of an allocation attempt.

The last three are one primitive applied to different inputs, not three capabilities. "How far is part A's surface from part B's, in this region" and "how much wall is left above this pocket" are the same query, and one real job needed both: the 0.300 mm residual left above its magnet pockets was the most consequential number it produced and nothing in the pipeline would have surfaced it, while the cross-part clearance it also needed sent trimesh's proximity path into a 20.5 GiB allocation attempt for 100k points against a 96k-face mesh. The job finished because an agent hand-rolled cropping and batching. The resource bound is therefore scope rather than optimization: an unbounded query is a check that fails as an out-of-memory kill rather than as a result.

It also gains the primitives needed to assess, where those things are declared:

* the tolerance zones the engine actually supports;
* lightweight limit tolerances;
* clearances between regions of different materials;
* the same geometry before and after compensation, without measuring one against the other;
* geometry in a specific operation-dependent assembly state.

The engine reports which tolerance constructs it can evaluate. A declared construct outside that set is reported as an unevaluated limitation, never as conformance, and never as an approximate band that happens to be checkable.

Preservation uses a staged method:

1. compare cheap structural facts;
2. locate spatially changed regions;
3. refine comparison only where required;
4. distinguish allowed changes from unexpected changes;
5. report the method and detection limit.

Every verdict is reported per named region, against that region's declared disposition, in both directions:

* **must-preserve** regions, where movement in either direction is a failure;
* **permitted-change** regions, judged against the band declared for them;
* **consumed-by-intent** regions, where the material's disappearance is the requested result and its absence is evidence that the edit happened;
* geometry added or removed outside every declared region, which fails whichever direction finds it.

A single whole-part verdict is issued only where a single whole-part obligation was declared. An unfiltered global maximum over a part carrying three dispositions measures the largest legitimate change, and reporting it as a preservation verdict fails correct parts: one real modification job's unfiltered global maximum was 1.797 mm, and it was a legitimate change — the job deliberately consumed material where its two parts now interpenetrate, in a band that opened to 2.88 mm by design. A two-verdict checker fails that part outright. It would be right about the number and wrong about the part.

Sampling density is derived from a declared minimum detectable defect size rather than a fixed count, and the verdict is named for what the method established — stage 5 of [ADR 0002](docs/adr/0002-route-and-contract-authority.md). The size to design against is small: the entire defect that same job's audit had to find was 85 faces of 93,530.

A datum a comparison rests on is one of its bindings. Changing a shared datum invalidates the comparisons that used it, in every coordinated scope that referenced it, per [ADR 0003](docs/adr/0003-datum-provenance-and-authority.md).

Exact B-rep claims are available only when an actual exact comparison backend exists.

Alternative comparisons may reuse common source indices and shared external-object analysis.

*Bounded repair*

A supplied artifact classified `REPAIR_REQUIRED` currently ends the job: diagnosis names the condition and nothing acts on it. `MISSION.md` requires repair and architecture section 11.4 specifies it, so this is the slice that implements it, bounded on purpose:

* repair is attempted only where diagnosis names a specific defect class, and only where the declared edit needs the geometry that defect affects;
* the repaired artifact is a new artifact with its own identity and an explicit relationship to the file it came from. The supplied file is never rewritten, for the reason `diagnose` already refuses to rewrite it — it is frequently the only authoritative copy;
* every repair is recorded: what was wrong, the method, the named region it changed, the geometry before and after, and whether that region was already permitted to change;
* an assessment resting on repaired geometry says so and says which region, per architecture sections 6.2 and 8.4;
* a defect the available methods cannot fix is reported as a limitation, never narrowed until it passes.

Repair also depends on diagnosis naming the right defect class, which is not free: a report that calls nine three-face edges and one four-face edge "boundary edges" points a repairer at hole-filling, which cannot work on any of them ([`docs/defects.md`](docs/defects.md) D1). **That prerequisite is now met** — `diagnose` reports `boundary_edges`, `nonmanifold_edges`, `max_faces_per_edge` and the full per-edge distribution, and raises a separate finding for the class hole-filling cannot touch — so this release inherits a diagnosis it can dispatch on rather than one it would have to re-derive.

*Certified export*

A preservation audit, a commissioning measurement and a final claim are all statements about an artifact, and an artifact is a file. The writer that produces it is a backend, and architecture section 12 already forbids a backend from silently changing topology interpretation or artifact identity. Nothing currently checks that it did not.

* every production write is re-read and re-measured before anything claims anything about it;
* the re-read compares classification, body count, per-part volumes and topology counts against the geometry that was written, and fails when they move;
* coordinate precision is part of the contract. A writer that formats coordinates loses geometry, and how much it lost is reported rather than assumed negligible;
* the check runs in the shipped frozen runtime. A self-check whose dependency is absent from that runtime has never run, and it must report that it was skipped rather than imply that it passed.

The evidence threshold in section 3.1 is met by two sibling jobs, not by one: both halves of the case-and-drawer commission independently hand-wrote the same float32-weld and file-versus-memory comparison, after a clean float64 solid came back from a binary STL write carrying 429 zero-area faces and 367 non-manifold edges.

**Explicit exclusions**

Do not:

* build a universal geometric-equivalence prover;
* increase sample density uniformly over every model;
* let sampled evidence claim exact preservation;
* treat geometric closeness as proof of equal function;
* claim conformance to a formal construct the engine cannot evaluate;
* compare a requirement against compensated manufacturing geometry;
* assume a sibling alternative's assessment applies to another;
* repair geometry the declared edit does not need, or present a repaired artifact as the supplied one;
* issue a preservation verdict for a region whose disposition was never declared;
* run an unbounded proximity query and let the process die in place of failing the check;
* compare an in-memory mesh when the claim is about the file that was written.

**User-visible improvement**

Users can modify and combine supported STEP, STL, and 3MF sources while receiving reproducible evidence about unintended changes.

Supported modification and combination jobs may regain successful final claims.

**Proof**

Fixtures include:

* identical meshes with different vertex order;
* rigidly transformed equivalents;
* equivalent remeshing;
* small undeclared addition outside edit scope;
* permitted addition inside edit scope;
* removed source feature;
* thin feature;
* changed component structure;
* multi-source preservation;
* two alternatives sharing unchanged source geometry;
* one branch-specific edit that leaves sibling evidence valid;
* merged geometry requiring reassessment;
* a part whose largest legitimate change is larger than its largest illegitimate one;
* a consumed-by-intent region whose material is *not* gone, which fails;
* a source carrying three-face and four-face edges, repaired inside a declared region and refused outside it;
* an export whose write welds vertices, caught by re-reading the file rather than the memory it came from;
* a two-part clearance query whose unbounded form would exhaust memory, which fails as a check.

The result must state:

* comparison method;
* tolerance;
* detection limit;
* unsupported conditions;
* source-specific verdicts;
* per-region verdicts and the disposition each was judged against;
* any repair the result rests on, and the region it changed;
* alternative identity.

**Authentic exercise**

Produce fresh vent-mount alternatives from the authentic request and sources.

Compare each against:

* source-preservation obligations;
* donor alignment;
* 17 mm functional geometry;
* manufacturing intent;
* the physically proven historical result where informative.

Historical physical proof remains separate from proof of a new candidate.

Run the case-and-drawer magnetic-retention modification as the second authentic exercise, because it is the job that produced most of this release's scope and it exercises what the vent mount does not: two coordinated edit scopes, a shared datum, three region dispositions in one part, a repair-blocked source, a cross-part clearance query large enough to matter, and a residual wall — 0.300 mm above the magnet pockets — that decides whether the part is usable at all.

## Release 7 — Real-object fitting

**Outcome**

The skill can design parts that fit existing real objects using clean CAD, published dimensions, measurements, photographs, or combinations of evidence.

**Dependencies**

Requires Releases 2, 3, and 6.

It may be exchanged in order with Release 8 after those common dependencies are complete. Fitting is recommended first because it covers more frequent use cases and has stronger existing fixtures.

**Scope**

*Independent mating-object model*

Represent the external object independently from the candidate.

The mating object may come from:

* trusted CAD;
* published dimensions;
* structured primitive geometry;
* measured datums;
* a visual envelope;
* reconstructed surfaces.

The mating-object model is shared across alternatives unless an alternative explicitly uses a different evidence interpretation.

*Interface model*

Support interface classes such as:

* clearance;
* sliding;
* interference;
* compliant;
* snap;
* retained;
* seated.

An interface may define:

* mating regions;
* seated transform;
* fit band;
* insertion direction;
* intended contact;
* forbidden contact;
* retention;
* critical dimensions.

*Tolerance and fit semantics*

The lightweight tolerance and fit profile from Release 2 becomes the default for fitted work, and gains what fitting actually needs:

* explicit datums, so a measurement and the dimension it feeds name the same reference;
* measurement semantics — what was measured, how, and against which face or feature;
* interface-specific tolerance bands, so a press fit and a clearance hole on the same part are not judged in one band.

Formal tolerance-profile support is added here only for jobs that supply or require it: a declared profile family, a declared edition, and the specific constructs the implementation can evaluate. A supplied formal tolerance is either evaluated under its own profile or reported as unsupported. It is never reinterpreted as a lightweight band, and ASME and ISO semantics are never mixed in one declaration.

The fitted fixtures are the evidence for how far this needs to go. Determine whether the lightweight model was sufficient for the Pixel case, the Berlingo knob, and the lighter fitted cases before expanding formal support. Recurring real ambiguity that the lightweight profile cannot express is the only justification for adding a construct.

*Evidence reconciliation*

Support:

* photos;
* caliper readings;
* published specifications;
* conflicting values;
* confidence;
* corrected measurements;
* physical-fit feedback.

Different interpretations may become explicit evidence alternatives when the ambiguity cannot yet be resolved.

*Interface assessment*

Prefer:

* satisfaction of declared fit bands;
* comparison relative to the shared external object;
* insertion and seating feasibility;
* retention;
* critical dimensions.

Do not score whole-part resemblance when non-interface geometry is unconstrained.

*Fitted concept alternatives*

Support alternatives such as:

* rigid cradle versus compliant cradle;
* snap retention versus friction retention;
* open frame versus full case;
* single-piece versus multi-piece construction.

They share the external object and mandatory interface constraints.

**Explicit exclusions**

Do not:

* require a full scanned object when published dimensions and analytic geometry are sufficient;
* require a dedicated metrology agent for every fitted job;
* treat a third-party reference design as the only valid shape;
* hide unresolved measurement conflicts by averaging them silently;
* require a formal tolerance profile for a job that supplied none;
* implement formal constructs no fixture has needed;
* generate many fitted alternatives without user or planning justification.

**Primary fixtures**

*Pixel 7 case*

* published Pixel 7 dimensions as geometric truth;
* authentic photos and request;
* downloaded working case as private interface reference;
* scraped phone mesh used only as a visual envelope.

*Berlingo gear knob*

* authentic caliper measurements;
* documented measurement correction;
* physical jam feedback;
* design-stage reference status.

*Garmin dock and D30 broom holder*

* lighter fitted regression cases;
* variant-selection coverage.

**User-visible improvement**

Users can request cases, docks, knobs, adapters, holders, clips, and replacement parts that are assessed against the object they must fit.

They may also compare materially different retention or construction strategies without duplicating the mating-object reconstruction.

**Authentic exercise**

Perform:

* one live blind Pixel 7 case design;
* optionally two retention alternatives;
* one Berlingo correction iteration.

After review, capture the results as L1 replay fixtures.

## Release 8 — Multi-part and moving assemblies

**Outcome**

The skill can represent, build, branch, and assess assemblies whose correctness depends on relationships and motion between components.

**Dependencies**

Requires Releases 3, 5, and 6.

It may follow or precede Release 7 after those dependencies, based on actual project priority.

**Scope**

*Assembly representation*

Support:

* component identities;
* parent assemblies;
* local transforms;
* fixed and moving components;
* material and print assignments;
* meaningful assembly states.

Component identity remains stable across alternatives where the same physical concept remains.

*Three kinds of movement*

Separate what has until now been one concept:

* **operating motion** — how the finished product moves in use;
* **assembly motion** — the path a component travels while the product is built;
* **disassembly or service motion** — the path a component travels while being accessed, adjusted, replaced, or removed.

They are assessed against different requirements. A drawer that must slide through 40 mm of travel forever and a lid that must clear a boss once during assembly are not the same obligation, and a part can satisfy one while failing the other.

Assembly and service motion are evaluated in the assembly state the operation model establishes. This is where the operation identities carried dormant since Release 3 first do work.

Support:

* sequence-aware collision checks, evaluated in the state the sequence produces rather than only in the finished state;
* insertion accessibility for tools, hands, and the component itself;
* required intermediate poses;
* prerequisite components that must already be present;
* the resulting assembly state of each operation;
* irreversible operations, and which later assembly options they remove.

*Motion representation*

Initially support:

* prismatic motion;
* revolute motion;
* threaded or helical motion where practical;
* discrete assembly and operating poses.

Each motion defines:

* participating components;
* permitted degrees of freedom;
* travel;
* starting and terminal poses;
* intended contact;
* forbidden interference;
* stops;
* retention;
* assembly and disassembly path.

*Motion assessment*

Evaluate:

* full declared travel;
* static fit;
* dynamic clearance;
* intended friction or contact;
* collisions;
* stops;
* retention;
* assembly feasibility.

Use deterministic pose sampling and bind results to:

* geometry;
* motion definition;
* alternative identity;
* tool and sampling version.

*Mechanism alternatives*

Support alternatives such as:

* sliding drawer versus hinged lid;
* snap stop versus screw stop;
* printed hinge versus metal pin;
* one-piece compliant mechanism versus multi-part assembly.

Comparative assessment distinguishes:

* mandatory motion success;
* manufacturing complexity;
* component count;
* assembly burden;
* physical uncertainty.

**Explicit exclusions**

Do not:

* build a general rigid-body physics simulator;
* infer mechanism intent merely from separate bodies;
* claim friction performance from geometry alone;
* require an operation sequence for an assembly whose parts go together in any order;
* treat an assembly path as evidence about operating motion, or the reverse;
* reuse motion results across geometrically different alternatives without reassessment.

**Primary fixture**

Use the Pixel 9 Pro XL sliding drawer case:

* case shell;
* sliding drawer;
* two buttons;
* four watertight meshes;
* declared prismatic drawer motion;
* tight friction-fit intent;
* working third-party reference;
* phone envelope derived from published dimensions.

**User-visible improvement**

Users can design and assess:

* drawers;
* sliders;
* hinges;
* clamps;
* threaded mechanisms;
* retained multi-part devices.

They can preserve competing mechanism concepts and return to a fallback after physical testing.

**Authentic exercise**

Run:

1. an L1 reference replay;
2. a live blind sliding-case design or adaptation;
3. an intentionally defective variant with a mid-travel jam;
4. optionally a second mechanism alternative if it is genuinely plausible.

## Release 9 — Unified manufacturing, physical feedback, and alternative selection

**Outcome**

All supported design types produce consistent FDM deliverables, and real print outcomes can change the preferred alternative without erasing previous work.

**Continuous requirement**

Basic FDM awareness is required in every earlier release.

This release unifies and hardens the behavior rather than postponing manufacturing until the end.

**Scope**

*Manufacturing model*

Support per-job, per-alternative, per-component, per-body, per-region, per-interface, and per-feature intent for:

* printer;
* material;
* process;
* nozzle;
* build envelope;
* orientation;
* support, including soluble and breakaway support material;
* strength direction;
* minimum features;
* fit compensation;
* surface priority;
* print order;
* assembly order;
* coupons.

An assignment inherits from its enclosing scope. A single-material job still states its material once.

*Vertical slices*

The multi-material and sequencing work lands here, as slices rather than as a subsystem:

* per-body and per-region material assignment;
* inter-material interface intent;
* multi-material print preparation;
* rigid plus flexible components in one product;
* soluble and breakaway support interfaces;
* print pauses and embedded inserts;
* separately printed materials joined after printing;
* post-processing operations;
* operation-plan execution and resumption;
* calibrated differential compensation;
* calibration-scope tracking;
* coupons where calibration is unavailable;
* physical outcomes bound to material, orientation, process, and operation history.

Take them in the order real jobs need them. Each is a slice with its own L0 tests, its own replay, and its own authentic exercise; none of them is a prerequisite for a single-material job to run exactly as it does today.

*Compensation and calibration*

Compensation becomes computable, and stays bounded by what was actually measured.

* a compensation value derives from a calibration or is recorded as provisional;
* a calibration records the printer, material brand and formulation, nozzle, orientation, slicer settings, and process conditions it was taken under;
* applying it outside that scope is refused, not extrapolated;
* required finished geometry is never rewritten — compensation produces manufacturing geometry beside it;
* where no relevant calibration exists, the interface keeps its requirement, the allowance is recorded as an assumption, and a coupon or physical test is required before the fit can be claimed.

*Manufacturing assessment*

Evaluate, where supported:

* build envelope;
* topology;
* minimum thickness;
* holes and gaps;
* bridging and overhang implications;
* support regions;
* orientation-sensitive strength;
* material and nozzle mapping;
* component separation;
* inter-material interface clearances and their compensation basis;
* feasibility and accessibility of each declared operation;
* assembly sequence.

*Packaging*

Produce consistent:

* editable source;
* neutral CAD where supported;
* production meshes;
* generic 3MF;
* multi-material packages carrying per-body material identity;
* selected slicer-specific packages;
* print notes;
* the operation plan, where one exists;
* assembly notes;
* required coupons and physical tests.

Generated structured files must be independently re-imported and checked, and a re-import must recover the material assignments the writer put in.

`design-tool package` is the verb ADR 0001 promised and nothing implements. It lays parts out, emits spec-clean OPC, writes vertices at round-trip precision, and applies the certified-export rule from Release 6 to its own output: it feeds what it wrote back through `diagnose` and fails when the classification, the body count or any per-part volume has moved. A packager that cannot verify its own output is a writer with a claim attached, and the current one is worse than that — it formats vertices with `%.6g`, moving them by up to 0.0005 mm and changing a part's volume in the second decimal, and its round-trip self-check has never executed in the shipped runtime ([`docs/defects.md`](docs/defects.md) D2, D3).

*Physical outcome model*

Record outcomes such as:

* not printed;
* print failed;
* printed;
* fit too tight;
* fit too loose;
* fit passed;
* motion jammed;
* motion passed;
* retention failed;
* coupon printed and measured;
* insert seated or failed to seat;
* support released cleanly or damaged the part;
* bond or weld held or failed;
* load tested;
* user-confirmed working.

Bind the outcome to:

* artifact identity;
* job revision;
* alternative identity;
* printer;
* material;
* process;
* nozzle;
* orientation;
* relevant slicing conditions;
* the operation history that produced the tested object;
* tested external object.

An outcome missing any of these cannot later be reused as calibration.

*Feedback-driven branching*

Physical feedback may:

* revise the current alternative;
* create a correction branch;
* restore a previously paused alternative;
* change the preferred alternative;
* motivate a merge of successful features.

The original failed artifact and outcome remain preserved.

*Comparative physical evidence*

Alternative comparison incorporates physical outcomes without flattening them into software scores.

Examples:

* one concept is easier to print but fails retention;
* another uses more material but passes fit testing;
* a third remains untested and therefore has incomplete evidence.

**Explicit exclusions**

Do not:

* infer universal printer compensation from one successful part;
* transfer a calibration across printers, material formulations, nozzles, orientations, or slicer settings;
* invent a shrinkage coefficient to fill a gap in the data;
* collapse physical outcomes into software status;
* automatically declare one alternative universally superior;
* require large private project files in the main repository;
* delete failed or non-preferred alternatives that still have learning value.

**User-visible improvement**

The skill can respond coherently to:

* "this printed and works";
* "the hole is too tight";
* "the drawer jams halfway";
* "the clip broke along the layers";
* "the TPU gasket does not seal";
* "the magnet dropped out of its pocket";
* "go back to the screw version";
* "combine the snap geometry from option A with the reinforced body from option B."

**Authentic exercise**

Prepare and, where practical, test packages for:

* the vent mount;
* the Pixel 7 case;
* the Pixel 9 sliding assembly;
* a simple deterministic bracket;
* at least one pair of retained alternatives.

Record the physically proven vent mount and Berlingo failure without flattening their different evidence classes.

For the multi-material and sequencing slices, cover a small representative set rather than every combination:

* a rigid body with a TPU gasket or other compliant component;
* a soluble or breakaway support interface;
* an embedded magnet, nut, or heat-set insert loaded during a print pause;
* two separately printed materials joined with a controlled fit.

Do not run all four if a later one teaches nothing the earlier ones did not. Choose the smallest set that covers the distinct semantics — a compliant interface, a sacrificial interface, a paused-insert operation, and a cross-material clearance — and record which semantics each one actually exercised.

## Release 10 — Simplification, interchangeability, and stable product

**Outcome**

The repository becomes one coherent product rather than a collection of migration layers.

**Scope**

*Simplification*

Remove:

* deprecated project formats;
* deprecated command paths;
* duplicate planning authorities;
* route-specific implementations replaced by capability composition;
* dead schemas;
* obsolete adapters;
* duplicated role instructions;
* transitional status formats;
* linear-history assumptions superseded by the revision graph.

Retain compatibility only where it still serves active users and has a defined removal date.

*Capability interfaces*

Define stable boundaries for replaceable:

* AI providers;
* judgment contexts;
* CAD kernels;
* mesh engines;
* importers;
* renderers;
* motion solvers;
* slicers;
* storage;
* benchmark scorers.

Each implementation reports:

* supported capabilities;
* version identity;
* determinism;
* unit and tolerance behavior;
* which tolerance profiles and constructs it can evaluate;
* which manufacturing processes and materials it can prepare;
* resource expectations;
* limitations.

Fallback must be explicit and may not silently weaken claim strength. There is no silent fallback for a material, a process, a compensation value, a standards profile, or a tolerance construct.

*Revision-storage conformance*

Any supported storage implementation must preserve:

* immutable history;
* shared ancestry;
* sibling alternatives;
* alternative-specific artifacts;
* explicit merges;
* dependency-aware invalidation;
* preferred and paused dispositions.

*Documentation alignment*

Align:

* `README.md`;
* `SKILL.md`;
* `ARCHITECTURE.md`;
* `ROADMAP.md`;
* ADRs;
* CLI help;
* schemas;
* examples;
* current benchmark documentation.

*Release qualification*

Run:

* full deterministic suite;
* full L1 replay suite;
* bounded L2 blind suite;
* alternative-exploration fixtures;
* clean-clone install;
* packaged-skill install;
* cross-platform path tests;
* performance baselines;
* selected real physical workflows.

Qualify, and publish the result:

* the documented list of supported tolerance profiles and editions;
* a conformance fixture for every supported formal tolerance construct;
* explicit limitation or rejection of every unsupported construct, demonstrated by a fixture that declares one;
* validated operation-plan serialization and resumption;
* independent re-import of multi-material packages by something other than the writer;
* no silent material, process, compensation, standard, or tolerance fallback anywhere in the product;
* backend conformance for the tolerance and operation semantics each backend claims.

**User-visible improvement**

The skill has:

* one supported job model;
* one command surface;
* one planning authority;
* one result model;
* first-class alternative exploration;
* clear capability limits;
* replaceable providers and backends;
* documentation that matches reality.

**Exit criteria**

The full architectural vision is reached when all major mission use cases work through the same coherent product and no known architecture-level limitation is hidden behind a successful claim.

## 5. Continuous tracks

These are active throughout all releases.

### 5.1 Benchmark ladder

**L0 — component fixtures**

Run on every commit: `uv run pytest`, about a minute on this machine, and green
on Linux with no expected-failure list -- measured on the hosted runner for
Python 3.11 and 3.12, not only locally. The parsing rules it used to fail on are
covered for both path flavours from either host; what has not been re-measured
in this slice is a *Windows run*, where the last recorded one had two
environmental failures of its own (a machine-speed tier-guard timeout and a
mesh-library edge count), and neither is a platform assumption in the tests. The count moves with
every slice and is reported in each commit rather than here; what is *enforced*
is `L0_COLLECTED_CEILING` in `conftest.py`, currently 1440, because a ceiling a
slow machine cannot move is the only regression control that means anything.

Which tier a test is collected in is structural. `testpaths` in `pyproject.toml`
names `skills/3d-modeling/scripts` and `tools`; `benchmarks/heavy` and
`benchmarks/replays` are in neither, so a bare run cannot collect either of them.
Whether a test *belongs* where it sits is measured rather than declared: the
repository-root `conftest.py` fails any L0 test that starts a child process
(`git` excepted, at ~45 ms a call) or that exceeds a five-second per-test
ceiling, and names `benchmarks/heavy/` in the failure. `tools/test_tiers.py` and
`benchmarks/heavy/test_tiers_heavy.py` are the guard's own pair — the decision as
a function, and the decision shown red in a real session.

Protect:

* parsing;
* transforms;
* planning;
* acceptance authority;
* state invalidation;
* branch isolation;
* alternative inheritance;
* context isolation;
* deterministic comparison;
* tolerance semantics and unsupported-construct reporting;
* separation of requirement from compensation;
* material assignment inheritance and scoped invalidation;
* operation dependencies and resulting states;
* serialization.

**L0-heavy — the component fixtures that cost a process**

Run on pull requests and before merge, on the same trigger as L1:
`uv run pytest benchmarks/heavy`. Four runs of this tier in one session took 11 m 40 s, 13 m 21 s, 15 m 39 s and 17 m 19 s on the same commit range, so the honest figure is a band of roughly 12-17 minutes rather than a number -- wall clock on this hardware drifts by about 1.8x within a session, which is why the enforceable budget is a collected-test ceiling and not a duration. The counts move with every slice and are reported per commit. This is also the tier that needs the confined boundary, so it is the one the authoritative pre-merge job runs in a container that can actually build one; a run that could not is a run that measured nothing.

Not a fourth rung. It is the part of L0 that cannot be paid on every commit — the
two command surfaces, the confined build boundary, the packaging and bundle
smokes, the screening corpus, the B-rep reads — cut out of the gate for a cost
reason and not a coverage one, which is why it runs on a trigger rather than on
none. `benchmarks/heavy/README.md` carries the profile that decided the seam. The
counts are conserved: 820 of the 1163 tests that were in the gate stayed, 343
moved, and nothing was deleted or weakened to make either number.

**L1 — replay**

Run on pull requests and before merge.

Built. `tools/replay.py` is the harness and `benchmarks/replays/` holds the
cases; each case records the job's inputs, the designer's proposal and model, and
the reviewer's judgement with no envelope on it, so the harness stamps the
envelope of the packet the current run issued and a recorded answer survives a
protocol bump instead of being refused by one. A case may declare several
formulations, in which case the harness reaches each through `design-tool branch`
and reads what each one's receipts currently support by calling `status.report` --
the same assembly `design-tool status` renders, called directly rather than read
back out of what that command printed. Four of the list below are covered today — original design, modification,
alternative *formulation* (siblings isolated on disk and in the review
bindings), and, since Release 4 slice 2, alternative *comparison*: the branched
case runs `design-tool compare` after every formulation settles and freezes what
it claims. The rest are recorded as the releases that build them land.

Cover:

* original design;
* alternative formulation;
* alternative comparison;
* modification;
* combination;
* fitting;
* multi-part assemblies;
* motion;
* multi-material assignment and inter-material interfaces;
* operation plans and their resumption;
* manufacturing packaging;
* physical feedback transitions.

No live AI call occurs.

**L2 — blind live evaluation**

Run on demand and before significant releases.

**What L2 does not yet cover, stated because the gap is easy to miss.** The blind
scorer never runs a job: `--score` takes a mesh that already exists and compares
it, so **no automated test in this repository asks an agent to turn a brief into
a design**. The four L1 recordings are self-recorded goldens and `_play_one`
refuses an `AGENT_COMMISSION` outright (`tools/replay.py:1028`), so
`design_proposal.json` and `model.py` are shipped *inputs* and the authoring step
that is the CUSTOM lane never executes. Real-subprocess coverage is not thin --
21 files in `benchmarks/heavy/` spawn one across 47 call sites, and
`test_build_skill_heavy.py` alone drives intake, plan, build and commission
through the extracted bundle. What none of it does is ask a live agent to author
geometry: every one exercises packaging or a deterministic CLI path against
inputs the test already holds. `docs/agents/qa-e2e-implementation.md` is
the five-fixture plan that closes this, and `docs/agents/qa-e2e-plan.md` records
the audit it came from. Neither is built yet.

**Built, for reconstruction.** `tools/blind.py` asks and scores against the
external reference corpus (`benchmarks/corpus.json`, Voron 2, GPL-3.0, never
committed):

    uv run python tools/blind.py --ask voron-deck-support --into /tmp/job
    uv run design-tool run /tmp/job --no-render
    uv run python tools/blind.py --score /tmp/job/candidate.stl \
                                 --against voron-deck-support

The question is the part's purpose plus the counterparts somebody measured --
the extrusion slot, the panel stock, the fastener -- and a stated build
envelope. Not the part's own geometry: that is the answer, `corpus.request_view`
is the only door to question material, and it refuses any number coinciding
with the reference's extents or volume.

**What a score is, and it is narrow.** Four dimensional measurements -- the three
bounding-box extents *sorted*, the volume, the body count, whether the solid is
closed -- **plus one shape descriptor**: the three principal moments of inertia
about the solid's own centre of mass at unit density, sorted and each divided by
`V^(5/3)`, scored as three separate per-moment rows at a 1% band.
Sorting buys orientation-independence with no registration — a part modelled
lying down still scores — and costs the axis identity with it. It is
**dimensional agreement, not shape equivalence**, and that is measured rather
than hedged: a plain slab with one rectangular pocket, sized to the deck
support's bounding box and volume, agrees on every *dimensional* row, and so
does the same slab with x and y swapped, which would not fit the extrusion the
brief specifies. **Normalised inertia is what rejects that slab** -- by 33% to
63%, where the per-body Euler tuple matched it exactly and normalised area sat
within 1.7%, which is why inertia shipped and the other two proposed descriptors
did not. It still does not certify a shape: three numbers can be shared by
distinct solids, so agreement there is evidence rather than proof. In the other direction two percent of that part's volume is about
one small through-hole, so whether a *correct* reconstruction passes the volume
row can turn on a feature the brief never dimensioned. Shape comparison is
Release 6 and needs the registration this avoids.

**The first blind run, and what it measured.** A designer agent with no access
to this session was given the generated job and nothing else, and told not to
open the corpus, the reference, or the web. It did not. Scored against the
withheld reference:

    OFF smallest  8.200 against  5.800  (+2.400, band 0.116)
    OFF middle   12.000 against 14.495  (-2.495, band 0.290)
    OFF largest  16.000 against 20.000  (-4.000, band 0.400)
    OFF volume   1023.19 against 1068.534        (4.2% out, band 2%)
    ok  bodies        1 against       1
    ok  watertight True against    True

Wrong on all three axes by 15–40%, and within **4.2% on volume**. Reasoning from
function and wall thickness got the quantity of material nearly right while
getting the shape wrong, which is the disclaimer above demonstrated rather than
asserted.

**Two findings the run produced that no test would have.**

The designer reported, unprompted, that the brief was not fully blind: every
requirement's `source` read "Voron 2 published hardware" and the purpose said
"deck panel", so any model carrying Voron familiarity was handed the ecosystem,
the part class and the hardware standard — *"which fixes the topology even
though it withholds the sizes"*. Sources are non-identifying now. Worth noting
what caught this: not a rule, a designer volunteering that its answer came
partly from recall.

And it named the deeper problem before the score was run — `docs/defects.md`
**D30**: for this reference the interface dimension **is** the answer dimension.
The part bolts flat to a 20 mm extrusion face, so it is 20 mm across.
`extrusion_series: "2020"` was refused by the coincidence check because 2020
states 20 and 20.0 mm is the answer — and removing it removed what the designer
needed to derive the width. Its own largest unconstrained axis was the depth
along the extrusion: *"Nothing stated touches it. A reference at 8 or at 20 is
equally consistent with the brief."* Two of three failing axes trace to
information the question could not carry, so `OFF, OFF, OFF` here is partly a
property of the question rather than of the designer, and D30 records the three
ways to close it.

**What it does not yet do.** Run more than once, on more than one entry, or with
D30 resolved — so there is no baseline, and one score is an anecdote. The
envelope was checked as a possible signal and carries none: all four entries
declare an identical 45×45×25.

Use a small number of authentic jobs to measure:

* request interpretation;
* design judgment;
* metrology;
* evidence use;
* correction behavior;
* meaningful alternative formulation;
* comparative reasoning.

Reviewed L2 runs should become L1 fixtures when legally and practically possible.

### 5.2 Learning record

Every authentic exercise produces a compact learning record containing:

* job and artifact identities;
* alternative identities;
* shared ancestry;
* tested capability;
* expected result;
* observed result;
* physical evidence;
* alternative comparison;
* preferred or rejected disposition;
* new defect or limitation;
* classification of the discovery;
* action taken;
* roadmap impact;
* architecture impact.

The format should remain lightweight enough that it is actually used.

### 5.3 Performance

At every release:

* preserve deterministic fast paths;
* measure cold and warm costs;
* cache stable expensive work;
* prevent accidental dispatch growth;
* keep new checks capability-triggered;
* share common work across alternatives;
* report cost per alternative;
* report cost regressions explicitly.

### 5.4 Security and isolation

At every release:

* treat imported CAD and archives as untrusted;
* validate paths;
* prevent traversal and symlink escape;
* isolate private benchmark answers;
* constrain generated-code execution;
* enforce process, memory, and time limits;
* isolate alternative artifact namespaces;
* prevent one alternative from reading private reference answers or overwriting siblings.

### 5.5 Licensing and privacy

At every release:

* record artifact licenses;
* separate vendored and external material;
* avoid committing private projects by default;
* verify immutable evidence hashes;
* keep redistributable and internal benchmark sets separable;
* ensure branched alternatives inherit licensing and privacy restrictions correctly.

### 5.6 Documentation truthfulness

At every release:

* document current support;
* document current limits;
* remove invalidated claims;
* distinguish generated, assessed, reviewed, printed, and physically proven results;
* distinguish supported branch storage from supported automatic alternative generation;
* distinguish tolerance constructs that can be declared from those that can be evaluated;
* distinguish a calibrated compensation from a provisional allowance.

## 6. Dependency rules

The roadmap may change, but these dependencies are mandatory:

* stable evidence precedes review-dependent workflows;
* candidate-independent acceptance precedes successful custom claims;
* the revision graph precedes broad alternative-dependent capability expansion;
* branch isolation precedes persistent A/B exploration;
* multi-source representation precedes multi-source preservation;
* a declared region disposition precedes any preservation verdict over that region;
* recorded datum provenance precedes any claim that rests on the datum;
* bounded repair precedes modification of an artifact diagnosis classified `REPAIR_REQUIRED`;
* a certified export precedes any claim about the artifact that export produced;
* deterministic comparison precedes strong preservation, interface scoring, comparative geometry scoring, and motion-contact claims;
* explicit component and interface semantics precede motion;
* lightweight explicit tolerancing precedes any formal tolerance profile;
* a supported comparison method precedes any conformance claim about a tolerance construct;
* per-body material identity precedes inter-material interface obligations;
* an operation model precedes sequence-aware assembly assessment;
* measured calibration precedes any applied compensation value;
* physical outcomes precede generalized calibration;
* stable capability semantics precede backend interchangeability;
* transitional paths are removed only after their replacement has been exercised on real jobs.

A narrow capability-liveness repair may move earlier.

A non-blocking rigor improvement should not delay a useful vertical slice unless the current output would be misleading.

## 7. Replanning checkpoints

A formal roadmap review occurs after Releases 2, 4, 6, 8, and 9.

At each checkpoint:

1. review authentic-job outcomes;
2. review performance and AI cost;
3. review alternative-exploration cost;
4. review benchmark gaps;
5. identify recurring manual work;
6. identify abstractions introduced for only one fixture;
7. identify concepts a single real job had to hand-build because the model could not express them, and check whether a second job has since needed the same one — a hand-built workaround is evidence of a gap only after it recurs, and until then it belongs in that project's record;
8. identify branches that added no useful learning;
9. evaluate whether comparison criteria reflect actual user decisions;
10. decide whether the next release remains the highest-value step;
11. revise later roadmap sections as needed.

Once a release has introduced tolerance, material, or sequencing semantics, the checkpoint also asks:

* Did formal tolerancing prevent a real ambiguity, or only add notation?
* Was the lightweight profile sufficient for the jobs that were actually run?
* Did the operation model improve manufacturability, or only add bookkeeping?
* Did multi-material compensation use a calibration relevant to the conditions it was applied under?
* Did any of these capabilities increase cost for jobs that did not use them?
* Does a recurring real requirement justify expanding the supported formal semantics — and is there a fixture that would fail without it?

An answer of "no material difference" is a reason to stop expanding that capability, not a reason to try harder.

Release order after Release 6 is deliberately flexible:

* fitting may precede motion;
* motion may precede fitting;
* a manufacturing blocker may be pulled forward;
* a newly demonstrated authority defect stops dependent work;
* a high-value real project may justify a narrow alternative-comparison feature earlier.

The roadmap should optimize the next useful learning step, not preserve its numbering.

## 8. Architecture-change triggers

The roadmap should not amend `ARCHITECTURE.md` merely because implementation is difficult.

An architecture change is justified when real evidence shows that:

* a recurring design concept cannot be represented;
* branch or merge semantics cannot preserve authority;
* the proposed authority boundary cannot work;
* an invariant prevents an important legitimate use case;
* a logical layer must own responsibility assigned elsewhere;
* proportional cost cannot be achieved under the current decomposition;
* comparative assessment cannot distinguish mandatory correctness from preference.

An architecture change should include:

1. the demonstrated case;
2. the failed assumption;
3. the proposed revision;
4. affected invariants;
5. affected roadmap releases;
6. new regression evidence.

## 9. Full-vision completion criteria

The roadmap is complete when the skill can, through one coherent user experience:

* produce a simple known part quickly without AI design work;
* produce a novel editable design in one ordinary design context;
* preserve and explore materially different alternatives;
* compare alternatives against shared requirements and explicit trade-offs;
* select a preferred alternative without deleting useful fallbacks;
* merge successful elements while preserving provenance and invalidating affected evidence;
* diagnose STEP, STL, and 3MF without false repair claims;
* repair a supplied artifact where an edit needs it, and record what the repair changed and which claims rest on it;
* modify supplied geometry while preserving declared regions, with a verdict per region and its declared disposition;
* certify that an exported artifact carries what was claimed about the geometry it came from;
* combine multiple source artifacts with source-specific obligations;
* design parts that fit real objects using appropriate evidence;
* express ordinary tolerances explicitly without industrial GD&T ceremony;
* accept a supplied formal tolerance under its declared profile, or say plainly that it cannot;
* create and assess multi-part moving assemblies;
* assign materials and processes where they belong and state what each inter-material interface still owes;
* express and resume a manufacturing sequence with pauses, inserts, and post-processing;
* prepare consistent FDM deliverables;
* incorporate real print and fit feedback into later revisions;
* restore or revise alternatives after physical failure;
* resume interrupted work without stale or mismatched evidence;
* use context and AI calls proportional to actual need;
* distinguish software, judgment, preference, print, and physical evidence;
* improve through fast fixtures, replay, and bounded blind runs;
* replace providers and geometry implementations without changing core job meaning;
* remain understandable enough that new work does not recreate parallel authorities.

Completion is not the existence of every planned subsystem.

It is demonstrated reliable performance across the major real use cases, with proportional cost, honest limitations, meaningful alternative exploration, and a learning loop that measurably improves later work.
