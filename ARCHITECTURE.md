# Architecture

## 1. Purpose

This document defines the intended end-state architecture of the 3D-modeling skill.

It describes:

* the mission and architectural drivers;
* the stable domain model;
* the logical system boundaries;
* the authority and trust model;
* the execution and state model;
* the performance and cost model;
* the continuous-improvement system;
* the invariants every implementation must preserve.

It does not describe implementation phases, migration order, temporary restrictions, or release sequencing. Those belong in `ROADMAP.md`.

Architecture Decision Records may define narrower technical decisions. Schemas and tests are the executable expression of this architecture, but do not replace it.

## 2. Mission

Create a fast, accurate, reliable, and versatile 3D-modeling capability that transforms natural-language requirements—together with any available CAD files, photos, measurements, specifications, and user feedback—into editable, manufacturable designs and usable production deliverables.

The capability must support:

* original designs using supplied or appropriately chosen dimensions;
* modification, repair, and adaptation of existing CAD;
* combination of two or more existing CAD artifacts;
* parts that mate accurately with real objects;
* reconstruction from photos, measurements, descriptions, and specifications;
* multi-part and moving assemblies;
* ordinary FDM preparation.

It must use effort proportional to the difficulty, uncertainty, and consequence of the job while minimizing:

* user effort;
* execution time;
* context consumption;
* AI API usage;
* repeated work;
* unnecessary process.

Trust, verification, provenance, and benchmarking exist to improve the design and the reliability of its claims. They are supporting capabilities, not the product.

## 3. Architectural drivers

The architecture is shaped by the following priorities, in order.

### 3.1 Functional quality

The resulting design must satisfy the real task:

* dimensions must be appropriate;
* mating interfaces must fit;
* assemblies must align;
* intended motion must work;
* required geometry must be preserved;
* the part must be practical to manufacture and iterate.

A sophisticated process that produces a poor part has failed.

### 3.2 Versatility

The same skill must cover simple and complex work without splitting into unrelated products.

A job may begin from:

* no geometry;
* one or more STEP, STL, or 3MF files;
* photographs;
* caliper measurements;
* published specifications;
* a previous design revision;
* physical-test feedback;
* any combination of these.

### 3.3 Proportional effort

Simple jobs must remain fast and inexpensive.

Additional reasoning, analysis, or independent judgment is justified only when the job contains uncertainty or requirements that benefit from it.

### 3.4 Honest confidence

The system must distinguish:

* what was requested;
* what was assumed;
* what was measured;
* what was computed;
* what was judged;
* what was physically tested;
* what remains unknown.

Software checks must not be presented as physical proof.

### 3.5 Efficient iteration and exploration

The architecture must support repeated design changes and competing alternatives without:

* losing prior decisions;
* forcing one concept to overwrite another;
* accepting stale results;
* repeating unchanged expensive work;
* forcing unnecessary redispatch;
* growing context without bound.

Exploring a snap-fit concept must not require abandoning a screw-fastened concept, and comparing the two must not require reconstructing their shared history manually.

### 3.6 Replaceable implementation

The architecture must not depend fundamentally on:

* one AI provider;
* one model;
* one agent framework;
* one CAD kernel;
* one mesh library;
* one slicer;
* one storage layout.

## 4. Architectural approach

The system combines three complementary ideas.

### 4.1 Adaptive execution

Each job performs only the work required by its actual capabilities and risks.

The architecture does not require every job to pass through the same fixed sequence. Deterministic generation, custom design, evidence interpretation, preservation analysis, motion evaluation, manufacturing preparation, and independent review are composed as needed.

### 4.2 Unified design workbench

Ordinary custom design is treated as one coherent engineering task.

A single design context should normally be able to:

* understand the relevant request;
* inspect supplied artifacts and evidence;
* choose appropriate dimensions;
* create or modify geometry;
* receive measurements and diagnostics;
* revise the design;
* explore alternatives;
* prepare usable deliverables.

Additional contexts are introduced only when independence or specialization produces meaningful value.

### 4.3 Explicit design intent

Important engineering concepts are represented explicitly rather than being scattered across prompts, scripts, filenames, and prose reports.

These include:

* components;
* source artifacts;
* datums and transforms;
* dimensions, tolerances, and provenance;
* interfaces and fit;
* materials and manufacturing processes;
* permitted edits and preservation obligations;
* motion;
* manufacturing constraints;
* manufacturing, assembly, and service operations where sequence matters;
* uncertainty;
* evidence;
* design alternatives and their relationships.

The architecture does not prescribe whether this representation is implemented as a graph, relational model, document model, or another structure. It prescribes the concepts and relationships that must be expressible.

## 5. Logical architecture

The system is divided into five logical layers.

```text
┌──────────────────────────────────────────────────────────┐
│  Interaction Layer                                       │
│  Request intake · user decisions · feedback · delivery   │
├──────────────────────────────────────────────────────────┤
│  Intent and Planning Layer                               │
│  Job model · alternatives · planning · context shaping   │
├──────────────────────────────────────────────────────────┤
│  Engineering Layer                                       │
│  Design judgment · evidence recovery · manufacturing     │
├──────────────────────────────────────────────────────────┤
│  Geometry and Analysis Layer                             │
│  CAD · import/export · measurement · fit · motion        │
├──────────────────────────────────────────────────────────┤
│  Evidence and Learning Layer                             │
│  State · provenance · comparison · physical outcomes     │
└──────────────────────────────────────────────────────────┘
```

These are authority and responsibility boundaries, not necessarily separate processes or services.

A small implementation may place several layers in one process. A larger implementation may separate them. The logical boundaries remain the same.

## 6. Authoritative job model

Each job has one authoritative machine-readable model.

It represents the engineering problem, its revision history, and any active design alternatives. Execution, assessment, comparison, and status are derived from it.

The authoritative job model contains the following domains.

### 6.1 Request and decisions

The system preserves:

* the original user request verbatim;
* its structured interpretation;
* required deliverables;
* explicit priorities;
* accepted trade-offs;
* later user corrections;
* physical-test feedback;
* decisions made during the job.

The structured interpretation may evolve. The original request and user decisions remain immutable historical evidence.

A decision records its scope. A decision may apply to:

* the whole job;
* one design alternative;
* one component;
* one interface;
* one manufacturing configuration;
* one physical-test iteration.

A decision made for one alternative must not silently constrain competing alternatives unless it was declared job-wide.

### 6.2 Artifact registry

Every imported or generated artifact has a stable identity.

An artifact record includes, as applicable:

* content hash;
* format;
* units;
* coordinate system;
* component or assembly structure;
* source and placement transforms;
* provenance;
* role in the job;
* authority level;
* license and redistribution restrictions;
* relationship to other artifacts;
* revision or alternative that produced it;
* repairs applied to it, and the region each one changed.

