#!/usr/bin/env python3
"""
Module: MIRA v4 Shared Models
Purpose: All shared Pydantic models and enums for MIRA v4 BuildSpec REV1.

BoundState AI 2026
Version: 4.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-8739.8B, SWE-013, SWE-032, SWE-033
Safety Critical: True

This module is the FOUNDATION for all v4 modules. Every other module
imports from here. No module-specific models should be defined elsewhere.

Spec Reference: BS-MIRA-V4-BUILDSPEC-001-REV1
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# =============================================================================
# Enums
# =============================================================================


class SafetyContext(str, Enum):
    """Safety domain classification per BuildSpec Table 6.

    Determines required fields and gate behavior for batch mode
    and confidence thresholds.

    Compliance: SWE-013, NASA-STD-6016 S4.2.1
    """

    OXYGEN = "oxygen"              # O2 >= 23.5%
    HYDROGEN = "hydrogen"          # LH2/GH2 service
    CRYOGENIC = "cryogenic"        # T < -100F (-73C)
    HIGH_PRESSURE = "high_pressure"  # > 3000 psi (20.7 MPa)
    GENERAL = "general"            # Non-safety-critical


class DirtyDataTier(str, Enum):
    """Dirty data classification per BuildSpec Section 3.2.

    CLEAN:    0-10%  dirty records -> proceed normally
    DEGRADED: 11-30% dirty records -> proceed with warning
    REFUSE:   >30%   dirty records -> REFUSE for affected property

    Compliance: SWE-032, NASA-STD-8739.8B
    """

    CLEAN = "clean"
    DEGRADED = "degraded"
    REFUSE = "refuse"


class GateAction(str, Enum):
    """Confidence gate actions per BuildSpec Section 2.5.

    PASS:    Query proceeds (>= 0.85 safety, >= 0.70 general)
    CLARIFY: Route to clarification engine (0.50 - 0.69)
    REFUSE:  Insufficient information (< 0.50)

    Compliance: SWE-013, SWE-033
    """

    PASS = "PASS"
    CLARIFY = "CLARIFY"
    REFUSE = "REFUSE"


class BatchGateAction(str, Enum):
    """Batch safety gate actions per BuildSpec Section 4.3.

    PROCEED: Query can proceed (general, or safety-critical with all fields)
    REFUSE:  Safety-critical context with missing required fields

    Compliance: SWE-013, NASA-STD-6016 S4.2.1, S5.1.4
    """

    PROCEED = "PROCEED"
    REFUSE = "REFUSE"


class SchemaChangeType(str, Enum):
    """Schema diff classification per BuildSpec Section 8.2.

    NEW_FIELD:     Granta has field not in dictionary (WARN)
    REMOVED_FIELD: Dictionary has field not in Granta (FAIL)
    TYPE_CHANGE:   Field exists but type differs (FAIL)
    NAME_CHANGE:   Fuzzy match suggests rename (WARN)

    Compliance: SWE-032, NASA-STD-8739.8B
    """

    NEW_FIELD = "new_field"
    REMOVED_FIELD = "removed_field"
    TYPE_CHANGE = "type_change"
    NAME_CHANGE = "name_change"


class HeritageVetoType(str, Enum):
    """Heritage veto severity per BuildSpec Section 7.2.

    SAFETY_CRITICAL: Flagging with mandatory acknowledgment gate
    NON_SAFETY:      Flagging with rank sink only

    Compliance: NASA-STD-6016 S4.2.1, SWE-013, SWE-033
    """

    SAFETY_CRITICAL = "safety_critical"
    NON_SAFETY = "non_safety"


# =============================================================================
# Environment & Query Models
# =============================================================================


class EnvironmentSpec(BaseModel):
    """Environment specification for MIRA v4 queries.

    Canonical units: Celsius / kPa / percentage.

    NOTE: This is distinct from the existing EnvironmentEnvelope
    (which uses Fahrenheit / psia). EnvironmentSpec is the v4 canonical
    form used throughout all v4 modules.

    Compliance: SWE-032
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
        """Normalize fluid medium to uppercase."""
        if v is None:
            return None
        return str(v).strip().upper()

    def count_missing_fields(self) -> int:
        """Count how many of the 6 environment fields are None.

        Used by confidence calculator for unknown_env_penalty.
        Max 6 fields: temperature_c, pressure_kpa, o2_pct,
                       fluid_medium, duration_hr, cycles.
        """
        count = 0
        for field_name in [
            "temperature_c", "pressure_kpa", "o2_pct",
            "fluid_medium", "duration_hr", "cycles",
        ]:
            if getattr(self, field_name) is None:
                count += 1
        return count

    def get_missing_field_names(self) -> List[str]:
        """Return names of missing (None) environment fields."""
        missing = []
        for field_name in [
            "temperature_c", "pressure_kpa", "o2_pct",
            "fluid_medium", "duration_hr", "cycles",
        ]:
            if getattr(self, field_name) is None:
                missing.append(field_name)
        return missing


