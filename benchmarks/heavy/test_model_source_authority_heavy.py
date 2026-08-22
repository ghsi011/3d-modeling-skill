#!/usr/bin/env python3
"""L0-heavy -- D35 proved by building for real, on both certified backends.

These rows execute manifold3d and build123d. The build123d row alone costs 3.7 s
against a 5 s commit-gate ceiling, and the spawn guard in `conftest.py` cannot
see the process-creation mechanisms this pipeline uses, so a real build does not
belong in L0 merely because it fits today. The naming invariant and the binding
resolution -- the parts that can regress silently and cost nothing to check --
stay behind in
`skills/3d-modeling/scripts/pipeline/test_backend_record_name.py`.

D35: a certified backend wrote its build record over the designer's source.

Both certified backends wrote a five-line generated record to
`output_dir / "model.py"` with no existence check, and for an unbranched project
that directory is the project root. `model.py` there is the designer's file: the
designer charter tells a designer on a certified `INCONSEQUENTIAL` `DIRECT` job
to produce it with `dt.py build --out model.py` and then "read it, and edit it".
So the run destroyed the designer's entire deliverable, exited reporting
success, and said nothing.

**The repair is a namespace correction, not an existence check.** The generated
file is not a source; it is the backend's record of what it executed. Refusing
to write it where a designer file already sits would preserve the file and leave
`BuildArtifacts.source_path` pointing at code the backend *did not run* -- so the
manifest's `source_sha256` would then attest that the designer's module produced
this STL, which is a worse claim than the one it replaces. The record gets its
own name, and `source_path` follows it there.

The authored lane is untouched. `backends/authored.py` **adopts** an existing
module and never writes one, so on that lane `source_path` is genuinely the
designer's file and must stay that way.
"""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from pipeline import bindings as B
from pipeline import contract as CT

# Distinctive on purpose: if any assertion below passes while this text is gone,
# the row is measuring something other than survival.
AUTHORED_SOURCE = '''\
# The designer wrote this and edited it, exactly as the charter says to.
DESIGNER_MARKER = "do-not-replace"


def build():
    raise NotImplementedError("designer content")
'''


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


_CLIP = {"bore_d": 12.0, "wall": 3.0, "height": 9.0, "mouth_gap": 9.0,
         "flange_t": 5.0, "screw_d": 4.8, "flange_w": 40.0, "flange_d": 22.0}


def _contract(template: str, backend: str, parameters: dict) -> CT.Contract:
    """The model contract a certified run hands its backend.

    Only `template`, `backend` and `parameters` are read by the two backends
    under test; the rest is the shape `Contract` requires and carries no meaning
    for these rows.
    """
    return CT.Contract(
        job_id="d35", template=template, template_version="1.0.0",
        domain_id=None, backend=backend, parameters=dict(parameters),
        features=(), expected_bbox_mm={"x": 0.0, "y": 0.0, "z": 0.0},
        bbox_tolerance_mm=0.5, expected_bodies=1,
        orientation={"model_to_printer": "identity", "bed_z_mm": 0.0},
        material={"process": "FDM", "material": "PLA"},
        nozzle={"diameter_mm": 0.4}, printer="Test Printer", modifiers=(),
        minimum_coverage=0.0, step_required=False,
        consequence="INCONSEQUENTIAL", updated_utc="1970-01-01T00:00:00Z")


class _CertifiedBackendCase(unittest.TestCase):
    """Shared rows, run once per certified backend.

    Both backends carried the same three lines of the same defect, so proving it
    on one and asserting the other by inspection would leave half the production
    surface untested -- and they are separate files that have already drifted
    from each other once (their generated records differ by a word).
    """

    backend_name: str = ""
    template: str = ""
    parameters: dict = {}

    def _backend(self):
        from pipeline import backends
        return backends.get(self.backend_name)

    def _build(self, output_dir: Path):
        return self._backend().build(
            _contract(self.template, self.backend_name, self.parameters),
            output_dir)

    def test_a_designer_authored_model_survives_the_build(self) -> None:
        """**The defect.** Byte-identical, not merely present."""
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            model = out / B.DEFAULT_SOURCE
            model.write_text(AUTHORED_SOURCE, encoding="utf-8")
            before = model.read_bytes()
            self._build(out)
            after = model.read_bytes()
        self.assertEqual(before, after,
                         "the certified backend overwrote the designer's source")

    def test_the_record_does_not_claim_to_be_the_source_that_ran(self) -> None:
        """The false repair this rules out: preserving `model.py` and still
        pointing `source_path` at it would make the manifest attest that the
        designer's module produced this STL. The backend executed a template."""
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            (out / B.DEFAULT_SOURCE).write_text(AUTHORED_SOURCE, encoding="utf-8")
            built = self._build(out)
            self.assertNotEqual(out / B.DEFAULT_SOURCE, built.source_path)
            self.assertEqual(out / B.BACKEND_RECORD, built.source_path)
            self.assertNotEqual(_sha(out / B.DEFAULT_SOURCE), _sha(built.source_path))

    def test_the_record_says_what_the_backend_actually_executed(self) -> None:
        """A record that survives while describing nothing is not evidence.

        Read as JSON rather than searched as text, because the record is a
        receipt now: a substring check would pass on a file that merely mentions
        the template somewhere."""
        import json
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            built = self._build(out)
            record = json.loads(built.source_path.read_text(encoding="utf-8"))
        self.assertEqual(self.template, record["template"])
        self.assertEqual(self.backend_name, record["backend"])
        self.assertEqual(self.parameters, record["parameters"])
        self.assertEqual(B.BACKEND_RECORD_SCHEMA, record["schema_version"])

    def test_a_designer_helper_under_the_records_name_survives(self) -> None:
        """**The defect the first repair moved rather than ended.**

        `isolation._stage` stages every top-level `*.py` beside the model as the
        designer's, on the stated ground that "the pipeline writes no Python
        into a project directory, so every `.py` there is the designer's". A
        record named `backend_build_record.py` broke exactly that invariant: a
        designer shipping a helper under that name would have lost it to the
        same write, for the same reason `model.py` was lost.

        So the record is a `.json` receipt. Nothing executes it, and the
        extension is what stops it claiming an ownership it does not have.
        """
        helper = "backend_build_record.py"
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            (out / helper).write_text(AUTHORED_SOURCE, encoding="utf-8")
            before = (out / helper).read_bytes()
            built = self._build(out)
            after = (out / helper).read_bytes()
            self.assertTrue(built.source_path.is_file())
            self.assertNotEqual(out / helper, built.source_path)
        self.assertEqual(before, after,
                         "the record destroyed a designer helper of that name")

    def test_the_record_is_not_python(self) -> None:
        """Stated on its own because the extension IS the repair: a `.py` record
        under any name re-enters the namespace the boundary treats as the
        designer's."""
        self.assertFalse(B.BACKEND_RECORD.endswith(".py"), B.BACKEND_RECORD)

    def test_a_job_with_no_designer_source_still_gets_its_record(self) -> None:
        """**The control, and it passes in both builds.** Without it, "stop
        writing the record" would satisfy every row above while destroying the
        only account of what the backend ran."""
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            built = self._build(out)
            self.assertTrue(built.source_path.is_file())
            self.assertFalse((out / B.DEFAULT_SOURCE).exists(),
                             "the backend still writes to the designer's path")

    def test_the_record_is_not_the_designers_filename(self) -> None:
        """Stated as its own row because it is the whole repair. A rename that
        happened to collide with `model.py` again would pass every other row."""
        self.assertNotEqual(B.DEFAULT_SOURCE, B.BACKEND_RECORD)


