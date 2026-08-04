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

**The sample plan is a function of the pair, not of a random draw.** This audit
used to call `trimesh.sample.sample_surface`, which draws from the process-wide
generator. Two runs of one unchanged pair therefore disagreed: ADR 0002 recorded
`max_deviation_mm` moving 1.13 to 2.00 mm over six runs of one pair, and on the
vent-mount fixture here `samples_outside_region` alone moved between 28,257 and
28,636 over six.

That is not a cosmetic instability. `commission_report.json` carries the audit,
the review packet carries the report, and the review envelope binds the packet:
a reviewer's answer to run *n* could not be checked against run *n+1*, so no
`MODIFY` job with an edit scope could complete a review round trip at all. It
could not be resumed, and it could not be finished.

The plan is now derived from the two artifacts' own hashes, the declared region
and the sample count, and laid out with a pinned SplitMix64 stream over meshes
whose vertex and face order has been made canonical first. Identical inputs
produce byte-identical evidence, and the plan's digest travels with the verdict
so an answer can name the evidence it was written against.

**It was a low-discrepancy sequence, and that was a measured mistake.** See
`_stream`: an independent review reimplemented the planner and counted patches
of the size the derivation undertakes to find that contained no sample at all --
13.10% at the default count and 21.99% at the count the recorded fixture uses,
against the 1% promised. A Kronecker sequence's 2-D projections are striated, and
the planner uses two of those coordinates to place a point inside its triangle,
so the stripes land on the surface. Low discrepancy bounds a box's count against
its volume; finding a defect needs bounded dispersion, which it does not bound.
An independent stream satisfies the Poisson arithmetic the derivation actually
uses, and `SAMPLE_PLAN_VERSION` is 3 because every plan digest moved.

**Determinism is not sensitivity.** Reproducibility is what makes the review
round trip possible; it says nothing about what the plan can find. Sensitivity is
a separate property with a separate mechanism -- `derive_sample_count` from a
declared `minimum_detectable_defect_mm`, measured end to end by
`test_phase3.TheSamplePlanActuallyFindsWhatItPromisesTest` rather than argued
from the arithmetic. Real B-rep comparison is still not implemented. The receipts
say so in the words they use.

**Determinism of the answer is not determinism of completing.** The plan was
reproducible and the run was not: the same unchanged pair took 23 GiB and died on
one attempt in eleven, which means a review round trip could still fail to happen.
So the distance queries run under a declared memory ceiling, and the batch size is
computed from it against the work about to be done -- a refusal with arithmetic in
it rather than a race with the allocator. The ceiling changes the peak and not one
float; it is deliberately outside the plan and the evidence, because a review
answer must not expire when the job is rerun on a smaller machine.

