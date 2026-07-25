#!/usr/bin/env python3
"""
Weld STL parts into ONE **Bambu Studio project 3MF** with print settings and
per-part filament assignment already baked in, so opening it in Bambu Studio is
"import -> eyeball -> slice" with nothing to configure by hand.

    python make_bambu_3mf.py out.3mf "Base (translucent)=base.stl" "Text (CF)=text.stl"

Part-name -> filament rule (the whole point of this script; see PART_RULES):
    name contains "Base"  ->  filament 1, Bambu PETG Translucent, MAIN nozzle
    name contains "Text"  ->  filament 2, Bambu PETG-CF,          AUX  nozzle

Why this exists at all: the plain 3MF core spec (what skills/3d-modeling/scripts/
make_3mf.py writes) carries geometry and nothing else. Bambu Studio imports it as
one object with N selectable parts, but every part lands on filament 1 and the
process preset is whatever was last used. On a dual-nozzle X2D with a translucent
part that must be 100% infill, that is four separate hand-edits, each easy to get
wrong and invisible until the print fails. See references/bambu-3mf-authoring.md
for the concepts (project_settings.config vs model_settings.config, the slicer
round-trip, the three traps, and the honesty rule) this script implements.

ADAPTING TO ANOTHER MACHINE/PRINTER: every preset name, profile id, extruder
map, and pinned value below is X2D-specific and was read out of THIS machine's
*installed* Bambu Studio profile tree (BBL system bundle) - names from a newer
machine like the X2D do NOT transfer from H2D/older machines. To retarget:
re-run the round-trip in references/bambu-3mf-authoring.md (configure a plate for
the new machine in Bambu Studio, Save Project As, unzip, diff two saves) to learn
that machine's profile ids and key names/values, then update PRINTER_PRESET /
PROCESS_PRESET / FILAMENT_PRESETS / PART_RULES / the per-variant + fixup tables
here. Never guess keys; verify() proves internal consistency only, not that the
slicer accepts the file.

Requires: trimesh, numpy (mesh load), lxml (verification). Reads - never writes -
the installed Bambu Studio profile tree.
"""

import io
import json
import os
import sys
import uuid
import zipfile

import trimesh
from lxml import etree

# ============================ WHERE THE FACTS COME FROM =====================
# Everything below was read out of the *installed* Bambu Studio, not guessed.
# The user runs BambuStudio 02.07.01.62 (bambu-studio.exe FileVersion, and
# BambuStudio.conf app.version) with vendor profile bundle BBL 02.07.00.08.
# X2D support is new, so profile names from H2D/older machines do NOT transfer -
# every name below is copied verbatim from a file on this disk.
#
# Ground truth for the file layout and for every value below is
# reference_x2d.3mf: a project the user actually saved from Bambu Studio
# 02.07.01.62 for this X2D. Everything this script emits was diffed against it -
# same members, same XML shape, same array lengths, and identical values except
# for the settings we deliberately override and two filament swatch colours.

BBL_ROOT = os.path.join(os.environ.get("APPDATA", ""), "BambuStudio")
BBL_VENDOR_JSON = os.path.join(BBL_ROOT, "system", "BBL.json")   # profile index
BBL_SYSTEM_DIR = os.path.join(BBL_ROOT, "system", "BBL")
BBL_CONF = os.path.join(BBL_ROOT, "BambuStudio.conf")            # app version

# --- Presets. Names are the exact `name` field of the system profile JSONs, ---
# --- which is also the string Bambu Studio shows in its preset combo boxes. ---
PRINTER_PRESET = "Bambu Lab X2D 0.4 nozzle"
#   system/BBL/machine/Bambu Lab X2D 0.4 nozzle.json  setting_id GM045
#   -> nozzle_diameter ["0.4","0.4"], extruder_type ["Direct Drive","Bowden"]

PROCESS_PRESET = "0.20mm Standard @BBL X2D"
#   system/BBL/process/0.20mm Standard @BBL X2D.json  setting_id GP151
#   Already layer_height 0.2 / initial_layer_print_height 0.2; it is also the
#   machine's own `default_print_profile`, so it is the least surprising base.

FILAMENT_PRESETS = [
    "Bambu PETG Translucent @BBL X2D 0.4 nozzle",   # setting_id GFSG01_19, filament_id GFG01
    "Bambu PETG-CF @BBL X2D 0.4 nozzle",            # setting_id GFSG50_17, filament_id GFG50
]
# Both are `instantiation: true` with compatible_printers ["Bambu Lab X2D 0.4
# nozzle"], i.e. they are exactly the two entries the X2D 0.4 filament dropdown
# offers for these materials. PETG-CF carries required_nozzle_HRC 40 - fine, both
# X2D nozzles are hardened steel.

# Filament swatch colours. Cosmetic (3D-view tint + flush estimate) but the
# indigo is real: it is the PETG-CF spool already in this user's Bambu filament
# inventory - AppData/Roaming/BambuStudio/filament_inventory/spools.json,
# setting_id GFG50, tray "G50-B6", color_code "#324585FF".
FILAMENT_COLOURS = ["#E8E8E8", "#324585"]

