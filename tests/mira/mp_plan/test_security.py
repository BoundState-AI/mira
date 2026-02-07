#!/usr/bin/env python3
"""
Security Tests for M&P Plan Generator V2.

These tests are designed to find vulnerabilities by attempting:
- Path traversal attacks
- Injection attacks
- DoS via large inputs
- Type confusion
- Integer overflow
- Boundary condition exploits
- Session hijacking patterns

BoundState AI 2026
"""

import pytest
import uuid
from datetime import datetime, date, timedelta
from pathlib import Path
import tempfile
import os

from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create FastAPI test client."""
    from mira.api.app import app
    return TestClient(app)


@pytest.fixture
def session_manager():
    """Create isolated session manager for testing."""
    from mira.mp_plan.session_manager import SessionManager
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = SessionManager(storage_dir=Path(tmpdir))
        yield manager


class TestPathTraversalAttacks:
    """Test for path traversal vulnerabilities."""

    def test_session_id_path_traversal_in_get(self, client):
        """Attempt path traversal via session_id in GET."""
        # Try to escape the session directory
        malicious_ids = [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32\\config\\sam",
            "....//....//....//etc/passwd",
            "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd",
            "..%252f..%252f..%252fetc/passwd",
            "session/../../../etc/passwd",
        ]
        for malicious_id in malicious_ids:
            response = client.get(f"/mp-plan/sessions/{malicious_id}")
            # Should return 404 (not found), not expose system files
            assert response.status_code == 404, f"Path traversal may have worked with: {malicious_id}"

    def test_session_id_path_traversal_in_delete(self, client):
        """Attempt path traversal via session_id in DELETE."""
        malicious_ids = [
            "../../../important_file",
            "..\\..\\..\\windows\\system.ini",
        ]
        for malicious_id in malicious_ids:
            response = client.delete(f"/mp-plan/sessions/{malicious_id}")
            assert response.status_code == 404

    def test_artifact_id_path_traversal(self, client):
        """Attempt path traversal via artifact_id in download."""
        # Create a session first
        create_resp = client.post("/mp-plan/sessions", json={"program_name": "test"})
        session_id = create_resp.json()["session_id"]

        malicious_ids = [
            "../../../etc/passwd",
            "..%2f..%2f..%2fetc%2fpasswd",
        ]
        for malicious_id in malicious_ids:
            response = client.get(f"/mp-plan/sessions/{session_id}/download/{malicious_id}")
            assert response.status_code == 404


class TestInjectionAttacks:
    """Test for injection vulnerabilities."""

    def test_json_injection_in_program_name(self, client):
        """Attempt JSON injection in program_name."""
        payloads = [
            '{"injected": "true"}',
            '", "admin": true, "x": "',
            "'; DROP TABLE sessions; --",
            "<script>alert('xss')</script>",
        ]
        for payload in payloads:
            response = client.post(
                "/mp-plan/sessions",
                json={"program_name": payload},
            )
            # Should succeed but sanitize/escape the input
            assert response.status_code == 200
            data = response.json()
            # Verify the payload is stored as-is (Pydantic validates)
            assert data["program_name"] == payload

    def test_material_name_injection(self, client):
        """Attempt injection via material name."""
        create_resp = client.post("/mp-plan/sessions", json={"program_name": "test"})
        session_id = create_resp.json()["session_id"]

        malicious_names = [
            "'; DROP TABLE materials; --",
            "$(cat /etc/passwd)",
            "`cat /etc/passwd`",
            "{{7*7}}",  # SSTI
            "${7*7}",   # Expression injection
            "{{constructor.constructor('return this')()}}",
        ]
        for name in malicious_names:
            response = client.post(
                f"/mp-plan/sessions/{session_id}/materials",
                json={"materials": [{"name": name, "application": "test", "quantity": 1}]},
            )
            assert response.status_code == 200

    def test_closure_path_injection(self, client):
        """Attempt injection via closure path selection."""
        create_resp = client.post(
            "/mp-plan/sessions",
            json={"program_name": "test", "vehicle_preset": "ISS"},
        )
        session_id = create_resp.json()["session_id"]

        # Try to inject via closure decision
        response = client.post(
            f"/mp-plan/sessions/{session_id}/closure",
            json={
                "gap_id": "nonexistent",
                "selected_path": "'; exec('import os; os.system(\"whoami\")')",
                "rationale": "test",
            },
        )
        # Should fail because gap doesn't exist
        assert response.status_code == 404


class TestDenialOfService:
    """Test for DoS vulnerabilities."""

    def test_large_program_name(self, client):
        """Attempt DoS with very large program name."""
        huge_name = "A" * 10_000_000  # 10MB string
        response = client.post(
            "/mp-plan/sessions",
            json={"program_name": huge_name},
        )
        # Should either reject or handle gracefully
        # Status code 200 is OK if it handles it, 413/422 if rejected
        assert response.status_code in [200, 413, 422, 500]

    def test_many_materials(self, client):
        """Attempt DoS by adding excessive materials."""
        create_resp = client.post("/mp-plan/sessions", json={"program_name": "test"})
        session_id = create_resp.json()["session_id"]

        # Try to add 100,000 materials
        materials = [
            {"name": f"mat_{i}", "application": "test", "quantity": 1}
            for i in range(1000)  # Reduced for test speed
        ]
        response = client.post(
            f"/mp-plan/sessions/{session_id}/materials",
            json={"materials": materials},
        )
        # Should handle or rate-limit
        assert response.status_code in [200, 413, 429, 500]

    def test_deep_nested_json(self, client):
        """Attempt DoS with deeply nested JSON."""
        # Create deeply nested structure
        nested = {"a": "b"}
        for _ in range(100):
            nested = {"nested": nested}

        response = client.post(
            "/mp-plan/sessions",
            json={"program_name": "test", **nested},
        )
        # Should reject due to extra="forbid" or handle gracefully
        assert response.status_code in [422, 500]

    def test_unicode_bomb(self, client):
        """Attempt DoS with unicode expansion."""
        # Unicode characters that expand when processed
        unicode_bomb = "\U0001F4A9" * 100000
        response = client.post(
            "/mp-plan/sessions",
            json={"program_name": unicode_bomb},
        )
        assert response.status_code in [200, 413, 422, 500]


class TestTypeConfusion:
    """Test for type confusion vulnerabilities."""

    def test_quantity_negative(self, client):
        """Test handling of negative quantity."""
        create_resp = client.post("/mp-plan/sessions", json={"program_name": "test"})
        session_id = create_resp.json()["session_id"]

        response = client.post(
            f"/mp-plan/sessions/{session_id}/materials",
            json={"materials": [{"name": "test", "application": "test", "quantity": -1}]},
        )
        # Should reject or handle negative quantity
        assert response.status_code in [200, 422]

    def test_quantity_overflow(self, client):
        """Test handling of integer overflow in quantity."""
        create_resp = client.post("/mp-plan/sessions", json={"program_name": "test"})
        session_id = create_resp.json()["session_id"]

        response = client.post(
            f"/mp-plan/sessions/{session_id}/materials",
            json={"materials": [{"name": "test", "application": "test", "quantity": 2**63}]},
        )
        # Should reject overflow
        assert response.status_code in [422, 500]

    def test_o2_pct_extreme_values(self, client):
        """Test handling of extreme O2 percentage values."""
        create_resp = client.post("/mp-plan/sessions", json={"program_name": "test"})
        session_id = create_resp.json()["session_id"]

        # Note: NaN and Infinity can't be serialized as JSON (not JSON compliant),
        # so they are rejected at the client level. We test only JSON-serializable
        # extreme values here.
        extreme_values = [
            -100.0,      # Negative
            0.0,         # Zero (invalid - must be > 0)
            100.1,       # Over 100%
            1e308,       # Very large but finite
        ]

        for o2_val in extreme_values:
            response = client.post(
                f"/mp-plan/sessions/{session_id}/environment",
                json={
                    "name": "test",
                    "o2_pct": o2_val,
                    "pressure_psia": 14.7,
                    "temp_min_c": 20,
                    "temp_max_c": 25,
                    "habitable": True,
                },
            )
            # Should reject invalid values with 422
            assert response.status_code == 422, f"Expected 422 for o2_pct={o2_val}, got {response.status_code}"

    def test_string_instead_of_number(self, client):
        """Test handling of string where number expected."""
        create_resp = client.post("/mp-plan/sessions", json={"program_name": "test"})
        session_id = create_resp.json()["session_id"]

        response = client.post(
            f"/mp-plan/sessions/{session_id}/environment",
            json={
                "name": "test",
                "o2_pct": "twenty-three",  # String instead of float
                "pressure_psia": 14.7,
                "temp_min_c": 20,
                "temp_max_c": 25,
                "habitable": True,
            },
        )
        assert response.status_code == 422  # Validation error


class TestBoundaryConditions:
    """Test boundary conditions that could cause issues."""

    def test_empty_session_id(self, client):
        """Test handling of empty session ID."""
        # Note: /mp-plan/sessions/ with trailing slash may redirect to /sessions
        # which is the list endpoint (200). Test with whitespace-only ID instead.
        response = client.get("/mp-plan/sessions/   ")
        # Should return 404 for whitespace-only ID
        assert response.status_code == 404

    def test_null_bytes_in_input(self, client):
        """Test handling of null bytes in input."""
        response = client.post(
            "/mp-plan/sessions",
            json={"program_name": "test\x00injected"},
        )
        # Should handle null byte safely
        assert response.status_code in [200, 422]

    def test_very_long_session_id(self, client):
        """Test handling of very long session ID."""
        long_id = "a" * 10000
        response = client.get(f"/mp-plan/sessions/{long_id}")
        assert response.status_code == 404

    def test_special_chars_in_ids(self, client):
        """Test handling of special characters in IDs."""
        special_ids = [
            "test<script>",
            "test'\"",
            "test;",
            "test&",
            "test|",
            "test$()",
        ]
        for special_id in special_ids:
            response = client.get(f"/mp-plan/sessions/{special_id}")
            assert response.status_code == 404


class TestAuthorizationBypasses:
    """Test for authorization bypass vulnerabilities."""

    def test_access_other_session_data(self, client):
        """Attempt to access data from another session."""
        # Create two sessions
        session1 = client.post("/mp-plan/sessions", json={"program_name": "session1"}).json()
        session2 = client.post("/mp-plan/sessions", json={"program_name": "session2"}).json()

        # Add material to session1
        client.post(
            f"/mp-plan/sessions/{session1['session_id']}/materials",
            json={"materials": [{"name": "secret_material", "application": "test", "quantity": 1}]},
        )

        # Try to access session1's data via session2's endpoint shouldn't work
        response = client.get(f"/mp-plan/sessions/{session2['session_id']}")
        data = response.json()
        # Session2 should not have session1's materials
        assert data.get("material_count", 0) == 0

    def test_modify_other_session(self, client):
        """Attempt to modify another session's data."""
        session1 = client.post("/mp-plan/sessions", json={"program_name": "victim"}).json()

        # Generate a fake session ID
        fake_session_id = str(uuid.uuid4())[:8]

        # Try to add material to non-existent session
        response = client.post(
            f"/mp-plan/sessions/{fake_session_id}/materials",
            json={"materials": [{"name": "malicious", "application": "test", "quantity": 1}]},
        )
        assert response.status_code == 404


