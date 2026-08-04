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
import re
from pathlib import Path
from typing import Any

from . import findings as F
from . import schemas as S
from .findings import Issue

PROJECT_SCHEMA = 1
PROJECT_FILE = "project.json"

SOURCE_MODE = ("NEW", "MODIFY", "RECONSTRUCT")
ROUTE = ("DIRECT", "CUSTOM", "FITTED", "FULL")

# Where a branched formulation's own work lives, under the project directory. A
# project that has never branched has no such directory and no path component
# added to anything it writes.
ALTERNATIVES_DIR = "alternatives"

# The id becomes a directory name and appears in the execution plan and in every
# review envelope, so it is restricted to the characters every filesystem agrees
# about. `schemas.resolve_within` is still the gate that proves the join stays
# inside the project; this is what stops an id that would need quoting, case
# folding or percent-encoding to be written down at all.
ALTERNATIVE_ID = re.compile(r"^[a-z0-9-]+$")

# What an alternative's disposition may say -- the seven states ARCHITECTURE.md
# 6.13 names. A lifecycle that cannot record "paused" records it as "rejected",
# so the vocabulary is complete from the start.
ALTERNATIVE_DISPOSITION = ("ACTIVE", "PREFERRED", "PAUSED", "REJECTED",
                           "SUPERSEDED", "FALLBACK", "MERGED")

# The three a formulation may be *worked under*: it can be the active one, and
# `design-tool run` will build it.
#
# `FALLBACK` is here and the other four are not, and the reason is a real job.
# The vent-ball exercise retained one formulation unchanged as the thing to fall
# back on if a photo estimate turned out wrong, and had to record it `ACTIVE`
# because a build that would not run a `FALLBACK` gives "retained" and
# "abandoned" the same behaviour. A fallback you may not keep current is not a
# fallback; it is a rejection with a kinder word. So a fallback runs, and what
# separates it from `ACTIVE` is `status`: it is named as the option to fall back
# on exactly when the current formulation has no claim (`cli.status`).
RUNNABLE_DISPOSITION = ("ACTIVE", "PREFERRED", "FALLBACK")

# The three that say this formulation is finished with. They are not runnable,
# and concluding one *clears its `next_action.json`*: an instruction is read as
# "this is what the job is waiting for", and a formulation nobody will pick up
# again is waiting for nothing. Its receipts stay exactly where they are --
# 13.1 says history is not rewritten, and a rejection is evidence.
CONCLUDED_DISPOSITION = ("REJECTED", "SUPERSEDED", "MERGED")

# Why a formulation is in the state it is in. ARCHITECTURE.md 14.6 is explicit
# that "the disposition must include its basis", and this is that list, spelled
# as a closed set so that the answer is comparable across jobs rather than a
# free sentence per project. `ACTIVE` needs none: it is the state a formulation
# starts in, and demanding a reason for the default would be demanding a reason
# for nothing having happened yet.
DISPOSITION_BASIS = ("USER_SELECTION", "REQUIREMENT_FAILURE",
                     "MANUFACTURING_DISADVANTAGE", "PHYSICAL_TEST",
                     "UNRESOLVED_EVIDENCE", "STRONGER_CONCEPT")

BASIS_REQUIRED = tuple(d for d in ALTERNATIVE_DISPOSITION if d != "ACTIVE")

# The two that must name what replaced them. `SUPERSEDED` without a successor is
# an assertion that something better exists with no way to find it, and `MERGED`
# without one is a claim about a graph edge nobody can check -- which is the
# whole reason `MERGED` survives in a build that has no merge: it is refused
# unless the successor's `parents` actually record the merge, so the state
# cannot be claimed ahead of the capability.
SUCCESSOR_REQUIRED = ("SUPERSEDED", "MERGED")

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


