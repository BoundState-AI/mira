#!/usr/bin/env python3
"""
Module: V8 MUA Models
Purpose: Data models for LLM-rendered MUA documents.

BoundState AI 2026
Version: 8.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013 (Traceability), SWE-032 (Data validation)
Safety Critical: True
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class MUAEnvironment(BaseModel):
    """Operating environment for MUA."""
    medium: str = "Air"
    o2_percent: float = 21.0
    pressure_psia: float = 14.7
    temp_min_f: Optional[float] = None
    temp_max_f: Optional[float] = None
    location: str = "nonhabitable"
    application: Optional[str] = None


class MUARating(BaseModel):
    """Single test class rating."""
    test_class: str
    rating: Optional[str] = None
    source: Optional[str] = None
    report_number: Optional[str] = None
    test_date: Optional[str] = None


class MUAGap(BaseModel):
    """Identified gap in compliance."""
    gap_id: str
    dimension: str
    severity: Literal["critical", "high", "medium", "low"]
    description: str
    disposition: Optional[str] = None
    rationale: Optional[str] = None


class MUAPrecedent(BaseModel):
    """A real MUA precedent from the corpus."""
    mua_number: str
    material_name: Optional[str] = None
    material_specification: Optional[str] = None
    determination: Optional[str] = None
    rationale: Optional[str] = None
    environment: Optional[str] = None
    o2_concentration_pct: Optional[float] = None
    pressure_psi_max: Optional[float] = None
    parser_confidence: Optional[float] = None
    relevance_score: Optional[float] = None


class MUAEvidenceStrength(BaseModel):
    """Evidence strength assessment."""
    band: str  # STRONG, MODERATE, LIMITED, INSUFFICIENT
    score: float
    components: Dict[str, Any] = Field(default_factory=dict)
    penalties: Dict[str, Any] = Field(default_factory=dict)


class MUASessionData(BaseModel):
    """
    Complete MUA session data - the structured input to the renderer.

    This is the "db dump" that the LLM transforms into a professional document.
    All fields come from the MUA session engine, MAPTIS queries, and compliance
    analysis. The renderer never invents data - it only presents this data
    in professional document form.
    """
    # Identity
    mua_id: str
    session_id: Optional[str] = None
    finalized_at: Optional[str] = None

    # Material
    material_name: str
    maptis_code: Optional[str] = None
    material_class: Optional[str] = None

    # Classification
    category: str  # "I", "II", "III"
    center: Optional[str] = None
    applied_standard: str = "NASA-STD-6016C"
    reviewer: Optional[str] = None

    # Environment
    environment: MUAEnvironment = Field(default_factory=MUAEnvironment)

    # Ratings
    ratings: List[MUARating] = Field(default_factory=list)

    # Gaps
    gaps: List[MUAGap] = Field(default_factory=list)

    # Evidence
    evidence_strength: Optional[MUAEvidenceStrength] = None

    # Precedents (from Postgres)
    precedents: List[MUAPrecedent] = Field(default_factory=list)

    # Additional context
    banners: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)
    cited_evidence: List[Dict[str, Any]] = Field(default_factory=list)


class MUARenderedDocument(BaseModel):
    """Output from the LLM renderer."""
    mua_id: str
    document_text: str
    rendered_at: datetime = Field(default_factory=datetime.utcnow)
    model_used: str = ""
    precedents_used: int = 0
    token_count: Optional[int] = None
