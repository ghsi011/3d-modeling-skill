# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to
the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the
corresponding label string from this table.

## Why the columns are identical, and which of these labels exist

The vocabulary is kept as the canonical names rather than translated into local ones,
because there was no local vocabulary to translate into: at the time of writing this
repository had no issues at all, so no label had ever been applied to one. Inventing
`bug:triage`-style names would add a translation step protecting nothing.

Of the five, **`wontfix` already exists** — it is one of GitHub's defaults on this repo,
described as "This will not be worked on". The table points at that existing label
rather than a new one, because two labels meaning the same thing is exactly the
duplication this file exists to prevent.

The other four do not exist yet and will need creating the first time they are used:

```bash
gh label create needs-triage   --description "Maintainer needs to evaluate this issue"  --color d4c5f9
gh label create needs-info     --description "Waiting on reporter for more information" --color fef2c0
gh label create ready-for-agent --description "Fully specified, ready for an AFK agent" --color 0e8a16
gh label create ready-for-human --description "Requires human implementation"           --color 1d76db
```

`gh label create` fails if the label already exists, which makes it safe to re-run as a
check rather than something to guess about.

## Nothing in this repository reads this file

No tooling here consumes it: it is configuration for a triage skill, to be read by that
skill when one is available. Nothing in this repository's own gate, tests or CI applies
these labels or depends on them, so the table is a decision recorded ahead of its
consumer rather than a description of behaviour anything exhibits today.

Which skills happen to be installed on a given machine is not a fact this file can carry
truthfully — it changes without the repository changing, and durable documentation that
asserts it goes stale silently.
