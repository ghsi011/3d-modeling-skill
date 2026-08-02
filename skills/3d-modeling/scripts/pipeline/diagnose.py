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

    # Area is not tessellability, and reading it as one is how a file nothing can
    # turn into triangles was called `USABLE_EXACT`. `vent_mount.step` has 329
    # faces, every one of them with a finite positive area -- one is 1.75e-14 mm2,
    # which is small and is not zero -- and six of them are cones OCC produces no
    # triangulation for at any deflection tried. Under the area test alone that
    # file passed diagnosis and then failed the first operation that needed
    # geometry, which is the failure diagnosis exists to prevent: the error moved
    # to a stage with less context to explain it.
    #
    # So the same probe every consumer of this file will run is run here, and its
    # answer is a finding. The cost is one tessellation pass -- about 2 s on that
    # 329-face part, against the 9 s the import itself takes.
    import mesh_io
    reading = mesh_io.tessellate_brep(
        shape, tolerance=mesh_io.BREP_READ_LINEAR_DEFLECTION,
        angular_tolerance=mesh_io.BREP_READ_ANGULAR_DEFLECTION)

    findings: list[str] = []
    if not solids:
        findings.append("no solids: this STEP carries surfaces or wires only, so "
                        "there is no volume to modify")
    if invalid:
        findings.append(f"{invalid} face(s) have no usable area, which is what a "
                        "null tessellation looks like from here")
    if not reading.complete:
        findings.append(
            f"{len(reading.failures)} of {reading.faces} face(s) cannot be "
            f"tessellated at {reading.linear_deflection} mm linear / "
            f"{reading.angular_deflection} rad angular deflection, so nothing "
            f"downstream can turn this file into a mesh: "
            + "; ".join(reading.failures))

    classification = (
        "RECONSTRUCTION_REQUIRED" if not solids
        else "REPAIR_REQUIRED" if (invalid or not reading.complete)
        else "USABLE_EXACT")
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
        "untessellatable_faces": len(reading.failures),
        "tessellation": reading.as_dict(),
        "scale_suspicions": _scale_suspicions(extents),
        "findings": findings,
        "classification": classification,
    }


_MODEL_NS = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
# The production extension. Bambu Studio, OrcaSlicer and PrusaSlicer all write
# it: the root part carries the scene and nothing else, and every mesh lives in
# its own `3D/Objects/object_NN.model` reached through a component's `p:path`.
# A reader that ignores `p:path` and only opens one part sees components
# pointing at ids it cannot find, and calls an intact file broken.
_PRODUCTION_NS = "{http://schemas.microsoft.com/3dmanufacturing/production/2015/06}"
_RELATIONSHIP_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_ROOT_MODEL_REL = "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"
_CONVENTIONAL_ROOT = "3d/3dmodel.model"

# A component chain this deep is a malformed file, not a scene. The recursion is
# also cycle-guarded; this is the second belt.
_MAX_COMPONENT_DEPTH = 32


def _part_key(name: str) -> str:
    """3MF part names are absolute and case-insensitive; zip entries are neither."""
    return name.replace("\\", "/").lstrip("/").lower()


def _transform(text: str | None):
    """A 3MF transform is a 4x3 row-major matrix applied to *row* vectors.

    numpy and trimesh apply column vectors, so the 3x3 block transposes and the
    translation moves into the last column. Getting this backwards silently
    mirrors every rotated part.
    """
    import numpy as np
    matrix = np.eye(4)
    if text is None:
        return matrix, True
    values = text.split()
    if len(values) != 12:
        return matrix, False
    try:
        numbers = [float(v) for v in values]
    except ValueError:
        return matrix, False
    matrix[:3, :3] = np.array(numbers[:9]).reshape(3, 3).T
    matrix[:3, 3] = numbers[9:]
    return matrix, True


def _mesh_arrays(mesh_el) -> tuple[list, list, int]:
    """A 3MF mesh is indexed, not a triangle soup, so nothing is merged here.

    Merging coincident vertices is the parse for STL; doing it to a 3MF would
    change the author's topology and hide a genuinely split seam.
    """
    vertices_el = mesh_el.find(f"{_MODEL_NS}vertices")
    triangles_el = mesh_el.find(f"{_MODEL_NS}triangles")
    vertices: list[tuple[float, float, float]] = []
    if vertices_el is not None:
        for vertex in vertices_el.findall(f"{_MODEL_NS}vertex"):
            vertices.append((float(vertex.attrib.get("x", 0.0)),
                             float(vertex.attrib.get("y", 0.0)),
                             float(vertex.attrib.get("z", 0.0))))
    faces: list[tuple[int, int, int]] = []
    unusable = 0
    if triangles_el is not None:
        for triangle in triangles_el.findall(f"{_MODEL_NS}triangle"):
            try:
                face = (int(triangle.attrib["v1"]), int(triangle.attrib["v2"]),
                        int(triangle.attrib["v3"]))
            except (KeyError, ValueError):
                unusable += 1
                continue
            if any(i < 0 or i >= len(vertices) for i in face):
                unusable += 1
                continue
            faces.append(face)
    return vertices, faces, unusable


