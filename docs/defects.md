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
   rules blocks outbound 53.

   **The DNS half of this row is retired, and the route is now explicitly
   unproven.** It read "DNS resolves too, and by a second route: `gethostbyname`
   opens no socket in the calling process, it goes through the DNS Client service
   over RPC" — and the suite never observed that. Its probe resolved
   `example.com`, which does not resolve on this machine with no confinement at
   all, so the row reported denied here whatever the boundary did. Re-aiming it
   at `localhost` made it deterministic and stopped it observing the property:
   measured, after `ipconfig /flushdns`, resolving `localhost` leaves no
   `localhost` entry in the DNS Client cache while hosts-file names like
   `kubernetes.docker.internal` are cached, so that lookup does not traverse the
   service. The only names that both resolve offline and traverse it are this
   machine's own hosts-file entries, which a suite cannot rely on and must not
   write, so **no deterministic instrument in this repository establishes that
   the DNS Client route is open.** The row is renamed `local_name_resolution`,
   removed from the limitations tuple, and a guard fails if any DNS row returns
   to it. The socket evidence above stands on its own and is unaffected: the
   network is open, and `network_tcp_connect` measures it.

   That `gethostbyname` reached the service was observed by hand on one machine.
   It is kept here as exactly that — a machine-specific observation, not durable
   release evidence.

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
supposed to have, and three are asserted *open*: the three limitations above.
Row 1 was measured twice, by an outbound socket and by a DNS query, on the
argument that they are two different mechanisms. **That second measurement is
withdrawn** — see row 1 — and the socket carries the row alone. A neutral
`local_name_resolution` row still runs and is deliberately not among the
limitations, because local name resolution is not a property this boundary
contract cares about. A change that closes one turns that test red, which is
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

**Status: FIXED.** `cli.status` iterates the union -- the shared root plus every
declared alternative -- and the root's row is synthesised in the report rather
than written into `project.json`. That distinction is the whole of the fix's
scope: a declared row for the root would make it a thing a user could reject or
supersede, and would move what every existing project deserialises to. It goes
through the same `Alternative.as_dict()` as any other row, so a basis nobody set
is absent rather than empty, and the root is a formulation rather than a special
case.

The quieter half is closed too: all five fields `_derived_at` computes reach the
report, so per-formulation staleness is readable from one call.

**Fixture:** `pipeline/test_alternatives.py::OneJobHasOneFormulationCountTest`,
three tests. Before the fix the counts are 3 against 4 and the `stale` field is
absent; two mutations were attempted -- the root dropped from the union, and the
three derived fields dropped again -- and both were caught.

**What the fix did *not* move, which is worth recording.** The L1 recordings did
not change. `tools/replay.py`'s `_derive_all` never read the broken block: it
issues `branch --activate` and `status` once per formulation and reads
`final_status`/`stored_status`/`stale` from each. So the harness's workaround is
also the reason the goldens were never exposed to the defect. That workaround
can now be one call, which would also stop a replay leaving the project parked
on whichever formulation it activated last -- separate work, because it changes
the recorded exit sequence.

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

**Deliberately not closed in the D15/D28 closure pass, and the reason is worth
keeping.** The obvious "fix" — accept a bare float so that `_band_for` honours
both shapes — would **widen a live band by a factor of two** on the one
recording that exercises it, in exchange for making an input shape look
consistent. A protection is not improved by being loosened to match the
documentation of its own input. And the two numbers still answer different
questions: an acceptance tolerance says how far a *part* may be from its target
and remain acceptable, a replay band says how far a *rerun* may be from the
recording and still be the same run. Until that question is settled, the
conservative behaviour stands and this entry stays open rather than being
converted into a change that trades protection for tidiness.

## D30 — for some references the interface dimension *is* the answer dimension

**Where.** [`benchmarks/corpus.json`](../benchmarks/corpus.json), and the whole
blind-benchmark premise in [`tools/blind.py`](../tools/blind.py).

