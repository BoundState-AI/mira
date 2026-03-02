#!/usr/bin/env python3
"""
Module: Models
Purpose: Hydrogen compatibility request/response models for MIRA under BoundState.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-CSET, SWE-013, SWE-032
Safety Critical: False
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field

from core.models.answer import AnswerSeverity, EngineAnswer
import uuid


class ConditionOptionResponse(BaseModel):
    """Heat treatment condition option for clarification responses.

    Presented when a material has different HEE bands depending on condition
    and the user didn't specify which condition they're asking about.
    """

    condition_name: str = Field(
        description="Heat treatment condition name (e.g., 'ST 1750F', 'Annealed').",
    )
    hee_band: str = Field(
        description="HEE band for this condition (e.g., 'severe', 'small').",
    )
    verdict_if_selected: str = Field(
        description="What verdict would be returned if this condition is selected.",
    )
    evidence_count: int = Field(
        description="Number of evidence records supporting this condition.",
    )
    source: str = Field(
        description="Source document(s) for this condition's data.",
    )


class HydrogenPhase(str, Enum):
    """Phase of hydrogen for the query."""

    GAS = "gh2"
    LIQUID = "lh2"


class H2CompatibilityRequest(BaseModel):
    """Structured request for a hydrogen compatibility evaluation.

    NOTE: material_key should be a validated identifier into the material
    repository (MAPTIS, internal catalog, etc.), not a free-text name.
    """

    question: str = Field(
        description="Raw natural-language question, if provided.",
    )
    material_key: str = Field(
        description="Canonical material identifier (e.g. MAPTIS ID, spec key).",
    )
    pressure_psia: float = Field(
        description="Operating pressure in psia.",
    )
    temperature_k: float = Field(
        description="Operating temperature in kelvin.",
    )
    phase: HydrogenPhase = Field(
        description="Hydrogen phase (gas or liquid).",
    )
    application_id: Optional[str] = Field(
        default=None,
        description="Optional application identifier (subsystem/component).",
    )
    yield_strength_ksi: Optional[float] = Field(
        default=None,
        description="Material yield strength in ksi (critical for HE risk).",
    )
    condition: Optional[str] = Field(
        default=None,
        description="Optional heat-treatment/material condition filter (e.g., ST 1900F, annealed).",
    )


class H2CompatibilityResponse(EngineAnswer):
    """Specialization of EngineAnswer for hydrogen compatibility.

    Key H2-specific concerns:
    - Hydrogen embrittlement (HE) risk
    - Pressure effects on permeation
    - Temperature effects on HE severity

    When needs_clarification=True, the user should be prompted to specify
    the heat treatment condition before a definitive verdict can be given.
    """

    classification: AnswerSeverity = Field(
        description="Hydrogen compatibility classification.",
    )
    embrittlement_risk: Optional[str] = Field(
        default=None,
        description="Hydrogen embrittlement risk level (low/medium/high/severe).",
    )
    h2_score: Optional[float] = Field(
        default=None,
        description="Computed H2 compatibility score (0.0 to 1.0).",
    )

    # Clarification fields - populated when multiple conditions with different bands exist
    needs_clarification: bool = Field(
        default=False,
        description="True if user should specify heat treatment condition.",
    )
    clarification_prompt: Optional[str] = Field(
        default=None,
        description="User-facing prompt explaining why clarification is needed.",
    )
    available_conditions: List[ConditionOptionResponse] = Field(
        default_factory=list,
        description="Available condition options when clarification is needed.",
    )
    band_distribution: Optional[dict] = Field(
        default=None,
        description="Distribution of HEE bands across all evidence (e.g., {'extreme': 2, 'severe': 1}).",
    )


class H2ConditionLookupResponse(BaseModel):
    """Condition lookup response for UI pre-fill/selection."""

    material_key: str = Field(
        description="Requested material identifier/text.",
    )
    canonical_material: Optional[str] = Field(
        default=None,
        description="Resolved canonical material name if known.",
    )
    has_matches: bool = Field(
        default=False,
        description="True when evidence records were found for the material.",
    )
    requires_clarification: bool = Field(
        default=False,
        description="True when multiple conditions have different HEE bands.",
    )
    match_type: str = Field(
        default="none",
        description="Best match quality (exact/alias/fuzzy/family/none).",
    )
    available_conditions: List[ConditionOptionResponse] = Field(
        default_factory=list,
        description="Available heat-treatment condition options for this material.",
    )
    band_distribution: Optional[dict[str, int]] = Field(
        default=None,
        description="HEE band counts across matched evidence records.",
    )
    unresolved_condition_count: int = Field(
        default=0,
        description="Number of matched records whose condition label needs review.",
    )
    notes: Optional[str] = Field(
        default=None,
        description="Optional informational note for the UI.",
    )


class H2ConditionAliasRecord(BaseModel):
    """Condition alias-cache record for review/approval."""

    raw_key: str
    raw_text: str
    canonical_condition: str
    display_label: str
    is_condition: bool
    confidence: Optional[float] = None
    resolver_provider: Optional[str] = None
    resolver_model: Optional[str] = None
    source_document: Optional[str] = None
    material_name: Optional[str] = None
    needs_review: bool = False
    human_verified: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class H2ConditionAliasListResponse(BaseModel):
    """Condition alias review listing for the UI."""

    material_key: Optional[str] = None
    unresolved_only: bool = True
    count: int = 0
    aliases: List[H2ConditionAliasRecord] = Field(default_factory=list)


class H2ConditionAliasVerifyRequest(BaseModel):
    """Request to human-verify/override a condition alias mapping."""

    raw_key: str
    display_label: str
    canonical_condition: Optional[str] = None
    is_condition: bool = True
    raw_text: Optional[str] = None
    source_document: Optional[str] = None
    material_name: Optional[str] = None


class H2ConditionAliasVerifyResponse(BaseModel):
    """Response after verifying a condition alias."""

    status: str = "ok"
    cache_entries_cleared: int = 0
    alias: H2ConditionAliasRecord
