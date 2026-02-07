#!/usr/bin/env python3
"""
Module: Compatibility Models
Purpose: compatibility_models

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

# Re-export everything from common.models.compatibility
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