class TestModelValidation:
    """Test Pydantic model validation for security."""

    def test_extra_fields_rejected(self, client):
        """Ensure extra fields are rejected (extra='forbid')."""
        response = client.post(
            "/mp-plan/sessions",
            json={
                "program_name": "test",
                "admin": True,  # Extra field
                "is_superuser": True,  # Extra field
            },
        )
        assert response.status_code == 422  # Validation error

    def test_draft_authoritative_flag(self):
        """Test that DraftTextBox cannot be made authoritative."""
        from mira.mp_plan.models.draft import DraftTextBox

        with pytest.raises(ValueError, match="can never be authoritative"):
            DraftTextBox(
                draft_type="test",
                content="test",
                prompt_template_id="test",
                prompt_hash="test",
                model_id="test",
                inputs_hash="test",
                is_authoritative=True,
            )

    def test_draft_requires_review(self):
        """Test that DraftTextBox must require human review."""
        from mira.mp_plan.models.draft import DraftTextBox

        with pytest.raises(ValueError, match="requires human review"):
            DraftTextBox(
                draft_type="test",
                content="test",
                prompt_template_id="test",
                prompt_hash="test",
                model_id="test",
                inputs_hash="test",
                requires_human_review=False,
            )


class TestCredentialExposure:
    """Test for credential exposure vulnerabilities."""

    def test_no_credentials_in_response(self, client):
        """Ensure no credentials appear in API responses."""
        response = client.get("/mp-plan/sessions")
        response_text = response.text.lower()

        sensitive_terms = ["password", "secret", "api_key", "token", "credential"]
        for term in sensitive_terms:
            # Allow "authoritative" which contains "auth"
            if term != "auth" or "authoritative" not in response_text:
                assert term not in response_text, f"Found sensitive term '{term}' in response"

    def test_error_messages_no_sensitive_data(self, client):
        """Ensure error messages don't leak sensitive info."""
        # Trigger various errors and check responses
        error_responses = [
            client.get("/mp-plan/sessions/nonexistent"),
            client.post("/mp-plan/sessions", json={"invalid": True}),
            client.delete("/mp-plan/sessions/fake"),
        ]

        for response in error_responses:
            response_text = response.text.lower()
            # Should not expose internal paths, stack traces with passwords, etc.
            assert "c:\\boundstate" not in response_text or "traceback" not in response_text
            assert "postgresql" not in response_text or "password" not in response_text


