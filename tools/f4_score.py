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
scorer is not the artifact anybody prints. `--candidate-3mf` is therefore
mandatory rather than optional, and `three_mf_rows` asks two questions of it: is
it a readable 3MF at all, through `pipeline.diagnose` rather than a second
opinion grown here, and does it carry the requested edit, by running these same
predicates against its geometry. Without that gate the scorer could return
success from a source and a candidate STL while the archive beside them was a
stale pre-edit export -- every geometric row green and the printed part
unmodified. That is the case the fixture owes a mutation for.

Reading the archive needs `lxml`, which trimesh's 3MF loader imports and this
project deliberately does not carry. It is supplied per-run with `--with`, the
same way `embreex` is: an isolated accelerator or reader for an answer-side tool
is not a dependency of the skill. The alternative was assembling the archive's
geometry here from `pipeline/diagnose`'s XML helpers, which was rejected -- that
means reimplementing 3MF build-transform resolution, and a gate that silently
mis-reads a transformed archive is precisely the false confidence it exists to
prevent.

Usage:
    uv run --with embreex --with lxml python tools/f4_score.py --source <src> \
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


def _as_single_mesh(loaded):
    """One mesh from whatever `trimesh.load` returned.

    A 3MF is a *scene*: objects, components and build transforms. Concatenating
    it is correct here and only here -- the question this gate asks is whether
    the shipped archive carries the requested edit, which is a question about the
    geometry as placed. `pipeline/diagnose` is what reports the scene structure
    as authored, and it runs first, so nothing about the scene is lost by this
    step; it is asked separately.
    """
    if isinstance(loaded, trimesh.Trimesh):
        return loaded
    dumped = loaded.dump(concatenate=True)
    if isinstance(dumped, trimesh.Trimesh):
        return dumped
    raise ValueError("the 3MF carries no triangles this gate can measure")


def three_mf_rows(path: Path, src, spec: dict, pitch: float) -> list[dict]:
    """The separate manufacturing gate, and why it is not optional.

    F4 owes a gate on the artifact that would actually be *printed*, not only on
    the mesh handed to the scorer. Without it the scorer could return success
    from `--source` and `--candidate` alone while the 3MF beside them was a
    stale, pre-edit export -- every geometric row passing on the STL and the
    thing a person sends to a printer still being the unmodified part. That is
    the failure the fixture explicitly owes a mutation for, and a gate that
    cannot see it is not a gate.

    Two questions, kept apart because they fail for unrelated reasons:

    * is the archive a readable, usable 3MF at all -- asked through
      `pipeline.diagnose`, the pipeline's own common validation path, so this
      tool does not grow a second opinion about what a valid 3MF is;
    * does the archive carry the requested edit -- asked by running the *same*
      geometric predicates against the 3MF's own geometry. Reused rather than
      reimplemented: a stale pre-edit archive fails `slot_exists` for the same
      reason a candidate with no slot does, and a wrong-sized slot fails the same
      dimensional rows. A second implementation of those predicates could
      disagree with the first, and then the gate's verdict would depend on which
      one a reader happened to believe.
    """
    rows: list[dict] = []
    scripts = ROOT / "skills" / "3d-modeling" / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from pipeline.diagnose import diagnose

    report = diagnose(path)
    classification = str(report.get("classification"))
    usable = classification in ("USABLE_EXACT", "USABLE_MESH")
    findings = report.get("findings") or []
    rows.append(_row(
        "candidate_3mf_is_usable", usable,
        f"{classification}" + (f", {len(findings)} finding(s)" if findings else ""),
        "USABLE_EXACT or USABLE_MESH from pipeline.diagnose",
        "the archive that gets printed has to be readable on its own terms"))
    if not usable:
        # Measuring geometry inside an archive the pipeline calls unusable would
        # produce numbers nobody should act on, so the remaining rows are not
        # invented -- their absence is the finding.
        return rows

    inner = score(src, _as_single_mesh(_load(path)), spec, pitch)
    failed = [r["row"] for r in inner if not r["ok"]]
    rows.append(_row(
        "candidate_3mf_carries_the_requested_edit", not failed,
        "every geometric row passes on the archive" if not failed
        else f"{len(failed)} row(s) fail on the archive: {', '.join(failed)}",
        "the 3MF satisfies the same edit predicates as the candidate mesh",
        "a stale pre-edit 3MF passes every STL row and still ships the "
        "unmodified part"))
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
    rows = score(src, _load(a.candidate), spec, a.pitch)
    rows += three_mf_rows(a.candidate_3mf, src, spec, a.pitch)
    if a.json:
        print(json.dumps(rows, indent=2))
    else:
        w = max(len(r["row"]) for r in rows)
        for r in rows:
            print(f"  [{'PASS' if r['ok'] else 'FAIL'}] {r['row']:<{w}}  got {r['got']}  want {r['want']}")
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
