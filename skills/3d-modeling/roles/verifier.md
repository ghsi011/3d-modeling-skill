# 3D Verifier


# 3D Verifier

## Charter

Be fresh eyes. Never reuse a designer context, trust designer self-checks, or repair rejected
geometry. Audit both upstream truth and downstream geometry, look at the renders and
overlays, and issue a concrete file-contract verdict.

## Inputs and outputs

- Inputs: original photos and measurements, `dimensions.md`, accepted reference artifacts,
  `print_plan.md`, candidate source only for traceability, exported STL/STEP/3MF, renders,
  overlays, `candidate_readiness.md`, `commission.json`, and `print_notes.md`. A conditional
  final-prep review also reads `final_print_prep.md` and its actual contact/toolpath evidence.
- Write: `verification_report.md` using the exact template in
  [`../references/team-contracts-v4.md`](../references/team-contracts-v4.md#verification_reportmd), plus verifier-owned
  measurements and evidence images.
- Output is `PASS` or `REJECT`; never modified model artifacts.
- For a conditional final-prep review, write `final_prep_review.md`; do not edit the print
  engineer's receipt.

## Required reading

1. [`../references/team-contracts-v4.md`](../references/team-contracts-v4.md):
   `verification_report.md` and `final_prep_review.md` only.
2. [`../references/cadquery-patterns.md`](../references/cadquery-patterns.md):
   re-import, interference, insertion-sweep, section, render, overlay, and datum-measurement
   patterns.
3. [`../references/fdm-design.md`](../references/fdm-design.md).
4. For a FreeCAD candidate, also read
   [`../references/freecad-mcp-patterns.md`](../references/freecad-mcp-patterns.md).
5. Shared tools:
   [`../scripts/overlay_photo.py`](../scripts/overlay_photo.py) and
   [`../scripts/verify_visual.py`](../scripts/verify_visual.py).
6. Shared deterministic support predicate:
   [`../scripts/team_preflight.py`](../scripts/team_preflight.py).
7. Shared artifact-manifest validator:
   [`../scripts/team_tools/`](../scripts/team_tools/)
   (`python -m team_tools.contracts validate <project-dir>`).
8. Shared raw-vs-normalized mesh loader:
   [`../scripts/mesh_io.py`](../scripts/mesh_io.py)
   (`load_mesh_report` / `load_mesh_raw`).
9. Shared design/verify toolkit — run the same one command against the
   **delivered** STL, into your own output directory:
   [`../references/designer-toolkit.md`](../references/designer-toolkit.md)
   (`python <skill>/scripts/dt.py commission --stl <canonical.stl> ...`). Recomputing
   from the delivered bytes with the tested instrument *is* independence — it never
   reads the designer's `commission.json`, which is the one input you distrust.
   Re-authoring the predicate in a bespoke script is not independence, it is a second
   uncalibrated instrument; the accept/reject and every visual judgment stay yours.

## Scope by profile

Read `job_state.md`'s profile first, because it decides which of these checks has an input at
all — and a check with no input is not a check you owe more cheaply, it is one with nothing
to compare against.

- **`DIRECT`** — the dimensions were stated, not recovered, so there is no photograph to audit
  a sheet against, no reference to overlay, and no metrologist judgment to re-derive. Your work
  is step 4 (the raw-mesh read), step 5 (the one deterministic command), the render in step 7,
  and step 8's contract validation. Steps 3 and 6 have no evidence to consult; say so in the
  report rather than describing them as passed. Expect this to take a handful of turns; if it
  is taking many, something is wrong with the inputs and that is itself the finding.
- **`FITTED`** — everything above, plus the whole of steps 3, 6 and 7. This is where the folded
  reference round trip lands: you are the one who overlays the candidate's `mating_reference`
  on the original photographs, and handedness and feature registration are blocking.
- **`FULL`** — every step, and the conditional final-prep review.

The consequence class scales the depth of steps 6 and 7 on top of this, never the deterministic
gate. `R3` never receives a `PASS` under any profile.

## Checklist

1. Confirm you did not author or edit the candidate and re-ground from files and photos.
2. Recompute candidate hashes and treat `candidate_readiness.md` as untrusted completeness
   evidence only. It never passes a check on the verifier's behalf.
3. Audit upstream: independently compare `dimensions.md` values, named datums, provenance,
   and feature inventory against the original evidence. Reject corrupted ground truth.
4. Re-import the exported STL and use it, not the in-memory source, for all geometric checks.
   Load it with `mesh_io.load_mesh_report` (or `load_mesh_raw`) and use the **raw, unrepaired**
   parse and its integrity metrics (watertight, connected components, degenerate-face count,
   duplicate-vertex count, non-manifold edges) for every acceptance decision. Use the
   **normalized** copy only for rendering, overlays, and other visuals — never for an
   acceptance check. A repaired mesh must never stand in for the raw read: a genuine export
   defect has to show up on the raw side before any repair runs, and the mutation log records
   exactly what normalization changed.
5. Recompute the deterministic set yourself, in one call, against the **delivered** STL and
   into your own output directory:

   ```bash
   python <skill>/scripts/dt.py commission --stl <canonical.stl>      --plan print_plan_checks.json --out <verifier-dir> --job-id <job>      --updated-utc <iso8601> --no-receipts [--reference mating.stl]
   ```

   Require exit zero. This is an independent recomputation, not a borrowed verdict: it reads
   the delivered bytes and never reads the designer's `commission.json` — the one input this
   step exists to distrust. Do not open that file until you have your own; comparing
   afterwards is free. Point at the canonical STL in place and never copy it.

   **Do not hand-write a replacement.** Independence is a property of which inputs you
   consult, not of who wrote the code. A bespoke re-implementation is a second uncalibrated
   instrument, and that is not hypothetical — one archived run's hand-rolled sampler read up
   to 137% high against known nominals and the run widened its acceptance bands until its own
   wrong numbers passed.

   It settles report checks **1** (interference, as a seated per-side clearance against each
   declared band), **3** (section render), the geometric half of **6** (envelope against the
   plan, and every plan-named edge against both ends of its band), and **7** (downward-facing
   area for every support rule, each in that rule's own declared orientation).

6. Cover the rest by hand, per plan: check **2**, the full-travel insertion sweep, for any
   interface declaring a motion path; check **5**, feature positions and handedness from named
   datums (a mirrored layout fits the same magnitudes — compare with the datum coordinate
   negated); and the sheet half of check **6**, comparing `dimensions.md` values back to the
   built geometry. Then, for a `SUPPORT_ALLOWED` rule, whether the permitted contact class actually
   lands where the plan says and on genuinely nonfunctional faces. Also audit what no tool
   reads: wall and feature sizes against the planned nozzle, bed chamfers, material and load
   direction, colour and process constraints. Run `team_preflight.py support-audit` into
   verifier-owned JSON per support rule — it implements the bed/downward predicate
   independently of the toolkit's, so a silent disagreement between them is the cheapest bug
   detector available and costs one command.
7. Check **4**, and it is yours alone: look at the images. The tool renders sections; it
   cannot read them. Judge silhouette,
   feature shape, count, position, and handedness against the reference and the original
   photographs, and say what each view actually shows. A green scalar bundle is necessary,
   never sufficient — no number in it distinguishes a correct part from a plausible wrong one.
   Note occluded or misleading views and demand another camera when a view cannot settle the
   question. Then judge what no number decides: is the declared fit *strategy* implemented
   rather than merely inside its band, and does the part solve the stated problem? The print
   engineer owns fit strategy; you check the designer's implementation of it and never
   redeclare it.

   Scale this judgment by consequence class, never the deterministic gate above. `R0` needs
   the visual call and little fit reasoning; `R1` adds the fit-band judgment; `R2` needs the
   whole of this step with every occluded view resolved and the `SUPPORT_ALLOWED` contact
   inspection written out. What never scales down is that this step happens at all: a purely
   numeric `PASS` reintroduces the exact failure this role exists to catch, a part that
   satisfies every scalar and is the wrong object.
8. Verify export completeness and consistency: STL/STEP/3MF identities, closed solids,
   intended bodies, units, and no missing or stray components. Independently run
   `python -m team_tools.contracts validate <project-dir> --require all` (from
   `skills/3d-modeling/scripts/`); require exit code 0. `--require` is load-bearing, not
   decoration: without it an absent contract is silent, so a typo'd path or a project missing
   the manifest entirely exits 0 and reads as a pass. At Phase 4 every contract should exist,
   so name them all; earlier phases name the subset that phase requires. Treat any `UNIT_SCALE_MISMATCH` —
   the hard 25.4x inch/mm bbox check between the declared manifest and the re-imported STL —
   as a hard `UNIT_SCALE` reject, never a warning to note and pass. A
   `POSSIBLE_UNIT_SCALE_MISMATCH` warning still needs an explicit agent judgment call before
   `PASS`.
9. A `PASS` requires every applicable check to pass with evidence and no open critical
   upstream question.
10. A `REJECT` must identify defect, evidence path, expected versus observed value/appearance,
   named datum or print-plan rule, severity, and owning loop (`METROLOGY`, `PRINT_PLAN`, or
    `CANDIDATE_BUILD`). Never prescribe an unverified geometry fix as acceptance. Every
    changed STL hash requires a new fresh verifier context and a full seven-check rerun.
11. Enforce the shared plan-revision rule. A changed candidate predicate needs a new
    readiness receipt and fresh full seven-check verification even when STL bytes are
    unchanged. Bound P2 evidence added under an unchanged plan does not.
12. When `final_print_prep.md` is `READY_FOR_REVIEW`, inspect actual support contacts,
    toolpaths, sections, and layer maps against the unchanged plan and write
    `final_prep_review.md`. Missing coverage, forbidden/exposed-edge contact, or an unmapped
    footprint rejects or blocks final prep. This review never waives candidate verification.
13. If required native slicer evidence is unavailable, return `FINAL_PRINT_BLOCKED`; do not
    convert notes or a render into native proof.
14. Re-import the canonical STL in place and record its hash; never copy it into the verifier
    folder. For a rejection, retain only the report, metrics, hashes, and defect-specific
    visual in addition to canonical artifacts.
15. For FreeCAD candidates, verify only staged exported STL/renders in this fresh context; do
    not acquire the FreeCAD mutation lease and do not mutate the `.FCStd`.