def _trimesh_of(vertices: list, faces: list):
    import numpy as np
    import trimesh
    return trimesh.Trimesh(
        vertices=np.asarray(vertices, dtype=float).reshape(-1, 3),
        faces=np.asarray(faces, dtype=np.int64).reshape(-1, 3),
        process=False)


def _mesh_facts(mesh) -> dict[str, Any]:
    """The same questions the STL branch answers, asked of one 3MF object."""
    triangles = int(len(mesh.faces))
    if triangles == 0:
        return {"triangles": 0, "vertices": int(len(mesh.vertices)), "bbox_mm": [],
                "watertight": False, "winding_consistent": False,
                "volume_mm3": None, "bodies": 0, "boundary_edges": 0}
    watertight = bool(mesh.is_watertight)
    return {
        "triangles": triangles,
        "vertices": int(len(mesh.vertices)),
        "bbox_mm": [round(float(v), 4) for v in mesh.extents],
        "watertight": watertight,
        "winding_consistent": bool(mesh.is_winding_consistent),
        "volume_mm3": round(float(mesh.volume), 4) if watertight else None,
        "bodies": int(len(mesh.split(only_watertight=False))),
        "boundary_edges": int(len(mesh.edges_unique) - len(mesh.face_adjacency)),
    }


def _root_part_key(archive, by_key: dict[str, str], model_keys: list[str]) -> str:
    """Which `.model` is the scene.

    Reading whichever part the zip happens to list first is how a Bambu export
    gets diagnosed from one of its mesh parts -- which carries no build, no
    materials and one anonymous object. The package relationship names the real
    root; the conventional path and then zip order are the fallbacks.
    """
    import xml.etree.ElementTree as ET
    if "_rels/.rels" in by_key:
        try:
            rels = ET.fromstring(archive.read(by_key["_rels/.rels"]))
        except (ET.ParseError, KeyError, OSError):
            rels = None
        if rels is not None:
            for rel in rels.findall(f"{_RELATIONSHIP_NS}Relationship"):
                if rel.attrib.get("Type") != _ROOT_MODEL_REL:
                    continue
                key = _part_key(rel.attrib.get("Target", ""))
                if key in model_keys:
                    return key
    if _CONVENTIONAL_ROOT in model_keys:
        return _CONVENTIONAL_ROOT
    return model_keys[0]


def _object_record(obj, part_key: str) -> dict[str, Any]:
    mesh_el = obj.find(f"{_MODEL_NS}mesh")
    components_el = obj.find(f"{_MODEL_NS}components")
    components: list[dict[str, Any]] = []
    if components_el is not None:
        for component in components_el.findall(f"{_MODEL_NS}component"):
            ref = component.attrib.get("objectid")
            if not ref:
                continue
            components.append({
                "objectid": ref,
                # The whole point: which part the id lives in, when it is not
                # this one.
                "path": component.attrib.get(f"{_PRODUCTION_NS}path"),
                "transform": component.attrib.get("transform"),
            })
    return {
        "id": obj.attrib.get("id"),
        "name": obj.attrib.get("name"),
        "type": obj.attrib.get("type", "model"),
        "pid": obj.attrib.get("pid"),
        "part": part_key,
        "components": components,
        "_mesh_el": mesh_el,
    }


def _resolve(ref: dict[str, Any], referring_part: str,
             objects: dict[tuple[str, str], dict[str, Any]]):
    """An id is dangling only if it is in neither part it could plausibly be in.

    `p:path` is authoritative when present, but a writer that emits it and also
    keeps the object local is producing a file that still resolves, and calling
    that broken would be the original bug with an extra step.
    """
    object_id = ref.get("objectid")
    path = ref.get("path")
    if path:
        candidate = (_part_key(path), object_id)
        if candidate in objects:
            return candidate
    candidate = (referring_part, object_id)
    return candidate if candidate in objects else None


