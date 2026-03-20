"""
Module: MIRA Chat — Migration Runner
Purpose: Create chat tables if they do not exist.  Uses raw DDL via
         ``CREATE TABLE IF NOT EXISTS`` for Phase 2 simplicity.
         Alembic can be layered on in Phase 3 if needed.

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

from sqlalchemy.ext.asyncio import AsyncEngine

from .schema import metadata

logger = logging.getLogger(__name__)


async def run_migrations(engine: AsyncEngine) -> None:
    """Create all chat tables if they do not already exist.

    Uses SQLAlchemy's ``metadata.create_all`` with ``checkfirst=True``
    (the default), so this is safe to call on every startup.

    Parameters
    ----------
    engine:
        The async engine returned by ``init_db()``.
    """
    logger.info("[CHAT-DB] Running migrations (CREATE TABLE IF NOT EXISTS)...")

    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)

    logger.info(
        "[CHAT-DB] Migration complete.  Tables: %s",
        ", ".join(sorted(t.name for t in metadata.sorted_tables)),
    )
