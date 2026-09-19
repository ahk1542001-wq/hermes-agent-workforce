from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from hermes_job_scout.models import (
    Decision,
    EvidenceRef,
    JobRecord,
    JobState,
    SearchPolicy,
    SourceAuthority,
    WorkAuthLabel,
    WorkType,
)
from hermes_job_scout.policy import (
    classify_work_authorization,
    evaluate_hard_filters,
)

NOW = datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc)
FIXTURES = Path(__file__).parent / "fixtures" / "jobs"


def _policy(**updates: object) -> SearchPolicy:
    values: dict[str, object] = {
        "policy_version": "2026-09-synthetic-v1",
        "headline": "AI Automation Engineer | Agentic Workflows & n8n",
        "role_aliases": [
            "AI automation engineer",
            "agentic workflow engineer",
            "n8n automation engineer",
        ],
        "geography_priority": [
            "worldwide remote",
            "APAC remote",
            "international remote",
            "Thailand",
        ],
        "allowed_work_types": [
            WorkType.FULL_TIME,
            WorkType.DIRECT_CONTRACT,
            WorkType.FREELANCE_CONTRACT,
            WorkType.PAID_INTERNSHIP,
        ],
        "accepted_languages": ["English", "Thai basic or optional"],
        "thai_level": "basic",
        "max_experience_years": 3,
        "freshness_days": 30,
        "excluded_seniority": ["senior", "lead", "principal"],
    }
    values.update(updates)
    return SearchPolicy.model_validate(values)


def _job(**updates: object) -> JobRecord:
    values: dict[str, object] = {
        "job_id": "synthetic-job-1",
        "stable_url": "https://careers.example.com/jobs/1",
        "source_type": "official",
        "authority": SourceAuthority.OFFICIAL,
        "company": "Example Automation Labs",
        "role": "AI Automation Engineer",
        "first_seen_at": NOW - timedelta(days=1),
        "last_verified_at": NOW,
        "posted_at": NOW - timedelta(days=2),
        "closes_at": NOW + timedelta(days=10),
        "work_type": WorkType.FULL_TIME,
        "location": "Remote (Worldwide)",
        "remote_region": "Worldwide remote",
        "experience": "0-3 years",
        "language": ["English"],
        "skills": ["Python", "n8n", "agentic workflows"],
        "salary_evidence": [],
        "work_authorization_evidence": [],
        "evidence_refs": [],
        "uncertainty_flags": [],
        "fingerprint": "a" * 64,
        "state": JobState.DISCOVERED,
        "owner_decision": Decision.NEEDS_VICTOR,
        "work_auth_label": None,
    }
    values.update(updates)
    return JobRecord.model_validate(values)


def _support_evidence() -> list[EvidenceRef]:
    return [
        EvidenceRef(
            field="work_authorization",
            excerpt="We welcome foreign applicants and provide visa and work-permit support.",
            source_url="https://careers.example.com/jobs/thai-1",
            retrieved_at=NOW,
        )
    ]


def test_accepted_ai_automation_role_is_qualified_with_salary_uncertainty() -> None:
    result = evaluate_hard_filters(_job(), _policy(), NOW)

    assert result.decision is Decision.QUALIFIED
    assert result.work_auth_label is WorkAuthLabel.A_REMOTE_GLOBAL
    assert result.reason_codes == ("SALARY_UNKNOWN",)
    assert result.uncertainty_flags == ("SALARY_UNKNOWN",)


def test_paid_internship_and_direct_contract_are_allowed() -> None:
    for work_type in (WorkType.PAID_INTERNSHIP, WorkType.DIRECT_CONTRACT):
        result = evaluate_hard_filters(_job(work_type=work_type), _policy(), NOW)
        assert result.decision is Decision.QUALIFIED


def test_thai_sponsorship_is_labeled_and_requires_explicit_evidence() -> None:
    job = _job(
        location="Bangkok, Thailand",
        remote_region="Thailand",
        work_authorization_evidence=_support_evidence(),
    )

    assert classify_work_authorization(job) is WorkAuthLabel.B_THAI_SUPPORT
    result = evaluate_hard_filters(job, _policy(), NOW)
    assert result.decision is Decision.QUALIFIED
    assert result.work_auth_label is WorkAuthLabel.B_THAI_SUPPORT


def test_missing_thai_sponsorship_is_uncertain_not_legal_eligibility() -> None:
    job = _job(location="Bangkok, Thailand", remote_region="Thailand")

    assert classify_work_authorization(job) is WorkAuthLabel.C_THAI_UNKNOWN
    result = evaluate_hard_filters(job, _policy(), NOW)
    assert result.decision is Decision.NEEDS_VICTOR
    assert result.work_auth_label is WorkAuthLabel.C_THAI_UNKNOWN
    assert "WORK_AUTH_UNCONFIRMED" in result.reason_codes