class ParsedQuery(BaseModel):
    """Augmented query carrying environment fields and intent metadata.

    Produced by the query parser (Sonnet) and validated by the
    intent guardrail (mira.intent). Consumed by confidence calculator,
    batch safety gate, and heritage veto engine.

    Compliance: SWE-032, SWE-033
    """

    model_config = {"extra": "forbid"}

    raw_query: str = Field(..., min_length=1, description="Original user query")
    intent: str = Field(
        "general_search", description="Resolved intent classification"
    )
    safety_context: SafetyContext = Field(
        SafetyContext.GENERAL, description="Detected safety context"
    )
    environment: EnvironmentSpec = Field(
        default_factory=EnvironmentSpec, description="Query environment specification"
    )
    material_key: Optional[str] = Field(
        None, description="Target material identifier"
    )
    filters: Dict[str, Any] = Field(
        default_factory=dict, description="Typed query filters"
    )
    sonnet_intent: Optional[str] = Field(
        None, description="Intent from Sonnet (primary)"
    )
    heuristic_intent: Optional[str] = Field(
        None, description="Intent from deterministic IntentClassifier"
    )
    batch_mode: bool = Field(
        False, description="True if this query is part of a batch"
    )


# =============================================================================
# Evidence & Data Quality Models
# =============================================================================


class EvidenceRow(BaseModel):
    """Single evidence record for confidence counting.

    Each evidence row represents one data point supporting a
    material recommendation. The dirty_flag indicates whether
    the record contains non-typed data.

    Compliance: SWE-013, SWE-032
    """

    model_config = {"extra": "forbid"}

    record_id: str = Field(..., min_length=1, description="Unique record identifier")
    source: str = Field(
        "UNKNOWN", description="Data source (MAPTIS, GRANTA, BOK, etc.)"
    )
    data_class: str = Field(
        "derived", description="Data provenance class (direct_test, standard_table, derived)"
    )
    dirty_flag: bool = Field(
        False, description="True if record contains non-typed data"
    )
    dirty_fields: List[str] = Field(
        default_factory=list, description="Fields with non-typed data"
    )
    raw_values: Dict[str, Any] = Field(
        default_factory=dict, description="Original raw values for dirty fields (audit trail)"
    )
    test_year: Optional[int] = Field(
        None, ge=1900, le=2100, description="Year test was performed"
    )


# =============================================================================
# Confidence Models
# =============================================================================


class PenaltyDetail(BaseModel):
    """Detail of a single confidence penalty.

    Included in ConfidenceResult.penalty_details for human-readable
    penalty breakdown and Decision Lineage audit.

    Compliance: SWE-033
    """

    model_config = {"extra": "forbid"}

    penalty_type: str = Field(
        ..., description="Penalty type: unknown_env, staleness, sparse_evidence, dirty_data, heritage_conflict"
    )
    penalty_value: float = Field(
        ..., ge=0.0, description="Penalty amount applied"
    )
    explanation: str = Field(
        ..., description="Human-readable explanation of penalty"
    )


class ConfidenceResult(BaseModel):
    """Result of confidence calculation per BuildSpec Section 2.

    Contains the score, full penalty breakdown, gate action,
    and explanation. This entire object is stored in the
    immutable Decision Lineage artifact.

    Compliance: SWE-013, SWE-033, NASA-STD-8739.8B
    """

    model_config = {"extra": "forbid"}

    score: float = Field(..., ge=0.0, le=1.0, description="Confidence score 0.0-1.0")
    penalties: Dict[str, float] = Field(
        ..., description="Penalty name -> applied value"
    )
    penalty_details: List[PenaltyDetail] = Field(
        default_factory=list, description="Detailed penalty breakdown"
    )
    gate_action: GateAction = Field(
        ..., description="PASS | CLARIFY | REFUSE"
    )
    safety_critical: bool = Field(
        ..., description="True if O2/H2/cryo/high-pressure detected"
    )
    explanation: str = Field(
        ..., description="Human-readable penalty breakdown"
    )


# =============================================================================
# Dirty Data & Filter Relaxation Models
# =============================================================================


class DirtyDataResult(BaseModel):
    """Result of dirty data classification for a record set.

    Compliance: SWE-032
    """

    model_config = {"extra": "forbid"}

    tier: DirtyDataTier = Field(..., description="Dirty data tier classification")
    dirty_fraction: float = Field(
        ..., ge=0.0, le=1.0, description="Fraction of dirty records"
    )
    total_records: int = Field(..., ge=0, description="Total records examined")
    dirty_records: int = Field(..., ge=0, description="Number of dirty records")
    user_message: Optional[str] = Field(
        None, description="User-facing message (for DEGRADED/REFUSE)"
    )


