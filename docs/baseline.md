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
