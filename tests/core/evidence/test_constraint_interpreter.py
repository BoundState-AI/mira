#!/usr/bin/env python3
"""
Module: Test Constraint Interpreter
Purpose: Comprehensive tests for ConstraintInterpreter.

BoundState AI 2025
Version: 7
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013 (traceability), SWE-033 (deterministic safety)
Safety Critical: False
"""

from __future__ import annotations

import pytest
from dataclasses import dataclass
from typing import Optional

from core.evidence.constraint_interpreter import (
    ConstraintInterpreter,
    MaterialConstraints,
)


# ============================================================================
# TEST HELPERS
# ============================================================================


@dataclass
class ExpectedConstraints:
    """Expected values for constraint assertions."""

    material: Optional[str] = None
    environment: Optional[str] = None
    pressure_psi_max: Optional[float] = None
    pressure_psi_min: Optional[float] = None  # For range expressions
    temp_c_max: Optional[float] = None
    temp_c_min: Optional[float] = None
    o2_pct: Optional[float] = None
    configuration: Optional[str] = None
    pressure_tolerance: float = 1.0
    temp_tolerance: float = 0.5


def assert_constraints_match(
    actual: MaterialConstraints,
    expected: ExpectedConstraints,
    query: str,
) -> None:
    """Assert that actual constraints match expected values with tolerances."""
    # Material (case-insensitive)
    if expected.material is not None:
        assert actual.material is not None, f"Query '{query}': expected material but got None"
        assert expected.material.lower() in actual.material.lower(), (
            f"Query '{query}': expected material '{expected.material}' "
            f"but got '{actual.material}'"
        )

    # Environment
    if expected.environment is not None:
        assert actual.environment == expected.environment, (
            f"Query '{query}': expected environment '{expected.environment}' "
            f"but got '{actual.environment}'"
        )

    # Pressure (with tolerance)
    if expected.pressure_psi_max is not None:
        assert actual.pressure_psi_max is not None, (
            f"Query '{query}': expected pressure but got None"
        )
        assert abs(actual.pressure_psi_max - expected.pressure_psi_max) <= expected.pressure_tolerance, (
            f"Query '{query}': expected pressure ~{expected.pressure_psi_max} psi "
            f"but got {actual.pressure_psi_max} psi"
        )

    # Temperature (with tolerance)
    if expected.temp_c_max is not None:
        assert actual.temp_c_max is not None, (
            f"Query '{query}': expected temp_c_max but got None"
        )
        assert abs(actual.temp_c_max - expected.temp_c_max) <= expected.temp_tolerance, (
            f"Query '{query}': expected temp ~{expected.temp_c_max} C "
            f"but got {actual.temp_c_max} C"
        )

    if expected.temp_c_min is not None:
        assert actual.temp_c_min is not None, (
            f"Query '{query}': expected temp_c_min but got None"
        )
        assert abs(actual.temp_c_min - expected.temp_c_min) <= expected.temp_tolerance, (
            f"Query '{query}': expected temp_c_min ~{expected.temp_c_min} C "
            f"but got {actual.temp_c_min} C"
        )


@pytest.fixture
def interpreter():
    """Create ConstraintInterpreter instance."""
    return ConstraintInterpreter()


# ============================================================================
# TEST CLASS: Unit Conversion (7 tests)
# ============================================================================


