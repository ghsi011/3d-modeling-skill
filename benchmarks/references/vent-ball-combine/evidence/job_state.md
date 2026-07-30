---
contract: job-state
contract_version: 4
job_id: vent-ball-01
revision: 1
owner: orchestrator
mode: PIPELINE
profile: DIRECT
state: DELIVERY
backend: build123d
active_candidate: candidate-01
updated_utc: 2026-07-28T00:00:00Z
---

# Job state

## Brief

Combine two models the user has already printed and verified:

* `2026-05+17mm+ball+male+v1.stl` — a 17 mm male ball joint that fits their MagSafe cradle.
* `CAD+FILE.step` — a Tesla Model 3 air-vent phone mount that grips the vent well.

The vent mount is to carry the ball joint instead of its phone-holding mechanism.
The ball sits 90° to the face the phone rested against. The lips holding the
phone from above and below come off.

## Consequence

**CONSEQUENTIAL.** Vehicle-mounted, carrying a phone on a magnetic cradle in a
moving car. Two failure modes matter: the ball root snapping, and the vent grip
letting go. Either drops a phone into the footwell of a car in motion.

Nothing on `safety.py`'s `MANDATORY_CONCERNS` list applies — this is not
life-safety, load-bearing for a person, braking or steering, a pressure vessel,
a mains barrier, fire containment, or regulated structural/medical use. It is an
accessory that can become a loose object. That is the hazard to design against
and the one the user should judge before driving with it.

Prohibited claims for this job: not "safe", not "ready to use", not "verified".
Only what `final_status.json` / `commission.json` actually establishes.

## Route

**DIRECT in shape, with no certified template.** No template covers this — it is
a graft of two user-supplied solids — but the deciding question of the route
profiles is *what has to be recovered from evidence?* and the answer is
**nothing**. There is no photograph, no caliper reading, and no real object to
reconstruct. Both mating interfaces arrive as exact digital geometry the user
has already printed and validated:

* the 17 mm sphere and its neck, which the cradle grips;
* the vent claws and the arm snap bores, which the vent and the arm engage.

Both are carried through **unmodified**, so acceptance does not depend on a
dimension recovered by anybody. That is why no metrologist was dispatched
(recorded in `dimensions.md`) and why this did not route `FITTED`.

**No independent verification.** No fresh context has looked at this part. It was
authored, built, and checked by the orchestrator, and authors are blind to their
own errors. The strongest claim available is `COMMISSIONED`.

## What was changed, and what was not

| STEP solid | disposition |
|---|---|
| `solids()[0]` — top phone hook on its ratchet | **dropped.** It is the upper lip. |
| `solids()[1]` — pivoting vent arm | **untouched.** It reads like a third lip in a render but sits behind the plate and is half the vent clamp. Retained by pegs snapping into the leg bores, not by the hook, so dropping the hook does not free it. The user already has one printed. |
| `solids()[2]` — main body | **edited**, as below. |

Edits to the main body, all of them in the plate's own frame:

1. **Half-space cut at the phone-rest plane** — removes the lower phone lip.
   Checked first, not assumed: the only body geometry forward of that face lies
   at y ∈ [−35.6, −25.0], which is the lip and nothing else. The face comes out
   flush.
2. **Ratchet-channel fill** — the dropped hook rode in a channel that left the
   backplate 2.5 mm thick over a 20 mm width, right where the ball wants to
   root. Filled to the plate's own 6.0 mm.
3. **Plinth** — a tapered pad from 2 mm inside the backplate to 2.9 mm proud of
   it, standing 1 mm past the ball's base plate all round.
4. **Ball** — the source STL, unscaled and unrotated about its own axis, its
   base plate seated on the plinth and its axis normal to the phone-rest face.

## Two repairs that were not asked for

Both source solids ship with faces OpenCascade cannot triangulate at any
deflection, and neither `clean()` nor `ShapeFix` helps. Left alone they punch
holes in every export.

