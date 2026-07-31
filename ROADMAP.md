# Roadmap

## 1. Purpose

This roadmap describes how to evolve the current repository into the system defined by `ARCHITECTURE.md`.

The roadmap is incremental by design.

Every release increment must:

* improve a capability that a user can exercise;
* preserve useful existing behavior;
* remain small enough to review and benchmark independently;
* add regression protection before or with invasive changes;
* be exercised on authentic modeling work;
* produce lessons that may revise later increments;
* avoid unnecessary runtime, context, process, and AI cost.

This document defines the current best path, not an immutable sequence.

The architecture defines the intended destination. This roadmap may change whenever implementation evidence or real projects reveal a better route to that destination.

## 2. Current position

The current branch already provides important foundations:

* one command surface for running a job;
* a canonical project representation;
* a compiled execution plan;
* one route authority consumed by the runner;
* unchanged dispatch counts across existing routes;
* fast certified deterministic generation;
* authored custom geometry support;
* STEP, STL, and modern production-extension 3MF diagnosis;
* correct 3MF root, unit, component, and build-transform handling;
* controlled failure for malformed or unsupported geometry;
* deterministic L0 benchmark infrastructure;
* structurally separated public and private fixture material;
* selected real benchmark artifacts;
* reproducible packaging and toolchain identity.

The following work is already complete and is treated as the protected baseline.

**Route authority**

The project route is compiled once and the runner consumes the resulting execution plan without re-deriving it.

**Diagnosis hardening**

Modern 3MF structure, external model parts, component transforms, root relationships, geometry condition, and cyclic component graphs are handled explicitly.

**Benchmark foundation**

The repository has:

* fast component fixtures;
* real source artifacts;
* public/private answer separation;
* fixture licensing rules;
* immutable artifact checks;
* initial replay structure.

The immediate unresolved blockers are:

1. unchanged modification jobs cannot reliably complete review resumption while preservation evidence varies between runs;
2. custom candidate code can still influence the criteria used to judge its own output;
3. project history and state are still effectively linear and do not cleanly support divergent design alternatives;
4. Multi-artifact edit intent is now declarable: `edit_scopes` supports several source artifacts, coordinated scopes may share existing interfaces through `interface_ids`, and the plan and gate preserve one obligation per scope. Multi-source candidate production and preservation measurement remain unavailable.
5. preservation is not yet strong enough to support successful modification claims;
6. fitted authored designs and moving assemblies are not yet complete end-to-end capabilities;
7. physical outcomes and alternative comparisons are not yet part of a systematic learning loop.

Several narrower gaps are carried forward from the completed consolidation work. They are not blockers in the same sense, but they are owed and are easy to mistake for finished work:

* the command surface described by ADR 0001 is only partly built. `doctor`, `selftest`, `init`, `route`, `run`, `status`, `diagnose`, and the deprecated `run-job` exist; `commission`, `audit`, `motion`, `coupon`, and `package` do not. Until they do, the older `dt.py` verbs stay in agent instructions.
* designer commissions are not yet generated from canonical project state, and the template registry does not yet distinguish a certified template from a starting one.
* a job that declares motion routes `FULL`, and its motion modifier is reported `DEFERRED` rather than measured. The sweep engine does not exist. Naming it unmeasured is deliberate and is not a substitute for Release 8.
* there is no resource governor, and the 3MF writers are not versioned adapters.
* preservation sampling is deterministic but its density is not derived from a declared minimum detectable defect size, and exact STEP comparison is undecided. A real modification job put a number on what that costs: the entire defect the audit had to find was 85 faces of a 93,530-face part, under a tenth of a percent of its surface. Every job that declares an edit scope therefore reports `EXPERIMENTAL_UNAVAILABLE` rather than a successful status.
* preservation also has one verdict for one box. The same job needed three dispositions over named regions — geometry that must not move, geometry permitted to change, and geometry the edit deliberately consumed — because the deviation its audit reported, an unfiltered global maximum of 1.797 mm, *was* the requested change: material consumed where the two parts now interpenetrate, in a band opened to 2.88 mm by design. One box and one band cannot tell that apart from a defect, so the checker fails a correct part.
* there is no repair path at all. `design-tool diagnose` classifies an artifact `REPAIR_REQUIRED` and stops, so a supplied file with non-manifold or open geometry cannot be modified through this skill even though `MISSION.md` names repair as a required capability and `ARCHITECTURE.md` §11.4 specifies it.
* nothing certifies what an export writer wrote. A clean float64 solid became 429 zero-area faces and 367 non-manifold edges when written as binary STL, and two halves of one job independently hand-wrote the same float32-weld and file-versus-memory checks. Preservation and commissioning measure a file, and no tool currently proves the file carries what the geometry in memory did.
* datums carry no provenance and are not dependency bindings. [ADR 0003](docs/adr/0003-datum-provenance-and-authority.md) records the case: a hand-authored shared datum, one of whose fields described a part before that part was modified, was given blanket precedence by an agent brief, and the compliant action was to build three features that must not exist.
* a `FITTED` or `FULL` job built from authored geometry reports `UNSUPPORTED`. That is a limit of what this build can do, not a stage that is pending.

Tolerances today are single numeric bands owned by the pipeline. There is no tolerance profile, no datum model beyond what a dimension names, no per-body material assignment, and no operation model. Those are introduced by the releases below, at the point where a real job needs them.

## 3. Roadmap operating rules

### 3.1 Deliver vertical slices

Prefer a narrow complete capability over a broad unfinished framework.

A release increment should normally include:

* input representation;
* execution;
* output;
* state and resumption;
* relevant assessment;
* regression fixtures;
* one authentic use case;
* user-facing documentation.

Do not build a general abstraction unless the current vertical slice requires it or multiple real cases already justify it.

### 3.2 Keep work usable during repairs

When a capability cannot honestly claim success, it should still perform useful deterministic work where possible.

It should continue to:

* diagnose inputs;
* generate geometry;
* export artifacts;
* measure results;
* write evidence;
* support iteration;
* preserve alternative branches and their artifacts.

It must clearly limit its final claim.

### 3.3 Correctness wins explicitly

Performance and cost constraints are real product requirements, but correctness takes priority.

When correctness requires a measurable cost increase:

1. measure the increase;
2. explain which failure it prevents;
3. confirm that the cost applies only where necessary;
4. record the accepted trade-off.

No trade-off may be taken silently.

### 3.4 Preserve the common case

The intended common behavior remains:

* deterministic reusable work: zero AI design calls;
* ordinary custom work: one coherent design context;
* optional alternative exploration: explicitly requested or justified;
* additional AI calls: only when ambiguity, independence, consequence, or user preference justifies them.

No release may add an AI round trip to an existing path as an accidental side effect.

### 3.5 Treat alternative exploration as optional work

The architecture supports branching, but the system must not generate multiple concepts for every job.

Alternative exploration is justified when:

* the user asks for options;
* materially different mechanisms are plausible;
* early commitment would be costly;
* the consequences justify comparison;
* a preferred concept fails;
* a benchmark explicitly tests design exploration.

Cosmetic variants do not justify full branches unless styling is itself the task.

### 3.6 Use real jobs as design evidence

Each release increment must be exercised on at least one authentic project.

Synthetic fixtures prove mechanisms. Real jobs reveal missing concepts, bad assumptions, and unusable workflows.

### 3.7 Add engineering semantics only where they earn their cost

Tolerance profiles, multi-material assignment, compensation, and operation sequencing are added the same way every other capability is: as narrow vertical slices, driven by a real job.

There is no "implement GD&T" release and no "implement multi-material" release. The foundations appear when something needs them, and they deepen only where use demonstrates they are insufficient.

For all such work:

* begin with a narrow vertical slice, not an ontology;
* add L0 deterministic tests for the new semantics;
* add at least one L1 replay that exercises them end to end;
* use an authentic project before generalizing;
* measure runtime, context, and dispatch cost before and after;
* preserve the zero-call and one-call common paths;
* do not implement a complete ASME or ISO ontology speculatively;
* do not generalize a compensation value from one print;
* do not add operation sequencing to jobs with only one meaningful operation;
* keep required final geometry separate from manufacturing compensation in every release that touches either;
* revise later roadmap scope based on what the slice actually showed.