class TrimeshManifoldRecordTest(_CertifiedBackendCase):
    backend_name = "trimesh-manifold"
    template = "c_clip"
    parameters = _CLIP


class Build123dRecordTest(_CertifiedBackendCase):
    backend_name = "build123d"
    template = "trim_ring"
    parameters = {"hole_d": 20.0, "lip_w": 3.0, "panel_t": 2.0,
                  "lip_t": 1.5, "wall": 1.6, "chamfer": 0.6}


# The base class is a fixture, not a test: unittest would otherwise collect its
# rows a third time with no backend name and fail on the lookup.
del _CertifiedBackendCase


if __name__ == "__main__":
    unittest.main()


class TheManifestBindsTheRecordAndNotTheDesignersFileTest(unittest.TestCase):
    """**The claim the whole namespace correction exists to make honest.**

    The rows above prove the backend writes elsewhere. This proves the receipt
    followed it. `artifact_manifest.json`'s `source_sha256` is what says "this is
    the source that produced this STL", and it travels into both review
    envelopes, `final_status.json`'s `artifact_hashes.source`, and the `source`
    binding every receipt is checked on.

    So the false repair is exactly here: preserve the designer's `model.py`,
    leave `source_path` pointing at it, and this digest becomes an attestation
    that their module built a part a certified template built. The file survives
    and the receipt lies -- which is worse than the destruction, because nothing
    looks wrong.
    """

    def _run(self, seed_designer_source: bool):
        import json
        from pipeline import cli
        from pipeline.test_execution_plan import _laid_out, _project

        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), _project())
            model = directory / B.DEFAULT_SOURCE
            if seed_designer_source:
                model.write_text(AUTHORED_SOURCE, encoding="utf-8")
            cli.run([str(directory), "--no-render"])
            manifest = json.loads(
                (directory / "artifact_manifest.json").read_text(encoding="utf-8"))
            record = directory / B.BACKEND_RECORD
            return {
                "bound": manifest["source_sha256"],
                "record_sha": _sha(record) if record.is_file() else None,
                "model_sha": _sha(model) if model.is_file() else None,
                "model_text": model.read_text(encoding="utf-8") if model.is_file() else None,
                "binding": B.current(directory)["source"],
            }

    def test_the_manifest_hashes_the_record_while_the_designer_file_survives(self) -> None:
        seen = self._run(seed_designer_source=True)
        self.assertEqual(AUTHORED_SOURCE, seen["model_text"],
                         "the certified run overwrote the designer's source")
        self.assertEqual(seen["record_sha"], seen["bound"])
        self.assertNotEqual(seen["model_sha"], seen["bound"],
                            "the manifest attests the designer's module built this")

    def test_the_source_binding_agrees_with_the_manifest(self) -> None:
        """`bindings.current()` re-derives the binding from a *filename* rather
        than from the manifest, so the two can disagree silently. On the
        certified lane nothing but the fallback names the source, which is
        exactly how a rename could leave this `None` with no test going red."""
        seen = self._run(seed_designer_source=True)
        self.assertIsNotNone(seen["binding"], "the source binding went unreadable")
        self.assertEqual(seen["bound"], seen["binding"])

    def test_a_certified_job_with_no_designer_file_is_unaffected(self) -> None:
        """**The control.** The ordinary certified job, which is most of them."""
        seen = self._run(seed_designer_source=False)
        self.assertIsNone(seen["model_sha"], "the run wrote to the designer's path")
        self.assertEqual(seen["record_sha"], seen["bound"])
        self.assertEqual(seen["bound"], seen["binding"])
