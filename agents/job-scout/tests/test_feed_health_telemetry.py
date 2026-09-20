from datetime import datetime, timezone
from pathlib import Path

import pytest

from hermes_job_scout.database import DatabaseError, JobStore
from hermes_job_scout.models import (
    DiscoveryRun,
    HttpUrl,
    JobRecord,
    JobState,
    SourceAuthority,
    WorkType,
)
from hermes_job_scout.reporting import format_run_summary
from hermes_job_scout.workspace import WorkspacePaths, bootstrap_private_workspace

NOW = datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    paths = WorkspacePaths.from_root(tmp_path / "Career")
    bootstrap_private_workspace(paths)
    return JobStore.open(paths.database, paths.marker.read_text(encoding="utf-8"))


def test_successful_feed_read_updates_source_health(store: JobStore) -> None:
    rev = store.update_source_health("himalayas", NOW, success=True, changed=True)
    assert rev > 0

    source = store.get_source("himalayas")
    assert source is not None
    assert source.organization == "Himalayas"
    assert source.status == "healthy"
    assert source.last_checked_at == NOW
    assert source.last_success_at == NOW
    assert source.last_changed_at == NOW
    assert source.last_error_code is None

    # Subsequent check without change
    store.update_source_health("himalayas", LATER, success=True, changed=False)
    updated = store.get_source("himalayas")
    assert updated is not None
    assert updated.last_checked_at == LATER
    assert updated.last_success_at == LATER
    assert updated.last_changed_at == NOW  # unchanged from prior timestamp


def test_failed_feed_read_records_error_code(store: JobStore) -> None:
    store.update_source_health(
        "remoteok", NOW, success=False, error_code="HTTP_503_SERVICE_UNAVAILABLE"
    )
    source = store.get_source("remoteok")
    assert source is not None
    assert source.status == "failing"
    assert source.last_checked_at == NOW
    assert source.last_success_at is None
    assert source.last_error_code == "HTTP_503_SERVICE_UNAVAILABLE"


def test_partial_run_explicitly_flags_coverage_and_names_failed_sources(
    store: JobStore,
) -> None:
    store.update_source_health("himalayas", NOW, success=True)
    store.update_source_health("remotive", NOW, success=False, error_code="TIMEOUT")

    run = DiscoveryRun(
        run_id="run-feed-partial-001",
        started_at=NOW,
        completed_at=LATER,
        coverage="partial",
        checked_source_ids=["himalayas", "remotive"],
        failed_source_ids=["remotive"],
        changed_count=5,
        result_count=10,
        provider="structured_feed_runner",
        model_calls=0,
        actual_search_retrieval_spend_usd=0.0,
    )
    store.record_discovery_run(run, store.current_revision())

    persisted = store.get_discovery_run("run-feed-partial-001")
    assert persisted is not None
    assert persisted.coverage == "partial"
    assert persisted.failed_source_ids == ["remotive"]

    himalayas_src = store.get_source("himalayas")
    remotive_src = store.get_source("remotive")
    assert himalayas_src is not None and remotive_src is not None

    summary = format_run_summary(persisted, [himalayas_src, remotive_src])
    assert "run-feed-partial-001" in summary
    assert "Coverage: partial" in summary
    assert "Failed sources: remotive" in summary
    assert "remotive" in summary
    assert "TIMEOUT" in summary


def test_unchanged_listings_do_not_create_redundant_write_events(store: JobStore) -> None:
    rec = JobRecord(
        job_id="REQ-IMMUTABLE-1",
        stable_url=HttpUrl("https://himalayas.app/jobs/immutable/1"),
        source_type="discovery_hint",
        authority=SourceAuthority.DISCOVERY_HINT,
        company="Immutable AI",
        role="Automation Architect",
        first_seen_at=NOW,
        last_verified_at=NOW,
        work_type=WorkType.FULL_TIME,
        location="Worldwide",
        remote_region="Worldwide",
        experience="0-3 years",
        fingerprint="d" * 64,
        state=JobState.DISCOVERED,
    )

    rev1 = store.upsert_job(rec, store.current_revision())
    events_initial = store.list_events(rec.job_id)
    assert len(events_initial) == 1

    # Upserting the identical record again should be a no-op
    rev2 = store.upsert_job(rec, store.current_revision())
    assert rev2 == rev1
    events_after = store.list_events(rec.job_id)
    assert len(events_after) == 1


def test_update_source_health_validation_and_errors(store: JobStore) -> None:
    with pytest.raises(ValueError, match="checked_at must include a timezone"):
        store.update_source_health("himalayas", datetime(2026, 9, 20, 9, 0), success=True)

    with pytest.raises(DatabaseError, match="not found in catalog or registry"):
        store.update_source_health("completely_unknown_source", NOW, success=True)


def test_format_run_summary_full_coverage_no_sources() -> None:
    run = DiscoveryRun(
        run_id="run-full-001",
        started_at=NOW,
        completed_at=LATER,
        coverage="full",
        checked_source_ids=["himalayas"],
        failed_source_ids=[],
        changed_count=2,
        result_count=5,
        provider="structured_feed_runner",
        model_calls=0,
        actual_search_retrieval_spend_usd=0.0,
    )
    summary = format_run_summary(run)
    assert "Coverage: full" in summary
    assert "Failed sources: None" in summary
