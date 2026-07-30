# Tooling reference

This page documents the deterministic tool surfaces used by the 3D modeling
team pipeline. Run repository tools from the repo root unless a command says
otherwise. The shared modeling scripts live in
[`skills/3d-modeling/scripts/`](../skills/3d-modeling/scripts/).

For the core runtime and the optional extras each tool needs, see
[Dependencies](../README.md#dependencies) in the README.

Exit code convention across these tools:

| Code | Meaning |
| --- | --- |
| 0 | Command completed successfully. For validation commands, the checked gate passed. |
| 1 | The command ran but the gate failed, output verification failed, or an uncaught runtime error occurred. |
| 2 | Command line usage failed, an input contract was malformed, a file could not be opened, or a strict preflight guard rejected the input. A file that is simply *absent* is not always an open failure: `team_tools.contracts validate` records a missing contract as a warning and still exits `0` unless the caller named it with `--require`. |

Individual tools narrow or extend this table below.

## `design-tool` — the canonical project surface

One command surface over one machine-authoritative project file. See
[ADR 0001](adr/0001-one-project-one-cli.md) for why there used to be two.

```bash
uv run design-tool init <project> --job-id J --source-mode NEW|MODIFY|RECONSTRUCT \
    --consequence INCONSEQUENTIAL|CONSEQUENTIAL --updated-utc <iso8601> [--from-job-json]
uv run design-tool route  <project>
uv run design-tool run    <project> [--no-render]
uv run design-tool status <project> [--json]
```

| exit | meaning |
| --- | --- |
| 0 | the job finished; there is nothing outstanding |
| 1 | a gate failed — the geometry does not match its contract, a review rejected it, or the lane may not claim success (`EXPERIMENTAL_UNAVAILABLE`) |
| 2 | `project.json` is malformed or incomplete; every missing field is named |
| 3 | something has to be answered or built before this can continue — read `next_action.json` |

### `project.json`

The one authoritative description of a job, validated by
[`pipeline/project.py`](../skills/3d-modeling/scripts/pipeline/project.py). It carries the
job id, source mode, consequence and rationale, the manufacturing inputs, every
requirement with its provenance (`STATED` / `INHERITED` / `MEASURED` / `CHOSEN`),
source artifacts with hashes and classification, interfaces and who owns the other
side of each, declared motion, edit scope, expected components, open questions,
required reviews, bindings and status.

Nothing is invented. `init` writes a skeleton in which every field you must supply
is present and empty, and prints them as a to-do list; `run` refuses with exit 2
until they are filled, naming all of them at once rather than one per round trip.

A directory holding only a legacy `job.json` is adapted on first `run` and marked
`compat: "job.json@1"`, which keeps it routing under the pre-consolidation rules.
Old completed projects need no migration.

### `next_action.json`

What the job is waiting for, written when `run` stops and deleted when it
finishes:

| kind | meaning |
| --- | --- |
| `FIX_PROJECT` | `project.json` is not complete enough to route; `unresolved` names every problem |
| `AGENT_COMMISSION` | a specialist has to produce something — `role`, `authorized_inputs`, `required_outputs`, `bound` hashes, `completion_command` |
| `REVIEW` | a bounded review is needed — `evidence` is the packet, `respond_with` is where the answer goes |
| `NEEDS_EVIDENCE` / `BLOCKED` | the run completed but could not reach a claim, or a gate failed; `unresolved` carries the status reasons |
| `LANE_UNAVAILABLE` | the run completed and the lane is not allowed to claim success; nothing an agent writes lifts it, which is why it is not a `REVIEW` |

A commission carries no expectation of what the specialist should conclude. That
is not politeness: a verifier told what to conclude has stopped being a verifier.

### The authored model source API (the `AUTHORED` builder)

A job whose plan names the `AUTHORED` builder -- every `CUSTOM` job, and any
other route for which no certified template covers the shape -- builds a Python
module the designer wrote. It is loaded and
validated by
[`pipeline/authored.py`](../skills/3d-modeling/scripts/pipeline/authored.py)
before anything is built:

```python
PARAMS        = {...}                          # the numbers the shape is built from
BBOX_MM       = {"x": .., "y": .., "z": ..}    # required
BODIES        = 1
EXPECTED      = [ {feature rows} ]             # required, non-empty
PROFILE_MARKS = {"z": [6.0]}                   # where the shape legitimately steps
VOLUME_MM3    = ...                            # the closed form
COMPONENTS    = [...]                          # optional
INTERFACES    = [...]                          # optional
PROVENANCE    = {...}                          # optional

def build(): ...                               # or a module-level `part`
```

`EXPECTED` rows use the same `kind` vocabulary as the certified templates —
`section_area`, `bed_contact`, `through_hole`, `bore_by_displacement`,
`void_region`, `overhang` and the rest of `commission.KNOWN_CHECKS`. An unknown
kind is refused rather than reported as an unrunnable check.

**Every declaration must be derived from `PARAMS` by arithmetic that does not go
through the builder.** Writing `BBOX_MM` by running the build and copying what
came out is a threshold authored by the party being measured, after measuring;
that is a receipt, not a gate. `PROFILE_MARKS` and `VOLUME_MM3` are optional, and
their absence is reported as an uncalibrated screen rather than treated as a
clean one.

The contract binds the module's path and hash under `source`, and the artifact
manifest records which kernel actually ran. An authored mesh model's
`boolean_engine` is recorded as `unrecorded` — the certified backends select
manifold3d at every call site and can name it, and an authored model was not
observed doing so.

There is no validity domain, because nobody has certified one. An authored model
never routes `DIRECT`.

### `print_plan_checks.json` (the `AUTHORED` builder)

Generated by `design-tool run` from the printer, the nozzle and the project's
declared `envelope_mm`, **before** the designer commission is written, and
validated before it is bound. Its `SELF_SUPPORT_REQUIRED` rule becomes an
`overhang` contract feature, so the support ceiling is measured by the same gate
as everything else and cannot have been set after reading the candidate. Its
`owner` is `builtin-direct-template`: nobody engineered this part, and naming the
source is what keeps that visible.

`envelope_mm` is therefore required whenever the geometry is authored. It is a design-driving
value like any other — stated by the brief or chosen by design — and `run`
refuses with exit 2 rather than guessing it.

## `design-tool diagnose` — what a supplied artifact actually is

```bash
uv run design-tool diagnose <artifact.step|.stl|.obj|.3mf> [--out report.json]
```

Measures a supplied file and classifies what can be built on it. **It never
writes to the artifact** — not a repair, not a normalization, not a re-export.
The supplied file is frequently the only authoritative copy, and a diagnosis that
silently fixed what it found would destroy the evidence that it needed fixing.

| classification | meaning |
| --- | --- |
| `USABLE_EXACT` | an exact B-rep with solids; boolean edits are exact |
| `USABLE_MESH` | a closed, consistent mesh; edits are mesh operations |
| `REPAIR_REQUIRED` | loadable, but not sound enough to build on as it is |
| `RECONSTRUCTION_REQUIRED` | nothing here can be built on (exit 1) |

Reported per format: body/component count, bbox, watertightness and winding for
meshes, faces with no usable area for B-reps, degenerate faces, boundary edges,
and the 3MF scene — objects, components, build items with their transforms, and
materials — rather than one merged solid, because that structure *is* the
functional information in a multi-part or multi-colour job.

### The 3MF scene, and the geometry in it

A 3MF is reported at both levels. The scene keeps its shape: `objects` (each with
its part, its components and its own mesh facts), `build_items`, `materials`, the
declared `unit`, and `root_part` / `model_parts` naming what was actually read.
Alongside it, every object is measured with the same questions the STL branch
asks — `bbox_mm`, `watertight`, `winding_consistent`, `triangles`,
`boundary_edges`, `bodies` and `volume_mm3` — so a 3MF diagnosis can answer the
questions its classification rests on. A 3MF mesh is indexed rather than a
triangle soup, so nothing is merged on the way in; merging would change the
author's topology and hide a genuinely split seam.

**The production extension is followed.** Bambu Studio, OrcaSlicer and
PrusaSlicer keep the scene in `3D/3dmodel.model` and every mesh in its own
`3D/Objects/object_NN.model`, reached through a `p:path` on the component. The
root part is the one the package relationship names, not whichever `.model` the
zip happens to list first, and an object id counts as dangling only when it
resolves in neither the referencing part nor the part its `p:path` names. Reading
one part and resolving ids against it alone reported intact, watertight,
winding-consistent files as `REPAIR_REQUIRED` for components that were never
broken.

`placed` reports each mesh instance with its build-item and component transforms
applied, and the top-level `bbox_mm` is the assembled scene (`bbox_note` says
which frame it is in). The transform is not decoration: a build item carrying a
`1.07` scale makes its part 7% larger than the numbers in its mesh part, and a
reader that skips it measures every scaled part undersize.

**A component chain that does not terminate is a finding.** Two objects whose
components refer to each other resolve cleanly, dangle nothing and parse — and
the scene they describe cannot be assembled. Cycles are searched over the whole
object graph rather than along the placement walk, for the same reason dangling
ids are: an unreferenced object whose components loop is still a broken file. A
chain more than 32 deep is reported separately, because it is a different
malformation. Either finding costs a file its `USABLE_MESH` — geometry inside a
loop that is watertight and consistently wound is still `REPAIR_REQUIRED`, and a
scene with no reachable mesh at all remains `RECONSTRUCTION_REQUIRED`.

Units are answered as honestly as the format allows. STL carries none, so the
bbox is reported as authored with a *suspicion* beside it (`/25.4` and `x1000`
arithmetic shown) and nothing is converted. 3MF and STEP carry them and they are
read. A mesh is reported twice — as parsed and after merging coincident vertices
— because an STL is a triangle soup and an unmerged read calls every sound part
`REPAIR_REQUIRED`.

## Modification: the edit scope and the preservation audit

A `MODIFY` project declares an `edit_scope` before the edit: the artifact, the
named region, **a `region_box`**, what must be preserved, what may be removed,
what is being added, the expected body delta, and whether a mesh fallback is
allowed. A name alone cannot be compared against, so the box is what the audit
measures; the name is what a person argues with.

[`pipeline/preservation.py`](../skills/3d-modeling/scripts/pipeline/preservation.py)
compares everything outside that box, bidirectionally — sampling only the source
misses material the edit added outside the region, and sampling only the
candidate misses material it removed. It reaches the commissioning verdict as a
`preservation` contract feature, not as a separate report, so a job can actually
fail for it.

| verdict | meaning |
| --- | --- |
| `PRESERVED_EXACTLY` | only when the caller declares both sides exact B-rep exports from one kernel |
| `PRESERVED_WITHIN_TOLERANCE` | no sampled point outside the region moved more than the declared band |
| `CHANGED` | something outside the declared region moved, with the worst point |
| `UNMEASURABLE` | no region box, or the region covers the whole part — escalates, never passes |

**The claim never outruns the method.** A sampled mesh comparison cannot
establish exact preservation, so it does not say it did; the report carries the
method, the sample count and the tolerance it was measured at.

The support ceiling is inherited on a `MODIFY` job: a generated zero fails a
supplied part for overhangs that were in the file before anybody touched it, and
the designer cannot chamfer them away without redrawing the part. The ceiling is
therefore the source artifact's own measurement — taken from a file fixed before
the job started, so it is not a threshold tuned to the candidate — and any
overhang the edit *adds* still fails.

### `route_decision.json`

The route, the deciding condition, the source mode, the escalation triggers that
turned an independent verification on, **and every route that was not taken with
the reason**. Routing used to leave no trace, so it could be neither audited nor
regression-tested.

### `execution_plan.json`

What will actually be executed under that decision, compiled from it by
[`pipeline/execution.py`](../skills/3d-modeling/scripts/pipeline/execution.py) in
the same invocation: the route, the **builder** (`CERTIFIED_TEMPLATE` or
`AUTHORED`) **and why that builder**, the reviews the job owes, whether an
independent verification is `NEVER`, `OPTIONAL` or `REQUIRED`, whether the job
must prove it preserved everything outside its declared edit region, and whether
the lane may claim success at all. Nobody writes this file by hand and no command
exists to produce it on its own — `design-tool run` is still one command for a
whole job.

A declared `model` is the builder on every route. Preferring a matched certified
template over it emitted a plan that contradicted itself — `builder:
CERTIFIED_TEMPLATE, model: model.py` — and then built the template, so a job
declaring both reached `VERIFIED` without the designer's file being named on any
receipt. `builder_rationale` says which declaration won and which was set aside.

`requires_preservation` is set by the **edit scope**, not by the source mode, and
the runner refuses a contract that does not carry the row it names. Keyed on
`source_mode == "MODIFY"` instead, a project that declared an edit scope over a
supplied artifact and wrote `RECONSTRUCT` beside it built a certified template,
never opened the artifact, and finished `VERIFIED`.

`OPTIONAL` is compiled only for `FITTED` and `FULL`, and `design-tool run`
supplies a verifier for it. It used to be compiled exactly when no verifier would
be supplied, so only `run-job` — which hands the runner every callable
unconditionally — could act on it, and one `job.json` finished `VERIFIED` through
the deprecated entry point and `NEEDS_MORE_EVIDENCE` through the supported one.
`DIRECT` and `CUSTOM` reach `NEVER`: `DIRECT` trades the look away, and `CUSTOM`
is one designer commission that must not grow a second round trip by side effect.

The runner consumes it verbatim and decides no route of its own. It used to keep
a second copy of the answer, re-derived from `intent.select`, and every guard
downstream read that one: a `RECONSTRUCT` job whose parameters happened to sit
inside a certified domain routed `FITTED`, executed as `DIRECT` with neither the
metrologist nor the verifier it owed, and wrote `"route": "DIRECT"` on its own
receipt.

Route and builder are separate axes and are recorded separately. A certified
template used by a `FITTED` job makes the build cheap; it does not make the
evidence obligation smaller, and the job stays `FITTED`.

`final_status.json` carries the plan's route, `execution_plan_sha256` and
`lane_status`, so a receipt can be checked against the plan that produced it.

## `design-tool run-job` — the deprecated predecessor

Reads `job.json` directly, skipping the canonical project. Kept so existing job
directories keep working; `design-tool run` is the supported entry point and
adapts a bare `job.json` on first use. One invocation runs contract, build,
commission, screening, witness and status; every extra invocation would pay
interpreter startup to do work measured in milliseconds.

```bash
uv run design-tool run-job job_dir/ [--no-render]
```

`job_dir/job.json` describes the job:

| field | meaning |
| --- | --- |
| `job_id` | names the job in every artifact it writes |
| `template` | a certified template name; omit to let routing decide |
| `parameters` | the template's parameters, in mm |
| `consequence` | `INCONSEQUENTIAL` or `CONSEQUENTIAL` — there is no third level |
| `printer` | **required** printer profile name; the pipeline never invents the machine |
| `material` | **required** object naming non-empty `process` and `material` strings |
| `nozzle` | **required** object with positive numeric `diameter_mm` |
| `orientation` | **required** object with `model_to_printer_matrix` (`identity` or a 4×4 numeric matrix) and numeric `bed_z_mm` |
| `stated` | which parameters the user actually gave, as opposed to chosen for them |
| `updated_utc` | timestamp carried into the contract |
| `reviewer` | who answers the reviews, by their own account — including `fresh_context`, which nothing here can verify and so is never assumed |
| `modifiers`, `step`, `evidence`, `interface_map`, `cache_dir` | optional; see `runner.JobRequest` |

The manufacturing fields are part of the immutable `model_contract.json`, not
informal print notes. A minimal complete job has all four:

```json
{
  "job_id": "clip-01",
  "template": "c_clip",
  "consequence": "INCONSEQUENTIAL",
  "printer": "Bambu Lab X2D",
  "material": {"process": "FDM", "material": "PETG"},
  "nozzle": {"diameter_mm": 0.4},
  "orientation": {"model_to_printer_matrix": "identity", "bed_z_mm": 0.0},
  "parameters": {"bore_d": 12.0, "wall": 3.0, "height": 9.0, "mouth_gap": 9.0,
                 "flange_w": 40.0, "flange_d": 22.0, "flange_t": 5.0, "screw_d": 4.8},
  "stated": ["bore_d", "flange_w"],
  "updated_utc": "<iso8601>"
}
```

Exit codes, which extend the table above:

| Code | Meaning |
| --- | --- |
| 0 | The job finished and `final_status.json` records a status the run earned. |
| 1 | The job stopped at a named stage, or finished at a status short of passing. The receipt says which and why. |
| 3 | The job needs a review before it can finish. See below. |

### Answering a review

A certified `INCONSEQUENTIAL` `DIRECT` job has no review callback. A certified
`CONSEQUENTIAL` `DIRECT` job has exactly one bounded safety review and no normal
geometric verifier. `FITTED` requires one bounded specification review; an independent
verification review may follow when the caller supplies it and the screen is clear.
`FULL` requires both the specification review and independent verification. These are
judgements about a part; a deterministic program that returned one would be inventing
it. So the CLI writes the evidence and stops:

```
design-tool: this job needs a safety review before it can finish.
  the evidence is written to  reviews/safety_packet.json
  write the answer to         reviews/safety_response.json
  then run the same command again.
```

Write the response file and re-run the same command. Responses are validated
against the same schema an in-process caller is held to — a malformed one is a
`SchemaError`, not a shrug. The safety packet deliberately omits
`verification_report.json`: a second opinion that read the first one is not a
second opinion.

### What it writes

`model_contract.json`, `intent_manifest.json`, `candidate.stl` (and
`candidate.step` when the contract asks), `commission_report.json`,
`manufacturing_report.json`, `witness/`, `artifact_manifest.json`,
`timings.json`, and `final_status.json`.

**Read `final_status.json`, and read `allowed_claim` before repeating anything
about the part.** `COMMISSIONED` is not `VERIFIED`, and neither one is "safe".
`EXPERIMENTAL_UNAVAILABLE` is none of them: the work ran and the receipts are on
disk, and the lane is not yet allowed to certify its own result. `lane_status`
and the `reasons` list say which lane and why.

## `design-tool selftest` — does this installation build what it certifies?

The smoke set that ships inside the distributed bundle. An installed skill has
the code and none of the repository's tests, so before this existed the
strongest thing an agent could say about an installation was "it imported".

```bash
uv run design-tool selftest [--quick] [--json]
```

It checks the core toolchain, then compares every certified template's contract
against the hashes frozen in
[`pipeline/selftest.py`](../skills/3d-modeling/scripts/pipeline/selftest.py),
then builds each one through the real backends and commissions the exported
mesh. `--quick` stops after the contracts, so it runs on any interpreter and
builds no geometry.

The frozen hashes are derived from declared parameters, expectations and the
envelope — never from a mesh — so they hold across trimesh, manifold3d and
build123d versions. A mismatch means a certified contract *moved*, which is an
architecture decision rather than a dependency bump. Exit 1 names every check
that failed and why.

## `python -m pipeline.corpus` — the screening corpus measurement

Builds every certified template, mutates each one, and reports what broad
screening caught. Exits non-zero when the measured gate fails.

```bash
uv run python -m pipeline.corpus
```

The fields worth reading: `gate`, `screening_false_negative_rate` (scored on
defects *fused* to the part, since a disconnected one is caught free by the
component detector), `false_positive_rate` with its `clean_parts_checked`
denominator, and `survivors_of_everything`.


## `team_preflight.py`

Script: [`skills/3d-modeling/scripts/team_preflight.py`](../skills/3d-modeling/scripts/team_preflight.py)

Runs deterministic non-acceptance gates for the team pipeline. It emits sorted,
indented JSON to stdout unless `--output` is provided. All subcommands return
`0` when the emitted JSON has `"result": "PASS"`, `1` when it has
`"result": "FAIL"`, and `2` for usage, unreadable files, malformed JSON, or
schema errors raised before a gate result can be written.

### support, actual command `support-audit`

```bash
uv run python skills/3d-modeling/scripts/team_preflight.py support-audit \
  --stl candidate.stl \
  --plan print_plan_checks.json \
  --rule-id support-rule-id \
  [--output support_audit.json]
```

Inputs:

* `--stl`, exported STL to re-import and screen.
* `--plan`, `print_plan_checks.json` containing `support_rules`.
* `--rule-id`, support rule id inside the plan.
* `--output`, optional JSON output path. Without it, JSON goes to stdout.

Outputs:

* JSON kind `downward-facing-surface-screen`.
* STL hash, plan hash, transform hash, bed contact area, out-of-limit face
  count, out-of-limit area, configured maximum area, and `PASS` or `FAIL`.

Exit codes:

* `0`, out-of-limit area is within the rule limit.
* `1`, out-of-limit area exceeds the rule limit.
* `2`, missing rule, malformed rigid transform, missing file, bad JSON, or bad
  numeric input.

### interfaces, actual command `validate-interfaces`

```bash
uv run python skills/3d-modeling/scripts/team_preflight.py validate-interfaces \
  --plan print_plan_checks.json \
  [--output interface_validation.json]
```

Inputs:

* `--plan`, `print_plan_checks.json` with an optional `interfaces` array.
* `--output`, optional JSON output path.

Outputs:

* JSON kind `interfaces-validation`.
* Sorted `interface_ids`, collected error strings, and `PASS` or `FAIL`.

Exit codes:

* `0`, `interfaces` is absent, null, or fully valid.
* `1`, an interface row is malformed, has a duplicate id, uses an unknown
  `fit_type`, declares an invalid range, or misses required acceptance fields.
* `2`, the plan cannot be read or parsed.

## `python -m team_tools.contracts`

Module: [`skills/3d-modeling/scripts/team_tools/contracts.py`](../skills/3d-modeling/scripts/team_tools/contracts.py)

This package validates the v4 team contracts: the four Markdown ones through their
frontmatter (identity, revision, binding hashes), and the JSON ones structurally.
Passing it proves contract structure, identifiers, declared hashes, and revision
bindings only. It doesn't prove geometric or manufacturing correctness.
`job_state.md` is a closed header: `consequence` is required, legacy `risk_class` is
rejected, and unknown frontmatter fields are errors rather than ignored warnings.

### `validate`

```bash
cd skills/3d-modeling/scripts
uv run python -m team_tools.contracts validate path/to/project [--require CONTRACT] [--output receipt.json] [--timestamp ISO-8601]
```

Inputs:

* Project directory containing the contracts. Each is looked up as Markdown
  first (`dimensions.md`), then a JSON mirror (`dimensions.json`) if one
  exists; `artifact_manifest.json` is JSON-only. A directory that does not
  exist is a filesystem error (exit `2`), never a project whose contracts all
  happen to be missing.
* Optional `--require`, naming contracts whose absence is an **error** rather
  than a warning: `job_state`, `dimensions`, `print_plan`,
  `verification_report`, `artifact_manifest`, or `all`. Repeatable and
  comma-separated, from `job_state`, `dimensions`, `print_plan`,
  `verification_report`, `artifact_manifest`, `candidate_readiness`,
  `final_print_prep`, `final_prep_review`, or `all`. An unknown name is a usage
  error (exit `2`) rather than a silently dropped requirement.
* Optional `--output` receipt path.
* Optional `--timestamp`, injected into the receipt instead of reading wall
  clock time.

Outputs:

* Canonical JSON receipt with tool version, schema version, job id, required
  contracts, validated paths, observed revisions, computed SHA-256 values,
  per-contract results, warning ids, error ids, issues, timestamp, invocation,
  and disclaimer.

Exit codes:

* `0`, `results.overall` is `PASS`.
* `1`, one or more contract results failed.
* `2`, a contract loader or filesystem error prevented validation, including a
  missing project directory or an unknown `--require` name.

Absence is silent by default, on purpose: mid-pipeline a project legitimately
holds only the contracts its phase has produced, so a blanket error would make
`validate` unusable before Phase 4 — and a warning on every correct run trains
its reader to skim the channel that also carries `POSSIBLE_UNIT_SCALE_MISMATCH`.
So **a bare `validate` on a project holding no contracts at all exits `0`**. The
exit code alone proves that nothing which was read was rejected; it does not
prove anything was read. `validated_paths` records exactly what was.

Anything gating on this command must therefore say what it expects, either by
passing `--require` (absence becomes `REQUIRED_CONTRACT_MISSING`, an error, and
the run exits `1`) or by asserting that the contracts it needs appear in the
receipt's `validated_paths`. Prefer `--require`: it lands in the receipt's
`required_contracts` field, so a reviewer can tell a deliberately narrow
validate from one that gated on nothing.

### `hash` and `status`

```bash
cd skills/3d-modeling/scripts
uv run python -m team_tools.contracts hash path/to/project
uv run python -m team_tools.contracts status path/to/project
```

Both take a project directory and print to stdout by default. `hash` takes
`--output` and `--timestamp`; `status` takes `--output` and `--json`.

| Command | What it proves | Exits `1` when |
| --- | --- | --- |
| `hash` | Contract and artifact SHA-256 values recomputed from the bytes on disk, never trusting a hash written into a contract. | A declared artifact hash differs from the bytes on disk. |
| `status` | Each contract's revision, plus the downstream bindings that later revisions have made stale. | A row is `STALE`, `INVALIDATED`, or `UNREADABLE`. |

## `dt.py` — the toolkit launcher

Module: [`skills/3d-modeling/scripts/designer_toolkit/__main__.py`](../skills/3d-modeling/scripts/designer_toolkit/__main__.py)

Invoke it by absolute path from your project directory. It puts its own directory
on `sys.path`, so command-line paths resolve against your working directory rather
than the skill's, and neither a `cd` nor a `PYTHONPATH` is needed. The module form
(`python -m designer_toolkit ...`) still works but requires the working directory to
be `skills/3d-modeling/scripts/`, which is what made every measured designer run
write a shim instead. Every subcommand
prints indented JSON to stdout. The CLI doesn't catch toolkit exceptions, so
success returns `0`, argparse usage errors return `2`, and runtime errors
normally return `1` with a Python traceback.

### `commission`

```bash
uv run python <skill>/scripts/dt.py commission (--model model.py | --stl body.stl) --plan plan.json   --out DIR --job-id JOB --updated-utc ISO8601 [--reference ref.stl] [--no-render] [--no-receipts]
```

Inputs: a model module defining `part`/`build()` or an already-exported STL; the
bound `print_plan_checks.json`; an output directory; an injected timestamp.

Outputs: `commission.json` with every deterministic verdict and the next action for
each failure, plus `artifact_manifest.json` and `candidate_readiness.md` derived from
the same measurements. Exit `0` when every check passed, `1` when any failed, so a
failing candidate cannot be handed on.

This subsumes the former `measure`, `overhang`, `datums`, `interference`, `sweep`,
`export` and `finalize` subcommands, which are gone. Each was a separate process
paying interpreter and CAD-library startup, re-parsing the same STL, and costing an
agent round trip repeated after every edit — and offering the pieces individually is
what led three measured runs to assemble a hand-written verification script instead
of running the gate. The library functions remain importable for the rare direct use.

### `coupon`

```bash
uv run python <skill>/scripts/dt.py coupon --plan plan.json --out coupon.stl
uv run python <skill>/scripts/dt.py doctor
uv run python <skill>/scripts/dt.py plan template --bbox X Y Z --out print_plan_checks.json
uv run python <skill>/scripts/dt.py plan check print_plan_checks.json
```

Inputs to `coupon`: plan JSON, either a JSON object with `interfaces` or a raw
interface list, and a required `--out`. `doctor` and `plan` take neither.

Outputs: JSON object with written `stl` path and `legend` rows. The command also
writes the coupon STL.

## `preview.py`

Script: [`skills/3d-modeling/scripts/preview.py`](../skills/3d-modeling/scripts/preview.py)

```bash
uv run python skills/3d-modeling/scripts/preview.py model.stl [output.png] \
  [--views iso|multi] [--title "Title"] [--subtitle "Text"] \
  [--resolution 600] [--strict]
```

Inputs:

* STL path.
* Optional output PNG path. Default is `<stl_name>_preview.png`.
* `--views iso` for one isometric image or `--views multi` for an eight-view sheet
  (all four sides square-on plus two isometrics, top and bottom).
* Optional title, subtitle, and per-view resolution.
* `--strict` to fail before rendering if the normalized mesh is not watertight.

Outputs:

* Text summary with model path, bounding box, triangle count, watertight warning
  if present, and final preview path.
* PNG preview image.

Exit codes: the convention above, with `--strict` rejecting a non-watertight
mesh as a `2` rather than a `1`.

## `mesh_io` library

Library: [`skills/3d-modeling/scripts/mesh_io.py`](../skills/3d-modeling/scripts/mesh_io.py)

`mesh_io` is not a CLI. Import it from Python code that needs mesh loading
without the heavier preview rendering stack.

```python
from mesh_io import load_mesh, load_mesh_raw, load_mesh_report
```

Inputs:

* A mesh file path accepted by `trimesh.load`, normally STL for this pipeline.

Outputs:

* `load_mesh_raw(path)`: raw, unrepaired `trimesh.Trimesh` plus
  `MeshIntegrity` metrics.
* `load_mesh(path)`: normalized mesh for rendering and modeling use.
* `load_mesh_report(path)`: raw mesh, raw integrity, normalized mesh, mutation
  log, and normalized geometry hash.

Failure behavior:

* The library raises `ValueError` for unparseable files, empty geometry,
  zero-face meshes, or non-finite coordinates. Callers decide their own exit
  code.

## `make_3mf.py`

Script: [`skills/3d-modeling/scripts/make_3mf.py`](../skills/3d-modeling/scripts/make_3mf.py)

```bash
uv run python skills/3d-modeling/scripts/make_3mf.py out.3mf \
  "KnobBody (black)=body.stl" "Pattern (white)=pattern.stl"
```

Inputs:

* Output 3MF path.
* One or more part specs in `name=path/to/part.stl` form. Part meshes must
  already share the same coordinate system.

Outputs:

* Core-spec 3MF with one build object containing one component per input part.
* Stdout lines for each part with vertex count, triangle count, watertightness,
  and final file size.
* Best-effort round-trip reload summary. A skipped round-trip check is reported
  but doesn't fail the already-written file.

Exit codes:

* `0`, 3MF was written.
* `1`, usage is invalid, an STL cannot be loaded, or another uncaught runtime
  error occurs. Non-watertight inputs print warnings but do not fail by
  themselves.

## `make_bambu_3mf.py`

Script: [`skills/3d-modeling/scripts/make_bambu_3mf.py`](../skills/3d-modeling/scripts/make_bambu_3mf.py)

```bash
uv run python skills/3d-modeling/scripts/make_bambu_3mf.py out.3mf \
  "Base (translucent)=base.stl" "Text (CF)=text.stl"
```

Inputs:

* Output Bambu Studio project 3MF path.
* One or more part specs in `name=path/to/part.stl` form.
* Installed Bambu Studio profile tree under `%APPDATA%/BambuStudio`, currently
  targeted at the X2D profile constants in the script.

Outputs:

* Bambu Studio project 3MF with geometry, `project_settings.config`,
  `model_settings.config`, `slice_info.config`, print settings, and per-part
  filament assignment.
* Stdout with resolved app/profile versions, printer, process, filament mapping,
  mesh stats, written file size, bed placement, and internal verification log.

Exit codes:

* `0`, file was written and internal verification passed.
* `1`, usage is invalid, a profile is missing, a mesh load fails, internal
  verification fails, or an uncaught runtime error occurs. Non-watertight inputs
  print warnings but do not fail by themselves.

## `overlay_photo.py`

Script: [`skills/3d-modeling/scripts/overlay_photo.py`](../skills/3d-modeling/scripts/overlay_photo.py)

```bash
uv run python skills/3d-modeling/scripts/overlay_photo.py cand.stl photo.png out.png [z_mm ...]
```

Inputs:

* Candidate STL.
* Near-orthographic top photo.
* Output PNG path.
* Optional z slice heights. Defaults to `3.5 22.0`.

Outputs:

* Overlay PNG with candidate slice boundaries drawn over the segmented photo.
* Stdout residual metrics: mean residual in mm, p90 residual in mm, sample count,
  and overlay path.

Exit codes:

* `0`, overlay was written and metrics printed.
* `1`, missing arguments, photo segmentation failure, mesh load failure, invalid
  z value, or another uncaught runtime error.

## `verify_visual.py`

Script: [`skills/3d-modeling/scripts/verify_visual.py`](../skills/3d-modeling/scripts/verify_visual.py)

```bash
uv run python skills/3d-modeling/scripts/verify_visual.py ref-stl-or-dir cand-stl-or-dir out-prefix \
  [--test T4] [--json]
```

Inputs:

* Reference STL or directory containing STLs.
* Candidate STL or directory containing STLs.
* Output prefix.
* Optional `--test T4` for camera-window position checks.
* Optional `--json` to print the metrics JSON to stdout.

Outputs:

* `<out-prefix>_compare.png`, a composite image with reference row, candidate
  row, and slice overlay row.
* `<out-prefix>_verify.json`, metrics including bounding boxes, rotation,
  pose scores, slice IoU values, layout IoU, boundary F1, mirror flag, optional
  position checks, verdict, and composite path.
* Stdout verdict lines and composite path, or compact JSON when `--json` is set.

Exit codes:

* `0`, comparison assets were written. A mismatch verdict is data in the JSON,
  not a process failure.
* `1`, missing arguments, no mesh found, render failure, JSON write failure, or
  another uncaught runtime error.

## `tools/gen_harness.py`

Script: [`tools/gen_harness.py`](../tools/gen_harness.py)

```bash
uv run python tools/gen_harness.py [--check]
```

Inputs:

* Neutral role files under `skills/roles/*.md`.
* Existing generated files when `--check` is used.

Outputs:

* Without `--check`, writes the skill tree (`skills/3d-modeling/SKILL.md` and
  `roles/*.md`) plus the Claude agent files, then prints the count written.
* With `--check`, writes nothing. It prints `OK` and a file count if generated
  content matches disk, or prints mismatched paths to stderr.

Exit codes: the convention above, with a `--check` mismatch reported as a `1`.

## `tools/build_skill.py`

Script: [`tools/build_skill.py`](../tools/build_skill.py)

```bash
uv run python tools/build_skill.py [--out dist/skills]
```

Inputs:

* The `skills/3d-modeling/` tree, packed verbatim.
* `--out`, output directory for the generated `.skill` zip artifacts. Defaults
  to `dist/skills`.

Outputs:

* One `3d-modeling.skill` zip: `skills/3d-modeling/` packed verbatim, so the
  orchestrator's `SKILL.md` sits at the archive root with `roles/`, `references/`
  and `scripts/` beside it. Because the shipped shape is the repo shape, every
  relative link inside the archive is the same link that resolves in the repo —
  asserted by `test_every_internal_link_resolves_inside_the_archive`.
* All entries use a fixed timestamp (1980-01-01), sorted archive order, and
  `0o644` permissions for deterministic, reproducible builds. `__pycache__/`
  and `.pyc` files are excluded.

## `uv build --wheel` — the Python runtime surface

```bash
uv build --wheel --out-dir dist/wheels
```

The wheel contains the `pipeline`, `designer_toolkit`, and `team_tools` runtime
packages, required sibling modules such as `mesh_io` and `preview`, and the
`design-tool` entry point. It intentionally excludes test modules and does not
claim to be the agent bundle: `SKILL.md`, roles, and references belong to the
`.skill` archive above. Release validation installs the wheel through uv from
an external working directory and runs both `design-tool doctor` and
`design-tool run-job`; the archive tests extract the `.skill` bundle and run its
documented route from the same kind of external directory.
