# Changelog

All notable changes to the **3d-modeling** skill are documented here.
This project loosely follows [Keep a Changelog](https://keepachangelog.com/) and
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
