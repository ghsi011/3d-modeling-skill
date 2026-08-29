#!/usr/bin/env python3
"""D34, D35 and D36 are one entry apiece now, not three separate repairs.

Each defect was a role's deliverable and a pipeline write sharing one filename
in one directory. D35 and D36 were closed by moving the pipeline's file and D34
by an existence check with an owner comparison inside `cli._print_plan` --
repairs that each removed one collision and left the condition that produced it,
a shared directory whose names are string literals in whichever module happens
to write them.

The three names are registered in `pipeline/artifact_names.py` instead, so
ownership is a property the registry enforces and the plan generator's bespoke
guard is `default_path`'s refusal.

**Why this file is in `benchmarks/heavy/`, stated plainly because the honest
reason and the tier's stated rule are not the same reason.** These two cases
start no child interpreter, need no corpus, read no B-rep and run no job twice.
By `benchmarks/heavy/README.md`'s own admission rule they belong beside
`pipeline/artifact_names.py` in the commit gate, and both reviewers and the #46
sibling argued exactly that from review-workflow section 5, *tier by behavior,
not by available headroom*. They were right on the merits. What put the file
here is **structure**: `conftest.py`'s `L0_COLLECTED_CEILING` stands at 1440 by
the user's explicit permission, the gate was at 1438, and when the choice was
put to the user between raising the ceiling again and moving these two, the user
chose moving. Declining to raise a ceiling is the same authority that set it.

**The consequence, so nobody has to rediscover it.** These cases no longer run
on every commit. They run in pre-merge with the rest of this tier, so coverage
is preserved and nothing was weakened or deleted -- but the commit gate no
longer carries them, and a local `uv run pytest` will not catch a registry
regression that a `uv run pytest benchmarks/heavy` would.

**This proves the pipeline cannot take a role's deliverable, because each row
fails when that artifact's owner is removed from the registry.** `Y` is one
`register(...)` call replaced by the bare string it returns -- the state every
one of these filenames was in before the registry existed. All three were run
that way; see `benchmarks/mutations/d47-role-artifact-owners.json`. D34
additionally fails `pipeline/test_plan_authority.py`'s survival row under its
own removal, because that is the one of the three whose defective write still
exists in the tree to reproduce: the other two moved to names of their own, so
what removal exposes there is the barrier and not the overwrite. Narrowed here
rather than claimed whole.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pipeline import artifact_names as N

#: Every artifact a role authors that the pipeline shares a directory with, and
#: the role that holds it. Read off the registry's own constants rather than
#: respelled, so a renamed entry cannot leave this file testing a dead string.
ROLE_ARTIFACTS = {
    N.MODEL_SOURCE: N.DESIGNER,             # D35
    N.ARTIFACT_MANIFEST: N.DESIGNER,        # D36
    N.PRINT_PLAN_CHECKS: N.PRINT_ENGINEER,  # D34
}


class TheRoleAuthoredArtifactsAreRegisteredToTheirOwnersTest(unittest.TestCase):

    def test_each_artifact_is_held_by_its_role_and_closed_to_the_pipeline(self) -> None:
        """The registration itself, and both refusals the registry can make.

        `_OWNERS` is read directly because *who holds it* is the fact under
        test; asserting only that something raises would pass equally for a name
        registered to nobody, which is exactly the mutated state.
        """
        for name, role in ROLE_ARTIFACTS.items():
            with self.subTest(artifact=name):
                self.assertEqual(role, N._OWNERS.get(name),
                                 f"{name} is not held by {role}")
                with self.assertRaises(N.NameConflict):
                    N.register(name, owner=N.PIPELINE)
                self.assertEqual(role, N._OWNERS[name],
                                 "the refused claim moved the owner anyway")
                with self.assertRaises(N.NameConflict):
                    N.path(Path("work"), name, owner=N.PIPELINE)

    def test_a_role_artifact_on_disk_refuses_the_pipelines_default(self) -> None:
        """`default_path`, which is what `cli._print_plan` now writes through.

        Presence of the file is the authority boundary, so the seeded file is
        deliberately not a valid contract of any kind: a registry that read the
        content to decide would hand this one back, and *content* is what an
        engineer's half-written plan and a designer's edited `model.py` have no
        guarantees about.

        The absence arm is the control and it observes the same property through
        the same call: without it, refusing every default would satisfy the row
        above while stranding the jobs the generated template exists for.
        """
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            for name in ROLE_ARTIFACTS:
                with self.subTest(artifact=name):
                    self.assertEqual(
                        work / name,
                        N.default_path(work, name, owner=N.PIPELINE),
                        "a name the role has not written was refused anyway")
                    (work / name).write_text("the role wrote this",
                                             encoding="utf-8")
                    with self.assertRaises(N.NameConflict):
                        N.default_path(work, name, owner=N.PIPELINE)
                    self.assertEqual("the role wrote this",
                                     (work / name).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
