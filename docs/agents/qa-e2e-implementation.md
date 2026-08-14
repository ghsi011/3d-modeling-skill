# Five real-model end-to-end QA fixtures for the 3D-modeling skill

**Status:** implementation brief / research-verified plan  
**Prepared:** 2026-08-14  
**Repository:** `ghsi011/3d-modeling-skill`

## 0. What this document authorizes and what it does not

This document specifies the target five-fixture QA suite and the evidence each fixture must produce. It is not permission to weaken a gate, widen a ceiling, vendor third-party binaries, add dependencies, re-record goldens, or invent synthetic verification evidence. Repository `AGENTS.md`, `ARCHITECTURE.md`, the review workflow, and explicit user permissions still govern implementation.

Implement the suite **incrementally, one real end-to-end fixture at a time**. A fixture is not "implemented" because its manifest exists; it must actually start from the public/request-side package, run the live design path, produce STL and 3MF deliverables, and be scored against hidden truth without exposing that truth to the authoring side.

The five fixtures are chosen to exercise **different failure surfaces**, not to produce five variations of the current bracket benchmark:

1. deterministic design from a dimensional standard;
2. functional enclosure/mating around a real object, including multi-part output;
3. standard mechanical hardware / B-rep precision;
4. modification of supplied geometry with preservation of everything outside the requested edit;
5. reconstruction from images plus sparse measurements.

The current blind scorer is useful evidence but is not sufficient for these fixtures. Bounding-box extents, volume, body count, watertightness, and normalized principal inertia do not establish fit, feature location, preservation, or shape equivalence.

---

# 1. Non-negotiable benchmark invariants

## 1.1 The run must be genuinely end to end

The benchmark arm starts with only the material a real requester could provide for that use case:

- `brief.md`;
- structured requirements if the production pipeline requires them;
- optional **request-side** images, measurements, drawings, or source STEP when that use case legitimately supplies them.

It ends with the production skill's normal deliverables, including:

- editable model/source required by the skill;
- one or more final STL files;
- one final 3MF containing the intended printable object(s);
- normal assessments/receipts produced by the real path.

Do **not** ship pre-authored `model.py`, a design proposal, or candidate geometry as benchmark input. The authoring step is the thing being tested.

## 1.2 Hidden truth is answer-side only

The candidate/authoring side must not receive:

- reference model bytes;
- reference path;
- reference filename or repository identity when it would make the answer directly searchable;
- reference digest;
- generator name/version;
- hidden target measurements except those deliberately disclosed as legitimate request-side measurements.

Keep the current request/answer wall. Reuse `tools/corpus.py`'s external-reference discipline rather than inventing a second weaker mechanism.

Where a source identity itself gives away the answer, materialize a neutral input filename. Example: the Prusa source STEP used for MODIFY may be presented as `source.step`; its bytes are legitimately supplied, but its GitHub path does not need to become prompt material.

## 1.3 No third-party model bytes in the skill repository

`AGENTS.md` forbids project-specific models, large binaries, private evidence, and licensed third-party artifacts in the skill repository.

Commit only small text/code needed to reproduce the benchmark:

- fixture definitions;
- source URLs;
- pinned commit/tag;
- licence metadata;
- expected SHA-256;
- generator parameters/commands;
- benchmark-owned request text;
- benchmark-owned small scripts;
- acceptance predicates;
- calibration records.

Third-party geometry and generated reference geometry live outside the repo under `DESIGN_TOOL_CORPUS_ROOT` or in the E2E project tree, with hashes binding the exact bytes.

## 1.4 A green skip is not required hosted coverage

If a fixture is declared part of **required hosted pre-merge coverage**, an unavailable pinned generator/reference is a hard, named failure.

A loud skip is acceptable only when the fixture is explicitly:

- a local discovery run; or
- an optional/external evaluation track.

Never describe a skipped fixture as hosted E2E coverage.

## 1.5 No hand-written verification PASS in a live E2E arm

Do not fabricate a production-shaped PASS receipt just to push `status.decide` beyond `COMMISSIONED`.

Synthetic receipts are acceptable only in narrow state-machine unit tests whose claim is explicitly "given this synthetic upstream state, the state machine does X." They do not count as live E2E verification coverage.

If the real E2E path cannot obtain independent verification, leave that portion **unproven** and report the capability gap.

---

# 2. Common output contract

Every fixture should finish with a candidate folder containing, at minimum:

```text
<run>/
  request/
    brief.md
    project.json                 # if the production path uses it
    attachments/                 # only legitimate request-side material
  candidate/
    <editable-source...>
    <part-a>.stl
    [<part-b>.stl ...]
    candidate.3mf
    <normal production receipts/evidence...>
  score/
    result.json
    result.md
    <fixture-specific evidence...>
```