def _cycle_edges(objects: dict[tuple[str, str], dict[str, Any]]) -> set[tuple]:
    """Every component reference that closes a loop, anywhere in the file.

    Driven from every object rather than from the build, for the same reason the
    dangling sweep is: an unreferenced object whose components loop is still a
    broken file, and a walk that only follows what the build reaches calls it
    fine. Doing this in `_leaves` had exactly that blind spot.

    A cycle is not a dangling reference and must not be reported as one. Every id
    involved is present; the file resolves; it simply describes a scene that
    cannot be assembled, because following the components never terminates.

    Iterative rather than recursive: the depth cap belongs to the placement walk,
    which has a matrix to carry, and a graph search that inherited it would
    silently stop looking for cycles on a file deep enough to need one found.
    """
    found: set[tuple] = set()
    finished: set[tuple] = set()
    for start in objects:
        if start in finished:
            continue
        stack = [(start, iter(objects[start]["components"]))]
        on_path = {start}
        while stack:
            node, refs = stack[-1]
            descended = False
            for ref in refs:
                child = _resolve(ref, node[0], objects)
                if child is None or child in finished:
                    continue                  # dangling, or already cleared
                if child in on_path:
                    found.add((node, child))
                    continue
                stack.append((child, iter(objects[child]["components"])))
                on_path.add(child)
                descended = True
                break
            if not descended:
                stack.pop()
                on_path.discard(node)
                finished.add(node)
    return found


def _leaves(target, matrix, objects, dangling: set, too_deep: set,
            chain: tuple = ()):
    """Every mesh reachable from `target`, with its accumulated placement.

    Both guards have to stop the walk. Only one of them is reported here: a cycle
    is found by `_cycle_edges` over the whole file, so returning quietly on one is
    not losing the finding. A chain that is merely too deep is a different thing
    and has no other detector, so it is recorded -- silently dropping the geometry
    under it would leave a report that looks complete and is not.
    """
    if target in chain:
        return
    if len(chain) > _MAX_COMPONENT_DEPTH:
        too_deep.add(target)
        return
    record = objects.get(target)
    if record is None:
        return
    if record["geometry"] is not None:
        yield target, matrix
    for ref in record["components"]:
        resolved = _resolve(ref, target[0], objects)
        if resolved is None:
            dangling.add(ref["objectid"])
            continue
        child, _ok = _transform(ref.get("transform"))
        yield from _leaves(resolved, matrix @ child, objects, dangling,
                           too_deep, chain + (target,))


