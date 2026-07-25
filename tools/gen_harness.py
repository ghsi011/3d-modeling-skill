#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
# ─── How to run ───
# python tools/gen_harness.py
# python tools/gen_harness.py --check

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias

if __package__:
    from .gen_harness_openai import render_openai_files
    from .gen_harness_opencode import render_opencode_files
else:
    from gen_harness_openai import render_openai_files
    from gen_harness_opencode import render_opencode_files


ROOT: Final = Path(__file__).resolve().parents[1]
ROLE_DIR: Final = ROOT / "skills" / "roles"

Scalar: TypeAlias = str | bool | tuple[str, ...]

REQUIRED_KEYS: Final = frozenset(
    {
        "role",
        "source",
        "agent_description",
        "skill_description",
        "agent_body",
        "display_name",
        "short_description",
        "default_prompt",
        "reads_files",
        "edits_files",
        "writes_files",
        "runs_shell",
        "web",
        "loads_skill",
        "can_spawn",
        "model_hint",
        "permission_mode_hint",
    },
)


@dataclass(frozen=True, slots=True)
class Role:
    role: str
    source: str
    agent_description: str
    skill_description: str
    agent_body: str
    display_name: str
    short_description: str
    default_prompt: str
    reads_files: bool
    edits_files: bool
    writes_files: bool
    runs_shell: bool
    web: bool
    loads_skill: bool
    can_spawn: tuple[str, ...]
    model_hint: str
    permission_mode_hint: str
    body: str


@dataclass(frozen=True, slots=True)
class GeneratedFile:
    path: Path
    content: str


class RoleParseError(Exception):
    def __init__(self, path: Path, detail: str) -> None:
        self.path = path
        self.detail = detail
        super().__init__(f"{path}: {detail}")


