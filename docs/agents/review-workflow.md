# 3D Modeling Review Workflow Guide

**Purpose:** minimize time-to-trustworthy-result without weakening correctness, authority, or feedback loops.

## 1. Core operating rule

**Measure → narrow → rule → implement → falsify → preserve → synchronize → verify → review → merge → QA.**

Prefer a narrow measured improvement with an explicit remaining limitation over a speculative general solution.

## 2. Authority and merge discipline

- Claude implements; reviewer rules; user retains permission authority where explicitly reserved.
- Never bypass, weaken, widen, or relocate around a gate unless the repository's documented seam actually applies and required user permission exists.
- Merge only when the exact PR head has green hosted CI, reviewer approval names that head, the PR body is current, and no permission blocker remains.
- Final review should be boring: no new architecture questions.

## 3. Evidence model

Every implementation should separate four proofs:

1. **Reproduction:** the defect or bottleneck exists.
2. **Cause:** the measured mechanism explains it.
3. **Regression:** the fix prevents that mechanism from returning, preferably mutation/adversarially.
4. **Preservation:** unrelated behavior and explicit non-scope remain unchanged.

Counts and snapshots are corroboration, not proof of preservation.

## 3a. Measurement discipline

A measurement is a claim about the world and inherits none of the authority of the code
that produced it. Five errors in a single document, all one shape — **a plausible inference
written down in the grammar of a measurement** — produced these rules. Each is mechanical,
because "be careful" has already failed.

**Two methods for a load-bearing measurement, or it is an anecdote.** A measurement is
load-bearing when something rests on it: a claim, an acceptance threshold, a disclosure from
a withheld reference, a fit or safety decision — or when the method is itself suspect or
disputed. Those are not reported until a second method sharing no assumption with the first
agrees. Where the two disagree, **report the disagreement** rather than silently selecting a
survivor; only what survives both may be stated as fact.

Ordinary diagnostic and corroborative numbers ship from **one validated method**, with their
provenance and their uncertainty. Requiring a second instrument for every figure would cost
more than it protects, which §7's proportional rule already forbids: the question is always
whether the check shortens time to a *trustworthy* result, and for a number nothing rests on
it does not.

*Evidence:* a bore was measured three ways and gave thread depths of 0.48, 2.08 and 4.51 mm
per flank; the first was published as fact before the others existed. That figure was
load-bearing — a fixture's expected value rested on it. Only the median diameter survived
all three, and it is the only one that shipped.

**A filter is a suspect, not a convenience.** Before filtering data ahead of a measurement,
state what the filter can reject and prove it cannot reject the phenomenon being measured.
*Evidence:* rings were filtered to near-circular ones (`std/mean < 0.06`) and the surviving
ripple was reported as the thread profile — a filter defined to reject threads, measuring
threads. This is the same failure as an instrument that cannot observe what it reports, and
it reads exactly like a clean result.

**Every number carries its provenance.** One of `PUBLISHED` (a public source, named and
checkable), `MEASURED` (by whom, how, and how many independent methods), `INFERRED` (a
standard, a convention, a memory) or `TESTED` (a physical result). A number with no tag does
not ship, and `INFERRED` may never appear in a column headed *source*. *Evidence:* a
standard code and its diameter were asserted in a sourced table with nothing behind either.

**A disclosure needs a public source, not a plausible one.** When a document deliberately
withholds a reference, every disclosed fact must name where an unprivileged reader learns
it. If that cannot be pointed at, the fact is a leak however reasonable it sounds.
*Evidence:* "a keeper reading the product page knows both" — the page stated one of the two,
and the other had been measured from the withheld reference.

**Physical result outranks measurement, which outranks publication, which outranks
inference.** Where two sources conflict, say which won and why, rather than presenting the
survivor alone.

**Provenance is not sufficiency, and this is the one that survived the rules above.** A
fact can be impeccably `PUBLISHED` and still be a leak, because provenance answers *where
did this come from* and never *does stating it hand over the solution*. The two questions
are independent and both must be asked. *Evidence, found by an independent auditor after
the five rules above were written:* a brief withholding a reference disclosed a "hive wall
opening: 11 x 20 mm" under a heading declaring such facts to be "properties of the world
the part must join, not of any particular solution". Hive bodies do not come with an
11 x 20 mm hole. The keeper cuts one **because this product's instructions say to**, so the
figure is the reference's own chosen pass-through, published — and every candidate is then
forced through the tongue the reference invented. The provenance tag was correct and the
categorisation was wrong, which is why tagging alone does not save a document.

The test that separates them: *would this constraint exist if the reference had never been
designed?* If it exists only because the reference exists, it is a solution, whatever
public page it now appears on. The same auditor found the corrected number retained under a
new justification — the excuse had changed and the leak had not, so **check that a
correction removed the fact and not merely its rationale**.

## 3b. Discriminating evidence

§3a governs a *measurement*. This governs the *instrument*, and it exists because a joint
post-mortem found one failure underneath six separate incidents:

> **An instrument that passes while asking a different question from the claim resting on
> it.**

It covers a citation guard whose probes proved the pattern still worked while the corpus was
the fix; a concurrency probe whose "hang" was an event the searcher never triggered; a
missing-name finding for a name the library never binds; a defect reported fixed because a
fabricated path was not a listable directory; an unread page paraphrased into a requirement;
and a DNS row that could not pass on the machine that ran it. **Optimise for preventing
false evidence, not for accumulating more of it.**

**Write the discriminating observation before the implementation.** For every regression,
control, probe, benchmark or protection, state:

> *This proves **X** because it changes or fails when **Y** changes.*

