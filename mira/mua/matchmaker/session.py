"""Session persistence for MUA Matchmaker v8.

Persists session state through the shared ``SessionStore`` from
``mira.core.session_store``.  All data is serialized via
``MatchmakerSession.model_dump(mode="json")`` and deserialized
via ``model_validate()`` on every read.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .models import IssueStatus, MatchmakerEvent, MatchmakerSession, SessionSummary

logger = logging.getLogger(__name__)

_MODULE = "matchmaker"


class MatchmakerSessionStore:
    """Session store backed by the shared ``SessionStore``.

    Provides both async methods (``aget``, ``asave``, etc.) for use
    in FastAPI handlers, and sync wrappers (``get``, ``save``, etc.)
    for tests and non-async callers.
    """

    def __init__(self, session_dir: Path | None = None) -> None:
        from mira.core.session_store import get_session_store
        self._store = get_session_store()
        if session_dir is not None:
            logger.warning(
                "MatchmakerSessionStore(session_dir=...) is deprecated and ignored; "
                "sessions now persist through the shared SessionStore."
            )

    # -- async primary API --------------------------------------------------

    async def acreate(self, session: MatchmakerSession) -> MatchmakerSession:
        await self.asave(session)
        return session

    async def aget(self, session_id: str) -> Optional[MatchmakerSession]:
        from mira.core.session_store import load_model
        return await load_model(_MODULE, session_id, MatchmakerSession, self._store)

    async def asave(self, session: MatchmakerSession) -> None:
        from mira.core.session_store import save_model
        session.updated_at = datetime.utcnow()
        await save_model(_MODULE, session.session_id, session, self._store)

    async def adelete(self, session_id: str) -> bool:
        return await self._store.delete_module_data(_MODULE, session_id)

    async def alist(self) -> list[SessionSummary]:
        from mira.core.session_store import load_model

        summaries: list[SessionSummary] = []
        for key in await self._store.list_module_keys(_MODULE):
            session = await load_model(_MODULE, key, MatchmakerSession, self._store)
            if session is None:
                continue
            issue_values = list(session.issues.values())
            done_count = len([i for i in issue_values if i.status == IssueStatus.DONE])
            manual_count = len(
                [i for i in issue_values if i.status == IssueStatus.MANUAL_REQUIRED]
            )
            summaries.append(
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
        summaries.sort(key=lambda s: s.updated_at, reverse=True)
        return summaries

    async def aappend_event(self, session: MatchmakerSession, event: MatchmakerEvent) -> None:
        session.events.append(event)
        await self.asave(session)

    # -- sync wrappers (tests / non-async callers) --------------------------

    @staticmethod
    def _run_sync(coro: Any) -> Any:
        import asyncio
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        raise RuntimeError(
            "MatchmakerSessionStore sync methods cannot be used inside a running "
            "event loop. Use the async methods (aget, asave, etc.) instead."
        )

    def create(self, session: MatchmakerSession) -> MatchmakerSession:
        return self._run_sync(self.acreate(session))

    def get(self, session_id: str) -> Optional[MatchmakerSession]:
        return self._run_sync(self.aget(session_id))

    def save(self, session: MatchmakerSession) -> None:
        self._run_sync(self.asave(session))

    def delete(self, session_id: str) -> bool:
        return self._run_sync(self.adelete(session_id))

    def list(self) -> list[SessionSummary]:
        return self._run_sync(self.alist())

    def append_event(self, session: MatchmakerSession, event: MatchmakerEvent) -> None:
        self._run_sync(self.aappend_event(session, event))

    # -- backward compat (deprecated) --------------------------------------

    @property
    def session_dir(self) -> Path:
        """Deprecated. Returns a placeholder path for backward compatibility."""
        logger.warning("MatchmakerSessionStore.session_dir is deprecated.")
        return Path("data") / "matchmaker_sessions"
