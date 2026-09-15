"""Safe, local-only private workspace primitives."""

from __future__ import annotations

import fcntl
import json
import os
import stat
import time
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Iterator
from uuid import uuid4

from .config import WorkspacePaths
from .models import WorkspaceMarker


class WorkspaceSafetyError(ValueError):
    """The requested path is not an approved private workspace."""


class WorkspaceLockTimeout(TimeoutError):
    """Another writer owns the workspace lock."""


_WORKSPACE_DIRS = (
    "master",
    "evidence",
    "applications",
    "reports",
    "pending-ai-os-updates",
    "data",
)
_PRIVATE_MODE = 0o600
_DIRECTORY_MODE = 0o700
_ROOT = Path(__file__).absolute().parents[4]
_FORBIDDEN_ROOTS = (
    Path.home() / "Documents" / "Second Brain Test",
    _ROOT,
    Path.home() / ".hermes",
)


def _absolute(path: Path) -> Path:
    return path.expanduser().absolute()


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _has_symlink_component(path: Path) -> bool:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            return True
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


def _has_git_ancestor(path: Path) -> bool:
    current = path if path.is_dir() else path.parent
    while True:
        if (current / ".git").exists():
            return True
        if current == current.parent:
            return False
        current = current.parent


def _marker_from_file(path: Path) -> WorkspaceMarker:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != _PRIVATE_MODE:
            raise WorkspaceSafetyError("workspace marker must be a private regular file")
        return WorkspaceMarker.model_validate_json(path.read_text(encoding="utf-8"))
    except WorkspaceSafetyError:
        raise
    except Exception as exc:
        raise WorkspaceSafetyError("workspace marker is invalid") from exc


def _validate_existing_workspace(root: Path) -> WorkspaceMarker:
    if not root.is_dir() or stat.S_IMODE(root.stat().st_mode) != _DIRECTORY_MODE:
        raise WorkspaceSafetyError("existing private workspace must be a 0700 directory")
    if _contains_symlink(root):
        raise WorkspaceSafetyError("workspace contains a symbolic link")
    marker = root / ".job-scout-workspace.json"
    if not marker.exists():
        raise WorkspaceSafetyError("existing target lacks a valid workspace marker")
    return _marker_from_file(marker)


def _canonical_paths(paths: WorkspacePaths) -> WorkspacePaths:
    canonical = WorkspacePaths.from_root(paths.root)
    if paths != canonical:
        raise WorkspaceSafetyError("WorkspacePaths fields must match their canonical root")
    return canonical


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
    if candidate.exists() and any(candidate.iterdir()):
        _validate_existing_workspace(candidate)
    return candidate


def _open_directory(path: Path, *, dir_fd: int | None = None) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        return os.open(path, flags, dir_fd=dir_fd)
    except OSError as exc:
        raise WorkspaceSafetyError(f"cannot open private directory: {path}") from exc


def _open_relative_directory(root: Path, relative: PurePosixPath) -> int:
    descriptor = _open_directory(root)
    try:
        root_info = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(root_info.st_mode)
            or stat.S_IMODE(root_info.st_mode) != _DIRECTORY_MODE
        ):
            raise WorkspaceSafetyError("private workspace root must be a 0700 directory")
        for component in relative.parts:
            if component in {"", ".", ".."}:
                raise WorkspaceSafetyError("private path contains an unsafe component")
            next_descriptor = _open_directory(Path(component), dir_fd=descriptor)
            next_info = os.fstat(next_descriptor)
            if (
                not stat.S_ISDIR(next_info.st_mode)
                or stat.S_IMODE(next_info.st_mode) != _DIRECTORY_MODE
            ):
                os.close(next_descriptor)
                raise WorkspaceSafetyError("private workspace directory must be 0700")
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _workspace_for_path(path: Path) -> tuple[Path, WorkspaceMarker, PurePosixPath]:
    target = _absolute(path)
    if _has_symlink_component(target):
        raise WorkspaceSafetyError("private path crosses a symbolic link")
    current = target.parent
    while current != current.parent:
        marker_path = current / ".job-scout-workspace.json"
        if marker_path.is_file():
            marker = _validate_existing_workspace(current)
            relative = PurePosixPath(os.path.relpath(target, current))
            if relative.is_absolute() or ".." in relative.parts:
                raise WorkspaceSafetyError("private path is outside its workspace")
            return current, marker, relative
        current = current.parent
    raise WorkspaceSafetyError("private path is outside a bootstrapped workspace")


