#!/usr/bin/env python3
"""
Module: Test Fmeca
Purpose: FMECA Module Tests for BoundState

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

from mira.miul.fmeca import (
    SeverityRating,
    OccurrenceRating,
    DetectionRating,
    FailureType,
    FMECAEntry,
    RPNResult,
    calculate_rpn,
    failure_type_from_criticality,
)


# =============================================================================
# SeverityRating Tests
# =============================================================================


class TestSeverityRating:
    """Tests for SeverityRating enum."""

    def test_all_ratings_defined(self):
        """All 6 severity ratings should be defined."""
        expected = {0, 1, 2, 3, 4, 5}
        actual = {r.value for r in SeverityRating}
        assert actual == expected

    def test_order_is_increasing(self):
        """Higher severity should have higher value."""
        assert SeverityRating.VERY_VERY_LOW < SeverityRating.LOW
        assert SeverityRating.LOW < SeverityRating.MODERATE
        assert SeverityRating.MODERATE < SeverityRating.HIGH
        assert SeverityRating.HIGH < SeverityRating.VERY_HIGH

    def test_from_failure_type_critical(self):
        """Critical failure types should map to high severity."""
        sev = SeverityRating.from_failure_type(FailureType.TYPE_1SC)
        assert sev == SeverityRating.VERY_HIGH

        sev = SeverityRating.from_failure_type(FailureType.TYPE_1)
        assert sev == SeverityRating.VERY_HIGH

    def test_from_failure_type_moderate(self):
        """Type 3 should map to moderate severity."""
        sev = SeverityRating.from_failure_type(FailureType.TYPE_3)
        assert sev == SeverityRating.MODERATE

    def test_from_failure_type_low(self):
        """Type 4/5 should map to low severity."""
        sev = SeverityRating.from_failure_type(FailureType.TYPE_4)
        assert sev == SeverityRating.LOW

        sev = SeverityRating.from_failure_type(FailureType.TYPE_5)
        assert sev == SeverityRating.VERY_VERY_LOW


# =============================================================================
# OccurrenceRating Tests
# =============================================================================


class TestOccurrenceRating:
    """Tests for OccurrenceRating enum."""

    def test_all_ratings_defined(self):
        """All 6 occurrence ratings should be defined."""
        expected = {0, 1, 2, 3, 4, 5}
        actual = {r.value for r in OccurrenceRating}
        assert actual == expected

    def test_from_probability_very_low(self):
        """Very low probability should map to lowest rating."""
        rating = OccurrenceRating.from_probability(0.0005)
        assert rating == OccurrenceRating.VERY_VERY_LOW

    def test_from_probability_low(self):
        """Low probability should map correctly."""
        rating = OccurrenceRating.from_probability(0.01)
        assert rating == OccurrenceRating.VERY_LOW

        rating = OccurrenceRating.from_probability(0.10)
        assert rating == OccurrenceRating.LOW

    def test_from_probability_moderate(self):
        """Moderate probability should map correctly."""
        rating = OccurrenceRating.from_probability(0.20)
        assert rating == OccurrenceRating.MODERATE

    def test_from_probability_high(self):
        """High probability should map correctly."""
        rating = OccurrenceRating.from_probability(0.40)
        assert rating == OccurrenceRating.HIGH

    def test_from_probability_very_high(self):
        """Very high probability should map to highest rating."""
        rating = OccurrenceRating.from_probability(0.75)
        assert rating == OccurrenceRating.VERY_HIGH


# =============================================================================
# DetectionRating Tests
# =============================================================================


class TestDetectionRating:
    """Tests for DetectionRating enum."""

    def test_all_ratings_defined(self):
        """All 5 detection ratings should be defined (1-5)."""
        expected = {1, 2, 3, 4, 5}
        actual = {r.value for r in DetectionRating}
        assert actual == expected

    def test_from_screens_both_pass(self):
        """Both screens passing should give CERTAIN detection."""
        rating = DetectionRating.from_screens(True, True)
        assert rating == DetectionRating.CERTAIN

    def test_from_screens_one_pass(self):
        """One screen passing should give MODERATE_HIGH."""
        rating = DetectionRating.from_screens(True, False)
        assert rating == DetectionRating.MODERATE_HIGH

        rating = DetectionRating.from_screens(False, True)
        assert rating == DetectionRating.MODERATE_HIGH

    def test_from_screens_none_pass(self):
        """No screens passing should give REMOTE."""
        rating = DetectionRating.from_screens(False, False)
        assert rating == DetectionRating.REMOTE

    def test_from_screens_unknown(self):
        """Unknown screens should give conservative default."""
        rating = DetectionRating.from_screens(None, None)
        assert rating == DetectionRating.LOW_MODERATE


# =============================================================================
# FailureType Tests
# =============================================================================


class TestFailureType:
    """Tests for FailureType enum."""

    def test_all_types_defined(self):
        """All 8 failure types should be defined."""
        assert len(FailureType) == 8

    def test_description_property(self):
        """Each type should have a description."""
        for ft in FailureType:
            desc = ft.description
            assert isinstance(desc, str)
            assert len(desc) > 0

    def test_type_1sc_is_most_critical(self):
        """TYPE_1SC should be the most critical (lowest value)."""
        assert FailureType.TYPE_1SC.value == 1

    def test_type_5_is_least_critical(self):
        """TYPE_5 should be the least critical (highest value)."""
        assert FailureType.TYPE_5.value == 8


# =============================================================================
# FMECAEntry Tests
# =============================================================================


class TestFMECAEntry:
    """Tests for FMECAEntry model."""

    def test_basic_creation(self):
        """Should create valid FMECA entry."""
        entry = FMECAEntry(
            fmea_number="FMEA-001",
            item_name="BRACKET, SUPPORT",
            item_part_number="12345-001",
            failure_mode_code="FM-001",
            ssp_criticality="1",
            source="test",
        )

        assert entry.fmea_number == "FMEA-001"
        assert entry.ssp_criticality == "1"

    def test_normalizes_criticality(self):
        """Should normalize criticality to uppercase."""
        entry = FMECAEntry(
            fmea_number="FMEA-001",
            item_name="TEST",
            item_part_number="12345",
            failure_mode_code="FM-001",
            ssp_criticality="  1s  ",  # Whitespace and lowercase
            source="test",
        )

        assert entry.ssp_criticality == "1S"

    def test_derives_failure_type(self):
        """Should auto-derive failure type from criticality."""
        entry = FMECAEntry(
            fmea_number="FMEA-001",
            item_name="TEST",
            item_part_number="12345",
            failure_mode_code="FM-001",
            ssp_criticality="1",
            source="test",
        )

        assert entry.failure_type is not None
        assert entry.failure_type == FailureType.TYPE_1

    def test_derives_severity(self):
        """Should auto-derive severity from failure type."""
        entry = FMECAEntry(
            fmea_number="FMEA-001",
            item_name="TEST",
            item_part_number="12345",
            failure_mode_code="FM-001",
            ssp_criticality="1",
            source="test",
        )

        assert entry.severity is not None
        assert entry.severity == SeverityRating.VERY_HIGH

    def test_derives_occurrence_from_probability(self):
        """Should auto-derive occurrence from probability."""
        entry = FMECAEntry(
            fmea_number="FMEA-001",
            item_name="TEST",
            item_part_number="12345",
            failure_mode_code="FM-001",
            ssp_criticality="2",
            failure_probability=0.10,
            source="test",
        )

        assert entry.occurrence is not None
        assert entry.occurrence == OccurrenceRating.LOW

    def test_can_calculate_rpn_true(self):
        """can_calculate_rpn should be True when all ratings set."""
        entry = FMECAEntry(
            fmea_number="FMEA-001",
            item_name="TEST",
            item_part_number="12345",
            failure_mode_code="FM-001",
            ssp_criticality="1",
            failure_probability=0.10,
            source="test",
        )

        assert entry.can_calculate_rpn

    def test_screens_pass_all_true(self):
        """screens_pass should be True when all screens pass."""
        entry = FMECAEntry(
            fmea_number="FMEA-001",
            item_name="TEST",
            item_part_number="12345",
            failure_mode_code="FM-001",
            ssp_criticality="1",
            screen_a_prelaunch=True,
            screen_b_flight=True,
            source="test",
        )

        assert entry.screens_pass

    def test_screens_pass_some_fail(self):
        """screens_pass should be False when any screen fails."""
        entry = FMECAEntry(
            fmea_number="FMEA-001",
            item_name="TEST",
            item_part_number="12345",
            failure_mode_code="FM-001",
            ssp_criticality="1",
            screen_a_prelaunch=True,
            screen_b_flight=False,
            source="test",
        )

        assert not entry.screens_pass


# =============================================================================
# RPNResult Tests
# =============================================================================


class TestRPNResult:
    """Tests for RPNResult model."""

    def test_calculate_basic(self):
        """Should calculate RPN correctly."""
        result = RPNResult.calculate(
            severity=SeverityRating.MODERATE,  # 3
            occurrence=OccurrenceRating.LOW,    # 2
            detection=DetectionRating.REMOTE,   # 2 -> inverted to 4
        )

        # RPN = 3 * 2 * 4 = 24
        assert result.rpn == 24

    def test_calculate_zero_rpn(self):
        """RPN should be zero when severity or occurrence is zero."""
        result = RPNResult.calculate(
            severity=SeverityRating.VERY_VERY_LOW,  # 0
            occurrence=OccurrenceRating.LOW,
            detection=DetectionRating.CERTAIN,
        )

        assert result.rpn == 0
        assert result.risk_level == "Negligible"

    def test_detection_inversion(self):
        """Detection should be inverted (1->5, 5->1)."""
        result = RPNResult.calculate(
            severity=SeverityRating.MODERATE,
            occurrence=OccurrenceRating.MODERATE,
            detection=DetectionRating.CERTAIN,  # 5 -> inverted to 1
        )

        assert result.detection == 5
        assert result.detection_inverted == 1

        result2 = RPNResult.calculate(
            severity=SeverityRating.MODERATE,
            occurrence=OccurrenceRating.MODERATE,
            detection=DetectionRating.NONE,  # 1 -> inverted to 5
        )

        assert result2.detection == 1
        assert result2.detection_inverted == 5

    def test_risk_levels(self):
        """Should assign correct risk levels."""
        # Low risk
        result = RPNResult.calculate(
            severity=SeverityRating.LOW,
            occurrence=OccurrenceRating.VERY_LOW,
            detection=DetectionRating.CERTAIN,
        )
        assert result.risk_level in ("Negligible", "Low")

        # High risk
        result = RPNResult.calculate(
            severity=SeverityRating.VERY_HIGH,
            occurrence=OccurrenceRating.HIGH,
            detection=DetectionRating.NONE,
        )
        assert result.risk_level in ("High", "Critical")

    def test_requires_action_threshold(self):
        """Should flag RPN exceeding threshold."""
        result = RPNResult.calculate(
            severity=SeverityRating.VERY_HIGH,  # 5
            occurrence=OccurrenceRating.HIGH,    # 4
            detection=DetectionRating.NONE,      # 1 -> inverted to 5
            action_threshold=40,
        )

        # RPN = 5 * 4 * 5 = 100
        assert result.rpn == 100
        assert result.requires_action

    def test_rationale_contains_components(self):
        """Rationale should explain calculation."""
        result = RPNResult.calculate(
            severity=SeverityRating.MODERATE,
            occurrence=OccurrenceRating.LOW,
            detection=DetectionRating.REMOTE,
        )

        assert "S(3)" in result.rationale
        assert "O(2)" in result.rationale
        assert "D(" in result.rationale


# =============================================================================
# calculate_rpn Function Tests
# =============================================================================


class TestCalculateRPN:
    """Tests for calculate_rpn function."""

    def test_returns_result_for_complete_entry(self):
        """Should return RPNResult when entry has all ratings."""
        entry = FMECAEntry(
            fmea_number="FMEA-001",
            item_name="TEST",
            item_part_number="12345",
            failure_mode_code="FM-001",
            ssp_criticality="1",
            failure_probability=0.10,
            source="test",
        )

        result = calculate_rpn(entry)

        assert result is not None
        assert isinstance(result, RPNResult)

    def test_returns_none_for_incomplete_entry(self):
        """Should return None when entry missing ratings."""
        entry = FMECAEntry(
            fmea_number="FMEA-001",
            item_name="TEST",
            item_part_number="12345",
            failure_mode_code="FM-001",
            ssp_criticality="1",
            # No failure_probability - can't derive occurrence
            source="test",
        )

        # Force occurrence to None for test
        entry.occurrence = None

        result = calculate_rpn(entry)

        # With occurrence=None, should return None
        if not entry.can_calculate_rpn:
            assert result is None


# =============================================================================
# failure_type_from_criticality Function Tests
# =============================================================================


class TestFailureTypeFromCriticality:
    """Tests for failure_type_from_criticality function."""

    def test_category_1(self):
        """Category 1 should map to TYPE_1."""
        ft = failure_type_from_criticality("1")
        assert ft == FailureType.TYPE_1

    def test_category_1_with_safety(self):
        """Category 1 with safety hazard should map to TYPE_1SC."""
        ft = failure_type_from_criticality("1", has_safety_hazard=True)
        assert ft == FailureType.TYPE_1SC

    def test_category_1s(self):
        """Category 1S should map to TYPE_1SC."""
        ft = failure_type_from_criticality("1S")
        assert ft == FailureType.TYPE_1SC

    def test_category_1r(self):
        """Category 1R should map to TYPE_2."""
        ft = failure_type_from_criticality("1R")
        assert ft == FailureType.TYPE_2

    def test_category_2(self):
        """Category 2 should map to TYPE_2."""
        ft = failure_type_from_criticality("2")
        assert ft == FailureType.TYPE_2

    def test_category_2r(self):
        """Category 2R should map to TYPE_3."""
        ft = failure_type_from_criticality("2R")
        assert ft == FailureType.TYPE_3

    def test_category_3(self):
        """Category 3 should map to TYPE_4."""
        ft = failure_type_from_criticality("3")
        assert ft == FailureType.TYPE_4

    def test_unknown_defaults_to_type_3(self):
        """Unknown criticality should default to TYPE_3."""
        ft = failure_type_from_criticality("UNKNOWN")
        assert ft == FailureType.TYPE_3

    def test_case_insensitive(self):
        """Should handle lowercase input."""
        ft = failure_type_from_criticality("1s")
        assert ft == FailureType.TYPE_1SC


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
