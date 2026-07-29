#!/usr/bin/env python3
"""Everything a verifier can settle mechanically, in one call.

The verifier's chain was six commands: raw integrity, recomputation, a crop, two
contract checks, and the report draft. Every one of them is under a second of
compute, and together they cost minutes -- because the cost of this pipeline is
agent turns, not arithmetic. A measured dispatch spent 6 min 25 s running four
commands totalling 4.4 seconds of work.

So the work is collapsed rather than trimmed. What lands is the same evidence in
one artifact, and a verifier whose remaining job is the part no tool can do.

On what the recomputation is worth, stated precisely because the charter is
about to stop asking for six commands on the strength of it: running the same
instrument over the same bytes cannot catch a wrong instrument -- both runs
share the bug -- and it cannot catch a hand-edited receipt, because receipts are
derived rather than typed. What it catches is a delivered STL that is not the
one the designer measured, and that is a hash comparison. It is kept anyway: it
costs a second, it is the only thing that would notice a receipt describing a
different mesh, and the binding proof is reported beside it so a reader can see
which of the two actually settled the question.

    uv run --project <skill> --frozen python <skill>/scripts/dt.py audit <project-dir> --out <verifier-dir> \
        --job-id <job> --updated-utc <iso8601>
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from pipeline import schemas as pipeline_schemas

from .verdict import FAIL as _FAIL
from .verdict import PASS as _PASS
from .verdict import Check


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _bound_hash(readiness: Path) -> str | None:
    """The candidate hash the designer's receipt commits to.

    Read out of the frontmatter rather than parsed as YAML: the file is Markdown
    with a fenced header, and adding a YAML dependency to read one scalar buys
    nothing.
    """
    try:
        lines = readiness.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        if line.startswith("candidate_stl_sha256:"):
            return line.split(":", 1)[1].strip() or None
    return None


def check_binding(project: Path, stl: Path) -> Check:
    """Is the delivered STL the one the receipt describes?

    This is the whole residual value of re-measuring, reduced to a hash. If it
    holds, the designer's numbers describe these exact bytes and a recomputation
    is redundant by construction; if it does not, nothing downstream of the
    receipt means anything and the recomputation is the least of the problem.
    """
    from .receipts import sha256_file

    readiness = project / "candidate_readiness.md"
    if not readiness.is_file():
        return Check("binding", "Delivered STL matches the receipt", _FAIL,
                     "no candidate_readiness.md in the project",
                     "Without the designer's receipt there is nothing to verify against.")
    bound = _bound_hash(readiness)
    if not bound:
        return Check("binding", "Delivered STL matches the receipt", _FAIL,
                     "candidate_readiness.md declares no candidate_stl_sha256",
                     "A receipt that binds no hash describes no particular mesh.")
    actual = sha256_file(stl)
    if bound == actual:
        return Check("binding", "Delivered STL matches the receipt", _PASS,
                     f"{actual[:12]} as bound")
    return Check(
        "binding", "Delivered STL matches the receipt", _FAIL,
        f"receipt binds {bound[:12]}, delivered file is {actual[:12]}",
        "The measurements in candidate_readiness.md describe a different mesh than "
        "the one delivered. Nothing downstream of that receipt can be relied on; "
        "send it back rather than re-deriving it here.",
    )


def _run(argv: list[str], cwd: Path) -> tuple[int, str, str]:
    done = subprocess.run([sys.executable, "-m", *argv], cwd=str(cwd),
                          capture_output=True, text=True, check=False)
    return done.returncode, done.stdout, done.stderr


def audit(project: Path, out_dir: Path, *, job_id: str, updated_utc: str,
          stl: Path, plan: Path, reference: Path | str | None = None) -> dict[str, Any]:
    scripts = Path(__file__).resolve().parents[1]
    out_dir.mkdir(parents=True, exist_ok=True)

    checks: list[Check] = [check_binding(project, stl)]
    evidence: dict[str, Any] = {}

    # Reported, not re-checked. The one acceptance-relevant number in a raw parse
    # is the degenerate face count, and `normalize_mesh` takes it on an unmutated
    # copy before removing anything -- so it is identical, by construction, to
    # what the recomputation's `repair` check already fails on. A separate check
    # here would be two paths to one number that could disagree, which is the
    # defect this pipeline has already fixed once, in overhang area, at 2x.
    #
    # Every other field a raw parse yields is meaningless for STL: the format
    # stores no vertex sharing, so a sound part reads as many components and
    # watertight=False. It is here because a reader wanting the numbers should
    # not need a second command to see them.
    from . import integrity as integrity_module
    evidence["raw_integrity"] = integrity_module.report(stl)

    # A verifier holds the STL and the plan, never model.py, so a template's own
    # expectations would be invisible here. The designer's evidence records the
    # rows it checked; they are re-measured below against the delivered bytes,
    # which is the part that matters.
    theirs = _read_json(project / "commission.json")
    rows = (theirs or {}).get("evidence", {}).get("features_checked") or []
    plan_for_recompute = plan
    if rows and not (_read_json(plan) or {}).get("features"):
        merged = _read_json(plan) or {}
        merged["features"] = rows
        plan_for_recompute = out_dir / "plan_with_declared_features.json"
        plan_for_recompute.write_text(json.dumps(merged, indent=2), encoding="utf-8")

    argv = ["designer_toolkit.commission", "--stl", str(stl),
            "--plan", str(plan_for_recompute),
            "--path-base", str(project),
            "--out", str(out_dir), "--job-id", job_id, "--updated-utc", updated_utc,
            "--no-receipts", "--no-render"]
    if reference is not None:
        argv += ["--reference", _project_relative_name(
            project, reference, what="audit reference")]
    code, stdout, stderr = _run(argv, scripts)
    mine = json.loads(stdout) if stdout.strip().startswith("{") else None
    if mine is None:
        checks.append(Check("recompute", "Independent recomputation", _FAIL,
                            (stderr or "no output").strip()[-400:],
                            "The gate could not run against the delivered STL."))
    else:
        (out_dir / "commission.json").write_text(json.dumps(mine, indent=2), encoding="utf-8")
        disagreements = _compare(theirs, mine) if theirs else ["designer wrote no commission.json"]
        checks.append(Check(
            "recompute", "Independent recomputation agrees", _PASS if not disagreements else _FAIL,
            "every check verdict matches the designer's" if not disagreements
            else "; ".join(disagreements),
            "" if not disagreements else
            "The same instrument on the same bytes reached a different verdict. That "
            "is either a receipt describing another mesh or a plan that changed under "
            "it; find which before reading anything else here.",
        ))
        evidence["coverage"] = mine.get("coverage")
        evidence["recomputed_verdict"] = mine.get("verdict")
        if code != 0:
            checks.append(Check("gate", "Delivered candidate passes the gate", _FAIL,
                                f"recomputation exited {code}",
                                "The delivered part fails a deterministic check."))

    for command, label in ((["team_tools.contracts", "validate", str(project),
                             "--require", _required_contracts(project)],
                            "contracts-validate"),
                           (["team_tools.contracts", "status", str(project)], "contracts-status")):
        code, stdout, stderr = _run(command, scripts)
        checks.append(Check(
            label, f"Contract {label.split('-')[1]}", _PASS if code == 0 else _FAIL,
            "clean" if code == 0 else _summarise_contracts(stdout, stderr),
            "" if code == 0 else "Fix the contracts before judging the geometry.",
        ))

    evidence["look_at"] = _gather_views(project, out_dir)

    # Recomputed here from the delivered bytes rather than copied out of the
    # designer's receipt, which also carries it. The point of the curve is to
    # show a fresh reader the whole part; taking the author's version of it
    # would defeat that for the sake of 0.14 s.
    try:
        from . import features as _features
        from ._bootstrap import as_mesh
        evidence["slice_profile"] = _features.slice_profile(as_mesh(str(stl)))
    except Exception:  # noqa: BLE001 - evidence, never a gate
        evidence["slice_profile"] = []

    return {
        "verdict": _FAIL if any(c.result == _FAIL for c in checks) else _PASS,
        "checks": [c.as_dict() for c in checks],
        "evidence": evidence,
        "still_requires_a_look": [
            "The images in evidence.look_at. Every measurement above is conditioned on "
            "somebody having declared what to measure; a render is conditioned on nothing, "
            "which is why it is the only thing here that can show a feature nobody named.",
            "The sheet against the geometry. Nothing above reads dimensions.md, so a "
            "part that measures self-consistently and disagrees with what was asked "
            "for passes everything here.",
            "Whether the thing solves the problem it was built for.",
        ],
    }


# Never `verification_report`: this command produces the numbers that report is
# written from, so at audit time it cannot exist. Requiring it made the first
# audit of every job fail with REQUIRED_CONTRACT_MISSING, which reads exactly
# like a real defect and was documented as the normal first pass.
_AT_AUDIT_TIME = "job_state,dimensions,print_plan,artifact_manifest,candidate_readiness"


def _required_contracts(project: Path) -> str:
    """What this project should contain by the time an audit runs.

    A DIRECT job also never has a verification_report, because it dispatches
    nobody -- so both routes want the same set here, for different reasons.
    """
    return _AT_AUDIT_TIME


def _delivered_candidate(project: Path) -> Path:
    """The STL this project actually produced, not a guessed filename.

    `commission --candidate-id C1` writes `C1.stl`, and this defaulted to
    `candidate-01.stl` regardless -- so any job that named its candidate exited 2
    here until the caller passed `--stl`. Two defaults that disagree about the
    same file is a trap, so this one asks the manifest, which records what was
    written, and only falls back to the conventional name.
    """
    manifest_path = project / "artifact_manifest.json"
    if not manifest_path.is_file():
        return pipeline_schemas.resolve_within(project, "candidate-01.stl",
                                               what="default candidate STL")
    manifest = _read_json(manifest_path)
    if not isinstance(manifest, dict):
        raise ValueError("artifact_manifest.json is unreadable; candidate path is unresolved")
    candidate_id = manifest.get("candidate_id")
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        raise ValueError("artifact_manifest.json has no non-empty candidate_id")
    rows = [row for row in (manifest.get("artifacts") or [])
            if isinstance(row, dict) and row.get("id") == candidate_id]
    if len(rows) != 1 or rows[0].get("role") != "candidate" or rows[0].get("type") != "stl":
        raise ValueError(
            f"artifact_manifest.json candidate_id {candidate_id!r} does not name exactly "
            "one candidate STL artifact")
    return pipeline_schemas.resolve_within(
        project, rows[0].get("path"), what="artifact_manifest candidate STL"
    )


def _project_relative_name(project: Path, raw: Path | str, *, what: str) -> str:
    """Validate a project-relative input and return its stable spelling."""
    resolved = pipeline_schemas.resolve_within(project, str(raw), what=what)
    return resolved.relative_to(project.resolve()).as_posix()


def _gather_views(project: Path, out_dir: Path) -> list[str]:
    """The images to look at, tiled onto one page and listed by path.

    Named rather than left to be found. A verifier that has to discover which
    renders exist spends turns on directory listings before it has looked at
    anything, and turns are the cost here. The contact sheet is a triage page,
    not a substitute for the full-size views -- both are listed.
    """
    renders = sorted((project / "renders").glob("*.png")) if (project / "renders").is_dir() else []
    if not renders:
        return []
    views = [str(path) for path in renders]
    try:
        import crop_evidence
        sheet = crop_evidence.contact_sheet(renders, out_dir / "contact_sheet.jpg")
        views.insert(0, str(sheet))
    except Exception:  # noqa: BLE001 - a missing imaging extra must not fail the audit
        pass
    return views


def _summarise_contracts(stdout: str, stderr: str) -> str:
    """Which contracts failed, not the whole payload.

    These commands emit a full JSON report. Pasting it into a check detail buries
    the one line that matters under a schema dump, and the agent reading this is
    paying for every token of it.
    """
    payload = json.loads(stdout) if stdout.strip().startswith("{") else None
    if payload is None:
        return (stderr or stdout).strip()[-300:]
    results = payload.get("results") or {}
    bad = sorted(k for k, v in results.items() if v != "PASS" and k != "overall")
    issues = [f"{i.get('id')}@{i.get('where')}" for i in (payload.get("issues") or [])
              if i.get("severity") == "error"][:6]
    detail = ", ".join(bad) or "see the report"
    return f"{detail}" + (f" ({'; '.join(issues)})" if issues else "")


def _structurally_absent(check_id: str) -> bool:
    """Checks a verifying run cannot have, for reasons that are not defects.

    A verifier measures delivered bytes: it has no `model.py`, so the pre-build
    static stage has nothing to read; it exports nothing, so there is no STEP to
    report on; and it renders nothing, because the designer's renders are the
    images under discussion and re-rendering them proves nothing about the part.

    Listed explicitly rather than tolerated by a blanket rule. Every id not named
    here that goes missing is a real disagreement, and treating "absent" as
    "fine" is how a recomputation comes back quietly emptier than the run it is
    checking.
    """
    return check_id in ("step", "render") or check_id.startswith("static-")


def _compare(theirs: dict[str, Any], mine: dict[str, Any]) -> list[str]:
    """Which check verdicts differ, by id."""
    def by_id(payload):
        return {c["id"]: c["result"] for c in payload.get("checks", [])}

    a, b = by_id(theirs), by_id(mine)
    out = []
    for check_id in sorted(set(a) | set(b)):
        if _structurally_absent(check_id):
            # Asymmetric on purpose, and in both directions: a successful render
            # adds no check at all, while this recomputation passes --no-render
            # and therefore always reports one. Comparing those two would
            # manufacture a disagreement out of the fact that the verifier is
            # not the one drawing the pictures.
            continue
        if check_id not in a:
            out.append(f"{check_id}: designer did not run it")
        elif check_id not in b:
            out.append(f"{check_id}: absent from the recomputation")
        elif a[check_id] != b[check_id]:
            out.append(f"{check_id}: designer {a[check_id]}, recomputed {b[check_id]}")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("project", type=Path)
    parser.add_argument("--out", type=Path, required=True,
                        help="the verifier's own directory, never the project root: "
                             "writing over the designer's receipts destroys the comparison")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--updated-utc", required=True)
    parser.add_argument("--stl", type=Path, help="default: <project>/candidate-01.stl")
    parser.add_argument("--plan", type=Path, help="default: <project>/print_plan_checks.json")
    parser.add_argument("--reference", type=Path)
    args = parser.parse_args(argv)

    if args.out.resolve() == args.project.resolve():
        sys.stderr.write("audit: --out must not be the project root; the comparison "
                         "needs the designer's receipts left intact\n")
        return 2

    # Absolute throughout: every subprocess below runs from the scripts
    # directory so it can import the package, and a relative `--plan` handed
    # straight through resolved against the wrong root.
    project = args.project.resolve()
    out = args.out.resolve()
    try:
        manifest_candidate = _delivered_candidate(project)
        stl = (args.stl or manifest_candidate).resolve()
    except (OSError, ValueError, pipeline_schemas.PathEscape) as exc:
        sys.stderr.write(f"audit: candidate path is unsafe or unresolved: {exc}\n")
        return 2
    plan = (args.plan or project / "print_plan_checks.json").resolve()
    for path, what in ((stl, "candidate STL"), (plan, "print plan")):
        if not path.is_file():
            sys.stderr.write(f"audit: no {what} at {path}\n")
            return 2

    try:
        result = audit(project, out, job_id=args.job_id,
                       updated_utc=args.updated_utc, stl=stl, plan=plan,
                       reference=str(args.reference) if args.reference else None)
    except (OSError, ValueError, pipeline_schemas.PathEscape) as exc:
        sys.stderr.write(f"audit: reference path is unsafe or unresolved: {exc}\n")
        return 2
    (out / "audit.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    sys.stdout.write(json.dumps(result, indent=2) + "\n")
    for check in result["checks"]:
        if check["result"] == _FAIL:
            sys.stderr.write(f"FAIL {check['id']}: {check['detail']}\n")
    return 1 if result["verdict"] == _FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
