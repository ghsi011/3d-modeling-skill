#!/usr/bin/env python3
"""L0 for the lazy `build123d` facade -- the half that answers in this process.

What the facade *does* needs a fresh interpreter, because the honest instrument
for "was this module imported" is `sys.modules` in a process that has just
started, and `conftest.py` permits an L0 test to spawn `git` and nothing else.
That half is `benchmarks/heavy/test_lazy_build123d_heavy.py`, and it is where the
structural regression control lives: a minimal candidate must not load `sklearn`
or `ezdxf`, asserted on `sys.modules` rather than on a clock.

What is left here is not a residue. It is the two claims that no run can make:

* the pinned submodule inventory is the installed package's own. The facade
  answers a name by importing submodules in a fixed order, and that order is a
  fact about one release of somebody else's package. A submodule this list has
  never heard of is a name the facade cannot serve or -- worse, if the release
  ever moved one -- serves from the wrong module. `PROVEN_VERSIONS` is the guard
  and this is the guard's own check, run on every commit against whatever
  `uv.lock` currently resolves;
* the facade is installed at the one point in `build_child.py` where it is safe
  to install it: after the syscall filter, inside the stopwatch, before the first
  candidate byte is imported. That is a call site, and D8's finding is that a
  protection whose weakening is invisible to any assertion about a return value
  needs the call site read as syntax.
"""
from __future__ import annotations

import ast
import importlib.machinery
import importlib.util
import sys
import tempfile
import types
import unittest
from collections.abc import Callable
from pathlib import Path

from . import lazy_build123d as L
from .test_import_cost import _module_level_imports

PACKAGE_ROOT = Path(__file__).resolve().parent


def _installed_init() -> Path | None:
    """The installed `build123d/__init__.py`, found without executing it.

    `find_spec` is ~1.5 ms and imports nothing -- which is the only reason this
    check can live in the commit gate at all.
    """
    spec = importlib.util.find_spec(L.PACKAGE)
    if spec is None or spec.origin is None:
        return None
    return Path(spec.origin)


def _submodules_the_package_imports(init: Path) -> list[str]:
    """`from build123d.X import ...` in the package body, in source order, by AST.

    Order is part of the answer, so this walks `tree.body` rather than
    `ast.walk`, which promises nothing about ordering.

    Absolute imports only. `from .version import version as __version__` is
    relative and is deliberately not in the inventory: the facade never has to
    serve `version` from a search, because `__version__` starts with an
    underscore pair and goes straight to the real `__init__`.
    """
    found: list[str] = []
    for node in ast.parse(init.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.ImportFrom) and not node.level and node.module:
            parts = node.module.split(".")
            if parts[0] == L.PACKAGE and len(parts) == 2 and parts[1] not in found:
                found.append(parts[1])
    return found


