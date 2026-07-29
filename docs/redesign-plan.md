# Pipeline redesign — implementation plan

Supersedes the draft spec. Same goals, same toolchain, four substantive changes
and two previously-undefined subsystems now defined. Baseline measurements this
plan is calibrated against: [`redesign-baseline.md`](redesign-baseline.md).

## 0. What changed from the draft, and why

| # | change | reason |
|---|---|---|
| 1 | Broad geometry anomaly screening is **specified, deterministic, and bounded in what it claims** (§5); certified `INCONSEQUENTIAL` `DIRECT` zero-dispatch is gated on its **measured** false-negative rate | The draft made clean `DIRECT` zero-dispatch while relying on "an anomaly detector fires" that it never defined. A 4 mm post once passed 27 green checks, an exact bbox and a matching bed-contact area. Screening catches added material; it cannot prove absence. |
| 2 | **Certified template** and **parameter domain** are defined (§4) | `DIRECT` is gated on both. Neither existed, and neither is inferable from a Python function. |
| 3 | Manufacturing evidence gets an artifact and a phase (§3.7, §9.4) | The draft made supports/inserts/multi-material "modifiers" but deleted the phase where slicer-dependent evidence is produced. Modifiers are declarative; they don't answer "did the supports contact a non-functional face", which cannot be measured from the STL. |
| 4 | Performance section split into **compute** and **wall clock**, and the implementation order is resequenced by measured value (§17, §18) | Every deterministic target in the draft's table is *already met* on the trimesh path. A real job is 3.1 min of wall clock for 3.5 s of compute. Optimizing compute further is worth ~1.5 s. |

Two review passes are incorporated throughout. From the second (15 findings), the
substantive ones were: screening cannot prove absence, so the missing-countersink regression
stays a contract test (§5.1, test 57); expectation generators must not share the
build's arithmetic (§4); certified `INCONSEQUENTIAL` `DIRECT` zero-dispatch is gated on a measured mutation corpus
rather than on detector code existing (§5.4); out-of-domain routes normally
instead of defaulting to `FITTED` (§4); the safety packet omits the normal verifier's
conclusion (§10.1); toolpath predicates are always
`DEFERRED` absent a named slicer adapter (§3.7).

From the third pass: a contract-completeness preflight before any build (§3.2.1);
route and template-selection rationale recorded so routing becomes auditable and
regression-testable (§3.1); policy version and image preprocessing added to the
safety-cache key (§7.9); `W1` given enforced budgets and measured inside the fused
path rather than standalone (§7.7); and an **end-to-end vertical slice promoted to
its own phase, before backends, caching or manufacturing** (§18, Phase D) — one
thin path proven working beats six phases of components that have never met.

Consequence model is exactly two levels, as specified — including the removal of
an automatic-`BLOCK` application list an earlier draft of this plan carried,
which was a third tier in disguise.

---

## 1. Core decisions

Keep these four independent. Nothing here may imply anything else here.

### 1.1 Consequence level

Exactly two:

* **`INCONSEQUENTIAL`** — failure mainly wastes time or material, damages the
  printed part, or causes minor inconvenience.
* **`CONSEQUENTIAL`** — failure could reasonably injure someone, damage
  equipment or property, create a fire or electrical hazard, cause a vehicle or
  machine malfunction, or otherwise have meaningful consequences.

No further levels or liability text.

Consequence does **not** affect geometry routing. Its only effect is a mandatory
final safety-verification pass (§10) after all normal work completes.

Ambiguity resolves toward `CONSEQUENTIAL`. Classification is a judgment about the
request, not a keyword match.

### 1.2 Geometry and evidence route

* **`DIRECT`** — a certified template (§4) covers the geometry, every required
  input is trusted and complete, parameters fall inside the certified domain, and
  every proof obligation can be generated deterministically.
* **`FITTED`** — acceptance depends on external geometry, measurements, material
  behaviour, movement, fit, or tolerances that must be recovered or interpreted.
* **`FULL`** — novel geometry, coupled assemblies, uncertain interfaces, or anything
  else needing the complete workflow. **Not** parallel exploration: candidate
  strategy is independent (§1.4) and `PARALLEL` applies to any route where it helps.

Routing must not depend on whether the part touches or mates with something.
The question is:

> Does acceptance depend on external geometry, material behaviour, motion, load,
> tolerance, or evidence not fully represented by trusted inputs and a certified
> template contract?

* A cable clip is `DIRECT` **only if** a certified template covers the material,
  wall geometry, mouth gap, deformation assumption and accepted bundle range, and
  the bundle dimension is trusted.
* A cradle for a specific phone is normally `FITTED` — the phone is externally
  owned.
* A certified build123d template may be `DIRECT`.
* A `CONSEQUENTIAL` part may be `DIRECT`.

After intent normalization and template matching, route selection is
deterministic. Unresolved ambiguity escalates to `FITTED` or `FULL`; it never
opens a routing conversation.

### 1.3 Manufacturing modifiers

Independent of route: multi-material, multi-colour, flexible filament, supports,
inserts, threads, captive hardware, split-body printing.

These change planning, checks, and which evidence is required (§3.7). They never
force `FULL` by themselves.

### 1.4 Candidate strategy

`SINGLE` or `PARALLEL`. A search strategy — not a route, not a consequence level.

---

## 2. Canonical pipeline

```text
brief + evidence
    ↓ normalized intent                      → intent_manifest.json
    ↓ consequence classification
    ↓ template matching + route selection    → recorded in intent_manifest
    ↓ immutable model contract               → model_contract.json
    ↓ CONTRACT-COMPLETENESS PREFLIGHT        → fail here, before any geometry
    ↓ backend selection
    ↓ isolated geometry build                → model source, build receipt
    ↓ STL export + optional STEP             → artifact_manifest.json
    ↓ single mesh load (raw + normalized)
    ↓ deterministic commissioning            → commission_report.json
    ↓ broad geometry anomaly screening       → folded into commission_report
    ↓ minimal witness generation (W1)
    ↓ manufacturing evidence, if modifiers   → manufacturing_report.json
    ↓ route-specific verification            → verification_report.json (optional, §3.5)
    ↓ final safety verification if CONSEQUENTIAL → safety_verification_report.json
    ↓ final status                           → final_status.json
```

