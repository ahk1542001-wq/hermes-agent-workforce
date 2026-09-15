"""Safe, local-only private workspace primitives."""

from __future__ import annotations

import json
import os
import stat
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from .config import WorkspacePaths
from .models import WorkspaceMarker


class WorkspaceSafetyError(ValueError):
    """The requested path is not an approved private workspace."""


class WorkspaceLockTimeout(TimeoutError):
    """Another writer owns the workspace lock."""


_LOCK_EXPIRY_SECONDS = 30.0
_WORKSPACE_DIRS = (
    "master",
    "evidence",
    "applications",
    "reports",
    "pending-ai-os-updates",
    "data",
)
_FORBIDDEN_ROOTS = (
    Path.home(),
    Path("/Users/mac/Documents") / "Second Brain Test",
    Path("/Users/mac/Projects/code/hermes-agent-workforce"),
    Path("/Users/mac/.hermes"),
)


def _absolute(path: Path) -> Path:
    return path.expanduser().absolute()


def _has_symlink_component(path: Path) -> bool:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            if current.is_symlink():
                return True
        except OSError as exc:
            raise WorkspaceSafetyError(f"cannot inspect workspace path: {current}") from exc
    return False


def _contains_symlink(path: Path) -> bool:
    if not path.exists():
        return False
    pending = [path]
    while pending:
        current = pending.pop()
        try:
            info = current.lstat()
        except OSError as exc:
            raise WorkspaceSafetyError(f"cannot inspect workspace entry: {current}") from exc
        if stat.S_ISLNK(info.st_mode):
            return True
        if stat.S_ISDIR(info.st_mode):
            try:
                pending.extend(current.iterdir())
            except OSError as exc:
                raise WorkspaceSafetyError(
                    f"cannot inspect workspace directory: {current}"
                ) from exc
    return False


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _has_git_ancestor(path: Path) -> bool:
    current = path if path.is_dir() else path.parent
    while True:
        if (current / ".git").exists():
            return True
        if current == current.parent:
            return False
        current = current.parent


def assert_safe_private_root(root: Path) -> Path:
    """Validate a dedicated, real directory before any workspace write."""
    candidate = _absolute(root)
    if candidate == Path(candidate.anchor):
        raise WorkspaceSafetyError("filesystem root cannot be a private workspace")
    for forbidden in _FORBIDDEN_ROOTS:
        protected_descendant = forbidden != Path.home() and _inside(candidate, _absolute(forbidden))
        if candidate == _absolute(forbidden) or protected_descendant:
            raise WorkspaceSafetyError(
                "path is inside a protected system, vault, repository, or Hermes root"
            )
    if _has_symlink_component(candidate):
        raise WorkspaceSafetyError("workspace path crosses a symbolic link")
    if _has_git_ancestor(candidate):
        raise WorkspaceSafetyError("a Git worktree cannot be a private workspace")
    if candidate.exists() and not candidate.is_dir():
        raise WorkspaceSafetyError("private workspace root must be a directory")
    if not candidate.parent.exists() or not candidate.parent.is_dir():
        raise WorkspaceSafetyError("private workspace parent must already exist")
    if candidate.exists() and _contains_symlink(candidate):
        raise WorkspaceSafetyError("workspace contains a symbolic link")
    if candidate.exists():
        allowed = set(_WORKSPACE_DIRS) | {".job-scout-workspace.json", ".workspace.lock"}
        unknown = [entry.name for entry in candidate.iterdir() if entry.name not in allowed]
        if unknown:
            raise WorkspaceSafetyError("non-empty unrecognized workspace target")
    return candidate


def _chmod_private(path: Path, mode: int) -> None:
    os.chmod(path, mode)