A job that declares none of these things must cost exactly what it cost before the capability existed. That is a measurable claim, and the performance gate measures it.

### 3.8 Separate architectural learning from project peculiarities

After each release, classify discoveries as follows.

Classification determines whether the code, roadmap, or architecture must change. It does not determine whether dependent work may continue. Any defect that violates an authority invariant, defeats a release gate, or can produce a false successful claim fails closed until repaired and regression-tested. Work that does not depend on the violated boundary may continue with its claims explicitly limited.

**Implementation defect**

The design is adequate; the implementation is wrong.

Action:

Fix the code and add a regression fixture. If the defect violates an authority or claim-strength invariant, stop the dependent success-claim path until the fixture proves the repair.

**Missing roadmap capability**

The architecture already allows the behavior, but no release currently implements it.

Action:

* add, split, or reorder a roadmap item.

**Missing domain concept**

The authoritative model cannot express a recurring real requirement cleanly.

Action:

* amend `ARCHITECTURE.md`;
* record an ADR;
* revise dependent roadmap items.

**Invalid architectural assumption**

A trust boundary, authority rule, or major decomposition is shown to be wrong.

Action:

* stop dependent work;
* revise the architecture before continuing.

**Project-specific exception**

The issue is real but does not justify a general mechanism.

Action:

* record it in the project or fixture;
* do not enlarge the core architecture without further evidence.

A severe authority or correctness defect may justify an architecture change after one demonstrated case. Convenience features should normally require broader evidence.

## 4. Release gate

Every release increment must pass the following applicable gates.

### 4.1 Functional gate

* The user-visible capability works through the normal command surface.
* Failures are actionable and controlled.
* The capability produces useful artifacts even when its final claim is limited.
* Supported interrupted work resumes correctly.
* Alternative-specific work cannot overwrite sibling artifacts.

### 4.2 Authority gate

* Runtime execution follows the compiled plan.
* Candidate output cannot redefine the criteria used to judge it.
* Reviews are bound to the evidence reviewed.
* Claims state only what the evidence supports.
* Alternative creation cannot silently weaken shared mandatory requirements.

### 4.3 Regression gate

* Existing tests remain green.
* Important new behavior receives L0 coverage.
* At least one relevant L1 replay exists.
* A mutation or adversarial test demonstrates that the principal protection can fail.

A test that only confirms a nominal verdict is insufficient when the underlying evidence chain can be asserted directly.

### 4.4 Performance gate

* Certified deterministic paths show no meaningful regression outside measurement noise.
* Dispatch counts do not increase accidentally.
* New expensive checks are capability-triggered.
* A job that declares no tolerance profile, no per-body material, and no operation plan shows no measured cost change.
* Cold and warm costs are measured separately where imports dominate.
* Cache behavior is measured rather than assumed.
* Shared work is reused across alternatives.

Provisional suite budgets on the reference machine:

* commit-gating L0 suite: approximately five seconds or less;
* normal warm L1 replay suite: approximately two minutes or less;
* live L2 suite: on demand, limited to a small number of jobs.

These are budgets, not correctness limits. A necessary exception must be documented.

### 4.5 Real-job gate

The release is used on at least one authentic project.

The outcome records:

* what worked;
* what failed;
* what required manual intervention;
* what was physically tested;
* what remains unresolved;
* which alternatives were explored;
* why an alternative was preferred, paused, or rejected;
* whether the roadmap or architecture should change.

### 4.6 Documentation gate

Current documentation must describe what the released skill actually supports.

Future architecture must not be presented as current behavior.

## Release 1 — Stable evidence and resumable review

**Outcome**

An unchanged job can produce evidence, receive a review response, and resume without the evidence changing underneath that response.

**Why this comes first**

This is a capability-liveness defect.

A modification job that cannot complete a review round trip is not merely weakly verified; it is unusable through the intended command flow.

**Scope**

Make evidence generation deterministic where resumption depends on it.

Bind preservation sampling and evidence generation to:

* source hashes;
* candidate hashes;
* edit intent;
* source-to-design transforms;
* algorithm version;
* sampling parameters.

Canonicalize:

* mesh traversal where relevant;
* evidence ordering;
* numeric serialization;
* receipt serialization.

Bind each review response to:

* the evidence packet identity;
* the relevant execution-plan identity;
* the relevant acceptance revision;
* the sampling-plan identity where applicable.

Reuse valid evidence for unchanged inputs.

**Explicit exclusions**

Do not implement yet:

* adaptive high-density preservation;
* minimum detectable defect guarantees;
* multi-source preservation;
* exact B-rep comparison;
* complete inherited-overhang analysis;
* divergent alternative histories.

This release makes the evidence repeatable. It does not make the existing preservation method sufficient for a successful modification claim.

**User-visible improvement**

A user can run a modification job, answer its requested review, rerun the same command, and progress without an evidence-envelope mismatch caused solely by nondeterminism.

**Proof**

Required tests include:

* repeated unchanged runs produce byte-stable evidence;
* a response to one unchanged run is accepted by the next;
* changed source rejects the old response;
* changed candidate rejects the old response;
* changed edit intent rejects the old response;
* changed transform rejects the old response;
* changed algorithm version rejects the old response;
* interrupted and resumed runs retain one evidence identity;
* clean-clone reproduction yields the same identity.

**Authentic exercise**

Use the vent-mount and 17 mm ball project to complete an evidence and review round trip.

The final result remains limited by the current preservation capability.

## Release 2 — Trustworthy ordinary custom design

**Outcome**

A user can request an original or ordinary custom part and receive a meaningful result from one design context, while candidate geometry is structurally unable to rewrite its own acceptance criteria.

**Scope**

Separate:

* design intent;
* design proposal;
* geometry implementation;
* observed geometry;
* acceptance specification.

The ordinary flow becomes:

1. one design context produces a proposal and editable model source;
2. the proposal is validated and frozen;
3. the system compiles the acceptance specification;
4. the model executes;
5. the exported artifact is measured against that specification.

Acceptance information may come from:

* explicit user requirements;
* immutable source artifacts;
* accepted proposal values;
* manufacturing policy;
* system-owned tolerance policy.

It may not be re-read from mutable model code after evaluation.

Proposal changes remain allowed, but create a visible new design revision and invalidate dependent results.

*Isolated build boundary*

Execute authored candidate code through an isolated one-shot build boundary. The authoritative process freezes and retains acceptance state, sends only required build inputs to the candidate process, then independently reimports and assesses the produced artifacts.

The ruled design shape is:

1. the parent validates and freezes the proposal;
2. the parent constructs and retains the authoritative acceptance object;
3. a one-shot child process executes the candidate code;
4. the child receives only the build inputs it needs;
5. the child writes geometry and a small build manifest to a temporary build directory;
6. the parent reimports and hashes the produced artifacts;
7. the parent performs commissioning, screening, review binding, and final status in its clean interpreter.

The protocol is JSON and files, not pickle or shared Python objects. The child must not write authoritative receipts. The parent retains the frozen contract in memory and verifies its on-disk hash after the child exits. `DIRECT` does not need a subprocess; the cost applies only to authored candidate execution.

*Minimum common tolerance foundation*

The acceptance specification stops carrying bare numbers with an implied band.

Add, and no more than this:

* a lightweight explicit tolerance representation — nominal value with a unilateral, bilateral, or limit tolerance;
* the datum or measurement reference a value is taken from, where the value would otherwise be ambiguous;
* the measurement method, where interpretation would otherwise be ambiguous;
* provenance on the tolerance as well as on the value;
* a recorded separation between required finished-part geometry and any process compensation, so that compensation has somewhere to go later without rewriting a requirement.

The system continues to own the band. A designer states what the part must measure; the pipeline decides what band that magnitude is judged in. That property is the point of this release and the tolerance representation must not weaken it.

Compensation is separated in this release but not yet computed. A job with no compensation records none, and nothing about it changes.