def _atomic_replace_in_directory(parent: Path, name: str, data: bytes) -> None:
    parent_fd = _open_directory(parent)
    temporary_name = f".{name}.{uuid4().hex}.tmp"
    temporary_fd: int | None = None
    try:
        try:
            existing = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if (
                not stat.S_ISREG(existing.st_mode)
                or stat.S_IMODE(existing.st_mode) != _PRIVATE_MODE
            ):
                raise WorkspaceSafetyError("private write target must be a regular file")
        except FileNotFoundError:
            pass
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        temporary_fd = os.open(temporary_name, flags, _PRIVATE_MODE, dir_fd=parent_fd)
        with os.fdopen(temporary_fd, "wb") as handle:
            temporary_fd = None
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.rename(temporary_name, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        target_fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
        try:
            target_info = os.fstat(target_fd)
            if not stat.S_ISREG(target_info.st_mode):
                raise WorkspaceSafetyError("private write target must be a regular file")
            os.fchmod(target_fd, _PRIVATE_MODE)
        finally:
            os.close(target_fd)
        os.fsync(parent_fd)
    except Exception:
        if temporary_fd is not None:
            os.close(temporary_fd)
        try:
            os.unlink(temporary_name, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
        raise
    finally:
        os.close(parent_fd)


def _create_private_file_exclusive(path: Path, data: bytes = b"") -> None:
    parent_fd = _open_directory(path.parent)
    descriptor: int | None = None
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path.name, flags, _PRIVATE_MODE, dir_fd=parent_fd)
        if data:
            view = memoryview(data)
            while view:
                view = view[os.write(descriptor, view) :]
        os.fsync(descriptor)
    except FileExistsError:
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent_fd)


def bootstrap_private_workspace(paths: WorkspacePaths) -> WorkspaceMarker:
    """Create the empty private tree and return its stable non-secret marker."""
    canonical = _canonical_paths(paths)
    root = assert_safe_private_root(canonical.root)
    root.mkdir(mode=_DIRECTORY_MODE, exist_ok=True)
    os.chmod(root, _DIRECTORY_MODE)
    if canonical.marker.exists():
        marker = _validate_existing_workspace(root)
    else:
        marker = WorkspaceMarker(marker_version=1, workspace_id=uuid4(), schema_version=1)
        try:
            _create_private_file_exclusive(canonical.marker, marker.model_dump_json().encode())
        except FileExistsError:
            marker = _validate_existing_workspace(root)
    for directory in (
        canonical.master,
        canonical.evidence,
        canonical.education,
        canonical.certificates,
        canonical.project_metrics,
        canonical.applications,
        canonical.reports,
        canonical.pending_ai_os_updates,
        canonical.data,
    ):
        directory.mkdir(mode=_DIRECTORY_MODE, exist_ok=True)
        os.chmod(directory, _DIRECTORY_MODE)
    try:
        _create_private_file_exclusive(canonical.lock)
    except FileExistsError:
        pass
    return marker


def read_private_bytes(path: Path) -> tuple[bytes, Path, WorkspaceMarker, PurePosixPath]:
    """Read a 0600 regular file through validated directory file descriptors."""
    target = _absolute(path)
    root, marker, relative = _workspace_for_path(target)
    if not relative.parts:
        raise WorkspaceSafetyError("private path must name a file")
    parent_relative = PurePosixPath(*relative.parts[:-1])
    parent_fd = _open_relative_directory(root, parent_relative)
    descriptor: int | None = None
    try:
        descriptor = os.open(
            relative.parts[-1],
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != _PRIVATE_MODE:
            raise WorkspaceSafetyError("private file must be a 0600 regular file")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks), root, marker, relative
    except OSError as exc:
        raise WorkspaceSafetyError("cannot read private file") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent_fd)


def atomic_write_private(path: Path, data: bytes) -> None:
    """Write one private file atomically through a validated directory FD."""
    target = _absolute(path)
    root, _, relative = _workspace_for_path(target)
    if not relative.parts:
        raise WorkspaceSafetyError("private write path must name a file")
    parent = root.joinpath(*relative.parts[:-1])
    _atomic_replace_in_directory(parent, relative.parts[-1], data)


def _lock_payload() -> bytes:
    return json.dumps(
        {"pid": os.getpid(), "created_at": time.time()}, separators=(",", ":")
    ).encode("utf-8")


@contextmanager
def workspace_lock(paths: WorkspacePaths, timeout_seconds: float = 2.5) -> Iterator[None]:
    """Acquire a persistent, kernel-enforced non-stealable workspace lock."""
    if timeout_seconds < 0:
        raise ValueError("timeout must not be negative")
    canonical = _canonical_paths(paths)
    root = assert_safe_private_root(canonical.root)
    if root != canonical.root or not canonical.marker.exists():
        raise WorkspaceSafetyError("workspace must be bootstrapped before locking")
    descriptor = os.open(
        canonical.lock,
        os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        _PRIVATE_MODE,
    )
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise WorkspaceSafetyError("workspace lock must be a regular file")
        os.fchmod(descriptor, _PRIVATE_MODE)
        started = time.monotonic()
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() - started >= timeout_seconds:
                    raise WorkspaceLockTimeout("workspace lock is held by another writer")
                time.sleep(min(0.02, max(0.001, timeout_seconds / 20)))
        payload = _lock_payload()
        os.ftruncate(descriptor, 0)
        os.lseek(descriptor, 0, os.SEEK_SET)
        view = memoryview(payload)
        while view:
            view = view[os.write(descriptor, view) :]
        os.fsync(descriptor)
        try:
            yield
        finally:
            os.ftruncate(descriptor, 0)
            os.fsync(descriptor)
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)
