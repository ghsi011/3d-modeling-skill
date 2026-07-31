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
