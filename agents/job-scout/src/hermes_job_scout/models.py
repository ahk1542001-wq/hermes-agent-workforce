"""Strict, provider-neutral contracts for the Job Scout public package."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)


class StrictModel(BaseModel):
    """Common model policy: unknown fields are never silently accepted."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        str_strip_whitespace=True,
    )

    @field_validator("*", mode="after")
    @classmethod
    def _timestamps_must_be_aware(cls, value: Any) -> Any:
        if isinstance(value, datetime) and value.utcoffset() is None:
            raise ValueError("timestamps must include a timezone")
        return value


class JobState(StrEnum):
    DISCOVERED = "discovered"
    VERIFIED = "verified"
    QUALIFIED = "qualified"
    SHORTLISTED = "shortlisted"
    SELECTED = "selected"
    PACK_DRAFTED = "pack_drafted"
    PACK_REVIEWED = "pack_reviewed"
    PACK_APPROVED = "pack_approved"
    SUBMITTING = "submitting"
    SUBMITTED = "submitted"
    FOLLOW_UP_DUE = "follow_up_due"
    CLOSED = "closed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    DUPLICATE = "duplicate"
    NEEDS_VICTOR = "needs_victor"
    FAILED_UNCONFIRMED = "failed_unconfirmed"
    WITHDRAWN = "withdrawn"
    ARCHIVED = "archived"


class SourceAuthority(StrEnum):
    OFFICIAL = "official"
    ATS = "ats"
    RSS = "rss"
    API = "api"
    AGGREGATOR = "aggregator"
    DISCOVERY_HINT = "discovery_hint"
    USER_PROVIDED = "user_provided"


class WorkAuthLabel(StrEnum):
    A_REMOTE_GLOBAL = "A_REMOTE_GLOBAL"
    B_THAI_SUPPORT = "B_THAI_SUPPORT"
    C_THAI_UNKNOWN = "C_THAI_UNKNOWN"


class WorkType(StrEnum):
    FULL_TIME = "full_time"
    DIRECT_CONTRACT = "direct_contract"
    FREELANCE_CONTRACT = "freelance_contract"
    PAID_INTERNSHIP = "paid_internship"


class Decision(StrEnum):
    QUALIFIED = "qualified"
    REJECTED = "rejected"
    NEEDS_VICTOR = "needs_victor"


class CandidateFact(StrictModel):
    fact_id: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=80)
    allowed_wording: str = Field(min_length=1, max_length=500)
    source: str = Field(min_length=1, max_length=500)
    verified: bool
    metric_evidence: str | None = Field(default=None, max_length=500)


class CandidateProfile(StrictModel):
    candidate_id: str = Field(min_length=1, max_length=120)
    display_name: str = Field(min_length=1, max_length=120)
    headline: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=1_000)
    facts: list[CandidateFact] = Field(min_length=1)
    skills: list[str] = Field(default_factory=list)
    languages: dict[str, str] = Field(default_factory=dict)
    experience: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _claims_are_verified_and_bound(self) -> CandidateProfile:
        fact_ids = [fact.fact_id for fact in self.facts]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("fact IDs must be unique")
        allowed_wording = {fact.allowed_wording for fact in self.facts if fact.verified}
        language_claims = [f"{language}: {level}" for language, level in self.languages.items()]
        claims = [
            self.summary,
            *self.skills,
            *self.experience,
            *self.education,
            *language_claims,
        ]
        if len(claims) != len(set(claims)):
            raise ValueError("profile claims must be unique")
        unsupported = [claim for claim in claims if claim not in allowed_wording]
        if unsupported:
            raise ValueError("profile claims must reference verified allowed wording")
        return self


class CandidateEvidencePack(StrictModel):
    pack_id: str = Field(min_length=1, max_length=120)
    schema_version: int = Field(default=1, ge=1, le=1)
    source_note: str = Field(min_length=1, max_length=500)
    candidate_profile: CandidateProfile


class SearchPolicy(StrictModel):
    policy_version: str = Field(min_length=1, max_length=80)
    headline: str = Field(min_length=1, max_length=160)
    role_aliases: list[str] = Field(min_length=1)
    geography_priority: list[str] = Field(min_length=1)
    allowed_work_types: list[WorkType] = Field(min_length=1)
    accepted_languages: list[str] = Field(min_length=1)
    thai_level: str = "basic"
    max_experience_years: int = Field(default=3, ge=0)
    freshness_days: int = Field(default=30, ge=1)
    cash_budget_usd: float = Field(default=0, ge=0, le=0)
    excluded_seniority: list[str] = Field(default_factory=lambda: ["senior", "lead"])


