#!/usr/bin/env python3
"""
Module: Data Laundering Pipeline Models
Purpose: All Pydantic models and enums for the four-layer data laundering pipeline.

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Claude "CC" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: True

Pipeline-level models. These are DISTINCT from mira_v4.models (which are
domain-specific). These models define the pipeline envelope, layer outputs,
and audit trail structure.

All models use extra="forbid" — unknown fields are rejected.
Raw user input is NEVER stored as plaintext. Only SHA-256 hashes.

Spec Reference: BS-DL-ARCH-001
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# =============================================================================
# Enums
# =============================================================================


class QueryType(str, Enum):
    """Classification of query structure."""
    LOOKUP = "lookup"
    COMPARISON = "comparison"
    RECOMMENDATION = "recommendation"
    REGULATORY = "regulatory"
    EXPLORATORY = "exploratory"


class QueryIntent(str, Enum):
    """Resolved intent after Layer 1 sanitization."""
    MATERIAL_SEARCH = "material_search"
    PROPERTY_LOOKUP = "property_lookup"
    COMPATIBILITY_CHECK = "compatibility_check"
    RISK_ASSESSMENT = "risk_assessment"
    DOCUMENT_RETRIEVAL = "document_retrieval"
    COMPARISON = "comparison"
    GENERAL = "general"


class PipelineStatus(str, Enum):
    """Overall pipeline execution status."""
    COMPLETED = "completed"
    REJECTED_LAYER_1 = "rejected_layer_1"
    REJECTED_LAYER_2 = "rejected_layer_2"
    REJECTED_LAYER_3 = "rejected_layer_3"
    ERROR = "error"


class RejectionReason(str, Enum):
    """Why a query was killed at a specific layer."""
    PARSE_FAILURE = "parse_failure"
    INJECTION_DETECTED = "injection_detected"
    SCHEMA_VIOLATION = "schema_violation"
    NO_CANDIDATES = "no_candidates"
    ALL_CANDIDATES_FAILED_VALIDATION = "all_candidates_failed_validation"
    SAFETY_GATE_REFUSE = "safety_gate_refuse"
    DIRTY_DATA_REFUSE = "dirty_data_refuse"
    CONFIDENCE_REFUSE = "confidence_refuse"
    LLM_ERROR = "llm_error"
    VALIDATOR_ERROR = "validator_error"


# =============================================================================
# Layer 1 Output: SanitizedQuery
# =============================================================================


class EnvironmentFilter(BaseModel):
    """Environment constraints extracted from user input at Layer 1.

    Canonical units: Celsius / kPa / percentage.
    """

    model_config = {"extra": "forbid"}

    temperature_c: Optional[float] = Field(
        None, description="Temperature in Celsius"
    )
    pressure_kpa: Optional[float] = Field(
        None, ge=0, description="Pressure in kPa"
    )
    o2_pct: Optional[float] = Field(
        None, ge=0, le=100, description="Oxygen concentration %"
    )
    fluid_medium: Optional[str] = Field(
        None, description="Test fluid (e.g., LOX, GOX, LH2, GH2)"
    )
    duration_hr: Optional[float] = Field(
        None, ge=0, description="Exposure duration in hours"
    )
    cycles: Optional[int] = Field(
        None, ge=0, description="Thermal/pressure cycles"
    )

    @field_validator("fluid_medium", mode="before")
    @classmethod
    def normalize_fluid(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return str(v).strip().upper()


class SanitizedQuery(BaseModel):
    """Layer 1 output: rigid typed JSON from raw user input.

    This model is the ONLY thing that crosses from Layer 1 to Layer 2.
    Raw user input is dead after this. Only the SHA-256 hash survives.

    extra="forbid" — any field not in this schema kills the query.
    """

    model_config = {"extra": "forbid"}

    input_hash: str = Field(
        ..., min_length=64, max_length=64,
        description="SHA-256 of the raw user input. Raw text is DEAD."
    )
    query_type: QueryType = Field(
        ..., description="Structural classification of the query"
    )
    intent: QueryIntent = Field(
        ..., description="Resolved intent classification"
    )
    material_name: Optional[str] = Field(
        None, description="Target material identifier"
    )
    property_names: List[str] = Field(
        default_factory=list,
        description="Requested material properties"
    )
    environment: EnvironmentFilter = Field(
        default_factory=EnvironmentFilter,
        description="Environment constraints"
    )
    filters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional typed filters extracted from query"
    )
    safety_context: Optional[str] = Field(
        None, description="Detected safety context (oxygen, hydrogen, cryogenic, etc.)"
    )

    @staticmethod
    def hash_input(raw_input: str) -> str:
        """SHA-256 hash of raw user input. The raw text dies here."""
        return hashlib.sha256(raw_input.encode("utf-8")).hexdigest()


# =============================================================================
# Layer 2 Output: ReasonerOutput
# =============================================================================


class CandidateRecord(BaseModel):
    """A single candidate record proposed by the reasoner (Layer 2)."""

    model_config = {"extra": "forbid"}

    material_key: str = Field(
        ..., min_length=1, description="Material identifier"
    )
    record_id: Optional[str] = Field(
        None, description="Database record ID if known"
    )
    reasoning: str = Field(
        ..., description="Why this candidate was selected"
    )
    relevance_score: float = Field(
        ..., ge=0.0, le=1.0,
        description="LLM-estimated relevance 0.0-1.0"
    )
    properties: Dict[str, Any] = Field(
        default_factory=dict,
        description="Expected properties for this material"
    )


class ReasonerOutput(BaseModel):
    """Layer 2 output: ranked candidate list with reasoning.

    Sonnet produces this. It has NOT been validated against ground truth.
    These are hypotheses, not facts.
    """

    model_config = {"extra": "forbid"}

    candidates: List[CandidateRecord] = Field(
        ..., min_length=1,
        description="Ranked candidate records"
    )
    search_strategy: str = Field(
        ..., description="Description of the search approach used"
    )
    filters_applied: Dict[str, Any] = Field(
        default_factory=dict,
        description="Filters that were applied to narrow candidates"
    )
    total_considered: int = Field(
        0, ge=0,
        description="Total records considered before ranking"
    )


# =============================================================================
# Layer 3 Output: ValidatedResults
# =============================================================================


class ValidatedRecord(BaseModel):
    """A single record that survived Layer 3 ground-truth validation."""

    model_config = {"extra": "forbid"}

    material_key: str = Field(
        ..., min_length=1, description="Material identifier"
    )
    record_id: str = Field(
        ..., min_length=1, description="Database record ID"
    )
    source: str = Field(
        ..., description="Data source (MAPTIS, GRANTA, etc.)"
    )
    properties: Dict[str, Any] = Field(
        default_factory=dict,
        description="Validated property values"
    )
    confidence_score: float = Field(
        ..., ge=0.0, le=1.0,
        description="Confidence score from penalty calculator"
    )
    dirty_flag: bool = Field(
        False, description="True if record contains non-typed data"
    )
    dirty_fields: List[str] = Field(
        default_factory=list,
        description="Fields with non-typed data"
    )
    raw_values: Dict[str, Any] = Field(
        default_factory=dict,
        description="Original raw values for dirty fields (audit trail)"
    )
    heritage_vetoed: bool = Field(
        False, description="True if heritage veto applies"
    )
    heritage_requires_acknowledgment: bool = Field(
        False, description="True if safety-critical heritage veto"
    )


class ValidatedResults(BaseModel):
    """Layer 3 output: ground-truth-confirmed records with provenance."""

    model_config = {"extra": "forbid"}

    records: List[ValidatedRecord] = Field(
        default_factory=list,
        description="Records that survived validation"
    )
    query_hash: str = Field(
        ..., min_length=64, max_length=64,
        description="Deterministic query hash"
    )
    snapshot_hash: str = Field(
        ..., min_length=64, max_length=64,
        description="Snapshot hash with timestamp"
    )
    total_candidates: int = Field(
        0, ge=0,
        description="Total candidates received from Layer 2"
    )
    candidates_validated: int = Field(
        0, ge=0,
        description="Candidates that passed validation"
    )
    candidates_rejected: int = Field(
        0, ge=0,
        description="Candidates rejected by validation"
    )
    relaxation_suggestions: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Suggested filter relaxations if zero results"
    )
    safety_gate_result: Optional[Dict[str, Any]] = Field(
        None, description="Batch safety gate result if applicable"
    )
    dirty_data_summary: Optional[Dict[str, Any]] = Field(
        None, description="Dirty data classification summary"
    )
    schema_version: str = Field(
        "unknown", description="Schema version at query time"
    )


# =============================================================================
# Layer 4 Output: PresentedResponse
# =============================================================================


class Citation(BaseModel):
    """A single citation linking a claim to its source record."""

    model_config = {"extra": "forbid"}

    record_id: str = Field(..., description="Source record ID")
    source: str = Field(..., description="Data source name")
    claim: str = Field(..., description="The specific claim being cited")


class PresentedResponse(BaseModel):
    """Layer 4 output: formatted response text with citations.

    Haiku produces this from ONLY validated data. It sees nothing
    from Layer 1 or Layer 2. Only Layer 3 validated records.
    """

    model_config = {"extra": "forbid"}

    response_text: str = Field(
        ..., min_length=1,
        description="Formatted response for the user"
    )
    citations: List[Citation] = Field(
        default_factory=list,
        description="Citations linking claims to source records"
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="Any warnings (dirty data, heritage vetoes, etc.)"
    )
    confidence_summary: str = Field(
        "", description="Human-readable confidence summary"
    )


# =============================================================================
# Pipeline Envelope (Root Artifact)
# =============================================================================


class LayerTiming(BaseModel):
    """Timing and cost metadata for a single pipeline layer."""

    model_config = {"extra": "forbid"}

    layer: int = Field(..., ge=1, le=4, description="Layer number 1-4")
    layer_name: str = Field(..., description="Layer name")
    started_at: str = Field(..., description="ISO 8601 start timestamp")
    completed_at: Optional[str] = Field(
        None, description="ISO 8601 completion timestamp"
    )
    duration_ms: Optional[float] = Field(
        None, ge=0, description="Duration in milliseconds"
    )
    llm_model: Optional[str] = Field(
        None, description="LLM model used (if any)"
    )
    llm_input_tokens: Optional[int] = Field(
        None, ge=0, description="Input tokens consumed"
    )
    llm_output_tokens: Optional[int] = Field(
        None, ge=0, description="Output tokens produced"
    )
    error: Optional[str] = Field(
        None, description="Error message if layer failed"
    )


class PipelineEnvelope(BaseModel):
    """Root audit artifact for a single pipeline execution.

    This IS the audit trail. Every query produces one of these.
    It wraps all four layer outputs plus timing and cost metadata.

    WARNING: Once completed, this should be treated as immutable
    for compliance with NASA-STD-8739.8B.
    """

    model_config = {"extra": "forbid"}

    envelope_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique envelope identifier"
    )
    domain: str = Field(
        ..., description="Domain pack identifier (e.g., 'mira', 'aegis', 'sentinel')"
    )
    status: PipelineStatus = Field(
        PipelineStatus.ERROR,
        description="Overall pipeline execution status"
    )
    rejection_reason: Optional[RejectionReason] = Field(
        None, description="Why the query was rejected (if applicable)"
    )
    rejection_detail: Optional[str] = Field(
        None, description="Human-readable rejection explanation"
    )

    # Input hash only — raw text is dead
    input_hash: str = Field(
        ..., min_length=64, max_length=64,
        description="SHA-256 of the raw user input"
    )

    # Layer outputs (None if layer was not reached)
    layer_1_output: Optional[SanitizedQuery] = Field(
        None, description="Layer 1 sanitization output"
    )
    layer_2_output: Optional[ReasonerOutput] = Field(
        None, description="Layer 2 reasoning output"
    )
    layer_3_output: Optional[ValidatedResults] = Field(
        None, description="Layer 3 validation output"
    )
    layer_4_output: Optional[PresentedResponse] = Field(
        None, description="Layer 4 presentation output"
    )

    # Timing
    layer_timings: List[LayerTiming] = Field(
        default_factory=list,
        description="Per-layer timing and cost metadata"
    )
    pipeline_started_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 pipeline start timestamp"
    )
    pipeline_completed_at: Optional[str] = Field(
        None, description="ISO 8601 pipeline completion timestamp"
    )
    total_duration_ms: Optional[float] = Field(
        None, ge=0, description="Total pipeline duration in milliseconds"
    )

    # Lineage link
    decision_lineage_id: Optional[str] = Field(
        None, description="Link to v4 DecisionLineage record if generated"
    )

    def mark_completed(self, status: PipelineStatus) -> None:
        """Mark the pipeline as completed with final status and timing."""
        self.status = status
        self.pipeline_completed_at = datetime.now(timezone.utc).isoformat()
        # Compute total duration
        started = datetime.fromisoformat(self.pipeline_started_at)
        completed = datetime.fromisoformat(self.pipeline_completed_at)
        self.total_duration_ms = (completed - started).total_seconds() * 1000

    def add_layer_timing(self, timing: LayerTiming) -> None:
        """Add a layer timing record to the envelope."""
        self.layer_timings.append(timing)
