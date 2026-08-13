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

## 4. State synchronization rule

After every material change ask:

> **What statements, tests, manifests, counts, comments, docs, roadmap entries, changelog entries, or PR claims depended on what I just changed?**

Then update and re-verify every affected representation immediately.

**PR bodies are durable prose about the current head.** Any material new SHA or changed claim requires the PR body to be synchronized in the same action.

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

## 12. Updating this guide

Treat this file as a living operating guide. Update it only when a repeated workflow failure, newly proven seam, or better feedback-loop rule is demonstrated by evidence. Keep it concise: replace weaker rules rather than accumulating exceptions.
