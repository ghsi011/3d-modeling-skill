from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

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


def test_generation_is_idempotent_and_matches_committed_bytes() -> None:
    """The drift gate, over every generated file at once.

    Reads the committed bytes from disk and never writes: a test that
    regenerates into the working tree would repair the very drift the next
    check is meant to catch, and CI runs pytest before
    ``gen_harness.py --check``.
    """
    # Given: two independent generation passes over the same neutral roles.
    first = {file.path: file.content for file in gen_harness.generate(gen_harness.load_roles())}
    second = {file.path: file.content for file in gen_harness.generate(gen_harness.load_roles())}

    # Then: generation is deterministic ...
    assert first == second

    # ... and every committed artifact is what the current roles produce.
    on_disk = {path: path.read_text(encoding="utf-8") for path in first}
    assert first == on_disk


def test_check_reports_orphaned_generated_files(capsys) -> None:
    """The drift gate must fail when a generated output is left behind."""
    roles = gen_harness.load_roles()
    files = gen_harness.generate(roles)
    orphan = gen_harness.SKILL_DIR / "roles" / "orphan.md"
    orphan.write_text("# stale generated role\n", encoding="utf-8")
    try:
        assert gen_harness.check(files) == 1
        assert "orphan.md" in capsys.readouterr().err
    finally:
        orphan.unlink()


def test_generated_skill_roles_have_exactly_one_h1() -> None:
    """The generator owns the title, so a body H1 must not double it.

    `render_skill` prepends `# 3D <name>` from `display_name`; the neutral bodies
    also open with their own `# 3D <name>`. Before the fix every `roles/*.md`
    rendered that heading twice at the top of the file -- a duplicated document
    title, valid Markdown that reads as a mistake.
    """
    roles = gen_harness.load_roles()
    skill_files = [f for f in gen_harness.generate(roles)
                   if f.path.parent.name == "roles" and f.path.parent.parent.name == "3d-modeling"]

    assert len(skill_files) == 5
    for file in skill_files:
        h1_lines = [line for line in file.content.splitlines() if line.startswith("# ")]
        assert len(h1_lines) == 1, f"{file.path.name} has {len(h1_lines)} H1 headings: {h1_lines}"
        assert h1_lines[0].startswith("# 3D "), h1_lines[0]


def test_generated_router_qualifies_zero_dispatch_claim() -> None:
    """Only the certified inconsequential DIRECT route is dispatch-free."""
    router = next(file.content for file in gen_harness.generate(gen_harness.load_roles())
                  if file.path == gen_harness.SKILL_DIR / "SKILL.md")
    assert "certified `INCONSEQUENTIAL` `DIRECT`" in router
    assert "zero model calls" in router
    assert "`CONSEQUENTIAL` `DIRECT`" in router
    assert "bounded safety review" in router
    assert "`FITTED` or `FULL`" in router
    assert "required reviews" in router


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


def test_the_template_table_is_expanded_and_matches_the_registry() -> None:
    """The charter lists the certified templates so that choosing one is not a
    round trip.

    Hand-copying that list would trade the turn for drift, so it is injected from
    the certified registry at generation time. Two ways it can fail silently: the
    marker survives into the output, leaving the reader an HTML comment where the
    table should be; or injection stops and the charter simply has no list. Both
    look fine in a diff.
    """
    roles = gen_harness.load_roles()
    charter = next(f for f in gen_harness.generate(roles)
                   if f.path.name == "orchestrator.md" and f.path.parent.name == "roles")

    assert gen_harness.TEMPLATE_MARKER not in charter.content
    assert "| template | backend | covers | parameters (all bounded) |" in charter.content

    sys.path.insert(0, str(ROOT / "skills" / "3d-modeling" / "scripts"))
    try:
        from pipeline.templates import registry
        certified = registry()
    finally:
        sys.path.pop(0)

    assert certified, "the registry must not be empty"
    for name, template in certified.items():
        assert f"| `{name}` |" in charter.content, f"{name} is missing from the charter"
        assert template.backend in charter.content, f"{name}'s backend is not shown"
        # Every parameter, because a value outside a bound is not DIRECT and a
        # reader needs to know which knobs exist before choosing a template.
        for parameter in template.bounds:
            assert f"`{parameter}`" in charter.content,                 f"{name}.{parameter} is bounded but not listed"
