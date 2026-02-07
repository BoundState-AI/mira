#!/usr/bin/env python3
"""
Module:   Init  
Purpose: MUA v6 Components - Phase 1-5.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013 (Traceability), SWE-032 (Data validation), SWE-033 (Safety)
Safety Critical: True
"""

from mira.mua.v6.material_identity import (
    MaterialIdentity,
    MaterialCandidate,
    ResolutionMethod,
    ConfidenceLevel,
    resolve_material_identity,
)

from mira.mua.v6.maptis_test_data import (
    TestDataCurrency,
    TestEnvelope,
    FlammabilityTestResult,
    TestDataStatus,
    query_maptis_test_data,
    query_maptis_test_data_bulk,
)

from mira.mua.v6.enriched_search import (
    FAMILY_MAP,
    FAMILY_MAP_REVERSE,
    SUPPORTING_DETERMINATIONS,
    CONFLICTING_DETERMINATIONS,
    EnrichedMUAResult,
    EnrichedSearchResults,
    EnrichedMUASearch,
    search_enriched_precedents,
)

from mira.mua.v6.envelope_matching import (
    OverlapStatus,
    DimensionCheck,
    EnvelopeOverlapResult,
    compute_envelope_overlap,
)

from mira.mua.v6.decision_engine import (
    GenerationDecision,
    DecisionResult,
    MUADecisionEngine,
)

from mira.mua.v6.logic_validator import (
    RationaleValidationResult,
    LogicValidator,
)

__all__ = [
    # Material Identity (Phase 1A)
    "MaterialIdentity",
    "MaterialCandidate",
    "ResolutionMethod",
    "ConfidenceLevel",
    "resolve_material_identity",
    # Test Data (Phase 1B)
    "TestDataCurrency",
    "TestEnvelope",
    "FlammabilityTestResult",
    "TestDataStatus",
    "query_maptis_test_data",
    "query_maptis_test_data_bulk",
    # Enriched Search (Phase 2)
    "FAMILY_MAP",
    "FAMILY_MAP_REVERSE",
    "SUPPORTING_DETERMINATIONS",
    "CONFLICTING_DETERMINATIONS",
    "EnrichedMUAResult",
    "EnrichedSearchResults",
    "EnrichedMUASearch",
    "search_enriched_precedents",
    # Envelope Matching (Phase 3)
    "OverlapStatus",
    "DimensionCheck",
    "EnvelopeOverlapResult",
    "compute_envelope_overlap",
    # Decision Engine (Phase 4)
    "GenerationDecision",
    "DecisionResult",
    "MUADecisionEngine",
    # Logic Validator (Phase 5)
    "RationaleValidationResult",
    "LogicValidator",
]

__safety_critical__ = True
