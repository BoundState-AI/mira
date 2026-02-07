#!/usr/bin/env python3
"""
Tests: MIRA v4 Shared Models
Purpose: Validate enums, model defaults, validation rules, and immutability.

BoundState AI 2026
Compliance: NASA-STD-8739.8B, SWE-013, SWE-032, SWE-033
Spec Reference: BS-MIRA-V4-BUILDSPEC-001-REV1
"""

import sys
sys.path.insert(0, r"C:\BoundState")

import pytest
from pydantic import ValidationError

from mira_v4.models import (
    BatchGateAction,
    ConfidenceResult,
    DecisionLineage,
    DirtyDataTier,
    EnvironmentSpec,
    EvidenceRow,
    GateAction,
    HeritageOverride,
    ParsedQuery,
    SafetyContext,
    SchemaChange,
    SchemaChangeType,
)


# =============================================================================
# Enum Value Tests
# =============================================================================


class TestSafetyContextEnum:
    """Verify SafetyContext enum members match BuildSpec Table 6."""

    def test_safety_context_enum_values(self):
        assert SafetyContext.OXYGEN.value == "oxygen"
        assert SafetyContext.HYDROGEN.value == "hydrogen"
        assert SafetyContext.CRYOGENIC.value == "cryogenic"
        assert SafetyContext.HIGH_PRESSURE.value == "high_pressure"
        assert SafetyContext.GENERAL.value == "general"
        # Exactly 5 members
        assert len(SafetyContext) == 5


class TestDirtyDataTierEnum:
    """Verify DirtyDataTier enum members match BuildSpec Section 3.2."""

    def test_dirty_data_tier_enum_values(self):
        assert DirtyDataTier.CLEAN.value == "clean"
        assert DirtyDataTier.DEGRADED.value == "degraded"
        assert DirtyDataTier.REFUSE.value == "refuse"
        assert len(DirtyDataTier) == 3


class TestGateActionEnum:
    """Verify GateAction enum members match BuildSpec Section 2.5."""

    def test_gate_action_enum_values(self):
        assert GateAction.PASS.value == "PASS"
        assert GateAction.CLARIFY.value == "CLARIFY"
        assert GateAction.REFUSE.value == "REFUSE"
        assert len(GateAction) == 3


# =============================================================================
# EnvironmentSpec Tests
# =============================================================================


class TestEnvironmentSpec:
    """Validate EnvironmentSpec field counting and normalization."""

    def test_environment_spec_count_missing_fields_all_none(self):
        """All fields None -> 6 missing."""
        env = EnvironmentSpec()
        assert env.count_missing_fields() == 6

    def test_environment_spec_count_missing_fields_all_filled(self):
        """All fields filled -> 0 missing."""
        env = EnvironmentSpec(
            temperature_c=-200.0,
            pressure_kpa=5000.0,
            o2_pct=99.5,
            fluid_medium="LOX",
            duration_hr=1.0,
            cycles=10,
        )
        assert env.count_missing_fields() == 0

    def test_environment_spec_count_missing_fields_partial(self):
        """2 fields filled -> 4 missing."""
        env = EnvironmentSpec(temperature_c=-200.0, fluid_medium="LOX")
        assert env.count_missing_fields() == 4

    def test_environment_spec_fluid_normalization_lowercase(self):
        """Lowercase fluid_medium -> uppercase."""
        env = EnvironmentSpec(fluid_medium="lox")
        assert env.fluid_medium == "LOX"

    def test_environment_spec_fluid_normalization_mixed_case(self):
        """Mixed case fluid_medium -> uppercase."""
        env = EnvironmentSpec(fluid_medium="Gaseous Oxygen")
        assert env.fluid_medium == "GASEOUS OXYGEN"

    def test_environment_spec_fluid_normalization_whitespace(self):
        """Whitespace-padded fluid_medium -> stripped and uppercased."""
        env = EnvironmentSpec(fluid_medium="  gox  ")
        assert env.fluid_medium == "GOX"

    def test_environment_spec_fluid_normalization_none(self):
        """None fluid_medium stays None."""
        env = EnvironmentSpec(fluid_medium=None)
        assert env.fluid_medium is None

    def test_environment_spec_get_missing_field_names(self):
        """get_missing_field_names returns correct field names."""
        env = EnvironmentSpec(temperature_c=-200.0, pressure_kpa=5000.0)
        missing = env.get_missing_field_names()
        assert "o2_pct" in missing
        assert "fluid_medium" in missing
        assert "duration_hr" in missing
        assert "cycles" in missing
        assert "temperature_c" not in missing
        assert "pressure_kpa" not in missing
        assert len(missing) == 4


# =============================================================================
# ParsedQuery Tests
# =============================================================================


class TestParsedQuery:
    """Validate ParsedQuery default values."""

    def test_parsed_query_defaults(self):
        """Verify default values for optional/defaulted fields."""
        query = ParsedQuery(raw_query="test query")
        assert query.intent == "general_search"
        assert query.safety_context == SafetyContext.GENERAL
        assert query.environment.count_missing_fields() == 6
        assert query.material_key is None
        assert query.filters == {}
        assert query.sonnet_intent is None
        assert query.heuristic_intent is None
        assert query.batch_mode is False

    def test_parsed_query_requires_raw_query(self):
        """raw_query is required and must be non-empty."""
        with pytest.raises(ValidationError):
            ParsedQuery(raw_query="")


# =============================================================================
# EvidenceRow Tests
# =============================================================================


