#!/usr/bin/env python3
"""Which owner holds which filename in the work directory.

D34, D35, D36 and D37 are one shape found four times: two legitimate writers,
one filename, and nothing anywhere that could say the name was taken. D34 was
closed by an existence check inside the writer and D35 and D36 by moving the
pipeline's file -- repairs that remove the collision they were written for and
leave the condition that produced it, a shared directory whose names are string
literals in whichever module happens to write them.

This is the smallest thing that makes the collision impossible rather than
repaired. A registered name has exactly one owner; a second owner claiming it is
refused; and a writer resolves its path *through* the owner that holds the name,
so pointing a write back at somebody else's file raises instead of succeeding.

**It holds the one artifact D37 is about and nothing else.** The rest of the
work directory is brought under it by later work, and guessing at that shape now
would be scaffolding for a change nobody has made yet.
"""
from __future__ import annotations

from pathlib import Path

# The two owners that write into a work directory at the same time. `verifier`
# is spelled as `team_tools.validators._EXPECTED_OWNERS` already spells it, so
# the registry and the contract validator name the same role.
VERIFIER = "verifier"
PIPELINE = "pipeline"


class NameConflict(Exception):
    """A filename was claimed or written by an owner that does not hold it."""


_OWNERS: dict[str, str] = {}


def register(name: str, *, owner: str) -> str:
    """Record that `owner` holds `name`, refusing it if somebody else does.

    Registering the same pair twice is a no-op rather than a conflict: this
    source checkout imports some modules both package-relatively and by bare
    name, and an import that raised the second time would be reporting the
    packaging, not a collision.
    """
    held = _OWNERS.setdefault(name, owner)
    if held != owner:
        raise NameConflict(
            f"{name!r} is registered to {held!r}; {owner!r} may not claim it too")
    return name


def path(work_dir: Path | str, name: str, *, owner: str) -> Path:
    """Where `owner` may write `name`, or `NameConflict` if it is not theirs."""
    held = _OWNERS.get(name)
    if held != owner:
        raise NameConflict(
            f"{owner!r} may not write {name!r}: it is registered to {held!r}")
    return Path(work_dir) / name


# The verifier's team contract. `team_tools.validators.CANONICAL_FILENAMES`
# names it, `_EXPECTED_OWNERS` requires `verifier` to have authored it, and
# `team_tools.status` cross-checks four bindings against it.
VERIFICATION_REPORT = register("verification_report.json", owner=VERIFIER)

# The pipeline's own independent-verification report: a decision, an evidence
# packet digest, a review envelope and a reviewer. It carries none of the four
# bindings above and no `contract` marker, so it is a different document that
# was sharing the name -- and it is the one that moves, for D36's reason. The
# team contract's name is externally specified, validator-known and
# charter-facing; this one has no reader outside this package.
PIPELINE_VERIFICATION_REPORT = register("pipeline_verification_report.json",
                                        owner=PIPELINE)
