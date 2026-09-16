"""Durable, revision-checked operational state for the local Job Scout.

The database is deliberately boring: the private workspace is the trust
boundary, SQLite is the materialized state, and application events are never
updated or deleted.  Network/provider adapters belong in later tasks.
"""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, TypeVar, cast
from uuid import uuid4

from pydantic import ValidationError

from .config import WorkspacePaths
from .models import (
    ApplicationEvent,
    DiscoveryRun,
    JobRecord,
    SourceRecord,
    WorkspaceMarker,
)
from .workspace import (
    WorkspaceSafetyError,
    _open_relative_directory_fd,
    _open_workspace_root,
    read_private_bytes,
    workspace_lock,
)


class DatabaseError(RuntimeError):
    """The local store is invalid, unavailable, or cannot safely be changed."""


class RevisionConflict(DatabaseError):
    """A writer attempted to change state from an obsolete revision."""


class MarkerMismatch(DatabaseError):
    """The database is not bound to the supplied private workspace marker."""


ModelT = TypeVar("ModelT")

_PRIVATE_MODE = 0o600
_PRIVATE_DIRECTORY_MODE = 0o700
_EXPECTED_COLUMNS = {
    "schema_meta": ("key", "value"),
    "workspace_state": ("workspace_id", "revision"),
    "jobs": ("job_id", "canonical_url", "fingerprint", "payload"),
    "application_events": ("sequence", "event_id", "job_id", "payload"),
    "approvals": ("approval_id", "job_id", "payload"),
    "source_registry": ("source_id", "payload"),
    "discovery_runs": ("run_id", "payload"),
    "run_metrics": (
        "run_id",
        "provider",
        "coverage",
        "changed_count",
        "checked_source_count",
        "failed_source_count",
        "result_count",
        "tokens_used",
        "tool_calls",
        "query_count",
        "pages_checked",
        "cache_hits",
        "free_credits_remaining",
        "model_calls",
        "actual_search_retrieval_spend_usd",
    ),
}
_EXPECTED_TRIGGERS = {
    "application_events_no_update",
    "application_events_no_delete",
}
_EXPECTED_TRIGGER_SQL = {
    "application_events_no_update": (
        "CREATE TRIGGER application_events_no_update BEFORE UPDATE ON application_events "
        "BEGIN SELECT RAISE(ABORT, 'application events are append-only'); END"
    ),
    "application_events_no_delete": (
        "CREATE TRIGGER application_events_no_delete BEFORE DELETE ON application_events "
        "BEGIN SELECT RAISE(ABORT, 'application events are append-only'); END"
    ),
}
_EXPECTED_TABLE_SQL = {
    "schema_meta": """
        CREATE TABLE schema_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """,
    "workspace_state": """
        CREATE TABLE workspace_state (
            workspace_id TEXT PRIMARY KEY,
            revision INTEGER NOT NULL CHECK (revision >= 0)
        )
    """,
    "jobs": """
        CREATE TABLE jobs (
            job_id TEXT PRIMARY KEY,
            canonical_url TEXT NOT NULL UNIQUE,
            fingerprint TEXT NOT NULL UNIQUE,
            payload TEXT NOT NULL
        )
    """,
    "application_events": """
        CREATE TABLE application_events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            job_id TEXT NOT NULL REFERENCES jobs(job_id),
            payload TEXT NOT NULL
        )
    """,
    "approvals": """
        CREATE TABLE approvals (
            approval_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES jobs(job_id),
            payload TEXT NOT NULL
        )
    """,
    "source_registry": """
        CREATE TABLE source_registry (
            source_id TEXT PRIMARY KEY,
            payload TEXT NOT NULL
        )
    """,
    "discovery_runs": """
        CREATE TABLE discovery_runs (
            run_id TEXT PRIMARY KEY,
            payload TEXT NOT NULL
        )
    """,
    "run_metrics": """
        CREATE TABLE run_metrics (
            run_id TEXT PRIMARY KEY REFERENCES discovery_runs(run_id),
            provider TEXT NOT NULL,
            coverage TEXT NOT NULL,
            changed_count INTEGER NOT NULL,
            checked_source_count INTEGER NOT NULL,
            failed_source_count INTEGER NOT NULL,
            result_count INTEGER NOT NULL,
            tokens_used INTEGER,
            tool_calls INTEGER NOT NULL,
            query_count INTEGER NOT NULL,
            pages_checked INTEGER NOT NULL,
            cache_hits INTEGER NOT NULL,
            free_credits_remaining TEXT NOT NULL,
            model_calls INTEGER NOT NULL,
            actual_search_retrieval_spend_usd TEXT NOT NULL
        )
    """,
}
_REQUIRED_UNIQUE_COLUMNS = {
    "jobs": {("canonical_url",), ("fingerprint",)},
    "application_events": {("event_id",)},
}
_EXPECTED_FOREIGN_KEYS = {
    "application_events": {("job_id", "jobs", "job_id")},
    "approvals": {("job_id", "jobs", "job_id")},
    "run_metrics": {("run_id", "discovery_runs", "run_id")},
}


