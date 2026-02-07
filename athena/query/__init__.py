#!/usr/bin/env python3
"""
Module:   Init  
Purpose: ATHENA Query Interface.

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

from athena.query.engine import (
    QueryEngine,
    CompatibilityQuery,
    ExpertVerdict,
    VerdictType,
)

__all__ = [
    "QueryEngine",
    "CompatibilityQuery",
    "ExpertVerdict",
    "VerdictType",
]
__safety_critical__ = True