JSON is canonical. Markdown is a generated human view and must never become a
competing source of truth. This inverts today's direction, where four contracts
are Markdown-authoritative.

A clean `DIRECT` pass contains: no design-agent dispatch, no verifier dispatch
when `INCONSEQUENTIAL`, no environment resolution, one job-level command, at most
one geometry worker process, one mesh load, no STEP unless required, `W1`
witnesses only. A certified `INCONSEQUENTIAL` `DIRECT` job has no review callback.
A certified `CONSEQUENTIAL` `DIRECT` job adds exactly one bounded safety call and
still has no normal geometric verifier.

---

## 3. Canonical artifacts

Every schema carries an explicit version. Changing a schema requires a version
bump and a migration path.

### 3.1 `intent_manifest.json`
Schema version, original brief hash, normalized requirements, provenance per
value, **stated vs. inferred** per value, units, external evidence references,
consequence level, unresolved ambiguities, manufacturing modifiers, candidate
strategy.

Stated-vs-inferred is not decoration. Defaulting an unmarked value to "the user
said this" fabricates authority; the default is **inferred**, which understates
and invites scrutiny.

**Route and template-selection rationale.** The manifest also records the decision,
not just its outcome:

* every template considered, with version and `domain_id`;
* for the match: which requirements it covers;
* for each rejection: the specific reason — no geometric coverage, a parameter
  outside the certified domain (naming the parameter and the bound), a violated
  cross-parameter constraint, or a missing capability;
* the route chosen, and if not `DIRECT`, **the exact condition that caused it**.

Routing is otherwise a judgment that leaves no trace, which makes it the one
decision in the pipeline nobody can audit or regression-test. Recorded this way,
"this brief must reject `c_clip` because `bore_d=60` exceeds the certified 40 mm
bound" becomes an assertion.

### 3.2 `model_contract.json`
Written **before** geometry generation, immutable once the build begins.

Schema version, template id + version, selected backend, instantiated parameters,
certified-domain id (§4), required semantic features, expected dimensions and
tolerances, required cross-sections, holes and bore profiles, counterbores and
countersinks, voids and openings, edge treatments, interfaces and clearances,
print orientation, bed-contact requirements, support/overhang policy,
mating-interface ownership, material and process assumptions, expected loads or
force directions where relevant, mandatory checks, minimum required coverage,
provenance for every expectation.

The contract also carries the required manufacturing inputs from `job.json`:
`printer` (non-empty profile name), `material` (process and material strings),
`nozzle` (positive `diameter_mm`), and `orientation` (the model-to-printer matrix
and numeric `bed_z_mm`). A run-job example is incomplete without all four.

**Expectations may not live only in `model.py`.** Model-local `PARAMS` and
`EXPECTED` are deprecated as authoritative and may exist only as generated
compatibility views. Deleting a feature or parameter from model code must not
delete the expectation for it — that failure mode is documented in this repo:
drop `countersink_d` and the geometry and its expectation vanish together, so the
part is self-consistently wrong and nothing objects.

### 3.2.1 Contract-completeness preflight

Run **after** the contract is written and **before** any geometry is built. Every
mandatory feature must carry all five of:

1. **Provenance** — where the requirement came from, and whether stated or inferred.
2. **An expectation** — the value or relation the solid must satisfy.
3. **A tolerance** — a band, not a bare number. A tolerance-free expectation is
   either untestable or secretly exact.
4. **A verification method** — which check answers it, by id.
5. **Defined behaviour when the check cannot run** — `ESCALATE` or `FAIL`.
   Never "skip".

A contract failing any of these is rejected before a build is paid for.

This is the `static-envelope` lesson generalized: an archived run spent 39 minutes
building against a plan whose only support rule declared `SUPPORT_ALLOWED` with no
`allowed_contact_class`, passed commissioning, and was rejected for the plan
afterwards. None of these five needs geometry to check.

Point 5 exists because skipping is how defects ship here: a candidate once went
out 31% too thick while three checks reported `SKIPPED`, nothing counted them, and
the gate exited zero. Under this preflight a feature whose check cannot run has
already declared what that means, so silence is not an option the runtime has.

### 3.3 `artifact_manifest.json`
Schema version, source hashes, contract hash, backend + exact version, Python
version, `uv.lock` hash, build command, STL hash, STEP hash when present, units,
bounding box, tessellation settings, build duration, commission duration, cache
status, normalization/repair actions, boolean operation sequence, peak memory
where available.

### 3.4 `commission_report.json`
Schema version; for every applicable check: whether it ran, why it ran or was
skipped, expected, measured, tolerance, `PASS`/`FAIL`/`ESCALATE`. Plus coverage
numerator and denominator, mandatory-coverage result, raw-vs-normalized mesh
findings, **anomaly-detection results (§5)**, witness references, per-stage
timing.

### 3.5 `verification_report.json`
**Optional.** On a clean certified `INCONSEQUENTIAL` `DIRECT` job no verifier runs,
so this file is absent and `final_status.json` records that the route carried no
independent verification. A consequential `DIRECT` job has the separate safety
report, but still has no normal geometric verifier. The canonical runner does not
emit a deterministic stand-in report. Never emit an empty report to satisfy an
artifact list; a blank verification reads as a verification.

When a verifier does run: route-specific verification result, visual anomalies, requirement mismatches,
missing evidence, requested additional checks, final decision, model and prompt
version where an LLM verifier was used, exact evidence-packet hash.

### 3.6 `safety_verification_report.json`
`CONSEQUENTIAL` only. Contents in §10.

### 3.7 `manufacturing_report.json`  *(added)*
Produced when any manufacturing modifier (§1.3) requires evidence the STL cannot
carry. Slicer-dependent predicates — did supports contact only permitted faces,
do toolpaths bridge as assumed, is the insert pocket reachable, does the
multi-material boundary land where declared — are not measurable from geometry.

Schema version, modifiers in force, required evidence list, evidence produced
(paths + hashes), per-predicate result, and `SATISFIED` / `DEFERRED` / `BLOCKED`.