def _split_frontmatter(path: Path) -> tuple[list[str], str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise RoleParseError(path, "missing opening frontmatter fence")
    marker = text.find("\n---\n", 4)
    if marker < 0:
        raise RoleParseError(path, "missing closing frontmatter fence")
    frontmatter = text[4:marker].splitlines()
    return frontmatter, text[marker + len("\n---\n") :]


def _parse_scalar(raw: str) -> Scalar:
    value = raw.strip()
    if value == "true":
        return True
    if value == "false":
        return False
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if inner == "":
            return ()
        return tuple(part.strip() for part in inner.split(","))
    return value


def parse_frontmatter(path: Path) -> tuple[dict[str, Scalar], str]:
    lines, body = _split_frontmatter(path)
    data: dict[str, Scalar] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        if ":" not in line:
            raise RoleParseError(path, f"invalid frontmatter line: {line}")
        key, raw = line.split(":", 1)
        if raw.strip() == "|-":
            index += 1
            block: list[str] = []
            while index < len(lines) and (lines[index].startswith("  ") or lines[index] == ""):
                block.append(lines[index][2:] if lines[index].startswith("  ") else "")
                index += 1
            data[key] = "\n".join(block)
            continue
        data[key] = _parse_scalar(raw)
        index += 1
    return data, body


def _require_str(path: Path, data: dict[str, Scalar], key: str) -> str:
    value = data[key]
    if not isinstance(value, str):
        raise RoleParseError(path, f"{key} must be a string")
    return value


def _require_bool(path: Path, data: dict[str, Scalar], key: str) -> bool:
    value = data[key]
    if not isinstance(value, bool):
        raise RoleParseError(path, f"{key} must be a boolean")
    return value


def _require_list(path: Path, data: dict[str, Scalar], key: str) -> tuple[str, ...]:
    value = data[key]
    if not isinstance(value, tuple):
        raise RoleParseError(path, f"{key} must be an inline list")
    return value


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    return value


def parse_role(path: Path) -> Role:
    data, body = parse_frontmatter(path)
    missing = REQUIRED_KEYS.difference(data)
    if missing:
        raise RoleParseError(path, f"missing required keys: {', '.join(sorted(missing))}")
    return Role(
        role=_require_str(path, data, "role"),
        source=_require_str(path, data, "source"),
        agent_description=_require_str(path, data, "agent_description"),
        skill_description=_require_str(path, data, "skill_description"),
        agent_body=_require_str(path, data, "agent_body"),
        display_name=_strip_wrapping_quotes(_require_str(path, data, "display_name")),
        short_description=_strip_wrapping_quotes(_require_str(path, data, "short_description")),
        default_prompt=_strip_wrapping_quotes(_require_str(path, data, "default_prompt")),
        reads_files=_require_bool(path, data, "reads_files"),
        edits_files=_require_bool(path, data, "edits_files"),
        writes_files=_require_bool(path, data, "writes_files"),
        runs_shell=_require_bool(path, data, "runs_shell"),
        web=_require_bool(path, data, "web"),
        loads_skill=_require_bool(path, data, "loads_skill"),
        can_spawn=_require_list(path, data, "can_spawn"),
        model_hint=_require_str(path, data, "model_hint"),
        permission_mode_hint=_require_str(path, data, "permission_mode_hint"),
        body=body,
    )


def load_roles(role_dir: Path = ROLE_DIR) -> tuple[Role, ...]:
    roles = tuple(parse_role(path) for path in sorted(role_dir.glob("*.md")))
    if len(roles) != 5:
        raise RoleParseError(role_dir, f"expected 5 role files, found {len(roles)}")
    return roles


def _agent_tools(role: Role) -> str:
    if role.role == "designer" and not role.can_spawn:
        return "disallowedTools: Agent"
    tools: list[str] = []
    if role.reads_files:
        tools.extend(["Read", "Grep", "Glob"])
    if role.writes_files:
        tools.append("Write")
    if role.edits_files:
        tools.append("Edit")
    if role.runs_shell:
        tools.append("Bash")
    if role.web:
        tools.extend(["WebSearch", "WebFetch"])
    if role.loads_skill:
        tools.append("Skill")
    if role.can_spawn:
        spawned = ", ".join(f"3d-{name}" for name in role.can_spawn)
        tools.append(f"Agent({spawned})")
    return f"tools: {', '.join(tools)}"


def render_agent(role: Role) -> GeneratedFile:
    name = f"3d-{role.role}"
    content = (
        "---\n"
        f"name: {name}\n"
        f"description: {role.agent_description}\n"
        f"{_agent_tools(role)}\n"
        f"model: {role.model_hint}\n"
        f"permissionMode: {role.permission_mode_hint}\n"
        "skills:\n"
        f"  - {name}\n"
        "---\n\n"
        f"{role.agent_body}\n"
    )
    return GeneratedFile(ROOT / ".claude" / "agents" / f"{name}.md", content)


def render_skill(role: Role) -> GeneratedFile:
    name = f"3d-{role.role}"
    content = (
        "---\n"
        f"name: {name}\n"
        f"description: {role.skill_description}\n"
        "---\n"
        f"{role.body}"
    )
    return GeneratedFile(ROOT / "skills" / name / "SKILL.md", content)


def generate(roles: tuple[Role, ...]) -> tuple[GeneratedFile, ...]:
    files: list[GeneratedFile] = []
    for role in roles:
        files.append(render_agent(role))
        files.append(render_skill(role))
    files.extend(GeneratedFile(file.path, file.content) for file in render_opencode_files(ROOT, roles))
    files.extend(GeneratedFile(file.path, file.content) for file in render_openai_files(ROOT, roles))
    return tuple(files)


def check(files: tuple[GeneratedFile, ...]) -> int:
    mismatches = [file.path for file in files if file.path.read_text(encoding="utf-8") != file.content]
    if mismatches:
        print("Generated files differ from disk:", file=sys.stderr)
        for path in mismatches:
            print(f"  {_display_path(path)}", file=sys.stderr)
        return 1
    print(f"OK: {len(files)} generated files match disk")
    return 0


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def write(files: tuple[GeneratedFile, ...]) -> None:
    for file in files:
        file.path.parent.mkdir(parents=True, exist_ok=True)
        file.path.write_text(file.content, encoding="utf-8")
    print(f"Wrote {len(files)} generated files")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Claude 3D role packaging from neutral roles.")
    parser.add_argument("--check", action="store_true", help="fail if generated files differ from disk")
    args = parser.parse_args()
    files = generate(load_roles())
    if args.check:
        return check(files)
    write(files)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
