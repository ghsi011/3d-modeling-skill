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

**A geometry hit is not a safety hit.** They are separate namespaces on purpose.
Reusing a safety review because the mesh matched would be answering "is this part
safe" with "this is the same part", which is a different question and a worse
one -- the reviewer, its prompt, its reasoning settings and what it was shown all
have to match too, and those live in `safety.cache_identity`.
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

LAYERS = ("build", "commission", "witness")


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


def lock_hash(root: Path) -> str:
    """The toolchain, by its lockfile.

    Not the installed versions: two machines resolving the same lock get the same
    geometry, and a machine whose lock moved should miss even if the version
    numbers happen to line up.
    """
    lock = root / "uv.lock"
    return S.sha256_file(lock) if lock.is_file() else "no-lockfile"


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
        if payload.get("key", {}).get("digest") != key.digest():
            # The digest names the directory, so a mismatch means the entry was
            # written by a different key and the filesystem is lying to us.
            return None
        for name in payload.get("files", []):
            if not (slot / name).is_file():
                return None
        # Recompute from the bytes rather than trusting what was written down --
        # this whole pipeline exists because an entered hash is not a hash.
        for name, digest in payload.get("hashes", {}).items():
            if S.sha256_file(slot / name) != digest:
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

    def restore(self, key: Key, into: Path) -> list[str]:
        payload = self.lookup(key)
        if payload is None:
            return []
        slot = self._slot(key)
        into.mkdir(parents=True, exist_ok=True)
        restored = []
        for name in payload["files"]:
            shutil.copy2(slot / name, into / name)
            restored.append(name)
        return restored