The exact project layout may follow current production conventions; do not create a duplicate workflow solely for benchmarking.

## 2.1 Common CAD hard gates

Before fixture-specific scoring, every candidate must pass:

1. every expected STL exists and parses;
2. intended solid/body count is correct for the fixture;
3. each required solid is watertight unless the fixture explicitly says otherwise;
4. units are millimetres and scale is sane;
5. no unexpected extra printable body is present;
6. model fits the declared build envelope;
7. required geometry is present in the final STL, not only source;
8. normal production validity/printability checks that apply to the fixture pass.

These are necessary, not sufficient.

## 2.2 Common 3MF hard gates

3MF is a **separate manufacturing/delivery gate**. A run may be reported as:

- `CAD_PASS / 3MF_PASS`;
- `CAD_PASS / 3MF_FAIL`;
- `CAD_FAIL` (3MF result may still be recorded diagnostically).

Do not byte-compare 3MF archives.

Validate instead:

1. archive is structurally valid and readable by the repository's 3MF tooling;
2. intended printable object count matches the accepted STL set;
3. geometry represented in the 3MF corresponds to the final candidate STL geometry within a calibrated export/reload tolerance;
4. no hidden/extra printable object is present;
5. units and object transforms are correct;
6. plate placement/orientation matches the fixture's print contract;
7. printer/material/nozzle assignments are present when the production skill claims them;
8. multi-part fixtures preserve the required separate objects/assemblies.

Do not require identical ZIP metadata, UUIDs, object ordering, tessellation, slicer metadata, or compression.

---

# 3. Comparison architecture: do not make one universal similarity score

A single scalar must **not** decide PASS across these five tasks.

There are three different truth models.

## 3.1 Reference-driven / substantially determined geometry

Used by:

- F1 Gridfinity;
- F5 image reconstruction;
- parts of F3 pillow block.

Hard acceptance can include:

- feature count/topology;
- named-datum dimensions;
- silhouette agreement;
- rigidly registered surface distance;
- exact required interfaces.

## 3.2 Functional design with many valid solutions

Used by:

- F2 real-object enclosure;
- portions of F3 mechanical mating.

Primary truth is functional:

- no forbidden collision;
- required clearance **band** is met;
- ports/controls/fasteners remain accessible;
- required axes and hole locations align;
- output part count/assembly behavior is correct;
- print constraints pass.

Reference-model similarity is secondary/diagnostic. A geometrically different enclosure that satisfies every frozen functional requirement must be allowed to PASS.

## 3.3 MODIFY / preservation

Used by F4.

Split geometry into:

- **authorized edit region**;
- **preservation region**.

The requested edit has its own exact predicates. Outside that region, unrelated geometry must remain equivalent to the supplied original within calibrated transport/tessellation noise.

Global bbox/volume similarity is not an adequate preservation test.

---

# 4. Registration and geometric-distance rules

When a fixture uses geometric surface comparison:

1. no scaling;
2. no reflection;
3. only translation plus a **proper rotation** (`det(R) = +1`) may be fitted;
4. prefer fixture-defined named datums and canonical axes before generic fitting;
5. do not let unconstrained ICP erase handedness or feature-location errors;
6. after alignment, compute bidirectional sampled surface distances rather than a one-way nearest-neighbour score;
7. report at least median/mean, p95, p99 or max as appropriate, and the fraction within the calibrated band;
8. keep feature/datum checks independent even if the global surface metric passes.

A mirrored part must not become a PASS because a fitter found a reflection.

---

# 5. Threshold calibration policy

Do **not** choose Hausdorff/surface-distance tolerances by looking at agent results.

Before freezing any geometric-distance band, measure same-geometry noise:

1. source reference -> export STL at tessellation A -> reload;
2. same source -> export STL at tessellation B -> reload;
3. if practical, source -> second independent exporter -> reload;
4. rigidly translate/rotate one copy and confirm the registration path recovers it;
5. compare all same-geometry variants;
6. select a threshold with an explicit safety margin above measured transport/tessellation noise.

The calibration record belongs in the fixture evidence and should state:

- source hash;
- exporter and version;
- tessellation settings;
- measured distribution;
- selected band;
- why the margin is sufficient.

For dimensions explicitly stated in a brief, use the stated tolerance instead of inventing a similarity band.

For functional fits use a **bounded min/max clearance**, never a one-sided minimum: too loose can fail just as surely as interference.

---

# 6. The five fixtures

---

## F1 — Standard-driven design: 2 x 1 x 3 modular storage bin with one divider

### Purpose

