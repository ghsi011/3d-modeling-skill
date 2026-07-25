# Changelog

All notable changes to the **3d-modeling** skill are documented here.
This project loosely follows [Keep a Changelog](https://keepachangelog.com/) and
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added — test coverage where a promise was unverified

Coverage audit found 85% over the statements the suite imported, but 2,670 lines
across 11 modules touched by no test at all.

- **`check_internal_links.py`** was a CI gate with zero tests — the same shape as
  the drift gate that turned out to pass unconditionally. 7 tests; it also gained
  a `root` parameter (it hardcoded the repo root, so it could not be pointed at a
  fixture) and `.venv`/`dist`/`temp` exclusions, since a local virtualenv's package
  READMEs are not ours to validate and can fail a run CI passes.
- **`make_3mf.py`** writes a deliverable — a malformed 3MF is not a caught error
  but a broken hand-off found at the printer. 5 tests over the OPC members a slicer
  needs, the per-part component structure multi-colour depends on, geometry
  round-tripping, and the non-watertight warning.
- **`run_cadquery_model.py`**: 236 lines, no tests, and its published exit codes
  (3 on timeout) were the least verified promises in the repo. 6 tests, all on the
  core stack since the runner's logic is not CadQuery's.
- **`python -m designer_toolkit`**: 7 smoke tests. The designer is told to call this
  CLI rather than re-author the measurement patterns, so a broken subcommand sends
  the role back to hand-rolling what the toolkit exists to prevent.
- Coverage now reads 74% over 2,159 statements — a truer figure over a bigger base.
  What remains uncovered needs a live GL context or a real Bambu Studio install.

### Changed — one plan file can serve both gates

`print_plan_checks.json` (team_preflight) and `print_plan.json` (team_tools) carried
field-for-field identical edges and support rules, differing only in whether the
version key was `schema_version` or `contract_version`. The contract asked the print
engineer to maintain both and nothing compared them. `team_preflight` now accepts
either name, verified by pointing it at team_tools' own example plan unmodified.

### Fixed — benchmark-driven role corrections

Roles were run blind against parts whose ground truth was withheld, then re-run with
identical inputs after a single change (see AGENTS.md → *Changing a role*).

- **Metrologist, rounded-edge envelopes.** It read a phone's width at "a flat region"
  — but the widest section of a rounded part is at mid-thickness, so jaws on the
  curved shoulder under-read width while the same curvature inflates thickness. The
  delivered width error fell 1.66 mm → 0.36 and length 0.61 mm → 0.01, using 15%
  fewer tokens. The re-run diagnosed the bias by name and resolved to the true
  envelope instead of shipping the biased read.
- **Metrologist, conflicts must ask.** The first run logged three caliper-vs-spec
  conflicts as open questions and stalled at DRAFT without asking anyone. Both
  sources are fallible, so neither wins on principle; a fit-critical conflict now
  goes to the user with both values and the downstream effect. The re-run withheld
  two ambiguous readings entirely rather than shipping one wrong by 2.84 mm.
- **`fdm-design.md`, part-class wall thickness.** The "4 walls" structural default was
  applied to a snap-on case, giving 2.03 mm walls where the real printed case uses
  1.02 — +1.2 mm on width and thickness and ~46% material. That default is for a part
  meant to be stiff and wrong for one meant to flex, and on a part that wraps a
  mating object the wall is a dimension entering the envelope twice.

### Added — the gates enforce what the contract claims

- **`R3_ACCEPTANCE_PROHIBITED`.** The contract says the pipeline must never mark a
  life-safety / medical / load-bearing / regulated job accepted "regardless of what
  any gate, checklist, or verification report reports", and that a `PASS` report for
  such a job is invalid for that reason alone. Nothing enforced it: an R3 job with
  `status: PASS` validated clean. `risk_class` is now a `job_state.md` frontmatter
  field with a checked enum, and R3 + an acceptance verdict is a hard error. Four
  regression tests, including that lower risk classes still pass.
- **`contracts status` is now part of the orchestrator's readiness gate.** It is the
  only check that compares each contract's `revision` against what downstream
  contracts bound to — a `dimensions.md` revised after the plan cited it surfaces as
  `STALE` there and nowhere else — and no role invoked it.
- **Evidence binding stated honestly.** Rule 15 ("hashes bind agents to files") now
  says where binding is real: `artifact_manifest.json`, whose artifacts have their
  SHA-256 recomputed and bbox/component count re-checked. An evidence path written
  only as a Markdown table cell is not resolved by anything — a report citing a file
  that does not exist validates clean — so evidence a gate rests on must also appear
  as a manifest row.

### Changed — contracts are validated where they are actually written

`team_tools` validated JSON exclusively, but v4 defines four of the five contracts
as Markdown and no role is told anywhere to author a JSON mirror. So 393 lines of
validator schema-checked files the pipeline never creates, `validate` reported
four `MISSING_CONTRACT_FILE` warnings on every correct run, and `--require all`
rejected a project built exactly to the contract.

The binding fields were in the Markdown all along: `revision`,
`dimensions_revision`, `print_plan_revision`, `reference_sha256`,
`candidate_stl_sha256` all live in the frontmatter. Each contract is now looked up
as Markdown first, then a JSON mirror if one exists, and:

- **Markdown** gets `validate_contract_header` — identity, version, owner, `job_id`,
  and the integer `revision` the staleness and binding checks compare. Its body is
  provenance, uncertainty and open questions written for the next agent to read;
  a validator walking those rows could only ever confirm that prose is prose.
- **JSON** (`artifact_manifest.json`, a machine-authored `print_plan.json`)
  additionally gets its full structural validator, unchanged.
- `validate_job_state`, `validate_dimensions` and `validate_verification_report`
  are deleted (−393 lines, plus their tests).
- `MISSING_CONTRACT_FILE` is gone. It fired on every correct run, on the same
  `warning_ids` channel that carries `POSSIBLE_UNIT_SCALE_MISMATCH` — which the
  verifier is required to act on. A benchmark designer run called those warnings
  "expected", which is precisely the habit worth not teaching. `validated_paths`
  already records what was read.

Verified against a real agent-produced project: `validate` now reads
`dimensions.md`, `job_state.md` and `artifact_manifest.json` with zero warnings,
`status` reports revisions from the Markdown, and `--require all` passes a
five-contract Markdown project. The verifier role is back to `--require all`.

### Removed — streamlining pass (net −1,534 lines, 16,767 → 15,237)

A six-axis review (docs prose, skill/role text, Python, gate value, repo hygiene,
FDM domain content) looking for duplication, dead weight, and instructions that
cost tokens without changing an outcome.

- `skills/3d-modeling/scripts/backends/` — a `ModelBackend` ABC with cadquery /
  build123d / freecad adapters and a test-only `FakeBackend`. Zero importers: the
  real export path is `designer_toolkit.exporter._write_solid`, which does its own
  dispatch and never knew the package existed.
- `team_tools` `render` and `agent-summary` subcommands (`render.py`, `summary.py`).
  No role, agent definition or reference ever invoked them, and no rendered output
  is committed anywhere. `render` generated Markdown *from* JSON, inverting a
  pipeline whose Markdown is the authored side.
- `references/preflight-checklist.md` — 135 lines with zero inbound references,
  contradicting `fdm-design.md` on chamfer size and `troubleshooting.md` on
  calibration order. Its correct thread number and its six-step calibration order
  (which included the max-volumetric-speed step the live file omitted) were
  harvested into the files that are actually loaded.
- Half of `references/build123d-patterns.md` (192 → 84): unreferenced, and the
  backend-neutral half was a verbatim clone of `cadquery-patterns.md`. Its sample
  called a `finalize(strict=True)` signature that does not exist.
- Dead Python: `verify_visual.footprint_iou` (superseded by `pose_score`),
  `MeshIntegrity.non_manifold_edge_count` (computed on every export, read by
  nothing), an `engine=` parameter no caller passes, a `team_tools/__init__`
  re-export nothing imports, and three copies of the same `_as_mesh` coercion.
- Repeated exit-code blocks, harness invocation stated in three files, a hand-run
  OpenCode checklist duplicating what `test_gen_harness.py` asserts, and per-extra
  `pyproject` comments duplicating the README table.
- `.skill` bundles no longer ship the test suite and fixtures — 412 KB → 141 KB per
  artifact, across six artifacts. Nothing in a shipped skill ran them.

### Fixed

- Connected-component counts are now computed in pure numpy (label propagation over
  face adjacency) instead of `trimesh.Trimesh.split`. `split` needs scipy to label
  components and networkx to close any component with a hole; on a core-only install
  it raises, and both call sites swallowed that into "1 component" — so a two-body
  export could pass `is_single_watertight_solid()` and the artifact manifest's
  `expected_components` check silently observed nothing. Verified to match `split`
  exactly on 50 meshes (welded, unwelded, holey, corner-touching, multi-body).
  Affects `mesh_io.compute_integrity`, `designer_toolkit.exporter` /`metrics`, and
  `team_tools` `COMPONENT_COUNT_MISMATCH`.
- `designer_toolkit.metrics.datum_features` now raises a single `ImportError` naming
  the `section` extra when its stack is absent, instead of surfacing trimesh's
  deferred `ModuleNotFoundError` from several frames down, one missing package at a time.
- The `visual` extra was missing `networkx` and `rtree`, which `verify_visual.slice_union`
  reaches through `Path2D.polygons_full`. Its catch-all turned the resulting ImportError
  into `None` — read downstream as "empty slice", so a part sliced against itself scored
  IoU 0.0 instead of 1.0 and every overlay/alignment number silently collapsed. The extra
  is now complete and `slice_union` checks the stack before the catch-all, which keeps
  doing its real job (genuinely degenerate sections).
- Repository URLs in `pyproject.toml` and `CHANGELOG.md` pointed at a `github.com/Idan/…`
  org that does not exist; they 404'd.
- The generated-harness drift gate never fired. CI ran `pytest` before
  `gen_harness.py --check`, and a test shelled out to the generator *without*
  `--check`, rewriting the working tree — so the check compared regenerated files
  against themselves and passed unconditionally. Reproduced by drifting a role
  source: `--check` alone exited 1, after `pytest` it exited 0. The test now
  compares in memory and writes nothing, and `--check` runs before `pytest`.
- `manifest_checks._compare_extents` used `elif`, so a near-25.4× scale flag on any
  one axis suppressed `BBOX_MISMATCH` on every axis — a declared bbox 5× wrong on
  another axis was reported as a warning, not an error. The 25.4× promotion also
  swept all axes, so an unrelated axis landing near 25.4× could promote a warning
  to a hard error. Both fixed, with regression tests in both directions.
- `mesh_io._components` swallowed every failure into "1 component", the exact
  silent multi-body pass `connected_component_count` was written to prevent. It now
  raises a `ValueError` naming the vertex/face counts; the CLI callers already
  surface `ValueError` cleanly.
- `designer_toolkit`'s overhang self-check could report clean where the authoritative
  gate FAILs — measured at 0.00 mm² vs 1873.15 mm² on a 46° face — while a comment
  claimed lockstep with a `team_preflight` default that does not exist (the field is
  required per-rule). `finalize` now records whether the threshold came from the
  caller or the toolkit default, and re-screens at the bare 45° value to announce
  the gap when they differ.
- FDM guidance corrected against the source corpus, all five independently
  re-confirmed: printed threads floored at `M8 (≥1/8")` — 8 mm glossed as 3.175 mm,
  which forced heat-set inserts onto every M4–M6 boss the sources say prints fine;
  30–40% infill against a documented 15–20%; warp-relief cuts specified at 1 mm deep
  where deeper *increases* warp (0.5 mm); bottom chamfer stated three
  incompatible ways across two files; and a 0.8 mm wall rule where 0.8 mm is the
  geometric floor and 1 mm is the design rule.
- `team_tools.contracts` now exits `2` on a project directory that does not exist. Every
  canonical contract is "absent" either way, so a typo'd path was indistinguishable from a
  clean early-phase project and validated `PASS` with exit `0`.
- The README framed the pipeline as Claude Code subagents, though the roles are generated
  from `skills/roles/` into three harnesses. Rewritten harness-neutral, with per-harness
  entry points and the setup prompt branching on the harness rather than assuming one.

### Added

- `team_tools.contracts validate --require <contract>[,…]|all` — names contracts whose
  absence is a `REQUIRED_CONTRACT_MISSING` **error** rather than a warning, so the exit
  code becomes a sound gate. Absence stays a warning by default because mid-pipeline a
  project legitimately holds only the contracts its phase has produced. The names are
  recorded in the receipt's new `required_contracts` field; an unknown name is a usage
  error (exit 2) rather than a silently dropped requirement. The verifier and designer
  role definitions now pass it.
- `section` optional extra (`scipy`, `networkx`, `shapely`, `rtree`) — the trimesh
  soft dependencies the cross-section path needs for `datum_features` and the datum
  blocks `bundle.finalize` derives from it. Kept separate from `visual` so the datum
  path does not pull in pyrender/PyOpenGL and a GL context.
- CI `section` job running the designer-toolkit suite with that extra installed. The
  main matrix stays core-only and now also proves the tooling degrades honestly there.

### Removed

- Deleted the retired historical `skills/team-design.md` design document after migrating live
  runtime contract language into `skills/3d-modeling/references/team-contracts-v4.md`.
- Retired the former single-entry `skills/3d-modeling/SKILL.md`; the invocable surface is now
  the five-role file-contract pipeline while `skills/3d-modeling/references/` and
  `skills/3d-modeling/scripts/` remain the shared library.

## [0.1.0] — 2026-07-25

Initial public import of the multi-agent 3D-modeling skill. This release is the
product of a real-part optimization program: agents ran **blind** (photos +
calipers + public specs only) against **held-out** ground truth (the user's final
3MFs / a downloaded reference model) on three physical parts — a Pixel 7 case, a
Garmin Fenix 7X charging dock, and a broom-holder clip. Each single pipeline step
was scored against its oracle; a fix was promoted only after re-test on a
different part with **no regression** (anti-overfit gate), with the scorer kept
separate from the editor.

### Added — five-role, file-contract pipeline

- A five-role Claude Code subagent pipeline that turns a request + reference
  photos/calipers into a verified, print-ready model. Roles communicate **only**
  through project contract files and source evidence, never chat summaries:
  - **orchestrator** — routes solo-vs-team, owns job state and phase gates,
    dispatches specialists, never authors geometry.
  - **metrologist** — converts photos/calipers/specs into datum-based ground
    truth (`dimensions.md`); visually accepts the blind mating reference.
  - **print-engineer** — issues the pre-design manufacturing contract
    (`print_plan.md`) and the post-verification coupon / slicing / print-order /
    field-test plan.
  - **designer** — builds one blind reference or one candidate from the
    contracts, with mandatory FDM-aware design; may not accept its own work.
  - **verifier** — a fresh, independent context that re-imports the exported STL
    and runs all seven Phase-4 checks, including actual render + photo-overlay
    inspection.
- A **solo monolith** entry point (`skills/3d-modeling/SKILL.md` +
  `references/fdm-design.md`) for simple, single-part, non-fit-critical jobs. The
  solo skill was held byte-identical through the whole optimization program.
  (`SKILL.md` retired — see Unreleased; `references/fdm-design.md` remains.)
- Role charters and design rationale in `skills/team-design.md` (historical; the file
  was deleted afterwards — see Unreleased — and does not exist in any commit);
  the **normative** runtime contract and gate schema in
  `skills/3d-modeling/references/team-contracts-v4.md`.

### Added — deterministic tooling

- **`team_preflight.py`** — deterministic support/geometry predicate gate over
  the exported STL under a stated rigid transform.
- **`team_tools/`** — a contract-automation CLI (`validate` / `hash` / `status` /
  `render`) plus an `artifact_manifest`. It auto-computes **SHA-256** and binds
  artifacts to a contract **revision** (no agent-entered hashes), detects stale
  dependencies, and validates finite numbers, enums, IDs, foreign keys, and
  path-safety, including a 25.4× unit-scale (inch→mm) check.
- **`mesh_io.py`** — raw-vs-normalized mesh reporting so a genuine defect in an
  exported file is visible on the *raw* read before any repair runs (P-14).
- Backend runners and authoring helpers: `run_cadquery_model.py`, `preview.py`,
  `make_3mf.py`, `make_bambu_3mf.py`, and the shared visual tools
  `overlay_photo.py` / `verify_visual.py`.

### Added — `designer_toolkit` (Phase-4 tooling, agentic→code speedup)

- **`designer_toolkit/`** — the deterministic Phase-4 work the designer and
  verifier used to re-author (and re-debug) every job, now a tested library they
  **call**: `export_and_hash` (export + re-import + hash — measures the REAL
  delivered geometry on the normalized mesh, killing stale-hash and phantom-shell
  bugs), `measure` / `datum_features` / `overhang_area` (bbox/volume/integrity;
  section holes in MODEL coordinates via `plane_transform`; overhang at the SAME
  −0.73 screen as the gate), `interference` / `insertion_sweep` (boolean fit on
  the exported mesh), `fit_coupon` (parametric multi-lane coupon from the plan's
  interfaces), `render` (ref-vs-candidate view grid + section, pyrender-gated),
  and a one-call `finalize` that assembles the whole evidence bundle. Also a CLI
  (`python -m designer_toolkit …`).
- **Why:** move the mechanical measuring out of per-job agent code to shorten the
  design step; the agent writes only the parametric geometry and the judgment
  calls (`finalize` leaves `visual_accept` / `fit_band_ok` unset on purpose — a
  green mechanical bundle is necessary, not sufficient).
- Mesh/fit/coupon paths are CI-safe (need `manifold3d` for booleans, no CAD
  kernel); the CadQuery export path is lazy and `render` is deferred. 14 tests;
  full suite **139** as of this release. Surfaced in the designer/verifier slices and
  `cadquery-patterns.md` via `references/designer-toolkit.md`.

### Hardened — preflight gate (Sprint 1)

- Reject **non-finite / NaN / ±Inf / None / bool / malformed** numeric samples
  that previously *false-passed* the gate (confirmed reproduction, now rejected).
- Fix a `float(None)` crash on a null read-cap (S-03); it now raises a clean,
  field-named error only inside `SELF_SUPPORT_REQUIRED`.
- Validate finite, rigid transforms and **contain evidence paths** (reject `..`,
  absolute, and symlink escapes).
- **Honestly relabel** the support audit as a "downward-facing-surface screen":
  it is a crude downward-normal test, *not* a supportability proof (see
  meta-finding). No functional-correctness claim is made by passing it.

### Changed — H-03: fit-strategy ownership

- Moved fit/clearance ownership from the metrologist to the **print engineer**.
  The metrologist reports as-observed geometry + uncertainty only; the print plan
  now declares fit through a structured **per-interface `fit_type` enum**,
  enforced by a `validate-interfaces` gate. Backward-compatible: `interfaces` is
  optional (absent → skipped).

### Fixed — two validated design-step spec fixes

- **Fillet / OCC robustness fallback ladder** (design-step optimization #1): a
  graduated retry strategy for fillet/chamfer operations that otherwise abort the
  OCC kernel, so a single fragile edge no longer sinks an otherwise-valid model.
- **45° self-support screen margin** (design-step optimization #2): the
  downward-facing-surface screen threshold was corrected to **-0.73**
  (= -sin 47°), giving a ~2° margin past the 45° self-support limit. This stops
  the screen from false-flagging legitimate 45° chamfer faces while still
  catching genuinely unsupported overhangs. Value validated, not guessed.

Both fixes were re-tested across 3 parts / 3 fit types with **zero regression**;
the bounded-fit-band principle propagated to real Pixel-case geometry at
0.20 mm/side (in-band).

### Notes / meta-finding

- **Executable gates ≠ functional correctness.** Passing a deterministic gate
  (schema, finite-number, hash/revision-binding, path-safety, `team_preflight`)
  is *necessary evidence, not proof* that a part will fit, print, or survive its
  load — that remains an agent judgment call. This was corroborated
  independently by an external review and by the design step (④) remaining the
  quality frontier: a real contact/motion model is deferred.
- Deferred (out of the v0.1.0 scope): a `cad_runner` resource governor, a
  contact/motion engine, a fail-closed 3MF writer, a Bambu adapter, camera
  calibration, and a golden-fixture regression suite.

[0.1.0]: https://github.com/ghsi011/3d-modeling-skill/releases/tag/v0.1.0
