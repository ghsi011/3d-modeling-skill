---
name: 3d-modeling
description: Design and verify 3D-printable parts. Use for any request to model, dimension, or print-prep a physical object. Writes an immutable contract before the geometry, builds it with build123d or trimesh, measures the exported mesh against that contract, screens for geometry nobody declared, and reports exactly what was established -- certified INCONSEQUENTIAL DIRECT jobs can use one command with no model calls, while other routes keep their required reviews.
---

# 3D modeling

A contract-first pipeline for designing printable parts. The contract is written
before the geometry and frozen once the build starts, so an expectation cannot
vanish with the code that produced it; the exported mesh is what gets measured,
whatever kernel made it.

**Most jobs are one command.**

```bash
uv run design-tool run-job <project-dir>    # needs a job.json beside the brief
```

That runs intent, routing, the immutable contract, a completeness preflight, the
build, one mesh load, commissioning, broad anomaly screening, witnesses and the
final status -- zero model calls, well under a second. Read `final_status.json`
when it finishes: `allowed_claim` states exactly what was established, and it is
the sentence to repeat rather than paraphrase.

Read [`roles/orchestrator.md`](roles/orchestrator.md) for the job.json fields, the
certified templates and what to do when a job does not route `DIRECT`. The other
roles are for work the runner hands out: recovering measurements from photographs,
and the independent look that is the only route to `VERIFIED`. Read the one your
dispatch names and only that one -- the others are cost you carry without using.

- [`roles/orchestrator.md`](roles/orchestrator.md) — Route and govern team 3D jobs. Start here when you are governing a job.
- [`roles/designer.md`](roles/designer.md) — Build FDM-aware reference and candidate CAD.
- [`roles/metrologist.md`](roles/metrologist.md) — Turn measurements into geometric ground truth.
- [`roles/print-engineer.md`](roles/print-engineer.md) — Plan and validate the physical print process.
- [`roles/verifier.md`](roles/verifier.md) — Independently verify exported printable geometry.

Shared assets sit beside them: [`references/`](references/) for the design guidance
and the verification patterns, [`scripts/`](scripts/) for the tooling.
`design-tool doctor` reports what the interpreter you have can actually do.

The toolchain is four things and no more: `uv`, `build123d` for exact B-rep,
`trimesh` for measuring the exported mesh, and `manifold3d` as the boolean engine,
named explicitly at every call. There is no other CAD kernel and no silent
fallback to one.
