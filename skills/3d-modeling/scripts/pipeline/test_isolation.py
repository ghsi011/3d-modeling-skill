#!/usr/bin/env python3
"""Release 2's confined build boundary: the candidate runs with less authority.

Stage 2 moved the acceptance criteria out of `model.py` and froze them before the
builder ran. `0a8e464` then moved the builder into a child process. Neither was
enough, and the reason is one sentence: separation was implemented as a different
*interpreter* and the claim ADR 0002 needs is about *privilege*. The child was a
peer -- same user, same filesystem, no lifetime bound -- and an adversarial review
walked through it three ways that no import graph can see:

* `pipeline/backends/authored.py` is first imported by the parent *after*
  `isolation.build` returns. The candidate rewrote it while building and the
  parent executed its module-level code seconds later, in the interpreter
  holding the frozen contract. Exit 0, `VERIFIED`, `expected 432.0 measured
  80.002`, contract still at revision 1;
* the same, through a `__pycache__` entry stamped with the real file's mtime and
  size, leaving the `.py` byte-identical, so hashing the source saw nothing;
* a `DETACHED_PROCESS` grandchild that outlived `subprocess.run`'s timeout and
  rewrote `final_status.json` 25 s after the run reported `FAILED`.

The repair is `confine.py`: a restricted, low-integrity, privilege-stripped
token; a workspace whose only writable object is one directory; and a job object
with `KILL_ON_JOB_CLOSE` and no breakaway, which the parent drains to zero before
it reads a byte.

What each class here is for:

* `TheCandidateCannotReachTheGateTest` -- the four in-process attacks. They still
  run, they still reach nothing, and they are cheap;
* `PortedFromTheAdversarialReviewTest` -- the three attacks that broke `0a8e464`,
  plus a write into the virtual environment and an escape through a junction.
  Each one asserts the *file on disk*, and each one restores it if the boundary
  ever fails, so a red suite does not also leave a rewritten source tree;
* `WhatTheConfinementEnforcesTest` -- one probe model reporting what it could
  actually do, so every property this boundary claims is a measurement rather
  than a comment. The two rows that are *allowed* are in the table too, because
  a limitation nobody wrote down is a limitation nobody knows about;
* `TheOutputsAreValidatedTest` -- every way to name something that is not
  `candidate.stl`, plus reparse points, alternate data streams and paths that
  resolve out of the sandbox;
* `TheChildContractTest` and `TheBuildChildTest` -- what crosses, in both
  directions, and the module that executes candidate code, which had no test;
* `TheCallSitesAreAssertedTest` -- the four D8 survivors whose weakening no
  assertion about a return value can see;
* `DirectIsExemptTest` -- `DIRECT` creates no process, proven with an audit hook
  rather than by replacing two module attributes;
* `TheParentNeverImportsTheExecutorTest` -- the structural claim over the import
  graph.
"""
from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import os
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from . import acceptance as ACC
from . import cli
from . import commission
from . import confine
from . import contract as C
from . import isolation
from . import runner
from . import schemas as S
from . import status as ST
from .test_frozen import _request as _frozen_request
from .test_phase2 import RISER, RISER_PROPOSAL, RISER_SMALL_PAD
from .test_phase2 import _laid_out, _project, _read

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_ROOT.parents[2]

# The pad the proposal froze, and the pad the attacking models actually build.
# 432 mm2 promised, 80 mm2 delivered: the demonstrated 352 mm2 miss.
PROMISED_MM2 = 24.0 * 18.0
DELIVERED_MM2 = 10.0 * 8.0
# 0.5% of 432 mm2, owned by `contract.area_tolerance` and by nothing the designer
# or the candidate writes.
SYSTEM_BAND_MM2 = 2.16

requires_confinement = unittest.skipIf(
    not confine.available(),
    f"the confined build boundary is not available here: "
    f"{confine.unavailable_reason()}")

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
# contract is a file, and the candidate used to run with write access to the
# directory it is in.
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

# ---------------------------------------------------------------------------
# The three that broke `0a8e464`, ported from the adversarial review, plus two
# the review's own conclusion implies.
# ---------------------------------------------------------------------------

# The payload every one of them installs: a `status.decide` that always says
# VERIFIED, on a part 352 mm2 short.
PAYLOAD = '''
import sys as _sys

_status = _sys.modules.get("pipeline.status")
if _status is not None:
    _undecided = _status.decide

    def _decide(**kw):
        payload = _undecided(**kw)
        payload["final_status"] = "VERIFIED"
        payload["allowed_claim"] = "the part was independently verified"
        payload["reasons"] = []
        return payload

    _status.decide = _decide
'''

# 1. Same run, no persistence, no race. `backends/authored.py` is on the path of
#    every authored job and the parent imports it for the first time *after* the
#    build has returned (`runner.py` -> `backends/__init__.py`). Rewrite it while
#    building and the parent runs the new module-level code itself.
LAZY_IMPORT_ATTACK = '''
import os
from pathlib import Path

_root = Path(os.environ["PYTHONPATH"].split(os.pathsep)[0])
_target = _root / "pipeline" / "backends" / "authored.py"
_text = _target.read_text(encoding="utf-8")
_target.write_text(_text + """
# OWNED_BY_THE_CANDIDATE
''' + PAYLOAD.replace("\n", "\n") + '''
""", encoding="utf-8")
''' + RISER_SMALL_PAD

# 2. The same, with the `.py` left byte-identical. `PYTHONDONTWRITEBYTECODE`
#    stops the child writing bytecode by accident, not on purpose, and the parent
#    does not run with that flag.
POISONED_PYC_ATTACK = '''
import importlib.util
import marshal
import os
import struct
from pathlib import Path

_root = Path(os.environ["PYTHONPATH"].split(os.pathsep)[0])
_py = _root / "pipeline" / "backends" / "authored.py"
_stat = _py.stat()
_code = compile(_py.read_text(encoding="utf-8") + """
''' + PAYLOAD + '''
""", str(_py), "exec")
_pyc = Path(importlib.util.cache_from_source(str(_py)))
_pyc.parent.mkdir(parents=True, exist_ok=True)
_pyc.write_bytes(
    importlib.util.MAGIC_NUMBER
    + struct.pack("<III", 0, int(_stat.st_mtime) & 0xFFFFFFFF,
                  _stat.st_size & 0xFFFFFFFF)
    + marshal.dumps(_code))
''' + RISER_SMALL_PAD

# 3. Cross-run. `pipeline/status.py` is outside any project directory, so the
#    old boundary's snapshot never looked at it. This run still fails; run N+1
#    loads the rewritten module before any candidate code exists in it at all.
SOURCE_TREE_ATTACK = '''
import os
from pathlib import Path

_root = Path(os.environ["PYTHONPATH"].split(os.pathsep)[0])
_status = _root / "pipeline" / "status.py"
_status.write_text(_status.read_text(encoding="utf-8") + """

# OWNED_BY_THE_CANDIDATE
_undecided = decide


def decide(**kw):
    payload = _undecided(**kw)
    payload["final_status"] = "VERIFIED"
    return payload
""", encoding="utf-8")
''' + RISER_SMALL_PAD

# 4. A grandchild that outlives the whole run: past the boundary, past
#    commissioning, past the parent's own exit, and then rewrites the receipts.
GRANDCHILD_ATTACK = '''
import os
import subprocess
import sys

_GRANDCHILD = r"""
import json, sys, time
from pathlib import Path
d = Path(sys.argv[1])
time.sleep(10)
(d / "GRANDCHILD_WAS_HERE.txt").write_text("owned", encoding="utf-8")
p = d / "final_status.json"
try:
    payload = json.loads(p.read_text(encoding="utf-8"))
except Exception:
    payload = {"schema_version": 1, "job_id": "custom"}
payload["final_status"] = "VERIFIED"
payload["allowed_claim"] = "the part was independently verified"
p.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
na = d / "next_action.json"
if na.is_file():
    na.unlink()
"""

_flags = 0
if os.name == "nt":
    _flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
subprocess.Popen([sys.executable, "-c", _GRANDCHILD, __TARGET__],
                 creationflags=_flags, close_fds=True,
                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                 stderr=subprocess.DEVNULL)
''' + RISER_SMALL_PAD

