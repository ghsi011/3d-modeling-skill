#!/usr/bin/env python3
"""`design-tool selftest` — does this installation still build what it certifies?

The repository's test suite is external to the distributed bundle: a skill
installed somewhere else has the code and none of the tests, so "it imported"
was the strongest thing an agent could say about an installation before running
a real job against it.

This is the smoke set that ships. It builds every certified template through the
real backends, re-imports the exported mesh, and compares the contract each one
produced against the hashes frozen in this file. Those hashes are derived from
declared parameters, expectations and the envelope -- never from a mesh -- so
they hold across trimesh, manifold3d and build123d versions, and a mismatch
means a certified contract moved rather than that a dependency was bumped.

The frozen constants live here, in the shipped module, rather than in the test
file that checks them. `pipeline/test_frozen.py` imports them. Two copies of a
golden is two goldens, and the one nobody runs is the one that drifts.
"""
from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------
# The frozen jobs: one per certified template, inside its domain.
# --------------------------------------------------------------------------

FROZEN_PARAMETERS: dict[str, dict[str, Any]] = {
    "box_shell": {"inner_w": 60.0, "inner_d": 40.0, "inner_h": 30.0,
                  "wall": 2.4, "floor": 2.0},
    "c_clip": {"bore_d": 12.0, "wall": 3.0, "height": 9.0, "mouth_gap": 9.0,
               "flange_w": 40.0, "flange_d": 22.0, "flange_t": 5.0, "screw_d": 4.8},
    "l_bracket": {"width": 30.0, "leg_a": 50.0, "leg_b": 50.0, "thickness": 4.0,
                  "hole_d": 5.0, "hole_inset": 12.0},
    "trim_ring": {"hole_d": 60.0, "lip_w": 5.0, "panel_t": 18.0, "lip_t": 3.0,
                  "wall": 2.0, "chamfer": 1.0},
    "vented_enclosure": {"inner_w": 80.0, "inner_d": 60.0, "inner_h": 40.0,
                         "wall": 2.4, "floor": 2.0, "vent_cols": 4, "vent_rows": 3,
                         "vent_w": 6.0, "vent_h": 4.0, "boss_d": 8.0, "boss_bore": 3.0},
}

FROZEN_CONTRACTS: dict[str, dict[str, Any]] = {
    "box_shell": {
        "contract_sha256": "7ab7d78e886c0616c18cf26e75836a4de31f6621af9609624c0674f7b0aeaebf",
        "backend": "trimesh-manifold", "features": 4,
        "bbox": {"x": 64.8, "y": 44.8, "z": 32.0},
    },
    "c_clip": {
        "contract_sha256": "5a8223076e4cab37ef76eedc3cc144b36df88aaa393bb47bfdc4df51ff42217b",
        "backend": "trimesh-manifold", "features": 5,
        "bbox": {"x": 40.0, "y": 22.0, "z": 14.0},
    },
    "l_bracket": {
        "contract_sha256": "fc5c9e98754e525515f70f026fc734a03763c190adecfadb497fcddb6c2c6b47",
        "backend": "trimesh-manifold", "features": 4,
        "bbox": {"x": 30.0, "y": 50.0, "z": 50.0},
    },
    "trim_ring": {
        "contract_sha256": "4c1e62738bcd92b065885fed1b3ace7c9684e0f8a290526ff6d2a910820c3b31",
        "backend": "build123d", "features": 4,
        "bbox": {"x": 70.0, "y": 70.0, "z": 21.0},
    },
    "vented_enclosure": {
        "contract_sha256": "1bb18f1baf419fdc45983e82fd54a8c2f0a3d4b2255bb806971b65505cc4f010",
        "backend": "trimesh-manifold", "features": 4,
        "bbox": {"x": 84.8, "y": 64.8, "z": 42.0},
    },
}

# The receipts each route writes. A change that stops writing one of these has
# removed evidence, whatever else it improved.
FROZEN_ARTIFACTS: dict[str, frozenset[str]] = {
    "DIRECT": frozenset({"intent_manifest", "model_contract", "artifact_manifest",
                         "commission_report", "final_status"}),
    "FITTED": frozenset({"intent_manifest", "specification", "model_contract",
                         "artifact_manifest", "commission_report", "final_status",
                         "verification_report"}),
    "FULL": frozenset({"intent_manifest", "specification", "model_contract",
                       "artifact_manifest", "commission_report", "final_status",
                       "verification_report"}),
}

SELFTEST_JOB_ID = "selftest"
SELFTEST_PRINTER = "Selftest Printer"
SELFTEST_MATERIAL = {"process": "FDM", "material": "PLA"}
SELFTEST_NOZZLE = {"diameter_mm": 0.4}
SELFTEST_ORIENTATION = {"model_to_printer_matrix": "identity", "bed_z_mm": 0.0}
SELFTEST_UTC = "1970-01-01T00:00:00Z"