**What is wrong.** A blind request states what the part must fit and withholds
the part's own size. For `voron-deck-support` those are the same number. The
part bolts flat against a 20 mm extrusion face, so it is 20 mm across: its
x-extent *is* the interface. `extrusion_series: "2020"` was refused by the
coincidence check for exactly this reason — 2020 states 20, and 20.0 mm is the
answer — and removing it removed information the designer needed.

**Evidence.** The first blind run, scored against the withheld reference:

```
OFF smallest  8.200 against  5.800  (+2.400, band 0.116)
OFF middle   12.000 against 14.495  (-2.495, band 0.290)
OFF largest  16.000 against 20.000  (-4.000, band 0.400)
OFF volume   1023.19 against 1068.534         (4.2% out, band 2%)
ok  bodies        1 against       1
ok  watertight True against    True
```

The designer's own report named the cause before the score was run: *"No
extrusion profile size is given (2020? 2040? 1515?). That is what actually sets
how far the panel edge sits from the slot centreline, and therefore the pad
length and the total X."* It also ranked, unprompted, the depth along the
extrusion as its largest unconstrained axis: *"Nothing stated touches it. A
reference at 8 or at 20 is equally consistent with the brief."*

**What it can cause.** A benchmark that is unanswerable rather than hard, and
reports the difference as a low score. Two of the three failing axes here are
traceable to information the question could not carry: one because stating it
would state the answer, one because nothing in the brief constrains it at all.
A reader taking `OFF, OFF, OFF` as a measure of the designer is reading a
property of the question.

**What it is not.** A reason to hand the dimension over quietly. The coincidence
check is right that `"2020"` on a 20 mm part is the answer; what is wrong is
concluding that the request is therefore fine without it.

**What would close it.** One of three, and the choice is a design decision
rather than a repair:

* **declare the disclosure.** State the extrusion series, record in the manifest
  that the x-extent is thereby given, and score the remaining axes. This is
  `request_vocabulary` from the second design returning in a principled form —
  a *declared* disclosure rather than an exemption, with the score's denominator
  shrinking to match.
* **choose references whose interfaces do not fix their envelope.** A part that
  clips into a slot without spanning a face has an interface that constrains it
  without determining it. None of the four committed entries is clearly that.
* **score what the question can constrain.** Drop the axis the interface fixes
  from the comparison and say so, which makes the score narrower and honest
  rather than wide and misleading.

**Fixture that must fail first.** A test asserting that for each entry, every
axis the score compares is constrained by something the request states — which
fails today on `voron-deck-support`'s x, and would fail on its y for a different
reason.

**Partly closed, and the second run is why the rest is still open.** The first
option is built: an entry may declare, in writing, which of the reference's own
measurements the question gives away and why (`benchmarks/corpus.json`
`discloses`, enforced in `corpus.request_view`). Declared coincidences are
permitted, undeclared ones still refused, a disclosure that gives away nothing
is refused as an exemption in disguise, and `blind.score` marks a disclosed axis
`given` and reports how many axes were actually reconstructed.

A second blind run — a fresh designer, the improved brief now stating
`extrusion_series: 2020` — measured what that bought:

```
OFF smallest    10.000 against   5.800  (+4.200)     run 1: +2.400
OFF middle      20.000 against  14.495  (+5.505)     run 1: -2.495
giv largest     20.000 against  20.000  (+0.000)     given, not earned
OFF volume    2826.376 against 1068.534              run 1: 1023.190
```

Two things follow, and the second is the finding.

**The disclosure mechanism earns its place on first use.** The given axis came
back exact. Without the `giv` mark that reads as a perfect row and an
improvement over run 1; it is the question's own number reflected back, and
crediting it would have been the flattering score the mark exists to refuse.

**Stating the interface did not make the question answerable.** The two
genuinely reconstructed axes got *worse*, and both designers — independently,
with no shared context — named the same cause. Run 1: *"the depth along the
extrusion is unconstrained by the brief. A reference at 8 or at 20 is equally
consistent with the brief."* Run 2: *"the brief constrains the part's
cross-section well and its plan size barely at all. A scorer weighting bbox
extents is largely scoring whether I guessed the same lip overlap and foot
length as the original author, which no amount of engineering recovers from the
four stated numbers."*