class TestUnitConversion:
    """Test pressure and temperature unit conversions."""

    def test_psi_direct(self, interpreter):
        """PSI should be used directly without conversion."""
        query = "aluminum 6061 at 200 psi"
        result = interpreter.parse_query(query)
        assert_constraints_match(
            result,
            ExpectedConstraints(material="aluminum 6061", pressure_psi_max=200.0),
            query,
        )

    @pytest.mark.xfail(reason="psig vs psia conversion not implemented")
    def test_psig_vs_psia(self, interpreter):
        """CRITICAL: 200 psig = 214.7 psia (atmospheric offset)."""
        query = "aluminum at 200 psig"
        result = interpreter.parse_query(query)
        # psig = psia - 14.7, so 200 psig = 214.7 psia
        assert_constraints_match(
            result,
            ExpectedConstraints(pressure_psi_max=214.7, pressure_tolerance=0.1),
            query,
        )

    def test_bar_to_psi(self, interpreter):
        """Bar should convert to PSI (1 bar = 14.504 psi)."""
        query = "stainless steel at 10 bar"
        result = interpreter.parse_query(query)
        assert_constraints_match(
            result,
            ExpectedConstraints(pressure_psi_max=145.04, pressure_tolerance=1.0),
            query,
        )

    def test_mpa_to_psi(self, interpreter):
        """MPa should convert to PSI (1 MPa = 145.04 psi)."""
        query = "inconel 718 at 20 mpa"
        result = interpreter.parse_query(query)
        assert_constraints_match(
            result,
            ExpectedConstraints(pressure_psi_max=2900.8, pressure_tolerance=5.0),
            query,
        )

    def test_kpa_to_psi(self, interpreter):
        """kPa should convert to PSI (1 kPa = 0.145 psi)."""
        query = "titanium at 1000 kpa"
        result = interpreter.parse_query(query)
        assert_constraints_match(
            result,
            ExpectedConstraints(pressure_psi_max=145.0, pressure_tolerance=1.0),
            query,
        )

    def test_fahrenheit_to_celsius(self, interpreter):
        """Fahrenheit should convert to Celsius."""
        query = "aluminum at 200 F"
        result = interpreter.parse_query(query)
        # 200 F = 93.33 C
        assert_constraints_match(
            result,
            ExpectedConstraints(temp_c_max=93.33, temp_tolerance=0.5),
            query,
        )

    def test_kelvin_to_celsius(self, interpreter):
        """Kelvin should convert to Celsius."""
        query = "stainless steel at 300 K"
        result = interpreter.parse_query(query)
        # 300 K = 26.85 C
        assert_constraints_match(
            result,
            ExpectedConstraints(temp_c_max=26.85, temp_tolerance=0.5),
            query,
        )


# ============================================================================
# TEST CLASS: Range Expressions (5 tests - all xfail)
# ============================================================================


class TestRangeExpressions:
    """Test range expression parsing - documents needed features."""

    @pytest.mark.xfail(reason="Range parsing not implemented")
    def test_hyphenated_range(self, interpreter):
        """'50-200 psi' should extract min/max."""
        query = "aluminum 6061 at 50-200 psi"
        result = interpreter.parse_query(query)
        assert result.pressure_psi_min == 50.0
        assert result.pressure_psi_max == 200.0

    @pytest.mark.xfail(reason="Range parsing not implemented")
    def test_between_expression(self, interpreter):
        """'between 100 and 500 psi' should extract range."""
        query = "stainless steel between 100 and 500 psi"
        result = interpreter.parse_query(query)
        assert result.pressure_psi_min == 100.0
        assert result.pressure_psi_max == 500.0

    @pytest.mark.xfail(reason="'above' keyword not implemented")
    def test_above_expression(self, interpreter):
        """'above 100 psi' should set min, not max."""
        query = "inconel 718 above 100 psi"
        result = interpreter.parse_query(query)
        assert result.pressure_psi_min == 100.0
        assert result.pressure_psi_max is None

    @pytest.mark.xfail(reason="'below' keyword not implemented")
    def test_below_expression(self, interpreter):
        """'below 500 psi' should set max only."""
        query = "titanium below 500 psi"
        result = interpreter.parse_query(query)
        assert result.pressure_psi_max == 500.0
        assert result.pressure_psi_min is None

    @pytest.mark.xfail(reason="Temperature range not implemented")
    def test_temperature_range(self, interpreter):
        """Temperature range should extract min and max."""
        query = "aluminum from -40 to 200 F"
        result = interpreter.parse_query(query)
        # -40 F = -40 C, 200 F = 93.33 C
        assert result.temp_c_min == pytest.approx(-40.0, abs=0.5)
        assert result.temp_c_max == pytest.approx(93.33, abs=0.5)


# ============================================================================
# TEST CLASS: Environment Detection (12 tests)
# ============================================================================


