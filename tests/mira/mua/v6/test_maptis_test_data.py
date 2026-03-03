#!/usr/bin/env python3
"""
Module: Test Maptis Test Data
Purpose: Tests for MAPTIS Test Data Query (MUA v6).

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
import asyncio
import sys
from unittest.mock import MagicMock, patch, AsyncMock

sys.path.insert(0, r"C:\BoundState")

from mira.mua.v6.maptis_test_data import (
    TestDataCurrency,
    TestEnvelope,
    FlammabilityTestResult,
    TestDataStatus,
    query_maptis_test_data,
    query_maptis_test_data_bulk,
    _get_best_rating,
    _parse_float,
)


class TestTestDataCurrency:
    """Tests for TestDataCurrency enum."""

    def test_currency_values(self):
        """Currency enum should have expected values."""
        assert TestDataCurrency.CURRENT.value == "current"
        assert TestDataCurrency.EXPIRED.value == "expired"
        assert TestDataCurrency.UNKNOWN.value == "unknown"
        assert TestDataCurrency.NOT_FOUND.value == "not_found"

    def test_all_values_are_strings(self):
        """All currency values should be strings."""
        for currency in TestDataCurrency:
            assert isinstance(currency.value, str)


class TestTestEnvelope:
    """Tests for TestEnvelope model."""

    def test_empty_envelope(self):
        """Empty envelope should have all None values."""
        envelope = TestEnvelope()
        assert envelope.pressure_psia is None
        assert envelope.moc_o2_pct is None
        assert envelope.temperature_f is None
        assert envelope.sample_temperature_f is None

    def test_populated_envelope(self):
        """Populated envelope should store values correctly."""
        envelope = TestEnvelope(
            pressure_psia=14.7,
            moc_o2_pct=25.0,
            temperature_f=70.0,
            sample_temperature_f=72.0,
        )
        assert envelope.pressure_psia == 14.7
        assert envelope.moc_o2_pct == 25.0
        assert envelope.temperature_f == 70.0
        assert envelope.sample_temperature_f == 72.0

    def test_partial_envelope(self):
        """Envelope can have some values set, others None."""
        envelope = TestEnvelope(
            pressure_psia=14.7,
            moc_o2_pct=None,
        )
        assert envelope.pressure_psia == 14.7
        assert envelope.moc_o2_pct is None


class TestFlammabilityTestResult:
    """Tests for FlammabilityTestResult model."""

    def test_basic_result(self):
        """Should create valid test result."""
        result = FlammabilityTestResult(
            material_code="20494",
            rating="A",
            envelope=TestEnvelope(pressure_psia=14.7),
            currency=TestDataCurrency.CURRENT,
        )
        assert result.material_code == "20494"
        assert result.rating == "A"
        assert result.currency == TestDataCurrency.CURRENT

    def test_default_source(self):
        """Default source should be set for traceability."""
        result = FlammabilityTestResult(
            material_code="20494",
            rating="B",
            envelope=TestEnvelope(),
            currency=TestDataCurrency.EXPIRED,
        )
        assert "silver_report_rows" in result.source
        assert "flammability_report" in result.source


class TestTestDataStatus:
    """Tests for TestDataStatus model."""

    def test_no_data_status(self):
        """Status with no data should have correct defaults."""
        status = TestDataStatus(material_code="12345")
        assert status.material_code == "12345"
        assert not status.has_current_data
        assert not status.has_expired_data
        assert status.current_rating is None
        assert status.expired_rating is None
        assert len(status.current_results) == 0
        assert len(status.expired_results) == 0

    def test_current_data_status(self):
        """Status with current data should reflect it."""
        status = TestDataStatus(
            material_code="12345",
            has_current_data=True,
            has_expired_data=True,
            current_rating="A",
            expired_rating="B",
            current_results=[
                FlammabilityTestResult(
                    material_code="12345",
                    rating="A",
                    envelope=TestEnvelope(),
                    currency=TestDataCurrency.CURRENT,
                )
            ],
        )
        assert status.has_current_data
        assert status.current_rating == "A"
        assert len(status.current_results) == 1

    def test_total_records(self):
        """Total records should be tracked."""
        status = TestDataStatus(
            material_code="12345",
            total_records=15,
        )
        assert status.total_records == 15


class TestGetBestRating:
    """Tests for _get_best_rating helper."""

    def test_empty_list_returns_none(self):
        """Empty list should return None."""
        assert _get_best_rating([]) is None

    def test_single_rating(self):
        """Single rating should be returned."""
        assert _get_best_rating(["A"]) == "A"
        assert _get_best_rating(["B"]) == "B"

    def test_best_rating_selected(self):
        """Best (lowest severity) rating should be selected."""
        assert _get_best_rating(["A", "B", "C"]) == "A"
        assert _get_best_rating(["C", "B", "A"]) == "A"
        assert _get_best_rating(["X", "B"]) == "B"

    def test_rating_priority(self):
        """Rating priority should be A > B > C > D > I > K > N > U > X."""
        assert _get_best_rating(["B", "A"]) == "A"
        assert _get_best_rating(["C", "B"]) == "B"
        assert _get_best_rating(["X", "U"]) == "U"
        assert _get_best_rating(["N", "K"]) == "K"

    def test_unknown_ratings_handled(self):
        """Unknown ratings should be handled gracefully."""
        # If all unknown, return first
        assert _get_best_rating(["Z", "Y"]) == "Z"
        # If mix, return best known
        assert _get_best_rating(["Z", "A"]) == "A"

    def test_whitespace_handled(self):
        """Whitespace should be trimmed."""
        assert _get_best_rating([" A ", "B"]) == "A"


class TestParseFloat:
    """Tests for _parse_float helper."""

    def test_none_returns_none(self):
        """None should return None."""
        assert _parse_float(None) is None

    def test_valid_float(self):
        """Valid float string should parse."""
        assert _parse_float("14.7") == 14.7
        assert _parse_float("0.0") == 0.0
        assert _parse_float("-10.5") == -10.5

    def test_integer_string(self):
        """Integer string should parse to float."""
        assert _parse_float("100") == 100.0

    def test_invalid_returns_none(self):
        """Invalid values should return None."""
        assert _parse_float("not a number") is None
        assert _parse_float("") is None
        assert _parse_float("N/A") is None


@pytest.mark.asyncio
class TestQueryMaptisTestData:
    """Tests for async query function."""

    @patch("mira.mua.v6.maptis_test_data._sync_query_maptis_test_data")
    async def test_query_returns_status(self, mock_sync_query):
        """Query should return TestDataStatus."""
        mock_sync_query.return_value = TestDataStatus(
            material_code="20494",
            has_current_data=True,
            has_expired_data=False,
            current_rating="A",
        )

        result = await query_maptis_test_data("20494")

        assert isinstance(result, TestDataStatus)
        assert result.material_code == "20494"
        assert result.has_current_data
        mock_sync_query.assert_called_once()

    @patch("psycopg2.connect")
    async def test_flag_2_is_current(self, mock_connect):
        """Flag='2' should be classified as CURRENT."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {
                "material_code": "20494",
                "rating": "A",
                "expire_flag": "2",  # CURRENT
                "pressure": "14.7",
                "moc_o2_pct": "25.0",
                "temperature": "70.0",
                "sample_temp": None,
                "report_id": "123",
            }
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        result = await query_maptis_test_data("20494")

        assert result.has_current_data
        assert len(result.current_results) == 1
        assert result.current_results[0].currency == TestDataCurrency.CURRENT
        assert result.current_rating == "A"

    @patch("psycopg2.connect")
    async def test_flag_1_is_expired(self, mock_connect):
        """Flag='1' should be classified as EXPIRED."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {
                "material_code": "20494",
                "rating": "B",
                "expire_flag": "1",  # EXPIRED
                "pressure": None,
                "moc_o2_pct": None,
                "temperature": None,
                "sample_temp": None,
                "report_id": "456",
            }
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        result = await query_maptis_test_data("20494", include_expired=True)

        assert not result.has_current_data
        assert result.has_expired_data
        assert len(result.expired_results) == 1
        assert result.expired_results[0].currency == TestDataCurrency.EXPIRED

    @patch("psycopg2.connect")
    async def test_null_flag_is_unknown(self, mock_connect):
        """NULL flag should be classified as UNKNOWN."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {
                "material_code": "20494",
                "rating": "C",
                "expire_flag": None,  # UNKNOWN
                "pressure": "10.0",
                "moc_o2_pct": "21.0",
                "temperature": "75.0",
                "sample_temp": None,
                "report_id": "789",
            }
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        result = await query_maptis_test_data("20494")

        # UNKNOWN goes to neither current nor expired
        assert not result.has_current_data
        # has_expired_data checks actual flag='1' rows
        assert result.total_records == 1

    @patch("psycopg2.connect")
    async def test_envelope_calculation(self, mock_connect):
        """Envelope should calculate most restrictive from current data."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {
                "material_code": "20494",
                "rating": "A",
                "expire_flag": "2",
                "pressure": "20.0",
                "moc_o2_pct": "30.0",
                "temperature": "100.0",
                "sample_temp": None,
                "report_id": "1",
            },
            {
                "material_code": "20494",
                "rating": "A",
                "expire_flag": "2",
                "pressure": "14.7",  # Lower = more restrictive
                "moc_o2_pct": "25.0",  # Lower = more restrictive
                "temperature": "70.0",  # Lower = more restrictive
                "sample_temp": None,
                "report_id": "2",
            },
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        result = await query_maptis_test_data("20494")

        assert result.envelope is not None
        assert result.envelope.pressure_psia == 14.7  # Min of 20.0 and 14.7
        assert result.envelope.moc_o2_pct == 25.0  # Min of 30.0 and 25.0
        assert result.envelope.temperature_f == 70.0  # Min of 100.0 and 70.0

    @patch("psycopg2.connect")
    async def test_no_records_found(self, mock_connect):
        """No records should return empty status."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        result = await query_maptis_test_data("99999")

        assert not result.has_current_data
        assert not result.has_expired_data
        assert result.total_records == 0


