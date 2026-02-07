#!/usr/bin/env python3
"""
Module: Test Knowledge Twins Endpoint
Purpose: Tests for Knowledge Twins page API endpoints.

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


class TestHybridQuery:
    """Tests for hybrid query endpoint used by Knowledge Twins."""

    def test_h2_query_basic(self, client):
        """Query H2 compatibility for a material."""
        response = client.post(
            "/api/query/hybrid",
            json={
                "query": "Is 316 stainless steel compatible with hydrogen?",
                "enable_semantic": True
            }
        )
        # Should return query result or 503 if engine not loaded
        assert response.status_code in [200, 503]
        if response.status_code == 200:
            data = response.json()
            assert "status" in data
            assert "query" in data

    def test_o2_query_basic(self, client):
        """Query O2 compatibility for a material."""
        response = client.post(
            "/api/query/hybrid",
            json={
                "query": "Is aluminum compatible with oxygen at 3000 psi?",
                "enable_semantic": True
            }
        )
        assert response.status_code in [200, 503]
        if response.status_code == 200:
            data = response.json()
            assert "status" in data

    def test_query_with_pressure(self, client):
        """Query includes pressure constraint."""
        response = client.post(
            "/api/query/hybrid",
            json={
                "query": "titanium hydrogen 5000 psi compatibility",
                "enable_semantic": True
            }
        )
        assert response.status_code in [200, 503]

    def test_query_empty_rejected(self, client):
        """Empty query is rejected."""
        response = client.post(
            "/api/query/hybrid",
            json={"query": ""}
        )
        assert response.status_code == 422

    def test_query_response_structure(self, client):
        """Query response has expected structure."""
        response = client.post(
            "/api/query/hybrid",
            json={
                "query": "inconel 718 hydrogen compatibility",
                "enable_semantic": True
            }
        )
        if response.status_code == 200:
            data = response.json()
            # Check expected response fields
            assert "status" in data
            assert "query" in data
            assert "evidence_summary" in data


class TestHybridQueryH2:
    """Tests specific to H2 queries."""

    def test_h2_hee_query(self, client):
        """Query for HEE index."""
        response = client.post(
            "/api/query/hybrid",
            json={
                "query": "What is the HEE index for 304 stainless steel in hydrogen?",
                "enable_semantic": True
            }
        )
        assert response.status_code in [200, 503]

    def test_h2_embrittlement_query(self, client):
        """Query for embrittlement susceptibility."""
        response = client.post(
            "/api/query/hybrid",
            json={
                "query": "Is Monel K-500 susceptible to hydrogen embrittlement?",
                "enable_semantic": True
            }
        )
        assert response.status_code in [200, 503]


class TestHybridQueryO2:
    """Tests specific to O2 queries."""

    def test_o2_flammability_query(self, client):
        """Query for flammability rating in oxygen."""
        response = client.post(
            "/api/query/hybrid",
            json={
                "query": "What is the oxygen flammability rating for PTFE?",
                "enable_semantic": True
            }
        )
        assert response.status_code in [200, 503]

    def test_o2_ignition_query(self, client):
        """Query for ignition mechanisms in oxygen."""
        response = client.post(
            "/api/query/hybrid",
            json={
                "query": "What ignition mechanisms apply to aluminum in oxygen?",
                "enable_semantic": True
            }
        )
        assert response.status_code in [200, 503]


class TestQueryHealth:
    """Tests for query engine health endpoints."""

    def test_hybrid_query_router_accessible(self, client):
        """Hybrid query router is properly mounted."""
        response = client.post("/api/query/hybrid", json={})
        # Should get validation error (422) or engine unavailable (503), not 404
        assert response.status_code in [422, 503]

    def test_query_health_endpoint(self, client):
        """Query health endpoint is accessible."""
        response = client.get("/api/query/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "query_engine" in data

    def test_query_examples_endpoint(self, client):
        """Query examples endpoint is accessible."""
        response = client.get("/api/query/examples")
        assert response.status_code == 200
        data = response.json()
        assert "examples" in data
        assert isinstance(data["examples"], list)

    def test_ui_health_endpoint(self, client):
        """UI health endpoint is accessible."""
        response = client.get("/api/ui/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data


__safety_critical__ = True
