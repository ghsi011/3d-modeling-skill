#!/usr/bin/env python3
"""Phase 2: the `CUSTOM` lane — authored geometry through the same gates.

The point of the lane is that it costs a backend and not a second pipeline. An
authored model reaches the immutable contract, the preflight, commissioning of
the re-imported mesh, broad screening, the witnesses and the status decision
unchanged, so there is one definition of each and a novel part is held to the
same standard as a certified one.

What is genuinely new, and what each test here is for:

* **A source API with declarations, not measurements.** `BBOX_MM`, `EXPECTED`,
  `PROFILE_MARKS` and `VOLUME_MM3` are derived from `PARAMS` by arithmetic that
  does not go through the builder. A model that omits them is refused before
  anything is built.
* **A print plan written before the geometry.** Generated from the printer and
  the declared envelope, gated, and turned into a contract feature — so the
  support ceiling cannot have been set after reading the candidate.
* **The route decision owns which reviews run.** An unconditional verifier
  turned every `CUSTOM` job into one that requires a fresh context, which is the
  opposite of a deliberate escalation.
"""
from __future__ import annotations

import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from . import authored as A
from . import cli
from . import commission as CM
from . import project as P
from . import route as RT
from . import selftest as ST

UTC = "1970-01-01T00:00:00Z"

# A two-tier riser: a 40x30x6 base with a 24x18x8 pad on it. Self-supporting,
# one body, and every expectation is the closed form of a rectangle.
RISER = '''
import trimesh

PARAMS = {"base_w": 40.0, "base_d": 30.0, "base_h": 6.0,
          "pad_w": 24.0, "pad_d": 18.0, "pad_h": 8.0}
BBOX_MM = {"x": 40.0, "y": 30.0, "z": 14.0}
BODIES = 1
PROFILE_MARKS = {"z": [6.0]}
VOLUME_MM3 = 40.0 * 30.0 * 6.0 + 24.0 * 18.0 * 8.0
EXPECTED = [
    {"feature_id": "base-section", "kind": "section_area",
     "at": {"z": 3.0}, "value_mm2": 40.0 * 30.0},
    {"feature_id": "pad-section", "kind": "section_area",
     "at": {"z": 10.0}, "value_mm2": 24.0 * 18.0},
    {"feature_id": "bed-footprint", "kind": "bed_contact", "value_mm2": 40.0 * 30.0},
]


def build():
    base = trimesh.creation.box(extents=(40.0, 30.0, 6.0))
    base.apply_translation((20.0, 15.0, 3.0))
    pad = trimesh.creation.box(extents=(24.0, 18.0, 8.0))
    pad.apply_translation((20.0, 15.0, 10.0))
    return trimesh.boolean.union([base, pad], engine="manifold")
'''

# The same footprint inverted: a wide slab held up on a narrow post, so most of
# the slab's underside faces the bed with nothing beneath it.
MUSHROOM = '''
import trimesh

PARAMS = {"post_w": 8.0, "cap_w": 40.0, "cap_d": 30.0}
BBOX_MM = {"x": 40.0, "y": 30.0, "z": 14.0}
BODIES = 1
PROFILE_MARKS = {"z": [10.0]}
VOLUME_MM3 = 8.0 * 8.0 * 10.0 + 40.0 * 30.0 * 4.0
EXPECTED = [
    {"feature_id": "post-section", "kind": "section_area",
     "at": {"z": 5.0}, "value_mm2": 8.0 * 8.0},
    {"feature_id": "cap-section", "kind": "section_area",
     "at": {"z": 12.0}, "value_mm2": 40.0 * 30.0},
    {"feature_id": "bed-footprint", "kind": "bed_contact", "value_mm2": 8.0 * 8.0},
]


def build():
    post = trimesh.creation.box(extents=(8.0, 8.0, 10.0))
    post.apply_translation((20.0, 15.0, 5.0))
    cap = trimesh.creation.box(extents=(40.0, 30.0, 4.0))
    cap.apply_translation((20.0, 15.0, 12.0))
    return trimesh.boolean.union([post, cap], engine="manifold")
'''

