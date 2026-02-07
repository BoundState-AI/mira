#!/usr/bin/env python3
"""
Module: Adapter Output Types
Purpose: O2, H2, and MUA adapter output models

BoundState AI 2025
Version: 2.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: True
"""

# Copyright © 2025 BoundState AI. All Rights Reserved.
# Classification: BoundState Proprietary
# License: Evaluation Use Only - Authorized Pilot Program
"""
NASA-STD-6016C Compliance Module - Adapter Output Types

O2AdapterOutput: Output from O2 adapter
H2AdapterOutput: Output from H2 adapter
MUAAdapterOutput: Output from MUA adapter

IMPORTANT: Adapters emit these outputs, NOT MPRDetermination.
That's the conductor's job.

Fran Fix #1: Adapters emit signals only, conductor maps to MPRs.

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033

Author: BoundState Team
Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI <noreply@openai.com>
Co-Authored-By: Grok <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

__version__ = "2.0.0"
__safety_critical__ = True

from typing import Any, Optional

from pydantic import BaseModel, Field

from mira.compliance.models.enums import ComplianceBasis
from mira.compliance.models.evidence import EvidenceRef
from mira.compliance.models.gaps import GapSignal, OperationalConstraint


class PrecedentValidation(BaseModel):
    """
    Validation result for a precedent match.

    Used by MUA adapter to verify precedent applicability.
    """

    precedent_id: str
    """ID of the precedent being validated."""

    is_applicable: bool
    """Whether precedent is applicable to current case."""

    match_score: float = Field(ge=0.0, le=1.0)
    """How well the precedent matches (0.0-1.0)."""

    match_factors: list[str] = []
    """Factors that contributed to match."""

    mismatch_factors: list[str] = []
    """Factors that reduced match score."""

    evidence_ref: Optional[EvidenceRef] = None
    """Evidence for the precedent."""

    model_config = {"extra": "forbid"}


class O2AdapterOutput(BaseModel):
    """
    Output from O2 adapter.

    IMPORTANT: Does NOT include MPR selection. That's conductor's job.

    Fran Fix #1: Adapter emits signals, not MPRDetermination.
    """

    # Material & environment
    material_id: str
    """Canonical material identifier."""

    environment_id: str
    """Environment identifier."""

    # Twin response summary
    classification: str
    """O2 classification: 'OK', 'CAUTION', 'PROHIBITED', 'UNKNOWN'."""

    rationale: str
    """Rationale for classification."""

    # Signals (may be empty if OK)
    gap_signals: list[GapSignal] = []
    """Gap signals emitted by O2 evaluation."""

    # Evidence with source typing
    evidence_refs: list[EvidenceRef] = []
    """Evidence supporting this output."""

    # Basis recommendation
    suggested_basis: ComplianceBasis
    """Adapter's suggested compliance basis (conductor decides final)."""

    # Raw twin response for audit
    raw_response: dict[str, Any] = {}
    """Raw response from O2 twin for audit trail."""

    model_config = {"extra": "forbid"}

    def has_gaps(self) -> bool:
        """Check if any gaps were found."""
        return len(self.gap_signals) > 0

    def is_ok(self) -> bool:
        """Check if classification is OK."""
        return self.classification.upper() == "OK"

    def is_prohibited(self) -> bool:
        """Check if material is prohibited."""
        return self.classification.upper() == "PROHIBITED"

    def get_critical_gaps(self) -> list[GapSignal]:
        """Get only critical-severity gaps."""
        return [g for g in self.gap_signals if g.is_critical()]