Artifact identity is content-based. A filename or path alone is not sufficient identity.

**A repair is recorded, not absorbed.** Section 11.4 requires that a repair which changes source geometry be recorded; the record lives here. Each entry names what was wrong, the method applied, the named region it changed, what the geometry measured before and after, and whether the change was inside a region the edit intent already permitted. A repaired artifact is a distinct artifact with its own identity and its own relationship to the file it was derived from. It never replaces the supplied file, and the supplied file remains the authoritative statement of what the user handed over.

Typical artifact roles include:

* authoritative base geometry;
* donor geometry;
* mating object;
* measurement reference;
* visual envelope;
* prior revision;
* alternative candidate;
* production export.

A job may contain zero, one, or many source artifacts.

### 6.3 Components and assemblies

A component is a separately meaningful physical part or body.

It records:

* identity;
* geometric origin;
* local coordinate frame;
* parent assembly;
* material or manufacturing assignment;
* relationship to other components;
* whether it is fixed, moving, removable, replaceable, or reference-only.

A single printed object is treated as a one-component assembly. This allows single-part and multi-part jobs to use the same representation.

Component identities should remain stable across revisions when the physical concept remains the same. A component that is replaced by a fundamentally different concept may receive a new identity while retaining an explicit relationship to the component it replaces.

### 6.4 Datums and coordinate systems

Datums define stable geometric references for:

* dimensions;
* alignment;
* mating;
* preservation;
* assembly;
* measurement;
* motion.

Transforms between the following spaces must be explicit when relevant:

* source artifact;
* source component;
* design assembly;
* external mating object;
* measurement setup;
* manufacturing orientation;
* printer build space.

No geometry-dependent conclusion may silently assume two coordinate systems are identical.

An ordinary datum is a named reference a dimension is measured from. That is sufficient for most work.

**A datum is evidence, and carries what evidence carries.**

A datum records its provenance, using the same classes section 6.5 defines for dimensions. Where it is derived from geometry, it names the artifact *and the revision of that artifact* it was taken on. A datum measured before an edit is valid against the revision it was measured on; it is not silently valid against the result of that edit.

A datum records the scope it is valid in: which artifacts, components, and interfaces it may be used to place, and — where an operation changes the geometry it refers to — up to which operation.

A datum with no recorded provenance is an assumption. It may still be used, and it is named as an assumption, with an owner and with the check that would settle it. It does not acquire authority over measured evidence by being written down first. A conflict between a datum and a measurement remains a conflict until it is deliberately resolved, exactly as section 6.5 requires for dimensions.

Coordinated edits that must agree on a reference name one datum identity rather than each holding a copy. Two copies of one number are two authorities over one declaration.

A datum is a dependency binding (section 13.4). Changing it produces a new revision and invalidates the results that depended on it. It is never a silent rewrite.

The demonstrated case, the rejected alternatives, and the reasoning are in [ADR 0003](docs/adr/0003-datum-provenance-and-authority.md).

When a job uses the formal tolerance profile described in section 6.5, a datum may additionally be a datum feature, and several datum features may be combined into a datum reference frame with a declared precedence. The formal construction is an elaboration of the same concept, not a second one, and it is present only when the job declares it.

### 6.5 Dimensions, tolerances, and provenance

Dimensions remain associated with where they came from.

Common provenance classes include:

* stated by the user;
* inherited from an immutable artifact;
* measured from supplied evidence;
* taken from a published specification;
* chosen through engineering judgment;
* derived from another constrained value;
* measured from generated geometry.

Conflicting values remain separate until they are deliberately resolved.

A measured candidate value must not replace the requirement it is being measured against.

A dimension may be:

* shared by all alternatives;
* overridden by a specific alternative;
* intentionally varied across alternatives for comparison.

**Two levels of tolerance semantics**

A dimension that constrains anything carries explicit tolerance semantics. The architecture supports two profiles for expressing them, and the lighter one is the normal path.

*Lightweight explicit tolerancing*

This profile is the ordinary path for FDM work and is sufficient for most jobs.

It expresses:

* the nominal value;
* a unilateral, bilateral, or limit tolerance;
* the datum or measurement reference the value is taken from;
* the fit class or functional band the value serves;
* the measurement method, where interpretation would otherwise be ambiguous;
* provenance;
* confidence, or the uncertainty that remains unresolved.

The profile is mathematically explicit — a value, a band, and what the band is measured against — but it does not require complete industrial GD&T notation, a datum reference frame, a feature-control frame, or a material-condition modifier.

*Formal standards-based tolerancing*

A formal profile is used only when:

* the user supplies formal tolerances;
* the source engineering data requires them;
* the consequence or manufacturing context justifies them;
* interoperability with formal engineering documentation requires them.

A formal tolerance declaration identifies:

* the governing standards family or profile;
* the applicable edition;
* the specific semantic construct being used.

Examples of such families include ASME Y14.5 and applicable ISO GPS profiles. The architecture does not reproduce those standards and does not claim to implement them completely. It records which profile governs a declaration and which constructs an implementation can actually evaluate.

Where implemented, and only where implemented, the formal profile may cover:

* datum features and datum reference frames;
* features of size;
* size limits;
* tolerance zones;
* form;
* orientation;
* location;
* profile;
* run-out;
* material-condition modifiers.

Support is incremental. Being able to record a construct is not the same as being able to evaluate it.

*Rules that hold for both profiles*

* ASME and ISO semantics are never mixed implicitly; a declaration belongs to one named profile and edition.
* Proprietary meanings are never invented for standard symbols or terms.
* An unsupported formal construct is never silently approximated by a lightweight band.
* An unsupported construct is reported as an explicit limitation of the assessment, never as a pass.
* The selected profile and edition are preserved in provenance and in every assessment result that depends on them.

### 6.6 Requirement, compensation, and observed geometry

Three geometric descriptions of the same part are distinct and must not collapse into one another.

1. **Required finished-part geometry** — the tolerance-carrying description of what the finished part must be. This is authoritative.
2. **Manufacturing geometry** — the geometry actually submitted for production, after any process compensation such as printer, material, orientation, or shrinkage allowance.
3. **Observed geometry** — what a generated artifact, a print, or a measurement actually exhibits.

Compensation is a recorded transformation between the first and the second. It never rewrites the first. A part whose bore was grown 0.15 mm to print correctly still requires the original bore, and is still accepted or rejected against it.

A compensation record identifies:

* what it compensates for;
* the calibration or assumption it derives from;
* the scope in which that calibration is valid;
* the geometry, interface, or material pair it applies to;
* whether it is measured, calibrated, or provisional.

