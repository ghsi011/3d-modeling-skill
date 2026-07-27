#!/usr/bin/env python3
"""CLI entry point: uv run --project <skill> --frozen python -m team_tools.contracts <validate|hash|status> <path>

Resolves when the skill project is selected via --project.  The shorthand
`uv run --project <skill> --frozen python <skill>/scripts/dt.py validate|status <path>`
also works from any directory.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Every module in this package is imported bare (``import common``, not
# ``import team_tools.common``) so the same source works both as
# `uv run --project <skill> --frozen python -m team_tools.contracts` (selects the skill project, team_tools resolves as a package)
# package) and as a direct script invocation (team_tools/ itself on
# sys.path). This line makes that true in the `-m` case too, since only cwd
# (scripts/) is added to sys.path there, not scripts/team_tools/.
_PACKAGE_DIR = str(Path(__file__).resolve().parent)
if _PACKAGE_DIR not in sys.path:
    sys.path.insert(0, _PACKAGE_DIR)

from common import ContractError, canonical_json  # noqa: E402
from receipts import build_hash_receipt, build_validate_receipt  # noqa: E402
from status import compute_status, exit_code, format_status_lines  # noqa: E402
from validators import CANONICAL_FILENAMES  # noqa: E402


def _write(payload: str, output: Path | None) -> None:
    if output is None:
        sys.stdout.write(payload)
    else:
        output.write_text(payload, encoding="utf-8")


def _parse_required(raw: list[str] | None) -> list[str]:
    """Expand --require values into contract keys.

    Accepts repeated flags and comma-separated lists, plus the shorthand
    ``all``. An unknown name is a usage error rather than a silently ignored
    requirement -- a typo here would otherwise disarm the very gate the caller
    asked for.
    """
    if not raw:
        return []
    names: list[str] = []
    for chunk in raw:
        names.extend(part.strip() for part in chunk.split(",") if part.strip())
    if "all" in names:
        return list(CANONICAL_FILENAMES)
    unknown = sorted(set(names) - set(CANONICAL_FILENAMES))
    if unknown:
        raise ContractError(
            f"--require: unknown contract {', '.join(unknown)} "
            f"(choose from {', '.join(CANONICAL_FILENAMES)}, or all)"
        )
    return names


def _cmd_validate(args: argparse.Namespace) -> int:
    receipt, _project = build_validate_receipt(
        args.path.resolve(), timestamp=args.timestamp, argv=sys.argv[1:],
        required=_parse_required(args.require),
    )
    _write(canonical_json(receipt), args.output.resolve() if args.output else None)
    return 0 if receipt["results"]["overall"] == "PASS" else 1


def _cmd_hash(args: argparse.Namespace) -> int:
    receipt = build_hash_receipt(args.path.resolve(), timestamp=args.timestamp, argv=sys.argv[1:])
    _write(canonical_json(receipt), args.output.resolve() if args.output else None)
    return 0 if not receipt["hash_mismatches"] else 1


def _cmd_status(args: argparse.Namespace) -> int:
    rows = compute_status(args.path.resolve())
    if args.json:
        _write(canonical_json(rows), args.output.resolve() if args.output else None)
    else:
        text = "\n".join(format_status_lines(rows)) + "\n"
        _write(text, args.output.resolve() if args.output else None)
    return exit_code(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uv run --project <skill> --frozen python -m team_tools.contracts",
        description=(
            "Deterministic contract-automation CLI for the 3D team pipeline: validate/hash/"
            "status over the structured-JSON contracts. Passing these "
            "gates is necessary evidence, not proof of geometric or manufacturing correctness."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser(
        "validate", help="Validate every contract JSON in a project dir, cross-check FKs, emit a receipt."
    )
    validate.add_argument("path", type=Path, help="Project directory containing the contract JSON files.")
    validate.add_argument("--output", type=Path, help="Write the receipt here instead of stdout.")
    validate.add_argument("--timestamp", help="Injected timestamp for the receipt (never wall-clock).")
    validate.add_argument(
        "--require",
        action="append",
        metavar="CONTRACT",
        help=(
            "Contract(s) whose absence is an error, not a warning: "
            f"{', '.join(CANONICAL_FILENAMES)}, or all. Repeatable and comma-separated. "
            "Without this, a project missing every contract still exits 0 -- gate on the "
            "contracts your phase actually requires."
        ),
    )
    validate.set_defaults(func=_cmd_validate)

    hash_cmd = subparsers.add_parser(
        "hash", help="Recompute SHA-256 of contracts + declared artifacts (never trusts entered hashes)."
    )
    hash_cmd.add_argument("path", type=Path, help="Project directory.")
    hash_cmd.add_argument("--output", type=Path, help="Write the receipt here instead of stdout.")
    hash_cmd.add_argument("--timestamp", help="Injected timestamp for the receipt (never wall-clock).")
    hash_cmd.set_defaults(func=_cmd_hash)

    status = subparsers.add_parser(
        "status", help="Report each contract's revision plus stale/invalidated downstream bindings."
    )
    status.add_argument("path", type=Path, help="Project directory.")
    status.add_argument("--output", type=Path, help="Write the report here instead of stdout.")
    status.add_argument("--json", action="store_true", help="Emit machine-readable JSON instead of text lines.")
    status.set_defaults(func=_cmd_status)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ContractError as exc:
        sys.stderr.write(f"team_tools.contracts: {exc}\n")
        return 2
    except OSError as exc:
        sys.stderr.write(f"team_tools.contracts: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
