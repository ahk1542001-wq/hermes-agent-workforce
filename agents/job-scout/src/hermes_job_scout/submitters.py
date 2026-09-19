"""Mock-only submission boundary with durable idempotency reservation."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .approvals import SubmissionAction, validate_approval
from .database import DatabaseError, JobStore
from .models import ApplicationEvent, JobState
from .state_machine import is_transition_allowed


class ExternalActionDisabled(RuntimeError):
    """A non-mock action or invalid approval attempted to cross the boundary."""


class DuplicateSubmission(ExternalActionDisabled):
    """An idempotency key was already reserved, completed, or left ambiguous."""


@dataclass(frozen=True)
class SubmissionReceipt:
    receipt_id: str
    job_id: str
    idempotency_key: str
    submitted_at: datetime
    status: str


class Submitter(Protocol):
    def submit(self, action: SubmissionAction) -> SubmissionReceipt: ...


def _event_key(prefix: str, idempotency_key: str) -> str:
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    return f"{prefix}-{digest}"


class MockSubmitter:
    """Persist a synthetic receipt; never import or call an external transport."""

    def __init__(
        self,
        store: JobStore,
        *,
        now: Callable[[], datetime],
        fail_after_reservation: bool = False,
    ) -> None:
        self._store = store
        self._now = now
        self._fail_after_reservation = fail_after_reservation

    def _already_reserved(self, action: SubmissionAction) -> bool:
        reservation_id = _event_key("submission-reserved", action.idempotency_key)
        return any(
            event.event_id == reservation_id for event in self._store.list_events(action.job_id)
        )

    def submit(self, action: SubmissionAction) -> SubmissionReceipt:
        now = self._now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ExternalActionDisabled("submission clock must include a timezone")
        if action.approval is None:
            raise ExternalActionDisabled("exact approval is required")
        validation = validate_approval(action.approval, action, now)
        if not validation.allowed:
            raise ExternalActionDisabled(validation.code)
        job = self._store.get_job(action.job_id)
        if job is None:
            raise ExternalActionDisabled("JOB_NOT_FOUND")
        if self._already_reserved(action):
            raise DuplicateSubmission("idempotency key is already reserved")
        if not is_transition_allowed(job.state, JobState.SUBMITTING, new_evidence=False):
            raise ExternalActionDisabled("JOB_NOT_PACK_APPROVED")

        reservation_id = _event_key("submission-reserved", action.idempotency_key)
        reservation = ApplicationEvent(
            event_id=reservation_id,
            job_id=action.job_id,
            state=JobState.SUBMITTING,
            occurred_at=now,
            actor="mock_submitter",
            event_type="submission_reserved",
            details={"idempotency_key": action.idempotency_key, "mode": "mock"},
        )
        try:
            with self._store.transaction(action.expected_revision) as transaction_handle:
                transaction_handle.upsert_job(job.model_copy(update={"state": JobState.SUBMITTING}))
                transaction_handle.append_event(reservation)
        except DatabaseError as exc:
            if self._already_reserved(action):
                raise DuplicateSubmission("idempotency key is already reserved") from exc
            raise

        reservation_revision = self._store.current_revision()
        if self._fail_after_reservation:
            failed = self._store.get_job(action.job_id)
            if failed is None:
                raise ExternalActionDisabled("JOB_NOT_FOUND_AFTER_RESERVATION")
            with self._store.transaction(reservation_revision) as transaction_handle:
                transaction_handle.upsert_job(
                    failed.model_copy(update={"state": JobState.FAILED_UNCONFIRMED})
                )
                transaction_handle.append_event(
                    ApplicationEvent(
                        event_id=_event_key("submission-failed", action.idempotency_key),
                        job_id=action.job_id,
                        state=JobState.FAILED_UNCONFIRMED,
                        occurred_at=now,
                        actor="mock_submitter",
                        event_type="submission_failed_unconfirmed",
                        details={"idempotency_key": action.idempotency_key},
                    )
                )
            raise TimeoutError("synthetic timeout after idempotency reservation")

        receipt = SubmissionReceipt(
            receipt_id=_event_key("mock-receipt", action.idempotency_key),
            job_id=action.job_id,
            idempotency_key=action.idempotency_key,
            submitted_at=now,
            status="mock_submitted",
        )
        current = self._store.get_job(action.job_id)
        if current is None:
            raise ExternalActionDisabled("JOB_NOT_FOUND_AFTER_RESERVATION")
        with self._store.transaction(reservation_revision) as transaction_handle:
            transaction_handle.upsert_job(current.model_copy(update={"state": JobState.SUBMITTED}))
            transaction_handle.append_event(
                ApplicationEvent(
                    event_id=receipt.receipt_id,
                    job_id=action.job_id,
                    state=JobState.SUBMITTED,
                    occurred_at=now,
                    actor="mock_submitter",
                    event_type="submission_receipt",
                    details={
                        "idempotency_key": action.idempotency_key,
                        "status": receipt.status,
                    },
                )
            )
        return receipt


def get_submitter(
    mode: str,
    *,
    store: JobStore,
    now: Callable[[], datetime],
) -> Submitter:
    if mode != "mock":
        raise ExternalActionDisabled("only mock submission is enabled")
    return MockSubmitter(store, now=now)


__all__ = [
    "DuplicateSubmission",
    "ExternalActionDisabled",
    "MockSubmitter",
    "SubmissionReceipt",
    "Submitter",
    "get_submitter",
]
