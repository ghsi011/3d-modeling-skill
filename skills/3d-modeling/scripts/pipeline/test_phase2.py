#!/usr/bin/env python3
"""Stage 2: the acceptance contract, frozen before the candidate exists.

The `CUSTOM` lane's value is that it costs a backend and not a second pipeline:
authored geometry reaches the immutable contract, the preflight, commissioning of
the re-imported mesh, broad screening, the witnesses and the status decision
unchanged. What it did not have was an owner for the acceptance criteria.
`EXPECTED`, `BBOX_MM`, `BODIES`, `VOLUME_MM3` and `PROFILE_MARKS` were read out of
`model.py` on every run and the contract was overwritten with what was found, so
a designer could read a failure, widen the expectation and be commissioned on the
next run with nothing recording that the expectation had moved.

What each group of tests here is for:

* **Two artifacts, one commission.** `design_proposal.json` says what the part
  must measure; `model.py` says how it is built. One designer dispatch produces
  both, and freezing the first is a deterministic pipeline step rather than a
  second round trip.
* **The candidate cannot widen its own tolerance.** The demonstrated defect --
  a model declaring a 24x18 pad, building a 10x8 one, with a self-declared
  500 mm2 band, commissioned `PASS` on a 352 mm2 miss -- is asserted closed from
  both directions: the band cannot be declared, and the miss is caught.
* **Structural, not checked.** `acceptance.py` imports nothing that can see a
  mesh, `runner.py` contains no function that writes an acceptance contract, and
  `AuthoredModel` has no acceptance fields for one to be read back through.
* **Revisions, never overwrites.** A changed proposal cuts a new revision,
  invalidates the receipts issued against the old one, and says so in history.
* **A screen calibrated by its own subject is not a screen.** On the authored
  lanes the volume and profile detectors may report `NOT_APPLICABLE` or
  `ANOMALY`, and never `CLEAR`.
* **A print plan written before the geometry**, gated, and turned into a frozen
  contract feature.
* **The route decision owns which reviews run.** An unconditional verifier
  turned every `CUSTOM` job into one that requires a fresh context, which is the
  opposite of a deliberate escalation.
"""
from __future__ import annotations

import ast
import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from . import acceptance as ACC
from . import authored as A
from . import cli
from . import project as P
from . import route as RT
from . import runner
from . import selftest as ST

UTC = "1970-01-01T00:00:00Z"

# A two-tier riser: a 40x30x6 base with a 24x18x8 pad on it. Self-supporting,
# one body, and every expectation is the closed form of a rectangle.
RISER = '''
import trimesh

PARAMS = {"base_w": 40.0, "base_d": 30.0, "base_h": 6.0,
          "pad_w": 24.0, "pad_d": 18.0, "pad_h": 8.0}


def build():
    base = trimesh.creation.box(extents=(40.0, 30.0, 6.0))
    base.apply_translation((20.0, 15.0, 3.0))
    pad = trimesh.creation.box(extents=(24.0, 18.0, 8.0))
    pad.apply_translation((20.0, 15.0, 10.0))
    return trimesh.boolean.union([base, pad], engine="manifold")
'''

RISER_PROPOSAL = {
    "schema_version": 1,
    "job_id": "custom",
    "design_id": "two-tier-riser",
    "rationale": "a 40x30 base carrying a 24x18 pad",
    "params": {"base_w": 40.0, "base_d": 30.0, "base_h": 6.0,
               "pad_w": 24.0, "pad_d": 18.0, "pad_h": 8.0},
    "bbox_mm": {"x": 40.0, "y": 30.0, "z": 14.0},
    "bodies": 1,
    "profile_marks": {"z": [6.0]},
    "features": [
        {"feature_id": "base-section", "kind": "section_area",
         "at": {"z": 3.0}, "value_mm2": 40.0 * 30.0},
        {"feature_id": "pad-section", "kind": "section_area",
         "at": {"z": 10.0}, "value_mm2": 24.0 * 18.0},
        {"feature_id": "bed-footprint", "kind": "bed_contact",
         "value_mm2": 40.0 * 30.0},
    ],
}

# The same declaration, built 10x8 instead of 24x18. This is the demonstrated
# defect: 432 mm2 promised, 80 mm2 delivered, a 352 mm2 miss.
RISER_SMALL_PAD = RISER.replace("extents=(24.0, 18.0, 8.0)",
                                "extents=(10.0, 8.0, 8.0)")

# The same footprint inverted: a wide slab held up on a narrow post, so most of
# the slab's underside faces the bed with nothing beneath it.
MUSHROOM = '''
import trimesh

PARAMS = {"post_w": 8.0, "cap_w": 40.0, "cap_d": 30.0}


def build():
    post = trimesh.creation.box(extents=(8.0, 8.0, 10.0))
    post.apply_translation((20.0, 15.0, 5.0))
    cap = trimesh.creation.box(extents=(40.0, 30.0, 4.0))
    cap.apply_translation((20.0, 15.0, 12.0))
    return trimesh.boolean.union([post, cap], engine="manifold")
'''

