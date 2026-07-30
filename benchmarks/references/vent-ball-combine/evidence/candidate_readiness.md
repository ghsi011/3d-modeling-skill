---
contract: candidate-readiness
contract_version: 4
job_id: vent-ball-01
revision: 1
candidate_id: candidate-01
owner: cad-designer
status: READY
non_acceptance: true
dimensions_revision: UNBOUND
print_plan_revision: 1
candidate_stl_sha256: 5d2d7324e87a195eef0b21bf155ac0792184eec33fdfbf6a1273b0b24b03d507
commission_verdict: PASS
updated_utc: 2026-07-28T00:00:00Z
---

# Candidate readiness — DESIGNER SELF-CHECK, NON-ACCEPTANCE

Generated from `commission.json`. Every number below was measured on the
re-imported exported STL, not on the in-memory model. This document never
passes a Phase-4 gate on a verifier's behalf.

## Deterministic checks

**8 of 9 checks ran.** These did not, and this document asserts nothing about them: `step`. Treat every one as an open question a reader has to close by other means.

| ID | Check | Result | Measured |
|---|---|---|---|
| static-wall | Wall is printable at the planned nozzle | PASS | wall 6.0 mm against a 0.80 mm floor (2x the 0.4 mm nozzle) |
| step | STEP exported alongside the STL | SKIPPED | no STEP was written: this part was built through the mesh path, which exports STL only |
| solid | Watertight, 1 body | PASS | watertight=True, components=1, plan expects 1 |
| repair | Export needed no structural repair | PASS | 48811 coincident vertices merged, no faces dropped |
| envelope | Overall size vs plan | PASS | worst axis y off by -0.01 mm (tolerance 0.5 mm) |
| seated-S-01 | Part sits on the declared bed | PASS | lowest point sits at z=0.000 against a declared bed at 0.000 (tolerance 0.05) |
| support-S-01 | S-01 downward-facing area within its limit | PASS | 1628.14 mm2 past -0.70710678 in the 'plan model_to_printer_matrix' placement (limit 1700.0 mm2) |
| fit-I-01 | Interface I-01 fit | PASS | seated clearance -0.0000 mm against a declared band [-0.05, 0.05] mm |
| fit-I-02 | Interface I-02 fit | PASS | seated clearance 0.1200 mm against a declared band [0.09, 0.18] mm |

## Open items

| Check | Required next action |
|---|---|
| none | commission reported no failing check |

## Judgment — not machine-supplied

Commission leaves these null on purpose. Answer both, from the renders.

- `visual_accept`: <!-- REQUIRED: the agent fills this in after looking. -->
- `fit_band_ok`: <!-- REQUIRED: the agent fills this in after looking. -->
