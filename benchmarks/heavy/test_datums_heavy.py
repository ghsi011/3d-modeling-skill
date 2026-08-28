"""D31's cross-process property, which costs an interpreter to check.

The L0 half of this lives in `pipeline/test_datums.py` and asserts that the
canonical datum block is ordered by `datum_id`. It exists because a mutation
survived: removing `sorted()` from the block passed every reordering fixture,
since the referenced ids are collected into a *set* and a set has already
discarded declaration order. Two projects differing only in that order iterate
identically inside one process.

What no single-process test can see is that a set's iteration order is a function
of `PYTHONHASHSEED`. Unsorted, one project would serialize differently in two
interpreters, which ends two properties the pipeline is built on: a rerun on
unchanged inputs is byte-identical (`cli` requires `--updated-utc` from the caller
precisely so nothing in a receipt moves when nothing about the job did), and a
clean clone reproduces the same identity. Both are statements about *different
processes*, so proving them takes two.

This is in the heavy tier rather than the commit gate for the reason
`benchmarks/heavy/README.md` gives: it starts child interpreters. It is cheap as
heavy tests go -- two short-lived children, no CAD kernel, no build -- but it is
still a process, and the L0 budget is a wall clock somebody has to trust.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

SCRIPTS_DIR = (Path(__file__).resolve().parents[2]
               / "skills" / "3d-modeling" / "scripts")

# Eight ids whose sorted order is not their declaration order. Under the mutation
# the block's order is the set's, so the probability that two different hash seeds
# agree is small; with `sorted()` the answer cannot depend on the seed at all.
CHILD = """
import json
import sys

sys.path.insert(0, %r)

from pipeline import cli
from pipeline import project as P

datums = tuple(
    P.Datum(datum_id=name, value=12.4, unit="mm", provenance="MEASURED",
            derived_from=None, valid_for=("src",), note="")
    for name in ("zeta", "alpha", "mid", "beta", "yankee", "delta", "kilo", "omega"))

scope = P.EditScope(artifact_id="src", region="pocket",
                    datum_ids=tuple(d.datum_id for d in datums))
project = P.Project(job_id="d31", updated_utc="1970-01-01T00:00:00Z",
                    source_mode="MODIFY", consequence="INCONSEQUENTIAL",
                    brief="request.md", datums=datums, edit_scopes=(scope,))

