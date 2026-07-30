#!/usr/bin/env python3
"""`project.json` — the one machine-authoritative description of a job.

Before this file there were two independently editable authorities over the same
job: `job.json`, which the certified-template runner reads, and the five v4
Markdown contracts, which the role files describe. They disagree about what a job
*is*, which is why novel geometry and imported-artifact modification had no route
that could finish. `docs/adr/0001-one-project-one-cli.md` has the whole finding.

So: one file, one schema, one validator. Markdown contracts stay as generated
human-readable views; `job.json` becomes an input with an adapter. Nothing here
invents a value. A field the caller has not supplied is absent or null and shows
up in `validate()` as a problem naming itself, because the failure direction that
is safe is refusing to build rather than building against a default.

Two distinctions the schema exists to keep separate, both of which have been
collapsed by hand before:

**Where a number came from.** `STATED` by the user, `INHERITED` from a trusted
source artifact, `MEASURED` from evidence, or `CHOSEN` by design. An inherited
dimension carries the artifact's path and hash; a chosen one carries its
rationale and no claim that anybody said it.

**What kind of work this is.** `source_mode` is orthogonal to both consequence
and route. A supplied STEP that is trusted and needs no reconciliation is a
`MODIFY` job that can route `CUSTOM`; the same STEP with a photo that has to be
reconciled against it is `RECONSTRUCT` and cannot.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

from . import schemas as S

PROJECT_SCHEMA = 1
PROJECT_FILE = "project.json"

SOURCE_MODE = ("NEW", "MODIFY", "RECONSTRUCT")
ROUTE = ("DIRECT", "CUSTOM", "FITTED", "FULL")

# Where a design-driving value came from. Four, not two: collapsing `INHERITED`
# into `STATED` claims the user said something the supplied artifact did, and
# collapsing it into `CHOSEN` throws away the binding to the artifact's hash.
PROVENANCE = ("STATED", "INHERITED", "MEASURED", "CHOSEN")

# What an imported artifact can be used for, decided by diagnosis and never by
# assumption. `design-tool diagnose` fills this in; until it has, the field is
# null and every route that would build on the artifact refuses.
ARTIFACT_CLASS = ("USABLE_EXACT", "USABLE_MESH", "REPAIR_REQUIRED",
                  "RECONSTRUCTION_REQUIRED")
ARTIFACT_FORMAT = ("STEP", "STL", "3MF", "OBJ", "OTHER")

MOTION_KIND = ("LINEAR", "ROTARY", "PIECEWISE")

CANDIDATE_STRATEGY = S.CANDIDATE_STRATEGY


def _rows(value: Any, what: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise S.SchemaError(f"{what} must be a list of objects")
    return list(value)


def _text(value: Any, what: str, *, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise S.SchemaError(f"{what} must be a non-empty string")
    return value


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class Requirement:
    """One design-driving value, and the reason anyone should believe it."""

    name: str
    value: Any
    unit: str
    provenance: str
    source: str
    note: str = ""
    # Set on INHERITED rows: which supplied artifact this was read out of.
    artifact_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    def problems(self) -> list[str]:
        where = f"requirement {self.name!r}"
        out: list[str] = []
        if not self.name.strip():
            out.append("a requirement with no name cannot be bound to anything")
        if self.provenance not in PROVENANCE:
            out.append(f"{where}: provenance {self.provenance!r} is not one of "
                       f"{list(PROVENANCE)}")
        if isinstance(self.value, bool) or self.value is None:
            out.append(f"{where}: value must be a finite number or a non-empty string")
        elif isinstance(self.value, (int, float)):
            try:
                S.require_finite_number(self.value, what=where)
            except S.SchemaError as exc:
                out.append(str(exc))
        elif not (isinstance(self.value, str) and self.value.strip()):
            out.append(f"{where}: value must be a finite number or a non-empty string")
        if not self.source.strip():
            out.append(f"{where}: source must name who supplied this value")
        if self.provenance == "INHERITED" and not self.artifact_id:
            out.append(f"{where}: an inherited value must name the artifact_id it was "
                       "read out of, or it is indistinguishable from a chosen one")
        return out


@dataclasses.dataclass(frozen=True)
class SourceArtifact:
    """A supplied file that is authoritative starting geometry or evidence."""

    artifact_id: str
    path: str
    sha256: str | None = None
    format: str | None = None
    units: str | None = None
    classification: str | None = None
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    def problems(self, project_dir: Path | None) -> list[str]:
        where = f"source artifact {self.artifact_id!r}"
        out: list[str] = []
        if not self.artifact_id.strip():
            out.append("a source artifact with no id cannot be referenced")
        try:
            resolved = (S.resolve_within(project_dir, self.path, what=f"{where}.path")
                        if project_dir is not None else None)
        except S.PathEscape as exc:
            out.append(str(exc))
            resolved = None
        if resolved is not None and not resolved.is_file():
            out.append(f"{where}: {self.path!r} is not a file in this project")
        if self.format is not None and self.format not in ARTIFACT_FORMAT:
            out.append(f"{where}: format {self.format!r} is not one of "
                       f"{list(ARTIFACT_FORMAT)}")
        if self.classification is not None and self.classification not in ARTIFACT_CLASS:
            out.append(f"{where}: classification {self.classification!r} is not one of "
                       f"{list(ARTIFACT_CLASS)}")
        return out


@dataclasses.dataclass(frozen=True)
class Interface:
    """A mating surface, and who owns the geometry on the other side of it.

    The fit *strategy* -- band, contact state, coupon, acceptance method -- is the
    print engineer's, and lives in the print plan. What the project carries is the
    fact that the interface exists and whether the other side is externally owned,
    because that is what routing and the verification triggers read.
    """

    interface_id: str
    kind: str
    external: bool
    owner: str
    fit_strategy_ref: str | None = None
    motion_id: str | None = None
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    def problems(self) -> list[str]:
        where = f"interface {self.interface_id!r}"
        out: list[str] = []
        if not self.interface_id.strip():
            out.append("an interface with no id cannot be bound to a fit strategy")
        if not isinstance(self.external, bool):
            out.append(f"{where}: external must be true or false; whether the other "
                       "side is somebody else's geometry is what decides the route")
        if not self.owner.strip():
            out.append(f"{where}: owner must name who owns the mating geometry")
        return out


@dataclasses.dataclass(frozen=True)
class Motion:
    """A declared relative movement between named components.

    Phase 1 carries the declaration; the sweep engine that tests the complete
    path arrives in Phase 5. Declaring one is already load-bearing: a job with
    motion is never `DIRECT`, and a `CUSTOM` job with motion requires independent
    verification.
    """

    motion_id: str
    kind: str
    static: tuple[str, ...]
    moving: tuple[str, ...]
    declared: dict[str, Any] = dataclasses.field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"motion_id": self.motion_id, "kind": self.kind,
                "static": list(self.static), "moving": list(self.moving),
                "declared": dict(self.declared)}

    def problems(self) -> list[str]:
        where = f"motion {self.motion_id!r}"
        out: list[str] = []
        if not self.motion_id.strip():
            out.append("a motion with no id cannot be reported against")
        if self.kind not in MOTION_KIND:
            out.append(f"{where}: kind {self.kind!r} is not one of {list(MOTION_KIND)}")
        if not self.static:
            out.append(f"{where}: name the static component ids")
        if not self.moving:
            out.append(f"{where}: name the moving component ids")
        overlap = set(self.static) & set(self.moving)
        if overlap:
            out.append(f"{where}: {sorted(overlap)} are declared both static and "
                       "moving, so no sweep can be defined")
        return out


@dataclasses.dataclass(frozen=True)
class EditScope:
    """What a `MODIFY` job may touch, and what it must leave exactly alone.

    Written before the edit, like everything else here. The preservation audit in
    Phase 3 measures against this declaration; an edit scope written afterwards
    would be a description of what happened, not a gate.
    """

    artifact_id: str
    region: str
    preserve: tuple[str, ...] = ()
    may_remove: tuple[str, ...] = ()
    add: tuple[str, ...] = ()
    expected_body_delta: int = 0
    mesh_fallback_allowed: bool = False
    preserve_metadata: bool = True
    alignment_transform: Any = "identity"

    def as_dict(self) -> dict[str, Any]:
        payload = dataclasses.asdict(self)
        for key in ("preserve", "may_remove", "add"):
            payload[key] = list(getattr(self, key))
        return payload

    def problems(self) -> list[str]:
        out: list[str] = []
        if not self.artifact_id.strip():
            out.append("edit_scope: artifact_id must name the source artifact being "
                       "modified")
        if not self.region.strip():
            out.append("edit_scope: region must name the edit region; the preservation "
                       "audit measures everything outside it")
        if isinstance(self.expected_body_delta, bool) or \
                not isinstance(self.expected_body_delta, int):
            out.append("edit_scope: expected_body_delta must be an integer")
        if self.alignment_transform != "identity":
            matrix = self.alignment_transform
            ok = (isinstance(matrix, list) and len(matrix) == 4
                  and all(isinstance(row, list) and len(row) == 4 for row in matrix))
            if not ok:
                out.append("edit_scope: alignment_transform must be 'identity' or a "
                           "4x4 matrix")
        return out


@dataclasses.dataclass(frozen=True)
class Component:
    """One printed body the job expects to produce."""

    component_id: str
    role: str
    count: int = 1
    material: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    def problems(self) -> list[str]:
        out: list[str] = []
        if not self.component_id.strip():
            out.append("a component with no id cannot appear in a manifest")
        if isinstance(self.count, bool) or not isinstance(self.count, int) or self.count < 1:
            out.append(f"component {self.component_id!r}: count must be at least 1")
        return out


@dataclasses.dataclass(frozen=True)
class OpenQuestion:
    """Something nobody has answered, and whether it blocks the build."""

    question: str
    blocking: bool = True
    owner: str = "user"

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# The project
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class Project:
    job_id: str
    updated_utc: str
    source_mode: str
    consequence: str

    # Manufacturing inputs. Required rather than defaulted, for the reason the
    # runner already gives: the contract must name the machine, process, nozzle
    # and transform that the deterministic checks describe.
    printer: str | None = None
    material: dict[str, Any] | None = None
    nozzle: dict[str, Any] | None = None
    orientation: dict[str, Any] | None = None

    consequence_rationale: str = ""
    route: str | None = None
    route_rationale: str = ""

    brief: str = "brief.md"
    brief_sha256: str | None = None

    requirements: tuple[Requirement, ...] = ()
    source_artifacts: tuple[SourceArtifact, ...] = ()
    interfaces: tuple[Interface, ...] = ()
    motion: tuple[Motion, ...] = ()
    components: tuple[Component, ...] = ()
    open_questions: tuple[OpenQuestion, ...] = ()
    edit_scope: EditScope | None = None

    # The certified template, when one covers the shape, and the parameters it
    # takes. A `CUSTOM` job names a model source instead.
    template: str | None = None
    parameters: dict[str, Any] = dataclasses.field(default_factory=dict)
    model: str | None = None

    expected_artifacts: tuple[str, ...] = ()
    required_reviews: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    modifiers: tuple[str, ...] = ()
    interface_map: dict[str, str] = dataclasses.field(default_factory=dict)
    reviewer: dict[str, Any] = dataclasses.field(default_factory=dict)
    candidate_strategy: str = "SINGLE"
    # An explicit ask for an independent look, from the user or the orchestrator.
    # It only ever adds a review; nothing reads it to remove one.
    verification_requested: bool = False
    step: bool = False
    cache_dir: str | None = None

    bindings: dict[str, Any] = dataclasses.field(default_factory=dict)
    status: dict[str, Any] = dataclasses.field(default_factory=dict)
    # Set by an adapter. `job.json@1` means the routing authority reproduces the
    # legacy answers rather than the new ones -- see `route.decide`.
    compat: str | None = None

    # -- serialization ----------------------------------------------------

    def as_payload(self) -> dict[str, Any]:
        return {
            "schema_version": PROJECT_SCHEMA,
            "job_id": self.job_id,
            "updated_utc": self.updated_utc,
            "source_mode": self.source_mode,
            "consequence": self.consequence,
            "consequence_rationale": self.consequence_rationale,
            "route": self.route,
            "route_rationale": self.route_rationale,
            "brief": self.brief,
            "brief_sha256": self.brief_sha256,
            "printer": self.printer,
            "material": self.material,
            "nozzle": self.nozzle,
            "orientation": self.orientation,
            "template": self.template,
            "parameters": dict(self.parameters),
            "model": self.model,
            "requirements": [r.as_dict() for r in self.requirements],
            "source_artifacts": [a.as_dict() for a in self.source_artifacts],
            "interfaces": [i.as_dict() for i in self.interfaces],
            "motion": [m.as_dict() for m in self.motion],
            "components": [c.as_dict() for c in self.components],
            "open_questions": [q.as_dict() for q in self.open_questions],
            "edit_scope": self.edit_scope.as_dict() if self.edit_scope else None,
            "expected_artifacts": list(self.expected_artifacts),
            "required_reviews": list(self.required_reviews),
            "evidence": list(self.evidence),
            "modifiers": list(self.modifiers),
            "interface_map": dict(self.interface_map),
            "reviewer": dict(self.reviewer),
            "candidate_strategy": self.candidate_strategy,
            "verification_requested": self.verification_requested,
            "step": self.step,
            "cache_dir": self.cache_dir,
            "bindings": dict(self.bindings),
            "status": dict(self.status),
            "compat": self.compat,
        }

    def project_hash(self) -> str:
        return S.payload_hash(self.as_payload())

    def save(self, project_dir: Path) -> Path:
        path = Path(project_dir) / PROJECT_FILE
        path.write_text(S.canonical_json(self.as_payload()), encoding="utf-8")
        return path

    # -- derived ----------------------------------------------------------

    @property
    def blocking_questions(self) -> tuple[str, ...]:
        return tuple(q.question for q in self.open_questions if q.blocking)

    @property
    def external_interfaces(self) -> tuple[Interface, ...]:
        return tuple(i for i in self.interfaces if i.external)

    def artifact(self, artifact_id: str) -> SourceArtifact | None:
        for row in self.source_artifacts:
            if row.artifact_id == artifact_id:
                return row
        return None

    # -- validation -------------------------------------------------------

    def validate(self, project_dir: Path | None = None, *,
                 require_buildable: bool = True) -> list[str]:
        """Every reason this project cannot be routed or built, or an empty list.

        Deliberately a list rather than an exception: `design-tool init` writes a
        skeleton and prints these as the to-do list, and a caller filling one in
        wants all of them at once rather than one per round trip.

        `require_buildable=False` drops the one problem that is a normal state
        rather than a defect: a `CUSTOM` job has no model until the designer
        commission produces one, and refusing to route it before then would make
        the commission unreachable.
        """
        problems: list[str] = []

        if not self.job_id.strip():
            problems.append("job_id is required and must be a non-empty string")
        if not self.updated_utc.strip():
            problems.append("updated_utc is required; a wall-clock stamp would make "
                            "two runs of one job differ in their bytes")
        if self.source_mode not in SOURCE_MODE:
            problems.append(f"source_mode {self.source_mode!r} is not one of "
                            f"{list(SOURCE_MODE)}")
        if self.consequence not in S.CONSEQUENCE:
            problems.append(f"consequence {self.consequence!r} is not one of "
                            f"{list(S.CONSEQUENCE)}")
        elif not self.consequence_rationale.strip():
            problems.append("consequence_rationale is required: a class with no reason "
                            "behind it cannot be re-checked when the job changes")
        if self.route is not None and self.route not in ROUTE:
            problems.append(f"route {self.route!r} is not one of {list(ROUTE)}")
        if self.candidate_strategy not in CANDIDATE_STRATEGY:
            problems.append(f"candidate_strategy {self.candidate_strategy!r} is not one "
                            f"of {list(CANDIDATE_STRATEGY)}")

        if not isinstance(self.printer, str) or not self.printer.strip():
            problems.append("printer is required and must be a non-empty string")
        material = self.material
        if (not isinstance(material, dict)
                or not isinstance(material.get("process"), str)
                or not material["process"].strip()
                or not isinstance(material.get("material"), str)
                or not material["material"].strip()):
            problems.append("material must name non-empty process and material strings")
        nozzle = self.nozzle
        diameter = nozzle.get("diameter_mm") if isinstance(nozzle, dict) else None
        if (not isinstance(diameter, (int, float)) or isinstance(diameter, bool)
                or diameter <= 0):
            problems.append("nozzle.diameter_mm must be a positive number")
        problems.extend(_orientation_problems(self.orientation))

        for name, value in sorted(self.parameters.items()):
            if not isinstance(name, str):
                problems.append("parameters keys must be strings")
                continue
            try:
                S.require_finite_number(value, what=f"parameters.{name}")
            except S.SchemaError as exc:
                problems.append(str(exc))

        seen: set[str] = set()
        for requirement in self.requirements:
            if requirement.name in seen:
                problems.append(f"requirement {requirement.name!r}: duplicate name -- "
                                "two provenances for one value is no provenance")
            seen.add(requirement.name)
            problems.extend(requirement.problems())
            if requirement.artifact_id and self.artifact(requirement.artifact_id) is None:
                problems.append(f"requirement {requirement.name!r}: artifact_id "
                                f"{requirement.artifact_id!r} names no source artifact")

        for artifact in self.source_artifacts:
            problems.extend(artifact.problems(project_dir))
        for interface in self.interfaces:
            problems.extend(interface.problems())
            if interface.motion_id and not any(m.motion_id == interface.motion_id
                                               for m in self.motion):
                problems.append(f"interface {interface.interface_id!r}: motion_id "
                                f"{interface.motion_id!r} names no declared motion")
        for motion in self.motion:
            problems.extend(motion.problems())
        for component in self.components:
            problems.extend(component.problems())

        if self.source_mode == "MODIFY":
            if not self.source_artifacts:
                problems.append("source_mode is MODIFY and no source artifact is "
                                "declared; there is nothing authoritative to modify")
            if self.edit_scope is None:
                problems.append("source_mode is MODIFY and no edit_scope is declared; "
                                "without one nothing can say what must be preserved")
        if self.edit_scope is not None:
            problems.extend(self.edit_scope.problems())
            if self.artifact(self.edit_scope.artifact_id) is None:
                problems.append(f"edit_scope: artifact_id "
                                f"{self.edit_scope.artifact_id!r} names no source "
                                "artifact")
        if self.source_mode == "NEW" and self.source_artifacts:
            problems.append("source_mode is NEW but source artifacts are declared; "
                            "geometry inherited from a supplied file is MODIFY")

        if require_buildable and self.template is None and self.model is None:
            problems.append("neither template nor model is named; nothing can be "
                            "built until one of them is")
        if self.model is not None and project_dir is not None:
            try:
                S.resolve_within(project_dir, self.model, what="model")
            except S.PathEscape as exc:
                problems.append(str(exc))

        for name in self.evidence:
            if project_dir is not None:
                try:
                    S.resolve_within(project_dir, name, what="evidence")
                except S.PathEscape as exc:
                    problems.append(str(exc))
        return problems


def _orientation_problems(orientation: Any) -> list[str]:
    problems: list[str] = []
    matrix = orientation.get("model_to_printer_matrix") if isinstance(orientation, dict) else None
    ok = matrix == "identity" or (
        isinstance(matrix, list) and len(matrix) == 4
        and all(isinstance(row, list) and len(row) == 4
                and all(isinstance(value, (int, float)) and not isinstance(value, bool)
                        for value in row)
                for row in matrix))
    if not ok:
        problems.append("orientation.model_to_printer_matrix must be 'identity' or a "
                        "4x4 matrix")
    bed_z = orientation.get("bed_z_mm") if isinstance(orientation, dict) else None
    if not isinstance(bed_z, (int, float)) or isinstance(bed_z, bool):
        problems.append("orientation.bed_z_mm must be a number")
    return problems


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def from_payload(payload: dict[str, Any]) -> Project:
    """Parse a project payload, refusing shapes rather than coercing them."""
    if not isinstance(payload, dict):
        raise S.SchemaError("project must be a JSON object")
    version = payload.get("schema_version")
    if version != PROJECT_SCHEMA:
        raise S.SchemaError(
            f"project schema_version {version!r} is not {PROJECT_SCHEMA}; a reader "
            "that guesses at an unknown version is indistinguishable from one that "
            "read it correctly")

    edit = payload.get("edit_scope")
    edit_scope = None
    if edit is not None:
        if not isinstance(edit, dict):
            raise S.SchemaError("edit_scope must be an object or null")
        edit_scope = EditScope(
            artifact_id=str(edit.get("artifact_id", "")),
            region=str(edit.get("region", "")),
            preserve=tuple(edit.get("preserve") or ()),
            may_remove=tuple(edit.get("may_remove") or ()),
            add=tuple(edit.get("add") or ()),
            expected_body_delta=edit.get("expected_body_delta", 0),
            mesh_fallback_allowed=bool(edit.get("mesh_fallback_allowed", False)),
            preserve_metadata=bool(edit.get("preserve_metadata", True)),
            alignment_transform=edit.get("alignment_transform", "identity"))

    return Project(
        job_id=str(payload.get("job_id", "")),
        updated_utc=str(payload.get("updated_utc", "")),
        source_mode=str(payload.get("source_mode", "")),
        consequence=str(payload.get("consequence", "")),
        consequence_rationale=str(payload.get("consequence_rationale", "")),
        route=payload.get("route"),
        route_rationale=str(payload.get("route_rationale", "")),
        brief=str(payload.get("brief") or "brief.md"),
        brief_sha256=payload.get("brief_sha256"),
        printer=payload.get("printer"),
        material=payload.get("material"),
        nozzle=payload.get("nozzle"),
        orientation=payload.get("orientation"),
        template=payload.get("template"),
        parameters=dict(payload.get("parameters") or {}),
        model=payload.get("model"),
        requirements=tuple(
            Requirement(name=str(row.get("name", "")), value=row.get("value"),
                        unit=str(row.get("unit", "mm")),
                        provenance=str(row.get("provenance", "")),
                        source=str(row.get("source", "")),
                        note=str(row.get("note", "")),
                        artifact_id=row.get("artifact_id"))
            for row in _rows(payload.get("requirements"), "requirements")),
        source_artifacts=tuple(
            SourceArtifact(artifact_id=str(row.get("artifact_id", "")),
                           path=str(row.get("path", "")),
                           sha256=row.get("sha256"), format=row.get("format"),
                           units=row.get("units"),
                           classification=row.get("classification"),
                           note=str(row.get("note", "")))
            for row in _rows(payload.get("source_artifacts"), "source_artifacts")),
        interfaces=tuple(
            Interface(interface_id=str(row.get("interface_id", "")),
                      kind=str(row.get("kind", "")),
                      external=row.get("external"),
                      owner=str(row.get("owner", "")),
                      fit_strategy_ref=row.get("fit_strategy_ref"),
                      motion_id=row.get("motion_id"),
                      note=str(row.get("note", "")))
            for row in _rows(payload.get("interfaces"), "interfaces")),
        motion=tuple(
            Motion(motion_id=str(row.get("motion_id", "")),
                   kind=str(row.get("kind", "")),
                   static=tuple(row.get("static") or ()),
                   moving=tuple(row.get("moving") or ()),
                   declared=dict(row.get("declared") or {}))
            for row in _rows(payload.get("motion"), "motion")),
        components=tuple(
            Component(component_id=str(row.get("component_id", "")),
                      role=str(row.get("role", "")),
                      count=row.get("count", 1), material=row.get("material"))
            for row in _rows(payload.get("components"), "components")),
        open_questions=tuple(
            OpenQuestion(question=str(row.get("question", "")),
                         blocking=bool(row.get("blocking", True)),
                         owner=str(row.get("owner", "user")))
            for row in _rows(payload.get("open_questions"), "open_questions")),
        edit_scope=edit_scope,
        expected_artifacts=tuple(payload.get("expected_artifacts") or ()),
        required_reviews=tuple(payload.get("required_reviews") or ()),
        evidence=tuple(payload.get("evidence") or ()),
        modifiers=tuple(payload.get("modifiers") or ()),
        interface_map=dict(payload.get("interface_map") or {}),
        reviewer=dict(payload.get("reviewer") or {}),
        candidate_strategy=str(payload.get("candidate_strategy") or "SINGLE"),
        verification_requested=bool(payload.get("verification_requested", False)),
        step=bool(payload.get("step", False)),
        cache_dir=payload.get("cache_dir"),
        bindings=dict(payload.get("bindings") or {}),
        status=dict(payload.get("status") or {}),
        compat=payload.get("compat"),
    )


def load(project_dir: Path) -> Project:
    path = Path(project_dir) / PROJECT_FILE
    if not path.is_file():
        raise FileNotFoundError(f"no {PROJECT_FILE} in {project_dir}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise S.SchemaError(f"{PROJECT_FILE} is not valid UTF-8: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise S.SchemaError(f"{PROJECT_FILE} is not valid JSON: {exc}") from exc
    return from_payload(payload)


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------

def from_job_json(spec: dict[str, Any]) -> Project:
    """Derive a project from a legacy `job.json`, marked as one.

    The `compat` mark is load-bearing rather than cosmetic. A legacy job has no
    `source_mode`, so the routing authority cannot ask the questions the new
    route model is built on -- and answering them by assumption would silently
    re-route jobs that were routing correctly. `route.decide` sees the mark and
    reproduces `intent.select`'s answers exactly.
    """
    stated = frozenset(spec.get("stated") or ())
    parameters = dict(spec.get("parameters") or {})
    requirements = tuple(
        Requirement(name=name, value=value, unit="mm",
                    provenance="STATED" if name in stated else "CHOSEN",
                    source="user" if name in stated else "designer")
        for name, value in sorted(parameters.items()))
    questions = tuple(OpenQuestion(question=text, blocking=True)
                      for text in (spec.get("ambiguities") or ()))
    external = bool(spec.get("external_geometry", False))
    return Project(
        job_id=str(spec.get("job_id", "")),
        updated_utc=str(spec.get("updated_utc", "")),
        source_mode="RECONSTRUCT" if external else "NEW",
        consequence=str(spec.get("consequence", "")),
        consequence_rationale="carried over from job.json, which has no field for it",
        printer=spec.get("printer"),
        material=spec.get("material"),
        nozzle=spec.get("nozzle"),
        orientation=spec.get("orientation"),
        brief=str(spec.get("brief") or "brief.md"),
        template=spec.get("template"),
        parameters=parameters,
        requirements=requirements,
        open_questions=questions,
        interfaces=tuple(
            Interface(interface_id=interface_id, kind="fit", external=True,
                      owner="external object",
                      note=f"drives the {parameter!r} parameter")
            for interface_id, parameter in sorted((spec.get("interface_map") or {}).items())),
        evidence=tuple(spec.get("evidence") or ()),
        modifiers=tuple(spec.get("modifiers") or ()),
        interface_map=dict(spec.get("interface_map") or {}),
        reviewer=dict(spec.get("reviewer") or {}),
        candidate_strategy=str(spec.get("candidate_strategy") or "SINGLE"),
        step=bool(spec.get("step", False)),
        cache_dir=spec.get("cache_dir"),
        compat="job.json@1",
        status={"external_geometry": external},
    )


def to_job_request_fields(project: Project) -> dict[str, Any]:
    """The subset `runner.JobRequest` needs, without inventing anything.

    Kept here rather than in the runner so that there is exactly one place that
    knows how a canonical project maps onto the legacy request, and the runner
    keeps taking the request it already takes.
    """
    stated = frozenset(r.name for r in project.requirements
                       if r.provenance == "STATED")
    return {
        "job_id": project.job_id,
        "template": project.template,
        "parameters": dict(project.parameters),
        "stated": stated,
        "consequence": project.consequence,
        "updated_utc": project.updated_utc,
        "printer": project.printer,
        "material": project.material,
        "nozzle": project.nozzle,
        "orientation": project.orientation,
        "modifiers": tuple(project.modifiers),
        "candidate_strategy": project.candidate_strategy,
        "external_geometry": bool(project.status.get("external_geometry",
                                                     bool(project.external_interfaces))),
        "ambiguities": project.blocking_questions,
        "step": project.step,
        "evidence": tuple(project.evidence),
        "interface_map": dict(project.interface_map),
        "reviewer": dict(project.reviewer),
    }


def skeleton(*, job_id: str, source_mode: str, consequence: str,
             updated_utc: str) -> Project:
    """The empty project `design-tool init` writes.

    Every field the caller must supply is present and empty, and shows up in
    `validate()` naming itself. Nothing is guessed: a skeleton that defaulted the
    printer would produce a contract describing a machine nobody chose.
    """
    return Project(
        job_id=job_id, updated_utc=updated_utc, source_mode=source_mode,
        consequence=consequence,
        open_questions=(
            OpenQuestion("what printer, material and nozzle is this for?",
                         blocking=True, owner="user"),
            OpenQuestion("which values are stated by the brief, and which are "
                         "chosen by design?", blocking=True, owner="orchestrator"),
        ),
    )
