"""
MIRA Chat — PostgreSQL Persistence Layer (Phase 2)

Replaces Phase 1 in-memory session store and JSONL audit file with
durable PostgreSQL-backed storage.  Falls back to in-memory behavior
when the database is unavailable so development/CI can run without
a database instance.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-032, NASA-STD-8739.8B
Safety Critical: True
Deployment: AWS GovCloud West (FedRAMP High, ITAR)
"""


def __getattr__(name: str):
    """Lazy imports — avoid pulling in sqlalchemy at package init time.

    This allows ``from .db.router_integration import ...`` in the chat
    router without requiring sqlalchemy to be installed (it is only
    needed when the PostgreSQL backend is actually used).
    """
    if name == "AuditWriter":
        from .audit_writer import AuditWriter
        return AuditWriter
    if name == "SessionManager":
        from .session_manager import SessionManager
        return SessionManager
    if name in ("get_db_session", "get_engine", "init_db", "shutdown_db"):
        from . import connection
        return getattr(connection, name)
    if name == "run_migrations":
        from .migrations import run_migrations
        return run_migrations
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AuditWriter",
    "SessionManager",
    "get_db_session",
    "get_engine",
    "init_db",
    "shutdown_db",
    "run_migrations",
]
