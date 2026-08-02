#!/usr/bin/env python3
"""One structured validation finding, and the code vocabulary a caller matches on.

`Issue` is not new. It was written for `team_tools` and has been carrying every
contract-validation finding since: a severity, a code, a field path, and a stable
`id` of `CODE@where` that two runs of one job agree on. What was new is that
nothing outside that package could use it, so `Project.validate()` -- the one
validator the whole pipeline routes through -- answered in English sentences and
nothing else. With one alternative a list of sentences is readable. With N,
"which alternative, which field, and is this the same problem as last run" are
questions a sentence cannot answer, so the type moved here rather than being
invented a second time.

**Which way the dependency points.** `team_tools` is the older package and
`pipeline` is the one being built, so `team_tools.common` imports this module and
not the reverse. A shared module under `team_tools` would have made every future
part of the pipeline depend on the layer it is replacing. This module is stdlib
only and `pipeline/__init__.py` is a docstring, so the import costs `team_tools`
nothing it was not already paying.

**The code grouping rule.** A code is a promise: it is what a caller matches on
and what a fixture asserts. The prefix names *what has to change to clear the
finding*, which is the one grouping that tells a reader whose problem it is:

* ``SCHEMA_*`` -- one field is wrong in itself: absent, the wrong type, outside
  its enum, out of range, or not a finite number. Clear it by correcting that
  field.
* ``REF_*`` -- the field holds a well-formed id that no row declares, or two rows
  claim one id, or ancestry is out of order. Clear it by adding, removing or
  renaming a *row*; the field on its own is not wrong.
* ``ARTIFACT_*`` -- the declaration is fine and the file on disk disagrees: the
  path leaves the project, names no file, or the document it names was refused.
  Clear it by supplying, correcting or replacing that file. Nothing in
  `project.json` alone can fix it.
* ``INTENT_*`` -- every field and every reference is fine and the declarations
  still do not describe one job. Clear it by deciding what the job is; there is
  no mechanical repair.

The shape follows `analysis.py`'s `MeasurementFailed` codes
(``BOOLEAN_ENGINE_REFUSED``, ``SECTION_INSTRUMENT_EMPTY``), which are the only
prior art in this package: SCREAMING_SNAKE, and a shared prefix that names the
subject a reader groups by.

A code is deliberately *not* unique per check. `id` is ``CODE@where`` and `where`
is an exact field path, so ``SCHEMA_ENUM@source_mode`` already names exactly one
rule. That is the same trade `team_tools` made -- one ``BAD_PATH`` across every
path field -- and it keeps the vocabulary small enough to be matched on rather
than looked up.
"""

from __future__ import annotations

from typing import Any, Iterable


class Issue:
    """One validation finding, always naming the exact contract field/id/rule.

    ``where`` is a dotted/bracketed path such as
    ``dimensions.dimensions[D99].feature_id`` or ``edit_scopes[1].region_box`` so
    failures are unambiguous and the resulting ``id`` (``CODE@where``) is stable
    and deterministic across runs.

    ``message`` defaults to ``f"{where}: {detail}"``, which is what every
    `team_tools` finding has always produced and what its receipts carry. It can
    be supplied instead, and `pipeline` supplies it: those sentences were written
    before this type existed, they carry their own naming (``"source_mode is NEW
    but source artifacts are declared; ..."``), and the suite asserts on several
    of them. Prefixing a field path onto a sentence that already names its field
    would change the English a user reads to gain nothing a caller could not read
    off ``where``. So the two became independent -- that is the one change made
    while moving the type, and it is additive: an `Issue` built the old way still
    produces the old message.
    """

    __slots__ = ("severity", "code", "where", "detail", "message", "id")

    def __init__(self, severity: str, code: str, where: str, detail: str, *,
                 message: str | None = None) -> None:
        if severity not in ("error", "warning"):
            raise ValueError(f"bad severity {severity!r}")
        self.severity = severity
        self.code = code
        self.where = where
        self.detail = detail
        self.message = f"{where}: {detail}" if message is None else message
        self.id = f"{code}@{where}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "severity": self.severity,
            "code": self.code,
            "where": self.where,
            "message": self.message,
        }

    def __str__(self) -> str:
        return self.message

    def __repr__(self) -> str:
        # A failing `assertTrue(..., problems)` prints this list. The default
        # object repr would print addresses, which is the one thing about a
        # finding that is neither stable nor informative.
        return f"Issue({self.id!r}, {self.message!r})"


