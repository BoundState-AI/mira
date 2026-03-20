"""
Module: MIRA Chat — Session Manager
Purpose: PostgreSQL-backed server-side session store that replaces the
         Phase 1 in-memory ``_session_store`` dict in router.py.

Falls back to an in-memory dict when the database is unavailable,
preserving full Phase 1 behavior so development and CI work without
a running PostgreSQL instance.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-032, NASA-STD-8739.8B
Safety Critical: True
Deployment: AWS GovCloud West (FedRAMP High, ITAR)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..models import ChatMessage
from .connection import get_db_session, get_engine
from .schema import chat_sessions, chat_turns

logger = logging.getLogger(__name__)

# Default retention period per BS-SPEC-MIRA-CHAT-001-REV2
_DEFAULT_RETENTION_MONTHS = 24


class SessionManager:
    """Server-side session manager backed by PostgreSQL.

    Falls back to in-memory dict if database is unavailable,
    preserving Phase 1 behavior.
    """

    def __init__(self) -> None:
        # In-memory fallback (mirrors Phase 1 _session_store)
        self._memory_store: dict[str, dict[str, Any]] = {}
        self._max_memory_sessions = 500

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def _db_available(self) -> bool:
        return get_engine() is not None

    def _get_memory_session(self, session_id: str) -> dict[str, Any]:
        """Phase 1 in-memory fallback."""
        if session_id not in self._memory_store:
            if len(self._memory_store) >= self._max_memory_sessions:
                oldest = next(iter(self._memory_store))
                del self._memory_store[oldest]
            self._memory_store[session_id] = {
                "session_id": session_id,
                "engine_context": {},
                "accumulated_entities": {},
                "history": [],
                "last_assessment": None,
                "turn_count": 0,
            }
        return self._memory_store[session_id]

    # ------------------------------------------------------------------
    # get_session — upsert pattern
    # ------------------------------------------------------------------

    async def get_session(
        self,
        session_id: str,
        module_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return the session dict for *session_id*, creating if not exists.

        Parameters
        ----------
        session_id:
            Unique session identifier (from frontend or auto-generated).
        module_context:
            Optional frontend module context to store on first creation.

        Returns
        -------
        dict with keys: session_id, engine_context, accumulated_entities,
        turn_count, last_assessment.
        """
        if not self._db_available:
            return self._get_memory_session(session_id)

        try:
            async with get_db_session() as session:
                # Upsert: insert if missing, otherwise return existing
                stmt = pg_insert(chat_sessions).values(
                    session_id=session_id,
                    module_context=module_context,
                ).on_conflict_do_update(
                    index_elements=["session_id"],
                    set_={"last_active": func.now()},
                )
                await session.execute(stmt)

                # Fetch the full row
                row = (
                    await session.execute(
                        select(chat_sessions).where(
                            chat_sessions.c.session_id == session_id
                        )
                    )
                ).mappings().first()

                if row is None:
                    # Should not happen after upsert, but be defensive
                    logger.error("[SESSION] Upsert succeeded but row not found: %s", session_id)
                    return self._get_memory_session(session_id)

                return {
                    "session_id": row["session_id"],
                    "engine_context": dict(row["engine_context"] or {}),
                    "accumulated_entities": dict(row["accumulated_entities"] or {}),
                    "turn_count": row["turn_count"] or 0,
                    "last_assessment": row["last_assessment"],
                }

        except Exception:
            logger.exception("[SESSION] DB read failed for session %s, falling back to memory", session_id)
            return self._get_memory_session(session_id)

    # ------------------------------------------------------------------
    # update_session — partial update of session fields
    # ------------------------------------------------------------------

    async def update_session(self, session_id: str, **updates: Any) -> None:
        """Update one or more fields on an existing session row.

        Accepted keyword arguments map to chat_sessions columns:
        engine_context, accumulated_entities, turn_count, last_assessment,
        module_context.
        """
        if not self._db_available:
            mem = self._get_memory_session(session_id)
            for key, value in updates.items():
                if key in mem:
                    mem[key] = value
            return

        # Map caller keys to column updates
        allowed_columns = {
            "engine_context",
            "accumulated_entities",
            "turn_count",
            "last_assessment",
            "module_context",
        }
        col_updates = {k: v for k, v in updates.items() if k in allowed_columns}
        col_updates["last_active"] = func.now()

        try:
            async with get_db_session() as session:
                await session.execute(
                    update(chat_sessions)
                    .where(chat_sessions.c.session_id == session_id)
                    .values(**col_updates)
                )
        except Exception:
            logger.exception("[SESSION] DB update failed for session %s", session_id)
            # Silent fallback — next read will re-fetch from DB or memory
            mem = self._get_memory_session(session_id)
            for key, value in updates.items():
                if key in mem:
                    mem[key] = value

    # ------------------------------------------------------------------
    # append_turn — write to chat_turns AND bump session
    # ------------------------------------------------------------------

    async def append_turn(
        self,
        session_id: str,
        user_msg: str,
        assistant_msg: str,
        engine_used: str | None,
        entities: dict[str, Any],
        envelope: dict[str, Any] | None = None,
    ) -> None:
        """Record a conversation turn.

        Writes one row to ``chat_turns`` and bumps ``last_active`` and
        ``turn_count`` on the parent session.
        """
        if not self._db_available:
            mem = self._get_memory_session(session_id)
            history: list = mem.setdefault("history", [])
            history.append(ChatMessage(role="user", content=user_msg, entities=entities))
            history.append(
                ChatMessage(
                    role="assistant",
                    content=assistant_msg,
                    engine_used=engine_used,
                    entities=entities,
                )
            )
            # Keep only the last 10 messages
            mem["history"] = history[-10:]
            mem["turn_count"] = mem.get("turn_count", 0) + 1
            return

        try:
            async with get_db_session() as session:
                # Get current turn count
                row = (
                    await session.execute(
                        select(chat_sessions.c.turn_count).where(
                            chat_sessions.c.session_id == session_id
                        )
                    )
                ).scalar_one_or_none()

                next_turn = (row or 0) + 1

                # Insert the turn
                await session.execute(
                    chat_turns.insert().values(
                        session_id=session_id,
                        turn_number=next_turn,
                        user_message=user_msg,
                        assistant_message=assistant_msg,
                        engine_used=engine_used,
                        entities=entities or {},
                        envelope_json=envelope,
                    )
                )

                # Bump session
                await session.execute(
                    update(chat_sessions)
                    .where(chat_sessions.c.session_id == session_id)
                    .values(
                        turn_count=next_turn,
                        last_active=func.now(),
                    )
                )

        except Exception:
            logger.exception("[SESSION] append_turn DB write failed for session %s", session_id)
            # Fall back to memory so the current request still works
            mem = self._get_memory_session(session_id)
            history = mem.setdefault("history", [])
            history.append(ChatMessage(role="user", content=user_msg, entities=entities))
            history.append(
                ChatMessage(
                    role="assistant",
                    content=assistant_msg,
                    engine_used=engine_used,
                    entities=entities,
                )
            )
            mem["history"] = history[-10:]

    # ------------------------------------------------------------------
    # get_history — last N messages as ChatMessage
    # ------------------------------------------------------------------

    async def get_history(
        self,
        session_id: str,
        max_turns: int = 5,
    ) -> list[ChatMessage]:
        """Return the last *max_turns* exchanges as ChatMessage objects.

        Each turn produces two messages (user + assistant), so this
        returns up to ``max_turns * 2`` ChatMessage objects.
        """
        if not self._db_available:
            mem = self._get_memory_session(session_id)
            history: list[ChatMessage] = mem.get("history", [])
            # max_turns turns = max_turns*2 messages
            return history[-(max_turns * 2) :]

        try:
            async with get_db_session() as session:
                rows = (
                    await session.execute(
                        select(chat_turns)
                        .where(chat_turns.c.session_id == session_id)
                        .order_by(chat_turns.c.turn_number.desc())
                        .limit(max_turns)
                    )
                ).mappings().all()

            # Rows come back newest-first; reverse for chronological order
            rows = list(reversed(rows))

            messages: list[ChatMessage] = []
            for row in rows:
                entities = dict(row["entities"] or {})
                messages.append(
                    ChatMessage(
                        role="user",
                        content=row["user_message"],
                        entities=entities,
                    )
                )
                messages.append(
                    ChatMessage(
                        role="assistant",
                        content=row["assistant_message"],
                        engine_used=row["engine_used"],
                        entities=entities,
                    )
                )

            return messages

        except Exception:
            logger.exception("[SESSION] get_history DB read failed for session %s", session_id)
            mem = self._get_memory_session(session_id)
            return mem.get("history", [])[-(max_turns * 2) :]

    # ------------------------------------------------------------------
    # purge_before — retention enforcement
    # ------------------------------------------------------------------

    async def purge_before(
        self,
        cutoff: datetime | None = None,
    ) -> int:
        """Delete sessions (and cascaded turns) older than *cutoff*.

        If *cutoff* is not provided, defaults to 24 months ago per spec.

        Returns the number of sessions deleted.
        """
        if cutoff is None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=_DEFAULT_RETENTION_MONTHS * 30)

        if not self._db_available:
            # Memory store has no timestamps — just clear everything
            count = len(self._memory_store)
            self._memory_store.clear()
            return count

        try:
            async with get_db_session() as session:
                # chat_turns are CASCADE deleted via FK
                result = await session.execute(
                    delete(chat_sessions).where(
                        chat_sessions.c.last_active < cutoff
                    )
                )
                deleted = result.rowcount
                logger.info(
                    "[SESSION] Purged %d sessions older than %s",
                    deleted,
                    cutoff.isoformat(),
                )
                return deleted

        except Exception:
            logger.exception("[SESSION] purge_before failed")
            return 0
