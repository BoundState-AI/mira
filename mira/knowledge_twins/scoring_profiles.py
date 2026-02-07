#!/usr/bin/env python3
"""
Module: Scoring Profiles
Purpose: scoring_profiles

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032, SWE-033
Safety Critical: True
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field, field_validator, model_validator

from .compatibility_models import (
    GasType,
    MaterialFamilyKey,
    PropertyKey,
)


__all__ = [
    "ScoringProfile",
    "H2_SCORING_PROFILE",
    "O2_SCORING_PROFILE",
    "get_scoring_profile",
    "get_hard_reject_ratings",
    "get_family_bonus",
]


# ---------------------------------------------------------------------------
# Scoring Profile Model
# ---------------------------------------------------------------------------


class ScoringProfile(BaseModel):
    """Versioned scoring profile configuration.

    Defines weights, thresholds, hard rules, and family bonuses for
    a specific gas type. Profiles must be versioned with provenance.

    CRITICAL RULES:
    1. COMPATIBLE requires direct evidence (checked by verdict engine)
    2. Hard rejects are evaluated BEFORE scoring
    3. Family bonus only applies when material_family_key is validated
    """

    model_config = {"extra": "forbid"}

    profile_id: str
    version: str
    gas_type: GasType

    # Property weights (must use PropertyKey enum values as keys)
    weights: Dict[str, float] = Field(
        description="Property weights for scoring. Keys must be PropertyKey values."
    )

    # Verdict thresholds
    thresholds: Dict[str, float] = Field(
        description="Thresholds for verdict determination. Keys: compatible, marginal"
    )

    # Hard rejection rules (bypass scoring entirely)
    hard_rules: Dict[str, Any] = Field(
        default_factory=dict,
        description="Hard rejection rules applied before scoring"
    )

    # Family-based bonus (validated families only)
    family_bonus: Dict[str, float] = Field(
        default_factory=dict,
        description="Bonus scores for validated material families"
    )

    # Audit trail
    provenance: str = Field(
        description="Who set this profile, why, and when"
    )
    effective_from: str = Field(
        description="ISO 8601 timestamp when profile became effective"
    )
    effective_to: Optional[str] = Field(
        default=None,
        description="ISO 8601 timestamp when profile was superseded"
    )

    @field_validator("thresholds")
    @classmethod
    def validate_thresholds(cls, v: Dict[str, float]) -> Dict[str, float]:
        """Validate required threshold keys."""
        required = {"compatible", "marginal"}
        if not required <= set(v.keys()):
            raise ValueError(f"thresholds must include: {required}")
        if not (0.0 <= v["marginal"] <= v["compatible"] <= 1.0):
            raise ValueError(
                "thresholds must satisfy: 0 <= marginal <= compatible <= 1"
            )
        return v

    @field_validator("weights")
    @classmethod
    def validate_weights(cls, v: Dict[str, float]) -> Dict[str, float]:
        """Validate that weights are in valid range."""
        for key, weight in v.items():
            if not (0.0 <= weight <= 1.0):
                raise ValueError(f"Weight for {key} must be in [0, 1], got {weight}")
        total = sum(v.values())
        # Allow some slack for floating point - weights should sum to ~0.70
        # (remaining 0.30 is precedent_match from envelope overlap)
        if total > 1.01:
            raise ValueError(
                f"Property weights sum to {total}, must be <= 1.0"
            )
        return v

    @field_validator("family_bonus")
    @classmethod
    def validate_family_bonus(cls, v: Dict[str, float]) -> Dict[str, float]:
        """Validate family bonus values."""
        valid_families = {f.value for f in MaterialFamilyKey}
        for key, bonus in v.items():
            if key not in valid_families:
                raise ValueError(f"Invalid family key: {key}")
            if not (0.0 <= bonus <= 0.20):
                raise ValueError(
                    f"Family bonus for {key} must be in [0, 0.20], got {bonus}"
                )
        return v


# ---------------------------------------------------------------------------
# Default H2 Scoring Profile
# ---------------------------------------------------------------------------


H2_SCORING_PROFILE = ScoringProfile(
    profile_id="hydrogen_service",
    version="1.0.0",
    gas_type=GasType.H2,
    weights={
        PropertyKey.H2_EMBRITTLEMENT_CLASS.value: 0.35,
        PropertyKey.FRACTURE_TOUGHNESS_KSI_SQRT_IN.value: 0.20,
        PropertyKey.ELONGATION_PCT_AT_TEMP.value: 0.10,
        PropertyKey.H2_PERMEATION_RATE.value: 0.05,
        # Remaining ~0.30 is precedent_match (envelope overlap)
    },
    thresholds={
        "compatible": 0.75,
        "marginal": 0.50,
    },
    hard_rules={
        # H2 currently has no hard reject rules (unlike O2 flammability)
        # Add rules here as needed, e.g.:
        # "h2_embrittlement_class_reject": ["SEVERE", "PROHIBITED"]
    },
    family_bonus={
        MaterialFamilyKey.AUSTENITIC_STAINLESS.value: 0.10,
        MaterialFamilyKey.NICKEL_ALLOY.value: 0.10,
        MaterialFamilyKey.ALUMINUM_ALLOY.value: 0.05,
        MaterialFamilyKey.COPPER_ALLOY.value: 0.03,
    },
    provenance=(
        "Based on NASA Hydrogen Safety Standard (NSS 1740.16) and "
        "Sandia hydrogen materials compatibility guide (SAND2012_7321). "
        "Austenitic stainless and nickel alloys have excellent H2 resistance "
        "(FCC structure, low hydrogen embrittlement risk). "
        "Set by Dr. Wilde + Claude, 2025-12-17."
    ),
    effective_from="2025-12-17T00:00:00Z",
)


# ---------------------------------------------------------------------------
# Default O2 Scoring Profile
# ---------------------------------------------------------------------------


O2_SCORING_PROFILE = ScoringProfile(
    profile_id="oxygen_service",
    version="1.0.0",
    gas_type=GasType.O2,
    weights={
        PropertyKey.FLAMMABILITY_RATING.value: 0.40,
        PropertyKey.IGNITION_ENERGY_J.value: 0.15,
        PropertyKey.MECHANICAL_IMPACT_FT_LBS.value: 0.10,
        PropertyKey.AUTOGENOUS_IGNITION_TEMP_F.value: 0.05,
        # Remaining ~0.30 is precedent_match (envelope overlap)
    },
    thresholds={
        "compatible": 0.70,
        "marginal": 0.45,
    },
    hard_rules={
        # Flammability ratings that trigger immediate INCOMPATIBLE verdict
        "flammability_rating_reject": ["D", "X", "U"],
    },
    family_bonus={
        MaterialFamilyKey.AUSTENITIC_STAINLESS.value: 0.05,
        MaterialFamilyKey.NICKEL_ALLOY.value: 0.05,
        MaterialFamilyKey.COPPER_ALLOY.value: 0.05,
    },
    provenance=(
        "Based on NASA-STD-6001B and NASA-STD-6016C oxygen compatibility "
        "guidelines. Flammability rating is the primary driver per Test 1 "
        "(upward flame propagation). Ratings D (severe burning), X (unknown), "
        "and U (untested) are hard rejects requiring OCA. "
        "Set by Dr. Wilde + Claude, 2025-12-17."
    ),
    effective_from="2025-12-17T00:00:00Z",
)


# ---------------------------------------------------------------------------
# Profile Lookup Functions
# ---------------------------------------------------------------------------


_PROFILES: Dict[GasType, ScoringProfile] = {
    GasType.H2: H2_SCORING_PROFILE,
    GasType.O2: O2_SCORING_PROFILE,
}


def get_scoring_profile(gas_type: GasType) -> ScoringProfile:
    """Get the scoring profile for a gas type.

    Args:
        gas_type: H2 or O2

    Returns:
        Scoring profile for the gas type

    Raises:
        ValueError: If no profile exists for the gas type
    """
    profile = _PROFILES.get(gas_type)
    if profile is None:
        raise ValueError(f"No scoring profile for gas_type: {gas_type}")
    return profile


def get_hard_reject_ratings(profile: ScoringProfile) -> Set[str]:
    """Get the set of hard reject ratings from a profile.

    For O2, this returns flammability ratings that trigger immediate
    INCOMPATIBLE verdict (D, X, U per NASA-STD-6001B).

    Args:
        profile: Scoring profile

    Returns:
        Set of rating values that trigger hard rejection
    """
    reject_list = profile.hard_rules.get("flammability_rating_reject", [])
    return set(reject_list)


def get_family_bonus(
    profile: ScoringProfile,
    family_key: Optional[MaterialFamilyKey],
) -> float:
    """Get the family bonus for a material family.

    CRITICAL: Only applies when family_key is validated at ingestion time.
    Returns 0.0 for UNKNOWN or None families.

    Args:
        profile: Scoring profile
        family_key: Validated material family key (or None/UNKNOWN)

    Returns:
        Bonus score (0.0 to 0.20)
    """
    if family_key is None or family_key == MaterialFamilyKey.UNKNOWN:
        return 0.0

    return profile.family_bonus.get(family_key.value, 0.0)


# ---------------------------------------------------------------------------
# Property Score Normalization
# ---------------------------------------------------------------------------


def normalize_flammability_rating(rating: str) -> float:
    """Normalize flammability rating to score (0.0 to 1.0).

    Per NASA-STD-6001B Appendix B:
    - A: Self-extinguishing in 6" or less (best)
    - B: Burn length > 6" but self-extinguishing (acceptable)
    - C: Burns to end of sample (marginal)
    - D/X/U: Hard reject (handled separately)

    Args:
        rating: Flammability rating (A, B, C, etc.)

    Returns:
        Normalized score (0.0 to 1.0)
    """
    rating_scores = {
        "A": 1.0,
        "B": 0.75,
        "C": 0.45,
        "D": 0.0,  # Hard reject
        "X": 0.0,  # Hard reject
        "U": 0.0,  # Hard reject
    }
    return rating_scores.get(rating.upper().strip(), 0.2)


def normalize_h2_embrittlement_class(rating: str) -> float:
    """Normalize H2 embrittlement class to score (0.0 to 1.0).

    Based on NASA hydrogen compatibility guidelines:
    - A: Excellent resistance (FCC metals, copper alloys)
    - B: Good resistance (some aluminum alloys)
    - C: Moderate resistance (requires review)
    - D+: Poor resistance (may require mitigations)

    Args:
        rating: H2 embrittlement class

    Returns:
        Normalized score (0.0 to 1.0)
    """
    rating_scores = {
        "A": 1.0,
        "B": 0.75,
        "C": 0.50,
        "D": 0.25,
        "E": 0.10,
        "F": 0.0,
    }
    return rating_scores.get(rating.upper().strip(), 0.2)


# ---------------------------------------------------------------------------
# Scoring Profile Registry (for database-backed profiles)
# ---------------------------------------------------------------------------


class ScoringProfileRegistry:
    """Registry for scoring profiles with database backing.

    Supports loading profiles from PostgreSQL scoring_profile_config table.
    Falls back to built-in defaults if database unavailable.
    """

    def __init__(self) -> None:
        self._cache: Dict[tuple, ScoringProfile] = {}

    def get_profile(
        self,
        gas_type: GasType,
        version: Optional[str] = None,
    ) -> ScoringProfile:
        """Get a scoring profile, optionally by version.

        Args:
            gas_type: H2 or O2
            version: Optional specific version (None = latest)

        Returns:
            Scoring profile
        """
        cache_key = (gas_type, version)
        if cache_key in self._cache:
            return self._cache[cache_key]

        # For now, return built-in defaults
        # TODO: Add database loading when DB schema is deployed
        profile = get_scoring_profile(gas_type)
        self._cache[cache_key] = profile
        return profile

    def clear_cache(self) -> None:
        """Clear the profile cache."""
        self._cache.clear()


# Global registry instance
_registry = ScoringProfileRegistry()


def get_profile_from_registry(
    gas_type: GasType,
    version: Optional[str] = None,
) -> ScoringProfile:
    """Get a scoring profile from the global registry.

    Args:
        gas_type: H2 or O2
        version: Optional specific version

    Returns:
        Scoring profile
    """
    return _registry.get_profile(gas_type, version)
