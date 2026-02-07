#!/usr/bin/env python3
"""
Module:   Init  
Purpose: [Automatically migrated - needs manual review]

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: False
"""

from __future__ import annotations

__version__ = "1.0.0"
__author__ = "Dr. Joseph Wilde / BoundState AI, Claude (Anthropic), Fran (OpenAI), Grok (xAI)"

from mira.precedent_engine.models.enums import (
    DeviationType,
    ProgramFamily,
    PrecedentAdequacyLevel,
    EquivalenceMode,
    LLMContribution,
)
from mira.precedent_engine.models.raw import RawMUARecord
from mira.precedent_engine.models.enriched import EnrichedMUA
from mira.precedent_engine.models.precedent import (
    PrecedentMatch,
    PrecedentStatistics,
    PrecedentRetrievalResult,
)
from mira.precedent_engine.models.candidate import (
    RationaleSegment,
    CandidateMUA,
    EngineResult,
)
from mira.precedent_engine.models.config import (
    MaterialEquivalenceConfig,
    EnvironmentEquivalenceConfig,
    DeviationEquivalenceConfig,
    ProgramEquivalenceConfig,
    ScoringWeights,
    PrecedentEquivalenceConfig,
    PrecedentAdequacyConfig,
    SynthesisConstraints,
    EngineConfig,
)
from mira.precedent_engine.core.precedent_engine import PrecedentEngine
from mira.precedent_engine.core.runner import MUAPrecedentRunner
from mira.precedent_engine.core.storage import VectorStore
import uuid

__all__ = [
    # Version info
    "__version__",
    "__author__",
    # Enums
    "DeviationType",
    "ProgramFamily",
    "PrecedentAdequacyLevel",
    "EquivalenceMode",
    "LLMContribution",
    # Models
    "RawMUARecord",
    "EnrichedMUA",
    "PrecedentMatch",
    "PrecedentStatistics",
    "PrecedentRetrievalResult",
    "RationaleSegment",
    "CandidateMUA",
    "EngineResult",
    # Config
    "MaterialEquivalenceConfig",
    "EnvironmentEquivalenceConfig",
    "DeviationEquivalenceConfig",
    "ProgramEquivalenceConfig",
    "ScoringWeights",
    "PrecedentEquivalenceConfig",
    "PrecedentAdequacyConfig",
    "SynthesisConstraints",
    "EngineConfig",
    # Core
    "PrecedentEngine",
    "MUAPrecedentRunner",
    "VectorStore",
]
