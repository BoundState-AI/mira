#!/usr/bin/env python3
"""
Module: compatibility_models
Purpose: Core Pydantic models for H2/O2 Knowledge Twins compatibility assessment

Copyright (c) 2025 BoundState Inc. All Rights Reserved.
Classification: BoundState Proprietary

Author: Dr. Joseph N. Wilde, Founder, BoundState Inc.
Created: 2025-02-XX
Equipment: Personal hardware, personal funding, personal API accounts

Development tools: Claude (Anthropic), Fran ChatGPT (OpenAI), Grok (xAI)

Compliance: SWE-032, SWE-033, NASA-STD-6016, NASA-STD-6001B
Safety Critical: True

Location: common/models/compatibility.py (shared by MIRA and ATHENA)

CRITICAL CONSTRAINTS (CC DO NOT LIST):
- DO NOT infer gas_type from material_name or free-text fields
- DO NOT assume envelope fields are present (they're usually NULL in MAPTIS)
- DO NOT use material_name for identity matching (use material_key only)
- DO NOT infer material_family_key at runtime from names
- DO NOT generate narrator text with invented facts (template assembly only)
- DO NOT hard-code scoring weights in engine code (must come from versioned config)
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Core Enums
# ---------------------------------------------------------------------------


class GasType(str, Enum):
    """Gas type for compatibility assessment."""

    H2 = "H2"
    O2 = "O2"


class CompatibilityClass(str, Enum):
    """Compatibility classification verdict."""

    COMPATIBLE = "compatible"
    MARGINAL = "marginal"
    INCOMPATIBLE = "incompatible"
    INSUFFICIENT_DATA = "insufficient_data"


class Phase(str, Enum):
    """Physical phase of the gas/fluid.

    REQUIRED: MAPTIS often lacks phase information, so UNKNOWN must be supported.
    """

    GASEOUS = "gaseous"
    LIQUID = "liquid"
    SUPERCRITICAL = "supercritical"
    UNKNOWN = "unknown"


class DataClass(str, Enum):
    """Data provenance classification for evidence items.

    Trust hierarchy (highest to lowest):
    1. DIRECT_TEST - MAPTIS / lab report with actual test data
    2. STANDARD_TABLE - Published standard table entry (NASA-STD-6001B, etc.)
    3. BOK_PRECEDENT - Explicit BOK statement with traceable source
    4. DERIVED - Extracted/normalized from text (lowest trust)
    """

    DIRECT_TEST = "direct_test"
    STANDARD_TABLE = "standard_table"
    BOK_PRECEDENT = "bok_precedent"
    DERIVED = "derived"


class PropertyKey(str, Enum):
    """Validated property keys for scoring.

    Properties are grouped by service type but may overlap.
    """

    # O2 service properties
    FLAMMABILITY_RATING = "flammability_rating"
    OXYGEN_CONCENTRATION_PCT = "oxygen_concentration_pct"
    TEST_PRESSURE_PSIA = "test_pressure_psia"
    TEMP_MIN_F = "temp_min_f"
    TEMP_MAX_F = "temp_max_f"
    IGNITION_ENERGY_J = "ignition_energy_j"
    MECHANICAL_IMPACT_FT_LBS = "mechanical_impact_ft_lbs"
    AUTOGENOUS_IGNITION_TEMP_F = "autogenous_ignition_temp_f"

    # H2 service properties
    H2_EMBRITTLEMENT_CLASS = "h2_embrittlement_class"
    FRACTURE_TOUGHNESS_KSI_SQRT_IN = "fracture_toughness_ksi_sqrt_in"
    ELONGATION_PCT_AT_TEMP = "elongation_pct_at_temp"
    H2_PERMEATION_RATE = "h2_permeation_rate"

    # MAPTIS crack_growth (definitive H2 identity evidence)
    CRACK_GROWTH_FLUID = "crack_growth_fluid"
    CRACK_GROWTH_PRESSURE_PSIA = "crack_growth_pressure_psia"
    CRACK_GROWTH_TEMPERATURE_F = "crack_growth_temperature_f"


class MaterialFamilyKey(str, Enum):
    """Material family classification.

    CRITICAL: Assigned at ingestion time via validated semantic tagging,
    NOT inferred at runtime from material names.
    """

    AUSTENITIC_STAINLESS = "austenitic_stainless"
    FERRITIC_STAINLESS = "ferritic_stainless"
    MARTENSITIC_STAINLESS = "martensitic_stainless"
    NICKEL_ALLOY = "nickel_alloy"
    ALUMINUM_ALLOY = "aluminum_alloy"
    COPPER_ALLOY = "copper_alloy"
    TITANIUM_ALLOY = "titanium_alloy"
    CARBON_STEEL = "carbon_steel"
    HIGH_STRENGTH_STEEL = "high_strength_steel"
    FLUOROPOLYMER = "fluoropolymer"
    ELASTOMER = "elastomer"
    THERMOPLASTIC = "thermoplastic"
    THERMOSET = "thermoset"
    CERAMIC = "ceramic"
    COMPOSITE = "composite"
    UNKNOWN = "unknown"  # If unknown, family bonus = 0 and warning emitted


# ---------------------------------------------------------------------------
# Valid Material Type Keys (MAPTIS)
# ---------------------------------------------------------------------------


VALID_MATERIAL_TYPE_KEYS = {235, 239, 723, 229, 231, 232, 233}
"""
Material type key mapping (from MAPTIS):
235: Metal
239: Polymer
723: Elastomer
229: Ceramic
231: Composite
232: Coating
233: Adhesive
"""


# ---------------------------------------------------------------------------
# Property Evidence (Atomic Evidence Unit)
# ---------------------------------------------------------------------------


class PropertyEvidence(BaseModel):
    """Single property measurement with full provenance.

    This is the atomic unit of evidence - each measurement must have
    a traceable source and data class for audit compliance.
    """

    model_config = {"extra": "forbid", "populate_by_name": True}

    property_key: PropertyKey
    value_numeric: Optional[float] = None
    value_text: Optional[str] = None
    units: Optional[str] = None

    test_method: Optional[str] = None
    test_temp_f: Optional[float] = None
    test_pressure_psia: Optional[float] = None

    source_ref: str
    data_class: DataClass
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def at_least_one_value(self) -> "PropertyEvidence":
        """Ensure at least one value field is populated."""
        if self.value_numeric is None and (
            self.value_text is None or str(self.value_text).strip() == ""
        ):
            raise ValueError("PropertyEvidence requires value_numeric or value_text")
        return self

    def get_display_value(self) -> str:
        """Get human-readable display value with units."""
        if self.value_numeric is not None:
            return f"{self.value_numeric} {self.units or ''}".strip()
        return str(self.value_text).strip()


# ---------------------------------------------------------------------------
# Environment Envelope (Nullable, Auditable)
# ---------------------------------------------------------------------------


class EnvironmentEnvelope(BaseModel):
    """Operating envelope for compatibility assessment.

    CRITICAL: MAPTIS frequently lacks temperature/pressure data.
    ALL envelope fields MUST support nulls without guessing or interpolation.
    """

    model_config = {"extra": "forbid", "populate_by_name": True}

    temp_min_f: Optional[float] = None
    temp_max_f: Optional[float] = None
    pressure_min_psia: Optional[float] = None
    pressure_max_psia: Optional[float] = None
    phase: Phase = Phase.UNKNOWN
    concentration_pct: Optional[float] = None  # May be unknown in many tests

    @model_validator(mode="after")
    def ranges_are_paired(self) -> "EnvironmentEnvelope":
        """Validate that range pairs are consistent.

        Rules:
        - temp pair: both set or both None
        - pressure pair: both set or both None
        - ranges must be valid (min <= max)
        """
        # Temperature pair validation
        if (self.temp_min_f is None) ^ (self.temp_max_f is None):
            raise ValueError(
                "temp_min_f and temp_max_f must both be set or both be None"
            )
        if self.temp_min_f is not None and self.temp_max_f is not None:
            if self.temp_max_f < self.temp_min_f:
                raise ValueError("temp_max_f must be >= temp_min_f")

        # Pressure pair validation
        if (self.pressure_min_psia is None) ^ (self.pressure_max_psia is None):
            raise ValueError(
                "pressure_min_psia and pressure_max_psia must both be set or both be None"
            )
        if self.pressure_min_psia is not None and self.pressure_max_psia is not None:
            if self.pressure_max_psia < self.pressure_min_psia:
                raise ValueError("pressure_max_psia must be >= pressure_min_psia")

        # Concentration bounds validation
        if self.concentration_pct is not None:
            if self.concentration_pct < 0.0 or self.concentration_pct > 100.0:
                raise ValueError(
                    "concentration_pct must be within [0,100] when provided"
                )

        return self


class EnvelopeEvidence(BaseModel):
    """Provenance for envelope fields themselves.

    Tracks where the envelope constraints came from for audit trail.
    """

    model_config = {"extra": "forbid", "populate_by_name": True}

    data_class: DataClass
    source_ref: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# CompatibilityRecord (Index Row)
# ---------------------------------------------------------------------------


class CompatibilityRecord(BaseModel):
    """Single compatibility data point stored in BOK index.

    This is the core record stored in the FAISS twin indices.
    Each record represents a material-environment compatibility data point.
    """

    model_config = {"extra": "forbid", "populate_by_name": True}

    record_id: str

    # Identity fields (validated, not string-matched)
    material_key: str = Field(
        description="Canonical identity: 'MAPTIS:{int}' - NEVER use material_name"
    )
    material_name: str = Field(description="Display only - NOT used for decisions")
    material_type_key: int
    material_family_key: Optional[MaterialFamilyKey] = None

    gas_type: GasType
    environment: EnvironmentEnvelope
    environment_evidence: Optional[EnvelopeEvidence] = None

    compatibility: CompatibilityClass
    reason: str
    mitigation: Optional[str] = None

    properties: List[PropertyEvidence] = Field(default_factory=list)

    standard_ref: str
    test_report_id: Optional[str] = None
    source: str

    @field_validator("material_type_key")
    @classmethod
    def validate_material_type_key(cls, v: int) -> int:
        """Validate material_type_key against known MAPTIS types."""
        if v not in VALID_MATERIAL_TYPE_KEYS:
            raise ValueError(f"Invalid material_type_key: {v}")
        return v

    def get_property(self, key: PropertyKey) -> Optional[PropertyEvidence]:
        """Get a property by key from the properties list."""
        for p in self.properties:
            if p.property_key == key:
                return p
        return None

    def has_direct_evidence(self) -> bool:
        """Check if record has at least one DIRECT_TEST or STANDARD_TABLE property.

        CRITICAL: COMPATIBLE verdict requires this to return True.
        """
        return any(
            p.data_class in (DataClass.DIRECT_TEST, DataClass.STANDARD_TABLE)
            for p in self.properties
        )


# ---------------------------------------------------------------------------
# Scored Evidence Item (Output / Audit Trail)
# ---------------------------------------------------------------------------


class ScoredEvidenceItem(BaseModel):
    """Evidence item with full scoring breakdown for SWE-033 audit trail.

    Every score component must be traceable to support deterministic audits.
    """

    model_config = {"extra": "forbid", "populate_by_name": True}

    property_key: PropertyKey
    raw_value: str
    normalized_score: float = Field(ge=0.0, le=1.0)
    weight: float = Field(ge=0.0, le=1.0)
    contribution: float = Field(ge=0.0, le=1.0)  # = normalized_score * weight

    source_ref: str
    test_method: Optional[str] = None
    data_class: DataClass
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)


# ---------------------------------------------------------------------------
# CompatibilityAssessment (Output)
# ---------------------------------------------------------------------------


class CompatibilityAssessment(BaseModel):
    """Result of compatibility query with full audit trail.

    This is the response model for the compatibility assessment API.
    All verdicts must be traceable to evidence.
    """

    model_config = {"extra": "forbid", "populate_by_name": True}

    material_key: str
    material_name: str
    gas_type: GasType
    query_environment: EnvironmentEnvelope

    verdict: CompatibilityClass
    confidence_score: float = Field(ge=0.0, le=1.0)

    evidence: List[ScoredEvidenceItem]
    total_score: float = Field(ge=0.0, le=1.0)

    has_direct_evidence: bool  # COMPATIBLE requires this to be True

    warnings: List[str] = Field(default_factory=list)
    mitigations: List[str] = Field(default_factory=list)

    precedent_records: List[str] = Field(default_factory=list)

    reasoning: str  # Template-assembled only; NO invented facts

    scoring_profile_version: str
    envelope_overlap_config_version: str


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------


__all__ = [
    # Enums
    "GasType",
    "CompatibilityClass",
    "Phase",
    "DataClass",
    "PropertyKey",
    "MaterialFamilyKey",
    # Constants
    "VALID_MATERIAL_TYPE_KEYS",
    # Evidence models
    "PropertyEvidence",
    "EnvelopeEvidence",
    # Environment models
    "EnvironmentEnvelope",
    # Record models
    "CompatibilityRecord",
    # Scoring models
    "ScoredEvidenceItem",
    # Assessment output
    "CompatibilityAssessment",
]
