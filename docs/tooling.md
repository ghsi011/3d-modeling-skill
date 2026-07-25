# Tooling reference

This page documents the deterministic tool surfaces used by the 3D modeling
team pipeline. Run repository tools from the repo root unless a command says
otherwise. The shared modeling scripts live in
[`skills/3d-modeling/scripts/`](../skills/3d-modeling/scripts/).

Install the core dependencies before using the contract and mesh tools:

```bash
pip install trimesh numpy pillow manifold3d
```

Optional features need extras from `pyproject.toml`: `cad` for CadQuery,
`render` for preview rendering, `visual` for photo and reference comparison,
`bambu` for Bambu project 3MF verification, and `mcp` for the local stdio MCP
bridge.

Exit code convention across these tools:

| Code | Meaning |
| --- | --- |
| 0 | Command completed successfully. For validation commands, the checked gate passed. |
| 1 | The command ran but the gate failed, output verification failed, or an uncaught runtime error occurred. |
| 2 | Command line usage failed, an input contract was malformed, a file could not be opened, or a strict preflight guard rejected the input. |
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

Run from `skills/3d-modeling/scripts/`, or put that directory on `PYTHONPATH`.
This package validates the structured JSON mirror of the v4 team contracts.
Passing it proves contract structure, identifiers, declared hashes, and revision
bindings only. It doesn't prove geometric or manufacturing correctness.

### `validate`

```bash
cd skills/3d-modeling/scripts
python -m team_tools.contracts validate path/to/project [--output receipt.json] [--timestamp ISO-8601]
```

Inputs:

* Project directory containing the contract JSON files.
* Optional `--output` receipt path.
* Optional `--timestamp`, injected into the receipt instead of reading wall
  clock time.

Outputs:

* Canonical JSON receipt with tool version, schema version, job id, validated
  paths, observed revisions, computed SHA-256 values, per-contract results,
  warning ids, error ids, issues, timestamp, invocation, and disclaimer.

Exit codes:

* `0`, `results.overall` is `PASS`.
* `1`, one or more contract results failed.
* `2`, a contract loader or filesystem error prevented validation.

### `hash`

```bash
cd skills/3d-modeling/scripts
python -m team_tools.contracts hash path/to/project [--output hashes.json] [--timestamp ISO-8601]
```

Inputs:

* Project directory.
* Optional output path and injected timestamp.

Outputs:

* Canonical JSON receipt with recomputed contract SHA-256 values, recomputed
  artifact SHA-256 values, `hash_mismatches`, timestamp, invocation, and note.

Exit codes:

* `0`, no declared artifact hash mismatches were found.
* `1`, one or more declared artifact hashes differ from bytes on disk.
* `2`, project loading or filesystem access failed.

### `status`

```bash
cd skills/3d-modeling/scripts
python -m team_tools.contracts status path/to/project [--json] [--output status.txt]
```

Inputs:

* Project directory.
* `--json` for machine-readable rows. Without it, output is aligned text.
* Optional output path.

Outputs:

* Text or canonical JSON rows for each contract and stale or invalidated
  downstream binding. Rows include `contract`, `status`, and `detail`.

Exit codes:

* `0`, no row has `STALE`, `INVALIDATED`, or `UNREADABLE`.
* `1`, at least one such row is present.
* `2`, project loading or filesystem access failed.

### `render`

```bash
cd skills/3d-modeling/scripts
python -m team_tools.contracts render path/to/contract.json [--output contract.md]
```

Inputs:

* Path to one structured contract JSON file.
* Optional Markdown output path.

Outputs:

* Stable, git-diff-friendly Markdown rendering of the contract.

Exit codes:

* `0`, Markdown was written or printed.
* `2`, the file cannot be read, parsed, or rendered.

### `agent-summary`

```bash
cd skills/3d-modeling/scripts
python -m team_tools.contracts agent-summary path/to/project [--output summary.txt]
```

Inputs:

* Project directory.
* Optional output path.

Outputs:

* Compact informational text: mode, state, contract revisions, artifact counts,
  stale or invalidated binding count, blocking error count, warning count, and a
  pointer back to the authoritative JSON contracts and validation receipt.

Exit codes:

* `0`, summary was written or printed.
* `2`, project loading or filesystem access failed.

## `python -m designer_toolkit`

Module: [`skills/3d-modeling/scripts/designer_toolkit/__main__.py`](../skills/3d-modeling/scripts/designer_toolkit/__main__.py)

Run from `skills/3d-modeling/scripts/`, or put that directory on `PYTHONPATH`.
Every subcommand prints indented JSON to stdout. The CLI doesn't catch toolkit
exceptions, so success returns `0`, argparse usage errors return `2`, and runtime
errors normally return `1` with a Python traceback.