So the bounding box is mostly free parameters. What the brief does pin is the
cross-section — rebate depth from `panel_stock`, bore from `fastener_thread`,
key width from `extrusion_slot_opening` — and those are the dimensions a person
means by *critical*. The benchmark currently scores the ones the question cannot
constrain and cannot score the ones it can, because measuring a rebate depth on
an arbitrary mesh is feature recognition and that is Release 6/7.

**What remains open, restated.** Not "which of three options", but: the score
compares an envelope the question does not determine. Until it can compare a
feature, a low score on these entries is substantially a fact about the
question. The honest interim is what the report now says — how many axes were
reconstructed rather than given — and not a claim that the number measures a
designer.

## D31 — a datum's contents are not in the acceptance contract that depends on them

**Where.** `pipeline/cli.py::_requirement_hash`, against
`pipeline/cli.py:1229` where an edit scope freezes `datum_ids`.

**What is wrong.** A scope records *which* datums it depends on and the
requirement hash does not record *what they said*. `_requirement_hash` covers
the brief, `STATED`/`INHERITED`/`MEASURED` requirements, the envelope, the
interfaces, the components and the modifiers, and its docstring names its own
subject as "the values somebody stated or measured". `project.datums` is not in
it. So a datum that keeps its `datum_id` while its value, unit, provenance or
`derived_from` revision changes leaves the frozen contract byte-identical, and
a review answer bound to the old reference keeps binding.

**Evidence.** Read rather than run: `_requirement_hash` builds its payload from
six keys and `datums` is not among them, and `cli.py:1229` writes
`{"datum_ids": list(scope.datum_ids)}` — identifiers, no contents.

**What it can cause.** A stale acceptance revision that should have been cut.
This is the D28 shape — a key that names a thing rather than what the thing
established — and D15's — one question answered in two places. It was filed
rather than fixed because the claim path it would corrupt is already capped:
every job with an edit scope is held at `EXPERIMENTAL_UNAVAILABLE` because
sample density is not derived from a declared minimum detectable defect size, so
no successful preservation claim is reachable through it today. That cap was the
fail-closed, and it is the reason this was a defect and not a stop.

**The fixture that must fail before the fix lands.** A project whose scope names
one datum, run to a frozen contract; the datum's value changed with its id kept;
the contract re-derived. The test must show the requirement hash moved and the
stored review answer refused. It must fail against today's implementation.

**Status: FIXED.** `cli._referenced_datums` binds `Datum.as_dict()` verbatim for
exactly the datums some `EditScope.datum_ids` names — one entry per identity,
sorted by `datum_id` — and `cli._requirement_payload` carries them under a key
that is *absent* when nothing references one. Only referenced datums participate,
which is §13.4's "a binding that a job does not use does not participate in its
identity"; two scopes sharing one datum bind one entry, which is decision 4 held
in the serialization rather than in prose.

Three properties are worth recording because each was a choice rather than a
consequence. The contents live in the requirement payload and *not* on the
preservation row, because contents per row would write one datum's number twice
into one contract — the two-authorities failure the ADR was written from,
rebuilt. `as_dict()` is bound verbatim rather than field by field, because a
hand-built projection carries the fields its author remembered and drops `owner`,
`settled_by`, `note`, or whichever field is added next; a fixture asserts the
bound row *equals* `Datum.as_dict()`.

The precise claim, third: **the contract binds `Datum.as_dict()` verbatim, and
`Datum.as_dict()` canonicalizes the order of the set-valued `valid_for` field.**
Datum values, units and provenance are **not** normalized, and neither is the
loader's malformed-input behaviour. `valid_for` is sorted because `Project.validate` reads it as a
membership set — `set(datum.valid_for) & ({scope.artifact_id} | set(scope.interface_ids))`
— so two declarations differing only in the order of the same scopes are one
declaration to every check that consumes them, and identity was distinguishing a
state the model does not. Measured: `("src", "drawer")` hashed `50db5e53…` and
`("drawer", "src")` hashed `0a239014…`, which cut a spurious acceptance revision and
refused a review answer over a difference that says nothing. Over-invalidation, so
never a false success, and still a canonicalization defect. It is sorted in
`as_dict` rather than in the binding so the bound row stays the model's own
serialization — the property the equality fixture above rests on. The visible
consequence is that a project saved and reloaded gets `valid_for` back sorted, so
the round-trip fixture asserts the set survives rather than the tuple order.

