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

## D13 — `preservation.audit` cannot read a STEP at all

**Where.** `pipeline/preservation.py`, the mesh load path.

**What is wrong.** Loading a STEP raises `ModuleNotFoundError: cascadio`. The
audit therefore cannot measure preservation against a STEP source under any
circumstances.

**Evidence.** Found by the first real run of the `vent-ball-combine` fixture
through `design-tool`. That fixture's primary source is `vent_mount.step`, and it
is the repository's only `PHYSICALLY_PROVEN` artifact.

**What it can cause.** Every MODIFY or COMBINE job whose base is a STEP is
unmeasurable, which is most CAD a user would supply. It also means `ROADMAP.md`
Release 1's authentic exercise cannot complete as written: the job named to prove
the gate has a source the instrument cannot read.

**Fixture that must fail first.** A MODIFY job declaring a STEP source, asserted
to produce a preservation verdict rather than an import error.

## D14 — `diagnose` calls a STEP clean that cannot be tessellated

**Where.** `pipeline/diagnose.py`, STEP path.

**What is wrong.** `vent_mount.step` is reported usable. Four cone faces make it
untessellatable downstream, so the file passes diagnosis and then fails the first
operation that needs geometry.

**What it can cause.** Diagnosis exists to say whether a source can be worked
with. A clean verdict on a file nothing can tessellate is the exact failure
diagnosis is for, and it moves the error to a stage with less context to explain
it.

**Fixture that must fail first.** That STEP, asserted to report the untessellatable
faces.

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

## D16 — the preservation audit peaked at 16.7 GB resident

**Where.** `pipeline/preservation.audit` on real geometry.

**What is wrong.** Measured during the vent-ball run. There is no resource bound
on the audit; `ROADMAP.md` section 2 already records that no resource governor
exists, and this is the first measurement of what that costs.

**What it can cause.** A large source can exhaust the machine rather than fail
controllably. `ARCHITECTURE.md` section 12 requires geometry execution to operate
under explicit limits and fail diagnosably.

**Fixture that must fail first.** An audit against a declared memory ceiling,
asserted to refuse rather than allocate past it.

## D17 — a successful `route` leaves a stale `next_action.json`

**Where.** `pipeline/cli.py`, the `route` verb.

**What is wrong.** `route` succeeds without clearing or rewriting the pending
next action, so the file continues to instruct toward a state the project has
left.

**What it can cause.** The file exists to tell an agent what to do next. A stale
one sends it to the wrong step, and nothing detects the staleness — `next_action`
carries no run id, no sequence and no self-digest.

**Fixture that must fail first.** `init` then `route`, asserting the next action
names the state after routing.

## D18 — one unreadable source zeroes the inherited-overhang allowance for all of them

**Where.** `cli._inherited_overhang`.

**What is wrong.** It returns `None` if *any* source cannot be measured. On a
two-source job where one source is a STEP (D13), the allowance the candidate is
entitled to inherit from the *readable* source is zeroed too.

**Evidence.** The vent-ball run: the candidate failed
`feature-plan-support-00` with 4582.055 mm² of overhang **it inherited from the
source it was told to preserve**. That is a contract failure caused entirely by a
missing importer, and it reads like a design defect.

**What it can cause.** D13 produces a second, misattributed failure. A user
debugging the overhang would be debugging geometry that was never wrong.

**Fixture that must fail first.** A two-source job with one unreadable source,
asserted to inherit the readable source's allowance and to report the other as
unmeasured.

## D19 — the audit is not reliably completable on real geometry

**Where.** `pipeline/preservation.audit`. Supersedes D16's severity.

**What is wrong.** Measured on the vent-ball fixture: 22.4 GB peak working set,
23.49 GB across processes, 39.74 GB page file, free RAM at 0–1.5 GB throughout.
**One of eleven identical invocations died** with
`MemoryError: Unable to allocate 1.57 GiB for an array with shape (210081703,)`.

It failed controllably — `BLOCKED`, receipt written — and the retry succeeded.
That is the problem: the same unchanged job produced two different outcomes.
Determinism of the *answer* is achieved; determinism of *completing* is not.

**What it can cause.** A liveness defect, not a rigor one. Release 1 exists so
that an unchanged job can be rerun and resumed; a job that completes on ten
attempts out of eleven cannot be relied on to do that, and the failure rate
scales with source size.

**Fixture that must fail first.** An audit under a declared memory ceiling,
asserted to refuse before allocating past it rather than to race the allocator.

## D20 — the user-facing verdict does not say the source was unreadable

**Where.** `final_status.json` and the CLI summary line.

**What is wrong.** The check row keeps the distinction cleanly —
`ran: false`, `status: UNAVAILABLE`, `measured: null`, `result: ESCALATE`,
`error_code: PRESERVATION_UNMEASURABLE`, with the `ModuleNotFoundError` as its
reason, beside a sibling row reading `ran: true / MEASURED / FAIL / CHANGED`.
Nothing collapses them **in that JSON**.

The distinction stops there. `final_status.json` says only "rejected by
independent verification", and the CLI summary says the same. A user who does not
open `commission_report.json` learns that a reviewer rejected their part, not
that the tool could not read their primary source.

**What it can cause.** "Your part changed" and "the instrument cannot read your
primary source" demand different actions from the user, and only one of them is
their fault.

**Fixture that must fail first.** A run with an unmeasurable source, asserted to
name that in the final status and in the summary line.

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
