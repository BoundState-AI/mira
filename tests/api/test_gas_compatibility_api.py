#!/usr/bin/env python3
"""
Module: Test Gas Compatibility Api
Purpose: API Integration Tests for Gas Compatibility Endpoints

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


client = TestClient(app)


# =============================================================================
# O2 API TESTS - POST /mira/o2/compatibility
# =============================================================================

class TestO2CompatibilityAPI:
    """Integration tests for the O2 compatibility endpoint."""

    def test_o2_endpoint_exists(self):
        """The O2 compatibility endpoint should be reachable."""
        response = client.post(
            "/mira/o2/compatibility",
            json={
                "question": "Test question",
                "material_key": "SS 316",
                "pressure_psia": 500,
                "temperature_k": 300,
                "phase": "gox",
            },
        )
        # Should get 200 or a proper error, not 404
        assert response.status_code != 404

    def test_o2_titanium_prohibited(self):
        """Titanium in GOX should return PROHIBITED via API."""
        response = client.post(
            "/mira/o2/compatibility",
            json={
                "question": "Is titanium compatible with GOX?",
                "material_key": "Ti-6Al-4V",
                "pressure_psia": 200,
                "temperature_k": 300,
                "phase": "gox",
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert data["classification"] == "prohibited", (
            f"Ti in GOX should be PROHIBITED, got {data['classification']}"
        )
        assert "rationale" in data
        assert len(data.get("evidence", [])) > 0

    def test_o2_ss316_approved(self):
        """SS 316 in GOX should return OK (approved) via API."""
        response = client.post(
            "/mira/o2/compatibility",
            json={
                "question": "Is SS 316 compatible with GOX?",
                "material_key": "SS 316",
                "pressure_psia": 500,
                "temperature_k": 300,
                "phase": "gox",
            },
        )
        assert response.status_code == 200
        data = response.json()

        # SS 316 should be OK or CAUTION, definitely not PROHIBITED
        assert data["classification"] in ["ok", "caution"], (
            f"SS 316 should be approved for GOX, got {data['classification']}"
        )

    def test_o2_al6061_gox_200psia_prohibited(self):
        """AL 6061 at 200 psia GOX should return PROHIBITED (the 6061 bug fix)."""
        response = client.post(
            "/mira/o2/compatibility",
            json={
                "question": "Is AL 6061-T6 compatible with GOX at 200 psia?",
                "material_key": "AL 6061-T6",
                "pressure_psia": 200,
                "temperature_k": 300,
                "phase": "gox",
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert data["classification"] == "prohibited", (
            f"AL 6061 at 200 psia GOX should be PROHIBITED, got {data['classification']}. "
            "This is the critical 6061 bug regression guard."
        )

    def test_o2_response_has_evidence(self):
        """O2 API responses should include evidence items."""
        response = client.post(
            "/mira/o2/compatibility",
            json={
                "question": "Test evidence",
                "material_key": "Inconel 625",
                "pressure_psia": 3000,
                "temperature_k": 350,
                "phase": "gox",
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert "evidence" in data
        assert len(data["evidence"]) > 0
        assert "source_id" in data["evidence"][0]


# =============================================================================
# H2 API TESTS - POST /mira/h2/compatibility
# =============================================================================

class TestH2CompatibilityAPI:
    """Integration tests for the H2 compatibility endpoint."""

    def test_h2_endpoint_exists(self):
        """The H2 compatibility endpoint should be reachable."""
        response = client.post(
            "/mira/h2/compatibility",
            json={
                "question": "Test question",
                "material_key": "SS 316",
                "pressure_psia": 5000,
                "temperature_k": 300,
                "phase": "gh2",
            },
        )
        # Should get 200 or a proper error, not 404
        assert response.status_code != 404

    def test_h2_ss316_approved(self):
        """SS 316 in GH2 should return OK (approved) via API."""
        response = client.post(
            "/mira/h2/compatibility",
            json={
                "question": "Is SS 316 compatible with hydrogen?",
                "material_key": "SS 316",
                "pressure_psia": 5000,
                "temperature_k": 300,
                "phase": "gh2",
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert data["classification"] == "ok", (
            f"SS 316 should be APPROVED for H2, got {data['classification']}"
        )
        assert data.get("embrittlement_risk") in ["low", "very_low", None]

    def test_h2_inconel_625_caution(self):
        """Inconel 625 in high-pressure H2 should return CAUTION via API."""
        response = client.post(
            "/mira/h2/compatibility",
            json={
                "question": "Is Inconel 625 compatible with high-pressure hydrogen?",
                "material_key": "Inconel 625",
                "pressure_psia": 10000,
                "temperature_k": 350,
                "phase": "gh2",
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert data["classification"] == "caution", (
            f"Inconel 625 should be CAUTION for H2, got {data['classification']}"
        )
        assert data.get("embrittlement_risk") == "medium"

    def test_h2_high_strength_steel_prohibited(self):
        """High-strength steel (>150 ksi) should return PROHIBITED via API."""
        response = client.post(
            "/mira/h2/compatibility",
            json={
                "question": "Is high-strength steel compatible with hydrogen?",
                "material_key": "AISI 4340",
                "pressure_psia": 5000,
                "temperature_k": 300,
                "phase": "gh2",
                "yield_strength_ksi": 180.0,
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert data["classification"] == "prohibited", (
            f"High-strength steel should be PROHIBITED for H2, got {data['classification']}"
        )
        assert data.get("embrittlement_risk") == "severe"

    def test_h2_titanium_elevated_temp_prohibited(self):
        """Titanium at elevated temp (>300F) should return PROHIBITED via API."""
        response = client.post(
            "/mira/h2/compatibility",
            json={
                "question": "Is Ti-6Al-4V compatible with hot hydrogen?",
                "material_key": "Ti-6Al-4V",
                "pressure_psia": 2000,
                "temperature_k": 450,  # ~350F - above hydride limit
                "phase": "gh2",
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert data["classification"] == "prohibited", (
            f"Ti at elevated temp should be PROHIBITED for H2, got {data['classification']}"
        )

    def test_h2_response_has_evidence(self):
        """H2 API responses should include evidence items."""
        response = client.post(
            "/mira/h2/compatibility",
            json={
                "question": "Test evidence",
                "material_key": "Monel 400",
                "pressure_psia": 5000,
                "temperature_k": 300,
                "phase": "gh2",
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert "evidence" in data
        assert len(data["evidence"]) > 0
        assert "source_id" in data["evidence"][0]


# =============================================================================
# PING / HEALTH CHECK
# =============================================================================

class TestMiraHealthCheck:
    """Basic health check tests."""

    def test_mira_ping(self):
        """MIRA ping endpoint should return OK."""
        response = client.get("/mira/ping")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["domain"] == "mira"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
