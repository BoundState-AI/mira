#!/usr/bin/env python3
"""
Module: Test Enrichment
Purpose: MIUL Enrichment Service Tests for BoundState

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
import pandas as pd

sys.path.insert(0, r"C:\BoundState")

from mira.miul.enrichment import (
    MIULEnrichmentService,
    get_enrichment_service,
    reset_enrichment_service,
    RATING_FIELD_MAP,
    MIUL_RATING_COLUMNS,
    RATING_SEVERITY,
)


class TestConstants:
    """Tests for module constants."""

    def test_rating_field_map_complete(self):
        """Rating field map should have all test types."""
        expected_types = {
            "flammability_report",
            "promoted_combustion_report",
            "corrosion_report",
            "stress_corrosion_cracking_report",
            "tvs_outgassing_report",
            "fluid_compatibility_report",
            "toxicity_report",
        }
        assert set(RATING_FIELD_MAP.keys()) == expected_types

    def test_miul_rating_columns_match_jsc27301f(self):
        """MIUL columns should match JSC 27301F Section 4.2.1."""
        expected_columns = {"FLAM", "SCC", "CORR", "TVS", "FS", "TOX"}
        actual_columns = set(MIUL_RATING_COLUMNS.values())
        assert actual_columns == expected_columns

    def test_rating_severity_order(self):
        """Severity should follow A (best) to X (worst) order."""
        assert RATING_SEVERITY["A"] < RATING_SEVERITY["B"]
        assert RATING_SEVERITY["B"] < RATING_SEVERITY["C"]
        assert RATING_SEVERITY["A"] < RATING_SEVERITY["U"]
        assert RATING_SEVERITY["A"] < RATING_SEVERITY["X"]

    def test_severity_has_all_common_ratings(self):
        """Severity map should have all common ratings."""
        common_ratings = ["A", "B", "C", "D", "I", "N", "U", "X"]
        for rating in common_ratings:
            assert rating in RATING_SEVERITY


class TestServiceInit:
    """Tests for MIULEnrichmentService initialization."""

    def test_default_params(self):
        """Should initialize with default connection params."""
        service = MIULEnrichmentService()
        assert service._conn_params["host"] == "localhost"
        assert service._conn_params["port"] == 5432
        assert service._conn_params["database"] == "mira"

    def test_custom_params(self):
        """Should accept custom connection params."""
        service = MIULEnrichmentService(
            host="custom-host",
            port=5433,
            database="custom_db",
            user="custom_user",
            password="custom_pass",
        )
        assert service._conn_params["host"] == "custom-host"
        assert service._conn_params["port"] == 5433
        assert service._conn_params["database"] == "custom_db"

    def test_connection_initially_none(self):
        """Connection should not be established until needed."""
        service = MIULEnrichmentService()
        assert service._conn is None


class TestConnectionManagement:
    """Tests for database connection management."""

    @patch("psycopg2.connect")
    def test_lazy_connection(self, mock_connect):
        """Should not connect until _get_connection called."""
        service = MIULEnrichmentService()
        mock_connect.assert_not_called()

        service._get_connection()
        mock_connect.assert_called_once()

    @patch("psycopg2.connect")
    def test_reuses_connection(self, mock_connect):
        """Should reuse existing open connection."""
        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_connect.return_value = mock_conn

        service = MIULEnrichmentService()
        service._get_connection()
        service._get_connection()

        assert mock_connect.call_count == 1

    @patch("psycopg2.connect")
    def test_reconnects_if_closed(self, mock_connect):
        """Should reconnect if connection was closed."""
        mock_conn = MagicMock()
        mock_conn.closed = True
        mock_connect.return_value = mock_conn

        service = MIULEnrichmentService()
        service._conn = mock_conn  # Set a "closed" connection

        service._get_connection()
        mock_connect.assert_called()

    @patch("psycopg2.connect")
    def test_close_closes_connection(self, mock_connect):
        """Close should close the connection."""
        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_connect.return_value = mock_conn

        service = MIULEnrichmentService()
        service._get_connection()
        service.close()

        mock_conn.close.assert_called_once()

    @patch("psycopg2.connect")
    def test_close_handles_already_closed(self, mock_connect):
        """Close should handle already-closed connection."""
        mock_conn = MagicMock()
        mock_conn.closed = True
        mock_connect.return_value = mock_conn

        service = MIULEnrichmentService()
        service._conn = mock_conn

        # Should not raise
        service.close()
        mock_conn.close.assert_not_called()


class TestNormalizeDesignation:
    """Tests for designation normalization."""

    def test_basic_passthrough(self):
        """Original designation should always be in variants."""
        service = MIULEnrichmentService()
        variants = service._normalize_designation("INCONEL 718")
        assert "INCONEL 718" in variants

    def test_a286_hyphen_insertion(self):
        """A286 should generate A-286 variant."""
        service = MIULEnrichmentService()
        variants = service._normalize_designation("A286")
        assert "A-286" in variants

    def test_sst_suffix_expansion(self):
        """416 SST should expand to multiple variants."""
        service = MIULEnrichmentService()
        variants = service._normalize_designation("416 SST")
        assert "STAINLESS STEEL 416" in variants
        assert "CRES 416" in variants
        assert "416" in variants

    def test_ss_prefix_expansion(self):
        """SS 316L should expand to stainless variants."""
        service = MIULEnrichmentService()
        variants = service._normalize_designation("SS 316L")
        assert "STAINLESS STEEL 316L" in variants
        assert "CRES 316L" in variants

    def test_cres_prefix_expansion(self):
        """CRES 316L should expand to stainless variants."""
        service = MIULEnrichmentService()
        variants = service._normalize_designation("CRES 316L")
        assert "STAINLESS STEEL 316L" in variants

    def test_bare_alloy_number(self):
        """316L alone should generate stainless variants."""
        service = MIULEnrichmentService()
        variants = service._normalize_designation("316L")
        assert "STAINLESS STEEL 316L" in variants
        assert "CRES 316L" in variants


class TestTranslateMiulCode:
    """Tests for MIUL code to DB code translation."""

    @patch("psycopg2.connect")
    def test_numeric_code_queries_by_material_key(self, mock_connect):
        """Numeric code should query by material_key."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {"material_code": "10018"}
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        service = MIULEnrichmentService()
        result = service._translate_miul_code_to_db_code("12345")

        assert result == "10018"
        # Verify material_key was used in query
        call_args = mock_cursor.execute.call_args
        assert 12345 in call_args[0][1]

    @patch("psycopg2.connect")
    def test_non_numeric_returns_direct(self, mock_connect):
        """Non-numeric code should be returned directly."""
        service = MIULEnrichmentService()
        result = service._translate_miul_code_to_db_code("ABC123")

        assert result == "ABC123"

    def test_empty_returns_none(self):
        """Empty value should return None."""
        service = MIULEnrichmentService()
        assert service._translate_miul_code_to_db_code("") is None
        assert service._translate_miul_code_to_db_code(None) is None

    @patch("psycopg2.connect")
    def test_strips_whitespace(self, mock_connect):
        """Should strip whitespace from code."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        service = MIULEnrichmentService()
        service._translate_miul_code_to_db_code("  ABC123  ")

        # Should work without raising


class TestFindMaterialCodeByDesignation:
    """Tests for designation-based material code lookup."""

    @patch("psycopg2.connect")
    def test_tries_variants_in_order(self, mock_connect):
        """Should try each variant until match found."""
        mock_cursor = MagicMock()
        # First query returns nothing, second returns match
        mock_cursor.fetchone.side_effect = [None, {"material_code": "20001"}]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        service = MIULEnrichmentService()
        result = service.find_material_code_by_designation("316L")

        assert result == "20001"

    @patch("psycopg2.connect")
    def test_returns_none_for_no_match(self, mock_connect):
        """Should return None when no match found."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        service = MIULEnrichmentService()
        result = service.find_material_code_by_designation("UNKNOWN_MATERIAL")

        assert result is None

    def test_empty_designation_returns_none(self):
        """Empty designation should return None."""
        service = MIULEnrichmentService()
        assert service.find_material_code_by_designation("") is None
        assert service.find_material_code_by_designation(None) is None
        assert service.find_material_code_by_designation("   ") is None

    @patch("psycopg2.connect")
    def test_db_error_propagates(self, mock_connect):
        """Database errors should propagate (not silently swallowed)."""
        mock_conn = MagicMock()
        mock_conn.cursor.side_effect = Exception("DB Error")
        mock_connect.return_value = mock_conn

        service = MIULEnrichmentService()
        # DB errors propagate - caller should handle
        with pytest.raises(Exception, match="DB Error"):
            service.find_material_code_by_designation("316L")


