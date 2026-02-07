#!/usr/bin/env python3
"""
Module: Test Maptis Ratings
Purpose: MAPTIS Ratings Lookup Tests for BoundState

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

from mira.miul.maptis_ratings import (
    MAPTISRatingsClient,
    RATING_COLUMNS,
    RATING_MAP,
    RATING_SEVERITY,
    get_ratings,
    get_ratings_bulk,
)


class TestRatingConstants:
    """Tests for rating constants and mappings."""

    def test_rating_columns_complete(self):
        """All 6 JSC 27301F rating columns should be defined."""
        expected = ["FLAM", "SCC", "CORR", "TVS", "TOX", "FS"]
        assert RATING_COLUMNS == expected

    def test_rating_map_covers_all_test_types(self):
        """RATING_MAP should map all known test report types."""
        expected_contracts = {
            "flammability_report",
            "promoted_combustion_report",
            "stress_corrosion_cracking_report",
            "corrosion_report",
            "tvs_outgassing_report",
            "toxicity_report",
            "fluid_compatibility_report",
        }
        assert set(RATING_MAP.keys()) == expected_contracts

    def test_rating_severity_ordering(self):
        """Rating severity should increase: A < B < ... < X."""
        assert RATING_SEVERITY["A"] < RATING_SEVERITY["B"]
        assert RATING_SEVERITY["B"] < RATING_SEVERITY["C"]
        assert RATING_SEVERITY["C"] < RATING_SEVERITY["D"]
        assert RATING_SEVERITY["U"] > RATING_SEVERITY["D"]
        assert RATING_SEVERITY["X"] == max(RATING_SEVERITY.values())


class TestWorstRating:
    """Tests for _worst_rating static method."""

    def test_worst_of_single_rating(self):
        """Single rating should return itself."""
        result = MAPTISRatingsClient._worst_rating(["A"])
        assert result == "A"

    def test_worst_of_multiple_ratings(self):
        """Should return most severe rating."""
        result = MAPTISRatingsClient._worst_rating(["A", "B", "C"])
        assert result == "C"

    def test_worst_with_unknown_ratings(self):
        """Should handle unknown ratings gracefully."""
        result = MAPTISRatingsClient._worst_rating(["A", "UNKNOWN", "B"])
        assert result == "B"

    def test_worst_empty_list(self):
        """Empty list should return empty string."""
        result = MAPTISRatingsClient._worst_rating([])
        assert result == ""

    def test_worst_all_unknown(self):
        """All unknown ratings should return first value."""
        result = MAPTISRatingsClient._worst_rating(["UNKNOWN", "BAD"])
        assert result == "UNKNOWN"

    def test_worst_with_u_and_x(self):
        """U and X (unverified/unknown) should be worst."""
        result = MAPTISRatingsClient._worst_rating(["A", "U", "B"])
        assert result == "U"

        result = MAPTISRatingsClient._worst_rating(["A", "X", "U"])
        assert result == "X"


class TestMAPTISRatingsClientInit:
    """Tests for client initialization."""

    def test_default_connection_params(self):
        """Default params should be localhost postgres."""
        with patch("psycopg2.connect"):
            client = MAPTISRatingsClient()
            assert client._conn_params["host"] == "localhost"
            assert client._conn_params["port"] == 5432
            assert client._conn_params["database"] == "mira"

    def test_custom_connection_params(self):
        """Custom params should override defaults when env vars not set."""
        # Clear env vars so custom params take effect
        with patch.dict("os.environ", {}, clear=True):
            with patch("psycopg2.connect"):
                client = MAPTISRatingsClient(
                    host="custom-host",
                    port=5433,
                    database="custom_db",
                    user="custom_user",
                    password="custom_pass",
                )
                assert client._conn_params["host"] == "custom-host"
                assert client._conn_params["port"] == 5433
                assert client._conn_params["database"] == "custom_db"

    @patch.dict("os.environ", {"POSTGRES_HOST": "env-host", "POSTGRES_PORT": "5434"})
    def test_env_vars_override_defaults(self):
        """Environment variables should override defaults."""
        with patch("psycopg2.connect"):
            client = MAPTISRatingsClient()
            assert client._conn_params["host"] == "env-host"
            assert client._conn_params["port"] == 5434


class TestGetRatings:
    """Tests for get_ratings single material lookup."""

    def test_empty_material_code_returns_empty(self):
        """Empty material code should return empty dict."""
        with patch("psycopg2.connect"):
            client = MAPTISRatingsClient()
            result = client.get_ratings("")
            assert result == {}

    def test_none_material_code_returns_empty(self):
        """None material code should return empty dict."""
        with patch("psycopg2.connect"):
            client = MAPTISRatingsClient()
            result = client.get_ratings(None)
            assert result == {}

    @patch("psycopg2.connect")
    def test_successful_rating_lookup(self, mock_connect):
        """Should return ratings dict from database."""
        # Setup mock cursor
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [{"rating": "A"}]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        client = MAPTISRatingsClient()
        result = client.get_ratings("20494")

        # Should have called execute for each contract_id in RATING_MAP
        assert mock_cursor.execute.call_count == len(RATING_MAP)
        # Should have at least one rating
        assert len(result) > 0

    @patch("psycopg2.connect")
    def test_strips_material_code(self, mock_connect):
        """Should strip whitespace from material code."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        client = MAPTISRatingsClient()
        client.get_ratings("  20494  ")

        # Verify the stripped code was used in queries
        call_args = mock_cursor.execute.call_args_list[0][0]
        assert "20494" in call_args[1]


