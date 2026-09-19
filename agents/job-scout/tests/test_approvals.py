from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from hermes_job_scout.approvals import (
    SubmissionAction,
    hash_payload,
    validate_approval,
)
from hermes_job_scout.models import ApprovalGrant

NOW = datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc)
PAYLOAD = {"answers": {"work_authorization": "Requires employer support"}, "message": "Hello"}


def _grant(**updates: object) -> ApprovalGrant:
    values: dict[str, object] = {
        "approval_id": "approval-1",
        "job_id": "job-1",
        "recipient": "jobs@example.com",
        "payload_sha256": hash_payload(PAYLOAD),
        "attachment_sha256": ["a" * 64],
        "issued_at": NOW - timedelta(minutes=5),
        "expires_at": NOW + timedelta(hours=2),
    }
    values.update(updates)
    return ApprovalGrant.model_validate(values)


def _action(**updates: object) -> SubmissionAction:
    values: dict[str, object] = {
        "job_id": "job-1",
        "approval_id": "approval-1",
        "recipient": "jobs@example.com",
        "payload_sha256": hash_payload(PAYLOAD),
        "attachment_sha256": ("a" * 64,),
        "idempotency_key": "submit-job-1-v1",
        "required_owner_fields": ("work_authorization",),
        "owner_confirmed_fields": ("work_authorization",),
        "expected_revision": 1,
    }
    values.update(updates)
    return SubmissionAction(**values)


def test_hash_payload_is_canonical_and_rejects_non_json_values() -> None:
    assert hash_payload({"b": 2, "a": 1}) == hash_payload({"a": 1, "b": 2})
    with pytest.raises(ValueError, match="canonical JSON"):
        hash_payload({"bad": {1, 2}})


def test_exact_approval_is_valid() -> None:
    result = validate_approval(_grant(), _action(), NOW)
    assert result.allowed is True
    assert result.code == "VALID"


def test_expired_approval_is_rejected() -> None:
    grant = _grant(expires_at=NOW - timedelta(seconds=1))
    assert validate_approval(grant, _action(), NOW).code == "APPROVAL_EXPIRED"


@pytest.mark.parametrize(
    ("grant_updates", "action_updates", "code"),
    [
        ({"job_id": "job-2"}, {}, "JOB_ID_MISMATCH"),
        ({"approval_id": "approval-2"}, {}, "APPROVAL_ID_MISMATCH"),
        ({"recipient": "other@example.com"}, {}, "RECIPIENT_MISMATCH"),
        ({"payload_sha256": "b" * 64}, {}, "PAYLOAD_HASH_MISMATCH"),
    ],
)
def test_changed_action_fields_invalidate_approval(
    grant_updates: dict[str, object], action_updates: dict[str, object], code: str
) -> None:
    result = validate_approval(_grant(**grant_updates), _action(**action_updates), NOW)
    assert result.allowed is False
    assert result.code == code


def test_attachment_change_invalidates_approval() -> None:
    grant = _grant(attachment_sha256=["a" * 64])
    action = _action(attachment_sha256=("b" * 64,))
    assert validate_approval(grant, action, NOW).code == "ATTACHMENT_HASH_MISMATCH"


def test_missing_owner_required_fields_fail_closed() -> None:
    action = _action(
        required_owner_fields=("work_authorization", "legal_declaration"),
        owner_confirmed_fields=("work_authorization",),
    )
    result = validate_approval(_grant(), action, NOW)
    assert result.allowed is False
    assert result.code == "OWNER_FIELDS_MISSING"


def test_naive_validation_time_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone"):
        validate_approval(_grant(), _action(), NOW.replace(tzinfo=None))
