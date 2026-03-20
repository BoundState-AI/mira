"""
Module: MIRA Chat — Router Integration Helpers
Purpose: Drop-in replacement functions for the in-memory session logic
         in router.py.  These delegate to SessionManager (PostgreSQL) but
         preserve the exact same caller interface so the router can switch
         with minimal diff.

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

from ..models import ChatMessage
from .audit_writer import AuditWriter
from .session_manager import SessionManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singletons (initialized once, used by all requests)
# ---------------------------------------------------------------------------

_session_manager: SessionManager | None = None
_audit_writer: AuditWriter | None = None


def _get_session_manager() -> SessionManager:
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager


def _get_audit_writer() -> AuditWriter:
    global _audit_writer
    if _audit_writer is None:
        _audit_writer = AuditWriter()
    return _audit_writer


def get_audit_writer() -> AuditWriter:
    """Public accessor for the singleton AuditWriter.

    Used by the router to replace ``write_audit_record()`` calls.
    """
    return _get_audit_writer()


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
    - ``turn_count``  (int)
    - ``last_assessment``  (dict | None)

    The dict is *not* a live reference to the DB row — callers must
    call ``save_session_state`` to persist mutations.
    """
    mgr = _get_session_manager()
    session = await mgr.get_session(session_id, module_context=module_context)

    # Ensure the shape matches what the router expects (Phase 1 compat)
    session.setdefault("engine_context", {})
    session.setdefault("accumulated_entities", {})
    session.setdefault("turn_count", 0)
    session.setdefault("last_assessment", None)
    session.setdefault("history", [])

    return session


async def save_session_state(session_id: str, session: dict[str, Any]) -> None:
    """Persist the mutated session dict back to the database.

    Call this after the router has modified engine_context,
    accumulated_entities, turn_count, or last_assessment.
    """
    mgr = _get_session_manager()
    await mgr.update_session(
        session_id,
        engine_context=session.get("engine_context", {}),
        accumulated_entities=session.get("accumulated_entities", {}),
        turn_count=session.get("turn_count", 0),
        last_assessment=session.get("last_assessment"),
    )


async def append_history(
    session_id: str,
    user_msg: str,
    assistant_msg: str,
    engine_used: str | None,
    entities: dict[str, Any],
    envelope: dict[str, Any] | None = None,
) -> None:
    """Record a conversation turn to chat_turns and bump the session.

    Replaces ``_append_session_history(session, ...)`` in the Phase 1 router.
    """
    mgr = _get_session_manager()
    await mgr.append_turn(
        session_id=session_id,
        user_msg=user_msg,
        assistant_msg=assistant_msg,
        engine_used=engine_used,
        entities=entities,
        envelope=envelope,
    )


async def get_effective_history(
    session_id: str,
    frontend_history: list[ChatMessage],
    max_messages: int = 10,
) -> list[ChatMessage]:
    """Resolve the conversation history for the query interpreter.

    Priority:
      1. Explicit frontend history (if non-empty) — capped to *max_messages*
      2. Server-side history from chat_turns (PostgreSQL or memory)

    This replaces ``_resolve_effective_history(request.history, session["history"])``
    in the Phase 1 router.
    """
    if frontend_history:
        return frontend_history[-max_messages:]

    mgr = _get_session_manager()
    max_turns = max_messages // 2  # Each turn is 2 messages
    history = await mgr.get_history(session_id, max_turns=max_turns)
    return history[-max_messages:]