def _normalize_sql(value: str) -> str:
    return " ".join(value.strip().rstrip(";").lower().split())


def _canonical_json(model: object) -> str:
    """Serialize a Pydantic model with stable keys and timezone text intact."""
    if hasattr(model, "model_dump"):
        value = cast(Any, model).model_dump(mode="json")
    else:  # pragma: no cover - kept private and defensive
        value = model
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _marker_from_input(marker: WorkspaceMarker | str) -> WorkspaceMarker:
    if isinstance(marker, WorkspaceMarker):
        return marker
    if isinstance(marker, str):
        try:
            return WorkspaceMarker.model_validate_json(marker)
        except (ValueError, ValidationError) as exc:
            raise MarkerMismatch("workspace marker is invalid") from exc
    raise MarkerMismatch("workspace marker has an invalid type")


class _Transaction:
    """Operations available while one revision-checked transaction is open."""

    def __init__(self, store: JobStore) -> None:
        self.store = store
        self.changed = False

    def upsert_job(self, record: JobRecord) -> None:
        self.store._upsert_job(record, self)

    def append_event(self, event: ApplicationEvent) -> None:
        self.store._append_event(event, self)

    def upsert_source(self, source: SourceRecord) -> None:
        self.store._upsert_source(source, self)

    def record_discovery_run(self, run: DiscoveryRun) -> None:
        self.store._record_discovery_run(run, self)


