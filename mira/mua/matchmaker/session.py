"""Session persistence for MUA Matchmaker v8."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import IssueStatus, MatchmakerEvent, MatchmakerSession, SessionSummary


def _default_session_dir() -> Path:
    base = Path(os.getenv("MIRA_DATA_DIR", "data")).resolve()
    return base / "matchmaker_sessions"


class MatchmakerSessionStore:
    """Disk-backed session store with atomic writes and crash recovery."""

    def __init__(self, session_dir: Path | None = None) -> None:
        self._session_dir = session_dir or _default_session_dir()
        self._session_dir.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    @property
    def session_dir(self) -> Path:
        return self._session_dir

    def create(self, session: MatchmakerSession) -> MatchmakerSession:
        self.save(session)
        return session

    def get(self, session_id: str) -> Optional[MatchmakerSession]:
        path = self._session_path(session_id)
        if not path.exists():
            return None

        with self._lock_for(session_id):
            payload = self._load_payload(path)
            if payload is None:
                return None
            return MatchmakerSession.model_validate(payload)

    def save(self, session: MatchmakerSession) -> None:
        session.updated_at = datetime.utcnow()
        path = self._session_path(session.session_id)
        payload = session.model_dump(mode="json")

        with self._lock_for(session.session_id):
            if path.exists():
                shutil.copy2(path, self._backup_path(path))
            self._atomic_write(path, payload)

    def delete(self, session_id: str) -> bool:
        path = self._session_path(session_id)
        backup = self._backup_path(path)
        deleted = False
        with self._lock_for(session_id):
            if path.exists():
                path.unlink()
                deleted = True
            if backup.exists():
                backup.unlink()
        return deleted

    def list(self) -> list[SessionSummary]:
        sessions: list[SessionSummary] = []
        for path in sorted(self._session_dir.glob("*.json")):
            if path.name.endswith(".json.backup"):
                continue
            payload = self._load_payload(path)
            if payload is None:
                continue
            try:
                session = MatchmakerSession.model_validate(payload)
            except Exception:
                continue

            issue_values = list(session.issues.values())
            done_count = len([i for i in issue_values if i.status == IssueStatus.DONE])
            manual_count = len(
                [i for i in issue_values if i.status == IssueStatus.MANUAL_REQUIRED]
            )
            sessions.append(
                SessionSummary(
                    session_id=session.session_id,
                    material_input=session.material_input,
                    updated_at=session.updated_at,
                    issue_count=len(issue_values),
                    done_count=done_count,
                    manual_count=manual_count,
                    category=session.category,
                )
            )

        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions

    def append_event(self, session: MatchmakerSession, event: MatchmakerEvent) -> None:
        session.events.append(event)
        self.save(session)

    def _session_path(self, session_id: str) -> Path:
        return self._session_dir / f"{session_id}.json"

    @staticmethod
    def _backup_path(path: Path) -> Path:
        return path.with_suffix(".json.backup")

    def _lock_for(self, session_id: str) -> threading.Lock:
        with self._locks_guard:
            lock = self._locks.get(session_id)
            if lock is None:
                lock = threading.Lock()
                self._locks[session_id] = lock
            return lock

    def _load_payload(self, path: Path) -> dict | None:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (json.JSONDecodeError, OSError):
            backup = self._backup_path(path)
            if backup.exists():
                try:
                    with open(backup, "r", encoding="utf-8") as handle:
                        payload = json.load(handle)
                    self._atomic_write(path, payload)
                    return payload
                except (json.JSONDecodeError, OSError):
                    return None
            return None

    @staticmethod
    def _atomic_write(filepath: Path, data: dict) -> None:
        dir_path = filepath.parent
        fd, tmp_path = tempfile.mkstemp(dir=str(dir_path), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, default=str)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, str(filepath))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