class TheOmissionSetIsTheDesignTest(unittest.TestCase):
    """Three names, chosen by subtraction, and the reason written down once."""

    def test_the_pinned_inventory_is_the_installed_packages_own(self) -> None:
        init = _installed_init()
        self.assertIsNotNone(init, "build123d is a core dependency and its "
                                   "__init__.py must be findable")
        if L.installed_version() not in L.PROVEN_VERSIONS:
            self.skipTest(
                f"build123d {L.installed_version()} is not in PROVEN_VERSIONS, so "
                "the facade declines on this install and there is no inventory to "
                "hold to account. Sweeping a new release is what adds it.")
        self.assertEqual(
            list(L.SUBMODULES), _submodules_the_package_imports(init),
            "the facade's submodule inventory and build123d's own __init__.py "
            "disagree in membership or in order. A submodule the inventory has "
            "never heard of is a name the search cannot serve; a name the "
            "release moved into an earlier-searched module is a silent "
            "mis-bind; and a *reordered* inventory is no longer a description "
            "of the package but a claim about which submodules are cheap, which "
            "is the design this slice rejected. Re-run the identity sweep in "
            "benchmarks/heavy/test_lazy_build123d_heavy.py against the new "
            "release before touching either list.")

    def test_the_search_is_the_inventory_minus_exactly_the_three(self) -> None:
        """Stated as a set difference, because that is the whole justification.

        The omission is "the smallest set that keeps the measured win", not "the
        set that happens to serve the candidates in this repository". An authored
        candidate is arbitrary by contract, so what the omission has to buy is a
        property of the mechanism: no name lookup can reach `ezdxf`.

        Two of the three are here for seconds -- about 0.7 s each on the bearing
        candidate, `docs/baseline.md`. `brep_from_stl` measured **+0.011 s**
        against a 0.39 s spread and was removed on that, and the identity sweep
        put it straight back: it binds `copy` to the module where `__init__`
        leaves the function. It is omitted because it cannot be served correctly.
        """
        self.assertEqual(("exporters", "import_dxf", "brep_from_stl"), L.DEFERRED)
        self.assertEqual(set(), set(L.SEARCH) & set(L.DEFERRED))
        self.assertEqual(set(L.SUBMODULES) - set(L.DEFERRED), set(L.SEARCH))
        self.assertEqual(len(L.SUBMODULES) - len(L.DEFERRED), len(L.SEARCH),
                         "a repeated name in the inventory would shrink the "
                         "search without saying so")

    def test_the_rebound_names_are_inventory_names_in_the_packages_order(
            self) -> None:
        """What a syntax tree can say about `REBOUND`, and it is not the whole.

        `REBOUND` is the submodules whose own name `build123d/__init__.py` leaves
        bound to something that is *not* the submodule, and it is what
        `_Facade.__setattr__` declines so the import system's parent binding
        cannot answer `build123d.pack` with a module where the package answers
        with a function.

        Whether a *given* release rebinds exactly these two is asked in
        `benchmarks/heavy/test_lazy_build123d_heavy.py`, against the executed
        package, and deliberately not here. `__init__.py` reaches `pack` through
        `from build123d.pack import *`, so answering it from the syntax tree
        means emulating star-import semantics -- reading a submodule's `__all__`
        when it has one and its top-level names when it does not -- which is a
        guess in the grammar of a check. The executed package answers the same
        question by identity and cannot be wrong about it.

        What is left is exact and cheap: a name outside the inventory is a name
        no import can bind, so declining its write would protect nothing, and the
        order is the package's own for the reason `SUBMODULES` keeps it.
        """
        self.assertEqual((), tuple(set(L.REBOUND) - set(L.SUBMODULES)),
                         "a rebound name that is not in the inventory is a name "
                         "no import binds, so declining its write protects "
                         "nothing")
        self.assertEqual([sub for sub in L.SUBMODULES if sub in set(L.REBOUND)],
                         list(L.REBOUND))
        self.assertNotEqual((), L.REBOUND,
                            "an empty REBOUND declines nothing, and `import "
                            "build123d.pack` then answers with the submodule -- "
                            "which is `TypeError: 'module' object is not "
                            "callable` for a candidate that calls it")

    def test_the_search_keeps_the_packages_order(self) -> None:
        """A subsequence of the inventory, never a re-sort of it.

        Sorting the expensive submodules to the back would buy the same seconds
        on the candidate this was measured on and would make the omission inert
        -- measured, `docs/baseline.md`. It is rejected because the order would
        then be an unchecked claim about relative cost, and the omission is what
        this slice is asking a reviewer to accept.
        """
        kept = [name for name in L.SUBMODULES if name in set(L.SEARCH)]
        self.assertEqual(kept, list(L.SEARCH))


