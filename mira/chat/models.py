"""
Module: MIRA Chat — Shared Data Models
Purpose: Pydantic models for the unified MIRA Chat interface per BS-SPEC-MIRA-CHAT-001-REV2.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class Status(str, Enum):
    """Disposition status returned by any engine."""

    PASS = "PASS"
    CONDITIONAL_PASS = "CONDITIONAL_PASS"
    FAIL = "FAIL"
    REFUSE = "REFUSE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    ERROR = "ERROR"


class TaskMode(str, Enum):
    """What kind of work the engine performed."""

    ANSWER_ONLY = "answer_only"
    DRAFT_ARTIFACT = "draft_artifact"
    REVIEW_EXISTING = "review_existing"


class SideEffectLevel(str, Enum):
    """Describes the persistence level of engine side-effects."""

    READ_ONLY = "read_only"
    TRANSIENT_GENERATE = "transient_generate"
    PERSISTED_DRAFT = "persisted_draft"
    WORKFLOW_SUBMIT = "workflow_submit"


# ---------------------------------------------------------------------------
# Chat-layer request / response models
# ---------------------------------------------------------------------------


class ChatMessage(BaseModel):
    """A single message in the conversation history."""

    role: str = Field(description="'user' or 'assistant'")
    content: str
    engine_used: Optional[str] = None
    entities: dict[str, Any] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    """Inbound chat request from the frontend."""

    message: str = Field(min_length=1)
    session_id: Optional[str] = None
    history: list[ChatMessage] = Field(
        default_factory=list,
        max_length=10,
        description="Last 5 turns (up to 10 messages), capped by the backend.",
    )
    module_context: Optional[dict[str, Any]] = Field(
        default=None,
        description="Optional module context from the frontend (module, case_id, material, etc.).",
    )


class ChatResponse(BaseModel):
    """Outbound response sent to the frontend."""

    response: str
    session_id: str
    engine_used: Optional[str] = None
    verdict: Optional[str] = None
    audit_id: Optional[str] = None
    follow_up_suggestions: list[str] = Field(default_factory=list)
    mode: Optional[TaskMode] = None
    entities: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Extracted/resolved entities for this turn. The frontend MUST echo "
            "these back in the next ChatMessage so multi-turn entity resolution works."
        ),
    )


# ---------------------------------------------------------------------------
# Engine envelope — the normalized contract every adapter must produce
# ---------------------------------------------------------------------------


class EngineEnvelope(BaseModel):
    """
    Normalized response envelope returned by every EngineAdapter.

    All engines — OCA, H2, Galvanic, MUA — MUST produce this structure so
    the chat orchestrator can render a consistent UX regardless of which
    domain engine answered the query.
    """

    status: Status
    engine_id: str
    engine_version: str = "1.0.0"
    mode: TaskMode = TaskMode.ANSWER_ONLY
    response_text: str = ""

    # Authority & provenance
    authority_basis: list[str] = Field(
        default_factory=list,
        description="Standards / specs that underpin the answer (e.g. NASA-STD-6001B).",
    )
    citations: list[str] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Serialised evidence cards or summaries.",
    )
    assumptions: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)

    # Actionable outputs
    recommended_actions: list[str] = Field(default_factory=list)
    mua_disposition: Optional[str] = Field(
        default=None,
        description="OCA-specific: final disposition value when applicable.",
    )

    # Audit lineage
    audit_lineage: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Engine-internal trace events for the audit record.",
    )

    # Opaque payload for domain-specific extras
    domain_payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Engine-specific data the frontend may need (e.g. case_id).",
    )


# ---------------------------------------------------------------------------
# Audit record — written after every engine execution
# ---------------------------------------------------------------------------


class AuditRecord(BaseModel):
    """
    Full audit record per BS-SPEC-MIRA-CHAT-001-REV2 Section 10.1.

    Every engine invocation produces one of these; they are stored for
    traceability and compliance review.
    """

    audit_id: str = Field(default_factory=lambda: f"aud-{uuid4().hex[:12]}")
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    session_id: str = ""
    user_input: str = ""
    parsed_entities: dict[str, Any] = Field(default_factory=dict)
    normalized_units: dict[str, str] = Field(default_factory=dict)
    coarse_intent: str = ""
    fine_routing: str = ""
    task_mode: TaskMode = TaskMode.ANSWER_ONLY
    routing_confidence: float = 0.0
    engines_invoked: list[str] = Field(default_factory=list)
    engine_versions: dict[str, str] = Field(default_factory=dict)
    engine_status: Status = Status.ERROR
    source_citations: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    llm_model_used: Optional[str] = None
    response_hash: str = ""
    artifact_generated: bool = False
    follow_ups_offered: list[str] = Field(default_factory=list)
    follow_ups_taken: list[str] = Field(default_factory=list)
    module_context: Optional[dict[str, Any]] = None
    authority_basis: list[str] = Field(default_factory=list)
    envelope_json: dict[str, Any] = Field(default_factory=dict)
    error_detail: Optional[str] = None
