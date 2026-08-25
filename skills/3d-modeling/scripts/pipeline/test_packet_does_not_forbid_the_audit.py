#!/usr/bin/env python3
"""The verification packet must not tell the verifier to skip verifying.

`build_packet` used to hand the reader this task:

    "The numbers below were measured deterministically and are not in dispute
     -- do not recompute them."

`roles/verifier.md`, the charter the same dispatch tells that reader to follow
exactly, says the opposite in four places: *audits upstream measurements and all
seven exported-STL checks*; *audit upstream: independently compare*; *an
independent recomputation compared check-by-check*; and, giving the reason,
*independently of the toolkit's, so a silent disagreement between them is the
cheapest bug*.

Two authorities, one role, opposite instructions about the one thing the role
exists to do.

**The charter is the one that is right.** A verdict that trusts the numbers it is
auditing is not a second opinion. The observed verifier resolved the conflict
correctly -- 13% of its calls re-measure the mesh -- so the damage was never a
wrong verdict. It was a latent hazard: a verifier that had obeyed the packet
would have returned a decision fast and hollow, and nothing downstream would have
caught it, because the report still parses, still carries a decision, and still
binds.

This also closes off an attractive shortcut. The cheapest way to make the
verifier fast is to have it judge the pipeline's numbers instead of re-deriving
them -- and the packet was inviting exactly that. It is barred: that
re-derivation *is* the acceptance independence, so verifier speed has to come out
of its orientation and never out of its measurement.
"""
from __future__ import annotations

import unittest

from . import verification


def _task() -> str:
    packet = verification.build_packet(
        brief="a bracket", intent={}, contract={}, artifact={}, commission={},
        witness={})
    return packet.payload["task"]


class ThePacketDoesNotForbidRecomputationTest(unittest.TestCase):

    def test_it_does_not_tell_the_verifier_to_skip_recomputing(self) -> None:
        task = _task().lower()
        self.assertNotIn("do not recompute", task)
        self.assertNotIn("not in dispute", task)

    def test_it_asks_for_an_independent_re_derivation(self) -> None:
        """The charter's word, in the packet's mouth."""
        task = _task().lower()
        self.assertIn("independent", task)
        self.assertIn("re-derive", task)

    def test_a_disagreement_is_named_as_a_finding(self) -> None:
        """Line 180 of the charter is why this exists: a silent disagreement
        between two independent measurements is the cheapest bug in the system,
        and only a verifier that expects to find one will report it."""
        self.assertIn("disagreement", _task().lower())

    def test_the_numbers_are_still_supplied(self) -> None:
        """**The control.** A re-derivation nobody can compare against is not an
        audit either. Withholding the measurements would be the opposite error,
        and this row fails if the fix drifts that way."""
        packet = verification.build_packet(
            brief="a bracket", intent={"i": 1}, contract={"c": 2},
            artifact={"a": 3}, commission={"m": 4}, witness={"w": 5})
        for key in ("model_contract", "artifact_manifest", "commission_report",
                    "witness"):
            with self.subTest(key=key):
                self.assertIn(key, packet.payload)
        self.assertEqual({"m": 4}, packet.payload["commission_report"])


if __name__ == "__main__":
    unittest.main()
