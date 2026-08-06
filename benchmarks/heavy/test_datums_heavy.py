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

import os
import subprocess
import sys
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
