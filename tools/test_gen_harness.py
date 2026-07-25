from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tools import gen_harness


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_METADATA = {
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
}

OPENAI_AGENT_PATHS = [
    "dist/openai/3d-designer.yaml",
    "dist/openai/3d-metrologist.yaml",
    "dist/openai/3d-orchestrator.yaml",
    "dist/openai/3d-print-engineer.yaml",
    "dist/openai/3d-verifier.yaml",
]


def _parse_generated_frontmatter(content: str) -> dict[str, gen_harness.Scalar]:
    lines = content[4 : content.find("\n---\n", 4)].splitlines()
    data: dict[str, gen_harness.Scalar] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        key, raw = line.split(":", 1)
        if key == "permission" and raw.strip() == "":
            index += 1
            task_allowed: list[str] = []
            while index < len(lines) and lines[index].startswith("  "):
                permission_line = lines[index]
                permission_key, permission_raw = permission_line.strip().split(":", 1)
                if permission_key == "task" and permission_raw.strip() == "":
                    index += 1
                    while index < len(lines) and lines[index].startswith("    "):
                        task_name, task_value = lines[index].strip().split(":", 1)
                        if task_value.strip() == "allow":
                            task_allowed.append(task_name)
                        index += 1
                    continue
                data[f"permission.{permission_key}"] = gen_harness._parse_scalar(permission_raw)
                index += 1
            if task_allowed:
                data["permission.task"] = tuple(task_allowed)
            continue
        data[key] = gen_harness._parse_scalar(raw)
        index += 1
    return data


def test_parse_all_neutral_roles_when_metadata_is_complete() -> None:
    # Given: the five neutral role source files from Task 1.
    role_paths = sorted((ROOT / "skills" / "roles").glob("*.md"))

    # When: each role frontmatter is parsed.
    parsed = [gen_harness.parse_frontmatter(path)[0] for path in role_paths]

    # Then: every role has the generator metadata required for Claude packaging.
    assert len(parsed) == 5
    for frontmatter in parsed:
        assert REQUIRED_METADATA <= frontmatter.keys()


def test_generated_claude_agents_match_current_golden_bytes() -> None:
    # Given: generated Claude agent files from neutral roles.
    generated = [file for file in gen_harness.generate(gen_harness.load_roles()) if ".claude" in file.path.parts]

    # When: the current committed agent files are read from disk.
    expected = {path: path.read_text(encoding="utf-8") for path in (ROOT / ".claude" / "agents").glob("3d-*.md")}

    # Then: generated content is byte-for-byte identical to today's Claude packaging.
    assert {file.path: file.content for file in generated} == expected


def test_generated_role_skills_match_current_golden_bytes() -> None:
    # Given: generated role SKILL.md files from neutral roles.
    generated = [file for file in gen_harness.generate(gen_harness.load_roles()) if file.path.name == "SKILL.md"]

    # When: the current role SKILL.md files are read from disk.
    expected = {
        ROOT / "skills" / f"3d-{role.role}" / "SKILL.md": (ROOT / "skills" / f"3d-{role.role}" / "SKILL.md").read_text(
            encoding="utf-8",
        )
        for role in gen_harness.load_roles()
    }

    # Then: generated content is byte-for-byte identical to today's role skill packaging.
    assert {file.path: file.content for file in generated} == expected


def test_generated_opencode_packaging_uses_plural_agents_path() -> None:
    # Given: OpenCode packaging generated from the five neutral roles.
    generated = [
        file
        for file in gen_harness.generate(gen_harness.load_roles())
        if ".opencode" in file.path.parts or file.path.name == "opencode.json"
    ]

    # When: generated paths are grouped by OpenCode artifact type.
    agent_paths = sorted(path.relative_to(ROOT).as_posix() for path in (file.path for file in generated) if path.suffix == ".md")
    config_paths = [file.path.relative_to(ROOT).as_posix() for file in generated if file.path.name == "opencode.json"]

    # Then: all agents target the official plural directory and no singular path is emitted.
    assert agent_paths == [
        ".opencode/agents/3d-designer.md",
        ".opencode/agents/3d-metrologist.md",
        ".opencode/agents/3d-orchestrator.md",
        ".opencode/agents/3d-print-engineer.md",
        ".opencode/agents/3d-verifier.md",
    ]
    assert config_paths == ["opencode.json"]
    assert all("/.opencode/agent/" not in file.path.as_posix() for file in generated)


def test_generated_opencode_frontmatter_maps_modes_and_permissions() -> None:
    # Given: generated OpenCode agent markdown for every neutral role.
    generated = {
        file.path.name: _parse_generated_frontmatter(file.content)
        for file in gen_harness.generate(gen_harness.load_roles())
        if file.path.parent == ROOT / ".opencode" / "agents" and file.path.suffix == ".md"
    }

    # When: orchestrator and verifier frontmatter are selected.
    orchestrator = generated["3d-orchestrator.md"]
    verifier = generated["3d-verifier.md"]

    # Then: OpenCode receives primary/subagent modes and the machine-consumed permission gates.
    assert orchestrator["mode"] == "primary"
    assert orchestrator["permission.task"] == ("3d-metrologist", "3d-designer", "3d-verifier", "3d-print-engineer")
    for name, frontmatter in generated.items():
        if name != "3d-orchestrator.md":
            assert frontmatter["mode"] == "subagent"
    assert verifier["permission.edit"] == "deny"


