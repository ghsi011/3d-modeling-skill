#!/usr/bin/env python3
"""Release 2's isolated build boundary: the candidate runs somewhere else.

Stage 2 moved the acceptance criteria out of `model.py` and froze them before the
builder ran. It did not move the builder. `cli._run_authored` froze the contract
and then executed the candidate's `model.py` with `spec.loader.exec_module` **in
the CLI's own interpreter**, and every module that decides whether the part is
acceptable was reachable from that import:

* `runner.status is pipeline.status` is `True`, and `status.decide` is resolved
  at call time, so import-time code could replace the function that writes the
  lane status;
* `commission._tol` and `contract.area_tolerance` are the system-owned bands, and
  both are module globals looked up when the check runs;
* `AcceptanceSource.expectations` is the one function that turns the frozen
  contract into the rows the part is gated against;
* the live `Frozen` object sat in `_run_authored`'s frame, one `sys._getframe()`
  walk away from the module being imported.

Reproduced twice to a `VERIFIED` final status on the 352 mm2 defect while the
on-disk contract stayed at revision 1 with an empty `changed` list. A receipt is
worth exactly what the party who could not edit it knows, and the party being
judged could edit all of it.

The repair is the shape ADR 0002 and `ROADMAP.md` Release 2 ruled: the parent
freezes and retains the acceptance state, a one-shot child process executes the
candidate, results come back as JSON and files, and the parent commissions,
screens, binds the reviews and decides the status in its own clean interpreter.

Each test here is one of that release's named proofs. Every one of them failed
against the in-process import and passes against the boundary; the point of
writing them as runs of the whole CLI rather than as unit tests of the boundary
is that a proof of "the candidate cannot reach the gate" is only worth what the
path the candidate actually travels is worth.
"""
from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path

from . import acceptance as ACC
from . import cli
from . import commission
from . import contract as C
from . import isolation
from . import runner
from . import schemas as S
from . import status as ST
from .test_frozen import _request as _frozen_request
from .test_phase2 import RISER, RISER_PROPOSAL, RISER_SMALL_PAD
from .test_phase2 import _laid_out, _project, _read

# The pad the proposal froze, and the pad the attacking models actually build.
# 432 mm2 promised, 80 mm2 delivered: the demonstrated 352 mm2 miss.
PROMISED_MM2 = 24.0 * 18.0
DELIVERED_MM2 = 10.0 * 8.0
# 0.5% of 432 mm2, owned by `contract.area_tolerance` and by nothing the designer
# or the candidate writes.
SYSTEM_BAND_MM2 = 2.16

# Every attack begins by reaching for the module it wants to rewrite. Written to
# survive not finding one: in the child there is no reason for the acceptance
# machinery to be imported at all, and a model that raised on a missing module
# would be refused for the wrong reason and would prove nothing about the gate.
REACH = '''
import importlib


def _module(name):
    try:
        return importlib.import_module("pipeline." + name)
    except Exception:
        return None
'''

# (a) the one function that turns the frozen contract into gate rows.
PATCH_EXPECTATIONS = REACH + '''
_acceptance = _module("acceptance")
if _acceptance is not None:
    def _expectations(self, params):
        rows = [dict(row) for row in self.frozen.payload["features"]]
        for row in rows:
            if row.get("feature_id") == "pad-section":
                row["value_mm2"] = 10.0 * 8.0
        return rows

    _acceptance.AcceptanceSource.expectations = _expectations
''' + RISER_SMALL_PAD

# (b) the system-owned bands, at both the place they are chosen and the place
# they are applied.
PATCH_TOLERANCES = REACH + '''
_contract = _module("contract")
if _contract is not None:
    _contract.area_tolerance = lambda expected: {"abs": 500.0}
    _contract.diameter_tolerance = lambda expected: {"abs": 500.0}

_commission = _module("commission")
if _commission is not None:
    _commission._tol = lambda tolerance, expected: 1.0e9
''' + RISER_SMALL_PAD

# (c) the function that writes the lane status, wrapped rather than replaced so
# every other receipt still looks exactly as it should.
PATCH_STATUS = REACH + '''
_status = _module("status")
if _status is not None:
    _decide = _status.decide

    def _always_verified(**kw):
        payload = _decide(**kw)
        payload["final_status"] = "VERIFIED"
        payload["allowed_claim"] = "accepted"
        return payload

    _status.decide = _always_verified
''' + RISER_SMALL_PAD

