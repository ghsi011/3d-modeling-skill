#!/usr/bin/env python3
"""Primitive mesh CSG, with manifold3d selected explicitly at every boolean.

Never `trimesh.boolean.*` without `engine="manifold"`. Automatic engine selection
is a commissioning failure, not a convenience: whichever engine happens to be
importable then decides the result, and a receipt that does not name the engine
cannot be reproduced.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import trimesh

from . import BuildArtifacts

ENGINE = "manifold"

# Where the mounting screw sits along the flange, as a fraction of its width.
# Shared with the expectations only as a number in the contract, never as an
# import: the two sides must not be able to move together.
SCREW_X_FRACTION = 0.2

# How far a free-standing boss sits from the wall beside it. Not zero: see
# `build_vented_enclosure` for what tangency costs.
BOSS_CLEARANCE_MM = 1.0


def _boolean(op: str, meshes: list[trimesh.Trimesh]) -> trimesh.Trimesh:
    fn = {"difference": trimesh.boolean.difference,
          "union": trimesh.boolean.union,
          "intersection": trimesh.boolean.intersection}[op]
    return fn(meshes, engine=ENGINE)


def seated(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Minimum Z at zero.

    `trimesh.creation.box()` is centred on the origin, so the library default is
    the opposite of this pipeline's convention: a mesh built by hand is
    underground unless somebody moved it. Call this rather than retyping the
    arithmetic -- three test fixtures encoded a part half below the bed because
    the convention was prose and not a function.
    """
    mesh.apply_translation((0.0, 0.0, -float(mesh.bounds[0][2])))
    return mesh


def _box(extents, centre) -> trimesh.Trimesh:
    mesh = trimesh.creation.box(extents=extents)
    mesh.apply_translation(centre)
    return mesh


def _cylinder(radius: float, height: float, centre, sections: int = 96) -> trimesh.Trimesh:
    mesh = trimesh.creation.cylinder(radius=radius, height=height, sections=sections)
    mesh.apply_translation(centre)
    return mesh


def build_c_clip(p: dict[str, Any]) -> tuple[trimesh.Trimesh, list[str]]:
    """A C-channel on a mounting flange, axis along Z so every wall is vertical."""
    fw, fd, ft = float(p["flange_w"]), float(p["flange_d"]), float(p["flange_t"])
    bore_d, wall, height = float(p["bore_d"]), float(p["wall"]), float(p["height"])
    gap, screw_d = float(p["mouth_gap"]), float(p["screw_d"])

    cx, cy = fw / 2.0, fd / 2.0
    outer_r, inner_r = bore_d / 2.0 + wall, bore_d / 2.0
    ops: list[str] = []

    flange = _box((fw, fd, ft), (cx, cy, ft / 2.0))
    ring_z = ft + height / 2.0
    ring = _boolean("difference", [
        _cylinder(outer_r, height, (cx, cy, ring_z)),
        # Overshoot the bore through both ends: a cutter whose face lands exactly
        # on the surface it crosses leaves coplanar artifacts that survive as
        # degenerate faces and fail repair on re-import.
        _cylinder(inner_r, height + 2.0, (cx, cy, ring_z)),
    ])
    ops.append("difference: ring outer - bore")

    # The mouth: a straight slot on one side, running the full ring height so a
    # bundle can be pressed in anywhere along it.
    mouth = _box((gap, outer_r + 2.0, height + 2.0),
                 (cx, cy + (outer_r + 2.0) / 2.0, ring_z))
    ring = _boolean("difference", [ring, mouth])
    ops.append("difference: ring - mouth slot")

    part = _boolean("union", [flange, ring])
    ops.append("union: flange + ring")

    # Clear of the channel on purpose. A screw on the flange centre sits directly
    # under the bore, where a driver cannot reach it and the bundle wants to be.
    screw = _cylinder(screw_d / 2.0, ft + 2.0, (fw * SCREW_X_FRACTION, cy, ft / 2.0))
    part = _boolean("difference", [part, screw])
    ops.append("difference: part - screw bore")

    return seated(part), ops


