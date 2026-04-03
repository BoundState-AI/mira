"""
Module: MIRA Chat — SQLAlchemy Table Definitions
Purpose: PostgreSQL schema for chat sessions, turns, and audit records
         per BS-SPEC-MIRA-CHAT-001-REV2.

Three tables:
  chat_sessions  — session lifecycle and accumulated state
  chat_turns     — full conversation history (one row per exchange)
  chat_audit     — engineering audit record (Section 10.1)
  module_state   — generic module payloads keyed by module + id

Retention: 24 months per spec.  The ``purge_before`` utilities in
SessionManager and AuditWriter honour this default.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-032, NASA-STD-8739.8B
Safety Critical: True
Deployment: AWS GovCloud West (FedRAMP High, ITAR)
"""

from __future__ import annotations

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

# All chat tables share a dedicated metadata instance so they can be
# created / dropped independently of the rest of the MIRA schema.
metadata = MetaData(schema="public")

# ---------------------------------------------------------------------------
# chat_sessions
# ---------------------------------------------------------------------------

chat_sessions = Table(
    "chat_sessions",
    metadata,
    Column("session_id", String(64), primary_key=True),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    ),
    Column(
        "last_active",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    ),
    Column("module_context", JSONB, nullable=True),
    Column(
        "engine_context",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    ),
    Column(
        "accumulated_entities",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    ),
    Column("turn_count", Integer, nullable=False, server_default=text("0")),
    Column("last_assessment", JSONB, nullable=True),
)

# ---------------------------------------------------------------------------
# chat_turns
# ---------------------------------------------------------------------------

chat_turns = Table(
    "chat_turns",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "session_id",
        String(64),
        ForeignKey("public.chat_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("turn_number", Integer, nullable=False),
    Column("user_message", Text, nullable=False),
    Column("assistant_message", Text, nullable=False),
    Column("engine_used", String(64), nullable=True),
    Column("entities", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("envelope_json", JSONB, nullable=True),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    ),
    # Composite index for efficient history retrieval
    Index("ix_chat_turns_session_turn", "session_id", "turn_number"),
)

# ---------------------------------------------------------------------------
# module_state
# ---------------------------------------------------------------------------

module_state = Table(
    "module_state",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("module", String(64), nullable=False),
    Column("state_key", String(128), nullable=False),
    Column("payload", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    ),
    UniqueConstraint("module", "state_key", name="uq_module_state_module_key"),
    Index("ix_module_state_module", "module"),
    Index("ix_module_state_module_key", "module", "state_key"),
)

# ---------------------------------------------------------------------------
# chat_audit
# ---------------------------------------------------------------------------

chat_audit = Table(
    "chat_audit",
    metadata,
    Column("audit_id", String(32), primary_key=True),
    Column("timestamp", DateTime(timezone=True), nullable=False),
    Column(
        "session_id",
        String(64),
        ForeignKey("public.chat_sessions.session_id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("user_input", Text, nullable=False),
    Column("parsed_entities", JSONB, nullable=True),
    Column("normalized_units", JSONB, nullable=True),
    Column("coarse_intent", String(64), nullable=True),
    Column("fine_routing", String(64), nullable=True),
    Column("task_mode", String(32), nullable=True),
    Column("routing_confidence", Float, nullable=True),
    Column("engines_invoked", ARRAY(String(64)), nullable=True),
    Column("engine_versions", JSONB, nullable=True),
    Column("engine_status", String(32), nullable=True),
    Column("source_citations", ARRAY(Text), nullable=True),
    Column("assumptions", ARRAY(Text), nullable=True),
    Column("missing_inputs", ARRAY(Text), nullable=True),
    Column("llm_model_used", String(128), nullable=True),
    Column("response_hash", String(128), nullable=True),
    Column("artifact_generated", Boolean, nullable=False, server_default=text("false")),
    Column("follow_ups_offered", ARRAY(Text), nullable=True),
    Column("follow_ups_taken", ARRAY(Text), nullable=True),
    Column("module_context", JSONB, nullable=True),
    Column("authority_basis", ARRAY(Text), nullable=True),
    Column("envelope_json", JSONB, nullable=True),
    Column("error_detail", Text, nullable=True),
    # Index for session-based lookups
    Index("ix_chat_audit_session_id", "session_id"),
    # Index for time-based purge queries
    Index("ix_chat_audit_timestamp", "timestamp"),
)
