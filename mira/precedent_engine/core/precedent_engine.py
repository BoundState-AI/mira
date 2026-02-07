#!/usr/bin/env python3
"""
Module: Precedent Engine
Purpose: precedent_engine

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-033, NASA-STD-6016, NASA-STD-8739.8B
Safety Critical: True
"""

from __future__ import annotations

from datetime import datetime
from math import exp
from typing import Literal

import uuid

from mira.precedent_engine.models.config import (
    PrecedentAdequacyConfig,
    PrecedentEquivalenceConfig,
)
from mira.precedent_engine.models.enriched import EnrichedMUA
from mira.precedent_engine.models.enums import EquivalenceMode, PrecedentAdequacyLevel, ProgramFamily
from mira.precedent_engine.models.precedent import (
    PrecedentMatch,
    PrecedentRetrievalResult,
    PrecedentStatistics,
)


class PrecedentEngine:
    """
    Core engine for precedent tier assignment, scoring, and adequacy classification.

    This is the key differentiator: tiered retrieval with continuous similarity
    scoring and statistical adequacy assessment.

    CRITICAL: All operations in this class are SYNCHRONOUS (pure computation).
    LLM is NOT involved in any tier assignment, equivalence checking, or
    adequacy scoring. These are deterministic calculations based on
    configuration parameters.

    Compliance: SWE-013, SWE-033
    Safety Critical: True
    """

    def __init__(
        self,
        equivalence_config: PrecedentEquivalenceConfig,
        adequacy_config: PrecedentAdequacyConfig,
    ) -> None:
        """
        Initialize the precedent engine.

        Args:
            equivalence_config: Configuration for material/env/deviation equivalence
            adequacy_config: Thresholds for adequacy classification
        """
        self.eq = equivalence_config
        self.adequacy = adequacy_config

    def evaluate_candidates(
        self,
        query: EnrichedMUA,
        candidates: list[EnrichedMUA],
        now: datetime | None = None,
    ) -> PrecedentRetrievalResult:
        """
        Evaluate candidate MUAs against query.

        1. Assign tiers to each candidate
        2. Compute similarity scores
        3. Classify overall adequacy
        4. Return structured result

        IMPORTANT: This is a SYNCHRONOUS method. No async, no LLM calls.
        All scoring is deterministic based on configuration.

        Args:
            query: The query MUA to find precedents for
            candidates: List of candidate MUAs from vector search
            now: Current timestamp (for recency weighting)

        Returns:
            PrecedentRetrievalResult with tier-sorted matches and adequacy
        """
        now = now or datetime.utcnow()

        tier1: list[PrecedentMatch] = []
        tier2: list[PrecedentMatch] = []
        tier3: list[PrecedentMatch] = []

        for cand in candidates:
            match = self._evaluate_single(query, cand, now)
            if match is None:
                continue

            if match.tier == 1:
                tier1.append(match)
            elif match.tier == 2:
                tier2.append(match)
            else:
                tier3.append(match)

        # Sort by score within tiers
        tier1.sort(key=lambda m: m.similarity_score, reverse=True)
        tier2.sort(key=lambda m: m.similarity_score, reverse=True)
        tier3.sort(key=lambda m: m.similarity_score, reverse=True)

        # Compute statistics
        all_matches = tier1 + tier2 + tier3
        statistics = self._compute_statistics(query, candidates)

        n_rejected = sum(1 for m in all_matches if m.is_rejected)
        n_superseded = sum(1 for m in all_matches if m.is_superseded)
        unique_programs = {m.source_program for m in all_matches if m.source_program}

        # Determine adequacy
        if tier1:
            tier_used = 1
            best = tier1[0]
        elif tier2:
            tier_used = 2
            best = tier2[0]
        elif tier3:
            tier_used = 3
            best = tier3[0]
        else:
            return self._build_empty_result(query, statistics)

        adequacy, reasoning = self._classify_adequacy(
            tier_used=tier_used,
            best_score=best.similarity_score,
            n_matches=len(all_matches),
            n_rejected=n_rejected,
            n_unique_programs=len(unique_programs),
        )

        # Build environment summary
        env_summary = self._build_environment_summary(query)

        return PrecedentRetrievalResult(
            query_material_key=query.material_key,
            query_material_name=query.material_name,
            query_environment_summary=env_summary,
            statistics=statistics,
            n_total_candidates=len(all_matches),
            n_tier1=len(tier1),
            n_tier2=len(tier2),
            n_tier3=len(tier3),
            n_rejected_in_set=n_rejected,
            n_superseded_in_set=n_superseded,
            n_unique_programs=len(unique_programs),
            n_unique_test_sources=len({m.contract_id for m in all_matches}),
            adequacy=adequacy,
            adequacy_reasoning=reasoning,
            tier1_matches=tier1[:10],  # Limit for response size
            tier2_matches=tier2[:10],
            tier3_matches=tier3[:5],
            recommended_base=best,
            base_selection_reasoning=f"Highest scoring Tier {tier_used} match (score={best.similarity_score:.3f})",
        )

    def _evaluate_single(
        self,
        query: EnrichedMUA,
        cand: EnrichedMUA,
        now: datetime,
    ) -> PrecedentMatch | None:
        """
        Evaluate a single candidate and return PrecedentMatch or None.

        Args:
            query: Query MUA
            cand: Candidate MUA
            now: Current timestamp

        Returns:
            PrecedentMatch if candidate passes filters, None otherwise
        """
        # Assign tier
        tier = self._assign_tier(query, cand)
        if tier is None:
            return None

        # Compute equivalence flags for this tier
        material_equiv = self._material_equivalent(query, cand, tier)
        env_equiv = self._environment_equivalent(query, cand, tier)
        dev_equiv = self._deviation_equivalent(query, cand, tier)

        # Compute similarity scores
        material_sim = 1.0 if material_equiv else 0.0
        env_sim = self._environment_similarity(query, cand)
        dev_sim = self._deviation_similarity(query, cand)
        program_weight = self._program_weight(query.program_family, cand.program_family)

        # Recency weight
        if cand.approval_date:
            years_old = max((now.date() - cand.approval_date).days / 365.25, 0.0)
        else:
            years_old = 10.0  # Default for missing dates

        hl = self.eq.recency_half_life_years
        recency_weight = exp(-years_old * (0.693 / max(hl, 1e-6)))

        # Compute final score
        w = self.eq.weights
        base_score = (
            w.material * material_sim + w.environment * env_sim + w.deviation * dev_sim
        )

        # Program and recency as multiplicative factors
        final_score = max(
            0.0, min(1.0, base_score * program_weight * (0.5 + 0.5 * recency_weight))
        )

        # Environment delta summary
        env_delta = self._build_environment_delta(query, cand)

        return PrecedentMatch(
            contract_id=cand.contract_id,
            material_name=cand.material_name,
            material_key=cand.material_key,
            tier=tier,
            similarity_score=final_score,
            material_equivalent=material_equiv,
            environment_equivalent=env_equiv,
            deviation_equivalent=dev_equiv,
            program_weight=program_weight,
            media=cand.media,
            o2_pct=cand.o2_pct,
            location_class=cand.location_class,
            temp_max_f=cand.temp_max_f,
            temp_min_f=cand.temp_min_f,
            pressure_max_psia=cand.pressure_max_psia,
            is_rejected=cand.is_rejected,
            is_superseded=cand.is_superseded,
            superseded_by=cand.superseded_by,
            available_rationale_types=cand.deviation_types,
            rationale_text=cand.rationale_text,
            source_program=cand.program,
            source_program_family=cand.program_family,
            approval_date=cand.approval_date,
            category=cand.category,
            environment_delta_summary=env_delta,
            precedent_family=cand.precedent_family,
        )

    def _assign_tier(self, query: EnrichedMUA, cand: EnrichedMUA) -> Literal[1, 2, 3] | None:
        """
        Assign tier based on equivalence rules.

        Returns 1, 2, 3, or None if candidate is not usable.

        Tier 1: Exact material + environment + deviation match
        Tier 2: Same material, relaxed environment/deviation tolerance
        Tier 3: Analog (different material, same deviation alignment)

        IMPORTANT per Addendum B: Rejected MUAs are Tier 3 at best.
        """
        # Rejected MUAs are Tier 3 at best
        if cand.is_rejected:
            if self._deviation_equivalent(query, cand, tier=2):
                return 3
            return None

        # Check Tier 1 equivalence
        if (
            self._material_equivalent(query, cand, tier=1)
            and self._environment_equivalent(query, cand, tier=1)
            and self._deviation_equivalent(query, cand, tier=1)
        ):
            return 1

        # Check Tier 2 equivalence
        if (
            self._material_equivalent(query, cand, tier=2)
            and self._environment_equivalent(query, cand, tier=2)
            and self._deviation_equivalent(query, cand, tier=2)
        ):
            return 2

        # Tier 3: analog (at least deviation alignment)
        if self._deviation_equivalent(query, cand, tier=2):
            return 3

        return None

    def _material_equivalent(
        self, query: EnrichedMUA, cand: EnrichedMUA, tier: int
    ) -> bool:
        """
        Check material equivalence.

        IMPORTANT per Addendum B: Name-based equivalence (when material_key is
        missing) SHALL NOT produce Tier 1 matches. This fallback is advisory only.
        """
        cfg = self.eq.material

        if cfg.mode == EquivalenceMode.OFF:
            return True

        # Primary: material_key comparison
        if query.material_key and cand.material_key:
            if query.material_key == cand.material_key:
                return True

        # Tier 2: allow family equivalence if configured
        if tier >= 2 and cfg.allow_family_equivalence_tier2:
            family = cfg.family_groups.get(query.material_key or "", [])
            if cand.material_key in family:
                return True

        # Name-based fallback when material_key is not available
        # This allows practical searching by material name
        if not query.material_key or not cand.material_key:
            q_norm = (query.material_name or "").upper().replace(" ", "").replace("-", "")
            c_norm = (cand.material_name or "").upper().replace(" ", "").replace("-", "")

            # Exact match - allow Tier 1
            if q_norm and c_norm and q_norm == c_norm:
                return True

            # Substring match (e.g., "6061" matches "6061-T6 ALUMINUM")
            # Allow Tier 1 if query is clearly contained in candidate
            if q_norm and c_norm and len(q_norm) >= 4:
                if q_norm in c_norm:
                    return True  # Query is substring of candidate - Tier 1 OK

            # Tier 2/3: allow reverse substring (candidate in query)
            if tier >= 2 and q_norm and c_norm:
                if c_norm in q_norm:
                    return True

        return False

    def _environment_equivalent(
        self, query: EnrichedMUA, cand: EnrichedMUA, tier: int
    ) -> bool:
        """Check environment equivalence."""
        cfg = self.eq.environment

        if cfg.mode == EquivalenceMode.OFF:
            return True

        # Location class
        if cfg.require_same_location_class:
            if query.location_class != cand.location_class:
                return False

        # Media
        if tier == 1 and cfg.require_same_media_tier1:
            if query.media and cand.media and query.media != cand.media:
                return False

        # Temperature (Rankine)
        tolerance_pct = (
            cfg.temp_tolerance_pct_tier1 if tier == 1 else cfg.temp_tolerance_pct_tier2
        )
        if not self._temp_within_tolerance(query, cand, tolerance_pct):
            return False

        # Pressure
        tolerance_psia = (
            cfg.pressure_tolerance_psia_tier1
            if tier == 1
            else cfg.pressure_tolerance_psia_tier2
        )
        if not self._pressure_within_tolerance(query, cand, tolerance_psia):
            return False

        # O2%
        o2_tolerance = (
            cfg.o2_tolerance_pct_tier1 if tier == 1 else cfg.o2_tolerance_pct_tier2
        )
        if abs(query.o2_pct - cand.o2_pct) > o2_tolerance:
            return False

        return True

    def _deviation_equivalent(
        self, query: EnrichedMUA, cand: EnrichedMUA, tier: int
    ) -> bool:
        """Check deviation type equivalence."""
        cfg = self.eq.deviation

        if cfg.mode == EquivalenceMode.OFF:
            return True

        q_types = set(query.deviation_types)
        c_types = set(cand.deviation_types)

        if not q_types:
            return True  # No specific deviations required

        if tier == 1:
            if cfg.require_same_deviation_types_tier1:
                return q_types == c_types
        else:
            if cfg.allow_subset_deviation_types_tier2:
                return q_types.issubset(c_types)

        return q_types == c_types

    def _temp_within_tolerance(
        self, query: EnrichedMUA, cand: EnrichedMUA, tolerance_pct: float
    ) -> bool:
        """Check temperature within tolerance (Rankine scale)."""
        if query.temp_max_f is None or cand.temp_max_f is None:
            return True  # Missing data = assume compatible

        # Convert to Rankine centers
        q_center = ((query.temp_min_f or 70) + query.temp_max_f) / 2 + 459.67
        c_center = ((cand.temp_min_f or 70) + cand.temp_max_f) / 2 + 459.67

        delta_pct = abs(q_center - c_center) / max(q_center, 1.0) * 100
        return delta_pct <= tolerance_pct

    def _pressure_within_tolerance(
        self, query: EnrichedMUA, cand: EnrichedMUA, tolerance_psia: float
    ) -> bool:
        """Check pressure within tolerance."""
        q_pressure = query.pressure_max_psia or 0
        c_pressure = cand.pressure_max_psia or 0

        return abs(q_pressure - c_pressure) <= tolerance_psia

    def _environment_similarity(self, query: EnrichedMUA, cand: EnrichedMUA) -> float:
        """Compute continuous environment similarity [0,1]."""
        cfg = self.eq.environment

        if cfg.mode == EquivalenceMode.OFF:
            return 1.0

        scores = []

        # Temperature similarity
        if query.temp_max_f is not None and cand.temp_max_f is not None:
            q_center = ((query.temp_min_f or 70) + query.temp_max_f) / 2 + 459.67
            c_center = ((cand.temp_min_f or 70) + cand.temp_max_f) / 2 + 459.67
            delta_pct = abs(q_center - c_center) / max(q_center, 1.0) * 100
            max_tol = max(cfg.temp_tolerance_pct_tier2, 1.0)
            temp_sim = max(0.0, 1.0 - delta_pct / max_tol)
            scores.append(temp_sim)

        # Pressure similarity
        q_p = query.pressure_max_psia or 0
        c_p = cand.pressure_max_psia or 0
        if q_p > 0 or c_p > 0:
            delta_p = abs(q_p - c_p)
            max_p = max(cfg.pressure_tolerance_psia_tier2, 1.0)
            p_sim = max(0.0, 1.0 - delta_p / max_p)
            scores.append(p_sim)

        # O2 similarity
        delta_o2 = abs(query.o2_pct - cand.o2_pct)
        max_o2 = max(cfg.o2_tolerance_pct_tier2, 1.0)
        o2_sim = max(0.0, 1.0 - delta_o2 / max_o2)
        scores.append(o2_sim)

        # Location match
        loc_sim = 1.0 if query.location_class == cand.location_class else 0.5
        scores.append(loc_sim)

        return sum(scores) / len(scores) if scores else 1.0

    def _deviation_similarity(self, query: EnrichedMUA, cand: EnrichedMUA) -> float:
        """Compute deviation similarity (Jaccard)."""
        q_types = set(query.deviation_types)
        c_types = set(cand.deviation_types)

        if not q_types and not c_types:
            return 1.0
        if not q_types or not c_types:
            return 0.5  # Partial match

        intersection = len(q_types & c_types)
        union = len(q_types | c_types)

        return intersection / union if union > 0 else 0.0

    def _program_weight(self, q_family: ProgramFamily, p_family: ProgramFamily) -> float:
        """Get program compatibility weight."""
        cfg = self.eq.program

        if cfg.mode == EquivalenceMode.OFF:
            return 1.0

        if q_family == p_family:
            return cfg.same_program_weight

        key = (p_family, q_family)
        return cfg.compatibility_weights.get(key, cfg.default_cross_program_weight)

    def _compute_statistics(
        self, query: EnrichedMUA, all_candidates: list[EnrichedMUA]
    ) -> PrecedentStatistics:
        """Compute corpus-wide statistics for this query."""
        # Filter to same material
        same_material = [
            c
            for c in all_candidates
            if c.material_key == query.material_key
            or c.material_name.upper() == query.material_name.upper()
        ]

        n_total = len(same_material)
        n_approved = sum(1 for c in same_material if c.is_usable_precedent)
        n_rejected = sum(1 for c in same_material if c.is_rejected)
        n_deferred = sum(
            1 for c in same_material if (c.determination or "").upper() == "DEFERRED"
        )

        # Similar environment
        n_similar_env = sum(
            1 for c in same_material if self._environment_equivalent(query, c, tier=2)
        )

        # Same deviation
        n_same_dev = sum(
            1 for c in same_material if self._deviation_equivalent(query, c, tier=2)
        )

        # Approval rate
        approval_rate = n_approved / n_total if n_total > 0 else 0.0

        # Rejection rate upper bound (95% CI, Clopper-Pearson approximation)
        if n_approved > 0 and n_rejected == 0:
            # Use beta distribution for CI
            try:
                from scipy import stats

                rejection_upper = stats.beta.ppf(0.95, 1, n_approved + 1)
            except ImportError:
                # Fallback without scipy
                rejection_upper = 1 / (n_approved + 1)
        elif n_total > 0:
            rejection_upper = (n_rejected + 1) / (n_total + 2)  # Laplace smoothing
        else:
            rejection_upper = 1.0

        return PrecedentStatistics(
            n_total_with_material=n_total,
            n_similar_environment=n_similar_env,
            n_same_deviation=n_same_dev,
            n_approved=n_approved,
            n_rejected=n_rejected,
            n_deferred=n_deferred,
            approval_rate=approval_rate,
            rejection_rate_upper_bound=rejection_upper,
        )

    def _classify_adequacy(
        self,
        tier_used: int,
        best_score: float,
        n_matches: int,
        n_rejected: int,
        n_unique_programs: int,
    ) -> tuple[PrecedentAdequacyLevel, str]:
        """
        Classify precedent adequacy.

        IMPORTANT: This is a DETERMINISTIC classification. LLM is NOT involved.
        """
        cfg = self.adequacy

        rejected_fraction = n_rejected / max(n_matches, 1)

        # Tier 3 always insufficient
        if cfg.tier3_always_insufficient and tier_used >= 3:
            return (
                PrecedentAdequacyLevel.INSUFFICIENT,
                "Only Tier 3 (analog) matches found. Manual justification required.",
            )

        # Check for STRONG
        if (
            tier_used == 1
            and best_score >= cfg.min_score_strong
            and n_matches >= cfg.min_count_strong
            and n_unique_programs >= cfg.min_unique_sources_strong
            and rejected_fraction <= cfg.max_rejected_fraction_strong
        ):
            return (
                PrecedentAdequacyLevel.STRONG,
                f"Strong precedent: {n_matches} Tier 1 matches, best score {best_score:.2f}, "
                f"{n_unique_programs} unique programs, {rejected_fraction:.0%} rejected.",
            )

        # Check for MODERATE
        if (
            n_matches >= cfg.min_count_moderate
            and best_score >= cfg.min_score_moderate
            and rejected_fraction <= cfg.max_rejected_fraction_moderate
        ):
            level = (
                cfg.tier2_max_adequacy if tier_used == 2 else PrecedentAdequacyLevel.MODERATE
            )
            return (
                level,
                f"Moderate precedent: Tier {tier_used}, {n_matches} matches, "
                f"best score {best_score:.2f}, review recommended.",
            )

        # INSUFFICIENT
        reasons = []
        if best_score < cfg.min_score_moderate:
            reasons.append(f"best score {best_score:.2f} < {cfg.min_score_moderate}")
        if n_matches < cfg.min_count_moderate:
            reasons.append(f"only {n_matches} matches")
        if rejected_fraction > cfg.max_rejected_fraction_moderate:
            reasons.append(f"{rejected_fraction:.0%} rejected")

        return (
            PrecedentAdequacyLevel.INSUFFICIENT,
            f"Insufficient precedent: {', '.join(reasons)}. Manual justification required.",
        )

    def _build_environment_summary(self, query: EnrichedMUA) -> str:
        """Build human-readable environment summary."""
        parts = []

        if query.media:
            parts.append(query.media)

        if query.temp_min_f is not None or query.temp_max_f is not None:
            t_min = query.temp_min_f or "?"
            t_max = query.temp_max_f or "?"
            parts.append(f"{t_min}°F to {t_max}°F")

        if query.pressure_max_psia:
            parts.append(f"{query.pressure_max_psia} psia max")

        if query.o2_pct != 21.0:
            parts.append(f"{query.o2_pct}% O2")

        parts.append(query.location_class.replace("_", " ").title())

        return ", ".join(parts) if parts else "Standard conditions"

    def _build_environment_delta(self, query: EnrichedMUA, cand: EnrichedMUA) -> str:
        """Build human-readable delta between query and candidate environment."""
        deltas = []

        if query.temp_max_f and cand.temp_max_f:
            t_delta = cand.temp_max_f - query.temp_max_f
            if abs(t_delta) > 10:
                deltas.append(f"Temp: {t_delta:+.0f}°F")

        if query.pressure_max_psia and cand.pressure_max_psia:
            p_delta = cand.pressure_max_psia - query.pressure_max_psia
            if abs(p_delta) > 50:
                deltas.append(f"Pressure: {p_delta:+.0f} psia")

        if abs(query.o2_pct - cand.o2_pct) > 1:
            deltas.append(f"O2: {cand.o2_pct - query.o2_pct:+.1f}%")

        return "; ".join(deltas) if deltas else "Environment match"

    def _build_empty_result(
        self, query: EnrichedMUA, statistics: PrecedentStatistics
    ) -> PrecedentRetrievalResult:
        """Build result when no candidates pass filters."""
        return PrecedentRetrievalResult(
            query_material_key=query.material_key,
            query_material_name=query.material_name,
            query_environment_summary=self._build_environment_summary(query),
            statistics=statistics,
            n_total_candidates=0,
            n_tier1=0,
            n_tier2=0,
            n_tier3=0,
            n_rejected_in_set=0,
            n_superseded_in_set=0,
            n_unique_programs=0,
            n_unique_test_sources=0,
            adequacy=PrecedentAdequacyLevel.INSUFFICIENT,
            adequacy_reasoning="No precedents passed equivalence filters.",
            tier1_matches=[],
            tier2_matches=[],
            tier3_matches=[],
            recommended_base=None,
            base_selection_reasoning="No base MUA recommended; manual justification required.",
        )
