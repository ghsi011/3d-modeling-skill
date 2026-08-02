"""Cut the anti-rotation flat into the supplied ball's flange, and nothing else.

The supplied artifact is loaded and edited. It is deliberately not redrawn: a
model rebuilt from scratch to add one feature is indistinguishable from an edit
by every check in this pipeline except the preservation audit, and the audit is
the reason the edit scope beside this file names a region.

`__SOURCE__` is replaced by the replay harness with the path the supplied
artifact was materialised at. A recorded model cannot carry the path of a
temporary directory that does not exist yet; `case.json` declares the
substitution.
"""
import trimesh

PARAMS = {
    "flat_depth_mm": 2.0,
    "flat_top_z_mm": 3.5,
    # The supplied artifact's own +y extreme, read off the file rather than
    # chosen. The flat is cut `flat_depth_mm` inboard of it.
    "source_y_max_mm": 174.98655700683594,
    "source_x_mid_mm": 181.74044799804688,
}

SOURCE = r"__SOURCE__"


def build():
    ball = trimesh.load(SOURCE, process=True, force="mesh")
    plane_y = PARAMS["source_y_max_mm"] - PARAMS["flat_depth_mm"]
    top = PARAMS["flat_top_z_mm"]
    # A box with vertical walls, open below the bed. Every face it introduces is
    # vertical or is on the bed, so the edit adds no downward-facing area to the
    # overhang the candidate inherits from the part it was given.
    cutter = trimesh.creation.box(extents=(60.0, 20.0, top + 2.0))
    cutter.apply_translation((PARAMS["source_x_mid_mm"], plane_y + 10.0,
                              (top + 2.0) / 2.0 - 2.0))
    return trimesh.boolean.difference([ball, cutter], engine="manifold")
