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

    future_time = datetime(2026, 9, 21, 9, 0, tzinfo=timezone.utc)
    future_item = item.model_copy(update={"published_at": future_time})
    rec_future = normalize_feed_item(future_item, NOW)
    assert rec_future.first_seen_at == NOW
