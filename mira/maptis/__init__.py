#!/usr/bin/env python3
"""
Module:   Init  
Purpose: MAPTIS-specific data models, repositories, and helpers.

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

from .repository import (
    # Core types
    MaterialFamily,
    MaterialRecord,
    # O2 safety exports
    get_material_for_o2,
    O2_PROHIBITED_FAMILIES,
    O2_RESTRICTED_FAMILIES,
    get_o2_family_rule,
    # H2 safety exports
    get_material_for_h2,
    H2_APPROVED_FAMILIES,
    H2_CAUTION_FAMILIES,
    H2_PROHIBITED_FAMILIES,
    H2_HIGH_STRENGTH_THRESHOLD_KSI,
    H2_PRESSURE_THRESHOLD_PSIA,
    get_h2_family_rule,
)

__all__ = [
    "models",
    "repository",
    "material_resolver",
    "ratings",
    "sync",
    # Core types
    "MaterialFamily",
    "MaterialRecord",
    # O2 safety exports
    "get_material_for_o2",
    "O2_PROHIBITED_FAMILIES",
    "O2_RESTRICTED_FAMILIES",
    "get_o2_family_rule",
    # H2 safety exports
    "get_material_for_h2",
    "H2_APPROVED_FAMILIES",
    "H2_CAUTION_FAMILIES",
    "H2_PROHIBITED_FAMILIES",
    "H2_HIGH_STRENGTH_THRESHOLD_KSI",
    "H2_PRESSURE_THRESHOLD_PSIA",
    "get_h2_family_rule",
]
