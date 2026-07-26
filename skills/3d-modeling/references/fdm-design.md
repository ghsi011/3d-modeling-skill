# FDM design reference — numbers and tactics

Values assume a tuned 0.4 mm nozzle, 0.2 mm layers. Sources at end.
Deeper dives: [mechanisms.md](mechanisms.md) (hinges/springs/magnets),
[materials.md](materials.md) (filament picks, support pairings),
[troubleshooting.md](troubleshooting.md) (symptom→fix).

## 1. Printability rules

- Overhangs ≤ 45° from vertical always print clean; well-cooled modern machines manage
  50–60° in PLA. Design to 45, accept 50 when unavoidable.
- Bridges: reliable to ~50 mm on a well-cooled machine; past that add an internal rib every
  25–50 mm. Expect visible droop over ~25 mm — keep those spans off show faces. CF/GF is
  the exception: 8–10 mm flat-bridge ceiling (troubleshooting.md). Long shallow curves/
  fillets under a surface: keep ≤30° from horizontal or they need support.
- Walls: 1 mm design rule (0.8 mm = 2× nozzle is the bare geometric floor; side extrusion
  eats the margin). Keep thickness a multiple of line width (1.2/1.6/2.0) or the slicer
  gap-fills. Vertical pins ≥ Ø5 mm or they snap — use steel dowels below that.
- Text/detail (single-color engrave/emboss): ≥3 mm tall, stroke 0.5–1 mm wide; engraved
  0.5–1 mm deep; embossed 0.5–0.75 mm tall, never >1 mm (sags); deboss beats raised,
  cleanest on vertical faces, never on the bed layer. Multi-color inlay strokes need
  ≥0.8 mm (§6). Surface textures ≥0.4 mm wide (nozzle width); knurling 0.5 mm wide /
  0.5 mm spacing.
- Slicer manipulation: a 0.2–2 mm wide slot or disc cut through a region forces the
  slicer to build solid perimeter walls there — free local reinforcement around holes,
  bosses, and rods without touching infill settings.
- Vertical holes: 1 mm fillet on the top edge = screw funnel + stops top-layer pull-out.
- Vents: 45° slats as thin as 0.5 mm; overlap + stair-step the slats to block water
  splash while passing air.
- Holes print undersized: +0.3–0.5 mm on Ø2–3, +0.2–0.4 on Ø3–8, +0.2–0.3 on Ø8–12.
  Oversize in CAD or use slicer X-Y hole compensation (0.05 PLA / 0.1 PETG-ABS);
  drill/ream critical bores. §4 fit clearances are ON TOP of this correction for mating
  bores — apply hole compensation first, then the fit clearance; don't confuse the two.
- Chamfer horizontal/overhanging edges; fillet only vertical edges. Never fillet into the
  bed plane (creates a near-0° overhang). Bed-contact chamfer size: §9.
- Horizontal holes: teardrop (to ~Ø4) or flat-roof/diamond with +0.4 mm above nominal.
- **A rectangular opening through a vertical wall is a different problem, and the teardrop
  advice does not reach it.** A bore's roof is a curve, so gabling it works; a rectangular
  opening has a flat lintel with nothing under it *anywhere across the wall thickness*, so
  there is no direction to gable it in. Widening or filleting the corners does not help
  either. The fix is to stop making one opening: split it into narrow openings, each gabled
  across its own width, and leave a mullion between them. A window, a vent and a screened
  panel are all this shape, and a hive job spent a large part of its design time
  rediscovering it.

## 2. Orientation & strength

- Across-layer (Z) strength: design as if half. Never load a cantilever root, screw boss,
  or snap arm across layers.
- Orientation decision order: (1) big flat face on bed, (2) overhangs minimized/designed
  out, (3) layers aligned with load, (4) cosmetic faces up/outward — never on supports,
  (5) seam on a hidden or sharp edge, (6) multi-color layers as low as possible.
  Conflicts? Split the part (dovetails or pins + glue), each half in its ideal orientation.
- One-piece boxes/enclosures: print **diagonally on an edge at 45°** (lids/trays ~35°)
  — box+lid pairs instead get a diagonal parting line, §9. Diagonal printing kills
  supports, layer lines loop through every wall (no single weak splitting plane), uniform
  finish on all faces. Flatten a small land on the down edge for bed adhesion.
