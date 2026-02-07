#!/usr/bin/env python3
"""
Module:   Init  
Purpose: ATHENA Semantic Layer.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032, SWE-033
Safety Critical: True
"""

from athena.semantic.ontology import SemanticTag
from athena.semantic.mapper import SemanticMapper
from athena.semantic.units import UnitDetector, UnitInfo
from athena.semantic.cleaner import ValueCleaner, NumericValue
from athena.semantic.materials import MaterialResolver

__all__ = [
    "SemanticTag",
    "SemanticMapper",
    "UnitDetector",
    "UnitInfo",
    "ValueCleaner",
    "NumericValue",
    "MaterialResolver",
]
__safety_critical__ = True
