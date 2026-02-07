#!/usr/bin/env python3
"""
Module: Test Parsing
Purpose: Tests for athena.utils.parsing module.

BoundState AI 2025
Version: 4.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032, NASA-STD-8739.8B
Safety Critical: True
"""

from __future__ import annotations

from enum import Enum

import pytest

from athena.utils.parsing import (
    parse_confidence,
    safe_parse_enum,
    safe_parse_enum_list,
)


class TestParseConfidence:
    """Tests for parse_confidence function."""

    def test_parse_confidence_float(self):
        """Parse float value directly."""
        assert parse_confidence(0.85) == 0.85

    def test_parse_confidence_string(self):
        """Parse string to float."""
        assert parse_confidence("0.75") == 0.75

    def test_parse_confidence_none_returns_default(self):
        """None returns 0.5 default."""
        assert parse_confidence(None) == 0.5

    def test_parse_confidence_clamps_high(self):
        """Values > 1.0 are clamped to 1.0."""
        assert parse_confidence(1.5) == 1.0
        assert parse_confidence("2.0") == 1.0

    def test_parse_confidence_clamps_low(self):
        """Values < 0.0 are clamped to 0.0."""
        assert parse_confidence(-0.5) == 0.0
        assert parse_confidence("-1.0") == 0.0

    def test_parse_confidence_edge_cases(self):
        """Edge cases at boundaries."""
        assert parse_confidence(0.0) == 0.0
        assert parse_confidence(1.0) == 1.0

    def test_parse_confidence_invalid_string(self):
        """Invalid string returns 0.5 default."""
        assert parse_confidence("not a number") == 0.5
        assert parse_confidence("") == 0.5

    def test_parse_confidence_integer(self):
        """Integer values work."""
        assert parse_confidence(1) == 1.0
        assert parse_confidence(0) == 0.0


class TestSafeParseEnum:
    """Tests for safe_parse_enum function."""

    @pytest.fixture
    def status_enum(self):
        """Sample enum for testing."""
        class Status(Enum):
            PENDING = "pending"
            ACTIVE = "active"
            COMPLETED = "completed"
        return Status

    def test_safe_parse_enum_exact_value(self, status_enum):
        """Parse exact enum value."""
        result = safe_parse_enum(status_enum, "pending")

        assert result == status_enum.PENDING

    def test_safe_parse_enum_case_insensitive(self, status_enum):
        """Parse case-insensitive value."""
        result = safe_parse_enum(status_enum, "PENDING")

        assert result == status_enum.PENDING

    def test_safe_parse_enum_by_name(self, status_enum):
        """Parse by enum name (case-insensitive)."""
        result = safe_parse_enum(status_enum, "active")

        assert result == status_enum.ACTIVE

    def test_safe_parse_enum_none_returns_default(self, status_enum):
        """None value returns default."""
        result = safe_parse_enum(status_enum, None, default=status_enum.PENDING)

        assert result == status_enum.PENDING

    def test_safe_parse_enum_none_no_default(self, status_enum):
        """None value with no default returns None."""
        result = safe_parse_enum(status_enum, None)

        assert result is None

    def test_safe_parse_enum_invalid_returns_default(self, status_enum):
        """Invalid value returns default."""
        result = safe_parse_enum(
            status_enum,
            "invalid_status",
            default=status_enum.PENDING,
        )

        assert result == status_enum.PENDING

    def test_safe_parse_enum_invalid_no_default(self, status_enum):
        """Invalid value with no default returns None."""
        result = safe_parse_enum(status_enum, "invalid_status")

        assert result is None

    def test_safe_parse_enum_hyphen_to_underscore(self, status_enum):
        """Hyphens converted to underscores."""
        # Create enum with underscore in value
        class HyphenEnum(Enum):
            IN_PROGRESS = "in_progress"

        result = safe_parse_enum(HyphenEnum, "in-progress")

        assert result == HyphenEnum.IN_PROGRESS


class TestSafeParseEnumList:
    """Tests for safe_parse_enum_list function."""

    @pytest.fixture
    def color_enum(self):
        """Sample enum for testing."""
        class Color(Enum):
            RED = "red"
            GREEN = "green"
            BLUE = "blue"
        return Color

    def test_safe_parse_enum_list_all_valid(self, color_enum):
        """Parse list of valid values."""
        result = safe_parse_enum_list(color_enum, ["red", "green"])

        assert result == [color_enum.RED, color_enum.GREEN]

    def test_safe_parse_enum_list_skips_invalid(self, color_enum):
        """Invalid values are skipped."""
        result = safe_parse_enum_list(color_enum, ["red", "invalid", "blue"])

        assert result == [color_enum.RED, color_enum.BLUE]

    def test_safe_parse_enum_list_empty(self, color_enum):
        """Empty list returns empty list."""
        result = safe_parse_enum_list(color_enum, [])

        assert result == []

    def test_safe_parse_enum_list_none(self, color_enum):
        """None returns empty list."""
        result = safe_parse_enum_list(color_enum, None)

        assert result == []

    def test_safe_parse_enum_list_all_invalid(self, color_enum):
        """All invalid values returns empty list."""
        result = safe_parse_enum_list(color_enum, ["invalid1", "invalid2"])

        assert result == []

    def test_safe_parse_enum_list_case_insensitive(self, color_enum):
        """Values parsed case-insensitively."""
        result = safe_parse_enum_list(color_enum, ["RED", "Green", "BLUE"])

        assert len(result) == 3
        assert color_enum.RED in result
        assert color_enum.GREEN in result
        assert color_enum.BLUE in result


class TestEnumParsingWithAthenaEnums:
    """Tests using actual ATHENA enums if available."""

    def test_parse_ocr_source(self):
        """Parse OCRSource enum values."""
        try:
            from athena.models.enums import OCRSource
        except ImportError:
            pytest.skip("athena.models.enums not available")

        result = safe_parse_enum(OCRSource, "abbyy")

        assert result == OCRSource.ABBYY

    def test_parse_vision_trigger(self):
        """Parse VisionTrigger enum values."""
        try:
            from athena.models.enums import VisionTrigger
        except ImportError:
            pytest.skip("athena.models.enums not available")

        result = safe_parse_enum(VisionTrigger, "low_ocr_confidence")

        assert result == VisionTrigger.LOW_OCR_CONFIDENCE