- Strength budget: perimeters >> infill. Structural default: 4 walls, 5 top/bottom,
  15–20% gyroid (continuous path also relieves warp). Past that, add walls, not infill.
- That default is for a part meant to be **stiff**. It is wrong for one meant to
  **flex**: a snap-on shell, case, clip or living-hinged lid engages by deflecting,
  and wall thickness is the stiffness knob — 4 perimeters can make a case that will
  not clip on, or that cracks instead of springing. Use 2–3 perimeters (0.8–1.2 mm)
  there, and treat the number as a fit decision, not a strength one.
- On any part that **wraps** a mating object, the wall is also a dimension: it enters
  the external envelope twice, and it eats the internal pocket. Going 1.6 mm instead
  of 1.0 on a phone case adds 1.2 mm to width and thickness and ~46% to material —
  measured against a real printed case, which uses ~1.0 mm. Declare the wall in the
  plan alongside the clearances, not as a slicer afterthought.
- FDM cost ≈ surface area, not volume: thick voluminous parts beat thin-walled/ribbed
  ones (weight-saving cutouts often ADD time and material). Don't model internal
  cavities — let honeycomb infill lightweight it; modeled thin shells put layer seams
  at stress concentrations.

## 3. Designing out supports

- Put 45° chamfers under every boss, counterbore, and side protrusion.
- Sacrificial bridge: roof a counterbore with one bridged layer, drill/punch after; leave
  0.4 mm droop clearance under any bridged roof that matters.
- Model break-away tabs with a 0.2 mm (1-layer) gap where a slicer support would scar.
- Designed bed helpers, exact numbers: raft 1 mm thick; brim 0.2 mm (one layer);
  tie-down struts 1 mm wide; one-layer "velcro" connection points 0.4–0.5 mm. Large flat
  first layers: warp-relief checkerboard cuts 0.5 mm deep, ~25 mm apart (deeper warps more).
- Internal steps: widening-upward needs nothing; narrowing-upward creates internal bridges
  — flip the part or chamfer the transition.
- Prefer a designed bridge (or a 1-layer sacrificial floor punched out after) over any
  support — span limits per §1.
- When support is unavoidable, **model it in CAD** so every print is identical: triangular
  fins parallel to the overhang, body 0.5–1 mm off the part, connected by 0.5 mm snap
  prongs; ~0.2 mm top gap, 0.2–0.3 bottom; 45° the fins themselves; wide base; chamfer
  so they break away by hand. "Thumbtack" pin supports stabilize tall diagonal parts.
  Cut holes through sacrificial blocks (crush to remove) and emboss "SUPPORT" on them.
  Trick: generate tree supports in a slicer's SLA mode, export STL, place in CAD.

## 4. Fits & tolerances (per-side clearance — store per-side values in Params cells / PARAMETERS variables)

- Press: 0.0–0.1 mm · snug: 0.1–0.2 · sliding: 0.15–0.3 · loose: 0.3–0.5 ·
  free rotation: 0.4–0.7. PETG/ABS want +0.05 over PLA. Mating parts from another
  printer: 0.5. (Diametral = 2× these.)
- Press-fit insurance: 3–4 crush ribs 0.2 mm proud inside a +0.4 mm bore — ribs deform
  plastically, bore doesn't crack — but **single assembly only** (refit force collapses).
  For repeated assembly use **grip fins** (thin elastic fins that flex, not crush):
  fin ID 1 mm under the rod diameter (11 mm ID grips a 12 mm rod), 0.3 mm clearance gap
  behind each fin — constant grip that also absorbs shrinkage.
  Hex/square bores tolerate interference better than round.
- Alignment: **diamond pins** — square pins rotated 45° in diamond holes — self-center
  and print sideways with zero overhang sag (round pins print oval on their side).
  Panel edge-joins: curved **spring T-slots** that compress on insertion.
- Compliance beats precision: a fit tuned on one printer/material won't transfer. Build
  in flex — slot behind a wall so it springs (gap 0.3–0.5 mm), chamfer mating lid edges
  so parts wedge over a range, cut away box corners (least accurate region, where fits
  bind). Assume ±0.1 mm per surface; single-layer features run undersized.
