# Print-in-place mechanisms — hinges, springs, flexures, magnets

Catalog of mechanisms that print reliably. Universal rules: forces stay **in the layer
plane**; overhang-free or chamfered joints; chunky beats tuned (a good design prints at
any layer height/infill/material — never rely on slicer settings for function).
Gaps: ≥0.3 mm between PIP surfaces; 0.4–0.6 free-spinning; vertical ≥2 layers.

## 1. Hinges (pick by life + load)

| Type | How | Notes |
|---|---|---|
| Living (flap) | thin flexing web | Print on its side, flex in-plane. PP/TPU for real cycle life; PETG/PA a few gentle cycles; PLA never. Can't bend far. Never bridge it |
| Circular (arc) | arc spreads bending | Less wear + built-in spring-return (self-closing lid); less range; arc protrudes |
| Toothed circular | grooves cut into arc | More flex + life, less protrusion; tune via groove depth & count |
| Spring (distributed) | many small flexures | Long articulated columns; no single point flexes far |
| Slat (kerf) | slats twist in torsion | Woodworking-style; design around target bend radius |
| Axle, vertical print | axle axis vertical | Smooth precise rotation; **chamfer inner axle ends** or droop welds them; weak in torsion → make chunky |
| Axle, horizontal | layers through axis | Strong but bore sags oval → rough rotation; cheap parts |
| Cone | splayed cone in socket | Self-captive, rotates, no side travel; weak in twist → oversize |
| Double-cone | cones top+bottom, ~2 mm engage | Leverage-free, strong; overhang can fuse → hybrid profile (cone-step-cone), alternate cones per link, or print on side |

## 2. Printed springs (all flat, in-plane)
- Extension: coil profile printed flat as slot pattern. **Round every corner** — square
  corners are the crack sites. Member ≥1 mm (thicker = stiffer).
- Spiral/torsion: wind-up and self-closing lids; thicker feed = stronger, more coils +
  height = more energy.
- Leaf / parallel-leaf flexure stage: compress + shear; pair keeps orientation constant.
  Strength ≈ band thickness only.
- Stabilizer ring: extension springs around a perimeter = trampoline mount for buttons
  and vibration isolation.
- Any spring printed at an angle loses most return force. FDM can't do helical coils —
  use flat styles (or steel springs).
- Flat springs can be fully encased mid-print → assembled mechanism with zero assembly.
  Use-case: embedded leaf springs inside a knob bore grip any shaft shape/size.
- Compliant spring latches: design ~2 mm of travel; print-in-place vertical springs make
  sliding latches integral to an enclosure printed on its long edge.
- Flexures: thinnest possible for range; stack several thin instead of one thick for
  stiffness; ALWAYS add hard end-stops against plastic deformation.

## 3. Magnets (7 retention methods, best first)
- Press-fit cylinder (not disc — side-wall friction) into bore, arbor press it.
- Snap-lip pocket: press magnet past a small modeled lip; works for spheres too
  (self-orienting).
- Pause-and-insert mid-print: fully captive, invisible.
- Side slot after print: easy but leaves a wall that weakens pull.
- Latches: magnet + **steel ball/washer** on the other side — cheaper, and two magnets
  chip each other.

## 4. Pins & bosses
- Short and thick; length multiplies leverage stress. Fillet the base (root is where
  they snap). Vertical pins ≥ Ø5 or use steel dowel.
- Gear-tooth micro-cutouts around a pin cross-section = more perimeter per layer =
  stronger, slicer-independent. Slots plunged through pin into parent body anchor it
  like local dense infill.