The system does not invent a compensation value. It does not assume a calibration transfers between printers, material brands or formulations, nozzles, orientations, slicer settings, or process conditions.

When suitable calibration is absent, the system:

* preserves the required finished geometry unchanged;
* records any provisional allowance as an assumption rather than as a measured value;
* exposes the resulting uncertainty;
* requires a coupon or physical test where the affected interface matters.

### 6.7 Interfaces

An interface describes how two components, or a component and an external object, interact.

An interface may define:

* participating features or regions;
* seated or operating transform;
* fit type;
* clearance or interference band;
* insertion and removal direction;
* intended contact;
* forbidden contact;
* alignment features;
* retention;
* sealing;
* keep-outs;
* critical dimensions.

External real objects are represented independently from the candidate design whenever possible.

This allows the candidate and any reference design to be assessed against the same external object without requiring whole-part similarity.

**Intended relationship**

An interface declares what the two sides are meant to do to each other, such as:

* bonded;
* mechanically interlocked;
* compliant;
* sliding;
* separable;
* sealed;
* sacrificial;
* soluble support;
* breakaway support;
* printed in place but intended to release;
* inserted during a print pause;
* assembled after printing.

The last several are as much manufacturing statements as geometric ones, which is why an interface may reference the operation that creates it (section 6.11).

**Interfaces that cross materials or processes**

An interface may join regions made of different materials, produced by different processes, or produced at different times in a manufacturing sequence.

Where the two sides differ, the interface may additionally record:

* the material and manufacturing process on each side;
* the required finished clearance or interference;
* the required contact, separation, sealing, or adhesion behavior;
* process- and orientation-dependent compensation;
* differential shrinkage or thermal uncertainty;
* the calibration source and its validity scope;
* a required test coupon;
* the physical validation the interface still needs.

A same-material, same-process interface does not carry these fields, and nothing requires a job to populate them.

The required finished clearance and any compensation applied to reach it remain separate, as section 6.6 requires. An interface whose compensation rests on no relevant calibration is not thereby relaxed; it is an interface with a recorded assumption and an outstanding physical test.

Competing alternatives may satisfy the same functional interface through different formulations, such as:

* snap-fit versus screws;
* sliding retention versus magnetic retention;
* one-piece compliant geometry versus a multi-part assembly;
* a rigid part with a separate compliant gasket versus one multi-material part.

### 6.8 Edit intent

Modification and combination use one multi-source edit model.

For every relevant source, the model may describe:

* geometry that must be preserved;
* geometry that may be removed;
* geometry that may be altered;
* geometry that must be added;
* regions where changes are permitted;
* the source transform in the shared design space;
* material, process, and component roles inherited from the source;
* output components that inherit from the source.

**Obligations attach to named regions, and a region carries one disposition.**

Each of the obligations above is stated over a named region of a named source, and every region carries exactly one of:

* **must-preserve** — nothing here may move, in either direction;
* **permitted-change** — the edit may alter this, within a declared band;
* **consumed-by-intent** — this material is deliberately removed, displaced, or interpenetrated by another part, and its disappearance is the requested result rather than a violation.

The third is not a convenience. A magnet pocket cut into a wall consumes material that a two-verdict comparison reports as a preservation failure, and a job whose largest legitimate change exceeds its largest illegitimate one cannot be judged by one global number at all. An unfiltered maximum deviation over a whole part is a measurement, not a verdict.

A region's disposition is declared before the edit and is part of the acceptance specification. Assessment reports a verdict per region and states which region each deviation fell in; a single whole-part verdict is reported only where a single whole-part obligation was declared.

Imported intent that the current job does not use is preserved rather than discarded. A donor assembly that names two materials still names them after the edit, even when the target job prints in one.

Combining two or more artifacts is therefore not a separate architectural mechanism. It is a multi-source edit with source-specific obligations.

Different alternatives may use different source selections, donor components, alignments, or edit strategies while sharing the same original job and source registry.

### 6.9 Motion

Motion is represented explicitly.

A motion definition may include:

* participating components;
* joint or motion type;
* permitted degrees of freedom;
* travel range;
* starting, seated, and terminal poses;
* intended contacts;
* forbidden interference;
* stops;
* retention;
* assembly and disassembly paths.

Multiple bodies do not imply motion unless motion is declared.

Three kinds of movement are distinguished, because they are assessed against different requirements:

* **operating motion** — how the finished product moves in normal use;
* **assembly motion** — the path a component travels while the product is being built;
* **disassembly or service motion** — the path a component travels while being accessed, adjusted, replaced, or removed.

A drawer that slides in use and a lid that must clear a boss once during assembly are not the same obligation. Assembly and service motion belong to the operations described in section 6.11 and are evaluated in the assembly state those operations establish.

Alternative mechanisms may define different motion models while satisfying the same user-level function.

### 6.10 Manufacturing intent

Manufacturing intent may apply to the whole job, a component, a body, a region, an interface, a feature, or one alternative.

It includes, as applicable:

* manufacturing process;
* printer and build envelope;
* material;
* nozzle or tool;
* orientation constraints;
* support policy and support material;
* strength direction;
* minimum features;
* fit compensation;
* surface priorities;
* print order;
* assembly order;
* required test coupons.

FDM is the first-class target process. The model should allow additional manufacturing processes without redefining the core design concepts.

**Assignment scope**

Material and process assignment applies at the narrowest scope that is actually true. An assignment may be made for:

* the job;
* a design alternative;
* a component;
* a body;
* a region within a body;
* an interface;
* a support structure.

An assignment inherits from its enclosing scope until something overrides it. A job printed in one material on one printer states that once, and every body inherits it. A rigid housing with a TPU gasket overrides the assignment for one body.

Where a job assigns more than one material or process, the interfaces between them carry the obligations described in section 6.7, and any compensation applied at those interfaces obeys section 6.6.

**Print order, assembly order, and sequence**

`print order` and `assembly order` remain adequate for jobs where nothing depends on the order beyond convenience. Where correctness depends on operations happening in a particular order, the explicit operation model in section 6.11 is used instead.

### 6.11 Manufacturing, assembly, and service operations

Some jobs are correct only if things happen in the right order, using the right tools, with the right things already in place. Where that is true, sequence is a first-class part of the design rather than a note in a report.

Sequencing is optional. A one-piece print with a single meaningful operation does not get an operation model, and nothing about a simple job becomes more expensive because the concept exists.

Three sequences are distinguished, along with one thing that is regularly confused with them.

**Manufacturing sequence** — how the part is produced. Operations include print, pause, change material or tool, insert a magnet, nut, bearing, or reinforcement, resume printing, remove breakaway or soluble support, cure, machine, heat-set, bond, weld, finish, and inspect.

**Assembly sequence** — how separately produced components are positioned and joined.

