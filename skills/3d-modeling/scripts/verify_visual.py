#!/usr/bin/env python3
"""Visual + layout verification of a candidate model against a reference model.

Usage:
  uv run --project <skill> --frozen python <skill>/scripts/verify_visual.py <ref-stl-or-dir> <cand-stl-or-dir> <out-prefix> [--test T4] [--json]

Produces:
  <out-prefix>_compare.png   side-by-side composite: ref row / cand row (identical
                             cameras) + slice-overlay row (ref=red cand=blue overlap=dark)
  <out-prefix>_verify.json   metrics: bbox delta, slice material/cavity IoU, mirror flag,
                             feature-position checks (test-specific)

Design rules this tool enforces (see verification_postmortem.md):
  - candidate is ALWAYS rendered beside the reference from the same cameras
  - layout is scored by rasterized overlap (IoU), not by counting features
  - feature POSITIONS are compared to the reference's positions, not just sizes
  - a mirrored candidate that fits better than the direct one is flagged, never
    silently accepted
The grader must view the composite and describe both rows before recording a score.
"""
import glob
import importlib.util
import json
import os
import sys

import numpy as np
import shapely.geometry as sg
import trimesh
from PIL import Image, ImageDraw, ImageFont
from shapely.ops import unary_union

# preview.py lives alongside this file in scripts/; make it importable.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('PYOPENGL_PLATFORM', 'egl')
from preview import render_view  # noqa: E402  (needs the sys.path bootstrap above)

RES = 0.5          # raster resolution mm/px for IoU
ZFRACS = [0.18, 0.35, 0.5, 0.7, 0.88]


def _font(size=16):
    for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def load_main(path):
    """Load the main body mesh: largest-volume part, scorer-compatible skip rules."""
    files = sorted(glob.glob(os.path.join(path, '**/*.stl'), recursive=True)) \
        if os.path.isdir(path) else [path]
    skip = ('_check', 'section', 'preview', 'ref_', 'fixture')
    kept = [f for f in files if not any(s in os.path.basename(f).lower() for s in skip)] or files
    meshes = []
    for f in kept:
        m = trimesh.load(f)
        meshes += list(m.geometry.values()) if hasattr(m, 'geometry') else [m]
    if not meshes:
        raise SystemExit(f'no meshes under {path}')
    def bulk(x):
        try:
            return abs(x.volume) if x.is_volume else abs(x.convex_hull.volume)
        except Exception:
            return float(x.area)
    m = max(meshes, key=bulk).copy()
    m.apply_translation(-m.bounds[0])
    return m, kept


# trimesh soft dependencies the cross-section path reaches in turn: scipy (csgraph,
# walking the cut edges), networkx (vertex graph -> closed paths), rtree (the
# enclosure tree that decides which ring is a hole). shapely is imported at module
# scope above, so it cannot be silently missing by the time we get here. Shipped
# with shapely as the `section` extra and folded into `visual`.
_SECTION_STACK = ("scipy", "networkx", "rtree")
_section_stack_ok = False


def _require_section_stack():
    """Fail fast, and legibly, when the cross-section stack is not installed.

    ``polygons_full`` defers each ImportError into trimesh's own call stack, where
    ``slice_union``'s catch-all below turns it into a bare ``None`` — and downstream
    that reads as "this slice is empty", not "this install is incomplete". A part
    sliced against ITSELF then scores IoU 0.0 instead of 1.0, so every overlay and
    alignment number silently collapses instead of erroring. Checking up front
    keeps the catch-all for what it is actually for (degenerate or empty sections)
    while naming all the missing packages at once. Mirrors
    ``designer_toolkit.metrics._require_section_stack``.
    """
    global _section_stack_ok
    if _section_stack_ok:
        return
    missing = [n for n in _SECTION_STACK if importlib.util.find_spec(n) is None]
    if missing:
        raise ImportError(
            f"slice_union() needs {', '.join(missing)} "
            f"(mesh cross-section + ring extraction): uv sync --frozen --no-dev --extra visual"
        )
    _section_stack_ok = True


def slice_union(m, z):
    """cross-section as shapely geometry in MODEL-FRAME XY coordinates.
    to_2D() without a transform re-origins on a path-dependent frame (varies per
    mesh/slice!) — always pass plane_transform to stay in model coordinates.
    Returns None for a genuinely empty/degenerate section; a missing dependency
    raises instead of masquerading as one."""
    _require_section_stack()
    try:
        sec = m.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
        if sec is None:
            return None
        p, _ = sec.to_2D(trimesh.geometry.plane_transform([0, 0, z], [0, 0, 1]))
        polys = list(p.polygons_full)
        return unary_union(polys).buffer(0) if polys else None
    except Exception:
        return None