def _rows(value: Any, what: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise S.SchemaError(f"{what} must be a list of objects")
    return list(value)


def _ids(value: Any, what: str) -> tuple[str, ...]:
    """A list of ids, refusing the bare string that looks like one.

    `tuple("magnet-pockets")` is fourteen ids, so a caller who wrote a string
    where a list belongs would otherwise be told about fourteen interfaces
    nobody declared instead of about the field they got wrong.
    """
    if value is None:
        return ()
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise S.SchemaError(f"{what} must be a list of ids, not a bare string")
    return tuple(value)


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

    def problems(self, index: int = 0) -> list[Issue]:
        where = f"requirement {self.name!r}"
        path = f"requirements[{index}]"
        out: list[Issue] = []
        if not self.name.strip():
            out.append(F.problem(F.SCHEMA_REQUIRED, f"{path}.name",
                                 "a requirement with no name cannot be bound to anything"))
        if self.provenance not in PROVENANCE:
            out.append(F.problem(F.SCHEMA_ENUM, f"{path}.provenance",
                                 f"{where}: provenance {self.provenance!r} is not one of "
                                 f"{list(PROVENANCE)}"))
        if isinstance(self.value, bool) or self.value is None:
            out.append(F.problem(F.SCHEMA_TYPE, f"{path}.value",
                                 f"{where}: value must be a finite number or a non-empty string"))
        elif isinstance(self.value, (int, float)):
            try:
                S.require_finite_number(self.value, what=where)
            except S.SchemaError as exc:
                out.append(F.problem(F.SCHEMA_NON_FINITE, f"{path}.value", str(exc)))
        elif not (isinstance(self.value, str) and self.value.strip()):
            out.append(F.problem(F.SCHEMA_TYPE, f"{path}.value",
                                 f"{where}: value must be a finite number or a non-empty string"))
        if not self.source.strip():
            out.append(F.problem(F.SCHEMA_REQUIRED, f"{path}.source",
                                 f"{where}: source must name who supplied this value"))
        if self.provenance == "INHERITED" and not self.artifact_id:
            out.append(F.problem(
                F.SCHEMA_REQUIRED, f"{path}.artifact_id",
                f"{where}: an inherited value must name the artifact_id it was "
                "read out of, or it is indistinguishable from a chosen one"))
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

    def problems(self, project_dir: Path | None, index: int = 0) -> list[Issue]:
        where = f"source artifact {self.artifact_id!r}"
        path = f"source_artifacts[{index}]"
        out: list[Issue] = []
        if not self.artifact_id.strip():
            out.append(F.problem(F.SCHEMA_REQUIRED, f"{path}.artifact_id",
                                 "a source artifact with no id cannot be referenced"))
        try:
            resolved = (S.resolve_within(project_dir, self.path, what=f"{where}.path")
                        if project_dir is not None else None)
        except S.PathEscape as exc:
            out.append(F.problem(F.ARTIFACT_PATH_UNSAFE, f"{path}.path", str(exc)))
            resolved = None
        if resolved is not None and not resolved.is_file():
            out.append(F.problem(F.ARTIFACT_MISSING, f"{path}.path",
                                 f"{where}: {self.path!r} is not a file in this project"))
        if self.format is not None and self.format not in ARTIFACT_FORMAT:
            out.append(F.problem(F.SCHEMA_ENUM, f"{path}.format",
                                 f"{where}: format {self.format!r} is not one of "
                                 f"{list(ARTIFACT_FORMAT)}"))
        if self.classification is not None and self.classification not in ARTIFACT_CLASS:
            out.append(F.problem(F.SCHEMA_ENUM, f"{path}.classification",
                                 f"{where}: classification {self.classification!r} is not one of "
                                 f"{list(ARTIFACT_CLASS)}"))
        return out


@dataclasses.dataclass(frozen=True)
class Datum:
    """A geometric reference, and the evidence that makes it usable.

    [ADR 0003](../../../docs/adr/0003-datum-provenance-and-authority.md). The
    failure it was written from: a job coordinated two edit scopes across two
    artifacts by writing the same number into both, the source file was
    rewritten mid-job, and under the new revision that declaration produced
    three bosses that must not exist. Nothing detected it, for two reasons that
    are both fields here -- nothing recorded which revision the number had been
    measured on, and there were two copies of one number, so the second to be
    corrected was the one that shipped.

    So a datum is one object with an identity, and coordinated scopes reference
    it rather than each holding a copy. `valid_for` is the scope in which it may
    be used: 6.12 requires evidence to carry the scope it was taken in, and a
    datum is evidence.

    **An assumption is allowed and is labelled.** A number somebody picked is
    often the only way two artifacts can be coordinated before either is
    measured. The ADR does not forbid it; what it forbids is being unable to
    tell it from a measurement.

    **What this is not.** An `Interface` is the other shared thing two edit
    scopes name, and the two answer different questions. An interface says *that
    a mating surface exists between two artifacts and who owns the far side of
    it*; a datum says *what number an edit is placed against, where that number
    came from, and where it may be used*. Two scopes cutting one magnet pocket
    name the interface; the face they measure the pocket from is the datum. A
    datum may be scoped to an interface (`valid_for`), which is the only link
    between them, and it is a reference rather than a second copy.
    """

    datum_id: str
    value: Any
    unit: str
    # One of `PROVENANCE`, the same closed set every other design-driving value
    # uses -- or empty, which 6.4 names as the assumption case and permits. A
    # sixth *class* invented here would be a second vocabulary for one idea, and
    # 6.5's argument applies unchanged; the empty string is not a sixth class but
    # the absence of one, which is the distinction the ADR turns on.
    provenance: str
    # `{"artifact_id": ..., "revision": ...}` where the datum was read off
    # geometry, and None where it was not. A derived datum is valid against the
    # revision it was measured on and no later one.
    derived_from: dict[str, Any] | None = None
    # Which artifacts, components or interfaces this may be used to place. Each
    # entry must name a row the job declares -- see `Project.validate` -- because
    # a scope naming nothing is a scope no edit can ever satisfy.
    valid_for: tuple[str, ...] = ()
    # An assumption's two obligations, and only an assumption's. 6.4: it "is
    # named as an assumption, with an owner and with the check that would settle
    # it". Without them the status report lists a number nobody can act on,
    # which is exactly what a `note` already was.
    owner: str = ""
    settled_by: str = ""
    note: str = ""

    @property
    def is_assumption(self) -> bool:
        """A number nobody measured and nobody derived.

        Provenance decides it, and nothing else. Two cases, for the reason 6.4
        gives: a number with **no recorded provenance** is the assumption the ADR
        names outright, and `CHOSEN` -- engineering judgment -- is the same thing
        with a label on it. Neither is refused; both owe an owner and a check.

        This read `provenance == "CHOSEN" and not self.derived_from` until a
        mutation survived: no test could tell that from dropping the second
        clause, because a `CHOSEN` datum naming an artifact revision is already
        refused below. A second copy of that rule here would be a second
        authority over one question, which is the thing ADR 0003 is about.
        """
        return self.provenance == "CHOSEN" or not str(self.provenance).strip()

    def as_dict(self) -> dict[str, Any]:
        payload = dataclasses.asdict(self)
        payload["valid_for"] = list(self.valid_for)
        return payload

    def problems(self, index: int = 0) -> list[Issue]:
        where = f"datum {self.datum_id!r}"
        path = f"datums[{index}]"
        out: list[Issue] = []
        if not self.datum_id.strip():
            out.append(F.problem(F.SCHEMA_REQUIRED, f"{path}.datum_id",
                                 "a datum with no id cannot be referenced, and "
                                 "a datum nobody can reference is a copy"))
        # Empty is permitted and is the assumption 6.4 names; see
        # `is_assumption`. Anything else must be one of the closed set.
        if str(self.provenance).strip() and self.provenance not in PROVENANCE:
            out.append(F.problem(F.SCHEMA_ENUM, f"{path}.provenance",
                                 f"{where}: provenance {self.provenance!r} is "
                                 f"not one of {list(PROVENANCE)}"))

        # Required of `INHERITED`, permitted of `MEASURED`, refused of the rest,
        # and the three are different questions that one flag used to answer
        # wrongly.
        #
        # `INHERITED` means read out of a supplied artifact, so it always has a
        # revision to name -- the same shape `Requirement` uses, which requires
        # `artifact_id` on `INHERITED` and is silent elsewhere.
        #
        # `MEASURED` covers both of 6.5's measuring classes: off supplied
        # evidence, and off generated geometry. The second has a revision and the
        # first may not -- calipers on a physical part have no artifact revision
        # to invent -- so it is optional. It may not be *refused*: this rule read
        # `INHERITED` only, which meant the honest row recording the revision it
        # was measured on was rejected while the vague one validated clean, and
        # the only way to record the revision was to relabel the number
        # `INHERITED`, a provenance the value cannot support. That inverted the
        # incentive on precisely the class ADR 0003 was written from -- the
        # incident's bad field was measured off the job's own drawer.
        required = self.provenance == "INHERITED"
        may_carry = required or self.provenance == "MEASURED"
        if required and not isinstance(self.derived_from, dict):
            out.append(F.problem(
                F.SCHEMA_REQUIRED, f"{path}.derived_from",
                f"{where}: INHERITED means read out of a supplied artifact, and "
                "a datum that does not say which artifact at which revision is "
                "valid against nothing in particular"))
        elif isinstance(self.derived_from, dict):
            if not may_carry:
                out.append(F.problem(
                    F.INTENT_CONTRADICTION, f"{path}.derived_from",
                    f"{where}: provenance is {self.provenance!r} and it names an "
                    "artifact revision. A number nobody read off geometry has no "
                    "revision to be valid against, and claiming one is a "
                    "provenance the value cannot support"))
            if not str(self.derived_from.get("artifact_id", "")).strip():
                out.append(F.problem(F.SCHEMA_REQUIRED,
                                     f"{path}.derived_from.artifact_id",
                                     f"{where}: derived from which artifact?"))
            revision = self.derived_from.get("revision")
            if not isinstance(revision, int) or isinstance(revision, bool) \
                    or revision < 1:
                out.append(F.problem(
                    F.SCHEMA_TYPE, f"{path}.derived_from.revision",
                    f"{where}: revision {revision!r} is not a revision number. "
                    "This is the field the three bosses turned on"))

        # The number the whole construct exists to carry, checked the way
        # `Requirement` checks its own. A datum whose value is None is a
        # reference to nothing, and it used to validate clean: this block
        # checked the id, the provenance, the revision and the scope, and never
        # the number.
        if isinstance(self.value, bool) or self.value is None:
            out.append(F.problem(F.SCHEMA_TYPE, f"{path}.value",
                                 f"{where}: value must be a finite number or a "
                                 "non-empty string"))
        elif isinstance(self.value, (int, float)):
            try:
                S.require_finite_number(self.value, what=where)
            except S.SchemaError as exc:
                out.append(F.problem(F.SCHEMA_NON_FINITE, f"{path}.value",
                                     str(exc)))
            # Only where the value is a number. A datum naming a face rather
            # than a length has no unit, and requiring one would make it invent
            # one -- the same reasoning the revision field follows above.
            if not str(self.unit).strip():
                out.append(F.problem(
                    F.SCHEMA_REQUIRED, f"{path}.unit",
                    f"{where}: a number with no unit is a number two readers "
                    "can read differently, which 12 exists to stop"))
        elif not (isinstance(self.value, str) and self.value.strip()):
            out.append(F.problem(F.SCHEMA_TYPE, f"{path}.value",
                                 f"{where}: value must be a finite number or a "
                                 "non-empty string"))

        if not self.valid_for:
            out.append(F.problem(
                F.SCHEMA_REQUIRED, f"{path}.valid_for",
                f"{where}: a datum that may be used to place anything is a "
                "datum with no scope, and 6.12 requires evidence to carry the "
                "scope it was taken in"))

        # 6.4 permits the assumption and prices it. The obligation is the
        # assumption's alone: a measured or inherited number is already settled,
        # and asking it to name a settling check would make every honest datum
        # invent one.
        if self.is_assumption:
            for field, what in (("owner", "who resolves it"),
                                ("settled_by", "what resolving it means")):
                if not str(getattr(self, field)).strip():
                    out.append(F.problem(
                        F.SCHEMA_REQUIRED, f"{path}.{field}",
                        f"{where}: a number nobody measured is an assumption, "
                        f"and 6.4 names one with an owner and with the check "
                        f"that would settle it. This one does not say {what}, "
                        f"so it is a number in a list nobody can act on"))
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

    def problems(self, index: int = 0) -> list[Issue]:
        where = f"interface {self.interface_id!r}"
        path = f"interfaces[{index}]"
        out: list[Issue] = []
        if not self.interface_id.strip():
            out.append(F.problem(F.SCHEMA_REQUIRED, f"{path}.interface_id",
                                 "an interface with no id cannot be bound to a fit strategy"))
        if not isinstance(self.external, bool):
            out.append(F.problem(
                F.SCHEMA_TYPE, f"{path}.external",
                f"{where}: external must be true or false; whether the other "
                "side is somebody else's geometry is what decides the route"))
        if not self.owner.strip():
            out.append(F.problem(F.SCHEMA_REQUIRED, f"{path}.owner",
                                 f"{where}: owner must name who owns the mating geometry"))
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

    def problems(self, index: int = 0) -> list[Issue]:
        where = f"motion {self.motion_id!r}"
        path = f"motion[{index}]"
        out: list[Issue] = []
        if not self.motion_id.strip():
            out.append(F.problem(F.SCHEMA_REQUIRED, f"{path}.motion_id",
                                 "a motion with no id cannot be reported against"))
        if self.kind not in MOTION_KIND:
            out.append(F.problem(F.SCHEMA_ENUM, f"{path}.kind",
                                 f"{where}: kind {self.kind!r} is not one of {list(MOTION_KIND)}"))
        if not self.static:
            out.append(F.problem(F.SCHEMA_REQUIRED, f"{path}.static",
                                 f"{where}: name the static component ids"))
        if not self.moving:
            out.append(F.problem(F.SCHEMA_REQUIRED, f"{path}.moving",
                                 f"{where}: name the moving component ids"))
        overlap = set(self.static) & set(self.moving)
        if overlap:
            # Not SCHEMA_*: both fields are well-formed lists of ids and the
            # reader has to decide which body moves, not correct a spelling.
            out.append(F.problem(F.INTENT_CONTRADICTION, f"{path}.moving",
                                 f"{where}: {sorted(overlap)} are declared both static and "
                                 "moving, so no sweep can be defined"))
        return out


@dataclasses.dataclass(frozen=True)
class EditScope:
    """What a `MODIFY` job may touch in one artifact, and what it must leave alone.

    Written before the edit, like everything else here. The preservation audit in
    Phase 3 measures against this declaration; an edit scope written afterwards
    would be a description of what happened, not a gate.

    One scope is one artifact. A job that modifies two artifacts declares two
    scopes -- see `Project.edit_scopes` -- and the two are tied together by the
    `Interface` rows they name, not by a second kind of declaration.
    """

    artifact_id: str
    region: str
    # The named region is what a person reads; the box is what the preservation
    # audit measures against. Both, because a name alone cannot be compared and a
    # box alone cannot be argued with.
    region_box: dict[str, Any] | None = None
    preserve: tuple[str, ...] = ()
    may_remove: tuple[str, ...] = ()
    add: tuple[str, ...] = ()
    expected_body_delta: int = 0
    mesh_fallback_allowed: bool = False
    preserve_metadata: bool = True
    # Where this artifact's own coordinates sit in the job's frame. Two scopes
    # whose region boxes are written in one frame are already talking about one
    # datum; this is the field that makes that true rather than assumed.
    alignment_transform: Any = "identity"
    # Which declared `Interface` rows this edit realizes -- the shared datum
    # between two scopes. A magnet pocket cut into a case body and the matching
    # pocket cut into its drawer are two edits of one interface, and the
    # interface is what says they have to agree on where it is.
    #
    # Nothing new was invented for this. An `Interface` already carries a mating
    # surface and who owns the geometry on the other side of it, and a `Motion`
    # is already referenced the same way -- by id, from the row that takes part
    # in it. What was missing was only the reference itself: two scopes could sit
    # beside an interface with nothing saying they were its two sides, so the
    # agreement lived in a `note` a reader had to believe rather than in a field
    # a validator could check.
    #
    # This comment used to call an interface "the shared datum between two
    # scopes", which ADR 0003 made ambiguous. The two are different questions and
    # both are needed: an interface says *that* a mating surface exists between
    # two artifacts and who owns the far side; a `Datum` says *what number* an
    # edit is placed against, where it came from, and where it may be used. The
    # link between them is that a datum may be `valid_for` an interface, which is
    # how one number serves both sides of one feature.
    interface_ids: tuple[str, ...] = ()
    # Which declared `Datum` rows this edit is placed against. ADR 0003
    # decision 4: coordinated scopes that must agree on a reference name one
    # identity and do not each hold a copy, because two copies of a number are
    # two authorities over one declaration and the second one to be corrected is
    # the one that ships.
    datum_ids: tuple[str, ...] = ()
    # The band a sampled comparison may call unchanged. Two tessellations of one
    # surface disagree by the chord error of whichever is coarser, so this is not
    # zero -- and it is declared before the edit, like everything else here.
    preservation_tolerance_mm: float = 0.05
    # The smallest undeclared change this edit undertakes to find outside its
    # region. `preservation_tolerance_mm` is how far a sampled point may move
    # before it counts as movement; this is how *small a patch* the plan can see
    # at all, and the two are independent: a 0.05 mm band measured by a plan that
    # can only resolve 0.8 mm is a tight tolerance on a coarse detector, which is
    # exactly the combination that reads as a strong result and is not one.
    #
    # `None` means the job declared nothing and the audit falls back to its fixed
    # count, saying so. Optional rather than defaulted to a number because a
    # default here would be this file inventing a sensitivity on the job's behalf
    # -- and because a key that is always present would move every frozen
    # contract hash that predates it, for jobs that declare nothing new.
    minimum_detectable_defect_mm: float | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = dataclasses.asdict(self)
        for key in ("preserve", "may_remove", "add", "interface_ids",
                    "datum_ids"):
            payload[key] = list(getattr(self, key))
        return payload

    def canonical_alignment_transform(self) -> Any:
        """The transform in the one spelling a hash is allowed to depend on.

        `"identity"` stays the word it was declared as. A matrix is rounded to
        the places every other length in this pipeline is rounded to, because two
        spellings of one value -- `5.0` beside the `4.999999999999999` a kernel's
        own arithmetic produces, or `-0.0` beside `0.0` -- must not be two
        different contract hashes and two different sampling plans.

        A malformed matrix comes back verbatim rather than raising: `problems()`
        is what refuses it, and a hashing helper that threw first would turn a
        validation finding into a traceback.
        """
        matrix = self.alignment_transform
        if matrix == "identity":
            return "identity"
        try:
            return [[S.canonical_number(value, 6) for value in row]
                    for row in matrix]
        except (TypeError, S.SchemaError):
            return matrix

    @property
    def where(self) -> str:
        """How a problem's *sentence* names this scope.

        By artifact id, because `Project.validate` refuses two scopes over one
        artifact. With the duplicate refused the id names exactly one scope, and
        a problem nobody can attribute to a scope is a problem nobody can act on
        once there is more than one of them.

        This is the English a user reads. What a *caller* acts on is the finding's
        `where` field path -- `edit_scopes[1].region_box` -- which is the position
        in the file rather than the id in it, so a caller does not have to search
        the list to find the field the sentence is about. Both, for the same
        reason the scope carries both a named region and a box.
        """
        return f"edit_scope {self.artifact_id!r}"

    def problems(self, index: int = 0) -> list[Issue]:
        where = self.where
        path = f"edit_scopes[{index}]"
        out: list[Issue] = []
        if not self.artifact_id.strip():
            out.append(F.problem(F.SCHEMA_REQUIRED, f"{path}.artifact_id",
                                 f"{where}: artifact_id must name the source artifact being "
                                 "modified"))
        if not self.region.strip():
            out.append(F.problem(F.SCHEMA_REQUIRED, f"{path}.region",
                                 f"{where}: region must name the edit region; the preservation "
                                 "audit measures everything outside it"))
        box = self.region_box
        if box is None:
            out.append(F.problem(F.SCHEMA_REQUIRED, f"{path}.region_box",
                                 f"{where}: region_box is required -- 'outside the edit "
                                 "region' has no geometric meaning without one, and the "
                                 "preservation audit would have nothing to compare"))
        elif (not isinstance(box, dict)
              or not isinstance(box.get("min"), (list, tuple))
              or not isinstance(box.get("max"), (list, tuple))
              or len(box["min"]) != 3 or len(box["max"]) != 3):
            out.append(F.problem(F.SCHEMA_TYPE, f"{path}.region_box",
                                 f"{where}: region_box must be {{'min': [x, y, z], "
                                 "'max': [x, y, z]}"))
        else:
            for axis, (low, high) in enumerate(zip(box["min"], box["max"])):
                # Per axis, because a box can be empty on two of them at once and
                # `CODE@where` has to name one finding. `region_box` alone would
                # give both the same id, and an id two findings share is one a
                # caller cannot key on -- which is the whole reason for it.
                axis_path = f"{path}.region_box.{'xyz'[axis]}"
                try:
                    high_mm = S.require_finite_number(
                        high, what=f"{where}.region_box.max")
                    low_mm = S.require_finite_number(
                        low, what=f"{where}.region_box.min")
                    if high_mm <= low_mm:
                        out.append(F.problem(F.SCHEMA_RANGE, axis_path,
                                             f"{where}: region_box is empty on axis "
                                             f"{'xyz'[axis]}"))
                except S.SchemaError as exc:
                    out.append(F.problem(F.SCHEMA_NON_FINITE, axis_path, str(exc)))
        if self.preservation_tolerance_mm <= 0:
            out.append(F.problem(F.SCHEMA_RANGE, f"{path}.preservation_tolerance_mm",
                                 f"{where}: preservation_tolerance_mm must be positive; a "
                                 "zero band cannot be met by two tessellations of one surface"))
        if self.minimum_detectable_defect_mm is not None:
            size = self.minimum_detectable_defect_mm
            try:
                usable = (not isinstance(size, bool)
                          and S.require_finite_number(size, what="size") > 0)
            except (S.SchemaError, TypeError, ValueError):
                usable = False
            if not usable:
                out.append(F.problem(
                    F.SCHEMA_RANGE, f"{path}.minimum_detectable_defect_mm",
                    f"{where}: minimum_detectable_defect_mm must be a positive "
                    "finite length. It is the smallest undeclared change the "
                    "audit undertakes to find; a zero or absent size is a "
                    "sensitivity nobody declared, which is what the fallback "
                    "count already is."))
        if isinstance(self.expected_body_delta, bool) or \
                not isinstance(self.expected_body_delta, int):
            out.append(F.problem(F.SCHEMA_TYPE, f"{path}.expected_body_delta",
                                 f"{where}: expected_body_delta must be an integer"))
        if self.alignment_transform != "identity":
            matrix = self.alignment_transform
            ok = (isinstance(matrix, list) and len(matrix) == 4
                  and all(isinstance(row, list) and len(row) == 4 for row in matrix))
            if not ok:
                out.append(F.problem(F.SCHEMA_TYPE, f"{path}.alignment_transform",
                                     f"{where}: alignment_transform must be 'identity' or "
                                     "a 4x4 matrix"))
        if any(not isinstance(name, str) or not name.strip()
               for name in self.interface_ids):
            out.append(F.problem(F.SCHEMA_TYPE, f"{path}.interface_ids",
                                 f"{where}: interface_ids must be a list of non-empty "
                                 "interface ids"))
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

    def problems(self, index: int = 0) -> list[Issue]:
        path = f"components[{index}]"
        out: list[Issue] = []
        if not self.component_id.strip():
            out.append(F.problem(F.SCHEMA_REQUIRED, f"{path}.component_id",
                                 "a component with no id cannot appear in a manifest"))
        if isinstance(self.count, bool) or not isinstance(self.count, int) or self.count < 1:
            out.append(F.problem(F.SCHEMA_RANGE, f"{path}.count",
                                 f"component {self.component_id!r}: count must be at least 1"))
        return out


@dataclasses.dataclass(frozen=True)
class Alternative:
    """One competing formulation of the same job, and where it came from.

    A row, not a copy. Branching records that this formulation exists, who its
    ancestors are and why somebody started it; it duplicates no requirement, no
    source artifact and no evidence. Everything unchanged is still read from the
    one shared `project.json`, and what differs is whatever the alternative's own
    directory contains.

    `parents` is a list from the first commit that has it, and this slice never
    writes more than one entry. That is deliberate: a merge is a revision with
    two contributing parents (ARCHITECTURE.md 13.2), and a field that has to
    change shape to record one is a field every reader of the old shape has to be
    migrated off. Widening a list later is additive; widening a scalar is not.
    """

    alternative_id: str
    parents: tuple[str, ...] = ()
    reason: str = ""
    disposition: str = "ACTIVE"
    # Why it is in that state, and -- for the two terminal states that imply one
    # -- which formulation replaced it. `reason` is why this branch was *started*
    # and never changes; these two are why it is where it ended up, and they move
    # with every transition. One field for both would lose the first the moment
    # anything was paused.
    basis: str = ""
    superseded_by: str = ""

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"alternative_id": self.alternative_id,
                                   "parents": list(self.parents),
                                   "reason": self.reason,
                                   "disposition": self.disposition}
        # Absent while empty, which is the rule every optional key in this file
        # follows: an `ACTIVE` row serializes to exactly the bytes it did before
        # a basis existed, so no project in the corpus moves for a field it has
        # nothing to put in.
        if self.basis:
            payload["basis"] = self.basis
        if self.superseded_by:
            payload["superseded_by"] = self.superseded_by
        return payload

    def problems(self, index: int = 0) -> list[Issue]:
        where = f"alternative {self.alternative_id!r}"
        path = f"alternatives[{index}]"
        out: list[Issue] = []
        if not ALTERNATIVE_ID.match(self.alternative_id or ""):
            out.append(F.problem(
                F.SCHEMA_TYPE, f"{path}.alternative_id",
                f"{where}: alternative_id must match {ALTERNATIVE_ID.pattern} "
                "-- it becomes a directory name and is written into the "
                "execution plan and every review envelope, so an id two "
                "filesystems spell differently is one two receipts disagree "
                "about"))
        if self.disposition not in ALTERNATIVE_DISPOSITION:
            out.append(F.problem(F.SCHEMA_ENUM, f"{path}.disposition",
                                 f"{where}: disposition {self.disposition!r} is not one of "
                                 f"{list(ALTERNATIVE_DISPOSITION)}"))
        if not self.reason.strip():
            out.append(F.problem(
                F.SCHEMA_REQUIRED, f"{path}.reason",
                f"{where}: reason must say why this formulation exists. Two "
                "alternatives with no stated difference cannot be compared, "
                "and the one nobody can justify is the one that is kept by "
                "accident"))
        if any(not isinstance(parent, str) or not parent.strip()
               for parent in self.parents):
            out.append(F.problem(F.SCHEMA_TYPE, f"{path}.parents",
                                 f"{where}: parents must be a list of alternative ids"))
        out.extend(self._basis_problems(path, where))
        return out

    def _basis_problems(self, path: str, where: str) -> list[Issue]:
        """The disposition's own justification, refused when it is missing.

        A disposition that only labels is the defect it was supposed to fix with
        a nicer name -- `PAUSED` with nothing saying why is the same amount of
        information as `ACTIVE`, and the next person to read it has to guess
        whether the work was parked or abandoned. ARCHITECTURE.md 14.6 already
        required the basis; this is where the requirement bites.
        """
        out: list[Issue] = []
        if self.basis and self.basis not in DISPOSITION_BASIS:
            out.append(F.problem(F.SCHEMA_ENUM, f"{path}.basis",
                                 f"{where}: basis {self.basis!r} is not one of "
                                 f"{list(DISPOSITION_BASIS)}"))
        if self.disposition in BASIS_REQUIRED and not self.basis.strip():
            out.append(F.problem(
                F.SCHEMA_REQUIRED, f"{path}.basis",
                f"{where}: {self.disposition} must say what it rests on -- one of "
                f"{list(DISPOSITION_BASIS)}. A disposition with no basis records "
                "that somebody decided and not what they decided it on, which is "
                "the label this lifecycle exists to stop being"))
        if self.disposition in SUCCESSOR_REQUIRED and not self.superseded_by.strip():
            out.append(F.problem(
                F.SCHEMA_REQUIRED, f"{path}.superseded_by",
                f"{where}: {self.disposition} must name the formulation that "
                "replaced it. Without one this row says a better concept exists "
                "and gives no way to find it"))
        if self.superseded_by and self.disposition not in SUCCESSOR_REQUIRED:
            out.append(F.problem(
                F.INTENT_CONTRADICTION, f"{path}.superseded_by",
                f"{where}: superseded_by names {self.superseded_by!r} while the "
                f"disposition is {self.disposition}, which is not one of "
                f"{list(SUCCESSOR_REQUIRED)}"))
        if self.superseded_by and self.superseded_by == self.alternative_id:
            out.append(F.problem(
                F.REF_ORDER, f"{path}.superseded_by",
                f"{where}: a formulation cannot supersede itself"))
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
    datums: tuple[Datum, ...] = ()
    motion: tuple[Motion, ...] = ()
    components: tuple[Component, ...] = ()
    open_questions: tuple[OpenQuestion, ...] = ()
    # One scope per artifact being modified, and never a singular field beside
    # this one. Modifying a case body and its drawer together -- two artifacts,
    # two coordinated edits, one shared magnet-pocket datum -- had nowhere to be
    # declared while this was a single `EditScope | None`, which is the capability
    # gap `docs/adr/0002` records. Two authorities over the same declaration is
    # one authority and one bug, so there is no `edit_scope` alias: a payload
    # carrying the old key is refused by name rather than silently dropped.
    edit_scopes: tuple[EditScope, ...] = ()

    # The certified template, when one covers the shape, and the parameters it
    # takes. A `CUSTOM` job names a model source instead.
    template: str | None = None
    parameters: dict[str, Any] = dataclasses.field(default_factory=dict)
    model: str | None = None
    # The x/y/z the part is allowed to occupy. Required on CUSTOM: the print plan
    # is written before the geometry, and it cannot be written without knowing
    # the envelope. It is a design-driving value like any other -- stated by the
    # brief or chosen by design, and recorded as such in `requirements`.
    envelope_mm: dict[str, float] | None = None

    expected_artifacts: tuple[str, ...] = ()
    required_reviews: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    modifiers: tuple[str, ...] = ()
    interface_map: dict[str, str] = dataclasses.field(default_factory=dict)
    reviewer: dict[str, Any] = dataclasses.field(default_factory=dict)
    # The competing formulations of this job, in ancestry order, and which one is
    # being worked on. Both are absent from `as_payload` while the tuple is empty,
    # so a project that never branches carries no trace of the capability -- see
    # `as_payload`.
    alternatives: tuple[Alternative, ...] = ()
    active_alternative: str | None = None
    # An explicit ask for an independent look, from the user or the orchestrator.
    # It only ever adds a review; nothing reads it to remove one.
    verification_requested: bool = False
    step: bool = False
    cache_dir: str | None = None

    # There are deliberately no `status` and `bindings` fields any more. They
    # mirrored one run's outcome -- its stage, its final status, its allowed
    # claim and its artifact digests -- into the one file that has to be shared,
    # so the project said the job was whatever had finished last. Slice A already
    # had to stop a branch stamping them, which left the mirror true only of the
    # shared root and silently wrong the moment anybody read it while a branch
    # was active; the same argument that deleted `project_hash()` applies to the
    # values it was hashing. A formulation's outcome is `final_status.json` in
    # that formulation's own directory, and what is *current* is derived from the
    # bindings on disk (`bindings.py`, `status.derive`) rather than repeated from
    # a copy nothing keeps in step.
    #
    # Whether the job's geometry is externally owned was living in `status`, and
    # that is a declaration rather than an outcome, so it has its own field.
    # `None` means "nobody said", which is not the same as `False`: the legacy
    # adapter is told by `job.json`, and a canonical project is read off its
    # declared external interfaces.
    external_geometry: bool | None = None
    # Set by an adapter. `job.json@1` means the routing authority reproduces the
    # legacy answers rather than the new ones -- see `route.decide`.
    compat: str | None = None

    # -- serialization ----------------------------------------------------

    def as_payload(self) -> dict[str, Any]:
        """The canonical document, with the branching keys absent until they mean something.

        Absent, not null. A project that has never branched must serialize to
        exactly the bytes it serialized to before branching existed -- that is the
        whole of the zero-cost claim, and `"alternatives": []` beside
        `"active_alternative": null` would break it on every job in the corpus
        while saying nothing a reader did not already know. `review.py` had
        already written the opposite precedent with `execution_plan_sha256: None`;
        it is not followed here.
        """
        payload: dict[str, Any] = {
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
            "envelope_mm": self.envelope_mm,
            "requirements": [r.as_dict() for r in self.requirements],
            "source_artifacts": [a.as_dict() for a in self.source_artifacts],
            "interfaces": [i.as_dict() for i in self.interfaces],
            "motion": [m.as_dict() for m in self.motion],
            "components": [c.as_dict() for c in self.components],
            "open_questions": [q.as_dict() for q in self.open_questions],
            "edit_scopes": [s.as_dict() for s in self.edit_scopes],
            "expected_artifacts": list(self.expected_artifacts),
            "required_reviews": list(self.required_reviews),
            "evidence": list(self.evidence),
            "modifiers": list(self.modifiers),
            "interface_map": dict(self.interface_map),
            "reviewer": dict(self.reviewer),
            "verification_requested": self.verification_requested,
            "step": self.step,
            "cache_dir": self.cache_dir,
            "compat": self.compat,
        }
        if self.external_geometry is not None:
            # Absent when nobody said, following the rule every other optional
            # key here follows: a `null` in a serialized document is a statement
            # that somebody considered the question, and on a canonical project
            # the answer is read off the declared interfaces instead.
            payload["external_geometry"] = self.external_geometry
        # Absent until it means something, for the reason the docstring gives
        # about `alternatives`: a job that declares no datum must serialize to
        # exactly the bytes it did before ADR 0003 was implemented, or every
        # frozen contract hash in the corpus moves for a key saying nothing.
        if self.datums:
            payload["datums"] = [d.as_dict() for d in self.datums]
        if self.alternatives:
            payload["alternatives"] = [a.as_dict() for a in self.alternatives]
            payload["active_alternative"] = self.active_alternative
        return payload

    # There is deliberately no `project_hash()`. It hashed this whole payload --
    # `status` and `bindings` included, both of which every finished run
    # rewrites -- so it moved on writes that changed nothing anybody was bound
    # to, and it was read by nothing. A digest that always differs is one its
    # readers learn to ignore, and the next digest they are asked to check is the
    # one that mattered. What a designer commission needs to be bound to is the
    # half of the job nobody on the design side owns, and `cli._requirement_hash`
    # already computes exactly that and is already what the frozen acceptance
    # contract carries. Two digests over one declaration is one authority and one
    # bug, so the unread one is gone rather than repaired.

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

    def alternative(self, alternative_id: str | None) -> Alternative | None:
        for row in self.alternatives:
            if row.alternative_id == alternative_id:
                return row
        return None

    def work_dir(self, project_dir: Path) -> Path:
        """Where this job writes everything that belongs to one formulation.

        The project directory itself when no alternative is active, which is
        every project that has never branched: no subdirectory appears, no path
        component is added, and `candidate.stl` is still written where it always
        was. Once an alternative is active it is `alternatives/<id>`, and that
        one move is what makes sibling isolation structural rather than checked.
        Without it the second sibling's `acceptance.freeze` reads the first's
        contract as `previous`, cuts a revision, and `_invalidate` deletes the
        first's final status, commissioning report, artifact manifest,
        manufacturing report and both review reports -- which the first then does
        to the second on its next run, forever.

        Routed through `resolve_within` rather than joined: the id is validated
        text, and the one resolver that proves a name stays under a directory is
        the one every other declared path in this pipeline already goes through.
        """
        if not self.active_alternative:
            return Path(project_dir)
        return S.resolve_within(Path(project_dir),
                                f"{ALTERNATIVES_DIR}/{self.active_alternative}",
                                what="alternative directory")

    # -- validation -------------------------------------------------------

    def validate(self, project_dir: Path | None = None, *,
                 require_buildable: bool = True) -> list[Issue]:
        """Every reason this project cannot be routed or built, or an empty list.

        Deliberately a list rather than an exception: `design-tool init` writes a
        skeleton and prints these as the to-do list, and a caller filling one in
        wants all of them at once rather than one per round trip.

        Deliberately `Issue` rather than `str`, since Release 3 made status
        derived. "Why is this alternative not COMMISSIONED" is now a question
        asked of N formulations at once, and the answer has to be matchable: a
        `code` a caller branches on, a `where` naming the exact field
        (`edit_scopes[1].region_box`), a `severity`, and an `id` two runs agree
        on. The English is unchanged and is carried in `message` -- see
        `findings.problem` for why the sentence and the path are separate.

        The *order* is unchanged too, and is part of the contract: `init` prints
        this list as a to-do list, and a list that reshuffles between runs reads
        as a different set of problems.

        `require_buildable=False` drops the one problem that is a normal state
        rather than a defect: a `CUSTOM` job has no model until the designer
        commission produces one, and refusing to route it before then would make
        the commission unreachable.
        """
        problems: list[Issue] = []

        if not self.job_id.strip():
            problems.append(F.problem(F.SCHEMA_REQUIRED, "job_id",
                                      "job_id is required and must be a non-empty string"))
        if not self.updated_utc.strip():
            problems.append(F.problem(F.SCHEMA_REQUIRED, "updated_utc",
                                      "updated_utc is required; a wall-clock stamp would make "
                                      "two runs of one job differ in their bytes"))
        if self.source_mode not in SOURCE_MODE:
            problems.append(F.problem(F.SCHEMA_ENUM, "source_mode",
                                      f"source_mode {self.source_mode!r} is not one of "
                                      f"{list(SOURCE_MODE)}"))
        if self.consequence not in S.CONSEQUENCE:
            problems.append(F.problem(F.SCHEMA_ENUM, "consequence",
                                      f"consequence {self.consequence!r} is not one of "
                                      f"{list(S.CONSEQUENCE)}"))
        elif not self.consequence_rationale.strip():
            problems.append(F.problem(F.SCHEMA_REQUIRED, "consequence_rationale",
                                      "consequence_rationale is required: a class with no reason "
                                      "behind it cannot be re-checked when the job changes"))
        if self.route is not None and self.route not in ROUTE:
            problems.append(F.problem(F.SCHEMA_ENUM, "route",
                                      f"route {self.route!r} is not one of {list(ROUTE)}"))
        problems.extend(self._alternative_problems())

        if not isinstance(self.printer, str) or not self.printer.strip():
            problems.append(F.problem(F.SCHEMA_REQUIRED, "printer",
                                      "printer is required and must be a non-empty string"))
        material = self.material
        if (not isinstance(material, dict)
                or not isinstance(material.get("process"), str)
                or not material["process"].strip()
                or not isinstance(material.get("material"), str)
                or not material["material"].strip()):
            problems.append(F.problem(F.SCHEMA_TYPE, "material",
                                      "material must name non-empty process and material strings"))
        nozzle = self.nozzle
        diameter = nozzle.get("diameter_mm") if isinstance(nozzle, dict) else None
        if (not isinstance(diameter, (int, float)) or isinstance(diameter, bool)
                or diameter <= 0):
            problems.append(F.problem(F.SCHEMA_RANGE, "nozzle.diameter_mm",
                                      "nozzle.diameter_mm must be a positive number"))
        problems.extend(_orientation_problems(self.orientation))

        for name, value in sorted(self.parameters.items()):
            if not isinstance(name, str):
                problems.append(F.problem(F.SCHEMA_TYPE, "parameters",
                                          "parameters keys must be strings"))
                continue
            try:
                S.require_finite_number(value, what=f"parameters.{name}")
            except S.SchemaError as exc:
                problems.append(F.problem(F.SCHEMA_NON_FINITE, f"parameters.{name}",
                                          str(exc)))

        seen: set[str] = set()
        for index, requirement in enumerate(self.requirements):
            if requirement.name in seen:
                problems.append(F.problem(F.REF_DUPLICATE, f"requirements[{index}].name",
                                          f"requirement {requirement.name!r}: duplicate name -- "
                                          "two provenances for one value is no provenance"))
            seen.add(requirement.name)
            problems.extend(requirement.problems(index))
            if requirement.artifact_id and self.artifact(requirement.artifact_id) is None:
                problems.append(F.problem(F.REF_UNDECLARED, f"requirements[{index}].artifact_id",
                                          f"requirement {requirement.name!r}: artifact_id "
                                          f"{requirement.artifact_id!r} names no source artifact"))

        for index, artifact in enumerate(self.source_artifacts):
            problems.extend(artifact.problems(project_dir, index))
        # What a datum's `valid_for` may name: the rows a scope can be measured
        # against. ADR 0003 decision 3 says artifacts, components and interfaces,
        # and a scope naming none of them is a scope no edit can ever satisfy.
        placeable = ({row.artifact_id for row in self.source_artifacts}
                     | {row.component_id for row in self.components}
                     | {row.interface_id for row in self.interfaces})
        seen_datums: set[str] = set()
        for index, datum in enumerate(self.datums):
            problems.extend(datum.problems(index))
            if datum.datum_id in seen_datums:
                # ADR 0003 decision 4's precondition. An identity two rows
                # answer to is not an identity, and the whole mechanism is that
                # coordinated scopes reference *one* object.
                #
                # What this detects is the id collision, and only that. Two rows
                # holding one number under two ids validate clean; finding those
                # means comparing values, which is Release 6's job and not a
                # declaration check.
                problems.append(F.problem(
                    F.REF_DUPLICATE, f"datums[{index}].datum_id",
                    f"datum {datum.datum_id!r} is declared twice. An identity "
                    "two rows answer to is not one, and coordinated scopes "
                    "reference one object rather than each holding a copy"))
            seen_datums.add(datum.datum_id)
            # The field the ADR calls "the field that failed", and the one id
            # reference in this neighbourhood that had no referential check
            # while every other one did.
            derived_from = datum.derived_from
            if isinstance(derived_from, dict):
                named = str(derived_from.get("artifact_id", "")).strip()
                if named and self.artifact(named) is None:
                    problems.append(F.problem(
                        F.REF_UNDECLARED,
                        f"datums[{index}].derived_from.artifact_id",
                        f"datum {datum.datum_id!r} was derived from {named!r}, "
                        "which names no declared source artifact. A revision of "
                        "a file the job does not have is a revision nothing can "
                        "be checked against"))
            for position, scope_id in enumerate(datum.valid_for):
                if scope_id not in placeable:
                    problems.append(F.problem(
                        F.REF_UNDECLARED,
                        f"datums[{index}].valid_for[{position}]",
                        f"datum {datum.datum_id!r} is valid for {scope_id!r}, "
                        "which names no declared artifact, component or "
                        "interface. A scope nothing answers to is a scope no "
                        "edit can be inside"))
        for index, interface in enumerate(self.interfaces):
            problems.extend(interface.problems(index))
            if interface.motion_id and not any(m.motion_id == interface.motion_id
                                               for m in self.motion):
                problems.append(F.problem(F.REF_UNDECLARED, f"interfaces[{index}].motion_id",
                                          f"interface {interface.interface_id!r}: motion_id "
                                          f"{interface.motion_id!r} names no declared motion"))
        for index, motion in enumerate(self.motion):
            problems.extend(motion.problems(index))
        for index, component in enumerate(self.components):
            problems.extend(component.problems(index))

        if self.source_mode == "MODIFY":
            if not self.source_artifacts:
                problems.append(F.problem(F.INTENT_CONTRADICTION, "source_artifacts",
                                          "source_mode is MODIFY and no source artifact is "
                                          "declared; there is nothing authoritative to modify"))
            if not self.edit_scopes:
                problems.append(F.problem(F.INTENT_CONTRADICTION, "edit_scopes",
                                          "source_mode is MODIFY and edit_scopes is empty; "
                                          "without at least one edit_scope nothing can say "
                                          "what must be preserved"))
        scoped: set[str] = set()
        declared_interfaces = {i.interface_id for i in self.interfaces}
        declared_datums = {d.datum_id: d for d in self.datums}
        for index, scope in enumerate(self.edit_scopes):
            problems.extend(scope.problems(index))
            if self.artifact(scope.artifact_id) is None:
                problems.append(F.problem(F.REF_UNDECLARED, f"edit_scopes[{index}].artifact_id",
                                          f"{scope.where}: artifact_id names no source "
                                          "artifact"))
            if scope.artifact_id in scoped:
                problems.append(F.problem(F.REF_DUPLICATE, f"edit_scopes[{index}].artifact_id",
                                          f"{scope.where}: this artifact_id is declared "
                                          "twice -- two scopes over one artifact are two "
                                          "answers to 'what may this edit touch', and the "
                                          "preservation audit would measure the artifact "
                                          "against whichever region it read last"))
            scoped.add(scope.artifact_id)
            for position, interface_id in enumerate(scope.interface_ids):
                if interface_id not in declared_interfaces:
                    problems.append(F.problem(
                        F.REF_UNDECLARED,
                        f"edit_scopes[{index}].interface_ids[{position}]",
                        f"{scope.where}: interface_id {interface_id!r} "
                        "names no declared interface; a datum two edits "
                        "have to agree on cannot be one nothing declares"))
            # ADR 0003: a datum is one object, referenced. A scope may name one
            # that exists, and only inside the scope that datum declares itself
            # valid for -- a reference used one artifact over is the stale
            # reference the ADR was written from, moved sideways.
            for position, datum_id in enumerate(scope.datum_ids):
                at = f"edit_scopes[{index}].datum_ids[{position}]"
                datum = declared_datums.get(datum_id)
                if datum is None:
                    problems.append(F.problem(
                        F.REF_UNDECLARED, at,
                        f"{scope.where}: datum_id {datum_id!r} names no "
                        "declared datum. Two scopes agreeing on a reference "
                        "name one identity; a name nothing declares is a copy "
                        "with extra steps"))
                # Decision 3 names artifacts, components *and* interfaces, so
                # the match is against everything this scope is inside -- the
                # artifact it edits and the interfaces it realizes. Comparing
                # against `artifact_id` alone refused the coordinated case the
                # ADR is written for: a datum scoped to the interface two scopes
                # both realize was out of scope for both of them.
                elif not (set(datum.valid_for)
                          & ({scope.artifact_id} | set(scope.interface_ids))):
                    problems.append(F.problem(
                        F.INTENT_CONTRADICTION, at,
                        f"{scope.where}: datum {datum_id!r} is valid for "
                        f"{list(datum.valid_for)} and this scope edits "
                        f"{scope.artifact_id!r}. A datum used outside the scope "
                        "it was taken in is the stale reference ADR 0003 exists "
                        "to stop, one artifact over"))
        if self.source_mode == "NEW" and self.source_artifacts:
            problems.append(F.problem(F.INTENT_CONTRADICTION, "source_mode",
                                      "source_mode is NEW but source artifacts are declared; "
                                      "geometry inherited from a supplied file is MODIFY"))

        if self.envelope_mm is not None:
            envelope = self.envelope_mm
            if (not isinstance(envelope, dict) or sorted(envelope) != ["x", "y", "z"]):
                problems.append(F.problem(F.SCHEMA_TYPE, "envelope_mm",
                                          "envelope_mm must name x, y and z"))
            else:
                for axis, value in sorted(envelope.items()):
                    try:
                        if S.require_finite_number(
                                value, what=f"envelope_mm.{axis}") <= 0:
                            problems.append(F.problem(F.SCHEMA_RANGE, f"envelope_mm.{axis}",
                                                      f"envelope_mm.{axis} must be positive"))
                    except S.SchemaError as exc:
                        problems.append(F.problem(F.SCHEMA_NON_FINITE, f"envelope_mm.{axis}",
                                                  str(exc)))

        if require_buildable and self.template is None and self.model is None:
            # `where` is the first field the sentence names, which is the rule
            # this file follows wherever one problem constrains a pair: a
            # caller acting on it may fill in either, and a finding that named
            # neither would be one nothing could be keyed to.
            problems.append(F.problem(F.INTENT_INCOMPLETE, "template",
                                      "neither template nor model is named; nothing can be "
                                      "built until one of them is"))
        if self.model is not None and project_dir is not None:
            try:
                S.resolve_within(project_dir, self.model, what="model")
            except S.PathEscape as exc:
                problems.append(F.problem(F.ARTIFACT_PATH_UNSAFE, "model", str(exc)))

        for index, name in enumerate(self.evidence):
            if project_dir is not None:
                try:
                    S.resolve_within(project_dir, name, what="evidence")
                except S.PathEscape as exc:
                    problems.append(F.problem(F.ARTIFACT_PATH_UNSAFE, f"evidence[{index}]",
                                              str(exc)))
        return problems

    def _alternative_problems(self) -> list[Issue]:
        """The branching half, refused rather than worked around.

        Ancestry order is the whole of the acyclicity rule: a parent must be
        declared before the child that names it. `design-tool branch` appends, so
        the property holds by construction, and a hand-edited file that breaks it
        is refused here rather than sending a later ancestry walk round a loop.
        Checking order instead of running a cycle search also refuses a
        self-parent with the same sentence.
        """
        problems: list[Issue] = []
        declared: set[str] = set()
        for index, row in enumerate(self.alternatives):
            problems.extend(row.problems(index))
            if row.alternative_id in declared:
                problems.append(F.problem(
                    F.REF_DUPLICATE, f"alternatives[{index}].alternative_id",
                    f"alternative {row.alternative_id!r}: declared twice -- two rows "
                    "for one id are two answers to what its parents and disposition "
                    "are, and both name one directory"))
            for position, parent in enumerate(row.parents):
                if parent not in declared:
                    problems.append(F.problem(
                        F.REF_ORDER, f"alternatives[{index}].parents[{position}]",
                        f"alternative {row.alternative_id!r}: parent {parent!r} is "
                        "not declared before it. Alternatives are recorded in "
                        "ancestry order, which is what makes this list a graph with "
                        "no cycles rather than one that has to be walked to find out"))
            declared.add(row.alternative_id)

        problems.extend(self._disposition_problems())

        if self.active_alternative is not None:
            active = self.alternative(self.active_alternative)
            if active is None:
                problems.append(F.problem(
                    F.REF_UNDECLARED, "active_alternative",
                    f"active_alternative {self.active_alternative!r} names no declared "
                    "alternative; the job would write its receipts into a directory "
                    "nothing in the project describes"))
            elif active.disposition not in RUNNABLE_DISPOSITION:
                problems.append(F.problem(
                    F.INTENT_UNSUPPORTED, "active_alternative",
                    f"active_alternative {self.active_alternative!r} is "
                    f"{active.disposition}, and only {list(RUNNABLE_DISPOSITION)} may "
                    "be worked under. "
                    + ("Resume it first (`design-tool branch --disposition ACTIVE "
                       f"--of {self.active_alternative} --basis USER_SELECTION`); "
                       "a run that silently continued a paused formulation would be "
                       "a pause that paused nothing"
                       if active.disposition == "PAUSED" else
                       f"{active.disposition} says this formulation is finished "
                       "with; branch a new one from it rather than reopening it in "
                       "place, which would rewrite the history it is the record of")))
        return problems

    def _disposition_problems(self) -> list[Issue]:
        """The rules one row cannot see, because they are about the set.

        Two of them, and each removes a way for the lifecycle to hold two answers
        to one question: which formulation is the job's answer, and whether a
        claimed merge is in the graph at all.
        """
        problems: list[Issue] = []
        by_id = {row.alternative_id: row for row in self.alternatives}
        preferred = [(index, row) for index, row in enumerate(self.alternatives)
                     if row.disposition == "PREFERRED"]
        for index, row in preferred[1:]:
            problems.append(F.problem(
                F.REF_DUPLICATE, f"alternatives[{index}].disposition",
                f"alternative {row.alternative_id!r} is PREFERRED and so is "
                f"{preferred[0][1].alternative_id!r}. Two preferred formulations "
                "are two answers to what this job's design is; switch with "
                "`design-tool branch --disposition PREFERRED`, which demotes the "
                "previous one to ACTIVE rather than leaving both standing"))

        for index, row in enumerate(self.alternatives):
            if not row.superseded_by or row.superseded_by == row.alternative_id:
                continue
            successor = by_id.get(row.superseded_by)
            if successor is None:
                problems.append(F.problem(
                    F.REF_UNDECLARED, f"alternatives[{index}].superseded_by",
                    f"alternative {row.alternative_id!r}: superseded_by "
                    f"{row.superseded_by!r} names no declared alternative"))
            elif (row.disposition == "MERGED"
                  and row.alternative_id not in successor.parents):
                problems.append(F.problem(
                    F.REF_UNDECLARED, f"alternatives[{index}].superseded_by",
                    f"alternative {row.alternative_id!r} is MERGED into "
                    f"{row.superseded_by!r}, and {row.superseded_by!r} does not "
                    f"list it among its parents. A merge is a revision with "
                    "several contributing parents (ARCHITECTURE.md 13.2); until "
                    "one records it, MERGED is a label over a graph that shows no "
                    "merge -- and this build does not perform merges, so the row "
                    "has to be written before the state can be claimed"))
        return problems