Exercise "design from a specification" without supplying candidate CAD.

This is the cleanest fixture for proving that a live request can reach finished STL + 3MF and that deterministic geometric comparison machinery works.

### Hidden reference source

**Generator:** `michaelgale/cq-gridfinity`  
**Licence:** MIT  
**Pin:** tag `v.0.5.7`  
**Commit:** `a5cff2c45e2cf33162c55b43becb27d97d66cebb`

Source:

- https://github.com/michaelgale/cq-gridfinity
- https://github.com/michaelgale/cq-gridfinity/tree/a5cff2c45e2cf33162c55b43becb27d97d66cebb

Verified generator properties:

- X/Y Gridfinity unit = 42 mm;
- height unit = 7 mm;
- `GridfinityBox` supports length/width/height, dividers, lip/no-lip, holes, scoops, labels and wall thickness;
- exports STEP and STL.

### Stable reference configuration

Use the pinned generator to produce a simple canonical configuration equivalent to:

```python
GridfinityBox(
    2, 1, 3,
    length_div=1,
    width_div=0,
    holes=False,
    no_lip=False,
    scoops=False,
    labels=False,
    wall_th=1.0,
)
```

Record the actual generator command, environment, output STEP hash and output STL hash during ingest.

Do not infer exact final bbox dimensions into the brief from the reference output. The request should carry only the standard/interface information that a requester legitimately states.

### Candidate input package

Use neutral language; do not name `cq-gridfinity`.

Brief requirements:

- storage bin compatible with a modular 42 mm X/Y grid;
- footprint: 2 grid units by 1 grid unit;
- height: 3 units, with one height unit = 7 mm;
- one internal divider splitting the long direction into two compartments;
- standard stack/mating lip required;
- no magnets or screw holes;
- no finger scoops;
- no label flange;
- nominal wall thickness 1.0 mm;
- PLA / 0.4 mm nozzle;
- final STL + 3MF required.

If a base mating profile must be described numerically, source it from a public standard/reference document and treat it as request-side stated data. Do not leak the hidden generator's actual output measurements.

### Hard acceptance

- common CAD gates;
- exactly one printable body;
- divider count = 1;
- divider location/topology matches the requested long-axis split;
- stack/mating lip exists;
- forbidden optional features absent;
- named standard/interface dimensions satisfy the brief;
- registered reference comparison inside calibrated same-geometry-derived band for substantially determined surfaces;
- candidate 3MF passes common 3MF gate.

### Diagnostic metrics

- sorted extents;
- volume;
- normalized inertia;
- bidirectional surface-distance distribution;
- wall-thickness samples;
- interior usable volume.

### Required mutation probes

At minimum, prove the fixture catches:

1. divider removed;
2. divider moved to wrong axis;
3. lip removed;
4. magnet holes added;
5. one axis scaled;
6. mirrored/incorrect-handed transformation if the fixture gains any handed feature;
7. extra body inserted into STL or 3MF.

---

## F2 — Real-object mating + multi-part output: Framework Laptop 13 Mainboard printable case

### Purpose

Exercise the hardest functional-design class:

- fit to a real object;
- several ports/keep-outs;
- multi-part printable output;
- parts must mate with each other and with the counterpart;
- a different external shape may still be correct.

This fixture must **not** be judged primarily by "looks like the official case."

### Verified source family

**Repository:** `FrameworkComputer/Framework-Laptop-13`  
**Current research pin:** `9680262347b80efe2314673bf1f26eb955165fca`  
**Licence for Mainboard / Printable Case material:** CC BY 4.0

Source:

- https://github.com/FrameworkComputer/Framework-Laptop-13
- https://github.com/FrameworkComputer/Framework-Laptop-13/tree/9680262347b80efe2314673bf1f26eb955165fca/Mainboard

Verified repository material includes:

- Mainboard 2D drawings with PCB outline, keepouts and connector locations;
- an OpenSCAD 3D-printable tray;
- a fully featured official Printable Case;
- individual printable-case STL files;
- `Mainboard/Printable Case/printable_case_full.stp`;
- case documentation stating the case is split into sections to fit home printers and that each section is printable without supports.

The official case was first uploaded in commit:

`331c382f6bb2d30446f2ba466e17928c5eb7d8d6`

The same commit also added the generic Mainboard 2D drawing family. This is useful provenance for selecting a compatible fixture pair.

### Activation blocker — resolve before enabling the fixture

Do not silently mix a current case reference with a different-generation mainboard truth.

Before F2 becomes an active benchmark:

