# Handoff — clean state

`main` is the authoritative baseline. There is no milestone branch to resume and
no queued work.

## Where things stand

Release 1 is ruled `COMPLETE`, with its nine-row proof table in `ROADMAP.md`.
The gates are green on Linux and are run where they mean something: the commit
gate has no platform-assumption allowance left, and the pre-merge job builds the
real confined boundary rather than reporting on a runner that could not.

`docs/defects.md` is the open-defect record. D29 is deliberately open with its
reasoning written down, and D22 is carried as a Release 6 limitation rather than
a blocker. Neither is a task; both are limits on what may be claimed.

## What is authorised next

Nothing. No implementation task is currently authorised, and the next step will
be planned with the user rather than picked up from this file.

That includes the bee-porter work. It is an external design project, retained
outside this repository under its own project directory, and it is **not**
automatically the next repository slice — nothing in the skill is waiting on it,
and starting it is a decision for the user to make, not a continuation of this
one.

## Working notes for whoever picks this up

Read `AGENTS.md` first; it is the operating contract, and `ARCHITECTURE.md` and
`ROADMAP.md` are the design and planning authorities.

Record `git rev-parse HEAD` and `git status --short` at the start and end of any
run that depends on the tree, and stop if either moved unexpectedly. One writer
per worktree. No expected SHA is pinned here on purpose: a hash in a handoff
goes stale the moment anything lands, and a stale one reads as an instruction.