print(json.dumps({
    "order": [row["datum_id"] for row in cli._referenced_datums(project)],
    "digest": cli._requirement_hash(project, "0" * 64),
}))
"""


def _in_child(seed: str) -> dict:
    env = dict(os.environ, PYTHONHASHSEED=seed)
    done = subprocess.run([sys.executable, "-c", CHILD % str(SCRIPTS_DIR)],
                          capture_output=True, text=True, check=False, env=env)
    assert done.returncode == 0, done.stderr
    import json

    return json.loads(done.stdout)


def test_the_bound_datum_order_does_not_depend_on_the_hash_seed() -> None:
    """Two interpreters, two seeds, one answer.

    Asserted on the order *and* the digest. The order is what a reader can act on
    when this fails, and the digest is the thing the contract actually carries --
    a test that compared only the order would pass an implementation that sorted
    the block and then serialized something else.
    """
    first = _in_child("0")
    second = _in_child("1")
    expected = ["alpha", "beta", "delta", "kilo", "mid", "omega", "yankee", "zeta"]

    assert first["order"] == expected, (
        "the block must be ordered by datum_id, not by set iteration order under "
        f"this child's hash seed: {first['order']}")
    assert first["order"] == second["order"], (
        "two hash seeds disagreed about the order, so the serialization is a "
        "function of the interpreter and not of the job")
    assert first["digest"] == second["digest"], (
        "two hash seeds produced different requirement digests, which ends "
        "byte-identical reruns and clean-clone reproduction")


# ---------------------------------------------------------------------------
# D31's own recorded closure fixture, driven rather than composed
# ---------------------------------------------------------------------------
#
# `docs/defects.md` D31 names the fixture that must fail before the fix lands:
# *"A project whose scope names one datum, run to a frozen contract; the datum's
# value changed with its id kept; the contract re-derived. The test must show the
# requirement hash moved and the stored review answer refused."*
#
# The unit tests in `pipeline/test_datums.py` prove the hash moves, and they prove
# the refusal only by composition -- the envelope carries `contract_sha256`, and
# `review.is_bound` refuses a mismatch, so a moved contract must refuse. True, and
# an argument rather than a measurement. This runs the job.
#
# It lives here rather than in the commit gate for the reason
# `benchmarks/heavy/README.md` draws the seam: a full run builds geometry in a
# confined child. `benchmarks/heavy/test_bindings_heavy.py` already holds the
# invalidation tests moved out of L0 for the same cost reason, so this is the
# consistent home for a full-run invalidation fixture.

MODEL = '''
import trimesh

PARAMS = {"w": 40.0, "d": 30.0, "h": 10.0}


def build():
    block = trimesh.creation.box(extents=(40.0, 30.0, 10.0))
    block.apply_translation((20.0, 15.0, 5.0))
    return block
'''

PROPOSAL = {
    "schema_version": 1,
    "job_id": "d31-closure",
    "design_id": "seated-block",
    "rationale": "a block seated against the measured pocket face",
    "params": {"w": 40.0, "d": 30.0, "h": 10.0},
    "bbox_mm": {"x": 40.0, "y": 30.0, "z": 10.0},
    "bodies": 1,
    "profile_marks": {"z": []},
    "features": [
        {"feature_id": "block-section", "kind": "section_area",
         "at": {"z": 5.0}, "value_mm2": 1200.0},
        {"feature_id": "bed-footprint", "kind": "bed_contact",
         "value_mm2": 1200.0},
    ],
}

UTC = "1970-01-01T00:00:00Z"


def _project(P, value: float):
    """A MODIFY job whose single edit scope is placed against one datum.

    MODIFY, and necessarily so: a `Datum` is reachable only through
    `EditScope.datum_ids`, so there is no lane on which a datum is referenced and
    the edit-scope cap does not apply. The run therefore ends
    `EXPERIMENTAL_UNAVAILABLE`, which is the cap doing its job and is asserted
    rather than worked around -- the receipts, the contract and the review
    envelope are all still written, and they are the subject here.
    """
    return P.Project(
        job_id="d31-closure", updated_utc=UTC, source_mode="MODIFY",
        consequence="INCONSEQUENTIAL",
        consequence_rationale="a desk block; failure wastes material",
        printer="Test Printer", material={"process": "FDM", "material": "PLA"},
        nozzle={"diameter_mm": 0.4},
        orientation={"model_to_printer_matrix": "identity", "bed_z_mm": 0.0},
        template=None, parameters={}, model="model.py",
        envelope_mm={"x": 60.0, "y": 50.0, "z": 20.0},
        reviewer={"model_snapshot": "test"},
        verification_requested=True,
        source_artifacts=(P.SourceArtifact(
            artifact_id="src", path="source.stl", format="STL",
            classification="USABLE_MESH"),),
        datums=(P.Datum(datum_id="pocket-face", value=value, unit="mm",
                        provenance="MEASURED", derived_from=None,
                        valid_for=("src",), note=""),),
        edit_scopes=(P.EditScope(
            artifact_id="src", region="the pocket face",
            region_box={"min": [0.0, 0.0, 0.0], "max": [5.0, 5.0, 5.0]},
            datum_ids=("pocket-face",), mesh_fallback_allowed=True,
            preserve=("everything outside the pocket",)),),
    )


def _answer(cli, R, S, work: Path) -> str:
    """Store the reviewer's PASS, echoing the packet's own envelope back.

    Returns the stored envelope's own `digest()`, which is what
    `review.validate_response_envelope` compares and therefore what the refusal
    below names. It is deliberately not `contract_sha256`: the envelope digest
    covers the whole envelope, so asserting on it proves the refusal is about
    *this* answer rather than about some hash that happens to appear in the
    output.
    """
    packet = json.loads((work / cli.REVIEW_DIR / "verification_packet.json")
                        .read_text(encoding="utf-8"))
    envelope = packet["review_envelope"]
    (work / cli.REVIEW_DIR / "verification_response.json").write_text(
        S.canonical_json({
            "decision": "PASS", "defects": [], "unmet_requirements": [],
            "missing_evidence": [], "summary": "nothing undeclared visible",
            "review_envelope": envelope}), encoding="utf-8")
    return R.envelope_from_response({"review_envelope": envelope}).digest()


def test_changing_a_referenced_datum_refuses_the_stored_review_answer() -> None:
    sys.path.insert(0, str(SCRIPTS_DIR))
    import trimesh

    from pipeline import acceptance as ACC
    from pipeline import cli
    from pipeline import project as P
    from pipeline import review as R
    from pipeline import schemas as S

    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw) / "project"
        work.mkdir(parents=True)
        (work / "brief.md").write_text("seat a block against the pocket face\n",
                                       encoding="utf-8")
        trimesh.creation.box(extents=(20.0, 20.0, 20.0)).export(work / "source.stl")
        (work / "model.py").write_text(textwrap.dedent(MODEL), encoding="utf-8")
        (work / ACC.PROPOSAL_FILE).write_text(S.canonical_json(PROPOSAL),
                                              encoding="utf-8")
        _project(P, 12.4).save(work)

        # ---- run to a frozen contract with a stored answer bound to it -------
        cli.run([str(work), "--no-render"])
        bound_to = _answer(cli, R, S, work)
        cli.run([str(work), "--no-render"])

        contract = json.loads((work / ACC.ACCEPTANCE_FILE)
                              .read_text(encoding="utf-8"))
        assert contract["revision"] == 1, contract["revision"]
        assert (work / "pipeline_verification_report.json").is_file(), (
            "the stored answer has to have produced a receipt, or there is "
            "nothing for the change below to invalidate")
        status = json.loads((work / "final_status.json").read_text(encoding="utf-8"))
        assert status["lane_status"] == "EXPERIMENTAL_UNAVAILABLE", (
            "an edit-scope job must still be capped; D31 makes the binding "
            f"correct and lifts nothing, but this run says {status['lane_status']}")

        # The bytes of the receipt that the datum correction must remove, taken
        # while it is still the current one. Compared after the rerun below.
        before_digest = S.sha256_file(work / "pipeline_verification_report.json")

        # ---- the datum's value is corrected, its id kept --------------------
        _project(P, 12.9).save(work)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            cli.run([str(work), "--no-render"])
        said = stderr.getvalue()

        contract = json.loads((work / ACC.ACCEPTANCE_FILE)
                              .read_text(encoding="utf-8"))
        assert contract["revision"] == 2, (
            "correcting a referenced datum must cut a new acceptance revision, "
            f"and the contract is still at {contract['revision']}")

        history = json.loads((work / ACC.HISTORY_FILE).read_text(encoding="utf-8"))
        entry = history["revisions"][-1]

        # Exactly one field moved, and it is the requirement hash. Asserted as a
        # whole list rather than with `any(...)`: the point of a dependency-scoped
        # binding is that a datum correction moves the identity and *nothing else*,
        # and a substring search over the changes would pass just as happily if
        # half the contract had moved with it.
        assert len(entry["changed"]) == 1 and \
            entry["changed"][0].startswith("requirement_sha256:"), entry["changed"]

        invalidated = entry["supersedes"]["invalidated_receipts"]
        assert "pipeline_verification_report.json" in invalidated, (
            "the review receipt issued against revision 1 must be invalidated "
            f"through the existing graph; removed: {sorted(invalidated)}")
        assert "final_status.json" in invalidated, (
            "and the job's answer with it, since it rested on that review")

        # The history must name the bytes it removed, not just the filename. This
        # is the one half of the deletion claim this test can honestly carry.
        assert invalidated["pipeline_verification_report.json"]["sha256"] == before_digest, (
            "the history must record the digest of the receipt it removed; it "
            f"recorded {invalidated['pipeline_verification_report.json']['sha256'][:12]} "
            f"and the receipt was {before_digest[:12]}")

        # Whether the file was *unlinked* is deliberately NOT asserted here, and
        # the reason is worth writing down because the obvious assertion is a trap.
        #
        # An independent review pointed out that the checks above read only the
        # history, which `acceptance.freeze` writes from `bindings.invalidate`'s
        # return value -- so deleting `path.unlink()` from `invalidate` would leave
        # them green. Correct. But asserting absence, or a changed digest, here does
        # not close it: this run *regenerates* `pipeline_verification_report.json` after the
        # freeze -- as an error report recording the refusal -- so the revision-1
        # bytes are gone from disk either way and any such assertion passes under
        # the mutation too. Measured, not assumed: the mutation survived that
        # assertion, which is why it is not in this file.
        #
        # Deletion is `bindings.invalidate`'s own contract and is owned where it
        # belongs -- `benchmarks/heavy/test_bindings_heavy.py::ScopedInvalidationTest`
        # asserts both that a receipt is reported removed and that it is no longer
        # on disk. Verified against the same mutation: removing `path.unlink()`
        # fails two tests there. Re-asserting it here would be a second authority
        # over one question, and the version of it that fits this fixture cannot
        # fail.


        # The refusal itself, which is the half the unit tests could only argue.
        #
        # One review called the message assertions brittle and suggested dropping
        # them, since the structural checks above already prove the invalidation.
        # Kept deliberately, because they prove a different thing: that the stored
        # answer was *refused* rather than quietly re-used against the new
        # contract. Nothing above would notice a run that accepted it. Brittleness
        # to a reworded refusal is the intended cost -- rewording the sentence a
        # reader relies on should make somebody re-read this test.
        assert "review envelope mismatch" in said, (
            "the stored response must be refused rather than reused against the "
            f"new contract. stderr was: {said[-600:]}")
        assert bound_to[:16] in said, (
            "and the refusal must name the envelope the answer was issued "
            f"against ({bound_to[:16]}); stderr was: {said[-600:]}")