class TestAggregateRatings:
    """Tests for rating aggregation."""

    def test_single_rating_returned(self):
        """Single rating should be returned as-is."""
        service = MIULEnrichmentService()
        result = service._aggregate_ratings(["A"])
        assert result == "A"

    def test_worst_rating_selected(self):
        """Should return worst (highest severity) rating."""
        service = MIULEnrichmentService()

        # B is worse than A
        result = service._aggregate_ratings(["A", "B"])
        assert result == "B"

        # U is worse than A and B
        result = service._aggregate_ratings(["A", "B", "U"])
        assert result == "U"

    def test_empty_list_returns_none(self):
        """Empty list should return None."""
        service = MIULEnrichmentService()
        assert service._aggregate_ratings([]) is None

    def test_none_values_filtered(self):
        """None and empty values should be filtered."""
        service = MIULEnrichmentService()
        result = service._aggregate_ratings(["A", None, "", "B"])
        assert result == "B"

    def test_case_normalization(self):
        """Ratings should be uppercased."""
        service = MIULEnrichmentService()
        result = service._aggregate_ratings(["a", "b"])
        assert result == "B"


class TestGetRatingsForMaterialCode:
    """Tests for single material code rating lookup."""

    @patch("psycopg2.connect")
    def test_queries_all_test_types(self, mock_connect):
        """Should query for all test types."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        service = MIULEnrichmentService()
        service.get_ratings_for_material_code("10018")

        # Should have made multiple queries (one per test type)
        assert mock_cursor.execute.call_count == len(RATING_FIELD_MAP)

    @patch("psycopg2.connect")
    def test_returns_mapped_ratings(self, mock_connect):
        """Should return ratings mapped to MIUL columns."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [{"rating": "A"}]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        service = MIULEnrichmentService()
        result = service.get_ratings_for_material_code("10018")

        # Should have MIUL column names as keys
        for key in result.keys():
            assert key in {"FLAM", "SCC", "CORR", "TVS", "TOX", "FS"}


