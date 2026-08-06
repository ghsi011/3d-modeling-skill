#!/usr/bin/env python3
"""The manifest's two claims, tested as claims rather than as documentation.

`tools/fixtures.py` asserts four things about itself: that evidence is recorded
honestly, that the answer cannot reach a design agent, that licensed geometry
cannot leave the machine, and that the one fixture whose bytes it does keep
cannot go missing quietly. The first is a data question and the rest are
structural, so they are tested structurally -- by asking what is reachable from
the object a design agent is handed and from the directory it is given, not by
checking that a function chose not to return something.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures as FX                                              # noqa: E402


def _forms(secret: str) -> tuple[str, ...]:
    """Every spelling a path takes on its way through a file.

    A leak does not have to arrive verbatim. `json.dumps` doubles backslashes, a
    URL or a POSIX-normalised path turns them into forward slashes, and any of
    the three is enough for a reader to find the file. Searching only for the
    first is how a wall test passes with the wall down.
    """
    return tuple({secret, secret.replace("\\", "\\\\"),
                  secret.replace("\\", "/")})


def _all_text(fixture_id: str) -> str:
    """Everything a design agent could read off the public record, as one string."""
    record = FX.public(fixture_id)
    return "\n".join((
        repr(record),
        json.dumps(dataclasses.asdict(record), sort_keys=True),
        "\n".join(f"{k}={v!r}" for k, v in vars(record).items()),
        "\n".join(dir(record)),
    ))


class Manifest(unittest.TestCase):
    def test_every_fixture_declares_a_vocabulary_the_module_knows(self) -> None:
        for fixture_id in FX.fixture_ids():
            with self.subTest(fixture=fixture_id):
                record = FX.public(fixture_id)
                self.assertIn(record.evidence_class, FX.EVIDENCE_CLASSES)
                self.assertIn(record.distribution, FX.DISTRIBUTIONS)
                self.assertTrue(record.use_cases)
                for use_case in record.use_cases:
                    self.assertIn(use_case, FX.USE_CASES)
                self.assertTrue(record.license)

    def test_the_public_request_material_is_in_the_repository(self) -> None:
        for fixture_id in FX.fixture_ids():
            with self.subTest(fixture=fixture_id):
                self.assertTrue(FX.request_text(fixture_id).strip())

    def test_evidence_is_not_flattened_across_the_three_real_jobs(self) -> None:
        """The claim this manifest exists to keep honest.

        One of these was printed and fitted and works. One was printed by
        somebody else, which is evidence about their design. One has never been
        printed at all and two of its driving numbers are photo estimates its own
        notes give as plus or minus two millimetres. A set that filed all three as
        "a real job" would let a later report say "proven on three real jobs".
        """
        self.assertEqual(FX.PHYSICALLY_PROVEN,
                         FX.public("vent-ball-combine").evidence_class)
        self.assertEqual(FX.WORKING_THIRD_PARTY,
                         FX.public("pixel9-card-case").evidence_class)
        self.assertEqual(FX.DESIGN_STAGE_UNVERIFIED,
                         FX.public("berlingo-knob").evidence_class)
        proven = [f for f in FX.fixture_ids()
                  if FX.public(f).evidence_class == FX.PHYSICALLY_PROVEN]
        self.assertEqual(["vent-ball-combine"], proven,
                         "exactly one fixture here has been printed and used; if "
                         "that number grows, something was printed or something "
                         "was reclassified, and both want saying out loud")

    def test_a_fixture_with_no_evidence_says_so_in_its_own_request_material(self) -> None:
        """The metadata and the prose have to agree, because agents read the prose."""
        text = FX.request_text("berlingo-knob")
        self.assertIn("Nothing has been printed.", text)
        self.assertIn(FX.DESIGN_STAGE_UNVERIFIED, text)
        self.assertIn("never measured", text)


class TheWallBetweenRequestAndAnswer(unittest.TestCase):
    def test_the_public_record_has_no_field_that_could_hold_an_answer(self) -> None:
        names = {f.name for f in dataclasses.fields(FX.PublicFixture)}
        self.assertEqual(set(), names & {"reference", "private_reference",
                                         "answer", "solution", "expected"})

    def test_the_public_record_carries_no_absolute_path_at_all(self) -> None:
        """The invariant that makes the leak below impossible rather than absent.

        This started as a narrower test and it failed: `PublicFixture.sources`
        held the absolute path of every input, and `vent-ball-combine`'s inputs
        live in the same project directory as its reference. Nothing named the
        answer, and the record still disclosed the folder it sits in.

        The fix was structural -- `SourceRef` identifies an input by name and
        hash and cannot express a location -- so the check is structural too. A
        public record with no absolute path in it cannot point at anything,
        including things nobody has thought of yet.
        """
        for fixture_id in FX.fixture_ids():
            with self.subTest(fixture=fixture_id):
                blob = json.dumps(dataclasses.asdict(FX.public(fixture_id)))
                self.assertNotIn(":\\\\", blob)
                self.assertNotIn(":/", blob)
                self.assertNotIn("\\\\\\\\", blob, "no UNC path either")
        self.assertEqual(
            {"name", "sha256", "bytes"},
            {f.name for f in dataclasses.fields(FX.SourceRef)},
            "an input is identified, never located; adding a path field here "
            "reopens the leak")

    def test_nothing_reachable_from_the_public_record_locates_the_reference(self) -> None:
        """The structural claim, tested structurally.

        Not "the loader chose not to return it" -- that is a decision, and a
        decision is one refactor from being reversed. The reference path and its
        hash are in a mapping the public object has no edge to, so no amount of
        attribute access, `repr`, `vars`, `dir` or JSON serialisation of what a
        design agent holds produces either of them.
        """
        for fixture_id in FX.fixture_ids():
            if not FX.has_reference(fixture_id):
                continue
            with self.subTest(fixture=fixture_id):
                secret = FX._REFERENCES[fixture_id]
                text = _all_text(fixture_id)
                for secret_string in (secret.sha256, secret.path, secret.name,
                                      str(FX.recorded_path(secret.path).parent)):
                    for form in _forms(secret_string):
                        self.assertNotIn(form, text, form)

    def test_the_staged_bundle_carries_no_byte_that_leads_to_the_answer(self) -> None:
        """The same wall at the filesystem, where an agent actually works.

        The fixture that matters is `vent-ball-combine`: its reference sits in
        the same project directory its sources came from, so a bundle that merely
        recorded where the inputs live would have handed over the answer's parent
        and one `ls`. That is why the staged bundle copies its sources instead of
        naming them, and why the *parent* is searched for here as well as the file.

        Every form the path could take is searched, not just the raw bytes. A
        Windows path written through `json.dumps` arrives with its backslashes
        doubled, so a bytes-only search would sail past exactly the leak this test
        exists to catch, and pass with the wall down.

        Skipping is decided before the loop rather than inside a `subTest`, where
        `skipTest` is swallowed and the case would report OK having checked
        nothing.
        """
        candidates = [f for f in FX.fixture_ids() if FX.has_reference(f)]
        self.assertIn("vent-ball-combine", candidates)
        for fixture_id in candidates:
            for index in range(len(FX.public(fixture_id).sources)):
                try:
                    FX.source_path(fixture_id, index)
                except FX.FixtureUnavailable as exc:
                    self.skipTest(str(exc))

        with tempfile.TemporaryDirectory() as raw:
            for fixture_id in candidates:
                with self.subTest(fixture=fixture_id):
                    secret = FX._REFERENCES[fixture_id]
                    bundle = FX.public_bundle(fixture_id, Path(raw) / fixture_id)
                    staged = sorted(p for p in bundle.rglob("*") if p.is_file())
                    self.assertTrue(staged)
                    blob = b"\n".join(p.read_bytes() for p in staged)
                    for secret_string in (secret.sha256, secret.path,
                                          secret.name,
                                          str(FX.recorded_path(secret.path).parent)):
                        for form in _forms(secret_string):
                            self.assertNotIn(form.encode(), blob, form)
                    self.assertFalse([p for p in staged
                                      if p.name == secret.name])

    def test_no_request_material_names_the_answer_or_where_it_lives(self) -> None:
        """The softest edge of the wall, and so the one worth sweeping.

        `request_text` returns authored prose. Nothing structural stops a future
        edit from helpfully mentioning the reference file, so every fixture's
        request material is searched, not just the one with the obvious risk.
        """
        self.assertIn("17 mm", FX.request_text("vent-ball-combine"),
                      "the job is still describable without the answer")
        for fixture_id in FX.fixture_ids():
            text = FX.request_text(fixture_id)
            for held in FX._REFERENCES.values():
                with self.subTest(fixture=fixture_id, reference=held.name):
                    for secret_string in (held.sha256, held.path, held.name,
                                          str(FX.recorded_path(held.path).parent)):
                        for form in _forms(secret_string):
                            self.assertNotIn(form, text, form)

    def test_a_vendored_answer_is_kept_out_of_the_directory_the_agent_is_given(self) -> None:
        """Committing the answer must not quietly move it to the public side.

        The public record names exactly one location -- the request material --
        and the fixture directory around it is what a design agent is handed.
        An answer vendored into that directory would be withheld by the loader
        and reachable by one `ls ..`: the leak this module was rewritten to
        close, rebuilt one directory up and inside the repository this time,
        where no worktree has to survive for it to work.

        So the check is placement rather than disclosure. Everything under a
        fixture's own directory is material the agent may read, and the answer
        is not under it.
        """
        for fixture_id in FX.fixture_ids():
            request = FX.REPO_ROOT / FX.public(fixture_id).public_request
            given = request.parent.parent
            with self.subTest(fixture=fixture_id):
                self.assertEqual("public", request.parent.name)
                self.assertEqual(fixture_id, given.name)
                for path in given.rglob("*"):
                    self.assertEqual(
                        "public", path.relative_to(given).parts[0],
                        f"{path} sits in the fixture's own directory, which is "
                        "handed over whole")
                held = FX._REFERENCES.get(fixture_id)
                if held is None or not held.vendored:
                    continue
                answer = held.location.resolve()
                self.assertTrue(answer.is_file())
                self.assertFalse(answer.is_relative_to(given.resolve()),
                                 "one `cd ..` from the request is not a wall")

    def test_asking_for_an_answer_that_is_not_held_is_an_error_not_an_empty_path(self) -> None:
        self.assertFalse(FX.has_reference("component-cycle"))
        with self.assertRaises(KeyError):
            FX.reference("component-cycle")


class Licensing(unittest.TestCase):
    def test_the_by_nc_sa_fixture_is_marked_internal_only(self) -> None:
        record = FX.public("pixel9-card-case")
        self.assertEqual("CC-BY-NC-SA-4.0", record.license)
        self.assertEqual(FX.INTERNAL_ONLY, record.distribution)

    def test_a_redistributable_bundle_refuses_it_rather_than_documenting_a_rule(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(FX.LicenceWithheld) as caught:
                FX.redistributable_bundle("pixel9-card-case", Path(raw) / "out")
            self.assertIn("CC-BY-NC-SA-4.0", str(caught.exception))
            self.assertFalse((Path(raw) / "out").exists(),
                             "the refusal happens before anything is written")

    def test_the_only_redistributable_fixture_is_the_one_we_built(self) -> None:
        shippable = [f for f in FX.fixture_ids()
                     if FX.public(f).distribution == FX.REDISTRIBUTABLE]
        self.assertEqual(["component-cycle"], shippable)
        with tempfile.TemporaryDirectory() as raw:
            bundle = FX.redistributable_bundle("component-cycle",
                                               Path(raw) / "out")
            self.assertTrue((bundle / "request.md").is_file())

    def test_whether_geometry_may_be_committed_is_decided_by_who_made_it(self) -> None:
        """The licensing rule, expressed where it actually bites: placement.

        Vendoring is what stopped the one `PHYSICALLY_PROVEN` fixture from being
        a single `git worktree prune` away from gone, and having worked once it
        is the obvious reach the next time a recorded path looks fragile. The
        next fragile path belongs to somebody else. So the rule is checked
        rather than remembered: the owner's own work may be committed here, and
        nothing else may be -- not the CC-BY-NC-SA case, not a third-party file
        this project has no claim on -- and anything not committed is still
        absent from the tree rather than merely undeclared.
        """
        tracked = [FX.REPO_ROOT / name
                   for name in ("benchmarks", "docs", "skills", "tools")]
        present = {path.name for root in tracked for path in root.rglob("*")
                   if path.is_file()}
        committed = 0
        for fixture_id in FX.fixture_ids():
            licence = FX.public(fixture_id).license
            records = list(FX._SOURCES.get(fixture_id, ()))
            held = FX._REFERENCES.get(fixture_id)
            if held is not None:
                records.append(held)
            for record in records:
                with self.subTest(fixture=fixture_id, file=record.name):
                    if record.vendored:
                        committed += 1
                        self.assertIn(
                            licence, FX.OWN_WORK_LICENSES,
                            "only the owner's own models are copied into this "
                            "repository; everything else is referenced")
                    else:
                        self.assertNotIn(
                            record.name, present,
                            "third-party fixtures are referenced by path and "
                            "hash, never vendored")
        self.assertTrue(committed, "the vendoring this rule governs is gone")

    def test_the_by_nc_sa_case_is_still_referenced_and_not_committed(self) -> None:
        """Named, because it is the one the rule above exists for."""
        for record in FX._SOURCES["pixel9-card-case"]:
            self.assertIsInstance(record, FX.ExternalFile)
            self.assertFalse(record.vendored)


class Resolution(unittest.TestCase):
    _GONE = "benchmarks/references/nowhere/deleted-proof.stl"

    def test_a_missing_vendored_file_is_a_failure_and_not_a_skip(self) -> None:
        """The exact failure mode the vendoring was done to remove.

        `vent-ball-combine` is the only fixture here that has been printed and
        used, and it was recorded at a path inside a sibling worktree with no
        commits behind it. Prune that directory and `resolve` raised
        `FixtureUnavailable`, every caller skipped on it, and the suite reported
        green having lost its only evidence that a job of this shape can be
        finished -- the absence never appearing anywhere a reader would look.

        The bytes are committed now, so their absence is not a fact about the
        machine and does not get to be quiet. The message has to say so, because
        whoever reads it will be reading it in a red suite they did not expect.
        """
        absent = FX.VendoredFile(path=self._GONE, sha256="0" * 64, bytes=1)
        with self.assertRaises(FX.FixtureMissing) as caught:
            FX.resolve(absent, what="the proven fixture")
        message = str(caught.exception)
        self.assertIn("deleted-proof.stl", message)
        self.assertIn("committed", message)
        self.assertNotIn("skipping", message)

    def test_the_missing_vendored_file_is_not_swallowed_by_a_skip_handler(self) -> None:
        """Where a loud failure would have gone quiet again.

        Every skip in this suite is spelled `except FixtureUnavailable:
        skipTest(...)`, in callers nobody would think to re-read. A
        `FixtureMissing` that inherited from it would raise loudly in the test
        above and be silently converted back into a skip everywhere it matters,
        which is the whole defect wearing a new exception name.
        """
        self.assertFalse(issubclass(FX.FixtureMissing, FX.FixtureUnavailable))
        self.assertFalse(issubclass(FX.FixtureUnavailable, FX.FixtureMissing))
        absent = FX.VendoredFile(path=self._GONE, sha256="0" * 64, bytes=1)
        with self.assertRaises(FX.FixtureMissing):
            try:
                FX.resolve(absent, what="the proven fixture")
            except FX.FixtureUnavailable as exc:      # what every caller writes
                self.fail(f"a skip handler caught it: {exc}")

    def test_the_proven_fixture_needs_no_directory_outside_the_repository(self) -> None:
        """Vendored means vendored: verified, and reached from `REPO_ROOT`.

        Not asserted as "it happens to be here on this machine" -- the recorded
        paths are checked to be inside the repository, which is what makes the
        failure above the right one and this fixture unprunable.
        """
        answer = FX.reference("vent-ball-combine")
        self.assertEqual(
            "5d2d7324e87a195eef0b21bf155ac0792184eec33fdfbf6a1273b0b24b03d507",
            hashlib.sha256(answer.read_bytes()).hexdigest())
        for index in range(len(FX.public("vent-ball-combine").sources)):
            path = FX.source_path("vent-ball-combine", index)
            # Raises ValueError if the file is reached from anywhere else.
            path.resolve().relative_to(FX.REPO_ROOT)
        answer.resolve().relative_to(FX.REPO_ROOT)

    def test_git_is_told_not_to_rewrite_the_bytes_it_is_asked_to_preserve(self) -> None:
        """Vendoring only holds if a clone gives the recorded file back.

        Found by staging it. `vent_mount.step` is ASCII with CRLF line endings,
        and git's default text handling normalised it to LF going in and would
        convert it back according to whatever `core.autocrlf` said on the
        machine checking it out. The blob committed was 632,950 bytes of
        something else, and `resolve()` would have raised `FixtureMismatch` --
        correctly, and on every clone, for a file nobody had touched. So the
        recorded bytes are marked `-text`, and every vendored path is checked
        for that mark rather than the two that happen to be ASCII today.

        The set comes from `hash_verified_paths()` rather than being listed here,
        because the trap is worst for the files that look least like geometry:
        `model.py` and `artifact_manifest.json` are plain text, are pinned by
        hash, and would be exactly the ones a reader assumed were safe to let git
        normalise.
        """
        paths = list(FX.hash_verified_paths())
        self.assertTrue(paths)
        for expected in ("benchmarks/references/vent-ball-combine/evidence"
                         "/model.py",
                         "benchmarks/references/vent-ball-combine/evidence"
                         "/artifact_manifest.json",
                         "benchmarks/references/vent-ball-combine/evidence"
                         "/candidate-01.stl"):
            self.assertIn(expected, paths,
                          "a hash-pinned text file left out of the line-ending "
                          "check is the whole CRLF defect again")
        try:
            found = subprocess.run(
                ["git", "check-attr", "text", "--", *paths],
                cwd=FX.REPO_ROOT, capture_output=True, text=True, check=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            self.skipTest(f"git is not usable here: {exc}")
        for line in found.stdout.splitlines():
            with self.subTest(line=line):
                self.assertTrue(
                    line.endswith(": text: unset"),
                    "a hash-verified file left to git's line-ending conversion "
                    "comes back from a clone as different bytes")

    def test_a_missing_file_is_a_skip_with_the_path_in_the_message(self) -> None:
        absent = FX.ExternalFile(path=r"C:\nowhere\absent.3mf", sha256="0" * 64,
                                 bytes=1)
        with self.assertRaises(FX.FixtureUnavailable) as caught:
            FX.resolve(absent, what="absent fixture")
        self.assertIn("absent.3mf", str(caught.exception))
        self.assertIn("skipping", str(caught.exception))

    def test_a_file_whose_bytes_moved_is_a_failure_and_not_a_skip(self) -> None:
        """A fixture whose hash moved is a different fixture.

        Skipping it would leave the L0 numbers asserted against bytes that are no
        longer there, and report the whole thing as green.
        """
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "drifted.3mf"
            path.write_bytes(b"not the recorded bytes")
            wrong_hash = FX.ExternalFile(path=str(path), sha256="0" * 64,
                                         bytes=path.stat().st_size)
            with self.assertRaises(FX.FixtureMismatch):
                FX.resolve(wrong_hash, what="drifted")

            wrong_size = FX.ExternalFile(path=str(path), sha256="0" * 64,
                                         bytes=999999)
            with self.assertRaises(FX.FixtureMismatch) as caught:
                FX.resolve(wrong_size, what="drifted")
            self.assertIn("999999", str(caught.exception))

    def test_the_recorded_hashes_match_the_files_when_the_files_are_here(self) -> None:
        """The manifest's own integrity, on a machine that has the geometry."""
        checked = 0
        for fixture_id in FX.fixture_ids():
            for index, external in enumerate(FX.public(fixture_id).sources):
                try:
                    path = FX.source_path(fixture_id, index)
                except FX.FixtureUnavailable:
                    continue
                with self.subTest(fixture=fixture_id, file=external.name):
                    # Hashed here rather than trusting that `resolve` did it:
                    # `source_path` returning a path proves it checked something,
                    # and this proves what it checked was the recorded digest.
                    self.assertEqual(external.sha256,
                                     hashlib.sha256(path.read_bytes()).hexdigest())
                    self.assertEqual(external.bytes, path.stat().st_size)
                checked += 1
        if not checked:
            self.skipTest("none of the external fixtures are on this machine")


