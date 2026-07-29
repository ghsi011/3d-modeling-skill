#!/usr/bin/env python3
"""Content-addressed caching, keyed on everything that could change the answer.

A cache is a claim that two runs would produce the same result, so the key has to
name every input that could make them differ. Miss one and the cache is a way of
serving a stale answer confidently -- worse than no cache, because the receipt
still looks fresh.

So the key is the contract hash, the template and its certified `domain_id`, the
backend and its version, the toolchain lock, the schema version, and the export
and tessellation settings. Tessellation is in there because a section area
measured off a coarser mesh is a different number, and two runs that disagree
about it are not the same run.

**A geometry hit is not a safety hit.** Reusing a safety review because the mesh
matched would be answering "is this part safe" with "this is the same part",
which is a different question and a worse one -- the reviewer, its prompt, its
reasoning settings and what it was shown all have to match too. `safety` computes
its own identity from those, and nothing here consults it.

There is one cached layer, the build. Commission and witness are fast enough that
caching them would buy less than the risk of serving one stale.
"""
from __future__ import annotations

import dataclasses
import json
import shutil
from pathlib import Path
from typing import Any

from . import schemas as S

# Bumped by hand when a change makes previously cached results wrong in a way the
# key cannot see -- a fixed detector, a corrected closed form. Every cache
# generation before it is dead, which is the intended blunt instrument: the
# alternative is reasoning about which stale entries are still fine.
GENERATION = 1

@dataclasses.dataclass(frozen=True)
class Key:
    """Everything that could change the answer, and nothing that could not."""

    contract_sha256: str
    template: str
    template_version: str
    domain_id: str | None
    backend: str
    backend_version: str
    lock_sha256: str
    schema_version: int
    step_required: bool
    tessellation: dict[str, Any]
    generation: int = GENERATION

    def digest(self) -> str:
        return S.payload_hash(dataclasses.asdict(self))

    def as_dict(self) -> dict[str, Any]:
        return {**dataclasses.asdict(self), "digest": self.digest()}


# Packages whose version can change the geometry or the measurement. Used to
# identify the toolchain when no lockfile is available.
TOOLCHAIN_PACKAGES = ("trimesh", "manifold3d", "build123d", "numpy")
CACHE_RECEIPT_SCHEMA = 1


def find_lock(start: Path) -> Path | None:
    """The nearest lockfile that belongs to a project, searching upward.

    Paired with `pyproject.toml` deliberately. Locating it by a fixed depth --
    `parents[4]`, which was correct for this repository and nothing else -- read
    two directories *above* an installed skill and would have hashed whatever
    unrelated `uv.lock` happened to be sitting there. A lockfile with no project
    beside it is somebody else's.
    """
    for directory in (start, *start.parents):
        if (directory / "uv.lock").is_file() and (directory / "pyproject.toml").is_file():
            return directory / "uv.lock"
    return None


def lock_hash(root: Path) -> str:
    """The toolchain, by its lockfile where there is one.

    Preferred over installed versions: two machines resolving the same lock get
    the same geometry, and a machine whose lock moved should miss even if the
    version numbers happen to line up.

    **Never a constant.** This returned the literal `"no-lockfile"` whenever it
    could not find one, so every machine without a lockfile shared a cache key no
    matter what was actually installed -- which is precisely the "serving a stale
    answer with a fresh-looking receipt" this module opens by warning about, and
    it fired on exactly the configuration that cannot check: an installed bundle.
    Falling back to the installed versions of the packages that decide geometry
    is weaker than a lock and enormously stronger than a constant.
    """
    lock = find_lock(root.resolve()) or find_lock(Path(__file__).resolve().parent)
    if lock is not None:
        return "lock:" + S.sha256_file(lock)
    return "versions:" + S.payload_hash(installed_versions())


def installed_versions() -> dict[str, str]:
    """What is actually importable, for when no lockfile identifies it.

    A package that cannot be found is recorded as absent rather than skipped: an
    absent build123d and an installed one are different toolchains, and a key
    blind to the difference would serve one's geometry to the other.
    """
    from importlib import metadata

    found: dict[str, str] = {}
    for name in TOOLCHAIN_PACKAGES:
        try:
            found[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            found[name] = "absent"
    return found


def key_for(contract, *, backend_version: str, tessellation: dict[str, Any],
            root: Path) -> Key:
    return Key(
        contract_sha256=contract.contract_hash(),
        template=contract.template, template_version=contract.template_version,
        domain_id=contract.domain_id, backend=contract.backend,
        backend_version=backend_version, lock_sha256=lock_hash(root),
        schema_version=S.CONTRACT_SCHEMA, step_required=bool(contract.step_required),
        tessellation=dict(tessellation),
    )


class Cache:
    """One directory per key digest. Absent is a miss; malformed is also a miss.

    A cache that raises on a corrupt entry turns a stale byte into a failed job.
    Treating it as a miss costs one rebuild and cannot be worse than not having
    cached at all.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def _slot(self, key: Key) -> Path:
        return self.root / key.digest()

    def lookup(self, key: Key) -> dict[str, Any] | None:
        slot = self._slot(key)
        receipt = slot / "cache_receipt.json"
        if not receipt.is_file():
            return None
        try:
            payload = json.loads(receipt.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if (not isinstance(payload, dict)
                or not isinstance(payload.get("schema_version"), int)
                or isinstance(payload.get("schema_version"), bool)
                or payload.get("schema_version") != CACHE_RECEIPT_SCHEMA):
            return None
        key_payload = payload.get("key")
        files = payload.get("files")
        hashes = payload.get("hashes")
        if (not isinstance(key_payload, dict) or not isinstance(files, list)
                or not all(isinstance(name, str) for name in files)
                or not isinstance(hashes, dict)
                or not all(isinstance(name, str) and isinstance(digest, str)
                           for name, digest in hashes.items())):
            return None
        if key_payload.get("digest") != key.digest():
            # The digest names the directory, so a mismatch means the entry was
            # written by a different key and the filesystem is lying to us.
            return None
        file_paths: dict[str, Path] = {}
        for name in files:
            try:
                file_paths[name] = S.resolve_within(slot, name, what="cache artifact")
            except S.PathEscape:
                return None
            if not file_paths[name].is_file():
                return None
        # Recompute from the bytes rather than trusting what was written down --
        # this whole pipeline exists because an entered hash is not a hash.
        for name, digest in hashes.items():
            try:
                path = file_paths.get(name) or S.resolve_within(
                    slot, name, what="cache artifact"
                )
            except S.PathEscape:
                return None
            if not path.is_file() or S.sha256_file(path) != digest:
                return None
        return payload

    def store(self, key: Key, *, files: dict[str, Path],
              payloads: dict[str, Any]) -> dict[str, Any]:
        slot = self._slot(key)
        slot.mkdir(parents=True, exist_ok=True)
        hashes: dict[str, str] = {}
        for name, source in files.items():
            if not source.is_file():
                continue
            shutil.copy2(source, slot / name)
            hashes[name] = S.sha256_file(slot / name)
        receipt = {
            "schema_version": CACHE_RECEIPT_SCHEMA,
            "key": key.as_dict(),
            "files": sorted(hashes),
            "hashes": hashes,
            "payloads": payloads,
            "note": ("A geometry hit is not a safety hit. Reusing a safety review "
                     "because the mesh matched answers 'is this part safe' with "
                     "'this is the same part'."),
        }
        (slot / "cache_receipt.json").write_text(S.canonical_json(receipt), encoding="utf-8")
        return receipt
