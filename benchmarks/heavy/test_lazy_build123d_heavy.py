#!/usr/bin/env python3
"""L0-heavy -- what the lazy `build123d` facade does, in interpreters that just started.

`skills/3d-modeling/scripts/pipeline/test_lazy_build123d.py` holds the claims a
syntax tree can make. These are the ones only a process can: whether a module was
imported, whether a name is the same object, and whether an unproven release gets
ordinary build123d.

**Structure, not milliseconds.** `docs/agents/review-workflow.md` section 7:
*profile with time; regress with structure*. The wall clock found this -- median
6.004 s to 4.332 s on the real bearing candidate through the confined boundary,
ten interleaved runs an arm, ranges not overlapping (`docs/baseline.md`) -- and
the wall clock is a terrible regression control, because a loaded runner moves it
further than the whole effect. So what is asserted here is the causal property: a
minimal candidate's imports leave `ezdxf` out of `sys.modules` entirely. That
fails on the pull request that puts `exporters` or `import_dxf` back into the
search set, and it fails for the same reason the seconds would come back.

**Both directions, every time.** A test that only asserts absence passes just as
well when build123d stopped working. Every structural case here has its arm
without the facade beside it, and the deferred names have a case proving they
still resolve -- and still bring their library with them when they do.

**The identity sweep is the one that matters and the one that goes vacuous.**
The facade resolves a name by importing submodules until one carries it, so the
question is whether any name resolves to a *different* object than the real
`__init__.py` binds. Asking that of a facade that has already fallen back
compares the real package with itself and passes unconditionally -- so the sweep
tracks whether the facade was still lazy at each resolution and fails if it was
not. The defect that earned this: an earlier draft with no `__dir__` returned 11
names from `dir(build123d)` where the package returns 485, behind a
byte-identical mesh. Every timing and geometry check passed.

**A question that forces the package can only be asked first, so it gets its own
interpreter.** `dironly`, `dunderdironly` and `namespaceonly` each ask exactly
one thing of a facade nothing else has touched, and all three were earned rather
than chosen. The `dir()` mutation SURVIVED the whole-surface comparison, because
that comparison reads `__version__` and resolves a fallback name before it
reaches `dir`. `vars(build123d)` -- which reaches a module's namespace without
`__getattr__` ever being consulted, since PEP 562 answers only a lookup that
*failed* -- returned 9 names against 485 at a head where every one of these tests
was green. And the same `dir()` mutation SURVIVED again once the namespace hook
answered for it: `module_dir` fetches `__dict__` through ordinary attribute
access before it looks for a `__dir__` in it, so only a direct `__dir__()` call
still asks `__dir__` anything.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "skills" / "3d-modeling" / "scripts"

# What the *omitted* submodules carry and nothing a served submodule also
# reaches, which is the only set an omission can be held to. `ezdxf` comes
# through both `exporters` and `import_dxf`, and `pyparsing` comes with it.
#
# Two libraries are deliberately absent from this tuple and it is the correction
# that keeps the test honest. `svgpathtools`, `svgelements`, `svgwrite` and
# `ocpsvg` are reached by `importers`, which the facade *serves*, so both arms
# load them and asserting their absence would fail on a correct facade; `scipy`
# is the same through `topology/one_d.py`. The measured whole is 3155 modules in
# the eager arm against 2296 in this one.
OMITTED_STACK = ("ezdxf", "pyparsing")

# `brep_from_stl`'s stack. Omitting it is worth +0.011 s against a 0.39 s spread,
# which is nothing, so its absence from an ordinary build is a consequence of
# build123d importing it *last* rather than of the omission -- and the two claims
# are asserted under separate names rather than in one tuple, so that an ordering
# accident cannot be read as a guarantee the design makes. What the omission of
# `brep_from_stl` actually buys is in the identity sweep, not here.
LAST_IMPORT_STACK = ("sklearn", "joblib", "threadpoolctl")

# What the real bearing commission imports, verbatim from
# `C:\projects\3d\bearing-clamp-discovery\job\model.py`. Seven names, and the
# only reason they are the ones written here is that this is the candidate the
# measurement was taken on -- the contract is that *any* authored candidate gets
# the guarantee about `ezdxf`, which is why that guarantee is a property of the
# omission set rather than of this list.
MINIMAL = "Align, Axis, Box, Compound, Cylinder, Location, chamfer"

_PROBE = '''
import json, pickle, sys, types
sys.path.insert(0, __SCRIPTS__)

# The namespace as `types.ModuleType` itself answers it, which is the one route
# into a module's `__dict__` that a facade cannot intercept -- and that is why
# this is here rather than `build123d.__dict__`. The facade's own `__dict__` hook
# executes the real `__init__.py` on purpose, so asking through it would end the
# laziness these probes exist to observe: the instrument would destroy what it
# measures and every `lazy_throughout` would read False.
RAW = types.ModuleType.__dict__["__dict__"]

mode, arm = sys.argv[1], sys.argv[2]
if arm in ("lazy", "fake"):
    from pipeline import lazy_build123d as L
    if arm == "fake":
        # An explicitly unsupported release. Nothing about build123d changes; the
        # facade is told it is looking at something it has never swept.
        L.installed_version = lambda: "99.0.0-not-a-release"
    assert L.install(), "the facade declined to install"

def structure():
    return {
        "top_level": sorted({name.split(".")[0] for name in sys.modules}),
        "build123d_submodules": sorted(
            name for name in sys.modules if name.startswith("build123d.")),
        "module_count": len(sys.modules),
    }

out = {"arm": arm, "mode": mode}

if mode == "structure":
    from build123d import __MINIMAL__
    out["after_minimal_imports"] = structure()

elif mode == "deferred":
    import build123d
    out["before"] = structure()
    fn = build123d.import_dxf
    out["callable"] = callable(fn)
    out["module_name"] = fn.__module__
    out["after"] = structure()

elif mode == "star":
    namespace = {}
    exec("from build123d import *", namespace)
    out["star"] = sorted(k for k in namespace if not k.startswith("__"))

elif mode == "dironly":
    # `dir()` and nothing else, before any name has forced the fallback. Every
    # other question in this file leaves the facade fully imported long before it
    # reaches `dir`, so asking it there proves nothing about `__dir__` -- measured:
    # the mutation that takes the forced import out of `__dir__` SURVIVED the
    # whole-surface comparison, and this is the case that kills it.
    import build123d
    out["dir"] = sorted(dir(build123d))
    out["dir_len"] = len(out["dir"])

elif mode == "submoduleimport":
    # The route where the *import system* writes the facade's namespace. `import
    # build123d.pack` binds the submodule onto its parent by `setattr`, which no
    # `__getattr__` can see, and `__init__.py` leaves a *function* under that
    # name. Measured before the repair: `build123d.pack` was a module through the
    # facade and a function against the package, so `build123d.pack(shapes)` was
    # `TypeError: 'module' object is not callable`.
    import build123d.pack
    out["pack_type"] = type(build123d.pack).__name__
    out["pack_callable"] = callable(build123d.pack)
    out["pack_qualname"] = getattr(build123d.pack, "__qualname__", None)
    out["pack_home"] = getattr(build123d.pack, "__module__", None)
    # Read before the second import: declining the write must not cost the
    # deferral it was added to protect. `pack` is `__init__`'s eighteenth import
    # and reaches no `ezdxf`.
    out["ezdxf_after_pack"] = "ezdxf" in sys.modules
    import build123d.import_dxf
    out["import_dxf_type"] = type(build123d.import_dxf).__name__
    out["import_dxf_callable"] = callable(build123d.import_dxf)

elif mode == "dunderdironly":
    # `build123d.__dir__()` and nothing else -- the route `dir()` stopped taking.
    # `dir()` on a module fetches `__dict__` through ordinary attribute access
    # before it looks for a `__dir__` in it, and `__dict__` is now the hook, so
    # `dir()` arrives at a package the namespace hook has already made real.
    # Calling `__dir__` itself does not touch `__dict__`, so this is where the
    # forced import inside `__dir__` is still the only thing answering.
    import build123d
    out["dunder_dir"] = sorted(build123d.__dir__())
    out["dunder_dir_len"] = len(out["dunder_dir"])

elif mode == "namespaceonly":
    # `vars()` and `__dict__` and nothing else, before any name has forced the
    # fallback. They are the introspection routes that never reach `__getattr__`:
    # PEP 562 answers a lookup that *failed*, and a module's `__dict__` cannot
    # fail, so the facade was walked straight past. Measured before the hook
    # existed: 9 names here against the package's 485, and `"Box" in
    # vars(build123d)` False. Asked in its own interpreter for the reason
    # `dironly` is -- every other mode has already forced the real `__init__`
    # long before it gets here.
    import build123d
    out["type_before"] = type(build123d).__name__
    out["vars"] = sorted(vars(build123d))
    out["has_box"] = "Box" in vars(build123d)
    out["dict_keys"] = sorted(build123d.__dict__)
    out["type_after"] = type(build123d).__name__

elif mode == "pickle":
    # The route that never touches an attribute of the package: the import
    # system reads `__path__` off the parent and goes straight to the submodule,
    # so `__getattr__` is never called. `modify_copyreg()` is armed there or it
    # is not armed at all, and a candidate that pickles or deep-copies a solid
    # is the one that finds out.
    import build123d.objects_part
    solid = build123d.objects_part.Box(2.0, 3.0, 4.0)
    out["volume"] = round(float(solid.volume), 6)
    out["round_trip_volume"] = round(float(pickle.loads(pickle.dumps(solid)).volume), 6)
    out["copyreg_armed"] = "build123d.persistence" in sys.modules

elif mode == "semantics":
    import build123d
    # Read before anything else can force the fallback: the one property of the
    # facade that is knowingly not equal to the package's own.
    out["doc_on_first_read"] = build123d.__doc__

    if arm == "lazy":
        servable = json.loads(sys.argv[3])
        kept, lazy_throughout = {}, True
        for name in servable:
            lazy_throughout &= "__getattr__" in RAW.__get__(build123d)
            kept[name] = getattr(build123d, name)
        out["served_lazily"] = len(kept)
        out["lazy_throughout"] = lazy_throughout
        # One name that only an omitted submodule can answer. It must force the
        # real `__init__` and it must bring `ezdxf` with it.
        out["fallback_forced_by"] = "ExportSVG"
        kept["ExportSVG"] = build123d.ExportSVG
        out["fallback_happened"] = "__getattr__" not in RAW.__get__(build123d)
        out["identity_mismatches"] = sorted(
            name for name, value in kept.items()
            if build123d.__dict__.get(name, object()) is not value)

    from build123d import Text
    out["text_bbox"] = [round(float(v), 3)
                        for v in Text("Ag", 10.0).bounding_box().size.to_tuple()]
    out["version"] = build123d.__version__
    out["all"] = list(build123d.__all__)
    out["dir"] = sorted(dir(build123d))
    out["namespace"] = sorted(build123d.__dict__)
    out["doc"] = build123d.__doc__
    # Read last, with the package fully imported in both arms. Intercepting
    # `__dict__` needs a class of the facade's own, so this is the field that says
    # the class did not survive the fallback that made it unnecessary.
    out["type_name"] = type(build123d).__name__
    out["name"] = build123d.__name__
    out["loader"] = type(build123d.__loader__).__name__
    out["spec_name"] = build123d.__spec__.name
    out["file_is_the_packages_own"] = build123d.__file__.endswith("__init__.py")
    out["submodule_identity"] = build123d.objects_part.Box is build123d.Box
    try:
        build123d.NoSuchNameAtAll
        out["missing"] = None
    except AttributeError as exc:
        out["missing"] = str(exc)
    out["structure"] = structure()

elif mode == "premise":
    # The sweep the search order rests on, applied by hand in a process where the
    # real package is fully imported: for every name the package binds, walk the
    # facade's own search order and compare the first hit against what the real
    # `__init__` bound. This is what "0 conflicts" means, and it is measured over
    # the whole namespace rather than over `__all__`, because a candidate can
    # read a name the package never advertised.
    import importlib
    from pipeline.lazy_build123d import REBOUND, SEARCH, SUBMODULES
    import build123d
    out["pinned_rebound"] = list(REBOUND)
    # Which submodules the executed package leaves bound to something that is not
    # the submodule -- asked by identity, in a process where `__init__.py` has
    # run, because that is the only instrument that cannot be wrong about it.
    # `__init__.py` reaches `pack` through `from build123d.pack import *`, so the
    # syntax tree can only guess.
    out["rebound"] = [sub for sub in SUBMODULES
                      if build123d.__dict__.get(sub)
                      is not importlib.import_module("build123d." + sub)]
    modules = {sub: importlib.import_module("build123d." + sub) for sub in SEARCH}
    MISSING = object()
    wrong, unserved, servable = [], [], []
    for name in sorted(build123d.__dict__):
        if name.startswith("__"):
            continue
        real = build123d.__dict__[name]
        for sub in SEARCH:
            found = getattr(modules[sub], name, MISSING)
            if found is not MISSING:
                (wrong if found is not real else servable).append(name)
                break
        else:
            unserved.append(name)
    out["wrong"] = wrong
    out["servable"] = servable
    out["unserved"] = unserved
    out["unserved_public"] = sorted(set(unserved) & set(build123d.__all__))

print(json.dumps(out))
'''


def _fresh(mode: str, arm: str, *args: str) -> dict:
    """One probe, one interpreter, so `sys.modules` means what it says.

    `-S` is deliberately not used: the point is to reproduce the import graph a
    confined child actually has, not an artificially bare one.
    """
    source = (_PROBE.replace("__SCRIPTS__", repr(str(SCRIPTS)))
                    .replace("__MINIMAL__", MINIMAL))
    done = subprocess.run([sys.executable, "-c", source, mode, arm, *args],
                          capture_output=True, text=True, cwd=str(REPO), timeout=900)
    if done.returncode != 0:
        raise AssertionError(f"probe {mode}/{arm} failed:\n{done.stderr}")
    return json.loads(done.stdout.strip().splitlines()[-1])


_CACHE: dict[tuple[str, ...], dict] = {}


def _probe(mode: str, arm: str, *args: str) -> dict:
    key = (mode, arm, *args)
    if key not in _CACHE:
        _CACHE[key] = _fresh(mode, arm, *args)
    return _CACHE[key]


class TheDeferredStackStaysOutOfTheChildTest(unittest.TestCase):
    """Condition 3, and the only regression control this slice has.

    Asserted on `sys.modules`, never on a duration: `conftest.py` already refuses
    wall clock as a control on this machine -- the same suite at the same commit
    measured 43.3 s and 76.9 s within one session -- and a millisecond threshold
    over a 1.7 s effect would fail on a loaded runner and pass on a fast one
    while measuring nothing either way.
    """

    def test_a_minimal_candidates_imports_load_no_ezdxf(self) -> None:
        after = _probe("structure", "lazy")["after_minimal_imports"]
        for library in OMITTED_STACK:
            with self.subTest(library=library):
                self.assertNotIn(
                    library, after["top_level"],
                    f"{library} is loaded after seven ordinary build123d names. "
                    "The omission is what keeps it out: build123d imports "
                    "`exporters` sixth and `import_dxf` ninth, ahead of the "
                    "submodules carrying Box, Compound and chamfer, so putting "
                    "either back into SEARCH lets any candidate's name lookup "
                    "drag ezdxf in -- measured at about 0.7 s each.")
        for submodule in ("exporters", "import_dxf"):
            with self.subTest(submodule=submodule):
                self.assertNotIn(f"build123d.{submodule}",
                                 after["build123d_submodules"])

    def test_the_sklearn_stack_is_out_too_but_the_omission_is_not_why(self) -> None:
        """Recorded under its own name because the two are different claims.

        `brep_from_stl` is `__init__.py`'s last import, so even served it would
        stay unimported here: a search stops at the first hit, and a name that
        would walk past it falls through to the real `__init__`, which imports it
        anyway. Measured at +0.011 s against a 0.39 s spread. So this absence is
        an ordering consequence and not something the omission earned -- what the
        omission earned is in `test_the_search_order_cannot_change_what_a_name_
        means`, where serving it makes `build123d.copy` the wrong object.
        """
        after = _probe("structure", "lazy")["after_minimal_imports"]
        for library in LAST_IMPORT_STACK:
            with self.subTest(library=library):
                self.assertNotIn(library, after["top_level"])
        self.assertNotIn("build123d.brep_from_stl", after["build123d_submodules"])

    def test_the_same_imports_without_the_facade_load_all_of_it(self) -> None:
        """The positive control. Absence is evidence only where presence was
        reachable, and this is also the reproduction: it is what every authored
        build paid for before this slice."""
        after = _probe("structure", "plain")["after_minimal_imports"]
        for library in OMITTED_STACK + LAST_IMPORT_STACK:
            with self.subTest(library=library):
                self.assertIn(library, after["top_level"])
        self.assertLess(
            _probe("structure", "lazy")["after_minimal_imports"]["module_count"],
            after["module_count"],
            "the facade arm imports at least as many modules as the eager one, "
            "so whatever this file is measuring, it is not the deferral")

    def test_a_deferred_name_still_resolves_and_brings_its_library_with_it(self) -> None:
        """`import_dxf` is one of the seven public names only the omitted three
        can answer. Deferred is not removed: the fallback executes the real
        `__init__.py` and the candidate gets the function it asked for."""
        probe = _probe("deferred", "lazy")
        self.assertTrue(probe["callable"])
        self.assertEqual("build123d.import_dxf", probe["module_name"])
        self.assertNotIn("ezdxf", probe["before"]["top_level"])
        self.assertIn("ezdxf", probe["after"]["top_level"],
                      "asking for a name only ezdxf's submodule carries must "
                      "actually load ezdxf, or the fallback is not a fallback")


class TheFacadeIsTheSamePackageTest(unittest.TestCase):
    """Condition 2: semantic equivalence, not geometry-only.

    Byte-identical STL across sixty timed builds said nothing about `dir()`,
    which was wrong by 474 names in the draft this came from. So the comparison
    here is the whole observable surface of the module, taken by identical code
    in both arms, plus an object-identity sweep the facade cannot satisfy by
    having already given up.
    """

    def test_the_search_order_cannot_change_what_a_name_means(self) -> None:
        """The premise, over the whole namespace rather than over `__all__`.

        179 of the 474 names the package binds have more than one provider — 83
        of the 200 public ones among them — so "which submodule answers first"
        would be a live question if any two ever disagreed. None do, and the
        public names no served submodule carries are exactly the ones that live
        only in the omitted submodules.
        """
        premise = _probe("premise", "plain")
        self.assertEqual([], premise["wrong"],
                         "a name resolves to a different object depending on "
                         "which submodule the search reaches first, so the "
                         "search order now decides what a candidate's import "
                         "means")
        self.assertEqual(
            ["DotLength", "Export2D", "ExportDXF", "ExportSVG", "LineType",
             "detect_primitives", "import_dxf"],
            premise["unserved_public"])
        self.assertGreater(len(premise["servable"]), 400)

    def test_the_rebound_set_is_what_this_release_actually_rebinds(self) -> None:
        """`REBOUND` against the executed package, by identity.

        The facade declines the import system's parent binding for exactly these
        names, and it has to decide that without executing `__init__.py` -- so
        the list is pinned, like `SUBMODULES`, and this is the check that holds
        the pin to account. A release that rebound a third submodule would leave
        the facade answering that name with a module where the package answers
        with whatever it re-exported, and nothing at runtime could notice.

        Asked here rather than at L0 because `__init__.py` reaches `pack` through
        `from build123d.pack import *`: a syntax tree would have to emulate
        star-import semantics to answer, and an executed package does not.
        """
        premise = _probe("premise", "plain")
        self.assertEqual(["import_dxf", "pack"], premise["rebound"],
                         "build123d 0.11.1 rebinds these two submodule names and "
                         "no others, measured by identity in a process where "
                         "__init__.py has run")
        self.assertEqual(premise["rebound"], premise["pinned_rebound"])

    def test_every_name_the_facade_serves_is_the_object_the_package_binds(self) -> None:
        lazy = self._lazy()
        self.assertTrue(lazy["lazy_throughout"],
                        "the facade fell back to the real __init__ part-way "
                        "through the sweep, so the rest of it compared the "
                        "package with itself and could not have failed")
        self.assertEqual(len(_probe("premise", "plain")["servable"]),
                         lazy["served_lazily"])
        self.assertEqual([], lazy["identity_mismatches"])
        self.assertTrue(lazy["fallback_happened"],
                        "resolving a name only the omitted three carry must "
                        "execute the real __init__")

    def test_the_public_surface_is_identical(self) -> None:
        lazy, plain = self._lazy(), self._plain()
        for field in ("version", "all", "dir", "namespace", "doc", "name",
                      "loader", "spec_name", "file_is_the_packages_own",
                      "submodule_identity", "missing", "text_bbox", "type_name"):
            with self.subTest(field=field):
                self.assertEqual(plain[field], lazy[field])
        self.assertEqual(200, len(plain["all"]))
        self.assertEqual(485, len(plain["dir"]),
                         "the count the `dir()` defect was found against")

    def test_dir_on_its_own_is_still_the_whole_namespace(self) -> None:
        """The case the whole-surface comparison could not make, and the proof is
        a mutation that survived it.

        `dir()` is the one question a facade cannot answer lazily, and removing
        the forced import from `__dir__` is invisible to every other test here --
        each of them has already read `__version__` or resolved a fallback name,
        so the package is fully imported by the time `dir` is asked. Measured:
        `dir-loses-its-forced-import` SURVIVED `test_the_public_surface_is_
        identical` and is killed by this. The original defect returned 11 names.
        """
        lazy, plain = _probe("dironly", "lazy"), _probe("dironly", "plain")
        self.assertEqual(plain["dir"], lazy["dir"])
        self.assertEqual(485, plain["dir_len"])

    def test_the_modules_own_dir_hook_still_forces_the_import(self) -> None:
        """`__dir__` asked directly, which is the route `dir()` stopped taking.

        Measured when the `vars()` repair landed: `dir-loses-its-forced-import`
        SURVIVED the probe above, for the second time in this slice's history and
        for a new reason. CPython's `module_dir` fetches `__dict__` through
        ordinary attribute access *before* it looks for a `__dir__` inside it, so
        `dir()` now arrives at a package the namespace hook has already made
        real, and `__dir__`'s own forcing is answering a question already
        answered.

        Two routes still rest on it, which is why the implementation stayed and
        the fixture moved: a candidate calling `build123d.__dir__()`, which never
        touches `__dict__` -- this test -- and any interpreter whose `dir()`
        reads the namespace slot directly the way attribute lookup does. Without
        both hooks, `dir()` would be correct by one interpreter's internals,
        which is the shape of the defect that started this.
        """
        lazy, plain = _probe("dunderdironly", "lazy"), _probe("dunderdironly",
                                                              "plain")
        self.assertEqual(plain["dunder_dir"], lazy["dunder_dir"])
        self.assertEqual(485, plain["dunder_dir_len"],
                         "the count both `dir()` defects were found against")

    def test_importing_a_submodule_leaves_the_object_the_package_leaves(self) -> None:
        """The write side of the same boundary, and the third defect of its shape.

        `import build123d.pack` asks the package for nothing. The import system
        *binds* the submodule onto its parent with `setattr`, and a namespace
        write reaches `__getattr__` no more than a namespace read does -- so the
        facade kept the module where `__init__.py` leaves the function it
        re-exports, and `build123d.pack(shapes)` was `TypeError: 'module' object
        is not callable` through the boundary and worked without it. Two of the
        24 submodules are rebound that way and both are checked here.

        The `ezdxf` assertion is not decoration: declining a write is only a
        repair if the deferral survives it, and it would be easy to buy this by
        forcing the real `__init__` on any submodule import.
        """
        lazy, plain = _probe("submoduleimport", "lazy"), _probe("submoduleimport",
                                                                "plain")
        for field in ("pack_type", "pack_callable", "pack_qualname", "pack_home",
                      "import_dxf_type", "import_dxf_callable"):
            with self.subTest(field=field):
                self.assertEqual(plain[field], lazy[field])
        self.assertTrue(plain["pack_callable"],
                        "the package's own `pack` is callable, so a facade that "
                        "answers with the submodule is answering a different "
                        "question from the one the candidate asked")
        self.assertEqual("function", plain["pack_type"])
        self.assertFalse(lazy["ezdxf_after_pack"],
                         "importing one cheap submodule pulled in ezdxf, so the "
                         "write is being declined by forcing the real __init__ "
                         "rather than by letting the search answer")

    def test_vars_and_the_namespace_are_still_the_packages_own(self) -> None:
        """The same defect one route over, and the route `__dir__` cannot cover.

        `__getattr__` is consulted only about a lookup that *failed*, and
        `module.__dict__` never fails -- `types.ModuleType` answers it from a
        slot -- so `vars(build123d)` and `build123d.__dict__` walked straight
        past the facade without arming it: **9** names against the package's
        **485**, and `"Box" in vars(build123d)` **False** where build123d says
        True. Reproduced on this branch's own head before the repair. A candidate
        that reads a module namespace instead of asking it for a name, and every
        introspection tool that does the same, observed a different package
        without `__getattr__` being called once.

        Its own interpreter, and `vars()` first, for the reason `dironly` has
        one: every other question in this file forces the real `__init__` before
        it would get here, and a namespace read after that compares the package
        with itself.
        """
        lazy, plain = _probe("namespaceonly", "lazy"), _probe("namespaceonly",
                                                              "plain")
        self.assertEqual(485, len(plain["vars"]),
                         "the count both namespace defects were found against")
        self.assertEqual(plain["vars"], lazy["vars"])
        self.assertTrue(lazy["has_box"],
                        "`Box in vars(build123d)` is True for the package and "
                        "must be True through the facade, or a candidate can "
                        "see two different build123ds depending on how it asks")
        self.assertEqual(plain["dict_keys"], lazy["dict_keys"])
        self.assertEqual(lazy["vars"], lazy["dict_keys"])

    def test_the_namespace_hook_does_not_outlive_the_fallback(self) -> None:
        """What that hook costs, measured rather than promised.

        `__dict__` can only be intercepted on the module's *class*, so while the
        facade is still lazy `type(build123d)` is a `types.ModuleType` subclass
        and not `types.ModuleType` itself. That is the one observable this repair
        adds, it is why `_full()` puts the class back, and this test is what
        holds both halves: the difference exists while the facade is lazy, and
        nothing of it survives the question that makes the package real.
        """
        lazy, plain = _probe("namespaceonly", "lazy"), _probe("namespaceonly",
                                                              "plain")
        self.assertEqual("module", plain["type_before"])
        self.assertNotEqual(
            "module", lazy["type_before"],
            "the facade is serving a plain module class, so nothing is "
            "intercepting `vars()` and the test above is passing for a reason "
            "that is not the repair")
        self.assertEqual("module", lazy["type_after"])
        self.assertEqual(plain["type_after"], lazy["type_after"])

    def test_a_star_import_binds_the_same_names(self) -> None:
        """`from build123d import *` reads `__all__`, which starts with an
        underscore pair and goes straight to the real `__init__`. It buys the
        candidate nothing and it must cost it nothing either."""
        self.assertEqual(_probe("star", "plain")["star"],
                         _probe("star", "lazy")["star"])

    def test_a_solid_still_pickles_when_only_a_submodule_was_imported(self) -> None:
        """`modify_copyreg()` is `__init__.py`'s one side effect beyond its
        imports, and `import build123d.objects_part` is the route that never
        touches an attribute of the package. Arming it on `__path__` is what
        covers that route; without it this is the test that goes red."""
        lazy, plain = _probe("pickle", "lazy"), _probe("pickle", "plain")
        self.assertEqual(plain["volume"], lazy["volume"])
        self.assertEqual(plain["round_trip_volume"], lazy["round_trip_volume"])
        self.assertEqual(lazy["volume"], lazy["round_trip_volume"])
        self.assertTrue(lazy["copyreg_armed"])

    def test_the_docstring_is_right_before_anything_forces_the_import(self) -> None:
        """The dunder that cannot be deferred, so it is not deferred.

        `module_from_spec` seeds `__doc__` with `None`, and popping the key sends
        the lookup to `types.ModuleType.__doc__` -- the *type's* docstring --
        rather than to `__getattr__`. So the facade reads it off the code object
        at install time. This test is what says so: read `build123d.__doc__`
        first, before any name has forced the fallback, and it must already be
        the package's own.
        """
        self.assertEqual("build123d import definitions",
                         self._plain()["doc_on_first_read"])
        self.assertEqual(self._plain()["doc_on_first_read"],
                         self._lazy()["doc_on_first_read"])

    def _plain(self) -> dict:
        return _probe("semantics", "plain")

    def _lazy(self) -> dict:
        return _probe("semantics", "lazy",
                      json.dumps(_probe("premise", "plain")["servable"]))


class TheOptimizationFailsOpenOnAnUnprovenReleaseTest(unittest.TestCase):
    """Condition 1, and the compromise the whole slice rests on.

    The facade is a repo-owned object sitting in `sys.modules` under a
    third-party name, and its search order is a fact about `build123d 0.11.1`
    verified name by name. A release that *moves* a name is safe -- the search
    misses and the real `__init__` runs. A release that puts a *different* object
    under an existing name in an earlier-searched module would mis-bind
    silently, and nothing at runtime can see that happen.

    So the optimization is switched on only for releases actually swept, and
    `pyproject.toml` keeps `build123d>=0.9` untouched: narrowing the dependency
    range to preserve a speedup would be paying for it with the ability to
    install. What an unproven release gets is ordinary build123d, and "ordinary"
    is asserted against the arm that never installed a facade at all.
    """

    def test_an_unswept_release_gets_ordinary_build123d(self) -> None:
        fake, plain = _probe("semantics", "fake"), _probe("semantics", "plain")
        for field in ("version", "all", "dir", "namespace", "doc",
                      "doc_on_first_read", "name", "loader", "spec_name",
                      "file_is_the_packages_own", "submodule_identity",
                      "missing", "text_bbox", "type_name"):
            with self.subTest(field=field):
                self.assertEqual(plain[field], fake[field])

    def test_an_unswept_release_defers_nothing_at_all(self) -> None:
        """Not merely equivalent: the same work. The fallback executes the real
        `__init__.py`, so every library the eager package loads is loaded."""
        fake = _probe("structure", "fake")["after_minimal_imports"]
        for library in OMITTED_STACK + LAST_IMPORT_STACK:
            with self.subTest(library=library):
                self.assertIn(
                    library, fake["top_level"],
                    "an unproven build123d is being served lazily, so the "
                    "version guard is not deciding anything and the facade's "
                    "search order is being applied to a release nobody swept")

    def test_the_same_probe_on_the_proven_release_does_defer(self) -> None:
        """The control that stops the two tests above from passing vacuously: if
        the facade never worked, an unproven release would look identical to a
        proven one and both would be green."""
        lazy = _probe("structure", "lazy")["after_minimal_imports"]
        self.assertEqual([], [lib for lib in OMITTED_STACK + LAST_IMPORT_STACK
                              if lib in lazy["top_level"]])


if __name__ == "__main__":
    unittest.main()
