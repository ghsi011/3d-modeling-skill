# ADR 0001 — One project representation, one command surface, four routes

Status: accepted, 2026-07-30
Supersedes: nothing. Consolidates the two execution surfaces described below.
Execution plan: the phase-by-phase migration map that accompanied this ADR has
been deleted, and sequencing is now owned by [`ROADMAP.md`](../../ROADMAP.md).
The phase numbers below are the record of what was decided at the time; the
decision and its rationale stand as written.

## The sentence this whole design serves

> Deterministic software owns structure, provenance, artifact identity, repeatable
> measurement and resource limits. Agents own interpretation, geometry, trade-offs
> and visual engineering judgment. More expensive roles are added only when the job
> contains evidence or consequences that they can actually evaluate.

## Context: the skill has two execution surfaces

Measured on the source tree at `f7082e5`, the skill ships two overlapping ways to
do the same job.

**Surface A — the certified-template runner.** `design-tool run-job <dir>` reads
`job.json`, routes with `pipeline/intent.py`, derives an immutable contract from
`pipeline/templates.py` + `pipeline/expectations.py`, builds, commissions the
exported mesh, screens, renders witnesses, and writes `final_status.json` with an
`allowed_claim`. Reviews are answered on disk (`reviews/<kind>_packet.json` ->
`reviews/<kind>_response.json`, exit 3), which is already a resumable shape.
It is fast, auditable and closed: it can only build one of five certified
templates.

**Surface B — the general toolkit.** `scripts/dt.py <verb>` reaches
`designer_toolkit/` and `team_tools/`. `dt.py commission --model model.py --plan
print_plan_checks.json` gates arbitrary authored geometry against a print plan:
support, seating, envelope, edges, interfaces with fit bands, assembly
interference, repair, STEP export. `dt.py validate|status` gate the five v4
Markdown contracts and their revision bindings. This surface is what the role
files actually describe, and it is the only route today for novel geometry.

The two surfaces disagree about what a job *is*. Surface A's `FITTED`/`FULL` are
template-centred — `FULL` refuses outright unless a certified template is named,
because there is nothing to recover parameters into. Surface B's `FITTED`/`FULL`
are the general workflows the roles document. So:

* novel from-scratch geometry has no first-class route: `intent.select` calls it
  `FULL`, and `runner.run` then refuses it for having no certified template;
* modifying a supplied STEP/STL/3MF has no route at all — the orchestrator role
  tells you to send it through `FULL` and skip evidence recovery, which lands in
  the same refusal;
* two contract concepts (`pipeline/contract.py` and the v4 Markdown set) are
  independently editable authorities over the same job;
* the agent-facing instructions name two CLIs, and the role files carry the
  historical narrative for both.

## Decision

### 1. Four routes, one authority

Routing moves out of `intent.select` into `pipeline/route.py`, which decides over
the canonical project rather than over a parameter dict. `intent.select` keeps
its job — certified-template domain matching, with every rejection recorded — and
stops being the route authority.

| route | when | expected work |
|---|---|---|
| `DIRECT` | a certified template covers the complete requested shape, every design-driving value is known or chosen, nothing is recovered from evidence, no custom authoring | zero design-agent calls; deterministic contract, build, commissioning, screening, witnesses; safety review only where consequence policy requires it |
| `CUSTOM` | geometry is novel or outside certified bounds; every value is stated, cited, inherited from a trusted source artifact, or chosen by design; no photo/caliper/spec reconciliation | one designer commission; print plan before candidate measurement; deterministic commissioning of the exported artifact; independent verification when the escalation triggers fire |
| `FITTED` | acceptance depends on one externally owned object represented by photos, calipers, official specs, or source CAD needing reconciliation | metrologist, pre-design print/fit strategy, designer, fresh verifier |
| `FULL` | multiple interacting parts, multiple external interfaces, coupled motion, mechanisms, print-in-place, functional multi-material registration, parallel candidates, or high-consequence complexity | the complete workflow, skipping only phases whose inputs genuinely do not exist |

