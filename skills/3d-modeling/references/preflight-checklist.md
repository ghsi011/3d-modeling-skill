# Pre-print validation checklist (FDM functional parts)

Run this as a **gate before exporting final STL and before slicing** any design meant to be
manufactured — especially multi-part functional assemblies, threaded/sealed parts, and stiff
carbon-filled filaments (PETG-CF, PA-CF) on the Bambu X2D. It exists because a design can pass
watertight/interference checks in CAD and still fail on the plate: e.g. the nuc-feeder drip
barrel was knocked off the bed twice at its bridge layers even with dried filament (see
[troubleshooting.md](troubleshooting.md) → "PETG-CF parts knocked off").

Sources: the **3D Design NotebookLM** corpus (DFAM lectures, print-troubleshooting + filament-
calibration videos, DfAM papers), cross-checked against Bambu Lab's PETG-CF TDS/wiki and
community reports. Numbers are starting points — a calibrated printer + material beats any table.

How to read it: each item is **PASS / FIX / N/A**. Any FIX with no mitigation = do not print yet.

---

## A. Geometry / DFAM (fix in CAD, before STL)

### A1. Bed adhesion & knock-off (the #1 mid-print killer)
- [ ] **Footprint vs height sanity.** Tall part on a small or *segmented* footprint (spokes,
  arms, rings, a cylinder on legs) is the classic knock-off. If height ÷ min-footprint-width is
  large, add a brim (slicer) AND/OR widen the base contact.
- [ ] **First-layer chamfer.** 0.5–1 mm chamfer on every bottom edge — kills side-extrusion
  "elephant lip" and gives a clean transition. (Also enable slicer elephant-foot compensation.)
- [ ] **Round vertical corners** on the first layer so the nozzle never makes a sharp 90° turn
  it can drag the part up by. Sharp bottom corners are where peel starts.
- [ ] **No text / logos / tiny cosmetic holes on the first layer** — small tool moves warp and
  drag; move them up a few layers or emboss instead of engrave on layer 1.
- [ ] **Tall thin risky feature?** Design a **sacrificial support fin** (0.5–1 mm wall, parallel,
  0.5–1 mm gap, joined by horizontal 0.5–1 mm breakaway prongs) rather than trusting auto-supports.
- [ ] **Custom brim / mouse-ears** (if used) modeled at exactly one layer (0.2 mm) thick.

