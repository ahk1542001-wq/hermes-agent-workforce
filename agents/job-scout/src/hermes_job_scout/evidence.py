"""Candidate Evidence Pack parsing and owner-approval binding."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import CandidateProfile
from .workspace import atomic_write_private


class EvidencePackError(ValueError):
    """The private Evidence Pack is malformed or does not validate."""


class EvidenceApprovalError(ValueError):
    """An approval is missing, malformed, or no longer binds to the pack."""


@dataclass(frozen=True, slots=True)
class EvidencePack:
    candidate_profile: CandidateProfile
    pack_sha256: str
    raw_markdown: bytes
    path: Path

    @property
    def profile(self) -> CandidateProfile:
        return self.candidate_profile

    @property
    def sha256(self) -> str:
        return self.pack_sha256


@dataclass(frozen=True, slots=True)
class EvidenceApproval:
    pack_sha256: str
    approved_at: datetime
    approved_by: str
    schema_version: int = 1


_FENCE_RE = re.compile(r"```([^\r\n`]*)\r?\n(.*?)```", re.DOTALL)


def load_evidence_pack(path: Path) -> EvidencePack:
    """Load exactly one JSON CandidateProfile block and hash all Markdown bytes."""
    candidate_path = path.expanduser().absolute()
    try:
        raw = candidate_path.read_bytes()
    except OSError as exc:
        raise EvidencePackError("cannot read Evidence Pack") from exc
    if candidate_path.is_symlink() or not candidate_path.is_file():
        raise EvidencePackError("Evidence Pack must be a regular file")

    try:
        markdown = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise EvidencePackError("Evidence Pack must be valid UTF-8 Markdown") from exc
    blocks = list(_FENCE_RE.finditer(markdown))
    if len(blocks) != 1 or blocks[0].group(1).strip().lower() != "json":
        raise EvidencePackError("Evidence Pack must contain exactly one fenced json block")
    try:
        payload: Any = json.loads(blocks[0].group(2))
        profile = CandidateProfile.model_validate(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise EvidencePackError("fenced JSON must be a valid CandidateProfile") from exc
    return EvidencePack(
        candidate_profile=profile,
        pack_sha256=hashlib.sha256(raw).hexdigest(),
        raw_markdown=raw,
        path=candidate_path,
    )


def approve_evidence_pack(
    pack: EvidencePack,
    approval_path: Path,
    approved_at: datetime,
) -> EvidenceApproval:
    """Write a small owner approval record bound to the complete Markdown hash."""
    if approved_at.tzinfo is None or approved_at.utcoffset() is None:
        raise EvidenceApprovalError("approval timestamp must include a timezone")
    approval = EvidenceApproval(
        pack_sha256=pack.pack_sha256,
        approved_at=approved_at,
        approved_by="owner",
        schema_version=1,
    )
    data = {
        "pack_sha256": approval.pack_sha256,
        "approved_at": approval.approved_at.isoformat(),
        "approved_by": approval.approved_by,
        "schema_version": approval.schema_version,
    }
    try:
        atomic_write_private(
            approval_path,
            json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        )
    except (OSError, ValueError) as exc:
        raise EvidenceApprovalError("approval record could not be written privately") from exc
    return approval


def _coerce_approval(approval: EvidenceApproval | Path) -> EvidenceApproval:
    if isinstance(approval, Path):
        try:
            payload = json.loads(approval.read_text(encoding="utf-8"))
            return EvidenceApproval(
                pack_sha256=payload["pack_sha256"],
                approved_at=datetime.fromisoformat(payload["approved_at"]),
                approved_by=payload["approved_by"],
                schema_version=payload["schema_version"],
            )
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise EvidenceApprovalError("approval record is malformed") from exc
    return approval


def require_approved_evidence(
    pack: EvidencePack,
    approval: EvidenceApproval | Path,
) -> EvidencePack:
    """Fail closed unless the exact current pack is approved by the owner."""
    record = _coerce_approval(approval)
    if record.schema_version != 1 or record.approved_by != "owner":
        raise EvidenceApprovalError("approval is not an owner approval for schema version 1")
    if record.approved_at.tzinfo is None or record.approved_at.utcoffset() is None:
        raise EvidenceApprovalError("approval timestamp must include a timezone")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", record.pack_sha256):
        raise EvidenceApprovalError("approval hash is not SHA-256")
    if record.pack_sha256 != pack.pack_sha256:
        raise EvidenceApprovalError("Evidence Pack changed after owner approval")
    return pack