Nothing else is normalized, and one sentence here has since been overtaken by its own
fix. A datum declared `"unit": null` *used to* reach this code as the string `"None"`
and be bound as `"None"`; that was D33, and the loader now refuses a unit that is
present and not a string, so such a project no longer loads at all -- the entry left
this file when its fixture landed and the account is in `CHANGELOG.md`. What the
paragraph was arguing survives unchanged: whether identity follows the object the
system accepted is a different question from whether the loader built the right
object, and this binding still normalizes nothing but `valid_for`. The unit regression
uses `mm → cm`, so it depended on neither then and does not now.

`datum_ids` is now sorted in the contract row — a set of references to declared
identities is not a precedence — but never deduplicated, because a repeated id is
a declaration `Project.validate` owns and collapsing it here would hide it.
`project.json` order is untouched.

**Measured, not argued.** Before: the same project with one datum corrected 12.4
→ 12.9, id kept, produced the identical requirement hash
`4149de157b6702cecd1f59f0cdcfb3ac495d842bbf0a47bdcde5740af9e7b712` twice. After,
driven end to end by `benchmarks/heavy/test_datums_heavy.py`: the acceptance
contract moves to revision 2, the history's `changed` list holds exactly one entry
and it is the `requirement_sha256` move, four receipts bound to revision 1 are
invalidated and removed — `pipeline_artifact_receipt.json`,
`commission_report.json`, `pipeline_verification_report.json`,
`final_status.json` — and the stored review answer is
refused outright: *"review envelope mismatch: response bound to … but current
request is …"*. That is the fixture this entry asked for, and it fails against the
pre-fix implementation.

The cap is untouched and still asserted. A datum is reachable only through an edit
scope, so every job that can rest on one remains `EXPERIMENTAL_UNAVAILABLE`; this
fix makes the binding correct and lifts nothing. ADR 0003 decision 6 — precedence
between a datum and other evidence — is still neither implemented nor enforced,
and both it and the sampling reason behind the cap remain open.

The surviving mutation is the part worth reading. Removing `sorted()` from the
canonical block passed all fourteen fixtures, because the referenced ids are
collected into a *set*: the set had already discarded declaration order, so two
projects differing only in that order iterate identically inside one process, and
every reordering fixture compares two projects in one interpreter. What none of
them could see is that a set's iteration order is a function of `PYTHONHASHSEED`,
so unsorted the same project serializes differently in two interpreters — ending
byte-identical reruns and clean-clone reproduction, which are claims about
*different processes*. Two fixtures close it: an L0 order assertion, and a heavy
one that runs the project in two children with seeds 0 and 1 and requires both the
order and the digest to match.

## D32 — the preservation detection limit is derived from one of the two surfaces sampled

**Where.** `pipeline/preservation.py::_sampled`.

**What is wrong.** The audit samples both directions — points planned on the
source and points planned on the candidate — and derives the reported detection
limit from `source.area` alone. The comment beside it argues the choice for the
case where the edit *removed* material, and that argument is sound there. It
does not cover the other direction: where an allowed edit adds substantial
surface, the candidate-side pass spreads the same sample count over a larger
surface and its in-region samples are then discarded, so the sensitivity
actually achieved outside the region is worse than the figure reported beside
it.

**Evidence.** `sampled_area = float(source.area)` feeds
`detectable_defect_mm(sampled_area, samples)`, while the second pair plans its
points on the candidate. The docstring above it justifies only the
smaller-candidate case.

**What it can cause.** A reported detection limit that overstates what the
candidate-direction sampling achieved, under `PRESERVED_WITHIN_TOLERANCE`. Same
cap as D31 applies and is the reason this is filed rather than stopped: the
`EXPERIMENTAL_UNAVAILABLE` ceiling means the figure is not currently load-bearing
for a success claim.

