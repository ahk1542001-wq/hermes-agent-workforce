import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import HttpUrl

from hermes_job_scout.config import WorkspacePaths
from hermes_job_scout.database import DatabaseError, JobStore, RevisionConflict
from hermes_job_scout.models import (
    ApplicationEvent,
    DiscoveryRun,
    JobRecord,
    JobState,
    SourceAuthority,
    SourceRecord,
    WorkType,
)
from hermes_job_scout.workspace import bootstrap_private_workspace

NOW = datetime(2026, 9, 15, 8, 0, tzinfo=timezone(timedelta(hours=7)))


def _job(job_id: str = "job-1", *, state: JobState = JobState.DISCOVERED) -> JobRecord:
    return JobRecord(
        job_id=job_id,
        stable_url="https://example.com/jobs/1",
        source_type="official",
        authority=SourceAuthority.OFFICIAL,
        company="Example Labs",
        role="AI Automation Engineer",
        first_seen_at=NOW,
        last_verified_at=NOW,
        work_type=WorkType.DIRECT_CONTRACT,
        location="Remote",
        remote_region="global",
        experience="0-3 years",
        fingerprint="1" * 64,
        state=state,
    )


def _source(source_id: str = "source-1", *, checked: datetime = NOW) -> SourceRecord:
    return SourceRecord(
        source_id=source_id,
        organization="Example Labs",
        source_type="official_careers",
        url="https://example.com/careers",
        status="ok",
        last_checked_at=checked,
        last_success_at=checked,
    )


def _run(run_id: str = "run-1", *, changed_count: int = 0) -> DiscoveryRun:
    return DiscoveryRun(
        run_id=run_id,
        started_at=NOW,
        completed_at=NOW + timedelta(minutes=2),
        coverage="full",
        checked_source_ids=["source-1"],
        changed_count=changed_count,
        result_count=1,
        provider="synthetic",
        actual_search_retrieval_spend_usd=0,
    )


@pytest.fixture
def workspace(tmp_path: Path) -> tuple[WorkspacePaths, UUID]:
    paths = WorkspacePaths.from_root(tmp_path / "Career")
    marker = bootstrap_private_workspace(paths)
    return paths, marker.workspace_id


def test_open_creates_schema_with_marker_wal_and_foreign_keys(workspace) -> None:
    paths, workspace_id = workspace
    store = JobStore.open(paths.database, paths.marker.read_text(encoding="utf-8"))
    assert store.current_revision() == 0
    with sqlite3.connect(paths.database) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)
        assert connection.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone() == ("1",)
        assert connection.execute("SELECT workspace_id FROM workspace_state").fetchone() == (
            str(workspace_id),
        )
    assert store._connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    store.close()


def test_open_rejects_marker_mismatch(workspace) -> None:
    paths, _ = workspace
    wrong = json.loads(paths.marker.read_text(encoding="utf-8"))
    wrong["workspace_id"] = str(uuid4())
    with pytest.raises(DatabaseError):
        JobStore.open(paths.database, json.dumps(wrong))


def test_jobs_have_unique_url_and_fingerprint_and_roundtrip_timezone(workspace) -> None:
    paths, marker = workspace
    store = JobStore.open(paths.database, paths.marker.read_text(encoding="utf-8"))
    record = _job()
    assert store.upsert_job(record, expected_revision=0) == 1
    assert store.get_job(record.job_id) == record
    assert store.get_job(record.job_id).first_seen_at.tzinfo is not None
    with pytest.raises(DatabaseError):
        store.upsert_job(_job("job-2"), expected_revision=1)
    other = _job("job-2").model_copy(update={"stable_url": HttpUrl("https://example.com/jobs/2")})
    with pytest.raises(DatabaseError):
        store.upsert_job(other, expected_revision=1)
    store.close()


def test_stale_revision_cannot_overwrite_newer_state(workspace) -> None:
    paths, _ = workspace
    raw_marker = paths.marker.read_text(encoding="utf-8")
    first = JobStore.open(paths.database, raw_marker)
    second = JobStore.open(paths.database, raw_marker)
    first.upsert_job(_job(), expected_revision=0)
    with pytest.raises(RevisionConflict):
        second.upsert_job(_job(state=JobState.VERIFIED), expected_revision=0)
    assert first.current_revision() == 1
    first.close()
    second.close()


def test_events_are_append_only_and_explicit_event_roundtrips(workspace) -> None:
    paths, _ = workspace
    store = JobStore.open(paths.database, paths.marker.read_text(encoding="utf-8"))
    record = _job()
    store.upsert_job(record, expected_revision=0)
    event = ApplicationEvent(
        event_id="event-1",
        job_id=record.job_id,
        state=JobState.VERIFIED,
        occurred_at=NOW + timedelta(minutes=3),
        actor="owner",
        event_type="verified",
        details={"source": "synthetic"},
    )
    assert store.append_event(event, expected_revision=1) == 2
    assert store.list_events(record.job_id)[-1] == event
    with pytest.raises(DatabaseError):
        store.append_event(event, expected_revision=2)
    with sqlite3.connect(paths.database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM application_events").fetchone() == (2,)
        assert connection.execute(
            "SELECT COUNT(*) FROM application_events WHERE event_id='event-1'"
        ).fetchone() == (1,)
    store.close()


def test_state_change_and_event_are_one_transaction(workspace) -> None:
    paths, _ = workspace
    store = JobStore.open(paths.database, paths.marker.read_text(encoding="utf-8"))
    with pytest.raises(RuntimeError):
        with store.transaction(0) as transaction:
            transaction.upsert_job(_job())
            raise RuntimeError("simulated interruption")
    assert store.current_revision() == 0
    assert store.get_job("job-1") is None
    assert store.list_events("job-1") == []
    store.close()


def test_sources_runs_and_reopen_after_interruption(workspace) -> None:
    paths, _ = workspace
    raw_marker = paths.marker.read_text(encoding="utf-8")
    store = JobStore.open(paths.database, raw_marker)
    assert store.upsert_source(_source(), expected_revision=0) == 1
    assert store.record_discovery_run(_run(), expected_revision=1) == 2
    assert store.record_discovery_run(_run("run-2", changed_count=0), expected_revision=2) == 3
    store.close()
    reopened = JobStore.open(paths.database, raw_marker)
    assert reopened.current_revision() == 3
    assert reopened.get_source("source-1") == _source()
    assert reopened.get_discovery_run("run-1") == _run()
    reopened.close()


def test_transaction_can_group_job_and_event_once(workspace) -> None:
    paths, _ = workspace
    store = JobStore.open(paths.database, paths.marker.read_text(encoding="utf-8"))
    with store.transaction(0) as transaction:
        transaction.upsert_job(_job())
        transaction.append_event(
            ApplicationEvent(
                event_id="manual-1",
                job_id="job-1",
                state=JobState.DISCOVERED,
                occurred_at=NOW,
                actor="test",
                event_type="captured",
            )
        )
    assert store.current_revision() == 1
    assert len(store.list_events("job-1")) == 2
    store.close()
