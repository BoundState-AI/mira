#!/usr/bin/env python3
"""
Tests: Batch Mode Safety-Critical REFUSE Gate
Purpose: AC-R4 compliance -- 10/10 REFUSE tests for underspecified safety-critical queries.

Validates that safety-critical batch queries with missing required fields are
hard-refused, that general queries always proceed, and that safety context
detection works from fluid_medium, keywords, o2_pct, and temperature.

BoundState AI 2026
Compliance: SWE-013, SWE-033, NASA-STD-6016 S4.2.1, S5.1.4
Spec Reference: BS-MIRA-V4-BUILDSPEC-001-REV1, Section 4
"""

import sys
sys.path.insert(0, r"C:\BoundState")

import pytest

from mira_v4.batch_safety import BatchSafetyGate
from mira_v4.models import (
    BatchGateAction,
    EnvironmentSpec,
    ParsedQuery,
    SafetyContext,
)


# =============================================================================
# Shared Setup
# =============================================================================

gate = BatchSafetyGate()


def _make_query(
    raw_query: str = "test query",
    safety_context: SafetyContext = SafetyContext.GENERAL,
    temperature_c=None,
    pressure_kpa=None,
    o2_pct=None,
    fluid_medium=None,
    duration_hr=None,
    cycles=None,
    batch_mode: bool = True,
) -> ParsedQuery:
    """Helper to build a ParsedQuery with specified environment fields."""
    env = EnvironmentSpec(
        temperature_c=temperature_c,
        pressure_kpa=pressure_kpa,
        o2_pct=o2_pct,
        fluid_medium=fluid_medium,
        duration_hr=duration_hr,
        cycles=cycles,
    )
    return ParsedQuery(
        raw_query=raw_query,
        safety_context=safety_context,
        environment=env,
        batch_mode=batch_mode,
    )


# =============================================================================
# General Context: Always PROCEED
# =============================================================================


class TestGeneralContextProceeds:
    """General context queries always PROCEED regardless of missing fields."""

    def test_general_context_always_proceeds(self):
        """General query with all fields missing still gets PROCEED."""
        query = _make_query(
            raw_query="Find tensile strength data",
            safety_context=SafetyContext.GENERAL,
        )
        result = gate.check(query)
        assert result.action == BatchGateAction.PROCEED
        assert result.safety_context == SafetyContext.GENERAL
        assert result.penalty > 0.0  # General batch penalty applied


# =============================================================================
# Safety-Critical with All Fields: PROCEED
# =============================================================================


class TestSafetyCriticalAllFieldsProceeds:
    """Safety-critical queries with all required fields get PROCEED."""

    def test_oxygen_all_fields_present_proceeds(self):
        """O2 context with all 4 required fields -> PROCEED."""
        query = _make_query(
            raw_query="LOX compatibility",
            safety_context=SafetyContext.OXYGEN,
            temperature_c=-200.0,
            pressure_kpa=5000.0,
            o2_pct=99.5,
            fluid_medium="LOX",
        )
        result = gate.check(query)
        assert result.action == BatchGateAction.PROCEED
        assert result.missing_fields == []

    def test_hydrogen_all_fields_present_proceeds(self):
        """H2 context with all 3 required fields -> PROCEED."""
        query = _make_query(
            raw_query="LH2 material compatibility",
            safety_context=SafetyContext.HYDROGEN,
            temperature_c=-253.0,
            pressure_kpa=2000.0,
            fluid_medium="LH2",
        )
        result = gate.check(query)
        assert result.action == BatchGateAction.PROCEED
        assert result.missing_fields == []

    def test_cryogenic_all_fields_present_proceeds(self):
        """Cryogenic context with all 2 required fields -> PROCEED."""
        query = _make_query(
            raw_query="Cryogenic service material search",
            safety_context=SafetyContext.CRYOGENIC,
            temperature_c=-200.0,
            pressure_kpa=3000.0,
        )
        result = gate.check(query)
        assert result.action == BatchGateAction.PROCEED
        assert result.missing_fields == []

    def test_high_pressure_all_fields_present_proceeds(self):
        """High-pressure context with all 3 required fields -> PROCEED."""
        query = _make_query(
            raw_query="High-pressure service material",
            safety_context=SafetyContext.HIGH_PRESSURE,
            temperature_c=25.0,
            pressure_kpa=25000.0,
            fluid_medium="GN2",
        )
        result = gate.check(query)
        assert result.action == BatchGateAction.PROCEED
        assert result.missing_fields == []


# =============================================================================
# AC-R4: 10 REFUSE Test Cases (Parametrized)
# =============================================================================