class TheFacadeStepsAsideTest(unittest.TestCase):
    """Every path that must end in ordinary `import build123d`.

    `install()` costs one `find_spec` and one module object and decides nothing
    about which release this is; that decision is armed on first contact, where
    a candidate that never names build123d never pays for it. So what is
    checkable here is the declining, and each of these is a case where the
    boundary must not have an opinion.
    """

    def setUp(self) -> None:
        self._saved = sys.modules.pop(L.PACKAGE, None)
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        sys.modules.pop(L.PACKAGE, None)
        if self._saved is not None:
            sys.modules[L.PACKAGE] = self._saved

    def test_it_declines_when_the_candidate_already_imported_build123d(self) -> None:
        """Whatever is already bound stays bound. Replacing it mid-flight would
        be the boundary rewriting an import the candidate has already made."""
        sentinel = types.ModuleType(L.PACKAGE)
        sys.modules[L.PACKAGE] = sentinel
        self.assertFalse(L.install())
        self.assertIs(sentinel, sys.modules[L.PACKAGE])

    def _shadowed_by(self, write: Callable[[Path], None]) -> None:
        """Put a candidate-supplied `build123d` at the front of `sys.path`."""
        raw = tempfile.TemporaryDirectory()
        self.addCleanup(raw.cleanup)
        write(Path(raw.name))
        sys.path.insert(0, raw.name)
        self.addCleanup(sys.path.remove, raw.name)
        importlib.invalidate_caches()
        self.addCleanup(importlib.invalidate_caches)

    def test_it_declines_when_the_candidate_ships_its_own_build123d(self) -> None:
        """The sealed input directory is `sys.path[0]` by the time this runs.

        A designer who ships `build123d.py` beside the model shadows the library
        today, and must keep shadowing it: a shadowing *module* has no
        `submodule_search_locations`, so there is nowhere for
        `_carries_the_inventory` to look and the facade steps aside rather than
        deciding what the candidate's file was supposed to mean.
        """
        self._shadowed_by(lambda root: (root / f"{L.PACKAGE}.py").write_text(
            "SHADOW = 1\n", encoding="utf-8"))

        self.assertFalse(L.install())
        self.assertNotIn(L.PACKAGE, sys.modules,
                         "declining means leaving the name alone, so the "
                         "candidate's own file resolves the way it always did")

    def test_it_declines_when_the_candidate_ships_its_own_build123d_package(
            self) -> None:
        """The other shape of the same file, and the one that was not declined.

        A designer may ship `build123d/` rather than `build123d.py`, and a
        package has `submodule_search_locations` -- so a check that asked only
        whether the spec was a package accepted it and the boundary installed
        itself over a package the candidate deliberately supplied. Reproduced
        before the repair, in a child with this directory on `sys.path[0]`: the
        candidate's first attribute access raised `ModuleNotFoundError: No module
        named 'build123d.persistence'`, naming a submodule the candidate never
        wrote, from a package it did.

        `_carries_the_inventory` is what declines both: this package has search
        locations and not one of the 24 submodules the search would import out of
        them.
        """
        def write(root: Path) -> None:
            package = root / L.PACKAGE
            package.mkdir()
            (package / "__init__.py").write_text("SHADOW = 1\n", encoding="utf-8")

        self._shadowed_by(write)

        self.assertFalse(L.install())
        self.assertNotIn(
            L.PACKAGE, sys.modules,
            "declining means leaving the name alone, so the candidate's own "
            "package resolves the way it always did -- and being a package "
            "rather than a module is not what decides it")

    def test_it_declines_a_complete_package_the_candidate_supplied(self) -> None:
        """The shadow the shape rule cannot see, and the one that meant it most.

        A candidate that ships a `build123d/` carrying all 24 submodule names
        satisfies `_carries_the_inventory` exactly -- asserted below, because a
        fixture that declined for the *old* reason would prove nothing about the
        new one. `installed_version()` then reads the installed distribution's
        metadata, which is a fact about site-packages and not about the package
        on `sys.path`, so first contact would arm against a release the candidate
        never supplied and rewrite the one it did.

        Measured at `d5e9a7f`, before the origin rule existed: the shape rule
        returned True and `install()` returned **True** over this exact package.
        Only where it came from separates the two, so the boundary says which
        directory is the candidate's and this is what it buys.
        """
        def write(root: Path) -> None:
            package = root / L.PACKAGE
            package.mkdir()
            (package / "__init__.py").write_text(
                "SHADOW = 'supplied on purpose'\n", encoding="utf-8")
            for sub in L.SUBMODULES:
                (package / f"{sub}.py").write_text(
                    "# supplied by the candidate\n", encoding="utf-8")

        self._shadowed_by(write)
        candidate_dir = sys.path[0]

        spec = importlib.util.find_spec(L.PACKAGE)
        self.assertTrue(
            L._carries_the_inventory(spec),
            "this fixture is supposed to satisfy the shape rule -- if it does "
            "not, it is being declined for the old reason and says nothing "
            "about the origin rule it was written for")
        self.assertTrue(L._is_the_candidates_own(spec, candidate_dir))

        self.assertFalse(
            L.install(candidate_dir),
            "the boundary installed over a complete, well-formed build123d the "
            "candidate deliberately supplied")
        self.assertNotIn(L.PACKAGE, sys.modules)

    def test_a_package_outside_the_candidates_directory_is_not_theirs(self) -> None:
        """The other direction, so the origin rule cannot pass by declining all.

        The installed build123d is not in the sealed input directory, and a rule
        that answered True for everything would decline the real package too --
        which is a facade that never installs and a slice that ships nothing.
        """
        real = importlib.util.find_spec(L.PACKAGE)
        self.assertIsNotNone(real)
        raw = tempfile.TemporaryDirectory()
        self.addCleanup(raw.cleanup)
        self.assertFalse(L._is_the_candidates_own(real, raw.name))
        self.assertFalse(L._is_the_candidates_own(real, None),
                         "with no candidate directory there is nothing for a "
                         "package to be inside of")

    def test_it_declines_a_loader_that_cannot_hand_over_the_code(self) -> None:
        """PEP 451 requires `exec_module`; `get_code` belongs to `SourceLoader`.

        `install()` reads `loader.get_code(PACKAGE).co_consts` to answer
        `__doc__` correctly, and read unguarded that raised `AttributeError:
        'NoGetCodeLoader' object has no attribute 'get_code'` out of the boundary
        -- an unhandled exception on an import the import system handles
        perfectly, since a vendored, plugin or metapath loader need not have it.

        The search locations are the **real** build123d directory on purpose. A
        fabricated one is not a listable directory, so `_carries_the_inventory`
        declines first and the guard below is never reached -- which is exactly
        how this looked repaired when it was not.
        """
        real = importlib.util.find_spec(L.PACKAGE)
        self.assertIsNotNone(real)

        class NoGetCode:
            def create_module(self, spec):
                return None

            def exec_module(self, module):
                module.marker = 42

        def spec_without_get_code(name: str, package: str | None = None):
            if name != L.PACKAGE:
                return original(name, package)
            spec = importlib.machinery.ModuleSpec(
                name, NoGetCode(), origin=real.origin, is_package=True)
            spec.submodule_search_locations = list(
                real.submodule_search_locations)
            return spec

        original = importlib.util.find_spec
        importlib.util.find_spec = spec_without_get_code
        self.addCleanup(setattr, importlib.util, "find_spec", original)

        self.assertFalse(L.install(), "the facade installed over a loader whose "
                                      "code it cannot read, so `__doc__` would "
                                      "be answered wrongly")
        self.assertNotIn(L.PACKAGE, sys.modules)

    def test_it_declines_when_build123d_cannot_be_found_at_all(self) -> None:
        """A checkout without the dependency gets a normal ImportError from the
        candidate's own import, raised by the import system and not by this."""
        original = importlib.util.find_spec

        def missing(name: str, package: str | None = None):
            return None if name == L.PACKAGE else original(name, package)

        importlib.util.find_spec = missing
        self.addCleanup(setattr, importlib.util, "find_spec", original)
        self.assertFalse(L.install())
        self.assertNotIn(L.PACKAGE, sys.modules)


