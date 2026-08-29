# Baseline — the behaviour Phase 0 froze

Measured at `f7082e5` on the reference workstation (Windows 11, Python 3.11,
trimesh 4.12.2, `uv run --frozen`), before any consolidation work. These are
measurements of one environment, not timing guarantees.

The phase and stage names below are the sequence recorded in
[ADR 0001](adr/0001-one-project-one-cli.md) and
[ADR 0002](adr/0002-route-and-contract-authority.md). They label when a
measurement was taken, not work that is currently queued; sequencing is owned by
[`ROADMAP.md`](../ROADMAP.md).

Regenerate the per-route numbers with `pipeline/test_frozen.py` and
`design-tool selftest --json`; the fixtures that hold them to account are in
[`pipeline/test_frozen.py`](../skills/3d-modeling/scripts/pipeline/test_frozen.py)
and [`pipeline/selftest.py`](../skills/3d-modeling/scripts/pipeline/selftest.py).

## Test suite

| | |
|---|---|
| collected | 706 passed, 4 skipped, 240 subtests |
| wall time | 555 s (9 m 15 s) |

## Deterministic cost per route

`render=False`, warm interpreter, in-process (no CLI start-up). Model calls are
stubbed, so the `llm calls` column is the number of dispatches the route
*requires*, not their latency.

| route | template | deterministic wall | llm calls | final status |
|---|---|---|---|---|
| `DIRECT` | `c_clip` (trimesh-manifold) | 0.20 s | 0 | `NEEDS_MORE_EVIDENCE` |
| `DIRECT` | `trim_ring` (build123d) | 3.90 s | 0 | `NEEDS_MORE_EVIDENCE` |
| `FITTED` | `c_clip` | 0.21 s | 2 | `VERIFIED` |
| `FULL` | `c_clip`, `bore_d=60` | 0.19 s | 2 | `VERIFIED` |

The `trim_ring` figure is a build123d cold import (3.69 s of the 3.90 s is the
build stage). The trimesh path's whole run is 0.2 s, of which commissioning and
screening are 0.13 s.

`design-tool selftest` builds all five certified templates in ~4.6 s, dominated
by the same cold import.

## Re-measured after repair stage 1 (route authority)

Same machine, same method, five runs after one warm-up, median. The stage moved
routing out of the runner and into a compiled `execution_plan.json`; reading a
plan is cheaper than re-deriving a route, and the measurement says so.

| route | before | after | llm calls |
|---|---|---|---|
| `DIRECT` `c_clip` | 0.197 s | 0.193 s | 0 -> 0 |
| `DIRECT` `trim_ring` (warm) | 0.252 s | 0.237 s | 0 -> 0 |
| `FITTED` `c_clip` | 0.183 s | 0.189 s | 2 -> 2 |
| `FULL` `c_clip`, `bore_d=60` | 0.184 s | 0.186 s | 2 -> 2 |

The `trim_ring` figures here are warm: the 3.69 s build123d cold import above is
paid once per interpreter and is untouched. Differences are inside the run-to-run
spread; no route gained or lost a dispatch.

## Re-measured after repair stage 2 (acceptance contract)

Same machine, same method. The stage adds a step to the authored lanes -- load
and validate `design_proposal.json`, generate the acceptance contract, compare it
against the frozen one -- and touches the certified path only where the
system-owned tolerance helpers moved module.

| route | stage 1 | stage 2 | llm calls |
|---|---|---|---|
| `DIRECT` `c_clip` | 0.193 s | 0.192 s | 0 -> 0 |
| `DIRECT` `trim_ring` (warm) | 0.237 s | 0.245 s | 0 -> 0 |
| `FITTED` `c_clip` | 0.189 s | 0.188 s | 2 -> 2 |
| `FULL` `c_clip`, `bore_d=60` | 0.186 s | 0.188 s (min of five) | 2 -> 2 |

A whole `CUSTOM` run of the two-tier riser -- validate the proposal, compare
against the frozen contract, build, export, re-import, commission, screen, write
the witnesses and decide the status -- is **0.046 s**, of which the proposal load
and the no-op freeze are **0.00055 s**. The freeze is a file read, a payload hash
and a dictionary comparison; it is not on the same order as the mesh work it
precedes.

