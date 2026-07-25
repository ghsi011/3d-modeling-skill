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
| 3 | Timeout, only used by `run_cadquery_model.py`. |

Individual tools narrow or extend this table below.

## `team_preflight.py`

Script: [`skills/3d-modeling/scripts/team_preflight.py`](../skills/3d-modeling/scripts/team_preflight.py)

Runs deterministic non-acceptance gates for the team pipeline. It emits sorted,
indented JSON to stdout unless `--output` is provided. All subcommands return
`0` when the emitted JSON has `"result": "PASS"`, `1` when it has
`"result": "FAIL"`, and `2` for usage, unreadable files, malformed JSON, or
schema errors raised before a gate result can be written.

### support, actual command `support-audit`

```bash
python skills/3d-modeling/scripts/team_preflight.py support-audit \
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

### validate, actual command `validate-receipts`

```bash
python skills/3d-modeling/scripts/team_preflight.py validate-receipts \
  --stl candidate.stl \
  --plan print_plan_checks.json \
  --readiness readiness.json \
  [--output receipt_validation.json]
```

Inputs:

* `--stl`, exported STL that readiness claims to describe.
* `--plan`, `print_plan_checks.json` with edge and support expectations.
* `--readiness`, readiness receipt with candidate hashes, edge samples, and
  support audit paths.
* `--output`, optional JSON output path.

Outputs:

* JSON kind `receipt-validation`.
* Candidate STL hash, plan hash, sorted edge ids, sorted support rule ids,
  collected error strings, and `PASS` or `FAIL`.

Exit codes:

* `0`, hashes match, edge and support id coverage is complete, samples satisfy
  plan rules, and support audit files bind to the same STL, plan, rule, and
  transform.
* `1`, validation ran and found one or more receipt errors.
* `2`, an input file cannot be read, JSON is invalid, or required top-level
  structures are malformed.

### interfaces, actual command `validate-interfaces`

```bash
python skills/3d-modeling/scripts/team_preflight.py validate-interfaces \
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

Invoke by absolute path from wherever the job is: `python <skill>/scripts/dt.py <command>`.
It puts its own directory on `sys.path`, so command-line paths resolve against your working
directory rather than the skill's. The module form (`python -m designer_toolkit ...`) still
works but requires the working directory to be `skills/3d-modeling/scripts/`, which is what
made every measured designer run write a shim instead.
This package validates the v4 team contracts: the four Markdown ones through their
frontmatter (identity, revision, binding hashes), and the JSON ones structurally.
Passing it proves contract structure, identifiers, declared hashes, and revision
bindings only. It doesn't prove geometric or manufacturing correctness.

### `validate`

```bash
cd skills/3d-modeling/scripts
python -m team_tools.contracts validate path/to/project [--require CONTRACT] [--output receipt.json] [--timestamp ISO-8601]
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
  comma-separated. An unknown name is a usage error (exit `2`) rather than a
  silently dropped requirement.
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
python -m team_tools.contracts hash path/to/project
python -m team_tools.contracts status path/to/project
```

Both take a project directory and print to stdout by default; run `--help` for
the output, timestamp, and `--json` flags.

| Command | What it proves | Exits `1` when |
| --- | --- | --- |
| `hash` | Contract and artifact SHA-256 values recomputed from the bytes on disk, never trusting a hash written into a contract. | A declared artifact hash differs from the bytes on disk. |
| `status` | Each contract's revision, plus the downstream bindings that later revisions have made stale. | A row is `STALE`, `INVALIDATED`, or `UNREADABLE`. |

## `dt.py` — the toolkit launcher

Module: [`skills/3d-modeling/scripts/designer_toolkit/__main__.py`](../skills/3d-modeling/scripts/designer_toolkit/__main__.py)

Run from `skills/3d-modeling/scripts/`, or put that directory on `PYTHONPATH`.
Every subcommand prints indented JSON to stdout. The CLI doesn't catch toolkit
exceptions, so success returns `0`, argparse usage errors return `2`, and runtime
errors normally return `1` with a Python traceback.

### `commission`

```bash
python <skill>/scripts/dt.py commission (--model model.py | --stl body.stl) --plan plan.json   --out DIR --job-id JOB --updated-utc ISO8601 [--reference ref.stl] [--no-render] [--no-receipts]
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
python <skill>/scripts/dt.py coupon --plan plan.json --out coupon.stl
python <skill>/scripts/dt.py doctor
python <skill>/scripts/dt.py plan template --bbox X Y Z --out print_plan_checks.json
python <skill>/scripts/dt.py plan check print_plan_checks.json
```