# --- MAIN vs AUX -> extruder index. Three independent confirmations: ---------
#   1. machine/Bambu Lab X2D 0.4 nozzle.json:
#        extruder_type            = ["Direct Drive", "Bowden"]
#        printer_extruder_variant = ["Direct Drive Standard","Direct Drive High
#                                    Flow","Bowden Standard","Bowden High Flow"]
#   2. process/0.20mm Standard @BBL X2D (inherited) pairs those four variants
#        with print_extruder_id   = ["1","1","2","2"]
#   3. a real X2D project saved by this Studio build (Downloads/Poop-Bucket-
#        Logo-X2D.3mf) carries printer_extruder_id = ["1","1","2","2"] against
#        the same variant list.
#   => extruder 1 == Direct Drive == MAIN;  extruder 2 == Bowden == AUX.
EXTRUDER_MAIN = 1
EXTRUDER_AUX = 2

# --- Part-name -> (filament slot, physical extruder) ------------------------
# `filament slot` is what goes in model_settings.config as the per-part
# `extruder` metadata: a 1-based index into the project's filament list.
# `physical extruder` is a separate concept, expressed by filament_map below.
# Note the rule is applied HERE, at build time, and the result is written out as
# a literal per-part `extruder` value. Nothing at import time re-derives it from
# the name, which matters: a bare core-spec 3MF (no model_settings.config) loses
# its part names entirely - importing the old sample_coupon.3mf gave Bambu Studio
# parts called "assembly" and "assembly_2" (see reference_x2d.3mf). Names
# survive only because we write them as <metadata key="name"> ourselves, and the
# assignment does not depend on that surviving anyway.
PART_RULES = [
    ("Base", 1, EXTRUDER_MAIN),   # translucent PETG, direct drive, ~98% of volume
    ("Text", 2, EXTRUDER_AUX),    # PETG-CF, Bowden; ~0.5 g in the bottom 3 layers
]
DEFAULT_SLOT = 1                  # unmatched part names fall back to filament 1

# --- Process overrides we bake in on top of PROCESS_PRESET ------------------
PROCESS_OVERRIDES = {
    # The coupon's step heights are chosen so every zone is a whole number of
    # 0.2 mm layers. Both are already 0.2 in GP151; pinned here so a future
    # preset change can never silently re-round the geometry.
    "layer_height": "0.2",
    "initial_layer_print_height": "0.2",

    # Sparse infill inside a translucent plate prints a lattice straight through
    # the viewing path. 100% removes it. Preset default is 15%.
    "sparse_infill_density": "100%",
    # At 100% the pattern still matters optically: `grid` (the preset default)
    # crosses over itself and leaves a faint waffle. `monotonic` lays a
    # unidirectional solid, same as a top surface. Enum verified against the
    # pattern list in BambuStudio.dll.
    "sparse_infill_pattern": "monotonic",

    # Brim would run over the engraved zone labels, which sit ~1.9 mm from the
    # part edge. Enum values in BambuStudio.dll: no_brim / outer_only /
    # inner_only / outer_and_inner / auto_brim / brim_ears. Studio's default is
    # auto_brim, so this override is doing real work.
    "brim_type": "no_brim",
    "brim_width": "0",

    # The only plate this user owns. Enum from BambuStudio.dll: Cool Plate /
    # Engineering Plate / High Temp Plate / Textured PEI Plate / Supertack
    # Plate. It selects which of the filament profiles' *_plate_temp pairs is
    # used - both PETG profiles say textured_plate_temp 70 / first layer 70.
    # (The X2D machine model also declares default_bed_type "Textured PEI
    # Plate" and not_support_bed_type "Cool Plate".)
    "curr_bed_type": "Textured PEI Plate",
}

# Chamber / cooling is deliberately NOT overridden. The X2D advertises
# support_chamber_temp_control 1, but both PETG profiles ship
# chamber_temperatures ["0"] - no active chamber heating, i.e. the cool-running
# configuration PETG wants - together with during_print_exhaust_fan_speed 70 and
# activate_air_filtration 0. Those inherited values are the correct "PETG on an
# X2D in Cool Mode" answer; inventing our own would only make it worse.

# ============================ PROFILE RESOLUTION ============================
# Bambu profiles are a single-inheritance chain via the `inherits` key, resolved
# against the vendor index in system/BBL.json. Flattening it here reproduces what
# Studio itself computes when you pick the preset, and guarantees the numbers we
# emit match the *installed* bundle rather than some remembered version.

# Keys that are profile bookkeeping, not print settings. Confirmed absent from a
# real project_settings.config written by this Studio build.
_META_KEYS = {
    "type", "name", "from", "inherits", "setting_id", "instantiation",
    "description", "include", "filament_id", "version",
    "compatible_printers", "compatible_printers_condition",
    "filament_ingredients_safe", "filament_emission_safe", "filament_contact_safe",
}

