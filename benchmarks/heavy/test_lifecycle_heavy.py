#!/usr/bin/env python3
"""L0-heavy — restart on the lane that has a review round trip.

The commit-gate half of this slice
(`skills/3d-modeling/scripts/pipeline/test_lifecycle.py`) restarts a *certified*
job, which builds in this process. That covers the discard and the rebuild and
it cannot cover the case restart exists for, because a certified job in that
fixture answers no review: the sharpest thing `--restart` does is throw away a
review answer whose bindings all still hold, which is precisely what scoped
invalidation will never do and precisely what somebody asks for when they no
longer trust the answer.

Reaching that means an authored job carried to `VERIFIED` through the confined
build boundary, and the boundary is a child interpreter, which the root
`conftest.py` refuses inside the gate. So it runs here.
"""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from pipeline import bindings as B
from pipeline import cli
from pipeline import lifecycle as LC

# The authored fixture the bindings slice already built: a project laid out, a
# model and proposal authored, a verification round trip answered from the
# packet's own envelope, and a stored VERIFIED at the end. Imported rather than
# copied -- two spellings of one fixture is how two tiers stop testing the same
# thing.
from pipeline.test_bindings import (  # noqa: E402
    _answer,
    _read,
    _status,
    _verified,
)


class RestartDiscardsATrustedAnswerTest(unittest.TestCase):
    """The one case resume cannot reach, because nothing about it is stale."""

    def test_a_review_answer_whose_bindings_hold_is_discarded_and_asked_again(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _verified(Path(raw))
            answer = directory / cli.REVIEW_DIR / "verification_response.json"
            self.assertEqual({}, _status(directory)["stale"],
                             "nothing has moved: a resume would reuse every one "
                             "of these receipts, correctly")

            with contextlib.redirect_stderr(io.StringIO()):
                exit_code = cli.run([str(directory), "--restart", "--no-render"])

            # The run got as far as needing the verification it no longer has.
            self.assertEqual(cli.NEEDS_ACTION, exit_code)
            self.assertFalse(answer.is_file())
            self.assertEqual("REVIEW",
                             _read(directory / cli.NEXT_ACTION_FILE)["kind"])
            self.assertEqual("NOT_RUN", _status(directory)["final_status"])

            event = [e for e in LC.read(directory) if e["event"] == "RESTART"][0]
            self.assertEqual("VERIFIED", event["discarded_status"])
            self.assertIn("reviews/verification_response.json", event["discarded"])

            # Answering the fresh packet finishes the job again, from the model
            # and the frozen contract the restart kept.
            _answer(directory)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(0, cli.run([str(directory), "--no-render"]))
            self.assertEqual("VERIFIED", _status(directory)["stored_status"])

    def test_the_run_identity_of_an_unchanged_authored_job_does_not_move(self) -> None:
        """Byte-identical reruns are the constraint the identity decision keeps."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _verified(Path(raw))
            before = _status(directory)["run_id"]
            with contextlib.redirect_stderr(io.StringIO()):
                cli.run([str(directory), "--no-render"])
            self.assertEqual(before, _status(directory)["run_id"])
            self.assertEqual(before, B.run_id(directory, model_name="model.py"))

    def test_restarting_one_formulation_leaves_its_sibling_verified(self) -> None:
        """13.5, through the command surface rather than over hand-written files."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _verified(Path(raw))
            root = json.loads(
                (directory / "final_status.json").read_text(encoding="utf-8"))

            with contextlib.redirect_stderr(io.StringIO()):
                cli.branch([str(directory), "--from", ".", "--id", "sibling",
                            "--reason", "a second formulation of the same job"])
                cli.run([str(directory), "--restart", "--no-render"])

            self.assertEqual(
                root,
                json.loads((directory / "final_status.json").read_text(
                    encoding="utf-8")),
                "the restart applied to the active formulation, which is the "
                "branch; the root's own conclusion is not the branch's to discard")


if __name__ == "__main__":
    unittest.main()