Inputs: plan JSON. The command accepts either a JSON object with `interfaces` or
a raw interface list. `--out` is required.

Outputs: JSON object with written `stl` path and `legend` rows. The command also
writes the coupon STL.

## `preview.py`

Script: [`skills/3d-modeling/scripts/preview.py`](../skills/3d-modeling/scripts/preview.py)

```bash
python skills/3d-modeling/scripts/preview.py model.stl [output.png] \
  [--views iso|multi] [--title "Title"] [--subtitle "Text"] \
  [--resolution 600] [--strict]
```

Inputs:

* STL path.
* Optional output PNG path. Default is `<stl_name>_preview.png`.
* `--views iso` for one isometric image or `--views multi` for a six-view sheet.
* Optional title, subtitle, and per-view resolution.
* `--strict` to fail before rendering if the normalized mesh is not watertight.

Outputs:

* Text summary with model path, bounding box, triangle count, watertight warning
  if present, and final preview path.
* PNG preview image.

Exit codes: the convention above, with `--strict` rejecting a non-watertight
mesh as a `2` rather than a `1`.

## `run_cadquery_model.py`

Script: [`skills/3d-modeling/scripts/run_cadquery_model.py`](../skills/3d-modeling/scripts/run_cadquery_model.py)

```bash
python skills/3d-modeling/scripts/run_cadquery_model.py path/to/model.py \
  [--preview] [--strict] [--views iso|multi] [--timeout 180]
```

Inputs:

* CadQuery Python script path.
* `--preview`, render a preview for each STL written by the script.
* `--strict`, fail if any STL is not watertight, or if no STL is produced.
* `--views`, preview layout when rendering.
* `--timeout`, seconds before killing the model subprocess.

Outputs:

* One JSON object on stdout with `success`, script path, discovered STL, 3MF,
  STEP, and STP outputs, preview paths when requested, aggregate watertightness,
  captured stdout, captured stderr, and child return code.

Exit codes:

* `0`, the CadQuery script completed and all requested post-checks passed.
* `1`, the CadQuery script failed, preview failed, or `--strict` rejected output.
* `2`, the interpreter or script path could not be launched.
* `3`, the subprocess timed out.

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
python skills/3d-modeling/scripts/make_3mf.py out.3mf \
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
python skills/3d-modeling/scripts/make_bambu_3mf.py out.3mf \
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
python skills/3d-modeling/scripts/overlay_photo.py cand.stl photo.png out.png [z_mm ...]
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
python skills/3d-modeling/scripts/verify_visual.py ref-stl-or-dir cand-stl-or-dir out-prefix \
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

## `tools/mcp_server.py`

Script: [`tools/mcp_server.py`](../tools/mcp_server.py)

Install the MCP extra before registering the bridge:

```bash
pip install -e ".[mcp]"
```

Register the stdio server from the repository root with this one-liner:

```bash
claude mcp add 3d-modeling-tools -- python tools/mcp_server.py
```

Run directly when a host needs to launch the stdio server itself:

```bash
python tools/mcp_server.py
```

Inputs:

* Stdio MCP requests from the host harness.
* Project paths and tool arguments forwarded to contract, preflight, and toolkit
  functions.

Outputs:

* MCP tool responses over stdio.
* No generated project files unless the called tool writes them.

Exposed tool families:

* `team_preflight_*`, support, receipt, and interface preflight checks.
* `contracts_*`, contract validation, hashing, and status rows.
* `designer_*`, mesh measurement and Phase-4 readiness bundle helpers.

Exit codes:

* `0`, the stdio server starts and exits normally after the MCP transport
  closes.
* Non-zero, Python cannot import required dependencies, tool initialization
  fails, or the stdio transport exits with an uncaught runtime error.

## `tools/gen_harness.py`

Script: [`tools/gen_harness.py`](../tools/gen_harness.py)

```bash
python tools/gen_harness.py [--check]
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
python tools/build_skill.py [--out dist/skills]
```

Inputs:

* Repository `skills/` tree. Each role directory (`3d-orchestrator`,
  `3d-metrologist`, `3d-designer`, `3d-verifier`, `3d-print-engineer`) must
  contain a `SKILL.md` at its root. Shared references and scripts under
  `skills/3d-modeling/references/` and `skills/3d-modeling/scripts/` are
  included in every per-role bundle.
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
