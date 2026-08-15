#!/usr/bin/env python3
"""`import build123d` in the confined child, without the libraries nobody asked for.

Used by `build_child.py` and by nothing else: it is installed inside the one-shot
child, after the syscall filter, and the parent never imports either module.

**The measurement.** `build123d/__init__.py` is eager. It imports 24 submodules,
and importing *any* one of them executes the package body first, so a candidate
that asks for seven names pays for `sklearn`, `ezdxf`, `svgpathtools`,
`svgelements`, `svgwrite` and `ocpsvg` as well. On the real bearing candidate
through the real confined boundary, ten interleaved fresh-child runs per arm:
median wall **5.784 s -> 4.045 s, a 1.739 s (30.1%) cut**, with the ranges not
overlapping (worst lazy 4.253 s < best base 5.666 s) and one STL sha256 across
all twenty runs. `PYTHONPROFILEIMPORTTIME=1` in the same child: 2836 modules and
5.223 s of import self-time become 1980 and 3.107 s.

**The seam is `sys.modules`, and it is repo-owned.** `install()` binds the name
`build123d` to a module object built from `find_spec` -- the real `__path__`, the
real loader, *not executed* -- carrying a PEP 562 `__getattr__`. A name is
resolved by importing submodules until one carries it. Anything the search cannot
serve executes the real `__init__.py` at full price, so no name and no side
effect is lost: they are deferred, and only for as long as nothing asks.

**Why the search order cannot change what a name means.** Verified against
`build123d 0.11.1` by importing the real package and comparing object identity
for all 200 names in `__all__` against every submodule that carries them: 83
names are re-exported by more than one submodule and **0 resolve to a different
object from a different submodule**. Every provider of a name provides the
identical object. That property is a fact about one release, which is what
`PROVEN_VERSIONS` is for.

**Why three submodules are omitted rather than merely ordered last.** Ordering
the expensive ones last would already have served the checked-in candidates,
because a search stops at the first hit and never reaches them. That is a
property of *our* candidates' import lists, and an authored candidate is
arbitrary by contract. Omitting them makes it a property of the mechanism: with
`exporters`, `import_dxf` and `brep_from_stl` outside `SEARCH`, no name lookup by
any candidate can pull `sklearn` or `ezdxf` in, and `benchmarks/heavy/
test_lazy_build123d_heavy.py` asserts exactly that on `sys.modules` rather than
on a clock. Measured import cost in the confined child: `brep_from_stl` 941 ms
(`sklearn.cluster` 937 ms), `exporters` 748 ms (`ezdxf` 651 ms + `svgpathtools`
89 ms), `import_dxf` 651 ms (`ezdxf`). Seven of the 200 public names live only in
these three (`DotLength`, `Export2D`, `ExportDXF`, `ExportSVG`, `LineType`,
`detect_primitives`, `import_dxf`); a candidate asking for one of them executes
the real `__init__` and pays what it costs -- measured, no gain and no
regression. This is the smallest omission set that keeps the measured win, and
that is the whole of its justification.

**Why nothing is armed until the package is first touched.** The experiment this
came from ran the version read and `modify_copyreg()` eagerly at install time.
Both are wrong here and one of them badly: `importlib.metadata` costs 132 ms to
import plus 46 ms to answer, and `build123d.persistence` costs **3.19 s** in a
fresh interpreter because it loads OCP. An authored *trimesh* candidate -- which
`docs/baseline.md` prices at ~1.6 s of child and which never names build123d --
would have paid all of it for nothing. So `_arm()` runs on first contact and the
build123d candidate pays what it was going to pay anyway.

`__path__` is the hook that makes that safe. `import build123d.topology` is the
one route into the package that never touches an attribute: the import system
reads `__path__` off the parent and goes straight to the submodule. So `__path__`
is removed from the facade's namespace at install time and served by
`__getattr__`, which is where the version check and `modify_copyreg()` are armed.
Without it, a candidate that imports only submodules would silently get neither.

**Why a pinned version and not a range.** `pyproject.toml` says
`build123d>=0.9` and is deliberately not narrowed for this: a release that
*moves* a name is safe, because the search misses and the real `__init__` runs;
a release that puts a *different* object under an existing name in an
earlier-searched module would mis-bind silently. That is the one failure this
cannot detect at runtime, so the optimization is switched on only for releases
whose public surface has actually been swept name by name, and every other
release gets ordinary build123d. The facade is inert on those: the first
attribute access executes the real `__init__.py` through the real loader.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
from typing import Any

PACKAGE = "build123d"

# The releases whose 200 public names were compared object-by-object against
# every submodule that carries them, with 0 conflicts. Adding a release here
# means running that sweep against it -- `benchmarks/heavy/
# test_lazy_build123d_heavy.py::TheFacadeIsTheSamePackageTest` is the sweep --
# not widening a range until the gate goes green.
PROVEN_VERSIONS = frozenset({"0.11.1"})

# Every submodule `build123d/__init__.py` imports, cheapest first. The order is a
# cost property only: the 0-conflict sweep above is what makes it unable to
# change which object a name binds to. `mesher`, `drafting` and `importers` are
# cheap but rarely wanted, so they sit after the common names and are reached
# only by a candidate that actually asks for one of theirs.
#
# `test_lazy_build123d.py` parses the installed `__init__.py` and fails if this
# inventory and that file ever disagree, because a submodule this list has never
# heard of is a name the facade would answer with the wrong module or not at all.
SUBMODULES = (
    "build_enums", "geometry", "build_common", "topology",
    "build_line", "build_part", "build_sketch",
    "objects_part", "objects_sketch", "operations_generic",
    "operations_part", "operations_sketch", "objects_curve",
    "pack", "joints", "exporters3d", "text", "persistence",
    "mesher", "drafting", "importers",
    # Omitted from the search; listed here because this tuple is the inventory
    # of what the package imports, and the omission is a set difference against
    # it rather than a hand-picked include list.
    "exporters", "import_dxf", "brep_from_stl",
)

# The three that carry `sklearn`, `ezdxf`, `svgpathtools` and `svgwrite`.
DEFERRED = ("exporters", "import_dxf", "brep_from_stl")

SEARCH = tuple(name for name in SUBMODULES if name not in DEFERRED)

_MISSING = object()


def installed_version() -> str | None:
    """The installed build123d distribution's version, or `None` if unreadable.

    Function-local import for the reason the whole module exists: `importlib.
    metadata` is 132 ms of import on this machine, and a candidate that never
    names build123d must not pay it. Reached only from `_arm()`, which runs on
    first contact with the package.

    `PackageNotFoundError` is not an error here. A checkout that vendored
    build123d without installing it has no distribution metadata, and the honest
    answer to "which release is this" is then "unknown" -- which is the fallback
    case, not a crash.
    """
    import importlib.metadata                     # noqa: PLC0415 - see docstring
    try:
        return importlib.metadata.version(PACKAGE)
    except importlib.metadata.PackageNotFoundError:
        return None


def install() -> bool:
    """Bind `build123d` to the facade. True if it was installed.

    Cheap by construction -- one `find_spec` and one module object, ~1.6 ms. It
    decides nothing about *which* build123d this is; `_arm()` does that on first
    contact, so the decision costs nothing to a candidate that never asks.

    It declines whenever `find_spec` does not resolve to an importable package,
    which is what keeps a candidate's own `build123d.py` working exactly as it
    does today: the sealed input directory is `sys.path[0]` by the time this
    runs, a shadowing *module* has no `submodule_search_locations`, and the
    facade steps aside rather than deciding what the candidate's file meant.
    """
    if PACKAGE in sys.modules:
        return False
    try:
        spec = importlib.util.find_spec(PACKAGE)
    except (ImportError, ValueError):              # a broken or shadowed install
        return False
    if spec is None or not spec.submodule_search_locations or spec.loader is None:
        return False

    module = importlib.util.module_from_spec(spec)
    loader = spec.loader
    real_path = spec.submodule_search_locations
    # The hook. `module_from_spec` put `__path__` here; taking it out is what
    # routes `import build123d.topology` through `__getattr__` at all.
    module.__dict__.pop("__path__", None)
    # The one attribute that cannot be deferred like every other name. Popping
    # the key does not send it to `__getattr__`: attribute lookup then finds
    # `types.ModuleType.__doc__`, which is the *type's* docstring and is a
    # worse answer than the `None` that `module_from_spec` seeds. So it is read
    # off the code object the loader already knows how to produce -- 0.5-0.7 ms
    # against a cached `.pyc` -- and a candidate that reads `build123d.__doc__`
    # before touching anything else gets what the package says.
    consts = loader.get_code(PACKAGE).co_consts
    module.__doc__ = consts[0] if consts and isinstance(consts[0], str) else None

    served: set[str] = set()
    state = {"armed": False, "lazy": False, "full": False}

    def _submodule(sub: str) -> Any:
        """Import one submodule without letting it bind itself onto the facade.

        The import system sets every submodule it imports as an attribute of its
        parent, and for `pack` and `import_dxf` the real `__init__.py` then
        rebinds the name to a *function* of the same name. Leaving the module
        there answers those two with the wrong object -- and it is the search's
        own side effect, so it happens to whichever names the candidate never
        asked about. Found by the identity sweep; no build could have seen it.
        """
        imported = importlib.import_module(f"{PACKAGE}.{sub}")
        if module.__dict__.get(sub) is imported:
            del module.__dict__[sub]
        return imported

    def _arm() -> bool:
        """First contact: decide whether this release may be served lazily.

        Returns True when it may. On any other release this executes the real
        `__init__.py` and the facade is finished -- one branch, so the expensive
        path and the fallback path cannot drift apart.
        """
        if state["armed"]:
            return state["lazy"]
        state["armed"] = True
        # Before anything else can ask for it: `_full()` executes `__init__.py`,
        # whose first statement imports a submodule, which reads `__path__` off
        # this module and would re-enter `__getattr__`.
        module.__path__ = real_path
        if installed_version() in PROVEN_VERSIONS:
            state["lazy"] = True
            # `__init__.py`'s only side effect beyond its imports. It has to
            # happen before a candidate pickles or deep-copies a shape, and a
            # candidate cannot have a shape without having reached here first.
            _submodule("persistence").modify_copyreg()
        else:
            _full()
        return state["lazy"]

    def _full() -> None:
        """Execute the real `__init__.py` into this module object.

        Everything the facade added comes out first, so what is left afterwards
        is what an ordinary import leaves: the same object, the same loader, the
        same namespace. A cached name that the real `__init__` does not rebind
        would otherwise show up in `dir()`, which is the family the `dir()`
        defect below belongs to.
        """
        if state["full"]:
            return
        state["full"] = True
        for name in ("__getattr__", "__dir__", *served):
            module.__dict__.pop(name, None)
        served.clear()
        # And put back what `_submodule()` took out. An ordinary import binds a
        # submodule onto its package as it imports it, and only the *first*
        # import does: a cached one comes straight back out of `sys.modules` and
        # touches no parent. So `__init__.py` cannot restore these itself, and
        # `dir(build123d)` would come up short by however many submodules the
        # search happened to walk before it gave up.
        for sub in SUBMODULES:
            cached = sys.modules.get(f"{PACKAGE}.{sub}")
            if cached is not None:
                module.__dict__[sub] = cached
        loader.exec_module(module)

    def _getattr(name: str) -> Any:
        lazy = _arm()
        if name == "__path__":
            return module.__path__
        # No shortcut for `getattr(build123d, "<a submodule name>")`, and the
        # reason is `import_dxf`: it is both a submodule and a public function,
        # and `__init__.py`'s `from build123d.import_dxf import import_dxf`
        # leaves the *function* under that name. Answering submodule names with
        # the submodule got that one wrong -- caught by the identity sweep, not
        # by any build -- so the search decides, and a name it cannot serve goes
        # to the real `__init__` like every other name it cannot serve.
        if lazy and not name.startswith("__"):
            for sub in SEARCH:
                found = getattr(_submodule(sub), name, _MISSING)
                if found is not _MISSING:
                    setattr(module, name, found)
                    served.add(name)
                    return found
        _full()
        try:
            return module.__dict__[name]
        except KeyError:
            raise AttributeError(
                f"module {PACKAGE!r} has no attribute {name!r}") from None

    def _dir() -> list[str]:
        # `dir()` is a question about the whole namespace, so it is the one
        # question the facade cannot answer lazily. Measured on the experiment
        # that had no `__dir__`: `dir(build123d)` returned 11 names where the
        # real package returns 485 -- behind a byte-identical mesh, so every
        # timing and geometry check passed. A candidate deriving `PARAMS` from
        # `dir()` would have declared something different and nothing would have
        # said so.
        _arm()
        _full()
        return sorted(module.__dict__)

    module.__getattr__ = _getattr
    module.__dir__ = _dir
    sys.modules[PACKAGE] = module
    return True