**Where the toolchain stops.** uv + build123d + trimesh + manifold3d contains no
slicer, and the plan forbids adding GUI software to the core path. So:

* **Geometry-derived predicates are `SATISFIED` deterministically** — downward
  face area in the planned orientation, bed contact, overhang against the
  declared rule, insert-pocket reachability, declared multi-material boundary
  positions. These are measurable from the mesh and the orientation, and
  commissioning already does most of them.
* **Toolpath and actual support-contact predicates are always `DEFERRED`** unless
  a named slicer adapter exists. There is no adapter today, and none is in scope.
  Claiming otherwise promises verification this stack cannot produce.

If a slicer adapter is ever added, it is named and versioned here, its outputs are
hashed into the report, and only then may those predicates be `SATISFIED`.

**Effect of `DEFERRED`, precisely.** A job with a *required* deferred predicate
may not reach `VERIFIED`. It ends at `COMMISSIONED` — geometry proven, a
manufacturing predicate unproven — and `final_status.json` states the allowed
claim in words: "geometrically commissioned; support-contact behaviour not
verified." If the deferred predicate is one the safety verifier needs on a
`CONSEQUENTIAL` job, that verifier returns `NEEDS_MORE_EVIDENCE` and the job ends
there. `DEFERRED` is never silently upgraded and never rounds up to `VERIFIED`.

### 3.8 `final_status.json`
Consequence level, geometry route, backend, commission result, anomaly result,
manufacturing result when applicable, normal verification result, safety
verification result when applicable, final status, allowed output claim, artifact
hashes.

Statuses: `FAILED`, `NEEDS_MORE_EVIDENCE`, `COMMISSIONED`, `VERIFIED`.

A `CONSEQUENTIAL` job may not reach `VERIFIED` without a passing safety
verification. A job with a required-but-`DEFERRED` manufacturing predicate may
not reach `VERIFIED` either; it ends `COMMISSIONED` with the allowed claim
spelled out. Never emit the words `certified` or `guaranteed safe`.

---

## 4. Certified templates  *(new — the draft assumed these existed)*

A template is **certified** when it declares, in version-controlled data beside
the code:

1. **A parameter domain** — per parameter: type, unit, and a closed validity
   range or enumeration. Ranges are inclusive bounds with a stated basis
   ("wall ≥ 2.0 mm: four perimeters at 0.4 mm nozzle"), not bare numbers.
2. **Cross-parameter constraints** — the relations the geometry actually
   requires, as expressions over the parameters (`mouth_gap < bore_d`,
   `tongue < min(wall_x, wall_y)`).
3. **Expectation generators** — functions from parameters to contract
   expectations, **independently implemented** and never measured from the
   produced mesh.

   Independence is the whole value and it is easy to lose. "Derived from the same
   arithmetic that builds the solid" recreates the common-mode failure: geometry
   and expectation share a helper, a bug moves both, and they agree. This repo has
   the failure documented — *"drop `countersink_d` and the expectation disappears
   with the geometry, because one parameter drives both; the part is then
   self-consistently wrong and this module says nothing."*

   So: separate module, separate tests, no shared helper for any critical
   dimension. The mouth-cutter bug is the model to preserve — it changed the
   boolean result and left `fw * fd - pi * r**2` untouched, so the two disagreed
   by 67 mm2. Where a relation is better stated than computed, let the template
   author declare an acceptance relation instead.
4. **A certification record** — domain id, template version, the commit that
   certified it, and the evidence: which parameter combinations were built and
   commissioned green.

   **Not every corner.** Ten ranged parameters is 1,024 corners; `c_clip` has
   eight, so 256 builds at ~3.5 s each. Exhaustive corners only for domains small
   enough to enumerate cheaply (say ≤ 5 ranged parameters). Otherwise: every
   per-parameter boundary, pairwise combinations, every cross-parameter
   constraint boundary, randomized property tests across the domain, and targeted
   mutation tests. Record which strategy was used and its coverage.

```json
{
  "template": "c_clip", "version": "2.0.0", "domain_id": "c_clip@2.0.0/d1",
  "backend": "trimesh-manifold",
  "parameters": {
    "bore_d":  {"unit": "mm", "range": [4.0, 40.0], "basis": "boolean stability below 4; bed span above 40"},
    "wall":    {"unit": "mm", "range": [2.0, 8.0],  "basis": "4 perimeters at 0.4 nozzle"}
  },
  "constraints": ["mouth_gap < bore_d", "wall <= bore_d / 2"],
  "certified_utc": "…", "certified_commit": "…",
  "evidence": {"corners_built": 16, "commission": "PASS"}
}
```

**Rules.**
A parameter outside its range, or a violated constraint, makes the job **not
`DIRECT`**. It does not become `FITTED` by default — routing then runs normally
and decides between `FITTED` and `FULL` on §1.2's question. A novel shape outside
a template domain often has no external object to measure, and calling that
"fitted" is wrong.

Widening a domain requires re-running the evidence and bumping `domain_id`; a
domain may never be widened to admit a part that failed. An uncertified template is usable, but only on `FITTED`/`FULL`.

`domain_id` is part of the cache key (§8.9) and of `model_contract.json`.

---

## 5. Broad geometry anomaly screening

*Renamed from "unconditioned anomaly detection", which overstated it. These are
broad screens. They are not tied to individual declared semantic features, which
is their value — but they are not unconditioned, and they do not solve
undeclared-feature detection in general.*

### 5.1 What this can and cannot do

**Can:** catch material that should not be there — an undeclared post, a stray
boolean fragment, a shell that broke into pieces, a part sitting under the bed.
Added geometry leaves evidence.

**Cannot:** catch a *missing* internal feature. A deleted countersink leaves a
plain bore: smooth, plausible, and anomalous only against the curve the part
should have had. This repo already says so, in `slice_profile`'s own docstring —
*"To turn a curve into a pass/fail you need the curve the part should have had,
and the only thing that can produce it is the template that produced the part —
so the comparison would be against itself."* Missing features are caught by
contract feature-witnesses (§3.2), and only by those.

Do not let a screening pass be read as coverage for absence.

### 5.2 Detectors

