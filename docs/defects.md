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

## D5 — `EditScope.alignment_transform` is declared, validated, and read by nothing

**Where.** [`pipeline/project.py`](../skills/3d-modeling/scripts/pipeline/project.py):274
declares it; :348-354 validates it; it is serialised into `project.json`. No
reader exists.

**What is wrong.** The field states where a source artifact sits in the job's
shared frame — the single value a coordinated multi-artifact edit most depends
on. It reaches neither `preservation._seed_material`, nor the contract row built
by `cli._preservation_feature`, nor `cli._requirement_hash`, nor the review
envelope. `Project.project_hash()` covers it, and that hash appears in no
receipt.

**Evidence.** A finished MODIFY job was given a 5 mm x-translation on its edit
scope, saved, and rerun. Every evidence digest was unchanged, the stored review
response was accepted, and the run wrote a final status. Changing where the
source sits changed nothing anyone downstream could see.

**What it can cause.** A reviewer's answer stays bound to a job whose geometry
has moved underneath it. This is `ROADMAP.md` Release 1's proof "changed
transform rejects the old response", and it is the one proof of the nine that
has neither mechanism nor test.

**Fixture that must fail first.** Run a MODIFY job to its review pause, store the
answer, change `alignment_transform`, rerun, assert `ReviewError` and that no
`final_status.json` is written. A fixture asserting only that `project_hash()`
moves passes today.

## D6 — four declared edit-intent fields bind to nothing

**Where.** `EditScope.preserve`, `.may_remove`, `.add`, `.expected_body_delta`,
and `.interface_ids`, consumed nowhere outside
[`pipeline/project.py`](../skills/3d-modeling/scripts/pipeline/project.py).

**What is wrong.** `cli._preservation_feature` carries only `region_box`, the
region name and `preservation_tolerance_mm` into the acceptance contract, and
only the first and last into the sampling seed. The remaining fields are what the
job *promised about the edit* — what must survive, what may go, what is being
added, how many bodies should result — and changing any of them moves no hash.

**Evidence.** Editing each of the four on a finished job left the contract hash
and every evidence digest unmoved, and the stale `PASS` was accepted on rerun.
`region_box`, the region name and `preservation_tolerance_mm` were each
demonstrated to reject correctly, so the mechanism is sound and the coverage is
partial.

**What it can cause.** A job can change what it claims to be doing without
invalidating the evidence that it did the previous thing.

**Fixture that must fail first.** One parameterised rerun-rejection test over all
seven intent fields. Three pass today; four fail.

## D7 — the build boundary separates namespaces, not privileges

**Where.** [`pipeline/isolation.py`](../skills/3d-modeling/scripts/pipeline/isolation.py)
and the design it implements, landed in `0a8e464`.

**What is wrong.** The child is a peer process: same user, same filesystem, no
lifetime bound. ADR 0002 asks the boundary to carry a *privilege* claim and it
is built as a *namespace* one. Three consequences, each reproduced.

1. **Same-run, no persistence needed.** `pipeline/backends/authored.py` is first
   imported by the parent *after* `ISO.build` returns
   (`runner.py:369` → `backends/__init__.py:57`), and it is on the path of every
   authored job. The candidate rewrites that file while it builds; the parent
   executes its module-level code seconds later in the interpreter holding the
   frozen contract and `status.decide`. Result on `0a8e464`, first run, clean
   tree: exit 0, `final_status VERIFIED`, `feature-pad-section PASS expected
   432.0 measured 80.002`, contract untouched at revision 1, history
   `changed: []`. That is the pre-change reproduction, verbatim, on the
   post-change code. A stealth variant writes a poisoned
   `__pycache__/*.pyc` stamped with the real file's mtime and size, leaving the
   `.py` byte-identical, so hashing the source would not catch it. Other
   post-build first-imports exist on other job shapes: `analysis.py:219`,
   `commission.py:130/225/247`, `screening.py:201/266`, `witness.py:103-104`.
2. **A detached grandchild outlives the run.** `subprocess.run(timeout=)` kills
   the direct child only. A `DETACHED_PROCESS` grandchild sleeps past `_restore`,
   past commissioning, past the parent's exit, then rewrites `final_status.json`
   and deletes `next_action.json`. Measured: the run reported exit 1 FAILED, and
   25 s later `design-tool status` reported VERIFIED with nothing outstanding.
3. **Cross-run.** The candidate rewrites the pipeline source or drops a `.pth` /
   `sitecustomize` into the writable venv, and owns run N+1 before any candidate
   code exists in that run.

**What it can cause.** Every claim ADR 0002 gates. The gate is not met.

**What the boundary does hold**, verified by attack: nothing about acceptance
crosses in through `build_input.json`; all seven Windows artifact-name variants
are refused by exact byte compare; `pipeline.authored` and `pipeline.build_child`
are absent from the parent's import graph; and DIRECT creates zero processes,
proven with `sys.addaudithook` rather than by monkeypatching.

**Fixture that must fail first.** A candidate that rewrites
`pipeline/backends/authored.py` at import time, asserted to leave the parent's
final status unchanged. And a second asserting no process survives the run.

## D8 — ten plausible weakenings leave all sixteen isolation tests green

**Where.** [`pipeline/test_isolation.py`](../skills/3d-modeling/scripts/pipeline/test_isolation.py).

**What is wrong.** Mutation testing against a clean copy killed 5 of 15
mutations. The survivors include: matching an artifact by basename instead of
exact name; launching the child with `shell=True`; removing `model.py` from
`_guarded`, so a candidate can rewrite its own source mid-build while both
`module_sha256` and `artifact.source_sha256` are taken post-build; taking
`module_sha256` from the child's own manifest, which the `BuiltCandidate`
docstring explicitly forbids; and deleting the PARAMS-versus-proposal divergence
check, which no test anywhere references.

`test_the_boundary_never_builds_a_shell_string` inspects the argv that
`child_command()` returns and never the call site, so **it cannot fail for the
thing it is named after**.

`_accept_artifact`, `_child_env`, `BUILD_TIMEOUT_S`, `_restore`, `_guarded`,
`_json_object`, `BuiltCandidate` and `boundary_seconds` have zero test
references each. `pipeline/build_child.py`, the only module that executes
candidate code, has no test at all.

**Fixture that must fail first.** One mutation-survivor test per row above.
