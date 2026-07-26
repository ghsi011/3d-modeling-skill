# Team pipeline runtime contracts v4

**Normative status: this file is the sole normative runtime contract and gate schema for the
five-role pipeline.** Do not build runtime contracts from historical design notes or copied
templates — use the schemas below.

This is the compact runtime schema for the five-role pipeline.

Rules:

- Tables may add rows but may not remove columns.
- Every contract uses millimetres unless a row says otherwise.
- `A` = direct measurement, `B` = authoritative/corroborated, `C` = image-derived,
  `D` = assumption.
- Hashes bind agents to files. Chat is never a contract. Binding is only real where the
  tooling recomputes it, which today means `artifact_manifest.json`: every artifact listed
  there has its SHA-256 recomputed from the bytes on disk and its declared bbox and component
  count checked against the re-imported mesh. An evidence path written only as a table cell in
  a Markdown body is **not** verified — nothing resolves it, and a report citing a file that
  does not exist validates clean. So any evidence a gate actually rests on (a render, an
  overlay, a preflight receipt) must also appear as an artifact row in the manifest; otherwise
  the citation is prose, and should be read as prose.
- Compact means fewer repeated words and images, not fewer datums, sources, checks, or
  uncertainties.
- Shared references and scripts stay in `skills/3d-modeling/references/` and
  `skills/3d-modeling/scripts/`. Role slices link to them by relative path; do not copy,
  fork, or re-author shared workflow/tooling patterns. Reading a shared reference does not
  grant write authority over another role's contract.

## `job_state.md`

```markdown
---
contract: job-state
contract_version: 4
job_id: <slug>
revision: <integer>
owner: orchestrator
mode: PIPELINE
profile: DIRECT | FITTED | FULL
state: INTAKE | METROLOGY | REFERENCE_BUILD | REFERENCE_ACCEPTANCE | PRINT_PLAN | CANDIDATE_BUILD | INDEPENDENT_VERIFICATION | PRINT_PREP | FINAL_PREP_REVIEW | DELIVERY | BLOCKED
backend: cadquery | build123d | freecad
active_candidate: <id-or-none>
freecad_owner: none | <job_id>/<commission>/<acquired-utc>
updated_utc: <iso-8601>
---

# Job state

## Route
<criterion and reason>

## Bound inputs
| Contract/evidence | Revision/hash | Status |
|---|---|---|

## Gates
| Gate | Required receipt | Result | Evidence |
|---|---|---|---|

## Dispatches
| ID | Role/commission | Authorized inputs | Required output | Budget min | Status |
|---|---|---|---|---:|---|

## Open user questions
| ID | Question | Blocks |
|---|---|---|
```

The profile decides which phases run. `DIRECT`: every design-driving dimension is stated, nothing is recreated from evidence and a
template covers the shape, so `METROLOGY`, `REFERENCE_BUILD` and `REFERENCE_ACCEPTANCE` have
no input and the orchestrator does the whole job in its own turns without dispatching — its
`## Route` recording "built and checked by the orchestrator; no independent fresh-context
verification". `FITTED`: one measured real object, so the blind rebuild happens inside the
candidate build and its overlay inside verification. `FULL`: multi-part/moving mechanisms,
safety/load consequences, several independent interfaces, multi-colour alignment, or parallel
candidates -- every phase runs, except that `METROLOGY` is skipped when the job carries no
photographs, measurements or real object: the metrologist reconciles sources, and given one
source it can only transcribe. The orchestrator then writes `dimensions.md` itself and records
in `job_state.md` that no metrologist was dispatched. See [`../SKILL.md`](../SKILL.md) for the
deciding question and the full sequences. `PRINT_PLAN` and `INDEPENDENT_VERIFICATION` run
under every profile.

**A multi-part job is many projects, not one directory with many STLs.** Contracts resolve
as `<project-dir>/<name>` with no search below it, and `dt.py audit` reads
`<project>/job_state.md`, so every part needs its own directory carrying its own
`job_state.md`, `dimensions.md`, `print_plan_checks.json` and receipts. Derive those slices
from one table rather than writing each by hand -- a seven-part job that hand-maintains
seven copies of the same job id and revision will drift, and `contracts status` reports the
drift only after it has happened. The parent directory holds the brief and the table; it is
not itself a project and `validate` should not be pointed at it.