class TestEvidenceRow:
    """Validate EvidenceRow default values."""

    def test_evidence_row_defaults(self):
        """Verify default values for optional/defaulted fields."""
        row = EvidenceRow(record_id="REC-0001")
        assert row.source == "UNKNOWN"
        assert row.data_class == "derived"
        assert row.dirty_flag is False
        assert row.dirty_fields == []
        assert row.raw_values == {}
        assert row.test_year is None

    def test_evidence_row_requires_record_id(self):
        """record_id is required and must be non-empty."""
        with pytest.raises(ValidationError):
            EvidenceRow(record_id="")

    def test_evidence_row_test_year_bounds(self):
        """test_year must be between 1900 and 2100."""
        # Valid boundaries
        row_low = EvidenceRow(record_id="R1", test_year=1900)
        assert row_low.test_year == 1900

        row_high = EvidenceRow(record_id="R2", test_year=2100)
        assert row_high.test_year == 2100

        # Out of bounds
        with pytest.raises(ValidationError):
            EvidenceRow(record_id="R3", test_year=1899)

        with pytest.raises(ValidationError):
            EvidenceRow(record_id="R4", test_year=2101)


# =============================================================================
# ConfidenceResult Tests
# =============================================================================


class TestConfidenceResult:
    """Validate ConfidenceResult score bounds."""

    def test_confidence_result_validation_score_bounds(self):
        """Score must be between 0.0 and 1.0 inclusive."""
        # Valid at boundaries
        result_zero = ConfidenceResult(
            score=0.0,
            penalties={"unknown_env": 1.0},
            gate_action=GateAction.REFUSE,
            safety_critical=False,
            explanation="Score 0.0",
        )
        assert result_zero.score == 0.0

        result_one = ConfidenceResult(
            score=1.0,
            penalties={},
            gate_action=GateAction.PASS,
            safety_critical=False,
            explanation="Score 1.0",
        )
        assert result_one.score == 1.0

    def test_confidence_result_validation_score_too_high(self):
        """Score > 1.0 should raise ValidationError."""
        with pytest.raises(ValidationError):
            ConfidenceResult(
                score=1.01,
                penalties={},
                gate_action=GateAction.PASS,
                safety_critical=False,
                explanation="Too high",
            )

    def test_confidence_result_validation_score_negative(self):
        """Negative score should raise ValidationError."""
        with pytest.raises(ValidationError):
            ConfidenceResult(
                score=-0.01,
                penalties={},
                gate_action=GateAction.REFUSE,
                safety_critical=False,
                explanation="Negative",
            )


# =============================================================================
# Immutability Tests (Frozen Models)
# =============================================================================


class TestHeritageOverrideImmutable:
    """Verify HeritageOverride is frozen (immutable after creation)."""

    def test_heritage_override_immutable(self):
        """Attempting to modify a frozen HeritageOverride should raise."""
        override = HeritageOverride(
            material_key="PTFE",
            heritage_failure_id="HF-001",
            failure_environment=EnvironmentSpec(temperature_c=-200.0),
            query_environment=EnvironmentSpec(temperature_c=-180.0),
            engineer_name="Dr. Wilde",
            engineer_rationale="Failure not applicable to this use case",
        )
        with pytest.raises(ValidationError):
            override.material_key = "INCONEL-718"

    def test_heritage_override_fields_populated(self):
        """Override auto-generates override_id and timestamp."""
        override = HeritageOverride(
            material_key="PTFE",
            heritage_failure_id="HF-001",
            failure_environment=EnvironmentSpec(),
            query_environment=EnvironmentSpec(),
            engineer_name="Test Engineer",
            engineer_rationale="Test rationale",
        )
        assert override.override_id is not None
        assert len(override.override_id) > 0
        assert override.timestamp is not None
        assert override.acknowledged is True


class TestDecisionLineageImmutable:
    """Verify DecisionLineage is frozen (immutable after creation)."""

    def test_decision_lineage_immutable(self):
        """Attempting to modify a frozen DecisionLineage should raise."""
        lineage = DecisionLineage(
            query_hash="a" * 64,
            snapshot_hash="b" * 64,
            parsed_query=ParsedQuery(raw_query="test"),
            confidence=ConfidenceResult(
                score=0.85,
                penalties={},
                gate_action=GateAction.PASS,
                safety_critical=False,
                explanation="Test",
            ),
            schema_version="1.0.0",
        )
        with pytest.raises(ValidationError):
            lineage.query_hash = "c" * 64


# =============================================================================
# SchemaChange Tests
# =============================================================================


class TestSchemaChangeSeverityValidation:
    """Verify SchemaChange.severity is restricted to FAIL or WARN."""

    def test_schema_change_severity_validation_fail(self):
        """FAIL is a valid severity."""
        change = SchemaChange(
            field_name="tensile_strength",
            change_type=SchemaChangeType.REMOVED_FIELD,
            severity="FAIL",
        )
        assert change.severity == "FAIL"

    def test_schema_change_severity_validation_warn(self):
        """WARN is a valid severity."""
        change = SchemaChange(
            field_name="new_field",
            change_type=SchemaChangeType.NEW_FIELD,
            severity="WARN",
        )
        assert change.severity == "WARN"

    def test_schema_change_severity_validation_invalid(self):
        """Invalid severity raises ValidationError."""
        with pytest.raises(ValidationError):
            SchemaChange(
                field_name="test_field",
                change_type=SchemaChangeType.NEW_FIELD,
                severity="ERROR",
            )

    def test_schema_change_severity_validation_lowercase(self):
        """Lowercase severity is rejected (must be exact FAIL or WARN)."""
        with pytest.raises(ValidationError):
            SchemaChange(
                field_name="test_field",
                change_type=SchemaChangeType.NEW_FIELD,
                severity="fail",
            )
