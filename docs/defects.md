# Open defects

Implementation defects that are confirmed, reproducible, and not yet fixed.

[`AGENTS.md`](../AGENTS.md) says what to do about a defect a real job exposes:
add a failing regression fixture, make the smallest architecture-consistent fix,
run the affected replay. This file exists for the interval between *confirmed*
and *fixed*, which had no home before it and in which findings were being lost.

What this file is not:

* **not a planning authority.** [`ROADMAP.md`](../ROADMAP.md) owns sequencing.
  A defect here is a thing that is wrong, not a thing that is scheduled. Nothing
  here is a roadmap item, and a defect that turns out to need a capability the
  architecture does not have stops being a defect and becomes a roadmap or
  architecture change under [`ROADMAP.md` §3.8](../ROADMAP.md).
* **not a second description of behaviour.** [`docs/tooling.md`](tooling.md)
  describes what each tool does and points here where what it does is wrong.

An entry leaves this file when the fix and its regression fixture land, and the
`CHANGELOG.md` entry is where it goes.

Every entry carries: where it is, what is wrong, the evidence, what it can cause,
and the fixture that must fail before the fix lands.

## D1 — `diagnose` reports non-manifold edges as boundary edges

**Where.** [`pipeline/diagnose.py`](../skills/3d-modeling/scripts/pipeline/diagnose.py),
lines 112 and 317, surfaced at line 668 and in every `boundary_edges` field of a
diagnosis report.

**What is wrong.** The count is
`len(mesh.edges_unique) - len(mesh.face_adjacency)`. `face_adjacency` holds a
pair only for an edge shared by *exactly* two faces, so that expression counts
every edge that is not two-manifold — open edges and edges shared by three or
more faces alike — and reports the total under a name that means only the first.

**Evidence.** A real source artifact reported `boundary_edges: 332`. Its actual
condition was 322 boundary edges, 9 edges shared by three faces, and 1 edge
shared by four.

**What it can cause.** The number is what a reader acts on. "332 boundary edges"
points a repairer at hole-filling, which cannot close a three-face edge and
cannot close a four-face one, so the report hides the condition that actually
blocked every downstream tool. It is also the input to the `REPAIR_REQUIRED`
finding string, so the classification is right for a reason it states wrongly.

**Fixture that must fail first.** A mesh carrying one boundary edge, one
three-face edge and one four-face edge, asserted as three separate counts. A
fixture asserting only the classification passes today and would pass after a
wrong fix.

**FIXED** at `4adbf11`. `diagnose.edge_manifold_counts` counts faces per edge
off `edges_unique_inverse` — the face-use count directly, rather than anything
inferred from an adjacency table's shape — and the report carries
`boundary_edges` (now only edges used by exactly one face), `nonmanifold_edges`,
`max_faces_per_edge` and the whole `faces_per_edge` distribution. Both branches
that carried the expression are fixed: the mesh branch and the per-object 3MF
branch. A non-manifold edge now raises its own finding, worded so a repairer is
not sent at hole-filling: *"not a hole and cannot be closed by filling one"*. It
fires whether or not the mesh is also open, because a closed mesh can carry a
three-face edge — and that is precisely the case the old code was silent on, since
`watertight` was true, the boundary finding never printed, and the wrong number
was the only trace.

Fixture: `pipeline/test_phase3.py::EdgeManifoldCountsTest`, two fans sharing no
vertex — 16 unique edges, 14 used once, one used three times, one used four —
so the arithmetic is checkable by hand, and the old expression's 16 is asserted
to be exactly `boundary_edges + nonmanifold_edges`. Six mutations attempted, six
caught. Verified on the real vendored `ball_male_17mm.stl`: 10,584 edges, all
used by exactly two faces, `USABLE_MESH` unchanged.

## D2 — `make_3mf.py` writes vertices at `%.6g`

**Where.** [`make_3mf.py`](../skills/3d-modeling/scripts/make_3mf.py), `mesh_xml`.

**What is wrong.** Vertices are formatted `f'{x:.6g}'`. Six significant figures
over a part measured in tens of millimetres is a resolution of about 0.0001 mm
near 10 mm and coarser further out, and the written coordinate is not the
coordinate that was measured.

**Evidence.** Vertices moved by up to 0.0005 mm, which changed a part's volume in
the second decimal place.

**What it can cause.** The 3MF is the deliverable; the measurements that
authorized it were taken on the mesh in memory. Anything asserted about volume,
clearance or preservation is asserted about a slightly different part than the
one that ships. It is small, and it is exactly the class of difference a
tolerance band is supposed to be spent on deliberately.

**Fixture that must fail first.** Write a part whose coordinates exceed six
significant figures, re-read the file, and assert vertex-for-vertex equality and
volume equality within the writer's declared precision — where "declared" means
the writer states one.