def rasterize(u, x0, y0, nx, ny):
    """boolean grid of a shapely geometry, cell centers, RES spacing"""
    g = np.zeros((ny, nx), bool)
    if u is None or u.is_empty:
        return g
    xs = x0 + (np.arange(nx) + 0.5) * RES
    ys = y0 + (np.arange(ny) + 0.5) * RES
    try:
        import shapely
        pts = np.array(np.meshgrid(xs, ys)).reshape(2, -1).T
        mask = shapely.contains_xy(u, pts[:, 0], pts[:, 1])
        return mask.reshape(ny, nx)
    except Exception:
        from shapely.prepared import prep
        pu = prep(u)
        for j, y in enumerate(ys):
            for i, x in enumerate(xs):
                g[j, i] = pu.contains(sg.Point(x, y))
        return g


def rot_z(m, k):
    """k*90deg rotation about bbox center, min corner re-zeroed"""
    mm = m.copy()
    if k:
        c = (mm.bounds[0] + mm.bounds[1]) / 2
        mm.apply_transform(trimesh.transformations.rotation_matrix(k * np.pi / 2, [0, 0, 1], c))
    mm.apply_translation(-mm.bounds[0])
    return mm


def mirror_x(m):
    mm = m.copy()
    mm.apply_transform(np.diag([-1, 1, 1, 1.0]))
    mm.invert()  # fix winding
    mm.apply_translation(-mm.bounds[0])
    return mm


def pose_score(ref, cand):
    """alignment score = full-height projected-cavity IoU on a coarse grid.
    Mid-slice sampling misses features that exist only near a face (e.g. a camera
    hole in a 2 mm back wall) and cannot resolve 180° flips of symmetric outlines."""
    x0 = min(ref.bounds[0][0], cand.bounds[0][0]) - 1
    y0 = min(ref.bounds[0][1], cand.bounds[0][1]) - 1
    x1 = max(ref.bounds[1][0], cand.bounds[1][0]) + 1
    y1 = max(ref.bounds[1][1], cand.bounds[1][1]) + 1
    global RES
    saved, RES = RES, 1.0
    try:
        nx, ny = int((x1 - x0) / RES) + 1, int((y1 - y0) / RES) + 1
        grids = (x0, y0, nx, ny)
        cr, _ = projected_cavity(ref, grids, nz=6)
        cc, _ = projected_cavity(cand, grids, nz=6)
    finally:
        RES = saved
    uni = (cr | cc).sum()
    return float((cr & cc).sum() / uni) if uni else 1.0


def align_candidate(ref, cand):
    """best of 4 z-rotations, direct; mirrored best returned separately for an
    explicit apples-to-apples flag (mirrored is never silently accepted)"""
    best = (-1, 0, None)
    for k in range(4):
        c = rot_z(cand, k)
        s = pose_score(ref, c)
        if s > best[0]:
            best = (s, k, c)
    mbest = (-1, 0, None)
    cm = mirror_x(cand)
    for k in range(4):
        c = rot_z(cm, k)
        s = pose_score(ref, c)
        if s > mbest[0]:
            mbest = (s, k, c)
    return best[2], best[1], best[0], mbest[0], mbest[2]


def slice_metrics(ref, cand):
    """material + cavity IoU at matched relative heights"""
    out = []
    hr, hc = ref.bounds[1][2], cand.bounds[1][2]
    x0 = min(ref.bounds[0][0], cand.bounds[0][0]) - 1
    y0 = min(ref.bounds[0][1], cand.bounds[0][1]) - 1
    x1 = max(ref.bounds[1][0], cand.bounds[1][0]) + 1
    y1 = max(ref.bounds[1][1], cand.bounds[1][1]) + 1
    nx, ny = int((x1 - x0) / RES) + 1, int((y1 - y0) / RES) + 1
    for zf in ZFRACS:
        ur = slice_union(ref, max(0.4, min(hr - 0.4, zf * hr)))
        uc = slice_union(cand, max(0.4, min(hc - 0.4, zf * hc)))
        gr, gc = rasterize(ur, x0, y0, nx, ny), rasterize(uc, x0, y0, nx, ny)
        uni = (gr | gc).sum()
        mat = (gr & gc).sum() / uni if uni else 0.0
        # cavity = hull minus material, per mesh, on same grid
        def cav(u, g):
            if u is None or u.is_empty:
                return np.zeros_like(g)
            return rasterize(u.convex_hull, x0, y0, nx, ny) & ~g
        cr, cc = cav(ur, gr), cav(uc, gc)
        cuni = (cr | cc).sum()
        cavio = (cr & cc).sum() / cuni if cuni else 1.0
        out.append(dict(zfrac=zf, material_iou=round(float(mat), 3),
                        cavity_iou=round(float(cavio), 3)))
    grids = (x0, y0, nx, ny)
    return out, grids


