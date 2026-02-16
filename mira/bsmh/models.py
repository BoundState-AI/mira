#!/usr/bin/env python3
"""
Shared models for the temporary BSMH query path.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class BSMHStructuredQuery(BaseModel):
    """Structured query produced by the bouncer."""

    material: Optional[str] = None
    materials: List[str] = Field(default_factory=list)
    environment: Optional[str] = None
    pressure_psi: Optional[float] = None
    temperature_f: Optional[float] = None
    o2_pct: Optional[float] = None
    intent: str = "general"
    original_query: str

    model_config = {"extra": "forbid"}


class BouncerResult(BaseModel):
    """Outcome from the bouncer layer."""

    status: Literal["accepted", "rejected"]
    rejection_reason: Optional[str] = None
    structured_query: Optional[BSMHStructuredQuery] = None
    source: Literal["local_llm", "heuristic", "haiku"] = "heuristic"

    model_config = {"extra": "forbid"}


class RuleEvidenceItem(BaseModel):
    """Single deterministic evidence check."""

    property: str
    value: str
    requirement: str
    passed: bool
    source: Optional[str] = None

    model_config = {"extra": "forbid"}


class MaterialRuleResult(BaseModel):
    """Deterministic verdict for one material."""

    material_name: str
    material_key: Optional[Any] = None
    oxygen_rating: Optional[str] = None
    hydrogen_signal_present: Optional[bool] = None
    verdict: Literal["COMPATIBLE", "INCOMPATIBLE", "CONDITIONAL", "INSUFFICIENT_DATA"]
    score: float = Field(..., ge=0.0, le=1.0)
    evidence_strength: Literal["strong", "moderate", "limited", "insufficient"] = "limited"
    linkage_gap: bool = Field(
        False,
        description="True when MUA heritage is substantial but MAPTIS test linkage is sparse, "
        "indicating a database coverage gap rather than untested material.",
    )
    warnings: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    evidence_chain: List[RuleEvidenceItem] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class RuleDecisionPacket(BaseModel):
    """Output from deterministic MIRA-rules stage."""

    verdict: Literal["COMPATIBLE", "INCOMPATIBLE", "CONDITIONAL", "INSUFFICIENT_DATA"]
    confidence: float = Field(..., ge=0.0, le=1.0)
    materials: List[MaterialRuleResult] = Field(default_factory=list)
    aggregation_scope: Literal["primary_only", "all_materials"] = "primary_only"
    primary_material_count: int = 0
    associated_material_count: int = 0
    bok_context_used: bool = False
    bok_evidence_count: int = 0
    bok_sources: List[str] = Field(default_factory=list)
    requested_materials: List[str] = Field(default_factory=list)
    missing_requested_materials: List[str] = Field(default_factory=list)
    determination_material_keys: List[Any] = Field(default_factory=list)
    determination_material_names: List[str] = Field(default_factory=list)
    rules_applied: List[str] = Field(default_factory=list)
    standards_category: Optional[str] = None
    evidence_gaps: List[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class BSMHQueryRequest(BaseModel):
    """Request model for the temporary BSMH endpoint."""

    query: str = Field(..., min_length=1, description="Natural language M&P query")
    material_key: Optional[str] = Field(None, description="Target material identifier")
    temperature_c: Optional[float] = Field(None, description="Temperature in Celsius")
    pressure_kpa: Optional[float] = Field(None, ge=0, description="Pressure in kPa")
    o2_pct: Optional[float] = Field(None, ge=0, le=100, description="O2 concentration %")
    fluid_medium: Optional[str] = Field(None, description="Fluid medium (LOX, GOX, LH2, etc.)")
    duration_hr: Optional[float] = Field(None, ge=0, description="Exposure duration hours")
    cycles: Optional[int] = Field(None, ge=0, description="Thermal/pressure cycles")
    answer_mode: Literal["sonnet"] = Field(
        "sonnet",
        description="Answer formatter mode. BSMH production path is Sonnet-only.",
    )

    model_config = {"extra": "forbid"}


class BSMHQueryResponse(BaseModel):
    """Response model for temporary BSMH endpoint."""

    status: Literal["ok", "rejected", "error"]
    pipeline: str = "B-S-M-S"
    answer: str
    answer_sonnet: Optional[str] = None
    answer_mode: Literal["sonnet"] = "sonnet"
    sonnet_calls_used: int = 0
    bouncer: BouncerResult
    rules: Optional[RuleDecisionPacket] = None
    materials: List[Dict[str, Any]] = Field(default_factory=list)
    sonnet_metadata: Dict[str, Any] = Field(default_factory=dict)
    raw_v4_answer: Optional[str] = None
    v4_lineage_id: Optional[str] = None
    v4_gate_action: Optional[str] = None
    v4_confidence_score: Optional[float] = None
    error: Optional[str] = None

    model_config = {"extra": "forbid"}