def test_generated_opencode_config_has_schema_and_mcp_server() -> None:
    # Given: generated OpenCode root config.
    config = next(file for file in gen_harness.generate(gen_harness.load_roles()) if file.path.name == "opencode.json")

    # When: the JSON content is parsed.
    parsed = json.loads(config.content)

    # Then: schema and the local deterministic-tool MCP server are ready for OpenCode.
    assert parsed["$schema"] == "https://opencode.ai/config.json"
    assert parsed["mcp"] == {
        "3d-modeling-tools": {
            "type": "local",
            "command": ["python", "tools/mcp_server.py"],
            "enabled": True,
        }
    }


def test_generated_opencode_agent_body_uses_neutral_role_body() -> None:
    # Given: the neutral orchestrator role and its generated OpenCode agent.
    role = next(role for role in gen_harness.load_roles() if role.role == "orchestrator")
    generated = next(
        file
        for file in gen_harness.generate((role,))
        if file.path == ROOT / ".opencode" / "agents" / "3d-orchestrator.md"
    )

    # When: the generated markdown body is split from OpenCode frontmatter.
    body = generated.content[generated.content.find("\n---\n", 4) + len("\n---\n") :]

    # Then: OpenCode consumes the full neutral role body as its system prompt.
    assert body == role.body


def test_generated_openai_yaml_extends_harvested_interface_fields() -> None:
    # Given: OpenAI packaging generated from every neutral role.
    generated = {
        file.path.relative_to(ROOT).as_posix(): yaml.safe_load(file.content)
        for file in gen_harness.generate(gen_harness.load_roles())
        if file.path.parent == ROOT / "dist" / "openai"
    }
    role = next(role for role in gen_harness.load_roles() if role.role == "orchestrator")

    # When: the orchestrator portable YAML is selected.
    orchestrator = generated["dist/openai/3d-orchestrator.yaml"]

    # Then: the generic package preserves harvested UI strings and exposes machine-readable role data.
    assert sorted(generated) == OPENAI_AGENT_PATHS
    assert orchestrator["interface"] == {
        "display_name": role.display_name,
        "short_description": role.short_description,
        "default_prompt": role.default_prompt,
    }
    assert orchestrator["role"] == "orchestrator"
    assert orchestrator["description"] == role.skill_description
    assert orchestrator["source"] == "skills/roles/orchestrator.md"
    assert orchestrator["capabilities"]["reads_files"] is True
    assert orchestrator["capabilities"]["can_spawn"] == [
        "metrologist",
        "designer",
        "verifier",
        "print-engineer",
    ]


def test_gitignore_force_includes_openai_dist_packaging() -> None:
    # Given: a generated OpenAI packaging path under the otherwise ignored dist tree.
    target = "dist/openai/3d-orchestrator.yaml"

    # When: git evaluates ignore rules for that path.
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-v", target],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    # Then: the path is force-included by the dist/openai negation rule.
    assert result.returncode == 0, result.stderr
    assert "!dist/openai/**" in result.stdout


def test_generated_opencode_agents_match_current_golden_bytes() -> None:
    # Given: generated OpenCode agent files from neutral roles.
    generated = [
        file
        for file in gen_harness.generate(gen_harness.load_roles())
        if file.path.parent == ROOT / ".opencode" / "agents"
    ]

    # When: the current OpenCode agent files are read from disk.
    expected = {path: path.read_text(encoding="utf-8") for path in (ROOT / ".opencode" / "agents").glob("3d-*.md")}

    # Then: generated content is byte-for-byte identical to committed OpenCode packaging.
    assert {file.path: file.content for file in generated} == expected


def test_check_is_clean_after_two_generations() -> None:
    # Given: the generator CLI and current repository packaging.
    command = [sys.executable, "tools/gen_harness.py"]

    # When: generation runs twice and --check reads the resulting files.
    first = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=10, check=False)
    second = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=10, check=False)
    checked = subprocess.run([*command, "--check"], cwd=ROOT, text=True, capture_output=True, timeout=10, check=False)

    # Then: both writes and the final idempotency check succeed.
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert checked.returncode == 0, checked.stderr


def test_check_reports_mismatch_when_generated_file_differs(tmp_path: Path) -> None:
    # Given: a generated file contract whose on-disk bytes differ.
    target = tmp_path / "3d-demo.md"
    target.write_text("stale\n", encoding="utf-8")
    generated = (gen_harness.GeneratedFile(target, "fresh\n"),)

    # When: the check helper compares generated content to disk.
    exit_code = gen_harness.check(generated)

    # Then: mismatch is reported as a nonzero failure.
    assert exit_code == 1


def test_missing_role_metadata_raises_clear_error(tmp_path: Path) -> None:
    # Given: a malformed neutral role missing the required can_spawn key.
    source = ROOT / "skills" / "roles" / "designer.md"
    malformed = tmp_path / "designer.md"
    shutil.copyfile(source, malformed)
    text = malformed.read_text(encoding="utf-8").replace("can_spawn: []\n", "")
    malformed.write_text(text, encoding="utf-8")

    # When / Then: parsing fails with the missing metadata named in the error.
    with pytest.raises(gen_harness.RoleParseError, match="can_spawn"):
        gen_harness.parse_role(malformed)