MUSHROOM_PROPOSAL = {
    "schema_version": 1,
    "job_id": "mushroom",
    "design_id": "mushroom",
    "rationale": "a wide cap on a narrow post",
    "params": {"post_w": 8.0, "cap_w": 40.0, "cap_d": 30.0},
    "bbox_mm": {"x": 40.0, "y": 30.0, "z": 14.0},
    "bodies": 1,
    "profile_marks": {"z": [10.0]},
    "features": [
        {"feature_id": "post-section", "kind": "section_area",
         "at": {"z": 5.0}, "value_mm2": 8.0 * 8.0},
        {"feature_id": "cap-section", "kind": "section_area",
         "at": {"z": 12.0}, "value_mm2": 40.0 * 30.0},
        {"feature_id": "bed-footprint", "kind": "bed_contact", "value_mm2": 8.0 * 8.0},
    ],
}

# A second, unrelated part on the other kernel: an exact B-rep spacer washer.
WASHER = '''
from build123d import BuildPart, BuildSketch, Circle, Mode, extrude

PARAMS = {"outer_d": 30.0, "bore_d": 12.0, "thickness": 4.0}


def build():
    with BuildPart() as washer:
        with BuildSketch():
            Circle(radius=15.0)
            Circle(radius=6.0, mode=Mode.SUBTRACT)
        extrude(amount=4.0)
    return washer
'''

_WASHER_SECTION = 3.141592653589793 / 4.0 * (30.0 ** 2 - 12.0 ** 2)

WASHER_PROPOSAL = {
    "schema_version": 1,
    "job_id": "washer",
    "design_id": "spacer-washer",
    "rationale": "a spacer under a desk foot",
    "params": {"outer_d": 30.0, "bore_d": 12.0, "thickness": 4.0},
    "bbox_mm": {"x": 30.0, "y": 30.0, "z": 4.0},
    "bodies": 1,
    "profile_marks": {"z": []},
    "features": [
        {"feature_id": "washer-section", "kind": "section_area",
         "at": {"z": 2.0}, "value_mm2": _WASHER_SECTION},
        {"feature_id": "bed-footprint", "kind": "bed_contact",
         "value_mm2": _WASHER_SECTION},
    ],
}


def _project(**over) -> P.Project:
    base = dict(
        job_id="custom", updated_utc=UTC, source_mode="NEW",
        consequence="INCONSEQUENTIAL",
        consequence_rationale="a desk riser; failure wastes material",
        printer="Test Printer", material={"process": "FDM", "material": "PETG"},
        nozzle={"diameter_mm": 0.4},
        orientation={"model_to_printer_matrix": "identity", "bed_z_mm": 0.0},
        model="model.py", envelope_mm={"x": 40.0, "y": 30.0, "z": 14.0},
        requirements=(P.Requirement(name="base_w", value=40.0, unit="mm",
                                    provenance="STATED", source="user"),),
    )
    base.update(over)
    return P.Project(**base)


def _laid_out(root: Path, source: str | None, project: P.Project,
              proposal: dict | None = RISER_PROPOSAL) -> Path:
    directory = root / "project"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "brief.md").write_text("a riser block", encoding="utf-8")
    if source is not None:
        (directory / "model.py").write_text(textwrap.dedent(source), encoding="utf-8")
    if proposal is not None:
        _propose(directory, proposal)
    project.save(directory)
    return directory


