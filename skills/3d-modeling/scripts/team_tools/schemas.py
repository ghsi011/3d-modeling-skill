"""Small generic helpers shared by every contract validator in validators.py.

Deliberately not a schema-DSL/framework: each contract validator in
validators.py calls these functions directly and adds its own cross-field and
foreign-key rules in plain Python. This module only factors out the parts that
are identical across contracts: required/optional/unknown-field handling, enum
checks, and indexed-row (ID-uniqueness) handling.
"""

from __future__ import annotations

from typing import Any, Callable

try:
    from .common import Issue, error, warning
except ImportError:  # pragma: no cover - direct script/test compatibility
    from common import Issue, error, warning

NUMBER = (int, float)

# Enumerations shared across contracts (team-contracts-v4.md naming).


def check_type(value: Any, expected: type | tuple[type, ...]) -> bool:
    if expected is float and isinstance(value, bool):
        return False
    if expected == NUMBER and isinstance(value, bool):
        return False
    if isinstance(expected, tuple):
        return isinstance(value, expected) and not (
            isinstance(value, bool) and bool not in expected
        )
    if expected is bool:
        return isinstance(value, bool)
    return isinstance(value, expected)


def type_name(expected: type | tuple[type, ...]) -> str:
    if isinstance(expected, tuple):
        return "|".join(getattr(item, "__name__", str(item)) for item in expected)
    return getattr(expected, "__name__", str(expected))


def check_object_fields(
    obj: dict[str, Any],
    *,
    required: dict[str, Any],
    optional: dict[str, Any],
    where: str,
) -> list[Issue]:
    """Required-vs-optional + explicit unknown-field policy (warn, never crash).

    ``required``/``optional`` map field name -> expected type (or tuple of types,
    e.g. ``(int, type(None))`` for a nullable integer).
    """
    issues: list[Issue] = []
    for name, expected in required.items():
        if name not in obj:
            issues.append(error("MISSING_FIELD", f"{where}.{name}", "required field is missing"))
        elif not check_type(obj[name], expected):
            issues.append(
                error(
                    "BAD_TYPE",
                    f"{where}.{name}",
                    f"expected {type_name(expected)}, got {type(obj[name]).__name__}",
                )
            )
    for name, expected in optional.items():
        if name in obj and not check_type(obj[name], expected):
            issues.append(
                error(
                    "BAD_TYPE",
                    f"{where}.{name}",
                    f"expected {type_name(expected)}, got {type(obj[name]).__name__}",
                )
            )
    known = set(required) | set(optional)
    for name in obj:
        if name not in known:
            issues.append(
                warning("UNKNOWN_FIELD", f"{where}.{name}", "unknown field (ignored)")
            )
    return issues


def check_enum(obj: dict[str, Any], field: str, allowed: frozenset[str], where: str) -> list[Issue]:
    if field not in obj:
        return []
    value = obj[field]
    if value not in allowed:
        return [
            error(
                "BAD_ENUM",
                f"{where}.{field}",
                f"{value!r} is not one of {sorted(allowed)}",
            )
        ]
    return []


def check_rows(
    rows: Any,
    *,
    where: str,
    row_validator: Callable[[dict[str, Any], str], list[Issue]],
) -> tuple[list[Issue], dict[str, dict[str, Any]]]:
    """Validate a list of ``{"id": ..., ...}`` rows: type, required string id,
    ID uniqueness, and per-row rules from ``row_validator``. Returns the issues
    plus an id -> row index for foreign-key checks elsewhere.
    """
    issues: list[Issue] = []
    index: dict[str, dict[str, Any]] = {}
    if not isinstance(rows, list):
        issues.append(error("BAD_TYPE", where, "expected a list"))
        return issues, index
    for position, row in enumerate(rows):
        row_where = f"{where}[{position}]"
        if not isinstance(row, dict):
            issues.append(error("BAD_TYPE", row_where, "expected an object"))
            continue
        row_id = row.get("id")
        if not isinstance(row_id, str) or not row_id.strip():
            issues.append(error("MISSING_ID", row_where, "row is missing a required string 'id'"))
        else:
            row_where = f"{where}[{row_id}]"
            if row_id in index:
                issues.append(error("DUPLICATE_ID", where, f"duplicate id '{row_id}'"))
            else:
                index[row_id] = row
        issues.extend(row_validator(row, row_where))
    return issues, index


def check_fk(
    ids: Any,
    *,
    field: str,
    where: str,
    known: dict[str, Any],
    known_label: str,
) -> list[Issue]:
    """Foreign-key check: every id in ``ids`` (a list of strings) must be a key of
    ``known``.
    """
    issues: list[Issue] = []
    if ids is None:
        return issues
    if not isinstance(ids, list):
        issues.append(error("BAD_TYPE", f"{where}.{field}", "expected a list of id strings"))
        return issues
    for index, ref_id in enumerate(ids):
        if not isinstance(ref_id, str):
            issues.append(
                error("BAD_TYPE", f"{where}.{field}[{index}]", "expected a string id")
            )
            continue
        if ref_id not in known:
            issues.append(
                error(
                    "FK_MISSING",
                    f"{where}.{field}[{index}]",
                    f"'{ref_id}' is not a known {known_label} id",
                )
            )
    return issues