# 4b. The same, but asking the kernel for permission to leave the job. The job
#     sets neither `JOB_OBJECT_LIMIT_BREAKAWAY_OK` nor `SILENT_BREAKAWAY_OK`, so
#     the only question is whether Windows honours that -- and the answer is a
#     measurement, not a reading of the documentation.
BREAKAWAY_ATTACK = GRANDCHILD_ATTACK.replace(
    "_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP",
    "_flags = subprocess.DETACHED_PROCESS | 0x01000000")

# 5. The virtual environment. A `.pth` or a `sitecustomize.py` in `site-packages`
#    is executed by *every* interpreter that starts with that environment, before
#    `pipeline` is imported at all, so it owns run N+1 with no candidate in it.
VENV_ATTACK = '''
import sysconfig
from pathlib import Path

_site = Path(sysconfig.get_paths()["purelib"])
(_site / "sitecustomize.py").write_text(
    "# OWNED_BY_THE_CANDIDATE\\n", encoding="utf-8")
(_site / "zzz_owned.pth").write_text(
    "import sys; sys.OWNED_BY_THE_CANDIDATE = True\\n", encoding="utf-8")
''' + RISER_SMALL_PAD

# 6. A junction out of the one writable directory. Creating a directory junction
#    needs no privilege at all, which is what makes it the interesting reparse
#    point: `os.symlink` would need one.
JUNCTION_ATTACK = '''
import os
import subprocess
from pathlib import Path

_escape = Path.cwd() / "escape"
subprocess.run(["cmd", "/c", "mklink", "/J", str(_escape), __TARGET__],
               capture_output=True, check=False)
(_escape / "OWNED_BY_THE_CANDIDATE.txt").write_text("owned", encoding="utf-8")
''' + RISER_SMALL_PAD

# A model that rewrites its own source while it builds. The old boundary hashed
# `model.py` *after* the build, so the receipt named whatever survived.
SELF_REWRITING = '''
from pathlib import Path

Path(__file__).write_text("# not what ran\\n", encoding="utf-8")
''' + RISER

# What the confinement actually permits, reported by the candidate itself. Every
# address it needs is substituted in before it runs, so nothing here is refused
# for want of knowing where to aim.
PROBE = '''
import ctypes
import os
import socket
from pathlib import Path

_report = {}


def _try(name, fn):
    try:
        fn()
        _report[name] = "ALLOWED"
    except Exception as exc:
        _report[name] = type(exc).__name__


def _write(path):
    Path(path).write_text("owned", encoding="utf-8")


_try("write_repository", lambda: _write(Path(__REPO__, "PWNED.txt")))
_try("write_site_packages", lambda: _write(Path(__SITE__, "sitecustomize.py")))
_try("write_pipeline_source",
     lambda: _write(Path(os.environ["PYTHONPATH"], "pipeline", "PWNED.py")))
_try("write_project_directory", lambda: _write(Path(__PROJECT__, "PWNED.txt")))
_try("read_project_directory",
     lambda: Path(__PROJECT__, "acceptance_contract.json").read_text())
_try("write_parent_temp", lambda: _write(Path(__PARENT_TEMP__, "PWNED.txt")))
_try("write_startup_folder", lambda: _write(Path(__STARTUP__, "PWNED.cmd")))
_try("write_own_inputs", lambda: _write(Path(__file__).with_name("PWNED.py")))
_try("write_own_source", lambda: _write(Path(__file__)))
_try("write_build_directory", lambda: _write(Path.cwd() / "allowed.txt"))
_try("write_low_integrity_profile", lambda: _write(Path(__LOCALLOW__, "PWNED.txt")))


def _connect():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    try:
        sock.connect(("1.1.1.1", 53))
    finally:
        sock.close()


def _junction():
    import subprocess

    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(Path.cwd() / "escape"), __PROJECT__],
        capture_output=True, check=False, text=True)
    if completed.returncode != 0:
        raise PermissionError((completed.stdout or "") + (completed.stderr or ""))


_try("create_reparse_point", _junction)

_try("network_tcp_connect", _connect)
_try("dns_resolution", lambda: socket.gethostbyname("example.com"))


def _open_parent():
    handle = ctypes.windll.kernel32.OpenProcess(0x0008 | 0x0020, False, __PARENT_PID__)
    if not handle:
        raise PermissionError("OpenProcess denied")


_try("open_parent_for_write", _open_parent)

# What this process's token actually is, read out of the kernel by the boundary's
# own accessors. The parent describing what it intends to build is not evidence;
# the child reading back what it got is.
from pipeline import confine as _confine

PROVENANCE = {"confinement_probe": _report,
              "child_token": _confine.describe_token()}
''' + RISER


