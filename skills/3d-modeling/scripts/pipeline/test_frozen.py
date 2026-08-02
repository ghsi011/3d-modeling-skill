#!/usr/bin/env python3
"""Phase 0: what "unchanged" means, written down before anything moves.

The consolidation in `docs/adr/0001-one-project-one-cli.md` adds a route, a
canonical project file and a single CLI. Its first acceptance goal is that
`DIRECT` does not become slower, more expensive, or different -- and "different"
is not a thing you can check against a memory of last week's output. So it is
checked against these literals.

Three kinds of golden live here, chosen because each fails for a different
reason:

* **Contract hashes.** Derived from the template's declared parameters,
  expectations and envelope -- never from a mesh -- so they are independent of
  the trimesh, manifold3d and build123d versions installed. A change here means
  a certified template's *contract* moved, which the scope controls forbid
  without evidence of a defect.
* **Route decisions.** In-domain and out-of-domain, with the deciding condition.
  Routing had no regression surface at all until `intent.py` started recording
  its candidates; this pins the answers a project-level router must keep giving.
* **Artifact inventories and final status.** The set of receipts a route
  produces, and the claim it is allowed to make. A route that silently stops
  writing a receipt is exactly the failure the migration could introduce.

Mesh hashes are deliberately *not* frozen: they move with a tessellator version
and would turn a dependency bump into a false alarm about the part.

The half of this file the commit gate will not carry is in
`benchmarks/heavy/test_frozen_heavy.py`, and runs before merge instead of on
every push: `FrozenRunTest`, `ShippedSelftestTest`. Same tests, moved rather
than weakened; `conftest.py` carries the rule and `benchmarks/heavy/README.md`
the measurement behind it.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from . import intent, runner, selftest, templates as T
from . import schemas as S

# The goldens live in `selftest.py`, which ships inside the bundle. Two copies of
# a golden is two goldens, and the one nobody runs is the one that drifts.
FROZEN_PARAMETERS = selftest.FROZEN_PARAMETERS
FROZEN_CONTRACTS = selftest.FROZEN_CONTRACTS
FROZEN_ARTIFACTS = {route: set(names) for route, names in selftest.FROZEN_ARTIFACTS.items()}

TEST_PRINTER = selftest.SELFTEST_PRINTER
TEST_MATERIAL = selftest.SELFTEST_MATERIAL
TEST_NOZZLE = selftest.SELFTEST_NOZZLE
TEST_ORIENTATION = selftest.SELFTEST_ORIENTATION
FROZEN_UTC = selftest.SELFTEST_UTC
FROZEN_JOB_ID = selftest.SELFTEST_JOB_ID


def _request(out: Path, template: str, **kw) -> runner.JobRequest:
    params = dict(kw.pop("params", None) or FROZEN_PARAMETERS[template])
    consequence = kw.pop("consequence", "INCONSEQUENTIAL")
    return runner.JobRequest(
        job_id=FROZEN_JOB_ID, brief_path=out / "brief.md", template=template,
        parameters=params, stated=frozenset(), consequence=consequence,
        out_dir=out, updated_utc=FROZEN_UTC, render=False, printer=TEST_PRINTER,
        material=dict(TEST_MATERIAL), nozzle=dict(TEST_NOZZLE),
        orientation=dict(TEST_ORIENTATION), **kw)


def _passing_review(packet):
    payload = getattr(packet, "payload", packet)
    response = {"decision": "PASS", "defects": [], "unmet_requirements": [],
                "missing_evidence": [], "summary": "nothing undeclared visible"}
    if isinstance(payload, dict) and "review_envelope" in payload:
        response["review_envelope"] = payload["review_envelope"]
    return response


def _spec(request):
    response = {
        "measurements": [{"feature": "bundle_across", "nominal_mm": 12.4,
                          "uncertainty_mm": 0.05, "method": "caliper",
                          "datum": "widest section", "confidence": "A"}],
        "interfaces": [{"interface_id": "channel", "measurement": "bundle_across",
                        "fit_class": "slip"}],
        "unresolved": [],
    }
    if "review_envelope" in request:
        response["review_envelope"] = request["review_envelope"]
    return response


class FrozenContractsTest(unittest.TestCase):
    """The certified contracts, by hash, before any consolidation moves them."""

    def test_every_certified_template_still_writes_its_frozen_contract(self) -> None:
        self.assertEqual(sorted(FROZEN_CONTRACTS), sorted(T.registry()),
                         "the certified registry changed shape; a template added or "
                         "removed is an architecture decision, not a refactor")
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            for name, expected in sorted(FROZEN_CONTRACTS.items()):
                with self.subTest(template=name):
                    contract = runner._contract_from(T.get(name), _request(out, name))
                    self.assertEqual(expected["contract_sha256"],
                                     contract.contract_hash(),
                                     f"{name}'s contract hash moved. Nothing in the "
                                     "consolidation may change a certified template's "
                                     "contract without evidence of a defect.")
                    self.assertEqual(expected["backend"], contract.backend)
                    self.assertEqual(expected["features"], len(contract.features))
                    self.assertEqual(expected["bbox"], contract.expected_bbox_mm)

    def test_the_contract_payload_is_byte_stable_across_two_builds(self) -> None:
        """Hashing proves nothing if two runs of one job disagree on the bytes."""
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw)
            for name in sorted(FROZEN_PARAMETERS):
                with self.subTest(template=name):
                    first = runner._contract_from(T.get(name), _request(out, name))
                    second = runner._contract_from(T.get(name), _request(out, name))
                    self.assertEqual(S.canonical_json(first.as_payload()),
                                     S.canonical_json(second.as_payload()))


class FrozenRoutingTest(unittest.TestCase):
    """The route answers a project-level router has to keep giving."""

    def test_every_certified_template_in_domain_routes_direct(self) -> None:
        for name, params in sorted(FROZEN_PARAMETERS.items()):
            with self.subTest(template=name):
                decision = intent.select(requested_template=name, parameters=params,
                                         external_geometry=False, ambiguities=())
                self.assertEqual("DIRECT", decision.route)
                self.assertEqual(name, decision.template)

    def test_out_of_domain_names_the_parameter_and_the_bound(self) -> None:
        decision = intent.select(
            requested_template="c_clip",
            parameters={**FROZEN_PARAMETERS["c_clip"], "bore_d": 60.0},
            external_geometry=False, ambiguities=())
        self.assertEqual("FULL", decision.route)
        reasons = " ".join(r for c in decision.candidates for r in c.reasons)
        self.assertIn("bore_d=60", reasons)
        self.assertIn("[4, 40]", reasons)

    def test_external_geometry_and_ambiguity_route_fitted(self) -> None:
        params = FROZEN_PARAMETERS["c_clip"]
        self.assertEqual("FITTED", intent.select(
            requested_template="c_clip", parameters=params,
            external_geometry=True, ambiguities=()).route)
        self.assertEqual("FITTED", intent.select(
            requested_template="c_clip", parameters=params,
            external_geometry=False, ambiguities=("radius or diameter?",)).route)

    def test_an_unmatched_shape_is_full_and_says_so(self) -> None:
        decision = intent.select(requested_template=None,
                                 parameters={"nothing_certified": 1.0},
                                 external_geometry=False, ambiguities=())
        self.assertEqual("FULL", decision.route)
        self.assertIn("no certified template", decision.condition)


if __name__ == "__main__":
    unittest.main()
