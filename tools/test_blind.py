#!/usr/bin/env python3
"""The blind benchmark: the question is answerable, and the score discriminates.

Two properties, and a benchmark that lost either would still produce numbers.

**The question must not contain the answer**, which `tools/test_corpus.py`
covers at the manifest, and which is asserted here at the *generated* artifact
-- the thing a designer is actually handed. A rule enforced on the manifest and
not on its output is a rule about a file nobody reads.

**The score must discriminate.** A scorer that reported agreement whatever it
was given would be indistinguishable from a working one on the only case anybody
runs by hand -- the reference against itself. So the reference scores perfect
against itself, a *different* reference scores off on every dimensional row, and
a rotated copy still scores perfect, because sorted extents are what makes
orientation drop out without registration.

Nothing here builds geometry or starts an interpreter: the corpus meshes are
loaded and measured in-process, which is L0's rule.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import blind
import corpus

ENTRY = "voron-deck-support"
OTHER = "voron-z-belt-clip-upper"


def _fetched(entry_id: str = ENTRY) -> bool:
    try:
        corpus.resolve(entry_id)
    except (corpus.CorpusUnavailable, corpus.CorpusCorrupt):
        return False
    return True


class TheQuestionIsAnswerableAndCarriesNoAnswerTest(unittest.TestCase):

    def _written(self, root: Path) -> Path:
        return blind.write_request(ENTRY, root / "job")

    def test_the_written_job_is_a_project_design_tool_can_be_pointed_at(self) -> None:
        """The generator's output, checked as the pipeline's input.

        `envelope_mm` is the one a blind request could most easily get wrong:
        `design-tool run` refuses to guess it, so it must be present, and it
        must not be the reference's own size.
        """
        from pipeline import project as P

        with tempfile.TemporaryDirectory() as raw:
            where = self._written(Path(raw))
            payload = json.loads((where / "project.json").read_text("utf-8"))
            self.assertEqual({"x", "y", "z"}, set(payload["envelope_mm"]))
            self.assertTrue((where / "brief.md").is_file())

            loaded = P.load(where)
            self.assertEqual("NEW", loaded.source_mode)
            self.assertTrue(loaded.requirements,
                            "a request with no requirements is unanswerable")
            for row in loaded.requirements:
                with self.subTest(requirement=row.name):
                    self.assertEqual([], row.problems())

    def test_the_written_job_names_no_path_digest_or_entry_geometry(self) -> None:
        """`tools/fixtures.py`'s standard, applied here.

        That module's wall searches every staged byte for the reference's path,
        its *name*, and its parent directory. This searched for `path` and
        `sha256` only, and missed the leak that mattered: `project.json` carried
        `job_id: "blind-voron-deck-support"`, which ranks the true reference
        first or second among the hundred and fifty STLs already sitting in the
        corpus root. A wall that stops the path and publishes the filename is
        not a wall.
        """
        if not _fetched():
            self.skipTest("the reference is not on this machine")
        row = corpus._entries()[ENTRY]
        where_it_lives = corpus._location(ENTRY)
        truth = corpus.reference_measurements(ENTRY)

        with tempfile.TemporaryDirectory() as raw:
            where = self._written(Path(raw))
            staged = sorted(p for p in where.rglob("*") if p.is_file())
            self.assertEqual(["brief.md", "project.json"],
                             [p.name for p in staged],
                             "every file written is a file this test reads")
            written = "\n".join(p.read_text("utf-8") for p in staged)

            for token in (row["path"], row["sha256"], ENTRY, row["source"],
                          where_it_lives.name, where_it_lives.stem,
                          where_it_lives.parent.name, str(where_it_lives)):
                with self.subTest(token=token):
                    self.assertNotIn(str(token), written)

            # Parsed, not flattened. `json.dumps` escapes non-ASCII, so an em
            # dash in the brief became `\u2014` and a scan read `2014` -- 20.14,
            # within 2% of this part's 20.0 mm extent. That was serialisation
            # inventing a number, and the first fix for it narrowed the scan to
            # three keys, which then missed a real leak a review planted in a
            # file the narrowed scan no longer read. So: every staged file, each
            # parsed in its own format, with one named exemption.
            scanned = []
            for path in staged:
                if path.suffix == ".json":
                    payload = json.loads(path.read_text("utf-8"))
                    payload.pop("updated_utc", None)   # a fixed epoch, not a measurement
                    scanned.append(payload)
                else:
                    scanned.append(path.read_text("utf-8"))
            declared = {row["measurement"] for row
                        in corpus.request_view(ENTRY)["discloses"]}
            undeclared = [(value, name) for value, name
                          in corpus.coincidences(corpus.numbers_in(scanned), truth)
                          if name not in declared]
            self.assertEqual(
                [], undeclared,
                "a number in the generated job measures the reference and is "
                "not one the entry declares giving away")

    ASKING = ("request", "_project", "_brief", "write_request", "handle", "main")
    MAY_CALL = frozenset({"question_ids", "request_view", "CorpusLeak",
                          "CorpusUnavailable", "CorpusCorrupt",
                          "COINCIDENCE_FRACTION", "resolve",
                          "reference_measurements"})

    def test_the_asking_path_touches_only_the_question_side_of_the_corpus(self) -> None:
        """Every `corpus.<name>` in the module, by AST, not by grepping two
        function bodies.

        The first version of this inspected the source of `request` and
        `_project` -- two of the five functions on the asking path. A review
        added `blind_request.json["reference"] = corpus.reference_measurements(...)`
        to `write_request`, and then wrote the reference mesh itself into the
        job directory, and this test stayed green through both.
        """
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(blind))
        asking = {node.name: node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef) and node.name in self.ASKING}
        self.assertEqual(set(self.ASKING), set(asking),
                         "a function on the asking path was renamed and this "
                         "test stopped covering it")
        for name, node in sorted(asking.items()):
            for inner in ast.walk(node):
                if isinstance(inner, ast.Attribute) and \
                        isinstance(inner.value, ast.Name) and \
                        inner.value.id == "corpus":
                    with self.subTest(function=name, call=inner.attr):
                        self.assertIn(inner.attr, self.MAY_CALL)
                        self.assertNotIn(
                            inner.attr,
                            ("_entries", "_location", "manifest"),
                            "the asking path may not read the manifest rows, "
                            "which carry `path` and `sha256`")

    def test_an_entry_with_no_build_envelope_is_refused_not_invented(self) -> None:
        """Refused by `request_view`, which is where the check belongs.

        A generator that supplied its own envelope would be choosing a
        design-driving value nobody stated, and the obvious source to choose it
        from is the reference -- which is the answer. `blind.request` used to
        carry a second guard for this; a mutation showed it could never fire,
        because `build_envelope_mm` is a required request key and the entry is
        refused one layer earlier. An unreachable check reads as a thing that
        can happen, so it was deleted rather than kept for comfort.
        """
        payload = json.loads(json.dumps(corpus.manifest()))
        for row in payload["entries"]:
            row["request"].pop("build_envelope_mm", None)
        with self.assertRaises(corpus.CorpusLeak):
            blind.request(ENTRY, payload)


class TheScoreDiscriminatesTest(unittest.TestCase):
    """A scorer that always agreed would look right on the case anybody runs."""

    def setUp(self) -> None:
        if not (_fetched(ENTRY) and _fetched(OTHER)):
            self.skipTest("the corpus is not on this machine")

    def test_the_reference_scores_perfect_against_itself(self) -> None:
        report = blind.score(corpus.resolve(ENTRY), ENTRY)
        for row in report["extents"]:
            with self.subTest(axis=row["axis"]):
                self.assertTrue(row["agrees"])
                self.assertEqual(0.0, row["delta_mm"])
        for name in ("volume", "bodies", "watertight"):
            with self.subTest(row=name):
                self.assertTrue(report[name]["agrees"])

    def test_a_different_part_disagrees_on_every_dimensional_row(self) -> None:
        """The control the reference-against-itself case cannot provide."""
        report = blind.score(corpus.resolve(OTHER), ENTRY)
        for row in report["extents"]:
            with self.subTest(axis=row["axis"]):
                self.assertFalse(row["agrees"])
        self.assertFalse(report["volume"]["agrees"])

    def test_orientation_drops_out_without_any_registration(self) -> None:
        """Sorted extents are the whole trick, and this is what buys it.

        A part modelled lying down is the same part. Comparing raw x/y/z would
        call it wrong; comparing the sorted triple does not, and needs no
        fitting to say so.
        """
        import numpy as np
        import trimesh

        mesh = trimesh.load(str(corpus.resolve(ENTRY)), force="mesh")
        mesh.apply_transform(
            trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
        with tempfile.TemporaryDirectory() as raw:
            rotated = Path(raw) / "rotated.stl"
            mesh.export(str(rotated))
            self.assertNotEqual(
                [round(float(v), 3) for v in mesh.bounding_box.extents],
                [round(v, 3) for v in
                 blind.measure(corpus.resolve(ENTRY))["sorted_extents_mm"]],
                "the rotation has to actually move the raw extents, or this "
                "test is asserting nothing")
            report = blind.score(rotated, ENTRY)
        for row in report["extents"]:
            with self.subTest(axis=row["axis"]):
                self.assertTrue(row["agrees"])

    def test_the_report_carries_no_total_and_says_what_it_is_not(self) -> None:
        """8.5's argument against a weighted total, one tier down.

        Rolling "the right size" and "closed solid" into one figure hides which
        of them failed, and which one failed is the answer a reader acts on.
        """
        report = blind.score(corpus.resolve(ENTRY), ENTRY)
        self.assertIsNone(report["score"])
        self.assertIn("nothing about shape", report["what_this_is_not"])

    def _mesh(self, root: Path, name: str, mesh) -> Path:
        path = Path(root) / name
        mesh.export(str(path))
        return path

    def test_a_two_body_candidate_disagrees_on_bodies(self) -> None:
        """Hardcoding this row to True survived the whole suite.

        Every case above uses meshes that agree on `bodies` and `watertight`,
        so half the scored rows had no mutation behind them at all.
        """
        import trimesh

        want = blind.measure(corpus.resolve(ENTRY))
        a, b = (trimesh.creation.box(extents=[4, 4, 4]),
                trimesh.creation.box(extents=[4, 4, 4]))
        b.apply_translation([20, 0, 0])
        with tempfile.TemporaryDirectory() as raw:
            path = self._mesh(raw, "two.stl", a + b)
            report = blind.score(path, ENTRY)
        self.assertEqual(2, report["bodies"]["candidate"])
        self.assertEqual(want["bodies"], report["bodies"]["reference"])
        self.assertFalse(report["bodies"]["agrees"])

    def test_an_open_surface_disagrees_on_watertight_and_reports_no_volume(self) -> None:
        """And the volume row fails closed rather than reporting a number.

        A volume read off an unclosed surface is a divergence sum over a
        boundary that does not close. The first version printed it beside three
        agreements, so a reader took away "right size, right material, needs
        mesh repair" about something that is not a solid.
        """
        import trimesh

        box = trimesh.creation.box(extents=[20.0, 14.4955, 5.8])
        opened = trimesh.Trimesh(vertices=box.vertices, faces=box.faces[:-2])
        with tempfile.TemporaryDirectory() as raw:
            path = self._mesh(raw, "open.stl", opened)
            report = blind.score(path, ENTRY)
        self.assertFalse(report["watertight"]["candidate"])
        self.assertFalse(report["watertight"]["agrees"])
        self.assertIsNone(report["volume"]["agrees"])
        self.assertIsNone(report["volume"]["candidate_mm3"])
        self.assertIn("not a closed solid", report["volume"]["why"])

    def test_a_disclosed_axis_is_reported_as_given_not_reconstructed(self) -> None:
        """`docs/defects.md` D30: some interfaces *are* the answer.

        The deck support bolts flat to a 20 mm extrusion face, so its width is
        the face width. Stating the profile is what lets a designer derive
        anything, and it hands over one of three axes. The score may not then
        count that axis as a reconstruction.
        """
        view = corpus.request_view(ENTRY)
        self.assertEqual(["extent_x"],
                         [d["measurement"] for d in view["discloses"]])
        report = blind.score(corpus.resolve(ENTRY), ENTRY)
        self.assertEqual(["extent_x"], report["given_extents"])
        self.assertFalse(report["given_volume"])
        self.assertEqual(2, report["reconstructed_axes"])
        given = [row for row in report["extents"] if row["given"]]
        self.assertEqual(1, len(given))
        self.assertEqual(20.0, given[0]["reference_mm"],
                         "the disclosure names an axis of the reference and the "
                         "score sorts its extents, so it has to be mapped "
                         "through the same sort -- by value, not by index")

    def test_an_entry_disclosing_nothing_reconstructs_every_axis(self) -> None:
        """A disclosure is a cost, so an entry that pays none keeps all three."""
        report = blind.score(corpus.resolve(OTHER), OTHER)
        self.assertEqual([], report["given_extents"])
        self.assertFalse(report["given_volume"])
        self.assertEqual(3, report["reconstructed_axes"])
        self.assertFalse(any(row["given"] for row in report["extents"]))

    def test_extents_and_volume_are_counted_apart(self) -> None:
        """They were one list, so the summary could say four axes out of three.

        `given_axes` mixed `extent_x` with `volume_mm3`, and a disclosed volume
        marked no row at all -- the volume printed `ok` on a number the question
        had handed over.
        """
        report = blind.score(corpus.resolve(ENTRY), ENTRY)
        self.assertNotIn("volume_mm3", report["given_extents"])
        self.assertIn("given", report["volume"])
        self.assertLessEqual(len(report["given_extents"]), 3)
        self.assertEqual(3 - len(report["given_extents"]),
                         report["reconstructed_axes"])

    def test_a_disclosed_volume_marks_the_volume_row_and_no_extent(self) -> None:
        """No committed entry discloses a volume, so nothing exercised this.

        With extents and volume in one list the summary could report four axes
        out of three, and the volume row printed `ok` on a number the question
        had handed over.
        """
        import unittest.mock as mock

        view = dict(corpus.request_view(ENTRY))
        view["discloses"] = [{"requirement": "panel_stock",
                              "measurement": "volume_mm3", "why": "constructed"}]
        with mock.patch.object(corpus, "request_view", return_value=view):
            report = blind.score(corpus.resolve(ENTRY), ENTRY)
        self.assertEqual([], report["given_extents"],
                         "a volume is not an extent and may not be counted as one")
        self.assertTrue(report["given_volume"])
        self.assertTrue(report["volume"]["given"])
        self.assertEqual(3, report["reconstructed_axes"])
        self.assertFalse(any(row["given"] for row in report["extents"]))

    def test_agreement_is_never_looser_than_the_coincidence_check(self) -> None:
        """The invariant that makes a score mean anything, stated at last.

        `corpus` refuses any question number within `COINCIDENCE_FRACTION` of a
        reference measurement, so agreement can only be won on numbers the
        question did *not* hand over -- but only while the agreement band is no
        wider. A review set `AGREEMENT_FRACTION` to 0.04 and the whole suite
        stayed green, at which point a candidate sized straight off the brief
        scores a dimensional row: the panel clip's stated 6.2 mm slot is 3.33%
        from its own 6.0 mm extent, and the rail guide's stated 25 mm envelope
        is 3.85% from its 26 mm extent. Two constants in two files with nothing
        linking them.
        """
        self.assertLessEqual(blind.AGREEMENT_FRACTION, corpus.COINCIDENCE_FRACTION)

    def test_a_candidate_that_is_not_there_is_a_refusal_not_a_zero(self) -> None:
        """A missing file is the benchmark not having run."""
        with self.assertRaises(blind.BlindError):
            blind.score(Path("/nonexistent/candidate.stl"), ENTRY)


if __name__ == "__main__":
    unittest.main()
