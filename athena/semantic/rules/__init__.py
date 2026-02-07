#!/usr/bin/env python3
"""
Module:   Init  
Purpose: ATHENA Semantic Rules.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032
Safety Critical: True
"""

from athena.semantic.rules.base import EXACT_RULES, PATTERN_RULES
from athena.semantic.rules.h2 import H2_EXACT_RULES, H2_PATTERN_RULES
from athena.semantic.rules.o2 import O2_EXACT_RULES, O2_PATTERN_RULES
from athena.semantic.rules.composition import COMPOSITION_RULES

__all__ = [
    "EXACT_RULES",
    "PATTERN_RULES",
    "H2_EXACT_RULES",
    "H2_PATTERN_RULES",
    "O2_EXACT_RULES",
    "O2_PATTERN_RULES",
    "COMPOSITION_RULES",
]
__safety_critical__ = True