class TestSafetyCriticalRefuse:
    """AC-R4: 10/10 REFUSE tests for underspecified safety-critical queries."""

    @pytest.mark.parametrize(
        "description, safety_context, temp, pressure, o2, fluid, expected_missing",
        [
            # 1. O2 query missing pressure
            (
                "O2 missing pressure_kpa",
                SafetyContext.OXYGEN,
                -200.0,     # temperature_c
                None,       # pressure_kpa MISSING
                99.5,       # o2_pct
                "LOX",      # fluid_medium
                ["pressure_kpa"],
            ),
            # 2. O2 query missing temperature
            (
                "O2 missing temperature_c",
                SafetyContext.OXYGEN,
                None,       # temperature_c MISSING
                5000.0,     # pressure_kpa
                99.5,       # o2_pct
                "LOX",      # fluid_medium
                ["temperature_c"],
            ),
            # 3. O2 query missing o2_pct
            (
                "O2 missing o2_pct",
                SafetyContext.OXYGEN,
                -200.0,     # temperature_c
                5000.0,     # pressure_kpa
                None,       # o2_pct MISSING
                "LOX",      # fluid_medium
                ["o2_pct"],
            ),
            # 4. O2 query missing fluid_medium
            (
                "O2 missing fluid_medium",
                SafetyContext.OXYGEN,
                -200.0,     # temperature_c
                5000.0,     # pressure_kpa
                99.5,       # o2_pct
                None,       # fluid_medium MISSING
                ["fluid_medium"],
            ),
            # 5. H2 query missing pressure
            (
                "H2 missing pressure_kpa",
                SafetyContext.HYDROGEN,
                -253.0,     # temperature_c
                None,       # pressure_kpa MISSING
                None,       # o2_pct (not required for H2)
                "LH2",      # fluid_medium
                ["pressure_kpa"],
            ),
            # 6. H2 query missing temperature
            (
                "H2 missing temperature_c",
                SafetyContext.HYDROGEN,
                None,       # temperature_c MISSING
                2000.0,     # pressure_kpa
                None,       # o2_pct
                "LH2",      # fluid_medium
                ["temperature_c"],
            ),
            # 7. H2 query missing fluid_medium
            (
                "H2 missing fluid_medium",
                SafetyContext.HYDROGEN,
                -253.0,     # temperature_c
                2000.0,     # pressure_kpa
                None,       # o2_pct
                None,       # fluid_medium MISSING
                ["fluid_medium"],
            ),
            # 8. Cryo query missing temperature
            (
                "Cryo missing temperature_c",
                SafetyContext.CRYOGENIC,
                None,       # temperature_c MISSING
                3000.0,     # pressure_kpa
                None,       # o2_pct
                None,       # fluid_medium
                ["temperature_c"],
            ),
            # 9. Cryo query missing pressure
            (
                "Cryo missing pressure_kpa",
                SafetyContext.CRYOGENIC,
                -200.0,     # temperature_c
                None,       # pressure_kpa MISSING
                None,       # o2_pct
                None,       # fluid_medium
                ["pressure_kpa"],
            ),
            # 10. High-P query missing pressure
            (
                "High-P missing pressure_kpa",
                SafetyContext.HIGH_PRESSURE,
                25.0,       # temperature_c
                None,       # pressure_kpa MISSING
                None,       # o2_pct
                "GN2",      # fluid_medium
                ["pressure_kpa"],
            ),
        ],
        ids=[
            "01_O2_missing_pressure",
            "02_O2_missing_temperature",
            "03_O2_missing_o2_pct",
            "04_O2_missing_fluid_medium",
            "05_H2_missing_pressure",
            "06_H2_missing_temperature",
            "07_H2_missing_fluid_medium",
            "08_Cryo_missing_temperature",
            "09_Cryo_missing_pressure",
            "10_HighP_missing_pressure",
        ],
    )
    def test_safety_critical_refuse(
        self,
        description,
        safety_context,
        temp,
        pressure,
        o2,
        fluid,
        expected_missing,
    ):
        """AC-R4: Safety-critical query with missing required field -> REFUSE."""
        query = _make_query(
            raw_query=f"Batch: {description}",
            safety_context=safety_context,
            temperature_c=temp,
            pressure_kpa=pressure,
            o2_pct=o2,
            fluid_medium=fluid,
        )
        result = gate.check(query)

        assert result.action == BatchGateAction.REFUSE, (
            f"Expected REFUSE for {description}, got {result.action.value}. "
            f"Missing: {result.missing_fields}"
        )
        for field in expected_missing:
            assert field in result.missing_fields, (
                f"Expected '{field}' in missing_fields for {description}, "
                f"got {result.missing_fields}"
            )


# =============================================================================
# Safety Context Detection Tests
# =============================================================================