`Y` must be a plausible broken implementation: the old implementation, a missing call, a
bypass at the call site, an empty corpus, a leaked authority. **If the instrument gives the
same answer with `Y` broken, it is not evidence for `X`.** The full causal mechanism need
*not* precede the code — instrumenting is often how a mechanism is found — but the question
the instrument must discriminate does.

**A control owes the same proof as a regression.** A clean control means nothing unless it
observes the same property, through the same relevant path, as the arm it controls. *"There
was a control"* is not sufficient. One control here computed a different field from its
experimental arm and was therefore clean for a reason unrelated to the code, which turned
an artefact into a reported finding.

**Do not swap the question for a nearby one.** An instrument made deterministic by measuring
something adjacent has not been repaired; it has been quietly redefined. Where no
proportional way exists to observe the original property, **narrow the claim honestly** —
rename the row, synchronise every dependent statement, and leave the original fact
explicitly unproven rather than replaced by a measurement that resembles it.

*Evidence:* a probe pinned to a hostname that did not resolve on its own machine was
replaced with one that always resolves locally. That removed the network as a variable and
also stopped exercising the service route the row existed to observe — so a future boundary
could close that route with the row still green. The negative arm proved the test rejected
network-dependent names; it proved nothing about what the surviving arm measured.

## 3c. When the ruling channel fails

A review channel can become unavailable mid-slice — a thread reaching its limit, a rate
limit, an outage. Silence then looks exactly like agreement, which is the shape every rule
in this file exists to refuse.

* say once that the channel is unavailable, and **stop at the next ruling boundary**;
* **silence is never approval**, and a green suite is not a substitute for a ruling;
* a replacement channel opens with a handoff carrying exact `main`, every open PR and its
  head SHA, hosted CI state, the last valid ruling, the decision pending, and the queue;
* **never merge on a ruling that cannot be recovered exactly.** A ruling naming an earlier
  head has expired.

## 4. State synchronization rule

After every material change ask:

> **What statements, tests, manifests, counts, comments, docs, roadmap entries, changelog entries, or PR claims depended on what I just changed?**

Then update and re-verify every affected representation immediately.

**PR bodies are durable prose about the current head.** Any material new SHA or changed claim requires the PR body to be synchronized in the same action.

**Sweep the dependants, not the string.** Grepping for the old value finds where it was
written; it does not find the sentences that rested on it. After changing a fact, re-read
every section that *reasoned from* it. *Evidence:* a corrected interface was updated in the
table that declared it while the acceptance criterion testing that same interface still
named the superseded one — one document, two answers, found by a reader rather than by the
grep that had just been run over it.

## 5. Gate/tier decision rule

When a gate blocks work, do not assume either "impossible" or "move it elsewhere." Re-read the gate contract:

1. What property is the gate protecting?
2. What cases are explicitly outside it?
3. Does this work naturally cross that seam, or would moving it merely evade the constraint?

Tier by behavior, not by available headroom.

## 6. Test and refactor preservation

For structural moves, compare a **semantic inventory**, not only assertion or line counts:

- collected test IDs
- classes/functions/helpers
- referenced constants/fixtures
- skip conditions
- mocks/patch targets
- assertions and mutation coverage

A moved test must still exercise the same behavior at its new tier.

## 7. Performance optimization rule

**Profile with time; regress with structure.**

Use wall-clock measurements to find dominant cost. Then test the causal property whenever possible rather than a noisy millisecond threshold.

Examples: a non-geometry CLI import should not load the mesh stack; a valid cache hit must prevent the expensive build from executing.

Run cheap, high-information checks first; expensive geometry/build/replay only after uncertainty is narrowed.

## 8. Real-use QA loop

Use small, diverse blind/real-use samples as discovery instruments:

**small sample → inspect misses → form one measurable hypothesis → improve one seam → rerun.**

Prefer breadth before repetition. Do not add descriptors or machinery until an observed failure mode earns them.

## 9. Review-request formats

### Discovery / ruling request

- **Current state:** main/head and relevant gate state.
- **Observed:** measured reproduction and dominant mechanism.
- **Invariant:** what must remain true.
- **Decision needed:** one narrow question or blocker.
- **Not started:** confirm work has stopped at the ruling boundary.

### Final review request

- exact head SHA
- current diff/scope
- exact-head hosted CI run + all conclusions
- targeted/mutation/L0/L1/heavy evidence as applicable
- collection/gate impact
- golden/schema status
- permission status
- **PR body synchronized with this exact head**

Do not retell the whole development history unless it changes the verdict.

## 10. Reviewer protocol

### APPROVED FOR MERGE
Only when:

1. exact head identified;
2. diff matches the prior ruling;
3. required exact-head evidence is green;
4. durable claims and PR body are current;
5. no unresolved permission boundary remains.

### PROCEED WITH CHANGES / BLOCKED
Name **one blocker at a time**, plus its exact closure condition. Separate next-slice guidance from the merge verdict.

## 11. Standing pre-review self-check

Before requesting review, answer:

> **What changed since the last ruling, what representations could now be stale, what semantic behavior must be preserved, and can the reviewer decide from this packet without reconstructing earlier turns?**

If any answer is unclear, fix the packet before review.

And for every instrument the packet offers as evidence, per §3b:

> **What is `Y` — the broken implementation this would fail against — and has it been run
> that way?**

An instrument whose `Y` is "the implementation this replaces" and which still passes is not
a regression. Reviewers may reject a packet on this alone rather than reconstructing the
proof themselves; **reconstruction teaches that a narrative will be accepted in place of
one.**

## 12. Updating this guide

Treat this file as a living operating guide. Update it only when a repeated workflow failure, newly proven seam, or better feedback-loop rule is demonstrated by evidence. Keep it concise: replace weaker rules rather than accumulating exceptions.