**Disassembly or service sequence** — how components are accessed, replaced, adjusted, or removed, where that matters.

**Operating motion** — how the finished product functions in normal use. Operating motion is described by section 6.9 and is not an operation. Confusing the two makes a one-time assembly path look like a function of the product.

An operation may express:

* stable identity;
* operation type;
* prerequisite operations;
* affected components, regions, materials, or interfaces;
* required pose or assembly state;
* required clearance and accessibility;
* tools and consumables;
* whether it is reversible or irreversible;
* the expected resulting state;
* the inspection or validation it requires.

Operations form a dependency graph rather than necessarily a single list. An irreversible operation constrains which later operations remain possible, and that constraint is part of the design, not a runtime surprise.

Alternatives may legitimately differ in their manufacturing or assembly sequence. That difference is a comparable engineering trade-off, assessed in section 8.5 alongside the geometry.

### 6.12 Uncertainty and evidence

Requirements and decisions may carry:

* confidence;
* supporting evidence;
* conflicting evidence;
* assumptions;
* unresolved questions;
* consequences of being wrong;
* required physical tests.

Unknown values remain unknown until evidence or an explicit engineering decision resolves them.

Evidence may apply to:

* the job as a whole;
* a shared requirement;
* one design alternative;
* one candidate revision;
* one manufacturing configuration;
* one material or process pairing;
* one calibration and the scope in which it was taken.

Evidence for one alternative must not automatically validate another. Evidence taken under one printer, material, nozzle, orientation, or process condition does not automatically transfer to another.

### 6.13 Design alternatives and branching

The authoritative model supports divergent design alternatives as first-class entities.

An alternative represents one coherent formulation of the design problem. Examples include:

* snap-fit retention;
* M3 screw fastening;
* magnetic attachment;
* one-piece compliant construction;
* multi-part pinned construction.

Each alternative records:

* stable identity;
* parent revision or parent alternative;
* reason for branching;
* assumptions or decisions that differ from its parent;
* inherited shared intent;
* alternative-specific intent;
* proposal and implementation revisions;
* generated artifacts;
* assessments;
* manufacturing implications;
* physical outcomes;
* current disposition.

An alternative may be:

* active;
* paused;
* preferred;
* rejected;
* superseded;
* retained as a fallback;
* merged into another alternative.

Branching must not duplicate all shared job information. Alternatives inherit unchanged requirements, evidence, source artifacts, and decisions from their common ancestry while recording only their differences.

The revision history is therefore logically a directed acyclic graph rather than a mandatory linear sequence.

### 6.14 Alternative comparison and selection

The system supports explicit comparison between alternatives.

Comparison may include:

* requirement satisfaction;
* interface performance;
* manufacturing complexity;
* material and process strategy;
* material use;
* print time;
* support burden;
* manufacturing and assembly sequence complexity;
* reversibility of the operations it requires;
* tooling and consumables;
* assembly effort;
* component count;
* expected strength;
* serviceability and maintainability;
* adjustability;
* uncertainty;
* physical-test results;
* user preferences.

Criteria that a job does not exercise are absent from its comparison rather than scored as zero.

Comparison criteria must be traceable to the job rather than invented solely to favor one alternative.

Alternatives may be compared while incomplete, provided the comparison identifies missing or unequal evidence.

Selecting a preferred alternative does not delete the others.

A rejected or paused alternative remains available for:

* later reconsideration;
* reuse of successful subcomponents;
* fallback if physical testing disproves the preferred option;
* benchmark and learning value.

### 6.15 Alternative merging and reuse

A later alternative may reuse or merge validated elements from earlier alternatives.

Examples include:

* retaining the interface geometry of one concept while adopting the fastening method of another;
* reusing a tested phone cradle with a new vent attachment;
* transferring a successful drawer stop into a redesigned shell.

Merged work must retain provenance showing:

* which alternative each element came from;
* which assessments remain applicable;
* which assessments became stale;
* which interfaces or assumptions changed.

The system must not assume that combining two individually successful features produces a successful combined design without reassessment of their interaction.

## 7. Intent, proposal, implementation, and observation

The architecture distinguishes four categories that must not collapse into one another.

### 7.1 Intent

Intent describes what the design must accomplish.

It originates from:

* the user;
* authoritative source geometry;
* accepted specifications;
* explicit engineering decisions.

Intent may be shared across the whole job or scoped to one alternative.

### 7.2 Proposal

A proposal describes how the designer intends to satisfy the intent.

It may include:

* selected dimensions;
* proposed features;
* component structure;
* interfaces;
* material choices;
* manufacturing strategy;
* assumptions.

A proposal is allowed to make engineering choices. It is not allowed to rewrite user requirements silently.

Each alternative may have its own proposal history.

### 7.3 Implementation

Implementation describes how the geometry is produced.

It may be:

* a parametric model;
* a procedural script;
* direct CAD operations;
* mesh operations;
* a reusable template;
* an imported artifact;
* a combination of these.

Implementation details are replaceable and must not become the sole representation of design intent.

Each implementation is bound to the alternative and proposal revision it realizes.

### 7.4 Observation

Observation records what exists in the generated or imported artifact. It is the third of the three geometric descriptions in section 6.6, and it is never the first.

Examples include:

* measured dimensions;
* body count;
* volume;
* surface condition;
* fit distances;
* detected collisions;
* achieved assembly states;
* manufacturing warnings.

Observation must not become its own expectation.

Observations from one alternative must not be reused as observations of another merely because they share ancestry.

## 8. Acceptance and assessment

### 8.1 Acceptance specification

Before candidate implementation code executes, the system freezes the criteria against which the resulting artifact will be evaluated.

The acceptance specification is derived from:

* user requirements;
* accepted design decisions;
* immutable source artifacts;
* declared interfaces;
* manufacturing policy;
* system-owned tolerance policy;
* required capability checks;
* the specific alternative being assessed.

It may contain:

* required dimensions and their tolerance semantics;
* the governing tolerance profile and edition, where a formal profile applies;
* required features;
* component structure;
* interface obligations, including inter-material obligations;
* material and process assignments;
* preservation obligations, stated per named region with that region's disposition;
* motion obligations;
* required operations and their sequence obligations;
* manufacturing constraints;
* required evidence, including coupons and physical tests;
* explicitly unavailable assessments.

The acceptance specification describes the required finished part. Process compensation is not part of it; a candidate is judged against what the part must be, not against what was sent to the printer.

Where a declared tolerance construct cannot be evaluated by any available comparison method, the specification records it as an explicitly unavailable assessment. It is never quietly downgraded to a band that happens to be checkable.

Shared requirements may generate equivalent acceptance obligations for several alternatives. Alternative-specific decisions may produce different valid acceptance specifications.