def bootstrap_private_workspace(paths: WorkspacePaths) -> WorkspaceMarker:
    """Create the empty private tree and return its stable non-secret marker."""
    root = assert_safe_private_root(paths.root)
    if root != paths.root:
        raise WorkspaceSafetyError("workspace paths must be built from the validated root")
    root.mkdir(mode=0o700, exist_ok=True)
    _chmod_private(root, 0o700)
    for directory in (
        paths.master,
        paths.evidence,
        paths.education,
        paths.certificates,
        paths.project_metrics,
        paths.applications,
        paths.reports,
        paths.pending_ai_os_updates,
        paths.data,
    ):
        directory.mkdir(mode=0o700, exist_ok=True)
        _chmod_private(directory, 0o700)

    if paths.marker.exists():
        try:
            marker = WorkspaceMarker.model_validate_json(paths.marker.read_text(encoding="utf-8"))
        except Exception as exc:
            raise WorkspaceSafetyError("workspace marker is invalid") from exc
        return marker

    marker = WorkspaceMarker(marker_version=1, workspace_id=uuid4(), schema_version=1)
    _atomic_replace(paths.marker, marker.model_dump_json().encode("utf-8"))
    return marker


def _private_anchor(path: Path) -> Path | None:
    current = _absolute(path)
    while True:
        if (current / ".job-scout-workspace.json").is_file():
            return current
        if current == current.parent:
            return None
        current = current.parent


def atomic_write_private(path: Path, data: bytes) -> None:
    """Write one private file atomically, without leaving a temporary file."""
    target = _absolute(path)
    if _has_symlink_component(target) or target.is_symlink():
        raise WorkspaceSafetyError("private file path crosses a symbolic link")
    if not target.parent.is_dir() or _contains_symlink(target.parent):
        raise WorkspaceSafetyError("private file parent is not a real directory")
    anchor = _private_anchor(target.parent)
    if (
        anchor is None
        or not _inside(target, anchor)
        or stat.S_IMODE(anchor.stat().st_mode) != 0o700
    ):
        raise WorkspaceSafetyError("private file must be inside a bootstrapped workspace")
    if target.exists() and not target.is_file():
        raise WorkspaceSafetyError("private write target must be a regular file")

    _atomic_replace(target, data)


def _atomic_replace(target: Path, data: bytes) -> None:
    """Perform the atomic replace after the caller has validated its boundary."""
    temporary = target.parent / f".{target.name}.{uuid4().hex}.tmp"
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        _chmod_private(target, 0o600)
        try:
            directory_fd = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            # Directory fsync is not supported on every filesystem; the file
            # itself has already been flushed and atomically replaced.
            pass
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def _pid_is_alive(pid: int) -> bool | None:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None
    return True


def _read_lock(path: Path) -> tuple[int, float] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        pid = payload["pid"]
        created_at = payload["created_at"]
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            return None
        if not isinstance(created_at, (int, float)) or isinstance(created_at, bool):
            return None
        if created_at <= 0:
            return None
        return pid, float(created_at)
    except (OSError, ValueError, TypeError, KeyError):
        return None


@contextmanager
def workspace_lock(paths: WorkspacePaths, timeout_seconds: float = 2.5) -> Iterator[None]:
    """Acquire a non-stealable, bounded lock for state-changing operations."""
    if timeout_seconds < 0:
        raise ValueError("timeout must not be negative")
    root = assert_safe_private_root(paths.root)
    if root != paths.root or not paths.marker.exists():
        raise WorkspaceSafetyError("workspace must be bootstrapped before locking")

    started = time.monotonic()
    created_at = time.time()
    payload = json.dumps({"pid": os.getpid(), "created_at": created_at}, separators=(",", ":"))
    acquired = False
    while not acquired:
        try:
            descriptor = os.open(paths.lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            _chmod_private(paths.lock, 0o600)
            acquired = True
        except FileExistsError:
            lock_data = _read_lock(paths.lock)
            stale = False
            if lock_data is not None:
                owner_alive = _pid_is_alive(lock_data[0])
                stale = owner_alive is False
            else:
                try:
                    stale = time.time() - paths.lock.stat().st_mtime > _LOCK_EXPIRY_SECONDS
                except OSError:
                    stale = False
            if stale:
                try:
                    paths.lock.unlink()
                except FileNotFoundError:
                    pass
                continue
            if time.monotonic() - started >= timeout_seconds:
                raise WorkspaceLockTimeout("workspace lock is held by a live or unknown owner")
            time.sleep(min(0.02, max(0.001, timeout_seconds / 20)))

    try:
        yield
    finally:
        try:
            if paths.lock.read_text(encoding="utf-8") == payload:
                paths.lock.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            # Never remove another writer's replacement lock.
            pass