# Legacy keys that still sit in the shipped profile JSONs but are not options in
# this Studio build - none of these strings occurs anywhere in BambuStudio.dll,
# and none appears in a real project_settings.config written by it. Studio's
# loader would skip them with a warning; cleaner not to emit them at all.
_LEGACY_KEYS = {
    "deretract_speed_extruder_change", "extruder_clearance_radius",
    "extruder_height_gap", "filament_long_retractions_when_ec",
    "filament_retraction_distances_when_ec",
    "layer_time_smoothing", "layer_time_smoothing_threshold",
}
_META_KEYS |= _LEGACY_KEYS

# Filament options that Bambu Studio stores per *extruder variant* (4 of them on
# the X2D) even though the shipped filament JSONs carry only a single value for
# them. Derived by comparing a real 4-filament X2D project_settings.config
# (Downloads/Poop-Bucket-Logo-X2D.3mf, written by 02.07.01.62) against the
# installed filament profiles: these are exactly the keys whose project array is
# 4x the filament count while the profile holds one value. Everything else
# follows the profile's own block size, so no table is needed for it.
# Emitting them at block 1 is not fatal - Preset::normalize() resizes filament
# vectors by padding - but the padded entries land at the wrong offsets as soon
# as two filaments disagree, so get the shape right instead.
_PER_VARIANT_FILAMENT_KEYS = {
    "filament_adaptive_volumetric_speed", "filament_bridge_speed",
    "filament_deretraction_speed", "filament_enable_overhang_speed",
    "filament_flush_temp", "filament_flush_volumetric_speed",
    "filament_long_retractions_when_cut", "filament_overhang_1_4_speed",
    "filament_overhang_2_4_speed", "filament_overhang_3_4_speed",
    "filament_overhang_4_4_speed", "filament_overhang_totally_speed",
    "filament_pre_cooling_temperature", "filament_pre_cooling_temperature_nc",
    "filament_preheat_temperature_delta", "filament_ramming_travel_time_nc",
    "filament_ramming_volumetric_speed", "filament_ramming_volumetric_speed_nc",
    "filament_retract_before_wipe", "filament_retract_length_nc",
    "filament_retract_restart_extra", "filament_retract_when_changing_layer",
    "filament_retraction_minimum_travel", "filament_retraction_speed",
    "filament_z_hop", "long_retractions_when_ec",
    "override_process_overhang_speed", "slow_down_min_speed",
    "volumetric_speed_coefficients",
}
# Per-filament option that lives in the machine/process profile as a single
# value; same source, same reasoning.
_PER_FILAMENT_FROM_MACHINE = {"pre_start_fan_time"}

# Handful of keys where the value shipped in the *generic ancestor* profiles
# (fdm_process_common / fdm_process_dual_common / fdm_filament_common /
# fdm_bbl_3dp_002_common) is stale: a project actually saved by this Studio for
# an X2D (reference_x2d.3mf) contains something else, i.e. Studio's own
# default wins over those ancestors. Two of them matter semantically -
# monotonic_travel_into_wall "45.0" would be read as 45 *mm* instead of 45%, and
# long_retractions_when_ec flips 0 -> 1 - so pin all of them to what the real
# save contains. Values that are per-variant are given as a single element and
# replicated below.
_REFERENCE_FIXUPS = {
    "monotonic_travel_into_wall": "45%",       # profile says "45.0"
    "bottom_surface_density": "100%",          # profile says "100"
    "top_surface_density": "100%",             # profile says "100"
    "best_object_pos": "0.3,0.5",              # profile says "0.3x0.5"
}
_REFERENCE_FIXUPS_PER_VARIANT = {
    "long_retractions_when_ec": "1",           # fdm_filament_common says "0"
    "filament_preheat_temperature_delta": "10",  # fdm_filament_common says "0"
}


def profile_index():
    """name -> absolute path, for every machine/filament/process system profile."""
    with open(BBL_VENDOR_JSON, encoding="utf-8") as f:
        vendor = json.load(f)
    idx = {}
    for key in ("machine_list", "filament_list", "process_list"):
        for entry in vendor[key]:
            idx[entry["name"]] = os.path.join(
                BBL_SYSTEM_DIR, entry["sub_path"].replace("/", os.sep))
    return idx, vendor["version"]


def apply_gcode_templates(idx, name, cfg):
    """Overlay the machine's `<preset> template <key>.json` sidecars.

    The X2D's start/end/layer-change/filament-change/timelapse G-code is NOT in
    Bambu Lab X2D 0.4 nozzle.json - those keys are absent there and live in five
    sibling profiles named "<preset> template <key>" with instantiation:false.
    Miss this and the inheritance chain silently hands back the generic
    fdm_bbl_3dp_002_common G-code, which is X1/P1 flavour: no X2D toolhead-offset
    calibration, wrong dual-nozzle filament change. A real X2D project saved by
    Studio contains the X2D flavour (";======== X2D start gcode ========"), which
    is how this was caught.
    """
    prefix = name + " template "
    for key in [k for k in idx if k.startswith(prefix)]:
        for k, v in flatten(idx, key).items():
            if k not in _META_KEYS:
                cfg[k] = v
    return cfg