**A STEP is read by the kernel this runtime already has.** `trimesh.load`
dispatches STEP to `cascadio`, which is not installed here, so every audit against
a STEP source used to come back `ModuleNotFoundError`. `mesh_io.read_step` uses
`build123d`, which `diagnose` already uses, so there is one reading of a supplied
B-rep and not two that disagree about its units. The tessellation is at a declared
deflection and is recorded on the report; a B-rep whose faces OCC cannot
triangulate is refused rather than measured with holes in it.
"""
from __future__ import annotations

import dataclasses
import hashlib
import math
from pathlib import Path
from typing import Any

import numpy as np

from . import schemas as S

# 2: the report carries the sample plan that produced it -- the plan's own
# digest, the seeds derived from the artifact pair, and a digest over the whole
# receipt -- so a review answer can be bound to the evidence it read.
PRESERVATION_SCHEMA = 2

# The plan construction itself is versioned, and separately. A change to the
# sequence, the ordering rule or the seed material changes every plan digest and
# invalidates every review bound to one, which is the correct consequence and a
# silent one unless the version is in the seed material.
#
# 2: the seed material gained `alignment_transform` -- where the source artifact
# sits in the job's shared frame. It is the one edit-intent field that says which
# geometry the plan is a plan *of*, and it used to be declared, validated, and
# read by nothing.
SAMPLE_PLAN_VERSION = 3

# How many points to sample on the preserved surface, per direction, when a job
# declares no minimum detectable defect size. Enough that a missing feature of a
# few millimetres cannot fall between them on a part of ordinary size, and small
# enough that the query stays milliseconds.
#
# A job that declares `minimum_detectable_defect_mm` does not use this: its count
# is derived by `derive_sample_count` from the size it undertook to find. This
# constant is the fallback for a job that declared nothing, and a run that used
# it says so on the receipt rather than implying a sensitivity it never claimed.
DEFAULT_SAMPLES = 20000

# The probability that a defect of exactly the declared size is hit by at least
# one sample. Not 1.0, because no finite sample plan can promise that: what a
# density buys is a detection probability, and the honest receipt names it.
#
# 0.99 rather than 0.95 because the consumer is a preservation claim -- a missed
# defect is a part reported unchanged that changed -- and the cost of the
# stricter figure is a 1.5x sample count against a query already measured in
# milliseconds.
DEFAULT_DETECTION_CONFIDENCE = 0.99

# The largest sample plan this audit will build. Beyond it the audit refuses and
# names the size it *could* have found, rather than quietly sampling less finely
# than the job asked for. Release 6's rule: a declared resource bound on every
# query, with a controlled failure instead of an allocation attempt.
#
# 4,000,000 points is about 96 MB of float64 coordinates before any query
# batching, which `_query_batch` then splits against the memory ceiling.
MAX_DERIVED_SAMPLES = 4_000_000


class SampleBudgetExceeded(ValueError):
    """The declared defect size needs more samples than this audit will build.

    Raised rather than clamped. Clamping would answer a question the job did not
    ask -- "is this part preserved to 0.1 mm" answered with a plan that can only
    see 0.4 mm -- and the answer would look identical to one that could.
    """


def derive_sample_count(area_mm2: float, minimum_detectable_defect_mm: float,
                        *, confidence: float = DEFAULT_DETECTION_CONFIDENCE,
                        ceiling: int = MAX_DERIVED_SAMPLES) -> int:
    """How many surface samples it takes to find a defect of that size.

    `_plan_points` is **area-weighted**, so the sample density is uniform over
    the surface: `n / area` points per mm2 everywhere, whatever shape the part
    is and whatever fraction of it a declared region occupies. That is what
    makes this derivation possible at all -- the detectable size is a property
    of the density, not of the region, so it does not have to be recomputed per
    region and cannot be quietly different in the corner of the part nobody
    looked at.

    A defect of characteristic size `d` presents about `d^2` of surface. Treating
    the plan as a Poisson process over the surface, the chance that at least one
    of `n` points lands on a patch of area `a` is `1 - exp(-n * a / A)`, so
    requiring that to reach `confidence` gives

        n >= -ln(1 - confidence) * A / d^2

    That is deliberately the *conservative* reading. The plan is a
    low-discrepancy sequence, which is more evenly spread than a Poisson process
    and therefore hits a small patch at least as often -- so a count derived
    this way finds the declared size at least as reliably as the arithmetic
    promises. Erring the other way would be a sensitivity claim the method
    cannot keep.

    Raises `SampleBudgetExceeded` rather than returning a clamped count: see the
    exception.
    """
    area = float(area_mm2)
    defect = float(minimum_detectable_defect_mm)
    if not (0.0 < confidence < 1.0):
        raise ValueError(f"confidence must be strictly between 0 and 1, "
                         f"got {confidence!r}")
    if not math.isfinite(area) or area <= 0.0:
        raise ValueError(f"a sample plan needs a positive surface area, "
                         f"got {area_mm2!r}")
    if not math.isfinite(defect) or defect <= 0.0:
        raise ValueError(f"minimum_detectable_defect_mm must be positive, "
                         f"got {minimum_detectable_defect_mm!r}")
    needed = math.ceil(-math.log(1.0 - confidence) * area / (defect * defect))
    if needed > ceiling:
        raise SampleBudgetExceeded(
            f"finding a {defect} mm defect on {area:.1f} mm2 of surface at "
            f"{confidence:.0%} confidence needs {needed:,} samples, over this "
            f"audit's ceiling of {ceiling:,}. The smallest defect this ceiling "
            f"can find on this part is "
            f"{detectable_defect_mm(area, ceiling, confidence=confidence):.4f} mm. "
            "Declare that size, or split the region.")
    return max(1, needed)


def detectable_defect_mm(area_mm2: float, samples: int, *,
                         confidence: float = DEFAULT_DETECTION_CONFIDENCE) -> float:
    """The smallest defect a plan of `samples` points can find, inverted.

    The receipt carries this rather than only the count, because a count means
    nothing to a reader without the surface it is spread over: 20,000 points is
    dense on a 20 mm clip and sparse on a build plate.
    """
    area = float(area_mm2)
    if samples <= 0 or not math.isfinite(area) or area <= 0.0:
        return float("inf")
    return math.sqrt(-math.log(1.0 - confidence) * area / float(samples))

# The band a sampled comparison is allowed to call "unchanged". Not zero: two
# tessellations of one surface disagree by the chord error of whichever is
# coarser, and a candidate re-exported through a different kernel is a different
# tessellation of the same solid.
DEFAULT_TOLERANCE_MM = 0.05

VERDICT = ("PRESERVED_EXACTLY", "PRESERVED_WITHIN_TOLERANCE", "CHANGED",
           "UNMEASURABLE")

DIRECTIONS = ("source_to_candidate", "candidate_to_source")

# How much working memory one bidirectional pass may occupy. `ARCHITECTURE.md`
# section 12 requires geometry execution to run under resource limits and fail
# diagnosably; until this constant there was no limit, and the failure mode was
# the allocator's.
#
# Reported from the field on the vent-ball pair: 22.4 GB peak working set,
# 39.74 GB page file, free RAM at 0-1.5 GB throughout, and one invocation in
# eleven dead of `MemoryError: Unable to allocate 1.57 GiB for an array with
# shape (210081703,)`. The same unchanged job produced two different outcomes,
# which is the defect -- determinism of the answer was achieved and determinism
# of *completing* was not.
#
# Re-measured here, unbatched, on the same pair: 23.24 GiB peak working set,
# 91.18 GiB peak page file, and it does not finish -- 334 s in,
# `MemoryError: Unable to allocate 2.47 GiB for an array with shape
# (331606963,)`. Under this ceiling the same audit peaks at 2.16 GiB, pages
# 3.61 GiB, completes in 200 s, and returns the same numbers.
#
# 2 GiB is a working budget, not a guess at the machine's free memory: the point
# of a declared ceiling is that the same job behaves the same way on every
# machine, and a limit derived from whatever happened to be free would reproduce
# exactly the variability this exists to remove.
DEFAULT_MEMORY_CEILING_BYTES = 2 * 1024 ** 3

# Working bytes one (query point, candidate face) pair costs inside
# `trimesh.proximity.signed_distance`. It is not one array: the query holds the
# candidate index list, the tiled query points, the tiled triangles and a dozen
# per-row temporaries inside `closest_point`, and the r-tree's own results are
# Python ints in Python lists before any of that.
#
# Measured, not derived. Peak working set of one query in a fresh process, over
# the vent-ball pair, both directions, at 500 / 2,000 / 5,000 query points:
# 350.3, 350.2, 350.1, 350.2, 350.1 bytes per candidate -- flat to four
# significant figures across a 70x range and across two meshes of very different
# size, which is what a per-row cost looks like.
#
# Declared above the measurement rather than at it. A ceiling computed from an
# optimistic cost is not a ceiling, and the number this multiplies is a worst
# case whose whole job is to be safe.
WORKING_BYTES_PER_CANDIDATE = 384


class MemoryCeilingExceeded(RuntimeError):
    """The work about to be done does not fit the declared ceiling.

    Raised *before* the allocation, from arithmetic over the query size and the
    target's face count, rather than caught from the allocator afterwards. A
    `MemoryError` says the machine ran out; this says the job was too big for the
    limit the job declared, which is a different sentence and a different fix.
    """


class BrepUnreadable(ValueError):
    """A supplied exact B-rep cannot be turned into the mesh this audit needs."""


def _query_batch(target_faces: int, ceiling_bytes: int) -> int:
    """How many query points one distance call may carry, under the ceiling.

    The bound is the worst case rather than the expected one: every face of the
    target is assumed to be a candidate for every point in the batch. That is not
    a pessimistic abstraction -- it is what actually happens. Measured on the
    vent-ball pair, `trimesh.proximity.nearby_faces` returned all 7,056 faces for
    all 20,000 points in one direction and a mean of 16,583 of 19,522 in the
    other, because its query radius is the distance to the nearest *vertex* and a
    point 60 mm from a 20 mm part has a 60 mm bounding box around it.

    Splitting the query is exact, not an approximation: `closest_point` computes
    each point independently -- the candidate lookup, the per-row triangle
    distance and the two-best tie-break are all per query point -- so a batched
    run returns the same float64 values as an unbatched one, bit for bit. What
    changes is the peak, from `points x faces` to `batch x faces`.
    """
    per_point = max(1, int(target_faces)) * WORKING_BYTES_PER_CANDIDATE
    if per_point > ceiling_bytes:
        raise MemoryCeilingExceeded(
            f"one query point against a {target_faces}-face target needs about "
            f"{per_point} working bytes, past the declared ceiling of "
            f"{ceiling_bytes} bytes. Raise the ceiling or simplify the target; "
            f"nothing has been allocated.")
    return max(1, int(ceiling_bytes // per_point))


def _distances(target, points: np.ndarray, ceiling_bytes: int) -> np.ndarray:
    """Unsigned surface distance from each point to `target`, under the ceiling.

    `signed_distance` and not `closest_point` even though the sign is thrown away
    one line later: the magnitude is the same number either way, and keeping the
    call the audit has always made is what makes "byte-identical to today" a fact
    rather than an argument about when `np.sign` returns zero.
    """
    import trimesh

    batch = _query_batch(len(target.faces), ceiling_bytes)
    out = np.empty(len(points), dtype=np.float64)
    for start in range(0, len(points), batch):
        stop = min(start + batch, len(points))
        out[start:stop] = np.abs(
            trimesh.proximity.signed_distance(target, points[start:stop]))
    return out


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


def _load(path: Path) -> tuple[Any, dict[str, Any] | None]:
    """Merged, because a triangle soup has no surface to take a distance from.

    An STL stores three independent vertices per facet, so an unmerged read is a
    pile of loose triangles: `sample_surface` still works, but `signed_distance`
    needs a closed surface and reports nonsense without one. Merging coincident
    vertices is the parse, not a repair -- `diagnose` reports both reads, and
    that is where the difference between them is a finding.

    A STEP is not handed to `trimesh.load`. That path wants `cascadio`, which is
    not in this runtime, so every audit against a STEP source raised
    `ModuleNotFoundError` -- and the repository's only `PHYSICALLY_PROVEN`
    fixture has a STEP primary source, as does most CAD anybody supplies. It goes
    through `mesh_io.read_step` instead, which uses the OCC kernel this runtime
    already carries for diagnosis. See that function for why a second STEP reader
    was not added.

    Returns the mesh and, for a B-rep, the record of how it was read. Reading a
    mesh file is a parse and has nothing to record; reading a B-rep is a
    tessellation at a declared deflection, and a different deflection is a
    different measurement.
    """
    import trimesh

    # Which suffixes are a STEP is `diagnose`'s answer, not a second one here:
    # that module owns format recognition for every supplied artifact, and two
    # spellings of one set is how a file gets diagnosed as a B-rep and read as
    # something else.
    from . import diagnose

    if path.suffix.lower() in diagnose.STEP_SUFFIXES:
        import mesh_io
        reading = mesh_io.read_step(path)
        if not reading.complete:
            # Fail closed rather than measure the part with holes in it. Dropping
            # the faces OCC could not triangulate would leave a mesh that is not
            # closed, so `signed_distance` has no inside to sign against and
            # every sample near a hole reports a distance to geometry that is
            # missing rather than moved.
            raise BrepUnreadable(
                (f"{len(reading.failures)} of {reading.faces} face(s) of "
                 f"{path.name} cannot be tessellated, so there is no surface to "
                 f"measure against: " + "; ".join(reading.failures))
                if reading.failures else
                # No named faces to blame. Naming none and claiming a count
                # would be the false clean one layer up. See `docs/defects.md`
                # D23.
                f"{path.name}: {reading.summary()}")
        return reading.mesh(), reading.as_dict()

    loaded = trimesh.load(str(path), force="mesh")
    mesh = (loaded if isinstance(loaded, trimesh.Trimesh)
            else loaded.dump(concatenate=True))
    if len(mesh.faces) == 0:
        # `trimesh.load` parses a file that is not an STL at all into an empty
        # mesh rather than raising, and an empty mesh reaches the distance query
        # as an r-tree over nothing: `ValueError: Bounds must be (n, dimension *
        # 2)`, raised out of the audit, out of the check, and out of the run as a
        # stage failure with no row and no receipt. A source with no surface is
        # unmeasurable, which is a verdict this file already knows how to write.
        raise ValueError(f"{path.name} parsed to a mesh with no triangles, so "
                         "there is no surface to sample or to measure against")
    return mesh, None


def _ordered(mesh):
    """The same geometry, with vertex and face order made a function of it.

    A seeded plan is only reproducible if the thing it indexes into is. Face
    order decides which face each sample lands on, and nothing guarantees that
    two reads of one file -- through a different loader path, a scene rather than
    a mesh, a concatenation whose order came from a dict -- present the faces in
    the same order. Sorting them here removes the question rather than assuming
    the answer.

    Winding is preserved: each triangle is rolled so its lowest vertex index
    leads, which is a cyclic shift, and `signed_distance` reads winding for its
    sign. This is defined up to exactly coincident vertices, which the merge in
    `_load` is what removes.
    """
    import trimesh
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    if len(vertices) == 0 or len(faces) == 0:
        return mesh

    vertex_order = np.lexsort((vertices[:, 2], vertices[:, 1], vertices[:, 0]))
    rank = np.empty(len(vertex_order), dtype=np.int64)
    rank[vertex_order] = np.arange(len(vertex_order), dtype=np.int64)
    faces = rank[faces]

    roll = np.argmin(faces, axis=1)
    columns = (np.arange(3, dtype=np.int64)[None, :] + roll[:, None]) % 3
    faces = np.take_along_axis(faces, columns, axis=1)
    face_order = np.lexsort((faces[:, 2], faces[:, 1], faces[:, 0]))

    return trimesh.Trimesh(vertices=vertices[vertex_order],
                           faces=faces[face_order], process=False)


def _generalized_golden(dimensions: int) -> float:
    """The root of x**(d+1) = x + 1, by the fixed-point iteration that finds it.

    Sixty-four steps of a contraction on doubles: the same arithmetic on every
    run, and converged long before the last one.
    """
    x = 2.0
    for _ in range(64):
        x = (1.0 + x) ** (1.0 / (dimensions + 1.0))
    return x


_ALPHA = np.array([1.0 / _generalized_golden(3) ** (j + 1) for j in range(3)],
                  dtype=np.float64)


# SplitMix64. Ten lines, pinned here forever, and the reason it is here rather
# than `numpy.random` is the reason the additive-recurrence sequence was here
# before it: a library generator's stream is not something this file should have
# to pin, because a plan that changes when a dependency changes invalidates every
# review bound to it.
#
# **Why the sequence it replaces had to go.** It was an additive recurrence
# (`t_i = frac(offset + i*alpha)`), chosen because low discrepancy sounded
# strictly better than random. It is not, for this question. Discrepancy bounds
# how far a *box's* sample count strays from its volume; what a defect hunt needs
# is bounded *dispersion* -- no empty patch anywhere -- and low discrepancy does
# not bound that. Worse, a Kronecker sequence's 2-D projections are striated, so
# it misses patches thinner than its stripe spacing far more often than area
# alone implies.
#
# Measured, by reimplementing the old planner and counting patches of area d^2
# that contained no sample, at exactly the count `derive_sample_count` returns
# for that d: 13.10% missed at 20,000 samples and 21.99% at 38,014, against the
# 1% the derivation promises. Not a narrow resonance -- it spanned 10^4 to 10^5,
# which is the whole operating band. A uniform draw through the same measurement
# gives 1.06% against 1.00% theory, which is what the Poisson arithmetic in
# `derive_sample_count` assumes and what this now supplies.
#
# So the trade is deliberate and the other way round from the original: an
# equidistributed sequence that breaks the model, for an independent one that
# satisfies it. Reproducibility is unchanged -- same seed, same bytes, forever.
_SPLITMIX_GAMMA = 0x9E3779B97F4A7C15
_SPLITMIX_MASK = (1 << 64) - 1


def _stream(seed: str, count: int) -> np.ndarray:
    """`count` x 3 independent uniforms in [0, 1), deterministic from `seed`.

    Vectorised SplitMix64: the state is `s0 + i*gamma` for i in 0..3n, which is
    a pure function of the index, so the whole block is generated without a loop
    and without carrying state between calls.
    """
    if count <= 0:
        return np.zeros((0, 3), dtype=np.float64)
    start = int.from_bytes(hashlib.sha256(seed.encode("utf-8")).digest()[:8],
                           "big")
    index = np.arange(3 * count, dtype=np.uint64)
    z = (np.uint64(start) + index * np.uint64(_SPLITMIX_GAMMA))
    z = (z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
    z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
    z = z ^ (z >> np.uint64(31))
    # 53 bits is exactly what a float64 mantissa holds, so every value is
    # representable and the map to [0,1) is uniform rather than nearly so.
    return ((z >> np.uint64(11)).astype(np.float64)
            / float(1 << 53)).reshape(count, 3)


def _offsets(seed: str) -> np.ndarray:
    """Three starting phases in [0, 1), read straight out of the seed digest."""
    raw = hashlib.sha256(seed.encode("utf-8")).digest()
    return np.array(
        [int.from_bytes(raw[i * 8:(i + 1) * 8], "big") / float(1 << 64)
         for i in range(3)], dtype=np.float64)


def _plan_points(mesh, count: int, seed: str) -> np.ndarray:
    """`count` surface points, area-weighted, with no random draw anywhere.

    An additive-recurrence (R3) low-discrepancy sequence, phased by the seed:
    `t_i = frac(offset + i * alpha)`, three coordinates at a time. The first
    coordinate indexes the cumulative-area distribution over faces, which is
    what makes the plan area-weighted; the other two become barycentric weights
    through the usual square-root map, which is what makes a point uniform
    inside its triangle.

    Low-discrepancy rather than pseudo-random because the sequence is short,
    auditable and stable across library versions -- a generator's stream is not
    something this file should have to pin.
    """
    areas = np.asarray(mesh.area_faces, dtype=np.float64)
    total = float(areas.sum())
    if count <= 0 or len(areas) == 0 or not np.isfinite(total) or total <= 0.0:
        return np.zeros((0, 3), dtype=np.float64)

    cumulative = np.cumsum(areas) / total
    cumulative[-1] = 1.0

    t = _stream(seed, count)

    faces = np.searchsorted(cumulative, t[:, 0], side="left")
    faces = np.clip(faces, 0, len(areas) - 1)

    triangles = np.asarray(mesh.triangles, dtype=np.float64)[faces]
    root = np.sqrt(t[:, 1])[:, None]
    v = t[:, 2][:, None]
    return (triangles[:, 0] * (1.0 - root)
            + triangles[:, 1] * (root * (1.0 - v))
            + triangles[:, 2] * (root * v))


def _seed_material(*, source_sha256: str, candidate_sha256: str, region: Region,
                   tolerance_mm: float, samples: int,
                   alignment_transform: Any = "identity") -> dict[str, Any]:
    """Everything the plan is a function of, in one hashable structure.

    The two artifact hashes are in it because a plan must be bound to the exact
    pair it compared -- a receipt that reused one pair's plan on another pair
    would be evidence about neither. The region, the band and the count are in
    it because changing any of them is a different measurement, and a
    measurement that quietly kept the old plan would be reporting the old one.

    `alignment_transform` is in it because it says where the source artifact sits
    in the job's shared frame, and a region box is written in that frame: move the
    source and the same box selects different surface, so the same plan would be
    measuring something else under the same digest. It is *bound* here and not yet
    *applied* to the comparison -- applying it would mean asserting that the
    candidate's builder applied the same matrix, which nothing in this build
    checks, and coordinated multi-source preservation is explicitly out of scope
    for the release that made this deterministic. Binding it makes a changed
    transform invalidate the evidence; it does not make the audit frame-aware.

    The other declared edit-intent fields -- `preserve`, `may_remove`, `add`,
    `expected_body_delta`, `preserve_metadata`, `interface_ids` -- are
    deliberately *not* here. They are promises about the edit rather than
    statements about where the geometry is, and none of them changes which points
    get sampled or what they are compared against. They are bound into the
    acceptance contract instead, which
    the review envelope carries as `contract_sha256`, so changing one still
    refuses a stale answer -- without claiming a measurement was rerun that was
    not.
    """
    return {
        "plan_version": SAMPLE_PLAN_VERSION,
        "sequence": "R3 additive recurrence over the cumulative face-area distribution",
        "ordering": "vertices and faces lexicographically ordered before sampling",
        "source_sha256": source_sha256,
        "candidate_sha256": candidate_sha256,
        "region": region.as_dict(),
        "alignment_transform": alignment_transform,
        "tolerance_mm": S.canonical_number(tolerance_mm, 6),
        "samples_per_direction": int(samples),
        "directions": list(DIRECTIONS),
    }


def _direction_seed(material: dict[str, Any], direction: str) -> str:
    """One seed per direction, so the two passes are not the same point set."""
    return S.payload_hash({"plan": material, "direction": direction})


def _sampled(source, candidate, region: Region, samples: int,
             tolerance_mm: float, material: dict[str, Any],
             ceiling_bytes: int) -> dict[str, Any]:
    """Bidirectional surface distance outside the region.

    Both directions, because one is not enough in either sense: sampling only the
    source misses material the edit *added* outside the region, and sampling only
    the candidate misses material it removed.

    Both batch sizes are settled before either direction runs. The refusal this
    audit owes is a refusal to *start*, not one discovered halfway through with
    the first direction's evidence already written -- a job that reports one
    direction and abandons the other is the partial answer this file exists to
    avoid.
    """
    results: dict[str, Any] = {}
    seeds: dict[str, str] = {}
    worst = 0.0
    worst_point: list[float] | None = None
    tested = 0

    # Zipped against `DIRECTIONS` rather than re-spelling the names here: the
    # plan descriptor publishes that tuple, and two spellings of one list is how
    # a receipt ends up describing a measurement nobody ran.
    pairs = tuple(zip(DIRECTIONS, ((source, candidate), (candidate, source))))
    for _, (_, target) in pairs:
        _query_batch(len(target.faces), ceiling_bytes)     # raises before any query

    # The surface the plan is spread over, and therefore what its density means.
    # The source's area rather than the candidate's: the plan is a plan of the
    # geometry that must survive, and on a job that removed material by intent
    # the candidate is smaller for a reason that is not a change in sensitivity.
    sampled_area = float(source.area)
    detectable = detectable_defect_mm(sampled_area, samples)

    for name, (a, b) in pairs:
        seed = _direction_seed(material, name)
        seeds[name] = seed
        points = _plan_points(a, samples, seed)
        outside = points[~region.contains(points)] if len(points) else points
        tested += int(len(outside))
        if len(outside) == 0:
            results[name] = {"sampled": 0,
                             "note": "every planned sample fell inside the declared "
                                     "edit region, so this direction measured nothing"}
            continue
        distances = _distances(b, outside, ceiling_bytes)
        index = int(np.argmax(distances))
        peak = float(distances[index])
        results[name] = {"sampled": int(len(outside)),
                         "max_deviation_mm": S.canonical_number(peak),
                         "mean_deviation_mm": S.canonical_number(float(distances.mean()))}
        if peak > worst:
            worst = peak
            worst_point = [S.canonical_number(float(v), 3) for v in outside[index]]

    plan = {**material, "direction_seeds": seeds}
    plan["sha256"] = S.payload_hash(plan)

    if tested == 0:
        return {"method": "sampled bidirectional surface distance",
                "verdict": "UNMEASURABLE",
                "reason": "the declared edit region covers the whole part, so "
                          "there is nothing outside it to preserve",
                "sample_plan": plan,
                "directions": results}

    return {
        "method": "sampled bidirectional surface distance",
        "verdict": ("PRESERVED_WITHIN_TOLERANCE" if worst <= tolerance_mm
                    else "CHANGED"),
        "tolerance_mm": S.canonical_number(tolerance_mm, 6),
        "max_deviation_mm": S.canonical_number(worst),
        "worst_point_mm": worst_point,
        "samples_outside_region": tested,
        "sample_plan": plan,
        "directions": results,
        # What this plan could have found, as a size rather than as a count. A
        # count means nothing to a reader without the surface it is spread over
        # -- 20,000 points is a 0.49 mm detector on a 20 mm clip and a 7 mm one
        # on a build plate -- and a preservation claim is exactly the place that
        # difference decides whether the claim is worth anything.
        "detectable_defect_mm": S.canonical_number(detectable, 6),
        "detection_confidence": DEFAULT_DETECTION_CONFIDENCE,
        "sampled_area_mm2": S.canonical_number(sampled_area, 4),
        "claim_note": "a sampled comparison cannot establish exact preservation; "
                      "it establishes that no sampled point outside the declared "
                      f"region moved more than {tolerance_mm} mm. The plan is "
                      "derived from this pair of artifacts and carries no random "
                      "draw, so the audit reruns byte-identically. Its density is "
                      f"{samples} points over {sampled_area:.1f} mm2, which finds "
                      f"a defect of {detectable:.4f} mm or larger with "
                      f"{DEFAULT_DETECTION_CONFIDENCE:.0%} confidence; anything "
                      "smaller than that can still be missed, and is missed "
                      "identically on every run.",
    }


def audit(*, source_path: Path, candidate_path: Path, region: Region | None,
          tolerance_mm: float = DEFAULT_TOLERANCE_MM,
          samples: int = DEFAULT_SAMPLES,
          exact: bool = False,
          alignment_transform: Any = "identity",
          memory_ceiling_bytes: int = DEFAULT_MEMORY_CEILING_BYTES) -> dict[str, Any]:
    """Compare everything outside the declared edit region.

    `exact=True` is a claim about the *inputs*, made by whoever knows they are
    both exact B-reps re-exported from one kernel. It is not inferred from the
    file extension: an STL exported from a STEP is a mesh, whatever it came from.

    `alignment_transform` is the edit scope's declaration of where the source sits
    in the job's frame. It binds the plan; it is not applied to the meshes. See
    `_seed_material`.

    `memory_ceiling_bytes` bounds the working set of the distance queries and is
    deliberately **not** part of the plan or the evidence. It changes how the
    measurement is executed and provably not what it measures -- the batched and
    unbatched runs return the same float64 values -- so binding a review answer to
    it would mean a reviewer's answer expiring because the job was rerun on a
    machine with a different budget. What it *does* change is whether the audit
    runs at all, and a refusal is a verdict with its arithmetic in the reason.
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
        return _sealed(report)

    try:
        report["source_sha256"] = S.sha256_file(source_path)
        report["candidate_sha256"] = S.sha256_file(candidate_path)
        source_mesh, source_reading = _load(source_path)
        candidate_mesh, candidate_reading = _load(candidate_path)
        source = _ordered(source_mesh)
        candidate = _ordered(candidate_mesh)
    except Exception as exc:                          # noqa: BLE001 - a file that
        report.update({"method": "none", "verdict": "UNMEASURABLE",
                       "reason": f"{type(exc).__name__}: {exc}"})
        return _sealed(report)

    # Only where a side actually had to be tessellated. A mesh file's read is a
    # parse with nothing to declare, and a key that appeared on every report to
    # say "not applicable" would move every evidence digest ever taken to record
    # that nothing happened.
    tessellation = {name: record for name, record
                    in (("source", source_reading), ("candidate", candidate_reading))
                    if record is not None}
    if tessellation:
        report["tessellation"] = tessellation

    report["bodies"] = {
        "source": int(len(source.split(only_watertight=False))),
        "candidate": int(len(candidate.split(only_watertight=False))),
    }
    report["bodies"]["changed"] = (
        report["bodies"]["source"] != report["bodies"]["candidate"])
    report["volume_mm3"] = {
        "source": (S.canonical_number(float(source.volume), 3)
                   if source.is_watertight else None),
        "candidate": (S.canonical_number(float(candidate.volume), 3)
                      if candidate.is_watertight else None),
    }

    material = _seed_material(
        source_sha256=report["source_sha256"],
        candidate_sha256=report["candidate_sha256"],
        region=region, tolerance_mm=tolerance_mm, samples=samples,
        alignment_transform=alignment_transform)
    try:
        measured = _sampled(source, candidate, region, samples, tolerance_mm,
                            material, memory_ceiling_bytes)
    except MemoryCeilingExceeded as exc:
        # A refusal, not a crash, and it names the arithmetic that produced it.
        # The distinction the receipt has to carry is between "this part changed"
        # and "this instrument declined to run", and only one of those is about
        # the part.
        report.update({"method": "sampled bidirectional surface distance",
                       "verdict": "UNMEASURABLE",
                       "reason": f"{type(exc).__name__}: {exc}"})
        return _sealed(report)
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
            "about two tessellations of it. The comparison is still the sampled "
            "one, run to a deterministic plan derived from this pair.")
    return _sealed(report)


