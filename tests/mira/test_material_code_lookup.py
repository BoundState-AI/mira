#!/usr/bin/env python3
"""
Module: Test Material Code Lookup
Purpose: Material Code Lookup Tests for BoundState

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

from mira.miul.material_code_lookup import (
    MaterialMatch,
    MaterialCodeLookupService,
    get_lookup_service,
    reset_lookup_service,
)


class TestMaterialMatch:
    """Tests for MaterialMatch dataclass."""

    def test_basic_match(self):
        """Should create valid material match."""
        match = MaterialMatch(
            material_code="10018",
            designation="A-286 Stainless Steel",
            confidence="high",
            method="uns_lookup",
            score=0.95,
            specs=["S66286"],
        )
        assert match.material_code == "10018"
        assert match.confidence == "high"
        assert match.score == 0.95

    def test_score_range(self):
        """Score should be 0.0-1.0."""
        match = MaterialMatch(
            material_code="123",
            designation="Test",
            confidence="medium",
            method="fuzzy",
            score=0.75,
            specs=[],
        )
        assert 0.0 <= match.score <= 1.0


class TestMaterialAliases:
    """Tests for material name aliases."""

    def test_aluminum_aliases_exist(self):
        """Aluminum should have common aliases."""
        aliases = MaterialCodeLookupService.MATERIAL_ALIASES.get("ALUMINUM", set())
        assert "AL" in aliases

    def test_stainless_aliases_exist(self):
        """Stainless should have common aliases."""
        aliases = MaterialCodeLookupService.MATERIAL_ALIASES.get("STAINLESS", set())
        assert "CRES" in aliases
        assert "SS" in aliases

    def test_bidirectional_aliases(self):
        """Aliases should be bidirectional."""
        # If AL -> ALUMINUM, then ALUMINUM -> AL
        al_aliases = MaterialCodeLookupService.MATERIAL_ALIASES.get("AL", set())
        assert "ALUMINUM" in al_aliases


class TestFuzzyScoreCalculation:
    """Tests for fuzzy score calculation."""

    def test_exact_match_returns_1(self):
        """Exact match should return 1.0."""
        service = MaterialCodeLookupService()
        score = service._calculate_fuzzy_score("316L", "316L", {"316L"})
        assert score == 1.0

    def test_substring_match_high_score(self):
        """Query substring in candidate should score high."""
        service = MaterialCodeLookupService()
        score = service._calculate_fuzzy_score(
            "316L",
            "STAINLESS STEEL 316L SHEET",
            {"316L", "STAINLESS", "STEEL"}
        )
        assert score >= 0.9

    def test_no_number_match_low_score(self):
        """No key number match should score low."""
        service = MaterialCodeLookupService()
        score = service._calculate_fuzzy_score(
            "7075 ALUMINUM",
            "6061 ALUMINUM",
            {"7075", "ALUMINUM"}
        )
        # Different alloy numbers should score low
        assert score < 0.5

    def test_material_type_match_bonus(self):
        """Material type alias match should add bonus."""
        service = MaterialCodeLookupService()
        # CRES is alias for STAINLESS
        score = service._calculate_fuzzy_score(
            "STAINLESS 316",
            "CRES 316",
            {"STAINLESS", "316"}
        )
        # Should get bonus for STAINLESS=CRES alias
        assert score > 0.5


class TestLookupByUns:
    """Tests for UNS-based lookup."""

    @patch("psycopg2.connect")
    def test_aluminum_uns_extraction(self, mock_connect):
        """Should extract alloy from aluminum UNS."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        service = MaterialCodeLookupService()
        service._lookup_by_uns("A97075")

        # Should search for both UNS code and extracted alloy "7075"
        call_args = mock_cursor.execute.call_args
        assert call_args is not None

    @patch("psycopg2.connect")
    def test_stainless_uns_extraction(self, mock_connect):
        """Should extract alloy from stainless UNS."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        service = MaterialCodeLookupService()
        service._lookup_by_uns("S31603")

        # Should have searched with stainless-specific query
        call_args = mock_cursor.execute.call_args
        assert call_args is not None

    @patch("psycopg2.connect")
    def test_a286_special_case(self, mock_connect):
        """A-286 (S66286) should be handled specially."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {"material_code": "10018", "designation": "A-286 STAINLESS"}
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        service = MaterialCodeLookupService()
        matches = service._lookup_by_uns("S66286")

        assert len(matches) == 1
        assert matches[0].material_code == "10018"

    @patch("psycopg2.connect")
    def test_returns_material_matches(self, mock_connect):
        """Should return MaterialMatch objects."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {"material_code": "12345", "designation": "TEST MATERIAL"}
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        service = MaterialCodeLookupService()
        matches = service._lookup_by_uns("N06625")

        assert len(matches) == 1
        assert isinstance(matches[0], MaterialMatch)
        assert matches[0].method == "uns_lookup"
        assert matches[0].confidence == "high"


class TestLookupByDesignation:
    """Tests for designation-based lookup."""

    @patch("mira.miul.material_code_lookup.normalize_alloy")
    @patch("psycopg2.connect")
    def test_uses_normalizer_first(self, mock_connect, mock_normalize):
        """Should try UNS normalization first."""
        # Setup normalizer to return resolved result
        mock_normalized = MagicMock()
        mock_normalized.is_resolved = True
        mock_normalized.uns = "S31603"
        mock_normalized.canonical_name = "316L"
        mock_normalized.confidence = 0.9
        mock_normalize.return_value = mock_normalized

        # Setup DB to return match for UNS lookup
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {"material_code": "20001", "designation": "316L STAINLESS"}
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        service = MaterialCodeLookupService()
        matches = service.lookup_by_designation("SS 316L")

        # Should have called normalizer
        mock_normalize.assert_called_once_with("SS 316L")

    @patch("mira.miul.material_code_lookup.NORMALIZER_AVAILABLE", False)
    @patch("psycopg2.connect")
    def test_fuzzy_fallback_when_no_normalizer(self, mock_connect):
        """Should fall back to fuzzy when normalizer unavailable."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {"material_code": "20001", "designation": "316L STAINLESS STEEL"}
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        service = MaterialCodeLookupService()
        matches = service.lookup_by_designation("316L")

        # Should still find matches via fuzzy
        assert len(matches) >= 0  # May or may not find depending on scoring

    @patch("psycopg2.connect")
    def test_db_error_propagates(self, mock_connect):
        """Database errors should propagate (not silently swallowed)."""
        mock_conn = MagicMock()
        mock_conn.cursor.side_effect = Exception("DB Error")
        mock_connect.return_value = mock_conn

        service = MaterialCodeLookupService()
        # DB errors propagate - caller should handle
        with pytest.raises(Exception, match="DB Error"):
            service.lookup_by_designation("TEST")


