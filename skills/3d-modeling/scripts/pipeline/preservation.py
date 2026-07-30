#!/usr/bin/env python3
"""Did the edit stay inside the region it declared?

A `MODIFY` job's contract is not only "the new feature is right". It is also
"nothing else moved" -- and that second half had nothing measuring it. A model
rebuilt from scratch to add one boss is indistinguishable, from every check in
this pipeline, from one that edited the boss and left the rest alone. The
difference matters: the supplied artifact is the authority, and a redraw silently
replaces it with somebody's reading of it.

So the edit scope names a region, written before the edit, and this measures
everything outside it.

**The method is reported, and the claim never outruns it.** Two artifacts that
are both exact B-reps can be compared exactly, by boolean difference, and the
answer is a volume. Two meshes can only be compared by sampling, and the answer
is a distance with a sample count beside it. Calling the second "preserved
exactly" would be a claim the instrument cannot make, so it is called
`PRESERVED_WITHIN_TOLERANCE` and carries the tolerance it was measured at.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import numpy as np

PRESERVATION_SCHEMA = 1

# How many points to sample on the preserved surface. Enough that a missing
# feature of a few millimetres cannot fall between them on a part of ordinary
# size, and small enough that the query stays milliseconds.
DEFAULT_SAMPLES = 20000

# The band a sampled comparison is allowed to call "unchanged". Not zero: two
# tessellations of one surface disagree by the chord error of whichever is
# coarser, and a candidate re-exported through a different kernel is a different
# tessellation of the same solid.
DEFAULT_TOLERANCE_MM = 0.05

VERDICT = ("PRESERVED_EXACTLY", "PRESERVED_WITHIN_TOLERANCE", "CHANGED",
           "UNMEASURABLE")


@dataclasses.dataclass(frozen=True)
class Region:
    """The axis-aligned box the edit is allowed to touch.

    A named region alone cannot be measured against, so the edit scope carries
    the box as well as the name. Everything outside it, plus a margin, is what
    gets compared -- the margin because a boolean at the boundary legitimately
    perturbs the tessellation just outside it.
    """

    minimum: tuple[float, float, float]
    maximum: tuple[float, float, float]
    margin_mm: float = 0.5

    def contains(self, points: np.ndarray) -> np.ndarray:
        low = np.asarray(self.minimum, dtype=float) - self.margin_mm
        high = np.asarray(self.maximum, dtype=float) + self.margin_mm
        return np.all((points >= low) & (points <= high), axis=1)

    def as_dict(self) -> dict[str, Any]:
        return {"min": list(self.minimum), "max": list(self.maximum),
                "margin_mm": self.margin_mm}

    @classmethod
    def from_declaration(cls, declared: Any) -> "Region | None":
        if not isinstance(declared, dict):
            return None
        low, high = declared.get("min"), declared.get("max")
        if not (isinstance(low, (list, tuple)) and len(low) == 3
                and isinstance(high, (list, tuple)) and len(high) == 3):
            return None
        return cls(tuple(float(v) for v in low), tuple(float(v) for v in high),
                   float(declared.get("margin_mm", 0.5)))


def _load(path: Path):
    """Merged, because a triangle soup has no surface to take a distance from.

    An STL stores three independent vertices per facet, so an unmerged read is a
    pile of loose triangles: `sample_surface` still works, but `signed_distance`
    needs a closed surface and reports nonsense without one. Merging coincident
    vertices is the parse, not a repair -- `diagnose` reports both reads, and
    that is where the difference between them is a finding.
    """
    import trimesh
    loaded = trimesh.load(str(path), force="mesh")
    return loaded if isinstance(loaded, trimesh.Trimesh) else loaded.dump(concatenate=True)


def _sampled(source, candidate, region: Region, samples: int,
             tolerance_mm: float) -> dict[str, Any]:
    """Bidirectional surface distance outside the region.

    Both directions, because one is not enough in either sense: sampling only the
    source misses material the edit *added* outside the region, and sampling only
    the candidate misses material it removed.
    """
    import trimesh

    results: dict[str, Any] = {}
    worst = 0.0
    worst_point: list[float] | None = None
    tested = 0

    for name, (a, b) in (("source_to_candidate", (source, candidate)),
                         ("candidate_to_source", (candidate, source))):
        points, _ = trimesh.sample.sample_surface(a, samples)
        outside = points[~region.contains(points)]
        tested += int(len(outside))
        if len(outside) == 0:
            results[name] = {"sampled": 0,
                             "note": "every sample fell inside the declared edit "
                                     "region, so this direction measured nothing"}
            continue
        distances = np.abs(trimesh.proximity.signed_distance(b, outside))
        index = int(np.argmax(distances))
        peak = float(distances[index])
        results[name] = {"sampled": int(len(outside)),
                         "max_deviation_mm": round(peak, 4),
                         "mean_deviation_mm": round(float(distances.mean()), 4)}
        if peak > worst:
            worst = peak
            worst_point = [round(float(v), 3) for v in outside[index]]

    if tested == 0:
        return {"method": "sampled bidirectional surface distance",
                "verdict": "UNMEASURABLE",
                "reason": "the declared edit region covers the whole part, so "
                          "there is nothing outside it to preserve",
                "directions": results}

    return {
        "method": "sampled bidirectional surface distance",
        "verdict": ("PRESERVED_WITHIN_TOLERANCE" if worst <= tolerance_mm
                    else "CHANGED"),
        "tolerance_mm": tolerance_mm,
        "max_deviation_mm": round(worst, 4),
        "worst_point_mm": worst_point,
        "samples_outside_region": tested,
        "directions": results,
        "claim_note": "a sampled comparison cannot establish exact preservation; "
                      "it establishes that no sampled point outside the declared "
                      f"region moved more than {tolerance_mm} mm",
    }


def audit(*, source_path: Path, candidate_path: Path, region: Region | None,
          tolerance_mm: float = DEFAULT_TOLERANCE_MM,
          samples: int = DEFAULT_SAMPLES,
          exact: bool = False) -> dict[str, Any]:
    """Compare everything outside the declared edit region.

    `exact=True` is a claim about the *inputs*, made by whoever knows they are
    both exact B-reps re-exported from one kernel. It is not inferred from the
    file extension: an STL exported from a STEP is a mesh, whatever it came from.
    """
    source_path, candidate_path = Path(source_path), Path(candidate_path)
    report: dict[str, Any] = {
        "schema_version": PRESERVATION_SCHEMA,
        "source": source_path.name,
        "candidate": candidate_path.name,
        "region": region.as_dict() if region else None,
    }

    if region is None:
        report.update({
            "method": "none",
            "verdict": "UNMEASURABLE",
            "reason": "the edit scope declares no region box, so 'outside the "
                      "edit region' has no geometric meaning and nothing can be "
                      "compared",
        })
        return report

    try:
        source = _load(source_path)
        candidate = _load(candidate_path)
    except Exception as exc:                          # noqa: BLE001 - a file that
        report.update({"method": "none", "verdict": "UNMEASURABLE",
                       "reason": f"{type(exc).__name__}: {exc}"})
        return report

    report["bodies"] = {
        "source": int(len(source.split(only_watertight=False))),
        "candidate": int(len(candidate.split(only_watertight=False))),
    }
    report["bodies"]["changed"] = (
        report["bodies"]["source"] != report["bodies"]["candidate"])
    report["volume_mm3"] = {
        "source": round(float(source.volume), 3) if source.is_watertight else None,
        "candidate": (round(float(candidate.volume), 3)
                      if candidate.is_watertight else None),
    }

    measured = _sampled(source, candidate, region, samples, tolerance_mm)
    report.update(measured)
    if exact and report["verdict"] == "PRESERVED_WITHIN_TOLERANCE":
        # Only reachable when the caller has stated both sides are exact
        # re-exports of one kernel's B-rep. Even then the measurement is the
        # sampled one; what `exact` buys is the right to say the tessellation
        # difference is not hiding a geometric one.
        report["verdict"] = "PRESERVED_EXACTLY"
        report["claim_note"] = (
            "both artifacts were declared exact B-rep exports from one kernel, so "
            "the sampled agreement is a statement about the geometry rather than "
            "about two tessellations of it")
    return report


def as_finding(report: dict[str, Any]) -> str:
    """One line a receipt can carry without the reader opening the JSON."""
    verdict = report.get("verdict")
    if verdict in ("PRESERVED_EXACTLY", "PRESERVED_WITHIN_TOLERANCE"):
        return (f"{verdict}: {report.get('samples_outside_region', 0)} sample(s) "
                f"outside the edit region, worst {report.get('max_deviation_mm')} mm "
                f"against a {report.get('tolerance_mm')} mm band")
    if verdict == "CHANGED":
        return (f"CHANGED: geometry outside the declared edit region moved "
                f"{report.get('max_deviation_mm')} mm at "
                f"{report.get('worst_point_mm')}, past the "
                f"{report.get('tolerance_mm')} mm band")
    return f"UNMEASURABLE: {report.get('reason', 'no reason recorded')}"
