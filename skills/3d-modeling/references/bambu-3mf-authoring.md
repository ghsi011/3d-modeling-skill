# Authoring a print-ready Bambu Studio project 3MF

A plain core-spec 3MF ([scripts/make_3mf.py](../scripts/make_3mf.py)) carries geometry only —
Bambu Studio imports it as one object, every part on filament 1, process = whatever was last
used. A print-ready Bambu *project* 3MF carries the **settings** too, so import is
"eyeball → slice". Two files do the work:

- `Metadata/project_settings.config` — JSON: layer height, infill, brim, bed type, and the
  per-filament / per-extruder-variant **arrays** (nozzle temps, flush volumes, retraction…).
- `Metadata/model_settings.config` — XML: per-object and per-part assignment via
  `<metadata key="extruder" value="N"/>`, where **N is a 1-based filament slot** (not a
  physical nozzle — the slot→nozzle mapping is `filament_map` in project_settings).

## Never guess keys — round-trip the real slicer

Machine/process/filament key NAMES and VALUES differ per machine and change between Studio
builds; a new machine's keys aren't documented. Get them from the slicer itself:

1. In Bambu Studio, configure ONE plate correctly for the exact machine (printer preset,
   process, filaments, per-object filament, bed type).
2. **File → Save Project As**, unzip the result, read `project_settings.config` and
   `model_settings.config`. Those are ground truth for names, shapes, and values.
3. **Save twice** — once before your changes, once after — and **diff** the two
   `project_settings.config` files. The diff is exactly the keys your settings touched;
   everything else you should leave inheriting.

Keep the saved project as the reference fixture and diff your generated file against it
(same members, same array lengths, same values except your deliberate overrides).

## Three traps (all cost a wasted print if missed)

1. **G-code hides in sidecar template profiles.** Machine start/end/layer-change/
   change-filament/timelapse G-code may not be in the machine profile — it can live in
   sibling `<machine> template <key>.json` profiles with `instantiation:false`. A naive
   `inherits` walk silently falls back to generic (X1/P1) G-code: wrong toolhead-offset
   calibration, wrong dual-nozzle filament change. **Verify the emitted G-code actually
   names the target machine** (e.g. grep the five blocks for the machine name).
2. **Generic-ancestor values carry the wrong unit form.** e.g. `fdm_process_dual_common`
   ships `monotonic_travel_into_wall` as `"45.0"`, which Studio parses as 45 **mm**, not
   45 **%**. Pin such keys to the value a real save contains, not the ancestor profile's.
3. **Bambu Studio may DISCARD your part names on import** — parts have come in renamed to
   "assembly" / "assembly_2". So key per-part filament assignment on the explicit
   `extruder` metadata you write into `model_settings.config`, **never** on part names
   surviving import.

## Honesty rule — you cannot confirm acceptance without launching the slicer

Structural verification proves the file is internally consistent, NOT that Studio likes it.
So: re-open the zip, parse every config, confirm each part's `extruder` slot and the
filament/nozzle map, check array shapes (n_filaments × block), confirm G-code names the
machine. State confidence **per setting**, and ship a short **"verify these after import"**
checklist (filament assignment preview, bed type, infill density, brim) rather than
claiming the print will succeed.

## Reusable tool

[scripts/make_bambu_3mf.py](../scripts/make_bambu_3mf.py) emits the whole project 3MF with
settings baked in and per-part filament assignment from part names, then self-verifies. It
is currently **X2D-specific** (built from that machine's installed profiles); to target
another machine, re-run the round-trip above to get that machine's profile ids and key
values, then update the presets/rules at the top of the script.