1. pin one exact Framework commit/reference package;
2. identify the exact board outline/keepout drawing used as counterpart truth;
3. identify the exact official printable-case variant used as hidden reference;
4. prove that the hidden official case is compatible with the chosen board/keepout truth by running the same interference/access predicates the candidate will face;
5. hash every external asset.

If current-main compatibility cannot be demonstrated from the public files, pin a **historically compatible** board-drawing + case pair from the 2022 case introduction history instead of guessing.

This is an ingest task, not something the candidate should solve.

### Candidate input package

The benchmark should imitate a real fit-critical request rather than hand over the hidden case.

Preferred first arm:

- neutralized board images/renders generated from the pinned counterpart truth;
- named dimensions/keepouts taken from the pinned public mechanical drawing;
- explicit connector/control accessibility requirements;
- mounting-hole locations;
- board thickness / envelope information;
- printer envelope and material;
- requirement for an enclosing printable multi-part case;
- requirement that all parts be printable and reassemblable;
- final per-part STLs + one 3MF.

Do not include:

- official case model;
- official case screenshots;
- case file names;
- source repository name in candidate-visible material if it makes the case directly searchable.

A later second arm may supply the actual board STEP as a legitimate mating counterpart. That is a different use case and should be scored separately.

### Hard acceptance

Primary functional predicates:

- all required case parts valid/watertight;
- board is placeable at the declared installed pose;
- forbidden board/component intersection = 0 within calibrated numeric tolerance;
- mounting hole axes/centres align within stated tolerance;
- connector/port keep-out volumes remain unobstructed;
- required controls remain reachable;
- ventilation/opening requirements in brief are present;
- candidate shell parts do not collide in the assembled pose;
- intended fastening/locating interfaces align;
- required min/max board-to-case clearance bands hold at named regions;
- assembly is enclosed where the brief requires enclosure;
- candidate fits printer envelope and print constraints;
- 3MF contains all and only intended printable pieces.

### Reference comparison

Diagnostic only unless a region is explicitly mandated by the brief:

- whole-shape surface distance;
- volume;
- inertia;
- support area;
- part count relative to official reference.

A candidate that meets every frozen functional and manufacturing predicate may PASS even if its shell architecture differs from Framework's official case.

### Required mutation probes

At minimum:

1. move one mounting hole;
2. close one required connector opening;
3. translate the board seat to cause collision;
4. over-widen a locating clearance beyond its maximum;
5. remove one required shell piece;
6. make two shell pieces collide;
7. drop one part from 3MF while STL set remains complete.

---

## F3 — Precision B-rep / standard hardware: M8-22-7 bearing pillow block

### Purpose

Force a true build123d/OCC-style mechanical path with standard hardware and exact fit geometry.

This fixture is more deterministic than F2 and is a good bridge between pure standard-driven geometry and underdetermined functional design.

### Hidden reference source

**Repository:** `gumyr/bd_warehouse`  
**Licence:** Apache-2.0

Do **not** pin current `main` for the first benchmark environment. As of the research date, current main commit `9d0dc942cd08217552bd6553f88e929f8a3115bb` depends on a development build of build123d (`>=0.11.2.dev0`), which is unnecessary benchmark fragility.

Use the stable release:

**Tag:** `v0.3.0`  
**Commit:** `28696f9b4c765c3b0385ccef1d41f45de245e8ad`

At that pin:

- `bd_warehouse` requires `build123d >= 0.11.1`;
- `examples/pillow_block.py` contains the desired reference.

Source:

- https://github.com/gumyr/bd_warehouse
- https://github.com/gumyr/bd_warehouse/blob/28696f9b4c765c3b0385ccef1d41f45de245e8ad/examples/pillow_block.py

### Verified reference geometry

The pinned example defines:

- block width = 50 mm;
- block height = 30 mm;
- thickness = 10 mm;
- outer corner fillet radius = 2 mm;
- centered `SingleRowDeepGrooveBallBearing(size="M8-22-7")`;
- `PressFitHole(... interference=0.025 mm)`;
- four `M2-0.4` socket-head-cap-screw clearance holes;
- hole grid determined by `padding = 12 mm`, yielding centres at ±19 mm X and ±9 mm Y from the block centre.

Regenerate the reference in an isolated pinned environment and record STEP/STL hashes.

### Candidate input package

Do not name `bd_warehouse`.

Brief may legitimately state the design itself because this fixture tests precise implementation:

- 50 x 30 x 10 mm rounded rectangular pillow block;
- 2 mm outer corner radius;
- centered 8 x 22 x 7 mm radial bearing;
- bearing press fit: 0.025 mm diametral interference as defined by the benchmark contract;
- four M2 mounting clearance holes;
- hole centres 12 mm in from the corresponding outer edge lines, equivalent to the frozen centre coordinates above;
- no extra bodies;
- PLA / 0.4 mm nozzle;
- final STL + 3MF.