class TheDeliveryRecord(unittest.TestCase):
    """Three claims about the receipt: unchanged, resolvable, and not redirected.

    The manifest names its candidate `candidate-01.stl`, which is what the job
    wrote. Vendoring committed those bytes under the name the part is known by
    and left the manifest's own path with nothing behind it -- a receipt whose
    artifact cannot be opened, which is not a receipt. The two tidy fixes were
    both worse: editing the record makes the snapshot cleaner and less true, and
    dropping the name leaves the dangle. So the duplicate is carried at the
    literal path, and what has to be tested is that carrying it did not turn into
    a lookup that lets any missing artifact find some other file.
    """
    FIXTURE = "vent-ball-combine"
    ANSWER = "5d2d7324e87a195eef0b21bf155ac0792184eec33fdfbf6a1273b0b24b03d507"

    def _staged(self, root: Path) -> Path:
        evidence = FX._DELIVERY_RECORDS[self.FIXTURE].location.parent
        copy = root / "evidence"
        shutil.copytree(evidence, copy)
        return copy

    def test_the_record_the_job_wrote_is_the_record_that_is_here(self) -> None:
        """Unchanged, established by hash rather than by reviewer discipline."""
        record = FX._DELIVERY_RECORDS[self.FIXTURE]
        path = record.location
        self.assertEqual(record.sha256,
                         hashlib.sha256(path.read_bytes()).hexdigest())
        manifest = FX.delivery_record(self.FIXTURE)
        candidate = [a for a in manifest["artifacts"] if a["role"] == "candidate"]
        self.assertEqual(["candidate-01.stl"], [a["path"] for a in candidate],
                         "the record still spells the name the job used; if this "
                         "changed, the snapshot was rewritten after the fact")
        self.assertEqual(self.ANSWER, candidate[0]["sha256"])

    def test_every_path_the_record_names_resolves_to_the_recorded_bytes(self) -> None:
        resolved = FX.delivery_artifacts(self.FIXTURE)
        manifest = FX.delivery_record(self.FIXTURE)
        self.assertEqual({a["id"] for a in manifest["artifacts"]},
                         set(resolved))
        for artifact_id, path in resolved.items():
            with self.subTest(artifact=artifact_id):
                self.assertTrue(path.is_file())
                path.resolve().relative_to(FX.REPO_ROOT)

    def test_the_duplicate_at_the_manifest_path_is_the_retained_artifact(self) -> None:
        """Equivalence stated, not assumed, because it is why the cost is near nil.

        Byte-identical means git stores one blob and this is a second tree entry.
        If the two ever diverge, that reasoning is wrong and the repository is
        quietly carrying two different candidates under one hash claim.
        """
        delivered = FX.delivery_artifacts(self.FIXTURE)["candidate-01"]
        retained = FX.reference(self.FIXTURE)
        self.assertNotEqual(delivered, retained)
        self.assertEqual(delivered.read_bytes(), retained.read_bytes())
        self.assertEqual(self.ANSWER,
                         hashlib.sha256(delivered.read_bytes()).hexdigest())

    def test_the_alias_record_says_what_the_duplicate_is_and_is_not_evidence(self) -> None:
        aliases = FX.historical_aliases(self.FIXTURE)
        self.assertEqual(1, len(aliases))
        alias = aliases[0]
        self.assertEqual("candidate-01.stl", alias["original_path"])
        self.assertEqual(Path(FX.reference(self.FIXTURE)).name,
                         alias["retained_equivalent"])
        self.assertEqual(FX.BYTE_IDENTICAL, alias["relationship"])
        self.assertEqual(self.ANSWER, alias["sha256"])
        evidence = FX._DELIVERY_RECORDS[self.FIXTURE].location.parent
        record = FX.REPO_ROOT / FX._ALIAS_RECORDS[self.FIXTURE]
        self.assertFalse(record.resolve().is_relative_to(evidence.resolve()),
                         "commentary on the evidence does not live inside it")

    def test_the_alias_record_cannot_stand_in_for_the_file_it_explains(self) -> None:
        """The property that keeps 'every path resolves' worth asserting.

        An alias is recorded for exactly this path, and its retained equivalent
        is on disk with the right hash. Resolution still has to fail, because the
        moment a missing artifact can be satisfied by a same-hash file under
        another name, the check stops being about the record and starts being
        about whether the bytes exist somewhere.
        """
        self.assertIn("candidate-01.stl",
                      [a["original_path"]
                       for a in FX.historical_aliases(self.FIXTURE)])
        self.assertTrue(FX.reference(self.FIXTURE).is_file())
        with tempfile.TemporaryDirectory() as raw:
            staged = self._staged(Path(raw))
            (staged / "candidate-01.stl").unlink()
            with self.assertRaises(FX.FixtureMissing) as caught:
                FX.delivery_artifacts(self.FIXTURE, directory=staged)
            self.assertIn("candidate-01.stl", str(caught.exception))

    def test_a_delivered_artifact_whose_bytes_moved_is_a_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            staged = self._staged(Path(raw))
            (staged / "candidate-01.stl").write_bytes(b"not the delivered bytes")
            with self.assertRaises(FX.FixtureMismatch) as caught:
                FX.delivery_artifacts(self.FIXTURE, directory=staged)
            self.assertIn(self.ANSWER, str(caught.exception))

    def test_a_record_that_addresses_outside_its_own_bundle_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(FX.FixtureMismatch):
                FX._resolve_delivered(
                    Path(raw), {"path": "../escaped.stl", "sha256": "0" * 64},
                    what="escaping artifact")


