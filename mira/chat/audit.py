"""
Module: MIRA Chat — Audit Writer
Purpose: Phase 1 JSONL audit trail per BS-SPEC-MIRA-CHAT-001-REV2 Section 10.1.

Every engine invocation produces an AuditRecord that is appended to a
JSON-lines file for traceability and compliance review. Thread-safe via
a module-level lock.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from .models import AuditRecord

LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Default path relative to project root; override with MIRA_CHAT_AUDIT_PATH.
_DEFAULT_AUDIT_LOG_PATH = "data/chat_audit.jsonl"

_write_lock = threading.Lock()

# Sequence counter for audit ID generation (resets each process lifetime).
_sequence_counter = 0
_sequence_lock = threading.Lock()


def _audit_log_path() -> Path:
    """Resolve the audit log file path, allowing env-var override."""
    configured = os.environ.get("MIRA_CHAT_AUDIT_PATH", "").strip()
    if configured:
        return Path(configured)
    # Resolve relative to the project root (two levels above mira/chat/)
    project_root = Path(__file__).resolve().parents[2]
    return project_root / _DEFAULT_AUDIT_LOG_PATH


# ---------------------------------------------------------------------------
# Audit ID generation
# ---------------------------------------------------------------------------


def generate_audit_id() -> str:
    """Generate a sequential audit ID in the format ``CHAT-YYYY-MMDD-NNN``.

    The sequence counter is process-scoped and monotonically increasing.
    It resets when the process restarts, which is acceptable for Phase 1
    since the JSONL file provides a durable ordered record.
    """
    global _sequence_counter
    with _sequence_lock:
        _sequence_counter += 1
        seq = _sequence_counter

    now = datetime.now(timezone.utc)
    date_part = now.strftime("%Y-%m%d")
    return f"CHAT-{date_part}-{seq:03d}"


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def write_audit_record(record: AuditRecord) -> None:
    """Append an AuditRecord as a single JSON line to the audit log.

    Creates the parent directory and file if they do not exist.
    Thread-safe: concurrent calls are serialised via a module-level lock.
    """
    path = _audit_log_path()

    try:
        # Ensure parent directory exists
        path.parent.mkdir(parents=True, exist_ok=True)

        # Serialise — Pydantic v2 .model_dump() with ISO timestamps
        payload = record.model_dump(mode="json")
        line = json.dumps(payload, default=str, separators=(",", ":"))

        with _write_lock:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")

        LOGGER.debug("Audit record written: %s -> %s", record.audit_id, path)

    except Exception:
        # Audit failures must never crash the request pipeline.
        LOGGER.exception("Failed to write audit record %s", record.audit_id)
