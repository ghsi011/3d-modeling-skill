# End-to-end QA plan

**Purpose:** make the QA suite exercise the *skill*, not only the pipeline, against
references good enough to disagree with us.

This plan is a design, not a claim of coverage. Nothing in it has been built yet. Every
number below marked *(measured)* was read out of a generator or a source file at the time
of writing; every number not so marked is an assumption and is labelled.

## 1. What is covered end to end today: nothing

The pipeline is well tested. The skill is not tested at all — **no automated test has ever
asked an agent to turn a brief into a design.** Three separate mechanisms hide this:

* **The L1 replays are self-recorded goldens.** `tools/replay.py` `record()` writes
  `expected.json` straight from `observe()` at a named commit. Worse, `_play_one`
  (`tools/replay.py:1028`, class at `:363`) raises `LiveDispatchRequired` on an `AGENT_COMMISSION`, so
  `design_proposal.json` and `model.py` are shipped **inputs**. The authoring step that
  *is* the CUSTOM lane never runs.
* **The blind benchmark never runs a job.** `tools/blind.py --score` hands a mesh straight
  to `score()`. Its five measurements — sorted extents, volume, body count, watertight,
  normalised principal inertia — cannot tell whether anything *fits* anything.
* **Two tests invoke the CLI as a real subprocess**, both packaging smokes in
  `benchmarks/heavy/test_build_skill_heavy.py`; the second asserts only
  `returncode in (0, 1)`.

`diagnose` — the one shipped supplied-geometry capability — has no end-to-end coverage:
`tools/test_diagnosis_l0.py` calls `D.diagnose()` directly.

## 2. Two families, and why conflating them fails

* **Exact-reference** — reconstruct from a dimensioned drawing, or apply a precisely
  specified edit. A withheld reference geometry can be *primary* evidence.
* **Functional-design** — cases, cradles, clamps, organizers. Many geometries are valid,
  so a withheld reference is *secondary*; the primary predicates are fit, interference,
  interface location, clearance, part count, B-rep validity.

Treating the second as the first is how `docs/defects.md` D30 happened: two blind runs
found the envelope is mostly free parameters, so a low score was substantially a fact
about the question. **Every fixture declares what constitutes truth before the agent
runs.**

## 3. References: generated, not fetched

The reference strategy is to *generate* counterparts from permissively licensed libraries
rather than vendor geometry. This removes the withheld-but-stored problem entirely — the
reference is regenerated and re-measured on demand.

| source | licence | role |
|---|---|---|
| `bd_warehouse` | Apache-2.0 | fasteners, bearings, ISO clearance tables |
| `cqgridfinity` | MIT | Gridfinity bins and baseplates |

**Measured in an isolated environment, not transcribed.** `uv run --isolated --with …`,
never added to `pyproject.toml`/`uv.lock`: `build_child.py` shares the parent's
site-packages, so an installed generator would be importable from a candidate's `model.py`
and could leak into the answer.

**The two generators need separate environments** *(measured)*: `cqgridfinity` pulls
`cadquery`, which needs a VTK-enabled OCP, while `build123d` uses the novtk variant. In one
env, `cadquery` fails with `cannot import name 'IVtkOCC_Shape' from 'OCP.IVtkOCC'`.

### 3.1 Clearance holes, read from `bd_warehouse` *(measured)*

| size | Close | **Normal (ISO 273)** | Loose | head Ø (ISO 4762) |
|---|---|---|---|---|
| M3-0.5 | 3.2 | **3.4** | 3.6 | 5.68 |
| M5-0.8 | 5.3 | **5.5** | 5.8 | 8.72 |
| M8-1.25 | 8.4 | **9.0** | 10.0 | 13.27 |

**This is why one arm is not enough.** For M5, ISO 273 Normal, `nominal + 0.5` and
`nominal × 1.1` *all* give 5.5 — a single-arm fixture passes on three different rules, two
of them wrong. M3 separates all three (3.4 / 3.5 / 3.3) and M8 separates `× 1.1`
(9.0 / 8.5 / 8.8). **F1 therefore has three arms, and M3 is the one that discriminates.**

### 3.2 Bearing `M8-22-7` *(measured)*

Bore 8, outer 22, bounding box 22 × 22 × 7, volume 1658.978 mm³. **There is no `.width`
attribute** — it raises `AttributeError`; take the width from the bounding box.

### 3.3 Gridfinity *(measured, `cqgridfinity` 0.5.7)*

| object | X | Y | Z | origin |
|---|---|---|---|---|
| bin 1×1 | 41.5 | 41.5 | 24.8 | centred in X/Y, `zmin = 0` |
| bin 2×1 | 83.5 | 41.5 | 24.8 | centred, `x ∈ [-41.75, 41.75]` |
| bin 3×1 | 125.5 | 41.5 | 24.8 | centred |
| baseplate 2×1 | 84.0 | 42.0 | 4.75 | — |