# A second, unrelated part on the other kernel: an exact B-rep spacer washer.
WASHER = '''
import math
from build123d import BuildPart, BuildSketch, Circle, Mode, extrude

PARAMS = {"outer_d": 30.0, "bore_d": 12.0, "thickness": 4.0}
BBOX_MM = {"x": 30.0, "y": 30.0, "z": 4.0}
BODIES = 1
PROFILE_MARKS = {"z": []}
VOLUME_MM3 = math.pi / 4.0 * (30.0 ** 2 - 12.0 ** 2) * 4.0
EXPECTED = [
    {"feature_id": "washer-section", "kind": "section_area",
     "at": {"z": 2.0}, "value_mm2": math.pi / 4.0 * (30.0 ** 2 - 12.0 ** 2)},
    {"feature_id": "bed-footprint", "kind": "bed_contact",
     "value_mm2": math.pi / 4.0 * (30.0 ** 2 - 12.0 ** 2)},
]


def build():
    with BuildPart() as washer:
        with BuildSketch():
            Circle(radius=15.0)
            Circle(radius=6.0, mode=Mode.SUBTRACT)
        extrude(amount=4.0)
    return washer
'''


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


def _laid_out(root: Path, source: str | None, project: P.Project) -> Path:
    directory = root / "project"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "brief.md").write_text("a riser block", encoding="utf-8")
    if source is not None:
        (directory / "model.py").write_text(textwrap.dedent(source), encoding="utf-8")
    project.save(directory)
    return directory


