#!/usr/bin/env python3
"""
Module: Test Mua V6 Api
Purpose: Tests for MUA v6 API Router.

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
from unittest.mock import MagicMock, patch, AsyncMock

sys.path.insert(0, r"C:\BoundState")

from fastapi.testclient import TestClient

from mira.api.app import app


@pytest.fixture
def client():
    """Create test client for the BoundState API."""
    return TestClient(app)


class TestMuaV6Ping:
    """Tests for /mua/v6/ping endpoint."""

    def test_ping_returns_ok(self, client):
        """Ping endpoint should return ok status."""
        response = client.get("/mua/v6/ping")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["domain"] == "mua-v6"
        assert "version" in data


class TestPrecedentSearch:
    """Tests for /mua/v6/precedents/search endpoint."""

    @patch("mira.api.routers.mua_v6.resolve_material_identity")
    @patch("mira.api.routers.mua_v6.search_enriched_precedents")
    def test_search_returns_structured_response(
        self, mock_search, mock_resolve, client
    ):
        """Basic search returns properly structured response."""
        # Mock material identity
        mock_identity = MagicMock()
        mock_identity.is_resolved = True
        mock_identity.material_code = "20494"
        mock_resolve.return_value = mock_identity

        # Mock search results
        mock_results = MagicMock()
        mock_results.supporting_count = 2
        mock_results.conflicting_count = 0
        mock_results.supporting = []
        mock_results.conflicting = []
        mock_search.return_value = mock_results

        response = client.post(
            "/mua/v6/precedents/search",
            json={"material": "INCONEL 625", "k": 5},
        )

        assert response.status_code == 200
        data = response.json()
        assert "request_id" in data
        assert "supporting_count" in data
        assert "conflicting_count" in data
        assert isinstance(data["supporting_precedents"], list)
        assert isinstance(data["conflicting_precedents"], list)

    @patch("mira.api.routers.mua_v6.resolve_material_identity")
    @patch("mira.api.routers.mua_v6.search_enriched_precedents")
    def test_search_with_environment(self, mock_search, mock_resolve, client):
        """Search with environment filter works."""
        mock_identity = MagicMock()
        mock_identity.is_resolved = True
        mock_identity.material_code = "20494"
        mock_resolve.return_value = mock_identity

        mock_results = MagicMock()
        mock_results.supporting_count = 1
        mock_results.conflicting_count = 0
        mock_results.supporting = []
        mock_results.conflicting = []
        mock_search.return_value = mock_results

        response = client.post(
            "/mua/v6/precedents/search",
            json={
                "material": "304 SS",
                "environment": {
                    "description": "30% O2 enriched atmosphere",
                    "o2_percent": 30.0,
                    "pressure_psia": 14.7,
                },
                "k": 10,
            },
        )

        assert response.status_code == 200

    def test_search_empty_material_rejected(self, client):
        """Empty material string returns 422."""
        response = client.post(
            "/mua/v6/precedents/search",
            json={"material": ""},
        )
        assert response.status_code == 422


class TestGenerate:
    """Tests for /mua/v6/generate endpoint."""

    @patch("mira.api.routers.mua_v6.get_logic_validator")
    @patch("mira.api.routers.mua_v6.query_maptis_test_data")
    @patch("mira.api.routers.mua_v6.resolve_material_identity")
    @patch("mira.api.routers.mua_v6.search_enriched_precedents")
    def test_evaluate_only_mode_returns_decision(
        self, mock_search, mock_resolve, mock_query, mock_validator, client
    ):
        """evaluate_only mode returns decision without draft."""
        # Mock material identity - unresolved
        mock_identity = MagicMock()
        mock_identity.is_resolved = False
        mock_identity.material_code = None
        mock_resolve.return_value = mock_identity

        # Mock search results - no supporting precedents
        mock_results = MagicMock()
        mock_results.supporting_count = 0
        mock_results.conflicting_count = 0
        mock_results.supporting = []
        mock_results.conflicting = []
        mock_search.return_value = mock_results

        # Mock validator as None (no API key)
        mock_validator.return_value = None

        response = client.post(
            "/mua/v6/generate",
            json={
                "material": "INCONEL 625",
                "environment": {
                    "description": "Oxygen service",
                    "o2_percent": 100.0,
                },
                "mode": "evaluate_only",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["draft_text"] is None
        assert "decision" in data
        assert "confidence_score" in data

    @patch("mira.api.routers.mua_v6.get_logic_validator")
    @patch("mira.api.routers.mua_v6.query_maptis_test_data")
    @patch("mira.api.routers.mua_v6.resolve_material_identity")
    @patch("mira.api.routers.mua_v6.search_enriched_precedents")
    def test_blocked_decision_no_precedents(
        self, mock_search, mock_resolve, mock_query, mock_validator, client
    ):
        """No precedents results in blocked decision."""
        mock_identity = MagicMock()
        mock_identity.is_resolved = False
        mock_identity.material_code = None
        mock_resolve.return_value = mock_identity

        mock_results = MagicMock()
        mock_results.supporting_count = 0
        mock_results.conflicting_count = 0
        mock_results.supporting = []
        mock_results.conflicting = []
        mock_search.return_value = mock_results

        mock_validator.return_value = None

        response = client.post(
            "/mua/v6/generate",
            json={
                "material": "UNOBTAINIUM_9999",
                "environment": {"description": "Test"},
                "mode": "auto",
            },
        )

        assert response.status_code == 200
        data = response.json()
        # Should be blocked due to no precedents and unresolved material
        assert data["decision"] in ["blocked", "review"]

    @patch("mira.api.routers.mua_v6.get_logic_validator")
    @patch("mira.api.routers.mua_v6.query_maptis_test_data")
    @patch("mira.api.routers.mua_v6.resolve_material_identity")
    @patch("mira.api.routers.mua_v6.search_enriched_precedents")
    def test_warnings_populated(
        self, mock_search, mock_resolve, mock_query, mock_validator, client
    ):
        """Response includes warnings list."""
        mock_identity = MagicMock()
        mock_identity.is_resolved = False
        mock_identity.material_code = None
        mock_resolve.return_value = mock_identity

        mock_results = MagicMock()
        mock_results.supporting_count = 0
        mock_results.conflicting_count = 0
        mock_results.supporting = []
        mock_results.conflicting = []
        mock_search.return_value = mock_results

        mock_validator.return_value = None

        response = client.post(
            "/mua/v6/generate",
            json={
                "material": "TEST MATERIAL",
                "environment": {"description": "Test env"},
                "mode": "evaluate_only",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "warnings" in data
        assert isinstance(data["warnings"], list)
        # Should have warning about unresolved material
        assert any("could not be resolved" in w for w in data["warnings"])


class TestStats:
    """Tests for /mua/v6/stats endpoint."""

    @patch("mira.miul.mua_faiss_search.MUAFAISSSearch")
    def test_stats_endpoint_returns_structure(self, mock_search_class, client):
        """Stats endpoint returns health info structure."""
        # Mock FAISS search
        mock_search = MagicMock()
        mock_search.metadata = [1, 2, 3]  # Pretend 3 items
        mock_search_class.return_value = mock_search

        response = client.get("/mua/v6/stats")
        assert response.status_code == 200
        data = response.json()
        assert "faiss_index_size" in data
        assert "material_resolver_available" in data
        assert "logic_validator_available" in data

    @patch("mira.miul.mua_faiss_search.MUAFAISSSearch")
    def test_stats_faiss_error_handled(self, mock_search_class, client):
        """Stats endpoint handles FAISS load failure gracefully."""
        mock_search_class.side_effect = Exception("FAISS load failed")

        response = client.get("/mua/v6/stats")
        assert response.status_code == 200
        data = response.json()
        # Should return 0 for index size on error
        assert data["faiss_index_size"] == 0


class TestRequestValidation:
    """Tests for request validation."""

    def test_material_min_length(self, client):
        """Material must have at least 1 character."""
        response = client.post(
            "/mua/v6/precedents/search",
            json={"material": ""},
        )
        assert response.status_code == 422

    def test_k_max_limit(self, client):
        """k must be <= 50."""
        response = client.post(
            "/mua/v6/precedents/search",
            json={"material": "Test", "k": 100},
        )
        assert response.status_code == 422

    def test_o2_percent_range(self, client):
        """o2_percent must be 0-100."""
        response = client.post(
            "/mua/v6/precedents/search",
            json={
                "material": "Test",
                "environment": {
                    "description": "Test",
                    "o2_percent": 150.0,
                },
            },
        )
        assert response.status_code == 422


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
