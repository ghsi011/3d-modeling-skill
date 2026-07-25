"""Rendered comparisons (pyrender-backed; optional — needs a GL context).

* ``compare_views()`` — the ref-vs-candidate view grid the designer must LOOK at
  (same cameras top/front/iso), one image, reference row over candidate row.
* ``section_render()`` — a capped half-section render for internal-feature review.

Both wrap ``scripts/preview.render_view`` so cameras match the rest of the
pipeline. The pyrender import is deferred to call time and re-raised with a clear
message, so importing ``designer_toolkit`` never fails on a headless box that
merely lacks a renderer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import trimesh

from . import _bootstrap  # noqa: F401  (puts scripts/ on sys.path; keep first)

import mesh_io

DEFAULT_VIEWS = ((89, -90), (5, -90), (25, -60))  # top, front, iso
_TILE = 420


def _as_render_mesh(mesh_or_path: Any) -> trimesh.Trimesh:
    # Rendering wants the repaired/normalized mesh, not the raw acceptance parse.
    if isinstance(mesh_or_path, (str, Path)):
        return mesh_io.load_mesh(mesh_or_path)
    return mesh_or_path


def _render_view(*args, **kwargs):
    try:
        from preview import render_view
    except Exception as exc:  # noqa: BLE001 - surface the missing renderer clearly
        raise RuntimeError(
            "designer_toolkit.render needs a working pyrender/GL context "
            f"(scripts/preview.py failed to import: {exc})"
        ) from exc
    return render_view(*args, **kwargs)


def compare_views(reference: Any, candidate: Any, out_path: str | Path, *,
                  views=DEFAULT_VIEWS, tile: int = _TILE) -> str:
    """Render ``reference`` (top row) and ``candidate`` (bottom row) from the
    same cameras into one side-by-side PNG. LOOK at it: silhouette, feature
    shapes, counts, positions — before trusting any single number.
    """
    from PIL import Image

    ref_m = _as_render_mesh(reference)
    cand_m = _as_render_mesh(candidate)
    row_r = [_render_view(ref_m, e, a, tile, tile) for e, a in views]
    row_c = [_render_view(cand_m, e, a, tile, tile) for e, a in views]
    canvas = Image.new("RGB", (len(views) * tile, 2 * tile), "white")
    for i, im in enumerate(row_r + row_c):
        canvas.paste(im, ((i % len(views)) * tile, (i // len(views)) * tile))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(str(out_path))
    return str(out_path)


def section_render(mesh_or_path: Any, out_path: str | Path, *,
                   plane_origin=(0, 0, 0), plane_normal=(1, 0, 0),
                   elev: float = 25, azim: float = -60, tile: int = 640) -> str:
    """Cap-slice the mesh at a plane and render the cut half from one iso camera,
    so internal walls/bores are visible.
    """
    m = _as_render_mesh(mesh_or_path)
    half = m.slice_plane(np.asarray(plane_origin, dtype=float),
                         np.asarray(plane_normal, dtype=float), cap=True)
    if half is None or len(half.faces) == 0:
        raise ValueError("section plane did not intersect the mesh")
    img = _render_view(half, elev, azim, tile, tile)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out_path))
    return str(out_path)
