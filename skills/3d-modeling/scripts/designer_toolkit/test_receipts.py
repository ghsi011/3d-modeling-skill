"""Tests for the derived handoff receipts.

The property under test is that the receipt describes the mesh actually being
shipped. One archived run's hand-written receipt described a mesh that was no
longer the one on disk, which is the failure re-typing these numbers invites.

The half of this file the commit gate will not carry is in
`benchmarks/heavy/test_receipts_heavy.py`, and runs before merge instead of on
every push: `CliTest`. Same tests, moved rather than weakened; `conftest.py`
carries the rule and `benchmarks/heavy/README.md` the measurement behind it.
"""

import sys
import tempfile
import unittest
from pathlib import Path

import trimesh

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from designer_toolkit import commission, plan, receipts  # noqa: E402

_WHEN = "2026-01-01T00:00:00Z"


def _seated_box(path: Path, extents) -> Path:
    """A box resting on the bed, which is how a DIRECT part is authored.

    `trimesh.creation.box` centres on the origin, so an unseated one hangs half
    below z=0 and every downward face reads as unsupported -- correctly, since
    the template declares an identity model-to-printer transform.
    """
    box = trimesh.creation.box(extents=extents)
    box.apply_translation((0.0, 0.0, extents[2] / 2.0))
    box.export(path)
    return path


def _run(work: Path, extents=(30.0, 20.0, 10.0)):
    stl = _seated_box(work / "box.stl", extents)
    built = plan.direct_template(extents, job_id="t")
    return commission.run(model=None, stl=stl, out_dir=work / "out",
                          plan=built, render=False).as_dict()


class InPlaceTest(unittest.TestCase):
    def test_verifying_a_delivered_stl_does_not_duplicate_it(self) -> None:
        """The charter forbids copying a canonical STL into a verifier folder,
        and the gate's own export step was the thing copying it -- a verifier
        had to notice the duplicate and delete it."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            stl = _seated_box(work / "delivered.stl", (30.0, 20.0, 10.0))
            out = work / "verify"

            commission.run(model=None, stl=stl, out_dir=out,
                           plan=plan.direct_template((30.0, 20.0, 10.0)), render=False)

            copies = [p.name for p in out.glob("*.stl")]
            self.assertEqual([], copies, "the delivered STL must be measured where it lies")
            self.assertTrue((out / "commission.json").is_file())


class MultiPartTest(unittest.TestCase):
    def test_two_parts_in_one_directory_do_not_overwrite_each_other(self) -> None:
        """A multi-plate job commissions several parts. The export stem was a
        fixed `candidate_01`, so the fifth part was the only one left."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            out = work / "out"
            for name, extents in (("body", (30.0, 20.0, 10.0)), ("lid", (30.0, 20.0, 4.0))):
                stl = _seated_box(work / f"{name}_src.stl", extents)
                commission.run(model=None, stl=stl, out_dir=out, candidate_id=name,
                               plan=plan.direct_template(extents), render=False)

            self.assertTrue((work / "body_src.stl").is_file())
            self.assertTrue((work / "lid_src.stl").is_file())
            self.assertTrue((out / "commission.json").is_file())