## D3 — `make_3mf.py`'s round-trip check has never run in this environment

**Where.** [`make_3mf.py`](../skills/3d-modeling/scripts/make_3mf.py), the `try`
block after the write.

**What is wrong.** The self-check re-loads the written file through `trimesh`,
which needs `lxml` for 3MF. `lxml` is not in the `--frozen` runtime. The `except`
catches bare `Exception` and prints `wrote OK; round-trip verification skipped`,
so the failure is indistinguishable from a run in which the check passed unless
someone reads the line.

**Evidence.** The message is what the shipped runtime prints. There is no run in
this environment in which the check executed.

**What it can cause.** A verification that has never executed reads on a
transcript as a verification. It is also the only thing standing between D2 and a
reader who would notice it.

**Fixture that must fail first.** Two of them: one asserting the round-trip check
actually executes in the frozen runtime, and one asserting that when it cannot
execute the exit path says so in a way a caller can act on rather than in a line
of stdout. A bare `except Exception` around a verification is the shape of the
defect, not the missing dependency.

## D4 — `run-job` ignores a project it is standing in, and `status` reports its receipt

**Where.** [`pipeline/cli.py`](../skills/3d-modeling/scripts/pipeline/cli.py),
`run_job`, which calls `_load_job(job_dir)` and never looks for `project.json`.

**What is wrong.** Run in a directory that holds a `project.json` carrying edit
scopes, `run-job` reads `job.json` alone, builds a job with no edit scope and no
preservation obligation, and writes `final_status.json` into that directory.
`design-tool status` then reports that file as the project's status.

**What it can cause.** This is the claim-integrity shape, not a usability wart. A
project whose whole point is a declared edit scope gets a receipt from a run that
had none, in the project's own directory, under the project's own name. The
scope-free run is also the one most likely to succeed, because it is the one with
the fewest obligations.

`run-job` is deprecated, which limits exposure and does not close it: the
deprecated verb is still documented, still reachable, and the receipt it leaves
is read by the supported one.

**Fixture that must fail first.** A directory holding both files, where the
project declares an edit scope. `run-job` must refuse rather than proceed, and
`status` must not present a `final_status.json` whose bindings do not match the
project's.

## D9 — the confined build boundary denies writes, not reads, the network or Low-labelled paths

Numbered past the two it replaces on purpose: D7 and D8 were the boundary that
did not meet the gate and the tests that did not guard it, and both are closed.
Reusing their numbers would make every reference to them ambiguous. D5 and D6 —
the edit-intent fields that were declared, validated, and read by nothing — left
this file the same way and are in `CHANGELOG.md`.

**Where.** [`pipeline/confine.py`](../skills/3d-modeling/scripts/pipeline/confine.py),
`RESTRICTING_SIDS` and `LOW_INTEGRITY_SID`, and the mechanism they add up to.

**What is wrong.** Three of the confinement's ruled properties are unmet — two in
part, and one, since D11, not at all. None of them is a bug in the code; each is
the ceiling of the mechanism the boundary was ruled to use, and the entry exists
so that "no network capability" is not read as more than it is. Which for a while
it was: rows 2 and 3 have always said what they mean, and row 1 did not.

1. **Network. The property asked for is *no network capability*, and none of it
   is achieved: the network is open.** This row read "refused with `WSAEACCES`,
   DNS excepted" until D11 was investigated, and that was wrong. The evidence
   for it was one probe against `1.1.1.1:53`, a port NordVPN Threat Protection
   filters on this machine — identically with no confinement at all. Re-measured
   under the real restricted low-integrity token: `1.1.1.1:443` connects,
   `1.1.1.1:80` connects, `93.184.215.14:80` connects. All three firewall
   profiles are `DefaultOutboundAction=NotConfigured` and none of 741 enumerable
   rules blocks outbound 53. DNS resolves too, and by a second route:
   `gethostbyname` opens no socket in the calling process, it goes through the
   DNS Client service over RPC.

   So the candidate can read the repository, the project directory and
   `acceptance_contract.json`, and post all three. Nothing in this boundary
   contests it: process-thread attributes do not gate sockets, Low integrity does
   not gate sockets, and neither does the restricting-SID set.
2. **The Low-labelled corners of the user profile.**
   `%USERPROFILE%\AppData\LocalLow` and `%USERPROFILE%\AppData\Local\Temp\Low`
   carry an explicit *Low* mandatory label from Windows, so a Low-integrity
   subject can write to them by design. Nothing this pipeline reads lives there,
   and nothing on this machine auto-runs from there, so the exposure is a
   drop-box rather than a path back into a run — but "exactly one writable
   output directory" is, strictly, three.