def error(code: str, where: str, detail: str) -> Issue:
    return Issue("error", code, where, detail)


def warning(code: str, where: str, detail: str) -> Issue:
    return Issue("warning", code, where, detail)


def problem(code: str, where: str, message: str) -> Issue:
    """An error whose English the caller wrote, bound to a field path and a code.

    The constructor `Project.validate` uses. `error()` composes its message from
    `where`; this one takes the sentence as written and lets `where` be the
    machine-readable path, which for a project is the field a caller edits
    (``edit_scopes[1].region_box``) rather than the noun the sentence uses
    (``edit_scope 'drawer'``).
    """
    return Issue("error", code, where, message, message=message)


def has_errors(issues: Iterable[Issue]) -> bool:
    return any(issue.severity == "error" for issue in issues)


def sort_issues(issues: Iterable[Issue]) -> list[Issue]:
    return sorted(issues, key=lambda issue: (issue.severity, issue.id))


def messages(issues: Iterable[Issue]) -> list[str]:
    """The human sentences, in the order the validator produced them.

    What every existing reader of `validate()` wanted: the terminal lines and
    `next_action.unresolved` are lists of sentences and stay lists of sentences.
    The structure goes alongside them, under its own key, rather than changing
    the type of a field four unrelated writers already fill with English.
    """
    return [issue.message for issue in issues]


# ---------------------------------------------------------------------------
# The project-validation vocabulary. See the module docstring for the rule that
# decides which prefix a new code gets.
# ---------------------------------------------------------------------------

# SCHEMA_*: one field, wrong in itself. Fix the field.
SCHEMA_REQUIRED = "SCHEMA_REQUIRED"        # absent, empty, or blank
SCHEMA_TYPE = "SCHEMA_TYPE"                # wrong Python/JSON shape, or wrong format
SCHEMA_ENUM = "SCHEMA_ENUM"                # not one of a closed set
SCHEMA_RANGE = "SCHEMA_RANGE"              # a number outside the bound the field allows
SCHEMA_NON_FINITE = "SCHEMA_NON_FINITE"    # not a finite real number (NaN, Inf, or not a number)

# REF_*: a reference between rows. Fix a row.
REF_UNDECLARED = "REF_UNDECLARED"          # names an id nothing declares
REF_DUPLICATE = "REF_DUPLICATE"            # two rows claim one id
REF_ORDER = "REF_ORDER"                    # ancestry declared out of order (the acyclicity rule)

# ARTIFACT_*: the file on disk disagrees with the declaration. Fix the files.
ARTIFACT_PATH_UNSAFE = "ARTIFACT_PATH_UNSAFE"  # absolute, traversing, or escaping the project
ARTIFACT_MISSING = "ARTIFACT_MISSING"          # a safe path that is not a file here
ARTIFACT_REFUSED = "ARTIFACT_REFUSED"          # present, and unusable: malformed, or the boundary rejected it

# INTENT_*: the declarations are each fine and together describe no one job.
# Fix the decision.
INTENT_CONTRADICTION = "INTENT_CONTRADICTION"  # two declarations that cannot both be meant
INTENT_INCOMPLETE = "INTENT_INCOMPLETE"        # nothing says what to build from
INTENT_UNSUPPORTED = "INTENT_UNSUPPORTED"      # declared, and this build honours no such state

CODES = (
    SCHEMA_REQUIRED, SCHEMA_TYPE, SCHEMA_ENUM, SCHEMA_RANGE, SCHEMA_NON_FINITE,
    REF_UNDECLARED, REF_DUPLICATE, REF_ORDER,
    ARTIFACT_PATH_UNSAFE, ARTIFACT_MISSING, ARTIFACT_REFUSED,
    INTENT_CONTRADICTION, INTENT_INCOMPLETE, INTENT_UNSUPPORTED,
)

# The prefix each code must carry, and what clearing it costs. A new code that
# matches no group is a code with no rule behind it.
CODE_GROUPS = ("SCHEMA_", "REF_", "ARTIFACT_", "INTENT_")
