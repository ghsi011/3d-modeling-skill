from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class OpenAIRole(Protocol):
    @property
    def role(self) -> str: ...

    @property
    def skill_description(self) -> str: ...

    @property
    def display_name(self) -> str: ...

    @property
    def short_description(self) -> str: ...

    @property
    def default_prompt(self) -> str: ...

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
class OpenAIFile:
    path: Path
    content: str


def render_openai_files(root: Path, roles: tuple[OpenAIRole, ...]) -> tuple[OpenAIFile, ...]:
    return tuple(render_openai_role(root, role) for role in roles)


def render_openai_role(root: Path, role: OpenAIRole) -> OpenAIFile:
    name = f"3d-{role.role}"
    content = (
        "interface:\n"
        f"  display_name: {_quoted(role.display_name)}\n"
        f"  short_description: {_quoted(role.short_description)}\n"
        f"  default_prompt: {_quoted(role.default_prompt)}\n"
        f"role: {role.role}\n"
        f"description: {_quoted(_strip_wrapping_quotes(role.skill_description))}\n"
        "capabilities:\n"
        f"  reads_files: {_bool(role.reads_files)}\n"
        f"  edits_files: {_bool(role.edits_files)}\n"
        f"  writes_files: {_bool(role.writes_files)}\n"
        f"  runs_shell: {_bool(role.runs_shell)}\n"
        f"  web: {_bool(role.web)}\n"
        f"  loads_skill: {_bool(role.loads_skill)}\n"
        f"  can_spawn: {_inline_list(role.can_spawn)}\n"
        f"source: skills/roles/{role.role}.md\n"
    )
    return OpenAIFile(root / "dist" / "openai" / f"{name}.yaml", content)


def _quoted(value: str) -> str:
    return json.dumps(value)


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    return value


def _bool(value: bool) -> str:
    if value:
        return "true"
    return "false"


def _inline_list(values: tuple[str, ...]) -> str:
    if not values:
        return "[]"
    return f"[{', '.join(_quoted(value) for value in values)}]"
