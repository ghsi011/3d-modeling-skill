"""Tests for tools/build_skill.py — the deterministic .skill artifact.

The load-bearing one is `test_every_internal_link_resolves_inside_the_archive`.
Its absence shipped an archive in which every required-reading link pointed one
directory above the installed skill: the files were all present, the build was
green, and an agent following its own charter found nothing.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import tomllib
import subprocess
import tempfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = ROOT / "tools" / "build_skill.py"

ARTIFACT = "3d-modeling.skill"
REPO_ROOT = Path(__file__).resolve().parents[1]
ROLE_FILES = ["roles/designer.md", "roles/metrologist.md",
              "roles/print-engineer.md", "roles/verifier.md"]

LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")

_UV = shutil.which("uv")


def _run_build(out_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_UV or "uv", "run", "python", str(BUILD_SCRIPT), "--out", str(out_dir)],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        check=True,
    )


@pytest.fixture(scope="module")
def wheel_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the production wheel once for the install/entrypoint checks."""
    _requires_uv()
    out = tmp_path_factory.mktemp("wheel")
    built = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out)],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        check=False,
    )
    assert built.returncode == 0, (
        f"`uv build --wheel` failed:\nstdout={built.stdout}\nstderr={built.stderr}")
    wheels = sorted(out.glob("*.whl"))
    assert len(wheels) == 1, f"expected one wheel, found {wheels}"
    return wheels[0]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _requires_uv() -> bool:
    """Skip helper for tests that need uv on PATH."""
    if _UV is None:
        pytest.skip("uv not on PATH")
    return True


@pytest.fixture(scope="module")
def build_dir():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "skills"
        _run_build(out)
        yield out


