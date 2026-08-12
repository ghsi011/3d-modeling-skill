# Domain Docs

How the engineering skills should consume this repo's domain documentation when
exploring the codebase.

**Layout: single-context.** One `CONTEXT.md` at the root and one `docs/adr/`. There is
no `CONTEXT-MAP.md` and there should not be one unless this repository grows genuinely
separate contexts with their own vocabularies — it is a single Python package with one
pipeline, not a monorepo.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root, or
- **`CONTEXT-MAP.md`** at the repo root if it exists — it points at one `CONTEXT.md` per
  context. Read each one relevant to the topic.
- **[`docs/adr/`](../adr/)** — read ADRs that touch the area you're about to work in.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't
suggest creating them upfront. The `/domain-modeling` skill creates them lazily when
terms or decisions actually get resolved.

`CONTEXT.md` does not exist here yet, and that is the expected state, not an omission to
correct. What would go in it is currently spread across
[`ARCHITECTURE.md`](../../ARCHITECTURE.md), which is where this project's vocabulary is
actually defined and which the ADRs cite by section number (`§6.4`, `§13.4`, and so on).
**Read `ARCHITECTURE.md` when you need the vocabulary.** If a `CONTEXT.md` is ever added
it must not restate `ARCHITECTURE.md`, because two definitions of one term is the defect
this project has repeatedly paid for.

## The ADRs here are decisions, and some of them are still open

`docs/adr/` currently holds:

| ADR | Subject |
| --- | --- |
| 0001 | one project, one CLI |
| 0002 | route and contract authority |
| 0003 | a datum is evidence with a provenance and a scope |
| 0004 | run identity is content-derived |
| 0005 | a comparison refuses rather than scores |

An ADR here can contain decisions that are **numbered, accepted in principle, and not
yet implemented** — ADR 0003 decision 6 is one. So "the ADR says X" is not the same as
"the code does X", and a skill that assumes the former can conclude a protection exists
when nothing enforces it. Check the code.

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a
hypothesis, a test name), use the term as defined in `ARCHITECTURE.md` — `datum`,
`edit scope`, `interface`, `provenance`, `review envelope`, `revision`. Don't drift to
synonyms. `measurement` and `datum` are not interchangeable here, and neither are
`requirement` and `dimension`.

If the concept you need isn't defined yet, that's a signal — either you're inventing
language the project doesn't use (reconsider) or there's a real gap (note it for
`/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently
overriding:

> _Contradicts ADR-0007 (event-sourced orders) — but worth reopening because…_

In this repository that obligation is stronger than the default, because
[`AGENTS.md`](../../AGENTS.md) requires durable prose to stay true: if a change makes a
sentence in an ADR, `ARCHITECTURE.md`, `ROADMAP.md`, `CHANGELOG.md`, or
[`docs/defects.md`](../defects.md) false, correcting that sentence is part of the change
and not follow-up work.
