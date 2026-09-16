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
    assert pack.profile is pack.candidate_profile
    assert pack.sha256 == pack.pack_sha256
    assert pack.raw_markdown == pack_path.read_bytes()


@pytest.mark.parametrize(
    "overrides",
    [
        {"pack_sha256": "not-a-sha256"},
        {"approved_at": datetime(2026, 9, 16, 9, 0)},
        {"pack_relative_path": "../outside.md"},
    ],
)
def test_evidence_approval_rejects_malformed_bindings(overrides: dict[str, object]) -> None:
    payload: dict[str, object] = {
        "pack_sha256": "a" * 64,
        "approved_at": NOW,
        "approved_by": "owner",
        "schema_version": 1,
        "workspace_id": "11111111-1111-4111-8111-111111111111",
        "pack_relative_path": "master/candidate-facts-private.md",
    }
    payload.update(overrides)
    with pytest.raises(ValidationError):
        EvidenceApproval.model_validate(payload)


def test_evidence_pack_rejects_invalid_utf8_and_profile_json(tmp_path: Path) -> None:
    paths = WorkspacePaths.from_root(tmp_path / "Career")
    bootstrap_private_workspace(paths)
    pack_path = paths.master / "candidate-facts-private.md"
    atomic_write_private(pack_path, b"# Evidence\n\n```json\n\xff\n```\n")
    with pytest.raises(EvidencePackError, match="UTF-8"):
        load_evidence_pack(pack_path)
    atomic_write_private(pack_path, b"# Evidence\n\n```json\n{broken}\n```\n")
    with pytest.raises(EvidencePackError, match="CandidateProfile"):
        load_evidence_pack(pack_path)


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
        other_pack_path = other.master / "candidate-facts-private.md"
        atomic_write_private(other_pack_path, _markdown(_profile()).encode("utf-8"))
        other_approval = approve_evidence_pack(
            load_evidence_pack(other_pack_path), other.master / "evidence-approval.json", NOW
        )
        require_approved_evidence(load_evidence_pack(pack_path), other_approval)


def test_approval_destination_is_one_reserved_path_only(tmp_path: Path) -> None:
    paths = WorkspacePaths.from_root(tmp_path / "Career")
    bootstrap_private_workspace(paths)
    pack_path = paths.master / "candidate-facts-private.md"
    pack = _markdown(_profile()).encode("utf-8")
    atomic_write_private(pack_path, pack)
    loaded = load_evidence_pack(pack_path)
    for destination in (
        paths.root / "evidence-approval.json",
        paths.lock,
        paths.database,
        pack_path,
        paths.master / "other-approval.json",
    ):
        with pytest.raises(EvidenceApprovalError):
            approve_evidence_pack(loaded, destination, NOW)


def test_approval_rejects_swapped_foreign_workspace_before_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hermes_job_scout.workspace as workspace_module

    paths = WorkspacePaths.from_root(tmp_path / "Career")
    foreign = WorkspacePaths.from_root(tmp_path / "Foreign")
    bootstrap_private_workspace(paths)
    bootstrap_private_workspace(foreign)
    pack_path = paths.master / "candidate-facts-private.md"
    foreign_pack_path = foreign.master / "candidate-facts-private.md"
    atomic_write_private(pack_path, _markdown(_profile()).encode("utf-8"))
    atomic_write_private(foreign_pack_path, _markdown(_profile()).encode("utf-8"))
    loaded = load_evidence_pack(pack_path)
    real_root = paths.root.with_name("career-real")
    original = workspace_module._open_directory_from_raw
    swapped = False

    def swap(parent_fd: int, name: str) -> int:
        nonlocal swapped
        if name == paths.root.name and not swapped:
            paths.root.rename(real_root)
            foreign.root.rename(paths.root)
            swapped = True
        return original(parent_fd, name)

    monkeypatch.setattr(workspace_module, "_open_directory_from_raw", swap)
    with pytest.raises(EvidenceApprovalError):
        approve_evidence_pack(loaded, paths.master / "evidence-approval.json", NOW)
    paths.root.rename(foreign.root)
    real_root.rename(paths.root)
    assert not (paths.master / "evidence-approval.json").exists()


def test_require_rejects_identical_pack_bytes_in_swapped_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hermes_job_scout.workspace as workspace_module

    paths = WorkspacePaths.from_root(tmp_path / "Career")
    foreign = WorkspacePaths.from_root(tmp_path / "Foreign")
    bootstrap_private_workspace(paths)
    bootstrap_private_workspace(foreign)
    pack_path = paths.master / "candidate-facts-private.md"
    foreign_pack_path = foreign.master / "candidate-facts-private.md"
    pack_bytes = _markdown(_profile()).encode("utf-8")
    atomic_write_private(pack_path, pack_bytes)
    atomic_write_private(foreign_pack_path, pack_bytes)
    loaded = load_evidence_pack(pack_path)
    approval = approve_evidence_pack(loaded, paths.master / "evidence-approval.json", NOW)
    real_root = paths.root.with_name("career-real")
    original = workspace_module._open_directory_from_raw
    swapped = False

    def swap(parent_fd: int, name: str) -> int:
        nonlocal swapped
        if name == paths.root.name and not swapped:
            paths.root.rename(real_root)
            foreign.root.rename(paths.root)
            swapped = True
        return original(parent_fd, name)

    monkeypatch.setattr(workspace_module, "_open_directory_from_raw", swap)
    with pytest.raises(EvidenceApprovalError):
        require_approved_evidence(loaded, approval)
    paths.root.rename(foreign.root)
    real_root.rename(paths.root)


def test_evidence_requires_exactly_one_json_profile_block(tmp_path: Path) -> None:
    paths = WorkspacePaths.from_root(tmp_path / "Career")
    bootstrap_private_workspace(paths)
    pack_path = paths.master / "candidate-facts-private.md"
    atomic_write_private(pack_path, b"```json\n{}\n```\n```json\n{}\n```\n")
    with pytest.raises(EvidencePackError):
        load_evidence_pack(pack_path)
