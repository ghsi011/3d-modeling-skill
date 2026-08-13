#!/usr/bin/env python3
"""L0-heavy -- the consequence the commit gate can only assert structurally.

`skills/3d-modeling/scripts/pipeline/test_import_cost.py` proves no module on the
CLI's import graph names the mesh stack at module level. That is the *causal
property*, and it is all L0 can honestly check: the instrument for "did the import
actually happen" is a fresh interpreter, and `conftest.py` permits `git` and
nothing else, because a child interpreter is the ~1.6 s mechanism tiering exists to
keep out of the commit gate.

Here a spawn is allowed, so the claim is checked directly: import `pipeline.cli` in
a clean interpreter and ask whether `trimesh` is in `sys.modules`.

**Why both tiers and not just this one.** A structural test fails on the pull
request that reintroduces the import, naming the file; this one fails later and
says only that something on a 28-module graph did it. Neither replaces the other,
and the structural one is the one that runs on every commit.

**Why both directions.** A test that only asserts absence passes just as well if
the CLI stopped working entirely, or if the import moved somewhere this file never
looks. So the second test is the positive control: a real measurement still loads
the library, in the same kind of fresh interpreter, which is also what proves the
function-local imports actually resolve rather than merely lint.
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "skills" / "3d-modeling" / "scripts"

# Measured warm on 22c3b29, three readings each, same session:
#   before  cli 1546-1569 ms, trimesh 1320-1336 ms of it (85%)
#   after   cli  257- 263 ms, trimesh not imported at all
# So a command that never touches geometry stopped waiting about 1.28 s.
_PROBE = """
import sys
sys.path.insert(0, {scripts!r})
import pipeline.cli
print("trimesh" in sys.modules)
"""

# Every function that received a deferred import is called here, in one fresh
# interpreter. That list is not decoration: `disc_area` is executed **zero** times
# by the entire L0 gate -- `test_pipeline.py:3126` replaces it with a stub -- so
# without this line its deferred import is unproven, and an import moved into the
# wrong function is a crash that waits for a real job to find it.
_MEASURE = """
import sys
sys.path.insert(0, {scripts!r})
import pipeline.analysis as A
import trimesh
box = trimesh.creation.box(extents=(10.0, 8.0, 4.0))
ctx = A.MeshAnalysisContext(path=None, raw=box, normalized=box, load_count=1,
                            repair_actions=())
print(round(ctx.section_area(0.0), 3))                      # _slab_area, _intersect
print(round(ctx.window_area(z=0.0, at=(0.0, 0.0), size=(4.0, 4.0)), 3))
print(round(ctx.disc_area(z=0.0, at=(0.0, 0.0), diameter=4.0), 3))
print(len(ctx.axis_profile(0, 2)))                          # _axis_area
"""

# A bore needs a hole to measure, so it gets its own body rather than distorting
# the closed forms above.
_BORE = """
import sys
sys.path.insert(0, {scripts!r})
import pipeline.analysis as A
import trimesh
plate = trimesh.creation.box(extents=(20.0, 20.0, 4.0))
pin = trimesh.creation.cylinder(radius=3.0, height=20.0, sections=192)
holed = trimesh.boolean.difference([plate, pin], engine="manifold")
ctx = A.MeshAnalysisContext(path=None, raw=holed, normalized=holed, load_count=1,
                            repair_actions=())
print(round(ctx.section_bore_diameter_mm(z=0.0, at=(0.0, 0.0)), 2))
"""


def _fresh(source: str) -> subprocess.CompletedProcess:
    """A clean interpreter, so `sys.modules` means what it says.

    `-S` is deliberately not used: the project's own dependencies live in the
    environment this test is running in, and the point is to reproduce a real
    command's import graph rather than an artificially bare one.
    """
    return subprocess.run(
        [sys.executable, "-c", source.format(scripts=str(SCRIPTS))],
        capture_output=True, text=True, cwd=str(REPO), timeout=300,
    )


class TheCommandLineDoesNotLoadTheMeshStackTest(unittest.TestCase):

    def test_importing_the_cli_leaves_trimesh_unimported(self) -> None:
        done = _fresh(_PROBE)
        self.assertEqual(0, done.returncode,
                         f"the probe itself failed:\n{done.stderr}")
        self.assertEqual(
            "False", done.stdout.strip(),
            "importing pipeline.cli loaded trimesh. Every command that does no "
            "geometry -- doctor, status, init, route -- now waits about 1.3 s for "
            "a library it never calls.")

    def test_every_deferred_import_still_resolves_when_it_is_needed(self) -> None:
        """The control. Absence is only evidence if presence is still reachable.

        Expectations are closed form, so they disagree with the code rather than
        record it: a 10x8x4 box sliced at mid-height is the full 80 mm^2 rectangle;
        a 4x4 window on it is 16 mm^2; a disc of diameter 4 is pi*r^2 = 12.566 mm^2.
        """
        done = _fresh(_MEASURE)
        self.assertEqual(0, done.returncode,
                         "a function-local import that does not resolve is a "
                         f"deferred crash, not a deferred cost:\n{done.stderr}")
        section, window, disc, profile = done.stdout.split()
        self.assertAlmostEqual(80.0, float(section), places=1)
        self.assertAlmostEqual(16.0, float(window), places=1)
        self.assertAlmostEqual(12.566, float(disc), places=1)
        self.assertEqual(2, int(profile))

    def test_the_bore_probe_still_resolves_its_import(self) -> None:
        """`section_bore_diameter_mm` is the numpy one, and it needs a real hole.

        A 6 mm drilled bore measured off the section boundary, so the expectation
        is the drill, not the measurement. The tessellated cylinder inscribes
        slightly under nominal, which is why this is a band rather than a point.
        """
        done = _fresh(_BORE)
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertAlmostEqual(6.0, float(done.stdout.strip()), delta=0.05)


if __name__ == "__main__":
    unittest.main()