class TestEnvironmentDetection:
    """Test gas/environment detection from query text."""

    def test_oxygen_keyword(self, interpreter):
        """'oxygen' should detect oxygen environment."""
        query = "aluminum for oxygen service"
        result = interpreter.parse_query(query)
        assert result.environment == "oxygen"

    def test_gox_abbreviation(self, interpreter):
        """'GOX' should detect gaseous oxygen."""
        query = "stainless steel in GOX"
        result = interpreter.parse_query(query)
        assert result.environment == "oxygen"

    def test_lox_abbreviation(self, interpreter):
        """'LOX' should detect liquid oxygen."""
        query = "inconel 718 for LOX systems"
        result = interpreter.parse_query(query)
        assert result.environment == "oxygen"

    def test_o2_formula(self, interpreter):
        """'O2' should detect oxygen."""
        query = "titanium compatible with O2"
        result = interpreter.parse_query(query)
        assert result.environment == "oxygen"

    def test_o2_unicode_subscript(self, interpreter):
        """'O₂' (unicode subscript) should detect oxygen."""
        query = "aluminum 6061 in O₂ environment"
        result = interpreter.parse_query(query)
        assert result.environment == "oxygen"

    def test_hydrogen_keyword(self, interpreter):
        """'hydrogen' should detect hydrogen environment."""
        query = "stainless steel 316 for hydrogen service"
        result = interpreter.parse_query(query)
        assert result.environment == "hydrogen"

    def test_gh2_abbreviation(self, interpreter):
        """'GH2' should detect gaseous hydrogen."""
        query = "inconel in GH2 systems"
        result = interpreter.parse_query(query)
        assert result.environment == "hydrogen"

    def test_lh2_abbreviation(self, interpreter):
        """'LH2' should detect liquid hydrogen."""
        query = "aluminum 2219 for LH2 tanks"
        result = interpreter.parse_query(query)
        assert result.environment == "hydrogen"

    def test_h2_formula(self, interpreter):
        """'H2' should detect hydrogen."""
        query = "titanium in H2 environment"
        result = interpreter.parse_query(query)
        assert result.environment == "hydrogen"

    def test_vacuum_keyword(self, interpreter):
        """'vacuum' should detect vacuum environment."""
        query = "kapton in vacuum"
        result = interpreter.parse_query(query)
        assert result.environment == "vacuum"

    @pytest.mark.xfail(reason="Oxygen enriched air detection not implemented")
    def test_oxygen_enriched_air(self, interpreter):
        """'oxygen enriched' should detect oxygen environment."""
        query = "aluminum in oxygen enriched atmosphere"
        result = interpreter.parse_query(query)
        assert result.environment == "oxygen"

    @pytest.mark.xfail(reason="O2 percentage detection not implemented")
    def test_oxygen_percentage_above_threshold(self, interpreter):
        """>23.5% O2 is considered oxygen service."""
        query = "material compatibility at 30% oxygen"
        result = interpreter.parse_query(query)
        assert result.environment == "oxygen"
        assert result.o2_pct == 30.0


# ============================================================================
# TEST CLASS: Material Extraction (11 tests)
# ============================================================================


class TestMaterialExtraction:
    """Test material name extraction from queries."""

    def test_stainless_steel_with_alloy(self, interpreter):
        """'stainless steel 316' should extract full designation."""
        query = "stainless steel 316 for oxygen"
        result = interpreter.parse_query(query)
        assert result.material is not None
        assert "316" in result.material

    def test_aluminum_with_temper(self, interpreter):
        """'aluminum 6061-T6' should extract with temper."""
        query = "aluminum 6061-T6 at 200 psi"
        result = interpreter.parse_query(query)
        assert result.material is not None
        assert "6061" in result.material

    def test_inconel_alloy(self, interpreter):
        """'inconel 718' should extract correctly."""
        query = "inconel 718 for high temp"
        result = interpreter.parse_query(query)
        assert result.material is not None
        assert "inconel" in result.material.lower()
        assert "718" in result.material

    def test_ss_abbreviation(self, interpreter):
        """'SS 316' abbreviation should be recognized."""
        query = "SS 316 in oxygen service"
        result = interpreter.parse_query(query)
        assert result.material is not None
        assert "316" in result.material

    def test_cres_abbreviation(self, interpreter):
        """'CRES 316' abbreviation should be recognized."""
        query = "CRES 316L for GOX"
        result = interpreter.parse_query(query)
        assert result.material is not None
        assert "316" in result.material

    def test_al_abbreviation(self, interpreter):
        """'AL 6061' abbreviation should be recognized."""
        query = "AL 6061 at 500 psi"
        result = interpreter.parse_query(query)
        assert result.material is not None
        assert "6061" in result.material

    def test_polymer_viton(self, interpreter):
        """'viton' polymer should be extracted."""
        query = "viton seals in oxygen"
        result = interpreter.parse_query(query)
        assert result.material is not None
        assert "viton" in result.material.lower()

    def test_polymer_teflon(self, interpreter):
        """'teflon' should be extracted."""
        query = "teflon tape for oxygen"
        result = interpreter.parse_query(query)
        assert result.material is not None
        assert "teflon" in result.material.lower()

    def test_polymer_kapton(self, interpreter):
        """'kapton' should be extracted."""
        query = "kapton film in vacuum"
        result = interpreter.parse_query(query)
        assert result.material is not None
        assert "kapton" in result.material.lower()

    def test_generic_aluminum(self, interpreter):
        """Generic 'aluminum' without alloy should be captured."""
        query = "is aluminum compatible with oxygen"
        result = interpreter.parse_query(query)
        assert result.material is not None
        assert "aluminum" in result.material.lower()

    def test_unknown_material_fallback(self, interpreter):
        """Unknown material name should use fallback pattern."""
        query = "can unobtainium-42 be used in oxygen"
        result = interpreter.parse_query(query)
        # Should either extract the material or return None gracefully
        # Don't crash on unknown materials
        assert isinstance(result, MaterialConstraints)


