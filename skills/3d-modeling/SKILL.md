---
name: 3d-modeling
description: Design and verify 3D-printable parts. Use for any request to model, dimension, or print-prep a physical object, whether it is designed from scratch, modified from a supplied STEP/STL/3MF, or reconstructed from photos and calipers. Writes an immutable contract before the geometry, builds it with build123d or trimesh, measures the exported mesh against that contract, screens for geometry nobody declared, and reports exactly what was established.
---

# 3D modeling

A contract-first pipeline for designing printable parts. The contract is written
before the geometry and frozen once the build starts, so an expectation cannot
vanish with the code that produced it; the exported mesh is what gets measured,
whatever kernel made it.

Deterministic software owns structure, provenance, artifact identity, repeatable
measurement and resource limits. Agents own interpretation, geometry, trade-offs
and visual engineering judgment. More expensive roles are added only when the job
contains evidence or consequences that they can actually evaluate.

## One command surface

```bash
uv run design-tool init <project> --job-id J --source-mode NEW|MODIFY|RECONSTRUCT \
    --consequence INCONSEQUENTIAL|CONSEQUENTIAL --updated-utc <iso8601>
uv run design-tool route  <project>     # decide and record the route
uv run design-tool run    <project>     # every deterministic stage, then stop cleanly
uv run design-tool run    <project> --restart   # discard this branch's conclusions
uv run design-tool status <project>     # route, bindings, what it is waiting for
uv run design-tool branch <project> --from <alt|.> --id <name> --reason "<text>"
uv run design-tool branch <project> --activate <alt|.>
uv run design-tool branch <project> --disposition <state> --basis <basis> [--of <alt>]
uv run design-tool doctor               # what this interpreter can actually do
uv run design-tool selftest             # does this installation build what it certifies
```

`branch` declares a competing formulation of the same job. It copies nothing:
shared requirements, source artifacts and evidence stay in `project.json`, and
only what differs — the proposal, the model, the artifacts, the acceptance
revision, the reviews and every receipt — lives under `alternatives/<id>/`. A
review answered for one branch is refused by its sibling. A project that never
branches pays nothing: no directory appears and no payload gains a field.

`--disposition` moves a formulation between the seven lifecycle states and each
one changes something: `ACTIVE`, `PREFERRED` (at most one; switching demotes the
previous holder rather than erasing it) and `FALLBACK` (retained, still runnable,
and named by `status` when the current formulation has no claim) may be worked
under; `PAUSED` is parked and keeps its instruction; `REJECTED`, `SUPERSEDED` and
`MERGED` are concluded, clear their instruction and keep every receipt. Every
state but `ACTIVE` must say what it rests on with `--basis`. Transitions and
restarts are recorded in `lifecycle.json`.

`run --restart` discards what *this* formulation concluded — its receipts and its
review answers — and keeps what it concluded from: the frozen contract, the
proposal, the model, the build cache and every sibling. Use it when an answer
whose bindings all still hold is one you no longer trust; ordinary staleness is
already handled by re-running.

`project.json` is the one machine-authoritative description of a job. Fill it in,
then run `design-tool run <project>` and keep running the identical command.
Every stage the tool can do deterministically, it does; when agent judgement is
genuinely required it writes `next_action.json`, stops, and continues from that
state on the next invocation. A finished run deletes the file.

Exit codes: `0` done, `1` a gate failed, `2` the project is malformed, `3`
something has to be answered or built before it can continue — read
`next_action.json`.

`design-tool run-job <dir>` is the deprecated predecessor. It reads `job.json`
directly and still works; `run` adapts a bare `job.json` into a project on first
use and keeps it routing under the legacy rules.

## Four routes

The route is decided by **what has to be recovered, and how many things have to
agree**. Consequence never selects a route — it adds the mandatory safety pass.
Source mode never selects one either — `MODIFY` is not automatically `FITTED`.

