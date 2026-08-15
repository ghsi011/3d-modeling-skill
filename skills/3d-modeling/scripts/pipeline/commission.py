#!/usr/bin/env python3
"""Measure the exported solid against the contract, and fail closed.

Every check names the contract feature it answers, so coverage is countable
rather than asserted: a feature with no check that ran is not covered, whatever
the other checks said. That is the shape of the failure this replaces -- a
candidate shipped 31% too thick while three checks reported SKIPPED, nothing
counted them, and the gate exited zero.

A check that cannot run does not decide its own consequence. The contract said,
in advance, whether that feature's silence is an `ESCALATE` or a `FAIL`.
"""
from __future__ import annotations

import dataclasses
import math
from pathlib import Path
from typing import Any

from . import schemas as S
from .analysis import MeasurementFailed, MeshAnalysisContext
from .contract import Contract, Feature

# Which check answers which declared kind. The preflight validates a feature's
# `verified_by` against these names, so a contract cannot name a check that does
# not exist and then read its absence as silence.
KNOWN_CHECKS = frozenset({
    "section_area", "bed_contact", "through_hole", "bore_by_displacement",
    "void_region", "envelope", "watertight", "bodies", "unit_scale", "seated",
    "fit_acceptance", "overhang", "preservation", "counterpart_fit",
})


@dataclasses.dataclass
class Check:
    check_id: str
    feature_id: str | None
    title: str
    ran: bool
    reason: str
    expected: Any
    measured: Any
    tolerance: Any
    result: str
    status: str = "MEASURED"
    error_code: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if not self.ran and self.measured is None and self.status == "MEASURED":
            self.status = "UNAVAILABLE"
        S.require_enum(self.status, S.MEASUREMENT_STATUS, what="check.status")

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def _tol(tolerance: dict[str, Any], expected: float) -> float:
    if "abs" in tolerance:
        return float(tolerance["abs"])
    if "frac" in tolerance:
        return abs(float(tolerance["frac"]) * float(expected))
    band = tolerance.get("band")
    if band:
        return abs(float(band[1]) - float(band[0])) / 2.0
    raise ValueError("tolerance declares no abs, frac or band")


def _verdict(feature: Feature, ok: bool, ran: bool) -> str:
    if not ran:
        return "ESCALATE" if feature.on_unrunnable == "ESCALATE" else "FAIL"
    return "PASS" if ok else "FAIL"


def _unavailable_check(feature: Feature, title: str, reason: str, code: str,
                       expected: Any, tolerance: Any) -> Check:
    return Check(
        check_id=f"feature-{feature.feature_id}", feature_id=feature.feature_id,
        title=title, ran=False, reason=reason, expected=expected, measured=None,
        tolerance=tolerance, result=_verdict(feature, False, False),
        status="UNAVAILABLE", error_code=code, error_message=reason)


class SampleAreaUnreadable(ValueError):
    """The declared sensitivity cannot be turned into a plan on this source.

    Distinct from `SampleBudgetExceeded`: that one means the job asked for more
    than this audit will build, this one means the surface the count would be
    derived from could not be read at all. Both become UNAVAILABLE checks, and
    both name which.
    """


def _preservation_samples(expectation: dict[str, Any], source_path: Path) -> int:
    """How many points this row's plan gets, and where the number came from.

    A declared `minimum_detectable_defect_mm` derives the count from the source's
    own surface area, so the plan is as fine as the job asked for on the part the
    job actually has. Without one the fixed fallback stands -- unchanged, so a
    contract written before this field existed plans exactly the points it always
    did.

    An explicit `samples` on the row wins over the fallback, because a contract
    that names its own count must not have it recomputed under a receipt that
    already published it. It does **not** win over a declared defect size: a row
    carrying both used to return the count and drop the declaration on the floor,
    with no finding and no receipt key, so a job could ask for 0.3 mm, be given a
    0.8 mm plan, and read PRESERVED with nothing anywhere saying it had not got
    what it asked for.

    Found by review, along with the fact that the justification originally given
    here -- "the frozen fixtures set one" -- was not true: no committed JSON in
    this repository sets `samples`. A rule defended by a fact that is false is a
    rule nobody can check.
    """
    declared = expectation.get("minimum_detectable_defect_mm")
    if "samples" in expectation and declared is None:
        return int(expectation["samples"])
    if "samples" in expectation:
        raise SampleAreaUnreadable(
            f"this contract row names both an explicit sample count "
            f"({expectation['samples']}) and a minimum detectable defect size "
            f"of {declared} mm. They are two different instructions about the "
            "same plan and this audit will not silently honour one: drop the "
            "count and let the size derive it, or drop the size.")
    from . import preservation as PR          # noqa: PLC0415 - kernel is lazy
    if declared is None:
        return PR.DEFAULT_SAMPLES
    from . import analysis                      # noqa: PLC0415
    # The *normalized* mesh, which is the one the plan is laid out over --
    # `preservation._ordered` canonicalizes the same geometry, and measuring the
    # density against the raw parse would describe a surface the plan never saw.
    #
    # `analysis.load` refuses a STEP: `trimesh.load` dispatches those to
    # `cascadio`, which is not in this runtime, so it raises. `PR.audit` handles
    # the same source fine -- it routes STEP through `mesh_io.read_step` -- which
    # made this the sharpest possible failure: *declaring* a sensitivity turned a
    # working audit into an uncaught stage crash, on the one source class the
    # module was extended to support. Found by review.
    #
    # `SampleAreaUnreadable` rather than a bare raise, so the caller can turn it
    # into an UNAVAILABLE check like every other measurement this file cannot
    # take. A declaration must never be the thing that breaks a job.
    try:
        area = float(analysis.load(Path(source_path)).normalized.area)
    except Exception as exc:                     # noqa: BLE001 - any read failure
        raise SampleAreaUnreadable(
            f"a minimum detectable defect size of {declared} mm was declared, "
            f"and the surface area of {Path(source_path).name} could not be "
            f"read to derive a sample count from it: "
            f"{type(exc).__name__}: {exc}") from exc
    return PR.derive_sample_count(area, float(declared))