**The fixture that must fail before the fix lands.** A candidate whose area is a
large multiple of its source's, with an unauthorised change outside the region;
the reported limit must not claim a sensitivity the candidate-direction pass did
not have. Reporting per-direction, or the conservative larger area, both satisfy
it; the fixture should not pick one.

## D34 — `design-tool run` overwrites the print engineer's accepted plan

**Where.** `pipeline/cli.py::_print_plan`, reached from `_run_authored`.

**What is wrong.** The function generates a plan template from the printer and
the declared envelope and, whenever that template validates, writes it to
`work_dir / print_plan_checks.json` with no test for whether that file already
exists. For an unbranched project `Project.work_dir` returns the project root,
which is exactly where the print engineer's accepted plan lives: `dt.py audit`
defaults to `<project>/print_plan_checks.json`, `dt.py commission --plan` is
pointed at it, and the role charter's pre-design rule 9 names it as the
engineer's deliverable.

So on any job where an engineer authored a plan, the run silently replaced it —
every Edge ID, every declared interface, and, since the charter hardening
landed, every `deliverables` and `export_fidelity` obligation — with a template
that has none of them. The generated template is not wrong; generating it *over
an author* is. Its own docstring justifies it by four archived runs in which no
plan was bound and each designer set its own ceiling from its own measurement,
and that argument holds exactly where nobody authored a plan.

**Evidence.** Found twice independently. An external post-mortem of the shipped
0.2.0 build recorded three separate print-engineer sessions doing nothing but
restoring the file the run had just overwritten — 19.0 active minutes and 1.72M
logical tokens re-authoring a deleted artifact — and reproduced here in one call
on `776524b`: an accepted plan carrying `revision: 3`, `S-01` and `I-01` comes
back as a generated template with `"edges": []`.

**What it can cause.** A candidate gated against a plan nobody wrote. The
failure is silent in the direction that matters: no rule reports, no receipt
records a substitution, and the plan on disk afterwards is internally valid — it
is simply not the plan the job accepted. It also defeats the charter's
deliverable and export-fidelity obligations at run time on the authored lane,
where a plan can be perfectly authored, perfectly validated, and then replaced
before the candidate is judged.

**The fixture that must fail before the fix lands.** Drive the real run endpoint
on an unbranched project seeded with an authored plan that carries distinctive
support, interface and deliverable content; the file must survive byte-identical
and the downstream contract must see the *authored* values, not the template's.
Presence of the file is the authority boundary — not `authored_by`, which is
optional and would hand back every plan that happens to omit it. Two further
rows bound the fix: with no plan on disk the template is still generated, and an
existing plan that cannot be read or does not validate is refused without being
overwritten, because a run that repairs an unbuildable plan by substituting its
own turns the engineer's error into the pipeline's silent decision.

**Closed, and the shape is now one mechanism rather than three repairs.**
`print_plan_checks.json` is registered to `print-engineer` in
[`pipeline/artifact_names.py`](../skills/3d-modeling/scripts/pipeline/artifact_names.py),
beside D35's `model.py` and D36's `artifact_manifest.json`, and `cli._print_plan`
resolves its write through that registry's `default_path` instead of holding an
existence-and-owner check of its own. **The authority rule is unchanged** —
presence of the file is the boundary and not the optional `authored_by`; an
unreadable or invalid plan is refused rather than repaired; a generated plan
whose commission has moved is refused rather than overwritten. Only what enforces
it moved, and the move is proven rather than asserted: removing this one registry
entry puts the overwrite back and fails the fixture above with no edit to it
([`benchmarks/mutations/d47-role-artifact-owners.json`](../benchmarks/mutations/d47-role-artifact-owners.json)).

## D35 — a certified backend writes its build record over the designer's `model.py`

**Where.** `pipeline/backends/trimesh_manifold.py` and
`pipeline/backends/build123d_backend.py`, in each backend's `build()`.

**What is wrong.** Both write a five-line generated record to
`output_dir / "model.py"` with no existence check, and `output_dir` is the work
directory, which for an unbranched project is the project root. `model.py` there
is the designer's file — the designer charter tells a designer on a certified
`INCONSEQUENTIAL` `DIRECT` job to produce it with `dt.py build --out model.py`
and then "read it, and edit it" — and the builder is chosen from the project and
the route rather than from what is on disk, so a project can hold an authored
`model.py` and still route `CERTIFIED_TEMPLATE`.

