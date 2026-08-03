#!/usr/bin/env python3
"""Release 3's context-budget foundation: what a job costs, and what it may cost.

Everything here fails on the code as it stood before `pipeline/cost.py` existed,
and for one reason: nothing measured any of it. `JobResult.llm_calls` was printed
to stderr and written down nowhere, `docs/baseline.md` held four hand-taken
wall-clock figures, and the two numbers this file exists to produce -- what a
review round trip costs in repeated builds, and what a second formulation costs
over the first -- had never been produced by anything.

Where a test shows a protection holding, its neighbour mutates the protection and
shows the loss is reachable. The protection here is the plan's dispatch ceiling:
`cost.budget` reads it off the compiled plan, `runner.run` refuses a run that
spends past it, and `cli._commission_authored` refuses a commission the plan did
not budget. Shrinking a ceiling has to turn a passing run into a refusal, or the
check is not being consulted.

The half of this file the commit gate will not carry is in
`benchmarks/heavy/test_cost_heavy.py`: the authored lane pays a confined child
interpreter, which the root `conftest.py` refuses inside the gate. What stayed
here answers in this process.
"""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from . import cli
from . import cost as COST
from . import execution as EX
from . import project as P
from . import runner
from . import schemas as S
from . import selftest as ST

# The certified fixtures, imported rather than restated -- two spellings of one
# fixture is how two files stop testing the same thing.
from .test_pipeline import (  # noqa: E402
    CLIP,
    _full_request,
    _looked_at,
    _request,
)

UTC = "1970-01-01T00:00:00Z"

SAFETY_REVIEWER = {"model_snapshot": "m", "prompt_hash": "p", "policy_version": "1",
                   "reasoning_settings": "none", "inference_config": "{}",
                   "image_preprocessing": "none"}


def _safety_pass(packet):
    payload = getattr(packet, "payload", packet)
    response = {"decision": "PASS", "failure_modes": [], "safety_concerns": [],
                "missing_evidence": [], "required_actions": [], "summary": "ok"}
    if isinstance(payload, dict) and "review_envelope" in payload:
        response["review_envelope"] = payload["review_envelope"]
    return response


def _ledger(work_dir: Path) -> dict:
    return json.loads((work_dir / COST.COST_FILE).read_text(encoding="utf-8"))


def _certified(root: Path, **over) -> Path:
    """A project the certified template covers: one route, no dispatch, no child."""
    directory = root / "project"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "brief.md").write_text("a clip", encoding="utf-8")
    base = dict(
        job_id="cost", updated_utc=UTC, source_mode="NEW",
        consequence="INCONSEQUENTIAL",
        consequence_rationale="a desk clip; failure wastes material",
        printer="Test Printer", material={"process": "FDM", "material": "PLA"},
        nozzle={"diameter_mm": 0.4},
        orientation={"model_to_printer_matrix": "identity", "bed_z_mm": 0.0},
        template="c_clip", parameters=dict(ST.FROZEN_PARAMETERS["c_clip"]),
        model=None, envelope_mm=None, reviewer={"model_snapshot": "test"},
    )
    base.update(over)
    P.Project(**base).save(directory)
    return directory


def _authored_but_unwritten(root: Path) -> Path:
    """An authored project whose designer has not delivered yet.

    The commission is written and the run stops, so nothing here builds geometry
    and nothing starts a child interpreter -- which is why the one dispatch
    `llm_calls` never counted can be measured inside the commit gate.
    """
    directory = root / "project"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "brief.md").write_text("a block, 40 x 30 x 10", encoding="utf-8")
    P.Project(
        job_id="cost", updated_utc=UTC, source_mode="NEW",
        consequence="INCONSEQUENTIAL",
        consequence_rationale="a desk block; failure wastes material",
        printer="Test Printer", material={"process": "FDM", "material": "PLA"},
        nozzle={"diameter_mm": 0.4},
        orientation={"model_to_printer_matrix": "identity", "bed_z_mm": 0.0},
        template=None, parameters={}, model="model.py",
        envelope_mm={"x": 60.0, "y": 50.0, "z": 20.0},
        reviewer={"model_snapshot": "test"}).save(directory)
    return directory


def _quiet(call, *argv) -> int:
    with contextlib.redirect_stderr(io.StringIO()):
        return call(list(argv))


