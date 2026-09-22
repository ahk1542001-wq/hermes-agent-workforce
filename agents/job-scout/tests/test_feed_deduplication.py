from datetime import datetime, timezone

import pytest

from hermes_job_scout.models import (
    HttpUrl,
    JobRecord,
    JobState,
    RawFeedItem,
    SourceAuthority,
    WorkType,
)
from hermes_job_scout.normalize import deduplicate, normalize_feed_item

NOW = datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc)


def test_same_job_across_two_feeds_collapses() -> None:
    item_himalayas = RawFeedItem(
        source_name="himalayas",
        source_item_id="REQ-001",
        title="AI Automation Engineer",
        company="Acme Corp",
        url="https://himalayas.app/jobs/acme-corp/ai-automation-engineer?utm_source=feed",
        apply_url="https://jobs.lever.co/acme/REQ-001?trk=123",
        description="Build workflows with n8n and Python.",
        location="Worldwide",
        published_at=NOW,
        retrieved_at=NOW,
    )
    item_remoteok = RawFeedItem(
        source_name="remoteok",
        source_item_id="REQ-001",
        title="AI Automation Engineer",
        company="Acme Corp",
        url="https://remoteok.com/remote-jobs/REQ-001?ref=rss",
        apply_url="https://jobs.lever.co/acme/REQ-001?utm_campaign=board",
        description="Build workflows with n8n and Python.",
        location="Worldwide",
        published_at=NOW,
        retrieved_at=NOW,
    )

    rec1 = normalize_feed_item(item_himalayas, NOW)
    rec2 = normalize_feed_item(item_remoteok, NOW)

    result = deduplicate([rec1, rec2])
    assert len(result.records) == 1
    assert len(result.duplicate_groups) == 1
    group = result.duplicate_groups[0]
    assert len(group.provenance) == 2
    assert "https://himalayas.app/jobs/acme-corp/ai-automation-engineer" in group.provenance
    assert "https://remoteok.com/remote-jobs/REQ-001" in group.provenance


def test_similar_titles_with_different_requisition_ids_remain_separate() -> None:
    item1 = RawFeedItem(
        source_name="himalayas",
        source_item_id="REQ-101",
        title="AI Automation Engineer",
        company="Acme Corp",
        url="https://himalayas.app/jobs/acme-corp/role-101",
        description="Workflow role 101",
        location="Worldwide",
        published_at=NOW,
        retrieved_at=NOW,
    )
    item2 = RawFeedItem(
        source_name="himalayas",
        source_item_id="REQ-102",
        title="AI Automation Engineer",
        company="Acme Corp",
        url="https://himalayas.app/jobs/acme-corp/role-102",
        description="Workflow role 102",
        location="Worldwide",
        published_at=NOW,
        retrieved_at=NOW,
    )

    rec1 = normalize_feed_item(item1, NOW)
    rec2 = normalize_feed_item(item2, NOW)

    result = deduplicate([rec1, rec2])
    assert len(result.records) == 2
    assert len(result.duplicate_groups) == 0


def test_stronger_official_evidence_becomes_canonical_over_discovery_hint() -> None:
    hint_item = RawFeedItem(
        source_name="himalayas",
        source_item_id="REQ-999",
        title="Agentic Engineer",
        company="Omega AI",
        url="https://himalayas.app/jobs/omega-ai/agentic-eng",
        apply_url="https://jobs.ashbyhq.com/omega/999",
        description="Build agents",
        location="Worldwide",
        retrieved_at=NOW,
    )
    hint_rec = normalize_feed_item(hint_item, NOW)
    assert hint_rec.authority is SourceAuthority.DISCOVERY_HINT

    # Official ATS record for the same requisition
    ats_rec = JobRecord(
        job_id="REQ-999",
        stable_url=HttpUrl("https://jobs.ashbyhq.com/omega/999"),
        source_type="ats",
        authority=SourceAuthority.ATS,
        company="Omega AI",
        role="Agentic Engineer",
        first_seen_at=NOW,
        last_verified_at=NOW,
        work_type=WorkType.FULL_TIME,
        location="Worldwide",
        remote_region="Worldwide",
        experience="0-3 years",
        fingerprint=hint_rec.fingerprint,
        state=JobState.VERIFIED,
    )

    result = deduplicate([hint_rec, ats_rec])
    assert len(result.records) == 1
    assert result.records[0].authority is SourceAuthority.ATS
    assert str(result.records[0].stable_url) == "https://jobs.ashbyhq.com/omega/999"
    assert len(result.duplicate_groups) == 1
    expected_prov = "https://himalayas.app/jobs/omega-ai/agentic-eng"
    assert expected_prov in result.duplicate_groups[0].provenance


