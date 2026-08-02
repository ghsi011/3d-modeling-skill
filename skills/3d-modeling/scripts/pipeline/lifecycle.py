#!/usr/bin/env python3
"""What was deliberately done to this job's formulations, and when.

Two events, and both exist because the alternative to recording them is losing
something ARCHITECTURE.md 13.1 says is not lost.

* **`RESTART`** -- `design-tool run --restart` discards a formulation's
  conclusions on purpose. `bindings.invalidate` already had the rule that a
  superseded pass must be "neither current nor erased", and it kept it by
  printing the digests of what it removed to stderr, where nothing can read them
  ten minutes later. A restart is the one operation in this pipeline that throws
  away a receipt whose bindings still hold, so it is the one that most needs a
  record of what it threw away.
* **`DISPOSITION`** -- a formulation moved between lifecycle states. The state
  itself lives in `project.json`, which holds only the *current* value; the
  transition, its basis and what it displaced live here. Preferring one
  formulation demotes another, and "changing the preferred alternative does not
  erase the previously preferred one" (13.3) is a statement about a history, not
  about a field.

**This journal is bound by nothing, and that is deliberate.** No receipt carries
its digest, `bindings.RECEIPTS` does not name it, and appending to it cannot make
anything stale. That is what lets it hold the one thing a content-derived run
identity cannot (`bindings.identity`): a record ordered by when things happened,
in a system whose every other artifact is ordered by what it contains. A journal
that participated in identity would end byte-identical reruns, which is the
constraint the identity decision turns on.

Every event is stamped with the caller-supplied `updated_utc` rather than a
clock, for the same reason: this file must not be the thing that makes two
otherwise identical projects differ.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import schemas as S

LIFECYCLE_FILE = "lifecycle.json"
LIFECYCLE_SCHEMA = 1

# What a recorded event may be. Closed, so an event nothing writes cannot appear
# and an event kind added later has to be declared before it can be recorded.
EVENT = ("RESTART", "DISPOSITION")


def path(project_dir: Path) -> Path:
    """At the project root, not in a formulation's directory.

    A disposition is a decision about a formulation taken from outside it -- the
    row lives in the shared `project.json` and preferring one alternative demotes
    another -- so a per-formulation journal would have to write two files for one
    event and would have nowhere to put the ordering between them.
    """
    return Path(project_dir) / LIFECYCLE_FILE


def read(project_dir: Path) -> list[dict[str, Any]]:
    """Every recorded event, oldest first; an unreadable journal reads as empty.

    Not an error: nothing depends on this file, so a corrupt one must not be able
    to stop a job. What it must not do is *look* complete -- `record` refuses to
    append to a journal it could not read, so a damaged file is preserved rather
    than silently replaced by one holding a single event.
    """
    target = path(project_dir)
    if not target.is_file():
        return []
    try:
        loaded = json.loads(target.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return []
    if not isinstance(loaded, dict):
        return []
    events = loaded.get("events")
    return [row for row in events if isinstance(row, dict)] if isinstance(events, list) else []


def _is_a_journal(target: Path) -> bool:
    """Whether the file on disk is this document and not something else."""
    try:
        loaded = json.loads(target.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(loaded, dict) and isinstance(loaded.get("events"), list)


def record(project_dir: Path, event: dict[str, Any]) -> Path:
    """Append one event. Refuses an undeclared kind, and refuses to lose a file.

    Rewriting the whole document rather than appending a line: this is JSON that
    `design-tool status` reads, the volumes are a handful of events per job, and
    a format that is only valid once a reader has stitched lines together is a
    format somebody reads wrong.
    """
    S.require_enum(str(event.get("event")), EVENT, what="lifecycle event")
    target = path(project_dir)
    if target.is_file() and not _is_a_journal(target):
        # An empty journal and an unreadable one both `read` as no events, and
        # appending to the second would delete a record. The whole point of this
        # file is that records are not deleted, so the ambiguity is refused
        # rather than resolved in the direction that loses one.
        raise S.SchemaError(
            f"{LIFECYCLE_FILE} is not a readable journal; it is the record of "
            "what was deliberately discarded, so it is not overwritten")
    events = read(project_dir)
    events.append(dict(event))
    target.write_text(S.canonical_json({"schema_version": LIFECYCLE_SCHEMA,
                                        "events": events}), encoding="utf-8")
    return target


def last(project_dir: Path) -> dict[str, Any] | None:
    events = read(project_dir)
    return events[-1] if events else None
