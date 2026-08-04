"""The external corpus loader: identity, and the difference between two failures.

A blind benchmark's one indispensable property is that the reference is the
reference. Everything else it reports is downstream of that, so the loader's job
is not to find files -- it is to refuse the ones that are not what they claim.

The distinction these tests exist for is `MISSING` against `CORRUPT`. A checkout
that has fetched nothing is ordinary and its benchmarks report unavailable. A
file that is present and hashes differently is a reference that has drifted, and
a score against a drifted reference is a number indistinguishable from a real
one. Collapsing the second into the first is the cheapest way to make this whole
mechanism decorative.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import corpus


def _manifest(root: Path, digest: str) -> dict:
    return {
        "schema_version": 1,
        "roots": {"default": str(root)},
        "sources": {"demo": {"kind": "git", "url": "https://example.invalid/x.git",
                             "ref": "0" * 40, "sparse": ["STLs"], "into": "demo",
                             "license": "GPL-3.0-only"}},
        "entries": [{"id": "demo-part", "source": "demo",
                     "path": "STLs/part.stl", "sha256": digest,
                     "role": "REFERENCE"}],
    }


class TheLoaderRefusesWhatItCannotVouchForTest(unittest.TestCase):

    def test_a_present_and_matching_entry_resolves(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            part = root / "demo" / "STLs" / "part.stl"
            part.parent.mkdir(parents=True)
            part.write_bytes(b"solid demo\nendsolid\n")
            payload = _manifest(root, corpus._digest(part))

            self.assertEqual(part, corpus.resolve("demo-part", payload))
            self.assertEqual({"demo-part": "OK"}, corpus.verify(payload))

    def test_a_missing_entry_is_unavailable_and_says_how_to_get_it(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            payload = _manifest(Path(raw), "0" * 64)
            with self.assertRaises(corpus.CorpusUnavailable) as caught:
                corpus.resolve("demo-part", payload)
            self.assertIn("tools/corpus.py --fetch", str(caught.exception))
            self.assertEqual({"demo-part": "MISSING"}, corpus.verify(payload))

    def test_a_drifted_entry_is_corrupt_and_not_merely_missing(self) -> None:
        """The distinction this module exists for.

        `CorpusCorrupt` is not a subclass of `CorpusUnavailable` and must never
        be caught by a handler reaching for the other: one means "this machine
        has not fetched", the other means "the reference is not the reference".
        """
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            part = root / "demo" / "STLs" / "part.stl"
            part.parent.mkdir(parents=True)
            part.write_bytes(b"solid demo\nendsolid\n")
            payload = _manifest(root, corpus._digest(part))
            part.write_bytes(b"solid something else\nendsolid\n")

            with self.assertRaises(corpus.CorpusCorrupt) as caught:
                corpus.resolve("demo-part", payload)
            self.assertIn("drifted", str(caught.exception))
            self.assertEqual({"demo-part": "CORRUPT"}, corpus.verify(payload))
            self.assertNotIsInstance(caught.exception, corpus.CorpusUnavailable)

    def test_the_digest_is_checked_on_every_call_not_once_at_fetch(self) -> None:
        """A file verified when it arrived says nothing about the file now."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            part = root / "demo" / "STLs" / "part.stl"
            part.parent.mkdir(parents=True)
            part.write_bytes(b"solid demo\nendsolid\n")
            payload = _manifest(root, corpus._digest(part))
            corpus.resolve("demo-part", payload)          # fine

            part.write_bytes(b"solid tampered\nendsolid\n")
            with self.assertRaises(corpus.CorpusCorrupt):
                corpus.resolve("demo-part", payload)

    def test_an_unknown_id_names_what_there_is(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            payload = _manifest(Path(raw), "0" * 64)
            with self.assertRaises(KeyError) as caught:
                corpus.resolve("no-such-part", payload)
            self.assertIn("demo-part", str(caught.exception))

    def test_the_root_can_be_moved_without_editing_a_committed_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            payload = _manifest(Path("/nonexistent"), "0" * 64)
            import os
            os.environ[corpus.ROOT_ENV] = raw
            try:
                self.assertEqual(Path(raw), corpus.corpus_root(payload))
            finally:
                del os.environ[corpus.ROOT_ENV]


class TheCommittedManifestIsWellFormedTest(unittest.TestCase):
    """The real one, checked for the properties a reader depends on."""

    def setUp(self) -> None:
        self.payload = corpus.manifest()

    def test_every_entry_names_a_declared_source(self) -> None:
        sources = set(self.payload["sources"])
        for row in self.payload["entries"]:
            with self.subTest(entry=row["id"]):
                self.assertIn(row["source"], sources)

    def test_every_entry_carries_a_full_digest(self) -> None:
        for row in self.payload["entries"]:
            with self.subTest(entry=row["id"]):
                self.assertRegex(row["sha256"], r"^[0-9a-f]{64}$")

    def test_every_source_is_pinned_to_a_commit_not_a_branch(self) -> None:
        """A branch moves and the digests do not."""
        for name, source in self.payload["sources"].items():
            with self.subTest(source=name):
                self.assertRegex(source["ref"], r"^[0-9a-f]{40}$")

    def test_every_source_records_a_licence(self) -> None:
        for name, source in self.payload["sources"].items():
            with self.subTest(source=name):
                self.assertTrue(source.get("license"),
                                "a corpus entry with no licence is one nobody "
                                "can decide where to put")

    def test_nothing_in_the_corpus_is_inside_this_repository(self) -> None:
        """The rule the whole file exists to keep.

        `AGENTS.md`: never place licensed third-party artifacts in this
        repository. A root that resolved inside it would put them there on the
        next fetch, and the fetch is the thing nobody watches.
        """
        root = corpus.corpus_root(self.payload).resolve()
        self.assertFalse(
            str(root).startswith(str(corpus.ROOT.resolve()) + "/")
            or root == corpus.ROOT.resolve(),
            f"the corpus root {root} is inside the repository at {corpus.ROOT}")
        for row in self.payload["entries"]:
            with self.subTest(entry=row["id"]):
                where = corpus.location(row["id"], self.payload).resolve()
                self.assertFalse(str(where).startswith(
                    str(corpus.ROOT.resolve()) + "/"))


if __name__ == "__main__":
    unittest.main()
