#!/usr/bin/env python3
"""L0-heavy — the half of
`skills/3d-modeling/scripts/pipeline/test_isolation.py`
that costs a child interpreter.

The repository-root `conftest.py` refuses a child interpreter inside the commit
gate, and these classes start one. Same tests, moved rather than weakened;
`benchmarks/heavy/README.md` records the profile that decided the seam and what
runs this tier. What stayed behind is what answers in the parent process.
"""
from __future__ import annotations

import ast
import dataclasses
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
from pipeline import acceptance as ACC
from pipeline import cli
from pipeline import confine
from pipeline import isolation
from pipeline import safety
from pipeline import schemas as S
from pipeline import verification
from pipeline.test_phase2 import RISER, RISER_PROPOSAL
from pipeline.test_phase2 import _laid_out, _project, _read

# The fixtures this half shares with the half that stayed behind,
# imported rather than copied: two spellings of one fixture is how
# two tiers stop testing the same thing.
from pipeline.test_isolation import (  # noqa: E402
    BREAKAWAY_ATTACK,
    EVERY_ATTACK,
    GRANDCHILD_ATTACK,
    JUNCTION_ATTACK,
    LAZY_IMPORT_ATTACK,
    MANIFEST_INJECTION,
    MARKER,
    MUTATE_ACCEPTANCE,
    PACKAGE_ROOT,
    PATCH_EXPECTATIONS,
    PATCH_STATUS,
    PATCH_TOLERANCES,
    POISONED_PYC_ATTACK,
    PROBE,
    REPO_ROOT,
    REVIEWER_INJECTION,
    SCRIPTS_ROOT,
    SELF_REWRITING,
    SOURCE_TREE_ATTACK,
    VENV_ATTACK,
    _AttackTest,
    _make_junction,
    _substitute,
    _unlink_quietly,
    requires_confinement,
)


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
        candidate actually reaches for. It gets as far as creating the directory
        and opening a handle to it; `FSCTL_SET_REPARSE_POINT` on that handle comes
        back `ERROR_ACCESS_DENIED` -- measured, inside the one directory the
        candidate can write. `isolation._sweep` is the second net, and refuses to
        read a build directory holding a reparse point at all.

        Aimed at the control rather than at `mklink /J`, which is `cmd.exe` and
        which the child-process policy now refuses (D12). An attack refused for
        not being allowed to start a program is not an attack on reparse points.
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

