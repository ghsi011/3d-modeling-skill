#!/usr/bin/env python3
"""Release 3's lifecycle group: run identity, resume versus restart, dispositions.

Three items that share one argument, which is why they share a file.

**Run identity.** A run id is supposed to answer "which invocation produced this
receipt", and an invocation counter cannot: this command surface is built so a
rerun on unchanged inputs is byte-identical -- `--updated-utc` is required from
the caller for exactly that reason -- and a counter breaks it on the second run
of every job. So the identity is content-derived (`bindings.identity`), and two
invocations over identical bindings are correctly the same run. What that buys
over any single existing digest is the last binding in the map: two formulations
byte-identical at the instant one was branched from the other have *different*
run identities, which no artifact hash can say.

**Resume versus restart.** Resume is what a bare `run` already does; `--resume`
asserts there is something to continue and refuses when there is not. Restart is
the interesting one now that invalidation is scoped: it is not "delete
everything", because that would discard the frozen acceptance contract, the
content cache, the proposal and the model -- inputs, not conclusions -- and, if
it were scoped to the project, every sibling. It is "discard what this
formulation concluded, keep what it concluded from", and what it buys that
resume cannot is the one case scoped invalidation is blind to by construction: a
conclusion whose bindings all still hold and that somebody no longer trusts.

**Dispositions.** Seven states, and each one now changes something in execution,
invalidation or status rather than labelling. `FALLBACK` is the one a real job
demanded: the vent-ball exercise had to record a genuinely retained fallback as
`ACTIVE` because a build that would not run one gives "retained" and "abandoned"
the same behaviour.

Every test here fails on the code as it stood before this slice. Where a test
shows a protection holding, its neighbour mutates the protection and shows the
loss is reachable.

The end-to-end runs here are on the **certified** lane, which builds in this
process. The authored lane runs its candidate behind the confined boundary, which
is a child interpreter and belongs in `benchmarks/heavy/test_lifecycle_heavy.py`
-- and that is where the sharpest restart case lives, because reaching a review
answer whose bindings all still hold means carrying a real job to `VERIFIED`
first. `conftest.py` carries the tier rule and `benchmarks/heavy/README.md` the
measurement behind it.
"""
from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import tempfile
import unittest
from pathlib import Path

from . import bindings as B
from . import cli
from . import cost as COST
from . import lifecycle as LC
from . import project as P
from . import schemas as S
from . import selftest as ST

UTC = "1970-01-01T00:00:00Z"

# What every receipt binds, and what a run reads. Written by hand rather than
# produced by a run: this half of the slice is about *which files are removed and
# which are kept*, and a fixture that had to build real geometry to ask that
# question would be a fixture in the wrong tier.
SCAFFOLD = {
    "acceptance_contract.json": {"contract_sha256": "a" * 64,
                                 "expected_artifacts": {"stl": "candidate.stl",
                                                        "source": "model.py"}},
    "model_contract.json": {"job_id": "lifecycle",
                            "source": {"acceptance_contract_sha256": "a" * 64}},
    "execution_plan.json": {"route": "CUSTOM", "builder": "AUTHORED"},
}
CONCLUSIONS = (B.PIPELINE_RECEIPT, "commission_report.json",
               "final_status.json")


def _project(**over) -> P.Project:
    base = dict(
        job_id="lifecycle", updated_utc=UTC, source_mode="NEW",
        consequence="INCONSEQUENTIAL",
        consequence_rationale="a desk block; failure wastes material",
        printer="Test Printer", material={"process": "FDM", "material": "PLA"},
        nozzle={"diameter_mm": 0.4},
        orientation={"model_to_printer_matrix": "identity", "bed_z_mm": 0.0},
        template=None, parameters={}, model="model.py",
        envelope_mm={"x": 60.0, "y": 50.0, "z": 20.0},
        reviewer={"model_snapshot": "test"},
        requirements=(P.Requirement(name="mount_pitch", value=32.0, unit="mm",
                                    provenance="STATED", source="user"),),
    )
    base.update(over)
    return P.Project(**base)


