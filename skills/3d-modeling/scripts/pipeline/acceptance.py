#!/usr/bin/env python3
"""The design proposal, and the acceptance contract frozen from it.

**The defect this replaces.** `EXPECTED`, `BBOX_MM`, `BODIES`, `VOLUME_MM3` and
`PROFILE_MARKS` used to be read out of `model.py` on every run, and the contract
was overwritten with whatever was found. A designer could read a failure, widen
the expectation and be commissioned on the next run with nothing recording that
the expectation had moved. Demonstrated, not argued: a model declaring a 24x18
pad, building a 10x8 one, with a self-declared `{"abs": 500.0}` band on that row,
was commissioned `PASS` on a 352 mm2 miss.

So the two things a designer used to write in one file are separated by *who owns
them* rather than by taste:

* the **design proposal** (`design_proposal.json`) -- what the designer proposes
  to build, in their own numbers. Geometry declarations only: a feature's
  position and size, the bounding box, the body count, the heights the shape
  legitimately steps at;
* the **acceptance contract** (`acceptance_contract.json`) -- generated *here*,
  from the frozen proposal and the system-owned inputs, and written to disk
  before the builder runs.

**What makes it structural rather than checked.** `generate` takes a proposal,
hashes of the job's fixed inputs, the print plan's own rows and the plan's gates.
There is no parameter it could be handed a mesh, a build result or a measurement
through, and this module imports no analysis module, no backend and no
commissioning code -- `test_phase2.AcceptanceIsUpstreamTest` asserts both, because
a rule this easy to break quietly is not a rule unless something checks it. A
tolerance cannot travel from the proposal into the
contract either: `_row` copies a whitelist of geometry fields per kind and
`tolerance` is in no whitelist, so there is no path from the designer's number to
the gate rather than a validator standing in front of one.

**Revisions, never overwrites.** A freeze that generates the same body as the one
on disk leaves the file alone. A freeze that generates a different body writes a
new revision, records in `acceptance_history.json` what moved and what the
superseded revision had claimed, and deletes the receipts bound to it -- the
artifact manifest, the commissioning report, the manufacturing report, both
review reports and the final status. A designer may still change their mind about
what the part should be. They cannot do it invisibly, and they cannot do it while
keeping the receipt that was issued against the old expectation.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

from . import contract as C
from . import schemas as S

PROPOSAL_SCHEMA = 1
ACCEPTANCE_SCHEMA = 1
HISTORY_SCHEMA = 1

PROPOSAL_FILE = "design_proposal.json"
ACCEPTANCE_FILE = "acceptance_contract.json"
HISTORY_FILE = "acceptance_history.json"

# Everything a run writes that only means something against one acceptance
# revision. A bump deletes them and records their digests in the history, so a
# superseded pass cannot be read as a current one and cannot be read as never
# having happened either.
INVALIDATED_BY_A_NEW_REVISION = (
    "artifact_manifest.json", "commission_report.json", "manufacturing_report.json",
    "safety_verification_report.json", "verification_report.json",
    "final_status.json",
)

# Where an expected solid volume may legitimately come from. Five sources and one
# admission -- ADR 0002 section 3. There is no universal second-party source for
# a novel `CUSTOM` part, and inventing one would restore the shape of the
# certified lane's screen without restoring its substance: a number the
# designer's own proposal informed is not an independent expectation, it is the
# same defect with an extra hop.
VOLUME_BASIS = (
    "CERTIFIED_TEMPLATE",
    "ANALYTIC_FROM_FROZEN_PROPOSAL",
    "IMMUTABLE_SOURCE_PLUS_BOUNDED_DELTA",
    "PREVIOUSLY_APPROVED_REVISION",
    "INDEPENDENT_VERIFIER_BOUND",
    "NOT_INDEPENDENTLY_SPECIFIED",
)

# What a proposal may declare, and exactly which fields of each survive into the
# contract. A kind that is not a key here is not proposable, and a field that is
# not in its tuple has no route from the proposal to the gate.
#
# `tolerance` is deliberately in none of them. So are `overhang`, `preservation`
# and `fit_acceptance`: the support ceiling comes from the print plan, the
# preservation row from the declared edit scope and the fit row from the bounded
# external measurement. All three are rows about what somebody else owns, and a
# candidate that could write them would be setting its own ceiling again.
PROPOSABLE = {
    "section_area": ("at", "value_mm2"),
    "bed_contact": ("value_mm2",),
    "through_hole": ("at", "d_mm", "z_from", "z_to"),
    "bore_by_displacement": ("at", "d_mm", "enclosing_d_mm", "z"),
    "void_region": ("at", "z", "size_mm"),
}

ACCEPTANCE_VERSION_PREFIX = "authored-r"


class ProposalError(S.SchemaError):
    """The design proposal cannot be frozen as written."""


# ---------------------------------------------------------------------------
# The proposal
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class DesignProposal:
    """What the designer proposes to build, reduced to what may be gated on."""

    job_id: str
    design_id: str
    rationale: str
    params: dict[str, Any]
    bbox_mm: dict[str, float]
    bodies: int
    features: tuple[dict[str, Any], ...]
    profile_marks: dict[str, list[float]]

    def as_payload(self) -> dict[str, Any]:
        return {
            "schema_version": PROPOSAL_SCHEMA,
            "job_id": self.job_id,
            "design_id": self.design_id,
            "rationale": self.rationale,
            "params": dict(self.params),
            "bbox_mm": dict(self.bbox_mm),
            "bodies": self.bodies,
            "features": [dict(row) for row in self.features],
            "profile_marks": {"z": list(self.profile_marks.get("z", ()))},
        }

    def proposal_hash(self) -> str:
        """The hash of the parsed proposal, not of the file's bytes.

        Reformatting `design_proposal.json` must not bump a revision: the
        revision exists to record that an *expectation* moved, and a reader who
        learns that a whitespace edit moved one stops believing the ones that
        matter.
        """
        return S.payload_hash(self.as_payload())


def _finite(value: Any, what: str) -> float:
    try:
        return S.require_finite_number(value, what=what)
    except S.SchemaError as exc:
        raise ProposalError(str(exc)) from None


def _numbers(value: Any, what: str) -> dict[str, float]:
    if not isinstance(value, dict):
        raise ProposalError(f"{what} must be an object of finite numbers")
    return {str(key): _finite(item, f"{what}.{key}") for key, item in value.items()}


def _text(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProposalError(f"{what} must be a non-empty string")
    return value


def _clean(value: Any, what: str) -> Any:
    """A JSON value with every number checked finite, and nothing else in it.

    Applied to the geometry fields a proposal is allowed to carry. `NaN` is a
    real JSON-parseable float in Python and it poisons every arithmetic
    consequence downstream, so it is refused where the number enters rather than
    where it is eventually compared.
    """
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return _finite(value, what)
    if isinstance(value, (list, tuple)):
        return [_clean(item, f"{what}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, dict):
        return {str(key): _clean(item, f"{what}.{key}")
                for key, item in sorted(value.items())}
    raise ProposalError(f"{what}: {type(value).__name__} is not a JSON value")


def from_payload(payload: Any) -> DesignProposal:
    """Parse a proposal payload, refusing shapes rather than coercing them."""
    if not isinstance(payload, dict):
        raise ProposalError(f"{PROPOSAL_FILE} must be a JSON object")
    version = payload.get("schema_version")
    if version != PROPOSAL_SCHEMA:
        raise ProposalError(
            f"{PROPOSAL_FILE} schema_version {version!r} is not {PROPOSAL_SCHEMA}; a "
            "reader that guesses at an unknown version is indistinguishable from one "
            "that read it correctly")

    params = payload.get("params")
    if not isinstance(params, dict) or not params:
        raise ProposalError("params must be a non-empty object: the numbers the "
                            "shape is built from")
    for key, value in params.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            _finite(value, f"params.{key}")

    bbox = _numbers(payload.get("bbox_mm"), "bbox_mm")
    if sorted(bbox) != ["x", "y", "z"] or any(v <= 0 for v in bbox.values()):
        raise ProposalError("bbox_mm must be positive in x, y and z")

    bodies = payload.get("bodies", 1)
    if isinstance(bodies, bool) or not isinstance(bodies, int) or bodies < 1:
        raise ProposalError("bodies must be a whole number of at least 1")

    rows = payload.get("features")
    if not isinstance(rows, list) or not rows:
        raise ProposalError(
            "features must be a non-empty list. A contract that requires nothing of "
            "the solid cannot fail, and a gate that cannot fail is not one.")

    features: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ProposalError(f"features[{index}] must be an object")
        feature_id = row.get("feature_id")
        kind = row.get("kind")
        if not isinstance(feature_id, str) or not feature_id.strip():
            raise ProposalError(f"features[{index}] must carry a non-empty feature_id")
        if feature_id in seen:
            raise ProposalError(f"features: duplicate feature_id {feature_id!r} -- "
                                "receipts could not name which one")
        seen.add(feature_id)
        if kind not in PROPOSABLE:
            raise ProposalError(
                f"features[{index}] kind {kind!r} is not one a proposal may declare. "
                f"Proposable: {sorted(PROPOSABLE)}. The support ceiling comes from the "
                "print plan, the preservation row from the declared edit scope and the "
                "fit row from the bounded external measurement; a proposal that could "
                "write those would be setting its own ceiling again.")
        if "tolerance" in row:
            raise ProposalError(
                f"features[{index}] declares a tolerance. Acceptance bands are "
                "system-owned: a threshold authored by the party being measured is a "
                "receipt rather than a gate, and a 500 mm2 band on a 432 mm2 feature "
                "is how a 352 mm2 miss was commissioned PASS.")
        missing = [field for field in PROPOSABLE[kind] if field not in row]
        if missing:
            raise ProposalError(
                f"features[{index}] ({kind}) is missing {', '.join(missing)}")
        features.append({
            "feature_id": feature_id, "kind": kind,
            "note": str(row.get("note", "")),
            **{field: _clean(row[field], f"features[{index}].{field}")
               for field in PROPOSABLE[kind]},
        })

    marks = payload.get("profile_marks") or {}
    if not isinstance(marks, dict):
        raise ProposalError("profile_marks must be an object like {'z': [6.0]}")
    if "volume_mm3" in payload:
        raise ProposalError(
            "a proposal may not declare volume_mm3. The volume screen is calibrated "
            "by an expectation from somewhere other than the thing being screened, "
            "and the designer's own number is not one -- see VOLUME_BASIS. Where no "
            "independent source exists the contract records "
            "NOT_INDEPENDENTLY_SPECIFIED and the detector reports NOT_APPLICABLE, "
            "which is worse-looking and more honest than a screen that clears itself.")

    return DesignProposal(
        job_id=str(payload.get("job_id", "")),
        design_id=_text(payload.get("design_id"), "design_id"),
        rationale=str(payload.get("rationale", "")),
        params=dict(params), bbox_mm=bbox, bodies=bodies,
        features=tuple(features),
        profile_marks={"z": [_finite(v, "profile_marks.z")
                             for v in (marks.get("z") or ())]},
    )


def load_proposal(path: Path) -> DesignProposal:
    path = Path(path)
    if not path.is_file():
        raise ProposalError(f"no such design proposal: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise ProposalError(f"{path.name} is not valid UTF-8: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ProposalError(f"{path.name} is not valid JSON: {exc}") from exc
    return from_payload(payload)


# ---------------------------------------------------------------------------
# Generating the contract
# ---------------------------------------------------------------------------

def _tolerance(kind: str, row: dict[str, Any]) -> dict[str, Any]:
    """The system's own band for a row, keyed on what the row measures.

    The one place a number the designer wrote could have become the band it is
    judged against, and the only inputs are the kind and the expected magnitude.
    """
    if kind in ("section_area", "bed_contact"):
        return C.area_tolerance(float(row["value_mm2"]))
    if kind in ("through_hole", "bore_by_displacement"):
        return C.diameter_tolerance(float(row["d_mm"]))
    return {"abs": 1.0}


def _row(row: dict[str, Any]) -> dict[str, Any]:
    """One frozen acceptance row: whitelisted geometry, system-owned band."""
    kind = row["kind"]
    return {
        "feature_id": row["feature_id"],
        "kind": kind,
        "note": row.get("note") or "declared in the frozen design proposal",
        "tolerance": _tolerance(kind, row),
        **{field: row[field] for field in PROPOSABLE[kind]},
    }


def generate(*, proposal: DesignProposal, job_id: str, route: str,
             requirement_sha256: str, source_artifact_sha256: dict[str, str],
             print_plan_sha256: str | None,
             print_plan_features: tuple[dict[str, Any], ...],
             preservation_features: tuple[dict[str, Any], ...],
             route_gates: dict[str, Any],
             expected_artifacts: dict[str, Any],
             expected_volume_mm3: float | None,
             expected_volume_basis: str,
             bbox_tolerance_mm: float = 0.5,
             minimum_coverage: float = 1.0) -> dict[str, Any]:
    """The contract body, from the frozen proposal and system-owned inputs only.

    Every parameter here exists before any geometry does. There is deliberately
    no way to pass a mesh, a build result or a measurement: the ordering that
    makes one-agent `CUSTOM` safe is that this runs, and its result reaches disk,
    before `model.py` is executed at all.
    """
    S.require_enum(expected_volume_basis, VOLUME_BASIS,
                   what="expected_volume_basis")
    return {
        "schema_version": ACCEPTANCE_SCHEMA,
        "job_id": job_id,
        "route": route,
        "design_id": proposal.design_id,
        "proposal_sha256": proposal.proposal_hash(),
        "requirement_sha256": requirement_sha256,
        "source_artifact_sha256": dict(sorted(source_artifact_sha256.items())),
        "print_plan_sha256": print_plan_sha256,
        "parameters": dict(proposal.params),
        "expected_bbox_mm": dict(proposal.bbox_mm),
        "expected_bodies": proposal.bodies,
        # System-owned, and named as such on the receipt. The band on every row
        # below is computed here from the row's own magnitude; the envelope band
        # and the coverage floor are constants of the pipeline. None of the three
        # is readable out of the proposal.
        "tolerance_owner": "pipeline",
        "bbox_tolerance_mm": bbox_tolerance_mm,
        "minimum_coverage": minimum_coverage,
        "features": ([_row(row) for row in proposal.features]
                     + [dict(row) for row in print_plan_features]
                     + [dict(row) for row in preservation_features]),
        "profile_marks": {"z": sorted(set(proposal.profile_marks.get("z", ())))},
        "expected_volume_mm3": expected_volume_mm3,
        "expected_volume_basis": expected_volume_basis,
        "route_gates": dict(sorted(route_gates.items())),
        "expected_artifacts": dict(sorted(expected_artifacts.items())),
    }


# ---------------------------------------------------------------------------
# Freezing, and what a new revision invalidates
# ---------------------------------------------------------------------------

def _differences(old: Any, new: Any, path: str = "") -> list[str]:
    """Which dotted fields moved, so the history says what changed and not that."""
    if isinstance(old, dict) and isinstance(new, dict):
        out: list[str] = []
        for key in sorted(set(old) | set(new)):
            where = f"{path}.{key}" if path else str(key)
            if key not in old:
                out.append(f"{where} added")
            elif key not in new:
                out.append(f"{where} removed")
            else:
                out += _differences(old[key], new[key], where)
        return out
    if isinstance(old, list) and isinstance(new, list):
        out = []
        for index in range(max(len(old), len(new))):
            where = f"{path}[{index}]"
            if index >= len(old):
                out.append(f"{where} added")
            elif index >= len(new):
                out.append(f"{where} removed")
            else:
                out += _differences(old[index], new[index], where)
        return out
    if old != new:
        return [f"{path or 'contract'}: {old!r} -> {new!r}"]
    return []


@dataclasses.dataclass(frozen=True)
class Frozen:
    """The acceptance contract as it now stands on disk."""

    path: Path
    payload: dict[str, Any]
    revision: int
    contract_sha256: str
    # What this freeze did: `FROZEN` on the first one, `UNCHANGED` when the
    # generated body matched what was already there, `SUPERSEDED` when it did not
    # and a revision was cut.
    disposition: str
    changed: tuple[str, ...] = ()
    invalidated: dict[str, Any] = dataclasses.field(default_factory=dict)

    @property
    def version(self) -> str:
        return f"{ACCEPTANCE_VERSION_PREFIX}{self.revision}"


def _body(payload: dict[str, Any]) -> dict[str, Any]:
    """The part of a stored contract that a regeneration is compared against.

    The revision, the stamp and the contract's own hash are consequences of the
    freeze rather than statements about the part, so comparing them would make
    every run a new revision.
    """
    return {key: value for key, value in payload.items()
            if key not in ("revision", "frozen_utc", "contract_sha256")}


def _invalidate(project_dir: Path) -> dict[str, Any]:
    """Remove the receipts the superseded revision issued, recording them first.

    Deleting rather than leaving them: `final_status.json` is what a reader and
    `design-tool status` treat as the job's answer, and an answer measured
    against an expectation that has since moved is worse than no answer. Their
    digests go into the history, so a superseded pass is neither current nor
    erased.
    """
    removed: dict[str, Any] = {}
    for name in INVALIDATED_BY_A_NEW_REVISION:
        path = project_dir / name
        if not path.is_file():
            continue
        removed[name] = S.sha256_file(path)
        path.unlink()
    return removed


def freeze(project_dir: Path, body: dict[str, Any], *, updated_utc: str) -> Frozen:
    """Write the contract if it is new, keep it byte-for-byte if it is not.

    Called before the builder, from the CLI, and never from `runner.py` -- the
    module that executes the model has no function that can write an acceptance
    contract, which is what makes "the candidate cannot influence its own
    acceptance criteria" a property of the call graph rather than of a check.
    """
    project_dir = Path(project_dir)
    path = project_dir / ACCEPTANCE_FILE
    previous: dict[str, Any] | None = None
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProposalError(
                f"{ACCEPTANCE_FILE} is on disk and unreadable ({exc}); a frozen "
                "contract that cannot be read cannot be compared against, and "
                "regenerating over it would be the silent overwrite this file "
                "exists to prevent") from exc
        if isinstance(loaded, dict):
            previous = loaded

    if previous is not None and _body(previous) == body:
        return Frozen(path=path, payload=previous,
                      revision=int(previous.get("revision", 1)),
                      contract_sha256=str(previous.get("contract_sha256", "")),
                      disposition="UNCHANGED")

    revision = int(previous.get("revision", 0)) + 1 if previous else 1
    changed = tuple(_differences(_body(previous), body)) if previous else ()
    payload = {**body, "revision": revision, "frozen_utc": updated_utc}
    payload["contract_sha256"] = S.payload_hash(payload)

    invalidated = _invalidate(project_dir) if previous else {}
    entry = {
        "revision": revision,
        "contract_sha256": payload["contract_sha256"],
        "proposal_sha256": body["proposal_sha256"],
        "frozen_utc": updated_utc,
        "reason": ("the acceptance contract is frozen before the builder runs"
                   if previous is None else
                   "the proposal or its system-owned inputs changed after a run"),
        "changed": list(changed),
        "supersedes": None if previous is None else {
            "revision": int(previous.get("revision", 1)),
            "contract_sha256": previous.get("contract_sha256"),
            "proposal_sha256": previous.get("proposal_sha256"),
            "invalidated_receipts": invalidated,
        },
    }
    history = _history(project_dir)
    history["revisions"].append(entry)
    (project_dir / HISTORY_FILE).write_text(S.canonical_json(history), encoding="utf-8")
    path.write_text(S.canonical_json(payload), encoding="utf-8")
    return Frozen(path=path, payload=payload, revision=revision,
                  contract_sha256=payload["contract_sha256"],
                  disposition="FROZEN" if previous is None else "SUPERSEDED",
                  changed=changed, invalidated=invalidated)


def _history(project_dir: Path) -> dict[str, Any]:
    path = Path(project_dir) / HISTORY_FILE
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            loaded = None
        if isinstance(loaded, dict) and isinstance(loaded.get("revisions"), list):
            return loaded
    return {"schema_version": HISTORY_SCHEMA, "revisions": []}


# ---------------------------------------------------------------------------
# The frozen contract, where a certified template goes
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class AcceptanceSource:
    """The frozen contract presented with a `CertifiedTemplate`'s surface.

    Same attribute names and call signatures, so `runner._contract_from` reaches
    commissioning, screening, the witnesses and the status decision unchanged and
    there is one definition of each. What it is emphatically *not* is the loaded
    model: `authored.AuthoredModel` no longer has an `expectations`, a `bbox` or
    a `bodies` at all, so the object the builder came out of cannot be handed to
    the function that writes the contract.
    """

    frozen: Frozen
    module: str | None = None
    module_sha256: str | None = None
    provenance: dict[str, Any] = dataclasses.field(default_factory=dict)

    backend: str = "authored"
    domain_id: str | None = None
    covers: str = "geometry authored for this job"

    @property
    def name(self) -> str:
        return str(self.frozen.payload["design_id"])

    @property
    def version(self) -> str:
        return self.frozen.version

    @property
    def bodies(self) -> int:
        return int(self.frozen.payload["expected_bodies"])

    @property
    def parameters(self) -> dict[str, Any]:
        return dict(self.frozen.payload["parameters"])

    def expectations(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """The frozen rows, ignoring whatever parameters are passed in.

        A certified template computes its expectations from the parameters it is
        handed. This one cannot: the rows were frozen before the build, and
        recomputing them from anything a later stage supplies is the door this
        whole module closes.
        """
        return [dict(row) for row in self.frozen.payload["features"]]

    def bbox(self, params: dict[str, Any]) -> dict[str, float]:
        return dict(self.frozen.payload["expected_bbox_mm"])

    def as_source(self) -> dict[str, Any]:
        payload = self.frozen.payload
        return {
            "kind": "authored",
            "module": self.module,
            "module_sha256": self.module_sha256,
            "provenance": dict(self.provenance),
            "acceptance_contract_sha256": self.frozen.contract_sha256,
            "acceptance_revision": self.frozen.revision,
            "proposal_sha256": payload["proposal_sha256"],
            "profile_marks": {"z": list(payload["profile_marks"]["z"])},
            # What the volume detector is entitled to say. `screening.py` reads
            # the basis, not the route: the question is who wrote the expectation,
            # and on every authored contract the answer is the party being
            # screened.
            "expected_volume_mm3": payload["expected_volume_mm3"],
            "expected_volume_basis": payload["expected_volume_basis"],
        }
