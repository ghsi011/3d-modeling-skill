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
    """The certified templates, listed from the registry itself.

    Choosing a starting point must not cost a round trip -- 8 to 47 seconds to
    learn something that changes only when this repo changes. Hand-copying the
    list would have traded that turn for drift, so it is generated and
    `gen_harness --check` fails the build when it moves.

    Parameters rather than a call signature: every one is bounded, and a job
    outside a bound is not `DIRECT`, so the names are what a reader needs.
    """
    import sys
    sys.path.insert(0, str(ROOT / "skills" / "3d-modeling" / "scripts"))
    try:
        from pipeline.templates import registry
        certified = registry()
    finally:
        sys.path.pop(0)
    rows = ["| template | backend | covers | parameters (all bounded) |",
            "|---|---|---|---|"]
    for name, template in sorted(certified.items()):
        params = ", ".join(f"`{p}`" for p in sorted(template.bounds))
        rows.append(f"| `{name}` | {template.backend} | {template.covers} | {params} |")
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


def _strip_leading_h1(body: str) -> str:
    """Drop a body's own opening H1 so the generated title is not doubled.

    `render_skill` prepends the canonical title from `display_name`. A neutral
    role body that also opens with its own `# 3D ...` heading then rendered two
    identical H1s at the top of every `roles/*.md` -- valid Markdown, but a
    duplicated document title. The generator owns the visible title; a body H1 is
    redundant, so it is removed here at the one place that adds the real one.
    """
    lines = body.split("\n")
    index = 0
    while index < len(lines) and lines[index].strip() == "":
        index += 1
    if index < len(lines) and lines[index].startswith("# "):
        del lines[index]
        if index < len(lines) and lines[index].strip() == "":
            del lines[index]
        return "\n".join(lines)
    return body


