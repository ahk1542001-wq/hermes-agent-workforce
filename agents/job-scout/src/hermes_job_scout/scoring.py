"""Deterministic, evidence-backed ranking with an optional bounded reasoner."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from .models import (
    CandidateProfile,
    Decision,
    FitScore,
    JobRecord,
    JobState,
    SourceAuthority,
    WorkAuthLabel,
)

DEFAULT_WEIGHTS: dict[str, int] = {
    "skill_task_fit": 30,
    "experience_level_fit": 20,
    "location_work_auth_fit": 15,
    "source_quality_freshness": 15,
    "compensation_evidence": 10,
    "company_role_clarity": 10,
}
_SCORABLE_STATES = {
    JobState.QUALIFIED,
    JobState.SHORTLISTED,
    JobState.SELECTED,
    JobState.PACK_DRAFTED,
    JobState.PACK_REVIEWED,
    JobState.PACK_APPROVED,
    JobState.SUBMITTING,
    JobState.SUBMITTED,
    JobState.FOLLOW_UP_DUE,
    JobState.CLOSED,
}


@dataclass(frozen=True)
class ReasoningResult:
    """An explanation whose claims remain bound to extracted and approved evidence."""

    summary: str
    job_field_refs: tuple[str, ...]
    candidate_fact_ids: tuple[str, ...]
    skill_claims: tuple[str, ...] = ()


class FitReasoner(Protocol):
    """Optional explanation interface; deterministic scoring never depends on it."""

    def explain(self, job: JobRecord, profile: CandidateProfile) -> ReasoningResult: ...


def _normalized_set(values: list[str]) -> set[str]:
    return {" ".join(value.casefold().split()) for value in values}


def _validate_weights(weights: Mapping[str, int]) -> dict[str, int]:
    if set(weights) != set(DEFAULT_WEIGHTS):
        raise ValueError("weights must define every supported scoring criterion exactly once")
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in weights.values()
    ):
        raise ValueError("weights must be nonnegative integers")
    if sum(weights.values()) == 0:
        raise ValueError("at least one scoring weight must be nonzero")
    return {name: weights[name] for name in DEFAULT_WEIGHTS}


def _validate_reasoning(
    result: ReasoningResult,
    job: JobRecord,
    profile: CandidateProfile,
) -> None:
    job_fields = set(type(job).model_fields)
    approved_fact_ids = {fact.fact_id for fact in profile.facts if fact.verified}
    if not result.job_field_refs or not result.candidate_fact_ids:
        raise ValueError("unsupported reasoning evidence: citations cannot be empty")
    if not set(result.job_field_refs).issubset(job_fields):
        raise ValueError("unsupported reasoning evidence: unknown job field")
    if not set(result.candidate_fact_ids).issubset(approved_fact_ids):
        raise ValueError("unsupported reasoning evidence: unapproved candidate fact")

    supported_skills = _normalized_set([*job.skills, *profile.skills])
    unsupported = _normalized_set(list(result.skill_claims)) - supported_skills
    if unsupported:
        raise ValueError("unsupported skill in reasoning result")


def _component_scores(job: JobRecord, profile: CandidateProfile) -> dict[str, float | None]:
    job_skills = _normalized_set(job.skills)
    profile_skills = _normalized_set(profile.skills)
    skill_score: float | None
    if job_skills and profile_skills:
        skill_score = 100.0 if job_skills & profile_skills else 0.0
    else:
        skill_score = None

    experience_score = 100.0 if job.experience and profile.experience else None
    work_auth_score = (
        100.0
        if job.work_auth_label in {WorkAuthLabel.A_REMOTE_GLOBAL, WorkAuthLabel.B_THAI_SUPPORT}
        else None
    )
    source_scores = {
        SourceAuthority.OFFICIAL: 100.0,
        SourceAuthority.ATS: 100.0,
        SourceAuthority.API: 90.0,
        SourceAuthority.RSS: 85.0,
        SourceAuthority.USER_PROVIDED: 75.0,
        SourceAuthority.AGGREGATOR: 50.0,
        SourceAuthority.DISCOVERY_HINT: 0.0,
        SourceAuthority.NEEDS_VERIFICATION: 0.0,
    }
    compensation_score = 100.0 if job.salary_evidence else None
    company_clarity_score = 100.0 if job.company and job.role else None
    return {
        "skill_task_fit": skill_score,
        "experience_level_fit": experience_score,
        "location_work_auth_fit": work_auth_score,
        "source_quality_freshness": source_scores[job.authority],
        "compensation_evidence": compensation_score,
        "company_role_clarity": company_clarity_score,
    }


def score_job(
    job: JobRecord,
    profile: CandidateProfile,
    policy_version: str,
    *,
    weights: Mapping[str, int] = DEFAULT_WEIGHTS,
    reasoner: FitReasoner | None = None,
) -> FitScore:
    """Score one qualified record without requiring or trusting an LLM."""

    if not policy_version.strip():
        raise ValueError("policy_version cannot be blank")
    if job.state is JobState.REJECTED or job.owner_decision is Decision.REJECTED:
        raise ValueError("rejected records cannot be scored")
    if job.state not in _SCORABLE_STATES:
        raise ValueError("record must be in a qualified lifecycle state before scoring")

    ordered_weights = _validate_weights(weights)
    components = _component_scores(job, profile)
    configured_weight = sum(ordered_weights.values())
    known_weight = sum(
        ordered_weights[name]
        for name, score in components.items()
        if score is not None and ordered_weights[name] > 0
    )
    if known_weight == 0:
        raise ValueError("no scoring criterion has usable evidence")
    weighted_points = sum(
        ordered_weights[name] * score / 100
        for name, score in components.items()
        if score is not None
    )
    total_score = round(weighted_points / known_weight * 100, 2)
    evidence_coverage = round(known_weight / configured_weight * 100, 2)

    if reasoner is not None:
        explanation = reasoner.explain(job, profile)
        if not isinstance(explanation, ReasoningResult):
            raise ValueError("reasoner must return ReasoningResult")
        _validate_reasoning(explanation, job, profile)

    return FitScore(
        total_score=total_score,
        component_evidence={
            name: score
            for name, score in components.items()
            if score is not None and ordered_weights[name] > 0
        },
        policy_version=policy_version,
        evidence_coverage=evidence_coverage,
        provisional=evidence_coverage < 100,
    )


__all__ = ["DEFAULT_WEIGHTS", "FitReasoner", "ReasoningResult", "score_job"]