def test_normalize_feed_item_validation_and_defaults() -> None:
    with pytest.raises(ValueError, match="item must be a RawFeedItem"):
        normalize_feed_item(None, NOW)  # type: ignore[arg-type]

    item = RawFeedItem(
        source_name="himalayas",
        source_item_id="REQ-EMPTY",
        title="Engineer",
        company="Omega",
        url="https://himalayas.app/jobs/omega/eng",
        location="",
        published_at=None,
        retrieved_at=NOW,
    )
    with pytest.raises(ValueError, match="retrieved_at must include a timezone"):
        normalize_feed_item(item, datetime(2026, 9, 20, 9, 0))

    rec = normalize_feed_item(item, NOW)
    assert rec.location == "Worldwide"
    assert rec.posted_at is None
    assert rec.first_seen_at == NOW
    assert rec.evidence_refs == []
    assert rec.experience == "Unknown"
    assert "EXPERIENCE_UNKNOWN" in rec.uncertainty_flags

    future_time = datetime(2026, 9, 21, 9, 0, tzinfo=timezone.utc)
    future_item = item.model_copy(update={"published_at": future_time})
    rec_future = normalize_feed_item(future_item, NOW)
    assert rec_future.first_seen_at == NOW


def test_experience_extraction_requires_requirement_context_and_checks_all_matches() -> None:
    base = RawFeedItem(
        source_name="himalayas",
        source_item_id="REQ-EXP",
        title="AI Engineer",
        company="Acme Corp",
        url="https://himalayas.app/jobs/acme/engineer",
        location="Worldwide",
        retrieved_at=NOW,
    )
    historical = base.model_copy(
        update={
            "description": "We have served customers for 10 years. No prior experience required."
        }
    )
    historical_record = normalize_feed_item(historical, NOW)
    assert historical_record.experience == "Unknown"
    assert "EXPERIENCE_UNKNOWN" in historical_record.uncertainty_flags

    company_history = base.model_copy(
        update={"description": "We have 10 years of experience delivering AI products."}
    )
    company_history_record = normalize_feed_item(company_history, NOW)
    assert company_history_record.experience == "Unknown"
    assert "EXPERIENCE_UNKNOWN" in company_history_record.uncertainty_flags

    mixed = base.model_copy(
        update={"description": "2 years preferred; 5+ years required for this role."}
    )
    mixed_record = normalize_feed_item(mixed, NOW)
    assert "2 years preferred" in mixed_record.experience
    assert "5+ years required" in mixed_record.experience
    assert "EXPERIENCE_UNKNOWN" not in mixed_record.uncertainty_flags


def test_missing_published_at_and_work_type_flags_uncertainty() -> None:
    item = RawFeedItem(
        source_name="himalayas",
        source_item_id="REQ-NO-DATE",
        title="AI Automation Engineer",
        company="Acme Corp",
        url="https://himalayas.app/jobs/acme/engineer",
        published_at=None,
        retrieved_at=NOW,
    )
    rec = normalize_feed_item(item, NOW)
    assert rec.posted_at is None
    assert "FRESHNESS_UNKNOWN" in rec.uncertainty_flags
    assert rec.work_type is None
    assert "WORK_TYPE_UNKNOWN" in rec.uncertainty_flags