class MatingReferenceTest(unittest.TestCase):
    def test_the_reference_the_fit_was_measured_against_is_hashed(self) -> None:
        """A FITTED run hand-added this row. The gate was handed the file and
        measured the clearance against it; a reference nothing hashes can drift
        from the one the number came from."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            ref = _seated_box(work / "mating_reference.stl", (20.0, 20.0, 20.0))
            outer = trimesh.creation.box(extents=(30.0, 30.0, 30.0))
            outer.apply_translation((0.0, 0.0, 15.0))
            cavity = trimesh.creation.box(extents=(20.6, 20.6, 40.0))
            cavity.apply_translation((0.0, 0.0, 20.0))
            stl = work / "shell.stl"
            trimesh.boolean.difference([outer, cavity]).export(stl)

            built = plan.direct_template((30.0, 30.0, 30.0))
            built["interfaces"] = [{"id": "I-01", "fit_type": "clearance",
                                    "min_mm": 0.20, "max_mm": 0.45}]
            result = commission.run(model=None, stl=stl, out_dir=work / "out",
                                    plan=built, reference=str(ref), render=False).as_dict()

            manifest = receipts.build_manifest(result, work / "out", job_id="t",
                                               updated_utc=_WHEN)

            row = next(a for a in manifest["artifacts"] if a["role"] == "mating_reference")
            self.assertEqual(receipts.sha256_file(ref), row["sha256"])
            self.assertFalse(row["printable_deliverable"],
                             "the contract rejects a mating_reference marked printable")


class ManifestTest(unittest.TestCase):
    def test_the_hash_is_of_the_file_that_exists_now(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            result = _run(work)

            manifest = receipts.build_manifest(result, work / "out", job_id="t",
                                               updated_utc=_WHEN)

            row = next(a for a in manifest["artifacts"] if a["id"] == "candidate-01")
            on_disk = receipts.sha256_file(Path(result["evidence"]["export"]["stl_path"]))
            self.assertEqual(on_disk, row["sha256"])

    def test_the_step_it_exported_is_in_the_manifest(self) -> None:
        """The .step sat on disk beside a manifest that did not mention it,
        because `finalize` re-exports without one and its export block won.
        Two measured runs shipped that; a third hand-added the row."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            result = _run(work)
            step_path = result["evidence"]["export"].get("step_path")
            if step_path is None or not Path(step_path).is_file():
                self.skipTest("no CAD kernel here, so no STEP was written")

            manifest = receipts.build_manifest(result, work / "out", job_id="t",
                                               updated_utc=_WHEN)

            self.assertTrue(any(a["type"] == "step" for a in manifest["artifacts"]),
                            manifest["artifacts"])

    def test_the_export_block_describes_the_authoritative_export(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            export = _run(Path(raw))["evidence"]["export"]

            self.assertTrue(Path(export["stl_path"]).is_file())
            self.assertEqual(64, len(export["file_sha256"]))

    def test_the_bbox_is_corners_not_extents(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            manifest = receipts.build_manifest(_run(work), work / "out", job_id="t",
                                               updated_utc=_WHEN)

            bbox = next(a for a in manifest["artifacts"] if a["id"] == "candidate-01")["bbox"]
            self.assertEqual(3, len(bbox["min"]))
            for low, high in zip(bbox["min"], bbox["max"]):
                self.assertGreater(high, low)

    def test_it_passes_the_projects_own_manifest_validator(self) -> None:
        """The whole point of deriving it: no round trip to find out it is wrong.

        Every row type is exercised, including a render. The first version of
        this test ran with rendering off, so no render row existed and it never
        noticed the emitter writing `type: "render"` -- a value absent from the
        schema's type enum, which a real run then had to hand-correct.
        """
        sys.path.insert(0, str(_SCRIPTS / "team_tools"))
        import validators  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            result = _run(work)
            out = work / "out"
            renders = out / "renders"
            renders.mkdir(parents=True, exist_ok=True)
            (renders / "section_x.png").write_bytes(b"a row to hash, not a real png")
            result["evidence"]["renders"] = ["renders/section_x.png"]

            manifest = receipts.build_manifest(result, out, job_id="t", updated_utc=_WHEN)

            self.assertTrue(any(a["role"] == "render" for a in manifest["artifacts"]),
                            manifest["artifacts"])
            for row in manifest["artifacts"]:
                self.assertIn(row["type"], validators.ARTIFACT_TYPE, row)
            issues, _ = validators.validate_artifact_manifest(manifest)

            self.assertEqual([], [i for i in issues if i.severity == "error"], issues)


class ReadinessTest(unittest.TestCase):
    def test_a_passing_commission_is_ready(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            text = receipts.build_readiness(_run(work), job_id="t", updated_utc=_WHEN)

            self.assertIn("status: READY", text)
            self.assertIn("NON-ACCEPTANCE", text)

    def test_a_failing_commission_is_not_ready_and_lists_the_action(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            # Build a box that is not the size the plan declares.
            stl = _seated_box(work / "box.stl", (30.0, 20.0, 14.0))
            built = plan.direct_template((30.0, 20.0, 10.0), job_id="t")
            result = commission.run(model=None, stl=stl, out_dir=work / "out",
                                    plan=built, render=False).as_dict()

            text = receipts.build_readiness(result, job_id="t", updated_utc=_WHEN)

            self.assertIn("status: NOT_READY", text)
            self.assertIn("do not widen the tolerance", text)

    def test_the_frontmatter_matches_the_contract_template(self) -> None:
        """A derived receipt that omits contract fields is still a malformed
        receipt -- just one nobody typed."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            text = receipts.build_readiness(_run(work), job_id="t",
                                            source_revisions={"dimensions": 3,
                                                              "print_plan": 2},
                                            updated_utc=_WHEN)

            for field in ("contract: candidate-readiness", "contract_version: 4",
                          "owner: cad-designer", "non_acceptance: true",
                          "dimensions_revision: 3", "print_plan_revision: 2"):
                self.assertIn(field, text)
            # A 64-hex hash, not merely the label: the empty field matched too.
            line = next(ln for ln in text.splitlines()
                        if ln.startswith("candidate_stl_sha256:"))
            self.assertRegex(line, r"^candidate_stl_sha256: [0-9a-f]{64}$")

    def test_an_unsupplied_revision_says_unbound_rather_than_guessing(self) -> None:
        """Defaulting to 1 asserts a binding nobody checked, and `contracts
        status` then reports a clean match against an invented number."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            text = receipts.build_readiness(_run(work), job_id="t", updated_utc=_WHEN)

            self.assertIn("dimensions_revision: UNBOUND", text)
            self.assertIn("print_plan_revision: UNBOUND", text)

    def test_visual_accept_is_blocked_when_nothing_was_rendered(self) -> None:
        """A verification caught a `visual_accept: yes` written on an interpreter
        with no renderer. The claim was sincere and ungrounded, which is the
        worst combination -- so it is not a blank to fill."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            result = _run(work)  # render=False, so the render check is SKIPPED
            result["checks"].append({"id": "render", "title": "r", "result": "SKIPPED",
                                     "detail": "renderer unavailable"})

            text = receipts.build_readiness(result, job_id="t", updated_utc=_WHEN)

            self.assertIn("CANNOT BE ANSWERED HERE", text)
            self.assertIn("Do not write a verdict you did not see", text)

    def test_the_judgments_are_never_answered_here(self) -> None:
        """A receipt that fills itself in completely has stopped being one.

        `fit_band_ok` is always left for a reader. `visual_accept` is left blank
        when there are renders and explicitly blocked when there are none -- the
        one thing it must never be is decided, and this fixture does not render,
        so it must come back blocked."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            text = receipts.build_readiness(_run(work), job_id="t", updated_utc=_WHEN)

            self.assertIn("`fit_band_ok`: <!-- REQUIRED", text)
            self.assertIn("`visual_accept`: <!-- CANNOT BE ANSWERED HERE", text)
            for verdict in ("`visual_accept`: yes", "`visual_accept`: no"):
                self.assertNotIn(verdict, text)


if __name__ == "__main__":
    unittest.main()