| route | when | work |
|---|---|---|
| `DIRECT` | a certified template covers the whole shape, every value is known or chosen, nothing is recovered from evidence | zero design-agent calls |
| `CUSTOM` | geometry is novel or outside certified bounds; every value is stated, cited, inherited from a trusted artifact, or chosen by design | one designer commission |
| `FITTED` | acceptance depends on one externally owned object — photos, calipers, official spec, or source CAD needing reconciliation | metrologist, print plan, designer, fresh verifier |
| `FULL` | several interacting parts, more than one external interface, declared motion, mechanisms, parallel candidates | the complete workflow |

`CUSTOM` covers both from-scratch authoring and modification of an existing
design. It requires an independent verification when the job is
`CONSEQUENTIAL`, has an external mating interface, declares motion, needs
imported-geometry repair, has open questions, or when one is asked for.

A `CUSTOM` job is one designer commission that returns two files:
`design_proposal.json`, which says what the part must measure, and `model.py`,
which says how it is built. The pipeline validates and freezes the proposal,
generates `acceptance_contract.json` from it and the system-owned inputs, and
only then executes the model — so the built artifact cannot influence what it is
judged against. Acceptance bands are the pipeline's, not the designer's. Changing
the proposal cuts a new contract revision, invalidates the receipts issued
against the old one, and says so in `acceptance_history.json`.

**Any job that declares an edit scope cannot claim success right now.** A
`MODIFY` job declares one `edit_scopes` entry per artifact it modifies, and the
modification cap follows those scopes, not the `source_mode` label beside them —
an edit scope over a supplied artifact carries the preservation obligation on
every builder and every route, and every declared scope is owed its own audit
row. These jobs build, screen, gate and write every receipt, and a designer can
iterate against real measurements — but
the run reports `EXPERIMENTAL_UNAVAILABLE` instead of `COMMISSIONED` or
`VERIFIED`, because the preservation audit's sample density is not yet derived
from a declared minimum detectable defect size. `final_status.json` carries
`lane_status` and the reason, and a genuine `FAILED` is still reported as
`FAILED`.

A `FITTED` or `FULL` job built from authored geometry reports `UNSUPPORTED`
instead: the bounded metrology recovery those routes owe is defined only against
a certified template's bounds, so there is nothing to recover into. That is a
limit of what this build can do rather than a stage that is coming — name a
certified template, or drop the obligation. The repository's
`docs/adr/0002-route-and-contract-authority.md` records the rest.

`VERIFIED` requires an independent context on every route. Nothing else reaches
it.

## Source mode

`NEW` creates geometry from requirements. `MODIFY` starts from one or more
supplied artifacts that are authoritative. `RECONSTRUCT` recovers geometry from
evidence. A `MODIFY` job declares an edit scope: what must be preserved, what may
be removed, what is being added, and which named region the edit lives in.

Dimensions carry their provenance and are never collapsed into each other:
`STATED` by the user, `INHERITED` from a supplied artifact (bound to its hash),
`MEASURED` from evidence, `CHOSEN` by design.

## Roles

Read the one your dispatch names and only that one — the others are cost you
carry without using.

- [`roles/orchestrator.md`](roles/orchestrator.md) — Route and govern team 3D jobs. Start here when you are governing a job.
- [`roles/designer.md`](roles/designer.md) — Build FDM-aware reference and candidate CAD.
- [`roles/metrologist.md`](roles/metrologist.md) — Turn measurements into geometric ground truth.
- [`roles/print-engineer.md`](roles/print-engineer.md) — Plan and validate the physical print process.
- [`roles/verifier.md`](roles/verifier.md) — Independently verify exported printable geometry.

Shared assets sit beside them: [`references/`](references/) for the design guidance
and the verification patterns, [`scripts/`](scripts/) for the tooling.

The toolchain is four things and no more: `uv`, `build123d` for exact B-rep,
`trimesh` for measuring the exported mesh, and `manifold3d` as the boolean engine,
named explicitly at every call. There is no other CAD kernel and no silent
fallback to one.

