"""
Module: MIRA Chat — PostgreSQL Audit Writer
Purpose: Replaces the Phase 1 JSONL file writer with durable PostgreSQL
         storage for audit records per BS-SPEC-MIRA-CHAT-001-REV2 Section 10.1.

Falls back to the JSONL file writer if the database is unavailable.
Audit failures never crash the request pipeline — all writes are
wrapped in try/except with logged warnings.

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
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select

from ..models import AuditRecord, Status, TaskMode
from .connection import get_db_session, get_engine
from .schema import chat_audit

logger = logging.getLogger(__name__)

# Default retention per spec
_DEFAULT_RETENTION_MONTHS = 24


def _audit_record_to_row(record: AuditRecord) -> dict[str, Any]:
    """Convert an AuditRecord Pydantic model to a dict for INSERT."""
    return {
        "audit_id": record.audit_id,
        "timestamp": record.timestamp,
        "session_id": record.session_id or None,
        "user_input": record.user_input,
        "parsed_entities": record.parsed_entities or None,
        "normalized_units": record.normalized_units or None,
        "coarse_intent": record.coarse_intent or None,
        "fine_routing": record.fine_routing or None,
        "task_mode": record.task_mode.value if record.task_mode else None,
        "routing_confidence": record.routing_confidence,
        "engines_invoked": record.engines_invoked or None,
        "engine_versions": record.engine_versions or None,
        "engine_status": record.engine_status.value if record.engine_status else None,
        "source_citations": record.source_citations or None,
        "assumptions": record.assumptions or None,
        "missing_inputs": record.missing_inputs or None,
        "llm_model_used": record.llm_model_used,
        "response_hash": record.response_hash or None,
        "artifact_generated": record.artifact_generated,
        "follow_ups_offered": record.follow_ups_offered or None,
        "follow_ups_taken": record.follow_ups_taken or None,
        "module_context": record.module_context,
        "authority_basis": record.authority_basis or None,
        "envelope_json": record.envelope_json or None,
        "error_detail": record.error_detail,
    }


def _row_to_audit_record(row: dict[str, Any]) -> AuditRecord:
    """Reconstruct an AuditRecord from a database row mapping."""
    engine_status_raw = row.get("engine_status")
    try:
        engine_status = Status(engine_status_raw) if engine_status_raw else Status.ERROR
    except ValueError:
        engine_status = Status.ERROR

    task_mode_raw = row.get("task_mode")
    try:
        task_mode = TaskMode(task_mode_raw) if task_mode_raw else TaskMode.ANSWER_ONLY
    except ValueError:
        task_mode = TaskMode.ANSWER_ONLY

    return AuditRecord(
        audit_id=row["audit_id"],
        timestamp=row["timestamp"],
        session_id=row.get("session_id") or "",
        user_input=row["user_input"],
        parsed_entities=row.get("parsed_entities") or {},
        normalized_units=row.get("normalized_units") or {},
        coarse_intent=row.get("coarse_intent") or "",
        fine_routing=row.get("fine_routing") or "",
        task_mode=task_mode,
        routing_confidence=row.get("routing_confidence") or 0.0,
        engines_invoked=list(row.get("engines_invoked") or []),
        engine_versions=dict(row.get("engine_versions") or {}),
        engine_status=engine_status,
        source_citations=list(row.get("source_citations") or []),
        assumptions=list(row.get("assumptions") or []),
        missing_inputs=list(row.get("missing_inputs") or []),
        llm_model_used=row.get("llm_model_used"),
        response_hash=row.get("response_hash") or "",
        artifact_generated=row.get("artifact_generated", False),
        follow_ups_offered=list(row.get("follow_ups_offered") or []),
        follow_ups_taken=list(row.get("follow_ups_taken") or []),
        module_context=row.get("module_context"),
        authority_basis=list(row.get("authority_basis") or []),
        envelope_json=dict(row.get("envelope_json") or {}),
        error_detail=row.get("error_detail"),
    )


class AuditWriter:
    """PostgreSQL audit writer.

    Falls back to JSONL file if database is unavailable.
    Audit failures never crash the request pipeline.
    """

    def __init__(self) -> None:
        # Lazy import so the JSONL fallback only loads if needed
        self._jsonl_fallback = None

    @property
    def _db_available(self) -> bool:
        return get_engine() is not None

    def _get_jsonl_writer(self):
        """Lazy-load the Phase 1 JSONL writer for fallback."""
        if self._jsonl_fallback is None:
            from ..audit import write_audit_record
            self._jsonl_fallback = write_audit_record
        return self._jsonl_fallback

    # ------------------------------------------------------------------
    # write
    # ------------------------------------------------------------------

    async def write(self, record: AuditRecord) -> None:
        """Write an audit record to PostgreSQL, or JSONL as fallback.

        Never raises — all errors are logged and swallowed.
        """
        if not self._db_available:
            self._write_jsonl_fallback(record)
            return

        try:
            row_data = _audit_record_to_row(record)
            async with get_db_session() as session:
                await session.execute(chat_audit.insert().values(**row_data))
            logger.debug("[AUDIT] Written to DB: %s", record.audit_id)

        except Exception:
            logger.exception(
                "[AUDIT] DB write failed for %s, falling back to JSONL",
                record.audit_id,
            )
            self._write_jsonl_fallback(record)

    def _write_jsonl_fallback(self, record: AuditRecord) -> None:
        """Write to JSONL file (Phase 1 behavior)."""
        try:
            writer = self._get_jsonl_writer()
            writer(record)
        except Exception:
            logger.exception("[AUDIT] JSONL fallback also failed for %s", record.audit_id)

    # ------------------------------------------------------------------
    # get_by_session
    # ------------------------------------------------------------------

    async def get_by_session(self, session_id: str) -> list[AuditRecord]:
        """Retrieve all audit records for a given session, ordered by time."""
        if not self._db_available:
            logger.warning("[AUDIT] get_by_session called without DB — returning empty list")
            return []

        try:
            async with get_db_session() as session:
                rows = (
                    await session.execute(
                        select(chat_audit)
                        .where(chat_audit.c.session_id == session_id)
                        .order_by(chat_audit.c.timestamp.asc())
                    )
                ).mappings().all()

            return [_row_to_audit_record(dict(row)) for row in rows]

        except Exception:
            logger.exception("[AUDIT] get_by_session failed for %s", session_id)
            return []

    # ------------------------------------------------------------------
    # get_by_audit_id
    # ------------------------------------------------------------------

    async def get_by_audit_id(self, audit_id: str) -> AuditRecord | None:
        """Retrieve a single audit record by its unique audit_id."""
        if not self._db_available:
            logger.warning("[AUDIT] get_by_audit_id called without DB — returning None")
            return None

        try:
            async with get_db_session() as session:
                row = (
                    await session.execute(
                        select(chat_audit).where(chat_audit.c.audit_id == audit_id)
                    )
                ).mappings().first()

            if row is None:
                return None

            return _row_to_audit_record(dict(row))

        except Exception:
            logger.exception("[AUDIT] get_by_audit_id failed for %s", audit_id)
            return None

    # ------------------------------------------------------------------
    # purge_before
    # ------------------------------------------------------------------

    async def purge_before(
        self,
        cutoff: datetime | None = None,
    ) -> int:
        """Delete audit records older than *cutoff*.

        If *cutoff* is not provided, defaults to 24 months ago per spec.

        Returns the number of records deleted.
        """
        if cutoff is None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=_DEFAULT_RETENTION_MONTHS * 30)

        if not self._db_available:
            logger.warning("[AUDIT] purge_before called without DB — no-op")
            return 0

        try:
            async with get_db_session() as session:
                result = await session.execute(
                    delete(chat_audit).where(chat_audit.c.timestamp < cutoff)
                )
                deleted = result.rowcount
                logger.info(
                    "[AUDIT] Purged %d audit records older than %s",
                    deleted,
                    cutoff.isoformat(),
                )
                return deleted

        except Exception:
            logger.exception("[AUDIT] purge_before failed")
            return 0
