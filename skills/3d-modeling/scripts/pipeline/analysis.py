#!/usr/bin/env python3
"""One mesh load per job, and every derived quantity computed once.

The old gate loaded the exported STL four times in a single commission and
recomputed bounds, normals and components on each pass. Nothing was wrong with
the answers; it just paid for them repeatedly, and a second load is also a second
chance for raw and normalized to diverge without anyone noticing which one a
given check used.

So both meshes are loaded here, once, and every check takes this object. `raw` is
parsed with no topology repair; `normalized` is the merged/repaired copy. Checks
that care about what was *exported* read `raw`; checks that need well-formed
topology read `normalized`; and the difference between them is itself reported,
because a repair that changed the geometry is a finding rather than a convenience.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - annotations only, never evaluated
    # `from __future__ import annotations` above makes every annotation in this
    # file a string, so these two names are wanted by a type checker and by nobody
    # at runtime. Keeping them out of the module body is what stops a command that
    # never loads a mesh from paying for the mesh stack: measured warm on 22c3b29,
    # importing `pipeline.cli` cost 1546-1569 ms, of which `trimesh` was
    # 1320-1336 ms -- 85%, reached only through this module, by `doctor`, `status`,
    # `init` and `route`, none of which touch geometry. The runtime imports now sit
    # in the six functions that actually call the library, which is the rule
    # `diagnose.py` states and every backend already follows.
    import numpy as np
    import trimesh

SLAB_MM = 0.02


class MeasurementFailed(RuntimeError):
    """The instrument did not answer. Distinct from answering zero."""

    def __init__(self, message: str, *, code: str = "BOOLEAN_ENGINE_REFUSED") -> None:
        super().__init__(message)
        self.code = code


@dataclasses.dataclass
class MeshAnalysisContext:
    path: Path
    raw: trimesh.Trimesh
    normalized: trimesh.Trimesh
    load_count: int
    repair_actions: tuple[str, ...]
    # What the parse and the normalization actually saw. Reported, never a
    # verdict: every escalation here is `repair_actions`, which is derived from
    # comparing the two meshes rather than from either tool's own log.
    integrity: dict[str, Any] = dataclasses.field(default_factory=dict)
    mutations: dict[str, Any] = dataclasses.field(default_factory=dict)
    # Recorded, never escalated: see `load` for why the ratio is meaningless.
    vertex_merge: tuple[int, int] = (0, 0)
    _sections: dict[tuple, float] = dataclasses.field(default_factory=dict)
    _windows: dict[tuple, float] = dataclasses.field(default_factory=dict)
    _fit_dimensions: dict[tuple, float] = dataclasses.field(default_factory=dict)

    @property
    def bounds(self) -> np.ndarray:
        return self.normalized.bounds

    @property
    def extents(self) -> np.ndarray:
        return self.normalized.extents

    @property
    def components(self) -> list[trimesh.Trimesh]:
        if not hasattr(self, "_components"):
            self._components = self.normalized.split(only_watertight=False)
        return self._components

    def section_area(self, z: float) -> float:
        """Material area on a Z plane, net of every hole, cached per height.

        Measured by intersecting a thin slab and dividing by its thickness. The
        obvious route is `mesh.section`, which reaches scipy, networkx, shapely
        and rtree. Those packages are core because a normal certified DIRECT
        commission must measure the same cross-sections from a production wheel.
        """
        key = ("z", round(float(z), 6))
        if key not in self._sections:
            self._sections[key] = self._slab_area(z)
        return self._sections[key]

    def section_bore_diameter_mm(self, *, z: float, at: tuple[float, float]) -> float:
        """Measure the nearest circular void boundary from candidate geometry.

        This is a geometry probe, not an inverse of a section-area formula. It
        intersects the exported candidate with the requested plane, finds the
        nearest section vertex to the declared datum, and reports twice that
        radius. Contract wall, mouth, and other design parameters never enter
        this measurement, so compensating one of them cannot mask a bore error.
        """
        key = (round(float(z), 6), round(float(at[0]), 6), round(float(at[1]), 6))
        if key in self._fit_dimensions:
            return self._fit_dimensions[key]
        try:
            section = self.normalized.section(
                plane_origin=[0.0, 0.0, float(z)], plane_normal=[0.0, 0.0, 1.0]
            )
        except Exception as exc:
            raise MeasurementFailed(
                f"the section instrument could not measure the candidate at z={z:.3f}: {exc}",
                code="SECTION_INSTRUMENT_REFUSED",
            ) from exc
        if section is None or len(section.discrete) == 0:
            raise MeasurementFailed(
                f"the candidate has no measurable section at z={z:.3f}",
                code="SECTION_INSTRUMENT_EMPTY",
            )
        # Above the `try`, not inside it: the handler below turns anything raised
        # into a MeasurementFailed, and a missing dependency is not a measurement
        # that failed.
        import numpy as np

        try:
            points = np.vstack([np.asarray(path, dtype=float) for path in section.discrete])
            distances = np.linalg.norm(points[:, :2] - np.asarray(at, dtype=float), axis=1)
            distances = distances[distances > 1e-6]
            if distances.size == 0:
                raise ValueError("section has no non-central boundary vertices")
            value = 2.0 * float(np.min(distances))
        except Exception as exc:
            if isinstance(exc, MeasurementFailed):
                raise
            raise MeasurementFailed(
                f"the section instrument could not identify a circular void boundary: {exc}",
                code="SECTION_INSTRUMENT_INDETERMINATE",
            ) from exc
        self._fit_dimensions[key] = value
        return value

    def _slab_area(self, z: float) -> float:
        # Function-local, as everywhere else in this package: a job that never
        # touches a mesh must not pay the import.
        import trimesh

        span = float(max(self.extents)) * 4.0 + 10.0
        window = trimesh.creation.box(extents=(span, span, SLAB_MM))
        centre = self.normalized.centroid
        window.apply_translation([float(centre[0]), float(centre[1]), float(z)])
        solid = self._intersect(window, where=f"the plane z={z:.3f}")
        return 0.0 if solid.is_empty else float(solid.volume) / SLAB_MM

    def _intersect(self, window, *, where: str):
        """Intersect, turning an engine refusal into a measurement failure.

        manifold3d raises `Not all meshes are volumes!` on a mesh it cannot treat
        as a solid. Left uncaught that ends the job in a traceback out of the CLI
        -- no receipt, no final status, and a half-written project directory. A
        part the engine cannot measure is a finding, and findings are written
        down.
        """
        # Above the `try` for the same reason as in `section_bore_diameter_mm`: the
        # handler turns anything raised into a MeasurementFailed, and an absent
        # library is not the engine refusing a part.
        import trimesh

        try:
            solid = trimesh.boolean.intersection([self.normalized, window],
                                                 engine="manifold")
        except Exception as exc:
            if isinstance(exc, MeasurementFailed):
                raise
            raise MeasurementFailed(
                f"the boolean engine could not measure {where}: {exc}. The mesh is "
                "not a closed solid, so nothing sectioned from it means anything."
            ) from exc
        if solid is None:
            raise MeasurementFailed(
                f"the boolean engine returned nothing for {where}, so this is an "
                "absent measurement rather than an empty one.",
                code="BOOLEAN_ENGINE_RETURNED_NONE",
            )
        return solid

    def window_area(self, *, z: float, at: tuple[float, float],
                    size: tuple[float, float]) -> float:
        """Material area inside one axis-aligned rectangle on a Z plane."""
        key = (round(z, 6), round(at[0], 6), round(at[1], 6), round(size[0], 6), round(size[1], 6))
        if key not in self._windows:
            import trimesh

            window = trimesh.creation.box(extents=(float(size[0]), float(size[1]), SLAB_MM))
            window.apply_translation([float(at[0]), float(at[1]), float(z)])
            solid = self._intersect(window, where=f"the window at z={z:.3f}")
            # `_intersect` raises for an absent engine answer; a non-empty answer
            # is the measured material, and an empty one is a genuinely measured
            # zero.
            self._windows[key] = 0.0 if solid.is_empty else float(solid.volume) / SLAB_MM
        return self._windows[key]

    def disc_area(self, *, z: float, at: tuple[float, float], diameter: float) -> float:
        """Material area inside a disc on a Z plane, cached like the rest."""
        key = ("disc", round(z, 6), round(at[0], 6), round(at[1], 6), round(diameter, 6))
        if key not in self._windows:
            import trimesh

            window = trimesh.creation.cylinder(radius=float(diameter) / 2.0,
                                               height=SLAB_MM, sections=192)
            window.apply_translation([float(at[0]), float(at[1]), float(z)])
            solid = self._intersect(window, where=f"the disc at z={z:.3f}")
            self._windows[key] = 0.0 if solid.is_empty else float(solid.volume) / SLAB_MM
        return self._windows[key]

    def annulus_volume(self, *, centre: tuple[float, float, float],
                       axis: tuple[float, float, float],
                       r_mm: tuple[float, float],
                       z_mm: tuple[float, float]) -> float:
        """Candidate material inside one annular zone, in mm3.

        The instrument the bearing blind spot needed. Every other measurement in
        this class asks a question about the candidate alone -- an area, an
        extent, a diameter -- and a clamp that grips the *inner* race of its
        bearing answers all of them correctly while being the one part the brief
        forbids. That failure is not a dimension being wrong. It is material in a
        place no dimension names, so the measurement has to be a volume in a
        region rather than a number on a plane.

        `r_mm` is `(inner, outer)`; an inner radius of zero gives a plain
        cylinder. `centre` and `axis` place the zone in the candidate's frame,
        and `z_mm` is the span along `axis` measured from `centre`. The zone is
        built from the assembled pose rather than from anything measured on the
        candidate, which is what keeps the question candidate-independent: the
        same zone is put to a good part and a bad one.

        Volume, not area, and deliberately: an area on a plane can miss a lip
        that sits between two sampled heights, which is exactly how the failure
        this measures escapes the section rows.
        """
        inner, outer = float(r_mm[0]), float(r_mm[1])
        low, high = float(z_mm[0]), float(z_mm[1])
        height = high - low
        # Refused before the mesh stack is touched, and before the cache is
        # consulted, because this is a statement about the declaration rather
        # than about the part: a zone that encloses nothing intersects every
        # candidate in 0.0 mm3, which on a receipt is indistinguishable from a
        # part that genuinely stays clear.
        if outer <= inner or height <= 0:
            raise MeasurementFailed(
                f"the zone at {tuple(centre)} has no volume to measure: radii "
                f"{inner:g}..{outer:g} mm over {height:g} mm of height. A zone "
                "that encloses nothing cannot report material inside it.",
                code="ZONE_DEGENERATE")
        if not any(float(v) != 0.0 for v in axis):
            raise MeasurementFailed(
                "the zone declares a zero-length axis, so its orientation is "
                "undefined and the region it names is not a region.",
                code="ZONE_AXIS_DEGENERATE")

        key = ("annulus", tuple(round(float(v), 6) for v in centre),
               tuple(round(float(v), 6) for v in axis),
               (round(inner, 6), round(outer, 6)),
               (round(low, 6), round(high, 6)))
        if key not in self._windows:
            import numpy as np
            import trimesh

            zone = trimesh.creation.cylinder(radius=outer, height=height,
                                             sections=192)
            if inner > 0:
                # Taller than the zone so the bore is a through hole rather than
                # a blind pocket with two lids the boolean would keep.
                bore = trimesh.creation.cylinder(radius=inner,
                                                 height=height * 2.0 + 1.0,
                                                 sections=192)
                zone = trimesh.boolean.difference([zone, bore], engine="manifold")
            # `trimesh.creation.cylinder` is centred on the origin and runs along
            # +Z, so the zone's own mid-height is the offset that lands `low` at
            # `low`.
            zone.apply_translation([0.0, 0.0, low + height / 2.0])
            direction = np.asarray(axis, dtype=float)
            norm = float(np.linalg.norm(direction))
            zone.apply_transform(trimesh.geometry.align_vectors(
                [0.0, 0.0, 1.0], direction / norm))
            zone.apply_translation([float(v) for v in centre])
            solid = self._intersect(zone, where=f"the zone at {centre}")
            self._windows[key] = 0.0 if solid.is_empty else float(solid.volume)
        return self._windows[key]

    def axis_profile(self, axis: int, samples: int, *, jitter: float = 0.0) -> list[dict[str, Any]]:
        """Material area along one axis, for the screening detectors.

        Jitter exists because a fixed grid is easy to be unlucky with: a small
        local defect can sit entirely between two evenly spaced planes and never
        appear. The offset is deterministic per job so a rerun samples the same
        places -- reproducibility matters more here than independence.
        """
        low, high = float(self.bounds[0][axis]), float(self.bounds[1][axis])
        if high <= low:
            return []
        step = (high - low) / samples
        rows = []
        for i in range(samples):
            at = low + (i + 0.5 + jitter) * step
            at = min(max(at, low + step * 0.05), high - step * 0.05)
            rows.append({"at": round(at, 4), "area_mm2": round(self._axis_area(axis, at), 3)})
        return rows

    def _axis_area(self, axis: int, at: float) -> float:
        if axis == 2:
            return self.section_area(at)
        span = float(max(self.extents)) * 4.0 + 10.0
        extents = [span, span, span]
        extents[axis] = SLAB_MM
        import trimesh

        window = trimesh.creation.box(extents=tuple(extents))
        centre = list(self.normalized.centroid)
        centre[axis] = at
        window.apply_translation([float(v) for v in centre])
        solid = self._intersect(window, where=f"axis {axis} at {at:.3f}")
        return 0.0 if solid.is_empty else float(solid.volume) / SLAB_MM


def load(path: Path) -> MeshAnalysisContext:
    """Parse once, repair once, and report what the repair changed."""
    import mesh_io

    # One parse. `load_mesh` would re-read the file from disk; `normalize_mesh`
    # derives the repaired copy from the bytes already in hand, which is what
    # "load each STL once" has to mean if the count is to be worth asserting.
    # Counted, not declared. The previous version assigned a module constant to
    # `load_count` and a test asserted against it, so adding a genuine second
    # parse left the receipt reporting 1 and the test green. A number that cannot
    # be wrong is not a measurement.
    parses = 0
    real_raw_loader = mesh_io.load_mesh_raw

    def counting_loader(target):
        nonlocal parses
        parses += 1
        return real_raw_loader(target)

    raw, integrity = counting_loader(path)
    normalized, mutations = mesh_io.normalize_mesh(raw)

    # Vertex merging is not a repair -- it is the STL format. Every file stores
    # three unshared vertices per triangle, so the merge ratio is about 6:1 on
    # every mesh ever exported (measured here: 3048 -> 508, faces and volume
    # unchanged, volume delta exactly 0). Escalating on it would fire on every
    # job, and an escalation that always fires is one nobody reads.
    #
    # What is worth escalating is geometry that changed: faces dropped as
    # degenerate, or a volume that moved.
    actions: list[str] = []
    if len(raw.faces) != len(normalized.faces):
        actions.append(f"dropped {len(raw.faces) - len(normalized.faces)} degenerate "
                       f"face(s): {len(raw.faces)} -> {len(normalized.faces)}")
    volume_delta = abs(float(raw.volume) - float(normalized.volume))
    if volume_delta > max(1e-6, 1e-9 * abs(float(raw.volume))):
        actions.append(f"volume moved by {volume_delta:.6g} mm3 during normalization")
    return MeshAnalysisContext(
        path=path, raw=raw, normalized=normalized, load_count=parses,
        repair_actions=tuple(actions),
        integrity=dataclasses.asdict(integrity),
        mutations=dataclasses.asdict(mutations),
        vertex_merge=(len(raw.vertices), len(normalized.vertices)))
