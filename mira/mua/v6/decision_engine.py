#!/usr/bin/env python3
"""
Module: Decision Engine
Purpose: Generation decision engine for MUA drafts.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013 (Traceability), SWE-033 (Safety decisions)
Safety Critical: True
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from .envelope_matching import EnvelopeOverlapResult, OverlapStatus
from .maptis_test_data import TestDataStatus

__all__ = [
    "GenerationDecision",
    "DecisionResult",
    "MUADecisionEngine",
]

__safety_critical__ = True

LOGGER = logging.getLogger(__name__)


class GenerationDecision(str, Enum):
    """Deterministic decision for MUA generation.

    Priority order (highest to lowest):
    1. BLOCKED - Cannot proceed, fundamental issues
    2. REVIEW_REQUIRED - Human review needed before generation
    3. WARN - Can generate but with explicit warnings
    4. PROCEED - Safe to auto-generate
    """
    PROCEED = "proceed"
    WARN = "warn"
    REVIEW_REQUIRED = "review"
    BLOCKED = "blocked"


class DecisionResult(BaseModel):
    """Result of decision engine evaluation.

    SWE-013: Includes source field for traceability.
    SWE-033: Decision factors are explicitly documented.
    """
    model_config = {"extra": "forbid"}

    decision: GenerationDecision = Field(description="The generation decision")
    reasons: list[str] = Field(
        default_factory=list,
        description="Human-readable explanation of decision"
    )
    blocking_factors: list[str] = Field(
        default_factory=list,
        description="Factors that triggered BLOCKED decision"
    )
    review_factors: list[str] = Field(
        default_factory=list,
        description="Factors that triggered REVIEW_REQUIRED"
    )
    warning_factors: list[str] = Field(
        default_factory=list,
        description="Factors that triggered WARN"
    )
    confidence_score: float = Field(
        ge=0.0, le=1.0, default=0.0,
        description="Confidence in the decision (0=no confidence, 1=high)"
    )
    source: str = Field(
        default="MUADecisionEngine",
        description="SWE-013: Source for traceability"
    )

    @property
    def can_auto_generate(self) -> bool:
        """True if system can auto-generate without human review.

        Only PROCEED allows fully automatic generation.
        """
        return self.decision == GenerationDecision.PROCEED

    @property
    def requires_human(self) -> bool:
        """True if human review or action is required.

        Both REVIEW_REQUIRED and BLOCKED require human involvement.
        """
        return self.decision in (
            GenerationDecision.REVIEW_REQUIRED,
            GenerationDecision.BLOCKED,
        )

    @property
    def can_generate_with_warnings(self) -> bool:
        """True if can generate but should include warnings.

        Both PROCEED and WARN allow generation (WARN with warnings).
        """
        return self.decision in (
            GenerationDecision.PROCEED,
            GenerationDecision.WARN,
        )


class MUADecisionEngine:
    """Evaluate all factors and return deterministic generation decision.

    Decision logic (evaluated in priority order):
    1. BLOCKED: No precedents, outside envelope, unresolved material
    2. REVIEW_REQUIRED: Conflicting precedents, all data expired, extrapolation
    3. WARN: Mixed data currency, partial overlap, low confidence
    4. PROCEED: All checks pass

    SWE-013: All evaluations are logged with factors.
    SWE-033: Safety-critical decisions require explicit human review.

    Example:
        >>> engine = MUADecisionEngine()
        >>> result = engine.evaluate(
        ...     supporting_count=3,
        ...     conflicting_count=0,
        ...     envelope_result=envelope_result,
        ...     test_data_status=test_status,
        ...     material_resolved=True,
        ... )
        >>> if result.can_auto_generate:
        ...     print("Safe to proceed")
    """

    # Minimum supporting precedents for high confidence
    MIN_SUPPORTING_PRECEDENTS: int = 2

    # Threshold for weak precedent similarity (FAISS L2 distance - lower is better)
    MAX_GOOD_PRECEDENT_SCORE: float = 1.5

    def evaluate(
        self,
        supporting_count: int,
        conflicting_count: int,
        envelope_result: Optional[EnvelopeOverlapResult],
        test_data_status: Optional[TestDataStatus],
        material_resolved: bool,
        avg_precedent_score: float = 0.0,
    ) -> DecisionResult:
        """Evaluate all factors and return generation decision.

        Args:
            supporting_count: Number of APPROVED/APPROVED_WITH_LIMITS precedents.
            conflicting_count: Number of REJECTED precedents.
            envelope_result: Result of envelope overlap computation.
            test_data_status: MAPTIS test data validation result.
            material_resolved: Whether material was resolved by lookup service.
            avg_precedent_score: Average similarity score of precedents
                (lower = better match in FAISS L2 distance).

        Returns:
            DecisionResult with decision and detailed factors.

        SWE-033: Decisions are logged for audit trail.
        """
        result = DecisionResult(decision=GenerationDecision.PROCEED)

        # === PHASE 1: Check BLOCKING conditions ===
        self._check_blocking_conditions(
            result=result,
            supporting_count=supporting_count,
            material_resolved=material_resolved,
            envelope_result=envelope_result,
        )

        if result.blocking_factors:
            result.decision = GenerationDecision.BLOCKED
            result.reasons = result.blocking_factors
            result.confidence_score = 0.0
            LOGGER.warning(
                "MUA generation BLOCKED",
                extra={"factors": result.blocking_factors},
            )
            return result

        # === PHASE 2: Check REVIEW_REQUIRED conditions ===
        self._check_review_conditions(
            result=result,
            supporting_count=supporting_count,
            conflicting_count=conflicting_count,
            envelope_result=envelope_result,
            test_data_status=test_data_status,
        )

        if result.review_factors:
            result.decision = GenerationDecision.REVIEW_REQUIRED
            result.reasons = result.review_factors
            result.confidence_score = 0.3
            LOGGER.info(
                "MUA generation requires REVIEW",
                extra={"factors": result.review_factors},
            )
            return result

        # === PHASE 3: Check WARNING conditions ===
        self._check_warning_conditions(
            result=result,
            envelope_result=envelope_result,
            test_data_status=test_data_status,
            avg_precedent_score=avg_precedent_score,
        )

        if result.warning_factors:
            result.decision = GenerationDecision.WARN
            result.reasons = result.warning_factors
            result.confidence_score = 0.6
            LOGGER.info(
                "MUA generation proceeding with WARNINGS",
                extra={"factors": result.warning_factors},
            )
            return result

        # === PHASE 4: All checks passed - PROCEED ===
        result.decision = GenerationDecision.PROCEED
        result.reasons = [
            f"{supporting_count} supporting precedent(s) found",
            "Material identity resolved",
            "Query within precedent envelope bounds",
        ]
        result.confidence_score = 0.85

        LOGGER.info(
            "MUA generation PROCEEDING",
            extra={
                "supporting_count": supporting_count,
                "confidence": result.confidence_score,
            },
        )

        return result

    def _check_blocking_conditions(
        self,
        result: DecisionResult,
        supporting_count: int,
        material_resolved: bool,
        envelope_result: Optional[EnvelopeOverlapResult],
    ) -> None:
        """Check conditions that block generation entirely.

        Blocking conditions (any triggers BLOCKED):
        - No supporting precedents
        - Material could not be resolved
        - Query completely outside all precedent envelopes
        """
        if supporting_count == 0:
            result.blocking_factors.append(
                "No supporting (APPROVED/APPROVED_WITH_LIMITS) precedents found - "
                "cannot generate MUA without precedent basis"
            )

        if not material_resolved:
            result.blocking_factors.append(
                "Material identity could not be resolved - "
                "cannot verify family match or lookup test data"
            )

        if envelope_result and envelope_result.status == OverlapStatus.OUTSIDE:
            result.blocking_factors.append(
                "Query environment completely outside all precedent tested envelopes - "
                "no basis for extrapolation"
            )

    def _check_review_conditions(
        self,
        result: DecisionResult,
        supporting_count: int,
        conflicting_count: int,
        envelope_result: Optional[EnvelopeOverlapResult],
        test_data_status: Optional[TestDataStatus],
    ) -> None:
        """Check conditions requiring human review before generation.

        Review conditions (any triggers REVIEW_REQUIRED):
        - Conflicting precedents exist (REJECTED for similar config)
        - All test data is expired (no current validation)
        - Query extrapolates beyond precedent bounds
        - Insufficient supporting precedents
        """
        if conflicting_count > 0:
            result.review_factors.append(
                f"{conflicting_count} conflicting (REJECTED) precedent(s) found - "
                "similar configurations have been denied before"
            )

        if test_data_status is not None:
            # All expired: has_current_data=False AND has_expired_data=True
            if not test_data_status.has_current_data and test_data_status.has_expired_data:
                result.review_factors.append(
                    f"All {test_data_status.total_records} MAPTIS test record(s) are expired "
                    "(flam_dataexpireflag=1) - no current test validation available"
                )

        if envelope_result and envelope_result.status == OverlapStatus.EXTRAPOLATION:
            # Add specific extrapolation warnings
            for warning in envelope_result.extrapolation_warnings:
                result.review_factors.append(f"Envelope extrapolation: {warning}")

        if supporting_count < self.MIN_SUPPORTING_PRECEDENTS:
            result.review_factors.append(
                f"Only {supporting_count} supporting precedent(s) found, "
                f"minimum {self.MIN_SUPPORTING_PRECEDENTS} recommended for high confidence"
            )

    def _check_warning_conditions(
        self,
        result: DecisionResult,
        envelope_result: Optional[EnvelopeOverlapResult],
        test_data_status: Optional[TestDataStatus],
        avg_precedent_score: float,
    ) -> None:
        """Check conditions that trigger warnings but allow generation.

        Warning conditions (any triggers WARN):
        - Mixed currency (both current and expired data)
        - Unknown currency (data exists but no flag)
        - Partial envelope overlap
        - Weak precedent similarity scores
        """
        if test_data_status is not None:
            # Mixed currency: has both current AND expired
            if test_data_status.has_current_data and test_data_status.has_expired_data:
                # Estimate expired count if we have totals
                # Note: expired_results only populated if include_expired=True was used
                expired_count = len(test_data_status.expired_results)
                current_count = len(test_data_status.current_results)
                if test_data_status.total_records > 0:
                    result.warning_factors.append(
                        f"Mixed test data currency - {current_count} current, "
                        f"{expired_count} expired records in results"
                    )
                else:
                    result.warning_factors.append(
                        "Mixed test data currency detected (both current and expired exist)"
                    )

            # Unknown currency: no current, no expired, but records exist
            if (not test_data_status.has_current_data and
                not test_data_status.has_expired_data and
                test_data_status.total_records > 0):
                result.warning_factors.append(
                    f"Test data currency unknown for {test_data_status.total_records} record(s) - "
                    "flam_dataexpireflag not set"
                )

        if envelope_result and envelope_result.status == OverlapStatus.PARTIAL_OVERLAP:
            result.warning_factors.append(
                f"Partial envelope coverage ({envelope_result.overlap_ratio:.0%}) - "
                "some dimensions not fully verified"
            )
            # Add specific dimension warnings
            for warning in envelope_result.extrapolation_warnings:
                if "cannot verify" in warning.lower():
                    result.warning_factors.append(warning)

        # Check precedent quality (lower FAISS L2 score = better match)
        if avg_precedent_score > self.MAX_GOOD_PRECEDENT_SCORE:
            result.warning_factors.append(
                f"Average precedent similarity score {avg_precedent_score:.2f} indicates weak match "
                f"(threshold: {self.MAX_GOOD_PRECEDENT_SCORE:.1f}, lower is better)"
            )
