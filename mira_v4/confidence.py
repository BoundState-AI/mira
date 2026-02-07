#!/usr/bin/env python3
"""
Module: Confidence Score Formula
Purpose: Penalty-based confidence scoring for MIRA v4 queries.

BoundState AI 2026
Version: 4.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-033, NASA-STD-8739.8B
Safety Critical: True

Implements BuildSpec REV1 Item 1: Confidence Score Formula (P0).

The MIRA v4 confidence score is a PENALTY-BASED score. It is NOT a
statistical confidence interval. It starts at 1.0 (maximum confidence)
and is reduced by quantified penalties for each source of uncertainty.

Formula:
    confidence = 1.0
        - unknown_env_penalty   * n_unknown_env_fields
        - staleness_penalty     * staleness_factor
        - sparse_evidence_penalty * (1 - min(n_evidence / 5, 1.0))
        - dirty_data_penalty    * dirty_fraction
        - heritage_conflict_penalty (if heritage veto active)
    confidence = max(0.0, confidence)

Gate thresholds:
    >= 0.85: PASS (safety-critical)
    >= 0.70: PASS (general only)
    0.50 - 0.69: CLARIFY
    < 0.50: REFUSE

Spec Reference: BS-MIRA-V4-BUILDSPEC-001-REV1, Section 2
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Tuple

from .models import (
    ConfidenceResult,
    EnvironmentSpec,
    EvidenceRow,
    GateAction,
    PenaltyDetail,
)

logger = logging.getLogger(__name__)


class ConfidenceCalculator:
    """Penalty-based confidence score calculator per BuildSpec Section 2.

    Starting score: 1.0 (maximum confidence).
    Five penalty types reduce the score based on quantified data quality issues.
    The penalty breakdown is included in the immutable Decision Lineage artifact.

    Compliance: SWE-013, SWE-033, NASA-STD-8739.8B
    """

    # =========================================================================
    # Penalty Constants (from BuildSpec Section 2.4, Table 3)
    # =========================================================================

    #: Per missing environment field. Max 6 fields = 0.48 total.
    UNKNOWN_ENV_PENALTY_PER_FIELD: float = 0.08

    #: Per staleness tier. staleness_factor = 0 if <5yr, 1 if 5-10yr,
    #: 2 if 10-20yr, 3 if >20yr. Max penalty = 0.15.
    STALENESS_PENALTY_PER_TIER: float = 0.05

    #: Scaled linearly from 0.20 (zero evidence) to 0.00 (5+ evidence rows).
    SPARSE_EVIDENCE_PENALTY_MAX: float = 0.20

    #: Scaled by dirty_fraction (proportion of dirty records).
    DIRTY_DATA_PENALTY_MAX: float = 0.25

    #: Applied ONLY when heritage veto is active. Binary: 0.00 or 0.15.
    HERITAGE_CONFLICT_PENALTY: float = 0.15

    # =========================================================================
    # Gate Thresholds (from BuildSpec Section 2.5, Table 4)
    # =========================================================================

    #: Safety-critical queries need >= 0.85 to PASS.
    SAFETY_PASS_THRESHOLD: float = 0.85

    #: General queries need >= 0.70 to PASS.
    GENERAL_PASS_THRESHOLD: float = 0.70

    #: Below 0.50 is always REFUSE.
    REFUSE_THRESHOLD: float = 0.50

    # =========================================================================
    # Staleness Tiers
    # =========================================================================

    #: Maximum staleness factor (>20 years).
    MAX_STALENESS_FACTOR: int = 3

    def calculate(
        self,
        environment: EnvironmentSpec,
        evidence_rows: List[EvidenceRow],
        dirty_fraction: float,
        heritage_veto_active: bool,
        safety_critical: bool,
    ) -> ConfidenceResult:
        """Calculate confidence score with all penalties.

        Args:
            environment: Query environment specification.
            evidence_rows: Evidence records supporting the recommendation.
            dirty_fraction: Proportion of dirty records (0.0-1.0).
            heritage_veto_active: True if heritage veto applies.
            safety_critical: True if O2/H2/cryo/high-pressure context.

        Returns:
            ConfidenceResult with score, penalties breakdown,
            gate_action, and human-readable explanation.
        """
        penalties: dict[str, float] = {}
        penalty_details: list[PenaltyDetail] = []
        explanations: list[str] = []

        # --- Penalty 1: Unknown environment fields ---
        env_penalty, env_explanation = self._compute_unknown_env_penalty(environment)
        penalties["unknown_env"] = env_penalty
        if env_penalty > 0:
            penalty_details.append(PenaltyDetail(
                penalty_type="unknown_env",
                penalty_value=env_penalty,
                explanation=env_explanation,
            ))
            explanations.append(env_explanation)

        # --- Penalty 2: Data staleness ---
        stale_penalty, stale_explanation = self._compute_staleness_penalty(evidence_rows)
        penalties["staleness"] = stale_penalty
        if stale_penalty > 0:
            penalty_details.append(PenaltyDetail(
                penalty_type="staleness",
                penalty_value=stale_penalty,
                explanation=stale_explanation,
            ))
            explanations.append(stale_explanation)

        # --- Penalty 3: Sparse evidence ---
        sparse_penalty, sparse_explanation = self._compute_sparse_evidence_penalty(
            evidence_rows
        )
        penalties["sparse_evidence"] = sparse_penalty
        if sparse_penalty > 0:
            penalty_details.append(PenaltyDetail(
                penalty_type="sparse_evidence",
                penalty_value=sparse_penalty,
                explanation=sparse_explanation,
            ))
            explanations.append(sparse_explanation)

        # --- Penalty 4: Dirty data ---
        dirty_penalty, dirty_explanation = self._compute_dirty_data_penalty(
            dirty_fraction
        )
        penalties["dirty_data"] = dirty_penalty
        if dirty_penalty > 0:
            penalty_details.append(PenaltyDetail(
                penalty_type="dirty_data",
                penalty_value=dirty_penalty,
                explanation=dirty_explanation,
            ))
            explanations.append(dirty_explanation)

        # --- Penalty 5: Heritage conflict ---
        heritage_penalty, heritage_explanation = self._compute_heritage_penalty(
            heritage_veto_active
        )
        penalties["heritage_conflict"] = heritage_penalty
        if heritage_penalty > 0:
            penalty_details.append(PenaltyDetail(
                penalty_type="heritage_conflict",
                penalty_value=heritage_penalty,
                explanation=heritage_explanation,
            ))
            explanations.append(heritage_explanation)

        # --- Compute final score ---
        total_penalty = sum(penalties.values())
        score = max(0.0, 1.0 - total_penalty)

        # --- Determine gate action ---
        gate_action = self._determine_gate(score, safety_critical)

        # --- Build explanation string ---
        if explanations:
            full_explanation = (
                f"Confidence: {score:.3f} ({gate_action.value}). "
                f"Penalties: {'; '.join(explanations)}"
            )
        else:
            full_explanation = (
                f"Confidence: {score:.3f} ({gate_action.value}). "
                f"No penalties applied."
            )

        result = ConfidenceResult(
            score=round(score, 6),
            penalties=penalties,
            penalty_details=penalty_details,
            gate_action=gate_action,
            safety_critical=safety_critical,
            explanation=full_explanation,
        )

        logger.debug(
            f"Confidence calculated: score={score:.3f}, "
            f"gate={gate_action.value}, safety={safety_critical}, "
            f"penalties={penalties}"
        )

        return result

    # =========================================================================
    # Penalty Computation Methods
    # =========================================================================

    def _compute_unknown_env_penalty(
        self, env: EnvironmentSpec
    ) -> Tuple[float, str]:
        """Compute penalty for missing environment fields.

        0.08 per missing field. Max 6 fields = 0.48 total.

        Per BuildSpec Section 2.4, Table 3:
            Fields: temp, pressure, O2%, fluid_medium, duration, cycles.
        """
        n_missing = env.count_missing_fields()
        penalty = self.UNKNOWN_ENV_PENALTY_PER_FIELD * n_missing

        if n_missing > 0:
            missing_names = env.get_missing_field_names()
            explanation = (
                f"Unknown environment: {n_missing} missing field(s) "
                f"({', '.join(missing_names)}), "
                f"penalty = {n_missing} x {self.UNKNOWN_ENV_PENALTY_PER_FIELD} = {penalty:.2f}"
            )
        else:
            explanation = "All environment fields specified."

        return penalty, explanation

    def _compute_staleness_penalty(
        self, evidence: List[EvidenceRow]
    ) -> Tuple[float, str]:
        """Compute penalty for data staleness.

        0.05 per staleness tier. staleness_factor:
            0 if data < 5 years
            1 if 5-10 years
            2 if 10-20 years
            3 if > 20 years
        Max penalty = 0.15.

        Uses median test year from evidence rows. If no test years
        are available, applies maximum staleness penalty.
        """
        current_year = datetime.now(timezone.utc).year

        # Collect valid test years
        years = [e.test_year for e in evidence if e.test_year is not None]

        if not years:
            # No year data available -- apply max staleness as conservative default
            staleness_factor = self.MAX_STALENESS_FACTOR
            explanation = (
                f"No test year data available. "
                f"Max staleness factor ({staleness_factor}) applied, "
                f"penalty = {staleness_factor} x {self.STALENESS_PENALTY_PER_TIER} = "
                f"{staleness_factor * self.STALENESS_PENALTY_PER_TIER:.2f}"
            )
        else:
            # Use median year
            sorted_years = sorted(years)
            mid = len(sorted_years) // 2
            if len(sorted_years) % 2 == 0:
                median_year = (sorted_years[mid - 1] + sorted_years[mid]) / 2
            else:
                median_year = sorted_years[mid]

            age = current_year - median_year

            if age < 5:
                staleness_factor = 0
            elif age < 10:
                staleness_factor = 1
            elif age < 20:
                staleness_factor = 2
            else:
                staleness_factor = 3

            explanation = (
                f"Median test year: {median_year:.0f}, age: {age:.0f}yr, "
                f"staleness tier: {staleness_factor}, "
                f"penalty = {staleness_factor} x {self.STALENESS_PENALTY_PER_TIER} = "
                f"{staleness_factor * self.STALENESS_PENALTY_PER_TIER:.2f}"
            )

        penalty = self.STALENESS_PENALTY_PER_TIER * staleness_factor
        return penalty, explanation

    def _compute_sparse_evidence_penalty(
        self, evidence: List[EvidenceRow]
    ) -> Tuple[float, str]:
        """Compute penalty for sparse evidence.

        Per BuildSpec Section 2.4:
            sparse_evidence_penalty * (1 - min(n_evidence / 5, 1.0))

        Scaled linearly from 0.20 (zero evidence) to 0.00 (5+ evidence rows).
        """
        n_evidence = len(evidence)
        scale_factor = 1.0 - min(n_evidence / 5.0, 1.0)
        penalty = self.SPARSE_EVIDENCE_PENALTY_MAX * scale_factor

        explanation = (
            f"Evidence rows: {n_evidence}, "
            f"scale factor: {scale_factor:.2f}, "
            f"penalty = {self.SPARSE_EVIDENCE_PENALTY_MAX} x {scale_factor:.2f} = {penalty:.3f}"
        )

        return round(penalty, 6), explanation

    def _compute_dirty_data_penalty(
        self, dirty_fraction: float
    ) -> Tuple[float, str]:
        """Compute penalty for dirty data.

        Per BuildSpec Section 2.4:
            dirty_data_penalty * dirty_fraction

        Scaled by dirty_fraction (proportion of matched records with
        DIRTY_DATA flag). Max penalty = 0.25 when dirty_fraction = 1.0.
        """
        dirty_fraction = max(0.0, min(1.0, dirty_fraction))
        penalty = self.DIRTY_DATA_PENALTY_MAX * dirty_fraction

        explanation = (
            f"Dirty fraction: {dirty_fraction:.2%}, "
            f"penalty = {self.DIRTY_DATA_PENALTY_MAX} x {dirty_fraction:.3f} = {penalty:.3f}"
        )

        return round(penalty, 6), explanation

    def _compute_heritage_penalty(
        self, heritage_veto_active: bool
    ) -> Tuple[float, str]:
        """Compute penalty for heritage conflict.

        Per BuildSpec Section 2.4:
            Binary: 0.00 if no conflict, 0.15 if heritage veto active.
        """
        if heritage_veto_active:
            penalty = self.HERITAGE_CONFLICT_PENALTY
            explanation = (
                f"Heritage veto active, "
                f"penalty = {self.HERITAGE_CONFLICT_PENALTY}"
            )
        else:
            penalty = 0.0
            explanation = "No heritage conflict."

        return penalty, explanation

    # =========================================================================
    # Gate Determination
    # =========================================================================

    def _determine_gate(self, score: float, safety_critical: bool) -> GateAction:
        """Determine gate action from score and safety context.

        Per BuildSpec Section 2.5, Table 4:
            >= 0.85: PASS (safety-critical contexts)
            >= 0.70: PASS (general contexts only)
            0.50 - 0.69: CLARIFY
            < 0.50: REFUSE
        """
        if score < self.REFUSE_THRESHOLD:
            return GateAction.REFUSE

        if safety_critical:
            if score >= self.SAFETY_PASS_THRESHOLD:
                return GateAction.PASS
            elif score >= self.REFUSE_THRESHOLD:
                # Between 0.50 and 0.85 for safety-critical = CLARIFY
                return GateAction.CLARIFY
        else:
            if score >= self.GENERAL_PASS_THRESHOLD:
                return GateAction.PASS
            elif score >= self.REFUSE_THRESHOLD:
                # Between 0.50 and 0.70 for general = CLARIFY
                return GateAction.CLARIFY

        return GateAction.REFUSE
