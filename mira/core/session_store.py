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

_MAX_HISTORY_MESSAGES = 10
_PLACEHOLDER_VALUES = {"", "restored", "placeholder", "changeme", "none", "null", "undefined"}
_LOCALHOST_VALUES = {"localhost", "127.0.0.1", "::1"}


def _normalized_env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _looks_real_secret(value: str) -> bool:
    return value.strip().lower() not in _PLACEHOLDER_VALUES


def _looks_real_host(value: str) -> bool:
    cleaned = value.strip().lower()
    return cleaned not in _PLACEHOLDER_VALUES and cleaned not in _LOCALHOST_VALUES


def _has_usable_postgres_configuration() -> bool:
    database_url = _normalized_env("MIRA_CHAT_DATABASE_URL")
    if database_url:
        return True
    password = _normalized_env("POSTGRES_PASSWORD")
    host = _normalized_env("POSTGRES_HOST")
    return _looks_real_secret(password) and _looks_real_host(host)


def _runtime_environment() -> str:
    return (
        _normalized_env("MIRA_ENV")
        or _normalized_env("ENVIRONMENT")
        or "development"
    ).lower()


def _production_like_environment() -> bool:
    return _runtime_environment() not in {"development", "dev", "test", "testing", "ci", "local"}


def _postgres_fail_closed() -> bool:
    return _normalized_env("MIRA_SESSION_BACKEND").lower() == "postgres" and _production_like_environment()


class SessionData(BaseModel):
    """The canonical session shape shared by all MIRA modules."""

    session_id: str
    engine_context: dict[str, Any] = Field(default_factory=dict)
    accumulated_entities: dict[str, Any] = Field(default_factory=dict)
    history: list[dict[str, Any]] = Field(default_factory=list)
    turn_count: int = Field(default=0)
    last_assessment: dict[str, Any] | None = Field(default=None)


@runtime_checkable
class SessionStore(Protocol):
    async def get(self, session_id: str) -> SessionData:
        ...

    async def save(self, session_id: str, data: SessionData) -> None:
        ...

    async def delete(self, session_id: str) -> bool:
        ...

    async def exists(self, session_id: str) -> bool:
        ...

    async def get_module_data(self, module: str, key: str) -> dict[str, Any] | None:
        ...

    async def save_module_data(self, module: str, key: str, data: dict[str, Any]) -> None:
        ...

    async def delete_module_data(self, module: str, key: str) -> bool:
        ...

    async def list_module_keys(self, module: str) -> list[str]:
        ...


class MemorySessionStore:
    """In-memory session store backed by an ``OrderedDict``."""

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

    async def get(self, session_id: str) -> SessionData:
        with self._lock:
            if session_id in self._store:
                self._store.move_to_end(session_id)
                return self._store[session_id]
            if len(self._store) >= self.max_sessions:
                evicted_id, _ = self._store.popitem(last=False)
                logger.debug("[SESSION-MEM] Evicted oldest session %s", evicted_id)
            data = SessionData(session_id=session_id)
            self._store[session_id] = data
            return data

    async def save(self, session_id: str, data: SessionData) -> None:
        with self._lock:
            if len(data.history) > self.max_history:
                data.history = data.history[-self.max_history :]
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

    @property
    def session_count(self) -> int:
        with self._lock:
            return len(self._store)


class DynamoDBSessionStore:
    """Placeholder for future DynamoDB-backed session store."""

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


