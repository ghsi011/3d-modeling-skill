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
