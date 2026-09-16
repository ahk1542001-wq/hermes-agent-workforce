import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from hermes_job_scout.models import (
    ApprovalGrant,
    CandidateEvidencePack,
    CandidateProfile,
    Decision,
    DiscoveryHint,
    DiscoveryRun,
    EvidenceRef,
    FitScore,
    JobRecord,
    JobState,
    SearchPolicy,
    SourceAuthority,
    SourceRecord,
    WorkspaceMarker,
    WorkType,
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


@pytest.mark.parametrize("value", [-1, 101, float("nan"), "50"])
def test_fit_score_component_values_are_finite_bounded_numbers(value: object) -> None:
    with pytest.raises(ValidationError):
        FitScore(
            total_score=72,
            component_evidence={"skill_fit": value},
            policy_version="2026-09-v1",
            evidence_coverage=80,
            provisional=True,
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
    with pytest.raises(ValidationError):
        DiscoveryHint(
            provider="synthetic-search",
            query="AI automation engineer remote",
            title="AI Automation Engineer",
            url="https://example.com/jobs/automation",
            position=1,
            retrieved_at=NOW,
            authority=SourceAuthority.OFFICIAL,
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
            run_id="run-synthetic-empty-source",
            started_at=NOW,
            completed_at=NOW,
            coverage="full",
            checked_source_ids=[""],
            failed_source_ids=[],
            changed_count=0,
            provider="synthetic-search",
            actual_search_retrieval_spend_usd=0,
        )
    with pytest.raises(ValidationError):
        DiscoveryRun(
            run_id="run-synthetic-duplicate-failed",
            started_at=NOW,
            completed_at=NOW,
            coverage="partial",
            checked_source_ids=["source-a"],
            failed_source_ids=["source-a", "source-a"],
            changed_count=0,
            provider="synthetic-search",
            actual_search_retrieval_spend_usd=0,
        )
    with pytest.raises(ValidationError):
        DiscoveryRun(
            run_id="run-synthetic-empty-failed",
            started_at=NOW,
            completed_at=NOW,
            coverage="partial",
            checked_source_ids=["source-a"],
            failed_source_ids=[""],
            changed_count=0,
            provider="synthetic-search",
            actual_search_retrieval_spend_usd=0,
        )
    with pytest.raises(ValidationError):
        DiscoveryRun(
            run_id="run-synthetic-empty-provider",
            started_at=NOW,
            completed_at=NOW,
            coverage="full",
            checked_source_ids=["source-a"],
            failed_source_ids=[],
            changed_count=0,
            provider="",
            actual_search_retrieval_spend_usd=0,
        )


def test_discovery_run_records_auditable_result_and_tool_counts() -> None:
    run = DiscoveryRun(
        run_id="run-synthetic-audit",
        started_at=NOW,
        completed_at=NOW,
        coverage="full",
        checked_source_ids=["source-a"],
        changed_count=0,
        result_count=4,
        tokens_used=120,
        tool_calls=2,
        free_credits_remaining={"search": 20},
        provider="synthetic-search",
        actual_search_retrieval_spend_usd=0,
    )
    assert run.result_count == 4
    with pytest.raises(ValidationError):
        DiscoveryRun(
            run_id="run-synthetic-bad-audit",
            started_at=NOW,
            completed_at=NOW,
            coverage="full",
            checked_source_ids=["source-a"],
            changed_count=0,
            result_count=-1,
            tokens_used=-1,
            tool_calls=-1,
            free_credits_remaining={"search": -1},
            provider="synthetic-search",
            actual_search_retrieval_spend_usd=0,
        )
    with pytest.raises(ValidationError):
        DiscoveryRun(
            run_id="run-synthetic-string-audit",
            started_at=NOW,
            completed_at=NOW,
            coverage="full",
            checked_source_ids=["source-a"],
            changed_count=0,
            result_count="4",
            tokens_used="2",
            tool_calls="1",
            free_credits_remaining={"search": "20"},
            provider="synthetic-search",
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
            provider="synthetic-search",
            actual_search_retrieval_spend_usd=0,
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"coverage": "unknown"},
        {"failed_source_ids": ["source-b"]},
        {"completed_at": NOW - timedelta(seconds=1)},
    ],
)
def test_discovery_run_rejects_invalid_run_relationships(overrides: dict[str, object]) -> None:
    payload: dict[str, object] = {
        "run_id": "run-invalid-relationship",
        "started_at": NOW,
        "completed_at": NOW,
        "coverage": "full",
        "checked_source_ids": ["source-a"],
        "failed_source_ids": [],
        "changed_count": 0,
        "provider": "synthetic-search",
    }
    payload.update(overrides)
    with pytest.raises(ValidationError):
        DiscoveryRun.model_validate(payload)


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
    with pytest.raises(ValidationError):
        ApprovalGrant(
            approval_id="approval-2",
            job_id="job-1",
            recipient="jobs@example.com",
            payload_sha256="a" * 64,
            attachment_sha256=["not-a-sha256"],
            issued_at=issued,
            expires_at=issued + timedelta(hours=1),
        )
    with pytest.raises(ValidationError):
        ApprovalGrant(
            approval_id="approval-3",
            job_id="job-1",
            recipient="jobs@example.com",
            payload_sha256="a" * 64,
            issued_at=issued,
            expires_at=issued,
        )