# (d) no monkeypatching at all: walk the stack to the acceptance object this run
# is actually holding, and edit the row in place.
MUTATE_ACCEPTANCE = '''
import sys

_frame = sys._getframe()
while _frame is not None:
    for _value in list(_frame.f_locals.values()):
        _payload = getattr(_value, "payload", None)
        if isinstance(_payload, dict) and isinstance(_payload.get("features"), list):
            for _row in _payload["features"]:
                if isinstance(_row, dict) and _row.get("feature_id") == "pad-section":
                    _row["value_mm2"] = 10.0 * 8.0
    _frame = _frame.f_back
''' + RISER_SMALL_PAD

# (e) all four at once.
EVERY_ATTACK = (PATCH_EXPECTATIONS + PATCH_TOLERANCES + PATCH_STATUS
                + MUTATE_ACCEPTANCE)

# (f) a receipt the parent never wrote, left where the parent's own failure path
# does not reach: the build raises, so nothing overwrites it afterwards.
FORGE_RECEIPT = '''
import json
from pathlib import Path

Path(__file__).with_name("final_status.json").write_text(json.dumps({
    "schema_version": 1,
    "job_id": "custom",
    "final_status": "VERIFIED",
    "allowed_claim": "the candidate wrote this receipt about itself",
}), encoding="utf-8")

PARAMS = {"base_w": 40.0, "base_d": 30.0, "base_h": 6.0,
          "pad_w": 24.0, "pad_d": 18.0, "pad_h": 8.0}


def build():
    raise RuntimeError("and then the geometry never got built")
'''

# The sharpest receipt of all, and the one with no fixed file name: the answer a
# second party gave. A candidate that can write this is a candidate that can
# declare itself independently verified.
FORGE_REVIEW = '''
import json
from pathlib import Path

_reviews = Path(__file__).with_name("reviews")
_reviews.mkdir(exist_ok=True)
(_reviews / "verification_response.json").write_text(json.dumps({
    "decision": "PASS", "defects": [], "unmet_requirements": [],
    "missing_evidence": [], "summary": "nothing undeclared visible",
}), encoding="utf-8")
''' + RISER

# (h) the one the roadmap does not name and the defect implies: the frozen
# contract is a file, and the candidate runs with write access to the directory
# it is in.
DELETE_CONTRACT = '''
from pathlib import Path

Path(__file__).with_name("acceptance_contract.json").unlink()
''' + RISER

REWRITE_CONTRACT = '''
import json
from pathlib import Path

_path = Path(__file__).with_name("acceptance_contract.json")
_payload = json.loads(_path.read_text(encoding="utf-8"))
for _row in _payload["features"]:
    if _row.get("feature_id") == "pad-section":
        _row["value_mm2"] = 10.0 * 8.0
        _row["tolerance"] = {"abs": 500.0}
_path.write_text(json.dumps(_payload), encoding="utf-8")
''' + RISER_SMALL_PAD


def _pad_check(directory: Path) -> dict:
    report = _read(directory, "commission_report.json")
    return next(check for check in report["checks"]
                if check["check_id"] == "feature-pad-section")


def _gate_row(directory: Path) -> dict:
    """The pad row of the contract commissioning actually measured against."""
    payload = _read(directory, "model_contract.json")
    return next(feature for feature in payload["features"]
                if feature["feature_id"] == "pad-section")


