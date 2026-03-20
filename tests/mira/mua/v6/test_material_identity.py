#!/usr/bin/env python3
"""
Module: Test Material Identity
Purpose: Tests for Material Identity Resolution (MUA v6).

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
from unittest.mock import MagicMock, patch

sys.path.insert(0, r"C:\BoundState")

from mira.mua.v6.material_identity import (
    MaterialIdentity,
    MaterialCandidate,
    ResolutionMethod,
    ConfidenceLevel,
    resolve_material_identity,
    _detect_family,
    _map_confidence,
    _map_method,
)


class TestMaterialIdentity:
    """Tests for MaterialIdentity model."""

    def test_resolved_identity(self):
        """Resolved identity should have material_code and is_resolved=True."""
        identity = MaterialIdentity(
            material_code="10018",
            designation="A-286 STAINLESS STEEL",
            confidence=ConfidenceLevel.HIGH,
            method=ResolutionMethod.UNS_NORMALIZED,
            score=0.95,
            specs=["S66286"],
        )
        assert identity.is_resolved
        assert not identity.needs_review
        assert identity.material_code == "10018"

    def test_unresolved_identity_none_code(self):
        """Unresolved identity with None material_code should have is_resolved=False."""
        identity = MaterialIdentity(
            material_code=None,
            designation="UNKNOWN MATERIAL XYZ",
            confidence=ConfidenceLevel.LOW,
            method=ResolutionMethod.UNRESOLVED,
            score=0.0,
        )
        assert not identity.is_resolved
        assert identity.needs_review

    def test_low_confidence_needs_review(self):
        """Low confidence (score < 0.5) should need review even with a code."""
        identity = MaterialIdentity(
            material_code="12345",
            designation="AMBIGUOUS ALLOY",
            confidence=ConfidenceLevel.LOW,
            method=ResolutionMethod.FAMILY_FILTERED,
            score=0.3,
        )
        assert identity.is_resolved  # Has a code
        assert identity.needs_review  # But score < 0.5

    def test_medium_confidence_no_review(self):
        """Medium confidence (score >= 0.5) should not need review if has code."""
        identity = MaterialIdentity(
            material_code="12345",
            designation="SOME ALLOY",
            confidence=ConfidenceLevel.MEDIUM,
            method=ResolutionMethod.FAMILY_FILTERED,
            score=0.6,
        )
        assert identity.is_resolved
        assert not identity.needs_review

    def test_ambiguous_with_candidates(self):
        """Ambiguous identity should have candidates list."""
        identity = MaterialIdentity(
            material_code=None,
            designation="302 SST",
            confidence=ConfidenceLevel.LOW,
            method=ResolutionMethod.AMBIGUOUS,
            score=0.3,
            candidates=[
                MaterialCandidate(material_code="10089", designation="CRES 302", score=0.6),
                MaterialCandidate(material_code="10090", designation="302 SS", score=0.55),
            ],
        )
        assert identity.is_ambiguous
        assert len(identity.candidates) == 2
        assert not identity.is_resolved


class TestMaterialCandidate:
    """Tests for MaterialCandidate model."""

    def test_valid_candidate(self):
        """Should create valid candidate."""
        candidate = MaterialCandidate(
            material_code="10018",
            designation="A-286",
            score=0.85,
        )
        assert candidate.material_code == "10018"
        assert candidate.score == 0.85

    def test_score_bounds(self):
        """Score should be between 0 and 1."""
        candidate = MaterialCandidate(
            material_code="123",
            designation="Test",
            score=0.5,
        )
        assert 0.0 <= candidate.score <= 1.0


class TestResolutionMethod:
    """Tests for ResolutionMethod enum."""

    def test_all_methods_defined(self):
        """All expected resolution methods should be defined."""
        methods = [m.value for m in ResolutionMethod]
        assert "direct_lookup" in methods
        assert "uns_normalized" in methods
        assert "exact_match" in methods
        assert "family_filtered" in methods
        assert "ambiguous" in methods
        assert "unresolved" in methods


class TestConfidenceLevel:
    """Tests for ConfidenceLevel enum."""

    def test_all_levels_defined(self):
        """All confidence levels should be defined."""
        levels = [l.value for l in ConfidenceLevel]
        assert "high" in levels
        assert "medium" in levels
        assert "low" in levels


class TestDetectFamily:
    """Tests for _detect_family helper."""

    def test_titanium_detection(self):
        """Should detect titanium family."""
        assert _detect_family("TI-6AL-4V") == "TITANIUM"
        assert _detect_family("TITANIUM ALLOY") == "TITANIUM"

    def test_stainless_detection(self):
        """Should detect stainless family."""
        assert _detect_family("316L SST") == "STAINLESS"
        assert _detect_family("CRES 304") == "STAINLESS"
        assert _detect_family("STAINLESS STEEL") == "STAINLESS"

    def test_nickel_detection(self):
        """Should detect nickel family."""
        assert _detect_family("INCONEL 625") == "NICKEL"
        assert _detect_family("HASTELLOY X") == "NICKEL"
        assert _detect_family("MONEL 400") == "NICKEL"

    def test_aluminum_detection(self):
        """Should detect aluminum family."""
        assert _detect_family("ALUMINUM 6061") == "ALUMINUM"
        assert _detect_family("AL 7075") == "ALUMINUM"

    def test_no_family_returns_none(self):
        """Unknown materials should return None."""
        assert _detect_family("UNKNOWN MATERIAL") is None
        assert _detect_family("") is None
        assert _detect_family(None) is None


class TestMapConfidence:
    """Tests for _map_confidence helper."""

    def test_string_mapping(self):
        """Should map string confidence values."""
        assert _map_confidence("high", 0.9) == ConfidenceLevel.HIGH
        assert _map_confidence("medium", 0.6) == ConfidenceLevel.MEDIUM
        assert _map_confidence("low", 0.3) == ConfidenceLevel.LOW

    def test_score_fallback(self):
        """Should fall back to score-based classification."""
        assert _map_confidence("unknown", 0.8) == ConfidenceLevel.HIGH
        assert _map_confidence("unknown", 0.6) == ConfidenceLevel.MEDIUM
        assert _map_confidence("unknown", 0.3) == ConfidenceLevel.LOW


class TestMapMethod:
    """Tests for _map_method helper."""

    def test_known_methods(self):
        """Should map known method strings."""
        assert _map_method("direct_lookup") == ResolutionMethod.DIRECT_LOOKUP
        assert _map_method("uns_normalized") == ResolutionMethod.UNS_NORMALIZED
        assert _map_method("exact_match") == ResolutionMethod.EXACT_MATCH
        assert _map_method("family_filtered") == ResolutionMethod.FAMILY_FILTERED
        assert _map_method("ambiguous") == ResolutionMethod.AMBIGUOUS
        assert _map_method("unresolved") == ResolutionMethod.UNRESOLVED

    def test_unknown_defaults_to_unresolved(self):
        """Unknown methods should default to UNRESOLVED."""
        assert _map_method("unknown") == ResolutionMethod.UNRESOLVED
        assert _map_method("") == ResolutionMethod.UNRESOLVED


class TestResolveMaterialIdentity:
    """Tests for resolve_material_identity function."""

    def test_empty_designation_returns_unresolved(self):
        """Empty designation should return unresolved identity."""
        result = resolve_material_identity("")
        assert not result.is_resolved
        assert result.method == ResolutionMethod.UNRESOLVED
        assert result.score == 0.0

    def test_whitespace_only_returns_unresolved(self):
        """Whitespace-only designation should return unresolved."""
        result = resolve_material_identity("   ")
        assert not result.is_resolved

    @patch("mira.mua.v6.material_identity.get_lookup_service")
    def test_high_confidence_match(self, mock_get_service):
        """High confidence match should return resolved identity."""
        from mira.miul.material_code_lookup import MaterialMatch

        mock_match = MaterialMatch(
            material_code="10018",
            designation="A-286 STAINLESS STEEL",
            confidence="high",
            method="uns_normalized",
            score=0.95,
            specs=["S66286"],
        )
        mock_service = MagicMock()
        mock_service.lookup_material_code.return_value = mock_match
        mock_get_service.return_value = mock_service

        result = resolve_material_identity("A-286")

        assert result.is_resolved
        assert result.material_code == "10018"
        assert result.confidence == ConfidenceLevel.HIGH
        assert result.score == 0.95
        assert "S66286" in result.specs

    @patch("mira.mua.v6.material_identity.get_lookup_service")
    def test_ambiguous_match_no_code(self, mock_get_service):
        """Ambiguous match should have None material_code."""
        from mira.miul.material_code_lookup import MaterialMatch

        candidate = MaterialMatch(
            material_code="10089",
            designation="CRES 302",
            confidence="medium",
            method="family_filtered",
            score=0.6,
            specs=[],
        )

        mock_match = MaterialMatch(
            material_code=None,
            designation="302 SST",
            confidence="low",
            method="ambiguous",
            score=0.3,
            specs=[],
            candidates=[candidate],
        )
        mock_service = MagicMock()
        mock_service.lookup_material_code.return_value = mock_match
        mock_get_service.return_value = mock_service

        result = resolve_material_identity("302 SST")

        assert not result.is_resolved
        assert result.material_code is None
        assert result.method == ResolutionMethod.AMBIGUOUS
        assert len(result.candidates) == 1
        assert result.candidates[0].material_code == "10089"

    @patch("mira.mua.v6.material_identity.get_lookup_service")
    def test_lookup_error_returns_unresolved(self, mock_get_service):
        """Lookup service error should return unresolved identity."""
        mock_service = MagicMock()
        mock_service.lookup_material_code.side_effect = Exception("DB error")
        mock_get_service.return_value = mock_service

        result = resolve_material_identity("INCONEL 625")

        assert not result.is_resolved
        assert result.method == ResolutionMethod.UNRESOLVED
        assert "error" in result.source.lower()

    @patch("mira.mua.v6.material_identity.get_lookup_service")
    def test_family_detected_in_result(self, mock_get_service):
        """Material family should be detected from designation."""
        from mira.miul.material_code_lookup import MaterialMatch

        mock_match = MaterialMatch(
            material_code="20001",
            designation="TI-6AL-4V",
            confidence="high",
            method="uns_normalized",
            score=0.95,
            specs=[],
        )
        mock_service = MagicMock()
        mock_service.lookup_material_code.return_value = mock_match
        mock_get_service.return_value = mock_service

        result = resolve_material_identity("TI-6AL-4V")

        assert result.material_family == "TITANIUM"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