def _substitute(source: str, values: dict[str, object]) -> str:
    """Replace `__NAME__` placeholders with Python literals of `values`.

    `repr` and not string interpolation: these are Windows paths, and a
    substitution that pastes `C:\\Users\\...` into a source file produces `\\U`,
    which is a unicode escape and a `SyntaxError`.
    """
    for name, value in values.items():
        source = source.replace(name, repr(value) if isinstance(value, str)
                                else str(value))
    return source


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
    succeeded before the boundary existed, which means the patch landed on the
    *test runner's* modules and stayed there -- so a suite that ran this file
    before the repair had to survive its own fixtures.
    """

    def setUp(self) -> None:
        for holder, name in ((ACC.AcceptanceSource, "expectations"),
                             (C, "area_tolerance"), (C, "diameter_tolerance"),
                             (commission, "_tol"), (ST, "decide")):
            self.addCleanup(setattr, holder, name, getattr(holder, name))

    def _run(self, source: str, proposal: dict | None = RISER_PROPOSAL,
             *, target: Path | None = None,
             beside: dict[str, str] | None = None):
        """Lay out a project, hand the candidate `target`, and run the CLI.

        `__TARGET__` in an attack source is replaced with a literal path *after*
        the project exists. The candidate is given the address it wants -- the
        project directory, or `site-packages` -- because a boundary that works
        only while the candidate does not know where to write is not a boundary,
        it is an unlisted number.
        """
        raw = tempfile.TemporaryDirectory()
        self.addCleanup(raw.cleanup)
        directory = _laid_out(Path(raw.name), source, _project(), proposal)
        for name, text in (beside or {}).items():
            (directory / name).write_text(text, encoding="utf-8")
        if "__TARGET__" in source:
            model = directory / "model.py"
            model.write_text(
                _substitute(model.read_text(encoding="utf-8"),
                            {"__TARGET__": str(target or directory)}),
                encoding="utf-8")
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

    def _assert_no_verified_receipt(self, directory: Path) -> None:
        """Whatever else happened, nothing said the part was accepted."""
        final = directory / "final_status.json"
        if final.is_file():
            self.assertNotIn(
                json.loads(final.read_text(encoding="utf-8"))["final_status"],
                ("VERIFIED", "COMMISSIONED"),
                "the candidate reached a receipt that says the part is accepted")


@requires_confinement
class TheCandidateCannotReachTheGateTest(_AttackTest):
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


@requires_confinement
class TheChildWritesNoReceiptsTest(_AttackTest):
    """(f) and the one the defect implies: the project directory is not the
    child's to write in, and now it is not the child's to write in *at all*.

    Under the previous boundary these four succeeded at the filesystem and were
    caught afterwards by a snapshot-and-restore. The restore is gone: the write
    itself is refused by the operating system, so each of these is now a model
    that raised `PermissionError` on import. The assertions are the same ones and
    they are stronger, because "the file was never created" does not depend on
    the parent remembering to look.
    """

    def test_a_receipt_written_by_the_candidate_is_rejected(self) -> None:
        directory, code = self._run(FORGE_RECEIPT)
        self.assertNotEqual(0, code)
        self.assertFalse(
            (directory / "final_status.json").is_file(),
            "a final status the candidate wrote about itself survived the run, and "
            "`design-tool status` reads that file")
        action = _read(directory, cli.NEXT_ACTION_FILE)
        self.assertTrue(any("Permission" in problem or "final_status.json" in problem
                            for problem in action["unresolved"]),
                        action["unresolved"])

    def test_a_review_answer_written_by_the_candidate_is_rejected(self) -> None:
        directory, code = self._run(FORGE_REVIEW)
        self.assertNotEqual(0, code)
        self.assertFalse(
            (directory / "reviews" / "verification_response.json").is_file(),
            "a candidate left an independent verifier's PASS on disk for the next "
            "run of a route that reads one")

    def test_deleting_the_frozen_contract_is_refused(self) -> None:
        directory, code = self._run(DELETE_CONTRACT)
        self.assertNotEqual(0, code)
        self.assertTrue((directory / ACC.ACCEPTANCE_FILE).is_file(),
                        "the run finished with the contract it was gated against "
                        "no longer on disk")
        self.assertEqual(1, _read(directory, ACC.ACCEPTANCE_FILE)["revision"])

    def test_rewriting_the_frozen_contract_is_refused(self) -> None:
        directory, code = self._run(REWRITE_CONTRACT)
        self.assertNotEqual(0, code)
        frozen = _read(directory, ACC.ACCEPTANCE_FILE)
        row = next(feature for feature in frozen["features"]
                   if feature["feature_id"] == "pad-section")
        self.assertAlmostEqual(PROMISED_MM2, float(row["value_mm2"]), places=6,
                               msg="the file every receipt binds by hash says the "
                                   "part only ever had to be 80 mm2")
        body = {key: value for key, value in frozen.items()
                if key != "contract_sha256"}
        self.assertEqual(frozen["contract_sha256"], S.payload_hash(body))


@requires_confinement
class PortedFromTheAdversarialReviewTest(_AttackTest):
    """The three that broke `0a8e464`, and four its conclusion implies.

    Each one names a real file outside the project directory and asserts its
    bytes. Each one also *restores* that file, so that a boundary which fails
    here fails one test instead of leaving this package's own source rewritten
    for every test after it -- including the ones that would then agree with it.

    All seven fail against `893c9cc`, which is the only reason to have them.
    """

    def setUp(self) -> None:
        super().setUp()
        self._unchanged: list[tuple[Path, bytes | None]] = []

    def _guard(self, path: Path) -> None:
        """Remember a file's exact state, and put it back whatever happens."""
        before = path.read_bytes() if path.is_file() else None

        def restore() -> None:
            after = path.read_bytes() if path.is_file() else None
            if after == before:
                return
            if before is None:
                path.unlink()
            else:
                path.write_bytes(before)

        self.addCleanup(restore)
        self._unchanged.append((path, before))

    def _assert_guarded_files_did_not_move(self) -> None:
        for path, before in self._unchanged:
            after = path.read_bytes() if path.is_file() else None
            self.assertEqual(
                before, after,
                f"the candidate changed {path}, which the parent reads with the "
                "parent's own authority")

    def test_it_cannot_rewrite_a_module_the_parent_imports_after_the_build(self) -> None:
        """The lead attack, and the one that needed neither persistence nor a race.

        `backends/authored.py` is imported for the first time at `runner.py`'s
        `get_backend(...)`, which runs after `isolation.build` has returned. On
        `0a8e464` this produced exit 0, `VERIFIED`, `feature-pad-section PASS
        expected 432.0 measured 80.002`, with the contract untouched at revision
        1 and an empty `changed` list.
        """
        target = PACKAGE_ROOT / "backends" / "authored.py"
        self._guard(target)
        directory, code = self._run(LAZY_IMPORT_ATTACK)

        self.assertNotEqual(0, code)
        self._assert_guarded_files_did_not_move()
        self.assertNotIn(b"OWNED_BY_THE_CANDIDATE", target.read_bytes())
        self._assert_no_verified_receipt(directory)

    def test_it_cannot_poison_the_bytecode_cache_of_that_module(self) -> None:
        """The stealth variant: the `.py` is left byte-identical.

        Hashing the source finds nothing, which is the whole point of the attack
        and the reason source-integrity hashing is not this boundary's gate.
        """
        source = PACKAGE_ROOT / "backends" / "authored.py"
        cache = Path(importlib.util.cache_from_source(str(source)))
        self._guard(source)
        self._guard(cache)
        directory, code = self._run(POISONED_PYC_ATTACK)

        self.assertNotEqual(0, code)
        self._assert_guarded_files_did_not_move()
        self._assert_no_verified_receipt(directory)

    def test_it_cannot_rewrite_this_packages_source_for_the_next_run(self) -> None:
        """Cross-run. `pipeline/status.py` is in no project directory at all."""
        target = PACKAGE_ROOT / "status.py"
        self._guard(target)
        directory, code = self._run(SOURCE_TREE_ATTACK)

        self.assertNotEqual(0, code)
        self._assert_guarded_files_did_not_move()
        self.assertNotIn(b"OWNED_BY_THE_CANDIDATE", target.read_bytes())
        self._assert_no_verified_receipt(directory)

    def test_it_cannot_drop_a_sitecustomize_into_the_virtual_environment(self) -> None:
        """The venv is executed by every interpreter that starts with it.

        A `.pth` in `site-packages` runs its `import` line before `site` has
        finished, which is before `pipeline` exists and long before any candidate
        code does. This one is not in the review's set; it is what "cross-run via
        the writable venv" means when it is written down as a file.
        """
        import sysconfig                              # noqa: PLC0415 - local
        site = Path(sysconfig.get_paths()["purelib"])
        for name in ("sitecustomize.py", "zzz_owned.pth"):
            self._guard(site / name)
        directory, code = self._run(VENV_ATTACK)

        self.assertNotEqual(0, code)
        self._assert_guarded_files_did_not_move()
        self.assertFalse((site / "zzz_owned.pth").exists(),
                         "a candidate left a .pth in site-packages, which the next "
                         "interpreter runs before this package is imported")
        self._assert_no_verified_receipt(directory)

    def test_nothing_the_candidate_spawned_outlives_the_run(self) -> None:
        """A `DETACHED_PROCESS` grandchild is inside the job whatever it passes.

        Measured on `0a8e464`: the run reported exit 1 `FAILED`, and 25 s later
        `design-tool status` reported `VERIFIED` with nothing outstanding. The
        grandchild here sleeps 20 s and this test waits longer than that, because
        a test that finishes before the attack does proves nothing.
        """
        directory, code = self._run(GRANDCHILD_ATTACK)
        self.assertNotEqual(0, code)

        # The grandchild sleeps ten seconds and is aimed at the project directory
        # by name. This waits longer than that, because a test that finishes
        # before the attack does proves nothing.
        marker = directory / "GRANDCHILD_WAS_HERE.txt"
        deadline = time.monotonic() + 18.0
        while time.monotonic() < deadline:
            self.assertFalse(marker.is_file(),
                             "a process the candidate spawned outlived the run and "
                             "wrote into the project directory")
            time.sleep(0.5)
        self._assert_no_verified_receipt(directory)

    def test_a_grandchild_asking_to_leave_the_job_does_not_leave_it(self) -> None:
        """`CREATE_BREAKAWAY_FROM_JOB`, which is the flag that would work.

        `DETACHED_PROCESS` never left a job; it worked against `0a8e464` because
        there was no job. This is the flag whose whole purpose is to leave one,
        against a job that permits neither kind of breakaway -- and what the
        kernel does with it is measured here rather than read out of the
        documentation.
        """
        directory, code = self._run(BREAKAWAY_ATTACK)
        self.assertNotEqual(0, code)

        marker = directory / "GRANDCHILD_WAS_HERE.txt"
        deadline = time.monotonic() + 18.0
        while time.monotonic() < deadline:
            self.assertFalse(marker.is_file(),
                             "a process the candidate spawned with "
                             "CREATE_BREAKAWAY_FROM_JOB left the job that bounds "
                             "the build and outlived the run")
            time.sleep(0.5)
        self._assert_no_verified_receipt(directory)

    def test_a_junction_does_not_carry_a_write_out_of_the_sandbox(self) -> None:
        """A directory junction needs no privilege at all to create.

        `os.symlink` needs `SeCreateSymbolicLinkPrivilege` or Developer Mode; a
        junction needs neither, which makes it the reparse point an unprivileged
        candidate actually reaches for. It can create one inside the directory it
        owns. What it cannot do is write through it, because the access check
        happens against the target.
        """
        import sysconfig                              # noqa: PLC0415 - local
        site = Path(sysconfig.get_paths()["purelib"])
        self._guard(site / "OWNED_BY_THE_CANDIDATE.txt")
        directory, code = self._run(JUNCTION_ATTACK, target=site)

        self.assertNotEqual(0, code)
        self._assert_guarded_files_did_not_move()
        self._assert_no_verified_receipt(directory)

    def test_the_canary_refuses_the_run_if_the_frozen_contract_ever_moves(self) -> None:
        """The one integrity check that is kept, and it is not the gate.

        The confinement is what stops the candidate writing the contract; this
        says so if it ever did not. It cannot be exercised by a candidate any
        more -- that is the point -- so it is exercised by a thread in this test
        with the parent's own rights, which is the only party that still can.

        `ROADMAP.md` Release 2 rules that source-integrity hashing does not
        count toward this gate. This is what "a narrow canary is worth keeping"
        looks like written down: one file, checked after the job is dead, and a
        refusal that names the boundary rather than the model.
        """
        import threading                             # noqa: PLC0415 - test-only

        # One name, or the canary watches a file that is no longer the contract.
        # This is the shape that made `PARENT_OWNED` worth deleting: a second
        # list whose drift is silent.
        self.assertEqual(ACC.ACCEPTANCE_FILE, isolation.CANARY_FILE)

        raw = tempfile.TemporaryDirectory()
        self.addCleanup(raw.cleanup)
        work = Path(raw.name)
        (work / "model.py").write_text(RISER, encoding="utf-8")
        canary = work / isolation.CANARY_FILE
        canary.write_text('{"revision": 1, "value_mm2": 432.0}', encoding="utf-8")

        def rewrite() -> None:
            time.sleep(0.4)
            canary.write_text('{"revision": 1, "value_mm2": 80.0}', encoding="utf-8")

        thread = threading.Thread(target=rewrite, daemon=True)
        thread.start()
        try:
            with self.assertRaises(isolation.BuildRefused) as caught:
                isolation.build(work / "model.py", dest_dir=work, step=False)
        finally:
            thread.join(timeout=5.0)
        self.assertIn(isolation.CANARY_FILE, str(caught.exception))
        self.assertIn("failure of the boundary itself", str(caught.exception))

    def test_a_model_cannot_rewrite_its_own_source_while_it_builds(self) -> None:
        """`module_sha256` names what ran, because it is taken before it runs.

        The previous boundary hashed `model.py` after the child exited, and the
        D8 mutation "remove `model.py` from `_guarded`" survived every test. The
        input directory is now sealed read-only, and the digest is taken from the
        authoritative file before the sandbox is even built.
        """
        raw = tempfile.TemporaryDirectory()
        self.addCleanup(raw.cleanup)
        work = Path(raw.name)
        model = work / "model.py"
        model.write_text(SELF_REWRITING, encoding="utf-8")
        before = S.sha256_file(model)

        with self.assertRaises(isolation.BuildRefused):
            isolation.build(model, dest_dir=work, step=False)
        self.assertEqual(before, S.sha256_file(model),
                         "the model rewrote the file the receipt names")