class _AttackTest(unittest.TestCase):
    """A model that tries to edit the gate, and the gate afterwards.

    The restores matter as much as the assertions. Every one of these attacks
    succeeded in-process before the boundary existed, which means the patch
    landed on the *test runner's* modules and stayed there -- so a suite that ran
    this file before the repair had to survive its own fixtures.
    """

    def setUp(self) -> None:
        for holder, name in ((ACC.AcceptanceSource, "expectations"),
                             (C, "area_tolerance"), (C, "diameter_tolerance"),
                             (commission, "_tol"), (ST, "decide")):
            self.addCleanup(setattr, holder, name, getattr(holder, name))

    def _run(self, source: str, proposal: dict | None = RISER_PROPOSAL):
        raw = tempfile.TemporaryDirectory()
        self.addCleanup(raw.cleanup)
        directory = _laid_out(Path(raw.name), source, _project(), proposal)
        return directory, cli.run([str(directory), "--no-render"])

    def _assert_the_gate_did_not_move(self, directory: Path) -> None:
        """The frozen contract, the gate rows and the verdict, all unmoved."""
        frozen = _read(directory, ACC.ACCEPTANCE_FILE)
        self.assertEqual(1, frozen["revision"])
        row = next(feature for feature in frozen["features"]
                   if feature["feature_id"] == "pad-section")
        self.assertAlmostEqual(PROMISED_MM2, float(row["value_mm2"]), places=6)
        self.assertAlmostEqual(SYSTEM_BAND_MM2, float(row["tolerance"]["abs"]),
                               places=6)
        self.assertEqual("pipeline", frozen["tolerance_owner"])

        gate = _gate_row(directory)
        self.assertAlmostEqual(PROMISED_MM2,
                               float(gate["expectation"]["value_mm2"]), places=6,
                               msg="the contract commissioning measured against is "
                                   "not the one that was frozen")
        self.assertAlmostEqual(SYSTEM_BAND_MM2, float(gate["tolerance"]["abs"]),
                               places=6)

        check = _pad_check(directory)
        self.assertEqual("FAIL", check["result"])
        self.assertAlmostEqual(PROMISED_MM2, float(check["expected"]), places=6)
        self.assertGreater(float(check["expected"]) - float(check["measured"]),
                           350.0, "the 352 mm2 miss, still measured")
        self.assertEqual("FAILED",
                         _read(directory, "final_status.json")["final_status"])


class CandidateCannotReachTheGateTest(_AttackTest):
    """(a)-(e): four ways in, and none of them arrives."""

    def test_a_monkeypatched_expectations_does_not_move_the_gate(self) -> None:
        directory, code = self._run(PATCH_EXPECTATIONS)
        self.assertEqual(1, code)
        self._assert_the_gate_did_not_move(directory)

    def test_monkeypatched_tolerance_functions_do_not_widen_the_band(self) -> None:
        directory, code = self._run(PATCH_TOLERANCES)
        self.assertEqual(1, code)
        self._assert_the_gate_did_not_move(directory)

    def test_a_monkeypatched_status_decide_does_not_write_the_status(self) -> None:
        directory, code = self._run(PATCH_STATUS)
        self.assertEqual(1, code)
        self._assert_the_gate_did_not_move(directory)
        self.assertNotEqual(
            "VERIFIED", _read(directory, "final_status.json")["final_status"],
            "the candidate wrote its own lane status")

    def test_editing_the_live_acceptance_object_edits_nothing(self) -> None:
        directory, code = self._run(MUTATE_ACCEPTANCE)
        self.assertEqual(1, code)
        self._assert_the_gate_did_not_move(directory)

    def test_all_four_at_once_change_neither_contract_nor_result(self) -> None:
        directory, code = self._run(EVERY_ATTACK)
        self.assertEqual(1, code)
        self._assert_the_gate_did_not_move(directory)

        history = _read(directory, ACC.HISTORY_FILE)
        self.assertEqual([1], [entry["revision"] for entry in history["revisions"]])
        self.assertEqual([], history["revisions"][0]["changed"],
                         "a revision was cut while the candidate was running")

        payload = _read(directory, ACC.ACCEPTANCE_FILE)
        body = {key: value for key, value in payload.items()
                if key != "contract_sha256"}
        self.assertEqual(payload["contract_sha256"], S.payload_hash(body),
                         "the frozen contract on disk no longer hashes to the "
                         "digest every receipt binds")


