# Baseline — the behaviour Phase 0 froze

Measured at `f7082e5` on the reference workstation (Windows 11, Python 3.11,
trimesh 4.12.2, `uv run --frozen`), before any consolidation work. These are
measurements of one environment, not timing guarantees.

Regenerate the per-route numbers with `pipeline/test_frozen.py` and
`design-tool selftest --json`; the fixtures that hold them to account are in
[`pipeline/test_frozen.py`](../skills/3d-modeling/scripts/pipeline/test_frozen.py)
and [`pipeline/selftest.py`](../skills/3d-modeling/scripts/pipeline/selftest.py).

## Test suite

| | |
|---|---|
| collected | 706 passed, 4 skipped, 240 subtests |
| wall time | 555 s (9 m 15 s) |

## Deterministic cost per route

`render=False`, warm interpreter, in-process (no CLI start-up). Model calls are
stubbed, so the `llm calls` column is the number of dispatches the route
*requires*, not their latency.

| route | template | deterministic wall | llm calls | final status |
|---|---|---|---|---|
| `DIRECT` | `c_clip` (trimesh-manifold) | 0.20 s | 0 | `NEEDS_MORE_EVIDENCE` |
| `DIRECT` | `trim_ring` (build123d) | 3.90 s | 0 | `NEEDS_MORE_EVIDENCE` |
| `FITTED` | `c_clip` | 0.21 s | 2 | `VERIFIED` |
| `FULL` | `c_clip`, `bore_d=60` | 0.19 s | 2 | `VERIFIED` |

The `trim_ring` figure is a build123d cold import (3.69 s of the 3.90 s is the
build stage). The trimesh path's whole run is 0.2 s, of which commissioning and
screening are 0.13 s.

`design-tool selftest` builds all five certified templates in ~4.6 s, dominated
by the same cold import.

## The DIRECT status finding

A clean certified `INCONSEQUENTIAL` `DIRECT` job finishes `NEEDS_MORE_EVIDENCE`,
not `COMMISSIONED`.

`SKILL.md` and `roles/orchestrator.md` both present `COMMISSIONED` as the
ordinary outcome of this route. The shipped code does not produce it:
`screening.calibrated` is `False` — the corpus flipped it back when it was
re-measured against mutants actually fused to the part — and `status.decide`
refuses to call a part commissioned when the broad screen is uncalibrated *and*
nobody independent looked. `DIRECT`'s own route trade is that nobody independent
looks. So the two conditions are always both true on this route, and the claim
that comes back is:

> the geometry matches its contract, but the broad screen is uncalibrated and
> nobody independent looked, so undeclared geometry cannot be ruled out. Supply a
> verifier, or say plainly that nothing has looked at this part.

That claim is accurate. The documentation is what is out of date.

Frozen rather than fixed. The two ways to make this route say `COMMISSIONED` are
to earn the calibration on a corpus, or to weaken the threshold — and weakening a
threshold after observing the candidate is exactly what the scope controls
forbid. `test_frozen.py::test_direct_writes_its_frozen_receipt_set_and_claim`
pins it so the consolidation cannot change it by accident, in either direction.

## Receipts written, per route

| route | receipts |
|---|---|
| `DIRECT` | `intent_manifest`, `model_contract`, `artifact_manifest`, `commission_report`, `final_status` |
| `FITTED` | the above plus `specification`, `verification_report` |
| `FULL` | the same set as `FITTED` |

Plus `timings.json` (deliberately unhashed — durations are not part of any
artifact's identity) and `witness/` when a renderer is available.
`manufacturing_report` appears only when the job declares modifiers.

## Certified contract hashes

Frozen in `pipeline/selftest.py::FROZEN_CONTRACTS`. Derived from declared
parameters, expectations and the envelope — never from a mesh — so they are
independent of the tessellator version, and a mismatch means a certified
contract moved rather than that a dependency was bumped.

## Known-good agent-facing command surface, before consolidation

| surface | commands |
|---|---|
| `design-tool` | `run-job`, `doctor` (`selftest` added in Phase 0) |
| `scripts/dt.py` | `commission`, `doctor`, `crop`, `integrity`, `report`, `templates`, `probe`, `validate`, `status`, `screen`, `audit`, `intake`, `build`, `plan`, `coupon` |
| `python -m team_tools.contracts` | `validate`, `status`, `hash` |
| `scripts/team_preflight.py` | `support-audit`, `validate-interfaces` |
| `python -m pipeline.corpus` | screening calibration measurement |

Two CLIs and 20+ agent-facing verbs. [ADR 0001](adr/0001-one-project-one-cli.md)
reduces this to one documented interface.
