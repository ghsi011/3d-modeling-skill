#!/usr/bin/env python3
"""FastMCP stdio server for the deterministic 3D-modeling tools."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "skills" / "3d-modeling" / "scripts"
TEAM_TOOLS_DIR = SCRIPTS_DIR / "team_tools"

for import_path in (str(SCRIPTS_DIR), str(TEAM_TOOLS_DIR)):
    if import_path not in sys.path:
        sys.path.insert(0, import_path)

from mcp.server.fastmcp import FastMCP  # noqa: E402
from designer_toolkit import bundle, metrics  # noqa: E402
from team_preflight import (  # noqa: E402
    load_json,
    support_audit,
    validate_interfaces,
    validate_receipts,
)
from team_tools.receipts import build_hash_receipt, build_validate_receipt  # noqa: E402
from team_tools.status import compute_status  # noqa: E402


mcp = FastMCP("3d-modeling deterministic tools")


def _json_object(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value))


def _json_list(value: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return json.loads(json.dumps(value))


@mcp.tool()
def team_preflight_support(stl_path: str, plan_path: str, rule_id: str) -> dict[str, Any]:
    """Run the support-audit/downward-facing-surface preflight screen."""
    result, _maximum_area = support_audit(
        stl_path=Path(stl_path).resolve(),
        plan_path=Path(plan_path).resolve(),
        rule_id=rule_id,
    )
    return _json_object(result)


@mcp.tool()
def team_preflight_validate(stl_path: str, plan_path: str, readiness_path: str) -> dict[str, Any]:
    """Validate preflight receipt hashes and edge/support/interface coverage."""
    return _json_object(
        validate_receipts(
            stl_path=Path(stl_path).resolve(),
            plan_path=Path(plan_path).resolve(),
            readiness_path=Path(readiness_path).resolve(),
        )
    )


@mcp.tool()
def team_preflight_interfaces(plan_path: str) -> dict[str, Any]:
    """Validate the print_plan_checks.json interfaces fit-strategy block."""
    return _json_object(validate_interfaces(load_json(Path(plan_path).resolve())))


@mcp.tool()
def contracts_validate(project_dir: str, timestamp: str | None = None) -> dict[str, Any]:
    """Validate structured team contract JSON files and return a receipt."""
    receipt, _project = build_validate_receipt(
        Path(project_dir).resolve(),
        timestamp=timestamp,
        argv=["validate", project_dir],
    )
    return _json_object(receipt)


@mcp.tool()
def contracts_hash(project_dir: str, timestamp: str | None = None) -> dict[str, Any]:
    """Recompute contract and artifact SHA-256 values for a project."""
    return _json_object(
        build_hash_receipt(
            Path(project_dir).resolve(),
            timestamp=timestamp,
            argv=["hash", project_dir],
        )
    )


@mcp.tool()
def contracts_status(project_dir: str) -> list[dict[str, Any]]:
    """Report contract revision, stale binding, and invalidation status rows."""
    return _json_list(compute_status(Path(project_dir).resolve()))


@mcp.tool()
def designer_measure(stl_path: str) -> dict[str, Any]:
    """Measure an exported STL mesh with designer_toolkit metrics."""
    return _json_object(asdict(metrics.measure(stl_path)))


@mcp.tool()
def designer_finalize(stl_path: str, plan_path: str | None = None) -> dict[str, Any]:
    """Build the designer_toolkit Phase-4 evidence bundle for an exported STL."""
    plan: dict[str, Any] = {}
    if plan_path is not None:
        plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    return _json_object(
        bundle.finalize(
            stl_path,
            plan.get("out_stem", stl_path.rsplit(".", 1)[0]),
            datums=plan.get("datums", ()),
            reference=plan.get("reference"),
            insertion=plan.get("insertion"),
            orientation_transform=plan.get("orientation_transform"),
            overhang_threshold=plan.get(
                "overhang_threshold",
                metrics.DEFAULT_DOWNWARD_NORMAL_Z_MAX,
            ),
            also_step=False,
        )
    )


def main() -> None:
    """Run the server over stdio; stdout is reserved for MCP frames."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
