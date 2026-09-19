"""Exact, expiring approval binding for one synthetic or external action."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .models import ApprovalGrant


@dataclass(frozen=True)
class SubmissionAction:
    job_id: str
    approval_id: str
    recipient: str
    payload_sha256: str
    attachment_sha256: tuple[str, ...]
    idempotency_key: str
    required_owner_fields: tuple[str, ...]
    owner_confirmed_fields: tuple[str, ...]
    expected_revision: int
    approval: ApprovalGrant | None = None

    def __post_init__(self) -> None:
        if not self.job_id or not self.approval_id or not self.recipient:
            raise ValueError("submission identity fields cannot be blank")
        if not self.idempotency_key:
            raise ValueError("idempotency_key cannot be blank")
        if self.expected_revision < 0:
            raise ValueError("expected_revision cannot be negative")
        hashes = (self.payload_sha256, *self.attachment_sha256)
        if any(
            len(value) != 64 or any(char not in "0123456789abcdefABCDEF" for char in value)
            for value in hashes
        ):
            raise ValueError("payload and attachment hashes must be SHA-256 hex values")


@dataclass(frozen=True)
class ApprovalValidation:
    allowed: bool
    code: str


def hash_payload(canonical_json: Any) -> str:
    """Hash a JSON value after stable canonical serialization."""

    try:
        value = json.loads(canonical_json) if isinstance(canonical_json, str) else canonical_json
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("payload must be valid canonical JSON data") from exc
    return hashlib.sha256(encoded).hexdigest()


def validate_approval(
    grant: ApprovalGrant,
    action: SubmissionAction,
    now: datetime,
) -> ApprovalValidation:
    """Validate every approval-bound field without inference or fallback."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("approval validation time must include a timezone")
    if now < grant.issued_at:
        return ApprovalValidation(False, "APPROVAL_NOT_ACTIVE")
    if now >= grant.expires_at:
        return ApprovalValidation(False, "APPROVAL_EXPIRED")
    if grant.job_id != action.job_id:
        return ApprovalValidation(False, "JOB_ID_MISMATCH")
    if grant.approval_id != action.approval_id:
        return ApprovalValidation(False, "APPROVAL_ID_MISMATCH")
    if grant.recipient != action.recipient:
        return ApprovalValidation(False, "RECIPIENT_MISMATCH")
    if grant.payload_sha256.casefold() != action.payload_sha256.casefold():
        return ApprovalValidation(False, "PAYLOAD_HASH_MISMATCH")
    if tuple(value.casefold() for value in grant.attachment_sha256) != tuple(
        value.casefold() for value in action.attachment_sha256
    ):
        return ApprovalValidation(False, "ATTACHMENT_HASH_MISMATCH")
    if not set(action.required_owner_fields).issubset(action.owner_confirmed_fields):
        return ApprovalValidation(False, "OWNER_FIELDS_MISSING")
    return ApprovalValidation(True, "VALID")


__all__ = ["ApprovalValidation", "SubmissionAction", "hash_payload", "validate_approval"]
