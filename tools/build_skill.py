#!/usr/bin/env python3
"""Build the deterministic .skill zip artifact for the 3D modeling pipeline.

One archive: `skills/3d-modeling/` packed verbatim, router and all five role
files together. `gen_harness.render_skill` explains why it is one and not one
per role.

Usage:
    uv run python tools/build_skill.py [--out dist/skills]
"""
from __future__ import annotations

import argparse
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / "skills"
SKILL_DIR = SKILLS_DIR / "3d-modeling"
ARTIFACT_NAME = "3d-modeling.skill"

# A bundle is a runtime surface, not a dev checkout. The suites and their
# fixtures are a third of the packed bytes, no shipped skill runs them, and no
# role or reference tells an agent to. They stay in the repo, where CI runs them.
EXCLUDE_DIRS = {"__pycache__", ".ruff_cache", ".pytest_cache", "examples"}
EXCLUDE_EXTS = {".pyc"}
EXCLUDE_PREFIXES = ("test_",)
FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def _should_include(path: Path) -> bool:
    if path.suffix in EXCLUDE_EXTS or path.name.startswith(EXCLUDE_PREFIXES):
        return False
    for part in path.parts:
        if part in EXCLUDE_DIRS:
            return False
    return True


def _collect_files(base: Path) -> list[Path]:
    if not base.exists():
        return []
    return [p for p in sorted(base.rglob("*")) if p.is_file() and _should_include(p)]


def _write_zip(zip_path: Path, entries: list[tuple[str, bytes]]) -> None:
    entries_sorted = sorted(entries, key=lambda e: e[0])
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for arcname, data in entries_sorted:
            info = zipfile.ZipInfo(arcname, date_time=FIXED_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, data)


def _build_skill(out_dir: Path) -> Path:
    """Pack `skills/3d-modeling/` verbatim.

    The tree on disk is already the shipped shape -- SKILL.md at the root,
    roles/ beside it, references/ and scripts/ beside those -- so every relative
    link inside the archive is the same link that resolves in the repo. That is
    the property `test_build_skill` asserts, and the one whose absence shipped
    an archive whose every required-reading link pointed one directory above
    the installed skill.
    """
    zip_path = out_dir / ARTIFACT_NAME
    entries = [
        (f.relative_to(SKILL_DIR).as_posix(), f.read_bytes())
        for f in _collect_files(SKILL_DIR)
    ]
    entries.append(("pyproject.toml", _bundle_pyproject().encode("utf-8")))
    # The lockfile travels with the project file that needs it. Without it an
    # installed bundle has no lockfile to identify its toolchain by, and the
    # cache key falls back to installed versions -- correct, but weaker than the
    # lock this was actually tested against.
    entries.append(("uv.lock", (ROOT / "uv.lock").read_bytes()))
    # README and LICENSE so pyproject.toml's readme/license fields resolve.
    # The README is bundle-local (not the repo's, which links outside the archive).
    entries.append(("README.md", _bundle_readme().encode("utf-8")))
    entries.append(("LICENSE", (ROOT / "LICENSE").read_bytes()))
    _write_zip(zip_path, entries)
    return zip_path