def projected_cavity(m, grids, nz=9):
    """XY cells that are cavity (inside hull, not material) in ANY *body* slice — the
    top-view pocket layout, independent of pocket depth.
    Rim-only slices (material < 25% of hull, e.g. a tray's raised edge or a case's
    bare side walls) are excluded: hull-minus-material there marks the whole footprint
    as cavity and floods the projection (caught visually — red-flooded panel)."""
    x0, y0, nx, ny = grids
    h = m.bounds[1][2]
    acc = np.zeros((ny, nx), bool)
    hull_any = np.zeros((ny, nx), bool)
    for zf in np.linspace(0.12, 0.92, nz):
        u = slice_union(m, max(0.4, min(h - 0.4, zf * h)))
        if u is None or u.is_empty:
            continue
        g = rasterize(u, x0, y0, nx, ny)
        gh = rasterize(u.convex_hull, x0, y0, nx, ny)
        if g.sum() < 0.25 * gh.sum():
            continue  # rim-only slice
        acc |= (gh & ~g)
        hull_any |= gh
    if not acc.any():
        # every slice was rim-like (thin-walled deep-pocket parts) — fall back to
        # the slice with the highest material fraction so the mask is never empty
        best, best_frac = None, -1.0
        for zf in np.linspace(0.12, 0.92, nz):
            u = slice_union(m, max(0.4, min(h - 0.4, zf * h)))
            if u is None or u.is_empty:
                continue
            g = rasterize(u, x0, y0, nx, ny)
            gh = rasterize(u.convex_hull, x0, y0, nx, ny)
            frac = g.sum() / max(gh.sum(), 1)
            if frac > best_frac:
                best, best_frac = (gh & ~g, gh), frac
        if best is not None:
            acc, hull_any = acc | best[0], hull_any | best[1]
    return acc, hull_any


def layout_iou(ref, cand, grids):
    cr, _ = projected_cavity(ref, grids)
    cc, _ = projected_cavity(cand, grids)
    uni = (cr | cc).sum()
    return ((cr & cc).sum() / uni if uni else 1.0), cr, cc


def boundary_f1(mr, mc, tol_px=3):
    """BF-score of projected-cavity boundaries: do the pocket OUTLINES coincide?
    Punishes wrong shapes (rectangle vs tool silhouette) that area-IoU forgives."""
    from scipy import ndimage
    def bound(m):
        return m & ~ndimage.binary_erosion(m)
    br, bc = bound(mr), bound(mc)
    if not br.any() or not bc.any():
        return 0.0
    st = ndimage.iterate_structure(ndimage.generate_binary_structure(2, 1), tol_px)
    prec = (bc & ndimage.binary_dilation(br, st)).sum() / bc.sum()
    rec = (br & ndimage.binary_dilation(bc, st)).sum() / br.sum()
    return float(2 * prec * rec / (prec + rec)) if prec + rec else 0.0


def overlay_img(ref, cand, z_ref, z_cand, grids, scale=3):
    x0, y0, nx, ny = grids
    gr = rasterize(slice_union(ref, z_ref), x0, y0, nx, ny)
    gc = rasterize(slice_union(cand, z_cand), x0, y0, nx, ny)
    img = np.full((ny, nx, 3), 255, np.uint8)
    img[gr & ~gc] = (225, 70, 70)    # reference only  -> red
    img[gc & ~gr] = (70, 100, 230)   # candidate only  -> blue
    img[gr & gc] = (85, 60, 110)     # overlap         -> dark purple
    im = Image.fromarray(img[::-1])  # y up
    return im.resize((nx * scale, ny * scale), Image.NEAREST)


def mask_overlay_img(mr, mc, scale=3):
    ny, nx = mr.shape
    img = np.full((ny, nx, 3), 255, np.uint8)
    img[mr & ~mc] = (225, 70, 70)
    img[mc & ~mr] = (70, 100, 230)
    img[mr & mc] = (85, 60, 110)
    im = Image.fromarray(img[::-1])
    return im.resize((nx * scale, ny * scale), Image.NEAREST)