class TestBuildSkill:
    def test_one_artifact_is_built(self, build_dir: Path):
        emitted = {p.name for p in build_dir.glob("*.skill")}
        assert emitted == {ARTIFACT}

    def test_reproducible_builds(self):
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            out1, out2 = Path(tmp1) / "skills", Path(tmp2) / "skills"
            _run_build(out1)
            _run_build(out2)
            assert _sha256(out1 / ARTIFACT) == _sha256(out2 / ARTIFACT)

    def test_archive_shape(self, build_dir: Path):
        with zipfile.ZipFile(build_dir / ARTIFACT) as zf:
            names = zf.namelist()
        assert "SKILL.md" in names, "the orchestrator must be the skill entry point"
        for role in ROLE_FILES:
            assert role in names, f"missing {role}"
        assert any(n.startswith("references/") for n in names)
        assert any(n.startswith("scripts/") for n in names)

    def test_the_extracted_bundle_runs_the_whole_route_on_its_own(self, build_dir: Path):
        """What ships must work standing alone, not just in the repo.

        Everything is measured from the working tree; the archive is what a host
        installs, so it has to carry a whole working toolchain -- launcher,
        templates, contract scaffolding, plan generator and gate -- with nothing
        importing back into the repo it was built from. Driven through
        `uv run --project <extracted-bundle> --frozen python <skill>/scripts/dt.py ...`
        from an external job CWD, which is the documented invocation form for a
        host that has installed the skill outside the job directory.
        """
        pytest.importorskip("trimesh")
        pytest.importorskip("manifold3d")
        _requires_uv()

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with zipfile.ZipFile(build_dir / ARTIFACT) as zf:
                zf.extractall(root)

            # Sync the extracted bundle so `uv run --frozen` has a venv.
            sync = subprocess.run(
                ["uv", "sync", "--frozen"],
                capture_output=True, text=True, cwd=str(root), check=False)
            assert sync.returncode == 0, (
                f"extracted bundle `uv sync --frozen` failed:\n{sync.stderr}")

            # Create an external job directory (no pyproject.toml).
            job_dir = Path(raw) / "external-job"
            job_dir.mkdir()
            (job_dir / "brief.md").write_text("test clip job", encoding="utf-8")

            launcher = root / "scripts" / "dt.py"
            assert launcher.is_file(), "the bundle must carry its own launcher"

            job = job_dir / "output"
            base = ["uv", "run", "--project", str(root), "--frozen",
                    "python", str(launcher)]

            def invoke(*args: str, cwd: Path = job_dir) -> subprocess.CompletedProcess:
                return subprocess.run(base + list(args), capture_output=True, text=True,
                                      cwd=str(cwd), check=False)

            timestamp = "1970-01-01T00:00:00Z"
            intake = invoke(
                "intake", "--job-id", "ship", "--template", "c_clip",
                "--param", "bore_d=12.0", "--param", "wall=3.0", "--param", "height=9.0",
                "--param", "mouth_gap=9.0", "--param", "flange=(40.0, 22.0, 5.0)",
                "--param", "screw_d=4.5", "--param", "screw_at=(8.0, 11.0)",
                "--param", "countersink_d=9.0", "--consequence", "INCONSEQUENTIAL",
                "--updated-utc", timestamp, "--out", str(job))
            assert intake.returncode == 0, intake.stderr[-2000:]

            plan = invoke("plan", "template", "--bbox", "40", "22", "14",
                          "--job-id", "ship", "--updated-utc", timestamp,
                          "--out", str(job / "print_plan_checks.json"))
            assert plan.returncode == 0, plan.stderr[-2000:]

            build = invoke("build", "--template", "c_clip",
                           "--param", "bore_d=12.0", "--param", "wall=3.0", "--param", "height=9.0",
                           "--param", "mouth_gap=9.0", "--param", "flange=(40.0, 22.0, 5.0)",
                           "--param", "screw_d=4.5", "--param", "screw_at=(8.0, 11.0)",
                           "--param", "countersink_d=9.0", "--out", str(job / "model.py"))
            assert build.returncode == 0, build.stderr[-2000:]

            done = invoke("commission", "--model", "model.py", "--plan", "print_plan_checks.json",
                          "--out", ".", "--job-id", "ship", "--updated-utc", timestamp,
                          "--no-render", cwd=job)

            assert done.returncode == 0, done.stderr[-2000:]
            for name in ("job_state.md", "dimensions.md", "print_plan_checks.json",
                         "model.py", "candidate-01.stl", "commission.json",
                         "artifact_manifest.json", "candidate_readiness.md"):
                assert (job / name).is_file(), f"the bundle did not produce {name}"

    def test_every_internal_link_resolves_inside_the_archive(self, build_dir: Path):
        """No link may escape the archive or point at a missing member.

        This is what the five-bundle layout got wrong: SKILL.md kept the repo's
        `../3d-modeling/references/...` paths while the bundle carried those
        assets at its own root, so all 36 links resolved above the install root.
        """
        with zipfile.ZipFile(build_dir / ARTIFACT) as zf:
            members = set(zf.namelist())
            broken: list[str] = []
            for name in (n for n in members if n.endswith(".md")):
                text = zf.read(name).decode("utf-8", errors="replace")
                for _label, target in LINK_RE.findall(text):
                    if target.startswith(("http://", "https://", "mailto:", "#")):
                        continue
                    path_part = target.split("#", 1)[0]
                    if not path_part:
                        continue
                    resolved = (Path(name).parent / path_part).as_posix()
                    resolved = str(Path(resolved).as_posix()).replace("\\", "/")
                    normalized = Path(resolved)
                    parts: list[str] = []
                    for part in normalized.parts:
                        if part == "..":
                            if not parts:
                                broken.append(f"{name} -> {target} (escapes the archive)")
                                break
                            parts.pop()
                        elif part != ".":
                            parts.append(part)
                    else:
                        candidate = "/".join(parts)
                        if candidate not in members and f"{candidate}/" not in members:
                            if not any(m.startswith(f"{candidate}/") for m in members):
                                broken.append(f"{name} -> {target} (no member {candidate})")
        assert not broken, "links break inside the shipped skill:\n  " + "\n  ".join(broken)

    def test_no_pycache_in_zip(self, build_dir: Path):
        with zipfile.ZipFile(build_dir / ARTIFACT) as zf:
            assert not [e for e in zf.namelist() if "__pycache__" in e]

    def test_fixed_timestamps_and_permissions(self, build_dir: Path):
        with zipfile.ZipFile(build_dir / ARTIFACT) as zf:
            for info in zf.infolist():
                assert info.date_time == (1980, 1, 1, 0, 0, 0), info.filename
                assert info.external_attr >> 16 == 0o644, info.filename

    def test_entries_are_sorted(self, build_dir: Path):
        with zipfile.ZipFile(build_dir / ARTIFACT) as zf:
            names = zf.namelist()
        assert names == sorted(names)

    def test_the_bundle_can_run_the_command_skill_md_opens_with(self, build_dir: Path):
        """SKILL.md's first line is `uv run design-tool run-job`. `design-tool` is
        a console script, so without a project file beside it the installed
        bundle answers that command with `program not found` -- the shipped
        artifact could not run the one command it leads with.
        """
        with zipfile.ZipFile(build_dir / ARTIFACT) as zf:
            names = zf.namelist()
            assert "pyproject.toml" in names, (
                "the bundle ships no project file, so its own headline command "
                "does not resolve once installed")
            bundled = tomllib.loads(zf.read("pyproject.toml").decode("utf-8"))
            skill_md = zf.read("SKILL.md").decode("utf-8")

        entry = bundled["project"]["scripts"]
        assert entry.get("design-tool") == "pipeline.cli:main", entry
        assert "scripts/pipeline/cli.py" in names, "the entry point must be packed too"

        # Anywhere in the file, fenced or inline. The first version of this
        # required backticks and SKILL.md puts the command in a code block, so it
        # iterated an empty list and could not fail -- which is the same shape of
        # defect as the packaging bug it was written to catch.
        commands = set(re.findall(r"uv run ([a-z][a-z0-9-]*)", skill_md))
        assert commands, "SKILL.md names no `uv run` command; this test would prove nothing"
        for command in sorted(commands - {"python"}):
            assert command in entry, (
                f"SKILL.md tells the reader to run `{command}`, which the bundle "
                f"does not define. It defines {sorted(entry)}.")

    def test_the_bundle_pins_the_same_toolchain_the_tests_ran_against(self, build_dir: Path):
        """A second copy of a version floor drifts from the first, and the bundle
        would then resolve a different toolchain than anything was tested on."""
        with zipfile.ZipFile(build_dir / ARTIFACT) as zf:
            bundled = tomllib.loads(zf.read("pyproject.toml").decode("utf-8"))
        repo = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        assert bundled["project"]["dependencies"] == repo["project"]["dependencies"]
        assert bundled["project"]["requires-python"] == repo["project"]["requires-python"]
        assert bundled["project"]["version"] == repo["project"]["version"]
        # The bundle keeps the same name as root so the lockfile matches.
        assert bundled["project"]["name"] == repo["project"]["name"]

        # optional-dependencies must be preserved (these live under [project] in TOML).
        bundled_optional = bundled.get("project", {}).get("optional-dependencies", {})
        repo_optional = repo.get("project", {}).get("optional-dependencies", {})
        assert bundled_optional == repo_optional, (
            f"bundle optional-deps {bundled_optional} != repo {repo_optional}")

        # dependency-groups must be preserved.
        bundled_groups = bundled.get("dependency-groups", {})
        repo_groups = repo.get("dependency-groups", {})
        assert bundled_groups == repo_groups, (
            f"bundle dependency-groups {bundled_groups} != repo {repo_groups}")

    def test_the_lockfile_travels_with_the_project_file(self, build_dir: Path):
        """`cache.find_lock` only accepts a lockfile with a `pyproject.toml`
        beside it, so shipping one without the other identifies nothing. Without
        both, an installed bundle falls back to installed versions -- correct,
        but weaker than the lock it was tested against."""
        with zipfile.ZipFile(build_dir / ARTIFACT) as zf:
            names = zf.namelist()
            assert "uv.lock" in names and "pyproject.toml" in names, names[:5]
            assert zf.read("uv.lock") == (REPO_ROOT / "uv.lock").read_bytes(), (
                "the bundle must pin the toolchain the repository tested against")

    def test_bundle_readme_and_license_are_packed(self, build_dir: Path):
        """pyproject.toml's readme/license fields must resolve in the bundle."""
        with zipfile.ZipFile(build_dir / ARTIFACT) as zf:
            names = zf.namelist()
            assert "README.md" in names, "bundle must carry README.md"
            assert "LICENSE" in names, "bundle must carry LICENSE"
            bundled = tomllib.loads(zf.read("pyproject.toml").decode("utf-8"))
            assert "readme" in bundled.get("project", {}), "project.readme must be set"
            assert "license" in bundled.get("project", {}), "project.license must be set"

    def test_bundle_project_is_path_adjusted_projection(self, build_dir: Path):
        """The bundled pyproject.toml adjusts only package-discovery paths;
        all other root metadata is preserved verbatim after normalising the
        two path changes."""
        with zipfile.ZipFile(build_dir / ARTIFACT) as zf:
            bundled = tomllib.loads(zf.read("pyproject.toml").decode("utf-8"))
        repo = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        # The bundle adjusts exactly two paths from the root:
        #   - tool.setuptools.package-dir  ("" -> "scripts")
        #   - tool.setuptools.packages.find.where (["skills/.../scripts"] -> ["scripts"])
        # Compare the full parsed documents after normalising those two fields.

        repo_pkg_dir = repo.get("tool", {}).get("setuptools", {}).get("package-dir", {})
        bundled_pkg_dir = bundled.get("tool", {}).get("setuptools", {}).get("package-dir", {})
        if repo_pkg_dir:
            assert bundled_pkg_dir == {"": "scripts"}, (
                f"expected bundle package-dir={{'': 'scripts'}}, got {bundled_pkg_dir}")
        expected_where = ["scripts"]
        bundled_where = bundled.get("tool", {}).get("setuptools", {}).get("packages", {}).get("find", {}).get("where")
        assert bundled_where == expected_where, (
            f"expected find.where={expected_where}, got {bundled_where}")

        # Deep-copy repo TOML, normalise the two bundle-only path changes, then
        # compare the entire document — no broader table may be removed or altered.
        import copy
        normalized = copy.deepcopy(repo)
        if repo_pkg_dir:
            # Replace the root path with the bundle path so comparison works.
            # In the root the value is {"": "skills/3d-modeling/scripts"}.
            # In the bundle it's {"": "scripts"} — we normalise repo to match.
            normalized["tool"]["setuptools"]["package-dir"] = {"": "scripts"}
        repo_find = normalized.get("tool", {}).get("setuptools", {}).get("packages", {}).get("find", {})
        if repo_find and "where" in repo_find:
            repo_find["where"] = ["scripts"]
        assert bundled == normalized, (
            f"bundle TOML differs from root after normalising only the two "
            f"setuptools path fields.\n"
            f"Keys only in bundled: {set(bundled) - set(normalized)}\n"
            f"Keys only in normalized: {set(normalized) - set(bundled)}\n"
            f"Diff tool keys:\n  repo: {normalized.get('tool', {})}\n  bundle: {bundled.get('tool', {})}")

    def test_bundled_booleans_are_toml_and_not_python(self, build_dir: Path):
        """The projection writes TOML, and `bool` is a subclass of `int`.

        `[tool.ruff]` tested `(int, float)` before `bool`, so its `bool` arm was
        unreachable and every boolean rendered through the f-string as Python's
        `True`. Nothing noticed while the table held no booleans; the first one
        added broke `uv lock --check` and every test that syncs the bundle, with
        a TOML parse error pointing at a line the author never wrote.

        Checked as text as well as by parse: a parse alone cannot distinguish
        "rendered correctly" from "rendered `True` and tomllib was lenient",
        and tomllib is not lenient, which is exactly why this was a hard failure
        rather than a silently wrong bundle.
        """
        with zipfile.ZipFile(build_dir / ARTIFACT) as zf:
            raw = zf.read("pyproject.toml").decode("utf-8")
        bundled = tomllib.loads(raw)
        booleans = {k: v for k, v in bundled.get("tool", {}).get("ruff", {}).items()
                    if isinstance(v, bool)}
        assert booleans, (
            "this test is only meaningful while [tool.ruff] carries a boolean; "
            "force-exclude was the first and pins the immutable design source")
        for key, value in booleans.items():
            assert f"{key} = {'true' if value else 'false'}" in raw, (
                f"{key} was not rendered as a TOML boolean")
        assert not re.search(r"=\s*(True|False)\b", raw), (
            "a Python boolean literal reached the bundled pyproject.toml")

    def test_extracted_lock_passes_uv_lock_check(self, build_dir: Path):
        """`uv lock --check` on the extracted bundle must pass, proving the
        bundled pyproject.toml is satisfiable by the bundled lockfile."""
        _requires_uv()

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with zipfile.ZipFile(build_dir / ARTIFACT) as zf:
                zf.extractall(root)

            done = subprocess.run(
                ["uv", "lock", "--check"],
                capture_output=True, text=True, cwd=str(root), check=False)
            assert done.returncode == 0, (
                f"bundled lock is inconsistent with bundled pyproject.toml:\n"
                f"{done.stderr}")

    def test_extracted_bundle_syncs_frozen(self, build_dir: Path):
        """The extracted bundle can `uv sync --frozen`, proving the lockfile
        resolves all dependencies including optional-deps and dev groups."""
        _requires_uv()

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with zipfile.ZipFile(build_dir / ARTIFACT) as zf:
                zf.extractall(root)

            sync = subprocess.run(
                ["uv", "sync", "--frozen"],
                capture_output=True, text=True, cwd=str(root), check=False)
            assert sync.returncode == 0, (
                f"extracted bundle `uv sync --frozen` failed:\n{sync.stderr}")

    def test_extracted_bundle_preserves_lock_bytes(self, build_dir: Path):
        """After extracting, the lockfile on disk matches the one in the archive
        byte-for-byte — no transformation happened during extraction."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with zipfile.ZipFile(build_dir / ARTIFACT) as zf:
                zipped = zf.read("uv.lock")
                zf.extractall(root)
            on_disk = (root / "uv.lock").read_bytes()
            assert on_disk == zipped, "lockfile bytes changed during extraction"

    def test_extracted_bundle_runs_design_tool_doctor(self, build_dir: Path):
        """After `uv sync --frozen`, `uv run --frozen design-tool doctor`
        executes and exits zero."""
        _requires_uv()

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with zipfile.ZipFile(build_dir / ARTIFACT) as zf:
                zf.extractall(root)

            sync = subprocess.run(
                ["uv", "sync", "--frozen"],
                capture_output=True, text=True, cwd=str(root), check=False)
            assert sync.returncode == 0, sync.stderr

            doctor = subprocess.run(
                ["uv", "run", "--frozen", "design-tool", "doctor"],
                capture_output=True, text=True, cwd=str(root), check=False)
            assert doctor.returncode == 0, (
                f"`uv run --frozen design-tool doctor` failed:\n{doctor.stderr}")
            assert "python" in doctor.stdout.lower(), (
                f"doctor output missing python info:\n{doctor.stdout}")

    def test_bundle_doctor_with_external_cwd(self, build_dir: Path):
        """`uv run --project <extracted bundle> --frozen design-tool doctor`
        executes and exits zero even when CWD is an arbitrary job directory,
        proving source-checkout discovery cannot mask failures."""
        _requires_uv()
        pytest.importorskip("trimesh")

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with zipfile.ZipFile(build_dir / ARTIFACT) as zf:
                zf.extractall(root)

            # Sync so the venv exists.
            subprocess.run(
                ["uv", "sync", "--frozen"],
                capture_output=True, text=True, cwd=str(root), check=True)

            # Create an external job directory with no pyproject.toml.
            job_dir = Path(raw) / "external-job"
            job_dir.mkdir()
            (job_dir / "brief.md").write_text("test", encoding="utf-8")

            # Run from the external CWD using --project to select the bundle.
            doctor = subprocess.run(
                ["uv", "run", "--project", str(root), "--frozen",
                 "design-tool", "doctor"],
                capture_output=True, text=True, cwd=str(job_dir), check=False)
            assert doctor.returncode == 0, (
                f"`uv run --project <skill> --frozen design-tool doctor` from "
                f"external CWD failed:\n{doctor.stderr}")
            assert "python" in doctor.stdout.lower()

    def test_bundle_doctor_with_external_cwd_and_short_flag(self, build_dir: Path):
        """`uv run --project <extracted bundle>/pyproject.toml --frozen` works
        when pointing at the toml file rather than the directory, confirming
        the flag form documented in role instructions."""
        _requires_uv()

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with zipfile.ZipFile(build_dir / ARTIFACT) as zf:
                zf.extractall(root)

            subprocess.run(
                ["uv", "sync", "--frozen"],
                capture_output=True, text=True, cwd=str(root), check=True)

            job_dir = Path(raw) / "another-job"
            job_dir.mkdir()

            pyproject_toml = root / "pyproject.toml"
            assert pyproject_toml.is_file()
            doctor = subprocess.run(
                ["uv", "run", "--project", str(pyproject_toml), "--frozen",
                 "design-tool", "doctor"],
                capture_output=True, text=True, cwd=str(job_dir), check=False)
            assert doctor.returncode == 0, (
                f"`uv run --project <skill>/pyproject.toml --frozen design-tool doctor` "
                f"from external CWD failed:\n{doctor.stderr}")

    def test_shipped_docs_use_absolute_script_paths(self, build_dir: Path):
        """Every `uv run --project <skill> --frozen python scripts/...` command
        in shipped markdown AND bundled `.py` sources must use
        `<skill>/scripts/...` (absolute form), not bare `scripts/...` (which
        would fail from an external CWD).  Module calls (`python -m ...`) and
        console-script commands (`design-tool`) are exempt."""
        with zipfile.ZipFile(build_dir / ARTIFACT) as zf:
            members = zf.namelist()
            bad: list[str] = []
            for name in (n for n in members if n.endswith((".md", ".py"))):
                text = zf.read(name).decode("utf-8", errors="replace")
                if "uv run --project <skill> --frozen" not in text:
                    continue
                for lineno, line in enumerate(text.splitlines(), 1):
                    if "--project <skill> --frozen" not in line:
                        continue
                    if "python -m " in line:
                        continue
                    if "design-tool " in line:
                        continue
                    # Comment-only lines about module layout are exempt.
                    stripped = line.strip()
                    if stripped.startswith("#"):
                        continue
                    if " scripts/" in line and "<skill>/scripts/" not in line:
                        bad.append(f"{name}:{lineno}: {line.strip()}")
            assert not bad, (
                "these shipped lines use the bare `scripts/` form "
                "that fails from external CWD; they must use `<skill>/scripts/`:\n"
                + "\n".join(bad))

    def test_bundle_ships_no_test_source(self, build_dir: Path):
        """No file whose name starts with test_ is shipped inside the archive,
        and no script inside scripts/ is a test file."""
        with zipfile.ZipFile(build_dir / ARTIFACT) as zf:
            offenders = [
                e for e in zf.namelist()
                if Path(e).name.startswith("test_") or "_test." in Path(e).name
                or "/tests/" in e or "/test_" in e
            ]
        assert not offenders, f"bundle ships test source: {offenders}"

    def test_production_wheel_excludes_test_modules(self, wheel_path: Path):
        """The wheel is the Python runtime surface, not a source checkout."""
        with zipfile.ZipFile(wheel_path) as zf:
            names = zf.namelist()

        offenders = [
            name for name in names
            if name.endswith(".py") and (
                Path(name).name.startswith("test_")
                or Path(name).stem.endswith("_test")
            )
        ]
        assert not offenders, f"production wheel ships test modules: {offenders}"
        assert "pipeline/cli.py" in names
        assert "mesh_io.py" in names
        assert "preview.py" in names
        assert "designer_toolkit/__init__.py" in names
        assert not any(name == "SKILL.md" or name.startswith("roles/") for name in names)

    def test_production_wheel_entrypoint_smoke_from_external_cwd(self, wheel_path: Path):
        """The installed wheel must expose its entry point outside the checkout."""
        _requires_uv()
        with tempfile.TemporaryDirectory() as raw:
            external = Path(raw) / "external-job"
            external.mkdir()
            smoke = subprocess.run(
                ["uv", "run", "--isolated", "--no-project", "--with", str(wheel_path),
                 "design-tool", "doctor"],
                capture_output=True,
                text=True,
                cwd=str(external),
                check=False,
            )
        assert smoke.returncode == 0, (
            f"wheel entrypoint failed from an external CWD:\n{smoke.stderr}")
        assert "python" in smoke.stdout.lower()

    def test_production_wheel_team_tools_import_from_external_interpreter(self, wheel_path: Path):
        """The advertised team_tools package must not depend on checkout sys.path."""
        _requires_uv()
        with tempfile.TemporaryDirectory() as raw:
            external = Path(raw) / "external-job"
            external.mkdir()
            smoke = subprocess.run(
                ["uv", "run", "--isolated", "--no-project", "--with", str(wheel_path),
                 "python", "-c",
                 "from team_tools import contracts, project, receipts, status, validators; "
                 "print(contracts.build_parser().prog)"],
                capture_output=True,
                text=True,
                cwd=str(external),
                check=False,
            )
        assert smoke.returncode == 0, (
            f"team_tools failed from an external interpreter:\n{smoke.stderr}")
        assert "team_tools.contracts" in smoke.stdout

    def test_production_wheel_runs_job_from_external_cwd(self, wheel_path: Path):
        """`doctor` is not enough: the installed wheel must commission a job."""
        _requires_uv()
        with tempfile.TemporaryDirectory() as raw:
            external = Path(raw) / "external-job"
            external.mkdir()
            job = external / "clip"
            job.mkdir()
            (job / "brief.md").write_text("a clip", encoding="utf-8")
            (job / "job.json").write_text(json.dumps({
                "job_id": "wheel-clip",
                "template": "c_clip",
                "consequence": "INCONSEQUENTIAL",
                "printer": "Test Printer",
                "material": {"process": "FDM", "material": "PLA"},
                "nozzle": {"diameter_mm": 0.4},
                "orientation": {
                    "model_to_printer_matrix": "identity", "bed_z_mm": 0.0,
                },
                "parameters": {
                    "bore_d": 12.0, "wall": 3.0, "height": 9.0,
                    "mouth_gap": 9.0, "flange_w": 40.0, "flange_d": 22.0,
                    "flange_t": 5.0, "screw_d": 4.8,
                },
                "stated": [],
                "updated_utc": "1970-01-01T00:00:00Z",
            }), encoding="utf-8")
            smoke = subprocess.run(
                ["uv", "run", "--isolated", "--no-project", "--with", str(wheel_path),
                 "design-tool", "run-job", str(job), "--no-render"],
                capture_output=True,
                text=True,
                cwd=str(external),
                check=False,
            )
            assert smoke.returncode in (0, 1), smoke.stderr
            assert "Traceback" not in smoke.stderr
            assert "ModuleNotFoundError" not in smoke.stderr
            assert (job / "commission_report.json").is_file(), smoke.stderr
            assert (job / "final_status.json").is_file(), smoke.stderr