def _sealed(report: dict[str, Any]) -> dict[str, Any]:
    """The report's own digest, over everything else in it.

    What binds a review answer to the evidence it was written against. Computed
    last and over the canonical text, so key order cannot move it and the field
    cannot be part of what it covers.
    """
    report["evidence_sha256"] = S.payload_hash(
        {k: v for k, v in report.items() if k != "evidence_sha256"})
    return report


def as_finding(report: dict[str, Any]) -> str:
    """One line a receipt can carry without the reader opening the JSON."""
    verdict = report.get("verdict")
    plan = (report.get("sample_plan") or {}).get("sha256")
    against = f", plan {plan[:12]}" if isinstance(plan, str) else ""
    if verdict in ("PRESERVED_EXACTLY", "PRESERVED_WITHIN_TOLERANCE"):
        return (f"{verdict}: {report.get('samples_outside_region', 0)} sample(s) "
                f"outside the edit region, worst {report.get('max_deviation_mm')} mm "
                f"against a {report.get('tolerance_mm')} mm band{against}")
    if verdict == "CHANGED":
        return (f"CHANGED: geometry outside the declared edit region moved "
                f"{report.get('max_deviation_mm')} mm at "
                f"{report.get('worst_point_mm')}, past the "
                f"{report.get('tolerance_mm')} mm band{against}")
    return f"UNMEASURABLE: {report.get('reason', 'no reason recorded')}"