* **Leg snap bores (fixed).** The four cone faces of the two barrel bores. Each
  bore was plugged and re-cut from the STEP's own cone parameters — semi-angle
  16.0751°, ref radius 2.3, mouth d 4.000, barrel d 5.200 × 0.836, length 5.000.
  The repaired body's volume is 48336.18 mm³ against the original's 48336.22 — a
  0.04 mm³ difference, which is the one deliberate change below.
* **Mouth relief (deliberate, 0.020 mm per side).** A re-cut ending exactly at
  the mouth radius is tangent to the cone it continues and leaves a 0.0005 mm²
  annular sliver OpenCascade also cannot mesh — one unmeshable face traded for
  another. The stubs are therefore 2.020 mm rather than 2.000. It opens each
  bore mouth by 0.02 mm per side, roughly a tenth of FDM placement noise, and it
  moves the arm's seated clearance from 0.100 to 0.120 mm.
* **Arm peg cones (not fixed, not needed).** `solids()[1]` has the same defect
  plus a 274 mm² side face that drops out. The arm is not part of the
  deliverable — it is unchanged and the user has one — so it was rebuilt only as
  a *reference* for the fit check, from its own surface parameters.

## One defect this build introduced and then fixed

The first version filled the ratchet channel over its whole height, to the
backplate's own top edge at y = 30.01, on the reasoning that the channel had no
purpose once the hook was dropped. It had one: **the vent arm's pivot hub lives
in it.** The hub is a cylinder of radius 5.83 about the bore axis, so its crown
stands at z = −5.76 in every rotational pose, and a fill to z = −6.0 put 0.24 mm
of new material inside it. The arm would not have seated — not at some extreme
of travel, but in its designed rest position.

Nothing in the commission gate could have caught this. Every check it runs is
conditioned on the contract naming a feature, and the fit check was pointed at
the peg, which was fine. It was found by asking a question the gate does not
ask: *is any part of the arm inside the part I am shipping?*

The fill now stops at y = 18, and the channel above it is left exactly as the
source has it. `arm_travel.py` re-asks the question across ±40° of rotation in
5° steps and finds **zero arm vertices inside the delivered part at every
angle** — the worst extra penetration this build introduces is +0.0000 mm.
(The same script reports ~0.25 mm of apparent penetration against the *source*
body at every angle. That is not real: the source's bores are the unmeshable
cones described above, so its mesh has eight open circles and inside/outside is
undefined near them. It is a good illustration of why the bores were rebuilt.)

## Ball orientation

The base plate's long side (28.3 mm) runs up the plate, so the longer footprint
resists the phone's tipping moment, which acts about the across-plate axis. That
also puts the source ball's 0.46 mm neck fin on the underside. The fin is
carried through, not removed.

## Print orientation

`orient_scan.py` scored 47 placements. The ball axis and the vent-claw profiles
want orthogonal build directions and no orientation gets both — see
`print_plan.md` for what was chosen and what it costs.

## Outcome

`commission.json` verdict **PASS**, 8 of 9 checks run (`step` skipped: the part
finishes through the mesh path, so it ships as STL only and there is no editable
B-rep for a downstream consumer). Delivered as `candidate-01.stl`,
sha256 `5d2d7324e87a195e…`, 19 522 triangles, watertight, one body, 50.1 cm³.

**Allowed claim: COMMISSIONED.** The geometry was measured against the contract
written before it and matched, and nobody independent looked. Not VERIFIED, not
safe, not ready to use — it has not been printed.

## Open risks

1. **Nothing has been printed.** Every number here is geometry.
2. **The ball root is new load path.** The neck's 23.6 mm² throat is still the
   weakest section and is the source part's own, but that part was never a
   cantilever in a car before. Untested.
3. **No fresh context verified this.**
4. **The vent grip now carries more moment** than it did: the phone hangs off a
   ball 22 mm proud of the plate instead of resting against the plate.
