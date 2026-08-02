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

The half of this file the commit gate will not carry is in
`benchmarks/heavy/test_phase2_heavy.py`, and runs before merge instead of on
every push: `AcceptanceIsUpstreamTest`,
`CandidateCannotWidenItsOwnToleranceTest`, `CustomLaneTest`, `PrintPlanTest`,
`ReviewPolicyTest`, `RevisionTest`, `ScreeningPolicyTest`. Same tests, moved
rather than weakened; `conftest.py` carries the rule and
`benchmarks/heavy/README.md` the measurement behind it.
"""
from __future__ import annotations

import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from . import acceptance as ACC
from . import authored as A
from . import project as P

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


if __name__ == "__main__":
    unittest.main()