_BUILDERS: dict = {}


class TrimeshManifoldBackend:
    name = "trimesh-manifold"

    def build(self, contract, output_dir: Path) -> BuildArtifacts:
        import manifold3d

        started = time.perf_counter()
        builder = _BUILDERS.get(contract.template)
        if builder is None:
            raise KeyError(f"{self.name}: no builder for template {contract.template!r}")
        part, ops = builder(contract.parameters)

        output_dir.mkdir(parents=True, exist_ok=True)
        stl_path = output_dir / "candidate.stl"
        part.export(stl_path)

        source_path = output_dir / "model.py"
        source_path.write_text(
            "# Generated from model_contract.json. The contract is authoritative;\n"
            "# this file is a record of what was built, not a source of expectations.\n"
            f"TEMPLATE = {contract.template!r}\n"
            f"BACKEND = {self.name!r}\n"
            f"PARAMETERS = {contract.parameters!r}\n",
            encoding="utf-8")

        if contract.step_required:
            raise ValueError(
                f"{self.name} exports STL only. The contract requires STEP, which needs "
                "a B-rep kernel -- route this template to build123d or drop the "
                "requirement.")

        return BuildArtifacts(
            stl_path=stl_path, step_path=None, source_path=source_path,
            backend=self.name,
            backend_version=f"trimesh {trimesh.__version__}/manifold3d "
                            f"{getattr(manifold3d, '__version__', 'unknown')}",
            tessellation={"cylinder_sections": 96, "note": "primitives are already meshes"},
            boolean_ops=tuple(ops),
            build_seconds=time.perf_counter() - started,
        )




def build_box_shell(p: dict[str, Any]) -> tuple[trimesh.Trimesh, list[str]]:
    """A walled box: enclosure, tray, drawer, bin. Open top."""
    iw, id_, ih = float(p["inner_w"]), float(p["inner_d"]), float(p["inner_h"])
    wall, floor = float(p["wall"]), float(p["floor"])
    ow, od, oh = iw + 2.0 * wall, id_ + 2.0 * wall, floor + ih
    ops: list[str] = []

    shell = _box((ow, od, oh), (ow / 2.0, od / 2.0, oh / 2.0))
    # Overshoot the cavity through the top so it breaks the surface cleanly: a
    # cutter face landing exactly on the face it crosses leaves coplanar
    # artifacts that survive as degenerate faces and fail repair on re-import.
    cavity_h = ih + wall
    cavity = _box((iw, id_, cavity_h), (ow / 2.0, od / 2.0, floor + cavity_h / 2.0))
    part = _boolean("difference", [shell, cavity])
    ops.append("difference: shell - cavity, overshot through the top")
    return seated(part), ops


def build_l_bracket(p: dict[str, Any]) -> tuple[trimesh.Trimesh, list[str]]:
    """Two plates at a right angle, a fastener hole through each.

    Printed with the corner in the bed plane so neither leg overhangs: the flat
    leg lies down and the upright rises from it, which is why the expectations
    section the two separately.
    """
    width = float(p["width"])
    leg_a, leg_b, t = float(p["leg_a"]), float(p["leg_b"]), float(p["thickness"])
    hole_d, inset = float(p["hole_d"]), float(p["hole_inset"])
    ops: list[str] = []

    flat = _box((width, leg_b, t), (width / 2.0, leg_b / 2.0, t / 2.0))
    upright = _box((width, t, leg_a), (width / 2.0, t / 2.0, leg_a / 2.0))
    part = _boolean("union", [flat, upright])
    ops.append("union: flat leg + upright")

    flat_hole = _cylinder(hole_d / 2.0, t + 2.0, (width / 2.0, leg_b - inset, t / 2.0))
    part = _boolean("difference", [part, flat_hole])
    ops.append("difference: fastener hole through the flat leg")

    upright_hole = _cylinder(hole_d / 2.0, t + 2.0, (width / 2.0, t / 2.0, leg_a - inset))
    upright_hole.apply_transform(trimesh.transformations.rotation_matrix(
        3.141592653589793 / 2.0, [1, 0, 0], (width / 2.0, t / 2.0, leg_a - inset)))
    part = _boolean("difference", [part, upright_hole])
    ops.append("difference: fastener hole through the upright")
    return seated(part), ops