`DIRECT` is not broadened. `CUSTOM` covers both from-scratch authoring and
modification of an existing design; the difference between those is carried by
source mode, not by the route.

An uncomplicated `INCONSEQUENTIAL` `CUSTOM` part with no external interface may
finish `COMMISSIONED` after deterministic gates and an explicit witness
inspection. It may never finish `VERIFIED` — that still requires an independent
context, on every route.

`CUSTOM` escalates to independent verification when any of these holds:
`CONSEQUENTIAL`; an external mating interface; declared motion; significant
imported-geometry repair; a screen that is not clearly calibrated; the user asks
for it; or the orchestrator identifies meaningful ambiguity.

### 2. Source mode is orthogonal

`source_mode` is a required project field with three values, and it is not
conflated with consequence or with the route.

* `NEW` — geometry is created from requirements.
* `MODIFY` — one or more supplied artifacts are authoritative starting geometry.
* `RECONSTRUCT` — geometry must be recovered from evidence.

`MODIFY` does not by itself force `FITTED`: a supplied STEP that is trusted and
needs no reconciliation is a `CUSTOM` job with an edit scope. `RECONSTRUCT`
always implies at least `FITTED`, because reconciliation is exactly what the
metrologist owns.

### 3. One canonical project representation

`project.json` (schema 1) is the machine-authoritative state, validated by
`pipeline/project.py`. It carries or references: job id and schema version;
source mode; route and rationale; consequence and rationale; brief hash; stated,
inherited, measured and chosen requirements; source artifacts and hashes;
printer/material/nozzle/orientation; interfaces and fit strategies; motion
definitions; edit and preservation scope; expected components and artifacts; open
questions; required reviews; current bindings and status.

Markdown contracts stay as generated human-readable views. There is never a
second independently editable authority.

Adapters, so nothing in flight has to migrate:

* `pipeline/project.py::from_job_json` derives a project from an existing
  `job.json` and marks it `compat: "job.json@1"`;
* the pipeline JSON artifacts (`intent_manifest.json`, `model_contract.json`,
  `artifact_manifest.json`, `final_status.json`) keep their schemas and their
  meaning;
* the v4 Markdown contracts keep `team_tools`' validators; a project may
  reference them, and `design-tool status` reports their staleness alongside the
  project's own bindings.

Old completed projects are not migrated.

### 4. One documented CLI

`design-tool` is the single agent-facing interface:

```
design-tool doctor                 # what this interpreter can actually do
design-tool init <project>         # write a project.json skeleton, nothing invented
design-tool route <project>        # decide and record the route, with the rationale
design-tool run <project>          # every deterministic stage available, then stop cleanly
design-tool status <project>       # bindings, staleness, current status
design-tool diagnose <artifact>    # imported-file diagnosis and classification
design-tool commission <project>   # the deterministic gate on the exported artifact
design-tool audit <project>        # what a verifier can settle mechanically
design-tool motion <project>       # the declared-path sweep
design-tool coupon <project>       # fit coupon from the declared interfaces
design-tool package <project>      # 3MF / Bambu project draft
```

`run-job` remains as a deprecated alias of the `DIRECT`/`FITTED`/`FULL` runner so
existing job directories keep working. `dt.py` and `team_tools` stay reachable
for debugging during migration and leave ordinary agent instructions as each
verb becomes reachable through `design-tool`.

`design-tool run` is resumable on every route:

1. validate current inputs;
2. execute every deterministic stage available;
3. write a structured `next_action.json` when agent judgment is required;
4. stop cleanly;
5. consume the resulting contract/review on the next identical invocation;
6. continue without the orchestrator reconstructing state by hand.

The runner never pretends to perform an agent review. That property is already
enforced at the review boundary and is extended, not relaxed.

