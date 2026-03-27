#!/usr/bin/env python3
"""
Module: Database Configuration
Purpose: Centralized PostgreSQL connection configuration with environment variable support.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-8739.8B, SWE-013, SWE-032
Safety Critical: True

IMPORTANT: This module is the SINGLE SOURCE OF TRUTH for database credentials.
All modules requiring PostgreSQL access SHOULD use get_db_config() from this module.

================================================================================
SECURITY NOTE: KNOWN RISK - DEVELOPMENT DEFAULTS
================================================================================
This module and others in the codebase use 'postgres/postgres' as development
defaults. This is a KNOWN SECURITY RISK that has been acknowledged:

- These defaults are ONLY for local development convenience
- Production deployments MUST use environment variables
- The team is aware this creates a security vulnerability if deployed as-is
- Future work: Implement proper secrets management (AWS Secrets Manager, Vault)
================================================================================

Environment Variables (USE THESE IN PRODUCTION):
    POSTGRES_HOST: Database host (default: localhost)
    POSTGRES_PORT: Database port (default: 5432)
    POSTGRES_DB: Database name (default: mira)
    POSTGRES_USER: Database user (default: postgres - CHANGE IN PRODUCTION)
    POSTGRES_PASSWORD: Database password (default: postgres - CHANGE IN PRODUCTION)
    MIRA_ENV: Environment mode ('development', 'staging', 'production')

In production (MIRA_ENV=production):
    - POSTGRES_USER and POSTGRES_PASSWORD SHOULD be set via environment
    - Will log warning if using defaults

In development (default):
    - Falls back to postgres/postgres if not set
    - Logs warning about insecure defaults
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "get_db_config",
    "get_db_connection_params",
    "open_db_connection",
    "DatabaseConfig",
    "require_production_credentials",
]


@dataclass(frozen=True)
class DatabaseConfig:
    """Immutable database configuration."""
    host: str
    port: int
    database: str
    user: str
    password: str
    options: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for psycopg2.connect(**config)."""
        params = {
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "user": self.user,
            "password": self.password,
        }
        if self.options:
            params["options"] = self.options
        return params

    def to_dsn(self) -> str:
        """Convert to PostgreSQL DSN string."""
        dsn = f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"
        if self.options:
            dsn += f"?options={self.options}"
        return dsn


# Singleton config instance
_config: Optional[DatabaseConfig] = None
_pool_lock = threading.Lock()
_connection_pools: dict[str, Any] = {}


def _pool_enabled() -> bool:
    raw = os.environ.get("MIRA_DB_POOL_ENABLED", "").strip().lower()
    if raw:
        return raw in {"1", "true", "yes", "on"}
    return True


class _PooledConnectionProxy:
    """Wrap a psycopg2 pooled connection so close() returns it to the pool."""

    def __init__(self, pool, conn):
        self._pool = pool
        self._conn = conn

    def __getattr__(self, name: str):
        return getattr(self._conn, name)

    def __enter__(self):
        self._conn.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            return self._conn.__exit__(exc_type, exc, tb)
        finally:
            self.close()

    def close(self) -> None:
        if self._conn is None:
            return
        conn = self._conn
        self._conn = None
        self._pool.putconn(conn)


def _pool_key(config: DatabaseConfig) -> str:
    return "|".join(
        [
            config.host,
            str(config.port),
            config.database,
            config.user,
            config.options or "",
        ]
    )


def _get_connection_pool(config: DatabaseConfig):
    from psycopg2.pool import ThreadedConnectionPool

    key = _pool_key(config)
    with _pool_lock:
        pool = _connection_pools.get(key)
        if pool is None:
            minconn = max(1, int(os.environ.get("MIRA_DB_POOL_MIN_CONNECTIONS", "1")))
            maxconn = max(minconn, int(os.environ.get("MIRA_DB_POOL_MAX_CONNECTIONS", "10")))
            pool = ThreadedConnectionPool(minconn, maxconn, **config.to_dict())
            _connection_pools[key] = pool
        return pool


def _get_environment() -> str:
    """Get current environment mode."""
    return os.environ.get("MIRA_ENV", "development").lower()


def _is_production() -> bool:
    """Check if running in production mode."""
    return _get_environment() == "production"


def require_production_credentials() -> None:
    """Validate that production credentials are set.

    Call this at application startup to fail fast if credentials are missing.

    Raises:
        RuntimeError: If MIRA_ENV=production and credentials not set
    """
    if not _is_production():
        return

    user = os.environ.get("POSTGRES_USER")
    password = os.environ.get("POSTGRES_PASSWORD")

    if not user or not password:
        raise RuntimeError(
            "PRODUCTION MODE REQUIRES CREDENTIALS:\n"
            "  - POSTGRES_USER environment variable must be set\n"
            "  - POSTGRES_PASSWORD environment variable must be set\n"
            "  Current MIRA_ENV: production\n"
            "\n"
            "Set these environment variables or use MIRA_ENV=development for local testing."
        )