def flatten(idx, name):
    """Resolve `name` through its `inherits` chain, child overriding parent."""
    chain = []
    while name:
        path = idx.get(name)
        if path is None:
            raise SystemExit(f"profile not found in installed BBL bundle: {name!r}")
        with open(path, encoding="utf-8") as f:
            node = json.load(f)
        chain.append(node)
        name = node.get("inherits")
    out = {}
    for node in reversed(chain):          # root ancestor first
        out.update(node)
    return out


def studio_version():
    """App version string, e.g. '02.07.01.62'. Stamped into the config files so
    they agree with the Studio that will open them. BambuStudio.conf is JSON
    followed by trailing bytes, hence raw_decode."""
    try:
        with open(BBL_CONF, encoding="utf-8") as f:
            conf, _ = json.JSONDecoder().raw_decode(f.read())
        return conf["app"]["version"]
    except Exception:
        return "02.07.01.62"          # observed on this machine; last resort


# ======================== Metadata/project_settings.config ==================
# The JSON blob holding print + filament + printer settings for the whole
# project. Studio starts from its compiled-in defaults, applies this on top, then
# tries to match each section back to a named preset. Keys we omit therefore fall
# back to Studio's own default - which, for anything the system profiles do not
# override, is the same value the preset would have given.

def build_project_settings(idx, bundle_version):
    machine = apply_gcode_templates(idx, PRINTER_PRESET, flatten(idx, PRINTER_PRESET))
    machine["printable_area"] = [s.strip() for s in machine["printable_area"]]
    process = flatten(idx, PROCESS_PRESET)
    filaments = [flatten(idx, n) for n in FILAMENT_PRESETS]
    n = len(filaments)

    cfg = {}
    # Machine and process values are already shaped correctly: scalars, or lists
    # of 2 (per physical extruder), 4 (per extruder *variant*) or 8 (2 x 4).
    for src in (machine, process):
        for k, v in src.items():
            if k not in _META_KEYS:
                cfg[k] = v

    # Filament values are per-preset and must be concatenated in slot order.
    # Shape rule, read off a real project file: a filament option stored as a
    # 1-element list is per-filament (final length n), a 4-element list is
    # per-extruder-variant (final length 4n, e.g. nozzle_temperature), a
    # 2-element list stays 2-per-filament. So: concatenate the raw blocks.
    n_var = len(machine["printer_extruder_variant"])
    fil_keys = set()
    for f in filaments:
        fil_keys |= {k for k, v in f.items() if k not in _META_KEYS and isinstance(v, list)}
    blocks = {}
    for k in sorted(fil_keys):
        if not all(k in f and len(f[k]) == len(filaments[0].get(k, [])) for f in filaments):
            continue          # inconsistent across presets -> let Studio default it
        rep = n_var if (k in _PER_VARIANT_FILAMENT_KEYS and len(filaments[0][k]) == 1) else 1
        blocks[k] = len(filaments[0][k]) * rep
        cfg[k] = [str(x) for f in filaments for x in f[k] for _ in range(rep)]

    # Same treatment for the handful that arrive from the machine/process side
    # but are per-filament in a project file.
    for k in _PER_FILAMENT_FROM_MACHINE:
        if isinstance(cfg.get(k), list) and len(cfg[k]) == 1:
            cfg[k] = [str(cfg[k][0])] * n
            blocks[k] = 1

    # ---- identity / preset matching -----------------------------------------
    cfg["from"] = "project"
    cfg["name"] = "project_settings"
    cfg["version"] = studio_version()          # must agree with the app reading it
    cfg["printer_settings_id"] = PRINTER_PRESET
    cfg["print_settings_id"] = PROCESS_PRESET
    cfg["filament_settings_id"] = list(FILAMENT_PRESETS)
    cfg["print_compatible_printers"] = [PRINTER_PRESET]
    cfg["default_print_profile"] = PROCESS_PRESET
    cfg["filament_ids"] = [flatten(idx, nme).get("filament_id", "") for nme in FILAMENT_PRESETS]

    # ---- THE per-part colour plumbing ---------------------------------------
    # Two distinct concepts, easy to conflate:
    #   * filament slot  - which spool a part is printed with. Lives per part in
    #     model_settings.config as `extruder` (1-based into these lists).
    #   * filament_map   - which physical nozzle each *slot* is loaded on.
    # filament_map_mode enum from BambuStudio.dll: Auto For Flush / Auto For
    # Match / Manual / Nozzle Manual / Auto For Quality. "Manual" is what stops
    # Studio re-deciding the mapping for us; the auto modes optimise flush volume
    # and would happily put both PETGs on the same nozzle.
    cfg["filament_map_mode"] = "Manual"
    cfg["filament_map"] = [str(e) for _, _, e in sorted(PART_RULES, key=lambda r: r[1])][:n]
    cfg["filament_colour"] = FILAMENT_COLOURS[:n]
    cfg["filament_multi_colour"] = FILAMENT_COLOURS[:n]
    cfg["default_filament_colour"] = [""] * n
    # These two are stored in the *filament* profile as a 1-element stub, but a
    # real project file expands them to one entry per extruder variant per
    # filament (16 for a 4-filament X2D project). Expand them the same way, and
    # drop them from `blocks` so the shape check below uses the real shape.
    cfg["filament_self_index"] = [str(i + 1) for i in range(n) for _ in range(n_var)]
    cfg["filament_extruder_variant"] = [v for _ in range(n)
                                        for v in machine["printer_extruder_variant"]]
    for k in ("filament_self_index", "filament_extruder_variant"):
        blocks[k] = n_var
    # Redundant with the machine profile, but a real project file states them
    # explicitly and they are the record of which variant belongs to which
    # nozzle - the evidence for EXTRUDER_MAIN/EXTRUDER_AUX above.
    cfg["printer_extruder_id"] = ["1", "1", "2", "2"]
    cfg["printer_extruder_variant"] = list(machine["printer_extruder_variant"])
    cfg["nozzle_volume_type"] = list(machine.get("default_nozzle_volume_type",
                                                 ["Standard", "Standard"]))

    # Flush volumes must be sized n*n per extruder (2n^2) and n per extruder
    # (2n), or Studio has to resize them itself. Values barely matter here: on a
    # dual-nozzle machine each nozzle keeps its own filament, so a "colour
    # change" is a nozzle change, not a purge of one material through the other.
    cfg["flush_volumes_matrix"] = ["0" if i == j else "140"
                                   for _ in range(2) for i in range(n) for j in range(n)]
    cfg["flush_volumes_vector"] = ["140"] * (2 * n)
    cfg["flush_multiplier"] = ["1", "1"]

    # Record which overrides genuinely deviate from the stock process preset
    # *before* applying them, so Studio's "modified" markers point at the real
    # deltas. layer_height/initial_layer_print_height are already 0.2 in GP151
    # and so should not show up here; curr_bed_type is a plater setting and is
    # not part of the process preset at all.
    cfg.update(_REFERENCE_FIXUPS)
    for k, v in _REFERENCE_FIXUPS_PER_VARIANT.items():
        cfg[k] = [v] * (n * n_var)
        blocks[k] = n_var

    deltas = sorted(k for k, v in PROCESS_OVERRIDES.items()
                    if k in process and str(process[k]) != v)
    cfg.update(PROCESS_OVERRIDES)
    # Layout is [process, filament_1 .. filament_n, printer].
    cfg["different_settings_to_system"] = [";".join(deltas)] + [""] * n + [""]

    return cfg, blocks, bundle_version


