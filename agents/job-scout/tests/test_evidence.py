import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from hermes_job_scout.config import WorkspacePaths
from hermes_job_scout.evidence import (
    EvidenceApproval,
    EvidenceApprovalError,
    EvidencePackError,
    approve_evidence_pack,
    load_evidence_pack,
    require_approved_evidence,
)
from hermes_job_scout.models import CandidateProfile
from hermes_job_scout.workspace import atomic_write_private, bootstrap_private_workspace

NOW = datetime(2026, 9, 16, 9, 0, tzinfo=timezone.utc)


def _profile() -> CandidateProfile:
    return CandidateProfile.model_validate(
        {
            "candidate_id": "candidate-example",
            "display_name": "Alex Example",
            "headline": "Automation builder",
            "summary": "Built a deterministic automation demo.",
            "facts": [
                {
                    "fact_id": "fact-summary",
                    "category": "project",
                    "allowed_wording": "Built a deterministic automation demo.",
                    "source": "synthetic fixture",
                    "verified": True,
                }
            ],
            "skills": [],
            "languages": {},
            "experience": [],
            "education": [],
        }
    )


def _markdown(profile: CandidateProfile, suffix: str = "") -> str:
    return (
        "# Candidate Evidence Pack\n\n```json\n"
        + profile.model_dump_json(indent=2)
        + "\n```\n"
        + suffix
    )


def test_evidence_pack_loads_one_profile_block_and_binds_complete_markdown(tmp_path: Path) -> None:
    paths = WorkspacePaths.from_root(tmp_path / "Career")
    bootstrap_private_workspace(paths)
    pack_path = paths.master / "candidate-facts-private.md"
    atomic_write_private(pack_path, _markdown(_profile()).encode("utf-8"))

    pack = load_evidence_pack(pack_path)

    assert pack.candidate_profile.candidate_id == "candidate-example"
    assert len(pack.pack_sha256) == 64
    assert pack.raw_markdown == pack_path.read_bytes()


def test_changed_pack_invalidates_owner_approval(tmp_path: Path) -> None:
    paths = WorkspacePaths.from_root(tmp_path / "Career")
    bootstrap_private_workspace(paths)
    pack_path = paths.master / "candidate-facts-private.md"
    atomic_write_private(pack_path, _markdown(_profile()).encode("utf-8"))
    approval = approve_evidence_pack(
        load_evidence_pack(pack_path), paths.master / "evidence-approval.json", NOW
    )
    atomic_write_private(pack_path, _markdown(_profile(), "\nUpdated prose.").encode("utf-8"))

    with pytest.raises(EvidenceApprovalError):
        require_approved_evidence(load_evidence_pack(pack_path), approval)


def test_approval_is_owner_bound_and_private(tmp_path: Path) -> None:
    paths = WorkspacePaths.from_root(tmp_path / "Career")
    bootstrap_private_workspace(paths)
    pack_path = paths.master / "candidate-facts-private.md"
    approval_path = paths.master / "evidence-approval.json"
    atomic_write_private(pack_path, _markdown(_profile()).encode("utf-8"))
    approval = approve_evidence_pack(load_evidence_pack(pack_path), approval_path, NOW)

    assert approval.approved_by == "owner"
    assert json.loads(approval_path.read_text(encoding="utf-8"))["schema_version"] == 1
    require_approved_evidence(load_evidence_pack(pack_path), approval)


def test_pack_must_be_private_regular_file(tmp_path: Path) -> None:
    paths = WorkspacePaths.from_root(tmp_path / "Career")
    bootstrap_private_workspace(paths)
    pack_path = paths.master / "candidate-facts-private.md"
    pack_path.write_text(_markdown(_profile()), encoding="utf-8")
    with pytest.raises(EvidencePackError):
        load_evidence_pack(pack_path)


def test_approval_rejects_extra_fields_and_cross_workspace(tmp_path: Path) -> None:
    paths = WorkspacePaths.from_root(tmp_path / "Career")
    other = WorkspacePaths.from_root(tmp_path / "Other")
    bootstrap_private_workspace(paths)
    bootstrap_private_workspace(other)
    pack_path = paths.master / "candidate-facts-private.md"
    atomic_write_private(pack_path, _markdown(_profile()).encode("utf-8"))
    approval = approve_evidence_pack(
        load_evidence_pack(pack_path), paths.master / "evidence-approval.json", NOW
    )
    with pytest.raises(ValidationError):
        EvidenceApproval.model_validate({**approval.model_dump(), "extra": "no"})
    with pytest.raises(EvidenceApprovalError):
        require_approved_evidence(load_evidence_pack(pack_path), other.marker)


def test_evidence_requires_exactly_one_json_profile_block(tmp_path: Path) -> None:
    pack_path = tmp_path / "candidate-facts-private.md"
    pack_path.write_text("```json\n{}\n```\n```json\n{}\n```\n", encoding="utf-8")
    with pytest.raises(EvidencePackError):
        load_evidence_pack(pack_path)
