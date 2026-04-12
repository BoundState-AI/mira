#!/usr/bin/env python3
"""
Module: MIRA v4 Decision Lineage API — Request/Response Models
Purpose: Pydantic models for the MIRA v4 decision lineage pipeline.

BoundState AI 2026
Version: 4.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Atlas" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-032
Safety Critical: False

Extracted from mira_v4.py to keep the router focused on route handlers.
Contains only data models (Pydantic BaseModel subclasses).
No business logic, no LLM calls, no side effects.

All models use extra="forbid" where applicable to reject unknown fields
per BoundState Pydantic standards.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Query request
# ---------------------------------------------------------------------------


class V4QueryRequest(BaseModel):
    """Request for the full MIRA v4 decision lineage pipeline."""

    query: str = Field(..., min_length=1, description="Natural language query")
    batch_mode: bool = Field(False, description="Enable batch mode safety gate")
    material_key: Optional[str] = Field(None, description="Target material identifier")
    temperature_c: Optional[float] = Field(None, description="Temperature in Celsius")
    pressure_kpa: Optional[float] = Field(None, ge=0, description="Pressure in kPa")
    o2_pct: Optional[float] = Field(None, ge=0, le=100, description="O2 concentration %")
    fluid_medium: Optional[str] = Field(None, description="Fluid medium (LOX, GOX, LH2, etc.)")
    duration_hr: Optional[float] = Field(None, ge=0, description="Exposure duration hours")
    cycles: Optional[int] = Field(None, ge=0, description="Thermal/pressure cycles")
    llm_model: Optional[str] = Field(
        None,
        description="Requested response model hint (kept for UI backward compatibility)",
    )

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# Response sub-models (building blocks for V4QueryResponse)
# ---------------------------------------------------------------------------


class V4PenaltyDetailResponse(BaseModel):
    """Single penalty breakdown entry."""

    penalty_type: str
    penalty_value: float
    explanation: str


class V4ConfidenceResponse(BaseModel):
    """Confidence calculation result."""

    score: float
    penalties: Dict[str, float]
    penalty_details: List[V4PenaltyDetailResponse]
    gate_action: str
    safety_critical: bool
    explanation: str


class V4BatchGateResponse(BaseModel):
    """Batch safety gate result."""

    action: str
    penalty: float
    missing_fields: List[str]
    safety_context: str
    reason: str


class V4DirtyDataResponse(BaseModel):
    """Dirty data tier classification."""

    tier: str
    dirty_fraction: float
    total_records: int
    dirty_records: int
    user_message: Optional[str] = None


class V4HeritageVetoResponse(BaseModel):
    """Heritage veto check result."""

    vetoed: bool
    veto_type: Optional[str] = None
    heritage_failure_ids: List[str] = Field(default_factory=list)
    requires_acknowledgment: bool = False
    rank_penalty: float = 0.0
    envelope_match_details: Dict[str, Any] = Field(default_factory=dict)


class V4IntentDisagreementResponse(BaseModel):
    """Intent classifier disagreement record."""

    sonnet_intent: str
    heuristic_intent: str
    chosen_intent: str
    penalty_applied: float
    explanation: str


class V4MaterialResponse(BaseModel):
    """Enriched material result with test data summary."""

    material_key: Any  # int from DB
    material_code: Optional[Any] = None
    designation: str = ""
    composition: Optional[str] = None
    material_type_key: Optional[int] = None
    material_type_name: Optional[str] = None
    use_temp_min_f: Optional[float] = None
    use_temp_max_f: Optional[float] = None
    use_temp_min_c: Optional[float] = None
    use_temp_max_c: Optional[float] = None
    test_counts: Dict[str, int] = Field(default_factory=dict)
    total_tests: int = 0
    latest_test_year: Optional[int] = None
    mua_count: int = 0
    has_mua_precedent: bool = False
    oxygen_compatible: bool = False
    similarity_score: Optional[float] = None


# ---------------------------------------------------------------------------
# Query response (full decision lineage)
# ---------------------------------------------------------------------------


class V4QueryResponse(BaseModel):
    """Full decision lineage response."""

    lineage_id: str
    query_hash: str
    snapshot_hash: str
    confidence: V4ConfidenceResponse
    gate_action: str
    batch_gate: Optional[V4BatchGateResponse] = None
    dirty_data: Optional[V4DirtyDataResponse] = None
    heritage_veto: Optional[V4HeritageVetoResponse] = None
    intent_disagreement: Optional[V4IntentDisagreementResponse] = None
    answer: str = ""
    materials: List[Dict[str, Any]] = Field(default_factory=list)
    all_materials: List[Dict[str, Any]] = Field(default_factory=list)
    all_material_count: int = 0
    materials_focus_applied: bool = False
    material_families: List[str] = Field(default_factory=list)
    search_source: str = ""
    parsed_query: Dict[str, Any] = Field(default_factory=dict)
    schema_version: str = ""
    timestamp: str = ""
    total_test_records: int = 0
    materials_with_tests: int = 0
    materials_with_mua: int = 0


# ---------------------------------------------------------------------------
# Batch mode
# ---------------------------------------------------------------------------


class V4BatchQueryRequest(BaseModel):
    """Batch mode request with multiple queries."""

    queries: List[V4QueryRequest] = Field(..., min_length=1, max_length=100)

    model_config = {"extra": "forbid"}


class V4BatchQueryResponse(BaseModel):
    """Batch mode response."""

    results: List[V4QueryResponse]
    total: int
    refused_count: int


# ---------------------------------------------------------------------------
# Heritage override
# ---------------------------------------------------------------------------


class V4HeritageOverrideRequest(BaseModel):
    """Engineer acknowledgment for heritage veto."""

    material_key: str = Field(..., min_length=1, description="Material identifier")
    heritage_failure_id: str = Field(..., min_length=1, description="Heritage failure record ID")
    failure_environment: Dict[str, Any] = Field(..., description="Failure environment (EnvironmentSpec-compatible)")
    query_environment: Dict[str, Any] = Field(..., description="Query environment (EnvironmentSpec-compatible)")
    engineer_name: str = Field(..., min_length=1, description="Engineer name")
    engineer_rationale: str = Field(..., min_length=10, description="Rationale for override (min 10 chars)")
    lineage_hash: str = Field(..., min_length=64, max_length=64, description="Parent decision lineage query_hash")

    model_config = {"extra": "forbid"}


class V4HeritageOverrideResponse(BaseModel):
    """Created heritage override record."""

    override_id: str
    material_key: str
    heritage_failure_id: str
    engineer_name: str
    timestamp: str
    acknowledged: bool


# ---------------------------------------------------------------------------
# Schema validation (CI)
# ---------------------------------------------------------------------------


class V4SchemaValidationResponse(BaseModel):
    """Schema validation result for CI."""

    passed: bool
    schema_version: str
    changes: List[Dict[str, Any]] = Field(default_factory=list)
    requires_faiss_rebuild: bool = False
    requires_regression: bool = False