@requires_confinement
class WhatTheConfinementEnforcesTest(_AttackTest):
    """Every property this boundary claims, measured by the candidate itself.

    One run, one probe model, one table. The rows that come back `ALLOWED` are
    asserted as allowed on purpose: `AppData\\LocalLow` is Low-labelled by
    Windows and therefore writable by a Low-integrity subject, DNS resolution
    goes through a service rather than a socket, and the candidate can read what
    `BUILTIN\\Users` can read. Those are this boundary's named limitations, and a
    test that asserted them closed would be the second-worst thing in this file.
    """

    DENIED = ("write_repository", "write_site_packages", "write_pipeline_source",
              "write_project_directory", "write_parent_temp", "write_startup_folder",
              "write_own_inputs", "write_own_source", "create_reparse_point",
              "network_tcp_connect", "open_parent_for_write")
    ALLOWED = ("write_build_directory", "read_project_directory",
               "write_low_integrity_profile", "dns_resolution")

    _cached: dict[str, str] = {}

    def _probe(self) -> dict[str, str]:
        """One confined run, cached: the table is the same for every assertion."""
        if WhatTheConfinementEnforcesTest._cached:
            return WhatTheConfinementEnforcesTest._cached

        import sysconfig                              # noqa: PLC0415 - local
        raw = tempfile.TemporaryDirectory()
        self.addCleanup(raw.cleanup)
        work = Path(raw.name)
        project = work / "project"
        project.mkdir()
        (project / ACC.ACCEPTANCE_FILE).write_text('{"value_mm2": 432.0}',
                                                   encoding="utf-8")

        profile = Path(os.environ.get("USERPROFILE", str(Path.home())))
        site = Path(sysconfig.get_paths()["purelib"])
        startup = (profile / "AppData" / "Roaming" / "Microsoft" / "Windows"
                   / "Start Menu" / "Programs" / "Startup")
        locallow = profile / "AppData" / "LocalLow"
        parent_temp = Path(tempfile.gettempdir())

        model = project / "model.py"
        model.write_text(_substitute(PROBE, {
            "__REPO__": str(REPO_ROOT),
            "__SITE__": str(site),
            "__PROJECT__": str(project),
            "__PARENT_TEMP__": str(parent_temp),
            "__STARTUP__": str(startup),
            "__LOCALLOW__": str(locallow),
            "__PARENT_PID__": os.getpid(),
        }), encoding="utf-8")

        # Whatever the boundary lets through has to be cleaned up, including the
        # two rows this test asserts are *allowed*.
        for directory, name in ((REPO_ROOT, "PWNED.txt"),
                                (site, "sitecustomize.py"),
                                (SCRIPTS_ROOT / "pipeline", "PWNED.py"),
                                (parent_temp, "PWNED.txt"),
                                (startup, "PWNED.cmd"),
                                (locallow, "PWNED.txt")):
            self.addCleanup(_unlink_quietly, directory / name)

        built = isolation.build(model, dest_dir=project, step=False)
        WhatTheConfinementEnforcesTest._cached = {
            "probe": dict(built.provenance["confinement_probe"]),
            "token": dict(built.provenance["child_token"]),
        }
        return WhatTheConfinementEnforcesTest._cached

    def test_the_confinement_denies_what_it_says_it_denies(self) -> None:
        report = self._probe()["probe"]
        for row in self.DENIED:
            with self.subTest(row=row):
                self.assertIn(row, report)
                self.assertNotEqual(
                    "ALLOWED", report[row],
                    f"the candidate could {row.replace('_', ' ')}")

    def test_the_named_limitations_are_still_the_named_limitations(self) -> None:
        """The gaps, asserted open, so that closing one is a visible change.

        If one of these starts coming back denied, the boundary got stronger and
        this file should say so. If a *new* row appears in `ALLOWED`, somebody
        widened it without writing it down.
        """
        report = self._probe()["probe"]
        for row in self.ALLOWED:
            with self.subTest(row=row):
                self.assertEqual(
                    "ALLOWED", report[row],
                    f"{row} is now denied; the boundary improved and neither this "
                    "test, docs/defects.md nor ROADMAP.md says so")

    def test_the_child_token_is_restricted_low_integrity_and_unprivileged(self) -> None:
        """Read out of the child's own token, not restated from the constants.

        A test that asserted `RESTRICTING_SIDS` omits `Authenticated Users` would
        be asserting that a tuple equals itself. This is what the kernel says the
        process that just built the part was running as.
        """
        token = self._probe()["token"]
        self.assertEqual(confine.LOW_INTEGRITY_SID, token["integrity"],
                         "the child did not run at low integrity, which is what "
                         "refuses the project directory and the parent's process")
        self.assertEqual([confine.KEPT_PRIVILEGE], token["privileges"],
                         "the child holds a privilege the boundary did not intend "
                         "it to; bypass-traverse-checking is the only one kept")
        self.assertTrue(token["restricting_sids"],
                        "the child's token carries no restricting SIDs, so it is "
                        "not a restricted token at all")
        self.assertNotIn(
            "S-1-5-11", token["restricting_sids"],
            "Authenticated Users back in the restricting set restores Modify on "
            "everything inherited from C:\\, which is the repository and the venv")
        self.assertIn("S-1-5-11", token["deny_only"],
                      "Authenticated Users must also be deny-only, so the ordinary "
                      "check loses it as well as the restricted one")
        self.assertNotIn(confine.user_sid(), token["deny_only"],
                         "the token's own user SID cannot be deny-only and the "
                         "process could not start if it were")