def test_mid_level_role_is_qualified_only_as_stretch() -> None:
    result = evaluate_hard_filters(
        _job(role="Mid-level AI Automation Engineer", experience="3-5 years"),
        _policy(),
        NOW,
    )

    assert result.decision is Decision.QUALIFIED
    assert result.labels == ("STRETCH",)
    assert result.reason_codes[:1] == ("STRETCH_ROLE",)


def test_non_ai_role_is_rejected() -> None:
    result = evaluate_hard_filters(_job(role="Customer Support Specialist"), _policy(), NOW)
    assert result.decision is Decision.REJECTED
    assert result.reason_codes == ("NON_AI_ROLE",)


def test_fluent_thai_is_rejected() -> None:
    result = evaluate_hard_filters(_job(language=["English", "Thai fluent"]), _policy(), NOW)
    assert result.decision is Decision.REJECTED
    assert result.reason_codes == ("THAI_FLUENT_REQUIRED",)


def test_senior_role_is_rejected() -> None:
    result = evaluate_hard_filters(_job(role="Senior AI Automation Engineer"), _policy(), NOW)
    assert result.decision is Decision.REJECTED
    assert result.reason_codes == ("EXCLUDED_SENIORITY",)


def test_experience_above_policy_is_rejected() -> None:
    result = evaluate_hard_filters(_job(experience="4+ years"), _policy(), NOW)
    assert result.decision is Decision.REJECTED
    assert result.reason_codes == ("EXPERIENCE_TOO_HIGH",)


def test_expired_role_is_rejected() -> None:
    result = evaluate_hard_filters(_job(closes_at=NOW - timedelta(minutes=1)), _policy(), NOW)
    assert result.decision is Decision.REJECTED
    assert result.reason_codes == ("EXPIRED",)


def test_fake_company_is_rejected() -> None:
    result = evaluate_hard_filters(_job(company="Fake Company Ltd"), _policy(), NOW)
    assert result.decision is Decision.REJECTED
    assert result.reason_codes == ("COMPANY_NOT_CREDIBLE",)


def test_unsupported_geography_is_rejected() -> None:
    result = evaluate_hard_filters(
        _job(location="Paris, France", remote_region="France"), _policy(), NOW
    )
    assert result.decision is Decision.REJECTED
    assert result.reason_codes == ("GEOGRAPHY_UNSUPPORTED",)


def test_unpaid_internship_is_rejected() -> None:
    result = evaluate_hard_filters(
        _job(role="Unpaid AI Automation Internship", work_type=WorkType.PAID_INTERNSHIP),
        _policy(),
        NOW,
    )
    assert result.decision is Decision.REJECTED
    assert result.reason_codes == ("UNPAID_INTERNSHIP",)


@pytest.mark.parametrize(
    "authority", [SourceAuthority.DISCOVERY_HINT, SourceAuthority.NEEDS_VERIFICATION]
)
def test_discovery_hint_cannot_qualify(authority: SourceAuthority) -> None:
    result = evaluate_hard_filters(
        _job(authority=authority, source_type=authority.value), _policy(), NOW
    )
    assert result.decision is Decision.NEEDS_VICTOR
    assert result.reason_codes == ("SOURCE_UNVERIFIED",)


def test_prompt_injection_is_data() -> None:
    payload = json.loads((FIXTURES / "prompt_injection.json").read_text(encoding="utf-8"))
    raw_evidence = payload["evidence_refs"][0]
    raw_evidence["retrieved_at"] = datetime.fromisoformat(
        raw_evidence["retrieved_at"].replace("Z", "+00:00")
    )
    job = _job(evidence_refs=[EvidenceRef.model_validate(raw_evidence)])

    result = evaluate_hard_filters(job, _policy(), NOW)

    assert result.decision is Decision.QUALIFIED
    assert result.reason_codes == ("SALARY_UNKNOWN",)


@pytest.mark.parametrize(
    ("fixture_name", "expected_decision", "expected_reason"),
    [
        ("contradictory_experience.json", Decision.REJECTED, "EXPERIENCE_TOO_HIGH"),
        ("stale_aggregator.json", Decision.NEEDS_VICTOR, "SOURCE_UNVERIFIED"),
        ("company_alias_collision.json", Decision.QUALIFIED, "SALARY_UNKNOWN"),
    ],
)
def test_ambiguity_mutations_have_explicit_outcomes(
    fixture_name: str, expected_decision: Decision, expected_reason: str
) -> None:
    payload = json.loads((FIXTURES / fixture_name).read_text(encoding="utf-8"))
    authority = SourceAuthority(payload.get("authority", "official"))
    job = _job(
        authority=authority,
        source_type=authority.value,
        company=payload.get("company", "Example Automation Labs"),
        role=payload.get("role", "AI Automation Engineer"),
        experience=payload.get("experience", "0-3 years"),
    )
    result = evaluate_hard_filters(job, _policy(), NOW)
    assert result.decision is expected_decision
    assert result.reason_codes[0] == expected_reason
