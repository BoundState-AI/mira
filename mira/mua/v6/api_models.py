#!/usr/bin/env python3
"""
Module: Api Models
Purpose: API Models for V6 MUA Generator.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013 (Traceability)
Safety Critical: False
"""

from __future__ import annotations

from typing import List, Literal, Optional
from pydantic import BaseModel, Field

__all__ = [
    "EnvironmentSpec",
    "V6GenerateRequest",
    "V6PrecedentSearchRequest",
    "V6GenerateFromSelectionRequest",
    "PrecedentSummary",
    "V6GenerateResponse",
    "PrecedentOption",
    "V6StatsResponse",
]


class EnvironmentSpec(BaseModel):
    """Environment specification for MUA request."""

    type: str = Field(..., description="Environment type (vacuum, cabin_air, enriched_o2, lox_gox, etc.)")
    o2_percent: Optional[float] = Field(None, ge=0, le=100, description="O2 percentage")
    pressure_psia: Optional[float] = Field(None, ge=0, description="Pressure in PSIA")
    temperature_f: Optional[float] = Field(None, description="Temperature in Fahrenheit")
    is_habitable: bool = Field(False, description="Whether environment is habitable")


class V6GenerateRequest(BaseModel):
    """Request to generate MUA draft."""

    material: str = Field(..., min_length=1, description="Material designation")
    environment: EnvironmentSpec = Field(..., description="Environment specification")
    application: str = Field("", description="Application/usage context")
    issues: Optional[List[str]] = Field(None, description="Issue categories to address (auto-detect if not provided)")
    mode: Literal["auto", "interactive"] = Field("auto", description="Generation mode")


class V6PrecedentSearchRequest(BaseModel):
    """Request to search for precedents (interactive mode)."""

    material: str = Field(..., min_length=1, description="Material designation")
    environment: EnvironmentSpec = Field(..., description="Environment specification")
    issues: Optional[List[str]] = Field(None, description="Issue categories to filter by")
    top_k: int = Field(10, ge=1, le=50, description="Number of results to return")
    approved_only: bool = Field(True, description="Filter to APPROVED precedents only")


class V6GenerateFromSelectionRequest(BaseModel):
    """Generate MUA from user-selected precedents."""

    material: str = Field(..., min_length=1, description="Material designation")
    environment: EnvironmentSpec = Field(..., description="Environment specification")
    application: str = Field("", description="Application/usage context")
    issues: List[str] = Field(default_factory=list, description="Issue categories addressed")
    selected_mua_numbers: List[str] = Field(..., min_length=1, description="Selected precedent MUA numbers")


class PrecedentSummary(BaseModel):
    """Summary of a precedent used in generation."""

    mua_number: str
    material: str
    environment: str
    determination: str
    relevance_score: float
    rationale_excerpt: str = Field("", max_length=300)


class V6GenerateResponse(BaseModel):
    """MUA generation response."""

    draft_text: str = Field(..., description="Generated MUA draft text")
    material: str
    environment: str
    recommended_determination: str
    confidence: float = Field(..., ge=0, le=1)
    precedents_used: List[PrecedentSummary]
    issues_addressed: List[str]
    gaps_identified: List[str]
    warnings: List[str]
    mode_used: Literal["auto", "selected"]


class PrecedentOption(BaseModel):
    """Precedent option for interactive selection."""

    mua_number: str
    material_designation: str
    environment_summary: str
    issue_summary: str
    determination: str
    rationale_preview: str = Field("", max_length=300, description="First 300 chars of rationale")
    match_score: float = Field(..., ge=0, le=1)
    applicability_notes: str = Field("", description="Why this might/might not apply")
    is_synthesized_rationale: bool = Field(False, description="Whether rationale was synthesized from application")


class V6StatsResponse(BaseModel):
    """Statistics about the v6 precedent database."""

    total_records: int
    index_vectors: int
    embedding_model: str
    by_determination: dict
    by_environment_type: dict
    by_material_family: dict
    by_issue_category: dict