1. **Multi-axis profile screening.** Material area as a function of position along
   **X, Y and Z**, not Z alone. Sampling is jittered or adaptive rather than a
   fixed 28 slices, because a small local defect falls between fixed planes and a
   fixed grid is easy to be unlucky with. Thresholds are **scale-normalized**
   (fraction of local section area, not mm²) so a 12 mm² post in a 2,000 mm²
   floor is not lost in the noise floor of a large part.

   Legitimate parts step abruptly all the time — ribs, pockets, shoulders,
   threads, mounting bosses. So the comparison is against a **template reference
   envelope**: the profile band the certified template's own parameters imply,
   generated independently of the build (§4.3). Absent a reference envelope the
   detector reports `INDETERMINATE`, never `CLEAR`.

2. **Silhouette versus contract hull.** Orthographic silhouettes compared against
   the hull the contract implies. Explicitly contract-conditioned — it screens for
   material outside a declared envelope, not for undeclared features generally.

3. **Component and shell audit.** Component count against `expected_bodies`, plus
   any component whose volume is a small fraction of the largest — the shape a
   stray boolean fragment takes. The least conditioned of the three.

4. **Void intrusion.** Material inside a declared `void_region`. Implemented.

5. **Bed-plane sanity.** Lowest point versus the declared bed. Implemented as a
   refusal.

### 5.3 Output

Each reports `CLEAR`, `ANOMALY`, or `INDETERMINATE` into `commission_report.json`.
**`INDETERMINATE` is not a pass** — a detector that could not run means the part
was not screened on that axis.

Any `ANOMALY` or `INDETERMINATE` **escalates** the evidence requirement. A
canonical `DIRECT` run does not silently add a reviewer: it records
`NEEDS_MORE_EVIDENCE` instead. `FULL` retains its route-required independent
verification; `FITTED` invokes independent verification only when its configured
review path and screening condition permit it. A screen never hard-fails a job on
its own; it is a trigger, not a verdict. Broad screens have false positives, and a
false positive that fails a correct part teaches its reader to widen the threshold.

### 5.4 Gate on measured efficacy, not on existence

Certified `INCONSEQUENTIAL` `DIRECT` zero-dispatch is **not** unlocked by these detectors existing. It is
unlocked by measured performance against a mutation corpus.

**Corpus.** For each certified template, generated mutants across five classes:
undeclared additions (posts, ribs, bosses), missing features, wrong-face features
(a countersink on the opposite face), edge-open cuts, and boolean debris. Include
the archived real defects: the missing countersink, the edge-open flange, the rib
across the brood cavity, the welded segments, the 0.25 mm-misplaced pockets.

**Acceptance.** Measured across **at least three templates** and reported per
class:

| metric | requirement |
|---|---|
| false negatives, added-material classes | ≤ 5% |
| false negatives, missing/wrong-face classes | not claimed — §5.1; these are the contract's job, and the corpus reports the contract's rate |
| false positives on known-good parts across the certified domain | ≤ 2% |

Below those numbers, clean `DIRECT` remains incomplete rather than acquiring an
unlisted reviewer: the canonical status is `NEEDS_MORE_EVIDENCE`. This is a hard
gate: removing the look without a measured screen must not silently produce a
stronger claim, and the 4 mm post is what that costs.

## 6. Backend architecture

One narrow interface; no backend conditionals sprayed through the codebase.

```python
class GeometryBackend(Protocol):
    def build(self, contract: ModelContract, output_dir: Path) -> BuildArtifacts: ...
```

### 6.1 `Build123dBackend`
For exact B-rep: fillets, chamfers, revolves, lofts, sweeps, exact face/edge
operations, threads where supported, editable STEP, and certified templates that
benefit from exact CAD.

Always export STL for commissioning. Export STEP only when the contract requires
it. Record tessellation settings. Import build123d and OpenCascade **lazily**,
only when selected. Do not re-tessellate a body. Do not retain B-rep objects
after export. Using build123d must not by itself require a designer dispatch.

### 6.2 `TrimeshManifoldBackend`
For primitive mesh CSG: boxes, cylinders, clips, brackets, slots, repeated
primitive features, and fast certified templates where STEP is unnecessary.

Trimesh for primitives, transforms, file handling, mesh processing. **Explicitly
select Manifold3D for every boolean** — never automatic engine selection. Record
the Manifold3D version and the boolean operation sequence. Prefer batched or
balanced booleans over long sequential chains. Avoid unnecessary mesh copies and
repeated validation passes.

### 6.3 Selection
Templates own their backend choice. For novel geometry: primitive boolean work →
Trimesh + Manifold3D; exact face/edge operations, fillets, chamfers, lofts,
revolves, sweeps, or a STEP requirement → build123d.

This is not "templates versus build123d". A certified template may use either.

---

## 7. Fast execution architecture

### 7.1 One job-level command
```bash
uv run design-tool run-job job_dir/
```
Handles manifest loading, contract validation, routing, backend selection, build,
export, commissioning, anomaly detection, witness generation, verification,
reporting. Lower-level verbs remain for debugging only. Never one `uv run` per
check.

### 7.2 Process model
One lightweight controller. At most one isolated geometry worker per candidate,
terminating after export. Commissioning in the controller. No subprocess per
measurement or per report. No agent dispatched merely to run deterministic
commands. Do not keep OpenCascade resident to hide startup cost.

### 7.3 No dependency work inside jobs
A job never runs `uv sync`, resolves dependencies, modifies `uv.lock`, downloads
packages, probes optional dependencies repeatedly, or rebuilds unrelated caches.
Environment setup is separate: `uv sync --frozen`.

### 7.4 Load each mesh once
Load the raw STL once with processing disabled; create the normalized copy once,
only if needed; reuse both across every check. `mesh_io.load_mesh_raw` /
`load_mesh` already provide exactly this pair — today `commission.py` loads the
STL **four** times (lines 543, 571, 632, 809). Never recompute bounds, adjacency,
normals, components or mass properties twice.

```python
@dataclass
class MeshAnalysisContext:
    raw_mesh: trimesh.Trimesh
    normalized_mesh: trimesh.Trimesh | None
    bounds: np.ndarray
    components: list[trimesh.Trimesh]
    face_normals: np.ndarray
    cached_sections: dict[SectionKey, SectionResult]
    cached_proximity: dict[CheckKey, float]
    cached_silhouettes: dict[ViewKey, SilhouetteResult]
```

