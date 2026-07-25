from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol


OPENCODE_SCHEMA: Final = "https://opencode.ai/config.json"
OPENCODE_MCP_CONFIG: Final = {
    "3d-modeling-tools": {
        "type": "local",
        "command": ["python", "tools/mcp_server.py"],
        "enabled": True,
    }
}


class OpenCodeRole(Protocol):
    @property
    def role(self) -> str: ...

    @property
    def agent_description(self) -> str: ...

    @property
    def body(self) -> str: ...

    @property
    def reads_files(self) -> bool: ...

    @property
    def edits_files(self) -> bool: ...

    @property
    def writes_files(self) -> bool: ...

    @property
    def runs_shell(self) -> bool: ...

    @property
    def web(self) -> bool: ...

    @property
    def loads_skill(self) -> bool: ...

    @property
    def can_spawn(self) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class OpenCodeFile:
    path: Path
    content: str


def render_opencode_files(root: Path, roles: tuple[OpenCodeRole, ...]) -> tuple[OpenCodeFile, ...]:
    files = [render_opencode_agent(root, role) for role in roles]
    files.append(render_opencode_config(root))
    return tuple(files)


def render_opencode_agent(root: Path, role: OpenCodeRole) -> OpenCodeFile:
    name = f"3d-{role.role}"
    body = role.body.replace("../3d-modeling/", "../../skills/3d-modeling/")
    content = (
        "---\n"
        f"description: {role.agent_description}\n"
        f"mode: {_mode(role)}\n"
        "permission:\n"
        f"{_permission_frontmatter(role)}"
        "---\n"
        f"{body}"
    )
    return OpenCodeFile(root / ".opencode" / "agents" / f"{name}.md", content)


def render_opencode_config(root: Path) -> OpenCodeFile:
    content = json.dumps({"$schema": OPENCODE_SCHEMA, "mcp": OPENCODE_MCP_CONFIG}, indent=2)
    return OpenCodeFile(root / "opencode.json", f"{content}\n")


def _mode(role: OpenCodeRole) -> str:
    if role.can_spawn:
        return "primary"
    return "subagent"


def _permission_frontmatter(role: OpenCodeRole) -> str:
    lines = [
        f"  read: {_allow(role.reads_files)}",
        f"  write: {_allow(role.writes_files)}",
        f"  edit: {_allow(role.edits_files)}",
        f"  bash: {_allow(role.runs_shell)}",
        f"  skill: {_allow(role.loads_skill)}",
        f"  webfetch: {_allow(role.web)}",
        f"  websearch: {_allow(role.web)}",
    ]
    if role.can_spawn:
        lines.append("  task:")
        lines.append('    "*": deny')
        lines.extend(f"    3d-{spawned}: allow" for spawned in role.can_spawn)
    else:
        lines.append("  task: deny")
    return "\n".join(lines) + "\n"


def _allow(enabled: bool) -> str:
    if enabled:
        return "allow"
    return "deny"