The footprints confirm the published 42 pitch with 0.25 clearance per side. **The origin
convention is centred**, which is what F3's derived hole centre depends on — a 2×1's cell
centres are at `x = ±21.0`. Note `zlen = 24.8` for a 3-unit bin rather than 21: the height
is not simply `7 × n`, so no fixture may assume it.

**Excluded, and for the accurate reason:** `Stu142/Gridfinity-Documentation` is
**CC BY-NC-SA 4.0**. That licence does *not* forbid copying categorically — it permits
noncommercial sharing under its conditions — so the honest statement is that NonCommercial
plus ShareAlike is a poor fit for a reusable repository QA asset, which must stay freely
redistributable and relicensable downstream. Its drawings are therefore kept out of our
distributable fixture assets. F3 uses only the published pitch/clearance/footprint numbers
and measurements of the MIT-generated artifact.

## 4. The fixture set

| # | fixture | use case | family | primary predicates | tier |
|---|---|---|---|---|---|
| **F0** | `refuse-unsupported-lanes` — 4 arms | mate-with-external-object, reconstruct-from-photos, multi-part, motion | refusal | `lane_status == UNSUPPORTED`; `allowed_claim` says "at all" not "yet" (`status.py:436`); `next_action.kind == LANE_UNAVAILABLE`; exit **1**, not 3; *(live)* the skill refuses in prose and does not retarget a certified template or drop `external_interfaces` to escape the cap | heavy + live |
| **F1** | `direct-fastener-clearance` — M3/M5/M8 | certified-template DIRECT | functional | measured min-inscribed bore per arm (3.4 / 5.5 / 9.0 ±0.05); the generated screw passes at nominal **and at four 0.20 mm radial offsets**; `route == DIRECT`, `builder == CERTIFIED_TEMPLATE`, zero dispatches in `cost.json`; a missing candidate is a **refusal, never a zero** | heavy + live |
| **F2** | `custom-bearing-carrier-608` | authored CUSTOM from spec | functional | **swept insertion envelope** (Ø22.04 from seat floor upward, Ø8.5 through full Z) ≤ 1 mm³; seat min-radius and roundness at three heights; **axial seat extent ≥ 7.00**; shoulder bore ∈ [19.0, 21.0]; declaration completeness in the proposal | heavy + live |
| **F3** | `modify-gridfinity-drain` — 2 geometry arms + cap arm + D21 arm | modify supplied geometry | exact-reference | preservation outside the region box (≤ 0.05); hole Ø 20.0 ±0.2 and centre **±0.05**; footprint 83.50 / 41.50 ±0.20; volume delta against an independently computed boolean; `diagnose` as precondition | heavy + live |
| **F4** | `diagnose-supplied-files` | diagnose supplied artifact | exact-reference (facts) | CLI-level classification per artifact; exit 1 on `RECONSTRUCTION_REQUIRED`; **the artifact's SHA is unchanged after the run**; D1 asserted *as the documented wrong count*, so the day D1 is fixed this goes red | heavy |
| **F5** | `branch-alternatives` | competing concepts | exact-reference | sibling-refusal: answering branch A's review into branch B must be refused | heavy |

### Why these predicates and not similarity

The adversarial pass built impostors that pass the obvious checks:

* a **hex seat** passes a diameter check, because `pipeline/commission.py:258` computes
  `got = 2.0 * math.sqrt(void / math.pi)` — that is **area, not radius**;
* a **captured seat** and a **blind shaft pocket** both pass any seated-pose test and are
  rejected only by a swept insertion envelope;
* a **shallow seat** passes everything, because nothing in this repository measures the
  axial extent of a void.

Two proposed bands were also wrong and are corrected above: a shoulder bore of
`[8.5, 19.0]` was inverted and would have *permitted* inner-race contact, and a hole-centre
band of ±0.20 would have admitted the exact `bbox/N` mis-derivation (0.125 mm) it was meant
to catch.

## 5. Predicate gaps, smallest first

| gap | builds on | needed before |
|---|---|---|
| **G1** refuse-don't-zero: missing candidate, drifted source, absent generator each exit 2 with a distinct error | `blind.py`; `CorpusCorrupt` kept separate from `CorpusUnavailable` | all |
| **G2** request-leak guard and the `--ask`/`--score` wall | `corpus.request_view`, `REQUEST_KEYS`, the coincidence check | all |
| **G3** receipt-claim predicates encoding the real status rule — `status.py:271-283` downgrades **before** the lane cap at `:416-437` is ever reached | file reads | F0, F1, F3, F5 |
| **G4** seated interference — **already exists**: `designer_toolkit/fit.py:29 interference`, `:34 overlap_away_from`, `designer_toolkit/commission.py:643 seated_clearance_mm`. Only a caller outside the toolkit is missing | those three | F1, F2 |
| **G5** min-inscribed radius and roundness on a cross-section | `trimesh` `section()` → `Path2D.polygons_full`, as `analysis.py` already does | F2 |
| **G6** axial extent of a void — **no module here can express this today** | G5 swept in 0.1 mm steps | F2 |
| **G7** swept insertion envelope — the highest-value new primitive; `fit.py`'s own docstring says *"It does not perform an insertion/travel sweep"* | G4 + a swept prism | F2, and every future fit fixture |
| **G8** generated-counterpart builder with a fail-closed self-check before scoring | `tools/fixtures.py` hash discipline | F1, F2, F3 |
| **G9** out-of-run preservation recomputation at a **declared** defect size | `preservation.derive_sample_count`, `detectable_defect_mm` | F3 |
| **G10** live-dispatch harness: materialise the job dir, dispatch the skill, capture the transcript and every `design-tool` invocation | nothing exists — `replay.py:1028` refuses by design | every live arm |
| **G11** claim-conformance checker: does the skill's prose exceed `final_status.allowed_claim`? | G10 | live arms |

