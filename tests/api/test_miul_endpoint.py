#!/usr/bin/env python3
"""
Module: Test Miul Endpoint
Purpose: Tests for MIUL Builder page API endpoints.

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


class TestMIULHealth:
    """Tests for MIUL service health."""

    def test_miul_ping(self, client):
        """MIUL ping endpoint responds."""
        response = client.get("/miul/ping")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["domain"] == "miul"

    def test_miul_router_accessible(self, client):
        """MIUL router is properly mounted."""
        response = client.post("/miul/extract-dt")
        # Should get validation error (422) for missing files, not 404 (router not found)
        assert response.status_code == 422


class TestMIULFastExtract:
    """Tests for Drawing Tree extraction endpoint."""

    def test_fast_extract_requires_files(self, client):
        """DT extraction requires an uploaded PDF."""
        response = client.post("/miul/extract-dt")
        assert response.status_code == 422

    def test_fast_extract_rejects_non_pdf(self, client):
        """DT extraction rejects non-PDF files."""
        # Create a fake text file
        fake_file = BytesIO(b"This is not a PDF")
        response = client.post(
            "/miul/extract-dt",
            files={"dt_file": ("test.txt", fake_file, "text/plain")},
        )
        assert response.status_code == 400


class TestMIULEnrich:
    """Tests for MIUL enrichment endpoint."""

    def test_enrich_requires_file(self, client):
        """Enrich endpoint requires Excel file."""
        response = client.post("/miul/enrich")
        assert response.status_code == 422

    def test_enrich_rejects_non_excel(self, client):
        """Enrich endpoint rejects non-Excel files."""
        fake_file = BytesIO(b"This is not an Excel file")
        response = client.post(
            "/miul/enrich",
            files={"file": ("test.txt", fake_file, "text/plain")},
        )
        assert response.status_code == 400


class TestMIULGaps:
    """Tests for MIUL rating gaps endpoint."""

    def test_gaps_requires_file(self, client):
        """Gaps endpoint requires Excel file."""
        response = client.get("/miul/gaps")
        # GET endpoint expects file parameter
        assert response.status_code == 422


class TestMIULMSFCExtract:
    """Tests for current MIUL drawing-tree extraction endpoint."""

    def test_msfc_requires_files(self, client):
        """DT extract requires an uploaded file."""
        response = client.post("/miul/extract-dt")
        assert response.status_code == 422


class TestMIULDMLLVExtract:
    """Tests for MIUL DT extraction parameter validation."""

    def test_dmllv_requires_files(self, client):
        """DT extraction requires the uploaded PDF even when optional form fields are omitted."""
        response = client.post("/miul/extract-dt")
        assert response.status_code == 422


__safety_critical__ = True