3. **Reads.** The confinement is a *write* confinement. The candidate can read
   anything `BUILTIN\Users` can read, which includes the project directory and
   therefore `acceptance_contract.json`. It cannot change the contract, and the
   `build_input.json` it is handed still carries nothing about acceptance — but a
   candidate that goes looking can see the document it is measured against, and
   "measured against a document it is never shown" is now true of the protocol
   and not of the filesystem.

**Evidence.** `test_isolation.WhatTheConfinementEnforcesTest` runs one probe
model under the real boundary and reports sixteen rows. Eleven are asserted
closed, one — writing the build directory — is the capability the candidate is
supposed to have, and four are asserted *open*: the three limitations above, with
row 1 measured twice because an outbound socket and a DNS query are two different
mechanisms and both work. A change that closes one turns that test red, which is
the point: a limitation that quietly stops being one is a limitation nobody
updates the documentation for.

The table records what is true; it does not record what is owed, and for the
network those are different. So `test_the_boundary_denies_outbound_tcp` states
the property this boundary is *supposed* to have and is marked
`expectedFailure`. The suite stays green while the gap is open, and the day the
gap closes unittest reports an unexpected success — a red suite whose message is
"the boundary improved and this file did not".

**What blocks each.** Network and reads both want a mechanism the ruling did not
authorise. Read denial and a real network capability model are the same
mechanism:

* **`AppContainer`** — `CreateAppContainerProfile` plus
  `PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES` with an empty capability set.
  File access becomes deny-by-default for anything that does not grant the
  package SID, and network is a capability (`internetClient`) that is simply not
  granted, enforced by the Windows Filtering Platform rather than by an ACL. The
  cost is that the interpreter, the standard library and every installed package
  must be ACL'd for that package SID, which is a persistent change to shared
  locations outside this repository.