### 5. Commissions are generated, roles are slim

Each specialist commission is generated from canonical project state and contains
only: role, project path, authorized inputs, required outputs, bound revisions
and hashes, explicit unresolved decisions, completion command. No role charter,
no historical rationale, no expected answer.

Runtime role files keep charter, authority boundaries, inputs, outputs and
checklist. Incident narratives, benchmark numbers and long explanations move to
this ADR, to `docs/`, and to test names. The rule survives; the storytelling
leaves the agent's context.

## Modules: reuse, consolidate, retire

**Reused unchanged (the controls worth keeping).**

| module | what it owns |
|---|---|
| `pipeline/contract.py` | the immutable contract, its hash, and the preflight |
| `pipeline/schemas.py` | finite-number validation, path containment, canonical JSON, hashing |
| `pipeline/review.py` | review envelopes, evidence binding, fail-closed pass rules |
| `pipeline/safety.py`, `verification.py` | the two bounded review kinds |
| `pipeline/status.py` | final status and the allowed claim |
| `pipeline/screening.py`, `corpus.py` | broad anomaly screening and its calibration |
| `pipeline/witness.py`, `analysis.py`, `cache.py` | witnesses, one mesh load, content-addressed cache |
| `pipeline/expectations.py`, `templates.py` | certified templates and their split expectations |
| `designer_toolkit/commission.py` and its check modules | the deterministic gate for authored geometry |
| `designer_toolkit/plan.py` | the print plan, including per-interface fit strategy |
| `team_tools/validators.py`, `status.py` | v4 contract validation and revision staleness |

**Consolidated (one authority, several callers).**

| overlap | resolution |
|---|---|
| routing in `intent.select` vs the role files' route table | `pipeline/route.py` decides; `intent.select` matches template domains |
| `job.json` vs v4 Markdown contracts | `project.json` is authoritative; both become inputs/views |
| `pipeline/cli.py` vs `scripts/dt.py` | one `design-tool` front end; `dt.py` becomes an internal debugging launcher |
| `pipeline/screening.py` vs `designer_toolkit/screen.py` | one screening call reached through `design-tool` |
| `pipeline/cli.py doctor` vs `designer_toolkit/doctor.py` | one `doctor`, reporting both backends and extras |
| certified templates vs starting templates | one registry with an explicit `certified` flag; only certified templates are `DIRECT`-eligible |

**Retired from agent-facing instructions (not deleted while callers remain).**

`scripts/dt.py` verbs, `python -m team_tools.contracts`, and
`scripts/team_preflight.py` leave the role files and `SKILL.md` as their
functionality becomes reachable through `design-tool`. They remain importable and
tested throughout the migration.

## Consequences

* A novel part and a supplied-STEP modification each get a route that can
  actually finish, which neither has today.
* `DIRECT` is untouched: same routing inputs, same contract, same artifacts, same
  cost. Phase 0 freezes that as a fixture before anything moves.
* There is one place to look for "what is this job", which is what makes
  resumability and generated commissions possible at all.
* The migration is additive for two phases before anything is removed, so a
  half-applied migration still runs.

## Rejected alternatives

**A second general-purpose skill (`3d-mini` as a sibling).** Two skills competing
for the same trigger description is a routing problem for the host, and the
controls would diverge immediately. The strong ideas from that design —
imported-file diagnosis, explicit preservation of inherited geometry, mandatory
full-travel motion checks, a smaller agent-facing interface — are ported here
instead.

**Rewriting the runner around the general toolkit.** The certified `DIRECT` path
is the only measured zero-dispatch route in the repository. A rewrite would put
its cost and its receipts back in play to buy something that can be added beside
it.

**Making `FITTED` the default for anything uncertain.** Already rejected in the
orchestrator charter for a measured reason: reading contact as mating sends every
job to `FITTED`. `CUSTOM` exists so that "novel" and "fitted" stop being the same
answer.