`job_state.md`'s `## Route` section also records the job's consequence/risk class from the
orchestrator's Consequence and escalation gate (`R0_DECORATIVE` / `R1_LOW_CONSEQUENCE` /
`R2_ENGINEERING_REVIEW` / `R3_PROHIBITED_AUTONOMOUS_ACCEPTANCE`; see
[`../SKILL.md`](../SKILL.md)), its rationale, any named
human reviewer requirement, and the claims the pipeline is prohibited from making for that
class. Record the same enum as a `risk_class` field in `job_state.md`'s frontmatter: that is
what makes the R3 prohibition machine-enforceable. `validate` rejects an unknown value, and
rejects any project whose `job_state` declares `R3_PROHIBITED_AUTONOMOUS_ACCEPTANCE` while its
`verification_report` claims `PASS`, with `R3_ACCEPTANCE_PROHIBITED` — the prohibition is not
advisory. Absence of the field remains valid for backward compatibility, but a job with no
`risk_class` cannot be checked for it, so omit it only for work that is plainly `R0`.

For `freecad` backend work, the orchestrator acquires a repo-wide mutation lease at
`.claude/3d-freecad.lock` before any FreeCAD MCP call that can mutate a document. The lock
records `job_id`, commission, and acquisition time; `job_state.md` mirrors the same value in
`freecad_owner` while the lease is held and resets it to `none` when released. There is exactly
one active FreeCAD designer commission across all jobs, including reference and candidate work.
FreeCAD reference modeling completes and passes metrologist review before candidate modeling
continues in the same `.FCStd`. The verifier works from staged exported STL/renders in a fresh
context and never needs the FreeCAD mutation lease. CadQuery/build123d reference work remains
serial before print planning; after that gate, parallel candidates may run only in isolated
folders with no shared filenames, import state, or output directories.

## `dimensions.md`

```markdown
---
contract: dimensions
contract_version: 4
job_id: <slug>
revision: <integer>
owner: metrologist
status: DRAFT | REFERENCE_REVIEW | ACCEPTED | BLOCKED
updated_utc: <iso-8601>
---

# Dimensions

## Frame
| Axis/datum | Definition | Source | Confidence |
|---|---|---|---|

## Sources
| ID | Evidence path/URL | Variant | SHA-256 or access date | Authority/limits |
|---|---|---|---|---|

## Blind-build completeness
| Feature ID | Name/count/function | Datum value or bounded envelope | Source | Confidence | Candidate response | Ready |
|---|---|---|---|---|---|---|

## Dimensions
| ID | Feature | Value/range | Datum/method | Source | Confidence | Tolerance/design response |
|---|---|---:|---|---|---|---|

## Open questions
| ID | Unknown | Risk | Approved bound/question | Blocks |
|---|---|---|---|---|

## Reference round trip
| Build ID/hash | Views/overlay | Verdict | Sheet revision required |
|---|---|---|---|
```

Every visible feature must appear in blind-build completeness. A cosmetic feature may use a
visual/bounded envelope, but cannot be omitted. Camera, control, connector, protective-lip,
handed, load, and clearance features are functional.

A mating/fit-relevant dimension records **as-observed geometry and its measurement
uncertainty** (instrument resolution, repeat-read spread, near-feature bias) — not a fit class,
clearance band, or interference allowance. Fit strategy (clearance, transition, interference,
intended contact, and their bounds) is owned by `print_plan.md`, not this sheet; see that
section for the per-interface declaration and the "bounded band, not a floor" principle it
inherits.

## `print_plan.md`

