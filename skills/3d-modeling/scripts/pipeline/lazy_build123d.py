#!/usr/bin/env python3
"""`import build123d` in the confined child, without the libraries nobody asked for.

Used by `build_child.py` and by nothing else: it is installed inside the one-shot
child, after the syscall filter, and the parent never imports either module.

**The measurement.** `build123d/__init__.py` is eager. It imports 24 submodules,
and importing *any* one of them executes the package body first, so a candidate
that asks for seven names pays for `sklearn` and `ezdxf` and everything those
two drag with them. Measured on the real bearing candidate through the real
confined boundary, fresh child per run, arms interleaved: the numbers, the spread
and the per-submodule attribution are in `docs/baseline.md` under "the lazy
build123d facade", which is also where the `build_seconds` change point is
recorded. Measured in the same child: the eager import loads 3155 modules and
this one loads 2296.

**The seam is `sys.modules`, and it is repo-owned.** `install()` binds the name
`build123d` to a module object built from `find_spec` -- the real `__path__`, the
real loader, *not executed* -- carrying a PEP 562 `__getattr__`. A name is
resolved by importing submodules until one carries it. Anything the search cannot
serve executes the real `__init__.py` at full price, so no name and no side
effect is lost: they are deferred, and only for as long as nothing asks.

**Why the search order cannot change what a name means.** Verified against
`build123d 0.11.1` over the package's **whole namespace** and not just `__all__`,
because a candidate can read a name the package never advertised: for each of the
474 names `build123d` binds, walk `SEARCH` and compare the first hit against what
`__init__.py` bound. **179 of them have more than one provider and 0 resolve to a
different object** -- 83 of the 200 public names are among the multiply-provided
ones. Every provider of a name provides the identical object, so search order
cannot decide what an import means. That is a fact about one release, which is
what `PROVEN_VERSIONS` is for, and
`benchmarks/heavy/test_lazy_build123d_heavy.py` is where it is re-run.

**The search walks the package's own import order, minus the submodules in
`DEFERRED`, and that omission is the entire design.** `SEARCH` is `SUBMODULES`
less `DEFERRED` -- a set difference against what `build123d/__init__.py` itself
imports, in the order it imports it, rather than a hand-picked list of what
somebody thought was cheap. The justification is "the smallest omission that
keeps the measured win", not "it serves the candidates checked in here", because
an authored candidate is arbitrary by contract; so what the omission buys is a
property of the mechanism rather than of one import list. `exporters` is
`__init__`'s sixth import and `import_dxf` its ninth, both ahead of the
submodules that carry `Box`, `Compound` and `chamfer`, and both reach `ezdxf`.
Taking them out of the search means no name lookup by any candidate can load it,
and `benchmarks/heavy/test_lazy_build123d_heavy.py` asserts that on `sys.modules`
rather than on a clock.

A cheap-first *reordering* was measured against this and is not shipped. It is
within the run-to-run spread on the candidate it was measured on (arm
`cheapfirst`, `docs/baseline.md`), and it would make the omission inert, because
a search that stops at the first hit never reaches whatever was sorted to the
back. It is rejected for what it does to the *next* candidate: the order would
then be an unchecked claim about relative cost, and a name served by a late
submodule would walk into everything sorted behind it.

Seven of the 200 public names live only in the omitted submodules (`DotLength`,
`Export2D`, `ExportDXF`, `ExportSVG`, `LineType`, `detect_primitives`,
`import_dxf`). A candidate asking for one of them executes the real `__init__`
and pays what it costs -- measured, no gain and no regression.

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

**`vars()` and `__dict__` do not reach `__getattr__` either, and that is a second
hole of the same shape.** PEP 562 is consulted only when ordinary lookup
*fails*, and `module.__dict__` never fails: `types.ModuleType` answers it from a
slot. Measured on the facade before this was fixed: `build123d.__dict__` carried
**9** names where the real package carries **485**, and `'Box' in
vars(build123d)` was `False` where build123d answers `True` -- behind the same
byte-identical mesh as the `dir()` defect, so nothing built could have seen it.
Anything that reads a module's namespace rather than asking it for a name
observed a different package without ever calling `__getattr__`.

The module's *class* is the only hook for that, so `install()` gives the facade a
`types.ModuleType` subclass whose `__dict__` is a property that executes the real
`__init__.py` first. It is the same answer `__dir__` gives to the same kind of
question -- a whole-namespace question cannot be answered lazily -- through the
one route that exists for it. `importlib.util.LazyLoader` reassigns
`module.__class__` for its own laziness and restores `types.ModuleType` on first
use, and `_full()` restores it here for the reason it pops `__getattr__`: what is
left afterwards has to be what an ordinary import leaves. Attribute lookup never
touches the property -- CPython reads a module's namespace slot directly, which
is exactly why `__getattr__` could not cover this -- so the search path is
unchanged, and the facade's own code holds that namespace in a local rather than
reaching it back through the hook it just installed.

One difference outlives none of this and is stated rather than hidden:
`type(build123d)` is the subclass while the facade is still lazy, because the
subclass *is* the hook. It is gone at the first question that forces the real
package, and `benchmarks/heavy/test_lazy_build123d_heavy.py` measures both halves
of that instead of taking this paragraph's word for it.

**That boundary has a write side, and the import system is what uses it.**
`import build123d.pack` never asks the package for an attribute: the import
system *sets* one, binding the submodule onto its parent, and a namespace write
reaches `__getattr__` no more than a namespace read does. For 22 of the 24
submodules that write is what `build123d/__init__.py` leaves anyway. For the two
in `REBOUND` it is not, and the facade answered `build123d.pack` with a module
where build123d answers with a function -- `TypeError: 'module' object is not
callable` for a candidate that did nothing unusual, measured in one interpreter
against both arms. `_Facade.__setattr__` declines those two writes and lets the
search answer, which is the only thing that knows. It is also why the search no
longer clears its own imports off the package afterwards: one rule at the write
covers the facade's imports and the candidate's, where clearing up afterwards
only ever covered the facade's.

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
import importlib.machinery
import importlib.util
import os
import sys
import types
from typing import Any

PACKAGE = "build123d"

# The releases whose 200 public names were compared object-by-object against
# every submodule that carries them, with 0 conflicts. Adding a release here
# means running that sweep against it -- `benchmarks/heavy/
# test_lazy_build123d_heavy.py::TheFacadeIsTheSamePackageTest` is the sweep --
# not widening a range until the gate goes green.
PROVEN_VERSIONS = frozenset({"0.11.1"})

# Every submodule `build123d/__init__.py` imports, **in the order it imports
# them**. It is the package's own list and not a chosen one: reordering it is
# how a facade stops being a description of build123d and becomes a set of
# guesses about which submodules are cheap, and the guesses are what go stale on
# the next release. `test_lazy_build123d.py` parses the installed `__init__.py`
# and fails if this tuple and that file disagree in membership *or* in order.
SUBMODULES = (
    "build_common", "build_enums", "build_line", "build_part", "build_sketch",
    "exporters", "geometry", "importers", "import_dxf", "joints", "mesher",
    "objects_curve", "objects_part", "objects_sketch", "operations_generic",
    "operations_part", "operations_sketch", "pack", "topology", "drafting",
    "persistence", "exporters3d", "text", "brep_from_stl",
)

# The three the search does not walk, and the whole of the design. Everything
# else in this module is bookkeeping around a search that mirrors the package.
#
# Two of them are here for seconds and one is here for correctness, and the
# difference is worth the four lines it costs, because a reader who assumes all
# three earn their place the same way will remove the wrong one.
#
# `exporters` (`__init__`'s sixth import) and `import_dxf` (its ninth) are ahead
# of the submodules that carry `Box`, `Compound` and `chamfer`, and both reach
# `ezdxf`. Measured on the bearing candidate, serving either costs about 0.7 s.
#
# `brep_from_stl` costs **+0.011 s** against a 0.39 s run-to-run spread -- it is
# `__init__`'s *last* import, so a search that stops at the first hit only reaches
# it for a name nothing else carries, and such a name falls through to the real
# `__init__` anyway. On the seconds alone it had earned nothing and was removed.
# The identity sweep put it back: `build123d.brep_from_stl` binds `copy` to the
# **module** where `__init__` leaves `copy.copy`, the *function*, from
# `exporters`, and `T` and `TOLERANCE` differ too -- so serving it breaks the
# 0-conflict property the whole search rests on, for a candidate that never
# mentioned it. It is omitted because it cannot be served correctly, not because
# it is slow, and that is why removing it on the timing would have been wrong.
DEFERRED = ("exporters", "import_dxf", "brep_from_stl")

SEARCH = tuple(name for name in SUBMODULES if name not in DEFERRED)

# The submodules whose own name `build123d/__init__.py` leaves bound to something
# that is **not** the submodule: `from build123d.pack import pack` puts the
# *function* there, and `from build123d.import_dxf import import_dxf` does the
# same. Every one of the other 22 is left as the module, which is what the import
# system already bound -- measured name by name against the installed package,
# and these two are the whole of the difference.
#
# It matters because the import system's parent binding is a *namespace write*.
# `import build123d.pack` makes it, `__getattr__` is never consulted, and the
# facade answered with a module where build123d answers with a callable --
# `TypeError: 'module' object is not callable` for a candidate that did nothing
# unusual. `_Facade.__setattr__` declines exactly these two writes and lets the
# search decide, which is the only place that knows.
#
# A per-release fact like `SUBMODULES`, and pinned the same way:
# `test_lazy_build123d.py` reads `from build123d.X import X` out of the installed
# `__init__.py` and fails if this tuple and that file disagree.
REBOUND = ("import_dxf", "pack")

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


def _carries_the_inventory(spec: importlib.machinery.ModuleSpec) -> bool:
    """True when `spec` is a package that can supply every name in `SUBMODULES`.

    The whole of what the facade offers is *I will answer a name by importing
    these 24 submodules out of this package*, so a `build123d` that cannot supply
    them is not one this module has any business standing in front of, however it
    reached `sys.path`. Both shapes of candidate shadow fail here, and for the
    same reason rather than for two:

    * a candidate's own `build123d.py` is a *module*. It has no
      `submodule_search_locations`, so there is nowhere to look and nothing to
      find;
    * a candidate's own `build123d/` is a *package*. It has search locations and
      not one of the submodules in them. Measured before this asked about more
      than the search locations: the facade installed over it, and the
      candidate's first attribute access died with `ModuleNotFoundError: No
      module named 'build123d.persistence'` -- an error about a submodule it
      never wrote, raised out of a package it deliberately supplied.

    One `os.listdir` per search location and set membership against
    `importlib.machinery.all_suffixes()`, which is the import machinery's own
    answer to what a module may be called rather than this module's guess at it:
    a measured **0.11 ms** median over nine fresh interpreters (0.10-0.18)
    against the ~1.6 ms `install()` already cost, and a shadow is refused on the
    first name that misses.

    It is deliberately a question about *shape* and not about identity. Proving
    this is the swept release means reading distribution metadata, which costs
    132 ms and is the reason `_arm()` defers it to first contact. What that
    leaves open is a candidate shipping a package that carries all 24 names,
    which this cannot tell from the real one -- and which is why the version
    guard, not this, is what says the search order is safe. A release that
    renamed a submodule fails here and gets ordinary build123d, the same
    direction `PROVEN_VERSIONS` fails.
    """
    entries: set[str] = set()
    for location in spec.submodule_search_locations or ():
        try:
            entries.update(os.listdir(location))
        except OSError:            # unreadable, or not a directory at all
            return False
    suffixes = importlib.machinery.all_suffixes()
    return all(sub in entries or any(sub + suffix in entries for suffix in suffixes)
               for sub in SUBMODULES)


def install() -> bool:
    """Bind `build123d` to the facade. True if it was installed.

    Cheap by construction -- one `find_spec`, one directory listing and one
    module object, ~1.6 ms with the listing's measured 0.11 ms inside it. It
    decides nothing about *which* build123d this is; `_arm()` does that on first
    contact, so the decision costs nothing to a candidate that never asks.

    It declines whenever `find_spec` does not resolve to a package carrying the
    inventory the search is written against, which is what keeps a candidate's
    own `build123d` working exactly as it does today: the sealed input directory
    is `sys.path[0]` by the time this runs, a shadowing *module* has no
    `submodule_search_locations` and a shadowing *package* has none of the
    submodules, and the facade steps aside rather than deciding what the
    candidate's file meant. `_carries_the_inventory` is the one rule both fail.
    """
    if PACKAGE in sys.modules:
        return False
    try:
        spec = importlib.util.find_spec(PACKAGE)
    except (ImportError, ValueError):              # a broken or shadowed install
        return False
    if spec is None or spec.loader is None or not _carries_the_inventory(spec):
        return False

    module = importlib.util.module_from_spec(spec)
    loader = spec.loader
    real_path = spec.submodule_search_locations
    # The namespace, held directly. Everything below reads and writes it through
    # this name and never through `module.__dict__`, because `__dict__` is about
    # to become the hook two paragraphs of the module docstring are about: going
    # back through it would execute the real `__init__.py` on the facade's first
    # own bookkeeping and there would be nothing left to defer.
    ns = module.__dict__
    # The hook. `module_from_spec` put `__path__` here; taking it out is what
    # routes `import build123d.topology` through `__getattr__` at all.
    ns.pop("__path__", None)
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
        """Import one submodule. What it binds onto the facade is `__setattr__`'s.

        The import system sets every submodule it imports as an attribute of its
        parent, and that write is the same one a candidate's own `import
        build123d.pack` makes -- so it is answered in one place, at the write,
        rather than cleaned up here for the search's imports and left standing
        for the candidate's.
        """
        return importlib.import_module(f"{PACKAGE}.{sub}")

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
            ns.pop(name, None)
        served.clear()
        # The third hook, and it comes out here for the same reason as the other
        # two rather than being left as a harmless subclass: `type(build123d)` is
        # observable, and a module the boundary handed back with a repo-owned
        # class is not what an ordinary import leaves. It is also the ordering
        # `exec_module` needs -- it executes `__init__.py` into `module.__dict__`,
        # which would otherwise be the property calling back into here.
        module.__class__ = types.ModuleType
        # And put back what `_submodule()` took out. An ordinary import binds a
        # submodule onto its package as it imports it, and only the *first*
        # import does: a cached one comes straight back out of `sys.modules` and
        # touches no parent. So `__init__.py` cannot restore these itself, and
        # `dir(build123d)` would come up short by however many submodules the
        # search happened to walk before it gave up.
        for sub in SUBMODULES:
            cached = sys.modules.get(f"{PACKAGE}.{sub}")
            if cached is not None:
                ns[sub] = cached
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
            return ns[name]
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
        #
        # Still forced here although `__dict__` now gets there first, and that is
        # a measurement rather than a preference: once the namespace hook landed,
        # `dir-loses-its-forced-import` SURVIVED the `dir()`-and-nothing-else
        # probe, because CPython's `module_dir` fetches `__dict__` through
        # ordinary attribute access *before* it looks for a `__dir__` inside it.
        # Two routes still rest on this line -- a candidate calling
        # `build123d.__dir__()`, which never touches `__dict__`, and any
        # interpreter whose `dir()` reads the namespace slot directly the way
        # attribute lookup does. Dropping it would leave `dir()` correct by an
        # implementation detail of one interpreter, which is how the original
        # defect got in.
        _arm()
        _full()
        return sorted(ns)

    class _Facade(types.ModuleType):
        """The facade's class, and the only hook `vars()` has.

        `__getattr__` is asked a question only when ordinary lookup *fails*, and
        `module.__dict__` never fails -- `types.ModuleType` answers it from a
        slot -- so a facade with no class of its own reported 9 names where the
        package reports 485. A property on the class is what CPython consults
        first, and this is what it is for.

        Exactly one instance, so the property closes over that module rather than
        reading `self`: reading it back off `self` would be `__dict__` again.
        Attribute lookup does not come through here at all, which is why the
        search costs nothing for it.
        """

        @property
        def __dict__(self) -> dict[str, Any]:      # type: ignore[override]
            _arm()
            _full()
            return ns

        def __setattr__(self, name: str, value: Any) -> None:
            """Decline the two parent bindings the real `__init__` overwrites.

            The import system binds every submodule it imports onto its parent,
            and it does it with `setattr` -- a namespace write, so `__getattr__`
            never sees it and cannot correct it. For 22 of the 24 that binding is
            exactly what `build123d/__init__.py` leaves, and it stands. For the
            two in `REBOUND` it is not: `__init__.py` puts a *function* under
            each of those names, so `import build123d.pack` followed by
            `build123d.pack(...)` raised `TypeError: 'module' object is not
            callable` through the facade and worked against the package.
            Measured in one interpreter, both arms.

            Declining is all that is needed, because `__getattr__` then answers:
            the search serves `pack` from the `pack` submodule itself -- the
            function, identical object -- and `import_dxf` is omitted from the
            search, so it falls through to the real `__init__` like every other
            name the search cannot serve, which is where its function is.
            """
            if name in REBOUND and value is sys.modules.get(f"{PACKAGE}.{name}"):
                return
            super().__setattr__(name, value)

    module.__getattr__ = _getattr
    module.__dir__ = _dir
    module.__class__ = _Facade
    sys.modules[PACKAGE] = module
    return True
