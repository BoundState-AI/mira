#!/usr/bin/env python3
"""
Module: Test Knowledge Twins
Purpose: Tests for H2/O2 Knowledge Twins compatibility assessment.

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

from __future__ import annotations

import math
from typing import Dict, Optional

import pytest

from mira.knowledge_twins import (
    # Models
    GasType,
    CompatibilityClass,
    Phase,
    DataClass,
    PropertyKey,
    MaterialFamilyKey,
    PropertyEvidence,
    EnvelopeEvidence,
    EnvironmentEnvelope,
    CompatibilityRecord,
    CompatibilityAssessment,
    # BOK Loaders
    clean_str,
    clean_float,
    canonical_maptis_material_key,
    FluidInfo,
    make_fluids_resolver_from_map,
    map_flammability_row_to_record,
    map_crack_growth_row_to_record,
    map_fluid_compatibility_row_to_record,
    maptis_rows_to_twin_records,
    # Envelope Overlap
    DEFAULT_ENVELOPE_CONFIG,
    calculate_range_overlap,
    calculate_envelope_overlap,
    # Scoring Profiles
    H2_SCORING_PROFILE,
    O2_SCORING_PROFILE,
    get_scoring_profile,
    get_hard_reject_ratings,
    get_family_bonus,
    normalize_flammability_rating,
    # Verdict Engine
    VerdictEngine,
    compute_verdict,
    check_hard_rejects,
    # Index Builder
    create_embedding_text,
    normalize_embedding,
)


# ---------------------------------------------------------------------------
# Test: Normalization Helpers
# ---------------------------------------------------------------------------


class TestNormalizationHelpers:
    """Tests for clean_str and clean_float normalization."""

    def test_clean_str_whitespace(self):
        """Rating "C " -> parsed as "C" """
        assert clean_str("C ") == "C"
        assert clean_str(" A") == "A"
        assert clean_str("  B  ") == "B"

    def test_clean_str_none(self):
        """None -> empty string"""
        assert clean_str(None) == ""

    def test_clean_float_whitespace(self):
        """Pressure " 10.2000" -> float 10.2"""
        assert clean_float(" 10.2000") == 10.2
        assert clean_float("  500  ") == 500.0

    def test_clean_float_null_string(self):
        """NULL string -> None"""
        assert clean_float("NULL") is None
        assert clean_float("null") is None

    def test_clean_float_empty(self):
        """Empty string -> None"""
        assert clean_float("") is None
        assert clean_float("   ") is None

    def test_clean_float_none(self):
        """None -> None"""
        assert clean_float(None) is None


# ---------------------------------------------------------------------------
# Test: Material Key Canonicalization
# ---------------------------------------------------------------------------


class TestMaterialKeyCanonicalization:
    """Tests for canonical_maptis_material_key."""

    def test_integer_key(self):
        """Integer material_key -> MAPTIS:{int}"""
        assert canonical_maptis_material_key(66228) == "MAPTIS:66228"

    def test_string_integer(self):
        """String integer -> MAPTIS:{int}"""
        assert canonical_maptis_material_key("66228") == "MAPTIS:66228"

    def test_float_string(self):
        """Float string -> MAPTIS:{int}"""
        assert canonical_maptis_material_key("66228.0") == "MAPTIS:66228"

    def test_null_key(self):
        """NULL -> MAPTIS:UNKNOWN"""
        assert canonical_maptis_material_key(None) == "MAPTIS:UNKNOWN"
        assert canonical_maptis_material_key("NULL") == "MAPTIS:UNKNOWN"


# ---------------------------------------------------------------------------
# Test: Flammability Row Mapping
# ---------------------------------------------------------------------------


class TestFlammabilityRowMapping:
    """Tests for map_flammability_row_to_record."""

    def test_flammability_whitespace_rating(self):
        """Rating "C " -> parsed as "C" """
        row = {
            "material_key": 66228,
            "designation": "Test Material",
            "material_type_key": 235,
            "test_type": "flammability",
            "payload": {
                "flam_rating": "C ",  # Trailing whitespace
                "flam_pressure": 10.2,
                "flam_moc_o2_pct": 30.0,
            },
        }

        record = map_flammability_row_to_record(row)

        # Verify rating was cleaned
        rating_prop = record.get_property(PropertyKey.FLAMMABILITY_RATING)
        assert rating_prop is not None
        assert rating_prop.value_text == "C"

    def test_flammability_whitespace_pressure(self):
        """Pressure " 10.2000" -> float 10.2"""
        row = {
            "material_key": 66228,
            "designation": "Test Material",
            "material_type_key": 235,
            "test_type": "flammability",
            "payload": {
                "flam_rating": "B",
                "flam_pressure": " 10.2000",  # Leading whitespace
                "flam_moc_o2_pct": 30.0,
            },
        }

        record = map_flammability_row_to_record(row)

        # Verify pressure was cleaned
        pressure_prop = record.get_property(PropertyKey.TEST_PRESSURE_PSIA)
        assert pressure_prop is not None
        assert pressure_prop.value_numeric == 10.2

    def test_flammability_gasname_not_o2(self):
        """flam_gasname=NITROGEN but moc_o2_pct=30 -> gas_type O2, concentration_pct=30"""
        row = {
            "material_key": 66228,
            "designation": "Test Material",
            "material_type_key": 235,
            "test_type": "flammability",
            "payload": {
                "flam_rating": "A",
                "flam_gasname": "NITROGEN",  # This should NOT determine O2 identity
                "flam_moc_o2_pct": 30.0,  # This IS the O2 signal
            },
        }

        record = map_flammability_row_to_record(row)

        # Verify gas_type is O2 (from flam_moc_o2_pct, not gasname)
        assert record.gas_type == GasType.O2

        # Verify concentration was captured
        o2_prop = record.get_property(PropertyKey.OXYGEN_CONCENTRATION_PCT)
        assert o2_prop is not None
        assert o2_prop.value_numeric == 30.0

    def test_flammability_uses_6001b_rating(self):
        """flam_rating_6001b takes precedence over flam_rating"""
        row = {
            "material_key": 66228,
            "designation": "Test Material",
            "material_type_key": 235,
            "test_type": "flammability",
            "payload": {
                "flam_rating": "C",
                "flam_rating_6001b": "B",  # Should use this
                "flam_moc_o2_pct": 30.0,
            },
        }

        record = map_flammability_row_to_record(row)
        rating_prop = record.get_property(PropertyKey.FLAMMABILITY_RATING)
        assert rating_prop is not None
        assert rating_prop.value_text == "B"


# ---------------------------------------------------------------------------
# Test: Fluid Compatibility Join Rule
# ---------------------------------------------------------------------------


class TestFluidCompatibilityJoin:
    """Tests for fluid_compatibility fluids table join requirement."""

    def test_fluid_compatibility_without_join(self):
        """fluid_compatibility without fluids_resolver -> excluded from twins"""
        row = {
            "material_key": 66228,
            "designation": "Test Material",
            "material_type_key": 235,
            "test_type": "fluid_compatibility",
            "payload": {
                "fluc_reference": "FLUID123",
                "fluc_rating": "A",
            },
        }

        # Without fluids_resolver, should return None
        result = map_fluid_compatibility_row_to_record(
            row, fluids_resolver=lambda x: None
        )
        assert result is None

    def test_fluid_compatibility_with_h2_join(self):
        """fluid_compatibility with H2 fluid -> H2 twin"""
        fluids_map = {
            "FLUID123": FluidInfo(
                fluid_key="FLUID123", fluid_name="GASEOUS HYDROGEN"
            )
        }
        resolver = make_fluids_resolver_from_map(fluids_map)

        row = {
            "material_key": 66228,
            "designation": "Test Material",
            "material_type_key": 235,
            "test_type": "fluid_compatibility",
            "payload": {
                "fluc_reference": "FLUID123",
                "fluc_rating": "A",
            },
        }

        record = map_fluid_compatibility_row_to_record(row, fluids_resolver=resolver)

        assert record is not None
        assert record.gas_type == GasType.H2

    def test_fluid_compatibility_non_h2o2(self):
        """fluid_compatibility with non-H2/O2 fluid -> excluded"""
        fluids_map = {
            "FLUID456": FluidInfo(
                fluid_key="FLUID456", fluid_name="WATER"  # Not H2 or O2
            )
        }
        resolver = make_fluids_resolver_from_map(fluids_map)

        row = {
            "material_key": 66228,
            "designation": "Test Material",
            "material_type_key": 235,
            "test_type": "fluid_compatibility",
            "payload": {
                "fluc_reference": "FLUID456",
                "fluc_rating": "A",
            },
        }

        record = map_fluid_compatibility_row_to_record(row, fluids_resolver=resolver)
        assert record is None  # Excluded because not H2/O2

    def test_maptis_rows_warns_on_missing_resolver(self):
        """maptis_rows_to_twin_records warns when fluids_resolver not provided"""
        rows = [
            {
                "material_key": 66228,
                "designation": "Test Material",
                "material_type_key": 235,
                "test_type": "fluid_compatibility",
                "payload": {
                    "fluc_reference": "FLUID123",
                    "fluc_rating": "A",
                },
            }
        ]

        records, warnings = maptis_rows_to_twin_records(
            rows, fluids_resolver=None
        )

        assert len(records) == 0
        assert len(warnings) == 1
        assert "fluids_resolver not provided" in warnings[0]


# ---------------------------------------------------------------------------
# Test: Null Envelope Overlap
# ---------------------------------------------------------------------------


class TestNullEnvelopeOverlap:
    """Tests for null-safe envelope overlap calculation."""

    def test_null_temp_overlap(self):
        """Null temp fields -> overlap component = 0.0 and warning emitted"""
        query_env = EnvironmentEnvelope(
            temp_min_f=-423,
            temp_max_f=-423,
            pressure_min_psia=500,
            pressure_max_psia=500,
            phase=Phase.LIQUID,
        )

        record_env = EnvironmentEnvelope(
            temp_min_f=None,  # Missing temperature
            temp_max_f=None,
            pressure_min_psia=500,
            pressure_max_psia=500,
            phase=Phase.LIQUID,
        )

        score, warnings = calculate_envelope_overlap(query_env, record_env)

        # Temperature overlap should be 0
        assert score < 1.0  # Some score from pressure/phase

        # Warning should be emitted
        assert any("Temperature" in w for w in warnings)

    def test_null_pressure_overlap(self):
        """Null pressure fields -> overlap component = 0.0 and warning emitted"""
        query_env = EnvironmentEnvelope(
            temp_min_f=70,
            temp_max_f=70,
            pressure_min_psia=500,
            pressure_max_psia=500,
            phase=Phase.GASEOUS,
        )

        record_env = EnvironmentEnvelope(
            temp_min_f=70,
            temp_max_f=70,
            pressure_min_psia=None,  # Missing pressure
            pressure_max_psia=None,
            phase=Phase.GASEOUS,
        )

        score, warnings = calculate_envelope_overlap(query_env, record_env)

        # Warning should be emitted
        assert any("Pressure" in w for w in warnings)

    def test_unknown_phase_overlap(self):
        """UNKNOWN phase -> phase match = 0.0 and warning emitted"""
        query_env = EnvironmentEnvelope(
            temp_min_f=70,
            temp_max_f=70,
            pressure_min_psia=500,
            pressure_max_psia=500,
            phase=Phase.GASEOUS,
        )

        record_env = EnvironmentEnvelope(
            temp_min_f=70,
            temp_max_f=70,
            pressure_min_psia=500,
            pressure_max_psia=500,
            phase=Phase.UNKNOWN,  # Unknown phase
        )

        score, warnings = calculate_envelope_overlap(query_env, record_env)

        # Warning should be emitted
        assert any("Phase" in w and "UNKNOWN" in w for w in warnings)

    def test_full_overlap(self):
        """Query fully contained in record -> overlap = 1.0"""
        query_env = EnvironmentEnvelope(
            temp_min_f=70,
            temp_max_f=80,
            pressure_min_psia=400,
            pressure_max_psia=600,
            phase=Phase.GASEOUS,
            concentration_pct=30.0,
        )

        record_env = EnvironmentEnvelope(
            temp_min_f=50,
            temp_max_f=100,  # Wider range
            pressure_min_psia=300,
            pressure_max_psia=700,  # Wider range
            phase=Phase.GASEOUS,
            concentration_pct=30.0,
        )

        score, warnings = calculate_envelope_overlap(query_env, record_env)

        assert score == pytest.approx(1.0)  # Full overlap
        assert len(warnings) == 0


# ---------------------------------------------------------------------------
# Test: COMPATIBLE Requires Direct Evidence
# ---------------------------------------------------------------------------


class TestCompatibleRequiresDirectEvidence:
    """Tests that COMPATIBLE verdict requires direct test evidence."""

    def test_compatible_requires_direct_evidence(self):
        """Score meets threshold but no DIRECT_TEST -> verdict is MARGINAL"""
        # Create a record with only BOK_PRECEDENT evidence (not DIRECT_TEST)
        record = CompatibilityRecord(
            record_id="TEST:001",
            material_key="MAPTIS:66228",
            material_name="Test Material",
            material_type_key=235,
            material_family_key=MaterialFamilyKey.AUSTENITIC_STAINLESS,
            gas_type=GasType.O2,
            environment=EnvironmentEnvelope(
                temp_min_f=70,
                temp_max_f=70,
                pressure_min_psia=500,
                pressure_max_psia=500,
                phase=Phase.GASEOUS,
                concentration_pct=30.0,
            ),
            compatibility=CompatibilityClass.INSUFFICIENT_DATA,
            reason="Test record",
            properties=[
                PropertyEvidence(
                    property_key=PropertyKey.FLAMMABILITY_RATING,
                    value_text="A",
                    source_ref="BOK-001",
                    data_class=DataClass.BOK_PRECEDENT,  # NOT direct test
                )
            ],
            standard_ref="NASA-STD-6001B",
            source="TEST",
        )

        query_env = EnvironmentEnvelope(
            temp_min_f=70,
            temp_max_f=70,
            pressure_min_psia=500,
            pressure_max_psia=500,
            phase=Phase.GASEOUS,
            concentration_pct=30.0,
        )

        assessment = compute_verdict(
            material_key="MAPTIS:66228",
            material_name="Test Material",
            gas_type=GasType.O2,
            query_env=query_env,
            matched_records=[record],
        )

        # Should NOT be COMPATIBLE without direct evidence
        assert assessment.verdict != CompatibilityClass.COMPATIBLE
        assert assessment.has_direct_evidence is False

    def test_compatible_with_direct_evidence(self):
        """Score meets threshold with DIRECT_TEST -> verdict is COMPATIBLE"""
        record = CompatibilityRecord(
            record_id="TEST:002",
            material_key="MAPTIS:66228",
            material_name="Test Material",
            material_type_key=235,
            material_family_key=MaterialFamilyKey.AUSTENITIC_STAINLESS,
            gas_type=GasType.O2,
            environment=EnvironmentEnvelope(
                temp_min_f=70,
                temp_max_f=70,
                pressure_min_psia=500,
                pressure_max_psia=500,
                phase=Phase.GASEOUS,
                concentration_pct=30.0,
            ),
            compatibility=CompatibilityClass.INSUFFICIENT_DATA,
            reason="Test record",
            properties=[
                PropertyEvidence(
                    property_key=PropertyKey.FLAMMABILITY_RATING,
                    value_text="A",
                    source_ref="TEST-001",
                    data_class=DataClass.DIRECT_TEST,  # Direct test evidence
                )
            ],
            standard_ref="NASA-STD-6001B",
            source="MAPTIS",
        )

        query_env = EnvironmentEnvelope(
            temp_min_f=70,
            temp_max_f=70,
            pressure_min_psia=500,
            pressure_max_psia=500,
            phase=Phase.GASEOUS,
            concentration_pct=30.0,
        )

        assessment = compute_verdict(
            material_key="MAPTIS:66228",
            material_name="Test Material",
            gas_type=GasType.O2,
            query_env=query_env,
            matched_records=[record],
        )

        # Should have direct evidence flag
        assert assessment.has_direct_evidence is True


# ---------------------------------------------------------------------------
# Test: Hard Rejects
# ---------------------------------------------------------------------------


class TestHardRejects:
    """Tests for hard rejection rules."""

    def test_flammability_d_rating_hard_reject(self):
        """Flammability rating D -> immediate INCOMPATIBLE"""
        record = CompatibilityRecord(
            record_id="TEST:003",
            material_key="MAPTIS:66228",
            material_name="Test Material",
            material_type_key=235,
            gas_type=GasType.O2,
            environment=EnvironmentEnvelope(phase=Phase.GASEOUS),
            compatibility=CompatibilityClass.INSUFFICIENT_DATA,
            reason="Test record",
            properties=[
                PropertyEvidence(
                    property_key=PropertyKey.FLAMMABILITY_RATING,
                    value_text="D",  # Hard reject rating
                    source_ref="TEST-001",
                    data_class=DataClass.DIRECT_TEST,
                )
            ],
            standard_ref="NASA-STD-6001B",
            source="MAPTIS",
        )

        is_rejected, reason = check_hard_rejects(record, O2_SCORING_PROFILE)

        assert is_rejected is True
        assert "D" in reason

    def test_flammability_x_rating_hard_reject(self):
        """Flammability rating X (unknown) -> immediate INCOMPATIBLE"""
        record = CompatibilityRecord(
            record_id="TEST:004",
            material_key="MAPTIS:66228",
            material_name="Test Material",
            material_type_key=235,
            gas_type=GasType.O2,
            environment=EnvironmentEnvelope(phase=Phase.GASEOUS),
            compatibility=CompatibilityClass.INSUFFICIENT_DATA,
            reason="Test record",
            properties=[
                PropertyEvidence(
                    property_key=PropertyKey.FLAMMABILITY_RATING,
                    value_text="X",  # Hard reject rating
                    source_ref="TEST-001",
                    data_class=DataClass.DIRECT_TEST,
                )
            ],
            standard_ref="NASA-STD-6001B",
            source="MAPTIS",
        )

        is_rejected, reason = check_hard_rejects(record, O2_SCORING_PROFILE)

        assert is_rejected is True
        assert "X" in reason

    def test_flammability_a_rating_not_rejected(self):
        """Flammability rating A -> NOT rejected"""
        record = CompatibilityRecord(
            record_id="TEST:005",
            material_key="MAPTIS:66228",
            material_name="Test Material",
            material_type_key=235,
            gas_type=GasType.O2,
            environment=EnvironmentEnvelope(phase=Phase.GASEOUS),
            compatibility=CompatibilityClass.INSUFFICIENT_DATA,
            reason="Test record",
            properties=[
                PropertyEvidence(
                    property_key=PropertyKey.FLAMMABILITY_RATING,
                    value_text="A",  # Good rating
                    source_ref="TEST-001",
                    data_class=DataClass.DIRECT_TEST,
                )
            ],
            standard_ref="NASA-STD-6001B",
            source="MAPTIS",
        )

        is_rejected, reason = check_hard_rejects(record, O2_SCORING_PROFILE)

        assert is_rejected is False
        assert reason is None


# ---------------------------------------------------------------------------
# Test: Embedding Normalization
# ---------------------------------------------------------------------------


class TestEmbeddingNormalization:
    """Tests for embedding normalization."""

    def test_embedding_normalization(self):
        """Embeddings must have L2 norm = 1.0"""
        raw_embedding = [0.5, 0.5, 0.5, 0.5] + [0.0] * 764  # 768-dim

        normalized = normalize_embedding(raw_embedding)

        # Check norm
        norm = math.sqrt(sum(x * x for x in normalized))
        assert abs(norm - 1.0) < 1e-6

    def test_zero_embedding_raises(self):
        """Zero-norm embedding -> raises ValueError"""
        zero_embedding = [0.0] * 768

        with pytest.raises(ValueError, match="Zero-norm"):
            normalize_embedding(zero_embedding)

    def test_normalized_embedding_unchanged(self):
        """Already normalized embedding stays normalized"""
        # Create a unit vector
        raw = [1.0 / math.sqrt(768)] * 768

        normalized = normalize_embedding(raw)

        # Should still be normalized
        norm = math.sqrt(sum(x * x for x in normalized))
        assert abs(norm - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# Test: Range Overlap
# ---------------------------------------------------------------------------


class TestRangeOverlap:
    """Tests for calculate_range_overlap."""

    def test_no_overlap(self):
        """Non-overlapping ranges -> 0.0"""
        assert calculate_range_overlap(0, 10, 20, 30) == 0.0

    def test_full_overlap(self):
        """Query contained in record -> 1.0"""
        assert calculate_range_overlap(5, 15, 0, 20) == 1.0

    def test_partial_overlap(self):
        """Partial overlap -> fraction"""
        # Query 0-10, Record 5-15
        # Overlap is 5-10 = 5
        # Query size is 10
        # Overlap ratio = 5/10 = 0.5
        overlap = calculate_range_overlap(0, 10, 5, 15)
        assert overlap == 0.5

    def test_null_values(self):
        """Any null value -> 0.0"""
        assert calculate_range_overlap(None, 10, 0, 20) == 0.0
        assert calculate_range_overlap(0, None, 0, 20) == 0.0
        assert calculate_range_overlap(0, 10, None, 20) == 0.0
        assert calculate_range_overlap(0, 10, 0, None) == 0.0


# ---------------------------------------------------------------------------
# Test: Scoring Profile Validation
# ---------------------------------------------------------------------------


class TestScoringProfiles:
    """Tests for scoring profile validation."""

    def test_h2_profile_valid(self):
        """H2 scoring profile is valid"""
        assert H2_SCORING_PROFILE.gas_type == GasType.H2
        assert H2_SCORING_PROFILE.thresholds["compatible"] > H2_SCORING_PROFILE.thresholds["marginal"]

    def test_o2_profile_valid(self):
        """O2 scoring profile is valid"""
        assert O2_SCORING_PROFILE.gas_type == GasType.O2
        assert O2_SCORING_PROFILE.thresholds["compatible"] > O2_SCORING_PROFILE.thresholds["marginal"]

    def test_o2_hard_reject_ratings(self):
        """O2 profile has correct hard reject ratings"""
        reject_ratings = get_hard_reject_ratings(O2_SCORING_PROFILE)
        assert "D" in reject_ratings
        assert "X" in reject_ratings
        assert "U" in reject_ratings
        assert "A" not in reject_ratings

    def test_family_bonus_austenitic(self):
        """Austenitic stainless gets family bonus"""
        h2_bonus = get_family_bonus(H2_SCORING_PROFILE, MaterialFamilyKey.AUSTENITIC_STAINLESS)
        o2_bonus = get_family_bonus(O2_SCORING_PROFILE, MaterialFamilyKey.AUSTENITIC_STAINLESS)

        assert h2_bonus > 0
        assert o2_bonus > 0

    def test_family_bonus_unknown(self):
        """Unknown family gets no bonus"""
        bonus = get_family_bonus(H2_SCORING_PROFILE, MaterialFamilyKey.UNKNOWN)
        assert bonus == 0.0

        bonus_none = get_family_bonus(H2_SCORING_PROFILE, None)
        assert bonus_none == 0.0


# ---------------------------------------------------------------------------
# Test: Flammability Rating Normalization
# ---------------------------------------------------------------------------


class TestFlammabilityRatingNormalization:
    """Tests for flammability rating score normalization."""

    def test_rating_a_score(self):
        """Rating A -> score 1.0"""
        assert normalize_flammability_rating("A") == 1.0

    def test_rating_b_score(self):
        """Rating B -> score 0.75"""
        assert normalize_flammability_rating("B") == 0.75

    def test_rating_c_score(self):
        """Rating C -> score 0.45"""
        assert normalize_flammability_rating("C") == 0.45

    def test_rating_d_score(self):
        """Rating D -> score 0.0 (hard reject)"""
        assert normalize_flammability_rating("D") == 0.0

    def test_rating_whitespace(self):
        """Rating with whitespace handled"""
        assert normalize_flammability_rating("A ") == 1.0
        assert normalize_flammability_rating(" B") == 0.75


# ---------------------------------------------------------------------------
# Test: Envelope Validation
# ---------------------------------------------------------------------------


class TestEnvelopeValidation:
    """Tests for EnvironmentEnvelope validation."""

    def test_valid_envelope(self):
        """Valid envelope passes validation"""
        env = EnvironmentEnvelope(
            temp_min_f=-423,
            temp_max_f=-423,
            pressure_min_psia=500,
            pressure_max_psia=500,
            phase=Phase.LIQUID,
            concentration_pct=100.0,
        )
        assert env.temp_min_f == -423

    def test_paired_temps_required(self):
        """temp_min_f and temp_max_f must both be set or both None"""
        with pytest.raises(ValueError, match="both be set or both be None"):
            EnvironmentEnvelope(
                temp_min_f=70,
                temp_max_f=None,  # One set, one None
                phase=Phase.GASEOUS,
            )

    def test_temp_range_valid(self):
        """temp_max_f must be >= temp_min_f"""
        with pytest.raises(ValueError, match="must be >= temp_min_f"):
            EnvironmentEnvelope(
                temp_min_f=100,
                temp_max_f=50,  # Invalid: max < min
                phase=Phase.GASEOUS,
            )

    def test_concentration_bounds(self):
        """concentration_pct must be in [0, 100]"""
        with pytest.raises(ValueError, match="within \\[0,100\\]"):
            EnvironmentEnvelope(
                phase=Phase.GASEOUS,
                concentration_pct=150.0,  # Invalid: > 100
            )


# ---------------------------------------------------------------------------
# Test: Property Evidence Validation
# ---------------------------------------------------------------------------


class TestPropertyEvidenceValidation:
    """Tests for PropertyEvidence validation."""

    def test_requires_value(self):
        """PropertyEvidence requires value_numeric or value_text"""
        with pytest.raises(ValueError, match="requires value_numeric or value_text"):
            PropertyEvidence(
                property_key=PropertyKey.FLAMMABILITY_RATING,
                # No value_numeric or value_text
                source_ref="TEST",
                data_class=DataClass.DIRECT_TEST,
            )

    def test_numeric_value_valid(self):
        """PropertyEvidence with numeric value is valid"""
        prop = PropertyEvidence(
            property_key=PropertyKey.TEST_PRESSURE_PSIA,
            value_numeric=500.0,
            units="psia",
            source_ref="TEST",
            data_class=DataClass.DIRECT_TEST,
        )
        assert prop.value_numeric == 500.0

    def test_text_value_valid(self):
        """PropertyEvidence with text value is valid"""
        prop = PropertyEvidence(
            property_key=PropertyKey.FLAMMABILITY_RATING,
            value_text="A",
            source_ref="TEST",
            data_class=DataClass.DIRECT_TEST,
        )
        assert prop.value_text == "A"


# ---------------------------------------------------------------------------
# Test: Embedding Text Generation
# ---------------------------------------------------------------------------


class TestEmbeddingTextGeneration:
    """Tests for create_embedding_text."""

    def test_creates_searchable_text(self):
        """Creates text suitable for semantic search"""
        record = CompatibilityRecord(
            record_id="TEST:001",
            material_key="MAPTIS:66228",
            material_name="316 Stainless Steel",
            material_type_key=235,
            gas_type=GasType.O2,
            environment=EnvironmentEnvelope(
                temp_min_f=70,
                temp_max_f=70,
                pressure_min_psia=500,
                pressure_max_psia=500,
                phase=Phase.GASEOUS,
                concentration_pct=30.0,
            ),
            compatibility=CompatibilityClass.COMPATIBLE,
            reason="Excellent O2 compatibility",
            properties=[
                PropertyEvidence(
                    property_key=PropertyKey.FLAMMABILITY_RATING,
                    value_text="A",
                    source_ref="TEST",
                    data_class=DataClass.DIRECT_TEST,
                )
            ],
            standard_ref="NASA-STD-6001B",
            source="MAPTIS",
        )

        text = create_embedding_text(record)

        # Verify key elements are in text
        assert "316 Stainless Steel" in text
        assert "MAPTIS:66228" in text
        assert "O2 service" in text
        assert "gaseous" in text
        assert "compatible" in text

    def test_handles_null_envelope_fields(self):
        """Handles null envelope fields gracefully"""
        record = CompatibilityRecord(
            record_id="TEST:002",
            material_key="MAPTIS:66228",
            material_name="Test Material",
            material_type_key=235,
            gas_type=GasType.H2,
            environment=EnvironmentEnvelope(
                temp_min_f=None,
                temp_max_f=None,
                pressure_min_psia=None,
                pressure_max_psia=None,
                phase=Phase.UNKNOWN,
            ),
            compatibility=CompatibilityClass.INSUFFICIENT_DATA,
            reason="Test",
            standard_ref="MAPTIS",
            source="MAPTIS",
        )

        text = create_embedding_text(record)

        # Should handle nulls gracefully
        assert "unknown" in text.lower()
        assert "temp unknown" in text.lower()
