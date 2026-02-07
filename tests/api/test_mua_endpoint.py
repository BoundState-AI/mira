#!/usr/bin/env python3
"""
Module: Test Mua Endpoint
Purpose: Tests for MUA Generator page API endpoints.

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
from io import BytesIO


@pytest.fixture
def client():
    """Create test client for API."""
    from mira.api.app import app
    return TestClient(app)


class TestMUAHealth:
    """Tests for MUA service health."""

    def test_mua_ping(self, client):
        """MUA ping endpoint responds."""
        response = client.get("/mua/ping")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["domain"] == "mua"

    def test_mua_router_accessible(self, client):
        """MUA router is properly mounted."""
        # Verify router responds to POST generate-batch (even without file)
        response = client.post("/mua/generate-batch")
        # Should get validation error (422) for missing file, not 404 (router not found)
        assert response.status_code == 422


class TestMUAGenerateBatch:
    """Tests for batch MUA generation endpoint."""

    def test_generate_batch_requires_file(self, client):
        """Generate batch requires Excel file."""
        response = client.post("/mua/generate-batch")
        assert response.status_code == 422

    def test_generate_batch_rejects_non_excel(self, client):
        """Generate batch rejects non-Excel files."""
        fake_file = BytesIO(b"This is not an Excel file")
        response = client.post(
            "/mua/generate-batch",
            files={"file": ("test.txt", fake_file, "text/plain")},
        )
        assert response.status_code == 400


class TestMUAGenerateBatchExcel:
    """Tests for batch MUA generation with Excel output."""

    def test_generate_excel_requires_file(self, client):
        """Generate batch Excel requires file."""
        response = client.post("/mua/generate-batch-excel")
        assert response.status_code == 422


class TestMUABOKFind:
    """Tests for MUA BOK precedent search."""

    def test_bok_find_basic(self, client):
        """Search BOK for precedents."""
        response = client.post(
            "/mua/bok/find",
            json={"material": "316 SS", "issues": ["CORR"], "k": 5}
        )
        # Should return results or 503 if BOK not loaded
        assert response.status_code in [200, 503]
        if response.status_code == 200:
            data = response.json()
            assert "precedents" in data
            assert "count" in data

    def test_bok_find_multiple_issues(self, client):
        """Search BOK for multiple issues."""
        response = client.post(
            "/mua/bok/find",
            json={"material": "Inconel 625", "issues": ["SCC", "CORR"], "k": 10}
        )
        assert response.status_code in [200, 503]

    def test_bok_find_requires_material(self, client):
        """BOK find requires material parameter."""
        response = client.post(
            "/mua/bok/find",
            json={"issues": ["CORR"]}
        )
        assert response.status_code == 422


class TestMUABOKGenerateFromSelection:
    """Tests for MUA generation from selected precedents."""

    def test_generate_from_selection_requires_fields(self, client):
        """Generate from selection requires material and selections."""
        response = client.post(
            "/mua/bok/generate-from-selection",
            json={}
        )
        assert response.status_code == 422

    def test_generate_from_selection_requires_precedents(self, client):
        """Generate from selection requires at least one precedent."""
        response = client.post(
            "/mua/bok/generate-from-selection",
            json={
                "material": "316 SS",
                "issues": {"CORR": "B"},
                "selected_precedent_ids": []
            }
        )
        # Should return 400 for empty selections or 503 if engine not loaded
        assert response.status_code in [400, 422, 503]


class TestMUABOKStats:
    """Tests for MUA BOK statistics endpoint."""

    def test_bok_stats(self, client):
        """Get BOK statistics."""
        response = client.get("/mua/bok/stats")
        # Should return stats or error if BOK not loaded
        assert response.status_code == 200
        data = response.json()
        assert "total_muas" in data


class TestMUABOKSynthesize:
    """Tests for MUA LLM synthesis endpoint."""

    def test_synthesize_requires_fields(self, client):
        """Synthesize requires material, issue, and application."""
        response = client.post(
            "/mua/bok/synthesize",
            json={}
        )
        assert response.status_code == 422

    def test_synthesize_basic(self, client):
        """Synthesize MUA for material."""
        response = client.post(
            "/mua/bok/synthesize",
            json={
                "material": "Nylon 6/6",
                "issue": "FLAM",
                "application": "Cable ties in avionics bay",
                "environment": "Ambient, <150F"
            }
        )
        # Should return synthesis result or 503 if synthesizer not available
        assert response.status_code in [200, 503]


class TestMUAPrecedentEvaluate:
    """Tests for tiered precedent evaluation endpoint."""

    def test_precedent_evaluate_requires_material(self, client):
        """Precedent evaluate requires material_name."""
        response = client.post(
            "/mua/bok/precedent/evaluate",
            json={}
        )
        assert response.status_code == 422

    def test_precedent_evaluate_basic(self, client):
        """Evaluate precedents for material."""
        response = client.post(
            "/mua/bok/precedent/evaluate",
            json={
                "material_name": "Inconel 625",
                "deviation_types": ["SCC", "CORR"],
                "k": 10
            }
        )
        # Should return evaluation or 503 if engine not available
        assert response.status_code in [200, 503]


__safety_critical__ = True
