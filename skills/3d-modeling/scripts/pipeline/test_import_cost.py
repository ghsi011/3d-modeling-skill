#!/usr/bin/env python3
"""A command that never touches a mesh must not pay for the mesh library.

Measured on `22c3b29`, warm, three readings: importing `pipeline.cli` costs
1546-1569 ms, of which `trimesh` is 1320-1336 ms -- **85%**, every time. The edge
that buys it is `analysis.py`'s module-level `import trimesh`, reached from `cli`
through `compare` and `screening`. So `doctor`, `status`, `init` and `route` --
none of which load geometry -- each wait about 1.3 s for a library they never call.

`diagnose.py` already states the rule this file enforces: *"Function-local, as
everywhere else in this module: a job that never touches a mesh must not pay the
import."* Every `build123d` import in the backends is function-local for the same
measured reason. `analysis.py` was the exception, and nothing was checking.

**Why this test is structural rather than timed.** The honest instrument for "did
the import happen" is a fresh interpreter, and L0 may not start one -- `conftest.py`
permits `git` and nothing else, because a child interpreter is the ~1.6 s mechanism
that tiering exists to keep out of the commit gate. A wall-clock assertion is worse
than unavailable: it is the unstable measurement `conftest.py` already refuses for
`L0_TEST_CEILING_S`, and it would fail on a loaded runner while passing on a fast
one. So the gate asserts the *causal property* -- no module-level mesh import
anywhere on the graph `cli` pulls in -- and `benchmarks/heavy/test_import_graph.py`
asserts the consequence in a real interpreter, where a spawn is allowed.

The graph walk matters more than checking `analysis.py` by name. The cost came back
once already through a module nobody was watching; a test naming one file would
have watched that file.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent

# The stack a non-geometry command must not drag in. `trimesh` is the measured
# 85%; `build123d` is the ~10.7 s one the backends already keep function-local and
# is here so this test fails if that discipline ever moves into a module body.
# `numpy` is here for the same reason and by the same measurement, not because it is a
# mesh library: it cost 123-129 ms of a 308-337 ms CLI import through `contract` and
# `screening`, which every command reaches and only four functions in either one use.
# The set is "what a command that does no geometry must not pay for", which is why the
# name is about the cost rather than about meshes.
DEFERRED_IMPORTS = frozenset({"trimesh", "build123d", "manifold3d", "cascadio", "numpy"})

# Where a command actually enters the package.
ENTRY = "cli"


def _module_level_imports(path: Path) -> set[str]:
    """Top-level import names only -- an import inside a function is the fix, not the bug.

    `if TYPE_CHECKING:` blocks are excluded deliberately: they are annotations, never
    evaluated at runtime, and `analysis.py` needs one to keep its dataclass readable.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()

    def walk(body: list[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, ast.Import):
                found.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    found.add(node.module.split(".")[0])
                elif node.level and node.module:
                    found.add("." + node.module.split(".")[0])
                elif node.level:
                    # `from . import compare` -- the module is None and the siblings
                    # are the *names*. Missing this shape is not hypothetical: it is
                    # how `cli.py` reaches `compare` and `screening`, so the first
                    # draft of this walk stopped at `cli` and asserted nothing.
                    found.update("." + alias.name for alias in node.names)
            elif isinstance(node, ast.If):
                # A guarded import still executes unless the guard is TYPE_CHECKING.
                test = node.test
                is_type_checking = (
                    (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING")
                    or (isinstance(test, ast.Attribute)
                        and test.attr == "TYPE_CHECKING"))
                if not is_type_checking:
                    walk(node.body)
                walk(node.orelse)
            elif isinstance(node, ast.Try):
                walk(node.body)
                for handler in node.handlers:
                    walk(handler.body)
                walk(node.orelse)
                walk(node.finalbody)

    walk(tree.body)
    return found


def _reachable_from(entry: str) -> dict[str, set[str]]:
    """Every package module `entry` pulls in at import time, and what each imports."""
    graph: dict[str, set[str]] = {}
    pending = [entry]
    while pending:
        name = pending.pop()
        if name in graph:
            continue
        path = PACKAGE / f"{name}.py"
        if not path.is_file():
            continue
        imports = _module_level_imports(path)
        graph[name] = imports
        for imported in imports:
            if imported.startswith("."):
                pending.append(imported[1:])
            elif (PACKAGE / f"{imported}.py").is_file():
                pending.append(imported)
    return graph


class ANonGeometryCommandDoesNotPayForTheMeshStackTest(unittest.TestCase):

    def test_nothing_the_cli_imports_loads_a_mesh_library_at_module_level(self) -> None:
        graph = _reachable_from(ENTRY)
        self.assertIn("analysis", graph,
                      "the walk must actually reach the module this slice fixed, or "
                      "it is asserting about a graph that stops short")
        for module, imports in sorted(graph.items()):
            with self.subTest(module=module):
                offenders = sorted(imports & DEFERRED_IMPORTS)
                self.assertEqual(
                    [], offenders,
                    f"pipeline/{module}.py imports {offenders} at module level, so "
                    "every command that reaches it pays for it. Move the "
                    "import into the function that uses it, as diagnose.py does.")

    def test_the_walk_would_notice_an_import_that_came_back(self) -> None:
        """The falsification: a guard that cannot fail reads like one that holds.

        `_module_level_imports` is the whole instrument, so it is exercised against a
        module body that does what the bug did -- including the two shapes that could
        smuggle it past a naive check.
        """
        cases = {
            "import trimesh": True,
            "import trimesh as tm": True,
            "from trimesh import creation": True,
            "if os.name == 'nt':\n    import trimesh": True,
            "try:\n    import trimesh\nexcept ImportError:\n    trimesh = None": True,
            "def f():\n    import trimesh": False,
            "if TYPE_CHECKING:\n    import trimesh": False,
        }
        for source, should_find in cases.items():
            with self.subTest(source=source):
                path = PACKAGE / "__probe__.py"
                try:
                    path.write_text(source + "\n", encoding="utf-8")
                    found = "trimesh" in _module_level_imports(path)
                finally:
                    path.unlink(missing_ok=True)
                self.assertEqual(should_find, found)


if __name__ == "__main__":
    unittest.main()
