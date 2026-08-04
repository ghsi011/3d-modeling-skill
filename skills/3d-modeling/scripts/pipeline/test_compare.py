#!/usr/bin/env python3
"""Release 4 slice 1: what setting two formulations beside each other proves.

Every test here fails on the code as it stood before `pipeline/compare.py`,
and the four that matter fail for four different reasons. They are worth
listing, because "print the receipts side by side" reads like a formatting
change and it is not:

* **a formulation is graded against a rubric it wrote itself.** On the authored
  lane the proposal sets the declared feature set, `expected_bbox_mm`,
  `expected_bodies` and -- through the declared magnitude -- each feature's
  tolerance band. So `envelope PASS` beside `envelope PASS` can be two answers
  to two different questions, and printing them adjacent asserts an equality
  nobody measured. This is `docs/defects.md` D25, and its three faces are three
  tests here;
* **coverage is a ratio to a denominator each formulation chose** (D24). Three
  of three and eight of eight both score 1.0, so the number cannot be compared
  and must not be printed as though it could;
* **a mandatory failure and a preference criterion are different registers.**
  `ARCHITECTURE.md` 8.5 forbids a weighted total hiding the first behind the
  second; there is no total here, and the test that keeps it that way asserts a
  FAILED formulation is never reported as preferable however good its numbers;
* **a comparison that omits what it cannot measure is worse than none.** On a
  `MODIFY` pair the entire finding is that preservation cannot be measured, and
  a comparison that reported the axes it *could* reach as though they were the
  question would be a false equivalence with a receipt.

No test here builds geometry. Every formulation is laid down as the receipts a
run would have written, which is what `compare` reads and all it reads -- so
this file is L0 on every platform, including the ones where the confined build
boundary cannot run at all.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from . import bindings as B
from . import cli
from . import compare as CMP
from . import project as P
from . import schemas as S
from . import screening as SCR

UTC = "1970-01-01T00:00:00Z"

# One feature row, and the two numbers a comparison turns on: the id, which
# decides whether two formulations declared the same obligation, and the
# expectation, which decides whether their two PASSes mean the same thing.
GRIP = {"feature_id": "grip-section", "kind": "section_area",
        "expectation": {"at": {"z": 5.0}, "value_mm2": 1134.11},
        "tolerance": {"abs": 5.67}}
BORE = {"feature_id": "bore-wall-section", "kind": "section_area",
        "expectation": {"at": {"z": 8.0}, "value_mm2": 881.33},
        "tolerance": {"abs": 4.41}}
CROWN = {"feature_id": "crown-footprint", "kind": "bed_contact",
         "expectation": {"value_mm2": 1134.11}, "tolerance": {"abs": 5.67}}


def _feature(row: dict) -> dict:
    """A contract feature row as `contract.Feature.as_dict` writes one."""
    return {"feature_id": row["feature_id"], "kind": row["kind"],
            "provenance": "declared in the frozen design proposal",
            "expectation": dict(row["expectation"]),
            "tolerance": dict(row["tolerance"]),
            "verified_by": row["kind"], "on_unrunnable": "ESCALATE",
            "mandatory": True}


def _project(root: Path, **over) -> P.Project:
    base = dict(
        job_id="comparing", updated_utc=UTC, source_mode="NEW",
        consequence="INCONSEQUENTIAL",
        consequence_rationale="a desk part; failure wastes material",
        printer="Test Printer", material={"process": "FDM", "material": "PLA"},
        nozzle={"diameter_mm": 0.4},
        orientation={"model_to_printer_matrix": "identity", "bed_z_mm": 0.0},
        template=None, parameters={}, model="model.py",
        envelope_mm={"x": 60.0, "y": 60.0, "z": 60.0},
        reviewer={"model_snapshot": "test"},
        requirements=(P.Requirement(name="engagement_length", value=36.0,
                                    unit="mm", provenance="STATED",
                                    source="user"),))
    base.update(over)
    project = P.Project(**base)
    root.mkdir(parents=True, exist_ok=True)
    (root / "brief.md").write_text("a part", encoding="utf-8")
    project.save(root)
    return project


def formulation(work_dir: Path, *, features=(GRIP, BORE, CROWN),
                bbox=(38.0, 38.0, 50.0), bodies=1, verdict="PASS",
                final_status="VERIFIED", requirement_sha256="req-shared",
                source="the model as authored", volume_mm3=47526.263,
                measured=None) -> None:
    """Lay down the receipts one finished run would have written.

    Consistent by construction: every digest a receipt records is computed from
    the file it is about, so a formulation written by this helper reads as
    current and one whose source is rewritten afterwards reads as stale. That is
    the only way to write a staleness fixture that is testing `bindings.broken`
    rather than testing a hand-typed hash.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "model.py").write_text(source, encoding="utf-8")
    (work_dir / "candidate.stl").write_text("solid candidate\nendsolid\n",
                                            encoding="utf-8")
    source_sha = S.sha256_file(work_dir / "model.py")
    stl_sha = S.sha256_file(work_dir / "candidate.stl")

    plan = {"schema_version": 1, "route": "CUSTOM", "builder": "AUTHORED"}
    (work_dir / "execution_plan.json").write_text(S.canonical_json(plan),
                                                  encoding="utf-8")
    plan_sha = S.payload_hash(plan)

    acceptance = {
        "schema_version": 1, "job_id": "comparing", "route": "CUSTOM",
        "design_id": "d1", "requirement_sha256": requirement_sha256,
        "tolerance_owner": "pipeline", "minimum_coverage": 1.0,
        "bbox_tolerance_mm": 0.5,
        "expected_bbox_mm": {"x": bbox[0], "y": bbox[1], "z": bbox[2]},
        "expected_bodies": bodies,
        "expected_artifacts": {"stl": "candidate.stl"},
        "features": [dict(row) for row in features]}
    acceptance["contract_sha256"] = S.payload_hash(acceptance)
    (work_dir / "acceptance_contract.json").write_text(
        S.canonical_json(acceptance), encoding="utf-8")

    model_contract = {
        "schema_version": 1, "job_id": "comparing", "template": "authored",
        "template_version": "1", "backend": "authored",
        "expected_bbox_mm": {"x": bbox[0], "y": bbox[1], "z": bbox[2]},
        "bbox_tolerance_mm": 0.5, "expected_bodies": bodies,
        "minimum_coverage": 1.0,
        "features": [_feature(row) for row in features],
        "source": {"acceptance_contract_sha256": acceptance["contract_sha256"]}}
    (work_dir / "model_contract.json").write_text(
        S.canonical_json(model_contract), encoding="utf-8")
    contract_sha = S.payload_hash(model_contract)

    manifest = {"schema_version": 1, "job_id": "comparing",
                "contract_sha256": contract_sha, "stl_sha256": stl_sha,
                "step_sha256": None, "source_sha256": source_sha,
                "backend": "authored", "units": "mm",
                "bbox_mm": {"x": bbox[0], "y": bbox[1], "z": bbox[2]},
                "updated_utc": UTC}
    (work_dir / "artifact_manifest.json").write_text(S.canonical_json(manifest),
                                                     encoding="utf-8")

    measured = dict(measured or {})
    checks = [
        {"check_id": "watertight", "feature_id": None, "title": "Closed solid",
         "ran": True, "reason": "measured", "expected": True, "measured": True,
         "tolerance": None, "result": "PASS", "status": "MEASURED"},
        {"check_id": "bodies", "feature_id": None, "title": "Separate solids",
         "ran": True, "reason": "measured", "expected": bodies,
         "measured": measured.get("bodies", bodies), "tolerance": None,
         "result": "PASS", "status": "MEASURED"},
        # The check the whole of D25's second face turns on: its expectation is
        # the bbox this formulation declared for itself.
        {"check_id": "envelope", "feature_id": None,
         "title": "Overall size vs contract", "ran": True, "reason": "measured",
         "expected": {"x": bbox[0], "y": bbox[1], "z": bbox[2]},
         "measured": {"x": bbox[0], "y": bbox[1], "z": bbox[2]},
         "tolerance": 0.5, "result": "PASS", "status": "MEASURED"},
    ]
    for row in features:
        checks.append({
            "check_id": f"feature-{row['feature_id']}",
            "feature_id": row["feature_id"], "title": row["feature_id"],
            "ran": True, "reason": "measured",
            "expected": row["expectation"].get("value_mm2"),
            "measured": measured.get(row["feature_id"],
                                     row["expectation"].get("value_mm2")),
            "tolerance": row["tolerance"], "result": "PASS",
            "status": "MEASURED"})
    if verdict == "FAIL":
        checks[-1] = {**checks[-1], "result": "FAIL"}

    declared = len(features)
    report = {
        "schema_version": 1, "contract_hash": contract_sha, "verdict": verdict,
        "coverage": {"covered": declared, "declared": declared,
                     "fraction": 1.0, "minimum": 1.0},
        "checks": checks,
        # A LIST, which is what `screening.run` writes. It was a mapping keyed
        # by detector name here until `docs/defects.md` D27: `compare._measured`
        # read it that way, this fixture was authored to match the reader rather
        # than the writer, and twenty-two fixtures then agreed with each other
        # and with nothing the pipeline produces.
        "screening": {"overall": "CLEAR", "calibrated": False,
                      "detectors": [{"detector": "volume",
                                     "result": "NOT_APPLICABLE",
                                     "measured_mm3": volume_mm3,
                                     "expected_mm3": None}]}}
    (work_dir / "commission_report.json").write_text(S.canonical_json(report),
                                                     encoding="utf-8")

    status = {
        "schema_version": 1, "job_id": "comparing", "route": "CUSTOM",
        "execution_plan_sha256": plan_sha, "lane_status": "AVAILABLE",
        "commission_verdict": verdict, "screening": "CLEAR",
        "screening_calibrated": False, "witnesses_rendered": False,
        "manufacturing": None, "verification": None,
        "safety_verification": None, "final_status": final_status,
        "allowed_claim": f"the run concluded {final_status}",
        "unavailable_checks": [], "reasons": [],
        "artifact_hashes": {"contract": contract_sha, "stl": stl_sha,
                            "step": None, "source": source_sha},
        "updated_utc": UTC}
    (work_dir / "final_status.json").write_text(S.canonical_json(status),
                                                encoding="utf-8")