def test_naive_model_timestamp_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EvidenceRef(
            field="role",
            excerpt="AI automation",
            source_url="https://example.com/jobs/automation",
            retrieved_at=datetime(2026, 9, 15, 8, 0),
        )


def test_source_and_job_timestamps_cannot_move_backwards() -> None:
    with pytest.raises(ValidationError):
        SourceRecord(
            source_id="source-1",
            organization="Example Automation Labs",
            source_type="official",
            url="https://example.com/jobs",
            status="healthy",
            last_checked_at=NOW,
            last_success_at=NOW + timedelta(minutes=1),
        )
    with pytest.raises(ValidationError):
        JobRecord(
            job_id="job-1",
            stable_url="https://example.com/jobs/automation",
            source_type="official",
            authority=SourceAuthority.OFFICIAL,
            company="Example Automation Labs",
            role="AI Automation Engineer",
            first_seen_at=NOW + timedelta(days=1),
            last_verified_at=NOW,
            location="Worldwide",
            remote_region="global",
            experience="0-3 years",
            fingerprint="a" * 64,
            work_type=WorkType.FULL_TIME,
        )

    with pytest.raises(ValidationError, match="posted.*closing|closes"):
        JobRecord(
            job_id="job-2",
            stable_url="https://example.com/jobs/automation-2",
            source_type="official",
            authority=SourceAuthority.OFFICIAL,
            company="Example Automation Labs",
            role="AI Automation Engineer",
            first_seen_at=NOW,
            last_verified_at=NOW,
            posted_at=NOW + timedelta(days=2),
            closes_at=NOW + timedelta(days=1),
            work_type=WorkType.FULL_TIME,
            location="Worldwide",
            remote_region="global",
            experience="0-3 years",
            fingerprint="b" * 64,
        )


@pytest.mark.parametrize(
    ("state", "decision"),
    [
        (JobState.VERIFIED, Decision.NEEDS_VICTOR),
        (JobState.DISCOVERED, Decision.QUALIFIED),
    ],
)
def test_unverified_authority_cannot_be_verified_or_qualified(
    state: JobState, decision: Decision
) -> None:
    with pytest.raises(ValidationError, match="unverified source authority"):
        JobRecord.model_validate(
            {
                "job_id": "job-unverified",
                "stable_url": "https://www.linkedin.com/jobs/view/1",
                "source_type": "discovery_hint",
                "authority": SourceAuthority.DISCOVERY_HINT,
                "company": "Example Automation Labs",
                "role": "AI Automation Engineer",
                "first_seen_at": NOW,
                "last_verified_at": NOW,
                "work_type": WorkType.FULL_TIME,
                "location": "Worldwide",
                "remote_region": "global",
                "experience": "0-3 years",
                "fingerprint": "c" * 64,
                "state": state,
                "owner_decision": decision,
            }
        )


def test_candidate_evidence_pack_is_strict_and_schema_versioned() -> None:
    payload = json.loads((EXAMPLES / "evidence_pack.synthetic.json").read_text(encoding="utf-8"))
    pack = CandidateEvidencePack.model_validate(payload)
    assert pack.schema_version == 1
    payload["unexpected"] = "no"
    with pytest.raises(ValidationError):
        CandidateEvidencePack.model_validate(payload)


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
    assert CandidateEvidencePack.model_validate(payload).candidate_profile.facts


def test_candidate_profile_rejects_unsupported_free_form_claims() -> None:
    payload = json.loads(
        (EXAMPLES / "candidate_profile.synthetic.json").read_text(encoding="utf-8")
    )
    payload["unapproved_claim"] = "I invented a credential"
    with pytest.raises(ValidationError):
        CandidateProfile.model_validate(payload)


def test_candidate_profile_rejects_unverified_or_unbound_claims_and_duplicates() -> None:
    payload = json.loads(
        (EXAMPLES / "candidate_profile.synthetic.json").read_text(encoding="utf-8")
    )
    payload["facts"][2]["verified"] = False
    with pytest.raises(ValidationError):
        CandidateProfile.model_validate(payload)

    payload = json.loads(
        (EXAMPLES / "candidate_profile.synthetic.json").read_text(encoding="utf-8")
    )
    payload["skills"][0] = "Unsupported cloud credential"
    with pytest.raises(ValidationError):
        CandidateProfile.model_validate(payload)

    payload = json.loads(
        (EXAMPLES / "candidate_profile.synthetic.json").read_text(encoding="utf-8")
    )
    payload["facts"].append(payload["facts"][0])
    with pytest.raises(ValidationError):
        CandidateProfile.model_validate(payload)


def test_candidate_profile_languages_must_be_verified_claims() -> None:
    payload = json.loads(
        (EXAMPLES / "candidate_profile.synthetic.json").read_text(encoding="utf-8")
    )
    payload["languages"]["French"] = "native"
    with pytest.raises(ValidationError):
        CandidateProfile.model_validate(payload)
