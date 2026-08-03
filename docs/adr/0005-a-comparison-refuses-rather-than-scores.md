# ADR 0005 — A comparison refuses rather than scores

Status: accepted, 2026-08-03
Supersedes: nothing. Decides the shape of `design-tool compare`, the first
slice of Release 4, and the four open questions
[`docs/release-4-scope.md`](../release-4-scope.md) left unresolved.

## The sentence this decision serves

> Setting two formulations beside each other is an act that asserts something.
> A comparison's first job is to be right about what it asserts, and its second
> is to say what it could not reach. Choosing is a third thing, it belongs to a
> person, and the record has to carry their name.

## Context

Release 4 is *alternative formulation and comparative assessment*. Everything
the release needs in order to *record* an alternative shipped in Release 3: the
`Alternative` row with several parents, seven dispositions that each change
behaviour, per-formulation directories, per-formulation cost, derived status.
What did not exist is any module that compares two of them.

Two things were established before this decision was taken, and both moved it.

**The scoping document was audited rather than believed.**
`docs/release-4-scope.md` was written by one agent in one pass and had never
been reviewed. Its citations were checked one by one; most held, and three did
not survive in the form they were written. The audit is recorded in
[`ROADMAP.md`](../../ROADMAP.md) Release 4 rather than repeated here.

**The measured case against building anything at all was taken seriously.** An
independent reading of the recorded three-formulation knob found that 44 of
about 46 frozen per-formulation fields are identical across all three
formulations; that `INCOMPARABLE_CHECK_SETS`, the verdict the scoping calls the
whole point, cannot fire on any committed fixture; that the one measurement that
discriminates — solid volume — is printed by no command and frozen in no
recording; and that eleven of the facts a comparison would print are already
side by side in `design-tool status --json`. Its conclusion was that the slice
is worth about thirty lines inside an existing loop and not a verb.

That reading is right about the facts and wrong about what they mean, and the
reason it is wrong is the decision below.

## Decision

### 1. The defect is not that the formulations are similar. It is that "similar" was never measured

The 44-of-46 finding is not evidence that the knob's formulations are
equivalent. It is an artifact of how each one was graded. On the authored lane a
formulation's own `design_proposal.json` sets the declared feature set, the
`expected_bbox_mm` and `expected_bodies` the always-present checks measure
against, and — through the declared magnitude — each feature's tolerance band.
Every formulation is graded against a rubric it wrote for itself, and
`docs/defects.md` D25 records this with its three faces.

So on the recorded case, live and with nothing constructed: the root declares
`bbox_mm.z = 50.0`, `plate-seated` declares `52.0`, each is checked against its
own declaration to a band of 0.5, and both are recorded `PASS`. A report that
prints `envelope PASS` beside `envelope PASS` tells a reader the two are equal
on size. They are 2 mm apart by design, and that difference is the whole point
of the fork.

Identical PASS columns across differently-specified contracts are not evidence
of equivalence. They are the signature of self-grading. A command whose first
output is *"these three PASSes are not the same PASS"* is not reprinting
`status`; it is contradicting the conclusion a reader would otherwise draw from
it.

This also answers the strongest objection on its own terms. `INCOMPARABLE_CHECK_SETS`
indeed cannot fire on any committed fixture — but it is one of three faces of
D25, and `INCOMPARABLE_EXPECTATIONS` fires on the authentic case today.

### 2. A verb, not fields on `status`

`design-tool status` answers *where does this job stand*. `design-tool compare`
answers *what does setting these formulations beside each other establish, and
what does it not*. Folding the second into the first would put the
`not_compared` block, the rubric verdict and the requirement-digest caveat
inside a command whose job is something else, and would make `status` a
cross-formulation authority. That is the duplicate-planning-authority shape
[ADR 0001](0001-one-project-one-cli.md) and Release 10 exist to remove.

The two commands share their reading layer rather than their conclusions:
`compare` calls `status.derive` over `bindings.broken`, the same pair `status`
uses, and re-adjudicates nothing.

### 3. There is no score, no weight and no order

`ARCHITECTURE.md` 8.5 forbids a weighted score hiding a mandatory failure. The
guarantee here is structural rather than careful: there is no weighted score.
`comparison.json` carries `ranking: null` and `score: null` as fields, and
formulations are a JSON **object keyed by id and never an array**, because an
array has an order and an order reads as a ranking.

`preference.admissible` is false — with the reason named — when any formulation
did not pass its own mandatory checks, when the rubrics disagree, or when a
dimension the job turns on cannot be measured at all. The measurements are still
printed in full in every one of those cases: withholding a number somebody took
would be its own dishonesty. What is withheld is the licence to read them as a
reason.

