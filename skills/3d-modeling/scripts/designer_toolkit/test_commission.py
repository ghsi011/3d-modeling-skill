"""Tests for the one-call commission gate.

The gate exists because every rejection a fresh verifier ever issued was a
deterministic predicate the designer's own receipt already claimed to have
checked. So these tests are mostly about one property: a candidate that would
have been rejected downstream must fail *here*, with a non-zero exit, before it
can be handed on.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import trimesh

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from designer_toolkit import commission  # noqa: E402


def _plan(**overrides):
    plan = {
        "contract": "print-plan", "contract_version": 4, "job_id": "t", "revision": 1,
        "owner": "print-engineer",
        "support_rules": [{
            "id": "S-01", "disposition": "SUPPORT_ALLOWED",
            "downward_normal_z_max": -0.73, "max_out_of_limit_area_mm2": 10000.0,
        }],
        "interfaces": [], "edges": [],
    }
    plan.update(overrides)
    return plan


def _box_stl(directory: Path, extents=(30, 20, 10)) -> Path:
    path = directory / "box.stl"
    trimesh.creation.box(extents=extents).export(path)
    return path


class EnvelopeCheckTest(unittest.TestCase):
    """The check whose absence shipped a phone case 31% too thick."""

    def test_a_part_the_wrong_size_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            stl = _box_stl(work, extents=(30, 20, 14))
            plan = _plan(expected_bbox_mm={"x": 30, "y": 20, "z": 10},
                         bbox_tolerance_mm=1.0)

            result = commission.run(model=None, stl=stl, out_dir=work / "out",
                                    plan=plan, render=False)

            envelope = next(c for c in result.checks if c.id == "envelope")
            self.assertEqual(envelope.result, "FAIL")
            self.assertIn("z", envelope.detail)
            self.assertIn("do not widen the tolerance", envelope.action)

    def test_a_part_the_right_size_passes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            stl = _box_stl(work, extents=(30, 20, 10))
            plan = _plan(expected_bbox_mm={"x": 30, "y": 20, "z": 10},
                         bbox_tolerance_mm=0.5)

            result = commission.run(model=None, stl=stl, out_dir=work / "out",
                                    plan=plan, render=False)

            self.assertEqual(next(c for c in result.checks if c.id == "envelope").result, "PASS")

    def test_a_plan_with_no_expected_size_says_so_loudly(self) -> None:
        """Skipping silently is how the 31% error passed. It must be visible."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            result = commission.run(model=None, stl=_box_stl(work), out_dir=work / "out",
                                    plan=_plan(), render=False)

            envelope = next(c for c in result.checks if c.id == "envelope")
            self.assertEqual(envelope.result, "SKIPPED")
            self.assertIn("expected_bbox_mm", envelope.action)


class SupportCheckTest(unittest.TestCase):
    def test_self_support_required_with_a_nonzero_ceiling_is_rejected(self) -> None:
        """The contract says that combination means zero. Two archived runs
        declared SELF_SUPPORT_REQUIRED with ceilings of 1850 and 2150 and passed.
        """
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            plan = _plan(support_rules=[{
                "id": "S-01", "disposition": "SELF_SUPPORT_REQUIRED",
                "downward_normal_z_max": -0.73, "max_out_of_limit_area_mm2": 1850.0,
            }])

            result = commission.run(model=None, stl=_box_stl(work), out_dir=work / "out",
                                    plan=plan, render=False)

            ceiling = next(c for c in result.checks if c.id == "support-ceiling")
            self.assertEqual(ceiling.result, "FAIL")

    def test_it_screens_in_the_best_placement_it_can_find(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            result = commission.run(model=None, stl=_box_stl(work), out_dir=work / "out",
                                    plan=_plan(), render=False)

            support = next(c for c in result.checks if c.id == "support")
            self.assertEqual(support.result, "PASS")
            self.assertIn("placement", support.detail)
            self.assertGreater(len(result.evidence["placements_considered"]), 1)


class SolidCheckTest(unittest.TestCase):
    def test_a_two_body_export_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            first = trimesh.creation.box(extents=(10, 10, 10))
            second = trimesh.creation.box(extents=(10, 10, 10))
            second.apply_translation((40, 0, 0))
            path = work / "two.stl"
            trimesh.util.concatenate((first, second)).export(path)

            result = commission.run(model=None, stl=path, out_dir=work / "out",
                                    plan=_plan(), render=False)

            self.assertEqual(next(c for c in result.checks if c.id == "solid").result, "FAIL")


class CliTest(unittest.TestCase):
    def test_a_failing_candidate_exits_nonzero(self) -> None:
        """The whole point: a failing candidate cannot reach a verifier."""
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            stl = _box_stl(work, extents=(30, 20, 14))
            plan_path = work / "plan.json"
            plan_path.write_text(json.dumps(
                _plan(expected_bbox_mm={"x": 30, "y": 20, "z": 10}, bbox_tolerance_mm=0.5)),
                encoding="utf-8")

            completed = subprocess.run(
                [sys.executable, "-m", "designer_toolkit.commission",
                 "--stl", str(stl), "--plan", str(plan_path),
                 "--out", str(work / "out"), "--no-render"],
                cwd=_SCRIPTS, capture_output=True, text=True, check=False,
            )

            self.assertEqual(completed.returncode, 1)
            self.assertIn("FAIL envelope", completed.stderr)
            self.assertEqual(json.loads(completed.stdout)["verdict"], "FAIL")

    def test_it_writes_the_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            commission.run(model=None, stl=_box_stl(work), out_dir=work / "out",
                           plan=_plan(), render=False)

            payload = json.loads((work / "out" / "commission.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["verdict"], "PASS")
            self.assertIsNone(payload["judgment_required"]["visual_accept"])


class LoadPartTest(unittest.TestCase):
    def test_a_module_without_part_or_build_says_what_it_needs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            module = Path(raw) / "model.py"
            module.write_text("x = 1\n", encoding="utf-8")

            with self.assertRaises(ValueError) as caught:
                commission.load_part(module)

            self.assertIn("build()", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