@requires_confinement
class TheOutputsAreValidatedTest(unittest.TestCase):
    """The parent adopts a file by name, and every other name is a way in.

    `_accept_artifact` had zero test references and a surviving mutation that
    matched by basename. These are the seven ways to write something Windows will
    open as `candidate.stl` without being byte-equal to it, plus the three
    filesystem shapes that are not a plain file.
    """

    def setUp(self) -> None:
        raw = tempfile.TemporaryDirectory()
        self.addCleanup(raw.cleanup)
        self.work = Path(raw.name)
        self.build_dir = self.work / "build"
        self.dest = self.work / "dest"
        self.build_dir.mkdir()
        self.dest.mkdir()
        (self.build_dir / isolation.STL_NAME).write_bytes(b"solid\n")

    def _accept(self, name):
        return isolation._accept_artifact(self.build_dir, name, self.dest, what="stl")

    def test_the_exact_name_is_accepted(self) -> None:
        path = self._accept(isolation.STL_NAME)
        self.assertEqual(b"solid\n", path.read_bytes())

    def test_every_windows_spelling_of_the_name_is_refused(self) -> None:
        for name in ("CANDIDATE.STL", "candidate.stl.", "candidate.stl ",
                     "./candidate.stl", ".\\candidate.stl", "CANDID~1.STL",
                     "candidate.stl::$DATA", "candidate.stl:payload",
                     "../../elsewhere/candidate.stl", "sub/candidate.stl",
                     "candidate.st", "candidate.stlx", "", None, 7):
            with self.subTest(name=name):
                with self.assertRaises(isolation.BuildRefused):
                    self._accept(name)

    def test_a_basename_match_is_not_a_match(self) -> None:
        """The surviving mutation, named.

        `Path(name).name == STL_NAME` accepts `..\\..\\somewhere\\candidate.stl`
        and reads whatever is there. Asserted with a file that exists at the
        traversed path, so a boundary that matched on basename would succeed
        rather than fail for the wrong reason.
        """
        outside = self.work / isolation.STL_NAME
        outside.write_bytes(b"not the candidate\n")
        with self.assertRaises(isolation.BuildRefused):
            self._accept(f"../{isolation.STL_NAME}")
        self.assertFalse((self.dest / isolation.STL_NAME).is_file())

    def test_an_alternate_data_stream_on_the_artifact_is_refused(self) -> None:
        target = self.build_dir / isolation.STL_NAME
        with open(f"{target}:payload", "w", encoding="utf-8") as handle:
            handle.write("a second stream a digest cannot see")
        self.assertIn(":payload:$DATA", confine.data_streams(target))
        with self.assertRaises(isolation.BuildRefused) as caught:
            self._accept(isolation.STL_NAME)
        self.assertIn("alternate data stream", str(caught.exception))

    def test_a_reparse_point_named_as_the_artifact_is_refused(self) -> None:
        target = self.build_dir / isolation.STL_NAME
        target.unlink()
        elsewhere = self.work / "elsewhere"
        elsewhere.mkdir()
        if not _make_junction(target, elsewhere):
            self.skipTest("this filesystem would not take a junction")
        self.assertTrue(confine.is_reparse_point(target))
        with self.assertRaises(isolation.BuildRefused) as caught:
            self._accept(isolation.STL_NAME)
        self.assertIn("reparse point", str(caught.exception))

    def test_a_build_directory_holding_a_reparse_point_is_refused(self) -> None:
        """Defence in depth, and stated as such.

        The confined candidate cannot create a reparse point at all -- `mklink /J`
        comes back `Access is denied.` and
        `WhatTheConfinementEnforcesTest` asserts that row. This guard does not
        rely on it: the parent copies out with the parent's rights, and a build
        directory that is partly somewhere else is refused before anything in it
        is read. The junction here is made by this test, at the parent's
        integrity level, which is the only party that can.
        """
        elsewhere = self.work / "elsewhere"
        elsewhere.mkdir()
        if not _make_junction(self.build_dir / "escape", elsewhere):
            self.skipTest("this filesystem would not take a junction")
        with self.assertRaises(isolation.BuildRefused) as caught:
            isolation._sweep(self.build_dir)
        self.assertIn("reparse point", str(caught.exception))

    def test_a_missing_artifact_is_a_finding_and_not_a_crash(self) -> None:
        (self.build_dir / isolation.STL_NAME).unlink()
        with self.assertRaises(isolation.BuildRefused) as caught:
            self._accept(isolation.STL_NAME)
        self.assertIn("no such file", str(caught.exception))


class TheChildContractTest(unittest.TestCase):
    """What crosses the boundary, in both directions."""

    def test_nothing_about_acceptance_crosses_into_the_child(self) -> None:
        payload = isolation.child_input(
            model_name="model.py", build_dir=Path("C:/tmp/sandbox/out"),
            input_dir=Path("C:/tmp/sandbox/in"), step=True)
        flat = json.dumps(payload)
        for forbidden in ("acceptance", "expectation", "tolerance", "feature",
                          "contract", "proposal", "value_mm2"):
            self.assertNotIn(forbidden, flat,
                             f"the child is handed {forbidden!r}, and an input the "
                             "child can see is an input the child can answer")

    def test_the_child_is_not_told_where_the_project_is(self) -> None:
        """It used to be handed the model's authoritative path.

        Which is the project directory, which is where every receipt lives. The
        candidate that forged `final_status.json` found it with
        `Path(__file__).with_name(...)`.
        """
        payload = isolation.child_input(
            model_name="model.py", build_dir=Path("C:/tmp/sandbox/out"),
            input_dir=Path("C:/tmp/sandbox/in"), step=False)
        self.assertEqual("model.py", payload["model_name"])
        for value in payload.values():
            self.assertNotIn("project", str(value))

    def test_the_child_environment_is_built_and_not_inherited(self) -> None:
        """`_child_env` had zero test references and handed over `os.environ`.

        Which named the project directory, the user, and every path this machine
        happens to have -- and `PYTHONPATH`, which is how three of the ported
        attacks found the source tree they rewrote.
        """
        build_dir = Path("C:/tmp/sandbox/out")
        env = isolation.child_environment(build_dir)
        home = str(build_dir / isolation.HOME_DIR)
        for name in ("TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA"):
            self.assertEqual(home, env[name],
                             f"{name} points outside the one writable directory")
        self.assertEqual(str(SCRIPTS_ROOT), env["PYTHONPATH"])
        self.assertEqual("1", env["PYTHONDONTWRITEBYTECODE"])
        self.assertEqual("1", env["PYTHONNOUSERSITE"])

        sentinel = "PIPELINE_TEST_SENTINEL"
        os.environ[sentinel] = "the parent's environment"
        self.addCleanup(os.environ.pop, sentinel, None)
        self.assertNotIn(sentinel, isolation.child_environment(build_dir),
                         "the parent's environment was copied, so the candidate is "
                         "handed the project, the job and every path this machine "
                         "happens to have")
        self.assertNotEqual(os.environ.get("PATH"), env["PATH"],
                            "PATH was inherited rather than constructed")

    def test_the_command_line_survives_a_path_with_spaces(self) -> None:
        command = isolation.child_command(Path("C:/a project/in/build_input.json"))
        self.assertIsInstance(command, list)
        self.assertEqual(["-m", isolation.CHILD_MODULE], command[1:3])
        self.assertTrue(command[0].endswith(("python.exe", "python", "python3",
                                             "pythonw.exe")), command[0])
        line = confine.command_line(command)
        self.assertIn(f'"{Path("C:/a project/in/build_input.json")}"', line,
                      "a project path with a space in it did not survive as one "
                      "argument")

    def test_the_build_is_bounded_in_time_and_the_bound_is_the_job(self) -> None:
        """`BUILD_TIMEOUT_S` had zero test references.

        A model with a loop in it has to be a diagnosable failure rather than a
        hung command, and the bound has to apply to the *job* -- bounding one
        process is what let a grandchild outlive `subprocess.run(timeout=)`.
        """
        self.assertGreater(isolation.BUILD_TIMEOUT_S, 60.0)
        # And it is the *default*, which is where a build with no explicit
        # timeout gets its bound from. Asserting the constant alone leaves
        # `timeout: float = 1.0e9` green.
        self.assertEqual(
            isolation.BUILD_TIMEOUT_S,
            inspect.signature(isolation.build).parameters["timeout"].default,
            "a build called without a timeout is not bounded by BUILD_TIMEOUT_S")
        raw = tempfile.TemporaryDirectory()
        self.addCleanup(raw.cleanup)
        work = Path(raw.name)
        model = work / "model.py"
        model.write_text(textwrap.dedent('''
            import time

            PARAMS = {"a": 1.0}


            def build():
                time.sleep(600)
        '''), encoding="utf-8")

        if not confine.available():
            self.skipTest(confine.unavailable_reason())
        started = time.perf_counter()
        with self.assertRaises(isolation.BuildRefused) as caught:
            isolation.build(model, dest_dir=work, step=False, timeout=3.0)
        elapsed = time.perf_counter() - started
        self.assertIn("did not finish building within", str(caught.exception))
        self.assertLess(elapsed, 60.0,
                        "the timeout did not actually stop the build")

    def test_a_manifest_from_another_protocol_is_refused(self) -> None:
        """The schema check, reachable without arranging for a child to lie.

        `CHILD_SCHEMA` moved from 1 to 2 when the child stopped being handed the
        model's authoritative path, so a manifest that still says 1 was written
        by a boundary that told the candidate where the project was.
        """
        good = {"schema_version": isolation.CHILD_SCHEMA, "ok": True,
                "model": {}, "artifacts": {}, "build": {}}
        self.assertEqual(({}, {}, {}), isolation._sections(good, 0))

        for manifest, expected in (
                ({**good, "schema_version": 1}, "this boundary speaks"),
                ({**good, "schema_version": None}, "this boundary speaks"),
                ({**good, "ok": False, "error": {"message": "the solid was empty"}},
                 "the solid was empty"),
                ({**good, "ok": False, "error": None},
                 "the build failed and said nothing"),
                ({**good, "model": None}, "missing model, artifacts or build"),
                ({**good, "build": "a string"}, "missing model, artifacts or build")):
            with self.subTest(manifest=manifest):
                with self.assertRaises(isolation.BuildRefused) as caught:
                    isolation._sections(manifest, 7)
                self.assertIn(expected, str(caught.exception))

    def test_a_manifest_that_is_not_a_json_object_is_a_finding(self) -> None:
        """`_json_object` had zero test references and is the only reader of
        anything the untrusted party wrote."""
        raw = tempfile.TemporaryDirectory()
        self.addCleanup(raw.cleanup)
        work = Path(raw.name)
        for content, expected in ((b"\xff\xfe not utf-8", "not readable JSON"),
                                  (b"{ not json", "not readable JSON"),
                                  (b"[1, 2, 3]", "is not an object"),
                                  (b'"a string"', "is not an object")):
            path = work / "build_manifest.json"
            path.write_bytes(content)
            with self.subTest(content=content):
                with self.assertRaises(isolation.BuildRefused) as caught:
                    isolation._json_object(path, isolation.MANIFEST_FILE)
                self.assertIn(expected, str(caught.exception))
        with self.assertRaises(isolation.BuildRefused):
            isolation._json_object(work / "absent.json", "absent.json")


