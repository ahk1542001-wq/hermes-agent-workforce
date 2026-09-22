from datetime import datetime, timezone

import pytest

from hermes_job_scout.models import (
    Decision,
    ExtractedSource,
    HttpUrl,
    JobRecord,
    JobState,
    RawFeedItem,
    SearchPolicy,
    SourceAuthority,
    WorkType,
)
from hermes_job_scout.normalize import deduplicate, normalize_feed_item
from hermes_job_scout.policy import evaluate_hard_filters
from hermes_job_scout.sources import verify_feed_listing

NOW = datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc)


def _sample_hint() -> JobRecord:
    item = RawFeedItem(
        source_name="himalayas",
        source_item_id="REQ-404",
        title="AI Engineer",
        company="Acme Corp",
        url="https://himalayas.app/jobs/acme-corp/ai-engineer",
        apply_url="https://jobs.lever.co/acme/REQ-404?trk=feed",
        description="Build workflows.",
        location="Worldwide",
        published_at=NOW,
        retrieved_at=NOW,
    )
    return normalize_feed_item(item, NOW)


def test_discovery_hint_cannot_directly_transition_to_verified_or_qualified() -> None:
    hint = _sample_hint()
    assert hint.authority is SourceAuthority.DISCOVERY_HINT
    assert hint.state is JobState.DISCOVERED

    with pytest.raises(ValueError, match="unverified source authority"):
        JobRecord.model_validate({**hint.model_dump(mode="python"), "state": JobState.VERIFIED})

    with pytest.raises(ValueError, match="unverified source authority"):
        JobRecord.model_validate(
            {**hint.model_dump(mode="python"), "owner_decision": Decision.QUALIFIED}
        )


def test_transport_mechanism_cannot_promote_authority() -> None:
    hint = _sample_hint()
    # Passing an aggregator URL does not promote authority
    result = verify_feed_listing(hint, official_url="https://www.linkedin.com/jobs/view/123456")
    assert result.authority is SourceAuthority.DISCOVERY_HINT
    assert result.state is JobState.DISCOVERED

    result_indeed = verify_feed_listing(
        hint, official_url="https://www.indeed.com/viewjob?jk=abcdef"
    )
    assert result_indeed.authority is SourceAuthority.DISCOVERY_HINT
    assert result_indeed.state is JobState.DISCOVERED


def test_recognized_ats_promotes_to_ats_and_verified() -> None:
    hint = _sample_hint()
    verified = verify_feed_listing(hint, official_url="https://jobs.lever.co/acme/REQ-404")
    assert verified.authority is SourceAuthority.ATS
    assert verified.state is JobState.VERIFIED
    assert str(verified.stable_url) == "https://jobs.lever.co/acme/REQ-404"
    assert verified.source_type == "ats"


def test_ats_company_mismatch_fails_closed() -> None:
    hint = _sample_hint()
    # lever URL is for 'othercorp', not 'acme'
    result = verify_feed_listing(hint, official_url="https://jobs.lever.co/othercorp/REQ-404")
    assert result.authority is SourceAuthority.DISCOVERY_HINT
    assert result.state is JobState.DISCOVERED


def test_ats_company_substring_collision_fails_closed() -> None:
    hint = _sample_hint()
    result = verify_feed_listing(
        hint,
        official_url="https://jobs.lever.co/notacme/REQ-404",
    )
    assert result.authority is SourceAuthority.DISCOVERY_HINT
    assert result.state is JobState.DISCOVERED


@pytest.mark.parametrize(
    ("company", "url", "authority"),
    [
        ("Acme Corp", "https://acme.bamboohr.com/careers/123", SourceAuthority.ATS),
        ("Acme Corp", "https://acme.recruitee.com/o/engineer", SourceAuthority.ATS),
        ("Example Corp", "https://careers.example.com/jobs/123", SourceAuthority.OFFICIAL),
    ],
)
def test_supported_subdomain_authorities_still_match_company(
    company: str,
    url: str,
    authority: SourceAuthority,
) -> None:
    hint = _sample_hint().model_copy(update={"company": company})
    verified = verify_feed_listing(hint, official_url=url)
    assert verified.authority is authority
    assert verified.state is JobState.VERIFIED


def test_workday_infrastructure_shard_cannot_match_company() -> None:
    hint = _sample_hint().model_copy(update={"company": "WD5"})
    result = verify_feed_listing(
        hint,
        official_url="https://other.wd5.myworkdayjobs.com/en-US/Careers/job/engineer/123",
    )
    assert result.authority is SourceAuthority.DISCOVERY_HINT
    assert result.state is JobState.DISCOVERED


def test_verified_listing_with_unknown_eligibility_stays_needs_victor() -> None:
    verified = verify_feed_listing(_sample_hint())
    policy = SearchPolicy(
        policy_version="test-v1",
        headline="AI Automation Engineer",
        role_aliases=["AI Engineer"],
        geography_priority=["Worldwide"],
        allowed_work_types=[WorkType.FULL_TIME],
        accepted_languages=["English"],
    )
    decision = evaluate_hard_filters(verified, policy, NOW)
    assert decision.decision is Decision.NEEDS_VICTOR
    assert "EXPERIENCE_UNKNOWN" in decision.uncertainty_flags


