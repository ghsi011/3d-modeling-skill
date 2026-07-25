# Materials — extended picks, drying, support pairings

Environment table (which polymer survives where) lives in fdm-design.md §7. This file:
underrated filaments worth choosing, moisture handling, and support-interface pairings.

## 1. Picks beyond the basics

| Filament | Why | Numbers / caveats |
|---|---|---|
| PA (nylon) | most rugged FDM material; repeated-impact parts | Dry at **80–100 °C** (50–60 °C dryers insufficient). Bed heat suffices, no chamber needed; Magigoo PA or PA plate for adhesion. Easy variants for open printers: Sunlu Easy PA, Polymaker CoPA. Ventilate. Bonds to almost nothing |
| PA12-CF vs PA6 | PA12 absorbs less water, holds shape better | CF/GF nylons print easier than neat PA |
| TPU-GF/CF | TPU layer adhesion + partial rigidity (between TPU and PA) | Semi-matte; spools often 500–750 g |
| PC-CF | HDT ~130 °C at fraction of PPA-CF price; prints easier than neat PC | Excels at load-bearing printed threads; satin finish |
| Foamed "Air" TPU/PEBA | ~40 % air: light, skin-friendly, EVA-like compression recovery → gaskets/seals/wearables | Standard TPU stays squished — bad gaskets. Foaming needs flow/PA re-tuning |
| PETG-CF | fixes PETG: no nozzle boogers, stiffer, matte, far less moisture-bubbling | ~$20–30/kg. CF weakens PLA but not PETG |

- Any CF/GF filament → hardened steel nozzle; on X2D never through the auxiliary nozzle.
- Wet-filament tells: popping/bubbling while extruding; ooze smearing calibration pads;
  stringing that temperature tuning doesn't fix. PETG, TPU, PA worst offenders.

## 2. Support-interface pairings (tested on X2D dual-nozzle)

Model → best interface material (aux nozzle prints ONLY the thin interface layers):

| Model | Winner | Loser / trade-off |
|---|---|---|
| PA (Easy PA, PA12-CF, PA6-GF) | Support-for-ABS | ASA grooves or welds |
| **PA6-CF** | **ASA** | Support-for-ABS welds solid — filled nylons differ; always coupon-test |
| ASA / ABS-GF / PC-ABS | Support-for-ABS | same-material support sags/lines |
| PC | ASA (releases, small grooves) | Support-for-ABS: perfect surface but needs a chisel |
| TPU | cheap PETG (or Support-for-PLA) | never zero XY-spacing; 3 interface layers |
| PLA | Support-for-PLA / PVA (dried) | — |

- Dedicated dissimilar interface prints at **zero Z-gap** → no sag lines. Don't manually
  zero spacings the slicer sets for interface materials.
- Dual nozzle = ~zero purge; AMS single-nozzle purges every swap (dark→light ≈ 3×).
- Run a small support coupon before committing any large print with a new pairing.