class TestSafetyContextDetection:
    """Verify safety context detection from various query attributes."""

    def test_safety_context_detection_from_fluid_medium(self):
        """LOX fluid_medium -> OXYGEN context detected."""
        query = _make_query(
            raw_query="Find materials",
            safety_context=SafetyContext.GENERAL,  # Not pre-classified
            fluid_medium="LOX",
            temperature_c=-200.0,
            pressure_kpa=5000.0,
            o2_pct=99.5,
        )
        detected = gate.detect_safety_context(query)
        assert detected == SafetyContext.OXYGEN

    def test_safety_context_detection_from_fluid_medium_hydrogen(self):
        """LH2 fluid_medium -> HYDROGEN context detected."""
        query = _make_query(
            raw_query="Find materials",
            safety_context=SafetyContext.GENERAL,
            fluid_medium="LH2",
        )
        detected = gate.detect_safety_context(query)
        assert detected == SafetyContext.HYDROGEN

    def test_safety_context_detection_from_keywords(self):
        """'LOX compatible' in raw_query -> OXYGEN context detected."""
        query = _make_query(
            raw_query="Find LOX compatible materials for valve seats",
            safety_context=SafetyContext.GENERAL,
        )
        detected = gate.detect_safety_context(query)
        assert detected == SafetyContext.OXYGEN

    def test_safety_context_detection_from_keywords_hydrogen(self):
        """'hydrogen service' in raw_query -> HYDROGEN context detected."""
        query = _make_query(
            raw_query="Materials for hydrogen service at high pressure",
            safety_context=SafetyContext.GENERAL,
        )
        detected = gate.detect_safety_context(query)
        assert detected == SafetyContext.HYDROGEN

    def test_safety_context_detection_from_keywords_cryogenic(self):
        """'cryogenic' in raw_query -> CRYOGENIC context detected."""
        query = _make_query(
            raw_query="Cryogenic temperature seal materials",
            safety_context=SafetyContext.GENERAL,
        )
        detected = gate.detect_safety_context(query)
        assert detected == SafetyContext.CRYOGENIC

    def test_safety_context_detection_from_o2_pct(self):
        """o2_pct >= 23.5 -> OXYGEN context detected."""
        query = _make_query(
            raw_query="Material search",
            safety_context=SafetyContext.GENERAL,
            o2_pct=30.0,
        )
        detected = gate.detect_safety_context(query)
        assert detected == SafetyContext.OXYGEN

    def test_safety_context_detection_from_o2_pct_boundary(self):
        """o2_pct = 23.5 exactly -> OXYGEN context detected."""
        query = _make_query(
            raw_query="Material search",
            safety_context=SafetyContext.GENERAL,
            o2_pct=23.5,
        )
        detected = gate.detect_safety_context(query)
        assert detected == SafetyContext.OXYGEN

    def test_safety_context_detection_from_o2_pct_below_threshold(self):
        """o2_pct = 20.0 (< 23.5) -> GENERAL context (not oxygen)."""
        query = _make_query(
            raw_query="Material search",
            safety_context=SafetyContext.GENERAL,
            o2_pct=20.0,
        )
        detected = gate.detect_safety_context(query)
        assert detected == SafetyContext.GENERAL

    def test_safety_context_detection_from_temperature(self):
        """temperature_c < -73.3 -> CRYOGENIC context detected."""
        query = _make_query(
            raw_query="Material search at low temp",
            safety_context=SafetyContext.GENERAL,
            temperature_c=-100.0,
        )
        detected = gate.detect_safety_context(query)
        assert detected == SafetyContext.CRYOGENIC

    def test_safety_context_detection_from_temperature_boundary(self):
        """temperature_c = -73.3 exactly -> NOT cryogenic (threshold is <)."""
        query = _make_query(
            raw_query="Material search",
            safety_context=SafetyContext.GENERAL,
            temperature_c=-73.3,
        )
        detected = gate.detect_safety_context(query)
        # -73.3 is NOT < -73.3, so it should NOT be cryogenic
        assert detected != SafetyContext.CRYOGENIC

    def test_safety_context_detection_from_pressure(self):
        """pressure_kpa > 20684 -> HIGH_PRESSURE context detected."""
        query = _make_query(
            raw_query="Material search at high pressure",
            safety_context=SafetyContext.GENERAL,
            pressure_kpa=25000.0,
        )
        detected = gate.detect_safety_context(query)
        assert detected == SafetyContext.HIGH_PRESSURE

    def test_safety_context_general_when_no_signals(self):
        """No safety signals -> GENERAL context."""
        query = _make_query(
            raw_query="Find tensile strength data for aluminum",
            safety_context=SafetyContext.GENERAL,
            temperature_c=25.0,
            pressure_kpa=101.325,
        )
        detected = gate.detect_safety_context(query)
        assert detected == SafetyContext.GENERAL

    def test_safety_context_explicit_overrides_detection(self):
        """Pre-classified safety_context != GENERAL is used directly."""
        query = _make_query(
            raw_query="Just a query",
            safety_context=SafetyContext.OXYGEN,
        )
        detected = gate.detect_safety_context(query)
        assert detected == SafetyContext.OXYGEN