# ============================================================================
# TEST CLASS: Compound Queries (3 tests)
# ============================================================================


class TestCompoundQueries:
    """Test queries with multiple materials or complex structure."""

    @pytest.mark.xfail(reason="Multiple material extraction not implemented")
    def test_multiple_materials_or(self, interpreter):
        """'SS316 or Inconel 625' should extract both materials."""
        query = "SS 316 or inconel 625 for oxygen"
        result = interpreter.parse_query(query)
        # Current implementation only extracts first match
        # This documents the limitation
        assert "316" in str(result.material) or "625" in str(result.material)

    def test_material_with_environment_and_pressure(self, interpreter):
        """Complex query with material, environment, pressure."""
        query = "stainless steel 316 for oxygen service at 3000 psi"
        result = interpreter.parse_query(query)
        assert result.material is not None
        assert "316" in result.material
        assert result.environment == "oxygen"
        assert result.pressure_psi_max is not None
        assert abs(result.pressure_psi_max - 3000.0) < 1.0

    @pytest.mark.xfail(reason="Comparison queries not implemented")
    def test_comparison_query(self, interpreter):
        """'compare X and Y' should extract both materials."""
        query = "compare aluminum 6061 and titanium for oxygen"
        result = interpreter.parse_query(query)
        # Document that comparison queries need special handling
        assert result.material is not None


# ============================================================================
# TEST CLASS: Edge Cases and Boundaries (10 tests)
# ============================================================================


class TestEdgeCasesAndBoundaries:
    """Test edge cases, boundaries, and error handling."""

    def test_empty_query(self, interpreter):
        """Empty query should return empty constraints without crashing."""
        result = interpreter.parse_query("")
        assert result.material is None
        assert result.environment is None
        assert result.pressure_psi_max is None

    def test_whitespace_only_query(self, interpreter):
        """Whitespace-only query should return empty constraints."""
        result = interpreter.parse_query("   \t\n  ")
        assert result.material is None

    def test_no_constraints_query(self, interpreter):
        """Query with no extractable constraints should return None values."""
        result = interpreter.parse_query("hello world")
        assert result.material is None
        assert result.environment is None
        assert result.pressure_psi_max is None

    def test_extreme_pressure_value(self, interpreter):
        """Very high pressure values should be accepted."""
        query = "inconel at 50000 psi"
        result = interpreter.parse_query(query)
        assert result.pressure_psi_max == 50000.0

    def test_zero_pressure(self, interpreter):
        """Zero pressure should be accepted."""
        query = "aluminum at 0 psi"
        result = interpreter.parse_query(query)
        assert result.pressure_psi_max == 0.0

    def test_decimal_pressure(self, interpreter):
        """Decimal pressure values should be parsed."""
        query = "steel at 14.7 psi"
        result = interpreter.parse_query(query)
        assert result.pressure_psi_max == pytest.approx(14.7, abs=0.01)

    def test_negative_temperature(self, interpreter):
        """Negative temperatures (cryogenic) should be parsed."""
        query = "aluminum at -320 F"
        result = interpreter.parse_query(query)
        # -320 F = -195.56 C (cryogenic)
        assert result.temp_c_max is not None
        assert result.temp_c_max < -100

    def test_very_long_query(self, interpreter):
        """Very long query should not crash."""
        long_query = "Can " + "aluminum 6061 " * 100 + "be used in oxygen at 200 psi"
        result = interpreter.parse_query(long_query)
        # Should extract something without crashing
        assert isinstance(result, MaterialConstraints)

    def test_special_sql_characters(self, interpreter):
        """Query with SQL-like characters should not cause issues."""
        query = "aluminum'; DROP TABLE materials;-- at 200 psi"
        result = interpreter.parse_query(query)
        # Should not crash, may or may not extract material
        assert isinstance(result, MaterialConstraints)

    def test_case_insensitivity(self, interpreter):
        """Parsing should be case-insensitive."""
        query1 = interpreter.parse_query("ALUMINUM 6061 at 200 PSI")
        query2 = interpreter.parse_query("aluminum 6061 at 200 psi")
        assert query1.pressure_psi_max == query2.pressure_psi_max