### 7.5 Lazy imports
Measured: `import trimesh, manifold3d` costs **1.47 s** — 78% of a no-witness
`DIRECT` run. Do not import build123d on trimesh-only jobs, rendering code
without witnesses, or optional analysis packages on the core path. Keep schema
validation and routing lightweight. Measure backend import time separately.

### 7.6 Lazy outputs
On a clean `DIRECT` pass: export STL; STEP only if requested; `W1` only. No dense
slices, debug meshes, alternate orientations or full-resolution renders.

Expand only when a mandatory check fails, a result is near tolerance, a parameter
is near a certified-domain boundary, normalization changed the geometry, a verifier
requests more, or the safety verifier needs a specific view. An anomaly or
indeterminate screen escalates the final status; it does not add a reviewer to a
canonical `DIRECT` run.

### 7.7 Witness levels
* **`W0`** deterministic receipt only — internal diagnostics, never sufficient for
  acceptance.
* **`W1`** compact routine witness — low-resolution orthographic views or
  silhouettes, one or two isometrics, a small set of uniformly spaced sections,
  required feature sections, coverage report. Clean `DIRECT`, and the initial
  safety packet.

  **`W1` carries fixed budgets, enforced in code, not conventions:**

  | budget | limit |
  |---|---|
  | views | ≤ 8 orthographic + 2 isometric |
  | image resolution | ≤ 512 px on the long edge |
  | sections | ≤ 12, plus one per required feature |
  | peak memory | ≤ 256 MB above the controller baseline |
  | wall clock | ≤ 2 s |

  Exceeding a budget is a build failure, not a slow run. A witness level with no
  ceiling grows one view at a time until it is the dominant cost, and each
  addition looks reasonable on its own.

  **Benchmarked inside the fused path, never standalone.** The baseline's ~1.65 s
  for witnesses was measured in isolation, which is the flattering number: it
  excludes the mesh already being resident, the section cache being warm, and the
  controller's own overhead. §17.1's target is on the end-to-end delta between a
  `--no-witness` and a `W1` run of the same job.
* **`W2`** expanded anomaly witness — sections near the suspicious region, higher
  resolution, difference views, extra orientations, accessibility/edge-opening
  evidence.
* **`W3`** full independent-review packet — `FULL`, difficult `FITTED`, unresolved
  anomalies, safety escalation.

Never generate `W2`/`W3` unconditionally.

### 7.8 Conditional STEP
Export when the user asks, the template promises editable CAD, a downstream
workflow needs it, or the contract requires it. Always export STL regardless.

### 7.9 Content-addressed caching
Key on contract hash, template/source hash, **certified `domain_id`**, backend
version, toolchain lock hash, schema version, export settings, tessellation
settings.

Layers: build artifacts, commission analysis, witnesses, human-readable reports.
A hit validates hashes and receipts. Never reuse across incompatible tool
versions, schema versions, units, contract values, tessellation or backend
versions.

**A geometry cache hit is not a safety-verification cache hit.** A cached
`CONSEQUENTIAL` job still runs §10 unless a prior result matches on *every* one
of: evidence-packet hash, prompt hash, model snapshot identifier, reasoning
settings, **safety-policy version**, output-schema version, inference
configuration, and **image preprocessing configuration**. The last matters because
the verifier reads renders: a different downsampling or crop is a different
reviewer looking at a different picture. "Same verifier
version" is not identity — the same version under different reasoning settings is
a different reviewer.

---

## 8. Commissioning

Every backend commissions the exported STL through one path.

```bash
uv run design-tool run-job job_dir/                 # production
uv run design-tool commission --artifact body.stl \
  --contract model_contract.json --source model.py  # diagnostic
```

### 8.1 Fail closed
Fail or explicitly escalate on: missing contract; invalid schema; contract hash
mismatch; missing mandatory feature declaration; a contract that did not pass the
§3.2.1 preflight; mandatory check skipped;
coverage below minimum; unknown unit scale; suspected 25.4× mismatch; a mesh path
using any boolean engine other than Manifold3D; unexpected repair; artifact not
traceable to the immutable contract; missing optional dependency required by a
mandatory check; **any anomaly detector reporting `ANOMALY` or `INDETERMINATE`
without escalation**; missing safety report on a `CONSEQUENTIAL` job; safety
result `BLOCK` or `NEEDS_MORE_EVIDENCE`.

Unexpected repair preserves the raw artifact, records the normalized artifact
separately, records the exact changes, and escalates — never silently accepts.

### 8.2 Required checks
Watertightness, winding, normals, component count, envelope, unit scale, volume
and surface area where informative, bed contact, planned-orientation overhang,
cross-sections, hole profiles, bore profiles, counterbores, countersinks, voids
and openings, mating clearance, edge-connected cuts, required feature witnesses,
raw-vs-normalized differences, and the §5 detectors.

Global scalars are never sufficient on their own.

---

## 9. Route-specific execution

### 9.1 `DIRECT`
Requires: certified template; parameters inside the certified domain; trusted
complete inputs; complete immutable contract; no unresolved ambiguity; all
mandatory checks pass; required coverage complete; no unexpected repair; all
anomaly detectors `CLEAR`.

Certified `INCONSEQUENTIAL` `DIRECT`: zero specialist calls (once §5.4 is satisfied), one job command, one
worker, one mesh load, `W1` only, no STEP unless requested.

Certified `CONSEQUENTIAL` `DIRECT`: identical deterministic path, then exactly one
bounded final safety-verification call in a fresh context, with no normal geometric
verifier.

### 9.2 `FITTED`
Minimum dispatches needed to recover externally owned information. Preserve
datum-based dimensions, measurement provenance, fit ownership, fit bands,
acceptance method, material and process assumptions.

The bounded specification review is required. Independent verification may follow
when the caller supplies that review and the screen is clear; it is not a hidden
`DIRECT` review.

Combine compatible specification work into one constrained structured call. Use
deterministic transformation for schema conversion and validation. Never dispatch
an agent to run deterministic CLI commands. Put all required inputs in the initial
context. Never ask an agent to reread a file it just wrote. Prefer one-shot
structured output.