@pytest.mark.asyncio
class TestQueryBulk:
    """Tests for bulk query function."""

    @patch("mira.mua.v6.maptis_test_data.query_maptis_test_data")
    async def test_bulk_returns_dict(self, mock_query):
        """Bulk query should return dict mapping code to status."""
        mock_query.return_value = TestDataStatus(
            material_code="20494",
            has_current_data=True,
            has_expired_data=False,
        )

        result = await query_maptis_test_data_bulk(["20494", "20495"])

        assert isinstance(result, dict)
        assert "20494" in result
        assert "20495" in result

    @patch("mira.mua.v6.maptis_test_data.query_maptis_test_data")
    async def test_empty_list_returns_empty_dict(self, mock_query):
        """Empty list should return empty dict."""
        result = await query_maptis_test_data_bulk([])
        assert result == {}
        mock_query.assert_not_called()

    @patch("mira.mua.v6.maptis_test_data.query_maptis_test_data")
    async def test_deduplication(self, mock_query):
        """Duplicate codes should be deduplicated."""
        mock_query.return_value = TestDataStatus(
            material_code="20494",
            has_current_data=True,
        )

        result = await query_maptis_test_data_bulk(["20494", "20494", "20494"])

        # Should only query once despite 3 duplicates
        assert mock_query.call_count == 1

    @patch("mira.mua.v6.maptis_test_data.query_maptis_test_data")
    async def test_handles_exceptions(self, mock_query):
        """Exceptions should result in default status."""
        # Create an async mock that returns values or raises exceptions
        async def mock_side_effect(code, *args, **kwargs):
            if code == "20494":
                return TestDataStatus(material_code="20494", has_current_data=True)
            else:
                raise Exception("DB Error")

        mock_query.side_effect = mock_side_effect

        result = await query_maptis_test_data_bulk(["20494", "20495"])

        assert "20494" in result
        assert result["20494"].has_current_data
        assert "20495" in result
        assert not result["20495"].has_current_data  # Default on error


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
