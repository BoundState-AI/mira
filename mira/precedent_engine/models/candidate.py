#!/usr/bin/env python3
"""
Module: Candidate
Purpose: [Automatically migrated - needs manual review]

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-033, NASA-STD-6016, NASA-STD-8739.8B
Safety Critical: True
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from mira.precedent_engine.models.enums import (
    DeviationType,
    LLMContribution,
    PrecedentAdequacyLevel,
)
from mira.precedent_engine.models.precedent import (
    PrecedentRetrievalResult,
    PrecedentStatistics,
)


class RationaleSegment(BaseModel):
    """
    A single rationale segment with provenance.

    Every piece of rationale text must trace to its source precedent(s)
    and indicate how the LLM contributed to its synthesis.
    """

    model_config = {"extra": "forbid"}

    deviation_type: DeviationType
    text: str
    source_mua_ids: list[str] = Field(min_length=1)
    contribution_type: LLMContribution
    has_gap: bool = False
    gap_description: str | None = None


class CandidateMUA(BaseModel):
    """
    Complete draft MUA with full provenance.

    CRITICAL NOTES:
    - determination is NEVER auto-populated. Human decision required.
    - suggested_routing_category is a ROUTING HINT, not a compliance decision.
      The final category assignment is made by the approving engineer per
      NASA-STD-6016 requirements.

    This is a draft for human review, not an approval.
    """

    model_config = {"extra": "forbid"}

    # Identity
    mua_number: str  # e.g., "AUTO-PRECEDENT-SS316L-2025-001"

    # Material
    material_name: str
    material_key: str | None = None
    specification: str | None = None
    manufacturer: str | None = None
    trade_name: str | None = None

    # Application
    component: str | None = None
    application_description: str | None = None

    # Environment
    environment_envelope: str  # Human-readable summary
    media: str | None = None
    o2_pct: float = 21.0
    location_class: Literal["habitable", "non_habitable"] = "non_habitable"
    temp_max_f: float | None = None
    temp_min_f: float | None = None
    pressure_max_psia: float | None = None

    # Category routing (per Addendum C - renamed for clarity)
    suggested_routing_category: Literal["I", "II", "III"] | None = None
    routing_category_reasoning: str | None = None

    # Rationale (from narrator LLM)
    rationales: list[RationaleSegment] = Field(default_factory=list)
    combined_rationale_text: str | None = None

    # CRITICAL: Never auto-populated
    determination: None = None  # Always None - human decision required

    # Precedent summary
    precedent_adequacy: PrecedentAdequacyLevel
    precedent_summary: str  # "147 prior flights; 0 rejections"
    precedent_mua_ids: list[str] = Field(default_factory=list)
    base_mua_id: str | None = None
    base_mua_similarity: float | None = Field(default=None, ge=0.0, le=1.0)

    # Statistics for reviewer
    statistics: PrecedentStatistics | None = None

    # Audit trail
    retrieval_result: PrecedentRetrievalResult | None = None
    synthesis_timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Warnings and flags
    warnings: list[str] = Field(default_factory=list)
    requires_manual_justification: bool = False
    conflicts_detected: list[str] = Field(default_factory=list)


class EngineResult(BaseModel):
    """
    Top-level engine output.

    This is the final result from MUAPrecedentRunner.process_case().
    Status indicates the outcome:
    - "candidate": Draft MUA generated successfully
    - "escalate": Precedent inadequate, manual justification required
    - "error": Processing error occurred
    """

    model_config = {"extra": "forbid"}

    status: Literal["candidate", "escalate", "error"]
    candidate_mua: CandidateMUA | None = None
    reason: str | None = None
    retrieval_result: PrecedentRetrievalResult | None = None

    # Original input for traceability
    query_material: str | None = None
    query_environment: str | None = None


# Rebuild models to resolve forward references
CandidateMUA.model_rebuild()
EngineResult.model_rebuild()
