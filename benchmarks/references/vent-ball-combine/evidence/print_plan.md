---
contract: print-plan
contract_version: 4
job_id: vent-ball-01
revision: 1
owner: print-engineer
status: ACCEPTED
dimensions_revision: 1
updated_utc: 2026-07-28T00:00:00Z
---

# Print plan

Owner note: no print engineer was dispatched; the orchestrator wrote this plan.
That is the weak point of the DIRECT route and it is recorded rather than hidden
— the party being measured wrote the threshold. The one number it could have
flattered itself on, the support budget, was set at 1700 mm² against a measured
1628 mm², and the orientation behind it was chosen by a 47-placement sweep whose
full table is below.

Machine-readable projection: `print_plan_checks.json`. This file is the reasoning
behind it, not a second source of requirements.

## Model-to-printer transform

| Item | Exact value |
|---|---|
| Transform/rotation | identity — the STL ships already in the print orientation |
| Bed-contact landmark | the outer side face of the leg at design x = +25 |
| Bed normal | (0, 0, 1) in the delivered file |
| Open/insertion direction | arm peg along the delivered +x; cradle onto the ball along +x |
| Forbidden downward faces | claw prongs, snap-bore walls, the phone-rest face, the sphere above its equator |

## Geometry rules and phase scope

| ID | Rule | Numeric limit | Verification predicate | required_now | deferred_owner | final_gate |
|---|---|---:|---|---|---|---|
| S-01 | Downward-facing area in the declared placement | 1700 mm² | `commission` support-S-01 | designer readiness + this gate | none | none |
| I-01 | Delivered sphere congruent with the source ball | −0.05 … +0.05 mm | `commission` fit-I-01 vs `reference_ball.stl` | this gate | none | none |
| I-02 | Arm peg seated in the leg bore | +0.09 … +0.18 mm | `commission` fit-I-02 vs `reference_peg.stl` | this gate | none | none |

## Orientation, and the trade it cannot avoid

`orient_scan.py` scored 47 placements — the eight axis-aligned ones plus a 15°
roll sweep about both in-plane axes — on the same downward-normal screen the
commission gate uses.

| placement | overhang mm² | bed contact mm² | height mm |
|---|---|---|---|
| **rot-y-90 (chosen)** | **1628** | **1233** | **50** |
| rot-x-120 | 1579 | 0 | 72 |
| rot-y-270 | 1634 | 1233 | 50 |
| rot-x-300 | 2342 | 8 | 72 |
| as-modelled (ball up) | ~5100 | 9 | 84 |

`rot-x-120` looks marginally better on overhang and is unbuildable: nothing flat
touches the bed. Of everything that can actually be printed, `rot-y-90` has both
the least overhang and by far the most bed contact.

**Print it on its side**, with one leg's outer face flat on the bed. The model
ships already in this orientation, seated at z = 0, so the slicer needs no
rotation and `model_to_printer_matrix` is the identity.

The reason is functional, not cosmetic. Every vent claw and every snap hook on
this part is a 2D profile extruded 15 mm across the plate. Lay that axis along
the build direction and those profiles become identical layers stacked on each
other: the claws — the features the whole mount depends on, and the ones the
user has already proved work — print with nothing under them and no support
anywhere near them.

**What it costs, plainly.** The ball's axis is normal to the phone-rest face,
which is what was asked for, and the claw profiles run across that face. Those
two directions are perpendicular, so no orientation puts the ball upright *and*
the claws flat. Printing the claws right means printing the ball on its side.
There is no orientation that avoids this, and the model cannot be changed to
avoid it without disobeying the brief.

## S-01 — SUPPORT_ALLOWED, budget 1700 mm² (measured 1628 mm²)

Support is needed in exactly three places, and nowhere else:

1. **Upper leg, ~1440 mm².** The second leg's cross-section appears at 35 mm
   with only the 6 mm backplate under it. Its downward face is flat and
   perpendicular to the build direction, so support releases cleanly. The face
   is the leg's inner side, which faces the arm's swept volume — knock any
   remaining nibs down flush before snapping the arm in.
