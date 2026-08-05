# Handoff prompt — next Claude session

Paste the block below into a fresh Claude Code session in `C:\github\3d-modeling-skill`.

---

Work from `claude/milestone-1`. Fetch first. Record `git rev-parse HEAD` and
`git status --short`. Expected head at handoff: `bb49eb8`. One writer only.

Draft PR: https://github.com/ghsi011/3d-modeling-skill/pull/1

## State at handoff

D15 and D28 are closed, mutation-tested (6/6 and 6/6), and pushed. Release 1 is
ruled `COMPLETE` with a nine-row proof table in `ROADMAP.md`. ROADMAP's stale
current-position blockers 1 and 2 are reconciled and a Releases 1-5 ledger is
added. D29 is deliberately held open with its reasoning recorded in
`docs/defects.md`. The draft PR carries the full evidence table.

## Task 1 — finish the PR gate (blocking merge)

Two items are outstanding on the PR checklist:

1. **L0-heavy at head `bb49eb8`.** Run `uv run pytest benchmarks/heavy -q` from a
   clean pinned worktree and post the result to the PR. A full-tier run was
   started at `f327687` and never confirmed; the only delta since is a
   docs-only commit (`git diff --stat f327687..HEAD` is two `.md` files). The
   Release-1 proof subset already passed from the pinned checkout. Do not report
   the tier green without a completed full run.
2. **CI on the PR** — both jobs, Linux, Python 3.11 and 3.12. The PR reports two
   Windows L0 failures separately and honestly; both reproduce at the branch
   point `62fe422`:
   * `tools/test_documentation.py::test_every_architecture_section_cited_by_name_exists`
     fails the 5 s L0 tier guard, not its assertion — it passes with
     `L0_TIER_GUARD=off` in ~20 s. Machine-speed sensitivity, documented in
     ROADMAP section 4.4.
   * `tools/test_diagnosis_l0.py::L0Damaged::...` asserts `boundary_edges == 332`
     and measures 322 — a mesh-library version difference in the very count D1 is
     about.

   If Linux CI shows the previously documented 13 Windows-assumption failures,
   confirm they are **exactly** those and report them separately. **No new
   failure may be hidden inside that allowance.**

Then mark the PR ready for review. Do not start another release slice,
benchmark feature, ontology, repair capability, or unrelated refactor.

## Task 2 — the queued authentic design project

After the PR gate closes, start the queued high-priority project. Full brief is
in memory at `queued-bee-porter-project.md`; re-read it before starting.

**Modular TPU one-way bee porter for a ten-frame Langstroth hive.** Retain the
project externally under `C:\projects\3d\langstroth-tpu-bee-porter\` — never in
this skill repository. The user uploaded a bee-porter reference photo and has a
completed engineering research report; preserve both unchanged as project
evidence. If the photo is not on disk, ask for it rather than proceeding without
it.

Twenty passages as four replaceable five-valve TPU modules; the wood is not
printed. V1 centre geometry is the centre of a prototype family and is **not**
production-proven: ~175x200 mm module, ~180 mm valve length, 35 mm lane pitch,
inverted-V tent of two flat TPU walls, 16.0 mm mounted-edge span, 8.5 mm tent
height, 3.25 mm resting slit, 1.0 mm wall, 0.7 mm rounded bee-contact edge,
30 mm flex-zone spacing, 20 mm asymmetric super-side entry, shielded
non-flared brood-side exit, shared replaceable mounting flange, no rigid bridge
across the working slit. Alternating external ribs on the lower walls;
**nothing hard may cross the bee passage at the ridge**.

Record or request only these genuinely blocking measurements first: inside box
width and length; frame-centre positions with ten frames installed; vertical
clearance under the porter board; board material and thickness; exact Polymaker
TPU variant; installed X2D nozzle and usable build area; whether drones must
pass; whether queen exclusion is required.

Five prototype stages, in order: print-calibration coupons (gaps 3.0/3.25/3.5,
walls 0.8/1.0/1.2, X/Y orientations, edge radii — keep designed and observed
values separate); mechanical coupons at 60-70 mm (add rib spacing 20/30/35 and
one retained alternative geometry; measure force at 4.0/4.5/5.0 mm opening,
immediate recovery, recovery after 10-minute and 24-hour holds, behaviour at
room temperature / 35C / 45C, permanent set, local versus neighbouring-zone
deformation, damage after cycling — beam theory is a **relative** sensitivity
estimate only); **directionality, mandatory and separate from stiffness**, with
three otherwise-equivalent coupons A symmetric, B funnelled+shielded, and
**C = B installed reversed** — the reverse control is what determines whether
the geometry creates directional behaviour rather than merely resembling an
arrow; safety screening with rounded gauges, soft surrogate bodies and thin
wing-like film near ribs, seams and transitions, rejecting anything that
catches, pinches, sharply buckles or needs precise alignment; then a limited
live-bee trial in a small observation fixture under the humane stop criteria
from the research report.

No full module proceeds unless the selected coupon shows safe forward passage
**and** materially reduced reverse passage. The first full-size deliverable is
**one five-valve module only**, with editable parametric source, STL and 3MF,
dimensional drawing, X2D profile assumptions, measurement fixture or gauges,
wooden opening and clamping template, installation drawing, test record, and
explicit unresolved physical claims. Prefer screws and removable clamping
strips; do not rely on glue or isolated staples as the primary seal or
retention.

**Stop condition:** stop once the coupon family, test fixtures, measurement plan
and one selected candidate are ready for printing. Do not claim a final bee
porter before the physical and live-bee stages are complete.

Promote only reusable lessons to the skill after physical evidence exists —
flexible-slit coupon generation, force/displacement records, warm-creep
evidence, designed-versus-observed flexible gaps, biological passage validation,
non-crossing spacer patterns. **Never** add bee-specific assumptions, TPU
compensation values, or unmeasured force thresholds to the general skill.
