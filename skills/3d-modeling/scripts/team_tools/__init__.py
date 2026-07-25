"""team_tools -- deterministic contract-automation package for the 3D team pipeline.

Net-new, self-contained package. Depends only on the Python standard library plus
the already-installed ``trimesh`` and ``numpy`` (used for artifact mesh checks).

This package does not modify, and never imports, ``team_preflight.py`` -- it is a
separate, additive layer that operates on the structured-JSON contract
representation of the team contracts (added in Sprint 1A; see CHANGELOG.md).
"""

from __future__ import annotations

# Canonical values live in common.py (imported bare, without a "team_tools."
# prefix, everywhere inside the package) so the CLI and tests work whether
# invoked as `python -m team_tools.contracts ...` or `python team_tools/...py`
# directly -- see the sys.path bootstrap at the top of contracts.py /
# test_contracts.py for why. Re-exported here only for callers that import the
# package normally, e.g. `from team_tools import TOOL_VERSION`.
try:  # pragma: no cover - trivial re-export
    from .common import TOOL_NAME, TOOL_SCHEMA_VERSION, TOOL_VERSION
except ImportError:  # pragma: no cover - package not fully on sys.path yet
    TOOL_NAME = "team_tools.contracts"
    TOOL_VERSION = "1.0"
    TOOL_SCHEMA_VERSION = 1
