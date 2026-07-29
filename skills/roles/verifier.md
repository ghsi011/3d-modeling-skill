---
role: verifier
source: skills/3d-modeling/roles/verifier.md
agent_description: Fresh independent verifier that audits upstream measurements and all seven exported-STL checks, including actual visual render and overlay inspection.
skill_description: Independently accept or reject fit-critical 3D designs. Use only in a fresh context that did not author the geometry, to audit dimensions.md against photos and to run all seven Phase-4 checks on re-imported exported STL plus visual renders, overlays, and print_plan.md constraints.
agent_body: |-
  Load the `3d-modeling` skill and follow its `roles/verifier.md` exactly, in a context
  that did not design the candidate. Re-import
  the exported STL, inspect the renders and overlays with fresh eyes, and write only verifier
  evidence plus `verification_report.md`. Never edit or fix geometric source. Reject with
  concrete evidence and the owning upstream loop whenever any required check lacks proof.
display_name: "3D Verifier"
short_description: "Independently verify exported printable geometry"
default_prompt: "Use $3d-verifier for a fresh-context exported-artifact audit."
reads_files: true
edits_files: false
writes_files: true
runs_shell: true
web: false
loads_skill: true
can_spawn: []
model_hint: opus
permission_mode_hint: acceptEdits
---

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
- Write: `verification_report.md`, drafted by `dt.py report` from your own recomputation and
  completed by you, plus verifier-owned measurements and evidence images.
- Output is `PASS` or `REJECT`; never modified model artifacts.
- For a conditional final-prep review, write `final_prep_review.md`; do not edit the print
  engineer's receipt.

## Required reading

Always:

1. [`../3d-modeling/references/fdm-design.md`](../3d-modeling/references/fdm-design.md) — you
   judge printability, and this is what you judge it against.
2. Shared raw-vs-normalized mesh loader, which `dt.py audit` reads for you:
   [`../3d-modeling/scripts/mesh_io.py`](../3d-modeling/scripts/mesh_io.py). Read its
   docstring for why the raw side is authoritative — every shared tool downstream loads the
   normalized copy, so an export defect only ever shows on the raw side and normalization
   erases the evidence.
3. Shared design/verify toolkit — run the same one command against the **delivered** STL,
   into your own output directory:
   [`../3d-modeling/references/designer-toolkit.md`](../3d-modeling/references/designer-toolkit.md)
   (`dt.py audit <project> --out <your-dir> ...`, then `dt.py report`). Recomputing from the
   delivered bytes with the tested instrument *is* independence — the recomputation never
   reads the designer's verdicts, which is the input you distrust. Re-authoring the
   predicate in a bespoke script is not independence, it is a second uncalibrated instrument;
   the accept/reject and every visual judgment stay yours.

Only when the job has the evidence for it:

4. `FITTED`/`FULL`, where photographs and a mating reference exist:
   [`../3d-modeling/scripts/overlay_photo.py`](../3d-modeling/scripts/overlay_photo.py),
   [`../3d-modeling/scripts/verify_visual.py`](../3d-modeling/scripts/verify_visual.py), and
   [`../3d-modeling/references/verification-patterns.md`](../3d-modeling/references/verification-patterns.md)
   for the insertion-sweep and datum-measurement patterns you author yourself.
5. A `SUPPORT_ALLOWED` rule, whose contact class you inspect independently:
   [`../3d-modeling/scripts/team_preflight.py`](../3d-modeling/scripts/team_preflight.py).
6. A conditional final-prep review, for the `final_prep_review.md` template:
   [`../3d-modeling/references/team-contracts-v4.md`](../3d-modeling/references/team-contracts-v4.md).
   The `verification_report.md` template is **not** on this list: `dt.py report` emits it,
   already filled with your own measurements, so reading the whole contract to obtain a
   thirty-line skeleton buys nothing.

`dt.py crop` zooms a render or a photograph in one call, capped so the pixels are not paid
for twice — reach for it rather than hand-rolling an image crop when a view is too small to
settle a question.

`team_tools.contracts` you run rather than read:
`validate <project-dir> --require all` and `status <project-dir>`, both requiring exit zero.

## Scope by profile

Read `job_state.md`'s profile first, because it decides which of these checks has an input at
all — and a check with no input is not a check you owe more cheaply, it is one with nothing
to compare against.

- **`DIRECT`** — the canonical runner does not dispatch this role. A certified
  `INCONSEQUENTIAL` `DIRECT` job has no review callback; a certified `CONSEQUENTIAL`
  `DIRECT` job has one safety review and still has no normal geometric verifier. The
  runner ignores a verification callback on this route, so do not create
  a `verification_report.md` or report an independent verdict for a canonical `DIRECT`
  job. If a separately commissioned audit is requested outside this route, label it as
  external manual work rather than changing the route's claim.