def test_confirmed_employer_promotes_to_official_and_verified() -> None:
    item = RawFeedItem(
        source_name="himalayas",
        source_item_id="REQ-EMP",
        title="AI Engineer",
        company="Example Corp",
        url="https://himalayas.app/jobs/example-corp/ai-engineer",
        apply_url="https://example.com/jobs/REQ-EMP",
        description="Build workflows.",
        location="Worldwide",
        retrieved_at=NOW,
    )
    hint = normalize_feed_item(item, NOW)
    verified = verify_feed_listing(hint, official_url="https://example.com/jobs/REQ-EMP")
    assert verified.authority is SourceAuthority.OFFICIAL
    assert verified.state is JobState.VERIFIED
    assert str(verified.stable_url) == "https://example.com/jobs/REQ-EMP"
    assert verified.source_type == "official"


def test_unrecognized_domain_remains_discovery_hint() -> None:
    hint = _sample_hint()
    result = verify_feed_listing(hint, official_url="https://unknown-aggregator.org/jobs/404")
    assert result.authority is SourceAuthority.DISCOVERY_HINT
    assert result.state is JobState.DISCOVERED


def test_verify_using_apply_url_ref_when_no_url_explicitly_passed() -> None:
    hint = _sample_hint()
    # hint has apply_url="https://jobs.lever.co/acme/REQ-404?trk=feed" in evidence_refs
    verified = verify_feed_listing(hint)
    assert verified.authority is SourceAuthority.ATS
    assert verified.state is JobState.VERIFIED
    assert str(verified.stable_url) == "https://jobs.lever.co/acme/REQ-404"


def test_verify_with_extracted_source() -> None:
    hint = _sample_hint()
    extracted = ExtractedSource(
        provider="hermes_extract",
        url=HttpUrl("https://jobs.lever.co/acme/REQ-404"),
        title="AI Engineer at Acme Corp",
        content="We are looking for an AI Engineer at Acme Corp...",
        retrieved_at=NOW,
        content_sha256="0" * 64,
        authority=SourceAuthority.ATS,
    )
    verified = verify_feed_listing(hint, official_source=extracted)
    assert verified.authority is SourceAuthority.ATS
    assert verified.state is JobState.VERIFIED
    assert str(verified.stable_url) == "https://jobs.lever.co/acme/REQ-404"


def test_official_evidence_becomes_canonical_in_deduplication() -> None:
    hint = _sample_hint()
    verified = verify_feed_listing(hint, official_url="https://jobs.lever.co/acme/REQ-404")

    result = deduplicate([hint, verified])
    assert len(result.records) == 1
    retained = result.records[0]
    assert retained.authority is SourceAuthority.ATS
    assert str(retained.stable_url) == "https://jobs.lever.co/acme/REQ-404"
    assert len(result.duplicate_groups) == 1
    expected_prov = "https://himalayas.app/jobs/acme-corp/ai-engineer"
    assert expected_prov in result.duplicate_groups[0].provenance
    assert "https://jobs.lever.co/acme/REQ-404" in result.duplicate_groups[0].provenance


def test_verify_feed_listing_edge_cases_and_error_handling() -> None:
    with pytest.raises(ValueError, match="hint_record must be a JobRecord"):
        verify_feed_listing(None)  # type: ignore[arg-type]

    # Hint without apply_url and no official_url passed -> unchanged
    item = RawFeedItem(
        source_name="himalayas",
        source_item_id="REQ-NO-APPLY",
        title="AI Engineer",
        company="Acme Corp",
        url="https://himalayas.app/jobs/acme-corp/ai-engineer",
        apply_url=None,
        description="No apply link",
        location="Worldwide",
        published_at=NOW,
        retrieved_at=NOW,
    )
    hint_no_apply = normalize_feed_item(item, NOW)
    assert verify_feed_listing(hint_no_apply) == hint_no_apply

    # Malformed URL passed -> unchanged
    assert verify_feed_listing(hint_no_apply, official_url="ftp://malformed-url") == hint_no_apply

    # Company with only generic words
    item_generic = RawFeedItem(
        source_name="himalayas",
        source_item_id="REQ-GEN",
        title="AI Engineer",
        company="AI Labs",
        url="https://himalayas.app/jobs/ai-labs/ai-engineer",
        apply_url="https://jobs.lever.co/ai/REQ-GEN",
        description="Generic company",
        location="Worldwide",
        published_at=NOW,
        retrieved_at=NOW,
    )
    hint_generic = normalize_feed_item(item_generic, NOW)
    verified_gen = verify_feed_listing(hint_generic)
    assert verified_gen.authority is SourceAuthority.ATS
