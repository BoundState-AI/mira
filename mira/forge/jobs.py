#!/usr/bin/env python3
"""
In-process FORGE compile job manager.

This converts long-running compile requests into background jobs so the API
does not depend on a single browser/proxy/uvicorn request surviving for
multiple minutes.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from threading import Lock, Thread
from typing import Callable, Protocol
from uuid import uuid4

from .models import (
    ForgeCompileAcceptedResponse,
    ForgeCompileJobEvent,
    ForgeCompileJobResponse,
    ForgeCompileRequest,
    ForgeCompileResponse,
)

_MAX_JOB_EVENTS = 32
_MAX_JOBS = 64
_DEFAULT_JOB_STORE_PATH = ".forge/compile_jobs.sqlite3"
_TEST_STORE_TOKEN = uuid4().hex


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_store_path(path: str | Path | None) -> Path:
    if path is not None:
        return Path(path).expanduser().resolve()

    explicit = os.getenv("FORGE_JOB_STORE_PATH", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()

    if os.getenv("ENVIRONMENT", "").strip().lower() == "test":
        return (
            Path(tempfile.gettempdir()) / f"forge_compile_jobs_test_{os.getpid()}_{_TEST_STORE_TOKEN}.sqlite3"
        ).resolve()

    return Path(_DEFAULT_JOB_STORE_PATH).expanduser().resolve()


def _auto_resume_enabled() -> bool:
    return os.getenv("FORGE_AUTO_RESUME_JOBS", "").strip().lower() in {"1", "true", "yes"}


class _CompileRunner(Protocol):
    def compile_database(
        self,
        request: ForgeCompileRequest,
        *,
        progress_callback: Callable[[str, str, float], None] | None = None,
    ) -> ForgeCompileResponse: ...


@dataclass(slots=True)
class _ForgeJobState:
    job_id: str
    request: ForgeCompileRequest
    status: str
    stage: str
    message: str
    progress: float
    created_at: str
    updated_at: str
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    result: ForgeCompileResponse | None = None
    events: list[ForgeCompileJobEvent] = field(default_factory=list)


class _SQLiteJobStore:
    """Durable local SQLite store for FORGE compile jobs."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = _resolve_store_path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def get(self, job_id: str) -> _ForgeJobState | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM forge_compile_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_state(row)

    def upsert(self, state: _ForgeJobState) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO forge_compile_jobs (
                    job_id,
                    request_json,
                    status,
                    stage,
                    message,
                    progress,
                    created_at,
                    updated_at,
                    started_at,
                    completed_at,
                    error,
                    result_json,
                    events_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    request_json = excluded.request_json,
                    status = excluded.status,
                    stage = excluded.stage,
                    message = excluded.message,
                    progress = excluded.progress,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at,
                    started_at = excluded.started_at,
                    completed_at = excluded.completed_at,
                    error = excluded.error,
                    result_json = excluded.result_json,
                    events_json = excluded.events_json
                """,
                self._state_to_row(state),
            )

    def list_resumable(self) -> list[_ForgeJobState]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM forge_compile_jobs
                WHERE status IN ('queued', 'running')
                ORDER BY updated_at ASC
                """
            ).fetchall()
        return [self._row_to_state(row) for row in rows]

    def prune(self, max_jobs: int) -> list[str]:
        with self._connect() as connection:
            total_jobs = connection.execute(
                "SELECT COUNT(*) FROM forge_compile_jobs"
            ).fetchone()[0]
            if total_jobs < max_jobs:
                return []

            rows = connection.execute(
                """
                SELECT job_id FROM forge_compile_jobs
                WHERE status IN ('completed', 'failed')
                ORDER BY updated_at ASC
                LIMIT ?
                """,
                (max(0, total_jobs - max_jobs + 1),),
            ).fetchall()
            job_ids = [row[0] for row in rows]
            if not job_ids:
                return []
            connection.executemany(
                "DELETE FROM forge_compile_jobs WHERE job_id = ?",
                [(job_id,) for job_id in job_ids],
            )
        return job_ids

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS forge_compile_jobs (
                    job_id TEXT PRIMARY KEY,
                    request_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    message TEXT NOT NULL,
                    progress REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    error TEXT,
                    result_json TEXT,
                    events_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_forge_compile_jobs_status_updated_at
                ON forge_compile_jobs(status, updated_at)
                """
            )

    def _state_to_row(self, state: _ForgeJobState) -> tuple[object, ...]:
        return (
            state.job_id,
            state.request.model_dump_json(),
            state.status,
            state.stage,
            state.message,
            state.progress,
            state.created_at,
            state.updated_at,
            state.started_at,
            state.completed_at,
            state.error,
            state.result.model_dump_json() if state.result is not None else None,
            json.dumps([event.model_dump() for event in state.events]),
        )

    def _row_to_state(self, row: sqlite3.Row) -> _ForgeJobState:
        request = ForgeCompileRequest.model_validate_json(row["request_json"])
        result = (
            ForgeCompileResponse.model_validate_json(row["result_json"])
            if row["result_json"]
            else None
        )
        events = [
            ForgeCompileJobEvent.model_validate(event)
            for event in json.loads(row["events_json"] or "[]")
        ]
        return _ForgeJobState(
            job_id=row["job_id"],
            request=request,
            status=row["status"],
            stage=row["stage"],
            message=row["message"],
            progress=row["progress"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            error=row["error"],
            result=result,
            events=events,
        )


class ForgeCompileJobManager:
    """Run FORGE compiles in background threads with progress reporting."""

    def __init__(self, compiler: _CompileRunner, *, store_path: str | Path | None = None) -> None:
        self._compiler = compiler
        self._jobs: dict[str, _ForgeJobState] = {}
        self._lock = Lock()
        self._store = _SQLiteJobStore(store_path)
        self._recover_incomplete_jobs()

    def submit(self, request: ForgeCompileRequest) -> ForgeCompileAcceptedResponse:
        job_id = str(uuid4())
        timestamp = _utc_now()
        state = _ForgeJobState(
            job_id=job_id,
            request=request,
            status="queued",
            stage="queued",
            message="FORGE compile queued.",
            progress=0.0,
            created_at=timestamp,
            updated_at=timestamp,
            events=[
                ForgeCompileJobEvent(
                    timestamp=timestamp,
                    status="queued",
                    stage="queued",
                    message="FORGE compile queued.",
                    progress=0.0,
                )
            ],
        )

        with self._lock:
            self._jobs[job_id] = state
            self._store.upsert(state)
            self._prune_completed_jobs()

        self._start_worker(job_id)

        return ForgeCompileAcceptedResponse(
            status="accepted",
            job_id=job_id,
            status_url=f"/forge/compile/{job_id}",
        )

    def get(self, job_id: str) -> ForgeCompileJobResponse | None:
        with self._lock:
            state = self._jobs.get(job_id)
        if state is not None:
            return self._snapshot(state)
        stored = self._store.get(job_id)
        if stored is None:
            return None
        return self._snapshot(stored)

    def _run_job(self, job_id: str) -> None:
        state = self._get_state(job_id)
        if state is None:
            return

        self._update(
            job_id,
            status="running",
            stage="starting",
            message="FORGE compile started.",
            progress=1.0,
            started_at=_utc_now(),
        )

        try:
            result = self._compiler.compile_database(
                state.request,
                progress_callback=lambda stage, message, progress: self._update(
                    job_id,
                    status="running",
                    stage=stage,
                    message=message,
                    progress=progress,
                ),
            )
        except Exception as exc:
            self._update(
                job_id,
                status="failed",
                stage="failed",
                message="FORGE compile failed.",
                progress=100.0,
                error=str(exc),
                completed_at=_utc_now(),
            )
            return

        self._update(
            job_id,
            status="completed",
            stage="completed",
            message="FORGE compile completed.",
            progress=100.0,
            result=result,
            completed_at=_utc_now(),
        )

    def _get_state(self, job_id: str) -> _ForgeJobState | None:
        with self._lock:
            state = self._jobs.get(job_id)
        if state is not None:
            return state
        return self._store.get(job_id)

    def _update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        stage: str | None = None,
        message: str | None = None,
        progress: float | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
        error: str | None = None,
        result: ForgeCompileResponse | None = None,
    ) -> None:
        timestamp = _utc_now()
        with self._lock:
            state = self._jobs.get(job_id)
            if state is None:
                return

            if status is not None:
                state.status = status
            if stage is not None:
                state.stage = stage
            if message is not None:
                state.message = message
            if progress is not None:
                state.progress = max(0.0, min(100.0, float(progress)))
            if started_at is not None:
                state.started_at = started_at
            if completed_at is not None:
                state.completed_at = completed_at
            if error is not None:
                state.error = error
            if result is not None:
                state.result = result
            state.updated_at = timestamp

            event = ForgeCompileJobEvent(
                timestamp=timestamp,
                status=state.status,  # type: ignore[arg-type]
                stage=state.stage,
                message=state.message,
                progress=state.progress,
            )
            if not state.events or state.events[-1] != event:
                state.events.append(event)
                if len(state.events) > _MAX_JOB_EVENTS:
                    state.events = state.events[-_MAX_JOB_EVENTS:]
            self._store.upsert(state)

    def _snapshot(self, state: _ForgeJobState) -> ForgeCompileJobResponse:
        return ForgeCompileJobResponse(
            job_id=state.job_id,
            status=state.status,  # type: ignore[arg-type]
            stage=state.stage,
            message=state.message,
            progress=state.progress,
            created_at=state.created_at,
            updated_at=state.updated_at,
            started_at=state.started_at,
            completed_at=state.completed_at,
            error=state.error,
            result=state.result,
            events=list(state.events),
        )

    def _prune_completed_jobs(self) -> None:
        pruned_job_ids = set(self._store.prune(_MAX_JOBS))
        if not pruned_job_ids:
            return
        for job_id in pruned_job_ids:
            state = self._jobs.get(job_id)
            if state is not None and state.status in {"completed", "failed"}:
                self._jobs.pop(job_id, None)

    def _start_worker(self, job_id: str) -> None:
        worker = Thread(
            target=self._run_job,
            args=(job_id,),
            daemon=True,
            name=f"forge-compile-{job_id[:8]}",
        )
        worker.start()

    def _recover_incomplete_jobs(self) -> None:
        for state in self._store.list_resumable():
            timestamp = _utc_now()
            with self._lock:
                self._jobs[state.job_id] = state
            if _auto_resume_enabled():
                state.status = "queued"
                state.stage = "queued"
                state.message = "FORGE compile resumed after application restart."
                state.progress = min(max(float(state.progress), 1.0), 99.0)
                state.updated_at = timestamp
                state.error = None
                state.completed_at = None
                event = ForgeCompileJobEvent(
                    timestamp=timestamp,
                    status="queued",
                    stage="queued",
                    message=state.message,
                    progress=state.progress,
                )
                if not state.events or state.events[-1] != event:
                    state.events.append(event)
                    if len(state.events) > _MAX_JOB_EVENTS:
                        state.events = state.events[-_MAX_JOB_EVENTS:]
                self._store.upsert(state)
                self._start_worker(state.job_id)
                continue

            self._update(
                state.job_id,
                status="failed",
                stage="interrupted",
                message="FORGE compile was interrupted by application restart. Resubmit to run again.",
                progress=state.progress,
                error="FORGE compile interrupted by application restart",
                completed_at=timestamp,
            )