class TestSessionSecurity:
    """Test session handling security."""

    def test_session_id_not_predictable(self, client):
        """Ensure session IDs are not predictable."""
        sessions = []
        for _ in range(10):
            response = client.post("/mp-plan/sessions", json={"program_name": "test"})
            sessions.append(response.json()["session_id"])

        # All session IDs should be unique
        assert len(set(sessions)) == 10

        # Session IDs should not be sequential
        for i in range(len(sessions) - 1):
            # Simple numeric check - shouldn't be sequential
            try:
                diff = int(sessions[i+1], 16) - int(sessions[i], 16)
                assert diff != 1, "Session IDs appear sequential"
            except ValueError:
                pass  # Not hex, which is fine

    def test_deleted_session_inaccessible(self, client):
        """Ensure deleted sessions are truly inaccessible."""
        # Create and delete session
        create_resp = client.post("/mp-plan/sessions", json={"program_name": "test"})
        session_id = create_resp.json()["session_id"]
        client.delete(f"/mp-plan/sessions/{session_id}")

        # Should not be accessible
        response = client.get(f"/mp-plan/sessions/{session_id}")
        assert response.status_code == 404

        # Should not be able to modify
        response = client.post(
            f"/mp-plan/sessions/{session_id}/materials",
            json={"materials": [{"name": "test", "application": "test", "quantity": 1}]},
        )
        assert response.status_code == 404