def build_vented_enclosure(p: dict[str, Any]) -> tuple[trimesh.Trimesh, list[str]]:
    """A walled box with a vent grid through one wall and mounting bosses inside.

    The complex one, and complex in the way that matters: `cols * rows` cuts plus
    four bosses is dozens of booleans against one solid, which is where a mesh
    kernel actually gets tested. The vents go through the +Y wall only, so the
    other three stay solid and the wall-ring expectation has something to hold.
    """
    iw, id_, ih = float(p["inner_w"]), float(p["inner_d"]), float(p["inner_h"])
    wall, floor = float(p["wall"]), float(p["floor"])
    cols, rows = int(p["vent_cols"]), int(p["vent_rows"])
    vw, vh = float(p["vent_w"]), float(p["vent_h"])
    boss_d, boss_bore = float(p["boss_d"]), float(p["boss_bore"])

    ow, od, oh = iw + 2.0 * wall, id_ + 2.0 * wall, floor + ih
    ops: list[str] = []

    part = _boolean("difference", [
        _box((ow, od, oh), (ow / 2.0, od / 2.0, oh / 2.0)),
        _box((iw, id_, ih + wall), (ow / 2.0, od / 2.0, floor + (ih + wall) / 2.0)),
    ])
    ops.append("difference: shell - cavity")

    # Every vent cut in one union, then one subtraction. A chain of `cols*rows`
    # sequential differences costs the same booleans and gives the kernel more
    # chances to leave a sliver between them.
    pitch_x, pitch_z = ow / (cols + 1), ih / (rows + 1)
    cutters = []
    for i in range(cols):
        for j in range(rows):
            cutters.append(_box((vw, wall * 3.0, vh),
                                (pitch_x * (i + 1), od - wall / 2.0,
                                 floor + pitch_z * (j + 1))))
    part = _boolean("difference", [part, _boolean("union", cutters)])
    ops.append(f"difference: part - {cols * rows} vents, unioned first")

    # Stood clear of the walls rather than tangent to them. A boss whose surface
    # exactly touches the wall's produces an edge where three faces meet: the
    # mesh has no open boundary and is still not a volume, so it exports fine,
    # reimports fine, and the boolean engine then refuses to measure it. Tangency
    # is the trap -- overlap or clearance, never touching.
    inset = wall + boss_d / 2.0 + BOSS_CLEARANCE_MM
    bosses = [_cylinder(boss_d / 2.0, ih, (x, y, floor + ih / 2.0))
              for x in (inset, ow - inset) for y in (inset, od - inset)]
    part = _boolean("union", [part, _boolean("union", bosses)])
    ops.append("union: four corner bosses")

    bores = [_cylinder(boss_bore / 2.0, ih + 2.0, (x, y, floor + ih / 2.0))
             for x in (inset, ow - inset) for y in (inset, od - inset)]
    part = _boolean("difference", [part, _boolean("union", bores)])
    ops.append("difference: four boss bores, overshot")
    return seated(part), ops


_BUILDERS.update({"c_clip": build_c_clip, "box_shell": build_box_shell,
                  "l_bracket": build_l_bracket,
                  "vented_enclosure": build_vented_enclosure})

__all__ = ["TrimeshManifoldBackend", "build_c_clip", "build_box_shell",
           "build_l_bracket", "build_vented_enclosure", "seated", "ENGINE"]
