#!/usr/bin/env python3
"""
Tests for M&P Plan Generator V2 API endpoints.

BoundState AI 2026
"""

import pytest
from fastapi.testclient import TestClient


# Fixture to create test client
@pytest.fixture
def client():
    """Create FastAPI test client."""
    from mira.api.app import app
    return TestClient(app)


class TestHealthCheck:
    """Tests for health check endpoint."""

    def test_ping(self, client):
        """Test ping endpoint."""
        response = client.get("/mp-plan/ping")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["domain"] == "mp_plan"


class TestSessionManagement:
    """Tests for session CRUD endpoints."""

    def test_create_session(self, client):
        """Test creating a new session."""
        response = client.post(
            "/mp-plan/sessions",
            json={
                "program_name": "Test Program",
                "program_phase": "Development",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert data["program_name"] == "Test Program"
        assert data["can_generate"] is False

    def test_create_session_with_preset(self, client):
        """Test creating session with vehicle preset."""
        response = client.post(
            "/mp-plan/sessions",
            json={
                "program_name": "ISS Test",
                "vehicle_preset": "ISS",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["environment_count"] == 1

    def test_get_session(self, client):
        """Test getting session by ID."""
        # Create session first
        create_response = client.post(
            "/mp-plan/sessions",
            json={"program_name": "Get Test"},
        )
        session_id = create_response.json()["session_id"]

        # Get session
        response = client.get(f"/mp-plan/sessions/{session_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == session_id

    def test_get_nonexistent_session(self, client):
        """Test getting nonexistent session returns 404."""
        response = client.get("/mp-plan/sessions/nonexistent-id")
        assert response.status_code == 404

    def test_delete_session(self, client):
        """Test deleting a session."""
        # Create session first
        create_response = client.post(
            "/mp-plan/sessions",
            json={"program_name": "Delete Test"},
        )
        session_id = create_response.json()["session_id"]

        # Delete session
        response = client.delete(f"/mp-plan/sessions/{session_id}")
        assert response.status_code == 200
        assert response.json()["status"] == "deleted"

        # Verify deleted
        get_response = client.get(f"/mp-plan/sessions/{session_id}")
        assert get_response.status_code == 404

    def test_list_sessions(self, client):
        """Test listing all sessions."""
        # Create a session
        client.post(
            "/mp-plan/sessions",
            json={"program_name": "List Test"},
        )

        response = client.get("/mp-plan/sessions")
        assert response.status_code == 200
        data = response.json()
        assert "sessions" in data
        assert data["count"] >= 1


class TestDataEntry:
    """Tests for data entry endpoints."""

    def test_add_environment(self, client):
        """Test adding environment to session."""
        # Create session
        create_response = client.post(
            "/mp-plan/sessions",
            json={"program_name": "Env Test"},
        )
        session_id = create_response.json()["session_id"]

        # Add environment
        response = client.post(
            f"/mp-plan/sessions/{session_id}/environment",
            json={
                "name": "Custom Env",
                "o2_pct": 25.0,
                "pressure_psia": 14.7,
                "temp_min_c": 18.0,
                "temp_max_c": 27.0,
                "habitable": True,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Custom Env"
        assert data["o2_pct"] == 25.0

    def test_add_materials_batch(self, client):
        """Test adding multiple materials."""
        # Create session
        create_response = client.post(
            "/mp-plan/sessions",
            json={"program_name": "Mat Test"},
        )
        session_id = create_response.json()["session_id"]

        # Add materials
        response = client.post(
            f"/mp-plan/sessions/{session_id}/materials",
            json={
                "materials": [
                    {
                        "name": "Kapton",
                        "application": "Insulation",
                        "maptis_code": "KAPTON-001",
                    },
                    {
                        "name": "Viton",
                        "application": "O-Ring",
                    },
                ]
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2


class TestComputeLoop:
    """Tests for compute loop endpoints."""

    def test_get_blocking_questions(self, client):
        """Test getting blocking questions."""
        # Create empty session
        create_response = client.post(
            "/mp-plan/sessions",
            json={"program_name": "Question Test"},
        )
        session_id = create_response.json()["session_id"]

        # Get questions
        response = client.get(f"/mp-plan/sessions/{session_id}/questions")
        assert response.status_code == 200
        data = response.json()
        assert "questions" in data
        # Should have environment missing question
        assert data["count"] >= 1

    def test_submit_answer(self, client):
        """Test submitting answer to question."""
        # Create session
        create_response = client.post(
            "/mp-plan/sessions",
            json={"program_name": "Answer Test"},
        )
        session_id = create_response.json()["session_id"]

        # First get questions to populate blocking_questions
        questions_response = client.get(f"/mp-plan/sessions/{session_id}/questions")
        assert questions_response.status_code == 200
        questions = questions_response.json()["questions"]
        assert len(questions) > 0
        assert questions[0]["question_id"] == "env_missing"

        # Submit answer (environment selection)
        response = client.post(
            f"/mp-plan/sessions/{session_id}/answer",
            json={
                "question_id": "env_missing",
                "answer": "ISS",
                "rationale": "Standard ISS cabin environment",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "applied"

    def test_run_compute(self, client):
        """Test running compute loop."""
        # Create session with preset
        create_response = client.post(
            "/mp-plan/sessions",
            json={
                "program_name": "Compute Test",
                "vehicle_preset": "ISS",
            },
        )
        session_id = create_response.json()["session_id"]

        # Add a material
        client.post(
            f"/mp-plan/sessions/{session_id}/materials",
            json={
                "materials": [
                    {
                        "name": "Test Material",
                        "application": "Test",
                        "maptis_code": "TEST-001",
                    }
                ]
            },
        )

        # Run compute
        response = client.post(f"/mp-plan/sessions/{session_id}/compute")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "computed"


class TestGeneration:
    """Tests for artifact generation endpoints."""

    def test_generate_requires_complete_session(self, client):
        """Test that generation requires complete session."""
        # Create empty session
        create_response = client.post(
            "/mp-plan/sessions",
            json={"program_name": "Gen Test"},
        )
        session_id = create_response.json()["session_id"]

        # Try to generate (should fail)
        response = client.post(
            f"/mp-plan/sessions/{session_id}/generate",
            json={"artifacts": ["mp_plan_docx"]},
        )
        assert response.status_code == 400

    def test_get_review_packet(self, client):
        """Test getting review packet."""
        # Create session with preset and material
        create_response = client.post(
            "/mp-plan/sessions",
            json={
                "program_name": "Review Test",
                "vehicle_preset": "ISS",
            },
        )
        session_id = create_response.json()["session_id"]

        # Add material
        client.post(
            f"/mp-plan/sessions/{session_id}/materials",
            json={
                "materials": [
                    {
                        "name": "Review Material",
                        "application": "Test",
                        "maptis_code": "REVIEW-001",
                    }
                ]
            },
        )

        # Get review packet
        response = client.get(f"/mp-plan/sessions/{session_id}/review-packet")
        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert "key_findings" in data


class TestReferenceData:
    """Tests for reference data endpoints."""

    def test_list_policy_packs(self, client):
        """Test listing policy packs."""
        response = client.get("/mp-plan/policy-packs")
        assert response.status_code == 200
        data = response.json()
        assert "policy_packs" in data
        assert len(data["policy_packs"]) >= 1

    def test_list_vehicle_presets(self, client):
        """Test listing vehicle presets."""
        response = client.get("/mp-plan/vehicle-presets")
        assert response.status_code == 200
        data = response.json()
        assert "presets" in data
        # Should have ISS, HLS, etc.
        preset_ids = [p["preset_id"] for p in data["presets"]]
        assert "ISS" in preset_ids
        assert "HLS" in preset_ids
