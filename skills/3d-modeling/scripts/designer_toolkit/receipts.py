#!/usr/bin/env python3
"""Emit the two handoff artifacts from what the commission already measured.

`artifact_manifest.json` and `candidate_readiness.md` were the last things a
designer hand-wrote, and every number in them -- hashes, bounding boxes,
component counts, overhang areas, edge measurements -- is something the
commission just computed from the exported mesh. Re-typing them is not merely
slow, it is the specific way the worst evidence defect happened: one archived
run's receipt described a mesh that was no longer the one being shipped.

So the manifest is derived, and the readiness document is derived with exactly
two blanks left in it -- the judgments a machine cannot make. Those blanks are
the point. A receipt that fills itself in completely has stopped being a
receipt.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

# The manifest's `type` is the file format; `role` is what the file is for.
# Conflating them emitted `type: "render"`, which is not in the schema's type
# enum at all -- so a derived manifest had to be hand-corrected, which is the
# entire cost deriving it was meant to remove.
_MANIFEST_TYPES = {".stl": "stl", ".step": "step", ".stp": "step", ".3mf": "3mf",
                   ".png": "png", ".jpg": "png", ".jpeg": "png", ".svg": "svg"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _bbox_block(stl_path: Path) -> dict[str, list[float]] | None:
    """Corner coordinates, read from the mesh being hashed.

    `MeasureReport.bbox_mm` carries extents, and the manifest wants corners --
    deriving them from anything but the shipped bytes is how a receipt starts
    describing a different mesh.
    """
    import trimesh

    try:
        bounds = trimesh.load(stl_path, process=False).bounds
    except Exception:  # noqa: BLE001 - an unreadable export is reported by the solid check
        return None
    return {"min": [float(v) for v in bounds[0]], "max": [float(v) for v in bounds[1]]}


def build_manifest(
    commission: dict[str, Any],
    out_dir: Path,
    *,
    job_id: str,
    candidate_id: str = "candidate-01",
    source_revisions: dict[str, int] | None = None,
    updated_utc: str,
) -> dict[str, Any]:
    """Every file the commission produced, hashed from disk.

    Hashed from disk rather than carried through from the export report: the
    manifest's job is to describe the bytes that actually exist now.
    """
    export = commission.get("evidence", {}).get("export", {})

    artifacts: list[dict[str, Any]] = []
    for key, role, printable in (("stl_path", "candidate", True), ("step_path", "candidate", False)):
        raw = export.get(key)
        if not raw:
            continue
        path = Path(raw)
        if not path.is_file():
            continue
        row: dict[str, Any] = {
            "id": candidate_id if key == "stl_path" else f"{candidate_id}-step",
            "role": role,
            "path": path.name,
            "type": _MANIFEST_TYPES.get(path.suffix.lower(), "stl"),
            "sha256": sha256_file(path),
            "printable_deliverable": printable,
        }
        if key == "stl_path":
            components = export.get("components")
            if isinstance(components, int) and components >= 1:
                row["expected_components"] = components
            bbox = _bbox_block(path)
            if bbox:
                row["bbox"] = bbox
        if source_revisions:
            row["source_revisions"] = dict(source_revisions)
        artifacts.append(row)

    # The mating reference, when one was supplied. The gate was handed the file
    # and measured the fit against it, so leaving it off the manifest made the
    # designer hand-add the row -- and a reference nothing hashes can drift from
    # the one the clearance was measured against. Never printable: the contract
    # rejects a mating_reference marked as a deliverable.
    reference = commission.get("evidence", {}).get("reference_path")
    if reference:
        path = Path(reference)
        if path.is_file():
            row = {
                "id": "mating-reference", "role": "mating_reference", "path": path.name,
                "type": _MANIFEST_TYPES.get(path.suffix.lower(), "stl"),
                "sha256": sha256_file(path), "printable_deliverable": False,
            }
            bbox = _bbox_block(path)
            if bbox:
                row["bbox"] = bbox
            if source_revisions:
                row["source_revisions"] = dict(source_revisions)
            artifacts.append(row)

    # Renders are listed too. An evidence file nothing hashes can silently
    # describe a mesh you no longer ship.
    for relative in commission.get("evidence", {}).get("renders", []) or []:
        path = out_dir / relative
        if path.is_file():
            artifacts.append({
                "id": path.stem, "role": "render", "path": relative.replace("\\", "/"),
                "type": _MANIFEST_TYPES.get(path.suffix.lower(), "png"),
                "sha256": sha256_file(path),
                "printable_deliverable": False,
            })

    return {
        "contract": "artifact-manifest",
        "contract_version": 1,
        "job_id": job_id,
        "candidate_id": candidate_id,
        "units": "mm",
        "updated_utc": updated_utc,
        "artifacts": artifacts,
    }


_UNSET = "<!-- REQUIRED: the agent fills this in after looking. -->"

# When no render exists there is nothing to look at, so `visual_accept` is not a
# blank to fill -- it is a question this run cannot answer. A verification caught
# a `visual_accept: yes` written on an interpreter with no renderer; the claim
# was sincere and ungrounded, which is the worst combination.
_BLOCKED = ("<!-- CANNOT BE ANSWERED HERE: no render was produced, so there was "
            "nothing to look at. Install the `visual` extra and re-run, or hand off "
            "with this explicitly unanswered. Do not write a verdict you did not see. -->")


def build_readiness(
    commission: dict[str, Any],
    *,
    job_id: str,
    candidate_id: str = "candidate-01",
    revision: int = 1,
    source_revisions: dict[str, int] | None = None,
    updated_utc: str,
) -> str:
    """The readiness document, with the judgments left blank.

    Marked NON-ACCEPTANCE in the frontmatter because that is what it is: the
    designer measuring its own work. A verifier that has not re-derived these
    numbers itself has not verified anything.
    """
    export = commission.get("evidence", {}).get("export", {})
    verdict = commission.get("verdict", "FAIL")
    status = "READY" if verdict == "PASS" else "NOT_READY"

    rows = "\n".join(
        f"| {c['id']} | {c['title']} | {c['result']} | {c['detail'].replace('|', '/')} |"
        for c in commission.get("checks", [])
    )
    failures = [c for c in commission.get("checks", []) if c["result"] == "FAIL"]
    open_items = "\n".join(
        f"| {c['id']} | {c.get('next_action', '').replace('|', '/')} |" for c in failures
    ) or "| none | commission reported no failing check |"

    rendered = any(c["id"] == "render" and c["result"] == "SKIPPED"
                   for c in commission.get("checks", []))
    visual = _BLOCKED if rendered else _UNSET

    # `PASS` says nothing failed. It does not say much ran, and a reader takes
    # `status: READY` to mean both. A run whose STEP export, interface fit and
    # every edge treatment SKIPPED reported READY off four executed checks --
    # and on the DIRECT route, whose built-in plan declares no interfaces and no
    # edges, that is the normal case rather than an unlucky one.
    coverage = commission.get("coverage") or {}
    declared, ran = coverage.get("declared", 0), coverage.get("ran", 0)
    skipped = coverage.get("skipped") or []
    coverage_line = f"**{ran} of {declared} checks ran.**"
    if skipped:
        coverage_line += (
            f" These did not, and this document asserts nothing about them: "
            f"`{'`, `'.join(skipped)}`. Treat every one as an open question a "
            f"reader has to close by other means.")
    revisions = source_revisions or {}
    # No default of 1. A binding invented here is worse than an absent one: it
    # asserts a revision nobody checked, and `contracts status` -- the only
    # check that compares a binding against the current revision -- then reports
    # a clean match against a number this file made up.
    dimensions_revision = revisions.get("dimensions", "UNBOUND")
    print_plan_revision = revisions.get("print_plan", "UNBOUND")
    return f"""---