If the repository's fit convention expresses clearance per side rather than diametral interference, normalize the fixture once and document the convention explicitly. Do not let two conventions coexist.

### Hard acceptance

- exact outer dimensions within declared tolerance;
- corner-radius feature present;
- bearing seat axis and centre correct;
- bearing seat dimension/interference in the frozen fit band;
- bearing counterpart seats without forbidden collision outside the intentional press-fit region;
- four fastener-hole centres correct;
- hole geometry passes the frozen M2 clearance predicate;
- one intended watertight printable block;
- candidate STEP/B-rep path exercised if the production skill claims it;
- 3MF common gate passes.

### Diagnostic metrics

- global surface distance;
- bearing-axis runout/offset;
- hole-pattern position deltas;
- volume/inertia;
- wall margins around bearing seat and fasteners.

### Required mutation probes

1. normalize bearing fit by the wrong convention;
2. shift bearing centre;
3. move one M2 hole;
4. replace M2 clearance with nominal 2.0 mm bore;
5. wrong block thickness;
6. extra body;
7. corrupt or omit 3MF object.

---

## F4 — MODIFY lane: targeted edit of Original Prusa MINI display-box STEP

### Purpose

Test the claim "modify this existing design" rather than "redraw something similar."

The key question is not global similarity. It is:

> Did the requested region change correctly while everything else stayed unchanged?

### Source model

**Repository:** `prusa3d/Original-Prusa-MINI`  
**Licence:** GPL-3.0  
**Pin:** `853bc30c4b10190f1d669ed6d0a567e333c28f21`

Source STEP:

`STEP/PRINTED PARTS/MINI-display-box.stp`

Source:

- https://github.com/prusa3d/Original-Prusa-MINI
- https://github.com/prusa3d/Original-Prusa-MINI/blob/853bc30c4b10190f1d669ed6d0a567e333c28f21/STEP/PRINTED%20PARTS/MINI-display-box.stp

The repository also exposes the broader STEP and source part sets, so this is a real production CAD artifact rather than a benchmark-created primitive.

### Required ingest work before fixture activation

The exact edit must be selected **after inspecting the pinned source geometry**, not guessed from the filename.

The edit should be:

- non-trivial;
- entirely expressible from datums/features visible in the supplied source;
- local;
- safe from ambiguous hidden interior conflicts;
- easy to mask spatially;
- measurable without reference leakage.

Preferred shape of edit:

- add one rounded rectangular cable/vent slot to a broad non-mating planar wall; or
- add one mounting/clearance hole at a specified offset from named source datums.

Do not freeze the example until source inspection proves that the selected face and edit volume are valid.

Once chosen, record in the fixture:

- source STEP SHA-256;
- canonical coordinate frame;
- authorized edit bounding volume/mask;
- exact edit dimensions/tolerances;
- reference-generation script and output hashes.

### Hidden target generation

Generate the hidden target deterministically from the exact supplied source STEP using benchmark-owned code and OCCT/build123d or the repository's approved B-rep tooling.

The candidate receives the **original** STEP, never the edited target.

### Candidate input package

- `source.step` (byte-identical to the pinned source but neutral filename);
- brief naming the exact target feature, source datums, dimensions and tolerance;
- instruction to preserve every other feature;
- print/manufacturing requirements;
- final modified STL + 3MF required.

### Hard acceptance

Two independent regions:

#### A. Edit region

- requested feature exists;
- correct type/topology;
- correct size;
- correct centre/axis/orientation from named datums;
- through/blind depth as requested;
- no unintended disconnected solid.

#### B. Preservation region

Outside the authorized edit mask:

- candidate and original/source geometry agree within calibrated same-geometry transport/tessellation tolerance;
- source datum positions do not move;
- source body count is preserved unless the edit explicitly changes it;
- no unrelated feature disappears or appears.

A global bbox/volume/inertia PASS cannot substitute for the preservation-region check.

### Required mutation probes

1. make requested edit 1 mm too large;
2. move edit centre;
3. make through-cut blind or vice versa;
4. alter an unrelated source feature outside mask;
5. translate the whole model while preserving shape;
6. delete an unrelated detail;
7. 3MF contains pre-edit rather than post-edit geometry.

---

## F5 — Images + sparse measurements: LDraw Technic Brick 1 x 2 with axlehole (`32064a`)

### Purpose

Exercise reconstruction from visual evidence and measurements without giving the agent CAD.

This is the first fixture that directly measures the "photos/descriptions -> geometry" path.

### Hidden source

