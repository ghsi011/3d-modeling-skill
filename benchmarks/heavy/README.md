# L0-heavy — the component fixtures that cost a child interpreter

```bash
uv run pytest benchmarks/heavy -q     # ~20 min, 449 tests, before merge
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
the confined build boundary to exist, and four in `test_cost_heavy.py`, which
measure the two costs only the authored lane has — the confined boundary itself,
and the second build a bounded review round trip pays for.

A handful of tests moved without starting anything, because they do the
expensive work themselves: the screening corpus (19 s a test), the STEP reads
that go through a B-rep kernel, and the preservation and determinism fixtures
that run a whole job more than once.

One moved for a reason the seam above does not describe, and it is recorded here
rather than left for the next reader to rediscover.
`ReviewEnvelopeRenderTest` in [`test_pipeline_heavy.py`](test_pipeline_heavy.py)
is the single case in its class that asks for `render=True`. That is cheap and
answers in the parent process on Windows, and it cannot on Linux: `preview`
selects the EGL platform there, PyOpenGL resolves the library through
`ctypes.util.find_library`, and that shells out to `ldconfig` — and to `gcc` and
`ld` when the library is missing. Finding EGL does not avoid it; `find_library`
runs `ldconfig` to answer at all. So the case starts a child process on every
Linux machine, which is the one thing the gating tier refuses, and it belongs in
the tier that permits one. The property being tested is unaffected: a witness
whose renderer failed to import records `renderer="unavailable: ..."` with no
images, which is a different record from the `"none"` of a job that never asked,
and the envelope binds either — so the case still refuses the stale answer for
the reason it names. That was checked by mutation, not by watching it pass:
leaving the second run's render flag unchanged makes the stale answer accepted.

Two moved for a reason that is not about cost at all, and it is recorded here
because the rule below does not describe them and a reader applying that rule
would find two files contradicting it.
[`test_work_directory_names_heavy.py`](test_work_directory_names_heavy.py) holds
the fixtures for the artifact-name registry (#46). They start no child process
and the two together cost a fraction of a second of call time, so by the seam
above they belong in the gating tier. They are here because
`L0_COLLECTED_CEILING` was full when that slice landed and **the user ruled that
the fixtures move rather than that the ceiling rise**. The consequence is the one
this tier always carries and is worth naming for a case that did not have to
carry it: they no longer run on every commit, they run before merge, so the
coverage is preserved and the moment it is observed is later.

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

**Import a `tools/` module by the same name its siblings use.** A module under
`tools/` reaches its neighbours by bare name -- `import corpus` -- because pytest
prepends a test file's own directory. A half living here does not get that, and the
obvious repair, `from tools import corpus`, is not equivalent: it produces a
*second* module object for the same file, so `corpus is tools.corpus` is false.
Anything that patches one is invisible to the other, and a `mock.patch.object` on
the wrong object silently does nothing -- the test then fails, or worse passes, for
a reason unrelated to what it asserts. Put `tools/` on `sys.path` and use the bare
names. `test_blind_corpus.py` carries the measured case.
