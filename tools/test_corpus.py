r"""The external corpus loader: identity, and the wall between question and answer.

A blind benchmark's one indispensable property is that the reference is the
reference. Everything else it reports is downstream of that, so the loader's job
is not to find files -- it is to refuse the ones that are not what they claim.

The distinction the first half of this file exists for is `MISSING` against
`CORRUPT`. A checkout that has fetched nothing is ordinary and its benchmarks
report unavailable. A file that is present and hashes differently is a reference
that has drifted, and a score against a drifted reference is a number
indistinguishable from a real one. Collapsing the second into the first is the
cheapest way to make this whole mechanism decorative.

The second half is the other direction: not the answer arriving wrong, but the
answer arriving *early*, in the material a generator writes the question from.
"""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

import corpus


def _manifest(root: Path, digest: str) -> dict:
    return {
        "schema_version": 1,
        "roots": {"default": str(root)},
        "request_vocabulary": ["flat panel"],
        "sources": {"demo": {"kind": "git", "url": "https://example.invalid/x.git",
                             "ref": "0" * 40, "sparse": ["STLs"], "into": "demo",
                             "license": "GPL-3.0-only"}},
        "entries": [{"id": "demo-part", "source": "demo",
                     "path": "STLs/part.stl", "sha256": digest,
                     "role": "REFERENCE",
                     "request": {"purpose": "Holds a panel flat.",
                                 "interfaces": ["flat panel"]}}],
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


class TheQuestionDoesNotCarryTheAnswerTest(unittest.TestCase):
    r"""A blind benchmark's answer must not reach whoever writes its question.

    Three versions of this, and the first two failed the same way.

    `corpus.json` originally carried each reference's bounding box in its
    `note`, beside the entry id. The first guard was a regular expression in
    *this file*, matching a number next to a length unit or an `A x B` pair. A
    review broke it twelve ways in one pass -- `20.00 by 14.50 by 5.80` is the
    sentence it was written for with one word changed -- and two of its four
    branches were dead on arrival, because `\b` after a non-word character
    requires a word character next, so neither `45 degrees` nor `45° chamfer`
    ever matched.

    The second guard widened the pattern to "no digit in any string, except
    these fifteen key names". A second review broke that nineteen ways: the
    measurement went into a JSON number, into a dict *key*, into `attribution`,
    into a fullwidth digit, into a Roman numeral -- and, already committed in
    the very diff that scrubbed the notes, into the entry id
    `voron-deck-support-3mm`. It also proved the two tests written to
    demonstrate the guard were tautologies over their own literals: replace the
    enforcing rule with `re.compile(r"(?!x)x")`, restore the original bounding
    box to a note, and the suite stayed green.

    Both failures are one failure. A rule in a test constrains the committed
    text; the leak happens in whatever a generator is *handed*. So the rule is
    `corpus.request_view` now, it is the only door to question material, and
    these tests call it instead of restating it -- mutate `corpus.leaks` and
    every test below goes red, which is the property the previous two versions
    did not have.

    What is enforced, exactly: no numeric character, numeral or number-word
    reaches question material, except through a term on `request_vocabulary`.
    Not "no measurement can leak" -- a purpose can still describe a shape in
    words. A weaker method may not issue a stronger claim.
    """

    def setUp(self) -> None:
        self.payload = corpus.manifest()

    def _entry(self, **request):
        """A manifest whose one entry carries the request block given."""
        payload = copy.deepcopy(self.payload)
        payload["entries"] = [{**self.payload["entries"][0],
                               "request": request}]
        return payload

    def test_every_committed_entry_offers_a_clean_question(self) -> None:
        for entry_id in sorted(corpus.entries(self.payload)):
            with self.subTest(entry=entry_id):
                view = corpus.request_view(entry_id, self.payload)
                self.assertEqual({"purpose", "interfaces"}, set(view))

    def test_the_question_names_no_identifier_path_or_digest(self) -> None:
        """An id is a place a measurement hides; a path is one `ls` from the answer.

        `voron-deck-support-3mm` was the committed id at the moment the notes
        were scrubbed, and `deck_support_3mm_x8.stl` still is the path -- it is
        the vendor's own filename and cannot be renamed. Neither can reach a
        question, so neither needs a rule about its contents.
        """
        for entry_id, row in sorted(corpus.entries(self.payload).items()):
            with self.subTest(entry=entry_id):
                view = corpus.request_view(entry_id, self.payload)
                flat = repr(view)
                for field in ("id", "path", "sha256", "source", "role"):
                    self.assertNotIn(field, view)
                    self.assertNotIn(str(row[field]), flat)

    def test_the_rule_refuses_every_bypass_two_reviews_found(self) -> None:
        r"""Each of these defeated a previous guard. None may pass this one.

        Through `corpus.leaks`, the function `request_view` itself calls, so
        weakening the rule fails this test. The version this replaces asserted
        `re.findall(r"\d", text)` over its own literals and protected nothing.
        """
        bypasses = (
            # Defeated the pattern guard.
            "Single body, watertight, 20.00 by 14.50 by 5.80.",
            "20.00 * 14.50 * 5.80",
            "bbox [20.0, 14.5, 5.8]",
            "20,00 / 14,50 / 5,80",
            "radius 2.5 millimetres",
            "0.787 inches",
            "1200 microns",
            "118 thou",
            "Two M3 holes on a pitch of 15",
            "Print at 1:1",
            "A 45° chamfer.",
            "45 degrees of draft.",
            "20mm_wide slot",
            # Defeated the digit guard. Not one of these holds an ASCII digit.
            "Twenty by fourteen point five by five point eight millimetres.",
            "２０.００ by １４.５０",   # fullwidth
            "٢٠ by ١٤",                             # Arabic-Indic
            "²⁰ by ¹⁴; wall ½ that.",          # superscript, fraction
            "⑳ by ⑭ by ⑤.",                              # circled
            "XX by XIV by VI.",                                         # Roman
            "Single body.",                                             # states the bodies check
        )
        for text in bypasses:
            with self.subTest(bypass=text):
                self.assertTrue(
                    corpus.leaks(text),
                    "this string defeated an earlier guard and must not defeat "
                    "this one")

    def test_a_purpose_that_states_no_quantity_is_allowed(self) -> None:
        """Over the committed prose, not over literals written to pass.

        The rule must let a real description through or it is a ban, and the
        descriptions that matter are the ones in the file.
        """
        for entry_id, row in sorted(corpus.entries(self.payload).items()):
            with self.subTest(entry=entry_id):
                self.assertEqual((), corpus.leaks(row["request"]["purpose"]))

    def test_a_quantity_in_a_purpose_is_refused(self) -> None:
        for purpose in ("Holds a 3 mm panel.",
                        "Holds a three-millimetre panel.",
                        "Holds a panel. Single body."):
            with self.subTest(purpose=purpose):
                with self.assertRaises(corpus.CorpusLeak):
                    corpus.request_view("voron-deck-support",
                                        self._entry(purpose=purpose,
                                                    interfaces=[]))

    def test_a_measurement_that_is_not_a_string_has_nowhere_to_go(self) -> None:
        """The channels the digit guard could not see, closed by the key whitelist.

        A JSON number, a list of them and a measurement used as a dict *key* all
        passed the previous rule, which walked to string leaves and yielded
        values. Here they are neither scanned nor refused -- they are
        unrepresentable, because two keys exist and both have a pinned type.
        """
        cases = {
            "json numbers": {"purpose": "Holds a panel.", "interfaces": [],
                             "bbox": [20.0, 14.5, 5.8]},
            "json scalar": {"purpose": "Holds a panel.", "interfaces": [],
                            "height_mm": 5.8},
            "dict key": {"purpose": "Holds a panel.", "interfaces": [],
                         "envelope": {"20.00 x 14.50 x 5.80": "bounding box"}},
            "purpose is a number": {"purpose": 5.8, "interfaces": []},
            "interfaces is prose": {"purpose": "Holds a panel.",
                                    "interfaces": "20.00 x 14.50"},
        }
        for name, request in cases.items():
            with self.subTest(channel=name):
                with self.assertRaises(corpus.CorpusLeak):
                    corpus.request_view("voron-deck-support",
                                        self._entry(**request))

    def test_an_interface_off_the_declared_disclosure_is_refused(self) -> None:
        """Interfaces may carry measurements. Only the ones declared."""
        with self.assertRaises(corpus.CorpusLeak) as caught:
            corpus.request_view(
                "voron-deck-support",
                self._entry(purpose="Holds a panel.",
                            interfaces=["20.00 x 14.50 x 5.80 envelope"]))
        self.assertIn("request_vocabulary", str(caught.exception))

    def test_the_declared_disclosure_is_pinned(self) -> None:
        """Growing it is an edit here, so a new disclosure cannot pass unread.

        This is the whole difference between this list and the exemption list it
        replaced. An exemption grew whenever an ordinary field needed a digit --
        a sparse-checkout path, a second corpus root -- and each growth silently
        reopened the hole. A disclosure names the dimension being given away,
        and adding one turns this test red until somebody writes it down.
        """
        self.assertEqual(
            ["2020 aluminium extrusion", "3 mm flat panel", "M3 fastener",
             "MGN9 linear rail", "flat panel", "toothed belt"],
            self.payload["request_vocabulary"])

    def test_an_entry_with_no_request_block_is_refused_not_improvised(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["entries"] = [{k: v for k, v in self.payload["entries"][0].items()
                               if k != "request"}]
        with self.assertRaises(corpus.CorpusLeak):
            corpus.request_view("voron-deck-support", payload)

    def test_material_outside_a_request_is_not_the_generators_business(self) -> None:
        """And so may carry digits, which the previous rule taxed for nothing.

        Under the digit guard `ARCHITECTURE.md 16.6` had to be written "section
        sixteen point six", which broke the cross-reference every other pointer
        in the repository greps for, and `M3 fasteners` became "metric
        fasteners" in a sentence that still promised "the vocabulary a person
        would actually use". Both are back, because neither is question material
        and the wall is no longer made of prose.
        """
        self.assertIn("16.6", self.payload["note"])
        self.assertIn("M3 fasteners", self.payload["sources"]["voron2"]["why"])


if __name__ == "__main__":
    unittest.main()
