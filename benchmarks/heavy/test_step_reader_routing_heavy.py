#!/usr/bin/env python3
"""L0-heavy -- a STEP handed to the loaders has to be read, not dispatched to cascadio.

**This proves STEP reaches the analysis and toolkit paths, because both fail when
the loader hands STEP to `trimesh.load`.** That is not hypothetical: it is the
state this file was written against, and the failure was silent in the way that
costs most.

`mesh_io.read_step` exists precisely because `trimesh.load` dispatches STEP to
`cascadio`, which this repository deliberately does not carry — its own docstring
records the measurement, on `vent_mount.step`: cascadio returns the part in
**metres** where the kernel path returns millimetres, the silent unit
substitution ARCHITECTURE.md section 12 forbids. So the dispatch could only fail,
and it did, with `Failed to load STL: No module named 'cascadio'`.

What that cost on a real MODIFY run:

* `cli._inherited_overhang` swallowed the failure into `unmeasured` and returned
  `None`, so the inherited-overhang ceiling stayed at the generated 0.0 and the
  candidate was charged for the **54.792 mm²** of downward area it inherited from
  the very part it was told to preserve;
* `commission._preservation_samples` raised through it, which disables the
  preservation audit entirely whenever `minimum_detectable_defect_mm` is declared
  on a STEP source — coverage drops and the job fails a gate for a reason with
  nothing to do with the candidate. On the MODIFY lane, whose whole subject is
  preservation, that is the one gate that had to work.

Two entry points needed the branch, not one. `designer_toolkit._bootstrap.as_mesh`
routes every toolkit call through `load_mesh`, so `overhang_area` still died on
cascadio after `load_mesh_raw` alone was fixed. `as_mesh`'s own docstring says it
exists so "fit/metrics/render cannot drift apart on which side of that choice
they take" — and a STEP readable by one loader and not the other is exactly that
drift.

Uses a STEP written by this runtime's own kernel rather than the external
GPL-3.0 fixture source, so the test carries no licence obligation and runs on a
bare checkout.

Heavy tier, and the repository's own guard is what put it here: at L0 it measured
5.1 s against the 5 s ceiling and `conftest.py` said exactly why -- "It starts no
process, so it is doing the expensive work itself ... a B-rep read". It reads
B-rep four times, so this is its tier rather than a ceiling to argue with.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parents[1] / "skills" / "3d-modeling" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

BOX = (12.0, 8.0, 4.0)          # mm, and deliberately not a cube: a cube cannot
                                # show a transposed or scaled axis.


def _write_step(dest: Path) -> Path:
    from build123d import Box, export_step
    export_step(Box(*BOX), str(dest))
    return dest


class AStepFileIsReadableByEveryLoaderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.step = _write_step(Path(cls._tmp.name) / "probe.step")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_load_mesh_raw_reads_a_step(self) -> None:
        import mesh_io
        mesh, _ = mesh_io.load_mesh_raw(self.step)
        self.assertGreater(len(mesh.faces), 0)

    def test_load_mesh_reads_a_step(self) -> None:
        """The entry point `as_mesh` sends the whole toolkit through."""
        import mesh_io
        self.assertGreater(len(mesh_io.load_mesh(self.step).faces), 0)

    def test_the_analysis_path_reads_a_step(self) -> None:
        from pipeline import analysis
        self.assertGreater(len(analysis.load(self.step).normalized.faces), 0)

    def test_the_toolkit_metric_reads_a_step(self) -> None:
        """`overhang_area` is the one `cli._inherited_overhang` calls."""
        from designer_toolkit import metrics
        area = metrics.overhang_area(str(self.step))
        self.assertIsInstance(area, float)

    def test_a_readable_step_yields_a_preservation_sample_count(self) -> None:
        """The audit the old behaviour silently disabled.

        This is the other half of `test_phase3`'s
        `test_a_source_whose_area_cannot_be_read_is_a_finding_not_a_crash`. That
        row keeps the cheap property -- an unreadable source refuses -- and this
        one keeps the property that needs a real B-rep read, because deriving a
        sample count from a STEP's surface area costs 11.72 s against a 5 s
        commit gate.

        It matters because `minimum_detectable_defect_mm` on a STEP source used
        to disable the preservation audit outright: coverage fell and the job
        failed a gate for a reason unrelated to the candidate, on the one lane
        whose whole subject is preservation.
        """
        from pipeline import commission
        count = commission._preservation_samples(
            {"minimum_detectable_defect_mm": 0.3}, self.step)
        self.assertIsInstance(count, int)
        self.assertGreater(count, 0)

    def test_it_is_read_in_millimetres_and_not_metres(self) -> None:
        """The reason cascadio is refused, asserted rather than trusted.

        A metre-scaled read would give 0.012 x 0.008 x 0.004 and every downstream
        tolerance would pass vacuously, which is worse than failing.
        """
        import mesh_io
        mesh = mesh_io.load_mesh(self.step)
        size = mesh.bounds[1] - mesh.bounds[0]
        for got, want, axis in zip(sorted(size), sorted(BOX), "xyz"):
            self.assertAlmostEqual(want, got, places=3,
                                   msg=f"{axis} read as {got}, expected {want} mm; "
                                       "a 1000x error here is the unit substitution "
                                       "section 12 forbids")


if __name__ == "__main__":
    unittest.main()