class DiscoveryHint(StrictModel):
    provider: str = Field(min_length=1, max_length=100)
    query: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=300)
    url: HttpUrl
    description: str = Field(default="", max_length=2_000)
    position: int = Field(ge=1)
    retrieved_at: datetime
    authority: SourceAuthority = SourceAuthority.DISCOVERY_HINT

    @field_validator("authority")
    @classmethod
    def _must_remain_a_hint(cls, value: SourceAuthority) -> SourceAuthority:
        if value is not SourceAuthority.DISCOVERY_HINT:
            raise ValueError("a discovery hint cannot claim official verification")
        return value


class ExtractedSource(StrictModel):
    provider: str = Field(min_length=1, max_length=100)
    url: HttpUrl
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(max_length=20_000)
    retrieved_at: datetime
    content_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    metadata: dict[str, str] = Field(default_factory=dict)
    extraction_error: str | None = Field(default=None, max_length=300)
    authority: SourceAuthority


class SourceRecord(StrictModel):
    source_id: str = Field(min_length=1, max_length=120)
    organization: str = Field(min_length=1, max_length=200)
    source_type: str = Field(min_length=1, max_length=80)
    url: HttpUrl
    status: str = Field(min_length=1, max_length=40)
    last_checked_at: datetime
    last_success_at: datetime | None = None
    last_changed_at: datetime | None = None
    last_error_code: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def _health_timestamps_are_ordered(self) -> SourceRecord:
        for timestamp in (self.last_success_at, self.last_changed_at):
            if timestamp is not None and timestamp > self.last_checked_at:
                raise ValueError("source health timestamps cannot exceed last checked time")
        return self


class DiscoveryRun(StrictModel):
    run_id: str = Field(min_length=1, max_length=120)
    started_at: datetime
    completed_at: datetime
    coverage: str
    checked_source_ids: list[str] = Field(min_length=1)
    failed_source_ids: list[str] = Field(default_factory=list)
    changed_count: int = Field(ge=0)
    result_count: int = Field(default=0, ge=0)
    tokens_used: int | None = Field(default=None, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    provider: str = Field(min_length=1, max_length=100)
    query_count: int = Field(default=0, ge=0)
    pages_checked: int = Field(default=0, ge=0)
    cache_hits: int = Field(default=0, ge=0)
    free_credits_remaining: dict[str, int] = Field(default_factory=dict)
    model_calls: int = Field(default=0, ge=0)
    actual_search_retrieval_spend_usd: float = Field(default=0, ge=0, le=0)

    @field_validator("coverage")
    @classmethod
    def _coverage_is_explicit(cls, value: str) -> str:
        if value not in {"full", "partial"}:
            raise ValueError("coverage must be 'full' or 'partial'")
        return value

    @field_validator("checked_source_ids")
    @classmethod
    def _checked_sources_are_unique(cls, value: list[str]) -> list[str]:
        if any(not source_id for source_id in value):
            raise ValueError("source IDs cannot be blank")
        if len(value) != len(set(value)):
            raise ValueError("checked source IDs must be unique")
        return value

    @field_validator("failed_source_ids")
    @classmethod
    def _failed_sources_are_unique_and_nonblank(cls, value: list[str]) -> list[str]:
        if any(not source_id for source_id in value):
            raise ValueError("source IDs cannot be blank")
        if len(value) != len(set(value)):
            raise ValueError("failed source IDs must be unique")
        return value

    @model_validator(mode="after")
    def _failed_sources_were_checked(self) -> DiscoveryRun:
        if not set(self.failed_source_ids).issubset(self.checked_source_ids):
            raise ValueError("failed source IDs must be a subset of checked source IDs")
        if self.completed_at < self.started_at:
            raise ValueError("completion cannot precede start")
        return self

    @field_validator("free_credits_remaining")
    @classmethod
    def _credits_are_nonnegative(cls, value: dict[str, int]) -> dict[str, int]:
        if any(credit < 0 for credit in value.values()):
            raise ValueError("free credits remaining cannot be negative")
        return value


class EvidenceRef(StrictModel):
    field: str = Field(min_length=1, max_length=120)
    excerpt: str | None = Field(default=None, max_length=1_000)
    source_url: AnyHttpUrl | None = None
    retrieved_at: datetime | None = None

    @model_validator(mode="after")
    def _excerpt_needs_provenance(self) -> EvidenceRef:
        if self.excerpt is not None and (self.source_url is None or self.retrieved_at is None):
            raise ValueError("evidence excerpts require source URL and retrieval timestamp")
        return self


class JobRecord(StrictModel):
    job_id: str = Field(min_length=1, max_length=120)
    stable_url: HttpUrl
    source_type: str = Field(min_length=1, max_length=80)
    authority: SourceAuthority
    company: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=300)
    first_seen_at: datetime
    last_verified_at: datetime
    posted_at: datetime | None = None
    closes_at: datetime | None = None
    work_type: WorkType
    location: str = Field(min_length=1, max_length=200)
    remote_region: str = Field(min_length=1, max_length=120)
    experience: str = Field(min_length=1, max_length=500)
    language: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    salary_evidence: list[EvidenceRef] = Field(default_factory=list)
    work_authorization_evidence: list[EvidenceRef] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    uncertainty_flags: list[str] = Field(default_factory=list)
    fingerprint: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    state: JobState = JobState.DISCOVERED
    owner_decision: Decision = Decision.NEEDS_VICTOR
    work_auth_label: WorkAuthLabel | None = None

    @model_validator(mode="after")
    def _verification_follows_first_seen(self) -> JobRecord:
        if self.first_seen_at > self.last_verified_at:
            raise ValueError("first seen timestamp cannot exceed last verified timestamp")
        if (
            self.posted_at is not None
            and self.closes_at is not None
            and self.posted_at > self.closes_at
        ):
            raise ValueError("posted_at cannot exceed closes_at")
        return self