### 9.3 `FULL`
Independent verification retained. The verifier never receives the designer's
hidden reasoning — only the brief, the immutable manifests and contract, exported
artifacts, deterministic measurements, and witnesses.

`FULL` retains both route-required reviews: one bounded specification review and one
independent verification review. An imported or off-template solid is a legitimate
starting artifact when no evidence recovery is needed; bind its path and hash, skip
only the missing evidence-recovery phase, and record dimensions read from it as
**inherited from imported solid**. Any new dimension or adjustment is
**chosen by design** and must carry its rationale. The imported artifact is not thereby
treated as a certified `DIRECT` template.

For `CONSEQUENTIAL` jobs, the safety verifier is separate from both the designer
and the normal verifier. The canonical runner makes one bounded safety review; its
packet omits `verification_report.json`, so the safety decision cannot be anchored
on a normal verifier's conclusion.

### 9.4 Manufacturing evidence  *(added)*
When any modifier in force requires evidence the STL cannot carry, produce
`manufacturing_report.json` (§3.7) before final status. On `DIRECT` this is
deterministic where possible (support-contact screening against the planned
orientation) and `DEFERRED` where it genuinely needs a slicer. `DEFERRED` is
carried into `final_status.json`, never silently upgraded.

---

## 10. Mandatory consequential safety verification

Every `CONSEQUENTIAL` job runs one additional final safety pass. Non-negotiable.
It is not skipped because the route is `DIRECT`, the template is certified, the
part looks simple, deterministic checks passed, another verifier reviewed it, the
artifact came from cache, the user wants speed, or the route has no other
dispatch.

### 10.1 Independence
Fresh context. The safety reviewer must not receive the designer's hidden chain of
thought, self-justification, informal safety claims, or any instruction to confirm
an existing answer. It receives the original brief, consequence classification,
`intent_manifest.json`, `model_contract.json`, `artifact_manifest.json`,
`commission_report.json`, `manufacturing_report.json`, STL metadata, renders and
silhouettes, relevant sections, material assumptions, print orientation, expected
loads and force directions, and fit and retention assumptions. The canonical packet
deliberately omits `verification_report.json`; a second opinion that reads the first
one is anchored by construction.

### 10.2 Required questions
Plausible failure modes; could it detach, fracture, deform, slip, jam, short,
overheat, or interfere with nearby equipment; are load direction and magnitude
represented; visible or implied stress concentrations; does print orientation
create weak inter-layer loading; are wall thicknesses, attachment points and
transitions plausible; are flexible or snap-fit assumptions supported; could
tolerance or material variation produce unsafe behaviour; could a missing, extra
or misplaced feature create a hazard; are external interfaces represented
accurately; is physical testing required before use; is the evidence sufficient
to pass at all.

**Mandatory review concerns.** Where the brief indicates life-safety,
load-bearing for a person, braking or steering, a pressure vessel, a
mains-electrical barrier, fire containment, or regulated structural or medical
use, the verifier must address that application explicitly in
`safety_concerns` and state what physical evidence would be needed. It decides
`PASS`/`BLOCK`/`NEEDS_MORE_EVIDENCE` on the evidence like any other job.

This is not a hidden third consequence level. An earlier draft made these an
automatic `BLOCK` list, which is a third tier wearing a different hat — the
pipeline classifies with exactly two levels and nothing here changes that.

Strict structured output:

```json
{
  "decision": "PASS | BLOCK | NEEDS_MORE_EVIDENCE",
  "failure_modes": [], "safety_concerns": [],
  "missing_evidence": [], "required_actions": [], "summary": ""
}
```

### 10.3 Control flow
`PASS` → may reach `VERIFIED` if everything else passed.
`BLOCK` → `FAILED`.
`NEEDS_MORE_EVIDENCE` → deterministically generate the allowed additional
witnesses, or request the missing information, then rerun. Bounded to a small
configurable number of cycles (default 2); after the limit, stop at
`NEEDS_MORE_EVIDENCE`.

### 10.4 Shape
One bounded call, not an autonomous loop: compact packet, structured output,
fixed maximum length, no shell access by default, no file-navigation loop, no
charter rereading, deterministic evidence expansion. A full autonomous verifier
runs only after the bounded call identifies a genuinely unresolved issue.

---

## 11. Isolated build execution

One worker subprocess per candidate, with wall-clock timeout, memory limit or
monitoring where supported, captured stdout/stderr, deterministic working
directory, explicit output paths, clean termination after export, and a failure
receipt on timeout, crash or resource exhaustion.

Avoid long-lived OpenCascade sessions, repeated tessellation, exporting
intermediate solids outside debug mode, unlimited segment or pattern counts,
unbounded sequential boolean chains, and retaining dead geometry.

Validate parameters against the certified domain (§4) **before** constructing
geometry.

---

## 12. `uv` migration

`pyproject.toml` authoritative. **Commit `uv.lock`** — it is currently gitignored
at `.gitignore:60`. Document `uv sync --frozen`. Run production commands through
`uv run` or installed console scripts; **define console entry points**, which do
not exist today. Remove obsolete Poetry/Conda/duplicate requirements/ad-hoc pip
instructions, keeping a short migration note.

Pin or constrain tested versions of build123d, trimesh and manifold3d. Keep the
core install lean: the core path must not require SciPy, Shapely, Rtree, Blender
or GUI software. Optional capabilities fail explicitly when required and absent.

Never resolve or sync from inside a job.

---

## 13. Remove CadQuery and FreeCAD MCP

Sweep for imports, templates, selectors, exporters, MCP calls, MCP configuration,
setup instructions, role charters recommending either, tests, examples, fallback
branches, and documentation describing either as active.

Known sites: `designer_toolkit/exporter.py:81` (lazy `import cadquery`),
`scripts/run_cadquery_model.py` + `test_run_cadquery_model.py`,
`references/cadquery-patterns.md`, `references/freecad-mcp-patterns.md`,
`roles/designer.md` required-reading items 4 and 6.

Migrate useful CadQuery templates to build123d or Trimesh+Manifold3D. Salvage the
runner's *contract* — its timeout and exit-code tests are the right shape for the
§11 worker — then delete the CadQuery-specific code.