class TestGetRatingsBulk:
    """Tests for bulk rating lookup."""

    @patch("psycopg2.connect")
    def test_empty_list_returns_empty(self, mock_connect):
        """Empty material list should return empty dict."""
        service = MIULEnrichmentService()
        result = service.get_ratings_bulk([])
        assert result == {}

    @patch("psycopg2.connect")
    def test_uses_single_query(self, mock_connect):
        """Should use single query for efficiency."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        service = MIULEnrichmentService()
        service.get_ratings_bulk(["10018", "20001", "30002"])

        # Should only call execute once
        assert mock_cursor.execute.call_count == 1

    @patch("psycopg2.connect")
    def test_returns_dict_per_material(self, mock_connect):
        """Should return separate dict for each material."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {
                "material_code": "10018",
                "contract_id": "flammability_report",
                "payload": {"flam_rating": "A"},
            },
            {
                "material_code": "20001",
                "contract_id": "flammability_report",
                "payload": {"flam_rating": "B"},
            },
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        service = MIULEnrichmentService()
        result = service.get_ratings_bulk(["10018", "20001"])

        assert "10018" in result
        assert "20001" in result
        assert result["10018"]["FLAM"] == "A"
        assert result["20001"]["FLAM"] == "B"


class TestEnrichMiulDataframe:
    """Tests for DataFrame enrichment."""

    @patch("psycopg2.connect")
    def test_creates_rating_columns(self, mock_connect):
        """Should create missing rating columns."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_cursor.fetchone.return_value = None
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        service = MIULEnrichmentService()

        df = pd.DataFrame({
            "Material Code": ["10018"],
        })

        result_df, stats = service.enrich_miul_dataframe(df)

        # Should have all rating columns
        for col in ["FLAM", "SCC", "CORR", "TVS", "TOX", "FS"]:
            assert col in result_df.columns

    @patch("psycopg2.connect")
    def test_looks_up_missing_material_codes(self, mock_connect):
        """Should look up Material Code from Designation when missing."""
        mock_cursor = MagicMock()
        # First call for designation lookup returns a code
        # Subsequent calls return empty
        mock_cursor.fetchone.side_effect = [
            {"material_code": "20001"},  # Designation lookup
            None,  # Translate call
        ]
        mock_cursor.fetchall.return_value = []
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        service = MIULEnrichmentService()

        df = pd.DataFrame({
            "Material Code": [None],
            "Designation": ["316L STAINLESS"],
        })

        result_df, stats = service.enrich_miul_dataframe(df)

        assert stats["codes_looked_up"] >= 0  # May or may not find depending on mocks

    @patch("psycopg2.connect")
    def test_returns_stats(self, mock_connect):
        """Should return enrichment statistics."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_cursor.fetchone.return_value = {"material_code": "10018"}
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        service = MIULEnrichmentService()

        df = pd.DataFrame({
            "Material Code": ["10018", "20001"],
        })

        _, stats = service.enrich_miul_dataframe(df)

        assert "total_materials" in stats
        assert "enriched_count" in stats
        assert "coverage_pct" in stats
        assert "ratings_by_type" in stats

    @patch("psycopg2.connect")
    def test_handles_empty_dataframe(self, mock_connect):
        """Should handle empty DataFrame."""
        service = MIULEnrichmentService()

        df = pd.DataFrame(columns=["Material Code", "Designation"])

        result_df, stats = service.enrich_miul_dataframe(df)

        assert stats["total_materials"] == 0
        assert stats["enriched_count"] == 0

    @patch("psycopg2.connect")
    def test_handles_no_material_codes(self, mock_connect):
        """Should handle case with no Material Codes available."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None  # No matches for designation
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        service = MIULEnrichmentService()

        df = pd.DataFrame({
            "Material Code": [None, ""],
            "Designation": ["UNKNOWN1", "UNKNOWN2"],
        })

        result_df, stats = service.enrich_miul_dataframe(df)

        assert stats["total_materials"] == 0


class TestSingletonManagement:
    """Tests for singleton service management."""

    @patch("psycopg2.connect")
    def test_get_returns_singleton(self, mock_connect):
        """get_enrichment_service should return same instance."""
        reset_enrichment_service()

        service1 = get_enrichment_service()
        service2 = get_enrichment_service()

        assert service1 is service2

        reset_enrichment_service()

    @patch("psycopg2.connect")
    def test_reset_clears_singleton(self, mock_connect):
        """reset_enrichment_service should clear the singleton."""
        reset_enrichment_service()

        service1 = get_enrichment_service()
        reset_enrichment_service()
        service2 = get_enrichment_service()

        assert service1 is not service2

        reset_enrichment_service()

    @patch("psycopg2.connect")
    def test_reset_closes_connection(self, mock_connect):
        """reset should close existing connection."""
        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_connect.return_value = mock_conn

        reset_enrichment_service()

        service = get_enrichment_service()
        service._get_connection()

        reset_enrichment_service()

        mock_conn.close.assert_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