### 8.2 Authority boundary

The candidate implementation must not silently redefine the criteria used to accept its output.

Candidate implementation executes within a boundary that cannot mutate the authoritative job model, execution plan, acceptance specification, assessment implementation, or final-status authority. The boundary may be a separate process, a restricted declarative runtime, or another mechanism that establishes the same property.

A separate namespace is not by itself such a boundary. The property required is that the candidate *cannot* perform the mutation, not that it is observed to have performed one:

* the candidate's authority must be reduced by the platform, not by convention — a peer process with the same user, the same filesystem rights and no lifetime bound is a different namespace and the same privilege;
* the boundary must bound the candidate's *lifetime*, not only its call. Anything the candidate starts must be dead before the authoritative process reads what the candidate produced;
* assessment inputs must be re-read, validated and hashed by the authoritative process after the boundary is closed, and receipts, status and authoritative project state must be created only there;
* integrity checking of the authoritative process's own code may be kept as a canary and must not be counted toward this property. It reports a compromise that has already had its effect.

A confinement bounds what the candidate can *do*. It does not bound what the candidate can *say*, because the boundary exists in order for build results to cross it. So the evidence a reviewer is given is a separate obligation:

* no text the candidate authored may appear in any payload a reviewer receives. A reviewer's decision is an authority over the run, and a party that can address the decider is a party that can argue its own case — which is the acceptance-authority defect in a different medium. Read access to the acceptance specification does not create this channel; it aims it, because a candidate that knows the bands can argue in their vocabulary.
* the property must hold by construction rather than by inspection. A value the candidate composed must have no field, parameter or attribute on the path to a reviewer payload; where a candidate-supplied value is genuinely needed, it crosses as a token validated against a vocabulary the authoritative side owns, and the authoritative side supplies the words. Filtering candidate text for suspicious content is not this property: it is a check, and a check can be removed, mis-ordered or skipped on one path.
* what the candidate declared is still recorded, in an artifact no assessment and no review consumes. Suppressing it would make a designer iterate against a declaration nothing reads.

Where a required property cannot be established by the available mechanism, it is recorded as a named limitation of the boundary with the mechanism that would close it. It is not quietly dropped, and the boundary is not weakened elsewhere to compensate.

A designer may propose dimensions and features before evaluation.

After seeing a failed result, changing the proposal is a legitimate new design revision. It must be visible and must invalidate results that depended on the previous revision.

A normal custom job may produce both its proposal and implementation within one AI context. Establishing the proposal as the current basis for assessment does not inherently require a second AI call.

Creating an alternative is not a mechanism for silently weakening acceptance. Differences from the parent or sibling alternatives must be explicit.

### 8.3 Assessment

Assessment compares observations against the acceptance specification.

It should prefer direct evidence:

* named dimensions and their declared bands;
* declared features;
* explicit interfaces;
* source-specific preservation;
* defined motion;
* declared operations and the states they produce;
* manufacturing constraints.

Broad heuristics may supplement direct checks but must not issue stronger conclusions than their calibration supports.

Assessments are bound to:

* the candidate artifact;
* the alternative;
* the proposal revision;
* the acceptance specification;
* the tolerance profile and edition in force;
* the material, process, and compensation assumptions in force;
* the relevant source and tool identities.

### 8.4 Claim strength

Every result must state only what its method established.

Examples:

* an exact representation comparison may establish exact identity;
* a deterministic distance comparison may establish equivalence within a tolerance;
* sampled comparison may establish preservation only down to a stated detection limit;
* a visual review may identify plausibility or visible defects;
* a supported tolerance construct may be reported as satisfied only by a method that implements its semantics;
* a successful print may establish printability for the tested conditions;
* a printed coupon may establish a clearance for the material, printer, orientation, and settings it was printed under, and for no others;
* a physical fit test may establish fit for the tested object and part;
* a comparison over one named region may establish that region's obligation and no other's;
* a measurement taken on repaired geometry establishes something about the repaired artifact, and states the repair it rests on.

A weaker method must never produce a stronger claim.

A claim also inherits the scope of what it was measured over. Preservation established for one named region says nothing about a region with a different obligation, and a claim resting on geometry that was repaired inside region R is a claim about a part that was repaired inside region R.

A declared formal construct that the comparison engine cannot evaluate produces an explicit limitation, never a conformance claim. A part that was never printed has no compensation evidence, whatever allowance its manufacturing geometry carries.

### 8.5 Comparative assessment

Comparing alternatives is distinct from accepting them individually.

An alternative may satisfy all mandatory requirements yet be less desirable because it:

* requires more hardware;
* is harder to print;
* uses more material;
* needs a second material, tool change, or print pause;
* is harder to assemble;
* requires an irreversible operation that forecloses later repair;
* is harder to service;
* has greater uncertainty;
* performs worse in physical testing.

Comparison dimensions that a job does not exercise are not scoring categories for it. A single-material one-piece print is not penalized for having no assembly sequence.

Comparative results must distinguish:

* mandatory pass or failure;
* preference criteria;
* incomplete evidence;
* subjective user choices.

No weighted score may hide a mandatory failure.

## 9. Execution planning

The authoritative job model is compiled into an execution plan.

The plan determines:

* required capabilities;
* dependency order;
* reusable prior work;
* required engineering judgment;
* required deterministic analyses;
* required manufacturing, assembly, and service operations;
* required coupons, calibrations, and physical tests;
* resource budgets;
* stopping conditions;
* deliverables;
* which alternatives are active;
* which work can be shared across alternatives;
* which comparisons are requested.

The execution plan is a derived artifact, not an independent source of intent.

There is one planning authority for a job revision. Runtime components must not independently reinterpret the job into competing plans.

Named routes or workflow profiles may exist as planning conveniences. They are policy summaries, not permanent domain concepts.

### 9.1 Planning alternative exploration

Alternative exploration should be intentional rather than an accidental multiplication of candidates.

The planner may create or request multiple alternatives when:

* the user requests options;
* several materially different concepts are plausible;
* uncertainty makes early commitment expensive;
* physical consequence justifies comparing concepts;
* a previous concept fails;
* a benchmark explicitly tests design exploration.

The planner should avoid creating alternatives when:

* differences are merely cosmetic;
* one approach clearly dominates under established constraints;
* the additional AI and geometry cost is unlikely to change the decision.

### 9.2 Shared work across alternatives

The planner should share unchanged work such as:

* source parsing;
* mating-object reconstruction;
* published specifications;
* printer profiles;
* common interface definitions;
* immutable source indices;
* benchmark-private setup.

Alternative-specific work remains isolated.

This allows concept exploration without multiplying all job cost.

## 10. Context management

Context is an expensive resource.

The system must prepare the smallest sufficient context for each judgment task.

