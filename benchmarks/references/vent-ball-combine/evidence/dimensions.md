---
contract: dimensions
contract_version: 4
job_id: vent-ball-01
revision: 1
owner: metrologist
status: ACCEPTED
updated_utc: 2026-07-28T00:00:00Z
---

# Dimensions

Owner note: no metrologist was dispatched. The orchestrator wrote this sheet, for
the reason immediately below.

## Why no metrologist

There is no real object to recover. Both mating interfaces already exist as
digital geometry the user has printed and verified — a STEP of the vent mount
and an STL of the ball — so every fit-critical dimension is *read off the source
files*, not reconstructed from photographs or calipers. A metrologist given one
source can only transcribe it.

What that means for confidence: rows marked **inherited** are not measurements at
all. They are the source geometry, carried through unchanged, and their accuracy
is whatever the user's own printed parts already demonstrated. Rows marked
**chosen** are mine and carry no such evidence.

## Datum

The design frame is the phone-rest face of the vent mount's main solid — a face
the STEP defines exactly, 3000.0 mm² and planar:

| datum | value (STEP coordinates) | source |
|---|---|---|
| face centre | (7.980, 11.900, 33.040) | `import_step(...).solids()[2]`, the only 3000 mm² planar face |
| face normal | (0, −0.934, +0.358) | same face; 21.0° recline from vertical |
| in-plane x | (1, 0, 0) | the plate's 50 mm width direction |

Design frame: **x** across the plate, **y** up the plate, **z** out of the face
along the ball axis. Origin at the face centre, so the face is the plane z = 0.

## Table

| # | dimension | value (mm) | provenance | confidence | blind-build completeness |
|---|---|---|---|---|---|
| 1 | phone-rest face | 50.00 × 60.00 | inherited (STEP planar face, area 3000.0) | A | the face the ball mounts to |
| 2 | face recline from vertical | 21.0° | inherited (face normal) | A | sets the ball's direction in the car |
| 3 | ball diameter | 17.00 | inherited (sphere fit r = 8.448 on 11 174 vertices, residual mean 0.238; faceted 16.90 inscribed / 17.12 circumscribed) | A | the cradle socket's mating surface |
| 4 | ball base plate | 20.30 × 28.30, corner r 4.04 | inherited (section area 560.47 at its own z 1.52) | A | the footprint the plinth must carry |
| 5 | ball centre above its own base | 20.579 | inherited (sphere fit) | A | preserves the cradle's swing clearance |
| 6 | neck throat | 23.6 mm² at its own z 12.5 | inherited | A | the joint's real weakest section; untouched |
| 7 | neck fin | 0.46 thick, out to r 6.17 | inherited | A | present in the source; carried, not removed |
| 8 | vent-arm snap bore | mouth d 4.000, bulge d 5.200 × 0.836, length 5.000, cone semi-angle 16.0751° | inherited (the STEP's own cone surfaces) | A | retains the pivoting arm |
| 9 | bore axis | design (x ±12.5, y 25.00, z −10.77) | inherited | A | both legs |
| 10 | backplate thickness, sides | 6.00 | inherited (ray cast) | A | what the plinth roots into |
| 11 | backplate thickness, ratchet channel | 2.50–3.10 over x ∈ [−9.75, +10.25] | inherited (ray cast, 2 mm grid) | A | **the reason the channel is filled** |
| 12 | ratchet channel rails | 8.00 thick over x ∈ ±[9.5, 13.0] | inherited | A | absorbed by the fill |
| 13 | lower phone lip | forward of the face, y ∈ [−35.6, −25.0], reaching z +19.0 | inherited | A | **removed** — the only material forward of the face |
| 14 | top phone hook | STEP solid[0], 50 × 25.8 × 46.7 | inherited | A | **removed** — dropped entirely |
| 15 | ratchet-channel fill | x ±14.0, y −12.0 → +30.01, to z −6.0 | chosen | D | brings 11 up to 6.00 under the ball |
| 16 | plinth height above face | 2.90 | chosen | D | clears the base plate's bottom rounding |
| 17 | plinth ledge past the ball base | 1.00 per side | chosen | D | avoids a coplanar boolean at the base wall |
| 18 | plinth buried depth | 2.00 below the face | chosen | D | avoids a coplanar boolean at the face |
| 19 | plinth footprint at the face | 27.0 × 35.0 | chosen (derived from 16–18) | D | 3.35 mm skirt each side |
| 20 | ball centre standoff from the face | 22.179 | chosen (derived: 1.6 + 20.579) | D | 1.6 mm further out than a flush mount |
| 21 | bore mouth relief | +0.020 per side | chosen | D | see job_state.md; the alternative was an unmeshable face |
| 22 | overall, print frame | 84.11 × 65.61 × 50.00 | derived from 1–20 | A | |

## Resolved at intake

* **"90 degrees to the face the phone rests against"** — read as the ball's stem
  axis normal to the 50 × 60 face, so a cradle on the ball hangs parallel to
  that face. The ball's base plate sits flat on it. Not read as 90° to the car's
  vertical: the face reclines 21°, and the user named the face, not the car.
* **"remove the lips holding the phone from above and below"** — the upper lip is
  the whole ratcheting hook assembly (STEP solid[0]), dropped; the lower lip is
  the shelf forward of the face, cut. The pivoting vent arm (solid[1]) looks like
  a third lip in a render but is behind the plate and is half the vent clamp, so
  it stays.
* **Ball rotation about its own axis** — the base plate's long side (28.3 mm) runs
  up the plate, the short side (20.3) across. Chosen so the longer footprint
  resists the phone's tipping moment, which acts about the across-plate axis.
  This also puts the neck fin on the underside.

## Blockers

None outstanding.
