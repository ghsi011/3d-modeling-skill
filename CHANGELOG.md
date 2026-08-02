# Changelog

All notable changes to the **3d-modeling** skill are documented here.
This project loosely follows [Keep a Changelog](https://keepachangelog.com/) and
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added — a recorded job, replayed, with nothing asked of a model

`ROADMAP.md` section 5.1 defines three benchmark tiers and this repository
shipped three releases with two of them. L0 is the unit suite and
`tools/test_diagnosis_l0.py`. L2 is blind live evaluation, deliberately manual.
**L1 — a recorded engineering output replayed through the current system with no
live AI call — did not exist**, and section 4.3 asks for at least one of every
release. `test_diagnosis_l0.py` replays five artifacts through `diagnose`, which
is one component; `pipeline/test_frozen.py` calls `runner.run` on parameters a
test made up, which is the runner without the command surface, without a project,
without a proposal, without the confined build and without a review round trip.
Nothing replayed a *job*.

`tools/replay.py` does. It materialises a recorded case into a fresh directory,
runs `design-tool route` and then `design-tool run` until the job settles, and
compares what came out against `expected.json`. `benchmarks/replays/` holds two
cases, which is the number two real lanes need and not one more:

* **`custom-knob-sleeve`** — an authored `CUSTOM` job against the vendored
  `berlingo-knob` request. Proposal, acceptance freeze at revision 1, the
  confined build, ten commissioning checks, the broad screen and the status
  decision. No review at all, so its dispatch count is zero by construction. Two
  seconds.
* **`modify-ball-flange-flat`** — a `MODIFY` job over `ball_male_17mm.stl`, the
  real 17 mm ball the `vent-ball-combine-r1` exercise consumed, resolved through
  `tools/fixtures.py` so its size and SHA-256 are checked before the job sees it.
  A declared edit scope, a preservation row inside the frozen contract, and a
  two-review round trip that pauses for safety, pauses for verification and
  finishes — preservation, the acceptance revision and the round trip being the
  three places a regression has actually landed. Thirteen seconds.

**What a replay asserts, and why it is not more.** Almost everything here is
hash-bound on purpose, so a replay that diffed receipts byte for byte would go
red on a new field, a protocol bump and a dependency upgrade — every one of them
legitimate — and would be deleted inside a month. The assertions are layered.
Binding: the exit codes in sequence; the final status and the verdicts under it;
the per-check verdicts, exactly, because coverage is a fraction and stays 1.0
when the declared set shrinks with the covered one; the measured values inside
the band the *contract itself* declares for them, falling back to the pipeline's
own 0.5% where a row declares zero; the receipt set by name; the reviews
answered; and four hashes that are equalities between two values from the same
run rather than literals in a file. Advisory, reported and never failing:
`reasons` and `allowed_claim`, which are prose. Not asserted at all: receipt
bytes, any pinned digest, findings text, timings, witness images.

**The recorded answer is re-bound, not replayed.** A stored review response
echoes an envelope binding the packet, the contract, the plan, the evidence
digests and the protocol version — which is why the real vent-ball run carries
two 164-byte reports whose whole content is `review envelope mismatch`. So a case
records the reviewer's *judgement* with no envelope, and the harness stamps the
one the current run just issued. That is what a human reviewer does; only the
judgement is recorded. It would be a hole if nothing checked the binding still
bit, so the suite asserts each report's envelope is the packet's, and an
adversarial case hands the run an answer bound to evidence that moved and
requires it to refuse, write no final status, and make the comparison go red.

**Zero live dispatches, asserted.** `materialise` creates no `reviews/`, so every
response on disk is one the harness wrote and it can only write a recorded one; a
review with no recording raises rather than leaving the job paused; and
`AGENT_COMMISSION` is fatal, because that instruction *is* the live dispatch on
the `CUSTOM` lane.

**The two suites are separated structurally.** `testpaths` names
`skills/3d-modeling/scripts` and `tools`; `benchmarks/replays` is in neither, so
a bare `uv run pytest` cannot collect a job replay. CI runs L0 on every push and
L1 on pull requests as its own job. The harness's own guards are L0 —
`tools/test_replay.py`, 34 tests in 2 s, with every guard shown red under a
mutation that disables it — because a check nobody checks
reports all clear just as convincingly when it is broken.

**Where the expectations came from.** Not from the two completed real runs on
disk. `oneplus8t-magnet-drawer` has no `project.json`, no execution plan and no
review packets: it was built by hand-rolled scripts and there is nothing to
replay it *through*. `vent-ball-combine-r1-exercise-2` is a full recording and is
still not the source, for four reasons: it costs ~876 s and 24 GB of RAM against
a two-minute budget for the whole tier and died in the allocator once in eleven
runs; it ran at `2721ffe`, before two later slices; its root `final_status.json`
was deleted by its own revision-2 bump; and two of the three defects behind its
terminal `FAILED` are *instrument* failures this repository intends to fix, so
pinning them would build a fixture that goes red the day the bug is repaired.
What is taken from it is what survives a change of scale and is real: the
recorded request, the `MODIFY`-with-an-edit-scope shape, and the source artifact
itself. Both `expected.json` files are recorded at the current commit
deliberately; re-record with `--record` when a change legitimately moves one, and
put the diff in the review.

### Changed — a project problem is data, not a sentence

Release 3 slice C, and the half of the derived-status work that was left owed.
Once `design-tool status` answers per alternative, "why is this one not
`COMMISSIONED`" is a question asked of N formulations at once — and
`Project.validate()` answered it with a `list[str]` of English. No code to branch
on, no field path to jump to, no severity, and nothing an instruction written
today could be compared against one written last week. With one formulation that
list is readable. With several it is a search.

**A move, not a design.** The type already existed and was complete:
`team_tools.common.Issue` — severity, code, field path, message, and a stable
`CODE@where` id — has carried every contract-validation finding since it was
written. It now lives in `pipeline/findings.py`, and `team_tools.common`
re-exports it from there, so both packages report through one type rather than
two that drift. The dependency points from `team_tools` to `pipeline` and never
back: `team_tools` is the older layer and `pipeline` is the one being built, and
a shared module owned the other way round would make everything built next depend
on what it replaces. `pipeline/test_findings.py` holds that direction with an AST
check over every production module in the package, because the import that
reverses it is a one-line change nobody would notice in review.

One thing changed on the way. `Issue.message` was always `f"{where}: {detail}"`;
it can now be supplied instead, and `pipeline` supplies it. Those sentences were
written before the type existed, they already name their own field
(`"source_mode is NEW but source artifacts are declared; ..."`), and the suite
asserts on several of them — so prefixing a path onto them would have changed
what a user reads to gain nothing a caller could not read off `where` directly.
The default is untouched, which is what keeps every existing `team_tools` receipt
byte-identical.

**The codes are grouped by what clears them.** `SCHEMA_` means one field is wrong
in itself — correct the field. `REF_` means a well-formed id that no row
declares, or two rows for one id — add, remove or rename a row. `ARTIFACT_` means
the declaration is fine and a file disagrees: it escapes the project, is not
there, or was read and refused — fix the file. `INTENT_` means every field and
every reference is fine and the declarations still describe no one job — make a
decision. The shape follows `analysis.py`'s existing `BOOLEAN_ENGINE_*` /
`SECTION_INSTRUMENT_*` codes, and the vocabulary is deliberately small: `id` is
`CODE@where`, so `SCHEMA_ENUM@source_mode` already names exactly one rule and a
code per check would be a lookup table rather than something to match on.

**`where` is a position, not a name.** `edit_scopes[1].region_box`, not
`edit_scope 'drawer'`. With two scopes over two artifacts, the sentence quotes an
id and a caller still has to search the list for it; the path is the field. The
box checks name the axis too (`region_box.x`), because a box can be empty on two
axes at once and an id two findings share is an id nothing can be keyed on.

**Nothing that read the old answer reads a different one.** The terminal prints
the same sentences in the same order — the skeleton project's six lines are
pinned literally in a fixture. `next_action.unresolved` is still a list of
sentences, because four unrelated stages fill it (a validator, a status
derivation, a stage message, the project's open questions) and a field whose
element type depends on which of them wrote it is a field no reader can parse.
The structure arrives beside it under `findings`, one entry per line and in the
same order, in the refusal instruction and in `design-tool status --json` alike.
The four stage refusals that reported bare sentences through the same
function — a missing envelope, a plan that does not validate, a refused proposal
or build, a model contradicting its proposal — are findings now too, so
`_report_problems` has one element type whichever stage called it.

Zero-cost is unaffected: `next_action.json` is hashed into nothing, and the five
pinned contract goldens and `test_frozen.py` are untouched.

### Changed — the status is computed from the evidence, and invalidation is scoped to it

Release 3 slice B. Three separate ways for a receipt to say something that is no
longer so, and one mechanism that answers all three.

**The status was stored.** `status.decide` ran once, mid-run, its answer went
into `final_status.json`, and every reader afterwards repeated it verbatim —
`design-tool status` recomputed the project's `problems` and took the verdict as
given. A `VERIFIED` receipt beside a candidate somebody had rebuilt, an evidence
file somebody had corrected, or a plan that had since moved all read as current,
and nothing on disk could tell.

`final_status` in the `status` report is now derived. `pipeline/bindings.py`
reads each receipt's own record of what it was issued against — the artifact
manifest's digests, the commissioning report's contract hash, a review report's
whole envelope down to the witness images and evidence files it was shown, the
final status's artifact hashes and plan digest — and compares it against what is
on disk. A stored `COMMISSIONED` or `VERIFIED` whose receipts no longer bind
derives `STALE`; a directory where no run concluded derives `NOT_RUN`. The stored
verdict is still reported under its own name, because it remains the record of
what that run concluded; what changed is that a reader no longer trusts it
without checking.

It is deliberately **not a second gate**. Nothing is re-run and no threshold is
re-applied, so a job whose bindings all hold derives exactly what it stored, and
the only move available is downward. A `FAILED` or `NEEDS_MORE_EVIDENCE` whose
bindings broke keeps its own name and carries the breakage alongside — the same
choice the lane cap makes, and for the same reason: a finding replaced by "this
is out of date" is a defect nobody is looking at any more.

**Invalidation was all-or-nothing.** A changed acceptance body deleted a fixed
six-name tuple, whatever had actually moved. That rule can express "something
changed, therefore everything is stale" and nothing else — not "this changed,
therefore that is", and not "this is still true, leave it alone". The tuple is
gone and the rule is derived from the bindings each receipt carries. An
acceptance revision still reaches the same six files, because every receipt binds
the model contract's hash and the model contract binds the acceptance contract's,
so one broken edge takes the chain. What is new is everything else: a rebuilt
candidate takes the artifact manifest and the commissioning report measured
beside it; a corrected caliper sheet takes only the reviews that were shown it
and the status that rested on them, and the measurements of a candidate that did
not move stay on disk. `model_contract.json` is reported stale and never removed —
it is the contract the others are checked against, and deleting it would turn
"issued against a contract that has moved" into "there is no contract here".

`design-tool run` performs that sweep immediately before executing, which is what
keeps ADR 0002 §4's promise on a run that does not finish: a job that stops for a
review no longer leaves the previous run's success sitting beside it.

**`project.json` no longer mirrors either.** The `status` and `bindings` blocks
copied one run's stage, verdict, claim and artifact digests into the one file
that has to stay shared, so the project said the job was whatever had finished
last — and slice A had already had to stop a branch stamping them, which left a
mirror that was true of the root and silently wrong while a branch was active.
They are dropped rather than made per-alternative: two authorities over one fact
is the shape this codebase removes, and it is the same argument that deleted
`project_hash()`. A project file written under the old mirror still loads, since
what is dropped is a copy of something that is on disk in its own right; the one
value in there that was a declaration rather than an outcome —
`external_geometry`, recorded by the `job.json` adapter and read by `route.decide`
and `to_job_request_fields` — is carried across into its own field.

### Fixed — a successful `route` no longer instructs toward a state the project has left (D17)

`next_action.json` carried no identity: no run id, no sequence, no self-digest.
Staleness was handled entirely by overwriting or unlinking the file, so any path
that changed the project without reaching one of those two calls left an
instruction pointing at work already done, and nothing could detect it. A
successful `route` was exactly such a path — it wrote "this project cannot be
routed" while the project was incomplete, and left the sentence there once the
project was completed and routed.

Every instruction now carries `state` (the acceptance contract, the model
contract, the execution plan, the artifact digests, and which formulation it is)
and `state_sha256` over it — the same map the derived status checks receipts
against, because an instruction and a receipt go stale for the same reasons.
`status` reports `waiting_for_superseded` and stops counting a superseded
instruction as something to do. `route` recomputes the instruction against the
state after routing: nothing, when the receipts still support a current success,
and `RUN` otherwise.

### Fixed — a STEP can be read, by the kernel that was already here (D13, D14)

`preservation.audit` handed every source path to `trimesh.load`, which dispatches
STEP to `cascadio`. `cascadio` is not in this runtime and is not in `uv.lock`, so
**every** audit against a STEP source returned `UNMEASURABLE:
ModuleNotFoundError: cascadio` — most CAD anybody supplies, the base of every
`MODIFY` and `COMBINE` on one, and the primary source of the repository's only
`PHYSICALLY_PROVEN` fixture.

**`cascadio` was not added.** It was measured first, which is what settled it.
`build123d` is already a core dependency and `diagnose` already reads STEP
through it, so the choice was between one STEP reader and two — and the second
one disagrees with the first about the file. On `vent_mount.step`, `cascadio`
returns the part in **metres** where `build123d` returns millimetres, in 324
disconnected bodies with 8,284 boundary edges against 10 and 1,854, and it still
produces no triangles for the cone faces. A silent unit substitution is the first
thing `ARCHITECTURE.md` §12 forbids of a backend swap, so 16 MiB of second OCC
build would have bought a units defect and no capability.

`mesh_io` gained the reading instead: `tessellate_brep` probes every face through
the public tessellation API and **returns** what it could not read rather than
throwing it away, and `read_step` is the one place a supplied B-rep becomes
triangles. `validate_brep_tessellation` — which already existed and already named
the faces OCC refuses — is now that function with a raise on the end, so there is
one probe and not two. The deflection it reads at is a declared constant
(`BREP_READ_LINEAR_DEFLECTION`, 0.01 mm) and travels onto the preservation
receipt under `tessellation`, because two deflections are two meshes of one solid
and therefore two measurements; a mesh file's read is a parse and records nothing,
so no evidence digest moves for a job that never touched a B-rep.

`diagnose` runs the same probe (D14). `vent_mount.step` was `USABLE_EXACT` with
no findings and then killed the first operation that needed geometry with
`'NoneType' object has no attribute 'NbNodes'`. The old test was face *area*, and
area is not tessellability: all 329 faces have finite positive area — one of them
is 1.75e-14 mm², which is small and is not zero — so `invalid_faces` was 0 and
would have stayed 0 however the check was tightened. It now reports
`untessellatable_faces`, names each one with its surface type and centre, and
classifies `REPAIR_REQUIRED`.

The file itself is still untessellatable, and that is now [D22](docs/defects.md)
rather than a clean verdict: **six** cone faces, not the four D14 recorded, plus
a seventh face that fails when the shape has not been meshed as a whole first.
The audit refuses on it and names them, rather than measuring a surface with six
holes in it and reporting a distance to geometry that is missing rather than
moved.

A source that parses to zero triangles is refused the same way. `trimesh.load`
turns a file that is not an STL at all into an empty mesh rather than raising, and
an empty mesh reached the distance query as an r-tree over nothing —
`ValueError: Bounds must be (n, dimension * 2)`, raised out of the audit, out of
the check and out of the run as a stage failure with no row and no receipt.

### Fixed — the preservation audit runs under a declared ceiling (D16, D19)

Measured on the vent-ball pair, unbatched, on this machine: **23.24 GiB peak
working set, 91.18 GiB peak page file, and it does not finish** — 334 s in,
`MemoryError: Unable to allocate 2.47 GiB for an array with shape
(331606963,)`. The reported field failure was the same shape at
`(210081703,)`, and it killed one invocation in eleven while the other ten
completed. Determinism of the *answer* was achieved in the previous release;
determinism of *completing* was not, and Release 1 exists so that an unchanged
job can be rerun and resumed.

The 210 million was never mysterious. `trimesh.proximity.nearby_faces` uses the
distance to the nearest *vertex* as its query radius, so a sample 60 mm from a
20 mm part asks the r-tree for everything inside a 60 mm box: all 7,056 faces came
back for all 20,000 points in one direction, and a mean of 16,583 of 19,522 in the
other. At a measured 350 bytes of working set per (point, face) pair — flat to
four significant figures across a 70x range of query sizes and two meshes — that
is the whole of the 23 GiB.

`audit` now takes `memory_ceiling_bytes`, declared at 2 GiB, and derives the
query batch from it: `ceiling / (faces x WORKING_BYTES_PER_CANDIDATE)`, with the
per-candidate cost declared above the measurement at 384 bytes because a ceiling
computed from an optimistic cost is not a ceiling. Both directions' batches are
settled before either runs, so a job too big for its ceiling is refused with the
arithmetic in the reason and nothing allocated — not discovered halfway through
with one direction's numbers already written.

**The ceiling bounds execution and does not touch the measurement.** Splitting
the query is exact: `closest_point` computes every point independently — the
candidate lookup, the per-row triangle distance and the two-best tie-break are all
per query point — so a batched run returns the same float64 values as an
unbatched one. `signed_distance` is still the call being made, even though the
sign is discarded one line later, so that "byte-identical to today" is a fact
rather than an argument about when `np.sign` returns zero. The ceiling is
deliberately **not** in the sample plan or the evidence: binding a review answer
to a machine's memory budget would expire that answer when the job was rerun
somewhere smaller, having measured the same thing.

Same fixture, same region, under the 2 GiB ceiling: **2.16 GiB peak working set,
3.61 GiB page file, 200 s, and it completes.** 10.8x less resident, 25x less page
file, 1.7x faster than the run that died.

### Fixed — an unreadable source no longer zeroes the allowance for the readable one (D18)

`cli._inherited_overhang` returned `None` — the generated zero — if *any*
declared source could not be measured. On the vent-ball run one source was the
STEP above, so the allowance the candidate was entitled to inherit from the
readable source went to zero with it, and the job failed
`feature-plan-support-00` on 4,582.055 mm² of overhang **it had inherited from the
part it was told to preserve**. A contract failure caused entirely by a missing
importer, reading like a design defect.

The old argument was that a partial sum is a ceiling nobody measured. A zero is
not more measured than a partial sum — it is less measured, and it is wrong in
the direction that fails a correct part. The sum over the sources that read is a
strict lower bound on what the candidate legitimately inherits, so it cannot
excuse an overhang the edit added; what it cannot cover is the unread source's own
share, and the provenance note now says which sources were measured, which were
not, why not, and that the ceiling is therefore partial. `None` still means the
generated zero and now means only what it says: not one declared source could be
measured.

### Fixed — the verdict a user reads names the check that never ran (D20)

`commission_report.json` kept the distinction perfectly — `ran: false`,
`status: UNAVAILABLE`, `measured: null`, `result: ESCALATE`,
`error_code: PRESERVATION_UNMEASURABLE`, the exception as its reason, beside a
sibling row reading `ran: true / MEASURED` — and carried it nowhere.
`final_status.json` said "rejected by independent verification" and the CLI
summary line said the same, so a user who did not open the commission report
learned that a reviewer had refused their part rather than that the tool had never
read their primary source. Those call for different actions and only one of them
is the user's fault.

`status.decide` now collects every `UNAVAILABLE` check into `unavailable_checks`
and appends them to `allowed_claim`, after the lane cap, because a rejection, a
failure and a capped success can each sit beside an instrument that never
measured. `design-tool status` and the end-of-run summary both print
`allowed_claim`, so the sentence cannot drift from the receipt. A run with nothing
unavailable is unchanged, and the frozen `DIRECT` claims are untouched.

### Added — a second formulation of the same job, isolated on disk and in the receipts

`design-tool branch <project> --from <alt|.> --id <name> --reason "<text>"` is one
deterministic verb with no dispatch. It appends an `{alternative_id, parents,
reason, disposition}` row to `project.json`, points `active_alternative` at it,
and **copies nothing**: the brief, the requirements, the source artifacts and the
evidence stay shared and are read by reference. `--activate <alt|.>` switches,
`.` being the shared root the siblings were branched from. `parents` is a list
from this first release, because a merge is a revision with several contributing
parents and widening a scalar later is not additive; nothing here writes more
than one entry.

When an alternative is active, every file that means something about *one*
formulation is written under `alternatives/<id>/`. With one shared directory the
collisions ran worst-first, and none of them announced itself:

* two siblings froze into one `acceptance_contract.json`. The second's `freeze`
  read the first's contract as `previous`, cut a revision, and `_invalidate`
  deleted the first's `final_status.json`, `commission_report.json`,
  `artifact_manifest.json`, `manufacturing_report.json` and both review reports.
  Re-running the first did it back. Two alternatives destroyed each other on
  every alternating run, and `acceptance_history.json` recorded the fork as one
  linear chain of corrections;
* `_run_authored` skips the designer commission when `design_proposal.json` and
  `model.py` both exist, so a second alternative was **never commissioned**: it
  rebuilt the first's geometry and filed the receipts under its own name;
* `candidate.stl` and `candidate.step` are fixed literals, so the second build
  overwrote the first;
* a review is answered by the *presence* of `reviews/<kind>_response.json`, so a
  sibling picked up the answer written next door and then failed closed on the
  envelope while reporting the wrong diagnosis.

**Path isolation is necessary and provably not sufficient**, so `alternative_id`
joins exactly two hashed payloads: `execution_plan.json` and the review envelope
(`REVIEW_PROTOCOL_VERSION` 3 → 4, so a stored protocol-3 answer is refused by
name rather than by an unexplained digest mismatch). `ExecutionPlan.as_payload`
carries no parameters and deliberately omits `candidates`, so two authored
formulations of one job compile to the same plan hash; the envelope's `revision`
is `updated_utc`, a timestamp rather than a graph node; and at the instant a
branch is created its sibling is a copy, so `contract_sha256`, `artifact_hashes`
and `witness_hashes` are all equal. A safety `PASS` written for one sibling was
therefore `is_bound` for the other — a false pass of exactly the class the
authority gate forbids, reachable with nobody doing anything wrong. It does
**not** join `contract_sha256`: two formulations requiring identical geometry
legitimately share an acceptance contract.

Invalidation is one rule. A change to the shared half of `project.json`
invalidates every alternative; a change inside an alternative invalidates that
one only. Both follow from freezing per alternative root, and
`acceptance_history.json` now records the alternative on each entry and inside
`supersedes`, so a correction and a fork are distinguishable rather than
identical.

**Zero cost when unused, exactly rather than approximately.** A project that has
never branched serializes, compiles and hashes to the bytes it did before: every
new field is absent when there is nothing to say and never `null` — the
`execution_plan_sha256: None` precedent in `review.py` is deliberately not
followed — no subdirectory appears, and the five pinned certified contract hashes
and every `test_frozen` golden are unchanged and were not re-pinned.

`pipeline/test_alternatives.py` carries the fixtures; each was verified to fail
under a targeted mutation of the protection it covers, including the two that
matter most — remove `alternative_id` from the envelope and one sibling's PASS
binds the other; emit it as `null` instead of omitting it and the zero-cost
proof fails.

### Removed — `candidate_strategy`, and `Project.project_hash()`

`candidate_strategy: "PARALLEL"` was validated, stored in `project.json`, carried
into `intent_manifest.json` and hashed, and its entire behavioural effect was
appending one sentence to the route escalation list. Nothing generated a second
candidate, isolated one, or compared two — a schema field that let a document
claim a capability with nothing behind it. A project or `job.json` carrying it is
now refused **by name** and pointed at `design-tool branch`; `"SINGLE"` is read
and dropped, because it claimed nothing and sits in every `project.json` this
build has written.

`Project.project_hash()` hashed the whole payload including the mutable `status`
and `bindings` blocks, so it moved on every finished run, and it was read by
nothing. Its one appearance — `next_action.json`'s `bound.project_sha256` — is
replaced by `requirement_sha256`, the digest of the half of the job nobody on the
design side owns, which is what the frozen acceptance contract already carries and
what shared-half invalidation already keys on. A digest that always differs is one
its readers learn to ignore, and two digests over one declaration is one authority
and one bug.

### Fixed — a shared source artifact is found from a branch

`commission` resolved a declared preservation source beside the candidate, which
stopped being beside the project once the candidate moved under
`alternatives/<id>`. It takes the shared root explicitly now and defaults to the
candidate's own directory for every caller that has none, so a `MODIFY` job on a
branch measures against the artifact where the project declared it rather than
reporting `SOURCE_MISSING` for a file that is already there.

### Fixed — the candidate was writing to the party that decides the run (D10)

`model.py` declares `PROVENANCE`. The child returned it in
`build_manifest.json`, `isolation.py` adopted it verbatim, `acceptance.py` put it
in `contract.source`, and `runner.py` handed that contract to the safety reviewer
and the verification reviewer, whose PASS or REJECT decides acceptance. Free text
the candidate composed reached the grader. No process confinement closes this,
because the data is supposed to cross — and read access to the frozen contract
(D9 row 3) does not create the channel, it aims it: a candidate that knows the
tolerance bands and the design id can write in the gate's own vocabulary.

Three more channels were found beside it, all in `artifact_manifest.json`, which
both packets embed whole: `backend_version`, `tessellation` and `boolean_engine`
were candidate-supplied strings copied straight onto the receipt. And the
manifest is written by a process the candidate's module-level code already runs
in, so *every* field of it is candidate-authored whatever `build_child` intends.

The repair is a type, not a filter — a sanitiser that stripped suspicious words
would be one more removable check, and this branch has had two of those fail:

* the engine strings are a **closed vocabulary the parent owns**. The child
  returns a `kernel` token; `isolation.KERNELS` maps it to the words on the
  receipt, and the version comes from the parent's own `importlib.metadata`. A
  token the table does not hold selects `unrecorded` — it is never passed
  through. Nothing about the receipt's wording changed;
* `PARAMS` and `PROVENANCE` are quarantined in an
  `isolation.CandidateDeclaration`. `BuiltCandidate` — the only object that
  leaves the boundary — otherwise holds paths, digests, numbers and that one
  token. `AcceptanceSource` has no `provenance` field at all now, so
  `as_source()` cannot carry one;
* `PROVENANCE` is written to `candidate_declaration.json` and read by nothing.
  That is the cost, stated plainly: a reviewer that was using the designer's
  account of how the part was made no longer gets it. It was never evidence — it
  is the assertion of the party being judged — and the reviewer keeps the brief,
  the frozen contract, the measurements and the witnesses, all of which are
  written by someone else.

`test_isolation.NoCandidateProseReachesAReviewerTest` is permanent and attacks it
twice: a `PROVENANCE` addressed to the reviewer, and a model that replaces
`schemas.canonical_json` in its own process and rewrites the entire manifest on
its way out. Both assert one marker absent from every receipt, from the real
`reviews/safety_packet.json` the run produced, and from a verification packet
built from the same evidence. Two more assert the shape rather than a run: the
field set of `BuiltCandidate`, and that not one of the fourteen modules on the
path to a reviewer packet imports the boundary or reads `.declared`.

`CHILD_SCHEMA` is 3. `model.name` and `BuiltCandidate.kernel` were read by
nothing and are gone with the strings.

### Fixed — the network probe was measuring NordVPN, not the boundary (D11)

`test_isolation`'s network row asserted refusal by connecting to `1.1.1.1:53`.
That port is filtered on this machine by NordVPN Threat Protection, identically
with no confinement at all, so the row was green everywhere and had never
measured the confinement. Re-measured under the real restricted low-integrity
token: `1.1.1.1:443` connects, `1.1.1.1:80` connects, `93.184.215.14:80`
connects. All three firewall profiles are `DefaultOutboundAction=NotConfigured`.

The probe aims at 443 now and the row is `ALLOWED`, because it is. The
expectation that this boundary denies outbound TCP is kept as a *failing* test,
`test_the_boundary_denies_outbound_tcp`, marked `expectedFailure`: the suite
stays green while the gap is open, and closing it produces an unexpected success,
which unittest reports as a failure. A limitation that goes off is worth more
than a paragraph that does not. `confine.py`'s docstring said the restricted
token refused `socket.connect`; it does not, and it now says so, as does
`docs/defects.md` D9 row 1 — the network is open, not closed-except-DNS.

### Fixed — the confined child could still create processes (D12)

Measured: a candidate under the full boundary launched `cmd.exe`. Every
counter-measure was downstream of the process already existing — the job object
caught it, the survivor sweep counted it, the drain killed it before anything was
read. `PROC_THREAD_ATTRIBUTE_CHILD_PROCESS_POLICY` with
`PROCESS_CREATION_CHILD_PROCESS_RESTRICTED` moves the refusal to `CreateProcess`:
measured `WinError 367`, at zero geometry cost (1.77 s trimesh, 5.86 s build123d
including its cold import).

It has one prerequisite. A virtual environment's `python.exe` is a launcher that
spawns the base interpreter as a child, so under this policy the boundary could
not start its own child. `isolation.base_executable()` launches
`sys._base_executable` directly and `PYTHONPATH` gains the environment's
`site-packages`; both paths are read-only to the restricted token, and outside a
virtual environment the two answers coincide.

Two attacks had to be rewritten to keep measuring what they were written for:
`mklink /J` is `cmd.exe`, so the junction attack and the probe's reparse-point
row now go straight at `FSCTL_SET_REPARSE_POINT` with no subprocess at all —
strictly stronger, since it needs no privilege and no helper program, and it
turns a row that used to be denied because `cmd.exe` said `Access is denied.`
into one denied by the kernel: `ERROR_ACCESS_DENIED` on the control itself,
measured, from inside the one directory the candidate can write. The
`DETACHED_PROCESS` and `CREATE_BREAKAWAY_FROM_JOB` grandchild attacks now fail at
process creation instead of inside the job; both are kept, because the job object
is what makes a failure of this policy survivable and it is the mechanism that
has already been walked through once.

### Fixed — seven declared fields that a reviewer's answer did not depend on (D5, D6)

An edit scope declared twelve things about a modification. Five of them reached
the acceptance contract or the sampling plan; seven did not reach anything at
all. `alignment_transform`, `preserve`, `may_remove`, `add`,
`expected_body_delta`, `preserve_metadata` and `interface_ids` were parsed,
validated, written into `project.json`, covered by `Project.project_hash()` — and
read by no consumer, and `project_hash()` appears on no receipt. Demonstrated: a
finished `MODIFY` job given a 5 mm x-translation on its edit scope, saved and
rerun, produced every evidence digest unchanged, had its stored `PASS` accepted,
and wrote a final status. (`preserve_metadata` was the seventh; the defect entry
named six, and it has the same shape.)

* `cli._preservation_feature` now carries all seven into the contract's
  preservation row, so all seven reach the frozen acceptance revision and
  therefore `contract_sha256` in the review envelope;
* `preservation._seed_material` takes `alignment_transform` as well, because it
  is the one of the seven that says which geometry the plan is a plan *of*: a
  region box is written in the job's frame, so moving the source under it makes
  the same box select different surface. It is *bound* there, not applied — the
  audit is not frame-aware, and coordinated multi-source preservation is out of
  scope for this release. `SAMPLE_PLAN_VERSION` is 2 accordingly;
* the other six are contract-only on purpose. They are promises about the edit,
  not statements about where the geometry is, and none of them changes which
  points are sampled. Putting them in the seed would move a sample-plan digest to
  advertise a measurement that was not rerun.

### Fixed — the execution plan bound nothing a reviewer answered

`ExecutionPlan.plan_hash()` reached `final_status.json` and nothing else, and
that file is written *after* the review it should have bound. So `builder`,
`source_mode`, `lane_status`, `lane_note` and `preserved_artifact_ids` — the
lane cap included — could change under a stored answer and keep it.
`ReviewEnvelope` carries `execution_plan_sha256` now, supplied at all three review
boundaries — safety, verification, and the `FITTED` specification recovery, which
is only asked for because the plan routed `FITTED`.
`REVIEW_PROTOCOL_VERSION` is 3: the envelope's
shape changed, so a stored protocol-2 answer is refused by name rather than by an
unexplained digest mismatch. No fixture or benchmark carried one.

### Added — the Release 1 rerun-rejection proofs, run end to end

`ROADMAP.md` Release 1 asks for five rerun-rejection proofs. The nearest tests
compared two digests computed in-process without running a job, or fabricated a
digest rather than changing an input; none offered a review a stored response or
checked whether a final status was written anyway. `test_phase3.py` now runs the
whole loop — run to the review pause, store the answer, change exactly one thing,
rerun — over changed source, changed candidate, changed algorithm version and
every edit-intent field, and requires both a `ReviewError` and no
`final_status.json`. Seven of the eleven cases failed before this change. A
twelfth case covers the protocol bump: a stored protocol-2 answer is refused by
version, not reinterpreted.

Two more shapes had been demonstrated and never tested: a two-scope job, where
changing one scope must leave the other artifact's evidence byte-identical and
must still refuse the answer; and clean-clone reproduction for the `MODIFY` lane,
where the two existing two-directory tests are certified-template `DIRECT` jobs
with no edit scope, no preservation audit and no sample plan. `module_sha256` is
excluded from the clone comparison, and the exclusion is asserted rather than
assumed: the confined build stages `model.py` alone into a sandbox and runs it
there, so a `MODIFY` model must name its source artifact by absolute path.

### Changed — Release 1 no longer claims evidence reuse

Its scope said "reuse valid evidence for unchanged inputs". The code has never
done that and should not: only the build is cached, a preservation audit is about
two seconds, and a cache key for one would have to name exactly the bindings this
release exists to get right. A wrong key serves a stale audit under a fresh
receipt. `ROADMAP.md` now says what the code does — identical inputs re-derive
byte-identical evidence, which is idempotence and is what makes the round trip
resumable.

### Fixed — the candidate is built with less authority, not just in another interpreter

The previous entry moved the builder into its own process. An adversarial review
then walked through it three ways, and none of them needed an import, a race, or
anything to persist:

* `pipeline/backends/authored.py` is first imported by the parent **after**
  `isolation.build` returns, on the path of every authored job. The candidate
  rewrote it while building and the parent executed its module-level code
  seconds later, in the interpreter holding the frozen contract. Exit 0,
  `final_status VERIFIED`, `feature-pad-section PASS expected 432.0 measured
  80.002`, contract untouched at revision 1, history `changed: []` — the
  pre-change reproduction, verbatim, on the post-change code;
* a stealth variant compiled the same patch into
  `__pycache__/authored.cpython-313.pyc`, stamped with the real file's mtime and
  size, leaving the `.py` byte-identical. Hashing the source finds nothing;
* a `DETACHED_PROCESS` grandchild outlived `subprocess.run`'s timeout: the run
  reported exit 1 `FAILED`, and 25 s later `design-tool status` reported
  `VERIFIED` with nothing outstanding.

The root cause is one sentence. Separation was implemented as a different
*interpreter* and the claim ADR 0002 needs is about *privilege*. Same user, same
filesystem, no lifetime bound.

`pipeline/confine.py` replaces it with an OS-enforced confinement, built with
`ctypes` against `advapi32`/`kernel32` rather than by adding `pywin32` to a
security boundary:

* a **restricted token** whose restricting-SID list omits
  `NT AUTHORITY\Authenticated Users`, with every other group deny-only. On this
  machine `C:\` grants `Authenticated Users: Modify` by inheritance and nothing
  else the token carries grants write, so the repository, the virtual
  environment and this package's source cap at `BUILTIN\Users: Read & Execute`.
  Measured: it also refuses `socket.connect` with `WSAEACCES`;
* **low integrity**, which is what refuses the project directory, the parent's
  `%TEMP%`, the Startup folder, the sandbox's own inputs, and
  `OpenProcess(PROCESS_VM_WRITE)` against the parent. Each of those was measured
  by running the probe at *medium* integrity and watching it succeed;
* a **job object** with `KILL_ON_JOB_CLOSE` and breakaway not permitted.
  `DETACHED_PROCESS` never left a job; the attack worked because there was no
  job. `CREATE_BREAKAWAY_FROM_JOB` is the flag whose purpose *is* to leave one,
  and a grandchild that passes it is measured not to. The parent drains the job
  to zero live processes before it reads one byte out of the build directory;
  the count is taken by process id after a short settle, because a job keeps
  counting a process until its last handle closes and because Windows puts its
  own transient `conhost.exe` in there for under 100 ms of every run;
* exactly **two inherited handles**, named in a
  `PROC_THREAD_ATTRIBUTE_HANDLE_LIST`: a `NUL` and one pipe for the transcript;
* a **constructed environment**. Three of the attacks found the tree they
  rewrote by reading `PYTHONPATH` out of an inherited one.

Every privilege is deleted except `SeChangeNotifyPrivilege` — bypass traverse
checking, which `Everyone` holds by default and which grants access to no object.

The workspace is two directories with protected DACLs that inherit nothing:
`in\` holds **copies** of `model.py` and every `*.py` beside it and is sealed
read-only after staging, and `out\` is labelled Low and is the only object on
the machine the child can write. The child is no longer told where the project
is; it gets a directory and a file name.

Ordering, which is most of the repair: every input is hashed **before** the
child exists, so `module_sha256` names what ran rather than what survived; and
nothing is read out of the build directory until the job is dead. Each output is
then checked by exact byte compare against the name asked for, refused if it is
a reparse point, refused if it carries an alternate data stream, refused if its
real path resolves outside the sandbox, and hashed by the parent.

Staging every `*.py` beside `model.py` also closed a gap nobody had named: the
old boundary put the whole *project directory* on the child's `sys.path` and the
receipt recorded one digest, so a part built from a model and a helper was
described by a contract naming half of it. `model_contract.json`'s `source`
block now carries `sources_sha256`, a digest per staged file.

**Source-integrity hashing is not the gate.** The `.pyc` attack is the reason:
it left the source byte-identical, and a check that fires after the authority has
been exercised is detection, not confinement. One narrow canary is kept over
`acceptance_contract.json`, and a failure of it is reported as a failure of the
boundary rather than as a finding about the model.

**Named limitations, measured and asserted still open** (`docs/defects.md` D9):
DNS resolution still succeeds through the DNS Client service, which is a
low-bandwidth outbound channel; `AppData\LocalLow` and `%TEMP%\Low` carry an
explicit Low label from Windows and are therefore writable; and the candidate
can still *read* what `BUILTIN\Users` can read, including the contract it is
measured against. `AppContainer` is the mechanism that closes the first and the
third; an Untrusted integrity level closes the second and does not start
(`STATUS_DLL_INIT_FAILED`, measured), as does a `NULL`-SID lockdown token used as
a primary token.

Deleted rather than layered: `PARENT_OWNED`, `PARENT_OWNED_DIRS`, `_guarded`,
`_snapshot` and `_restore` — an eighteen-name list that had to be kept in step
with `acceptance.INVALIDATED_BY_A_NEW_REVISION` and whose failure mode was a
silent gap, replaced by an operating system that does not let the write happen;
`_child_env`, which handed over `os.environ`; and `subprocess` from the boundary
entirely, which means the D8 mutation "launch the child with `shell=True`" has no
expression left to mutate.

Tests: `pipeline/test_isolation.py` grew from 16 to 58. It carries the three
attacks that broke `0a8e464`, a write into the virtual environment, a grandchild
that asks the kernel to leave the job, an escape through a junction, one probe
model that measures fourteen confinement properties from inside the confinement
and asserts the three named limitations still open, and the first tests
`pipeline/build_child.py` has ever had. Every one of the ported attacks fails
against `893c9cc` and passes here; 27 of the 53 tests that can run against the
old boundary fail on it.

`DIRECT` creating no process is now proven with `sys.addaudithook` over a
`pipeline.confine.spawn` audit event rather than by replacing two module
attributes, because a hook catches a process created through a name nobody
thought to replace.

Mutation kill rate, same method both sides (apply one weakening to a clean copy
of the tree, run `test_isolation.py`): **5 of 15 before, 25 of 25 after.** The
before figure is the review's own fifteen against `893c9cc`, reproduced exactly.
The after figure is those fifteen mapped onto the new code — three have no target
left, because `PARENT_OWNED` and `_restore` are gone — plus thirteen for the
mechanisms this boundary added: `Authenticated Users` back in the restricting
set, medium integrity, every privilege kept, the job never terminated, survivors
never counted, the sweep removed, alternate data streams and reparse points
unchecked, every inheritable handle inherited, the environment inherited, the
confinement made optional, the parent reading before the job drains, and sibling
sources not staged.

Four survived the first pass and each one was a real gap, now closed: the
timeout was asserted as a constant and not as `build`'s default; nothing built a
manifest declaring another protocol, so the schema check was extracted into
`_sections` and unit-tested; nothing asserted the sandbox is deleted; and
nothing asserted the child's transcript is captured rather than inherited, which
also turned up a genuine hole — a model that printed a measurement and then
raised had the print discarded, and the manifest-error path now carries it.

Suite: 964 passed / 4 skipped / 379 subtests to 1006 passed / 4 skipped / 419
subtests, 673 s to 794 s. `design-tool selftest` 11/11, `gen_harness --check`
11/11, no frozen contract hash moved, ruff and the internal link check clean.

Cost: a whole authored `design-tool run` goes 1.674 s to 1.668 s, and the
confinement's own share of it is about 0.14 s — free next to the cold geometry
import it wraps. `DIRECT` is untouched: 0.191 s to 0.186 s on `c_clip`, inside
the run-to-run spread, dispatch 0 to 0.

### Fixed — the candidate is built in a process that cannot reach its own gate

Freezing the acceptance contract before the builder was necessary and was not
sufficient. `cli._run_authored` froze the contract and then imported the
candidate's `model.py` with `spec.loader.exec_module` **in the CLI's own
interpreter**, and an import is an execution: `runner.status is pipeline.status`,
`status.decide` resolves at call time, `commission._tol` and
`contract.area_tolerance` are module globals, `AcceptanceSource.expectations` is
one assignment, and the live frozen contract sat in the calling frame one
`sys._getframe()` away. Reproduced to a `VERIFIED` final status on the same
352 mm2 miss, with the on-disk contract still at revision 1 and an empty
`changed` list.

`model.py` now runs in a **one-shot child process** — `sys.executable -m
pipeline.build_child`, an argument vector and never a shell string, so it works
on Windows without `fork` and a path with a space in it survives.
`pipeline/isolation.py` is the parent half: it hands the child a model path, a
scratch directory, two output names and whether a STEP is wanted, and *nothing*
about acceptance. Results come back as JSON and files. The parent re-reads and
re-hashes the geometry itself, copies only the two artifacts it asked for by
name, and verifies that every pipeline-owned file in the project directory — the
frozen contract, its history, the proposal, the project, every receipt, and
`model.py` — is byte-identical to what it was before the child started. One that
moved is restored and the run is refused.

Consequences a designer will notice: `PARAMS` and `PROVENANCE` must be JSON, the
model's own directory is deterministically on `sys.path` rather than depending on
where the command was invoked from, and the candidate cannot write a receipt.

`DIRECT` executes no candidate code and does not enter the boundary; `runner.py`
does not import it. Measured unchanged at 0.191 s (`c_clip`) and 0.243 s
(`trim_ring`, warm).
A certified INCONSEQUENTIAL `DIRECT` job still makes zero dispatches: the
boundary is a process, not a round trip. An authored build pays one cold
interpreter, of which 0.16 s is the boundary and the rest is the geometry kernel
the candidate itself imports.

Deleted as redundant rather than left beside it: the builder callable no longer
crosses into the parent at all (`JobRequest.authored_builder` and
`.authored_model` are gone, `backends/authored.py` no longer imports a geometry
kernel or calls anything), and `cli.py` no longer imports the module that
executes model files.

### Added — a deterministic pipeline with certified INCONSEQUENTIAL DIRECT zero dispatches

Six iterations of the approved redesign. The entry below describing `DIRECT` as
"two dispatches" is what this replaced: on a certified template inside its
domain, certified `INCONSEQUENTIAL` `DIRECT` now costs **zero specialist calls**, and
the whole job — contract, build, commission, screening, witness, status — measures
well under a second for the certified trimesh path on the reference workstation.
A build123d cold import or a static interface check can cost more; these are
environment measurements, not guarantees. A certified `CONSEQUENTIAL` `DIRECT` job instead has one
bounded safety review and no normal geometric verifier.

The shape of it:

* **The contract is written before the geometry** and frozen at build start.
  `model_contract.json` names every mandatory feature with five properties:
  where its number came from, what it should measure, the tolerance, which check
  proves it, and what to do when that check cannot run. `preflight` refuses a
  contract missing any of them.
* **Expectations share no code path with the backends.** `expectations.py`
  imports `math` and nothing else, so geometry and expectation cannot fail
  together. Asserted by an import-graph test, not by a naming convention.
* **Fail-closed.** A check that cannot run escalates or fails per the contract.
  There is no `SKIP`, deliberately.
* **Broad screening**, measured against a mutation corpus over every certified
  template and scored on defects fused to the part — the ones the component
  detector does not catch for free. `python -m pipeline.corpus` is the gate, and
  it moves the final status rather than editing a claim string.
* **Routes**: certified `INCONSEQUENTIAL DIRECT` has no review callback; certified
  `CONSEQUENTIAL DIRECT` has exactly one bounded safety review and no normal
  geometric verifier; `FITTED` requires one bounded specification review; and
  `FULL` requires specification plus independent verification. `VERIFIED` is
  reachable only through independent verification that never saw the designer's
  reasoning.
* **Five certified templates**, `c_clip`, `box_shell`, `l_bracket`, `trim_ring`
  and `vented_enclosure`, each with parameter bounds that route an
  out-of-domain job away from `DIRECT` rather than building it anyway.
* **Content-addressed caching**, keyed on the contract hash, template,
  `domain_id`, backend version, lockfile, schema version and tessellation
  settings. Off unless asked for.

Measured cold on the reference workstation for certified `INCONSEQUENTIAL` `DIRECT`
jobs: zero specialist calls; a 12-vent enclosure in 0.42 s, 72 vents in 0.53 s,
and 300 vents in 0.78 s on the trimesh path. These measurements do not cover every
template or environment.

### Changed — consequence is two levels, everywhere

An earlier revision classified jobs with four risk-tier names and then wrote a
two-value enum into `job.json`, with nothing mapping between them: a highest-tier
job became `CONSEQUENTIAL` and every finer-grained guarantee evaporated at the
file boundary. Four names that decay to two on write are worse than two names,
because they read like protection that is not there.

`INCONSEQUENTIAL` and `CONSEQUENTIAL` are now the only levels in the charters as
well as the code. No legacy risk-tier field survives at the file boundary.
The prohibited applications did not become a third level — they are
`safety.MANDATORY_CONCERNS`, which the mandatory safety review must address
explicitly. `team-contracts-v4.md` documents the two-value consequence field and
the review obligations instead of leaving a discarded risk mapping to be guessed.


### Changed — the pipeline runs the phases a job actually has

`profile: COMPACT | FULL` decided how verbose the record was and nothing else —
the contract said outright that "both profiles run the same gates" — so a job
whose every dimension the user stated still paid all seven dispatches. It also
contradicted itself: `COMPACT` was defined as having "no recreated mating
geometry", while `REFERENCE_BUILD` exists to reconstruct exactly that.

The profile is now decided by one question, what must be recovered from
evidence, and it decides which phases run. Certified `INCONSEQUENTIAL` `DIRECT`
(dimensions stated, nothing recreated) has no review callback; certified
`CONSEQUENTIAL` `DIRECT` has exactly one bounded safety review and no normal
geometric verifier. `FITTED` retains its required bounded specification review,
with independent verification when configured; `FULL` retains specification and
independent-verification review. `PRINT_PREP` became conditional on what
`commission.json` reports rather than on the profile.

Two rules survive every profile because the archive shows what happens without
them: the plan is never authored by whoever builds the geometry — with no plan
bound, all four archived runs set their own support ceiling *after* reading
their own measurement — and verification is never folded into the build.

So `DIRECT` needs a plan it did not write. `designer_toolkit.plan` supplies one,
with conservative numbers fixed ahead of any part and stamped
`threshold_source: builtin-default`, and `plan check` rejects an unbuildable
plan at authoring time instead of after a 39-minute build.

### Removed — the tool surface that taught designers to hand-roll the gate

Three measured runs, and none executed `commission`; each hand-wrote a
verification script. They were following the documentation, whose headline
section documented `finalize` and offered a menu of seven individual
subcommands. A tool surface that offers the pieces gets the pieces assembled by
hand.

`measure`, `overhang`, `datums`, `interference`, `sweep`, `export` and
`finalize` are gone from the CLI; `commission` and `coupon` remain. Every
library function stays importable. The verifier now recomputes with the same one
command against the delivered STL — independence is a property of which inputs
you consult, and it never reads the designer's `commission.json`.

### Added — checks that cost no build, and templates that can be asked

`commission` runs a pre-build stage over a module-level `PARAMS` dict and
returns before the first CAD call when the declared numbers already settle the
question: a wall under two extrusion widths, an edge treatment at half the wall
or more, a declared size that disagrees with the plan, and a cavity mouth fillet
larger than its clearance. That last one is closed form — a fillet pulls the
wall in by its own radius at the mouth, so clearance must be ≥ radius. One
archived run bisected four full build/export/measure cycles toward it.

`designer_toolkit.templates` (`box_shell`, `panel`, `bolt_boss`, `stack`)
returns geometry together with the `PARAMS` describing it, computed from the
same arithmetic that built the solid, so the two cannot drift. `panel` reports
the narrowest material left between its openings — a plate whose holes leave a
0.6 mm rib is watertight, the right size, and unprintable, and every other gate
passes it.

`artifact_manifest.json` and `candidate_readiness.md` are now derived from those
measurements rather than retyped, with `visual_accept` and `fit_band_ok` left
blank on purpose.

### Fixed — gate defects that passed bad parts

The fit check compared a boolean intersection *volume* against the plan's
per-side *millimetres*, so a part built exactly to a declared `[0.15, 0.30]`
band failed; nothing caught it because every fixture set `interfaces: []`. The
support screen used the best orientation it could find rather than the plan's
declared `model_to_printer_matrix`. Only `support_rules[0]` was checked. Every
edge check was silently skipped on any contract-conformant plan, because the
loop required a `corner_xy` field that appears nowhere in the contract. And
`metrics.overhang_area` disagreed with the authoritative gate by 2× on a real
candidate — returning 0.0 mm² for a part the gate scored at 10,507 — because it
excluded faces by an arbitrary centroid height rather than the gate's
three-vertex bed test.

Also: `status` answered the reference-freshness question from whichever
reference happened to be listed first, so a multi-part job could change its lid
and read as clean; and all five agent definitions requested skills
(`3d-designer` and friends) that stopped existing at the single-skill
restructure, which fails silently and left every specialist starting with no
charter loaded.

### Removed — the per-harness packaging layer

The OpenCode and generic/OpenAI outputs, their generators, their tests, and
`docs/harness-matrix.md` are gone (−1,065 lines, 12 files). Once the pipeline
ships as one skill whose orchestrator dispatches by pointing a subagent at
`roles/<name>.md`, per-harness agent registration buys nothing a file read does
not: any runtime that can spawn a subagent and read a file runs the pipeline
unchanged. `PyYAML` went with them — nothing imports `yaml` any more.

`.claude/agents/` is still generated, because it is what makes
`claude --agent 3d-verifier` and `@`-mentioning a specialist work; the role file
and the agent definition remain two renderings of one source in `skills/roles/`.

### Changed — one skill, not five

The five role slices shipped as five installable skills that reached each other
by relative path. Installing them proved that broken: each archive carried the
shared assets at its own root while every `SKILL.md` still said
`../3d-modeling/references/...`, so **36 links across the five roles resolved one
directory above the install** — the files were all present, the build was green,
and an agent following its own required reading found nothing.

The orchestrator is now the skill and the four specialists are files it hands to
subagents:

```
3d-modeling.skill
  SKILL.md          <- the orchestrator; the only invocable entry point
  roles/{metrologist,designer,print-engineer,verifier}.md
  references/  scripts/
```

`skills/3d-modeling/` on disk *is* the shipped tree, so every relative link in the
archive is the same link that resolves in the repo. The roles were never
independently useful anyway — a designer with no commission refuses to start, by
design.

Dispatch is harness-neutral: the orchestrator points a subagent at
`roles/<name>.md` and gives it a dispatch id and a project directory, nothing
about the expected answer. Where a host registers named specialist agents
(generated from the same role sources into `.claude/agents/`), dispatching by
name is equivalent — the role file and the agent definition are two renderings
of one source. A host with no such registry loses nothing: a plain subagent
pointed at the role file is the whole mechanism.

`test_every_internal_link_resolves_inside_the_archive` now fails the build if any
link escapes the archive or names a missing member. It caught one leftover
immediately: `team-contracts-v4.md` still pointed at the deleted
`3d-orchestrator/SKILL.md`.

### Added — test coverage where a promise was unverified

Coverage audit found 85% over the statements the suite imported, but 2,670 lines
across 11 modules touched by no test at all.

- **`check_internal_links.py`** was a CI gate with zero tests — the same shape as
  the drift gate that turned out to pass unconditionally. 7 tests; it also gained
  a `root` parameter (it hardcoded the repo root, so it could not be pointed at a
  fixture) and `.venv`/`dist`/`temp` exclusions, since a local virtualenv's package
  READMEs are not ours to validate and can fail a run CI passes.
- **`make_3mf.py`** writes a deliverable — a malformed 3MF is not a caught error
  but a broken hand-off found at the printer. 5 tests over the OPC members a slicer
  needs, the per-part component structure multi-colour depends on, geometry
  round-tripping, and the non-watertight warning.
- **`run_cadquery_model.py`**: 236 lines, no tests, and its published exit codes
  (3 on timeout) were the least verified promises in the repo. 6 tests, all on the
  core stack since the runner's logic is not CadQuery's.
- **`python -m designer_toolkit`**: 7 smoke tests. The designer is told to call this
  CLI rather than re-author the measurement patterns, so a broken subcommand sends
  the role back to hand-rolling what the toolkit exists to prevent.
- Coverage now reads 74% over 2,159 statements — a truer figure over a bigger base.
  What remains uncovered needs a live GL context or a real Bambu Studio install.

### Changed — one plan file can serve both gates

`print_plan_checks.json` (team_preflight) and `print_plan.json` (team_tools) carried
field-for-field identical edges and support rules, differing only in whether the
version key was `schema_version` or `contract_version`. The contract asked the print
engineer to maintain both and nothing compared them. `team_preflight` now accepts
either name, verified by pointing it at team_tools' own example plan unmodified.

### Fixed — benchmark-driven role corrections

Roles were run blind against parts whose ground truth was withheld, then re-run with
identical inputs after a single change (see AGENTS.md → *Changing a role*).

- **Metrologist, rounded-edge envelopes.** It read a phone's width at "a flat region"
  — but the widest section of a rounded part is at mid-thickness, so jaws on the
  curved shoulder under-read width while the same curvature inflates thickness. The
  delivered width error fell 1.66 mm → 0.36 and length 0.61 mm → 0.01, using 15%
  fewer tokens. The re-run diagnosed the bias by name and resolved to the true
  envelope instead of shipping the biased read.
- **Metrologist, conflicts must ask.** The first run logged three caliper-vs-spec
  conflicts as open questions and stalled at DRAFT without asking anyone. Both
  sources are fallible, so neither wins on principle; a fit-critical conflict now
  goes to the user with both values and the downstream effect. The re-run withheld
  two ambiguous readings entirely rather than shipping one wrong by 2.84 mm.
- **`fdm-design.md`, part-class wall thickness.** The "4 walls" structural default was
  applied to a snap-on case, giving 2.03 mm walls where the real printed case uses
  1.02 — +1.2 mm on width and thickness and ~46% material. That default is for a part
  meant to be stiff and wrong for one meant to flex, and on a part that wraps a
  mating object the wall is a dimension entering the envelope twice.

  Measured at n=3 (one run before the change, two after). The two post-change runs
  agree to 0.05 mm on wall and 0.1 mm on both plan dimensions — 2.03 → 1.57 and
  1.52 mm/side, with material down 17% — so the effect is the change and not
  run-to-run variance. It closes about half the gap to the oracle's 1.02: both
  runs chose 1.2 mm nominal, within the guidance, then added material elsewhere.
  Thickness moved the *wrong* way in both (12.5 → 14.0 and 14.1 against an oracle
  10.74) because each independently added a camera-relief boss and retention ribs
  — a choice the wall guidance neither caused nor prevents, and one that is now
  clearly systematic rather than a fluke. Accuracy cost about a third more tokens.

### Changed — the gates enforce what the contract claims

- Mandatory safety concerns are now addressed by the bounded safety review rather
  than by a discarded R-tier contract. The two-value consequence field
  remains the only classification at the file boundary, and the safety reviewer
  must explicitly address any listed concern and its required physical evidence.
- **`contracts status` is now part of the orchestrator's readiness gate.** It is the
  only check that compares each contract's `revision` against what downstream
  contracts bound to — a `dimensions.md` revised after the plan cited it surfaces as
  `STALE` there and nowhere else — and no role invoked it.
- **Evidence binding stated honestly.** Rule 15 ("hashes bind agents to files") now
  says where binding is real: `artifact_manifest.json`, whose artifacts have their
  SHA-256 recomputed and bbox/component count re-checked. An evidence path written
  only as a Markdown table cell is not resolved by anything — a report citing a file
  that does not exist validates clean — so evidence a gate rests on must also appear
  as a manifest row.

### Changed — contracts are validated where they are actually written

`team_tools` validated JSON exclusively, but v4 defines four of the five contracts
as Markdown and no role is told anywhere to author a JSON mirror. So 393 lines of
validator schema-checked files the pipeline never creates, `validate` reported
four `MISSING_CONTRACT_FILE` warnings on every correct run, and `--require all`
rejected a project built exactly to the contract.

The binding fields were in the Markdown all along: `revision`,
`dimensions_revision`, `print_plan_revision`, `reference_sha256`,
`candidate_stl_sha256` all live in the frontmatter. Each contract is now looked up
as Markdown first, then a JSON mirror if one exists, and:

- **Markdown** gets `validate_contract_header` — identity, version, owner, `job_id`,
  and the integer `revision` the staleness and binding checks compare. Its body is
  provenance, uncertainty and open questions written for the next agent to read;
  a validator walking those rows could only ever confirm that prose is prose.
- **JSON** (`artifact_manifest.json`, a machine-authored `print_plan.json`)
  additionally gets its full structural validator, unchanged.
- `validate_job_state`, `validate_dimensions` and `validate_verification_report`
  are deleted (−393 lines, plus their tests).
- `MISSING_CONTRACT_FILE` is gone. It fired on every correct run, on the same
  `warning_ids` channel that carries `POSSIBLE_UNIT_SCALE_MISMATCH` — which the
  verifier is required to act on. A benchmark designer run called those warnings
  "expected", which is precisely the habit worth not teaching. `validated_paths`
  already records what was read.

Verified against a real agent-produced project: `validate` now reads
`dimensions.md`, `job_state.md` and `artifact_manifest.json` with zero warnings,
`status` reports revisions from the Markdown, and `--require all` passes a
five-contract Markdown project. The verifier role is back to `--require all`.

### Removed — streamlining pass (net −1,534 lines, 16,767 → 15,237)

A six-axis review (docs prose, skill/role text, Python, gate value, repo hygiene,
FDM domain content) looking for duplication, dead weight, and instructions that
cost tokens without changing an outcome.

- `skills/3d-modeling/scripts/backends/` — a `ModelBackend` ABC with cadquery /
  build123d / freecad adapters and a test-only `FakeBackend`. Zero importers: the
  real export path is `designer_toolkit.exporter._write_solid`, which does its own
  dispatch and never knew the package existed.
- `team_tools` `render` and `agent-summary` subcommands (`render.py`, `summary.py`).
  No role, agent definition or reference ever invoked them, and no rendered output
  is committed anywhere. `render` generated Markdown *from* JSON, inverting a
  pipeline whose Markdown is the authored side.
- `references/preflight-checklist.md` — 135 lines with zero inbound references,
  contradicting `fdm-design.md` on chamfer size and `troubleshooting.md` on
  calibration order. Its correct thread number and its six-step calibration order
  (which included the max-volumetric-speed step the live file omitted) were
  harvested into the files that are actually loaded.
- Half of `references/build123d-patterns.md` (192 → 84): unreferenced, and the
  backend-neutral half was a verbatim clone of `cadquery-patterns.md`. Its sample
  called a `finalize(strict=True)` signature that does not exist.
- Dead Python: `verify_visual.footprint_iou` (superseded by `pose_score`),
  `MeshIntegrity.non_manifold_edge_count` (computed on every export, read by
  nothing), an `engine=` parameter no caller passes, a `team_tools/__init__`
  re-export nothing imports, and three copies of the same `_as_mesh` coercion.
- Repeated exit-code blocks, harness invocation stated in three files, a hand-run
  OpenCode checklist duplicating what `test_gen_harness.py` asserts, and per-extra
  `pyproject` comments duplicating the README table.
- `.skill` bundles no longer ship the test suite and fixtures — 412 KB → 141 KB per
  artifact, across six artifacts. Nothing in a shipped skill ran them.

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
- The generated-harness drift gate never fired. CI ran `pytest` before
  `gen_harness.py --check`, and a test shelled out to the generator *without*
  `--check`, rewriting the working tree — so the check compared regenerated files
  against themselves and passed unconditionally. Reproduced by drifting a role
  source: `--check` alone exited 1, after `pytest` it exited 0. The test now
  compares in memory and writes nothing, and `--check` runs before `pytest`.
- `manifest_checks._compare_extents` used `elif`, so a near-25.4× scale flag on any
  one axis suppressed `BBOX_MISMATCH` on every axis — a declared bbox 5× wrong on
  another axis was reported as a warning, not an error. The 25.4× promotion also
  swept all axes, so an unrelated axis landing near 25.4× could promote a warning
  to a hard error. Both fixed, with regression tests in both directions.
- `mesh_io._components` swallowed every failure into "1 component", the exact
  silent multi-body pass `connected_component_count` was written to prevent. It now
  raises a `ValueError` naming the vertex/face counts; the CLI callers already
  surface `ValueError` cleanly.
- `designer_toolkit`'s overhang self-check could report clean where the authoritative
  gate FAILs — measured at 0.00 mm² vs 1873.15 mm² on a 46° face — while a comment
  claimed lockstep with a `team_preflight` default that does not exist (the field is
  required per-rule). `finalize` now records whether the threshold came from the
  caller or the toolkit default, and re-screens at the bare 45° value to announce
  the gap when they differ.
- FDM guidance corrected against the source corpus, all five independently
  re-confirmed: printed threads floored at `M8 (≥1/8")` — 8 mm glossed as 3.175 mm,
  which forced heat-set inserts onto every M4–M6 boss the sources say prints fine;
  30–40% infill against a documented 15–20%; warp-relief cuts specified at 1 mm deep
  where deeper *increases* warp (0.5 mm); bottom chamfer stated three
  incompatible ways across two files; and a 0.8 mm wall rule where 0.8 mm is the
  geometric floor and 1 mm is the design rule.
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
  −0.73 screen as the gate), `interference` (static seated boolean-overlap fit on
  the exported mesh — a single position at rest; no insertion/travel sweep is
  computed, and dynamic motion fit is deferred), `fit_coupon` (parametric
  multi-lane coupon from the plan's
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
