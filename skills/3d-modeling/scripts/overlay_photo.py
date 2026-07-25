#!/usr/bin/env python3
"""Render-over-photo overlay: draw a candidate model's slice boundaries on top of the
user's (near-orthographic) top photo, plus a residual metric.

Usage: python3 overlay_photo.py <cand.stl> <photo.png> <out.png> [z_mm ...]

Mapping: candidate slice bbox is fit to the photo's segmented body bbox (scale+translate,
y flipped: model +Y = photo up). Residual = mean/p90 distance (mm) from candidate
boundary pixels to the nearest photo edge pixel — drives the iterate loop; the overlay
image is what you LOOK at to decide which feature moves where.
Loop discipline: photo only — the ground-truth reference must never enter the loop.
"""
import os
import sys

import numpy as np
import trimesh
from PIL import Image, ImageDraw
from scipy import ndimage

# verify_visual.py lives alongside this file in scripts/; make it importable.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from verify_visual import slice_union  # noqa: E402  (needs the sys.path bootstrap above)


def segment_body(a):
    """photo body bbox from non-white profiles (label rows excluded by >50px rule)"""
    nonwhite = a.sum(2) < 720
    rows, cols = nonwhite.sum(1), nonwhite.sum(0)
    ys = np.where(rows > 50)[0]
    xs = np.where(cols > 50)[0]
    return xs.min(), xs.max(), ys.min(), ys.max(), nonwhite


def photo_edges(a, body):
    g = a.mean(2)
    gy, gx = np.gradient(g)
    mag = np.hypot(gx, gy)
    edges = (mag > 8) & body
    return edges


def boundaries_px(m, zs, to_px):
    """candidate slice boundary points, mapped to photo px, grouped per ring"""
    rings = []
    for z in zs:
        u = slice_union(m, z)
        if u is None:
            continue
        for poly in getattr(u, 'geoms', [u]):
            for ring in [poly.exterior] + list(poly.interiors):
                pts = np.array(ring.coords)
                rings.append(np.array([to_px(x, y) for x, y in pts]))
    return rings


def main():
    stl, photo_p, out_p = sys.argv[1], sys.argv[2], sys.argv[3]
    zs = [float(z) for z in sys.argv[4:]] or [3.5, 22.0]
    im = Image.open(photo_p).convert('RGB')
    a = np.asarray(im).astype(int)
    x0p, x1p, y0p, y1p, nonwhite = segment_body(a)

    m = trimesh.load(stl)
    if hasattr(m, 'geometry'):
        m = max(m.geometry.values(), key=lambda g: abs(g.volume))
    m = m.copy()
    m.apply_translation(-m.bounds[0])
    bx, by = m.bounds[1][0], m.bounds[1][1]
    sx = (x1p - x0p) / bx
    sy = (y1p - y0p) / by

    def to_px(x, y):
        return (x0p + x * sx, y1p - y * sy)   # model +Y = photo up

    rings = boundaries_px(m, zs, to_px)

    # residual: candidate boundary px -> nearest photo edge px, in mm
    edges = photo_edges(a, nonwhite)
    dist = ndimage.distance_transform_edt(~edges)
    ds = []
    for r in rings:
        for (px, py) in r[::2]:
            xi, yi = int(round(px)), int(round(py))
            if 0 <= yi < dist.shape[0] and 0 <= xi < dist.shape[1]:
                ds.append(dist[yi, xi] / ((sx + sy) / 2))
    ds = np.array(ds) if ds else np.array([99.0])

    ov = im.copy()
    d = ImageDraw.Draw(ov)
    for r in rings:
        d.line([tuple(p) for p in r], fill=(230, 30, 30), width=2)
    d.text((6, im.height - 18),
           f"residual mm: mean {ds.mean():.2f}  p90 {np.percentile(ds, 90):.2f}  "
           f"scale {1/sx:.3f}/{1/sy:.3f} mm/px  z={zs}", fill=(0, 0, 0))
    ov.save(out_p)
    print(f"residual mm: mean {ds.mean():.2f}  p90 {np.percentile(ds, 90):.2f}  n={len(ds)}")
    print('overlay:', out_p)


if __name__ == '__main__':
    main()