def get_db_config(
    host: Optional[str] = None,
    port: Optional[int] = None,
    database: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    options: Optional[str] = None,
) -> DatabaseConfig:
    """Get database configuration from environment with optional overrides.

    Priority order:
    1. Explicit parameters passed to this function
    2. Environment variables (POSTGRES_HOST, POSTGRES_PORT, etc.)
    3. Secure defaults (localhost, 5432, mira)
    4. Development-only fallback for user/password (with warning)

    Args:
        host: Override for database host
        port: Override for database port
        database: Override for database name
        user: Override for database user
        password: Override for database password
        options: PostgreSQL connection options

    Returns:
        DatabaseConfig instance

    Raises:
        RuntimeError: If production mode and credentials missing
    """
    global _config

    # Check production requirements
    if _is_production():
        require_production_credentials()

    # Build config with priority: explicit > env var > default
    resolved_host = host or os.environ.get("POSTGRES_HOST", "localhost")
    resolved_port = port or int(os.environ.get("POSTGRES_PORT", "5432"))
    resolved_db = database or os.environ.get("POSTGRES_DB", "mira")

    # User and password handling
    resolved_user = user or os.environ.get("POSTGRES_USER")
    resolved_password = password or os.environ.get("POSTGRES_PASSWORD")

    # Development fallback (only if not production)
    if not resolved_user:
        if _is_production():
            raise RuntimeError("POSTGRES_USER required in production")
        resolved_user = "postgres"
        logger.warning(
            "[DB_CONFIG] Using development default user 'postgres'. "
            "Set POSTGRES_USER for production."
        )

    if not resolved_password:
        if _is_production():
            raise RuntimeError("POSTGRES_PASSWORD required in production")
        resolved_password = "postgres"
        logger.warning(
            "[DB_CONFIG] Using development default password. "
            "Set POSTGRES_PASSWORD for production."
        )

    return DatabaseConfig(
        host=resolved_host,
        port=resolved_port,
        database=resolved_db,
        user=resolved_user,
        password=resolved_password,
        options=options,
    )


def get_db_connection_params(
    host: Optional[str] = None,
    port: Optional[int] = None,
    database: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    options: Optional[str] = None,
) -> Dict[str, Any]:
    """Get database connection parameters as a dict for psycopg2.connect().

    Convenience wrapper around get_db_config().to_dict().

    Example:
        import psycopg2
        from mira.core.db_config import get_db_connection_params

        conn = psycopg2.connect(**get_db_connection_params())
    """
    config = get_db_config(host, port, database, user, password, options)
    return config.to_dict()


def _default_statement_timeout_ms() -> int:
    """Return the default per-statement timeout in milliseconds.

    Configurable via ``MIRA_DB_STATEMENT_TIMEOUT_MS`` (default 30 000 ms).
    Set to ``0`` to disable.
    """
    return int(os.environ.get("MIRA_DB_STATEMENT_TIMEOUT_MS", "30000"))


def open_db_connection(
    host: Optional[str] = None,
    port: Optional[int] = None,
    database: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    options: Optional[str] = None,
    connect_timeout: Optional[int] = None,
):
    """Open a psycopg2 connection, using a shared pool when available."""
    import psycopg2

    config = get_db_config(host, port, database, user, password, options)
    params = config.to_dict()
    if connect_timeout is not None:
        params["connect_timeout"] = connect_timeout

    # Apply statement_timeout to prevent runaway queries
    stmt_timeout = _default_statement_timeout_ms()
    if stmt_timeout > 0:
        existing = params.get("options", "")
        timeout_opt = f"-c statement_timeout={stmt_timeout}"
        params["options"] = f"{existing} {timeout_opt}".strip() if existing else timeout_opt

    if not _pool_enabled():
        return psycopg2.connect(**params)

    try:
        pool = _get_connection_pool(config)
        return _PooledConnectionProxy(pool, pool.getconn())
    except Exception as exc:
        logger.warning("[DB_CONFIG] Falling back to direct connection: %s", exc)
        return psycopg2.connect(**params)


# Validation at module load time (optional - can be called explicitly)
def _validate_on_import():
    """Log configuration status on import."""
    env = _get_environment()
    logger.info(f"[DB_CONFIG] Environment: {env}")

    if _is_production():
        try:
            require_production_credentials()
            logger.info("[DB_CONFIG] Production credentials validated")
        except RuntimeError as e:
            logger.error(f"[DB_CONFIG] {e}")
            # Don't raise here - let it fail when actually used


# Run validation when module is imported (unless suppressed)
if os.environ.get("MIRA_SKIP_DB_VALIDATION") != "1":
    _validate_on_import()