Worse than D34 on two counts. `model.py` is the designer's entire deliverable
rather than one contract file among several, and the run **exits reporting
success** with no finding, so the only symptom is that the designer's next read
of their own file returns a summary of a part a template built.

Two docstrings in the same package state the rule this breaks
(`backends/authored.py`, `isolation.py`).

**Evidence.** Reproduced on `237c36a`: a distinctive authored `model.py` in a
certified c_clip job comes back as `# Generated from model_contract.json …
TEMPLATE = 'c_clip'`, exit 3, no finding. Both backends carry their own copy of
the same five lines and both destroy the file.

**What it can cause.** Silent loss of authored work, and — if repaired the
obvious way — a receipt that lies. `BuildArtifacts.source_path` feeds
`artifact_manifest.json`'s `source_sha256`, which travels into both review
envelopes, `final_status.json`'s `artifact_hashes.source`, and the `source`
binding every receipt is checked on. Preserving the designer's file while still
naming it the source would make all of those attest that their module produced a
part a certified template produced.

**The fixture that must fail before the fix lands.** Seed a distinctive authored
`model.py`, execute the certified build path on **each** backend, and require:
the authored file byte-identical afterwards; the generated record still present
and still naming the template, backend and parameters actually executed; and
`source_sha256` equal to the record's digest and not the authored file's.
Control: with no authored `model.py`, the backend still produces its record and
every receipt that depends on it.

**One coupling the repair must carry with it.** `bindings.current()` does not
read `BuildArtifacts`; it re-derives the `source` binding from a filename, and on
the certified lane — no frozen acceptance contract, no declared `project.model` —
the only thing naming that file is the fallback. Rename the record without moving
that fallback and the binding silently resolves to a file nothing writes any
more, leaving `source` null on every certified job with no test going red.

**Closed, and the name it moved off is now held rather than merely vacated.**
The rename is what closed the defect; it did not stop the next writer reaching
for `model.py`, because nothing anywhere could say the name was taken. It is
registered to `cad-designer` in
[`pipeline/artifact_names.py`](../skills/3d-modeling/scripts/pipeline/artifact_names.py)
since #47, so the pipeline claiming or writing it is refused by the same
mechanism that holds D34's plan and D36's manifest. What removing that entry is
observed to expose is the barrier and not the overwrite — the backends write
`bindings.BACKEND_RECORD` and there is no write left in the tree aimed at
`model.py` for a removal to re-enable
([`benchmarks/mutations/d47-role-artifact-owners.json`](../benchmarks/mutations/d47-role-artifact-owners.json)
records that narrowing rather than claiming the defect itself returns).

## D36 — the pipeline's build receipt squats on the designer's artifact manifest

**Where.** `pipeline/runner.py` (both writes) and `pipeline/bindings.py`
(`RECEIPTS`, `REMOVABLE`, and the dependency edge from `commission_report.json`).

**What is wrong.** `artifact_manifest.json` is a team contract:
`team_tools/validators.py::CANONICAL_FILENAMES` names it,
`designer_toolkit/receipts.py` writes it with `contract: artifact-manifest`, and
the charters point readers at it. The pipeline wrote an entirely different object
to the same path — `backend`, `backend_version`, `boolean_engine`, `cache`,
`contract_sha256`, the artifact digests — overlapping the contract shape on only
three keys and disagreeing even on the version key (`schema_version` against
`contract_version`).

**Two mechanisms, and the second is the one a rename of the write alone would
have missed.** The pipeline also treated that path as one of *its own* receipts:
the name was in `REMOVABLE` and carried a `depends_on` edge to
`model_contract.json`, so `bindings.invalidate` deleted the designer's file
outright — recording the sha of a file the pipeline never wrote, and naming a
reason about a dependency the designer never declared.

