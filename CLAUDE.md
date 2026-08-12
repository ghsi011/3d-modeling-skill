read AGENTS.md

## Agent skills

Configuration for the installed engineering skills. These three files hold *where things
live*; `AGENTS.md` holds the rules, and nothing below relaxes it.

### Issue tracker

Issues live in this repo's GitHub Issues, via the `gh` CLI — but roadmap work is tracked
in `ROADMAP.md` and defects in `docs/defects.md`, and GitHub Issues is currently empty.
See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical role names, unmapped, reusing the existing `wontfix` label; nothing
reads them until the `triage` skill is installed. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context, with the vocabulary in `ARCHITECTURE.md` rather than a `CONTEXT.md`. See
`docs/agents/domain.md`.
