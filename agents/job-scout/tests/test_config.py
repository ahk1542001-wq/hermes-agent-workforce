from pathlib import Path

import pytest

from hermes_job_scout.config import WorkspacePaths


def test_workspace_paths_are_deterministic_and_private(tmp_path: Path) -> None:
    paths = WorkspacePaths.from_root(tmp_path / "Career")

    assert paths.root == (tmp_path / "Career").absolute()
    assert paths.master == paths.root / "master"
    assert paths.education == paths.root / "evidence" / "education"
    assert paths.certificates == paths.root / "evidence" / "certificates"
    assert paths.project_metrics == paths.root / "evidence" / "project-metrics"
    assert paths.applications == paths.root / "applications"
    assert paths.reports == paths.root / "reports"
    assert paths.pending_ai_os_updates == paths.root / "pending-ai-os-updates"
    assert paths.data == paths.root / "data"
    assert paths.database == paths.data / "jobs.sqlite"
    assert paths.marker == paths.root / ".job-scout-workspace.json"
    assert paths.lock == paths.root / ".workspace.lock"


def test_paths_reject_non_directory_roots(tmp_path: Path) -> None:
    file_path = tmp_path / "not-a-directory"
    file_path.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        WorkspacePaths.from_root(file_path)
