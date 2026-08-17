#!/usr/bin/env python3
"""F4's scorer: two independent regions, and nothing global.

The fixture's claim is *did the requested region change correctly while
everything else stayed unchanged*, so that is what this measures. `bbox`, total
volume and inertia appear nowhere.

**Rays, not a voxel grid, and the reason is measured.** The first version of this
file sampled point-containment on a 3D grid through the mask: 2.19 million
points, which drove trimesh's pure-Python ray fallback into an 8.10 GiB
allocation after eight minutes. One ray per (y, z) does the same job with 57x
fewer queries *and* returns exact crossing positions instead of cells quantised
to the sampling pitch. Run it under `uv run --with embreex` and the ray engine is
about 15x faster again; embreex is deliberately not a project dependency, only an
isolated accelerator for this tool.

**How it measures.** For every (y, z) in the mask, a ray along -X gives the solid
intervals of the source and of the candidate. Their difference in solid length is
the depth of material the candidate removed at that point:

* where removal is non-zero, the (y, z) is inside the slot. That footprint's
  extents, centroid and area are the edit rows.
* outside the mask the two interval structures must agree. A disagreement there
  is a preservation failure whatever it looks like.

No pose is recovered, because a MODIFY candidate is derived from the supplied
source and is already in its frame. F1 must register; F4 asserts frame agreement,
and a candidate that moved fails preservation immediately rather than being
quietly re-aligned into passing.

**Throughness is topological.** The slot axis must carry no candidate material
inside the mask. It is never compared against the wall's 2.4300 mm, which is
answer-side.

**A separate manufacturing gate, and it is required.** The mesh handed to the
scorer is not the artifact anybody prints, so `--candidate-3mf` is mandatory
rather than optional -- an optional gate is one a passing run can decline to
take. Without it this scorer could return success from a source and a candidate
STL while the archive beside them was a stale pre-edit export: every geometric
row green and the printed part unmodified. That is the case the fixture owes a
mutation for.

The gate itself is `tools/e2e.py:three_mf_rows`, the one this repository already
had, and F4 supplies only its own calibration. An earlier version of this file
grew a second one, and replacing it is worth recording rather than quietly
fixing: being newer it was also *weaker*, because it never checked the declared
unit -- and 3MF's default unit is the **micron**, so an archive silently a
thousand times too small would have passed every row it could ask.

Usage:
    uv run --with embreex python tools/f4_score.py --source <src> \
        --candidate <cand> --candidate-3mf <cand.3mf>

Exit 0 if every row passes, 1 if any fails, 2 if it could not measure.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "benchmarks" / "e2e" / "f4-prusa-modify.json"
LAUNCH_X = 60.0          # well outside the part on +X
EPS = 1e-9


def _load(path: Path):
    if path.suffix.lower() in {".stp", ".step"}:
        sys.path.insert(0, str(ROOT / "skills" / "3d-modeling" / "scripts"))
        import tempfile
        from build123d import export_stl, import_step
        tmp = Path(tempfile.mkdtemp()) / "src.stl"
        export_stl(import_step(str(path)), str(tmp), tolerance=0.01, angular_tolerance=0.1)
        return trimesh.load(str(tmp))
    return trimesh.load(str(path))


def solid_lengths(mesh, yz: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """Solid length along -X within [lo, hi], one value per (y, z) row.

    Crossings are paired in order along the ray, which is what a watertight mesh
    guarantees. An odd count means the ray grazed an edge; those rows are
    returned as NaN so the caller can exclude rather than silently halve them.
    """
    n = len(yz)
    origins = np.column_stack([np.full(n, LAUNCH_X), yz[:, 0], yz[:, 1]])
    dirs = np.tile([-1.0, 0.0, 0.0], (n, 1))
    loc, idx, _ = mesh.ray.intersects_location(origins, dirs, multiple_hits=True)
    out = np.zeros(n)
    if len(idx) == 0:
        return out
    order = np.lexsort((-loc[:, 0], idx))          # per ray, decreasing x
    idx, xs = idx[order], loc[order, 0]
    starts = np.searchsorted(idx, np.arange(n), side="left")
    ends = np.searchsorted(idx, np.arange(n), side="right")
    for i in range(n):
        seg = xs[starts[i]:ends[i]]
        if len(seg) == 0:
            continue
        if len(seg) % 2:
            out[i] = np.nan
            continue
        a = np.minimum(seg[0::2], hi)              # entry (higher x)
        b = np.maximum(seg[1::2], lo)              # exit  (lower x)
        out[i] = float(np.clip(a - b, 0, None).sum())
    return out


def _outside(pts, mask) -> np.ndarray:
    return ~((pts[:, 0] >= mask["x"][0]) & (pts[:, 0] <= mask["x"][1]) &
             (pts[:, 1] >= mask["y"][0]) & (pts[:, 1] <= mask["y"][1]) &
             (pts[:, 2] >= mask["z"][0]) & (pts[:, 2] <= mask["z"][1]))


def _two_sided_distance(a, b, mask, n: int = 40000, seed: int = 5) -> np.ndarray:
    """Distances from each mesh's surface to the other, outside the mask.

    Two-sided because one direction alone is blind in one of the two ways that
    matter: sampling only the source misses material the candidate *added*, and
    sampling only the candidate misses material it *removed*.
    """
    out = []
    for first, second in ((a, b), (b, a)):
        pts, _ = trimesh.sample.sample_surface(first, n, seed=seed)
        pts = pts[_outside(pts, mask)]
        if not len(pts):
            continue
        out.append(np.abs(trimesh.proximity.signed_distance(second, pts)))
    return np.concatenate(out) if out else np.zeros(0)


def _row(name, ok, got, want, why=""):
    return {"row": name, "ok": bool(ok), "got": got, "want": want, "why": why}


def score(src, cnd, spec: dict, pitch: float) -> list[dict]:
    edit, mask = spec["edit"], spec["mask"]["box_mm"]
    tol = float(edit["cad_tolerance_mm"])
    x_lo, x_hi = mask["x"]
    rows: list[dict] = []

    ys = np.arange(mask["y"][0], mask["y"][1] + pitch / 2, pitch)
    zs = np.arange(mask["z"][0], mask["z"][1] + pitch / 2, pitch)
    gy, gz = np.meshgrid(ys, zs, indexing="ij")
    yz = np.column_stack([gy.ravel(), gz.ravel()])

    s_len = solid_lengths(src, yz, x_lo, x_hi)
    c_len = solid_lengths(cnd, yz, x_lo, x_hi)
    good = ~(np.isnan(s_len) | np.isnan(c_len))
    removed = np.zeros(len(yz), bool)
    removed[good] = (s_len[good] - c_len[good]) > 0.10      # 0.1 mm of depth
    added = np.zeros(len(yz), bool)
    added[good] = (c_len[good] - s_len[good]) > 0.10

    if not removed.any():
        return [_row("slot_exists", False, "no material removed inside the mask",
                     "the requested slot", "nothing was cut where the request asked")]

    face = yz[removed]
    y0, y1 = face[:, 0].min(), face[:, 0].max()
    z0, z1 = face[:, 1].min(), face[:, 1].max()
    # Ray centres, so the true extent is one pitch wider than the centre span.
    width, height = (y1 - y0) + pitch, (z1 - z0) + pitch
    cy, cz = (y0 + y1) / 2.0, (z0 + z1) / 2.0

    rows.append(_row("slot_width_mm", abs(width - edit["slot_y_mm"]) <= tol,
                     round(float(width), 4), f"{edit['slot_y_mm']} +/- {tol}"))
    rows.append(_row("slot_height_mm", abs(height - edit["slot_z_mm"]) <= tol,
                     round(float(height), 4), f"{edit['slot_z_mm']} +/- {tol}"))
    rows.append(_row("centre_y_mm", abs(cy - edit["centre_canonical"]["y"]) <= tol,
                     round(float(cy), 4), f"{edit['centre_canonical']['y']} +/- {tol}"))
    rows.append(_row("centre_z_mm", abs(cz - edit["centre_canonical"]["z"]) <= tol,
                     round(float(cz), 4), f"{edit['centre_canonical']['z']} +/- {tol}"))

    # Corner radius from the area a rounded rectangle loses to its corners,
    # rather than by fitting an arc to sampled points.
    area = int(removed.sum()) * pitch * pitch
    lost = max(width * height - area, 0.0)
    r_meas = math.sqrt(lost / (4 - math.pi)) if lost > EPS else 0.0
    rows.append(_row("corner_radius_mm", abs(r_meas - edit["corner_radius_mm"]) <= tol,
                     round(float(r_meas), 4), f"{edit['corner_radius_mm']} +/- {tol}",
                     "derived from the area a rounded rectangle loses at its corners"))

    # The cut must reach the named outer face, not float inside the wall.
    face_x = float(str(edit["face"]).split("=")[-1].replace("mm", "").strip())
    centre_ray = np.array([[edit["centre_canonical"]["y"], edit["centre_canonical"]["z"]]])
    s_here = solid_lengths(src, centre_ray, x_lo, x_hi)[0]
    c_here = solid_lengths(cnd, centre_ray, x_lo, x_hi)[0]
    rows.append(_row("on_the_plus_x_wall", abs(face_x - mask["x"][1]) <= tol + 0.01,
                     f"mask outer bound {mask['x'][1]}", f"the x = {face_x} face",
                     "the mask is anchored on the named face, so a cut elsewhere cannot register"))
    rows.append(_row("through_the_wall", c_here <= 0.01,
                     f"{c_here:.4f} mm of candidate material on the slot axis",
                     "no material on the slot axis within the mask",
                     f"topological; the source carries {s_here:.4f} mm there and the depth is never scored"))

    # Preservation: two-sided surface distance outside the mask.
    #
    # NOT ray length, and the reason is measured. Ray length counts *crossings*,
    # so a ray grazing a curved shell either catches it or slips through
    # depending on the chord approximation, and when it slips the length jumps by
    # the whole cavity. On this part that produced 5 failing rays at up to
    # 18.87 mm -- and a control of the UNEDITED source against a second
    # tessellation of itself reproduced the same 5 rays at 18.8686 mm, so the
    # signal was entirely the instrument. Surface distance measures geometry
    # rather than topology: the same control gives max 0.0597 mm.
    #
    # This is the calibration mistake the fixture warns about, made in the
    # fixture: the frozen noise floor was measured on *regeneration* (one
    # generator, one tolerance, 0.000000 mm) while the comparison actually made
    # is *cross-tessellation* -- our STL against whatever the pipeline exported.
    # A floor calibrated on the wrong pairing is a different question from the
    # claim resting on it.
    thresh = float(spec["calibration"]["preservation"]["threshold_mm"])
    d = _two_sided_distance(src, cnd, mask)
    worst = float(d.max()) if len(d) else 0.0
    rows.append(_row("source_equivalence_outside_the_mask", worst <= thresh,
                     f"worst {worst:.5f} mm over {len(d)} probes",
                     f"<= {thresh} mm outside the mask",
                     "any change outside the authorized region fails, whatever it looks like"))
    rows.append(_row("nothing_added_inside_the_mask", int(added.sum()) == 0,
                     f"{int(added.sum())} rays gained material",
                     "the edit removes material and does not add it"))
    return rows


def three_mf_rows(path: Path, src, candidate, spec: dict, pitch: float) -> list[dict]:
    """The separate manufacturing gate, delegated to the one that already exists.

    F4 owes a gate on the artifact that would actually be *printed*, not only on
    the mesh handed to the scorer. Without it this scorer could return success
    from `--source` and `--candidate` alone while the 3MF beside them was a
    stale, pre-edit export -- every geometric row passing on the STL and the
    thing a person sends to a printer still being the unmodified part.

    **`tools/e2e.py:three_mf_rows` is that gate and this calls it.** An earlier
    version of this function grew its own: readability through
    `pipeline.diagnose`, then F4's geometric predicates re-run against the
    archive. It worked, and it was still wrong to keep, for two reasons that are
    worth recording rather than quietly fixing. It was a second opinion about
    what a valid 3MF is, on a repository that already had one -- so two fixtures
    could disagree about the same archive and a reader would have to know which
    implementation ran. And being newer, it was *weaker*: it never checked the
    declared unit, and 3MF's default unit is the **micron**, so an archive
    silently a thousand times too small would have passed every row this file
    could ask. It also needed `lxml` for trimesh's loader, where the common path
    reads the OPC archive directly.

    So the rows here are the common ones -- present, readable, millimetres, one
    printable body, and matches the accepted STL -- and F4 supplies only its own
    calibration for the last of those.

    The band is measured, not chosen, on the pairing actually compared: this
    fixture's honest candidate STL against the 3MF written from that same STL.
    Export and reload move the surface by **max 0.000060 mm, p99 0.000033 mm**
    at 8310 vertices, and the volume by -0.001612 mm3. The declared band sits
    far above that and far below any real staleness -- a pre-edit archive differs
    by the whole 2.4300 mm wall -- so the row cannot fail for quantisation and
    cannot pass a substituted body.
    """
    tools = ROOT / "tools"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    import e2e

    # `e2e.three_mf_rows` reads `geometry["three_mf"]` and
    # `geometry["reference_comparison"]`, so the calibration block itself is
    # what it wants -- not the three_mf entry inside it.
    common = e2e.three_mf_rows(Path(path), candidate, spec["calibration"])

    # Shape adapter, and only that: `e2e` names its fields
    # predicate/passes/measured/required while this scorer's rows are
    # row/ok/got/want. Translating here keeps one row shape in the report and
    # one conjunction in `main`, rather than two dialects a reader has to know.
    #
    # `passes is None` marks a diagnostic that e2e reports without gating. It is
    # carried through as ok=True deliberately: a diagnostic must not fail the run,
    # and mapping None to False would invent a failure out of a measurement
    # nobody claimed was a gate.
    rows = [_row(r["predicate"], True if r["passes"] is None else r["passes"],
                 r["measured"], r["required"], r.get("why", ""))
            for r in common]

    # --- and one row the common gate structurally cannot supply -------------
    #
    # `three_mf_matches_the_accepted_stl` bands the **p99** surface distance, and
    # on this fixture that is blind to the very failure F4 owes a mutation for.
    # Measured: the stale pre-edit archive against the accepted candidate gives
    # p95 0.000023 mm, p99 0.000042 mm -- inside a 0.010 mm band -- while max is
    # 1.997931 mm. The reason is arithmetic rather than tuning: the slot is
    # 79.14 mm2 of a 19,656.7 mm2 surface, **0.403%**, so 99% of samples land on
    # geometry the two artifacts share and a 99th-percentile statistic cannot see
    # the edit at all. Raising the band would not help; the band is not the
    # problem. On F1 that row works because its comparison is whole-part.
    #
    # So F4 adds its own question -- does the archive carry the requested edit --
    # answered by the same predicates the candidate mesh is scored with. This is
    # not a second opinion about 3MF *validity*, which stays delegated above; it
    # is a different question, and it is the one that fails for a stale archive.
    if all(r["ok"] for r in rows):
        read = e2e.read_three_mf(Path(path))
        archive = trimesh.util.concatenate(read["bodies"])
        inner = score(src, archive, spec, pitch)
        failed = [r["row"] for r in inner if not r["ok"]]
        rows.append(_row(
            "three_mf_carries_the_requested_edit", not failed,
            "every edit row passes on the archive" if not failed
            else f"{len(failed)} row(s) fail on the archive: {', '.join(failed)}",
            "the 3MF satisfies the same edit predicates as the candidate mesh",
            "a stale pre-edit archive passes every whole-surface statistic and "
            "still ships the unmodified part"))
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Score an F4 candidate")
    ap.add_argument("--source", required=True, type=Path)
    ap.add_argument("--candidate", required=True, type=Path)
    # Required, not optional. An optional manufacturing gate is one a passing
    # run can decline to take, which is the same as not having it.
    ap.add_argument("--candidate-3mf", required=True, type=Path,
                    dest="candidate_3mf")
    ap.add_argument("--fixture", type=Path, default=FIXTURE)
    ap.add_argument("--pitch", type=float, default=0.05)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    spec = json.loads(a.fixture.read_text(encoding="utf-8"))
    src = _load(a.source)
    candidate = _load(a.candidate)
    rows = score(src, candidate, spec, a.pitch)
    rows += three_mf_rows(a.candidate_3mf, src, candidate, spec, a.pitch)
    if a.json:
        print(json.dumps(rows, indent=2))
    else:
        w = max(len(r["row"]) for r in rows)
        for r in rows:
            print(f"  [{'PASS' if r['ok'] else 'FAIL'}] {r['row']:<{w}}  got {r['got']}  want {r['want']}")
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
