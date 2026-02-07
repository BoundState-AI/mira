#!/usr/bin/env python3
"""
Module: Test Search Api
Purpose: Search API Tests for BoundState

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
boto3 = pytest.importorskip("boto3", reason="boto3 required for API tests")
import sys

sys.path.insert(0, r"C:\BoundState")

from fastapi.testclient import TestClient

from mira.api.app import app
from core.models.answer import AnswerSeverity


@pytest.fixture
def client():
    """Create test client for the BoundState API."""
    return TestClient(app)


class TestSearchEndpoint:
    """Tests for the /search endpoint."""

    def test_search_ping(self, client):
        """Search ping endpoint should return ok."""
        response = client.get("/search/ping")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_search_query_exists(self, client):
        """POST /search/query should exist and accept requests."""
        response = client.post(
            "/search/query",
            json={"question": "What materials are compatible with oxygen?"},
        )
        assert response.status_code == 200

    def test_search_query_returns_answer_structure(self, client):
        """Response should have proper EngineAnswer structure."""
        response = client.post(
            "/search/query",
            json={"question": "Find materials for hydrogen service"},
        )
        assert response.status_code == 200

        data = response.json()
        assert "answer" in data
        answer = data["answer"]

        # Should have all required EngineAnswer fields
        assert "classification" in answer
        assert "rationale" in answer
        assert "evidence" in answer

    def test_search_query_returns_unknown_classification(self, client):
        """Search endpoint should return UNKNOWN classification (not a compatibility check)."""
        response = client.post(
            "/search/query",
            json={"question": "SS316L oxygen compatibility"},
        )
        assert response.status_code == 200

        answer = response.json()["answer"]
        # Search returns UNKNOWN - use /mira/o2 or /mira/h2 for classifications
        assert answer["classification"] == AnswerSeverity.UNKNOWN.value

    def test_search_query_with_low_relevance_query(self, client):
        """Semantic search returns results even for unusual queries - verify structure.

        Note: With FAISS semantic search, there's no true "empty" result - vectors
        always have some similarity. The API should still return proper structure.
        """
        response = client.post(
            "/search/query",
            json={"question": "nonexistent material xyz123"},
        )
        assert response.status_code == 200

        answer = response.json()["answer"]
        # Evidence may be empty or contain low-relevance semantic matches
        assert isinstance(answer["evidence"], list)
        assert "rationale" in answer
        assert answer["classification"] == AnswerSeverity.UNKNOWN.value

    def test_search_query_with_filters(self, client):
        """Search should accept optional filters."""
        response = client.post(
            "/search/query",
            json={
                "question": "Find materials",
                "environment": "oxygen",
                "material_key": "SS316L",
                "top_k": 5,
            },
        )
        assert response.status_code == 200

    def test_search_query_validates_top_k(self, client):
        """top_k should be validated (1-100)."""
        # Too low
        response = client.post(
            "/search/query",
            json={"question": "test", "top_k": 0},
        )
        assert response.status_code == 422  # Validation error

        # Too high
        response = client.post(
            "/search/query",
            json={"question": "test", "top_k": 200},
        )
        assert response.status_code == 422


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
