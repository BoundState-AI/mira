#!/usr/bin/env python3
"""
Module: Verdict Engine
Purpose: verdict_engine

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

import logging
from typing import Any, Dict, List, Optional, Tuple

from .compatibility_models import (
    CompatibilityAssessment,
    CompatibilityClass,
    CompatibilityRecord,
    DataClass,
    EnvironmentEnvelope,
    GasType,
    PropertyEvidence,
    PropertyKey,
    ScoredEvidenceItem,
)
from .envelope_overlap import (
    DEFAULT_ENVELOPE_CONFIG,
    EnvelopeOverlapConfig,
    calculate_confidence_penalty,
    calculate_envelope_overlap,
)
from .scoring_profiles import (
    ScoringProfile,
    get_family_bonus,
    get_hard_reject_ratings,
    get_scoring_profile,
    normalize_flammability_rating,
    normalize_h2_embrittlement_class,
)


logger = logging.getLogger(__name__)

__all__ = [
    "VerdictEngine",
    "compute_verdict",
    "score_property",
    "check_hard_rejects",
]


# ---------------------------------------------------------------------------
# Property Score Computation
# ---------------------------------------------------------------------------


def score_property(
    prop: PropertyEvidence,
    gas_type: GasType,
) -> Tuple[float, str]:
    """Compute normalized score for a property.

    Args:
        prop: Property evidence to score
        gas_type: H2 or O2 (determines normalization)

    Returns:
        Tuple of (normalized_score, raw_value_str)
    """
    raw_value = prop.get_display_value()

    # Text-based ratings (flammability, embrittlement class)
    if prop.property_key == PropertyKey.FLAMMABILITY_RATING:
        if prop.value_text:
            score = normalize_flammability_rating(prop.value_text)
            return score, raw_value

    if prop.property_key == PropertyKey.H2_EMBRITTLEMENT_CLASS:
        if prop.value_text:
            score = normalize_h2_embrittlement_class(prop.value_text)
            return score, raw_value

    # Numeric properties - normalize based on typical ranges
    if prop.value_numeric is not None:
        if prop.property_key == PropertyKey.IGNITION_ENERGY_J:
            # Higher ignition energy = safer (inverse relationship)
            # Typical range: 0.1 to 100+ J
            score = min(1.0, prop.value_numeric / 50.0)
            return score, raw_value

        if prop.property_key == PropertyKey.MECHANICAL_IMPACT_FT_LBS:
            # Higher impact energy = safer
            # Typical range: 0 to 100 ft-lbs
            score = min(1.0, prop.value_numeric / 72.0)  # 72 ft-lbs = common target
            return score, raw_value

        if prop.property_key == PropertyKey.AUTOGENOUS_IGNITION_TEMP_F:
            # Higher AIT = safer
            # Typical range: 400 to 1000+ F
            score = min(1.0, max(0.0, (prop.value_numeric - 400.0) / 600.0))
            return score, raw_value

        if prop.property_key == PropertyKey.FRACTURE_TOUGHNESS_KSI_SQRT_IN:
            # Higher toughness = better H2 resistance
            # Typical range: 20 to 150 ksi*sqrt(in)
            score = min(1.0, prop.value_numeric / 100.0)
            return score, raw_value

        if prop.property_key == PropertyKey.ELONGATION_PCT_AT_TEMP:
            # Higher elongation = more ductile = better H2 resistance
            # Typical range: 0 to 50%
            score = min(1.0, prop.value_numeric / 40.0)
            return score, raw_value

    # Default: use confidence as score for unknown property types
    return prop.confidence * 0.5, raw_value


# ---------------------------------------------------------------------------
# Hard Reject Check
# ---------------------------------------------------------------------------


def check_hard_rejects(
    record: CompatibilityRecord,
    profile: ScoringProfile,
) -> Tuple[bool, Optional[str]]:
    """Check if record triggers a hard rejection rule.

    Hard rejects are evaluated BEFORE scoring and bypass the normal
    scoring algorithm entirely.

    Args:
        record: Compatibility record to check
        profile: Scoring profile with hard_rules

    Returns:
        Tuple of (is_rejected, rejection_reason)
    """
    reject_ratings = get_hard_reject_ratings(profile)

    if not reject_ratings:
        return False, None

    # Check flammability rating (O2 service)
    flam_prop = record.get_property(PropertyKey.FLAMMABILITY_RATING)
    if flam_prop and flam_prop.value_text:
        rating = flam_prop.value_text.strip().upper()
        if rating in reject_ratings:
            return True, (
                f"Hard reject: flammability rating '{rating}' is in prohibited list "
                f"{reject_ratings}. Per NASA-STD-6001B, materials with rating "
                f"D (severe burning), X (unknown), or U (untested) require OCA."
            )

    return False, None


# ---------------------------------------------------------------------------
# Verdict Engine
# ---------------------------------------------------------------------------


class VerdictEngine:
    """Deterministic verdict computation engine.

    Computes compatibility verdicts using:
    1. Hard reject rules (bypass scoring)
    2. Property-based scoring with versioned weights
    3. Envelope overlap scoring
    4. Family bonus (validated families only)
    5. Direct evidence requirement for COMPATIBLE verdict

    All computations are deterministic and fully auditable per SWE-033.
    """

    def __init__(
        self,
        scoring_profile: Optional[ScoringProfile] = None,
        envelope_config: Optional[EnvelopeOverlapConfig] = None,
    ) -> None:
        """Initialize verdict engine.

        Args:
            scoring_profile: Optional scoring profile (loaded by gas_type if None)
            envelope_config: Optional envelope overlap config
        """
        self._profile = scoring_profile
        self._envelope_config = envelope_config or DEFAULT_ENVELOPE_CONFIG

    def compute(
        self,
        material_key: str,
        material_name: str,
        gas_type: GasType,
        query_env: EnvironmentEnvelope,
        matched_records: List[CompatibilityRecord],
    ) -> CompatibilityAssessment:
        """Compute compatibility assessment.

        Args:
            material_key: Canonical material identifier
            material_name: Display name
            gas_type: H2 or O2
            query_env: Query environment envelope
            matched_records: Records from FAISS search

        Returns:
            CompatibilityAssessment with full audit trail
        """
        # Load profile if not set
        profile = self._profile or get_scoring_profile(gas_type)

        if not matched_records:
            return self._insufficient_data_assessment(
                material_key=material_key,
                material_name=material_name,
                gas_type=gas_type,
                query_env=query_env,
                profile=profile,
                reason="No matching records found in BOK index.",
            )

        # Use best-matching record for scoring
        best_record = matched_records[0]

        # Step 1: Check hard rejects (BEFORE scoring)
        is_rejected, reject_reason = check_hard_rejects(best_record, profile)
        if is_rejected:
            return self._hard_reject_assessment(
                material_key=material_key,
                material_name=material_name,
                gas_type=gas_type,
                query_env=query_env,
                profile=profile,
                record=best_record,
                reject_reason=reject_reason or "Hard rejection rule triggered.",
            )

        # Step 2: Compute envelope overlap
        env_overlap, env_warnings = calculate_envelope_overlap(
            query_env=query_env,
            record_env=best_record.environment,
            config=self._envelope_config,
        )

        # Step 3: Score properties
        scored_evidence, property_score = self._score_properties(
            record=best_record,
            profile=profile,
        )

        # Step 4: Apply family bonus
        family_bonus = get_family_bonus(profile, best_record.material_family_key)

        # Step 5: Compute total score
        # Score = (property_score * 0.70) + (envelope_overlap * 0.30) + family_bonus
        precedent_weight = 0.30  # Remaining weight after property weights
        total_score = (
            property_score
            + (env_overlap * precedent_weight)
            + family_bonus
        )
        total_score = min(1.0, total_score)  # Cap at 1.0

        # Step 6: Check direct evidence requirement
        has_direct = best_record.has_direct_evidence()

        # Step 7: Determine verdict
        verdict = self._determine_verdict(
            total_score=total_score,
            has_direct_evidence=has_direct,
            profile=profile,
        )

        # Step 8: Calculate confidence with penalty for missing envelope data
        confidence_penalty = calculate_confidence_penalty(env_warnings)
        confidence_score = total_score * confidence_penalty

        # Step 9: Collect warnings and mitigations
        all_warnings = list(env_warnings)
        if not has_direct and verdict == CompatibilityClass.COMPATIBLE:
            # This shouldn't happen due to _determine_verdict logic, but safety check
            all_warnings.append(
                "COMPATIBLE verdict requires direct evidence - downgraded to MARGINAL"
            )
            verdict = CompatibilityClass.MARGINAL

        if best_record.material_family_key == MaterialFamilyKey.UNKNOWN:
            all_warnings.append(
                "Material family unknown - no family bonus applied"
            )

        mitigations: List[str] = []
        if best_record.mitigation:
            mitigations.append(best_record.mitigation)

        # Step 10: Generate reasoning (template-based, NO invented facts)
        reasoning = self._generate_reasoning(
            verdict=verdict,
            best_record=best_record,
            total_score=total_score,
            env_overlap=env_overlap,
            family_bonus=family_bonus,
            has_direct=has_direct,
            profile=profile,
        )

        return CompatibilityAssessment(
            material_key=material_key,
            material_name=material_name,
            gas_type=gas_type,
            query_environment=query_env,
            verdict=verdict,
            confidence_score=confidence_score,
            evidence=scored_evidence,
            total_score=total_score,
            has_direct_evidence=has_direct,
            warnings=all_warnings,
            mitigations=mitigations,
            precedent_records=[r.record_id for r in matched_records[:5]],
            reasoning=reasoning,
            scoring_profile_version=f"{profile.profile_id}:{profile.version}",
            envelope_overlap_config_version=(
                f"{self._envelope_config.config_id}:{self._envelope_config.version}"
            ),
        )

    def _score_properties(
        self,
        record: CompatibilityRecord,
        profile: ScoringProfile,
    ) -> Tuple[List[ScoredEvidenceItem], float]:
        """Score properties from a record.

        Args:
            record: Compatibility record
            profile: Scoring profile

        Returns:
            Tuple of (scored_evidence_items, total_property_score)
        """
        scored_items: List[ScoredEvidenceItem] = []
        total_contribution = 0.0

        for prop in record.properties:
            prop_key_str = prop.property_key.value
            weight = profile.weights.get(prop_key_str, 0.0)

            if weight == 0.0:
                continue  # Property not in scoring profile

            normalized_score, raw_value = score_property(prop, record.gas_type)

            # Apply confidence factor
            adjusted_score = normalized_score * prop.confidence
            contribution = adjusted_score * weight

            scored_items.append(
                ScoredEvidenceItem(
                    property_key=prop.property_key,
                    raw_value=raw_value,
                    normalized_score=adjusted_score,
                    weight=weight,
                    contribution=contribution,
                    source_ref=prop.source_ref,
                    test_method=prop.test_method,
                    data_class=prop.data_class,
                    confidence=prop.confidence,
                )
            )

            total_contribution += contribution

        return scored_items, total_contribution

    def _determine_verdict(
        self,
        total_score: float,
        has_direct_evidence: bool,
        profile: ScoringProfile,
    ) -> CompatibilityClass:
        """Determine verdict from score and evidence.

        CRITICAL: COMPATIBLE requires has_direct_evidence=True

        Args:
            total_score: Computed total score
            has_direct_evidence: Whether record has direct test/standard evidence
            profile: Scoring profile with thresholds

        Returns:
            CompatibilityClass verdict
        """
        compatible_threshold = profile.thresholds["compatible"]
        marginal_threshold = profile.thresholds["marginal"]

        if total_score >= compatible_threshold:
            # CRITICAL: Direct evidence required for COMPATIBLE
            if has_direct_evidence:
                return CompatibilityClass.COMPATIBLE
            else:
                # Downgrade to MARGINAL without direct evidence
                return CompatibilityClass.MARGINAL

        if total_score >= marginal_threshold:
            return CompatibilityClass.MARGINAL

        if total_score > 0.2:
            return CompatibilityClass.INCOMPATIBLE

        return CompatibilityClass.INSUFFICIENT_DATA

    def _generate_reasoning(
        self,
        verdict: CompatibilityClass,
        best_record: CompatibilityRecord,
        total_score: float,
        env_overlap: float,
        family_bonus: float,
        has_direct: bool,
        profile: ScoringProfile,
    ) -> str:
        """Generate template-based reasoning.

        CRITICAL: Template assembly only - NO invented facts.

        Args:
            verdict: Determined verdict
            best_record: Best matching record
            total_score: Computed total score
            env_overlap: Envelope overlap score
            family_bonus: Applied family bonus
            has_direct: Whether direct evidence exists
            profile: Scoring profile

        Returns:
            Reasoning string
        """
        parts = [
            f"Assessment for {best_record.material_name} ({best_record.material_key}) "
            f"in {best_record.gas_type.value} service.",
        ]

        parts.append(f"Verdict: {verdict.value.upper()}")
        parts.append(f"Total score: {total_score:.2f}")

        if has_direct:
            parts.append(
                "Direct test evidence available (DIRECT_TEST or STANDARD_TABLE)."
            )
        else:
            parts.append(
                "No direct test evidence - assessment based on BOK precedent or derived data."
            )

        if family_bonus > 0:
            family_name = (
                best_record.material_family_key.value
                if best_record.material_family_key
                else "unknown"
            )
            parts.append(
                f"Family bonus of {family_bonus:.2f} applied for {family_name}."
            )

        parts.append(f"Envelope overlap: {env_overlap:.2f}")
        parts.append(f"Reference: {best_record.standard_ref}")

        if best_record.reason:
            parts.append(f"Record reason: {best_record.reason}")

        return " ".join(parts)

    def _insufficient_data_assessment(
        self,
        material_key: str,
        material_name: str,
        gas_type: GasType,
        query_env: EnvironmentEnvelope,
        profile: ScoringProfile,
        reason: str,
    ) -> CompatibilityAssessment:
        """Create assessment for insufficient data case."""
        return CompatibilityAssessment(
            material_key=material_key,
            material_name=material_name,
            gas_type=gas_type,
            query_environment=query_env,
            verdict=CompatibilityClass.INSUFFICIENT_DATA,
            confidence_score=0.0,
            evidence=[],
            total_score=0.0,
            has_direct_evidence=False,
            warnings=[reason],
            mitigations=[],
            precedent_records=[],
            reasoning=f"INSUFFICIENT_DATA: {reason}",
            scoring_profile_version=f"{profile.profile_id}:{profile.version}",
            envelope_overlap_config_version=(
                f"{self._envelope_config.config_id}:{self._envelope_config.version}"
            ),
        )

    def _hard_reject_assessment(
        self,
        material_key: str,
        material_name: str,
        gas_type: GasType,
        query_env: EnvironmentEnvelope,
        profile: ScoringProfile,
        record: CompatibilityRecord,
        reject_reason: str,
    ) -> CompatibilityAssessment:
        """Create assessment for hard rejection case."""
        return CompatibilityAssessment(
            material_key=material_key,
            material_name=material_name,
            gas_type=gas_type,
            query_environment=query_env,
            verdict=CompatibilityClass.INCOMPATIBLE,
            confidence_score=1.0,  # High confidence in rejection
            evidence=[],
            total_score=0.0,
            has_direct_evidence=record.has_direct_evidence(),
            warnings=[reject_reason],
            mitigations=[
                "Oxygen Compatibility Assessment (OCA) required per NASA-STD-6001B."
            ],
            precedent_records=[record.record_id],
            reasoning=f"INCOMPATIBLE (HARD REJECT): {reject_reason}",
            scoring_profile_version=f"{profile.profile_id}:{profile.version}",
            envelope_overlap_config_version=(
                f"{self._envelope_config.config_id}:{self._envelope_config.version}"
            ),
        )


# ---------------------------------------------------------------------------
# Convenience Function
# ---------------------------------------------------------------------------


def compute_verdict(
    material_key: str,
    material_name: str,
    gas_type: GasType,
    query_env: EnvironmentEnvelope,
    matched_records: List[CompatibilityRecord],
    scoring_profile: Optional[ScoringProfile] = None,
    envelope_config: Optional[EnvelopeOverlapConfig] = None,
) -> CompatibilityAssessment:
    """Convenience function to compute a verdict.

    Args:
        material_key: Canonical material identifier
        material_name: Display name
        gas_type: H2 or O2
        query_env: Query environment envelope
        matched_records: Records from FAISS search
        scoring_profile: Optional scoring profile
        envelope_config: Optional envelope overlap config

    Returns:
        CompatibilityAssessment with full audit trail
    """
    engine = VerdictEngine(
        scoring_profile=scoring_profile,
        envelope_config=envelope_config,
    )
    return engine.compute(
        material_key=material_key,
        material_name=material_name,
        gas_type=gas_type,
        query_env=query_env,
        matched_records=matched_records,
    )


# Import for _determine_verdict fallback
from .compatibility_models import MaterialFamilyKey
import uuid
