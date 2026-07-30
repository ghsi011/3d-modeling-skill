#!/usr/bin/env python3
"""What a supplied artifact actually is, before anything is built on it.

`MODIFY` used to have no route at all, and the closest thing to one was advice:
treat the supplied file as geometry to inspect. Inspecting it by eye is how a
model in inches gets scaled by nobody, and how a mesh with 400 boundary edges
gets booleaned against until the kernel refuses.

So the artifact is measured first, and the measurement produces a classification
the routing and the edit scope can both read:

    USABLE_EXACT            an exact B-rep with solids; boolean edits are exact
    USABLE_MESH             a closed, consistent mesh; edits are mesh operations
    REPAIR_REQUIRED         loadable, but not sound enough to build on as it is
    RECONSTRUCTION_REQUIRED nothing here can be built on

**Nothing here writes to the artifact.** Not a repair, not a normalization, not a
re-export. The supplied file is frequently the only authoritative copy, and a
diagnosis that silently fixed what it found would destroy the evidence that it
needed fixing. Repair, where it is allowed at all, is a declared step in the edit
scope with its own receipt.

The units question is answered as honestly as the format allows. STL carries no
units at all, so this reports the bbox and a *suspicion* -- never a conversion.
3MF and STEP do carry them, and they are read rather than guessed.
"""
from __future__ import annotations

import argparse
import math
import zipfile
from pathlib import Path
from typing import Any

from . import schemas as S

DIAGNOSIS_SCHEMA = 1

MESH_SUFFIXES = {".stl", ".obj", ".ply", ".off"}
STEP_SUFFIXES = {".step", ".stp"}
THREEMF_SUFFIXES = {".3mf"}

# Below this, a part is more likely a millimetre model read as metres than a real
# object; above it, more likely an inch model read as millimetres. Both are
# reported as a suspicion with the arithmetic shown, never applied.
TINY_MM = 1.0
HUGE_MM = 1000.0
INCH_MM = 25.4