def test_explicit_work_type_in_metadata_or_param_is_honored() -> None:
    item_with_meta = RawFeedItem(
        source_name="himalayas",
        source_item_id="REQ-META",
        title="AI Automation Engineer",
        company="Acme Corp",
        url="https://himalayas.app/jobs/acme/engineer",
        published_at=NOW,
        retrieved_at=NOW,
        metadata={"work_type": "direct_contract"},
    )
    rec_meta = normalize_feed_item(item_with_meta, NOW)
    assert rec_meta.work_type is WorkType.DIRECT_CONTRACT
    assert "WORK_TYPE_UNKNOWN" not in rec_meta.uncertainty_flags

    item_plain = RawFeedItem(
        source_name="himalayas",
        source_item_id="REQ-PARAM",
        title="AI Automation Engineer",
        company="Acme Corp",
        url="https://himalayas.app/jobs/acme/engineer",
        published_at=NOW,
        retrieved_at=NOW,
    )
    rec_param = normalize_feed_item(item_plain, NOW, work_type=WorkType.FULL_TIME)
    assert rec_param.work_type is WorkType.FULL_TIME
    assert "WORK_TYPE_UNKNOWN" not in rec_param.uncertainty_flags


def test_cross_source_ats_identity_collapses() -> None:
    item1 = RawFeedItem(
        source_name="himalayas",
        source_item_id="HIM-001",
        title="AI Automation Engineer",
        company="Acme Corp",
        url="https://himalayas.app/jobs/acme-corp/role-him",
        apply_url="https://jobs.ashbyhq.com/acme-corp/req-1",
        description="First description from Himalayas",
        location="Worldwide",
        published_at=NOW,
        retrieved_at=NOW,
    )
    item2 = RawFeedItem(
        source_name="remoteok",
        source_item_id="ROK-999",
        title="AI Automation Engineer",
        company="Acme Corp",
        url="https://remoteok.com/remote-jobs/999",
        apply_url="https://jobs.ashbyhq.com/acme-corp/req-1?trk=ro_feed",
        description="Completely different description from RemoteOK",
        location="Worldwide",
        published_at=NOW,
        retrieved_at=NOW,
    )
    rec1 = normalize_feed_item(item1, NOW)
    rec2 = normalize_feed_item(item2, NOW)
    assert rec1.fingerprint != rec2.fingerprint

    result = deduplicate([rec1, rec2])
    assert len(result.records) == 1
    assert len(result.duplicate_groups) == 1
    prov = result.duplicate_groups[0].provenance
    assert "https://himalayas.app/jobs/acme-corp/role-him" in prov
    assert "https://remoteok.com/remote-jobs/999" in prov


def test_same_company_different_ats_urls_remain_separate() -> None:
    item1 = RawFeedItem(
        source_name="himalayas",
        source_item_id="REQ-001",
        title="AI Automation Engineer",
        company="Acme Corp",
        url="https://himalayas.app/jobs/acme-corp/role-1",
        apply_url="https://jobs.ashbyhq.com/acme-corp/req-1",
        description="Role 1",
        location="Worldwide",
        published_at=NOW,
        retrieved_at=NOW,
    )
    item2 = RawFeedItem(
        source_name="himalayas",
        source_item_id="REQ-002",
        title="AI Automation Engineer",
        company="Acme Corp",
        url="https://himalayas.app/jobs/acme-corp/role-2",
        apply_url="https://jobs.ashbyhq.com/acme-corp/req-2",
        description="Role 2",
        location="Worldwide",
        published_at=NOW,
        retrieved_at=NOW,
    )
    rec1 = normalize_feed_item(item1, NOW)
    rec2 = normalize_feed_item(item2, NOW)

    result = deduplicate([rec1, rec2])
    assert len(result.records) == 2
    assert len(result.duplicate_groups) == 0


def test_same_ats_url_with_mismatched_company_does_not_merge() -> None:
    valid = RawFeedItem(
        source_name="himalayas",
        source_item_id="VALID-1",
        title="AI Automation Engineer",
        company="Acme Corp",
        url="https://himalayas.app/jobs/acme/valid",
        apply_url="https://jobs.ashbyhq.com/acme/req-1",
        description="0-3 years experience required.",
        location="Worldwide",
        published_at=NOW,
        retrieved_at=NOW,
    )
    mismatched = RawFeedItem(
        source_name="remoteok",
        source_item_id="MISMATCH-1",
        title="AI Automation Engineer",
        company="Other Corp",
        url="https://remoteok.com/remote-jobs/mismatch",
        apply_url="https://jobs.ashbyhq.com/acme/req-1",
        description="0-3 years experience required.",
        location="Worldwide",
        published_at=NOW,
        retrieved_at=NOW,
    )

    result = deduplicate([normalize_feed_item(valid, NOW), normalize_feed_item(mismatched, NOW)])

    assert len(result.records) == 2
    assert len(result.duplicate_groups) == 0


