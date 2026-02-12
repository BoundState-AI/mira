"""
MUA Final - Data Models

Clean Pydantic models for the unified MUA system.  These are the
"session data" that the LLM renderer transforms into a professional
NASA document.  All fields come from the v7 investigation pipeline;
the renderer never invents data.

BoundState AI 2026
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

class MUAEnvironment(BaseModel):
    """Operating environment for MUA."""
    medium: str = "Air"
    o2_percent: float = 21.0
    pressure_psia: float = 14.7
    temp_min_f: Optional[float] = None
    temp_max_f: Optional[float] = None
    location: str = "nonhabitable"
    application: Optional[str] = None


# ---------------------------------------------------------------------------
# Evidence components
# ---------------------------------------------------------------------------

class MUARating(BaseModel):
    """Single MAPTIS test class rating."""
    test_class: str
    rating: Optional[str] = None
    source: Optional[str] = None
    report_number: Optional[str] = None
    test_date: Optional[str] = None
    is_current: Optional[bool] = None


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
    relevance_score: Optional[float] = None
    is_supporting: bool = True
    is_conflicting: bool = False
    relationship_explanation: Optional[str] = None


class MUAConflict(BaseModel):
    """Cross-source conflict (from v7 conflict detector)."""
    conflict_id: str
    severity: str  # hard, soft, none
    source_a: str
    source_b: str
    description: str
    recommendation: str
    disposition: Optional[str] = None
    rationale: Optional[str] = None


class MUAEvidenceStrength(BaseModel):
    """Evidence strength assessment (Fran's formula from v7)."""
    band: str  # STRONG, MODERATE, WEAK, INSUFFICIENT
    score: float
    components: Dict[str, Any] = Field(default_factory=dict)
    penalties: Dict[str, Any] = Field(default_factory=dict)
    explanation: Optional[str] = None


class MUAEnvelopeResult(BaseModel):
    """Environmental envelope coverage."""
    overall_status: str
    o2_status: str
    pressure_status: str
    temp_status: str
    coverage_ratio: float
    details: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Session data (the bridge between v7 pipeline and LLM renderer)
# ---------------------------------------------------------------------------

class MUASessionData(BaseModel):
    """
    Complete MUA session data -- the structured input to the renderer.

    This is the "db dump" that Claude transforms into a professional
    NASA document.  All fields are populated by the v7 investigation
    pipeline + engineer review decisions.  The renderer never invents
    data -- it only presents what's here.
    """
    # Identity
    mua_id: str
    session_id: Optional[str] = None
    finalized_at: Optional[str] = None

    # Material
    material_name: str
    maptis_code: Optional[str] = None
    material_class: Optional[str] = None
    material_family: Optional[str] = None
    is_novel_material: bool = False
    is_process_sensitive: bool = False

    # Classification
    category: str  # "I", "II", "III"
    center: Optional[str] = None
    applied_standard: str = "NASA-STD-6016C"
    reviewer: Optional[str] = None

    # Environment
    environment: MUAEnvironment = Field(default_factory=MUAEnvironment)

    # Ratings (from MAPTIS)
    ratings: List[MUARating] = Field(default_factory=list)

    # Gaps (with engineer dispositions from v7 review step)
    gaps: List[MUAGap] = Field(default_factory=list)

    # Conflicts (from v7 conflict detector, with engineer dispositions)
    conflicts: List[MUAConflict] = Field(default_factory=list)

    # Evidence
    evidence_strength: Optional[MUAEvidenceStrength] = None
    envelope: Optional[MUAEnvelopeResult] = None

    # Precedents (from v7 PG search, filtered by review decisions)
    precedents: List[MUAPrecedent] = Field(default_factory=list)

    # Routing basis (from v7 category router)
    routing_basis: List[Dict[str, Any]] = Field(default_factory=list)

    # Context
    banners: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)
    cited_evidence: List[Dict[str, Any]] = Field(default_factory=list)
    dependency_warnings: List[str] = Field(default_factory=list)

    # Process params (for adhesives/composites/potting/sealants)
    process_params: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Rendered output
# ---------------------------------------------------------------------------

class MUARenderedDocument(BaseModel):
    """Output from the LLM renderer."""
    mua_id: str
    document_text: str
    rendered_at: datetime = Field(default_factory=datetime.utcnow)
    model_used: str = ""
    precedents_used: int = 0
    token_count: Optional[int] = None
