# Issue tracker: GitHub

Issues and PRDs for this repo live as GitHub issues, in
[`ghsi011/3d-modeling-skill`](https://github.com/ghsi011/3d-modeling-skill/issues).
Use the `gh` CLI for all operations; it infers the repo from `git remote -v` when run
inside a clone.

## What this repo actually tracks where, as of 2026-08-12

Read this before treating the issue tracker as the whole picture, because it is not.

- **GitHub Issues currently hold nothing.** `gh issue list --state all` returns an
  empty list. GitHub is the *chosen* tracker for issues from here on, not a record of
  where past work was tracked.
- **Roadmap work lives in [`ROADMAP.md`](../../ROADMAP.md)** — release rows, slice
  ordering, and the evidence each release consumed. It is the authority on what is
  next, and no issue supersedes it.
- **Defects live in [`docs/defects.md`](../defects.md)**, each with a `Status` and,
  where one exists, the fixture that pins it.
- **Architectural decisions live in [`docs/adr/`](../adr/)**.
- **Scope and priority rulings arrive out of band**, in a coordination conversation
  rather than in this repository. An issue does not change scope.

So a skill that reads only the issue tracker will conclude this repo has no work in
it. If you need to know what to do next, `ROADMAP.md` is the file.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."`. Use a heredoc for
  multi-line bodies.
- **Read an issue**: `gh issue view <number> --comments`.
- **List issues**:
  `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'`
  with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `gh issue comment <number> --body "..."`
- **Apply / remove labels**: `gh issue edit <number> --add-label "..."` /
  `--remove-label "..."`
- **Close**: `gh issue close <number> --comment "..."`

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo treats external PRs as
feature requests; `/triage` reads this flag.)_

Left `no` deliberately: every pull request here so far has been opened by the
maintainer or by an agent working under the maintainer's direction, so there is no
external request queue for triage to read. Flip it if that changes.

When set to `yes`, PRs run through the same labels and states as issues, using the
`gh pr` equivalents:

- **Read a PR**: `gh pr view <number> --comments`, and `gh pr diff <number>` for the
  diff.
- **List external PRs for triage**:
  `gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments`
  then keep only `authorAssociation` of `CONTRIBUTOR`, `FIRST_TIME_CONTRIBUTOR`, or
  `NONE` (drop `OWNER`/`MEMBER`/`COLLABORATOR`).
- **Comment / label / close**: `gh pr comment`, `gh pr edit --add-label`/
  `--remove-label`, `gh pr close`.

GitHub shares one number space across issues and PRs, so a bare `#42` may be either —
resolve with `gh pr view 42` and fall back to `gh issue view 42`.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --comments`.

## One local rule that outranks the conventions above

[`AGENTS.md`](../../AGENTS.md) governs this repository, and nothing here relaxes it.
In particular: work lands through a pull request against `main`, never a direct push;
and a claim about this repository's behaviour needs evidence attached, which applies
to an issue body exactly as much as to a commit message.