**Official LDraw part:** `parts/32064a.dat`  
**Description:** Technic Brick 1 x 2 with Axlehole with Open Sides and Stud Blocker  
**LDraw status:** Official  
**Licence:** CC BY 2.0 and CC BY 4.0

Source:

- https://library.ldraw.org/parts/5544
- https://ldraw.org/article/218.html

LDraw format facts used by ingest:

- right-handed coordinate system;
- 1 brick width/depth = 20 LDU;
- 1 brick height = 24 LDU;
- 1 plate = 8 LDU;
- 1 stud diameter = 12 LDU;
- 1 LDU ≈ 0.4 mm.

Important: LDraw itself calls 0.4 mm a **real-world approximation**. Do not use it as micron-level metrology truth.

### Reference ingest

Do not add an LDraw parser dependency to the skill merely for this fixture without explicit dependency authorization.

Instead, prepare the hidden reference in an isolated ingest environment:

1. fetch the official part and all required LDraw subparts/primitives;
2. convert deterministically to a triangulated reference at a documented scale;
3. record converter/version/command;
4. record source DAT hash and output STL hash;
5. generate controlled reference images from the same hidden geometry.

The converted STL remains external corpus data.

### Candidate-visible image package

Generate a fixed set of images before the run, for example:

- front orthographic-ish;
- side;
- top;
- one 3/4 perspective.

Use the same neutral material/background and fixed camera parameters for every run.

Do not expose:

- LDraw part number;
- LDraw source path;
- hidden mesh;
- generator/converter metadata.

### Candidate-visible measurements

Use sparse, realistic measurements only:

- overall 2-stud length;
- 1-stud width;
- standard brick height;
- axle-hole centre height/longitudinal position;
- one or two additional dimensions a caliper could realistically establish.

Do **not** transcribe every LDraw vertex or hidden feature size. The point is to force visual reconstruction.

### Hard acceptance

- one intended watertight body;
- correct overall major dimensions within a tolerance calibrated for LDraw's approximate real-world scale;
- correct stud count and centre positions;
- axle hole exists and is through as required;
- axle-hole centre/axis correct;
- open-side / stud-blocker topology present;
- handedness correct;
- silhouettes from the supplied camera views agree within a calibrated image-space band;
- rigid proper-rotation surface comparison passes a **looser, explicitly calibrated** band than STEP-derived fixtures;
- final 3MF passes common gate.

### Diagnostic metrics

- registered bidirectional surface distance;
- silhouette IoU / boundary distance by supplied view;
- volume;
- normalized inertia;
- per-feature position table.

### Required mutation probes

1. round hole substituted for axle hole;
2. axle hole shifted vertically;
3. one stud removed;
4. open-side detail filled;
5. mirrored geometry;
6. wrong global scale;
7. image silhouette scorer disabled;
8. 3MF missing the candidate body.

---

# 7. Why the earlier Arduino candidate is replaced

Do not use the previously proposed Arduino UNO R4 community case as one of the canonical five.

The Framework fixture is stronger because:

- board mechanical material and official printable case live in one first-party hardware repository;
- the Mainboard and Printable Case material explicitly carries CC BY 4.0;
- the repository contains both mechanical reference material and official printable artifacts;
- it can exercise multi-part enclosure behavior rather than only one community-designed case.

The cost is an ingest requirement: pin a proven-compatible Framework board/case pair rather than assuming every generation is interchangeable.

---

# 8. Why the bee escape is not one of the first five

The TPU bee escape is valuable later as a **physical-validation** benchmark, not as an automated golden-model fixture.

Its engineering study leaves decisive properties to experiment/live use:

- comfortable worker opening force;
- reverse-passage probability;
- creep at hive temperature;
- trapping/snag safety;
- propolization;
- clearing time.

A CAD model can be geometrically correct and still fail the real job. Do not pretend a hidden STL can settle those questions.

Once the automated suite is mature, the bee escape is an excellent sixth benchmark for the separate evidence state "physical field validation."

---

# 9. Proposed fixture metadata shape

Do not replace `benchmarks/corpus.json`'s existing semantics casually. The current corpus manifest owns reference identity and hash; keep that source of truth.

If multi-asset/multi-part E2E fixtures need a separate small manifest, prefer a shape like the following **conceptually** and adapt it to current repository conventions:

```json
{
  "id": "e2e-grid-bin-2x1x3",
  "class": "FROM_SPEC",
  "required_hosted": false,
  "request": {
    "brief": "benchmarks/e2e/requests/grid-bin/brief.md",
    "attachments": []
  },
  "reference": {
    "corpus_entry": "grid-bin-2x1x3-v057",
    "redistribution": "EXTERNAL_ONLY"
  },
  "expected_outputs": {
    "stls": 1,
    "three_mf": 1
  },
  "acceptance_profile": "reference_determined_v1"
}
```

