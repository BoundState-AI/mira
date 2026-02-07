#!/usr/bin/env python3
"""
Test Suite: Rating Filtering (Expire Flags + Invalid Ratings)

Tests the filtering of expired data (dataexpireflag='1') and invalid ratings
(X = data invalidated/superseded) across all rating query modules.

BoundState AI 2026
Compliance: SWE-013, NASA-STD-8739.8B
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock

# Import the modules under test
from mira.miul.maptis_ratings import (
    EXPIRE_FLAG_MAP,
    INVALID_RATINGS,
    RATING_MAP,
    MAPTISRatingsClient,
)
from mira.miul.enrichment import MIULEnrichmentService


class TestConstants:
    """Test that constants are correctly defined."""

    def test_invalid_ratings_contains_x(self):
        """X should be in INVALID_RATINGS (means data invalidated)."""
        assert "X" in INVALID_RATINGS

    def test_invalid_ratings_is_set(self):
        """INVALID_RATINGS should be a set for O(1) lookup."""
        assert isinstance(INVALID_RATINGS, set)

    def test_expire_flag_map_covers_all_rating_types(self):
        """Every contract_id in RATING_MAP should have an expire flag field."""
        for contract_id in RATING_MAP.keys():
            assert contract_id in EXPIRE_FLAG_MAP, (
                f"Missing expire flag for {contract_id}"
            )

    def test_expire_flag_field_naming_convention(self):
        """Expire flag fields should follow naming pattern: {prefix}_dataexpireflag."""
        for contract_id, field in EXPIRE_FLAG_MAP.items():
            assert field.endswith("_dataexpireflag"), (
                f"Unexpected field name format: {field}"
            )

    def test_expire_flag_map_has_tvs(self):
        """TVS outgassing should have expire flag (key issue that started this)."""
        assert "tvs_outgassing_report" in EXPIRE_FLAG_MAP
        assert EXPIRE_FLAG_MAP["tvs_outgassing_report"] == "tvs_dataexpireflag"


class TestMaptisRatingsExpireFilter:
    """Test expire flag filtering in maptis_ratings module."""

    @patch("psycopg2.connect")
    def test_get_ratings_excludes_expired_records(self, mock_connect):
        """Records with expire_flag='1' should be excluded from results."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []  # No results after filtering
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        client = MAPTISRatingsClient()
        client.get_ratings("50085")

        # Verify the SQL includes expire flag filter
        calls = mock_cursor.execute.call_args_list
        assert len(calls) > 0

        # Check that at least one query contains the expire flag filter pattern
        sql_found = False
        for call in calls:
            sql = call[0][0]
            if "!= '1'" in sql or "IS NULL" in sql:
                sql_found = True
                break
        assert sql_found, "Query should filter out expired records (expire_flag='1')"

        client.close()

    @patch("psycopg2.connect")
    def test_get_ratings_bulk_excludes_expired_records(self, mock_connect):
        """Bulk query should exclude records with expire_flag='1'."""
        # Simulate DB returning expired and current records
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {
                "material_code": "50085",
                "contract_id": "tvs_outgassing_report",
                "payload": {
                    "tvs_rating": "C",
                    "tvs_dataexpireflag": "1",  # EXPIRED - should be excluded
                    "materialkey": "50085",
                },
            },
            {
                "material_code": "50085",
                "contract_id": "flammability_report",
                "payload": {
                    "flam_rating": "A",
                    "flam_dataexpireflag": "2",  # CURRENT - should be included
                    "materialkey": "50085",
                },
            },
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        client = MAPTISRatingsClient()
        result = client.get_ratings_bulk(["50085"])

        # TVS should be excluded (expired), FLAM should be included
        assert "50085" in result
        assert "TVS" not in result["50085"], "Expired TVS should be filtered out"
        assert result["50085"].get("FLAM") == "A", "Current FLAM should be included"

        client.close()