### A2. Warping of thin/flat features
- [ ] **Large flat base** → checkerboard the underside: ~1 mm-deep cuts, ~25 mm (1") apart, to
  break the continuous shrink lines. (Do not breach the outer wall.)
- [ ] **Long flat sidewalls** → add ~1 mm wrinkle/ripple/slight curve so shrinkage straightens
  the ripple instead of lifting the corners.
- [ ] **Interrupt internal tension** → small circular cavities / narrow slits inside the model
  break long diagonal infill runs that pull corners off the bed.

### A3. Overhangs & bridges (tightened for carbon-filled/stiff filaments)
- [ ] **Overhang angle:** self-supporting surfaces should rise ≥ 45° from horizontal (≤ 45° from
  vertical). **30° from horizontal is the absolute floor** before you need support/redesign.
- [ ] **Bridge span:** general max reliable unsupported bridge ≈ 25–50 mm (1–2"); add an internal
  rib every 25–50 mm to break longer spans. **For PETG-CF/PA-CF, be far more conservative** —
  fibers make edges *curl up* proud of the layer, the nozzle then clips them and shears the part
  off. Keep flat bridges short (target < 8–10 mm) or eliminate them with corbels.
- [ ] **90° overhang → 45–60° CHAMFER, never a fillet.** A fillet is tangent to horizontal at
  the top → an infinite 0° overhang that droops. Chamfers give a self-supporting stair-step.
  (Corbel technique: fuse a 45°-rotated square prism along each supporting edge to shrink a flat
  bridge span without support material; clip it to where solid wall exists above.)

### A4. Mating parts, threads & seals
- [ ] **Moving/snug fit:** start at **0.2 mm** gap between parts. Pin-in-hole: hole **0.25–0.5 mm**
  larger than the pin.
- [ ] **Horizontal (side-printed) holes** shrink more from overhang sag → give them extra clearance,
  or print undersize and ream.
- [ ] **Airtight/precise hole:** model **0.5 mm undersize** and ream/tap to final size post-print.
- [ ] **Printed threads:** none below ~1/8" (≈3 mm) major diameter — nozzles can't resolve them.
  Model thread crests/roots as **45° triangular cuts** (no horizontal overhang). A **horizontally**
  printed threaded hole should have its top+bottom thread arcs deleted in CAD, leaving only the
  clean vertical sidewalls to grip.
- [ ] **Pressure/gasket faces:** force solid material by embedding thin (0.1–2 mm) slots/cuts in
  CAD so the slicer lays dense perimeters exactly there, rather than hoping infill fills it.

---

## B. Material & calibration preflight (do once per filament/printer)

- [ ] **Filament dried.** PETG/PETG-CF are hygroscopic. Bambu PETG-CF: **65 °C / 8 h** (dryer) or
  heatbed **75–85 °C / 12 h**. Note: drying alone does **not** cure adhesion/bridge failures.
- [ ] **Hardened steel nozzle** installed for any carbon/glass-filled filament (abrasive).
- [ ] **Calibrated, in this order** (each has a "correct value" tell):
  1. **Temperature tower** → pick the *highest* temp that still bridges/overhangs cleanly with
     minimal stringing (higher = better layer adhesion + higher max flow). Bambu PETG-CF nozzle
     range **240–270 °C**.
  2. **Max volumetric speed** → find Z of first defect/sheen change, read flow at that height,
     subtract 10–20%. This hard-caps your real print speed.
  3. **Pressure / linear advance** → run the PA pattern **at your actual outer-wall speed/accel**;
     correct = sharpest corner with no gaps.
  4. **Flow ratio / extrusion multiplier** → correct = top surface with no gaps between lines.
     (For airtight parts, bias slightly high — e.g. ×1.02 — for wall fusion.)
  5. **Retraction** (optional) → lowest value with no stringing; too high pokes holes in walls.

---

## C. Final 3MF settings to verify before you hit slice

Confirm these are actually in the project, not just "probably inherited." Right column = the
values baked into the nuc-feeder PETG-CF X2D project as a worked example.

| Setting | Target for a sealed PETG-CF part | Nuc-feeder 3MF |
|---|---|---|
| Filament / nozzle map | correct material on the intended nozzle | PETG-CF, MAIN (direct-drive) |
| Walls / perimeters | **≥ 4** for any pressure/airtight wall (perimeters > infill for strength) | 4 |
| Top / bottom layers | +1–2 extra tops to avoid pillowing | 5 / 3 |
| Infill | 15–30% functional; gyroid for isotropic sealing | 30% gyroid |
| **Brim** | **outer, ≥ 5 mm — set explicitly; do NOT trust `auto_brim`** (it gave our part none) | outer_only, 5 mm |
| **Bridge speed** | **halved** vs default for CF (curl control) | 25 mm/s |
| Flow ratio | calibrated; ~×1.02 bias for airtight walls | 0.969 (×1.02) |
| Nozzle temp | in material range (PETG-CF 240–270) | 255 °C |
| Plate temp / type | PETG-CF 60–80 °C; the plate you actually own | 70 °C, Textured PEI |
| Part-cooling fan | **PETG-CF 0–40% general**; full fan only on overhangs/bridges | 40% max / 100% overhang |
| Elephant-foot comp | ~0.15 mm (with the CAD chamfer, not instead of it) | 0.15 mm |
| Seam position | hide inside/rear away from threads & sealing faces | aligned* |
| Max volumetric speed | your calibrated cap | 11.5 mm³/s |

\* For threaded sockets, prefer a rear/hidden seam so a seam blob doesn't tighten the thread fit.

**Slicer sanity preview:** confirm **0 support material** (unless intended), brim actually renders
around **every** part, and the bridge/overhang regions are the only blue "overhang" faces.

---

## D. Bed prep & first-layer watch (at the machine)

- [ ] **Degrease the plate** with dish soap (no aloe/moisturizer) or IPA; don't touch it after.
- [ ] **PETG-CF ↔ textured PEI is a known weak combo on big/tall parts** — corners lift / parts
  come loose in a narrow Z-window. A thin **glue-stick** layer both evens adhesion *and* acts as a
  release layer (PETG can also bond *too* hard to smooth PEI and tear it). Prefer glue stick here.
- [ ] **Z-offset dialed:** too high → separation; too low → elephant foot / nozzle collision →
  layer shift → knock-off. Enable **Z-hop** so travel moves clear curled edges.
- [ ] **Watch layer 1** and the first bridge layers live. Abort early if a corner lifts or a bridge
  strand stands proud — that is the exact moment a knock-off begins.
- [ ] **Multi-part plate risk:** one knocked-off part spaghettis the rest. Print the tallest/
  riskiest part **alone first**; add the others once it's proven.
- [ ] **Release:** let the plate fully cool (or chill it) before removing — don't pry hot.

---

### One-line gate
Chamfered base + rounded first-layer corners + no long flat CF bridges (corbel/chamfer them) +
explicit outer brim + slowed bridges + degreased plate/glue stick + calibrated flow/temp +
≥4 walls on sealed faces + risky part printed first. If any of those is missing, fix before slicing.
