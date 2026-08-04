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
        "schema_version": 2,
        "roots": {"default": str(root)},
        "sources": {"demo": {"kind": "git", "url": "https://example.invalid/x.git",
                             "ref": "0" * 40, "sparse": ["STLs"], "into": "demo",
                             "license": "GPL-3.0-only"}},
        "entries": [{"id": "demo-part", "source": "demo",
                     "path": "STLs/part.stl", "sha256": digest,
                     "role": "REFERENCE",
                     "request": {
                         "purpose": "Holds a panel flat against an extrusion.",
                         "requirements": [
                             {"name": "panel_stock", "value": 3.0, "unit": "mm",
                              "provenance": "MEASURED", "source": "calipers",
                              "note": ""}]}}],
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
                where = corpus._location(row["id"], self.payload).resolve()
                self.assertFalse(str(where).startswith(
                    str(corpus.ROOT.resolve()) + "/"))


class TheQuestionCarriesMeasurementsButNotTheAnswerTest(unittest.TestCase):
    r"""A request is full of numbers. None of them may be the part's own size.

    Three designs and a correction, and the first three all failed the same way:
    they were rules about *how a leak is spelled*.

    A regex matching a number next to a unit -- broken twelve ways in one review
    pass. Then "no digit in any string" with an exemption list -- nineteen. Then
    a twenty-word denylist of the part's own vocabulary -- about eighty, with
    `girth`, `ht`, `part_thickness` and `overall` walking straight through, and
    four of its own entries unable to match themselves because the tokenizer
    split on underscores and `bounding_box` has one.

    Each round got harder to evade and no closer to being right, because a real
    request *is* measurements: somebody puts calipers on the extrusion slot and
    the panel edge and writes the numbers down, and a request with those
    stripped out is not a hard benchmark but an unanswerable one. The question
    was never how the number is spelled. It is what the number measures.

    So two mechanisms, and the second exists because the first cannot work
    alone:

    * **names are allowlisted.** A requirement's leading token must be one of
      the entry's declared `counterparts`. Every other allowlist in this module
      -- `REQUEST_KEYS`, `REQUIREMENT_KEYS`, `REQUEST_PROVENANCE` -- is a thing
      nothing got through; the single denylist is the thing eighty names got
      through.
    * **numbers are checked against the reference.** No wording rule can catch
      `extrusion_series: "2020"` on a part whose x-extent is exactly 20.0 mm.
      That is not hypothetical: it is what this manifest shipped, found by a
      review measuring the STLs. So every number anywhere in the question is
      compared against the reference's own extents and volume.

    What is enforced is in `request_view`'s docstring, and it stops short of
    "the answer cannot leak" -- a purpose can still describe a shape in words
    carrying no number at all, and with the corpus absent the second check
    cannot run and the view says so.
    """

    def setUp(self) -> None:
        self.payload = corpus.manifest()

    def _entry(self, entry_id="voron-deck-support", **over):
        payload = copy.deepcopy(self.payload)
        row = next(r for r in payload["entries"] if r["id"] == entry_id)
        request = dict(row["request"])
        request.update(over.pop("request", {}))
        if "extra" in over:
            request["requirements"] = list(request["requirements"]) + [over.pop("extra")]
        payload["entries"] = [{**row, **over, "request": request}]
        return payload

    def _refused(self, **over):
        with self.assertRaises(corpus.CorpusLeak):
            corpus.request_view("voron-deck-support", self._entry(**over))

    def _req(self, **over):
        base = {"name": "panel_stock", "value": 3.0, "unit": "mm",
                "provenance": "STATED", "source": "published hardware", "note": ""}
        return {**base, **over}

    # -- what the corpus ships -------------------------------------------

    def test_every_committed_entry_offers_an_answerable_question(self) -> None:
        for entry_id in corpus.question_ids(self.payload):
            with self.subTest(entry=entry_id):
                view = corpus.request_view(entry_id, self.payload)
                self.assertEqual({"purpose", "requirements",
                                  "build_envelope_mm", "discloses",
                                  "checked_against_reference"}, set(view))
                self.assertTrue(view["requirements"])

    def test_every_committed_request_carries_measurements_with_a_source(self) -> None:
        """The property the digit rules destroyed in order to protect.

        Deliberately *not* asserting anything is `MEASURED`. The version of this
        test that did was requiring a false claim: six rows said `MEASURED` with
        sources like "calipers across the slot mouth", and nobody in this
        repository has calipers or the parts. Making the manifest honest turned
        the suite red, which is a test doing the opposite of its job.
        """
        for entry_id in corpus.question_ids(self.payload):
            for row in corpus.request_view(entry_id, self.payload)["requirements"]:
                with self.subTest(requirement=row["name"]):
                    self.assertIn(row["provenance"], corpus.REQUEST_PROVENANCE)
                    self.assertTrue(row["source"].strip())
                    if isinstance(row["value"], (int, float)):
                        self.assertTrue(row["unit"].strip())

    def test_the_committed_corpus_states_no_number_the_reference_measures(self) -> None:
        """The check that operates on the answer instead of on the wording.

        Skipped rather than faked where the corpus is not fetched: a checkout
        that has fetched nothing is ordinary, and asserting a check nobody ran
        is the failure this whole module is about.
        """
        for entry_id in corpus.question_ids(self.payload):
            with self.subTest(entry=entry_id):
                view = corpus.request_view(entry_id, self.payload)
                if not view["checked_against_reference"]:
                    self.skipTest(f"{entry_id} is not on this machine")
                measured = corpus.reference_measurements(entry_id, self.payload)
                declared = {row["measurement"] for row in view["discloses"]}
                undeclared = [(value, name) for value, name
                              in corpus.coincidences(corpus.numbers_in(view),
                                                     measured)
                              if name not in declared]
                self.assertEqual(
                    [], undeclared,
                    "every coincidence the shipped corpus states is one it "
                    "declares in writing, with a reason -- see D30. An "
                    "undeclared one is the leak.")

    def test_the_question_names_no_identifier_path_or_digest(self) -> None:
        for entry_id, row in sorted(corpus._entries(self.payload).items()):
            with self.subTest(entry=entry_id):
                flat = repr(corpus.request_view(entry_id, self.payload))
                for field in ("id", "path", "sha256", "source", "role"):
                    self.assertNotIn(str(row[field]), flat)

    # -- the allowlist ---------------------------------------------------

    def test_a_name_that_measures_no_declared_counterpart_is_refused(self) -> None:
        """Every name a review walked through the denylist with."""
        for name in ("girth", "span", "overall", "size", "dimension",
                     "ht", "wd", "dia", "part_x", "lwh",
                     "bounding_box", "body_count", "thickness_of_part",
                     "part_thickness", "envelope", "envelopes", "bodycount",
                     "ｅｎｖｅｌｏｐｅ"):
            with self.subTest(name=name):
                self._refused(extra=self._req(name=name, value=1.7))

    def test_a_name_that_measures_a_declared_counterpart_is_admitted(self) -> None:
        for name in ("extrusion_slot_opening", "panel_stock", "panel_pocket",
                     "fastener_thread_pitch"):
            with self.subTest(name=name):
                view = corpus.request_view(
                    "voron-deck-support",
                    self._entry(extra=self._req(name=name, value=1.7)))
                self.assertIn(name, [r["name"] for r in view["requirements"]])

    def test_an_entry_declaring_no_counterparts_is_refused(self) -> None:
        """An empty allowlist admits everything, which is the denylist again."""
        with self.assertRaises(corpus.CorpusLeak) as caught:
            corpus.request_view("voron-deck-support",
                                self._entry(counterparts=[]))
        # The *reason* matters. With no counterparts every requirement also
        # fails the allowlist, so a test asserting only that something raised
        # passed with this guard deleted -- it was reading the second failure
        # and calling it the first.
        self.assertIn("counterparts", str(caught.exception))

    # -- the coincidence check -------------------------------------------

    def test_the_leak_this_manifest_shipped_is_refused_unless_declared(self) -> None:
        """`extrusion_series: "2020"` on a part exactly 20.0 mm across.

        A correctly named counterpart, a true statement about the hardware, and
        one of the three answers. Found by a review measuring the STL, not by
        any rule about words -- and no rule about words could have found it.

        It is *stated* now, and declared: `docs/defects.md` D30 records why. The
        part bolts flat to the extrusion face, so refusing the coincidence
        refuses the one thing a designer needs to derive the width. Both halves
        are asserted here, because the mechanism is only honest if the second
        one holds: declared, it passes and the score reports that axis as given;
        undeclared, it is refused exactly as before.
        """
        if not corpus.request_view("voron-deck-support",
                                   self.payload)["checked_against_reference"]:
            self.skipTest("the reference is not on this machine")

        declared = corpus.request_view("voron-deck-support", self.payload)
        self.assertEqual(["extent_x"],
                         [row["measurement"] for row in declared["discloses"]])
        self.assertIn("2020", [str(row["value"])
                               for row in declared["requirements"]])

        payload = copy.deepcopy(self.payload)
        for row in payload["entries"]:
            row.pop("discloses", None)
        with self.assertRaises(corpus.CorpusLeak) as caught:
            corpus.request_view("voron-deck-support", payload)
        self.assertIn("extent_x", str(caught.exception))

    def test_a_measurement_smuggled_into_any_field_is_refused(self) -> None:
        """`names_the_part` scanned two fields of six. This scans the question."""
        if not corpus.request_view("voron-deck-support",
                                   self.payload)["checked_against_reference"]:
            self.skipTest("the reference is not on this machine")
        # Both axes: 5.8 is given away by nothing, and 20.0 is *declared* --
        # which excuses only the number `extrusion_series` states, not this one.
        # These were retargeted off 20.0 while the disclosure excused by name;
        # they are back, because that was the hole rather than the rule.
        for value in (5.8, 20.0):
            with self.subTest(measurement=value):
                self._refused(extra=self._req(
                    source=f"calipers; the part measures {value} across"))
                self._refused(extra=self._req(note=f"about {value} overall"))
                self._refused(request={
                    "purpose": f"Holds a panel. It is {value} mm across."})

    def test_a_value_that_is_not_a_number_or_a_name_is_refused(self) -> None:
        """A list is a bounding box with the brackets left on."""
        for value in ([20.0, 14.5, 5.8], {"x": 20.0}, None, True):
            with self.subTest(value=value):
                self._refused(extra=self._req(value=value, unit=""))

    def test_a_non_string_in_any_text_field_is_refused(self) -> None:
        for field in ("note", "source", "unit", "name"):
            with self.subTest(field=field):
                self._refused(extra=self._req(**{field: [20.0, 14.5]}))

    # -- the rest of the shape -------------------------------------------

    def test_a_provenance_a_requester_could_not_have_is_refused(self) -> None:
        for provenance in ("INHERITED", "CHOSEN", "GUESSED", ""):
            with self.subTest(provenance=provenance):
                self._refused(extra=self._req(provenance=provenance))

    def test_a_number_with_no_unit_and_a_name_with_one_are_both_refused(self) -> None:
        self._refused(extra=self._req(value=1.7, unit=""))
        self._refused(extra=self._req(name="fastener_thread", value="M3", unit="mm"))

    def test_a_measurement_with_no_source_is_refused(self) -> None:
        self._refused(extra=self._req(source=""))

    def test_an_unknown_key_anywhere_is_refused(self) -> None:
        self._refused(request={"bbox": [20.0, 14.5]})
        self._refused(extra={**self._req(), "measured_bbox": [20.0]})

    def test_a_request_missing_either_half_is_refused(self) -> None:
        """Neither half is optional, and neither was covered until a review
        deleted the check and watched every test stay green."""
        for drop in ("purpose", "requirements"):
            with self.subTest(missing=drop):
                payload = self._entry()
                del payload["entries"][0]["request"][drop]
                with self.assertRaises(corpus.CorpusLeak):
                    corpus.request_view("voron-deck-support", payload)

    def test_a_request_with_no_requirements_at_all_is_refused(self) -> None:
        """Unanswerable is not the same as hard."""
        self._refused(request={"requirements": []})

    def test_an_entry_with_no_request_block_is_refused_not_improvised(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["entries"] = [{k: v for k, v in self.payload["entries"][0].items()
                               if k != "request"}]
        with self.assertRaises(corpus.CorpusLeak):
            corpus.request_view("voron-deck-support", payload)

    def test_nothing_a_generator_may_call_can_reach_the_answer(self) -> None:
        """The wall, structurally rather than by convention.

        `tools/fixtures.py:30` records why: withholding a file while disclosing
        its directory is not withholding it, and its public record therefore
        carries no filesystem path at all. This module used to hand out whole
        entry rows through a public `entries()` -- so the reference's path and
        digest sat one `.get("path")` away from the question, and the claim that
        `request_view` was "the only door" was a convention rather than a wall.

        The generator's side of the module is `question_ids` and `request_view`.
        Neither can produce a path, a digest or a source id, whatever it is
        asked for.
        """
        for entry_id in corpus.question_ids(self.payload):
            with self.subTest(entry=entry_id):
                row = corpus._entries(self.payload)[entry_id]
                reachable = repr(corpus.request_view(entry_id, self.payload))
                for field in ("path", "sha256", "source"):
                    self.assertNotIn(str(row[field]), reachable)
        self.assertNotIn("path", repr(corpus.question_ids(self.payload)))

    def test_the_public_surface_a_generator_sees_names_no_location(self) -> None:
        """`entries` is private now, and a test says so rather than a comment.

        A public accessor returning answer material is one refactor from being
        called by the thing it must not be called by.
        """
        self.assertFalse(hasattr(corpus, "entries"),
                         "a public `entries()` returns rows carrying `path` "
                         "and `sha256`; the generator-facing surface is "
                         "`question_ids` and `request_view`")

    def test_a_build_envelope_that_is_not_three_positive_axes_is_refused(self) -> None:
        """Both guards shipped with no fixture; deleting either stayed green."""
        for envelope in ([45.0, 45.0, 25.0], {"x": 45.0, "y": 45.0},
                         {"x": 45.0, "y": 45.0, "z": 25.0, "w": 1.0},
                         {"x": -1.0, "y": 45.0, "z": 25.0},
                         {"x": 0, "y": 45.0, "z": 25.0},
                         {"x": "45", "y": 45.0, "z": 25.0}):
            with self.subTest(envelope=envelope):
                self._refused(request={"build_envelope_mm": envelope})

    def test_an_envelope_that_is_the_references_own_size_is_refused(self) -> None:
        """The envelope is the obvious place to smuggle the answer back in."""
        if not corpus.request_view("voron-deck-support",
                                   self.payload)["checked_against_reference"]:
            self.skipTest("the reference is not on this machine")
        # Both, for the reason above: a declared axis is excused only in the
        # requirement that declares it, and an envelope is never that.
        self._refused(request={"build_envelope_mm":
                               {"x": 45.0, "y": 45.0, "z": 5.8}})
        self._refused(request={"build_envelope_mm":
                               {"x": 20.0, "y": 45.0, "z": 25.0}})

    def test_one_number_that_leaks_two_measurements_reports_both(self) -> None:
        """`coincidences` stopped at the first matching name.

        No committed reference has two near-equal extents, so nothing caught
        this end to end -- and the consequences were both directions of wrong.
        A value within band of two measurements reported one, so the other
        leaked invisibly; and which one you got depended on dict iteration
        order, so an equally true disclosure could be refused as spurious. The
        spurious check now depends on this enumeration being complete.
        """
        measured = {"extent_x": 20.0, "extent_y": 20.3, "extent_z": 5.0,
                    "volume_mm3": 2030.0}
        self.assertEqual(
            [(20.0, "extent_x"), (20.0, "extent_y")],
            list(corpus.coincidences((20.0,), measured)),
            "20.0 is within 2% of both extents and both must be named")
        # And the catalogue-series form reaches all three of them.
        self.assertEqual(
            {"extent_x", "extent_y", "volume_mm3"},
            {n for _, n in corpus.coincidences((2030.0,), measured)})

    def test_a_disclosure_that_gives_away_nothing_is_refused(self) -> None:
        """Otherwise a `discloses` row is an exemption with a reason attached.

        Declare `extent_z` on an entry whose question never states it, and that
        axis is excused for every future edit of the entry -- which is the
        exemption list this whole design replaced. Caught on the first attempt
        at the manifest: I declared the panel clip's extrusion series discloses
        `extent_x`, and measurement says it discloses nothing, because the part
        is 30 mm across and the profile is 20.
        """
        if not corpus.request_view("voron-deck-support",
                                   self.payload)["checked_against_reference"]:
            self.skipTest("the reference is not on this machine")
        with self.assertRaises(corpus.CorpusLeak) as caught:
            corpus.request_view("voron-deck-support", self._entry(
                discloses=[{"requirement": "panel_stock",
                            "measurement": "extent_z",
                            "why": "it does not, and that is the point"}]))
        self.assertIn("gives away nothing", str(caught.exception))

    def test_a_disclosure_with_no_reason_is_refused(self) -> None:
        if not corpus.request_view("voron-deck-support",
                                   self.payload)["checked_against_reference"]:
            self.skipTest("the reference is not on this machine")
        self._refused(discloses=[{"requirement": "extrusion_series",
                                  "measurement": "extent_x", "why": "  "}])

    def test_a_disclosure_naming_no_real_measurement_is_refused(self) -> None:
        if not corpus.request_view("voron-deck-support",
                                   self.payload)["checked_against_reference"]:
            self.skipTest("the reference is not on this machine")
        """By *this* rule, not by the spurious check firing second.

        `_refused` asserts only that some `CorpusLeak` was raised, and with this
        branch deleted the spurious check raises instead and the test stays
        green -- verbatim the failure this file already records for
        `counterparts`: reading the second failure and calling it the first.
        """
        with self.assertRaises(corpus.CorpusLeak) as caught:
            corpus.request_view("voron-deck-support", self._entry(
                discloses=[{"requirement": "extrusion_series",
                            "measurement": "girth", "why": "x"}]))
        self.assertIn("is measured on", str(caught.exception))

    def test_a_disclosure_of_the_wrong_shape_is_refused(self) -> None:
        """The shape check had no fixture at all; deleting it stayed green."""
        if not corpus.request_view("voron-deck-support",
                                   self.payload)["checked_against_reference"]:
            self.skipTest("the reference is not on this machine")
        for row in ("extent_x", ["extent_x"], {}, {"measurement": "extent_x"},
                    {"requirement": "extrusion_series", "measurement": "extent_x"},
                    {"requirement": "extrusion_series", "measurement": "extent_x",
                     "why": "ok", "extra": 1},
                    {"requirement": "", "measurement": "extent_x", "why": "ok"},
                    {"requirement": 3, "measurement": "extent_x", "why": "ok"},
                    {"requirement": "extrusion_series", "measurement": "extent_x",
                     "why": ["20.0", "14.5"]}):
            with self.subTest(row=row):
                self._refused(discloses=[row])

    def test_a_disclosure_excuses_only_the_number_its_requirement_states(self) -> None:
        """The exemption list returning, and the reason it is not.

        Declaring `extent_x` because `extrusion_series: 2020` legitimately gives
        away a 20 mm face used to excuse *every* 20.0 in the entry. A review
        walked four channels through it, and the worst was the build envelope,
        which `blind._project` writes into `project.json` as a hard constraint --
        handing the designer the answer as a rule to obey, which is strictly
        more than the profile the disclosure was argued for.
        """
        if not corpus.request_view("voron-deck-support",
                                   self.payload)["checked_against_reference"]:
            self.skipTest("the reference is not on this machine")
        self._refused(request={"build_envelope_mm":
                               {"x": 20.0, "y": 45.0, "z": 25.0}})
        self._refused(request={"purpose":
                               "Holds a panel. It is 20.0 mm across overall."})
        self._refused(extra=self._req(name="panel_pocket", value=20.0))
        self._refused(extra=self._req(
            source="calipers; the part measures 20.0 across"))
        # And the declared one still passes, or the disclosure does nothing.
        self.assertEqual(
            ["extent_x"],
            [row["measurement"] for row
             in corpus.request_view("voron-deck-support",
                                    self.payload)["discloses"]])

    def test_only_the_declared_measurement_is_excused(self) -> None:
        """A disclosure of one axis does not open the others."""
        if not corpus.request_view("voron-deck-support",
                                   self.payload)["checked_against_reference"]:
            self.skipTest("the reference is not on this machine")
        # extent_x is declared; stating extent_z as well must still be refused.
        self._refused(extra=self._req(name="panel_pocket", value=5.8))

    def test_the_view_says_whether_it_could_check_the_reference(self) -> None:
        """A checkout that has fetched nothing must not imply a check it skipped."""
        payload = copy.deepcopy(self.payload)
        payload["roots"]["default"] = "/nonexistent-corpus-root"
        view = corpus.request_view("voron-deck-support", payload)
        self.assertFalse(view["checked_against_reference"])


if __name__ == "__main__":
    unittest.main()