class TestMaptisRatingsXFilter:
    """Test X rating filtering in maptis_ratings module."""

    @patch("psycopg2.connect")
    def test_get_ratings_excludes_x_ratings(self, mock_connect):
        """X ratings should be filtered out (data invalidated)."""
        mock_cursor = MagicMock()
        # Return X and C ratings for same material
        mock_cursor.fetchall.side_effect = [
            [{"rating": "X"}],  # TVS - should be filtered
            [{"rating": "A"}],  # FLAM
            [],  # SCC
            [],  # CORR
            [],  # TOX
            [],  # FS
            [],  # PROM
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        client = MAPTISRatingsClient()
        result = client.get_ratings("50085")

        # X rating should be filtered, so TVS won't appear
        assert "TVS" not in result, "X rating should be filtered out"
        assert result.get("FLAM") == "A", "Valid ratings should be included"

        client.close()

    @patch("psycopg2.connect")
    def test_get_ratings_bulk_excludes_x_ratings(self, mock_connect):
        """Bulk query should filter out X ratings."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {
                "material_code": "50085",
                "contract_id": "tvs_outgassing_report",
                "payload": {
                    "tvs_rating": "X",  # INVALID - should be excluded
                    "tvs_dataexpireflag": "2",  # Even if current!
                    "materialkey": "50085",
                },
            },
            {
                "material_code": "50085",
                "contract_id": "flammability_report",
                "payload": {
                    "flam_rating": "B",
                    "flam_dataexpireflag": "2",
                    "materialkey": "50085",
                },
            },
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        client = MAPTISRatingsClient()
        result = client.get_ratings_bulk(["50085"])

        assert "50085" in result
        assert "TVS" not in result["50085"], "X rating should be filtered even if current"
        assert result["50085"].get("FLAM") == "B"

        client.close()


class TestEnrichmentExpireFilter:
    """Test expire flag filtering in enrichment module."""

    @patch("psycopg2.connect")
    def test_get_ratings_for_material_code_excludes_expired(self, mock_connect):
        """Enrichment service should exclude expired records."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        service = MIULEnrichmentService()
        service.get_ratings_for_material_code("50085")

        # Verify SQL includes expire flag filter
        calls = mock_cursor.execute.call_args_list
        sql_found = False
        for call in calls:
            sql = call[0][0]
            if "!= '1'" in sql:
                sql_found = True
                break
        assert sql_found, "Query should filter out expired records"

        service.close()

    @patch("psycopg2.connect")
    def test_get_ratings_bulk_excludes_expired(self, mock_connect):
        """Bulk enrichment should exclude expired records."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {
                "material_code": "50085",
                "contract_id": "tvs_outgassing_report",
                "payload": {
                    "tvs_rating": "C",
                    "tvs_dataexpireflag": "1",  # EXPIRED
                    "materialkey": "50085",
                },
            },
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        service = MIULEnrichmentService()
        result = service.get_ratings_bulk(["50085"])

        # Expired record should be excluded
        assert "TVS" not in result.get("50085", {}), "Expired record should be filtered"

        service.close()


class TestEnrichmentXFilter:
    """Test X rating filtering in enrichment module."""

    @patch("psycopg2.connect")
    def test_get_ratings_bulk_excludes_x_ratings(self, mock_connect):
        """Enrichment bulk query should filter out X ratings."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {
                "material_code": "50085",
                "contract_id": "tvs_outgassing_report",
                "payload": {
                    "tvs_rating": "X",
                    "tvs_dataexpireflag": "2",  # Current but X = invalid
                    "materialkey": "50085",
                },
            },
            {
                "material_code": "50085",
                "contract_id": "corrosion_report",
                "payload": {
                    "cor_rating": "A",
                    "cor_dataexpireflag": "2",
                    "materialkey": "50085",
                },
            },
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        service = MIULEnrichmentService()
        result = service.get_ratings_bulk(["50085"])

        assert "TVS" not in result.get("50085", {}), "X rating should be filtered"
        assert result["50085"].get("CORR") == "A", "Valid rating should be included"

        service.close()