No silent fallback to CadQuery, FreeCAD, Blender, OpenSCAD, another boolean
engine, or an optional dependency. Do not claim completion while any active
import, route, config, test or doc still references the retired tools.

---

## 14. Documentation

Update architecture docs, setup instructions, doctor output, CLI help, role
charters, template docs, examples, troubleshooting.

Remove these, all currently present and now false:
* "trimesh is only a fallback when no CAD kernel exists" (`trimesh-patterns.md:3`)
* "`DIRECT` means trimesh-only"
* "build123d requires a designer dispatch"
* "STL handoff may omit semantic expectations"
* any rule that routes geometry by consequence
* any consequence tier beyond these two values

State plainly:

```text
build123d                       = exact CAD authoring
trimesh                         = mesh inspection and exported-artifact measurement
manifold3d                      = the mesh boolean engine, always explicit
model_contract.json             = requirement truth
exported STL                    = commissioned artifact truth
anomaly screening               = broad checks, not tied to declared features
                                  (cannot prove absence -- see the contract for that)
manufacturing_report.json       = evidence geometry cannot carry
safety_verification_report.json = final safety review, CONSEQUENTIAL only
```

---

## 15. Tests

The draft's 45, plus these, and all adversarial rather than happy-path:

46. A certified template rejects a parameter outside its domain, the job becomes
    not-`DIRECT`, and routing then decides `FITTED` or `FULL` on its own merits.
47. A violated cross-parameter constraint escalates identically.
48. A domain may not be widened to admit a previously failing part.
49. `domain_id` participates in the cache key.
50. Slice-profile detector fires on a synthetic undeclared post.
51. Silhouette detector fires on material outside the contract hull.
52. Component detector fires on a stray boolean fragment.
53. An `INDETERMINATE` detector escalates and does not pass.
54. Certified `INCONSEQUENTIAL` `DIRECT` zero-dispatch is refused while any §5.1 detector 1–3 is absent.
55. `manufacturing_report.json` is produced when a modifier requires it.
56. `DEFERRED` manufacturing evidence reaches `final_status.json` unaltered.
57. The archived missing-countersink defect is caught by its **contract feature
    witness**, and the screening detectors are asserted *not* to be relied on for
    it — a deleted countersink leaves a plausible bore and no anomalous geometry.
    A test claiming otherwise would be asserting something the geometry cannot
    support.
58. A part below the declared bed is refused, not measured.
59. Mutation corpus (§5.4): per template, mutants across added-material,
    missing-feature, wrong-face, edge-open and boolean-debris classes.
60. Measured false-negative rate on added-material classes is at or under the
    §5.4 threshold, across at least three templates.
61. Measured false-positive rate on known-good parts sampled across the certified
    domain is at or under the §5.4 threshold.
62. Certified `INCONSEQUENTIAL` `DIRECT` zero-dispatch is refused while those measured rates are unmet — the
    gate is efficacy, not the presence of detector code.
63. A screening `ANOMALY` escalates and does not hard-fail the job.
64. `INDETERMINATE` on any detector escalates rather than passing.
65. A required-but-`DEFERRED` manufacturing predicate blocks `VERIFIED` and lands
    the job at `COMMISSIONED` with the allowed claim stated.
66. The consequential safety packet omits `verification_report.json`, so the one
    bounded safety review cannot be anchored on an independent-verification report.
67. A safety cache entry is not reused when the prompt hash, model snapshot,
    reasoning settings, schema version or inference configuration differ.
68. Out-of-domain parameters produce a not-`DIRECT` job that then routes normally
    — not an automatic `FITTED`.
69. Expectation generators and geometry builders share no helper for any critical
    dimension (import-graph assertion).
70. Contract-completeness preflight rejects a feature missing provenance, an
    expectation, a tolerance, a verification method, or cannot-run behaviour —
    one test per omission, each asserting the build never started.
71. A feature declaring `skip` as its cannot-run behaviour is rejected: the only
    legal values are `ESCALATE` and `FAIL`.
72. The preflight runs before geometry: on rejection, no STL and no build receipt
    exist.
73. `intent_manifest.json` records every template considered, the match reason,
    and a specific rejection reason per candidate.
74. An out-of-domain parameter's rejection reason names the parameter and the
    bound it violated.
75. A not-`DIRECT` decision records the exact condition that caused it.
76. `W1` exceeding any budget (views, resolution, sections, memory, wall clock)
    fails the build rather than running slowly.
77. Witness cost is measured as the end-to-end delta between `--no-witness` and
    `W1` on the same job, not standalone.
78. The safety cache misses when policy version or image preprocessing
    configuration differs.

### Regression corpus
Keep every historical defect as a test with its own reproduction: missing
countersink, edge-open flange, welded segments on STL reimport, the rib across
the brood cavity, magnet pockets 0.25 mm out, the 31%-too-thick case, the
underground fixture, the fabricated provenance rows.

---

## 16. CI

`uv sync --frozen` from the committed lockfile. Format, lint, type-check, unit
tests, backend integration, historical defect regressions, representative
commissioning. Verify forbidden imports and references. Save failure receipts.

No FreeCAD, CadQuery, Blender, SciPy, Shapely, Rtree, or GUI requirements.

Split: fast unit/schema · backend integration · historical defects · performance
smoke. Do not run full benchmarks across every matrix cell. Mock LLM calls
normally; keep a small optional live-model suite for the safety prompt.

---

## 17. Performance requirements

Split into two, because the draft conflated them and the conclusion changes.

### 17.1 Deterministic compute — mostly already met
Measured on the target machine (n=5):

| operation | target | today |
|---|---|---|
| trimesh/manifold3d cold `DIRECT` | < 5 s / < 10 s | **3.54 / 3.60 s** — met |
| commission-only | < 2 s / < 5 s | **1.66 / 2.00 s** — met |
| compact witness | < 2 s / < 5 s | **~1.65 s** — met |
| cached `DIRECT` validation | < 2 s / < 4 s | no cache — to build |
| build123d cold, no STEP | < 10 s / < 20 s | no backend — to build |
| build123d with STEP | < 20 s / < 35 s | no backend — to build |