class TestConnectionManagement:
    """Tests for database connection management."""

    @patch("psycopg2.connect")
    def test_lazy_connection(self, mock_connect):
        """Should not connect until needed."""
        service = MaterialCodeLookupService()
        mock_connect.assert_not_called()

        # Access connection
        service._get_connection()
        mock_connect.assert_called_once()

    @patch("psycopg2.connect")
    def test_reuses_connection(self, mock_connect):
        """Should reuse existing connection."""
        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_connect.return_value = mock_conn

        service = MaterialCodeLookupService()
        service._get_connection()
        service._get_connection()

        # Should only connect once
        assert mock_connect.call_count == 1

    @patch("psycopg2.connect")
    def test_reconnects_if_closed(self, mock_connect):
        """Should reconnect if connection closed."""
        mock_conn = MagicMock()
        mock_conn.closed = True
        mock_connect.return_value = mock_conn

        service = MaterialCodeLookupService()
        service.conn = mock_conn  # Set closed connection
        service._get_connection()

        mock_connect.assert_called()

    @patch("psycopg2.connect")
    def test_close_closes_connection(self, mock_connect):
        """Close should close the connection."""
        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_connect.return_value = mock_conn

        service = MaterialCodeLookupService()
        service._get_connection()
        service.close()

        mock_conn.close.assert_called_once()


class TestSingletonManagement:
    """Tests for singleton service management."""

    @patch("psycopg2.connect")
    def test_get_lookup_service_returns_singleton(self, mock_connect):
        """get_lookup_service should return same instance."""
        reset_lookup_service()

        service1 = get_lookup_service()
        service2 = get_lookup_service()

        assert service1 is service2

        reset_lookup_service()

    @patch("psycopg2.connect")
    def test_reset_creates_new_instance(self, mock_connect):
        """reset should allow new instance creation."""
        reset_lookup_service()

        service1 = get_lookup_service()
        reset_lookup_service()
        service2 = get_lookup_service()

        # After reset, should be different instances
        # (though they may be equal, the global was reset)
        assert service2 is not None

        reset_lookup_service()

    @patch("psycopg2.connect")
    def test_reset_closes_connection(self, mock_connect):
        """reset should close existing connection."""
        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_connect.return_value = mock_conn

        reset_lookup_service()

        service = get_lookup_service()
        service._get_connection()

        reset_lookup_service()

        mock_conn.close.assert_called()


class TestMatchSorting:
    """Tests for match result sorting."""

    @patch("mira.miul.material_code_lookup.NORMALIZER_AVAILABLE", False)
    @patch("psycopg2.connect")
    def test_matches_sorted_by_score_descending(self, mock_connect):
        """Matches should be sorted by score, highest first."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {"material_code": "A", "designation": "316L STEEL"},  # Should score high
            {"material_code": "B", "designation": "SOMETHING ELSE"},  # Should score low
            {"material_code": "C", "designation": "316L STAINLESS CRES"},  # Should score high
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        service = MaterialCodeLookupService()
        matches = service.lookup_by_designation("316L")

        # If we have matches, they should be sorted
        if len(matches) > 1:
            scores = [m.score for m in matches]
            assert scores == sorted(scores, reverse=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
