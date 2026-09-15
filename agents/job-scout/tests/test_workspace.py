import json
import multiprocessing
import os
import stat
import time
from pathlib import Path
from typing import Any

import pytest

from hermes_job_scout.config import WorkspacePaths
from hermes_job_scout.workspace import (
    WorkspaceLockTimeout,
    WorkspaceSafetyError,
    assert_safe_private_root,
    atomic_write_private,
    bootstrap_private_workspace,
    workspace_lock,
)


def _hold_lock(root: str, ready: Any) -> None:
    paths = WorkspacePaths.from_root(Path(root))
    with workspace_lock(paths, timeout_seconds=2.5):
        ready.put("locked")
        time.sleep(1.0)


def test_bootstrap_creates_private_tree_and_stable_marker(tmp_path: Path) -> None:
    paths = WorkspacePaths.from_root(tmp_path / "Career")
    marker = bootstrap_private_workspace(paths)

    expected_dirs = [
        paths.root,
        paths.master,
        paths.evidence,
        paths.education,
        paths.certificates,
        paths.project_metrics,
        paths.applications,
        paths.reports,
        paths.pending_ai_os_updates,
        paths.data,
    ]
    assert all(path.is_dir() for path in expected_dirs)
    assert not paths.database.exists()
    assert set(json.loads(paths.marker.read_text(encoding="utf-8"))) == {
        "marker_version",
        "workspace_id",
        "schema_version",
    }
    assert marker == bootstrap_private_workspace(paths)
    assert stat.S_IMODE(paths.root.stat().st_mode) == 0o700
    assert stat.S_IMODE(paths.master.stat().st_mode) == 0o700
    assert stat.S_IMODE(paths.marker.stat().st_mode) == 0o600


def test_bootstrap_accepts_only_an_empty_precreated_root(tmp_path: Path) -> None:
    root = tmp_path / "Career"
    root.mkdir()
    paths = WorkspacePaths.from_root(root)

    bootstrap_private_workspace(paths)

    assert stat.S_IMODE(root.stat().st_mode) == 0o700


def test_allowed_named_entries_without_marker_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "Career"
    (root / "master").mkdir(parents=True)
    paths = WorkspacePaths.from_root(root)

    with pytest.raises(WorkspaceSafetyError):
        bootstrap_private_workspace(paths)


def test_atomic_write_is_private_and_replaces_complete_content(tmp_path: Path) -> None:
    paths = WorkspacePaths.from_root(tmp_path / "Career")
    bootstrap_private_workspace(paths)
    target = paths.reports / "run.json"

    atomic_write_private(target, b"complete")

    assert target.read_bytes() == b"complete"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert not list(paths.reports.glob(".run.json.*.tmp"))


def test_private_root_rejects_home_root_git_and_nested_symlinks(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceSafetyError):
        assert_safe_private_root(Path("/"))
    with pytest.raises(WorkspaceSafetyError):
        assert_safe_private_root(Path.home())

    git_root = tmp_path / "repo"
    (git_root / ".git").mkdir(parents=True)
    with pytest.raises(WorkspaceSafetyError):
        assert_safe_private_root(git_root / "private")

    unrecognized = tmp_path / "non-empty"
    unrecognized.mkdir()
    (unrecognized / "unknown.txt").write_text("x", encoding="utf-8")
    with pytest.raises(WorkspaceSafetyError):
        assert_safe_private_root(unrecognized)

    direct_link = tmp_path / "direct-link"
    direct_link.symlink_to(tmp_path / "target", target_is_directory=False)
    with pytest.raises(WorkspaceSafetyError):
        assert_safe_private_root(direct_link)

    nested_target = tmp_path / "nested-target"
    nested_target.mkdir()
    nested_link = tmp_path / "nested-link"
    nested_link.mkdir()
    (nested_link / "escape").symlink_to(nested_target, target_is_directory=True)
    with pytest.raises(WorkspaceSafetyError):
        assert_safe_private_root(nested_link)


def test_competing_writer_times_out_without_deleting_live_lock(tmp_path: Path) -> None:
    paths = WorkspacePaths.from_root(tmp_path / "Career")
    bootstrap_private_workspace(paths)
    ready: multiprocessing.Queue[str] = multiprocessing.Queue()
    process = multiprocessing.Process(target=_hold_lock, args=(str(paths.root), ready))
    process.start()
    assert ready.get(timeout=2) == "locked"

    with pytest.raises(WorkspaceLockTimeout):
        with workspace_lock(paths, timeout_seconds=0.1):
            raise AssertionError("a live lock must not be stolen")
    assert paths.lock.exists()
    process.join(timeout=3)
    assert process.exitcode == 0


def test_dead_lock_requires_confirmed_dead_owner_or_expiry(tmp_path: Path) -> None:
    paths = WorkspacePaths.from_root(tmp_path / "Career")
    bootstrap_private_workspace(paths)
    paths.lock.write_text("not-json", encoding="utf-8")
    os.chmod(paths.lock, 0o600)
    with workspace_lock(paths, timeout_seconds=0.2):
        assert paths.lock.exists()
    assert paths.lock.read_bytes() == b""


def test_lock_is_released_by_process_death(tmp_path: Path) -> None:
    paths = WorkspacePaths.from_root(tmp_path / "Career")
    bootstrap_private_workspace(paths)
    process = multiprocessing.Process(
        target=_hold_lock, args=(str(paths.root), multiprocessing.Queue())
    )
    process.start()
    process.terminate()
    process.join(timeout=3)
    assert process.exitcode is not None
    with workspace_lock(paths, timeout_seconds=0.2):
        assert paths.lock.exists()


def test_private_root_rejects_nested_symlink_created_after_bootstrap(tmp_path: Path) -> None:
    paths = WorkspacePaths.from_root(tmp_path / "Career")
    bootstrap_private_workspace(paths)
    (paths.reports / "escape").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(WorkspaceSafetyError):
        atomic_write_private(paths.reports / "escape" / "report.md", b"no")


def test_forged_workspace_paths_are_rejected(tmp_path: Path) -> None:
    paths = WorkspacePaths.from_root(tmp_path / "Career")
    bootstrap_private_workspace(paths)
    forged = paths.__class__(
        root=paths.root,
        master=paths.root / "elsewhere",
        evidence=paths.evidence,
        education=paths.education,
        certificates=paths.certificates,
        project_metrics=paths.project_metrics,
        applications=paths.applications,
        reports=paths.reports,
        pending_ai_os_updates=paths.pending_ai_os_updates,
        data=paths.data,
        database=paths.database,
        marker=paths.marker,
        lock=paths.lock,
    )
    with pytest.raises(WorkspaceSafetyError):
        with workspace_lock(forged):
            pass
