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

import contextlib
import io
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


def _written(root: Path) -> Path:
    """Write the request under `root`, and return where it landed.

    Module-level rather than a method because the corpus-dependent half of this
    class now lives in `benchmarks/heavy/test_blind_corpus.py` and needs it too;
    the heavy directory's rule is that a shared fixture is imported from the half
    that stayed rather than copied into the half that moved.
    """
    return blind.write_request(ENTRY, root / "job")


class TheQuestionIsAnswerableAndCarriesNoAnswerTest(unittest.TestCase):

    ASKING = ("request", "_project", "_brief", "write_request", "handle", "main")
    MAY_CALL = frozenset({"question_ids", "request_view", "CorpusLeak",
                          "CorpusUnavailable", "CorpusCorrupt",
                          "COINCIDENCE_FRACTION", "resolve",
                          "reference_measurements"})

    def test_the_written_job_is_a_project_design_tool_can_be_pointed_at(self) -> None:
        """The generator's output, checked as the pipeline's input.

        `envelope_mm` is the one a blind request could most easily get wrong:
        `design-tool run` refuses to guess it, so it must be present, and it
        must not be the reference's own size.
        """
        from pipeline import project as P

        with tempfile.TemporaryDirectory() as raw:
            where = _written(Path(raw))
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


class TheShapeDescriptorIsIntrinsicTest(unittest.TestCase):
    """Normalised principal inertia: the one descriptor the evidence justified.

    The four dimensional rows -- sorted extents, volume, bodies, watertight -- cannot
    see shape, and `blind.score`'s own report says so. Measured rather than argued: a
    plain slab with one rectangular pocket, sized to the deck-support reference's
    bounding box and volume, passes **every** row while being incapable of the job --
    no lip, no slot tongue, no bolt hole. Judged by the three descriptors proposed for
    it, the per-body Euler tuple matched that impostor exactly and normalised surface
    area sat within 1.7% of it, while the principal moments were 33% to 63% out. So
    inertia is the whole slice: no Euler, no area.

    **Why the expectations here are closed-form.** A solid box of extents a, b, c at
    unit density has mass `V = abc` and principal moments `V(b^2+c^2)/12` and its two
    partners, about the centre of mass. That comes from mechanics, not from this
    repository and not from trimesh, so the assertion can disagree with the code. A
    fixture that compared `measure()` against whatever trimesh returned would be a
    snapshot: green forever, including on the day the normalisation is wrong.

    **Why `V^(5/3)` and not `V`.** With unit density inertia scales as length^5, so
    `I/V` still scales as length^2 -- a second size check wearing a shape descriptor's
    name. `I/V^(5/3)` is dimensionless, which is what makes it say something the
    extents and the volume do not.
    """

    BOX = (20.0, 14.0, 6.0)

    def _analytic(self) -> list[float]:
        a, b, c = self.BOX
        volume = a * b * c
        moments = sorted([volume * (b * b + c * c) / 12.0,
                          volume * (a * a + c * c) / 12.0,
                          volume * (a * a + b * b) / 12.0])
        return [m / volume ** (5.0 / 3.0) for m in moments]

    def test_a_solid_box_matches_its_closed_form_principal_moments(self) -> None:
        import trimesh
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "box.stl"
            trimesh.creation.box(extents=self.BOX).export(path)
            got = blind.measure(path)["inertia_normalised"]
        self.assertEqual(3, len(got))
        self.assertEqual(sorted(got), list(got), "reported sorted, so orientation drops out")
        for want, have in zip(self._analytic(), got):
            self.assertAlmostEqual(want, have, places=6,
                                   msg="the descriptor must agree with mechanics, "
                                       "not merely with whatever the mesh library says")

    def test_the_descriptor_is_scale_free(self) -> None:
        """The property that makes it a *shape* descriptor.

        A box and the same box at ten times the size are the same shape, so a
        dimensionless descriptor has to give the same triple. If this ever fails while
        the test above passes, the normalisation exponent is wrong -- which is exactly
        the mistake `I/V` would have been.
        """
        import trimesh
        with tempfile.TemporaryDirectory() as raw:
            small = Path(raw) / "small.stl"
            large = Path(raw) / "large.stl"
            trimesh.creation.box(extents=self.BOX).export(small)
            trimesh.creation.box(extents=[v * 10 for v in self.BOX]).export(large)
            a = blind.measure(small)["inertia_normalised"]
            b = blind.measure(large)["inertia_normalised"]
        for one, ten in zip(a, b):
            self.assertAlmostEqual(one, ten, places=6)

    def test_a_candidate_with_no_volume_reports_no_descriptor(self) -> None:
        """`I/V^(5/3)` divides by volume, so a non-watertight candidate has none.

        The report already models the idea: `score` prints `--` for the volume of an
        open surface rather than a number nobody can stand behind. The descriptor goes
        one step further and is absent at `measure` time, and the difference is not
        fussiness. An open mesh still has *a* volume -- a defined float, merely
        meaningless -- so `measure` reports it and `score` withholds it. Dividing by
        that volume produces NaN or infinity, which is not a value being withheld but
        no value at all, and a NaN formatted into a table reads exactly like a
        measurement.
        """
        import numpy as np
        import trimesh
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "sheet.stl"
            vertices = np.array([[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0]], float)
            trimesh.Trimesh(vertices=vertices, faces=np.array([[0, 1, 2], [0, 2, 3]]),
                            process=False).export(path)
            got = blind.measure(path)
        self.assertFalse(got["watertight"])
        # `volume_mm3` stays a float here on purpose: `measure` reports what it
        # measured and `score` is what withholds it. Asserting `None` at this seam was
        # my own first draft, and it was a claim about a design this file does not have.
        self.assertIsInstance(got["volume_mm3"], float)
        self.assertIsNone(got["inertia_normalised"])