class TestGetRatingsBulk:
    """Tests for get_ratings_bulk batch lookup."""

    def test_empty_list_returns_empty(self):
        """Empty list should return empty dict."""
        with patch("psycopg2.connect"):
            client = MAPTISRatingsClient()
            result = client.get_ratings_bulk([])
            assert result == {}

    @patch("psycopg2.connect")
    def test_deduplicates_codes(self, mock_connect):
        """Should dedupe material codes before querying."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        client = MAPTISRatingsClient()
        result = client.get_ratings_bulk(["20494", "20494", "20495", "20494"])

        # Result should have entries for unique codes only
        assert "20494" in result
        assert "20495" in result

    @patch("psycopg2.connect")
    def test_bulk_query_structure(self, mock_connect):
        """Bulk query should use single query with ANY() for efficiency."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        client = MAPTISRatingsClient()
        client.get_ratings_bulk(["20494", "20495"])

        # Should execute single bulk query (not per-material)
        assert mock_cursor.execute.call_count == 1

        # Query should use ANY() operator
        sql = mock_cursor.execute.call_args[0][0]
        assert "ANY" in sql


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    @patch("mira.miul.maptis_ratings.MAPTISRatingsClient")
    def test_get_ratings_creates_and_closes_client(self, mock_client_class):
        """get_ratings should create client, query, then close."""
        mock_client = MagicMock()
        mock_client.get_ratings.return_value = {"FLAM": "A"}
        mock_client_class.return_value = mock_client

        result = get_ratings("20494")

        mock_client_class.assert_called_once()
        mock_client.get_ratings.assert_called_once_with("20494")
        mock_client.close.assert_called_once()
        assert result == {"FLAM": "A"}

    @patch("mira.miul.maptis_ratings.MAPTISRatingsClient")
    def test_get_ratings_bulk_creates_and_closes_client(self, mock_client_class):
        """get_ratings_bulk should create client, query, then close."""
        mock_client = MagicMock()
        mock_client.get_ratings_bulk.return_value = {"20494": {"FLAM": "A"}}
        mock_client_class.return_value = mock_client

        result = get_ratings_bulk(["20494"])

        mock_client_class.assert_called_once()
        mock_client.get_ratings_bulk.assert_called_once_with(["20494"])
        mock_client.close.assert_called_once()
        assert result == {"20494": {"FLAM": "A"}}

    @patch("mira.miul.maptis_ratings.MAPTISRatingsClient")
    def test_closes_client_on_exception(self, mock_client_class):
        """Client should be closed even if query raises exception."""
        mock_client = MagicMock()
        mock_client.get_ratings.side_effect = Exception("DB error")
        mock_client_class.return_value = mock_client

        with pytest.raises(Exception):
            get_ratings("20494")

        mock_client.close.assert_called_once()


class TestRatingAggregation:
    """Tests for rating aggregation logic."""

    @patch("psycopg2.connect")
    def test_aggregates_worst_case_rating(self, mock_connect):
        """Multiple results for same rating should aggregate to worst case."""
        mock_cursor = MagicMock()
        # Simulate multiple flammability test results
        mock_cursor.fetchall.side_effect = [
            [{"rating": "A"}, {"rating": "B"}, {"rating": "A"}],  # flammability
            [],  # promoted_combustion
            [],  # scc
            [],  # corrosion
            [],  # tvs
            [],  # toxicity
            [],  # fluid_compat
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        client = MAPTISRatingsClient()
        result = client.get_ratings("20494")

        # Should aggregate to worst rating (B)
        assert result.get("FLAM") == "B"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