def _answer_on_disk(work_dir: Path, kind: str) -> None:
    """Echo the packet's own envelope back with a closed PASS, the way an agent does."""
    room = work_dir / cli.REVIEW_DIR
    packet = json.loads((room / f"{kind}_packet.json").read_text(encoding="utf-8"))
    body = ({"decision": "PASS", "failure_modes": [], "safety_concerns": [],
             "missing_evidence": [], "required_actions": [], "summary": "ok"}
            if kind == "safety" else
            {"decision": "PASS", "defects": [], "unmet_requirements": [],
             "missing_evidence": [], "summary": "nothing undeclared visible"})
    (room / f"{kind}_response.json").write_text(
        S.canonical_json({**body,
                          "review_envelope": packet["review_envelope"]}),
        encoding="utf-8")


def _status(directory: Path) -> dict:
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(io.StringIO()):
        cli.status([str(directory), "--json"])
    return json.loads(stream.getvalue())


# ---------------------------------------------------------------------------
# The ledger: one entry per invocation, and the totals over them
# ---------------------------------------------------------------------------

class TheLedgerRecordsWhatARunSpentTest(unittest.TestCase):
    """`cost.json` beside the receipts, holding what no receipt holds."""

    def test_a_certified_run_writes_one_invocation_and_dispatches_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result = runner.run(_request(out))
            self.assertTrue((out / COST.COST_FILE).is_file(),
                            "a run that recorded no cost is a run nobody can "
                            "hold to a budget")
            totals = COST.totals_at(out)
            self.assertEqual(1, totals["invocations"])
            self.assertEqual(1, totals["builds"])
            self.assertEqual(0, totals["dispatches"])
            self.assertEqual(0, result.llm_calls)
            self.assertGreater(totals["deterministic_seconds"], 0.0)

    def test_the_ledger_counts_the_same_dispatches_the_runner_does(self) -> None:
        """One counter, not two.

        `llm_calls` is the number this repository already publishes and freezes
        (`docs/baseline.md`, `benchmarks/heavy/test_frozen_heavy.py`). The ledger
        entry sits beside the increment rather than replacing it, so the two
        cannot disagree -- and this is what says so on every route that
        dispatches anything.
        """
        cases = {
            "DIRECT/INCONSEQUENTIAL": (lambda out: runner.run(_request(out)), 0),
            "DIRECT/CONSEQUENTIAL": (
                lambda out: runner.run(_request(
                    out, consequence="CONSEQUENTIAL", safety_call=_safety_pass,
                    reviewer=SAFETY_REVIEWER)), 1),
            "FULL": (
                lambda out: runner.run(_full_request(
                    out, verify_call=_looked_at,
                    reviewer={"model_snapshot": "test"})), 2),
        }
        for name, (call, expected) in sorted(cases.items()):
            with self.subTest(route=name), tempfile.TemporaryDirectory() as raw:
                out = Path(raw)
                result = call(out)
                totals = COST.totals_at(out)
                self.assertEqual(expected, result.llm_calls, name)
                self.assertEqual(result.llm_calls, totals["reviews"],
                                 "the ledger and `llm_calls` are one count")

    def test_the_context_each_reviewer_was_handed_is_measured_in_bytes(self) -> None:
        """Section 15.6's `context size`, taken where the context is handed over.

        Bytes and not tokens: there is no tokenizer here, and a fabricated token
        count would be a worse number than an honest byte count.
        """
        handed: dict[str, int] = {}

        def watched_spec(request):
            handed["spec"] = COST.context_bytes(request)
            from .test_pipeline import _full_spec
            return _full_spec(request)

        def watched_verify(packet):
            handed["verification"] = COST.context_bytes(packet.payload)
            return _looked_at(packet)

        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            runner.run(_full_request(out, spec_call=watched_spec,
                                     verify_call=watched_verify,
                                     reviewer={"model_snapshot": "test"}))
            rows = {row["kind"]: row["context_bytes"]
                    for row in _ledger(out)["invocations"][0]["dispatches"]}
            self.assertEqual(handed, rows,
                             "the recorded size must be the size of the payload "
                             "the reviewer was actually given")
            self.assertGreater(rows["verification"], 1000,
                               "a verification packet carries the intent, the "
                               "contract, the manifest and the commissioning "
                               "report; a three-figure number would mean the "
                               "wrong object was measured")

    def test_a_resumed_run_is_not_charged_for_a_question_nobody_asked_twice(self) -> None:
        """The accounting error the ledger found in the counter it reuses.

        `design-tool run` is resumable by re-running, and the invocation that
        finishes a job re-reads every answer written for it -- incrementing
        `llm_calls` again for each. This job asks two questions and takes three
        invocations, and summing `llm_calls` over them gives 0 + 1 + 2 = 3.
        Two were asked. The ledger counts the question at the pause that wrote
        the packet and records the re-reads as reuse, so the dispatch count is
        the number of times somebody was actually asked something.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _certified(Path(raw), consequence="CONSEQUENTIAL",
                                   verification_requested=True)
            seen = []
            for _ in range(3):
                seen.append(_quiet(cli.run, str(directory), "--no-render"))
                pending = json.loads((directory / cli.NEXT_ACTION_FILE)
                                     .read_text(encoding="utf-8"))
                if pending.get("kind") != "REVIEW":
                    break
                _answer_on_disk(directory, pending["review_kind"])

            totals = COST.totals_at(directory)
            self.assertEqual(3, totals["invocations"])
            self.assertEqual(2, totals["reviews"],
                             "two questions: one safety, one verification")
            self.assertEqual(3, totals["reviews_reused"],
                             "and three re-reads of the two answers, which is "
                             "what `llm_calls` counts as three dispatches")
            self.assertEqual(3, totals["builds"])
            self.assertEqual(2, totals["repeated_builds"])
            self.assertEqual(
                sum((row["reviews"] + row["reviews_reused"])
                    for row in [totals]),
                5, "five review calls in total, of which two were questions")

    def test_a_run_that_produced_no_claim_is_recorded_rather_than_absent(self) -> None:
        """15.6's `failed work`: seconds spent by a run that concluded nothing."""
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result = runner.run(_request(
                out, consequence="CONSEQUENTIAL",
                safety_call=lambda p: {"decision": "BANANA", "summary": "?"},
                reviewer=SAFETY_REVIEWER))
            self.assertFalse(result.ok)
            entry = _ledger(out)["invocations"][0]
            self.assertFalse(entry["ok"])
            self.assertEqual("safety", entry["stage"])
            self.assertEqual(1, COST.totals_at(out)["failed_invocations"])
            self.assertEqual(1, COST.totals_at(out)["builds"],
                             "the geometry was built and then the run stopped; "
                             "that build is spent whatever the claim says")

    def test_repeated_builds_are_counted_across_invocations(self) -> None:
        """15.6's `repeated work`, which no single-run record can express."""
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            runner.run(_request(out))
            runner.run(_request(out))
            runner.run(_request(out))
            totals = COST.totals_at(out)
            self.assertEqual(3, totals["invocations"])
            self.assertEqual(3, totals["builds"])
            self.assertEqual(2, totals["repeated_builds"])

    def test_a_cache_hit_is_recorded_and_avoided_no_build(self) -> None:
        """The finding, measured rather than asserted.

        `runner.run` consults the cache *after* `backend.build` returns, so a hit
        confirms the bytes and saves nothing. `builds_avoided` is the number that
        would move if that ever changed, and it is zero here because the second
        run built the part again and then agreed with itself.
        """
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            (out / "cache").mkdir()
            runner.run(_request(out, cache_dir=out / "cache"))
            runner.run(_request(out, cache_dir=out / "cache"))
            totals = COST.totals_at(out)
            self.assertEqual({"stored": 1, "hit": 1}, totals["cache"])
            self.assertEqual(2, totals["builds"])
            self.assertEqual(0, totals["builds_avoided"],
                             "a hit that still ran the build avoided nothing, and "
                             "a cache-reuse figure that said otherwise would be "
                             "reporting a saving nobody made")

    def test_an_unreadable_ledger_is_not_overwritten(self) -> None:
        """`lifecycle.record`'s rule: the record of what was spent is not lost."""
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            (out / COST.COST_FILE).write_text("{not json", encoding="utf-8")
            ledger = COST.Ledger(job_id="cost")
            with self.assertRaises(S.SchemaError):
                COST.append(out, ledger, ledger.invocation(ok=True, stage="x"))
            self.assertEqual("{not json",
                             (out / COST.COST_FILE).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The budget: declared by the plan, checked against what was spent
# ---------------------------------------------------------------------------

class TheFrozenDispatchBudgetTest(unittest.TestCase):
    """The four numbers `docs/baseline.md` has always carried, pinned in code.

    The goldens live in `pipeline/cost.py`, which ships inside the bundle, for
    `selftest.FROZEN_CONTRACTS`'s reason: two copies of a golden is two goldens
    and the one nobody runs is the one that drifts.
    """

    def _plan(self, **kw) -> EX.ExecutionPlan:
        base = dict(job_id="cost", template="c_clip", parameters=dict(CLIP),
                    external_geometry=False, ambiguities=(),
                    consequence="INCONSEQUENTIAL")
        base.update(kw)
        return EX.from_job_request(**base)

    def test_each_route_compiles_to_the_dispatch_count_that_is_frozen(self) -> None:
        cases = {
            "DIRECT": self._plan(),
            "FITTED": self._plan(external_geometry=True),
            "FULL": self._plan(parameters={**CLIP, "bore_d": 60.0}),
        }
        for route, plan in sorted(cases.items()):
            with self.subTest(route=route):
                self.assertEqual(route, plan.route)
                self.assertEqual(COST.FROZEN_REVIEW_DISPATCH[route],
                                 COST.budget(plan)["reviews"],
                                 f"{route}'s review dispatch count moved. "
                                 "ROADMAP.md 3.4 forbids a release adding an AI "
                                 "round trip to an existing path as a side "
                                 "effect; moving it here is how a release says "
                                 "it meant to.")

    def test_consequence_adds_exactly_one_safety_review_and_no_more(self) -> None:
        for route, params, external in (("DIRECT", CLIP, False),
                                        ("FITTED", CLIP, True),
                                        ("FULL", {**CLIP, "bore_d": 60.0}, False)):
            with self.subTest(route=route):
                cheap = self._plan(parameters=params, external_geometry=external)
                dear = self._plan(parameters=params, external_geometry=external,
                                  consequence="CONSEQUENTIAL")
                self.assertEqual(
                    COST.budget(cheap)["reviews"] + COST.FROZEN_SAFETY_DISPATCH,
                    COST.budget(dear)["reviews"],
                    "consequence adds the mandatory safety pass and never a "
                    "geometric review; `route._verification_reasons` says so and "
                    "this is the cost side of the same statement")

    def test_authored_geometry_costs_exactly_one_commission(self) -> None:
        """The dispatch `llm_calls` cannot see, in the budget it belongs to."""
        certified = self._plan()
        authored = self._plan(authored=True)
        self.assertEqual(0, COST.budget(certified)["commissions"])
        self.assertEqual(COST.FROZEN_COMMISSION_DISPATCH,
                         COST.budget(authored)["commissions"])

    def test_a_route_that_owes_a_recovery_it_cannot_run_budgets_none(self) -> None:
        """The obligation is not the ability.

        An authored `FULL` job owes a specification and no certified bounds exist
        to recover into, so the lane is `UNSUPPORTED` and nothing is dispatched.
        A ceiling read off `required_reviews` rather than off
        `dispatches_specification` would budget a call that can never happen and
        would forgive one that should not.
        """
        plan = self._plan(parameters={**CLIP, "bore_d": 60.0}, authored=True)
        self.assertTrue(plan.requires_specification)
        self.assertFalse(plan.dispatches_specification)
        self.assertEqual("UNSUPPORTED", plan.lane_status)
        self.assertEqual(1, COST.budget(plan)["reviews"],
                         "the verification it can run, and not the specification "
                         "it cannot")


class ADispatchThePlanDidNotBudgetIsRefusedTest(unittest.TestCase):
    """The mutation: shrink the ceiling and the same run has to stop.

    ROADMAP.md 4.3 asks for a test showing the principal protection can fail.
    The protection is the ceiling, so the mutation is applied to the ceiling and
    not to the run: the job below is a correct job that dispatches exactly what
    its route requires, and the only thing that changes is what it is allowed to
    dispatch. If this passes without a refusal, `runner.run` is not consulting
    the budget at all and every other test in this file is measuring a number
    nothing acts on.
    """

    @contextlib.contextmanager
    def _ceiling(self, **over):
        original = COST.budget
        COST.budget = lambda plan: {**original(plan), **over}
        try:
            yield
        finally:
            COST.budget = original

    def test_a_safety_review_outside_the_budget_stops_the_run(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            with self._ceiling(reviews=0):
                result = runner.run(_request(
                    out, consequence="CONSEQUENTIAL", safety_call=_safety_pass,
                    reviewer=SAFETY_REVIEWER))
            self.assertFalse(result.ok, "a run that spent past its plan's ceiling "
                                        "must not come back successful")
            self.assertEqual("cost", result.stage)
            self.assertIn("bounded review", result.message)
            self.assertEqual(["cost"],
                             [row["stage"] for row in _ledger(out)["invocations"]])
            self.assertTrue(COST.totals_at(out)["overruns"],
                            "the overrun is recorded, not only reported")

    def test_the_same_run_inside_its_budget_is_untouched(self) -> None:
        """The other half of the pair: the ceiling must not fail a correct job."""
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            result = runner.run(_request(
                out, consequence="CONSEQUENTIAL", safety_call=_safety_pass,
                reviewer=SAFETY_REVIEWER))
            self.assertEqual("complete", result.stage)
            self.assertEqual([], COST.totals_at(out)["overruns"])

    def test_a_commission_outside_the_budget_stops_before_the_designer(self) -> None:
        """The dispatch that happens in the CLI, guarded by the same ceiling."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _authored_but_unwritten(Path(raw))
            with self._ceiling(commissions=0):
                self.assertEqual(1, _quiet(cli.run, str(directory), "--no-render"))
            self.assertTrue(COST.totals_at(directory)["overruns"])


# ---------------------------------------------------------------------------
# The commission: the dispatch that was never counted
# ---------------------------------------------------------------------------

class TheDesignerCommissionIsADispatchTest(unittest.TestCase):
    """`AGENT_COMMISSION` is the live dispatch on the authored lane.

    `tools/replay.py` says so in as many words and refuses to replay a case that
    provokes one; `runner.llm_calls` could never see it, because `cli.py` returns
    before the runner is reached. `docs/baseline.md` prices the `CUSTOM` riser at
    one call and that one is this -- counted by a person, because nothing in the
    build counted it.
    """

    def test_the_commission_is_counted_and_its_context_is_measured(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _authored_but_unwritten(Path(raw))
            self.assertEqual(cli.NEEDS_ACTION,
                             _quiet(cli.run, str(directory), "--no-render"))
            totals = COST.totals_at(directory)
            self.assertEqual(1, totals["commissions"])
            self.assertEqual(0, totals["reviews"])
            self.assertEqual(0, totals["builds"],
                             "the designer has not delivered, so nothing was built")

            row = _ledger(directory)["invocations"][0]["dispatches"][0]
            self.assertEqual("commission", row["kind"])
            self.assertGreater(row["context_bytes"], row["instruction_bytes"],
                               "the context is the instruction plus every file it "
                               "authorises the agent to read; counting only the "
                               "instruction would price a commission at a few "
                               "kilobytes of JSON and leave the brief, the "
                               "project file and the plans unmeasured")
            instruction = json.loads(
                (directory / cli.NEXT_ACTION_FILE).read_text(encoding="utf-8"))
            named = {name for name in instruction["authorized_inputs"]
                     if (directory / name).is_file()}
            self.assertEqual(named, set(row["named_input_bytes"]),
                             "every authorised input that exists is measured, and "
                             "one that does not contributes nothing rather than "
                             "an estimate")

    def test_a_second_unanswered_run_is_a_second_commission(self) -> None:
        """Re-running without delivering asks again, and that is repeated work."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _authored_but_unwritten(Path(raw))
            _quiet(cli.run, str(directory), "--no-render")
            _quiet(cli.run, str(directory), "--no-render")
            self.assertEqual(2, COST.totals_at(directory)["commissions"])
            self.assertEqual(2, COST.totals_at(directory)["invocations"])


# ---------------------------------------------------------------------------
# Per-alternative incremental cost
# ---------------------------------------------------------------------------

class WhatASecondFormulationCostsTest(unittest.TestCase):
    """ARCHITECTURE.md 15.2's `record incremental cost per alternative`.

    The vent-ball branch exercise measured this by hand: a sibling cost a full
    build and a full audit with nothing shared. Here the pipeline produces the
    number, on the lane that builds in this process.
    """

    # Built once for the class. Both tests below only read it, and building the
    # fork twice would pay for two more certified builds inside the commit gate
    # to ask two questions of one arrangement.
    @classmethod
    def setUpClass(cls) -> None:
        cls._raw = tempfile.TemporaryDirectory()
        directory = _certified(Path(cls._raw.name))
        # Both formulations finish `NEEDS_MORE_EVIDENCE` and therefore exit
        # `NEEDS_ACTION`, which is `DIRECT`'s frozen behaviour rather than
        # anything about cost -- the broad screen is uncalibrated and nobody
        # independent looks, and `docs/baseline.md` records why that is frozen
        # rather than fixed. What matters here is that each formulation built its
        # own geometry.
        assert _quiet(cli.run, str(directory), "--no-render") == cli.NEEDS_ACTION
        assert _quiet(cli.branch, str(directory), "--from", ".", "--id", "wider",
                      "--reason", "the same clip with more flange to grip") == 0
        assert _quiet(cli.run, str(directory), "--no-render") == cli.NEEDS_ACTION
        cls.directory = directory

    @classmethod
    def tearDownClass(cls) -> None:
        cls._raw.cleanup()

    def test_each_formulation_pays_its_own_build_and_shares_nothing(self) -> None:
        report = _status(self.directory)["cost"]

        self.assertEqual([".", "wider"], sorted(report["by_alternative"]))
        for key in (".", "wider"):
            with self.subTest(formulation=key):
                self.assertEqual(1, report["by_alternative"][key]["builds"])
        self.assertEqual(2, report["project"]["builds"],
                         "two formulations, two builds: the second inherits the "
                         "shared intent and pays for the geometry again")

        added = report["incremental"]["wider"]
        self.assertEqual(1, added["builds"])
        self.assertEqual(1, added["invocations"])
        self.assertGreater(added["deterministic_seconds"], 0.0)
        self.assertEqual({"builds_avoided": 0, "reviews_from_a_sibling": 0},
                         added["shared"],
                         "nothing computational is shared between siblings in "
                         "this build: the first is measured off the ledgers and "
                         "the second is zero by construction, because the review "
                         "envelope carries the alternative id")

    def test_the_root_is_not_charged_to_the_branch_that_came_after_it(self) -> None:
        """`incremental` is what each formulation *added*, so the root is not in it."""
        report = _status(self.directory)["cost"]
        self.assertEqual(["wider"], sorted(report["incremental"]))
        self.assertAlmostEqual(
            report["by_alternative"]["."]["deterministic_seconds"]
            + report["by_alternative"]["wider"]["deterministic_seconds"],
            report["project"]["deterministic_seconds"], places=3,
            msg="the project total is the sum of its formulations; nothing is "
                "counted twice and nothing is left out")

    def test_a_job_that_never_branched_reports_one_formulation_and_no_increment(self) -> None:
        """The zero-cost claim, on the reader as well as on the receipts."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _certified(Path(raw))
            _quiet(cli.run, str(directory), "--no-render")
            report = _status(directory)["cost"]
            self.assertEqual({}, report["incremental"])
            self.assertEqual(1, report["project"]["formulations"])


class SomethingReadsTheLedgerTest(unittest.TestCase):
    """A cost field no reader reads is the shape this codebase removes."""

    def test_status_reports_the_ledger_it_did_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _certified(Path(raw))
            _quiet(cli.run, str(directory), "--no-render")
            before = (directory / COST.COST_FILE).read_text(encoding="utf-8")
            report = _status(directory)
            self.assertEqual(COST.totals_at(directory),
                             report["cost"]["by_alternative"]["."])
            self.assertEqual(before,
                             (directory / COST.COST_FILE).read_text(encoding="utf-8"),
                             "`status` reads and never writes, and that has to "
                             "hold for the ledger too")

    def test_a_restart_is_counted_as_repeated_work_from_the_journal(self) -> None:
        """Read off `lifecycle.json` rather than recorded twice.

        A restart throws away receipts whose bindings still hold so the job can
        be done again, which is repeated work by definition -- and it is already
        journalled, so counting it a second time would be two records of one
        event.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _certified(Path(raw))
            _quiet(cli.run, str(directory), "--no-render")
            _quiet(cli.run, str(directory), "--restart", "--no-render")
            report = _status(directory)["cost"]
            self.assertEqual(1, report["project"]["restarts"])
            self.assertEqual(2, report["project"]["builds"])

    def test_the_terminal_line_names_the_numbers_a_reader_needs(self) -> None:
        line = COST.one_line({"dispatches": 3, "context_bytes": 21500,
                              "deterministic_seconds": 4.25, "builds": 3,
                              "repeated_builds": 2, "restarts": 1})
        self.assertIn("3 dispatch(es)", line)
        self.assertIn("21.5 kB", line)
        self.assertIn("4.25s", line)
        self.assertIn("2 repeated", line)
        self.assertIn("1 restart", line)


if __name__ == "__main__":
    unittest.main()