def _branched(root: Path, *ids: str, project=None) -> Path:
    """A project with the named alternatives declared, and their directories."""
    directory = root / "project"
    project = project or _project(directory)
    for name in ids:
        assert cli.branch([str(directory), "--from", ".", "--id", name,
                           "--reason", f"the {name} concept"]) == 0
    return directory


def _run(directory: Path, *args: str) -> tuple[int, dict | None]:
    code = cli.compare([str(directory), *args])
    path = directory / CMP.COMPARISON_FILE
    payload = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    return code, payload


# ---------------------------------------------------------------------------
# The rubric each formulation wrote for itself -- docs/defects.md D25
# ---------------------------------------------------------------------------

class TheRubricIsNotSharedTest(unittest.TestCase):
    """Three faces of one defect: a proposal sets what it will be graded on.

    Each of these produces two formulations that both PASS every check they
    declared. A comparison that reported "both passed" and stopped would be
    stating an equality that was never measured.
    """

    def test_different_check_sets_are_reported_incomparable_not_equal(self) -> None:
        """D24, structurally: 3-of-3 and 4-of-4 are both 1.0 and mean nothing."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _branched(Path(raw), "lean", "full")
            formulation(directory / P.ALTERNATIVES_DIR / "lean",
                        features=(GRIP, BORE))
            formulation(directory / P.ALTERNATIVES_DIR / "full",
                        features=(GRIP, BORE, CROWN))
            formulation(directory)

            code, payload = _run(directory)
            self.assertEqual(0, code)
            axis = payload["axes"]["mandatory"]

            # The finding, and the thing a fraction could never say: *which*
            # obligation one of them did not take on.
            self.assertEqual(CMP.INCOMPARABLE_CHECK_SETS, axis["verdict"])
            self.assertEqual(["bore-wall-section", "grip-section"], axis["shared"])
            self.assertEqual({"lean": []}, {"lean": axis["only_in"].get("lean", [])})
            self.assertEqual(["crown-footprint"], axis["only_in"]["full"])

            # Both scored a perfect coverage, and the report never sets the two
            # numbers against each other.
            for key in ("lean", "full"):
                own = axis["per_formulation"][key]["self_coverage"]
                self.assertEqual(1.0, own["fraction"])
            self.assertNotIn("coverage", payload)

            # And nothing anywhere prefers one.
            self.assertFalse(payload["preference"]["admissible"])
            self.assertIsNone(payload["ranking"])
            self.assertIsNone(payload["score"])

    def test_the_same_check_against_a_different_expectation_is_incomparable(self) -> None:
        """The face that fires on the recorded knob with nothing constructed.

        `benchmarks/replays/branch-knob-seat-fallback`: the root declares
        `bbox_mm.z = 50.0` and `plate-seated` declares `52.0`, both are checked
        against their own declaration to a band of 0.5, and both PASS. Same
        check id, same tolerance, two different questions.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _branched(Path(raw), "as-drawn", "plate-seated")
            formulation(directory / P.ALTERNATIVES_DIR / "as-drawn",
                        bbox=(38.0, 38.0, 50.0))
            formulation(directory / P.ALTERNATIVES_DIR / "plate-seated",
                        bbox=(38.0, 38.0, 52.0))
            formulation(directory, bbox=(38.0, 38.0, 50.0))

            code, payload = _run(directory)
            self.assertEqual(0, code)
            axis = payload["axes"]["mandatory"]

            self.assertEqual(CMP.INCOMPARABLE_EXPECTATIONS, axis["verdict"])
            # The check sets agree. It is the yardstick that does not.
            self.assertEqual({}, axis["only_in"])
            self.assertIn("envelope", axis["expectations"])
            envelope = axis["expectations"]["envelope"]
            self.assertEqual(50.0, envelope["expected"]["as-drawn"]["z"])
            self.assertEqual(52.0, envelope["expected"]["plate-seated"]["z"])
            self.assertEqual({"as-drawn": "PASS", "plate-seated": "PASS", ".": "PASS"},
                             envelope["result"])
            self.assertFalse(payload["preference"]["admissible"])

    def test_a_looser_band_bought_by_declaring_a_bigger_number_is_reported(self) -> None:
        """A feature's band is 0.5% of the magnitude its proposal declared.

        `contract.area_tolerance`. So a formulation declaring 1134.11 mm2 is
        graded to +/-5.67 and one declaring 881.33 mm2 to +/-4.41 -- and the
        first bought the looser band by declaring the bigger number. Two PASSes
        against two bands are not one result.
        """
        wide = {**GRIP, "expectation": {"at": {"z": 5.0}, "value_mm2": 2000.0},
                "tolerance": {"abs": 10.0}}
        with tempfile.TemporaryDirectory() as raw:
            directory = _branched(Path(raw), "tight", "loose")
            formulation(directory / P.ALTERNATIVES_DIR / "tight",
                        features=(GRIP, BORE))
            formulation(directory / P.ALTERNATIVES_DIR / "loose",
                        features=(wide, BORE))
            formulation(directory, features=(GRIP, BORE))

            _, payload = _run(directory)
            axis = payload["axes"]["mandatory"]
            self.assertEqual(CMP.INCOMPARABLE_EXPECTATIONS, axis["verdict"])
            row = axis["expectations"]["feature-grip-section"]
            self.assertEqual({"abs": 5.67}, row["tolerance"]["tight"])
            self.assertEqual({"abs": 10.0}, row["tolerance"]["loose"])

    def test_two_bands_over_one_expectation_are_incomparable(self) -> None:
        """The band alone, isolated from the value it is usually derived from.

        On the authored lane a proposal may not declare a band at all
        (`acceptance.py:246`) and the pipeline computes it from the declared
        magnitude, so equal expectations imply equal bands *today*. Plan and
        preservation rows supply their own (`cli.py:1069`, `:1153`), and a
        contract row that states a band keeps it (`runner.py:755-759`) -- so the
        two are separate questions, and this asserts the second one is actually
        being asked rather than riding on the first.
        """
        relaxed = {**BORE, "tolerance": {"abs": 40.0}}
        with tempfile.TemporaryDirectory() as raw:
            directory = _branched(Path(raw), "tight", "relaxed")
            formulation(directory / P.ALTERNATIVES_DIR / "tight",
                        features=(GRIP, BORE))
            formulation(directory / P.ALTERNATIVES_DIR / "relaxed",
                        features=(GRIP, relaxed))
            formulation(directory, features=(GRIP, BORE))

            _, payload = _run(directory)
            axis = payload["axes"]["mandatory"]
            self.assertEqual(CMP.INCOMPARABLE_EXPECTATIONS, axis["verdict"])
            row = axis["expectations"]["feature-bore-wall-section"]
            # The two were measured against the same expectation. Only the
            # width of the gate around it moved. Asserted against the *contract's*
            # own shape -- the whole expectation dict -- because that is what the
            # comparand reads now: an independent review found the previous
            # comparand (the check's projected `expected`) dropped the probe
            # height into the check title, so two formulations measuring
            # different sections of different parts compared equal.
            self.assertEqual(BORE["expectation"], row["expected"]["tight"])
            self.assertEqual(BORE["expectation"], row["expected"]["relaxed"])
            self.assertEqual({"abs": 4.41}, row["tolerance"]["tight"])
            self.assertEqual({"abs": 40.0}, row["tolerance"]["relaxed"])

    def test_one_rubric_reports_comparable(self) -> None:
        """The mechanism has to be able to say yes, or it says nothing."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _branched(Path(raw), "a", "b")
            for name in ("a", "b"):
                formulation(directory / P.ALTERNATIVES_DIR / name)
            formulation(directory)

            _, payload = _run(directory)
            axis = payload["axes"]["mandatory"]
            self.assertEqual(CMP.COMPARABLE, axis["verdict"])
            self.assertEqual({}, axis["expectations"])
            self.assertEqual({}, axis["only_in"])
            self.assertTrue(payload["preference"]["admissible"])


# ---------------------------------------------------------------------------
# A mandatory failure is not a preference criterion -- ARCHITECTURE.md 8.5
# ---------------------------------------------------------------------------

class AMandatoryFailureOutweighsNothingTest(unittest.TestCase):

    def test_a_failed_formulation_is_never_reported_preferable(self) -> None:
        """However good its material and cost numbers are."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _branched(Path(raw), "cheap", "sound")
            # The failing one is better on every measured axis there is.
            formulation(directory / P.ALTERNATIVES_DIR / "cheap",
                        verdict="FAIL", final_status="FAILED",
                        volume_mm3=1000.0)
            formulation(directory / P.ALTERNATIVES_DIR / "sound",
                        volume_mm3=90000.0)
            formulation(directory)

            _, payload = _run(directory)
            self.assertEqual(
                "FAIL",
                payload["axes"]["mandatory"]["per_formulation"]["cheap"]["verdict"])
            self.assertFalse(payload["preference"]["admissible"])
            self.assertIn("cheap", payload["preference"]["because"])
            # The measurement is still reported -- withholding a number somebody
            # took would be its own dishonesty -- and it is not a reason.
            measured = payload["axes"]["measured"]["per_formulation"]
            self.assertEqual(1000.0, measured["cheap"]["volume_mm3"])
            self.assertEqual(90000.0, measured["sound"]["volume_mm3"])

    def test_the_mandatory_row_moves_when_the_verdict_does(self) -> None:
        """The mutation: flip one commission verdict, assert the report follows.

        A protection that reports the same thing whatever the receipt says is
        not a protection, and this is the cheapest way to show this one is
        reading rather than asserting.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _branched(Path(raw), "one", "two")
            for name in ("one", "two"):
                formulation(directory / P.ALTERNATIVES_DIR / name)
            formulation(directory)

            _, before = _run(directory)
            self.assertTrue(before["preference"]["admissible"])
            self.assertEqual(
                "PASS",
                before["axes"]["mandatory"]["per_formulation"]["one"]["verdict"])

            # Exactly one byte of meaning changes: the stored verdict.
            report = directory / P.ALTERNATIVES_DIR / "one" / "commission_report.json"
            payload = json.loads(report.read_text(encoding="utf-8"))
            payload["verdict"] = "FAIL"
            report.write_text(S.canonical_json(payload), encoding="utf-8")

            _, after = _run(directory)
            self.assertEqual(
                "FAIL",
                after["axes"]["mandatory"]["per_formulation"]["one"]["verdict"])
            self.assertFalse(after["preference"]["admissible"])


# ---------------------------------------------------------------------------
# Absent, not zero -- ARCHITECTURE.md 6.14
# ---------------------------------------------------------------------------

class CriteriaAJobDoesNotExerciseAreAbsentTest(unittest.TestCase):

    def test_a_single_material_one_piece_pair_emits_no_assembly_rows(self) -> None:
        """Absent, not zero, and not "1 vs 1"."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _branched(Path(raw), "a", "b")
            for name in ("a", "b"):
                formulation(directory / P.ALTERNATIVES_DIR / name, bodies=1)
            formulation(directory, bodies=1)

            _, payload = _run(directory)
            dimensions = " ".join(row["dimension"] for row in payload["not_compared"])
            for absent in ("assembly", "tooling", "hardware", "material count",
                           "sequence"):
                self.assertNotIn(absent, dimensions,
                                 f"{absent!r} is not a dimension a one-piece "
                                 "single-material pair exercises, so it may not "
                                 "appear at all -- 6.14")
            # And the rows that are always true of two solids are there.
            self.assertIn("geometric difference between formulations", dimensions)
            self.assertIn("print time", dimensions)

    def test_a_multi_body_pair_does_emit_them(self) -> None:
        """The guard is a predicate over the job, not a permanent silence."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _branched(Path(raw), "a", "b")
            for name in ("a", "b"):
                formulation(directory / P.ALTERNATIVES_DIR / name, bodies=3)
            formulation(directory, bodies=3)

            _, payload = _run(directory)
            rows = {row["dimension"]: row for row in payload["not_compared"]}
            assembly = [name for name in rows if "assembly" in name]
            self.assertEqual(1, len(assembly))
            self.assertEqual(CMP.DECIDING, rows[assembly[0]]["standing"])
            self.assertEqual("Release 8", rows[assembly[0]]["owner"])


# ---------------------------------------------------------------------------
# The MODIFY pair, where not_compared is the entire finding
# ---------------------------------------------------------------------------

class AModifyPairIsReportedUnrankableTest(unittest.TestCase):
    """Two modifications compared today discriminate nothing, and say so.

    This is the test that stops the `not_compared` block being decorative. The
    scoping for this slice proposed deferring `MODIFY` pairs on the grounds that
    a comparison of them settles nothing; the answer taken instead is that
    settling nothing *is* the correct output, provided the comparison says which
    axis it could not reach and refuses preference on those grounds. Without
    this test that is a sentence in a document; with it, it is a mechanism.
    """

    def test_preservation_is_named_and_preference_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            directory = root / "project"
            _project(directory, source_mode="MODIFY")
            for name in ("flat", "chamfered"):
                self.assertEqual(0, cli.branch(
                    [str(directory), "--from", ".", "--id", name,
                     "--reason", f"the {name} edit"]))
                formulation(directory / P.ALTERNATIVES_DIR / name,
                            final_status="EXPERIMENTAL_UNAVAILABLE")
            formulation(directory, final_status="EXPERIMENTAL_UNAVAILABLE")

            _, payload = _run(directory)
            rows = {row["dimension"]: row for row in payload["not_compared"]}
            preservation = [name for name in rows if "preservation" in name]
            self.assertEqual(1, len(preservation),
                             "a MODIFY job's comparison must name preservation")
            row = rows[preservation[0]]
            self.assertEqual(CMP.DECIDING, row["standing"])
            self.assertEqual("Release 6", row["owner"])
            self.assertIn("D22", row["reason"])

            # Every other axis may be equal and the comparison still settles
            # nothing. That is the sentence, and it has to be in the file.
            self.assertFalse(payload["preference"]["admissible"])
            self.assertIn("preservation", payload["preference"]["because"])


# ---------------------------------------------------------------------------
# Unequal evidence -- ARCHITECTURE.md 14.7
# ---------------------------------------------------------------------------

class UnequalEvidenceIsTheFindingTest(unittest.TestCase):

    def test_a_stale_formulation_is_reported_stale_not_by_its_stored_verdict(self) -> None:
        """The receipt says VERIFIED; the files it was issued against moved."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _branched(Path(raw), "current", "moved")
            for name in ("current", "moved"):
                formulation(directory / P.ALTERNATIVES_DIR / name)
            formulation(directory)

            # After it concluded, never before: the point is a verdict reached
            # against one version of an input and read afterwards against
            # another.
            (directory / P.ALTERNATIVES_DIR / "moved" / "model.py").write_text(
                "the model as revised", encoding="utf-8")

            _, payload = _run(directory)
            claim = payload["axes"]["claim"]["per_formulation"]
            self.assertEqual("STALE", claim["moved"]["status"])
            self.assertEqual("VERIFIED", claim["moved"]["stored_status"])
            # The claim string is withheld while it is not current, and the
            # stored one is kept under its own name. A claim printed beside a
            # STALE status is the exact sentence a reader would quote.
            self.assertIsNone(claim["moved"]["allowed_claim"])
            self.assertIsNotNone(claim["moved"]["stored_claim"])
            self.assertEqual("VERIFIED", claim["current"]["status"])
            self.assertIsNotNone(claim["current"]["allowed_claim"])

            self.assertEqual(
                CMP.MANDATORY_UNKNOWN_STALE,
                payload["axes"]["mandatory"]["per_formulation"]["moved"]["verdict"])
            self.assertFalse(payload["preference"]["admissible"])
            self.assertIn("final_status.json",
                          payload["axes"]["evidence"]["per_formulation"]["moved"]
                          ["stale_receipts"])

    def test_a_formulation_that_never_ran_is_not_the_least_demanding_one(self) -> None:
        """No contract on disk is unequal evidence, not a small contract."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _branched(Path(raw), "built", "empty")
            formulation(directory / P.ALTERNATIVES_DIR / "built")
            formulation(directory)

            _, payload = _run(directory)
            axis = payload["axes"]["mandatory"]
            self.assertEqual(["empty"], axis["no_contract_on_disk"])
            self.assertIsNone(axis["per_formulation"]["empty"]["declared_checks"])
            self.assertEqual(CMP.MANDATORY_NOT_RUN,
                             axis["per_formulation"]["empty"]["verdict"])
            self.assertFalse(payload["preference"]["admissible"])

    def test_a_declared_check_that_did_not_run_is_not_an_undeclared_one(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _branched(Path(raw), "a", "b")
            for name in ("a", "b"):
                formulation(directory / P.ALTERNATIVES_DIR / name)
            formulation(directory)

            report = directory / P.ALTERNATIVES_DIR / "a" / "commission_report.json"
            payload = json.loads(report.read_text(encoding="utf-8"))
            for row in payload["checks"]:
                if row["check_id"] == "feature-crown-footprint":
                    row.update(ran=False, measured=None, status="UNAVAILABLE",
                               result="ESCALATE", error_code="NO_PLACEMENT")
            report.write_text(S.canonical_json(payload), encoding="utf-8")

            _, out = _run(directory)
            own = out["axes"]["mandatory"]["per_formulation"]["a"]
            # Still declared -- the contract is what declares -- and named as
            # unmeasured. A comparison that read the report alone would have
            # seen a formulation with one obligation fewer.
            self.assertIn("crown-footprint", own["declared_checks"])
            self.assertEqual(["feature-crown-footprint"], own["did_not_run"])
            self.assertEqual({}, out["axes"]["mandatory"]["only_in"])


# ---------------------------------------------------------------------------
# What the command refuses, and what it never does
# ---------------------------------------------------------------------------

class TheCommandSurfaceTest(unittest.TestCase):

    def test_one_formulation_is_refused_rather_than_compared_with_itself(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw) / "project"
            _project(directory)
            formulation(directory)
            self.assertEqual(2, cli.compare([str(directory)]))
            self.assertFalse((directory / CMP.COMPARISON_FILE).exists())

    def test_the_shared_root_is_one_of_the_formulations(self) -> None:
        """`status`'s alternatives table drops it; a comparison may not.

        `branch` never writes a row for the root, so a set taken from
        `project.alternatives` is one short on every branched job. See
        `docs/defects.md` D26.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _branched(Path(raw), "sibling")
            formulation(directory / P.ALTERNATIVES_DIR / "sibling")
            formulation(directory)

            _, payload = _run(directory)
            self.assertEqual([".", "sibling"], payload["compared"])

    def test_a_concluded_formulation_is_not_compared_but_stays_nameable(self) -> None:
        """6.14 keeps a rejected alternative available; it is not the default."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _branched(Path(raw), "kept", "dropped")
            for name in ("kept", "dropped"):
                formulation(directory / P.ALTERNATIVES_DIR / name)
            formulation(directory)
            self.assertEqual(0, cli.branch(
                [str(directory), "--disposition", "REJECTED", "--of", "dropped",
                 "--basis", "USER_SELECTION"]))

            _, payload = _run(directory)
            self.assertEqual([".", "kept"], payload["compared"])

            _, named = _run(directory, "--against", "kept,dropped")
            self.assertEqual(["dropped", "kept"], named["compared"])

    def test_it_builds_nothing_and_changes_nothing_but_its_own_report(self) -> None:
        """Zero dispatch and zero build, asserted as bytes rather than claimed."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _branched(Path(raw), "a", "b")
            for name in ("a", "b"):
                formulation(directory / P.ALTERNATIVES_DIR / name)
            formulation(directory)

            before = {path.relative_to(directory).as_posix(): S.sha256_file(path)
                      for path in sorted(directory.rglob("*")) if path.is_file()}
            self.assertEqual(0, cli.compare([str(directory)]))
            after = {path.relative_to(directory).as_posix(): S.sha256_file(path)
                     for path in sorted(directory.rglob("*")) if path.is_file()}

            self.assertEqual({CMP.COMPARISON_FILE}, set(after) - set(before))
            self.assertEqual(before, {name: digest for name, digest in after.items()
                                      if name != CMP.COMPARISON_FILE})

    def test_it_is_recomputable_and_says_what_it_was_issued_against(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _branched(Path(raw), "a", "b")
            for name in ("a", "b"):
                formulation(directory / P.ALTERNATIVES_DIR / name)
            formulation(directory)

            _, first = _run(directory)
            _, again = _run(directory)
            self.assertEqual(first, again, "a comparison over unchanged receipts "
                                           "is the same comparison")

            for key in first["compared"]:
                issued = first["issued_against"][key]
                # The identity covers inputs; a corrected receipt would move the
                # comparison with no binding broken, which is why the receipt
                # digests are here too.
                self.assertEqual(
                    B.run_id(directory if key == "." else
                             directory / P.ALTERNATIVES_DIR / key,
                             alternative_id=None if key == "." else key,
                             model_name="model.py"),
                    issued["run_id"])
                self.assertEqual(set(CMP.READS), set(issued["receipts"]))
                self.assertTrue(all(issued["receipts"].values()))

            # Two byte-identical siblings are still two runs.
            self.assertNotEqual(first["issued_against"]["a"]["run_id"],
                                first["issued_against"]["b"]["run_id"])

    def test_identical_designs_are_named_so_a_tie_is_not_read_as_agreement(self) -> None:
        """`.` and `as-drawn` on the recorded knob are one design under two ids."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _branched(Path(raw), "twin", "other")
            formulation(directory / P.ALTERNATIVES_DIR / "twin",
                        source="the model as authored")
            formulation(directory / P.ALTERNATIVES_DIR / "other",
                        source="a materially different model")
            formulation(directory, source="the model as authored")

            _, payload = _run(directory)
            groups = payload["identical_designs"]
            self.assertEqual(1, len(groups))
            self.assertEqual([".", "twin"], groups[0]["members"])
            self.assertIn("corroboration", groups[0]["note"])


# ---------------------------------------------------------------------------
# The sentence most easily lost
# ---------------------------------------------------------------------------

class TheRequirementDigestIsABindingNotASatisfactionTest(unittest.TestCase):

    def test_the_shared_digest_is_reported_as_a_binding(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _branched(Path(raw), "a", "b")
            for name in ("a", "b"):
                formulation(directory / P.ALTERNATIVES_DIR / name)
            formulation(directory)

            _, payload = _run(directory)
            shared = payload["shared"]
            self.assertTrue(shared["same_requirement_digest"])
            self.assertEqual("req-shared", shared["requirement_digest"])
            # The words that keep the two sentences apart. If this drifts into
            # claiming the requirement was met, the comparison has overclaimed.
            self.assertIn("not 'all of them meet the requirement'",
                          shared["what_that_means"])
            self.assertIn("never individually measured", shared["what_that_means"])

    def test_formulations_frozen_against_different_job_states_are_named(self) -> None:
        """A digest that differs means the shared half of the job moved."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _branched(Path(raw), "before", "after")
            formulation(directory / P.ALTERNATIVES_DIR / "before",
                        requirement_sha256="req-old")
            formulation(directory / P.ALTERNATIVES_DIR / "after",
                        requirement_sha256="req-new")
            formulation(directory)

            _, payload = _run(directory)
            self.assertFalse(payload["shared"]["same_requirement_digest"])
            self.assertIsNone(payload["shared"]["requirement_digest"])
            self.assertEqual("req-old",
                             payload["shared"]["per_formulation"]["before"])


# ---------------------------------------------------------------------------
# D27: the fixtures agreed with the reader instead of with the writer
# ---------------------------------------------------------------------------

class TheMaterialAxisReadsTheShapeARunWritesTest(unittest.TestCase):
    """`screening.detectors` is a list, and this module read it as a mapping.

    Nothing caught it. Every fixture in this file was authored against the
    reader, so twenty-two of them agreed with each other and with no receipt any
    run has produced; `compare` raised `AttributeError` the first time it was
    pointed at the recorded knob. The L1 replay is the protection that would
    have caught it and now does, because it runs the verb against receipts a
    real pipeline wrote. These are the L0 half.
    """

    def _report(self, detectors) -> dict:
        return {"screening": {"overall": "CLEAR", "detectors": detectors}}

    def test_the_measurement_is_found_in_the_shape_screening_writes(self) -> None:
        row = SCR.detector(
            self._report([{"detector": "profile-z", "result": "NOT_APPLICABLE"},
                          {"detector": "volume", "result": "NOT_APPLICABLE",
                           "measured_mm3": 47526.263}]),
            "volume")
        self.assertEqual(47526.263, row["measured_mm3"])

    def test_the_shape_the_fixtures_invented_is_refused_and_not_shrugged_off(self) -> None:
        """Loud, because quiet is what made this survive.

        A reader returning `None` here would have reported "no volume measured"
        on every job forever, and that is a sentence nobody thinks to doubt.
        """
        with self.assertRaises(SCR.ScreeningShapeUnexpected) as caught:
            SCR.detector(
                self._report({"volume": {"detector": "volume",
                                         "measured_mm3": 47526.263}}),
                "volume")
        self.assertIn("list of rows", str(caught.exception))

    def test_a_detector_that_did_not_run_is_absent_not_an_error(self) -> None:
        report = self._report([{"detector": "volume", "result": "CLEAR"}])
        self.assertIsNone(SCR.detector(report, "components"))
        self.assertIsNone(SCR.detector({}, "volume"))

    def test_the_comparison_carries_the_volume_off_a_real_shaped_receipt(self) -> None:
        """End to end through `report`, which is where the crash was."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _branched(Path(raw), "a", "b")
            formulation(directory / P.ALTERNATIVES_DIR / "a", volume_mm3=47526.263)
            formulation(directory / P.ALTERNATIVES_DIR / "b", volume_mm3=49792.874)
            formulation(directory, volume_mm3=47526.263)

            _, payload = _run(directory)
            measured = payload["axes"]["measured"]["per_formulation"]
            self.assertEqual(47526.263, measured["a"]["volume_mm3"])
            self.assertEqual(49792.874, measured["b"]["volume_mm3"])
            self.assertEqual("NOT_APPLICABLE", measured["a"]["volume_detector"])


if __name__ == "__main__":
    unittest.main()
