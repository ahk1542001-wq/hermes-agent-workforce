from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from hermes_job_scout.models import (
    CandidateFact,
    CandidateProfile,
    Decision,
    EvidenceRef,
    JobRecord,
    JobState,
    SourceAuthority,
    WorkAuthLabel,
    WorkType,
)
from hermes_job_scout.scoring import (
    DEFAULT_WEIGHTS,
    ReasoningResult,
    score_job,
)

NOW = datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc)


def _profile() -> CandidateProfile:
    claims = {
        "summary": "Builds evidence-backed AI automation workflows.",
        "skill_python": "Python",
        "skill_n8n": "n8n",
        "experience": "Built production automation workflows for small teams.",
    }
    facts = [
        CandidateFact(
            fact_id=fact_id,
            category="candidate",
            allowed_wording=wording,
            source="synthetic fixture",
            verified=True,
        )
        for fact_id, wording in claims.items()
    ]
    return CandidateProfile(
        candidate_id="synthetic-candidate",
        display_name="Synthetic Candidate",
        headline="AI Automation Engineer",
        summary=claims["summary"],
        facts=facts,
        skills=[claims["skill_python"], claims["skill_n8n"]],
        experience=[claims["experience"]],
    )


def _job(**updates: object) -> JobRecord:
    values: dict[str, object] = {
        "job_id": "score-job-1",
        "stable_url": "https://careers.example.com/jobs/score-1",
        "source_type": "official",
        "authority": SourceAuthority.OFFICIAL,
        "company": "Example Automation Labs",
        "role": "AI Automation Engineer",
        "first_seen_at": NOW - timedelta(days=2),
        "last_verified_at": NOW,
        "posted_at": NOW - timedelta(days=4),
        "closes_at": NOW + timedelta(days=20),
        "work_type": WorkType.FULL_TIME,
        "location": "Remote (Worldwide)",
        "remote_region": "Worldwide remote",
        "experience": "0-3 years",
        "language": ["English"],
        "skills": ["Python", "n8n"],
        "salary_evidence": [
            EvidenceRef(
                field="salary",
                excerpt="Salary range is published in the official listing.",
                source_url="https://careers.example.com/jobs/score-1",
                retrieved_at=NOW,
            )
        ],
        "work_authorization_evidence": [],
        "evidence_refs": [],
        "uncertainty_flags": [],
        "fingerprint": "b" * 64,
        "state": JobState.QUALIFIED,
        "owner_decision": Decision.NEEDS_VICTOR,
        "work_auth_label": WorkAuthLabel.A_REMOTE_GLOBAL,
    }
    values.update(updates)
    return JobRecord.model_validate(values)


def test_default_weights_are_exact_and_ordered() -> None:
    assert tuple(DEFAULT_WEIGHTS.items()) == (
        ("skill_task_fit", 30),
        ("experience_level_fit", 20),
        ("location_work_auth_fit", 15),
        ("source_quality_freshness", 15),
        ("compensation_evidence", 10),
        ("company_role_clarity", 10),
    )


def test_fully_evidenced_match_scores_100_with_stable_components() -> None:
    score = score_job(_job(), _profile(), "policy-v1")

    assert score.total_score == 100
    assert score.evidence_coverage == 100
    assert score.provisional is False
    assert score.policy_version == "policy-v1"
    assert tuple(score.component_evidence) == tuple(DEFAULT_WEIGHTS)
    assert score.component_evidence == {name: 100 for name in DEFAULT_WEIGHTS}


def test_unknown_nonzero_criteria_produce_provisional_normalized_score() -> None:
    score = score_job(_job(salary_evidence=[]), _profile(), "policy-v1")

    assert score.total_score == 100
    assert score.evidence_coverage == 90
    assert score.provisional is True
    assert "compensation_evidence" not in score.component_evidence


def test_known_mismatch_counts_as_zero_not_unknown() -> None:
    score = score_job(_job(skills=["Rust"]), _profile(), "policy-v1")

    assert score.component_evidence["skill_task_fit"] == 0
    assert score.total_score == 70
    assert score.evidence_coverage == 100
    assert score.provisional is False


def test_rejected_record_has_no_score() -> None:
    with pytest.raises(ValueError, match="rejected"):
        score_job(
            _job(state=JobState.REJECTED, owner_decision=Decision.REJECTED),
            _profile(),
            "policy-v1",
        )


def test_unqualified_discovered_record_has_no_score() -> None:
    with pytest.raises(ValueError, match="qualified lifecycle"):
        score_job(_job(state=JobState.DISCOVERED), _profile(), "policy-v1")


def test_explicit_owner_decision_survives_rescoring() -> None:
    job = _job(state=JobState.SHORTLISTED, owner_decision=Decision.QUALIFIED)

    score_job(
        job,
        _profile(),
        "policy-v2",
        weights={
            "skill_task_fit": 10,
            "experience_level_fit": 10,
            "location_work_auth_fit": 20,
            "source_quality_freshness": 20,
            "compensation_evidence": 20,
            "company_role_clarity": 20,
        },
    )

    assert job.state is JobState.SHORTLISTED
    assert job.owner_decision is Decision.QUALIFIED


class _UnsupportedSkillReasoner:
    def explain(self, job: JobRecord, profile: CandidateProfile) -> ReasoningResult:
        return ReasoningResult(
            summary="Invented experience",
            job_field_refs=("skills",),
            candidate_fact_ids=("skill_python",),
            skill_claims=("Kubernetes",),
        )


class _BoundedReasoner:
    def explain(self, job: JobRecord, profile: CandidateProfile) -> ReasoningResult:
        return ReasoningResult(
            summary="Python is supported by the listing and candidate evidence.",
            job_field_refs=("skills",),
            candidate_fact_ids=("skill_python",),
            skill_claims=("Python",),
        )


def test_reasoner_cannot_introduce_unsupported_skill() -> None:
    with pytest.raises(ValueError, match="unsupported skill"):
        score_job(_job(), _profile(), "policy-v1", reasoner=_UnsupportedSkillReasoner())


def test_bounded_reasoner_cites_existing_fields_and_approved_facts() -> None:
    score = score_job(_job(), _profile(), "policy-v1", reasoner=_BoundedReasoner())
    assert score.total_score == 100


@pytest.mark.parametrize(
    "result",
    [
        ReasoningResult(
            summary="Bad field",
            job_field_refs=("imaginary_field",),
            candidate_fact_ids=("skill_python",),
        ),
        ReasoningResult(
            summary="Bad fact",
            job_field_refs=("skills",),
            candidate_fact_ids=("imaginary_fact",),
        ),
    ],
)
def test_reasoner_must_reference_extracted_fields_and_approved_facts(
    result: ReasoningResult,
) -> None:
    class _Reasoner:
        def explain(self, job: JobRecord, profile: CandidateProfile) -> ReasoningResult:
            return result

    with pytest.raises(ValueError, match="unsupported reasoning evidence"):
        score_job(_job(), _profile(), "policy-v1", reasoner=_Reasoner())
