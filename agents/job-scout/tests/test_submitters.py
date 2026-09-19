from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from hermes_job_scout.approvals import SubmissionAction, hash_payload
from hermes_job_scout.config import WorkspacePaths
from hermes_job_scout.database import JobStore
from hermes_job_scout.models import (
    ApprovalGrant,
    Decision,
    JobRecord,
    JobState,
    SourceAuthority,
    WorkType,
)
from hermes_job_scout.submitters import (
    DuplicateSubmission,
    ExternalActionDisabled,
    MockSubmitter,
    get_submitter,
)
from hermes_job_scout.workspace import bootstrap_private_workspace

NOW = datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc)
PAYLOAD = {"message": "Synthetic application"}


def _job() -> JobRecord:
    return JobRecord(
        job_id="job-1",
        stable_url="https://careers.example.com/jobs/1",
        source_type="official",
        authority=SourceAuthority.OFFICIAL,
        company="Example Labs",
        role="AI Automation Engineer",
        first_seen_at=NOW,
        last_verified_at=NOW,
        work_type=WorkType.DIRECT_CONTRACT,
        location="Remote",
        remote_region="worldwide remote",
        experience="0-3 years",
        fingerprint="1" * 64,
        state=JobState.PACK_APPROVED,
        owner_decision=Decision.QUALIFIED,
    )


def _grant() -> ApprovalGrant:
    return ApprovalGrant(
        approval_id="approval-1",
        job_id="job-1",
        recipient="jobs@example.com",
        payload_sha256=hash_payload(PAYLOAD),
        attachment_sha256=["a" * 64],
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
    )


def _action(revision: int, **updates: object) -> SubmissionAction:
    values: dict[str, object] = {
        "job_id": "job-1",
        "approval_id": "approval-1",
        "recipient": "jobs@example.com",
        "payload_sha256": hash_payload(PAYLOAD),
        "attachment_sha256": ("a" * 64,),
        "idempotency_key": "submit-job-1-v1",
        "required_owner_fields": ("work_authorization",),
        "owner_confirmed_fields": ("work_authorization",),
        "expected_revision": revision,
        "approval": _grant(),
    }
    values.update(updates)
    return SubmissionAction(**values)


def _workspace(tmp_path: Path) -> tuple[WorkspacePaths, JobStore]:
    paths = WorkspacePaths.from_root(tmp_path / "Career")
    bootstrap_private_workspace(paths)
    store = JobStore.open(paths.database, paths.marker.read_text(encoding="utf-8"))
    store.upsert_job(_job(), expected_revision=0)
    return paths, store


def test_factory_exposes_mock_only(tmp_path: Path) -> None:
    _, store = _workspace(tmp_path)
    assert isinstance(get_submitter("mock", store=store, now=lambda: NOW), MockSubmitter)
    for mode in ("live", "browser", "email", "telegram", "http"):
        with pytest.raises(ExternalActionDisabled):
            get_submitter(mode, store=store, now=lambda: NOW)
    store.close()


def test_mock_submission_records_one_receipt_and_blocks_duplicate(tmp_path: Path) -> None:
    _, store = _workspace(tmp_path)
    submitter = MockSubmitter(store, now=lambda: NOW)
    action = _action(store.current_revision())

    receipt = submitter.submit(action)

    assert receipt.status == "mock_submitted"
    assert store.get_job("job-1").state is JobState.SUBMITTED
    receipts = [
        event for event in store.list_events("job-1") if event.event_type == "submission_receipt"
    ]
    assert len(receipts) == 1
    with pytest.raises(DuplicateSubmission):
        submitter.submit(_action(store.current_revision()))
    assert (
        len(
            [
                event
                for event in store.list_events("job-1")
                if event.event_type == "submission_receipt"
            ]
        )
        == 1
    )
    store.close()


def test_timeout_marks_failed_and_reopen_cannot_retry_same_key(tmp_path: Path) -> None:
    paths, store = _workspace(tmp_path)
    action = _action(store.current_revision())
    submitter = MockSubmitter(store, now=lambda: NOW, fail_after_reservation=True)

    with pytest.raises(TimeoutError, match="synthetic timeout"):
        submitter.submit(action)
    assert store.get_job("job-1").state is JobState.FAILED_UNCONFIRMED
    store.close()

    reopened = JobStore.open(paths.database, paths.marker.read_text(encoding="utf-8"))
    with pytest.raises(DuplicateSubmission):
        MockSubmitter(reopened, now=lambda: NOW).submit(_action(reopened.current_revision()))
    assert not [
        event for event in reopened.list_events("job-1") if event.event_type == "submission_receipt"
    ]
    reopened.close()


def test_invalid_approval_never_reserves_idempotency_key(tmp_path: Path) -> None:
    _, store = _workspace(tmp_path)
    action = _action(store.current_revision(), recipient="changed@example.com")
    with pytest.raises(ExternalActionDisabled, match="RECIPIENT_MISMATCH"):
        MockSubmitter(store, now=lambda: NOW).submit(action)
    assert not [
        event for event in store.list_events("job-1") if event.event_type.startswith("submission_")
    ]
    assert store.get_job("job-1").state is JobState.PACK_APPROVED
    store.close()