def _bundle_pyproject() -> str:
    """The project file that makes `design-tool` exist inside the bundle.

    `SKILL.md`'s first command is `uv run design-tool run-job`. `design-tool` is
    a console script, so without a project file beside it an installed bundle
    answered that command with `error: Failed to spawn: design-tool -- program
    not found`: the shipped artifact could not run the one command it leads with.

    The dependency list is read from the repository's own `pyproject.toml` rather
    than restated, because a second copy of a version floor drifts from the first
    and the bundle would then resolve a different toolchain than the tests ran
    against.  The same applies to optional-dependencies, dependency-groups,
    tool.setuptools and any uv-specific configuration — only the setuptools
    package-discovery paths are adjusted for the bundle layout.

    Raises:
        ValueError: if the root pyproject.toml lacks expected sections or the
            setuptools paths have an unexpected shape.
    """
    root = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = root["project"]

    # --- fail-early assertions on expected root structure ------------------
    if "dependencies" not in project:
        raise ValueError("root pyproject.toml: [project] has no 'dependencies'")
    if "build-system" not in root:
        raise ValueError("root pyproject.toml: missing [build-system]")
    if not isinstance(project.get("scripts"), dict):
        raise ValueError("root pyproject.toml: [project.scripts] must be a dict")

    st = root.get("tool", {}).get("setuptools", {})
    if st.get("package-dir", {}).get("", "") != "skills/3d-modeling/scripts":
        raise ValueError(
            'root pyproject.toml: expected tool.setuptools.package-dir.'
            '"" == "skills/3d-modeling/scripts", '
            f'got {st.get("package-dir")!r}')
    find_where = st.get("packages", {}).get("find", {}).get("where")
    if find_where != ["skills/3d-modeling/scripts"]:
        raise ValueError(
            "root pyproject.toml: expected "
            'tool.setuptools.packages.find.where == ["skills/3d-modeling/scripts"], '
            f"got {find_where!r}")
    # -----------------------------------------------------------------------

    lines: list[str] = [
        "# Generated by tools/build_skill.py -- do not edit inside the bundle.",
        "#",
        "# This exists so `uv run design-tool run-job <project-dir>`, the command SKILL.md",
        "# opens with, resolves in an installed skill and not only in the source repo.",
        "[project]",
        f'name = "{project["name"]}"',
        f'version = "{project["version"]}"',
        f'description = "{_toml_escape(project["description"])}"',
        'readme = "README.md"',
        f'requires-python = "{project["requires-python"]}"',
        'license = { file = "LICENSE" }',
    ]

    # Preserve authors (TOML inline tables: [{ name = "Idan" }]).
    if "authors" in project:
        parts = []
        for author in project["authors"]:
            inner = ", ".join(f'{k} = "{v}"' for k, v in author.items())
            parts.append("{" + inner + "}")
        lines.append("authors = [" + ", ".join(parts) + "]")

    # preserve keywords if present
    if "keywords" in project:
        kw = ", ".join(f'"{s}"' for s in project["keywords"])
        lines.append(f"keywords = [{kw}]")

    # dependencies
    lines.append("dependencies = [")
    for d in project["dependencies"]:
        lines.append(f'    "{d}",')
    lines.append("]")

    # optional-dependencies — all extras under a single header
    optional = project.get("optional-dependencies", {})
    if optional:
        lines.append("\n[project.optional-dependencies]")
        for extra_name, extra_deps in optional.items():
            lines.append(f"{extra_name} = [")
            for dep in extra_deps:
                lines.append(f'    "{dep}",')
            lines.append("]")

    # dependency-groups
    dep_groups = root.get("dependency-groups", {})
    if dep_groups:
        lines.append("\n[dependency-groups]")
        for group_name, group_deps in dep_groups.items():
            lines.append(f"{group_name} = [")
            for dep in group_deps:
                lines.append(f'    "{dep}",')
            lines.append("]")

    # console scripts
    scripts = project.get("scripts", {})
    if scripts:
        lines.append("\n[project.scripts]")
        for cmd, target in scripts.items():
            lines.append(f'{cmd} = "{target}"')

    # project.urls (preserved from root) — emitted after all [project] keys so
    # keys like dependencies are not inadvertently placed under the urls sub-table.
    urls = project.get("urls", {})
    if urls:
        lines.append("\n[project.urls]")
        for key, value in urls.items():
            lines.append(f'{key} = "{value}"')

    # tool.setuptools — full projection with only paths adapted.
    # Root:  package-dir = {"" = "skills/3d-modeling/scripts"}
    #        packages.find.where = ["skills/3d-modeling/scripts"]
    #        packages.find.include = ["pipeline*"]
    # Bundle: package-dir = {"" = "scripts"}
    #         packages.find.where = ["scripts"]
    #         packages.find.include unchanged.
    lines.append("\n[tool.setuptools]")
    lines.append('package-dir = { "" = "scripts" }')
    find = st.get("packages", {}).get("find", {})
    include = find.get("include")
    lines.append("\n[tool.setuptools.packages.find]")
    lines.append('where = ["scripts"]')
    if include:
        inc_fmt = ", ".join(f'"{s}"' for s in include)
        lines.append(f"include = [{inc_fmt}]")

    # tool.ruff (preserved from root, with lint handled as a sub-table)
    ruff_config = root.get("tool", {}).get("ruff", {})
    ruff_scalars = {k: v for k, v in ruff_config.items() if k != "lint"}
    if ruff_scalars:
        lines.append("\n[tool.ruff]")
        for key, value in ruff_scalars.items():
            if isinstance(value, str):
                lines.append(f'{key} = "{value}"')
            elif isinstance(value, (int, float)):
                lines.append(f"{key} = {value}")
            elif isinstance(value, bool):
                lines.append(f"{key} = {'true' if value else 'false'}")
            elif isinstance(value, list):
                items = ", ".join(repr(v) for v in value)
                lines.append(f"{key} = [{items}]")
            else:
                lines.append(f"{key} = {_toml_value(value)}")

    # tool.ruff.lint (preserved as a sub-table)
    ruff_lint = ruff_config.get("lint", {})
    if ruff_lint:
        lines.append("\n[tool.ruff.lint]")
        for key, value in ruff_lint.items():
            if isinstance(value, list):
                items = ", ".join(f'"{s}"' for s in value)
                lines.append(f"{key} = [{items}]")
            elif isinstance(value, str):
                lines.append(f'{key} = "{value}"')
            else:
                lines.append(f"{key} = {_toml_value(value)}")

    # tool.pytest (preserved from root)
    pytest_config = root.get("tool", {}).get("pytest", {}).get("ini_options", {})
    if pytest_config:
        lines.append("\n[tool.pytest.ini_options]")
        for key, value in pytest_config.items():
            if isinstance(value, list):
                items = ", ".join(f'"{s}"' for s in value)
                lines.append(f"{key} = [{items}]")
            elif isinstance(value, str):
                lines.append(f'{key} = "{value}"')
            else:
                lines.append(f"{key} = {_toml_value(value)}")

    # uv config if present
    uv_config = root.get("tool", {}).get("uv", {})
    if uv_config:
        lines.append("\n[tool.uv]")
        for key, value in uv_config.items():
            if isinstance(value, str):
                lines.append(f'{key} = "{value}"')
            elif isinstance(value, bool):
                lines.append(f"{key} = {'true' if value else 'false'}")
            elif isinstance(value, (int, float)):
                lines.append(f"{key} = {value}")
            else:
                lines.append(f"{key} = {_toml_value(value)}")

    # build-system (pass through from root)
    build_sys = root.get("build-system", {})
    if build_sys:
        lines.append("\n[build-system]")
        for key, value in build_sys.items():
            if isinstance(value, str):
                lines.append(f'{key} = "{value}"')
            elif isinstance(value, list):
                items_fmt = ", ".join(f'"{v}"' for v in value)
                lines.append(f"{key} = [{items_fmt}]")
            else:
                lines.append(f"{key} = {_toml_value(value)}")

    return "\n".join(lines) + "\n"


def _bundle_readme() -> str:
    """Minimal README for the installed skill bundle.

    The repo README is not packed because its relative links resolve against
    the repo tree, not the archive layout.  The skill's primary documentation
    is SKILL.md; this file exists so pyproject.toml's `readme` field resolves.
    """
    return (
        "# 3d-modeling-skill-bundle\n\n"
        "See SKILL.md for the router entry point and role documentation.\n"
        "See scripts/, roles/, references/ for the deterministic tooling, "
        "role charters, and design references.\n"
    )


def _toml_escape(raw: str) -> str:
    """Escape a string for a TOML basic string value."""
    return raw.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _toml_value(value):
    """Render a Python value as a TOML literal (non-string values only)."""
    import json as _json
    return _json.dumps(value)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build .skill zip artifacts")
    parser.add_argument(
        "--out",
        default="dist/skills",
        help="Output directory (default: dist/skills)",
    )
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    built = _build_skill(out_dir)
    print(f"  built {built}")
    print(f"Done: 1 artifact in {out_dir}")


if __name__ == "__main__":
    main()
