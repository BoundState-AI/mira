#!/usr/bin/env python3
"""
Module: Test Query Endpoint
Purpose: Tests for Query page API endpoints.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-CSET, SWE-013
Safety Critical: True
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch


@pytest.fixture
def client():
    """Create test client for API."""
    from mira.api.app import app
    return TestClient(app)


class TestQueryEndpoint:
    """Tests for /api/search semantic search endpoint."""

    def test_search_returns_results(self, client):
        """Search for common material returns results."""
        response = client.post(
            "/api/search",
            json={"query": "stainless steel", "top_k": 10}
        )
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert "total" in data
        assert isinstance(data["results"], list)

    def test_search_with_polymer_query(self, client):
        """Search for polymers returns polymer materials."""
        response = client.post(
            "/api/search",
            json={"query": "PTFE polymer", "top_k": 5}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 0

    def test_search_empty_query_rejected(self, client):
        """Empty query is rejected with 422."""
        response = client.post(
            "/api/search",
            json={"query": "", "top_k": 10}
        )
        assert response.status_code == 422

    def test_search_top_k_limit(self, client):
        """top_k parameter limits results."""
        response = client.post(
            "/api/search",
            json={"query": "aluminum", "top_k": 3}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) <= 3

    def test_search_result_has_material_fields(self, client):
        """Search results include required material fields."""
        response = client.post(
            "/api/search",
            json={"query": "titanium alloy", "top_k": 1}
        )
        assert response.status_code == 200
        data = response.json()
        if data["results"]:
            result = data["results"][0]
            assert "material_key" in result
            assert "score" in result

    def test_search_default_top_k(self, client):
        """Search uses default top_k when not specified."""
        response = client.post(
            "/api/search",
            json={"query": "copper"}
        )
        assert response.status_code == 200
        data = response.json()
        # Default is 25
        assert len(data["results"]) <= 25

    def test_search_returns_coming_soon_when_semantic_unavailable(self, client):
        """Search falls back to a graceful coming-soon payload when MAPTIS search is offline."""
        with patch("mira.api.routers.ui_endpoints.get_semantic_search", return_value=None):
            response = client.post(
                "/api/search",
                json={"query": "stainless steel", "top_k": 10}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["results"] == []
        assert data["pipeline"] == "coming_soon"
        assert "coming soon" in data["message"].lower()


__safety_critical__ = True
