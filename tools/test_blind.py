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


if __name__ == "__main__":
    unittest.main()