def feature_holes(m, zs, min_dim=15, max_area=2600):
    """interior holes (w,h,center) in slices at absolute z values"""
    found = []
    for z in zs:
        u = slice_union(m, z)
        if u is None:
            continue
        for poly in getattr(u, 'geoms', [u]):
            for h in poly.interiors:
                c = np.array(h.coords)
                mn, mx = c.min(0), c.max(0)
                w, hh = mx[0] - mn[0], mx[1] - mn[1]
                if min(w, hh) >= min_dim and sg.Polygon(h).area <= max_area:
                    found.append(dict(z=float(z), w=float(w), h=float(hh),
                                      cx=float((mn[0] + mx[0]) / 2),
                                      cy=float((mn[1] + mx[1]) / 2)))
    return found


def camera_position_check(ref, cand):
    """T4: camera window center vs reference center, in bbox-relative coords.
    Datums: dx from footprint center (signed), dy from the TOP edge (y max)."""
    res = dict(name='camera window position vs reference', crit=True)
    def desc(m):
        h_top = m.bounds[1][2]
        zs = (0.6, 1.0, 1.6, h_top - 1.6, h_top - 1.0, h_top - 0.6)
        holes = feature_holes(m, [z for z in zs if 0.3 < z < h_top - 0.3])
        if not holes:
            return None
        h = max(holes, key=lambda x: x['w'] * x['h'])
        b = m.bounds
        return dict(w=round(h['w'], 1), h=round(h['h'], 1),
                    dx_center=round(h['cx'] - (b[0][0] + b[1][0]) / 2, 1),
                    dy_top=round(b[1][1] - h['cy'], 1))
    r, c = desc(ref), desc(cand)
    res['ref'], res['cand'] = r, c
    if not r or not c:
        res['ok'] = False
        res['detail'] = 'camera window not found in ' + ('reference' if not r else 'candidate')
        return res
    dx = c['dx_center'] - r['dx_center']
    dxm = -c['dx_center'] - r['dx_center']       # mirrored interpretation
    dy = c['dy_top'] - r['dy_top']
    res['offset_mm'] = dict(dx=round(dx, 1), dy=round(dy, 1), dx_if_mirrored=round(dxm, 1))
    direct_ok = abs(dx) <= 2.0 and abs(dy) <= 2.0
    mirror_ok = abs(dxm) <= 2.0 and abs(dy) <= 2.0
    res['ok'] = bool(direct_ok)
    res['mirrored_would_pass'] = bool(mirror_ok and not direct_ok)
    res['detail'] = (f"Δx={dx:+.1f} Δy={dy:+.1f} (tol ±2.0)" +
                     (" — MIRRORED placement would pass: check front/back orientation!"
                      if res['mirrored_would_pass'] else ""))
    return res