- Tight or unknown fit → print a coupon first; `fit_coupon()` owns the offset ladder (it
  brackets nominal both ways, which pegs need) — [designer-toolkit.md](designer-toolkit.md).
  Ten minutes of printing saves the real part.
- Snap fits: taper the arm toward the tip, base fillet ≥ 0.5× thickness, deflect only
  during assembly, print the arm lying in the layer plane. PETG/ABS/PA — PLA arms shatter.
- Threads: printable down to ~1/8" (≈3 mm) major diameter — below that no nozzle resolves
  a crest. Model vertical, 0.15–0.3 mm radial clearance, trapezoidal profile, features
  2–4 mm; horizontal threaded holes: cut away the thread's top and bottom arcs (sag zones)
  — sidewall threads alone grip the screw. Under 1/8" use heat-set inserts; above it
  printed threads hold, but inserts still win for repeated assembly (hole Ø4.1–4.3 for M3,
  blind hole +1 mm, 1–2 mm solid plastic around the hole, iron ~10–20°C above print temp)
  or captive nuts (pocket +0.1–0.2 mm, pause-and-insert, bridge over) — a flanged nut
  dropped in mid-print with plastic grown over it is pull-out-proof.

## 5. Print-in-place & moving parts

- Gaps: 0.3 mm minimum between PIP features (0.4–0.6 free-spinning). First motion
  "cracks" the joint free — keep contact area small.
- Living-hinge web: 0.2–0.5 mm thick × 3–6 mm span, filleted.
- Everything else — 9 hinge types, hinge/flexure materials, printed springs, magnet
  retention, hard stops, pin strengthening: [mechanisms.md](mechanisms.md).

## 6. Multi-color / multi-material

- **Waste economics**: single-nozzle AMS purges on every swap (dark→light ≈ 3× light→dark;
  a 12 g model can make 70 g waste). Prime tower height = last color-change layer, so
  concentrate color in few, contiguous, **low** layers. Dual-nozzle (X2D/H2D): ~zero purge
  between two materials; >2 colors still purge within a nozzle group.
- **Face-down graphics**: mirror text/logo into the bottom face, colors in layers 1–3 —
  minimal purge, razor-sharp boundaries, uniform plate finish. Guard with elephant-foot
  compensation ≥ 0.15 so thin strokes don't bleed. This also shrinks the prime tower.
- **Flush inlays**: cut the recess and the inlay from the same sketch, zero clearance
  (same-layer extrusions fuse); 0.4–0.6 mm deep (2–3 layers) hides the base color; stroke
  width ≥ 0.8–1.0 mm, bold sans fonts. Export as one 3MF via scripts/make_3mf.py.
- **Free color tricks**: color-change-at-Z (pause/M600) gives per-band color with zero
  purge and no AMS; engrave-and-paint-fill or a sticker recess when only one filament.
- **Bonding matrix**: same polymer = welds. Welds well: ABS↔ASA, PETG↔TPU, ABS/ASA↔TPU,
  PETG↔ABS. Separates cleanly (use as support interface or avoid as structure):
  PLA↔PETG, PLA↔ASA/ABS, TPU↔PLA, PA↔almost everything. Co-printed colors must share a
  polymer family or be mechanically interlocked (dovetails, through-holes, captive geometry).
- Mixed-material jobs share one bed/chamber: don't pair PLA with ABS/ASA (bed 60 vs 95 °C,
  chamber heat-creeps PLA); PLA+PETG at ~60–65 °C is the workable odd couple.

## 7. Material by environment

Parked car in sun (cabin 60–80 °C, dash to 105 °C): ASA/ABS/PC only — PLA fails, PETG
marginal. Outdoors year-round: ASA. Always propose the PLA fit-test before printing the
final in engineering material.

## 8. Finishing tricks

- Model texture in CAD (knurl, crosshatch, noise), not in the slicer — it travels with the
  file and is free in FDM (vs tooling cost in molding). No raised detail thinner than nozzle.
- Seams distort round walls up to 0.4 mm and protrude into holes — give the slicer a
  sharp concave corner (≥120°) to hide the seam in, or align to a hidden edge. Vertical
  holes: a 120° teardrop corner does the same job.
- Warping: CAD-modeled mouse-ear tabs (0.2–0.4 mm discs) release cleaner than brim;
  rounded outer contours warp less than sharp corners.
