#!/usr/bin/env python3
"""
Module:   Init  
Purpose: Hydrogen compatibility domain logic for MIRA.

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

from .engine import (
    HydrogenCompatibilityEngine,
    get_h2_engine,
    evaluate_h2_compatibility,
)
from .models import (
    HydrogenPhase,
    H2CompatibilityRequest,
    H2CompatibilityResponse,
    ConditionOptionResponse,
    H2ConditionLookupResponse,
    H2ConditionAliasRecord,
    H2ConditionAliasListResponse,
    H2ConditionAliasVerifyRequest,
    H2ConditionAliasVerifyResponse,
)

__all__ = [
    "engine",
    "models",
    # Class-based engine
    "HydrogenCompatibilityEngine",
    "get_h2_engine",
    # Clean wrapper function
    "evaluate_h2_compatibility",
    # Request/Response models
    "HydrogenPhase",
    "H2CompatibilityRequest",
    "H2CompatibilityResponse",
    "ConditionOptionResponse",
    "H2ConditionLookupResponse",
    "H2ConditionAliasRecord",
    "H2ConditionAliasListResponse",
    "H2ConditionAliasVerifyRequest",
    "H2ConditionAliasVerifyResponse",
]