For a multi-asset reference, extend corpus identity so each named asset has its own expected SHA-256. Do not hide a directory or ZIP behind "whatever files happen to be there."

Generated references additionally bind:

- generator repository;
- tag/commit;
- environment/lock;
- command/parameters;
- resulting hashes.

---

# 10. Runner behavior

The E2E runner should conceptually do the following:

```text
materialize request-side package
        |
        v
assert no answer-side asset/identity leaked
        |
        v
run the REAL skill / commission path
        |
        v
collect final STL(s) + 3MF + production receipts
        |
        v
common CAD/3MF validation
        |
        v
resolve hidden corpus/generator output
        |
        v
fixture-specific hard predicates
        |
        v
diagnostic reference metrics
        |
        v
write machine-readable + human-readable report
```

Do not let score-side code participate in authoring.

The run report must bind:

- fixture ID/revision;
- candidate input hashes;
- final candidate STL hashes;
- 3MF hash;
- hidden reference hash(es);
- scorer version/commit;
- every hard predicate and result;
- every diagnostic metric;
- overall `PASS` only as conjunction of required hard predicates, never a weighted score.

---

# 11. Evidence naming

Each fixture report should be readable without opening code.

Recommended categories:

```text
score/
  result.json
  result.md
  calibration.json
  geometry/
    registration.json
    surface-distance.json
  features/
    named-datums.json
  fit/
    interference.json
    clearance.json
  modify/
    edit-region.json
    preservation-region.json
  images/
    silhouette-*.png
  manufacturing/
    three-mf-validation.json
```

Only create applicable files. Do not manufacture empty ceremony.

---

# 12. Mutation requirement for every new hard predicate

Every predicate that can cause PASS/FAIL must have a mutation that proves it can fail.

Examples:

- hole-position predicate -> move hole;
- collision predicate -> translate mating seat until collision;
- max-clearance predicate -> over-widen fit;
- part-count predicate -> add/remove body;
- preservation predicate -> change unrelated feature;
- handedness predicate -> mirror;
- 3MF geometry binding -> put stale/pre-edit geometry in 3MF;
- silhouette predicate -> move/erase a visible feature;
- registration -> scale or reflect and prove it is rejected.

A passing fixture without a mutation-proven failure path is not a protection.

---

# 13. Implementation sequence

The final objective is all five fixtures, but do not implement them in one giant abstraction-first PR.

## Slice A — common live-E2E shell + F1

Implement only the minimum required to:

- materialize F1 request;
- invoke the real design path;
- find final STL + 3MF;
- keep hidden reference separate;
- run common output gates;
- run F1's exact/reference-driven predicates;
- produce a report.

Run it for real and post-mortem.

## Slice B — F4 MODIFY

Add only what preservation requires:

- supplied source STEP input;
- deterministic target edit;
- edit-region mask;
- preservation-region comparison.

Run it for real and post-mortem.

## Slice C — F5 images + measurements

Add:

- image attachments on request side;
- controlled-camera silhouette comparison;
- feature/datum checks;
- calibrated LDraw reference conversion.

Run it for real and post-mortem.

## Slice D — F3 hardware/B-rep

Add only the missing standard-hardware and fit predicates earned by the run.

Pin `bd_warehouse v0.3.0`; do not inherit current-main's dev-build dependency.

## Slice E — F2 Framework enclosure

Do this last because it requires the richest functional predicate set and multi-part 3MF.

Before implementation, close the board/case compatibility ingest blocker.

### Important continuity rule

If the previously approved **split-bearing-clamp discovery commission** has not yet run, it remains the first real fit-predicate discovery exercise. That commission is allowed to teach the harness what it actually needs; this five-fixture rollout must not use this document as an excuse to prebuild a generic interface-predicate framework from imagined requirements.

---

# 14. Acceptance criteria for the QA suite itself

The suite is successful only when all of these are true:

1. each active fixture can be run from a clean checkout with its declared external prerequisites;
2. the authoring side never reads hidden answer bytes;
3. candidate source is actually authored during the run;
4. every active fixture reaches final STL + 3MF or reports a real production blocker;
5. references are hash-bound and drift is loud;
6. all hard predicates are candidate-independent and frozen before the run;
7. every hard predicate has a mutation-proven failure;
8. no fixture depends on a single aggregate similarity score;
9. geometric thresholds are calibrated from same-geometry noise, not performers;
10. functional fixtures privilege fit/clearance/access over similarity to one gold design;
11. MODIFY fixture proves preservation outside the authorized edit;
12. image fixture proves visual/feature reconstruction, not merely bbox agreement;
13. 3MF is validated separately from CAD;
14. required hosted fixtures fail when their generator/reference is absent; optional fixtures say SKIP explicitly;
15. reports distinguish software assessment, independent verification, and physical validation.

