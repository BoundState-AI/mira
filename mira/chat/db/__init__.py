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

from .audit_writer import AuditWriter
from .connection import get_db_session, get_engine, init_db, shutdown_db
from .migrations import run_migrations
from .session_manager import SessionManager

__all__ = [
    "AuditWriter",
    "SessionManager",
    "get_db_session",
    "get_engine",
    "init_db",
    "shutdown_db",
    "run_migrations",
]
