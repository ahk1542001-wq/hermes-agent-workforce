from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from hermes_job_scout.config import WorkspacePaths
from hermes_job_scout.database import JobStore
from hermes_job_scout.models import JobRecord, JobState, SourceAuthority, WorkType
from hermes_job_scout.state_machine import (
    InvalidTransition,
    TransitionContext,
    transition,
)
from hermes_job_scout.workspace import bootstrap_private_workspace

NOW = datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc)


def _job(state: JobState) -> JobRecord:
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
        state=state,
    )


def _store(tmp_path: Path, state: JobState) -> JobStore:
    paths = WorkspacePaths.from_root(tmp_path / f"Career-{state.value}")
    bootstrap_private_workspace(paths)
    store = JobStore.open(paths.database, paths.marker.read_text(encoding="utf-8"))
    store.upsert_job(_job(state), expected_revision=0)
    return store


def _context(store: JobStore, *, new_evidence: bool = False) -> TransitionContext:
    return TransitionContext(
        store=store,
        expected_revision=store.current_revision(),
        actor="test",
        occurred_at=NOW,
        evidence={"source": "synthetic"},
        new_evidence=new_evidence,
    )


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (JobState.DISCOVERED, JobState.VERIFIED),
        (JobState.VERIFIED, JobState.QUALIFIED),
        (JobState.QUALIFIED, JobState.SHORTLISTED),
        (JobState.SHORTLISTED, JobState.SELECTED),
        (JobState.SELECTED, JobState.PACK_DRAFTED),
        (JobState.PACK_DRAFTED, JobState.PACK_REVIEWED),
        (JobState.PACK_REVIEWED, JobState.PACK_APPROVED),
        (JobState.PACK_APPROVED, JobState.SUBMITTING),
        (JobState.SUBMITTING, JobState.SUBMITTED),
        (JobState.SUBMITTED, JobState.FOLLOW_UP_DUE),
        (JobState.FOLLOW_UP_DUE, JobState.CLOSED),
    ],
)
def test_normal_state_transition_is_atomic(
    tmp_path: Path, current: JobState, target: JobState
) -> None:
    store = _store(tmp_path, current)
    revision = transition("job-1", target, _context(store))

    assert revision == 2
    assert store.get_job("job-1").state is target
    events = store.list_events("job-1")
    assert events[-1].event_type == "state_transition"
    assert events[-1].state is target
    store.close()


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (JobState.DISCOVERED, JobState.REJECTED),
        (JobState.VERIFIED, JobState.EXPIRED),
        (JobState.QUALIFIED, JobState.DUPLICATE),
        (JobState.SELECTED, JobState.NEEDS_VICTOR),
        (JobState.PACK_APPROVED, JobState.WITHDRAWN),
        (JobState.SUBMITTING, JobState.FAILED_UNCONFIRMED),
        (JobState.REJECTED, JobState.ARCHIVED),
        (JobState.CLOSED, JobState.ARCHIVED),
    ],
)
def test_exceptional_transitions_are_explicit(
    tmp_path: Path, current: JobState, target: JobState
) -> None:
    store = _store(tmp_path, current)
    transition("job-1", target, _context(store))
    assert store.get_job("job-1").state is target
    store.close()


def test_skipped_normal_state_is_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path, JobState.DISCOVERED)
    with pytest.raises(InvalidTransition, match="discovered.*qualified"):
        transition("job-1", JobState.QUALIFIED, _context(store))
    assert store.get_job("job-1").state is JobState.DISCOVERED
    store.close()


def test_failed_unconfirmed_cannot_retry_without_new_evidence(tmp_path: Path) -> None:
    store = _store(tmp_path, JobState.FAILED_UNCONFIRMED)
    with pytest.raises(InvalidTransition, match="new evidence"):
        transition("job-1", JobState.NEEDS_VICTOR, _context(store))

    transition("job-1", JobState.NEEDS_VICTOR, _context(store, new_evidence=True))
    assert store.get_job("job-1").state is JobState.NEEDS_VICTOR
    store.close()


def test_unknown_job_and_naive_time_fail_closed(tmp_path: Path) -> None:
    store = _store(tmp_path, JobState.DISCOVERED)
    with pytest.raises(InvalidTransition, match="does not exist"):
        transition("missing", JobState.VERIFIED, _context(store))
    context = _context(store)
    with pytest.raises(ValueError, match="timezone"):
        transition(
            "job-1",
            JobState.VERIFIED,
            TransitionContext(
                store=store,
                expected_revision=context.expected_revision,
                actor=context.actor,
                occurred_at=NOW.replace(tzinfo=None),
                evidence=context.evidence,
            ),
        )
    store.close()


def test_untrusted_evidence_cannot_override_transition_audit_fields(tmp_path: Path) -> None:
    store = _store(tmp_path, JobState.DISCOVERED)
    context = _context(store)
    transition(
        "job-1",
        JobState.VERIFIED,
        TransitionContext(
            store=store,
            expected_revision=context.expected_revision,
            actor=context.actor,
            occurred_at=context.occurred_at,
            evidence={"from": "forged", "to": "forged", "source": "synthetic"},
        ),
    )
    event = store.list_events("job-1")[-1]
    assert event.details["from"] == "discovered"
    assert event.details["to"] == "verified"
    store.close()