def _request(out: Path, template: str):
    from . import runner
    return runner.JobRequest(
        job_id=SELFTEST_JOB_ID, brief_path=out / "brief.md", template=template,
        parameters=dict(FROZEN_PARAMETERS[template]), stated=frozenset(),
        consequence="INCONSEQUENTIAL", out_dir=out, updated_utc=SELFTEST_UTC,
        render=False, printer=SELFTEST_PRINTER, material=dict(SELFTEST_MATERIAL),
        nozzle=dict(SELFTEST_NOZZLE), orientation=dict(SELFTEST_ORIENTATION))


def _contract_case(template: str) -> dict[str, Any]:
    """The contract only: no geometry, so it runs on any interpreter."""
    from . import runner, templates as T
    expected = FROZEN_CONTRACTS[template]
    with tempfile.TemporaryDirectory() as raw:
        contract = runner._contract_from(T.get(template), _request(Path(raw), template))
    actual = contract.contract_hash()
    problems = []
    if actual != expected["contract_sha256"]:
        problems.append(f"contract hash {actual} != frozen {expected['contract_sha256']}")
    if contract.backend != expected["backend"]:
        problems.append(f"backend {contract.backend} != frozen {expected['backend']}")
    if len(contract.features) != expected["features"]:
        problems.append(f"{len(contract.features)} features != frozen {expected['features']}")
    if contract.expected_bbox_mm != expected["bbox"]:
        problems.append(f"bbox {contract.expected_bbox_mm} != frozen {expected['bbox']}")
    return {"check": f"contract:{template}", "ok": not problems, "problems": problems}


def _build_case(template: str) -> dict[str, Any]:
    """Build, export, re-import and commission -- the whole deterministic run."""
    from . import runner
    started = time.perf_counter()
    with tempfile.TemporaryDirectory() as raw:
        out = Path(raw)
        try:
            result = runner.run(_request(out, template))
        except Exception as exc:                            # noqa: BLE001
            return {"check": f"build:{template}", "ok": False,
                    "problems": [f"{type(exc).__name__}: {exc}"]}
        problems = []
        if result.final_status is None:
            problems.append(f"{result.stage}: {result.message}")
        else:
            missing = FROZEN_ARTIFACTS["DIRECT"] - set(result.artifacts)
            if missing:
                problems.append(f"receipts not written: {sorted(missing)}")
            if result.final_status["commission_verdict"] != "PASS":
                problems.append("commissioning did not pass on a certified template "
                                f"in its own domain: {result.message}")
            if result.final_status["route"] != "DIRECT":
                problems.append(f"route {result.final_status['route']} != DIRECT")
        return {"check": f"build:{template}", "ok": not problems, "problems": problems,
                "seconds": round(time.perf_counter() - started, 3),
                "final_status": (result.final_status or {}).get("final_status")}


def _toolchain_case() -> dict[str, Any]:
    import importlib.metadata as md
    problems, versions = [], {}
    for name in ("trimesh", "manifold3d", "build123d", "numpy", "pillow"):
        try:
            versions[name] = md.version(name)
        except md.PackageNotFoundError:
            problems.append(f"{name} is required on the core path and is not installed")
    return {"check": "toolchain", "ok": not problems, "problems": problems,
            "versions": versions}


def run(*, quick: bool = False) -> dict[str, Any]:
    """Every smoke check, with the failures named rather than counted."""
    cases = [_toolchain_case()]
    for template in sorted(FROZEN_CONTRACTS):
        cases.append(_contract_case(template))
    if not quick:
        for template in sorted(FROZEN_PARAMETERS):
            cases.append(_build_case(template))
    failed = [c for c in cases if not c["ok"]]
    return {"ok": not failed, "cases": cases, "failed": len(failed),
            "ran": len(cases)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="design-tool selftest",
        description="Build every certified template and compare the contracts "
                    "against the frozen hashes.")
    parser.add_argument("--quick", action="store_true",
                        help="contracts and toolchain only -- no geometry is built")
    parser.add_argument("--json", action="store_true", help="machine-readable report")
    args = parser.parse_args(argv)

    report = run(quick=args.quick)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for case in report["cases"]:
            mark = "[yes]" if case["ok"] else "[NO ]"
            seconds = f"  {case['seconds']:.2f}s" if "seconds" in case else ""
            print(f"  {mark} {case['check']}{seconds}")
            for problem in case["problems"]:
                print(f"         {problem}")
        print(f"\n  {report['ran'] - report['failed']}/{report['ran']} checks passed")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
