#!/usr/bin/env python3
"""
Module: Precedent
Purpose: [Automatically migrated - needs manual review]

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-033, NASA-STD-6016
Safety Critical: True
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from mira.precedent_engine.models.enums import (
    DeviationType,
    PrecedentAdequacyLevel,
    ProgramFamily,
)


class PrecedentMatch(BaseModel):
    """
    A single precedent MUA matched to a query, with tier and score.

    Created by PrecedentEngine from EnrichedMUA candidates.

    IMPORTANT: The similarity_score is computed DETERMINISTICALLY by
    PrecedentEngine. Vector similarity from Qdrant/FAISS is DISCARDED
    after candidate retrieval.
    """

    model_config = {"extra": "forbid", "frozen": True}

    # Identity
    contract_id: str
    material_name: str
    material_key: str | None = None

    # Tier and score (computed by engine)
    tier: Literal[1, 2, 3]
    similarity_score: float = Field(ge=0.0, le=1.0)

    # Equivalence breakdown (for explainability)
    material_equivalent: bool
    environment_equivalent: bool
    deviation_equivalent: bool
    program_weight: float = Field(ge=0.0, le=1.0)

    # Environment envelope
    media: str | None = None
    o2_pct: float = 21.0
    location_class: Literal["habitable", "non_habitable"] = "non_habitable"
    temp_max_f: float | None = None
    temp_min_f: float | None = None
    pressure_max_psia: float | None = None

    # Status
    is_rejected: bool = False
    is_superseded: bool = False
    superseded_by: str | None = None

    # Content available
    available_rationale_types: list[DeviationType] = Field(default_factory=list)
    rationale_text: str | None = None

    # Metadata
    source_program: str | None = None
    source_program_family: ProgramFamily = ProgramFamily.OTHER
    approval_date: date | None = None
    category: Literal["I", "II", "III"] | None = None

    # Environment delta for reviewer
    environment_delta_summary: str | None = None

    # Clustering
    precedent_family: int | None = None


class PrecedentStatistics(BaseModel):
    """
    Statistical summary of precedent corpus for this query.

    This provides the "147 flights, 0 rejections" data that supports
    engineering decisions. All statistics are computed DETERMINISTICALLY
    by PrecedentEngine - no LLM involvement.
    """

    model_config = {"extra": "forbid", "frozen": True}

    n_total_with_material: int = 0  # All MUAs with same material_key
    n_similar_environment: int = 0  # Within environment tolerance
    n_same_deviation: int = 0  # Same deviation types
    n_approved: int = 0
    n_rejected: int = 0
    n_deferred: int = 0

    # Derived
    approval_rate: float = 0.0  # n_approved / n_total
    rejection_rate_upper_bound: float = 1.0  # 95% CI upper bound


class PrecedentRetrievalResult(BaseModel):
    """
    Full result from precedent retrieval.

    This is the primary output of PrecedentEngine.evaluate_candidates().
    It contains the complete analysis needed for adequacy gating and
    downstream rationale synthesis.

    IMPORTANT: Vector similarity is used ONLY to generate the candidate pool.
    It does not contribute directly to tier assignment, equivalence checking,
    or adequacy scoring. The vector score from Qdrant/FAISS is DISCARDED
    after candidate retrieval.
    """

    model_config = {"extra": "forbid"}

    # Query info
    query_material_key: str | None = None
    query_material_name: str
    query_environment_summary: str

    # Statistics (the "147 flights, 0 rejections" data)
    statistics: PrecedentStatistics

    # Counts by tier
    n_total_candidates: int = Field(ge=0)
    n_tier1: int = Field(ge=0)
    n_tier2: int = Field(ge=0)
    n_tier3: int = Field(ge=0)
    n_rejected_in_set: int = Field(ge=0)
    n_superseded_in_set: int = Field(ge=0)

    # Diversity metrics
    n_unique_programs: int = Field(ge=0)
    n_unique_test_sources: int = Field(ge=0)

    # Adequacy classification
    adequacy: PrecedentAdequacyLevel
    adequacy_reasoning: str

    # Matches by tier (limited to top-k per tier)
    tier1_matches: list[PrecedentMatch] = Field(default_factory=list)
    tier2_matches: list[PrecedentMatch] = Field(default_factory=list)
    tier3_matches: list[PrecedentMatch] = Field(default_factory=list)

    # Recommended base template
    recommended_base: PrecedentMatch | None = None
    base_selection_reasoning: str = ""

    retrieval_timestamp: datetime = Field(default_factory=datetime.utcnow)
