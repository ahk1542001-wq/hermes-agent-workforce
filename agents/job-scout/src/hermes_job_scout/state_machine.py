"""Append-only, revision-checked state transitions for Job Scout records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping
from uuid import uuid4

from .database import JobStore
from .models import ApplicationEvent, JobRecord, JobState


class InvalidTransition(RuntimeError):
    """The requested transition is absent, stale, or lacks required evidence."""


@dataclass(frozen=True)
class TransitionContext:
    store: JobStore
    expected_revision: int
    actor: str
    occurred_at: datetime
    evidence: Mapping[str, str]
    new_evidence: bool = False


_NORMAL_NEXT = {
    JobState.DISCOVERED: JobState.VERIFIED,
    JobState.VERIFIED: JobState.QUALIFIED,
    JobState.QUALIFIED: JobState.SHORTLISTED,
    JobState.SHORTLISTED: JobState.SELECTED,
    JobState.SELECTED: JobState.PACK_DRAFTED,
    JobState.PACK_DRAFTED: JobState.PACK_REVIEWED,
    JobState.PACK_REVIEWED: JobState.PACK_APPROVED,
    JobState.PACK_APPROVED: JobState.SUBMITTING,
    JobState.SUBMITTING: JobState.SUBMITTED,
    JobState.SUBMITTED: JobState.FOLLOW_UP_DUE,
    JobState.FOLLOW_UP_DUE: JobState.CLOSED,
}
_EXCEPTIONAL = {
    JobState.DISCOVERED: {
        JobState.REJECTED,
        JobState.EXPIRED,
        JobState.DUPLICATE,
        JobState.NEEDS_VICTOR,
    },
    JobState.VERIFIED: {
        JobState.REJECTED,
        JobState.EXPIRED,
        JobState.DUPLICATE,
        JobState.NEEDS_VICTOR,
    },
    JobState.QUALIFIED: {
        JobState.REJECTED,
        JobState.EXPIRED,
        JobState.DUPLICATE,
        JobState.NEEDS_VICTOR,
    },
    JobState.SHORTLISTED: {JobState.EXPIRED, JobState.NEEDS_VICTOR, JobState.WITHDRAWN},
    JobState.SELECTED: {JobState.EXPIRED, JobState.NEEDS_VICTOR, JobState.WITHDRAWN},
    JobState.PACK_DRAFTED: {JobState.EXPIRED, JobState.NEEDS_VICTOR, JobState.WITHDRAWN},
    JobState.PACK_REVIEWED: {JobState.EXPIRED, JobState.NEEDS_VICTOR, JobState.WITHDRAWN},
    JobState.PACK_APPROVED: {JobState.EXPIRED, JobState.NEEDS_VICTOR, JobState.WITHDRAWN},
    JobState.SUBMITTING: {JobState.FAILED_UNCONFIRMED},
    JobState.SUBMITTED: {JobState.NEEDS_VICTOR, JobState.WITHDRAWN},
    JobState.FOLLOW_UP_DUE: {JobState.NEEDS_VICTOR, JobState.WITHDRAWN},
    JobState.FAILED_UNCONFIRMED: {JobState.NEEDS_VICTOR},
    JobState.REJECTED: {JobState.ARCHIVED},
    JobState.EXPIRED: {JobState.ARCHIVED},
    JobState.DUPLICATE: {JobState.ARCHIVED},
    JobState.WITHDRAWN: {JobState.ARCHIVED},
    JobState.CLOSED: {JobState.ARCHIVED},
}


def is_transition_allowed(current: JobState, target: JobState, *, new_evidence: bool) -> bool:
    if current is JobState.FAILED_UNCONFIRMED and target is JobState.NEEDS_VICTOR:
        return new_evidence
    return _NORMAL_NEXT.get(current) is target or target in _EXCEPTIONAL.get(current, set())


def transition(job_id: str, target: JobState, context: TransitionContext) -> int:
    """Update current state and append its event in one revision-checked transaction."""

    if context.occurred_at.tzinfo is None or context.occurred_at.utcoffset() is None:
        raise ValueError("transition time must include a timezone")
    if not context.actor:
        raise ValueError("transition actor cannot be blank")
    current = context.store.get_job(job_id)
    if current is None:
        raise InvalidTransition(f"job {job_id!r} does not exist")
    if not is_transition_allowed(current.state, target, new_evidence=context.new_evidence):
        if current.state is JobState.FAILED_UNCONFIRMED and not context.new_evidence:
            raise InvalidTransition("FAILED_UNCONFIRMED requires new evidence before recovery")
        raise InvalidTransition(
            f"transition {current.state.value} -> {target.value} is not allowed"
        )

    try:
        updated = JobRecord.model_validate({**current.model_dump(mode="python"), "state": target})
    except ValueError as exc:
        raise InvalidTransition("target state violates job invariants") from exc
    event = ApplicationEvent(
        event_id=f"transition-{uuid4().hex}",
        job_id=job_id,
        state=target,
        occurred_at=context.occurred_at,
        actor=context.actor,
        event_type="state_transition",
        details={
            **dict(context.evidence),
            "from": current.state.value,
            "to": target.value,
        },
    )
    with context.store.transaction(context.expected_revision) as transaction_handle:
        transaction_handle.upsert_job(updated)
        transaction_handle.append_event(event)
    return context.store.current_revision()


__all__ = ["InvalidTransition", "TransitionContext", "is_transition_allowed", "transition"]
