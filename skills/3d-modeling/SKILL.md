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
uv run design-tool status <project>     # route, bindings, what it is waiting for
uv run design-tool doctor               # what this interpreter can actually do
uv run design-tool selftest             # does this installation build what it certifies
```

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

**`CUSTOM`, and any job that declares an `edit_scope`, cannot claim success right
now.** The modification cap follows the declared edit scope, not the
`source_mode` label beside it — an edit scope over a supplied artifact carries
the preservation obligation on every builder and every route. These jobs build,
screen, gate and write every receipt, and a designer can iterate against real
measurements — but the run reports `EXPERIMENTAL_UNAVAILABLE` instead of
`COMMISSIONED` or `VERIFIED`, because the candidate still supplies its own
acceptance criteria. `final_status.json` carries `lane_status` and the reason,
and a genuine `FAILED` is still reported as `FAILED`. The repository's
`docs/adr/0002-route-and-contract-authority.md` records why, and what lifts it.

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

Read `final_status.json` when a job finishes: `allowed_claim` states exactly what
was established, and it is the sentence to repeat rather than paraphrase.
`COMMISSIONED` is not `VERIFIED`, and neither one is "safe" — a printed and
tested part is what makes a part ready to use, and this pipeline does not print.
