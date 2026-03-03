#!/usr/bin/env python3
"""
Module: Test Decision Engine
Purpose: Tests for Decision Engine (MUA v6 Phase 4).

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

import pytest
import sys

sys.path.insert(0, r"C:\BoundState")

from mira.mua.v6.decision_engine import (
    GenerationDecision,
    DecisionResult,
    MUADecisionEngine,
)
from mira.mua.v6.envelope_matching import (
    OverlapStatus,
    EnvelopeOverlapResult,
)
from mira.mua.v6.maptis_test_data import (
    TestDataStatus,
)


class TestGenerationDecision:
    """Tests for GenerationDecision enum."""

    def test_decision_values(self):
        """Decision enum should have expected values."""
        assert GenerationDecision.PROCEED.value == "proceed"
        assert GenerationDecision.WARN.value == "warn"
        assert GenerationDecision.REVIEW_REQUIRED.value == "review"
        assert GenerationDecision.BLOCKED.value == "blocked"

    def test_all_values_are_strings(self):
        """All decision values should be strings."""
        for decision in GenerationDecision:
            assert isinstance(decision.value, str)


class TestDecisionResult:
    """Tests for DecisionResult model."""

    def test_proceed_result(self):
        """PROCEED result should allow auto-generation."""
        result = DecisionResult(
            decision=GenerationDecision.PROCEED,
            reasons=["All checks passed"],
            confidence_score=0.85,
        )
        assert result.can_auto_generate
        assert not result.requires_human
        assert result.can_generate_with_warnings

    def test_warn_result(self):
        """WARN result should allow generation with warnings."""
        result = DecisionResult(
            decision=GenerationDecision.WARN,
            reasons=["Minor concerns"],
            warning_factors=["Weak similarity"],
            confidence_score=0.6,
        )
        assert not result.can_auto_generate
        assert not result.requires_human
        assert result.can_generate_with_warnings

    def test_review_result(self):
        """REVIEW_REQUIRED should require human."""
        result = DecisionResult(
            decision=GenerationDecision.REVIEW_REQUIRED,
            reasons=["Conflicting precedent"],
            review_factors=["REJECTED precedent found"],
            confidence_score=0.3,
        )
        assert not result.can_auto_generate
        assert result.requires_human
        assert not result.can_generate_with_warnings

    def test_blocked_result(self):
        """BLOCKED should require human."""
        result = DecisionResult(
            decision=GenerationDecision.BLOCKED,
            reasons=["No precedents"],
            blocking_factors=["No supporting precedents found"],
            confidence_score=0.0,
        )
        assert not result.can_auto_generate
        assert result.requires_human
        assert not result.can_generate_with_warnings

    def test_source_traceability(self):
        """Should have default source for SWE-013 compliance."""
        result = DecisionResult(decision=GenerationDecision.PROCEED)
        assert result.source == "MUADecisionEngine"


class TestMUADecisionEngine:
    """Tests for MUADecisionEngine class."""

    def setup_method(self):
        """Create engine instance for each test."""
        self.engine = MUADecisionEngine()

    # === BLOCKED Tests ===

    def test_blocked_no_supporting_precedents(self):
        """Zero supporting precedents should block."""
        result = self.engine.evaluate(
            supporting_count=0,
            conflicting_count=0,
            envelope_result=None,
            test_data_status=None,
            material_resolved=True,
        )
        assert result.decision == GenerationDecision.BLOCKED
        assert len(result.blocking_factors) > 0
        assert any("no supporting" in f.lower() for f in result.blocking_factors)

    def test_blocked_unresolved_material(self):
        """Unresolved material should block."""
        result = self.engine.evaluate(
            supporting_count=3,
            conflicting_count=0,
            envelope_result=None,
            test_data_status=None,
            material_resolved=False,
        )
        assert result.decision == GenerationDecision.BLOCKED
        assert any("material" in f.lower() for f in result.blocking_factors)

    def test_blocked_outside_envelope(self):
        """OUTSIDE envelope status should block."""
        envelope = EnvelopeOverlapResult(
            status=OverlapStatus.OUTSIDE,
            overlap_ratio=0.0,
        )
        result = self.engine.evaluate(
            supporting_count=3,
            conflicting_count=0,
            envelope_result=envelope,
            test_data_status=None,
            material_resolved=True,
        )
        assert result.decision == GenerationDecision.BLOCKED
        assert any("outside" in f.lower() for f in result.blocking_factors)

    # === REVIEW_REQUIRED Tests ===

    def test_review_conflicting_precedents(self):
        """Conflicting precedents should require review."""
        result = self.engine.evaluate(
            supporting_count=3,
            conflicting_count=1,
            envelope_result=None,
            test_data_status=None,
            material_resolved=True,
        )
        assert result.decision == GenerationDecision.REVIEW_REQUIRED
        assert any("conflicting" in f.lower() for f in result.review_factors)

    def test_review_all_expired_data(self):
        """All expired test data should require review."""
        test_status = TestDataStatus(
            material_code="20494",
            has_current_data=False,
            has_expired_data=True,
            total_records=5,
        )
        result = self.engine.evaluate(
            supporting_count=3,
            conflicting_count=0,
            envelope_result=None,
            test_data_status=test_status,
            material_resolved=True,
        )
        assert result.decision == GenerationDecision.REVIEW_REQUIRED
        assert any("expired" in f.lower() for f in result.review_factors)

    def test_review_extrapolation_envelope(self):
        """EXTRAPOLATION envelope status should require review."""
        envelope = EnvelopeOverlapResult(
            status=OverlapStatus.EXTRAPOLATION,
            overlap_ratio=0.33,
            extrapolation_warnings=["O2 exceeds by 50%"],
        )
        result = self.engine.evaluate(
            supporting_count=3,
            conflicting_count=0,
            envelope_result=envelope,
            test_data_status=None,
            material_resolved=True,
        )
        assert result.decision == GenerationDecision.REVIEW_REQUIRED
        assert any("extrapolation" in f.lower() for f in result.review_factors)

    def test_review_insufficient_precedents(self):
        """Less than MIN_SUPPORTING_PRECEDENTS should require review."""
        result = self.engine.evaluate(
            supporting_count=1,  # Less than default MIN of 2
            conflicting_count=0,
            envelope_result=None,
            test_data_status=None,
            material_resolved=True,
        )
        assert result.decision == GenerationDecision.REVIEW_REQUIRED
        assert any("supporting precedent" in f.lower() for f in result.review_factors)

    # === WARN Tests ===

    def test_warn_mixed_currency(self):
        """Mixed current and expired data should warn."""
        test_status = TestDataStatus(
            material_code="20494",
            has_current_data=True,
            has_expired_data=True,
            total_records=10,
        )
        result = self.engine.evaluate(
            supporting_count=3,
            conflicting_count=0,
            envelope_result=None,
            test_data_status=test_status,
            material_resolved=True,
        )
        assert result.decision == GenerationDecision.WARN
        assert any("mixed" in f.lower() for f in result.warning_factors)

    def test_warn_unknown_currency(self):
        """Unknown data currency should warn."""
        test_status = TestDataStatus(
            material_code="20494",
            has_current_data=False,
            has_expired_data=False,
            total_records=5,  # Records exist but currency unknown
        )
        result = self.engine.evaluate(
            supporting_count=3,
            conflicting_count=0,
            envelope_result=None,
            test_data_status=test_status,
            material_resolved=True,
        )
        assert result.decision == GenerationDecision.WARN
        assert any("unknown" in f.lower() for f in result.warning_factors)

    def test_warn_partial_overlap(self):
        """PARTIAL_OVERLAP envelope should warn."""
        envelope = EnvelopeOverlapResult(
            status=OverlapStatus.PARTIAL_OVERLAP,
            overlap_ratio=0.67,
            extrapolation_warnings=[],
        )
        result = self.engine.evaluate(
            supporting_count=3,
            conflicting_count=0,
            envelope_result=envelope,
            test_data_status=None,
            material_resolved=True,
        )
        assert result.decision == GenerationDecision.WARN
        assert any("partial" in f.lower() for f in result.warning_factors)

    def test_warn_weak_similarity(self):
        """High avg_precedent_score (weak match) should warn."""
        result = self.engine.evaluate(
            supporting_count=3,
            conflicting_count=0,
            envelope_result=None,
            test_data_status=None,
            material_resolved=True,
            avg_precedent_score=2.0,  # Above threshold of 1.5
        )
        assert result.decision == GenerationDecision.WARN
        assert any("similarity" in f.lower() for f in result.warning_factors)

    # === PROCEED Tests ===

    def test_proceed_all_pass(self):
        """All checks passing should proceed."""
        envelope = EnvelopeOverlapResult(
            status=OverlapStatus.WITHIN,
            overlap_ratio=1.0,
        )
        test_status = TestDataStatus(
            material_code="20494",
            has_current_data=True,
            has_expired_data=False,
            total_records=5,
        )
        result = self.engine.evaluate(
            supporting_count=5,
            conflicting_count=0,
            envelope_result=envelope,
            test_data_status=test_status,
            material_resolved=True,
            avg_precedent_score=0.5,  # Good score (low = better)
        )
        assert result.decision == GenerationDecision.PROCEED
        assert result.can_auto_generate
        assert result.confidence_score > 0.8

    def test_proceed_no_test_data(self):
        """No test data (but other checks pass) can proceed."""
        envelope = EnvelopeOverlapResult(
            status=OverlapStatus.WITHIN,
            overlap_ratio=1.0,
        )
        result = self.engine.evaluate(
            supporting_count=3,
            conflicting_count=0,
            envelope_result=envelope,
            test_data_status=None,  # No test data
            material_resolved=True,
        )
        assert result.decision == GenerationDecision.PROCEED

    def test_proceed_no_envelope(self):
        """No envelope data (but other checks pass) can proceed."""
        result = self.engine.evaluate(
            supporting_count=3,
            conflicting_count=0,
            envelope_result=None,  # No envelope
            test_data_status=None,
            material_resolved=True,
        )
        assert result.decision == GenerationDecision.PROCEED

    # === Confidence Score Tests ===

    def test_confidence_blocked(self):
        """BLOCKED should have 0 confidence."""
        result = self.engine.evaluate(
            supporting_count=0,
            conflicting_count=0,
            envelope_result=None,
            test_data_status=None,
            material_resolved=True,
        )
        assert result.confidence_score == 0.0

    def test_confidence_review(self):
        """REVIEW_REQUIRED should have 0.3 confidence."""
        result = self.engine.evaluate(
            supporting_count=3,
            conflicting_count=1,
            envelope_result=None,
            test_data_status=None,
            material_resolved=True,
        )
        assert result.confidence_score == 0.3

    def test_confidence_warn(self):
        """WARN should have 0.6 confidence."""
        envelope = EnvelopeOverlapResult(
            status=OverlapStatus.PARTIAL_OVERLAP,
            overlap_ratio=0.67,
        )
        result = self.engine.evaluate(
            supporting_count=3,
            conflicting_count=0,
            envelope_result=envelope,
            test_data_status=None,
            material_resolved=True,
        )
        assert result.confidence_score == 0.6

    def test_confidence_proceed(self):
        """PROCEED should have 0.85 confidence."""
        result = self.engine.evaluate(
            supporting_count=3,
            conflicting_count=0,
            envelope_result=None,
            test_data_status=None,
            material_resolved=True,
        )
        assert result.confidence_score == 0.85

    # === Priority Order Tests ===

    def test_blocked_takes_priority_over_review(self):
        """BLOCKED conditions should override REVIEW conditions."""
        # Both: no material AND conflicting precedents
        result = self.engine.evaluate(
            supporting_count=3,
            conflicting_count=1,  # Would trigger REVIEW
            envelope_result=None,
            test_data_status=None,
            material_resolved=False,  # Triggers BLOCKED
        )
        assert result.decision == GenerationDecision.BLOCKED

    def test_review_takes_priority_over_warn(self):
        """REVIEW conditions should override WARN conditions."""
        envelope = EnvelopeOverlapResult(
            status=OverlapStatus.PARTIAL_OVERLAP,  # Would trigger WARN
            overlap_ratio=0.67,
        )
        result = self.engine.evaluate(
            supporting_count=3,
            conflicting_count=1,  # Triggers REVIEW
            envelope_result=envelope,
            test_data_status=None,
            material_resolved=True,
        )
        assert result.decision == GenerationDecision.REVIEW_REQUIRED


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
