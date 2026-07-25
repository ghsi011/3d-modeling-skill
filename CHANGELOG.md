# Changelog

All notable changes to the **3d-modeling** skill are documented here.
This project loosely follows [Keep a Changelog](https://keepachangelog.com/) and
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