**Explicit exclusions**

Do not yet attempt:

* full fitted authored work;
* full multi-source modification;
* strong preservation claims;
* universal anomaly screening for novel custom designs;
* divergent branch storage;
* automatic A/B concept generation;
* a second AI confirmation of the proposal;
* formal GD&T support of any kind — no profiles, no editions, no feature-control frames, no datum reference frames;
* material compensation values;
* per-body material assignment.

Proposal freezing is deterministic continuation of one design commission, not another dispatch.

**User-visible improvement**

A user can obtain:

* editable source;
* production geometry;
* measured requirements;
* a clear commissioned result;
* explicit remaining physical-test requirements;

for ordinary novel work using one design call.

**Proof**

Adversarial tests include:

* proposal declares 24 × 18 while implementation builds 10 × 8;
* implementation supplies an excessive tolerance;
* expectation changes after a failed result;
* model changes while an old proposal remains;
* proposal changes and correctly invalidates prior artifacts;
* candidate-measured volume is reused as expected volume;
* candidate profile data attempts to clear its own anomaly screen;
* a proposal supplies its own tolerance band and the pipeline's band still governs;
* a compensated dimension is measured against the compensated value rather than against the requirement;
* candidate code monkeypatches `AcceptanceSource.expectations`;
* candidate code monkeypatches commissioning tolerance functions;
* candidate code monkeypatches final-status logic;
* candidate code modifies its local copy of the acceptance object;
* none changes the parent's frozen contract, assessment behavior, or final result;
* unexpected child-written receipts are ignored or rejected;
* `DIRECT` dispatch count and runtime remain unchanged.

The release passes only when candidate-controlled acceptance is structurally impossible, not merely rejected by one validator.

**Authentic exercise**

Use an open-ended FDM bracket request with:

* mounting requirements expressed as lightweight explicit tolerances;
* a keep-out;
* a build envelope;
* material and nozzle constraints;
* freedom over ribs, walls, and styling.

The bracket's fastener holes and mounting pitch are the test of whether the lightweight profile is expressive enough. If it is not, that is a finding for Release 7, not a reason to add formal tolerancing here.

Produce at least two geometrically different valid outputs in separate jobs to confirm that the system rewards requirements rather than resemblance. First-class shared branching arrives in the next release.

## Release 3 — Revision graph, branching, lifecycle, and context budgets

**Outcome**

The project can safely preserve divergent design alternatives, resume the correct branch, and reuse shared work without losing authority or increasing ordinary-job cost.

**Why this comes early**

Fitting, modification, combination, and motion all benefit from exploring competing concepts.

Adding branching after those capabilities would require retrofitting:

* artifact identity;
* invalidation;
* review bindings;
* acceptance revisions;
* physical outcomes;
* benchmark records.

**Scope**

*Revision graph*

Generalize the state model from an effectively linear history into a directed acyclic revision graph.

Support:

* ordinary single-parent revisions;
* sibling alternatives sharing a common ancestor;
* explicit alternative identity;
* stable parent relationships;
* alternative-specific proposals;
* alternative-specific implementations;
* alternative-specific artifacts;
* alternative-specific assessments;
* later explicit merges.

The user-facing system does not need to expose Git terminology.

*Alternative lifecycle*

Support alternative states such as:

* active;
* preferred;
* paused;
* rejected;
* superseded;
* retained as fallback;
* merged.

Changing the preferred alternative must not delete or overwrite previous alternatives.

*Binding-aware lifecycle*

Introduce or complete:

* run identities;
* job and alternative revisions;
* computed current status;
* stale-result invalidation;
* explicit resume versus restart;
* superseded next actions;
* structured malformed-project errors.

*Scoped decisions*

Allow decisions to apply to:

* the whole job;
* one alternative;
* one component;
* one interface;
* one manufacturing configuration.

An alternative-specific choice must not silently become a job-wide requirement.

*Dormant optional intent*

The authoritative model and its bindings must be able to carry, without any of it being required:

* tolerance-profile identity and edition;
* per-body and per-interface material identity;
* operation identities and their dependencies;
* alternative-specific manufacturing intent.

Nothing in this release populates these fields. Later releases do. Adding the capacity now is cheap; retrofitting it into artifact identity, invalidation, and review binding afterwards is not, which is the same argument that puts the revision graph here.

An absent field is absent, not defaulted. A job that names no tolerance profile is not silently assigned one, and its bindings do not include a profile identity.

*Scoped invalidation*

A change to any of the following invalidates its dependent results and nothing else:

* tolerance profile;
* material assignment;
* compensation assumptions;
* operation sequence.

Reassigning one body's material must not invalidate an assessment of an interface whose two sides are unchanged.

*Capability-based execution*

Compile required capabilities such as:

* source diagnosis;
* original design;
* alternative exploration;
* imported modification;
* combination;
* external-object fitting;
* evidence recovery;
* motion;
* manufacturing preparation;
* independent judgment.

Existing route names may remain useful summaries, but required work is derived from capabilities.

*Lazy assessment*

Create one capability-triggered assessment registry.

The inexpensive baseline covers:

* parseability;
* finite geometry;
* units;
* transforms;
* non-empty output;
* component structure;
* bounding box;
* build envelope;
* topology characterization.

Additional assessments run only when triggered by:

* an interface;
* edit intent;
* motion;
* manufacturing constraints;
* evidence uncertainty;
* consequence;
* alternative comparison;
* explicit user request.

*Context budget foundation*

Record and constrain:

* AI dispatch count;
* input context size;
* deterministic runtime;
* expensive imports;
* cache reuse;
* repeated work;
* incremental alternative cost.

Prepare task-specific context packages rather than loading all roles and project history by default.

A context working on one alternative receives:

* shared job intent;
* relevant ancestry;
* that alternative's differences;
* relevant evidence;
* sibling summaries only when comparison is needed.

**Explicit exclusions**

Do not yet:

* generate multiple concepts automatically;
* implement sophisticated alternative scoring;
* merge arbitrary geometry automatically;
* redesign every role or prompt;
* remove route labels;
* build a general distributed scheduler.

This release establishes safe branching and isolation. Rich alternative formulation and comparison follow in Release 4.

**User-visible improvement**

The user can:

* preserve a screw-fastened concept;
* branch into a snap-fit concept;
* continue developing either;
* switch the preferred concept;
* resume the correct branch;
* retain shared source analysis and requirements;
* avoid repeating unchanged work.

**Proof**

Fixtures include:

* two sibling alternatives sharing one proposal ancestor;
* alternative-specific proposal changes;
* one branch failure that does not invalidate its sibling;
* shared requirement change that invalidates both;
* branch-specific manufacturing change;
* paused and resumed alternative;
* switched preferred alternative;
* no artifact overwrite between siblings;
* review response bound to one branch only;
* explicit merge record with multiple parents;
* clean-clone reconstruction of the revision graph;
* a project declaring no tolerance profile, no per-body material, and no operations produces bindings identical to today's;
* a changed material assignment on one body invalidates only what depended on it.

**Authentic exercise**

Branch the bracket project into:

* a snap-fit formulation;
* an M3 screw formulation.

Confirm that:

* mandatory mounting requirements remain shared;
* fastening decisions remain branch-specific;
* source and printer context are reused;
* artifacts and assessments remain isolated;
* selecting one concept does not delete the other.

## Release 4 — Alternative formulation and comparative assessment

**Outcome**

The skill can intentionally generate, develop, compare, select, pause, and revisit materially different design concepts.

**Scope**

*Alternative formulation*

Allow the planner or user to request alternatives that differ in meaningful engineering choices, such as:

* snap-fit versus screws;
* magnetic versus mechanical retention;
* one-piece compliant versus multi-part pinned construction;
* rigid mount versus articulated mount;
* top-loading versus sliding enclosure;
* a single rigid part with a separate gasket versus one multi-material part;
* a part assembled from printed pieces versus one printed with an embedded insert.

Alternatives may therefore differ in tolerance strategy where the difference is legitimate, in materials, in inter-material interface strategy, in manufacturing sequence, in assembly sequence, and in serviceability — as well as in geometry.

