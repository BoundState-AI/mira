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

Compliance: SWE-013, NASA-STD-6016
Safety Critical: True
"""

from __future__ import annotations

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

__all__ = [
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
]