## What a job costs, and where it actually goes

Measured on **one** live agent-driven `CUSTOM` run of this pipeline, end to end:
the deterministic pipeline took **33.99 s** while the job took **2 h 57 m**, so
the pipeline was **0.32%** of that run's wall clock. That ratio is a measurement
of one commission on one route, not a constant of this software: a job whose
geometry is expensive to build, or one that needs no agent at all, sits somewhere
else entirely. What generalises is the shape, not the number — on an
agent-driven job, deterministic build time is small next to the roles.

The time is in the roles, and it is spent **generating tokens**. Measured across
eleven role transcripts and 5.09 h of leaf-role span: **86.5%** of that span was
spent waiting on the model and 13.3% on tools, and generation ran at 78–122
tokens per second in every role. So a role's wall clock is close to its output
tokens divided by about a hundred per second — output tokens *are* the clock,
not merely the bill.

Most of those tokens are reasoning rather than text anybody reads: on these
transcripts **most billed output does not appear in the transcript at all** —
59% to 83% of it depending on how characters are converted to tokens, and 68.5%
of turns store no reasoning block at all, which needs no token arithmetic to
say. So turn count matters because **each turn carries its own reasoning pass**,
and a job's cost tracks how many times a role has to stop and think.

It is *not* that re-sending history is free. On the runtime these figures were
taken from, re-sent context was cached and cheap enough not to be the term that
mattered — but that is a property of that runtime and that model, measured here
and not a general law. If you are optimising somewhere else, measure it rather
than inheriting this sentence. What travels is the method, not the ratio.

In order of what it saves:

**Write one script, print one consolidated report.** When several numbers are
needed, compute them in a single run rather than issuing ten commands and
reading ten results. One ingest pass here ran twenty measurements as twenty
commands; as one script it is one turn. This is the largest lever a role has and
it costs nothing to obey.

**Do not re-derive the dispatch's own metadata.** If the packet names the
interpreter, the command surface, a path, or an immutable identifier such as an
artifact hash, take it — re-deriving those spends a turn to learn something you
were handed, and the dispatch owns them.

**This does not extend to evidence.** A measurement or a conclusion that your
role is chartered to establish independently must still be established from the
bound artifact, however it reached you. A figure arriving in a packet says
nothing about whether it is current or who produced it, and a metrologist or
verifier that accepts a supplied measurement because it was convenient has
silently promoted somebody else's number to evidence — which is the one thing
an independent context exists not to do. Saving a turn is never a reason to
inherit a fact you owe.

**Ask for concurrency only where the work is genuinely independent.** Two roles
that do not read each other's output cost the slower one dispatched together and
the sum dispatched in sequence. But check the direction of the dependency first:
on `FITTED` and `FULL`, print planning *consumes* metrology — the plan is written
against recovered dimensions — so those two are sequential there, and running
them together buys nothing while risking a plan built on numbers that changed.
Independence is a property of the route, not a default.

**Never put two writers in one directory.** Two roles authoring the same
contract will clobber each other, and here that destroyed a revision no receipt
could recover — the loss is the audit trail, not the geometry. One file, one
owner.

Facts worth having rather than rediscovering, each measured on this repository:
`export_stl` and `export_step` are module functions, not methods on a shape;
`render_multi_view` takes `view_size`, not `resolution`; the confined build
stages only `*.py`, so a `MODIFY` model reads its supplied artifact by absolute
path; `trimesh`'s ray engine here is pure Python and slow on large meshes, so
bulk ray work belongs behind an isolated accelerator rather than in the
project's dependencies; and a fresh `uv run` in a new worktree resolves without
the optional extras, which silently removes the renderer and reports the witness
as unavailable.

Read `final_status.json` when a job finishes: `allowed_claim` states exactly what
was established, and it is the sentence to repeat rather than paraphrase.
`COMMISSIONED` is not `VERIFIED`, and neither one is "safe" — a printed and
tested part is what makes a part ready to use, and this pipeline does not print.
