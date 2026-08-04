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
import re
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


class TheManifestPublishesNoGeometryTest(unittest.TestCase):
    """A blind benchmark's answer must not be committed beside its question.

    The first version of `corpus.json` carried each reference's bounding box in
    its `note`, correct to the stated precision, beside the entry id -- in the
    file a request generator reads.

    The first version of *this guard* then matched a number adjacent to a length
    unit, or an `A x B` pair. An independent review broke it in a dozen ways in
    one pass: `20.00 by 14.50 by 5.80`, `20.00 * 14.50`, `bbox [20.0, 14.5, 5.8]`,
    `0.787 inches`, `1200 microns`, `Twenty by fourteen`, `radius 2.5
    millimetres`. Every one is the whole leak restored. Its `deg` branch did not
    even match `45 degrees`, and its `°` branch did not match `45° chamfer`,
    because a `\b` after a non-word character requires a word character next.

    So the rule is now the crude one -- **no digit in any prose string** -- and
    it is enforced over every string in the manifest except the identifier
    fields. A guard with a pattern to evade is a guard. A rule with nothing to
    evade is a wall, and this file is the wall.

    The identifier fields are exempt on purpose and it is worth saying why. An
    entry id names which real part a reference is; anyone holding it can go and
    fetch that part. The id is the *handle*, not the secret. What the manifest
    must never do is state the measurement in the same breath, because that is
    the one thing a blind reconstruction has to produce for itself.
    """

    # Identifiers, digests and locations. They name a thing; they do not measure
    # one. Everything not on this list is prose and is scanned.
    EXEMPT = frozenset({"id", "path", "sha256", "ref", "url", "license",
                        "into", "kind", "source", "role", "schema_version",
                        "redistribution", "branch", "default", "attribution"})

    def setUp(self) -> None:
        self.payload = corpus.manifest()

    def _strings(self, node, where="", key=None):
        """Every string in the manifest, with the key it arrived under."""
        if isinstance(node, dict):
            for k, v in node.items():
                yield from self._strings(v, f"{where}.{k}" if where else k, k)
        elif isinstance(node, list):
            for n, v in enumerate(node):
                yield from self._strings(v, f"{where}[{n}]", key)
        elif isinstance(node, str) and key not in self.EXEMPT:
            yield where, node

    def test_no_prose_field_contains_a_digit(self) -> None:
        for where, text in self._strings(self.payload):
            with self.subTest(field=where):
                digits = re.findall(r"\d", text)
                self.assertEqual(
                    [], digits,
                    f"{where} contains {len(digits)} digit(s). A prose field "
                    "names what a part is for; a measurement is the answer a "
                    "blind benchmark withholds, and every pattern narrower "
                    "than 'no digits' has been evaded already.")

    def test_the_guard_refuses_every_bypass_the_review_found(self) -> None:
        """Each of these defeated the previous guard. None may pass this one.

        Pinned individually rather than as 'something matched', because the
        previous mutation test asserted only that the string matched *somewhere*
        -- and it retained an unrelated unit, so deleting the entire bounding-box
        branch left it green.
        """
        bypasses = (
            "Single body, watertight, 20.00 by 14.50 by 5.80.",
            "20.00 * 14.50 * 5.80",
            "bbox [20.0, 14.5, 5.8]",
            "20.00 / 14.50 / 5.80 (millimeters)",
            "20,00 / 14,50 / 5,80",
            "radius 2.5 millimetres",
            "0.787 inches",
            "1200 microns",
            "118 thou",
            "Two M3 holes on a pitch of 15",
            "Print at 1:1",
            "A 45\u00b0 chamfer.",
            "45 degrees of draft.",
            "20mm_wide slot",
            "Supports a deck panel. Single body, 20.00 x 14.50 x 5.80 mm.",
        )
        for text in bypasses:
            with self.subTest(bypass=text):
                self.assertTrue(
                    re.findall(r"\d", text),
                    "this string defeated the previous guard and must not "
                    "defeat this one")

    def test_a_purpose_without_a_measurement_is_allowed(self) -> None:
        """The guard must let a legitimate description through, or it is a ban."""
        for text in ("Retains a bottom panel in the extrusion slot.",
                     "Clamps a toothed belt end. Single body, watertight.",
                     "Holds a linear rail true to an extrusion."):
            with self.subTest(note=text):
                self.assertEqual([], re.findall(r"\d", text))


if __name__ == "__main__":
    unittest.main()