An alternative may not differ in a mandatory requirement. A looser tolerance is a different alternative only when the requirement genuinely permits it; it is never a way to make a failing concept pass.

Each alternative records:

* why it exists;
* which assumptions differ;
* which intent remains shared;
* its proposal;
* its implementation;
* its artifacts;
* its assessments;
* its manufacturing implications.

*Bounded exploration policy*

Alternative generation is triggered only when:

* explicitly requested;
* materially different concepts are plausible;
* uncertainty makes comparison valuable;
* consequence justifies redundancy;
* the preferred concept fails.

The planner limits:

* number of active alternatives;
* AI calls per alternative;
* context duplication;
* repeated deterministic work.

*Comparative assessment*

Compare alternatives across:

* mandatory requirement satisfaction;
* interface performance;
* manufacturing complexity;
* material use;
* expected print time;
* support burden;
* component count;
* assembly effort;
* adjustability;
* maintainability;
* uncertainty;
* physical evidence;
* user preference.

Where the alternatives differ in them, comparison also covers:

* tolerance strategy;
* materials and material count;
* inter-material interface strategy;
* manufacturing sequence complexity;
* assembly sequence complexity and required tooling;
* irreversible operations and what they foreclose;
* serviceability.

These are comparison dimensions when present, not mandatory scoring categories for every job. A single-material one-piece print is compared on the criteria it actually exercises.

Mandatory failures remain visible and cannot be hidden by weighted totals.

Comparison distinguishes:

* objective measurements;
* policy-derived estimates;
* engineering judgment;
* missing evidence;
* user preference.

*Alternative disposition*

Support explicit reasons for:

* preferred;
* paused;
* rejected;
* superseded;
* retained as fallback.

*Reuse and merge planning*

Allow a new alternative to declare that it reuses elements from earlier alternatives.

The system identifies:

* potentially reusable artifacts or subcomponents;
* assessments that remain valid;
* assessments invalidated by interaction changes;
* required reassessment after merging.

This release does not require automatic geometric merging.

**Explicit exclusions**

Do not:

* generate several alternatives for every job;
* treat cosmetic variants as independent engineering concepts by default;
* collapse comparison into one opaque score;
* automatically claim that merged successful features form a successful whole;
* keep unlimited active alternatives.

**User-visible improvement**

A user can request:

> Explore snap-fit and M3 screw versions, compare them, and retain both while we test the preferred one.

The system can execute that without flattening the work into one linear sequence.

**Proof**

Required tests include:

* materially different alternatives inherit the same mandatory intent;
* cosmetic-only variants are not automatically treated as concept branches;
* alternative-specific requirements remain scoped;
* an alternative cannot loosen a shared mandatory tolerance to pass;
* a comparison over single-material alternatives reports no material or sequence dimensions;
* mandatory failure cannot be outweighed by preference scoring;
* comparison reports unequal evidence;
* paused alternative incurs no ongoing execution cost;
* switching preference does not delete prior results;
* merged proposal preserves source-alternative provenance;
* affected assessments become stale after a merge.

**Authentic exercise**

Use the bracket alternatives from Release 3.

Compare snap-fit and M3 concepts for:

* mandatory mounting compatibility;
* hardware requirements;
* printability;
* assembly;
* adjustability;
* strength uncertainty;
* material use.

Select one as preferred while retaining the other as fallback.

## Release 5 — Multi-source edit and combination model

**Outcome**

The skill can represent and execute genuine modification and combination jobs involving multiple source artifacts and alternative source strategies.

Delivered early slice: Multi-artifact edit declaration, validation, shared-interface references, planning, and preservation-row gating landed in response to the OnePlus case-and-drawer job. The remaining Release 5 work includes source-role generalization, selected assembly components, inheritance semantics, and candidate production suitable for per-artifact preservation assessment.

**Scope**

Generalize the authoritative job model to support:

* zero, one, or many sources;
* source-specific roles;
* source-specific transforms;
* selected components within source assemblies;
* source-specific preserved regions;
* source-specific removable regions;
* source-specific editable regions;
* added geometry;
* output-component inheritance;
* named regions, each carrying exactly one declared disposition — must-preserve, permitted-change, or consumed-by-intent;
* shared datums carrying provenance, the artifact revision they were derived from, and their validity scope.

The last two are declaration obligations, not measurement ones; Release 6 measures against them. A region with no disposition and a datum with no provenance are the two ways a job can arrive at Release 6 with nothing to judge it by. The datum requirement is [ADR 0003](docs/adr/0003-datum-provenance-and-authority.md): coordinated scopes name one datum identity rather than each holding a copy of the number, and a datum derived from an artifact before that artifact was edited is valid against the revision it was measured on and no later one.

Imported intent survives the edit. Multi-source edit intent preserves:

* per-source material identity;
* material assignments carried by an imported assembly;
* the donor's material role, where the donor contributes a distinct material;
* sequence obligations attached to inserts or embedded components in a source.

A job that prints in one material does not thereby erase the two materials its donor declared. Discarding imported multi-material intent is a defect, not a simplification — the intent is recorded even when this release cannot act on it.

Typical roles include:

* base;
* donor;
* external mating object;
* reference-only;
* previous revision.

Combination uses the same edit model as modification. It is not implemented as a second parallel concept.

The acceptance specification records every source obligation, even where the final comparison method is not yet strong enough to authorize success.

Alternatives may differ in:

* selected donor artifact;
* donor component;
* alignment;
* fastening strategy;
* retained geometry;
* output component structure.

**Explicit exclusions**

Do not yet promise:

* complete preservation verification;
* exact STEP preservation;
* all possible assembly-selection semantics;
* automatic inference of every edit region;
* automatic resolution of competing donor strategies.

The job may execute fully while reporting that preservation acceptance remains unavailable.

**User-visible improvement**

The user can formally express and run:

* retain the vent attachment from one source;
* retain the 17 mm ball from another;
* remove unwanted regions;
* align the sources;
* generate one combined result;
* preserve an alternative using a different donor or attachment strategy.

**Proof**

Fixtures cover:

* single-source modification;
* two-source combination;
* transformed donor;
* selected component from a source assembly;
* changed source hash;
* missing source;
* role mismatch;
* one preserved source and one intentionally consumed donor;
* a donor carrying two material assignments, both still readable after the edit;
* a source declaring an embedded insert, whose sequence obligation survives import;
* two alternatives using different donors;
* branch-local source change that does not invalidate the sibling;
* shared base-source change that invalidates both;
* two coordinated scopes referencing one shared datum, where changing that datum invalidates both and neither holds a private copy;
* a datum derived from a source revision the job then edits, which is refused against the later revision rather than silently reused.

No schema, acceptance compiler, or runtime API may assume exactly one source.

**Authentic exercise**

Run the real vent-mount plus ball combination through the ordinary command surface.

Optionally branch into:

* direct ball graft;
* reinforced intermediate neck.

Compare:

* source identities;
* source transforms;
* retained regions;
* removed regions;
* output component count;
* output gross dimensions;
* donor alignment;
* manufacturing implications.

## Release 6 — Deterministic geometric comparison and production modification

**Outcome**

Supported modification and combination jobs can reach honest successful outcomes based on reproducible source-specific evidence.

**Scope**

Three of the parts below — bounded repair, certified export, and per-region preservation — are separable slices with their own tests, their own replay, and their own authentic exercise. They are in one release because one real job needed all three at once, not because any of them has to wait for the others. Take them in the order real jobs need them, and do not hold the comparison core hostage to the slowest.

Build one shared deterministic comparison capability for:

* preservation;
* mating interfaces;
* alternative comparison;
* later motion contact;
* benchmark scoring.

The comparison core supports:

* canonical traversal;
* spatial indexing;
* transform-aware comparison;
* changed-cell detection;
* deterministic surface samples;
* bidirectional distance;
* region filtering;
* component correspondence;
* percentile and maximum deviations;
* cached source indices;
* stable serialization;
* surface-to-surface distance between two parts placed in their assembled transforms, filtered by region, reporting an interference count as well as a distance;
* residual material between geometry an edit added or removed and the nearest surface that edit must not break through;
* a declared resource bound on every query above, with a controlled failure instead of an allocation attempt.