```markdown
---
contract: print-plan
contract_version: 4
job_id: <slug>
revision: <integer>
owner: print-engineer
status: DRAFT | ACCEPTED | BLOCKED
dimensions_revision: <integer>
reference_sha256: <hash>
updated_utc: <iso-8601>
---

# Print plan

## Process
| Printer/material/nozzle | Layer | Environment/load | Rationale |
|---|---:|---|---|

## Model-to-printer transform
| Item | Exact value |
|---|---|
| Transform/rotation | <matrix or ordered rotations> |
| Bed-contact landmark | <named face/datum> |
| Bed normal | <vector> |
| Open/insertion direction | <vector> |
| Forbidden downward faces | <feature IDs> |

## Geometry rules and phase scope
| ID | Rule | Numeric limit | Verification predicate | required_now | deferred_owner | final_gate |
|---|---|---:|---|---|---|---|

## Interfaces
| ID | Fit type | Contact state | Range min/max per side | Motion path | Material | Coupon/calibration | Acceptance method |
|---|---|---|---:|---|---|---|---|

## Coupon
| Interfaces represented | Clearance lanes | Material | Pass/fail measurements |
|---|---|---|---|

## Final-prep placeholders
<slicer/profile, order, inspection, field test>
```

The transform is a design input, not prose. Prefer one multi-lane coupon STL. Add separate
coupon files only when disjoint interfaces cannot be tested together.

Every geometry rule freezes what must be proved before candidate verification and what, if
anything, is deferred:

- `required_now` names the exact candidate/readiness and verifier evidence required in the
  current phase.
- `deferred_owner` is `none` or one later owner with concrete artifact names.
- `final_gate` is `none` or the exact later state blocked until those artifacts are reviewed.
- An accepted plan revision may not move a failed or omitted `required_now` predicate to a
  later owner for the same candidate hash.

Classify every transformed downface, bridge, roof, or layer-transition predicate as
`SELF_SUPPORT_REQUIRED`, `BRIDGED_NO_SUPPORT` or `SUPPORT_ALLOWED`.
`SELF_SUPPORT_REQUIRED` requires a zero out-of-limit result in both readiness and check 7.
`SUPPORT_ALLOWED` requires a named mesh region, exact transform/nozzle/line-width/layer
range, quantified footprint or interval, one permitted nonfunctional contact class,
enumerated forbidden faces, and named post-print artifacts. No unplanned region may become
support-allowed after it fails verification.

`BRIDGED_NO_SUPPORT` is for area that spans unsupported and prints anyway — a bore roof, a
pocket ceiling, a short flat lintel. It needs a positive `max_out_of_limit_area_mm2`, which
is the budget for how much may bridge, and it must **not** name an `allowed_contact_class`:
nothing touches these faces, and that is exactly what separates it from `SUPPORT_ALLOWED`.
For the same reason it does not trigger `PRINT_PREP` — there are no support contacts to
review. It exists because neither of the other two describes a magnet pocket: the slicer
lays no scaffold, so it is not support-allowed, and the area is not zero, so it is not
self-supporting. A run building to the Gridfinity standard had to declare `SUPPORT_ALLOWED`
and then write a contact class saying no face may take support, which is a field used for
the opposite of its purpose on a feature that appears on tens of thousands of published
parts.

Support-free is the **default, not a hard constraint.** Do not classify a face
`SELF_SUPPORT_REQUIRED` when meeting it forces a *functional* surface (a mating wall, fit
face, bearing/grip surface, or the snug cavity itself) into a distorting gable, steep taper,
or over-wide cavity — that trades a real functional defect for support-purity. Where a
support-free orientation would compromise function or fit, the print engineer plans a bounded
`SUPPORT_ALLOWED` on a *nonfunctional* region instead. Zero-support absolutism is reserved for
parts where it costs nothing functional.

The print engineer owns fit strategy and declares it per interface. Every mating/contact
interface gets an ID and a full declaration: fit type (`clearance`, `transition`,
`interference`, intended elastic contact, crush rib, snap engagement, retention, seal, thread,
or compliant mechanism), intended contact state, an explicit per-side min **and** max range,
motion path (`none` for a fixed interface), material assumptions, a coupon/calibration
requirement, and a numeric/physical acceptance method. **No universal zero-interference rule**:
an interference, crush-rib, snap, or retention interface may declare a deliberately negative
(intersecting) range; a `clearance` interface must stay non-negative on both sides. A
fit-driving range is a **bounded band, not a floor** — over-clearance (slop, wobble, a captured
part that slips or rattles) fails the fit exactly as interference does. Do not carry a
one-sided "≥X, designer may increase" into the plan — that is what produces loose, rattly parts
that pass every gate.

The print engineer also writes `print_plan_checks.json` with every Edge ID, support rule, and
declared interface. This file is the machine-readable projection of the accepted Markdown plan,
not a second source of requirements:

The plan also declares the envelope the candidate is gated against, and the machine-readable
projection carries it: `expected_bbox_mm` (`{x, y, z}` in millimetres) and
`bbox_tolerance_mm`. These are not optional decoration — `commission` **fails** rather than
skips when they are absent, because a part can satisfy every other gate while being wholly the
wrong size, and one did, by 31%. `reference_sha256` is omitted when the job recreates no
mating object; there is no hash to bind.

```json
{
  "schema_version": 4,
  "candidate_predicate_revision": 1,
  "expected_bbox_mm": {"x": 76.5, "y": 158.6, "z": 10.1},
  "bbox_tolerance_mm": 0.5,
  "edges": [
    {
      "id": "E-01",
      "min_radius_mm": 0.4,
      "max_radius_mm": null,
      "samples_required": 3
    }
  ],
  "support_rules": [
    {
      "id": "S-01",
      "disposition": "SELF_SUPPORT_REQUIRED",
      "model_to_printer_matrix": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
      "bed_z_mm": 0,
      "bed_tolerance_mm": 0.05,
      "downward_normal_z_max": -0.70710678,
      "max_out_of_limit_area_mm2": 0
    }
  ],
  "interfaces": [
    {
      "id": "I-01",
      "fit_type": "clearance",
      "contact_state": "sliding, user-operated",
      "min_mm": 0.15,
      "max_mm": 0.30,
      "motion_path": "insert along -Z, 12 mm travel",
      "material": "PETG on PETG",
      "coupon_required": true,
      "acceptance_method": "gauge-pin pass/fail per lane",
      "reference": "mating_frame.stl"
    }
  ]
}
```

Each interface may carry its own `reference`: the path to the part it mates. One reference
yields one measurement -- the tightest point of the assembly -- and cannot say which
interface owns it, so a part with several fits needs several references. The gate refuses
more than one unreferenced interface rather than intersecting their bands, which is what it
used to do: six interfaces gave `[0.30, 0.25]`, a window no geometry can enter, and the only
way past was deleting interfaces from the plan until one was left. Declare every fit the
part has; an undeclared fit is an unverified fit either way, and a declared one is visible.

Use `allowed_sharp: true` only with `allowed_sharp_reason`. A `SUPPORT_ALLOWED` row also
names `allowed_contact_class` and forbidden faces in the Markdown plan. The print engineer
must make the Edge ID, support-rule ID, and interface ID sets complete before candidate CAD.

`interfaces` is optional for backward compatibility — a plan with no mating/contact interfaces
may omit it, and `team_preflight.py validate-interfaces` skips validation when the key is
absent. When present, every entry is fully validated: `id` (unique string), `fit_type` (one of
`clearance`, `transition`, `interference`, `elastic_contact`, `crush_rib`, `snap`, `retention`,
`seal`, `thread`, `compliant`), `contact_state` (string), finite `min_mm`/`max_mm` with
`max_mm >= min_mm` (a `clearance` interface additionally requires both `>= 0`; every other fit
type may declare a negative, intersecting range), `motion_path` (string), `material` (string),
`acceptance_method` (string), and `coupon_required` (bool). A malformed entry fails validation
with a field/ID-named error; see
[`../scripts/team_preflight.py`](../scripts/team_preflight.py).

## `candidate_readiness.md`

This is designer-owned dispatch evidence. It is never acceptance and never substitutes for
fresh verification.