2. **Ball and plinth, ~150 mm².** The sphere's lower cap and the underside of
   the plinth skirt.
3. **Top of the old ratchet channel, ~38 mm².** The channel is filled only up to
   y = 18 so the arm's pivot hub keeps its clearance, which leaves the fill's
   own end wall as a small downface. It is 20 mm wide and 3.4 mm deep and will
   bridge; support there is permitted but not required.

`required_now`: the exported STL must screen at or under 1700 mm² in the declared
placement. It does — 1628.06 mm² — checked by `commission.json`'s `support-S-01`.
`deferred_owner`: none. `final_gate`: none.

**Forbidden** — no support may touch a claw prong, a snap-bore wall, the
phone-rest face, or the sphere above its equator.

**On the sphere.** Support marks on a ball joint are the one place they matter,
because the cradle grips that surface. Use tree/organic support with the lowest
contact density the slicer offers so the scar is points rather than a raft, and
clean it back with a knife and 400 grit before the first fit. Print the ball
region a little slower and cooler if the profile allows — a sagging first
overhang layer under the sphere shows up as an out-of-round patch, which reads
as a loose cradle.

## Material

**PETG.** Not PLA. This lives on a windscreen-side air vent in a parked car;
PLA's glass transition is around 60 °C and a closed car in sun goes past it, and
the failure mode here is a phone landing in the footwell. PETG, ABS, ASA or
PC-blend all clear that. If only PLA is available, treat the part as a
fair-weather item and re-check it after any hot day.

Walls: the backplate is 6.0 mm and the plinth thicker, so nothing here is
wall-limited. Use ≥ 4 perimeters and ≥ 40 % infill — the load path from the ball
runs through the plinth into the plate as bending, and perimeters carry that,
not infill.

## Interfaces

| id | fit | band (per side) | measured | reference |
|---|---|---|---|---|
| I-01 | ball vs the cradle | −0.05 … +0.05 mm | **−0.0000 mm** | `reference_ball.stl` |
| I-02 | arm peg in the leg bore | +0.09 … +0.18 mm | **+0.1200 mm** | `reference_peg.stl` |

Neither band was tuned to pass. I-02's was derived from the two source solids'
own surface parameters before anything was measured — bore 2.000/2.600/2.000
against peg 1.900/2.440/1.900 gives 0.100 mm minimum, plus this build's 0.020 mm
mouth relief, so 0.120 mm — and the exported mesh measures 0.1200 mm.

I-01 is not a socket clearance, because nobody has the socket. It is a
congruence assertion: the delivered sphere against the source STL's own
spherical cap, moved exactly as the graft moves it. −8.5 × 10⁻¹⁰ mm means the
fusion did not move, scale or erode the ball by any amount a printer could
resolve.

No coupon. Both fits are inherited geometry that the user's own printed parts
already demonstrate; a coupon would be testing their prints, not mine.

## Print order and field test

1. Print the part. One piece. The arm and the top hook are **not** printed —
   the arm is unchanged and the user already has one; the hook is deleted.
2. Remove support. Sphere first, carefully; then the upper leg's inner face.
3. Snap the existing arm's pegs into the leg bores. It should click in and pivot
   freely. If it binds, the bore rebuild is the suspect — measure the mouth
   (should be 4.04 mm) before forcing anything.
4. Push the cradle onto the ball. Check it holds a phone's weight at full tilt
   *off the car*, hanging, for a few minutes.
5. Fit to the vent. Check the claws grip as before — nothing about them changed,
   so any difference means a print problem, not a design one.
6. **Before driving:** load the phone and shake the mount by hand, hard, in all
   three axes. Then drive a short familiar route before trusting it on a
   motorway. The ball is a new cantilever on a part that never carried one.

## Final prep

No slicer-dependent visual predicate is deferred, so no `final_print_prep.md`
round trip is owed. The support contacts named in S-01 are reviewed by the
post-print artifacts listed there, by the person holding the part.
