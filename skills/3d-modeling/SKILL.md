---
name: 3d-modeling
description: Route and govern 3D-printable modeling jobs. Use for new modeling or print-prep requests to run the five-role file-contract pipeline, enforce phase gates, dispatch specialists, maintain job state, and deliver verified artifacts without authoring geometry.
---

# 3D modeling

Five roles that speak to each other through file contracts rather than chat. Read the
one your dispatch names and only that one: each file is the whole charter for its job,
and the others are cost you carry without using.

- [`roles/orchestrator.md`](roles/orchestrator.md) — Route and govern team 3D jobs. Start here when you are governing a job.
- [`roles/designer.md`](roles/designer.md) — Build FDM-aware reference and candidate CAD.
- [`roles/metrologist.md`](roles/metrologist.md) — Turn measurements into geometric ground truth.
- [`roles/print-engineer.md`](roles/print-engineer.md) — Plan and validate the physical print process.
- [`roles/verifier.md`](roles/verifier.md) — Independently verify exported printable geometry.

Shared assets sit beside them: [`references/`](references/) for the contract spec and
the design guidance, [`scripts/`](scripts/) for the deterministic tooling.
`scripts/dt.py` is the toolkit launcher — invoke it by absolute path from wherever the
job is, and ask `dt.py doctor` what the interpreter you have can actually do.
