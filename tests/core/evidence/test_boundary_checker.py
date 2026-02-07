#!/usr/bin/env python3
"""
Module: Test Boundary Checker
Purpose: Tests for BoundaryChecker - Deterministic BOK Limit Checking

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013 (traceability), SWE-033 (deterministic safety)
Safety Critical: False
"""

import pytest
from core.evidence.boundary_checker import (
    BOKBoundaryChecker,
    BOKLimit,
    BoundaryCheckResult,
    BoundaryVerdict,
    check_material_boundary,
    get_boundary_checker,
)


class TestBOKBoundaryChecker:
    """Test suite for BOKBoundaryChecker."""

    @pytest.fixture
    def checker(self):
        """Create a checker with default limits."""
        return BOKBoundaryChecker()

    def test_aluminum_oxygen_within_limit(self, checker):
        """Aluminum at 2000 psia should be within static limit (3000 psia)."""
        result = checker.check_pressure_limit(
            query_pressure=2000.0,
            material="aluminum 6061",
            environment="oxygen",
            configuration="static"
        )
        assert result.verdict == BoundaryVerdict.WITHIN_LIMITS
        assert result.margin > 0  # Positive margin means within limit
        assert "NASA-STD-6016C" in result.evidence_sources[0]

    def test_aluminum_oxygen_exceeds_limit(self, checker):
        """Aluminum at 5000 psia should exceed static limit (3000 psia)."""
        result = checker.check_pressure_limit(
            query_pressure=5000.0,
            material="aluminum 6061",
            environment="oxygen",
            configuration="static"
        )
        assert result.verdict == BoundaryVerdict.EXCEEDS_LIMIT
        assert result.margin < 0  # Negative margin means exceeded
        assert result.is_prohibited is True

    def test_aluminum_dynamic_lower_limit(self, checker):
        """Aluminum at 150 psia should exceed dynamic limit (100 psia)."""
        result = checker.check_pressure_limit(
            query_pressure=150.0,
            material="aluminum 6061",
            environment="oxygen",
            configuration="dynamic"
        )
        assert result.verdict == BoundaryVerdict.EXCEEDS_LIMIT
        assert result.is_prohibited is True

    def test_titanium_always_low_limit(self, checker):
        """Titanium at 200 psia should exceed limit (100 psia for all configs)."""
        result = checker.check_pressure_limit(
            query_pressure=200.0,
            material="titanium 6al-4v",
            environment="oxygen"
        )
        assert result.verdict == BoundaryVerdict.EXCEEDS_LIMIT
        assert result.is_prohibited is True

    def test_stainless_steel_high_pressure_ok(self, checker):
        """Stainless 316 at 6000 psia should be within limit (10000 psia)."""
        result = checker.check_pressure_limit(
            query_pressure=6000.0,
            material="ss 316",
            environment="oxygen"
        )
        assert result.verdict == BoundaryVerdict.WITHIN_LIMITS
        assert result.is_safe is True

    def test_unknown_material_no_data(self, checker):
        """Unknown material should return NO_DATA verdict."""
        result = checker.check_pressure_limit(
            query_pressure=1000.0,
            material="unobtainium",
            environment="oxygen"
        )
        assert result.verdict == BoundaryVerdict.NO_DATA

    def test_material_family_normalization(self, checker):
        """Test material name to family normalization."""
        # SS 316 -> stainless_steel_300
        assert checker._normalize_material_family("SS 316") == "stainless_steel_300"
        assert checker._normalize_material_family("stainless steel 316L") == "stainless_steel_300"
        assert checker._normalize_material_family("CRES 321") == "stainless_steel_300"

        # Aluminum variants
        assert checker._normalize_material_family("aluminum 6061") == "aluminum"
        assert checker._normalize_material_family("AL 7075") == "aluminum"

        # Titanium
        assert checker._normalize_material_family("titanium") == "titanium"
        assert checker._normalize_material_family("ti 6al-4v") == "titanium"

    def test_environment_normalization(self, checker):
        """Test environment name normalization."""
        assert checker._normalize_environment("GOX") == "oxygen"
        assert checker._normalize_environment("LOX") == "oxygen"
        assert checker._normalize_environment("gaseous oxygen") == "oxygen"
        assert checker._normalize_environment("O2") == "oxygen"

        assert checker._normalize_environment("GH2") == "hydrogen"
        assert checker._normalize_environment("liquid hydrogen") == "hydrogen"

    def test_convenience_function(self):
        """Test module-level convenience function."""
        result = check_material_boundary(
            material="aluminum",
            environment="oxygen",
            pressure=200.0
        )
        assert result.verdict in [
            BoundaryVerdict.WITHIN_LIMITS,
            BoundaryVerdict.EXCEEDS_LIMIT,
            BoundaryVerdict.NO_DATA
        ]

    def test_check_all_limits(self, checker):
        """Test checking multiple limits at once."""
        results = checker.check_all_limits(
            material="aluminum 6061",
            environment="oxygen",
            pressure=200.0,
            temperature=100.0
        )
        assert len(results) >= 1
        # Should have at least one pressure check result

    def test_get_worst_result(self, checker):
        """Test selecting the most restrictive result."""
        results = [
            BoundaryCheckResult(verdict=BoundaryVerdict.WITHIN_LIMITS, rationale="OK"),
            BoundaryCheckResult(verdict=BoundaryVerdict.EXCEEDS_LIMIT, rationale="BAD"),
            BoundaryCheckResult(verdict=BoundaryVerdict.NO_DATA, rationale="UNKNOWN"),
        ]
        worst = checker.get_worst_result(results)
        assert worst.verdict == BoundaryVerdict.EXCEEDS_LIMIT

    def test_psig_to_psia_conversion(self, checker):
        """Test that PSIG is converted to PSIA for comparison."""
        # 100 psig = 114.7 psia
        result = checker.check_pressure_limit(
            query_pressure=100.0,
            material="titanium",
            environment="oxygen",
            pressure_units="psig"
        )
        # 114.7 psia > 100 psia limit, so should exceed
        assert result.verdict == BoundaryVerdict.EXCEEDS_LIMIT


class TestBOKLimit:
    """Test BOKLimit dataclass."""

    def test_bok_limit_creation(self):
        """Test creating a BOKLimit."""
        limit = BOKLimit(
            material_family="aluminum",
            environment="oxygen",
            limit_type="max_pressure",
            limit_value=3000.0,
            units="psia",
            source_doc="NASA-STD-6016C",
            section_ref="4.3.2.1"
        )
        assert limit.material_family == "aluminum"
        assert limit.limit_value == 3000.0


class TestBoundaryCheckResult:
    """Test BoundaryCheckResult dataclass."""

    def test_is_safe_property(self):
        """Test is_safe property."""
        safe_result = BoundaryCheckResult(
            verdict=BoundaryVerdict.WITHIN_LIMITS,
            rationale="OK"
        )
        assert safe_result.is_safe is True
        assert safe_result.is_prohibited is False

    def test_is_prohibited_property(self):
        """Test is_prohibited property."""
        prohibited_result = BoundaryCheckResult(
            verdict=BoundaryVerdict.EXCEEDS_LIMIT,
            rationale="Exceeds limit"
        )
        assert prohibited_result.is_prohibited is True
        assert prohibited_result.is_safe is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