# ========================= Metadata/model_settings.config ==================
# The XML that actually carries the per-part assignment. Structure copied from
# real Bambu projects (Downloads/Toolbox_X2D_logo.3mf is the same shape as ours:
# one object, several parts, differing `extruder`):
#   <object id=C>        C = the *container* object id in 3D/3dmodel.model
#     <metadata key="extruder" value="1"/>          object-level default
#     <part id=K>        K = objectid of the component, i.e. the sub-mesh id
#       <metadata key="extruder" value="2"/>        per-part override <- the point
# Plus a <plate> block; its filament_maps mirrors project_settings' filament_map
# because the mapping is stored per plate as well as per project.

def build_model_settings(parts, container_id, tvec):
    def esc(s):
        return (s.replace("&", "&amp;").replace("<", "&lt;")
                 .replace(">", "&gt;").replace('"', "&quot;"))

    o = io.StringIO()
    o.write('<?xml version="1.0" encoding="UTF-8"?>\n<config>\n')
    o.write(f'  <object id="{container_id}">\n')
    o.write(f'    <metadata key="name" value="{esc(parts[0]["name"])}"/>\n')
    o.write(f'    <metadata key="extruder" value="{parts[0]["slot"]}"/>\n')
    o.write(f'    <metadata face_count="{sum(p["faces"] for p in parts)}"/>\n')
    for p in parts:
        o.write(f'    <part id="{p["id"]}" subtype="normal_part">\n')
        o.write(f'      <metadata key="name" value="{esc(p["name"])}"/>\n')
        # Identity: the sub-meshes are already in a common coordinate system
        # (same CAD doc), and the plate placement lives on the build item.
        o.write('      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>\n')
        o.write(f'      <metadata key="source_file" value="{esc(os.path.basename(p["src"]))}"/>\n')
        o.write('      <metadata key="source_object_id" value="0"/>\n')
        o.write('      <metadata key="source_volume_id" value="0"/>\n')
        for axis in "xyz":     # zero: the parts are already in shared coords
            o.write(f'      <metadata key="source_offset_{axis}" value="0"/>\n')
        o.write(f'      <metadata key="extruder" value="{p["slot"]}"/>\n')
        o.write(f'      <mesh_stat face_count="{p["faces"]}" edges_fixed="0" '
                'degenerate_facets="0" facets_removed="0" facets_reversed="0" '
                'backwards_edges="0"/>\n')
        o.write('    </part>\n')
    o.write('  </object>\n')

    slots = sorted({p["slot"] for p in parts})
    fmap = {slot: ext for _, slot, ext in PART_RULES}
    o.write('  <plate>\n')
    o.write('    <metadata key="plater_id" value="1"/>\n')
    o.write('    <metadata key="plater_name" value=""/>\n')
    o.write('    <metadata key="locked" value="false"/>\n')
    o.write('    <metadata key="filament_map_mode" value="Manual"/>\n')
    o.write('    <metadata key="filament_maps" value="%s"/>\n'
            % " ".join(str(fmap.get(s, EXTRUDER_MAIN)) for s in slots))
    o.write('    <metadata key="filament_volume_maps" value="%s"/>\n'
            % " ".join("0" for _ in slots))
    o.write('    <model_instance>\n')
    o.write(f'      <metadata key="object_id" value="{container_id}"/>\n')
    o.write('      <metadata key="instance_id" value="0"/>\n')
    o.write('    </model_instance>\n')
    o.write('  </plate>\n')
    # The assemble_item transform mirrors the build item's plate placement -
    # reference_x2d.3mf carries "1 0 0 0 1 0 0 0 1 128 128 0" in both places.
    o.write(f'  <assemble>\n   <assemble_item object_id="{container_id}" '
            'instance_id="0" transform="1 0 0 0 1 0 0 0 1 '
            f'{tvec[0]:g} {tvec[1]:g} {tvec[2]:g}" offset="0 0 0" />\n'
            '  </assemble>\n')
    o.write('</config>\n')
    return o.getvalue()


