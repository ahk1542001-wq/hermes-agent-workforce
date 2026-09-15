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
    if candidate == Path(candidate.anchor) or candidate == _absolute(Path.home()):
        raise WorkspaceSafetyError("filesystem root or home cannot be a private workspace")
    for forbidden in _FORBIDDEN_ROOTS:
        if forbidden != Path.home() and _inside(candidate, _absolute(forbidden)):
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


def _open_directory_from(parent_fd: int, name: str) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        return os.open(name, flags, dir_fd=parent_fd)
    except OSError as exc:
        raise WorkspaceSafetyError(f"cannot open private directory: {name}") from exc


def _open_absolute_directory(path: Path, *, create_last: bool = False) -> int:
    """Open an absolute directory one component at a time from filesystem root."""
    target = _absolute(path)
    if _has_symlink_component(target):
        raise WorkspaceSafetyError("workspace path crosses a symbolic link")
    descriptor = os.open(
        Path(target.anchor),
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        for index, component in enumerate(target.parts[1:]):
            try:
                next_descriptor = _open_directory_from(descriptor, component)
            except WorkspaceSafetyError as exc:
                if not (create_last and index == len(target.parts[1:]) - 1):
                    raise exc
                try:
                    os.mkdir(component, _DIRECTORY_MODE, dir_fd=descriptor)
                    next_descriptor = _open_directory_from(descriptor, component)
                except OSError as create_error:
                    raise WorkspaceSafetyError(
                        "cannot create private workspace root"
                    ) from create_error
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _marker_from_fd(root_fd: int) -> WorkspaceMarker:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            ".job-scout-workspace.json",
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=root_fd,
        )
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != _PRIVATE_MODE:
            raise WorkspaceSafetyError("workspace marker must be a private regular file")
        data = os.read(descriptor, 64 * 1024)
        return WorkspaceMarker.model_validate_json(data)
    except FileNotFoundError as exc:
        raise WorkspaceSafetyError("workspace marker is missing") from exc
    except WorkspaceSafetyError:
        raise
    except (OSError, ValueError) as exc:
        raise WorkspaceSafetyError("workspace marker is invalid") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _validate_root_fd(root_fd: int) -> WorkspaceMarker:
    info = os.fstat(root_fd)
    if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != _DIRECTORY_MODE:
        raise WorkspaceSafetyError("private workspace root must be a 0700 directory")
    return _marker_from_fd(root_fd)


def _open_relative_directory_fd(root_fd: int, relative: PurePosixPath) -> int:
    descriptor = os.dup(root_fd)
    try:
        for component in relative.parts:
            if component in {"", ".", ".."}:
                raise WorkspaceSafetyError("private path contains an unsafe component")
            next_descriptor = _open_directory_from(descriptor, component)
            info = os.fstat(next_descriptor)
            if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != _DIRECTORY_MODE:
                os.close(next_descriptor)
                raise WorkspaceSafetyError("private workspace directory must be 0700")
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _discover_workspace(path: Path) -> tuple[Path, PurePosixPath]:
    target = _absolute(path)
    if _has_symlink_component(target):
        raise WorkspaceSafetyError("private path crosses a symbolic link")
    current = target.parent
    while current != current.parent:
        marker_path = current / ".job-scout-workspace.json"
        if marker_path.is_file():
            relative = PurePosixPath(os.path.relpath(target, current))
            if relative.is_absolute() or ".." in relative.parts:
                raise WorkspaceSafetyError("private path is outside its workspace")
            return current, relative
        current = current.parent
    raise WorkspaceSafetyError("private path is outside a bootstrapped workspace")


def _write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(descriptor, view) :]


def _atomic_replace_in_fd(parent_fd: int, name: str, data: bytes) -> None:
    try:
        existing = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISREG(existing.st_mode) or stat.S_IMODE(existing.st_mode) != _PRIVATE_MODE:
            raise WorkspaceSafetyError("private write target must be a 0600 regular file")
    except FileNotFoundError:
        pass
    temporary_name = f".{name}.{uuid4().hex}.tmp"
    temporary_fd: int | None = None
    try:
        temporary_fd = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            _PRIVATE_MODE,
            dir_fd=parent_fd,
        )
        _write_all(temporary_fd, data)
        os.fsync(temporary_fd)
        os.close(temporary_fd)
        temporary_fd = None
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


def _create_file_exclusive_fd(root_fd: int, name: str, data: bytes = b"") -> None:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            _PRIVATE_MODE,
            dir_fd=root_fd,
        )
        _write_all(descriptor, data)
        os.fsync(descriptor)
    finally:
        if descriptor is not None:
            os.close(descriptor)


