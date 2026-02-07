#!/usr/bin/env python3
"""
Module: Config
Purpose: [Automatically migrated - needs manual review]

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-033, NASA-STD-6016
Safety Critical: True
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from mira.precedent_engine.models.enums import EquivalenceMode, PrecedentAdequacyLevel, ProgramFamily
import uuid


class MaterialEquivalenceConfig(BaseModel):
    """
    How 'same material' is defined for precedent matching.

    IMPORTANT: Name-based equivalence (when material_key is missing) SHALL NOT
    produce Tier 1 matches. This fallback is advisory only per Addendum B.
    """

    model_config = {"extra": "forbid", "frozen": True}

    mode: EquivalenceMode = EquivalenceMode.STRICT
    require_same_material_key: bool = True
    allow_family_equivalence_tier2: bool = False
    family_groups: dict[str, list[str]] = Field(default_factory=dict)


class EnvironmentEquivalenceConfig(BaseModel):
    """
    Environment equivalence using absolute temperature (Rankine) for scaling.

    Temperature tolerance is expressed as a percentage of absolute temperature
    to properly handle cryogenic ranges where Fahrenheit percentages are meaningless.
    """

    model_config = {"extra": "forbid", "frozen": True}

    mode: EquivalenceMode = EquivalenceMode.STRICT

    # Temperature tolerance as percentage of absolute temp (Rankine)
    temp_tolerance_pct_tier1: float = Field(default=0.0, ge=0.0, le=100.0)
    temp_tolerance_pct_tier2: float = Field(default=5.0, ge=0.0, le=100.0)

    # Pressure tolerance in psia
    pressure_tolerance_psia_tier1: float = Field(default=0.0, ge=0.0)
    pressure_tolerance_psia_tier2: float = Field(default=100.0, ge=0.0)

    # O2 percentage tolerance
    o2_tolerance_pct_tier1: float = Field(default=0.0, ge=0.0)
    o2_tolerance_pct_tier2: float = Field(default=5.0, ge=0.0)

    require_same_location_class: bool = True
    require_same_media_tier1: bool = True
    require_same_media_tier2: bool = False


class DeviationEquivalenceConfig(BaseModel):
    """
    Deviation type and severity matching rules.

    Flammability ratings use a scale (A-D, X) where lower values indicate
    better fire resistance. The gap between query and candidate ratings
    determines tier eligibility.
    """

    model_config = {"extra": "forbid", "frozen": True}

    mode: EquivalenceMode = EquivalenceMode.STRICT
    require_same_deviation_types_tier1: bool = True
    allow_subset_deviation_types_tier2: bool = True

    flammability_scale: dict[str, int] = Field(
        default_factory=lambda: {"A": 0, "B": 1, "C": 2, "D": 3, "X": 4}
    )
    untested_ratings: set[str] = Field(default_factory=lambda: {"U", "NT"})

    max_flammability_gap_tier1: int = 0
    max_flammability_gap_tier2: int = 1
    untested_blocks_tier1: bool = True


class ProgramEquivalenceConfig(BaseModel):
    """
    Cross-program precedent use policy.

    Different programs have varying levels of compatibility based on
    shared requirements, environments, and engineering heritage.
    """

    model_config = {"extra": "forbid", "frozen": True}

    mode: EquivalenceMode = EquivalenceMode.ADVISORY

    compatibility_weights: dict[tuple[ProgramFamily, ProgramFamily], float] = Field(
        default_factory=lambda: {
            (ProgramFamily.ISS, ProgramFamily.ORION_ARTEMIS): 0.85,
            (ProgramFamily.SHUTTLE, ProgramFamily.ISS): 0.75,
            (ProgramFamily.SHUTTLE, ProgramFamily.ORION_ARTEMIS): 0.70,
            (ProgramFamily.COMMERCIAL_CREW, ProgramFamily.ORION_ARTEMIS): 0.80,
        }
    )
    default_cross_program_weight: float = Field(default=0.6, ge=0.0, le=1.0)
    same_program_weight: float = Field(default=1.0, ge=0.0, le=1.0)


class ScoringWeights(BaseModel):
    """
    Weights for similarity score components.

    Weights must sum to 1.0. The similarity score is computed as:
    score = w_material * material_sim + w_environment * env_sim + w_deviation * dev_sim
    """

    model_config = {"extra": "forbid", "frozen": True}

    material: float = Field(default=0.4, ge=0.0, le=1.0)
    environment: float = Field(default=0.4, ge=0.0, le=1.0)
    deviation: float = Field(default=0.2, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> "ScoringWeights":
        """Validate that weights sum to 1.0."""
        total = self.material + self.environment + self.deviation
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"Weights must sum to 1.0, got {total}")
        return self


class PrecedentEquivalenceConfig(BaseModel):
    """
    Top-level equivalence configuration.

    This aggregates all dimension-specific equivalence configs and
    cross-cutting parameters like recency weighting.
    """

    model_config = {"extra": "forbid", "frozen": True}

    material: MaterialEquivalenceConfig = Field(default_factory=MaterialEquivalenceConfig)
    environment: EnvironmentEquivalenceConfig = Field(default_factory=EnvironmentEquivalenceConfig)
    deviation: DeviationEquivalenceConfig = Field(default_factory=DeviationEquivalenceConfig)
    program: ProgramEquivalenceConfig = Field(default_factory=ProgramEquivalenceConfig)
    weights: ScoringWeights = Field(default_factory=ScoringWeights)

    recency_half_life_years: float = Field(default=15.0, gt=0.0)


class PrecedentAdequacyConfig(BaseModel):
    """
    Thresholds for adequacy classification.

    These thresholds determine whether the precedent base is sufficient
    for auto-drafting (STRONG), drafting with warnings (MODERATE), or
    requires manual justification (INSUFFICIENT).

    IMPORTANT: These are deterministic rules. LLM is NOT involved in
    adequacy determination.
    """

    model_config = {"extra": "forbid", "frozen": True}

    # Score thresholds
    min_score_strong: float = Field(default=0.85, ge=0.0, le=1.0)
    min_score_moderate: float = Field(default=0.70, ge=0.0, le=1.0)

    # Count requirements
    min_count_strong: int = Field(default=3, ge=1)
    min_count_moderate: int = Field(default=1, ge=1)

    # Diversity requirements
    min_unique_sources_strong: int = Field(default=2, ge=1)
    min_unique_sources_moderate: int = Field(default=1, ge=1)

    # Rejection handling
    max_rejected_fraction_strong: float = Field(default=0.0, ge=0.0, le=1.0)
    max_rejected_fraction_moderate: float = Field(default=0.2, ge=0.0, le=1.0)

    # Tier constraints
    tier3_always_insufficient: bool = True
    tier2_max_adequacy: PrecedentAdequacyLevel = PrecedentAdequacyLevel.MODERATE


class SynthesisConstraints(BaseModel):
    """
    What the LLM narrator can and cannot do.

    These constraints enforce the boundary between acceptable synthesis
    (rephrasing, combining existing text) and forbidden generation
    (inventing data, extrapolating beyond precedent bounds).
    """

    model_config = {"extra": "forbid", "frozen": True}

    # Structural
    allow_text_rephrasing: bool = True
    allow_rationale_merging: bool = True
    max_precedents_to_merge: int = Field(default=3, ge=1, le=10)

    # Numerical bounds
    allow_numerical_extrapolation: bool = False
    allow_interpolation_within_bounds: bool = False

    # Gap handling
    require_gap_annotation: bool = True
    gap_annotation_phrase: str = "Requires additional justification and/or testing per NASA-STD-6016."

    # Hard constraints
    forbid_new_test_data: bool = True
    forbid_new_specifications: bool = True
    forbid_new_requirement_language: bool = True

    # Provenance
    require_source_citation_per_segment: bool = True


class EngineConfig(BaseModel):
    """
    Top-level engine configuration.

    This is the main configuration object passed to MUAPrecedentRunner
    and other engine components.
    """

    model_config = {"extra": "forbid"}

    # Storage
    qdrant_path: str = "qdrant_mua_db"
    collection_name: str = "mua_precedents"

    # Embedding
    embed_model_name: str = "all-MiniLM-L12-v2"
    embed_dim: int = 384

    # Search
    top_k_initial: int = 500
    score_threshold_initial: float = 0.3

    # AWS Bedrock
    aws_region: str = "us-gov-west-1"
    bedrock_model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"

    # Sub-configs
    equivalence: PrecedentEquivalenceConfig = Field(default_factory=PrecedentEquivalenceConfig)
    adequacy: PrecedentAdequacyConfig = Field(default_factory=PrecedentAdequacyConfig)
    synthesis: SynthesisConstraints = Field(default_factory=SynthesisConstraints)

    # Clustering (optional)
    enable_clustering: bool = True
    min_cluster_size: int = 10
