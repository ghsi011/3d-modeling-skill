#!/usr/bin/env python3
"""`measurement: KeyError: 0` told a designer nothing, six times in one run.

The measurement block wraps four steps -- mesh load, commission, screening,
witness -- and wrapping the lot is deliberate: a part that cannot be measured is
a finding, and findings get written down rather than ending the run in a
traceback. What was missing is *which* step, so the failure reached the designer
as the bare exception:

    design-tool: measurement: KeyError: 0
    design-tool: measurement: TypeError: list indices must be integers or slices, not str
    design-tool: measurement: TypeError: 'float' object is not subscriptable

No step, no file, nothing to act on. One agent spent six invocations against
messages of that shape -- roughly twenty-five minutes of reasoning -- because
each answer said only that something had gone wrong somewhere.

The counter-example lives in the same transcripts and is what these should look
like: *"BudgetExceeded: W1: 15 sections exceeds the 12 budget. Raise the level or
declare fewer heights"* -- the limit, and the move.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from . import bindings as B
from . import runner
from .test_pipeline import _request


class TheFailureNamesItsStepTest(unittest.TestCase):
    """The step is read off `timings`: each records itself only on success, so
    the first one missing is the one that raised."""

    def test_each_step_is_named_by_the_timings_recorded_before_it(self) -> None:
        done: dict[str, float] = {}
        for expected in runner._MEASUREMENT_STEPS:
            with self.subTest(step=expected):
                said = runner._measurement_failure(ValueError("x"), dict(done))
                self.assertTrue(said.startswith(f"{expected} raised"), said)
            done[expected] = 0.1

    def test_the_exception_itself_is_still_reported_verbatim(self) -> None:
        """Naming the step adds to the message; it must not swallow the only
        fact the reader had before."""
        said = runner._measurement_failure(KeyError(0), {"mesh_load": 0.01})
        self.assertIn("KeyError", said)
        self.assertIn("0", said)

    def test_an_unrecognised_state_still_names_a_step(self) -> None:
        """Every timing present and something still raised: the message must not
        fall through to naming nothing."""
        said = runner._measurement_failure(ValueError("x"), {
            name: 0.1 for name in runner._MEASUREMENT_STEPS})
        self.assertTrue(said.startswith("witness raised"), said)


class AShapeErrorSaysWhereToLookTest(unittest.TestCase):
    """The class of failure that actually cost the six invocations."""

    def test_a_shape_error_names_the_file_carrying_the_declarations(self) -> None:
        said = runner._measurement_failure(
            TypeError("list indices must be integers or slices, not str"),
            {"mesh_load": 0.01})
        self.assertIn(B.MODEL_CONTRACT_FILE, said)

    def test_every_shape_error_is_covered(self) -> None:
        for exc in (TypeError("t"), KeyError(0), IndexError("i"),
                    AttributeError("a")):
            with self.subTest(exc=type(exc).__name__):
                said = runner._measurement_failure(exc, {"mesh_load": 0.01})
                self.assertIn(B.MODEL_CONTRACT_FILE, said)

    def test_a_measurement_error_is_not_blamed_on_a_declaration(self) -> None:
        """A `ValueError` from a boolean engine that refused a mesh is a fact
        about the part. Pointing it at the contract would be the D38 mistake in
        the other direction -- a confident sentence aimed at the wrong file."""
        said = runner._measurement_failure(
            ValueError("Not all meshes are volumes!"), {"mesh_load": 0.01})
        self.assertNotIn(B.MODEL_CONTRACT_FILE, said)
        self.assertIn("commission raised", said)

    def test_it_does_not_assert_whose_fault_it_is(self) -> None:
        """A TypeError in a measurement step can be a bad declaration or a bug in
        the step. The message points; it must not accuse."""
        said = runner._measurement_failure(TypeError("t"), {"mesh_load": 0.01})
        self.assertIn("usually", said)


class TheRunnerActuallyUsesItTest(unittest.TestCase):
    """**The row the others were missing.**

    Every test above exercises `_measurement_failure` directly, so all of them
    stay green if the call site goes back to `f"{type(exc).__name__}: {exc}"` --
    which is exactly what the mutation showed. A helper nothing calls is not a
    fix, and a suite that cannot see the difference is not evidence.

    So this one drives the real `runner.run` with a measurement step made to
    raise, and reads the message off the `JobResult`.
    """

    def test_a_real_run_reports_the_step_and_not_the_bare_exception(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            with mock.patch.object(runner.commission, "run",
                                   side_effect=KeyError(0)):
                result = runner.run(_request(out))

        self.assertFalse(result.ok)
        self.assertEqual("measurement", result.stage)
        self.assertIn("commission raised", result.message,
                      "the runner is not using _measurement_failure")
        self.assertIn("KeyError", result.message)
        self.assertIn(B.MODEL_CONTRACT_FILE, result.message)

    def test_a_real_run_still_writes_the_receipt_for_a_failed_measurement(self) -> None:
        """The wrapping exists so an unmeasurable part is a finding rather than a
        traceback. Naming the step must not cost that."""
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            with mock.patch.object(runner.commission, "run",
                                   side_effect=KeyError(0)):
                result = runner.run(_request(out))
            self.assertTrue((out / B.PIPELINE_RECEIPT).is_file())
        self.assertIn("artifact_manifest", result.artifacts)


if __name__ == "__main__":
    unittest.main()
