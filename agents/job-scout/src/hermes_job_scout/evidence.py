"""Candidate Evidence Pack parsing and owner-approval binding."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from .models import CandidateProfile, WorkspaceMarker
from .workspace import WorkspaceSafetyError, atomic_write_private, read_private_bytes


class EvidencePackError(ValueError):
    """The private Evidence Pack is malformed or does not validate."""


class EvidenceApprovalError(ValueError):
    """An approval is missing, malformed, or no longer binds to the pack."""


class EvidenceApproval(BaseModel):
    """Strict owner approval bound to one workspace-relative pack."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    pack_sha256: str
    approved_at: datetime
    approved_by: Literal["owner"]
    schema_version: Literal[1]
    workspace_id: UUID
    pack_relative_path: str

    @field_validator("pack_sha256")
    @classmethod
    def _hash_is_sha256(cls, value: str) -> str:
        if not re.fullmatch(r"[0-9a-fA-F]{64}", value):
            raise ValueError("pack hash must be SHA-256")
        return value.lower()

    @field_validator("approved_at")
    @classmethod
    def _timestamp_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("approval timestamp must include a timezone")
        return value

    @field_validator("pack_relative_path")
    @classmethod
    def _path_is_relative(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or not value or ".." in path.parts or "." in path.parts:
            raise ValueError("pack path must be a normalized relative path")
        return value


class EvidencePack:
    """Validated CandidateProfile plus its current complete-Markdown binding."""

    __slots__ = (
        "candidate_profile",
        "pack_sha256",
        "raw_markdown",
        "path",
        "workspace_root",
        "workspace_id",
        "pack_relative_path",
    )

    def __init__(
        self,
        candidate_profile: CandidateProfile,
        pack_sha256: str,
        raw_markdown: bytes,
        path: Path,
        workspace_root: Path,
        workspace_id: UUID,
        pack_relative_path: PurePosixPath,
    ) -> None:
        self.candidate_profile = candidate_profile
        self.pack_sha256 = pack_sha256
        self.raw_markdown = raw_markdown
        self.path = path
        self.workspace_root = workspace_root
        self.workspace_id = workspace_id
        self.pack_relative_path = pack_relative_path

    @property
    def profile(self) -> CandidateProfile:
        return self.candidate_profile

    @property
    def sha256(self) -> str:
        return self.pack_sha256


_FENCE_RE = re.compile(r"```([^\r\n`]*)\r?\n(.*?)```", re.DOTALL)


def load_evidence_pack(path: Path) -> EvidencePack:
    """Securely load one JSON CandidateProfile block from a private file."""
    candidate_path = path.expanduser().absolute()
    try:
        raw, root, marker, relative = read_private_bytes(candidate_path)
    except WorkspaceSafetyError as exc:
        raise EvidencePackError("Evidence Pack must be a private 0600 workspace file") from exc
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
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise EvidencePackError("fenced JSON must be a valid CandidateProfile") from exc
    return EvidencePack(
        candidate_profile=profile,
        pack_sha256=hashlib.sha256(raw).hexdigest(),
        raw_markdown=raw,
        path=candidate_path,
        workspace_root=root,
        workspace_id=marker.workspace_id,
        pack_relative_path=relative,
    )


def approve_evidence_pack(
    pack: EvidencePack,
    approval_path: Path,
    approved_at: datetime,
) -> EvidenceApproval:
    """Write strict owner approval only for the current pack in its workspace."""
    try:
        current = load_evidence_pack(pack.path)
    except EvidencePackError as exc:
        raise EvidenceApprovalError("current Evidence Pack is invalid") from exc
    if current.pack_sha256 != pack.pack_sha256:
        raise EvidenceApprovalError("in-memory Evidence Pack is stale")
    destination = approval_path.expanduser().absolute()
    expected_destination = current.workspace_root / "master" / "evidence-approval.json"
    if destination != expected_destination:
        raise EvidenceApprovalError(
            "approval destination must be the workspace master approval file"
        )
    approval = EvidenceApproval(
        pack_sha256=current.pack_sha256,
        approved_at=approved_at,
        approved_by="owner",
        schema_version=1,
        workspace_id=current.workspace_id,
        pack_relative_path=current.pack_relative_path.as_posix(),
    )
    try:
        atomic_write_private(
            destination,
            approval.model_dump_json(by_alias=False).encode("utf-8"),
        )
    except (OSError, ValueError, WorkspaceSafetyError) as exc:
        raise EvidenceApprovalError("approval record could not be written privately") from exc
    return approval


def _coerce_approval(
    approval: EvidenceApproval | Path,
) -> tuple[EvidenceApproval, Path | None, WorkspaceMarker | None, PurePosixPath | None]:
    if isinstance(approval, Path):
        try:
            raw, root, marker, relative = read_private_bytes(approval)
            return EvidenceApproval.model_validate_json(raw), root, marker, relative
        except (OSError, ValueError, WorkspaceSafetyError) as exc:
            raise EvidenceApprovalError("approval record is malformed or not private") from exc
    if not isinstance(approval, EvidenceApproval):
        raise EvidenceApprovalError("approval record has an invalid type")
    return approval, None, None, None


def require_approved_evidence(
    pack: EvidencePack,
    approval: EvidenceApproval | Path,
) -> EvidencePack:
    """Reload and validate the current pack before accepting an approval."""
    try:
        current = load_evidence_pack(pack.path)
    except EvidencePackError as exc:
        raise EvidenceApprovalError("current Evidence Pack is invalid") from exc
    if current.pack_sha256 != pack.pack_sha256:
        raise EvidenceApprovalError("in-memory Evidence Pack is stale")
    record, approval_root, approval_marker, approval_relative = _coerce_approval(approval)
    if approval_root is not None and approval_root != current.workspace_root:
        raise EvidenceApprovalError("approval file belongs to another workspace")
    if approval_marker is not None and approval_marker.workspace_id != current.workspace_id:
        raise EvidenceApprovalError("approval marker belongs to another workspace")
    if approval_relative is not None and approval_relative != PurePosixPath(
        "master/evidence-approval.json"
    ):
        raise EvidenceApprovalError("approval file is not the reserved approval path")
    if record.workspace_id != current.workspace_id:
        raise EvidenceApprovalError("approval belongs to another workspace")
    if record.pack_relative_path != current.pack_relative_path.as_posix():
        raise EvidenceApprovalError("approval belongs to another pack path")
    if record.pack_sha256 != current.pack_sha256:
        raise EvidenceApprovalError("Evidence Pack changed after owner approval")
    return current