class TheImmutableFiles(unittest.TestCase):
    """What is outside tooling control, and what stops it drifting anyway."""
    FIXTURE = "vent-ball-combine"
    MODEL = "benchmarks/references/vent-ball-combine/evidence/model.py"

    def test_the_design_source_is_byte_identical_to_what_ran(self) -> None:
        """The hash the lint exclusion does not provide.

        Excluding the file stops a formatter rewriting it. It does nothing about
        a hand edit, and the file's entire claim is that there has not been one.
        """
        path = FX.design_source(self.FIXTURE)
        self.assertEqual(
            "c48ec3660669376fedfa589da38401a98e8e0710f38b2aa50a4a2eaefa3f464a",
            hashlib.sha256(path.read_bytes()).hexdigest())
        path.resolve().relative_to(FX.REPO_ROOT)

    def test_the_lint_exclusion_names_one_file_and_not_the_tree_above_it(self) -> None:
        """The ownership boundary, checked where it is actually written.

        `benchmarks/references/` also holds the delivery record, the alias record
        and the renders; a directory-level exclusion would put any maintained
        file later dropped in there outside the linter without anyone deciding
        that. The exclusion is one path, and it is a path this module also pins
        by hash -- excluding a file nothing verifies would be the worse half of
        the pair on its own.
        """
        config = tomllib.loads(
            (FX.REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        excluded = config["tool"]["ruff"]["extend-exclude"]
        self.assertEqual([self.MODEL], excluded)
        self.assertTrue(
            config["tool"]["ruff"].get("force-exclude"),
            "without this ruff lints -- and `--fix` rewrites -- an excluded path "
            "that is passed to it directly, which is how pre-commit and "
            "format-on-save call it")
        self.assertTrue((FX.REPO_ROOT / self.MODEL).is_file(),
                        "an exclusion pointing at nothing is a stale rule")
        self.assertIn(self.MODEL, FX.hash_verified_paths())
        for entry in excluded:
            with self.subTest(entry=entry):
                self.assertTrue((FX.REPO_ROOT / entry).is_file(),
                                "exclusions here name files, not directories")

    def test_the_rest_of_the_evidence_tree_is_still_linted(self) -> None:
        """Named, because the previous rule silently covered all of it."""
        tree = FX.REPO_ROOT / "benchmarks" / "references"
        scripts = sorted(p.relative_to(FX.REPO_ROOT).as_posix()
                         for p in tree.rglob("*.py"))
        self.assertEqual([self.MODEL], scripts,
                         "a second Python file under the evidence tree is now "
                         "linted; if it is another immutable artifact it wants "
                         "its own documented subtree, not a wider exclusion")


class TheRecordedPathFlavourTest(unittest.TestCase):
    r"""A recorded path is parsed as it was written, on whatever host reads it.

    `Path` is the host, and the host is not the authority on another machine's
    path. On Linux `Path(r"C:\proj\knob.step")` has no separators in it, so
    `.name` is the whole string and `.parent` is `"."`. Both were live defects
    and neither was cosmetic: the basename went into `SourceRef.name` and
    published a full Windows path in the public record, and the parent was what
    three wall tests searched their material for -- so they searched every
    fixture's prose for `"."`, found it, and reported a leak on all of them.

    These cases are written against paths from the *other* OS on purpose. That
    is the only arrangement in which a host-flavour regression is visible.
    """

    WINDOWS = r"C:\github\3D\Berlingo gear shift knob\v4-cadquery\knob_v4.step"
    UNC = r"\\workshop\projects\3D\vent-mount\reference.stl"
    POSIX = "/home/owner/projects/3d/vent-mount/reference.stl"

    def _external(self, path: str) -> FX.ExternalFile:
        return FX.ExternalFile(path=path, sha256="0" * 64, bytes=1)

    def test_a_windows_drive_path_keeps_windows_semantics_here(self) -> None:
        self.assertEqual("knob_v4.step", self._external(self.WINDOWS).name)
        self.assertEqual(r"C:\github\3D\Berlingo gear shift knob\v4-cadquery",
                         str(FX.recorded_path(self.WINDOWS).parent))

    def test_a_unc_path_keeps_windows_semantics_here(self) -> None:
        self.assertEqual("reference.stl", self._external(self.UNC).name)
        self.assertEqual(r"\\workshop\projects\3D\vent-mount",
                         str(FX.recorded_path(self.UNC).parent))

    def test_a_posix_path_keeps_posix_semantics_here(self) -> None:
        self.assertEqual("reference.stl", self._external(self.POSIX).name)
        self.assertEqual("/home/owner/projects/3d/vent-mount",
                         str(FX.recorded_path(self.POSIX).parent))

    def test_the_flavour_is_chosen_by_the_recording_and_never_by_the_host(self) -> None:
        """The rule itself, so a change to it has to be deliberate."""
        for path in (self.WINDOWS, self.UNC, r"C:/proj/knob.step"):
            with self.subTest(path=path):
                self.assertIs(FX.PureWindowsPath, FX.recorded_flavour(path))
        for path in (self.POSIX, "relative/dir/knob.step"):
            with self.subTest(path=path):
                self.assertIs(FX.PurePosixPath, FX.recorded_flavour(path))

    def test_the_basename_is_the_same_answer_on_either_host(self) -> None:
        """What `.name` must satisfy, written so it cannot pass by accident.

        A host-`Path` implementation returns the whole recorded string on Linux
        and the basename on Windows. Asserting the basename *and* that the
        answer is shorter than the recording catches it either way round.
        """
        for path, expected in ((self.WINDOWS, "knob_v4.step"),
                               (self.UNC, "reference.stl"),
                               (self.POSIX, "reference.stl")):
            with self.subTest(path=path):
                name = self._external(path).name
                self.assertEqual(expected, name)
                self.assertNotIn("\\", name)
                self.assertNotIn("/", name)
                self.assertLess(len(name), len(path))

    def test_every_leak_form_of_a_recorded_parent_is_searched(self) -> None:
        """Raw, JSON-escaped and slash-normalised, which is three spellings.

        A parent that arrives through `json.dumps` has its backslashes doubled
        and a URL or POSIX normalisation turns them into forward slashes. The
        wall tests search all three; this asserts there really are three for a
        Windows recording, because a `"."` parent collapses them into one and
        that is what the defect looked like.
        """
        parent = str(FX.recorded_path(self.WINDOWS).parent)
        forms = _forms(parent)
        self.assertEqual(3, len(forms), forms)
        self.assertIn(parent, forms)
        self.assertIn(parent.replace("\\", "\\\\"), forms)
        self.assertIn(parent.replace("\\", "/"), forms)
        self.assertNotIn(".", forms, "a bare '.' matches every file ever written")

    def test_no_public_record_holds_a_reference_name_path_parent_or_digest(self) -> None:
        """The wall, restated over the values this repair changed.

        `.name` is what `SourceRef` publishes, so a regression here is a leak
        into the public record rather than only a wrong string.
        """
        for fixture_id in FX.fixture_ids():
            if not FX.has_reference(fixture_id):
                continue
            held = FX._REFERENCES[fixture_id]
            text = _all_text(fixture_id)
            with self.subTest(fixture=fixture_id):
                for secret in (held.sha256, held.path, held.name,
                               str(FX.recorded_path(held.path).parent)):
                    for form in _forms(secret):
                        self.assertNotIn(form, text, form)


if __name__ == "__main__":
    unittest.main()
