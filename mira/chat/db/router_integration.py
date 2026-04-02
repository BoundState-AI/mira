"""
Module: MIRA Chat — Router Integration Helpers
Purpose: Drop-in replacement functions for the in-memory session logic
         in router.py.  These delegate to the shared ``SessionStore``
         abstraction in ``mira.core.session_store`` so the router can
         switch with minimal diff.

         When ``MIRA_SESSION_BACKEND=memory`` (default), the core
         ``MemorySessionStore`` is used directly. When a chat database
         URL is configured and the backend is not pinned elsewhere, the
         shared store factory selects the Postgres adapter over the
         existing chat ``SessionManager``.

Usage in router.py::

    from .db.router_integration import (
        get_or_create_session,
        save_session_state,
        append_history,
        get_effective_history,
    )

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
from typing import Any

from ...core.session_store import SessionData, get_session_store
from ..models import ChatMessage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singletons (initialized once, used by all requests)
# ---------------------------------------------------------------------------

_audit_writer = None


def get_audit_writer():
    """Public accessor for the singleton AuditWriter.

    Used by the router to replace ``write_audit_record()`` calls.
    Lazily imports AuditWriter to avoid pulling in sqlalchemy at
    module load time.
    """
    global _audit_writer
    if _audit_writer is None:
        from .audit_writer import AuditWriter
        _audit_writer = AuditWriter()
    return _audit_writer


# ---------------------------------------------------------------------------
# Helpers — convert between SessionData and the dict the router expects
# ---------------------------------------------------------------------------


def _session_data_to_dict(data: SessionData) -> dict[str, Any]:
    """Convert a ``SessionData`` to the dict shape the router uses.

    The router mutates the dict in place during the request, then
    ``save_session_state`` persists the mutations back.
    """
    return {
        "session_id": data.session_id,
        "engine_context": dict(data.engine_context),
        "accumulated_entities": dict(data.accumulated_entities),
        "history": [
            ChatMessage(**entry) if isinstance(entry, dict) else entry
            for entry in data.history
        ],
        "turn_count": data.turn_count,
        "last_assessment": data.last_assessment,
    }


def _dict_to_session_data(session_id: str, session: dict[str, Any]) -> SessionData:
    """Convert the router's mutated session dict back to ``SessionData``."""
    history_raw: list[dict[str, Any]] = []
    for entry in session.get("history", []):
        if isinstance(entry, ChatMessage):
            history_raw.append(entry.model_dump(mode="json"))
        elif isinstance(entry, dict):
            history_raw.append(entry)
        else:
            history_raw.append(dict(entry))

    return SessionData(
        session_id=session_id,
        engine_context=session.get("engine_context", {}),
        accumulated_entities=session.get("accumulated_entities", {}),
        history=history_raw,
        turn_count=session.get("turn_count", 0),
        last_assessment=session.get("last_assessment"),
    )


# ---------------------------------------------------------------------------
# Drop-in session functions
# ---------------------------------------------------------------------------


async def get_or_create_session(
    session_id: str,
    module_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the session dict, creating it if it does not exist.

    This replaces ``_get_session(session_id)`` in the Phase 1 router.
    The returned dict has the same shape:

    - ``session_id``
    - ``engine_context``  (dict)
    - ``accumulated_entities``  (dict)
    - ``history``  (list[ChatMessage])
    - ``turn_count``  (int)
    - ``last_assessment``  (dict | None)

    The dict is *not* a live reference to the store — callers must
    call ``save_session_state`` to persist mutations.
    """
    store = get_session_store()
    data = await store.get(session_id)
    session = _session_data_to_dict(data)

    # Ensure the shape matches what the router expects (Phase 1 compat)
    session.setdefault("engine_context", {})
    session.setdefault("accumulated_entities", {})
    session.setdefault("turn_count", 0)
    session.setdefault("last_assessment", None)
    session.setdefault("history", [])

    return session


async def save_session_state(session_id: str, session: dict[str, Any]) -> None:
    """Persist the mutated session dict back to the store.

    Call this after the router has modified engine_context,
    accumulated_entities, turn_count, or last_assessment.
    """
    store = get_session_store()
    data = _dict_to_session_data(session_id, session)
    await store.save(session_id, data)


async def append_history(
    session_id: str,
    user_msg: str,
    assistant_msg: str,
    engine_used: str | None,
    entities: dict[str, Any],
    envelope: dict[str, Any] | None = None,
) -> None:
    """Record a conversation turn and persist to the store.

    Replaces ``_append_session_history(session, ...)`` in the Phase 1 router.
    """
    store = get_session_store()
    data = await store.get(session_id)

    from ...core.session_store import _MAX_HISTORY_MESSAGES

    data.history.append(
        ChatMessage(role="user", content=user_msg, entities=entities).model_dump(mode="json")
    )
    data.history.append(
        ChatMessage(
            role="assistant",
            content=assistant_msg,
            engine_used=engine_used,
            entities=entities,
        ).model_dump(mode="json")
    )
    # Cap history
    data.history = data.history[-_MAX_HISTORY_MESSAGES:]

    await store.save(session_id, data)


async def get_effective_history(
    session_id: str,
    frontend_history: list[ChatMessage],
    max_messages: int = 10,
) -> list[ChatMessage]:
    """Resolve the conversation history for the query interpreter.

    Priority:
      1. Explicit frontend history (if non-empty) — capped to *max_messages*
      2. Server-side history from the session store

    This replaces ``_resolve_effective_history(request.history, session["history"])``
    in the Phase 1 router.
    """
    if frontend_history:
        return frontend_history[-max_messages:]

    store = get_session_store()
    data = await store.get(session_id)
    messages: list[ChatMessage] = []
    for entry in data.history[-max_messages:]:
        if isinstance(entry, ChatMessage):
            messages.append(entry)
        elif isinstance(entry, dict):
            messages.append(ChatMessage(**entry))
    return messages
