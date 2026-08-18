#!/usr/bin/env python3
"""The witness's renderer calls have to be callable.

**This proves the render calls can execute, because it fails when a call passes
a keyword the target does not accept.** That is not a hypothetical `Y`: it is
the state this file was written against. `witness.generate` called
`preview.render_multi_view(..., resolution=MAX_RESOLUTION_PX)` while the
signature was `(tm, output_path, title, subtitle, view_size)` with no catch-all,
so every invocation raised `TypeError`. The `except Exception` around it is
deliberate -- a genuinely missing renderer should be a reported state rather
than a crash -- so the failure was recorded as `renderer="unavailable: ..."`,
nothing crashed, and the witness directory was empty on every run the module
ever made.

That is the shape §3b of the review workflow names: an instrument that reports a
state while asking a different question from the claim resting on it. The
receipt said "renderer unavailable", which a reader takes as *this machine has
no renderer* -- when what was true is *this call cannot be made*.

Checked statically, by reading both source files, for two reasons. Importing
`preview` drags the plotting stack into the commit gate, which the 5 s ceiling
in `conftest.py` should not have to pay; and a signature mismatch is a fact
about the source, so the cheaper instrument is also the more direct one. The
consequence is that this test still fails on a machine with no renderer
installed at all, which a call-it-and-see test could not distinguish.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
WITNESS = HERE / "witness.py"
PREVIEW = HERE.parent / "preview.py"

# module attribute -> the file that defines the function
CALLS = {"preview": PREVIEW}

RENDER = PREVIEW.parent / "designer_toolkit" / "render.py"

# Every render call the witness makes, and the parameter that decides how many
# pixels it produces. `witness.generate` publishes `resolution_px:
# MAX_RESOLUTION_PX` as the budget for the whole set, so each of these has to
# actually be rendered at it -- by an explicit keyword or by the target's own
# default, either is fine, and disagreeing is not.
BUDGETED = {
    "render_multi_view": ("view_size", PREVIEW),
    "section_render": ("tile", RENDER),
}


def _signatures(path: Path) -> dict[str, ast.arguments]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.name: node.args
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _accepted(args: ast.arguments) -> tuple[set[str], bool]:
    names = {a.arg for a in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)}
    return names, args.kwarg is not None


def _keyword_calls(path: Path, module: str) -> list[tuple[str, list[str], int]]:
    """Every `module.func(..., kw=...)` call in `path`, with its keywords."""
    out = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute)
                and isinstance(fn.value, ast.Name)
                and fn.value.id == module):
            continue
        kws = [k.arg for k in node.keywords if k.arg is not None]
        out.append((fn.attr, kws, node.lineno))
    return out


def _module_ints(path: Path) -> dict[str, int]:
    """Module-level `NAME = <int>` assignments, for resolving a default."""
    out: dict[str, int] = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if not isinstance(node, ast.Assign):
            continue
        if not (len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)):
            continue
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, int):
            out[node.targets[0].id] = value.value
    return out


def _calls_named(path: Path, func: str) -> list[ast.Call]:
    """Calls to `func`, whether spelled bare or as `module.func`.

    `section_render` is imported into the function body and called bare, while
    `render_multi_view` is reached through `preview.`, so matching only one shape
    would silently skip a call -- which is the failure this file exists to stop.
    """
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if (isinstance(fn, ast.Name) and fn.id == func) or \
           (isinstance(fn, ast.Attribute) and fn.attr == func):
            found.append(node)
    return found


def _default_of(defining_file: Path, func: str, param: str) -> int | None:
    """The declared default for one parameter, resolved through a constant."""
    for node in ast.parse(defining_file.read_text(encoding="utf-8")).body:
        if not (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == func):
            continue
        args = node.args
        pairs = list(zip(args.kwonlyargs, args.kw_defaults))
        positional = list(args.posonlyargs) + list(args.args)
        if args.defaults:
            pairs += list(zip(positional[-len(args.defaults):], args.defaults))
        for arg, default in pairs:
            if arg.arg != param or default is None:
                continue
            if isinstance(default, ast.Constant) and isinstance(default.value, int):
                return default.value
            if isinstance(default, ast.Name):
                return _module_ints(defining_file).get(default.id)
    return None


class TheWitnessRendersAtTheBudgetItPublishesTest(unittest.TestCase):
    """**This proves each render call produces the advertised pixel count,
    because it fails when a call takes a default that disagrees with it.**

    Not hypothetical either. Repairing the `resolution=`/`view_size=` keyword
    made the render path reachable for the first time, and a reachable path
    rendered a section at `section_render`'s own `tile=640` default while
    `generate` publishes `resolution_px: 512` in the receipt beside it. The first
    repair did not cause that; it revealed it, which is what happens when a
    branch nothing executed starts executing.

    Checked as a property rather than as a spelling: an explicit keyword bound to
    `MAX_RESOLUTION_PX` passes, and so does a target whose own default already
    equals it. What fails is a rendered size nobody can trace to the published
    budget.
    """

    def test_the_budget_is_a_number_this_test_can_read(self) -> None:
        self.assertIsInstance(_module_ints(WITNESS).get("MAX_RESOLUTION_PX"), int,
                              "MAX_RESOLUTION_PX is the budget every assertion "
                              "below rests on; if it stops being a plain int "
                              "this test is passing vacuously")

    def test_every_render_call_is_made_at_the_published_budget(self) -> None:
        budget = _module_ints(WITNESS)["MAX_RESOLUTION_PX"]
        for func, (param, defining_file) in BUDGETED.items():
            calls = _calls_named(WITNESS, func)
            self.assertTrue(calls,
                            f"no call to {func} found in {WITNESS.name}; if the "
                            "render moved, move this test with it rather than "
                            "letting it pass vacuously")
            for call in calls:
                passed = {k.arg: k.value for k in call.keywords if k.arg}
                if param in passed:
                    value = passed[param]
                    self.assertTrue(
                        isinstance(value, ast.Name)
                        and value.id == "MAX_RESOLUTION_PX",
                        f"{WITNESS.name}:{call.lineno} passes {param}= to {func} "
                        "as something other than MAX_RESOLUTION_PX, so the "
                        "receipt's published budget and the rendered size are "
                        "two independent numbers")
                    continue
                default = _default_of(defining_file, func, param)
                self.assertEqual(
                    budget, default,
                    f"{WITNESS.name}:{call.lineno} calls {func} without {param}=, "
                    f"so it renders at {defining_file.name}'s default of "
                    f"{default} while generate() publishes resolution_px "
                    f"{budget}. Pass {param}=MAX_RESOLUTION_PX, or the budget in "
                    "the receipt describes nothing")


class TheWitnessRenderCallsAreCallableTest(unittest.TestCase):
    def test_every_keyword_the_witness_passes_is_one_the_target_accepts(self) -> None:
        for module, defining_file in CALLS.items():
            sigs = _signatures(defining_file)
            calls = _keyword_calls(WITNESS, module)
            self.assertTrue(calls,
                            f"no `{module}.*(...)` keyword call found in "
                            f"{WITNESS.name}; if the call moved, move this test "
                            "with it rather than letting it pass vacuously")
            for func, keywords, lineno in calls:
                self.assertIn(func, sigs,
                              f"{WITNESS.name}:{lineno} calls {module}.{func}, "
                              f"which {defining_file.name} does not define")
                names, takes_kwargs = _accepted(sigs[func])
                if takes_kwargs:
                    continue
                unknown = [k for k in keywords if k not in names]
                self.assertEqual(
                    [], unknown,
                    f"{WITNESS.name}:{lineno} passes {unknown} to "
                    f"{module}.{func}, which accepts {sorted(names)} and has no "
                    "**kwargs. Every call raises TypeError, and the except "
                    "around it records that as renderer=\"unavailable\" -- so "
                    "the witness never renders and the receipt blames the "
                    "machine")


if __name__ == "__main__":
    unittest.main()