def _scaffold(work_dir: Path, *, conclusions: bool = True) -> Path:
    """One formulation's directory: its inputs, and optionally its conclusions."""
    work_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in SCAFFOLD.items():
        (work_dir / name).write_text(S.canonical_json(payload), encoding="utf-8")
    (work_dir / "model.py").write_text("def build():\n    return None\n",
                                       encoding="utf-8")
    (work_dir / "candidate.stl").write_bytes(b"solid candidate\nendsolid\n")
    if conclusions:
        for name in CONCLUSIONS:
            (work_dir / name).write_text(
                S.canonical_json({"final_status": "VERIFIED", "name": name}),
                encoding="utf-8")
        room = work_dir / cli.REVIEW_DIR
        room.mkdir(exist_ok=True)
        (room / "verification_response.json").write_text(
            S.canonical_json({"decision": "PASS"}), encoding="utf-8")
        (room / "verification_packet.json").write_text(
            S.canonical_json({"asked": True}), encoding="utf-8")
        (work_dir / cli.NEXT_ACTION_FILE).write_text(
            S.canonical_json({"kind": "REVIEW"}), encoding="utf-8")
    return work_dir


def _laid_out(root: Path, project: P.Project | None = None) -> Path:
    directory = root / "project"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "brief.md").write_text("a block", encoding="utf-8")
    (project or _project()).save(directory)
    return directory


def _digests(directory: Path) -> dict[str, str]:
    return {p.relative_to(directory).as_posix(): S.sha256_file(p)
            for p in sorted(directory.rglob("*")) if p.is_file()}


def _status(directory: Path) -> dict:
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        cli.status([str(directory), "--json"])
    return json.loads(stream.getvalue())


def _quiet(call, *argv) -> int:
    with contextlib.redirect_stderr(io.StringIO()):
        return call(list(argv))


def _branch(directory: Path, *, name: str, reason: str, parent: str = ".") -> int:
    return _quiet(cli.branch, str(directory), "--from", parent, "--id", name,
                  "--reason", reason)


def _set(directory: Path, **flags) -> int:
    argv = [str(directory)]
    for flag, value in flags.items():
        argv.extend([f"--{flag.replace('_', '-')}", value])
    return _quiet(cli.branch, *argv)


# ---------------------------------------------------------------------------
# Run identity
# ---------------------------------------------------------------------------