- Shrinkage scaling: ABS ~0.4–0.8%, ASA ~0.6%, PLA ~0.2–0.3% — or measure a test cube.

## 9. Production rules (print-farm wisdom — cheap insurance on any print)

- **Design slicer-agnostic**: every functional feature lives in CAD, never in slicer
  settings — the part must print right at any layer height, infill, or machine.
- First layer: as close to a circle as possible — no sharp corners, no text, minimal
  area on the bed face; sharp first-layer corners are the #1 warp/curl failure. Slightly
  recess (bow) large bottom faces to cut contact area.
- Chamfer every bed-contact edge 45° × 1 mm (machine-independent elephant-foot immunity,
  beats slicer compensation); 0.5 mm where a brim gets trimmed off that same edge.
- Round/fillet every vertical edge ≥1 mm: the nozzle never decelerates into corners →
  faster, stronger, more accurate, less ringing. Inner corners: chamfers stair-step
  predictably. Replace thin flat mounting tabs with chunky monolithic tabs grown from
  the body, chamfered underneath.
- Enclosures: cut the box/lid parting line diagonally so both halves print belly-down
  supportless; square lids with cut-out corners wedge tight on the flat walls; grip fins
  hold lids at constant pressure; quarter-turn lids = nub + channel <2 mm deep (or
  chamfered); sliding latches = print-in-place spring with ~2 mm travel. Hide any box
  inside an organic shell by boolean-cutting the cavity + standoffs into it; integrate
  DIN-rail / extrusion / strap mounts directly into the body.
- Batch tricks: group parts on a 1 mm raft (whole batch ejects as one), connect
  multi-part assemblies with snip-sprues so they ship assembled, stand large panels on
  edge held by thin fins.
- Invisible extras: text/logo/barcode embedded 0.5–1 mm under the surface reads only
  when backlit. Internal glue channels: assemble dry, inject glue at one port, channels
  route it everywhere — doubles as internal rebar.
- Fillet every feature-to-body transition — sharp inside corners are where FDM cracks.
- Zip-tie channels: ~4.8 OD / 3.2 ID tube sections, perpendicular to layers.
- Shadow lines: deliberate 0.5–1.5 mm gaps between mating shells hide fit imperfections.
- Zero post-processing target: no supports, no bed-face cleanup, textures hiding layer
  lines — every human touch multiplies cost at volume.

## 10. Domes, curves & rotors

- Domes: make them egg-shaped/oblong (steeper overhang) or keep the outside spherical
  and cut the inside to a cone — the sag is always internal. If support is needed, a
  designed internal "mushroom" 0.5 mm below the arch apex, or flatten the interior apex
  so slicer supports get a clean pop-off target.
- Spheres: cut a flat base at 60° tangent; or lift on a disc + fat 1 mm pin; star-pattern
  fin supports offset 0.2 mm beat solid cylinders (airflow → no thermal shrink lines).
- Shallow top curves stair-step: drop to 0.1 mm layers, or facet the curve deliberately,
  or pixelate it in 1 mm steps as an aesthetic, or hide it under noise/knurl/concentric
  rings; a domed lid with a flat edge chamfer can print on its side instead.
- Vase mode: one continuous contour per Z, no islands/holes, line width 150–200% of nozzle;
  prismatic folds for rigidity; never a flat roof — slot the ceiling to keep one outline.
- Propellers/fans: hub flat on bed, blade pitch >45° (shallower → designed vertical
  supports 0.3 mm off, twist away); a thin ring joining blade tips = permanent support;
  serrated/micro-blade leading edges are free in FDM.
- Rings with clips: best printed on their side on an octagonal outer flat; clips at 45°
  to the bed so they don't align with the weak layer plane; bottom clips moved to touch
  the bed need no support.

Sources: hubs.com/knowledge-base (FDM design, snap fits), blog.rahix.de/design-for-3d-printing,
cnckitchen.com (layer adhesion, inserts), wiki.bambulab.com (shrinkage, flush,
TPU), help.prusa3d.com (purging volumes), toms3d.org (material combination tests),
bambulab.com/en/filament-guide, orcaslicer.com/wiki (flush options), Slant3D channel
(production DFAM, supports, tolerances, mechanisms), The Next Layer (filaments,
troubleshooting), Planet 3DP (X2D support-interface tests).
