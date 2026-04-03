"""
Module: MIRA Chat — Router Integration Helpers
Purpose: Drop-in replacement functions for the in-memory session logic
         in router.py. These delegate to the shared ``SessionStore``
         abstraction in ``mira.core.session_store`` so the router can
         switch with minimal diff.
"""

from __future__ import annotations

import logging
from typing import Any

from ...core.session_store import SessionData, get_session_store
from ..models import ChatMessage

logger = logging.getLogger(__name__)

_audit_writer = None


def get_audit_writer():
    """Public accessor for the singleton AuditWriter."""

    global _audit_writer
    if _audit_writer is None:
        from .audit_writer import AuditWriter

        _audit_writer = AuditWriter()
    return _audit_writer


def _session_data_to_dict(data: SessionData) -> dict[str, Any]:
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


async def get_or_create_session(
    session_id: str,
    module_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    store = get_session_store()
    data = await store.get(session_id)
    session = _session_data_to_dict(data)
    session.setdefault("engine_context", {})
    session.setdefault("accumulated_entities", {})
    session.setdefault("turn_count", 0)
    session.setdefault("last_assessment", None)
    session.setdefault("history", [])
    if module_context and not session.get("module_context"):
        session["module_context"] = dict(module_context)
    return session


async def save_session_state(session_id: str, session: dict[str, Any]) -> None:
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
    data.history = data.history[-_MAX_HISTORY_MESSAGES:]
    await store.save(session_id, data)


async def get_effective_history(
    session_id: str,
    frontend_history: list[ChatMessage],
    max_messages: int = 10,
) -> list[ChatMessage]:
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
