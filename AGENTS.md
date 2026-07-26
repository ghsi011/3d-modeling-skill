# AGENTS.md

This repository packages a portable 3D modeling skill for FDM printed parts. It turns a plain-language commission, reference photos, and measurements into verified, print-ready model artifacts through role-specific agents and deterministic checks.

## Pipeline contract

Use the five-role pipeline for production work:

1. `3d-orchestrator`, owns intake, routing, job state, phase gates, and delivery.
2. `3d-metrologist`, owns datums, measurements, source confidence, and reference acceptance.
3. `3d-print-engineer`, owns print plan, fit strategy, material and orientation choices, coupons, and prep checks.
4. `3d-designer`, owns reference and candidate CAD from the accepted contracts.
5. `3d-verifier`, owns independent STL re-import checks, renders, and accept or reject evidence.

This is file-contract only communication: roles write and read project files, not chat summaries. Bind each role to the project contract files, source evidence, revisions, and hashes. The designer and verifier must stay independent, and verification must inspect exported artifacts, not only in-memory CAD state.

## Invocation

The pipeline ships as one skill. `skills/3d-modeling/SKILL.md` is a router naming five roles, all of them files in `skills/3d-modeling/roles/` -- the orchestrator reads its own charter like every specialist, rather than being the entry point itself. Any runtime that can spawn a subagent and read a file can run it — there is nothing to register per harness.

`skills/roles/*.md` are the source. After editing a role file, run `python tools/gen_harness.py`; CI fails on drift.

## Tooling paths

- `skills/3d-modeling/scripts`, deterministic model, mesh, preflight, preview, 3MF, and contract tooling.
- `tools/gen_harness.py`, renders the neutral role sources into the skill tree.
- `tools/bench.py`, snapshot a job mid-pipeline so one phase can be measured.
- `tools/build_skill.py`, packs `skills/3d-modeling/` into the deterministic `3d-modeling.skill`. CI step.
- `tools/check_internal_links.py`, relative-markdown-link resolver over the whole tree. CI step.

See also:

- [`docs/tooling.md`](docs/tooling.md)

## Runtime contracts

The normative file-contract schema is [`skills/3d-modeling/references/team-contracts-v4.md`](skills/3d-modeling/references/team-contracts-v4.md). It defines the required project files, revisions, hashes, gates, and role ownership rules. Don't replace it with chat instructions or harness-specific memory.

Every commission should state:

- role and task,
- authorized input files,
- required output files,
- contract revision or hash expectations,
- phase gate to satisfy,
- backend choice: `cadquery` | `build123d` | `freecad`.

## Backend selection

Treat the backend as an explicit commission input, not an agent preference. Use one backend per part unless the orchestrator records a new revision that changes the route.

The discriminator is the execution environment, not the modeling feature set: `cadquery` and `build123d` are headless Python/OCP kernels that run wherever the tooling runs, while `freecad` needs a desktop FreeCAD document driven over MCP.

Record the selected backend in the project contract files so downstream roles and tools can verify the same artifact chain.

## Changing a role

A role definition is a claim about what makes an agent design better. Test it the way the pipeline tests geometry: measure, do not assert.

Run the role blind against a part whose ground truth you hold but the agent cannot see — real photographs, a terse request, and nothing else in the job folder. Score its output against the truth afterwards. Then change exactly one thing in `skills/roles/`, re-run with byte-identical inputs, and compare. Record tokens, tool calls and wall-clock alongside the geometric error: a change that improves accuracy while costing twice as much has not obviously helped.

Two cautions learned from doing it. Pick a scoring datum the model cannot recall from training — a published phone dimension proves nothing about whether an agent measured, so score on a feature that appears in no spec sheet. And expect the useful failures to be reasoning failures rather than arithmetic: the run that moved the numbers most did not read its calipers differently, it stopped trusting a biased read and said why.

## Reviewing an iteration

Every implementation iteration ends with a code-review agent over its diff, and gets one mid-iteration when enough has changed to be worth the pass. This is not a formality at the end of the work — it is part of the work, and the iteration is not finished until its findings are resolved.

**Validate before you fix.** A reviewer's finding is a claim, not a fact. Re-derive each one against the code and paste the command that settles it. Both directions have burned this repo: a garbage-collection agent reported ~139 lines of duplicated role prose that measurement reduced to YAML frontmatter keys, and a review pass on the redesign plan caught an assertion that the repo's own docstring already contradicted. Acting on every finding is as wrong as acting on none.

Report which findings held, which did not, and why — in the commit message, where the next reader will be standing when they wonder.
