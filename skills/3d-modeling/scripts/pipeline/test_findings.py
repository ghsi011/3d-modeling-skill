#!/usr/bin/env python3
"""Release 3 slice C: a project problem is data, not a sentence.

`Project.validate()` answered in English. With one formulation that is readable;
with N, "which alternative, which field, and is this the same problem the last
run reported" are questions a sentence cannot answer. The type that answers them
already existed in `team_tools`, so it moved to `pipeline.findings` and
`validate()` returns it.

What each class here holds to:

* **The findings contract.** Every problem carries a code from a declared group,
  a field path that names a position rather than a name, and an id no other
  problem in the same report shares.
* **The English survives.** The sentences and their order are the same ones a
  user read before, pinned literally, because "the message is already good" is a
  claim a golden can keep and a comment cannot.
* **Both registers reach the reader.** The terminal still prints sentences;
  `next_action.json` and `design-tool status --json` carry the structure beside
  them, and `unresolved` -- which three other writers also fill -- is untouched.
* **The move did not change `team_tools`.** Its receipts carry `Issue.to_dict()`
  verbatim, so a move that altered the type would have altered every receipt.
"""
from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path

from . import cli
from . import findings as F
from . import project as P

UTC = "1970-01-01T00:00:00Z"


def _skeleton() -> P.Project:
    return P.skeleton(job_id="skeleton", source_mode="NEW",
                      consequence="INCONSEQUENTIAL", updated_utc=UTC)


def _broken() -> P.Project:
    """One project reaching every code the validator can emit.

    Deliberately absurd. The point is not that anybody writes this file, it is
    that the vocabulary is exercised as a whole: a code that no fixture ever
    produces is a code nothing has checked the spelling of, and one this fixture
    stops reaching is a check that quietly moved onto a different code.
    """
    return P.Project(
        job_id="", updated_utc="",
        source_mode="NEW",                       # with source artifacts: a contradiction
        consequence="NOT_A_CLASS",
        printer="", material=None, nozzle=None,
        orientation={"model_to_printer_matrix": "skew", "bed_z_mm": "low"},
        route="SIDEWAYS",
        parameters={"bore_d": float("nan")},
        requirements=(
            P.Requirement(name="bore_d", value=12.0, unit="mm",
                          provenance="GUESSED", source="", artifact_id="ghost"),
            P.Requirement(name="bore_d", value=13.0, unit="mm",
                          provenance="STATED", source="user"),
        ),
        source_artifacts=(
            P.SourceArtifact(artifact_id="src", path="../../secrets.step",
                             format="DWG", classification="MAYBE"),
            P.SourceArtifact(artifact_id="gone", path="never-supplied.step",
                             format="STEP"),
        ),
        interfaces=(P.Interface(interface_id="seat", kind="face", external=True,
                                owner="them", motion_id="nothing"),),
        motion=(P.Motion(motion_id="slide", kind="SIDEWAYS",
                         static=("rail",), moving=("rail",)),),
        components=(P.Component(component_id="body", role="housing", count=0),),
        edit_scopes=(
            P.EditScope(artifact_id="src", region="",
                        region_box={"min": [1.0, 1.0, 1.0], "max": [0.0, 0.0, 0.0]},
                        interface_ids=("nobody",)),
            P.EditScope(artifact_id="src", region="the other one"),
        ),
        alternatives=(P.Alternative(alternative_id="Snap Fit", parents=("nobody",),
                                    reason="", disposition="ABANDONED"),
                      P.Alternative(alternative_id="paused-one",
                                    reason="parked while the other is tried",
                                    disposition="PAUSED")),
        active_alternative="paused-one",
        envelope_mm={"x": 0.0, "y": 10.0, "z": 10.0},
    )