`CUSTOM` stays at one designer commission. The proposal and the model are
required outputs of the same commission, and freezing is a pipeline step between
them rather than a second dispatch.

## Re-measured after the isolated build boundary

Same machine, same method. The change moves authored candidate execution into a
one-shot child process; `DIRECT` executes no candidate code and does not go
through it. `runner.py` does not import the boundary at all.

| route | stage 2 | isolated | llm calls |
|---|---|---|---|
| `DIRECT` `c_clip` | 0.192 s | 0.191 s | 0 -> 0 |
| `DIRECT` `trim_ring` (warm) | 0.245 s | 0.243 s | 0 -> 0 |
| `CUSTOM` riser, whole `design-tool run` | 0.054 s | 1.674 s | 1 -> 1 |

`DIRECT` is inside the run-to-run spread on both templates and gained no
dispatch. What `CUSTOM` pays is one cold interpreter, decomposed on this machine:

| | |
|---|---|
| bare interpreter start | 0.06 s |
| `python -m pipeline.build_child` (the boundary's own imports) | 0.16 s |
| the same interpreter reaching `import trimesh` | 1.58 s |

So the boundary itself costs about **0.16 s**, and the remaining ~1.5 s is the
geometry kernel the *candidate* imports, paid cold because the process is fresh.
It used to be free because the parent had already imported trimesh for its own
mesh analysis — which is another way of saying the candidate was running inside
the interpreter that measures it. A build123d model pays its own cold import the
same way, and one authored build pays this once.

The test suite's wall time moves 567 s -> 673 s for the same reason: every
authored-lane fixture now starts a process.

## Re-measured after the OS-enforced confinement

Same machine, same method. The change replaces the one-shot child process with a
restricted, low-integrity, privilege-stripped token inside a job object with an
ACL-confined workspace. `DIRECT` still executes no candidate code and still does
not go through it.

| route | isolated (`0a8e464`) | confined | llm calls |
|---|---|---|---|
| `DIRECT` `c_clip` | 0.191 s | 0.186 s | 0 -> 0 |
| `DIRECT` `trim_ring` (warm) | 0.243 s | 0.252 s | 0 -> 0 |
| `CUSTOM` riser, whole `design-tool run` | 1.674 s | 1.668 s | 1 -> 1 |

`DIRECT` is inside the run-to-run spread on both templates and still creates no
process at all -- asserted now with a `sys.addaudithook` over a
`pipeline.confine.spawn` audit event rather than by replacing two module
attributes, because a hook catches a process created through a name nobody
thought to replace.

The confinement is not what an authored build pays for. Decomposed on this
machine:

| | |
|---|---|
| plain `subprocess.run` of a bare interpreter | 0.057 s |
| the same interpreter, confined | 0.194 s |
| the whole confined authored build | 1.607 s |

So building the token, sealing two directories, creating the job object,
draining it and settling for the OS's own transient `conhost.exe` costs about
**0.14 s**, and the remaining ~1.4 s is the geometry kernel the candidate itself
imports, paid cold because the process is fresh. The whole run measures the same
as it did with an unconfined child process.

The suite goes 964 passed / 4 skipped / 379 subtests to **1006 passed / 4
skipped / 419 subtests**, and its wall time 673 s -> 794 s. That is the
adversarial coverage rather than the mechanism: `test_isolation.py` goes from 16
tests to 58, and the two ported grandchild attacks each wait eighteen seconds to
prove nothing outlived the run.

## Where the 997 s commit gate went, and the tier cut out of it

Profiled at `79244ae` on the same machine, two ways over the same suite:
`pytest --durations=0`, and a plugin holding a `sys.addaudithook` that counts
`subprocess.Popen` per test. Run in five chunks, so the totals carry about 6 s of
extra interpreter start against a single 997 s run.

| | tests | wall |
|---|---|---|
| whole suite | 1163 | 1020 s |
| tests that started at least one child process | 194 | 876 s |
| tests that started none | 969 | 143 s |

86% of the gate in 17% of the tests, and it is one mechanism rather than a long
tail: a child interpreter that reaches `import trimesh` is ~1.6 s here, which is
the modal cost of a test in that first row. Of the 969 that start nothing, all but
about twenty are under 0.2 s.

The five files holding the most:

| file | wall | of which spawning |
|---|---|---|
| `designer_toolkit/test_audit.py` | 230 s | 230 s |
| `pipeline/test_phase3.py` | 188 s | 160 s |
| `tools/test_build_skill.py` | 121 s | 121 s |
| `pipeline/test_pipeline.py` | 82 s | 58 s (the screening corpus, in-process) |
| `pipeline/test_isolation.py` | 73 s | 73 s |

Cut at that seam, with the handful of in-process heavies — the corpus at 19 s a
test, the B-rep STEP reads, the preservation and determinism fixtures that run a
job more than once — moved with them:

| tier | tests | subtests | wall |
|---|---|---|---|
| L0, `uv run pytest` | 838 | 458 | **43 s** (42.8 / 43.0 / 43.7) |
| L0-heavy, `uv run pytest benchmarks/heavy` | 350 | 190 | ~962 s |
| L1, `uv run pytest benchmarks/replays` | 55 | 38 | 68 s |

Re-measured on the same machine after Release 3's lifecycle group, which added 31
gating tests, 3 heavy ones and nothing to L1:

| tier | tests | subtests | wall |
|---|---|---|---|
| L0, `uv run pytest` | 869 | 477 | **45 s** (43.9 / 45.7 / 47.1) |
| L0-heavy, `uv run pytest benchmarks/heavy` | 353 | 190 | 889 s |
| L1, `uv run pytest benchmarks/replays` | 55 | 38 | 62 s |

The gate grew 3 s for 31 tests, all of which answer in this process: the
lifecycle group's end-to-end cases are on the certified lane, which builds
without a child interpreter, and the authored-lane restart — the one that needs a
real review answer to exist before it can discard one — is in `benchmarks/heavy`
where the tier rule puts it.

820 of the 1163 stayed and 343 moved; the other 25 are the tier guard's own
tests, new here. `pytest --collect-only` is 2.5 s of the 43 s, and `import
trimesh` alone is 1.8 s of that — which is the floor a commit gate on this
dependency set cannot go below, and the reason section 4.4's five-second budget
is amended to a minute rather than met.

## What a job costs, measured by the job rather than by a person

Every figure above was taken by hand. From Release 3's context-budget foundation
the pipeline takes them itself: `pipeline/cost.py` writes `cost.json` beside a
formulation's receipts, one entry per invocation of `design-tool run`, and
`design-tool status --json` reports it per alternative under `cost`. Regenerate
any row below by running the job and reading that file.

### Per route, warm interpreter, `render=False`, in process

`ctx` is the canonical size of the payload each reviewer was actually handed;
there is no tokenizer here and a token count would be invented. `budget` is the
ceiling `cost.budget()` derives from the compiled plan, which the run is refused
for exceeding.

| route | budget | dispatches | ctx | deterministic | builds |
|---|---|---|---|---|---|
| `DIRECT` `c_clip` `INCONSEQUENTIAL` | 0 | 0 | 0 B | 0.183 s | 1 |
| `DIRECT` `c_clip` `CONSEQUENTIAL` | 1 | 1 safety | 22.0 kB | 0.177 s | 1 |
| `DIRECT` `trim_ring` (cold build123d) | 0 | 0 | 0 B | 3.361 s | 1 |
| `FITTED` `c_clip` | 2 | spec + verification | 29.1 kB | 0.192 s | 1 |
| `FULL` `c_clip`, `bore_d=60` | 2 | spec + verification | 29.1 kB | 0.181 s | 1 |

The `trim_ring` row is the cold/warm distinction section 4.4 asks to be kept
separate, and it is why the ledger records `warm_kernel` per invocation: the same
work costs 0.18 s in a process that has already imported the geometry kernel and
3.36 s in one that has not. Import cost is **not** decomposed further — that
needs an import hook in the confined child, which is machinery nothing has asked
for; what is recorded is which regime the seconds were measured in.

### The dispatch the counter never counted

`llm_calls` counts safety, specification and verification. It does not count the
**designer commission** — `next_action.json` kind `AGENT_COMMISSION` — because
that is written by `cli.py` and returns before the runner is reached, and
`tools/replay.py` calls it "the live dispatch on the `CUSTOM` lane" in as many
words. The `CUSTOM` riser priced at "1 llm call" in the table above is that
commission, counted by a person. It is a ledger entry now, and its context is the
instruction **plus every file `authorized_inputs` tells the agent to read**,
because those are the context.

### Where a resumable command surface over-counts

`design-tool run` continues by re-running, and the invocation that finishes a job
re-reads every answer written for it — incrementing `llm_calls` again each time.
On the recorded `modify-ball-flange-flat` replay, three invocations report
`llm_calls` 0, 1 and 2. Two questions were ever asked. The ledger counts the
question at the pause that wrote the packet and records the re-reads as
`reviews_reused`, so the dispatch count is the number of times somebody was
actually asked something:

| | invocations | questions | stored answers re-read | builds | of which repeated |
|---|---|---|---|---|---|
| `modify-ball-flange-flat` | 3 | 2 | 3 | 3 | 2 |

**A two-review round trip costs three builds of one part.** That is what
resumption costs on this design and nothing measured it before.

### Per-alternative incremental cost

Measured on the recorded `branch-knob-seat-fallback` replay: three formulations
of one job on the real `berlingo-knob` request, driven through `design-tool
branch`, `route` and `run`. (The harness also reads each formulation's derived
status, by calling `status.report` -- these figures come from `cost.json` and do
not depend on that read.)

| formulation | dispatches | ctx | deterministic | builds | shared |
|---|---|---|---|---|---|
| `.` (the shared root) | 1 | 23.8 kB | 2.96 s | 2 | — |
| `plate-seated` | 1 | 23.8 kB | 2.90 s | 2 | 0 builds, 0 reviews |
| `as-drawn` (the fallback) | 1 | 23.8 kB | 2.91 s | 2 | 0 builds, 0 reviews |
| **project** | **3** | **71.5 kB** | **8.78 s** | **6** | |

The vent-ball branch exercise reached this conclusion with a stopwatch: a sibling
costs a full build and a full audit, and nothing is shared. The sharpest row is
`as-drawn`, which builds a candidate **byte-identical to its parent's** and costs
2.91 s against the parent's 2.96 s — 98% of a solo job for the same bytes.

What *is* shared is intent, and intent is free: the brief, the requirements, the
engagement length and the printer are read from one `project.json` no formulation
rewrites. What is not shared is anything computational, and the two mechanisms
that could change that are reported separately because they are zero for
different reasons. `builds_avoided` is **measured** and is zero because
`runner.run` consults the content cache *after* `backend.build` returns — a hit
confirms the bytes and saves nothing. `reviews_from_a_sibling` is zero **by
construction**: the review envelope carries `alternative_id`, and
`benchmarks/replays` carries the adversarial case that proves it still bites.

### Where the assessment seconds actually are

Measured on the same runs, from `timings.json` and the commissioning report,
because "assessment is expensive" is the assumption a lazy assessment registry
would be built on and nobody had checked it:

| | `DIRECT` `c_clip` | `FULL` `c_clip` `bore_d=60` |
|---|---|---|
| whole run | 0.192 s | 0.187 s |
| build | 0.018 s | 0.014 s |
| mesh load | 0.007 s | 0.005 s |
| commissioning | 0.044 s | 0.044 s |
| screening | 0.075 s | 0.076 s |
| witness | 0.030 s | 0.028 s |
| **assessment share** | **62%** | **64%** |
| checks | 11: 6 unconditional, 5 per declared feature | 12: 6 unconditional, 6 per declared feature |

Assessment is indeed most of a certified run — and the half that a capability
trigger could defer is *already* deferred by the contract: a check exists for a
feature only because the job declared it, and the expensive conditional
assessment this build has (the preservation audit, ~2 s) runs only when an edit
scope is declared. What is left is the unconditional baseline, and the largest
item in it is the broad anomaly screen, whose entire purpose is to ask the
question no declared check asks.

The seconds that are not in this table are the ones worth chasing: the confined
build boundary at 1.37-2.73 s per authored invocation, and the repeated builds a
review round trip pays for. Neither is an assessment. That band was measured
before the lazy `build123d` facade recorded further down this file and is left as
it was taken: it is a trimesh-lane figure, and the facade does not touch the
trimesh lane. An authored **build123d** candidate now costs materially less than
it did, and "Re-measured after the lazy `build123d` facade" is where that is
decomposed.

### The commit gate after the slice, and why its wall clock cannot be read

Every figure below is the same commit on the same workstation within one working
session. The suite did not change between them; the box did.

| tier | tests | subtests | measured |
|---|---|---|---|
| L0 before this slice | 867 | 477 | 43.3 s, then 74.4 s, then 76.9 s |
| L0 after | 890 | 488 | 44.6 s, 50.5 s, then 77.0 / 84.6 / 84.9 / 88.4 / 110.1 s |
| L1 before | 55 | 38 | 62.1 s |
| L1 after | 57 | 43 | 61.9 s, then 76.3 s |
| L0-heavy before | 353 | 190 | 889 s |
| L0-heavy after | 357 | 194 | 1046 s, summed over five foreground chunks |

**Paired deltas for the same 23 added tests, taken minutes apart, range from
0.1 s to 10.5 s.** 50.5 − 43.3 = 7.2 s early; 84.9 − 74.4 = 10.5 s in the
middle; 77.0 − 76.9 = 0.1 s late. Three honest measurements of one change, and
they do not agree well enough to hold a budget to.

What *is* stable about the slice, on any box: **+23 tests, +11 subtests, zero
child processes, slowest test 0.73 s** measured in the fast regime and ~1.4 s in
the slow one, against `conftest.py`'s 5 s ceiling. The file measured 6.07 s on
its own in the fast regime. The four tests that need the confined boundary are in
`benchmarks/heavy/test_cost_heavy.py`. L1 gained no wall time at all: the
assertions were added to classes that already play their case once.

**Collection time is not a usable normaliser, and this is the measurement that
says so.** `pytest --collect-only` was 2.5 s at `79244ae` and is **2.2 s** today,
while the same 867-test suite went from 43.3 s to 76.9 s. A ratio-to-collection
budget would have reported a 1.8x slowdown as a 0.9x *improvement*. The drift
does not touch import-bound work; it lands on sustained geometry and mesh
computation, which is what the suite is made of and what a two-second import
burst is not.

`design-tool selftest` does track it, partially: the five certified builds
measured 4.11 s and 5.80 s in the two regimes (1.41x) against the suite's 1.78x.
It is already shipped, already run and already 11/11, so it is the natural
calibration figure to record beside any published timing here — while being
honest that it under-reports the drift rather than cancelling it.

**Where the remaining seconds are.** Profiled in the slow regime: of 482 timed
calls totalling 81.8 s, **40 tests over 0.5 s hold 35.8 s** — 44% of the gate in
8% of the tests, the same shape as the 997 s finding one order down. Nothing
exceeds 2.1 s and nothing comes near the 5 s ceiling.

## Re-measured after the lazy `build123d` facade

Same workstation, Windows 11, Python 3.12.6, `build123d 0.11.1`. The change is
`pipeline/lazy_build123d.py`: inside the confined child, `import build123d`
resolves a name by importing the package's own submodules in the package's own
order, minus `{exporters, import_dxf, brep_from_stl}`, and falls through to the
real `__init__.py` for anything that search cannot serve. Nothing outside the
child changed, and the trimesh lane — which never names build123d — is untouched
by construction: the facade arms nothing until the package is first asked for
something.

**`build_seconds` is not redefined, and this heading is the change point.** It
measures what it always measured — importing the candidate and building it,
which in a fresh process are one cost — and the implementation underneath it
became faster. Every figure recorded *above* this section is the old
implementation and stays as it was taken; every figure below is the new one. A
number from before this line and a number from after it are both honest and are
not comparable, which is why the line is here instead of a quiet re-measurement
of the tables above.

Method, and it is the method the finding needs rather than a convention: one
fresh confined child per run through `pipeline.isolation.build(..., step=True)`;
seven copies of `skills/3d-modeling/scripts` differing only in this module; all
seven visited round-robin with the order reversed on alternate rounds; one
discarded warm-up per arm; ten kept runs per arm. Interleaving is not caution.
The bounded experiment that preceded this slice watched the **unchanged** base
arm's median move 5.368 s → 5.784 s between two sets on identical work, so a
before/after pair taken across such a gap could have reported anything between
1.2 s and 2.2 s.

Candidate: the real bearing commission,
`C:\projects\3d\bearing-clamp-discovery\job\model.py`, which imports seven names.

| arm | wall min | **wall median** | wall max | spread | `build_seconds` median |
|---|---|---|---|---|---|
| `origin/main`, no facade | 5.879 | **6.004** | 6.517 | 0.638 | 5.009 |
| **shipped** — the three omitted | 4.211 | **4.322** | 4.702 | 0.491 | **3.452** |
| omitting nothing, same order | 4.777 | 4.969 | 5.082 | 0.305 | 4.020 |
| …also serving `exporters` | 4.916 | 5.107 | 5.355 | 0.439 | 4.198 |
| …also serving `import_dxf` | 4.862 | 5.013 | 5.518 | 0.656 | 4.067 |
| …also serving `brep_from_stl` | 4.241 | 4.332 | 4.628 | 0.387 | 3.444 |
| a cheap-first re-sort, same omission | 4.129 | 4.237 | 4.516 | 0.387 | 3.352 |

**Wall 6.004 s → 4.322 s: 1.682 s, 28.0%, ranges not overlapping** (worst shipped
4.702 s < best base 5.879 s). `build_seconds` 5.009 s → 3.452 s: 1.557 s, 31.1%.
**One STL sha256 across all seventy runs**
(`8801818141c65dd55094bd85c992b7eecaa6e3e21adc7238132686950bb26eb8`), one STL
size, one declared-`PARAMS` digest, one STEP size, and every run returned a
`BuiltCandidate` rather than a refusal — a crash that finishes fast is not a
speedup, so nothing here trusts the clock alone.

### Where the 1.682 s is, and what the omission itself is worth

Two mechanisms, separable because the arms separate them:

| | |
|---|---|
| deferring at all — the package's order, nothing omitted | 6.004 → 4.969 = **1.035 s** |
| the omission, on top of that | 4.969 → 4.322 = **0.647 s** |

Per omitted submodule, as the marginal cost of *serving* it at the position
`build123d/__init__.py` imports it:

| submodule | `__init__` position | serving it costs |
|---|---|---|
| `exporters` | 6th | **+0.785 s** |
| `import_dxf` | 9th | **+0.691 s** |
| `brep_from_stl` | 24th, last | **+0.011 s** |

The first two do not sum to the pair, and that is a finding rather than noise:
both reach `ezdxf`, so serving either costs about one `ezdxf` and serving both
costs about the same again. Both sit ahead of the submodules carrying `Box`,
`Compound` and `chamfer`, so this candidate pays them — as does any candidate
whose names are not all in the first five submodules.

**`brep_from_stl` earned nothing on the clock and is omitted anyway.** +0.011 s
against a 0.39 s run-to-run spread is nothing: it is the package's last import,
so a search that stops at the first hit reaches it only for a name nothing else
carries, and such a name falls through to the real `__init__`, which imports it
anyway. It was removed on that measurement. The semantic-equivalence sweep put it
back within the hour — `build123d.brep_from_stl` binds `copy` to the **module**
where `__init__` leaves `copy.copy`, the *function*, re-exported from
`exporters`, and `T` and `TOLERANCE` differ the same way. Serving it would answer
`build123d.copy` with the wrong object for a candidate that never mentioned it.
So it is omitted because it cannot be served *correctly*, and the timing is
recorded here so that nobody removes it on the timing a second time.

**The cheap-first re-sort is inside the spread and is not shipped.** −0.085 s
against spreads of 0.39–0.49 s is no difference. It is the design the preceding
experiment measured, and what it buys is bought instead by an ordering claim that
nothing checks: sort the expensive submodules to the back and the omission goes
inert, because a search that stops at the first hit never reaches the back. That
is a property of *this* candidate's seven names and not of the mechanism, and an
authored candidate is arbitrary by contract.

### What the facade does not reach

The child still spends about 3.4 s and none of it is repo-owned: `IPython.lib.
pretty`, which `topology/shape_core.py` imports for `__repr__`; `build123d.text`,
most of which is a system-font scan at module scope; `scipy.optimize` from
`topology/one_d.py`; `sympy` reached from `operations_generic.py`; and
`OCP.Standard`. Reaching any of those means changing the library. Measured in the
same child, the eager import loads **3155** modules and this one loads **2296**.

Four libraries are *not* deferred and it would be easy to assume otherwise:
`svgpathtools`, `svgelements`, `svgwrite` and `ocpsvg` are reached by
`importers`, which the facade serves, so both arms load them.

### Confirmed on the shipped tree

The table above was taken on seven trees built to answer the design question, one
of which is the shipped configuration. Re-run afterwards on the two that matter
alone — `origin/main`'s child against the exact file that shipped — same method,
eight kept runs an arm:

| arm | wall min | **wall median** | wall max | spread | `build_seconds` median |
|---|---|---|---|---|---|
| `origin/main` | 5.725 | **5.931** | 6.268 | 0.543 | 4.910 |
| shipped | 4.216 | **4.299** | 4.465 | 0.249 | 3.404 |

**1.632 s, 27.5%; `build_seconds` 1.505 s, 30.7%; ranges not overlapping** (worst
shipped 4.465 s < best base 5.725 s), one STL sha256, one `PARAMS` digest and one
STEP size across all sixteen runs. The base arm's own median moved 6.004 s →
5.931 s between the two sessions on identical work, which is the drift the method
exists to cancel and is the reason both figures are reported rather than the
better one.

## The DIRECT status finding

A clean certified `INCONSEQUENTIAL` `DIRECT` job finishes `NEEDS_MORE_EVIDENCE`,
not `COMMISSIONED`.

`SKILL.md` and `roles/orchestrator.md` both present `COMMISSIONED` as the
ordinary outcome of this route. The shipped code does not produce it:
`screening.calibrated` is `False` — the corpus flipped it back when it was
re-measured against mutants actually fused to the part — and `status.decide`
refuses to call a part commissioned when the broad screen is uncalibrated *and*
nobody independent looked. `DIRECT`'s own route trade is that nobody independent
looks. So the two conditions are always both true on this route, and the claim
that comes back is:

> the geometry matches its contract, but the broad screen is uncalibrated and
> nobody independent looked, so undeclared geometry cannot be ruled out. Supply a
> verifier, or say plainly that nothing has looked at this part.

That claim is accurate. The documentation is what is out of date.

Frozen rather than fixed. The two ways to make this route say `COMMISSIONED` are
to earn the calibration on a corpus, or to weaken the threshold — and weakening a
threshold after observing the candidate is exactly what the scope controls
forbid. `test_frozen.py::test_direct_writes_its_frozen_receipt_set_and_claim`
pins it so the consolidation cannot change it by accident, in either direction.

## Receipts written, per route

| route | receipts |
|---|---|
| `DIRECT` | `intent_manifest`, `model_contract`, `artifact_manifest`, `commission_report`, `final_status` |
| `FITTED` | the above plus `specification`, `verification_report` |
| `FULL` | the same set as `FITTED` |

Plus `timings.json` (deliberately unhashed — durations are not part of any
artifact's identity) and `witness/` when a renderer is available.
`manufacturing_report` appears only when the job declares modifiers.

## Certified contract hashes

Frozen in `pipeline/selftest.py::FROZEN_CONTRACTS`. Derived from declared
parameters, expectations and the envelope — never from a mesh — so they are
independent of the tessellator version, and a mismatch means a certified
contract moved rather than that a dependency was bumped.

## Known-good agent-facing command surface, before consolidation

| surface | commands |
|---|---|
| `design-tool` | `run-job`, `doctor` (`selftest` added in Phase 0) |
| `scripts/dt.py` | `commission`, `doctor`, `crop`, `integrity`, `report`, `templates`, `probe`, `validate`, `status`, `screen`, `audit`, `intake`, `build`, `plan`, `coupon` |
| `python -m team_tools.contracts` | `validate`, `status`, `hash` |
| `scripts/team_preflight.py` | `support-audit`, `validate-interfaces` |
| `python -m pipeline.corpus` | screening calibration measurement |

Two CLIs and 20+ agent-facing verbs. [ADR 0001](adr/0001-one-project-one-cli.md)
reduces this to one documented interface.