def _feature_check(ctx: MeshAnalysisContext, feature: Feature,
                   bed_contact_mm2: float | None,
                   source_dir: Path | None = None,
                   contract: Contract | None = None) -> Check:
    exp = feature.expectation
    kind = feature.kind

    if kind == "section_area":
        z = float(exp["at"]["z"])
        want = float(exp["value_mm2"])
        tol = _tol(feature.tolerance, want)
        try:
            got = ctx.section_area(z)
        except MeasurementFailed as exc:
            return _unavailable_check(
                feature, f"Section area at z={z:.2f}", str(exc), exc.code, want, tol)
        measured: Any = round(got, 3)
        probe = exp.get("fit_probe")
        if isinstance(probe, dict):
            at = probe.get("at")
            z_probe = probe.get("z")
            fit_value = None
            if (isinstance(at, dict) and isinstance(z_probe, (int, float))
                    and not isinstance(z_probe, bool)
                    and isinstance(at.get("x"), (int, float))
                    and isinstance(at.get("y"), (int, float))):
                try:
                    fit_value = round(ctx.section_bore_diameter_mm(
                        z=float(z_probe), at=(float(at["x"]), float(at["y"]))), 4)
                except MeasurementFailed:
                    fit_value = None
            measured = {"area_mm2": round(got, 3), "fit_value_mm": fit_value}
        return Check(f"feature-{feature.feature_id}", feature.feature_id,
                     f"Section area at z={z:.2f}", True, "measured", want, measured, tol,
                     _verdict(feature, abs(got - want) <= tol, True))

    if kind == "bed_contact":
        want = float(exp["value_mm2"])
        tol = _tol(feature.tolerance, want)
        if bed_contact_mm2 is None:
            return _unavailable_check(
                feature, "Bed contact area",
                "no placement was computed, so there is no contact area",
                "NO_PLACEMENT", want, tol)
        return Check(f"feature-{feature.feature_id}", feature.feature_id,
                     "Bed contact area", True, "measured", want, round(bed_contact_mm2, 3), tol,
                     _verdict(feature, abs(bed_contact_mm2 - want) <= tol, True))

    if kind == "through_hole":
        from designer_toolkit import features as F
        at, want = exp["at"], float(exp["d_mm"])
        z0, z1 = float(exp["z_from"]), float(exp["z_to"])
        tol = _tol(feature.tolerance, want)
        radius = want * 0.7
        worst, detail = 0.0, []
        for frac in (0.2, 0.5, 0.8):
            z = z0 + frac * (z1 - z0)
            try:
                got = F.bore_diameter_mm(ctx.normalized, float(at["x"]), float(at["y"]), z, radius)
            except F.Indeterminate as exc:
                return _unavailable_check(
                    feature, f"Bore {want:.2f} mm", str(exc),
                    "BORE_INDETERMINATE", want, tol)
            except Exception as exc:
                # This instrument is the one feature check that does not go
                # through `analysis._intersect`, so an engine refusal here used
                # to escape commission.run entirely -- no report, no verdict.
                # An absent engine answer is not a measured zero: it is an
                # UNAVAILABLE observation, exactly like every other check's.
                return _unavailable_check(
                    feature, f"Bore {want:.2f} mm",
                    f"the boolean engine could not measure the bore at z={z:.2f}: "
                    f"{exc}. An absent engine answer is not an empty bore.",
                    "BOOLEAN_ENGINE_REFUSED", want, tol)
            detail.append(round(got, 3))
            worst = max(worst, abs(got - want))
        return Check(f"feature-{feature.feature_id}", feature.feature_id,
                     f"Bore {want:.2f} mm", True, "three stations along the axis",
                     want, detail, tol, _verdict(feature, worst <= tol, True))

    if kind == "bore_by_displacement":
        # A large bore in a thin wall cannot be measured by the two-radius
        # cross-check: that needs r and 0.8r both buried in material, and a
        # 56 mm bore behind a 2 mm wall leaves no radius where both are. The
        # check correctly refused rather than reporting a number computed
        # mostly from fresh air -- so this measures the same bore a different
        # way, by how much material is missing from a disc of known size.
        at, want = exp["at"], float(exp["d_mm"])
        outer_d, z = float(exp["enclosing_d_mm"]), float(exp["z"])
        tol = _tol(feature.tolerance, want)
        outer_area = math.pi / 4.0 * outer_d * outer_d
        try:
            material = ctx.disc_area(z=z, at=(float(at["x"]), float(at["y"])), diameter=outer_d)
        except MeasurementFailed as exc:
            return _unavailable_check(
                feature, f"Bore {want:.2f} mm", str(exc), exc.code, want, tol)
        void = outer_area - material
        if void <= 0.0:
            return _unavailable_check(
                feature, f"Bore {want:.2f} mm",
                "the enclosing disc is entirely solid, so no bore is present to "
                "measure at this height",
                "BORE_NOT_PRESENT", want, tol)
        got = 2.0 * math.sqrt(void / math.pi)
        return Check(f"feature-{feature.feature_id}", feature.feature_id,
                     f"Bore {want:.2f} mm", True,
                     f"material missing from a {outer_d:.2f} mm disc at z={z:.2f}",
                     want, round(got, 3), tol, _verdict(feature, abs(got - want) <= tol, True))

    if kind == "void_region":
        at, size, z = exp["at"], exp["size_mm"], float(exp["z"])
        allowed = float(exp.get("max_area_mm2", 0.0))
        tol = _tol(feature.tolerance, allowed or 1.0)
        lo, hi = ctx.bounds[0], ctx.bounds[1]
        half_x, half_y = float(size[0]) / 2.0, float(size[1]) / 2.0
        cx, cy = float(at["x"]), float(at["y"])
        if (cx - half_x < lo[0] - 0.02 or cx + half_x > hi[0] + 0.02
                or cy - half_y < lo[1] - 0.02 or cy + half_y > hi[1] + 0.02):
            return _unavailable_check(
                feature, "Void region",
                "the window reaches outside the part's own footprint, so an "
                "empty reading would be fresh air rather than a clear cavity",
                "WINDOW_OUTSIDE_FOOTPRINT", allowed, tol)
        try:
            got = ctx.window_area(z=z, at=(cx, cy), size=(float(size[0]), float(size[1])))
        except MeasurementFailed as exc:
            return _unavailable_check(
                feature, "Void region", str(exc), exc.code, allowed, tol)
        return Check(f"feature-{feature.feature_id}", feature.feature_id,
                     "Void region", True, "material inside a declared-empty window",
                     allowed, round(got, 3), tol,
                     _verdict(feature, got - allowed <= tol, True))

    if kind == "overhang":
        # The one plan rule that decides whether a novel part prints at all, and
        # the one four archived runs set *after* reading their own measurement.
        # It arrives here as a contract feature generated from a print plan that
        # was written before the geometry existed, so the threshold cannot have
        # been tuned to the candidate.
        #
        # `designer_toolkit.metrics.overhang_area` is the implementation, not a
        # second one: the downward-normal threshold, the bed band and the reason
        # the screen sits at -0.73 rather than the bare 45-degree value all live
        # there, and re-deriving them here would be two answers to one question.
        from designer_toolkit import metrics as M
        allowed = float(exp.get("max_area_mm2", 0.0))
        tol = _tol(feature.tolerance, allowed or 1.0)
        threshold = float(exp.get("downward_normal_z_max",
                                  M.DEFAULT_DOWNWARD_NORMAL_Z_MAX))
        bed_z = float(exp.get("bed_z_mm", M.DEFAULT_BED_Z_MM))
        # In the frame the part prints in. `overhang_area` documents this
        # parameter for exactly that -- "Pass the model-to-printer `transform`
        # to screen in print orientation" -- and this call omitted it while
        # `cli` copies the plan rule's threshold and bed height and drops its
        # matrix. On a cone: 0.0 mm2 authored, 1294 mm2 in the declared frame.
        from .contract import printer_transform

        transform = None if contract is None else printer_transform(contract)
        # No `contract is not None` conjunct. With it, a caller that omitted the
        # argument skipped the refusal *and* measured the authored frame: on the
        # cone fixture, PASS at 0.0 mm2 against FAIL at 1293 mm2, with a reason
        # naming no frame. That is D15 verbatim, reachable by forgetting an
        # optional argument -- the fallback this slice claims to have removed,
        # kept as a default.
        if transform is None:
            return _unavailable_check(
                feature, "Unsupported downward-facing area",
                "orientation.model_to_printer_matrix cannot be applied, so the "
                "print orientation this area would be measured in is unknown",
                "ORIENTATION_UNUSABLE", allowed, tol)
        try:
            got = M.overhang_area(ctx.normalized, threshold=threshold,
                                  bed_z=bed_z, transform=transform)
        except Exception as exc:                      # noqa: BLE001 - a measurement
            return _unavailable_check(                # that cannot run is a finding
                feature, "Unsupported downward-facing area",
                f"{type(exc).__name__}: {exc}", "OVERHANG_UNMEASURABLE", allowed, tol)
        return Check(f"feature-{feature.feature_id}", feature.feature_id,
                     "Unsupported downward-facing area", True,
                     f"faces with normal_z <= {threshold:g}, above the bed band",
                     allowed, round(float(got), 3), tol,
                     _verdict(feature, float(got) - allowed <= tol, True))

    if kind == "preservation":
        # The half of a MODIFY contract that had nothing measuring it: not "the
        # new feature is right" but "nothing else moved". A model rebuilt from
        # scratch to add one boss passes every other check in this file.
        from . import preservation as PR
        region = PR.Region.from_declaration(exp.get("region"))
        tolerance_mm = float(exp.get("tolerance_mm", PR.DEFAULT_TOLERANCE_MM))
        tol = _tol(feature.tolerance, tolerance_mm)
        # The source artifact is a *project* input, and since branching the
        # candidate is not written beside the project any more -- it is written
        # under `alternatives/<id>`. Looking beside the candidate is the right
        # default for every caller that has no separate root (`run-job`, the
        # frozen fixtures), and wrong for a branch, where it would report
        # `SOURCE_MISSING` for a file that is exactly where it was declared.
        root = Path(source_dir) if source_dir is not None else ctx.path.parent
        source = root / str(exp.get("source", ""))
        if not source.is_file():
            return _unavailable_check(
                feature, "Preservation outside the edit region",
                f"the declared source artifact {exp.get('source')!r} is not in "
                f"{root}, so there is nothing to compare against",
                "SOURCE_MISSING", tolerance_mm, tol)
        # Derived where the job declared a size, fixed where it did not, and the
        # receipt says which. `SampleBudgetExceeded` becomes an unavailable
        # check rather than an exception: a job that asked for a sensitivity
        # this audit cannot reach has made a declaration it cannot keep, and
        # that is a finding about the job, not a crash.
        try:
            planned = _preservation_samples(exp, source)
        except PR.SampleBudgetExceeded as exc:
            return _unavailable_check(
                feature, "Preservation outside the edit region", str(exc),
                "PRESERVATION_DENSITY_UNREACHABLE", tolerance_mm, tol)
        except SampleAreaUnreadable as exc:
            return _unavailable_check(
                feature, "Preservation outside the edit region", str(exc),
                "PRESERVATION_SOURCE_UNREADABLE", tolerance_mm, tol)
        report = PR.audit(source_path=source, candidate_path=ctx.path,
                          region=region, tolerance_mm=tolerance_mm,
                          samples=planned,
                          exact=bool(exp.get("exact", False)),
                          # Where the edit scope declared this source sits in the
                          # job's frame. Read off the frozen contract row rather
                          # than off `project.json`, so what the plan is bound to
                          # is what the acceptance revision froze -- and a
                          # contract written before this field was carried simply
                          # has no key here and gets the identity it declared by
                          # omission.
                          alignment_transform=exp.get("alignment_transform",
                                                      "identity"))
        if report["verdict"] == "UNMEASURABLE":
            return _unavailable_check(
                feature, "Preservation outside the edit region",
                report.get("reason", "the comparison could not run"),
                "PRESERVATION_UNMEASURABLE", tolerance_mm, tol)
        preserved = report["verdict"] in ("PRESERVED_EXACTLY",
                                          "PRESERVED_WITHIN_TOLERANCE")
        return Check(f"feature-{feature.feature_id}", feature.feature_id,
                     "Preservation outside the edit region", True,
                     PR.as_finding(report), tolerance_mm,
                     {"verdict": report["verdict"],
                      "max_deviation_mm": report.get("max_deviation_mm"),
                      "samples_outside_region": report.get("samples_outside_region"),
                      "method": report.get("method"),
                      # Beside `method` because it is a property of the method
                      # and not of the part: the smallest defect this plan's
                      # density could have found. A verdict of PRESERVED means
                      # nothing without it -- 38,014 samples is a fine detector
                      # on a 17 mm ball and a coarse one on a build plate, and
                      # a reviewer reading only the verdict cannot tell which
                      # they were handed.
                      "detectable_defect_mm": report.get("detectable_defect_mm"),
                      # The plan that produced this number and the digest of the
                      # whole audit. Both travel onto the receipt so a review
                      # answer can be checked against the evidence it read
                      # rather than against a verdict that happens to agree --
                      # see `run` below, which lifts them into the report, and
                      # `review.build_envelope`, which binds them.
                      "sample_plan_sha256": (
                          report.get("sample_plan") or {}).get("sha256"),
                      "evidence_sha256": report.get("evidence_sha256"),
                      "bodies": report.get("bodies")},
                     tol, _verdict(feature, preserved, True))

    if kind == "counterpart_fit":
        return _counterpart_fit_check(ctx, feature, source_dir)

    return _unavailable_check(
        feature, f"Feature kind {kind!r}",
        f"no check implements kind {kind!r}",
        "UNKNOWN_CHECK_KIND", None, None)