class SourceApiTest(unittest.TestCase):
    def _load(self, source: str, root: Path):
        path = root / "model.py"
        path.write_text(textwrap.dedent(source), encoding="utf-8")
        return A.load(path, known_kinds=CM.KNOWN_CHECKS)

    def test_a_complete_model_loads_with_its_declarations(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            model, builder = self._load(RISER, Path(raw))
            self.assertEqual({"x": 40.0, "y": 30.0, "z": 14.0}, model.bbox_mm)
            self.assertEqual(3, len(model.expected))
            self.assertEqual([6.0], model.profile_marks["z"])
            self.assertEqual(10656.0, model.volume_mm3)
            self.assertEqual("authored", model.backend)
            self.assertIsNone(model.domain_id,
                              "an authored model has no certified domain, and "
                              "claiming one would sell an assurance nobody produced")
            self.assertTrue(callable(builder))

    def test_every_required_declaration_is_required(self) -> None:
        """Renaming a declaration leaves valid Python that declares nothing."""
        for name in A.REQUIRED:
            with self.subTest(missing=name), tempfile.TemporaryDirectory() as raw:
                renamed = textwrap.dedent(RISER).replace(f"{name} = ", f"_NOT_{name} = ")
                with self.assertRaises(A.ModelError) as caught:
                    self._load(renamed, Path(raw))
                self.assertIn(name, str(caught.exception))

    def test_an_empty_expectation_list_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = textwrap.dedent(RISER).replace(
                "EXPECTED = [", "EXPECTED = []\n_UNUSED = [")
            with self.assertRaises(A.ModelError) as caught:
                self._load(source, Path(raw))
            self.assertIn("cannot fail", str(caught.exception))

    def test_a_kind_no_check_implements_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = textwrap.dedent(RISER).replace('"kind": "bed_contact"',
                                                    '"kind": "vibes"')
            with self.assertRaises(A.ModelError) as caught:
                self._load(source, Path(raw))
            self.assertIn("vibes", str(caught.exception))

    def test_a_duplicate_feature_id_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = textwrap.dedent(RISER).replace('"pad-section"', '"base-section"')
            with self.assertRaises(A.ModelError) as caught:
                self._load(source, Path(raw))
            self.assertIn("duplicate", str(caught.exception))

    def test_a_non_finite_declaration_is_refused_before_anything_is_built(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = textwrap.dedent(RISER).replace(
                'BBOX_MM = {"x": 40.0', 'BBOX_MM = {"x": float("nan")')
            with self.assertRaises(A.ModelError):
                self._load(source, Path(raw))

    def test_a_model_that_raises_on_import_is_a_finding_not_a_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(A.ModelError) as caught:
                self._load("raise RuntimeError('the designer left a stub')", Path(raw))
            self.assertIn("the designer left a stub", str(caught.exception))


class CustomLaneTest(unittest.TestCase):
    def test_a_custom_part_reaches_the_same_receipts_as_a_certified_one(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER, _project())
            code = cli.run([str(directory), "--no-render"])

            report = json.loads(
                (directory / "commission_report.json").read_text(encoding="utf-8"))
            self.assertEqual("PASS", report["verdict"], report["checks"])
            self.assertEqual("CLEAR", report["screening"]["overall"])
            final = json.loads(
                (directory / "final_status.json").read_text(encoding="utf-8"))
            self.assertEqual("CUSTOM", final["route"])
            self.assertEqual("PASS", final["commission_verdict"])
            self.assertEqual(ST.FROZEN_ARTIFACTS["DIRECT"] | {"final_status"},
                             ST.FROZEN_ARTIFACTS["DIRECT"])
            # Same frozen reason DIRECT stops here: the broad screen is
            # uncalibrated and this job did not require an independent look.
            self.assertEqual(cli.NEEDS_ACTION, code)
            self.assertEqual("NEEDS_MORE_EVIDENCE", final["final_status"])

    def test_an_unrelated_custom_part_on_the_other_kernel_works_too(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), WASHER, _project(
                job_id="washer", envelope_mm={"x": 30.0, "y": 30.0, "z": 4.0},
                consequence_rationale="a spacer washer under a desk foot"))
            cli.run([str(directory), "--no-render"])
            report = json.loads(
                (directory / "commission_report.json").read_text(encoding="utf-8"))
            self.assertEqual("PASS", report["verdict"], report["checks"])
            artifact = json.loads(
                (directory / "artifact_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("authored", artifact["backend"])
            self.assertIn("build123d", artifact["backend_version"])
            self.assertEqual("n/a (B-rep)", artifact["boolean_engine"])

    def test_the_contract_binds_the_module_that_was_built(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER, _project())
            cli.run([str(directory), "--no-render"])
            first = json.loads(
                (directory / "model_contract.json").read_text(encoding="utf-8"))
            self.assertEqual("authored", first["source"]["kind"])
            self.assertEqual("model.py", first["source"]["module"])

            (directory / "model.py").write_text(
                textwrap.dedent(RISER) + "\n# a comment the designer added\n",
                encoding="utf-8")
            cli.run([str(directory), "--no-render"])
            second = json.loads(
                (directory / "model_contract.json").read_text(encoding="utf-8"))
            self.assertNotEqual(first["source"]["module_sha256"],
                                second["source"]["module_sha256"])

    def test_a_mesh_model_does_not_claim_an_engine_nobody_observed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), RISER, _project())
            cli.run([str(directory), "--no-render"])
            artifact = json.loads(
                (directory / "artifact_manifest.json").read_text(encoding="utf-8"))
            self.assertIn("unrecorded", artifact["boolean_engine"])

    def test_undeclared_profile_steps_are_screened(self) -> None:
        """Remove the declaration and the real step becomes an anomaly."""
        with tempfile.TemporaryDirectory() as raw:
            source = textwrap.dedent(RISER).replace(
                'PROFILE_MARKS = {"z": [6.0]}', 'PROFILE_MARKS = {"z": []}')
            directory = _laid_out(Path(raw), source, _project())
            cli.run([str(directory), "--no-render"])
            report = json.loads(
                (directory / "commission_report.json").read_text(encoding="utf-8"))
            self.assertEqual("ANOMALY", report["screening"]["overall"])


class PrintPlanTest(unittest.TestCase):
    def test_the_plan_is_written_before_the_model_and_names_its_own_owner(self) -> None:
        """A plan the designer never sees is the only kind that gates it."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), None, _project())
            code = cli.run([str(directory), "--no-render"])
            self.assertEqual(cli.NEEDS_ACTION, code)
            self.assertFalse((directory / "model.py").is_file())
            plan = json.loads(
                (directory / cli.PLAN_FILE).read_text(encoding="utf-8"))
            self.assertEqual("builtin-direct-template", plan["owner"])

            action = json.loads(
                (directory / cli.NEXT_ACTION_FILE).read_text(encoding="utf-8"))
            self.assertEqual("designer", action["role"])
            self.assertIn(cli.PLAN_FILE, action["authorized_inputs"])
            self.assertIn("PARAMS", action["source_api"])
            self.assertTrue(action["bound"]["print_plan_sha256"])

    def test_the_support_ceiling_is_a_contract_feature_and_it_bites(self) -> None:
        """The rule four archived runs set after reading their own measurement.

        The mushroom is a 40x30 cap on an 8 mm post: most of the cap's underside
        faces the bed with nothing beneath it. Every declared expectation passes
        -- the sections and the footprint are exactly the closed form -- so this
        is the plan catching what the model's own arithmetic cannot.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), MUSHROOM, _project(job_id="mushroom"))
            code = cli.run([str(directory), "--no-render"])
            report = json.loads(
                (directory / "commission_report.json").read_text(encoding="utf-8"))
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
            action = json.loads(
                (directory / cli.NEXT_ACTION_FILE).read_text(encoding="utf-8"))
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
            action = json.loads(
                (directory / cli.NEXT_ACTION_FILE).read_text(encoding="utf-8"))
            self.assertEqual("safety", action["review_kind"])


if __name__ == "__main__":
    unittest.main()
