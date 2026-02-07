#!/usr/bin/env python3
"""
Module: O2 Engine
Purpose: Wrapper module for O2 compatibility engine.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: True
"""

from mira.o2.engine import (
    OxygenCompatibilityEngine,
    evaluate_o2_compatibility,
)

__all__ = [
    "OxygenCompatibilityEngine",
    "evaluate_o2_compatibility",
]