class TheFindingContractTest(unittest.TestCase):
    def test_a_skeleton_reports_the_same_sentences_in_the_same_order(self) -> None:
        """The English a user reads, pinned, plus the code it now carries.

        `design-tool init` prints this list as a to-do list. Both halves are the
        contract: a reshuffled list reads as a different set of problems, and a
        reworded one is a change to what the user was told.
        """
        self.assertEqual([
            ("SCHEMA_REQUIRED@consequence_rationale",
             "consequence_rationale is required: a class with no reason behind it "
             "cannot be re-checked when the job changes"),
            ("SCHEMA_REQUIRED@printer",
             "printer is required and must be a non-empty string"),
            ("SCHEMA_TYPE@material",
             "material must name non-empty process and material strings"),
            ("SCHEMA_RANGE@nozzle.diameter_mm",
             "nozzle.diameter_mm must be a positive number"),
            ("SCHEMA_TYPE@orientation.model_to_printer_matrix",
             "orientation.model_to_printer_matrix must be 'identity' or a 4x4 matrix"),
            ("SCHEMA_TYPE@orientation.bed_z_mm",
             "orientation.bed_z_mm must be a number"),
        ], [(issue.id, issue.message)
            for issue in _skeleton().validate(require_buildable=False)])

    def test_every_code_is_declared_and_belongs_to_one_group(self) -> None:
        """A code with no group is a code with no rule behind it.

        The grouping is the promise: the prefix says what has to change to clear
        the finding -- a field, a row, a file, or a decision -- so a caller can
        route a whole class of problem without matching every code in it.
        """
        for issue in _broken().validate():
            with self.subTest(where=issue.where):
                self.assertIn(issue.code, F.CODES)
                self.assertTrue(
                    any(issue.code.startswith(group) for group in F.CODE_GROUPS),
                    f"{issue.code} belongs to no declared group")
                self.assertEqual("error", issue.severity)

    def test_every_code_the_validator_can_emit_is_reached_by_this_fixture(self) -> None:
        """A declared code no fixture produces is a code nothing has spell-checked.

        Equality rather than containment, both ways: a code added to `CODES` and
        never emitted is dead vocabulary, and moving an existing check onto a
        different code silently retires the one it left.

        `ARTIFACT_REFUSED` is the exception and is excluded by name: no
        declaration in `project.json` can produce it, because it means a document
        the project *names* was read and refused. `BothRegistersReachTheReaderTest`
        reaches it through the stage that does the reading.
        """
        with tempfile.TemporaryDirectory() as raw:
            reached = {issue.code for issue in _broken().validate(Path(raw))}
        self.assertEqual(set(F.CODES) - {F.ARTIFACT_REFUSED}, reached)
        self.assertEqual(set(F.CODE_GROUPS),
                         {group for code in reached for group in F.CODE_GROUPS
                          if code.startswith(group)})

    def test_every_finding_names_a_field_path_no_other_finding_shares(self) -> None:
        """`CODE@where` is what a caller keys on across runs and alternatives.

        Two findings with one id are two things a caller cannot tell apart, which
        is the failure the whole type exists to remove. Positions, not names: a
        `where` built from an id would move when the id was corrected.
        """
        issues = _broken().validate()
        self.assertEqual(len(issues), len({issue.id for issue in issues}),
                         sorted(issue.id for issue in issues))
        for issue in issues:
            with self.subTest(id=issue.id):
                self.assertTrue(issue.where.strip())
                self.assertNotIn(" ", issue.where,
                                 "a field path is something a caller indexes with, "
                                 "not a phrase")

    def test_two_sibling_rows_are_told_apart_by_position(self) -> None:
        """The question with N alternatives is *which one*, and this is the answer.

        Both scopes are missing something, and before this slice the only thing
        distinguishing the two problems was the artifact id quoted inside an
        English sentence.
        """
        issues = _broken().validate()
        empty = [i for i in issues if i.code == F.SCHEMA_RANGE
                 and i.where.startswith("edit_scopes[0].region_box")]
        missing = [i for i in issues if i.where == "edit_scopes[1].region_box"]
        self.assertEqual(["edit_scopes[0].region_box.x",
                          "edit_scopes[0].region_box.y",
                          "edit_scopes[0].region_box.z"],
                         [i.where for i in empty])
        self.assertEqual(["SCHEMA_REQUIRED"], [i.code for i in missing])

    def test_a_dangling_reference_is_not_filed_as_a_bad_field(self) -> None:
        """The group is chosen by what clears it, and these clear differently.

        `interface_ids: ["nobody"]` is a well-formed list of well-formed ids. The
        field is not wrong; the row it points at does not exist. Filing it under
        SCHEMA_ would tell a caller to go and fix the spelling of a value that is
        spelled correctly.
        """
        by_id = {issue.id: issue for issue in _broken().validate()}
        self.assertEqual(
            F.REF_UNDECLARED, by_id["REF_UNDECLARED@edit_scopes[0].interface_ids[0]"].code)
        self.assertEqual(
            F.SCHEMA_REQUIRED, by_id["SCHEMA_REQUIRED@edit_scopes[0].region"].code)
        self.assertEqual(
            F.INTENT_CONTRADICTION, by_id["INTENT_CONTRADICTION@source_mode"].code)


