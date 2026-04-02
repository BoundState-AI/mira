"""
Module: MIRA Core — Shared Session Store
Purpose: Backend-agnostic session abstraction used by chat (and future
         modules like OCA, MUA v7, MP Plan) to persist session state
         across turns.

Design:
  - ``SessionStore`` is a Protocol (structural subtyping) so backends
    can be swapped without inheritance coupling.
  - ``SessionData`` is a Pydantic model — the canonical session shape.
    Serialization boundary uses ``.model_dump(mode="json")``.
  - ``MemorySessionStore`` is the default in-process backend used for
    development, CI, and single-process deployments.
  - ``get_session_store()`` is a factory that reads ``MIRA_SESSION_BACKEND``
    and returns a singleton store instance.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-032, NASA-STD-8739.8B
Safety Critical: True
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from collections import OrderedDict
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canonical session data model
# ---------------------------------------------------------------------------

_MAX_HISTORY_MESSAGES = 10


class SessionData(BaseModel):
    """The canonical session shape shared by all MIRA modules.

    History entries are plain dicts (not ChatMessage) so the core layer
    stays decoupled from chat-specific models.  Chat converts to/from
    ``ChatMessage`` at the boundary.
    """

    session_id: str
    engine_context: dict[str, Any] = Field(default_factory=dict)
    accumulated_entities: dict[str, Any] = Field(default_factory=dict)
    history: list[dict[str, Any]] = Field(default_factory=list)
    turn_count: int = 0
    last_assessment: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# SessionStore protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class SessionStore(Protocol):
    """Async session persistence interface.

    Backends must implement all methods.  The factory function
    ``get_session_store()`` returns a concrete instance chosen by
    the ``MIRA_SESSION_BACKEND`` environment variable.

    Chat-specific methods (get/save/delete/exists) operate on
    ``SessionData``.  Module-aware methods (get_module_data etc.)
    store arbitrary JSON payloads keyed by ``(module, key)``,
    enabling OCA, MUA v7, and future modules to share the same
    backend without a module-specific store.
    """

    # -- Chat session methods (Phase 1) ------------------------------------

    async def get(self, session_id: str) -> SessionData:
        """Return the session for *session_id*, creating if absent."""
        ...

    async def save(self, session_id: str, data: SessionData) -> None:
        """Persist a (possibly mutated) session."""
        ...

    async def delete(self, session_id: str) -> bool:
        """Remove a session.  Return True if it existed."""
        ...

    async def exists(self, session_id: str) -> bool:
        """Check whether a session exists without creating it."""
        ...

    # -- Generic module data methods (Phase 2) -----------------------------

    async def get_module_data(self, module: str, key: str) -> dict[str, Any] | None:
        """Load a JSON payload for *module*/*key*, or ``None`` if absent."""
        ...

    async def save_module_data(self, module: str, key: str, data: dict[str, Any]) -> None:
        """Persist a JSON payload for *module*/*key*."""
        ...

    async def delete_module_data(self, module: str, key: str) -> bool:
        """Delete the entry for *module*/*key*.  Return True if it existed."""
        ...

    async def list_module_keys(self, module: str) -> list[str]:
        """Return all keys stored under *module*."""
        ...


# ---------------------------------------------------------------------------
# MemorySessionStore — fully functional in-process backend
# ---------------------------------------------------------------------------


class MemorySessionStore:
    """In-memory session store backed by an ``OrderedDict``.

    Thread-safe via a ``threading.Lock``.  Caps the number of sessions
    to ``max_sessions`` using FIFO eviction.  History is capped to
    ``max_history`` messages per session.
    """

    def __init__(
        self,
        *,
        max_sessions: int = 500,
        max_history: int = _MAX_HISTORY_MESSAGES,
    ) -> None:
        self._store: OrderedDict[str, SessionData] = OrderedDict()
        self._module_data: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = threading.Lock()
        self.max_sessions = max_sessions
        self.max_history = max_history

    # -- protocol methods --------------------------------------------------

    async def get(self, session_id: str) -> SessionData:
        with self._lock:
            if session_id in self._store:
                # Move to end (most recently accessed)
                self._store.move_to_end(session_id)
                return self._store[session_id]
            # Evict oldest if at capacity
            if len(self._store) >= self.max_sessions:
                evicted_id, _ = self._store.popitem(last=False)
                logger.debug("[SESSION-MEM] Evicted oldest session %s", evicted_id)
            data = SessionData(session_id=session_id)
            self._store[session_id] = data
            return data

    async def save(self, session_id: str, data: SessionData) -> None:
        with self._lock:
            self._store[session_id] = data
            self._store.move_to_end(session_id)

    async def delete(self, session_id: str) -> bool:
        with self._lock:
            if session_id in self._store:
                del self._store[session_id]
                return True
            return False

    async def exists(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._store

    # -- module data methods -----------------------------------------------

    async def get_module_data(self, module: str, key: str) -> dict[str, Any] | None:
        with self._lock:
            return self._module_data.get((module, key))

    async def save_module_data(self, module: str, key: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._module_data[(module, key)] = data

    async def delete_module_data(self, module: str, key: str) -> bool:
        with self._lock:
            if (module, key) in self._module_data:
                del self._module_data[(module, key)]
                return True
            return False

    async def list_module_keys(self, module: str) -> list[str]:
        with self._lock:
            return [k for (m, k) in self._module_data if m == module]

    # -- convenience -------------------------------------------------------

    @property
    def session_count(self) -> int:
        with self._lock:
            return len(self._store)


# ---------------------------------------------------------------------------
# DynamoDB backend — scaffolded, not production-ready
# ---------------------------------------------------------------------------


class DynamoDBSessionStore:
    """Placeholder for future DynamoDB-backed session store.

    Raises ``NotImplementedError`` on all operations.  The interface
    shape is defined so callers can type-check and integration tests
    can verify the factory wiring.
    """

    async def get(self, session_id: str) -> SessionData:
        raise NotImplementedError("DynamoDB session store is not yet implemented")

    async def save(self, session_id: str, data: SessionData) -> None:
        raise NotImplementedError("DynamoDB session store is not yet implemented")

    async def delete(self, session_id: str) -> bool:
        raise NotImplementedError("DynamoDB session store is not yet implemented")

    async def exists(self, session_id: str) -> bool:
        raise NotImplementedError("DynamoDB session store is not yet implemented")

    async def get_module_data(self, module: str, key: str) -> dict[str, Any] | None:
        raise NotImplementedError("DynamoDB session store is not yet implemented")

    async def save_module_data(self, module: str, key: str, data: dict[str, Any]) -> None:
        raise NotImplementedError("DynamoDB session store is not yet implemented")

    async def delete_module_data(self, module: str, key: str) -> bool:
        raise NotImplementedError("DynamoDB session store is not yet implemented")

    async def list_module_keys(self, module: str) -> list[str]:
        raise NotImplementedError("DynamoDB session store is not yet implemented")


# ---------------------------------------------------------------------------
# Postgres backend - chat SessionManager adapter
# ---------------------------------------------------------------------------


class PostgresSessionStore:
    """Adapter over the existing chat PostgreSQL SessionManager.

    Imports are kept inside methods so environments without SQLAlchemy can
    still import this module as long as the postgres backend is not selected.
    """

    def __init__(self) -> None:
        self._manager = None
        self._memory_fallback = MemorySessionStore()
        self._init_lock = asyncio.Lock()
        self._db_initialized = False

    async def _get_manager(self):
        if self._manager is None:
            try:
                from ..chat.db.session_manager import SessionManager

                self._manager = SessionManager()
            except Exception:
                logger.exception(
                    "[SESSION] Failed to import chat SessionManager; "
                    "PostgresSessionStore will use memory fallback."
                )
                self._manager = False
        return self._manager

    async def _ensure_db_initialized(self) -> None:
        if self._db_initialized:
            return

        async with self._init_lock:
            if self._db_initialized:
                return

            try:
                from ..chat.db.connection import get_engine, init_db
                from ..chat.db.migrations import run_migrations

                if get_engine() is None:
                    engine = await init_db()
                    if engine is not None:
                        await run_migrations(engine)
            except Exception:
                logger.exception(
                    "[SESSION] Failed to initialize chat PostgreSQL backend; "
                    "SessionManager will use its in-memory fallback."
                )
            finally:
                self._db_initialized = True

    async def get(self, session_id: str) -> SessionData:
        await self._ensure_db_initialized()
        mgr = await self._get_manager()
        if not mgr:
            return await self._memory_fallback.get(session_id)
        session = await mgr.get_session(session_id)
        history = await mgr.get_history(session_id, max_turns=max(1, _MAX_HISTORY_MESSAGES // 2))
        return SessionData(
            session_id=session_id,
            engine_context=dict(session.get("engine_context") or {}),
            accumulated_entities=dict(session.get("accumulated_entities") or {}),
            history=[
                entry.model_dump(mode="json") if hasattr(entry, "model_dump") else dict(entry)
                for entry in history
            ],
            turn_count=int(session.get("turn_count") or 0),
            last_assessment=session.get("last_assessment"),
        )

    async def save(self, session_id: str, data: SessionData) -> None:
        await self._ensure_db_initialized()
        mgr = await self._get_manager()
        if not mgr:
            await self._memory_fallback.save(session_id, data)
            return

        # If the router provided history from the frontend, seed any missing
        # turns into the backend before saving scalar session state.
        existing_history = await mgr.get_history(
            session_id, max_turns=max(1, len(data.history) // 2 + 1)
        )
        existing_len = len(existing_history)
        normalized_history = [
            entry.model_dump(mode="json") if hasattr(entry, "model_dump") else dict(entry)
            for entry in existing_history
        ]

        if len(data.history) > existing_len and data.history[:existing_len] == normalized_history:
            for idx in range(existing_len, len(data.history), 2):
                if idx + 1 >= len(data.history):
                    break
                user_msg = data.history[idx]
                assistant_msg = data.history[idx + 1]
                if user_msg.get("role") != "user" or assistant_msg.get("role") != "assistant":
                    continue
                await mgr.append_turn(
                    session_id=session_id,
                    user_msg=str(user_msg.get("content", "")),
                    assistant_msg=str(assistant_msg.get("content", "")),
                    engine_used=assistant_msg.get("engine_used"),
                    entities=dict(assistant_msg.get("entities") or user_msg.get("entities") or {}),
                )

        await mgr.update_session(
            session_id,
            engine_context=data.engine_context,
            accumulated_entities=data.accumulated_entities,
            turn_count=data.turn_count,
            last_assessment=data.last_assessment,
        )

    async def delete(self, session_id: str) -> bool:
        await self._ensure_db_initialized()
        mgr = await self._get_manager()
        if not mgr:
            return await self._memory_fallback.delete(session_id)
        if not await mgr.get_session(session_id):
            return False

        try:
            from ..chat.db.connection import get_db_session, get_engine
            from ..chat.db.schema import chat_sessions
            from sqlalchemy import delete

            if get_engine() is None:
                mem = getattr(mgr, "_memory_store", None)
                if isinstance(mem, dict):
                    return mem.pop(session_id, None) is not None
                return False

            async with get_db_session() as session:
                result = await session.execute(
                    delete(chat_sessions).where(chat_sessions.c.session_id == session_id)
                )
                return bool(result.rowcount)
        except Exception:
            logger.exception("[SESSION] Failed to delete postgres-backed chat session %s", session_id)
            return False

    async def exists(self, session_id: str) -> bool:
        await self._ensure_db_initialized()
        mgr = await self._get_manager()
        if not mgr:
            return await self._memory_fallback.exists(session_id)
        session = await mgr.get_session(session_id)
        return bool(session and session.get("session_id") == session_id)

    async def get_module_data(self, module: str, key: str) -> dict[str, Any] | None:
        await self._ensure_db_initialized()
        mgr = await self._get_manager()
        if not mgr:
            return await self._memory_fallback.get_module_data(module, key)

        try:
            from sqlalchemy import select

            from ..chat.db.connection import get_db_session, get_engine
            from ..chat.db.schema import module_state

            if get_engine() is None:
                return await self._memory_fallback.get_module_data(module, key)

            async with get_db_session() as session:
                row = (
                    await session.execute(
                        select(module_state.c.payload).where(
                            module_state.c.module == module,
                            module_state.c.state_key == key,
                        )
                    )
                ).scalar_one_or_none()
                return dict(row) if row is not None else None
        except Exception:
            logger.exception(
                "[SESSION] Failed to load module state for %s/%s from postgres backend",
                module,
                key,
            )
            return None

    async def save_module_data(self, module: str, key: str, data: dict[str, Any]) -> None:
        await self._ensure_db_initialized()
        mgr = await self._get_manager()
        if not mgr:
            await self._memory_fallback.save_module_data(module, key, data)
            return

        try:
            from sqlalchemy import func
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            from ..chat.db.connection import get_db_session, get_engine
            from ..chat.db.schema import module_state

            if get_engine() is None:
                await self._memory_fallback.save_module_data(module, key, data)
                return

            async with get_db_session() as session:
                stmt = pg_insert(module_state).values(
                    module=module,
                    state_key=key,
                    payload=data,
                ).on_conflict_do_update(
                    constraint="uq_module_state_module_key",
                    set_={
                        "payload": data,
                        "updated_at": func.now(),
                    },
                )
                await session.execute(stmt)
        except Exception:
            logger.exception(
                "[SESSION] Failed to save module state for %s/%s to postgres backend",
                module,
                key,
            )
            raise

    async def delete_module_data(self, module: str, key: str) -> bool:
        await self._ensure_db_initialized()
        mgr = await self._get_manager()
        if not mgr:
            return await self._memory_fallback.delete_module_data(module, key)

        try:
            from sqlalchemy import delete

            from ..chat.db.connection import get_db_session, get_engine
            from ..chat.db.schema import module_state

            if get_engine() is None:
                return await self._memory_fallback.delete_module_data(module, key)

            async with get_db_session() as session:
                result = await session.execute(
                    delete(module_state).where(
                        module_state.c.module == module,
                        module_state.c.state_key == key,
                    )
                )
                return bool(result.rowcount)
        except Exception:
            logger.exception(
                "[SESSION] Failed to delete module state for %s/%s from postgres backend",
                module,
                key,
            )
            return False

    async def list_module_keys(self, module: str) -> list[str]:
        await self._ensure_db_initialized()
        mgr = await self._get_manager()
        if not mgr:
            return await self._memory_fallback.list_module_keys(module)

        try:
            from sqlalchemy import select

            from ..chat.db.connection import get_db_session, get_engine
            from ..chat.db.schema import module_state

            if get_engine() is None:
                return await self._memory_fallback.list_module_keys(module)

            async with get_db_session() as session:
                rows = (
                    await session.execute(
                        select(module_state.c.state_key)
                        .where(module_state.c.module == module)
                        .order_by(module_state.c.updated_at.desc())
                    )
                ).scalars().all()
                return list(rows)
        except Exception:
            logger.exception(
                "[SESSION] Failed to list module state keys for %s from postgres backend",
                module,
            )
            return []


# ---------------------------------------------------------------------------
# Typed helpers for module data
# ---------------------------------------------------------------------------

_T = Any  # TypeVar placeholder — actual type checking at call site


async def load_model(
    module: str,
    key: str,
    model_cls: type,
    store: SessionStore | None = None,
) -> Any | None:
    """Load a Pydantic model from the shared store.

    Parameters
    ----------
    module : str
        Module namespace (e.g. ``"oca"``, ``"mua_v7"``).
    key : str
        Unique key within the module (e.g. system_id, session_id).
    model_cls : type
        Pydantic model class with ``model_validate()``.
    store : SessionStore, optional
        If not provided, uses the singleton from ``get_session_store()``.

    Returns
    -------
    model instance or None if the key does not exist.
    """
    if store is None:
        store = get_session_store()
    raw = await store.get_module_data(module, key)
    if raw is None:
        return None
    return model_cls.model_validate(raw)


async def save_model(
    module: str,
    key: str,
    model: Any,
    store: SessionStore | None = None,
) -> None:
    """Persist a Pydantic model to the shared store.

    Parameters
    ----------
    module : str
        Module namespace (e.g. ``"oca"``, ``"mua_v7"``).
    key : str
        Unique key within the module.
    model : BaseModel
        Pydantic model instance. Serialized via ``model_dump(mode="json")``.
    store : SessionStore, optional
        If not provided, uses the singleton from ``get_session_store()``.
    """
    if store is None:
        store = get_session_store()
    await store.save_module_data(module, key, model.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# Factory / singleton
# ---------------------------------------------------------------------------

_store_instance: SessionStore | None = None
_store_lock = threading.Lock()


def get_session_store() -> SessionStore:
    """Return the singleton ``SessionStore`` chosen by environment.

    ``MIRA_SESSION_BACKEND`` values:
      - ``memory``   (default) - in-process ``MemorySessionStore``
      - ``postgres`` - adapter over chat ``SessionManager``
      - ``dynamodb`` - scaffolded ``DynamoDBSessionStore``

    The singleton is created on first call and reused thereafter.
    """
    global _store_instance
    if _store_instance is not None:
        return _store_instance

    with _store_lock:
        # Double-check after acquiring lock
        if _store_instance is not None:
            return _store_instance

        backend = os.environ.get("MIRA_SESSION_BACKEND", "").lower().strip()

        if not backend:
            if os.environ.get("MIRA_CHAT_DATABASE_URL", "").strip() or os.environ.get(
                "POSTGRES_HOST", ""
            ).strip():
                backend = "postgres"
            else:
                backend = "memory"

        if backend == "memory":
            _store_instance = MemorySessionStore()
            logger.info("[SESSION] Using MemorySessionStore backend")
        elif backend == "postgres":
            _store_instance = PostgresSessionStore()
            logger.info("[SESSION] Using PostgresSessionStore backend")
        elif backend == "dynamodb":
            _store_instance = DynamoDBSessionStore()
            logger.info("[SESSION] Using DynamoDBSessionStore backend (scaffolded)")
        else:
            logger.warning(
                "[SESSION] Unknown MIRA_SESSION_BACKEND=%r, falling back to memory",
                backend,
            )
            _store_instance = MemorySessionStore()

        return _store_instance


def reset_session_store() -> None:
    """Reset the singleton (for testing only)."""
    global _store_instance
    with _store_lock:
        _store_instance = None