def test_verified_ats_records_with_mismatched_company_do_not_merge() -> None:
    first = JobRecord(
        job_id="ATS-1",
        stable_url=HttpUrl("https://jobs.ashbyhq.com/acme/req-1"),
        source_type="ats",
        authority=SourceAuthority.ATS,
        company="Acme Corp",
        role="AI Automation Engineer",
        first_seen_at=NOW,
        last_verified_at=NOW,
        posted_at=NOW,
        work_type=WorkType.FULL_TIME,
        location="Worldwide",
        remote_region="Worldwide",
        experience="0-3 years experience required",
        fingerprint="a" * 64,
        state=JobState.VERIFIED,
    )
    second = first.model_copy(
        update={
            "job_id": "ATS-2",
            "company": "Other Corp",
            "fingerprint": "b" * 64,
        }
    )

    result = deduplicate([first, second])

    assert len(result.records) == 2
    assert len(result.duplicate_groups) == 0


def test_secondary_alias_with_ats_url_promotes_retained_record() -> None:
    # First alias: aggregator without apply_url
    item1 = RawFeedItem(
        source_name="himalayas",
        source_item_id="REQ-SAME",
        title="AI Automation Engineer",
        company="Acme Corp",
        url="https://himalayas.app/jobs/acme-corp/eng",
        description="Build workflows with Python and n8n.",
        location="Worldwide",
        published_at=NOW,
        retrieved_at=NOW,
    )
    # Second alias: has ATS apply URL for the same requisition
    item2 = RawFeedItem(
        source_name="remoteok",
        source_item_id="REQ-SAME",
        title="AI Automation Engineer",
        company="Acme Corp",
        url="https://remoteok.com/remote-jobs/same",
        apply_url="https://jobs.ashbyhq.com/acme-corp/req-same",
        description="Build workflows with Python and n8n.",
        location="Worldwide",
        published_at=NOW,
        retrieved_at=NOW,
    )
    rec1 = normalize_feed_item(item1, NOW)
    rec2 = normalize_feed_item(item2, NOW)

    result = deduplicate([rec1, rec2])
    assert len(result.records) == 1
    retained = result.records[0]
    assert retained.authority is SourceAuthority.ATS
    assert retained.state is JobState.VERIFIED
    assert any(ref.field in ("apply_url", "official_source") for ref in retained.evidence_refs)
    alias_urls = {
        str(ref.source_url)
        for ref in retained.evidence_refs
        if ref.field == "discovery_alias" and ref.source_url is not None
    }
    assert alias_urls == {
        "https://himalayas.app/jobs/acme-corp/eng",
        "https://remoteok.com/remote-jobs/same",
    }


def test_duplicate_merge_preserves_stricter_experience_evidence() -> None:
    base = {
        "title": "AI Automation Engineer",
        "company": "Acme Corp",
        "apply_url": "https://jobs.ashbyhq.com/acme-corp/req-exp",
        "location": "Worldwide",
        "published_at": NOW,
        "retrieved_at": NOW,
        "metadata": {"work_type": "full_time"},
    }
    junior = RawFeedItem(
        source_name="himalayas",
        source_item_id="HIM-EXP",
        url="https://himalayas.app/jobs/acme-corp/exp",
        description="0-3 years experience required.",
        **base,
    )
    senior = RawFeedItem(
        source_name="remoteok",
        source_item_id="ROK-EXP",
        url="https://remoteok.com/remote-jobs/exp",
        description="5+ years experience required.",
        **base,
    )

    retained = deduplicate(
        [normalize_feed_item(junior, NOW), normalize_feed_item(senior, NOW)]
    ).records[0]

    assert "0-3 years experience required" in retained.experience
    assert "5+ years experience required" in retained.experience