class _CannotAssemble(RuntimeError):
    """The declared bodies could not be put where the contract says they go."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def _assemble(ctx: MeshAnalysisContext, bodies) -> MeshAnalysisContext:
    """Put the exported solids into the pose the contract froze for them.

    **Why this exists.** The halves of a split part export in their *printed*
    pose -- side by side and, for a clamp, one of them flipped -- because that is
    how they go on a bed. Measured on the real commission: each half of the
    bearing clamp retains 24.38 mm3 of the 48.16 mm3 interference ring, and a
    single zone over the file as exported sees 24.38, because the cap sits 13 mm
    away in Y and outside a zone 7 mm wide. So a threshold set for a whole ring
    fails a correct part and one set for a half passes a part with no cap at all.
    Neither is a trustworthy verdict, and the repair is to assemble first.

    **How a body is named.** By a point the contract puts inside it, and exactly
    one solid may contain that point. Not by split order, which is an artefact of
    the mesh library and changes with the geometry; and not by anything the
    candidate says about itself, which would let the part choose which transform
    it receives. Ambiguity is refused rather than resolved: two solids around one
    locator means the contract cannot say which it meant.

    The transform is read through `contract.as_transform`, which is the same
    predicate `orientation.model_to_printer_matrix` and `alignment_transform` go
    through -- translation and a proper rotation, no reflection and no scale.
    Reused rather than reimplemented: a second reading of "may a mesh be moved by
    this" is a second authority over it.
    """
    from . import contract as CT

    import trimesh

    components = ctx.components
    posed = []
    claimed: dict[int, int] = {}
    for index, row in enumerate(bodies):
        locator = [float(v) for v in row["locator_mm"]]
        # `contains` is a ray test and answers nothing on an open surface, so a
        # component the locator's box reaches into but which is not a closed
        # solid stops the row rather than being guessed at.
        for candidate in (c for c in components if _in_box(c, locator)):
            if not candidate.is_watertight:
                raise _CannotAssemble(
                    f"bodies[{index}] reaches an exported solid that is not "
                    "closed, so whether the locator is inside it cannot be "
                    "decided by a ray test.",
                    code="BODY_NOT_A_SOLID")
        holding = [i for i, c in enumerate(components) if _holds(c, locator)]
        if not holding:
            raise _CannotAssemble(
                f"bodies[{index}] is named by the point {locator}, and no exported "
                "solid has material there. Either the part is not the one the "
                "contract was frozen against, a half is missing, or the point was "
                "put in a void -- the bore's own axis is inside the box of the "
                "half around it and inside none of its material.",
                code="BODY_LOCATOR_UNMATCHED")
        if len(holding) > 1:
            raise _CannotAssemble(
                f"bodies[{index}] is named by the point {locator}, which lies "
                f"inside {len(holding)} exported solids. A locator that names more "
                "than one body names none of them.",
                code="BODY_LOCATOR_AMBIGUOUS")
        # One row, one solid, and no solid twice. Without this a candidate that
        # lost a half can have both locators land in the survivor, which is then
        # copied under two transforms into an assembly that looks complete while
        # a real exported solid is never read. The rows would each be
        # unambiguous; it is the *pairing* that is not.
        if holding[0] in claimed:
            raise _CannotAssemble(
                f"bodies[{index}] selects the same exported solid as "
                f"bodies[{claimed[holding[0]]}]. Each row must name a different "
                "one, or a part could be assembled twice out of one half.",
                code="BODY_LOCATOR_NOT_DISTINCT")
        claimed[holding[0]] = index
        matrix = CT.as_transform(row.get("transform"))
        if matrix is None:
            raise _CannotAssemble(
                f"bodies[{index}] declares a transform that is not a finite rigid "
                "one, so the solid may not be moved by it.",
                code="BODY_TRANSFORM_UNUSABLE")
        moved = components[holding[0]].copy()
        moved.apply_transform(matrix)
        posed.append(moved)

    assembled = posed[0]
    for other in posed[1:]:
        # Union rather than concatenation: two halves that interpenetrate would
        # have their shared material counted twice by a concatenated mesh, and
        # that is the direction that reports a grip nobody has.
        assembled = trimesh.boolean.union([assembled, other], engine="manifold")
    return MeshAnalysisContext(path=ctx.path, raw=assembled, normalized=assembled,
                               load_count=0, repair_actions=())


def _in_box(mesh, point) -> bool:
    """Cheap rejection only. Never an answer on its own -- see `_holds`."""
    low, high = mesh.bounds
    return all(float(low[i]) <= point[i] <= float(high[i]) for i in range(3))


def _holds(mesh, point) -> bool:
    """Is the point inside this solid's **material**?

    The bounding box is a prefilter and nothing more. The first version of this
    stopped at the box and called it identity, with a comment arguing that a ray
    test was the expensive way to answer a question a careful contract could
    avoid asking badly. Review found the hole in that: a box is not a solid, and
    the gap between them is exactly where a wrong assembly hides. The axis of
    this clamp's own bore lies inside the body's box and in no material at all,
    so a locator put on the bearing axis -- the most natural point anyone would
    reach for -- named a solid it is not inside.

    Worse, the box of one half can cover a point meant for another. A candidate
    missing a half then has both locators land in the surviving one, and it is
    copied under two transforms into a complete-looking assembly while a real
    exported solid is ignored. Nothing in the old check could see that.

    `contains` is a ray test and it is only meaningful on a closed solid, so an
    open component is refused by the caller rather than guessed at.
    """
    if not _in_box(mesh, point):
        return False
    return bool(mesh.contains([point])[0])


def _counterpart_fit_check(ctx: MeshAnalysisContext, feature: Feature,
                           source_dir: Path | None) -> Check:
    """Does the candidate hold the thing it is for, without seizing it?

    **The blind spot this closes.** A real discovery commission passed 19 of 19
    checks on a split clamp for a 608 bearing. Every one of those checks was a
    property of the candidate alone -- bodies, watertight, seated, envelope, four
    section areas, six hole diameters, two void regions, support area, unit
    scale. The counterpart was never loaded, there was no assembly pose, and so
    nothing anywhere asked whether the bearing fits. A clamp that grips the
    *inner* race -- which stops the bearing turning, the one thing its brief
    forbids -- passes all nineteen.

    So this check asks the two questions the others structurally cannot, and it
    asks them of the part **assembled** -- each declared body moved into place by
    a transform the contract froze, because the halves export flat on a bed and
    that is not where the bearing goes (`_assemble` has the measured numbers):

    * **retained**: candidate material inside the annular band around the outer
      race. Zero means the clamp does not grip the bearing at all.
    * **intruded**: candidate material inside the cylinder the inner race and
      shaft turn in. Anything above the declared allowance means the clamp
      seizes the bearing.

    Both zones are frozen into the contract from the counterpart and the pose
    before any candidate exists, and `counterpart_fit` is in no `PROPOSABLE`
    whitelist, so neither a designer nor a candidate can move the question.

    **What this deliberately does not do.** It does not fit a circle to the seat
    and compare the diameter. That measurement was tried on the real commission
    and carried 0.26-0.37 mm of spread against an 0.03 mm interference -- an
    instrument that cannot resolve the thing it is measuring. A volume in a
    region has no such problem: the zones are known exactly because they are
    constructed, not measured.
    """
    exp = feature.expectation
    title = "Bearing fit at the assembled interface"
    ceiling = float(exp.get("max_intrusion_mm3", 0.0))
    tol = _tol(feature.tolerance, ceiling)

    root = Path(source_dir) if source_dir is not None else ctx.path.parent
    counterpart = root / str(exp.get("counterpart", ""))
    if not counterpart.is_file():
        return _unavailable_check(
            feature, title,
            f"the declared mating object {exp.get('counterpart')!r} is not in "
            f"{root}, so the part it has to fit was never loaded",
            "COUNTERPART_MISSING", exp, tol)
    digest = S.sha256_file(counterpart)
    if digest != str(exp.get("counterpart_sha256")):
        return _unavailable_check(
            feature, title,
            f"the mating object on disk hashes {digest}, and the contract was "
            f"frozen against {exp.get('counterpart_sha256')}. A fit measured "
            "against different bytes than the ones the zones came from is a fit "
            "against a different object.",
            "COUNTERPART_CHANGED", exp, tol)

    try:
        assembled = _assemble(ctx, exp.get("bodies") or ())
    except _CannotAssemble as exc:
        return _unavailable_check(feature, title, str(exc), exc.code, exp, tol)

    pose = exp.get("pose") or {}
    centre = tuple(float(v) for v in pose.get("centre_mm", (0.0, 0.0, 0.0)))
    axis = tuple(float(v) for v in pose.get("axis", (0.0, 0.0, 1.0)))
    try:
        retained = assembled.annulus_volume(
            centre=centre, axis=axis,
            r_mm=(float(exp["retain_r_mm"][0]), float(exp["retain_r_mm"][1])),
            z_mm=(float(exp["retain_z_mm"][0]), float(exp["retain_z_mm"][1])))
        intruded = assembled.annulus_volume(
            centre=centre, axis=axis,
            r_mm=(0.0, float(exp["clear_r_mm"])),
            z_mm=(float(exp["clear_z_mm"][0]), float(exp["clear_z_mm"][1])))
    except MeasurementFailed as exc:
        return _unavailable_check(
            feature, title, f"{type(exc).__name__}: {exc}",
            getattr(exc, "code", "BOOLEAN_ENGINE_REFUSED"), exp, tol)

    floor = float(exp["min_retain_mm3"])
    grips = retained >= floor
    clear = intruded - ceiling <= tol
    reasons = []
    if not grips:
        reasons.append(
            f"the candidate puts {retained:.1f} mm3 inside the outer-race band and "
            f"{floor:.1f} mm3 is the least that counts as gripping it")
    if not clear:
        reasons.append(
            f"the candidate puts {intruded:.1f} mm3 inside the cylinder the inner "
            f"race and shaft turn in, above the {ceiling:.1f} mm3 allowed, so the "
            "bearing is held rather than carried")
    return Check(
        check_id=f"feature-{feature.feature_id}", feature_id=feature.feature_id,
        title=title, ran=True,
        reason="; ".join(reasons) if reasons else
               "the candidate grips the outer race and stays clear of the inner one",
        expected={"min_retain_mm3": floor, "max_intrusion_mm3": ceiling,
                  "counterpart": exp.get("counterpart"), "pose": pose,
                  "bodies": len(exp.get("bodies") or ())},
        measured={"retained_mm3": round(retained, 3),
                  "intruded_mm3": round(intruded, 3),
                  # What was actually assembled, not what was asked for: a row
                  # reporting a grip over fewer halves than the contract named
                  # is the exact failure this slice was sent back to repair.
                  "bodies_posed": len(exp.get("bodies") or ())},
        tolerance=feature.tolerance,
        result=_verdict(feature, grips and clear, True))


def _fit_acceptance_check(feature: Feature, checks: list[Check]) -> Check:
    """Bind an uncertainty-aware fit row to measurements of this candidate.

    The fit row is not allowed to pass merely because its metadata is present.
    ``candidate_feature_id`` names the one ordinary geometry check that measured
    the mapped parameter on the exported candidate. A fit acceptance row passes
    only when that measurement ran and lies inside the fitted band; a mutated
    candidate therefore fails the fit gate even when the external measurement
    and tolerance metadata are unchanged.
    """
    expectation = feature.expectation
    candidate_id = expectation.get("candidate_feature_id")
    if not isinstance(candidate_id, str) or not candidate_id:
        return _unavailable_check(
            feature, f"Fit acceptance {expectation.get('interface_id', '?')}",
            "no candidate geometry check is bound to this fit acceptance row",
            "FIT_CANDIDATE_UNBOUND", expectation, feature.tolerance)

    by_id = {check.feature_id: check for check in checks if check.feature_id}
    candidate = by_id.get(candidate_id)
    if candidate is None:
        return _unavailable_check(
            feature, f"Fit acceptance {expectation.get('interface_id', '?')}",
            f"candidate geometry check is missing: {candidate_id}",
            "FIT_CANDIDATE_CHECK_MISSING", expectation, feature.tolerance)

    measured = candidate.measured
    values: list[float]
    if isinstance(measured, dict):
        raw_value = measured.get("fit_value_mm")
        if raw_value is None:
            return _unavailable_check(
                feature, f"Fit acceptance {expectation.get('interface_id', '?')}",
                f"candidate measurement {candidate_id} could not produce the fit dimension",
                "FIT_MEASUREMENT_UNAVAILABLE", expectation, feature.tolerance)
        values = [float(raw_value)] if isinstance(raw_value, (int, float)) else []
    elif isinstance(measured, (int, float)) and not isinstance(measured, bool):
        values = [float(measured)]
    elif isinstance(measured, list):
        values = [float(value) for value in measured
                  if isinstance(value, (int, float)) and not isinstance(value, bool)]
    else:
        values = []
    raw_target = expectation.get("target_mm")
    raw_tolerance = expectation.get("acceptance_tolerance_mm")
    target = (float(raw_target)
              if isinstance(raw_target, (int, float)) and not isinstance(raw_target, bool)
              and math.isfinite(raw_target) else None)
    tolerance = (float(raw_tolerance)
                 if isinstance(raw_tolerance, (int, float)) and not isinstance(raw_tolerance, bool)
                 and math.isfinite(raw_tolerance) else None)
    numeric = target is not None and tolerance is not None
    target_value = target if target is not None else 0.0
    tolerance_value = tolerance if tolerance is not None else 0.0
    ok = (candidate.ran and candidate.result == "PASS" and numeric and bool(values)
          and all(abs(value - target_value) <= tolerance_value for value in values))
    results = {candidate_id: candidate.result}
    return Check(
        check_id=f"feature-{feature.feature_id}", feature_id=feature.feature_id,
        title=f"Fit acceptance {expectation.get('interface_id', '?')}",
        ran=True,
        reason="candidate measurement is inside the fitted target band" if ok else
               "candidate measurement is outside the fitted target band",
        expected={key: expectation.get(key) for key in (
            "nominal_mm", "clearance_mm", "target_mm", "uncertainty_mm",
            "acceptance_tolerance_mm")},
        measured={"candidate_check": results, "candidate_value_mm": values},
        tolerance=feature.tolerance,
        result="PASS" if ok else "FAIL")


def run(ctx: MeshAnalysisContext, contract: Contract,
        source_dir: Path | None = None) -> dict[str, Any]:
    """Measure the built candidate against its frozen contract.

    `source_dir` is where a declared source artifact is read from, and defaults
    to the directory holding the candidate. They are the same place for every
    unbranched job; on an alternative the candidate moves under
    `alternatives/<id>` and the source artifact does not, because it is shared
    job input and branching copies nothing.
    """
    checks: list[Check] = []

    watertight = bool(ctx.normalized.is_watertight)
    checks.append(Check("watertight", None, "Closed solid", True, "measured",
                        True, watertight, None, "PASS" if watertight else "FAIL"))

    bodies = len(ctx.components)
    checks.append(Check("bodies", None, "Separate solids", True, "measured",
                        contract.expected_bodies, bodies, None,
                        "PASS" if bodies == contract.expected_bodies else "FAIL"))

    checks.append(_seated_check(ctx, contract))

    extents = [float(v) for v in ctx.extents]
    want = contract.expected_bbox_mm
    tol = contract.bbox_tolerance_mm
    worst = max(abs(extents[i] - float(want[k])) for i, k in enumerate("xyz"))
    checks.append(Check("envelope", None, "Overall size vs contract", True, "measured",
                        want, {k: round(extents[i], 3) for i, k in enumerate("xyz")}, tol,
                        "PASS" if worst <= tol else "FAIL"))

    # A part exported in inches reads as a plausible small part in millimetres.
    # 25.4x is the only mismatch worth naming, because it is the only one that
    # happens by accident.
    ratio = max(extents) / max(float(v) for v in want.values()) if max(want.values()) else 1.0
    suspicious = any(abs(ratio - f) < 0.02 for f in (25.4, 1 / 25.4))
    checks.append(Check("unit_scale", None, "Units are millimetres", True,
                        f"extent ratio {ratio:.3f} against the contract",
                        "mm", "mm", None, "FAIL" if suspicious else "PASS"))

    bed_contact = _bed_contact(ctx, contract)
    for feature in contract.features:
        if feature.kind == "fit_acceptance":
            continue
        checks.append(_feature_check(ctx, feature, bed_contact, source_dir,
                                     contract))

    for feature in contract.features:
        if feature.kind == "fit_acceptance":
            checks.append(_fit_acceptance_check(feature, checks))

    declared = [f for f in contract.features if f.mandatory]
    covered = [c for c in checks if c.feature_id and c.ran]
    coverage = len(covered) / len(declared) if declared else 1.0

    failed = [c for c in checks if c.result == "FAIL"]
    escalated = [c for c in checks if c.result == "ESCALATE"]
    if coverage < contract.minimum_coverage:
        failed.append(Check("coverage", None, "Mandatory feature coverage", True,
                            "counted", contract.minimum_coverage, round(coverage, 3), None, "FAIL"))
        checks.append(failed[-1])

    if ctx.repair_actions:
        checks.append(Check("repair", None, "Raw vs normalized", True,
                            "; ".join(ctx.repair_actions), "no geometric change",
                            list(ctx.repair_actions), None, "ESCALATE"))
        escalated.append(checks[-1])
    else:
        checks.append(Check("repair", None, "Raw vs normalized", True,
                            f"vertex merge {ctx.vertex_merge[0]} -> {ctx.vertex_merge[1]} "
                            "is the STL format, not a repair; faces and volume unchanged",
                            "no geometric change", "none", None, "PASS"))

    verdict = "FAIL" if failed else ("ESCALATE" if escalated else "PASS")
    return {
        "schema_version": S.COMMISSION_SCHEMA,
        "contract_hash": contract.contract_hash(),
        "verdict": verdict,
        "evidence_digests": _evidence_digests(checks),
        "coverage": {"covered": len(covered), "declared": len(declared),
                     "fraction": round(coverage, 4),
                     "minimum": contract.minimum_coverage},
        "mesh_loads": ctx.load_count,
        "repair_actions": list(ctx.repair_actions),
        "raw_parse_integrity": ctx.integrity,
        "normalization_log": ctx.mutations,
        "checks": [c.as_dict() for c in checks],
    }


# The digest fields a check may publish about the measurement it ran, rather
# than about the answer it got. Named here rather than found by convention so
# that adding one is a decision: whatever appears in this list is bound into the
# review envelope, and a reviewer's answer stops matching when it moves.
EVIDENCE_DIGEST_KEYS = ("sample_plan_sha256", "evidence_sha256")


def _evidence_digests(checks: list[Check]) -> dict[str, str]:
    """Which deterministic measurement plans produced this report's evidence.

    Collected generically from the checks rather than reached for by name. The
    preservation audit is the only check that publishes one today; a second one
    that does gets bound by declaring the field, not by editing the runner.
    """
    digests: dict[str, str] = {}
    for check in checks:
        measured = check.measured
        if not isinstance(measured, dict):
            continue
        for key in EVIDENCE_DIGEST_KEYS:
            value = measured.get(key)
            if isinstance(value, str) and value:
                digests[f"{check.check_id}.{key}"] = value
    return digests


def _placed(ctx: MeshAnalysisContext, contract: Contract):
    """The mesh as it will be printed, or None if the declaration cannot say.

    `designer_toolkit/orient.py` already applies a transform to a mesh and this
    is the same call. No second arithmetic: two of those is how one receipt came
    to hold two answers about one part.
    """
    from .contract import printer_transform

    transform = printer_transform(contract)
    if transform is None:
        return None
    placed = ctx.normalized.copy()
    placed.apply_transform(transform)
    return placed


def _seated_check(ctx: MeshAnalysisContext, contract: Contract) -> Check:
    """Does the part sit on the bed -- in the frame it will be printed in?

    This read `ctx.bounds[0][2]` against a hard-coded 0.0, named no frame, and
    could PASS. On a contract declaring a 180 degree flip it returned PASS at
    measured 0.0 while `screening._bed_screen`, fixed one commit earlier,
    returned ANOMALY at 14 mm below the bed. A screen escalates and a check
    decides, so the receipt carried two answers and the deciding one was wrong.
    """
    from .contract import declared_bed_z

    placed = _placed(ctx, contract)
    bed_z = declared_bed_z(contract)
    if placed is None or bed_z is None:
        missing = "model_to_printer_matrix" if placed is None else "bed_z_mm"
        return Check(
            "seated", None, "Part sits on the bed", False,
            f"orientation.{missing} cannot be used", None, None, None, "FAIL",
            error_code="ORIENTATION_UNUSABLE",
            error_message=(
                f"orientation.{missing} cannot be used, so where this part sits "
                "relative to the bed is unknown. Measuring the authored frame "
                "instead would decide the verdict from a frame the job did not "
                "declare"))
    lowest = float(placed.bounds[0][2])
    return Check("seated", None, "Part sits on the bed", True,
                 "measured in the printer frame (the declared "
                 "model_to_printer_matrix is applied)",
                 round(bed_z, 4), round(lowest, 4), 0.05,
                 "PASS" if abs(lowest - bed_z) <= 0.05 else "FAIL")


def _bed_contact(ctx: MeshAnalysisContext, contract: Contract) -> float | None:
    """Area of faces lying on the bed plane, in the frame the part prints in.

    At the part's lowest plane *after* the declared orientation is applied.
    Measured in its authored placement -- which is what this did -- that is a
    different face entirely under any rotation.

    `None`, never `0.0`, when the orientation cannot be applied. Zero contact
    area is a legitimate measurement, so returning it for a refusal made the two
    indistinguishable, and `_feature_check` published the refusal as
    `ran: true, status: MEASURED, reason: "measured"` -- three false statements
    on one row. Worse, `run` counts a check as covered when `feature_id and
    ran`, so the fabricated row held coverage at 1.0: the gate that exists
    because "a candidate shipped 31% too thick while three checks reported
    SKIPPED and nothing counted them" was defeated by that exact mechanism. With
    a small enough declared area it also PASSed.
    """
    mesh = _placed(ctx, contract)
    if mesh is None:
        return None
    z0 = float(mesh.bounds[0][2])
    triangles = mesh.triangles
    on_bed = (abs(triangles[:, :, 2] - z0).max(axis=1) <= 0.02)
    down = mesh.face_normals[:, 2] <= -0.999
    keep = on_bed & down
    if not keep.any():
        return 0.0
    return float(mesh.area_faces[keep].sum())
