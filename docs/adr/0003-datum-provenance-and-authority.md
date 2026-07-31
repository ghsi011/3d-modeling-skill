# ADR 0003 — A datum is evidence with a provenance and a scope

Status: accepted, 2026-08-01
Amends: [`ARCHITECTURE.md`](../../ARCHITECTURE.md) §6.4 (datums and coordinate
systems), §6.5 (provenance), §13.4 (dependency binding).
Extends: [ADR 0002](0002-route-and-contract-authority.md) §2, which said the
artifact being judged may not write the standard it is judged by. This ADR says
the same thing about the geometric reference that standard is written against.

## The sentence this whole design serves

> Nothing becomes authoritative by being hand-written and named. A shared
> geometric reference carries the artifact revision it was taken from and the
> scope in which it is valid, or it is a recorded assumption with an outstanding
> check.

## Context: one file, two jobs, and three bosses that must not exist

A two-part commission — a phone case and its card drawer, modified together to
replace a printed detent with magnetic retention — coordinated two edit scopes
through a single hand-authored `datum.json`. The agent brief that set the job up
gave that file blanket precedence: *datum.json wins*.

One of its fields had been derived from the drawer **before** the drawer was
modified. It sat beside fields derived from the case **after** the case was
modified. Nothing in the file, and nothing in the model behind it, recorded that
difference.

The consequences, in ascending order of how much luck was involved:

* The two jobs read the file independently. Neither could tell that the field it
  trusted described a part the other job had already changed.
* The file was silently rewritten mid-job. Under its revision 1 a correct part
  would have been reported as failing. Nothing recorded that a rewrite had
  happened and nothing was invalidated by it.
* Following the stated precedence rule, the compliant action was to build three
  bosses that must not exist. Only an out-of-band human correction stopped it.

The last of those is the finding. A rule that made the wrong part the *compliant*
one is not a near miss; it is a standard pointing the wrong way, and the only
control that caught it was a person who happened to be looking.

## What was actually wrong

Not the rule. `ARCHITECTURE.md` never says a hand-authored datum is
authoritative — "datum.json wins" was written in an agent brief. The architecture
has no position on datum precedence at all, and that is a different failure with
a different remedy.

| section | what it says | why it did not catch this |
|---|---|---|
| §6.4 datums | a datum is "a named reference a dimension is measured from" | says nothing about where the datum itself came from |
| §6.5 provenance | every dimension keeps where it came from, and conflicting values stay separate until deliberately resolved | applies to dimensions; a datum is not one |
| §13.1 immutable history | corrections produce revisions rather than silently rewriting prior evidence | was violated by the mid-job rewrite, and nothing detected it |
| §13.4 dependency binding | lists the inputs a result is bound to | does not list datums, so changing one invalidates nothing |
| §8.2 authority boundary | the candidate may not redefine the criteria used to accept it | the datum is not the candidate — it sat upstream of both jobs |

So this is a **missing domain concept** carrying the severity of an authority
defect, not an **invalid architectural assumption**. The distinction decides the
action, which is why it is worth being exact about. An invalid assumption stops
dependent work and revises the architecture before anything continues. A missing
concept amends the architecture, records an ADR, and revises the dependent
roadmap items. There is no architectural rule here to withdraw; there is one to
write.

Dependent work does not stop, and not because the finding is mild. Every job that
declares an edit scope already reports `EXPERIMENTAL_UNAVAILABLE` rather than a
successful status, so the lane that would have shipped this part is already
barred from claiming success. What this ADR adds is an obligation that must be
met **before that cap lifts**, not after it.

## Decision

### 1. A datum carries provenance

A datum records where it came from, using the same provenance classes §6.5
already defines for dimensions: stated by the user, inherited from an immutable
artifact, measured from supplied evidence, taken from a published specification,
chosen through engineering judgment, derived from another constrained value, or
measured from generated geometry.

A datum with no recorded provenance is an assumption. It may still be used — the
alternative is a job that cannot start — but it is named as an assumption, it
carries an owner, and it carries the check that would settle it.

### 2. A derived datum names the revision it was derived from

