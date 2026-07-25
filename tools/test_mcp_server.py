from __future__ import annotations

from pathlib import Path

import pytest

mcp_fastmcp = pytest.importorskip("mcp.server.fastmcp")

from tools import mcp_server  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]


def test_contracts_validate_tool_passes_example_project() -> None:
    # Given: the checked-in valid contract example project and an installed FastMCP runtime.
    project_dir = ROOT / "skills" / "3d-modeling" / "scripts" / "team_tools" / "examples" / "project_ok"

    # When: the MCP tool wrapper validates the project in-process.
    receipt = mcp_server.contracts_validate(str(project_dir), timestamp="2026-01-01T00:00:00Z")

    # Then: the observable contract validation result is a PASS payload.
    assert receipt["results"]["overall"] == "PASS"
    assert receipt["kind"] == "validate-receipt"


def test_mcp_server_exposes_fastmcp_instance() -> None:
    # Given / When: tools.mcp_server constructs its FastMCP server at import time.
    server = mcp_server.mcp

    # Then: hosts receive a concrete FastMCP stdio server object.
    assert isinstance(server, mcp_fastmcp.FastMCP)
