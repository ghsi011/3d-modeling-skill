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
import json, pickle, sys
sys.path.insert(0, __SCRIPTS__)

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
            lazy_throughout &= "__getattr__" in build123d.__dict__
            kept[name] = getattr(build123d, name)
        out["served_lazily"] = len(kept)
        out["lazy_throughout"] = lazy_throughout
        # One name that only an omitted submodule can answer. It must force the
        # real `__init__` and it must bring `ezdxf` with it.
        out["fallback_forced_by"] = "ExportSVG"
        kept["ExportSVG"] = build123d.ExportSVG
        out["fallback_happened"] = "__getattr__" not in build123d.__dict__
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
    from pipeline.lazy_build123d import SEARCH
    import build123d
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

        83 of the 200 public names are re-exported by more than one submodule, so
        "which submodule answers first" would be a live question if any two ever
        disagreed. None do -- and the public names no served submodule carries
        are exactly the ones that live only in the omitted submodules.
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
                      "submodule_identity", "missing", "text_bbox"):
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
                      "missing", "text_bbox"):
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
