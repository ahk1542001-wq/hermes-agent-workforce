"""Deterministic, evidence-bound eligibility policy for normalized job records."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from .models import (
    Decision,
    EvidenceRef,
    JobRecord,
    SearchPolicy,
    SourceAuthority,
    WorkAuthLabel,
)

_UNVERIFIED_AUTHORITIES = {
    SourceAuthority.DISCOVERY_HINT,
    SourceAuthority.NEEDS_VERIFICATION,
}
_FAKE_COMPANY_MARKERS = {
    "confidential",
    "fake company",
    "fake company ltd",
    "n/a",
    "undisclosed",
    "unknown",
}
_SPONSORSHIP_PATTERNS = (
    re.compile(r"\b(?:visa|work[- ]?permit)\s+(?:and\s+)?(?:sponsorship|support)\b", re.I),
    re.compile(r"\bsponsor(?:s|ed|ing|ship)?\b.{0,40}\b(?:visa|work[- ]?permit)\b", re.I),
    re.compile(r"\b(?:visa|work[- ]?permit)\b.{0,40}\bsponsor(?:s|ed|ing|ship)?\b", re.I),
)
_AI_ROLE_PATTERNS = tuple(
    re.compile(pattern, re.I)
    for pattern in (
        r"\bAI\b",
        r"\bautomation\b",
        r"\bagentic\b",
        r"\bLLMs?\b",
        r"\bn8n\b",
        r"\bworkflows?\b",
    )
)
_THAI_DISALLOWED_LEVELS = ("fluent", "native", "business", "professional", "required")
_YEAR_PATTERN = re.compile(
    r"(?P<low>\d+)\s*(?:(?:-|–|to)\s*(?P<high>\d+)|(?P<plus>\+))?\s*years?", re.I
)


@dataclass(frozen=True)
class PolicyDecision:
    """Stable result returned by the hard-filter gate."""

    decision: Decision
    reason_codes: tuple[str, ...]
    work_auth_label: WorkAuthLabel
    uncertainty_flags: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()


def _contains_explicit_sponsorship(evidence: EvidenceRef) -> bool:
    if evidence.excerpt is None or evidence.source_url is None or evidence.retrieved_at is None:
        return False
    return any(pattern.search(evidence.excerpt) for pattern in _SPONSORSHIP_PATTERNS)


def _is_thailand(job: JobRecord) -> bool:
    text = f"{job.location} {job.remote_region}".casefold()
    return "thailand" in text or "bangkok" in text


def classify_work_authorization(job: JobRecord) -> WorkAuthLabel:
    """Classify evidence without inferring legal eligibility."""

    if _is_thailand(job):
        if any(_contains_explicit_sponsorship(ref) for ref in job.work_authorization_evidence):
            return WorkAuthLabel.B_THAI_SUPPORT
        return WorkAuthLabel.C_THAI_UNKNOWN
    return WorkAuthLabel.A_REMOTE_GLOBAL


def _reject(code: str, work_auth: WorkAuthLabel) -> PolicyDecision:
    return PolicyDecision(
        decision=Decision.REJECTED,
        reason_codes=(code,),
        work_auth_label=work_auth,
    )


def _role_matches(job: JobRecord, policy: SearchPolicy) -> bool:
    role = job.role.casefold()
    if any(alias.casefold() in role for alias in policy.role_aliases):
        return True
    return any(pattern.search(job.role) for pattern in _AI_ROLE_PATTERNS)


def _geography_matches(job: JobRecord, policy: SearchPolicy) -> bool:
    actual = f"{job.location} {job.remote_region}".casefold()
    if _is_thailand(job):
        return any("thailand" in place.casefold() for place in policy.geography_priority)
    for place in policy.geography_priority:
        normalized = place.casefold()
        if normalized in actual:
            return True
        region = normalized.removesuffix(" remote").strip()
        if region and region in actual and "remote" in actual:
            return True
    return False


def _experience_outcome(job: JobRecord, policy: SearchPolicy) -> tuple[str | None, bool]:
    """Return a rejection code and whether a bounded stretch label applies."""

    text = job.experience.casefold()
    matches = list(_YEAR_PATTERN.finditer(text))
    if not matches:
        return None, False

    for match in matches:
        low = int(match.group("low"))
        high = int(match.group("high") or low)
        suffix = text[match.end() : match.end() + 32]
        explicitly_required = "required" in suffix
        if explicitly_required and high > policy.max_experience_years:
            return "EXPERIENCE_TOO_HIGH", False
        if match.group("plus") and low > policy.max_experience_years:
            return "EXPERIENCE_TOO_HIGH", False
        if match.group("high") is None and low > policy.max_experience_years:
            return "EXPERIENCE_TOO_HIGH", False

    highest = max(int(match.group("high") or match.group("low")) for match in matches)
    if highest > policy.max_experience_years:
        mid_level = bool(re.search(r"\bmid(?:-|\s)?level\b", job.role, re.I))
        if mid_level and any(
            int(match.group("low")) <= policy.max_experience_years for match in matches
        ):
            return None, True
        return "EXPERIENCE_TOO_HIGH", False
    return None, bool(re.search(r"\bmid(?:-|\s)?level\b", job.role, re.I))


def evaluate_hard_filters(
    job: JobRecord,
    policy: SearchPolicy,
    now: datetime,
) -> PolicyDecision:
    """Apply ordered hard filters and return stable, auditable reason codes."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a timezone")

    work_auth = classify_work_authorization(job)
    if job.authority in _UNVERIFIED_AUTHORITIES:
        return PolicyDecision(
            decision=Decision.NEEDS_VICTOR,
            reason_codes=("SOURCE_UNVERIFIED",),
            work_auth_label=work_auth,
            uncertainty_flags=("SOURCE_UNVERIFIED",),
        )
    if job.closes_at is not None and job.closes_at < now:
        return _reject("EXPIRED", work_auth)
    if (now - job.last_verified_at).days > policy.freshness_days:
        return _reject("STALE_LISTING", work_auth)
    if job.posted_at is not None and (now - job.posted_at).days > policy.freshness_days:
        return _reject("STALE_LISTING", work_auth)
    if job.work_type is not None and job.work_type not in policy.allowed_work_types:
        return _reject("WORK_TYPE_NOT_ALLOWED", work_auth)
    if "unpaid" in f"{job.role} {job.experience}".casefold():
        return _reject("UNPAID_INTERNSHIP", work_auth)
    if job.company.casefold().strip(" .") in _FAKE_COMPANY_MARKERS:
        return _reject("COMPANY_NOT_CREDIBLE", work_auth)
    if any(flag.casefold() == "fake_company" for flag in job.uncertainty_flags):
        return _reject("COMPANY_NOT_CREDIBLE", work_auth)
    role = job.role.casefold()
    if any(
        re.search(rf"\b{re.escape(level.casefold())}\b", role)
        for level in policy.excluded_seniority
    ):
        return _reject("EXCLUDED_SENIORITY", work_auth)
    if not _role_matches(job, policy):
        return _reject("NON_AI_ROLE", work_auth)

    uncertainty_reasons: list[str] = []
    if "FRESHNESS_UNKNOWN" in job.uncertainty_flags:
        uncertainty_reasons.append("FRESHNESS_UNKNOWN")
    if job.work_type is None or "WORK_TYPE_UNKNOWN" in job.uncertainty_flags:
        uncertainty_reasons.append("WORK_TYPE_UNKNOWN")
    if "EXPERIENCE_UNKNOWN" in job.uncertainty_flags:
        uncertainty_reasons.append("EXPERIENCE_UNKNOWN")

    experience_rejection, stretch = _experience_outcome(job, policy)
    if experience_rejection is not None:
        return _reject(experience_rejection, work_auth)
    for language in job.language:
        normalized = language.casefold()
        if "thai" in normalized and any(level in normalized for level in _THAI_DISALLOWED_LEVELS):
            return _reject("THAI_FLUENT_REQUIRED", work_auth)
    if not _geography_matches(job, policy):
        return _reject("GEOGRAPHY_UNSUPPORTED", work_auth)
    if work_auth is WorkAuthLabel.C_THAI_UNKNOWN:
        uncertainty_reasons.append("WORK_AUTH_UNCONFIRMED")

    if uncertainty_reasons:
        return PolicyDecision(
            decision=Decision.NEEDS_VICTOR,
            reason_codes=tuple(uncertainty_reasons),
            work_auth_label=work_auth,
            uncertainty_flags=tuple(uncertainty_reasons),
        )

    reasons: list[str] = []
    uncertainty: list[str] = []
    labels: list[str] = []
    if stretch:
        reasons.append("STRETCH_ROLE")
        labels.append("STRETCH")
    if not job.salary_evidence:
        reasons.append("SALARY_UNKNOWN")
        uncertainty.append("SALARY_UNKNOWN")
    return PolicyDecision(
        decision=Decision.QUALIFIED,
        reason_codes=tuple(reasons),
        work_auth_label=work_auth,
        uncertainty_flags=tuple(uncertainty),
        labels=tuple(labels),
    )


__all__ = ["PolicyDecision", "classify_work_authorization", "evaluate_hard_filters"]