Single-load, lazy imports and caching are still correct. Budget them honestly:
together they are worth roughly 1.5 s.

### 17.2 Wall clock — the real target
A measured end-to-end `DIRECT` job: **3.1 minutes for 3.5 seconds of compute.**
The gap is agent round trips at 8–47 s each.

| route | metric | target |
|---|---|---|
| `INCONSEQUENTIAL DIRECT` | dispatches | 0 (after §5.4) |
| | wall clock | < 60 s |
| `CONSEQUENTIAL DIRECT` | dispatches | exactly 1 |
| | wall clock | < 3 min |
| `FITTED` | dispatches | ≤ 3 |
| `FULL` | dispatches | reported, not capped |

Report separately per route: deterministic compute, dispatch count, LLM wall
clock, safety-verification latency, total wall clock. Add a benchmark command
emitting machine-readable timings. If a target cannot be met, report the dominant
stage — never weaken a check to hit a number.

---

## 18. Implementation order

Resequenced by measured value. The draft's order front-loads work worth ~1.5 s;
this front-loads what unblocks correctness and what removes minutes.

**Phase A — foundation (no behaviour change)**
1. Commit `uv.lock`, add console entry points, document `uv sync --frozen`.
2. Two consequence levels with a bounded safety review and independent
   verification.
3. Versioned schemas for all artifacts; JSON canonical, Markdown generated.

**Phase B — the contract (highest correctness value)**
4. `intent_manifest.json` and immutable `model_contract.json`.
5. Move expectations out of `model.py`; generate `PARAMS`/`EXPECTED` as views.
6. Certified templates: domain format, constraints, certification record (§4).

**Phase C — screening (gates certified INCONSEQUENTIAL DIRECT zero-dispatch)**
7. Screening detectors 1–3 (§5.2), enough to run — the measured rates come in E.
8. Escalation wiring: `ANOMALY`/`INDETERMINATE` leaves canonical `DIRECT` at
   `NEEDS_MORE_EVIDENCE`; route-required verification remains with `FITTED`/`FULL`.

**Phase D — end-to-end vertical slice** ← *the de-risking step*
9. Take **one** part, on **one** template, on **one** backend, all the way
   through: routing → contract → preflight → build → export → single load →
   commission → screening → `W1` → verification → `final_status.json`.
10. It must produce every artifact §19 demands for that route, and pass.
11. Benchmark it end to end and record it beside the baseline.

   Nothing else starts until this runs green. Six phases of components that have
   never met each other is how a redesign discovers in week four that the contract
   cannot express what the runner needs. One thin working path first, then widen
   it — and every later phase has a working reference to regress against rather
   than a specification to argue with.

**Phase E — proving the screen**
12. Mutation corpus across five defect classes, three templates (§5.4).
13. Measure false-negative and false-positive rates; publish them.
14. Only now may clean `INCONSEQUENTIAL DIRECT` drop to zero dispatches — and
    only if the rates clear §5.4. Until they do, the bounded visual call stays.

**Phase F — backends**
15. `GeometryBackend` interface; port the trimesh templates behind it.
16. `Build123dBackend`, lazy-imported, with one certified exact-CAD template.
17. Conditional STEP.

**Phase G — the full runner**
18. `run-job` generalized, `MeshAnalysisContext`, lazy imports.
19. Witness levels `W0`–`W3`, conditional generation, `W1` budgets enforced.
20. Isolated geometry worker with timeout and failure receipts.

**Phase H — safety and manufacturing**
21. Bounded two-stage safety verification (§10.1), structured output.
22. Bounded deterministic evidence expansion.
23. `manufacturing_report.json`, the modifier-driven evidence rules, and the
    `DEFERRED` status effect.

**Phase I — cleanup and proof**
24. Remove CadQuery and FreeCAD MCP everywhere.
25. Content-addressed caching.
26. Charters, docs, CI.
27. Re-benchmark; optimize only what profiling shows dominates.

Run the relevant tests after each phase. Two hard gates: **nothing proceeds past
D until the vertical slice is green**, and **certified `INCONSEQUENTIAL` `DIRECT` zero-dispatch does not ship
until E's measured rates meet §5.4** — detector code existing is not the gate.

### Do not
Rewrite unrelated code · add consequence levels · add legal acknowledgement or
approval workflows · introduce a service architecture without profiling evidence ·
keep a CAD kernel resident to hide startup · add heavy optional dependencies to
the core path · replace deterministic checks with LLM judgment · silence failures
to hit a target · let a `CONSEQUENTIAL` job skip its safety pass · change a schema
without versioning · claim completion from documentation alone.

---

## 19. Deliverables and proof

Code, updated `pyproject.toml`, committed `uv.lock`, backend interface and
implementations, migrated templates, versioned schemas, fused CLI, single-load
commissioning, analysis and content-addressed caching, anomaly detectors, safety
stage, manufacturing evidence, updated charters and architecture docs, complete
CadQuery/FreeCAD removal, tests, CI, migration notes, before/after performance.

The final report lists files changed, architectural decisions, remaining
limitations, unsupported geometry, exact dependency versions, median and p95
runtime, dispatch count by route, safety latency, cache behaviour.

Demonstrate, with all artifacts for each:
1. A certified Trimesh/Manifold3D `INCONSEQUENTIAL` `DIRECT` job.
2. A certified build123d `INCONSEQUENTIAL` `DIRECT` job.
3. A `CONSEQUENTIAL` `DIRECT` job with its safety report.
4. A representative `FITTED` job.
5. A representative `FULL` job.
6. A `CONSEQUENTIAL` job blocked by the safety verifier.
7. A `CONSEQUENTIAL` job returning `NEEDS_MORE_EVIDENCE` and receiving bounded
   expansion.
8. **A job where an anomaly detector catches undeclared geometry that every
   conditioned check passed.**

Prove: clean `uv sync --frozen`; no active CadQuery or FreeCAD path; certified
`INCONSEQUENTIAL DIRECT` uses zero specialist calls; certified `CONSEQUENTIAL
DIRECT` uses exactly one bounded safety review and no normal geometric verifier;
the STL is loaded once; STEP and expanded witnesses appear only when required.