class H2AdapterOutput(BaseModel):
    """
    Output from H2 adapter.

    IMPORTANT: Does NOT include MPR selection. That's conductor's job.

    Fran Fix #1: Adapter emits signals, not MPRDetermination.
    Fran Fix #4: Uses deterministic HEE band → severity mapping.
    Fran Fix #5: Uses canonical_name from resolver, not raw input.
    """

    # Material & environment
    material_id: str
    """Canonical material identifier."""

    environment_id: str
    """Environment identifier."""

    # Twin response summary
    verdict: str
    """H2 verdict: 'ALLOWED', 'ALLOWED_WITH_CONSTRAINTS', 'NOT_RECOMMENDED', 'UNKNOWN'."""

    confidence: float = Field(ge=0.0, le=1.0)
    """Overall confidence in verdict."""

    # Confidence split (Fran requirement)
    match_confidence: float = Field(ge=0.0, le=1.0)
    """Confidence in material matching."""

    envelope_confidence: float = Field(ge=0.0, le=1.0)
    """Confidence in envelope matching."""

    # Signals
    gap_signals: list[GapSignal] = []
    """Gap signals emitted by H2 evaluation."""

    # Constraints
    operational_constraints: list[OperationalConstraint] = []
    """Operational constraints for safe use."""

    # Evidence
    evidence_refs: list[EvidenceRef] = []
    """Evidence supporting this output."""

    # Basis (always EVIDENCE_WEIGHTED_ANALYSIS for H2)
    suggested_basis: ComplianceBasis = ComplianceBasis.EVIDENCE_WEIGHTED_ANALYSIS
    """Adapter's suggested compliance basis."""

    # H2 token match risk (from resolver)
    h2_token_match_risk: bool = False
    """Whether H2 token match risk was flagged."""

    # Raw twin response for audit
    raw_response: dict[str, Any] = {}
    """Raw response from H2 twin for audit trail."""

    model_config = {"extra": "forbid"}

    def has_gaps(self) -> bool:
        """Check if any gaps were found."""
        return len(self.gap_signals) > 0

    def has_constraints(self) -> bool:
        """Check if operational constraints exist."""
        return len(self.operational_constraints) > 0

    def is_allowed(self) -> bool:
        """Check if verdict is ALLOWED (without constraints)."""
        return self.verdict.upper() == "ALLOWED"

    def is_allowed_with_constraints(self) -> bool:
        """Check if verdict is ALLOWED_WITH_CONSTRAINTS."""
        return self.verdict.upper() == "ALLOWED_WITH_CONSTRAINTS"

    def is_not_recommended(self) -> bool:
        """Check if verdict is NOT_RECOMMENDED."""
        return self.verdict.upper() == "NOT_RECOMMENDED"

    def get_worst_hee_band(self) -> Optional[str]:
        """Get worst HEE band from gap signals."""
        bands = [g.hee_band for g in self.gap_signals if g.hee_band]
        if not bands:
            return None

        band_order = ["negligible", "small", "high", "severe", "extreme"]
        worst_idx = -1
        worst_band = None

        for band in bands:
            if band.lower() in band_order:
                idx = band_order.index(band.lower())
                if idx > worst_idx:
                    worst_idx = idx
                    worst_band = band.lower()

        return worst_band


class MUAAdapterOutput(BaseModel):
    """
    Output from MUA adapter.

    IMPORTANT: LLM drafts TEXT only, never sets compliance status.

    Fran Fix #7: Includes LLM invocation tracking for reproducibility.
    """

    # Material & environment
    material_id: str
    """Canonical material identifier."""

    environment_id: str
    """Environment identifier."""

    triggering_gap_ids: list[str]
    """IDs of gaps that triggered MUA generation."""

    # Categorization (deterministic, rule-based)
    category: int = Field(ge=1, le=3)
    """MUA category (1, 2, or 3)."""

    category_rule_id: str
    """ID of rule that determined category."""

    category_reasoning_trace: list[dict[str, Any]] = []
    """Trace of category determination for audit."""

    # Precedent validation (deterministic gates)
    precedent_validations: list[PrecedentValidation] = []
    """Results of precedent validation checks."""

    # LLM draft (text only)
    draft_text: str
    """LLM-generated draft text."""

    # Evidence
    evidence_refs: list[EvidenceRef] = []
    """Evidence supporting this MUA."""

    model_config = {"extra": "forbid"}

    def has_applicable_precedents(self) -> bool:
        """Check if any precedents are applicable."""
        return any(p.is_applicable for p in self.precedent_validations)

    def get_best_precedent(self) -> Optional[PrecedentValidation]:
        """Get highest-scoring applicable precedent."""
        applicable = [p for p in self.precedent_validations if p.is_applicable]
        if not applicable:
            return None
        return max(applicable, key=lambda p: p.match_score)

    def is_category_1(self) -> bool:
        """Check if high-risk category."""
        return self.category == 1

    def is_category_3(self) -> bool:
        """Check if low-risk/specialized category."""
        return self.category == 3
