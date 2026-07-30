#!/usr/bin/env python3
"""What each benchmark fixture is, what it proves, and what it must never hand over.

Stages 2-5 of [ADR 0002](../docs/adr/0002-route-and-contract-authority.md) move
authority, lifecycle, replay and geometry checks. The general suite has already
shown it can be green while an architectural defect sits underneath it, so the
rewrite needs a small set of *named* artifacts whose facts are asserted rather
than whose verdicts are asserted. This module is the register of those artifacts.

Three properties are load-bearing, and each is here because flattening it would
make the fixture set claim something it has not got.

**`evidence_class` is not a formality.** `vent-ball-combine` was printed, fitted
to a car vent and reported working. `berlingo-knob` was modelled and reviewed and
has never been printed at all -- two of its driving numbers are photo estimates
its own notes admit to. `pixel9-card-case` is somebody else's design that is in
service, which is evidence about the design and none at all about this pipeline.
Filing all three as "a real job" would let a later report say "proven on three
real jobs", and one of those three has no proof of anything.

**Public and private are separated structurally, not by convention.** A
benchmark that can hand a design agent the answer measures nothing, and the
usual defence -- "the loader does not return it" -- is one refactor from being
false. So the answer is not a field on the object a design agent receives. It
lives in a second mapping this module keeps to itself, `_REFERENCES`, keyed by
fixture id, and `PublicFixture` has no attribute, no property and no repr that
names it. Reaching the answer means calling `reference()` by name, which is a
thing a grader does and a thing a design agent has no reason to have written.

Withholding a file while disclosing its directory is not withholding it, and the
first version of this module did exactly that: the public record listed each
source input by absolute path, and `vent-ball-combine`'s inputs sit in the same
project directory as its reference. One `ls` and the wall was decoration. So the
public record carries no filesystem path at all beyond the repo-relative request
material -- inputs are `SourceRef`s, identified by name and hash, and the paths
live in `_SOURCES` beside `_REFERENCES`.

**Licence decides where the bytes live.** The Pixel 9 case is CC-BY-NC-SA and is
marked `INTERNAL_ONLY`. `redistributable_bundle()` refuses it outright rather
than trusting whoever assembles a public release to remember.

Nothing third-party is copied into the repository. Those files are recorded by
absolute path plus SHA-256; `resolve()` verifies the hash, and raises
`FixtureUnavailable` when the file is simply not on this machine so the suite
still runs on a checkout that has none of them.

The owner's own work is vendored instead, because pointing at it did not survive
contact with reality. `vent-ball-combine` -- the only `PHYSICALLY_PROVEN` entry
here -- was recorded at a path inside a sibling git worktree that had no commits
behind it. Prune the worktree and the fixture is gone, and because absence is a
skip the suite would have stayed green while the set quietly lost its only proof
that a job of this shape can be completed. So its geometry is committed, its
recorded paths are repo-relative, and a vendored file that is not on disk raises
`FixtureMissing`, which nothing skips on.

Vendoring the answer does not move it to the public side. It is committed under
`benchmarks/references/`, which is not the fixture's own directory and is not
reachable by walking up from anything the public record names: everything under
`benchmarks/fixtures/<id>/` is material a design agent may read, and the answer
is not under it.

**A receipt whose artifact cannot be opened is not a receipt.** The vendored job
record includes the delivery manifest the run wrote, and that manifest names its
candidate `candidate-01.stl` -- the name the job used, beside a hash that still
validates. Vendoring kept the same bytes under the name the part is known by and
left the manifest's own path with nothing behind it. The manifest is not edited
to match: it is what was delivered, and a record rewritten afterwards to make the
snapshot tidier is a worse record. So the duplicate is carried at the literal path
the manifest names, `historical_aliases.json` beside the evidence explains why two
names hold one file, and `delivery_artifacts()` resolves the path the manifest
actually spells. The alias record is read and checked and is never consulted to
find a file, because an alias that can stand in for a missing artifact is a
redirect, and a redirect is how "every path resolves" stops meaning anything.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
from pathlib import Path, PurePosixPath
from typing import ClassVar

REPO_ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------

# What is actually known about the fixture, ordered by how much it establishes.
# The names are deliberately awkward: `DESIGN_STAGE_UNVERIFIED` is harder to
# quote approvingly in a summary than "real job" is, which is the point.
PHYSICALLY_PROVEN = "PHYSICALLY_PROVEN"          # printed, fitted, reported working
WORKING_THIRD_PARTY = "WORKING_THIRD_PARTY"      # someone else's design, in service
DESIGN_STAGE_UNVERIFIED = "DESIGN_STAGE_UNVERIFIED"  # modelled; nothing printed
PARSER_SPECIMEN = "PARSER_SPECIMEN"              # a real file kept for what it exercises

EVIDENCE_CLASSES = (PHYSICALLY_PROVEN, WORKING_THIRD_PARTY,
                    DESIGN_STAGE_UNVERIFIED, PARSER_SPECIMEN)

INTERNAL_ONLY = "INTERNAL_ONLY"
REDISTRIBUTABLE = "REDISTRIBUTABLE"
DISTRIBUTIONS = (INTERNAL_ONLY, REDISTRIBUTABLE)

# Whether a fixture's bytes may be committed here is a question about who made
# them, not about how convenient it would be. The owner's own models are
# vendored, so that no directory outside this repository has to keep existing
# for the fixture to; everything else is somebody else's work and stays outside
# the tree, recorded by path and hash, so that cloning this repository
# redistributes nothing that was never ours to redistribute.
OWN_WORK_LICENSES = ("user-owned", "synthetic")

# Diagnosis is a use case in its own right here: three of these fixtures exist
# because of what a reader gets wrong on them, not because a part has to be
# designed from them.
USE_CASES = ("DIAGNOSE", "MODIFY", "COMBINE", "FROM_SCRATCH")


class FixtureUnavailable(RuntimeError):
    """The recorded file is not on this machine. Callers skip; they do not fail.

    Only ever raised for a file the repository points at and does not contain.
    A checkout on a machine that never had the owner's CAD directory should
    still run the whole suite.
    """


class FixtureMissing(RuntimeError):
    """A *vendored* file is not on disk. This is a failure and not a skip.

    Deliberately not a subclass of `FixtureUnavailable`. Every skip in this
    suite is spelled `except FixtureUnavailable: skipTest(...)`, and making this
    inherit from it would route the one case that has to be loud straight
    through the handler that silences it -- which is the exact failure mode
    vendoring the fixture was meant to remove.
    """


class FixtureMismatch(RuntimeError):
    """The file is present and is not the file the manifest recorded.

    This is a failure and not a skip. A fixture whose bytes moved is a different
    fixture, and every number asserted against it was measured on the old one.
    """


class LicenceWithheld(RuntimeError):
    """A redistributable bundle was asked for geometry that may not be shipped."""


@dataclasses.dataclass(frozen=True)
class ExternalFile:
    """A file the repository points at and never contains.

    Somebody else's geometry, or a user file this project has no claim on. The
    path is absolute and machine-specific, so absence is an ordinary fact about
    the machine rather than a defect.
    """
    path: str
    sha256: str
    bytes: int
    vendored: ClassVar[bool] = False

    @property
    def name(self) -> str:
        return Path(self.path).name

    @property
    def location(self) -> Path:
        return Path(self.path)


@dataclasses.dataclass(frozen=True)
class VendoredFile:
    """A file the repository contains, recorded repo-relative.

    The owner's own work, committed so that pruning a directory somewhere else
    cannot delete a fixture. The path is relative to `REPO_ROOT` and written
    POSIX-style, so the manifest reads the same on every machine -- and so that
    a recorded path carries no drive letter to be mistaken for a location on
    the machine that reads it.
    """
    path: str
    sha256: str
    bytes: int
    vendored: ClassVar[bool] = True

    @property
    def name(self) -> str:
        return PurePosixPath(self.path).name

    @property
    def location(self) -> Path:
        return REPO_ROOT / self.path


# Either kind is resolvable; only the consequence of absence differs.
FixtureFile = ExternalFile | VendoredFile


@dataclasses.dataclass(frozen=True)
class SourceRef:
    """An input, identified rather than located.

    The absolute path is deliberately absent. `vent-ball-combine`'s reference
    sits in the same project directory its two sources came from, so a public
    record that named where the inputs live would hand a design agent the
    answer's parent directory -- and a directory listing is not a wall. The
    loader knows the path; the object a design agent holds does not.
    """
    name: str
    sha256: str
    bytes: int


@dataclasses.dataclass(frozen=True)
class PublicFixture:
    """Everything a design agent may be given.

    Read the field list as the security property: there is no reference, no
    answer, no solution, no hash of one, and no filesystem path except the
    repo-relative request material. A design agent handed this object, or its
    `repr`, or its JSON, holds nothing that locates the reference -- which is a
    stronger statement than "the loader chose not to return it".
    """
    fixture_id: str
    use_cases: tuple[str, ...]
    evidence_class: str
    license: str
    distribution: str
    # Repo-relative, so the request material is reviewable in a diff.
    public_request: str
    # Inputs the job is *given*. A MODIFY or COMBINE job cannot start without
    # them, so they are public to the agent -- which is a different question
    # both from whether they may be redistributed and from whether the agent may
    # be told where on this machine they sit.
    sources: tuple[SourceRef, ...] = ()
    notes: str = ""


# --------------------------------------------------------------------------
# Where the files are
# --------------------------------------------------------------------------
#
# Paths live here and in `_REFERENCES` below, and in nothing that is handed out.
# Every file is recorded by path, size and SHA-256, and `resolve()` checks all
# three, so a file that moved is never quietly measured in place of the recorded
# one. What differs between the two kinds is only what absence means: an
# `ExternalFile` belongs to somebody else and may simply not be on this machine,
# while a `VendoredFile` is committed here and cannot be missing for an innocent
# reason.

_SOURCES: dict[str, tuple[FixtureFile, ...]] = {
    "pixel9-card-case": (
        ExternalFile(
            path=r"C:\github\3D\oneplus 8t case"
                 r"\Pixel+9+Pro+XL+Case+With+Card+Holder.3mf",
            sha256="5bbf1fba8ba417f50c8e4ea50a02fc16202e7ec40e710e6704747e1558e4"
                   "c001",
            bytes=2226161),),
    "oneplus-drawer-dropin": (
        ExternalFile(
            path=r"C:\github\3D\oneplus 8t case"
                 r"\oneplus8t-card-drawer-TPU95A-dropin.3mf",
            sha256="a155e3ebc31a38580477c5c08ebc469feaed2c6b85106caa4b479c2a3ace"
                   "d2a9",
            bytes=18628),),
    "oneplus-case-x2d-asa": (
        ExternalFile(
            path=r"C:\github\3D\oneplus 8t case"
                 r"\oneplus8t-card-case-X2D-ASA.3mf",
            sha256="32f7ce46007cb0b4f5f695222b48b0c98927555466c53516fa8802930ef6"
                   "0a1e",
            bytes=1120727),),
    # The owner's own two solids, committed. They are public to the agent, so
    # they sit under the fixture's `public/` directory: a design agent that
    # lists everything it has been given finds exactly what it was given.
    "vent-ball-combine": (
        VendoredFile(
            path="benchmarks/fixtures/vent-ball-combine/public/sources"
                 "/vent_mount.step",
            sha256="1b1edb15fb78f6491ceaeb761fe8bf0b4b1cc5ea4c70c7a1cabfb4a23d70"
                   "3f96",
            bytes=632950),
        VendoredFile(
            path="benchmarks/fixtures/vent-ball-combine/public/sources"
                 "/ball_male_17mm.stl",
            sha256="679c7e45fa8a5ccffb1d614079d96c72026a347d77fe0e87cb7f23eaf317"
                   "ed37",
            bytes=352884),
    ),
}


# --------------------------------------------------------------------------
# The manifest
# --------------------------------------------------------------------------
#
# Declared without sources, which are filled in below from `_SOURCES` as name,
# size and hash. Writing them here would be writing an absolute path into the
# object a design agent is handed, which is the leak `SourceRef` exists to close.

_DECLARED: tuple[PublicFixture, ...] = (
        PublicFixture(
            fixture_id="pixel9-card-case",
            use_cases=("DIAGNOSE", "MODIFY"),
            evidence_class=WORKING_THIRD_PARTY,
            license="CC-BY-NC-SA-4.0",
            distribution=INTERNAL_ONLY,
            public_request="benchmarks/fixtures/pixel9-card-case/public/request.md",
            notes="A Bambu Studio production-extension export: the root part "
                  "carries the scene and every mesh lives in its own part behind "
                  "a p:path. Downloaded and printed by the user; nothing about "
                  "this pipeline is evidenced by it working."),
        PublicFixture(
            fixture_id="oneplus-drawer-dropin",
            use_cases=("DIAGNOSE",),
            evidence_class=PARSER_SPECIMEN,
            license="user-owned",
            distribution=INTERNAL_ONLY,
            public_request="benchmarks/fixtures/oneplus-drawer-dropin/public/"
                           "request.md",
            notes="18 KB and one 536-triangle object: the cheapest real file "
                  "that still carries a build transform, so the assembled-scene "
                  "assertion costs ~0.01 s."),
        PublicFixture(
            fixture_id="oneplus-case-x2d-asa",
            use_cases=("DIAGNOSE",),
            evidence_class=PARSER_SPECIMEN,
            license="user-owned",
            distribution=INTERNAL_ONLY,
            public_request="benchmarks/fixtures/oneplus-case-x2d-asa/public/"
                           "request.md",
            notes="Damaged on purpose by history, not by us: 332 boundary edges "
                  "and inconsistent winding on the body, beside a second object "
                  "that is sound. The heavier 4,892-edge sibling is left out of "
                  "L0."),
        PublicFixture(
            fixture_id="vent-ball-combine",
            use_cases=("COMBINE", "MODIFY"),
            evidence_class=PHYSICALLY_PROVEN,
            license="user-owned",
            distribution=INTERNAL_ONLY,
            public_request="benchmarks/fixtures/vent-ball-combine/public/"
                           "request.md",
            notes="Two solids the user had already printed, grafted into one "
                  "part; the result was printed, fitted to a car vent and "
                  "reported working. The only fixture here that proves a job of "
                  "this shape can be completed, and so the one the repository "
                  "keeps its own copy of. It used to be recorded at a path "
                  "inside an uncommitted sibling worktree; pruning that "
                  "directory would have degraded the set's only "
                  "PHYSICALLY_PROVEN entry to a skip without failing "
                  "anything."),
        PublicFixture(
            fixture_id="berlingo-knob",
            use_cases=("FROM_SCRATCH",),
            evidence_class=DESIGN_STAGE_UNVERIFIED,
            license="user-owned",
            distribution=INTERNAL_ONLY,
            public_request="benchmarks/fixtures/berlingo-knob/public/request.md",
            notes="Designed from calipers and photographs and never printed. Its "
                  "own print notes list the base-plate height and the button "
                  "height as photo estimates at +/-2 mm. Whatever this fixture "
                  "measures, it is not fit."),
        PublicFixture(
            fixture_id="component-cycle",
            use_cases=("DIAGNOSE",),
            evidence_class=PARSER_SPECIMEN,
            license="synthetic",
            distribution=REDISTRIBUTABLE,
            public_request="benchmarks/fixtures/component-cycle/public/request.md",
            notes="Built in-test with zipfile. Two component wrappers pointing at "
                  "each other: nothing dangles, nothing parses badly, and there "
                  "is no geometry anywhere."),
)

_FIXTURES: dict[str, PublicFixture] = {
    fixture.fixture_id: dataclasses.replace(
        fixture,
        sources=tuple(SourceRef(name=external.name, sha256=external.sha256,
                                bytes=external.bytes)
                      for external in _SOURCES.get(fixture.fixture_id, ())))
    for fixture in _DECLARED
}

# --------------------------------------------------------------------------
# The other side of the wall
# --------------------------------------------------------------------------
#
# Keyed by fixture id and reachable only through `reference()`. It is a separate
# mapping rather than a field on `PublicFixture` so that handing a design agent
# the whole public record -- object, repr, JSON, a copied directory -- hands it
# nothing that locates the answer. A field marked "do not read this" is a
# comment; a value that is not in the object is a structure.
#
# The vendored answer is committed outside the fixture's own directory, under
# `benchmarks/references/`. That is the same wall in the filesystem: everything
# under `benchmarks/fixtures/<id>/` is material the agent may read, so an answer
# placed there would be one `cd ..` from the request it is meant to withhold --
# which is the leak this module was rewritten to close, rebuilt in a new place.
_REFERENCES: dict[str, FixtureFile] = {
    "vent-ball-combine": VendoredFile(
        path="benchmarks/references/vent-ball-combine"
             "/tesla-vent-mount-17mm-ball.stl",
        sha256="5d2d7324e87a195eef0b21bf155ac0792184eec33fdfbf6a1273b0b24b03d507",
        bytes=976184),
    "berlingo-knob": ExternalFile(
        path=r"C:\github\3D\Berlingo gear shift knob\v4-cadquery\knob_v4.step",
        sha256="fa57bc7f58caaa3c6d6973d5bfe6d7f2b5e968519ae76caec952bf8b24c6cbf6",
        bytes=811738),
}


# --------------------------------------------------------------------------
# The record of the job that produced the answer
# --------------------------------------------------------------------------
#
# Two files in the vendored evidence are immutable in the strict sense: their
# whole worth is that they are byte-identical to what ran, so they are recorded
# by hash here and are the only things in the tree that formatter and linter are
# told to leave alone.
#
# The delivery manifest is the receipt. It is not rewritten to suit the tree it
# now sits in -- including the candidate path, which names the file as the job
# named it. See `historical_aliases()` for what that costs and why it is paid.

_DELIVERY_RECORDS: dict[str, VendoredFile] = {
    "vent-ball-combine": VendoredFile(
        path="benchmarks/references/vent-ball-combine/evidence"
             "/artifact_manifest.json",
        sha256="fff5c058735cdb2297a8d65ba16da9fb575830b22fe634df3a7112f2e3e71065",
        bytes=1295),
}

# The script the part was actually built by. Nothing imports it and nothing may
# edit it: an artifact whose only claim is that nobody has touched it stops being
# one the moment a formatter tidies an import.
_DESIGN_SOURCES: dict[str, VendoredFile] = {
    "vent-ball-combine": VendoredFile(
        path="benchmarks/references/vent-ball-combine/evidence/model.py",
        sha256="c48ec3660669376fedfa589da38401a98e8e0710f38b2aa50a4a2eaefa3f464a",
        bytes=11820),
}

# Maintained metadata, deliberately *not* hash-pinned: it is commentary on the
# evidence and not evidence, so it is expected to be edited when there is more to
# explain. It sits outside `evidence/` for the same reason.
_ALIAS_RECORDS: dict[str, str] = {
    "vent-ball-combine": "benchmarks/references/vent-ball-combine"
                         "/historical_aliases.json",
}

BYTE_IDENTICAL = "BYTE_IDENTICAL"


# --------------------------------------------------------------------------
# Reading the public side
# --------------------------------------------------------------------------

def fixture_ids() -> tuple[str, ...]:
    return tuple(sorted(_FIXTURES))


def public(fixture_id: str) -> PublicFixture:
    """The record a design agent may hold. Frozen, and carries no answer."""
    try:
        return _FIXTURES[fixture_id]
    except KeyError:
        raise KeyError(f"no fixture named {fixture_id!r}; known: "
                       f"{', '.join(fixture_ids())}") from None


def request_text(fixture_id: str) -> str:
    path = REPO_ROOT / public(fixture_id).public_request
    if not path.is_file():
        raise FixtureUnavailable(
            f"{fixture_id}: the public request material is missing at {path}. "
            "This one lives in the repository, so this is a checkout problem "
            "rather than a machine that lacks the geometry.")
    return path.read_text(encoding="utf-8")


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve(record: FixtureFile, *, what: str) -> Path:
    """The verified path to a recorded file, or a reason it cannot be used.

    What absence means depends on who owns the bytes, and the difference is the
    whole point of the distinction. An `ExternalFile` is somebody else's and is
    referenced rather than copied, so a fresh checkout on a machine that never
    had the user's CAD directory should still run the whole suite: absence
    skips. A `VendoredFile` is committed here, so absence is not a fact about
    the machine -- it means the tree is not what it says it is, and skipping it
    is precisely how a suite reports green while a fixture has evaporated.

    A hash that moved is a failure either way. The file is there and it is not
    the file every number in the L0 set was measured against, and saying nothing
    about that is how a fixture set stops describing the thing it is named
    after.
    """
    path = record.location
    if not path.is_file():
        if record.vendored:
            raise FixtureMissing(
                f"{what}: {path} is committed to this repository and is not on "
                "disk. This is not a machine that happens to lack somebody "
                "else's geometry -- the bytes are tracked, so either the "
                "checkout is incomplete or the file was deleted. It fails "
                "loudly rather than passing quietly, because a proof fixture "
                "that disappears without failing anything leaves the suite "
                "green with nothing behind it.")
        raise FixtureUnavailable(
            f"{what}: not on this machine at {path}. The file is licensed or "
            "third-party geometry and is referenced rather than vendored; "
            "skipping.")
    size = path.stat().st_size
    if size != record.bytes:
        raise FixtureMismatch(
            f"{what}: {path} is {size} bytes and the manifest records "
            f"{record.bytes}. This is the same failure the hash would report, "
            "found without reading two megabytes.")
    found = _digest(path)
    if found != record.sha256:
        raise FixtureMismatch(
            f"{what}: {path} is present but hashes {found}, and the manifest "
            f"records {record.sha256}. Every assertion made against this "
            "fixture was measured on the recorded bytes.")
    return path


def source_path(fixture_id: str, index: int = 0) -> Path:
    """A verified input the job is given.

    The *contents* are public to a design agent -- a `MODIFY` job cannot start
    without them. The *location* is not, and is why this is a loader call rather
    than a field: `_SOURCES` is where the paths live.
    """
    public(fixture_id)                                    # rejects unknown ids
    records = _SOURCES.get(fixture_id, ())
    if not records:
        raise FixtureUnavailable(f"{fixture_id}: this fixture has no source "
                                 "artifact; it is designed from scratch.")
    return resolve(records[index], what=f"{fixture_id} source {index}")


# --------------------------------------------------------------------------
# Reading the delivery record
# --------------------------------------------------------------------------

def delivery_record(fixture_id: str) -> dict:
    """The artifact manifest the job wrote, verified against its recorded bytes.

    Read rather than reconstructed, and hash-checked on the way in, so that "the
    record is unchanged" is a fact the loader establishes rather than a habit
    reviewers are trusted to keep.
    """
    record = _DELIVERY_RECORDS.get(fixture_id)
    if record is None:
        raise KeyError(f"no delivery record is vendored for {fixture_id!r}")
    path = resolve(record, what=f"{fixture_id} delivery record")
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_delivered(directory: Path, artifact: dict, *, what: str) -> Path:
    """One artifact, opened at the exact path the record spells.

    The path is joined and never rewritten. There is no alias lookup here and no
    fallback to a file with the same hash under another name, because either one
    turns "every path in the receipt resolves" into "every path in the receipt
    resolves to something", which is a different and much weaker claim.
    """
    raw = artifact["path"]
    relative = PurePosixPath(raw)
    if relative.is_absolute() or ".." in relative.parts:
        raise FixtureMismatch(
            f"{what}: the record names {raw!r}, which leaves the directory it "
            "was delivered in. A receipt addresses its own bundle.")
    path = directory / relative
    if not path.is_file():
        raise FixtureMissing(
            f"{what}: the delivery record names {raw!r} and there is no file at "
            f"{path}. The record is immutable and the artifacts beside it are "
            "committed, so a path with nothing behind it means the evidence is "
            "incomplete -- not that this machine happens to lack something.")
    found = _digest(path)
    if found != artifact["sha256"]:
        raise FixtureMismatch(
            f"{what}: {path} hashes {found} and the delivery record says "
            f"{artifact['sha256']}. The receipt is describing other bytes.")
    return path


def delivery_artifacts(fixture_id: str, *,
                       directory: Path | None = None) -> dict[str, Path]:
    """Every artifact the record names, resolved and hash-checked.

    `directory` defaults to the manifest's own, which is how a receipt addresses
    its bundle; it is a parameter so the resolution can be exercised against a
    tree that is missing a file, which is the only way to show that the alias
    record is not quietly rescuing one.
    """
    manifest = delivery_record(fixture_id)
    if directory is None:
        directory = _DELIVERY_RECORDS[fixture_id].location.parent
    return {artifact["id"]: _resolve_delivered(
                directory, artifact,
                what=f"{fixture_id} artifact {artifact['id']!r}")
            for artifact in manifest["artifacts"]}


def historical_aliases(fixture_id: str) -> tuple[dict, ...]:
    """Why one set of bytes is carried under two names. Explanation only.

    The delivery record calls the candidate `candidate-01.stl`; the repository
    keeps the same bytes at the top of the reference directory under the name the
    part is known by. Editing the record to agree would have made the snapshot
    tidier and less true, and deleting the duplicate would have left a receipt
    pointing at nothing. So both files are present and this says why.

    Nothing in resolution reads this. It is returned for a reader and asserted
    against by the tests; `_resolve_delivered` never sees it.
    """
    relative = _ALIAS_RECORDS.get(fixture_id)
    if relative is None:
        return ()
    path = REPO_ROOT / relative
    if not path.is_file():
        raise FixtureMissing(
            f"{fixture_id}: the alias record is committed at {path} and is not "
            "on disk.")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return tuple(loaded.get("historical_aliases", ()))


def design_source(fixture_id: str) -> Path:
    """The script the reference was built by, verified.

    Immutable historical source: it is outside formatter and linter control
    precisely because its worth is that it has not been touched, so the hash is
    what stops it being touched by accident instead.
    """
    record = _DESIGN_SOURCES.get(fixture_id)
    if record is None:
        raise KeyError(f"no design source is vendored for {fixture_id!r}")
    return resolve(record, what=f"{fixture_id} design source")


def hash_verified_paths() -> tuple[str, ...]:
    """Every repo-relative path whose bytes this module checks against a digest.

    Including the ones reached through the delivery record, so that adding an
    artifact to a vendored manifest brings it under the line-ending check
    automatically rather than when somebody remembers.
    """
    paths = {record.path
             for records in _SOURCES.values() for record in records
             if record.vendored}
    paths |= {record.path for record in _REFERENCES.values() if record.vendored}
    for fixture_id, record in _DELIVERY_RECORDS.items():
        paths.add(record.path)
        base = PurePosixPath(record.path).parent
        for artifact in delivery_record(fixture_id)["artifacts"]:
            paths.add(str(base / PurePosixPath(artifact["path"])))
    paths |= {record.path for record in _DESIGN_SOURCES.values()}
    return tuple(sorted(paths))


# --------------------------------------------------------------------------
# Handing material out
# --------------------------------------------------------------------------

def public_bundle(fixture_id: str, destination: Path) -> Path:
    """Everything a design agent gets, materialised as a directory.

    Source geometry is copied in rather than pointed at, and the recorded path is
    left out of what gets written. That is not tidiness. `vent-ball-combine`'s
    reference used to sit in the same project directory its sources came from,
    so a bundle that named the source path would have handed an agent the
    answer's parent directory and one `ls`. Withholding the answer while
    disclosing where it lives is not withholding it -- which is also why
    vendoring put the sources under the fixture's `public/` directory and the
    answer somewhere else entirely, rather than side by side again.

    What the agent ends up with is a self-contained directory: the request, the
    inputs, and the fixture's own metadata -- which already carries sources as
    name and hash rather than as paths, because `PublicFixture` has never held a
    path. The reference cannot arrive here by accident; it would take a new call
    to `reference()`, which is a thing a design path has no reason to contain.
    """
    fixture = public(fixture_id)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "request.md").write_text(request_text(fixture_id),
                                            encoding="utf-8")

    records = _SOURCES.get(fixture_id, ())
    if records:
        (destination / "sources").mkdir(exist_ok=True)
        for index, record in enumerate(records):
            verified = resolve(record, what=f"{fixture_id} source {index}")
            shutil.copyfile(verified, destination / "sources" / record.name)
    (destination / "fixture.json").write_text(
        json.dumps(dataclasses.asdict(fixture), indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    return destination


def redistributable_bundle(fixture_id: str, destination: Path) -> Path:
    """The same, for a bundle that will leave this machine.

    The Pixel 9 case is CC-BY-NC-SA. Sharing a benchmark that carries it, or
    that carries a path and a hash pointing straight at it, is a licensing
    decision somebody has to make deliberately -- so this refuses rather than
    documenting a rule and hoping.
    """
    fixture = public(fixture_id)
    if fixture.distribution != REDISTRIBUTABLE:
        raise LicenceWithheld(
            f"{fixture_id}: distribution is {fixture.distribution} under "
            f"{fixture.license}. It may be used here and may not be shipped. "
            "Handle the licence deliberately or leave the fixture out of the "
            "bundle.")
    return public_bundle(fixture_id, destination)


def reference(fixture_id: str) -> Path:
    """The withheld answer. For grading only.

    Deliberately not reachable from `public()`, `public_bundle()` or anything
    they call. If this appears in a design path, the benchmark has stopped
    measuring.
    """
    external = _REFERENCES.get(fixture_id)
    if external is None:
        raise KeyError(f"no private reference is recorded for {fixture_id!r}")
    return resolve(external, what=f"{fixture_id} reference")


def has_reference(fixture_id: str) -> bool:
    """Whether an answer is held at all -- which is not the answer."""
    return fixture_id in _REFERENCES