The last three are one primitive applied to different inputs, not three capabilities. "How far is part A's surface from part B's, in this region" and "how much wall is left above this pocket" are the same query, and one real job needed both: the 0.300 mm residual left above its magnet pockets was the most consequential number it produced and nothing in the pipeline would have surfaced it, while the cross-part clearance it also needed sent trimesh's proximity path into a 20.5 GiB allocation attempt for 100k points against a 96k-face mesh. The job finished because an agent hand-rolled cropping and batching. The resource bound is therefore scope rather than optimization: an unbounded query is a check that fails as an out-of-memory kill rather than as a result.

It also gains the primitives needed to assess, where those things are declared:

* the tolerance zones the engine actually supports;
* lightweight limit tolerances;
* clearances between regions of different materials;
* the same geometry before and after compensation, without measuring one against the other;
* geometry in a specific operation-dependent assembly state.

The engine reports which tolerance constructs it can evaluate. A declared construct outside that set is reported as an unevaluated limitation, never as conformance, and never as an approximate band that happens to be checkable.

Preservation uses a staged method:

1. compare cheap structural facts;
2. locate spatially changed regions;
3. refine comparison only where required;
4. distinguish allowed changes from unexpected changes;
5. report the method and detection limit.

Every verdict is reported per named region, against that region's declared disposition, in both directions:

* **must-preserve** regions, where movement in either direction is a failure;
* **permitted-change** regions, judged against the band declared for them;
* **consumed-by-intent** regions, where the material's disappearance is the requested result and its absence is evidence that the edit happened;
* geometry added or removed outside every declared region, which fails whichever direction finds it.

A single whole-part verdict is issued only where a single whole-part obligation was declared. An unfiltered global maximum over a part carrying three dispositions measures the largest legitimate change, and reporting it as a preservation verdict fails correct parts: one real modification job's unfiltered global maximum was 1.797 mm, and it was a legitimate change — the job deliberately consumed material where its two parts now interpenetrate, in a band that opened to 2.88 mm by design. A two-verdict checker fails that part outright. It would be right about the number and wrong about the part.

Sampling density is derived from a declared minimum detectable defect size rather than a fixed count, and the verdict is named for what the method established — stage 5 of [ADR 0002](docs/adr/0002-route-and-contract-authority.md). The size to design against is small: the entire defect that same job's audit had to find was 85 faces of 93,530.

A datum a comparison rests on is one of its bindings. Changing a shared datum invalidates the comparisons that used it, in every coordinated scope that referenced it, per [ADR 0003](docs/adr/0003-datum-provenance-and-authority.md).

Exact B-rep claims are available only when an actual exact comparison backend exists.

Alternative comparisons may reuse common source indices and shared external-object analysis.

*Bounded repair*

A supplied artifact classified `REPAIR_REQUIRED` currently ends the job: diagnosis names the condition and nothing acts on it. `MISSION.md` requires repair and architecture section 11.4 specifies it, so this is the slice that implements it, bounded on purpose:

* repair is attempted only where diagnosis names a specific defect class, and only where the declared edit needs the geometry that defect affects;
* the repaired artifact is a new artifact with its own identity and an explicit relationship to the file it came from. The supplied file is never rewritten, for the reason `diagnose` already refuses to rewrite it — it is frequently the only authoritative copy;
* every repair is recorded: what was wrong, the method, the named region it changed, the geometry before and after, and whether that region was already permitted to change;
* an assessment resting on repaired geometry says so and says which region, per architecture sections 6.2 and 8.4;
* a defect the available methods cannot fix is reported as a limitation, never narrowed until it passes.

Repair also depends on diagnosis naming the right defect class, which is not free: a report that calls nine three-face edges and one four-face edge "boundary edges" points a repairer at hole-filling, which cannot work on any of them ([`docs/defects.md`](docs/defects.md) D1).

*Certified export*

A preservation audit, a commissioning measurement and a final claim are all statements about an artifact, and an artifact is a file. The writer that produces it is a backend, and architecture section 12 already forbids a backend from silently changing topology interpretation or artifact identity. Nothing currently checks that it did not.

* every production write is re-read and re-measured before anything claims anything about it;
* the re-read compares classification, body count, per-part volumes and topology counts against the geometry that was written, and fails when they move;
* coordinate precision is part of the contract. A writer that formats coordinates loses geometry, and how much it lost is reported rather than assumed negligible;
* the check runs in the shipped frozen runtime. A self-check whose dependency is absent from that runtime has never run, and it must report that it was skipped rather than imply that it passed.

The evidence threshold in section 3.1 is met by two sibling jobs, not by one: both halves of the case-and-drawer commission independently hand-wrote the same float32-weld and file-versus-memory comparison, after a clean float64 solid came back from a binary STL write carrying 429 zero-area faces and 367 non-manifold edges.

**Explicit exclusions**

Do not:

* build a universal geometric-equivalence prover;
* increase sample density uniformly over every model;
* let sampled evidence claim exact preservation;
* treat geometric closeness as proof of equal function;
* claim conformance to a formal construct the engine cannot evaluate;
* compare a requirement against compensated manufacturing geometry;
* assume a sibling alternative's assessment applies to another;
* repair geometry the declared edit does not need, or present a repaired artifact as the supplied one;
* issue a preservation verdict for a region whose disposition was never declared;
* run an unbounded proximity query and let the process die in place of failing the check;
* compare an in-memory mesh when the claim is about the file that was written.

**User-visible improvement**

Users can modify and combine supported STEP, STL, and 3MF sources while receiving reproducible evidence about unintended changes.

Supported modification and combination jobs may regain successful final claims.

**Proof**

Fixtures include:

* identical meshes with different vertex order;
* rigidly transformed equivalents;
* equivalent remeshing;
* small undeclared addition outside edit scope;
* permitted addition inside edit scope;
* removed source feature;
* thin feature;
* changed component structure;
* multi-source preservation;
* two alternatives sharing unchanged source geometry;
* one branch-specific edit that leaves sibling evidence valid;
* merged geometry requiring reassessment;
* a part whose largest legitimate change is larger than its largest illegitimate one;
* a consumed-by-intent region whose material is *not* gone, which fails;
* a source carrying three-face and four-face edges, repaired inside a declared region and refused outside it;
* an export whose write welds vertices, caught by re-reading the file rather than the memory it came from;
* a two-part clearance query whose unbounded form would exhaust memory, which fails as a check.

The result must state:

* comparison method;
* tolerance;
* detection limit;
* unsupported conditions;
* source-specific verdicts;
* per-region verdicts and the disposition each was judged against;
* any repair the result rests on, and the region it changed;
* alternative identity.

**Authentic exercise**

Produce fresh vent-mount alternatives from the authentic request and sources.

Compare each against:

* source-preservation obligations;
* donor alignment;
* 17 mm functional geometry;
* manufacturing intent;
* the physically proven historical result where informative.

Historical physical proof remains separate from proof of a new candidate.

Run the case-and-drawer magnetic-retention modification as the second authentic exercise, because it is the job that produced most of this release's scope and it exercises what the vent mount does not: two coordinated edit scopes, a shared datum, three region dispositions in one part, a repair-blocked source, a cross-part clearance query large enough to matter, and a residual wall — 0.300 mm above the magnet pockets — that decides whether the part is usable at all.

## Release 7 — Real-object fitting

**Outcome**

The skill can design parts that fit existing real objects using clean CAD, published dimensions, measurements, photographs, or combinations of evidence.

**Dependencies**

Requires Releases 2, 3, and 6.

It may be exchanged in order with Release 8 after those common dependencies are complete. Fitting is recommended first because it covers more frequent use cases and has stronger existing fixtures.

**Scope**

*Independent mating-object model*

Represent the external object independently from the candidate.

The mating object may come from:

* trusted CAD;
* published dimensions;
* structured primitive geometry;
* measured datums;
* a visual envelope;
* reconstructed surfaces.

