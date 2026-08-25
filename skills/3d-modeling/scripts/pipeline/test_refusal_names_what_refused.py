#!/usr/bin/env python3
"""A refusal has to name the file that refused, not the one it was written for.

`_report_problems` is the `FIX_PROJECT` channel, and `docs/tooling.md` is
explicit that the kind covers four stages -- `route`/`run` for an incomplete
`project.json`, and `plan`, `proposal` or `build` for something the project
merely points at. `stage` is what tells them apart, and that part was already
right.

What was wrong is the sentence. Both the headline and the recorded `reason` were
written for the route-time case and spoken over all four, so a CAD kernel
exception raised inside `model.py` was announced as:

    design-tool: project.json is not complete enough to build:
      - gp_Dir2d() - input vector has zero norm

That is false twice. The file named is not the file at fault -- the finding's own
`where` said `model.py` all along -- and **a valid `project.json` cannot be made
"more complete"**, so the instruction cannot be followed. A designer that trusts
it goes and re-reads a file that was never the problem, and one full iteration of
model reasoning is spent on the wrong question.

The cost is not the message. `design-tool run` is about four seconds; an agent
iteration on the runs measured for this was about 250. A cheap call that
misdirects is expensive.
"""
from __future__ import annotations

import unittest

from . import cli
from . import findings as F
from . import project as P


class TheHeadlineNamesWhatRefusedTest(unittest.TestCase):
    """`_refusal_wording` alone -- no build, no temp dir, no CAD."""

    @staticmethod
    def _build_failure() -> list[F.Issue]:
        return [F.problem(F.ARTIFACT_REFUSED, "model.py",
                          "gp_Dir2d() - input vector has zero norm")]

    def test_a_build_failure_names_the_model_and_not_the_project(self) -> None:
        headline, reason = cli._refusal_wording("build", self._build_failure())
        self.assertIn("model.py", headline)
        self.assertIn("model.py", reason)
        self.assertNotIn(P.PROJECT_FILE, headline)
        self.assertNotIn(P.PROJECT_FILE, reason)

    def test_a_build_failure_does_not_claim_the_project_is_incomplete(self) -> None:
        """The specific falsehood: a valid project.json is not 'incomplete', and
        telling a designer to complete it names a task with no end."""
        headline, reason = cli._refusal_wording("build", self._build_failure())
        self.assertNotIn("not complete enough", headline)
        self.assertNotIn("does not describe a job that can be routed", reason)

    def test_the_project_stages_are_unchanged(self) -> None:
        """The route-time sentence was correct for the route-time case and keeps
        its exact wording; this fix narrows a claim, it does not relocate one."""
        problems = [F.problem(F.SCHEMA_REQUIRED, "envelope_mm", "required")]
        for stage in ("run", "route"):
            with self.subTest(stage=stage):
                headline, reason = cli._refusal_wording(stage, problems)
                self.assertEqual(
                    f"{P.PROJECT_FILE} is not complete enough to {stage}", headline)
                self.assertEqual(
                    "the project does not describe a job that can be routed", reason)

    def test_the_headline_names_every_subject_exactly_once(self) -> None:
        with self.subTest("a proposal refusal names the proposal"):
            headline, _ = cli._refusal_wording(
                "proposal", [F.problem(F.ARTIFACT_REFUSED, "design_proposal.json",
                                       "revision 2 is not a superset")])
            self.assertIn("design_proposal.json", headline)
        with self.subTest("two files that refuse are both named"):
            headline, _ = cli._refusal_wording("plan", [
                F.problem(F.ARTIFACT_REFUSED, "print_plan_checks.json[0]", "a"),
                F.problem(F.ARTIFACT_REFUSED, "model.py", "b")])
            self.assertIn("print_plan_checks.json", headline)
            self.assertIn("model.py", headline)
        with self.subTest("one file with several findings is named once"):
            headline, _ = cli._refusal_wording("plan", [
                F.problem(F.ARTIFACT_REFUSED, "print_plan_checks.json[0]", "a"),
                F.problem(F.ARTIFACT_REFUSED, "print_plan_checks.json[1]", "b")])
            self.assertEqual(1, headline.count("print_plan_checks.json"))

    def test_it_falls_back_to_the_project_when_a_finding_names_nothing(self) -> None:
        """A finding with no `where` must not produce a headline naming the empty
        string; the project is the honest subject when nothing narrower is known."""
        headline, _ = cli._refusal_wording(
            "build", [F.problem(F.ARTIFACT_REFUSED, "", "something raised")])
        self.assertIn(P.PROJECT_FILE, headline)


class TheSubjectIsAFileAndNotAFieldTest(unittest.TestCase):
    """`_subject_of` -- the headline wants the file, the finding keeps the path."""

    def test_a_where_is_trimmed_to_the_file_it_names(self) -> None:
        """The third case is the trap this predicate exists for: splitting on the
        first dot turns `model.py` into `model`, which names nothing on disk. The
        last is the other direction -- `envelope_mm` is not a file and must not be
        mangled into one."""
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
