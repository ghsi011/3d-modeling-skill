#!/usr/bin/env python3
"""L0-heavy -- the half of `tools/test_blind.py` whose correctness needs the
external reference corpus.

`benchmarks/heavy/README.md` gives the seam: a test belongs here when it starts a
child, needs a corpus or a B-rep, or repeatedly runs a job. Every test in this file
needs the corpus. That is not a subprocess, which is why the file previously called
itself L0 -- the meshes are loaded in process -- but the corpus rule is the more
specific one and it decides.

**Why the move, measured rather than argued.** The reference geometry is fetched
from an external repository, is GPL-3.0-only and is marked `EXTERNAL_ONLY`, so it
is never vendored and never present in CI. On a checkout without it these tests
were *collected* by the commit gate and then skipped: 3 passed and 13 skipped, so
thirteen collected slots bought zero executed assertions in the gate that gates
every push. They now sit in the tier hosted `pre-merge` actually runs
(`uv run pytest benchmarks/heavy -q`), where a corpus could be provisioned and
they would execute in the right place.

Same tests, moved rather than weakened: not one assertion changed, none deleted,
and the scorer untouched. The fast local loop is
`uv run pytest benchmarks/heavy/test_blind_corpus.py -q`, which still costs about
two seconds with a corpus present; full heavy remains the pre-merge proof.

What stayed behind in `tools/test_blind.py` is what answers without the reference:
the asking wall, the request shape, and the refusal when an entry declares no build
envelope.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

# `tools/` goes on the path so the imports below are the *bare* names, and that is
# load-bearing rather than stylistic. `pyproject.toml` puts only `.` and the scripts
# directory on `pythonpath`; a module here cannot do the bare import its L0 half does,
# because that only resolves when pytest prepends a test file's own directory.
#
# The obvious repair -- `from tools import blind, corpus` -- silently breaks one test.
# `tools/blind.py` itself does a bare `import corpus`, so the package spelling produces
# a *second* module object for the same file: `corpus is tools.corpus` is False. A
# `mock.patch.object(corpus, "request_view", ...)` then patches a module `blind` never
# consults, the patch does nothing, and the test fails for a reason that has nothing to
# do with what it is testing. Measured, not guessed: that is exactly how
# `test_a_disclosed_volume_marks_the_volume_row_and_no_extent` failed on the first
# attempt at this move.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import blind  # noqa: E402
import corpus  # noqa: E402

# The fixtures this half shares with the half that stayed behind, imported rather
# than copied: two spellings of one fixture is how two tiers stop testing the same
# thing (`benchmarks/heavy/README.md`). Imported by the same bare name for the same
# module-identity reason as above.
from test_blind import ENTRY, OTHER, _fetched, _written  # noqa: E402


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


class TheWrittenJobNamesNoAnswerTest(unittest.TestCase):
    """The one member of `TheQuestionIsAnswerableAndCarriesNoAnswerTest` that needs
    the reference bytes, and therefore belongs on this side of the seam.

    Its three siblings answer without a corpus and stayed in `tools/test_blind.py`.
    Splitting a class across two tiers is worse to read than keeping it whole, and it
    is still correct: the corpus rule in `benchmarks/heavy/README.md` is an invariant
    about where a test can *run*, and cohesion is a preference about how it reads. The
    first attempt at this move kept the class together and left a corpus-dependent test
    collected-but-skipped in the commit gate, which is the thing the seam exists to
    prevent.
    """

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
            where = _written(Path(raw))
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

