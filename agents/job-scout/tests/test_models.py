import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from hermes_job_scout.models import (
    ApprovalGrant,
    CandidateProfile,
    DiscoveryHint,
    DiscoveryRun,
    EvidenceRef,
    FitScore,
    SearchPolicy,
    WorkspaceMarker,
)

EXAMPLES = Path(__file__).parents[1] / "examples"
NOW = datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc)


def test_workspace_marker_is_versioned_and_contains_no_path_or_personal_fields() -> None:
    marker = WorkspaceMarker(
        marker_version=1,
        workspace_id=UUID("11111111-1111-4111-8111-111111111111"),
        schema_version=1,
    )
    assert marker.marker_version == 1
    with pytest.raises(ValidationError):
        WorkspaceMarker(
            marker_version=2,
            workspace_id=marker.workspace_id,
            schema_version=1,
        )
    with pytest.raises(ValidationError):
        WorkspaceMarker(
            marker_version=1,
            workspace_id=marker.workspace_id,
            schema_version=1,
            path="/private",
        )


def test_scores_and_coverage_are_bounded_and_provisional_is_derived() -> None:
    score = FitScore(
        total_score=72,
        component_evidence={"skill_fit": 22},
        policy_version="2026-09-v1",
        evidence_coverage=80,
        provisional=True,
    )
    assert score.provisional is True
    with pytest.raises(ValidationError):
        FitScore(
            total_score=101,
            component_evidence={},
            policy_version="2026-09-v1",
            evidence_coverage=100,
            provisional=False,
        )
    with pytest.raises(ValidationError):
        FitScore(
            total_score=72,
            component_evidence={},
            policy_version="2026-09-v1",
            evidence_coverage=80,
            provisional=False,
        )


def test_evidence_excerpt_requires_source_url_and_retrieval_time() -> None:
    with pytest.raises(ValidationError):
        EvidenceRef(field="role", excerpt="AI automation", source_url=None, retrieved_at=None)
    ref = EvidenceRef(
        field="role",
        excerpt="AI automation engineer",
        source_url="https://example.com/jobs/automation",
        retrieved_at=NOW,
    )
    assert ref.source_url is not None


def test_discovery_hint_cannot_claim_official_verification() -> None:
    hint = DiscoveryHint(
        provider="synthetic-search",
        query="AI automation engineer remote",
        title="AI Automation Engineer",
        url="https://example.com/jobs/automation",
        description="Synthetic discovery result.",
        position=1,
        retrieved_at=NOW,
    )
    assert hint.authority.value == "discovery_hint"
    with pytest.raises(ValidationError):
        DiscoveryHint(
            provider="synthetic-search",
            query="AI automation engineer remote",
            title="AI Automation Engineer",
            url="https://example.com/jobs/automation",
            description="Synthetic discovery result.",
            position=1,
            retrieved_at=NOW,
            authority="official",
        )


def test_discovery_run_has_explicit_coverage_unique_sources_and_zero_spend() -> None:
    run = DiscoveryRun(
        run_id="run-synthetic-1",
        started_at=NOW,
        completed_at=NOW + timedelta(minutes=2),
        coverage="partial",
        checked_source_ids=["source-a", "source-b"],
        failed_source_ids=["source-b"],
        changed_count=3,
        provider="synthetic-search",
        query_count=2,
        pages_checked=1,
        cache_hits=1,
        actual_search_retrieval_spend_usd=0,
    )
    assert run.actual_search_retrieval_spend_usd == 0
    with pytest.raises(ValidationError):
        DiscoveryRun(
            run_id="run-synthetic-2",
            started_at=NOW,
            completed_at=NOW,
            coverage="full",
            checked_source_ids=["source-a", "source-a"],
            failed_source_ids=["source-a"],
            changed_count=0,
            actual_search_retrieval_spend_usd=0,
        )
    with pytest.raises(ValidationError):
        DiscoveryRun(
            run_id="run-synthetic-3",
            started_at=NOW,
            completed_at=NOW,
            coverage="partial",
            checked_source_ids=["source-a"],
            failed_source_ids=["source-b"],
            changed_count=-1,
            actual_search_retrieval_spend_usd=0,
        )


def test_approval_cannot_exceed_24_hours() -> None:
    issued = datetime(2026, 9, 15, tzinfo=timezone.utc)
    with pytest.raises(ValidationError):
        ApprovalGrant(
            approval_id="approval-1",
            job_id="job-1",
            recipient="jobs@example.com",
            payload_sha256="a" * 64,
            attachment_sha256=["b" * 64],
            issued_at=issued,
            expires_at=issued + timedelta(hours=25),
        )


def test_all_synthetic_examples_load_through_models() -> None:
    profile = CandidateProfile.model_validate_json(
        (EXAMPLES / "candidate_profile.synthetic.json").read_text(encoding="utf-8")
    )
    SearchPolicy.model_validate_json(
        (EXAMPLES / "search_policy.synthetic.json").read_text(encoding="utf-8")
    )
    assert profile.headline == "AI Automation Engineer | Agentic Workflows & n8n"
    assert profile.languages["Thai"] == "basic"

    payload = json.loads((EXAMPLES / "evidence_pack.synthetic.json").read_text(encoding="utf-8"))
    assert CandidateProfile.model_validate(payload["candidate_profile"]).facts


def test_candidate_profile_rejects_unsupported_free_form_claims() -> None:
    payload = json.loads(
        (EXAMPLES / "candidate_profile.synthetic.json").read_text(encoding="utf-8")
    )
    payload["unapproved_claim"] = "I invented a credential"
    with pytest.raises(ValidationError):
        CandidateProfile.model_validate(payload)
