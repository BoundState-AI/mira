#!/usr/bin/env python3
"""
Module: Test Gas Compatibility Endpoint
Purpose: Tests for Gas Compatibility page API endpoints.

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


@pytest.fixture
def client():
    """Create test client for API."""
    from mira.api.app import app
    return TestClient(app)


class TestO2BOKSearch:
    """Tests for O2 Body of Knowledge search endpoint."""

    def test_o2_bok_search_basic(self, client):
        """Search O2 BOK returns results."""
        response = client.post(
            "/api/v1/o2/search-bok",
            json={"query": "oxygen compatibility", "k": 5}
        )
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert "query" in data

    def test_o2_bok_search_metals(self, client):
        """Search O2 BOK for metals guidance."""
        response = client.post(
            "/api/v1/o2/search-bok",
            json={"query": "stainless steel oxygen", "k": 5}
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["results"], list)

    def test_o2_bok_search_ignition(self, client):
        """Search O2 BOK for ignition mechanisms."""
        response = client.post(
            "/api/v1/o2/search-bok",
            json={"query": "ignition mechanism particle impact", "k": 5}
        )
        assert response.status_code == 200

    def test_o2_bok_empty_query_rejected(self, client):
        """Empty query is rejected."""
        response = client.post(
            "/api/v1/o2/search-bok",
            json={"query": "", "k": 5}
        )
        assert response.status_code == 422


class TestH2BOKSearch:
    """Tests for H2 Body of Knowledge search endpoint."""

    def test_h2_bok_search_basic(self, client):
        """Search H2 BOK returns results."""
        response = client.post(
            "/api/v1/h2/search-bok",
            json={"query": "hydrogen embrittlement", "k": 5}
        )
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert "query" in data

    def test_h2_bok_search_alloys(self, client):
        """Search H2 BOK for alloy guidance."""
        response = client.post(
            "/api/v1/h2/search-bok",
            json={"query": "nickel alloys hydrogen", "k": 5}
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["results"], list)

    def test_h2_bok_search_hee(self, client):
        """Search H2 BOK for HEE index information."""
        response = client.post(
            "/api/v1/h2/search-bok",
            json={"query": "HEE index embrittlement", "k": 5}
        )
        assert response.status_code == 200

    def test_h2_bok_result_structure(self, client):
        """H2 BOK results have expected structure."""
        response = client.post(
            "/api/v1/h2/search-bok",
            json={"query": "hydrogen compatibility", "k": 1}
        )
        assert response.status_code == 200
        data = response.json()
        if data["results"]:
            result = data["results"][0]
            # Check expected fields
            assert "rank" in result
            assert "relevance_score" in result
            assert "text" in result


class TestBOKSearchCommon:
    """Common tests for both O2 and H2 BOK search."""

    @pytest.mark.parametrize("endpoint", [
        "/api/v1/o2/search-bok",
        "/api/v1/h2/search-bok"
    ])
    def test_k_parameter_limits_results(self, client, endpoint):
        """k parameter limits number of results."""
        response = client.post(
            endpoint,
            json={"query": "compatibility", "k": 3}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) <= 3

    @pytest.mark.parametrize("endpoint", [
        "/api/v1/o2/search-bok",
        "/api/v1/h2/search-bok"
    ])
    def test_default_k_value(self, client, endpoint):
        """Default k value is used when not specified."""
        response = client.post(
            endpoint,
            json={"query": "material safety"}
        )
        assert response.status_code == 200
        data = response.json()
        # Default k is 10
        assert len(data["results"]) <= 10


__safety_critical__ = True
