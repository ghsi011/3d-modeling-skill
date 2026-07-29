from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _json_blocks(path: Path) -> list[dict[str, object]]:
    text = path.read_text(encoding="utf-8")
    return [json.loads(match) for match in re.findall(r"```json\s*(.*?)```", text, re.DOTALL)]


def _job_example(path: Path) -> dict[str, object]:
    examples = [payload for payload in _json_blocks(path) if payload.get("job_id") == "clip-01"]
    assert len(examples) == 1, f"expected one canonical clip job in {path}"
    return examples[0]


def test_canonical_job_example_declares_manufacturing_inputs() -> None:
    for path in (
        ROOT / "skills" / "roles" / "orchestrator.md",
        ROOT / "skills" / "3d-modeling" / "roles" / "orchestrator.md",
        ROOT / "docs" / "tooling.md",
    ):
        job = _job_example(path)
        assert job["printer"]
        assert job["material"]
        assert job["nozzle"]
        assert job["orientation"]


def test_run_job_docs_describe_the_required_manufacturing_inputs() -> None:
    tooling = (ROOT / "docs" / "tooling.md").read_text(encoding="utf-8")
    contracts = (ROOT / "skills" / "3d-modeling" / "references" / "team-contracts-v4.md").read_text(
        encoding="utf-8"
    )

    for field in ("printer", "material", "nozzle", "orientation"):
        assert f"`{field}`" in tooling
        assert f"`{field}`" in contracts

    assert "consequence` is required" in contracts
    assert "Legacy `risk_class`" in contracts
    assert "unknown frontmatter header field are validation errors" in contracts


def test_documented_review_routes_match_the_canonical_runner() -> None:
    role = (ROOT / "skills" / "roles" / "orchestrator.md").read_text(encoding="utf-8")
    contracts = (ROOT / "skills" / "3d-modeling" / "references" / "team-contracts-v4.md").read_text(
        encoding="utf-8"
    )
    tooling = (ROOT / "docs" / "tooling.md").read_text(encoding="utf-8")

    for text in (role, contracts, tooling):
        assert "INCONSEQUENTIAL` `DIRECT`" in text
        assert "CONSEQUENTIAL` `DIRECT`" in text
        assert "FITTED" in text and "FULL" in text

    assert "no review" in role
    assert "one mandatory safety" in role
    assert "For a certified `INCONSEQUENTIAL` `DIRECT` job" in role
    assert "no specialist dispatches" in role
    assert "specification review" in tooling
    assert "independent verification" in tooling

    assert "Consequence does not change the geometry route" in role
    assert "`FULL` retains both route-required reviews" in role


def test_obsolete_redesign_documents_are_not_part_of_the_release() -> None:
    """The live role/tooling docs are authoritative; the old design drafts are not."""
    assert not (ROOT / "docs" / "redesign-baseline.md").exists()
    assert not (ROOT / "docs" / "redesign-plan.md").exists()


def test_static_fit_guidance_uses_the_declared_plan_band() -> None:
    patterns = (ROOT / "skills" / "3d-modeling" / "references" / "verification-patterns.md").read_text(
        encoding="utf-8"
    )
    contracts = (ROOT / "skills" / "3d-modeling" / "references" / "team-contracts-v4.md").read_text(
        encoding="utf-8"
    )

    assert "must be ~0" not in patterns
    assert "declared interface band" in patterns
    assert "seated_clearance_mm" in patterns
    assert "assembly_overlap_budget_mm3" in patterns
    assert "No universal zero-interference rule" in contracts
    assert "static seated overlap/clearance" in contracts


def test_documentation_rejects_the_old_consequential_direct_policy() -> None:
    paths = (
        ROOT / "README.md",
        ROOT / "CHANGELOG.md",
        ROOT / "docs" / "tooling.md",
        ROOT / "skills" / "3d-modeling" / "references" / "team-contracts-v4.md",
        ROOT / "skills" / "roles" / "orchestrator.md",
        ROOT / "skills" / "3d-modeling" / "roles" / "orchestrator.md",
        ROOT / "skills" / "roles" / "verifier.md",
    )
    texts = [path.read_text(encoding="utf-8") for path in paths]
    combined = "\n".join(texts)

    # This was the closing-lane contradiction: it made every consequential job
    # require geometric verification, including certified DIRECT jobs.
    assert "For `CONSEQUENTIAL`, deliver only after the mandatory safety pass and" not in combined
    assert "consequence determines the geometry route" not in combined

    for text in texts:
        normalized = re.sub(r"\s+", " ", text)
        if "CONSEQUENTIAL" in normalized and "DIRECT" in normalized:
            assert "no normal geometric verifier" in normalized


def test_direct_dispatch_claims_are_qualified_as_inconsequential() -> None:
    paths = (
        ROOT / "README.md",
        ROOT / "CHANGELOG.md",
        ROOT / "skills" / "roles" / "orchestrator.md",
        ROOT / "skills" / "3d-modeling" / "roles" / "orchestrator.md",
    )

    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "One command, no dispatches" not in text
        assert "**You do the whole thing yourself. No dispatches.**" not in text
        for line in text.splitlines():
            if re.search(r"zero[- ]dispatch(?:es)?|no dispatches", line, re.IGNORECASE):
                assert "INCONSEQUENTIAL" in line.upper(), f"unqualified dispatch claim in {path}: {line}"


def test_orchestrator_direct_second_look_policy_is_not_overbroad() -> None:
    paths = (
        ROOT / "skills" / "roles" / "orchestrator.md",
        ROOT / "skills" / "3d-modeling" / "roles" / "orchestrator.md",
    )

    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "On `DIRECT` you dispatch nobody" not in text
        assert "No independent review context looks at" not in text
        assert "on `DIRECT` nobody else will" not in text
        assert "certified `INCONSEQUENTIAL` `DIRECT` job has **no review**" in text
        assert "certified `CONSEQUENTIAL` `DIRECT` job has exactly **one mandatory safety**" in text
        assert "no normal geometric verifier" in re.sub(r"\s+", " ", text)


def test_verifier_role_does_not_invent_a_direct_review() -> None:
    verifier = (ROOT / "skills" / "roles" / "verifier.md").read_text(encoding="utf-8")

    assert "canonical runner does not dispatch this role" in verifier
    assert "has no review callback" in verifier
    assert "does not create" in verifier and "canonical `DIRECT`" in verifier


def test_imported_solids_have_explicit_provenance_guidance() -> None:
    role = (ROOT / "skills" / "roles" / "orchestrator.md").read_text(encoding="utf-8")
    metrologist = (ROOT / "skills" / "roles" / "metrologist.md").read_text(encoding="utf-8")
    contracts = (ROOT / "skills" / "3d-modeling" / "references" / "team-contracts-v4.md").read_text(
        encoding="utf-8"
    )

    for text in (role, metrologist, contracts):
        assert "imported" in text
        assert "inherited" in text
        assert "chosen by design" in text


def test_changelog_does_not_claim_risk_class_survives() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "risk_class" not in changelog