class RelaxationProposal(BaseModel):
    """Proposed filter relaxation per BuildSpec Section 3.4.

    Returned to the user as options, NOT applied automatically.

    Compliance: SWE-032
    """

    model_config = {"extra": "forbid"}

    field: str = Field(..., description="Which filter was relaxed")
    original_value: Any = Field(..., description="Original constraint")
    relaxed_value: Any = Field(..., description="Proposed relaxed constraint")
    relaxation_pct: float = Field(
        ..., ge=0.0, description="How much the constraint was widened (%)"
    )
    estimated_results: int = Field(
        ..., ge=0, description="Approximate result count after relaxation"
    )


# =============================================================================
# Batch Safety Gate Models
# =============================================================================


class BatchGateResult(BaseModel):
    """Result of batch safety gate check per BuildSpec Section 4.3.

    Compliance: SWE-013, NASA-STD-6016 S4.2.1, S5.1.4
    """

    model_config = {"extra": "forbid"}

    action: BatchGateAction = Field(
        ..., description="PROCEED or REFUSE"
    )
    penalty: float = Field(
        0.0, ge=0.0, description="Confidence penalty for general batch queries"
    )
    missing_fields: List[str] = Field(
        default_factory=list, description="Required fields that are missing"
    )
    safety_context: SafetyContext = Field(
        SafetyContext.GENERAL, description="Detected safety context"
    )
    reason: str = Field(
        "", description="Explanation of gate decision"
    )


# =============================================================================
# Provenance Models
# =============================================================================


class ProvenanceHashes(BaseModel):
    """Two-hash provenance scheme per BuildSpec Section 5.2.

    query_hash:    Deterministic. Same filters always produce same hash.
                   Used for cache matching and IV&V replay.
    snapshot_hash: Includes timestamp. Used for audit trail and
                   tamper detection in Decision Lineage.

    Compliance: SWE-013, NASA-STD-8739.8B
    """

    model_config = {"extra": "forbid"}

    query_hash: str = Field(
        ..., min_length=64, max_length=64, description="SHA-256 of canonicalized filters"
    )
    snapshot_hash: str = Field(
        ..., min_length=64, max_length=64, description="SHA-256 of query_hash + timestamp + records + schema"
    )
    canonical_filters: str = Field(
        ..., description="The canonicalized JSON string (for debugging/replay)"
    )
    timestamp: str = Field(
        ..., description="ISO 8601 retrieval timestamp"
    )
    record_ids: List[str] = Field(
        default_factory=list, description="Sorted record IDs in snapshot"
    )
    schema_version: str = Field(
        ..., description="Schema Dictionary version"
    )


# =============================================================================
# Heritage Veto Models
# =============================================================================


class HeritageOverride(BaseModel):
    """Heritage veto override record per BuildSpec Section 7.5.

    IMMUTABLE once created. Records an engineer's acknowledgment
    that they have reviewed a heritage failure and accept the risk.

    Compliance: NASA-STD-6016 S4.2.1, SWE-013, SWE-033
    """

    model_config = {"extra": "forbid", "frozen": True}

    override_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique override identifier"
    )
    material_key: str = Field(..., description="Material identifier")
    heritage_failure_id: str = Field(..., description="Heritage failure record ID")
    failure_environment: EnvironmentSpec = Field(
        ..., description="Environment of the heritage failure"
    )
    query_environment: EnvironmentSpec = Field(
        ..., description="Environment of the current query"
    )
    engineer_name: str = Field(..., min_length=1, description="Engineer who acknowledged")
    engineer_rationale: str = Field(
        ..., min_length=1, description="Free text: why this failure doesn't apply"
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 acknowledgment timestamp"
    )
    lineage_hash: str = Field(
        "", description="Links to parent Decision Lineage query_hash"
    )
    acknowledged: bool = Field(
        True, description="Immutable once set"
    )


class HeritageVetoResult(BaseModel):
    """Result of heritage veto check per BuildSpec Section 7.2.

    Compliance: NASA-STD-6016 S4.2.1, SWE-013, SWE-033
    """

    model_config = {"extra": "forbid"}

    vetoed: bool = Field(
        False, description="True if heritage veto applies"
    )
    veto_type: Optional[HeritageVetoType] = Field(
        None, description="SAFETY_CRITICAL or NON_SAFETY"
    )
    heritage_failure_ids: List[str] = Field(
        default_factory=list, description="Matching heritage failure record IDs"
    )
    requires_acknowledgment: bool = Field(
        False, description="True for safety-critical vetoes"
    )
    rank_penalty: float = Field(
        0.0, ge=0.0, description="Rank penalty for non-safety vetoes"
    )
    envelope_match_details: Dict[str, Any] = Field(
        default_factory=dict, description="Temperature/pressure/media overlap details"
    )