class JobStore:
    """SQLite state store bound to one validated private workspace marker."""

    SCHEMA_VERSION = 1

    def __init__(
        self,
        database: Path,
        marker: WorkspaceMarker,
        paths: WorkspacePaths,
        *,
        created: bool,
        root_fd: int,
        data_fd: int,
        database_fd: int,
        sidecar_fds: dict[str, int],
    ) -> None:
        self.path = database
        self.marker = marker
        self.paths = paths
        self._root_fd = root_fd
        self._data_fd = data_fd
        self._database_fd = database_fd
        self._sidecar_fds = sidecar_fds
        try:
            self._connection = sqlite3.connect(
                str(database), timeout=2.5, isolation_level=None, check_same_thread=True
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA busy_timeout = 2500")
            self._validate_main_file_identity()
            if not created:
                self._validate_existing_schema()
            journal_mode = self._connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            if str(journal_mode).lower() != "wal":
                raise DatabaseError("SQLite WAL mode could not be enabled")
            if created:
                self._initialize_schema()
            self._validate_existing_schema()
            self._secure_and_hold_storage_files()
        except DatabaseError:
            self.close()
            raise
        except sqlite3.Error as exc:
            self.close()
            raise DatabaseError("cannot open the private Job Scout database") from exc

    @classmethod
    def open(cls, path: Path, marker: WorkspaceMarker | str) -> JobStore:
        """Open or initialize ``data/jobs.sqlite`` for the supplied workspace."""
        database = path.expanduser().absolute()
        supplied = _marker_from_input(marker)
        root = database.parent.parent
        paths = WorkspacePaths.from_root(root)
        if database != paths.database:
            raise DatabaseError("database must be the canonical private workspace database")
        try:
            raw, discovered_root, discovered_marker, relative = read_private_bytes(
                paths.marker, expected_workspace_id=supplied.workspace_id
            )
            actual = WorkspaceMarker.model_validate_json(raw)
        except (WorkspaceSafetyError, ValueError, ValidationError) as exc:
            raise MarkerMismatch("workspace marker does not match the supplied marker") from exc
        if discovered_root != paths.root or relative.as_posix() != ".job-scout-workspace.json":
            raise MarkerMismatch("workspace marker is not the canonical root marker")
        if actual != supplied or discovered_marker != supplied:
            raise MarkerMismatch("workspace marker does not match the supplied marker")
        try:
            with workspace_lock(paths, expected_workspace_id=supplied.workspace_id):
                opened_root_fd, opened_marker = _open_workspace_root(
                    paths.root, expected_workspace_id=supplied.workspace_id
                )
                root_fd: int | None = opened_root_fd
                data_fd: int | None = None
                database_fd: int | None = None
                sidecar_fds: dict[str, int] = {}
                try:
                    if opened_marker != supplied:
                        raise MarkerMismatch("workspace identity changed before database open")
                    data_fd = _open_relative_directory_fd(opened_root_fd, PurePosixPath("data"))
                    flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
                    created = False
                    try:
                        database_fd = os.open(paths.database.name, flags, dir_fd=data_fd)
                    except FileNotFoundError:
                        database_fd = os.open(
                            paths.database.name,
                            flags | os.O_CREAT | os.O_EXCL,
                            _PRIVATE_MODE,
                            dir_fd=data_fd,
                        )
                        created = True
                    info = os.fstat(database_fd)
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                        raise DatabaseError("database must be a single-link regular file")
                    os.fchmod(database_fd, _PRIVATE_MODE)
                    for name in (
                        f"{paths.database.name}-wal",
                        f"{paths.database.name}-shm",
                    ):
                        descriptor: int | None = None
                        try:
                            try:
                                descriptor = os.open(name, flags, dir_fd=data_fd)
                            except FileNotFoundError:
                                descriptor = os.open(
                                    name,
                                    flags | os.O_CREAT | os.O_EXCL,
                                    _PRIVATE_MODE,
                                    dir_fd=data_fd,
                                )
                            sidecar_info = os.fstat(descriptor)
                            if not stat.S_ISREG(sidecar_info.st_mode) or sidecar_info.st_nlink != 1:
                                raise DatabaseError(
                                    f"SQLite sidecar is not a single-link regular file: {name}"
                                )
                            os.fchmod(descriptor, _PRIVATE_MODE)
                            sidecar_fds[name] = descriptor
                            descriptor = None
                        finally:
                            if descriptor is not None:
                                os.close(descriptor)
                    owned_root_fd = opened_root_fd
                    owned_data_fd = data_fd
                    owned_database_fd = database_fd
                    owned_sidecar_fds = sidecar_fds
                    root_fd = None
                    data_fd = None
                    database_fd = None
                    sidecar_fds = {}
                    return cls(
                        database,
                        supplied,
                        paths,
                        created=created,
                        root_fd=owned_root_fd,
                        data_fd=owned_data_fd,
                        database_fd=owned_database_fd,
                        sidecar_fds=owned_sidecar_fds,
                    )
                except Exception:
                    for descriptor in sidecar_fds.values():
                        os.close(descriptor)
                    if database_fd is not None:
                        os.close(database_fd)
                    if data_fd is not None:
                        os.close(data_fd)
                    if root_fd is not None:
                        os.close(root_fd)
                    raise
        except (WorkspaceSafetyError, sqlite3.Error, OSError) as exc:
            raise DatabaseError("private workspace lock or database is invalid") from exc

    def close(self) -> None:
        connection = getattr(self, "_connection", None)
        if connection is not None:
            self._connection.close()
        for descriptor in getattr(self, "_sidecar_fds", {}).values():
            os.close(descriptor)
        if hasattr(self, "_sidecar_fds"):
            self._sidecar_fds.clear()
        for name in ("_database_fd", "_data_fd", "_root_fd"):
            descriptor = getattr(self, name, None)
            if descriptor is not None:
                os.close(descriptor)
                setattr(self, name, None)

    def __enter__(self) -> JobStore:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def _validate_fd_entry(self, descriptor: int, name: str) -> None:
        held = os.fstat(descriptor)
        try:
            current = os.stat(name, dir_fd=self._data_fd, follow_symlinks=False)
        except OSError as exc:
            raise DatabaseError(f"private database file is unavailable: {name}") from exc
        if (
            not stat.S_ISREG(current.st_mode)
            or held.st_nlink != 1
            or current.st_nlink != 1
            or (held.st_dev, held.st_ino) != (current.st_dev, current.st_ino)
            or stat.S_IMODE(current.st_mode) != _PRIVATE_MODE
        ):
            raise DatabaseError(f"private database identity or mode changed: {name}")

    def _validate_main_file_identity(self) -> None:
        self._validate_fd_entry(self._database_fd, self.path.name)

    def _validate_workspace_chain(self) -> None:
        current_root_fd: int | None = None
        current_data_fd: int | None = None
        try:
            current_root_fd, marker = _open_workspace_root(
                self.paths.root, expected_workspace_id=self.marker.workspace_id
            )
            if marker != self.marker:
                raise DatabaseError("canonical workspace marker changed")
            held_root = os.fstat(self._root_fd)
            current_root = os.fstat(current_root_fd)
            if (
                not stat.S_ISDIR(current_root.st_mode)
                or stat.S_IMODE(current_root.st_mode) != _PRIVATE_DIRECTORY_MODE
                or (held_root.st_dev, held_root.st_ino)
                != (current_root.st_dev, current_root.st_ino)
            ):
                raise DatabaseError("canonical workspace root identity changed")
            current_data_fd = _open_relative_directory_fd(current_root_fd, PurePosixPath("data"))
            held_data = os.fstat(self._data_fd)
            current_data = os.fstat(current_data_fd)
            if (
                not stat.S_ISDIR(current_data.st_mode)
                or stat.S_IMODE(current_data.st_mode) != _PRIVATE_DIRECTORY_MODE
                or (held_data.st_dev, held_data.st_ino)
                != (current_data.st_dev, current_data.st_ino)
            ):
                raise DatabaseError("canonical data directory identity changed")
        except WorkspaceSafetyError as exc:
            raise DatabaseError("canonical workspace chain is unsafe") from exc
        finally:
            if current_data_fd is not None:
                os.close(current_data_fd)
            if current_root_fd is not None:
                os.close(current_root_fd)

    def _secure_and_hold_storage_files(self) -> None:
        self._validate_workspace_chain()
        self._validate_main_file_identity()
        expected = {f"{self.path.name}-wal", f"{self.path.name}-shm"}
        if set(self._sidecar_fds) != expected:
            raise DatabaseError("SQLite sidecar identity set is incomplete")
        for name, descriptor in self._sidecar_fds.items():
            self._validate_fd_entry(descriptor, name)

    def _validate_storage_identity(self) -> None:
        self._validate_workspace_chain()
        self._validate_main_file_identity()
        for name, descriptor in self._sidecar_fds.items():
            self._validate_fd_entry(descriptor, name)

    def _validate_existing_schema(self) -> None:
        rows = self._connection.execute(
            "SELECT name, type FROM sqlite_master "
            "WHERE type IN ('table', 'trigger') AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        actual_tables = {row[0] for row in rows if row[1] == "table"}
        actual_triggers = {row[0] for row in rows if row[1] == "trigger"}
        if actual_tables != set(_EXPECTED_COLUMNS) or actual_triggers != _EXPECTED_TRIGGERS:
            raise DatabaseError("database schema is incomplete or unexpected")
        for table, expected_columns in _EXPECTED_COLUMNS.items():
            columns = tuple(
                row[1] for row in self._connection.execute(f'PRAGMA table_info("{table}")')
            )
            if columns != expected_columns:
                raise DatabaseError(f"database table shape is invalid: {table}")
        table_sql = {
            row[0]: row[1]
            for row in self._connection.execute(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        for name, expected_sql in _EXPECTED_TABLE_SQL.items():
            actual_sql = table_sql.get(name)
            if actual_sql is None or _normalize_sql(actual_sql) != _normalize_sql(expected_sql):
                raise DatabaseError(f"database table contract is invalid: {name}")
        trigger_sql = {
            row[0]: row[1]
            for row in self._connection.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='trigger'"
            )
        }
        for name, expected_sql in _EXPECTED_TRIGGER_SQL.items():
            actual_sql = trigger_sql.get(name)
            if actual_sql is None or _normalize_sql(actual_sql) != _normalize_sql(expected_sql):
                raise DatabaseError(f"database trigger contract is invalid: {name}")
        for table, required_sets in _REQUIRED_UNIQUE_COLUMNS.items():
            actual_sets: set[tuple[str, ...]] = set()
            for index in self._connection.execute(f'PRAGMA index_list("{table}")'):
                if index[2] != 1:
                    continue
                actual_sets.add(
                    tuple(
                        column[2]
                        for column in self._connection.execute(f'PRAGMA index_info("{index[1]}")')
                    )
                )
            if not required_sets.issubset(actual_sets):
                raise DatabaseError(f"database uniqueness contract is invalid: {table}")
        for table, expected_keys in _EXPECTED_FOREIGN_KEYS.items():
            actual_keys = {
                (row[3], row[2], row[4])
                for row in self._connection.execute(f'PRAGMA foreign_key_list("{table}")')
            }
            if actual_keys != expected_keys:
                raise DatabaseError(f"database foreign-key contract is invalid: {table}")
        schema = self._connection.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
        if schema is None or schema[0] != str(self.SCHEMA_VERSION):
            raise DatabaseError("unsupported Job Scout database schema version")
        workspaces = self._connection.execute(
            "SELECT workspace_id, revision FROM workspace_state"
        ).fetchall()
        if len(workspaces) != 1 or workspaces[0][0] != str(self.marker.workspace_id):
            raise MarkerMismatch("database workspace identity does not match marker")
        if not isinstance(workspaces[0][1], int) or workspaces[0][1] < 0:
            raise DatabaseError("database revision is invalid")

    def _initialize_schema(self) -> None:
        connection = self._connection
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workspace_state (
                    workspace_id TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL CHECK (revision >= 0)
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    canonical_url TEXT NOT NULL UNIQUE,
                    fingerprint TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS application_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    job_id TEXT NOT NULL REFERENCES jobs(job_id),
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(job_id),
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS source_registry (
                    source_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS discovery_runs (
                    run_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS run_metrics (
                    run_id TEXT PRIMARY KEY REFERENCES discovery_runs(run_id),
                    provider TEXT NOT NULL,
                    coverage TEXT NOT NULL,
                    changed_count INTEGER NOT NULL,
                    checked_source_count INTEGER NOT NULL,
                    failed_source_count INTEGER NOT NULL,
                    result_count INTEGER NOT NULL,
                    tokens_used INTEGER,
                    tool_calls INTEGER NOT NULL,
                    query_count INTEGER NOT NULL,
                    pages_checked INTEGER NOT NULL,
                    cache_hits INTEGER NOT NULL,
                    free_credits_remaining TEXT NOT NULL,
                    model_calls INTEGER NOT NULL,
                    actual_search_retrieval_spend_usd TEXT NOT NULL
                );
                CREATE TRIGGER application_events_no_update
                BEFORE UPDATE ON application_events
                BEGIN
                    SELECT RAISE(ABORT, 'application events are append-only');
                END;
                CREATE TRIGGER application_events_no_delete
                BEFORE DELETE ON application_events
                BEGIN
                    SELECT RAISE(ABORT, 'application events are append-only');
                END;
                """
            )
            connection.execute("BEGIN IMMEDIATE")
            schema = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
            if schema is None:
                connection.execute(
                    "INSERT INTO schema_meta(key, value) VALUES ('schema_version', ?)",
                    (str(self.SCHEMA_VERSION),),
                )
            elif schema[0] != str(self.SCHEMA_VERSION):
                raise DatabaseError("unsupported Job Scout database schema version")
            rows = connection.execute(
                "SELECT workspace_id, revision FROM workspace_state"
            ).fetchall()
            if not rows:
                connection.execute(
                    "INSERT INTO workspace_state(workspace_id, revision) VALUES (?, 0)",
                    (str(self.marker.workspace_id),),
                )
            elif len(rows) != 1 or rows[0][0] != str(self.marker.workspace_id):
                raise MarkerMismatch("database workspace identity does not match marker")
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise

    def _current_revision_unlocked(self) -> int:
        row = self._connection.execute(
            "SELECT workspace_id, revision FROM workspace_state"
        ).fetchone()
        if row is None or row[0] != str(self.marker.workspace_id):
            raise MarkerMismatch("database workspace identity does not match marker")
        return int(row[1])

    def current_revision(self) -> int:
        try:
            with workspace_lock(self.paths, expected_workspace_id=self.marker.workspace_id):
                self._validate_storage_identity()
                return self._current_revision_unlocked()
        except (WorkspaceSafetyError, sqlite3.Error) as exc:
            raise DatabaseError("cannot read the private store revision") from exc

    @contextmanager
    def transaction(self, expected_revision: int) -> Iterator[_Transaction]:
        """Run grouped state changes under one lock and one revision bump."""
        if not isinstance(expected_revision, int) or isinstance(expected_revision, bool):
            raise RevisionConflict("expected revision must be an integer")
        try:
            with workspace_lock(self.paths, expected_workspace_id=self.marker.workspace_id):
                self._validate_storage_identity()
                self._connection.execute("BEGIN IMMEDIATE")
                try:
                    actual = self._current_revision_unlocked()
                    if actual != expected_revision:
                        raise RevisionConflict(
                            f"expected revision {expected_revision}, current revision is {actual}"
                        )
                    transaction = _Transaction(self)
                    yield transaction
                    self._validate_storage_identity()
                    if transaction.changed:
                        self._connection.execute(
                            "UPDATE workspace_state SET revision = revision + 1 "
                            "WHERE workspace_id = ?",
                            (str(self.marker.workspace_id),),
                        )
                    self._validate_storage_identity()
                    self._connection.execute("COMMIT")
                except Exception:
                    self._connection.execute("ROLLBACK")
                    raise
        except RevisionConflict:
            raise
        except (WorkspaceSafetyError, sqlite3.Error) as exc:
            raise DatabaseError("private store transaction failed closed") from exc

    def _insert_application_event(self, event: ApplicationEvent) -> None:
        try:
            self._connection.execute(
                "INSERT INTO application_events(event_id, job_id, payload) VALUES (?, ?, ?)",
                (event.event_id, event.job_id, _canonical_json(event)),
            )
        except sqlite3.IntegrityError as exc:
            raise DatabaseError("application event ID or job reference already exists") from exc

    def _upsert_job(self, record: JobRecord, transaction: _Transaction) -> None:
        payload = _canonical_json(record)
        row = self._connection.execute(
            "SELECT payload FROM jobs WHERE job_id = ?", (record.job_id,)
        ).fetchone()
        if row is not None and row[0] == payload:
            return
        try:
            if row is None:
                self._connection.execute(
                    "INSERT INTO jobs(job_id, canonical_url, fingerprint, payload) "
                    "VALUES (?, ?, ?, ?)",
                    (record.job_id, str(record.stable_url), record.fingerprint, payload),
                )
            else:
                self._connection.execute(
                    "UPDATE jobs SET canonical_url = ?, fingerprint = ?, payload = ? "
                    "WHERE job_id = ?",
                    (str(record.stable_url), record.fingerprint, payload, record.job_id),
                )
        except sqlite3.IntegrityError as exc:
            raise DatabaseError("job canonical URL or fingerprint is already registered") from exc
        self._insert_application_event(
            ApplicationEvent(
                event_id=f"job-store-{uuid4().hex}",
                job_id=record.job_id,
                state=record.state,
                occurred_at=datetime.now(timezone.utc),
                actor="job_store",
                event_type="job_upserted",
                details={"material_change": "true"},
            )
        )
        transaction.changed = True

    def upsert_job(self, record: JobRecord, expected_revision: int) -> int:
        with self.transaction(expected_revision) as transaction:
            transaction.upsert_job(record)
        return self.current_revision()

    def _append_event(self, event: ApplicationEvent, transaction: _Transaction) -> None:
        self._insert_application_event(event)
        transaction.changed = True

    def append_event(self, event: ApplicationEvent, expected_revision: int) -> int:
        with self.transaction(expected_revision) as transaction:
            transaction.append_event(event)
        return self.current_revision()

    def get_job(self, job_id: str) -> JobRecord | None:
        self._validate_storage_identity()
        row = self._connection.execute(
            "SELECT payload FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        if row is None:
            return None
        try:
            return JobRecord.model_validate_json(row[0])
        except ValidationError as exc:
            raise DatabaseError("stored job payload is invalid") from exc

    def list_events(self, job_id: str) -> list[ApplicationEvent]:
        self._validate_storage_identity()
        rows = self._connection.execute(
            "SELECT payload FROM application_events WHERE job_id = ? ORDER BY sequence", (job_id,)
        ).fetchall()
        try:
            return [ApplicationEvent.model_validate_json(row[0]) for row in rows]
        except ValidationError as exc:
            raise DatabaseError("stored application event payload is invalid") from exc

    def _upsert_source(self, source: SourceRecord, transaction: _Transaction) -> None:
        payload = _canonical_json(source)
        row = self._connection.execute(
            "SELECT payload FROM source_registry WHERE source_id = ?", (source.source_id,)
        ).fetchone()
        if row is not None and row[0] == payload:
            return
        self._connection.execute(
            "INSERT INTO source_registry(source_id, payload) VALUES (?, ?) "
            "ON CONFLICT(source_id) DO UPDATE SET payload=excluded.payload",
            (source.source_id, payload),
        )
        transaction.changed = True

    def upsert_source(self, source: SourceRecord, expected_revision: int) -> int:
        with self.transaction(expected_revision) as transaction:
            transaction.upsert_source(source)
        return self.current_revision()

    def get_source(self, source_id: str) -> SourceRecord | None:
        self._validate_storage_identity()
        row = self._connection.execute(
            "SELECT payload FROM source_registry WHERE source_id = ?", (source_id,)
        ).fetchone()
        if row is None:
            return None
        try:
            return SourceRecord.model_validate_json(row[0])
        except ValidationError as exc:
            raise DatabaseError("stored source payload is invalid") from exc

    def _record_discovery_run(self, run: DiscoveryRun, transaction: _Transaction) -> None:
        missing = [
            source_id
            for source_id in run.checked_source_ids
            if self._connection.execute(
                "SELECT 1 FROM source_registry WHERE source_id = ?", (source_id,)
            ).fetchone()
            is None
        ]
        if missing:
            raise DatabaseError(f"discovery run references unknown sources: {', '.join(missing)}")
        payload = _canonical_json(run)
        row = self._connection.execute(
            "SELECT payload FROM discovery_runs WHERE run_id = ?", (run.run_id,)
        ).fetchone()
        if row is not None and row[0] == payload:
            return
        try:
            self._connection.execute(
                "INSERT INTO discovery_runs(run_id, payload) VALUES (?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET payload=excluded.payload",
                (run.run_id, payload),
            )
            self._connection.execute(
                "INSERT INTO run_metrics(run_id, provider, coverage, changed_count, "
                "checked_source_count, failed_source_count, result_count, tokens_used, "
                "tool_calls, query_count, pages_checked, cache_hits, free_credits_remaining, "
                "model_calls, actual_search_retrieval_spend_usd) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET provider=excluded.provider, "
                "coverage=excluded.coverage, changed_count=excluded.changed_count, "
                "checked_source_count=excluded.checked_source_count, "
                "failed_source_count=excluded.failed_source_count, "
                "result_count=excluded.result_count, tokens_used=excluded.tokens_used, "
                "tool_calls=excluded.tool_calls, query_count=excluded.query_count, "
                "pages_checked=excluded.pages_checked, cache_hits=excluded.cache_hits, "
                "free_credits_remaining=excluded.free_credits_remaining, "
                "model_calls=excluded.model_calls, "
                "actual_search_retrieval_spend_usd=excluded.actual_search_retrieval_spend_usd",
                (
                    run.run_id,
                    run.provider,
                    run.coverage,
                    run.changed_count,
                    len(run.checked_source_ids),
                    len(run.failed_source_ids),
                    run.result_count,
                    run.tokens_used,
                    run.tool_calls,
                    run.query_count,
                    run.pages_checked,
                    run.cache_hits,
                    _canonical_json(run.free_credits_remaining),
                    run.model_calls,
                    str(run.actual_search_retrieval_spend_usd),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise DatabaseError("discovery run could not be recorded") from exc
        transaction.changed = True

    def record_discovery_run(self, run: DiscoveryRun, expected_revision: int) -> int:
        with self.transaction(expected_revision) as transaction:
            transaction.record_discovery_run(run)
        return self.current_revision()

    def get_discovery_run(self, run_id: str) -> DiscoveryRun | None:
        self._validate_storage_identity()
        row = self._connection.execute(
            "SELECT payload FROM discovery_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        try:
            return DiscoveryRun.model_validate_json(row[0])
        except ValidationError as exc:
            raise DatabaseError("stored discovery run payload is invalid") from exc


__all__ = ["DatabaseError", "JobStore", "MarkerMismatch", "RevisionConflict"]
