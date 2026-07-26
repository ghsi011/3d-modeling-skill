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
    """Always an allowlist, never a deny-list.

    A deny-list admits every tool it does not name, including the host's whole
    MCP surface. One measured designer run carried a deny-list and paid ~16k
    tokens of unused tool definitions at turn one, re-billed across all 256 of
    its turns -- more than it spent on required reading. An allowlist that omits
    `Agent` denies spawning just as effectively.
    """
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


SKILL_NAME: Final = "3d-modeling"


def render_agent(role: Role) -> GeneratedFile:
    """Every role requests the one skill.

    There is no `3d-designer` skill to request. `3d-modeling` is the only one,
    and its `roles/` directory holds all five charters. An agent naming a skill
    that does not exist does not fail loudly; it just starts with no skill
    loaded, which is the whole charter missing.
    """
    name = f"3d-{role.role}"
    content = (
        "---\n"
        f"name: {name}\n"
        f"description: {role.agent_description}\n"
        f"{_agent_tools(role)}\n"
        f"model: {role.model_hint}\n"
        f"permissionMode: {role.permission_mode_hint}\n"
        "skills:\n"
        f"  - {SKILL_NAME}\n"
        "---\n\n"
        f"{role.agent_body}\n"
    )
    return GeneratedFile(ROOT / ".claude" / "agents" / f"{name}.md", content)


SKILL_DIR = ROOT / "skills" / "3d-modeling"


TEMPLATE_MARKER = "<!-- TEMPLATE-TABLE -->"


def _template_table() -> str:
    """The shipped templates, listed from the templates themselves.

    `dt.py templates` exists and prints exactly this, and asking for it cost a
    round trip -- 8 to 47 seconds -- to learn something that changes only when
    this repo changes. On the `DIRECT` route, where the whole job is four
    commands, one of them was a lookup.

    Hand-copying the list into the charter would have traded that turn for the
    drift this repo keeps finding, so it is generated and `--check` fails the
    build when it moves.
    """
    import sys
    sys.path.insert(0, str(ROOT / "skills" / "3d-modeling" / "scripts"))
    try:
        from designer_toolkit.templates import CATALOGUE
    finally:
        sys.path.pop(0)
    rows = ["| template | covers | call |", "|---|---|---|"]
    rows += [f"| `{name}` | {covers} | `{call}` |"
             for name, (covers, call) in CATALOGUE.items()]
    return "\n".join(rows)


def _expand(body: str) -> str:
    return body.replace(TEMPLATE_MARKER, _template_table())


def _rewrite_shared_links(body: str, prefix: str) -> str:
    """Repoint `../3d-modeling/...` at its place inside the single skill.

    In `skills/roles/` a role sits beside `skills/3d-modeling/`, so it reaches
    shared assets as `../3d-modeling/references/...`. Inside the skill those
    assets are siblings (for SKILL.md) or one level up (for roles/*.md).
    """
    return (
        body.replace("../3d-modeling/references/", f"{prefix}references/")
        .replace("../3d-modeling/scripts/", f"{prefix}scripts/")
    )


def render_skill(role: Role) -> GeneratedFile:
    """Every role is a file under `roles/`, the orchestrator included.

    One installable skill, not one per role: the roles are not independently
    useful (a designer with no commission refuses to start, by design), and
    sibling skills that reach each other by relative path break the moment a
    host installs one of them on its own.
    """
    return GeneratedFile(
        SKILL_DIR / "roles" / f"{role.role}.md",
        f"# 3D {role.display_name.removeprefix('3D ')}\n\n"
        f"{_rewrite_shared_links(_expand(role.body), '../')}",
    )


def render_router(roles: tuple[Role, ...]) -> GeneratedFile:
    """`SKILL.md`: which role you are, and where to read it.

    A router, so that requesting the skill costs a name and five links. Make
    `SKILL.md` the orchestrator's charter instead and every specialist context
    loads the routing rules, the consequence classes and the dispatch protocol
    to read its own file -- none of which a designer acts on, and all of which
    each dispatch pays for.
    """
    orchestrator = next(r for r in roles if r.role == "orchestrator")
    lines = [
        "---",
        "name: 3d-modeling",
        f"description: {orchestrator.skill_description}",
        "---",
        "",
        "# 3D modeling",
        "",
        "Five roles that speak to each other through file contracts rather than chat. Read the",
        "one your dispatch names and only that one: each file is the whole charter for its job,",
        "and the others are cost you carry without using.",
        "",
    ]
    for role in sorted(roles, key=lambda r: (r.role != "orchestrator", r.role)):
        tail = " Start here when you are governing a job." if role.role == "orchestrator" else ""
        lines.append(
            f"- [`roles/{role.role}.md`](roles/{role.role}.md) — {role.short_description}.{tail}"
        )
    lines += [
        "",
        "Shared assets sit beside them: [`references/`](references/) for the contract spec and",
        "the design guidance, [`scripts/`](scripts/) for the deterministic tooling.",
        "`scripts/dt.py` is the toolkit launcher — invoke it by absolute path from wherever the",
        "job is, and ask `dt.py doctor` what the interpreter you have can actually do.",
        "",
    ]
    return GeneratedFile(SKILL_DIR / "SKILL.md", "\n".join(lines))


def generate(roles: tuple[Role, ...]) -> tuple[GeneratedFile, ...]:
    files: list[GeneratedFile] = [render_router(roles)]
    for role in roles:
        files.append(render_agent(role))
        files.append(render_skill(role))
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