class RunIdentityTest(unittest.TestCase):
    """Content-derived, over the whole binding map, and byte-identical on a rerun."""

    def test_an_unchanged_formulation_keeps_its_identity(self) -> None:
        """The property an invocation counter cannot have, which is why it is not one."""
        with tempfile.TemporaryDirectory() as raw:
            work = _scaffold(Path(raw) / "job")
            first = B.run_id(work)
            self.assertEqual(first, B.run_id(work))
            # Rewritten with the same bytes: identity is over content, so a file
            # somebody re-saved is not a different run.
            (work / "model.py").write_text(
                (work / "model.py").read_text(encoding="utf-8"), encoding="utf-8")
            self.assertEqual(first, B.run_id(work))

    def test_every_binding_in_the_map_moves_it(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = _scaffold(Path(raw) / "job")
            before = B.run_id(work)
            for name in ("model.py", "candidate.stl"):
                with self.subTest(binding=name):
                    target = work / name
                    kept = target.read_bytes()
                    target.write_bytes(kept + b"\n")
                    self.assertNotEqual(before, B.run_id(work))
                    target.write_bytes(kept)
                    self.assertEqual(before, B.run_id(work))
            for name, key in (("execution_plan.json", "route"),
                              ("model_contract.json", "job_id"),
                              ("acceptance_contract.json", "contract_sha256")):
                with self.subTest(binding=name):
                    target = work / name
                    kept = json.loads(target.read_text(encoding="utf-8"))
                    target.write_text(S.canonical_json({**kept, key: "moved"}),
                                      encoding="utf-8")
                    self.assertNotEqual(before, B.run_id(work))
                    target.write_text(S.canonical_json(kept), encoding="utf-8")
                    self.assertEqual(before, B.run_id(work))

    def test_a_reformatted_declaration_is_the_same_run(self) -> None:
        """Three bindings hash a canonical payload, not the bytes on disk.

        That is `bindings.current`'s existing rule and it matters here: an
        identity that moved when somebody re-indented `execution_plan.json` would
        report a run that had changed nothing as a different run, and the first
        person it lied to would stop believing it.
        """
        with tempfile.TemporaryDirectory() as raw:
            work = _scaffold(Path(raw) / "job")
            before = B.run_id(work)
            for name in ("execution_plan.json", "model_contract.json",
                         "acceptance_contract.json"):
                target = work / name
                target.write_text(
                    json.dumps(json.loads(target.read_text(encoding="utf-8")),
                               indent=4), encoding="utf-8")
            self.assertNotEqual(_digests(work), {})
            self.assertEqual(before, B.run_id(work))

    def test_two_byte_identical_formulations_are_two_runs(self) -> None:
        """The instant a branch is created it is a copy of its ancestor.

        Every artifact digest, the contract hash and the plan hash are equal --
        that is the false-pass case `test_alternatives` was built around. So an
        identity derived from artifacts alone would say the two are one run.
        `alternative` is in the binding map, and it is the whole reason this is
        an identity rather than a second name for a contract hash.
        """
        with tempfile.TemporaryDirectory() as raw:
            work = _scaffold(Path(raw) / "job")
            root = B.run_id(work)
            branched = B.run_id(work, alternative_id="snap-fit")
            self.assertNotEqual(root, branched)
            self.assertNotEqual(branched, B.run_id(work, alternative_id="screwed"))
            self.assertEqual(root, B.run_id(work, alternative_id=None))

    def test_the_instruction_is_stamped_with_the_run_identity(self) -> None:
        """One definition. Two would be two answers to "has this project moved"."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            _scaffold(directory)
            project = P.load(directory)
            path = cli._write_next_action(directory, project,
                                          {"kind": "REVIEW"})
            written = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(B.run_id(directory, model_name=project.model),
                             written["state_sha256"])
            self.assertEqual(written["state_sha256"], _status(directory)["run_id"])

    def test_the_identity_is_not_a_counter(self) -> None:
        """The mutation, made explicit: a run id that counted would break this.

        `identity` is a pure function of the state map and nothing else -- no
        clock, no sequence, no file it writes on the way past. Asserted by
        equality against a hash of the same map computed independently, so an
        implementation that mixed anything in would have to mix it in here too.
        """
        with tempfile.TemporaryDirectory() as raw:
            work = _scaffold(Path(raw) / "job")
            state = B.current(work)
            self.assertEqual(S.payload_hash(state), B.identity(state))
            self.assertEqual(B.identity(state), B.identity(dict(state)))


# ---------------------------------------------------------------------------
# Resume versus restart
# ---------------------------------------------------------------------------

class ResumeTest(unittest.TestCase):
    def test_resume_refuses_a_formulation_with_nothing_to_continue(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            _scaffold(directory, conclusions=False)
            self.assertEqual(2, _quiet(cli.run, str(directory), "--resume",
                                       "--no-render"))
            # And it refused before writing anything: a flag that asserted a
            # false precondition must not leave the project changed.
            self.assertFalse((directory / cli.NEXT_ACTION_FILE).exists())
            self.assertFalse((directory / "final_status.json").exists())

    def test_resume_and_restart_are_not_both_meant(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    cli.run([str(directory), "--resume", "--restart"])
            self.assertEqual(2, caught.exception.code)


class RestartTest(unittest.TestCase):
    """Scoped to one formulation, and to that formulation's conclusions."""

    def test_it_discards_the_conclusions_and_keeps_what_they_came_from(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            _scaffold(directory)
            project = P.load(directory)
            cli._restart(directory, directory, project)

            for name in CONCLUSIONS + (cli.NEXT_ACTION_FILE,):
                self.assertFalse((directory / name).exists(), name)
            self.assertFalse(
                (directory / cli.REVIEW_DIR / "verification_response.json").exists(),
                "a review answer is a conclusion: it is what a resume would "
                "reuse, and restart exists for the case where reusing it is "
                "exactly what somebody no longer wants")
            for name in tuple(SCAFFOLD) + ("model.py", "candidate.stl"):
                self.assertTrue((directory / name).is_file(), name)
            self.assertTrue(
                (directory / cli.REVIEW_DIR / "verification_packet.json").is_file(),
                "the packet is the question, rewritten at the top of every run")

    def test_it_records_what_it_discarded_before_discarding_it(self) -> None:
        """ADR 0002's rule -- neither current nor erased -- applied to the one
        operation that erases a receipt whose bindings still hold."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            _scaffold(directory)
            was = S.sha256_file(directory / "final_status.json")
            identity = B.run_id(directory, model_name="model.py")

            cli._restart(directory, directory, P.load(directory))

            event = LC.last(directory)
            self.assertEqual("RESTART", event["event"])
            self.assertEqual("VERIFIED", event["discarded_status"])
            self.assertEqual(identity, event["run_id"])
            self.assertEqual(was, event["discarded"]["final_status.json"])
            self.assertIn("reviews/verification_response.json", event["discarded"])

    def test_it_leaves_a_sibling_alone(self) -> None:
        """13.5: a change limited to one alternative does not reach its siblings."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            _branch(directory, name="snap-fit", reason="no fasteners")
            _branch(directory, name="screwed", reason="fasteners", parent=".")
            mine = _scaffold(directory / P.ALTERNATIVES_DIR / "screwed")
            theirs = directory / P.ALTERNATIVES_DIR / "snap-fit"
            _scaffold(theirs)
            untouched = _digests(theirs)

            project = P.load(directory)
            self.assertEqual("screwed", project.active_alternative)
            cli._restart(directory, mine, project)

            self.assertEqual(untouched, _digests(theirs))
            self.assertFalse((mine / "final_status.json").exists())

    def test_a_restart_with_nothing_to_discard_is_not_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            _scaffold(directory, conclusions=False)
            cli._restart(directory, directory, P.load(directory))
            self.assertEqual({}, LC.last(directory)["discarded"])

    def test_the_journal_binds_nothing(self) -> None:
        """It must not, or a restart would invalidate the run that followed it.

        The journal is the one file here ordered by when things happened rather
        than by what they contain, in a build whose every other artifact is
        content-addressed. Appending to it may not move a run identity or make a
        receipt stale, and this is what says so.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            _scaffold(directory)
            before = B.run_id(directory, model_name="model.py")
            stale = B.broken(directory)
            LC.record(directory, {"event": "RESTART", "alternative": ".",
                                  "discarded": {}, "updated_utc": UTC})
            self.assertEqual(before, B.run_id(directory, model_name="model.py"))
            self.assertEqual(stale, B.broken(directory))
            self.assertNotIn(LC.LIFECYCLE_FILE, [r.name for r in B.RECEIPTS])

    def test_a_damaged_journal_is_not_overwritten(self) -> None:
        """An empty journal and an unreadable one read the same; only one may append.

        Both spellings of "this is not the document": unparseable, and parseable
        as something else. Appending to either would replace a record with one
        event, and records here are not deleted.
        """
        for damaged in ("{not json", "[]", ""):
            with self.subTest(damaged=damaged), tempfile.TemporaryDirectory() as raw:
                directory = _laid_out(Path(raw))
                LC.path(directory).write_text(damaged, encoding="utf-8")
                with self.assertRaises(S.SchemaError):
                    LC.record(directory, {"event": "RESTART", "alternative": "."})
                self.assertEqual(damaged,
                                 LC.path(directory).read_text(encoding="utf-8"))

    def test_an_undeclared_event_kind_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(S.SchemaError):
                LC.record(Path(raw), {"event": "TIDIED", "alternative": "."})


# ---------------------------------------------------------------------------
# What each disposition changes
# ---------------------------------------------------------------------------

class DispositionTransitionTest(unittest.TestCase):
    """A declared proof each: switched preferred, and paused then resumed."""

    def _two(self, root: Path) -> Path:
        directory = _laid_out(root)
        _branch(directory, name="snap-fit", reason="no fasteners to lose")
        _branch(directory, name="screwed", reason="serviceable", parent=".")
        return directory

    def test_preferring_one_demotes_the_other_and_erases_neither(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = self._two(Path(raw))
            self.assertEqual(0, _set(directory, disposition="PREFERRED",
                                     of="snap-fit", basis="USER_SELECTION"))
            self.assertEqual(0, _set(directory, disposition="PREFERRED",
                                     of="screwed", basis="PHYSICAL_TEST"))

            project = P.load(directory)
            self.assertEqual("ACTIVE", project.alternative("snap-fit").disposition)
            self.assertEqual("PREFERRED", project.alternative("screwed").disposition)
            self.assertEqual("PHYSICAL_TEST", project.alternative("screwed").basis)
            # 13.3: changing the preferred alternative does not erase the
            # previously preferred one. The row is still there, its reason is
            # unchanged, and the demotion is in the journal rather than nowhere.
            self.assertEqual("no fasteners to lose",
                             project.alternative("snap-fit").reason)
            demotion = [e for e in LC.read(directory)
                        if e["alternative"] == "snap-fit" and e["now"] == "ACTIVE"]
            self.assertEqual(1, len(demotion))
            self.assertEqual("displaced as preferred by screwed",
                             demotion[0]["note"])

    def test_a_paused_formulation_is_parked_and_can_be_resumed(self) -> None:
        """Release 3's declared proof, which `PAUSED` could not previously reach.

        It could be *stored* before this slice and never activated again, so the
        state was reachable and the transition out of it was not.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = self._two(Path(raw))
            _scaffold(directory / P.ALTERNATIVES_DIR / "screwed")
            self.assertEqual("screwed", P.load(directory).active_alternative)

            self.assertEqual(0, _set(directory, disposition="PAUSED", of="screwed",
                                     basis="UNRESOLVED_EVIDENCE"))
            project = P.load(directory)
            self.assertIsNone(project.active_alternative,
                              "a paused formulation cannot be the active one, and "
                              "leaving the project pointing at it would refuse "
                              "every command the user ran next")
            self.assertEqual([], project.validate(directory, require_buildable=False))
            self.assertTrue(
                (directory / P.ALTERNATIVES_DIR / "screwed"
                 / cli.NEXT_ACTION_FILE).is_file(),
                "a pause keeps the instruction: it is what to do on resuming")
            self.assertEqual(2, _quiet(cli.branch, str(directory), "--activate",
                                       "screwed"))

            self.assertEqual(0, _set(directory, disposition="ACTIVE", of="screwed",
                                     basis="USER_SELECTION"))
            self.assertEqual(0, _quiet(cli.branch, str(directory), "--activate",
                                       "screwed"))
            self.assertEqual("screwed", P.load(directory).active_alternative)
            self.assertEqual(["PAUSED", "ACTIVE"],
                             [e["now"] for e in LC.read(directory)])

    def test_concluding_one_clears_its_instruction_and_keeps_its_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = self._two(Path(raw))
            where = _scaffold(directory / P.ALTERNATIVES_DIR / "snap-fit")
            self.assertEqual(0, _set(directory, disposition="REJECTED",
                                     of="snap-fit", basis="REQUIREMENT_FAILURE"))
            self.assertFalse((where / cli.NEXT_ACTION_FILE).exists(),
                             "a formulation this job is finished with is waiting "
                             "for nothing, and an instruction left on disk says "
                             "the opposite of the truth")
            for name in CONCLUSIONS:
                self.assertTrue((where / name).is_file(),
                                "13.1: a rejection is evidence, not a deletion")

    def test_superseding_names_what_replaced_it(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = self._two(Path(raw))
            self.assertEqual(2, _set(directory, disposition="SUPERSEDED",
                                     of="snap-fit", basis="STRONGER_CONCEPT"),
                             "SUPERSEDED with no successor asserts a better "
                             "concept exists and gives no way to find it")
            self.assertEqual("ACTIVE",
                             P.load(directory).alternative("snap-fit").disposition)
            self.assertEqual(0, _set(directory, disposition="SUPERSEDED",
                                     of="snap-fit", basis="STRONGER_CONCEPT",
                                     superseded_by="screwed"))
            self.assertEqual("screwed",
                             P.load(directory).alternative("snap-fit").superseded_by)

    def test_a_refused_transition_changes_nothing_on_disk(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = self._two(Path(raw))
            before = _digests(directory)
            self.assertEqual(2, _set(directory, disposition="MERGED", of="snap-fit",
                                     basis="STRONGER_CONCEPT",
                                     superseded_by="screwed"),
                             "this build performs no merges, and `screwed` does "
                             "not record `snap-fit` as a parent")
            self.assertEqual(2, _set(directory, disposition="PAUSED", of="nobody",
                                     basis="USER_SELECTION"))
            self.assertEqual(before, _digests(directory))

    def test_a_transition_is_not_mixed_with_creating_or_switching(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = self._two(Path(raw))
            self.assertEqual(2, _quiet(cli.branch, str(directory), "--activate",
                                       "snap-fit", "--disposition", "PAUSED"))
            self.assertEqual(2, _quiet(cli.branch, str(directory), "--from", ".",
                                       "--id", "third", "--reason", "because",
                                       "--disposition", "PREFERRED"))
            self.assertEqual(2, len(P.load(directory).alternatives))


class FallbackTest(unittest.TestCase):
    """What separates FALLBACK from ACTIVE, and from a rejection."""

    def test_a_fallback_may_be_worked_under(self) -> None:
        """The vent-ball case: a fallback you may not keep current is not one."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            _branch(directory, name="as-drawn", reason="the sleeve as drawn")
            self.assertEqual(0, _set(directory, disposition="FALLBACK",
                                     of="as-drawn", basis="UNRESOLVED_EVIDENCE"))
            project = P.load(directory)
            self.assertEqual("as-drawn", project.active_alternative,
                             "FALLBACK is runnable, so the project is not moved "
                             "off it the way a pause or a rejection moves it")
            self.assertEqual([], project.validate(directory, require_buildable=False))
            self.assertEqual(0, _quiet(cli.branch, str(directory), "--activate",
                                       "as-drawn"))

    def test_it_is_named_exactly_when_the_current_formulation_has_no_claim(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw))
            _branch(directory, name="as-drawn", reason="the sleeve as drawn")
            _branch(directory, name="plate-seated", reason="trusts the estimate",
                    parent=".")
            _set(directory, disposition="FALLBACK", of="as-drawn",
                 basis="UNRESOLVED_EVIDENCE")

            report = _status(directory)
            self.assertEqual([{"alternative_id": "as-drawn", "status": "NOT_RUN",
                               "reason": "the sleeve as drawn"}],
                             report["fallbacks"])
            self.assertEqual("NOT_RUN", report["final_status"])

            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                cli.status([str(directory)])
            self.assertIn("fallback     as-drawn is retained", stream.getvalue())

    def test_the_disposition_survives_a_round_trip_and_costs_nothing_absent(self) -> None:
        """An ACTIVE row serializes to the bytes it did before a basis existed."""
        plain = P.Alternative(alternative_id="a", reason="x")
        self.assertEqual({"alternative_id": "a", "parents": [], "reason": "x",
                          "disposition": "ACTIVE"}, plain.as_dict())
        rich = dataclasses.replace(plain, disposition="FALLBACK",
                                   basis="PHYSICAL_TEST")
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), _project(alternatives=(rich,)))
            reloaded = P.load(directory).alternative("a")
            self.assertEqual("FALLBACK", reloaded.disposition)
            self.assertEqual("PHYSICAL_TEST", reloaded.basis)


# ---------------------------------------------------------------------------
# The certified lane, end to end, because it builds without a child interpreter
# ---------------------------------------------------------------------------

class RestartOnARealRunTest(unittest.TestCase):
    """A whole job, restarted through the command surface a user has.

    The certified lane is the one that builds in this process -- the authored
    lane runs its candidate behind the confined boundary, which is a child
    interpreter and belongs in `benchmarks/heavy`. What is under test here is not
    the geometry: it is that a restart puts the job back to `NOT_RUN`, that
    re-running rebuilds it from inputs it kept, and that the discarded verdict is
    still findable afterwards.
    """

    def _certified(self, root: Path) -> Path:
        directory = root / "project"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "brief.md").write_text("a clip", encoding="utf-8")
        _project(template="c_clip", model=None, envelope_mm=None,
                 parameters=dict(ST.FROZEN_PARAMETERS["c_clip"])).save(directory)
        return directory

    def test_a_rerun_on_unchanged_inputs_moves_no_receipt_and_no_identity(self) -> None:
        """The constraint the run-identity decision turns on, asserted end to end.

        Two files move and neither is a receipt. `timings.json` is one run's
        durations, rewritten. `cost.json` is the ledger, appended to -- and the
        entry it gains is the point rather than an exception to the rule: the
        rerun really did happen, really did build the geometry a second time, and
        before the ledger existed that cost was recorded nowhere at all. Both are
        bound by nothing: no receipt carries either digest, `bindings.RECEIPTS`
        names neither, and the run identity below is unmoved.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = self._certified(Path(raw))
            _quiet(cli.run, str(directory), "--no-render")
            first, identity = _digests(directory), _status(directory)["run_id"]
            _quiet(cli.run, str(directory), "--no-render")
            second = _digests(directory)
            moved = {name for name in first
                     if first[name] != second.get(name)}
            self.assertEqual({"timings.json", "cost.json"}, moved,
                             "durations and what the job spent are the only two "
                             "things a rerun is allowed to move, and neither is "
                             "hashed into anything")
            self.assertEqual(identity, _status(directory)["run_id"])
            # And the rerun is *recorded* as repeated work rather than absorbed.
            totals = COST.totals_at(directory)
            self.assertEqual(2, totals["invocations"])
            self.assertEqual(2, totals["builds"])
            self.assertEqual(1, totals["repeated_builds"],
                             "the second run rebuilt geometry the first run had "
                             "already built, and that is what a rerun costs")
            self.assertEqual(0, totals["dispatches"],
                             "a certified INCONSEQUENTIAL job dispatches nothing, "
                             "however many times it is run")

    def test_a_restart_returns_the_job_to_not_run_and_a_rerun_rebuilds_it(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = self._certified(Path(raw))
            _quiet(cli.run, str(directory), "--no-render")
            was = _status(directory)
            self.assertNotEqual("NOT_RUN", was["final_status"])

            # This job concludes NEEDS_MORE_EVIDENCE -- an uncalibrated screen and
            # nobody independent looking -- so the exit code is the same before
            # and after. What is under test is the discard and the rebuild, and a
            # restart that changed the verdict would be re-adjudicating.
            self.assertEqual(cli.NEEDS_ACTION,
                             _quiet(cli.run, str(directory), "--restart",
                                    "--no-render"))
            event = [e for e in LC.read(directory) if e["event"] == "RESTART"][0]
            self.assertEqual(was["stored_status"], event["discarded_status"])
            self.assertIn("final_status.json", event["discarded"])
            # And the run that followed the discard rebuilt it, from the frozen
            # contract, the parameters and the cache the restart kept.
            self.assertEqual(was["stored_status"],
                             _status(directory)["stored_status"])
            self.assertEqual(was["bindings"], _status(directory)["bindings"])

    def test_resume_reports_what_it_is_reusing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = self._certified(Path(raw))
            _quiet(cli.run, str(directory), "--no-render")
            stream = io.StringIO()
            with contextlib.redirect_stderr(stream):
                cli.run([str(directory), "--resume", "--no-render"])
            self.assertIn("still bind what they were issued against",
                          stream.getvalue())


if __name__ == "__main__":
    unittest.main()
