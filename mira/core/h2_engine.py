#!/usr/bin/env python3
"""
Module: H2 Engine
Purpose: Wrapper module for H2 compatibility engine.

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

from mira.h2.engine import (
    HydrogenCompatibilityEngine,
    get_h2_engine,
    evaluate_h2_compatibility,
)

__all__ = [
    "HydrogenCompatibilityEngine",
    "get_h2_engine",
    "evaluate_h2_compatibility",
]