def _format_of(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in MESH_SUFFIXES:
        return {"stl": "STL", "obj": "OBJ"}.get(suffix.lstrip("."), "OTHER")
    if suffix in STEP_SUFFIXES:
        return "STEP"
    if suffix in THREEMF_SUFFIXES:
        return "3MF"
    return "OTHER"


def _scale_suspicions(extents: list[float]) -> list[str]:
    """Reported, never applied. A conversion nobody asked for is a silent edit."""
    out: list[str] = []
    if not extents:
        return out
    largest = max(extents)
    if largest < TINY_MM:
        out.append(
            f"the largest extent is {largest:.4f} mm. If this is a millimetre "
            f"model read as metres, x1000 gives {largest * 1000:.2f} mm.")
    if largest > HUGE_MM:
        out.append(
            f"the largest extent is {largest:.1f} mm, past a common bed. If this "
            f"is an inch model read as millimetres, /25.4 gives "
            f"{largest / INCH_MM:.2f} mm.")
    # A part whose every extent divides cleanly by 25.4 is worth a second look
    # even when the size is plausible.
    if largest >= TINY_MM and all(
            abs(round(e / INCH_MM, 3) - (e / INCH_MM)) < 1e-6 for e in extents):
        out.append("every extent is an exact multiple of 25.4 mm, which is what "
                   "an inch model looks like after a unitless import")
    return out


def _load_mesh(path: Path, *, process: bool):
    import trimesh
    loaded = trimesh.load(str(path), force="mesh", process=process)
    return (loaded if isinstance(loaded, trimesh.Trimesh)
            else loaded.dump(concatenate=True))


def _diagnose_mesh(path: Path) -> dict[str, Any]:
    """Two reads, because "as parsed" and "as interpreted" are different facts.

    An STL is a triangle soup: it stores three independent vertices per facet and
    no adjacency at all, so a perfectly sound part reads as thousands of boundary
    edges and hundreds of disconnected bodies until coincident vertices are
    merged. Classifying on the raw read called every STL ever written
    `REPAIR_REQUIRED`, which is useless in exactly the way a check that always
    fires is useless.

    Merging is the parse, not a repair -- but the difference between the two
    reads is itself information (a mesh that stays open after merging really is
    open), so both are reported and the merge is named.
    """
    raw = _load_mesh(path, process=False)
    mesh = _load_mesh(path, process=True)

    faces = int(len(mesh.faces))
    degenerate = int((mesh.area_faces <= 1e-12).sum()) if faces else 0
    boundary = (int(len(mesh.edges_unique) - len(mesh.face_adjacency))
                if faces else 0)
    components = mesh.split(only_watertight=False) if faces else []
    extents = [round(float(v), 4) for v in mesh.extents] if faces else []

    findings: list[str] = []
    if faces == 0:
        findings.append("no faces at all")
    if faces and not mesh.is_watertight:
        findings.append(f"not watertight after merging coincident vertices: "
                        f"{boundary} boundary edge(s)")
    if faces and not mesh.is_winding_consistent:
        findings.append("winding is inconsistent, so inside and outside are not "
                        "well defined")
    if degenerate:
        findings.append(f"{degenerate} degenerate face(s) with zero area")

    if faces == 0:
        classification = "RECONSTRUCTION_REQUIRED"
    elif mesh.is_watertight and mesh.is_winding_consistent and not degenerate:
        classification = "USABLE_MESH"
    else:
        classification = "REPAIR_REQUIRED"

    return {
        "format": _format_of(path),
        "units": None,
        "units_note": "the format carries no units; the bbox is reported as "
                      "authored and nothing has been converted",
        "bodies": int(len(components)),
        "faces": faces,
        "vertices": int(len(mesh.vertices)),
        "bbox_mm": extents,
        "volume_mm3": round(float(mesh.volume), 4) if mesh.is_watertight else None,
        "watertight": bool(mesh.is_watertight),
        "winding_consistent": bool(mesh.is_winding_consistent),
        "degenerate_faces": degenerate,
        "boundary_edges": boundary,
        "as_parsed": {
            "vertices": int(len(raw.vertices)),
            "faces": int(len(raw.faces)),
            "note": "before coincident vertices were merged. A large drop is what "
                    "a triangle-soup format looks like, not damage.",
        },
        "scale_suspicions": _scale_suspicions(extents),
        "findings": findings,
        "classification": classification,
    }


def _diagnose_step(path: Path) -> dict[str, Any]:
    try:
        from build123d import import_step
    except ImportError as exc:                        # pragma: no cover - core dep
        return {"format": "STEP", "classification": "RECONSTRUCTION_REQUIRED",
                "findings": [f"build123d is not importable: {exc}"]}
    try:
        shape = import_step(str(path))
    except Exception as exc:                          # noqa: BLE001 - a file the
        return {"format": "STEP",                     # kernel refuses is a finding
                "classification": "RECONSTRUCTION_REQUIRED",
                "findings": [f"the kernel refused this STEP: "
                             f"{type(exc).__name__}: {exc}"]}

    solids = list(getattr(shape, "solids", lambda: [])())
    faces = list(getattr(shape, "faces", lambda: [])())
    box = shape.bounding_box()
    extents = [round(float(v), 4) for v in (box.size.X, box.size.Y, box.size.Z)]

    invalid = 0
    for face in faces:
        try:
            if not math.isfinite(float(face.area)) or float(face.area) <= 0.0:
                invalid += 1
        except Exception:                             # noqa: BLE001 - a face whose
            invalid += 1                              # area cannot be taken is one

    findings: list[str] = []
    if not solids:
        findings.append("no solids: this STEP carries surfaces or wires only, so "
                        "there is no volume to modify")
    if invalid:
        findings.append(f"{invalid} face(s) have no usable area, which is what a "
                        "null tessellation looks like from here")

    classification = ("RECONSTRUCTION_REQUIRED" if not solids
                      else "REPAIR_REQUIRED" if invalid else "USABLE_EXACT")
    return {
        "format": "STEP",
        # STEP declares its units in the file header. build123d converts to
        # millimetres on import, so what is reported is the post-import frame and
        # says so rather than implying the header was read.
        "units": "mm",
        "units_note": "build123d imports STEP into millimetres; the header's own "
                      "unit declaration was not read separately",
        "bodies": len(solids),
        "faces": len(faces),
        "bbox_mm": extents,
        "invalid_faces": invalid,
        "scale_suspicions": _scale_suspicions(extents),
        "findings": findings,
        "classification": classification,
    }


_MODEL_NS = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"


def _diagnose_3mf(path: Path) -> dict[str, Any]:
    """The scene, not just the merged mesh.

    A 3MF's object/component/transform structure *is* functional information --
    which part is which, where each one sits, what material it carries. Loading
    it through a mesh library and reporting one merged solid throws away exactly
    what a multi-part or multi-colour job is about.
    """
    import xml.etree.ElementTree as ET

    findings: list[str] = []
    if not zipfile.is_zipfile(path):
        return {"format": "3MF", "classification": "RECONSTRUCTION_REQUIRED",
                "findings": ["not a zip archive, so it is not a 3MF"]}

    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        model_names = [n for n in names if n.lower().endswith(".model")]
        if not model_names:
            return {"format": "3MF", "classification": "RECONSTRUCTION_REQUIRED",
                    "findings": ["the archive carries no .model part"],
                    "archive_entries": sorted(names)}
        try:
            root = ET.fromstring(archive.read(model_names[0]))
        except ET.ParseError as exc:
            return {"format": "3MF", "classification": "RECONSTRUCTION_REQUIRED",
                    "findings": [f"the model part is not valid XML: {exc}"]}

    unit = root.attrib.get("unit", "millimeter")
    resources = root.find(f"{_MODEL_NS}resources")
    objects: list[dict[str, Any]] = []
    if resources is not None:
        for obj in resources.findall(f"{_MODEL_NS}object"):
            mesh = obj.find(f"{_MODEL_NS}mesh")
            components = obj.find(f"{_MODEL_NS}components")
            child_refs = ([c.attrib.get("objectid")
                           for c in components.findall(f"{_MODEL_NS}component")]
                          if components is not None else [])
            triangles = mesh.find(f"{_MODEL_NS}triangles") if mesh is not None else None
            objects.append({
                "id": obj.attrib.get("id"),
                "name": obj.attrib.get("name"),
                "type": obj.attrib.get("type", "model"),
                "pid": obj.attrib.get("pid"),
                "triangles": len(list(triangles)) if triangles is not None else 0,
                "components": [ref for ref in child_refs if ref],
            })

    build = root.find(f"{_MODEL_NS}build")
    items = ([{"objectid": item.attrib.get("objectid"),
               "transform": item.attrib.get("transform")}
              for item in build.findall(f"{_MODEL_NS}item")]
             if build is not None else [])

    materials = []
    if resources is not None:
        for group in resources.findall(f"{_MODEL_NS}basematerials"):
            for base in group.findall(f"{_MODEL_NS}base"):
                materials.append({"group": group.attrib.get("id"),
                                  "name": base.attrib.get("name"),
                                  "displaycolor": base.attrib.get("displaycolor")})

    if not objects:
        findings.append("no objects: there is nothing in this scene to modify")
    if unit != "millimeter":
        findings.append(f"the scene declares unit={unit!r}, so every number in it "
                        "is in that unit and not in millimetres")
    dangling = {ref for obj in objects for ref in obj["components"]} - {
        obj["id"] for obj in objects}
    if dangling:
        findings.append(f"component(s) reference object id(s) that are not in the "
                        f"file: {sorted(dangling)}")

    classification = ("RECONSTRUCTION_REQUIRED" if not objects
                      else "REPAIR_REQUIRED" if (dangling or unit != "millimeter")
                      else "USABLE_MESH")
    return {
        "format": "3MF",
        "units": unit,
        "units_note": "read from the model part's own unit attribute",
        "bodies": len(objects),
        "objects": objects,
        "build_items": items,
        "materials": materials,
        "scene_is_functional": bool(len(items) > 1 or materials
                                    or any(o["components"] for o in objects)),
        "findings": findings,
        "classification": classification,
    }


def diagnose(path: Path) -> dict[str, Any]:
    """Measure a supplied artifact. Never writes to it."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"no such artifact: {path}")

    fmt = _format_of(path)
    if fmt == "STEP":
        report = _diagnose_step(path)
    elif fmt == "3MF":
        report = _diagnose_3mf(path)
    elif fmt in ("STL", "OBJ"):
        try:
            report = _diagnose_mesh(path)
        except Exception as exc:                      # noqa: BLE001 - an unreadable
            report = {"format": fmt,                  # file is a finding
                      "classification": "RECONSTRUCTION_REQUIRED",
                      "findings": [f"{type(exc).__name__}: {exc}"]}
    else:
        report = {"format": "OTHER", "classification": "RECONSTRUCTION_REQUIRED",
                  "findings": [f"no diagnosis implements {path.suffix!r}; the "
                               "supported formats are STEP, STL, OBJ and 3MF"]}

    S.require_enum(report["classification"],
                   ("USABLE_EXACT", "USABLE_MESH", "REPAIR_REQUIRED",
                    "RECONSTRUCTION_REQUIRED"), what="classification")
    return {
        "schema_version": DIAGNOSIS_SCHEMA,
        "path": path.name,
        "sha256": S.sha256_file(path),
        "bytes": path.stat().st_size,
        **report,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="design-tool diagnose",
        description="Measure a supplied STEP, STL, OBJ or 3MF and classify what "
                    "can be built on it. Never writes to the artifact.")
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--out", type=Path,
                        help="write the report here as well as printing it")
    args = parser.parse_args(argv)

    try:
        report = diagnose(args.artifact)
    except FileNotFoundError as exc:
        raise SystemExit(f"design-tool: {exc}")

    text = S.canonical_json(report)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text, end="")
    # A classification is a finding, not a failure: the caller decides what to do
    # with REPAIR_REQUIRED. Only an artifact nothing can be built on exits
    # non-zero, so a script can branch on it without parsing.
    return 1 if report["classification"] == "RECONSTRUCTION_REQUIRED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
