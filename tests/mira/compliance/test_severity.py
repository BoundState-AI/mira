#!/usr/bin/env python3
"""
Module: Test Severity Mapping
Purpose: Test coverage for HEE band to severity mapping (Fran Fix #4)

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

# Copyright (c) 2025 BoundState AI. All Rights Reserved.
# Classification: BoundState Proprietary
# License: Evaluation Use Only - Authorized Pilot Program

import pytest
import sys

sys.path.insert(0, r"C:\BoundState")

from mira.compliance.severity import (
    HEE_BAND_SEVERITY_MAP,
    HEE_BAND_TRIGGER_MAP,
    quantize_hee_severity,
    hee_band_to_trigger,
)
from mira.compliance.models.enums import GapSeverity, GapTrigger


class TestHEEBandSeverityMap:
    """Test HEE_BAND_SEVERITY_MAP constants - Fran Fix #4."""

    def test_extreme_maps_to_critical(self):
        """Extreme HEE band MUST map to CRITICAL severity."""
        assert HEE_BAND_SEVERITY_MAP["extreme"] == GapSeverity.CRITICAL

    def test_severe_maps_to_critical(self):
        """Severe HEE band MUST map to CRITICAL severity."""
        assert HEE_BAND_SEVERITY_MAP["severe"] == GapSeverity.CRITICAL

    def test_high_maps_to_high(self):
        """High HEE band MUST map to HIGH severity."""
        assert HEE_BAND_SEVERITY_MAP["high"] == GapSeverity.HIGH

    def test_small_maps_to_medium(self):
        """Small HEE band MUST map to MEDIUM severity."""
        assert HEE_BAND_SEVERITY_MAP["small"] == GapSeverity.MEDIUM

    def test_negligible_maps_to_low(self):
        """Negligible HEE band MUST map to LOW severity."""
        assert HEE_BAND_SEVERITY_MAP["negligible"] == GapSeverity.LOW

    def test_all_bands_covered(self):
        """All HEE bands must be in the map."""
        expected_bands = {"extreme", "severe", "high", "small", "negligible"}
        actual_bands = set(HEE_BAND_SEVERITY_MAP.keys())
        assert actual_bands == expected_bands, "All HEE bands must be covered"


class TestHEEBandTriggerMap:
    """Test HEE_BAND_TRIGGER_MAP constants."""

    def test_extreme_maps_to_extreme_trigger(self):
        """Extreme band should map to EXTREME trigger."""
        assert HEE_BAND_TRIGGER_MAP["extreme"] == GapTrigger.HEE_BAND_EXTREME

    def test_severe_maps_to_severe_trigger(self):
        """Severe band should map to SEVERE trigger."""
        assert HEE_BAND_TRIGGER_MAP["severe"] == GapTrigger.HEE_BAND_SEVERE

    def test_high_maps_to_high_trigger(self):
        """High band should map to HIGH trigger."""
        assert HEE_BAND_TRIGGER_MAP["high"] == GapTrigger.HEE_BAND_HIGH


class TestQuantizeHEESeverity:
    """Test quantize_hee_severity function - Fran Fix #4."""

    def test_extreme_band_returns_critical(self):
        """quantize_hee_severity('extreme') MUST return CRITICAL."""
        severity = quantize_hee_severity("extreme")
        assert severity == GapSeverity.CRITICAL

    def test_severe_band_returns_critical(self):
        """quantize_hee_severity('severe') MUST return CRITICAL."""
        severity = quantize_hee_severity("severe")
        assert severity == GapSeverity.CRITICAL

    def test_high_band_returns_high(self):
        """quantize_hee_severity('high') MUST return HIGH."""
        severity = quantize_hee_severity("high")
        assert severity == GapSeverity.HIGH

    def test_small_band_returns_medium(self):
        """quantize_hee_severity('small') MUST return MEDIUM."""
        severity = quantize_hee_severity("small")
        assert severity == GapSeverity.MEDIUM

    def test_negligible_band_returns_low(self):
        """quantize_hee_severity('negligible') MUST return LOW."""
        severity = quantize_hee_severity("negligible")
        assert severity == GapSeverity.LOW

    def test_case_insensitive(self):
        """Function should be case-insensitive."""
        assert quantize_hee_severity("EXTREME") == GapSeverity.CRITICAL
        assert quantize_hee_severity("Extreme") == GapSeverity.CRITICAL
        assert quantize_hee_severity("SEVERE") == GapSeverity.CRITICAL

    def test_unknown_band_returns_high(self):
        """Unknown bands should default to HIGH (conservative)."""
        severity = quantize_hee_severity("unknown_band")
        assert severity == GapSeverity.HIGH

    def test_none_band_returns_high(self):
        """None input should default to HIGH (conservative)."""
        severity = quantize_hee_severity(None)
        assert severity == GapSeverity.HIGH

    def test_determinism(self):
        """Same input must ALWAYS return same output - Fran Fix #4."""
        for _ in range(100):
            assert quantize_hee_severity("extreme") == GapSeverity.CRITICAL
            assert quantize_hee_severity("severe") == GapSeverity.CRITICAL
            assert quantize_hee_severity("high") == GapSeverity.HIGH


class TestHEEBandToTrigger:
    """Test hee_band_to_trigger function."""

    def test_extreme_band_returns_extreme_trigger(self):
        """hee_band_to_trigger('extreme') should return HEE_BAND_EXTREME."""
        trigger = hee_band_to_trigger("extreme")
        assert trigger == GapTrigger.HEE_BAND_EXTREME

    def test_severe_band_returns_severe_trigger(self):
        """hee_band_to_trigger('severe') should return HEE_BAND_SEVERE."""
        trigger = hee_band_to_trigger("severe")
        assert trigger == GapTrigger.HEE_BAND_SEVERE

    def test_high_band_returns_high_trigger(self):
        """hee_band_to_trigger('high') should return HEE_BAND_HIGH."""
        trigger = hee_band_to_trigger("high")
        assert trigger == GapTrigger.HEE_BAND_HIGH

    def test_case_insensitive(self):
        """Function should be case-insensitive."""
        assert hee_band_to_trigger("EXTREME") == GapTrigger.HEE_BAND_EXTREME
        assert hee_band_to_trigger("Severe") == GapTrigger.HEE_BAND_SEVERE

    def test_unknown_band_returns_rating_non_a(self):
        """Unknown bands should return RATING_NON_A trigger (conservative default)."""
        trigger = hee_band_to_trigger("unknown")
        assert trigger == GapTrigger.RATING_NON_A

    def test_none_returns_rating_non_a(self):
        """None input should return RATING_NON_A trigger (conservative default)."""
        trigger = hee_band_to_trigger(None)
        assert trigger == GapTrigger.RATING_NON_A


class TestSeverityOrdering:
    """Test that severity mapping maintains proper ordering."""

    def test_severity_ordering_from_bands(self):
        """Extreme > Severe > High > Small > Negligible in severity."""
        extreme_sev = quantize_hee_severity("extreme")
        severe_sev = quantize_hee_severity("severe")
        high_sev = quantize_hee_severity("high")
        small_sev = quantize_hee_severity("small")
        negligible_sev = quantize_hee_severity("negligible")

        # CRITICAL is worst
        assert extreme_sev == GapSeverity.CRITICAL
        assert severe_sev == GapSeverity.CRITICAL

        # HIGH is next
        assert high_sev == GapSeverity.HIGH

        # MEDIUM is moderate
        assert small_sev == GapSeverity.MEDIUM

        # LOW is least severe
        assert negligible_sev == GapSeverity.LOW