class FitScore(StrictModel):
    total_score: float = Field(ge=0, le=100)
    component_evidence: dict[str, Annotated[float, Field(ge=0, le=100)]] = Field(
        default_factory=dict
    )
    policy_version: str = Field(min_length=1, max_length=80)
    evidence_coverage: float = Field(ge=0, le=100)
    provisional: bool

    @model_validator(mode="after")
    def _provisional_matches_coverage(self) -> FitScore:
        if self.provisional != (self.evidence_coverage < 100):
            raise ValueError("provisional must equal whether evidence coverage is below 100")
        return self


class ApprovalGrant(StrictModel):
    approval_id: str = Field(min_length=1, max_length=120)
    job_id: str = Field(min_length=1, max_length=120)
    recipient: str = Field(min_length=3, max_length=320)
    payload_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    attachment_sha256: list[str] = Field(default_factory=list)
    issued_at: datetime
    expires_at: datetime

    @field_validator("attachment_sha256")
    @classmethod
    def _attachment_hashes_are_valid(cls, value: list[str]) -> list[str]:
        invalid = any(
            len(item) != 64 or any(char not in "0123456789abcdefABCDEF" for char in item)
            for item in value
        )
        if invalid:
            raise ValueError("attachment hashes must be SHA-256 hex values")
        return value

    @model_validator(mode="after")
    def _expires_within_day(self) -> ApprovalGrant:
        lifetime = self.expires_at - self.issued_at
        if lifetime <= timedelta(0) or lifetime > timedelta(hours=24):
            raise ValueError("approval must expire after issue and within 24 hours")
        return self


class ApplicationEvent(StrictModel):
    event_id: str = Field(min_length=1, max_length=120)
    job_id: str = Field(min_length=1, max_length=120)
    state: JobState
    occurred_at: datetime
    actor: str = Field(min_length=1, max_length=80)
    event_type: str = Field(min_length=1, max_length=100)
    details: dict[str, str] = Field(default_factory=dict)


class WorkspaceMarker(StrictModel):
    marker_version: int = Field(default=1, ge=1, le=1)
    workspace_id: UUID
    schema_version: int = Field(default=1, ge=1, le=1)


__all__: list[str] = [
    "ApprovalGrant",
    "ApplicationEvent",
    "CandidateEvidencePack",
    "CandidateFact",
    "CandidateProfile",
    "Decision",
    "DiscoveryHint",
    "DiscoveryRun",
    "EvidenceRef",
    "ExtractedSource",
    "FitScore",
    "JobRecord",
    "JobState",
    "SearchPolicy",
    "SourceAuthority",
    "SourceRecord",
    "WorkAuthLabel",
    "WorkType",
    "WorkspaceMarker",
]
