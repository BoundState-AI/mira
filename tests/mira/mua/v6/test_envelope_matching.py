#!/usr/bin/env python3
"""
Module: Test Envelope Matching
Purpose: Tests for Envelope Matching (MUA v6 Phase 3).

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

from mira.mua.v6.envelope_matching import (
    OverlapStatus,
    DimensionCheck,
    EnvelopeOverlapResult,
    compute_envelope_overlap,
)


class TestOverlapStatus:
    """Tests for OverlapStatus enum."""

    def test_status_values(self):
        """Status enum should have expected values."""
        assert OverlapStatus.WITHIN.value == "within"
        assert OverlapStatus.PARTIAL_OVERLAP.value == "partial"
        assert OverlapStatus.EXTRAPOLATION.value == "extrapolation"
        assert OverlapStatus.OUTSIDE.value == "outside"

    def test_all_values_are_strings(self):
        """All status values should be strings."""
        for status in OverlapStatus:
            assert isinstance(status.value, str)


class TestDimensionCheck:
    """Tests for DimensionCheck NamedTuple."""

    def test_within_check(self):
        """Should create valid within check."""
        check = DimensionCheck(
            dimension="o2_percent",
            query_value=50.0,
            precedent_bound=100.0,
            status="within",
            margin=None,
        )
        assert check.dimension == "o2_percent"
        assert check.query_value == 50.0
        assert check.precedent_bound == 100.0
        assert check.status == "within"
        assert check.margin is None

    def test_exceeds_check(self):
        """Should create valid exceeds check with margin."""
        check = DimensionCheck(
            dimension="pressure_psia",
            query_value=30.0,
            precedent_bound=20.0,
            status="exceeds",
            margin=10.0,
        )
        assert check.status == "exceeds"
        assert check.margin == 10.0

    def test_unknown_check(self):
        """Should create unknown check when precedent has no data."""
        check = DimensionCheck(
            dimension="temperature",
            query_value=70.0,
            precedent_bound=None,
            status="unknown",
            margin=None,
        )
        assert check.status == "unknown"
        assert check.precedent_bound is None


class TestEnvelopeOverlapResult:
    """Tests for EnvelopeOverlapResult model."""

    def test_within_result(self):
        """WITHIN result should be safe."""
        result = EnvelopeOverlapResult(
            status=OverlapStatus.WITHIN,
            overlap_ratio=1.0,
            dimension_checks=[],
            extrapolation_warnings=[],
            score_penalty=0.0,
        )
        assert result.is_safe
        assert not result.requires_review
        assert not result.is_blocked

    def test_partial_result(self):
        """PARTIAL_OVERLAP result should be safe."""
        result = EnvelopeOverlapResult(
            status=OverlapStatus.PARTIAL_OVERLAP,
            overlap_ratio=0.67,
            dimension_checks=[],
            extrapolation_warnings=[],
            score_penalty=0.15,
        )
        assert result.is_safe
        assert not result.requires_review
        assert not result.is_blocked

    def test_extrapolation_result(self):
        """EXTRAPOLATION result should require review."""
        result = EnvelopeOverlapResult(
            status=OverlapStatus.EXTRAPOLATION,
            overlap_ratio=0.33,
            dimension_checks=[],
            extrapolation_warnings=["Pressure exceeds by 10 PSIA"],
            score_penalty=0.4,
        )
        assert not result.is_safe
        assert result.requires_review
        assert not result.is_blocked

    def test_outside_result(self):
        """OUTSIDE result should be blocked."""
        result = EnvelopeOverlapResult(
            status=OverlapStatus.OUTSIDE,
            overlap_ratio=0.0,
            dimension_checks=[],
            extrapolation_warnings=[],
            score_penalty=1.0,
        )
        assert not result.is_safe
        assert not result.requires_review
        assert result.is_blocked

    def test_source_traceability(self):
        """Should have default source for SWE-013 compliance."""
        result = EnvelopeOverlapResult(
            status=OverlapStatus.WITHIN,
            overlap_ratio=1.0,
        )
        assert result.source == "envelope_matching"


class TestComputeEnvelopeOverlap:
    """Tests for compute_envelope_overlap function."""

    def test_within_all_bounds(self):
        """Query within all bounds should return WITHIN."""
        result = compute_envelope_overlap(
            query_o2_percent=50.0,
            query_pressure_psia=14.7,
            query_temp_f=70.0,
            precedent_o2_max=100.0,
            precedent_pressure_max=20.0,
            precedent_temp_min=0.0,
            precedent_temp_max=200.0,
        )
        assert result.status == OverlapStatus.WITHIN
        assert result.overlap_ratio == 1.0
        assert result.score_penalty == 0.0
        assert len(result.extrapolation_warnings) == 0

    def test_exceeds_o2_dimension(self):
        """Exceeding O2 should trigger extrapolation."""
        result = compute_envelope_overlap(
            query_o2_percent=100.0,
            query_pressure_psia=14.7,
            query_temp_f=70.0,
            precedent_o2_max=50.0,  # Query exceeds!
            precedent_pressure_max=20.0,
            precedent_temp_min=0.0,
            precedent_temp_max=200.0,
        )
        # 2/3 within = PARTIAL_OVERLAP
        assert result.status == OverlapStatus.PARTIAL_OVERLAP
        assert len(result.extrapolation_warnings) > 0
        assert any("O2" in w for w in result.extrapolation_warnings)

    def test_exceeds_pressure_dimension(self):
        """Exceeding pressure should trigger warning."""
        result = compute_envelope_overlap(
            query_o2_percent=50.0,
            query_pressure_psia=30.0,  # Exceeds!
            precedent_o2_max=100.0,
            precedent_pressure_max=20.0,
        )
        assert len(result.extrapolation_warnings) > 0
        assert any("PSIA" in w for w in result.extrapolation_warnings)

    def test_exceeds_multiple_dimensions(self):
        """Exceeding all dimensions should return OUTSIDE."""
        result = compute_envelope_overlap(
            query_o2_percent=100.0,
            query_pressure_psia=100.0,
            query_temp_f=500.0,
            precedent_o2_max=50.0,
            precedent_pressure_max=20.0,
            precedent_temp_max=200.0,
        )
        assert result.status == OverlapStatus.OUTSIDE
        assert result.overlap_ratio == 0.0
        assert result.score_penalty == 1.0

    def test_partial_overlap_two_of_three(self):
        """2/3 dimensions within should be PARTIAL_OVERLAP."""
        result = compute_envelope_overlap(
            query_o2_percent=50.0,  # Within
            query_pressure_psia=14.7,  # Within
            query_temp_f=300.0,  # Exceeds!
            precedent_o2_max=100.0,
            precedent_pressure_max=20.0,
            precedent_temp_max=200.0,
        )
        assert result.status == OverlapStatus.PARTIAL_OVERLAP
        assert result.overlap_ratio == pytest.approx(0.67, rel=0.1)

    def test_missing_query_dimensions(self):
        """None query values should be skipped."""
        result = compute_envelope_overlap(
            query_o2_percent=50.0,
            query_pressure_psia=None,  # Not provided
            query_temp_f=None,  # Not provided
            precedent_o2_max=100.0,
            precedent_pressure_max=20.0,
        )
        # Only O2 checked, it's within
        assert result.status == OverlapStatus.WITHIN
        assert result.overlap_ratio == 1.0

    def test_missing_precedent_bounds(self):
        """None precedent bounds should result in 'unknown' status with warning."""
        result = compute_envelope_overlap(
            query_o2_percent=50.0,
            precedent_o2_max=None,  # No envelope data
        )
        # Cannot verify coverage
        assert len(result.extrapolation_warnings) > 0
        assert any("cannot verify" in w.lower() for w in result.extrapolation_warnings)

    def test_temperature_range_within(self):
        """Temperature within min/max range should be within."""
        result = compute_envelope_overlap(
            query_temp_f=70.0,
            precedent_temp_min=-40.0,
            precedent_temp_max=200.0,
        )
        assert result.status == OverlapStatus.WITHIN

    def test_temperature_below_min(self):
        """Temperature below min should trigger warning."""
        result = compute_envelope_overlap(
            query_temp_f=-100.0,  # Below min!
            precedent_temp_min=-40.0,
            precedent_temp_max=200.0,
        )
        assert len(result.extrapolation_warnings) > 0
        assert any("below" in w.lower() for w in result.extrapolation_warnings)

    def test_temperature_above_max(self):
        """Temperature above max should trigger warning."""
        result = compute_envelope_overlap(
            query_temp_f=300.0,  # Above max!
            precedent_temp_min=-40.0,
            precedent_temp_max=200.0,
        )
        assert len(result.extrapolation_warnings) > 0
        assert any("exceeds" in w.lower() for w in result.extrapolation_warnings)

    def test_score_penalty_within(self):
        """WITHIN should have 0 penalty."""
        result = compute_envelope_overlap(
            query_o2_percent=50.0,
            precedent_o2_max=100.0,
        )
        assert result.score_penalty == 0.0

    def test_score_penalty_partial(self):
        """PARTIAL_OVERLAP should have 0.15 penalty."""
        result = compute_envelope_overlap(
            query_o2_percent=50.0,
            query_pressure_psia=14.7,
            query_temp_f=300.0,
            precedent_o2_max=100.0,
            precedent_pressure_max=20.0,
            precedent_temp_max=200.0,
        )
        assert result.score_penalty == 0.15

    def test_score_penalty_extrapolation(self):
        """EXTRAPOLATION should have 0.4 penalty."""
        result = compute_envelope_overlap(
            query_o2_percent=100.0,
            query_pressure_psia=100.0,
            query_temp_f=70.0,
            precedent_o2_max=50.0,
            precedent_pressure_max=20.0,
            precedent_temp_min=0.0,
            precedent_temp_max=200.0,
        )
        # 1/3 within = EXTRAPOLATION
        assert result.status == OverlapStatus.EXTRAPOLATION
        assert result.score_penalty == 0.4

    def test_score_penalty_outside(self):
        """OUTSIDE should have 1.0 penalty."""
        result = compute_envelope_overlap(
            query_o2_percent=100.0,
            query_pressure_psia=100.0,
            query_temp_f=500.0,
            precedent_o2_max=50.0,
            precedent_pressure_max=20.0,
            precedent_temp_max=200.0,
        )
        assert result.score_penalty == 1.0

    def test_no_query_dimensions(self):
        """No query dimensions should return OUTSIDE."""
        result = compute_envelope_overlap()
        assert result.status == OverlapStatus.OUTSIDE
        assert result.overlap_ratio == 0.0
        assert len(result.extrapolation_warnings) > 0

    def test_dimension_checks_populated(self):
        """Dimension checks should be populated."""
        result = compute_envelope_overlap(
            query_o2_percent=50.0,
            query_pressure_psia=14.7,
            precedent_o2_max=100.0,
            precedent_pressure_max=20.0,
        )
        assert len(result.dimension_checks) == 2
        dims = {c.dimension for c in result.dimension_checks}
        assert "o2_percent" in dims
        assert "pressure_psia" in dims


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