def _orientation_problems(orientation: Any) -> list[Issue]:
    problems: list[Issue] = []
    matrix = orientation.get("model_to_printer_matrix") if isinstance(orientation, dict) else None
    ok = matrix == "identity" or (
        isinstance(matrix, list) and len(matrix) == 4
        and all(isinstance(row, list) and len(row) == 4
                and all(isinstance(value, (int, float)) and not isinstance(value, bool)
                        for value in row)
                for row in matrix))
    if not ok:
        problems.append(F.problem(F.SCHEMA_TYPE, "orientation.model_to_printer_matrix",
                                  "orientation.model_to_printer_matrix must be 'identity' or a "
                                  "4x4 matrix"))
    bed_z = orientation.get("bed_z_mm") if isinstance(orientation, dict) else None
    if not isinstance(bed_z, (int, float)) or isinstance(bed_z, bool):
        problems.append(F.problem(F.SCHEMA_TYPE, "orientation.bed_z_mm",
                                  "orientation.bed_z_mm must be a number"))
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

    # Refused by name rather than read. A payload written against the singular
    # field describes a job this schema still supports, so dropping the key in
    # silence would lose the one declaration that says what must be preserved --
    # and reading it would restore the second authority the plural field exists
    # to remove.
    if "edit_scope" in payload:
        raise S.SchemaError(
            "edit_scope is not a field of this schema: a project declares "
            "edit_scopes, a list, so that a job modifying two artifacts has "
            "somewhere to say so. Move the object into a one-element list.")

    # `SINGLE` is read and dropped; it was the only value with no claim in it, it
    # sits in every project.json this build has ever written, and refusing it
    # would break every one of them to remove a word. `PARALLEL` is refused by
    # name, because dropping it in silence is what it did already: it was
    # validated, stored, hashed, and produced exactly one extra sentence in the
    # route rationale while nothing generated, isolated or compared a second
    # candidate.
    strategy = payload.get("candidate_strategy")
    if strategy not in (None, "SINGLE"):
        raise S.SchemaError(
            f"candidate_strategy {strategy!r} is not a field of this schema. It "
            "never produced a second candidate -- its whole effect was one more "
            "line in the route rationale, so a project could declare parallel "
            "concepts and receive one concept with a longer explanation. Competing "
            "formulations are declared with `design-tool branch`, which gives each "
            "one its own directory, its own acceptance revision and its own review "
            "bindings.")
    edit_scopes = tuple(
        EditScope(
            artifact_id=str(edit.get("artifact_id", "")),
            region=str(edit.get("region", "")),
            region_box=edit.get("region_box"),
            preservation_tolerance_mm=float(
                edit.get("preservation_tolerance_mm", 0.05)),
            minimum_detectable_defect_mm=edit.get("minimum_detectable_defect_mm"),
            preserve=tuple(edit.get("preserve") or ()),
            may_remove=tuple(edit.get("may_remove") or ()),
            add=tuple(edit.get("add") or ()),
            expected_body_delta=edit.get("expected_body_delta", 0),
            mesh_fallback_allowed=bool(edit.get("mesh_fallback_allowed", False)),
            preserve_metadata=bool(edit.get("preserve_metadata", True)),
            alignment_transform=edit.get("alignment_transform", "identity"),
            interface_ids=_ids(edit.get("interface_ids"),
                               f"edit_scopes[{index}].interface_ids"),
            datum_ids=_ids(edit.get("datum_ids"),
                           f"edit_scopes[{index}].datum_ids"))
        for index, edit in enumerate(
            _rows(payload.get("edit_scopes"), "edit_scopes")))

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
        envelope_mm=payload.get("envelope_mm"),
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
        datums=tuple(
            Datum(datum_id=str(row.get("datum_id", "")),
                  value=row.get("value"),
                  unit=str(row.get("unit", "")),
                  provenance=str(row.get("provenance", "")),
                  derived_from=(row.get("derived_from")
                                if isinstance(row.get("derived_from"), dict)
                                else None),
                  # `_ids`, like every other id list here. `tuple("case-body")`
                  # is nine scopes, and a malformed declaration that recorded
                  # nine bogus ones read as a clean datum.
                  valid_for=_ids(row.get("valid_for"),
                                 f"datums[{index}].valid_for"),
                  owner=str(row.get("owner", "")),
                  settled_by=str(row.get("settled_by", "")),
                  note=str(row.get("note", "")))
            for index, row in enumerate(_rows(payload.get("datums"), "datums"))),
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
        edit_scopes=edit_scopes,
        expected_artifacts=tuple(payload.get("expected_artifacts") or ()),
        required_reviews=tuple(payload.get("required_reviews") or ()),
        evidence=tuple(payload.get("evidence") or ()),
        modifiers=tuple(payload.get("modifiers") or ()),
        interface_map=dict(payload.get("interface_map") or {}),
        reviewer=dict(payload.get("reviewer") or {}),
        alternatives=tuple(
            Alternative(alternative_id=str(row.get("alternative_id", "")),
                        parents=_ids(row.get("parents"),
                                     f"alternatives[{index}].parents"),
                        reason=str(row.get("reason", "")),
                        disposition=str(row.get("disposition") or "ACTIVE"),
                        basis=str(row.get("basis") or ""),
                        superseded_by=str(row.get("superseded_by") or ""))
            for index, row in enumerate(
                _rows(payload.get("alternatives"), "alternatives"))),
        active_alternative=payload.get("active_alternative"),
        verification_requested=bool(payload.get("verification_requested", False)),
        step=bool(payload.get("step", False)),
        cache_dir=payload.get("cache_dir"),
        external_geometry=_external_geometry(payload),
        compat=payload.get("compat"),
    )