class NoCandidateProseReachesAReviewerTest(_AttackTest):
    """D10. The candidate writes free text; a reviewer's PASS decides the run.

    This is not a confinement defect and no confinement closes it: the manifest
    is *supposed* to cross. Four strings used to cross with it and land on
    `model_contract.json` and `artifact_manifest.json`, both of which the safety
    packet and the verification packet embed whole. Reading the frozen contract
    -- which the candidate can do, D9 row 3 -- does not create the channel; it
    aims it, because the tolerance bands and the design id are in there.

    The fix asserted here is a shape, not a scan. `BuiltCandidate` has no
    free-text field; the engine words come out of `isolation.KERNELS`; and
    `PARAMS` and `PROVENANCE` live in a `CandidateDeclaration` that no module on
    the path to a reviewer packet mentions at all.
    """

    # Everything the parent may legitimately write the candidate's own words
    # into. Exactly one entry, and it is not in any packet.
    QUARANTINE = (isolation.DECLARATION_FILE,)

    def _files(self, directory: Path) -> list[Path]:
        return [path for path in sorted(directory.rglob("*"))
                if path.is_file() and path.suffix in (".json", ".md", ".txt")]

    def _assert_absent_from_every_receipt(self, directory: Path) -> None:
        checked = [path for path in self._files(directory)
                   if path.name not in self.QUARANTINE]
        # `model.py` is the candidate's own file and carries the marker by
        # construction; it is not a receipt and `_files` does not collect it. But
        # a run that wrote no receipts at all would pass an empty loop, so the
        # count is asserted before the contents.
        self.assertGreater(len(checked), 8,
                           "this run produced almost no receipts, so an empty "
                           "loop is what just came back green")
        for path in checked:
            with self.subTest(receipt=str(path.relative_to(directory))):
                self.assertNotIn(
                    MARKER, path.read_text(encoding="utf-8", errors="replace"),
                    f"candidate-authored text reached {path.name}")

    def _assert_absent_from_both_packets(self, directory: Path) -> None:
        """The two payloads a reviewer is actually handed, built from the receipts.

        The safety packet on disk is the real one this run produced; the
        verification packet is assembled here from the same receipts because a
        `CUSTOM` job never dispatches a verifier, and "the other reviewer would
        have been clean too" is worth asserting rather than reasoning about.
        """
        brief = (directory / "brief.md").read_text(encoding="utf-8")
        intent = _read(directory, "intent_manifest.json")
        contract = _read(directory, "model_contract.json")
        artifact = _read(directory, "artifact_manifest.json")
        report = _read(directory, "commission_report.json")
        witness = report["witness"]

        packets = {
            "safety": safety.build_packet(
                brief=brief, intent=intent, contract=contract, artifact=artifact,
                commission=report, manufacturing=None, witness=witness).payload,
            "verification": verification.build_packet(
                brief=brief, intent=intent, contract=contract, artifact=artifact,
                commission=report, witness=witness, specification=None).payload,
        }
        # Required, not "if present". A run that stopped before the reviewer was
        # asked anything would make every assertion below vacuous, and a vacuous
        # green is what this whole file exists to not produce.
        on_disk = directory / cli.REVIEW_DIR / "safety_packet.json"
        self.assertTrue(on_disk.is_file(),
                        "this run never wrote a safety packet, so nothing here is "
                        "evidence that a reviewer was handed a clean one")
        packets["safety_packet.json"] = json.loads(
            on_disk.read_text(encoding="utf-8"))
        for name, payload in packets.items():
            with self.subTest(packet=name):
                self.assertNotIn(MARKER, json.dumps(payload),
                                 f"the {name} reviewer was handed the candidate's "
                                 "own paragraph about how to decide")

    @requires_confinement
    def test_a_provenance_addressed_to_the_reviewer_reaches_no_reviewer(self) -> None:
        raw = tempfile.TemporaryDirectory()
        self.addCleanup(raw.cleanup)
        directory = _laid_out(
            Path(raw.name), REVIEWER_INJECTION,
            _project(consequence="CONSEQUENTIAL",
                     consequence_rationale="a bracket that carries a load"),
            RISER_PROPOSAL)
        cli.run([str(directory), "--no-render"])

        # First: the marker really did cross the boundary. Without this the test
        # would pass just as well against a build that never ran.
        declaration = _read(directory, isolation.DECLARATION_FILE)
        self.assertIn(MARKER, json.dumps(declaration["provenance"]),
                      "the attack did not reach the parent at all, so nothing "
                      "below is evidence of anything")
        self._assert_absent_from_every_receipt(directory)
        self._assert_absent_from_both_packets(directory)

    @requires_confinement
    def test_a_candidate_that_rewrites_its_whole_manifest_reaches_no_reviewer(self) -> None:
        """The manifest is written in the candidate's own process, so it owns it.

        `build_child` intends to report a kernel token and two declarations. What
        it *does* is serialise a dict in an interpreter the model's module-level
        code has already run in, so the honest attack replaces the serialiser.
        Every engine string, the kernel token itself and an invented artifact key
        all carry the marker, and the parent's receipts carry none of it because
        the parent looks a token up rather than copying a sentence.
        """
        raw = tempfile.TemporaryDirectory()
        self.addCleanup(raw.cleanup)
        directory = _laid_out(
            Path(raw.name), MANIFEST_INJECTION,
            _project(consequence="CONSEQUENTIAL",
                     consequence_rationale="a bracket that carries a load"),
            RISER_PROPOSAL)
        cli.run([str(directory), "--no-render"])

        declaration = _read(directory, isolation.DECLARATION_FILE)
        self.assertIn(MARKER, json.dumps(declaration["provenance"]))
        artifact = _read(directory, "artifact_manifest.json")
        self.assertEqual(isolation.UNRECORDED_KERNEL, artifact["backend_version"],
                         "a kernel token this boundary does not know was passed "
                         "through instead of being reduced")
        self._assert_absent_from_every_receipt(directory)
        self._assert_absent_from_both_packets(directory)

    def test_an_unknown_kernel_token_is_reduced_and_never_forwarded(self) -> None:
        """Two entries in, and a token that is in neither says less, not more."""
        engine = isolation._engine(MARKER)
        self.assertEqual(isolation.UNRECORDED_KERNEL, engine.kernel)
        self.assertNotIn(MARKER, json.dumps(dataclasses.asdict(engine)))
        for token, entry in isolation.KERNELS.items():
            with self.subTest(kernel=token):
                known = isolation._engine(token)
                self.assertEqual(entry["boolean_engine"], known.boolean_engine)
                self.assertTrue(known.backend_version.startswith(
                    str(entry["distribution"])))
        for junk in (None, 42, {"kernel": "trimesh"}, ["trimesh"], True):
            with self.subTest(token=junk):
                self.assertEqual(isolation.UNRECORDED_KERNEL,
                                 isolation._engine(junk).kernel)

    def test_the_boundarys_return_type_carries_no_candidate_prose(self) -> None:
        """The property, stated over the dataclass rather than over a run.

        Every field of `BuiltCandidate` is a path the parent chose, a digest the
        parent computed, a number, or an `Engine` whose strings are this module's
        constants. The one field holding what the candidate wrote is named for it
        and typed for it, which is what the next test can then search for.
        """
        fields = {field.name: field.type
                  for field in dataclasses.fields(isolation.BuiltCandidate)}
        self.assertEqual(
            {"module_path", "module_sha256", "input_sha256", "declared",
             "stl_path", "step_path", "engine",
             "build_seconds", "boundary_seconds"},
            set(fields),
            "a field was added to the object that crosses the boundary; if it "
            "holds anything the candidate composed, D10 is open again")
        self.assertEqual("CandidateDeclaration", str(fields["declared"]))
        self.assertNotIn(
            "provenance",
            {field.name for field in dataclasses.fields(ACC.AcceptanceSource)},
            "AcceptanceSource.as_source() is handed verbatim to both reviewers")

    def test_no_module_on_the_path_to_a_reviewer_reads_the_declaration(self) -> None:
        """The call-graph half, in the shape ADR 0002 uses about meshes.

        `acceptance.generate` is safe because it has no parameter a mesh could
        arrive through. A reviewer packet is safe for the same reason: not one of
        the modules that builds or fills one names `declared` or
        `CandidateDeclaration` anywhere, so there is no ordering of operations in
        which candidate text is in a packet -- and adding one would have to be
        written down here first.
        """
        watched = ("runner", "safety", "verification", "commission", "screening",
                   "witness", "intent", "contract", "acceptance", "status",
                   "review", "fitted", "analysis", "execution")
        for name in watched:
            path = PACKAGE_ROOT / f"{name}.py"
            tree = ast.parse(path.read_text(encoding="utf-8"))
            # Attribute *access*, not any occurrence of the word: `declared` is a
            # perfectly good local variable and both `commission` and `screening`
            # use it as one. `x.declared` is the only spelling that reads the
            # quarantine, and `CandidateDeclaration` is the only way to name its
            # type.
            read = {node.attr for node in ast.walk(tree)
                    if isinstance(node, ast.Attribute)}
            named = {node.id for node in ast.walk(tree)
                     if isinstance(node, ast.Name)} | read
            imported = {node.module for node in ast.walk(tree)
                        if isinstance(node, ast.ImportFrom)}
            imported |= {alias.name for node in ast.walk(tree)
                         if isinstance(node, ast.Import) for alias in node.names}
            imported |= {alias.name for node in ast.walk(tree)
                         if isinstance(node, ast.ImportFrom) for alias in node.names}
            with self.subTest(module=name):
                self.assertNotIn("declared", read,
                                 f"{name}.py reads the candidate's own declaration, "
                                 "and everything it builds is read by a reviewer")
                self.assertNotIn("CandidateDeclaration", named)
                # And it could not, because the type is not in scope: none of
                # these modules imports the boundary at all.
                self.assertNotIn("isolation", imported,
                                 f"{name}.py imports the build boundary, so the "
                                 "quarantined declaration is one attribute away")