```markdown
---
contract: candidate-readiness
contract_version: 4
job_id: <slug>
candidate_id: <id>
owner: cad-designer
status: READY | NOT_READY
non_acceptance: true
dimensions_revision: <integer>
print_plan_revision: <integer>
reference_sha256: <hash>
candidate_stl_sha256: <hash>
updated_utc: <iso-8601>
---

# Candidate readiness — DESIGNER SELF-CHECK, NON-ACCEPTANCE

| Pre-dispatch check on re-imported STL | Required | Observed | Result | Evidence |
|---|---:|---:|---|---|
| One watertight intended body and bounds | yes | | | |
| Seated interference | plan threshold | | | |
| Full insertion/travel sweep | zero forbidden collision | | | |
| Installed-coordinate section proves architecture/open face | yes | | | |
| Named bed face at printer Z=0 after exact transform | yes | | | |
| Unsupported roof/critical wall floors | plan limits | | | |
| Required renders/STEP/source present | yes | | | |

## Edge/comfort preflight — DESIGNER SELF-CHECK, NON-ACCEPTANCE
| Edge ID / feature boundary | Exposure class | Required radius or allowed-sharp condition | Re-imported-STL samples/method | Observed min/max | Result | Evidence |
|---|---|---|---|---:|---|---|

## Support-sensitivity preflight — DESIGNER SELF-CHECK, NON-ACCEPTANCE
| Rule/region ID | Exact transform/layer/nozzle predicate | Mesh result/footprint/interval | Plan disposition | Allowed contact class and forbidden faces checked | Result | Evidence |
|---|---|---|---|---|---|---|

## Parameter mapping
| Contract IDs | Source parameter(s) |
|---|---|

## Commands and hashes
<reproducible commands and output paths>
```

The orchestrator recomputes presence and hashes. `NOT_READY` stays inside the same designer
commission until corrected; no verifier is dispatched.

The designer also writes `artifact_manifest.json` and `candidate_readiness.md`, and does not
write either by hand: `dt.py commission` derives both from the measurements it just took on
the re-imported STL. The designer runs nothing else. `team_preflight.py` and the contract
commands re-screen the same mesh from the same numbers -- a second reading of one instrument,
not a second opinion -- and belong to the fresh verifier, where a disagreement between two
implementations means something. The designer owes no preflight artefact of its own: the
charter forbids hand-assembling one, and there is no validator on the other side of it.

`team_preflight.py support-audit` (subcommand name kept for backward compatibility; its
result `kind` is `downward-facing-surface-screen`) is a **conservative downward-facing-surface
orientation screen** -- it measures transformed non-bed-contact area whose normal faces down
past a threshold. It does **not** prove slicer supportability, bridgeability, or print
success; a face it flags as within limits can still fail to print cleanly, and slicer behavior
(support generation, bridging, interface layers) is not modeled. Treat a PASS as necessary
geometric evidence for the agent's supportability judgment, never as that judgment itself. It
is the verifier's second implementation, and its value is precisely that it is not the code
the gate ran.

Give every opening boundary, protective lip, exterior user-touch boundary, removal/grip edge,
and plan-named exposed edge an Edge ID. Classify it as `EXPOSED_FUNCTIONAL`,
`EXPOSED_COMFORT`, `HIDDEN`, `BED_CONTACT`, or `PERMITTED_SUPPORT_CONTACT`. An exposed edge
may remain sharp only with a feature-specific plan reason and allowed-sharp condition.
Otherwise sample the re-imported STL at both endpoints and one interior point. A nominal
0.40 mm round must measure 0.38–0.42 mm at every sample. Source fillets, renders, and global
sharp-edge counts are not measurements. These checks are dispatch preflight only; the fresh
verifier independently repeats the applicable sections.

## `artifact_manifest.json`