### `measure`

```bash
python -m designer_toolkit measure body.stl
```

Inputs: one STL path.

Outputs: JSON measurement report from the re-imported mesh, including bounding
box, volume, watertightness, component count, and related mesh metrics.

Exit codes: `0` on measurement success, `1` on load or metric failure, `2` for
usage errors.

### `overhang`

```bash
python -m designer_toolkit overhang body.stl [--threshold -0.73] [--min-z 0.3]
```

Inputs: STL path, optional downward normal threshold, optional minimum z cutoff.

Outputs: JSON object with `overhang_mm2`.

Exit codes: `0` on success, `1` on mesh or metric failure, `2` for usage errors.

### `datums`

```bash
python -m designer_toolkit datums body.stl --z 1.0 [--normal 0,0,1]
```

Inputs: STL path, required datum plane z value, optional comma-separated normal.

Outputs: JSON object with `features`, each serialized from the datum feature
extractor.

Exit codes: `0` on success, `1` on load or extraction failure, `2` for missing
or invalid arguments.

### `interference`

```bash
python -m designer_toolkit interference part.stl ref.stl
```

Inputs: candidate STL and reference or mating STL.

Outputs: JSON object with `interference_mm3`.

Exit codes: `0` on success, `1` on mesh or boolean failure, `2` for usage
errors.

### `sweep`

```bash
python -m designer_toolkit sweep part.stl ref.stl --travels 5,15,25,35 [--axis 0,0,-1]
```

Inputs: candidate STL, reference STL, required comma-separated travel distances,
and optional comma-separated axis.

Outputs: JSON object with `steps`, one serialized insertion sweep result per
travel distance.

Exit codes: `0` on success, `1` on mesh or boolean failure, `2` for usage
errors.

### `export`

```bash
python -m designer_toolkit export body.stl [--out out/body.stl]
```

Inputs: source STL path and optional output path. If `--out` is omitted, the
source path is reused.

Outputs: JSON export report with hash and re-import facts. The internal
`integrity` object is omitted from CLI output.

Exit codes: `0` on success, `1` on export or re-import failure, `2` for usage
errors.

### `coupon`

```bash
python -m designer_toolkit coupon --plan plan.json --out coupon.stl
```

Inputs: plan JSON. The command accepts either a JSON object with `interfaces` or
a raw interface list. `--out` is required.

Outputs: JSON object with written `stl` path and `legend` rows. The command also
writes the coupon STL.

Exit codes: `0` on success, `1` on bad plan content or coupon generation
failure, `2` for missing arguments.

### `finalize`

```bash
python -m designer_toolkit finalize body.stl [--plan plan.json]
```

Inputs: STL path and optional plan JSON. Plan keys can include `out_stem`,
`datums`, `reference`, `insertion`, `orientation_transform`, and
`overhang_threshold`.

Outputs: JSON readiness bundle from `designer_toolkit.bundle.finalize`, including
export and hash facts, overhang area, datum features, optional seated
interference, optional insertion sweep, and readiness skeleton fields that still
need human judgment.

Exit codes: `0` on success, `1` on bundle generation failure, `2` for usage
errors.

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

Exit codes:

* `0`, preview image was written.
* `1`, mesh loading failed or rendering raised an uncaught exception.
* `2`, argparse usage failed or `--strict` rejected a non-watertight mesh.

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

OpenCode registration is generated into root `opencode.json` as the
`3d-modeling-tools` local server. For Claude Code, register the same stdio
server from the repository root with this one-liner:

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

* Without `--check`, writes generated Claude agent files, role skill files,
  OpenCode agent/config files, and generic OpenAI YAML files, then prints the
  count written.
* With `--check`, writes nothing. It prints `OK` and a file count if generated
  content matches disk, or prints mismatched paths to stderr.

Exit codes:

* `0`, files were written successfully, or `--check` found no mismatches.
* `1`, `--check` found mismatches, role parsing failed, required role metadata
  was missing, generated file reads failed, or another uncaught runtime error
  occurred.
* `2`, argparse usage failed.

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

* Five per-role `<role>.skill` zips, each with `SKILL.md` at the archive root,
  plus `agents/`, `references/`, and `scripts/` sub-trees.
* One `3d-modeling-team.skill` bundle that aggregates all five roles under
  `roles/<role>/` alongside the shared `references/` and `scripts/`.
* All entries use a fixed timestamp (1980-01-01), sorted archive order, and
  `0o644` permissions for deterministic, reproducible builds. `__pycache__/`
  and `.pyc` files are excluded.

Exit codes:

* `0`, all artifacts were written.
* `1`, an uncaught runtime error occurred.
* `2`, argparse usage failed.
