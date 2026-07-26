#!/usr/bin/env python3
"""Draft the verification report from the verifier's own recomputation.

The seven-check table is filled by hand from numbers the verifier just measured
-- the same retyping that made the designer's receipts drift from the mesh they
described, one role along. So the deterministic columns are transcribed from the
verifier's *own* `commission.json`, and the columns that carry judgment are left
empty.

What is deliberately NOT filled in: every `Visual observation`, the whole
Input/upstream audit, the defect table, and the verdict. A report that arrives
pre-concluded is not a verification, and check 4 -- looking at the render -- is
the one thing in the set no tool can do. The draft exists to stop the verifier
retyping measurements, not to save it from deciding.

    python <skill>/scripts/dt.py report --commission verify/commission.json          --out verification_report.md --job-id <job> --updated-utc <iso8601>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Report row -> the commission check ids that settle its numeric column.
_ROWS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("1 interference", ("fit",), "seated per-side clearance vs declared band"),
    ("2 full insertion/travel sweep", (), "VERIFIER-OWNED: no tool computes this"),
    ("3 section", ("render",), "section render"),
    ("4 same-view/photo overlay look", (), "VERIFIER-OWNED: judgment, not a number"),
    ("5 named-datum feature positions/handedness", (),
     "VERIFIER-OWNED: compare datums, and again with the coordinate negated"),
    ("6 measurement-to-geometry audit", ("envelope", "edge-"),
     "envelope and plan-named edges"),
    ("7 planned-orientation printability/faces", ("support", "solid"),
     "downward area per support rule, in the orientation each declares"),
)

_UNSET = "<!-- REQUIRED -->"


def _matching(checks: list[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if not keys:
        return []
    return [c for c in checks
            if any(c["id"] == k or c["id"].startswith(k) for k in keys)]


def _cell(text: str) -> str:
    return text.replace("|", "/").replace("\n", " ")


def build(commission: dict[str, Any], *, job_id: str, candidate_id: str,
          revision: int, updated_utc: str) -> str:
    checks = commission.get("checks", [])
    export = commission.get("evidence", {}).get("export", {})

    rows = []
    for label, keys, method in _ROWS:
        found = _matching(checks, keys)
        if not found:
            rows.append(f"| {label} | {method} | | {_UNSET} | {_UNSET} | |")
            continue
        numeric = "; ".join(_cell(c["detail"]) for c in found)
        worst = "FAIL" if any(c["result"] == "FAIL" for c in found) else (
            "SKIPPED" if all(c["result"] == "SKIPPED" for c in found) else "PASS")
        rows.append(f"| {label} | {_cell(method)} | {numeric} | {_UNSET} | {worst} | "
                    "verify/commission.json |")

    return f"""---
contract: verification-report
contract_version: 4
job_id: {job_id}
revision: {revision}
owner: verifier
status: {_UNSET}
candidate_id: {candidate_id}
candidate_stl_sha256: {export.get('file_sha256', '')}
dimensions_revision: {_UNSET}
print_plan_revision: {_UNSET}
fresh_context: true
updated_utc: {updated_utc}
---

# Independent verification

Numeric columns below are transcribed from this verifier's own recomputation
against the delivered STL. Every `{_UNSET}` is yours to answer, and the report is
not complete until none remain.

## Input/upstream audit
| Input/claim | Expected revision/hash/datum | Independent observation | Result | Evidence |
|---|---|---|---|---|
| {_UNSET} | | | | |

## Seven checks on re-imported exported STL
| Check | Method | Numeric result | Visual observation | Result | Evidence |
|---|---|---:|---|---|---|
{chr(10).join(rows)}

## Defects
| ID | Owning loop | Feature/check IDs | Expected vs observed | Evidence | Required acceptance condition |
|---|---|---|---|---|---|

## Verdict
{_UNSET} — PASS, or REJECT to METROLOGY / PRINT_PLAN / CANDIDATE_BUILD.
A green numeric column is necessary and never sufficient: no number in it
distinguishes a correct part from a plausible wrong one.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--commission", type=Path, required=True,
                        help="the verifier's OWN commission.json, not the designer's")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--candidate-id", default="candidate-01")
    parser.add_argument("--revision", type=int, default=1)
    parser.add_argument("--updated-utc", required=True)
    args = parser.parse_args(argv)

    commission = json.loads(args.commission.read_text(encoding="utf-8"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(build(commission, job_id=args.job_id,
                              candidate_id=args.candidate_id, revision=args.revision,
                              updated_utc=args.updated_utc), encoding="utf-8")
    sys.stdout.write(f"{args.out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