class TheBoundaryInstallsItInOnePlaceTest(unittest.TestCase):
    """Read as syntax, because the ordering is the protection.

    Installed before the seal, the facade would be doing importlib work with more
    authority than the candidate gets. Installed after `A.load`, it would be
    replacing an import the candidate has already made. Outside the stopwatch, it
    would move work out of `build_seconds` without making anything faster, which
    `docs/baseline.md` names as the one thing this change must not do. None of
    those three is visible in any return value.
    """

    def _build_body(self) -> list[ast.stmt]:
        tree = ast.parse((PACKAGE_ROOT / "build_child.py").read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "_build":
                return node.body
        raise AssertionError("build_child._build is gone")

    def _index_of(self, body: list[ast.stmt], predicate) -> int:
        for index, node in enumerate(body):
            if predicate(node):
                return index
        return -1

    def test_the_child_installs_the_facade_after_the_seal_and_inside_the_clock(
            self) -> None:
        body = self._build_body()

        def calls(name: str):
            def check(node: ast.stmt) -> bool:
                return (isinstance(node, ast.Expr)
                        and isinstance(node.value, ast.Call)
                        and isinstance(node.value.func, ast.Attribute)
                        and node.value.func.attr == name)
            return check

        def starts_the_clock(node: ast.stmt) -> bool:
            return (isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "started"
                            for t in node.targets))

        def loads_the_model(node: ast.stmt) -> bool:
            return (isinstance(node, ast.Assign)
                    and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Attribute)
                    and node.value.func.attr == "load")

        seal = self._index_of(body, calls("seal_syscalls"))
        clock = self._index_of(body, starts_the_clock)
        install = self._index_of(body, calls("install"))
        load = self._index_of(body, loads_the_model)

        self.assertNotEqual(-1, install,
                            "build_child._build does not install the facade, so "
                            "every authored build pays for sklearn, ezdxf, "
                            "svgpathtools and svgwrite again -- measured 1.739 s "
                            "on the bearing candidate")
        self.assertLess(seal, install, "the facade must run under the same "
                                       "syscall filter the candidate does")
        self.assertLess(clock, install, "moving the facade out of `build_seconds` "
                                        "shrinks the number without making the "
                                        "child faster")
        self.assertLess(install, load, "the candidate's first import must find "
                                       "the facade already in sys.modules")

    def test_the_child_names_the_directory_it_sealed_when_it_installs(self) -> None:
        """The same directory on both lines, read as syntax.

        The facade declines a `build123d` resolved out of the candidate's own
        directory, and it cannot know which directory that is -- the boundary
        does, because it is the one that put it on `sys.path`. So the property is
        that the identifier inserted into `sys.path` is the identifier handed to
        `install()`. Passing *a* directory is not enough and passing none at all
        silently restores the defect: `install()` takes `candidate_dir=None` so
        that the probes and fixtures which have no candidate can call it, which
        makes the call site the only place this can be checked.

        D8's finding, again: a protection whose absence is invisible to any
        assertion about a return value has to be read out of the syntax tree.
        """
        body = self._build_body()

        def names_in(node: ast.AST) -> set[str]:
            return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}

        sealed: set[str] = set()
        handed: set[str] = set()
        for node in body:
            if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)):
                continue
            call = node.value
            if not isinstance(call.func, ast.Attribute):
                continue
            if call.func.attr == "insert" and names_in(call.func).issuperset({"sys"}):
                sealed |= names_in(call) - {"sys", "str"}
            elif call.func.attr == "install":
                handed = names_in(call) - {"L"}

        self.assertNotEqual(
            set(), handed,
            "build_child calls `install()` with no directory, so the facade has "
            "nothing to compare a spec against and a candidate's own complete "
            "build123d package is installed over -- measured at d5e9a7f")
        self.assertTrue(
            handed <= sealed,
            f"the directory handed to install() ({sorted(handed)}) is not the "
            f"one the boundary inserted into sys.path ({sorted(sealed)}), so the "
            "origin rule is being asked about the wrong directory")

    def test_the_boundary_never_imports_build123d_at_module_level(self) -> None:
        """The facade is only worth anything if nothing above it has already
        executed the package. `_export` keeps its `from build123d import ...`
        inside the function for exactly this reason."""
        for module in ("build_child.py", "lazy_build123d.py"):
            with self.subTest(module=module):
                self.assertNotIn(L.PACKAGE,
                                 _module_level_imports(PACKAGE_ROOT / module))


if __name__ == "__main__":
    unittest.main()