def _diagnose_3mf(path: Path) -> dict[str, Any]:
    """The scene *and* the geometry in it.

    A 3MF's object/component/transform structure *is* functional information --
    which part is which, where each one sits, what material it carries. Loading
    it through a mesh library and reporting one merged solid throws away exactly
    what a multi-part or multi-colour job is about. So the scene is reported as
    authored, and each object in it is measured with the same questions the STL
    branch asks: bbox, watertightness, winding, volume, bodies.

    Placement is reported through the build transforms, because a part carrying
    a 1.07 scale on its build item is 7% larger than the numbers in its mesh
    part, and a reader that skips the transform measures the wrong object.
    """
    import xml.etree.ElementTree as ET

    if not zipfile.is_zipfile(path):
        return {"format": "3MF", "classification": "RECONSTRUCTION_REQUIRED",
                "findings": ["not a zip archive, so it is not a 3MF"]}

    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        by_key = {_part_key(n): n for n in names}
        model_keys = sorted(k for k in by_key if k.endswith(".model"))
        if not model_keys:
            return {"format": "3MF", "classification": "RECONSTRUCTION_REQUIRED",
                    "findings": ["the archive carries no .model part"],
                    "archive_entries": sorted(names)}
        parsed: dict[str, Any] = {}
        broken: dict[str, str] = {}
        for key in model_keys:
            try:
                parsed[key] = ET.fromstring(archive.read(by_key[key]))
            except (ET.ParseError, KeyError, OSError, zipfile.BadZipFile) as exc:
                broken[key] = f"{type(exc).__name__}: {exc}"
        root_key = _root_part_key(archive, by_key, model_keys)

    if root_key not in parsed:
        # The scene itself is unreadable, so nothing below can be trusted.
        return {"format": "3MF", "classification": "RECONSTRUCTION_REQUIRED",
                "findings": [f"the model part {root_key!r} is not valid XML: "
                             f"{broken.get(root_key, 'unreadable')}"]}

    root = parsed[root_key]
    unit = root.attrib.get("unit", "millimeter")
    findings: list[str] = []
    for key in sorted(broken):
        findings.append(f"the model part {key!r} is not valid XML, so anything "
                        f"referring into it cannot resolve: {broken[key]}")

    # Anything that makes the geometry itself unsound. Kept beside the findings
    # rather than derived from them, so a finding can never be reported without
    # reaching the classification.
    unsound = bool(broken)
    objects: dict[tuple[str, str], dict[str, Any]] = {}
    ordered: list[dict[str, Any]] = []
    materials: list[dict[str, Any]] = []
    meshes: dict[tuple[str, str], Any] = {}
    # Root part first, so the reported order is the scene's order rather than
    # the zip's.
    for key in [root_key] + [k for k in model_keys if k != root_key]:
        part_root = parsed.get(key)
        if part_root is None:
            continue
        part_unit = part_root.attrib.get("unit", "millimeter")
        if part_unit != unit:
            findings.append(f"the part {key!r} declares unit={part_unit!r} while "
                            f"the scene declares {unit!r}; the two cannot both be "
                            "the frame the numbers are in")
        resources = part_root.find(f"{_MODEL_NS}resources")
        if resources is None:
            continue
        for obj in resources.findall(f"{_MODEL_NS}object"):
            record = _object_record(obj, key)
            mesh_el = record.pop("_mesh_el")
            record["geometry"] = None
            record["triangles"] = 0
            if mesh_el is not None:
                try:
                    vertices, faces, unusable = _mesh_arrays(mesh_el)
                    mesh = _trimesh_of(vertices, faces)
                except Exception as exc:              # noqa: BLE001 - a mesh that
                    findings.append(                  # will not parse is a finding
                        f"object {record['id']!r} in {key!r} carries a mesh that "
                        f"cannot be read: {type(exc).__name__}: {exc}")
                    unsound = True
                else:
                    record["geometry"] = _mesh_facts(mesh)
                    record["triangles"] = record["geometry"]["triangles"]
                    meshes[(key, record["id"])] = mesh
                    if unusable:
                        findings.append(
                            f"object {record['id']!r} in {key!r} has {unusable} "
                            "triangle(s) referring to vertices that do not exist")
                        unsound = True
            objects[(key, record["id"])] = record
            ordered.append(record)
        for group in resources.findall(f"{_MODEL_NS}basematerials"):
            for base in group.findall(f"{_MODEL_NS}base"):
                materials.append({"part": key,
                                  "group": group.attrib.get("id"),
                                  "name": base.attrib.get("name"),
                                  "displaycolor": base.attrib.get("displaycolor")})

    build = root.find(f"{_MODEL_NS}build")
    build_elements = build.findall(f"{_MODEL_NS}item") if build is not None else []
    dangling: set[str] = set()
    too_deep: set[tuple] = set()

    # Every component in the file is resolved, not only the ones the build
    # happens to reach: an unreferenced object with a broken component is still
    # a broken file. The same argument applies to a loop, so the cycle search
    # runs over the whole graph here rather than along the placement walk.
    for record in ordered:
        for ref in record["components"]:
            if _resolve(ref, record["part"], objects) is None:
                dangling.add(ref["objectid"])
    cycles = _cycle_edges(objects)

    items: list[dict[str, Any]] = []
    placed: list[dict[str, Any]] = []
    unplaced: set[str] = set()
    for element in build_elements:
        object_id = element.attrib.get("objectid")
        raw_transform = element.attrib.get("transform")
        matrix, readable = _transform(raw_transform)
        if not readable:
            findings.append(f"build item for object {object_id!r} carries a "
                            f"transform that is not 12 numbers, so where this "
                            f"part sits is unknown: {raw_transform!r}")
            unsound = True
        # A build item may carry `p:path` too, for the same reason a component
        # does.
        ref = {"objectid": object_id,
               "path": element.attrib.get(f"{_PRODUCTION_NS}path")}
        target = _resolve(ref, root_key, objects)
        if target is None:
            unplaced.add(str(object_id))
        items.append({"objectid": object_id, "path": ref["path"],
                      "transform": raw_transform,
                      "resolved": target is not None})
        if target is None:
            continue
        for leaf, placement in _leaves(target, matrix, objects, dangling,
                                       too_deep):
            mesh = meshes.get(leaf)
            if mesh is None or len(mesh.faces) == 0:
                continue
            moved = mesh.copy()
            moved.apply_transform(placement)
            bounds = moved.bounds
            placed.append({
                "objectid": leaf[1],
                "part": leaf[0],
                "via_item": object_id,
                "bbox_mm": [round(float(v), 4) for v in moved.extents],
                "min_mm": [round(float(v), 4) for v in bounds[0]],
                "max_mm": [round(float(v), 4) for v in bounds[1]],
                "volume_mm3": (round(float(abs(moved.volume)), 4)
                               if moved.is_watertight else None),
            })

    mesh_records = [r for r in ordered if r["geometry"] is not None]
    if not ordered:
        findings.append("no objects: there is nothing in this scene to modify")
    elif not mesh_records:
        # Objects that are all component wrappers, pointing at each other or at
        # nothing. The scene parses; there is still no geometry in it.
        findings.append("no mesh anywhere in the archive: every object is a "
                        "component wrapper, so there is no geometry to build on")
    if unit != "millimeter":
        findings.append(f"the scene declares unit={unit!r}, so every number in it "
                        "is in that unit and not in millimetres")
    if dangling:
        findings.append(f"component(s) reference object id(s) that are not in the "
                        f"file: {sorted(dangling)}")
    if unplaced:
        findings.append(f"build item(s) reference object id(s) that are not in the "
                        f"file: {sorted(unplaced)}")
    for (parent, child) in sorted(cycles):
        findings.append(
            f"object {parent[1]!r} in {parent[0]!r} reaches object {child[1]!r} "
            f"in {child[0]!r}, which is already on the way there: the component "
            "chain is a cycle and assembling this scene does not terminate")
        unsound = True
    for target in sorted(too_deep):
        findings.append(
            f"the component chain reaching object {target[1]!r} in {target[0]!r} "
            f"is more than {_MAX_COMPONENT_DEPTH} deep, which is a malformed "
            "file rather than a scene; the walk stopped short of it, so that "
            "object and anything under it were not placed")
        unsound = True

    for record in mesh_records:
        geometry = record["geometry"]
        where = f"object {record['id']!r} in {record['part']!r}"
        if geometry["triangles"] == 0:
            findings.append(f"{where} declares a mesh with no triangles")
            unsound = True
            continue
        if not geometry["watertight"]:
            findings.append(f"{where} is not watertight: "
                            f"{geometry['boundary_edges']} boundary edge(s)")
            unsound = True
        if not geometry["winding_consistent"]:
            findings.append(f"{where} has inconsistent winding, so inside and "
                            "outside are not well defined")
            unsound = True

    # The assembled scene where the build says where things go; the authored
    # extents where it does not, which is a different claim and is labelled one.
    authored = [r["geometry"]["bbox_mm"] for r in mesh_records
                if r["geometry"]["bbox_mm"]]
    if placed:
        lows = [min(p["min_mm"][i] for p in placed) for i in range(3)]
        highs = [max(p["max_mm"][i] for p in placed) for i in range(3)]
        bbox = [round(highs[i] - lows[i], 4) for i in range(3)]
    elif authored:
        bbox = [round(max(e[i] for e in authored), 4) for i in range(3)]
    else:
        bbox = []

    watertight = bool(mesh_records) and all(
        r["geometry"]["watertight"] for r in mesh_records)
    volumes = [p["volume_mm3"] for p in placed]
    classification = ("RECONSTRUCTION_REQUIRED" if not ordered or not mesh_records
                      else "REPAIR_REQUIRED"
                      if (dangling or unplaced or unsound or unit != "millimeter")
                      else "USABLE_MESH")
    return {
        "format": "3MF",
        "units": unit,
        "units_note": "read from the model part's own unit attribute",
        "root_part": root_key,
        "model_parts": model_keys,
        "bodies": len(mesh_records),
        "objects": ordered,
        "build_items": items,
        "placed": placed,
        "materials": materials,
        "triangles": sum(r["geometry"]["triangles"] for r in mesh_records),
        "bbox_mm": bbox,
        "bbox_note": ("the assembled scene with every build transform applied"
                      if placed else
                      "no build item placed anything; this is the authored "
                      "extent of the largest object on each axis"),
        "watertight": watertight,
        "winding_consistent": bool(mesh_records) and all(
            r["geometry"]["winding_consistent"] for r in mesh_records),
        "volume_mm3": (round(sum(volumes), 4)
                       if volumes and all(v is not None for v in volumes)
                       else None),
        "scene_is_functional": bool(len(items) > 1 or materials
                                    or any(o["components"] for o in ordered)),
        "scale_suspicions": _scale_suspicions(bbox),
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
    elif fmt in ("STL", "OBJ", "3MF"):
        reader = _diagnose_3mf if fmt == "3MF" else _diagnose_mesh
        try:
            report = reader(path)
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