def bootstrap_private_workspace(paths: WorkspacePaths) -> WorkspaceMarker:
    """Create the empty private tree while retaining validated root FDs."""
    canonical = _canonical_paths(paths)
    root = assert_safe_private_root(canonical.root)
    parent_fd = _open_absolute_directory(root.parent)
    root_fd: int | None = None
    try:
        try:
            root_fd = _open_directory_from(parent_fd, root.name)
        except WorkspaceSafetyError:
            try:
                os.mkdir(root.name, _DIRECTORY_MODE, dir_fd=parent_fd)
                root_fd = _open_directory_from(parent_fd, root.name)
            except OSError as exc:
                raise WorkspaceSafetyError("cannot create private workspace root") from exc
        os.fchmod(root_fd, _DIRECTORY_MODE)
        try:
            marker = _validate_root_fd(root_fd)
        except WorkspaceSafetyError as exc:
            if canonical.marker.exists():
                raise exc
            marker = WorkspaceMarker(marker_version=1, workspace_id=uuid4(), schema_version=1)
            try:
                _create_file_exclusive_fd(
                    root_fd, canonical.marker.name, marker.model_dump_json().encode()
                )
            except FileExistsError:
                marker = _validate_root_fd(root_fd)
        for relative in (
            PurePosixPath("master"),
            PurePosixPath("evidence"),
            PurePosixPath("evidence/education"),
            PurePosixPath("evidence/certificates"),
            PurePosixPath("evidence/project-metrics"),
            PurePosixPath("applications"),
            PurePosixPath("reports"),
            PurePosixPath("pending-ai-os-updates"),
            PurePosixPath("data"),
        ):
            current = root_fd
            opened: int | None = None
            try:
                for component in relative.parts:
                    try:
                        next_fd = _open_directory_from(current, component)
                    except WorkspaceSafetyError:
                        os.mkdir(component, _DIRECTORY_MODE, dir_fd=current)
                        next_fd = _open_directory_from(current, component)
                    os.fchmod(next_fd, _DIRECTORY_MODE)
                    if opened is not None:
                        os.close(opened)
                    opened = next_fd
                    current = next_fd
            finally:
                if opened is not None:
                    os.close(opened)
        try:
            _create_file_exclusive_fd(root_fd, canonical.lock.name)
        except FileExistsError:
            pass
        return marker
    finally:
        if root_fd is not None:
            os.close(root_fd)
        os.close(parent_fd)


def _open_workspace_root(root: Path) -> tuple[int, WorkspaceMarker]:
    descriptor = _open_absolute_directory(root)
    try:
        marker = _validate_root_fd(descriptor)
        return descriptor, marker
    except Exception:
        os.close(descriptor)
        raise


def read_private_bytes(path: Path) -> tuple[bytes, Path, WorkspaceMarker, PurePosixPath]:
    """Read a 0600 regular file via validated directory file descriptors."""
    root, relative = _discover_workspace(path)
    root_fd, marker = _open_workspace_root(root)
    parent_fd: int | None = None
    descriptor: int | None = None
    try:
        parent_fd = _open_relative_directory_fd(root_fd, PurePosixPath(*relative.parts[:-1]))
        descriptor = os.open(
            relative.parts[-1], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd
        )
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != _PRIVATE_MODE:
            raise WorkspaceSafetyError("private file must be a 0600 regular file")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks), root, marker, relative
    except OSError as exc:
        raise WorkspaceSafetyError("cannot read private file") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if parent_fd is not None:
            os.close(parent_fd)
        os.close(root_fd)


def atomic_write_private(path: Path, data: bytes) -> None:
    """Write one private file atomically through a validated directory FD."""
    root, relative = _discover_workspace(path)
    root_fd, _ = _open_workspace_root(root)
    parent_fd: int | None = None
    try:
        parent_fd = _open_relative_directory_fd(root_fd, PurePosixPath(*relative.parts[:-1]))
        _atomic_replace_in_fd(parent_fd, relative.parts[-1], data)
    finally:
        if parent_fd is not None:
            os.close(parent_fd)
        os.close(root_fd)


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
    root_fd, _ = _open_workspace_root(root)
    descriptor: int | None = None
    try:
        descriptor = os.open(
            canonical.lock.name,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            _PRIVATE_MODE,
            dir_fd=root_fd,
        )
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
        os.ftruncate(descriptor, 0)
        os.lseek(descriptor, 0, os.SEEK_SET)
        _write_all(descriptor, _lock_payload())
        os.fsync(descriptor)
        try:
            yield
        finally:
            os.ftruncate(descriptor, 0)
            os.fsync(descriptor)
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(root_fd)