**Evidence.** Both reproduced on `237c36a`. The write: a manifest declaring
`contract: artifact-manifest`, `owner: 3d-designer`, `revision: 7` comes back
with none of those keys and a wholly different shape, exit 3, no finding. The
deletion, proven in isolation because a building run's later write masks it:
`bindings.invalidate(work_dir)` removes the designer's manifest and records
`"model_contract.json, which it was issued beside, is no longer on disk"`.

The `invalidate` path is narrower than first reported: it is reached from
`_finish`, and the commission-stop path returns before that, so a run that never
builds leaves the manifest intact.

**What it can cause.** Silent loss of a role's contract artifact, and a run that
reports success while having replaced a validated contract with an object
`dt.py validate` rejects.

**The fix, and why it is a rename rather than a guard.** Both writers are
legitimate; only one is entitled to that name. The team contract's is externally
specified, validator-known and charter-facing, so the *pipeline's* moves — to
`bindings.PIPELINE_RECEIPT`. Renaming the contract's would turn a local collision
into a contract migration.

**The fixture that must fail before the fix lands.** Seed a valid team-contract
manifest; require it to survive both a normal run and `invalidate`; require the
pipeline's own receipt to still be written and still be invalidated when stale.
Control: with no team manifest present the pipeline still writes and manages its
own receipt. Reverting only the receipt filename must fail exactly the three
replay fixtures that record it, leaving `modify-ball-scope-refused` stable.

**Not in scope, deliberately.** The internal dict key `written["artifact_manifest"]`
and the verifier packet's `artifact_manifest` key are not filesystem names, and
nothing collides on them; moving those would change a reviewer-facing packet
shape for no correctness gain. `verification_report.json` carries the same
collision in both directions; that slice is **D37 below**, and it is closed.
It was called "differently-shaped" here, and that was wrong in the direction
that matters: the two write mechanisms are identical, and the verifier's
contract has a *reverse* mechanism the manifest does not — the team lane reads
that name back and cross-checks four bindings against whatever is there.

**Closed, and the name it moved off is now held rather than merely vacated.**
`artifact_manifest.json` is registered to `cad-designer` in
[`pipeline/artifact_names.py`](../skills/3d-modeling/scripts/pipeline/artifact_names.py)
since #47, so the pipeline claiming or writing it is refused by the same
mechanism that holds D34's plan and D35's model source — one registry rather than
two renames and a bespoke guard. The read-only compatibility path above is
untouched: `bindings._receipt_payload` still consults this name for a project
completed before the rename, and reading a file is not claiming it. As with D35,
what removing the entry exposes is the barrier and not the overwrite
([`benchmarks/mutations/d47-role-artifact-owners.json`](../benchmarks/mutations/d47-role-artifact-owners.json)).

## D37 — the pipeline's review report squats on the verifier's contract

**Where.** `pipeline/runner.py` (both writes) and `pipeline/bindings.py`
(`RECEIPTS`, `REMOVABLE`, and `_status_depends`'s edge from
`final_status.json`). `pipeline/cli.py` reaches it twice through `REMOVABLE`,
from `_finish` and from `_restart`, and needs no change once the table is right.

**What is wrong.** `verification_report.json` is a team contract:
`team_tools/validators.py::CANONICAL_FILENAMES` names it as the JSON spelling of
the `verification_report` contract, `_EXPECTED_OWNERS` requires `verifier` to
have authored it, `CONTRACT_KIND_BY_KEY` requires `contract:
verification-report`, and `team_tools/status.py` cross-checks
`dimensions_revision`, `print_plan_revision`, `reference_sha256` and
`candidate_stl_sha256` against it. The pipeline wrote a wholly different object
to the same path — `schema_version`, `evidence_packet_sha256`, `reviewer`,
`review_envelope`, `decision`, `unmet_requirements` — overlapping the contract on
`defects` and `fresh_context` and on nothing else.

**Three mechanisms. The first two are D36's, one of them with a second consumer
D36 never had to consider; the third runs the other way.**

1. **The write.** Both `runner` writes — the normal one and the malformed-answer
   receipt — took the contract's name with no test for what was there.
