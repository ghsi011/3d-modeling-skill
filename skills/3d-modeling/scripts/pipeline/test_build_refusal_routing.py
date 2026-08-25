#!/usr/bin/env python3
"""A build refusal goes to whoever can act on it.

`BuildRefused` covers three situations that need three different readers, and
every one of them used to produce the same instruction: *`project.json` is not
complete enough to build*, `kind: FIX_PROJECT`. A degenerate direction vector in
`model.py` and a sandbox that would not start were reported identically, and both
sent the reader to a `project.json` that was frequently already complete.

**The repair is classification, not relabelling.** The cause is decided where the
refusal is raised -- `isolation.py` knows whether it is refusing the model, the
job, or its own boundary -- and mapped here onto the four `next_action` kinds
that already exist. There is no fifth kind: `docs/tooling.md` names four, and a
consumer routing on them should not have to learn a new one to be told that the
geometry raised.

| cause | instruction |
|---|---|
| `MODEL` | `AGENT_COMMISSION`, role designer, `candidate_build` -- the geometry is the designer's |
| `PROJECT` | `FIX_PROJECT` -- the job as declared is wrong |
| `SYSTEM` | `BLOCKED` -- the boundary failed and nothing an agent writes lifts it |

Measured cost of getting this wrong: of 71 reads of pipeline **source** by
designers and print engineers, **50.7% happened immediately after a refusal** and
**0% after a clean run**. Nobody reads `commission.py` out of curiosity; they read
it because the refusal did not say what was needed. An agent turn is ~10.9 s of
reasoning, so an unactionable refusal is expensive in exactly the way a
four-second tool call is not.
"""
from __future__ import annotations

import unittest

from . import cli
from . import isolation as ISO


class TheCauseIsCarriedNotParsedTest(unittest.TestCase):
    """The classification lives with the raise, not in a string match here."""

    def test_a_refusal_defaults_to_the_model(self) -> None:
        """An unclassified refusal is more safely handed to the person who wrote
        the geometry than declared an infrastructure fault nobody will look at."""
        self.assertEqual(ISO.CAUSE_MODEL, ISO.BuildRefused("anything").cause)

    def test_each_cause_survives_being_raised_and_caught(self) -> None:
        for cause in (ISO.CAUSE_MODEL, ISO.CAUSE_PROJECT, ISO.CAUSE_SYSTEM):
            with self.subTest(cause=cause):
                try:
                    raise ISO.BuildRefused("x", cause=cause)
                except ISO.BuildRefused as exc:
                    self.assertEqual(cause, exc.cause)
                    self.assertIn("x", str(exc))


class EachCauseReachesADifferentReaderTest(unittest.TestCase):
    """Routing, asserted through the instruction a reader is actually handed.

    The point of the slice is that three situations stop producing one
    instruction, so the rows that matter are the ones that read `kind` back off
    `next_action.json` after a real refusal.
    """

    @staticmethod
    def _instruction(cause: str) -> dict:
        import json
        import tempfile
        from pathlib import Path
        from . import project as P
        from .test_bindings import _laid_out

        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            project = P.load(directory)
            cli._report_build_refusal(
                directory, directory, project,
                ISO.BuildRefused("gp_Dir2d() - input vector has zero norm",
                                 cause=cause),
                Path("model.py"))
            return json.loads(
                (directory / cli.NEXT_ACTION_FILE).read_text(encoding="utf-8"))

    def test_a_model_failure_asks_the_designer_for_geometry(self) -> None:
        """`AGENT_COMMISSION`, not `FIX_PROJECT`: the geometry is the designer's
        and `project.json` may be perfectly complete."""
        d = self._instruction(ISO.CAUSE_MODEL)
        self.assertEqual("AGENT_COMMISSION", d["kind"])
        self.assertEqual("designer", d["role"])
        self.assertEqual("candidate_build", d["stage"])
        self.assertIn("model.py", d["reason"])
        self.assertIn("zero norm", d["reason"])

    def test_a_project_deficiency_still_says_fix_the_project(self) -> None:
        d = self._instruction(ISO.CAUSE_PROJECT)
        self.assertEqual("FIX_PROJECT", d["kind"])

    def test_a_boundary_failure_is_not_a_designer_dispatch(self) -> None:
        """Nobody's geometry is at fault and no edit to the project lifts it, so
        it must not ask a designer for anything."""
        d = self._instruction(ISO.CAUSE_SYSTEM)
        self.assertEqual("BLOCKED", d["kind"])
        self.assertNotEqual("AGENT_COMMISSION", d["kind"])
        self.assertNotIn("role", d)

    def test_no_cause_invents_a_fifth_kind(self) -> None:
        """`docs/tooling.md` names the public vocabulary; the internal subclass
        chooses among those and must not add to them."""
        known = {"FIX_PROJECT", "RUN", "AGENT_COMMISSION", "REVIEW",
                 "NEEDS_EVIDENCE", "BLOCKED", "LANE_UNAVAILABLE"}
        for cause in (ISO.CAUSE_MODEL, ISO.CAUSE_PROJECT, ISO.CAUSE_SYSTEM):
            with self.subTest(cause=cause):
                self.assertIn(self._instruction(cause)["kind"], known)


class TheHeadlineNamesWhatRefusedTest(unittest.TestCase):
    """`project.json is not complete enough to build` is false twice when the
    build raised: the file named is not at fault, and a valid `project.json`
    cannot be made 'more complete', so the instruction has no end."""

    def test_a_non_project_stage_names_its_own_subject(self) -> None:
        from . import findings as F
        headline, reason = cli._refusal_wording(
            "build", [F.problem(F.ARTIFACT_REFUSED, "model.py", "boom")])
        self.assertIn("model.py", headline)
        self.assertIn("model.py", reason)
        self.assertNotIn("not complete enough", headline)

    def test_the_route_time_sentence_is_unchanged(self) -> None:
        """This narrows a claim; it does not relocate one."""
        from . import findings as F
        from . import project as P
        problems = [F.problem(F.SCHEMA_REQUIRED, "envelope_mm", "required")]
        for stage in ("run", "route"):
            with self.subTest(stage=stage):
                headline, reason = cli._refusal_wording(stage, problems)
                self.assertEqual(
                    f"{P.PROJECT_FILE} is not complete enough to {stage}", headline)
                self.assertEqual(
                    "the project does not describe a job that can be routed", reason)

    def test_a_where_is_trimmed_to_the_file_it_names(self) -> None:
        """The third case is the trap: splitting on the first dot turns
        `model.py` into `model`, which names nothing on disk. The last is the
        other direction -- `envelope_mm` is not a file."""
        for where, expected in (
                ("design_proposal.json.params", "design_proposal.json"),
                ("print_plan_checks.json[3]", "print_plan_checks.json"),
                ("model.py", "model.py"),
                ("model.py.PARAMS", "model.py"),
                ("envelope_mm", "envelope_mm")):
            with self.subTest(where=where):
                self.assertEqual(expected, cli._subject_of(where))


if __name__ == "__main__":
    unittest.main()