def compose(ref, cand, slices, grids, out_png, header, verdict_lines, proj_img=None):
    V = 420
    views = [(89, -90, 'Top'), (5, -90, 'Front'), (25, -60, 'Isometric')]
    imgs_r = [render_view(ref, e, a, V, V) for e, a, _ in views]
    imgs_c = [render_view(cand, e, a, V, V) for e, a, _ in views]
    hr, hc = ref.bounds[1][2], cand.bounds[1][2]
    raw = [overlay_img(ref, cand, max(0.4, min(hr - 0.4, zf * hr)),
                       max(0.4, min(hc - 0.4, zf * hc)), grids) for zf in (0.35, 0.5)]
    if proj_img is not None:
        raw.append(proj_img)
    ovs = []
    for im in raw:
        s = min(V / im.width, V / im.height)
        im = im.resize((int(im.width * s), int(im.height * s)))
        pad = Image.new('RGB', (V, V), 'white')
        pad.paste(im, ((V - im.width) // 2, (V - im.height) // 2))
        ovs.append(pad)
    gap, lab, head, foot = 6, 30, 60, 30 + 22 * len(verdict_lines)
    W = V * 3 + gap * 2
    H = head + 3 * (lab + V) + gap * 2 + foot
    canvas = Image.new('RGB', (W, H), 'white')
    d = ImageDraw.Draw(canvas)
    f_head, f_lab, f_small = _font(24), _font(17), _font(15)
    d.text((W // 2, 8), header, fill='black', font=f_head, anchor='mt')
    rows = [('REFERENCE (ground truth)', imgs_r, '#a03030'),
            ('CANDIDATE', imgs_c, '#3050a0'),
            ('SLICE OVERLAY  red=ref only · blue=cand only · dark=match', ovs, '#444444')]
    y = head
    for title, imgs, color in rows:
        d.text((W // 2, y + 4), title, fill=color, font=f_lab, anchor='mt')
        y += lab
        for i, im in enumerate(imgs):
            canvas.paste(im, (i * (V + gap), y))
            if title.startswith('SLICE'):
                zt = ('z=35%', 'z=50%', 'PROJECTED POCKETS')[i] if len(imgs) == 3 \
                    else ('z=35%', 'z=50%')[i]
                d.text((i * (V + gap) + 8, y + 6), zt, fill='#333333', font=f_small)
            else:
                d.text((i * (V + gap) + 8, y + 6), views[i][2], fill='#333333', font=f_small)
        y += V + gap
    for i, line in enumerate(verdict_lines):
        d.text((12, y + 6 + 22 * i), line, fill='black', font=f_small)
    canvas.save(out_png)


def main():
    ref_p, cand_p, prefix = sys.argv[1], sys.argv[2], sys.argv[3]
    test = sys.argv[sys.argv.index('--test') + 1] if '--test' in sys.argv else None
    ref, rf = load_main(ref_p)
    cand0, cf = load_main(cand_p)
    cand, rot_k, direct_fp, mirror_fp, cand_m = align_candidate(ref, cand0)
    slices, grids = slice_metrics(ref, cand)
    mat = [s['material_iou'] for s in slices]
    cav = [s['cavity_iou'] for s in slices]
    lio, mr_mask, mc_mask = layout_iou(ref, cand, grids)
    lio_mirror = None
    if cand_m is not None:
        lm, _, _ = layout_iou(ref, cand_m, grids)
        lio_mirror = round(float(lm), 3)
    res = dict(reference=rf, candidate=cf,
               bbox_ref=[round(float(x), 1) for x in ref.bounds[1] - ref.bounds[0]],
               bbox_cand=[round(float(x), 1) for x in cand.bounds[1] - cand.bounds[0]],
               rotation_deg=rot_k * 90,
               pose_score=round(direct_fp, 3),
               pose_score_mirrored=round(mirror_fp, 3),
               slices=slices,
               material_iou_mean=round(float(np.mean(mat)), 3),
               cavity_iou_mean=round(float(np.mean(cav)), 3),
               cavity_iou_min=round(float(np.min(cav)), 3),
               layout_iou=round(float(lio), 3),
               layout_iou_mirrored=lio_mirror,
               boundary_f1=round(boundary_f1(mr_mask, mc_mask), 3))
    res['mirror_flag'] = bool(lio_mirror is not None and
                              lio_mirror > res['layout_iou'] + 0.05)
    checks = []
    if test == 'T4':
        checks.append(camera_position_check(ref, cand))
    res['position_checks'] = checks
    li, bf = res['layout_iou'], res['boundary_f1']
    band = 'MATCH' if (li >= 0.7 and bf >= 0.55) else \
        ('PARTIAL' if (li >= 0.5 and bf >= 0.35) else 'LAYOUT MISMATCH')
    pos_fail = [c for c in checks if not c['ok']]
    if pos_fail:
        band = 'POSITION FAIL'
    res['layout_verdict'] = band
    verdict = [
        f"bbox ref {res['bbox_ref']}  cand {res['bbox_cand']}  (rot {res['rotation_deg']}°)",
        f"LAYOUT IoU (projected pockets) {li}   shape boundary-F1 {bf}   "
        f"slice cavity IoU mean {res['cavity_iou_mean']}   → {band}",
    ]
    if res['mirror_flag']:
        verdict.append(f"! MIRROR: mirrored candidate matches layout better "
                       f"(layout IoU {res['layout_iou_mirrored']} vs {li})"
                       f" — candidate likely mirrored vs reference")
    for c in checks:
        verdict.append(("PASS " if c['ok'] else "FAIL ") + c['name'] + ': ' + c.get('detail', ''))
    png = prefix + '_compare.png'
    compose(ref, cand, slices, grids, png, os.path.basename(prefix), verdict,
            proj_img=mask_overlay_img(mr_mask, mc_mask))
    res['composite'] = png
    with open(prefix + '_verify.json', 'w') as fh:
        json.dump(res, fh, indent=1)
    if '--json' in sys.argv:
        print(json.dumps(res))
    else:
        for line in verdict:
            print(line)
        print('composite:', png)


if __name__ == '__main__':
    main()
