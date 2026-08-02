# L0-heavy — the component fixtures that cost a child interpreter

```bash
uv run pytest benchmarks/heavy -q     # ~15 min, 353 tests, before merge
uv run pytest                         # the commit gate this half was cut out of
```

[`ROADMAP.md`](../../ROADMAP.md) section 5.1 puts **L0 on every commit** and
**L1 on pull requests**. This directory is neither rung: it is the part of L0
that cannot be paid on every commit, run on the same trigger as L1.

## Why it exists

Profiled at `79244ae`, the commit-gating suite was **997 s against a five-second
budget**. The profile is not a long tail. Of 1163 tests and 1020 s of measured
wall clock, **194 tests started a child interpreter and held 876 s** — 86% of the
gate in 17% of the tests. The remaining 969 tests cost 143 s between them, nearly
all of it under 0.2 s a test. One mechanism, priced at about 1.6 s a go, because
a fresh interpreter that reaches `import trimesh` costs that here
([`docs/baseline.md`](../../docs/baseline.md)).

So the split is along that seam. Everything that starts a child — the `dt.py` and
`design-tool` command surfaces, the confined build boundary, the packaging and
bundle smokes — moved here. Everything that answers in the parent stayed in the
unit suite beside the module it tests. Nothing was deleted and nothing was
weakened: 830 tests stayed, 333 moved, and 830 + 333 is the 1163 that were there
before. Written *since* the split rather than moved by it: three cases in
`test_lifecycle_heavy.py`, which restart a job whose review answer had to survive
the confined build boundary to exist.

A handful of tests moved without starting anything, because they do the
expensive work themselves: the screening corpus (19 s a test), the STEP reads
that go through a B-rep kernel, and the preservation and determinism fixtures
that run a whole job more than once.

## The rule a new test follows

> Write the test beside the module it tests. Move it here when it starts a child
> interpreter — the CLI surface, the confined build, a packaging smoke — or when
> it needs a corpus, a B-rep read, or a job run more than once.

You do not have to remember. The repository-root
[`conftest.py`](../../conftest.py) measures both properties while the suite runs
and fails the test that breaks either, naming this directory in the message. That
is the difference between this boundary and a marker: a marker is one forgotten
decorator away from a test silently leaving the tier it belongs to, and the
default here is the *gating* tier, so forgetting costs a red test rather than
lost coverage.

Which tier a file is collected in is still structural, and by the same lever that
made L1 real: `testpaths` in [`pyproject.toml`](../../pyproject.toml) names
`skills/3d-modeling/scripts` and `tools`, and this directory is in neither, so a
bare `uv run pytest` cannot collect it.

## What runs it, and when

| tier | command | trigger |
| --- | --- | --- |
| L0 | `uv run pytest` | every push, on both Python versions |
| L0-heavy | `uv run pytest benchmarks/heavy` | pull requests, before merge |
| L1 | `uv run pytest benchmarks/replays` | pull requests, before merge |

`tools/test_tiers.py` fails if `.github/workflows/ci.yml` stops naming this
directory. A tier nobody runs is worse than no tier, because it reports all
clear.

## Reading a file here

Each module is one half of a file that still exists under `testpaths`, and says
which in its docstring. Fixtures the two halves share are **imported** from the
half that stayed rather than copied: two spellings of one fixture is how two
tiers stop testing the same thing.