Every commission that produces exported geometry (reference or candidate) also writes
`artifact_manifest.json`: a **required candidate output**, machine-authoritative, no Markdown
mirror. `contract_version: 1` (independent of the Markdown contracts' `contract_version: 4`).
Owned by whichever commission produced the artifacts (the designer, for reference/candidate
STL/STEP/renders); the orchestrator and verifier read and gate on it, never author it.

Required top-level fields: `contract: artifact-manifest`, `contract_version: 1`, `job_id`,
`candidate_id`, `units` (declared unit; currently only `mm`), `updated_utc`, and an `artifacts`
list. Each artifact row: `id`, `role` (`reference | candidate | coupon | render | source |
mating_reference | other`), `path` (project-relative), `type` (`stl | step | svg | png | md |
json | py | 3mf`), `sha256` (recomputed from the file's bytes, never the agent-entered value),
and optionally `expected_components`, `bbox` (`{"min": [x,y,z], "max": [x,y,z]}`),
`source_revisions`, `transform`, `printable_deliverable`, and `paired_artifact_id` (an STL
paired with its STEP twin, for the bbox cross-check below).

Validation is already implemented in
[`../scripts/team_tools/`](../scripts/team_tools/) — run
`python -m team_tools.contracts validate <project-dir>` from `skills/3d-modeling/scripts/`.
It checks: artifact file exists; declared hash matches the recomputed one; bbox is finite with
positive extent on every axis; declared `expected_components` matches the re-imported STL's
observed connected-component count; a `mating_reference` artifact can never be marked
`printable_deliverable`; and artifact IDs are unique. **Unit/scale validation is a hard gate,
not advisory:** the declared bbox extent is compared against the re-imported STL's actual
extent, and an obvious 25.4x (inch/mm) ratio mismatch (within 0.5% of an exact ratio) is a hard
`UNIT_SCALE_MISMATCH` validation error; a looser match (within 3%) downgrades to a
`POSSIBLE_UNIT_SCALE_MISMATCH` warning instead of blocking. When a `paired_artifact_id` links an
STL to a STEP artifact and both load, their bounding-box extents are cross-checked the same way
(`STL_STEP_BBOX_MISMATCH`). STEP handling stays intentionally shallow: STEP loading is
opportunistic and skipped, never failed, when no OCC/cascadio backend is installed — there is no
deep STEP topology compare. STL bbox plus declared units is the load-bearing check.

The verifier treats a failed `python -m team_tools.contracts validate` (non-zero exit) as a hard
reject of the candidate's exported artifacts, distinct from the seven geometric checks. In
particular, any `UNIT_SCALE_MISMATCH` is a hard `UNIT_SCALE` reject — never downgrade it to a
note-and-pass — recorded as a defect owned by `CANDIDATE_BUILD`. A zero exit is **not** the
converse proof: an absent contract is silent, so an empty project directory validates `PASS`
with exit `0` and an empty `validated_paths`. The verifier must therefore name what the phase
requires:

```bash
python -m team_tools.contracts validate <project-dir> --require all
```

`--require` promotes each named contract's absence to a `REQUIRED_CONTRACT_MISSING` error, so
the exit code alone becomes a sound gate, and the names land in the receipt's
`required_contracts` for review. At Phase 4 of a dispatched job every contract should exist,
so name them all; earlier phases name the subset that phase requires. `DIRECT` never names
`all`: that route dispatches nobody, so no `verification_report.md` is ever written and `all`
demands one — it names `job_state,dimensions,print_plan,artifact_manifest`, which is what it
produces. Either way the verifier confirms the
receipt's `validated_paths` names every contract it expected. (A project directory that does
not exist is a hard exit `2` — a typo can never read as a pass.)

The four Markdown contracts are read through their **frontmatter**, which is where identity,
`revision`, and the binding hashes live; the body is provenance and open questions written for
the next agent, and is deliberately not schema-checked. `artifact_manifest.json` and a JSON
`print_plan.json`, being machine-authored, additionally get a full structural validator.

## `verification_report.md`

```markdown
---
contract: verification-report
contract_version: 4
job_id: <slug>
revision: <integer>
owner: verifier
status: PASS | REJECT
candidate_id: <id>
candidate_stl_sha256: <hash>
dimensions_revision: <integer>
print_plan_revision: <integer>
reference_sha256: <hash>
fresh_context: true
updated_utc: <iso-8601>
---

# Independent verification

## Input/upstream audit
| Input/claim | Expected revision/hash/datum | Independent observation | Result | Evidence |
|---|---|---|---|---|

## Seven checks on re-imported exported STL
| Check | Method | Numeric result | Visual observation | Result | Evidence |
|---|---|---:|---|---|---|
| 1 interference | | | | | |
| 2 full insertion/travel sweep | | | | | |
| 3 section | | | | | |
| 4 same-view/photo overlay look | | n/a | | | |
| 5 named-datum feature positions/handedness | | | | | |
| 6 measurement-to-geometry audit | | | | | |
| 7 planned-orientation printability/faces | | | | | |

## Defects
| ID | Owning loop | Severity | Feature/check IDs | Expected vs observed | Evidence | Required acceptance condition |
|---|---|---|---|---|---|---|

## Verdict
<PASS, or REJECT to METROLOGY / PRINT_PLAN / CANDIDATE_BUILD>
```

The verifier treats `candidate_readiness.md` as untrusted completeness evidence and reruns
all seven checks. Every changed STL hash requires a new fresh verifier context.

The verifier also independently repeats declared edge sections in check 6. In check 7 it
recomputes every `SELF_SUPPORT_REQUIRED` predicate and every `SUPPORT_ALLOWED`
footprint/classification. Visual inspection, not an isometric scalar claim, establishes
whether a support contact class is plausible.

The verifier reruns `team_preflight.py support-audit` into verifier-owned JSON for every
support rule and independently checks that its edge evidence covers the exact plan Edge ID
set. Shared code standardizes the geometric predicate; a fresh context, fresh execution,
fresh visual inspection, and independent measurements preserve verifier independence.

Do not copy the canonical candidate STL into verifier folders. Re-import it in place and
record its hash. A rejected run retains its report, metrics, the defect-specific visual, and
source/output hashes; it does not duplicate unchanged full render sets or exports. A passing
run retains the canonical full report and only verifier-owned visuals that add evidence.

## Plan-revision rule

A plan revision requires a new candidate-readiness receipt and a new fresh full seven-check
verification, even for the same STL hash, when it changes transform, bed landmark, open
direction, material, nozzle, layer or line width, shrink/clearance, walls, overhangs,
bridges, edge/comfort rules, loads, colour, support disposition, permitted contact class,
forbidden faces, or any acceptance threshold/evidence scope. A revision that only adds
post-verification artifacts under an unchanged bound plan requires the applicable final-prep
review, not seven checks. Metadata or coupon elaboration that changes no candidate predicate
requires neither. A failed `required_now` predicate can never be downgraded to deferred.

## `final_print_prep.md`

This is print-engineer-owned manufacturing evidence. Candidate `PASS` is not permission to
claim this receipt is complete.

```markdown
---
contract: final-print-prep
contract_version: 4
job_id: <slug>
owner: print-engineer
status: COMPLETE | READY_FOR_REVIEW | BLOCKED_NATIVE_SLICER | REJECTED
candidate_stl_sha256: <hash>
print_plan_revision: <integer>
verification_report_revision: <integer>
updated_utc: <iso-8601>
---

# Final print preparation

| Required P2 item | Plan rule/final gate | Observed artifact/hash | Result |
|---|---|---|---|
| Coupon source/export and pass/fail lanes | | | |
| Slicer/profile or reproducible settings | | | |
| Underside support-contact view, when required | | | |
| Section/toolpath view per support interval, when required | | | |
| Layer/contact map per support footprint, when required | | | |
| Transform/profile/nozzle/material match | | | |
| Print order, inspection, and field-test protocol | | | |
```

Use `COMPLETE` only when every plan-deferred item is satisfied and none requires independent
visual contact/toolpath review. Use `READY_FOR_REVIEW` when the plan relies on
`SUPPORT_ALLOWED` or another slicer-dependent visual predicate; the verifier then writes
`final_prep_review.md`. Support-free parts with zero out-of-limit regions need concrete
slicer settings and a coupon, but not a native project solely for ceremony.

## `final_prep_review.md`

```markdown
---
contract: final-prep-review
contract_version: 4
job_id: <slug>
owner: verifier
status: FINAL_PRINT_PASS | FINAL_PRINT_REJECT | FINAL_PRINT_BLOCKED
candidate_stl_sha256: <hash>
print_plan_revision: <integer>
final_print_prep_sha256: <hash>
updated_utc: <iso-8601>
---

| Deferred plan predicate | Independent visual/numeric observation | Result | Evidence |
|---|---|---|---|
```

This review does not rerun all seven candidate checks unless the STL or a candidate predicate
changed. It inspects actual support contacts, toolpaths, and layer maps against the unchanged
accepted plan. Missing coverage, forbidden/exposed-edge contact, or an unmapped footprint
rejects final prep.

If a plan-required native slicer cannot launch, import the candidate, save its project, or
show contacts/toolpaths, write `BLOCKED_NATIVE_SLICER` with command/version, candidate and
plan hashes, missing capability, and required owner action. Do not claim native proof or
Ready to Print. A reproducible portable fallback may be labelled `NON_NATIVE`, but it remains
`FINAL_PRINT_BLOCKED` unless the user explicitly approves that exception.