# =============================================================================
# Intent Guardrail Models
# =============================================================================


class IntentDisagreement(BaseModel):
    """Record of intent classifier disagreement per BuildSpec Section 6.2.

    Logged in Decision Lineage when Sonnet and the deterministic
    IntentClassifier produce conflicting intent classifications.

    Compliance: SWE-032, SWE-033
    """

    model_config = {"extra": "forbid"}

    sonnet_intent: str = Field(
        ..., description="Intent from Sonnet (primary classifier)"
    )
    heuristic_intent: str = Field(
        ..., description="Intent from deterministic IntentClassifier"
    )
    chosen_intent: str = Field(
        ..., description="The more conservative classification (winner)"
    )
    penalty_applied: float = Field(
        0.05, description="Confidence penalty for disagreement"
    )
    explanation: str = Field(
        ..., description="Why this classification was chosen"
    )


# =============================================================================
# Schema Validation Models
# =============================================================================


class SchemaChange(BaseModel):
    """A single schema change detected per BuildSpec Section 8.2.

    Compliance: SWE-032, NASA-STD-8739.8B
    """

    model_config = {"extra": "forbid"}

    field_name: str = Field(..., description="Affected field name")
    change_type: SchemaChangeType = Field(..., description="Type of change")
    old_value: Optional[str] = Field(
        None, description="Previous type/name (for TYPE_CHANGE/NAME_CHANGE)"
    )
    new_value: Optional[str] = Field(
        None, description="New type/name (for TYPE_CHANGE/NAME_CHANGE)"
    )
    severity: str = Field(
        ..., description="FAIL or WARN"
    )

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        if v not in ("FAIL", "WARN"):
            raise ValueError(f"severity must be FAIL or WARN, got '{v}'")
        return v


class SchemaValidationResult(BaseModel):
    """Result of schema validation comparison per BuildSpec Section 8.2.

    Compliance: SWE-032, NASA-STD-8739.8B
    """

    model_config = {"extra": "forbid"}

    passed: bool = Field(..., description="True if no FAIL-severity changes")
    schema_version: str = Field(..., description="Current schema version")
    changes: List[SchemaChange] = Field(
        default_factory=list, description="All detected changes"
    )
    requires_faiss_rebuild: bool = Field(
        False, description="True if changes require FAISS rebuild"
    )
    requires_regression: bool = Field(
        False, description="True if changes require 50-query regression"
    )


# =============================================================================
# Decision Lineage (Root Artifact)
# =============================================================================


class DecisionLineage(BaseModel):
    """Immutable decision artifact per BuildSpec, tying all items together.

    Every query through MIRA v4 produces a DecisionLineage record.
    This record is the audit trail for IV&V review and includes
    the complete penalty breakdown, provenance hashes, and all
    gate decisions.

    WARNING: This artifact is IMMUTABLE once created. It must be
    stored as-is for compliance with NASA-STD-8739.8B.

    Compliance: SWE-013, SWE-033, NASA-STD-8739.8B
    """

    model_config = {"extra": "forbid", "frozen": True}

    lineage_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique lineage identifier"
    )
    query_hash: str = Field(
        ..., description="Deterministic query hash (from provenance)"
    )
    snapshot_hash: str = Field(
        ..., description="Snapshot hash with timestamp (from provenance)"
    )
    parsed_query: ParsedQuery = Field(
        ..., description="The parsed query with environment and intent"
    )
    confidence: ConfidenceResult = Field(
        ..., description="Full confidence calculation result"
    )
    batch_gate: Optional[BatchGateResult] = Field(
        None, description="Batch safety gate result (if batch mode)"
    )
    dirty_data_tier: Optional[DirtyDataTier] = Field(
        None, description="Dirty data classification"
    )
    dirty_data_result: Optional[DirtyDataResult] = Field(
        None, description="Full dirty data analysis"
    )
    heritage_veto: Optional[HeritageVetoResult] = Field(
        None, description="Heritage veto check result"
    )
    intent_disagreement: Optional[IntentDisagreement] = Field(
        None, description="Intent classifier disagreement record"
    )
    heritage_overrides: List[HeritageOverride] = Field(
        default_factory=list, description="Engineer override records"
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 lineage creation timestamp"
    )
    schema_version: str = Field(
        ..., description="Schema Dictionary version at query time"
    )