def render_skill(role: Role) -> GeneratedFile:
    """Every role is a file under `roles/`, the orchestrator included.

    One installable skill, not one per role: the roles are not independently
    useful (a designer with no commission refuses to start, by design), and
    sibling skills that reach each other by relative path break the moment a
    host installs one of them on its own.
    """
    body = _rewrite_shared_links(_expand(_strip_leading_h1(role.body)), "../")
    return GeneratedFile(
        SKILL_DIR / "roles" / f"{role.role}.md",
        f"# 3D {role.display_name.removeprefix('3D ')}\n\n{body}",
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
        "A contract-first pipeline for designing printable parts. The contract is written",
        "before the geometry and frozen once the build starts, so an expectation cannot",
        "vanish with the code that produced it; the exported mesh is what gets measured,",
        "whatever kernel made it.",
        "",
        "Deterministic software owns structure, provenance, artifact identity, repeatable",
        "measurement and resource limits. Agents own interpretation, geometry, trade-offs",
        "and visual engineering judgment. More expensive roles are added only when the job",
        "contains evidence or consequences that they can actually evaluate.",
        "",
        "## One command surface",
        "",
        "```bash",
        "uv run design-tool init <project> --job-id J --source-mode NEW|MODIFY|RECONSTRUCT \\",
        "    --consequence INCONSEQUENTIAL|CONSEQUENTIAL --updated-utc <iso8601>",
        "uv run design-tool route  <project>     # decide and record the route",
        "uv run design-tool run    <project>     # every deterministic stage, then stop cleanly",
        "uv run design-tool run    <project> --restart   # discard this branch's conclusions",
        "uv run design-tool status <project>     # route, bindings, what it is waiting for",
        "uv run design-tool branch <project> --from <alt|.> --id <name> --reason \"<text>\"",
        "uv run design-tool branch <project> --activate <alt|.>",
        "uv run design-tool branch <project> --disposition <state> --basis <basis> [--of <alt>]",
        "uv run design-tool doctor               # what this interpreter can actually do",
        "uv run design-tool selftest             # does this installation build what it certifies",
        "```",
        "",
        "`branch` declares a competing formulation of the same job. It copies nothing:",
        "shared requirements, source artifacts and evidence stay in `project.json`, and",
        "only what differs — the proposal, the model, the artifacts, the acceptance",
        "revision, the reviews and every receipt — lives under `alternatives/<id>/`. A",
        "review answered for one branch is refused by its sibling. A project that never",
        "branches pays nothing: no directory appears and no payload gains a field.",
        "",
        "`--disposition` moves a formulation between the seven lifecycle states and each",
        "one changes something: `ACTIVE`, `PREFERRED` (at most one; switching demotes the",
        "previous holder rather than erasing it) and `FALLBACK` (retained, still runnable,",
        "and named by `status` when the current formulation has no claim) may be worked",
        "under; `PAUSED` is parked and keeps its instruction; `REJECTED`, `SUPERSEDED` and",
        "`MERGED` are concluded, clear their instruction and keep every receipt. Every",
        "state but `ACTIVE` must say what it rests on with `--basis`. Transitions and",
        "restarts are recorded in `lifecycle.json`.",
        "",
        "`run --restart` discards what *this* formulation concluded — its receipts and its",
        "review answers — and keeps what it concluded from: the frozen contract, the",
        "proposal, the model, the build cache and every sibling. Use it when an answer",
        "whose bindings all still hold is one you no longer trust; ordinary staleness is",
        "already handled by re-running.",
        "",
        "`project.json` is the one machine-authoritative description of a job. Fill it in,",
        "then run `design-tool run <project>` and keep running the identical command.",
        "Every stage the tool can do deterministically, it does; when agent judgement is",
        "genuinely required it writes `next_action.json`, stops, and continues from that",
        "state on the next invocation. A finished run deletes the file.",
        "",
        "Exit codes: `0` done, `1` a gate failed, `2` the project is malformed, `3`",
        "something has to be answered or built before it can continue — read",
        "`next_action.json`.",
        "",
        "`design-tool run-job <dir>` is the deprecated predecessor. It reads `job.json`",
        "directly and still works; `run` adapts a bare `job.json` into a project on first",
        "use and keeps it routing under the legacy rules.",
        "",
        "## Four routes",
        "",
        "The route is decided by **what has to be recovered, and how many things have to",
        "agree**. Consequence never selects a route — it adds the mandatory safety pass.",
        "Source mode never selects one either — `MODIFY` is not automatically `FITTED`.",
        "",
        "| route | when | work |",
        "|---|---|---|",
        "| `DIRECT` | a certified template covers the whole shape, every value is known or "
        "chosen, nothing is recovered from evidence | zero design-agent calls |",
        "| `CUSTOM` | geometry is novel or outside certified bounds; every value is stated, "
        "cited, inherited from a trusted artifact, or chosen by design | one designer "
        "commission |",
        "| `FITTED` | acceptance depends on one externally owned object — photos, calipers, "
        "official spec, or source CAD needing reconciliation | metrologist, print plan, "
        "designer, fresh verifier |",
        "| `FULL` | several interacting parts, more than one external interface, declared "
        "motion, mechanisms, parallel candidates | the complete workflow |",
        "",
        "`CUSTOM` covers both from-scratch authoring and modification of an existing",
        "design. It requires an independent verification when the job is",
        "`CONSEQUENTIAL`, has an external mating interface, declares motion, needs",
        "imported-geometry repair, has open questions, or when one is asked for.",
        "",
        "A `CUSTOM` job is one designer commission that returns two files:",
        "`design_proposal.json`, which says what the part must measure, and `model.py`,",
        "which says how it is built. The pipeline validates and freezes the proposal,",
        "generates `acceptance_contract.json` from it and the system-owned inputs, and",
        "only then executes the model — so the built artifact cannot influence what it is",
        "judged against. Acceptance bands are the pipeline's, not the designer's. Changing",
        "the proposal cuts a new contract revision, invalidates the receipts issued",
        "against the old one, and says so in `acceptance_history.json`.",
        "",
        "**Any job that declares an edit scope cannot claim success right now.** A",
        "`MODIFY` job declares one `edit_scopes` entry per artifact it modifies, and the",
        "modification cap follows those scopes, not the `source_mode` label beside them —",
        "an edit scope over a supplied artifact carries the preservation obligation on",
        "every builder and every route, and every declared scope is owed its own audit",
        "row. These jobs build, screen, gate and write every receipt, and a designer can",
        "iterate against real measurements — but",
        "the run reports `EXPERIMENTAL_UNAVAILABLE` instead of `COMMISSIONED` or",
        "`VERIFIED`, because the preservation audit's sample density is not yet derived",
        "from a declared minimum detectable defect size. `final_status.json` carries",
        "`lane_status` and the reason, and a genuine `FAILED` is still reported as",
        "`FAILED`.",
        "",
        "A `FITTED` or `FULL` job built from authored geometry reports `UNSUPPORTED`",
        "instead: the bounded metrology recovery those routes owe is defined only against",
        "a certified template's bounds, so there is nothing to recover into. That is a",
        "limit of what this build can do rather than a stage that is coming — name a",
        "certified template, or drop the obligation. The repository's",
        "`docs/adr/0002-route-and-contract-authority.md` records the rest.",
        "",
        "`VERIFIED` requires an independent context on every route. Nothing else reaches",
        "it.",
        "",
        "## Source mode",
        "",
        "`NEW` creates geometry from requirements. `MODIFY` starts from one or more",
        "supplied artifacts that are authoritative. `RECONSTRUCT` recovers geometry from",
        "evidence. A `MODIFY` job declares an edit scope: what must be preserved, what may",
        "be removed, what is being added, and which named region the edit lives in.",
        "",
        "Dimensions carry their provenance and are never collapsed into each other:",
        "`STATED` by the user, `INHERITED` from a supplied artifact (bound to its hash),",
        "`MEASURED` from evidence, `CHOSEN` by design.",
        "",
        "## Roles",
        "",
        "Read the one your dispatch names and only that one — the others are cost you",
        "carry without using.",
        "",
    ]
    for role in sorted(roles, key=lambda r: (r.role != "orchestrator", r.role)):
        tail = " Start here when you are governing a job." if role.role == "orchestrator" else ""
        lines.append(
            f"- [`roles/{role.role}.md`](roles/{role.role}.md) — {role.short_description}.{tail}"
        )
    lines += [
        "",
        "Shared assets sit beside them: [`references/`](references/) for the design guidance",
        "and the verification patterns, [`scripts/`](scripts/) for the tooling.",
        "",
        "The toolchain is four things and no more: `uv`, `build123d` for exact B-rep,",
        "`trimesh` for measuring the exported mesh, and `manifold3d` as the boolean engine,",
        "named explicitly at every call. There is no other CAD kernel and no silent",
        "fallback to one.",
        "",
        "Read `final_status.json` when a job finishes: `allowed_claim` states exactly what",
        "was established, and it is the sentence to repeat rather than paraphrase.",
        "`COMMISSIONED` is not `VERIFIED`, and neither one is \"safe\" — a printed and",
        "tested part is what makes a part ready to use, and this pipeline does not print.",
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
    mismatches = [
        file.path
        for file in files
        if not file.path.is_file()
        or file.path.read_text(encoding="utf-8") != file.content
    ]
    expected = {file.path for file in files}
    actual = {
        *((SKILL_DIR / "roles").glob("*.md") if (SKILL_DIR / "roles").is_dir() else ()),
        *((ROOT / ".claude" / "agents").glob("3d-*.md")
          if (ROOT / ".claude" / "agents").is_dir() else ()),
    }
    orphans = sorted(actual - expected)
    if mismatches or orphans:
        print("Generated files differ from disk:", file=sys.stderr)
        for path in mismatches:
            print(f"  {_display_path(path)}", file=sys.stderr)
        if orphans:
            print("Orphan generated files:", file=sys.stderr)
            for path in orphans:
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