# ============================================================================
# TEST CLASS: Special Characters (3 tests)
# ============================================================================


class TestSpecialCharacters:
    """Test handling of unicode and special characters."""

    def test_unicode_degree_symbol(self, interpreter):
        """°F and °C degree symbols should work."""
        query = "aluminum at 200°F"
        result = interpreter.parse_query(query)
        # Should extract temperature with degree symbol
        assert result.temp_c_max is not None

    def test_unicode_subscript_o2(self, interpreter):
        """O₂ (unicode subscript 2) should detect oxygen."""
        query = "stainless steel in O₂ atmosphere"
        result = interpreter.parse_query(query)
        assert result.environment == "oxygen"

    @pytest.mark.xfail(reason="Em-dash handling may vary")
    def test_em_dash_in_range(self, interpreter):
        """Em-dash (—) in ranges should be handled like hyphen."""
        query = "pressure 100—500 psi"
        result = interpreter.parse_query(query)
        # Em-dash between numbers should be treated as range
        assert result.pressure_psi_max is not None


# ============================================================================
# TEST CLASS: Real World Queries (4 tests)
# ============================================================================


class TestRealWorldQueries:
    """Test realistic query patterns from actual usage."""

    def test_typical_material_query(self, interpreter):
        """Typical material compatibility question."""
        query = "Is stainless steel 316 compatible with gaseous oxygen at 3000 psi?"
        result = interpreter.parse_query(query)
        assert result.material is not None
        assert "316" in result.material
        assert result.environment == "oxygen"
        assert result.pressure_psi_max == pytest.approx(3000.0, abs=1.0)

    def test_aerospace_application_query(self, interpreter):
        """Aerospace-style application query."""
        query = "aluminum 6061-T6 for LOX tank at cryogenic temperatures"
        result = interpreter.parse_query(query)
        assert result.material is not None
        assert "6061" in result.material
        assert result.environment == "oxygen"

    def test_seal_material_query(self, interpreter):
        """Seal material compatibility query."""
        query = "viton o-rings in hydrogen service at 500 psi and 200 F"
        result = interpreter.parse_query(query)
        assert result.material is not None
        assert "viton" in result.material.lower()
        assert result.environment == "hydrogen"
        assert result.pressure_psi_max == pytest.approx(500.0, abs=1.0)
        assert result.temp_c_max is not None

    def test_comparison_of_alloys(self, interpreter):
        """Comparing multiple alloy options."""
        query = "best material between inconel 718 and hastelloy c276 for GOX"
        result = interpreter.parse_query(query)
        assert result.material is not None
        assert result.environment == "oxygen"


# ============================================================================
# SUMMARY: 55 tests total
# ============================================================================
# TestUnitConversion: 7 tests (1 xfail)
# TestRangeExpressions: 5 tests (all xfail)
# TestEnvironmentDetection: 12 tests (2 xfail)
# TestMaterialExtraction: 11 tests
# TestCompoundQueries: 3 tests (2 xfail)
# TestEdgeCasesAndBoundaries: 10 tests
# TestSpecialCharacters: 3 tests (1 xfail)
# TestRealWorldQueries: 4 tests
# ============================================================================