2. **The deletion, and `REMOVABLE` has two consumers rather than one.** The name
   was a `Receipt` and `removable` defaults true, so it was in `REMOVABLE` with
   a `depends_on` edge to `commission_report.json`. `bindings.invalidate`
   removed the verifier's contract when it judged it stale — reached from
   `cli._finish`, the same narrow path as D36, not from a commission stop. And
   `cli._concluded_files` is `[work_dir / name for name in B.REMOVABLE]`, which
   `cli._restart` unlinks one by one — so `design-tool run --restart` deleted
   the verifier's contract **unconditionally**, with no staleness required, and
   recorded its digest in `lifecycle.json` as one of the pipeline's own
   discarded conclusions.
3. **The read-back, which D36 has no counterpart for.** The team lane reads that
   name and cross-checks four bindings against it. The pipeline's object carries
   none of them, so three of the four report the *contract* stale or invalidated
   against bindings it never claimed, and the fourth stops comparing entirely:
   `candidate_stl_sha256` is only checked once `candidate_id` resolves to a
   manifest row, and the pipeline's object has no `candidate_id`.

**Evidence.** All reproduced on `4bdefe7`, against the committed verifier
contract in `team_tools/examples/project_ok/`.

The deletion, in isolation because a building run's later write masks it:
`bindings.invalidate(work)` on a directory holding that contract returns

```
{"verification_report.json": {"sha256": "c577692b1f0b19ba...",
  "broke": ["commission_report.json, which it was issued beside, is no longer on disk"]}}
```

and the file is gone — a contract carrying `contract: verification-report`,
`owner: verifier`, `revision: 1`, deleted for failing a dependency the verifier
never declared.

The read-back, `team_tools.status.compute_status` over the same project with the
pipeline's object at that path instead of the contract:

```
VERIFICATION_REPORT  STALE        bound to dimensions rNone, current r1
VERIFICATION_REPORT  STALE        bound to print_plan rNone, current r1
VERIFICATION_REPORT  INVALIDATED  reference_sha256 bound <missing>, current 90c52df21b20
```

— and no row at all for `candidate_stl_sha256`. `exit_code` goes 0 → 1, so
`dt.py status` blocks a project whose only fault is that a run wrote its own
report. `validate_contract_header` on the same object returns
`BAD_CONTRACT_KIND` plus three `MISSING_FIELD`s.

**What it can cause.** Silent loss of the verifier's contract — the one artifact
in the pipeline whose whole worth is that the pipeline did not write it — and,
in the other direction, a blocked project and a `VERIFICATION_REPORT STALE`
verdict about a document the verifier never authored.

**The fix, and why it is a rename plus a registry.** Both writers are
legitimate; only one is entitled to the name, and it is the externally
specified, validator-known, charter-facing one. So the pipeline's moves, to
`artifact_names.PIPELINE_VERIFICATION_REPORT` =
`pipeline_verification_report.json`. What is new against D34/D35/D36 is that it
moves *through a registry*: `pipeline/artifact_names.py` records one owner per
filename, refuses a second owner, and resolves a write through the owner that
holds the name — so the next writer to reach for a role's artifact is refused
rather than repaired afterwards.

**The fixture that must fail before the fix lands.** Seed the committed verifier
contract in the work directory; require it byte-identical after a full run and
after `invalidate`, and require the pipeline's own report to be written
separately and still invalidated when stale. Each of the four team-lane bindings
must be moved on its own and produce its row, because a clean status is also
what a check that never ran produces. Control: with no verifier contract
present, the run still writes its own report and still invalidates it.
Discriminating: pointing the pipeline's write back at the shared name must fail
the survival row, and a second owner claiming a registered name must be refused.

**Not in scope, deliberately.** There is **no read-only compatibility path for a
project completed before this rename**, and D36 has one. The two cases are not
alike: D36's fallback exists because `commission_report.json` binds the pipeline
receipt by name, so the rename alone would have made a valid stored commission
read as stale. Here the only edge is `final_status.json` → the report, and a
legacy project's `final_status.json` therefore reads stale and is regenerated by
the next run. Nothing authored is destroyed, because after this change the
pipeline never touches `verification_report.json` again in any direction. A
legacy pipeline object left at that name is a file this change cannot reach and
does not create.