contract: candidate-readiness
contract_version: 4
job_id: {job_id}
revision: {revision}
candidate_id: {candidate_id}
owner: cad-designer
status: {status}
non_acceptance: true
dimensions_revision: {dimensions_revision}
print_plan_revision: {print_plan_revision}
candidate_stl_sha256: {export.get('file_sha256', '')}
commission_verdict: {verdict}
updated_utc: {updated_utc}
---

# Candidate readiness — DESIGNER SELF-CHECK, NON-ACCEPTANCE

Generated from `commission.json`. Every number below was measured on the
re-imported exported STL, not on the in-memory model. This document never
passes a Phase-4 gate on a verifier's behalf.

## Deterministic checks

{coverage_line}

| ID | Check | Result | Measured |
|---|---|---|---|
{rows}

## Open items

| Check | Required next action |
|---|---|
{open_items}

## Judgment — not machine-supplied

Commission leaves these null on purpose. Answer both, from the renders.

- `visual_accept`: {visual}
- `fit_band_ok`: {_UNSET}
"""


def write(
    commission: dict[str, Any],
    out_dir: Path,
    *,
    job_id: str,
    candidate_id: str = "candidate-01",
    source_revisions: dict[str, int] | None = None,
    revision: int = 1,
    updated_utc: str,
) -> list[Path]:
    manifest_path = out_dir / "artifact_manifest.json"
    manifest_path.write_text(
        json.dumps(build_manifest(commission, out_dir, job_id=job_id,
                                  candidate_id=candidate_id,
                                  source_revisions=source_revisions,
                                  updated_utc=updated_utc), indent=2) + "\n",
        encoding="utf-8")
    readiness_path = out_dir / "candidate_readiness.md"
    readiness_path.write_text(
        build_readiness(commission, job_id=job_id, candidate_id=candidate_id,
                        revision=revision, source_revisions=source_revisions,
                        updated_utc=updated_utc),
        encoding="utf-8")
    return [manifest_path, readiness_path]
