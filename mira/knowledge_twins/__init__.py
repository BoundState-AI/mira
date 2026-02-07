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

# Models
from .compatibility_models import (
    # Enums
    GasType,
    CompatibilityClass,
    Phase,
    DataClass,
    PropertyKey,
    MaterialFamilyKey,
    # Constants
    VALID_MATERIAL_TYPE_KEYS,
    # Evidence models
    PropertyEvidence,
    EnvelopeEvidence,
    # Environment models
    EnvironmentEnvelope,
    # Record models
    CompatibilityRecord,
    # Scoring models
    ScoredEvidenceItem,
    # Assessment output
    CompatibilityAssessment,
)

# BOK Loaders
from .bok_loaders import (
    clean_str,
    clean_float,
    canonical_maptis_material_key,
    FluidInfo,
    FluidsResolver,
    FamilyResolver,
    make_fluids_resolver_from_map,
    map_flammability_row_to_record,
    map_crack_growth_row_to_record,
    map_fluid_compatibility_row_to_record,
    maptis_rows_to_twin_records,
)

# Envelope Overlap
from .envelope_overlap import (
    EnvelopeOverlapConfig,
    DEFAULT_ENVELOPE_CONFIG,
    calculate_range_overlap,
    calculate_envelope_overlap,
)

# Scoring Profiles
from .scoring_profiles import (
    ScoringProfile,
    H2_SCORING_PROFILE,
    O2_SCORING_PROFILE,
    get_scoring_profile,
    get_hard_reject_ratings,
    get_family_bonus,
    normalize_flammability_rating,
    normalize_h2_embrittlement_class,
)

# Verdict Engine
from .verdict_engine import (
    VerdictEngine,
    compute_verdict,
    score_property,
    check_hard_rejects,
)

# Index Builder
from .index_builder import (
    H2_BOK_INDEX_CONFIG,
    O2_BOK_INDEX_CONFIG,
    create_embedding_text,
    normalize_embedding,
    TwinIndexBuilder,
    TwinIndexSearcher,
)

# Legacy BOK Loader
from .legacy_bok_loader import (
    load_legacy_h2_bok,
    load_legacy_o2_bok,
    load_all_legacy_bok,
    convert_legacy_section_to_record,
    extract_material_mentions,
    extract_temperature_mentions,
    extract_pressure_mentions,
    H2_SOURCE_DOCUMENTS,
    O2_SOURCE_DOCUMENTS,
)

# BOK Standards Extractor V6 (Vision-First)
from .bok_standards_extractor_v6 import (
    BOKStandardsExtractorV6,
    ExtractedSection,
    MaterialCompatibilityRecord,
    TestProcedureRecord,
    FlammabilityLimitRecord,
    EnvironmentSpecification,
    ContentType,
    extract_bok_pdf_v6,
    rebuild_bok_indices,
)

# H2 Knowledge Twin v2.1 (Refactored)
from .types import (
    # Enums
    Verdict,
    HEEBand,
    HEMechanism,
    EvidenceGrade,
    Phase,  # Override compatibility_models.Phase with H2-specific GH2/LH2 values
    LoadingMode,
    SpecimenType,
    ProductForm,
    WeldState,
    MaterialFamily,
    HeatTreatCondition,
    ReferenceEnvironment,
    TemperatureBehavior,
    # Constants
    HEE_BAND_THRESHOLDS,
    VALIDITY_ENVELOPE,
    NI_PREDICTOR,
    SANDIA_CODES,
    ELEVATED_TEMP_PEAK_MATERIALS,
    # Dataclasses
    Composition,
    HeatTreatment,
    StrengthData,
    LoadingRates,
    MaterialRecord,
    HydrogenEnvironment,
    LoadingState,
    Provenance,
    MetricValue,
    EvidenceObject,
    Driver,
    Constraint,
    Gap,
    RecommendedTest,
    MatchStats,
    AuditTrail,
    # Functions
    classify_hee_band,
    band_to_verdict_floor,
    get_temperature_behavior,
)
from .scoring import EnvelopeMatchScorer
from .matching import CandidateFinder
from .h2.query import H2Query, H2Response
from .h2.rules import RuleGate, RuleEngine
from .h2.engine import H2DecisionEngine