# ================================ GEOMETRY =================================
# Layout copied from real Bambu projects: the sub-meshes live in
# 3D/Objects/object_1.model and 3D/3dmodel.model holds one container object whose
# <component>s reference them by p:path (the 3MF "production" extension). This is
# the shape Studio writes itself, so it is the shape best tested on import.

MODEL_HDR = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<model unit="millimeter" xml:lang="en-US" '
    'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
    'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
    'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" '
    'requiredextensions="p">\n'
)
OBJECTS_PATH = "3D/Objects/object_1.model"


def mesh_xml(obj_id, mesh):
    o = io.StringIO()
    o.write(f'  <object id="{obj_id}" p:UUID="{uuid.uuid4()}" type="model">\n'
            '   <mesh>\n    <vertices>\n')
    for x, y, z in mesh.vertices:
        o.write(f'     <vertex x="{x:.6f}" y="{y:.6f}" z="{z:.6f}"/>\n')
    o.write('    </vertices>\n    <triangles>\n')
    for a, b, c in mesh.faces:
        o.write(f'     <triangle v1="{a}" v2="{b}" v3="{c}"/>\n')
    o.write('    </triangles>\n   </mesh>\n  </object>\n')
    return o.getvalue()


def build_geometry(parts, bed_centre, app_ver):
    """Return (objects_model_xml, root_model_xml, container_id)."""
    container_id = len(parts) + 1

    objs = io.StringIO()
    objs.write(MODEL_HDR)
    objs.write(' <metadata name="BambuStudio:3mfVersion">1</metadata>\n <resources>\n')
    for p in parts:
        objs.write(mesh_xml(p["id"], p["mesh"]))
    objs.write(' </resources>\n <build/>\n</model>\n')

    # Place the assembly: centre the combined footprint on the bed and drop it
    # to z=0. Doing it on the build item (not by moving vertices) keeps the parts
    # in their shared CAD coordinate system, which is what makes them line up.
    lo = [min(p["mesh"].bounds[0][i] for p in parts) for i in range(3)]
    hi = [max(p["mesh"].bounds[1][i] for p in parts) for i in range(3)]
    tx = bed_centre[0] - (lo[0] + hi[0]) / 2
    ty = bed_centre[1] - (lo[1] + hi[1]) / 2
    tz = -lo[2] + 0.0               # + 0.0 normalises a -0.0 away

    root = io.StringIO()
    root.write(MODEL_HDR)
    root.write(f' <metadata name="Application">BambuStudio-{app_ver}</metadata>\n')
    root.write(' <metadata name="BambuStudio:3mfVersion">1</metadata>\n')
    today = __import__("datetime").date.today().isoformat()
    root.write(f' <metadata name="CreationDate">{today}</metadata>\n')
    root.write(f' <metadata name="ModificationDate">{today}</metadata>\n')
    root.write(' <metadata name="Title"></metadata>\n')
    root.write(' <resources>\n')
    root.write(f'  <object id="{container_id}" p:UUID="{uuid.uuid4()}" type="model">\n'
               '   <components>\n')
    for p in parts:
        root.write(f'    <component p:path="/{OBJECTS_PATH}" objectid="{p["id"]}" '
                   f'p:UUID="{uuid.uuid4()}" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>\n')
    root.write('   </components>\n  </object>\n </resources>\n')
    root.write(f' <build p:UUID="{uuid.uuid4()}">\n')
    root.write(f'  <item objectid="{container_id}" p:UUID="{uuid.uuid4()}" '
               f'transform="1 0 0 0 1 0 0 0 1 {tx:.6f} {ty:.6f} {tz:.6f}" printable="1"/>\n')
    root.write(' </build>\n</model>\n')
    return objs.getvalue(), root.getvalue(), container_id, (tx, ty, tz)


CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
    ' <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
    ' <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n'
    ' <Default Extension="png" ContentType="image/png"/>\n'
    ' <Default Extension="gcode" ContentType="text/x.gcode"/>\n'
    '</Types>\n'
)
ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
    ' <Relationship Target="/3D/3dmodel.model" Id="rel-1" '
    'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n'
    '</Relationships>\n'
)
# Every sub-model file must be declared here or Studio will not open it.
MODEL_RELS = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
    f' <Relationship Target="/{OBJECTS_PATH}" Id="rel-1" '
    'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n'
    '</Relationships>\n'
)


def slice_info(app_ver):
    """Bambu writes this in every project; it only records who produced it."""
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<config>\n  <header>\n'
            '    <header_item key="X-BBL-Client-Type" value="slicer"/>\n'
            f'    <header_item key="X-BBL-Client-Version" value="{app_ver}"/>\n'
            '  </header>\n</config>\n')


# ================================ VERIFY ===================================

def verify(path, parts, cfg, blocks, container_id):
    """Re-open our own output and prove it says what we meant. Nothing here can
    prove Bambu Studio *likes* the file - only that it is internally consistent."""
    print("\n--- verification " + "-" * 58)
    ok = True

    def chk(label, cond, detail=""):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"  [{'ok ' if cond else 'FAIL'}] {label}{(' : ' + detail) if detail else ''}")

    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        expected = {"[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model",
                    "3D/_rels/3dmodel.model.rels", OBJECTS_PATH,
                    "Metadata/project_settings.config",
                    "Metadata/model_settings.config", "Metadata/slice_info.config"}
        chk("zip members", names == expected,
            "missing " + str(sorted(expected - names)) if expected - names else
            f"{len(names)} entries")

        # -- project_settings.config parses and says what we set ---------------
        got = json.loads(z.read("Metadata/project_settings.config"))
        chk("project_settings.config parses as JSON", True, f"{len(got)} keys")
        for k in ("layer_height", "initial_layer_print_height", "sparse_infill_density",
                  "sparse_infill_pattern", "brim_type", "brim_width", "curr_bed_type"):
            chk(f"  {k}", got.get(k) == cfg[k], repr(got.get(k)))
        chk("  printer / process preset",
            got["printer_settings_id"] == PRINTER_PRESET
            and got["print_settings_id"] == PROCESS_PRESET,
            f"{got['printer_settings_id']} / {got['print_settings_id']}")
        chk("  filament presets", got["filament_settings_id"] == FILAMENT_PRESETS,
            str(got["filament_settings_id"]))
        chk("  filament_map_mode / filament_map",
            got["filament_map_mode"] == "Manual" and got["filament_map"] == cfg["filament_map"],
            f"{got['filament_map_mode']} {got['filament_map']} "
            f"(1=Direct Drive/MAIN, 2=Bowden/AUX)")

        n = len(FILAMENT_PRESETS)
        bad = [k for k, b in blocks.items() if len(got.get(k, [])) != b * n]
        chk("  filament arrays all sized n_filaments x block", not bad, str(bad[:5]))
        chk("  chamber_temperatures (PETG wants no chamber heating)",
            set(got.get("chamber_temperatures", [])) == {"0"},
            str(got.get("chamber_temperatures")))
        chk("  textured plate temps", True,
            f"bed {got.get('textured_plate_temp')} / first layer "
            f"{got.get('textured_plate_temp_initial_layer')}")
        chk("  nozzle temps per filament x variant", True,
            str(got.get("nozzle_temperature")))
        # Guards the sidecar-template trap described in apply_gcode_templates().
        chk("  machine G-code is the X2D flavour, not generic BBL",
            all("X2D" in got.get(k, "") for k in
                ("machine_start_gcode", "machine_end_gcode", "layer_change_gcode",
                 "change_filament_gcode", "time_lapse_gcode")),
            "all 5 machine G-code blocks mention X2D")

        # -- model_settings.config: the per-part assignment --------------------
        ms = etree.fromstring(z.read("Metadata/model_settings.config"))
        obj = ms.find("object")
        chk("model_settings.config parses as XML",
            obj is not None and obj.get("id") == str(container_id),
            f'object id={obj.get("id") if obj is not None else None}')
        seen = {}
        for part in obj.findall("part"):
            name = part.find('metadata[@key="name"]').get("value")
            ext = part.find('metadata[@key="extruder"]').get("value")
            seen[name] = int(ext)
        for p in parts:
            want = p["slot"]
            nozzle = "MAIN/direct-drive" if p["extruder"] == EXTRUDER_MAIN else "AUX/Bowden"
            chk(f'  part "{p["name"]}" -> filament {want}',
                seen.get(p["name"]) == want,
                f'got {seen.get(p["name"])}; nozzle {p["extruder"]} ({nozzle}), '
                f'{FILAMENT_PRESETS[want - 1]}')

        # -- geometry ----------------------------------------------------------
        NS = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
        sub = etree.fromstring(z.read(OBJECTS_PATH))
        counts = {o.get("id"): (len(o.findall(".//m:vertex", NS)),
                                len(o.findall(".//m:triangle", NS)))
                  for o in sub.findall(".//m:object", NS)}
        for p in parts:
            v, t = counts.get(str(p["id"]), (0, 0))
            chk(f'  mesh {p["id"]} "{p["name"]}"',
                v == len(p["mesh"].vertices) and t == p["faces"],
                f"{v} verts / {t} tris")

        root = etree.fromstring(z.read("3D/3dmodel.model"))
        comps = root.findall(".//m:component", NS)
        chk("  root object references every sub-mesh", len(comps) == len(parts),
            f"{len(comps)} components")
        item = root.find(".//m:item", NS)
        chk("  build item present", item is not None,
            f'transform {item.get("transform") if item is not None else None}')

    print("  " + "-" * 60)
    print("  VERIFICATION " + ("PASSED" if ok else "FAILED"))
    return ok


