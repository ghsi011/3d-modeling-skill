# Print troubleshooting — symptom → cause → fix

Rule out mechanical causes before touching slicer settings.

## Calibration order for every new filament
Temperature tower → pressure advance (PA depends on temp) → flow rate → retraction →
shrinkage cube (measure, store compensation) → save custom profile.
Shrinkage: scale per fdm-design §8's per-material table, or measure a test cube.

## First layer & adhesion
- Wash plate with degreasing dish soap — no aloe/moisturizer soaps.
- Z-offset 0.1 mm too high already ruins adhesion; too low → elephant foot, shifts.
  Enable a brim and babystep live at print start.
- Stubborn: Magigoo (material-specific), 3DLAC, Nano Polymer; brim/mouse-ears vs warp.
- Elephant foot: compensation setting + check bed temp against spool range.

## Extrusion
- Clogs: acupuncture needle or cold pull (~100 °C). Recurring clogs = heat creep →
  clean heatsink fan; open the door for PLA/PETG in enclosures.
- Under-extrusion, ranked: too fast > partial clog > slipping extruder gear > temp low.
  Fix flow with slicer's flow test; push temp toward manufacturer max.
- Pressure advance: corners gap = PA too high; corners round/mushy = PA too low.
- Stringing: temp too high, retraction wrong, or wet filament (popping sounds = wet).
  Last resorts: faster travel, avoid crossing perimeters.
- CF/GF wear: nozzle orifice no longer round → replace.

## Surfaces
- Poor top: over-extrusion on top layer → narrower top width, slower, +top layers,
  ironing. Pillowing over infill = cooling → +1–2 top layers cheapest fix.
- Weak layer bond: too fast / too cold / cold room / overcooled — lower fan but keep
  100 % on bridges & overhangs. Rotate part toward directional cooling ducts.
- Support scars: +Z-distance a notch, add interface layers (see materials.md §2).

## Motion artifacts
- Layer shifts: nozzle collisions (over-extrusion, curled edges, low/slow Z-hop),
  loose belts, debris in idlers, dry rails. Power off, move head by hand, feel for it.
- Ghosting/ringing: belt tension (check quarterly) + input shaping.
- Z-banding: bent lead screw, binding nut, temp fluctuation → clean/lube, PID tune.

## Field failure: PETG-CF parts knocked off mid-print (nuc feeder, 2026-07)

**Symptom:** part detached from textured PEI a few mm up, spaghetti; happened twice
identically, at the same layer band. Filament was dried (12 h @65 °C, AMS at 21% RH) —
so NOT moisture. The failure height matched the part's first heavy bridging layers.

**Root causes (compound):**
1. **Flat bridges + CF filament = nozzle strikes.** CF-filled PETG curls at bridge and
   overhang edges; the nozzle clips the curled strands every pass and eventually shears
   the part off. Repeatable failure at the bridge band is the signature.
2. **PETG-CF grips textured PEI worse than plain PETG**, and Bambu Studio's `auto_brim`
   frequently decides on NO brim — a tall part on a small/segmented footprint (spokes,
   arms, narrow rings) then has no adhesion margin at all.
3. **Long flat arms warp**: tips lift, nozzle taps them with big leverage at the ends.

**Fixes that must travel together (design + slice):**
- Design: never leave >8–10 mm flat down-facing bridges in CF materials. Corbel them —
  45° fillets (fuse a 45°-rotated square prism along each supporting edge) shrink the
  span without support material. Keep corbels clipped to where solid wall exists above.
- Slice: force `brim_type: outer_only` (do not trust auto_brim), and halve
  `bridge_speed` (X2D preset ships ["50","50","50","200"] per extruder variant — the
  override must match that array shape).
- Bed prep: wipe plate with IPA; glue stick adds margin for CF on textured PEI.
- When several parts share a plate, one knock-off wrecks all of them — consider
  printing the risky tall part alone first.
