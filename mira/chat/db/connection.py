"""
Module: MIRA Chat — Database Connection Management
Purpose: Async SQLAlchemy 2.0 engine and session factory for the chat
         PostgreSQL layer.

Connection string comes from ``MIRA_CHAT_DATABASE_URL`` env var.  When
not set, the module logs a warning and ``get_engine()`` returns None,
signalling all consumers to fall back to in-memory Phase 1 behavior.

For AWS GovCloud / RDS deployments the URL should use the asyncpg driver::

    MIRA_CHAT_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/mira

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
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = logging.getLogger(__name__)

_PLACEHOLDER_VALUES = {"", "restored", "placeholder", "changeme", "none", "null", "undefined"}
_LOCALHOST_VALUES = {"localhost", "127.0.0.1", "::1"}

# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_initialized: bool = False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _resolve_database_url() -> str | None:
    """Resolve the database URL from environment.

    Priority:
      1. ``MIRA_CHAT_DATABASE_URL`` (chat-specific, preferred)
      2. Build from ``mira.core.db_config`` components with asyncpg driver

    Returns None if no database is configured.
    """
    session_backend = os.environ.get("MIRA_SESSION_BACKEND", "").strip().lower()
    if session_backend == "memory":
        logger.info("[CHAT-DB] Session backend pinned to memory; chat database disabled.")
        return None

    # Primary: dedicated chat database URL
    url = os.environ.get("MIRA_CHAT_DATABASE_URL", "").strip()
    if url:
        # Ensure asyncpg driver prefix
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url

    # Secondary: build from standard MIRA env vars only when postgres mode is active.
    if session_backend != "postgres":
        return None

    pg_host = os.environ.get("POSTGRES_HOST", "").strip()
    pg_pass = os.environ.get("POSTGRES_PASSWORD", "").strip()
    if not pg_host or pg_host.lower() in _PLACEHOLDER_VALUES | _LOCALHOST_VALUES:
        logger.warning("[CHAT-DB] Postgres backend requested without a usable host; falling back to memory.")
        return None
    if not pg_pass or pg_pass.lower() in _PLACEHOLDER_VALUES:
        logger.warning(
            "[CHAT-DB] Postgres backend requested without a usable password; falling back to memory."
        )
        return None

    pg_port = os.environ.get("POSTGRES_PORT", "5432")
    pg_db = os.environ.get("POSTGRES_DB", "mira")
    pg_user = os.environ.get("POSTGRES_USER", "postgres")
    return f"postgresql+asyncpg://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}"

    return None


async def init_db() -> AsyncEngine | None:
    """Initialize the async engine and session factory.

    Safe to call multiple times — only initializes once.
    Returns the engine, or None if no database URL is configured.
    """
    global _engine, _session_factory, _initialized

    if _initialized:
        return _engine

    _initialized = True

    url = _resolve_database_url()
    if url is None:
        logger.warning(
            "[CHAT-DB] No database URL configured (MIRA_CHAT_DATABASE_URL not set). "
            "Chat will use in-memory session store (Phase 1 fallback)."
        )
        return None

    # Mask password for logging
    safe_url = url
    try:
        at_idx = url.index("@")
        proto_end = url.index("://") + 3
        safe_url = url[:proto_end] + "***@" + url[at_idx + 1 :]
    except ValueError:
        pass

    logger.info("[CHAT-DB] Initializing async engine: %s", safe_url)

    _engine = create_async_engine(
        url,
        # Connection pool tuning for RDS
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=1800,  # Recycle connections every 30 min
        echo=os.environ.get("MIRA_CHAT_DB_ECHO", "").lower() in ("1", "true"),
    )

    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    logger.info("[CHAT-DB] Engine initialized successfully.")
    return _engine


async def shutdown_db() -> None:
    """Dispose of the engine and release all pooled connections."""
    global _engine, _session_factory, _initialized

    if _engine is not None:
        logger.info("[CHAT-DB] Disposing async engine.")
        await _engine.dispose()

    _engine = None
    _session_factory = None
    _initialized = False


def get_engine() -> AsyncEngine | None:
    """Return the current engine (None if not initialized or no DB configured)."""
    return _engine


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session for dependency injection.

    Usage in FastAPI::

        async with get_db_session() as session:
            result = await session.execute(select(...))

    Raises RuntimeError if the database was not initialized.
    """
    if _session_factory is None:
        raise RuntimeError(
            "Chat database not initialized. Call init_db() at startup, "
            "or set MIRA_CHAT_DATABASE_URL."
        )

    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
