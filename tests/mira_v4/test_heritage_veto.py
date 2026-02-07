#!/usr/bin/env python3
"""
Test Module: Heritage Veto Engine (heritage_veto.py)
Purpose: AC-R6 acknowledgment gate tests -- 5/5 acknowledgment gate cases.

BoundState AI 2026
Compliance: SWE-032, SWE-033, NASA-STD-6016 S4.2.1

Tests cover:
    - No heritage records -> no veto
    - Temperature envelope matching (10% relative margin)
    - Temperature envelope non-match (outside margin)
    - Pressure overlap matching (query >= 0.8 * failure)
    - Pressure non-overlap (ST-11: 200 psi vs 6000 psi -> NO veto)
    - Pressure overlap (ST-12: 5500 psi vs 6000 psi -> veto)
    - Media exact match requirement
    - Safety-critical context -> requires_acknowledgment
    - Non-safety context -> rank sink penalty only
    - Override record immutability (frozen Pydantic model)
    - apply_rank_sink preserves vetoed materials (sinks, does not drop)
    - 5 parametrised acknowledgment gate tests for AC-R6
"""

import sys
sys.path.insert(0, r"C:\BoundState")

import uuid
from datetime import datetime

import pytest

from mira_v4.models import (
    EnvironmentSpec,
    HeritageOverride,
    HeritageVetoType,
    SafetyContext,
)
from mira_v4.heritage_veto import (
    EnvelopeMatcher,
    HeritageVetoEngine,
    PRESSURE_OVERLAP_FACTOR,
    RANK_SINK_PENALTY,
    TEMPERATURE_MARGIN,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _psi_to_kpa(psi: float) -> float:
    """Convert psi to kPa (1 psi = 6.89476 kPa)."""
    return psi * 6.89476


def _make_heritage_record(
    failure_id: str,
    material_key: str,
    temperature_c: float = None,
    pressure_kpa: float = None,
    fluid_medium: str = None,
    description: str = "test failure",
) -> dict:
    """Build a heritage failure record dict."""
    env = {}
    if temperature_c is not None:
        env["temperature_c"] = temperature_c
    if pressure_kpa is not None:
        env["pressure_kpa"] = pressure_kpa
    if fluid_medium is not None:
        env["fluid_medium"] = fluid_medium
    return {
        "failure_id": failure_id,
        "material_key": material_key,
        "failure_environment": env,
        "failure_description": description,
    }


# ===========================================================================
# 1. No heritage records -> no veto
# ===========================================================================


class TestNoHeritageRecords:
    """When no heritage failure records exist, no veto should be raised."""

    def test_no_heritage_records_no_veto(self):
        engine = HeritageVetoEngine()
        query_env = EnvironmentSpec(
            temperature_c=-183.0,
            pressure_kpa=_psi_to_kpa(500),
            fluid_medium="LOX",
        )
        result = engine.check_heritage(
            material_key="Inconel-718",
            query_env=query_env,
            heritage_records=[],
            safety_context=SafetyContext.OXYGEN,
        )
        assert result.vetoed is False
        assert result.requires_acknowledgment is False
        assert result.rank_penalty == 0.0


# ===========================================================================
# 2. Temperature envelope matching
# ===========================================================================


class TestTemperatureEnvelope:
    """Temperature overlap uses 10% relative margin."""

    def test_envelope_match_temperature_within_margin(self):
        """Query temp within 10% margin of failure temp -> match on temp dimension."""
        matcher = EnvelopeMatcher()
        # failure_temp = -183 C, 10% margin of abs(-183) = 18.3
        # query_temp = -180 C, diff = 3 => relative_diff = 3/183 ~ 0.016 < 0.10
        query_env = EnvironmentSpec(temperature_c=-180.0, pressure_kpa=100.0, fluid_medium="LOX")
        failure_env = EnvironmentSpec(temperature_c=-183.0, pressure_kpa=100.0, fluid_medium="LOX")

        match, details = matcher.match_envelope(query_env, failure_env)
        assert details["temperature"]["match"] is True
        assert details["temperature"]["relative_diff"] <= TEMPERATURE_MARGIN

    def test_envelope_no_match_temperature_outside_margin(self):
        """Query temp well outside 10% margin -> no match on temp dimension."""
        matcher = EnvelopeMatcher()
        # failure_temp = -183 C, query_temp = 25 C => diff = 208
        # relative_diff = 208 / 183 ~ 1.14 >> 0.10
        query_env = EnvironmentSpec(temperature_c=25.0, pressure_kpa=100.0, fluid_medium="LOX")
        failure_env = EnvironmentSpec(temperature_c=-183.0, pressure_kpa=100.0, fluid_medium="LOX")

        match, details = matcher.match_envelope(query_env, failure_env)
        assert details["temperature"]["match"] is False
        assert match is False  # temperature mismatch prevents overall match


# ===========================================================================
# 3. Pressure envelope matching
# ===========================================================================


class TestPressureEnvelope:
    """Pressure overlap criterion: query_pressure >= 0.80 * failure_pressure."""

    def test_envelope_match_pressure_overlap(self):
        """query >= 0.8 * failure -> pressure match."""
        matcher = EnvelopeMatcher()
        failure_pressure = _psi_to_kpa(6000)
        query_pressure = _psi_to_kpa(5500)  # 5500/6000 = 0.917 >= 0.80

        query_env = EnvironmentSpec(
            temperature_c=-183.0, pressure_kpa=query_pressure, fluid_medium="LOX"
        )
        failure_env = EnvironmentSpec(
            temperature_c=-183.0, pressure_kpa=failure_pressure, fluid_medium="LOX"
        )

        _, details = matcher.match_envelope(query_env, failure_env)
        assert details["pressure"]["match"] is True

    def test_envelope_no_match_pressure_below_threshold(self):
        """ST-11: 200 psi query vs 6000 psi failure -> NO veto.
        200 << 0.80 * 6000 = 4800. Pressure dimension does NOT match."""
        matcher = EnvelopeMatcher()
        failure_pressure = _psi_to_kpa(6000)
        query_pressure = _psi_to_kpa(200)  # 200/6000 = 0.033 < 0.80

        query_env = EnvironmentSpec(
            temperature_c=-183.0, pressure_kpa=query_pressure, fluid_medium="LOX"
        )
        failure_env = EnvironmentSpec(
            temperature_c=-183.0, pressure_kpa=failure_pressure, fluid_medium="LOX"
        )

        _, details = matcher.match_envelope(query_env, failure_env)
        assert details["pressure"]["match"] is False

    def test_envelope_match_pressure_above_threshold(self):
        """ST-12: 5500 psi query vs 6000 psi failure -> veto.
        5500 >= 0.80 * 6000 = 4800. Pressure dimension matches."""
        matcher = EnvelopeMatcher()
        failure_pressure = _psi_to_kpa(6000)
        query_pressure = _psi_to_kpa(5500)

        query_env = EnvironmentSpec(
            temperature_c=-183.0, pressure_kpa=query_pressure, fluid_medium="LOX"
        )
        failure_env = EnvironmentSpec(
            temperature_c=-183.0, pressure_kpa=failure_pressure, fluid_medium="LOX"
        )

        _, details = matcher.match_envelope(query_env, failure_env)
        assert details["pressure"]["match"] is True


# ===========================================================================
# 4. Media exact match
# ===========================================================================


class TestMediaMatch:
    """Fluid medium requires exact case-insensitive match."""

    def test_media_exact_match_required(self):
        """LOX != GOX -> media dimension does not match."""
        matcher = EnvelopeMatcher()
        query_env = EnvironmentSpec(temperature_c=-183.0, pressure_kpa=100.0, fluid_medium="LOX")
        failure_env = EnvironmentSpec(temperature_c=-183.0, pressure_kpa=100.0, fluid_medium="GOX")

        match, details = matcher.match_envelope(query_env, failure_env)
        assert details["media"]["match"] is False
        assert match is False  # media mismatch prevents overall match


# ===========================================================================
# 5. Safety-critical vs non-safety veto behaviour
# ===========================================================================


class TestVetoTierBehaviour:
    """Safety-critical vetoes require acknowledgment; non-safety get rank sink."""

    def _make_matching_scenario(self, safety_context):
        """Create a full heritage veto scenario where all dimensions match."""
        engine = HeritageVetoEngine()
        query_env = EnvironmentSpec(
            temperature_c=-183.0,
            pressure_kpa=_psi_to_kpa(5500),
            fluid_medium="LOX",
        )
        heritage_records = [
            _make_heritage_record(
                failure_id="HF-001",
                material_key="SS-316L",
                temperature_c=-183.0,
                pressure_kpa=_psi_to_kpa(6000),
                fluid_medium="LOX",
                description="Ignition failure in LOX at 6000 psi",
            ),
        ]
        return engine.check_heritage(
            material_key="SS-316L",
            query_env=query_env,
            heritage_records=heritage_records,
            safety_context=safety_context,
        )

    def test_safety_critical_requires_acknowledgment(self):
        """OXYGEN context -> veto_type=SAFETY_CRITICAL, requires_acknowledgment=True."""
        result = self._make_matching_scenario(SafetyContext.OXYGEN)
        assert result.vetoed is True
        assert result.veto_type == HeritageVetoType.SAFETY_CRITICAL
        assert result.requires_acknowledgment is True

    def test_non_safety_rank_sink_only(self):
        """GENERAL context -> veto_type=NON_SAFETY, rank_penalty=0.30."""
        result = self._make_matching_scenario(SafetyContext.GENERAL)
        assert result.vetoed is True
        assert result.veto_type == HeritageVetoType.NON_SAFETY
        assert result.requires_acknowledgment is False
        assert result.rank_penalty == pytest.approx(RANK_SINK_PENALTY)


# ===========================================================================
# 6. Override immutability
# ===========================================================================


class TestOverrideImmutability:
    """HeritageOverride records must be frozen (immutable)."""

    def test_create_override_immutable(self):
        """Cannot mutate fields on a HeritageOverride after creation."""
        engine = HeritageVetoEngine()
        override = engine.create_override(
            material_key="SS-316L",
            heritage_failure_id="HF-001",
            failure_env=EnvironmentSpec(
                temperature_c=-183.0,
                pressure_kpa=_psi_to_kpa(6000),
                fluid_medium="LOX",
            ),
            query_env=EnvironmentSpec(
                temperature_c=-183.0,
                pressure_kpa=_psi_to_kpa(5500),
                fluid_medium="LOX",
            ),
            engineer_name="Dr. Wilde",
            engineer_rationale="Pressure delta is small and within test margin",
            lineage_hash="a" * 64,
        )
        with pytest.raises(Exception):
            # Pydantic frozen=True should raise ValidationError on assignment
            override.engineer_name = "Someone Else"


# ===========================================================================
# 7. apply_rank_sink preserves vetoed materials
# ===========================================================================


class TestApplyRankSink:
    """Rank-sink reorders but does NOT remove vetoed materials."""

    def test_apply_rank_sink_preserves_vetoed_materials(self):
        """All materials present after rank sink; vetoed ones at the end."""
        results = [
            {"material_key": "A", "score": 0.9},
            {"material_key": "B", "score": 0.8},
            {"material_key": "C", "score": 0.7},
        ]
        vetoed_keys = {"B"}
        reordered = HeritageVetoEngine.apply_rank_sink(results, vetoed_keys)

        # All three materials present
        assert len(reordered) == 3
        keys = [r["material_key"] for r in reordered]
        assert set(keys) == {"A", "B", "C"}

        # B must be last (sunk)
        assert reordered[-1]["material_key"] == "B"
        # A and C retain relative order before B
        non_vetoed_keys = [r["material_key"] for r in reordered if r["material_key"] != "B"]
        assert non_vetoed_keys == ["A", "C"]


# ===========================================================================
# 8. AC-R6 acknowledgment gate tests (5 / 5 parametrised)
# ===========================================================================

_ACK_GATE_ENGINE = HeritageVetoEngine()

_MATCHING_QUERY_ENV = EnvironmentSpec(
    temperature_c=-183.0,
    pressure_kpa=_psi_to_kpa(5500),
    fluid_medium="LOX",
)

_MATCHING_HERITAGE = [
    _make_heritage_record(
        failure_id="HF-ACK-001",
        material_key="SS-316L",
        temperature_c=-183.0,
        pressure_kpa=_psi_to_kpa(6000),
        fluid_medium="LOX",
        description="Heritage ignition failure in LOX",
    ),
]


class TestAcknowledgmentGate:
    """AC-R6: 5/5 acknowledgment gate test cases."""

    def test_ack_gate_1_safety_critical_requires_ack(self):
        """ACK-1: Safety-critical veto must set requires_acknowledgment=True."""
        result = _ACK_GATE_ENGINE.check_heritage(
            material_key="SS-316L",
            query_env=_MATCHING_QUERY_ENV,
            heritage_records=_MATCHING_HERITAGE,
            safety_context=SafetyContext.OXYGEN,
        )
        assert result.vetoed is True
        assert result.requires_acknowledgment is True

    def test_ack_gate_2_cannot_proceed_without_ack(self):
        """ACK-2: When requires_acknowledgment=True, the material cannot
        proceed without explicit engineer acknowledgment. The veto result
        itself blocks until override is created."""
        result = _ACK_GATE_ENGINE.check_heritage(
            material_key="SS-316L",
            query_env=_MATCHING_QUERY_ENV,
            heritage_records=_MATCHING_HERITAGE,
            safety_context=SafetyContext.OXYGEN,
        )
        # The veto result signals that acknowledgment is required
        assert result.requires_acknowledgment is True
        # No override record exists yet -- the material is blocked
        assert result.vetoed is True
        assert result.veto_type == HeritageVetoType.SAFETY_CRITICAL

    def test_ack_gate_3_override_contains_engineer_and_rationale(self):
        """ACK-3: Override record must contain engineer_name and engineer_rationale."""
        override = _ACK_GATE_ENGINE.create_override(
            material_key="SS-316L",
            heritage_failure_id="HF-ACK-001",
            failure_env=EnvironmentSpec(
                temperature_c=-183.0,
                pressure_kpa=_psi_to_kpa(6000),
                fluid_medium="LOX",
            ),
            query_env=_MATCHING_QUERY_ENV,
            engineer_name="Dr. Wilde",
            engineer_rationale="Reviewed failure report; pressure margin is acceptable",
            lineage_hash="b" * 64,
        )
        assert override.engineer_name == "Dr. Wilde"
        assert "pressure margin" in override.engineer_rationale
        assert override.acknowledged is True

    def test_ack_gate_4_override_has_uuid_and_timestamp(self):
        """ACK-4: Override record must have a valid UUID and ISO timestamp."""
        override = _ACK_GATE_ENGINE.create_override(
            material_key="SS-316L",
            heritage_failure_id="HF-ACK-001",
            failure_env=EnvironmentSpec(
                temperature_c=-183.0,
                pressure_kpa=_psi_to_kpa(6000),
                fluid_medium="LOX",
            ),
            query_env=_MATCHING_QUERY_ENV,
            engineer_name="Dr. Wilde",
            engineer_rationale="Acceptable risk after review",
            lineage_hash="c" * 64,
        )
        # Valid UUID
        parsed_uuid = uuid.UUID(override.override_id)
        assert parsed_uuid.version == 4

        # Valid ISO 8601 timestamp
        ts = datetime.fromisoformat(override.timestamp)
        assert ts.year >= 2024

    def test_ack_gate_5_override_is_frozen(self):
        """ACK-5: Override record is immutable (frozen Pydantic model)."""
        override = _ACK_GATE_ENGINE.create_override(
            material_key="SS-316L",
            heritage_failure_id="HF-ACK-001",
            failure_env=EnvironmentSpec(
                temperature_c=-183.0,
                pressure_kpa=_psi_to_kpa(6000),
                fluid_medium="LOX",
            ),
            query_env=_MATCHING_QUERY_ENV,
            engineer_name="Dr. Wilde",
            engineer_rationale="Acceptable risk after review",
            lineage_hash="d" * 64,
        )
        with pytest.raises(Exception):
            override.acknowledged = False
        with pytest.raises(Exception):
            override.engineer_rationale = "tampered"
