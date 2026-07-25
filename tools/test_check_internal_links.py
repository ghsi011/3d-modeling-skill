"""Tests for the internal-link CI gate.

This gate had no test, which is the same shape as the generated-harness drift
gate that turned out to pass unconditionally: a check nobody checks reports
"all clear" just as convincingly when it is broken. Each case below builds a
tiny markdown tree and asserts the gate's verdict on it.
"""

from __future__ import annotations

from pathlib import Path

from tools import check_internal_links as links


def _write(root: Path, name: str, body: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_resolving_link_is_clean(tmp_path: Path) -> None:
    _write(tmp_path, "target.md", "# target\n")
    _write(tmp_path, "doc.md", "see [target](target.md)\n")

    assert links.find_broken(tmp_path) == []
    assert links.main(tmp_path) == 0


def test_broken_link_is_reported_with_source_and_target(tmp_path: Path) -> None:
    _write(tmp_path, "doc.md", "see [gone](no_such_file.md)\n")

    broken = links.find_broken(tmp_path)

    assert len(broken) == 1
    source, target, _resolved = broken[0]
    assert source.name == "doc.md"
    assert target == "no_such_file.md"
    assert links.main(tmp_path) == 1


def test_relative_link_resolves_from_the_linking_file_not_the_root(tmp_path: Path) -> None:
    """The bug this guards: resolving against the repo root instead of the
    file's own directory silently passes wrong links and fails right ones.
    """
    _write(tmp_path, "shared/ref.md", "# ref\n")
    _write(tmp_path, "roles/role.md", "see [ref](../shared/ref.md)\n")

    assert links.find_broken(tmp_path) == []

    _write(tmp_path, "roles/bad.md", "see [ref](shared/ref.md)\n")  # missing the ../
    assert [t for _s, t, _r in links.find_broken(tmp_path)] == ["shared/ref.md"]


def test_external_and_anchor_targets_are_skipped(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "doc.md",
        "[web](https://example.com/x.md) [insecure](http://example.com)"
        " [mail](mailto:a@b.c) [self](#section)\n",
    )

    assert links.find_broken(tmp_path) == []


def test_anchor_is_stripped_before_resolving(tmp_path: Path) -> None:
    _write(tmp_path, "target.md", "# target\n")
    _write(tmp_path, "doc.md", "see [target](target.md#a-heading)\n")

    assert links.find_broken(tmp_path) == []


def test_excluded_directories_are_not_scanned(tmp_path: Path) -> None:
    """A local virtualenv or build output carries markdown that is not ours;
    scanning it can fail a run that CI, which has no such directory, passes.
    """
    for excluded in (".venv", "node_modules", "dist", "temp", "__pycache__"):
        _write(tmp_path, f"{excluded}/pkg.md", "see [nope](totally_missing.md)\n")

    assert links.find_broken(tmp_path) == []
    assert links.iter_markdown(tmp_path) == []


def test_scans_nested_authored_files(tmp_path: Path) -> None:
    _write(tmp_path, "a.md", "# a\n")
    _write(tmp_path, "deep/nested/b.md", "# b\n")

    assert [p.name for p in links.iter_markdown(tmp_path)] == ["a.md", "b.md"]