**G9 decides F3's shape.** `n = ⌈−ln(1−0.99)·A/d²⌉` (`preservation.py:186`). A 2×1 bin is
~27 000 mm² of surface, so `d = 0.25 mm` gives **≈1.99 M samples per direction** — under
`MAX_DERIVED_SAMPLES` but ~760 MB against `DEFAULT_MEMORY_CEILING_BYTES`. Above ≈54 300 mm²
of source surface the ceiling raises `SampleBudgetExceeded`. That is a decision, not a
detail.

## 6. Order of work

`_SPAWN_ALLOWED = {"git"}` bans child processes in L0, so **everything below lands in
`benchmarks/heavy/`**. No slice in this plan raises the collection ceiling.

1. **Spike the generators** — *done*, §3.1–3.3. Three fixtures' primary predicates rested
   on unmeasured assumptions; they are now measured.
2. **`tools/qabench.py` skeleton** — G1 + G2 + G3. Evidence: each guard shown **refusing**,
   plus a mutation manifest proving the leak guard and refusal path die when anchored out.
3. **F0, four arms.** Cheapest in the set, covers four claimed use cases, and catches the
   most common real request answered dishonestly.
4. **F4, diagnose.** No new geometry primitive; first CLI-level coverage of the one shipped
   supplied-geometry capability.
5. **G4–G7 plus the mutant bench** — shallow seat, hex seat, captured seat, blind shaft
   pocket, zero-clearance seat. Each mutant must fail exactly the named predicate *and pass
   every existing pipeline check*: the blind spot demonstrated, not asserted.
6. **F1, three arms.**
7. **F2**, heavy arm then live arm.
8. **G9 then F3.** Land the preservation recompute and its budget finding first.
9. **G10 + G11 live harness**, then upgrade the live arms.
10. **F5, alternatives.**

## 7. Decisions a human must make

1. **Generator installs** — isolated only, never in `pyproject.toml`. A hardcoded
   3.4/5.5/9.0 fallback is **not** permitted: that is the vendored-answer problem the
   generator was chosen to avoid. Absent generator ⇒ the fixture skips loudly.
2. **Network in CI.** If `pre-merge` has no network, F1–F3 skip there. Is a skip acceptable
   in the gate, or must it be a hard failure?
3. **Catalogue part vs declared `Interface`.** `route.py:200` sends exactly one declared
   external interface to FITTED regardless of evidence; `intent.py:59-62` argues the
   opposite. F1's lane predicate currently settles this by test — it wants one ADR line
   first.
4. **Is a hand-written PASS verification answer allowed** purely to drive `status.decide`
   past `COMMISSIONED` so a lane cap can be asserted end to end? It mints a verification
   receipt on no independent look. If allowed, such arms must be labelled, never archived
   as evidence, and never counted as coverage of `verification.py`.
5. **Preservation budget** — either F3 declares a defect size it can afford, or it declares
   0.25 mm and records `SampleBudgetExceeded` as *the finding*.

## 8. What this set still will not prove

* **Nothing is printed.** "It fits" means a modelled counterpart enters a modelled feature.
* **Nobody looks.** Every arm runs `--no-render`, as every job-level test here does, so
  `witness.py`'s image path and the "the safety reviewer saw numbers and no images"
  downgrade stay unexercised.
* **No fixture reaches `VERIFIED`, and none reaches `COMMISSIONED` honestly.**
  `screening.CALIBRATED = False` plus `status.py:271-283` caps every lane here at
  `NEEDS_MORE_EVIDENCE`. That is the lane's honest ceiling, not a fixture failure — and it
  leaves `verification.py`, `safety.py` and review-envelope binding at zero coverage.
* **Undeclared geometry is corroborated, never ruled out.** Screening profiles only Z and
  has a measured 0.30 false-negative rate on fused defects.
* **Four capabilities are tested only by their refusal** — repair, multi-artifact combine,
  motion, physical-feedback revision. F0 proves the refusal is legible. It proves nothing
  about the capability.
* **The scorers are our code.** Only the reference *numbers* are external. A shared
  misreading of ISO 273 or of the Gridfinity spec survives every predicate here — which is
  why the generators are read at score time rather than transcribed, and why §3 exists.