The mating-object model is shared across alternatives unless an alternative explicitly uses a different evidence interpretation.

*Interface model*

Support interface classes such as:

* clearance;
* sliding;
* interference;
* compliant;
* snap;
* retained;
* seated.

An interface may define:

* mating regions;
* seated transform;
* fit band;
* insertion direction;
* intended contact;
* forbidden contact;
* retention;
* critical dimensions.

*Tolerance and fit semantics*

The lightweight tolerance and fit profile from Release 2 becomes the default for fitted work, and gains what fitting actually needs:

* explicit datums, so a measurement and the dimension it feeds name the same reference;
* measurement semantics — what was measured, how, and against which face or feature;
* interface-specific tolerance bands, so a press fit and a clearance hole on the same part are not judged in one band.

Formal tolerance-profile support is added here only for jobs that supply or require it: a declared profile family, a declared edition, and the specific constructs the implementation can evaluate. A supplied formal tolerance is either evaluated under its own profile or reported as unsupported. It is never reinterpreted as a lightweight band, and ASME and ISO semantics are never mixed in one declaration.

The fitted fixtures are the evidence for how far this needs to go. Determine whether the lightweight model was sufficient for the Pixel case, the Berlingo knob, and the lighter fitted cases before expanding formal support. Recurring real ambiguity that the lightweight profile cannot express is the only justification for adding a construct.

*Evidence reconciliation*

Support:

* photos;
* caliper readings;
* published specifications;
* conflicting values;
* confidence;
* corrected measurements;
* physical-fit feedback.

Different interpretations may become explicit evidence alternatives when the ambiguity cannot yet be resolved.

*Interface assessment*

Prefer:

* satisfaction of declared fit bands;
* comparison relative to the shared external object;
* insertion and seating feasibility;
* retention;
* critical dimensions.

Do not score whole-part resemblance when non-interface geometry is unconstrained.

*Fitted concept alternatives*

Support alternatives such as:

* rigid cradle versus compliant cradle;
* snap retention versus friction retention;
* open frame versus full case;
* single-piece versus multi-piece construction.

They share the external object and mandatory interface constraints.

**Explicit exclusions**

Do not:

* require a full scanned object when published dimensions and analytic geometry are sufficient;
* require a dedicated metrology agent for every fitted job;
* treat a third-party reference design as the only valid shape;
* hide unresolved measurement conflicts by averaging them silently;
* require a formal tolerance profile for a job that supplied none;
* implement formal constructs no fixture has needed;
* generate many fitted alternatives without user or planning justification.

**Primary fixtures**

*Pixel 7 case*

* published Pixel 7 dimensions as geometric truth;
* authentic photos and request;
* downloaded working case as private interface reference;
* scraped phone mesh used only as a visual envelope.

*Berlingo gear knob*

* authentic caliper measurements;
* documented measurement correction;
* physical jam feedback;
* design-stage reference status.

*Garmin dock and D30 broom holder*

* lighter fitted regression cases;
* variant-selection coverage.

**User-visible improvement**

Users can request cases, docks, knobs, adapters, holders, clips, and replacement parts that are assessed against the object they must fit.

They may also compare materially different retention or construction strategies without duplicating the mating-object reconstruction.

**Authentic exercise**

Perform:

* one live blind Pixel 7 case design;
* optionally two retention alternatives;
* one Berlingo correction iteration.

After review, capture the results as L1 replay fixtures.

## Release 8 — Multi-part and moving assemblies

**Outcome**

The skill can represent, build, branch, and assess assemblies whose correctness depends on relationships and motion between components.

**Dependencies**

Requires Releases 3, 5, and 6.

It may follow or precede Release 7 after those dependencies, based on actual project priority.

**Scope**

*Assembly representation*

Support:

* component identities;
* parent assemblies;
* local transforms;
* fixed and moving components;
* material and print assignments;
* meaningful assembly states.

Component identity remains stable across alternatives where the same physical concept remains.

*Three kinds of movement*

Separate what has until now been one concept:

* **operating motion** — how the finished product moves in use;
* **assembly motion** — the path a component travels while the product is built;
* **disassembly or service motion** — the path a component travels while being accessed, adjusted, replaced, or removed.

They are assessed against different requirements. A drawer that must slide through 40 mm of travel forever and a lid that must clear a boss once during assembly are not the same obligation, and a part can satisfy one while failing the other.

Assembly and service motion are evaluated in the assembly state the operation model establishes. This is where the operation identities carried dormant since Release 3 first do work.

Support:

* sequence-aware collision checks, evaluated in the state the sequence produces rather than only in the finished state;
* insertion accessibility for tools, hands, and the component itself;
* required intermediate poses;
* prerequisite components that must already be present;
* the resulting assembly state of each operation;
* irreversible operations, and which later assembly options they remove.

*Motion representation*

Initially support:

* prismatic motion;
* revolute motion;
* threaded or helical motion where practical;
* discrete assembly and operating poses.

Each motion defines:

* participating components;
* permitted degrees of freedom;
* travel;
* starting and terminal poses;
* intended contact;
* forbidden interference;
* stops;
* retention;
* assembly and disassembly path.

*Motion assessment*

Evaluate:

* full declared travel;
* static fit;
* dynamic clearance;
* intended friction or contact;
* collisions;
* stops;
* retention;
* assembly feasibility.

Use deterministic pose sampling and bind results to:

* geometry;
* motion definition;
* alternative identity;
* tool and sampling version.

*Mechanism alternatives*

Support alternatives such as:

* sliding drawer versus hinged lid;
* snap stop versus screw stop;
* printed hinge versus metal pin;
* one-piece compliant mechanism versus multi-part assembly.

Comparative assessment distinguishes:

* mandatory motion success;
* manufacturing complexity;
* component count;
* assembly burden;
* physical uncertainty.

**Explicit exclusions**

Do not:

* build a general rigid-body physics simulator;
* infer mechanism intent merely from separate bodies;
* claim friction performance from geometry alone;
* require an operation sequence for an assembly whose parts go together in any order;
* treat an assembly path as evidence about operating motion, or the reverse;
* reuse motion results across geometrically different alternatives without reassessment.

**Primary fixture**

Use the Pixel 9 Pro XL sliding drawer case:

* case shell;
* sliding drawer;
* two buttons;
* four watertight meshes;
* declared prismatic drawer motion;
* tight friction-fit intent;
* working third-party reference;
* phone envelope derived from published dimensions.

**User-visible improvement**

Users can design and assess:

* drawers;
* sliders;
* hinges;
* clamps;
* threaded mechanisms;
* retained multi-part devices.

They can preserve competing mechanism concepts and return to a fallback after physical testing.

**Authentic exercise**

Run:

1. an L1 reference replay;
2. a live blind sliding-case design or adaptation;
3. an intentionally defective variant with a mid-travel jam;
4. optionally a second mechanism alternative if it is genuinely plausible.

## Release 9 — Unified manufacturing, physical feedback, and alternative selection

**Outcome**

All supported design types produce consistent FDM deliverables, and real print outcomes can change the preferred alternative without erasing previous work.

**Continuous requirement**

Basic FDM awareness is required in every earlier release.

This release unifies and hardens the behavior rather than postponing manufacturing until the end.

**Scope**

*Manufacturing model*

Support per-job, per-alternative, per-component, per-body, per-region, per-interface, and per-feature intent for:

* printer;
* material;
* process;
* nozzle;
* build envelope;
* orientation;
* support, including soluble and breakaway support material;
* strength direction;
* minimum features;
* fit compensation;
* surface priority;
* print order;
* assembly order;
* coupons.

An assignment inherits from its enclosing scope. A single-material job still states its material once.

*Vertical slices*

The multi-material and sequencing work lands here, as slices rather than as a subsystem:

* per-body and per-region material assignment;
* inter-material interface intent;
* multi-material print preparation;
* rigid plus flexible components in one product;
* soluble and breakaway support interfaces;
* print pauses and embedded inserts;
* separately printed materials joined after printing;
* post-processing operations;
* operation-plan execution and resumption;
* calibrated differential compensation;
* calibration-scope tracking;
* coupons where calibration is unavailable;
* physical outcomes bound to material, orientation, process, and operation history.