---

# 15. Research verification table

| Fixture | Source | Pin | Licence | Research status | Activation issue |
|---|---|---|---|---|---|
| F1 Grid bin | `michaelgale/cq-gridfinity` | `v.0.5.7` / `a5cff2c...` | MIT | verified | calibrate reference-distance band |
| F2 Framework case | `FrameworkComputer/Framework-Laptop-13` | candidate pin `9680262...`; historical case intro `331c382...` | CC BY 4.0 for Mainboard/Printable Case | verified source family | **prove board/case generation compatibility before activation** |
| F3 Pillow block | `gumyr/bd_warehouse` | **v0.3.0** / `28696f9...` | Apache-2.0 | verified; same pillow example present | pin compatible build123d environment |
| F4 Prusa modify | `prusa3d/Original-Prusa-MINI` | `853bc30...` | GPL-3.0 | verified STEP exists | inspect model and freeze one safe local edit |
| F5 image reconstruction | LDraw `parts/32064a.dat` | official part page / source hash at ingest | CC BY 2.0 + CC BY 4.0 | verified | choose deterministic external conversion path; calibrate approximate real-world scale |

---

# 16. Sources checked

## Repository / architecture

- `ghsi011/3d-modeling-skill/AGENTS.md`
- `ghsi011/3d-modeling-skill/tools/corpus.py`
- `ghsi011/3d-modeling-skill/tools/blind.py`
- `ghsi011/3d-modeling-skill/benchmarks/corpus.json`

## F1

- https://github.com/michaelgale/cq-gridfinity
- https://github.com/michaelgale/cq-gridfinity/tree/a5cff2c45e2cf33162c55b43becb27d97d66cebb
- https://github.com/michaelgale/cq-gridfinity/blob/a5cff2c45e2cf33162c55b43becb27d97d66cebb/LICENSE

## F2

- https://github.com/FrameworkComputer/Framework-Laptop-13
- https://github.com/FrameworkComputer/Framework-Laptop-13/tree/9680262347b80efe2314673bf1f26eb955165fca/Mainboard
- https://github.com/FrameworkComputer/Framework-Laptop-13/blob/9680262347b80efe2314673bf1f26eb955165fca/Mainboard/README.md
- https://github.com/FrameworkComputer/Framework-Laptop-13/blob/9680262347b80efe2314673bf1f26eb955165fca/Mainboard/Printable%20Case/README.md
- https://github.com/FrameworkComputer/Framework-Laptop-13/commit/331c382f6bb2d30446f2ba466e17928c5eb7d8d6

## F3

- https://github.com/gumyr/bd_warehouse
- https://github.com/gumyr/bd_warehouse/tree/28696f9b4c765c3b0385ccef1d41f45de245e8ad
- https://github.com/gumyr/bd_warehouse/blob/28696f9b4c765c3b0385ccef1d41f45de245e8ad/examples/pillow_block.py
- https://github.com/gumyr/bd_warehouse/blob/28696f9b4c765c3b0385ccef1d41f45de245e8ad/pyproject.toml

## F4

- https://github.com/prusa3d/Original-Prusa-MINI
- https://github.com/prusa3d/Original-Prusa-MINI/blob/853bc30c4b10190f1d669ed6d0a567e333c28f21/STEP/PRINTED%20PARTS/MINI-display-box.stp
- https://github.com/prusa3d/Original-Prusa-MINI/blob/853bc30c4b10190f1d669ed6d0a567e333c28f21/LICENSE

## F5

- https://library.ldraw.org/parts/5544
- https://ldraw.org/article/218.html

---

# 17. First action for the implementing agent

Before writing scorer machinery:

1. read `AGENTS.md`, `ARCHITECTURE.md`, `ROADMAP.md`, `docs/agents/review-workflow.md`, `tools/corpus.py`, `tools/blind.py`, and `benchmarks/corpus.json`;
2. confirm current main/head because this research document may outlive code changes;
3. map this plan onto the current repository rather than creating duplicate authorities;
4. preserve the existing corpus request/answer wall;
5. implement **Slice A only** first;
6. run F1 through the real skill from request to STL + 3MF;
7. bring the real run/post-mortem back for review before generalizing the harness.

The benchmark should grow from failures observed in those runs. The goal is not a sophisticated scorer. The goal is five different real commissions whose failures tell us whether the skill can actually do the jobs it claims to do.