# ================================= MAIN ====================================

def main():
    if len(sys.argv) < 3 or any("=" not in s for s in sys.argv[2:]):
        sys.exit(__doc__)
    out, specs = sys.argv[1], sys.argv[2:]

    idx, bundle_version = profile_index()
    app_ver = studio_version()
    print(f"Bambu Studio {app_ver}, BBL profile bundle {bundle_version}")
    print(f"printer  : {PRINTER_PRESET}")
    print(f"process  : {PROCESS_PRESET}")
    for i, f in enumerate(FILAMENT_PRESETS, 1):
        nozzle = [e for _, s, e in PART_RULES if s == i]
        tag = ("MAIN/direct-drive" if nozzle and nozzle[0] == EXTRUDER_MAIN
               else "AUX/Bowden") if nozzle else "?"
        print(f"filament {i}: {f}   -> extruder {nozzle[0] if nozzle else '?'} ({tag})")

    parts = []
    for i, spec in enumerate(specs, start=1):
        name, src = spec.split("=", 1)
        mesh = trimesh.load(src, process=True)     # welds duplicate STL vertices
        mesh.remove_unreferenced_vertices()
        slot, ext = DEFAULT_SLOT, EXTRUDER_MAIN
        for token, s, e in PART_RULES:
            if token.lower() in name.lower():
                slot, ext = s, e
                break
        else:
            print(f"  WARNING: '{name}' matches no rule in PART_RULES; "
                  f"defaulting to filament {DEFAULT_SLOT}")
        if not mesh.is_watertight:
            print(f"  WARNING: {name} is not watertight - check the source mesh")
        parts.append({"id": i, "name": name, "src": src, "mesh": mesh,
                      "faces": len(mesh.faces), "slot": slot, "extruder": ext})
        print(f"  {name}: {len(mesh.vertices)} verts, {len(mesh.faces)} tris, "
              f"watertight={mesh.is_watertight} -> filament {slot}, extruder {ext}")

    cfg, blocks, _ = build_project_settings(idx, bundle_version)

    # Bed centre from the machine profile's printable_area corners ("0x0",
    # "256x0", ...), so this follows the printer rather than a hard-coded 256.
    corners = [tuple(float(v) for v in c.strip().split("x"))
               for c in flatten(idx, PRINTER_PRESET)["printable_area"]]
    bed_centre = (sum(c[0] for c in corners) / len(corners),
                  sum(c[1] for c in corners) / len(corners))

    objs_xml, root_xml, container_id, tvec = build_geometry(parts, bed_centre, app_ver)
    model_settings = build_model_settings(parts, container_id, tvec)

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", ROOT_RELS)
        z.writestr("3D/3dmodel.model", root_xml)
        z.writestr("3D/_rels/3dmodel.model.rels", MODEL_RELS)
        z.writestr(OBJECTS_PATH, objs_xml)
        z.writestr("Metadata/project_settings.config",
                   json.dumps(cfg, indent=4, ensure_ascii=False))
        z.writestr("Metadata/model_settings.config", model_settings)
        z.writestr("Metadata/slice_info.config", slice_info(app_ver))

    print(f"\nwrote {out}  ({os.path.getsize(out)} bytes)")
    print(f"placed at bed centre {bed_centre[0]:.1f},{bed_centre[1]:.1f} "
          f"(build item translate {tvec[0]:.2f} {tvec[1]:.2f} {tvec[2]:.2f})")
    sys.exit(0 if verify(out, parts, cfg, blocks, container_id) else 1)


if __name__ == "__main__":
    main()