Take them in the order real jobs need them. Each is a slice with its own L0 tests, its own replay, and its own authentic exercise; none of them is a prerequisite for a single-material job to run exactly as it does today.

*Compensation and calibration*

Compensation becomes computable, and stays bounded by what was actually measured.

* a compensation value derives from a calibration or is recorded as provisional;
* a calibration records the printer, material brand and formulation, nozzle, orientation, slicer settings, and process conditions it was taken under;
* applying it outside that scope is refused, not extrapolated;
* required finished geometry is never rewritten — compensation produces manufacturing geometry beside it;
* where no relevant calibration exists, the interface keeps its requirement, the allowance is recorded as an assumption, and a coupon or physical test is required before the fit can be claimed.

*Manufacturing assessment*

Evaluate, where supported:

* build envelope;
* topology;
* minimum thickness;
* holes and gaps;
* bridging and overhang implications;
* support regions;
* orientation-sensitive strength;
* material and nozzle mapping;
* component separation;
* inter-material interface clearances and their compensation basis;
* feasibility and accessibility of each declared operation;
* assembly sequence.

*Packaging*

Produce consistent:

* editable source;
* neutral CAD where supported;
* production meshes;
* generic 3MF;
* multi-material packages carrying per-body material identity;
* selected slicer-specific packages;
* print notes;
* the operation plan, where one exists;
* assembly notes;
* required coupons and physical tests.

Generated structured files must be independently re-imported and checked, and a re-import must recover the material assignments the writer put in.

`design-tool package` is the verb ADR 0001 promised and nothing implements. It lays parts out, emits spec-clean OPC, writes vertices at round-trip precision, and applies the certified-export rule from Release 6 to its own output: it feeds what it wrote back through `diagnose` and fails when the classification, the body count or any per-part volume has moved. A packager that cannot verify its own output is a writer with a claim attached, and the current one is worse than that — it formats vertices with `%.6g`, moving them by up to 0.0005 mm and changing a part's volume in the second decimal, and its round-trip self-check has never executed in the shipped runtime ([`docs/defects.md`](docs/defects.md) D2, D3).

*Physical outcome model*

Record outcomes such as:

* not printed;
* print failed;
* printed;
* fit too tight;
* fit too loose;
* fit passed;
* motion jammed;
* motion passed;
* retention failed;
* coupon printed and measured;
* insert seated or failed to seat;
* support released cleanly or damaged the part;
* bond or weld held or failed;
* load tested;
* user-confirmed working.

Bind the outcome to:

* artifact identity;
* job revision;
* alternative identity;
* printer;
* material;
* process;
* nozzle;
* orientation;
* relevant slicing conditions;
* the operation history that produced the tested object;
* tested external object.

An outcome missing any of these cannot later be reused as calibration.

*Feedback-driven branching*

Physical feedback may:

* revise the current alternative;
* create a correction branch;
* restore a previously paused alternative;
* change the preferred alternative;
* motivate a merge of successful features.

The original failed artifact and outcome remain preserved.

*Comparative physical evidence*

Alternative comparison incorporates physical outcomes without flattening them into software scores.

Examples:

* one concept is easier to print but fails retention;
* another uses more material but passes fit testing;
* a third remains untested and therefore has incomplete evidence.

**Explicit exclusions**

Do not:

* infer universal printer compensation from one successful part;
* transfer a calibration across printers, material formulations, nozzles, orientations, or slicer settings;
* invent a shrinkage coefficient to fill a gap in the data;
* collapse physical outcomes into software status;
* automatically declare one alternative universally superior;
* require large private project files in the main repository;
* delete failed or non-preferred alternatives that still have learning value.

**User-visible improvement**

The skill can respond coherently to:

* "this printed and works";
* "the hole is too tight";
* "the drawer jams halfway";
* "the clip broke along the layers";
* "the TPU gasket does not seal";
* "the magnet dropped out of its pocket";
* "go back to the screw version";
* "combine the snap geometry from option A with the reinforced body from option B."

**Authentic exercise**

Prepare and, where practical, test packages for:

* the vent mount;
* the Pixel 7 case;
* the Pixel 9 sliding assembly;
* a simple deterministic bracket;
* at least one pair of retained alternatives.

Record the physically proven vent mount and Berlingo failure without flattening their different evidence classes.

For the multi-material and sequencing slices, cover a small representative set rather than every combination:

* a rigid body with a TPU gasket or other compliant component;
* a soluble or breakaway support interface;
* an embedded magnet, nut, or heat-set insert loaded during a print pause;
* two separately printed materials joined with a controlled fit.

Do not run all four if a later one teaches nothing the earlier ones did not. Choose the smallest set that covers the distinct semantics — a compliant interface, a sacrificial interface, a paused-insert operation, and a cross-material clearance — and record which semantics each one actually exercised.

## Release 10 — Simplification, interchangeability, and stable product

**Outcome**

The repository becomes one coherent product rather than a collection of migration layers.

**Scope**

*Simplification*

Remove:

* deprecated project formats;
* deprecated command paths;
* duplicate planning authorities;
* route-specific implementations replaced by capability composition;
* dead schemas;
* obsolete adapters;
* duplicated role instructions;
* transitional status formats;
* linear-history assumptions superseded by the revision graph.

Retain compatibility only where it still serves active users and has a defined removal date.

*Capability interfaces*

Define stable boundaries for replaceable:

* AI providers;
* judgment contexts;
* CAD kernels;
* mesh engines;
* importers;
* renderers;
* motion solvers;
* slicers;
* storage;
* benchmark scorers.

Each implementation reports:

* supported capabilities;
* version identity;
* determinism;
* unit and tolerance behavior;
* which tolerance profiles and constructs it can evaluate;
* which manufacturing processes and materials it can prepare;
* resource expectations;
* limitations.

Fallback must be explicit and may not silently weaken claim strength. There is no silent fallback for a material, a process, a compensation value, a standards profile, or a tolerance construct.

*Revision-storage conformance*

Any supported storage implementation must preserve:

* immutable history;
* shared ancestry;
* sibling alternatives;
* alternative-specific artifacts;
* explicit merges;
* dependency-aware invalidation;
* preferred and paused dispositions.

*Documentation alignment*

Align:

* `README.md`;
* `SKILL.md`;
* `ARCHITECTURE.md`;
* `ROADMAP.md`;
* ADRs;
* CLI help;
* schemas;
* examples;
* current benchmark documentation.

*Release qualification*

Run:

* full deterministic suite;
* full L1 replay suite;
* bounded L2 blind suite;
* alternative-exploration fixtures;
* clean-clone install;
* packaged-skill install;
* cross-platform path tests;
* performance baselines;
* selected real physical workflows.

Qualify, and publish the result:

* the documented list of supported tolerance profiles and editions;
* a conformance fixture for every supported formal tolerance construct;
* explicit limitation or rejection of every unsupported construct, demonstrated by a fixture that declares one;
* validated operation-plan serialization and resumption;
* independent re-import of multi-material packages by something other than the writer;
* no silent material, process, compensation, standard, or tolerance fallback anywhere in the product;
* backend conformance for the tolerance and operation semantics each backend claims.

**User-visible improvement**

The skill has:

* one supported job model;
* one command surface;
* one planning authority;
* one result model;
* first-class alternative exploration;
* clear capability limits;
* replaceable providers and backends;
* documentation that matches reality.

**Exit criteria**

The full architectural vision is reached when all major mission use cases work through the same coherent product and no known architecture-level limitation is hidden behind a successful claim.

## 5. Continuous tracks

These are active throughout all releases.

### 5.1 Benchmark ladder

**L0 — component fixtures**

Run on every commit.

Protect:

* parsing;
* transforms;
* planning;
* acceptance authority;
* state invalidation;
* branch isolation;
* alternative inheritance;
* context isolation;
* deterministic comparison;
* tolerance semantics and unsupported-construct reporting;
* separation of requirement from compensation;
* material assignment inheritance and scoped invalidation;
* operation dependencies and resulting states;
* serialization.