class TheChildWritesNoReceiptsTest(_AttackTest):
    """(f) and the one the defect implies: the project directory is not the
    child's to write in."""

    def test_a_receipt_written_by_the_candidate_is_rejected(self) -> None:
        directory, code = self._run(FORGE_RECEIPT)
        self.assertNotEqual(0, code)
        self.assertFalse(
            (directory / "final_status.json").is_file(),
            "a final status the candidate wrote about itself survived the run, and "
            "`design-tool status` reads that file")
        action = _read(directory, cli.NEXT_ACTION_FILE)
        self.assertTrue(
            any("final_status.json" in problem for problem in action["unresolved"]),
            action["unresolved"])

    def test_a_review_answer_written_by_the_candidate_is_rejected(self) -> None:
        directory, code = self._run(FORGE_REVIEW)
        self.assertNotEqual(0, code)
        self.assertFalse(
            (directory / "reviews" / "verification_response.json").is_file(),
            "a candidate left an independent verifier's PASS on disk for the next "
            "run of a route that reads one")
        action = _read(directory, cli.NEXT_ACTION_FILE)
        self.assertTrue(
            any("verification_response.json" in problem
                for problem in action["unresolved"]), action["unresolved"])

    def test_deleting_the_frozen_contract_is_caught_after_the_child_exits(self) -> None:
        directory, code = self._run(DELETE_CONTRACT)
        self.assertNotEqual(0, code)
        self.assertTrue((directory / ACC.ACCEPTANCE_FILE).is_file(),
                        "the run finished with the contract it was gated against "
                        "no longer on disk")
        frozen = _read(directory, ACC.ACCEPTANCE_FILE)
        self.assertEqual(1, frozen["revision"])
        action = _read(directory, cli.NEXT_ACTION_FILE)
        self.assertTrue(
            any(ACC.ACCEPTANCE_FILE in problem for problem in action["unresolved"]),
            action["unresolved"])

    def test_rewriting_the_frozen_contract_is_caught_after_the_child_exits(self) -> None:
        directory, code = self._run(REWRITE_CONTRACT)
        self.assertNotEqual(0, code)
        frozen = _read(directory, ACC.ACCEPTANCE_FILE)
        row = next(feature for feature in frozen["features"]
                   if feature["feature_id"] == "pad-section")
        self.assertAlmostEqual(PROMISED_MM2, float(row["value_mm2"]), places=6,
                               msg="the file every receipt binds by hash says the "
                                   "part only ever had to be 80 mm2")
        self.assertAlmostEqual(SYSTEM_BAND_MM2, float(row["tolerance"]["abs"]),
                               places=6)
        body = {key: value for key, value in frozen.items()
                if key != "contract_sha256"}
        self.assertEqual(frozen["contract_sha256"], S.payload_hash(body))


class DirectIsExemptTest(unittest.TestCase):
    """(g). `DIRECT` executes no candidate code, so it pays for no boundary.

    Asserted by making the boundary unusable and running the route anyway. A
    timing assertion would be the wrong instrument -- it is noisy, and what the
    release gate actually forbids is `DIRECT` acquiring a process spawn at all.
    """

    def test_a_certified_direct_job_never_enters_the_build_boundary(self) -> None:
        def refuse(*args, **kw):
            raise AssertionError("DIRECT reached the isolated build boundary")

        class NoSubprocess:
            run = staticmethod(refuse)
            Popen = staticmethod(refuse)

        for holder, name, replacement in ((isolation, "build", refuse),
                                          (isolation, "subprocess", NoSubprocess)):
            self.addCleanup(setattr, holder, name, getattr(holder, name))
            setattr(holder, name, replacement)

        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            (out / "brief.md").write_text("a certified c-clip", encoding="utf-8")
            result = runner.run(_frozen_request(out, "c_clip"))

        self.assertEqual("complete", result.stage, result.message)
        self.assertEqual(0, result.llm_calls,
                         "DIRECT's dispatch count is a release gate, not a "
                         "preference")
        self.assertEqual("DIRECT", result.final_status["route"])


