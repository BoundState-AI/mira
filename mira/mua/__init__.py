#!/usr/bin/env python3
"""
Module:   Init  
Purpose: MUA domain: models, historic retrieval, and generator.

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

from .service import generate_mua
from .api_models import (
    EnvironmentSpec,
    MaterialRating,
    MitigationClause,
    MuaGenerationRequest,
    MuaGenerationResponse,
    MuaRecord,
)

__all__ = [
    # Public API (STABLE)
    "generate_mua",
    "MuaGenerationRequest",
    "MuaGenerationResponse",
    "MuaRecord",
    "EnvironmentSpec",
    "MaterialRating",
    "MitigationClause",
    # Internal modules
    "models",
    "historic_retrieval",
    "historic_mua_simple",
    "mua_generator",
    "retrieval",
]