class TheDefaultReportShowsTheShapeRowTest(unittest.TestCase):
    """What a user actually reads has to carry the new row.

    `--json` is the exception, not the interface: without it `main` prints `_table`,
    so a descriptor computed and put in the payload but never printed is a capability
    the tool has and the reader does not. That is how this nearly shipped -- the row
    was in `score`'s dict, the table still listed four measurements, and nothing in
    either tier looked at the printed output, because `_table` had no test at all.

    The seam under test is report dict in, text out. It is the boundary `main`
    itself uses, so a change to how a score is computed cannot break these, and a
    change to what a reader sees cannot pass them.
    """

    def _report(self, inertia: dict) -> dict:
        """A report with one of everything, so the table has something to print."""
        return {
            "entry_id": "some-entry",
            "extents": [{"axis": "smallest", "candidate_mm": 6.0, "reference_mm": 6.0,
                         "delta_mm": 0.0, "band_mm": 0.12, "agrees": True,
                         "given": False}],
            "volume": {"candidate_mm3": 1680.0, "reference_mm3": 1680.0,
                       "band_mm3": 33.6, "agrees": True, "given": False, "why": None},
            "bodies": {"candidate": 1, "reference": 1, "agrees": True},
            "watertight": {"candidate": True, "reference": True, "agrees": True},
            "inertia": inertia,
            "score": None,
            "reconstructed_axes": 1,
            "given_extents": [],
            "given_volume": False,
            "what_this_is_not": "an intentionally short stand-in.",
        }

    def _printed(self, report: dict) -> str:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            blind._table(report)
        return buffer.getvalue()

    def test_the_moments_reach_the_reader(self) -> None:
        text = self._printed(self._report(
            {"candidate": [0.155925, 0.346678, 0.445786],
             "reference": [0.155925, 0.346678, 0.445786],
             "delta": [0.0, 0.0, 0.0],
             "band": [0.001559, 0.003467, 0.004458],
             "agrees": True}))
        self.assertIn("inertia", text)
        for moment in ("0.155925", "0.346678", "0.445786"):
            self.assertIn(moment, text,
                          msg="a moment that is computed and not printed is a "
                              "measurement the reader never receives")

    def test_a_shape_that_disagrees_is_marked_off(self) -> None:
        """The impostor's own numbers, so the mark under test is the one it earns."""
        text = self._printed(self._report(
            {"candidate": [0.254963, 0.462818, 0.664138],
             "reference": [0.155925, 0.346678, 0.445786],
             "delta": [0.099038, 0.116140, 0.218352],
             "band": [0.001559, 0.003467, 0.004458],
             "agrees": False}))
        self.assertIn("OFF", text)
        self.assertIn("0.254963", text)

    def test_an_unavailable_descriptor_prints_no_number(self) -> None:
        """The volume row's own convention: `--`, and a reason, never a value.

        A `None` formatted into the table would read as a measurement, which is the
        failure the withholding exists to prevent.
        """
        text = self._printed(self._report(
            {"candidate": None, "reference": [0.155925, 0.346678, 0.445786],
             "agrees": None,
             "why": "at least one side has no closed solid to take moments of"}))
        self.assertIn("inertia", text)
        self.assertIn("--", text)
        self.assertNotIn("None", text,
                         msg="`None` printed into a column reads exactly like a "
                             "value; the row must say it has none")
        self.assertIn("no closed solid", text)


if __name__ == "__main__":
    unittest.main()