**L1 — replay**

Run on pull requests and before merge.

Cover:

* original design;
* alternative formulation;
* alternative comparison;
* modification;
* combination;
* fitting;
* multi-part assemblies;
* motion;
* multi-material assignment and inter-material interfaces;
* operation plans and their resumption;
* manufacturing packaging;
* physical feedback transitions.

No live AI call occurs.

**L2 — blind live evaluation**

Run on demand and before significant releases.

Use a small number of authentic jobs to measure:

* request interpretation;
* design judgment;
* metrology;
* evidence use;
* correction behavior;
* meaningful alternative formulation;
* comparative reasoning.

Reviewed L2 runs should become L1 fixtures when legally and practically possible.

### 5.2 Learning record

Every authentic exercise produces a compact learning record containing:

* job and artifact identities;
* alternative identities;
* shared ancestry;
* tested capability;
* expected result;
* observed result;
* physical evidence;
* alternative comparison;
* preferred or rejected disposition;
* new defect or limitation;
* classification of the discovery;
* action taken;
* roadmap impact;
* architecture impact.

The format should remain lightweight enough that it is actually used.

### 5.3 Performance

At every release:

* preserve deterministic fast paths;
* measure cold and warm costs;
* cache stable expensive work;
* prevent accidental dispatch growth;
* keep new checks capability-triggered;
* share common work across alternatives;
* report cost per alternative;
* report cost regressions explicitly.

### 5.4 Security and isolation

At every release:

* treat imported CAD and archives as untrusted;
* validate paths;
* prevent traversal and symlink escape;
* isolate private benchmark answers;
* constrain generated-code execution;
* enforce process, memory, and time limits;
* isolate alternative artifact namespaces;
* prevent one alternative from reading private reference answers or overwriting siblings.

### 5.5 Licensing and privacy

At every release:

* record artifact licenses;
* separate vendored and external material;
* avoid committing private projects by default;
* verify immutable evidence hashes;
* keep redistributable and internal benchmark sets separable;
* ensure branched alternatives inherit licensing and privacy restrictions correctly.

### 5.6 Documentation truthfulness

At every release:

* document current support;
* document current limits;
* remove invalidated claims;
* distinguish generated, assessed, reviewed, printed, and physically proven results;
* distinguish supported branch storage from supported automatic alternative generation;
* distinguish tolerance constructs that can be declared from those that can be evaluated;
* distinguish a calibrated compensation from a provisional allowance.

## 6. Dependency rules

The roadmap may change, but these dependencies are mandatory:

* stable evidence precedes review-dependent workflows;
* candidate-independent acceptance precedes successful custom claims;
* the revision graph precedes broad alternative-dependent capability expansion;
* branch isolation precedes persistent A/B exploration;
* multi-source representation precedes multi-source preservation;
* a declared region disposition precedes any preservation verdict over that region;
* recorded datum provenance precedes any claim that rests on the datum;
* bounded repair precedes modification of an artifact diagnosis classified `REPAIR_REQUIRED`;
* a certified export precedes any claim about the artifact that export produced;
* deterministic comparison precedes strong preservation, interface scoring, comparative geometry scoring, and motion-contact claims;
* explicit component and interface semantics precede motion;
* lightweight explicit tolerancing precedes any formal tolerance profile;
* a supported comparison method precedes any conformance claim about a tolerance construct;
* per-body material identity precedes inter-material interface obligations;
* an operation model precedes sequence-aware assembly assessment;
* measured calibration precedes any applied compensation value;
* physical outcomes precede generalized calibration;
* stable capability semantics precede backend interchangeability;
* transitional paths are removed only after their replacement has been exercised on real jobs.

A narrow capability-liveness repair may move earlier.

A non-blocking rigor improvement should not delay a useful vertical slice unless the current output would be misleading.

## 7. Replanning checkpoints

A formal roadmap review occurs after Releases 2, 4, 6, 8, and 9.

At each checkpoint:

1. review authentic-job outcomes;
2. review performance and AI cost;
3. review alternative-exploration cost;
4. review benchmark gaps;
5. identify recurring manual work;
6. identify abstractions introduced for only one fixture;
7. identify concepts a single real job had to hand-build because the model could not express them, and check whether a second job has since needed the same one — a hand-built workaround is evidence of a gap only after it recurs, and until then it belongs in that project's record;
8. identify branches that added no useful learning;
9. evaluate whether comparison criteria reflect actual user decisions;
10. decide whether the next release remains the highest-value step;
11. revise later roadmap sections as needed.

Once a release has introduced tolerance, material, or sequencing semantics, the checkpoint also asks:

* Did formal tolerancing prevent a real ambiguity, or only add notation?
* Was the lightweight profile sufficient for the jobs that were actually run?
* Did the operation model improve manufacturability, or only add bookkeeping?
* Did multi-material compensation use a calibration relevant to the conditions it was applied under?
* Did any of these capabilities increase cost for jobs that did not use them?
* Does a recurring real requirement justify expanding the supported formal semantics — and is there a fixture that would fail without it?

An answer of "no material difference" is a reason to stop expanding that capability, not a reason to try harder.

Release order after Release 6 is deliberately flexible:

* fitting may precede motion;
* motion may precede fitting;
* a manufacturing blocker may be pulled forward;
* a newly demonstrated authority defect stops dependent work;
* a high-value real project may justify a narrow alternative-comparison feature earlier.

The roadmap should optimize the next useful learning step, not preserve its numbering.

## 8. Architecture-change triggers

The roadmap should not amend `ARCHITECTURE.md` merely because implementation is difficult.

An architecture change is justified when real evidence shows that:

* a recurring design concept cannot be represented;
* branch or merge semantics cannot preserve authority;
* the proposed authority boundary cannot work;
* an invariant prevents an important legitimate use case;
* a logical layer must own responsibility assigned elsewhere;
* proportional cost cannot be achieved under the current decomposition;
* comparative assessment cannot distinguish mandatory correctness from preference.

An architecture change should include:

1. the demonstrated case;
2. the failed assumption;
3. the proposed revision;
4. affected invariants;
5. affected roadmap releases;
6. new regression evidence.

## 9. Full-vision completion criteria

The roadmap is complete when the skill can, through one coherent user experience:

* produce a simple known part quickly without AI design work;
* produce a novel editable design in one ordinary design context;
* preserve and explore materially different alternatives;
* compare alternatives against shared requirements and explicit trade-offs;
* select a preferred alternative without deleting useful fallbacks;
* merge successful elements while preserving provenance and invalidating affected evidence;
* diagnose STEP, STL, and 3MF without false repair claims;
* repair a supplied artifact where an edit needs it, and record what the repair changed and which claims rest on it;
* modify supplied geometry while preserving declared regions, with a verdict per region and its declared disposition;
* certify that an exported artifact carries what was claimed about the geometry it came from;
* combine multiple source artifacts with source-specific obligations;
* design parts that fit real objects using appropriate evidence;
* express ordinary tolerances explicitly without industrial GD&T ceremony;
* accept a supplied formal tolerance under its declared profile, or say plainly that it cannot;
* create and assess multi-part moving assemblies;
* assign materials and processes where they belong and state what each inter-material interface still owes;
* express and resume a manufacturing sequence with pauses, inserts, and post-processing;
* prepare consistent FDM deliverables;
* incorporate real print and fit feedback into later revisions;
* restore or revise alternatives after physical failure;
* resume interrupted work without stale or mismatched evidence;
* use context and AI calls proportional to actual need;
* distinguish software, judgment, preference, print, and physical evidence;
* improve through fast fixtures, replay, and bounded blind runs;
* replace providers and geometry implementations without changing core job meaning;
* remain understandable enough that new work does not recreate parallel authorities.

Completion is not the existence of every planned subsystem.

It is demonstrated reliable performance across the major real use cases, with proportional cost, honest limitations, meaningful alternative exploration, and a learning loop that measurably improves later work.
