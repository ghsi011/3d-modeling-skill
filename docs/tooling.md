# Tooling reference

This page documents the deterministic tool surfaces used by the 3D modeling
team pipeline. Run repository tools from the repo root unless a command says
otherwise. The shared modeling scripts live in
[`skills/3d-modeling/scripts/`](../skills/3d-modeling/scripts/).

For the core runtime and the optional extras each tool needs, see
[Dependencies](../README.md#dependencies) in the README.

Exit code convention across these tools:

| Code | Meaning |
| --- | --- |
| 0 | Command completed successfully. For validation commands, the checked gate passed. |
| 1 | The command ran but the gate failed, output verification failed, or an uncaught runtime error occurred. |
| 2 | Command line usage failed, an input contract was malformed, a file could not be opened, or a strict preflight guard rejected the input. A file that is simply *absent* is not always an open failure: `team_tools.contracts validate` records a missing contract as a warning and still exits `0` unless the caller named it with `--require`. |

Individual tools narrow or extend this table below.

## `design-tool` — the canonical project surface

One command surface over one machine-authoritative project file. See
[ADR 0001](adr/0001-one-project-one-cli.md) for why there used to be two.

```bash
uv run design-tool init <project> --job-id J --source-mode NEW|MODIFY|RECONSTRUCT \
    --consequence INCONSEQUENTIAL|CONSEQUENTIAL --updated-utc <iso8601> [--from-job-json]
uv run design-tool route  <project>
uv run design-tool run    <project> [--no-render] [--resume | --restart]
uv run design-tool status <project> [--json]
uv run design-tool branch <project> --from <alternative|.> --id <name> --reason "<text>"
uv run design-tool branch <project> --activate <alternative|.>
uv run design-tool branch <project> --disposition <state> [--of <alternative>] \
    --basis <basis> [--superseded-by <alternative>]
```

| exit | meaning |
| --- | --- |
| 0 | the job finished; there is nothing outstanding |
| 1 | a gate failed — the geometry does not match its contract, a review rejected it, or the lane may not claim success (`EXPERIMENTAL_UNAVAILABLE`, `UNSUPPORTED`) |
| 2 | `project.json` is malformed or incomplete and every missing field is named, or a `branch` was refused and the reason is named |
| 3 | something has to be answered or built before this can continue — read `next_action.json` |

### `project.json`

The one authoritative description of a job, validated by
[`pipeline/project.py`](../skills/3d-modeling/scripts/pipeline/project.py). It carries the
job id, source mode, consequence and rationale, the manufacturing inputs, every
requirement with its provenance (`STATED` / `INHERITED` / `MEASURED` / `CHOSEN`),
source artifacts with hashes, classification and — where the job says — the
role each one plays, interfaces and who owns the other side of each, declared motion, edit scope, expected components, open questions,
required reviews, and — only once the job has branched — its design alternatives
and which one is active.

A source artifact's `role` is one of `ARCHITECTURE.md` 6.2's eight, and
declaring it is optional — a project that says nothing is a project nobody asked,
not one granting permission. Four of them name geometry this job owns and may
derive from: `BASE`, `DONOR`, `PRIOR_REVISION`, `ALTERNATIVE_CANDIDATE`. The
other four name geometry it only reads: `MATING_OBJECT` (what the part fits),
`MEASUREMENT_REFERENCE` (what it was measured against), `VISUAL_ENVELOPE` (the
space it must fit inside) and `PRODUCTION_EXPORT` (a file already handed
downstream). **Declaring one of those four forbids an edit scope over that
artifact**, and the run is refused — because an edit scope compiles a
preservation row, so the job would go on to measure whether somebody else's
object survived its edit.

Note that `role` on a source artifact and `role` on a component are different
fields with different vocabularies: the first says what a supplied file is *for*
and is one of the eight above; the second is free text naming what a printed
body *is*.

A component may name `inherited_from` — the declared source artifact this output
body came out of — and `inherited_materials`, what the donor declared. The second
is recorded and not acted on: `material` remains what this job will print, and a
component honestly carries both without the receipt reading as a multi-material
capability. `ARCHITECTURE.md` 6.8 is the obligation: imported intent the current
job does not use is preserved rather than discarded.

It also carries `datums` where a job declares any: a shared geometric reference
with an identity, a value, a provenance, the artifact **revision** it was read on
where it was read off geometry, and the artifacts, components or interfaces it is
valid for. Coordinated edit scopes name one datum identity through `datum_ids`
rather than each holding a copy of the number
([ADR 0003](adr/0003-datum-provenance-and-authority.md)). A datum with no recorded
provenance is permitted and is an assumption: it names an owner and the check that
would settle it, and `design-tool status` reports it. Changing a datum's *value*
currently invalidates nothing — see `ROADMAP.md` — which is why a job with an edit
scope cannot claim success.

There is no `status` and no `bindings` block. They mirrored one run's outcome —
its stage, its final status, its allowed claim and its artifact digests — into
the one file that has to stay shared, so the project said the job was whatever
had finished last, and a branch could not stamp them at all without saying that
about its sibling. A formulation's outcome is `final_status.json` in that
formulation's own directory, and whether it is still *current* is derived from
the bindings on disk rather than repeated from a copy nothing keeps in step. A
project file written under the old mirror still loads: what is dropped is a copy
of something that is on disk in its own right, and the one value in there that
was a declaration rather than an outcome — `external_geometry`, which the
`job.json` adapter recorded — is read across into its own field.

There is no `candidate_strategy`. `PARALLEL` was validated, stored and hashed,
and its entire behavioural effect was one extra sentence in the route rationale:
nothing generated a second candidate, isolated one, or compared two. A project
carrying it is refused by name and pointed at `design-tool branch`; `SINGLE` is
read and dropped, because it claimed nothing.

Nothing is invented. `init` writes a skeleton in which every field you must supply
is present and empty, and prints them as a to-do list; `run` refuses with exit 2
until they are filled, naming all of them at once rather than one per round trip.

A directory holding only a legacy `job.json` is adapted on first `run` and marked
`compat: "job.json@1"`, which keeps it routing under the pre-consolidation rules.
Old completed projects need no migration.

### `next_action.json`

What the job is waiting for, written when `route` or `run` stops and deleted when
the job finishes:

| kind | meaning |
| --- | --- |
| `FIX_PROJECT` | something has to be corrected before the run can continue; `unresolved` names every problem and `findings` carries the same list as structure. `stage` says what refused: `route`/`run` for an incomplete `project.json`, or `plan`, `proposal` or `build` |
| `RUN` | the route is decided and the plan is compiled, and nothing has been executed against it |
| `AGENT_COMMISSION` | a specialist has to produce something — `role`, `authorized_inputs`, `required_outputs`, `bound` hashes, `completion_command` |
| `REVIEW` | a bounded review is needed — `evidence` is the packet, `respond_with` is where the answer goes |
| `NEEDS_EVIDENCE` / `BLOCKED` | the run completed but could not reach a claim, or a gate failed; `unresolved` carries the status reasons |
| `LANE_UNAVAILABLE` | the run completed and the lane is not allowed to claim success; nothing an agent writes lifts it, which is why it is not a `REVIEW` |

A commission carries no expectation of what the specialist should conclude. That
is not politeness: a verifier told what to conclude has stopped being a verifier.

A `FIX_PROJECT` instruction also carries `findings`, one entry per `unresolved`
line and in the same order. Every refusal that stops a run before it can reach a
claim is one — the incomplete project, and also the missing envelope, the plan
that does not validate, the refused proposal, the refused build and the model
that contradicts its proposal, all of which report through the same function and
carry the stage they came from in `stage`:

| field | meaning |
| --- | --- |
| `code` | what kind of problem, from a small closed vocabulary (below) |
| `where` | the exact field path — `edit_scopes[1].region_box`, not "edit scope" |
| `severity` | `error` or `warning` |
| `id` | `CODE@where`; stable across runs, and unique within one instruction |
| `message` | the same sentence `unresolved` carries and the terminal prints |

The code's prefix says what has to change to clear it, which is the one grouping
that tells a reader whose problem it is: `SCHEMA_` correct a field, `REF_` add or
rename a row, `ARTIFACT_` fix a file the project names, `INTENT_` make a
decision. `pipeline/findings.py` holds the vocabulary and the rule.

`unresolved` is unchanged and stays a list of sentences: four different stages
write it, from a validator, from a status derivation, from a stage message and
from the project's open questions, so a reader cannot be asked to work out which
of the four filled the list it is holding. `design-tool status --json` reports
the same pair — `problems` and `findings` — for the project it is describing.

Every instruction carries `state` — the acceptance contract, the model contract,
the execution plan, the three artifact digests and which formulation this is —
and `state_sha256` over it. That is the same map `design-tool status` checks the
receipts against, deliberately: an instruction and a receipt go stale for the
same reasons, and two answers to "has this project moved" is one answer and one
bug. `status` reports `waiting_for_superseded` when the digest no longer matches,
and does not count a superseded instruction as something to do. `state_sha256` is
the **run identity** under another name and by the same function — see *Run
identity* below and [ADR 0004](adr/0004-run-identity-is-content-derived.md).

The file used to carry no identity at all — no run id, no sequence, no digest —
so staleness was handled entirely by overwriting or unlinking it, and any path
that changed the project without reaching one of those two calls left an
instruction pointing at work already done. A successful `route` was exactly such
a path (D17): it wrote "this project cannot be routed", the project was then
completed, and the sentence stayed. `route` now recomputes the instruction
against the state after routing — nothing, when the receipts still support a
current success; `RUN` otherwise.

`bound` carries `requirement_sha256` — the brief, the stated, inherited and
measured values, the envelope, the interfaces, the components and the modifiers,
which is the half of the job nobody on the design side owns and the same digest
the frozen acceptance contract carries. It replaced a digest of the whole
`project.json`, which covered the then-mutable `status` and `bindings` blocks and
so moved every time a run finished, binding nothing to anything. Those two blocks
have since been removed for the same reason.

### `design-tool status` — derived, not repeated

The status was **stored**: `status.decide` ran once, mid-run, its answer went
into `final_status.json`, and every reader from then on repeated it verbatim.
`design-tool status` recomputed the project's `problems` and took the verdict as
given, so a `VERIFIED` receipt beside a candidate somebody had rebuilt, an
evidence file somebody had corrected, or an execution plan that had since moved
all read as current.

`final_status` in the report is now **derived**. `bindings.py` reads each
receipt's own record of what it was issued against — the artifact manifest's
digests, the commissioning report's contract hash, a review report's whole
envelope including the witness images and evidence files it was shown, the final
status's artifact hashes and plan digest — and compares it against what is on
disk. A stored `COMMISSIONED` or `VERIFIED` whose receipts no longer bind derives
`STALE`; a directory where no run has concluded derives `NOT_RUN`.

| field | meaning |
| --- | --- |
| `final_status` | what the evidence on disk currently supports |
| `stored_status` | what the run concluded, still the record of that run |
| `stale` | each receipt that no longer binds, and which binding broke |
| `state` | the binding values the receipts are being checked against |
| `bindings` | this formulation's own artifact hashes, from its own final status |
| `assumptions` | every declared datum nobody measured — its id, its provenance, who settles it, and what settling it means. The provenance is there because the two kinds are not the same: `CHOSEN` is a number somebody picked deliberately, and an empty one was never recorded at all, which is the distinction ADR 0003 decision 1 exists to keep. Empty on a job that declares none, and the terminal prints nothing. This is where an assumption is *findable*: it is deliberately not a `validate` finding, because every caller there refuses the run on a non-empty list and ADR 0003 says an assumption does not refuse the job |
| `problems` | every reason the project cannot be routed, as sentences |
| `findings` | the same list as structure — `code`, `where`, `severity`, `id` — so "which alternative and which field" is a match rather than a search |
| `alternatives[]` | one row per formulation — the shared root **and** every declared alternative — each carrying `status`, `stored_status`, `stale` (the receipt **names** only -- the reasons stay on the top-level `stale`), `allowed_claim` and `reasons`, derived in that formulation's own directory, so switching branches is not the price of finding out where the other one stands. The root has no declared row in `project.json` and is synthesised into the report: it is a formulation by having a directory, a proposal, a contract and its own receipts. Iterating only the declared rows was `docs/defects.md` D26, where this block counted two formulations of the recorded knob and `cost` below counted three |
| `run_id` | which run this formulation currently is — the digest of `state`, content-derived; see *Run identity* below |
| `fallbacks` | every formulation the user declared `FALLBACK`, with its own derived status. The terminal names them only when `final_status` is not a claim, which is when the question is live |
| `lifecycle` | `lifecycle.json`'s events, oldest first: the restarts and the disposition transitions |
| `cost` | what each formulation spent, the project total, and `incremental` — what each formulation beyond the shared root *added*, with `shared` naming what it inherited. Branching shares intent, which is free; the build, the audit and the reviews are paid again per formulation, and the figure is read off the ledgers rather than asserted. See *`cost.json`* below |

Two rules bound it. **It is not a second gate**: nothing is re-run and no
threshold is re-applied, so a job whose bindings all hold derives exactly what it
stored. And it can only ever weaken — a `FAILED` or `NEEDS_MORE_EVIDENCE` whose
bindings broke keeps its own name and carries the breakage alongside, because a
finding replaced by "this is out of date" is a defect nobody is looking at any
more. That is the same choice the lane cap makes in `status.decide`.

`status` never writes. Reporting a broken binding is not invalidating it: a
superseded receipt is neither current nor erased, and a command that tidied away
the evidence it was describing would change the thing it was asked about.

### Invalidation: what depended on the thing that changed

`design-tool run` removes the receipts whose bindings no longer hold, immediately
before executing, and says what it removed. A new acceptance revision does the
same through `acceptance.freeze`, which additionally writes their digests into
`acceptance_history.json`.

The rule is derived from the bindings rather than from a list of names. It used
to be a fixed six-name tuple deleted on any acceptance revision, which could
express "something changed, therefore everything is stale" and nothing else. Now:

* an **acceptance revision** still reaches every receipt — each one binds the
  model contract's hash and the model contract binds the acceptance contract's,
  so one broken edge takes the chain, and the set is the same six files;
* a **rebuilt candidate** takes the artifact manifest, the commissioning report
  measured beside it, the reviews and the final status;
* a **corrected evidence file** takes only the reviews that were shown it and the
  status that rested on them. The commissioning measurements of a candidate that
  did not move are still true and stay on disk;
* a change inside **one alternative** reaches nothing in a sibling's directory,
  because the whole comparison is scoped to one formulation's work directory.

`model_contract.json` is reported stale and never removed: it is the contract
every other receipt binds, and deleting it would turn "issued against a contract
that has moved" into "there is no contract here", which says less and is no more
true.

### Run identity: which run this is, and why it is not a counter

`design-tool status --json` reports `run_id`: the SHA-256 of the binding map the
formulation currently presents — its frozen acceptance contract, its model
contract, its execution plan, its STL, its STEP, its source, and which
formulation it is. `next_action.json` carries the same value as `state_sha256`,
computed by the same function (`pipeline.bindings.identity`), because an
instruction and a receipt go stale for the same reasons and two answers to "has
this project moved" is one answer and one bug.

It is **content-derived on purpose**. An invocation counter would answer "which
invocation produced this receipt" by ending the property this command surface is
built around: `--updated-utc` is required from the caller precisely so a rerun on
unchanged inputs is byte-identical, and a counter differs on the second run of
every job. Two invocations over identical bindings produce identical evidence and
are interchangeable in every claim the system can make — they are the same run,
and the identity says so.

What it buys over any single existing digest is the last entry in the map. Two
formulations are byte-identical at the instant one is branched from the other:
same contract hash, same artifact digests, same plan. Their run identities
differ, because `alternative` is a binding.

### `design-tool run --resume` and `--restart`

A bare `run` resumes: it reuses every receipt whose bindings still hold and
discards exactly those that do not (see *Invalidation* above).

`--resume` is that, said out loud. It asserts the precondition the default
assumes — that something here has concluded — and **refuses with exit 2 when
nothing has**, rather than starting from nothing under a word that promised
otherwise. It also prints what is being reused before the run touches anything.

`--restart` discards what **this formulation concluded** and builds it again:

| discarded | kept |
| --- | --- |
| the six removable receipts (`artifact_manifest.json`, `commission_report.json`, `manufacturing_report.json`, both review reports, `final_status.json`) | `acceptance_contract.json` and its history — deleting it would cut a spurious revision on the next run |
| `reviews/<kind>_response.json` — the answers | `reviews/<kind>_packet.json` — the questions, rewritten every run |
| `next_action.json` | `design_proposal.json`, `model.py`, `model_contract.json`, `execution_plan.json` |
| | the content cache, and **every sibling formulation** |

It is not "delete everything and start again". The expensive work here is
content-addressed, so re-deriving it is cheap and correct; the proposal and the
model are *inputs*, not conclusions; and a restart scoped to the project rather
than the formulation would invalidate siblings, which section 13.5 forbids. A
restart that throws away still-valid work is a worse default than no restart.

What it buys that resume cannot is the one case scoped invalidation is blind to
by construction: **a conclusion whose bindings all still hold and that somebody
no longer trusts**. A review answered `PASS` against evidence that has not moved
is reused by resume forever, correctly. `--restart` is the only way to ask again.

Everything it removes is recorded in `lifecycle.json` first — name, SHA-256, the
verdict discarded and the run identity it was issued under — because a restart is
the one operation here that erases a receipt whose bindings still hold, and
"neither current nor erased" needs somewhere durable to live.

### `lifecycle.json` — what was deliberately done to this job

At the project root, appended to and **bound by nothing**: no receipt carries its
digest, `bindings.RECEIPTS` does not name it, and writing to it cannot make
anything stale. That is what lets it hold the one thing a content-derived
identity cannot — a record ordered by when things happened, in a build whose
every other artifact is ordered by what it contains. Every event is stamped with
the project's caller-supplied `updated_utc` rather than a clock.

| event | recorded |
| --- | --- |
| `RESTART` | the formulation, the run identity, the stored verdict discarded, and every discarded file with its digest |
| `DISPOSITION` | the formulation, the state it left, the state it entered, the basis, any successor, and a note — including the automatic demotion when a new formulation is preferred |

### `cost.json` — what the job spent, and what it was allowed to spend

In each formulation's own directory, appended to, and **bound by nothing** for
`lifecycle.json`'s reason: no receipt carries its digest, `bindings.RECEIPTS`
does not name it, and writing to it cannot make anything stale. A rerun on
unchanged inputs still moves no receipt and no run identity; what it moves is
this file, which is the honest record that the rerun happened and cost something.

One entry per invocation of `design-tool run`, including the ones that concluded
nothing — a run that spent two seconds and then stopped to ask for a review is
exactly the failed and repeated work `ARCHITECTURE.md` 15.6 asks to be visible,
and a file describing only the last invocation reports a third of what a review
round trip costs.

| total | what it is |
| --- | --- |
| `dispatches` / `reviews` / `commissions` | questions actually put to a model. The **commission** is counted here and is not in `llm_calls`: `AGENT_COMMISSION` is written by `cli.py` before the runner is reached |
| `reviews_reused` | stored answers a resumed run read back. `llm_calls` counts each of these as a fresh dispatch; this is the number that says how many were not |
| `context_bytes` | the canonical size of each payload handed over, at the moment it was handed over. For a commission, the instruction plus every file `authorized_inputs` names. Bytes, not tokens — there is no tokenizer here |
| `deterministic_seconds` / `build_boundary_seconds` | wall time inside the runner, and the confined child that ran before it |
| `builds` / `repeated_builds` | builds, and builds beyond the first. A two-review round trip is three builds of one part |
| `builds_avoided` / `cache` | the cache status per invocation, and the builds a hit actually saved — zero, because the cache is consulted *after* `backend.build` returns |
| `failed_invocations` | invocations that produced no claim: a pause, a refusal, or a capped lane |
| `budget` / `overruns` | the ceiling the compiled plan authorises, and anything spent past it |

**The budget is declared by the plan and checked against the ledger.**
`cost.budget(plan)` derives what one invocation may dispatch from the compiled
plan and nothing else: one safety review when the plan requires it, one
specification when the plan can actually run it, one verification unless the
route traded it away, one commission when the geometry is authored. A run that
spends past it is refused with stage `cost` — runtime execution follows the
compiled plan, which is the authority gate rather than a cost footnote. The
route-level numbers are frozen in `pipeline/cost.py` beside the code that ships,
the way `selftest.FROZEN_CONTRACTS` freezes a certified contract, so
`ROADMAP.md` 3.4's "no release may add an AI round trip to an existing path as an
accidental side effect" fails a test instead of going unnoticed.

`design-tool status --json` reports it per formulation under `cost`, with
`incremental` naming what each formulation beyond the shared root added and
`shared` naming what it inherited — see the next section.

### `design-tool branch --disposition` — the alternative lifecycle

```bash
uv run design-tool branch <project> --disposition PREFERRED --of plate-seated --basis PHYSICAL_TEST
uv run design-tool branch <project> --disposition PAUSED --basis UNRESOLVED_EVIDENCE
uv run design-tool branch <project> --disposition SUPERSEDED --of v1 --basis STRONGER_CONCEPT --superseded-by v2
```

`--of` defaults to the active formulation. A transition is not combined with
creating a branch or with `--activate`: a new branch starts `ACTIVE`, and a
lifecycle move is a decision worth its own command and its own record. The whole
project is validated before anything is written, so a refused transition changes
nothing on disk.

All seven states are honoured, and each one changes something:

| state | may be worked under | what it changes |
| --- | --- | --- |
| `ACTIVE` | yes | the state a branch starts in; the only one needing no basis |
| `PREFERRED` | yes | **at most one per project** — two are two answers to what the job's design is. Preferring one demotes the previous holder to `ACTIVE` (13.3: the previous preferred is not erased) and journals both halves |
| `FALLBACK` | yes | retained rather than abandoned. `design-tool status` names it as the option to fall back on exactly when the current formulation has no claim it may make |
| `PAUSED` | no | parked. A run cannot silently continue it; its `next_action.json` is **kept**, because that is what to do on resuming. Resuming is `--disposition ACTIVE`, which is a recorded transition rather than a silent activation |
| `REJECTED` | no | concluded. Its `next_action.json` is **cleared** — a formulation nobody will pick up again is waiting for nothing — and its receipts are untouched, because a rejection is evidence |
| `SUPERSEDED` | no | as `REJECTED`, and must name the declared formulation that replaced it |
| `MERGED` | no | as `SUPERSEDED`, and **refused unless the successor lists this formulation among its `parents`**. This build performs no merges; the state cannot be claimed ahead of a revision graph that records one |

Setting a non-runnable state on the active formulation moves the project to the
shared root, so that the next command a user runs is not a refusal they did not
ask for.

### `design-tool branch` — competing formulations of one job

```bash
uv run design-tool branch <project> --from . --id snap-fit --reason "no fasteners to lose"
uv run design-tool branch <project> --from snap-fit --id snap-fit-thicker --reason "..."
uv run design-tool branch <project> --activate .          # back to the shared root
```

Deterministic and free: no dispatch, no build, **and no copy**. It appends one
row to `project.json`, creates the directory that row names, and makes it active.

| field | meaning |
| --- | --- |
| `alternative_id` | lower-case letters, digits and hyphens. It becomes a directory name and appears in the execution plan and every review envelope, so an id two filesystems spell differently is one two receipts disagree about |
| `parents` | a **list** of ancestor ids, empty for a branch from the shared root. A list from the first release that has one, because a merge is a revision with several contributing parents and a field that has to change shape to record one is a field every reader has to be migrated off. Nothing in this release writes more than one entry |
| `reason` | why this formulation exists. Required: two alternatives with no stated difference cannot be compared, and the one nobody can justify is the one kept by accident |
| `disposition` | one of the seven states below. `branch` always creates `ACTIVE`; every other state is reached by `--disposition` |
| `basis` | why the formulation is in that state: `USER_SELECTION`, `REQUIREMENT_FAILURE`, `MANUFACTURING_DISADVANTAGE`, `PHYSICAL_TEST`, `UNRESOLVED_EVIDENCE` or `STRONGER_CONCEPT`. Required by every state but `ACTIVE`, and absent from the serialized row when empty |
| `superseded_by` | the formulation that replaced or absorbed this one. Required by `SUPERSEDED` and `MERGED`, refused elsewhere |

Ancestry order is the acyclicity rule: a parent must be declared before the child
that names it. `branch` appends, so it holds by construction, and a hand-edited
file that breaks it is refused rather than sending a later ancestry walk round a
loop.

**What moves, and what does not.** When an alternative is active, everything that
means something about *one* formulation is written under
`alternatives/<id>/`: `design_proposal.json`, `model.py`, `candidate.stl`,
`candidate.step`, `candidate_declaration.json`, `acceptance_contract.json`,
`acceptance_history.json`, `execution_plan.json`, `route_decision.json`,
`print_plan_checks.json`, `next_action.json`, `reviews/`, `witness/` and all ten
run receipts. Everything shared stays where it was and is read by reference:
`project.json`, the brief, source artifacts, evidence, the build cache and
`lifecycle.json` — the journal is shared because a disposition is a decision
taken about a formulation from outside it, and preferring one demotes another.

That is not tidiness. With one directory the collisions ran worst-first:

* two siblings froze into one `acceptance_contract.json`, so the second's
  `freeze` read the first's contract as `previous`, cut a revision, and deleted
  the first's final status, commissioning report, artifact manifest,
  manufacturing report and both review reports — which the first then did back,
  on every alternating run, while the history recorded the fork as one linear
  chain of corrections;
* the designer commission is skipped when `design_proposal.json` and `model.py`
  both exist, so a second alternative was **never commissioned**: it silently
  rebuilt the first's geometry and filed the receipts under its own name;
* `candidate.stl` and `candidate.step` are fixed literals, so the second build
  overwrote the first;
* a review is answered by the presence of `reviews/<kind>_response.json`, so one
  sibling picked up the answer written for its neighbour.

**Path isolation is necessary and not sufficient**, which is why `alternative_id`
also joins two hashed payloads — `execution_plan.json` and the review envelope,
and deliberately nothing else. `ExecutionPlan` carries no parameters, so two
authored formulations of one job compile to the same plan; the envelope's
`revision` is the job's `updated_utc`, a timestamp rather than a graph node; and
at the instant a branch is created its sibling is still a copy, so
`contract_sha256`, `artifact_hashes` and `witness_hashes` are equal too. Without
the id, a safety `PASS` written for one sibling is `is_bound` for the other. The
review protocol version is therefore `4`, and a stored protocol-3 response is
refused by name rather than by an unexplained digest mismatch.

It does **not** join `contract_sha256`: two formulations that require identical
geometry are two ways of getting there, not two parts, and they legitimately
share an acceptance contract.

**Invalidation, one rule.** A change to the shared half of `project.json`
invalidates every alternative; a change inside an alternative invalidates that
one only. Both fall out of the acceptance contract being frozen per alternative
root: a shared change moves `requirement_sha256`, so each alternative cuts its
own revision on its next run and removes its own receipts, and a branch-local
change moves nothing its sibling reads. `acceptance_history.json` records the
alternative on each entry and inside `supersedes`, so a reader can tell a
correction (a new revision of the same formulation) from a fork (a revision cut
from a different one).

**Zero cost when unused.** A project that has never branched serializes,
compiles and hashes to exactly the bytes it did before branching existed. Every
new field is *absent* when there is nothing to say and never `null`, no
subdirectory appears, and `candidate.stl` is still written at the project root.

### `design-tool compare` — what setting them side by side settles

```bash
uv run design-tool compare <project>
uv run design-tool compare <project> --against .,plate-seated --json
```

Deterministic and free. It reads the receipts each formulation already wrote,
writes `comparison.json` at the project root and prints a table. Zero dispatch,
zero build, no new project field. Every number in it was measured by a run that
had the part in front of it; the only thing added is the act of putting two of
them side by side and being explicit about what that does and does not settle.

**It has no score, no weight and no order, and it never selects.** `ranking` and
`score` are fields in the output and both are always `null`; formulations are a
JSON object keyed by id and never an array, because an array has an order and an
order reads as a ranking. Choosing is `design-tool branch --disposition`, which
records who chose and on what basis. See
[ADR 0005](adr/0005-a-comparison-refuses-rather-than-scores.md).

The default set is every formulation that may be worked under
(`ACTIVE`, `PREFERRED`, `FALLBACK`) **plus the shared root**, which is a
formulation with its own proposal, contract and receipts even though `branch`
writes no row for it. `--against` names an explicit set, including concluded
formulations — 6.14 keeps a rejected alternative available for reconsideration,
it is just not what "compare this job" means by default.

#### The first thing it reports: whether the verdicts are comparable at all

The mandatory axis carries one of three verdicts, and the reason it is three
rather than a boolean is [`docs/defects.md` D25](defects.md): on the authored
lane a formulation's own `design_proposal.json` sets the rubric it will be
graded against.

| verdict | when | what it means |
| --- | --- | --- |
| `COMPARABLE` | same mandatory feature ids, same expectations, same bands | these verdicts may be read beside each other |
| `INCOMPARABLE_CHECK_SETS` | the declared mandatory feature id sets differ | coverage is a ratio to a denominator each formulation chose, so 3-of-3 and 8-of-8 are both 1.0 and mean nothing against each other. The shared set is named, and so is what only one of them declared |
| `INCOMPARABLE_EXPECTATIONS` | same ids, different frozen expectation or band | each `PASS` is a pass against a value that formulation declared for itself |

The third is not hypothetical. On the recorded three-formulation knob, the root
declares `bbox_mm.z = 50.0` and `plate-seated` declares `52.0`, each is checked
against its own declaration to a band of `0.5`, and **both are `PASS`**. A report
that printed `envelope PASS` beside `envelope PASS` would tell a reader they are
equal on size. They are 2 mm apart by design, and that is the fork.

The comparand is the feature-id **set** from `model_contract.json`, and
deliberately never `coverage.fraction`: `covered` is not filtered to mandatory
features (`commission.py:437`) so the fraction is not bounded by 1.0, and a
fraction cannot say *which* check differs. Each formulation's own coverage is
reported inside its own block, under the name `self_coverage`.

The verdict scopes to the mandatory axis and not to the whole comparison. An
unusable rubric must not delete the evidence axis, which is computable however
badly two contracts disagree and is where a stale sibling is reported.

#### `preference.admissible`

False, with the reason named, when any of these holds:

* a formulation did not pass its own mandatory checks, or has no current verdict
  — 8.5, a preference criterion may not be weighed against a mandatory failure;
* the rubrics disagree, per the table above;
* a dimension this job *turns on* cannot be measured by this build at all.

The measurements are printed in full in every one of those cases. Withholding a
number somebody took would be its own dishonesty; what is withheld is the licence
to read it as a reason.

#### `not_compared` — the half that matters more

One row per dimension this job exercises and this build cannot measure, each
naming why and which release owns it. A comparison that silently omits the
dimension nobody can measure is worse than none: it leaves a reader concluding
two formulations are equivalent on an axis nothing looked at.

Rows carry a `standing`. `CONTEXT` is true of any two solids — geometric
difference between formulations (Release 6), print time and support toolpaths
(no slicer adapter, permanently absent rather than pending), and the
engineering-judgment dimensions that may only ever appear as a stated row
attributed to whoever stated it. `DECIDING` means this job turns on it, and a
`DECIDING` row that cannot be measured makes `preference.admissible` false.

Criteria a job does not exercise are **absent**, not zero and not "1 vs 1"
(6.14). A single-material one-piece pair emits no material-count, sequence,
assembly or tooling row at all; a pair with more than one body emits one, marked
`DECIDING`, owned by Release 8.

On a `MODIFY` pair, `not_compared` is the entire finding: both formulations
report `EXPERIMENTAL_UNAVAILABLE`, the axis that decides between them is
preservation, and preservation fails twice — see [`docs/defects.md` D22](defects.md)
and the undeclared sample density. The comparison says so and refuses preference.
That output is correct and complete, not a failure to compare.

#### The sentence it will not say

The shared requirements are bound as a *digest* (`cli._requirement_hash`) and
are never individually checked, and the contract's rows are geometric proxies a
designer chose. So `shared.requirement_digest` is reported as a **binding**:

> each formulation met the contract it froze, and all of them bind the same
> requirement digest

and never *"all of them meet the requirement"*. Where the digests differ, the
formulations were frozen against different states of the shared job, and the
report says that instead.

#### What it records about its own evidence

`comparison.json` is recomputable from disk at any moment, so there is nothing
to resume and nothing to invalidate. It records, per formulation, the whole
binding map, `bindings.identity` over it, the sha256 of every receipt it read,
and `bindings.broken` verbatim. The identity covers *inputs*, so a corrected
`commission_report.json` would move the comparison with no binding broken — which
is why the receipt digests are there too.

Two byte-identical siblings are grouped under `identical_designs` and named as
one design under several ids. On the recorded knob the root and `as-drawn` share
a source digest; without that block a reader takes their agreement for two
independent designs reaching the same answer, and it corroborates nothing.

Exit code is `0` whenever the report ran, and `2` for a project with fewer than
two formulations or an unknown `--against` name. A comparison is never *waiting*
for anything, so it never returns the needs-action code: a stale sibling is a
finding in the output, not a state to resolve here.

### The authored lane: two artifacts, one commission

A job whose plan names the `AUTHORED` builder -- every `CUSTOM` job, and any
other route for which no certified template covers the shape -- is produced by
one designer commission that returns **two** files.

`design_proposal.json` says what the part must measure. `model.py` says how it is
built. They are separate because the designer used to write one file that did
both, and a party that owns its own acceptance criteria can widen one after
seeing it missed: a model declaring a 24x18 pad, building a 10x8 one, with a
self-declared 500 mm2 band on that row, was commissioned `PASS` on a 352 mm2
miss.

`design_proposal.json`, validated by
[`pipeline/acceptance.py`](../skills/3d-modeling/scripts/pipeline/acceptance.py):

```json
{
  "schema_version": 1,
  "job_id": "riser-01",
  "design_id": "two-tier-riser",
  "rationale": "a 40x30 base carrying a 24x18 pad",
  "params": {"base_w": 40.0, "pad_w": 24.0},
  "bbox_mm": {"x": 40.0, "y": 30.0, "z": 14.0},
  "bodies": 1,
  "profile_marks": {"z": [6.0]},
  "features": [{"feature_id": "pad-section", "kind": "section_area",
                "at": {"z": 10.0}, "value_mm2": 432.0}]
}
```

`params` is the same dict `model.py` declares as `PARAMS`, and the run refuses
the pair when they disagree. `profile_marks` are the heights the shape
legitimately steps at: they explain a step, and they cannot clear the part.

`model.py`, loaded by
[`pipeline/authored.py`](../skills/3d-modeling/scripts/pipeline/authored.py)
after the freeze, under an OS-enforced confinement — see *The confined build boundary*
below:

```python
PARAMS     = {...}                             # the numbers the shape is built from
COMPONENTS = [...]                             # optional
INTERFACES = [...]                             # optional
PROVENANCE = {...}                             # optional

def build(): ...                               # or a module-level `part`
```

`EXPECTED`, `BBOX_MM`, `BODIES`, `PROFILE_MARKS`, `VOLUME_MM3` and any acceptance
tolerance are refused in `model.py`, and the loaded module has no field they
could be read back through.

Proposable `kind`s are `section_area`, `bed_contact`, `through_hole`,
`bore_by_displacement` and `void_region`. `overhang`, `preservation` and
`fit_acceptance` are not proposable: the support ceiling comes from the print
plan, the preservation row from the declared edit scope and the fit row from the
bounded external measurement. A row may not carry a `tolerance` — the band is
computed by the pipeline from the row's own magnitude. A proposal may not declare
`volume_mm3` at all; see `acceptance_contract.json` below.

**Every declaration must be derived from `params` by arithmetic that does not go
through the builder.** Writing `bbox_mm` by running the build and copying what
came out is a threshold authored by the party being measured, after measuring;
that is a receipt, not a gate.

The contract binds the module's path and hash under `source`, and the artifact
manifest records which kernel actually ran — as a token the child returns and the
parent looks up, never as a sentence the child composed. An authored mesh model's
`boolean_engine` is recorded as `unrecorded` — the certified backends select
manifold3d at every call site and can name it, and an authored model was not
observed doing so.

`PROVENANCE` is recorded in `candidate_declaration.json` and reaches no reviewer;
see *The confined build boundary* below.

There is no validity domain, because nobody has certified one. An authored model
never routes `DIRECT`.

### The confined build boundary

`model.py` runs **under an OS-enforced confinement**, not in the process that
freezes the contract and decides the status, and not as an ordinary peer process
either. Two things had to be true and only the first was:

* freezing before the builder runs. Necessary, and not sufficient: importing a
  module runs its module-level code, and from that code `status.decide`,
  `commission._tol`, `contract.area_tolerance` and
  `AcceptanceSource.expectations` were all one assignment away — demonstrated,
  not argued, as a `VERIFIED` receipt on a 352 mm2 miss;
* running the builder with *less authority*. A separate interpreter gave it a
  different namespace and the same rights. An adversarial review then rewrote a
  pipeline module the parent imports **after** the build returns and had the
  parent execute it; did the same through a `__pycache__` entry that left the
  `.py` byte-identical; and left a detached grandchild that rewrote
  `final_status.json` 25 s after the run reported `FAILED`.

[`pipeline/confine.py`](../skills/3d-modeling/scripts/pipeline/confine.py) builds
the confinement,
[`pipeline/isolation.py`](../skills/3d-modeling/scripts/pipeline/isolation.py) is
the parent half of the protocol, and
[`pipeline/build_child.py`](../skills/3d-modeling/scripts/pipeline/build_child.py)
is the child.

**There are two implementations, chosen by platform, and neither degrades.**
`confine.py` is the Windows one and dispatches to
[`pipeline/confine_posix.py`](../skills/3d-modeling/scripts/pipeline/confine_posix.py)
everywhere else. A platform with neither refuses to execute the candidate at
all; there is no unconfined path, and a boundary that quietly became an ordinary
subprocess would be worse than none because the receipts would not say which one
ran.

**The confinement**, on Windows, with no new dependency (`ctypes` against
`advapi32`/`kernel32`):

| mechanism | what it is | what it buys, measured |
|---|---|---|
| restricted token | `CreateRestrictedToken`, restricting SIDs without `Authenticated Users`, all groups but `Everyone`/`Users`/the logon SID deny-only | no write to the repository, `site-packages` or this package's source |
| low integrity | token integrity level `S-1-16-4096` | no write to the project directory, the parent's `%TEMP%`, the Startup folder or the sandbox's own inputs; no `OpenProcess(PROCESS_VM_WRITE)` on the parent |
| job object | `KILL_ON_JOB_CLOSE`, neither kind of breakaway permitted, UI restrictions, 8-process cap | nothing the candidate spawns survives, `DETACHED_PROCESS` and `CREATE_BREAKAWAY_FROM_JOB` included |
| child-process policy | `PROC_THREAD_ATTRIBUTE_CHILD_PROCESS_POLICY` / `PROCESS_CREATION_CHILD_PROCESS_RESTRICTED` | the candidate creates no process at all: `WinError 367` out of `CreateProcess`, before the job object has anything to catch |
| handle list | `PROC_THREAD_ATTRIBUTE_HANDLE_LIST` | exactly two handles inherited: a `NUL` and one pipe for the transcript |
| constructed environment | not `os.environ` | the candidate is not handed the project path, the user, or the machine's `PATH` |
| the confinement together | | a directory junction aimed straight at `FSCTL_SET_REPARSE_POINT` — no `cmd.exe`, no privilege, inside the one writable directory — comes back `ERROR_ACCESS_DENIED`, so the candidate cannot create a reparse point at all. `isolation._sweep` refuses to read a build directory holding one either way |

The restricted token does **not** deny sockets. This table said it did; the
evidence was a probe against a port a third-party firewall filters. The network
is open — [`docs/defects.md` D9](defects.md) row 1, and
`test_isolation.test_the_boundary_denies_outbound_tcp` is the expectation, kept
failing on purpose.

Every privilege is deleted except `SeChangeNotifyPrivilege`, which is
bypass-traverse-checking: `Everyone` holds it by default and it grants access to
no object.

**The confinement**, on Linux, also with no new dependency (`ctypes` against
`libc`). Every row is re-measured by
`benchmarks/heavy/test_confine_posix_heavy.py`, which runs a real confined child
and has it try the thing:

| mechanism | what it is | what it buys, measured |
|---|---|---|
| mount namespace | `MS_REC\|MS_PRIVATE` off the host's propagation, then `mount_setattr(AT_RECURSIVE, MOUNT_ATTR_RDONLY)` over `/`, then one read-write bind for the build directory | every write outside the build directory fails `EROFS` — the repository, `site-packages`, `/tmp`, `/etc`, `/root`. An allow-list of exactly one hole, so a mount nobody thought of is read-only because it is under `/` rather than because somebody remembered it |
| network namespace | created with no interfaces, loopback never brought up | `connect()` answers `ENETUNREACH` and DNS does not resolve. **The Windows boundary cannot say this** — see D11 |
| PID namespace | the boundary's supervisor is init | a grandchild that calls `setsid()` and sleeps is dead before the parent reads one output byte. There is no `CREATE_BREAKAWAY_FROM_JOB` to attempt: the namespace is a property of the process tree, not a handle |
| empty capability set | bounding set cleared first, then effective/permitted/inheritable, plus `SECBIT_NOROOT` and `PR_SET_NO_NEW_PRIVS` | `CapEff` is `0000000000000000`; `mount(MS_REMOUNT)` over `/` answers `EPERM`, so the candidate cannot unmake the read-only tree from inside. A candidate that reaches a new user namespace still cannot: inherited mounts are locked, and that is measured rather than assumed |
| seccomp-BPF | `EPERM` for `execve`/`execveat`, architecture-checked, installed by `build_child` immediately before the first candidate import | the candidate creates no process. Later than the other three by one function call, because the parent's last act is itself an `execve` — the honest statement is that it covers candidate code rather than the whole child process |

The identity is **not** dropped, and that is deliberate: a `MODIFY` job's model
legitimately reads the supplied artifact out of the project directory the parent
owns. Becoming another user does not confine that read — the read-only mount
already did — it only breaks it. Authority goes; identity stays; the same shape
the Windows child has under a restricted token.

The evidence that this is not the weaker boundary is not any single row: the L1
replay suite produces **byte-identical goldens** through it, 57 passed and 43
subtests against recordings frozen on Windows. A boundary that leaked would not
reproduce a digest.

**The workspace.** Two directories under a fresh sandbox, both with a protected
DACL that inherits nothing:

| directory | who can write it | what is in it |
|---|---|---|
| `in\` | nobody — read and execute only, at the implicit Medium label a Low subject cannot write | *copies* of `model.py` and every `*.py` beside it, plus `build_input.json` |
| `out\` | the child, and only the child's directory | `candidate.stl`, `build_manifest.json`, a `home\` for anything that wants `%TEMP%` or `Path.home()` |

What crosses, and nothing else:

| direction | contents |
|---|---|
| in | the sandbox input directory, the model's *file name* within it, the build directory, the two output file names, whether a STEP is wanted |
| out | `build_manifest.json` — `PARAMS`, `PROVENANCE`, a *kernel token*, the build duration — plus `candidate.stl` and optionally `candidate.step` |

JSON and files. Never a pickle, never a shared Python object, never a callable.
Nothing about acceptance goes in, and neither does the project's path.

**No string the candidate wrote comes out.** The manifest is written by a process
the candidate's own module-level code runs in, so every field of it is
candidate-authored whatever `build_child` intends — and four of those fields used
to be copied onto `model_contract.json` and `artifact_manifest.json`, both of
which the safety and verification packets embed whole. The reviewer's PASS
decides the run, so that was a candidate writing to its own grader
([`docs/defects.md` D10](defects.md), closed). Now:

* the kernel crosses as a **token**, matched against `isolation.KERNELS`. Every
  engine word on a receipt is the parent's, the version comes from the parent's
  own `importlib.metadata`, and a token the table does not hold selects
  `unrecorded` rather than being passed through;
* `PARAMS` and `PROVENANCE` cross into an `isolation.CandidateDeclaration`.
  `PARAMS` is compared against the frozen proposal and forwarded to nothing;
  `PROVENANCE` is written to `candidate_declaration.json` and read by nothing.
  Neither `Contract`, `artifact_manifest.json`, the safety packet nor the
  verification packet has a field or a parameter one could arrive through.

Four consequences a designer will notice:

* **`PARAMS` and `PROVENANCE` must be JSON.** They cross a process boundary as a
  document. A parameter the parent cannot read is a parameter the frozen proposal
  cannot be compared against.
* **A helper module beside `model.py` still resolves** — every `*.py` in the
  project directory is copied into the sandbox and that directory is on
  `sys.path`. A helper in a *subdirectory* is not, and neither is anything the
  model expects to find by walking up from `__file__`. Third-party packages
  resolve because `PYTHONPATH` names the environment's `site-packages`,
  read-only. The child is the *base* interpreter rather than the environment's
  `python.exe`, which is a launcher that would itself have to spawn a child.
* **The model cannot write anywhere except its own build directory** — not the
  project, not the repository, not the virtual environment, not its own source.
  A model that tries gets `PermissionError` from the operating system and the run
  is refused with that message.
* **A model cannot spawn anything.** Not "is refused for having": the kernel
  refuses `CreateProcess` itself, with `WinError 367`. Nothing on this path needs
  a subprocess, and a build that starts one has started something the run cannot
  account for. The job object still bounds whatever would exist if this ever
  failed.

`model_contract.json`'s `source` block now carries `sources_sha256`, a digest
per staged file, beside the single `module_sha256` it always had: a part built
from two files whose contract names one of them names less than what ran.

The parent hashes `model.py` and every staged input **before the child exists**,
waits for the job object to report no live processes before it reads a byte, and
then validates each output by exact name, rejects reparse points, alternate data
streams and paths that resolve out of the sandbox, and hashes what it promotes.
Source-integrity hashing is not the gate — the bytecode-cache attack left the
source byte-identical — and the one integrity check kept is a narrow canary over
`acceptance_contract.json`.

**Named limitations**, measured rather than assumed and asserted still open by
`test_isolation.WhatTheConfinementEnforcesTest`: see
[`docs/defects.md` D9](defects.md).

`DIRECT` executes no candidate code and does not come here at all: `runner.py`
imports neither module, the route's dispatch count and runtime are unchanged, and
`confine.run` raises a `pipeline.confine.spawn` audit event that a `DIRECT` run
is asserted never to trigger.

### `acceptance_contract.json` (the `AUTHORED` builder)

Generated by `design-tool run` from the frozen proposal and the system-owned
inputs, and written to disk **before `model.py` is imported**. It carries the
proposal hash, the user requirement hash, the source artifact hashes, the
system-owned tolerances, the print-plan constraints, the required feature checks,
the route-specific gates, the expected artifact identities, and its own revision
number and hash. Every receipt binds that hash.

The ordering is what makes one-agent `CUSTOM` safe, and it is structural rather
than checked: `acceptance.generate` takes a proposal, a project and a plan and
has no parameter a mesh could arrive through, `acceptance.py` imports no analysis
module and no backend, and `runner.py` — the module that runs the builder —
contains no function that writes an acceptance contract.

A run that regenerates the same contract leaves the file byte-identical. A run
that generates a different one cuts a **new revision**: it records in
`acceptance_history.json` which fields moved and what the superseded revision had
claimed, and deletes the receipts issued against it — the artifact manifest, the
commissioning report, the manufacturing report, both review reports and the final
status. A designer may still change their mind about what the part should be.
They cannot do it invisibly, and they cannot keep the receipt issued against the
old expectation.

The contract is frozen into the **work directory**, which is the project root for
an unbranched job and `alternatives/<id>` once one is active. That scoping is
what makes the deletion above correct across siblings; see `design-tool branch`.

Editing `model.py` does **not** move the contract. Iterating a build against a
fixed expectation is the point.

`expected_volume_basis` names where an expected solid volume came from, and is
`NOT_INDEPENDENTLY_SPECIFIED` for novel authored geometry. The measured volume
still appears on the receipt; what it may not do is clear an anomaly detector by
comparing against itself. On the authored lanes the volume and profile detectors
therefore report `NOT_APPLICABLE` rather than `CLEAR`, and still report `ANOMALY`
when a step the proposal does not explain shows up.

### `print_plan_checks.json` (the `AUTHORED` builder)

Generated by `design-tool run` from the printer, the nozzle and the project's
declared `envelope_mm`, **before** the designer commission is written, and
validated before it is bound. Its `SELF_SUPPORT_REQUIRED` rule becomes an
`overhang` contract feature, so the support ceiling is measured by the same gate
as everything else and cannot have been set after reading the candidate. Its
`owner` is `builtin-direct-template`: nobody engineered this part, and naming the
source is what keeps that visible.

`envelope_mm` is therefore required whenever the geometry is authored. It is a design-driving
value like any other — stated by the brief or chosen by design — and `run`
refuses with exit 2 rather than guessing it.

## `design-tool diagnose` — what a supplied artifact actually is

```bash
uv run design-tool diagnose <artifact.step|.stl|.obj|.3mf> [--out report.json]
```

Measures a supplied file and classifies what can be built on it. **It never
writes to the artifact** — not a repair, not a normalization, not a re-export.
The supplied file is frequently the only authoritative copy, and a diagnosis that
silently fixed what it found would destroy the evidence that it needed fixing.

| classification | meaning |
| --- | --- |
| `USABLE_EXACT` | an exact B-rep with solids; boolean edits are exact |
| `USABLE_MESH` | a closed, consistent mesh; edits are mesh operations |
| `REPAIR_REQUIRED` | loadable, but not sound enough to build on as it is |
| `RECONSTRUCTION_REQUIRED` | nothing here can be built on (exit 1) |

Reported per format: body/component count, bbox, watertightness and winding for
meshes, faces with no usable area for B-reps, **faces no mesher can triangulate**
for B-reps (`untessellatable_faces`, with each one named by index, surface type
and centre under `tessellation`, at the deflection the probe used — area is not
tessellability, and a STEP whose every face has a positive area can still be a
file nothing downstream can turn into a mesh), degenerate faces, boundary edges
(**read that field with [`docs/defects.md`](defects.md) D1 in hand: it currently
counts every edge that is not shared by exactly two faces, so a non-manifold edge
is reported as a boundary edge and a repairer is pointed at hole-filling that
cannot work**), and the 3MF scene — objects, components, build items with their transforms, and
materials — rather than one merged solid, because that structure *is* the
functional information in a multi-part or multi-colour job.

### The 3MF scene, and the geometry in it

A 3MF is reported at both levels. The scene keeps its shape: `objects` (each with
its part, its components and its own mesh facts), `build_items`, `materials`, the
declared `unit`, and `root_part` / `model_parts` naming what was actually read.
Alongside it, every object is measured with the same questions the STL branch
asks — `bbox_mm`, `watertight`, `winding_consistent`, `triangles`,
`boundary_edges`, `bodies` and `volume_mm3` — so a 3MF diagnosis can answer the
questions its classification rests on. A 3MF mesh is indexed rather than a
triangle soup, so nothing is merged on the way in; merging would change the
author's topology and hide a genuinely split seam.

**The production extension is followed.** Bambu Studio, OrcaSlicer and
PrusaSlicer keep the scene in `3D/3dmodel.model` and every mesh in its own
`3D/Objects/object_NN.model`, reached through a `p:path` on the component. The
root part is the one the package relationship names, not whichever `.model` the
zip happens to list first, and an object id counts as dangling only when it
resolves in neither the referencing part nor the part its `p:path` names. Reading
one part and resolving ids against it alone reported intact, watertight,
winding-consistent files as `REPAIR_REQUIRED` for components that were never
broken.

`placed` reports each mesh instance with its build-item and component transforms
applied, and the top-level `bbox_mm` is the assembled scene (`bbox_note` says
which frame it is in). The transform is not decoration: a build item carrying a
`1.07` scale makes its part 7% larger than the numbers in its mesh part, and a
reader that skips it measures every scaled part undersize.

**A component chain that does not terminate is a finding.** Two objects whose
components refer to each other resolve cleanly, dangle nothing and parse — and
the scene they describe cannot be assembled. Cycles are searched over the whole
object graph rather than along the placement walk, for the same reason dangling
ids are: an unreferenced object whose components loop is still a broken file. A
chain more than 32 deep is reported separately, because it is a different
malformation. Either finding costs a file its `USABLE_MESH` — geometry inside a
loop that is watertight and consistently wound is still `REPAIR_REQUIRED`, and a
scene with no reachable mesh at all remains `RECONSTRUCTION_REQUIRED`.

Units are answered as honestly as the format allows. STL carries none, so the
bbox is reported as authored with a *suspicion* beside it (`/25.4` and `x1000`
arithmetic shown) and nothing is converted. 3MF and STEP carry them and they are
read. A mesh is reported twice — as parsed and after merging coincident vertices
— because an STL is a triangle soup and an unmerged read calls every sound part
`REPAIR_REQUIRED`.

## Modification: the edit scope and the preservation audit

A `MODIFY` project declares `edit_scopes` before the edit — one entry per
artifact it modifies, each naming the artifact, the named region, **a
`region_box`**, what must be preserved, what may be removed, what is being
added, the expected body delta, and whether a mesh fallback is allowed. A name
alone cannot be compared against, so the box is what the audit measures; the
name is what a person argues with.

A job that modifies two artifacts at once — a case body and its drawer, with
magnet pockets that have to line up — declares two scopes, and both name the
same `Interface` in their `interface_ids`. That interface is the datum the two
edits have to agree on; nothing else declares an alignment, and `alignment_transform`
on each scope is what places that artifact's coordinates in the job's frame. Two
scopes over one artifact are refused, and every scope is owed its own
preservation row: `execution_plan.json` names the artifacts in
`preserved_artifact_ids` and the runner refuses a contract that carries fewer
rows than that.

Every field of the scope reaches the frozen acceptance contract's preservation
row, so every one of them reaches `contract_sha256` and therefore the review envelope:
changing what the edit promised refuses the answer written against the previous
promise. `alignment_transform` additionally reaches `preservation._seed_material`,
because it is the one field that says which geometry the sampling plan is a plan
of. It is bound there and **not applied** to the meshes — applying it would assert
that the candidate's builder applied the same matrix, which nothing here checks.
A changed transform invalidates the evidence; it does not make the audit
frame-aware.

The audit itself is not there yet for that job. `preservation.audit` compares one
source against one candidate in both directions, and the second direction samples
the whole candidate — so where the candidate carries a second edited artifact, that
artifact's surface reads as movement against the first artifact's source. The
coordinated multi-artifact edit is declarable, validated and planned; measuring it
needs a per-artifact candidate, which this build does not produce. The row says so
in its own note.

[`pipeline/preservation.py`](../skills/3d-modeling/scripts/pipeline/preservation.py)
compares everything outside that box, bidirectionally — sampling only the source
misses material the edit added outside the region, and sampling only the
candidate misses material it removed. It reaches the commissioning verdict as a
`preservation` contract feature, not as a separate report, so a job can actually
fail for it.

| verdict | meaning |
| --- | --- |
| `PRESERVED_EXACTLY` | only when the caller declares both sides exact B-rep exports from one kernel |
| `PRESERVED_WITHIN_TOLERANCE` | no sampled point outside the region moved more than the declared band |
| `CHANGED` | something outside the declared region moved, with the worst point |
| `UNMEASURABLE` | no region box, or the region covers the whole part — escalates, never passes |

**The claim never outruns the method.** A sampled mesh comparison cannot
establish exact preservation, so it does not say it did; the report carries the
method, the sample count and the tolerance it was measured at.

**The sample plan is a function of the pair, not of a draw.** The plan is derived
from the source and candidate hashes, the declared region, the band and the
count, and laid along a low-discrepancy sequence over meshes whose vertex and
face order has been canonicalised first. Identical inputs produce byte-identical
evidence, and the plan's digest and the audit's own digest are bound into the
review envelope — which is what lets a reviewer's answer survive a rerun. It did
not before: the audit drew from the process-wide generator, so the second run
measured a different part than the one that had been answered, the envelope
mismatched, and no `MODIFY` job with an edit scope could finish a review round
trip at all.

That is reproducibility, and it is not sensitivity. The density is still a fixed
count rather than one derived from a declared minimum detectable defect size, so
a small undeclared addition outside the edit region can still be missed — now
identically on every run. A real modification job sized the target: the whole
defect its audit had to find was 85 faces of a 93,530-face part. Deriving the
density, comparing B-reps properly and renaming the verdict to
`PRESERVED_WITHIN_SAMPLED_TOLERANCE` are stage 5 of
[ADR 0002](adr/0002-route-and-contract-authority.md), and the `MODIFY` lane stays
capped until they land.

The other half of the same cap is that there is one verdict for one box. A job
whose edit deliberately consumes material — a magnet pocket, or a band where two
parts now interpenetrate — has geometry that must not move, geometry permitted to
change, and geometry whose disappearance is the requested result, and one band
over one region cannot say which is which. The same job's unfiltered global
maximum was 1.797 mm and all of it was requested. Per-region dispositions are
Release 6 in [`ROADMAP.md`](../ROADMAP.md); until they land, an edit of that shape
is declarable and not judgeable.

The support ceiling is inherited on a `MODIFY` job: a generated zero fails a
supplied part for overhangs that were in the file before anybody touched it, and
the designer cannot chamfer them away without redrawing the part. The ceiling is
therefore the source artifact's own measurement — taken from a file fixed before
the job started, so it is not a threshold tuned to the candidate — and any
overhang the edit *adds* still fails.

### `route_decision.json`

The route, the deciding condition, the source mode, the escalation triggers that
turned an independent verification on, **and every route that was not taken with
the reason**. Routing used to leave no trace, so it could be neither audited nor
regression-tested.

### `execution_plan.json`

What will actually be executed under that decision, compiled from it by
[`pipeline/execution.py`](../skills/3d-modeling/scripts/pipeline/execution.py) in
the same invocation: the route, the **builder** (`CERTIFIED_TEMPLATE` or
`AUTHORED`) **and why that builder**, the reviews the job owes, whether an
independent verification is `NEVER`, `OPTIONAL` or `REQUIRED`, whether the job
must prove it preserved everything outside its declared edit region, and whether
the lane may claim success at all. Nobody writes this file by hand and no command
exists to produce it on its own — `design-tool run` is still one command for a
whole job.

A declared `model` is the builder on every route. Preferring a matched certified
template over it emitted a plan that contradicted itself — `builder:
CERTIFIED_TEMPLATE, model: model.py` — and then built the template, so a job
declaring both reached `VERIFIED` without the designer's file being named on any
receipt. `builder_rationale` says which declaration won and which was set aside.

`preserved_artifact_ids` is set by the **edit scopes**, not by the source mode,
and the runner refuses a contract carrying fewer preservation rows than there are
artifacts named there. Keyed on `source_mode == "MODIFY"` instead, a project that
declared an edit scope over a supplied artifact and wrote `RECONSTRUCT` beside it
built a certified template, never opened the artifact, and finished `VERIFIED`.
The ids rather than a flag: with two scopes, "the contract carries a preservation
row" stops being the same statement as "every declared scope is measured".

`OPTIONAL` is compiled only for `FITTED` and `FULL`, and `design-tool run`
supplies a verifier for it. It used to be compiled exactly when no verifier would
be supplied, so only `run-job` — which hands the runner every callable
unconditionally — could act on it, and one `job.json` finished `VERIFIED` through
the deprecated entry point and `NEEDS_MORE_EVIDENCE` through the supported one.
`DIRECT` and `CUSTOM` reach `NEVER`: `DIRECT` trades the look away, and `CUSTOM`
is one designer commission that must not grow a second round trip by side effect.

The runner consumes it verbatim and decides no route of its own. It used to keep
a second copy of the answer, re-derived from `intent.select`, and every guard
downstream read that one: a `RECONSTRUCT` job whose parameters happened to sit
inside a certified domain routed `FITTED`, executed as `DIRECT` with neither the
metrologist nor the verifier it owed, and wrote `"route": "DIRECT"` on its own
receipt.

Route and builder are separate axes and are recorded separately. A certified
template used by a `FITTED` job makes the build cheap; it does not make the
evidence obligation smaller, and the job stays `FITTED`.

`final_status.json` carries the plan's route, `execution_plan_sha256` and
`lane_status`, so a receipt can be checked against the plan that produced it.

## `design-tool run-job` — the deprecated predecessor

Reads `job.json` directly, skipping the canonical project. Kept so existing job
directories keep working; `design-tool run` is the supported entry point and
adapts a bare `job.json` on first use. One invocation runs contract, build,
commission, screening, witness and status; every extra invocation would pay
interpreter startup to do work measured in milliseconds.

**Do not run it in a directory that holds a `project.json`.** It does not look
for one, so a project declaring edit scopes gets a scope-free run with no
preservation obligation, and the `final_status.json` that run leaves behind is
what `design-tool status` then reports as the project's status. See
[`docs/defects.md`](defects.md) D4.

```bash
uv run design-tool run-job job_dir/ [--no-render]
```

`job_dir/job.json` describes the job:

| field | meaning |
| --- | --- |
| `job_id` | names the job in every artifact it writes |
| `template` | a certified template name; omit to let routing decide |
| `parameters` | the template's parameters, in mm |
| `consequence` | `INCONSEQUENTIAL` or `CONSEQUENTIAL` — there is no third level |
| `printer` | **required** printer profile name; the pipeline never invents the machine |
| `material` | **required** object naming non-empty `process` and `material` strings |
| `nozzle` | **required** object with positive numeric `diameter_mm` |
| `orientation` | **required** object with `model_to_printer_matrix` (`identity` or a 4×4 numeric matrix) and numeric `bed_z_mm` |
| `stated` | which parameters the user actually gave, as opposed to chosen for them |
| `updated_utc` | timestamp carried into the contract |
| `reviewer` | who answers the reviews, by their own account — including `fresh_context`, which nothing here can verify and so is never assumed |
| `modifiers`, `step`, `evidence`, `interface_map`, `cache_dir` | optional; see `runner.JobRequest` |

The manufacturing fields are part of the immutable `model_contract.json`, not
informal print notes. A minimal complete job has all four:

```json
{
  "job_id": "clip-01",
  "template": "c_clip",
  "consequence": "INCONSEQUENTIAL",
  "printer": "Bambu Lab X2D",
  "material": {"process": "FDM", "material": "PETG"},
  "nozzle": {"diameter_mm": 0.4},
  "orientation": {"model_to_printer_matrix": "identity", "bed_z_mm": 0.0},
  "parameters": {"bore_d": 12.0, "wall": 3.0, "height": 9.0, "mouth_gap": 9.0,
                 "flange_w": 40.0, "flange_d": 22.0, "flange_t": 5.0, "screw_d": 4.8},
  "stated": ["bore_d", "flange_w"],
  "updated_utc": "<iso8601>"
}
```

Exit codes, which extend the table above:

| Code | Meaning |
| --- | --- |
| 0 | The job finished and `final_status.json` records a status the run earned. |
| 1 | The job stopped at a named stage, or finished at a status short of passing. The receipt says which and why. |
| 3 | The job needs a review before it can finish. See below. |

### Answering a review

A certified `INCONSEQUENTIAL` `DIRECT` job has no review callback. A certified
`CONSEQUENTIAL` `DIRECT` job has exactly one bounded safety review and no normal
geometric verifier. `FITTED` requires one bounded specification review; an independent
verification review may follow when the caller supplies it and the screen is clear.
`FULL` requires both the specification review and independent verification. These are
judgements about a part; a deterministic program that returned one would be inventing
it. So the CLI writes the evidence and stops:

```
design-tool: this job needs a safety review before it can finish.
  the evidence is written to  reviews/safety_packet.json
  write the answer to         reviews/safety_response.json
  then run the same command again.
```

Write the response file and re-run the same command. Responses are validated
against the same schema an in-process caller is held to — a malformed one is a
`SchemaError`, not a shrug. The safety packet deliberately omits
`verification_report.json`: a second opinion that read the first one is not a
second opinion.

### What it writes

`model_contract.json`, `intent_manifest.json`, `candidate.stl` (and
`candidate.step` when the contract asks), `commission_report.json`,
`manufacturing_report.json`, `witness/`, `artifact_manifest.json`,
`timings.json`, `cost.json`, and `final_status.json`. On the `AUTHORED` builder,
`acceptance_contract.json` and `acceptance_history.json` as well.

`timings.json` and `cost.json` are the two files a rerun on unchanged inputs is
allowed to move, and neither is hashed into anything: durations are not part of
any artifact's identity, and what a job *spent* is not part of what it
*concluded*.

**Read `final_status.json`, and read `allowed_claim` before repeating anything
about the part.** `COMMISSIONED` is not `VERIFIED`, and neither one is "safe".
`EXPERIMENTAL_UNAVAILABLE` and `UNSUPPORTED` are none of them: the work ran and
the receipts are on disk, and the lane is not allowed to certify its own result.
The two are different — a named stage of ADR 0002 lifts the first and nothing
lifts the second, so a reader who cannot tell them apart either waits forever or
gives up too early. `lane_status` and the `reasons` list say which lane and why.

**A refused part and an instrument that never measured are different sentences.**
`unavailable_checks` lists every declared check that could not run, with its
`error_code` and the reason, and `allowed_claim` names them in words too — so
"the audit could not read your primary source" cannot be read as "a reviewer
rejected your part". Only one of those is anything the user did.

## `design-tool selftest` — does this installation build what it certifies?

The smoke set that ships inside the distributed bundle. An installed skill has
the code and none of the repository's tests, so before this existed the
strongest thing an agent could say about an installation was "it imported".

```bash
uv run design-tool selftest [--quick] [--json]
```

It checks the core toolchain, then compares every certified template's contract
against the hashes frozen in
[`pipeline/selftest.py`](../skills/3d-modeling/scripts/pipeline/selftest.py),
then builds each one through the real backends and commissions the exported
mesh. `--quick` stops after the contracts, so it runs on any interpreter and
builds no geometry.

The frozen hashes are derived from declared parameters, expectations and the
envelope — never from a mesh — so they hold across trimesh, manifold3d and
build123d versions. A mismatch means a certified contract *moved*, which is an
architecture decision rather than a dependency bump. Exit 1 names every check
that failed and why.

## `python -m pipeline.corpus` — the screening corpus measurement

Builds every certified template, mutates each one, and reports what broad
screening caught. Exits non-zero when the measured gate fails.

```bash
uv run python -m pipeline.corpus
```

The fields worth reading: `gate`, `screening_false_negative_rate` (scored on
defects *fused* to the part, since a disconnected one is caught free by the
component detector), `false_positive_rate` with its `clean_parts_checked`
denominator, and `survivors_of_everything`.


## `team_preflight.py`

Script: [`skills/3d-modeling/scripts/team_preflight.py`](../skills/3d-modeling/scripts/team_preflight.py)

Runs deterministic non-acceptance gates for the team pipeline. It emits sorted,
indented JSON to stdout unless `--output` is provided. All subcommands return
`0` when the emitted JSON has `"result": "PASS"`, `1` when it has
`"result": "FAIL"`, and `2` for usage, unreadable files, malformed JSON, or
schema errors raised before a gate result can be written.

### support, actual command `support-audit`

```bash
uv run python skills/3d-modeling/scripts/team_preflight.py support-audit \
  --stl candidate.stl \
  --plan print_plan_checks.json \
  --rule-id support-rule-id \
  [--output support_audit.json]
```

Inputs:

* `--stl`, exported STL to re-import and screen.
* `--plan`, `print_plan_checks.json` containing `support_rules`.
* `--rule-id`, support rule id inside the plan.
* `--output`, optional JSON output path. Without it, JSON goes to stdout.

Outputs:

* JSON kind `downward-facing-surface-screen`.
* STL hash, plan hash, transform hash, bed contact area, out-of-limit face
  count, out-of-limit area, configured maximum area, and `PASS` or `FAIL`.

Exit codes:

* `0`, out-of-limit area is within the rule limit.
* `1`, out-of-limit area exceeds the rule limit.
* `2`, missing rule, malformed rigid transform, missing file, bad JSON, or bad
  numeric input.

### interfaces, actual command `validate-interfaces`

```bash
uv run python skills/3d-modeling/scripts/team_preflight.py validate-interfaces \
  --plan print_plan_checks.json \
  [--output interface_validation.json]
```

Inputs:

* `--plan`, `print_plan_checks.json` with an optional `interfaces` array.
* `--output`, optional JSON output path.

Outputs:

* JSON kind `interfaces-validation`.
* Sorted `interface_ids`, collected error strings, and `PASS` or `FAIL`.

Exit codes:

* `0`, `interfaces` is absent, null, or fully valid.
* `1`, an interface row is malformed, has a duplicate id, uses an unknown
  `fit_type`, declares an invalid range, or misses required acceptance fields.
* `2`, the plan cannot be read or parsed.

## `python -m team_tools.contracts`

Module: [`skills/3d-modeling/scripts/team_tools/contracts.py`](../skills/3d-modeling/scripts/team_tools/contracts.py)

This package validates the v4 team contracts: the four Markdown ones through their
frontmatter (identity, revision, binding hashes), and the JSON ones structurally.
Passing it proves contract structure, identifiers, declared hashes, and revision
bindings only. It doesn't prove geometric or manufacturing correctness.
`job_state.md` is a closed header: `consequence` is required, legacy `risk_class` is
rejected, and unknown frontmatter fields are errors rather than ignored warnings.

### `validate`

```bash
cd skills/3d-modeling/scripts
uv run python -m team_tools.contracts validate path/to/project [--require CONTRACT] [--output receipt.json] [--timestamp ISO-8601]
```

Inputs:

* Project directory containing the contracts. Each is looked up as Markdown
  first (`dimensions.md`), then a JSON mirror (`dimensions.json`) if one
  exists; `artifact_manifest.json` is JSON-only. A directory that does not
  exist is a filesystem error (exit `2`), never a project whose contracts all
  happen to be missing.
* Optional `--require`, naming contracts whose absence is an **error** rather
  than a warning: `job_state`, `dimensions`, `print_plan`,
  `verification_report`, `artifact_manifest`, or `all`. Repeatable and
  comma-separated, from `job_state`, `dimensions`, `print_plan`,
  `verification_report`, `artifact_manifest`, `candidate_readiness`,
  `final_print_prep`, `final_prep_review`, or `all`. An unknown name is a usage
  error (exit `2`) rather than a silently dropped requirement.
* Optional `--output` receipt path.
* Optional `--timestamp`, injected into the receipt instead of reading wall
  clock time.

Outputs:

* Canonical JSON receipt with tool version, schema version, job id, required
  contracts, validated paths, observed revisions, computed SHA-256 values,
  per-contract results, warning ids, error ids, issues, timestamp, invocation,
  and disclaimer.

Exit codes:

* `0`, `results.overall` is `PASS`.
* `1`, one or more contract results failed.
* `2`, a contract loader or filesystem error prevented validation, including a
  missing project directory or an unknown `--require` name.

Absence is silent by default, on purpose: mid-pipeline a project legitimately
holds only the contracts its phase has produced, so a blanket error would make
`validate` unusable before Phase 4 — and a warning on every correct run trains
its reader to skim the channel that also carries `POSSIBLE_UNIT_SCALE_MISMATCH`.
So **a bare `validate` on a project holding no contracts at all exits `0`**. The
exit code alone proves that nothing which was read was rejected; it does not
prove anything was read. `validated_paths` records exactly what was.

Anything gating on this command must therefore say what it expects, either by
passing `--require` (absence becomes `REQUIRED_CONTRACT_MISSING`, an error, and
the run exits `1`) or by asserting that the contracts it needs appear in the
receipt's `validated_paths`. Prefer `--require`: it lands in the receipt's
`required_contracts` field, so a reviewer can tell a deliberately narrow
validate from one that gated on nothing.

### `hash` and `status`

```bash
cd skills/3d-modeling/scripts
uv run python -m team_tools.contracts hash path/to/project
uv run python -m team_tools.contracts status path/to/project
```

Both take a project directory and print to stdout by default. `hash` takes
`--output` and `--timestamp`; `status` takes `--output` and `--json`.

| Command | What it proves | Exits `1` when |
| --- | --- | --- |
| `hash` | Contract and artifact SHA-256 values recomputed from the bytes on disk, never trusting a hash written into a contract. | A declared artifact hash differs from the bytes on disk. |
| `status` | Each contract's revision, plus the downstream bindings that later revisions have made stale. | A row is `STALE`, `INVALIDATED`, or `UNREADABLE`. |

## `dt.py` — the toolkit launcher

Module: [`skills/3d-modeling/scripts/designer_toolkit/__main__.py`](../skills/3d-modeling/scripts/designer_toolkit/__main__.py)

Invoke it by absolute path from your project directory. It puts its own directory
on `sys.path`, so command-line paths resolve against your working directory rather
than the skill's, and neither a `cd` nor a `PYTHONPATH` is needed. The module form
(`python -m designer_toolkit ...`) still works but requires the working directory to
be `skills/3d-modeling/scripts/`, which is what made every measured designer run
write a shim instead. Every subcommand
prints indented JSON to stdout. The CLI doesn't catch toolkit exceptions, so
success returns `0`, argparse usage errors return `2`, and runtime errors
normally return `1` with a Python traceback.

### `commission`

```bash
uv run python <skill>/scripts/dt.py commission (--model model.py | --stl body.stl) --plan plan.json   --out DIR --job-id JOB --updated-utc ISO8601 [--reference ref.stl] [--no-render] [--no-receipts]
```

Inputs: a model module defining `part`/`build()` or an already-exported STL; the
bound `print_plan_checks.json`; an output directory; an injected timestamp.

Outputs: `commission.json` with every deterministic verdict and the next action for
each failure, plus `artifact_manifest.json` and `candidate_readiness.md` derived from
the same measurements. Exit `0` when every check passed, `1` when any failed, so a
failing candidate cannot be handed on.

This subsumes the former `measure`, `overhang`, `datums`, `interference`, `sweep`,
`export` and `finalize` subcommands, which are gone. Each was a separate process
paying interpreter and CAD-library startup, re-parsing the same STL, and costing an
agent round trip repeated after every edit — and offering the pieces individually is
what led three measured runs to assemble a hand-written verification script instead
of running the gate. The library functions remain importable for the rare direct use.

### `coupon`

```bash
uv run python <skill>/scripts/dt.py coupon --plan plan.json --out coupon.stl
uv run python <skill>/scripts/dt.py doctor
uv run python <skill>/scripts/dt.py plan template --bbox X Y Z --out print_plan_checks.json
uv run python <skill>/scripts/dt.py plan check print_plan_checks.json
```

Inputs to `coupon`: plan JSON, either a JSON object with `interfaces` or a raw
interface list, and a required `--out`. `doctor` and `plan` take neither.

Outputs: JSON object with written `stl` path and `legend` rows. The command also
writes the coupon STL.

## `preview.py`

Script: [`skills/3d-modeling/scripts/preview.py`](../skills/3d-modeling/scripts/preview.py)

```bash
uv run python skills/3d-modeling/scripts/preview.py model.stl [output.png] \
  [--views iso|multi] [--title "Title"] [--subtitle "Text"] \
  [--resolution 600] [--strict]
```

Inputs:

* STL path.
* Optional output PNG path. Default is `<stl_name>_preview.png`.
* `--views iso` for one isometric image or `--views multi` for an eight-view sheet
  (all four sides square-on plus two isometrics, top and bottom).
* Optional title, subtitle, and per-view resolution.
* `--strict` to fail before rendering if the normalized mesh is not watertight.

Outputs:

* Text summary with model path, bounding box, triangle count, watertight warning
  if present, and final preview path.
* PNG preview image.

Exit codes: the convention above, with `--strict` rejecting a non-watertight
mesh as a `2` rather than a `1`.

## `mesh_io` library

Library: [`skills/3d-modeling/scripts/mesh_io.py`](../skills/3d-modeling/scripts/mesh_io.py)

`mesh_io` is not a CLI. Import it from Python code that needs mesh loading
without the heavier preview rendering stack.

```python
from mesh_io import load_mesh, load_mesh_raw, load_mesh_report
```

Inputs:

* A mesh file path accepted by `trimesh.load`, normally STL for this pipeline.

Outputs:

* `load_mesh_raw(path)`: raw, unrepaired `trimesh.Trimesh` plus
  `MeshIntegrity` metrics.
* `load_mesh(path)`: normalized mesh for rendering and modeling use.
* `load_mesh_report(path)`: raw mesh, raw integrity, normalized mesh, mutation
  log, and normalized geometry hash.

Failure behavior:

* The library raises `ValueError` for unparseable files, empty geometry,
  zero-face meshes, or non-finite coordinates. Callers decide their own exit
  code.

## `make_3mf.py`

Script: [`skills/3d-modeling/scripts/make_3mf.py`](../skills/3d-modeling/scripts/make_3mf.py)

```bash
uv run python skills/3d-modeling/scripts/make_3mf.py out.3mf \
  "KnobBody (black)=body.stl" "Pattern (white)=pattern.stl"
```

Inputs:

* Output 3MF path.
* One or more part specs in `name=path/to/part.stl` form. Part meshes must
  already share the same coordinate system.

Outputs:

* Core-spec 3MF with one build object containing one component per input part.
* Stdout lines for each part with vertex count, triangle count, watertightness,
  and final file size.
* Best-effort round-trip reload summary. A skipped round-trip check is reported
  but doesn't fail the already-written file.

Exit codes:

* `0`, 3MF was written.
* `1`, usage is invalid, an STL cannot be loaded, or another uncaught runtime
  error occurs. Non-watertight inputs print warnings but do not fail by
  themselves.

Two open defects apply to anything this writes. Vertices are formatted `%.6g`,
so a written coordinate is not the coordinate that was measured, and the
round-trip reload has never executed in the frozen runtime — it needs `lxml`,
which is not there, and the skip is reported on stdout rather than in the exit
code. See [`docs/defects.md`](defects.md) D2 and D3. This is a draft-packaging
script, not the production writer ADR 0001 named; that verb does not exist yet.

## `make_bambu_3mf.py`

Script: [`skills/3d-modeling/scripts/make_bambu_3mf.py`](../skills/3d-modeling/scripts/make_bambu_3mf.py)

```bash
uv run python skills/3d-modeling/scripts/make_bambu_3mf.py out.3mf \
  "Base (translucent)=base.stl" "Text (CF)=text.stl"
```

Inputs:

* Output Bambu Studio project 3MF path.
* One or more part specs in `name=path/to/part.stl` form.
* Installed Bambu Studio profile tree under `%APPDATA%/BambuStudio`, currently
  targeted at the X2D profile constants in the script.

Outputs:

* Bambu Studio project 3MF with geometry, `project_settings.config`,
  `model_settings.config`, `slice_info.config`, print settings, and per-part
  filament assignment.
* Stdout with resolved app/profile versions, printer, process, filament mapping,
  mesh stats, written file size, bed placement, and internal verification log.

Exit codes:

* `0`, file was written and internal verification passed.
* `1`, usage is invalid, a profile is missing, a mesh load fails, internal
  verification fails, or an uncaught runtime error occurs. Non-watertight inputs
  print warnings but do not fail by themselves.

## `overlay_photo.py`

Script: [`skills/3d-modeling/scripts/overlay_photo.py`](../skills/3d-modeling/scripts/overlay_photo.py)

```bash
uv run python skills/3d-modeling/scripts/overlay_photo.py cand.stl photo.png out.png [z_mm ...]
```

Inputs:

* Candidate STL.
* Near-orthographic top photo.
* Output PNG path.
* Optional z slice heights. Defaults to `3.5 22.0`.

Outputs:

* Overlay PNG with candidate slice boundaries drawn over the segmented photo.
* Stdout residual metrics: mean residual in mm, p90 residual in mm, sample count,
  and overlay path.

Exit codes:

* `0`, overlay was written and metrics printed.
* `1`, missing arguments, photo segmentation failure, mesh load failure, invalid
  z value, or another uncaught runtime error.

## `verify_visual.py`

Script: [`skills/3d-modeling/scripts/verify_visual.py`](../skills/3d-modeling/scripts/verify_visual.py)

```bash
uv run python skills/3d-modeling/scripts/verify_visual.py ref-stl-or-dir cand-stl-or-dir out-prefix \
  [--test T4] [--json]
```

Inputs:

* Reference STL or directory containing STLs.
* Candidate STL or directory containing STLs.
* Output prefix.
* Optional `--test T4` for camera-window position checks.
* Optional `--json` to print the metrics JSON to stdout.

Outputs:

* `<out-prefix>_compare.png`, a composite image with reference row, candidate
  row, and slice overlay row.
* `<out-prefix>_verify.json`, metrics including bounding boxes, rotation,
  pose scores, slice IoU values, layout IoU, boundary F1, mirror flag, optional
  position checks, verdict, and composite path.
* Stdout verdict lines and composite path, or compact JSON when `--json` is set.

Exit codes:

* `0`, comparison assets were written. A mismatch verdict is data in the JSON,
  not a process failure.
* `1`, missing arguments, no mesh found, render failure, JSON write failure, or
  another uncaught runtime error.

## `tools/gen_harness.py`

Script: [`tools/gen_harness.py`](../tools/gen_harness.py)

```bash
uv run python tools/gen_harness.py [--check]
```

Inputs:

* Neutral role files under `skills/roles/*.md`.
* Existing generated files when `--check` is used.

Outputs:

* Without `--check`, writes the skill tree (`skills/3d-modeling/SKILL.md` and
  `roles/*.md`) plus the Claude agent files, then prints the count written.
* With `--check`, writes nothing. It prints `OK` and a file count if generated
  content matches disk, or prints mismatched paths to stderr.

Exit codes: the convention above, with a `--check` mismatch reported as a `1`.

## `tools/build_skill.py`

Script: [`tools/build_skill.py`](../tools/build_skill.py)

```bash
uv run python tools/build_skill.py [--out dist/skills]
```

Inputs:

* The `skills/3d-modeling/` tree, packed verbatim.
* `--out`, output directory for the generated `.skill` zip artifacts. Defaults
  to `dist/skills`.

Outputs:

* One `3d-modeling.skill` zip: `skills/3d-modeling/` packed verbatim, so the
  orchestrator's `SKILL.md` sits at the archive root with `roles/`, `references/`
  and `scripts/` beside it. Because the shipped shape is the repo shape, every
  relative link inside the archive is the same link that resolves in the repo —
  asserted by `test_every_internal_link_resolves_inside_the_archive`.
* All entries use a fixed timestamp (1980-01-01), sorted archive order, and
  `0o644` permissions for deterministic, reproducible builds. `__pycache__/`
  and `.pyc` files are excluded.

## `uv build --wheel` — the Python runtime surface

```bash
uv build --wheel --out-dir dist/wheels
```

The wheel contains the `pipeline`, `designer_toolkit`, and `team_tools` runtime
packages, required sibling modules such as `mesh_io` and `preview`, and the
`design-tool` entry point. It intentionally excludes test modules and does not
claim to be the agent bundle: `SKILL.md`, roles, and references belong to the
`.skill` archive above. Release validation installs the wheel through uv from
an external working directory and runs both `design-tool doctor` and
`design-tool run-job`; the archive tests extract the `.skill` bundle and run its
documented route from the same kind of external directory.