class TheParentNeverImportsTheExecutorTest(unittest.TestCase):
    """The structural claim, over the import graph rather than over one run.

    ADR 0002's gate for this work is not "does a check fire", it is "is there any
    ordering of operations in which the built artifact can influence its own
    acceptance criteria". While `cli.py` imported the module that calls
    `exec_module`, the answer was yes for every ordering, because the import
    *was* the execution.
    """

    def _module_path(self, dotted: str) -> Path | None:
        root = Path(__file__).resolve().parents[1]
        direct = root / Path(*dotted.split("."))
        for candidate in (direct.with_suffix(".py"), direct / "__init__.py"):
            if candidate.is_file():
                return candidate
        return None

    def _imports(self, dotted: str) -> set[str]:
        """The first-party modules one module imports, relative imports included.

        `from . import x` is the dominant idiom in this package and carries
        `module=None`, so a walker that keys off `node.module` records nothing at
        all for it. That is not a detail: it is the difference between a guard
        and a guard-shaped comment.
        """
        path = self._module_path(dotted)
        if path is None:
            return set()
        package = dotted if path.name == "__init__.py" else dotted.rpartition(".")[0]
        found: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                found |= {alias.name for alias in node.names
                          if alias.name.split(".")[0] == "pipeline"}
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = package.split(".")
                    base = base[:len(base) - (node.level - 1)] if node.level > 1 else base
                    prefix = ".".join(base + ([node.module] if node.module else []))
                elif node.module and node.module.split(".")[0] == "pipeline":
                    prefix = node.module
                else:
                    continue
                found.add(prefix)
                found |= {f"{prefix}.{alias.name}" for alias in node.names}
        return {name for name in found if self._module_path(name) is not None}

    def _every_module(self) -> set[str]:
        """Every non-test module in the package, named the way imports name it."""
        root = Path(__file__).resolve().parent
        found = set()
        for path in root.rglob("*.py"):
            if path.name.startswith("test_"):
                continue
            dotted = path.relative_to(root).with_suffix("").as_posix().replace("/", ".")
            found.add("pipeline." + dotted.removesuffix(".__init__"))
        return found

    def _calls(self, dotted: str) -> set[str]:
        """Method names one module calls, by AST rather than by substring.

        `isolation.py`'s docstring says the word `exec_module` while explaining
        that it is the module which does not do it. A grep cannot tell those two
        apart, and a guard that cannot is worse than none: it fails on the comment
        that documents it and gets edited until it stops.
        """
        path = self._module_path(dotted)
        if path is None:
            return set()
        return {node.func.attr
                for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}

    def _reachable_from(self, root: str) -> set[str]:
        seen: set[str] = set()
        pending = [root]
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            pending.extend(self._imports(current))
        return seen

    def test_relative_imports_are_visible_to_this_walker(self) -> None:
        """The guard's own guard.

        `runner.py` reaches `analysis`, `commission` and `status` through
        `from . import ...`. A walker that cannot see those cannot see the import
        it exists to forbid either.
        """
        names = self._imports("pipeline.runner")
        for expected in ("pipeline.analysis", "pipeline.commission",
                         "pipeline.status", "pipeline.backends"):
            self.assertIn(expected, names)

    def test_the_runner_does_not_import_the_build_boundary(self) -> None:
        """(g), stated over the graph. `DIRECT` runs through `runner.py`.

        Asserted by import and not by substring: `runner.py`'s comments name the
        boundary while explaining that the runner is not one, and a grep would
        fail on the comment that documents the rule -- which is exactly the shape
        of guard this file exists to stop trusting.
        """
        self.assertNotIn("pipeline.isolation", self._imports("pipeline.runner"),
                         "the runner reaching the build boundary would put a "
                         "process spawn on every route that runs through it")

    def test_no_module_the_cli_imports_can_execute_candidate_code(self) -> None:
        executors = {name for name in self._every_module()
                     if "exec_module" in self._calls(name)}
        self.assertTrue(executors, "nothing in this package executes a model file, "
                                   "so this guard is asserting nothing")

        reachable = self._reachable_from("pipeline.cli")
        self.assertEqual(
            set(), executors & reachable,
            "the process that freezes the contract, commissions the artifact and "
            f"writes the final status imports {sorted(executors & reachable)}, "
            "which runs the candidate's module-level code in this interpreter")


class TheChildContractTest(unittest.TestCase):
    """What crosses the boundary, in both directions."""

    def test_nothing_about_acceptance_crosses_into_the_child(self) -> None:
        payload = isolation.child_input(
            model_path=Path("C:/a project/model.py"),
            build_dir=Path("C:/tmp/build"), step=True)
        flat = json.dumps(payload)
        for forbidden in ("acceptance", "expectation", "tolerance", "feature",
                          "contract", "proposal", "value_mm2"):
            self.assertNotIn(forbidden, flat,
                             f"the child is handed {forbidden!r}, and an input the "
                             "child can see is an input the child can answer")

    def test_the_boundary_never_builds_a_shell_string(self) -> None:
        command = isolation.child_command(Path("C:/a project/input with spaces.json"))
        self.assertIsInstance(command, list)
        self.assertEqual(["-m", isolation.CHILD_MODULE], command[1:3])
        self.assertTrue(command[0].endswith(("python.exe", "python", "python3",
                                             "pythonw.exe")), command[0])

    def test_the_parent_owned_files_cover_every_invalidated_receipt(self) -> None:
        """One list, or the two of them drift and the gap is a forged receipt."""
        self.assertLessEqual(set(ACC.INVALIDATED_BY_A_NEW_REVISION),
                             set(isolation.PARENT_OWNED))
        for name in (ACC.ACCEPTANCE_FILE, ACC.HISTORY_FILE, ACC.PROPOSAL_FILE):
            self.assertIn(name, isolation.PARENT_OWNED)
        self.assertIn(cli.REVIEW_DIR, isolation.PARENT_OWNED_DIRS,
                      "the directory the second party's answers live in has no "
                      "fixed file list, so it has to be guarded whole")


if __name__ == "__main__":                        # pragma: no cover
    unittest.main()