__all__ = [
    # === Models ===
    # Enums
    "GasType",
    "CompatibilityClass",
    "Phase",
    "DataClass",
    "PropertyKey",
    "MaterialFamilyKey",
    # Constants
    "VALID_MATERIAL_TYPE_KEYS",
    # Evidence models
    "PropertyEvidence",
    "EnvelopeEvidence",
    # Environment models
    "EnvironmentEnvelope",
    # Record models
    "CompatibilityRecord",
    # Scoring models
    "ScoredEvidenceItem",
    # Assessment output
    "CompatibilityAssessment",
    # === BOK Loaders ===
    "clean_str",
    "clean_float",
    "canonical_maptis_material_key",
    "FluidInfo",
    "FluidsResolver",
    "FamilyResolver",
    "make_fluids_resolver_from_map",
    "map_flammability_row_to_record",
    "map_crack_growth_row_to_record",
    "map_fluid_compatibility_row_to_record",
    "maptis_rows_to_twin_records",
    # === Envelope Overlap ===
    "EnvelopeOverlapConfig",
    "DEFAULT_ENVELOPE_CONFIG",
    "calculate_range_overlap",
    "calculate_envelope_overlap",
    # === Scoring Profiles ===
    "ScoringProfile",
    "H2_SCORING_PROFILE",
    "O2_SCORING_PROFILE",
    "get_scoring_profile",
    "get_hard_reject_ratings",
    "get_family_bonus",
    "normalize_flammability_rating",
    "normalize_h2_embrittlement_class",
    # === Verdict Engine ===
    "VerdictEngine",
    "compute_verdict",
    "score_property",
    "check_hard_rejects",
    # === Index Builder ===
    "H2_BOK_INDEX_CONFIG",
    "O2_BOK_INDEX_CONFIG",
    "create_embedding_text",
    "normalize_embedding",
    "TwinIndexBuilder",
    "TwinIndexSearcher",
    # === Legacy BOK Loader ===
    "load_legacy_h2_bok",
    "load_legacy_o2_bok",
    "load_all_legacy_bok",
    "convert_legacy_section_to_record",
    "extract_material_mentions",
    "extract_temperature_mentions",
    "extract_pressure_mentions",
    "H2_SOURCE_DOCUMENTS",
    "O2_SOURCE_DOCUMENTS",
    # === BOK Standards Extractor V6 ===
    "BOKStandardsExtractorV6",
    "ExtractedSection",
    "MaterialCompatibilityRecord",
    "TestProcedureRecord",
    "FlammabilityLimitRecord",
    "EnvironmentSpecification",
    "ContentType",
    "extract_bok_pdf_v6",
    "rebuild_bok_indices",
    # === H2 Knowledge Twin v2.1 ===
    # Enums
    "Verdict",
    "HEEBand",
    "HEMechanism",
    "EvidenceGrade",
    "LoadingMode",
    "SpecimenType",
    "ProductForm",
    "WeldState",
    "MaterialFamily",
    "HeatTreatCondition",
    "ReferenceEnvironment",
    "TemperatureBehavior",
    # Constants
    "HEE_BAND_THRESHOLDS",
    "VALIDITY_ENVELOPE",
    "NI_PREDICTOR",
    "SANDIA_CODES",
    "ELEVATED_TEMP_PEAK_MATERIALS",
    # Dataclasses
    "Composition",
    "HeatTreatment",
    "StrengthData",
    "LoadingRates",
    "MaterialRecord",
    "HydrogenEnvironment",
    "LoadingState",
    "Provenance",
    "MetricValue",
    "EvidenceObject",
    "Driver",
    "Constraint",
    "Gap",
    "RecommendedTest",
    "MatchStats",
    "AuditTrail",
    # Functions
    "classify_hee_band",
    "band_to_verdict_floor",
    "get_temperature_behavior",
    # Classes
    "EnvelopeMatchScorer",
    "CandidateFinder",
    "H2Query",
    "H2Response",
    "RuleGate",
    "RuleEngine",
    "H2DecisionEngine",
]

__version__ = "0.4.0"