class BothRegistersReachTheReaderTest(unittest.TestCase):
    """Sentences for the terminal, structure for the caller, one validate() call."""

    def _refused(self, root: Path) -> tuple[Path, dict]:
        directory = root / "project"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "brief.md").write_text("a clip", encoding="utf-8")
        _skeleton().save(directory)
        self.assertEqual(2, cli.run([str(directory), "--no-render"]))
        action = json.loads((directory / cli.NEXT_ACTION_FILE)
                            .read_text(encoding="utf-8"))
        return directory, action

    def test_the_refusal_carries_the_findings_beside_the_sentences(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            _, action = self._refused(Path(raw))
        self.assertEqual("FIX_PROJECT", action["kind"])
        # Unchanged: still English, still one entry per problem, still in order.
        # Three other writers fill this key from `status.derive`'s reasons, a
        # stage's message and the project's blocking questions, so a reader
        # cannot be asked to guess which of the four produced the list it holds.
        self.assertTrue(all(isinstance(row, str) for row in action["unresolved"]),
                        action["unresolved"])
        self.assertEqual(action["unresolved"],
                         [row["message"] for row in action["findings"]])
        for row in action["findings"]:
            self.assertEqual({"id", "severity", "code", "where", "message"},
                             set(row))
            self.assertIn(row["code"], F.CODES)

    def test_status_reports_the_findings_the_run_refused_on(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory, action = self._refused(Path(raw))
            report = json.loads(_captured(lambda: cli.status([str(directory), "--json"])))
        self.assertEqual(action["unresolved"], report["problems"])
        self.assertEqual(action["findings"], report["findings"])

    def _authored(self, root: Path, **over) -> P.Project:
        directory = root / "project"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "brief.md").write_text("a clip", encoding="utf-8")
        project = _skeleton()
        project.printer = "Test Printer"
        project.material = {"process": "FDM", "material": "PLA"}
        project.nozzle = {"diameter_mm": 0.4}
        project.orientation = {"model_to_printer_matrix": "identity",
                               "bed_z_mm": 0.0}
        project.consequence_rationale = "a desk clip"
        project.model = "model.py"
        project.envelope_mm = {"x": 40.0, "y": 30.0, "z": 14.0}
        for name, value in over.items():
            setattr(project, name, value)
        project.save(directory)
        return project

    def _refusal(self, directory: Path) -> dict:
        self.assertEqual(2, cli.run([str(directory), "--no-render"]))
        action = json.loads((directory / cli.NEXT_ACTION_FILE)
                            .read_text(encoding="utf-8"))
        self.assertEqual(action["unresolved"],
                         [row["message"] for row in action["findings"]])
        return action

    def test_a_stage_refusal_is_a_finding_too(self) -> None:
        """`_report_problems` has one element type, whichever stage called it.

        Five call sites report a missing envelope, a plan that does not validate,
        a refused proposal, a refused build and a model that contradicts its
        proposal. They wrote bare sentences into the same field, so the list a
        reader parsed depended on which stage had filled it.
        """
        with tempfile.TemporaryDirectory() as raw:
            self._authored(Path(raw), envelope_mm=None)
            action = self._refusal(Path(raw) / "project")
        self.assertEqual(["SCHEMA_REQUIRED@envelope_mm"],
                         [row["id"] for row in action["findings"]])

    def test_a_document_the_project_names_and_cannot_use_is_artifact_refused(self) -> None:
        """The group is what clears it: this one needs the *file* corrected.

        Nothing in `project.json` is wrong -- it names a proposal, and the
        proposal is there. `SCHEMA_*` would send a reader to the wrong file.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw) / "project"
            self._authored(Path(raw))
            (directory / "model.py").write_text("PARAMS = {}\n", encoding="utf-8")
            (directory / "design_proposal.json").write_text("{ not json",
                                                            encoding="utf-8")
            action = self._refusal(directory)
        self.assertEqual("proposal", action["stage"])
        self.assertEqual(["ARTIFACT_REFUSED@design_proposal.json"],
                         [row["id"] for row in action["findings"]])


class TheMoveDidNotChangeTeamToolsTest(unittest.TestCase):
    def test_one_type_serves_both_packages(self) -> None:
        from team_tools import common as C
        self.assertIs(F.Issue, C.Issue)

    def test_a_team_tools_finding_still_composes_its_own_message(self) -> None:
        """Its receipts carry `to_dict()` verbatim, so this is a receipt golden.

        `pipeline` supplies its message and `team_tools` does not; the default is
        what every existing receipt was written with.
        """
        from team_tools import common as C
        self.assertEqual(
            {"id": "NON_FINITE@dimensions.dimensions[D99].nominal_mm",
             "severity": "error",
             "code": "NON_FINITE",
             "where": "dimensions.dimensions[D99].nominal_mm",
             "message": "dimensions.dimensions[D99].nominal_mm: non-finite number nan"},
            C.error("NON_FINITE", "dimensions.dimensions[D99].nominal_mm",
                    "non-finite number nan").to_dict())

    def test_the_dependency_points_from_team_tools_to_pipeline(self) -> None:
        """And never back.

        `team_tools` is the older package and `pipeline` is the one being built.
        A shared module owned the other way round would make everything built
        next depend on the layer it replaces, and the import that establishes it
        is a one-line change nobody would notice in review.
        """
        offenders = []
        for path in sorted(Path(__file__).resolve().parent.glob("*.py")):
            if path.name.startswith("test_"):
                # A test may import either package; what must not happen is a
                # production module of `pipeline` acquiring the dependency.
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = ([alias.name for alias in node.names]
                         if isinstance(node, ast.Import)
                         else [node.module or ""] if isinstance(node, ast.ImportFrom)
                         else [])
                if any(name.split(".")[0] == "team_tools" for name in names):
                    offenders.append(path.name)
        self.assertEqual([], offenders,
                         "a pipeline module imported team_tools; the shared type "
                         "lives in pipeline.findings precisely so it need not")


def _captured(call) -> str:
    import contextlib
    import io
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        call()
    return buffer.getvalue()


if __name__ == "__main__":
    unittest.main()
