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
4. modification and combination do not yet have a complete multi-source design model;
5. preservation is not yet strong enough to support successful modification claims;
6. fitted authored designs and moving assemblies are not yet complete end-to-end capabilities;
7. physical outcomes and alternative comparisons are not yet part of a systematic learning loop.

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

### 3.7 Separate architectural learning from project peculiarities

After each release, classify discoveries as follows.

**Implementation defect**

The design is adequate; the implementation is wrong.

Action:

* fix the code;
* add a regression fixture.

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

**Explicit exclusions**

Do not yet attempt:

* full fitted authored work;
* full multi-source modification;
* strong preservation claims;
* universal anomaly screening for novel custom designs;
* divergent branch storage;
* automatic A/B concept generation;
* a second AI confirmation of the proposal.

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
* candidate profile data attempts to clear its own anomaly screen.

The release passes only when candidate-controlled acceptance is structurally impossible, not merely rejected by one validator.

**Authentic exercise**

Use an open-ended FDM bracket request with:

* mounting requirements;
* a keep-out;
* a build envelope;
* material and nozzle constraints;
* freedom over ribs, walls, and styling.

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
* clean-clone reconstruction of the revision graph.

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
* top-loading versus sliding enclosure.

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
* output-component inheritance.

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
* two alternatives using different donors;
* branch-local source change that does not invalidate the sibling;
* shared base-source change that invalidates both.

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
* stable serialization.

Preservation uses a staged method:

1. compare cheap structural facts;
2. locate spatially changed regions;
3. refine comparison only where required;
4. distinguish allowed changes from unexpected changes;
5. report the method and detection limit.

Report separately:

* retained source geometry;
* intentionally removed geometry;
* added geometry;
* permitted changes;
* unintended changes outside the edit region.

Exact B-rep claims are available only when an actual exact comparison backend exists.

Alternative comparisons may reuse common source indices and shared external-object analysis.

**Explicit exclusions**

Do not:

* build a universal geometric-equivalence prover;
* increase sample density uniformly over every model;
* let sampled evidence claim exact preservation;
* treat geometric closeness as proof of equal function;
* assume a sibling alternative's assessment applies to another.

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
* merged geometry requiring reassessment.

The result must state:

* comparison method;
* tolerance;
* detection limit;
* unsupported conditions;
* source-specific verdicts;
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

Support per-job, per-alternative, per-component, per-interface, and per-feature intent for:

* printer;
* material;
* nozzle;
* build envelope;
* orientation;
* support;
* strength direction;
* minimum features;
* fit compensation;
* surface priority;
* print order;
* assembly order;
* coupons.

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
* assembly sequence.

*Packaging*

Produce consistent:

* editable source;
* neutral CAD where supported;
* production meshes;
* generic 3MF;
* selected slicer-specific packages;
* print notes;
* assembly notes;
* required physical tests.

Generated structured files must be independently re-imported and checked.

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
* load tested;
* user-confirmed working.

Bind the outcome to:

* artifact identity;
* job revision;
* alternative identity;
* printer;
* material;
* nozzle;
* relevant slicing conditions;
* tested external object.

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
* resource expectations;
* limitations.

Fallback must be explicit and may not silently weaken claim strength.

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
* distinguish supported branch storage from supported automatic alternative generation.

## 6. Dependency rules

The roadmap may change, but these dependencies are mandatory:

* stable evidence precedes review-dependent workflows;
* candidate-independent acceptance precedes successful custom claims;
* the revision graph precedes broad alternative-dependent capability expansion;
* branch isolation precedes persistent A/B exploration;
* multi-source representation precedes multi-source preservation;
* deterministic comparison precedes strong preservation, interface scoring, comparative geometry scoring, and motion-contact claims;
* explicit component and interface semantics precede motion;
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
7. identify branches that added no useful learning;
8. evaluate whether comparison criteria reflect actual user decisions;
9. decide whether the next release remains the highest-value step;
10. revise later roadmap sections as needed.

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
* modify supplied geometry while preserving declared regions;
* combine multiple source artifacts with source-specific obligations;
* design parts that fit real objects using appropriate evidence;
* create and assess multi-part moving assemblies;
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