Choosing stays with `design-tool branch --disposition`, which records who chose
and on what basis. A comparison that also chose would be a second authority over
one decision, and the one with no person's name on it.

### 4. The rubric verdict scopes to the axis, not to the comparison

Refusing the *whole* comparison because the mandatory axis is unusable would
destroy the evidence axis — which is computable however badly two contracts
disagree, and is where a stale sibling is reported. 8.5 requires comparative
results to distinguish mandatory pass-or-failure from preference criteria from
incomplete evidence from subjective choice; one verdict standing for all four is
the same collapse the rule forbids, run backwards.

### 5. `MODIFY` pairs are in, and this overrules the scoping

The scoping proposed comparing only from-scratch formulations, on the grounds
that two `MODIFY` formulations both report `EXPERIMENTAL_UNAVAILABLE` and a
comparison between them discriminates nothing. That is true and it is not a
reason to defer them — it is a reason to include them, because deferring the
case that is hard to answer *is* Release 6 in disguise, which is exactly the
question the scoping raised and did not settle.

A comparison's job is not to discriminate. It is to say what setting two
formulations beside each other does and does not establish. On a `MODIFY` pair
the answer — *both report `EXPERIMENTAL_UNAVAILABLE`, the axis that decides
between them is preservation, preservation cannot be measured here, `docs/defects.md`
D22 and the undeclared sample density are why, and Release 6 owns it* — is a
complete and correct output. The failure mode is the opposite one: a comparison
that printed material, envelope and cost on a `MODIFY` pair and let a reader
take them as decisive.

So `not_compared` rows carry a `standing` of `DECIDING` or `CONTEXT`, a
`DECIDING` row that cannot be measured makes `preference.admissible` false, and
`pipeline/test_compare.py::AModifyPairIsReportedUnrankableTest` asserts it. That
converts a paragraph in a document into a mechanism, which is the only form in
which this decision is worth anything.

### 6. What the output may never say

The shared requirements are bound as a digest (`cli._requirement_hash`) and are
never individually checked; the contract's rows are geometric proxies a designer
chose; and no edge in this build links a project requirement to the contract row
that measures it. So the honest sentence is:

> each formulation met the contract it froze, and all of them bind the same
> requirement digest

and never *"all of them meet the requirement"*. `shared.requirement_digest` is
reported as a **binding** and never as a satisfaction, and a fixture asserts the
words that keep the two apart.

## Consequences

* The first thing a reader of a comparison learns is whether the verdicts they
  are about to read are comparable at all. On the recorded knob, they are not.
* `comparison.json` is recomputable from disk at any moment, so there is nothing
  to resume and nothing to invalidate. It records each formulation's whole
  binding map, its `bindings.identity` and the digest of every receipt it read —
  the identity covers inputs only, so a corrected `commission_report.json` would
  move the comparison with no binding broken, and the receipt digests catch that.
* Two byte-identical siblings are named as one design under two ids. On the
  recorded knob the root and `as-drawn` share a source digest, and without that
  block a reader takes their agreement for two independent designs reaching the
  same answer.
* D25 is closed for the comparison path and open for every other reader. Nothing
  stops a person reading two `commission_report.json` files side by side and
  drawing the equality themselves, and no receipt says on its face that its
  expectations were self-declared.

## Rejected alternatives

**Thirty lines inside `status`'s existing loop.** The cheapest thing that
produces the fields, and it buys them by making `status` answer two questions.
Its own strongest evidence — that eleven facts are already side by side there —
is an argument that `status` is already close to the line, not that it should
cross it. The two real defects that reading found are recorded as `docs/defects.md`
D26 and are worth fixing on their own.

**Normalising coverage so two formulations' fractions compare.** There is no
shared denominator to normalise to. `covered` is not even filtered to mandatory
features (`commission.py:437`), so the fraction is not bounded by 1.0. Any
normalisation would be inventing the comparability it claims to measure.

**A weighted total with mandatory failures excluded from the weighting.** This
is 8.5's own words read as a specification for a score that is allowed. It is
not: the rule's point is that the reader of a total cannot see what went into
it, and an exclusion they cannot see is not a protection they have.

**Deferring the slice until the requirement-to-check edge exists.** That edge is
what would let a comparison say "both meet the requirement". Without it a
comparison can still say the two things that matter today — these verdicts are
not comparable, and here is the axis nobody measured — and saying them is worth
more than saying nothing until a schema change lands.