def _external_geometry(payload: dict[str, Any]) -> bool | None:
    """Whether the job's geometry is externally owned, from either spelling.

    `status` and `bindings` are gone from this schema, and unlike `edit_scope`
    and `candidate_strategy` they are not refused by name. Those two were
    *declarations*, and dropping a declaration in silence loses what somebody
    wrote; `status` and `bindings` were a run's own outcome stamped back into the
    shared file, so a document carrying them is carrying a copy of something that
    is on disk in its own right. Refusing them would make every project this
    build has ever written unloadable in order to remove a mirror.

    One value in there was not an outcome. `from_job_json` recorded
    `external_geometry` in `status`, and `route.decide` and
    `to_job_request_fields` both read it back, so dropping the key in silence
    would re-route every legacy job. It is read from either place, the field
    winning, and it is the only thing that survives the mirror.
    """
    declared = payload.get("external_geometry")
    if isinstance(declared, bool):
        return declared
    mirrored = payload.get("status")
    if isinstance(mirrored, dict) and isinstance(mirrored.get("external_geometry"), bool):
        return bool(mirrored["external_geometry"])
    return None


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
    strategy = spec.get("candidate_strategy")
    if strategy not in (None, "SINGLE"):
        raise S.SchemaError(
            f"job.json candidate_strategy {strategy!r} is not a field this build "
            "reads. It never produced a second candidate; competing formulations "
            "are declared with `design-tool branch` on a canonical project.")
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
        step=bool(spec.get("step", False)),
        cache_dir=spec.get("cache_dir"),
        compat="job.json@1",
        external_geometry=external,
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
        "external_geometry": bool(project.external_interfaces
                                  if project.external_geometry is None
                                  else project.external_geometry),
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
