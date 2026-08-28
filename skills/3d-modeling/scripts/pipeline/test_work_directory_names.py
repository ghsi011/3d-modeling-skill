#!/usr/bin/env python3
"""D46: the pipeline's own receipts get their names from the registry.

The runner wrote ten artifacts into the work directory, eight of them by bare
string literal, while `bindings` separately named five of those eight -- and
neither consulted the other. Two consequences were visible in the source before
anything went wrong:

* **one artifact, three names.** The execution plan was spelled by
  `execution.EXECUTION_PLAN_FILE`, re-exported as `cli.EXECUTION_PLAN_FILE`, and
  named a third time as `bindings.PLAN_FILE`;
* **one name, two artifacts.** That third spelling collided with
  `cli.PLAN_FILE`, which meant the print engineer's `print_plan_checks.json`.
  `cli` imports `bindings`, so both were live in one namespace.

Nothing is renamed here. Every artifact keeps the name it has today, which is
what `TODAYS_NAMES` pins: a test that asked the registry what it holds would
agree with any rename, so the spellings are written out instead.

**Two methods, densely subtested, and that is deliberate.** `conftest.py` caps
L0 collection at `L0_COLLECTED_CEILING` and the gate is at it, so a fixture here
costs a ruling rather than a line -- and a ceiling is a conversation rather than
a number to route around. Each subtest below names the claim it carries.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from . import artifact_names as N
from . import bindings as B
from . import cli
from . import execution as EX
from . import runner
from .test_pipeline import _run_full_looked

PACKAGE = Path(__file__).resolve().parent

#: The name every registered artifact has today, written out rather than read
#: back off the registry. This is the preservation row: a rename that moved a
#: replay golden or a pinned certified contract fails here first, on the name.
TODAYS_NAMES = {
    "VERIFICATION_REPORT": "verification_report.json",
    "PIPELINE_VERIFICATION_REPORT": "pipeline_verification_report.json",
    "INTENT_MANIFEST": "intent_manifest.json",
    "SPECIFICATION": "specification.json",
    "EXECUTION_PLAN": "execution_plan.json",
    "MODEL_CONTRACT_FILE": "model_contract.json",
    "PIPELINE_RECEIPT": "pipeline_artifact_receipt.json",
    "COMMISSION_REPORT": "commission_report.json",
    "MANUFACTURING_REPORT": "manufacturing_report.json",
    "SAFETY_VERIFICATION_REPORT": "safety_verification_report.json",
    "FINAL_STATUS": "final_status.json",
    "TIMINGS": "timings.json",
    "BACKEND_RECORD": "backend_build_record.json",
}

#: The two modules this ticket makes literal-free for a registered name: the one
#: that writes the receipts and the one that tables them. The rest of the
#: package still reads some of these names as literals, and sweeping those is a
#: later ticket -- claiming it here would be asserting something untrue.
LITERAL_FREE = ("runner.py", "bindings.py")


def _modules() -> list[Path]:
    """Every module of the pipeline package, its tests excluded."""
    return [path for path in sorted(PACKAGE.rglob("*.py"))
            if not path.name.startswith("test_")]


def _spells(path: Path, name: str) -> bool:
    """Whether `path` writes `name` out as a quoted literal.

    Quoted, so that the prose naming these files in docstrings and comments --
    which is how a reader of this package learns what each receipt is -- is not
    read as a second declaration of the name.
    """
    text = path.read_text(encoding="utf-8")
    return f'"{name}"' in text or f"'{name}'" in text


class TheReceiptNamesComeFromTheRegistryTest(unittest.TestCase):
    """**This proves the pipeline's receipt names have one declaration each,
    because it fails when any of them is written out a second time.**

    `Y` is the implementation this replaces: `runner.py` composing
    `out / "final_status.json"` and `bindings.RECEIPTS` restating the same
    filenames beside it. Run that way -- a literal put back in the runner, a
    literal put back in the table, or `_write` degenerating into a join -- the
    subtests below fail. All three are in
    `benchmarks/mutations/d46-work-directory-names.json` and all three were run.
    """

    def test_the_pipeline_names_its_receipts_only_through_the_registry(self) -> None:
        pipeline_owned = {name for name, owner in N._OWNERS.items()
                          if owner == N.PIPELINE}
        self.assertTrue(pipeline_owned, "the registry came back empty")

        with self.subTest("every artifact keeps the name it has today"):
            self.assertEqual(
                TODAYS_NAMES,
                {attribute: getattr(N, attribute) for attribute in TODAYS_NAMES})

        for module in LITERAL_FREE:
            path = PACKAGE / module
            for name in sorted(pipeline_owned):
                with self.subTest(module=module, name=name):
                    self.assertFalse(
                        _spells(path, name),
                        f"{module} writes {name!r} out instead of taking it "
                        "from artifact_names")

        with self.subTest("the receipt table is registered, entry by entry"):
            tabled = {receipt.name for receipt in B.RECEIPTS} | set(B.REMOVABLE)
            self.assertTrue(tabled)
            self.assertEqual(set(), tabled - pipeline_owned)

        with self.subTest("the execution plan is declared in exactly one place"):
            declaring = [path.name for path in _modules()
                         if _spells(path, N.EXECUTION_PLAN)]
            self.assertEqual(["artifact_names.py"], declaring)

        with self.subTest("the three duplicate constants are gone, not aliased"):
            for module, attribute in ((EX, "EXECUTION_PLAN_FILE"),
                                      (cli, "EXECUTION_PLAN_FILE"),
                                      (B, "PLAN_FILE")):
                self.assertFalse(hasattr(module, attribute),
                                 f"{module.__name__}.{attribute} is still bound")

        with self.subTest("PLAN_FILE no longer names two artifacts"):
            # The survivor is named for what it is. `cli` imports `bindings`, so
            # `hasattr` here is asking about the shared namespace and not only
            # about this module's own assignments.
            self.assertFalse(hasattr(cli, "PLAN_FILE"))
            self.assertEqual("print_plan_checks.json", cli.PRINT_PLAN_CHECKS_FILE)
            self.assertNotEqual(N.EXECUTION_PLAN, cli.PRINT_PLAN_CHECKS_FILE)

        with self.subTest("the runner's write is resolved, not joined"):
            # `_write` takes a directory and a name rather than a finished path
            # precisely so this cannot be composed around. The verifier's team
            # contract is the name to try: it is registered, and to somebody
            # else.
            with tempfile.TemporaryDirectory() as raw:
                with self.assertRaises(N.NameConflict):
                    runner._write(Path(raw), N.VERIFICATION_REPORT, {})
                self.assertFalse((Path(raw) / N.VERIFICATION_REPORT).exists())


class ACertifiedBackendMayNotClaimAReceiptsNameTest(unittest.TestCase):
    """**This proves the registry decides who holds a name, because it fails
    when a certified backend claims the final-status name.**

    `Y` is a certified backend writing its build record to
    `final_status.json` -- the file that says what the run concluded, and the
    one `design-tool status` and every reader treat as the job's answer. Two
    shapes of it are in
    `benchmarks/mutations/d46-work-directory-names.json` and both were run:

    * through the registry, which is refused, so the build raises and the run
      never reaches VERIFIED;
    * as a bare join, which is the pre-registry shape and is *not* refused --
      the record lands on the status file, the runner overwrites it at the end,
      and no build record is left on disk.

    The second is why the first is worth asserting. A run that merely broke
    would prove an exception was raised somewhere; these two together separate
    "the registry refused the claim" from "nothing was watching the name".
    """

    def test_a_certified_backend_may_not_write_the_pipelines_final_status(self) -> None:
        work = Path("work")
        with self.assertRaises(N.NameConflict) as caught:
            N.path(work, N.FINAL_STATUS, owner=N.BACKEND)
        self.assertIn(N.PIPELINE, str(caught.exception))
        self.assertEqual(N.PIPELINE, N._OWNERS[N.FINAL_STATUS],
                         "the refused claim moved the owner anyway")
        # The backend's own name still resolves for the backend, so the refusal
        # above is about ownership and not about `path` refusing everything.
        self.assertEqual(work / N.BACKEND_RECORD,
                         N.path(work, N.BACKEND_RECORD, owner=N.BACKEND))

        # And end to end, because the claim that matters is about the writer in
        # the source rather than about a call this test made up: a real
        # certified run leaves two distinct documents, each at its owner's name.
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result = _run_full_looked(out)
            self.assertTrue(result.ok,
                            f"the run stopped at {result.stage}: {result.message}")
            self.assertEqual("VERIFIED", result.final_status["final_status"],
                             "the run must actually reach the backend's write "
                             "and the status write, or this proves nothing")
            self.assertTrue((out / N.BACKEND_RECORD).is_file(),
                            "the certified backend wrote its record somewhere "
                            "other than the name it holds")
            record = json.loads(
                (out / N.BACKEND_RECORD).read_text(encoding="utf-8"))
            final = json.loads(
                (out / N.FINAL_STATUS).read_text(encoding="utf-8"))
        self.assertEqual("backend-build", record["record"])
        self.assertEqual("VERIFIED", final["final_status"])
        self.assertNotIn("record", final)


if __name__ == "__main__":
    unittest.main()