* A **`NULL`-SID lockdown token** (Chromium's `USER_LOCKDOWN`) would close the
  read gap without AppContainer, and does not work as a *primary* token: a
  process created with one dies at `STATUS_DLL_INIT_FAILED` before `main`,
  measured on this box. Reaching it needs the target to start under a permissive
  impersonation token and drop it after initialisation — which makes the confined
  program a participant in its own confinement, and means any lazily-loaded
  kernel DLL after that point fails.
* An **Untrusted integrity level** (`S-1-16-0`) would close row 2 outright, since
  nothing on the system is labelled Untrusted. Measured: a process created with
  an Untrusted primary token also dies at `STATUS_DLL_INIT_FAILED`. Low is the
  floor for a process that has to start.

**What it can cause.** Row 1 is an exfiltration channel, not a route back into
the gate — but it is a full-bandwidth one, not the few-bytes-per-hostname channel
this entry used to describe. Row 2 is a drop-box outside anything this pipeline
reads. Row 3 lets a candidate tailor geometry to the contract it will be measured
against — which is a weaker version of the defect this whole boundary exists to
close, and the one of the three worth closing first.

Row 3 also *aimed* D10, which is now closed: a candidate that can read the
contract knows the bands and the design id, and could once write a paragraph in
that vocabulary straight into the reviewer's packet. It can still read. It can no
longer write anything a reviewer sees.

**Fixture that must fail first.** For row 3, a model that reads
`acceptance_contract.json` from the project directory and reports its contents
through `PROVENANCE`, asserted to fail. It passes today, deliberately, in
`test_the_named_limitations_are_still_the_named_limitations`. For row 1,
`test_the_boundary_denies_outbound_tcp` is already on disk and already failing.

D10, D11 and D12 were here and are closed; `CHANGELOG.md` has them. D11's
correction is folded into row 1 above rather than carried as its own entry,
because what it found was not a second defect — it was that this row was
describing a property the boundary does not have.

D13 and D14 were here and are closed, and so are D16, D18, D19 and D20;
`CHANGELOG.md` has all six. D14 leaves one thing behind that is worth writing
down: its own description was wrong about the file. `vent_mount.step` has **six**
cone faces OCC cannot triangulate, not four, plus a seventh — a plane of
1.75e-14 mm² — that fails the same way when the shape has not been meshed as a
whole first. The diagnosis was right and the count was not, and the artifact is
still untessellatable, which is [D22](#d22--the-vent-mounts-cone-faces-are-still-untessellatable).

## D15 — `orientation` is declared, validated, frozen, and read by nothing

**Where.** `Contract.orientation`, validated in `contract.preflight`, carried into
the frozen payload.

**What is wrong.** Third instance of the shape D5 and D6 recorded: a field the
schema takes seriously and no code consumes. `model_to_printer_matrix` and
`bed_z_mm` reach no analysis, no screening, no manufacturing check.

**What it can cause.** A job can declare a print orientation, have it validated
and hashed into the acceptance contract, and have nothing whatsoever depend on
it. Overhang, bridging and strength direction are all orientation-dependent.

**Fixture that must fail first.** Two contracts differing only in orientation,
asserted to produce different assessments.

## D21 — a lane cap that only downgrades a passing verdict

**Where.** `pipeline/status.py`, the `lane_status` interaction.

**What is wrong.** `EXPERIMENTAL_UNAVAILABLE` replaces a verdict that would
otherwise be `COMMISSIONED` or `VERIFIED`. When commissioning fails first the
final status is `FAILED` and the cap never applies — so on the vent-ball fixture
the MODIFY lane's own cap is unreachable.

**What it can cause.** Documentation, ADR 0002 and this project's own reporting
have repeatedly said "every job declaring an edit scope reports
`EXPERIMENTAL_UNAVAILABLE`". That is true only of jobs that would otherwise pass.
The claim has been made in commit messages and in `docs/tooling.md` without that
qualifier.

**Fixture that must fail first.** An edit-scope job that fails commissioning,
asserted to report both the failure and the lane's unavailability rather than one
of them.

## D22 — OCC cannot mesh six legal cone faces in the vent mount

**Where.** `benchmarks/fixtures/vent-ball-combine/public/sources/vent_mount.step`,
and therefore `ROADMAP.md` Release 1's authentic exercise.

**What is wrong.** A bounded limitation in our mesher on legal geometry — not,
as this entry previously said, a broken source. The distinction decides whether
the honest statement is about the user's data or about our toolchain.
`BRepMesh_IncrementalMesh` returns `IsDone() = True` with
`GetStatusFlags() = 4` (`IMeshData_Failure`) on five cone faces of the
hinge-pivot bore.

**Two instruments, two counts, and the larger one is the one to fix against.**
The five above are what the mesher's own status flags report. The per-face
probe `mesh_io.tessellate_brep` runs — the one every consumer of this file
actually goes through — reports **six**, measured at `0cb4302`:

```
face 93  (GeomType.CONE) at (19.150, 28.865, 53.305)
face 107 (GeomType.CONE) at (-5.850, 28.865, 53.305)
face 225 (GeomType.CONE) at (19.023, 28.744, 53.351)
face 227 (GeomType.CONE) at (21.941, 28.744, 53.351)
face 233 (GeomType.CONE) at (-5.977, 28.744, 53.351)
face 235 (GeomType.CONE) at (-3.059, 28.744, 53.351)
```

All six are cones, all six raise `'NoneType' object has no attribute NbNodes`,
and `design-tool diagnose` classifies the file `REPAIR_REQUIRED` on them. The
discrepancy is not a regression — it is two different questions, one asked of
the shape-wide mesher and one asked face by face — and it is recorded because a
bounded repair will be measured against a count, and six is the number a repair
has to clear.

**Evidence that the faces are legal.** Every structural hypothesis was measured
and refuted: `BRepCheck_Analyzer(face).IsValid()` is True for all of them;
`ShapeAnalysis_Wire` reports Order, Connected, SmallEdges, Degenerated,
SelfIntersection, Closed and Gaps3d clean, MaxDistance3d 8.4e-08 mm; outer-wire
orientation follows the file's own convention; every bounding edge lies within
2.918e-07 mm of its cone, inside the edges' declared tolerances; every edge has
a pcurve and none is degenerate.

Three things settle it. `BRepBuilderAPI_MakeFace` on the **same**
`Geom_ConicalSurface` over the **same** UV range meshes perfectly, 502 nodes —
so the surface is sound and the failure is BRepMesh's handling of this
seam-closed boundary representation. Faces 96 and 106 are geometric twins of two
that fail — same surface parameters, same area to six decimals, same 5-edge
1-seam wire — and they mesh. And **gmsh triangulates all six**, 204 triangles
each. Identical data on either side of a cliff is a numerical robustness
failure, not a structural defect in the file.

The STEP contains **zero `PCURVE` and zero `SEAM_CURVE` entities** — every
pcurve and seam is manufactured by OCC's own reader from an ordinary AP214
`CONICAL_SURFACE` plus an `EDGE_LOOP`. OCC 7.9.3 is the newest available, so a
version bump is not a remedy.

**Corrections to this entry's earlier text.** It is **five** faces that fail at
every deflection, not six: face 94 triangulates at angular deflection ≥ 0.12 rad
and fails at ≤ 0.10. And the cascadio figures quoted here — 324 bodies, 8,284
boundary edges — do not reproduce, because both depend on the vertex-merge
tolerance and the trimesh version and this entry stated neither. Re-measured,
cascadio returns 658 raw bodies, 10 after a 1e-5 mm merge, still no cone
triangles, in **metres**.

**The file is separately unclean, in other faces.** Face 101, a plane of
1.75e-14 mm², is the only one of 329 that `BRepCheck_Analyzer` calls invalid
(`BRepCheck_UnorientableShape`, wire `BRepCheck_SelfIntersectingWire`), and it is
why the whole-shape check fails. gmsh independently refuses three surfaces — a
BSpline patch and two planes 0.0066 mm and 0.0028 mm thick. Those slivers are
real defects. They are not the six cones.

**What it can cause.** Preservation cannot be measured against the repository's
only `PHYSICALLY_PROVEN` source. Release 1's exercise completes with that row
`UNAVAILABLE` / `PRESERVATION_UNMEASURABLE`, which is deterministic and bound to
the same hashes as a measured row — so the gate's nine proofs are unaffected —
but no claim may be made that the instrument was exercised on the proven
artifact.

**What would close it.** A bounded, disclosed repair, prototyped and measured:
`ShapeUpgrade_ShapeDivideClosed` then `ShapeFix_Shape` makes all 345 faces
tessellate by splitting 16 closed faces at their seams. Topology only — 74
distinct analytic surfaces before and after, **zero added and zero removed at
`repr()` precision**, every cone and cylinder axis, radius and semi-angle
bit-identical, maximum on-face deviation **4.02e-14 mm**, the 50 × 60 phone-rest
datum plane identical to six decimals. That is `ROADMAP.md` Release 6's *Bounded
repair* slice and its first fixture, not a defect fix, and its result must be a
separate artifact that never overwrites the supplied file.

**Fixture that must fail first.** `L0UntessellatableStep`, inverted: the same
file asserted to tessellate completely.

## D23 — the function built to prevent a false clean verdict returns one

**FIXED.** The enumeration half, at `0cb4302`+1. The zero-volume half is
restated below as what it actually is, and is not this defect.

**Where.** `mesh_io.tessellate_brep`, and `validate_brep_tessellation` behind it.

**What was wrong.** `BrepTessellation.complete` was `not self.failures`, and a
shape the function cannot walk produces an empty failure list — so it returned
`complete=True` for input whose faces it cannot enumerate. There are three
answers, not two: every face read, some face failed, and *nobody looked*. The
third is not a weaker version of the first.

**Evidence.** Hit twice by accident while investigating D22:
`build123d.Shape.cast` returns `None` for a `ShapeFix_Shape` result, and that
`None` arrived here — `getattr(None, "faces", None)` is not callable, so the
early return produced a clean reading of nothing.

**What it could cause.** This is the exact function added in `a792b67` to stop
`diagnose` calling an untessellatable STEP clean, so it was a false clean in the
false-clean detector, and it reached all three consumers:
`diagnose` classified such a file `USABLE_EXACT`; `validate_brep_tessellation`
let it through the gate in front of every B-rep export; `preservation` proceeded
to measure against it and died one line later on an empty vertex array. Two of
those three are silent.

**The fix.** `BrepTessellation` gains `enumerated`, and `complete` becomes
`enumerated and faces > 0 and not failures` — three conjuncts, each of which was
a false clean that reached a caller. `summary()` distinguishes all three states,
and the receipt carries `enumerated` so a reader of the evidence can tell "this
shape has no faces" from "this shape was never walked". `diagnose` and
`preservation` stopped printing "0 of 0 face(s) cannot be tessellated".

**Fixtures.** `test_mesh_io.BrepTessellationDiagnosticTest` — a `None` shape, a
shape with no `faces()`, a shape whose `faces` is not callable, a shape
enumerating zero faces, and the positive case that must still report complete.
Seven mutations of the protection attempted, seven caught. Verified against real
geometry: `vent_mount.step` still reports `REPAIR_REQUIRED` over 329 enumerated
faces, and `design-tool selftest` still exports all five certified templates
through `validate_brep_tessellation`.

**Not fixed, and not this defect: a zero-volume shape reported `complete=True`
with 33,683 triangles.** That reading is *correct* about tessellation — every
face was walked and triangulated. What was wrong is a caller reading "every face
tessellated" as "this is a usable solid". `complete` is a statement about
coverage of the enumeration, and widening it to mean fitness would put a
solidity judgement inside a function whose whole job is to report what it could
read. Whatever gate should refuse a zero-volume export belongs beside the other
integrity checks in `compute_integrity`, and nothing has yet established that
this shape can reach an export path — so it is recorded here rather than
promoted to a defect nobody has reproduced deliberately.

## D24 — coverage is a ratio against the contract that declared it

**Where.** [`pipeline/commission.py`](../skills/3d-modeling/scripts/pipeline/commission.py):435-437.

```python
declared = [f for f in contract.features if f.mandatory]
covered  = [c for c in checks if c.feature_id and c.ran]
coverage = len(covered) / len(declared) if declared else 1.0
```

**What is wrong.** Nothing, for the job it was written for: within one run,
coverage answers "was the contract this job froze actually checked", and
`minimum_coverage` refuses a run that measured less of its own contract than it
promised to.

It becomes a defect the moment two formulations are set beside each other. A
formulation declaring three mandatory features and covering all three scores
1.0. A sibling declaring eight and covering all eight also scores 1.0. The number
is a ratio to a denominator each formulation chose for itself, so it says nothing
about which contract was more demanding — and a designer who declares less scores
exactly as well as one who declares more.

**Evidence.** Found by scoping Release 4 (`docs/release-4-scope.md`), by asking
what a comparison could honestly report rather than by building one. Both
formulations of the recorded `branch-knob-seat-fallback` case reach coverage 1.0
against separately authored proposals.

**What it can cause.** Any comparison that ranks or scores formulations on
coverage rewards declaring fewer obligations. `ARCHITECTURE.md` 8.5 forbids a
weighted total hiding a mandatory failure; this is the same failure one level
down, where the *set* of mandatory checks differs and the ratio conceals it.

**What would close it.** Release 4's scoping proposes the structural answer
rather than a scoring fix: a comparison refuses to rank formulations whose
mandatory check sets differ, and says so — `INCOMPARABLE_CHECK_SETS` — instead of
producing a number that reads as comparable. Coverage itself needs no change.

**Fixture that must fail first.** Two formulations of one job with different
mandatory feature sets, both at coverage 1.0, asserted to be reported as
incomparable rather than equal.

## D25 — a formulation is graded against the rubric its own proposal wrote

**Where.** [`pipeline/acceptance.py`](../skills/3d-modeling/scripts/pipeline/acceptance.py):316-325
and :357-359, reaching [`pipeline/runner.py`](../skills/3d-modeling/scripts/pipeline/runner.py):766-802.

**What is wrong.** Nothing, within one run: an authored job has to get its
expectations from somewhere, and the designer's proposal is the only thing that
knows what the part is supposed to be. The proposal is frozen before any
geometry exists, and the pipeline owns every band, so a formulation cannot
loosen a gate after seeing its own result.

It becomes a defect the moment two formulations are set beside each other. On
the authored lane the proposal sets **three** things that the checks are then
measured against, and all three are per-formulation while everything a reader
assumes is shared is shared:

1. **the check set.** `declared` is that formulation's own mandatory features
   (`commission.py:436`). This is D24, and it is the face that needs a fixture
   constructed — no committed case exercises it.
2. **the expectation.** `expected_bbox_mm` and `expected_bodies` come from the
   proposal (`acceptance.py:358-359`) and are what the always-present
   `envelope`, `bodies` and `unit_scale` checks measure against.
3. **the band.** A feature's tolerance is computed from the magnitude the
   proposal declared — `contract.area_tolerance` is 0.5% of it, floored at
   1 mm² — so declaring a larger number buys a looser band.

**Evidence.** Face 2 is live in the only recorded branched case, with nothing
constructed. In `benchmarks/replays/branch-knob-seat-fallback`, the root
formulation's `design_proposal.json` declares `bbox_mm.z = 50.0` and
`plate-seated`'s declares `52.0`. Each was checked against its own declaration
to a band of 0.5, and `expected.json` records `envelope` as `PASS` for both.
Face 3 is arithmetic on `contract.area_tolerance`: a row declaring 881.33 mm² is
graded to ±4.41 and one declaring 2000.0 mm² to ±10.0. Both faces were found by
building `design-tool compare` and asking what two PASSes actually assert.

**What it can cause.** Any report that prints one formulation's verdicts beside
another's asserts an equality nobody measured. "Both passed" is two separate
self-assessments printed adjacently, and on the recorded knob it would tell a
reader the two formulations are equal on envelope when one is 2 mm taller by
design. It is `ARCHITECTURE.md` 8.5's rule one level down, in the place a
weighted total is not needed to hide a mandatory difference — adjacency does it
unaided.

**What would close it.** Not a scoring fix and not a schema change. The
comparison refuses: `INCOMPARABLE_CHECK_SETS` where the sets differ,
`INCOMPARABLE_EXPECTATIONS` where the same check was measured against different
expectations or bands, and it names which. Shipped for the comparison path in
`pipeline/compare.py`. What is **not** closed is every other reader: nothing
stops a person or an agent reading two `commission_report.json` files side by
side and drawing the equality themselves, and no receipt says on its face that
its expectations were self-declared. Closing that needs the requirement-to-check
edge Release 4 has not built.

**Fixture that must fail first.** Two formulations declaring different
`bbox_mm`, both PASS on `envelope`, asserted to be reported
`INCOMPARABLE_EXPECTATIONS` rather than equal —
`pipeline/test_compare.py::TheRubricIsNotSharedTest`. Fifteen mutations of the
protections in that file were attempted and fifteen were caught.

## D26 — `status` reports two formulation counts for one job, and drops the root

**Where.** [`pipeline/cli.py`](../skills/3d-modeling/scripts/pipeline/cli.py):1759
against :1783.

```python
for row in project.alternatives:            # :1759 -- no row exists for the root
for key in [ROOT_ALTERNATIVE] + [row.alternative_id
                                 for row in project.alternatives]:   # :1783
```

**What is wrong.** `design-tool branch` never writes an `alternatives` row for
the shared root (`cli.py:2026-2029`) — the root is a formulation by having a
directory, a proposal, a contract and its own receipts, not by being declared.
So the `alternatives` block in one `status --json` report iterates two
formulations on the recorded knob while the `cost` block in the same report
iterates three. The two disagree about what the job is.

A second, quieter half: the loop calls `_derived_at` per sibling, which returns
`derived_status`, `stored_status`, `allowed_claim`, `stale` and `reasons`, and
keeps two of the five. `tools/replay.py:958-987` is the proof it is missed —
to read per-formulation staleness the harness has to issue `branch --activate`
and `status` once per formulation.

**Evidence.** Found while building `design-tool compare`, by asking where a
comparison should get its formulation set from. `compare` takes the union
(`cli.py`, `compare`) rather than reading `report["alternatives"]`, and
`pipeline/test_compare.py::TheCommandSurfaceTest::test_the_shared_root_is_one_of_the_formulations`
asserts the root is compared.

**What it can cause.** Any caller that takes its formulation set from
`status --json`'s `alternatives` silently omits the shared root — which on the
knob is one of the two designs. A comparison built that way would drop a
formulation and report the remainder as the whole.

**What would close it.** Iterate the union in `status` as `cost` already does,
and stop discarding the three derived fields. Deliberately **not** done in the
commit that found it, for a reason that has since expired: at the time the L1
replay suite could not execute on Linux at all, and changing a golden-feeding
command on a platform that cannot run the goldens is how a recording breaks.
`pipeline/confine_posix.py` removed that constraint — the suite now runs here and
reproduces its digests — so this is ordinary work on any platform, and what
remains is only that nobody has done it.

**Fixture that must fail first.** A branched project where
`len(status_report["alternatives"]) + 1 == len(status_report["cost"]["by_alternative"])`,
asserted to become equal.

## D27 — the comparison's material axis read a shape no run has ever written

**Where.** [`pipeline/compare.py`](../skills/3d-modeling/scripts/pipeline/compare.py):474,
before this commit:

```python
volume = ((report.get("screening") or {}).get("detectors") or {}).get("volume") or {}
```

**What is wrong.** `screening.run` returns `detectors` as a **list** of rows,
each carrying its own `detector` key (`screening.py:294`). Reading it as a
mapping keyed by detector name raises `AttributeError` on a real receipt, so
`compare`'s `volume_mm3` and `volume_detector` — the whole material axis
`ROADMAP.md`'s Release 4 asks for — could never be produced.

**Why nothing caught it.** Every fixture that exercised the line was authored
against the reader rather than the writer. `test_compare.py:189` built
`"detectors": {"volume": {...}}`, and twenty-two L0 fixtures then agreed with
each other and with nothing the pipeline produces. The suite was green, the
verb was "shipped", and the defect was one command away the whole time: the
first `design-tool compare` pointed at the recorded knob raised inside a dict
comprehension.

**Evidence.** Found by running the verb on
`benchmarks/replays/branch-knob-seat-fallback` while wiring the compare step
into the L1 recording — the work `ROADMAP.md` listed as owed. Reproduced by
reverting the reader with the fixtures left correct: 21 of 25 tests in
`test_compare.py` fail, which is the measure of how much the fixtures were
holding up on their own.

**Status: FIXED**, in two goes, and the first go is worth recording because it
made exactly the mistake this defect is about.

The first fix added `screening.detector(report, name)` and called it "the single
reader". An independent review found it was not: `tools/replay.py:1241` still
built `screening_detail.detectors` with `for row in screening.get("detectors",
())` — inside `_observe_dir`, the very function this record claimed had been
routed through the pipeline's reader. One caller fixed and one caller left is
not one reader; it is one reader and one place the next shape change surfaces as
a bare `AttributeError`.

So the reader is now `screening.detectors(report)`, returning the list, and
`detector(report, name)` is a lookup built on top of it — neutering the first
takes the second with it. Both live beside `screening.run`, the single writer.
`detectors` raises `ScreeningShapeUnexpected` on a non-list rather than
returning `[]`, because a reader that shrugged would have reported "no volume
measured" on every job forever, and that is a sentence nobody thinks to doubt.
`cli.compare` catches it beside `CompareError` and returns 2: loud is right,
but gate 4.1 asks for controlled failure rather than a stack trace.

Remaining subscript readers, deliberately: `test_pipeline.py:364` and three
sites in `benchmarks/heavy/test_phase2_heavy.py`. They are tests asserting on a
receipt they have just watched a run write, which is the one place reading the
shape directly is the point.

**What this is really evidence for.** A fixture written from a reader tests the
reader against itself. The protection that catches this class is a tier that
runs the verb against receipts a real pipeline wrote, which is what the compare
step in the L1 recording now is.

## D28 — two columns of one design are printed side by side and not named as one

**Where.** [`pipeline/compare.py`](../skills/3d-modeling/scripts/pipeline/compare.py),
`_identical_designs`: it groups formulations by
`reading["bindings"]["source"]`, and `bindings.current` (`bindings.py:119`)
reads that digest off disk **now**.

**What is wrong.** On `benchmarks/replays/branch-knob-seat-fallback` the shared
root and `as-drawn` are one design under two ids. Their receipts say so:

```
.          artifact_hashes = {source: 1e9b9ea…, contract: 4b52016…, stl: 50463d3…}
as-drawn   artifact_hashes = {source: 1e9b9ea…, contract: 4b52016…, stl: 50463d3…}
```

and every measured value the comparison prints for them is identical —
`volume_mm3` 47526.263 against 47526.263, envelope 38×38×50 against 38×38×50.
`identical_designs` is nonetheless `[]`, because `as-drawn`'s `model.py` was
revised after its run concluded and is `d3da8e4…` on disk. The block that exists
to stop a reader taking that agreement for two designs independently reaching
one answer is silent on the only case in the repository that exercises it.

**Evidence.** Measured, not inferred: the digests above are read off the two
`final_status.json` files a replay of the case writes, and
`benchmarks/replays/test_l1_replay.py::BranchKnobSeatFallbackTest::test_two_columns_of_one_design_are_not_reported_as_such_and_that_is_a_defect`
asserts all three facts together — same source digest, identical material, empty
`identical_designs`.

**Not the same thing as the mitigation.** `as-drawn` is reported `STALE` and its
mandatory verdict weakens to `UNKNOWN_STALE`, so a careful reader has *a* reason
to discount its column. That is the claim "this formulation's evidence no longer
binds", which is a different claim from "these two columns are one design", and
only the second one stops the agreement being read as corroboration.

**Scope.** The trigger is precisely an input revised after the run. Two
byte-identical siblings that nobody touched afterwards still group correctly.

**What would close it.** Group on the source digest the receipts were *produced
from* — `final_status.json`'s `artifact_hashes.source` — rather than the digest
on disk, since the columns being compared are the receipts and not the working
tree. Not done here: it changes what a frozen recording says, so it gets its own
slice.

**Fixture that must fail first.** The L1 assertion above, inverted: it currently
pins `identical_designs == []` and says in its own message that the fix turns it
into `[[".", "as-drawn"]]`.

## D29 — a declared tolerance in the wrong shape is silently ignored by the replay band

**Where.** [`tools/replay.py`](../tools/replay.py), `_band_for`:

```python
if isinstance(tolerance, dict):
    declared = abs(float(tolerance.get("abs") or 0.0))
```

**What is wrong.** A check whose `tolerance` is a bare number rather than a
`{"abs": …}` mapping falls through to the computed default. On
`benchmarks/replays/branch-knob-seat-fallback` the `envelope` check records
`tolerance: 0.5`, so the replay compares that measurement at 0.251 mm — the
0.5% + 1e-3 default — rather than at the 0.5 mm the receipt declares.

**Why it is recorded rather than fixed.** The direction is safe: the band in use
is *tighter* than the declared one, so nothing passes that should fail, and
"fixing" it would loosen a live protection by a factor of two. There is also a
real question underneath it, which is whether a replay band should read an
acceptance tolerance at all: a contract's tolerance says how far a part may be
from its target and still be acceptable, while a replay band says how far a
rerun may be from the recording and still be the same run. Those are different
questions, and `_band_for` currently answers the second with the first's number
where one happens to be in the expected shape.

**Evidence.** Found by an independent review of Release 4 slice 2 while checking
whether the new `material` band was real protection. Measured on the knob:
`volume_mm3` band 237.63 mm³ against a 2266.6 mm³ signal between the two
designs; `bbox_mm.z` band 0.251 mm. Probed — +200 mm³ passes, +300 mm³ fails;
+0.2 mm passes, +0.3 mm fails.

**What it can cause.** Nothing today, and that is why it is a note rather than a
repair. What it would cause is a maintainer reading `_band_for` and concluding
that declared tolerances are honoured, then writing one as a bare float and
believing they had widened a band they had not touched.

**What would close it.** Decide the question above first. If a replay band
should never read an acceptance tolerance, delete the branch and say so; if it
should, accept both shapes. Either way the knob's recording moves, so it is a
slice with a re-record and not a one-line change.