@requires_confinement
class TheBuiltCandidateTest(_AttackTest):
    """`BuiltCandidate` and `boundary_seconds` had zero test references each."""

    def _build(self, source: str = RISER):
        raw = tempfile.TemporaryDirectory()
        self.addCleanup(raw.cleanup)
        work = Path(raw.name)
        (work / "model.py").write_text(source, encoding="utf-8")
        return work, isolation.build(work / "model.py", dest_dir=work, step=False)

    def test_the_module_digest_is_the_parents_and_is_taken_before_the_build(self) -> None:
        """Never from the manifest, and never after the candidate has run.

        The D8 mutation "take `module_sha256` from the child's own manifest"
        survived every test in the file whose docstring forbids it. `build_child`
        is asserted here to compute no digest at all, so there is nothing in the
        manifest for a future edit to reach for.
        """
        work, built = self._build()
        self.assertEqual(S.sha256_file(work / "model.py"), built.module_sha256)
        self.assertEqual({"model.py": built.module_sha256}, built.input_sha256)

        child = ast.parse((PACKAGE_ROOT / "build_child.py").read_text(encoding="utf-8"))
        calls = {node.func.attr for node in ast.walk(child)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        self.assertEqual(set(), calls & {"sha256_file", "sha256_text", "payload_hash"},
                         "the party being measured computes a digest, and a digest "
                         "the parent did not take is a claim the parent did not make")

    def test_every_staged_input_is_digested_and_the_receipt_names_them(self) -> None:
        """A model may ship a helper beside it, and then two files built the part.

        The previous boundary put the *project directory* on the child's
        `sys.path` and recorded one digest. `model_contract.json` now names every
        `*.py` the candidate was allowed to import, because a contract that names
        one of two source files names less than what ran.
        """
        directory, code = self._run(
            "from helper import PAD\n" + RISER.replace(
                "extents=(24.0, 18.0, 8.0)", "extents=(PAD, 18.0, 8.0)"),
            beside={"helper.py": "PAD = 24.0\n"})
        self.assertEqual(3, code, "the honest two-file build did not commission")

        source = _read(directory, "model_contract.json")["source"]
        self.assertEqual({"helper.py", "model.py"}, set(source["sources_sha256"]))
        self.assertEqual(S.sha256_file(directory / "helper.py"),
                         source["sources_sha256"]["helper.py"])
        self.assertEqual(source["module_sha256"],
                         source["sources_sha256"]["model.py"])

    def test_the_sandbox_and_everything_in_it_is_gone_afterwards(self) -> None:
        """Whatever the child wrote that was not asked for by name goes with it.

        A sandbox left behind is a directory holding candidate-written files, an
        input directory sealed against its own owner, and a Low mandatory label,
        one per build, forever. The parent takes write access back before it
        deletes, which is the step that makes deleting possible at all.
        """
        pattern = "design-tool-sandbox-*"
        before = set(Path(tempfile.gettempdir()).glob(pattern))
        _work, built = self._build()
        self.assertTrue(built.stl_path.is_file())
        self.assertEqual(before, set(Path(tempfile.gettempdir()).glob(pattern)),
                         "a build sandbox survived the build")

    def test_a_model_that_printed_before_it_failed_has_its_output_reported(self) -> None:
        """The child's transcript is captured, not inherited.

        This program's own stdout is the run's report and the candidate does not
        get to write on it -- but a designer's `print()` and the traceback that
        followed it are the two most useful things in a failed build, so they are
        read off a pipe and put in the refusal.
        """
        raw = tempfile.TemporaryDirectory()
        self.addCleanup(raw.cleanup)
        work = Path(raw.name)
        (work / "model.py").write_text(textwrap.dedent('''
            import sys

            print("the bore came out at", 11.94)
            sys.stdout.flush()

            PARAMS = {"a": 1.0}


            def build():
                raise RuntimeError("and then it did not close")
        '''), encoding="utf-8")
        with self.assertRaises(isolation.BuildRefused) as caught:
            isolation.build(work / "model.py", dest_dir=work, step=False)
        message = str(caught.exception)
        self.assertIn("and then it did not close", message,
                      "the builder's own failure did not reach the caller")
        self.assertIn("the bore came out at 11.94", message,
                      "the designer's print() was not captured, so the transcript "
                      "went wherever this process's stdout goes")

    def test_the_boundary_reports_what_it_cost(self) -> None:
        """`boundary_seconds` had zero test references and `timings.json` reads it.

        It has to be strictly larger than what the child measured of itself,
        because it is the same interval plus interpreter start, the sandbox and
        the copy out. A receipt whose total excludes the dominant term is a
        receipt that says a 1.7 s job took 0.05 s.
        """
        _work, built = self._build()
        self.assertGreater(built.boundary_seconds, built.build_seconds,
                           "the boundary's own cost is not inside the child's")
        self.assertTrue(built.stl_path.is_file())
        self.assertIsNone(built.step_path)

    def test_declared_parameters_that_diverge_from_the_proposal_refuse_the_run(self) -> None:
        """The divergence check no test anywhere referenced.

        `PARAMS` is what the part is built from and the proposal is what it is
        measured against; when they differ the job is building one part and
        gating another, and the D8 mutation that deleted this check survived.
        """
        source = RISER.replace('"pad_w": 24.0', '"pad_w": 99.0')
        directory, code = self._run(source)
        self.assertNotEqual(0, code)
        action = _read(directory, cli.NEXT_ACTION_FILE)
        self.assertTrue(any("pad_w" in problem for problem in action["unresolved"]),
                        action["unresolved"])


@requires_confinement
class TheBuildChildTest(unittest.TestCase):
    """`pipeline/build_child.py` is the only module that executes candidate code
    and it had no test at all.

    Run the way it is actually run -- as `-m pipeline.build_child` under the
    confinement -- because a unit test that imports it into this interpreter is a
    test that does the thing the module exists to stop.
    """

    def _run_child(self, source: str, *, step: bool = False) -> dict:
        raw = tempfile.TemporaryDirectory()
        self.addCleanup(raw.cleanup)
        sandbox = Path(raw.name)
        inputs = sandbox / "in"
        outputs = sandbox / "out"
        inputs.mkdir()
        outputs.mkdir()
        (outputs / isolation.HOME_DIR).mkdir()
        (inputs / "model.py").write_text(source, encoding="utf-8")
        spec = isolation.child_input(model_name="model.py", build_dir=outputs,
                                     input_dir=inputs, step=step)
        (inputs / isolation.INPUT_FILE).write_text(S.canonical_json(spec),
                                                   encoding="utf-8")
        confine.seal_read_only(inputs)
        confine.seal_writable(outputs)
        try:
            result = confine.run(
                isolation.child_command(inputs / isolation.INPUT_FILE),
                cwd=outputs, env=isolation.child_environment(outputs), timeout=120.0)
            manifest = outputs / isolation.MANIFEST_FILE
            payload = (json.loads(manifest.read_text(encoding="utf-8"))
                       if manifest.is_file() else None)
            return {"result": result, "manifest": payload, "outputs": outputs}
        finally:
            confine.unseal(inputs)
            confine.unseal(outputs)

    def test_a_good_model_produces_a_manifest_and_the_geometry(self) -> None:
        run = self._run_child(RISER)
        self.assertEqual(0, run["result"].returncode, run["result"].output)
        manifest = run["manifest"]
        self.assertTrue(manifest["ok"], manifest)
        self.assertEqual(isolation.CHILD_SCHEMA, manifest["schema_version"])
        self.assertEqual("candidate.stl", manifest["artifacts"]["stl"])
        self.assertIsNone(manifest["artifacts"]["step"])
        self.assertEqual("trimesh", manifest["build"]["kernel"])
        self.assertEqual(24.0, manifest["model"]["params"]["pad_w"])
        self.assertTrue((run["outputs"] / "candidate.stl").is_file())

    def test_a_builder_that_raises_is_a_manifest_and_not_a_silence(self) -> None:
        run = self._run_child(
            'PARAMS = {"a": 1.0}\n\n\ndef build():\n'
            '    raise RuntimeError("the geometry did not close")\n')
        self.assertEqual(1, run["result"].returncode)
        self.assertFalse(run["manifest"]["ok"])
        self.assertEqual("RuntimeError", run["manifest"]["error"]["kind"])
        self.assertIn("did not close", run["manifest"]["error"]["message"])

    def test_a_model_calling_sys_exit_is_a_finding_and_not_a_success(self) -> None:
        run = self._run_child(
            'import sys\n\nPARAMS = {"a": 1.0}\n\n\ndef build():\n'
            '    sys.exit(0)\n')
        self.assertFalse(run["manifest"]["ok"])
        self.assertEqual("SystemExit", run["manifest"]["error"]["kind"])

    def test_a_declaration_that_will_not_survive_the_boundary_is_named(self) -> None:
        """`PARAMS` used to be read out of a live module in the same interpreter,
        so it could hold anything at all. It is JSON now, and that is a real
        constraint on a model which is stated as one."""
        run = self._run_child(
            'import trimesh\n\n'
            'PARAMS = {"engine": object()}\n\n\n'
            'def build():\n'
            '    return trimesh.creation.box(extents=(1.0, 1.0, 1.0))\n')
        self.assertFalse(run["manifest"]["ok"])
        self.assertIn("does not survive the build boundary",
                      run["manifest"]["error"]["message"])

    def test_a_helper_module_beside_the_model_resolves(self) -> None:
        raw = tempfile.TemporaryDirectory()
        self.addCleanup(raw.cleanup)
        work = Path(raw.name)
        (work / "model.py").write_text(
            "from helper import make\n\nPARAMS = {\"a\": 1.0}\n\n\n"
            "def build():\n    return make()\n", encoding="utf-8")
        (work / "helper.py").write_text(
            "import trimesh\n\n\ndef make():\n"
            "    return trimesh.creation.box(extents=(10.0, 10.0, 10.0))\n",
            encoding="utf-8")
        built = isolation.build(work / "model.py", dest_dir=work, step=False)
        self.assertTrue(built.stl_path.is_file())

    def test_a_step_the_child_named_but_did_not_write_is_refused(self) -> None:
        """The child reports; the parent checks the file is there.

        A trimesh mesh has no B-rep to export, so `_export` writes no STEP -- and
        the manifest still names one, because the name comes from what was asked
        for. The parent is what turns that into a refusal, by looking on disk for
        every artifact it adopts instead of believing the manifest.
        """
        run = self._run_child(RISER, step=True)
        self.assertTrue(run["manifest"]["ok"], run["manifest"])
        self.assertEqual("candidate.step", run["manifest"]["artifacts"]["step"])
        self.assertFalse((run["outputs"] / "candidate.step").is_file())

        with self.assertRaises(isolation.BuildRefused) as caught:
            isolation._accept_artifact(run["outputs"], "candidate.step",
                                       run["outputs"], what="step")
        self.assertIn("no such file", str(caught.exception))


class DirectIsExemptTest(unittest.TestCase):
    """(g). `DIRECT` executes no candidate code, so it pays for no boundary.

    Proven with `sys.addaudithook`, which fires on `subprocess.Popen`, `os.exec`,
    `os.spawn` and `os.posix_spawn` regardless of which module reached them --
    and on `pipeline.confine.spawn`, which `confine.run` raises immediately
    before the one `CreateProcessAsUserW` in this package. A hook catches a
    process created through a name nobody thought to replace; the previous
    version of this test replaced `isolation.build` and `isolation.subprocess`
    and covered exactly those two.
    """

    def test_a_certified_direct_job_never_creates_a_process(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            (out / "brief.md").write_text("a certified c-clip", encoding="utf-8")
            request = _frozen_request(out, "c_clip")
            _AUDIT.clear()
            _ARMED.append(True)
            try:
                result = runner.run(request)
            finally:
                _ARMED.clear()

        self.assertEqual([], _AUDIT,
                         "DIRECT created a process; its dispatch count and its "
                         "runtime are a release gate, not a preference")
        self.assertEqual("complete", result.stage, result.message)
        self.assertEqual(0, result.llm_calls)
        self.assertEqual("DIRECT", result.final_status["route"])

    def test_the_audit_hook_is_not_asserting_nothing(self) -> None:
        """This hook's own fixture.

        A hook that never fires proves the same thing whether the boundary is
        there or not. `confine.run` raises `pipeline.confine.spawn`, so raising
        it here has to be visible.
        """
        _AUDIT.clear()
        _ARMED.append(True)
        try:
            sys.audit(confine.AUDIT_SPAWN, "python.exe", 4)
        finally:
            _ARMED.clear()
        self.assertEqual(1, len(_AUDIT), _AUDIT)


class TheParentNeverImportsTheExecutorTest(unittest.TestCase):
    """The structural claim, over the import graph rather than over one run.

    ADR 0002's gate for this work is not "does a check fire", it is "is there any
    ordering of operations in which the built artifact can influence its own
    acceptance criteria". While `cli.py` imported the module that calls
    `exec_module`, the answer was yes for every ordering, because the import
    *was* the execution.
    """

    def _module_path(self, dotted: str) -> Path | None:
        root = SCRIPTS_ROOT
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
        found = set()
        for path in PACKAGE_ROOT.rglob("*.py"):
            if path.name.startswith("test_"):
                continue
            dotted = path.relative_to(PACKAGE_ROOT).with_suffix("").as_posix()
            found.add("pipeline." + dotted.replace("/", ".").removesuffix(".__init__"))
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
        names = self._imports("pipeline.runner")
        for forbidden in ("pipeline.isolation", "pipeline.confine"):
            self.assertNotIn(forbidden, names,
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


class TheCallSitesAreAssertedTest(unittest.TestCase):
    """Guards over how a value is used, not over what a helper returns.

    D8's finding, in one sentence:
    `test_the_boundary_never_builds_a_shell_string` inspected the argv
    `child_command()` returned and never the call site, so **it could not fail
    for the thing it was named after**. Four of the surviving mutations were the
    same shape -- a protection whose weakening is invisible to any assertion
    about a return value, because the weakening is in where the value came from
    or in what order things happen.

    These are the call sites, read as syntax. They are brittle on purpose: each
    one names a specific edit that would otherwise leave every other test in
    this file green.
    """

    def test_the_boundary_never_builds_a_shell_string(self) -> None:
        """Asserted at the call site, which is the thing D8 says was missing.

        The shipped version of this test read the argv `child_command()` returned
        and never looked at how it was used, so it could not fail for the thing
        it was named after. This reads `confine.py`'s syntax tree: the one call
        that creates a process must be `CreateProcessAsUserW`, it must be given a
        non-`None` `lpApplicationName`, and `subprocess` may appear in this
        package's boundary only as `list2cmdline`.
        """
        tree = ast.parse((PACKAGE_ROOT / "confine.py").read_text(encoding="utf-8"))
        creations = [node for node in ast.walk(tree)
                     if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Attribute)
                     and node.func.attr.startswith("CreateProcess")]
        self.assertEqual(1, len(creations),
                         "there is exactly one process creation in this package")
        call = creations[0]
        self.assertEqual("CreateProcessAsUserW", call.func.attr)
        self.assertNotIsInstance(
            call.args[1], ast.Constant,
            "lpApplicationName is None, so the command line is parsed to find the "
            "executable and quoting becomes a security question")

        subprocess_uses = {node.func.attr for node in ast.walk(tree)
                           if isinstance(node, ast.Call)
                           and isinstance(node.func, ast.Attribute)
                           and isinstance(node.func.value, ast.Name)
                           and node.func.value.id == "subprocess"}
        self.assertEqual({"list2cmdline"}, subprocess_uses)

        # By syntax tree and not by substring, for the reason this whole file
        # exists: `confine.command_line`'s docstring says the words `shell=True`
        # while explaining that nothing here ever passes them, and a grep guard
        # fails on the comment that documents it and then gets deleted.
        for module in ("confine.py", "isolation.py"):
            other = ast.parse((PACKAGE_ROOT / module).read_text(encoding="utf-8"))
            shells = [node for node in ast.walk(other)
                      if isinstance(node, ast.Call)
                      for keyword in node.keywords if keyword.arg == "shell"]
            self.assertEqual([], shells, f"{module} passes a shell keyword")

    def test_the_parent_waits_for_the_job_to_empty_before_it_returns(self) -> None:
        """The ordering that the grandchild attack turned on.

        Terminating the job is not the same as the job being empty, and the
        caller reads the output directory the instant this returns. Asserted
        over the syntax tree because the alternative is a test that races the
        kernel: there must be a loop on the job's live-process count, and it must
        come after the terminate.
        """
        tree = ast.parse((PACKAGE_ROOT / "confine.py").read_text(encoding="utf-8"))
        run = next(node for node in ast.walk(tree)
                   if isinstance(node, ast.FunctionDef) and node.name == "run")
        loops = [node for node in ast.walk(run) if isinstance(node, ast.While)
                 and any(isinstance(inner, ast.Call)
                         and isinstance(inner.func, ast.Name)
                         and inner.func.id == "_active_processes"
                         for inner in ast.walk(node.test))]
        self.assertEqual(1, len(loops),
                         "nothing waits for the job's live-process count to reach "
                         "zero, so the parent can read a directory something is "
                         "still writing to")
        terminate = next(node for node in ast.walk(run)
                         if isinstance(node, ast.Call)
                         and isinstance(node.func, ast.Attribute)
                         and node.func.attr == "TerminateJobObject")
        self.assertLess(terminate.lineno, loops[0].lineno)

    def _build_body(self) -> ast.FunctionDef:
        tree = ast.parse((PACKAGE_ROOT / "isolation.py").read_text(encoding="utf-8"))
        return next(node for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and node.name == "build")

    def test_the_module_digest_is_not_derived_from_the_manifest(self) -> None:
        """The D8 mutation that no test could see.

        `module_sha256=str(model.get('module_sha256') or ...)` leaves every
        assertion in this file green, because nothing the child writes carries
        that key *yet*. The guard has to be about where the value comes from, so
        it is: the keyword must be a plain name bound before the child was
        launched, and not an expression reading anything the child produced.
        """
        call = next(node for node in ast.walk(self._build_body())
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "BuiltCandidate")
        keyword = next(keyword for keyword in call.keywords
                       if keyword.arg == "module_sha256")
        self.assertIsInstance(
            keyword.value, ast.Name,
            "the parent's module digest is an expression rather than a value it "
            "computed before the candidate existed")

    def test_the_build_directory_is_swept_before_anything_in_it_is_read(self) -> None:
        """Ordering, because the check is worth nothing after the read.

        A junction in the build directory is a directory whose contents are
        somewhere else, and the parent walks it with the parent's rights. The
        confined candidate cannot make one -- but `_sweep` must still run, and it
        must run before `_json_object` opens the manifest.
        """
        body = self._build_body()
        calls = [node.func.id for node in ast.walk(body)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
        self.assertIn("_sweep", calls, "the build directory is never swept")
        self.assertLess(calls.index("_sweep"), calls.index("_json_object"),
                        "the manifest is read out of a directory that has not been "
                        "checked for reparse points")

    def test_the_child_inherits_only_the_handles_it_is_given(self) -> None:
        """`bInheritHandles=TRUE` with no handle list hands over everything.

        Every inheritable handle this process holds -- open project files, the
        parent's own log -- would cross. The list is what makes the flag safe, so
        the two are asserted together.
        """
        source = (PACKAGE_ROOT / "confine.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        updates = [node for node in ast.walk(tree)
                   if isinstance(node, ast.Call)
                   and isinstance(node.func, ast.Attribute)
                   and node.func.attr == "UpdateProcThreadAttribute"]
        self.assertEqual(1, len(updates))
        self.assertTrue(any(isinstance(arg, ast.Name)
                            and arg.id == "PROC_THREAD_ATTRIBUTE_HANDLE_LIST"
                            for arg in updates[0].args),
                        "the only process-thread attribute set is not the handle "
                        "list, so the child inherits whatever it inherits")
        self.assertIn("EXTENDED_STARTUPINFO_PRESENT", source,
                      "an attribute list that is not announced is not applied")

    def test_the_confinement_is_not_optional_on_an_unsupported_platform(self) -> None:
        """A boundary that degrades to an ordinary subprocess is not a boundary.

        Asserted over the source because there is only one machine to run it on:
        `isolation.build` must consult `confine.unavailable_reason` and refuse,
        and there must be no branch that runs the candidate without it.
        """
        source = (PACKAGE_ROOT / "isolation.py").read_text(encoding="utf-8")
        self.assertIn("unavailable_reason", source)
        tree = ast.parse(source)
        runners = [node for node in ast.walk(tree)
                   if isinstance(node, ast.Call)
                   and isinstance(node.func, ast.Attribute)
                   and node.func.attr == "run"
                   and isinstance(node.func.value, ast.Name)
                   and node.func.value.id == "confine"]
        self.assertEqual(1, len(runners),
                         "there is one place the candidate is executed")


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _make_junction(link: Path, target: Path) -> bool:
    """A directory junction, which needs no privilege. Returns whether it took."""
    if os.name != "nt":                               # pragma: no cover - platform
        return False
    import subprocess                                 # noqa: PLC0415 - test-only
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True, check=False)
    return completed.returncode == 0 and confine.is_reparse_point(link)


# One audit hook for the whole process: `sys.addaudithook` cannot be removed, so
# it is installed once at import and gated by a flag rather than added per test.
_AUDIT: list[str] = []
_ARMED: list[bool] = []
_WATCHED = (confine.AUDIT_SPAWN, "subprocess.Popen", "os.exec", "os.spawn",
            "os.posix_spawn", "os.fork")


def _audit_hook(event: str, args: tuple) -> None:
    if _ARMED and event.startswith(_WATCHED):
        _AUDIT.append(f"{event} {args!r}"[:200])


sys.addaudithook(_audit_hook)


if __name__ == "__main__":                        # pragma: no cover
    unittest.main()