@requires_confinement
class WhatTheConfinementEnforcesTest(_AttackTest):
    """Every property this boundary claims, measured by the candidate itself.

    One run, one probe model, one table. The rows that come back `ALLOWED` are
    asserted as allowed on purpose: `AppData\\LocalLow` is Low-labelled by
    Windows and therefore writable by a Low-integrity subject, DNS resolution
    goes through a service rather than a socket, and the candidate can read what
    `BUILTIN\\Users` can read. Those are this boundary's named limitations, and a
    test that asserted them closed would be the second-worst thing in this file.

    The worst thing in this file was `network_tcp_connect` asserted *denied*
    against port 53. That port is filtered on this machine by NordVPN Threat
    Protection, identically with no confinement at all, so the row was green
    everywhere and measured nothing (D11). It now aims at 443, which this
    boundary is genuinely responsible for and genuinely does not close, and the
    expectation lives in `test_the_boundary_denies_outbound_tcp` as an
    `expectedFailure`: written down, failing, and reported the day it stops.
    """

    DENIED = ("write_repository", "write_site_packages", "write_pipeline_source",
              "write_project_directory", "write_parent_temp", "write_startup_folder",
              "write_own_inputs", "write_own_source", "create_reparse_point",
              # D12. Measured refused at `CreateProcess` with WinError 367, which
              # is a different fact from "the job caught what it started".
              "spawn_process",
              "open_parent_for_write")
    ALLOWED = ("write_build_directory", "read_project_directory",
               "write_low_integrity_profile", "dns_resolution",
               # Open, and this is the honest row. `PROC_THREAD_ATTRIBUTE`s do
               # not gate sockets, Low integrity does not gate sockets, and the
               # restricting-SID set does not either -- the WSAEACCES this file
               # used to cite was one filtered port. See D9 row 1 and D11.
               "network_tcp_connect")

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
        # Through `declared`, which is where candidate-authored values live now.
        # The probe reports through `PROVENANCE` because that is the one channel a
        # model has, and D10 is precisely that the channel exists -- so the table
        # this class reads is itself the demonstration that the quarantine keeps
        # the value usable while keeping it away from a reviewer.
        WhatTheConfinementEnforcesTest._cached = {
            "probe": dict(built.declared.provenance["confinement_probe"]),
            "token": dict(built.declared.provenance["child_token"]),
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

    @unittest.expectedFailure
    def test_the_boundary_denies_outbound_tcp(self) -> None:
        """The property this boundary is supposed to have and does not. D9/D11.

        Deliberately failing, and deliberately kept. `confine.py` claimed an
        outbound `connect` came back `WSAEACCES`; the evidence was a probe against
        `1.1.1.1:53`, which NordVPN Threat Protection filters on this machine with
        no confinement at all. Re-measured under the real restricted low-integrity
        token: 443 connects, 80 connects, `93.184.215.14:80` connects. A candidate
        can post the repository, the project directory and the frozen contract.

        Written as an expectation rather than as a paragraph because a paragraph
        does not go off. `expectedFailure` keeps the suite honest in both
        directions: while the gap is open this is an expected failure and the run
        stays green, and the day AppContainer or a WFP filter closes it, unittest
        reports an *unexpected success* -- which is a red suite that says "the
        boundary improved and the documentation did not".
        """
        report = self._probe()["probe"]
        self.assertNotEqual(
            "ALLOWED", report["network_tcp_connect"],
            "the candidate opened a TCP connection to 1.1.1.1:443")

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
        # Two entries since D12: this package, and the virtual environment's
        # `site-packages`, because the boundary starts the *base* interpreter and
        # the base interpreter does not know about the environment. Both are
        # read-only to the child.
        import sysconfig                              # noqa: PLC0415 - local
        self.assertEqual([str(SCRIPTS_ROOT), sysconfig.get_paths()["purelib"]],
                         env["PYTHONPATH"].split(os.pathsep))
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
        # D12: never the virtual environment's `python.exe`, which is a launcher
        # that spawns the base interpreter -- and a child forbidden to create
        # processes cannot be started through one. Asserted against `sys.prefix`
        # rather than against a literal, because outside a virtual environment
        # the two answers coincide and the test must still mean something.
        if sys.prefix != sys.base_prefix:
            self.assertFalse(
                Path(command[0]).is_relative_to(Path(sys.prefix)),
                "the boundary launches the virtual environment's launcher, which "
                "spawns a child the child-process policy refuses")
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
