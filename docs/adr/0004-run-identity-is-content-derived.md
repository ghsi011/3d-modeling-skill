# ADR 0004 — A run is identified by what it was issued against, not by when it happened

Status: accepted, 2026-08-02
Interprets: [`ARCHITECTURE.md`](../../ARCHITECTURE.md) §13.4 (dependency
binding), §13.6 (resumption), §13.7 (determinism). It adds no requirement to the
architecture; it decides how one of the roadmap's scope items satisfies those
three at once, and records why the obvious reading of the item is refused.
Closes: `ROADMAP.md` Release 3, *binding-aware lifecycle* — "run identities".

## The sentence this decision serves

> Two invocations that were issued against identical bindings produce identical
> evidence and are interchangeable in every claim this system can make. They are
> the same run, and the identity says so.

## Context: the item, and the objection that deferred it

Release 3 scopes "run identities" without saying what one is for. The obvious
reading is that a run id answers **which invocation produced this receipt**, and
a previous scoping pass deferred the item with an argument rather than with a
shrug:

> The CLI's whole design is that a rerun on unchanged inputs is
> **byte-identical**. `design-tool init` requires `--updated-utc` from the caller
> and every verb reuses it precisely so that a rerun does not churn a digest.
> An invocation counter breaks that by construction: the second run of an
> unchanged job differs from the first in a field, and every hash downstream of
> that field differs with it. So either the id is content-derived — in which case
> it is a hash that already exists — or it ends byte-identical reruns.

The objection is correct about the counter and wrong about the conclusion. It
treats "content-derived" and "already exists" as the same claim. They are not,
and the difference is the whole of this decision.

## Decision

**The run identity is `SHA-256` over the binding map a formulation currently
presents.** One function, `pipeline.bindings.identity`, over one map,
`pipeline.bindings.current`:

| binding | value |
| --- | --- |
| `acceptance` | the frozen acceptance contract's digest, absent on the certified lane |
| `contract` | `model_contract.json`'s canonical payload hash |
| `plan` | `execution_plan.json`'s canonical payload hash |
| `stl`, `step`, `source` | the artifacts' digests, absent where not produced |
| `alternative` | which formulation this is; `.` for the shared root |

`design-tool status --json` reports it as `run_id`. `next_action.json` carries
the same value as `state_sha256`, computed by the same function — an instruction
and a receipt go stale for the same reasons, and two answers to "has this project
moved" is one answer and one bug.

### Why this is an identity and not a second name for an existing hash

Because of the last row. Two formulations are **byte-identical at the instant one
is branched from the other**: same contract hash, same STL digest, same source
digest, same compiled plan. That is not a hypothetical — it is the case
`pipeline/test_alternatives.py` was built around, and the reason `alternative_id`
joins the review envelope, because without it a safety `PASS` written for one
sibling is `is_bound` for the other.

An identity derived from the artifacts would say those two are one run. This one
does not. No single digest already in the build has that property: the contract
hash deliberately does not carry the formulation (two formulations requiring
identical geometry legitimately share an acceptance contract), and the artifact
digests cannot.

### Why the answer to "which invocation" is "the question does not separate them"

A run id is worth having when two things it distinguishes can be told apart by
some reader for some purpose. Under byte-identical rerun, two invocations over
identical bindings differ in nothing a receipt records, nothing a review can be
bound to, nothing a status can weaken, and nothing a user can act on. There is no
reader for whom telling them apart changes an answer.

An id that separated them would therefore be recording a distinction with no
consequence — and paying for it with the one property the whole command surface
is arranged around. That trade is not close.

## Alternatives rejected

**An invocation counter, or a wall-clock stamp, hashed into a receipt.** Ends
byte-identical reruns. `pipeline/test_frozen.py`, the deterministic-evidence
tests and the L1 replay's determinism assertion all fail, and every one of them
fails *correctly*.

**An invocation id deliberately not hashed into any receipt, carried in a side
channel.** Survives the determinism constraint and was seriously considered. It
is rejected as an *identity* for the reason this codebase retired
`candidate_strategy` and `project_hash`: nothing would read it, no claim would
change on it, and a stored value with no behaviour is the shape this repository
removes.

What survives from that option is narrower and does have a reader.
`lifecycle.json` is an append-only journal at the project root, bound by nothing,
recording the two events that are decisions rather than derivations — a
`--restart` and its discarded digests, and a disposition transition. It is
ordered by when things happened, which is exactly what a content-derived identity
cannot be, and it participates in no digest, so appending to it cannot make a
receipt stale. It is a log, not an identity, and it is named as one.

**Declaring the item delivered with no code.** Closest to right, and still wrong
by one row: before this change nothing computed a digest over the *whole* map,
`state_sha256` was an inline expression inside `cli._write_next_action` rather
than a named concept, and `design-tool status` could not report the value at all.
Delivering it is naming it once, computing it in one place, and proving the two
properties that make it an identity.

## Consequences

* `bindings.identity` and `bindings.run_id` are the one definition. A second
  spelling of "which run is this" is a defect, not a convenience.
* No receipt gained a field, so no frozen contract hash moved and no replay
  expectation was re-pinned.
* The proof is a fixture, not a claim: an unchanged formulation keeps its
  identity across reruns; every binding in the map moves it; a reformatted
  declaration does not (three bindings hash a canonical payload, not bytes); two
  byte-identical formulations are two runs; and a whole certified job re-run on
  unchanged inputs moves nothing but `timings.json`, which is hashed into
  nothing. Each was verified by mutating the protection — an identity that mixed
  in a counter, and a map that dropped `alternative` — and watching the fixture
  fail.

## What this does not decide

It does not give a run a *name a human chose*, and nothing here needs one. It
does not make `final_status.json` carry the identity: a conclusion is not an
identity, two runs reaching the same verdict against different evidence must not
share an id, and a verdict that is rewritten must not change one. And it does not
address which invocation of many wrote a given byte on a shared filesystem, which
is a concurrency question this build answers with one writer per worktree
(`AGENTS.md`) rather than with a digest.