Where a datum is derived from geometry, it names the artifact **and the revision
of that artifact** it was measured on. A datum measured on an artifact before an
edit is valid against that revision. It is not silently valid against the result
of the edit, and a job that uses it against a later revision is using a stale
reference, which is a condition that can be detected rather than a mistake that
has to be noticed.

This is the field that failed. It was correct, and it was correct about a part
that no longer existed.

### 3. A datum carries a validity scope

A datum states what it may be used to place: which artifacts, which components,
which interfaces, and — where a manufacturing or assembly operation changes the
geometry it refers to — up to which operation. §6.12 already requires evidence to
carry the scope it was taken in, and a datum is evidence.

### 4. A shared datum is one object, referenced

Coordinated edit scopes that must agree on a reference name the same datum
identity. They do not each hold a copy. Two copies of a number are two
authorities over one declaration, and the second one to be corrected is the one
that ships.

### 5. A datum is a dependency binding

Datums join the §13.4 binding list. A datum change produces a new revision,
invalidates exactly the results that depended on it, and is visible in history.
There is no silent rewrite, which is what §13.1 already required of every other
piece of evidence and what nothing enforced for this one.

### 6. No precedence rule outside the authoritative model

"This file wins" is not a property a file can be given by the brief that
introduces it. Precedence between a datum and other evidence is a property of the
authoritative job model: a datum with recorded provenance and an in-scope
revision is usable directly; a conflict between a datum and a measurement stays a
conflict until it is deliberately resolved, exactly as §6.5 requires for
dimensions.

A hand-authored shared reference is legitimate and is often the only way two
coordinated jobs can agree at all. What it does not get is blanket authority over
evidence that was measured.

### 7. What this does not decide

Nothing here requires a formal datum reference frame, a datum-feature precedence
order, or any construct from a formal tolerance profile. §6.4's ordinary datum —
a named reference with, now, a provenance and a scope — remains the normal path,
and the formal elaboration stays present only when a job declares it.

## Consequences

* `ARCHITECTURE.md` §6.4 gains provenance, validity scope, shared identity and
  binding for datums; §6.5's conflict rule is stated to cover them; §13.4 lists
  them among the bindings.
* [`ROADMAP.md`](../../ROADMAP.md) Release 5 carries the declaration obligation,
  because that is where coordinated multi-artifact edit intent is declared.
  Release 6 carries the invalidation obligation, because that is where a `MODIFY`
  job may claim success.
* A job whose datum has no provenance is not refused. It reports an assumption,
  and the assessment that rests on it says which datum it rested on.
* The existing `EXPERIMENTAL_UNAVAILABLE` cap on edit-scope jobs is the reason
  nothing has to stop today. It is also the thing that may not lift until a datum
  can carry the provenance and binding above.

## Rejected alternatives

**Classifying this as an invalid architectural assumption and stopping dependent
work.** The architecture stated no rule that was shown wrong; the rule that was
shown wrong lived in an agent brief. Stopping dependent work is the remedy for a
trust boundary that cannot hold, and there is nothing here to stop that the
edit-scope cap has not already stopped. Filing it that way would also lose the
actual lesson, which is that a document may be silent in a place where silence is
read as permission.

**Forbidding hand-authored datums.** The hand-authored file was the only thing
that let two coordinated jobs agree on anything. The defect was unbounded
authority, not authorship.

**Making the datum file immutable.** One of its fields was wrong. Immutability
would have frozen the wrong number and forced the correction to arrive as a
second file, which is the two-authorities problem with extra steps. §13.1's
answer — a correction is a new revision that invalidates what depended on the old
one — is already the right one and simply did not reach datums.

**Validating the datum file against a schema.** A schema can require a field to
be a finite number in millimetres. It cannot tell anyone that the number was
measured on the drawer before the drawer was modified. Only provenance can, and
the failure here was entirely a provenance failure — every field was
well-formed, and one of them was well-formed about the wrong part.

**Deriving every datum automatically from the source artifacts.** Attractive, and
it would have prevented this specific incident. It also assumes the reference a
job needs is always recoverable from geometry the job already has, which is false
for anything mating with a real object that has not been measured yet. Automatic
derivation is a good default where it applies; it is not a substitute for
recording where a number came from.