- **`FITTED`** — everything above, plus the whole of steps 3, 6 and 7. This is where the folded
  reference round trip lands: you are the one who overlays the candidate's `mating_reference`
  on the original photographs, and handedness and feature registration are blocking.
- **`FULL`** — every step, and the conditional final-prep review.

The consequence class does not create a geometric verifier for `DIRECT`. On `FITTED` or
`FULL`, a `CONSEQUENTIAL` job also needs the one bounded safety review, which is separate
from your geometric verdict. Your `PASS` remains valid for either consequence class;
`final_status.json` decides what claim the complete evidence permits.

## Checklist

1. Confirm you did not author or edit the candidate and re-ground from files and photos.
2. Recompute candidate hashes and treat `candidate_readiness.md` as untrusted completeness
   evidence only. It never passes a check on the verifier's behalf.
3. Audit upstream: independently compare `dimensions.md` values, named datums, provenance,
   and feature inventory against the original evidence. Reject corrupted ground truth.
4. Settle the mechanical half in one call, against the **delivered** STL and into your own
   output directory:

   ```bash
   uv run --project <skill> --frozen python <skill>/scripts/dt.py audit <project-dir> --out <verifier-dir>       --job-id <job> --updated-utc <iso8601> [--reference mating.stl]
   ```

   It reports the hash binding, an independent recomputation compared check-by-check against
   the designer's, and both contract checks, with the raw un-repaired parse alongside them as
   evidence. Require exit zero.

   `--out` is **your own directory**, never the project root: the recomputation exists to be
   compared against the designer's receipts, and writing over them destroys what you came to
   check. `audit` refuses that outright, because a run once did it.

   Two things about the numbers. The raw parse is reported, not judged: an STL stores no
   vertex sharing, so a sound part reads as many components and `watertight=False`, and the
   one number that means anything there — degenerate faces — is the same number the
   recomputation's `repair` check already fails on. Use the normalized copy for renders and
   overlays only, never for an acceptance decision. And the recomputation is the same
   instrument on the same bytes: it cannot catch a wrong instrument, and what it can catch — a
   delivered STL that is not the one measured — the hash binding catches first and more
   cheaply. It runs because it costs a second, not because it is where findings come from.
   Budget accordingly and leave the time for step 8.

   **Do not hand-write a replacement.** Independence is a property of which inputs you
   consult, not of who wrote the code. A bespoke re-implementation is a second uncalibrated
   instrument, and that is not hypothetical — one archived run's hand-rolled sampler read up
   to 137% high against known nominals and the run widened its acceptance bands until its own
   wrong numbers passed.
5. Where the sheet declares a number, ask the solid for it rather than writing a sampler:

   ```bash
   uv run --project <skill> --frozen python <skill>/scripts/dt.py probe <canonical.stl> --section 12.5
   uv run --project <skill> --frozen python <skill>/scripts/dt.py probe <canonical.stl> --hole=-8,13 --z 1.2 --nominal 6.5
   ```

   Ask at the position the *sheet* gives, not the one the model used — that is the whole
   check. A run building to a published standard put its magnet pockets 0.25 mm off on both
   axes and declared them in the same wrong place, so eight checks measured a correct hole at
   an incorrect position and agreed. Probing at the standard's coordinate reports the drift
   per axis.

   This is the one instrument you may use freely, because it is the gate's own: a verifier
   and a designer cannot disagree by instrument if they share one. Anything you write
   yourself is a second uncalibrated instrument, and one archived run's own sampler read 137%
   high against known nominals before the run widened its bands to suit.
6. Read `still_requires_a_look` in the audit output before going further. Nothing in step 4
   reads `dimensions.md`, so a part that measures self-consistently and disagrees with what
   was asked for passes all of it.