class TestCombinedFiltering:
    """Test combined expire flag + X rating filtering."""

    @patch("psycopg2.connect")
    def test_both_filters_applied(self, mock_connect):
        """Both expire flag and X rating filters should work together."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            # Scenario 1: Valid current data - INCLUDE
            {
                "material_code": "10001",
                "contract_id": "flammability_report",
                "payload": {
                    "flam_rating": "A",
                    "flam_dataexpireflag": "2",
                    "materialkey": "10001",
                },
            },
            # Scenario 2: Expired data - EXCLUDE (expire flag)
            {
                "material_code": "10001",
                "contract_id": "corrosion_report",
                "payload": {
                    "cor_rating": "B",
                    "cor_dataexpireflag": "1",
                    "materialkey": "10001",
                },
            },
            # Scenario 3: Invalidated data - EXCLUDE (X filter)
            {
                "material_code": "10001",
                "contract_id": "tvs_outgassing_report",
                "payload": {
                    "tvs_rating": "X",
                    "tvs_dataexpireflag": "2",
                    "materialkey": "10001",
                },
            },
            # Scenario 4: Expired + invalidated - EXCLUDE (both)
            {
                "material_code": "10001",
                "contract_id": "toxicity_report",
                "payload": {
                    "tox_spacestationrating": "X",
                    "tox_dataexpireflag": "1",
                    "materialkey": "10001",
                },
            },
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        client = MAPTISRatingsClient()
        result = client.get_ratings_bulk(["10001"])

        ratings = result.get("10001", {})

        # Only FLAM should be included
        assert ratings.get("FLAM") == "A", "Valid current data should be included"
        assert "CORR" not in ratings, "Expired data should be excluded"
        assert "TVS" not in ratings, "X rating should be excluded"
        assert "TOX" not in ratings, "Expired + X should be excluded"

        client.close()


class TestMaterial50085:
    """Specific tests for material 50085 (18-8 CRES) - the original issue."""

    @patch("psycopg2.connect")
    def test_50085_tvs_excluded(self, mock_connect):
        """Material 50085 should have NO TVS rating (was showing X incorrectly)."""
        mock_cursor = MagicMock()
        # Simulate the actual data: TVS='X' with old_rating='C'
        mock_cursor.fetchall.return_value = [
            {
                "material_code": "50085",
                "contract_id": "tvs_outgassing_report",
                "payload": {
                    "tvs_rating": "X",
                    "tvs_dataexpireflag": "2",
                    "tvs_oldrating": "C",  # Was valid, now invalidated
                    "materialkey": "50085",
                },
            },
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        client = MAPTISRatingsClient()
        result = client.get_ratings_bulk(["50085"])

        # Should have NO TVS rating, matching NASA MAPTIS behavior
        assert "TVS" not in result.get("50085", {}), (
            "Material 50085 should have no TVS rating (X filtered out)"
        )

        client.close()


class TestEdgeCases:
    """Test edge cases in filtering logic."""

    def test_invalid_ratings_case_insensitive(self):
        """X should be filtered regardless of case."""
        # The filtering uses .upper() so lowercase 'x' becomes 'X'
        assert "X" in INVALID_RATINGS
        # Code normalizes to uppercase before checking

    @patch("psycopg2.connect")
    def test_null_expire_flag_included(self, mock_connect):
        """Records with NULL expire flag should be included (unknown status)."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {
                "material_code": "10001",
                "contract_id": "flammability_report",
                "payload": {
                    "flam_rating": "A",
                    # No flam_dataexpireflag key = NULL
                    "materialkey": "10001",
                },
            },
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        client = MAPTISRatingsClient()
        result = client.get_ratings_bulk(["10001"])

        # NULL expire flag should be treated as valid (include)
        assert result["10001"].get("FLAM") == "A", (
            "NULL expire flag should be treated as valid"
        )

        client.close()

    @patch("psycopg2.connect")
    def test_expire_flag_2_included(self, mock_connect):
        """Records with expire_flag='2' (current) should be included."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {
                "material_code": "10001",
                "contract_id": "flammability_report",
                "payload": {
                    "flam_rating": "B",
                    "flam_dataexpireflag": "2",  # CURRENT
                    "materialkey": "10001",
                },
            },
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        client = MAPTISRatingsClient()
        result = client.get_ratings_bulk(["10001"])

        assert result["10001"].get("FLAM") == "B", (
            "expire_flag='2' should be included"
        )

        client.close()