A context package may contain:

* the relevant portion of the request;
* unresolved design intent;
* necessary source artifacts;
* relevant dimensions, tolerances, and evidence;
* the governing tolerance profile and edition, when one is in force;
* material and process assignments relevant to the decision;
* the operations the decision depends on;
* current failures and measurements;
* manufacturing constraints;
* required deliverables;
* the active alternative and its differences from its parent;
* sibling summaries when comparison is required.

It should exclude:

* unrelated project history;
* unused role instructions;
* private benchmark answers;
* stale results;
* large raw reports when a lossless structured summary is sufficient;
* artifacts unrelated to the decision;
* tolerance, material, or operation detail the decision does not depend on;
* complete sibling-alternative histories when a comparison summary is sufficient.

The context boundary must preserve identifiers and provenance so that compact context does not become ambiguous context.

A design context working on one alternative must not accidentally modify or reinterpret another alternative.

## 11. Engineering capabilities

The architecture exposes composable capabilities rather than one monolithic workflow.

### 11.1 Request interpretation

* preserve the authentic request;
* identify the actual functional objective;
* structure requirements and constraints;
* identify missing information;
* avoid asking questions whose answers can be derived reliably.

### 11.2 Source diagnosis

* parse supported CAD and mesh formats;
* resolve document roots and component references;
* preserve units and transforms;
* recover assembly structure;
* characterize actual geometry;
* distinguish damage from unsupported structure;
* avoid modifying the source during diagnosis.

### 11.3 Original design

* create novel parametric or procedural geometry;
* choose appropriate unspecified dimensions;
* create editable source;
* account for manufacturing constraints during design;
* create materially different alternatives when justified.

### 11.4 Modification and repair

* import authoritative source geometry;
* preserve required regions;
* limit changes to permitted regions;
* repair only when necessary;
* record when repair changes source geometry.

### 11.5 Combination

* align multiple source artifacts;
* select retained and removed donor geometry;
* establish interfaces between sources;
* produce one or more output components;
* retain source-specific provenance.

### 11.6 Evidence reconstruction

* interpret photos;
* reconcile caliper readings;
* use published specifications;
* establish datums;
* preserve confidence and conflicts;
* incorporate later physical-test feedback.

### 11.7 Interface engineering

* define mating geometry;
* establish fit classes and bands;
* assess insertion, seating, and retention;
* represent interfaces that cross materials or processes;
* keep the required finished clearance separate from any compensation applied to reach it;
* derive mating regions from the shared external object where practical;
* avoid constraining unrelated styling or structure.

### 11.8 Assembly, motion, and sequence

* manage multiple components;
* define joints or permitted motion;
* evaluate travel;
* detect forbidden interference;
* assess intended contact;
* assess stops, retention, and assembly paths;
* distinguish operating motion from assembly and service motion;
* express manufacturing, assembly, and service operations where order matters;
* assess accessibility, required intermediate poses, and prerequisite components;
* identify irreversible operations and what they foreclose.

### 11.9 Manufacturing preparation

* evaluate build volume;
* account for orientation and strength;
* identify support implications;
* assess minimum features;
* assign materials and processes at the scope where they apply;
* map components to materials and tools;
* plan multi-material, insert, and post-processing operations;
* apply compensation only from calibration valid for the actual conditions;
* prepare production artifacts;
* state required coupons and the physical tests still required.

### 11.10 Alternative generation and comparison

* create divergent concepts from a shared job state;
* isolate alternative-specific decisions and artifacts;
* reuse shared evidence;
* compare alternatives against common mandatory requirements;
* compare trade-offs without hiding incomplete evidence;
* select, pause, reject, merge, or revisit alternatives;
* preserve non-selected alternatives for later use and learning.

### 11.11 Independent judgment

Independent judgment may be introduced when justified by:

* ambiguous evidence;
* difficult metrology;
* consequential failure;
* complex motion;
* subtle preservation requirements;
* competing design alternatives;
* an explicit user request.

It is a capability, not mandatory ceremony.

## 12. Geometry and analysis runtime

The geometry runtime provides replaceable backends for:

* solid modeling;
* mesh modeling;
* boolean operations;
* import and export;
* normalization;
* measurement;
* rendering;
* interface analysis;
* tolerance and fit evaluation;
* preservation analysis;
* motion analysis;
* assembly-state analysis;
* manufacturing analysis.

A backend reports which tolerance constructs it can evaluate. A construct no available backend implements is an explicit limitation of the job, not a silently relaxed requirement.

Comparison must be able to distinguish required geometry from compensated manufacturing geometry, so that the two are never measured against each other by accident.

Backend choice must be explicit when it can affect results.

Substitution must not silently change:

* units;
* transforms;
* topology interpretation;
* boolean semantics;
* tolerance meaning;
* artifact identity;
* claim strength.

Geometry execution must operate under resource limits and fail in a controlled, diagnosable manner.

Alternative candidates must execute in isolated artifact namespaces so that one candidate cannot overwrite another.

An authored implementation receives only the inputs required to build its artifact. It does not execute inside the mutable authority context that performs acceptance or assessment.

## 13. State, revision, branching, and invalidation

### 13.1 Immutable history

Original inputs, accepted user decisions, imported artifacts, completed revisions, and alternative branches remain historically traceable.

Corrections produce new revisions rather than silently rewriting prior evidence.

History is not required to be linear.

### 13.2 Revision graph

The job history is logically a directed acyclic graph.

A revision may have:

* one parent for an ordinary continuation;
* one shared ancestor with sibling alternatives;
* multiple contributing parents when concepts are deliberately merged.

The implementation may use any storage mechanism capable of preserving these relationships. It is not required to expose Git semantics to the user.

### 13.3 Alternative lifecycle

An alternative may be:

* created from the current preferred design;
* created from an earlier revision;
* developed independently;
* compared with siblings;
* selected as preferred;
* paused;
* rejected;
* superseded;
* merged;
* restored later.

Changing the preferred alternative does not erase the previously preferred one.

### 13.4 Dependency binding

Every generated artifact and assessment is bound to the inputs capable of changing it.

These may include:

* job revision;
* alternative identity;
* parent revision;
* source hashes;
* transforms;
* datums and the shared references coordinated work agrees on;
* design proposal;
* acceptance specification;
* tolerance profile and edition;
* material and process assignments;
* compensation assumptions and the calibration behind them;
* operation sequence;
* manufacturing policy;
* toolchain identity;
* analysis parameters.

A binding that a job does not use does not participate in its identity.

### 13.5 Invalidation

When a binding changes, dependent results become stale.

Unrelated valid results remain reusable.

