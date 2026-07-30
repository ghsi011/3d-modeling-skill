#!/usr/bin/env python3
"""The manifest's two claims, tested as claims rather than as documentation.

`tools/fixtures.py` asserts three things about itself: that evidence is recorded
honestly, that the answer cannot reach a design agent, and that licensed geometry
cannot leave the machine. The first is a data question and the last two are
structural, so they are tested structurally -- by asking what is reachable from
the object a design agent is handed, not by checking that a function chose not to
return something.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import sys
import tempfile
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
                                      str(Path(secret.path).parent)):
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
                                          str(Path(secret.path).parent)):
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
                                          str(Path(held.path).parent)):
                        for form in _forms(secret_string):
                            self.assertNotIn(form, text, form)

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

    def test_no_licensed_geometry_was_copied_into_the_repository(self) -> None:
        """Repo weight and third-party licensing argue for the same thing."""
        tracked = [FX.REPO_ROOT / name
                   for name in ("benchmarks", "docs", "skills", "tools")]
        present = {path.name for root in tracked for path in root.rglob("*")
                   if path.is_file()}
        for fixture_id in FX.fixture_ids():
            for external in FX.public(fixture_id).sources:
                with self.subTest(fixture=fixture_id, file=external.name):
                    self.assertNotIn(
                        external.name, present,
                        "external fixtures are referenced by path and hash, "
                        "never vendored")


class Resolution(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
