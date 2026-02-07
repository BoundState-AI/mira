#!/usr/bin/env python3
"""
Module:   Init  
Purpose: H2 Knowledge Twin Package

BoundState AI 2025
Version: 3.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: False
"""

# New simplified engine (recommended)
from .engine_simple import H2Engine, H2Result, Verdict, query as h2_query

# Aliases module
from .aliases import get_canonical_name, normalize, CANONICAL_NAMES

# Legacy imports (deprecated - will be removed)
from .query import H2Query, H2Response
from .rules import RuleGate, RuleEngine
from .engine import H2DecisionEngine

__all__ = [
    # New simplified API
    "H2Engine",
    "H2Result",
    "Verdict",
    "h2_query",
    "get_canonical_name",
    "normalize",
    "CANONICAL_NAMES",
    # Legacy (deprecated)
    "H2Query",
    "H2Response",
    "RuleGate",
    "RuleEngine",
    "H2DecisionEngine",
]