A change to a tolerance profile, a material assignment, a compensation assumption, or an operation sequence invalidates the results that depend on that change and nothing else. Reassigning one body's material does not invalidate an interface both of whose sides are unchanged.

A change limited to one alternative must not invalidate sibling alternatives unless they depend on the changed shared input.

A shared requirement, source artifact, or mating-object change may invalidate several alternatives.

### 13.6 Resumption

Interrupted jobs may resume from the last valid state.

Resumption must not:

* inherit stale success;
* accept a review against different evidence;
* reuse an artifact against changed acceptance criteria;
* repeat unchanged expensive work unnecessarily;
* resume the wrong alternative;
* overwrite sibling-alternative artifacts.

### 13.7 Determinism

Deterministic capabilities must produce stable evidence for unchanged inputs.

When deterministic output cannot be guaranteed, the source of variation must be explicit and must not break ordinary resumption.

## 14. Result model

Results should not collapse distinct evidence into one overloaded status.

The result model should expose separate facets.

### 14.1 Artifact production

* editable source produced;
* candidate produced;
* production export produced;
* manufacturing package produced.

### 14.2 Geometric integrity

* readable;
* non-empty;
* units resolved;
* transforms resolved;
* component structure characterized;
* topology characterized.

### 14.3 Requirement assessment

* dimensions assessed;
* tolerances assessed, naming the profile and the constructs actually evaluated;
* tolerance constructs declared but not evaluable;
* features assessed;
* interfaces assessed, including inter-material obligations;
* preservation assessed, per named region and its disposition;
* repairs applied, and which assessments rest on repaired geometry;
* motion assessed;
* operations and sequence assessed;
* manufacturing constraints assessed.

### 14.4 Judgment

* design judgment completed;
* independent judgment completed;
* unresolved judgment required.

### 14.5 Physical evidence

* not printed;
* coupon printed and measured;
* printed;
* physically fitted;
* motion tested;
* assembled through the planned sequence;
* load tested;
* user-confirmed working.

A physical result names the printer, material, nozzle, orientation, process conditions, and operation history it was obtained under. Without those, it cannot be reused as calibration.

### 14.6 Alternative disposition

For each alternative, the result model may record:

* active;
* preferred;
* paused;
* rejected;
* superseded;
* retained as fallback;
* merged.

The disposition must include its basis, such as:

* user selection;
* mandatory requirement failure;
* manufacturing disadvantage;
* physical-test result;
* unresolved evidence;
* replacement by a stronger concept.

A basis is required by every disposition except the one a formulation starts in, and is drawn from a closed vocabulary rather than written freely, so that the answer is comparable across jobs. A disposition recorded without one says that somebody decided and not what they decided on, which is the same amount of information as no disposition at all.

A disposition that asserts a relationship to another alternative — superseded by, merged into — names that alternative, and a merge is accepted only where the revision graph records it as a contributing parent. A state nothing in the graph supports is a label.

### 14.7 Alternative comparison

Comparison results should show:

* mandatory requirement status for each alternative;
* differentiating trade-offs;
* evidence completeness;
* physical outcomes;
* uncertainty;
* user-selected preference.

Software assessment, independent judgment, alternative preference, and physical validation remain distinct.

## 15. Performance and cost model

Performance is a product requirement, not merely an implementation detail.

### 15.1 Proportional cost

A simple job must not inherit the cost of capabilities it does not use.

The intended common behavior is:

* no AI call when deterministic reusable work completely covers the task;
* one coherent design context for ordinary custom work;
* additional AI calls only when they add material value.

Optional semantics stay dormant. Formal tolerance profiles, multi-material assignment, compensation records, and operation sequencing cost nothing for a job that declares none of them — no extra dispatch, no extra analysis, no extra context. A capability that makes simple jobs more expensive because it exists has been implemented wrongly.

Exact timing and dispatch targets belong in benchmark documentation.

### 15.2 Alternative-exploration cost

Alternative exploration is intentionally more expensive than producing one design, but the cost must remain proportional.

The system should:

* share common source analysis and evidence;
* avoid repeating identical context;
* limit the number of simultaneous alternatives;
* stop dominated alternatives when justified;
* preserve paused alternatives without continuing to spend resources on them;
* record incremental cost per alternative.

The architecture does not require generating several alternatives for every job.

### 15.3 Incremental recomputation

Results are cached and reused when their complete dependency bindings remain valid.

Cache identity must include every input capable of changing the result, including alternative identity and inherited shared state.

### 15.4 Expensive imports

Expensive source parsing and normalization should be reusable across:

* repeated runs;
* design iterations;
* alternative branches;
* assessment stages;
* benchmark replays.

Raw imports must still be exercised often enough to detect importer regressions.

### 15.5 Resource control

Geometry operations execute with explicit limits for:

* wall-clock time;
* memory;
* process count;
* file size;
* geometric complexity;
* output size.

A failed operation must not destabilize the host machine.

### 15.6 Cost visibility

The system records enough information to identify:

* AI dispatch count;
* context size;
* deterministic runtime;
* import cost;
* cache reuse;
* repeated work;
* failed work;
* per-alternative incremental cost.

An architectural change must not conceal increased cost behind a successful output.

## 16. Continuous improvement

The skill improves through explicit retained evidence, not through implicit model training.

A curated case may contain:

* authentic request;
* permitted evidence;
* source artifacts;
* one or more design proposals;
* alternative relationships;
* editable design sources;
* production artifacts;
* structured requirements;
* interface definitions;
* assessments;
* comparative decisions;
* physical outcomes;
* failures and corrections;
* privacy and license metadata.

### 16.1 Component fixtures

Small deterministic fixtures test individual capabilities quickly.

Examples include:

* file parsing;
* unit handling;
* transforms;
* route or plan compilation;
* interface measurement;
* preservation comparison;
* state invalidation;
* branching and alternative isolation.

### 16.2 Replay fixtures

Recorded engineering outputs are replayed through the current system without a live AI call.

Replay tests protect:

* planning;
* proposal handling;
* artifact generation;
* measurement;
* assessment;
* state transitions;
* branching;
* alternative comparison;
* packaging.

### 16.3 Blind live evaluation

A limited set of authentic requests is periodically given to a design context without access to the reference answer.

Live evaluation measures capabilities that replay cannot:

* request interpretation;
* geometric judgment;
* metrology;
* design choices;
* alternative formulation;
* use of feedback.

Useful live results can become future replay fixtures.

### 16.4 Scoring modes

Open-ended original designs are scored on:

* requirement satisfaction;
* manufacturability;
* structural integrity;
* appropriate behavior of the system.

They are not scored on resemblance to one reference shape.

Fitted, modified, and combined designs may additionally be scored on:

* mating-interface agreement;
* fit-band satisfaction;
* preservation;
* required component structure.

Moving assemblies are scored on:

* interfaces;
* travel;
* contact;
* stops;
* retention;
* forbidden interference.

Multi-material and sequenced work may additionally be scored on:

* correct material and process assignment;
* inter-material interface treatment;
* honest handling of missing calibration;
* feasibility and completeness of the declared operation sequence;
* accessibility of insert and service operations.

Alternative-exploration tasks may additionally be scored on:

* meaningful conceptual diversity;
* preservation of shared requirements;
* explicit trade-offs;
* evidence-aware comparison;
* avoidance of superficial variants presented as distinct concepts.

### 16.5 Request-answer separation

Benchmark request material and private reference answers are structurally separated.

The design context must not be able to access:

* reference geometry;
* private scoring annotations;
* recorded successful outputs;
* withheld physical-test results.

This separation is enforced by the data loader and execution environment, not only by instructions.

### 16.6 Repository boundaries

The main repository may contain:

* architecture and schemas;
* tooling;
* compact redistributable fixtures;
* benchmark manifests;
* reusable design patterns;
* selected owner-controlled artifacts.

Large, private, copyrighted, or non-redistributable corpora may remain external and be referenced by stable identity and hash.

Not every completed design or alternative belongs in the repository. Retention is based on expected learning and regression value.

## 17. Extensibility

The architecture must allow replacement or addition of:

* AI providers and models;
* agent frameworks;
* CAD kernels;
* mesh engines;
* importers;
* renderers;
* motion solvers;
* slicers;
* manufacturing processes;
* tolerance profiles and the constructs supported within them;
* storage backends;
* benchmark scorers.

Provider-specific details remain behind capability boundaries.

No core job concept should depend exclusively on one implementation technology.

A storage backend is conformant only if it can preserve:

* immutable history;
* divergent alternatives;
* shared ancestry;
* alternative-specific artifacts;
* explicit merges;
* dependency-aware invalidation.

## 18. Architectural invariants

Every implementation must preserve the following.

1. There is one authoritative job model.
2. The original user request remains preserved and traceable.
3. Artifact identity is content-based.
4. Units, datums, coordinate systems, and transforms are explicit.
5. Tolerance semantics are explicit, and a formal tolerance declaration names its profile and edition.
6. Standards families are never mixed implicitly, and a tolerance construct that cannot be evaluated is reported as a limitation rather than approximated.
7. Required finished-part geometry is never rewritten by manufacturing compensation.
8. A calibration applies only within the scope in which it was obtained.
9. Material and process assignments are explicit at the scope where they apply, and inherited elsewhere.
10. Sequenced operations are explicit wherever correctness depends on order, and are not required otherwise.
11. Planning has one authority for a job state.
12. Runtime components do not silently re-plan the job.
13. Intent, proposal, implementation, and observation remain distinct.
14. Candidate output cannot silently redefine its acceptance criteria.
15. Acceptance criteria are frozen before candidate implementation code executes and remain outside the candidate's mutable authority.
16. Modification and combination support multiple source artifacts.
17. Preservation obligations are source-specific.
18. Imported material, process, and sequence intent is preserved rather than silently discarded.
19. Components, interfaces, motion, and declared operations are first-class concepts.
20. External mating objects remain independent from candidate geometry where practical.
21. Divergent design alternatives are first-class and may coexist.
22. Exploring one alternative does not overwrite or invalidate unrelated alternatives.
23. Shared ancestry and alternative-specific differences remain traceable.
24. Selecting a preferred alternative does not delete the others.
25. Merging alternatives preserves provenance and triggers reassessment of affected interactions.
26. Expensive capabilities and AI calls are triggered by job requirements.
27. Alternative exploration is bounded and shares valid common work.
28. Ordinary custom work does not require unnecessary context handoffs.
29. Context is minimized without losing decisive evidence or provenance.
30. Unchanged valid work can be reused.
31. Changed bindings invalidate dependent results, and unused bindings do not participate in identity.
32. Deterministic methods produce stable evidence for unchanged inputs.
33. Review responses are bound to the evidence they reviewed.
34. A weaker method cannot issue a stronger claim.
35. Benchmark answers are inaccessible to the design context.
36. Software assessment never silently implies physical validation.
37. Unsupported and uncertain conclusions remain explicit.
38. Optional semantics stay dormant for jobs that do not declare them.
39. Simple jobs remain fast.
40. Candidate implementation cannot mutate or replace planning, acceptance, assessment, or final-status authority.

## 19. Non-goals

The architecture does not aim to:

* formally prove arbitrary physical designs correct;
* replace physical testing where physical behavior matters;
* require complete GD&T representation for every ordinary part;
* reproduce or redistribute the content of a copyrighted standard;
* implement every construct of every tolerancing standard;
* invent shrinkage or compensation coefficients where no relevant calibration exists;
* simulate the manufacturing process;
* require an operation model for a one-step print;
* force every job through one workflow;
* require multiple agents;
* require one persistent agent;
* generate multiple alternatives for every job;
* preserve every unsuccessful experiment forever;
* encode every CAD operation in a universal intermediate language;
* prescribe one correct shape for an open-ended problem;
* reward whole-part resemblance when only an interface is constrained;
* retain every user project;
* support every possible CAD or slicer format;
* eliminate engineering judgment where evidence is genuinely ambiguous;
* maximize receipts, checks, alternatives, or process independently of design quality.

## 20. Definition of architectural success

The architecture is successful when:

* a simple, fully specified part can be produced quickly and cheaply;
* a novel part can be designed coherently in one ordinary workflow;
* materially different concepts can be explored without discarding their shared history;
* competing alternatives can be assessed against common requirements and explicit trade-offs;
* a preferred concept can be selected without deleting useful fallback options;
* successful elements from different alternatives can be combined with preserved provenance;
* supplied STEP, STL, and 3MF files can be diagnosed without false repair claims;
* imported geometry can be modified without unintended changes;
* multiple source artifacts can be combined with explicit ownership and preservation;
* a part can be designed to fit a real object using appropriate evidence;
* a multi-part assembly can be evaluated across its declared motion;
* ordinary dimensions carry explicit tolerances without industrial GD&T ceremony;
* a supplied formal tolerance is either evaluated under its declared profile or reported as unsupported;
* a part combining rigid and compliant materials records what each interface requires and what still needs a coupon;
* a part that must be printed, paused, insert-loaded, and resumed can express that sequence and be assessed against it;
* ordinary FDM constraints are addressed without overwhelming simple jobs;
* editable source and production exports remain traceable;
* uncertainty and required physical testing are communicated honestly;
* interrupted work can resume without stale results or unnecessary repetition;
* selected real projects and explored alternatives measurably improve future performance;
* those improvements do not bloat every job's context, runtime, or AI usage.
