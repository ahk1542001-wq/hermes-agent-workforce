"""Durable, revision-checked operational state for the local Job Scout.

The database is deliberately boring: the private workspace is the trust
boundary, SQLite is the materialized state, and application events are never
updated or deleted.  Network/provider adapters belong in later tasks.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
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
from .workspace import WorkspaceSafetyError, read_private_bytes, workspace_lock


class DatabaseError(RuntimeError):
    """The local store is invalid, unavailable, or cannot safely be changed."""


class RevisionConflict(DatabaseError):
    """A writer attempted to change state from an obsolete revision."""


class MarkerMismatch(DatabaseError):
    """The database is not bound to the supplied private workspace marker."""


ModelT = TypeVar("ModelT")


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

    def __init__(self, database: Path, marker: WorkspaceMarker, paths: WorkspacePaths) -> None:
        self.path = database
        self.marker = marker
        self.paths = paths
        try:
            self._connection = sqlite3.connect(
                str(database), timeout=2.5, isolation_level=None, check_same_thread=True
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA busy_timeout = 2500")
            journal_mode = self._connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            if str(journal_mode).lower() != "wal":
                raise DatabaseError("SQLite WAL mode could not be enabled")
            self._initialize_schema()
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
                return cls(database, supplied, paths)
        except (WorkspaceSafetyError, sqlite3.Error) as exc:
            raise DatabaseError("private workspace lock or database is invalid") from exc

    def close(self) -> None:
        connection = getattr(self, "_connection", None)
        if connection is not None:
            self._connection.close()

    def __enter__(self) -> JobStore:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

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
                self._connection.execute("BEGIN IMMEDIATE")
                try:
                    actual = self._current_revision_unlocked()
                    if actual != expected_revision:
                        raise RevisionConflict(
                            f"expected revision {expected_revision}, current revision is {actual}"
                        )
                    transaction = _Transaction(self)
                    yield transaction
                    if transaction.changed:
                        self._connection.execute(
                            "UPDATE workspace_state SET revision = revision + 1 "
                            "WHERE workspace_id = ?",
                            (str(self.marker.workspace_id),),
                        )
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