def _propose(directory: Path, proposal: dict) -> Path:
    path = directory / ACC.PROPOSAL_FILE
    path.write_text(json.dumps(proposal, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _read(directory: Path, name: str) -> dict:
    return json.loads((directory / name).read_text(encoding="utf-8"))


class SourceApiTest(unittest.TestCase):
    """What a model module may declare, which is now only how it is built."""

    def _load(self, source: str, root: Path):
        path = root / "model.py"
        path.write_text(textwrap.dedent(source), encoding="utf-8")
        return A.load(path)

    def test_a_model_declares_its_parameters_and_returns_the_solid(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            model, builder = self._load(RISER, Path(raw))
            self.assertEqual(40.0, model.params["base_w"])
            self.assertTrue(callable(builder))
            self.assertTrue(model.module_sha256)

    def test_the_model_owns_no_acceptance_criteria_at_all(self) -> None:
        """Structural, and asserted as such.

        A validator that rejects a moved expectation is a check that can be
        removed, mis-ordered or skipped on one code path -- which is exactly how
        the defect existed. The property here is that there is no field to read:
        `runner._contract_from` asks a template for `expectations`, `bbox` and
        `bodies`, and the object the builder came out of has none of the three.
        """
        for name in ("expectations", "bbox", "bodies", "expected", "bbox_mm",
                     "volume_mm3", "profile_marks"):
            self.assertFalse(
                hasattr(A.AuthoredModel, name)
                or name in A.AuthoredModel.__dataclass_fields__,
                f"AuthoredModel still carries {name!r}, so a model file can still "
                "reach the contract that judges it")

    def test_a_model_that_still_declares_them_is_told_where_they_went(self) -> None:
        for name in ("EXPECTED", "BBOX_MM", "BODIES", "PROFILE_MARKS", "VOLUME_MM3"):
            with self.subTest(declared=name), tempfile.TemporaryDirectory() as raw:
                source = textwrap.dedent(RISER) + f"\n{name} = 1\n"
                with self.assertRaises(A.ModelError) as caught:
                    self._load(source, Path(raw))
                self.assertIn(name, str(caught.exception))

    def test_params_is_still_required(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = textwrap.dedent(RISER).replace("PARAMS = ", "_NOT_PARAMS = ")
            with self.assertRaises(A.ModelError) as caught:
                self._load(source, Path(raw))
            self.assertIn("PARAMS", str(caught.exception))

    def test_a_model_that_raises_on_import_is_a_finding_not_a_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(A.ModelError) as caught:
                self._load("raise RuntimeError('the designer left a stub')", Path(raw))
            self.assertIn("the designer left a stub", str(caught.exception))


class ProposalTest(unittest.TestCase):
    """What a proposal may say, refused before anything is built."""

    def _load(self, over: dict, root: Path):
        return ACC.load_proposal(_propose(root, {**RISER_PROPOSAL, **over}))

    def test_a_complete_proposal_loads(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            proposal = self._load({}, Path(raw))
            self.assertEqual("two-tier-riser", proposal.design_id)
            self.assertEqual(3, len(proposal.features))
            self.assertEqual([6.0], proposal.profile_marks["z"])
            self.assertTrue(proposal.proposal_hash())

    def test_a_row_may_not_carry_its_own_tolerance(self) -> None:
        """The exact shape of the demonstrated defect, refused at the door."""
        rows = [dict(row) for row in RISER_PROPOSAL["features"]]
        rows[1]["tolerance"] = {"abs": 500.0}
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(ACC.ProposalError) as caught:
                self._load({"features": rows}, Path(raw))
            self.assertIn("system-owned", str(caught.exception))

    def test_a_proposal_may_not_declare_an_expected_volume(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(ACC.ProposalError) as caught:
                self._load({"volume_mm3": 10656.0}, Path(raw))
            self.assertIn("NOT_INDEPENDENTLY_SPECIFIED", str(caught.exception))

    def test_a_pipeline_owned_kind_is_not_proposable(self) -> None:
        """The support ceiling belongs to the print plan and the preservation row
        to the declared edit scope; a proposal that could write either would be
        setting its own ceiling again."""
        for kind in ("overhang", "preservation", "fit_acceptance"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as raw:
                rows = [{"feature_id": "sneak", "kind": kind, "value_mm2": 1.0}]
                with self.assertRaises(ACC.ProposalError) as caught:
                    self._load({"features": rows}, Path(raw))
                self.assertIn(kind, str(caught.exception))

    def test_an_empty_feature_list_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(ACC.ProposalError) as caught:
                self._load({"features": []}, Path(raw))
            self.assertIn("cannot fail", str(caught.exception))

    def test_a_duplicate_feature_id_is_refused(self) -> None:
        rows = [dict(row) for row in RISER_PROPOSAL["features"]]
        rows[1]["feature_id"] = rows[0]["feature_id"]
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(ACC.ProposalError) as caught:
                self._load({"features": rows}, Path(raw))
            self.assertIn("duplicate", str(caught.exception))

    def test_a_non_finite_declaration_is_refused_before_anything_is_built(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(ACC.ProposalError):
                self._load({"bbox_mm": {"x": float("nan"), "y": 30.0, "z": 14.0}},
                           Path(raw))

    def test_an_unknown_schema_version_is_refused_rather_than_guessed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(ACC.ProposalError) as caught:
                self._load({"schema_version": 99}, Path(raw))
            self.assertIn("99", str(caught.exception))


class AcceptanceIsUpstreamTest(unittest.TestCase):
    """The ordering, asserted over the code rather than over one run.

    ADR 0002's gate for this stage is not "does a check fire". It is "is there
    any ordering of operations in which the built artifact can influence its own
    acceptance criteria". These are the facts about the *code* that answer it.

    Ordering is not the whole answer and these are not the whole proof. An
    import is an execution, so freezing first bought nothing while the candidate
    was imported into this interpreter; `test_isolation.py` is where that half
    lives, and the first test below is this walker's own fixture because these
    guards were passing on the absolute imports alone.
    """

    def _imports(self, relative: str) -> set[str]:
        """Every name one module imports, `from . import x` included.

        The `and node.module` this used to carry made the guard blind to the
        dominant idiom in this package: `from . import analysis` parses as an
        `ImportFrom` with `module=None`, so the branch never ran and *nothing*
        was recorded -- not the module, not the alias. Every sibling import in
        the forbidden lists below was therefore invisible to the check that
        forbade it, and the two tests were passing on the absolute imports alone.
        `test_the_walker_sees_a_relative_import` is this walker's own fixture.
        """
        root = Path(__file__).resolve().parent
        tree = ast.parse((root / relative).read_text(encoding="utf-8"))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module:
                    names.add(node.module)
                names |= {alias.name for alias in node.names}
            elif isinstance(node, ast.Import):
                names |= {alias.name for alias in node.names}
        return names

    def test_the_walker_sees_a_relative_import(self) -> None:
        """A guard that cannot see the import it forbids is a comment."""
        names = self._imports("runner.py")
        for expected in ("analysis", "commission", "screening", "status"):
            self.assertIn(expected, names,
                          f"runner.py imports {expected} with `from . import` and "
                          "this walker cannot see it, so neither can the two tests "
                          "below")

    def test_the_contract_generator_cannot_see_a_mesh(self) -> None:
        names = self._imports("acceptance.py")
        for forbidden in ("analysis", "commission", "screening", "backends",
                          "trimesh", "build123d", "numpy", "runner"):
            self.assertNotIn(forbidden, names,
                             f"acceptance.py imports {forbidden}, so a measurement "
                             "could reach the criteria it is measured against")

    def test_the_generator_takes_no_parameter_a_build_could_arrive_through(self) -> None:
        import inspect

        taken = set(inspect.signature(ACC.generate).parameters)
        for forbidden in ("ctx", "mesh", "artifact", "built", "commission",
                          "report", "measured"):
            self.assertNotIn(forbidden, taken)

    def test_the_module_that_runs_the_builder_cannot_freeze_a_contract(self) -> None:
        """By import graph and by call, not by grep over the prose.

        `runner.py`'s docstrings name the acceptance contract while explaining
        that the runner is not a source of one, so a substring rule would fail on
        the comment that documents the rule.

        "Runs the builder" is now weaker than it was: the runner invokes a
        backend that adopts geometry a child process already produced, and it
        executes no candidate code at all. What it must still not be able to do
        is write the document the geometry is judged against.
        """
        self.assertNotIn("acceptance", self._imports("runner.py"),
                         "runner.py imports the freezer, which is one line away "
                         "from calling it after the build")
        tree = ast.parse((Path(__file__).resolve().parent / "runner.py")
                         .read_text(encoding="utf-8"))
        called = {node.func.attr for node in ast.walk(tree)
                  if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Attribute)}
        self.assertNotIn("freeze", called)

    def test_the_contract_is_on_disk_before_the_model_is_imported(self) -> None:
        """Proved by a model that reports when it ran.

        The module writes a marker on import. If the acceptance contract's
        modification is later than the marker, the freeze happened after the
        designer's code had a chance to run.
        """
        witness = textwrap.dedent(RISER) + textwrap.dedent('''
            from pathlib import Path
            Path(__file__).with_name("imported.marker").write_text(
                Path(__file__).with_name("acceptance_contract.json").read_text(
                    encoding="utf-8"), encoding="utf-8")
            ''')
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), witness, _project())
            cli.run([str(directory), "--no-render"])
            seen = (directory / "imported.marker").read_text(encoding="utf-8")
            self.assertEqual(
                (directory / ACC.ACCEPTANCE_FILE).read_text(encoding="utf-8"), seen,
                "the model saw a different acceptance contract than the one the run "
                "gated against, so the freeze is not upstream of the import")


class CandidateCannotWidenItsOwnToleranceTest(unittest.TestCase):
    """The demonstrated defect, closed from both directions.

    A model declaring a 24x18 pad, building a 10x8 one, with a self-declared
    `{"abs": 500.0}` band on that row, was commissioned `PASS` on a 352 mm2 miss.
    Two things had to be true for that: the band could be authored by the party
    being measured, and the declaration could be restated after the result.
    """

    def test_a_352_mm2_miss_is_caught_by_the_system_owned_band(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER_SMALL_PAD, _project())
            code = cli.run([str(directory), "--no-render"])

            contract = _read(directory, ACC.ACCEPTANCE_FILE)
            row = next(f for f in contract["features"]
                       if f["feature_id"] == "pad-section")
            self.assertEqual("pipeline", contract["tolerance_owner"])
            self.assertAlmostEqual(2.16, row["tolerance"]["abs"], places=6,
                                   msg="0.5% of 432 mm2, and nothing the designer "
                                       "wrote could have moved it")

            report = _read(directory, "commission_report.json")
            check = next(c for c in report["checks"]
                         if c["check_id"] == "feature-pad-section")
            self.assertEqual("FAIL", check["result"])
            self.assertAlmostEqual(432.0, float(check["expected"]))
            self.assertLess(float(check["measured"]), 100.0)
            self.assertGreater(float(check["expected"]) - float(check["measured"]),
                               350.0, "the 352 mm2 miss, measured")
            self.assertEqual("FAIL", report["verdict"])
            self.assertEqual("FAILED", _read(directory, "final_status.json")
                             ["final_status"])
            self.assertEqual(1, code)

    def test_the_band_it_used_to_widen_cannot_be_written_at_all(self) -> None:
        rows = [dict(row) for row in RISER_PROPOSAL["features"]]
        rows[1]["tolerance"] = {"abs": 500.0}
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER_SMALL_PAD, _project(),
                                  {**RISER_PROPOSAL, "features": rows})
            self.assertEqual(2, cli.run([str(directory), "--no-render"]))
            self.assertFalse((directory / ACC.ACCEPTANCE_FILE).is_file(),
                             "a proposal that names its own band must not reach a "
                             "frozen contract at all")
            action = _read(directory, cli.NEXT_ACTION_FILE)
            self.assertTrue(any("500" in problem for problem in action["unresolved"]),
                            action["unresolved"])

    def test_restating_the_expectation_after_the_result_is_a_visible_revision(self) -> None:
        """The other half: the number can still move, and it cannot move quietly.

        A designer who has read the failure and decided the pad really is 10x8
        may say so. What they cannot do is have the receipt that was issued
        against 24x18 survive them saying it.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER_SMALL_PAD, _project())
            cli.run([str(directory), "--no-render"])
            first = _read(directory, ACC.ACCEPTANCE_FILE)
            self.assertEqual(1, first["revision"])

            widened = [dict(row) for row in RISER_PROPOSAL["features"]]
            widened[1]["value_mm2"] = 10.0 * 8.0
            _propose(directory, {**RISER_PROPOSAL, "features": widened})
            cli.run([str(directory), "--no-render"])

            second = _read(directory, ACC.ACCEPTANCE_FILE)
            self.assertEqual(2, second["revision"])
            self.assertNotEqual(first["contract_sha256"], second["contract_sha256"])

            history = _read(directory, ACC.HISTORY_FILE)
            self.assertEqual([1, 2], [r["revision"] for r in history["revisions"]])
            entry = history["revisions"][1]
            self.assertTrue(any("432" in line and "80" in line
                                for line in entry["changed"]), entry["changed"])
            self.assertEqual(first["contract_sha256"],
                             entry["supersedes"]["contract_sha256"])
            self.assertIn("commission_report.json",
                          entry["supersedes"]["invalidated_receipts"])

    def test_a_proposal_copied_from_another_job_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER, _project(),
                                  {**RISER_PROPOSAL, "job_id": "some-other-job"})
            self.assertEqual(2, cli.run([str(directory), "--no-render"]))
            action = _read(directory, cli.NEXT_ACTION_FILE)
            self.assertTrue(any("some-other-job" in problem
                                for problem in action["unresolved"]), action)
            self.assertFalse((directory / ACC.ACCEPTANCE_FILE).is_file(),
                             "a proposal for another job cut a revision on its way "
                             "to being refused")

    def test_the_model_and_the_proposal_must_agree_about_the_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER, _project(), {
                **RISER_PROPOSAL,
                "params": {**RISER_PROPOSAL["params"], "pad_w": 10.0}})
            self.assertEqual(2, cli.run([str(directory), "--no-render"]))
            action = _read(directory, cli.NEXT_ACTION_FILE)
            self.assertTrue(any("pad_w" in problem
                                for problem in action["unresolved"]), action)


class RevisionTest(unittest.TestCase):
    def test_an_unchanged_proposal_leaves_the_contract_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER, _project())
            cli.run([str(directory), "--no-render"])
            before = (directory / ACC.ACCEPTANCE_FILE).read_bytes()
            cli.run([str(directory), "--no-render"])
            self.assertEqual(before, (directory / ACC.ACCEPTANCE_FILE).read_bytes())
            self.assertEqual(
                1, len(_read(directory, ACC.HISTORY_FILE)["revisions"]),
                "a rerun that changed nothing cut a revision, which makes every "
                "revision that does mean something unreadable")

    def test_reformatting_the_proposal_is_not_a_revision(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER, _project())
            cli.run([str(directory), "--no-render"])
            (directory / ACC.PROPOSAL_FILE).write_text(
                json.dumps(RISER_PROPOSAL), encoding="utf-8")
            cli.run([str(directory), "--no-render"])
            self.assertEqual(1, _read(directory, ACC.ACCEPTANCE_FILE)["revision"])

    def test_a_changed_user_requirement_cuts_a_revision_too(self) -> None:
        """Not only the proposal. The contract binds what the user asked for, and
        a contract that survived a change to that would gate a part against a job
        that no longer exists."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER, _project())
            cli.run([str(directory), "--no-render"])
            (directory / "brief.md").write_text("a taller riser block",
                                                encoding="utf-8")
            cli.run([str(directory), "--no-render"])
            self.assertEqual(2, _read(directory, ACC.ACCEPTANCE_FILE)["revision"])
            entry = _read(directory, ACC.HISTORY_FILE)["revisions"][1]
            self.assertTrue(any("requirement_sha256" in line
                                for line in entry["changed"]), entry["changed"])

    def test_a_new_revision_invalidates_an_independent_verification(self) -> None:
        """Not by deleting the answer -- by making it stop matching.

        The verifier's answer echoes a review envelope that binds the model
        contract's hash, and the model contract carries the acceptance contract's.
        A revision therefore unbinds every answer written against the old one
        without anybody having to remember to go and remove it.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER,
                                  _project(verification_requested=True,
                                           reviewer={"model_snapshot": "test"}))
            self.assertEqual(cli.NEEDS_ACTION, cli.run([str(directory), "--no-render"]))
            packet = _read(directory, "reviews/verification_packet.json")
            (directory / "reviews" / "verification_response.json").write_text(
                json.dumps({"decision": "PASS", "defects": [],
                            "unmet_requirements": [], "missing_evidence": [],
                            "summary": "nothing undeclared visible",
                            "review_envelope": packet["review_envelope"]}),
                encoding="utf-8")
            self.assertEqual(0, cli.run([str(directory), "--no-render"]))
            self.assertEqual("VERIFIED",
                             _read(directory, "final_status.json")["final_status"])

            moved = [dict(row) for row in RISER_PROPOSAL["features"]]
            moved[1]["value_mm2"] = 24.0 * 18.0 - 4.0
            _propose(directory, {**RISER_PROPOSAL, "features": moved})
            self.assertNotEqual(0, cli.run([str(directory), "--no-render"]))
            self.assertNotEqual(
                "VERIFIED",
                (_read(directory, "final_status.json")["final_status"]
                 if (directory / "final_status.json").is_file() else None),
                "an answer written against revision 1 survived into revision 2")

    def test_a_new_revision_removes_the_receipts_it_invalidates(self) -> None:
        """The run that cuts a revision may then fail before it writes anything.

        Driven through a model that raises on import, so the second run stops at
        the build with no fresh receipts of its own. What must not be sitting
        there afterwards is the previous revision's success -- a reader, and
        `design-tool status`, would take it for this one's.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER, _project())
            cli.run([str(directory), "--no-render"])
            for name in ("artifact_manifest.json", "commission_report.json",
                         "final_status.json"):
                self.assertTrue((directory / name).is_file(), name)

            moved = [dict(row) for row in RISER_PROPOSAL["features"]]
            moved[1]["value_mm2"] = 10.0 * 8.0
            _propose(directory, {**RISER_PROPOSAL, "features": moved})
            (directory / "model.py").write_text(
                textwrap.dedent(RISER) + "\nraise RuntimeError('mid-edit')\n",
                encoding="utf-8")
            self.assertEqual(2, cli.run([str(directory), "--no-render"]))

            self.assertEqual(2, _read(directory, ACC.ACCEPTANCE_FILE)["revision"])
            for name in ACC.INVALIDATED_BY_A_NEW_REVISION:
                self.assertFalse((directory / name).is_file(),
                                 f"{name} was issued against revision 1 and is "
                                 "still on disk under revision 2")
            removed = _read(directory, ACC.HISTORY_FILE)["revisions"][1][
                "supersedes"]["invalidated_receipts"]
            self.assertIn("final_status.json", removed)
            self.assertIn("commission_report.json", removed)


class CustomLaneTest(unittest.TestCase):
    def test_a_custom_part_reaches_the_same_receipts_as_a_certified_one(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER, _project())
            code = cli.run([str(directory), "--no-render"])

            report = _read(directory, "commission_report.json")
            self.assertEqual("PASS", report["verdict"], report["checks"])
            final = _read(directory, "final_status.json")
            self.assertEqual("CUSTOM", final["route"])
            self.assertEqual("PASS", final["commission_verdict"])
            self.assertEqual("AVAILABLE", final["lane_status"],
                             "the CUSTOM cap named acceptance criteria read out of "
                             "the model file; there are none left to read")
            for name in ST.FROZEN_ARTIFACTS["CUSTOM"]:
                self.assertTrue((directory / f"{name}.json").is_file(), name)
            # Same frozen reason DIRECT stops here: the broad screen is
            # uncalibrated and this job did not require an independent look.
            self.assertEqual(cli.NEEDS_ACTION, code)
            self.assertEqual("NEEDS_MORE_EVIDENCE", final["final_status"])

    def test_every_receipt_binds_the_frozen_contract(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER, _project())
            cli.run([str(directory), "--no-render"])
            frozen = _read(directory, ACC.ACCEPTANCE_FILE)
            contract = _read(directory, "model_contract.json")
            self.assertEqual(frozen["contract_sha256"],
                             contract["source"]["acceptance_contract_sha256"])
            self.assertEqual(frozen["proposal_sha256"],
                             contract["source"]["proposal_sha256"])
            self.assertEqual(1, contract["source"]["acceptance_revision"])
            self.assertEqual("two-tier-riser", contract["template"])
            self.assertEqual("authored-r1", contract["template_version"],
                             "the revision is on the receipt's face, not only in "
                             "the hash")
            self.assertEqual(_read(directory, "artifact_manifest.json")
                             ["contract_sha256"],
                             _read(directory, "commission_report.json")
                             ["contract_hash"])

    def test_an_unrelated_custom_part_on_the_other_kernel_works_too(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), WASHER, _project(
                job_id="washer", envelope_mm={"x": 30.0, "y": 30.0, "z": 4.0},
                consequence_rationale="a spacer washer under a desk foot"),
                WASHER_PROPOSAL)
            cli.run([str(directory), "--no-render"])
            report = _read(directory, "commission_report.json")
            self.assertEqual("PASS", report["verdict"], report["checks"])
            artifact = _read(directory, "artifact_manifest.json")
            self.assertEqual("authored", artifact["backend"])
            self.assertIn("build123d", artifact["backend_version"])
            self.assertEqual("n/a (B-rep)", artifact["boolean_engine"])

    def test_the_contract_binds_the_module_that_was_built(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER, _project())
            cli.run([str(directory), "--no-render"])
            first = _read(directory, "model_contract.json")
            self.assertEqual("authored", first["source"]["kind"])
            self.assertEqual("model.py", first["source"]["module"])

            (directory / "model.py").write_text(
                textwrap.dedent(RISER) + "\n# a comment the designer added\n",
                encoding="utf-8")
            cli.run([str(directory), "--no-render"])
            second = _read(directory, "model_contract.json")
            self.assertNotEqual(first["source"]["module_sha256"],
                                second["source"]["module_sha256"])
            self.assertEqual(1, _read(directory, ACC.ACCEPTANCE_FILE)["revision"],
                             "editing the model must not move the contract it is "
                             "judged against; iterating against a fixed expectation "
                             "is the whole point")

    def test_a_mesh_model_does_not_claim_an_engine_nobody_observed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER, _project())
            cli.run([str(directory), "--no-render"])
            self.assertIn("unrecorded", _read(directory, "artifact_manifest.json")
                          ["boolean_engine"])


class ScreeningPolicyTest(unittest.TestCase):
    """A screen calibrated by its own subject is not a screen."""

    def test_neither_calibrated_detector_clears_an_authored_part(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER, _project())
            cli.run([str(directory), "--no-render"])
            screen = _read(directory, "commission_report.json")["screening"]
            self.assertEqual("SELF_DECLARED", screen["expectation_source"])
            by_name = {d["detector"]: d for d in screen["detectors"]}
            self.assertEqual("NOT_APPLICABLE", by_name["volume"]["result"])
            self.assertEqual("NOT_INDEPENDENTLY_SPECIFIED",
                             by_name["volume"]["calibration"])
            self.assertIsNotNone(by_name["volume"]["measured_mm3"],
                                 "the measurement may still appear on the receipt")
            self.assertIsNone(by_name["volume"]["expected_mm3"])
            self.assertEqual("NOT_APPLICABLE", by_name["profile-z"]["result"])

    def test_an_undeclared_step_is_still_an_anomaly(self) -> None:
        """Removing the invalid clearance does not remove the finding.

        A step the designer's own declarations fail to explain is evidence
        against the part whoever wrote the declarations.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER, _project(),
                                  {**RISER_PROPOSAL, "profile_marks": {"z": []}})
            cli.run([str(directory), "--no-render"])
            report = _read(directory, "commission_report.json")
            self.assertEqual("ANOMALY", report["screening"]["overall"])

    def _with_volume(self, directory: Path, volume: float):
        """The same job's contract, with an independently specified volume on it."""
        frozen = ACC.Frozen(
            path=directory / ACC.ACCEPTANCE_FILE,
            payload={**_read(directory, ACC.ACCEPTANCE_FILE),
                     "expected_volume_mm3": volume,
                     "expected_volume_basis": "ANALYTIC_FROM_FROZEN_PROPOSAL"},
            revision=1, contract_sha256="", disposition="UNCHANGED")
        source = ACC.AcceptanceSource(frozen=frozen, module="model.py",
                                      module_sha256="")
        fields = P.to_job_request_fields(_project())
        fields["template"] = None
        return runner._contract_from(source, runner.JobRequest(
            brief_path=directory / "brief.md", out_dir=directory, render=False,
            acceptance=source, **fields))

    def test_an_independently_specified_volume_does_drive_the_screen(self) -> None:
        """The policy is about where the number came from, not about the lane.

        Nothing in this build has an independent expected volume for novel
        authored geometry, so `NOT_INDEPENDENTLY_SPECIFIED` is what a `CUSTOM`
        run records. The detector is still wired to honour one, because otherwise
        `expected_volume_basis` would be a field nothing reads and the first
        legitimate source to arrive -- a bounded source delta, a previously
        approved revision -- would need the screen rebuilt as well as the
        contract.
        """
        from . import analysis, screening

        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER, _project())
            cli.run([str(directory), "--no-render"])
            ctx = analysis.load(directory / "candidate.stl")
            truth = 40.0 * 30.0 * 6.0 + 24.0 * 18.0 * 8.0
            for volume, result in ((truth, "CLEAR"), (truth * 1.2, "ANOMALY")):
                with self.subTest(result=result):
                    screen = screening.run(ctx, self._with_volume(directory, volume))
                    self.assertEqual(result, {d["detector"]: d["result"]
                                              for d in screen["detectors"]}["volume"])

    def test_a_certified_part_still_gets_a_second_party_screen(self) -> None:
        """The policy is per owner, not a blanket downgrade: `templates.py` is
        written by somebody who is not the designer, so DIRECT keeps its screen."""
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            (out / "brief.md").write_text("a clip", encoding="utf-8")
            result = runner.run(ST._request(out, "c_clip"))
            screen = result.final_status and json.loads(
                (out / "commission_report.json").read_text(encoding="utf-8"))["screening"]
            self.assertEqual("SECOND_PARTY", screen["expectation_source"])
            by_name = {d["detector"]: d for d in screen["detectors"]}
            self.assertEqual("CLEAR", by_name["volume"]["result"])
            self.assertEqual("CLEAR", by_name["profile-z"]["result"])


class PrintPlanTest(unittest.TestCase):
    def test_one_commission_asks_for_the_proposal_and_the_model_together(self) -> None:
        """One dispatch, not two. Freezing is a pipeline step."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), None, _project(), None)
            code = cli.run([str(directory), "--no-render"])
            self.assertEqual(cli.NEEDS_ACTION, code)
            self.assertFalse((directory / "model.py").is_file())
            plan = _read(directory, cli.PLAN_FILE)
            self.assertEqual("builtin-direct-template", plan["owner"])

            action = _read(directory, cli.NEXT_ACTION_FILE)
            self.assertEqual("designer", action["role"])
            self.assertEqual("AGENT_COMMISSION", action["kind"])
            self.assertEqual([ACC.PROPOSAL_FILE, "model.py"],
                             action["required_outputs"])
            self.assertIn(cli.PLAN_FILE, action["authorized_inputs"])
            self.assertIn("features", action["proposal_api"])
            self.assertIn("PARAMS", action["source_api"])
            self.assertTrue(action["bound"]["print_plan_sha256"])

    def test_the_support_ceiling_is_a_frozen_contract_feature_and_it_bites(self) -> None:
        """The rule four archived runs set after reading their own measurement.

        The mushroom is a 40x30 cap on an 8 mm post: most of the cap's underside
        faces the bed with nothing beneath it. Every declared expectation passes
        -- the sections and the footprint are exactly the closed form -- so this
        is the plan catching what the proposal's own arithmetic cannot.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), MUSHROOM, _project(job_id="mushroom"),
                                  MUSHROOM_PROPOSAL)
            code = cli.run([str(directory), "--no-render"])
            frozen = _read(directory, ACC.ACCEPTANCE_FILE)
            self.assertTrue([f for f in frozen["features"]
                             if f["kind"] == "overhang"],
                            "the print plan's rule must be inside the frozen "
                            "contract, under the same revision discipline as "
                            "everything else the part is gated against")
            report = _read(directory, "commission_report.json")
            overhang = [c for c in report["checks"]
                        if c["check_id"].startswith("feature-plan-support")]
            self.assertTrue(overhang, "the plan's support rule reached no check")
            self.assertEqual("FAIL", overhang[0]["result"], overhang)
            self.assertGreater(overhang[0]["measured"], 900.0)
            self.assertEqual("FAIL", report["verdict"])
            self.assertEqual(1, code)

    def test_a_custom_job_without_an_envelope_is_refused_not_guessed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER, _project(envelope_mm=None))
            self.assertEqual(2, cli.run([str(directory), "--no-render"]))
            action = _read(directory, cli.NEXT_ACTION_FILE)
            self.assertTrue(any("envelope_mm" in p for p in action["unresolved"]))


class ReviewPolicyTest(unittest.TestCase):
    def test_an_uncomplicated_custom_job_dispatches_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER, _project())
            cli.run([str(directory), "--no-render"])
            self.assertFalse((directory / "reviews").exists(),
                             "a verifier the route did not ask for is not a free "
                             "extra look; it is an escalation nobody decided on")

    def test_a_consequential_custom_job_asks_for_safety_and_verification(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER, _project(
                consequence="CONSEQUENTIAL",
                consequence_rationale="carries a monitor arm over a desk",
                reviewer={"model_snapshot": "test"}))
            project = P.load(directory)
            decision = RT.decide(project)
            RT.apply(project, decision)
            self.assertEqual(("safety", "verification"), project.required_reviews)

            self.assertEqual(cli.NEEDS_ACTION, cli.run([str(directory), "--no-render"]))
            action = _read(directory, cli.NEXT_ACTION_FILE)
            self.assertEqual("safety", action["review_kind"])


if __name__ == "__main__":
    unittest.main()
