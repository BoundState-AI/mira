"""
BoundState Common Models.

Shared Pydantic models for MIRA and ATHENA.
"""
from __future__ import annotations

from common.models.compatibility import (
    GasType,
    CompatibilityClass,
    Phase,
    DataClass,
    PropertyKey,
    MaterialFamilyKey,
    VALID_MATERIAL_TYPE_KEYS,
    PropertyEvidence,
    EnvelopeEvidence,
    EnvironmentEnvelope,
    CompatibilityRecord,
    ScoredEvidenceItem,
    CompatibilityAssessment,
)

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