7. Cover the rest by hand, per plan: check **2**, the full-travel insertion sweep, for any
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
8. Check **4**, and it is yours alone: look at the images. **Spend your effort here.** Across
   every verification this pipeline has recorded, the deterministic recomputation has never
   once disagreed with the designer's — it is the same instrument on the same bytes, and
   agreement is what it is for.

   Be clear about why you are looking, because the old reason has expired. Two parts once
   passed every scalar and were wrong anyway — one missing a countersink its own sheet
   required, one whose mounting flange had a slot cut clean through it — and for a long time
   those were the argument that only eyes could catch such things. They are now arithmetic:
   both fail `feature-*` checks in about 40 ms, and both have regression tests.

   What survives is narrower and sharper. **Every measurement is conditioned on somebody
   having declared what to measure; a render is conditioned on nothing.** A feature the sheet
   asks for and the model never built takes its own expectation with it — one parameter drives
   the geometry and the check together — so the part measures self-consistently and is missing
   a hole. Nothing in the numbers can report that. You are the only thing here that sees what
   is present rather than what was asked about.

   So: the tool renders sections, it cannot read them. Judge silhouette,
   feature shape, count, position, and handedness against the reference and the original
   photographs, and say what each view actually shows. A green scalar bundle is necessary,
   never sufficient — no number in it distinguishes a correct part from a plausible wrong one.
   Note occluded or misleading views and demand another camera when a view cannot settle the
   question. Then judge what no number decides: is the declared fit *strategy* implemented
   rather than merely inside its band, and does the part solve the stated problem? The print
   engineer owns fit strategy; you check the designer's implementation of it and never
   redeclare it.

   Scale this judgment by consequence class, never the deterministic gate above. An
   `INCONSEQUENTIAL` `FITTED`/`FULL` job needs the visual call and the fit-band judgment. A
   `CONSEQUENTIAL` `FITTED`/`FULL` one needs the whole of this step, with every occluded view resolved and the `SUPPORT_ALLOWED`
   contact inspection written out. What never scales down is that this step happens at all: a purely
   numeric `PASS` reintroduces the exact failure this role exists to catch, a part that
   satisfies every scalar and is the wrong object. Compare the sheet's feature inventory
   against what you can see, item by item — that comparison is the one this role owns
   outright, and no future check will take it over, because a check has to be told what to
   look for and you do not.
9. Verify export completeness and consistency: STL/STEP/3MF identities, closed solids,
   intended bodies, units, and no missing or stray components. `audit` has already run
   `contracts validate --require all` and `status`; read their rows rather than repeating the
   commands. `--require` is load-bearing, not decoration: without it an absent contract is
   silent, so a typo'd path or a project missing the manifest entirely exits 0 and reads as a
   pass. Treat any `UNIT_SCALE_MISMATCH` —
   the hard 25.4x inch/mm bbox check between the declared manifest and the re-imported STL —
   as a hard `UNIT_SCALE` reject, never a warning to note and pass. A
   `POSSIBLE_UNIT_SCALE_MISMATCH` warning still needs an explicit agent judgment call before
   `PASS`.
8b. Draft the report from your own recomputation rather than retyping it:

   ```bash
   uv run --project <skill> --frozen python <skill>/scripts/dt.py report --commission <verifier-dir>/commission.json         --out verification_report.md --job-id <job> --updated-utc <iso8601>
   ```

   It transcribes the numeric columns from the file you just produced and leaves every
   judgment blank — the verdict, the status, every visual observation, the whole upstream
   audit, and the three checks no tool computes. Answer each one; the report is not finished
   while a `<!-- REQUIRED -->` remains. Retyping a measurement is how the designer's receipts
   once came to describe a mesh nobody was shipping, and a report that arrived pre-concluded
   would be worse than that.

10. A `PASS` requires every applicable check to pass with evidence and no open critical
   upstream question.
11. A `REJECT` must identify defect, evidence path, expected versus observed value/appearance,
   named datum or print-plan rule, severity, and owning loop (`METROLOGY`, `PRINT_PLAN`, or
    `CANDIDATE_BUILD`). Never prescribe an unverified geometry fix as acceptance. Every
    changed STL hash requires a new fresh verifier context and a full seven-check rerun.
12. Enforce the shared plan-revision rule. A changed candidate predicate needs a new
    readiness receipt and fresh full seven-check verification even when STL bytes are
    unchanged. Bound P2 evidence added under an unchanged plan does not.
13. When `final_print_prep.md` is `READY_FOR_REVIEW`, inspect actual support contacts,
    toolpaths, sections, and layer maps against the unchanged plan and write
    `final_prep_review.md`. Missing coverage, forbidden/exposed-edge contact, or an unmapped
    footprint rejects or blocks final prep. This review never waives candidate verification.
14. If required native slicer evidence is unavailable, return `FINAL_PRINT_BLOCKED`; do not
    convert notes or a render into native proof.
15. Never copy the canonical STL into your own folder — `audit` reads it in place, and a run
    that duplicated it verified a copy of the thing it was sent to check. For a rejection,
    retain only the report, metrics, hashes, and defect-specific visual in addition to
    canonical artifacts.
16. Verify the delivered artifacts in place. Never copy the canonical STL into your own
    folder -- a run that duplicated it verified a copy of the thing it was sent to check.
