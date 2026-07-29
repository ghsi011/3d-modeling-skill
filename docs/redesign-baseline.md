# Redesign baseline

Captured before any redesign work, on the machine the targets will be judged on.
Everything here is measured, not estimated. Re-run the same commands after each
phase and compare against this file rather than against memory.

Machine: Windows 11, Python 3.12.6, trimesh + manifold3d + numpy + pillow.
No CAD kernel installed at baseline time (build123d was added to the core as
the first act of iteration 1).

## Deterministic compute, today

| operation | median | p95 | spec target (§15.3) | status |
|---|---:|---:|---|---|
| trimesh + manifold3d import | 1.47 s | — | — | 78% of a no-witness run |
| `DIRECT`, no witnesses | 1.89 s | 2.08 s | — | |
| `DIRECT`, with witnesses | 3.54 s | 3.60 s | < 5 s / < 10 s | **already met** |
| witness generation alone | ~1.65 s | — | < 2 s / < 5 s | **already met** |
| commission-only | 1.66 s | 2.00 s | < 2 s / < 5 s | **already met** |
| cached `DIRECT` validation | — | — | < 2 s / < 4 s | no cache exists |
| build123d paths | — | — | < 10 s / < 20 s | backend does not exist |

n=5 per row, same clip part (`c_clip`, 8 parameters).

**The trimesh path already meets every deterministic target it has.** The
remaining compute wins are structural rather than algorithmic: content-addressed
caching (§5.9), not paying the 1.47 s import when nothing needs it (§5.5), and
loading the STL once (§5.4).

## Where the time actually goes

A measured end-to-end `DIRECT` job took **3.1 minutes** of wall clock for
**3.5 seconds** of compute. The ratio, not the arithmetic, is the target: every
agent round trip costs 8–47 s before a shell is reached, and the job took four.

This is why §5.1's fused job command matters more than any micro-optimization.
It is also why the import cost is worth naming: at 1.47 s, four separate
commands pay 5.9 s of interpreter startup to do 3.5 s of work.

## Known waste, with evidence

- **The STL is loaded 4 times per commission** (`commission.py:543, 571, 632,
  809`). `mesh_io` already exposes the raw/normalized pair the shared analysis
  context wants — `load_mesh_raw` (process=False) and `load_mesh` — so §5.4 is
  plumbing, not new capability.
- **No caching of any kind.** Every run rebuilds and re-measures.
- **No console entry points**; `dt.py` is invoked by absolute path.
- **`uv.lock` is committed** and hashed into the cache key, so a machine whose lock moved misses rather than serving geometry built against different resolved versions.
  `uv sync --frozen` resolves today, but nothing pins what CI installs.

## Contract inventory, and where it maps

| today | spec §3 |
|---|---|
| `job_state.md` + `dimensions.md` | `intent_manifest.json` |
| `print_plan_checks.json` + template `EXPECTED` | `model_contract.json` |
| `artifact_manifest.json` | `artifact_manifest.json` |
| `commission.json` | `commission_report.json` |
| `verification_report.md` | `verification_report.json` |
| `candidate_readiness.md` | folded into the artifact manifest / commission report |
| `final_print_prep.md`, `final_prep_review.md` | no successor — replaced by manufacturing modifiers (§1.3) |
| — | `safety_verification_report.json` (new) |
| — | `final_status.json` (new) |

Markdown is currently authoritative for four contracts. Under §2 JSON becomes
canonical and Markdown becomes a generated view, which inverts today's direction:
`report.py` and `intake.py` generate Markdown *as the source*.

## Test baseline

447 passing, 5 skipped, 115 subtests. `ruff` clean, `gen_harness --check` clean,
all internal links resolve. Two suites are slow: `test_audit.py` (91 s) and the
`team_preflight`/commission integration tests.

## Two things the spec leaves undefined

Both are load-bearing, and neither can be inferred from the current code.

**1. "Certified template" and "certified parameter-domain identifier" (§1.2, §3.2).**
`DIRECT` is gated on a template being certified and the parameters falling inside
a certified domain. Nothing like this exists — today a template is a Python
function with no declared validity range. What certifies one, what the domain is
expressed in, and who may widen it are unspecified.

**2. The anomaly detector that replaces the human look (§5.6, §6.2, §7.1).**
Clean certified `INCONSEQUENTIAL` `DIRECT` is specified as zero specialist calls
with `W1` witnesses generated but nobody reading them. Escalation fires when "an anomaly
detector fires", but no such detector is specified. Today a human look is
mandatory on this route for a documented reason: every check is conditioned on a
declaration, so geometry nobody declared is invisible to all of them — a 4 mm
post standing in a bin floor once passed twenty-seven green checks, an exact
bounding box and a matching bed-contact area. Removing the look without a
detector removes the only unconditioned evidence in the route.


---

# After iterations 1-5

Re-measured on the same machine, same method (n=5).

| operation | median | p95 | target | |
|---|---:|---:|---|---|
| `c_clip` (trimesh) end to end | 0.17 s | 0.19 s | < 5 s | met |
| `box_shell` | 0.04 s | 0.04 s | < 5 s | met |
| `l_bracket` | 0.13 s | 0.14 s | < 5 s | met |
| `trim_ring` (build123d) | 0.22 s | 3.27 s | < 10 s | met — p95 is the cold kernel import |
| `trim_ring` + STEP | 0.25 s | — | < 20 s | met |

Review dispatches on a clean certified `INCONSEQUENTIAL DIRECT` job: **0**.
On a certified `CONSEQUENTIAL DIRECT` job: exactly **1**, for the mandatory safety
pass, with no normal geometric verifier. `FITTED` retains its required specification review (with independent
verification when configured); `FULL` retains specification plus independent
verification.

Mesh loads per job: **1**, counted rather than declared.

## What the numbers rest on

Certified `INCONSEQUENTIAL` `DIRECT` zero-dispatch is gated on the mutation corpus,
not on the detectors existing:
58 mutants across all four certified templates and five defect classes, with
screening's own false-negative rate on defects fused to the part at 0.0 and false
positives at 0.0. `python -m pipeline.corpus` reproduces it and
`CalibrationTest` fails the build if it stops passing.

That gate rejected two earlier attempts, which is the only reason the number is
worth anything:

* The first measured `caught_by_contract or caught_by_screening` — the whole
  pipeline — and reported 0.0 while the screen itself missed 46.7%.
* The second scored disconnected solids as screening catches; on fused defects
  only, the rate was 87.5%.

## Still not met

* The `< 2 s` cached-validation target is met, and not only when cached: the
  300-vent enclosure commissions cold in 0.78 s. Content-addressed caching landed
  in `pipeline/cache.py` and is off unless a `cache_dir` is passed.
* Wall clock on a real agent-driven job is still unmeasured against the new
  pipeline. The deterministic compute is 0.17 s; the previous end-to-end
  measurement of 3.1 minutes was against the retired route.