class PostgresSessionStore:
    """Adapter over the existing chat PostgreSQL SessionManager."""

    def __init__(self) -> None:
        self._manager = None
        self._memory_fallback = MemorySessionStore()
        self._init_lock = asyncio.Lock()
        self._db_initialized = False
        self._fail_closed = _postgres_fail_closed()

    def _raise_or_memory(self, message: str) -> MemorySessionStore:
        if self._fail_closed:
            raise RuntimeError(message)
        logger.warning("%s Falling back to memory session store.", message)
        return self._memory_fallback

    async def preflight(self) -> None:
        await self._ensure_db_initialized()
        mgr = await self._get_manager()
        if not mgr:
            raise RuntimeError("Postgres session backend is unavailable during startup preflight.")

        from sqlalchemy import text

        from ..chat.db.connection import get_db_session, get_engine

        if get_engine() is None:
            raise RuntimeError("Chat PostgreSQL engine did not initialize for postgres session backend.")

        async with get_db_session() as session:
            await session.execute(text("SELECT 1"))

    async def _get_manager(self):
        if self._manager is None:
            try:
                from ..chat.db.session_manager import SessionManager

                self._manager = SessionManager()
            except Exception as exc:
                message = "[SESSION] Failed to import chat SessionManager for postgres backend."
                if self._fail_closed:
                    raise RuntimeError(message) from exc
                logger.exception("%s PostgresSessionStore will use memory fallback.", message)
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
            except Exception as exc:
                message = "[SESSION] Failed to initialize chat PostgreSQL backend."
                if self._fail_closed:
                    raise RuntimeError(message) from exc
                logger.exception("%s SessionManager will use its in-memory fallback.", message)
            finally:
                self._db_initialized = True

    async def get(self, session_id: str) -> SessionData:
        await self._ensure_db_initialized()
        mgr = await self._get_manager()
        if not mgr:
            return await self._raise_or_memory(
                "[SESSION] Postgres session manager unavailable during get()."
            ).get(session_id)
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
            await self._raise_or_memory(
                "[SESSION] Postgres session manager unavailable during save()."
            ).save(session_id, data)
            return

        existing_history = await mgr.get_history(
            session_id,
            max_turns=max(1, len(data.history) // 2 + 1),
        )
        normalized_existing = [
            entry.model_dump(mode="json") if hasattr(entry, "model_dump") else dict(entry)
            for entry in existing_history
        ]
        existing_len = len(normalized_existing)

        if len(data.history) > existing_len and data.history[:existing_len] == normalized_existing:
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
            return await self._raise_or_memory(
                "[SESSION] Postgres session manager unavailable during delete()."
            ).delete(session_id)

        try:
            from sqlalchemy import delete

            from ..chat.db.connection import get_db_session, get_engine
            from ..chat.db.schema import chat_sessions

            if get_engine() is None:
                if self._fail_closed:
                    raise RuntimeError("Postgres session backend lost its database engine during delete().")
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
            return await self._raise_or_memory(
                "[SESSION] Postgres session manager unavailable during exists()."
            ).exists(session_id)
        session = await mgr.get_session(session_id)
        return bool(session and session.get("session_id") == session_id)

    async def get_module_data(self, module: str, key: str) -> dict[str, Any] | None:
        await self._ensure_db_initialized()
        mgr = await self._get_manager()
        if not mgr:
            return await self._raise_or_memory(
                "[SESSION] Postgres session manager unavailable during get_module_data()."
            ).get_module_data(module, key)

        try:
            from sqlalchemy import select

            from ..chat.db.connection import get_db_session, get_engine
            from ..chat.db.schema import module_state

            if get_engine() is None:
                if self._fail_closed:
                    raise RuntimeError(
                        "Postgres session backend lost its database engine during get_module_data()."
                    )
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
            await self._raise_or_memory(
                "[SESSION] Postgres session manager unavailable during save_module_data()."
            ).save_module_data(module, key, data)
            return

        try:
            from sqlalchemy import func
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            from ..chat.db.connection import get_db_session, get_engine
            from ..chat.db.schema import module_state

            if get_engine() is None:
                if self._fail_closed:
                    raise RuntimeError(
                        "Postgres session backend lost its database engine during save_module_data()."
                    )
                await self._memory_fallback.save_module_data(module, key, data)
                return

            async with get_db_session() as session:
                stmt = pg_insert(module_state).values(
                    module=module,
                    state_key=key,
                    payload=data,
                ).on_conflict_do_update(
                    constraint="uq_module_state_module_key",
                    set_={"payload": data, "updated_at": func.now()},
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
            return await self._raise_or_memory(
                "[SESSION] Postgres session manager unavailable during delete_module_data()."
            ).delete_module_data(module, key)

        try:
            from sqlalchemy import delete

            from ..chat.db.connection import get_db_session, get_engine
            from ..chat.db.schema import module_state

            if get_engine() is None:
                if self._fail_closed:
                    raise RuntimeError(
                        "Postgres session backend lost its database engine during delete_module_data()."
                    )
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
            return await self._raise_or_memory(
                "[SESSION] Postgres session manager unavailable during list_module_keys()."
            ).list_module_keys(module)

        try:
            from sqlalchemy import select

            from ..chat.db.connection import get_db_session, get_engine
            from ..chat.db.schema import module_state

            if get_engine() is None:
                if self._fail_closed:
                    raise RuntimeError(
                        "Postgres session backend lost its database engine during list_module_keys()."
                    )
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


async def load_model(
    module: str,
    key: str,
    model_cls: type,
    store: SessionStore | None = None,
) -> Any | None:
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
    if store is None:
        store = get_session_store()
    await store.save_module_data(module, key, model.model_dump(mode="json"))


_store_instance: SessionStore | None = None
_store_lock = threading.Lock()


def _run_preflight_sync(store: PostgresSessionStore) -> None:
    """Run async postgres preflight from sync startup code.

    Uvicorn may import the app while an event loop is already running inside a
    worker process, so ``asyncio.run`` is not always legal here.
    """

    async def _preflight() -> None:
        await store.preflight()

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_preflight())
        return

    error: list[BaseException] = []

    def _runner() -> None:
        try:
            asyncio.run(_preflight())
        except BaseException as exc:  # pragma: no cover - thread handoff
            error.append(exc)

    thread = threading.Thread(
        target=_runner,
        name="mira-postgres-preflight",
        daemon=True,
    )
    thread.start()
    thread.join()
    if error:
        raise error[0]


def validate_session_backend_configuration() -> None:
    """Fail startup when production explicitly requires postgres but it is not ready."""

    backend = _normalized_env("MIRA_SESSION_BACKEND").lower()
    if backend != "postgres":
        return

    if not _has_usable_postgres_configuration():
        if _postgres_fail_closed():
            raise RuntimeError(
                "MIRA_SESSION_BACKEND=postgres but no usable PostgreSQL configuration is available."
            )
        return

    store = get_session_store()
    if not isinstance(store, PostgresSessionStore):
        raise RuntimeError("MIRA postgres session backend requested but store factory returned a different backend.")

    try:
        _run_preflight_sync(store)
    except RuntimeError:
        raise
    except Exception as exc:  # pragma: no cover - defensive wrapper
        raise RuntimeError("Postgres session backend failed startup preflight.") from exc


def get_session_store() -> SessionStore:
    """Return the singleton ``SessionStore`` chosen by environment."""

    global _store_instance
    if _store_instance is not None:
        return _store_instance

    with _store_lock:
        if _store_instance is not None:
            return _store_instance

        backend = _normalized_env("MIRA_SESSION_BACKEND").lower()
        if not backend:
            backend = "memory"

        if backend == "postgres" and not _has_usable_postgres_configuration():
            if _postgres_fail_closed():
                raise RuntimeError(
                    "Requested postgres session backend without usable credentials in a production-like environment."
                )
            logger.warning(
                "[SESSION] Requested postgres session backend without usable credentials; "
                "falling back to memory."
            )
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
    global _store_instance
    with _store_lock:
        _store_instance = None
