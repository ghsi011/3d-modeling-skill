"""Tests for the derived handoff receipts.

The property under test is that the receipt describes the mesh actually being
shipped. One archived run's hand-written receipt described a mesh that was no
longer the one on disk, which is the failure re-typing these numbers invites.
"""

import json
import subprocess
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


class ManifestTest(unittest.TestCase):
    def test_the_hash_is_of_the_file_that_exists_now(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            result = _run(work)

            manifest = receipts.build_manifest(result, work / "out", job_id="t",
                                               updated_utc=_WHEN)

            row = next(a for a in manifest["artifacts"] if a["id"] == "candidate-01")
            on_disk = receipts.sha256_file(work / "out" / row["path"])
            self.assertEqual(on_disk, row["sha256"])

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
        """The whole point of deriving it: no round trip to find out it is wrong."""
        sys.path.insert(0, str(_SCRIPTS / "team_tools"))
        import validators  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            manifest = receipts.build_manifest(_run(work), work / "out", job_id="t",
                                               updated_utc=_WHEN)

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
                          "dimensions_revision: 3", "print_plan_revision: 2",
                          "candidate_stl_sha256: "):
                self.assertIn(field, text)

    def test_the_judgments_are_left_blank(self) -> None:
        """A receipt that fills itself in completely has stopped being one."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            text = receipts.build_readiness(_run(work), job_id="t", updated_utc=_WHEN)

            self.assertIn("`visual_accept`: <!-- REQUIRED", text)
            self.assertIn("`fit_band_ok`: <!-- REQUIRED", text)


class CliTest(unittest.TestCase):
    def test_the_command_emits_both_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            stl = _seated_box(work / "box.stl", (30.0, 20.0, 10.0))
            plan_path = work / "plan.json"
            plan_path.write_text(json.dumps(plan.direct_template((30.0, 20.0, 10.0))),
                                 encoding="utf-8")
            out = work / "out"

            completed = subprocess.run(
                [sys.executable, "-m", "designer_toolkit.commission", "--stl", str(stl),
                 "--plan", str(plan_path), "--out", str(out), "--no-render",
                 "--job-id", "t", "--updated-utc", _WHEN],
                cwd=_SCRIPTS, capture_output=True, text=True, check=False,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertTrue((out / "artifact_manifest.json").is_file())
            self.assertTrue((out / "candidate_readiness.md").is_file())

    def test_the_timestamp_is_injected_so_a_rerun_is_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            first = receipts.build_readiness(_run(work), job_id="t", updated_utc=_WHEN)
            second = receipts.build_readiness(_run(work), job_id="t", updated_utc=_WHEN)

            self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
