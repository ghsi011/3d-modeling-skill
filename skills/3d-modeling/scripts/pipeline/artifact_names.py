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

**It holds the artifacts a role authors and the pipeline shares a directory
with, and nothing else.** The four defects are now one mechanism: D34's plan,
D35's model source, D36's manifest and D37's contract are entries here rather
than three renames and a bespoke guard. The rest of the work directory is the
pipeline's own scratch, unregistered and nobody's.
"""
from __future__ import annotations

from pathlib import Path

# The owners that write into a work directory at the same time. Each role is
# spelled as `team_tools.validators._EXPECTED_OWNERS` already spells it, so the
# registry and the contract validator name the same role.
VERIFIER = "verifier"
DESIGNER = "cad-designer"
PRINT_ENGINEER = "print-engineer"
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


def default_path(work_dir: Path | str, name: str, *, owner: str) -> Path:
    """Where `owner` may write a generated default for a name a role holds.

    `path` above is an owner resolving its *own* artifact. This is the other
    case, and there is exactly one of it: a name whose role accepts a generated
    default while it has not authored one -- the print engineer's plan, which
    `validators._EXPECTED_OWNERS` itself lets `builtin-direct-template` author.

    Presence of the holder's file is the authority boundary, whatever the file
    contains; `docs/defects.md` D34 states that rule and the evidence for it,
    and is the one copy. This only ever says no -- what a refused caller then
    *reports* is the caller's business.

    An unregistered name is nobody's and is allowed, because most of a work
    directory is the pipeline's own scratch.
    """
    target = Path(work_dir) / name
    held = _OWNERS.get(name)
    if held is not None and held != owner and target.exists():
        raise NameConflict(
            f"{owner!r} may not write {name!r}: it is registered to {held!r}, "
            f"who has already written it")
    return target


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

# D35. The designer's whole deliverable: the designer charter tells a designer on
# a certified `INCONSEQUENTIAL` `DIRECT` job to produce it with
# `dt.py build --out model.py` and then read it and edit it. Both certified
# backends used to write a five-line generated record straight over it and exit
# reporting success. The pipeline's record is `bindings.BACKEND_RECORD`, and the
# name it moved off is held here so nothing may take it back.
MODEL_SOURCE = register("model.py", owner=DESIGNER)

# D36. A team contract: `validators.CANONICAL_FILENAMES` names it,
# `designer_toolkit/receipts.py` writes it with `contract: artifact-manifest`,
# and the charters point readers at it. The pipeline wrote a wholly different
# object there and treated the path as one of its own receipts, so `invalidate`
# deleted it too. The pipeline's is `bindings.PIPELINE_RECEIPT`, which still
# *reads* this name for a project completed before that rename -- reading is not
# a claim, and the registry governs writes.
ARTIFACT_MANIFEST = register("artifact_manifest.json", owner=DESIGNER)

# D34. The print engineer's deliverable: `dt.py audit` defaults to it,
# `dt.py commission --plan` is pointed at it, and pre-design rule 9 names it.
# `cli._print_plan` generated a template over it on every run, destroying every
# Edge ID, declared interface and charter obligation in it. Unlike the two
# above, the pipeline is entitled to write a default *here* while the engineer
# has not -- see `default_path`, which is what now holds that line.
PRINT_PLAN_CHECKS = register("print_plan_checks.json", owner=PRINT_ENGINEER)
